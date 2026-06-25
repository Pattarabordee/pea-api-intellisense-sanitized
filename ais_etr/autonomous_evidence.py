from __future__ import annotations

from collections import Counter
import csv
import hashlib
from pathlib import Path
from typing import Any, Iterable

from .confidence_gate import FORWARD_CAPTURE_COLUMNS


EVIDENCE_COLUMNS = (
    "event_ref",
    "event_time",
    "feeder",
    "device_id",
    "source_lane",
    "eligibility_status",
    "stage1_class",
    "active_ais_outage_confirmed",
    "actual_restoration_minutes",
    "selected_p50",
    "selected_q10",
    "selected_q90",
    "selected_absolute_error",
    "evidence_status",
    "evidence_grade",
    "evidence_score",
    "evidence_reasons",
    "autofill_recommended",
    "context_sources",
    "cause_group",
    "work_type",
    "switching_or_isolation",
    "material_repair_required",
    "weather_or_lightning",
    "reportpo_feature_status",
    "reportpo_feature_quality",
    "reportpo_lifecycle_status",
    "reportpo_lifecycle_quality",
    "sfsd_match_status",
    "sfsd_match_level",
    "sfsd_evidence_quality",
    "sfsd_cause_status",
    "recommended_action",
)


def build_autonomous_evidence_collector(
    eligibility_csv: str | Path,
    reportpo_feature_audit_csv: str | Path,
    reportpo_lifecycle_audit_csv: str | Path,
    sfsd_evidence_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    autofill_output: str | Path | None = None,
    *,
    approved_score_threshold: float = 80.0,
    partial_score_threshold: float = 45.0,
    long_conflict_minutes: float = 60.0,
) -> dict[str, Any]:
    """Collect context evidence without promoting it to restoration truth.

    AIS outage/restore remains the only customer-facing truth. PEA sources are
    scored as context so operators can review them quickly, but generated
    forward-capture rows stay pending.
    """

    eligibility_rows = _read_csv(eligibility_csv)
    feature_by_ref = _read_reportpo_by_ref(reportpo_feature_audit_csv)
    lifecycle_by_ref = _read_reportpo_by_ref(reportpo_lifecycle_audit_csv)
    sfsd_by_ref = _read_by_ref(sfsd_evidence_csv, "event_ref")

    output_rows = [
        _build_evidence_row(
            row,
            feature_by_ref.get(row.get("event_ref") or "", []),
            lifecycle_by_ref.get(row.get("event_ref") or "", []),
            sfsd_by_ref.get(row.get("event_ref") or "", []),
            approved_score_threshold=approved_score_threshold,
            partial_score_threshold=partial_score_threshold,
            long_conflict_minutes=long_conflict_minutes,
        )
        for row in eligibility_rows
    ]
    _write_csv(output_csv, EVIDENCE_COLUMNS, output_rows)

    autofill_rows = [_autofill_row(row) for row in output_rows if row.get("autofill_recommended") == "TRUE"]
    if autofill_output:
        _write_csv(autofill_output, FORWARD_CAPTURE_COLUMNS, autofill_rows)

    summary = _summary(
        output_rows,
        eligibility_rows,
        approved_score_threshold,
        partial_score_threshold,
        long_conflict_minutes,
    )
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_markdown(summary, output_rows), encoding="utf-8-sig")

    return {
        **summary,
        "eligibility_csv": str(eligibility_csv),
        "reportpo_feature_audit_csv": str(reportpo_feature_audit_csv),
        "reportpo_lifecycle_audit_csv": str(reportpo_lifecycle_audit_csv),
        "sfsd_evidence_csv": str(sfsd_evidence_csv),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "autofill_output": str(autofill_output) if autofill_output else None,
        "autofill_rows": len(autofill_rows),
    }


