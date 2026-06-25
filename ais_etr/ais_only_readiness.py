from __future__ import annotations

from collections import Counter
import csv
import hashlib
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from .truth_quality import GATE_COVERAGE_MAX, GATE_COVERAGE_MIN, GATE_Q50_MAE_MAX, MIN_SUSTAINED_ROWS_FOR_TUNING


AIS_TRUTH_SOURCE = "ais_site_power_status"

READINESS_COLUMNS = (
    "source_lane",
    "event_ref",
    "event_time",
    "district",
    "feeder",
    "device_id",
    "source_name",
    "event_role",
    "match_level",
    "match_confidence",
    "affected_count",
    "actual_restoration_minutes",
    "truth_source",
    "sustained_outage_eligible",
    "model_metric_included",
    "model_feature_allowed",
    "current_p50",
    "current_q10",
    "current_q90",
    "current_absolute_error",
    "current_covered_q10_q90",
    "quarantine_reason",
    "recommended_action",
)

QUARANTINE_COLUMNS = (
    "source_name",
    "event_ref",
    "event_time",
    "feeder",
    "device_id",
    "pea_candidate_id",
    "match_status",
    "quarantine_reason",
    "approval_status",
    "model_metric_included",
    "model_feature_allowed",
    "recommended_action",
)


def build_ais_only_readiness(
    shadow_comparison_csv: str | Path,
    governance_status_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path,
    quarantine_output_csv: str | Path,
    *,
    reportpo_feature_audit_csv: str | Path = "runtime/reportpo_feature_join_audit.csv",
    reportpo_lifecycle_audit_csv: str | Path = "runtime/reportpo_lifecycle_join_audit.csv",
    sfsd_evidence_csv: str | Path = "runtime/sfsd_long_outage_evidence.csv",
    sfsd_decision_csv: str | Path = "runtime/sfsd_gap_decision_pack.csv",
    min_duration_minutes: float = 5.0,
) -> dict[str, Any]:
    governance_rows = _read_csv(governance_status_csv)
    approved_refs = {row.get("event_ref", "") for row in governance_rows if _is_approved_context(row)}
    comparison_rows = _read_csv(shadow_comparison_csv)

    readiness_rows = [
        _readiness_from_shadow(row, min_duration_minutes=min_duration_minutes)
        for row in comparison_rows
    ]
    approved_rows = [_readiness_from_approved_context(row) for row in governance_rows if _is_approved_context(row)]
    quarantine_rows = _build_quarantine_rows(
        governance_rows,
        approved_refs,
        reportpo_feature_audit_csv=reportpo_feature_audit_csv,
        reportpo_lifecycle_audit_csv=reportpo_lifecycle_audit_csv,
        sfsd_evidence_csv=sfsd_evidence_csv,
        sfsd_decision_csv=sfsd_decision_csv,
    )
    readiness_rows.extend(approved_rows)
    readiness_rows.extend(_readiness_from_quarantine(row) for row in quarantine_rows)

    _write_csv(output_csv, READINESS_COLUMNS, readiness_rows)
    _write_csv(quarantine_output_csv, QUARANTINE_COLUMNS, quarantine_rows)
    summary = _summary(readiness_rows, quarantine_rows)
    output = Path(markdown_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_render_markdown(summary, readiness_rows, quarantine_rows), encoding="utf-8-sig")
    return {
        **summary,
        "shadow_comparison_csv": str(shadow_comparison_csv),
        "governance_status_csv": str(governance_status_csv),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output),
        "quarantine_output_csv": str(quarantine_output_csv),
        "reportpo_feature_audit_csv": str(reportpo_feature_audit_csv),
        "reportpo_lifecycle_audit_csv": str(reportpo_lifecycle_audit_csv),
        "sfsd_evidence_csv": str(sfsd_evidence_csv),
        "sfsd_decision_csv": str(sfsd_decision_csv),
    }


