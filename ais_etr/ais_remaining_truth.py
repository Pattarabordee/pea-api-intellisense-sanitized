from __future__ import annotations

import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import sqlite3
from statistics import mean, median
from typing import Any

from .evaluation import TRUTH_MAPPING_COLUMNS


REMAINING_TRUTH_TARGET = "ais_remaining_restoration_minutes"
REMAINING_TRUTH_DEFINITION = "AIS_POWER_RESTORE_TIME - WEBEX_EVENT_TIME"
REMAINING_TRUTH_SOURCE = "ais_site_power_status"

REMAINING_AUDIT_COLUMNS = (
    "webex_message_id",
    "webex_event_time",
    "webex_device_id",
    "webex_feeder",
    "match_status",
    "match_level",
    "matched_ais_rows",
    "matched_site_count",
    "matched_peano_count",
    "actual_restoration_minutes",
    "max_elapsed_since_ais_start_minutes",
    "truth_quality",
    "truth_notes",
)


def match_ais_remaining_truth_to_shadow(
    db_path: str | Path,
    ais_truth_csv: str | Path,
    mapping_csv: str | Path,
    audit_csv: str | Path | None = None,
    *,
    start_tolerance_minutes: float = 5.0,
    aggregation: str = "max",
    overwrite: bool = False,
) -> dict[str, Any]:
    if start_tolerance_minutes < 0:
        raise ValueError("start_tolerance_minutes must be non-negative")
    runtime_rows = _runtime_shadow_rows(db_path)
    truth_by_peano = _load_truth_by_peano(ais_truth_csv)
    mapping_rows = _load_or_create_truth_mapping(mapping_csv, runtime_rows)
    mapping_by_message = {row["webex_message_id"]: row for row in mapping_rows}

    audit_rows = []
    matched_rows = filled_rows = preserved_existing_rows = no_match_rows = 0
    for runtime in runtime_rows:
        decision = _match_one(
            runtime,
            truth_by_peano,
            start_tolerance_minutes=start_tolerance_minutes,
            aggregation=aggregation,
        )
        audit_rows.append(decision)
        if decision["match_status"] == "matched":
            matched_rows += 1
        else:
            no_match_rows += 1

        message_id = runtime.get("webex_message_id") or ""
        mapping = mapping_by_message.get(message_id)
        if mapping is None or decision["match_status"] != "matched":
            continue
        if not overwrite and str(mapping.get("actual_restoration_minutes", "")).strip():
            preserved_existing_rows += 1
            continue
        mapping["actual_restoration_minutes"] = str(decision.get("actual_restoration_minutes") or "")
        mapping["truth_source"] = REMAINING_TRUTH_SOURCE
        mapping["truth_target"] = REMAINING_TRUTH_TARGET
        mapping["truth_definition"] = REMAINING_TRUTH_DEFINITION
        mapping["truth_quality"] = str(decision.get("truth_quality") or "")
        mapping["truth_notes"] = str(decision.get("truth_notes") or "")
        filled_rows += 1

    _write_truth_mapping(mapping_csv, mapping_rows)
    if audit_csv:
        _write_audit(audit_csv, audit_rows)
    return {
        "db_path": str(db_path),
        "ais_truth_csv": str(ais_truth_csv),
        "mapping_output": str(mapping_csv),
        "audit_output": str(audit_csv) if audit_csv else None,
        "runtime_events": len(runtime_rows),
        "matched_rows": matched_rows,
        "filled_rows": filled_rows,
        "preserved_existing_rows": preserved_existing_rows,
        "no_match_rows": no_match_rows,
        "start_tolerance_minutes": start_tolerance_minutes,
        "aggregation": aggregation,
        "truth_target": REMAINING_TRUTH_TARGET,
    }


def _match_one(
    runtime: dict[str, Any],
    truth_by_peano: dict[str, list[dict[str, Any]]],
    *,
    start_tolerance_minutes: float,
    aggregation: str,
) -> dict[str, Any]:
    base = {
        "webex_message_id": runtime.get("webex_message_id") or "",
        "webex_event_time": _format_dt(runtime.get("event_dt")),
        "webex_device_id": runtime.get("device_id") or "",
        "webex_feeder": runtime.get("feeder") or "",
        "match_status": "no_match",
        "match_level": "",
        "matched_ais_rows": 0,
        "matched_site_count": 0,
        "matched_peano_count": 0,
        "actual_restoration_minutes": "",
        "max_elapsed_since_ais_start_minutes": "",
        "truth_quality": "",
        "truth_notes": "no active AIS interval at Webex event time",
    }
    event_dt = runtime.get("event_dt")
    if event_dt is None:
        return {**base, "truth_notes": "missing Webex event time"}
    candidates = []
    tolerance = timedelta(minutes=start_tolerance_minutes)
    for peano in runtime.get("affected_peanos") or set():
        for row in truth_by_peano.get(peano, []):
            start = row["outage_start_dt"]
            restore = row["power_restore_dt"]
            if start - tolerance <= event_dt <= restore:
                remaining = round((restore - event_dt).total_seconds() / 60, 2)
                elapsed = round(max(0.0, (event_dt - start).total_seconds() / 60), 2)
                if remaining >= 0:
                    candidates.append({**row, "remaining": remaining, "elapsed": elapsed})
            elif start > event_dt + tolerance:
                break
    if not candidates:
        return base
    values = [row["remaining"] for row in candidates]
    actual = _aggregate(values, aggregation)
    site_count = len({row.get("site_id_norm") for row in candidates if row.get("site_id_norm")})
    peano_count = len({row.get("peano_norm") for row in candidates if row.get("peano_norm")})
    max_elapsed = max(row["elapsed"] for row in candidates)
    notes = (
        f"affected_peano_active_time; aggregation={aggregation}; ais_rows={len(candidates)}; "
        f"sites={site_count}; peanos={peano_count}; target={REMAINING_TRUTH_TARGET}"
    )
    return {
        **base,
        "match_status": "matched",
        "match_level": "affected_peano_active_time",
        "matched_ais_rows": len(candidates),
        "matched_site_count": site_count,
        "matched_peano_count": peano_count,
        "actual_restoration_minutes": "" if actual is None else str(actual),
        "max_elapsed_since_ais_start_minutes": str(max_elapsed),
        "truth_quality": "OK",
        "truth_notes": notes,
    }