def _build_evidence_row(
    eligibility: dict[str, str],
    feature_rows: list[dict[str, str]],
    lifecycle_rows: list[dict[str, str]],
    sfsd_rows: list[dict[str, str]],
    *,
    approved_score_threshold: float,
    partial_score_threshold: float,
    long_conflict_minutes: float,
) -> dict[str, str]:
    source_lane = eligibility.get("source_lane", "")
    eligibility_status = eligibility.get("eligibility_status", "")
    feature = _best_reportpo_row(feature_rows, "feature")
    lifecycle = _best_reportpo_row(lifecycle_rows, "lifecycle")
    sfsd = _best_sfsd_row(sfsd_rows)

    score = 0.0
    reasons: list[str] = []
    conflicts: list[str] = []
    context_sources: list[str] = []

    actual = _to_float(eligibility.get("actual_restoration_minutes"))
    active_confirmed = _bool_text(eligibility.get("active_ais_outage_confirmed"))

    if source_lane == "webex_trigger_no_ais_truth":
        status = "monitor_only"
        grade = "context_only"
        reasons.append("missing_ais_truth")
    elif source_lane == "pea_quarantined":
        status = "blocked_no_customer_send"
        grade = "blocked"
        reasons.append("pea_quarantined")
    else:
        if source_lane == "ais_truth_matched":
            score += 30
        else:
            reasons.append("not_ais_truth_matched")
        if active_confirmed == "TRUE":
            score += 15
        else:
            reasons.append("no_active_ais_evidence")

        _score_sfsd(sfsd, actual, long_conflict_minutes, context_sources, reasons, conflicts, score_holder := {"score": score})
        score = score_holder["score"]
        _score_reportpo_feature(feature, context_sources, reasons, score_holder := {"score": score})
        score = score_holder["score"]
        _score_reportpo_lifecycle(lifecycle, context_sources, reasons, score_holder := {"score": score})
        score = score_holder["score"]

        if conflicts:
            status = "rejected_conflict" if _has_hard_conflict(conflicts) else "pending_conflict"
            grade = "conflict"
            reasons.extend(conflicts)
        elif _is_strong_context(sfsd) and score >= approved_score_threshold:
            status = "approved_candidate"
            grade = "strong"
        elif score >= partial_score_threshold:
            status = "pending_insufficient_evidence"
            grade = "partial"
        else:
            status = "pending_insufficient_evidence"
            grade = "weak"

    sfsd_context = _sfsd_context_fields(sfsd if _is_strong_context(sfsd) else {})
    autofill = _autofill_recommended(source_lane, eligibility_status, status, sfsd_context, feature, lifecycle)
    if status in {"monitor_only", "blocked_no_customer_send"}:
        autofill = False

    return {
        "event_ref": eligibility.get("event_ref", ""),
        "event_time": eligibility.get("event_time", ""),
        "feeder": eligibility.get("feeder", ""),
        "device_id": eligibility.get("device_id", ""),
        "source_lane": source_lane,
        "eligibility_status": eligibility_status,
        "stage1_class": eligibility.get("stage1_class", ""),
        "active_ais_outage_confirmed": active_confirmed,
        "actual_restoration_minutes": eligibility.get("actual_restoration_minutes", ""),
        "selected_p50": eligibility.get("selected_p50", ""),
        "selected_q10": eligibility.get("selected_q10", ""),
        "selected_q90": eligibility.get("selected_q90", ""),
        "selected_absolute_error": eligibility.get("selected_absolute_error", ""),
        "evidence_status": status,
        "evidence_grade": grade,
        "evidence_score": _fmt(score),
        "evidence_reasons": ";".join(_dedupe(reasons)),
        "autofill_recommended": _bool_str(autofill),
        "context_sources": ";".join(_dedupe(context_sources)),
        "cause_group": sfsd_context.get("cause_group", ""),
        "work_type": sfsd_context.get("work_type", ""),
        "switching_or_isolation": "",
        "material_repair_required": "",
        "weather_or_lightning": sfsd_context.get("weather_or_lightning", ""),
        "reportpo_feature_status": feature.get("match_status", ""),
        "reportpo_feature_quality": feature.get("feature_quality", ""),
        "reportpo_lifecycle_status": lifecycle.get("match_status", ""),
        "reportpo_lifecycle_quality": lifecycle.get("lifecycle_quality", ""),
        "sfsd_match_status": sfsd.get("sfsd_match_status", ""),
        "sfsd_match_level": sfsd.get("sfsd_match_level", ""),
        "sfsd_evidence_quality": sfsd.get("sfsd_evidence_quality", ""),
        "sfsd_cause_status": sfsd.get("cause_status", ""),
        "recommended_action": _recommended_action(status, eligibility_status, reasons),
    }


