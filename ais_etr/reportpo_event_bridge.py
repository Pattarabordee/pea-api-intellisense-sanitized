from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path
import sqlite3
from typing import Any


EVENT_BRIDGE_COLUMNS = (
    "webex_message_ref",
    "event_time",
    "device_id",
    "feeder",
    "remaining_actual_minutes",
    "current_absolute_error",
    "reportpo_etr_match_status",
    "reportpo_etr_event_number",
    "reportpo_etr_device_id",
    "reportpo_etr_event_start_time",
    "po_event_number_match_status",
    "po_device_id",
    "po_cr_datetime",
    "po_ip_datetime",
    "po_last_restore_datetime",
    "po_cl_datetime",
    "po_lifecycle_quality",
    "bridge_status",
    "recommended_action",
)

SUMMARY_COLUMNS = ("metric", "value")


def build_reportpo_event_bridge_audit(
    db_path: str | Path,
    readiness_csv: str | Path,
    feature_audit_csv: str | Path,
    lifecycle_csv: str | Path,
    output_csv: str | Path,
    summary_output: str | Path | None = None,
    markdown_output: str | Path | None = None,
    *,
    high_error_threshold_minutes: float = 60.0,
) -> dict[str, Any]:
    message_by_event = _load_message_by_event(db_path)
    feature_by_message = _read_by_key(feature_audit_csv, "webex_message_id")
    lifecycle_by_event_number = _lifecycle_by_event_number(lifecycle_csv)
    readiness_rows = _read_csv(readiness_csv)
    rows = _build_rows(
        readiness_rows,
        message_by_event,
        feature_by_message,
        lifecycle_by_event_number,
        high_error_threshold_minutes=high_error_threshold_minutes,
    )
    _write_csv(output_csv, EVENT_BRIDGE_COLUMNS, rows)
    summary = _summarize(rows, lifecycle_by_event_number, high_error_threshold_minutes)
    if summary_output:
        _write_csv(summary_output, SUMMARY_COLUMNS, _summary_rows(summary))
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_markdown(summary, rows), encoding="utf-8-sig")
    return {
        **summary,
        "db_path": str(db_path),
        "readiness_csv": str(readiness_csv),
        "feature_audit_csv": str(feature_audit_csv),
        "lifecycle_csv": str(lifecycle_csv),
        "output_csv": str(output_csv),
        "summary_output": str(summary_output) if summary_output else None,
        "markdown_output": str(markdown_output) if markdown_output else None,
    }


def _build_rows(
    readiness_rows: list[dict[str, str]],
    message_by_event: dict[str, str],
    feature_by_message: dict[str, dict[str, str]],
    lifecycle_by_event_number: dict[str, dict[str, str]],
    *,
    high_error_threshold_minutes: float,
) -> list[dict[str, str]]:
    output = []
    for row in readiness_rows:
        if row.get("notification_time_gate") != "shadow_etr_candidate":
            continue
        if (_to_float(row.get("current_absolute_error")) or 0) < high_error_threshold_minutes:
            continue
        raw_message_id = message_by_event.get(row.get("event_id") or "", "")
        feature = feature_by_message.get(raw_message_id, {})
        event_number = str(feature.get("event_number") or "").strip()
        lifecycle = lifecycle_by_event_number.get(event_number, {}) if event_number else {}
        bridge_status, action = _bridge_status(feature, event_number, lifecycle)
        output.append(
            {
                "webex_message_ref": row.get("webex_message_ref", ""),
                "event_time": row.get("event_time", ""),
                "device_id": row.get("device_id", ""),
                "feeder": row.get("feeder", ""),
                "remaining_actual_minutes": row.get("remaining_actual_minutes", ""),
                "current_absolute_error": row.get("current_absolute_error", ""),
                "reportpo_etr_match_status": feature.get("match_status", ""),
                "reportpo_etr_event_number": event_number,
                "reportpo_etr_device_id": feature.get("reportpo_device_id", ""),
                "reportpo_etr_event_start_time": feature.get("reportpo_event_start_time", ""),
                "po_event_number_match_status": "matched" if lifecycle else ("missing_event_number" if not event_number else "no_match"),
                "po_device_id": lifecycle.get("op_device_id", ""),
                "po_cr_datetime": lifecycle.get("cr_datetime", ""),
                "po_ip_datetime": lifecycle.get("ip_datetime", ""),
                "po_last_restore_datetime": lifecycle.get("last_restore_datetime", ""),
                "po_cl_datetime": lifecycle.get("cl_datetime", ""),
                "po_lifecycle_quality": lifecycle.get("lifecycle_quality", ""),
                "bridge_status": bridge_status,
                "recommended_action": action,
            }
        )
    return sorted(
        output,
        key=lambda row: (
            -(_to_float(row.get("current_absolute_error")) or 0),
            row.get("event_time") or "",
            row.get("webex_message_ref") or "",
        ),
    )


def _bridge_status(
    feature: dict[str, str],
    event_number: str,
    lifecycle: dict[str, str],
) -> tuple[str, str]:
    feature_status = str(feature.get("match_status") or "").strip()
    if lifecycle:
        return (
            "event_number_bridge_found",
            "Use as audit evidence only; validate lifecycle timestamp semantics before any model feature or truth fill.",
        )
    if event_number:
        return (
            "etr_event_number_not_found_in_po",
            "ReportPO ETR event number does not bridge to PO lifecycle rows. Search for job id, ticket id, or another shared key.",
        )
    if feature_status in {"matched", "ambiguous"}:
        return (
            "etr_feature_match_missing_event_number",
            "Feature row matched by device/time but lacks an event number; inspect captured ReportPO fields for another join key.",
        )
    return (
        "no_etr_feature_match",
        "No reliable ReportPO ETR row for this Webex candidate; prioritize source-system/event-owner lookup over model tuning.",
    )


