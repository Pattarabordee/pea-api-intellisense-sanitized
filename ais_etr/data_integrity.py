from __future__ import annotations

from collections import Counter
import csv
from pathlib import Path
from typing import Any, Iterable


DATA_INTEGRITY_COLUMNS = (
    "source_name",
    "record_ref",
    "event_time",
    "feeder",
    "device_id",
    "source_class",
    "truth_gate_status",
    "model_use",
    "duration_minutes",
    "risk_flags",
    "bridge_status",
    "final_decision",
    "recommended_action",
)

APPROVAL_TEMPLATE_COLUMNS = (
    "event_ref",
    "event_time",
    "feeder",
    "webex_device_id",
    "sfsd_candidate_device_id",
    "final_decision",
    "approval_scope",
    "review_status",
    "reviewer",
    "reviewed_at",
    "approved_context_fields",
    "notes",
)

REQUEST_PACK_COLUMNS = (
    "event_ref",
    "event_time",
    "feeder",
    "webex_device_id",
    "request_type",
    "final_decision",
    "recommended_question",
    "status",
    "owner_response",
)

REVIEW_STATUS_COLUMNS = (
    "source_name",
    "event_ref",
    "event_time",
    "feeder",
    "webex_device_id",
    "sfsd_candidate_device_id",
    "request_type",
    "review_status",
    "validation_status",
    "usable_as_context",
    "unresolved_blocker",
    "recommended_action",
)

AIS_TRUTH_SOURCE = "ais_site_power_status"
AIS_TRUTH_TARGET = "ais_site_actual_restoration_minutes"
AIS_TRUTH_DEFINITION = "AIS_POWER_RESTORE_TIME - AIS_POWER_OUTAGE_TIME"

BLOCKED_TRUTH_FIELDS = (
    "EVENT_END_TIME",
    "cl_datetime",
    "ticket close time",
    "EVENT_ETR_TIME",
    "historical ETR timestamp",
)


def build_data_integrity_audit(
    output_csv: str | Path,
    policy_markdown: str | Path,
    governance_markdown: str | Path,
    approval_template_csv: str | Path,
    request_pack_csv: str | Path,
    *,
    ais_truth_csv: str | Path = "runtime/ais_truth_latest_candidate.csv",
    shadow_comparison_csv: str | Path = "runtime/shadow_model_comparison_ais_remaining.csv",
    sfsd_evidence_csv: str | Path = "runtime/sfsd_long_outage_evidence.csv",
    sfsd_decision_csv: str | Path = "runtime/sfsd_gap_decision_pack.csv",
    reportpo_etr_csv: str | Path = "runtime/reportpo_etr_latest.csv",
    reportpo_feature_audit_csv: str | Path = "runtime/reportpo_feature_join_audit.csv",
    reportpo_lifecycle_audit_csv: str | Path = "runtime/reportpo_lifecycle_join_audit.csv",
) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    rows.extend(_ais_truth_rows(ais_truth_csv))
    rows.extend(_shadow_comparison_rows(shadow_comparison_csv))
    rows.extend(_sfsd_evidence_rows(sfsd_evidence_csv))
    sfsd_decision_rows = _read_csv(sfsd_decision_csv)
    rows.extend(_sfsd_decision_audit_rows(sfsd_decision_rows))
    rows.extend(_reportpo_etr_rows(reportpo_etr_csv))
    rows.extend(_reportpo_feature_rows(reportpo_feature_audit_csv))
    rows.extend(_reportpo_lifecycle_rows(reportpo_lifecycle_audit_csv))

    _write_csv(output_csv, DATA_INTEGRITY_COLUMNS, rows)
    approval_rows = _approval_template_rows(sfsd_decision_rows)
    request_rows = _request_pack_rows(sfsd_decision_rows)
    _write_csv(approval_template_csv, APPROVAL_TEMPLATE_COLUMNS, approval_rows)
    _write_csv(request_pack_csv, REQUEST_PACK_COLUMNS, request_rows)

    summary = _summary(rows, approval_rows, request_rows)
    Path(policy_markdown).parent.mkdir(parents=True, exist_ok=True)
    Path(policy_markdown).write_text(_render_policy_markdown(summary), encoding="utf-8-sig")
    Path(governance_markdown).parent.mkdir(parents=True, exist_ok=True)
    Path(governance_markdown).write_text(
        _render_governance_markdown(summary, approval_rows, request_rows),
        encoding="utf-8-sig",
    )
    return {
        **summary,
        "output_csv": str(output_csv),
        "policy_markdown": str(policy_markdown),
        "governance_markdown": str(governance_markdown),
        "approval_template_csv": str(approval_template_csv),
        "request_pack_csv": str(request_pack_csv),
    }


