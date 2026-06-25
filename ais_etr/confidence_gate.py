from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timedelta
from pathlib import Path
import re
from statistics import mean
from typing import Any, Iterable

from .truth_quality import GATE_COVERAGE_MAX, GATE_COVERAGE_MIN, GATE_Q50_MAE_MAX


ELIGIBILITY_COLUMNS = (
    "event_ref",
    "event_id",
    "event_time",
    "district",
    "feeder",
    "device_id",
    "source_lane",
    "match_level",
    "match_confidence",
    "affected_count",
    "active_ais_outage_confirmed",
    "event_age_band",
    "webex_device_interruption_class",
    "actual_restoration_minutes",
    "selected_model_source",
    "selected_p50",
    "selected_q10",
    "selected_q90",
    "prediction_interval_width",
    "selected_absolute_error",
    "selected_covered_q10_q90",
    "stage1_class",
    "eligibility_status",
    "recommended_send_mode",
    "blocker_reasons",
)

ELIGIBILITY_SEGMENT_COLUMNS = (
    "dimension",
    "segment",
    "rows",
    "mae",
    "coverage",
    "high_error_rows",
    "auto_p50_rows",
)

FORWARD_CAPTURE_COLUMNS = (
    "event_ref",
    "event_time",
    "feeder",
    "device_id",
    "eligibility_status",
    "stage1_class",
    "blocker_reasons",
    "cause_group",
    "work_type",
    "switching_or_isolation",
    "material_repair_required",
    "weather_or_lightning",
    "crew_dispatch_time",
    "arrival_time",
    "first_restore_time",
    "review_status",
    "reviewer",
    "reviewed_at",
    "notes",
)

FORWARD_REJECT_COLUMNS = FORWARD_CAPTURE_COLUMNS + ("source_row_number", "validation_issues")

TWO_STAGE_COLUMNS = (
    "event_ref",
    "event_id",
    "event_time",
    "district",
    "feeder",
    "device_id",
    "source_lane",
    "eligibility_status",
    "stage1_class",
    "stage2_mode",
    "public_send_allowed",
    "public_message_type",
    "public_p50",
    "public_q10",
    "public_q90",
    "metric_p50",
    "metric_q10",
    "metric_q90",
    "actual_restoration_minutes",
    "metric_absolute_error",
    "metric_covered_q10_q90",
    "forward_context_status",
    "approved_forward_context_fields",
    "reason",
)

TWO_STAGE_SEGMENT_COLUMNS = (
    "dimension",
    "segment",
    "rows",
    "auto_rows",
    "metric_rows",
    "metric_mae",
    "metric_coverage",
    "high_error_rows",
)

FORWARD_CONTEXT_FIELDS = (
    "cause_group",
    "work_type",
    "switching_or_isolation",
    "material_repair_required",
    "weather_or_lightning",
    "crew_dispatch_time",
    "arrival_time",
    "first_restore_time",
)


def build_shadow_send_eligibility(
    ais_only_readiness_csv: str | Path,
    notification_time_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    production_gate_output: str | Path | None = None,
    *,
    lifecycle_challenger_csv: str | Path | None = "runtime/ais_only_lifecycle_challenger.csv",
    remaining_time_csv: str | Path | None = "runtime/ais_only_remaining_time_challenger.csv",
    segments_output: str | Path | None = None,
    min_match_confidence: float = 0.8,
    max_auto_interval_width_minutes: float = 120.0,
    max_auto_q90_minutes: float = 180.0,
    high_error_minutes: float = 60.0,
) -> dict[str, Any]:
    readiness_rows = _read_csv(ais_only_readiness_csv)
    notification_by_ref = _read_by_key(notification_time_csv, "webex_message_ref")
    lifecycle_by_ref = _read_by_key(lifecycle_challenger_csv, "event_ref") if lifecycle_challenger_csv else {}
    remaining_by_ref = _read_by_key(remaining_time_csv, "event_ref") if remaining_time_csv else {}

    output_rows = [
        _eligibility_row(
            row,
            notification_by_ref.get(row.get("event_ref") or "", {}),
            lifecycle_by_ref.get(row.get("event_ref") or "", {}),
            remaining_by_ref.get(row.get("event_ref") or "", {}),
            min_match_confidence=min_match_confidence,
            max_auto_interval_width_minutes=max_auto_interval_width_minutes,
            max_auto_q90_minutes=max_auto_q90_minutes,
        )
        for row in readiness_rows
    ]
    _write_csv(output_csv, ELIGIBILITY_COLUMNS, output_rows)
    segments = _eligibility_segments(output_rows, high_error_minutes)
    if segments_output:
        _write_csv(segments_output, ELIGIBILITY_SEGMENT_COLUMNS, segments)
    summary = _eligibility_summary(
        output_rows,
        min_match_confidence,
        max_auto_interval_width_minutes,
        max_auto_q90_minutes,
        high_error_minutes,
    )
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_eligibility_markdown(summary, output_rows, segments), encoding="utf-8-sig")
    if production_gate_output:
        Path(production_gate_output).parent.mkdir(parents=True, exist_ok=True)
        Path(production_gate_output).write_text(_render_production_gate_markdown(summary), encoding="utf-8-sig")
    return {
        **summary,
        "ais_only_readiness_csv": str(ais_only_readiness_csv),
        "notification_time_csv": str(notification_time_csv),
        "lifecycle_challenger_csv": str(lifecycle_challenger_csv) if lifecycle_challenger_csv else None,
        "remaining_time_csv": str(remaining_time_csv) if remaining_time_csv else None,
        "output_csv": str(output_csv),
        "segments_output": str(segments_output) if segments_output else None,
        "markdown_output": str(markdown_output) if markdown_output else None,
        "production_gate_output": str(production_gate_output) if production_gate_output else None,
    }


