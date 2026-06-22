from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from .confidence_gate import build_shadow_send_eligibility
from .shadow_operations import build_green_gate_tracker


GAP_ACTION_COLUMNS = (
    "event_ref",
    "event_time",
    "feeder",
    "device_id",
    "source_lane",
    "eligibility_status",
    "stage1_class",
    "blocker_reasons",
    "owner_lane",
    "next_evidence_needed",
    "metric_use",
    "conversion_rank",
    "production_send",
)

APPROVAL_QUEUE_COLUMNS = (
    "rank",
    "event_ref",
    "event_time",
    "feeder",
    "device_id",
    "source_lane",
    "eligibility_status",
    "blocker_reasons",
    "next_evidence_needed",
    "conversion_rank",
    "production_send",
)

PENDING_WORKER_SQL = """
WITH latest_evidence AS (
    SELECT DISTINCT ON (request_id) request_id, trace_status
    FROM evidence_traces
    ORDER BY request_id, id DESC
),
latest_etr AS (
    SELECT DISTINCT ON (request_id) request_id, status
    FROM etr_candidates
    ORDER BY request_id, id DESC
)
SELECT coalesce(json_agg(row_to_json(t)), '[]'::json)
FROM (
    SELECT r.request_id, r.received_at, r.detected_at_original, r.meter_hash, r.meter_last4,
           r.province, r.district, r.subdistrict,
           coalesce(e.trace_status, '') AS trace_status,
           coalesce(et.status, '') AS etr_status
    FROM ais_inbound_requests r
    LEFT JOIN latest_evidence e ON e.request_id = r.request_id
    LEFT JOIN latest_etr et ON et.request_id = r.request_id
    WHERE coalesce(e.trace_status, '') = 'PENDING_WORKER'
       OR coalesce(et.status, '') = 'NOT_READY_FOR_AUTO_SEND'
    ORDER BY r.received_at ASC
    LIMIT {limit}
) t;
"""


def build_production_gate_packet(
    *,
    eligibility_csv: str | Path = "runtime/cloud_pilot/green_eligibility_report.csv",
    green_gate_json: str | Path = "runtime/cloud_pilot/green_eligibility_report.json",
    real_hit_status_json: str | Path = "runtime/production_cloud_real_hit_status.json",
    readiness_gate_json: str | Path = "runtime/production_path_readiness_gate.json",
    owner_approval_template: str | Path = "runtime/cloud_pilot/owner_approval_status.template.json",
    output_csv: str | Path = "runtime/cloud_pilot/production_gate_gap_actions.csv",
    markdown_output: str | Path = "runtime/cloud_pilot/production_gate_owner_packet.md",
    json_output: str | Path = "runtime/cloud_pilot/production_gate_owner_packet.json",
    min_green_rows: int = 30,
    top_blockers: int = 12,
) -> dict[str, Any]:
    rows = _read_csv(eligibility_csv)
    gate_payload = _read_json(green_gate_json)
    real_hit = _read_json(real_hit_status_json)
    readiness = _read_json(readiness_gate_json)
    owner_template = _read_json(owner_approval_template)
    if not rows:
        summary = {
            "generated_at": _utc_now_iso(),
            "status": "BLOCKED_MISSING_ELIGIBILITY",
            "mode": "shadow",
            "production_send": "blocked",
            "missing_inputs": [str(eligibility_csv)],
        }
        _write_json(json_output, summary)
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_missing_green_report(summary), encoding="utf-8")
        return summary

    gap_rows = [_gap_action_row(row) for row in rows]
    smoke_row = _smoke_demo_gap_row(real_hit)
    if smoke_row:
        gap_rows.append(smoke_row)
    gap_rows.sort(key=lambda row: (_to_int(row.get("conversion_rank")), row.get("event_time", "")), reverse=True)
    _write_csv(output_csv, GAP_ACTION_COLUMNS, gap_rows)

    status_counts = Counter(row.get("eligibility_status") or "<blank>" for row in rows)
    blocker_counts: Counter[str] = Counter()
    for row in rows:
        for blocker in _split_reasons(row.get("blocker_reasons")):
            blocker_counts[blocker] += 1
    owner_counts = Counter(row.get("owner_lane") or "<blank>" for row in gap_rows)
    green_gate = gate_payload.get("green_gate") if isinstance(gate_payload.get("green_gate"), dict) else {}
    eligibility = gate_payload.get("eligibility") if isinstance(gate_payload.get("eligibility"), dict) else {}
    green_rows = _to_int(green_gate.get("green_rows"))
    if green_rows is None:
        green_rows = status_counts.get("green_auto_candidate", 0)
    additional_needed = _to_int(green_gate.get("additional_green_rows_needed"))
    if additional_needed is None:
        additional_needed = max(min_green_rows - green_rows, 0)
    summary = {
        "generated_at": _utc_now_iso(),
        "status": "PASS",
        "mode": "shadow",
        "production_send": "blocked",
        "decision": "AUTO_ETR_NO_GO",
        "green_rows": green_rows,
        "min_green_rows": min_green_rows,
        "additional_green_rows_needed": additional_needed,
        "green_q50_mae_minutes": green_gate.get("green_q50_mae_minutes") or eligibility.get("green_q50_mae_minutes"),
        "green_q10_q90_coverage": green_gate.get("green_q10_q90_coverage") or eligibility.get("green_q10_q90_coverage"),
        "production_gate_status": green_gate.get("gate_status") or eligibility.get("production_gate_status") or "blocked",
        "eligibility_status_counts": dict(status_counts.most_common()),
        "blocker_reason_counts": dict(blocker_counts.most_common(top_blockers)),
        "owner_lane_counts": dict(owner_counts.most_common()),
        "cloud_status": {
            "api_base_url": real_hit.get("api_base_url", ""),
            "web_console_url": real_hit.get("web_console_url", ""),
            "health_status": real_hit.get("health_status", ""),
            "database": real_hit.get("database", ""),
            "total_requests": real_hit.get("total_requests", 0),
            "non_smoke_requests": real_hit.get("non_smoke_requests", 0),
            "latest_request": _safe_latest_request(real_hit.get("latest_request")),
        },
        "readiness": {
            "cloud_endpoint_ready": readiness.get("cloud_endpoint_ready", ""),
            "production_infra_ready": readiness.get("production_infra_ready", ""),
            "auto_etr_ready": readiness.get("auto_etr_ready", ""),
        },
        "owner_approvals": owner_template.get("approvals", {}),
        "outputs": {
            "gap_actions_csv": str(output_csv),
            "markdown": str(markdown_output),
            "json": str(json_output),
        },
        "guardrails": [
            "production_send_remains_blocked",
            "smoke_demo_cases_do_not_count_as_green_truth",
            "ais_outage_restore_remains_customer_facing_truth",
            "no_full_meter_peano_customer_identity_or_raw_webex_text",
        ],
    }
    _write_json(json_output, summary)
    Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
    Path(markdown_output).write_text(_render_production_gate_packet(summary), encoding="utf-8")
    return summary