def build_truth_governance_review_status(
    approval_template_csv: str | Path,
    request_pack_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path,
) -> dict[str, Any]:
    """Validate owner-filled governance review files without changing them."""
    approval_rows = [_review_status_from_approval(row) for row in _read_csv(approval_template_csv)]
    request_rows = [_review_status_from_request(row) for row in _read_csv(request_pack_csv)]
    rows = approval_rows + request_rows
    _write_csv(output_csv, REVIEW_STATUS_COLUMNS, rows)

    summary = _review_status_summary(rows)
    output = Path(markdown_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_render_review_status_markdown(summary, rows), encoding="utf-8-sig")
    return {
        **summary,
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output),
        "approval_template_csv": str(approval_template_csv),
        "request_pack_csv": str(request_pack_csv),
    }


def truth_gate_for_row(row: dict[str, Any], *, source_name: str) -> dict[str, str]:
    """Classify a row before allowing it to be used as truth or model context."""
    source = _clean(row.get("truth_source") or row.get("source"))
    target = _clean(row.get("truth_target"))
    definition = _clean(row.get("truth_definition"))
    quality = _clean(row.get("truth_quality")).upper()
    duration = _to_float(row.get("actual_restoration_minutes") or row.get("duration_minutes"))
    flags = _duration_flags(duration)

    if source_name.startswith("ais") or source == AIS_TRUTH_SOURCE or target == AIS_TRUTH_TARGET:
        if source == AIS_TRUTH_SOURCE and target == AIS_TRUTH_TARGET and definition == AIS_TRUTH_DEFINITION:
            if duration is None or duration < 0:
                return _gate("ais_truth", "blocked_invalid_ais_truth", "blocked_for_model_training", duration, flags)
            if quality == "OK" and duration > 5:
                return _gate("ais_truth", "model_ready_truth", "eligible_truth", duration, flags)
            if duration <= 5 or quality == "REVIEW_SHORT":
                return _gate("ais_truth", "review_short_not_model_truth", "review_only", duration, flags)
            return _gate("ais_truth", "blocked_non_ok_ais_truth", "blocked_for_model_training", duration, flags)
        return _gate("blocked_truth_candidate", "blocked_unapproved_ais_semantics", "blocked_for_model_training", duration, flags)

    if source_name.startswith("reportpo"):
        flags = _dedupe([*flags, "event_etr_time_not_truth", "event_end_time_not_truth"])
        if duration is not None and duration <= 5:
            flags.append("pea_duration_le_5_kpi_risk")
        return _gate("pea_kpi_reporting_context", "context_only_not_customer_truth", "context_only", duration, flags)

    return _gate("blocked_truth_candidate", "blocked_unknown_truth_source", "blocked_for_model_training", duration, flags)


def _ais_truth_rows(path: str | Path) -> list[dict[str, str]]:
    rows = []
    for row in _read_csv(path):
        gate = truth_gate_for_row(row, source_name="ais_truth")
        rows.append(
            _audit_row(
                source_name="ais_truth",
                record_ref=f"source_row:{row.get('source_row_number') or ''}",
                event_time=row.get("outage_start_time", ""),
                feeder=row.get("feeder", ""),
                device_id=row.get("device_id", ""),
                bridge_status="direct_ais_source",
                final_decision=gate["truth_gate_status"],
                recommended_action=_action_for_gate(gate["truth_gate_status"]),
                **gate,
            )
        )
    return rows