def build_forward_capture_template(
    eligibility_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    top_n: int = 50,
) -> dict[str, Any]:
    rows = _read_csv(eligibility_csv)
    candidates = [
        row
        for row in rows
        if row.get("eligibility_status") in {"amber_human_review", "red_blocked"}
        and row.get("source_lane") == "ais_truth_matched"
    ]
    candidates.sort(key=lambda row: (_to_float(row.get("selected_absolute_error")) or -1, row.get("event_time") or ""), reverse=True)
    selected = candidates[: max(top_n, 0)]
    output_rows = [
        {
            "event_ref": row.get("event_ref", ""),
            "event_time": row.get("event_time", ""),
            "feeder": row.get("feeder", ""),
            "device_id": row.get("device_id", ""),
            "eligibility_status": row.get("eligibility_status", ""),
            "stage1_class": row.get("stage1_class", ""),
            "blocker_reasons": row.get("blocker_reasons", ""),
            "cause_group": "",
            "work_type": "",
            "switching_or_isolation": "",
            "material_repair_required": "",
            "weather_or_lightning": "",
            "crew_dispatch_time": "",
            "arrival_time": "",
            "first_restore_time": "",
            "review_status": "pending",
            "reviewer": "",
            "reviewed_at": "",
            "notes": "Fill within 24h when a reliable operational source is available; do not paste raw chat or meter lists.",
        }
        for row in selected
    ]
    _write_csv(output_csv, FORWARD_CAPTURE_COLUMNS, output_rows)
    summary = {
        "eligibility_csv": str(eligibility_csv),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "candidate_rows": len(candidates),
        "template_rows": len(output_rows),
        "top_n": top_n,
    }
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_forward_template_markdown(summary, output_rows), encoding="utf-8-sig")
    return summary


def import_forward_capture(
    input_csv: str | Path,
    output_valid_csv: str | Path,
    rejects_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    ais_only_readiness_csv: str | Path | None = None,
    first_restore_tolerance_minutes: float = 120.0,
) -> dict[str, Any]:
    candidate_by_ref = _read_by_key(ais_only_readiness_csv, "event_ref") if ais_only_readiness_csv else {}
    valid_rows: list[dict[str, str]] = []
    reject_rows: list[dict[str, str]] = []
    issue_counts: Counter[str] = Counter()
    for index, row in enumerate(_read_csv(input_csv), start=2):
        normalized = {**{column: "" for column in FORWARD_CAPTURE_COLUMNS}, **row}
        issues = _forward_validation_issues(normalized, candidate_by_ref, first_restore_tolerance_minutes)
        if issues:
            issue_counts.update(issues)
            reject_rows.append({**normalized, "source_row_number": str(index), "validation_issues": ";".join(issues)})
        else:
            valid_rows.append(normalized)
    _write_csv(output_valid_csv, FORWARD_CAPTURE_COLUMNS, valid_rows)
    _write_csv(rejects_csv, FORWARD_REJECT_COLUMNS, reject_rows)
    summary = {
        "input_csv": str(input_csv),
        "output_valid_csv": str(output_valid_csv),
        "rejects_csv": str(rejects_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "rows": len(valid_rows) + len(reject_rows),
        "valid_rows": len(valid_rows),
        "reject_rows": len(reject_rows),
        "issue_counts": dict(issue_counts.most_common()),
        "first_restore_tolerance_minutes": first_restore_tolerance_minutes,
    }
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_forward_import_markdown(summary), encoding="utf-8-sig")
    return summary