def build_production_approval_evidence_pack(
    *,
    gap_actions_csv: str | Path = "runtime/cloud_pilot/production_gate_gap_actions.csv",
    owner_packet_json: str | Path = "runtime/cloud_pilot/production_gate_owner_packet.json",
    real_hit_status_json: str | Path = "runtime/production_cloud_real_hit_status.json",
    readiness_gate_json: str | Path = "runtime/production_path_readiness_gate.json",
    ais_truth_queue_output: str | Path = "runtime/cloud_pilot/green_owner_top30_ais_truth_queue.csv",
    topology_queue_output: str | Path = "runtime/cloud_pilot/green_owner_top30_topology_queue.csv",
    ops_report_output: str | Path = "runtime/cloud_pilot/ops_controls_blocker_report.md",
    ais_test_window_output: str | Path = "runtime/cloud_pilot/ais_real_cloud_test_window_request.md",
    markdown_output: str | Path = "runtime/cloud_pilot/production_approval_evidence_next_actions.md",
    json_output: str | Path = "runtime/cloud_pilot/production_approval_evidence_next_actions.json",
    top_n: int = 30,
) -> dict[str, Any]:
    gap_rows = _read_csv(gap_actions_csv)
    owner_packet = _read_json(owner_packet_json)
    real_hit = _read_json(real_hit_status_json)
    readiness = _read_json(readiness_gate_json)
    cloud_status = owner_packet.get("cloud_status") if isinstance(owner_packet.get("cloud_status"), dict) else {}
    latest_request = _safe_latest_request(real_hit.get("latest_request") or cloud_status.get("latest_request"))
    api_base_url = real_hit.get("api_base_url") or cloud_status.get("api_base_url") or "https://pea-api-intellisense-api.onrender.com"
    web_console_url = real_hit.get("web_console_url") or cloud_status.get("web_console_url") or "https://pea-api-intellisense-web.onrender.com"

    ais_truth_rows = _owner_queue(gap_rows, owner_lane="ais_truth_owner", top_n=top_n)
    topology_rows = _owner_queue(gap_rows, owner_lane="pea_topology_owner", top_n=top_n)
    _write_csv(ais_truth_queue_output, APPROVAL_QUEUE_COLUMNS, ais_truth_rows)
    _write_csv(topology_queue_output, APPROVAL_QUEUE_COLUMNS, topology_rows)

    ops_controls = _ops_controls_status(real_hit)
    summary = {
        "generated_at": _utc_now_iso(),
        "status": "PASS",
        "mode": "shadow",
        "production_send": "blocked",
        "decision": "AUTO_ETR_NO_GO",
        "cloud": {
            "api_base_url": api_base_url,
            "web_console_url": web_console_url,
            "health_status": real_hit.get("health_status") or cloud_status.get("health_status", ""),
            "database": real_hit.get("database") or cloud_status.get("database", ""),
            "total_requests": real_hit.get("total_requests", cloud_status.get("total_requests", 0)),
            "non_smoke_requests": real_hit.get("non_smoke_requests", cloud_status.get("non_smoke_requests", 0)),
            "latest_request": latest_request,
        },
        "readiness": {
            "cloud_endpoint_ready": readiness.get("cloud_endpoint_ready") or (owner_packet.get("readiness") or {}).get("cloud_endpoint_ready", ""),
            "production_infra_ready": readiness.get("production_infra_ready") or (owner_packet.get("readiness") or {}).get("production_infra_ready", ""),
            "auto_etr_ready": readiness.get("auto_etr_ready") or (owner_packet.get("readiness") or {}).get("auto_etr_ready", ""),
        },
        "green_gate": {
            "green_rows": owner_packet.get("green_rows", 0),
            "min_green_rows": owner_packet.get("min_green_rows", 30),
            "additional_green_rows_needed": owner_packet.get("additional_green_rows_needed", 30),
            "q50_mae_minutes": owner_packet.get("green_q50_mae_minutes"),
            "q10_q90_coverage": owner_packet.get("green_q10_q90_coverage"),
        },
        "owner_queues": {
            "ais_truth_owner_rows": len(ais_truth_rows),
            "pea_topology_owner_rows": len(topology_rows),
            "top_n": top_n,
        },
        "ops_controls": ops_controls,
        "outputs": {
            "ais_truth_queue": str(ais_truth_queue_output),
            "topology_queue": str(topology_queue_output),
            "ops_report": str(ops_report_output),
            "ais_test_window_request": str(ais_test_window_output),
            "markdown": str(markdown_output),
            "json": str(json_output),
        },
        "guardrails": [
            "production_send_remains_blocked",
            "api_key_db_url_and_tokens_not_written",
            "smoke_demo_cases_do_not_count_as_green_truth",
            "ais_outage_restore_remains_customer_facing_truth",
        ],
    }
    _write_json(json_output, summary)
    _write_text(ops_report_output, _render_ops_blocker_report(summary))
    _write_text(ais_test_window_output, _render_ais_test_window_request(summary))
    _write_text(markdown_output, _render_production_approval_evidence_pack(summary))
    return summary