def _score_sfsd(
    sfsd: dict[str, str],
    actual: float | None,
    long_conflict_minutes: float,
    context_sources: list[str],
    reasons: list[str],
    conflicts: list[str],
    score_holder: dict[str, float],
) -> None:
    if not sfsd:
        reasons.append("sfsd_missing")
        return
    context_sources.append("sfsd")
    match_status = _lower(sfsd.get("sfsd_match_status"))
    match_level = _lower(sfsd.get("sfsd_match_level"))
    quality = _upper(sfsd.get("sfsd_evidence_quality"))
    cause_status = _lower(sfsd.get("cause_status"))
    if match_status == "matched" and match_level == "event_number":
        score_holder["score"] += 20
    elif "feeder" in match_level:
        reasons.append("sfsd_feeder_time_audit_only")
    elif match_status == "no_match":
        reasons.append("sfsd_no_match")
    else:
        reasons.append("sfsd_not_event_number_matched")
    if quality == "PEA_SUSTAINED":
        score_holder["score"] += 15
    elif quality == "PEA_MOMENTARY_OR_SHORT":
        reasons.append("sfsd_momentary_or_short")
        if actual is not None and actual > long_conflict_minutes:
            conflicts.append("pea_momentary_ais_sustained_conflict")
    elif quality:
        reasons.append("sfsd_quality_context_only")
    if cause_status == "cause_available":
        score_holder["score"] += 20
    elif cause_status:
        reasons.append("sfsd_cause_missing")


def _score_reportpo_feature(
    feature: dict[str, str],
    context_sources: list[str],
    reasons: list[str],
    score_holder: dict[str, float],
) -> None:
    if not feature:
        reasons.append("reportpo_feature_missing")
        return
    status = _lower(feature.get("match_status"))
    quality = _lower(feature.get("feature_quality"))
    flags = _lower(feature.get("feature_flags"))
    if status == "matched":
        context_sources.append("reportpo_feature")
        if quality == "proxy_only" or "cause_missing" in flags:
            score_holder["score"] += 5
            reasons.append("reportpo_feature_proxy_context_only")
        else:
            score_holder["score"] += 10
    elif status == "ambiguous":
        context_sources.append("reportpo_feature")
        reasons.append("reportpo_feature_ambiguous")
    elif status:
        reasons.append("reportpo_feature_no_match")


def _score_reportpo_lifecycle(
    lifecycle: dict[str, str],
    context_sources: list[str],
    reasons: list[str],
    score_holder: dict[str, float],
) -> None:
    if not lifecycle:
        reasons.append("reportpo_lifecycle_missing")
        return
    status = _lower(lifecycle.get("match_status"))
    quality = _lower(lifecycle.get("lifecycle_quality"))
    job_status = _lower(lifecycle.get("job_status_at_notification"))
    if status == "matched":
        context_sources.append("reportpo_lifecycle")
        score_holder["score"] += 5
        if quality in {"restore_available", "lifecycle_only"}:
            score_holder["score"] += 5
        if job_status == "closed" or lifecycle.get("cl_datetime"):
            reasons.append("close_time_context_only_not_truth")
    elif status == "ambiguous":
        context_sources.append("reportpo_lifecycle")
        reasons.append("reportpo_lifecycle_ambiguous")
    elif status:
        reasons.append("reportpo_lifecycle_no_match")


def _best_reportpo_row(rows: list[dict[str, str]], row_type: str) -> dict[str, str]:
    if not rows:
        return {}

    def score(row: dict[str, str]) -> tuple[int, int]:
        status = _lower(row.get("match_status"))
        if status == "matched":
            base = 3
        elif status == "ambiguous":
            base = 2
        elif status == "no_match":
            base = 1
        else:
            base = 0
        if row_type == "feature":
            quality = 1 if row.get("feature_quality") else 0
        else:
            quality = 1 if row.get("lifecycle_quality") else 0
        return (base, quality)

    return sorted(rows, key=score, reverse=True)[0]


def _best_sfsd_row(rows: list[dict[str, str]]) -> dict[str, str]:
    if not rows:
        return {}

    def score(row: dict[str, str]) -> tuple[int, int, int]:
        match = 2 if _lower(row.get("sfsd_match_status")) == "matched" else 0
        level = 2 if _lower(row.get("sfsd_match_level")) == "event_number" else (1 if "feeder" in _lower(row.get("sfsd_match_level")) else 0)
        cause = 1 if _lower(row.get("cause_status")) == "cause_available" else 0
        return (match, level, cause)

    return sorted(rows, key=score, reverse=True)[0]