def build_two_stage_shadow_challenger(
    eligibility_csv: str | Path,
    lifecycle_challenger_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    segments_output: str | Path | None = None,
    *,
    forward_capture_validated_csv: str | Path | None = "runtime/forward_capture_validated.csv",
    high_error_minutes: float = 60.0,
) -> dict[str, Any]:
    eligibility_rows = _read_csv(eligibility_csv)
    lifecycle_by_ref = _read_by_key(lifecycle_challenger_csv, "event_ref")
    forward_by_ref = _read_by_key(forward_capture_validated_csv, "event_ref") if forward_capture_validated_csv else {}
    output_rows = [
        _two_stage_row(row, lifecycle_by_ref.get(row.get("event_ref") or "", {}), forward_by_ref.get(row.get("event_ref") or "", {}))
        for row in eligibility_rows
    ]
    _write_csv(output_csv, TWO_STAGE_COLUMNS, output_rows)
    segments = _two_stage_segments(output_rows, high_error_minutes)
    if segments_output:
        _write_csv(segments_output, TWO_STAGE_SEGMENT_COLUMNS, segments)
    summary = _two_stage_summary(output_rows, high_error_minutes)
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_two_stage_markdown(summary, output_rows, segments), encoding="utf-8-sig")
    return {
        **summary,
        "eligibility_csv": str(eligibility_csv),
        "lifecycle_challenger_csv": str(lifecycle_challenger_csv),
        "forward_capture_validated_csv": str(forward_capture_validated_csv) if forward_capture_validated_csv else None,
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "segments_output": str(segments_output) if segments_output else None,
    }


def _eligibility_row(
    row: dict[str, str],
    notification: dict[str, str],
    lifecycle: dict[str, str],
    remaining: dict[str, str],
    *,
    min_match_confidence: float,
    max_auto_interval_width_minutes: float,
    max_auto_q90_minutes: float,
) -> dict[str, str]:
    event_ref = row.get("event_ref", "")
    selected_p50 = _first_float(lifecycle.get("lifecycle_v3_p50"), remaining.get("challenger_p50"), row.get("current_p50"))
    selected_q10 = _first_float(lifecycle.get("lifecycle_v3_q10"), remaining.get("challenger_q10"), row.get("current_q10"))
    selected_q90 = _first_float(lifecycle.get("lifecycle_v3_q90"), remaining.get("challenger_q90"), row.get("current_q90"))
    selected_error = _first_float(lifecycle.get("lifecycle_v3_absolute_error"), remaining.get("challenger_absolute_error"), row.get("current_absolute_error"))
    selected_covered = _normalize_bool_text(
        lifecycle.get("lifecycle_v3_covered_q10_q90")
        or remaining.get("challenger_covered_q10_q90")
        or row.get("current_covered_q10_q90")
    )
    interval_width = selected_q90 - selected_q10 if selected_q90 is not None and selected_q10 is not None else None
    match_level = _normalize_key(row.get("match_level")).lower()
    match_confidence = _to_float(row.get("match_confidence"))
    affected_count = _to_float(row.get("affected_count"))
    active_confirmed = _normalize_bool_text(notification.get("active_ais_outage_confirmed"))
    webex_device_state = notification.get("webex_device_interruption_class", "")
    source_lane = row.get("source_lane", "")
    reasons: list[str] = []

    if source_lane == "pea_quarantined":
        reasons.append("pea_quarantined")
    if source_lane == "webex_trigger_no_ais_truth":
        reasons.append("missing_ais_truth")
    if source_lane != "ais_truth_matched" and not reasons:
        reasons.append("not_ais_truth_matched")
    if row.get("model_metric_included") not in {"true", "TRUE", "True"} and source_lane == "ais_truth_matched":
        reasons.append("not_model_metric_included")
    if (affected_count or 0) <= 0:
        reasons.append("no_affected_ais")
    if not match_level:
        reasons.append("missing_protection_match")
    if match_level == "feeder":
        reasons.append("feeder_fallback_shadow_only")
    if match_confidence is None or match_confidence < min_match_confidence:
        reasons.append("low_match_confidence")
    if source_lane == "ais_truth_matched" and active_confirmed != "TRUE":
        reasons.append("no_active_ais_evidence")
    if source_lane == "ais_truth_matched" and webex_device_state == "momentary_le_1m":
        reasons.append("momentary_webex_requires_review")
    if interval_width is None:
        reasons.append("missing_prediction_interval")
    elif interval_width > max_auto_interval_width_minutes:
        reasons.append("wide_prediction_interval")
    if selected_q90 is not None and selected_q90 > max_auto_q90_minutes:
        reasons.append("long_outage_risk")
    if selected_p50 is None:
        reasons.append("missing_prediction")

    stage1 = _stage1_class(selected_p50, selected_q90, interval_width, row, notification, reasons, max_auto_q90_minutes)
    status, send_mode = _eligibility_status(source_lane, reasons, stage1)
    model_source = "lifecycle_v3" if lifecycle else ("remaining_time_v2" if remaining else "current_model")
    return {
        "event_ref": event_ref,
        "event_id": notification.get("event_id", "") or lifecycle.get("event_id", "") or remaining.get("event_id", ""),
        "event_time": row.get("event_time", ""),
        "district": row.get("district", ""),
        "feeder": row.get("feeder", ""),
        "device_id": row.get("device_id", ""),
        "source_lane": source_lane,
        "match_level": row.get("match_level", ""),
        "match_confidence": row.get("match_confidence", ""),
        "affected_count": row.get("affected_count", ""),
        "active_ais_outage_confirmed": active_confirmed,
        "event_age_band": notification.get("event_age_band", ""),
        "webex_device_interruption_class": webex_device_state,
        "actual_restoration_minutes": row.get("actual_restoration_minutes", ""),
        "selected_model_source": model_source,
        "selected_p50": _fmt(selected_p50),
        "selected_q10": _fmt(selected_q10),
        "selected_q90": _fmt(selected_q90),
        "prediction_interval_width": _fmt(interval_width),
        "selected_absolute_error": _fmt(selected_error),
        "selected_covered_q10_q90": selected_covered,
        "stage1_class": stage1,
        "eligibility_status": status,
        "recommended_send_mode": send_mode,
        "blocker_reasons": ";".join(_dedupe(reasons)),
    }


