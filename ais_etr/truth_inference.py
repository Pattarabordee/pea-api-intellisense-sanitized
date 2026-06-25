from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
import re
import sqlite3
from typing import Any

from .evaluation import TRUTH_MAPPING_COLUMNS


STATUS_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+"
    r"(Open|Close|Normal|Lockout|Trip|Operate|Alarm|In\s+Progress)\b",
    re.IGNORECASE,
)
RESTORE_STATUSES = {"close", "normal"}
INTERRUPTION_STATUSES = {"open", "lockout", "trip"}


def infer_webex_truth_mapping(
    db_path: str | Path,
    mapping_path: str | Path,
    candidates_output: str | Path | None = None,
    fill_empty_only: bool = True,
) -> dict[str, Any]:
    rows = _runtime_webex_rows(db_path)
    mapping_rows = _load_or_create_mapping(mapping_path, rows)
    mapping_by_message = {row["webex_message_id"]: row for row in mapping_rows}

    candidates = []
    filled = 0
    preserved_existing = 0
    for row in rows:
        candidate = infer_restoration_from_message(row)
        candidates.append(candidate)
        message_id = row["webex_message_id"]
        mapping = mapping_by_message.get(message_id)
        if mapping is None or not _has_actual_restoration(candidate.get("actual_restoration_minutes")):
            continue
        if fill_empty_only and str(mapping.get("actual_restoration_minutes", "")).strip():
            preserved_existing += 1
            continue
        mapping["actual_restoration_minutes"] = candidate["actual_restoration_minutes"]
        mapping["truth_source"] = candidate["truth_source"]
        mapping["truth_target"] = candidate["truth_target"]
        mapping["truth_definition"] = candidate["truth_definition"]
        mapping["truth_quality"] = candidate["truth_confidence"]
        mapping["truth_notes"] = candidate["truth_note"]
        filled += 1

    _write_mapping(mapping_path, mapping_rows)
    if candidates_output:
        _write_candidates(candidates_output, candidates)
    review_rows = sum(1 for row in candidates if row.get("truth_confidence") == "REVIEW")
    return {
        "mapping_output": str(mapping_path),
        "candidates_output": str(candidates_output) if candidates_output else None,
        "runtime_events": len(rows),
        "candidate_rows": sum(
            1
            for row in candidates
            if _has_actual_restoration(row.get("actual_restoration_minutes"))
        ),
        "filled_rows": filled,
        "preserved_existing_rows": preserved_existing,
        "review_rows": review_rows,
    }


def infer_restoration_from_message(row: dict[str, Any]) -> dict[str, Any]:
    message_id = row.get("webex_message_id") or ""
    event_time = _parse_dt(row.get("event_time"))
    status_events = _extract_status_events(row.get("raw_text") or "")
    interruption_seen = False
    restore_time: datetime | None = None
    for status_time, status in status_events:
        normalized = status.lower().replace(" ", "_")
        if event_time and status_time < event_time:
            continue
        if normalized in INTERRUPTION_STATUSES:
            interruption_seen = True
        if normalized in RESTORE_STATUSES and (interruption_seen or event_time):
            restore_time = status_time
            break

    actual_minutes = None
    confidence = "NO_CANDIDATE"
    note = "No Close/Normal status after event time"
    if event_time and restore_time:
        delta = max(0.0, (restore_time - event_time).total_seconds() / 60)
        actual_minutes = round(delta, 2)
        confidence = "REVIEW" if delta <= 5 else "INFERRED"
        note = "Inferred from first Close/Normal status after Webex event time"

    return {
        "webex_message_id": message_id,
        "event_time": row.get("event_time") or "",
        "device_id": row.get("device_id") or "",
        "feeder": row.get("feeder") or "",
        "actual_restoration_minutes": "" if actual_minutes is None else actual_minutes,
        "restoration_time": restore_time.isoformat(sep=" ") if restore_time else "",
        "truth_source": "webex_switch_status" if restore_time else "",
        "truth_target": "webex_status_first_close_minutes" if restore_time else "",
        "truth_definition": "first Close/Normal status after Webex event time - Webex event time"
        if restore_time
        else "",
        "truth_confidence": confidence,
        "truth_note": note,
    }


def _runtime_webex_rows(db_path: str | Path) -> list[dict[str, Any]]:
    path = Path(db_path)
    if not path.exists():
        return []
    uri = "file:" + str(path.resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        query = """
            SELECT
                e.webex_message_id,
                e.event_time,
                e.device_id,
                e.feeder,
                COALESCE(m.text, e.raw_text) AS raw_text
            FROM outage_events e
            LEFT JOIN webex_messages m ON m.id = e.webex_message_id
            WHERE e.webex_message_id IS NOT NULL
            ORDER BY e.event_time, e.webex_message_id
        """
        return [dict(row) for row in conn.execute(query).fetchall()]
    finally:
        conn.close()


def _extract_status_events(text: str) -> list[tuple[datetime, str]]:
    events = []
    for match in STATUS_RE.finditer(text):
        dt = _parse_dt(match.group(1))
        if dt is None:
            continue
        events.append((dt, match.group(2)))
    return sorted(events, key=lambda item: item[0])


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("T", " ")
    text = re.sub(r"Z$", "", text)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _has_actual_restoration(value: Any) -> bool:
    if value is None:
        return False
    return str(value).strip() != ""


def _load_or_create_mapping(mapping_path: str | Path, runtime_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
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


def _write_mapping(mapping_path: str | Path, rows: list[dict[str, str]]) -> None:
    output = Path(mapping_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(TRUTH_MAPPING_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def _write_candidates(output_path: str | Path, rows: list[dict[str, Any]]) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "webex_message_id",
        "event_time",
        "device_id",
        "feeder",
        "actual_restoration_minutes",
        "restoration_time",
        "truth_source",
        "truth_target",
        "truth_definition",
        "truth_confidence",
        "truth_note",
    ]
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
