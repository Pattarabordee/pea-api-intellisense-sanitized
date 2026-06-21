from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
from html import escape
import json
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from .truth_quality import GATE_COVERAGE_MAX, GATE_COVERAGE_MIN, GATE_Q50_MAE_MAX


GREEN_REVIEW_COLUMNS = (
    "event_ref",
    "event_time",
    "feeder",
    "device_id",
    "actual_restoration_minutes",
    "selected_p50",
    "selected_q10",
    "selected_q90",
    "prediction_interval_width",
    "selected_absolute_error",
    "selected_covered_q10_q90",
    "webex_device_interruption_class",
    "match_level",
    "affected_count",
    "primary_issue",
    "recommended_action",
)

THRESHOLD_CALIBRATION_COLUMNS = (
    "variant",
    "max_interval_width_minutes",
    "max_q90_minutes",
    "require_sustained_webex_state",
    "green_rows",
    "mae",
    "coverage",
    "high_error_rows",
    "gate_status",
    "decision_note",
)

CONTEXT_PRIORITY_COLUMNS = (
    "priority_rank",
    "priority_tier",
    "event_ref",
    "event_time",
    "feeder",
    "device_id",
    "actual_restoration_minutes",
    "selected_absolute_error",
    "evidence_score",
    "context_sources",
    "cause_group",
    "work_type",
    "weather_or_lightning",
    "evidence_reasons",
    "recommended_review_question",
)

WEBEX_MONITOR_COLUMNS = (
    "event_ref",
    "event_time",
    "district",
    "feeder",
    "device_id",
    "match_level",
    "match_confidence",
    "affected_count",
    "webex_device_interruption_class",
    "selected_p50",
    "selected_q90",
    "prediction_interval_width",
    "monitor_priority",
    "monitor_reason",
    "recommended_action",
)
GATE_TRACKER_COLUMNS = ("metric", "value", "status", "note")
AIS_DAILY_QA_COLUMNS = ("check", "rows", "status", "note")
MAPPING_REPAIR_PUBLIC_COLUMNS = (
    "site_ref",
    "mapping_status",
    "truth_quality",
    "alarm_type",
    "rows",
    "sustained_rows",
    "review_short_rows",
    "reject_rows",
    "missing_restore_rows",
    "negative_duration_rows",
    "over_24h_rows",
    "total_sustained_minutes",
    "earliest_outage",
    "latest_outage",
    "repair_priority",
    "recommended_action",
)
MAPPING_REPAIR_PRIVATE_COLUMNS = (
    "site_ref",
    "location_id",
    "sitecode",
    *MAPPING_REPAIR_PUBLIC_COLUMNS[1:],
)
DUPLICATE_FLAPPING_COLUMNS = (
    "site_ref",
    "rows",
    "sustained_rows",
    "review_short_rows",
    "duplicate_exact_rows",
    "duplicate_groups",
    "flapping_pairs",
    "max_duration_minutes",
    "latest_outage",
    "review_priority",
    "recommended_action",
)
GREEN_GROWTH_COLUMNS = (
    "growth_lane",
    "current_rows",
    "potential_rows",
    "priority",
    "owner",
    "next_action",
    "guardrail",
)
MAPPING_REPAIR_REQUEST_COLUMNS = (
    "priority_rank",
    "site_ref",
    "mapping_status",
    "truth_quality",
    "rows",
    "sustained_rows",
    "total_sustained_minutes",
    "repair_priority",
    "requested_owner_action",
    "acceptance_criteria",
    "private_lookup_required",
)
MAPPING_REPAIR_REQUEST_PRIVATE_COLUMNS = (
    "priority_rank",
    "site_ref",
    "location_id",
    "sitecode",
    "mapping_status",
    "truth_quality",
    "rows",
    "sustained_rows",
    "total_sustained_minutes",
    "repair_priority",
    "requested_owner_action",
    "acceptance_criteria",
)
WEBEX_TRUTH_REQUEST_COLUMNS = (
    "priority_rank",
    "event_ref",
    "event_time",
    "district",
    "feeder",
    "device_id",
    "match_level",
    "affected_count",
    "webex_device_interruption_class",
    "selected_q90",
    "request_priority",
    "requested_ais_fields",
    "acceptance_criteria",
)
FLAPPING_POLICY_COLUMNS = (
    "policy_topic",
    "phase1_decision",
    "phase2_candidate",
    "owner_decision_needed",
    "guardrail",
)
OWNER_TRACKER_COLUMNS = (
    "tracker_id",
    "workstream",
    "source_ref",
    "priority",
    "owner",
    "current_status",
    "requested_action",
    "acceptance_criteria",
    "source_file",
    "next_step",
)
OWNER_RESPONSE_TEMPLATE_COLUMNS = (
    "response_type",
    "source_ref",
    "owner_decision",
    "mapped_site_id",
    "mapped_site_code",
    "outage_start_time",
    "power_restore_time",
    "device_id",
    "feeder",
    "owner_notes",
    "reviewed_by",
    "reviewed_at",
)
OWNER_RESPONSE_VALIDATION_COLUMNS = (
    "response_type",
    "source_ref",
    "validation_status",
    "issue",
    "recommended_action",
)
FLAPPING_SENSITIVITY_COLUMNS = (
    "scenario",
    "merge_window_minutes",
    "input_scope",
    "metric_to_compare",
    "pass_condition",
    "owner_decision_needed",
)
OWNER_RESPONSE_INTAKE_COLUMNS = (
    "response_type",
    "source_ref",
    "validation_status",
    "intake_lane",
    "import_ready",
    "model_gate_eligible",
    "staging_target",
    "issue",
    "recommended_action",
)
OWNER_DRY_RUN_IMPACT_COLUMNS = (
    "scenario",
    "current_green_rows",
    "ready_mapping_rows",
    "ready_truth_rows",
    "optimistic_green_rows",
    "additional_green_rows_needed",
    "gate_status",
    "decision_note",
)
OWNER_RESPONSE_EXAMPLE_COLUMNS = (
    "example_name",
    "response_file",
    "expected_validation_status",
    "reason",
    "owner_action",
)
DAILY_EXECUTIVE_DELTA_COLUMNS = (
    "metric",
    "current_value",
    "previous_value",
    "delta",
    "status",
    "recommended_action",
)
CURRENT_CAPABILITY_PLAN_COLUMNS = (
    "section",
    "item",
    "status",
    "evidence",
    "recommended_action",
)


def build_green_candidate_error_review(
    eligibility_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    high_error_minutes: float = 60.0,
) -> dict[str, Any]:
    rows = [_green_review_row(row, high_error_minutes) for row in _read_csv(eligibility_csv) if row.get("eligibility_status") == "green_auto_candidate"]
    rows.sort(key=lambda row: _to_float(row.get("selected_absolute_error")) or -1, reverse=True)
    _write_csv(output_csv, GREEN_REVIEW_COLUMNS, rows)
    summary = _metric_summary(rows, "selected_absolute_error", "selected_covered_q10_q90", high_error_minutes)
    summary.update(
        {
            "output_csv": str(output_csv),
            "markdown_output": str(markdown_output) if markdown_output else None,
            "issue_counts": dict(Counter(row.get("primary_issue") or "<blank>" for row in rows).most_common()),
            "feeder_counts": dict(Counter(row.get("feeder") or "<blank>" for row in rows).most_common()),
        }
    )
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_green_review(summary, rows), encoding="utf-8-sig")
    return summary


def build_eligibility_threshold_calibration(
    eligibility_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    high_error_minutes: float = 60.0,
    min_rows_for_decision: int = 5,
) -> dict[str, Any]:
    rows = _read_csv(eligibility_csv)
    variants = [
        ("current_policy", None, None, False),
        ("width_le_120_q90_le_180", 120.0, 180.0, False),
        ("width_le_100_q90_le_180", 100.0, 180.0, False),
        ("width_le_90_q90_le_180", 90.0, 180.0, False),
        ("width_le_90_q90_le_160", 90.0, 160.0, False),
        ("sustained_webex_width_le_120", 120.0, 180.0, True),
        ("sustained_webex_width_le_90", 90.0, 180.0, True),
    ]
    output_rows = []
    for name, width, q90, require_sustained in variants:
        selected = _current_green(rows) if name == "current_policy" else [
            row
            for row in rows
            if _passes_candidate_policy(row, width, q90, require_sustained)
        ]
        metrics = _metric_summary(selected, "selected_absolute_error", "selected_covered_q10_q90", high_error_minutes)
        gate = _gate_status(metrics["rows"], metrics["mae"], metrics["coverage"], min_rows_for_decision)
        output_rows.append(
            {
                "variant": name,
                "max_interval_width_minutes": "" if width is None else _fmt(width),
                "max_q90_minutes": "" if q90 is None else _fmt(q90),
                "require_sustained_webex_state": _bool_str(require_sustained),
                "green_rows": str(metrics["rows"]),
                "mae": _fmt(metrics["mae"]),
                "coverage": _fmt(metrics["coverage"], digits=3),
                "high_error_rows": str(metrics["high_error_rows"]),
                "gate_status": gate,
                "decision_note": _threshold_decision_note(gate, metrics["rows"]),
            }
        )
    _write_csv(output_csv, THRESHOLD_CALIBRATION_COLUMNS, output_rows)
    best = _best_threshold_variant(output_rows)
    summary = {
        "variants": len(output_rows),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "best_variant": best.get("variant", ""),
        "best_gate_status": best.get("gate_status", ""),
        "min_rows_for_decision": min_rows_for_decision,
    }
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_threshold_calibration(summary, output_rows), encoding="utf-8-sig")
    return summary


def build_context_review_priority_pack(
    evidence_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    top_n: int = 50,
) -> dict[str, Any]:
    rows = [_context_priority_row(row) for row in _read_csv(evidence_csv) if row.get("evidence_status") == "approved_candidate"]
    rows.sort(
        key=lambda row: (
            _priority_sort(row.get("priority_tier")),
            _to_float(row.get("evidence_score")) or 0,
            _to_float(row.get("selected_absolute_error")) or 0,
            _to_float(row.get("actual_restoration_minutes")) or 0,
        ),
        reverse=True,
    )
    selected = rows[: max(top_n, 0)]
    for index, row in enumerate(selected, start=1):
        row["priority_rank"] = str(index)
    _write_csv(output_csv, CONTEXT_PRIORITY_COLUMNS, selected)
    summary = {
        "rows": len(rows),
        "selected_rows": len(selected),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "tier_counts": dict(Counter(row.get("priority_tier") for row in selected).most_common()),
        "feeder_counts": dict(Counter(row.get("feeder") or "<blank>" for row in selected).most_common()),
        "cause_counts": dict(Counter(row.get("cause_group") or "<blank>" for row in selected).most_common()),
    }
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_context_priority(summary, selected), encoding="utf-8-sig")
    return summary


def build_webex_only_monitoring_report(
    eligibility_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    top_n: int = 100,
) -> dict[str, Any]:
    rows = [
        _webex_monitor_row(row)
        for row in _read_csv(eligibility_csv)
        if row.get("source_lane") == "webex_trigger_no_ais_truth"
    ]
    rows.sort(
        key=lambda row: (
            _priority_sort(row.get("monitor_priority")),
            _to_float(row.get("selected_q90")) or 0,
            row.get("event_time") or "",
        ),
        reverse=True,
    )
    selected = rows[: max(top_n, 0)]
    _write_csv(output_csv, WEBEX_MONITOR_COLUMNS, selected)
    summary = {
        "rows": len(rows),
        "selected_rows": len(selected),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "priority_counts": dict(Counter(row.get("monitor_priority") or "<blank>" for row in rows).most_common()),
        "feeder_counts": dict(Counter(row.get("feeder") or "<blank>" for row in rows).most_common(12)),
        "device_class_counts": dict(Counter(row.get("webex_device_interruption_class") or "<blank>" for row in rows).most_common()),
        "match_level_counts": dict(Counter(row.get("match_level") or "<blank>" for row in rows).most_common()),
    }
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_webex_monitor(summary, selected), encoding="utf-8-sig")
    return summary


def build_operator_console_mock(
    eligibility_csv: str | Path,
    evidence_csv: str | Path,
    output_html: str | Path,
    markdown_output: str | Path | None = None,
    *,
    max_rows: int = 12,
) -> dict[str, Any]:
    eligibility = _read_csv(eligibility_csv)
    evidence = _read_csv(evidence_csv)
    status_counts = Counter(row.get("eligibility_status") or "<blank>" for row in eligibility)
    source_counts = Counter(row.get("source_lane") or "<blank>" for row in eligibility)
    evidence_counts = Counter(row.get("evidence_status") or "<blank>" for row in evidence)
    green = [row for row in eligibility if row.get("eligibility_status") == "green_auto_candidate"]
    amber = _top_rows([row for row in eligibility if row.get("eligibility_status") == "amber_human_review"], max_rows)
    monitor = _top_rows([row for row in eligibility if row.get("eligibility_status") == "monitor_only"], max_rows)
    conflicts = _top_rows([row for row in evidence if row.get("evidence_status") in {"pending_conflict", "rejected_conflict"}], max_rows)
    approved = _top_rows([row for row in evidence if row.get("evidence_status") == "approved_candidate"], max_rows)
    green_metrics = _metric_summary(green, "selected_absolute_error", "selected_covered_q10_q90", 60.0)
    summary = {
        "rows": len(eligibility),
        "green": status_counts.get("green_auto_candidate", 0),
        "amber": status_counts.get("amber_human_review", 0),
        "red": status_counts.get("red_blocked", 0),
        "monitor": status_counts.get("monitor_only", 0),
        "ais_truth_matched": source_counts.get("ais_truth_matched", 0),
        "pea_quarantined": source_counts.get("pea_quarantined", 0),
        "webex_only": source_counts.get("webex_trigger_no_ais_truth", 0),
        "approved_context": evidence_counts.get("approved_candidate", 0),
        "context_conflicts": evidence_counts.get("pending_conflict", 0) + evidence_counts.get("rejected_conflict", 0),
        "green_mae": green_metrics["mae"],
        "green_coverage": green_metrics["coverage"],
        "gate_status": _gate_status(green_metrics["rows"], green_metrics["mae"], green_metrics["coverage"], 1),
    }
    Path(output_html).parent.mkdir(parents=True, exist_ok=True)
    Path(output_html).write_text(_render_console_html(summary, green, amber, monitor, conflicts, approved, max_rows), encoding="utf-8-sig")
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_console_markdown(summary, output_html), encoding="utf-8-sig")
    return {
        **summary,
        "output_html": str(output_html),
        "markdown_output": str(markdown_output) if markdown_output else None,
    }


def build_green_gate_tracker(
    eligibility_csv: str | Path,
    threshold_calibration_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    min_green_rows: int = 30,
) -> dict[str, Any]:
    eligibility_rows = _read_csv(eligibility_csv)
    calibration_rows = _read_csv(threshold_calibration_csv)
    green_rows = [row for row in eligibility_rows if row.get("eligibility_status") == "green_auto_candidate"]
    ais_metric_rows = [
        row
        for row in eligibility_rows
        if row.get("source_lane") == "ais_truth_matched"
        and row.get("actual_restoration_minutes")
    ]
    green_metrics = _metric_summary(green_rows, "selected_absolute_error", "selected_covered_q10_q90", 60.0)
    best_variant = _best_threshold_variant(calibration_rows)
    additional_green_needed = max(min_green_rows - green_metrics["rows"], 0)
    gate_status = _gate_status(green_metrics["rows"], green_metrics["mae"], green_metrics["coverage"], min_green_rows)
    output_rows = [
        _gate_row("ais_truth_metric_rows", len(ais_metric_rows), "info", "AIS outage/restore rows available for backtest."),
        _gate_row("green_rows", green_metrics["rows"], "blocked" if additional_green_needed else "ready", "Rows currently eligible for automatic ETR backtest."),
        _gate_row("additional_green_rows_needed", additional_green_needed, "blocked" if additional_green_needed else "ready", f"Target minimum is {min_green_rows} green rows."),
        _gate_row("green_q50_mae_minutes", _fmt(green_metrics["mae"]), "pass" if green_metrics["mae"] is not None and green_metrics["mae"] <= GATE_Q50_MAE_MAX else "blocked", f"Target <= {GATE_Q50_MAE_MAX:g} minutes."),
        _gate_row("green_q10_q90_coverage", _fmt(green_metrics["coverage"], digits=3), "pass" if green_metrics["coverage"] is not None and GATE_COVERAGE_MIN <= green_metrics["coverage"] <= GATE_COVERAGE_MAX else "blocked", f"Target {GATE_COVERAGE_MIN:g}-{GATE_COVERAGE_MAX:g}."),
        _gate_row("green_high_error_rows", green_metrics["high_error_rows"], "blocked" if green_metrics["high_error_rows"] else "pass", "High error threshold is >=60 minutes."),
        _gate_row("production_gate_status", gate_status, "blocked" if gate_status.startswith("blocked") else "review", "Human approval is still required even if metric gate passes."),
        _gate_row("best_shadow_policy_variant", best_variant.get("variant", ""), best_variant.get("gate_status", "unknown"), "Best threshold-calibration variant from the latest report."),
    ]
    _write_csv(output_csv, GATE_TRACKER_COLUMNS, output_rows)
    summary = {
        "green_rows": green_metrics["rows"],
        "ais_truth_metric_rows": len(ais_metric_rows),
        "additional_green_rows_needed": additional_green_needed,
        "min_green_rows": min_green_rows,
        "green_q50_mae_minutes": _fmt(green_metrics["mae"]),
        "green_q10_q90_coverage": _fmt(green_metrics["coverage"], digits=3),
        "gate_status": gate_status,
        "best_variant": best_variant.get("variant", ""),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
    }
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_green_gate_tracker(summary, output_rows), encoding="utf-8-sig")
    return summary


def build_ais_daily_file_qa(
    candidate_csv: str | Path,
    review_csv: str | Path,
    rejects_csv: str | Path,
    join_audit_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
) -> dict[str, Any]:
    candidates = _read_csv(candidate_csv)
    review = _read_csv(review_csv)
    rejects = _read_csv(rejects_csv)
    audit = _read_csv(join_audit_csv)
    usable = [
        row
        for row in candidates
        if row.get("truth_quality") == "OK"
        and row.get("peano")
        and (_to_float(row.get("actual_restoration_minutes")) or 0) > 5
        and (_to_float(row.get("actual_restoration_minutes")) or 0) <= 1440
    ]
    missing_restore = [row for row in candidates + review + rejects if not row.get("power_restore_time")]
    negative = [row for row in candidates + review + rejects if (_to_float(row.get("actual_restoration_minutes")) or 0) < 0]
    over_24h = [row for row in candidates + review + rejects if (_to_float(row.get("actual_restoration_minutes")) or 0) > 1440]
    missing_peano = [row for row in candidates + rejects if not row.get("peano") or "MISSING_PEANO" in row.get("truth_quality", "")]
    duplicate_intervals = _duplicate_interval_rows(candidates + review)
    mapping_counts = Counter(row.get("mapping_status") or "<blank>" for row in audit)
    output_rows = [
        _qa_row("candidate_rows", len(candidates), "info", "Rows in the latest sustained candidate output."),
        _qa_row("usable_sustained_ok_rows", len(usable), "pass" if usable else "blocked", "Rows eligible for AIS-only evaluation."),
        _qa_row("review_le_5min_rows", len(review), "review" if review else "pass", "<=5 minute rows stay review-only."),
        _qa_row("reject_rows", len(rejects), "review" if rejects else "pass", "Rejected rows are not used for accuracy claims."),
        _qa_row("missing_meter_mapping_rows", len(missing_peano), "review" if missing_peano else "pass", "Needs AIS mapping repair before confident matching."),
        _qa_row("missing_restore_rows", len(missing_restore), "blocked" if missing_restore else "pass", "Restore time is required for truth."),
        _qa_row("negative_duration_rows", len(negative), "blocked" if negative else "pass", "Negative duration cannot be truth."),
        _qa_row("over_24h_rows", len(over_24h), "review" if over_24h else "pass", ">24h rows need owner review before evaluation."),
        _qa_row("duplicate_interval_rows", duplicate_intervals, "review" if duplicate_intervals else "pass", "Possible duplicate/flapping intervals; Phase 1 does not merge them."),
    ]
    for status, count in mapping_counts.most_common(8):
        safe_status = str(status).replace("peano", "meter").replace("PEANO", "meter")
        output_rows.append(_qa_row(f"mapping_status_{safe_status}", count, "info", "Join-audit mapping status count."))
    _write_csv(output_csv, AIS_DAILY_QA_COLUMNS, output_rows)
    summary = {
        "candidate_rows": len(candidates),
        "usable_sustained_ok_rows": len(usable),
        "review_le_5min_rows": len(review),
        "reject_rows": len(rejects),
        "missing_peano_rows": len(missing_peano),
        "missing_restore_rows": len(missing_restore),
        "negative_duration_rows": len(negative),
        "over_24h_rows": len(over_24h),
        "duplicate_interval_rows": duplicate_intervals,
        "mapping_status_counts": dict(mapping_counts.most_common(8)),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
    }
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_ais_daily_qa(summary, output_rows), encoding="utf-8-sig")
    return summary