def _stage1_class(
    p50: float | None,
    q90: float | None,
    width: float | None,
    row: dict[str, str],
    notification: dict[str, str],
    reasons: list[str],
    max_auto_q90_minutes: float,
) -> str:
    if row.get("source_lane") != "ais_truth_matched" or "missing_prediction" in reasons:
        return "uncertain"
    if "long_outage_risk" in reasons or (q90 is not None and q90 > max_auto_q90_minutes) or (p50 is not None and p50 >= max_auto_q90_minutes):
        return "long_outage_risk"
    if width is None or "wide_prediction_interval" in reasons or "momentary_webex_requires_review" in reasons:
        return "uncertain"
    if notification.get("notification_time_gate") and notification.get("notification_time_gate") != "shadow_etr_candidate":
        return "uncertain"
    return "normal"


def _eligibility_status(source_lane: str, reasons: list[str], stage1: str) -> tuple[str, str]:
    blocker_set = set(reasons)
    if source_lane == "webex_trigger_no_ais_truth" or "missing_ais_truth" in blocker_set:
        return "monitor_only", "monitor_parser_and_matching_only"
    if source_lane == "pea_quarantined" or "pea_quarantined" in blocker_set:
        return "red_blocked", "no_customer_send"
    hard_blockers = {
        "not_ais_truth_matched",
        "not_model_metric_included",
        "no_affected_ais",
        "missing_protection_match",
        "feeder_fallback_shadow_only",
        "low_match_confidence",
        "no_active_ais_evidence",
        "missing_prediction",
    }
    if blocker_set & hard_blockers:
        return "red_blocked", "no_customer_send"
    review_blockers = {
        "wide_prediction_interval",
        "long_outage_risk",
        "missing_prediction_interval",
        "momentary_webex_requires_review",
    }
    if stage1 in {"long_outage_risk", "uncertain"} or blocker_set & review_blockers:
        return "amber_human_review", "status_only_or_human_approved"
    return "green_auto_candidate", "shadow_auto_etr_candidate"


def _eligibility_segments(rows: list[dict[str, str]], high_error_minutes: float) -> list[dict[str, str]]:
    output = []
    for dimension in ("eligibility_status", "stage1_class", "source_lane", "blocker_reasons", "feeder"):
        groups: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            groups.setdefault(row.get(dimension) or "<blank>", []).append(row)
        for segment, values in groups.items():
            metric_values = [row for row in values if row.get("source_lane") == "ais_truth_matched"]
            errors = _numbers(metric_values, "selected_absolute_error")
            output.append(
                {
                    "dimension": dimension,
                    "segment": segment,
                    "rows": str(len(values)),
                    "mae": _fmt(_mean_or_none(errors)),
                    "coverage": _fmt(_coverage(metric_values, "selected_covered_q10_q90"), digits=3),
                    "high_error_rows": str(sum(1 for value in errors if value >= high_error_minutes)),
                    "auto_p50_rows": str(sum(1 for row in values if row.get("recommended_send_mode") == "shadow_auto_etr_candidate")),
                }
            )
    return sorted(output, key=lambda row: (row["dimension"], -_to_int(row["rows"]), row["segment"]))


