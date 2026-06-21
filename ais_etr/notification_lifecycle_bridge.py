from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path
import sqlite3
from typing import Any


BRIDGE_CANDIDATE_COLUMNS = (
    "priority_rank",
    "webex_message_ref",
    "event_time",
    "district",
    "device_type",
    "device_id",
    "feeder",
    "webex_device_interruption_class",
    "event_age_band",
    "remaining_actual_minutes",
    "current_p50",
    "current_absolute_error",
    "current_covered_q10_q90",
    "notification_time_gate",
    "reportpo_lifecycle_bridge_use",
    "reportpo_lifecycle_match_status",
    "reportpo_job_status_at_notification",
    "reportpo_lifecycle_quality",
    "reportpo_feature_match_status",
    "reportpo_event_status",
    "reportpo_etr_type_description",
    "bridge_gap",
    "recommended_bridge_action",
)

BRIDGE_SUMMARY_COLUMNS = (
    "metric",
    "value",
)


def build_notification_lifecycle_bridge_audit(
    db_path: str | Path,
    readiness_csv: str | Path,
    output_csv: str | Path,
    summary_output: str | Path | None = None,
    markdown_output: str | Path | None = None,
    *,
    feature_audit_csv: str | Path | None = None,
    high_error_threshold_minutes: float = 60.0,
    top_limit: int = 30,
) -> dict[str, Any]:
    readiness_rows = _read_csv(readiness_csv)
    message_by_event = _load_message_by_event(db_path)
    feature_by_message = _read_by_key(feature_audit_csv, "webex_message_id") if feature_audit_csv else {}
    rows = _build_candidate_rows(
        readiness_rows,
        message_by_event,
        feature_by_message,
        high_error_threshold_minutes=high_error_threshold_minutes,
        top_limit=top_limit,
    )
    _write_csv(output_csv, BRIDGE_CANDIDATE_COLUMNS, rows)
    summary = _summarize(readiness_rows, rows, high_error_threshold_minutes=high_error_threshold_minutes)
    if summary_output:
        _write_csv(summary_output, BRIDGE_SUMMARY_COLUMNS, _summary_rows(summary))
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_markdown(summary, rows), encoding="utf-8-sig")
    return {
        **summary,
        "db_path": str(db_path),
        "readiness_csv": str(readiness_csv),
        "feature_audit_csv": str(feature_audit_csv) if feature_audit_csv else None,
        "output_csv": str(output_csv),
        "summary_output": str(summary_output) if summary_output else None,
        "markdown_output": str(markdown_output) if markdown_output else None,
    }


def _build_candidate_rows(
    readiness_rows: list[dict[str, str]],
    message_by_event: dict[str, str],
    feature_by_message: dict[str, dict[str, str]],
    *,
    high_error_threshold_minutes: float,
    top_limit: int,
) -> list[dict[str, str]]:
    candidates = [
        row
        for row in readiness_rows
        if row.get("notification_time_gate") == "shadow_etr_candidate"
        and (_to_float(row.get("current_absolute_error")) or 0) >= high_error_threshold_minutes
    ]
    candidates = sorted(
        candidates,
        key=lambda row: (
            -(_to_float(row.get("current_absolute_error")) or 0),
            row.get("event_time") or "",
            row.get("event_id") or "",
        ),
    )[: max(1, int(top_limit))]
    output = []
    for index, row in enumerate(candidates, start=1):
        raw_message_id = message_by_event.get(row.get("event_id") or "", "")
        feature = feature_by_message.get(raw_message_id, {})
        gap, action = _bridge_gap_and_action(row, feature)
        output.append(
            {
                "priority_rank": str(index),
                "webex_message_ref": row.get("webex_message_ref", ""),
                "event_time": row.get("event_time", ""),
                "district": row.get("district", ""),
                "device_type": row.get("device_type", ""),
                "device_id": row.get("device_id", ""),
                "feeder": row.get("feeder", ""),
                "webex_device_interruption_class": row.get("webex_device_interruption_class", ""),
                "event_age_band": row.get("event_age_band", ""),
                "remaining_actual_minutes": row.get("remaining_actual_minutes", ""),
                "current_p50": row.get("current_p50", ""),
                "current_absolute_error": row.get("current_absolute_error", ""),
                "current_covered_q10_q90": row.get("current_covered_q10_q90", ""),
                "notification_time_gate": row.get("notification_time_gate", ""),
                "reportpo_lifecycle_bridge_use": row.get("reportpo_lifecycle_bridge_use", ""),
                "reportpo_lifecycle_match_status": row.get("reportpo_lifecycle_match_status", ""),
                "reportpo_job_status_at_notification": row.get("reportpo_job_status_at_notification", ""),
                "reportpo_lifecycle_quality": row.get("reportpo_lifecycle_quality", ""),
                "reportpo_feature_match_status": feature.get("match_status", ""),
                "reportpo_event_status": feature.get("event_status", ""),
                "reportpo_etr_type_description": feature.get("etr_type_description", ""),
                "bridge_gap": gap,
                "recommended_bridge_action": action,
            }
        )
    return output