def build_green_eligibility_report(
    *,
    ais_only_readiness: str | Path = "runtime/ais_only_readiness.csv",
    notification_time: str | Path = "runtime/notification_time_readiness.csv",
    lifecycle_challenger: str | Path = "runtime/ais_only_lifecycle_challenger.csv",
    remaining_time: str | Path = "runtime/ais_only_remaining_time_challenger.csv",
    threshold_calibration: str | Path = "runtime/eligibility_threshold_calibration.csv",
    output: str | Path = "runtime/cloud_pilot/green_eligibility_report.csv",
    markdown_output: str | Path = "runtime/cloud_pilot/green_eligibility_report.md",
    segments_output: str | Path = "runtime/cloud_pilot/green_eligibility_segments.csv",
    gate_output: str | Path = "runtime/cloud_pilot/green_gate_tracker.md",
    gate_csv_output: str | Path = "runtime/cloud_pilot/green_gate_tracker.csv",
    json_output: str | Path = "runtime/cloud_pilot/green_eligibility_report.json",
    min_green_rows: int = 30,
) -> dict[str, Any]:
    sources = [Path(ais_only_readiness), Path(notification_time)]
    missing = [str(path) for path in sources if not path.exists()]
    Path(json_output).parent.mkdir(parents=True, exist_ok=True)
    if missing:
        summary = {
            "generated_at": _utc_now_iso(),
            "status": "BLOCKED_MISSING_INPUT",
            "mode": "shadow",
            "production_send": "blocked",
            "missing_inputs": missing,
        }
        _write_json(json_output, summary)
        Path(markdown_output).write_text(_render_missing_green_report(summary), encoding="utf-8")
        return summary

    eligibility = build_shadow_send_eligibility(
        ais_only_readiness,
        notification_time,
        output,
        markdown_output,
        gate_output,
        lifecycle_challenger_csv=lifecycle_challenger if Path(lifecycle_challenger).exists() else None,
        remaining_time_csv=remaining_time if Path(remaining_time).exists() else None,
        segments_output=segments_output,
    )
    gate = build_green_gate_tracker(
        output,
        threshold_calibration,
        gate_csv_output,
        gate_output,
        min_green_rows=min_green_rows,
    )
    summary = {
        "generated_at": _utc_now_iso(),
        "status": "PASS",
        "mode": "shadow",
        "production_send": "blocked",
        "eligibility": eligibility,
        "green_gate": gate,
        "outputs": {
            "csv": str(output),
            "markdown": str(markdown_output),
            "segments": str(segments_output),
            "gate_csv": str(gate_csv_output),
            "gate_markdown": str(gate_output),
        },
    }
    _write_json(json_output, summary)
    return summary


def run_cloud_worker_shadow_loop(
    *,
    database_url: str | None = None,
    input_json: str | Path | None = None,
    output_json: str | Path = "runtime/cloud_pilot/cloud_worker_shadow_loop_report.json",
    markdown_output: str | Path = "runtime/cloud_pilot/cloud_worker_shadow_loop_report.md",
    limit: int = 50,
    dry_run: bool = True,
    apply: bool = False,
) -> dict[str, Any]:
    if apply and dry_run:
        raise ValueError("--apply cannot be combined with dry_run=True")
    rows = _load_pending_rows(database_url=database_url, input_json=input_json, limit=limit)
    decisions = [_worker_decision(row) for row in rows[: max(limit, 0)]]
    applied = False
    if apply and decisions:
        if not database_url:
            raise ValueError("DATABASE_URL is required for --apply")
        _apply_worker_decisions(database_url, decisions)
        applied = True
    summary = {
        "generated_at": _utc_now_iso(),
        "mode": "shadow",
        "production_send": "blocked",
        "status": "APPLIED" if applied else "DRY_RUN",
        "rows_seen": len(rows),
        "decisions": decisions,
        "guardrails": [
            "no_customer_facing_send",
            "meter_hash_or_last4_only",
            "raw_webex_text_not_used",
            "ais_outage_restore_remains_truth",
        ],
    }
    _write_json(output_json, summary)
    Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
    Path(markdown_output).write_text(_render_worker_report(summary), encoding="utf-8")
    return summary


