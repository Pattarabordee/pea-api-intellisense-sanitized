from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from .db import RuntimeDb
from .schemas import CustomerAsset, NotificationRecord, utc_now_iso
from .utils import normalize_device_id, normalize_feeder


DEFAULT_INBOUND_PATH = "/api/v1/ais/outage-verifications"
DEFAULT_REQUEST_LOG = "runtime/ais_inbound_requests.jsonl"
DEFAULT_CALLBACK_LOG = "runtime/ais_inbound_callbacks.jsonl"
API_VERSION = "v1"
SCHEMA_VERSION = "2026-06-20"
MAX_BODY_BYTES = 1_000_000
MAX_REQUEST_ID_CHARS = 128
MAX_METER_CHARS = 64
MAX_AREA_CHARS = 120
MAX_CAUSE_CHARS = 240
DEFAULT_MATCH_WINDOW_MINUTES = 360
DEFAULT_RATE_LIMIT_PER_MINUTE = 120
TIMESTAMP_FUTURE_REVIEW_MINUTES = 15
TIMESTAMP_STALE_REVIEW_DAYS = 7
CONFIDENT_LEVELS = {"cb", "recloser", "switch", "transformer"}
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]*$")
SMOKE_REQUEST_PREFIXES = (
    "AIS-CONNECTIVITY-",
    "AIS-IP-CHECK-",
    "AIS-SMOKE-",
    "AIS-PUBLIC-CHECK-",
    "AIS-PUBLIC-ALIAS-SMOKE-",
    "AIS-PUBLIC-AUTH-CHECK-",
    "AIS-PUBLIC-KEEPALIVE-",
    "AIS-PUBLIC-POST-RESTART-",
    "AIS-PUBLIC-FIXED-URL-",
    "AIS-PUBLIC-RESTART-SCRIPT-",
    "AIS-FINAL-LOCAL-SMOKE-",
    "AIS-BEARER-SMOKE-",
)
SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "client_secret",
    "refresh_token",
    "secret",
    "token",
    "x-api-key",
    "x_api_key",
}
METER_KEYS = {
    "peano",
    "meter",
    "meter_id",
    "meter_no",
    "meter_number",
    "meterid",
    "meterno",
    "meternumber",
    "pea_meter_no",
    "peameterno",
    "pea_no",
    "peano",
}
BANGKOK_TZ = timezone(timedelta(hours=7))


@dataclass(frozen=True)
class AisInboundResult:
    request_id: str
    accepted_response: dict[str, Any]
    callback_payload: dict[str, Any]
    callback_record: NotificationRecord
    duplicate: bool = False

    def asdict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "accepted_response": self.accepted_response,
            "callback_status": self.callback_record.status,
            "callback_status_code": self.callback_record.status_code,
            "duplicate": self.duplicate,
        }


class AisInboundValidationError(ValueError):
    pass


def process_ais_inbound_request(
    *,
    db_path: str | Path,
    payload: dict[str, Any],
    callback_url: str | None = None,
    requests_output: str | Path | None = DEFAULT_REQUEST_LOG,
    callbacks_output: str | Path | None = DEFAULT_CALLBACK_LOG,
    match_window_minutes: int = DEFAULT_MATCH_WINDOW_MINUTES,
    post_callback: bool = True,
) -> AisInboundResult:
    """Process one AIS outage verification request in shadow mode."""
    request = _normalize_inbound_payload(payload)
    db = RuntimeDb(db_path)
    db.init()

    duplicate = _request_exists(db, request["request_id"])
    if duplicate:
        accepted = _accepted_response(request, callback_status="SKIPPED_DUPLICATE", duplicate=True)
        callback_payload = _build_duplicate_callback(request)
        callback_record = NotificationRecord(payload=callback_payload, status="SKIPPED_DUPLICATE")
        _append_jsonl(callbacks_output, _redacted_callback_log(callback_payload, callback_record, callback_url))
        _persist_callback(db.path, request["request_id"], callback_url, callback_payload, callback_record)
        return AisInboundResult(request["request_id"], accepted, callback_payload, callback_record, duplicate=True)

    asset = _load_asset_by_peano(db, request["peano"])
    cause_lane = _classify_cause_lane(request)
    evidence = _find_runtime_evidence(
        db,
        asset,
        request.get("detected_at"),
        match_window_minutes=match_window_minutes,
    )
    callback_payload = _build_callback_payload(request, asset, cause_lane, evidence)
    callback_record = _send_or_capture_callback(
        callback_payload,
        callback_url=callback_url,
        callbacks_output=callbacks_output,
        post_callback=post_callback,
    )
    accepted = _accepted_response(request, callback_status=callback_record.status, duplicate=False)

    _append_jsonl(
        requests_output,
        {
            "received_at": accepted["received_at"],
            "request": _redact_payload(request),
            "accepted_response": accepted,
            "callback_status": callback_record.status,
        },
    )
    _persist_inbound_result(db, request, accepted, callback_record.status)
    _persist_callback(db.path, request["request_id"], callback_url, callback_payload, callback_record)
    return AisInboundResult(request["request_id"], accepted, callback_payload, callback_record)


def create_ais_inbound_server(
    *,
    db_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 8090,
    path: str = DEFAULT_INBOUND_PATH,
    api_key: str | None = None,
    callback_url: str | None = None,
    requests_output: str | Path = DEFAULT_REQUEST_LOG,
    callbacks_output: str | Path = DEFAULT_CALLBACK_LOG,
    match_window_minutes: int = DEFAULT_MATCH_WINDOW_MINUTES,
    post_callback: bool = True,
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), AisInboundHandler)
    server.db_path = Path(db_path)  # type: ignore[attr-defined]
    server.inbound_path = path  # type: ignore[attr-defined]
    server.api_key = <REDACTED_SECRET>  # type: ignore[attr-defined]
    server.callback_url = callback_url  # type: ignore[attr-defined]
    server.requests_output = Path(requests_output)  # type: ignore[attr-defined]
    server.callbacks_output = Path(callbacks_output)  # type: ignore[attr-defined]
    server.match_window_minutes = match_window_minutes  # type: ignore[attr-defined]
    server.post_callback = post_callback  # type: ignore[attr-defined]
    server.rate_limit_per_minute = max(0, int(rate_limit_per_minute or 0))  # type: ignore[attr-defined]
    server.rate_limit_state = {}  # type: ignore[attr-defined]
    server.rate_limit_lock = threading.Lock()  # type: ignore[attr-defined]
    return server


