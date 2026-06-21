from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Iterable

from .ais_add_field_truth import import_ais_add_field_truth
from .ais_only_lifecycle_challenger import build_ais_only_lifecycle_challenger
from .ais_only_readiness import build_ais_only_readiness
from .ais_only_remaining_time_challenger import build_ais_only_remaining_time_challenger
from .ais_remaining_truth import match_ais_remaining_truth_to_shadow
from .ais_truth import import_ais_truth
from .autonomous_evidence import build_autonomous_evidence_collector
from .confidence_gate import build_shadow_send_eligibility, build_two_stage_shadow_challenger
from .model_scope import build_shadow_model_comparison
from .notification_time_readiness import build_notification_time_readiness
from .shadow_operations import (
    build_ais_daily_file_qa,
    build_context_review_priority_pack,
    build_current_capability_development_plan,
    build_duplicate_flapping_audit,
    build_eligibility_threshold_calibration,
    build_executive_one_pager,
    build_flapping_policy_draft,
    build_flapping_sensitivity_plan,
    build_green_candidate_error_review,
    build_green_candidate_growth_plan,
    build_green_gate_tracker,
    build_mapping_repair_queue,
    build_mapping_repair_request_pack,
    build_operator_console_qa,
    build_operator_console_mock,
    build_owner_followup_tracker,
    build_owner_handoff_pack,
    build_owner_message_drafts,
    build_owner_response_dry_run_impact,
    build_owner_response_examples,
    build_owner_response_intake,
    build_owner_response_templates,
    build_daily_executive_delta,
    build_executive_pitch_pack,
    build_pitching_narrative_script,
    build_shadow_status_payload_contract,
    build_status_only_payload_templates,
    validate_owner_response_files,
    build_webex_truth_request_pack,
    build_webex_only_monitoring_report,
)
from .truth_quality import GATE_COVERAGE_MAX, GATE_COVERAGE_MIN, GATE_Q50_MAE_MAX


REVIEW_COLUMNS = (
    "event_ref",
    "event_time",
    "feeder",
    "device_id",
    "evidence_status",
    "evidence_score",
    "context_sources",
    "cause_group",
    "work_type",
    "weather_or_lightning",
    "sfsd_match_status",
    "sfsd_match_level",
    "sfsd_evidence_quality",
    "sfsd_cause_status",
    "evidence_reasons",
    "review_decision",
    "review_notes",
)

STEP_COLUMNS = ("step", "status", "detail")
CONTEXT_REVIEW_COLUMNS = (
    "event_ref",
    "event_time",
    "feeder",
    "device_id",
    "actual_restoration_minutes",
    "selected_p50",
    "selected_q10",
    "selected_q90",
    "selected_absolute_error",
    "evidence_status",
    "evidence_score",
    "context_sources",
    "cause_group",
    "work_type",
    "weather_or_lightning",
    "sfsd_match_status",
    "sfsd_match_level",
    "sfsd_evidence_quality",
    "sfsd_cause_status",
    "reportpo_feature_status",
    "reportpo_feature_quality",
    "reportpo_lifecycle_status",
    "reportpo_lifecycle_quality",
    "evidence_reasons",
    "recommended_action",
)
DIFF_HISTORY_COLUMNS = (
    "run_at",
    "total_rows",
    "ais_truth_matched",
    "webex_trigger_no_ais_truth",
    "pea_quarantined",
    "green_auto_candidate",
    "amber_human_review",
    "red_blocked",
    "monitor_only",
    "approved_candidate",
    "pending_insufficient_evidence",
    "context_conflicts",
    "green_q50_mae_minutes",
    "green_q10_q90_coverage",
    "production_gate_status",
    "pending_inbox_files",
)
INBOX_STATUS_COLUMNS = (
    "file_name",
    "file_path",
    "file_size_bytes",
    "modified_at",
    "fingerprint",
    "status",
    "processed_at",
    "source_format",
    "notes",
)
SUPPORTED_AIS_SOURCE_SUFFIXES = {".csv", ".xlsx", ".xls"}