def _shadow_comparison_rows(path: str | Path) -> list[dict[str, str]]:
    output = []
    for row in _read_csv(path):
        actual = _to_float(row.get("actual_restoration_minutes"))
        if actual is None:
            continue
        flags = _duration_flags(actual)
        if actual > 5 and _clean(row.get("truth_source")):
            gate = _gate("ais_truth", "shadow_evaluation_truth", "shadow_evaluation_eligible", actual, flags)
        else:
            gate = _gate("ais_truth", "shadow_review_not_model_gate", "review_only", actual, flags)
        output.append(
            _audit_row(
                source_name="shadow_ais_remaining",
                record_ref=row.get("webex_message_ref") or row.get("event_id") or "",
                event_time=row.get("event_time", ""),
                feeder=row.get("feeder", ""),
                device_id=row.get("device_id", ""),
                bridge_status=row.get("match_level", ""),
                final_decision=gate["truth_gate_status"],
                recommended_action=_action_for_gate(gate["truth_gate_status"]),
                **gate,
            )
        )
    return output


def _sfsd_evidence_rows(path: str | Path) -> list[dict[str, str]]:
    output = []
    for row in _read_csv(path):
        duration = _to_float(row.get("sfsd_duration_minutes"))
        flags = _duration_flags(duration)
        pattern = row.get("pea_ais_pattern") or ""
        if pattern == "pea_momentary_or_short_ais_long":
            flags = _dedupe([*flags, "pea_short_ais_long", "kpi_adjustment_risk"])
            gate = _gate("pea_kpi_reporting_context", "context_only_kpi_risk", "blocked_as_truth", duration, flags)
        else:
            gate = _gate("pea_operational_context", "context_only_not_customer_truth", "context_only", duration, flags)
        output.append(
            _audit_row(
                source_name="sfsd_long_outage_evidence",
                record_ref=row.get("event_ref", ""),
                event_time=row.get("event_time", ""),
                feeder=row.get("feeder", ""),
                device_id=row.get("device_id", ""),
                bridge_status=row.get("sfsd_match_level", ""),
                final_decision=pattern,
                recommended_action="Use as SFSD context only; AIS outage/restore remains truth.",
                **gate,
            )
        )
    return output


def _sfsd_decision_audit_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    output = []
    for row in rows:
        decision = row.get("final_decision") or ""
        if decision == "topology_supported_owner_approval_needed":
            gate = _gate("pea_operational_context", "owner_approval_required", "candidate_context_after_owner_approval", None, [])
        else:
            gate = _gate("blocked_truth_candidate", "bridge_rejected_or_unusable", "blocked_for_model_training", None, [])
        output.append(
            _audit_row(
                source_name="sfsd_gap_decision",
                record_ref=row.get("event_ref", ""),
                event_time=row.get("event_time", ""),
                feeder=row.get("feeder", ""),
                device_id=row.get("webex_device_id", ""),
                bridge_status=row.get("resolution_status", ""),
                final_decision=decision,
                recommended_action=row.get("final_action") or _action_for_gate(gate["truth_gate_status"]),
                **gate,
            )
        )
    return output


def _reportpo_etr_rows(path: str | Path) -> list[dict[str, str]]:
    output = []
    for row in _read_csv(path):
        gate = truth_gate_for_row(row, source_name="reportpo_etr")
        flags = _dedupe([*gate["risk_flags"].split(";"), *_split_flags(row.get("truth_flags"))])
        gate["risk_flags"] = ";".join(flags)
        output.append(
            _audit_row(
                source_name="reportpo_etr",
                record_ref=row.get("event_number", ""),
                event_time=row.get("event_start_time", ""),
                feeder=row.get("feeder", ""),
                device_id=row.get("device_id", ""),
                bridge_status=row.get("truth_target", ""),
                final_decision=gate["truth_gate_status"],
                recommended_action="ReportPO first-restore may be context only; do not use close/ETR fields as AIS truth.",
                **gate,
            )
        )
    return output


