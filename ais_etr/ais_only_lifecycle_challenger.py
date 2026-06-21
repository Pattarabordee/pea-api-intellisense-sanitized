from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timedelta
from pathlib import Path
import re
from statistics import mean
from typing import Any, Iterable

from .truth_quality import GATE_COVERAGE_MAX, GATE_COVERAGE_MIN, GATE_Q50_MAE_MAX


VALIDATED_REVIEW_COLUMNS = (
    "event_ref",
    "event_time",
    "feeder",
    "device_id",
    "active_error_minutes",
    "suspected_gap",
    "outage_cause",
    "work_type",
    "crew_dispatch_time",
    "arrival_time",
    "first_restore_time",
    "switching_or_isolation",
    "material_or_repair_required",
    "weather_or_lightning",
    "review_status",
    "reviewer",
    "reviewed_at",
    "approved_context_fields",
    "lifecycle_risk_flags",
    "validation_status",
    "notes",
)

REJECT_COLUMNS = VALIDATED_REVIEW_COLUMNS + ("source_row_number", "validation_issues")

FEATURE_AUDIT_COLUMNS = (
    "event_ref",
    "event_time",
    "feeder",
    "device_id",
    "source_lane",
    "model_metric_included",
    "review_status",
    "feature_status",
    "approved_context_fields",
    "lifecycle_risk_flags",
    "validation_issues",
    "recommended_action",
)

CHALLENGER_COLUMNS = (
    "event_id",
    "event_ref",
    "event_time",
    "district",
    "feeder",
    "device_id",
    "actual_restoration_minutes",
    "current_p50",
    "current_q10",
    "current_q90",
    "current_absolute_error",
    "current_covered_q10_q90",
    "active_state_p50",
    "active_state_absolute_error",
    "active_state_covered_q10_q90",
    "remaining_v2_p50",
    "remaining_v2_q10",
    "remaining_v2_q90",
    "remaining_v2_absolute_error",
    "remaining_v2_covered_q10_q90",
    "review_status",
    "lifecycle_feature_status",
    "approved_context_fields",
    "outage_cause",
    "work_type",
    "lifecycle_risk_flags",
    "lifecycle_source",
    "lifecycle_prior_rows_used",
    "selected_q10",
    "selected_q50",
    "selected_q75",
    "selected_q90",
    "lifecycle_v3_p50",
    "lifecycle_v3_q10",
    "lifecycle_v3_q90",
    "lifecycle_v3_absolute_error",
    "lifecycle_v3_covered_q10_q90",
    "error_delta_v3_minus_v2",
    "lifecycle_notes",
)

SEGMENT_COLUMNS = (
    "dimension",
    "segment",
    "rows",
    "current_mae",
    "active_state_mae",
    "remaining_v2_mae",
    "lifecycle_v3_mae",
    "mae_delta_v3_minus_v2",
    "current_coverage",
    "remaining_v2_coverage",
    "lifecycle_v3_coverage",
    "remaining_v2_high_error_rows",
    "lifecycle_v3_high_error_rows",
)

CONTEXT_FIELDS = (
    "outage_cause",
    "work_type",
    "crew_dispatch_time",
    "arrival_time",
    "first_restore_time",
    "switching_or_isolation",
    "material_or_repair_required",
    "weather_or_lightning",
)

BLOCKED_TRUTH_FIELD_PATTERNS = (
    "cl_datetime",
    "cldatetime",
    "event_end_time",
    "eventendtime",
    "ticket_close_time",
    "ticket_closed_time",
    "close_time",
    "closed_time",
    "job_close_time",
    "etr_time",
)