def _bridge_gap_and_action(row: dict[str, str], feature: dict[str, str]) -> tuple[str, str]:
    lifecycle_use = row.get("reportpo_lifecycle_bridge_use") or "not_available"
    device_state = row.get("webex_device_interruption_class") or "unknown"
    feature_status = feature.get("match_status") or "no_feature_match"
    remaining = _to_float(row.get("remaining_actual_minutes")) or 0.0
    p50 = _to_float(row.get("current_p50")) or 0.0

    if lifecycle_use == "not_available" and feature_status in {"matched", "ambiguous"}:
        return (
            "feature_match_without_po_lifecycle",
            "Use the matched ReportPO ETR feature row to search for an event/job/ticket bridge into PO lifecycle; keep audit-only until owner-approved.",
        )
    if lifecycle_use == "not_available":
        return (
            "missing_po_lifecycle_bridge",
            "Find an event-level bridge such as event number, job id, ticket id, or owner-approved device/time mapping; do not fill from feeder-only.",
        )
    if device_state == "momentary_le_1m" and remaining > 60:
        return (
            "momentary_webex_but_long_active_ais",
            "Review duplicate/flapping AIS intervals and downstream customer impact; momentary Webex state alone is not enough for customer-facing ETR.",
        )
    if remaining >= 180 and p50 < remaining * 0.5:
        return (
            "long_outage_underpredicted_with_lifecycle",
            "Use validated lifecycle timing, cause, crew status, and material/work-type fields as challenger features for long-outage escalation.",
        )
    return (
        "matched_lifecycle_still_high_error",
        "Review lifecycle semantics and add validated operational features only after bridge quality is confirmed.",
    )


def _summarize(
    readiness_rows: list[dict[str, str]],
    candidate_rows: list[dict[str, str]],
    *,
    high_error_threshold_minutes: float,
) -> dict[str, Any]:
    shadow_candidates = [row for row in readiness_rows if row.get("notification_time_gate") == "shadow_etr_candidate"]
    high_error_candidates = [
        row
        for row in shadow_candidates
        if (_to_float(row.get("current_absolute_error")) or 0) >= high_error_threshold_minutes
    ]
    missing_lifecycle = [
        row for row in high_error_candidates if (row.get("reportpo_lifecycle_bridge_use") or "not_available") == "not_available"
    ]
    matched_lifecycle = [row for row in high_error_candidates if row not in missing_lifecycle]
    gap_counts = Counter(row.get("bridge_gap") or "<blank>" for row in candidate_rows)
    summary = {
        "readiness_rows": len(readiness_rows),
        "shadow_etr_candidate_rows": len(shadow_candidates),
        "high_error_threshold_minutes": high_error_threshold_minutes,
        "high_error_candidate_rows": len(high_error_candidates),
        "missing_lifecycle_bridge_high_error_rows": len(missing_lifecycle),
        "matched_lifecycle_high_error_rows": len(matched_lifecycle),
        "exported_priority_rows": len(candidate_rows),
        "bridge_gap_counts": dict(gap_counts.most_common()),
        "top_feeders": dict(Counter(row.get("feeder") or "<blank>" for row in high_error_candidates).most_common(8)),
        "top_device_types": dict(Counter(row.get("device_type") or "<blank>" for row in high_error_candidates).most_common(8)),
        "top_device_states": dict(
            Counter(row.get("webex_device_interruption_class") or "<blank>" for row in high_error_candidates).most_common(8)
        ),
        "recommendation": _recommendation(len(high_error_candidates), len(missing_lifecycle), gap_counts),
    }
    return summary