def _readiness_from_shadow(row: dict[str, str], *, min_duration_minutes: float) -> dict[str, str]:
    actual = _to_float(row.get("actual_restoration_minutes"))
    affected = _to_float(row.get("affected_count")) or 0
    has_ais_truth = row.get("truth_source") == AIS_TRUTH_SOURCE
    eligible = bool(has_ais_truth and actual is not None and actual > min_duration_minutes and affected > 0 and row.get("match_level"))
    if eligible:
        lane = "ais_truth_matched"
        quarantine_reason = ""
        action = "Use in AIS-only sustained evaluation and challenger training candidates."
    else:
        lane = "webex_trigger_no_ais_truth"
        quarantine_reason = _shadow_quarantine_reason(row, actual, min_duration_minutes)
        action = "Keep as WebEx trigger/device evidence only; do not calculate MAE or train on it."
    return {
        "source_lane": lane,
        "event_ref": row.get("webex_message_ref", ""),
        "event_time": row.get("event_time", ""),
        "district": row.get("district", ""),
        "feeder": row.get("feeder", ""),
        "device_id": row.get("device_id", ""),
        "source_name": "webex_shadow",
        "event_role": "runtime_trigger",
        "match_level": row.get("match_level", ""),
        "match_confidence": row.get("match_confidence", ""),
        "affected_count": row.get("affected_count", ""),
        "actual_restoration_minutes": _fmt(actual),
        "truth_source": row.get("truth_source", ""),
        "sustained_outage_eligible": _bool(eligible),
        "model_metric_included": _bool(eligible),
        "model_feature_allowed": _bool(eligible),
        "current_p50": row.get("current_p50", ""),
        "current_q10": row.get("current_q10", ""),
        "current_q90": row.get("current_q90", ""),
        "current_absolute_error": row.get("current_absolute_error", "") if eligible else "",
        "current_covered_q10_q90": row.get("current_covered_q10_q90", "") if eligible else "",
        "quarantine_reason": quarantine_reason,
        "recommended_action": action,
    }


def _readiness_from_approved_context(row: dict[str, str]) -> dict[str, str]:
    return {
        "source_lane": "pea_context_approved",
        "event_ref": row.get("event_ref", ""),
        "event_time": row.get("event_time", ""),
        "district": "",
        "feeder": row.get("feeder", ""),
        "device_id": row.get("webex_device_id", ""),
        "source_name": row.get("source_name", ""),
        "event_role": "approved_context_only",
        "match_level": "owner_approved_context",
        "match_confidence": "",
        "affected_count": "",
        "actual_restoration_minutes": "",
        "truth_source": "pea_context_not_truth",
        "sustained_outage_eligible": "false",
        "model_metric_included": "false",
        "model_feature_allowed": "true",
        "current_p50": "",
        "current_q10": "",
        "current_q90": "",
        "current_absolute_error": "",
        "current_covered_q10_q90": "",
        "quarantine_reason": "",
        "recommended_action": "Use as lifecycle/cause context only; AIS outage/restore remains truth.",
    }