def _reportpo_feature_rows(path: str | Path) -> list[dict[str, str]]:
    output = []
    for row in _read_csv(path):
        status = row.get("match_status") or ""
        if status == "matched":
            gate = _gate("pea_operational_context", "feature_context_only_pending_bridge", "context_only", None, _split_flags(row.get("feature_flags")))
        else:
            gate = _gate("pea_operational_context", "feature_context_unavailable", "not_available", None, [])
        output.append(
            _audit_row(
                source_name="reportpo_feature_join",
                record_ref=row.get("webex_message_id", "")[:18],
                event_time=row.get("webex_event_time", ""),
                feeder=row.get("webex_feeder", ""),
                device_id=row.get("webex_device_id", ""),
                bridge_status=status,
                final_decision=gate["truth_gate_status"],
                recommended_action="Use cause/work-type context only after bridge approval.",
                **gate,
            )
        )
    return output


def _reportpo_lifecycle_rows(path: str | Path) -> list[dict[str, str]]:
    output = []
    for row in _read_csv(path):
        flags = _split_flags(row.get("lifecycle_flags"))
        if _clean(row.get("cl_datetime")):
            flags = _dedupe([*flags, "cl_datetime_not_truth", "ticket_close_time_not_truth"])
            gate = _gate("blocked_truth_candidate", "blocked_close_time_not_truth", "blocked_for_model_training", None, flags)
        elif row.get("match_status") == "matched":
            gate = _gate("pea_operational_context", "lifecycle_context_only_pending_bridge", "context_only", None, flags)
        else:
            gate = _gate("pea_operational_context", "lifecycle_context_unavailable", "not_available", None, flags)
        output.append(
            _audit_row(
                source_name="reportpo_lifecycle_join",
                record_ref=row.get("webex_message_id", "")[:18],
                event_time=row.get("webex_event_time", ""),
                feeder=row.get("webex_feeder", ""),
                device_id=row.get("webex_device_id", ""),
                bridge_status=row.get("match_status", ""),
                final_decision=gate["truth_gate_status"],
                recommended_action=_action_for_gate(gate["truth_gate_status"]),
                **gate,
            )
        )
    return output


def _approval_template_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    output = []
    for row in rows:
        if row.get("final_decision") != "topology_supported_owner_approval_needed":
            continue
        output.append(
            {
                "event_ref": row.get("event_ref", ""),
                "event_time": row.get("event_time", ""),
                "feeder": row.get("feeder", ""),
                "webex_device_id": row.get("webex_device_id", ""),
                "sfsd_candidate_device_id": row.get("sfsd_candidate_device_id", ""),
                "final_decision": row.get("final_decision", ""),
                "approval_scope": "use_sfsd_lifecycle_cause_context_only_not_truth",
                "review_status": "pending",
                "reviewer": "",
                "reviewed_at": "",
                "approved_context_fields": "",
                "notes": "Approve only if topology owner confirms both devices represent the same AIS affected path.",
            }
        )
    return output


def _request_pack_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    output = []
    for row in rows:
        decision = row.get("final_decision") or ""
        if decision == "topology_supported_owner_approval_needed":
            continue
        request_type = "exact_sfsd_event_key" if "bridge" in decision or "reject" in decision else "missing_source_or_ais_side_review"
        output.append(
            {
                "event_ref": row.get("event_ref", ""),
                "event_time": row.get("event_time", ""),
                "feeder": row.get("feeder", ""),
                "webex_device_id": row.get("webex_device_id", ""),
                "request_type": request_type,
                "final_decision": decision,
                "recommended_question": _owner_question(row),
                "status": "open",
                "owner_response": "",
            }
        )
    return output


