from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from .notification_policy import build_customer_facing_gate
from .parser import parse_webex_message


URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
LONG_NUMERIC_RE = re.compile(r"\b\d{12,13}\b")
WHITESPACE_RE = re.compile(r"\s+")


AUDIT_COLUMNS = [
    "event_id",
    "webex_message_id",
    "created",
    "device_type",
    "device_id_present",
    "feeder_present",
    "district_present",
    "district_source",
    "event_time_present",
    "event_time_source",
    "webex_device_interruption_class",
    "webex_open_close_minutes",
    "event_number_present",
    "event_number_missing_reason",
    "risk_level",
    "match_confidence",
    "match_bucket",
    "customer_facing_gate",
    "customer_facing_gate_reason",
    "affected_count",
    "notification_status",
    "raw_text_length",
    "raw_text_excerpt",
]


def sanitize_message_text(text: str | None, max_chars: int = 160) -> str:
    if not text:
        return ""
    value = URL_RE.sub("[URL_REDACTED]", text)
    value = EMAIL_RE.sub("[EMAIL_REDACTED]", value)
    value = LONG_NUMERIC_RE.sub("[LONG_NUMBER_REDACTED]", value)
    value = WHITESPACE_RE.sub(" ", value).strip()
    if len(value) > max_chars:
        return value[: max_chars - 3].rstrip() + "..."
    return value


def build_webex_audit(
    db_path: str | Path,
    districts: tuple[str, ...],
    room_district: str | None = None,
    output_csv: str | Path | None = None,
    samples_output: str | Path | None = None,
    max_text_chars: int = 160,
) -> dict[str, Any]:
    rows = _load_runtime_rows(db_path)
    audit_rows = []
    sample_rows = []
    for row in rows:
        message = _message_from_row(row)
        if room_district:
            message = {**message, "roomDistrict": room_district}
        event = parse_webex_message(message, districts=districts)
        parsed = _parsed_json(row["parsed_json"])
        parsed_fields = (event.parsed_fields if event else parsed.get("parsed_fields")) or {}
        raw_text = (event.raw_text if event else row["raw_text"]) or ""
        device = event.outage_device if event else None
        event_number = parsed_fields.get("event_number")
        match_confidence = _float_or_none(row["match_confidence"])
        affected_count = _int_or_zero(row["affected_count"])
        shadow_policy = _shadow_policy_from_notification(row["notification_payload_json"])
        if not shadow_policy:
            shadow_policy = build_customer_facing_gate(
                webex_device_interruption_class=parsed_fields.get("webex_device_interruption_class"),
                webex_open_close_minutes=parsed_fields.get("webex_open_close_minutes"),
                match_level=None,
                match_confidence=match_confidence,
                affected_count=affected_count,
            )
        audit_row = {
            "event_id": row["event_id"],
            "webex_message_id": row["webex_message_id"],
            "created": row["message_created"] or row["created_at"],
            "device_type": device.device_type if device else row["device_type"],
            "device_id_present": bool(device.device_id if device else row["device_id"]),
            "feeder_present": bool(device.feeder if device else row["feeder"]),
            "district_present": bool(event.district if event else row["district"]),
            "district_source": parsed_fields.get("district_source"),
            "event_time_present": bool(event.event_time if event else row["event_time"]),
            "event_time_source": parsed_fields.get("event_time_source"),
            "webex_device_interruption_class": parsed_fields.get("webex_device_interruption_class"),
            "webex_open_close_minutes": parsed_fields.get("webex_open_close_minutes"),
            "event_number_present": bool(event_number),
            "event_number_missing_reason": parsed_fields.get("event_number_missing_reason"),
            "risk_level": row["risk_level"],
            "match_confidence": match_confidence,
            "match_bucket": _match_bucket(match_confidence, affected_count),
            "customer_facing_gate": shadow_policy.get("customer_facing_gate"),
            "customer_facing_gate_reason": shadow_policy.get("reason"),
            "affected_count": affected_count,
            "notification_status": row["notification_status"],
            "raw_text_length": len(raw_text),
            "raw_text_excerpt": sanitize_message_text(raw_text, max_text_chars),
        }
        audit_rows.append(audit_row)
        sample_rows.append(_sample_item(message, event, parsed_fields, districts))

    if output_csv:
        _write_csv(output_csv, audit_rows)
    if samples_output:
        _write_samples(samples_output, sample_rows)

    summary = _summarize(audit_rows)
    summary["output_csv"] = str(output_csv) if output_csv else None
    summary["samples_output"] = str(samples_output) if samples_output else None
    return summary