def _build_quarantine_rows(
    governance_rows: list[dict[str, str]],
    approved_refs: set[str],
    *,
    reportpo_feature_audit_csv: str | Path,
    reportpo_lifecycle_audit_csv: str | Path,
    sfsd_evidence_csv: str | Path,
    sfsd_decision_csv: str | Path,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    rows.extend(_quarantine_from_governance(row) for row in governance_rows if not _is_approved_context(row))
    rows.extend(
        _quarantine_from_reportpo(row, "reportpo_feature_join", approved_refs)
        for row in _read_csv(reportpo_feature_audit_csv)
        if _redacted_ref(row.get("webex_message_id")) not in approved_refs
    )
    rows.extend(
        _quarantine_from_reportpo(row, "reportpo_lifecycle_join", approved_refs)
        for row in _read_csv(reportpo_lifecycle_audit_csv)
        if _redacted_ref(row.get("webex_message_id")) not in approved_refs
    )
    rows.extend(
        _quarantine_from_sfsd_evidence(row, approved_refs)
        for row in _read_csv(sfsd_evidence_csv)
        if row.get("event_ref", "") not in approved_refs
    )
    rows.extend(
        _quarantine_from_sfsd_decision(row, approved_refs)
        for row in _read_csv(sfsd_decision_csv)
        if row.get("event_ref", "") not in approved_refs
    )
    return rows


def _quarantine_from_governance(row: dict[str, str]) -> dict[str, str]:
    return _quarantine_row(
        source_name=row.get("source_name", ""),
        event_ref=row.get("event_ref", ""),
        event_time=row.get("event_time", ""),
        feeder=row.get("feeder", ""),
        device_id=row.get("webex_device_id", ""),
        pea_candidate_id=row.get("sfsd_candidate_device_id", ""),
        match_status=row.get("validation_status", ""),
        quarantine_reason=_governance_reason(row),
        approval_status=row.get("review_status", ""),
        recommended_action=row.get("recommended_action", "") or "Keep out of model metrics/features until review is resolved.",
    )


def _quarantine_from_reportpo(row: dict[str, str], source_name: str, approved_refs: set[str]) -> dict[str, str]:
    event_ref = _redacted_ref(row.get("webex_message_id"))
    status = row.get("match_status", "")
    candidate = row.get("reportpo_device_id") or row.get("po_device_id") or ""
    return _quarantine_row(
        source_name=source_name,
        event_ref=event_ref,
        event_time=row.get("webex_event_time", ""),
        feeder=row.get("webex_feeder", ""),
        device_id=row.get("webex_device_id", ""),
        pea_candidate_id=candidate,
        match_status=status,
        quarantine_reason=_pea_match_reason(status, event_ref in approved_refs),
        approval_status="not_owner_approved",
        recommended_action="Keep as PEA audit/context pool only; do not use for AIS truth, MAE, coverage, or model gate.",
    )


def _quarantine_from_sfsd_evidence(row: dict[str, str], approved_refs: set[str]) -> dict[str, str]:
    event_ref = row.get("event_ref", "")
    status = row.get("sfsd_match_status", "")
    return _quarantine_row(
        source_name="sfsd_long_outage_evidence",
        event_ref=event_ref,
        event_time=row.get("event_time", ""),
        feeder=row.get("feeder", ""),
        device_id=row.get("device_id", ""),
        pea_candidate_id=row.get("sfsd_device_id", ""),
        match_status=status,
        quarantine_reason=_pea_match_reason(status, event_ref in approved_refs),
        approval_status="not_owner_approved",
        recommended_action="Use for root-cause review only until AIS/owner bridge is approved.",
    )


def _quarantine_from_sfsd_decision(row: dict[str, str], approved_refs: set[str]) -> dict[str, str]:
    event_ref = row.get("event_ref", "")
    decision = row.get("final_decision", "")
    return _quarantine_row(
        source_name="sfsd_gap_decision",
        event_ref=event_ref,
        event_time=row.get("event_time", ""),
        feeder=row.get("feeder", ""),
        device_id=row.get("webex_device_id", ""),
        pea_candidate_id=row.get("sfsd_candidate_device_id", ""),
        match_status=decision,
        quarantine_reason=_decision_reason(decision, event_ref in approved_refs),
        approval_status="not_owner_approved",
        recommended_action=row.get("final_action", "") or "Keep blocked until source owner resolves the bridge decision.",
    )


def _readiness_from_quarantine(row: dict[str, str]) -> dict[str, str]:
    return {
        "source_lane": "pea_quarantined",
        "event_ref": row.get("event_ref", ""),
        "event_time": row.get("event_time", ""),
        "district": "",
        "feeder": row.get("feeder", ""),
        "device_id": row.get("device_id", ""),
        "source_name": row.get("source_name", ""),
        "event_role": "pea_context_quarantine",
        "match_level": row.get("match_status", ""),
        "match_confidence": "",
        "affected_count": "",
        "actual_restoration_minutes": "",
        "truth_source": "pea_context_not_truth",
        "sustained_outage_eligible": "false",
        "model_metric_included": "false",
        "model_feature_allowed": "false",
        "current_p50": "",
        "current_q10": "",
        "current_q90": "",
        "current_absolute_error": "",
        "current_covered_q10_q90": "",
        "quarantine_reason": row.get("quarantine_reason", ""),
        "recommended_action": row.get("recommended_action", ""),
    }


def _quarantine_row(
    *,
    source_name: str,
    event_ref: str,
    event_time: str,
    feeder: str,
    device_id: str,
    pea_candidate_id: str,
    match_status: str,
    quarantine_reason: str,
    approval_status: str,
    recommended_action: str,
) -> dict[str, str]:
    return {
        "source_name": source_name,
        "event_ref": event_ref,
        "event_time": event_time,
        "feeder": feeder,
        "device_id": device_id,
        "pea_candidate_id": pea_candidate_id,
        "match_status": match_status,
        "quarantine_reason": quarantine_reason,
        "approval_status": approval_status,
        "model_metric_included": "false",
        "model_feature_allowed": "false",
        "recommended_action": recommended_action,
    }


def _summary(readiness_rows: list[dict[str, str]], quarantine_rows: list[dict[str, str]]) -> dict[str, Any]:
    lane_counts = Counter(row["source_lane"] for row in readiness_rows)
    quarantine_reasons = Counter(row.get("quarantine_reason", "") for row in quarantine_rows)
    quarantine_sources = Counter(row.get("source_name", "") for row in quarantine_rows)
    metric_rows = [row for row in readiness_rows if row.get("source_lane") == "ais_truth_matched"]
    mae = _mean_number(metric_rows, "current_absolute_error")
    coverage = _coverage(metric_rows, "current_covered_q10_q90")
    return {
        "readiness_rows": len(readiness_rows),
        "lane_counts": dict(lane_counts.most_common()),
        "ais_truth_matched_rows": lane_counts.get("ais_truth_matched", 0),
        "webex_trigger_no_ais_truth_rows": lane_counts.get("webex_trigger_no_ais_truth", 0),
        "pea_context_approved_rows": lane_counts.get("pea_context_approved", 0),
        "pea_quarantined_rows": lane_counts.get("pea_quarantined", 0),
        "pea_quarantine_sources": dict(quarantine_sources.most_common()),
        "pea_quarantine_reasons": dict(quarantine_reasons.most_common()),
        "current_q50_mae_minutes": mae,
        "current_q10_q90_coverage": coverage,
        "minimum_sustained_rows_for_tuning": MIN_SUSTAINED_ROWS_FOR_TUNING,
        "q50_mae_gate_minutes": GATE_Q50_MAE_MAX,
        "q10_q90_coverage_gate_min": GATE_COVERAGE_MIN,
        "q10_q90_coverage_gate_max": GATE_COVERAGE_MAX,
        "model_gate_status": _model_gate_status(len(metric_rows), mae, coverage),
        "production_send_status": "blocked",
    }


def _render_markdown(
    summary: dict[str, Any],
    readiness_rows: list[dict[str, str]],
    quarantine_rows: list[dict[str, str]],
) -> str:
    lines = [
        "# AIS-Only Readiness",
        "",
        "This report separates AIS customer-facing truth from WebEx trigger evidence and PEA context/quarantine pools.",
        "",
        "## Lane Summary",
        "",
        "| Lane | Rows | Model metric? | Model feature? | Meaning |",
        "| --- | ---: | --- | --- | --- |",
        f"| `ais_truth_matched` | {summary['ais_truth_matched_rows']} | yes | candidate | AIS outage/restore truth, WebEx/topology matched, sustained `>5` minutes. |",
        f"| `webex_trigger_no_ais_truth` | {summary['webex_trigger_no_ais_truth_rows']} | no | no | WebEx trigger/device evidence only; no usable AIS truth label. |",
        f"| `pea_context_approved` | {summary['pea_context_approved_rows']} | no | yes | Owner-approved PEA lifecycle/cause context only; never restoration truth. |",
        f"| `pea_quarantined` | {summary['pea_quarantined_rows']} | no | no | PEA/SFSD/ReportPO rows without approved AIS bridge/context. |",
        "",
        "## AIS-Only Model Gate Snapshot",
        "",
        "| Metric | Value | Gate | Status |",
        "| --- | ---: | ---: | --- |",
        f"| AIS truth matched rows | {summary['ais_truth_matched_rows']} | >= {MIN_SUSTAINED_ROWS_FOR_TUNING} | {_row_status(summary['ais_truth_matched_rows'])} |",
        f"| Current q50 MAE minutes | {_blank(summary['current_q50_mae_minutes'])} | <= {GATE_Q50_MAE_MAX:g} | {_mae_status(summary['current_q50_mae_minutes'])} |",
        f"| Current q10-q90 coverage | {_blank(summary['current_q10_q90_coverage'])} | {GATE_COVERAGE_MIN:g}-{GATE_COVERAGE_MAX:g} | {_coverage_status(summary['current_q10_q90_coverage'])} |",
        f"| Model gate status | `{summary['model_gate_status']}` |  |  |",
        f"| Production send | `{summary['production_send_status']}` |  |  |",
        "",
        "## PEA Quarantine",
        "",
        "| Reason | Rows |",
        "| --- | ---: |",
    ]
    for reason, count in summary["pea_quarantine_reasons"].items():
        lines.append(f"| `{reason or '<blank>'}` | {count} |")
    lines.extend(["", "## Top Quarantined Devices", "", "| Source | Feeder | Device | Reason | Rows |", "| --- | --- | --- | --- | ---: |"])
    for item in _top_quarantine_devices(quarantine_rows):
        lines.append(
            f"| `{item['source_name']}` | {item['feeder']} | {item['device_id']} | `{item['quarantine_reason']}` | {item['rows']} |"
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- AIS outage/restore is the only customer-facing restoration truth in this lane.",
            "- WebEx remains a trigger and device evidence source, not an actual restoration label.",
            "- PEA/SFSD/ReportPO rows stay out of MAE, coverage, model gate, and training unless owner-approved as context.",
            "- This report excludes customer meter identifier lists, raw WebEx text, room IDs, tokens, secrets, and customer registration names.",
        ]
    )
    return "\n".join(lines) + "\n"


