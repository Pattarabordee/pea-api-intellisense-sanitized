from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path
from statistics import mean
from typing import Any


PRIORITY_COLUMNS = (
    "priority_rank",
    "event_ref",
    "event_time",
    "district",
    "feeder",
    "device_id",
    "event_age_band",
    "active_elapsed_minutes",
    "remaining_actual_minutes",
    "current_p50",
    "active_p50",
    "active_error_minutes",
    "active_covered_q10_q90",
    "error_delta_active_minus_current",
    "active_source",
    "active_rows_used",
    "priority_cluster_key",
    "suspected_gap",
    "lifecycle_bridge_status",
    "owner_review_status",
    "approved_context_fields",
    "recommended_next_action",
)

REVIEW_TEMPLATE_COLUMNS = (
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
    "notes",
)


def build_long_outage_root_cause_pack(
    active_state_csv: str | Path,
    priority_output: str | Path,
    markdown_output: str | Path | None = None,
    review_template_output: str | Path | None = None,
    *,
    shared_key_audit_csv: str | Path | None = None,
    manual_bridge_csv: str | Path | None = None,
    lifecycle_review_csv: str | Path | None = None,
    high_error_minutes: float = 60.0,
    duration_outlier_minutes: float = 480.0,
    sparse_history_min_rows: int = 5,
    top_limit: int = 50,
) -> dict[str, Any]:
    active_rows = [
        row
        for row in _read_csv(active_state_csv)
        if (_to_float(row.get("active_absolute_error")) or 0) >= high_error_minutes
    ]
    active_rows = sorted(
        active_rows,
        key=lambda row: (
            -(_to_float(row.get("active_absolute_error")) or 0),
            row.get("event_time") or "",
            row.get("webex_message_ref") or "",
        ),
    )[: max(0, int(top_limit))]
    bridge_status = _shared_key_bridge_status(shared_key_audit_csv)
    approved_manual_by_ref = _load_approved_manual_bridge(manual_bridge_csv)
    review_by_ref = _load_lifecycle_review(lifecycle_review_csv)
    priority_rows = [
        _priority_row(
            row,
            rank=index,
            bridge_status=bridge_status,
            approved_manual=approved_manual_by_ref.get(row.get("webex_message_ref") or "", {}),
            lifecycle_review=review_by_ref.get(row.get("webex_message_ref") or "", {}),
            high_error_minutes=high_error_minutes,
            duration_outlier_minutes=duration_outlier_minutes,
            sparse_history_min_rows=sparse_history_min_rows,
        )
        for index, row in enumerate(active_rows, start=1)
    ]
    _write_csv(priority_output, PRIORITY_COLUMNS, priority_rows)
    if review_template_output:
        _write_csv(
            review_template_output,
            REVIEW_TEMPLATE_COLUMNS,
            [_review_template_row(row, review_by_ref.get(row.get("event_ref") or "")) for row in priority_rows],
        )
    summary = _summary(
        priority_rows,
        high_error_minutes=high_error_minutes,
        duration_outlier_minutes=duration_outlier_minutes,
        bridge_status=bridge_status,
    )
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_markdown(summary, priority_rows, review_template_output), encoding="utf-8-sig")
    return {
        **summary,
        "active_state_csv": str(active_state_csv),
        "priority_output": str(priority_output),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "review_template_output": str(review_template_output) if review_template_output else None,
        "shared_key_audit_csv": str(shared_key_audit_csv) if shared_key_audit_csv else None,
        "manual_bridge_csv": str(manual_bridge_csv) if manual_bridge_csv else None,
        "lifecycle_review_csv": str(lifecycle_review_csv) if lifecycle_review_csv else None,
    }