def build_ais_only_lifecycle_challenger(
    ais_only_readiness_csv: str | Path,
    remaining_time_csv: str | Path,
    lifecycle_review_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    feature_audit_output: str | Path | None = None,
    valid_output: str | Path | None = None,
    rejects_output: str | Path | None = None,
    segments_output: str | Path | None = None,
    *,
    min_lifecycle_prior_rows: int = 2,
    high_error_minutes: float = 60.0,
    first_restore_tolerance_minutes: float = 120.0,
) -> dict[str, Any]:
    if min_lifecycle_prior_rows < 1:
        raise ValueError("min_lifecycle_prior_rows must be at least 1")

    readiness_rows = _read_csv(ais_only_readiness_csv)
    candidates = [
        row
        for row in readiness_rows
        if row.get("source_lane") == "ais_truth_matched"
        and row.get("model_metric_included") == "true"
        and (_to_float(row.get("actual_restoration_minutes")) or 0) > 5
    ]
    candidates.sort(key=lambda row: _parse_dt(row.get("event_time")) or datetime.max)
    candidate_by_ref = {row.get("event_ref") or "": row for row in candidates if row.get("event_ref")}

    validated_reviews, rejected_reviews = _validate_lifecycle_reviews(
        lifecycle_review_csv,
        candidate_by_ref,
        first_restore_tolerance_minutes=first_restore_tolerance_minutes,
    )
    if valid_output:
        _write_csv(valid_output, VALIDATED_REVIEW_COLUMNS, validated_reviews)
    if rejects_output:
        _write_csv(rejects_output, REJECT_COLUMNS, rejected_reviews)

    approved_by_ref = {row["event_ref"]: row for row in validated_reviews if row.get("event_ref")}
    rejected_by_ref = _first_by_key(rejected_reviews, "event_ref")
    remaining_by_ref = _read_by_key(remaining_time_csv, "event_ref")

    feature_audit_rows = _feature_audit_rows(candidates, approved_by_ref, rejected_by_ref)
    if feature_audit_output:
        _write_csv(feature_audit_output, FEATURE_AUDIT_COLUMNS, feature_audit_rows)

    output_rows: list[dict[str, str]] = []
    prior_rows: list[dict[str, str]] = []
    for row in candidates:
        output_row = _build_prediction_row(
            row,
            remaining_by_ref.get(row.get("event_ref") or "", {}),
            approved_by_ref.get(row.get("event_ref") or ""),
            rejected_by_ref.get(row.get("event_ref") or ""),
            prior_rows,
            min_lifecycle_prior_rows=min_lifecycle_prior_rows,
        )
        output_rows.append(output_row)
        prior_rows.append(output_row)

    _write_csv(output_csv, CHALLENGER_COLUMNS, output_rows)
    segments = _build_segments(output_rows, high_error_minutes)
    if segments_output:
        _write_csv(segments_output, SEGMENT_COLUMNS, segments)

    summary = _summary(
        output_rows,
        validated_reviews,
        rejected_reviews,
        feature_audit_rows,
        segments,
        min_lifecycle_prior_rows,
        high_error_minutes,
        first_restore_tolerance_minutes,
    )
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_markdown(summary, output_rows, segments), encoding="utf-8-sig")

    return {
        **summary,
        "ais_only_readiness_csv": str(ais_only_readiness_csv),
        "remaining_time_csv": str(remaining_time_csv),
        "lifecycle_review_csv": str(lifecycle_review_csv),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "feature_audit_output": str(feature_audit_output) if feature_audit_output else None,
        "valid_output": str(valid_output) if valid_output else None,
        "rejects_output": str(rejects_output) if rejects_output else None,
        "segments_output": str(segments_output) if segments_output else None,
    }