def _runtime_shadow_rows(db_path: str | Path) -> list[dict[str, Any]]:
    path = Path(db_path)
    if not path.exists():
        return []
    uri = "file:" + str(path.resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        query = """
            WITH latest_notifications AS (
                SELECT n.*
                FROM notifications n
                JOIN (
                    SELECT event_id, MAX(id) AS max_id
                    FROM notifications
                    GROUP BY event_id
                ) latest ON latest.max_id = n.id
            )
            SELECT
                e.webex_message_id,
                e.event_time,
                e.device_id,
                e.feeder,
                n.payload_json
            FROM outage_events e
            LEFT JOIN latest_notifications n ON n.event_id = e.event_id
            WHERE e.webex_message_id IS NOT NULL
            ORDER BY e.event_time, e.webex_message_id
        """
        rows = []
        for row in conn.execute(query).fetchall():
            item = dict(row)
            item["event_dt"] = _parse_dt(item.get("event_time"))
            item["affected_peanos"] = _affected_peanos(item.get("payload_json"))
            rows.append(item)
        return rows
    finally:
        conn.close()


def _load_truth_by_peano(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    by_peano: dict[str, list[dict[str, Any]]] = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("truth_quality") or "").strip().upper() != "OK":
                continue
            peano = _normalize_key(row.get("peano"))
            start = _parse_dt(row.get("outage_start_time"))
            restore = _parse_dt(row.get("power_restore_time"))
            actual = _to_float(row.get("actual_restoration_minutes"))
            if not peano or start is None or restore is None or actual is None or actual <= 5 or actual > 1440:
                continue
            by_peano.setdefault(peano, []).append(
                {
                    "site_id_norm": _normalize_key(row.get("site_id")),
                    "peano_norm": peano,
                    "outage_start_dt": start,
                    "power_restore_dt": restore,
                }
            )
    for values in by_peano.values():
        values.sort(key=lambda row: row["outage_start_dt"])
    return by_peano


def _load_or_create_truth_mapping(mapping_path: str | Path, runtime_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    path = Path(mapping_path)
    rows: list[dict[str, str]] = []
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                rows.append({column: (row.get(column) or "") for column in TRUTH_MAPPING_COLUMNS})
    existing = {row["webex_message_id"] for row in rows}
    for row in runtime_rows:
        message_id = row.get("webex_message_id") or ""
        if message_id and message_id not in existing:
            rows.append({column: "" for column in TRUTH_MAPPING_COLUMNS} | {"webex_message_id": message_id})
            existing.add(message_id)
    return rows


def _write_truth_mapping(mapping_path: str | Path, rows: list[dict[str, str]]) -> None:
    output = Path(mapping_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(TRUTH_MAPPING_COLUMNS))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in TRUTH_MAPPING_COLUMNS} for row in rows)


def _write_audit(output_path: str | Path, rows: list[dict[str, Any]]) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REMAINING_AUDIT_COLUMNS))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in REMAINING_AUDIT_COLUMNS} for row in rows)


def _affected_peanos(raw_payload: str | None) -> set[str]:
    if not raw_payload:
        return set()
    try:
        payload = json.loads(raw_payload)
    except Exception:
        return set()
    return {
        normalized
        for normalized in (_normalize_key(item.get("peano")) for item in payload.get("affected_customers") or [])
        if normalized
    }


def _aggregate(values: list[float], aggregation: str) -> float | None:
    if not values:
        return None
    mode = aggregation.strip().lower()
    if mode == "mean":
        return round(float(mean(values)), 2)
    if mode == "median":
        return round(float(median(values)), 2)
    if mode != "max":
        raise ValueError("aggregation must be one of: max, mean, median")
    return round(max(values), 2)


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    numeric = _to_float(text)
    if numeric is not None and 20000 <= numeric <= 80000:
        return datetime(1899, 12, 30) + timedelta(days=numeric)
    text = text.replace("T", " ").removesuffix("Z")
    if "." in text:
        head, tail = text.split(".", 1)
        match = re.match(r"\d+", tail)
        if match:
            text = head + "." + match.group(0)[:6]
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    ):
        try:
            return _normalize_year(datetime.strptime(text, fmt))
        except ValueError:
            pass
    try:
        return _normalize_year(datetime.fromisoformat(text)).replace(tzinfo=None)
    except ValueError:
        return None


def _normalize_year(value: datetime) -> datetime:
    if value.year > 2400:
        return value.replace(year=value.year - 543, tzinfo=None)
    return value.replace(tzinfo=None)


def _normalize_key(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in {"", "nan", "none", "null", "nat"}:
        return ""
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return re.sub(r"\s+", "", text).upper()


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _format_dt(value: datetime | None) -> str:
    return value.isoformat(sep=" ") if value else ""