def _eligibility_summary(
    rows: list[dict[str, str]],
    min_match_confidence: float,
    max_auto_interval_width_minutes: float,
    max_auto_q90_minutes: float,
    high_error_minutes: float,
) -> dict[str, Any]:
    status_counts = Counter(row.get("eligibility_status") or "<blank>" for row in rows)
    stage_counts = Counter(row.get("stage1_class") or "<blank>" for row in rows)
    green_rows = [row for row in rows if row.get("eligibility_status") == "green_auto_candidate"]
    metric_rows = [row for row in rows if row.get("source_lane") == "ais_truth_matched"]
    green_mae = _mean_or_none(_numbers(green_rows, "selected_absolute_error"))
    green_coverage = _coverage(green_rows, "selected_covered_q10_q90")
    return {
        "rows": len(rows),
        "ais_truth_matched_rows": len(metric_rows),
        "green_auto_candidate_rows": len(green_rows),
        "amber_human_review_rows": status_counts.get("amber_human_review", 0),
        "red_blocked_rows": status_counts.get("red_blocked", 0),
        "monitor_only_rows": status_counts.get("monitor_only", 0),
        "eligibility_status_counts": dict(status_counts.most_common()),
        "stage1_class_counts": dict(stage_counts.most_common()),
        "green_q50_mae_minutes": _round_or_none(green_mae),
        "green_q10_q90_coverage": _round_or_none(green_coverage, digits=3),
        "green_high_error_rows": sum(1 for value in _numbers(green_rows, "selected_absolute_error") if value >= high_error_minutes),
        "all_ais_q50_mae_minutes": _round_or_none(_mean_or_none(_numbers(metric_rows, "selected_absolute_error"))),
        "all_ais_q10_q90_coverage": _round_or_none(_coverage(metric_rows, "selected_covered_q10_q90"), digits=3),
        "production_gate_status": _production_gate_status(green_rows, green_mae, green_coverage),
        "min_match_confidence": min_match_confidence,
        "max_auto_interval_width_minutes": max_auto_interval_width_minutes,
        "max_auto_q90_minutes": max_auto_q90_minutes,
        "high_error_minutes": high_error_minutes,
    }


def _production_gate_status(green_rows: list[dict[str, str]], mae: float | None, coverage: float | None) -> str:
    if not green_rows:
        return "blocked_no_green_subset"
    if mae is not None and coverage is not None and mae <= GATE_Q50_MAE_MAX and GATE_COVERAGE_MIN <= coverage <= GATE_COVERAGE_MAX:
        return "shadow_green_subset_passed_requires_human_approval"
    return "blocked_metric_gate_failed"


def _forward_validation_issues(
    row: dict[str, str],
    candidate_by_ref: dict[str, dict[str, str]],
    first_restore_tolerance_minutes: float,
) -> list[str]:
    issues: list[str] = []
    status = str(row.get("review_status") or "").strip().lower()
    if status != "approved":
        issues.append("review_status_not_approved")
    event_ref = str(row.get("event_ref") or "").strip()
    if not event_ref:
        issues.append("missing_event_ref")
    candidate = candidate_by_ref.get(event_ref)
    if candidate_by_ref and event_ref and not candidate:
        issues.append("event_ref_not_in_ais_truth_matched")
    fields = _approved_forward_context_fields(row)
    if not fields:
        issues.append("approved_row_has_no_context_fields")
    dispatch = _parse_optional_time(row, "crew_dispatch_time", issues)
    arrival = _parse_optional_time(row, "arrival_time", issues)
    first_restore = _parse_optional_time(row, "first_restore_time", issues)
    event_time = _parse_dt(row.get("event_time") or (candidate or {}).get("event_time"))
    if dispatch and arrival and arrival < dispatch:
        issues.append("arrival_before_dispatch")
    if first_restore and dispatch and first_restore < dispatch:
        issues.append("first_restore_before_dispatch")
    if first_restore and arrival and first_restore < arrival:
        issues.append("first_restore_before_arrival")
    if first_restore and event_time and first_restore < event_time:
        issues.append("first_restore_before_event_time")
    if first_restore and event_time and candidate:
        actual = _to_float(candidate.get("actual_restoration_minutes"))
        if actual is not None:
            expected = event_time + timedelta(minutes=actual)
            delta = abs((first_restore - expected).total_seconds()) / 60
            if delta > first_restore_tolerance_minutes:
                issues.append("first_restore_conflicts_with_ais_truth")
    return _dedupe(issues)