def _owner_question(row: dict[str, str]) -> str:
    decision = row.get("final_decision") or ""
    if decision == "reject_sfsd_candidate_webex_device_confirmed":
        return "Please provide the exact SFSD/ReportPO event key for the Webex device; current SFSD candidate device is rejected by source trace."
    if decision == "do_not_bridge_time_gap_too_large":
        return "Please confirm whether there is an SFSD/ReportPO event within the bridge window for this Webex event, or mark it AIS-side/source-missing."
    return "Please provide owner-approved bridge/context evidence before this row is used for model features."


def _review_status_from_approval(row: dict[str, str]) -> dict[str, str]:
    status = (_clean(row.get("review_status")).lower() or "pending").replace(" ", "_")
    missing = []
    scope = _clean(row.get("approval_scope"))
    if status == "approved":
        if scope != "use_sfsd_lifecycle_cause_context_only_not_truth":
            missing.append("approval_scope")
        if not _clean(row.get("reviewer")):
            missing.append("reviewer")
        if not _clean(row.get("reviewed_at")):
            missing.append("reviewed_at")
        if not _clean(row.get("approved_context_fields")):
            missing.append("approved_context_fields")
        if missing:
            validation_status = "invalid_approved_missing_" + "_".join(missing)
            usable = "false"
            unresolved = "true"
            action = "Fix approved row metadata before using SFSD context; never use it as truth."
        else:
            validation_status = "approved_context_only"
            usable = "true"
            unresolved = "false"
            action = "Use approved SFSD lifecycle/cause fields as context only; AIS outage/restore remains truth."
    elif status in {"pending", "open", ""}:
        validation_status = "pending_owner_approval"
        usable = "false"
        unresolved = "true"
        action = "Topology owner must approve or reject before this row can affect model features."
    elif status in {"rejected", "not_approved"}:
        validation_status = "rejected_by_owner"
        usable = "false"
        unresolved = "false"
        action = "Do not use this SFSD candidate; keep AIS truth and source trace evidence."
    else:
        validation_status = "invalid_review_status"
        usable = "false"
        unresolved = "true"
        action = "Set review_status to pending, approved, or rejected."

    return _review_status_row(
        source_name="sfsd_owner_approval",
        event_ref=row.get("event_ref", ""),
        event_time=row.get("event_time", ""),
        feeder=row.get("feeder", ""),
        webex_device_id=row.get("webex_device_id", ""),
        sfsd_candidate_device_id=row.get("sfsd_candidate_device_id", ""),
        request_type="owner_approval",
        review_status=status,
        validation_status=validation_status,
        usable_as_context=usable,
        unresolved_blocker=unresolved,
        recommended_action=action,
    )


def _review_status_from_request(row: dict[str, str]) -> dict[str, str]:
    status = (_clean(row.get("status")).lower() or "open").replace(" ", "_")
    has_response = bool(_clean(row.get("owner_response")))
    if status in {"closed", "resolved", "answered"}:
        if has_response:
            validation_status = "source_request_resolved"
            unresolved = "false"
            action = "Use owner response only as bridge/context evidence; do not convert PEA close times into truth."
        else:
            validation_status = "invalid_resolved_missing_owner_response"
            unresolved = "true"
            action = "Add owner_response or change status back to open."
    elif status in {"open", "pending", ""}:
        validation_status = "source_request_open"
        unresolved = "true"
        action = "Request exact SFSD/ReportPO event key or source-missing confirmation from the data owner."
    elif status in {"rejected", "not_available", "source_missing"}:
        if has_response:
            validation_status = "source_request_closed_no_bridge"
            unresolved = "false"
            action = "Keep row out of PEA context bridge; document owner response as blocker evidence."
        else:
            validation_status = "invalid_closed_missing_owner_response"
            unresolved = "true"
            action = "Closed/rejected request needs owner_response explaining why no bridge is available."
    else:
        validation_status = "invalid_request_status"
        unresolved = "true"
        action = "Set status to open, resolved, closed, rejected, not_available, or source_missing."

    return _review_status_row(
        source_name="sfsd_source_request",
        event_ref=row.get("event_ref", ""),
        event_time=row.get("event_time", ""),
        feeder=row.get("feeder", ""),
        webex_device_id=row.get("webex_device_id", ""),
        sfsd_candidate_device_id="",
        request_type=row.get("request_type", ""),
        review_status=status,
        validation_status=validation_status,
        usable_as_context="false",
        unresolved_blocker=unresolved,
        recommended_action=action,
    )


