from __future__ import annotations

import csv
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import RuntimeDb
from .registry import load_assets_from_upstream_result
from .schemas import CustomerAsset
from .source_trace import (
    DEFAULT_GIS_BASE_URL,
    DEFAULT_TRACE_DOWN_URL,
    ArcGisTraceClient,
    trace_downstream_peanos_for_device,
)
from .utils import normalize_device_id, normalize_feeder


OVERRIDE_COLUMNS = [
    "peano",
    "feeder",
    "device_type",
    "device_id",
    "mapping_field",
    "status",
    "source",
    "reason",
    "reviewed_by",
    "reviewed_at",
]

APPLY_AUDIT_COLUMNS = [
    "peano",
    "device_id",
    "mapping_field",
    "status",
    "action",
    "reason",
]


def build_private_protection_mapping_overrides(
    db_path: str | Path,
    source_trace_audit_csv: str | Path,
    output_csv: str | Path,
    *,
    registry_xlsx: str | Path | None = None,
    device_id: str | None = None,
    status: str = "pending",
    reviewed_by: str = "",
    reviewed_at: str | None = None,
    base_url: str = DEFAULT_GIS_BASE_URL,
    trace_url: str = DEFAULT_TRACE_DOWN_URL,
    timeout_seconds: float = 120.0,
    sleep_seconds: float = 0.35,
    client: ArcGisTraceClient | None = None,
) -> dict[str, Any]:
    assets = _load_assets(db_path, registry_xlsx)
    confident_assets = {asset.peano: asset for asset in assets if asset.confidence_eligible}
    candidates = _load_source_trace_candidates(source_trace_audit_csv, device_id=device_id)
    rows: list[dict[str, str]] = []
    trace_status_counts: dict[str, int] = {}

    for candidate in candidates:
        dtype = str(candidate.get("device_type") or "")
        did = normalize_device_id(candidate.get("device_id")) or ""
        feeder = normalize_feeder(candidate.get("feeder")) or ""
        field = _mapping_field(dtype)
        if not did or not field:
            trace_status_counts["skipped_invalid_candidate"] = trace_status_counts.get("skipped_invalid_candidate", 0) + 1
            continue
        trace = trace_downstream_peanos_for_device(
            dtype,
            did,
            feeder,
            client=client,
            base_url=base_url,
            trace_url=trace_url,
            timeout_seconds=timeout_seconds,
            sleep_seconds=sleep_seconds,
        )
        trace_status = str(trace.get("status") or "unknown")
        trace_status_counts[trace_status] = trace_status_counts.get(trace_status, 0) + 1
        if trace_status != "success":
            continue
        matched = sorted(str(peano) for peano in trace.get("peanos", set()) if str(peano) in confident_assets)
        for peano in matched:
            asset = confident_assets[peano]
            rows.append(
                {
                    "peano": peano,
                    "feeder": asset.feeder or feeder,
                    "device_type": dtype,
                    "device_id": did,
                    "mapping_field": field,
                    "status": status,
                    "source": "source_trace_downstream",
                    "reason": f"TraceDownHV_LV confirmed confident AIS meter downstream of {did}",
                    "reviewed_by": reviewed_by,
                    "reviewed_at": reviewed_at or _now_iso(),
                }
            )

    rows = _dedupe_override_rows(rows)
    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, OVERRIDE_COLUMNS, rows)
    return {
        "output_csv": str(output),
        "candidate_devices": len(candidates),
        "override_rows": len(rows),
        "status": status,
        "trace_status_counts": dict(sorted(trace_status_counts.items())),
        "device_ids": sorted({row["device_id"] for row in rows}),
    }