def _is_strong_context(sfsd: dict[str, str]) -> bool:
    return (
        _lower(sfsd.get("sfsd_match_status")) == "matched"
        and _lower(sfsd.get("sfsd_match_level")) == "event_number"
        and _upper(sfsd.get("sfsd_evidence_quality")) == "PEA_SUSTAINED"
        and _lower(sfsd.get("cause_status")) == "cause_available"
    )


def _sfsd_context_fields(sfsd: dict[str, str]) -> dict[str, str]:
    if not sfsd:
        return {}
    return {
        "cause_group": sfsd.get("sfsd_main_cause", ""),
        "work_type": sfsd.get("sfsd_sub_cause", ""),
        "weather_or_lightning": sfsd.get("sfsd_weather", ""),
    }


def _autofill_recommended(
    source_lane: str,
    eligibility_status: str,
    status: str,
    sfsd_context: dict[str, str],
    feature: dict[str, str],
    lifecycle: dict[str, str],
) -> bool:
    if source_lane != "ais_truth_matched":
        return False
    if eligibility_status not in {"amber_human_review", "red_blocked"}:
        return False
    if status not in {"approved_candidate", "pending_conflict", "pending_insufficient_evidence", "rejected_conflict"}:
        return False
    return bool(
        any(sfsd_context.values())
        or _lower(feature.get("match_status")) in {"matched", "ambiguous"}
        or _lower(lifecycle.get("match_status")) in {"matched", "ambiguous"}
    )


def _autofill_row(row: dict[str, str]) -> dict[str, str]:
    notes = (
        f"autonomous_evidence_status={row.get('evidence_status','')}; "
        f"context_sources={row.get('context_sources','')}; "
        f"reasons={row.get('evidence_reasons','')}; "
        "review before approval; PEA context is not restoration truth."
    )
    return {
        "event_ref": row.get("event_ref", ""),
        "event_time": row.get("event_time", ""),
        "feeder": row.get("feeder", ""),
        "device_id": row.get("device_id", ""),
        "eligibility_status": row.get("eligibility_status", ""),
        "stage1_class": row.get("stage1_class", ""),
        "blocker_reasons": row.get("evidence_reasons", ""),
        "cause_group": row.get("cause_group", ""),
        "work_type": row.get("work_type", ""),
        "switching_or_isolation": row.get("switching_or_isolation", ""),
        "material_repair_required": row.get("material_repair_required", ""),
        "weather_or_lightning": row.get("weather_or_lightning", ""),
        "crew_dispatch_time": "",
        "arrival_time": "",
        "first_restore_time": "",
        "review_status": "pending",
        "reviewer": "",
        "reviewed_at": "",
        "notes": notes[:900],
    }


def _recommended_action(status: str, eligibility_status: str, reasons: list[str]) -> str:
    reason_set = set(reasons)
    if status == "approved_candidate":
        return "review_autofill_candidate_then_mark_approved_if_source_owner_accepts"
    if status == "pending_conflict":
        return "review_conflicting_context_before_feature_use"
    if status == "rejected_conflict":
        return "do_not_use_context_for_model_until_conflict_resolved"
    if status == "monitor_only":
        return "keep_monitoring_until_ais_truth_arrives"
    if status == "blocked_no_customer_send":
        return "keep_quarantined_no_customer_send"
    if "sfsd_missing" in reason_set:
        return "wait_for_next_powerbi_refresh_or_request_context_source"
    if eligibility_status == "green_auto_candidate":
        return "no_forward_capture_needed_keep_shadow_only_until_metric_gate_passes"
    return "collect_or_review_lifecycle_cause_context"


def _summary(
    rows: list[dict[str, str]],
    eligibility_rows: list[dict[str, str]],
    approved_score_threshold: float,
    partial_score_threshold: float,
    long_conflict_minutes: float,
) -> dict[str, Any]:
    statuses = Counter(row.get("evidence_status") or "<blank>" for row in rows)
    grades = Counter(row.get("evidence_grade") or "<blank>" for row in rows)
    lanes = Counter(row.get("source_lane") or "<blank>" for row in rows)
    actions = Counter(row.get("recommended_action") or "<blank>" for row in rows)
    return {
        "rows": len(rows),
        "eligibility_rows": len(eligibility_rows),
        "status_counts": dict(statuses.most_common()),
        "grade_counts": dict(grades.most_common()),
        "source_lane_counts": dict(lanes.most_common()),
        "recommended_action_counts": dict(actions.most_common()),
        "approved_candidate_rows": statuses.get("approved_candidate", 0),
        "pending_conflict_rows": statuses.get("pending_conflict", 0),
        "rejected_conflict_rows": statuses.get("rejected_conflict", 0),
        "pending_insufficient_evidence_rows": statuses.get("pending_insufficient_evidence", 0),
        "monitor_only_rows": statuses.get("monitor_only", 0),
        "blocked_no_customer_send_rows": statuses.get("blocked_no_customer_send", 0),
        "approved_score_threshold": approved_score_threshold,
        "partial_score_threshold": partial_score_threshold,
        "long_conflict_minutes": long_conflict_minutes,
    }