def _load_pending_rows(*, database_url: str | None, input_json: str | Path | None, limit: int) -> list[dict[str, Any]]:
    if input_json:
        payload = json.loads(Path(input_json).read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            return [dict(item) for item in payload["items"]]
        if isinstance(payload, dict):
            return []
        if isinstance(payload, list):
            return [dict(item) for item in payload]
        raise ValueError("input_json must be a list or operator payload with items")
    if not database_url:
        return []
    psql = shutil.which("psql")
    if not psql:
        raise RuntimeError("psql was not found; install PostgreSQL client tools or pass --input-json for dry-run")
    query = PENDING_WORKER_SQL.format(limit=max(limit, 0))
    result = subprocess.run(
        [psql, database_url, "-At", "-c", query],
        check=True,
        capture_output=True,
        text=True,
    )
    text = result.stdout.strip() or "[]"
    value = json.loads(text)
    return [dict(item) for item in value]


def _gap_action_row(row: dict[str, str]) -> dict[str, str]:
    reasons = _split_reasons(row.get("blocker_reasons"))
    return {
        "event_ref": row.get("event_ref", ""),
        "event_time": row.get("event_time", ""),
        "feeder": row.get("feeder", ""),
        "device_id": row.get("device_id", ""),
        "source_lane": row.get("source_lane", ""),
        "eligibility_status": row.get("eligibility_status", ""),
        "stage1_class": row.get("stage1_class", ""),
        "blocker_reasons": ";".join(reasons),
        "owner_lane": _owner_lane_for_reasons(reasons, row),
        "next_evidence_needed": _next_evidence_needed(reasons, row),
        "metric_use": _metric_use(row),
        "conversion_rank": str(_conversion_rank(row, reasons)),
        "production_send": "blocked",
    }


def _smoke_demo_gap_row(real_hit: dict[str, Any]) -> dict[str, str] | None:
    total = _to_int(real_hit.get("total_requests")) or 0
    if total <= 0:
        return None
    latest = _safe_latest_request(real_hit.get("latest_request"))
    return {
        "event_ref": latest.get("request_id") or "cloud_smoke_requests",
        "event_time": latest.get("received_at") or real_hit.get("generated_at", ""),
        "feeder": "",
        "device_id": "",
        "source_lane": "cloud_smoke_demo",
        "eligibility_status": "monitor_only",
        "stage1_class": "non_metric",
        "blocker_reasons": "smoke_demo_not_real_ais_truth",
        "owner_lane": "cloud_ops_owner",
        "next_evidence_needed": "Use as API/DB/console proof only; do not count toward green model gate.",
        "metric_use": "non_metric_smoke_demo_not_green_gate",
        "conversion_rank": "0",
        "production_send": "blocked",
    }


def _owner_lane_for_reasons(reasons: list[str], row: dict[str, str]) -> str:
    reason_set = set(reasons)
    if reason_set & {"missing_ais_truth", "not_ais_truth_matched", "no_active_ais_evidence"}:
        return "ais_truth_owner"
    if reason_set & {"no_affected_ais", "missing_protection_match", "feeder_fallback_shadow_only", "low_match_confidence"}:
        return "pea_topology_owner"
    if reason_set & {"wide_prediction_interval", "missing_prediction_interval", "missing_prediction", "long_outage_risk"}:
        return "model_owner"
    if reason_set & {"momentary_webex_requires_review"}:
        return "pea_operations_owner"
    if reason_set & {"pea_quarantined", "not_model_metric_included"}:
        return "data_governance_owner"
    if row.get("eligibility_status") == "green_auto_candidate":
        return "production_gate_owner"
    return "operator_review"


def _next_evidence_needed(reasons: list[str], row: dict[str, str]) -> str:
    if row.get("eligibility_status") == "green_auto_candidate":
        return "Hold for green-gate aggregate metrics and owner approval; production send remains blocked."
    mapping = {
        "missing_ais_truth": "AIS outage/restore timestamp and site or meter truth for this event.",
        "not_ais_truth_matched": "Map this event to approved AIS truth, or reject with owner reason.",
        "no_active_ais_evidence": "AIS confirms active site outage at event time, or marks not affected.",
        "no_affected_ais": "Confirm affected AIS site or meter behind the matched protection device.",
        "missing_protection_match": "Topology owner supplies approved protection-device match.",
        "feeder_fallback_shadow_only": "Replace feeder fallback with approved downstream protection match.",
        "low_match_confidence": "Repair topology/matching confidence to at least 0.80.",
        "wide_prediction_interval": "Model owner narrows q10-q90 interval to <=120 minutes using approved features.",
        "missing_prediction_interval": "Model owner provides q10/q50/q90 candidate.",
        "missing_prediction": "Model owner provides q10/q50/q90 candidate.",
        "long_outage_risk": "Operations/model owner adds approved lifecycle or cause context for long-outage risk.",
        "momentary_webex_requires_review": "Operations owner resolves momentary WebEx vs AIS sustained-outage conflict.",
        "not_model_metric_included": "Data owner validates metric inclusion or excludes with reason.",
        "pea_quarantined": "Keep PEA context as feature/quarantine only until owner approval and AIS truth exist.",
    }
    for reason in reasons:
        if reason in mapping:
            return mapping[reason]
    return "Operator review required; keep status-only or monitor-only."


def _metric_use(row: dict[str, str]) -> str:
    source_lane = row.get("source_lane", "")
    if source_lane == "ais_truth_matched":
        return "historical_ais_truth_backtest"
    if source_lane == "webex_trigger_no_ais_truth":
        return "monitor_until_ais_truth_arrives"
    if source_lane == "pea_quarantined":
        return "context_quarantine_not_truth"
    return "non_metric_review"


def _conversion_rank(row: dict[str, str], reasons: list[str]) -> int:
    status = row.get("eligibility_status", "")
    rank = {"green_auto_candidate": 300, "amber_human_review": 220, "red_blocked": 100, "monitor_only": 80}.get(status, 0)
    if row.get("source_lane") == "ais_truth_matched":
        rank += 40
    if _to_float(row.get("selected_absolute_error")) is not None and (_to_float(row.get("selected_absolute_error")) or 999) <= 16:
        rank += 20
    if str(row.get("selected_covered_q10_q90", "")).upper() == "TRUE":
        rank += 15
    rank -= min(len(reasons), 8) * 8
    return rank


def _safe_latest_request(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        "request_id": str(value.get("request_id") or ""),
        "received_at": str(value.get("received_at") or ""),
        "status": str(value.get("status") or ""),
        "callback_status": str(value.get("callback_status") or ""),
        "production_send": str(value.get("production_send") or "blocked"),
    }


def _worker_decision(row: dict[str, Any]) -> dict[str, Any]:
    request_id = str(row.get("request_id") or "").strip()
    evidence_status = "SECURE_TOPOLOGY_LOOKUP_REQUIRED"
    reason = "cloud_store_has_only_hashed_meter_reference"
    if _evidence_already_ready(row):
        evidence_status = "REVIEW_REQUIRED"
        reason = "existing_shadow_evidence_needs_operator_review"
    return {
        "request_id": request_id,
        "evidence_trace": {
            "trace_status": evidence_status,
            "match_found": False,
            "match_level": "",
            "confidence": "LOW",
            "evidence_json": {
                "source": "python_cloud_shadow_worker",
                "reason": reason,
                "meter_ref": _meter_ref(row),
                "production_send": "blocked",
            },
        },
        "etr_candidate": {
            "status": "NOT_READY_FOR_AUTO_SEND",
            "p50_minutes": None,
            "q10_minutes": None,
            "q90_minutes": None,
            "risk_level": "REVIEW",
            "model_version": "shadow-worker",
            "production_gate": "blocked_green_gate",
            "production_send": "blocked",
        },
        "audit_event": {
            "event_type": "cloud_shadow_worker_review",
            "details_json": {
                "reason": reason,
                "dry_run_safe": True,
                "production_send": "blocked",
            },
        },
    }


def _evidence_already_ready(row: dict[str, Any]) -> bool:
    result = row.get("result")
    if not isinstance(result, dict):
        return False
    evidence = result.get("evidence")
    return isinstance(evidence, dict) and evidence.get("match_found") is True


def _meter_ref(row: dict[str, Any]) -> dict[str, str]:
    meter = row.get("meter")
    if isinstance(meter, dict):
        return {"hash": str(meter.get("hash") or ""), "last4": str(meter.get("last4") or "")}
    return {
        "hash": str(row.get("meter_hash") or ""),
        "last4": str(row.get("meter_last4") or ""),
    }


def _apply_worker_decisions(database_url: str, decisions: list[dict[str, Any]]) -> None:
    psql = shutil.which("psql")
    if not psql:
        raise RuntimeError("psql was not found; cannot apply worker decisions")
    statements = []
    for decision in decisions:
        request_id = _sql_text(decision["request_id"])
        evidence = decision["evidence_trace"]
        etr = decision["etr_candidate"]
        audit = decision["audit_event"]
        statements.extend(
            [
                (
                    "INSERT INTO evidence_traces "
                    "(request_id, trace_status, match_found, match_level, confidence, evidence_json, production_send) "
                    f"VALUES ({request_id}, {_sql_text(evidence['trace_status'])}, false, '', 'LOW', "
                    f"{_sql_json(evidence['evidence_json'])}, 'blocked');"
                ),
                (
                    "INSERT INTO etr_candidates "
                    "(request_id, status, risk_level, model_version, production_gate, production_send) "
                    f"VALUES ({request_id}, {_sql_text(etr['status'])}, {_sql_text(etr['risk_level'])}, "
                    f"{_sql_text(etr['model_version'])}, {_sql_text(etr['production_gate'])}, 'blocked');"
                ),
                (
                    "INSERT INTO audit_events (event_type, request_id, details_json) "
                    f"VALUES ({_sql_text(audit['event_type'])}, {request_id}, {_sql_json(audit['details_json'])});"
                ),
            ]
        )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".sql", delete=False) as handle:
        handle.write("\n".join(statements))
        script_path = Path(handle.name)
    try:
        subprocess.run([psql, database_url, "-v", "ON_ERROR_STOP=1", "-f", str(script_path)], check=True)
    finally:
        script_path.unlink(missing_ok=True)