def build_status_only_payload_templates(
    eligibility_csv: str | Path,
    output_jsonl: str | Path,
    markdown_output: str | Path | None = None,
    *,
    max_rows: int = 50,
) -> dict[str, Any]:
    candidates = [
        row
        for row in _read_csv(eligibility_csv)
        if row.get("eligibility_status") in {"amber_human_review", "monitor_only"}
    ]
    amber = [row for row in candidates if row.get("eligibility_status") == "amber_human_review"]
    monitor = [row for row in candidates if row.get("eligibility_status") == "monitor_only"]
    for group in (amber, monitor):
        group.sort(
            key=lambda row: (
                _to_float(row.get("selected_q90")) or 0,
                row.get("event_time") or "",
            ),
            reverse=True,
        )
    selected = amber[: max(max_rows, 0)] + monitor[: max(max_rows, 0)]
    selected.sort(
        key=lambda row: (
            row.get("eligibility_status") == "amber_human_review",
            _to_float(row.get("selected_q90")) or 0,
            row.get("event_time") or "",
        ),
        reverse=True,
    )
    payloads = [_status_payload(row) for row in selected]
    output_path = Path(output_jsonl)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    counts = Counter(payload["status"] for payload in payloads)
    summary = {
        "candidate_rows": len(candidates),
        "payload_rows": len(payloads),
        "status_counts": dict(counts.most_common()),
        "output_jsonl": str(output_jsonl),
        "markdown_output": str(markdown_output) if markdown_output else None,
    }
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_status_payloads(summary, payloads), encoding="utf-8-sig")
    return summary


def build_operator_console_qa(
    html_path: str | Path,
    output_markdown: str | Path,
) -> dict[str, Any]:
    source = Path(html_path)
    text = source.read_text(encoding="utf-8-sig") if source.exists() else ""
    checks = {
        "html_exists": source.exists(),
        "has_no_production_send_banner": "No production send" in text,
        "has_production_gate": "Production Gate" in text,
        "has_responsive_viewport": "viewport" in text,
        "has_green_amber_red_monitor": all(term in text for term in ("Green", "Amber", "Red", "Monitor")),
        "no_sensitive_terms": not any(term.lower() in text.lower() for term in ("token", "secret", "room_id", "refresh_token", "access_token", "PEANO")),
        "has_table_sections": all(term in text for term in ("Green Backtest", "Amber Review Queue", "WebEx Monitor Queue", "Context Conflicts")),
    }
    passed = all(checks.values())
    summary = {
        "html_path": str(html_path),
        "output_markdown": str(output_markdown),
        "passed": passed,
        "checks": checks,
        "html_size_bytes": source.stat().st_size if source.exists() else 0,
    }
    Path(output_markdown).parent.mkdir(parents=True, exist_ok=True)
    Path(output_markdown).write_text(_render_console_qa(summary), encoding="utf-8-sig")
    return summary


def build_mapping_repair_queue(
    join_audit_csv: str | Path,
    candidate_csv: str | Path,
    rejects_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    private_output_csv: str | Path | None = "runtime/private/ais_mapping_repair_queue_private.csv",
    top_n: int = 100,
) -> dict[str, Any]:
    audit_rows = _read_csv(join_audit_csv)
    source_rows = audit_rows or _rows_for_mapping_fallback(_read_csv(candidate_csv), _read_csv(rejects_csv))
    groups: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for row in source_rows:
        location_id = _cell(row.get("location_id") or row.get("site_id"))
        sitecode = _cell(row.get("sitecode") or row.get("site_code"))
        mapping_status = _cell(row.get("mapping_status") or _note_value(row, "mapping_status") or "unknown")
        truth_quality = _cell(row.get("truth_quality") or "unknown")
        alarm_type = _cell(row.get("alarm_type") or _note_value(row, "alarm_type") or "unknown")
        if mapping_status == "matched_single_peano" and truth_quality == "OK":
            continue
        key = (location_id, sitecode, mapping_status, truth_quality, alarm_type)
        bucket = groups.setdefault(
            key,
            {
                "location_id": location_id,
                "sitecode": sitecode,
                "site_ref": _site_ref(location_id, sitecode),
                "mapping_status": mapping_status,
                "truth_quality": truth_quality,
                "alarm_type": alarm_type,
                "rows": 0,
                "sustained_rows": 0,
                "review_short_rows": 0,
                "reject_rows": 0,
                "missing_restore_rows": 0,
                "negative_duration_rows": 0,
                "over_24h_rows": 0,
                "total_sustained_minutes": 0.0,
                "earliest_outage": "",
                "latest_outage": "",
            },
        )
        duration = _to_float(row.get("actual_restoration_minutes"))
        bucket["rows"] += 1
        if duration is not None and 0 < duration <= 5:
            bucket["review_short_rows"] += 1
        if duration is not None and 5 < duration <= 1440 and truth_quality != "OK":
            bucket["sustained_rows"] += 1
            bucket["total_sustained_minutes"] += duration
        if truth_quality != "OK":
            bucket["reject_rows"] += 1
        if not row.get("power_restore_time"):
            bucket["missing_restore_rows"] += 1
        if duration is not None and duration < 0:
            bucket["negative_duration_rows"] += 1
        if duration is not None and duration > 1440:
            bucket["over_24h_rows"] += 1
        _update_time_window(bucket, row.get("outage_start_time"))

    output_rows = [_mapping_repair_row(bucket) for bucket in groups.values()]
    output_rows.sort(
        key=lambda row: (
            _repair_priority_rank(row.get("repair_priority")),
            _to_float(row.get("sustained_rows")) or 0,
            _to_float(row.get("total_sustained_minutes")) or 0,
            _to_float(row.get("rows")) or 0,
        ),
        reverse=True,
    )
    selected = output_rows[: max(top_n, 0)]
    public_rows = [_public_mapping_repair_row(row) for row in selected]
    _write_csv(output_csv, MAPPING_REPAIR_PUBLIC_COLUMNS, public_rows)
    if private_output_csv:
        _write_csv(private_output_csv, MAPPING_REPAIR_PRIVATE_COLUMNS, selected)
    priority_counts = Counter(row.get("repair_priority") or "<blank>" for row in output_rows)
    status_counts = Counter(_public_mapping_status(row.get("mapping_status")) or "<blank>" for row in output_rows)
    summary = {
        "input_rows": len(source_rows),
        "repair_groups": len(output_rows),
        "selected_rows": len(selected),
        "public_output_csv": str(output_csv),
        "private_output_csv": str(private_output_csv) if private_output_csv else None,
        "markdown_output": str(markdown_output) if markdown_output else None,
        "priority_counts": dict(priority_counts.most_common()),
        "mapping_status_counts": dict(status_counts.most_common(10)),
    }
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_mapping_repair_queue(summary, public_rows), encoding="utf-8-sig")
    return summary


def build_duplicate_flapping_audit(
    candidate_csv: str | Path,
    review_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    flap_window_minutes: float = 5.0,
    top_n: int = 100,
) -> dict[str, Any]:
    rows = _read_csv(candidate_csv) + _read_csv(review_csv)
    intervals: dict[str, list[dict[str, Any]]] = {}
    exact_keys: Counter[tuple[str, str, str, str]] = Counter()
    for row in rows:
        site_id = _cell(row.get("site_id") or row.get("location_id"))
        if not site_id:
            continue
        start = _parse_datetime(row.get("outage_start_time"))
        restore = _parse_datetime(row.get("power_restore_time"))
        duration = _to_float(row.get("actual_restoration_minutes"))
        site_ref = _site_ref(site_id, "")
        intervals.setdefault(site_ref, []).append(
            {
                "start": start,
                "restore": restore,
                "duration": duration,
                "is_review_short": duration is not None and 0 < duration <= 5,
                "is_sustained": duration is not None and 5 < duration <= 1440,
                "raw_start": row.get("outage_start_time") or "",
            }
        )
        exact_keys[(site_ref, row.get("outage_start_time") or "", row.get("power_restore_time") or "", row.get("actual_restoration_minutes") or "")] += 1

    duplicates_by_site: Counter[str] = Counter()
    duplicate_groups_by_site: Counter[str] = Counter()
    for key, count in exact_keys.items():
        site_ref = key[0]
        if count > 1 and all(key[1:]):
            duplicates_by_site[site_ref] += count
            duplicate_groups_by_site[site_ref] += 1

    output_rows = []
    for site_ref, site_intervals in intervals.items():
        site_intervals.sort(key=lambda row: row["start"] or datetime.min)
        flapping_pairs = 0
        for previous, current in zip(site_intervals, site_intervals[1:]):
            if previous["restore"] is None or current["start"] is None:
                continue
            delta_minutes = (current["start"] - previous["restore"]).total_seconds() / 60.0
            if 0 <= delta_minutes <= flap_window_minutes:
                flapping_pairs += 1
        duplicate_rows = duplicates_by_site.get(site_ref, 0)
        duplicate_groups = duplicate_groups_by_site.get(site_ref, 0)
        if duplicate_rows == 0 and flapping_pairs == 0:
            continue
        sustained_rows = sum(1 for row in site_intervals if row["is_sustained"])
        review_short_rows = sum(1 for row in site_intervals if row["is_review_short"])
        max_duration = max((row["duration"] or 0 for row in site_intervals), default=0)
        latest = max((row["raw_start"] for row in site_intervals if row["raw_start"]), default="")
        priority = "high" if flapping_pairs >= 3 or duplicate_rows >= 5 else "medium"
        output_rows.append(
            {
                "site_ref": site_ref,
                "rows": str(len(site_intervals)),
                "sustained_rows": str(sustained_rows),
                "review_short_rows": str(review_short_rows),
                "duplicate_exact_rows": str(duplicate_rows),
                "duplicate_groups": str(duplicate_groups),
                "flapping_pairs": str(flapping_pairs),
                "max_duration_minutes": _fmt(max_duration),
                "latest_outage": latest,
                "review_priority": priority,
                "recommended_action": _duplicate_flapping_action(duplicate_rows, flapping_pairs),
            }
        )
    output_rows.sort(
        key=lambda row: (
            _priority_sort(row.get("review_priority")),
            _to_float(row.get("flapping_pairs")) or 0,
            _to_float(row.get("duplicate_exact_rows")) or 0,
            _to_float(row.get("max_duration_minutes")) or 0,
        ),
        reverse=True,
    )
    selected = output_rows[: max(top_n, 0)]
    _write_csv(output_csv, DUPLICATE_FLAPPING_COLUMNS, selected)
    summary = {
        "input_rows": len(rows),
        "sites_with_findings": len(output_rows),
        "selected_rows": len(selected),
        "flap_window_minutes": flap_window_minutes,
        "duplicate_exact_rows": sum(_to_int(row.get("duplicate_exact_rows")) for row in output_rows),
        "flapping_pairs": sum(_to_int(row.get("flapping_pairs")) for row in output_rows),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
    }
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_duplicate_flapping_audit(summary, selected), encoding="utf-8-sig")
    return summary


def build_green_candidate_growth_plan(
    eligibility_csv: str | Path,
    green_gate_tracker_csv: str | Path,
    webex_monitor_csv: str | Path,
    mapping_repair_csv: str | Path,
    context_priority_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    min_green_rows: int = 30,
) -> dict[str, Any]:
    eligibility = _read_csv(eligibility_csv)
    gate_rows = _read_csv(green_gate_tracker_csv)
    monitor_rows = _read_csv(webex_monitor_csv)
    mapping_rows = _read_csv(mapping_repair_csv)
    context_rows = _read_csv(context_priority_csv)
    green_rows = [row for row in eligibility if row.get("eligibility_status") == "green_auto_candidate"]
    amber_rows = [row for row in eligibility if row.get("eligibility_status") == "amber_human_review"]
    high_webex = [row for row in monitor_rows if row.get("monitor_priority") == "high"]
    high_mapping = [row for row in mapping_rows if row.get("repair_priority") in {"critical", "high"}]
    amber_momentary = [
        row
        for row in amber_rows
        if "momentary" in (row.get("blocker_reasons") or row.get("webex_device_interruption_class") or "")
    ]
    narrower_amber = [
        row
        for row in amber_rows
        if (_to_float(row.get("prediction_interval_width")) or 9999) <= 120
        and (_to_float(row.get("selected_q90")) or 9999) <= 180
    ]
    context_high = [row for row in context_rows if row.get("priority_tier") == "high"]
    additional_needed = max(min_green_rows - len(green_rows), 0)
    rows = [
        _growth_row(
            "current_green_baseline",
            len(green_rows),
            additional_needed,
            "blocked" if additional_needed else "ready",
            "ETR model owner",
            "Keep collecting fresh AIS truth until the green subset has enough rows for a stable gate.",
            "No production send until metric gate and human approval pass.",
        ),
        _growth_row(
            "collect_ais_truth_for_high_priority_webex",
            len(high_webex),
            min(len(high_webex), additional_needed or len(high_webex)),
            "high",
            "AIS daily truth owner",
            "Prioritize daily AIS outage/restore files for WebEx rows with protection match and affected AIS count.",
            "Use for evaluation only after AIS restore timestamp arrives.",
        ),
        _growth_row(
            "repair_missing_or_ambiguous_site_mapping",
            len(high_mapping),
            sum(_to_int(row.get("sustained_rows")) for row in high_mapping),
            "high" if high_mapping else "medium",
            "AIS mapping owner",
            "Use the private repair queue to map missing/ambiguous sites, then rerun daily refresh.",
            "Do not infer affected customer impact without mapping evidence.",
        ),
        _growth_row(
            "review_momentary_webex_but_ais_sustained",
            len(amber_momentary),
            len(amber_momentary),
            "medium",
            "Operations reviewer",
            "Confirm whether these are true sustained customer outages or transient device operations.",
            "Keep status-only until reviewed; do not auto-send narrow p50.",
        ),
        _growth_row(
            "tighten_uncertainty_for_near_green_amber",
            len(narrower_amber),
            len(narrower_amber),
            "medium",
            "Model owner",
            "Inspect why these rows miss green blockers despite narrower uncertainty.",
            "Only promote if AIS truth backtest passes q50 MAE and coverage.",
        ),
        _growth_row(
            "approve_context_features_for_long_outage_review",
            len(context_high),
            len(context_high),
            "medium",
            "PEA/operations source owner",
            "Approve cause/work-type context for long-outage diagnostics, not restoration truth.",
            "PEA context remains feature-only and must not become the label.",
        ),
    ]
    _write_csv(output_csv, GREEN_GROWTH_COLUMNS, rows)
    gate_lookup = {row.get("metric", ""): row.get("value", "") for row in gate_rows}
    summary = {
        "green_rows": len(green_rows),
        "min_green_rows": min_green_rows,
        "additional_green_needed": additional_needed,
        "high_priority_webex_rows": len(high_webex),
        "high_mapping_repair_rows": len(high_mapping),
        "amber_momentary_rows": len(amber_momentary),
        "near_green_amber_rows": len(narrower_amber),
        "high_context_rows": len(context_high),
        "gate_status": gate_lookup.get("production_gate_status", ""),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
    }
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_green_growth_plan(summary, rows), encoding="utf-8-sig")
    return summary


def build_shadow_status_payload_contract(
    status_payload_jsonl: str | Path,
    eligibility_csv: str | Path,
    output_markdown: str | Path,
    *,
    sample_count: int = 2,
) -> dict[str, Any]:
    payloads = _read_jsonl(status_payload_jsonl)
    eligibility = _read_csv(eligibility_csv)
    status_counts = Counter(row.get("eligibility_status") or "<blank>" for row in eligibility)
    samples = [_contract_payload_sample(payload) for payload in payloads[: max(sample_count, 0)]]
    summary = {
        "payload_rows": len(payloads),
        "sample_rows": len(samples),
        "eligibility_counts": dict(status_counts.most_common()),
        "output_markdown": str(output_markdown),
    }
    Path(output_markdown).parent.mkdir(parents=True, exist_ok=True)
    Path(output_markdown).write_text(_render_shadow_status_contract(summary, samples), encoding="utf-8-sig")
    return summary


def build_executive_one_pager(
    eligibility_csv: str | Path,
    green_gate_tracker_csv: str | Path,
    ais_daily_qa_csv: str | Path,
    growth_plan_csv: str | Path,
    output_markdown: str | Path,
) -> dict[str, Any]:
    eligibility = _read_csv(eligibility_csv)
    gate_rows = _read_csv(green_gate_tracker_csv)
    qa_rows = _read_csv(ais_daily_qa_csv)
    growth_rows = _read_csv(growth_plan_csv)
    status_counts = Counter(row.get("eligibility_status") or "<blank>" for row in eligibility)
    source_counts = Counter(row.get("source_lane") or "<blank>" for row in eligibility)
    gate = {row.get("metric", ""): row.get("value", "") for row in gate_rows}
    qa = {row.get("check", ""): row.get("rows", "") for row in qa_rows}
    summary = {
        "total_rows": len(eligibility),
        "green": status_counts.get("green_auto_candidate", 0),
        "amber": status_counts.get("amber_human_review", 0),
        "red": status_counts.get("red_blocked", 0),
        "monitor": status_counts.get("monitor_only", 0),
        "ais_truth_matched": source_counts.get("ais_truth_matched", 0),
        "webex_only": source_counts.get("webex_trigger_no_ais_truth", 0),
        "pea_quarantined": source_counts.get("pea_quarantined", 0),
        "gate_status": gate.get("production_gate_status", "blocked"),
        "green_mae": gate.get("green_q50_mae_minutes", ""),
        "green_coverage": gate.get("green_q10_q90_coverage", ""),
        "additional_green_needed": gate.get("additional_green_rows_needed", ""),
        "usable_sustained_ok_rows": qa.get("usable_sustained_ok_rows", ""),
        "missing_mapping_rows": qa.get("missing_meter_mapping_rows", ""),
        "duplicate_interval_rows": qa.get("duplicate_interval_rows", ""),
        "growth_rows": growth_rows,
        "output_markdown": str(output_markdown),
    }
    Path(output_markdown).parent.mkdir(parents=True, exist_ok=True)
    Path(output_markdown).write_text(_render_executive_one_pager(summary), encoding="utf-8-sig")
    return summary


