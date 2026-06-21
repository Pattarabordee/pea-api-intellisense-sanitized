from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from statistics import mean
from typing import Any

from .notification_policy import build_customer_facing_gate
from .truth_quality import GATE_COVERAGE_MAX, GATE_COVERAGE_MIN, GATE_Q50_MAE_MAX, MIN_SUSTAINED_ROWS_FOR_TUNING


READINESS_COLUMNS = (
    "event_id",
    "webex_message_ref",
    "event_time",
    "district",
    "device_type",
    "device_id",
    "feeder",
    "match_level",
    "match_confidence",
    "affected_count",
    "webex_device_interruption_class",
    "webex_open_close_minutes",
    "active_ais_outage_confirmed",
    "max_elapsed_since_ais_start_minutes",
    "event_age_band",
    "remaining_actual_minutes",
    "evaluation_policy",
    "notification_time_gate",
    "notification_time_reason",
    "current_p50",
    "current_q10",
    "current_q90",
    "current_absolute_error",
    "current_covered_q10_q90",
    "challenger_p50",
    "challenger_q10",
    "challenger_q90",
    "challenger_absolute_error",
    "challenger_covered_q10_q90",
    "reportpo_lifecycle_match_status",
    "reportpo_job_status_at_notification",
    "reportpo_lifecycle_quality",
    "reportpo_lifecycle_bridge_use",
)

SEGMENT_COLUMNS = (
    "dimension",
    "segment",
    "events",
    "active_ais_rows",
    "sustained_eligible_rows",
    "candidate_rows",
    "mean_remaining_minutes",
    "current_q50_mae_minutes",
    "current_q10_q90_coverage",
    "high_error_events",
)


def build_notification_time_readiness(
    db_path: str | Path,
    comparison_csv: str | Path,
    remaining_audit_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    device_state_csv: str | Path | None = None,
    lifecycle_audit_csv: str | Path | None = None,
    segments_output: str | Path | None = None,
    short_threshold_minutes: float = 5.0,
    high_error_threshold_minutes: float = 60.0,
    min_segment_events: int = 3,
) -> dict[str, Any]:
    runtime = _load_runtime_event_context(db_path)
    remaining_by_message = _read_by_key(remaining_audit_csv, "webex_message_id")
    device_state_by_event = _read_by_key(device_state_csv, "event_id") if device_state_csv else {}
    lifecycle_by_message = _read_by_key(lifecycle_audit_csv, "webex_message_id") if lifecycle_audit_csv else {}
    comparison_rows = _read_csv(comparison_csv)

    rows = [
        _build_row(
            row,
            runtime.get(row.get("event_id") or "", {}),
            remaining_by_message,
            device_state_by_event,
            lifecycle_by_message,
            short_threshold_minutes=short_threshold_minutes,
        )
        for row in comparison_rows
    ]
    _write_csv(output_csv, READINESS_COLUMNS, rows)
    segment_rows = _build_segments(
        rows,
        min_segment_events=min_segment_events,
        high_error_threshold_minutes=high_error_threshold_minutes,
    )
    if segments_output:
        _write_csv(segments_output, SEGMENT_COLUMNS, segment_rows)

    summary = _summarize(rows, segment_rows, high_error_threshold_minutes=high_error_threshold_minutes)
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_markdown(summary, rows, segment_rows), encoding="utf-8-sig")
    return {
        **summary,
        "db_path": str(db_path),
        "comparison_csv": str(comparison_csv),
        "remaining_audit_csv": str(remaining_audit_csv),
        "device_state_csv": str(device_state_csv) if device_state_csv else None,
        "lifecycle_audit_csv": str(lifecycle_audit_csv) if lifecycle_audit_csv else None,
        "output_csv": str(output_csv),
        "segments_output": str(segments_output) if segments_output else None,
        "markdown_output": str(markdown_output) if markdown_output else None,
    }