def _owner_queue(rows: list[dict[str, str]], *, owner_lane: str, top_n: int) -> list[dict[str, Any]]:
    selected = [row for row in rows if row.get("owner_lane") == owner_lane and row.get("production_send", "blocked") == "blocked"]
    selected.sort(
        key=lambda row: (
            _to_int(row.get("conversion_rank")) or 0,
            row.get("source_lane") == "ais_truth_matched",
            row.get("event_time", ""),
        ),
        reverse=True,
    )
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in selected:
        unique_key = (
            row.get("event_ref", ""),
            row.get("feeder", ""),
            row.get("device_id", ""),
            row.get("source_lane", ""),
        )
        if unique_key in seen:
            continue
        seen.add(unique_key)
        index = len(output) + 1
        output.append(
            {
                "rank": index,
                "event_ref": row.get("event_ref", ""),
                "event_time": row.get("event_time", ""),
                "feeder": row.get("feeder", ""),
                "device_id": row.get("device_id", ""),
                "source_lane": row.get("source_lane", ""),
                "eligibility_status": row.get("eligibility_status", ""),
                "blocker_reasons": row.get("blocker_reasons", ""),
                "next_evidence_needed": row.get("next_evidence_needed", ""),
                "conversion_rank": row.get("conversion_rank", ""),
                "production_send": "blocked",
            }
        )
        if len(output) >= max(top_n, 0):
            break
    return output