def _validate_lifecycle_reviews(
    path: str | Path,
    candidate_by_ref: dict[str, dict[str, str]],
    *,
    first_restore_tolerance_minutes: float,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows = _read_csv(path)
    valid_rows: list[dict[str, str]] = []
    reject_rows: list[dict[str, str]] = []
    for index, row in enumerate(rows, start=2):
        normalized = {**{column: "" for column in VALIDATED_REVIEW_COLUMNS}, **row}
        issues = _review_validation_issues(normalized, candidate_by_ref, first_restore_tolerance_minutes)
        context_fields = _approved_context_fields(normalized)
        risk_flags = _risk_flags(normalized)
        normalized["approved_context_fields"] = ";".join(context_fields)
        normalized["lifecycle_risk_flags"] = ";".join(risk_flags)
        normalized["validation_status"] = "valid" if not issues else "rejected"
        if issues:
            reject_rows.append(
                {
                    **normalized,
                    "source_row_number": str(index),
                    "validation_issues": ";".join(issues),
                }
            )
        else:
            valid_rows.append(normalized)
    return valid_rows, reject_rows


def _review_validation_issues(
    row: dict[str, str],
    candidate_by_ref: dict[str, dict[str, str]],
    first_restore_tolerance_minutes: float,
) -> list[str]:
    issues: list[str] = []
    event_ref = str(row.get("event_ref") or "").strip()
    status = str(row.get("review_status") or "").strip().lower()
    if status != "approved":
        issues.append("review_status_not_approved")
    if not event_ref:
        issues.append("missing_event_ref")
    candidate = candidate_by_ref.get(event_ref)
    if event_ref and not candidate:
        issues.append("event_ref_not_in_ais_truth_matched")
    if not _approved_context_fields(row):
        issues.append("approved_row_has_no_context_fields")

    for column, value in row.items():
        if str(value or "").strip() and _is_blocked_truth_field(column):
            issues.append(f"blocked_truth_field_{_safe_issue_name(column)}")

    event_time = _parse_dt(row.get("event_time") or (candidate or {}).get("event_time"))
    if str(row.get("event_time") or "").strip() and event_time is None:
        issues.append("invalid_event_time")

    dispatch = _parse_optional_time(row, "crew_dispatch_time", issues)
    arrival = _parse_optional_time(row, "arrival_time", issues)
    first_restore = _parse_optional_time(row, "first_restore_time", issues)
    if dispatch and arrival and arrival < dispatch:
        issues.append("arrival_before_dispatch")
    if first_restore and dispatch and first_restore < dispatch:
        issues.append("first_restore_before_dispatch")
    if first_restore and arrival and first_restore < arrival:
        issues.append("first_restore_before_arrival")
    if first_restore and event_time and first_restore < event_time:
        issues.append("first_restore_before_webex_event_time")
    if first_restore and event_time and candidate:
        actual = _to_float(candidate.get("actual_restoration_minutes"))
        if actual is not None:
            expected_restore = event_time + timedelta(minutes=actual)
            delta = abs((first_restore - expected_restore).total_seconds()) / 60.0
            if delta > first_restore_tolerance_minutes:
                issues.append("first_restore_conflicts_with_ais_truth")
    return _dedupe(issues)


def _parse_optional_time(row: dict[str, str], column: str, issues: list[str]) -> datetime | None:
    text = str(row.get(column) or "").strip()
    if not text:
        return None
    parsed = _parse_dt(text)
    if parsed is None:
        issues.append(f"invalid_{column}")
    return parsed


def _build_prediction_row(
    row: dict[str, str],
    remaining_v2: dict[str, str],
    approved_review: dict[str, str] | None,
    rejected_review: dict[str, str] | None,
    prior_rows: list[dict[str, str]],
    *,
    min_lifecycle_prior_rows: int,
) -> dict[str, str]:
    actual = _to_float(row.get("actual_restoration_minutes"))
    current_p50 = _to_float(row.get("current_p50"))
    current_q10 = _to_float(row.get("current_q10"))
    current_q90 = _to_float(row.get("current_q90"))
    remaining_p50 = _first_float(remaining_v2.get("challenger_p50"), current_p50)
    remaining_q10 = _first_float(remaining_v2.get("challenger_q10"), current_q10)
    remaining_q90 = _first_float(remaining_v2.get("challenger_q90"), current_q90)
    active_p50 = _to_float(remaining_v2.get("active_state_p50"))
    active_error = _to_float(remaining_v2.get("active_state_absolute_error"))
    active_covered = _normalize_bool_text(remaining_v2.get("active_state_covered_q10_q90"))

    review_status = ""
    feature_status = "missing_review"
    context_fields = ""
    risk_flags = ""
    outage_cause = ""
    work_type = ""
    source = "remaining_v2_no_lifecycle_context"
    notes = "no approved lifecycle/cause context for this event"
    values: list[float] = []
    if rejected_review:
        review_status = rejected_review.get("review_status", "")
        feature_status = "review_rejected"
        notes = "lifecycle review rejected: " + str(rejected_review.get("validation_issues") or "")
    if approved_review:
        review_status = approved_review.get("review_status", "")
        feature_status = "approved_context_available"
        context_fields = approved_review.get("approved_context_fields", "")
        risk_flags = approved_review.get("lifecycle_risk_flags", "")
        outage_cause = _clean_label(approved_review.get("outage_cause"))
        work_type = _clean_label(approved_review.get("work_type"))
        values, source, notes = _select_lifecycle_prior_values(approved_review, prior_rows, min_lifecycle_prior_rows)
        if values:
            feature_status = "approved_context_used"
        else:
            source = "approved_context_no_prior"

    selected_q10 = selected_q50 = selected_q75 = selected_q90 = None
    v3_p50 = remaining_p50
    v3_q10 = remaining_q10
    v3_q90 = remaining_q90
    if values:
        selected_q10 = _quantile(values, 0.1)
        selected_q50 = _quantile(values, 0.5)
        selected_q75 = _quantile(values, 0.75)
        selected_q90 = _quantile(values, 0.9)
        v3_p50 = max(_or_zero(remaining_p50), selected_q50)
        if risk_flags and selected_q75 > v3_p50:
            v3_p50 = selected_q75
        v3_q10 = max(0.0, min(v3_p50, selected_q10))
        v3_q90 = max(_or_zero(remaining_q90), v3_p50, selected_q90)

    current_error = abs(current_p50 - actual) if current_p50 is not None and actual is not None else None
    remaining_error = _first_float(remaining_v2.get("challenger_absolute_error"))
    if remaining_error is None and remaining_p50 is not None and actual is not None:
        remaining_error = abs(remaining_p50 - actual)
    v3_error = abs(v3_p50 - actual) if v3_p50 is not None and actual is not None else None
    return {
        "event_id": row.get("event_id", ""),
        "event_ref": row.get("event_ref", ""),
        "event_time": row.get("event_time", ""),
        "district": row.get("district", ""),
        "feeder": row.get("feeder", ""),
        "device_id": row.get("device_id", ""),
        "actual_restoration_minutes": _fmt(actual),
        "current_p50": _fmt(current_p50),
        "current_q10": _fmt(current_q10),
        "current_q90": _fmt(current_q90),
        "current_absolute_error": _fmt(current_error),
        "current_covered_q10_q90": _bool_str(_covered(actual, current_q10, current_q90)),
        "active_state_p50": _fmt(active_p50),
        "active_state_absolute_error": _fmt(active_error),
        "active_state_covered_q10_q90": active_covered,
        "remaining_v2_p50": _fmt(remaining_p50),
        "remaining_v2_q10": _fmt(remaining_q10),
        "remaining_v2_q90": _fmt(remaining_q90),
        "remaining_v2_absolute_error": _fmt(remaining_error),
        "remaining_v2_covered_q10_q90": _normalize_bool_text(remaining_v2.get("challenger_covered_q10_q90")),
        "review_status": review_status,
        "lifecycle_feature_status": feature_status,
        "approved_context_fields": context_fields,
        "outage_cause": outage_cause,
        "work_type": work_type,
        "lifecycle_risk_flags": risk_flags,
        "lifecycle_source": source,
        "lifecycle_prior_rows_used": str(len(values)),
        "selected_q10": _fmt(selected_q10),
        "selected_q50": _fmt(selected_q50),
        "selected_q75": _fmt(selected_q75),
        "selected_q90": _fmt(selected_q90),
        "lifecycle_v3_p50": _fmt(v3_p50),
        "lifecycle_v3_q10": _fmt(v3_q10),
        "lifecycle_v3_q90": _fmt(v3_q90),
        "lifecycle_v3_absolute_error": _fmt(v3_error),
        "lifecycle_v3_covered_q10_q90": _bool_str(_covered(actual, v3_q10, v3_q90)),
        "error_delta_v3_minus_v2": _fmt(_delta(v3_error, remaining_error)),
        "lifecycle_notes": notes,
    }


def _select_lifecycle_prior_values(
    review: dict[str, str],
    prior_rows: list[dict[str, str]],
    min_rows: int,
) -> tuple[list[float], str, str]:
    cause = _normalize_text_key(review.get("outage_cause"))
    work = _normalize_text_key(review.get("work_type"))
    risk = _risk_key(review.get("lifecycle_risk_flags"))

    matchers = [
        ("prior_same_cause_work", lambda row: cause and work and row.get("_cause_key") == cause and row.get("_work_key") == work),
        ("prior_same_risk_flags", lambda row: risk and row.get("_risk_key") == risk),
        ("prior_same_work_type", lambda row: work and row.get("_work_key") == work),
        ("prior_same_cause", lambda row: cause and row.get("_cause_key") == cause),
    ]
    prepared = []
    for row in prior_rows:
        actual = _to_float(row.get("actual_restoration_minutes"))
        if actual is None:
            continue
        prepared.append(
            {
                **row,
                "_actual": actual,
                "_cause_key": _normalize_text_key(row.get("outage_cause")),
                "_work_key": _normalize_text_key(row.get("work_type")),
                "_risk_key": _risk_key(row.get("lifecycle_risk_flags")),
            }
        )
    prior_statuses = {"approved_context_available", "approved_context_used"}
    for source, predicate in matchers:
        values = [row["_actual"] for row in prepared if row.get("lifecycle_feature_status") in prior_statuses and predicate(row)]
        if len(values) >= min_rows:
            return values, source, f"{source}_rows={len(values)}"
    approved_values = [
        row["_actual"] for row in prepared if row.get("lifecycle_feature_status") in prior_statuses
    ]
    if len(approved_values) >= min_rows:
        return approved_values, "prior_approved_lifecycle_global", f"approved_lifecycle_prior_rows={len(approved_values)}"
    return [], "approved_context_no_prior", "approved context exists but no time-respecting lifecycle prior met threshold"


def _feature_audit_rows(
    candidates: list[dict[str, str]],
    approved_by_ref: dict[str, dict[str, str]],
    rejected_by_ref: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    rows = []
    for row in candidates:
        event_ref = row.get("event_ref") or ""
        approved = approved_by_ref.get(event_ref)
        rejected = rejected_by_ref.get(event_ref)
        if approved:
            status = "approved_context_available"
            action = "Use as shadow-only lifecycle/cause feature candidate; AIS outage/restore remains truth."
            review_status = approved.get("review_status", "")
            fields = approved.get("approved_context_fields", "")
            risk = approved.get("lifecycle_risk_flags", "")
            issues = ""
        elif rejected:
            status = "review_rejected"
            action = "Do not use this row as a feature until review issues are repaired and approved."
            review_status = rejected.get("review_status", "")
            fields = rejected.get("approved_context_fields", "")
            risk = rejected.get("lifecycle_risk_flags", "")
            issues = rejected.get("validation_issues", "")
        else:
            status = "missing_review"
            action = "Keep v2 prediction; request owner-approved lifecycle/cause context for high-error cases."
            review_status = ""
            fields = ""
            risk = ""
            issues = ""
        rows.append(
            {
                "event_ref": event_ref,
                "event_time": row.get("event_time", ""),
                "feeder": row.get("feeder", ""),
                "device_id": row.get("device_id", ""),
                "source_lane": row.get("source_lane", ""),
                "model_metric_included": row.get("model_metric_included", ""),
                "review_status": review_status,
                "feature_status": status,
                "approved_context_fields": fields,
                "lifecycle_risk_flags": risk,
                "validation_issues": issues,
                "recommended_action": action,
            }
        )
    return rows


def _build_segments(rows: list[dict[str, str]], high_error_minutes: float) -> list[dict[str, str]]:
    output = []
    for dimension in (
        "lifecycle_feature_status",
        "lifecycle_source",
        "feeder",
        "device_id",
        "outage_cause",
        "work_type",
        "lifecycle_risk_flags",
    ):
        groups: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            groups.setdefault(row.get(dimension) or "<blank>", []).append(row)
        for segment, values in groups.items():
            output.append(_segment_row(dimension, segment, values, high_error_minutes))
    return sorted(output, key=lambda row: (row["dimension"], -_to_int(row["rows"]), row["segment"]))


def _segment_row(dimension: str, segment: str, rows: list[dict[str, str]], high_error_minutes: float) -> dict[str, str]:
    remaining_mae = _mean_or_none(_numbers(rows, "remaining_v2_absolute_error"))
    v3_mae = _mean_or_none(_numbers(rows, "lifecycle_v3_absolute_error"))
    return {
        "dimension": dimension,
        "segment": segment,
        "rows": str(len(rows)),
        "current_mae": _fmt(_mean_or_none(_numbers(rows, "current_absolute_error"))),
        "active_state_mae": _fmt(_mean_or_none(_numbers(rows, "active_state_absolute_error"))),
        "remaining_v2_mae": _fmt(remaining_mae),
        "lifecycle_v3_mae": _fmt(v3_mae),
        "mae_delta_v3_minus_v2": _fmt(_delta(v3_mae, remaining_mae)),
        "current_coverage": _fmt(_coverage(rows, "current_covered_q10_q90"), digits=3),
        "remaining_v2_coverage": _fmt(_coverage(rows, "remaining_v2_covered_q10_q90"), digits=3),
        "lifecycle_v3_coverage": _fmt(_coverage(rows, "lifecycle_v3_covered_q10_q90"), digits=3),
        "remaining_v2_high_error_rows": str(sum(1 for value in _numbers(rows, "remaining_v2_absolute_error") if value >= high_error_minutes)),
        "lifecycle_v3_high_error_rows": str(sum(1 for value in _numbers(rows, "lifecycle_v3_absolute_error") if value >= high_error_minutes)),
    }


def _summary(
    rows: list[dict[str, str]],
    validated_reviews: list[dict[str, str]],
    rejected_reviews: list[dict[str, str]],
    feature_audit_rows: list[dict[str, str]],
    segments: list[dict[str, str]],
    min_lifecycle_prior_rows: int,
    high_error_minutes: float,
    first_restore_tolerance_minutes: float,
) -> dict[str, Any]:
    current_mae = _mean_or_none(_numbers(rows, "current_absolute_error"))
    active_mae = _mean_or_none(_numbers(rows, "active_state_absolute_error"))
    v2_mae = _mean_or_none(_numbers(rows, "remaining_v2_absolute_error"))
    v3_mae = _mean_or_none(_numbers(rows, "lifecycle_v3_absolute_error"))
    v3_coverage = _coverage(rows, "lifecycle_v3_covered_q10_q90")
    status_counts = Counter(row.get("feature_status") or "<blank>" for row in feature_audit_rows)
    reject_issue_counts: Counter[str] = Counter(
        issue
        for row in rejected_reviews
        for issue in str(row.get("validation_issues") or "").split(";")
        if issue
    )
    return {
        "candidates": len(rows),
        "validated_review_rows": len(validated_reviews),
        "rejected_review_rows": len(rejected_reviews),
        "approved_feature_candidate_rows": sum(1 for row in feature_audit_rows if row.get("feature_status") == "approved_context_available"),
        "feature_status_counts": dict(status_counts.most_common()),
        "reject_issue_counts": dict(reject_issue_counts.most_common()),
        "current_q50_mae_minutes": _round_or_none(current_mae),
        "active_state_q50_mae_minutes": _round_or_none(active_mae),
        "remaining_v2_q50_mae_minutes": _round_or_none(v2_mae),
        "lifecycle_v3_q50_mae_minutes": _round_or_none(v3_mae),
        "lifecycle_v3_minus_remaining_v2_mae_minutes": _round_or_none(_delta(v3_mae, v2_mae)),
        "current_q10_q90_coverage": _round_or_none(_coverage(rows, "current_covered_q10_q90"), digits=3),
        "remaining_v2_q10_q90_coverage": _round_or_none(_coverage(rows, "remaining_v2_covered_q10_q90"), digits=3),
        "lifecycle_v3_q10_q90_coverage": _round_or_none(v3_coverage, digits=3),
        "remaining_v2_high_error_rows": sum(1 for value in _numbers(rows, "remaining_v2_absolute_error") if value >= high_error_minutes),
        "lifecycle_v3_high_error_rows": sum(1 for value in _numbers(rows, "lifecycle_v3_absolute_error") if value >= high_error_minutes),
        "min_lifecycle_prior_rows": min_lifecycle_prior_rows,
        "high_error_minutes": high_error_minutes,
        "first_restore_tolerance_minutes": first_restore_tolerance_minutes,
        "lifecycle_v3_gate_status": _gate_status(v3_mae, v3_coverage),
        "recommendation": _recommendation(len(validated_reviews), v2_mae, v3_mae, v3_coverage),
        "segment_rows": len(segments),
    }


def _render_markdown(summary: dict[str, Any], rows: list[dict[str, str]], segments: list[dict[str, str]]) -> str:
    status_counts = summary.get("feature_status_counts") or {}
    source_segments = [row for row in segments if row.get("dimension") == "lifecycle_feature_status"]
    residual = sorted(
        [row for row in rows if _to_float(row.get("lifecycle_v3_absolute_error")) is not None],
        key=lambda row: _to_float(row.get("lifecycle_v3_absolute_error")) or 0,
        reverse=True,
    )[:10]
    lines = [
        "# AIS-Only Lifecycle/Cause Challenger v3",
        "",
        "This shadow diagnostic validates owner-reviewed lifecycle/cause context, then tests it without using PEA/SFSD/ReportPO quarantine rows as truth or fallback.",
        "",
        "## Summary",
        "",
        f"- Candidate rows: {summary['candidates']}",
        f"- Validated approved review rows: {summary['validated_review_rows']}",
        f"- Rejected review rows: {summary['rejected_review_rows']}",
        f"- Current q50 MAE: {_blank(summary['current_q50_mae_minutes'])} min",
        f"- Active-state q50 MAE: {_blank(summary['active_state_q50_mae_minutes'])} min",
        f"- Remaining-time v2 q50 MAE: {_blank(summary['remaining_v2_q50_mae_minutes'])} min",
        f"- Lifecycle/cause v3 q50 MAE: {_blank(summary['lifecycle_v3_q50_mae_minutes'])} min",
        f"- v3 minus v2 MAE: {_blank(summary['lifecycle_v3_minus_remaining_v2_mae_minutes'])} min",
        f"- Remaining-time v2 q10-q90 coverage: {_blank(summary['remaining_v2_q10_q90_coverage'])}",
        f"- Lifecycle/cause v3 q10-q90 coverage: {_blank(summary['lifecycle_v3_q10_q90_coverage'])}",
        f"- Remaining-time v2 high-error rows: {summary['remaining_v2_high_error_rows']}",
        f"- Lifecycle/cause v3 high-error rows: {summary['lifecycle_v3_high_error_rows']}",
        f"- Lifecycle/cause v3 gate status: {summary['lifecycle_v3_gate_status']}",
        "",
        "## Feature Status",
        "",
        "| Status | Rows |",
        "| --- | ---: |",
    ]
    for status, count in status_counts.items():
        lines.append(f"| `{status}` | {count} |")
    lines.extend(
        [
            "",
            "## Segment Summary",
            "",
            "| Segment | Rows | v2 MAE | v3 MAE | Delta | v3 coverage | v3 high-error |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in source_segments:
        lines.append(
            "| {segment} | {rows} | {v2} | {v3} | {delta} | {cov} | {high} |".format(
                segment=row.get("segment", ""),
                rows=row.get("rows", ""),
                v2=row.get("remaining_v2_mae", ""),
                v3=row.get("lifecycle_v3_mae", ""),
                delta=row.get("mae_delta_v3_minus_v2", ""),
                cov=row.get("lifecycle_v3_coverage", ""),
                high=row.get("lifecycle_v3_high_error_rows", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Biggest Remaining Misses",
            "",
            "| Event | Time | Feeder | Device | Actual | v2 p50 | v3 p50 | v3 error | Feature status |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in residual:
        lines.append(
            "| {ref} | {time} | {feeder} | {device} | {actual} | {v2} | {v3} | {error} | {status} |".format(
                ref=row.get("event_ref", ""),
                time=row.get("event_time", ""),
                feeder=row.get("feeder", ""),
                device=row.get("device_id", ""),
                actual=row.get("actual_restoration_minutes", ""),
                v2=row.get("remaining_v2_p50", ""),
                v3=row.get("lifecycle_v3_p50", ""),
                error=row.get("lifecycle_v3_absolute_error", ""),
                status=row.get("lifecycle_feature_status", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            str(summary["recommendation"]),
            "",
            "## Guardrails",
            "",
            "- AIS outage/restore remains the only customer-facing truth label.",
            "- WebEx remains trigger/device evidence only.",
            "- PEA/SFSD/ReportPO quarantine rows are not used in metrics, features, fallback, or truth.",
            "- `cl_datetime`, ticket close time, `EVENT_END_TIME`, and historical ETR timestamps are blocked from truth use.",
            "- This command does not overwrite `runtime/model_quantiles.json` and does not send production AIS notifications.",
            "- Outputs omit source chat bodies, room identifiers, credentials, customer meter identifier lists, and customer identity fields.",
        ]
    )
    return "\n".join(lines) + "\n"


def _recommendation(validated_count: int, v2_mae: float | None, v3_mae: float | None, v3_coverage: float | None) -> str:
    if validated_count < 20:
        return "Do not tune or promote the model yet; fewer than 20 owner-approved lifecycle/cause rows are available."
    if v3_mae is None:
        return "No usable lifecycle/cause challenger rows were available; continue review intake."
    if v3_mae <= GATE_Q50_MAE_MAX and v3_coverage is not None and GATE_COVERAGE_MIN <= v3_coverage <= GATE_COVERAGE_MAX:
        return "Lifecycle/cause challenger passes the shadow metric gate; prepare a human review package before any production use."
    if v2_mae is not None and v3_mae < v2_mae:
        return "Lifecycle/cause context improves v2 but still fails the production gate; expand approved lifecycle/cause coverage and inspect residual misses."
    return "Lifecycle/cause context does not yet improve v2; prioritize better cause/work-type consistency and more approved rows before model tuning."


def _approved_context_fields(row: dict[str, str]) -> list[str]:
    return [column for column in CONTEXT_FIELDS if str(row.get(column) or "").strip()]


def _risk_flags(row: dict[str, str]) -> list[str]:
    flags = []
    for column, label in (
        ("switching_or_isolation", "switching_or_isolation"),
        ("material_or_repair_required", "material_or_repair_required"),
        ("weather_or_lightning", "weather_or_lightning"),
    ):
        if _truthy(row.get(column)):
            flags.append(label)
    cause_work = " ".join([str(row.get("outage_cause") or ""), str(row.get("work_type") or "")]).lower()
    for needle, label in (
        ("tree", "vegetation_or_tree"),
        ("vegetation", "vegetation_or_tree"),
        ("lightning", "weather_or_lightning"),
        ("storm", "weather_or_lightning"),
        ("replace", "material_or_repair_required"),
        ("repair", "material_or_repair_required"),
    ):
        if needle in cause_work and label not in flags:
            flags.append(label)
    return sorted(flags)


def _is_blocked_truth_field(column: str) -> bool:
    normalized = _safe_issue_name(column)
    return any(pattern in normalized for pattern in BLOCKED_TRUTH_FIELD_PATTERNS)


def _safe_issue_name(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")


def _clean_label(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return re.sub(r"\s+", " ", text)


def _normalize_text_key(value: Any) -> str:
    return _clean_label(value).casefold()


def _risk_key(value: Any) -> str:
    parts = [part.strip() for part in str(value or "").split(";") if part.strip()]
    return ";".join(sorted(parts))


def _truthy(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"true", "yes", "y", "1", "required", "มี", "ใช่", "yes/true"}


def _read_by_key(path: str | Path | None, key: str) -> dict[str, dict[str, str]]:
    if not path or not Path(path).exists():
        return {}
    output: dict[str, dict[str, str]] = {}
    for row in _read_csv(path):
        value = row.get(key) or ""
        if value and value not in output:
            output[value] = row
    return output


def _first_by_key(rows: list[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row.get(key) or ""
        if value and value not in output:
            output[value] = row
    return output


def _read_csv(path: str | Path) -> list[dict[str, str]]:
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


def _quantile(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


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


def _gate_status(mae: float | None, coverage: float | None) -> str:
    if mae is None or coverage is None:
        return "no_truth"
    if mae <= GATE_Q50_MAE_MAX and GATE_COVERAGE_MIN <= coverage <= GATE_COVERAGE_MAX:
        return "pass"
    return "fail"


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


def _or_zero(value: float | None) -> float:
    return value if value is not None else 0.0


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