def _render_markdown(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    top_conflicts = [
        row
        for row in rows
        if row.get("evidence_status") in {"pending_conflict", "rejected_conflict"}
    ][:10]
    top_candidates = [
        row
        for row in rows
        if row.get("evidence_status") == "approved_candidate"
    ][:10]
    lines = [
        "# Autonomous Evidence Collector",
        "",
        "This report collects WebEx-triggered shadow rows and PowerBI-derived context evidence without approving production sends or changing restoration truth.",
        "",
        "## Guardrails",
        "",
        "- AIS outage/restore remains the customer-facing truth source.",
        "- WebEx remains trigger and device evidence.",
        "- SFSD/ReportPO/PowerBI rows are context only unless reviewed and approved later.",
        "- Generated forward-capture rows stay `pending`; this command never writes `approved` review status.",
        "- Ticket close time, `cl_datetime`, and administrative end time are not used as restoration truth.",
        "",
        "## Summary",
        "",
        f"- Rows: {summary['rows']}",
        f"- Approved candidates for human review: {summary['approved_candidate_rows']}",
        f"- Pending conflicts: {summary['pending_conflict_rows']}",
        f"- Rejected conflicts: {summary['rejected_conflict_rows']}",
        f"- Pending insufficient evidence: {summary['pending_insufficient_evidence_rows']}",
        f"- Monitor only: {summary['monitor_only_rows']}",
        f"- Blocked/no customer send: {summary['blocked_no_customer_send_rows']}",
        "",
        "## Status Counts",
        "",
        *[f"- {key}: {value}" for key, value in summary["status_counts"].items()],
        "",
        "## Top Approved Candidates",
        "",
    ]
    if top_candidates:
        lines.extend(_markdown_table(top_candidates))
    else:
        lines.append("No approved candidates found in this run.")
    lines.extend(["", "## Top Conflicts", ""])
    if top_conflicts:
        lines.extend(_markdown_table(top_conflicts))
    else:
        lines.append("No conflicts found in this run.")
    lines.extend(
        [
            "",
            "## Next Action",
            "",
            "Run this after WebEx/PowerBI refreshes and after each new AIS file import. Review `runtime/forward_capture_autofill_candidates.csv`, fill missing fields from fresh operational evidence if available, then run `forward-capture-import` before any challenger model uses the context.",
            "",
        ]
    )
    return "\n".join(lines)


def _markdown_table(rows: list[dict[str, str]]) -> list[str]:
    columns = ("event_ref", "feeder", "device_id", "evidence_status", "evidence_score", "context_sources", "evidence_reasons")
    lines = [
        "|" + "|".join(columns) + "|",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    for row in rows:
        lines.append("|" + "|".join(_clean_markdown_cell(row.get(column, "")) for column in columns) + "|")
    return lines


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


def _read_by_ref(path: str | Path, ref_column: str) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in _read_csv(path):
        ref = row.get(ref_column, "")
        if ref:
            grouped.setdefault(ref, []).append(row)
    return grouped


def _read_reportpo_by_ref(path: str | Path) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in _read_csv(path):
        ref = row.get("event_ref") or _redacted_ref(row.get("webex_message_id"))
        if ref:
            grouped.setdefault(ref, []).append(row)
    return grouped


def _redacted_ref(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("msg-") and len(text) <= 32:
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"msg-{digest}"


def _has_hard_conflict(conflicts: list[str]) -> bool:
    return "pea_momentary_ais_sustained_conflict" in conflicts


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _bool_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return "TRUE"
    if text in {"0", "false", "no", "n"}:
        return "FALSE"
    return ""


def _bool_str(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return ""
    rounded = round(value, digits)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded).rstrip("0").rstrip(".")


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _clean_markdown_cell(value: Any) -> str:
    text = str(value or "").replace("|", "/").replace("\n", " ").strip()
    return text[:180]