def _review_status_row(
    *,
    source_name: str,
    event_ref: str,
    event_time: str,
    feeder: str,
    webex_device_id: str,
    sfsd_candidate_device_id: str,
    request_type: str,
    review_status: str,
    validation_status: str,
    usable_as_context: str,
    unresolved_blocker: str,
    recommended_action: str,
) -> dict[str, str]:
    return {
        "source_name": source_name,
        "event_ref": _safe_ref(event_ref),
        "event_time": event_time,
        "feeder": feeder,
        "webex_device_id": webex_device_id,
        "sfsd_candidate_device_id": sfsd_candidate_device_id,
        "request_type": request_type,
        "review_status": review_status,
        "validation_status": validation_status,
        "usable_as_context": usable_as_context,
        "unresolved_blocker": unresolved_blocker,
        "recommended_action": recommended_action,
    }


def _review_status_summary(rows: list[dict[str, str]]) -> dict[str, Any]:
    validation = Counter(row["validation_status"] for row in rows)
    by_source = Counter(row["source_name"] for row in rows)
    unresolved = sum(1 for row in rows if row["unresolved_blocker"] == "true")
    invalid = sum(1 for row in rows if row["validation_status"].startswith("invalid"))
    approved_context = sum(1 for row in rows if row["usable_as_context"] == "true")
    pending_approvals = validation.get("pending_owner_approval", 0)
    open_requests = validation.get("source_request_open", 0)
    return {
        "review_rows": len(rows),
        "validation_status_counts": dict(validation.most_common()),
        "source_counts": dict(by_source.most_common()),
        "approved_context_rows": approved_context,
        "pending_approval_rows": pending_approvals,
        "open_source_request_rows": open_requests,
        "invalid_review_rows": invalid,
        "unresolved_blocker_rows": unresolved,
        "governance_review_blocked": unresolved > 0,
    }


def _render_review_status_markdown(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Truth Governance Review Status",
        "",
        "This report validates reviewer-filled SFSD approval/request files. It does not approve any row by itself.",
        "",
        "## Summary",
        "",
        f"- Review rows: {summary['review_rows']}",
        f"- Approved context-only rows: {summary['approved_context_rows']}",
        f"- Pending approval rows: {summary['pending_approval_rows']}",
        f"- Open source request rows: {summary['open_source_request_rows']}",
        f"- Invalid review rows: {summary['invalid_review_rows']}",
        f"- Unresolved blocker rows: {summary['unresolved_blocker_rows']}",
        f"- Governance review blocked: `{str(summary['governance_review_blocked']).lower()}`",
        "",
        "## Validation Status",
        "",
        "| Status | Rows |",
        "| --- | ---: |",
    ]
    for key, value in summary["validation_status_counts"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Rows Needing Action",
            "",
            "| Source | Event | Feeder | Webex device | Candidate | Status | Action |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in [item for item in rows if item["unresolved_blocker"] == "true"][:30]:
        lines.append(
            f"| `{row['source_name']}` | `{row['event_ref']}` | {row['feeder']} | {row['webex_device_id']} | "
            f"{row['sfsd_candidate_device_id']} | `{row['validation_status']}` | {row['recommended_action']} |"
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Approved SFSD rows can only become lifecycle/cause context, not restoration truth.",
            "- AIS outage/restore remains the customer-facing actual restoration source.",
            "- `EVENT_END_TIME`, `cl_datetime`, ticket close time, and ETR timestamps remain blocked as truth.",
            "- This report excludes PEANO lists, raw Webex text, room IDs, tokens, and customer registration names.",
        ]
    )
    return "\n".join(lines) + "\n"