def build_mapping_repair_request_pack(
    public_queue_csv: str | Path,
    private_queue_csv: str | Path,
    output_csv: str | Path,
    private_output_csv: str | Path,
    markdown_output: str | Path,
    *,
    top_n: int = 25,
) -> dict[str, Any]:
    public_rows = _read_csv(public_queue_csv)
    private_rows = _read_csv(private_queue_csv)
    private_by_ref = {row.get("site_ref", ""): row for row in private_rows if row.get("site_ref")}
    candidates = [
        row
        for row in public_rows
        if row.get("repair_priority") in {"critical", "high", "medium"}
        and str(row.get("mapping_status") or "").lower() not in {"matched_single_meter", "matched_single_peano"}
    ]
    candidates.sort(
        key=lambda row: (
            _repair_priority_rank(row.get("repair_priority")),
            _to_float(row.get("sustained_rows")) or 0,
            _to_float(row.get("total_sustained_minutes")) or 0,
            _to_float(row.get("rows")) or 0,
        ),
        reverse=True,
    )
    selected = candidates[: max(top_n, 0)]
    public_output = []
    private_output = []
    for rank, row in enumerate(selected, start=1):
        request_row = _mapping_request_row(rank, row)
        public_output.append(request_row)
        private = private_by_ref.get(row.get("site_ref", ""), {})
        private_output.append(
            {
                **request_row,
                "location_id": private.get("location_id", ""),
                "sitecode": private.get("sitecode", ""),
            }
        )
    _write_csv(output_csv, MAPPING_REPAIR_REQUEST_COLUMNS, public_output)
    _write_csv(private_output_csv, MAPPING_REPAIR_REQUEST_PRIVATE_COLUMNS, private_output)
    summary = {
        "candidate_rows": len(candidates),
        "selected_rows": len(selected),
        "critical_rows": sum(1 for row in candidates if row.get("repair_priority") == "critical"),
        "high_rows": sum(1 for row in candidates if row.get("repair_priority") == "high"),
        "potential_sustained_rows": sum(_to_int(row.get("sustained_rows")) for row in selected),
        "public_output_csv": str(output_csv),
        "private_output_csv": str(private_output_csv),
        "markdown_output": str(markdown_output),
    }
    Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
    Path(markdown_output).write_text(_render_mapping_repair_request_pack(summary, public_output), encoding="utf-8-sig")
    return summary


def build_webex_truth_request_pack(
    webex_monitor_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path,
    *,
    top_n: int = 100,
) -> dict[str, Any]:
    rows = [row for row in _read_csv(webex_monitor_csv) if row.get("monitor_priority") in {"high", "medium"}]
    rows.sort(
        key=lambda row: (
            _priority_sort(row.get("monitor_priority")),
            _to_float(row.get("affected_count")) or 0,
            _to_float(row.get("selected_q90")) or 0,
            row.get("event_time") or "",
        ),
        reverse=True,
    )
    selected = rows[: max(top_n, 0)]
    output_rows = [_webex_truth_request_row(index, row) for index, row in enumerate(selected, start=1)]
    _write_csv(output_csv, WEBEX_TRUTH_REQUEST_COLUMNS, output_rows)
    summary = {
        "candidate_rows": len(rows),
        "selected_rows": len(output_rows),
        "high_rows": sum(1 for row in rows if row.get("monitor_priority") == "high"),
        "affected_total": sum(_to_int(row.get("affected_count")) for row in selected),
        "feeder_counts": dict(Counter(row.get("feeder") or "<blank>" for row in selected).most_common(10)),
        "device_state_counts": dict(Counter(row.get("webex_device_interruption_class") or "<blank>" for row in selected).most_common()),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output),
    }
    Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
    Path(markdown_output).write_text(_render_webex_truth_request_pack(summary, output_rows), encoding="utf-8-sig")
    return summary


def build_flapping_policy_draft(
    duplicate_flapping_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path,
    *,
    phase2_windows: Iterable[int] = (5, 15, 30),
) -> dict[str, Any]:
    rows = _read_csv(duplicate_flapping_csv)
    high_rows = [row for row in rows if row.get("review_priority") == "high"]
    total_duplicate_rows = sum(_to_int(row.get("duplicate_exact_rows")) for row in rows)
    total_flapping_pairs = sum(_to_int(row.get("flapping_pairs")) for row in rows)
    max_site_rows = max((_to_int(row.get("rows")) for row in rows), default=0)
    policy_rows = [
        {
            "policy_topic": "phase1_grain",
            "phase1_decision": "Keep one AIS alarm row as one candidate interval.",
            "phase2_candidate": "Compare merge windows only after owner approval.",
            "owner_decision_needed": "Approve whether fail-clear-fail intervals can be merged for modelling.",
            "guardrail": "Do not merge source truth silently.",
        },
        {
            "policy_topic": "exact_duplicates",
            "phase1_decision": "Flag exact duplicates and keep them out of production promotion evidence if source duplicate is confirmed.",
            "phase2_candidate": "Deduplicate identical site/start/restore/duration rows before challenger training.",
            "owner_decision_needed": "Confirm whether duplicates are ingestion artifacts or separate alarms.",
            "guardrail": "Do not drop rows without source-owner confirmation.",
        },
        {
            "policy_topic": "flapping_window_candidates",
            "phase1_decision": "Use review-only tags for close fail-clear-fail patterns.",
            "phase2_candidate": "Backtest merge windows: " + ", ".join(f"{window} min" for window in phase2_windows) + ".",
            "owner_decision_needed": "Select one window per alarm family if Phase 2 modelling uses merged incidents.",
            "guardrail": "Customer-facing evaluation remains AIS outage/restore truth.",
        },
        {
            "policy_topic": "promotion_gate",
            "phase1_decision": "Exclude unresolved high-flapping sites from production promotion decisions.",
            "phase2_candidate": "Allow only if merged/unmerged sensitivity does not change pass/fail gate.",
            "owner_decision_needed": "Approve sensitivity threshold for flapping-heavy sites.",
            "guardrail": f"Gate remains q50 MAE <= {GATE_Q50_MAE_MAX:g} and q10-q90 coverage {GATE_COVERAGE_MIN:g}-{GATE_COVERAGE_MAX:g}.",
        },
    ]
    _write_csv(output_csv, FLAPPING_POLICY_COLUMNS, policy_rows)
    summary = {
        "input_sites": len(rows),
        "high_priority_sites": len(high_rows),
        "duplicate_exact_rows": total_duplicate_rows,
        "flapping_pairs": total_flapping_pairs,
        "max_site_rows": max_site_rows,
        "phase2_windows": list(phase2_windows),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output),
    }
    Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
    Path(markdown_output).write_text(_render_flapping_policy_draft(summary, policy_rows, rows[:20]), encoding="utf-8-sig")
    return summary


def build_owner_handoff_pack(
    executive_one_pager: str | Path,
    growth_plan_markdown: str | Path,
    mapping_request_markdown: str | Path,
    webex_truth_markdown: str | Path,
    flapping_policy_markdown: str | Path,
    output_markdown: str | Path,
) -> dict[str, Any]:
    sources = {
        "executive_one_pager": Path(executive_one_pager),
        "growth_plan": Path(growth_plan_markdown),
        "mapping_request": Path(mapping_request_markdown),
        "webex_truth_request": Path(webex_truth_markdown),
        "flapping_policy": Path(flapping_policy_markdown),
    }
    exists = {name: path.exists() for name, path in sources.items()}
    summary = {
        "source_status": exists,
        "ready_sources": sum(1 for value in exists.values() if value),
        "output_markdown": str(output_markdown),
    }
    Path(output_markdown).parent.mkdir(parents=True, exist_ok=True)
    Path(output_markdown).write_text(_render_owner_handoff_pack(summary, sources), encoding="utf-8-sig")
    return summary


def build_owner_message_drafts(
    owner_handoff_markdown: str | Path,
    mapping_request_markdown: str | Path,
    webex_truth_markdown: str | Path,
    flapping_policy_markdown: str | Path,
    output_markdown: str | Path,
) -> dict[str, Any]:
    sources = {
        "owner_handoff": Path(owner_handoff_markdown),
        "mapping_request": Path(mapping_request_markdown),
        "webex_truth_request": Path(webex_truth_markdown),
        "flapping_policy": Path(flapping_policy_markdown),
    }
    summary = {
        "ready_sources": sum(1 for path in sources.values() if path.exists()),
        "source_status": {name: path.exists() for name, path in sources.items()},
        "output_markdown": str(output_markdown),
    }
    Path(output_markdown).parent.mkdir(parents=True, exist_ok=True)
    Path(output_markdown).write_text(_render_owner_message_drafts(summary, sources), encoding="utf-8-sig")
    return summary


def build_owner_followup_tracker(
    mapping_request_csv: str | Path,
    webex_truth_request_csv: str | Path,
    flapping_policy_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path,
) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    for row in _read_csv(mapping_request_csv):
        rows.append(
            {
                "tracker_id": f"MAP-{row.get('priority_rank', '')}",
                "workstream": "mapping_repair",
                "source_ref": row.get("site_ref", ""),
                "priority": row.get("repair_priority", ""),
                "owner": "AIS mapping owner",
                "current_status": "waiting_owner_response",
                "requested_action": row.get("requested_owner_action", ""),
                "acceptance_criteria": row.get("acceptance_criteria", ""),
                "source_file": str(mapping_request_csv),
                "next_step": "Fill mapping repair response template or mark rejected with reason.",
            }
        )
    for row in _read_csv(webex_truth_request_csv):
        rows.append(
            {
                "tracker_id": f"TRUTH-{row.get('priority_rank', '')}",
                "workstream": "webex_truth_request",
                "source_ref": row.get("event_ref", ""),
                "priority": row.get("request_priority", ""),
                "owner": "AIS truth owner",
                "current_status": "waiting_owner_response",
                "requested_action": "Return AIS AC mains outage/restore timestamp for this WebEx event.",
                "acceptance_criteria": row.get("acceptance_criteria", ""),
                "source_file": str(webex_truth_request_csv),
                "next_step": "Fill WebEx truth response template with outage_start_time and power_restore_time.",
            }
        )
    for row in _read_csv(flapping_policy_csv):
        rows.append(
            {
                "tracker_id": f"POLICY-{len([item for item in rows if item['workstream'] == 'flapping_policy']) + 1}",
                "workstream": "flapping_policy",
                "source_ref": row.get("policy_topic", ""),
                "priority": "medium",
                "owner": "Operations/data owner",
                "current_status": "waiting_owner_decision",
                "requested_action": row.get("owner_decision_needed", ""),
                "acceptance_criteria": "Owner approves Phase 1 decision or revises policy in writing.",
                "source_file": str(flapping_policy_csv),
                "next_step": "Approve policy before any Phase 2 merge sensitivity run is promoted.",
            }
        )
    _write_csv(output_csv, OWNER_TRACKER_COLUMNS, rows)
    summary = {
        "rows": len(rows),
        "mapping_rows": sum(1 for row in rows if row["workstream"] == "mapping_repair"),
        "webex_truth_rows": sum(1 for row in rows if row["workstream"] == "webex_truth_request"),
        "policy_rows": sum(1 for row in rows if row["workstream"] == "flapping_policy"),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output),
    }
    Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
    Path(markdown_output).write_text(_render_owner_followup_tracker(summary, rows), encoding="utf-8-sig")
    return summary


def build_owner_response_templates(
    mapping_request_csv: str | Path,
    webex_truth_request_csv: str | Path,
    mapping_template_csv: str | Path,
    webex_template_csv: str | Path,
    markdown_output: str | Path,
    *,
    mapping_top_n: int = 25,
    webex_top_n: int = 100,
) -> dict[str, Any]:
    mapping_rows = []
    for row in _read_csv(mapping_request_csv)[: max(mapping_top_n, 0)]:
        mapping_rows.append(
            {
                "response_type": "mapping_repair",
                "source_ref": row.get("site_ref", ""),
                "owner_decision": "",
                "mapped_site_id": "",
                "mapped_site_code": "",
                "outage_start_time": "",
                "power_restore_time": "",
                "device_id": "",
                "feeder": "",
                "owner_notes": "",
                "reviewed_by": "",
                "reviewed_at": "",
            }
        )
    webex_rows = []
    for row in _read_csv(webex_truth_request_csv)[: max(webex_top_n, 0)]:
        webex_rows.append(
            {
                "response_type": "webex_truth",
                "source_ref": row.get("event_ref", ""),
                "owner_decision": "",
                "mapped_site_id": "",
                "mapped_site_code": "",
                "outage_start_time": "",
                "power_restore_time": "",
                "device_id": row.get("device_id", ""),
                "feeder": row.get("feeder", ""),
                "owner_notes": "",
                "reviewed_by": "",
                "reviewed_at": "",
            }
        )
    _write_csv(mapping_template_csv, OWNER_RESPONSE_TEMPLATE_COLUMNS, mapping_rows)
    _write_csv(webex_template_csv, OWNER_RESPONSE_TEMPLATE_COLUMNS, webex_rows)
    summary = {
        "mapping_template_rows": len(mapping_rows),
        "webex_template_rows": len(webex_rows),
        "mapping_template_csv": str(mapping_template_csv),
        "webex_template_csv": str(webex_template_csv),
        "markdown_output": str(markdown_output),
    }
    Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
    Path(markdown_output).write_text(_render_owner_response_templates(summary), encoding="utf-8-sig")
    return summary


def validate_owner_response_files(
    mapping_response_csv: str | Path,
    webex_response_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path,
) -> dict[str, Any]:
    rows = []
    rows.extend(_validate_mapping_response_rows(_read_csv(mapping_response_csv), mapping_response_csv))
    rows.extend(_validate_webex_truth_response_rows(_read_csv(webex_response_csv), webex_response_csv))
    if not rows:
        rows.append(
            {
                "response_type": "all",
                "source_ref": "",
                "validation_status": "waiting_for_owner_response",
                "issue": "No response rows found yet.",
                "recommended_action": "Send owner message drafts and wait for completed response templates.",
            }
        )
    _write_csv(output_csv, OWNER_RESPONSE_VALIDATION_COLUMNS, rows)
    status_counts = Counter(row.get("validation_status") for row in rows)
    summary = {
        "rows": len(rows),
        "status_counts": dict(status_counts.most_common()),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output),
    }
    Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
    Path(markdown_output).write_text(_render_owner_response_validation(summary, rows), encoding="utf-8-sig")
    return summary


def build_owner_response_intake(
    validation_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path,
) -> dict[str, Any]:
    validation_rows = _read_csv(validation_csv)
    rows = [_owner_response_intake_row(row) for row in validation_rows]
    if not rows:
        rows.append(
            {
                "response_type": "all",
                "source_ref": "",
                "validation_status": "waiting_for_owner_response",
                "intake_lane": "waiting",
                "import_ready": "FALSE",
                "model_gate_eligible": "FALSE",
                "staging_target": "",
                "issue": "No validation rows found.",
                "recommended_action": "Run owner-response-validate after owner files arrive.",
            }
        )
    _write_csv(output_csv, OWNER_RESPONSE_INTAKE_COLUMNS, rows)
    lane_counts = Counter(row.get("intake_lane") for row in rows)
    summary = {
        "rows": len(rows),
        "stage_truth_rows": sum(1 for row in rows if row.get("intake_lane") == "stage_ais_truth_import"),
        "stage_mapping_rows": sum(1 for row in rows if row.get("intake_lane") == "stage_private_mapping_review"),
        "review_rows": sum(1 for row in rows if row.get("intake_lane") == "review_queue"),
        "reject_rows": sum(1 for row in rows if row.get("intake_lane") == "reject_queue"),
        "lane_counts": dict(lane_counts.most_common()),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output),
    }
    Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
    Path(markdown_output).write_text(_render_owner_response_intake(summary, rows), encoding="utf-8-sig")
    return summary


def build_owner_response_dry_run_impact(
    eligibility_csv: str | Path,
    green_gate_tracker_csv: str | Path,
    owner_response_intake_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path,
    *,
    min_green_rows: int = 30,
) -> dict[str, Any]:
    eligibility = _read_csv(eligibility_csv)
    gate_rows = _read_csv(green_gate_tracker_csv)
    intake_rows = _read_csv(owner_response_intake_csv)
    gate = {row.get("metric", ""): row.get("value", "") for row in gate_rows}
    current_green = _to_int(gate.get("green_rows")) or sum(1 for row in eligibility if row.get("eligibility_status") == "green_auto_candidate")
    ready_mapping = sum(1 for row in intake_rows if row.get("intake_lane") == "stage_private_mapping_review")
    ready_truth = sum(1 for row in intake_rows if row.get("intake_lane") == "stage_ais_truth_import")
    current_additional = max(min_green_rows - current_green, 0)
    truth_optimistic = current_green + ready_truth
    combined_optimistic = current_green + ready_truth + ready_mapping
    output_rows = [
        _dry_run_row(
            "current_baseline",
            current_green,
            ready_mapping,
            ready_truth,
            current_green,
            current_additional,
            gate.get("production_gate_status", "blocked"),
            "Current evidence only; no owner response applied.",
        ),
        _dry_run_row(
            "approved_truth_only_optimistic",
            current_green,
            ready_mapping,
            ready_truth,
            truth_optimistic,
            max(min_green_rows - truth_optimistic, 0),
            _dry_run_gate_status(truth_optimistic, gate),
            "Assumes each ready AIS truth row can become one green candidate after rerun; actual metric still requires rerun.",
        ),
        _dry_run_row(
            "mapping_plus_truth_upper_bound",
            current_green,
            ready_mapping,
            ready_truth,
            combined_optimistic,
            max(min_green_rows - combined_optimistic, 0),
            _dry_run_gate_status(combined_optimistic, gate),
            "Upper bound only; mapping repair can unlock matches but does not guarantee green accuracy.",
        ),
    ]
    _write_csv(output_csv, OWNER_DRY_RUN_IMPACT_COLUMNS, output_rows)
    summary = {
        "current_green_rows": current_green,
        "ready_mapping_rows": ready_mapping,
        "ready_truth_rows": ready_truth,
        "current_additional_green_needed": current_additional,
        "optimistic_additional_green_needed": max(min_green_rows - combined_optimistic, 0),
        "current_gate_status": gate.get("production_gate_status", "blocked"),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output),
    }
    Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
    Path(markdown_output).write_text(_render_owner_response_dry_run(summary, output_rows), encoding="utf-8-sig")
    return summary