def _two_stage_row(row: dict[str, str], lifecycle: dict[str, str], forward: dict[str, str]) -> dict[str, str]:
    stage1 = row.get("stage1_class") or "uncertain"
    eligibility = row.get("eligibility_status") or ""
    forward_fields = _approved_forward_context_fields(forward)
    forward_status = "approved_context_available" if forward else "missing_context"
    if forward and not forward_fields:
        forward_status = "approved_without_context_fields"

    metric_p50 = _first_float(lifecycle.get("lifecycle_v3_p50"), row.get("selected_p50"))
    metric_q10 = _first_float(lifecycle.get("lifecycle_v3_q10"), row.get("selected_q10"))
    metric_q90 = _first_float(lifecycle.get("lifecycle_v3_q90"), row.get("selected_q90"))
    actual = _to_float(row.get("actual_restoration_minutes"))
    mode = "status_only_review"
    public_allowed = "FALSE"
    public_type = "status_only"
    public_p50 = public_q10 = public_q90 = ""
    reason = "not eligible for automatic p50 send"
    if eligibility == "green_auto_candidate" and stage1 == "normal":
        mode = "auto_etr_range"
        public_allowed = "TRUE"
        public_type = "etr_range"
        public_p50 = _fmt(metric_p50)
        public_q10 = _fmt(metric_q10)
        public_q90 = _fmt(metric_q90)
        reason = "green candidate with normal outage classification"
    elif eligibility == "amber_human_review":
        public_type = "human_review_required"
        reason = "amber risk requires human review or status-only message"
    elif eligibility == "monitor_only":
        mode = "monitor_only"
        public_type = "monitor_only"
        reason = "missing AIS truth; monitor parser and matching only"
    elif eligibility == "red_blocked":
        mode = "blocked"
        public_type = "no_customer_send"
        reason = "blocked by eligibility policy"
    error = abs(metric_p50 - actual) if metric_p50 is not None and actual is not None else None
    return {
        "event_ref": row.get("event_ref", ""),
        "event_id": row.get("event_id", ""),
        "event_time": row.get("event_time", ""),
        "district": row.get("district", ""),
        "feeder": row.get("feeder", ""),
        "device_id": row.get("device_id", ""),
        "source_lane": row.get("source_lane", ""),
        "eligibility_status": eligibility,
        "stage1_class": stage1,
        "stage2_mode": mode,
        "public_send_allowed": public_allowed,
        "public_message_type": public_type,
        "public_p50": public_p50,
        "public_q10": public_q10,
        "public_q90": public_q90,
        "metric_p50": _fmt(metric_p50),
        "metric_q10": _fmt(metric_q10),
        "metric_q90": _fmt(metric_q90),
        "actual_restoration_minutes": row.get("actual_restoration_minutes", ""),
        "metric_absolute_error": _fmt(error),
        "metric_covered_q10_q90": _bool_str(_covered(actual, metric_q10, metric_q90)),
        "forward_context_status": forward_status,
        "approved_forward_context_fields": ";".join(forward_fields),
        "reason": reason,
    }


def _two_stage_segments(rows: list[dict[str, str]], high_error_minutes: float) -> list[dict[str, str]]:
    output = []
    for dimension in ("stage1_class", "stage2_mode", "eligibility_status", "public_message_type", "forward_context_status"):
        groups: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            groups.setdefault(row.get(dimension) or "<blank>", []).append(row)
        for segment, values in groups.items():
            metric_values = [row for row in values if row.get("source_lane") == "ais_truth_matched" and row.get("metric_p50")]
            errors = _numbers(metric_values, "metric_absolute_error")
            output.append(
                {
                    "dimension": dimension,
                    "segment": segment,
                    "rows": str(len(values)),
                    "auto_rows": str(sum(1 for row in values if row.get("public_send_allowed") == "TRUE")),
                    "metric_rows": str(len(metric_values)),
                    "metric_mae": _fmt(_mean_or_none(errors)),
                    "metric_coverage": _fmt(_coverage(metric_values, "metric_covered_q10_q90"), digits=3),
                    "high_error_rows": str(sum(1 for value in errors if value >= high_error_minutes)),
                }
            )
    return sorted(output, key=lambda row: (row["dimension"], -_to_int(row["rows"]), row["segment"]))


def _two_stage_summary(rows: list[dict[str, str]], high_error_minutes: float) -> dict[str, Any]:
    auto_rows = [row for row in rows if row.get("public_send_allowed") == "TRUE"]
    ais_metric_rows = [row for row in rows if row.get("source_lane") == "ais_truth_matched" and row.get("metric_p50")]
    auto_errors = _numbers(auto_rows, "metric_absolute_error")
    return {
        "rows": len(rows),
        "auto_etr_range_rows": len(auto_rows),
        "status_only_or_review_rows": sum(1 for row in rows if row.get("public_send_allowed") != "TRUE"),
        "ais_metric_rows": len(ais_metric_rows),
        "auto_q50_mae_minutes": _round_or_none(_mean_or_none(auto_errors)),
        "auto_q10_q90_coverage": _round_or_none(_coverage(auto_rows, "metric_covered_q10_q90"), digits=3),
        "auto_high_error_rows": sum(1 for value in auto_errors if value >= high_error_minutes),
        "all_ais_metric_mae_minutes": _round_or_none(_mean_or_none(_numbers(ais_metric_rows, "metric_absolute_error"))),
        "all_ais_metric_coverage": _round_or_none(_coverage(ais_metric_rows, "metric_covered_q10_q90"), digits=3),
        "message_type_counts": dict(Counter(row.get("public_message_type") or "<blank>" for row in rows).most_common()),
        "high_error_minutes": high_error_minutes,
        "production_gate_status": _production_gate_status(auto_rows, _mean_or_none(auto_errors), _coverage(auto_rows, "metric_covered_q10_q90")),
    }


