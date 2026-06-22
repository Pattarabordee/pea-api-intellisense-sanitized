from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from .confidence_gate import build_shadow_send_eligibility
from .shadow_operations import build_green_gate_tracker


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


def _sql_text(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _sql_json(value: Any) -> str:
    return _sql_text(json.dumps(value, ensure_ascii=False, sort_keys=True)) + "::jsonb"


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


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