def _build_row(
    comparison: dict[str, str],
    runtime: dict[str, Any],
    remaining_by_message: dict[str, dict[str, str]],
    device_state_by_event: dict[str, dict[str, str]],
    lifecycle_by_message: dict[str, dict[str, str]],
    *,
    short_threshold_minutes: float,
) -> dict[str, str]:
    raw_message_id = runtime.get("webex_message_id") or ""
    remaining = remaining_by_message.get(raw_message_id, {})
    device_state = device_state_by_event.get(comparison.get("event_id") or "", {})
    lifecycle = lifecycle_by_message.get(raw_message_id, {})
    parsed = runtime.get("parsed_fields") or {}
    actual = _first_float(
        comparison.get("actual_restoration_minutes"),
        remaining.get("actual_restoration_minutes"),
    )
    active = _is_active_remaining_match(remaining, actual)
    device_class = (
        device_state.get("webex_device_interruption_class")
        or parsed.get("webex_device_interruption_class")
        or "unknown"
    )
    open_close = _first_text(
        device_state.get("webex_open_close_minutes"),
        parsed.get("webex_open_close_minutes"),
    )
    base_gate = build_customer_facing_gate(
        webex_device_interruption_class=str(device_class or "unknown"),
        webex_open_close_minutes=open_close,
        match_level=comparison.get("match_level"),
        match_confidence=comparison.get("match_confidence"),
        affected_count=comparison.get("affected_count"),
        active_ais_outage_confirmed=active,
    )
    policy = _evaluation_policy(actual, short_threshold_minutes)
    gate, reason = _notification_time_gate(base_gate, active, policy)
    return {
        "event_id": comparison.get("event_id", ""),
        "webex_message_ref": comparison.get("webex_message_ref") or _redacted_ref(raw_message_id),
        "event_time": comparison.get("event_time", ""),
        "district": comparison.get("district", ""),
        "device_type": comparison.get("device_type", ""),
        "device_id": comparison.get("device_id", ""),
        "feeder": comparison.get("feeder", ""),
        "match_level": comparison.get("match_level", ""),
        "match_confidence": comparison.get("match_confidence", ""),
        "affected_count": comparison.get("affected_count", ""),
        "webex_device_interruption_class": str(device_class or "unknown"),
        "webex_open_close_minutes": _fmt(_to_float(open_close)),
        "active_ais_outage_confirmed": _bool_text(active),
        "max_elapsed_since_ais_start_minutes": remaining.get("max_elapsed_since_ais_start_minutes", ""),
        "event_age_band": _event_age_band(_to_float(remaining.get("max_elapsed_since_ais_start_minutes"))),
        "remaining_actual_minutes": _fmt(actual),
        "evaluation_policy": policy,
        "notification_time_gate": gate,
        "notification_time_reason": reason,
        "current_p50": comparison.get("current_p50", ""),
        "current_q10": comparison.get("current_q10", ""),
        "current_q90": comparison.get("current_q90", ""),
        "current_absolute_error": comparison.get("current_absolute_error", ""),
        "current_covered_q10_q90": comparison.get("current_covered_q10_q90", ""),
        "challenger_p50": comparison.get("challenger_p50", ""),
        "challenger_q10": comparison.get("challenger_q10", ""),
        "challenger_q90": comparison.get("challenger_q90", ""),
        "challenger_absolute_error": comparison.get("challenger_absolute_error", ""),
        "challenger_covered_q10_q90": comparison.get("challenger_covered_q10_q90", ""),
        "reportpo_lifecycle_match_status": lifecycle.get("match_status", ""),
        "reportpo_job_status_at_notification": lifecycle.get("job_status_at_notification", ""),
        "reportpo_lifecycle_quality": lifecycle.get("lifecycle_quality", ""),
        "reportpo_lifecycle_bridge_use": _lifecycle_bridge_use(lifecycle),
    }


def _notification_time_gate(base_gate: dict[str, Any], active: bool, policy: str) -> tuple[str, str]:
    if not active:
        return "review_only", "no_active_ais_interval_at_webex_time"
    if policy != "sustained_outage_eligible":
        return "review_only", f"{policy}_not_customer_facing_etr_gate"
    if base_gate.get("customer_facing_gate") == "shadow_etr_candidate":
        return "shadow_etr_candidate", str(base_gate.get("reason") or "active_sustained_ais_interval")
    return "review_only", str(base_gate.get("reason") or "notification_time_gate_review")