def _priority_row(
    row: dict[str, str],
    *,
    rank: int,
    bridge_status: str,
    approved_manual: dict[str, str],
    lifecycle_review: dict[str, str],
    high_error_minutes: float,
    duration_outlier_minutes: float,
    sparse_history_min_rows: int,
) -> dict[str, str]:
    approved_fields = _approved_context_fields(lifecycle_review)
    lifecycle_status = _lifecycle_bridge_status(bridge_status, approved_manual, lifecycle_review, approved_fields)
    gaps = _suspected_gaps(
        row,
        lifecycle_status=lifecycle_status,
        approved_fields=approved_fields,
        high_error_minutes=high_error_minutes,
        duration_outlier_minutes=duration_outlier_minutes,
        sparse_history_min_rows=sparse_history_min_rows,
    )
    return {
        "priority_rank": str(rank),
        "event_ref": row.get("webex_message_ref", ""),
        "event_time": row.get("event_time", ""),
        "district": row.get("district", ""),
        "feeder": row.get("feeder", ""),
        "device_id": row.get("device_id", ""),
        "event_age_band": row.get("event_age_band", ""),
        "active_elapsed_minutes": row.get("active_elapsed_minutes", ""),
        "remaining_actual_minutes": row.get("remaining_actual_minutes", ""),
        "current_p50": row.get("current_p50", ""),
        "active_p50": row.get("active_p50", ""),
        "active_error_minutes": row.get("active_absolute_error", ""),
        "active_covered_q10_q90": row.get("active_covered_q10_q90", ""),
        "error_delta_active_minus_current": row.get("error_delta_active_minus_current", ""),
        "active_source": row.get("active_source", ""),
        "active_rows_used": row.get("active_rows_used", ""),
        "priority_cluster_key": _cluster_key(row),
        "suspected_gap": ";".join(gaps),
        "lifecycle_bridge_status": lifecycle_status,
        "owner_review_status": lifecycle_review.get("review_status", "") or approved_manual.get("review_status", ""),
        "approved_context_fields": ";".join(approved_fields),
        "recommended_next_action": _recommended_action(gaps, lifecycle_status),
    }


def _suspected_gaps(
    row: dict[str, str],
    *,
    lifecycle_status: str,
    approved_fields: list[str],
    high_error_minutes: float,
    duration_outlier_minutes: float,
    sparse_history_min_rows: int,
) -> list[str]:
    gaps: list[str] = []
    active_error = _to_float(row.get("active_absolute_error")) or 0.0
    remaining = _to_float(row.get("remaining_actual_minutes")) or 0.0
    active_rows_used = _to_int(row.get("active_rows_used"))
    active_source = row.get("active_source") or ""
    if lifecycle_status in {"missing_lifecycle_bridge", "blocked_cl_datetime_not_truth", "shared_key_not_found"}:
        gaps.append("missing_lifecycle")
    if not any(field in approved_fields for field in ("outage_cause", "work_type", "weather_or_lightning")):
        gaps.append("missing_cause")
    if active_source in {"affected_meter_conditional_duration_prior", "global_conditional_duration_prior", "current_model_only"}:
        gaps.append("device_history_too_sparse")
    elif active_rows_used < sparse_history_min_rows:
        gaps.append("device_history_too_sparse")
    if remaining >= duration_outlier_minutes or active_error >= duration_outlier_minutes:
        gaps.append("duration_outlier")
    if active_error >= high_error_minutes and row.get("active_covered_q10_q90") == "TRUE":
        gaps.append("possible_topology_or_truth_review")
    return _dedupe(gaps) or ["needs_owner_review"]


def _lifecycle_bridge_status(
    bridge_status: str,
    approved_manual: dict[str, str],
    lifecycle_review: dict[str, str],
    approved_fields: list[str],
) -> str:
    if str(lifecycle_review.get("cl_datetime") or "").strip():
        return "blocked_cl_datetime_not_truth"
    if str(approved_manual.get("review_status") or "").strip().lower() == "approved":
        return "owner_approved_manual_bridge_context"
    if approved_fields:
        return "owner_approved_lifecycle_context"
    if bridge_status == "shared_key_found":
        return "shared_key_available_context_only"
    if bridge_status == "shared_key_not_found":
        return "shared_key_not_found"
    return "missing_lifecycle_bridge"


def _shared_key_bridge_status(path: str | Path | None) -> str:
    if not path or not Path(path).exists():
        return "missing_lifecycle_bridge"
    rows = _read_csv(path)
    for row in rows:
        status = str(row.get("status") or "").strip().lower()
        decision = str(row.get("decision") or "").strip().lower()
        focus_rows = _to_int(row.get("focus_overlap_rows"))
        overlap_rows = _to_int(row.get("overlap_left_rows")) + _to_int(row.get("overlap_right_rows"))
        if status in {"exact_match", "exact_overlap"} and "not_usable" not in decision and (focus_rows > 0 or overlap_rows > 0):
            return "shared_key_found"
    if rows:
        return "shared_key_not_found"
    return "missing_lifecycle_bridge"