def build_daily_intake_workflow(
    intake_dir: str | Path = "runtime/daily_ais_intake",
    readme_output: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(intake_dir)
    inbox = root / "inbox"
    processed = root / "processed"
    rejected = root / "rejected"
    notes = root / "notes"
    for directory in (root, inbox, processed, rejected, notes):
        directory.mkdir(parents=True, exist_ok=True)
    readme = Path(readme_output) if readme_output else root / "README_TH.md"
    readme.parent.mkdir(parents=True, exist_ok=True)
    readme.write_text(_intake_readme(root), encoding="utf-8-sig")
    return {
        "intake_dir": str(root),
        "inbox": str(inbox),
        "processed": str(processed),
        "rejected": str(rejected),
        "notes": str(notes),
        "readme_output": str(readme),
    }


def build_daily_inbox_status(
    intake_dir: str | Path = "runtime/daily_ais_intake",
    output_csv: str | Path | None = None,
    manifest_csv: str | Path | None = None,
) -> dict[str, Any]:
    build_daily_intake_workflow(intake_dir)
    manifest_path = _manifest_path(intake_dir, manifest_csv)
    manifest_by_fingerprint = _manifest_by_fingerprint(manifest_path)
    rows = []
    for candidate in _scan_inbox(intake_dir):
        fingerprint = _file_fingerprint(candidate)
        manifest = manifest_by_fingerprint.get(fingerprint, {})
        status = manifest.get("status") or "pending"
        rows.append(
            {
                "file_name": candidate.name,
                "file_path": str(candidate),
                "file_size_bytes": str(candidate.stat().st_size),
                "modified_at": _file_modified_at(candidate),
                "fingerprint": fingerprint,
                "status": status,
                "processed_at": manifest.get("processed_at", ""),
                "source_format": manifest.get("source_format", _detect_ais_source_format(candidate, "auto")),
                "notes": manifest.get("notes", ""),
            }
        )
    rows.sort(key=lambda row: (row["status"] != "pending", row["modified_at"], row["file_name"]), reverse=True)
    if output_csv:
        _write_csv(output_csv, INBOX_STATUS_COLUMNS, rows)
    status_counts = Counter(row["status"] for row in rows)
    pending = [row for row in rows if row["status"] == "pending"]
    return {
        "intake_dir": str(intake_dir),
        "manifest_csv": str(manifest_path),
        "output_csv": str(output_csv) if output_csv else None,
        "files": len(rows),
        "pending_files": len(pending),
        "status_counts": dict(status_counts.most_common()),
        "next_pending_source": pending[0]["file_path"] if pending else None,
    }


def discover_daily_ais_source(
    intake_dir: str | Path = "runtime/daily_ais_intake",
    manifest_csv: str | Path | None = None,
    status_output_csv: str | Path | None = None,
) -> dict[str, Any]:
    status = build_daily_inbox_status(intake_dir, status_output_csv, manifest_csv)
    return {
        **status,
        "selected_source": status.get("next_pending_source"),
        "discovery_status": "selected_pending_file" if status.get("next_pending_source") else "no_pending_file",
    }


def build_evidence_review_reports(
    evidence_csv: str | Path,
    approved_output: str | Path,
    conflicts_output: str | Path,
    approved_markdown: str | Path | None = None,
    conflicts_markdown: str | Path | None = None,
) -> dict[str, Any]:
    rows = _read_csv(evidence_csv)
    approved = [
        _review_row(row, "pending_owner_review", "Check source evidence before marking approved.")
        for row in rows
        if row.get("evidence_status") == "approved_candidate"
    ]
    conflicts = [
        _review_row(row, "blocked_until_resolved", "Do not use for model feature or truth until the conflict is resolved.")
        for row in rows
        if row.get("evidence_status") in {"pending_conflict", "rejected_conflict"}
    ]
    _write_csv(approved_output, REVIEW_COLUMNS, approved)
    _write_csv(conflicts_output, REVIEW_COLUMNS, conflicts)
    if approved_markdown:
        Path(approved_markdown).parent.mkdir(parents=True, exist_ok=True)
        Path(approved_markdown).write_text(
            _render_review_markdown("Approved Context Candidate Review", approved, "These rows have the strongest context evidence, but they still require human/source-owner review."),
            encoding="utf-8-sig",
        )
    if conflicts_markdown:
        Path(conflicts_markdown).parent.mkdir(parents=True, exist_ok=True)
        Path(conflicts_markdown).write_text(
            _render_review_markdown("Rejected Context Conflicts", conflicts, "These rows show AIS truth and PEA/PowerBI context disagreeing. Keep them out of training and ETR claims until resolved."),
            encoding="utf-8-sig",
        )
    return {
        "evidence_csv": str(evidence_csv),
        "approved_output": str(approved_output),
        "conflicts_output": str(conflicts_output),
        "approved_markdown": str(approved_markdown) if approved_markdown else None,
        "conflicts_markdown": str(conflicts_markdown) if conflicts_markdown else None,
        "approved_rows": len(approved),
        "conflict_rows": len(conflicts),
        "approved_feeder_counts": dict(Counter(row.get("feeder") or "<blank>" for row in approved).most_common()),
        "conflict_feeder_counts": dict(Counter(row.get("feeder") or "<blank>" for row in conflicts).most_common()),
    }


def build_executive_status_pack(
    eligibility_csv: str | Path,
    evidence_csv: str | Path,
    two_stage_csv: str | Path,
    output: str | Path,
) -> dict[str, Any]:
    eligibility_rows = _read_csv(eligibility_csv)
    evidence_rows = _read_csv(evidence_csv)
    two_stage_rows = _read_csv(two_stage_csv)
    eligibility_counts = Counter(row.get("eligibility_status") or "<blank>" for row in eligibility_rows)
    evidence_counts = Counter(row.get("evidence_status") or "<blank>" for row in evidence_rows)
    source_lane_counts = Counter(row.get("source_lane") or "<blank>" for row in eligibility_rows)
    green_rows = [row for row in eligibility_rows if row.get("eligibility_status") == "green_auto_candidate"]
    green_errors = [_to_float(row.get("selected_absolute_error")) for row in green_rows]
    green_errors = [value for value in green_errors if value is not None]
    green_coverage = _coverage(green_rows, "selected_covered_q10_q90")
    green_mae = mean(green_errors) if green_errors else None
    auto_rows = [row for row in two_stage_rows if _truthy(row.get("public_send_allowed"))]
    gate_status = _gate_status(green_rows, green_mae, green_coverage)
    summary = {
        "eligibility_rows": len(eligibility_rows),
        "ais_truth_matched_rows": source_lane_counts.get("ais_truth_matched", 0),
        "webex_trigger_no_ais_truth_rows": source_lane_counts.get("webex_trigger_no_ais_truth", 0),
        "pea_quarantined_rows": source_lane_counts.get("pea_quarantined", 0),
        "green_auto_candidate_rows": eligibility_counts.get("green_auto_candidate", 0),
        "amber_human_review_rows": eligibility_counts.get("amber_human_review", 0),
        "red_blocked_rows": eligibility_counts.get("red_blocked", 0),
        "monitor_only_rows": eligibility_counts.get("monitor_only", 0),
        "approved_context_candidate_rows": evidence_counts.get("approved_candidate", 0),
        "context_conflict_rows": evidence_counts.get("pending_conflict", 0) + evidence_counts.get("rejected_conflict", 0),
        "pending_insufficient_evidence_rows": evidence_counts.get("pending_insufficient_evidence", 0),
        "two_stage_public_auto_rows": len(auto_rows),
        "green_q50_mae_minutes": _round_or_none(green_mae),
        "green_q10_q90_coverage": _round_or_none(green_coverage, 3),
        "production_gate_status": gate_status,
        "eligibility_counts": dict(eligibility_counts.most_common()),
        "evidence_counts": dict(evidence_counts.most_common()),
        "output": str(output),
    }
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(_render_executive_markdown(summary), encoding="utf-8-sig")
    return summary


def build_context_conflict_deep_dive(
    evidence_csv: str | Path,
    output_markdown: str | Path,
    output_csv: str | Path | None = None,
) -> dict[str, Any]:
    rows = [
        _context_review_row(row)
        for row in _read_csv(evidence_csv)
        if row.get("evidence_status") in {"pending_conflict", "rejected_conflict"}
    ]
    if output_csv:
        _write_csv(output_csv, CONTEXT_REVIEW_COLUMNS, rows)
    summary = _context_summary(rows)
    Path(output_markdown).parent.mkdir(parents=True, exist_ok=True)
    Path(output_markdown).write_text(_render_conflict_deep_dive(summary, rows), encoding="utf-8-sig")
    return {
        **summary,
        "evidence_csv": str(evidence_csv),
        "output_markdown": str(output_markdown),
        "output_csv": str(output_csv) if output_csv else None,
    }


def build_approved_context_candidate_summary(
    evidence_csv: str | Path,
    output_markdown: str | Path,
    output_csv: str | Path | None = None,
) -> dict[str, Any]:
    rows = [
        _context_review_row(row)
        for row in _read_csv(evidence_csv)
        if row.get("evidence_status") == "approved_candidate"
    ]
    if output_csv:
        _write_csv(output_csv, CONTEXT_REVIEW_COLUMNS, rows)
    summary = _context_summary(rows)
    Path(output_markdown).parent.mkdir(parents=True, exist_ok=True)
    Path(output_markdown).write_text(_render_approved_summary(summary, rows), encoding="utf-8-sig")
    return {
        **summary,
        "evidence_csv": str(evidence_csv),
        "output_markdown": str(output_markdown),
        "output_csv": str(output_csv) if output_csv else None,
    }


def build_daily_shadow_diff(
    eligibility_csv: str | Path,
    evidence_csv: str | Path,
    inbox_status_csv: str | Path,
    history_csv: str | Path,
    output_markdown: str | Path,
    *,
    append_history: bool = True,
    run_at: str | None = None,
) -> dict[str, Any]:
    current = _current_diff_snapshot(eligibility_csv, evidence_csv, inbox_status_csv, run_at or datetime.now().isoformat(timespec="seconds"))
    history = _read_csv(history_csv)
    previous = history[-1] if history else {}
    deltas = _diff_snapshot(previous, current)
    if append_history:
        history.append(current)
        _write_csv(history_csv, DIFF_HISTORY_COLUMNS, history)
    Path(output_markdown).parent.mkdir(parents=True, exist_ok=True)
    Path(output_markdown).write_text(_render_daily_diff(current, previous, deltas), encoding="utf-8-sig")
    return {
        "output_markdown": str(output_markdown),
        "history_csv": str(history_csv),
        "has_previous": bool(previous),
        "current": current,
        "deltas": deltas,
    }


def run_synthetic_daily_file_smoke_test(
    output_dir: str | Path = "runtime/synthetic_daily_smoke",
    markdown_output: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(output_dir)
    build_daily_intake_workflow(root)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    source = root / "inbox" / f"synthetic_ais_truth_{stamp}.csv"
    _write_csv(
        source,
        ["site_id", "peano", "outage_start_time", "power_restore_time", "device_id", "feeder"],
        [
            {
                "site_id": "SYNTH_SITE_001",
                "peano": "REDACTED-METER-0000",
                "outage_start_time": "2026-06-19T08:00:00",
                "power_restore_time": "2026-06-19T08:30:00",
                "device_id": "SYNTH_DEVICE_001",
                "feeder": "SYNTH01",
            }
        ],
    )
    manifest = root / "source_manifest.csv"
    status_csv = root / "inbox_status.csv"
    first = discover_daily_ais_source(root, manifest, status_csv)
    selected = first.get("selected_source")
    if selected:
        _append_manifest_row(
            manifest,
            selected,
            status="processed",
            source_format=_detect_ais_source_format(selected, "auto"),
            notes="synthetic smoke test processed marker",
        )
    second = discover_daily_ais_source(root, manifest, status_csv)
    passed = bool(selected) and second.get("selected_source") is None and second.get("pending_files") == 0
    markdown = Path(markdown_output) if markdown_output else root / "synthetic_daily_smoke_test.md"
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(_render_synthetic_smoke(passed, source, first, second), encoding="utf-8-sig")
    return {
        "passed": passed,
        "output_dir": str(root),
        "source": str(source),
        "manifest": str(manifest),
        "status_csv": str(status_csv),
        "markdown_output": str(markdown),
        "first_discovery": first,
        "second_discovery": second,
    }


def build_operator_shadow_review_checklist(
    output_markdown: str | Path,
) -> dict[str, Any]:
    Path(output_markdown).parent.mkdir(parents=True, exist_ok=True)
    Path(output_markdown).write_text(_render_operator_checklist(), encoding="utf-8-sig")
    return {"output_markdown": str(output_markdown)}


def run_daily_shadow_refresh(
    db_path: str | Path,
    *,
    intake_dir: str | Path = "runtime/daily_ais_intake",
    ais_source: str | Path | None = None,
    ais_source_format: str = "auto",
    ais_sheet: str | int | None = "AC MAIN FAIL",
    meter_mapping: str | Path | None = None,
    auto_discover_ais_source: bool = True,
    inbox_manifest_output: str | Path | None = None,
    inbox_status_output: str | Path | None = None,
    ais_truth_output: str | Path = "runtime/ais_truth_latest_candidate.csv",
    ais_truth_review_output: str | Path = "runtime/ais_truth_review_le_5min.csv",
    ais_truth_rejects_output: str | Path = "runtime/ais_truth_rejects_add_field.csv",
    ais_truth_audit_output: str | Path = "runtime/ais_truth_join_audit.csv",
    ais_truth_report_output: str | Path = "runtime/analysis/ais_add_field_truth_import_report.md",
    generic_ais_truth_output: str | Path = "runtime/ais_truth_latest.csv",
    generic_ais_truth_rejects_output: str | Path = "runtime/ais_truth_rejects.csv",
    remaining_mapping_output: str | Path = "runtime/shadow_truth_mapping_ais_remaining.csv",
    remaining_audit_output: str | Path = "runtime/ais_remaining_truth_match_audit.csv",
    current_model: str | Path = "runtime/model_quantiles.json",
    challenger_model: str | Path = "runtime/model_challenger_expanded_quantiles.json",
    shadow_comparison_output: str | Path = "runtime/shadow_model_comparison_ais_remaining.csv",
    shadow_comparison_markdown: str | Path = "runtime/shadow_model_comparison_ais_remaining.md",
    notification_time_output: str | Path = "runtime/notification_time_readiness.csv",
    notification_time_markdown: str | Path = "runtime/notification_time_readiness.md",
    notification_time_segments: str | Path = "runtime/notification_time_error_segments.csv",
    device_state_csv: str | Path = "runtime/shadow_webex_device_state_diagnostic.csv",
    lifecycle_audit_csv: str | Path = "runtime/reportpo_lifecycle_join_audit.csv",
    governance_status_csv: str | Path = "runtime/truth_governance_review_status.csv",
    reportpo_feature_audit_csv: str | Path = "runtime/reportpo_feature_join_audit.csv",
    sfsd_evidence_csv: str | Path = "runtime/sfsd_long_outage_evidence.csv",
    sfsd_decision_csv: str | Path = "runtime/sfsd_gap_decision_pack.csv",
    ais_only_readiness_output: str | Path = "runtime/ais_only_readiness.csv",
    ais_only_readiness_markdown: str | Path = "runtime/ais_only_readiness.md",
    pea_quarantine_output: str | Path = "runtime/pea_quarantine_audit.csv",
    remaining_challenger_output: str | Path = "runtime/ais_only_remaining_time_challenger.csv",
    remaining_challenger_markdown: str | Path = "runtime/ais_only_remaining_time_challenger.md",
    remaining_challenger_segments: str | Path = "runtime/ais_only_remaining_time_segments.csv",
    lifecycle_review_csv: str | Path = "runtime/ops_lifecycle_review_top_misses.csv",
    lifecycle_challenger_output: str | Path = "runtime/ais_only_lifecycle_challenger.csv",
    lifecycle_challenger_markdown: str | Path = "runtime/ais_only_lifecycle_challenger.md",
    lifecycle_feature_audit_output: str | Path = "runtime/ais_only_lifecycle_feature_audit.csv",
    lifecycle_valid_output: str | Path = "runtime/ops_lifecycle_review_validated.csv",
    lifecycle_rejects_output: str | Path = "runtime/ops_lifecycle_review_rejects.csv",
    lifecycle_segments_output: str | Path = "runtime/ais_only_lifecycle_segments.csv",
    eligibility_output: str | Path = "runtime/shadow_send_eligibility.csv",
    eligibility_markdown: str | Path = "runtime/shadow_send_eligibility.md",
    eligibility_segments: str | Path = "runtime/shadow_send_eligibility_segments.csv",
    production_gate_output: str | Path = "runtime/production_readiness_gate.md",
    evidence_output: str | Path = "runtime/autonomous_evidence_collector.csv",
    evidence_markdown: str | Path = "runtime/autonomous_evidence_collector.md",
    autofill_output: str | Path = "runtime/forward_capture_autofill_candidates.csv",
    approved_review_output: str | Path = "runtime/approved_context_candidates_review.csv",
    approved_review_markdown: str | Path = "runtime/approved_context_candidates_review.md",
    conflicts_output: str | Path = "runtime/rejected_context_conflicts.csv",
    conflicts_markdown: str | Path = "runtime/rejected_context_conflicts.md",
    conflict_deep_dive_output: str | Path = "runtime/context_conflict_deep_dive.csv",
    conflict_deep_dive_markdown: str | Path = "runtime/context_conflict_deep_dive.md",
    approved_summary_output: str | Path = "runtime/approved_context_candidate_summary.csv",
    approved_summary_markdown: str | Path = "runtime/approved_context_candidate_summary.md",
    green_review_output: str | Path = "runtime/green_candidate_error_review.csv",
    green_review_markdown: str | Path = "runtime/green_candidate_error_review.md",
    threshold_calibration_output: str | Path = "runtime/eligibility_threshold_calibration.csv",
    threshold_calibration_markdown: str | Path = "runtime/eligibility_threshold_calibration.md",
    green_gate_tracker_output: str | Path = "runtime/green_gate_tracker.csv",
    green_gate_tracker_markdown: str | Path = "runtime/green_gate_tracker.md",
    ais_daily_qa_output: str | Path = "runtime/ais_daily_file_qa.csv",
    ais_daily_qa_markdown: str | Path = "runtime/ais_daily_file_qa.md",
    mapping_repair_output: str | Path = "runtime/ais_mapping_repair_queue.csv",
    mapping_repair_private_output: str | Path = "runtime/private/ais_mapping_repair_queue_private.csv",
    mapping_repair_markdown: str | Path = "runtime/ais_mapping_repair_queue.md",
    mapping_request_output: str | Path = "runtime/ais_mapping_repair_request.csv",
    mapping_request_private_output: str | Path = "runtime/private/ais_mapping_repair_request_owner.csv",
    mapping_request_markdown: str | Path = "runtime/ais_mapping_repair_request_pack.md",
    duplicate_flapping_output: str | Path = "runtime/duplicate_flapping_audit.csv",
    duplicate_flapping_markdown: str | Path = "runtime/duplicate_flapping_audit.md",
    flapping_policy_output: str | Path = "runtime/duplicate_flapping_policy.csv",
    flapping_policy_markdown: str | Path = "runtime/duplicate_flapping_policy.md",
    flapping_sensitivity_output: str | Path = "runtime/flapping_sensitivity_plan.csv",
    flapping_sensitivity_markdown: str | Path = "runtime/flapping_sensitivity_plan.md",
    green_growth_output: str | Path = "runtime/green_candidate_growth_plan.csv",
    green_growth_markdown: str | Path = "runtime/green_candidate_growth_plan.md",
    status_payload_output: str | Path = "runtime/status_only_payload_templates.jsonl",
    status_payload_markdown: str | Path = "runtime/status_only_payload_templates.md",
    status_payload_contract: str | Path = "runtime/shadow_status_payload_contract.md",
    context_priority_output: str | Path = "runtime/context_review_priority.csv",
    context_priority_markdown: str | Path = "runtime/context_review_priority.md",
    webex_monitor_output: str | Path = "runtime/webex_only_monitoring.csv",
    webex_monitor_markdown: str | Path = "runtime/webex_only_monitoring.md",
    webex_truth_request_output: str | Path = "runtime/webex_ais_truth_request.csv",
    webex_truth_request_markdown: str | Path = "runtime/webex_ais_truth_request_pack.md",
    operator_console_output: str | Path = "runtime/operator_console_mock.html",
    operator_console_markdown: str | Path = "runtime/operator_console_mock.md",
    operator_console_qa_markdown: str | Path = "runtime/operator_console_qa.md",
    daily_diff_output: str | Path = "runtime/daily_shadow_diff.md",
    daily_diff_history: str | Path = "runtime/daily_shadow_status_history.csv",
    operator_checklist_output: str | Path = "runtime/operator_shadow_review_checklist.md",
    two_stage_output: str | Path = "runtime/two_stage_shadow_challenger.csv",
    two_stage_markdown: str | Path = "runtime/two_stage_shadow_challenger.md",
    two_stage_segments: str | Path = "runtime/two_stage_shadow_segments.csv",
    executive_output: str | Path = "runtime/executive_shadow_status_pack.md",
    executive_one_pager_output: str | Path = "runtime/executive_one_pager.md",
    owner_handoff_output: str | Path = "runtime/owner_handoff_pack.md",
    owner_message_drafts_output: str | Path = "runtime/owner_message_drafts_th.md",
    owner_followup_tracker_output: str | Path = "runtime/owner_followup_tracker.csv",
    owner_followup_tracker_markdown: str | Path = "runtime/owner_followup_tracker.md",
    owner_mapping_response_template: str | Path = "runtime/owner_response_templates/mapping_repair_response_template.csv",
    owner_webex_response_template: str | Path = "runtime/owner_response_templates/webex_truth_response_template.csv",
    owner_response_templates_markdown: str | Path = "runtime/owner_response_templates.md",
    owner_mapping_response_input: str | Path = "runtime/owner_responses/mapping_repair_response.csv",
    owner_webex_response_input: str | Path = "runtime/owner_responses/webex_truth_response.csv",
    owner_response_validation_output: str | Path = "runtime/owner_response_validation.csv",
    owner_response_validation_markdown: str | Path = "runtime/owner_response_validation.md",
    owner_response_intake_output: str | Path = "runtime/owner_response_intake.csv",
    owner_response_intake_markdown: str | Path = "runtime/owner_response_intake.md",
    owner_response_dry_run_output: str | Path = "runtime/owner_response_dry_run_impact.csv",
    owner_response_dry_run_markdown: str | Path = "runtime/owner_response_dry_run_impact.md",
    owner_response_examples_dir: str | Path = "runtime/owner_response_examples",
    owner_response_examples_markdown: str | Path = "runtime/owner_response_examples.md",
    daily_executive_delta_output: str | Path = "runtime/daily_executive_delta.csv",
    daily_executive_delta_markdown: str | Path = "runtime/daily_executive_delta.md",
    executive_pitch_pack_output: str | Path = "runtime/executive_pitch_pack.md",
    ais_updated_summary_output: str | Path = "runtime/analysis/ais_updated_truth_review_summary.csv",
    ais_updated_mapping_request_output: str | Path = "runtime/analysis/ais_updated_mapping_repair_request.csv",
    ais_updated_mapping_response_template: str | Path = "runtime/private/ais_updated_mapping_response_template_simple.csv",
    ais_updated_mapping_private_lookup: str | Path = "runtime/private/ais_updated_mapping_repair_request_owner.csv",
    ais_updated_mapping_owner_message: str | Path = "runtime/analysis/ais_updated_mapping_question_simple_th.md",
    current_capability_plan_output: str | Path = "runtime/current_capability_development_plan.csv",
    current_capability_plan_markdown: str | Path = "runtime/current_capability_development_plan.md",
    pitching_narrative_output: str | Path = "runtime/pitching_narrative_script.md",
    steps_output: str | Path = "runtime/daily_shadow_refresh_steps.csv",
    continue_on_error: bool = True,
) -> dict[str, Any]:
    steps: list[dict[str, str]] = []

    def step(name: str, func: Callable[[], Any]) -> Any:
        try:
            result = func()
            detail = _compact_detail(result)
            steps.append({"step": name, "status": "ok", "detail": detail})
            return result
        except Exception as exc:
            steps.append({"step": name, "status": "error", "detail": f"{type(exc).__name__}: {exc}"})
            if not continue_on_error:
                raise
            return None

    intake_result = step("daily_intake_workflow", lambda: build_daily_intake_workflow(intake_dir))
    manifest_path = _manifest_path(intake_dir, inbox_manifest_output)
    status_path = Path(inbox_status_output) if inbox_status_output else Path(intake_dir) / "inbox_status.csv"
    discovery_result = None
    if ais_source is None and auto_discover_ais_source:
        discovery_result = step(
            "ais_inbox_discovery",
            lambda: discover_daily_ais_source(intake_dir, manifest_path, status_path),
        )
        selected = (discovery_result or {}).get("selected_source")
        if selected:
            ais_source = selected

    import_result = None
    active_truth_path: str | Path = ais_truth_output
    if ais_source:
        detected = _detect_ais_source_format(ais_source, ais_source_format)
        if detected == "add_field":
            import_result = step(
                "ais_add_field_truth_import",
                lambda: import_ais_add_field_truth(
                    ais_source,
                    meter_mapping,
                    ais_truth_output,
                    ais_truth_review_output,
                    ais_truth_rejects_output,
                    ais_truth_audit_output,
                    ais_truth_report_output,
                    sheet=ais_sheet,
                ),
            )
            active_truth_path = ais_truth_output
        else:
            import_result = step(
                "ais_truth_import",
                lambda: import_ais_truth(
                    ais_source,
                    generic_ais_truth_output,
                    generic_ais_truth_rejects_output,
                    sheet=ais_sheet,
                ),
            )
            active_truth_path = generic_ais_truth_output
        if import_result is not None:
            _append_manifest_row(
                manifest_path,
                ais_source,
                status="processed",
                source_format=detected,
                notes=_compact_detail(import_result),
            )
    else:
        detail = "no pending AIS file discovered" if auto_discover_ais_source else "no --ais-source provided"
        steps.append({"step": "ais_truth_import", "status": "skipped", "detail": detail})

    if _exists(active_truth_path):
        step(
            "ais_remaining_truth_match_shadow",
            lambda: match_ais_remaining_truth_to_shadow(
                db_path,
                active_truth_path,
                remaining_mapping_output,
                remaining_audit_output,
                overwrite=True,
            ),
        )
    else:
        steps.append({"step": "ais_remaining_truth_match_shadow", "status": "skipped", "detail": f"missing truth file: {active_truth_path}"})

    if _exists(current_model) and _exists(challenger_model) and _exists(remaining_mapping_output):
        step(
            "shadow_model_comparison",
            lambda: build_shadow_model_comparison(
                db_path,
                current_model,
                challenger_model,
                shadow_comparison_output,
                shadow_comparison_markdown,
                remaining_mapping_output,
            ),
        )
    else:
        steps.append({"step": "shadow_model_comparison", "status": "skipped", "detail": "missing model or truth mapping input"})

    if _exists(shadow_comparison_output) and _exists(remaining_audit_output):
        step(
            "notification_time_readiness",
            lambda: build_notification_time_readiness(
                db_path,
                shadow_comparison_output,
                remaining_audit_output,
                notification_time_output,
                notification_time_markdown,
                device_state_csv=device_state_csv if _exists(device_state_csv) else None,
                lifecycle_audit_csv=lifecycle_audit_csv if _exists(lifecycle_audit_csv) else None,
                segments_output=notification_time_segments,
            ),
        )
    else:
        steps.append({"step": "notification_time_readiness", "status": "skipped", "detail": "missing shadow comparison or AIS remaining audit"})

    if _exists(shadow_comparison_output):
        step(
            "ais_only_readiness",
            lambda: build_ais_only_readiness(
                shadow_comparison_output,
                governance_status_csv,
                ais_only_readiness_output,
                ais_only_readiness_markdown,
                pea_quarantine_output,
                reportpo_feature_audit_csv=reportpo_feature_audit_csv,
                reportpo_lifecycle_audit_csv=lifecycle_audit_csv,
                sfsd_evidence_csv=sfsd_evidence_csv,
                sfsd_decision_csv=sfsd_decision_csv,
            ),
        )
    else:
        steps.append({"step": "ais_only_readiness", "status": "skipped", "detail": "missing shadow comparison"})

    if _exists(ais_only_readiness_output) and _exists(notification_time_output) and _exists(active_truth_path):
        step(
            "ais_only_remaining_time_challenger",
            lambda: build_ais_only_remaining_time_challenger(
                db_path,
                ais_only_readiness_output,
                notification_time_output,
                active_truth_path,
                remaining_challenger_output,
                remaining_challenger_markdown,
                remaining_challenger_segments,
            ),
        )
    else:
        steps.append({"step": "ais_only_remaining_time_challenger", "status": "skipped", "detail": "missing readiness, notification, or AIS truth input"})

    if _exists(ais_only_readiness_output) and _exists(remaining_challenger_output):
        step(
            "ais_only_lifecycle_challenger",
            lambda: build_ais_only_lifecycle_challenger(
                ais_only_readiness_output,
                remaining_challenger_output,
                lifecycle_review_csv,
                lifecycle_challenger_output,
                lifecycle_challenger_markdown,
                lifecycle_feature_audit_output,
                lifecycle_valid_output,
                lifecycle_rejects_output,
                lifecycle_segments_output,
            ),
        )
    else:
        steps.append({"step": "ais_only_lifecycle_challenger", "status": "skipped", "detail": "missing readiness or remaining challenger"})

    if _exists(ais_only_readiness_output) and _exists(notification_time_output):
        step(
            "shadow_send_eligibility",
            lambda: build_shadow_send_eligibility(
                ais_only_readiness_output,
                notification_time_output,
                eligibility_output,
                eligibility_markdown,
                production_gate_output,
                lifecycle_challenger_csv=lifecycle_challenger_output if _exists(lifecycle_challenger_output) else None,
                remaining_time_csv=remaining_challenger_output if _exists(remaining_challenger_output) else None,
                segments_output=eligibility_segments,
            ),
        )
    else:
        steps.append({"step": "shadow_send_eligibility", "status": "skipped", "detail": "missing AIS-only readiness or notification readiness"})

    if _exists(eligibility_output):
        evidence_result = step(
            "autonomous_evidence_collector",
            lambda: build_autonomous_evidence_collector(
                eligibility_output,
                reportpo_feature_audit_csv,
                lifecycle_audit_csv,
                sfsd_evidence_csv,
                evidence_output,
                evidence_markdown,
                autofill_output,
            ),
        )
    else:
        evidence_result = None
        steps.append({"step": "autonomous_evidence_collector", "status": "skipped", "detail": "missing shadow eligibility"})

    if _exists(evidence_output):
        review_result = step(
            "evidence_review_reports",
            lambda: build_evidence_review_reports(
                evidence_output,
                approved_review_output,
                conflicts_output,
                approved_review_markdown,
                conflicts_markdown,
            ),
        )
    else:
        review_result = None
        steps.append({"step": "evidence_review_reports", "status": "skipped", "detail": "missing autonomous evidence output"})

    if _exists(eligibility_output):
        step(
            "green_candidate_error_review",
            lambda: build_green_candidate_error_review(
                eligibility_output,
                green_review_output,
                green_review_markdown,
            ),
        )
        step(
            "eligibility_threshold_calibration",
            lambda: build_eligibility_threshold_calibration(
                eligibility_output,
                threshold_calibration_output,
                threshold_calibration_markdown,
            ),
        )
        step(
            "green_gate_tracker",
            lambda: build_green_gate_tracker(
                eligibility_output,
                threshold_calibration_output,
                green_gate_tracker_output,
                green_gate_tracker_markdown,
            ),
        )
        step(
            "status_only_payload_templates",
            lambda: build_status_only_payload_templates(
                eligibility_output,
                status_payload_output,
                status_payload_markdown,
            ),
        )
        step(
            "shadow_status_payload_contract",
            lambda: build_shadow_status_payload_contract(
                status_payload_output,
                eligibility_output,
                status_payload_contract,
            ),
        )
        step(
            "webex_only_monitoring",
            lambda: build_webex_only_monitoring_report(
                eligibility_output,
                webex_monitor_output,
                webex_monitor_markdown,
            ),
        )
        step(
            "webex_truth_request_pack",
            lambda: build_webex_truth_request_pack(
                webex_monitor_output,
                webex_truth_request_output,
                webex_truth_request_markdown,
            ),
        )
    else:
        steps.append({"step": "green_candidate_error_review", "status": "skipped", "detail": "missing shadow eligibility"})
        steps.append({"step": "eligibility_threshold_calibration", "status": "skipped", "detail": "missing shadow eligibility"})
        steps.append({"step": "green_gate_tracker", "status": "skipped", "detail": "missing shadow eligibility"})
        steps.append({"step": "status_only_payload_templates", "status": "skipped", "detail": "missing shadow eligibility"})
        steps.append({"step": "shadow_status_payload_contract", "status": "skipped", "detail": "missing shadow eligibility"})
        steps.append({"step": "webex_only_monitoring", "status": "skipped", "detail": "missing shadow eligibility"})
        steps.append({"step": "webex_truth_request_pack", "status": "skipped", "detail": "missing WebEx monitor output"})

    if _exists(ais_truth_output) or _exists(ais_truth_review_output) or _exists(ais_truth_rejects_output):
        step(
            "ais_daily_file_qa",
            lambda: build_ais_daily_file_qa(
                ais_truth_output,
                ais_truth_review_output,
                ais_truth_rejects_output,
                ais_truth_audit_output,
                ais_daily_qa_output,
                ais_daily_qa_markdown,
            ),
        )
        step(
            "mapping_repair_queue",
            lambda: build_mapping_repair_queue(
                ais_truth_audit_output,
                ais_truth_output,
                ais_truth_rejects_output,
                mapping_repair_output,
                mapping_repair_markdown,
                private_output_csv=mapping_repair_private_output,
            ),
        )
        step(
            "duplicate_flapping_audit",
            lambda: build_duplicate_flapping_audit(
                ais_truth_output,
                ais_truth_review_output,
                duplicate_flapping_output,
                duplicate_flapping_markdown,
            ),
        )
        step(
            "mapping_repair_request_pack",
            lambda: build_mapping_repair_request_pack(
                mapping_repair_output,
                mapping_repair_private_output,
                mapping_request_output,
                mapping_request_private_output,
                mapping_request_markdown,
            ),
        )
        step(
            "flapping_policy_draft",
            lambda: build_flapping_policy_draft(
                duplicate_flapping_output,
                flapping_policy_output,
                flapping_policy_markdown,
            ),
        )
    else:
        steps.append({"step": "ais_daily_file_qa", "status": "skipped", "detail": "missing AIS truth/review/reject outputs"})
        steps.append({"step": "mapping_repair_queue", "status": "skipped", "detail": "missing AIS truth/review/reject outputs"})
        steps.append({"step": "duplicate_flapping_audit", "status": "skipped", "detail": "missing AIS truth/review/reject outputs"})
        steps.append({"step": "mapping_repair_request_pack", "status": "skipped", "detail": "missing mapping repair queue outputs"})
        steps.append({"step": "flapping_policy_draft", "status": "skipped", "detail": "missing duplicate/flapping audit output"})

    if _exists(evidence_output):
        step(
            "context_conflict_deep_dive",
            lambda: build_context_conflict_deep_dive(
                evidence_output,
                conflict_deep_dive_markdown,
                conflict_deep_dive_output,
            ),
        )
        step(
            "approved_context_candidate_summary",
            lambda: build_approved_context_candidate_summary(
                evidence_output,
                approved_summary_markdown,
                approved_summary_output,
            ),
        )
        step(
            "context_review_priority",
            lambda: build_context_review_priority_pack(
                evidence_output,
                context_priority_output,
                context_priority_markdown,
            ),
        )
    else:
        steps.append({"step": "context_conflict_deep_dive", "status": "skipped", "detail": "missing autonomous evidence output"})
        steps.append({"step": "approved_context_candidate_summary", "status": "skipped", "detail": "missing autonomous evidence output"})
        steps.append({"step": "context_review_priority", "status": "skipped", "detail": "missing autonomous evidence output"})

    if _exists(eligibility_output) and _exists(green_gate_tracker_output) and _exists(webex_monitor_output):
        step(
            "green_candidate_growth_plan",
            lambda: build_green_candidate_growth_plan(
                eligibility_output,
                green_gate_tracker_output,
                webex_monitor_output,
                mapping_repair_output,
                context_priority_output,
                green_growth_output,
                green_growth_markdown,
            ),
        )
    else:
        steps.append({"step": "green_candidate_growth_plan", "status": "skipped", "detail": "missing eligibility, gate tracker, or WebEx monitor output"})

    if _exists(eligibility_output) and _exists(lifecycle_challenger_output):
        step(
            "two_stage_shadow_challenger",
            lambda: build_two_stage_shadow_challenger(
                eligibility_output,
                lifecycle_challenger_output,
                two_stage_output,
                two_stage_markdown,
                two_stage_segments,
                forward_capture_validated_csv=lifecycle_valid_output if _exists(lifecycle_valid_output) else None,
            ),
        )
    else:
        steps.append({"step": "two_stage_shadow_challenger", "status": "skipped", "detail": "missing eligibility or lifecycle challenger"})

    if _exists(eligibility_output) and _exists(evidence_output) and _exists(two_stage_output):
        executive_result = step(
            "executive_status_pack",
            lambda: build_executive_status_pack(eligibility_output, evidence_output, two_stage_output, executive_output),
        )
    else:
        executive_result = None
        steps.append({"step": "executive_status_pack", "status": "skipped", "detail": "missing eligibility, evidence, or two-stage output"})

    if _exists(eligibility_output) and _exists(green_gate_tracker_output) and _exists(ais_daily_qa_output) and _exists(green_growth_output):
        step(
            "executive_one_pager",
            lambda: build_executive_one_pager(
                eligibility_output,
                green_gate_tracker_output,
                ais_daily_qa_output,
                green_growth_output,
                executive_one_pager_output,
            ),
        )
    else:
        steps.append({"step": "executive_one_pager", "status": "skipped", "detail": "missing eligibility, gate tracker, AIS QA, or growth plan output"})

    if _exists(executive_one_pager_output) and _exists(green_growth_markdown):
        step(
            "owner_handoff_pack",
            lambda: build_owner_handoff_pack(
                executive_one_pager_output,
                green_growth_markdown,
                mapping_request_markdown,
                webex_truth_request_markdown,
                flapping_policy_markdown,
                owner_handoff_output,
            ),
        )
    else:
        steps.append({"step": "owner_handoff_pack", "status": "skipped", "detail": "missing executive one-pager or growth plan"})

    if _exists(owner_handoff_output):
        step(
            "owner_message_drafts",
            lambda: build_owner_message_drafts(
                owner_handoff_output,
                mapping_request_markdown,
                webex_truth_request_markdown,
                flapping_policy_markdown,
                owner_message_drafts_output,
            ),
        )
    else:
        steps.append({"step": "owner_message_drafts", "status": "skipped", "detail": "missing owner handoff pack"})

    if _exists(mapping_request_output) and _exists(webex_truth_request_output) and _exists(flapping_policy_output):
        step(
            "owner_followup_tracker",
            lambda: build_owner_followup_tracker(
                mapping_request_output,
                webex_truth_request_output,
                flapping_policy_output,
                owner_followup_tracker_output,
                owner_followup_tracker_markdown,
            ),
        )
        step(
            "owner_response_templates",
            lambda: build_owner_response_templates(
                mapping_request_output,
                webex_truth_request_output,
                owner_mapping_response_template,
                owner_webex_response_template,
                owner_response_templates_markdown,
            ),
        )
    else:
        steps.append({"step": "owner_followup_tracker", "status": "skipped", "detail": "missing request pack outputs"})
        steps.append({"step": "owner_response_templates", "status": "skipped", "detail": "missing request pack outputs"})

    step(
        "owner_response_validation",
        lambda: validate_owner_response_files(
            owner_mapping_response_input,
            owner_webex_response_input,
            owner_response_validation_output,
            owner_response_validation_markdown,
        ),
    )
    step(
        "owner_response_intake",
        lambda: build_owner_response_intake(
            owner_response_validation_output,
            owner_response_intake_output,
            owner_response_intake_markdown,
        ),
    )
    if _exists(eligibility_output) and _exists(green_gate_tracker_output) and _exists(owner_response_intake_output):
        step(
            "owner_response_dry_run_impact",
            lambda: build_owner_response_dry_run_impact(
                eligibility_output,
                green_gate_tracker_output,
                owner_response_intake_output,
                owner_response_dry_run_output,
                owner_response_dry_run_markdown,
            ),
        )
    else:
        steps.append({"step": "owner_response_dry_run_impact", "status": "skipped", "detail": "missing eligibility, gate tracker, or owner response intake"})
    step(
        "owner_response_examples",
        lambda: build_owner_response_examples(
            owner_response_examples_dir,
            owner_response_examples_markdown,
        ),
    )

    if _exists(duplicate_flapping_output):
        step(
            "flapping_sensitivity_plan",
            lambda: build_flapping_sensitivity_plan(
                duplicate_flapping_output,
                flapping_sensitivity_output,
                flapping_sensitivity_markdown,
            ),
        )
    else:
        steps.append({"step": "flapping_sensitivity_plan", "status": "skipped", "detail": "missing duplicate/flapping audit output"})

    if _exists(executive_one_pager_output) and _exists(owner_handoff_output):
        step(
            "pitching_narrative_script",
            lambda: build_pitching_narrative_script(
                executive_one_pager_output,
                owner_handoff_output,
                pitching_narrative_output,
            ),
        )
    else:
        steps.append({"step": "pitching_narrative_script", "status": "skipped", "detail": "missing executive one-pager or owner handoff"})

    if _exists(eligibility_output) and _exists(evidence_output):
        step(
            "daily_shadow_diff",
            lambda: build_daily_shadow_diff(
                eligibility_output,
                evidence_output,
                status_path,
                daily_diff_history,
                daily_diff_output,
            ),
        )
    else:
        steps.append({"step": "daily_shadow_diff", "status": "skipped", "detail": "missing eligibility or evidence output"})

    if _exists(daily_diff_history) and _exists(green_gate_tracker_output) and _exists(owner_followup_tracker_output) and _exists(owner_response_validation_output):
        step(
            "daily_executive_delta",
            lambda: build_daily_executive_delta(
                daily_diff_history,
                green_gate_tracker_output,
                owner_followup_tracker_output,
                owner_response_validation_output,
                daily_executive_delta_output,
                daily_executive_delta_markdown,
            ),
        )
    else:
        steps.append({"step": "daily_executive_delta", "status": "skipped", "detail": "missing daily diff history, gate tracker, owner tracker, or response validation"})

    if _exists(executive_one_pager_output) and _exists(daily_executive_delta_markdown) and _exists(owner_handoff_output) and _exists(owner_followup_tracker_output) and _exists(owner_response_validation_output) and _exists(owner_response_dry_run_output):
        step(
            "executive_pitch_pack",
            lambda: build_executive_pitch_pack(
                executive_one_pager_output,
                daily_executive_delta_markdown,
                owner_handoff_output,
                owner_followup_tracker_output,
                owner_response_validation_output,
                owner_response_dry_run_output,
                executive_pitch_pack_output,
            ),
        )
    else:
        steps.append({"step": "executive_pitch_pack", "status": "skipped", "detail": "missing executive one-pager, daily delta, owner handoff, owner tracker, validation, or dry-run impact"})

    step(
        "operator_shadow_review_checklist",
        lambda: build_operator_shadow_review_checklist(operator_checklist_output),
    )
    if _exists(eligibility_output) and _exists(evidence_output):
        step(
            "operator_console_mock",
            lambda: build_operator_console_mock(
                eligibility_output,
                evidence_output,
                operator_console_output,
                operator_console_markdown,
            ),
        )
        step(
            "operator_console_qa",
            lambda: build_operator_console_qa(operator_console_output, operator_console_qa_markdown),
        )
    else:
        steps.append({"step": "operator_console_mock", "status": "skipped", "detail": "missing eligibility or evidence output"})
        steps.append({"step": "operator_console_qa", "status": "skipped", "detail": "missing operator console output"})

    _write_csv(steps_output, STEP_COLUMNS, steps)
    if _exists(green_gate_tracker_output) and _exists(steps_output) and _exists(owner_followup_tracker_output) and _exists(owner_response_intake_output) and _exists(owner_response_dry_run_output):
        step(
            "current_capability_development_plan",
            lambda: build_current_capability_development_plan(
                green_gate_tracker_output,
                steps_output,
                owner_followup_tracker_output,
                owner_response_intake_output,
                owner_response_dry_run_output,
                current_capability_plan_output,
                current_capability_plan_markdown,
                ais_updated_summary_output,
                ais_updated_mapping_request_output,
                ais_updated_mapping_response_template,
                ais_updated_mapping_private_lookup,
                ais_updated_mapping_owner_message,
            ),
        )
    else:
        steps.append({"step": "current_capability_development_plan", "status": "skipped", "detail": "missing gate tracker, step log, owner tracker, intake, or dry-run impact"})

    _write_csv(steps_output, STEP_COLUMNS, steps)
    status_counts = Counter(row["status"] for row in steps)
    return {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "steps_output": str(steps_output),
        "step_status_counts": dict(status_counts.most_common()),
        "intake": intake_result,
        "inbox_discovery": discovery_result,
        "ais_import": import_result,
        "evidence": evidence_result,
        "review": review_result,
        "executive": executive_result,
        "key_outputs": {
            "intake_readme": str((Path(intake_dir) / "README_TH.md")),
            "autonomous_evidence": str(evidence_output),
            "autofill_candidates": str(autofill_output),
            "approved_review": str(approved_review_output),
            "conflicts": str(conflicts_output),
            "conflict_deep_dive": str(conflict_deep_dive_markdown),
            "approved_summary": str(approved_summary_markdown),
            "green_review": str(green_review_markdown),
            "threshold_calibration": str(threshold_calibration_markdown),
            "green_gate_tracker": str(green_gate_tracker_markdown),
            "ais_daily_file_qa": str(ais_daily_qa_markdown),
            "mapping_repair_queue": str(mapping_repair_markdown),
            "mapping_repair_private": str(mapping_repair_private_output),
            "mapping_repair_request": str(mapping_request_markdown),
            "mapping_repair_request_private": str(mapping_request_private_output),
            "duplicate_flapping_audit": str(duplicate_flapping_markdown),
            "flapping_policy": str(flapping_policy_markdown),
            "flapping_sensitivity_plan": str(flapping_sensitivity_markdown),
            "green_candidate_growth_plan": str(green_growth_markdown),
            "status_only_payload_templates": str(status_payload_markdown),
            "shadow_status_payload_contract": str(status_payload_contract),
            "context_priority": str(context_priority_markdown),
            "webex_monitoring": str(webex_monitor_markdown),
            "webex_truth_request": str(webex_truth_request_markdown),
            "daily_diff": str(daily_diff_output),
            "operator_checklist": str(operator_checklist_output),
            "operator_console": str(operator_console_output),
            "operator_console_qa": str(operator_console_qa_markdown),
            "executive_pack": str(executive_output),
            "executive_one_pager": str(executive_one_pager_output),
            "owner_handoff": str(owner_handoff_output),
            "owner_message_drafts": str(owner_message_drafts_output),
            "owner_followup_tracker": str(owner_followup_tracker_markdown),
            "owner_followup_tracker_csv": str(owner_followup_tracker_output),
            "owner_response_templates": str(owner_response_templates_markdown),
            "owner_mapping_response_template": str(owner_mapping_response_template),
            "owner_webex_response_template": str(owner_webex_response_template),
            "owner_response_validation": str(owner_response_validation_markdown),
            "owner_response_intake": str(owner_response_intake_markdown),
            "owner_response_dry_run_impact": str(owner_response_dry_run_markdown),
            "owner_response_examples": str(owner_response_examples_markdown),
            "daily_executive_delta": str(daily_executive_delta_markdown),
            "executive_pitch_pack": str(executive_pitch_pack_output),
            "ais_updated_file_review": "runtime/analysis/ais_updated_file_review.md",
            "ais_updated_truth_review_summary": str(ais_updated_summary_output),
            "ais_updated_mapping_repair_request": str(ais_updated_mapping_request_output),
            "ais_updated_mapping_response_template": str(ais_updated_mapping_response_template),
            "ais_updated_mapping_private_lookup": str(ais_updated_mapping_private_lookup),
            "ais_updated_mapping_owner_message": str(ais_updated_mapping_owner_message),
            "current_capability_development_plan": str(current_capability_plan_markdown),
            "pitching_narrative": str(pitching_narrative_output),
        },
    }


def _intake_readme(root: Path) -> str:
    return "\n".join(
        [
            "# AIS Daily Truth Intake Workflow",
            "",
            "วัตถุประสงค์: รับไฟล์ outage/restore จาก AIS รายวัน แล้วทำให้ระบบ AIS ETR shadow pilot ประเมินได้ทันที โดยยังไม่ส่ง production ให้ AIS",
            "",
            "## วิธีวางไฟล์",
            "",
            f"1. วางไฟล์ AIS รายวันไว้ใน `{root / 'inbox'}`",
            "2. ตั้งชื่อไฟล์ให้มีวันที่ เช่น `AIS_AC_MAIN_FAIL_2026-06-19.xlsx`",
            "3. รัน `python -m ais_etr daily-shadow-refresh` ระบบจะหาไฟล์ใหม่ล่าสุดใน inbox ให้เอง",
            "4. ถ้าต้องการระบุไฟล์เอง ให้ใช้ `python -m ais_etr daily-shadow-refresh --ais-source <path>`",
            "5. ถ้าเป็น template มาตรฐาน `site_id, peano, outage_start_time, power_restore_time` ให้ใช้ `--ais-source-format template`",
            "",
            "## กันการประมวลผลซ้ำ",
            "",
            f"- ระบบบันทึก manifest ไว้ที่ `{root / 'source_manifest.csv'}`",
            "- ถ้าไฟล์เดิมถูก import แล้ว รอบถัดไปจะไม่ import ซ้ำ เว้นแต่ไฟล์ถูกแก้ไขจน size/modified time เปลี่ยน",
            f"- ตรวจสถานะ inbox ได้ด้วย `python -m ais_etr daily-inbox-status` หรือเปิด `{root / 'inbox_status.csv'}`",
            "",
            "## ความหมายของเวลา",
            "",
            "- `outage_start_time` หรือ `First Occurred On` = เวลาไฟ AC mains ดับจริงที่ site",
            "- `power_restore_time` หรือ `Cleared On` = เวลาไฟ AC mains กลับมาจริง",
            "- `actual_restoration_minutes` = restore - outage",
            "- `<=5 นาที` = review-only; `>5 นาที` = sustained outage eligible",
            "",
            "## Guardrails",
            "",
            "- AIS outage/restore เป็น truth หลักสำหรับ customer-facing ETR",
            "- WebEx เป็น trigger/device evidence",
            "- PowerBI/SFSD/ReportPO เป็น context เท่านั้นจนกว่าจะ reviewed/approved",
            "- ห้ามใช้ ticket close time, `cl_datetime`, `EVENT_END_TIME`, หรือ ETR sent time เป็น restoration truth",
            "- ห้ามใส่ token, room id, verbatim WebEx text, customer name หรือ PEANO list ใน report สำหรับผู้บริหาร",
            "",
            "## Output หลักหลังรัน",
            "",
            "- `runtime/autonomous_evidence_collector.md`",
            "- `runtime/forward_capture_autofill_candidates.csv`",
            "- `runtime/approved_context_candidates_review.csv`",
            "- `runtime/rejected_context_conflicts.csv`",
            "- `runtime/executive_shadow_status_pack.md`",
            "",
        ]
    )


def _review_row(row: dict[str, str], decision: str, notes: str) -> dict[str, str]:
    return {
        "event_ref": row.get("event_ref", ""),
        "event_time": row.get("event_time", ""),
        "feeder": row.get("feeder", ""),
        "device_id": row.get("device_id", ""),
        "evidence_status": row.get("evidence_status", ""),
        "evidence_score": row.get("evidence_score", ""),
        "context_sources": row.get("context_sources", ""),
        "cause_group": row.get("cause_group", ""),
        "work_type": row.get("work_type", ""),
        "weather_or_lightning": row.get("weather_or_lightning", ""),
        "sfsd_match_status": row.get("sfsd_match_status", ""),
        "sfsd_match_level": row.get("sfsd_match_level", ""),
        "sfsd_evidence_quality": row.get("sfsd_evidence_quality", ""),
        "sfsd_cause_status": row.get("sfsd_cause_status", ""),
        "evidence_reasons": row.get("evidence_reasons", ""),
        "review_decision": decision,
        "review_notes": notes,
    }


def _render_review_markdown(title: str, rows: list[dict[str, str]], intro: str) -> str:
    feeder_counts = Counter(row.get("feeder") or "<blank>" for row in rows)
    lines = [
        f"# {title}",
        "",
        intro,
        "",
        f"- Rows: {len(rows)}",
        "",
        "## Feeder Counts",
        "",
        *[f"- {key}: {value}" for key, value in feeder_counts.most_common()],
        "",
        "## Review Rows",
        "",
    ]
    if rows:
        cols = ("event_ref", "feeder", "device_id", "evidence_status", "evidence_score", "context_sources", "evidence_reasons")
        lines.append("|" + "|".join(cols) + "|")
        lines.append("|" + "|".join("---" for _ in cols) + "|")
        for row in rows[:30]:
            lines.append("|" + "|".join(_cell(row.get(col, "")) for col in cols) + "|")
    else:
        lines.append("No rows in this category.")
    lines.append("")
    return "\n".join(lines)


def _render_executive_markdown(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# AIS ETR Shadow Pilot Executive Status",
            "",
            "This pack summarizes the current shadow pilot. It does not approve production AIS sends and does not change model artifacts.",
            "",
            "## Current Decision",
            "",
            f"- Production status: `{summary['production_gate_status']}`",
            "- Truth source: AIS outage/restore only",
            "- Trigger/source evidence: WebEx",
            "- PEA PowerBI/SFSD/ReportPO: context only until reviewed and approved",
            "",
            "## Readiness Counts",
            "",
            f"- Total shadow rows: {summary['eligibility_rows']}",
            f"- AIS truth matched: {summary['ais_truth_matched_rows']}",
            f"- WebEx trigger without AIS truth: {summary['webex_trigger_no_ais_truth_rows']}",
            f"- PEA quarantined/context-only: {summary['pea_quarantined_rows']}",
            f"- Green auto candidates: {summary['green_auto_candidate_rows']}",
            f"- Amber human review: {summary['amber_human_review_rows']}",
            f"- Red blocked: {summary['red_blocked_rows']}",
            f"- Monitor only: {summary['monitor_only_rows']}",
            "",
            "## Evidence Counts",
            "",
            f"- Context approved candidates for human review: {summary['approved_context_candidate_rows']}",
            f"- Context conflicts: {summary['context_conflict_rows']}",
            f"- Pending insufficient evidence: {summary['pending_insufficient_evidence_rows']}",
            "",
            "## Gate Metrics",
            "",
            f"- Green q50 MAE: {summary['green_q50_mae_minutes'] if summary['green_q50_mae_minutes'] is not None else 'n/a'} minutes",
            f"- Green q10-q90 coverage: {summary['green_q10_q90_coverage'] if summary['green_q10_q90_coverage'] is not None else 'n/a'}",
            f"- Production metric gate: q50 MAE <= {GATE_Q50_MAE_MAX} and q10-q90 coverage {GATE_COVERAGE_MIN}-{GATE_COVERAGE_MAX}",
            "",
            "## Recommended Next Action",
            "",
            "Use the daily AIS file to increase AIS truth coverage, review approved context candidates while events are fresh, and keep conflicts out of training until resolved.",
            "",
        ]
    )


def _context_review_row(row: dict[str, str]) -> dict[str, str]:
    return {column: row.get(column, "") for column in CONTEXT_REVIEW_COLUMNS}


def _context_summary(rows: list[dict[str, str]]) -> dict[str, Any]:
    reason_counts: Counter[str] = Counter()
    for row in rows:
        for reason in str(row.get("evidence_reasons") or "").split(";"):
            if reason.strip():
                reason_counts[reason.strip()] += 1
    return {
        "rows": len(rows),
        "feeder_counts": dict(Counter(row.get("feeder") or "<blank>" for row in rows).most_common()),
        "device_counts": dict(Counter(row.get("device_id") or "<blank>" for row in rows).most_common()),
        "cause_counts": dict(Counter(row.get("cause_group") or "<blank>" for row in rows).most_common()),
        "work_type_counts": dict(Counter(row.get("work_type") or "<blank>" for row in rows).most_common()),
        "context_source_counts": dict(Counter(row.get("context_sources") or "<blank>" for row in rows).most_common()),
        "reason_counts": dict(reason_counts.most_common()),
    }


def _render_conflict_deep_dive(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Context Conflict Deep Dive",
        "",
        "This report isolates rows where AIS outage/restore truth conflicts with PEA PowerBI/SFSD/ReportPO context. These rows must stay out of model truth, feature approval, and customer-facing ETR claims until resolved.",
        "",
        "## Decision",
        "",
        "- Keep these rows blocked from training and production sends.",
        "- Treat AIS outage/restore as the customer-facing truth.",
        "- Treat PowerBI/SFSD/ReportPO as context only, especially when it indicates momentary/short interruption while AIS shows sustained outage.",
        "",
        "## Summary",
        "",
        f"- Conflict rows: {summary['rows']}",
        "",
        "## Feeder Counts",
        "",
        *_bullet_counts(summary["feeder_counts"]),
        "",
        "## Main Reasons",
        "",
        *_bullet_counts(summary["reason_counts"]),
        "",
        "## Review Table",
        "",
        *_context_table(rows),
        "",
        "## Recommended Handling",
        "",
        "- Do not approve these rows in forward capture.",
        "- Do not infer restoration truth from PEA close time, short interruption labels, or administrative event end time.",
        "- If the same pattern repeats on new AIS daily files, escalate as a data-governance issue rather than tuning the model around it.",
        "",
    ]
    return "\n".join(lines)


def _render_approved_summary(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Approved Context Candidate Summary",
        "",
        "These rows have the strongest context evidence and are candidates for human/source-owner review. They are not automatically approved and do not become restoration truth.",
        "",
        "## Summary",
        "",
        f"- Candidate rows: {summary['rows']}",
        "",
        "## Feeder Counts",
        "",
        *_bullet_counts(summary["feeder_counts"]),
        "",
        "## Cause Counts",
        "",
        *_bullet_counts(summary["cause_counts"]),
        "",
        "## Work Type Counts",
        "",
        *_bullet_counts(summary["work_type_counts"]),
        "",
        "## Context Sources",
        "",
        *_bullet_counts(summary["context_source_counts"]),
        "",
        "## Review Table",
        "",
        *_context_table(rows),
        "",
        "## Recommended Handling",
        "",
        "- Review while the event is still fresh.",
        "- Only copy context into approved forward-capture fields after a reliable operational source or owner confirms it.",
        "- Keep `first_restore_time` blank unless it comes from AIS outage/restore or an explicitly approved equivalent.",
        "",
    ]
    return "\n".join(lines)


def _context_table(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return ["No rows."]
    columns = (
        "event_ref",
        "feeder",
        "device_id",
        "actual_restoration_minutes",
        "evidence_status",
        "evidence_score",
        "context_sources",
        "cause_group",
        "work_type",
        "evidence_reasons",
    )
    output = ["|" + "|".join(columns) + "|", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows[:50]:
        output.append("|" + "|".join(_cell(row.get(column, "")) for column in columns) + "|")
    return output


def _current_diff_snapshot(
    eligibility_csv: str | Path,
    evidence_csv: str | Path,
    inbox_status_csv: str | Path,
    run_at: str,
) -> dict[str, str]:
    eligibility = _read_csv(eligibility_csv)
    evidence = _read_csv(evidence_csv)
    inbox = _read_csv(inbox_status_csv)
    eligibility_counts = Counter(row.get("eligibility_status") or "<blank>" for row in eligibility)
    source_lane_counts = Counter(row.get("source_lane") or "<blank>" for row in eligibility)
    evidence_counts = Counter(row.get("evidence_status") or "<blank>" for row in evidence)
    green = [row for row in eligibility if row.get("eligibility_status") == "green_auto_candidate"]
    green_errors = [_to_float(row.get("selected_absolute_error")) for row in green]
    green_errors = [value for value in green_errors if value is not None]
    green_mae = mean(green_errors) if green_errors else None
    green_coverage = _coverage(green, "selected_covered_q10_q90")
    return {
        "run_at": run_at,
        "total_rows": str(len(eligibility)),
        "ais_truth_matched": str(source_lane_counts.get("ais_truth_matched", 0)),
        "webex_trigger_no_ais_truth": str(source_lane_counts.get("webex_trigger_no_ais_truth", 0)),
        "pea_quarantined": str(source_lane_counts.get("pea_quarantined", 0)),
        "green_auto_candidate": str(eligibility_counts.get("green_auto_candidate", 0)),
        "amber_human_review": str(eligibility_counts.get("amber_human_review", 0)),
        "red_blocked": str(eligibility_counts.get("red_blocked", 0)),
        "monitor_only": str(eligibility_counts.get("monitor_only", 0)),
        "approved_candidate": str(evidence_counts.get("approved_candidate", 0)),
        "pending_insufficient_evidence": str(evidence_counts.get("pending_insufficient_evidence", 0)),
        "context_conflicts": str(evidence_counts.get("pending_conflict", 0) + evidence_counts.get("rejected_conflict", 0)),
        "green_q50_mae_minutes": "" if green_mae is None else str(_round_or_none(green_mae)),
        "green_q10_q90_coverage": "" if green_coverage is None else str(_round_or_none(green_coverage, 3)),
        "production_gate_status": _gate_status(green, green_mae, green_coverage),
        "pending_inbox_files": str(sum(1 for row in inbox if row.get("status") == "pending")),
    }


def _diff_snapshot(previous: dict[str, str], current: dict[str, str]) -> dict[str, str]:
    deltas: dict[str, str] = {}
    for column in DIFF_HISTORY_COLUMNS:
        if column in {"run_at", "production_gate_status"}:
            continue
        current_value = _to_float(current.get(column))
        previous_value = _to_float(previous.get(column))
        if current_value is None or previous_value is None:
            deltas[column] = ""
        else:
            delta = current_value - previous_value
            deltas[column] = _signed(delta)
    if previous:
        deltas["production_gate_status"] = "unchanged" if previous.get("production_gate_status") == current.get("production_gate_status") else f"{previous.get('production_gate_status')} -> {current.get('production_gate_status')}"
    else:
        deltas["production_gate_status"] = "baseline"
    return deltas


def _render_daily_diff(current: dict[str, str], previous: dict[str, str], deltas: dict[str, str]) -> str:
    lines = [
        "# Daily Shadow Diff",
        "",
        "This report compares the current shadow readiness snapshot with the previous recorded snapshot. It is for monitoring only and does not approve production sends.",
        "",
        f"- Current run: {current.get('run_at')}",
        f"- Previous run: {previous.get('run_at', 'none') or 'none'}",
        f"- Production gate: `{current.get('production_gate_status')}` ({deltas.get('production_gate_status')})",
        "",
        "|Metric|Current|Delta|",
        "|---|---:|---:|",
    ]
    for column in DIFF_HISTORY_COLUMNS:
        if column in {"run_at", "production_gate_status"}:
            continue
        lines.append(f"|{column}|{current.get(column, '')}|{deltas.get(column, '')}|")
    lines.extend(
        [
            "",
            "## Reading Notes",
            "",
            "- Positive `ais_truth_matched` is good only when generated from AIS outage/restore files.",
            "- Positive `context_conflicts` means more rows need governance review before any model feature use.",
            "- The production gate remains blocked unless green MAE and coverage both pass the configured threshold.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_synthetic_smoke(passed: bool, source: Path, first: dict[str, Any], second: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Synthetic AIS Daily File Smoke Test",
            "",
            f"- Status: {'PASS' if passed else 'FAIL'}",
            f"- Synthetic source: `{source}`",
            f"- First discovery: `{first.get('discovery_status')}`",
            f"- First selected source: `{first.get('selected_source') or ''}`",
            f"- Second discovery after manifest mark: `{second.get('discovery_status')}`",
            f"- Pending files after manifest mark: `{second.get('pending_files')}`",
            "",
            "This smoke test validates inbox discovery and manifest de-duplication only. It does not import the synthetic file into production/runtime AIS truth.",
            "",
        ]
    )


def _render_operator_checklist() -> str:
    return "\n".join(
        [
            "# Operator Shadow Review Checklist",
            "",
            "Use this checklist when a new WebEx outage and/or daily AIS file arrives. The workflow is shadow-only until the metric gate and approval path pass.",
            "",
            "## 1. Daily Intake",
            "",
            "1. Put the AIS daily file in `runtime/daily_ais_intake/inbox`.",
            "2. Run `python -m ais_etr daily-shadow-refresh`.",
            "3. Check `runtime/daily_shadow_refresh_steps.csv`; failures must be resolved before reviewing ETR output.",
            "",
            "## 2. Truth Rules",
            "",
            "- AIS outage/restore is the customer-facing truth.",
            "- WebEx is trigger/device evidence.",
            "- PowerBI/SFSD/ReportPO is context only unless reviewed and approved.",
            "- Do not use ticket close time, `cl_datetime`, `EVENT_END_TIME`, or ETR sent time as restoration truth.",
            "- Keep `<=5 minute` interruptions in review-only unless a sustained AIS interval proves otherwise.",
            "",
            "## 3. Review Order",
            "",
            "1. Open `runtime/rejected_context_conflicts.csv` first; keep these blocked.",
            "2. Open `runtime/approved_context_candidates_review.csv`; review strong context candidates while fresh.",
            "3. Open `runtime/forward_capture_autofill_candidates.csv`; rows remain `pending` until a reviewer approves.",
            "4. Open `runtime/executive_shadow_status_pack.md` for management status.",
            "",
            "## 4. Production Gate",
            "",
            "- No production AIS sends while `runtime/production_readiness_gate.md` is blocked.",
            "- Auto p50/range send needs q50 MAE <= 16 minutes and q10-q90 coverage between 0.75 and 0.90 on the approved green subset.",
            "- If gate fails, use status-only or human-reviewed messaging only.",
            "",
        ]
    )


def _detect_ais_source_format(path: str | Path, requested: str) -> str:
    if requested in {"add_field", "template"}:
        return requested
    name = Path(path).name.lower()
    if "add_field" in name or "ac_main_fail" in name or "ac main fail" in name:
        return "add_field"
    return "template"


def _scan_inbox(intake_dir: str | Path) -> list[Path]:
    inbox = Path(intake_dir) / "inbox"
    if not inbox.exists():
        return []
    return [
        path
        for path in inbox.iterdir()
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_AIS_SOURCE_SUFFIXES
        and not path.name.startswith("~$")
    ]


def _manifest_path(intake_dir: str | Path, manifest_csv: str | Path | None = None) -> Path:
    return Path(manifest_csv) if manifest_csv else Path(intake_dir) / "source_manifest.csv"


def _manifest_by_fingerprint(manifest_csv: str | Path) -> dict[str, dict[str, str]]:
    rows = _read_csv(manifest_csv)
    output: dict[str, dict[str, str]] = {}
    for row in rows:
        fingerprint = row.get("fingerprint", "")
        if fingerprint:
            output[fingerprint] = row
    return output


def _append_manifest_row(
    manifest_csv: str | Path,
    source: str | Path,
    *,
    status: str,
    source_format: str,
    notes: str,
) -> None:
    path = Path(source)
    manifest = Path(manifest_csv)
    existing = _read_csv(manifest)
    fingerprint = _file_fingerprint(path)
    row = {
        "file_name": path.name,
        "file_path": str(path),
        "file_size_bytes": str(path.stat().st_size) if path.exists() else "",
        "modified_at": _file_modified_at(path) if path.exists() else "",
        "fingerprint": fingerprint,
        "status": status,
        "processed_at": datetime.now().isoformat(timespec="seconds"),
        "source_format": source_format,
        "notes": notes,
    }
    rows = [item for item in existing if item.get("fingerprint") != fingerprint]
    rows.append(row)
    _write_csv(manifest, INBOX_STATUS_COLUMNS, rows)


def _file_fingerprint(path: str | Path) -> str:
    source = Path(path)
    try:
        stat = source.stat()
        return f"{source.resolve()}|{stat.st_size}|{int(stat.st_mtime)}"
    except FileNotFoundError:
        return str(source)


def _file_modified_at(path: str | Path) -> str:
    return datetime.fromtimestamp(Path(path).stat().st_mtime).isoformat(timespec="seconds")


def _gate_status(green_rows: list[dict[str, str]], mae: float | None, coverage: float | None) -> str:
    if not green_rows:
        return "blocked_no_green_subset"
    if mae is not None and coverage is not None and mae <= GATE_Q50_MAE_MAX and GATE_COVERAGE_MIN <= coverage <= GATE_COVERAGE_MAX:
        return "shadow_green_subset_passed_requires_human_approval"
    return "blocked_metric_gate_failed"


def _compact_detail(value: Any) -> str:
    if isinstance(value, dict):
        parts = []
        for key in ("rows", "valid_rows", "reject_rows", "matched_rows", "filled_rows", "approved_candidate_rows", "conflict_rows", "production_gate_status", "output_csv", "output"):
            if key in value:
                parts.append(f"{key}={value[key]}")
        return "; ".join(parts)[:1000] if parts else str(value)[:1000]
    return str(value)[:1000]


def _bullet_counts(counts: dict[str, int]) -> list[str]:
    if not counts:
        return ["- none: 0"]
    return [f"- {key}: {value}" for key, value in counts.items()]


def _signed(value: float) -> str:
    if value == int(value):
        value = int(value)
    return f"+{value}" if value > 0 else str(value)


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


def _exists(path: str | Path | None) -> bool:
    return bool(path) and Path(path).exists()


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


def _to_bool(value: Any) -> bool | None:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _truthy(value: Any) -> bool:
    return _to_bool(value) is True


def _round_or_none(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _cell(value: Any) -> str:
    return str(value or "").replace("|", "/").replace("\n", " ").strip()[:180]