def serve_ais_inbound_api(
    *,
    db_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 8090,
    path: str = DEFAULT_INBOUND_PATH,
    api_key: str | None = None,
    callback_url: str | None = None,
    requests_output: str | Path = DEFAULT_REQUEST_LOG,
    callbacks_output: str | Path = DEFAULT_CALLBACK_LOG,
    match_window_minutes: int = DEFAULT_MATCH_WINDOW_MINUTES,
    post_callback: bool = True,
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
) -> None:
    server = create_ais_inbound_server(
        db_path=db_path,
        host=host,
        port=port,
        path=path,
        api_key=<REDACTED_SECRET>
        callback_url=callback_url,
        requests_output=requests_output,
        callbacks_output=callbacks_output,
        match_window_minutes=match_window_minutes,
        post_callback=post_callback,
        rate_limit_per_minute=rate_limit_per_minute,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


def write_demo_request(path: str | Path, peano: str = "PEANO_SAMPLE") -> dict[str, Any]:
    payload = {
        "request_id": "AIS-DEMO-0001",
        "meter_no": peano,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "province": "Sakon Nakhon",
        "district": "Phang Khon",
        "subdistrict": "Demo",
        "alarm_type": "AC_MAIN_FAIL",
        "main_cause": "Faulty AC main failed",
        "subcause": "PEA no back up",
    }
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return {"output": str(output), "request_id": payload["request_id"]}


def build_ais_inbound_status_report(
    db_path: str | Path,
    *,
    output: str | Path | None = "runtime/ais_inbound_status_report.md",
    limit: int = 20,
) -> dict[str, Any]:
    """Summarize durable AIS inbound request state from SQLite without exposing raw meters."""
    items = _load_inbound_status_items(db_path)
    real_items = [item for item in items if not item["is_smoke"]]
    smoke_items = [item for item in items if item["is_smoke"]]
    callback_counts = _count_by(items, "callback_status")
    decision_counts = _count_by(items, "decision_answer")
    latest_request = items[-1] if items else None
    latest_real_request = real_items[-1] if real_items else None
    report = {
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "mode": "shadow",
        "production_send": "blocked",
        "db_path": str(Path(db_path)),
        "total_requests": len(items),
        "smoke_requests": len(smoke_items),
        "real_requests": len(real_items),
        "latest_request": latest_request,
        "latest_real_request": latest_real_request,
        "callback_status_counts": callback_counts,
        "decision_counts": decision_counts,
        "recent_requests": list(reversed(items[-max(0, limit) :])) if limit else [],
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_path.with_name(output_path.name + ".tmp")
        tmp_path.write_text(_inbound_status_markdown(report), encoding="utf-8")
        tmp_path.replace(output_path)
        report["output"] = str(output_path)
    return report


def build_ais_inbound_db_snapshot(
    db_path: str | Path,
    *,
    output_dir: str | Path = "runtime/snapshots",
    label: str | None = None,
    output_markdown: str | Path | None = None,
    output_json: str | Path | None = None,
) -> dict[str, Any]:
    """Create an internal SQLite snapshot and redacted evidence report for inbound API data."""
    db = RuntimeDb(db_path)
    db.init()
    source_path = db.path
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y%m%dT%H%M%SZ")
    safe_label = _safe_snapshot_label(label or "manual")
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    snapshot_path = output_root / f"ais_inbound_{safe_label}_{timestamp}.sqlite"
    tmp_snapshot = snapshot_path.with_name(snapshot_path.name + ".tmp")

    source_conn = sqlite3.connect(source_path)
    dest_conn = sqlite3.connect(tmp_snapshot)
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()
    tmp_snapshot.replace(snapshot_path)

    status = build_ais_inbound_status_report(source_path, output=None, limit=5)
    table_counts = _sqlite_table_counts(
        source_path,
        [
            "ais_inbound_requests",
            "ais_inbound_callbacks",
            "webex_messages",
            "outage_events",
            "predictions",
            "notifications",
            "customer_assets",
        ],
    )
    snapshot_counts = _sqlite_table_counts(snapshot_path, list(table_counts.keys()))
    integrity_check = _sqlite_integrity_check(snapshot_path)
    report = {
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "mode": "shadow",
        "production_send": "blocked",
        "label": safe_label,
        "source_db_path": str(source_path),
        "snapshot_path": str(snapshot_path),
        "snapshot_sha256": _sha256_file(snapshot_path),
        "snapshot_bytes": snapshot_path.stat().st_size,
        "integrity_check": integrity_check,
        "table_counts": table_counts,
        "snapshot_table_counts": snapshot_counts,
        "counts_match": table_counts == snapshot_counts,
        "total_requests": status["total_requests"],
        "real_requests": status["real_requests"],
        "smoke_requests": status["smoke_requests"],
        "latest_real_request": status["latest_real_request"],
        "privacy_note": "Snapshot is internal evidence. Share the Markdown/JSON report, not the SQLite file, unless approved.",
    }

    md_path = Path(output_markdown) if output_markdown else output_root / f"ais_inbound_{safe_label}_{timestamp}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_tmp = md_path.with_name(md_path.name + ".tmp")
    md_tmp.write_text(_db_snapshot_markdown(report), encoding="utf-8")
    md_tmp.replace(md_path)

    json_path = Path(output_json) if output_json else output_root / f"ais_inbound_{safe_label}_{timestamp}.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_tmp = json_path.with_name(json_path.name + ".tmp")
    json_tmp.write_text(json.dumps(_db_snapshot_public_json(report), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    json_tmp.replace(json_path)

    report["output_markdown"] = str(md_path)
    report["output_json"] = str(json_path)
    return report


def build_ais_inbound_audit_export(
    db_path: str | Path,
    *,
    output_csv: str | Path = "runtime/ais_inbound_audit_export.csv",
    output_markdown: str | Path = "runtime/ais_inbound_audit_export.md",
    include_smoke: bool = False,
    limit: int = 200,
) -> dict[str, Any]:
    """Export safe row-level inbound API evidence for AIS/PEA pilot review."""
    items = _load_inbound_status_items(db_path)
    selected = items if include_smoke else [item for item in items if not item["is_smoke"]]
    selected = list(reversed(selected[-max(0, limit) :])) if limit else list(reversed(selected))
    rows = [_audit_export_row(item) for item in selected]

    csv_path = Path(output_csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_tmp = csv_path.with_name(csv_path.name + ".tmp")
    fieldnames = [
        "request_id",
        "request_type",
        "received_at",
        "detected_at",
        "detected_at_original",
        "timestamp_quality_status",
        "timestamp_quality_flags",
        "province",
        "district",
        "subdistrict",
        "meter_hash",
        "meter_last4",
        "verification_status",
        "decision_answer",
        "decision_reason",
        "confidence",
        "pea_distribution_outage",
        "next_action",
        "match_found",
        "match_level",
        "match_confidence",
        "device_type",
        "device_id",
        "feeder",
        "time_delta_minutes",
        "etr_status",
        "etr_minutes_p50",
        "q10",
        "q90",
        "risk_level",
        "callback_status",
        "callback_status_code",
        "production_send",
    ]
    with csv_tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({key: _csv_safe(value) for key, value in row.items()} for row in rows)
    csv_tmp.replace(csv_path)

    markdown_path = Path(output_markdown)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_tmp = markdown_path.with_name(markdown_path.name + ".tmp")
    markdown_tmp.write_text(
        _inbound_audit_export_markdown(
            rows,
            include_smoke=include_smoke,
            total_requests=len(items),
            real_requests=sum(1 for item in items if not item["is_smoke"]),
            smoke_requests=sum(1 for item in items if item["is_smoke"]),
            output_csv=csv_path,
        ),
        encoding="utf-8",
    )
    markdown_tmp.replace(markdown_path)
    return {
        "mode": "shadow",
        "production_send": "blocked",
        "include_smoke": include_smoke,
        "total_requests": len(items),
        "real_requests": sum(1 for item in items if not item["is_smoke"]),
        "smoke_requests": sum(1 for item in items if item["is_smoke"]),
        "exported_rows": len(rows),
        "output_csv": str(csv_path),
        "output_markdown": str(markdown_path),
    }


def build_ais_inbound_first_hit_packet(
    db_path: str | Path,
    *,
    output_markdown: str | Path = "runtime/ais_inbound_first_hit_packet.md",
    output_json: str | Path = "runtime/ais_inbound_first_hit_packet.json",
) -> dict[str, Any]:
    """Build an operator packet for the first real AIS request without exposing raw meters."""
    items = _load_inbound_status_items(db_path)
    real_items = [item for item in items if not item["is_smoke"]]
    latest_real = real_items[-1] if real_items else None
    packet = {
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "mode": "shadow",
        "production_send": "blocked",
        "status": "REAL_AIS_HIT_DETECTED" if latest_real else "WAITING_FOR_REAL_AIS_HIT",
        "total_requests": len(items),
        "real_requests": len(real_items),
        "smoke_requests": len(items) - len(real_items),
        "latest_real_request": latest_real,
        "operator_next_step": (
            "Review the redacted request, compare AIS timestamp with WebEx/topology evidence, and keep production send blocked."
            if latest_real
            else "Keep the endpoint running and ask AIS to send one real pilot request with the shared pilot key."
        ),
    }

    markdown_path = Path(output_markdown)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_tmp = markdown_path.with_name(markdown_path.name + ".tmp")
    markdown_tmp.write_text(_first_hit_packet_markdown(packet), encoding="utf-8")
    markdown_tmp.replace(markdown_path)

    json_path = Path(output_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_tmp = json_path.with_name(json_path.name + ".tmp")
    json_tmp.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    json_tmp.replace(json_path)

    packet["output_markdown"] = str(markdown_path)
    packet["output_json"] = str(json_path)
    return packet


def build_ais_inbound_readiness_gate(
    db_path: str | Path,
    *,
    status_file: str | Path = "runtime/ais_inbound_public_endpoint_status.json",
    verification_file: str | Path = "runtime/ais_inbound_public_endpoint_verification.json",
    doc_qa_file: str | Path = "runtime/ais_inbound_doc_qa.md",
    security_audit_file: str | Path = "runtime/ais_inbound_security_audit.json",
    first_hit_file: str | Path = "runtime/ais_inbound_first_hit_packet.json",
    db_snapshot_file: str | Path = "runtime/ais_inbound_db_snapshot_latest.json",
    output_markdown: str | Path = "runtime/ais_inbound_readiness_gate.md",
    output_json: str | Path = "runtime/ais_inbound_readiness_gate.json",
) -> dict[str, Any]:
    """Build a one-page gate for AIS inbound API pilot and production readiness."""
    status = _read_json_file(status_file)
    verification = _read_json_file(verification_file)
    security_audit = _read_json_file(security_audit_file)
    first_hit = _read_json_file(first_hit_file)
    db_snapshot = _read_json_file(db_snapshot_file)
    doc_qa = _read_text_file(doc_qa_file)
    inbound_status = build_ais_inbound_status_report(db_path, output=None, limit=10)

    public_url = str(status.get("primary_public_url") or verification.get("public_url") or "")
    health_url = str(status.get("primary_health_url") or verification.get("health_url") or "")
    checks = [
        _gate_check(
            "endpoint_url_present",
            bool(public_url.startswith("https://")),
            "Public HTTPS tunnel URL is available",
            "No current public HTTPS URL was found",
        ),
        _gate_check(
            "health_smoke",
            status.get("primary_health_smoke") == "200_OK" or _verification_check_ok(verification, "health"),
            "Health check passed",
            "Health check has not passed",
        ),
        _gate_check(
            "public_verifier",
            verification.get("all_checks_ok") is True,
            "Public endpoint verifier passed",
            "Public endpoint verifier is missing or failing",
        ),
        _gate_check(
            "doc_qa",
            _doc_qa_passed(doc_qa),
            "AIS-facing document QA passed",
            "AIS-facing document QA is missing or failing",
        ),
        _gate_check(
            "security_audit",
            _security_audit_passed(security_audit),
            "Shareable artifacts passed the security/privacy audit",
            "Security/privacy audit is missing or failing",
        ),
        _gate_check(
            "durable_request_store",
            isinstance(inbound_status.get("total_requests"), int),
            "SQLite inbound request store is queryable",
            "SQLite inbound request store could not be summarized",
        ),
        _gate_check(
            "db_snapshot_evidence",
            _db_snapshot_evidence_ok(db_snapshot),
            "Latest SQLite snapshot evidence is present and integrity-checked",
            "Latest SQLite snapshot evidence is missing or did not pass integrity/count checks",
            severity="WARN",
        ),
        _gate_check(
            "shadow_mode_guardrail",
            _all_shadow_blocked(status, verification, security_audit, inbound_status, first_hit, db_snapshot),
            "Shadow mode and production_send=blocked guardrails are intact",
            "Shadow/production guardrail is not proven",
        ),
        _gate_check(
            "first_real_ais_hit",
            int(first_hit.get("real_requests") or inbound_status.get("real_requests") or 0) > 0,
            "At least one real AIS request has reached the endpoint",
            "No real AIS request has reached the endpoint yet",
            severity="WARN",
        ),
        _gate_check(
            "production_infra",
            False,
            "Permanent production infrastructure is approved",
            "Endpoint still runs through local pilot tunnel; production infra is not approved",
            severity="WARN",
        ),
    ]

    critical_failures = [check for check in checks if check["status"] == "FAIL"]
    warnings = [check for check in checks if check["status"] == "WARN"]
    real_requests = int(first_hit.get("real_requests") or inbound_status.get("real_requests") or 0)
    pilot_test_status = "READY_FOR_AIS_TEST" if not critical_failures else "NOT_READY_FOR_AIS_TEST"
    if real_requests > 0 and not critical_failures:
        production_status = "BLOCKED_PENDING_PRODUCTION_APPROVAL"
    elif not critical_failures:
        production_status = "BLOCKED_WAITING_FOR_REAL_AIS_HIT"
    else:
        production_status = "BLOCKED_TECHNICAL_FAILURE"
    if not critical_failures and any(check["name"] == "production_infra" for check in warnings):
        production_status = "BLOCKED_LOCAL_TUNNEL_PILOT" if real_requests > 0 else production_status

    report = {
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "mode": "shadow",
        "production_send": "blocked",
        "pilot_test_status": pilot_test_status,
        "production_status": production_status,
        "pilot_api_test_readiness_percent": _readiness_percent(checks, include_production=False),
        "production_readiness_percent": _readiness_percent(checks, include_production=True),
        "public_url": public_url,
        "health_url": health_url,
        "total_requests": inbound_status.get("total_requests", 0),
        "real_requests": real_requests,
        "smoke_requests": inbound_status.get("smoke_requests", 0),
        "latest_real_request": inbound_status.get("latest_real_request"),
        "checks": checks,
        "operator_next_step": _readiness_next_step(pilot_test_status, production_status, real_requests),
        "remaining_time_estimate": _readiness_remaining_time(pilot_test_status, real_requests),
        "artifacts": {
            "status_file": str(status_file),
            "verification_file": str(verification_file),
            "doc_qa_file": str(doc_qa_file),
            "security_audit_file": str(security_audit_file),
            "first_hit_file": str(first_hit_file),
            "db_snapshot_file": str(db_snapshot_file),
        },
    }

    markdown_path = Path(output_markdown)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_tmp = markdown_path.with_name(markdown_path.name + ".tmp")
    markdown_tmp.write_text(_readiness_gate_markdown(report), encoding="utf-8")
    markdown_tmp.replace(markdown_path)

    json_path = Path(output_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_tmp = json_path.with_name(json_path.name + ".tmp")
    json_tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    json_tmp.replace(json_path)

    report["output_markdown"] = str(markdown_path)
    report["output_json"] = str(json_path)
    return report


def build_pilot_completion_gate(
    db_path: str | Path,
    *,
    status_file: str | Path = "runtime/ais_inbound_public_endpoint_status.json",
    verification_file: str | Path = "runtime/ais_inbound_public_endpoint_verification.json",
    security_audit_file: str | Path = "runtime/ais_inbound_security_audit.json",
    db_snapshot_file: str | Path = "runtime/ais_inbound_db_snapshot_latest.json",
    readiness_gate_file: str | Path = "runtime/ais_inbound_readiness_gate.json",
    green_gate_file: str | Path = "runtime/green_gate_tracker.md",
    production_gate_file: str | Path = "runtime/production_readiness_gate.md",
    share_pack_zip: str | Path = "runtime/shareable_pea_pitch_pack.zip",
    share_pack_dir: str | Path = "runtime/shareable_pea_pitch_pack",
    chatgpt_round2_file: str | Path = "runtime/browser_chatgpt_visual_review_response_round2.md",
    chatgpt_round3_file: str | Path = "runtime/browser_chatgpt_visual_review_response_round3.md",
    output_markdown: str | Path = "runtime/pilot_completion_gate.md",
    output_json: str | Path = "runtime/pilot_completion_gate.json",
) -> dict[str, Any]:
    """Build the final Pilot Complete gate without approving production ETR sending."""
    status = _read_json_file(status_file)
    verification = _read_json_file(verification_file)
    security_audit = _read_json_file(security_audit_file)
    db_snapshot = _read_json_file(db_snapshot_file)
    readiness_gate = _read_json_file(readiness_gate_file)
    green_gate_text = _read_text_file(green_gate_file)
    production_gate_text = _read_text_file(production_gate_file)
    inbound_status = build_ais_inbound_status_report(db_path, output=None, limit=10)

    real_requests = int(inbound_status.get("real_requests") or 0)
    callback_counts = inbound_status.get("callback_status_counts") or {}
    checks = [
        _gate_check(
            "endpoint_health",
            status.get("primary_health_smoke") == "200_OK" or _verification_check_ok(verification, "health"),
            "Health endpoint passed.",
            "Health endpoint is missing or failing.",
        ),
        _gate_check(
            "auth_smoke",
            (
                status.get("primary_auth_post_smoke") == "202_RECEIVED"
                and status.get("primary_unauth_post_smoke") == "401_UNAUTHORIZED"
            )
            or (
                _verification_check_ok(verification, "authorized_alias_post")
                and _verification_check_ok(verification, "unauthorized_post")
            ),
            "Authorized POST returns 202 and unauthorized POST returns 401.",
            "Auth smoke has not proven both 202 authorized and 401 unauthorized paths.",
        ),
        _gate_check(
            "status_lookup",
            _verification_check_ok(verification, "status_lookup_contract")
            or _verification_check_ok(verification, "status_lookup"),
            "Status lookup contract passed.",
            "Status lookup contract is missing or failing.",
        ),
        _gate_check(
            "duplicate_idempotency",
            int(callback_counts.get("SKIPPED_DUPLICATE") or 0) > 0
            or int(callback_counts.get("DUPLICATE") or 0) > 0,
            "Duplicate request_id path is captured without reprocessing production send.",
            "Duplicate/idempotency evidence is missing.",
        ),
        _gate_check(
            "sqlite_evidence_queryable",
            isinstance(inbound_status.get("total_requests"), int)
            and int(inbound_status.get("total_requests") or 0) > 0,
            "SQLite inbound request/callback evidence is queryable.",
            "SQLite inbound evidence is missing or empty.",
        ),
        _gate_check(
            "real_ais_hits",
            real_requests > 0,
            "Real AIS pilot requests have reached the endpoint.",
            "No real AIS pilot request has reached the endpoint yet.",
        ),
        _gate_check(
            "db_snapshot",
            _db_snapshot_evidence_ok(db_snapshot),
            "Latest SQLite snapshot passed integrity/count checks.",
            "Latest SQLite snapshot is missing or not integrity-checked.",
            severity="WARN",
        ),
        _gate_check(
            "security_privacy_scan",
            _security_audit_passed(security_audit),
            "Security/privacy audit passed for shareable AIS artifacts.",
            "Security/privacy audit is missing or failing.",
        ),
        _gate_check(
            "share_pack_freshness",
            _share_pack_ready(share_pack_zip, share_pack_dir),
            "Shareable delivery pack exists with an inventory.",
            "Shareable delivery pack or inventory is missing.",
        ),
        _gate_check(
            "production_guardrail",
            _all_shadow_blocked(status, verification, security_audit, db_snapshot, readiness_gate, inbound_status),
            "All checked reports keep mode=shadow and production_send=blocked.",
            "Shadow/blocked production guardrail is not proven.",
        ),
        _gate_check(
            "chatgpt_copilot_audit",
            _chatgpt_copilot_logged(chatgpt_round2_file, chatgpt_round3_file),
            "ChatGPT co-pilot review/audit notes exist; Codex remains final QA owner.",
            "ChatGPT co-pilot audit is partial; local QA remains the fallback.",
            severity="WARN",
        ),
        _gate_check(
            "production_infra",
            False,
            "Production infrastructure is approved.",
            "Production infra remains pending: local tunnel/shared pilot key/local SQLite are pilot-only.",
            severity="WARN",
        ),
        _gate_check(
            "green_auto_etr_gate",
            _green_gate_passed(green_gate_text, production_gate_text),
            "Green auto-ETR gate passed.",
            "Auto ETR remains blocked; green rows and owner approval are not production-ready.",
            severity="WARN",
        ),
    ]

    critical_failures = [check for check in checks if check["status"] == "FAIL"]
    pilot_complete_status = "PILOT_COMPLETE" if not critical_failures else "PILOT_INCOMPLETE"
    green_status = "READY_FOR_TRL8_GATE" if _green_gate_passed(green_gate_text, production_gate_text) else "BLOCKED_GREEN_GATE"
    production_auto_etr_status = green_status
    if "local tunnel" in production_gate_text.lower() or "local_tunnel" in production_gate_text.lower():
        production_auto_etr_status = f"{production_auto_etr_status}_AND_PRODUCTION_INFRA"
    latest_real = _latest_real_request_summary(inbound_status.get("latest_real_request"))

    report = {
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "mode": "shadow",
        "production_send": "blocked",
        "pilot_complete_status": pilot_complete_status,
        "production_infra_status": "PENDING_PEA_APPROVED_GATEWAY",
        "production_auto_etr_status": production_auto_etr_status,
        "total_requests": inbound_status.get("total_requests", 0),
        "real_requests": real_requests,
        "smoke_requests": inbound_status.get("smoke_requests", 0),
        "latest_real_request": latest_real,
        "checks": checks,
        "pilot_blockers": [check for check in critical_failures],
        "production_blockers": [
            "PEA-approved HTTPS/API gateway, hardened auth, monitoring, durable DB/backup, owner approval",
            "Green auto-ETR gate needs >=30 green rows plus model/coverage thresholds and owner approval",
        ],
        "operator_commands": {
            "endpoint_restart": "powershell -ExecutionPolicy Bypass -File .\\runtime\\start_ais_inbound_public_endpoint.ps1",
            "hit_check": "powershell -ExecutionPolicy Bypass -File .\\runtime\\ais_inbound_hit_check.ps1",
            "final_qa": "powershell -ExecutionPolicy Bypass -File .\\runtime\\pilot_complete_final_qa.ps1",
            "pilot_gate": "python -m ais_etr pilot-completion-gate",
        },
        "artifacts": {
            "status_file": str(status_file),
            "verification_file": str(verification_file),
            "security_audit_file": str(security_audit_file),
            "db_snapshot_file": str(db_snapshot_file),
            "readiness_gate_file": str(readiness_gate_file),
            "green_gate_file": str(green_gate_file),
            "production_gate_file": str(production_gate_file),
            "share_pack_zip": str(share_pack_zip),
        },
    }

    markdown_path = Path(output_markdown)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_tmp = markdown_path.with_name(markdown_path.name + ".tmp")
    markdown_tmp.write_text(_pilot_completion_gate_markdown(report), encoding="utf-8")
    markdown_tmp.replace(markdown_path)

    json_path = Path(output_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_tmp = json_path.with_name(json_path.name + ".tmp")
    json_tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    json_tmp.replace(json_path)

    report["output_markdown"] = str(markdown_path)
    report["output_json"] = str(json_path)
    return report


def replay_ais_inbound_callbacks(
    db_path: str | Path,
    *,
    callback_url: str,
    request_id: str | None = None,
    statuses: tuple[str, ...] = ("CAPTURED_NO_CALLBACK_URL", "ERROR", "HTTP_ERROR"),
    limit: int = 20,
    callbacks_output: str | Path | None = DEFAULT_CALLBACK_LOG,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Replay stored shadow callback payloads to an AIS callback URL."""
    if not callback_url:
        raise ValueError("callback_url is required for callback replay")
    rows = _load_callback_replay_candidates(db_path, request_id=request_id, statuses=statuses, limit=limit)
    replayed: list[dict[str, Any]] = []
    for row in rows:
        payload = _safe_json_loads(row.get("payload_json"))
        if payload.get("mode") != "shadow" or payload.get("decision", {}).get("production_send") != "blocked":
            replayed.append(
                {
                    "request_id": row.get("request_id"),
                    "previous_status": row.get("status"),
                    "replay_status": "SKIPPED_UNSAFE_PAYLOAD",
                    "status_code": "",
                }
            )
            continue
        if dry_run:
            replayed.append(
                {
                    "request_id": row.get("request_id"),
                    "previous_status": row.get("status"),
                    "replay_status": "DRY_RUN",
                    "status_code": "",
                }
            )
            continue
        record = _send_or_capture_callback(
            payload,
            callback_url=callback_url,
            callbacks_output=callbacks_output,
            post_callback=True,
        )
        _persist_callback(db_path, str(row.get("request_id") or ""), callback_url, payload, record)
        replayed.append(
            {
                "request_id": row.get("request_id"),
                "previous_status": row.get("status"),
                "replay_status": record.status,
                "status_code": _blank_if_none(record.status_code),
            }
        )
    return {
        "mode": "shadow",
        "production_send": "blocked",
        "callback_url_configured": bool(callback_url),
        "dry_run": dry_run,
        "request_id": request_id or "",
        "statuses": list(statuses),
        "candidate_count": len(rows),
        "replayed_count": len(replayed),
        "results": replayed,
    }


class AisInboundHandler(BaseHTTPRequestHandler):
    server_version = "AisEtrInboundApi/1.0"

    def do_GET(self) -> None:
        request_path = _request_path_only(self.path)
        health_paths = {
            "/health",
            "/api/health",
            f"{getattr(self.server, 'inbound_path', DEFAULT_INBOUND_PATH)}/health",
        }
        if request_path in health_paths:
            self._send_json(
                200,
                {
                    "status": "OK",
                    "mode": "shadow",
                    "api_version": API_VERSION,
                    "service": "ais_inbound_outage_verification",
                    "production_send": "blocked",
                    "inbound_path": getattr(self.server, "inbound_path", DEFAULT_INBOUND_PATH),
                },
            )
            return
        status_request_id = _status_request_id_from_path(
            request_path,
            getattr(self.server, "inbound_path", DEFAULT_INBOUND_PATH),
        )
        if status_request_id:
            if not _authorized(self.headers, getattr(self.server, "api_key", None)):
                self._send_json(401, _error_payload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required"))
                return
            result = _load_inbound_request_status(getattr(self.server, "db_path"), status_request_id)
            if result is None:
                self._send_json(
                    404,
                    _error_payload(
                        "REQUEST_NOT_FOUND",
                        "No AIS inbound request was found for this request_id",
                        request_id=status_request_id,
                    ),
                )
                return
            self._send_json(200, result, headers={"X-Request-ID": status_request_id})
            return
        if _is_inbound_path(request_path, getattr(self.server, "inbound_path", DEFAULT_INBOUND_PATH)):
            self._send_json(
                200,
                {
                    "status": "READY",
                    "mode": "shadow",
                    "api_version": API_VERSION,
                    "method": "POST",
                    "required_headers": [
                        "Content-Type: application/json",
                        "X-API-Key",
                        "bypass-tunnel-reminder: true",
                    ],
                    "status_lookup": f"{getattr(self.server, 'inbound_path', DEFAULT_INBOUND_PATH)}/{{request_id}}",
                    "production_send": "blocked",
                },
            )
            return
        self._send_json(404, _error_payload("NOT_FOUND", "Unknown endpoint"))

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key, Authorization, bypass-tunnel-reminder")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_POST(self) -> None:
        request_path = _request_path_only(self.path)
        if not _is_inbound_path(request_path, getattr(self.server, "inbound_path", DEFAULT_INBOUND_PATH)):
            self._send_json(404, _error_payload("NOT_FOUND", "Unknown endpoint"))
            return
        rate_allowed, rate_headers = _rate_limit_check(self.server, self.headers, self.client_address)
        if not rate_allowed:
            self._send_json(
                429,
                _error_payload("RATE_LIMITED", "Too many requests; retry after the Retry-After header value"),
                headers=rate_headers,
            )
            return
        if not _authorized(self.headers, getattr(self.server, "api_key", None)):
            self._send_json(401, _error_payload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required"))
            return
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type.lower():
            self._send_json(415, _error_payload("UNSUPPORTED_MEDIA_TYPE", "Content-Type must be application/json"))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, _error_payload("INVALID_CONTENT_LENGTH", "Content-Length must be an integer"))
            return
        if length > MAX_BODY_BYTES:
            # Drain the bounded pilot-size overflow so normal clients receive the
            # controlled 413 JSON response instead of a connection reset.
            self.rfile.read(min(length, MAX_BODY_BYTES + 1))
            self.close_connection = True
            self._send_json(
                413,
                _error_payload("PAYLOAD_TOO_LARGE", "Request body is too large"),
                headers={"Connection": "close"},
            )
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._send_json(400, _error_payload("INVALID_JSON", "Request body must be valid JSON"))
            return
        if not isinstance(payload, dict):
            self._send_json(400, _error_payload("INVALID_PAYLOAD", "Request body must be a JSON object"))
            return
        try:
            result = process_ais_inbound_request(
                db_path=getattr(self.server, "db_path"),
                payload=payload,
                callback_url=getattr(self.server, "callback_url", None),
                requests_output=getattr(self.server, "requests_output", DEFAULT_REQUEST_LOG),
                callbacks_output=getattr(self.server, "callbacks_output", DEFAULT_CALLBACK_LOG),
                match_window_minutes=getattr(self.server, "match_window_minutes", DEFAULT_MATCH_WINDOW_MINUTES),
                post_callback=getattr(self.server, "post_callback", True),
            )
        except AisInboundValidationError as exc:
            self._send_json(400, _error_payload("INVALID_REQUEST", str(exc), request_id=_first_text(payload, "request_id", "requestId")))
            return
        response_headers = dict(rate_headers)
        response_headers["X-Request-ID"] = result.request_id
        self._send_json(202, result.accepted_response, headers=response_headers)

    def _send_json(self, status_code: int, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def _normalize_inbound_payload(payload: dict[str, Any]) -> dict[str, Any]:
    request_id = _first_text(
        payload,
        "request_id",
        "requestId",
        "event_id",
        "eventId",
        "alarm_id",
        "alarmId",
        "alarm_no",
        "alarmNo",
        "ticket_id",
        "ticketId",
        "job_id",
        "jobId",
        "transaction_id",
        "transactionId",
    )
    peano = _first_text(
        payload,
        "peano",
        "PEANO",
        "meter_no",
        "meterNo",
        "meter_number",
        "meterNumber",
        "meter_id",
        "meterId",
        "meter",
        "pea_meter_no",
        "peaMeterNo",
        "pea_no",
        "peaNo",
    )
    detected_at = _first_text(
        payload,
        "detected_at",
        "detectedAt",
        "timestamp",
        "timeStamp",
        "event_time",
        "eventTime",
        "occurred_at",
        "occurredAt",
        "outage_start_time",
        "outageStartTime",
        "first_occurred_on",
        "firstOccurredOn",
        "create_date",
        "createDate",
        "CREATE_DATE",
    )
    if not request_id:
        raise AisInboundValidationError("request_id is required")
    if not peano:
        raise AisInboundValidationError("meter_no or peano is required")
    if not detected_at:
        raise AisInboundValidationError("timestamp or detected_at is required")
    request_id = _validate_safe_identifier(
        request_id,
        field_name="request_id",
        max_chars=MAX_REQUEST_ID_CHARS,
    )
    peano = _validate_safe_identifier(
        peano,
        field_name="meter_no",
        max_chars=MAX_METER_CHARS,
    )
    parsed_detected_at = _parse_time(detected_at)
    timestamp_quality = _timestamp_quality(detected_at, parsed_detected_at)
    return {
        "request_id": request_id,
        "peano": peano,
        "detected_at": _iso_utc(parsed_detected_at),
        "detected_at_original": detected_at,
        "timestamp_quality": timestamp_quality,
        "province": _bounded_optional_text(
            _first_text(payload, "province", "provinceName", "จังหวัด"),
            field_name="province",
            max_chars=MAX_AREA_CHARS,
        ),
        "district": _bounded_optional_text(
            _first_text(payload, "district", "districtName", "amphoe", "amphur", "อำเภอ"),
            field_name="district",
            max_chars=MAX_AREA_CHARS,
        ),
        "subdistrict": _bounded_optional_text(
            _first_text(payload, "subdistrict", "subDistrict", "subdistrictName", "tambon", "tambonName", "ตำบล"),
            field_name="subdistrict",
            max_chars=MAX_AREA_CHARS,
        ),
        "alarm_type": _bounded_optional_text(
            _first_text(payload, "alarm_type", "alarmType", "alarm"),
            field_name="alarm_type",
            max_chars=MAX_CAUSE_CHARS,
        ),
        "main_cause": _bounded_optional_text(
            _first_text(payload, "main_cause", "mainCause", "maincause", "MAINCAUSE"),
            field_name="main_cause",
            max_chars=MAX_CAUSE_CHARS,
        ),
        "subcause": _bounded_optional_text(
            _first_text(payload, "subcause", "subCause", "sub_cause", "subcause2", "subCause2", "SUBCAUSE2"),
            field_name="subcause",
            max_chars=MAX_CAUSE_CHARS,
        ),
        "raw": payload,
    }


def _first_text(payload: dict[str, Any], *keys: str) -> str | None:
    lower_payload = {str(name).lower(): value for name, value in payload.items()}
    for key in keys:
        value = payload.get(key)
        if value is None:
            value = lower_payload.get(key.lower())
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _validate_safe_identifier(value: str, *, field_name: str, max_chars: int) -> str:
    text = str(value).strip()
    if not text:
        raise AisInboundValidationError(f"{field_name} is required")
    if len(text) > max_chars:
        raise AisInboundValidationError(f"{field_name} must be {max_chars} characters or fewer")
    if not SAFE_IDENTIFIER_RE.match(text):
        raise AisInboundValidationError(
            f"{field_name} may contain only letters, numbers, dash, underscore, dot, colon, or at sign"
        )
    return text


def _bounded_optional_text(value: str | None, *, field_name: str, max_chars: int) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) > max_chars:
        raise AisInboundValidationError(f"{field_name} must be {max_chars} characters or fewer")
    return text


def _request_exists(db: RuntimeDb, request_id: str) -> bool:
    with db.session() as conn:
        row = conn.execute("SELECT 1 FROM ais_inbound_requests WHERE request_id = ? LIMIT 1", (request_id,)).fetchone()
        return row is not None


def _persist_inbound_result(
    db: RuntimeDb,
    request: dict[str, Any],
    accepted_response: dict[str, Any],
    callback_status: str,
) -> None:
    now = accepted_response.get("received_at") or utc_now_iso()
    with db.session() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO ais_inbound_requests (
                request_id, received_at, peano_hash, peano_last4, detected_at,
                province, district, subdistrict, request_json, response_json,
                callback_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request["request_id"],
                now,
                _hash_meter(request["peano"]),
                _last4(request["peano"]),
                request.get("detected_at"),
                request.get("province"),
                request.get("district"),
                request.get("subdistrict"),
                json.dumps(_redact_payload(request), ensure_ascii=False, sort_keys=True),
                json.dumps(accepted_response, ensure_ascii=False, sort_keys=True),
                callback_status,
            ),
        )


def _persist_callback(
    db_path: str | Path,
    request_id: str,
    callback_url: str | None,
    payload: dict[str, Any],
    record: NotificationRecord,
) -> None:
    db = RuntimeDb(db_path)
    db.init()
    with db.session() as conn:
        conn.execute(
            """
            INSERT INTO ais_inbound_callbacks (
                request_id, callback_url, mode, payload_json, status,
                status_code, response_text, sent_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                callback_url,
                payload.get("mode", "shadow"),
                json.dumps(_redact_payload(payload), ensure_ascii=False, sort_keys=True),
                record.status,
                record.status_code,
                record.response_text,
                utc_now_iso(),
            ),
        )


def _load_asset_by_peano(db: RuntimeDb, peano: str) -> CustomerAsset | None:
    assets = {asset.peano: asset for asset in db.load_customer_assets()}
    return assets.get(peano)


def _find_runtime_evidence(
    db: RuntimeDb,
    asset: CustomerAsset | None,
    detected_at: str | None,
    *,
    match_window_minutes: int,
) -> dict[str, Any]:
    if asset is None or not asset.confidence_eligible:
        return {"source": "topology", "match_level": "", "match_found": False}
    detected = _parse_time(detected_at) if detected_at else None
    candidates = _load_runtime_event_candidates(db)
    ranked = []
    for row in candidates:
        level = _asset_event_match_level(asset, row)
        if not level:
            continue
        try:
            event_time = _parse_time(row.get("event_time"))
        except AisInboundValidationError:
            continue
        delta = None
        if detected and event_time:
            delta = abs((event_time - detected).total_seconds()) / 60
            if delta > match_window_minutes:
                continue
        ranked.append((_level_rank(level), delta if delta is not None else 999999, row, level))
    if not ranked:
        return {
            "source": "topology",
            "match_level": "",
            "match_found": False,
            "reason": "meter_in_registry_but_no_recent_webex_match",
        }
    ranked.sort(key=lambda item: (item[0], item[1]))
    _, delta, row, level = ranked[0]
    return {
        "source": "WebEx + topology",
        "match_found": True,
        "match_level": level,
        "match_confidence": _match_confidence(level),
        "event_id": row.get("event_id"),
        "webex_message_id": row.get("webex_message_id"),
        "event_time": row.get("event_time"),
        "device_type": row.get("device_type"),
        "device_id": row.get("device_id"),
        "feeder": row.get("feeder"),
        "time_delta_minutes": None if delta == 999999 else round(float(delta), 2),
        "prediction": {
            "etr_minutes_p50": row.get("etr_minutes_p50"),
            "q10": row.get("q10"),
            "q90": row.get("q90"),
            "risk_level": row.get("risk_level"),
            "model_version": row.get("model_version"),
        },
    }


def _load_runtime_event_candidates(db: RuntimeDb) -> list[dict[str, Any]]:
    with db.session() as conn:
        try:
            rows = conn.execute(
                """
                WITH latest_predictions AS (
                    SELECT p.*
                    FROM predictions p
                    INNER JOIN (
                        SELECT event_id, MAX(id) AS max_id
                        FROM predictions
                        GROUP BY event_id
                    ) latest ON latest.max_id = p.id
                )
                SELECT
                    e.event_id,
                    e.webex_message_id,
                    e.event_time,
                    e.device_type,
                    e.device_id,
                    e.feeder,
                    p.model_version,
                    p.etr_minutes_p50,
                    p.q10,
                    p.q90,
                    p.risk_level
                FROM outage_events e
                LEFT JOIN latest_predictions p ON p.event_id = e.event_id
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [dict(row) for row in rows]


def _asset_event_match_level(asset: CustomerAsset, row: dict[str, Any]) -> str:
    device_id = normalize_device_id(row.get("device_id"))
    feeder = normalize_feeder(row.get("feeder"))
    if device_id:
        if device_id in asset.cb_ids:
            return "cb"
        if device_id in asset.recloser_ids:
            return "recloser"
        if device_id in asset.switch_ids:
            return "switch"
        if device_id in {asset.transformer_id, asset.transformer_peano}:
            return "transformer"
    if feeder and feeder == asset.feeder:
        return "feeder"
    return ""


def _level_rank(level: str) -> int:
    return {"cb": 0, "recloser": 1, "switch": 2, "transformer": 3, "feeder": 4}.get(level, 99)


def _match_confidence(level: str) -> float:
    return {"cb": 0.95, "recloser": 0.9, "switch": 0.86, "transformer": 0.72, "feeder": 0.35}.get(level, 0)


def _classify_cause_lane(request: dict[str, Any]) -> str:
    text = f"{request.get('main_cause', '')} {request.get('subcause', '')}".lower()
    if "pea activity" in text:
        return "pea_activity"
    if "pea no back up" in text or "pea no backup" in text:
        return "pea_no_backup"
    if "faulty ac main" in text or "ac main" in text:
        return "ac_main_uncategorized"
    if text.strip():
        return "possibly_ais_equipment_or_backup"
    return "unknown"


def _build_callback_payload(
    request: dict[str, Any],
    asset: CustomerAsset | None,
    cause_lane: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    status, confidence, reason = _verification_status(asset, cause_lane, evidence)
    prediction = evidence.get("prediction") if evidence.get("match_found") else None
    etr = _etr_payload(status, prediction)
    decision = _decision_payload(status, confidence, reason, etr)
    return {
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "mode": "shadow",
        "request_id": request["request_id"],
        "status": status,
        "confidence": confidence,
        "decision": decision,
        "received": {
            "meter_ref": _redact_meter(request["peano"]),
            "detected_at": request["detected_at"],
            "detected_at_original": request.get("detected_at_original", request["detected_at"]),
            "timestamp_quality": request.get("timestamp_quality", {"status": "unknown", "flags": []}),
            "province": request.get("province"),
            "district": request.get("district"),
            "subdistrict": request.get("subdistrict"),
        },
        "pea_distribution": {
            "status": status,
            "reason": reason,
            "cause_lane": cause_lane,
        },
        "evidence": {
            "source": evidence.get("source"),
            "match_found": bool(evidence.get("match_found")),
            "match_level": evidence.get("match_level") or "",
            "match_confidence": evidence.get("match_confidence") or 0,
            "device_type": evidence.get("device_type") or "",
            "device_id": evidence.get("device_id") or "",
            "feeder": evidence.get("feeder") or (asset.feeder if asset else ""),
            "event_time": evidence.get("event_time") or "",
            "time_delta_minutes": evidence.get("time_delta_minutes"),
            "note": evidence.get("reason") or "",
        },
        "etr": etr,
        "generated_at": utc_now_iso(),
    }


def _verification_status(
    asset: CustomerAsset | None,
    cause_lane: str,
    evidence: dict[str, Any],
) -> tuple[str, str, str]:
    if cause_lane == "pea_activity":
        return "PLANNED_OR_PEA_ACTIVITY", "MEDIUM", "ais_labeled_pea_activity"
    if cause_lane == "possibly_ais_equipment_or_backup":
        return "LIKELY_AIS_EQUIPMENT_OR_BACKUP", "LOW", "ais_subcause_points_to_non_pea_equipment_or_backup"
    if asset is None:
        return "NO_PEA_EVIDENCE_FOUND", "LOW", "meter_not_found_in_runtime_registry"
    if not asset.confidence_eligible:
        return "UNCERTAIN_NEEDS_REVIEW", "LOW", "meter_mapping_not_confidence_eligible"
    if evidence.get("match_found") and evidence.get("match_level") in CONFIDENT_LEVELS:
        return "CONFIRMED_PEA_OUTAGE", "HIGH", "confident_meter_to_protection_and_webex_match"
    if evidence.get("match_found") and evidence.get("match_level") == "feeder":
        return "UNCERTAIN_NEEDS_REVIEW", "MEDIUM", "feeder_match_is_audit_only"
    return "UNCERTAIN_NEEDS_REVIEW", "MEDIUM", "meter_in_registry_but_no_recent_webex_match"


def _etr_payload(status: str, prediction: dict[str, Any] | None) -> dict[str, Any]:
    if status != "CONFIRMED_PEA_OUTAGE":
        return {
            "status": "NOT_READY_FOR_AUTO_SEND",
            "reason": "verification_not_confirmed_for_auto_etr",
        }
    if not prediction or prediction.get("etr_minutes_p50") is None:
        return {
            "status": "NOT_READY_FOR_AUTO_SEND",
            "reason": "no_runtime_prediction_for_matched_event",
        }
    return {
        "status": "SHADOW_ONLY",
        "etr_minutes_p50": prediction.get("etr_minutes_p50"),
        "q10": prediction.get("q10"),
        "q90": prediction.get("q90"),
        "risk_level": prediction.get("risk_level"),
        "model_version": prediction.get("model_version"),
        "production_gate": "blocked_until_green_subset_passes",
    }


def _decision_payload(status: str, confidence: str, reason: str, etr: dict[str, Any]) -> dict[str, Any]:
    pea_outage: bool | None
    answer: str
    next_action: str
    if status == "CONFIRMED_PEA_OUTAGE":
        pea_outage = True
        answer = "confirmed_pea_distribution_outage"
        next_action = "shadow_etr_available" if etr.get("status") == "SHADOW_ONLY" else "operator_review_before_etr"
    elif status in {"LIKELY_AIS_EQUIPMENT_OR_BACKUP"}:
        pea_outage = False
        answer = "not_confirmed_as_pea_distribution_outage"
        next_action = "ais_internal_or_backup_review"
    elif status == "PLANNED_OR_PEA_ACTIVITY":
        pea_outage = True
        answer = "pea_activity_or_planned_context"
        next_action = "confirm_activity_window_before_customer_message"
    elif status == "NO_PEA_EVIDENCE_FOUND":
        pea_outage = None
        answer = "no_pea_evidence_found"
        next_action = "keep_monitoring_or_manual_review"
    else:
        pea_outage = None
        answer = "uncertain_needs_review"
        next_action = "manual_review_required"
    return {
        "pea_distribution_outage": pea_outage,
        "answer": answer,
        "confidence": confidence,
        "reason": reason,
        "auto_customer_etr_allowed": False,
        "production_send": "blocked",
        "next_action": next_action,
    }


def _accepted_response(request: dict[str, Any], *, callback_status: str, duplicate: bool) -> dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "mode": "shadow",
        "status": "RECEIVED",
        "http_status": 202,
        "request_id": request["request_id"],
        "duplicate": duplicate,
        "callback_status": callback_status,
        "result_path": f"{DEFAULT_INBOUND_PATH}/{urllib.parse.quote(request['request_id'], safe='')}",
        "production_send": "blocked",
        "received_at": utc_now_iso(),
    }


def _build_duplicate_callback(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "mode": "shadow",
        "request_id": request["request_id"],
        "status": "DUPLICATE_REQUEST",
        "confidence": "HIGH",
        "decision": {
            "pea_distribution_outage": None,
            "answer": "duplicate_request_not_reprocessed",
            "confidence": "HIGH",
            "reason": "request_id_already_received",
            "auto_customer_etr_allowed": False,
            "production_send": "blocked",
            "next_action": "query_existing_request_status",
        },
        "pea_distribution": {
            "status": "DUPLICATE_REQUEST",
            "reason": "request_id_already_received",
        },
        "etr": {
            "status": "NOT_READY_FOR_AUTO_SEND",
            "reason": "duplicate_request_not_reprocessed",
        },
        "generated_at": utc_now_iso(),
    }


def _send_or_capture_callback(
    payload: dict[str, Any],
    *,
    callback_url: str | None,
    callbacks_output: str | Path | None,
    post_callback: bool,
) -> NotificationRecord:
    if payload.get("mode") != "shadow":
        raise ValueError("AIS inbound callback simulator only allows shadow payloads")
    if not callback_url or not post_callback:
        record = NotificationRecord(payload=payload, status="CAPTURED_NO_CALLBACK_URL")
        _append_jsonl(callbacks_output, _redacted_callback_log(payload, record, callback_url))
        return record
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        callback_url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            record = NotificationRecord(payload=payload, status="SENT", status_code=resp.status, response_text=body[:1000])
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        record = NotificationRecord(payload=payload, status="HTTP_ERROR", status_code=exc.code, response_text=body[:1000])
    except Exception as exc:
        record = NotificationRecord(payload=payload, status="ERROR", response_text=str(exc)[:1000])
    _append_jsonl(callbacks_output, _redacted_callback_log(payload, record, callback_url))
    return record


def _redacted_callback_log(
    payload: dict[str, Any],
    record: NotificationRecord,
    callback_url: str | None,
) -> dict[str, Any]:
    return {
        "sent_at": utc_now_iso(),
        "callback_url_configured": bool(callback_url),
        "status": record.status,
        "status_code": record.status_code,
        "payload": _redact_payload(payload),
    }


def _redact_payload(value: Any, key: str | None = None) -> Any:
    if key and key.lower() in SENSITIVE_KEYS:
        return "REDACTED"
    if key and key.lower() in METER_KEYS:
        return _redact_meter(str(value))
    if key == "raw":
        return _redact_payload(value)
    if isinstance(value, dict):
        return {name: _redact_payload(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_redact_payload(item, key) for item in value]
    return value


def _redact_meter(value: str) -> dict[str, str]:
    return {"hash": _hash_meter(value), "last4": _last4(value)}


def _hash_meter(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _last4(value: str) -> str:
    text = str(value)
    return text[-4:] if len(text) >= 4 else text


def _append_jsonl(path: str | Path | None, row: dict[str, Any]) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _load_inbound_request_status(db_path: str | Path, request_id: str) -> dict[str, Any] | None:
    db = RuntimeDb(db_path)
    db.init()
    with db.session() as conn:
        request_row = conn.execute(
            """
            SELECT request_id, received_at, peano_hash, peano_last4, detected_at,
                   province, district, subdistrict, request_json, response_json, callback_status
            FROM ais_inbound_requests
            WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()
        if request_row is None:
            return None
        callback_row = conn.execute(
            """
            SELECT payload_json, status, status_code, sent_at
            FROM ais_inbound_callbacks
            WHERE request_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (request_id,),
        ).fetchone()
    callback_payload: dict[str, Any] | None = None
    if callback_row is not None:
        try:
            callback_payload = json.loads(callback_row["payload_json"])
        except json.JSONDecodeError:
            callback_payload = None
    request_payload = _safe_json_loads(request_row["request_json"])
    return {
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "mode": "shadow",
        "request_id": request_row["request_id"],
        "status": "COMPLETED" if callback_payload else "RECEIVED",
        "request_status": _safe_json_loads(request_row["response_json"]).get("status", "RECEIVED"),
        "callback_status": request_row["callback_status"],
        "production_send": "blocked",
        "received_at": request_row["received_at"],
        "detected_at": request_row["detected_at"],
        "detected_at_original": request_payload.get("detected_at_original", request_row["detected_at"]),
        "timestamp_quality": request_payload.get("timestamp_quality", {"status": "unknown", "flags": []}),
        "meter": {
            "hash": request_row["peano_hash"],
            "last4": request_row["peano_last4"],
        },
        "area": {
            "province": request_row["province"],
            "district": request_row["district"],
            "subdistrict": request_row["subdistrict"],
        },
        "result": callback_payload,
        "last_callback": None
        if callback_row is None
        else {
            "status": callback_row["status"],
            "status_code": callback_row["status_code"],
            "sent_at": callback_row["sent_at"],
        },
    }


def _safe_json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _load_inbound_status_items(db_path: str | Path) -> list[dict[str, Any]]:
    db = RuntimeDb(db_path)
    db.init()
    with db.session() as conn:
        rows = conn.execute(
            """
            WITH latest_callbacks AS (
                SELECT c.*
                FROM ais_inbound_callbacks c
                INNER JOIN (
                    SELECT request_id, MAX(id) AS max_id
                    FROM ais_inbound_callbacks
                    GROUP BY request_id
                ) latest ON latest.max_id = c.id
            )
            SELECT
                r.request_id,
                r.received_at,
                r.peano_hash,
                r.peano_last4,
                r.detected_at,
                r.province,
                r.district,
                r.subdistrict,
                r.request_json,
                r.response_json,
                r.callback_status AS request_callback_status,
                c.payload_json,
                c.status AS latest_callback_status,
                c.status_code,
                c.sent_at
            FROM ais_inbound_requests r
            LEFT JOIN latest_callbacks c ON c.request_id = r.request_id
            ORDER BY r.received_at ASC
            """
        ).fetchall()
    return [_inbound_status_item(dict(row)) for row in rows]


def _load_callback_replay_candidates(
    db_path: str | Path,
    *,
    request_id: str | None,
    statuses: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]]:
    db = RuntimeDb(db_path)
    db.init()
    statuses = tuple(status for status in statuses if status)
    if not statuses:
        return []
    placeholders = ",".join("?" for _ in statuses)
    params: list[Any] = list(statuses)
    request_filter = ""
    if request_id:
        request_filter = "AND c.request_id = ?"
        params.append(request_id)
    params.append(max(0, limit))
    with db.session() as conn:
        rows = conn.execute(
            f"""
            WITH latest_callbacks AS (
                SELECT c.*
                FROM ais_inbound_callbacks c
                INNER JOIN (
                    SELECT request_id, MAX(id) AS max_id
                    FROM ais_inbound_callbacks
                    GROUP BY request_id
                ) latest ON latest.max_id = c.id
            )
            SELECT request_id, payload_json, status, status_code, sent_at
            FROM latest_callbacks c
            WHERE c.status IN ({placeholders})
            {request_filter}
            ORDER BY c.id DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def _inbound_status_item(row: dict[str, Any]) -> dict[str, Any]:
    callback_payload = _safe_json_loads(row.get("payload_json"))
    accepted_response = _safe_json_loads(row.get("response_json"))
    request_payload = _safe_json_loads(row.get("request_json"))
    decision = callback_payload.get("decision") if isinstance(callback_payload.get("decision"), dict) else {}
    pea_distribution = (
        callback_payload.get("pea_distribution")
        if isinstance(callback_payload.get("pea_distribution"), dict)
        else {}
    )
    etr = callback_payload.get("etr") if isinstance(callback_payload.get("etr"), dict) else {}
    evidence = callback_payload.get("evidence") if isinstance(callback_payload.get("evidence"), dict) else {}
    request_id = str(row.get("request_id") or "")
    return {
        "request_id": request_id,
        "is_smoke": _is_smoke_request_id(request_id),
        "received_at": row.get("received_at"),
        "detected_at": row.get("detected_at"),
        "detected_at_original": request_payload.get("detected_at_original", row.get("detected_at")),
        "timestamp_quality": request_payload.get("timestamp_quality", {"status": "unknown", "flags": []}),
        "meter": {
            "hash": row.get("peano_hash"),
            "last4": row.get("peano_last4"),
        },
        "area": {
            "province": row.get("province") or "",
            "district": row.get("district") or "",
            "subdistrict": row.get("subdistrict") or "",
        },
        "request_status": accepted_response.get("status", "RECEIVED"),
        "callback_status": row.get("latest_callback_status") or row.get("request_callback_status") or "",
        "callback_status_code": row.get("status_code"),
        "callback_sent_at": row.get("sent_at"),
        "verification_status": callback_payload.get("status", ""),
        "confidence": callback_payload.get("confidence", ""),
        "decision_answer": decision.get("answer", ""),
        "decision_reason": decision.get("reason", pea_distribution.get("reason", "")),
        "pea_distribution_outage": decision.get("pea_distribution_outage"),
        "next_action": decision.get("next_action", ""),
        "match_found": bool(evidence.get("match_found")),
        "match_level": evidence.get("match_level", ""),
        "match_confidence": evidence.get("match_confidence", ""),
        "device_type": evidence.get("device_type", ""),
        "device_id": evidence.get("device_id", ""),
        "feeder": evidence.get("feeder", ""),
        "time_delta_minutes": evidence.get("time_delta_minutes"),
        "etr_status": etr.get("status", ""),
        "etr_minutes_p50": etr.get("etr_minutes_p50", ""),
        "q10": etr.get("q10", ""),
        "q90": etr.get("q90", ""),
        "risk_level": etr.get("risk_level", ""),
        "production_send": "blocked",
    }


def _is_smoke_request_id(request_id: str) -> bool:
    return any(str(request_id).startswith(prefix) for prefix in SMOKE_REQUEST_PREFIXES)


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _audit_export_row(item: dict[str, Any]) -> dict[str, Any]:
    area = item.get("area") or {}
    meter = item.get("meter") or {}
    return {
        "request_id": item.get("request_id") or "",
        "request_type": "smoke" if item.get("is_smoke") else "real",
        "received_at": item.get("received_at") or "",
        "detected_at": item.get("detected_at") or "",
        "detected_at_original": item.get("detected_at_original") or "",
        "timestamp_quality_status": (item.get("timestamp_quality") or {}).get("status", ""),
        "timestamp_quality_flags": ",".join((item.get("timestamp_quality") or {}).get("flags", [])),
        "province": area.get("province") or "",
        "district": area.get("district") or "",
        "subdistrict": area.get("subdistrict") or "",
        "meter_hash": meter.get("hash") or "",
        "meter_last4": meter.get("last4") or "",
        "verification_status": item.get("verification_status") or "",
        "decision_answer": item.get("decision_answer") or "",
        "decision_reason": item.get("decision_reason") or "",
        "confidence": item.get("confidence") or "",
        "pea_distribution_outage": _blank_if_none(item.get("pea_distribution_outage")),
        "next_action": item.get("next_action") or "",
        "match_found": str(bool(item.get("match_found"))).upper(),
        "match_level": item.get("match_level") or "",
        "match_confidence": _blank_if_none(item.get("match_confidence")),
        "device_type": item.get("device_type") or "",
        "device_id": item.get("device_id") or "",
        "feeder": item.get("feeder") or "",
        "time_delta_minutes": _blank_if_none(item.get("time_delta_minutes")),
        "etr_status": item.get("etr_status") or "",
        "etr_minutes_p50": _blank_if_none(item.get("etr_minutes_p50")),
        "q10": _blank_if_none(item.get("q10")),
        "q90": _blank_if_none(item.get("q90")),
        "risk_level": item.get("risk_level") or "",
        "callback_status": item.get("callback_status") or "",
        "callback_status_code": _blank_if_none(item.get("callback_status_code")),
        "production_send": item.get("production_send") or "blocked",
    }


def _blank_if_none(value: Any) -> str:
    return "" if value is None else str(value)


def _csv_safe(value: Any) -> str:
    text = _blank_if_none(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def _safe_snapshot_label(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "manual")).strip("-._")
    return text[:64] or "manual"


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_table_counts(db_path: str | Path, table_names: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    conn = sqlite3.connect(db_path)
    try:
        existing = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        for table in table_names:
            if table not in existing:
                counts[table] = 0
                continue
            counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()
    return counts


def _sqlite_integrity_check(db_path: str | Path) -> str:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return str(row[0] if row else "unknown")
    finally:
        conn.close()


def _db_snapshot_public_json(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "api_version": report["api_version"],
        "schema_version": report["schema_version"],
        "generated_at": report["generated_at"],
        "mode": report["mode"],
        "production_send": report["production_send"],
        "label": report["label"],
        "snapshot_path": report["snapshot_path"],
        "snapshot_sha256": report["snapshot_sha256"],
        "snapshot_bytes": report["snapshot_bytes"],
        "integrity_check": report["integrity_check"],
        "table_counts": report["table_counts"],
        "snapshot_table_counts": report["snapshot_table_counts"],
        "counts_match": report["counts_match"],
        "total_requests": report["total_requests"],
        "real_requests": report["real_requests"],
        "smoke_requests": report["smoke_requests"],
        "latest_real_request": report["latest_real_request"],
        "privacy_note": report["privacy_note"],
    }


def _read_json_file(path: str | Path) -> dict[str, Any]:
    try:
        return _safe_json_loads(Path(path).read_text(encoding="utf-8-sig"))
    except OSError:
        return {}


def _read_text_file(path: str | Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def _gate_check(
    name: str,
    ok: bool,
    pass_message: str,
    fail_message: str,
    *,
    severity: str = "FAIL",
) -> dict[str, str]:
    return {
        "name": name,
        "status": "PASS" if ok else severity,
        "message": pass_message if ok else fail_message,
    }


def _verification_check_ok(verification: dict[str, Any], name: str) -> bool:
    checks = verification.get("checks") if isinstance(verification.get("checks"), list) else []
    for check in checks:
        if isinstance(check, dict) and check.get("name") == name:
            return check.get("ok") is True
    return False


def _doc_qa_passed(markdown: str) -> bool:
    return "- Status: `PASS`" in markdown or "Status: PASS" in markdown


def _security_audit_passed(report: dict[str, Any]) -> bool:
    return (
        bool(report)
        and str(report.get("status") or "") == "PASS"
        and str(report.get("mode") or "") == "shadow"
        and str(report.get("production_send") or "") == "blocked"
        and not report.get("failures")
    )


def _all_shadow_blocked(*reports: dict[str, Any]) -> bool:
    for report in reports:
        if not report:
            continue
        mode = str(report.get("mode") or "shadow")
        production_send = str(report.get("production_send") or "blocked")
        if mode != "shadow" or production_send != "blocked":
            return False
    return True


def _db_snapshot_evidence_ok(report: dict[str, Any]) -> bool:
    if not report:
        return False
    return (
        str(report.get("mode") or "") == "shadow"
        and str(report.get("production_send") or "") == "blocked"
        and str(report.get("integrity_check") or "") == "ok"
        and report.get("counts_match") is True
        and bool(str(report.get("snapshot_path") or ""))
        and len(str(report.get("snapshot_sha256") or "")) == 64
    )


def _readiness_percent(checks: list[dict[str, str]], *, include_production: bool) -> int:
    selected = [
        check
        for check in checks
        if include_production or check["name"] not in {"first_real_ais_hit", "production_infra"}
    ]
    if not selected:
        return 0
    passed = sum(1 for check in selected if check["status"] == "PASS")
    return round((passed / len(selected)) * 100)


def _readiness_next_step(pilot_test_status: str, production_status: str, real_requests: int) -> str:
    if pilot_test_status != "READY_FOR_AIS_TEST":
        return "Restart or verify the endpoint, then rerun the public endpoint verifier."
    if real_requests <= 0:
        return "Ask AIS to send one real pilot request with the shared pilot key, then review the first-hit packet."
    if production_status == "BLOCKED_LOCAL_TUNNEL_PILOT":
        return "Review the real hit, keep production blocked, and move to permanent HTTPS infrastructure before production."
    return "Review the real hit and keep production blocked until the production gate is explicitly approved."


def _readiness_remaining_time(pilot_test_status: str, real_requests: int) -> str:
    if pilot_test_status != "READY_FOR_AIS_TEST":
        return "About 10-20 minutes after endpoint restart, depending on tunnel recovery."
    if real_requests <= 0:
        return "AIS can test now; expect 5-10 minutes to inspect evidence after the first real request arrives."
    return "Pilot evidence review can be done in about 5-10 minutes; production hardening still needs permanent HTTPS, monitoring, and approval."


def _share_pack_ready(zip_path: str | Path, pack_dir: str | Path) -> bool:
    zip_file = Path(zip_path)
    inventory = Path(pack_dir) / "package_inventory.json"
    return zip_file.exists() and zip_file.stat().st_size > 0 and inventory.exists()


def _chatgpt_copilot_logged(round2_file: str | Path, round3_file: str | Path) -> bool:
    round2 = _read_text_file(round2_file).strip()
    round3 = _read_text_file(round3_file).strip()
    return len(round2) >= 200 and len(round3) >= 20


def _green_gate_passed(green_gate_text: str, production_gate_text: str) -> bool:
    combined = f"{green_gate_text}\n{production_gate_text}".lower()
    blocked_markers = [
        "blocked",
        "green rows: `0`",
        "green rows = 0",
        "current green rows: 0",
        "blocked_too_few_green_rows",
        "blocked_no_green_subset",
    ]
    return bool(combined.strip()) and not any(marker in combined for marker in blocked_markers)


def _latest_real_request_summary(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    meter = item.get("meter") if isinstance(item.get("meter"), dict) else {}
    timestamp_quality = item.get("timestamp_quality") if isinstance(item.get("timestamp_quality"), dict) else {}
    return {
        "request_id": item.get("request_id") or "",
        "received_at": item.get("received_at") or "",
        "status": item.get("verification_status") or "",
        "callback_status": item.get("callback_status") or "",
        "decision": item.get("decision_answer") or "",
        "confidence": item.get("confidence") or "",
        "timestamp_quality_status": timestamp_quality.get("status") or "",
        "meter_last4": meter.get("last4") or "",
        "production_send": "blocked",
    }


def _inbound_audit_export_markdown(
    rows: list[dict[str, Any]],
    *,
    include_smoke: bool,
    total_requests: int,
    real_requests: int,
    smoke_requests: int,
    output_csv: Path,
) -> str:
    lines = [
        "# AIS Inbound Audit Export",
        "",
        f"Generated: `{utc_now_iso()}`",
        "",
        "## Summary",
        "",
        "- Mode: `shadow`",
        "- Production send: `blocked`",
        f"- Total requests: `{total_requests}`",
        f"- Real AIS requests: `{real_requests}`",
        f"- Smoke/test requests: `{smoke_requests}`",
        f"- Export includes smoke/test: `{str(include_smoke).lower()}`",
        f"- CSV: `{output_csv}`",
        "",
        "## Latest Exported Rows",
        "",
    ]
    if not rows:
        lines.append("No rows were exported for this filter.")
    else:
        lines.extend(
            [
                "| Received at | Request ID | Type | Time Quality | Decision | Confidence | Match | ETR | Callback | Meter last4 |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in rows[:20]:
            match = row.get("match_level") or ("matched" if row.get("match_found") == "TRUE" else "no_match")
            lines.append(
                "| "
                + " | ".join(
                    [
                        row.get("received_at", ""),
                        f"`{row.get('request_id', '')}`",
                        row.get("request_type", ""),
                        f"`{row.get('timestamp_quality_status', '')}`",
                        f"`{row.get('decision_answer', '')}`",
                        f"`{row.get('confidence', '')}`",
                        f"`{match}`",
                        f"`{row.get('etr_status', '')}`",
                        f"`{row.get('callback_status', '')}`",
                        row.get("meter_last4", ""),
                    ]
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "## Privacy And Safety",
            "",
            "- Full meter numbers are not exported; only hash and last4 are included.",
            "- API keys, callback secrets, WebEx room ids, verbatim WebEx text, and direct customer identity are not included.",
            "- PEA/SFSD/ReportPO rows are not used as restoration truth in this export.",
            "- Automatic customer ETR sending remains blocked.",
            "",
        ]
    )
    return "\n".join(lines)


def _db_snapshot_markdown(report: dict[str, Any]) -> str:
    latest = report.get("latest_real_request")
    lines = [
        "# AIS Inbound SQLite Snapshot",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Summary",
        "",
        f"- Mode: `{report['mode']}`",
        f"- Production send: `{report['production_send']}`",
        f"- Label: `{report['label']}`",
        f"- Snapshot file: `{report['snapshot_path']}`",
        f"- Snapshot SHA256: `{report['snapshot_sha256']}`",
        f"- Snapshot bytes: `{report['snapshot_bytes']}`",
        f"- SQLite integrity check: `{report['integrity_check']}`",
        f"- Source/snapshot counts match: `{str(report['counts_match']).lower()}`",
        f"- Total inbound requests: `{report['total_requests']}`",
        f"- Real AIS requests: `{report['real_requests']}`",
        f"- Smoke/test requests: `{report['smoke_requests']}`",
        "",
        "## Table Counts",
        "",
        "| Table | Source rows | Snapshot rows |",
        "| --- | ---: | ---: |",
    ]
    for table, count in report["table_counts"].items():
        lines.append(f"| `{table}` | {count} | {report['snapshot_table_counts'].get(table, 0)} |")
    lines.extend(["", "## Latest Real AIS Request", ""])
    if latest:
        meter = latest.get("meter") or {}
        area = latest.get("area") or {}
        lines.extend(
            [
                f"- Request ID: `{latest.get('request_id') or ''}`",
                f"- Received at: `{latest.get('received_at') or ''}`",
                f"- Verification status: `{latest.get('verification_status') or ''}`",
                f"- Callback status: `{latest.get('callback_status') or ''}`",
                f"- Decision: `{latest.get('decision_answer') or ''}`",
                f"- Area: `{area.get('province') or ''} / {area.get('district') or ''} / {area.get('subdistrict') or ''}`",
                f"- Meter last4: `{meter.get('last4') or ''}`",
                f"- Meter hash: `{meter.get('hash') or ''}`",
            ]
        )
    else:
        lines.append("No real AIS request has reached the endpoint yet.")
    lines.extend(
        [
            "",
            "## Privacy And Use",
            "",
            "- This snapshot is internal evidence and may contain raw stored runtime payloads.",
            "- Share this Markdown/JSON report by default, not the SQLite file.",
            "- Full meter numbers are not printed in this report.",
            "- `mode` remains `shadow` and `production_send` remains `blocked`.",
            "",
        ]
    )
    return "\n".join(lines)


def _first_hit_packet_markdown(packet: dict[str, Any]) -> str:
    latest = packet.get("latest_real_request")
    lines = [
        "# AIS Inbound First Real Hit Packet",
        "",
        f"Generated: `{utc_now_iso()}`",
        "",
        "## Summary",
        "",
        f"- Status: `{packet['status']}`",
        f"- Mode: `{packet['mode']}`",
        f"- Production send: `{packet['production_send']}`",
        f"- Total requests: `{packet['total_requests']}`",
        f"- Real AIS requests: `{packet['real_requests']}`",
        f"- Smoke/test requests: `{packet['smoke_requests']}`",
        "",
    ]
    if not latest:
        lines.extend(
            [
                "## Waiting State",
                "",
                "No real AIS request has reached the endpoint yet.",
                "",
                "Next step: keep the endpoint running and ask AIS to send one pilot request with the shared pilot key.",
            ]
        )
    else:
        area = latest.get("area") or {}
        meter = latest.get("meter") or {}
        lines.extend(
            [
                "## Latest Real AIS Request",
                "",
                f"- Request ID: `{latest.get('request_id') or ''}`",
                f"- Received at: `{latest.get('received_at') or ''}`",
                f"- Detected at: `{latest.get('detected_at') or ''}`",
                f"- Timestamp quality: `{(latest.get('timestamp_quality') or {}).get('status', '')}`",
                f"- Timestamp flags: `{', '.join((latest.get('timestamp_quality') or {}).get('flags', [])) or 'none'}`",
                f"- Request status: `{latest.get('request_status') or ''}`",
                f"- Verification status: `{latest.get('verification_status') or ''}`",
                f"- Callback status: `{latest.get('callback_status') or ''}`",
                f"- Decision: `{latest.get('decision_answer') or ''}`",
                f"- Reason: `{latest.get('decision_reason') or ''}`",
                f"- Confidence: `{latest.get('confidence') or ''}`",
                f"- Area: `{area.get('province') or ''} / {area.get('district') or ''} / {area.get('subdistrict') or ''}`",
                f"- Meter last4: `{meter.get('last4') or ''}`",
                f"- Meter hash: `{meter.get('hash') or ''}`",
                "",
                "## Evidence",
                "",
                f"- Match found: `{bool(latest.get('match_found'))}`",
                f"- Match level: `{latest.get('match_level') or ''}`",
                f"- Match confidence: `{_blank_if_none(latest.get('match_confidence'))}`",
                f"- Device: `{latest.get('device_type') or ''} {latest.get('device_id') or ''}`",
                f"- Feeder: `{latest.get('feeder') or ''}`",
                f"- Time delta minutes: `{_blank_if_none(latest.get('time_delta_minutes'))}`",
                f"- ETR status: `{latest.get('etr_status') or ''}`",
                "",
                "## Operator Action",
                "",
                "- Confirm this is a real AIS pilot request, not a smoke/test request.",
                "- Check whether the meter is in the runtime AIS registry and whether WebEx/topology evidence exists.",
                "- Keep automatic production sending blocked unless a separate production gate is approved.",
            ]
        )
    lines.extend(
        [
            "",
            "## Privacy And Safety",
            "",
            "- Full meter numbers are not included.",
            "- API keys, callback secrets, WebEx room ids, verbatim WebEx text, and direct customer identity are not included.",
            "- AIS outage/restore remains the customer-facing truth source.",
            "- PEA/SFSD/ReportPO remains context/quarantine unless owner-approved.",
            "",
        ]
    )
    return "\n".join(lines)


def _readiness_gate_markdown(report: dict[str, Any]) -> str:
    latest_real = report.get("latest_real_request")
    lines = [
        "# AIS Inbound Readiness Gate",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Executive Summary",
        "",
        f"- Pilot API test status: `{report['pilot_test_status']}`",
        f"- Production status: `{report['production_status']}`",
        f"- Pilot API test readiness: `{report['pilot_api_test_readiness_percent']}%`",
        f"- Production readiness: `{report['production_readiness_percent']}%`",
        f"- Mode: `{report['mode']}`",
        f"- Production send: `{report['production_send']}`",
        f"- Public URL: `{report.get('public_url') or 'missing'}`",
        f"- Health URL: `{report.get('health_url') or 'missing'}`",
        f"- Total requests: `{report.get('total_requests', 0)}`",
        f"- Real AIS requests: `{report.get('real_requests', 0)}`",
        f"- Smoke/test requests: `{report.get('smoke_requests', 0)}`",
        "",
        "## Gate Checks",
        "",
        "| Check | Status | Message |",
        "| --- | --- | --- |",
    ]
    for check in report.get("checks", []):
        lines.append(f"| `{check['name']}` | `{check['status']}` | {check['message']} |")

    lines.extend(
        [
            "",
            "## Latest Real AIS Request",
            "",
        ]
    )
    if latest_real:
        area = latest_real.get("area") or {}
        meter = latest_real.get("meter") or {}
        lines.extend(
            [
                f"- Request ID: `{latest_real.get('request_id') or ''}`",
                f"- Received at: `{latest_real.get('received_at') or ''}`",
                f"- Status: `{latest_real.get('verification_status') or ''}`",
                f"- Callback status: `{latest_real.get('callback_status') or ''}`",
                f"- Decision: `{latest_real.get('decision_answer') or ''}`",
                f"- Timestamp quality: `{(latest_real.get('timestamp_quality') or {}).get('status', '')}`",
                f"- Area: `{area.get('province') or ''} / {area.get('district') or ''} / {area.get('subdistrict') or ''}`",
                f"- Meter last4: `{meter.get('last4') or ''}`",
            ]
        )
    else:
        lines.append("No real AIS request has reached this endpoint yet.")

    lines.extend(
        [
            "",
            "## Operator Next Step",
            "",
            report["operator_next_step"],
            "",
            "## Remaining Time Estimate",
            "",
            report["remaining_time_estimate"],
            "",
            "## Production Guardrail",
            "",
            "- This gate does not approve production ETR sending.",
            "- The endpoint is acceptable for local pilot/API testing when the pilot test status is `READY_FOR_AIS_TEST`.",
            "- Permanent production still needs approved HTTPS hosting, monitoring, secret rotation, retry/queue policy, and owner approval.",
            "- AIS outage/restore remains the customer-facing truth source; WebEx is trigger/device evidence only.",
            "- PEA/SFSD/ReportPO remains context/quarantine unless owner-approved.",
            "",
            "## Artifacts",
            "",
        ]
    )
    for name, path in (report.get("artifacts") or {}).items():
        lines.append(f"- {name}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def _pilot_completion_gate_markdown(report: dict[str, Any]) -> str:
    latest_real = report.get("latest_real_request")
    lines = [
        "# PEA API Intellisense Pilot Completion Gate",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Decision",
        "",
        f"- Pilot status: `{report['pilot_complete_status']}`",
        "- Production live: `NO_GO`",
        f"- Production auto ETR: `{report['production_auto_etr_status']}`",
        f"- Mode: `{report['mode']}`",
        f"- Production send: `{report['production_send']}`",
        f"- Total inbound requests: `{report.get('total_requests', 0)}`",
        f"- Real AIS requests: `{report.get('real_requests', 0)}`",
        f"- Smoke/test requests: `{report.get('smoke_requests', 0)}`",
        "",
        "Pilot Complete means AIS/PEA can run the controlled shadow pilot with durable evidence, redacted audit exports, operator runbook, and delivery pack. It does not approve production customer-facing ETR automation.",
        "",
        "## Gate Checks",
        "",
        "| Check | Status | Message |",
        "| --- | --- | --- |",
    ]
    for check in report.get("checks", []):
        lines.append(f"| `{check['name']}` | `{check['status']}` | {check['message']} |")

    lines.extend(["", "## Latest Real AIS Request", ""])
    if latest_real:
        lines.extend(
            [
                f"- Request ID: `{latest_real.get('request_id') or ''}`",
                f"- Received at: `{latest_real.get('received_at') or ''}`",
                f"- Status: `{latest_real.get('status') or ''}`",
                f"- Callback status: `{latest_real.get('callback_status') or ''}`",
                f"- Decision: `{latest_real.get('decision') or ''}`",
                f"- Confidence: `{latest_real.get('confidence') or ''}`",
                f"- Timestamp quality: `{latest_real.get('timestamp_quality_status') or ''}`",
                f"- Meter last4: `{latest_real.get('meter_last4') or ''}`",
                f"- Production send: `{latest_real.get('production_send') or 'blocked'}`",
            ]
        )
    else:
        lines.append("No real AIS request has reached the endpoint yet.")

    lines.extend(
        [
            "",
            "## Go / No-Go",
            "",
            "| Lane | Decision | Why |",
            "| --- | --- | --- |",
            "| Controlled AIS API pilot | `GO` if pilot status is `PILOT_COMPLETE` | Shadow mode, durable SQLite evidence, redacted audit trail, API contract, operator runbook |",
            "| Production infrastructure | `NO_GO` | Needs PEA-approved HTTPS/API gateway, hardened auth, monitoring, durable DB/backup, and named owner approval |",
            "| Customer-facing auto ETR | `NO_GO` | Green gate is not passed; AIS outage/restore remains customer-facing truth |",
            "",
            "## Operator Commands",
            "",
        ]
    )
    for name, command in (report.get("operator_commands") or {}).items():
        lines.append(f"- {name}: `{command}`")

    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Do not send production callbacks from this gate.",
            "- Do not upload API keys, tokens, room ids, verbatim WebEx text, full meter/PEANO lists, customer identity, or raw runtime DB to ChatGPT or any external reviewer.",
            "- ChatGPT can review sanitized screenshots, redacted API contract text, scripts, and QA checklists only; Codex/operator remains responsible for final acceptance.",
            "- AIS outage/restore remains the customer-facing truth source; WebEx is trigger/device evidence only.",
            "- PEA/SFSD/ReportPO remains context/quarantine unless owner-approved.",
            "",
            "## Artifacts",
            "",
        ]
    )
    for name, path in (report.get("artifacts") or {}).items():
        lines.append(f"- {name}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def _inbound_status_markdown(report: dict[str, Any]) -> str:
    generated_at = utc_now_iso()
    latest_real = report.get("latest_real_request")
    lines = [
        "# AIS Inbound Request Status",
        "",
        f"Generated: `{generated_at}`",
        "",
        "## Summary",
        "",
        f"- Mode: `{report['mode']}`",
        f"- Production send: `{report['production_send']}`",
        f"- Total requests in SQLite: `{report['total_requests']}`",
        f"- Smoke/test requests: `{report['smoke_requests']}`",
        f"- Real AIS requests: `{report['real_requests']}`",
        "",
        "## Latest Real AIS Request",
        "",
    ]
    if latest_real:
        lines.extend(_inbound_status_item_lines(latest_real))
    else:
        lines.append("No real AIS request has reached the endpoint yet. Only smoke/test requests are present.")
    lines.extend(
        [
            "",
            "## Callback Status Counts",
            "",
            "| Callback status | Count |",
            "| --- | ---: |",
        ]
    )
    for status, count in report.get("callback_status_counts", {}).items():
        lines.append(f"| `{status}` | {count} |")
    lines.extend(
        [
            "",
            "## Decision Counts",
            "",
            "| Decision answer | Count |",
            "| --- | ---: |",
        ]
    )
    for decision, count in report.get("decision_counts", {}).items():
        lines.append(f"| `{decision}` | {count} |")
    lines.extend(
        [
            "",
            "## Recent Requests",
            "",
            "| Received at | Request ID | Type | Time Quality | Callback | Decision | Confidence | Meter last4 | Area |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in report.get("recent_requests", []):
        area = item.get("area") or {}
        area_text = " / ".join(part for part in [area.get("province"), area.get("district"), area.get("subdistrict")] if part)
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("received_at") or ""),
                    f"`{item.get('request_id') or ''}`",
                    "smoke" if item.get("is_smoke") else "real",
                    f"`{(item.get('timestamp_quality') or {}).get('status', '')}`",
                    f"`{item.get('callback_status') or ''}`",
                    f"`{item.get('decision_answer') or ''}`",
                    f"`{item.get('confidence') or ''}`",
                    str((item.get("meter") or {}).get("last4") or ""),
                    area_text,
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This report is built from the durable SQLite runtime tables.",
            "- Meter numbers are redacted to hash and last4 only.",
            "- No API key, WebEx room id, raw PEANO list, or raw customer identity is included.",
            "- Automatic customer ETR sending remains blocked.",
            "",
        ]
    )
    return "\n".join(lines)


def _inbound_status_item_lines(item: dict[str, Any]) -> list[str]:
    area = item.get("area") or {}
    meter = item.get("meter") or {}
    return [
        f"- Request ID: `{item.get('request_id')}`",
        f"- Received at: `{item.get('received_at')}`",
        f"- Detected at: `{item.get('detected_at')}`",
        f"- Timestamp quality: `{(item.get('timestamp_quality') or {}).get('status', '')}`",
        f"- Timestamp flags: `{', '.join((item.get('timestamp_quality') or {}).get('flags', [])) or 'none'}`",
        f"- Meter last4: `{meter.get('last4') or ''}`",
        f"- Area: `{area.get('province') or ''} / {area.get('district') or ''} / {area.get('subdistrict') or ''}`",
        f"- Callback status: `{item.get('callback_status') or ''}`",
        f"- Decision: `{item.get('decision_answer') or ''}`",
        f"- Confidence: `{item.get('confidence') or ''}`",
        f"- ETR status: `{item.get('etr_status') or ''}`",
        f"- Production send: `{item.get('production_send')}`",
    ]


def _error_payload(code: str, message: str, *, request_id: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "mode": "shadow",
        "status": "ERROR",
        "error": {
            "code": code,
            "message": message,
        },
        "production_send": "blocked",
        "generated_at": utc_now_iso(),
    }
    if request_id:
        payload["request_id"] = request_id
    return payload


def _rate_limit_check(server: Any, headers: Any, client_address: Any) -> tuple[bool, dict[str, str]]:
    limit = int(getattr(server, "rate_limit_per_minute", DEFAULT_RATE_LIMIT_PER_MINUTE) or 0)
    if limit <= 0:
        return True, {}
    window_seconds = 60.0
    now = time.monotonic()
    client_id = _rate_limit_client_id(headers, client_address)
    lock = getattr(server, "rate_limit_lock", None)
    state = getattr(server, "rate_limit_state", None)
    if state is None:
        state = {}
        setattr(server, "rate_limit_state", state)

    def update_state() -> tuple[bool, int]:
        timestamps = [stamp for stamp in state.get(client_id, []) if now - float(stamp) < window_seconds]
        if len(timestamps) >= limit:
            oldest = min(timestamps)
            retry_after = max(1, int(window_seconds - (now - oldest)) + 1)
            state[client_id] = timestamps
            return False, retry_after
        timestamps.append(now)
        state[client_id] = timestamps
        remaining = max(0, limit - len(timestamps))
        return True, remaining

    if lock is not None:
        with lock:
            allowed, value = update_state()
    else:
        allowed, value = update_state()
    headers_out = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Window": "60",
    }
    if allowed:
        headers_out["X-RateLimit-Remaining"] = str(value)
    else:
        headers_out["X-RateLimit-Remaining"] = "0"
        headers_out["Retry-After"] = str(value)
    return allowed, headers_out


def _rate_limit_client_id(headers: Any, client_address: Any) -> str:
    forwarded_for = str(headers.get("X-Forwarded-For") or "").strip()
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    if isinstance(client_address, tuple) and client_address:
        return str(client_address[0])
    return "unknown"


def _authorized(headers: Any, api_key: str | None) -> bool:
    if not api_key:
        <REDACTED_SECRET> True
    expected = str(api_key)
    x_key = str(headers.get("X-API-Key") or "")
    auth = headers.get("Authorization", "")
    if hmac.compare_digest(x_key, expected):
        return True
    if isinstance(auth, str) and auth.startswith("Bearer "):
        bearer = auth.removeprefix("Bearer ").strip()
        return hmac.compare_digest(bearer, expected)
    return False


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise AisInboundValidationError(f"invalid timestamp: {value}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BANGKOK_TZ)
    return parsed.astimezone(timezone.utc)


def _timestamp_quality(original: str, parsed_utc: datetime | None) -> dict[str, Any]:
    flags: list[str] = []
    if not _timestamp_has_timezone(original):
        flags.append("timezone_assumed_bangkok")
    if parsed_utc is None:
        flags.append("missing_timestamp")
    else:
        now = datetime.now(timezone.utc)
        delta_minutes = (parsed_utc - now).total_seconds() / 60
        if delta_minutes > TIMESTAMP_FUTURE_REVIEW_MINUTES:
            flags.append("future_timestamp_review")
        if delta_minutes < -(TIMESTAMP_STALE_REVIEW_DAYS * 24 * 60):
            flags.append("stale_timestamp_review")
    status = "OK" if not flags else "REVIEW"
    return {
        "status": status,
        "flags": flags,
        "assumption": "naive_timestamp_treated_as_asia_bangkok" if "timezone_assumed_bangkok" in flags else "",
    }


def _timestamp_has_timezone(value: str | None) -> bool:
    if not value:
        return False
    text = str(value).strip()
    if text.endswith("Z"):
        return True
    return bool(re.search(r"[+-]\d{2}:\d{2}$", text))


def _iso_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _request_path_only(path: str) -> str:
    return urllib.parse.urlsplit(path).path


def _is_inbound_path(path: str, inbound_path: str) -> bool:
    return path.rstrip("/") == inbound_path.rstrip("/")


def _status_request_id_from_path(path: str, inbound_path: str) -> str | None:
    prefix = inbound_path.rstrip("/") + "/"
    if not path.startswith(prefix):
        return None
    request_id = urllib.parse.unquote(path[len(prefix) :].strip("/"))
    if not request_id or "/" in request_id:
        return None
    return request_id