def _summarize(
    rows: list[dict[str, str]],
    segment_rows: list[dict[str, str]],
    *,
    high_error_threshold_minutes: float,
) -> dict[str, Any]:
    active_rows = [row for row in rows if row.get("active_ais_outage_confirmed") == "TRUE"]
    sustained_rows = [row for row in active_rows if row.get("evaluation_policy") == "sustained_outage_eligible"]
    candidates = [row for row in rows if row.get("notification_time_gate") == "shadow_etr_candidate"]
    review_rows = [row for row in rows if row.get("notification_time_gate") != "shadow_etr_candidate"]
    lifecycle_counts = Counter(row.get("reportpo_lifecycle_bridge_use") or "not_available" for row in rows)
    gate_counts = Counter(row.get("notification_time_gate") or "review_only" for row in rows)
    reason_counts = Counter(row.get("notification_time_reason") or "<blank>" for row in rows)
    policy_counts = Counter(row.get("evaluation_policy") or "<blank>" for row in rows)
    summary = {
        "events": len(rows),
        "active_ais_interval_rows": len(active_rows),
        "sustained_eligible_rows": len(sustained_rows),
        "customer_facing_candidate_rows": len(candidates),
        "review_only_rows": len(review_rows),
        "gate_counts": dict(sorted(gate_counts.items())),
        "reason_counts": dict(reason_counts.most_common(8)),
        "evaluation_policy_counts": dict(sorted(policy_counts.items())),
        "all_active_metrics": _metrics(active_rows),
        "sustained_candidate_metrics": _metrics(sustained_rows),
        "customer_facing_candidate_metrics": _metrics(candidates),
        "micro_short_review_metrics": _metrics(
            [row for row in active_rows if row.get("evaluation_policy") in {"momentary_micro_review", "short_interruption_review"}]
        ),
        "lifecycle_bridge_counts": dict(sorted(lifecycle_counts.items())),
        "top_error_segments": segment_rows[:10],
        "high_error_threshold_minutes": high_error_threshold_minutes,
    }
    summary["notification_time_gate_status"] = _gate_status(summary["customer_facing_candidate_metrics"])
    summary["recommendation"] = _recommendation(summary)
    return summary


def _build_segments(
    rows: list[dict[str, str]],
    *,
    min_segment_events: int,
    high_error_threshold_minutes: float,
) -> list[dict[str, str]]:
    dimensions = {
        "district": "district",
        "feeder": "feeder",
        "device_type": "device_type",
        "device_state": "webex_device_interruption_class",
        "event_age_band": "event_age_band",
        "lifecycle_status": "reportpo_job_status_at_notification",
    }
    output: list[dict[str, str]] = []
    for dimension, column in dimensions.items():
        values = sorted({row.get(column) or "<blank>" for row in rows})
        for value in values:
            group = [row for row in rows if (row.get(column) or "<blank>") == value]
            if len(group) < min_segment_events:
                continue
            metrics = _metrics([row for row in group if row.get("active_ais_outage_confirmed") == "TRUE"])
            output.append(
                {
                    "dimension": dimension,
                    "segment": value,
                    "events": str(len(group)),
                    "active_ais_rows": str(sum(1 for row in group if row.get("active_ais_outage_confirmed") == "TRUE")),
                    "sustained_eligible_rows": str(
                        sum(1 for row in group if row.get("evaluation_policy") == "sustained_outage_eligible")
                    ),
                    "candidate_rows": str(sum(1 for row in group if row.get("notification_time_gate") == "shadow_etr_candidate")),
                    "mean_remaining_minutes": _fmt(metrics["mean_actual_minutes"]),
                    "current_q50_mae_minutes": _fmt(metrics["current_q50_mae_minutes"]),
                    "current_q10_q90_coverage": _fmt(metrics["current_q10_q90_coverage"], digits=3),
                    "high_error_events": str(
                        sum(
                            1
                            for row in group
                            if (_to_float(row.get("current_absolute_error")) or 0) >= high_error_threshold_minutes
                        )
                    ),
                }
            )
    return sorted(
        output,
        key=lambda row: (
            -int(row.get("high_error_events") or 0),
            -(_to_float(row.get("current_q50_mae_minutes")) or 0),
            row.get("dimension", ""),
            row.get("segment", ""),
        ),
    )