def _top_quarantine_devices(rows: list[dict[str, str]], limit: int = 12) -> list[dict[str, str]]:
    counts = Counter(
        (
            row.get("source_name", ""),
            row.get("feeder", ""),
            row.get("device_id", ""),
            row.get("quarantine_reason", ""),
        )
        for row in rows
    )
    return [
        {
            "source_name": key[0],
            "feeder": key[1],
            "device_id": key[2],
            "quarantine_reason": key[3],
            "rows": str(value),
        }
        for key, value in counts.most_common(limit)
    ]


def _shadow_quarantine_reason(row: dict[str, str], actual: float | None, min_duration_minutes: float) -> str:
    if row.get("truth_source") != AIS_TRUTH_SOURCE:
        return "missing_ais_truth"
    if actual is None:
        return "missing_actual_restoration_minutes"
    if actual <= min_duration_minutes:
        return "ais_truth_not_sustained"
    if not row.get("match_level"):
        return "missing_topology_match"
    if (_to_float(row.get("affected_count")) or 0) <= 0:
        return "no_affected_ais_assets"
    return "not_ais_only_metric_eligible"


def _governance_reason(row: dict[str, str]) -> str:
    status = row.get("validation_status", "")
    if status == "pending_owner_approval":
        return "owner_approval_pending"
    if status == "source_request_open":
        return "source_request_open"
    if status.startswith("invalid"):
        return "invalid_review_metadata"
    return "not_owner_approved"