def _summary(
    rows: list[dict[str, str]],
    approval_rows: list[dict[str, str]],
    request_rows: list[dict[str, str]],
) -> dict[str, Any]:
    source_class = Counter(row["source_class"] for row in rows)
    gate = Counter(row["truth_gate_status"] for row in rows)
    model_use = Counter(row["model_use"] for row in rows)
    flags = Counter(flag for row in rows for flag in row.get("risk_flags", "").split(";") if flag)
    return {
        "audit_rows": len(rows),
        "source_class_counts": dict(source_class.most_common()),
        "truth_gate_counts": dict(gate.most_common()),
        "model_use_counts": dict(model_use.most_common()),
        "risk_flag_counts": dict(flags.most_common(20)),
        "model_ready_truth_rows": model_use.get("eligible_truth", 0),
        "shadow_evaluation_truth_rows": model_use.get("shadow_evaluation_eligible", 0),
        "owner_approval_rows": len(approval_rows),
        "source_request_rows": len(request_rows),
        "production_blocked": True,
        "promotion_blockers": _promotion_blockers(model_use, approval_rows, request_rows),
    }


def _promotion_blockers(model_use: Counter[str], approval_rows: list[dict[str, str]], request_rows: list[dict[str, str]]) -> list[str]:
    blockers = ["production_send_disabled"]
    if approval_rows:
        blockers.append("owner_approval_pending")
    if request_rows:
        blockers.append("exact_sfsd_event_key_or_source_review_pending")
    if model_use.get("blocked_for_model_training", 0):
        blockers.append("blocked_truth_candidates_present")
    return blockers