def _recommendation(high_error_rows: int, missing_lifecycle_rows: int, gap_counts: Counter[str]) -> str:
    if high_error_rows == 0:
        return "No high-error notification-time candidates meet the threshold; keep monitoring before lifecycle bridge work."
    if missing_lifecycle_rows / high_error_rows >= 0.5:
        return (
            "Prioritize an event-level bridge into ReportPO/eRespond lifecycle for high-error long outages. "
            "This is likely higher value than tuning the current model."
        )
    if gap_counts.get("momentary_webex_but_long_active_ais", 0):
        return "Review flapping/duplicate AIS intervals for momentary Webex rows before using them as model-training truth."
    return "Use matched lifecycle rows as a shadow challenger feature set, but keep production send blocked."


def _render_markdown(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Notification Lifecycle Bridge Audit",
        "",
        "This audit prioritizes high-error notification-time ETR candidates that need an event-level lifecycle bridge before model tuning. It is shadow-only and does not fill truth.",
        "",
        "## Summary",
        "",
        f"- Customer-facing shadow candidates: {summary['shadow_etr_candidate_rows']}",
        f"- High-error candidates: {summary['high_error_candidate_rows']}",
        f"- Missing PO lifecycle bridge among high-error candidates: {summary['missing_lifecycle_bridge_high_error_rows']}",
        f"- Matched lifecycle among high-error candidates: {summary['matched_lifecycle_high_error_rows']}",
        f"- Priority rows exported: {summary['exported_priority_rows']}",
        "",
        "## Bridge Gap Counts",
        "",
        "| Bridge gap | Rows |",
        "| --- | ---: |",
    ]
    for gap, count in summary["bridge_gap_counts"].items():
        lines.append(f"| {gap} | {count} |")
    lines.extend(["", "## Top Feeders In High-Error Candidates", "", "| Feeder | Rows |", "| --- | ---: |"])
    for feeder, count in summary["top_feeders"].items():
        lines.append(f"| {feeder} | {count} |")
    lines.extend(
        [
            "",
            "## Priority Rows",
            "",
            "| Rank | Event ref | Time | Device | Feeder | State | Remaining | p50 | Error | Gap |",
            "| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in rows[:20]:
        lines.append(
            "| {rank} | {ref} | {time} | {device} | {feeder} | {state} | {remaining} | {p50} | {error} | {gap} |".format(
                rank=row.get("priority_rank", ""),
                ref=row.get("webex_message_ref", ""),
                time=row.get("event_time", ""),
                device=row.get("device_id") or row.get("device_type") or "",
                feeder=row.get("feeder", ""),
                state=row.get("webex_device_interruption_class", ""),
                remaining=row.get("remaining_actual_minutes", ""),
                p50=row.get("current_p50", ""),
                error=row.get("current_absolute_error", ""),
                gap=row.get("bridge_gap", ""),
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
            "- Output uses redacted message references and aggregate counts.",
            "- It does not include source chat bodies, space identifiers, credential values, meter-id lists, or customer registration names.",
            "- Feeder-only evidence remains audit-only unless an owner approves a topology/event bridge.",
        ]
    )
    return "\n".join(lines) + "\n"


def _summary_rows(summary: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for key, value in summary.items():
        if isinstance(value, dict):
            rows.append({"metric": key, "value": json.dumps(value, ensure_ascii=False, sort_keys=True)})
        else:
            rows.append({"metric": key, "value": str(value)})
    return rows


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


def _read_by_key(path: str | Path | None, key: str) -> dict[str, dict[str, str]]:
    if not path or not Path(path).exists():
        return {}
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
