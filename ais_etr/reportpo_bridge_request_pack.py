from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path
from typing import Any


PRIORITY_COLUMNS = (
    "priority_rank",
    "webex_message_ref",
    "event_time",
    "device_id",
    "feeder",
    "reportpo_etr_event_number",
    "remaining_actual_minutes",
    "current_absolute_error",
    "bridge_status",
    "needed_shared_key",
)

REQUESTED_FIELDS = (
    {
        "source": "ReportPO ETR / eRespond event",
        "field": "shared_job_id_or_ticket_id",
        "why_needed": "Join ETR event rows to PO lifecycle rows when EVENT_ID values do not match.",
    },
    {
        "source": "ReportPO PO lifecycle",
        "field": "shared_job_id_or_ticket_id",
        "why_needed": "Provide the same key as the ETR event side for CR/NO/IP/restore/close lifecycle features.",
    },
    {
        "source": "ReportPO ETR / eRespond event",
        "field": "cause_group_or_cause_code",
        "why_needed": "Explain long outages and avoid training only on feeder/device averages.",
    },
    {
        "source": "ReportPO PO lifecycle",
        "field": "crew_dispatch_arrival_or_job_status_timestamps",
        "why_needed": "Model remaining time from notification time, not administrative close time.",
    },
    {
        "source": "ReportPO PO lifecycle",
        "field": "material_required_or_work_type",
        "why_needed": "Separate routine switching from repair/material-heavy outages.",
    },
)


def build_reportpo_bridge_request_pack(
    event_bridge_csv: str | Path,
    output_markdown: str | Path,
    priority_output: str | Path | None = None,
    *,
    top_limit: int = 20,
) -> dict[str, Any]:
    rows = _read_csv(event_bridge_csv)
    prioritized = _priority_rows(rows, top_limit=top_limit)
    if priority_output:
        _write_csv(priority_output, PRIORITY_COLUMNS, prioritized)
    summary = _summarize(rows, prioritized)
    output = Path(output_markdown)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_render_markdown(summary, prioritized), encoding="utf-8-sig")
    return {
        **summary,
        "event_bridge_csv": str(event_bridge_csv),
        "output_markdown": str(output_markdown),
        "priority_output": str(priority_output) if priority_output else None,
    }


def _priority_rows(rows: list[dict[str, str]], *, top_limit: int) -> list[dict[str, str]]:
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            -(_to_float(row.get("current_absolute_error")) or 0),
            row.get("event_time") or "",
            row.get("webex_message_ref") or "",
        ),
    )[: max(1, int(top_limit))]
    output = []
    for index, row in enumerate(sorted_rows, start=1):
        output.append(
            {
                "priority_rank": str(index),
                "webex_message_ref": row.get("webex_message_ref", ""),
                "event_time": row.get("event_time", ""),
                "device_id": row.get("device_id", ""),
                "feeder": row.get("feeder", ""),
                "reportpo_etr_event_number": row.get("reportpo_etr_event_number", ""),
                "remaining_actual_minutes": row.get("remaining_actual_minutes", ""),
                "current_absolute_error": row.get("current_absolute_error", ""),
                "bridge_status": row.get("bridge_status", ""),
                "needed_shared_key": _needed_key(row),
            }
        )
    return output


def _needed_key(row: dict[str, str]) -> str:
    status = row.get("bridge_status") or ""
    if status == "etr_event_number_not_found_in_po":
        return "job_id_or_ticket_id_shared_between_etr_and_po"
    if status == "no_etr_feature_match":
        return "webex_to_etr_event_bridge_then_job_id_or_ticket_id"
    return "source_owner_validated_event_bridge"


def _summarize(rows: list[dict[str, str]], prioritized: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "priority_rows": len(prioritized),
        "bridge_status_counts": dict(Counter(row.get("bridge_status") or "<blank>" for row in rows).most_common()),
        "top_feeders": dict(Counter(row.get("feeder") or "<blank>" for row in rows).most_common(8)),
        "top_devices": dict(Counter(row.get("device_id") or "<blank>" for row in rows).most_common(8)),
        "requested_fields": list(REQUESTED_FIELDS),
    }


def _render_markdown(summary: dict[str, Any], prioritized: list[dict[str, str]]) -> str:
    lines = [
        "# ReportPO / eRespond Shared-Key Request Pack",
        "",
        "Purpose: resolve the lifecycle bridge blocker for AIS ETR shadow evaluation. Current evidence shows ReportPO ETR event numbers do not match PO lifecycle event numbers for the high-error notification-time rows.",
        "",
        "## Evidence Summary",
        "",
        f"- High-error rows in bridge audit: {summary['rows']}",
        f"- Priority rows included: {summary['priority_rows']}",
        "",
        "| Bridge status | Rows |",
        "| --- | ---: |",
    ]
    for status, count in summary["bridge_status_counts"].items():
        lines.append(f"| {status} | {count} |")
    lines.extend(["", "## Requested Fields", "", "| Source | Field | Why needed |", "| --- | --- | --- |"])
    for item in REQUESTED_FIELDS:
        lines.append(f"| {item['source']} | `{item['field']}` | {item['why_needed']} |")
    lines.extend(["", "## Top Feeders", "", "| Feeder | Rows |", "| --- | ---: |"])
    for feeder, count in summary["top_feeders"].items():
        lines.append(f"| {feeder} | {count} |")
    lines.extend(
        [
            "",
            "## Priority Rows For Lookup",
            "",
            "| Rank | Event ref | Time | Device | Feeder | ReportPO ETR event | Error | Needed key |",
            "| ---: | --- | --- | --- | --- | --- | ---: | --- |",
        ]
    )
    for row in prioritized:
        lines.append(
            "| {rank} | {ref} | {time} | {device} | {feeder} | {event_number} | {error} | {needed} |".format(
                rank=row.get("priority_rank", ""),
                ref=row.get("webex_message_ref", ""),
                time=row.get("event_time", ""),
                device=row.get("device_id", ""),
                feeder=row.get("feeder", ""),
                event_number=row.get("reportpo_etr_event_number", ""),
                error=row.get("current_absolute_error", ""),
                needed=row.get("needed_shared_key", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Acceptance Criteria",
            "",
            "- At least one shared key joins ReportPO ETR event rows to PO lifecycle rows at event grain.",
            "- The shared key must work on the high-error priority rows, especially `SEK06`.",
            "- Lifecycle fields must include CR/NO/IP/first-restore/close or equivalent timestamps.",
            "- The output must remain shadow-only until source semantics are validated.",
            "",
            "## Safety Notes",
            "",
            "- This pack uses redacted message references and ReportPO event numbers only.",
            "- It excludes source chat bodies, space identifiers, credential values, meter-id lists, and customer registration names.",
        ]
    )
    return "\n".join(lines) + "\n"


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