def _ops_controls_status(real_hit: dict[str, Any]) -> dict[str, Any]:
    tools = {name: bool(shutil.which(name)) for name in ("pg_dump", "pg_restore", "psql")}
    env = {name: bool(os.environ.get(name)) for name in ("DATABASE_URL", "RESTORE_TEST_DATABASE_URL", "RENDER_API_KEY")}
    missing_tools = [name for name, present in tools.items() if not present]
    missing_env = [name for name, present in env.items() if not present]
    non_smoke_requests = _to_int(real_hit.get("non_smoke_requests")) or 0
    backup_restore_ready = all(tools.values()) and env["DATABASE_URL"] and env["RESTORE_TEST_DATABASE_URL"]
    render_alerts_ready = env["RENDER_API_KEY"]
    return {
        "tools_present": tools,
        "env_present": env,
        "backup_restore_drill": "READY_TO_RUN" if backup_restore_ready else "BLOCKED_MISSING_POSTGRES_TOOLS_OR_URLS",
        "render_alerts": "READY_TO_VERIFY_WITH_RENDER_API" if render_alerts_ready else "MANUAL_CONFIRM_REQUIRED_OR_RENDER_API_KEY_MISSING",
        "key_rotation_drill": "READY_AFTER_FIRST_REAL_AIS_HIT" if non_smoke_requests > 0 else "DEFER_UNTIL_FIRST_REAL_AIS_HIT",
        "missing_tools": missing_tools,
        "missing_env": missing_env,
    }