def _render_markdown(summary: dict[str, Any], rows: list[dict[str, str]], segments: list[dict[str, str]]) -> str:
    candidate_metrics = summary["customer_facing_candidate_metrics"]
    active_metrics = summary["all_active_metrics"]
    sustained_metrics = summary["sustained_candidate_metrics"]
    review_metrics = summary["micro_short_review_metrics"]
    top_errors = sorted(
        [row for row in rows if _to_float(row.get("current_absolute_error")) is not None],
        key=lambda row: _to_float(row.get("current_absolute_error")) or 0,
        reverse=True,
    )[:10]
    lines = [
        "# Notification-Time ETR Readiness",
        "",
        "This report evaluates ETR only at the point where a customer notification would be considered. A Webex event is customer-facing only when an AIS interval is still active at the Webex event time and the remaining outage is sustained (>5 minutes).",
        "",
        "## Summary",
        "",
        f"- Webex shadow events: {summary['events']}",
        f"- Events with active AIS interval at Webex time: {summary['active_ais_interval_rows']}",
        f"- Sustained eligible active intervals (>5 min): {summary['sustained_eligible_rows']}",
        f"- Customer-facing shadow ETR candidates: {summary['customer_facing_candidate_rows']}",
        f"- Review-only events: {summary['review_only_rows']}",
        f"- Candidate gate status: {summary['notification_time_gate_status']}",
        "",
        "## Metric View",
        "",
        "| Segment | Rows | Current MAE | Current coverage | Challenger MAE | Challenger coverage |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        _metric_row("All active AIS intervals", active_metrics),
        _metric_row("Sustained active intervals", sustained_metrics),
        _metric_row("Customer-facing candidates", candidate_metrics),
        _metric_row("Micro/short review", review_metrics),
        "",
        "## Gate Counts",
        "",
        "| Gate | Rows |",
        "| --- | ---: |",
    ]
    for gate, count in summary["gate_counts"].items():
        lines.append(f"| {gate} | {count} |")
    lines.extend(["", "## Review Reasons", "", "| Reason | Rows |", "| --- | ---: |"])
    for reason, count in summary["reason_counts"].items():
        lines.append(f"| {reason} | {count} |")
    lines.extend(["", "## ReportPO Lifecycle Bridge", "", "| Bridge use | Rows |", "| --- | ---: |"])
    for use, count in summary["lifecycle_bridge_counts"].items():
        lines.append(f"| {use} | {count} |")
    lines.extend(
        [
            "",
            "## Highest Error Segments",
            "",
            "| Dimension | Segment | Events | Active AIS | Sustained | Candidates | MAE | Coverage | High-error rows |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in segments[:10]:
        lines.append(
            "| {dimension} | {segment} | {events} | {active} | {sustained} | {candidates} | {mae} | {coverage} | {high} |".format(
                dimension=row.get("dimension", ""),
                segment=row.get("segment", ""),
                events=row.get("events", ""),
                active=row.get("active_ais_rows", ""),
                sustained=row.get("sustained_eligible_rows", ""),
                candidates=row.get("candidate_rows", ""),
                mae=row.get("current_q50_mae_minutes", ""),
                coverage=row.get("current_q10_q90_coverage", ""),
                high=row.get("high_error_events", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Top Error Rows",
            "",
            "| Event ref | Time | Device | Feeder | State | Remaining | Current p50 | Error | Gate |",
            "| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in top_errors:
        lines.append(
            "| {ref} | {time} | {device} | {feeder} | {state} | {actual} | {p50} | {error} | {gate} |".format(
                ref=row.get("webex_message_ref", ""),
                time=row.get("event_time", ""),
                device=row.get("device_id") or row.get("device_type") or "",
                feeder=row.get("feeder", ""),
                state=row.get("webex_device_interruption_class", ""),
                actual=row.get("remaining_actual_minutes", ""),
                p50=row.get("current_p50", ""),
                error=row.get("current_absolute_error", ""),
                gate=row.get("notification_time_gate", ""),
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
            "- This is a shadow-only readiness report and does not change production notification behavior.",
            "- It omits source chat text, space identifiers, credential values, meter-id lists, and customer registration names.",
            "- ReportPO lifecycle fields remain audit-only until an event-number, job-id, ticket-id, or owner-approved bridge is available.",
        ]
    )
    return "\n".join(lines) + "\n"


def _metric_row(label: str, metrics: dict[str, Any]) -> str:
    return (
        f"| {label} | {metrics['rows']} | {_blank(metrics['current_q50_mae_minutes'])} | "
        f"{_blank(metrics['current_q10_q90_coverage'])} | "
        f"{_blank(metrics['challenger_q50_mae_minutes'])} | {_blank(metrics['challenger_q10_q90_coverage'])} |"
    )


def _metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "mean_actual_minutes": _round_or_none(_mean(_numbers(rows, "remaining_actual_minutes"))),
        "current_q50_mae_minutes": _round_or_none(_mean(_numbers(rows, "current_absolute_error"))),
        "current_q10_q90_coverage": _round_or_none(_coverage(rows, "current_covered_q10_q90"), digits=3),
        "challenger_q50_mae_minutes": _round_or_none(_mean(_numbers(rows, "challenger_absolute_error"))),
        "challenger_q10_q90_coverage": _round_or_none(_coverage(rows, "challenger_covered_q10_q90"), digits=3),
    }


def _gate_status(metrics: dict[str, Any]) -> str:
    rows = int(metrics.get("rows") or 0)
    mae = metrics.get("current_q50_mae_minutes")
    coverage = metrics.get("current_q10_q90_coverage")
    if rows < MIN_SUSTAINED_ROWS_FOR_TUNING:
        return "insufficient_notification_time_truth"
    if mae is None or coverage is None:
        return "missing_metric"
    if float(mae) <= GATE_Q50_MAE_MAX and GATE_COVERAGE_MIN <= float(coverage) <= GATE_COVERAGE_MAX:
        return "gate_pass"
    return "gate_fail"


def _recommendation(summary: dict[str, Any]) -> str:
    metrics = summary["customer_facing_candidate_metrics"]
    gate = summary["notification_time_gate_status"]
    if summary["active_ais_interval_rows"] == 0:
        return "No active AIS interval truth is available. Do not claim notification-time ETR accuracy."
    if gate == "insufficient_notification_time_truth":
        return (
            "Keep collecting AIS outage/restore truth and Webex events. Do not tune or promote until "
            f"customer-facing sustained truth reaches at least {MIN_SUSTAINED_ROWS_FOR_TUNING} rows."
        )
    if gate == "gate_pass":
        return "Keep this model in shadow and require human approval before any AIS production send."
    return (
        "Do not promote the current model. Focus next on active AIS interval confirmation, long-outage lifecycle fields, "
        "and an owner-approved ReportPO/eRespond event bridge."
    )


def _load_runtime_event_context(db_path: str | Path) -> dict[str, dict[str, Any]]:
    path = Path(db_path)
    if not path.exists():
        return {}
    uri = "file:" + str(path.resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        output: dict[str, dict[str, Any]] = {}
        for row in conn.execute("SELECT event_id, webex_message_id, parsed_json FROM outage_events").fetchall():
            parsed_json = _safe_json(row["parsed_json"])
            fields = parsed_json.get("parsed_fields") or {}
            output[str(row["event_id"])] = {
                "webex_message_id": str(row["webex_message_id"] or ""),
                "parsed_fields": fields if isinstance(fields, dict) else {},
            }
        return output
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()


def _is_active_remaining_match(remaining: dict[str, str], actual: float | None) -> bool:
    if str(remaining.get("match_status") or "").strip().lower() == "matched":
        return True
    return actual is not None and str(remaining.get("truth_quality") or "").strip().upper() == "OK"


def _evaluation_policy(actual: float | None, short_threshold_minutes: float) -> str:
    if actual is None:
        return "no_active_ais_interval"
    if actual <= 1:
        return "momentary_micro_review"
    if actual <= short_threshold_minutes:
        return "short_interruption_review"
    if actual > 1440:
        return "invalid_gt_24h"
    return "sustained_outage_eligible"


def _event_age_band(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value <= 5:
        return "0_5m"
    if value <= 15:
        return "5_15m"
    if value <= 30:
        return "15_30m"
    if value <= 60:
        return "30_60m"
    if value <= 180:
        return "60_180m"
    return "180m_plus"


def _lifecycle_bridge_use(row: dict[str, str]) -> str:
    status = str(row.get("match_status") or "").strip().lower()
    if status == "matched":
        return "matched_audit_only"
    if status == "ambiguous":
        return "ambiguous_audit_only"
    if status in {"feeder_candidate_only", "candidate_only"}:
        return "candidate_audit_only"
    return "not_available"


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


def _safe_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _redacted_ref(value: str | None) -> str:
    if not value:
        return ""
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return f"msg-{digest}"


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _to_float(value)
        if parsed is not None:
            return parsed
    return None


def _numbers(rows: list[dict[str, str]], column: str) -> list[float]:
    return [value for value in (_to_float(row.get(column)) for row in rows) if value is not None]


def _coverage(rows: list[dict[str, str]], column: str) -> float | None:
    values = [str(row.get(column) or "").strip().upper() for row in rows]
    values = [value for value in values if value in {"TRUE", "FALSE"}]
    if not values:
        return None
    return sum(1 for value in values if value == "TRUE") / len(values)


def _mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def _round_or_none(value: float | None, *, digits: int = 2) -> float | None:
    return round(float(value), digits) if value is not None else None


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


def _fmt(value: float | None, *, digits: int = 2) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def _bool_text(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def _blank(value: Any) -> str:
    return "" if value is None else str(value)