def _summarize(
    rows: list[dict[str, str]],
    lifecycle_by_event_number: dict[str, dict[str, str]],
    high_error_threshold_minutes: float,
) -> dict[str, Any]:
    status_counts = Counter(row.get("bridge_status") or "<blank>" for row in rows)
    etr_status_counts = Counter(row.get("reportpo_etr_match_status") or "<blank>" for row in rows)
    po_status_counts = Counter(row.get("po_event_number_match_status") or "<blank>" for row in rows)
    summary = {
        "high_error_threshold_minutes": high_error_threshold_minutes,
        "high_error_rows": len(rows),
        "po_lifecycle_event_numbers": len(lifecycle_by_event_number),
        "bridge_status_counts": dict(status_counts.most_common()),
        "reportpo_etr_match_status_counts": dict(etr_status_counts.most_common()),
        "po_event_number_match_status_counts": dict(po_status_counts.most_common()),
        "top_feeders": dict(Counter(row.get("feeder") or "<blank>" for row in rows).most_common(10)),
        "top_devices": dict(Counter(row.get("device_id") or "<blank>" for row in rows).most_common(10)),
        "recommendation": _recommendation(status_counts),
    }
    return summary


def _recommendation(status_counts: Counter[str]) -> str:
    if status_counts.get("event_number_bridge_found", 0):
        return "Validate found event-number bridges with the source owner before using lifecycle fields as shadow challenger features."
    if status_counts.get("etr_event_number_not_found_in_po", 0):
        return (
            "ETR event numbers do not currently bridge to PO lifecycle. The next source work should capture or request a shared job/ticket key."
        )
    return "Prioritize source-system lookup for high-error rows; current PowerBI fields do not provide a safe lifecycle bridge."


def _render_markdown(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# ReportPO ETR-to-PO Event Bridge Audit",
        "",
        "This audit checks whether high-error notification-time candidates can bridge from ReportPO ETR feature rows to ReportPO PO lifecycle rows by event number. It is audit-only and does not fill truth.",
        "",
        "## Summary",
        "",
        f"- High-error notification-time rows: {summary['high_error_rows']}",
        f"- Unique PO lifecycle event numbers loaded: {summary['po_lifecycle_event_numbers']}",
        "",
        "## Bridge Status",
        "",
        "| Bridge status | Rows |",
        "| --- | ---: |",
    ]
    for status, count in summary["bridge_status_counts"].items():
        lines.append(f"| {status} | {count} |")
    lines.extend(["", "## PO Event Number Match Status", "", "| PO status | Rows |", "| --- | ---: |"])
    for status, count in summary["po_event_number_match_status_counts"].items():
        lines.append(f"| {status} | {count} |")
    lines.extend(["", "## Top Feeders", "", "| Feeder | Rows |", "| --- | ---: |"])
    for feeder, count in summary["top_feeders"].items():
        lines.append(f"| {feeder} | {count} |")
    lines.extend(
        [
            "",
            "## Priority Rows",
            "",
            "| Event ref | Time | Device | Feeder | ETR event | PO status | Error | Bridge status |",
            "| --- | --- | --- | --- | --- | --- | ---: | --- |",
        ]
    )
    for row in rows[:25]:
        lines.append(
            "| {ref} | {time} | {device} | {feeder} | {event_number} | {po_status} | {error} | {status} |".format(
                ref=row.get("webex_message_ref", ""),
                time=row.get("event_time", ""),
                device=row.get("device_id", ""),
                feeder=row.get("feeder", ""),
                event_number=row.get("reportpo_etr_event_number", ""),
                po_status=row.get("po_event_number_match_status", ""),
                error=row.get("current_absolute_error", ""),
                status=row.get("bridge_status", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            str(summary["recommendation"]),
            "",
            "## Safety Notes",
            "",
            "- Output uses redacted message references and ReportPO event numbers only.",
            "- It does not include source chat bodies, space identifiers, credential values, meter-id lists, or customer registration names.",
            "- Event-number bridges found here are audit evidence until validated by a ReportPO/eRespond owner.",
        ]
    )
    return "\n".join(lines) + "\n"


def _lifecycle_by_event_number(path: str | Path) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    for row in _read_csv(path):
        event_number = str(row.get("event_number") or "").strip()
        if event_number and event_number not in output:
            output[event_number] = row
    return output


def _load_message_by_event(db_path: str | Path) -> dict[str, str]:
    path = Path(db_path)
    if not path.exists():
        return {}
    uri = "file:" + str(path.resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        return {
            str(event_id): str(message_id or "")
            for event_id, message_id in conn.execute(
                "SELECT event_id, webex_message_id FROM outage_events WHERE event_id IS NOT NULL"
            ).fetchall()
        }
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()


def _read_by_key(path: str | Path, key: str) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    for row in _read_csv(path):
        value = str(row.get(key) or "").strip()
        if value and value not in output:
            output[value] = row
    return output


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: str | Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def _summary_rows(summary: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for key, value in summary.items():
        if isinstance(value, dict):
            rows.append({"metric": key, "value": json.dumps(value, ensure_ascii=False, sort_keys=True)})
        else:
            rows.append({"metric": key, "value": str(value)})
    return rows


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None