def _render_eligibility_markdown(summary: dict[str, Any], rows: list[dict[str, str]], segments: list[dict[str, str]]) -> str:
    status_segments = [row for row in segments if row.get("dimension") == "eligibility_status"]
    high_risk = sorted(
        [
            row
            for row in rows
            if row.get("source_lane") == "ais_truth_matched"
            and _to_float(row.get("selected_absolute_error")) is not None
        ],
        key=lambda row: _to_float(row.get("selected_absolute_error")) or 0,
        reverse=True,
    )[:10]
    lines = [
        "# Shadow Send Eligibility",
        "",
        "This report gates shadow ETR sends by confidence. It does not send production AIS notifications and does not update model artifacts.",
        "",
        "## Summary",
        "",
        f"- Rows: {summary['rows']}",
        f"- AIS truth matched rows: {summary['ais_truth_matched_rows']}",
        f"- Green auto candidates: {summary['green_auto_candidate_rows']}",
        f"- Amber human review: {summary['amber_human_review_rows']}",
        f"- Red blocked: {summary['red_blocked_rows']}",
        f"- Monitor only: {summary['monitor_only_rows']}",
        f"- Green q50 MAE: {_blank(summary['green_q50_mae_minutes'])} min",
        f"- Green q10-q90 coverage: {_blank(summary['green_q10_q90_coverage'])}",
        f"- Production gate status: {summary['production_gate_status']}",
        "",
        "## Eligibility Mix",
        "",
        "| Status | Rows | MAE | Coverage | High-error | Auto p50 rows |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in status_segments:
        lines.append(
            f"| `{row['segment']}` | {row['rows']} | {row['mae']} | {row['coverage']} | {row['high_error_rows']} | {row['auto_p50_rows']} |"
        )
    lines.extend(
        [
            "",
            "## Highest-Risk Backtest Rows",
            "",
            "| Event | Time | Feeder | Device | Status | Stage | Error | Reasons |",
            "| --- | --- | --- | --- | --- | --- | ---: | --- |",
        ]
    )
    for row in high_risk:
        lines.append(
            "| {ref} | {time} | {feeder} | {device} | {status} | {stage} | {error} | {reasons} |".format(
                ref=row.get("event_ref", ""),
                time=row.get("event_time", ""),
                feeder=row.get("feeder", ""),
                device=row.get("device_id", ""),
                status=row.get("eligibility_status", ""),
                stage=row.get("stage1_class", ""),
                error=row.get("selected_absolute_error", ""),
                reasons=row.get("blocker_reasons", ""),
            )
        )
    lines.extend(_guardrail_lines())
    return "\n".join(lines) + "\n"


def _render_production_gate_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Production Readiness Gate",
        "",
        "Production AIS send remains blocked unless the green subset passes metric gates and receives human approval.",
        "",
        "## Gate",
        "",
        f"- Green rows: {summary['green_auto_candidate_rows']}",
        f"- Green q50 MAE: {_blank(summary['green_q50_mae_minutes'])} min",
        f"- Green q10-q90 coverage: {_blank(summary['green_q10_q90_coverage'])}",
        f"- Gate target: q50 MAE <= {GATE_Q50_MAE_MAX:g} min and q10-q90 coverage {GATE_COVERAGE_MIN:g}-{GATE_COVERAGE_MAX:g}",
        f"- Status: {summary['production_gate_status']}",
        "",
        "## Allowed Actions",
        "",
        "- `green_auto_candidate`: shadow auto ETR candidate only until production approval.",
        "- `amber_human_review`: status-only or human-approved message.",
        "- `red_blocked`: no customer send.",
        "- `monitor_only`: parser/matching monitoring only.",
    ]
    lines.extend(_guardrail_lines())
    return "\n".join(lines) + "\n"


def _render_forward_template_markdown(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Forward Capture Template",
        "",
        "This template is for reliable operational context captured soon after new events. Historical unknowns can remain unresolved.",
        "",
        "## Summary",
        "",
        f"- Candidate rows: {summary['candidate_rows']}",
        f"- Template rows: {summary['template_rows']}",
        "",
        "## Required Handling",
        "",
        "- Use `review_status=approved` only when a reliable source exists.",
        "- Leave uncertain rows as `pending` or mark `rejected`; do not guess.",
        "- Do not paste raw chats, room IDs, PEANO lists, customer names, or secrets.",
    ]
    lines.extend(_guardrail_lines())
    return "\n".join(lines) + "\n"