def apply_protection_mapping_overrides(
    db_path: str | Path,
    overrides_csv: str | Path,
    *,
    audit_output: str | Path | None = None,
    required_status: str = "approved",
) -> dict[str, Any]:
    db = RuntimeDb(db_path)
    db.init()
    assets = {asset.peano: asset for asset in db.load_customer_assets()}
    rows = _read_csv(overrides_csv)
    audit_rows: list[dict[str, str]] = []
    changed: dict[str, CustomerAsset] = {}

    for row in rows:
        peano = str(row.get("peano") or "").strip()
        status = str(row.get("status") or "").strip().lower()
        device_id = normalize_device_id(row.get("device_id")) or ""
        mapping_field = str(row.get("mapping_field") or "").strip()
        if status != required_status.lower():
            audit_rows.append(_audit_row(row, "skipped", f"status is {status or '<blank>'}"))
            continue
        asset = changed.get(peano) or assets.get(peano)
        if asset is None:
            audit_rows.append(_audit_row(row, "skipped", "PEANO not found in runtime customer_assets"))
            continue
        if not asset.confidence_eligible:
            audit_rows.append(_audit_row(row, "skipped", "asset is not confidence_eligible"))
            continue
        updated, action, reason = _apply_single_override(asset, mapping_field, device_id)
        if action == "updated":
            changed[peano] = updated
        audit_rows.append(_audit_row(row, action, reason))

    if changed:
        db.upsert_customer_assets(changed.values())

    audit_path = Path(audit_output) if audit_output else None
    if audit_path:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        _write_csv(audit_path, APPLY_AUDIT_COLUMNS, audit_rows)

    counts: dict[str, int] = {}
    for row in audit_rows:
        counts[row["action"]] = counts.get(row["action"], 0) + 1
    return {
        "overrides_csv": str(overrides_csv),
        "audit_output": str(audit_path) if audit_path else None,
        "rows_read": len(rows),
        "assets_updated": len(changed),
        "action_counts": dict(sorted(counts.items())),
    }


def _load_assets(db_path: str | Path, registry_xlsx: str | Path | None) -> list[CustomerAsset]:
    db = RuntimeDb(db_path)
    db.init()
    assets = db.load_customer_assets()
    if assets or registry_xlsx is None:
        return assets
    return load_assets_from_upstream_result(registry_xlsx)


def _load_source_trace_candidates(path: str | Path, *, device_id: str | None) -> list[dict[str, str]]:
    target = normalize_device_id(device_id) if device_id else None
    candidates = []
    for row in _read_csv(path):
        did = normalize_device_id(row.get("device_id")) or ""
        if target and did != target:
            continue
        if row.get("source_trace_result") != "source_trace_confirms_confident_ais_downstream":
            continue
        candidates.append(row)
    return candidates


def _apply_single_override(asset: CustomerAsset, mapping_field: str, device_id: str) -> tuple[CustomerAsset, str, str]:
    if not device_id:
        return asset, "skipped", "missing device_id"
    if mapping_field == "cb_ids":
        current = tuple(asset.cb_ids or ())
        if device_id in current:
            return asset, "unchanged", "device already present in cb_ids"
        return replace(asset, cb_ids=(*current, device_id)), "updated", "added device to cb_ids"
    if mapping_field == "recloser_ids":
        current = tuple(asset.recloser_ids or ())
        if device_id in current:
            return asset, "unchanged", "device already present in recloser_ids"
        return replace(asset, recloser_ids=(*current, device_id)), "updated", "added device to recloser_ids"
    if mapping_field == "switch_ids":
        current = tuple(asset.switch_ids or ())
        if device_id in current:
            return asset, "unchanged", "device already present in switch_ids"
        return replace(asset, switch_ids=(*current, device_id)), "updated", "added device to switch_ids"
    if mapping_field == "transformer_id":
        if asset.transformer_id == device_id or asset.transformer_peano == device_id:
            return asset, "unchanged", "device already present in transformer fields"
        return replace(asset, transformer_id=device_id), "updated", "set transformer_id"
    return asset, "skipped", f"unsupported mapping_field {mapping_field or '<blank>'}"


def _mapping_field(device_type: str) -> str:
    value = (device_type or "").strip().lower()
    if value == "cb":
        return "cb_ids"
    if value == "recloser":
        return "recloser_ids"
    if value == "switch":
        return "switch_ids"
    if value == "transformer":
        return "transformer_id"
    return ""


def _dedupe_override_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen = set()
    deduped = []
    for row in rows:
        key = (row["peano"], row["mapping_field"], row["device_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _audit_row(row: dict[str, str], action: str, reason: str) -> dict[str, str]:
    return {
        "peano": str(row.get("peano") or ""),
        "device_id": normalize_device_id(row.get("device_id")) or "",
        "mapping_field": str(row.get("mapping_field") or ""),
        "status": str(row.get("status") or ""),
        "action": action,
        "reason": reason,
    }


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