def _load_runtime_rows(db_path: str | Path) -> list[sqlite3.Row]:
    path = Path(db_path)
    if not path.exists():
        return []
    uri = "file:" + str(path.resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        query = """
            WITH latest_predictions AS (
                SELECT p.*
                FROM predictions p
                JOIN (
                    SELECT event_id, MAX(id) AS max_id
                    FROM predictions
                    GROUP BY event_id
                ) latest ON latest.max_id = p.id
            ),
            latest_notifications AS (
                SELECT n.*
                FROM notifications n
                JOIN (
                    SELECT event_id, MAX(id) AS max_id
                    FROM notifications
                    GROUP BY event_id
                ) latest ON latest.max_id = n.id
            )
            SELECT
                e.event_id,
                e.webex_message_id,
                e.room_id,
                e.event_time,
                e.district,
                e.device_type,
                e.device_id,
                e.feeder,
                e.raw_text,
                e.parsed_json,
                e.created_at,
                m.created AS message_created,
                m.raw_json AS message_raw_json,
                p.risk_level,
                p.match_confidence,
                p.affected_count,
                n.status AS notification_status
                , n.payload_json AS notification_payload_json
            FROM outage_events e
            LEFT JOIN webex_messages m ON m.id = e.webex_message_id
            LEFT JOIN latest_predictions p ON p.event_id = e.event_id
            LEFT JOIN latest_notifications n ON n.event_id = e.event_id
            WHERE e.webex_message_id IS NOT NULL
            ORDER BY COALESCE(m.created, e.created_at), e.event_id
        """
        return list(conn.execute(query).fetchall())
    finally:
        conn.close()


def _message_from_row(row: sqlite3.Row) -> dict[str, Any]:
    raw = row["message_raw_json"]
    if raw:
        try:
            message = json.loads(raw)
            if isinstance(message, dict):
                return message
        except Exception:
            pass
    return {
        "id": row["webex_message_id"],
        "roomId": row["room_id"],
        "created": row["message_created"],
        "text": row["raw_text"] or "",
    }


def _parsed_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _sample_item(
    message: dict[str, Any],
    event: Any,
    parsed_fields: dict[str, Any],
    districts: tuple[str, ...],
) -> dict[str, Any]:
    text = message.get("text") or message.get("markdown") or ""
    item = {
        "id": message.get("id"),
        "roomId": "<REDACTED_ROOM_ID>",
        "created": message.get("created"),
        "text": sanitize_message_text(text, max_chars=1000),
    }
    room_district = message.get("roomDistrict")
    if room_district:
        item["roomDistrict"] = room_district
    if event is not None:
        sample_event = parse_webex_message(item, districts=districts)
        if sample_event is None:
            item["expected"] = {"ignored": True, "reason": "sanitized_sample_not_parseable"}
        else:
            sample_fields = sample_event.parsed_fields or {}
            item["expected"] = {
                "device_id": sample_event.outage_device.device_id,
                "device_type": sample_event.outage_device.device_type,
                "feeder": sample_event.outage_device.feeder,
                "district": sample_event.district,
                "event_number": sample_fields.get("event_number"),
                "event_number_missing_reason": sample_fields.get("event_number_missing_reason"),
                "event_time_source": sample_fields.get("event_time_source"),
                "webex_device_interruption_class": sample_fields.get("webex_device_interruption_class"),
                "webex_open_close_minutes": sample_fields.get("webex_open_close_minutes"),
            }
    return item


def _write_csv(output_csv: str | Path, rows: list[dict[str, Any]]) -> None:
    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_samples(output_path: str | Path, rows: list[dict[str, Any]]) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    return {
        "total_events": total,
        "field_completeness": {
            "device": _rate(rows, "device_id_present"),
            "feeder": _rate(rows, "feeder_present"),
            "district": _rate(rows, "district_present"),
            "event_time": _rate(rows, "event_time_present"),
            "event_number": _rate(rows, "event_number_present"),
        },
        "counts": {
            "device": sum(1 for row in rows if row["device_id_present"]),
            "feeder": sum(1 for row in rows if row["feeder_present"]),
            "district": sum(1 for row in rows if row["district_present"]),
            "event_time": sum(1 for row in rows if row["event_time_present"]),
            "event_number": sum(1 for row in rows if row["event_number_present"]),
        },
        "event_number_missing_reason": _value_counts(rows, "event_number_missing_reason"),
        "event_time_source": _value_counts(rows, "event_time_source"),
        "webex_device_interruption_class": _value_counts(rows, "webex_device_interruption_class"),
        "device_type": _value_counts(rows, "device_type"),
        "risk_level": _value_counts(rows, "risk_level"),
        "match_bucket": _value_counts(rows, "match_bucket"),
        "customer_facing_gate": _value_counts(rows, "customer_facing_gate"),
        "notification_status": _value_counts(rows, "notification_status"),
    }


def _rate(rows: list[dict[str, Any]], field: str) -> float | None:
    if not rows:
        return None
    return round(sum(1 for row in rows if row[field]) / len(rows), 3)


def _value_counts(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(field)
        label = str(value) if value not in (None, "") else "<missing>"
        counts[label] = counts.get(label, 0) + 1
    return counts


def _match_bucket(match_confidence: float | None, affected_count: int) -> str:
    if not affected_count:
        return "no_match"
    if match_confidence is None:
        return "unknown"
    if match_confidence >= 0.85:
        return "high_protection"
    if match_confidence >= 0.5:
        return "medium"
    return "low"


def _shadow_policy_from_notification(raw: str | None) -> dict[str, Any]:
    payload = _parsed_json(raw)
    policy = payload.get("shadow_policy")
    return policy if isinstance(policy, dict) else {}


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
