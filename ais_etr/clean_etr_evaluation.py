from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


TRUTH_SOURCE = "ais_meter_state"
TRUTH_TARGET = "ais_event_remaining_restoration_minutes"
OUTPUT_COLUMNS = (
    "case_ref",
    "outage_at",
    "restore_at",
    "prediction_created_at",
    "remaining_etr_minutes",
    "interval_duration_minutes",
    "truth_source",
    "truth_target",
    "training_eligibility",
    "incident_group_ref",
    "production_send",
)


def build_clean_etr_evaluation_frame(
    source_csv: str | Path,
    output_csv: str | Path,
    summary_json: str | Path,
    *,
    cluster_minutes: float = 5.0,
) -> dict[str, Any]:
    source_rows = _read_csv(source_csv)
    rows: list[dict[str, Any]] = []
    rejected = 0
    for index, source in enumerate(source_rows, 1):
        outage = _parse_time(source.get("outage_at") or source.get("outage_start_time"))
        restore = _parse_time(source.get("restore_at") or source.get("power_restore_time"))
        predicted = _parse_time(source.get("prediction_created_at") or source.get("request_received_at"))
        bridge = str(source.get("bridge_status") or "").strip().upper()
        if not outage or not restore or not predicted or bridge != "METER_STATE_MODEL_READY":
            rejected += 1
            continue
        interval_minutes = (restore - outage).total_seconds() / 60.0
        remaining_minutes = (restore - predicted).total_seconds() / 60.0
        if not (5 < interval_minutes <= 1440 and 0 < remaining_minutes <= 1440 and outage <= predicted < restore):
            rejected += 1
            continue
        verified_group = str(source.get("verified_incident_ref") or "").strip()
        rows.append(
            {
                "case_ref": _ref("case", source.get("interval_id") or source.get("case_ref") or f"row-{index}"),
                "outage_at": _format_time(outage),
                "restore_at": _format_time(restore),
                "prediction_created_at": _format_time(predicted),
                "remaining_etr_minutes": round(remaining_minutes, 3),
                "interval_duration_minutes": round(interval_minutes, 3),
                "truth_source": TRUTH_SOURCE,
                "truth_target": TRUTH_TARGET,
                "training_eligibility": "train_eligible",
                "incident_group_ref": _ref("incident", verified_group) if verified_group else "",
                "production_send": "blocked",
                "_outage": outage,
                "_restore": restore,
            }
        )
    _assign_conservative_groups(rows, cluster_minutes)
    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    incidents = len({row["incident_group_ref"] for row in rows})
    summary = {
        "source_rows": len(source_rows),
        "eligible_rows": len(rows),
        "rejected_rows": rejected,
        "independent_incident_groups": incidents,
        "minimum_incident_groups": 30,
        "gate_status": "shadow_evaluation_ready" if incidents >= 30 else "insufficient_independent_incidents",
        "truth_source": TRUTH_SOURCE,
        "truth_target": TRUTH_TARGET,
        "production_send": "blocked",
        "output_csv": str(output),
    }
    summary_path = Path(summary_json)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _assign_conservative_groups(rows: list[dict[str, Any]], cluster_minutes: float) -> None:
    unassigned = [index for index, row in enumerate(rows) if not row["incident_group_ref"]]
    remaining = set(unassigned)
    threshold = cluster_minutes * 60.0
    while remaining:
        seed = min(remaining)
        component = {seed}
        frontier = [seed]
        remaining.remove(seed)
        while frontier:
            current = frontier.pop()
            connected = [
                candidate
                for candidate in list(remaining)
                if abs((rows[current]["_outage"] - rows[candidate]["_outage"]).total_seconds()) <= threshold
                and abs((rows[current]["_restore"] - rows[candidate]["_restore"]).total_seconds()) <= threshold
            ]
            for candidate in connected:
                remaining.remove(candidate)
                component.add(candidate)
                frontier.append(candidate)
        basis = "|".join(sorted(rows[index]["case_ref"] for index in component))
        group_ref = _ref("incident_cluster", basis)
        for index in component:
            rows[index]["incident_group_ref"] = group_ref


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ref(namespace: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return namespace + "_" + hashlib.sha256(f"{namespace}|{text}".encode("utf-8")).hexdigest()[:16]