def build_owner_response_examples(
    output_dir: str | Path,
    markdown_output: str | Path,
) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    mapping_example = root / "mapping_repair_response_examples.csv"
    webex_example = root / "webex_truth_response_examples.csv"
    _write_csv(
        mapping_example,
        OWNER_RESPONSE_TEMPLATE_COLUMNS,
        [
            {
                "response_type": "mapping_repair",
                "source_ref": "example-site-approved",
                "owner_decision": "approved",
                "mapped_site_id": "AIS_SITE_EXAMPLE_001",
                "mapped_site_code": "",
                "owner_notes": "One PEA meter maps to one AIS site.",
                "reviewed_by": "owner_name",
                "reviewed_at": "2026-06-19",
            },
            {
                "response_type": "mapping_repair",
                "source_ref": "example-site-rejected",
                "owner_decision": "rejected",
                "owner_notes": "Not an AIS site in pilot scope.",
                "reviewed_by": "owner_name",
                "reviewed_at": "2026-06-19",
            },
            {
                "response_type": "mapping_repair",
                "source_ref": "example-site-missing-reviewer",
                "owner_decision": "approved",
                "mapped_site_id": "AIS_SITE_EXAMPLE_002",
                "owner_notes": "Will be review status until reviewer metadata is filled.",
            },
        ],
    )
    _write_csv(
        webex_example,
        OWNER_RESPONSE_TEMPLATE_COLUMNS,
        [
            {
                "response_type": "webex_truth",
                "source_ref": "example-event-sustained",
                "owner_decision": "approved",
                "outage_start_time": "2026-06-19T08:00:00",
                "power_restore_time": "2026-06-19T08:35:00",
                "device_id": "EXAMPLE_DEVICE",
                "feeder": "EXAMPLE01",
                "owner_notes": "Sustained customer-facing truth.",
                "reviewed_by": "owner_name",
                "reviewed_at": "2026-06-19",
            },
            {
                "response_type": "webex_truth",
                "source_ref": "example-event-short-review",
                "owner_decision": "approved",
                "outage_start_time": "2026-06-19T09:00:00",
                "power_restore_time": "2026-06-19T09:03:00",
                "device_id": "EXAMPLE_DEVICE",
                "feeder": "EXAMPLE01",
                "owner_notes": "Short interruption; review-only.",
                "reviewed_by": "owner_name",
                "reviewed_at": "2026-06-19",
            },
            {
                "response_type": "webex_truth",
                "source_ref": "example-event-time-order-reject",
                "owner_decision": "approved",
                "outage_start_time": "2026-06-19T10:30:00",
                "power_restore_time": "2026-06-19T10:00:00",
                "device_id": "EXAMPLE_DEVICE",
                "feeder": "EXAMPLE01",
                "owner_notes": "Reject because restore precedes outage.",
                "reviewed_by": "owner_name",
                "reviewed_at": "2026-06-19",
            },
        ],
    )
    example_rows = [
        _example_row("approved_mapping", mapping_example, "ready_for_review", "Approved mapping has one mapped site key and reviewer metadata.", "Review privately before applying runtime mapping."),
        _example_row("rejected_mapping", mapping_example, "ready_for_review", "Rejected/not_applicable rows are valid decisions but do not repair mapping.", "Keep owner note as evidence."),
        _example_row("missing_reviewer_mapping", mapping_example, "review", "Reviewer metadata is required before repair.", "Fill reviewed_by and reviewed_at."),
        _example_row("sustained_webex_truth", webex_example, "ready_for_import", "AIS AC mains duration is >5 minutes.", "Import through AIS truth flow then rerun shadow refresh."),
        _example_row("short_webex_truth", webex_example, "review_only", "Duration is <=5 minutes.", "Keep out of sustained ETR gate."),
        _example_row("bad_time_order", webex_example, "reject", "Restore time is before outage start.", "Correct timestamps before import."),
    ]
    summary = {
        "mapping_example": str(mapping_example),
        "webex_example": str(webex_example),
        "example_rows": len(example_rows),
        "markdown_output": str(markdown_output),
    }
    Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
    Path(markdown_output).write_text(_render_owner_response_examples(summary, example_rows), encoding="utf-8-sig")
    return summary


def build_daily_executive_delta(
    diff_history_csv: str | Path,
    green_gate_tracker_csv: str | Path,
    owner_followup_tracker_csv: str | Path,
    owner_response_validation_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path,
) -> dict[str, Any]:
    history = _read_csv(diff_history_csv)
    current = history[-1] if history else {}
    previous = history[-2] if len(history) >= 2 else {}
    gate = {row.get("metric", ""): row.get("value", "") for row in _read_csv(green_gate_tracker_csv)}
    tracker_counts = Counter(row.get("current_status") or "blank" for row in _read_csv(owner_followup_tracker_csv))
    validation_counts = Counter(row.get("validation_status") or "blank" for row in _read_csv(owner_response_validation_csv))
    output_rows = [
        _daily_delta_row("green_auto_candidate", current, previous, "Need at least 30 green rows before promotion."),
        _daily_delta_row("amber_human_review", current, previous, "Keep amber rows status-only or human-reviewed."),
        _daily_delta_row("red_blocked", current, previous, "Do not use red rows for customer sends."),
        _daily_delta_row("monitor_only", current, previous, "Collect AIS truth for high-priority WebEx-only rows."),
        _daily_delta_row("green_q50_mae_minutes", current, previous, "Target <=16 minutes on green subset."),
        _daily_delta_row("green_q10_q90_coverage", current, previous, "Target 0.75-0.90 on green subset."),
        {
            "metric": "production_gate_status",
            "current_value": gate.get("production_gate_status", current.get("production_gate_status", "")),
            "previous_value": previous.get("production_gate_status", ""),
            "delta": "",
            "status": "blocked" if str(gate.get("production_gate_status", "")).startswith("blocked") else "review",
            "recommended_action": "Keep shadow-only until row count and metric gate both pass.",
        },
        {
            "metric": "owner_waiting_rows",
            "current_value": str(tracker_counts.get("waiting_owner_response", 0) + tracker_counts.get("waiting_owner_decision", 0)),
            "previous_value": "",
            "delta": "",
            "status": "waiting_owner",
            "recommended_action": "Follow up using owner message drafts and templates.",
        },
        {
            "metric": "owner_response_ready_rows",
            "current_value": str(validation_counts.get("ready_for_import", 0) + validation_counts.get("ready_for_review", 0)),
            "previous_value": "",
            "delta": "",
            "status": "ready" if validation_counts.get("ready_for_import", 0) or validation_counts.get("ready_for_review", 0) else "waiting",
            "recommended_action": "Run intake/dry-run before applying any owner response.",
        },
    ]
    _write_csv(output_csv, DAILY_EXECUTIVE_DELTA_COLUMNS, output_rows)
    summary = {
        "history_rows": len(history),
        "has_previous": bool(previous),
        "production_gate_status": gate.get("production_gate_status", current.get("production_gate_status", "")),
        "owner_waiting_rows": tracker_counts.get("waiting_owner_response", 0) + tracker_counts.get("waiting_owner_decision", 0),
        "owner_ready_rows": validation_counts.get("ready_for_import", 0) + validation_counts.get("ready_for_review", 0),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output),
    }
    Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
    Path(markdown_output).write_text(_render_daily_executive_delta(summary, output_rows), encoding="utf-8-sig")
    return summary


def build_executive_pitch_pack(
    executive_one_pager: str | Path,
    daily_executive_delta: str | Path,
    owner_handoff_markdown: str | Path,
    owner_followup_tracker_csv: str | Path,
    owner_response_validation_csv: str | Path,
    dry_run_impact_csv: str | Path,
    output_markdown: str | Path,
) -> dict[str, Any]:
    tracker_counts = Counter(row.get("workstream") or "blank" for row in _read_csv(owner_followup_tracker_csv))
    validation_counts = Counter(row.get("validation_status") or "blank" for row in _read_csv(owner_response_validation_csv))
    dry_run_rows = _read_csv(dry_run_impact_csv)
    gate_row = next((row for row in dry_run_rows if row.get("scenario") == "current_baseline"), {})
    summary = {
        "executive_one_pager_exists": Path(executive_one_pager).exists(),
        "daily_delta_exists": Path(daily_executive_delta).exists(),
        "owner_handoff_exists": Path(owner_handoff_markdown).exists(),
        "tracker_counts": dict(tracker_counts.most_common()),
        "validation_counts": dict(validation_counts.most_common()),
        "current_green_rows": gate_row.get("current_green_rows", ""),
        "gate_status": gate_row.get("gate_status", ""),
        "output_markdown": str(output_markdown),
    }
    Path(output_markdown).parent.mkdir(parents=True, exist_ok=True)
    Path(output_markdown).write_text(_render_executive_pitch_pack(summary, dry_run_rows), encoding="utf-8-sig")
    return summary


def build_current_capability_development_plan(
    green_gate_tracker_csv: str | Path,
    daily_steps_csv: str | Path,
    owner_followup_tracker_csv: str | Path,
    owner_response_intake_csv: str | Path,
    owner_response_dry_run_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path,
    ais_updated_summary_csv: str | Path | None = None,
    ais_updated_mapping_request_csv: str | Path | None = None,
    ais_updated_mapping_response_template: str | Path | None = None,
    ais_updated_mapping_private_lookup: str | Path | None = None,
    ais_updated_mapping_owner_message: str | Path | None = None,
) -> dict[str, Any]:
    gate = {row.get("metric", ""): row.get("value", "") for row in _read_csv(green_gate_tracker_csv)}
    step_counts = Counter(row.get("status") or "blank" for row in _read_csv(daily_steps_csv))
    owner_counts = Counter(f"{row.get('workstream')}|{row.get('current_status')}" for row in _read_csv(owner_followup_tracker_csv))
    intake_counts = Counter(row.get("intake_lane") or "blank" for row in _read_csv(owner_response_intake_csv))
    dry_run_rows = _read_csv(owner_response_dry_run_csv)
    dry_run = {row.get("scenario", ""): row for row in dry_run_rows}
    ais_updated = _read_section_key_summary(ais_updated_summary_csv) if ais_updated_summary_csv else {}
    mapping_request_rows = _read_csv(ais_updated_mapping_request_csv) if ais_updated_mapping_request_csv else []
    current_green = _to_int(gate.get("green_rows"))
    green_needed = _to_int(gate.get("additional_green_rows_needed"))
    rows = []
    rows.extend(_current_capability_can_rows())
    rows.extend(_current_capability_ais_updated_rows(ais_updated))
    rows.extend(_current_capability_cannot_rows(gate))
    rows.extend(_current_capability_plan_rows(gate, dry_run))
    rows.extend(_current_capability_acceptance_rows(gate, dry_run, intake_counts))
    _write_csv(output_csv, CURRENT_CAPABILITY_PLAN_COLUMNS, rows)
    updated_summary = ais_updated.get("summary", {})
    updated_cause = ais_updated.get("cause_all", {})
    mapping_request_rows_count = len(mapping_request_rows)
    mapping_request_potential_rows = sum(_to_int(row.get("sustained_rows")) for row in mapping_request_rows)
    mapping_request_high_rows = sum(1 for row in mapping_request_rows if row.get("repair_priority") == "high")
    summary = {
        "daily_refresh_ok_steps": step_counts.get("ok", 0),
        "daily_refresh_skipped_steps": step_counts.get("skipped", 0),
        "ais_truth_matched_rows": gate.get("ais_truth_metric_rows", ""),
        "green_rows": current_green if current_green is not None else gate.get("green_rows", ""),
        "additional_green_rows_needed": green_needed if green_needed is not None else gate.get("additional_green_rows_needed", ""),
        "green_q50_mae_minutes": gate.get("green_q50_mae_minutes", ""),
        "green_q10_q90_coverage": gate.get("green_q10_q90_coverage", ""),
        "production_gate_status": gate.get("production_gate_status", ""),
        "owner_mapping_waiting": owner_counts.get("mapping_repair|waiting_owner_response", 0),
        "owner_webex_truth_waiting": owner_counts.get("webex_truth_request|waiting_owner_response", 0),
        "owner_flapping_waiting": owner_counts.get("flapping_policy|waiting_owner_decision", 0),
        "owner_response_waiting": intake_counts.get("waiting", 0),
        "dry_run_current_gap": (dry_run.get("current_baseline", {}) or {}).get("additional_green_rows_needed", ""),
        "dry_run_optimistic_gap": (dry_run.get("mapping_plus_truth_upper_bound", {}) or {}).get("additional_green_rows_needed", ""),
        "ais_updated_available": bool(updated_summary),
        "ais_updated_rows": updated_summary.get("rows", ""),
        "ais_updated_ok_rows": updated_summary.get("ok_rows", ""),
        "ais_updated_reject_rows": updated_summary.get("reject_rows", ""),
        "ais_updated_webex_matched_rows": updated_summary.get("webex_matched_rows", ""),
        "ais_updated_webex_no_match_rows": updated_summary.get("webex_no_match_rows", ""),
        "ais_updated_pea_no_backup_rows": updated_cause.get("pea_no_backup", ""),
        "ais_updated_pea_have_backup_rows": updated_cause.get("pea_have_backup", ""),
        "ais_updated_pea_activity_rows": updated_cause.get("pea_activity", ""),
        "ais_updated_mapping_request_available": bool(mapping_request_rows),
        "ais_updated_mapping_request_rows": mapping_request_rows_count,
        "ais_updated_mapping_request_high_rows": mapping_request_high_rows,
        "ais_updated_mapping_request_potential_rows": mapping_request_potential_rows,
        "ais_updated_mapping_request_csv": str(ais_updated_mapping_request_csv) if ais_updated_mapping_request_csv else "",
        "ais_updated_mapping_response_template": str(ais_updated_mapping_response_template) if ais_updated_mapping_response_template else "",
        "ais_updated_mapping_private_lookup": str(ais_updated_mapping_private_lookup) if ais_updated_mapping_private_lookup else "",
        "ais_updated_mapping_owner_message": str(ais_updated_mapping_owner_message) if ais_updated_mapping_owner_message else "",
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output),
    }
    Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
    Path(markdown_output).write_text(_render_current_capability_development_plan(summary, rows), encoding="utf-8-sig")
    return summary


def build_flapping_sensitivity_plan(
    duplicate_flapping_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path,
    *,
    windows: Iterable[int] = (0, 5, 15, 30),
) -> dict[str, Any]:
    rows = _read_csv(duplicate_flapping_csv)
    high_sites = sum(1 for row in rows if row.get("review_priority") == "high")
    total_pairs = sum(_to_int(row.get("flapping_pairs")) for row in rows)
    output_rows = []
    for window in windows:
        scenario = "no_merge_baseline" if int(window) == 0 else f"merge_within_{int(window)}m"
        output_rows.append(
            {
                "scenario": scenario,
                "merge_window_minutes": str(window),
                "input_scope": "High duplicate/flapping AIS alarm sites from duplicate_flapping_audit.",
                "metric_to_compare": "row count, sustained truth count, q50 MAE, q10-q90 coverage, green row count",
                "pass_condition": "No production change; scenario is useful only if it explains flapping without hiding sustained outages.",
                "owner_decision_needed": "Approve before any merged incident grain is used for challenger modelling.",
            }
        )
    _write_csv(output_csv, FLAPPING_SENSITIVITY_COLUMNS, output_rows)
    summary = {
        "audit_rows": len(rows),
        "high_priority_sites": high_sites,
        "flapping_pairs": total_pairs,
        "scenarios": len(output_rows),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output),
    }
    Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
    Path(markdown_output).write_text(_render_flapping_sensitivity_plan(summary, output_rows), encoding="utf-8-sig")
    return summary


def build_pitching_narrative_script(
    executive_one_pager: str | Path,
    owner_handoff_markdown: str | Path,
    output_markdown: str | Path,
) -> dict[str, Any]:
    summary = {
        "executive_one_pager_exists": Path(executive_one_pager).exists(),
        "owner_handoff_exists": Path(owner_handoff_markdown).exists(),
        "output_markdown": str(output_markdown),
    }
    Path(output_markdown).parent.mkdir(parents=True, exist_ok=True)
    Path(output_markdown).write_text(_render_pitching_narrative_script(summary), encoding="utf-8-sig")
    return summary


def _gate_row(metric: str, value: Any, status: str, note: str) -> dict[str, str]:
    return {"metric": metric, "value": str(value), "status": status, "note": note}


def _qa_row(check: str, rows: int, status: str, note: str) -> dict[str, str]:
    return {"check": check, "rows": str(rows), "status": status, "note": note}


def _growth_row(growth_lane: str, current_rows: int, potential_rows: int, priority: str, owner: str, next_action: str, guardrail: str) -> dict[str, str]:
    return {
        "growth_lane": growth_lane,
        "current_rows": str(current_rows),
        "potential_rows": str(potential_rows),
        "priority": priority,
        "owner": owner,
        "next_action": next_action,
        "guardrail": guardrail,
    }


def _mapping_request_row(rank: int, row: dict[str, str]) -> dict[str, str]:
    return {
        "priority_rank": str(rank),
        "site_ref": row.get("site_ref", ""),
        "mapping_status": row.get("mapping_status", ""),
        "truth_quality": row.get("truth_quality", ""),
        "rows": row.get("rows", ""),
        "sustained_rows": row.get("sustained_rows", ""),
        "total_sustained_minutes": row.get("total_sustained_minutes", ""),
        "repair_priority": row.get("repair_priority", ""),
        "requested_owner_action": "Map this redacted site reference to exactly one approved AIS site/meter record, or mark as not applicable with reason.",
        "acceptance_criteria": "After rerun, mapping status is matched_single_meter or explicitly rejected with owner note.",
        "private_lookup_required": "TRUE",
    }


def _webex_truth_request_row(rank: int, row: dict[str, str]) -> dict[str, str]:
    return {
        "priority_rank": str(rank),
        "event_ref": row.get("event_ref", ""),
        "event_time": row.get("event_time", ""),
        "district": row.get("district", ""),
        "feeder": row.get("feeder", ""),
        "device_id": row.get("device_id", ""),
        "match_level": row.get("match_level", ""),
        "affected_count": row.get("affected_count", ""),
        "webex_device_interruption_class": row.get("webex_device_interruption_class", ""),
        "selected_q90": row.get("selected_q90", ""),
        "request_priority": row.get("monitor_priority", ""),
        "requested_ais_fields": "site_id, outage_start_time, power_restore_time, optional device_id, optional feeder",
        "acceptance_criteria": "AIS restore time must be a real AC mains restore timestamp; duration must be >5 minutes for sustained evaluation.",
    }


def _validate_mapping_response_rows(rows: list[dict[str, str]], source: str | Path) -> list[dict[str, str]]:
    output = []
    for row in rows:
        source_ref = row.get("source_ref") or row.get("site_ref") or row.get("location_id") or ""
        if _is_simple_mapping_response(row):
            simple_result = _validate_simple_mapping_response_row(row, source_ref)
            if simple_result:
                output.append(simple_result)
            continue
        if not _has_owner_mapping_response(row):
            continue
        decision = str(row.get("owner_decision") or "").strip().lower()
        if decision not in {"approved", "rejected", "not_applicable"}:
            output.append(_validation_row("mapping_repair", source_ref, "reject", "owner_decision must be approved/rejected/not_applicable.", "Complete owner_decision before import."))
            continue
        if decision == "approved" and not (row.get("mapped_site_id") or row.get("mapped_site_code")):
            output.append(_validation_row("mapping_repair", source_ref, "reject", "approved mapping is missing mapped_site_id or mapped_site_code.", "Add one approved mapping key or mark rejected."))
            continue
        if not row.get("reviewed_by") or not row.get("reviewed_at"):
            output.append(_validation_row("mapping_repair", source_ref, "review", "reviewed_by/reviewed_at is missing.", "Add reviewer metadata before applying repair."))
            continue
        if decision in {"rejected", "not_applicable"}:
            output.append(_validation_row("mapping_repair", source_ref, "review_only", "Owner marked this mapping as not usable.", "Keep this row out of confident mapping repair."))
            continue
        output.append(_validation_row("mapping_repair", source_ref, "ready_for_review", "Mapping response shape is usable.", "Review privately before applying to runtime mapping."))
    return output


def _is_simple_mapping_response(row: dict[str, str]) -> bool:
    return "ais_answer" in row or "confirmed_peano_or_meter_id" in row


def _has_owner_mapping_response(row: dict[str, str]) -> bool:
    response_fields = (
        "owner_decision",
        "mapped_site_id",
        "mapped_site_code",
        "owner_notes",
        "reviewed_by",
        "reviewed_at",
    )
    return any(str(row.get(field) or "").strip() for field in response_fields)