def _render_forward_import_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Forward Capture Import",
        "",
        "Validated forward-capture rows are context candidates only; AIS outage/restore remains the truth label.",
        "",
        "## Summary",
        "",
        f"- Rows: {summary['rows']}",
        f"- Valid rows: {summary['valid_rows']}",
        f"- Reject rows: {summary['reject_rows']}",
        "",
        "## Issue Counts",
        "",
        "| Issue | Rows |",
        "| --- | ---: |",
    ]
    for issue, count in (summary.get("issue_counts") or {}).items():
        lines.append(f"| `{issue}` | {count} |")
    lines.extend(_guardrail_lines())
    return "\n".join(lines) + "\n"


def _render_two_stage_markdown(summary: dict[str, Any], rows: list[dict[str, str]], segments: list[dict[str, str]]) -> str:
    mode_segments = [row for row in segments if row.get("dimension") == "stage2_mode"]
    lines = [
        "# Two-Stage Shadow Challenger",
        "",
        "Stage 1 classifies normal, long-outage risk, or uncertain. Stage 2 only exposes ETR ranges for green normal rows.",
        "",
        "## Summary",
        "",
        f"- Rows: {summary['rows']}",
        f"- Auto ETR range rows: {summary['auto_etr_range_rows']}",
        f"- Status-only/review rows: {summary['status_only_or_review_rows']}",
        f"- Auto q50 MAE: {_blank(summary['auto_q50_mae_minutes'])} min",
        f"- Auto q10-q90 coverage: {_blank(summary['auto_q10_q90_coverage'])}",
        f"- Auto high-error rows: {summary['auto_high_error_rows']}",
        f"- Production gate status: {summary['production_gate_status']}",
        "",
        "## Stage 2 Mix",
        "",
        "| Mode | Rows | Auto rows | Metric rows | MAE | Coverage | High-error |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in mode_segments:
        lines.append(
            f"| `{row['segment']}` | {row['rows']} | {row['auto_rows']} | {row['metric_rows']} | {row['metric_mae']} | {row['metric_coverage']} | {row['high_error_rows']} |"
        )
    lines.extend(_guardrail_lines())
    return "\n".join(lines) + "\n"


def _guardrail_lines() -> list[str]:
    return [
        "",
        "## Guardrails",
        "",
        "- AIS outage/restore remains the only customer-facing truth label.",
        "- WebEx is trigger/device evidence only.",
        "- PEA/SFSD/ReportPO quarantine rows are not used in metrics, features, fallback, or truth.",
        "- No production AIS send is performed by these commands.",
        "- Outputs omit source chat bodies, room identifiers, credentials, customer meter identifier lists, and customer identity fields.",
    ]


def _approved_forward_context_fields(row: dict[str, str]) -> list[str]:
    return [column for column in FORWARD_CONTEXT_FIELDS if str(row.get(column) or "").strip()]


def _parse_optional_time(row: dict[str, str], column: str, issues: list[str]) -> datetime | None:
    text = str(row.get(column) or "").strip()
    if not text:
        return None
    parsed = _parse_dt(text)
    if parsed is None:
        issues.append(f"invalid_{column}")
    return parsed


def _read_by_key(path: str | Path | None, key: str) -> dict[str, dict[str, str]]:
    if not path or not Path(path).exists():
        return {}
    output: dict[str, dict[str, str]] = {}
    for row in _read_csv(path):
        value = row.get(key) or ""
        if value and value not in output:
            output[value] = row
    return output


def _read_csv(path: str | Path | None) -> list[dict[str, str]]:
    if not path:
        return []
    source = Path(path)
    if not source.exists():
        return []
    with source.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: str | Path, columns: Iterable[str], rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _coverage(rows: list[dict[str, str]], column: str) -> float | None:
    values = [str(row.get(column) or "").upper() for row in rows if str(row.get(column) or "").strip()]
    if not values:
        return None
    return sum(1 for value in values if value == "TRUE") / len(values)


def _covered(actual: float | None, lower: float | None, upper: float | None) -> bool | None:
    if actual is None or lower is None or upper is None:
        return None
    return lower <= actual <= upper


def _numbers(rows: list[dict[str, str]], column: str) -> list[float]:
    return [value for value in (_to_float(row.get(column)) for row in rows) if value is not None]


def _mean_or_none(values: list[float]) -> float | None:
    return mean(values) if values else None


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


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _to_float(value)
        if parsed is not None:
            return parsed
    return None


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: Any) -> int:
    numeric = _to_float(value)
    return int(numeric) if numeric is not None else 0


def _round_or_none(value: float | None, *, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _bool_str(value: bool | None) -> str:
    if value is None:
        return ""
    return "TRUE" if value else "FALSE"


def _normalize_bool_text(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"TRUE", "FALSE"}:
        return text
    if text in {"1", "YES", "Y"}:
        return "TRUE"
    if text in {"0", "NO", "N"}:
        return "FALSE"
    return ""


def _fmt(value: float | None, *, digits: int = 2) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def _blank(value: Any) -> str:
    return "" if value is None else str(value)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output