def _pea_match_reason(status: str, approved: bool) -> str:
    if approved:
        return ""
    normalized = (status or "").strip().lower()
    if normalized in {"", "no_match"}:
        return "pea_no_match_or_unbridged"
    if normalized == "ambiguous":
        return "pea_ambiguous_unapproved"
    if normalized in {"matched", "event_number"}:
        return "pea_match_not_owner_approved"
    return "pea_context_not_owner_approved"


def _decision_reason(decision: str, approved: bool) -> str:
    if approved:
        return ""
    if decision == "topology_supported_owner_approval_needed":
        return "owner_approval_pending"
    if decision == "reject_sfsd_candidate_webex_device_confirmed":
        return "pea_bridge_rejected_by_source_trace"
    if decision == "do_not_bridge_time_gap_too_large":
        return "pea_bridge_time_gap_too_large"
    return "pea_context_not_owner_approved"


def _is_approved_context(row: dict[str, str]) -> bool:
    return row.get("usable_as_context") == "true" and row.get("unresolved_blocker") != "true"


def _model_gate_status(rows: int, mae: float | None, coverage: float | None) -> str:
    if rows < MIN_SUSTAINED_ROWS_FOR_TUNING:
        return "blocked_insufficient_ais_truth"
    if mae is None or coverage is None:
        return "blocked_missing_metrics"
    if mae <= GATE_Q50_MAE_MAX and GATE_COVERAGE_MIN <= coverage <= GATE_COVERAGE_MAX:
        return "shadow_gate_pass_candidate"
    return "blocked_metric_gate_failed"


def _row_status(rows: int) -> str:
    return "pass" if rows >= MIN_SUSTAINED_ROWS_FOR_TUNING else "insufficient"


def _mae_status(value: float | None) -> str:
    if value is None:
        return "not_available"
    return "pass" if value <= GATE_Q50_MAE_MAX else "fail"


def _coverage_status(value: float | None) -> str:
    if value is None:
        return "not_available"
    return "pass" if GATE_COVERAGE_MIN <= value <= GATE_COVERAGE_MAX else "fail"


def _mean_number(rows: list[dict[str, str]], column: str) -> float | None:
    values = [value for value in (_to_float(row.get(column)) for row in rows) if value is not None]
    return mean(values) if values else None


def _coverage(rows: list[dict[str, str]], column: str) -> float | None:
    values = [value for value in (_to_bool(row.get(column)) for row in rows) if value is not None]
    return sum(1 for value in values if value) / len(values) if values else None


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


def _redacted_ref(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("msg-") and len(text) <= 32:
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"msg-{digest}"


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


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return ""
    rounded = round(value, digits)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded).rstrip("0").rstrip(".")


def _blank(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return _fmt(value)
    return str(value)