def _validate_simple_mapping_response_row(row: dict[str, str], source_ref: str) -> dict[str, str] | None:
    response_fields = (
        "ais_answer",
        "confirmed_peano_or_meter_id",
        "confirmed_site_code_if_different",
        "notes",
        "reviewed_by",
        "reviewed_at",
    )
    if not any(str(row.get(field) or "").strip() for field in response_fields):
        return None
    answer = str(row.get("ais_answer") or "").strip().lower()
    if answer not in {"confirmed", "not_found", "uncertain"}:
        return _validation_row("mapping_repair", source_ref, "reject", "ais_answer must be confirmed/not_found/uncertain.", "Use only one of the accepted simple answers.")
    if not row.get("reviewed_by") or not row.get("reviewed_at"):
        return _validation_row("mapping_repair", source_ref, "review", "reviewed_by/reviewed_at is missing.", "Add reviewer metadata before applying repair.")
    if answer == "confirmed":
        if not row.get("confirmed_peano_or_meter_id"):
            return _validation_row("mapping_repair", source_ref, "reject", "confirmed answer is missing confirmed_peano_or_meter_id.", "Add the confirmed meter key or change ais_answer.")
        return _validation_row("mapping_repair", source_ref, "ready_for_review", "Confirmed mapping response is usable.", "Review privately before applying to runtime mapping.")
    if answer == "not_found":
        return _validation_row("mapping_repair", source_ref, "review_only", "AIS marked this site as not found.", "Keep this row out of confident mapping repair.")
    return _validation_row("mapping_repair", source_ref, "review", "AIS marked this mapping as uncertain.", "Resolve manually before using this row.")


def _validate_webex_truth_response_rows(rows: list[dict[str, str]], source: str | Path) -> list[dict[str, str]]:
    output = []
    for row in rows:
        source_ref = row.get("source_ref", "")
        if not any(row.values()):
            continue
        start = _parse_datetime(row.get("outage_start_time"))
        restore = _parse_datetime(row.get("power_restore_time"))
        decision = str(row.get("owner_decision") or "").strip().lower()
        if decision and decision not in {"approved", "rejected", "not_applicable"}:
            output.append(_validation_row("webex_truth", source_ref, "reject", "owner_decision must be approved/rejected/not_applicable if filled.", "Fix owner_decision."))
            continue
        if not start or not restore:
            output.append(_validation_row("webex_truth", source_ref, "reject", "outage_start_time and power_restore_time are required.", "Fill real AIS AC mains fail/clear timestamps."))
            continue
        duration = (restore - start).total_seconds() / 60.0
        if duration < 0:
            output.append(_validation_row("webex_truth", source_ref, "reject", "restore time is before outage start.", "Correct timestamp order."))
            continue
        if duration <= 5:
            output.append(_validation_row("webex_truth", source_ref, "review_only", "duration is <=5 minutes.", "Keep out of sustained ETR gate unless owner explicitly classifies sustained impact."))
            continue
        if not row.get("reviewed_by") or not row.get("reviewed_at"):
            output.append(_validation_row("webex_truth", source_ref, "review", "reviewed_by/reviewed_at is missing.", "Add reviewer metadata before matching to shadow."))
            continue
        output.append(_validation_row("webex_truth", source_ref, "ready_for_import", "AIS truth response is sustained and structurally usable.", "Import through AIS truth flow, then rerun daily refresh."))
    return output


def _validation_row(response_type: str, source_ref: str, status: str, issue: str, action: str) -> dict[str, str]:
    return {
        "response_type": response_type,
        "source_ref": source_ref,
        "validation_status": status,
        "issue": issue,
        "recommended_action": action,
    }


def _owner_response_intake_row(row: dict[str, str]) -> dict[str, str]:
    response_type = row.get("response_type", "")
    status = row.get("validation_status", "")
    lane = "review_queue"
    import_ready = "FALSE"
    model_gate_eligible = "FALSE"
    staging_target = ""
    if status == "ready_for_import" and response_type == "webex_truth":
        lane = "stage_ais_truth_import"
        import_ready = "TRUE"
        model_gate_eligible = "TRUE"
        staging_target = "runtime/owner_response_staging/ais_truth_ready_for_import.csv"
    elif status == "ready_for_review" and response_type == "mapping_repair":
        lane = "stage_private_mapping_review"
        import_ready = "FALSE"
        staging_target = "runtime/owner_response_staging/mapping_ready_for_private_review.csv"
    elif status == "reject":
        lane = "reject_queue"
    elif status == "review_only":
        lane = "review_only_queue"
    elif status == "waiting_for_owner_response":
        lane = "waiting"
    return {
        "response_type": response_type,
        "source_ref": row.get("source_ref", ""),
        "validation_status": status,
        "intake_lane": lane,
        "import_ready": import_ready,
        "model_gate_eligible": model_gate_eligible,
        "staging_target": staging_target,
        "issue": row.get("issue", ""),
        "recommended_action": row.get("recommended_action", ""),
    }


def _dry_run_row(
    scenario: str,
    current_green_rows: int,
    ready_mapping_rows: int,
    ready_truth_rows: int,
    optimistic_green_rows: int,
    additional_green_rows_needed: int,
    gate_status: str,
    decision_note: str,
) -> dict[str, str]:
    return {
        "scenario": scenario,
        "current_green_rows": str(current_green_rows),
        "ready_mapping_rows": str(ready_mapping_rows),
        "ready_truth_rows": str(ready_truth_rows),
        "optimistic_green_rows": str(optimistic_green_rows),
        "additional_green_rows_needed": str(additional_green_rows_needed),
        "gate_status": gate_status,
        "decision_note": decision_note,
    }


def _dry_run_gate_status(optimistic_green_rows: int, gate: dict[str, str]) -> str:
    metric_gate = gate.get("production_gate_status", "blocked")
    if optimistic_green_rows < 30:
        return "blocked_too_few_green_rows"
    if str(metric_gate).startswith("blocked_metric"):
        return "blocked_metric_gate_failed_after_rerun_required"
    return "shadow_review_required"


def _example_row(example_name: str, response_file: Path, status: str, reason: str, action: str) -> dict[str, str]:
    return {
        "example_name": example_name,
        "response_file": str(response_file),
        "expected_validation_status": status,
        "reason": reason,
        "owner_action": action,
    }


def _daily_delta_row(metric: str, current: dict[str, str], previous: dict[str, str], action: str) -> dict[str, str]:
    current_value = current.get(metric, "")
    previous_value = previous.get(metric, "")
    delta = _numeric_delta(current_value, previous_value)
    status = "no_previous" if not previous else ("changed" if delta not in {"", "0", "0.0"} or current_value != previous_value else "unchanged")
    return {
        "metric": metric,
        "current_value": str(current_value),
        "previous_value": str(previous_value),
        "delta": delta,
        "status": status,
        "recommended_action": action,
    }


def _capability_row(section: str, item: str, status: str, evidence: str, action: str) -> dict[str, str]:
    return {
        "section": section,
        "item": item,
        "status": status,
        "evidence": evidence,
        "recommended_action": action,
    }


def _current_capability_can_rows() -> list[dict[str, str]]:
    return [
        _capability_row("can_do", "Use WebEx as trigger/device evidence", "ready_shadow", "Runtime pipeline parses and classifies WebEx events.", "Keep using WebEx as trigger, not restoration truth."),
        _capability_row("can_do", "Classify eligibility into green/amber/red/monitor", "ready_shadow", "Shadow eligibility and gate tracker are produced daily.", "Use eligibility status to decide status-only versus ETR candidate."),
        _capability_row("can_do", "Use AIS outage/restore as customer-facing truth", "ready_shadow", "AIS truth matched rows are tracked in green gate report.", "Only AIS outage/restore can feed customer-facing model labels."),
        _capability_row("can_do", "Generate evidence and owner workflow artifacts", "ready", "Daily refresh creates executive, owner, dry-run, and pitch artifacts.", "Use owner response loop before model tuning."),
        _capability_row("can_do", "Quarantine PEA/PowerBI context", "ready", "Context/quarantine lanes are separated from AIS truth lanes.", "Use PEA context only after approval and never as restoration label."),
    ]