def _render_policy_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# AIS ETR Data Integrity Policy",
        "",
        "This policy prevents PEA KPI/reporting data from being used as customer-facing AIS restoration truth without explicit approval.",
        "",
        "## Truth Source Gate",
        "",
        "| Source class | Model use | Policy |",
        "| --- | --- | --- |",
        "| `ais_truth` | truth/evaluation | Use only AIS outage/restore semantics: `AIS_POWER_RESTORE_TIME - AIS_POWER_OUTAGE_TIME` and sustained duration `>5` minutes. |",
        "| `pea_operational_context` | context only | Use for cause/lifecycle/topology after bridge or owner approval; never overwrite AIS truth. |",
        "| `pea_kpi_reporting_context` | context only | Treat as KPI-risk reporting data; do not use as customer restoration truth. |",
        "| `blocked_truth_candidate` | blocked | Exclude from model training/evaluation gates. |",
        "",
        "## Blocked Truth Fields",
        "",
    ]
    for field in BLOCKED_TRUTH_FIELDS:
        lines.append(f"- `{field}`")
    lines.extend(
        [
            "",
            "## KPI-Risk Signals",
            "",
            "- Duration `<=5` minutes or very near the 5-minute sustained-outage threshold.",
            "- PEA short/momentary event while AIS site remains in a long outage interval.",
            "- Event splits/merges or nearest SFSD candidate outside the bridge window.",
            "- Close-time or ETR-time fields used where first restoration is required.",
            "",
            "## Current Audit Snapshot",
            "",
            f"- Audit rows: {summary['audit_rows']}",
            f"- AIS model-ready truth rows: {summary['model_ready_truth_rows']}",
            f"- Shadow evaluation truth rows: {summary['shadow_evaluation_truth_rows']}",
            f"- Owner approval rows: {summary['owner_approval_rows']}",
            f"- Source request rows: {summary['source_request_rows']}",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_governance_markdown(
    summary: dict[str, Any],
    approval_rows: list[dict[str, str]],
    request_rows: list[dict[str, str]],
) -> str:
    lines = [
        "# Truth Governance Readiness",
        "",
        "## Status",
        "",
        "- Production send: blocked",
        "- Model promotion: blocked until owner approvals/source requests are resolved and AIS truth gate remains clean.",
        f"- Promotion blockers: `{';'.join(summary['promotion_blockers'])}`",
        "",
        "## Source Classes",
        "",
        "| Source class | Rows |",
        "| --- | ---: |",
    ]
    for key, value in summary["source_class_counts"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(["", "## Model Use", "", "| Model use | Rows |", "| --- | ---: |"])
    for key, value in summary["model_use_counts"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(["", "## Open Approval Rows", "", "| Event | Feeder | Webex device | SFSD candidate | Status |", "| --- | --- | --- | --- | --- |"])
    for row in approval_rows[:20]:
        lines.append(
            f"| `{row['event_ref']}` | {row['feeder']} | {row['webex_device_id']} | {row['sfsd_candidate_device_id']} | {row['review_status']} |"
        )
    lines.extend(["", "## Source Requests", "", "| Event | Feeder | Device | Request type | Status |", "| --- | --- | --- | --- | --- |"])
    for row in request_rows[:20]:
        lines.append(f"| `{row['event_ref']}` | {row['feeder']} | {row['webex_device_id']} | {row['request_type']} | {row['status']} |")
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- AIS outage/restore remains the customer-facing truth source.",
            "- SFSD/ReportPO rows are context unless explicitly owner-approved.",
            "- This report excludes PEANO lists, raw Webex text, room IDs, tokens, and customer registration names.",
        ]
    )
    return "\n".join(lines) + "\n"


def _gate(
    source_class: str,
    truth_gate_status: str,
    model_use: str,
    duration: float | None,
    flags: Iterable[str],
) -> dict[str, str]:
    return {
        "source_class": source_class,
        "truth_gate_status": truth_gate_status,
        "model_use": model_use,
        "duration_minutes": "" if duration is None else _fmt(duration),
        "risk_flags": ";".join(_dedupe(flags)),
    }


def _audit_row(
    *,
    source_name: str,
    record_ref: str,
    event_time: str,
    feeder: str,
    device_id: str,
    source_class: str,
    truth_gate_status: str,
    model_use: str,
    duration_minutes: str,
    risk_flags: str,
    bridge_status: str,
    final_decision: str,
    recommended_action: str,
) -> dict[str, str]:
    return {
        "source_name": source_name,
        "record_ref": _safe_ref(record_ref),
        "event_time": event_time,
        "feeder": feeder,
        "device_id": device_id,
        "source_class": source_class,
        "truth_gate_status": truth_gate_status,
        "model_use": model_use,
        "duration_minutes": duration_minutes,
        "risk_flags": risk_flags,
        "bridge_status": bridge_status,
        "final_decision": final_decision,
        "recommended_action": recommended_action,
    }


def _action_for_gate(status: str) -> str:
    if status in {"model_ready_truth", "shadow_evaluation_truth"}:
        return "Allowed for AIS truth/evaluation gate."
    if "short" in status:
        return "Keep in review queue; do not use for sustained-outage model gate."
    if "close_time" in status:
        return "Do not use ticket close/admin close time as restoration truth."
    if "owner" in status:
        return "Owner approval required before use as model context."
    return "Keep blocked or context-only until source semantics are approved."


def _duration_flags(duration: float | None) -> list[str]:
    if duration is None:
        return ["missing_duration"]
    flags = []
    if duration < 0:
        flags.append("negative_duration")
    if duration <= 1:
        flags.append("momentary_micro_review")
    elif duration <= 5:
        flags.append("short_interruption_review")
    if abs(duration - 5.0) <= 1.0:
        flags.append("near_5min_threshold")
    if duration > 1440:
        flags.append("over_24h_review")
    return flags


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


def _to_float(value: Any) -> float | None:
    text = _clean(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _split_flags(value: Any) -> list[str]:
    return [part.strip() for part in _clean(value).split(";") if part.strip()]


def _dedupe(values: Iterable[str]) -> list[str]:
    output = []
    seen = set()
    for value in values:
        if value and value not in seen:
            output.append(value)
            seen.add(value)
    return output


def _safe_ref(value: Any) -> str:
    text = _clean(value)
    return text[:80]


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def _fmt(value: float) -> str:
    return str(round(value, 3)).rstrip("0").rstrip(".") if value % 1 else str(round(value, 1))