def _load_approved_manual_bridge(path: str | Path | None) -> dict[str, dict[str, str]]:
    if not path or not Path(path).exists():
        return {}
    output = {}
    for row in _read_csv(path):
        ref = row.get("webex_message_ref") or row.get("webex_message_id") or ""
        if ref and str(row.get("review_status") or "").strip().lower() == "approved":
            output[ref] = row
    return output


def _load_lifecycle_review(path: str | Path | None) -> dict[str, dict[str, str]]:
    if not path or not Path(path).exists():
        return {}
    output = {}
    for row in _read_csv(path):
        ref = row.get("event_ref") or row.get("webex_message_ref") or ""
        if not ref:
            continue
        if str(row.get("review_status") or "").strip().lower() == "approved":
            output[ref] = row
    return output


def _approved_context_fields(row: dict[str, str]) -> list[str]:
    if str(row.get("review_status") or "").strip().lower() != "approved":
        return []
    fields = []
    for field in (
        "outage_cause",
        "work_type",
        "crew_dispatch_time",
        "arrival_time",
        "first_restore_time",
        "switching_or_isolation",
        "material_or_repair_required",
        "weather_or_lightning",
    ):
        if str(row.get(field) or "").strip():
            fields.append(field)
    return fields


def _review_template_row(row: dict[str, str], existing_review: dict[str, str] | None = None) -> dict[str, str]:
    base = {
        "event_ref": row.get("event_ref", ""),
        "event_time": row.get("event_time", ""),
        "feeder": row.get("feeder", ""),
        "device_id": row.get("device_id", ""),
        "active_error_minutes": row.get("active_error_minutes", ""),
        "suspected_gap": row.get("suspected_gap", ""),
        "outage_cause": "",
        "work_type": "",
        "crew_dispatch_time": "",
        "arrival_time": "",
        "first_restore_time": "",
        "switching_or_isolation": "",
        "material_or_repair_required": "",
        "weather_or_lightning": "",
        "review_status": "pending",
        "reviewer": "",
        "reviewed_at": "",
        "notes": "Fill only with source-owner approved lifecycle/cause context. Do not paste source chat bodies or meter lists.",
    }
    if existing_review and str(existing_review.get("review_status") or "").strip().lower() == "approved":
        for column in REVIEW_TEMPLATE_COLUMNS:
            if column in existing_review and str(existing_review.get(column) or "").strip():
                base[column] = existing_review.get(column, "")
    return base


def _summary(
    rows: list[dict[str, str]],
    *,
    high_error_minutes: float,
    duration_outlier_minutes: float,
    bridge_status: str,
) -> dict[str, Any]:
    gap_counts: Counter[str] = Counter()
    for row in rows:
        gap_counts.update([gap for gap in row.get("suspected_gap", "").split(";") if gap])
    errors = _numbers(rows, "active_error_minutes")
    top_lanes = [
        {"gap": gap, "rows": count}
        for gap, count in gap_counts.most_common(3)
    ]
    return {
        "priority_rows": len(rows),
        "high_error_minutes": high_error_minutes,
        "duration_outlier_minutes": duration_outlier_minutes,
        "shared_key_bridge_status": bridge_status,
        "mean_active_error_minutes": _round_or_none(mean(errors) if errors else None),
        "max_active_error_minutes": _round_or_none(max(errors) if errors else None),
        "gap_counts": dict(gap_counts.most_common()),
        "top_feature_lanes": top_lanes,
        "top_feeders": dict(Counter(row.get("feeder") or "<blank>" for row in rows).most_common(8)),
        "top_devices": dict(Counter(row.get("device_id") or "<blank>" for row in rows).most_common(8)),
        "lifecycle_bridge_status_counts": dict(Counter(row.get("lifecycle_bridge_status") or "<blank>" for row in rows).most_common()),
        "recommendation": _summary_recommendation(gap_counts, bridge_status),
    }