def _current_capability_ais_updated_rows(summary: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    if not summary.get("summary"):
        return []
    base = summary.get("summary", {})
    cause = summary.get("cause_all", {})
    top_mapping = summary.get("top_unmapped_sitecode", {})
    top_sitecodes = ", ".join(list(top_mapping.keys())[:5])
    rows = [
        _capability_row(
            "can_do",
            "Use AIS updated history as context",
            "ready_analysis",
            f"Reviewed rows={base.get('rows', '')}; OK sustained candidates={base.get('ok_rows', '')}; cause lanes: no_backup={cause.get('pea_no_backup', '0')}, have_backup={cause.get('pea_have_backup', '0')}, activity={cause.get('pea_activity', '0')}.",
            "Keep as analysis/history context until WebEx match coverage and mapping coverage improve.",
        ),
        _capability_row(
            "cannot_do",
            "Promote AIS updated file directly to production gate",
            "blocked",
            f"Dry-run WebEx matched rows={base.get('webex_matched_rows', '')}; no-match rows={base.get('webex_no_match_rows', '')}.",
            "Use updated rows for segmentation and backlog repair, not automatic production evidence.",
        ),
        _capability_row(
            "development_plan",
            "Repair AIS updated mapping backlog",
            "next",
            f"Reject rows={base.get('reject_rows', '')}; top unmapped sitecodes={top_sitecodes}.",
            "Ask AIS to map these Location IDs to one approved AIS meter/site record, then rerun import and dry-run matching.",
        ),
        _capability_row(
            "acceptance_criteria",
            "AIS updated file remains context-only until match improves",
            "blocked",
            f"Current dry-run match={base.get('webex_matched_rows', '')}; green gate still uses runtime AIS truth matched to WebEx/topology.",
            "Do not include updated history in MAE, coverage, or production gate until promoted through a separate reviewed run.",
        ),
    ]
    return rows


def _current_capability_cannot_rows(gate: dict[str, str]) -> list[dict[str, str]]:
    green_rows = gate.get("green_rows", "")
    coverage = gate.get("green_q10_q90_coverage", "")
    return [
        _capability_row("cannot_do", "Send automatic production AIS ETR", "blocked", f"Green rows={green_rows}; production gate={gate.get('production_gate_status', '')}.", "Keep all notification behavior shadow/status-only."),
        _capability_row("cannot_do", "Promote or overwrite model artifact", "blocked", "Green sample is still below the minimum evidence threshold.", "Do not overwrite runtime model artifact until gate passes."),
        _capability_row("cannot_do", "Claim whole-system model accuracy", "blocked", f"Green rows={green_rows}; q10-q90 coverage={coverage}.", "Report only green subset metrics and caveats."),
        _capability_row("cannot_do", "Use unmatched PEA/SFSD/ReportPO as truth", "blocked", "These sources remain context/quarantine unless bridged and owner-approved.", "Keep them out of MAE, coverage, and model gate."),
        _capability_row("cannot_do", "Use feeder-only/unapproved mapping as confident impact", "blocked", "Feeder fallback and unapproved mapping can over-match customer impact.", "Require topology or owner approval before confident notification."),
        _capability_row("cannot_do", "Use short interruptions in sustained ETR gate", "blocked", "Sustained ETR policy uses >5 minutes.", "Keep <=5 minute rows as review-only."),
    ]


def _current_capability_plan_rows(gate: dict[str, str], dry_run: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    optimistic_gap = (dry_run.get("mapping_plus_truth_upper_bound", {}) or {}).get("additional_green_rows_needed", gate.get("additional_green_rows_needed", ""))
    return [
        _capability_row("development_plan", "Close owner/AIS response loop", "next", "Owner response intake is the current bottleneck.", "Collect response templates, validate, stage, and dry-run before applying."),
        _capability_row("development_plan", "Increase green evidence", "next", f"Additional green rows needed={gate.get('additional_green_rows_needed', '')}; optimistic gap={optimistic_gap}.", "Prioritize AIS truth for high-priority WebEx events and approved mapping repair."),
        _capability_row("development_plan", "Fix coverage before tuning", "next", f"q50 MAE={gate.get('green_q50_mae_minutes', '')}; q10-q90 coverage={gate.get('green_q10_q90_coverage', '')}.", "Calibrate uncertainty/status-only policy after green rows reach minimum sample size."),
        _capability_row("development_plan", "Handle long-outage evidence forward", "next", "Historical long-outage cause/lifecycle is weak.", "Use forward capture within 24 hours and only approved context as challenger features."),
        _capability_row("development_plan", "Controlled production path", "future", "Production gate is still blocked.", "Promote only green lane after row-count and metric gates pass; otherwise status-only or human-approved."),
    ]


def _current_capability_acceptance_rows(
    gate: dict[str, str],
    dry_run: dict[str, dict[str, str]],
    intake_counts: Counter,
) -> list[dict[str, str]]:
    ready_responses = intake_counts.get("stage_ais_truth_import", 0) + intake_counts.get("stage_private_mapping_review", 0)
    baseline_gap = (dry_run.get("current_baseline", {}) or {}).get("additional_green_rows_needed", gate.get("additional_green_rows_needed", ""))
    optimistic_gap = (dry_run.get("mapping_plus_truth_upper_bound", {}) or {}).get("additional_green_rows_needed", baseline_gap)
    return [
        _capability_row("acceptance_criteria", "Owner response ready rows > 0", "waiting" if ready_responses == 0 else "ready", f"Ready rows={ready_responses}.", "Wait for owner response or follow up with message drafts."),
        _capability_row("acceptance_criteria", "Dry-run gap reduces", "waiting" if optimistic_gap == baseline_gap else "improving", f"Baseline gap={baseline_gap}; optimistic gap={optimistic_gap}.", "Use dry-run impact before applying any response."),
        _capability_row("acceptance_criteria", "Green rows near or above 30", "blocked" if (_to_int(gate.get("green_rows")) or 0) < 30 else "ready", f"Green rows={gate.get('green_rows', '')}.", "Keep evidence collection focused on green growth."),
        _capability_row("acceptance_criteria", "Green coverage within target", "blocked" if gate.get("green_q10_q90_coverage") != "" and not _coverage_in_gate(gate.get("green_q10_q90_coverage")) else "review", f"Coverage={gate.get('green_q10_q90_coverage', '')}.", "Calibrate uncertainty after row count is sufficient."),
        _capability_row("acceptance_criteria", "No production send or model overwrite before gate", "ready", "Current workflow remains shadow and evidence-only.", "Keep guardrails in daily refresh and automation."),
    ]


def _coverage_in_gate(value: Any) -> bool:
    coverage = _to_float(value)
    return coverage is not None and GATE_COVERAGE_MIN <= coverage <= GATE_COVERAGE_MAX


def _numeric_delta(current_value: Any, previous_value: Any) -> str:
    current = _to_float(current_value)
    previous = _to_float(previous_value)
    if current is None or previous is None:
        return ""
    return _fmt(current - previous, digits=3)


def _rows_for_mapping_fallback(candidates: list[dict[str, str]], rejects: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for row in candidates + rejects:
        rows.append(
            {
                "location_id": row.get("site_id", ""),
                "sitecode": row.get("sitecode", ""),
                "outage_start_time": row.get("outage_start_time", ""),
                "power_restore_time": row.get("power_restore_time", ""),
                "actual_restoration_minutes": row.get("actual_restoration_minutes", ""),
                "mapping_status": _note_value(row, "mapping_status"),
                "truth_quality": row.get("truth_quality", ""),
                "alarm_type": _note_value(row, "alarm_type"),
            }
        )
    return rows


def _site_ref(location_id: Any, sitecode: Any) -> str:
    source = f"{str(location_id or '').strip()}|{str(sitecode or '').strip()}"
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:10]
    return f"site-{digest}"


def _note_value(row: dict[str, str], key: str) -> str:
    notes = row.get("truth_notes") or ""
    prefix = f"{key}="
    for part in str(notes).split(";"):
        part = part.strip()
        if part.startswith(prefix):
            return part[len(prefix) :].strip()
    return ""


def _update_time_window(bucket: dict[str, Any], timestamp: Any) -> None:
    text = str(timestamp or "").strip()
    if not text:
        return
    if not bucket.get("earliest_outage") or text < bucket["earliest_outage"]:
        bucket["earliest_outage"] = text
    if not bucket.get("latest_outage") or text > bucket["latest_outage"]:
        bucket["latest_outage"] = text


def _mapping_repair_row(bucket: dict[str, Any]) -> dict[str, str]:
    priority = _mapping_repair_priority(bucket)
    row = {
        **bucket,
        "rows": str(bucket["rows"]),
        "sustained_rows": str(bucket["sustained_rows"]),
        "review_short_rows": str(bucket["review_short_rows"]),
        "reject_rows": str(bucket["reject_rows"]),
        "missing_restore_rows": str(bucket["missing_restore_rows"]),
        "negative_duration_rows": str(bucket["negative_duration_rows"]),
        "over_24h_rows": str(bucket["over_24h_rows"]),
        "total_sustained_minutes": _fmt(bucket["total_sustained_minutes"]),
        "repair_priority": priority,
        "recommended_action": _mapping_repair_action(bucket),
    }
    return {key: str(value) for key, value in row.items()}


def _public_mapping_repair_row(row: dict[str, str]) -> dict[str, str]:
    public = {column: row.get(column, "") for column in MAPPING_REPAIR_PUBLIC_COLUMNS}
    public["mapping_status"] = _public_mapping_status(public.get("mapping_status"))
    public["truth_quality"] = _public_mapping_status(public.get("truth_quality"))
    return public


def _public_mapping_status(value: Any) -> str:
    return str(value or "").replace("peano", "meter").replace("PEANO", "meter")


def _mapping_repair_priority(bucket: dict[str, Any]) -> str:
    status = str(bucket.get("mapping_status") or "")
    if bucket.get("negative_duration_rows") or bucket.get("missing_restore_rows"):
        return "blocked_data_quality"
    if bucket.get("sustained_rows", 0) >= 50 or bucket.get("total_sustained_minutes", 0) >= 10000:
        return "critical"
    if status.startswith("no_mapped") and bucket.get("sustained_rows", 0) > 0:
        return "high"
    if "ambiguous" in status:
        return "medium"
    if bucket.get("over_24h_rows"):
        return "medium"
    return "low"


def _mapping_repair_action(bucket: dict[str, Any]) -> str:
    status = str(bucket.get("mapping_status") or "")
    if bucket.get("negative_duration_rows") or bucket.get("missing_restore_rows"):
        return "Fix AIS timestamp quality first; do not use these rows for truth yet."
    if status.startswith("no_mapped"):
        return "Ask AIS mapping owner to link this site to the approved meter mapping, then rerun AIS daily refresh."
    if "ambiguous" in status:
        return "Resolve one-site-to-one-meter ambiguity before using this site for confident evaluation."
    if bucket.get("over_24h_rows"):
        return "Review long duration before using for model gate."
    return "Keep in repair backlog; no automatic customer impact claim."


def _repair_priority_rank(value: Any) -> int:
    return {"low": 1, "blocked_data_quality": 2, "medium": 3, "high": 4, "critical": 5}.get(str(value or ""), 0)


def _duplicate_flapping_action(duplicate_rows: int, flapping_pairs: int) -> str:
    if flapping_pairs and duplicate_rows:
        return "Review whether repeated fail-clear-fail intervals should be merged before Phase 2 modelling."
    if flapping_pairs:
        return "Keep Phase 1 as one alarm per interval; tag for Phase 2 flapping merge policy."
    return "Remove exact duplicate rows from daily AIS truth before evaluation if they are source duplicates."


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is not None:
                parsed = parsed.replace(tzinfo=None)
            return parsed
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    rows = []
    with source.open(encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _contract_payload_sample(payload: dict[str, Any]) -> dict[str, Any]:
    outage_device = payload.get("outage_device") if isinstance(payload.get("outage_device"), dict) else {}
    affected_summary = payload.get("affected_summary") if isinstance(payload.get("affected_summary"), dict) else {}
    return {
        "mode": payload.get("mode", "shadow"),
        "message_type": payload.get("message_type", "status_only"),
        "event_ref": payload.get("event_ref", ""),
        "status": payload.get("status", ""),
        "source_lane": payload.get("source_lane", ""),
        "outage_device": {
            "id": outage_device.get("id", ""),
            "feeder": outage_device.get("feeder", ""),
        },
        "affected_summary": {
            "affected_count": affected_summary.get("affected_count", ""),
            "match_level": affected_summary.get("match_level", ""),
        },
        "safety_note": "No numeric ETR range is included in status-only payload.",
    }


def _duplicate_interval_rows(rows: list[dict[str, str]]) -> int:
    keys = Counter(
        (
            row.get("site_id", ""),
            row.get("outage_start_time", ""),
            row.get("power_restore_time", ""),
            row.get("actual_restoration_minutes", ""),
        )
        for row in rows
    )
    return sum(count for key, count in keys.items() if all(key) and count > 1)


def _status_payload(row: dict[str, str]) -> dict[str, Any]:
    status = "HUMAN_REVIEW_REQUIRED" if row.get("eligibility_status") == "amber_human_review" else "MONITORING_ONLY"
    if status == "HUMAN_REVIEW_REQUIRED":
        message = "พบเหตุการณ์จาก WebEx และพบผลกระทบ AIS อยู่ระหว่างตรวจสอบสาเหตุ/ความเสี่ยงก่อนแจ้ง ETR เป็นตัวเลข"
    else:
        message = "พบเหตุการณ์จาก WebEx อยู่ระหว่างรอ AIS outage/restore truth เพื่อยืนยันผลกระทบ"
    return {
        "mode": "shadow",
        "message_type": "status_only",
        "event_ref": row.get("event_ref", ""),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "source_lane": row.get("source_lane", ""),
        "outage_device": {
            "id": row.get("device_id", ""),
            "feeder": row.get("feeder", ""),
        },
        "affected_summary": {
            "affected_count": _to_int(row.get("affected_count")),
            "match_level": row.get("match_level", ""),
        },
        "customer_message_th": message,
        "blocker_reasons": [part for part in str(row.get("blocker_reasons") or "").split(";") if part],
        "safety_note": "No numeric ETR range is included in status-only payload.",
    }


def _render_green_gate_tracker(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Green Gate Tracker",
        "",
        "This tracker answers how close the green subset is to production-gate evidence. It does not approve production sends.",
        "",
        f"- AIS truth metric rows: {summary['ais_truth_metric_rows']}",
        f"- Current green rows: {summary['green_rows']}",
        f"- Minimum green rows target: {summary['min_green_rows']}",
        f"- Additional green rows needed: {summary['additional_green_rows_needed']}",
        f"- Green q50 MAE: {summary['green_q50_mae_minutes']} minutes",
        f"- Green q10-q90 coverage: {summary['green_q10_q90_coverage']}",
        f"- Gate status: `{summary['gate_status']}`",
        f"- Best threshold variant: `{summary['best_variant']}`",
        "",
        "## Gate Checks",
        "",
        *_table(rows, GATE_TRACKER_COLUMNS),
        "",
        "## Recommendation",
        "",
        "- Keep automatic ETR blocked until enough fresh green AIS-truth rows pass both MAE and coverage gates.",
        "- Treat this as a shadow evidence tracker, not a production approval.",
        "",
    ]
    return "\n".join(lines)


def _render_ais_daily_qa(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# AIS Daily File QA",
        "",
        "This report validates the latest AIS outage/restore truth candidates before they are used in evaluation. It does not import or approve production sends by itself.",
        "",
        f"- Candidate rows: {summary['candidate_rows']}",
        f"- Usable sustained OK rows: {summary['usable_sustained_ok_rows']}",
        f"- <=5 minute review rows: {summary['review_le_5min_rows']}",
        f"- Reject rows: {summary['reject_rows']}",
        f"- Missing meter-mapping rows: {summary['missing_peano_rows']}",
        f"- Missing restore rows: {summary['missing_restore_rows']}",
        f"- Negative duration rows: {summary['negative_duration_rows']}",
        f"- >24h rows: {summary['over_24h_rows']}",
        f"- Duplicate interval rows: {summary['duplicate_interval_rows']}",
        "",
        "## Checks",
        "",
        *_table(rows, AIS_DAILY_QA_COLUMNS),
        "",
        "## Guardrail",
        "",
        "- Only AIS rows with outage and restore timestamps, duration >5 minutes, usable mapping, and non-negative duration can support customer-facing ETR evaluation.",
        "- Duplicate/flapping rows remain Phase 2 review and are not merged automatically here.",
        "",
    ]
    return "\n".join(lines)


def _render_status_payloads(summary: dict[str, Any], payloads: list[dict[str, Any]]) -> str:
    sample = payloads[:5]
    rows = [
        {
            "event_ref": payload.get("event_ref", ""),
            "status": payload.get("status", ""),
            "source_lane": payload.get("source_lane", ""),
            "feeder": payload.get("outage_device", {}).get("feeder", ""),
            "device_id": payload.get("outage_device", {}).get("id", ""),
            "affected_count": str(payload.get("affected_summary", {}).get("affected_count", "")),
        }
        for payload in sample
    ]
    lines = [
        "# Status-Only Payload Templates",
        "",
        "These payloads are for amber/monitor-only shadow notifications. They intentionally omit p50/q10/q90.",
        "",
        f"- Candidate rows: {summary['candidate_rows']}",
        f"- Payload rows: {summary['payload_rows']}",
        "",
        "## Status Counts",
        "",
        *_bullet_counts(summary["status_counts"]),
        "",
        "## Sample Payload Index",
        "",
        *_table(rows, ("event_ref", "status", "source_lane", "feeder", "device_id", "affected_count")),
        "",
        "## Guardrail",
        "",
        "- Use status-only wording when the event is amber/human-review or monitor-only.",
        "- Do not include ETR p50/ranges until the green gate passes and production approval exists.",
        "",
    ]
    return "\n".join(lines)


def _render_console_qa(summary: dict[str, Any]) -> str:
    rows = [
        {"check": check, "status": "PASS" if passed else "FAIL"}
        for check, passed in summary["checks"].items()
    ]
    lines = [
        "# Operator Console QA",
        "",
        f"- HTML path: `{summary['html_path']}`",
        f"- Size: {summary['html_size_bytes']} bytes",
        f"- Status: {'PASS' if summary['passed'] else 'FAIL'}",
        "",
        "## Checks",
        "",
        *_table(rows, ("check", "status")),
        "",
        "This is a static HTML QA. Final UX approval should still use a browser visual review before pitching.",
        "",
    ]
    return "\n".join(lines)


def _render_mapping_repair_queue(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# AIS Mapping Repair Queue",
        "",
        "This queue turns AIS daily QA failures into repair actions. The public queue uses redacted `site_ref` values; the private queue keeps raw join keys for the mapping owner.",
        "",
        f"- Input rows reviewed: {summary['input_rows']}",
        f"- Repair groups: {summary['repair_groups']}",
        f"- Selected queue rows: {summary['selected_rows']}",
        f"- Private repair file: `{summary['private_output_csv']}`",
        "",
        "## Priority Counts",
        "",
        *_bullet_counts(summary["priority_counts"]),
        "",
        "## Mapping Status Counts",
        "",
        *_bullet_counts(summary["mapping_status_counts"]),
        "",
        "## Top Queue",
        "",
        *_table(rows, ("site_ref", "mapping_status", "truth_quality", "rows", "sustained_rows", "total_sustained_minutes", "repair_priority", "recommended_action")),
        "",
        "## Guardrail",
        "",
        "- Use the public report for planning and the private file only for source-owner repair.",
        "- Missing or ambiguous mapping must not become confident customer impact until repaired and rerun.",
        "",
    ]
    return "\n".join(lines)


def _render_duplicate_flapping_audit(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Duplicate And Flapping Audit",
        "",
        "This audit identifies exact duplicate intervals and fail-clear-fail patterns in AIS outage/restore truth. Phase 1 still keeps one alarm row as one candidate interval; this report only flags review risk.",
        "",
        f"- Input intervals reviewed: {summary['input_rows']}",
        f"- Sites with duplicate/flapping findings: {summary['sites_with_findings']}",
        f"- Selected queue rows: {summary['selected_rows']}",
        f"- Flapping window: {summary['flap_window_minutes']} minutes",
        f"- Exact duplicate rows: {summary['duplicate_exact_rows']}",
        f"- Flapping pairs: {summary['flapping_pairs']}",
        "",
        "## Review Queue",
        "",
        *_table(rows, ("site_ref", "rows", "sustained_rows", "review_short_rows", "duplicate_exact_rows", "duplicate_groups", "flapping_pairs", "max_duration_minutes", "review_priority", "recommended_action")),
        "",
        "## Guardrail",
        "",
        "- Do not merge intervals automatically in Phase 1.",
        "- If a site repeatedly fails and clears within a few minutes, keep it out of promotion decisions until the merge policy is approved.",
        "",
    ]
    return "\n".join(lines)


def _render_green_growth_plan(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Green Candidate Growth Plan",
        "",
        "This plan prioritizes how to grow the safe green subset without relaxing truth or production guardrails.",
        "",
        f"- Current green rows: {summary['green_rows']}",
        f"- Minimum green rows target: {summary['min_green_rows']}",
        f"- Additional green rows needed: {summary['additional_green_needed']}",
        f"- High-priority WebEx rows waiting for AIS truth: {summary['high_priority_webex_rows']}",
        f"- High-priority mapping repair rows: {summary['high_mapping_repair_rows']}",
        f"- Amber momentary rows needing review: {summary['amber_momentary_rows']}",
        f"- Production gate: `{summary['gate_status']}`",
        "",
        "## Growth Lanes",
        "",
        *_table(rows, GREEN_GROWTH_COLUMNS),
        "",
        "## Recommendation",
        "",
        "- Spend effort first on high-priority WebEx rows that only need AIS truth, then mapping repair, then amber review.",
        "- Keep the green definition strict; growth should come from better evidence, not looser thresholds.",
        "",
    ]
    return "\n".join(lines)


def _render_shadow_status_contract(summary: dict[str, Any], samples: list[dict[str, Any]]) -> str:
    sample_text = "\n\n".join(f"```json\n{json.dumps(sample, ensure_ascii=False, indent=2, sort_keys=True)}\n```" for sample in samples) or "No sample payloads available yet."
    lines = [
        "# Shadow Status Payload Contract",
        "",
        "This contract separates automatic ETR candidates from status-only shadow messages. It is not a production AIS send approval.",
        "",
        f"- Status-only payload rows available: {summary['payload_rows']}",
        f"- Sample rows shown: {summary['sample_rows']}",
        "",
        "## Eligibility Rules",
        "",
        "|Status|Allowed payload|Numeric ETR?|Decision|",
        "|---|---|---|---|",
        "|green_auto_candidate|Shadow ETR payload after gate review|Only after metric gate and human approval|Still blocked for production today|",
        "|amber_human_review|Status-only / human review|No|Operator must review cause, lifecycle, and uncertainty|",
        "|monitor_only|Monitoring-only|No|Wait for AIS outage/restore truth|",
        "|red_blocked|No customer-facing payload|No|Blocked by quarantine, missing mapping, or unsafe evidence|",
        "",
        "## Status-Only Fields",
        "",
        "- `mode`: always `shadow`",
        "- `message_type`: `status_only`",
        "- `event_ref`: redacted event reference",
        "- `status`: `HUMAN_REVIEW_REQUIRED` or `MONITORING_ONLY`",
        "- `source_lane`: AIS-truth, WebEx-only, or quarantined lane",
        "- `outage_device`: device id and feeder only",
        "- `affected_summary`: count and match level only",
        "- `blocker_reasons`: why numeric ETR is withheld",
        "",
        "## Sample Status Payloads",
        "",
        sample_text,
        "",
        "## Guardrail",
        "",
        "- Status-only messages intentionally omit p50, q10, q25, q75, and q90.",
        "- AIS outage/restore remains the only customer-facing truth label.",
        "- WebEx remains trigger/device evidence; PEA context remains gated and feature-only.",
        "",
    ]
    return "\n".join(lines)


def _render_executive_one_pager(summary: dict[str, Any]) -> str:
    top_growth = summary["growth_rows"][:4]
    lines = [
        "# AIS ETR Shadow Pilot One-Pager",
        "",
        "## Decision",
        "",
        f"Production ETR send remains **blocked**: `{summary['gate_status']}`.",
        "",
        "## Current Evidence",
        "",
        f"- Total shadow rows: {summary['total_rows']}",
        f"- AIS-truth matched rows: {summary['ais_truth_matched']}",
        f"- WebEx-only monitor rows: {summary['webex_only']}",
        f"- PEA context quarantined rows: {summary['pea_quarantined']}",
        f"- Green auto candidates: {summary['green']}",
        f"- Amber human review: {summary['amber']}",
        f"- Red blocked: {summary['red']}",
        f"- Monitor only: {summary['monitor']}",
        f"- Green q50 MAE: {summary['green_mae']} minutes",
        f"- Green q10-q90 coverage: {summary['green_coverage']}",
        f"- Additional green rows needed: {summary['additional_green_needed']}",
        "",
        "## AIS Daily Truth Health",
        "",
        f"- Usable sustained rows: {summary['usable_sustained_ok_rows']}",
        f"- Missing mapping rows: {summary['missing_mapping_rows']}",
        f"- Duplicate interval rows: {summary['duplicate_interval_rows']}",
        "",
        "## Next Work",
        "",
        *_table(top_growth, ("growth_lane", "current_rows", "potential_rows", "priority", "owner", "next_action")),
        "",
        "## Guardrails",
        "",
        "- Train/evaluate on AIS outage/restore truth only.",
        "- Use WebEx as trigger and device evidence.",
        "- Keep PEA/SFSD/ReportPO as context-only until reviewed and approved.",
        "- Use status-only messaging for amber or monitor-only events.",
        "- Do not overwrite the production model artifact or send AIS production notifications.",
        "",
    ]
    return "\n".join(lines)


def _render_mapping_repair_request_pack(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# AIS Mapping Repair Request Pack",
        "",
        "This pack is for the AIS mapping owner. The public file uses redacted `site_ref`; the private file contains the raw lookup keys needed to repair mappings.",
        "",
        f"- Candidate repair rows: {summary['candidate_rows']}",
        f"- Selected rows for owner action: {summary['selected_rows']}",
        f"- Critical rows: {summary['critical_rows']}",
        f"- High rows: {summary['high_rows']}",
        f"- Potential sustained rows in selected queue: {summary['potential_sustained_rows']}",
        f"- Private owner file: `{summary['private_output_csv']}`",
        "",
        "## Owner Actions",
        "",
        *_table(rows, ("priority_rank", "site_ref", "mapping_status", "rows", "sustained_rows", "total_sustained_minutes", "repair_priority", "requested_owner_action")),
        "",
        "## Acceptance Criteria",
        "",
        "- Each selected `site_ref` must be mapped to exactly one approved AIS site/meter record, or rejected with owner reason.",
        "- After daily refresh, repaired rows should move out of missing/ambiguous mapping status.",
        "- No production notification changes happen from this pack alone.",
        "",
        "## Guardrail",
        "",
        "- Use the private CSV only with the mapping owner; do not paste raw keys into executive reports.",
        "- Mapping repair improves evaluation coverage but does not by itself approve customer-facing ETR sends.",
        "",
    ]
    return "\n".join(lines)


def _render_webex_truth_request_pack(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# WebEx High-Priority AIS Truth Request Pack",
        "",
        "This pack lists WebEx triggers with protection-level evidence but no AIS outage/restore truth yet. It is designed for daily AIS truth follow-up.",
        "",
        f"- Candidate WebEx rows: {summary['candidate_rows']}",
        f"- Selected rows: {summary['selected_rows']}",
        f"- High-priority rows: {summary['high_rows']}",
        f"- Total affected count across selected rows: {summary['affected_total']}",
        "",
        "## Top Feeders",
        "",
        *_bullet_counts(summary["feeder_counts"]),
        "",
        "## Device State Counts",
        "",
        *_bullet_counts(summary["device_state_counts"]),
        "",
        "## AIS Truth Request Queue",
        "",
        *_table(rows, ("priority_rank", "event_ref", "event_time", "district", "feeder", "device_id", "match_level", "affected_count", "request_priority", "requested_ais_fields")),
        "",
        "## Requested Return Format",
        "",
        "- `event_ref` from this pack if possible",
        "- `site_id`",
        "- `outage_start_time` as actual AIS AC mains fail time",
        "- `power_restore_time` as actual AIS AC mains clear time",
        "- optional `device_id`, `feeder`, and owner notes",
        "",
        "## Guardrail",
        "",
        "- Do not use WebEx-only rows for MAE, coverage, training, or production ETR until AIS truth arrives.",
        "- Status-only messaging remains the maximum allowed action while truth is missing.",
        "",
    ]
    return "\n".join(lines)


def _render_flapping_policy_draft(summary: dict[str, Any], policy_rows: list[dict[str, str]], sample_rows: list[dict[str, str]]) -> str:
    lines = [
        "# Duplicate/Flapping Review Policy Draft",
        "",
        "This draft keeps Phase 1 conservative: one AIS alarm row remains one candidate interval. Duplicate and fail-clear-fail patterns are flagged for review, not merged automatically.",
        "",
        f"- Sites in audit queue: {summary['input_sites']}",
        f"- High-priority sites: {summary['high_priority_sites']}",
        f"- Exact duplicate rows in selected audit: {summary['duplicate_exact_rows']}",
        f"- Flapping pairs in selected audit: {summary['flapping_pairs']}",
        f"- Max rows on one audited site: {summary['max_site_rows']}",
        f"- Phase 2 candidate windows: {', '.join(str(window) + ' min' for window in summary['phase2_windows'])}",
        "",
        "## Draft Policy",
        "",
        *_table(policy_rows, FLAPPING_POLICY_COLUMNS),
        "",
        "## Top Review Signals",
        "",
        *_table(sample_rows, ("site_ref", "rows", "sustained_rows", "review_short_rows", "duplicate_exact_rows", "flapping_pairs", "review_priority")),
        "",
        "## Owner Decision Needed",
        "",
        "- Confirm whether exact duplicates are source duplicates or separate alarms.",
        "- Approve whether Phase 2 should test 5/15/30 minute merge windows.",
        "- Decide whether flapping-heavy sites should be excluded from production promotion evidence until sensitivity passes.",
        "",
        "## Guardrail",
        "",
        "- No automatic merge in Phase 1.",
        "- AIS outage/restore remains the evaluation truth, and production sends remain blocked by gate.",
        "",
    ]
    return "\n".join(lines)


def _render_owner_handoff_pack(summary: dict[str, Any], sources: dict[str, Path]) -> str:
    rows = [
        {
            "artifact": name,
            "path": str(path),
            "status": "ready" if summary["source_status"].get(name) else "missing",
            "owner_use": _handoff_owner_use(name),
        }
        for name, path in sources.items()
    ]
    lines = [
        "# AIS ETR Owner Handoff Pack",
        "",
        "This pack gives each owner the smallest set of actions that can improve shadow evidence without changing production send behavior.",
        "",
        f"- Ready artifacts: {summary['ready_sources']} / {len(sources)}",
        "",
        "## Artifact Index",
        "",
        *_table(rows, ("artifact", "status", "path", "owner_use")),
        "",
        "## Recommended Owner Sequence",
        "",
        "1. AIS mapping owner repairs the private mapping queue.",
        "2. AIS truth owner returns outage/restore rows for high-priority WebEx events.",
        "3. Operations/data owner approves or revises the duplicate/flapping policy.",
        "4. ETR model owner reruns daily refresh and checks whether green rows move toward 30.",
        "",
        "## Production Guardrail",
        "",
        "- No production AIS send.",
        "- No overwrite of `runtime/model_quantiles.json`.",
        "- PEA/PowerBI context remains context-only until reviewed and approved.",
        "- Use status-only messages for amber or WebEx-only rows.",
        "",
    ]
    return "\n".join(lines)


def _render_owner_message_drafts(summary: dict[str, Any], sources: dict[str, Path]) -> str:
    lines = [
        "# Owner Message Drafts TH",
        "",
        "ใช้ร่างข้อความนี้ส่งต่อให้เจ้าของข้อมูล โดยแนบไฟล์ตาม path ที่ระบุและห้ามส่ง credentials, WebEx room identifier, verbatim WebEx text หรือข้อมูลลูกค้าที่ไม่จำเป็น",
        "",
        f"- Ready sources: {summary['ready_sources']} / {len(sources)}",
        "",
        "## Draft 1: AIS Mapping Owner",
        "",
        "หัวข้อ: ขอความช่วยเหลือซ่อม mapping site AIS สำหรับ AIS ETR shadow pilot",
        "",
        "เรียนทีม AIS mapping,",
        "",
        "รบกวนตรวจรายการในไฟล์ private mapping repair response ตาม `runtime/private/ais_mapping_repair_request_owner.csv` โดยเป้าหมายคือยืนยันว่าแต่ละ `site_ref` map ไปยัง site/meter ที่ถูกต้องหนึ่งรายการ หรือระบุว่าไม่เกี่ยวข้องพร้อมเหตุผล",
        "",
        "ขอให้กรอกผลตอบกลับใน template ที่แนบ โดยใช้ `owner_decision = approved/rejected/not_applicable` และระบุ `reviewed_by`, `reviewed_at` ทุกแถวที่ตอบกลับ",
        "",
        "หมายเหตุ: งานนี้ยังเป็น shadow mode เท่านั้น ไม่มีการส่ง notification จริงให้ AIS",
        "",
        "## Draft 2: AIS Truth Owner",
        "",
        "หัวข้อ: ขอ AIS outage/restore truth สำหรับ WebEx high-priority events",
        "",
        "เรียนทีม AIS alarm/truth data,",
        "",
        "รบกวนเติม `outage_start_time` และ `power_restore_time` ตามไฟ AC mains ดับ/กลับจริง สำหรับรายการ `event_ref` ใน `runtime/webex_ais_truth_request.csv` เพื่อให้ระบบประเมิน ETR ด้วย customer-facing truth ได้ถูกต้อง",
        "",
        "กรุณาใช้เวลาไฟดับจริงจาก AIS ไม่ใช่เวลาเปิด/ปิด ticket และถ้า duration <=5 นาที ให้ระบบจะถือเป็น review-only ไม่ใช้ตัดสิน model gate หลัก",
        "",
        "## Draft 3: Operations/Data Owner",
        "",
        "หัวข้อ: ขอ approve policy สำหรับ duplicate/flapping AIS alarm",
        "",
        "เรียนทีม operation/data,",
        "",
        "รบกวนพิจารณา `runtime/duplicate_flapping_policy.md` เพื่อยืนยันนโยบาย Phase 1 ว่ายังไม่ merge fail-clear-fail อัตโนมัติ และให้ Phase 2 ทดสอบ sensitivity ที่ 5/15/30 นาทีหลังได้รับอนุมัติเท่านั้น",
        "",
        "## Attachments / Links",
        "",
        f"- Owner handoff: `{sources['owner_handoff']}`",
        f"- Mapping request: `{sources['mapping_request']}`",
        f"- WebEx truth request: `{sources['webex_truth_request']}`",
        f"- Flapping policy: `{sources['flapping_policy']}`",
        "",
    ]
    return "\n".join(lines)


def _render_owner_followup_tracker(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    counts = Counter(row.get("workstream") for row in rows)
    lines = [
        "# Owner Follow-Up Tracker",
        "",
        "This tracker summarizes owner-facing follow-up tasks without exposing raw mapping keys or customer identifiers.",
        "",
        f"- Total tracker rows: {summary['rows']}",
        f"- Mapping repair rows: {summary['mapping_rows']}",
        f"- WebEx truth rows: {summary['webex_truth_rows']}",
        f"- Policy rows: {summary['policy_rows']}",
        "",
        "## Workstream Counts",
        "",
        *_bullet_counts(dict(counts.most_common())),
        "",
        "## Top Rows",
        "",
        *_table(rows, ("tracker_id", "workstream", "source_ref", "priority", "owner", "current_status", "next_step")),
        "",
        "## Guardrail",
        "",
        "- Tracker rows are follow-up tasks only; they do not apply mapping repair or truth import.",
        "- Use private response files only with source owners.",
        "",
    ]
    return "\n".join(lines)


def _render_owner_response_templates(summary: dict[str, Any]) -> str:
    lines = [
        "# Owner Response Templates",
        "",
        "Templates are ready for owners to fill. Completed files must pass validation before any import or repair is applied.",
        "",
        f"- Mapping response template rows: {summary['mapping_template_rows']}",
        f"- WebEx truth response template rows: {summary['webex_template_rows']}",
        f"- Mapping template: `{summary['mapping_template_csv']}`",
        f"- WebEx truth template: `{summary['webex_template_csv']}`",
        "",
        "## Required Rules",
        "",
        "- `owner_decision` must be `approved`, `rejected`, or `not_applicable`.",
        "- Mapping repair approvals need `mapped_site_id` or `mapped_site_code`.",
        "- WebEx truth approvals need `outage_start_time` and `power_restore_time` from AIS AC mains fail/clear.",
        "- All completed rows need `reviewed_by` and `reviewed_at`.",
        "",
    ]
    return "\n".join(lines)


def _render_owner_response_validation(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Owner Response Validation",
        "",
        "This validates returned owner response files before any repair/import step. It does not apply changes.",
        "",
        f"- Validation rows: {summary['rows']}",
        "",
        "## Status Counts",
        "",
        *_bullet_counts(summary["status_counts"]),
        "",
        "## Validation Rows",
        "",
        *_table(rows, OWNER_RESPONSE_VALIDATION_COLUMNS),
        "",
        "## Guardrail",
        "",
        "- Rows with `reject`, `review`, or `review_only` are not eligible for direct model gate use.",
        "- AIS truth must be sustained >5 minutes before it can count in the sustained ETR gate.",
        "",
    ]
    return "\n".join(lines)


def _render_owner_response_intake(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Owner Response Intake",
        "",
        "This stages validated owner responses into safe lanes. It does not apply mapping repair, import AIS truth, send notifications, or promote a model.",
        "",
        f"- Intake rows: {summary['rows']}",
        f"- AIS truth rows ready for import: {summary['stage_truth_rows']}",
        f"- Mapping rows ready for private review: {summary['stage_mapping_rows']}",
        f"- Review rows: {summary['review_rows']}",
        f"- Reject rows: {summary['reject_rows']}",
        "",
        "## Lane Counts",
        "",
        *_bullet_counts(summary["lane_counts"]),
        "",
        "## Intake Rows",
        "",
        *_table(rows, OWNER_RESPONSE_INTAKE_COLUMNS),
        "",
        "## Guardrail",
        "",
        "- `stage_ais_truth_import` can become model/evaluation truth only after AIS truth import and shadow rematch.",
        "- `stage_private_mapping_review` still needs private review before runtime mapping repair.",
        "- `review_only`, `review`, and `reject` rows stay out of the sustained ETR gate.",
        "",
    ]
    return "\n".join(lines)


def _render_owner_response_dry_run(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Owner Response Dry-Run Impact",
        "",
        "This estimates how validated owner responses could affect green evidence. It is intentionally conservative and does not apply any response.",
        "",
        f"- Current green rows: {summary['current_green_rows']}",
        f"- Ready mapping rows: {summary['ready_mapping_rows']}",
        f"- Ready AIS truth rows: {summary['ready_truth_rows']}",
        f"- Current additional green rows needed: {summary['current_additional_green_needed']}",
        f"- Optimistic additional green rows needed: {summary['optimistic_additional_green_needed']}",
        f"- Current gate status: {summary['current_gate_status']}",
        "",
        "## Scenarios",
        "",
        *_table(rows, OWNER_DRY_RUN_IMPACT_COLUMNS),
        "",
        "## Interpretation",
        "",
        "- This report is a planning estimate, not model evidence.",
        "- Mapping repair can improve match coverage but does not guarantee green eligibility.",
        "- AIS truth rows must be imported, matched, and evaluated before any gate claim.",
        "- Production AIS send remains blocked until green subset row count and metrics pass.",
        "",
    ]
    return "\n".join(lines)


def _render_owner_response_examples(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Owner Response Examples",
        "",
        "These examples show owners how to fill response files and what validation result to expect. They are synthetic examples only.",
        "",
        f"- Mapping examples: `{summary['mapping_example']}`",
        f"- WebEx truth examples: `{summary['webex_example']}`",
        f"- Example cases: {summary['example_rows']}",
        "",
        "## Expected Outcomes",
        "",
        *_table(rows, OWNER_RESPONSE_EXAMPLE_COLUMNS),
        "",
        "## Rules To Remember",
        "",
        "- Truth label: AIS outage/restore only.",
        "- Use `approved`, `rejected`, or `not_applicable` for `owner_decision`.",
        "- AIS truth must use real AC mains fail/clear time, not ticket close time.",
        "- Duration `<=5` minutes is review-only for customer-facing ETR gate.",
        "- Every completed row needs `reviewed_by` and `reviewed_at`.",
        "",
    ]
    return "\n".join(lines)


def _render_daily_executive_delta(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Daily Executive Delta",
        "",
        "A compact daily movement report for the AIS ETR shadow pilot.",
        "",
        f"- History rows: {summary['history_rows']}",
        f"- Has previous run: {summary['has_previous']}",
        f"- Production gate status: {summary['production_gate_status']}",
        f"- Owner waiting rows: {summary['owner_waiting_rows']}",
        f"- Owner response ready rows: {summary['owner_ready_rows']}",
        "",
        "## Metric Movement",
        "",
        *_table(rows, DAILY_EXECUTIVE_DELTA_COLUMNS),
        "",
        "## Decision",
        "",
        "- Keep shadow-only.",
        "- Prioritize owner responses that add AIS truth and repair mapping.",
        "- Do not tune/promote model from PEA context or unapproved owner responses.",
        "",
    ]
    return "\n".join(lines)


def _render_executive_pitch_pack(summary: dict[str, Any], dry_run_rows: list[dict[str, str]]) -> str:
    lines = [
        "# AIS ETR Executive Pitch Pack",
        "",
        "## Decision Summary",
        "",
        "The project should continue as a confidence-gated shadow pilot. It is not ready for automatic production ETR sends, but it now has a clear evidence workflow for becoming ready.",
        "",
        f"- Current green rows: {summary['current_green_rows']}",
        f"- Current gate status: {summary['gate_status']}",
        f"- Executive one-pager exists: {summary['executive_one_pager_exists']}",
        f"- Daily delta exists: {summary['daily_delta_exists']}",
        f"- Owner handoff exists: {summary['owner_handoff_exists']}",
        "",
        "## Owner Work Still Open",
        "",
        *_bullet_counts(summary["tracker_counts"]),
        "",
        "## Owner Response Validation",
        "",
        *_bullet_counts(summary["validation_counts"]),
        "",
        "## Dry-Run Impact",
        "",
        *_table(dry_run_rows, OWNER_DRY_RUN_IMPACT_COLUMNS),
        "",
        "## Narrative For Stakeholders",
        "",
        "1. WebEx is already useful as the live trigger and device evidence.",
        "2. AIS outage/restore remains the only customer-facing truth label.",
        "3. PEA/PowerBI sources are context-only unless owner approved.",
        "4. The system sends nothing to production until green evidence passes row-count and metric gates.",
        "5. The fastest path is owner response closure: AIS truth for WebEx events and private mapping repair.",
        "",
        "## Next Ask",
        "",
        "- AIS truth owner: return outage/restore times for high-priority WebEx events.",
        "- AIS mapping owner: approve or reject mapping repair rows.",
        "- Operations/data owner: approve Phase 1 duplicate/flapping policy before Phase 2 sensitivity.",
        "",
        "## Guardrail",
        "",
        "- No production AIS send.",
        "- No overwrite of `runtime/model_quantiles.json`.",
        "- No customer identifier list or verbatim WebEx text is required for this executive pack.",
        "",
    ]
    return "\n".join(lines)


def _render_current_capability_development_plan(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    can_rows = [row for row in rows if row.get("section") == "can_do"]
    cannot_rows = [row for row in rows if row.get("section") == "cannot_do"]
    plan_rows = [row for row in rows if row.get("section") == "development_plan"]
    acceptance_rows = [row for row in rows if row.get("section") == "acceptance_criteria"]
    lines = [
        "# AIS ETR Current Capability & Development Plan",
        "",
        "This report is generated from the latest shadow runtime artifacts. It summarizes what the pilot can do now, what remains blocked, and the next development sequence.",
        "",
        "## Current Status",
        "",
        f"- Daily refresh: {summary['daily_refresh_ok_steps']} OK, {summary['daily_refresh_skipped_steps']} skipped",
        f"- AIS truth matched rows: {summary['ais_truth_matched_rows']}",
        f"- Green auto candidates: {summary['green_rows']}",
        f"- Additional green rows needed: {summary['additional_green_rows_needed']}",
        f"- Green q50 MAE: {summary['green_q50_mae_minutes']} minutes",
        f"- Green q10-q90 coverage: {summary['green_q10_q90_coverage']}",
        f"- Production gate status: {summary['production_gate_status']}",
        f"- Owner follow-up waiting: mapping {summary['owner_mapping_waiting']}, WebEx truth {summary['owner_webex_truth_waiting']}, flapping policy {summary['owner_flapping_waiting']}",
        f"- Owner response intake waiting rows: {summary['owner_response_waiting']}",
        "",
        "## What We Can Do Now",
        "",
        *_table(can_rows, CURRENT_CAPABILITY_PLAN_COLUMNS),
        "",
        "## What We Cannot Or Should Not Do Yet",
        "",
        *_table(cannot_rows, CURRENT_CAPABILITY_PLAN_COLUMNS),
        "",
        "## Development Plan",
        "",
        *_table(plan_rows, CURRENT_CAPABILITY_PLAN_COLUMNS),
        "",
        "## Next Acceptance Criteria",
        "",
        *_table(acceptance_rows, CURRENT_CAPABILITY_PLAN_COLUMNS),
        "",
        "## Default Next Action",
        "",
        "Close the owner response loop first. Send the owner message drafts and response templates, place returned files under `runtime/owner_responses/`, then rerun `python -m ais_etr daily-shadow-refresh` so the system can validate, stage, and estimate impact before any manual apply step.",
        "",
        "## Public-Report Guardrail",
        "",
        "- Keep production sends disabled.",
        "- Keep the current model artifact unchanged until promotion gates pass.",
        "- Public reports must avoid credentials, WebEx room identifiers, verbatim WebEx message bodies, customer meter lists, and unnecessary customer identity fields.",
        "",
    ]
    if summary.get("ais_updated_available"):
        marker = lines.index("## What We Can Do Now")
        lines[marker:marker] = [
            "## AIS Updated File Analysis",
            "",
            f"- Updated AIS history rows reviewed: {summary.get('ais_updated_rows', '')}",
            f"- OK sustained candidates: {summary.get('ais_updated_ok_rows', '')}",
            f"- Reject/review rows: {summary.get('ais_updated_reject_rows', '')}",
            f"- WebEx dry-run matched rows: {summary.get('ais_updated_webex_matched_rows', '')}",
            f"- WebEx dry-run no-match rows: {summary.get('ais_updated_webex_no_match_rows', '')}",
            f"- Cause lanes: pea_no_backup {summary.get('ais_updated_pea_no_backup_rows', '')}, pea_have_backup {summary.get('ais_updated_pea_have_backup_rows', '')}, pea_activity {summary.get('ais_updated_pea_activity_rows', '')}",
            "- Status: analysis/history context only; not promoted into production gate.",
            "",
        ]
    if summary.get("ais_updated_mapping_request_available"):
        marker = lines.index("## What We Can Do Now")
        lines[marker:marker] = [
            "## AIS Mapping Response Loop",
            "",
            f"- Selected owner mapping rows: {summary.get('ais_updated_mapping_request_rows', 0)}",
            f"- High-priority rows: {summary.get('ais_updated_mapping_request_high_rows', 0)}",
            f"- Potential sustained rows covered: {summary.get('ais_updated_mapping_request_potential_rows', 0)}",
            f"- Owner message: `{summary.get('ais_updated_mapping_owner_message', '')}`",
            f"- Response template: `{summary.get('ais_updated_mapping_response_template', '')}`",
            f"- Private owner lookup: `{summary.get('ais_updated_mapping_private_lookup', '')}`",
            "- Status: waiting for AIS owner response; validation and dry-run are required before any staging.",
            "",
        ]
    return "\n".join(lines)


def _render_flapping_sensitivity_plan(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Flapping Sensitivity Plan",
        "",
        "This plan prepares Phase 2 sensitivity analysis without merging alarms in Phase 1.",
        "",
        f"- Audited sites in selected queue: {summary['audit_rows']}",
        f"- High-priority sites: {summary['high_priority_sites']}",
        f"- Flapping pairs: {summary['flapping_pairs']}",
        f"- Scenarios: {summary['scenarios']}",
        "",
        "## Scenarios",
        "",
        *_table(rows, FLAPPING_SENSITIVITY_COLUMNS),
        "",
        "## Guardrail",
        "",
        "- No merge is applied until owner approves the policy.",
        "- Any merged challenger must be compared against the unmerged baseline before promotion.",
        "",
    ]
    return "\n".join(lines)


def _render_pitching_narrative_script(summary: dict[str, Any]) -> str:
    lines = [
        "# AIS ETR Pitching Narrative Script",
        "",
        "## 30-Second Opening",
        "",
        "โครงการนี้ไม่ได้เริ่มจากการส่ง ETR อัตโนมัติทันที แต่เริ่มจากระบบ shadow ที่เชื่อม WebEx, map อุปกรณ์ป้องกันกับ AIS asset, เทียบกับ AIS outage/restore truth และกันเคสที่ไม่มั่นใจออกก่อน เพื่อไม่ให้ลูกค้าได้รับตัวเลขที่ดูแม่นแต่ผิดจริง",
        "",
        "## Core Message",
        "",
        "- WebEx เป็น trigger/device evidence",
        "- AIS outage/restore เป็น customer-facing truth",
        "- PEA/SFSD/ReportPO เป็น context เท่านั้นจนกว่าจะ owner approve",
        "- ระบบมี green/amber/red/monitor gate ก่อนส่งจริง",
        "- ตอนนี้ production ยัง blocked เพราะ green evidence ยังน้อยกว่าเกณฑ์",
        "",
        "## What We Can Show",
        "",
        "1. ระบบรับ WebEx event และจัดกลุ่ม eligibility ได้",
        "2. ระบบรู้ว่าเคสไหนยังขาด AIS truth และต้องขอข้อมูลอะไร",
        "3. ระบบสร้าง request pack ให้ owner ซ่อม mapping/truth ได้",
        "4. ระบบไม่เอาข้อมูลที่เสี่ยงหรือยังไม่ approved ไป claim accuracy",
        "",
        "## Expected Ask",
        "",
        "- ขอ AIS เติม outage/restore truth สำหรับ WebEx high-priority events",
        "- ขอ mapping owner ซ่อม mapping critical sites",
        "- ขอ operations/data owner approve flapping policy ก่อน Phase 2",
        "",
        "## Close",
        "",
        "แนวทางนี้ลดความเสี่ยงจากการทำนายผิด เพราะระบบไม่ได้พยายามส่งทุกเหตุการณ์ แต่จะส่งเฉพาะเมื่อมีหลักฐานพอและผ่าน gate เท่านั้น",
        "",
        "## Source Artifacts",
        "",
        f"- Executive one-pager exists: {summary['executive_one_pager_exists']}",
        f"- Owner handoff exists: {summary['owner_handoff_exists']}",
        "",
    ]
    return "\n".join(lines)


def _handoff_owner_use(name: str) -> str:
    return {
        "executive_one_pager": "Executive status and blocked gate decision.",
        "growth_plan": "Prioritized evidence growth lanes.",
        "mapping_request": "AIS mapping repair work queue.",
        "webex_truth_request": "AIS outage/restore truth request queue.",
        "flapping_policy": "Policy decision for duplicate/flapping alarm rows.",
    }.get(name, "Reference artifact.")


def _green_review_row(row: dict[str, str], high_error_minutes: float) -> dict[str, str]:
    actual = _to_float(row.get("actual_restoration_minutes"))
    p50 = _to_float(row.get("selected_p50"))
    q10 = _to_float(row.get("selected_q10"))
    q90 = _to_float(row.get("selected_q90"))
    error = _to_float(row.get("selected_absolute_error"))
    covered = _to_bool(row.get("selected_covered_q10_q90"))
    issue = "within_band"
    if error is not None and error >= high_error_minutes:
        issue = "high_error"
    if actual is not None and q90 is not None and actual > q90:
        issue = "actual_above_q90_underprediction"
    elif actual is not None and q10 is not None and actual < q10:
        issue = "actual_below_q10_overprediction"
    elif covered is False:
        issue = "interval_miss"
    if row.get("webex_device_interruption_class") == "momentary_le_1m" and actual is not None and actual > 5:
        issue = f"momentary_webex_but_ais_sustained;{issue}"
    return {
        "event_ref": row.get("event_ref", ""),
        "event_time": row.get("event_time", ""),
        "feeder": row.get("feeder", ""),
        "device_id": row.get("device_id", ""),
        "actual_restoration_minutes": row.get("actual_restoration_minutes", ""),
        "selected_p50": row.get("selected_p50", ""),
        "selected_q10": row.get("selected_q10", ""),
        "selected_q90": row.get("selected_q90", ""),
        "prediction_interval_width": row.get("prediction_interval_width", ""),
        "selected_absolute_error": row.get("selected_absolute_error", ""),
        "selected_covered_q10_q90": row.get("selected_covered_q10_q90", ""),
        "webex_device_interruption_class": row.get("webex_device_interruption_class", ""),
        "match_level": row.get("match_level", ""),
        "affected_count": row.get("affected_count", ""),
        "primary_issue": issue,
        "recommended_action": _green_action(issue, p50, actual),
    }


def _green_action(issue: str, p50: float | None, actual: float | None) -> str:
    if "momentary_webex_but_ais_sustained" in issue:
        return "Move similar momentary WebEx states to amber unless live AIS active-state confirms normal behavior."
    if "underprediction" in issue:
        return "Review tail uplift and long-outage risk signals before auto ETR."
    if "overprediction" in issue:
        return "Review short-duration guardrail; keep status-only if q10-q90 cannot cover short truth."
    if issue == "within_band":
        return "Keep in green backtest pool; still shadow-only until gate passes."
    return "Review interval calibration; green subset coverage is below gate."


def _passes_candidate_policy(
    row: dict[str, str],
    max_width: float | None,
    max_q90: float | None,
    require_sustained_webex: bool,
) -> bool:
    if row.get("source_lane") != "ais_truth_matched":
        return False
    if row.get("active_ais_outage_confirmed") != "TRUE":
        return False
    if row.get("match_level") in {"", "feeder", "no_match"}:
        return False
    if (_to_float(row.get("match_confidence")) or 0) < 0.8:
        return False
    if (_to_float(row.get("affected_count")) or 0) <= 0:
        return False
    if not row.get("selected_p50"):
        return False
    width = _to_float(row.get("prediction_interval_width"))
    q90 = _to_float(row.get("selected_q90"))
    if max_width is not None and (width is None or width > max_width):
        return False
    if max_q90 is not None and (q90 is None or q90 > max_q90):
        return False
    if require_sustained_webex and row.get("webex_device_interruption_class") != "sustained_candidate":
        return False
    return True


def _context_priority_row(row: dict[str, str]) -> dict[str, str]:
    score = _to_float(row.get("evidence_score")) or 0
    has_context = bool(row.get("cause_group") or row.get("work_type") or row.get("weather_or_lightning"))
    if score >= 70 and has_context:
        tier = "high"
    elif score >= 50:
        tier = "medium"
    else:
        tier = "low"
    return {
        "priority_rank": "",
        "priority_tier": tier,
        "event_ref": row.get("event_ref", ""),
        "event_time": row.get("event_time", ""),
        "feeder": row.get("feeder", ""),
        "device_id": row.get("device_id", ""),
        "actual_restoration_minutes": row.get("actual_restoration_minutes", ""),
        "selected_absolute_error": row.get("selected_absolute_error", ""),
        "evidence_score": row.get("evidence_score", ""),
        "context_sources": row.get("context_sources", ""),
        "cause_group": row.get("cause_group", ""),
        "work_type": row.get("work_type", ""),
        "weather_or_lightning": row.get("weather_or_lightning", ""),
        "evidence_reasons": row.get("evidence_reasons", ""),
        "recommended_review_question": _context_question(row),
    }


def _context_question(row: dict[str, str]) -> str:
    if row.get("cause_group") or row.get("work_type"):
        return "Can owner approve this cause/work-type context for feature use, without treating it as restoration truth?"
    return "Which reliable source confirms the missing cause/work type for this AIS-truth event?"


def _webex_monitor_row(row: dict[str, str]) -> dict[str, str]:
    match_level = row.get("match_level", "")
    affected = _to_float(row.get("affected_count")) or 0
    q90 = _to_float(row.get("selected_q90")) or 0
    if affected > 0 and match_level not in {"", "feeder", "no_match"}:
        priority = "high"
        reason = "protection match exists but AIS truth has not arrived"
    elif q90 >= 180:
        priority = "medium"
        reason = "potential long event; wait for AIS truth before evaluating"
    else:
        priority = "low"
        reason = "monitor parser/matching only until AIS truth arrives"
    return {
        "event_ref": row.get("event_ref", ""),
        "event_time": row.get("event_time", ""),
        "district": row.get("district", ""),
        "feeder": row.get("feeder", ""),
        "device_id": row.get("device_id", ""),
        "match_level": match_level,
        "match_confidence": row.get("match_confidence", ""),
        "affected_count": row.get("affected_count", ""),
        "webex_device_interruption_class": row.get("webex_device_interruption_class", ""),
        "selected_p50": row.get("selected_p50", ""),
        "selected_q90": row.get("selected_q90", ""),
        "prediction_interval_width": row.get("prediction_interval_width", ""),
        "monitor_priority": priority,
        "monitor_reason": reason,
        "recommended_action": "Do not calculate MAE; link when daily AIS truth arrives.",
    }


def _metric_summary(rows: list[dict[str, str]], error_column: str, coverage_column: str, high_error_minutes: float) -> dict[str, Any]:
    errors = [_to_float(row.get(error_column)) for row in rows]
    errors = [value for value in errors if value is not None]
    return {
        "rows": len(rows),
        "metric_rows": len(errors),
        "mae": mean(errors) if errors else None,
        "coverage": _coverage(rows, coverage_column),
        "high_error_rows": sum(1 for value in errors if value >= high_error_minutes),
    }


def _current_green(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if row.get("eligibility_status") == "green_auto_candidate"]


def _gate_status(rows: int, mae: float | None, coverage: float | None, min_rows: int) -> str:
    if rows < min_rows:
        return "blocked_too_few_green_rows"
    if mae is not None and coverage is not None and mae <= GATE_Q50_MAE_MAX and GATE_COVERAGE_MIN <= coverage <= GATE_COVERAGE_MAX:
        return "shadow_green_subset_passed_requires_human_approval"
    return "blocked_metric_gate_failed"


def _threshold_decision_note(gate: str, rows: int) -> str:
    if gate == "shadow_green_subset_passed_requires_human_approval":
        return "Candidate policy passes backtest metric gate; still requires human approval and live shadow validation."
    if gate == "blocked_too_few_green_rows":
        return "Too few rows for a stable production decision."
    return "Metric gate failed; keep production blocked."


def _best_threshold_variant(rows: list[dict[str, str]]) -> dict[str, str]:
    passing = [row for row in rows if row.get("gate_status") == "shadow_green_subset_passed_requires_human_approval"]
    if passing:
        passing.sort(key=lambda row: (_to_float(row.get("green_rows")) or 0, -(_to_float(row.get("mae")) or 9999)), reverse=True)
        return passing[0]
    candidates = [row for row in rows if _to_float(row.get("mae")) is not None]
    candidates.sort(key=lambda row: (_to_float(row.get("mae")) or 9999, -(_to_float(row.get("green_rows")) or 0)))
    return candidates[0] if candidates else {}


def _priority_sort(value: Any) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(str(value or "").lower(), 0)


def _top_rows(rows: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    rows.sort(key=lambda row: (_to_float(row.get("selected_absolute_error") or row.get("metric_absolute_error")) or 0, row.get("event_time") or ""), reverse=True)
    return rows[:limit]


def _render_green_review(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Green Candidate Error Review",
        "",
        "This report reviews the current green auto-candidate backtest. It does not approve production sends.",
        "",
        f"- Green rows: {summary['rows']}",
        f"- Green q50 MAE: {_fmt(summary['mae'])} minutes",
        f"- Green q10-q90 coverage: {_fmt(summary['coverage'], digits=3)}",
        f"- High-error rows: {summary['high_error_rows']}",
        "",
        "## Issue Counts",
        "",
        *_bullet_counts(summary["issue_counts"]),
        "",
        "## Review Rows",
        "",
        *_table(rows, ("event_ref", "feeder", "device_id", "actual_restoration_minutes", "selected_p50", "selected_q10", "selected_q90", "selected_absolute_error", "primary_issue")),
        "",
        "## Decision",
        "",
        "- Keep production blocked until the green subset passes q50 MAE and coverage gates.",
        "- If green misses cluster around momentary WebEx states, move those states to amber/status-only.",
        "",
    ]
    return "\n".join(lines)


def _render_threshold_calibration(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Eligibility Threshold Calibration",
        "",
        "This shadow-only calibration compares stricter send policies using AIS truth labels. It does not update model artifacts or send production notifications.",
        "",
        f"- Variants tested: {summary['variants']}",
        f"- Best variant: `{summary['best_variant']}`",
        f"- Best gate status: `{summary['best_gate_status']}`",
        f"- Minimum green rows for decision: {summary['min_rows_for_decision']}",
        "",
        "## Variant Results",
        "",
        *_table(rows, THRESHOLD_CALIBRATION_COLUMNS),
        "",
        "## Recommendation",
        "",
        "- Use the strictest passing policy only after it also passes on fresh shadow data.",
        "- If no variant passes, keep automatic p50/range sends blocked and use status-only or human review.",
        "",
    ]
    return "\n".join(lines)


def _render_context_priority(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Approved Context Review Priority",
        "",
        "These rows have the strongest context evidence but remain context-only until a reviewer approves them.",
        "",
        f"- Candidate rows: {summary['rows']}",
        f"- Selected rows: {summary['selected_rows']}",
        "",
        "## Priority Tiers",
        "",
        *_bullet_counts(summary["tier_counts"]),
        "",
        "## Top Feeders",
        "",
        *_bullet_counts(summary["feeder_counts"]),
        "",
        "## Review Queue",
        "",
        *_table(rows, ("priority_rank", "priority_tier", "event_ref", "feeder", "device_id", "actual_restoration_minutes", "evidence_score", "cause_group", "work_type")),
        "",
        "## Guardrail",
        "",
        "- Approved context can become a feature only; AIS outage/restore remains the restoration truth.",
        "",
    ]
    return "\n".join(lines)


def _render_webex_monitor(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# WebEx-Only Monitoring Report",
        "",
        "These WebEx triggers do not have AIS outage/restore truth yet. They are for parser/matching monitoring only.",
        "",
        f"- WebEx-only rows: {summary['rows']}",
        f"- Selected queue rows: {summary['selected_rows']}",
        "",
        "## Priority Counts",
        "",
        *_bullet_counts(summary["priority_counts"]),
        "",
        "## Top Feeders",
        "",
        *_bullet_counts(summary["feeder_counts"]),
        "",
        "## Device State Counts",
        "",
        *_bullet_counts(summary["device_class_counts"]),
        "",
        "## Monitoring Queue",
        "",
        *_table(rows, ("event_ref", "event_time", "feeder", "device_id", "webex_device_interruption_class", "selected_q90", "monitor_priority", "monitor_reason")),
        "",
        "## Guardrail",
        "",
        "- Do not use these rows for MAE, coverage, or model training until AIS truth arrives.",
        "",
    ]
    return "\n".join(lines)


def _render_console_markdown(summary: dict[str, Any], output_html: str | Path) -> str:
    lines = [
        "# Operator Console Mock",
        "",
        f"- HTML mock: `{output_html}`",
        f"- Total shadow rows: {summary['rows']}",
        f"- Green auto candidates: {summary['green']}",
        f"- Amber human review: {summary['amber']}",
        f"- Red blocked: {summary['red']}",
        f"- Monitor only: {summary['monitor']}",
        f"- Production gate: `{summary['gate_status']}`",
        "",
        "This is a static mock built from current shadow outputs. It does not connect to production AIS and does not send notifications.",
        "",
    ]
    return "\n".join(lines)


def _render_console_html(
    summary: dict[str, Any],
    green: list[dict[str, str]],
    amber: list[dict[str, str]],
    monitor: list[dict[str, str]],
    conflicts: list[dict[str, str]],
    approved: list[dict[str, str]],
    max_rows: int,
) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AIS ETR Shadow Ops Console</title>
  <style>
    :root {{
      --ink: #17202a;
      --muted: #5c6670;
      --line: #d8dee6;
      --bg: #f5f7fa;
      --panel: #ffffff;
      --green: #0b7a53;
      --amber: #9a6400;
      --red: #aa2e25;
      --blue: #145da0;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Arial, sans-serif; color: var(--ink); background: var(--bg); }}
    header {{ background: #101820; color: white; padding: 22px 32px; display: flex; justify-content: space-between; gap: 20px; align-items: center; }}
    h1 {{ margin: 0; font-size: 24px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 17px; }}
    .mode {{ border: 1px solid rgba(255,255,255,.45); padding: 8px 12px; border-radius: 6px; font-weight: 700; }}
    main {{ padding: 24px 32px 36px; max-width: 1440px; margin: 0 auto; }}
    .metrics {{ display: grid; grid-template-columns: repeat(5, minmax(140px, 1fr)); gap: 12px; margin-bottom: 22px; }}
    .metric {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; }}
    .metric strong {{ display: block; font-size: 26px; margin-bottom: 4px; }}
    .metric span {{ color: var(--muted); font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
    section {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; min-width: 0; }}
    table {{ width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 12px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 8px 6px; text-align: left; vertical-align: top; overflow-wrap: anywhere; }}
    th {{ color: var(--muted); font-weight: 700; }}
    .pill {{ display: inline-block; padding: 3px 7px; border-radius: 999px; color: white; font-size: 11px; font-weight: 700; }}
    .green {{ background: var(--green); }}
    .amber {{ background: var(--amber); }}
    .red {{ background: var(--red); }}
    .blue {{ background: var(--blue); }}
    .note {{ color: var(--muted); font-size: 13px; margin: 8px 0 0; }}
    @media (max-width: 900px) {{ .metrics, .grid {{ grid-template-columns: 1fr; }} header {{ align-items: flex-start; flex-direction: column; }} }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>AIS ETR Shadow Ops Console</h1>
      <div class="note">AIS truth only for evaluation. WebEx is trigger evidence. PEA PowerBI context is gated.</div>
    </div>
    <div class="mode">No production send</div>
  </header>
  <main>
    <div class="metrics">
      {_metric_html(summary["green"], "Green", "shadow auto candidates", "green")}
      {_metric_html(summary["amber"], "Amber", "human review", "amber")}
      {_metric_html(summary["red"], "Red", "blocked", "red")}
      {_metric_html(summary["monitor"], "Monitor", "WebEx only", "blue")}
      {_metric_html(_fmt(summary["green_mae"]), "Green MAE", "minutes", "blue")}
    </div>
    <section style="margin-bottom:18px">
      <h2>Production Gate</h2>
      <span class="pill red">{escape(str(summary["gate_status"]))}</span>
      <p class="note">Gate target: q50 MAE <= {GATE_Q50_MAE_MAX:g} minutes and q10-q90 coverage {GATE_COVERAGE_MIN:g}-{GATE_COVERAGE_MAX:g}. Current green coverage: {_fmt(summary["green_coverage"], digits=3)}.</p>
    </section>
    <div class="grid">
      {_section_table("Green Backtest", green[:max_rows], ("event_ref", "feeder", "device_id", "selected_p50", "selected_absolute_error", "selected_covered_q10_q90"))}
      {_section_table("Amber Review Queue", amber, ("event_ref", "feeder", "device_id", "stage1_class", "selected_absolute_error", "blocker_reasons"))}
      {_section_table("WebEx Monitor Queue", monitor, ("event_ref", "feeder", "device_id", "webex_device_interruption_class", "selected_q90", "blocker_reasons"))}
      {_section_table("Context Conflicts", conflicts, ("event_ref", "feeder", "device_id", "evidence_status", "evidence_reasons"))}
      {_section_table("Approved Context Candidates", approved, ("event_ref", "feeder", "device_id", "evidence_score", "cause_group", "work_type"))}
    </div>
  </main>
</body>
</html>
"""


def _metric_html(value: Any, label: str, subtitle: str, color: str) -> str:
    return f'<div class="metric"><strong><span class="pill {color}">{escape(str(value))}</span></strong><span>{escape(label)}: {escape(subtitle)}</span></div>'


def _section_table(title: str, rows: list[dict[str, str]], columns: Iterable[str]) -> str:
    header = "".join(f"<th>{escape(column)}</th>" for column in columns)
    if not rows:
        body = f'<tr><td colspan="{len(tuple(columns))}">No rows.</td></tr>'
    else:
        body = "\n".join(
            "<tr>" + "".join(f"<td>{escape(_cell(row.get(column, '')))}</td>" for column in columns) + "</tr>"
            for row in rows
        )
    return f"<section><h2>{escape(title)}</h2><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></section>"


def _table(rows: list[dict[str, str]], columns: Iterable[str]) -> list[str]:
    columns = tuple(columns)
    if not rows:
        return ["No rows."]
    output = ["|" + "|".join(columns) + "|", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows[:50]:
        output.append("|" + "|".join(_cell(row.get(column, "")) for column in columns) + "|")
    return output


def _bullet_counts(counts: dict[str, int]) -> list[str]:
    if not counts:
        return ["- none: 0"]
    return [f"- {key}: {value}" for key, value in counts.items()]


def _coverage(rows: list[dict[str, str]], column: str) -> float | None:
    values = [_to_bool(row.get(column)) for row in rows]
    values = [value for value in values if value is not None]
    return sum(1 for value in values if value) / len(values) if values else None


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: Any) -> int:
    number = _to_float(value)
    return int(number) if number is not None else 0


def _to_bool(value: Any) -> bool | None:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _bool_str(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def _fmt(value: Any, digits: int = 2) -> str:
    number = _to_float(value)
    if number is None:
        return ""
    text = f"{number:.{digits}f}"
    return text.rstrip("0").rstrip(".")


def _cell(value: Any) -> str:
    return str(value or "").replace("|", "/").replace("\n", " ").strip()[:180]


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    source = Path(path)
    if not source.exists():
        return []
    with source.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_section_key_summary(path: str | Path | None) -> dict[str, dict[str, str]]:
    if not path:
        return {}
    output: dict[str, dict[str, str]] = defaultdict(dict)
    for row in _read_csv(path):
        section = row.get("section", "")
        key = row.get("key", "")
        if not section or not key:
            continue
        output[section][key] = row.get("value", "")
    return dict(output)


def _write_csv(path: str | Path, columns: Iterable[str], rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})