def _sql_text(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _sql_json(value: Any) -> str:
    return _sql_text(json.dumps(value, ensure_ascii=False, sort_keys=True)) + "::jsonb"


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: str | Path, content: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def _read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        return {}
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    source = Path(path)
    if not source.exists():
        return []
    with source.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: str | Path, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _split_reasons(value: Any) -> list[str]:
    output: list[str] = []
    seen = set()
    for part in str(value or "").split(";"):
        reason = part.strip()
        if reason and reason not in seen:
            seen.add(reason)
            output.append(reason)
    return output


def _to_int(value: Any) -> int | None:
    numeric = _to_float(value)
    return int(numeric) if numeric is not None else None


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _render_production_gate_packet(summary: dict[str, Any]) -> str:
    cloud = summary.get("cloud_status") or {}
    readiness = summary.get("readiness") or {}
    owner_counts = summary.get("owner_lane_counts") or {}
    blockers = summary.get("blocker_reason_counts") or {}
    latest = cloud.get("latest_request") or {}
    lines = [
        "# Production Gate Owner Packet",
        "",
        f"- Generated: `{summary['generated_at']}`",
        "- Mode: `shadow`",
        "- Production send: `blocked`",
        f"- Decision: `{summary['decision']}`",
        "",
        "## Gate Snapshot",
        "",
        f"- Green rows: `{summary['green_rows']}` / `{summary['min_green_rows']}`",
        f"- Additional green rows needed: `{summary['additional_green_rows_needed']}`",
        f"- Green q50 MAE: `{summary.get('green_q50_mae_minutes') or ''}`",
        f"- Green q10-q90 coverage: `{summary.get('green_q10_q90_coverage') or ''}`",
        f"- Production gate status: `{summary['production_gate_status']}`",
        f"- Cloud endpoint: `{readiness.get('cloud_endpoint_ready', '')}`",
        f"- Production infra: `{readiness.get('production_infra_ready', '')}`",
        f"- Auto ETR: `{readiness.get('auto_etr_ready', '')}`",
        "",
        "## Cloud Evidence",
        "",
        f"- API: `{cloud.get('api_base_url', '')}`",
        f"- Health: `{cloud.get('health_status', '')}`",
        f"- Database: `{cloud.get('database', '')}`",
        f"- Total cloud requests: `{cloud.get('total_requests', 0)}`",
        f"- Real AIS cloud requests: `{cloud.get('non_smoke_requests', 0)}`",
        f"- Latest request: `{latest.get('request_id', '')}` / `{latest.get('status', '')}` / `production_send={latest.get('production_send', 'blocked')}`",
        "",
        "Smoke/demo requests prove API, DB, and console flow only. They do not count toward green model gate.",
        "",
        "## Top Blockers",
        "",
        "| Blocker | Rows |",
        "| --- | ---: |",
    ]
    for blocker, count in blockers.items():
        lines.append(f"| `{blocker}` | {count} |")
    lines.extend(
        [
            "",
            "## Owner Work Queue",
            "",
            "| Owner lane | Rows |",
            "| --- | ---: |",
        ]
    )
    for lane, count in owner_counts.items():
        lines.append(f"| `{lane}` | {count} |")
    lines.extend(
        [
            "",
            "## Approval Ask",
            "",
            "- AIS truth owner: provide outage/restore truth for prioritized WebEx/protection events.",
            "- PEA topology owner: approve downstream protection mapping; feeder-only stays non-green.",
            "- Model owner: improve uncertainty and validate q50 MAE/coverage on green subset.",
            "- Operations owner: review momentary/long-outage conflicts and approve context use.",
            "- Gateway/security owner: approve auth, monitoring, backup/restore, incident process, and emergency off.",
            "",
            "## Guardrails",
            "",
            "- Do not enable customer-facing Auto ETR from this packet.",
            "- `production_send` remains `blocked` until infra gate, green model gate, callback approval, and owner approval pass.",
            "- AIS outage/restore remains customer-facing truth.",
            "- Reports must not include API key, DB URL, token, room ID, verbatim WebEx text, full meter/PEANO, or customer identity.",
            "",
            "## Outputs",
            "",
        ]
    )
    for name, path in (summary.get("outputs") or {}).items():
        lines.append(f"- {name}: `{path}`")
    return "\n".join(lines) + "\n"


def _render_production_approval_evidence_pack(summary: dict[str, Any]) -> str:
    cloud = summary["cloud"]
    green = summary["green_gate"]
    readiness = summary["readiness"]
    queues = summary["owner_queues"]
    ops = summary["ops_controls"]
    latest = cloud.get("latest_request") or {}
    lines = [
        "# Production Approval Evidence Next Actions",
        "",
        f"- Generated: `{summary['generated_at']}`",
        "- Mode: `shadow`",
        "- Production send: `blocked`",
        f"- Decision: `{summary['decision']}`",
        "",
        "## Current State",
        "",
        f"- API health: `{cloud.get('health_status', '')}`",
        f"- Database: `{cloud.get('database', '')}`",
        f"- Total cloud requests: `{cloud.get('total_requests', 0)}`",
        f"- Real AIS cloud requests: `{cloud.get('non_smoke_requests', 0)}`",
        f"- Latest request: `{latest.get('request_id', '')}` / `{latest.get('status', '')}` / `production_send={latest.get('production_send', 'blocked')}`",
        f"- Cloud endpoint ready: `{readiness.get('cloud_endpoint_ready', '')}`",
        f"- Production infra ready: `{readiness.get('production_infra_ready', '')}`",
        f"- Auto ETR ready: `{readiness.get('auto_etr_ready', '')}`",
        "",
        "## Gate Work",
        "",
        f"- Green rows: `{green.get('green_rows', 0)}` / `{green.get('min_green_rows', 30)}`",
        f"- Additional green rows needed: `{green.get('additional_green_rows_needed', 30)}`",
        f"- AIS truth owner queue rows: `{queues.get('ais_truth_owner_rows', 0)}`",
        f"- PEA topology owner queue rows: `{queues.get('pea_topology_owner_rows', 0)}`",
        "",
        "## Ops Work",
        "",
        f"- Backup/restore drill: `{ops.get('backup_restore_drill', '')}`",
        f"- Render alerts: `{ops.get('render_alerts', '')}`",
        f"- Key rotation drill: `{ops.get('key_rotation_drill', '')}`",
        f"- Missing tools: `{', '.join(ops.get('missing_tools') or []) or 'none'}`",
        f"- Missing env names: `{', '.join(ops.get('missing_env') or []) or 'none'}`",
        "",
        "## Next Actions",
        "",
        "1. Ask AIS to send one valid request and one duplicate request to the cloud endpoint.",
        "2. Send `green_owner_top30_ais_truth_queue.csv` to AIS truth owner for active outage confirmation.",
        "3. Send `green_owner_top30_topology_queue.csv` to PEA topology owner for downstream protection approval.",
        "4. Install missing PostgreSQL client tools and set local-only database URLs before backup/restore drill.",
        "5. Keep Auto ETR blocked until green gate, infra gate, callback approval, and owner approval all pass.",
        "",
        "## Outputs",
        "",
    ]
    for name, path in (summary.get("outputs") or {}).items():
        lines.append(f"- {name}: `{path}`")
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This pack does not approve customer-facing Auto ETR.",
            "- Do not paste API keys, DB URLs, tokens, room IDs, verbatim WebEx text, full meter/PEANO, or customer identity into any shared channel.",
            "- Smoke/demo rows prove flow only; they do not count toward green model gate.",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_ops_blocker_report(summary: dict[str, Any]) -> str:
    ops = summary["ops_controls"]
    lines = [
        "# Ops Controls Blocker Report",
        "",
        f"- Generated: `{summary['generated_at']}`",
        "- Mode: `shadow`",
        "- Production send: `blocked`",
        "",
        "## Tooling",
        "",
        "| Tool | Present |",
        "| --- | --- |",
    ]
    for name, present in (ops.get("tools_present") or {}).items():
        lines.append(f"| `{name}` | `{str(bool(present)).lower()}` |")
    lines.extend(
        [
            "",
            "## Local Environment",
            "",
            "Only presence is reported. Values are never written.",
            "",
            "| Env name | Present |",
            "| --- | --- |",
        ]
    )
    for name, present in (ops.get("env_present") or {}).items():
        lines.append(f"| `{name}` | `{str(bool(present)).lower()}` |")
    lines.extend(
        [
            "",
            "## Status",
            "",
            f"- Backup/restore drill: `{ops.get('backup_restore_drill', '')}`",
            f"- Render alerts: `{ops.get('render_alerts', '')}`",
            f"- Key rotation drill: `{ops.get('key_rotation_drill', '')}`",
            "",
            "## Required Fix",
            "",
            "- Install PostgreSQL client tools if `pg_dump`, `pg_restore`, or `psql` is missing.",
            "- Set `DATABASE_URL` and `RESTORE_TEST_DATABASE_URL` locally only before restore drill.",
            "- Use Render UI/API to confirm alert rules; do not store Render API key in GitHub.",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_ais_test_window_request(summary: dict[str, Any]) -> str:
    cloud = summary["cloud"]
    endpoint = str(cloud.get("api_base_url", "")).rstrip("/") + "/api/v1/ais/outage-verifications"
    lines = [
        "# AIS Cloud Pilot Test Window Request",
        "",
        "ส่งให้ AIS ผ่านช่องทางทำงานปกติได้ แต่ `X-API-Key` ส่งแยกผ่าน secure direct channel เท่านั้น.",
        "",
        "## Request",
        "",
        f"- URL: `{endpoint}`",
        "- Method: `POST`",
        "- Headers:",
        "  - `Content-Type: application/json`",
        "  - `X-API-Key: <cloud pilot key via secure channel only>`",
        "- Mode: `shadow/pilot only`",
        "- Production send: `blocked`",
        "",
        "## Test Window Ask",
        "",
        "1. Send one valid request.",
        "2. Send the same `request_id` again to test duplicate/idempotency.",
        "3. Reply with only `request_id`, sent time, and HTTP status observed.",
        "",
        "## Sample Body",
        "",
        "```json",
        "{",
        '  "request_id": "AIS-CLOUD-PILOT-YYYYMMDD-0001",',
        '  "meter_no": "REDACTED-METER-0000",',
        '  "timestamp": "2026-06-22T10:00:00+07:00",',
        '  "province": "Sakon Nakhon",',
        '  "district": "Phang Khon",',
        '  "subdistrict": "Demo",',
        '  "alarm_type": "AC_MAIN_FAIL",',
        '  "main_cause": "AC main failed",',
        '  "subcause": "PEA no back up"',
        "}",
        "```",
        "",
        "## Expected Result",
        "",
        "- Valid request: `202 Accepted`",
        "- Duplicate `request_id`: duplicate-safe response; no production resend",
        "- Missing/invalid key: `401`",
        "- Bad JSON/timestamp: safe `400`",
        "",
        "Customer-facing Auto ETR is not live.",
    ]
    return "\n".join(lines) + "\n"


def _render_worker_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Cloud Worker Shadow Loop",
        "",
        f"- Generated: `{summary['generated_at']}`",
        f"- Status: `{summary['status']}`",
        "- Mode: `shadow`",
        "- Production send: `blocked`",
        f"- Pending rows reviewed: `{summary['rows_seen']}`",
        "",
        "## Decisions",
        "",
        "| request_id | evidence | ETR | reason |",
        "| --- | --- | --- | --- |",
    ]
    for item in summary.get("decisions", [])[:50]:
        lines.append(
            "| {request_id} | `{evidence}` | `{etr}` | {reason} |".format(
                request_id=item.get("request_id", ""),
                evidence=item.get("evidence_trace", {}).get("trace_status", ""),
                etr=item.get("etr_candidate", {}).get("status", ""),
                reason=item.get("evidence_trace", {}).get("evidence_json", {}).get("reason", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Dry-run is default; `--apply` is required to write append-only worker rows.",
            "- No customer-facing callback is sent.",
            "- Full meter, PEANO lists, customer identity, room IDs, tokens, and verbatim WebEx text are not written.",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_missing_green_report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Green Eligibility Report",
            "",
            f"- Generated: `{summary['generated_at']}`",
            f"- Status: `{summary['status']}`",
            "- Mode: `shadow`",
            "- Production send: `blocked`",
            "",
            "Missing inputs:",
            *[f"- `{path}`" for path in summary["missing_inputs"]],
            "",
        ]
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