def _render_markdown(
    summary: dict[str, Any],
    rows: list[dict[str, str]],
    review_template_output: str | Path | None,
) -> str:
    lines = [
        "# Long-Outage Lifecycle/Cause Evidence Pack",
        "",
        "This pack prioritizes shadow ETR misses that remain large after active AIS state is included. It is evidence-only and does not update model artifacts or customer notifications.",
        "",
        "## Summary",
        "",
        f"- Priority rows: {summary['priority_rows']}",
        f"- Mean active-state error: {_blank(summary['mean_active_error_minutes'])} min",
        f"- Max active-state error: {_blank(summary['max_active_error_minutes'])} min",
        f"- Shared-key bridge status: {summary['shared_key_bridge_status']}",
        "- Production send remains blocked.",
        "",
        "## Top Missing Feature Lanes",
        "",
        "| Feature lane | Rows |",
        "| --- | ---: |",
    ]
    for lane in summary["top_feature_lanes"]:
        lines.append(f"| {lane['gap']} | {lane['rows']} |")
    lines.extend(["", "## Top Feeders", "", "| Feeder | Rows |", "| --- | ---: |"])
    for feeder, count in summary["top_feeders"].items():
        lines.append(f"| {feeder} | {count} |")
    lines.extend(
        [
            "",
            "## Highest Priority Misses",
            "",
            "| Rank | Event ref | Time | Feeder | Device | Remaining | Active p50 | Error | Suspected gap |",
            "| ---: | --- | --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in rows[:20]:
        lines.append(
            "| {rank} | {ref} | {time} | {feeder} | {device} | {remaining} | {p50} | {error} | {gap} |".format(
                rank=row.get("priority_rank", ""),
                ref=row.get("event_ref", ""),
                time=row.get("event_time", ""),
                feeder=row.get("feeder", ""),
                device=row.get("device_id", ""),
                remaining=row.get("remaining_actual_minutes", ""),
                p50=row.get("active_p50", ""),
                error=row.get("active_error_minutes", ""),
                gap=row.get("suspected_gap", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Lifecycle/Truth Guardrails",
            "",
            "- AIS outage/restore remains the customer-facing truth source.",
            "- ReportPO/eRespond lifecycle fields are context only unless a shared key or owner-approved bridge exists.",
            "- Ticket close fields such as `cl_datetime` are blocked from truth usage.",
            "- Rows with `review_status` other than `approved` are not used as model features.",
            "",
            "## Recommendation",
            "",
            str(summary["recommendation"]),
            "",
            "## Outputs",
            "",
            f"- Review template: `{_blank(review_template_output)}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _recommended_action(gaps: list[str], lifecycle_status: str) -> str:
    if "duration_outlier" in gaps:
        return "Review cause/work type, field crew lifecycle, and restoration constraints before model tuning."
    if "missing_lifecycle" in gaps or lifecycle_status in {"shared_key_not_found", "missing_lifecycle_bridge"}:
        return "Find owner-approved event/job/ticket bridge or fill the lifecycle review template."
    if "missing_cause" in gaps:
        return "Fill source-owner approved outage cause and work type before training a challenger."
    if "device_history_too_sparse" in gaps:
        return "Collect more same-device/feed history or add topology/cause features."
    if "possible_topology_or_truth_review" in gaps:
        return "Review topology match and AIS interval semantics before using as model evidence."
    return "Keep in shadow review."


def _summary_recommendation(gap_counts: Counter[str], bridge_status: str) -> str:
    if not gap_counts:
        return "No high-error long-outage misses were available; continue shadow capture."
    if bridge_status != "shared_key_found" and gap_counts.get("missing_lifecycle", 0):
        return "Highest-value next step is owner-approved lifecycle/cause review for the top misses; current ReportPO/eRespond bridge is not sufficient for model training."
    if gap_counts.get("missing_cause", 0):
        return "Prioritize cause/work-type labels for top misses before building another model challenger."
    return "Use the reviewed context as shadow-only challenger features after approval."


def _cluster_key(row: dict[str, str]) -> str:
    feeder = row.get("feeder") or "unknown_feeder"
    device = row.get("device_id") or "unknown_device"
    return f"{feeder}|{device}"


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    if not Path(path).exists():
        return []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: str | Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def _numbers(rows: list[dict[str, str]], column: str) -> list[float]:
    return [value for row in rows if (value := _to_float(row.get(column))) is not None]


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: Any) -> int:
    try:
        return int(float(str(value or "0").strip()))
    except ValueError:
        return 0


def _round_or_none(value: float | None, *, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _dedupe(values: list[str]) -> list[str]:
    output = []
    seen = set()
    for value in values:
        if value and value not in seen:
            output.append(value)
            seen.add(value)
    return output


def _blank(value: Any) -> str:
    return "" if value is None else str(value)
