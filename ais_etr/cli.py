from __future__ import annotations

import argparse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import sqlite3
import time
import urllib.parse
import webbrowser

from .config import Settings
from .confidence_gate import (
    build_forward_capture_template,
    build_shadow_send_eligibility,
    build_two_stage_shadow_challenger,
    import_forward_capture,
)
from .cloud_production import (
    build_green_eligibility_report,
    build_mvp_daily_qa_pack,
    build_production_approval_evidence_pack,
    build_production_gate_packet,
    run_ais_truth_interval_pairing,
    run_cloud_worker_shadow_loop,
)
from .ais_active_state_challenger import build_active_state_remaining_challenger
from .ais_add_field_truth import import_ais_add_field_truth
from .ais_first_error_triage import build_ais_first_error_triage
from .ais_history_challenger import build_ais_history_challenger
from .ais_inbound import (
    DEFAULT_INBOUND_PATH as AIS_INBOUND_PATH,
    DEFAULT_RATE_LIMIT_PER_MINUTE as AIS_INBOUND_DEFAULT_RATE_LIMIT_PER_MINUTE,
    build_ais_inbound_audit_export,
    build_ais_inbound_db_snapshot,
    build_ais_inbound_first_hit_packet,
    build_ais_inbound_model_demo_readiness,
    build_ais_inbound_readiness_gate,
    build_ais_inbound_status_report,
    build_pilot_completion_gate,
    process_ais_inbound_request,
    replay_ais_inbound_callbacks,
    run_ais_inbound_shadow_demo_rehearsal,
    serve_ais_inbound_api,
    write_demo_request as write_ais_inbound_demo_request,
)
from .ais_inbound_contract import (
    build_ais_inbound_doc_qa,
    build_ais_inbound_security_audit,
    write_ais_inbound_contract_pack,
    write_ais_inbound_production_migration_pack,
    write_ais_inbound_test_kit,
)
from .ais_momentary_long_diagnostics import build_ais_momentary_long_diagnostics
from .ais_new_files_profile import build_ais_new_files_profile
from .ais_only_error_segmentation import build_ais_only_error_segmentation
from .ais_only_lifecycle_challenger import build_ais_only_lifecycle_challenger
from .ais_only_remaining_time_challenger import build_ais_only_remaining_time_challenger
from .ais_only_readiness import build_ais_only_readiness
from .ais_remaining_truth import match_ais_remaining_truth_to_shadow
from .ais_site_distance_feature import build_ais_site_distance_features
from .ais_truth import import_ais_truth, match_ais_truth_to_shadow, write_ais_truth_template
from .autonomous_evidence import build_autonomous_evidence_collector
from .data_integrity import build_data_integrity_audit, build_truth_governance_review_status
from .daily_refresh import (
    build_approved_context_candidate_summary,
    build_context_conflict_deep_dive,
    build_daily_intake_workflow,
    build_daily_inbox_status,
    build_daily_shadow_diff,
    build_evidence_review_reports,
    build_executive_status_pack,
    build_operator_shadow_review_checklist,
    run_synthetic_daily_file_smoke_test,
    run_daily_shadow_refresh,
)
from .db import RuntimeDb
from .error_diagnostics import build_shadow_error_diagnostics
from .evaluation import build_shadow_report, evaluate_sample_messages, export_shadow_truth_template
from .incident_clustering import build_shadow_incident_clusters, build_shadow_incident_replay_report
from .line_ingest import (
    DEFAULT_TRAINING_CORPUS_AUDIT,
    DEFAULT_TRAINING_CORPUS_OUTPUT,
    DEFAULT_TRAINING_CORPUS_REPORT,
    DEFAULT_WEBHOOK_SQLITE,
    build_line_training_corpus,
    import_line_history_export,
    serve_line_webhook,
)
from .line_training import (
    DEFAULT_LINE_PARSER_EVAL_OUTPUT,
    DEFAULT_LINE_PARSER_MODEL_OUTPUT,
    DEFAULT_LINE_PARSER_REPORT_OUTPUT,
    DEFAULT_LINE_PARSER_REVIEW_OUTPUT,
    DEFAULT_LINE_PARSER_SPLIT_OUTPUT,
    train_line_parser_shadow_model,
)
from .line_place_topology import (
    DEFAULT_LINE_PLACE_ENRICHED_OUTPUT,
    DEFAULT_LINE_PLACE_MARKDOWN_OUTPUT,
    DEFAULT_LINE_PLACE_OWNER_REVIEW_MARKDOWN_OUTPUT,
    DEFAULT_LINE_PLACE_OWNER_REVIEW_OUTPUT,
    DEFAULT_LINE_PLACE_OUTPUT,
    DEFAULT_LINE_PLACE_REVIEW_SOURCE,
    build_line_place_topology_lookup,
)
from .line_google_geocode import (
    DEFAULT_LINE_GOOGLE_GEOCODE_MARKDOWN_OUTPUT,
    DEFAULT_LINE_GOOGLE_GEOCODE_OUTPUT,
    build_line_google_geocode_missing_places,
)
from .long_outage_challenger import build_long_outage_refresh_challenger
from .long_outage_root_cause import build_long_outage_root_cause_pack
from .mock_webhook import DEFAULT_PATH as MOCK_WEBHOOK_PATH
from .mock_webhook import serve_mock_webhook
from .model_scope import (
    build_model_scope_comparison,
    build_shadow_model_comparison,
    build_station_district_mapping,
    build_station_mapping_review,
    train_scope_challenger_model,
)
from .notification_replay import DEFAULT_REPLAY_STATUSES, replay_failed_shadow_notifications
from .notification_lifecycle_bridge import build_notification_lifecycle_bridge_audit
from .notification_time_readiness import build_notification_time_readiness
from .ops_lifecycle import build_ops_lifecycle_template, validate_ops_lifecycle_file
from .operations import export_no_meter_backlog, setup_env, validate_env
from .pipeline import AisEtrPipeline
from .pre_ais_readiness import (
    build_ais_truth_intake_kit,
    build_pre_ais_evidence_pack,
    run_ais_truth_dry_run,
)
from .readiness import build_shadow_readiness_pack
from .registry_repair import build_no_match_repair_candidates
from .protection_repair import (
    apply_protection_mapping_overrides,
    build_private_protection_mapping_overrides,
)
from .reportpo_etr import (
    DEFAULT_REPORTPO_QUERYDATA_URL,
    build_reportpo_alias_template,
    fetch_reportpo_etr_querydata,
    import_reportpo_etr,
    join_reportpo_features_to_shadow,
    match_reportpo_truth,
)
from .reportpo_event_bridge import build_reportpo_event_bridge_audit
from .reportpo_bridge_request_pack import build_reportpo_bridge_request_pack
from .reportpo_feature_diagnostics import build_reportpo_feature_diagnostics
from .reportpo_feature_gap_audit import build_reportpo_feature_gap_audit
from .reportpo_feature_label_audit import build_reportpo_feature_label_audit
from .production_path import build_production_readiness_gate, export_sanitized_codebase
from .reportpo_lifecycle import (
    fetch_reportpo_lifecycle_querydata,
    import_reportpo_lifecycle,
    join_reportpo_lifecycle_to_shadow,
)
from .reportpo_manual_bridge_candidates import build_reportpo_manual_bridge_candidates
from .reportpo_model_inventory import build_reportpo_model_inventory
from .reportpo_pending import (
    audit_reportpo_pending_overlap,
    fetch_reportpo_pending_querydata,
    import_reportpo_pending,
)
from .reportpo_proxy_challenger import build_reportpo_proxy_challenger
from .reportpo_semantic_inference import build_reportpo_semantic_inference
from .reportpo_shared_key_discovery import build_reportpo_shared_key_discovery
from .source_trace import (
    DEFAULT_GIS_BASE_URL,
    DEFAULT_TRACE_DOWN_URL,
    trace_no_match_candidates_from_source_system,
)
from .source_trace_schematic import build_source_trace_schematic
from .sfsd_evidence import (
    DEFAULT_SFSD_MODELS_URL,
    DEFAULT_SFSD_QUERYDATA_URL,
    build_sfsd_gap_decision_pack,
    build_sfsd_gap_resolution_audit,
    build_sfsd_long_outage_evidence,
    build_sfsd_remaining_gap_review,
    build_sfsd_source_trace_candidates,
    fetch_sfsd_event_detail_querydata,
    fetch_sfsd_models_and_exploration,
    import_sfsd_events,
    refresh_sfsd_long_outage_evidence,
)
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
from .trace_audit import trace_no_match_candidates_against_upstream
from .truth_quality import build_truth_quality_audit
from .truth_inference import infer_webex_truth_mapping
from .webex_audit import build_webex_audit
from .webex_device_state_diagnostics import build_webex_device_state_diagnostic
from .webex_elapsed_challenger import build_webex_elapsed_refresh_challenger
from .webex_export import export_webex_room_history
from .webex import (
    WebexClient,
    WebexOAuthError,
    WebexOAuthTokenManager,
    build_authorization_url,
    generate_pkce_pair,
    validate_oauth_callback,
)


def _settings(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env(args.env)
    if args.db:
        settings = Settings(**{**settings.__dict__, "db_path": Path(args.db)})
    return settings


def cmd_init_db(args: argparse.Namespace) -> None:
    settings = _settings(args)
    pipeline = AisEtrPipeline(settings)
    pipeline.init_db()
    print(json.dumps({"db": str(settings.resolve(settings.db_path)), "status": "initialized"}, ensure_ascii=False))


def cmd_build_registry(args: argparse.Namespace) -> None:
    settings = _settings(args)
    pipeline = AisEtrPipeline(settings)
    summary = pipeline.build_registry(args.registry)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_train(args: argparse.Namespace) -> None:
    settings = _settings(args)
    pipeline = AisEtrPipeline(settings)
    result = pipeline.train_model()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_poll_once(args: argparse.Namespace) -> None:
    settings = _settings(args)
    pipeline = AisEtrPipeline(settings)
    result = pipeline.poll_once(max_messages=args.max_messages)
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_poll_loop(args: argparse.Namespace) -> None:
    settings = _settings(args)
    pipeline = AisEtrPipeline(settings)
    result = pipeline.poll_loop(
        interval_seconds=args.interval_seconds,
        max_messages=args.max_messages,
        iterations=args.iterations,
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, sort_keys=True))


def _oauth_manager(settings: Settings) -> WebexOAuthTokenManager:
    if not settings.webex_client_id or not settings.webex_client_secret:
        raise RuntimeError("WEBEX_CLIENT_ID and WEBEX_CLIENT_SECRET are required")
    return WebexOAuthTokenManager(
        client_id=settings.webex_client_id,
        client_secret=settings.webex_client_secret,
        token_path=settings.resolve(settings.webex_token_path),
        api_base=settings.webex_api_base,
    )


def _safe_token_result(status: str, manager: WebexOAuthTokenManager, token: dict | None = None) -> dict:
    metadata = manager.token_metadata()
    if token:
        metadata.update(
            {
                "expires_at": token.get("expires_at"),
                "refresh_expires_at": token.get("refresh_expires_at"),
                "scope": token.get("scope"),
                "token_type": token.get("token_type"),
            }
        )
    return {"status": status, **metadata}


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = {
            key: values[0]
            for key, values in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()
        }
        if params:
            self.server.callback_path = parsed.path  # type: ignore[attr-defined]
            self.server.callback_params = params  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"""<!doctype html>
<html>
<body>
<h1>Webex authorization received</h1>
<p>You can close this window and return to the terminal.</p>
<script>
if (window.location.hash && !window.location.search) {
  var fragment = window.location.hash.substring(1);
  if (fragment.indexOf('code=') >= 0 || fragment.indexOf('error=') >= 0) {
    window.location.replace(window.location.pathname + '?' + fragment);
  }
}
</script>
</body>
</html>"""
        )

    def log_message(self, format: str, *args) -> None:
        return


def _wait_for_oauth_callback(redirect_uri: str, expected_state: str, timeout_seconds: int) -> str:
    parsed = urllib.parse.urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    expected_path = parsed.path or "/"
    server = HTTPServer((host, port), _OAuthCallbackHandler)
    server.timeout = 1
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    try:
        while time.time() < deadline:
            server.callback_params = None  # type: ignore[attr-defined]
            server.callback_path = None  # type: ignore[attr-defined]
            server.handle_request()
            params = getattr(server, "callback_params", None)
            path = getattr(server, "callback_path", None)
            if params is None:
                continue
            if path != expected_path:
                last_error = RuntimeError(f"Unexpected OAuth callback path: {path}")
                continue
            try:
                return validate_oauth_callback(params, expected_state)
            except WebexOAuthError as exc:
                last_error = exc
                if "state mismatch" not in str(exc).lower():
                    raise
                print("Ignored OAuth callback with mismatched state; waiting for the current authorization URL.")
        if last_error:
            raise TimeoutError(
                f"Timed out waiting for a valid Webex OAuth callback after {timeout_seconds} seconds; "
                f"last callback error: {last_error}"
            )
        raise TimeoutError(f"Timed out waiting for Webex OAuth callback after {timeout_seconds} seconds")
    finally:
        server.server_close()


def cmd_webex_auth(args: argparse.Namespace) -> None:
    settings = _settings(args)
    manager = _oauth_manager(settings)
    state = secrets.token_urlsafe(24)
    code_verifier, code_challenge = generate_pkce_pair()
    auth_url = build_authorization_url(
        client_id=settings.webex_client_id or "",
        redirect_uri=settings.webex_redirect_uri,
        scopes=settings.webex_scopes,
        state=state,
        code_challenge=code_challenge,
        authorization_url=settings.webex_authorization_url,
    )
    print(json.dumps({"authorization_url": auth_url, "status": "waiting_for_browser_callback"}, ensure_ascii=False))
    if not args.no_browser:
        webbrowser.open(auth_url)
    code = _wait_for_oauth_callback(settings.webex_redirect_uri, state, args.timeout_seconds)
    token = manager.exchange_code(code, settings.webex_redirect_uri, code_verifier)
    print(json.dumps(_safe_token_result("authorized", manager, token), ensure_ascii=False, indent=2, sort_keys=True))


def cmd_webex_refresh_token(args: argparse.Namespace) -> None:
    settings = _settings(args)
    manager = _oauth_manager(settings)
    token = manager.refresh_access_token()
    print(json.dumps(_safe_token_result("refreshed", manager, token), ensure_ascii=False, indent=2, sort_keys=True))


def _webex_client(settings: Settings, require_room: bool = False) -> WebexClient:
    room_id = settings.webex_room_id if require_room else None
    if settings.webex_auth_mode == "oauth":
        manager = _oauth_manager(settings)
        return WebexClient(
            room_id=room_id,
            api_base=settings.webex_api_base,
            require_mention=False,
            token_provider=manager.access_token,
        )
    elif settings.webex_bot_token:
        return WebexClient(
            bot_token=settings.webex_bot_token,
            room_id=room_id,
            api_base=settings.webex_api_base,
            require_mention=settings.webex_require_mention,
        )
    raise RuntimeError("Configure WEBEX_AUTH_MODE=oauth with a token, or WEBEX_BOT_TOKEN, before using Webex")


def cmd_webex_rooms(args: argparse.Namespace) -> None:
    settings = _settings(args)
    client = _webex_client(settings, require_room=False)
    rooms = client.list_rooms(max_items=args.max_rooms, query=args.query)
    safe_rooms = [
        {
            "id": room.get("id"),
            "title": room.get("title"),
            "type": room.get("type"),
            "lastActivity": room.get("lastActivity"),
        }
        for room in rooms
    ]
    print(json.dumps({"count": len(safe_rooms), "items": safe_rooms}, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_webex_export_history(args: argparse.Namespace) -> None:
    settings = _settings(args)
    if not settings.webex_room_id:
        raise RuntimeError("WEBEX_ROOM_ID is required before exporting Webex room history")
    client = _webex_client(settings, require_room=True)
    result = export_webex_room_history(
        client,
        settings.resolve(args.output),
        settings.resolve(args.csv_output) if args.csv_output else None,
        settings.resolve(args.sample_output) if args.sample_output else None,
        max_messages=args.max_messages,
        page_size=args.page_size,
        before=args.before,
        after=args.after,
        include_room_id=args.include_room_id,
        include_actor=args.include_actor,
        include_raw=args.include_raw,
        sleep_seconds=args.sleep_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_webex_replay_history(args: argparse.Namespace) -> None:
    settings = _settings(args)
    pipeline = AisEtrPipeline(settings)
    result = pipeline.replay_webex_history(
        source=args.source,
        limit=args.limit,
        audit_output=args.audit_output,
        reprocess_existing=args.reprocess_existing,
        capture_notifications=not args.no_notification_capture,
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_line_import_history(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = import_line_history_export(
        settings.resolve(args.source),
        settings.resolve(args.manifest),
        settings.resolve(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_line_replay_history(args: argparse.Namespace) -> None:
    settings = _settings(args)
    pipeline = AisEtrPipeline(settings)
    result = pipeline.replay_webex_history(
        source=args.source,
        limit=args.limit,
        audit_output=args.audit_output,
        reprocess_existing=args.reprocess_existing,
        capture_notifications=not args.no_notification_capture,
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_line_build_training_corpus(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_line_training_corpus(
        sources=[settings.resolve(source) for source in args.sources],
        output=settings.resolve(args.output),
        audit_output=settings.resolve(args.audit_output) if args.audit_output else None,
        markdown_output=settings.resolve(args.markdown_output) if args.markdown_output else None,
        districts=settings.pilot_districts,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_line_train_parser_model(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = train_line_parser_shadow_model(
        source=settings.resolve(args.source),
        model_output=settings.resolve(args.model_output),
        split_output=settings.resolve(args.split_output),
        eval_output=settings.resolve(args.eval_output),
        markdown_output=settings.resolve(args.markdown_output),
        review_output=settings.resolve(args.review_output),
        max_features=args.max_features,
        threshold=args.threshold,
        seed=args.seed,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_line_place_topology_lookup(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_line_place_topology_lookup(
        review_source=settings.resolve(args.review_source),
        upstream=settings.resolve(args.upstream),
        output=settings.resolve(args.output),
        enriched_output=settings.resolve(args.enriched_output) if args.enriched_output else None,
        markdown_output=settings.resolve(args.markdown_output) if args.markdown_output else None,
        owner_review_output=settings.resolve(args.owner_review_output) if args.owner_review_output else None,
        owner_review_markdown_output=(
            settings.resolve(args.owner_review_markdown_output) if args.owner_review_markdown_output else None
        ),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_line_google_geocode_missing_places(args: argparse.Namespace) -> None:
    settings = _settings(args)
    statuses = tuple(part.strip() for part in args.statuses.split(",") if part.strip())
    result = build_line_google_geocode_missing_places(
        source=settings.resolve(args.source),
        output=settings.resolve(args.output),
        markdown_output=settings.resolve(args.markdown_output) if args.markdown_output else None,
        statuses=statuses,
        query_suffix=args.query_suffix,
        api_key_env=args.api_key_env,
        env_path=args.env,
        limit=args.limit,
        max_candidates_per_row=args.max_candidates_per_row,
        timeout_seconds=args.timeout_seconds,
        sleep_seconds=args.sleep_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_line_webhook_server(args: argparse.Namespace) -> None:
    settings = _settings(args)
    if settings.line_capture_mode != "shadow":
        raise RuntimeError("LINE_CAPTURE_MODE must remain 'shadow'")
    if not settings.line_channel_secret:
        raise RuntimeError("LINE_CHANNEL_SECRET is required for LINE webhook signature verification")
    if not settings.line_allowed_group_ids and not settings.line_allowed_chat_hashes:
        raise RuntimeError("LINE_ALLOWED_GROUP_IDS or LINE_ALLOWED_CHAT_HASHES must contain at least one approved chat")
    print(
        json.dumps(
            {
                "status": "listening",
                "mode": settings.line_capture_mode,
                "host": args.host,
                "port": args.port,
                "path": args.path,
                "output": str(settings.resolve(args.output)),
                "sqlite": str(settings.resolve(args.sqlite_output)) if args.sqlite_output else None,
                "allowed_group_count": len(settings.line_allowed_group_ids),
                "allowed_chat_hash_count": len(settings.line_allowed_chat_hashes),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    serve_line_webhook(
        host=args.host,
        port=args.port,
        channel_secret=settings.line_channel_secret,
        allowed_group_ids=settings.line_allowed_group_ids,
        output_jsonl=settings.resolve(args.output),
        output_sqlite=settings.resolve(args.sqlite_output) if args.sqlite_output else None,
        allowed_chat_hashes=settings.line_allowed_chat_hashes,
        path=args.path,
    )


def cmd_mock_webhook(args: argparse.Namespace) -> None:
    settings = _settings(args)
    output_path = settings.resolve(args.output)
    print(
        json.dumps(
            {
                "status": "listening",
                "url": f"http://{args.host}:{args.port}{args.path}",
                "output": str(output_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    serve_mock_webhook(
        host=args.host,
        port=args.port,
        output_path=output_path,
        notification_path=args.path,
    )


def cmd_ais_inbound_api(args: argparse.Namespace) -> None:
    settings = _settings(args)
    requests_output = settings.resolve(args.requests_output)
    callbacks_output = settings.resolve(args.callbacks_output)
    callback_url = args.callback_url or settings.ais_callback_url
    api_key = args.api_key or settings.ais_inbound_api_key
    print(
        json.dumps(
            {
                "status": "listening",
                "mode": "shadow",
                "url": f"http://{args.host}:{args.port}{args.path}",
                "callback_url_configured": bool(callback_url),
                "requests_output": str(requests_output),
                "callbacks_output": str(callbacks_output),
                "production_send": "blocked",
                "rate_limit_per_minute": args.rate_limit_per_minute,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    serve_ais_inbound_api(
        db_path=settings.resolve(settings.db_path),
        host=args.host,
        port=args.port,
        path=args.path,
        api_key=api_key,
        callback_url=callback_url,
        requests_output=requests_output,
        callbacks_output=callbacks_output,
        match_window_minutes=args.match_window_minutes,
        post_callback=not args.no_callback_post,
        rate_limit_per_minute=args.rate_limit_per_minute,
    )


def cmd_ais_inbound_verify_file(args: argparse.Namespace) -> None:
    settings = _settings(args)
    payload = json.loads(settings.resolve(args.source).read_text(encoding="utf-8-sig"))
    result = process_ais_inbound_request(
        db_path=settings.resolve(settings.db_path),
        payload=payload,
        callback_url=args.callback_url or settings.ais_callback_url,
        requests_output=settings.resolve(args.requests_output) if args.requests_output else None,
        callbacks_output=settings.resolve(args.callbacks_output) if args.callbacks_output else None,
        match_window_minutes=args.match_window_minutes,
        post_callback=not args.no_callback_post,
    )
    print(json.dumps(result.asdict(), ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_inbound_demo_request(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = write_ais_inbound_demo_request(settings.resolve(args.output), peano=args.peano)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_inbound_contract_pack(args: argparse.Namespace) -> None:
    settings = _settings(args)
    public_base = args.public_base
    if not public_base:
        status_path = settings.resolve(args.status_file)
        if status_path.exists():
            try:
                status = json.loads(status_path.read_text(encoding="utf-8-sig"))
                public_url = status.get("primary_public_url") or status.get("public_url")
                if public_url:
                    parsed = urllib.parse.urlsplit(str(public_url))
                    public_base = f"{parsed.scheme}://{parsed.netloc}"
            except Exception:
                public_base = None
    if not public_base:
        public_base = "https://ais-etr-pea-pilot.loca.lt"
    result = write_ais_inbound_contract_pack(settings.resolve(args.output_dir), public_base=public_base)
    print(json.dumps({"public_base": public_base, **result}, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_inbound_test_kit(args: argparse.Namespace) -> None:
    settings = _settings(args)
    public_base = args.public_base
    if not public_base:
        status_path = settings.resolve(args.status_file)
        if status_path.exists():
            try:
                status = json.loads(status_path.read_text(encoding="utf-8-sig"))
                public_url = status.get("primary_public_url") or status.get("public_url")
                if public_url:
                    parsed = urllib.parse.urlsplit(str(public_url))
                    public_base = f"{parsed.scheme}://{parsed.netloc}"
            except Exception:
                public_base = None
    if not public_base:
        public_base = "https://ais-etr-pea-pilot.loca.lt"
    result = write_ais_inbound_test_kit(
        settings.resolve(args.output_dir),
        public_base=public_base,
        source_dir=settings.resolve(args.source_dir),
        zip_output=settings.resolve(args.zip_output) if args.zip_output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_inbound_production_pack(args: argparse.Namespace) -> None:
    settings = _settings(args)
    public_base = args.public_base
    if not public_base:
        status_path = settings.resolve(args.status_file)
        if status_path.exists():
            try:
                status = json.loads(status_path.read_text(encoding="utf-8-sig"))
                public_url = status.get("primary_public_url") or status.get("public_url")
                if public_url:
                    parsed = urllib.parse.urlsplit(str(public_url))
                    public_base = f"{parsed.scheme}://{parsed.netloc}"
            except Exception:
                public_base = None
    if not public_base:
        public_base = "https://ais-etr-pea-pilot.loca.lt"
    result = write_ais_inbound_production_migration_pack(
        settings.resolve(args.output_dir),
        public_base=public_base,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_inbound_doc_qa(args: argparse.Namespace) -> None:
    settings = _settings(args)
    public_base = args.public_base
    if not public_base:
        status_path = settings.resolve(args.status_file)
        if status_path.exists():
            try:
                status = json.loads(status_path.read_text(encoding="utf-8-sig"))
                public_url = status.get("primary_public_url") or status.get("public_url")
                if public_url:
                    parsed = urllib.parse.urlsplit(str(public_url))
                    public_base = f"{parsed.scheme}://{parsed.netloc}"
            except Exception:
                public_base = None
    if not public_base:
        public_base = "https://ais-etr-pea-pilot.loca.lt"
    result = build_ais_inbound_doc_qa(
        settings.resolve(args.docs_dir),
        public_base=public_base,
        output=settings.resolve(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_inbound_security_audit(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_inbound_security_audit(
        settings.resolve(args.runtime_dir),
        private_key_file=settings.resolve(args.private_key_file),
        output_markdown=settings.resolve(args.output),
        output_json=settings.resolve(args.json_output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_inbound_status(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_inbound_status_report(
        settings.resolve(settings.db_path),
        output=settings.resolve(args.output) if args.output else None,
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_inbound_model_demo_readiness(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_inbound_model_demo_readiness(
        settings.resolve(settings.db_path),
        output=settings.resolve(args.output) if args.output else None,
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_inbound_shadow_demo_rehearsal(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = run_ais_inbound_shadow_demo_rehearsal(
        settings.resolve(settings.db_path),
        output=settings.resolve(args.output) if args.output else None,
        request_id=args.request_id,
        requests_output=settings.resolve(args.requests_output) if args.requests_output else None,
        callbacks_output=settings.resolve(args.callbacks_output) if args.callbacks_output else None,
        match_window_minutes=args.match_window_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_inbound_audit_export(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_inbound_audit_export(
        settings.resolve(settings.db_path),
        output_csv=settings.resolve(args.output),
        output_markdown=settings.resolve(args.markdown_output),
        include_smoke=args.include_smoke,
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_inbound_db_snapshot(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_inbound_db_snapshot(
        settings.resolve(settings.db_path),
        output_dir=settings.resolve(args.output_dir),
        label=args.label,
        output_markdown=settings.resolve(args.output) if args.output else None,
        output_json=settings.resolve(args.json_output) if args.json_output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_inbound_first_hit_packet(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_inbound_first_hit_packet(
        settings.resolve(settings.db_path),
        output_markdown=settings.resolve(args.output),
        output_json=settings.resolve(args.json_output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_inbound_readiness_gate(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_inbound_readiness_gate(
        settings.resolve(settings.db_path),
        status_file=settings.resolve(args.status_file),
        verification_file=settings.resolve(args.verification_file),
        doc_qa_file=settings.resolve(args.doc_qa_file),
        first_hit_file=settings.resolve(args.first_hit_file),
        output_markdown=settings.resolve(args.output),
        output_json=settings.resolve(args.json_output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_pilot_completion_gate(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_pilot_completion_gate(
        settings.resolve(settings.db_path),
        status_file=settings.resolve(args.status_file),
        verification_file=settings.resolve(args.verification_file),
        security_audit_file=settings.resolve(args.security_audit_file),
        db_snapshot_file=settings.resolve(args.db_snapshot_file),
        readiness_gate_file=settings.resolve(args.readiness_gate_file),
        green_gate_file=settings.resolve(args.green_gate_file),
        production_gate_file=settings.resolve(args.production_gate_file),
        share_pack_zip=settings.resolve(args.share_pack_zip),
        share_pack_dir=settings.resolve(args.share_pack_dir),
        chatgpt_round2_file=settings.resolve(args.chatgpt_round2_file),
        chatgpt_round3_file=settings.resolve(args.chatgpt_round3_file),
        output_markdown=settings.resolve(args.output),
        output_json=settings.resolve(args.json_output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_export_sanitized_codebase(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = export_sanitized_codebase(
        settings.workspace,
        output_dir=settings.resolve(args.output_dir),
        zip_output=settings.resolve(args.zip_output),
        manifest_output=settings.resolve(args.manifest_output),
        prompt_output=settings.resolve(args.prompt_output),
        audit_output=settings.resolve(args.audit_output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_production_readiness_gate(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_production_readiness_gate(
        settings.workspace,
        cloud_dir=settings.resolve(args.cloud_dir),
        sanitized_manifest=settings.resolve(args.sanitized_manifest),
        pilot_gate_file=settings.resolve(args.pilot_gate_file),
        green_gate_file=settings.resolve(args.green_gate_file),
        production_gate_file=settings.resolve(args.production_gate_file),
        owner_approval_file=settings.resolve(args.owner_approval_file),
        output_markdown=settings.resolve(args.output),
        output_json=settings.resolve(args.json_output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_inbound_replay_callbacks(args: argparse.Namespace) -> None:
    settings = _settings(args)
    callback_url = args.callback_url or settings.ais_callback_url
    statuses = tuple(status.strip() for status in args.statuses.split(",") if status.strip())
    result = replay_ais_inbound_callbacks(
        settings.resolve(settings.db_path),
        callback_url=callback_url,
        request_id=args.request_id,
        statuses=statuses,
        limit=args.limit,
        callbacks_output=settings.resolve(args.callbacks_output) if args.callbacks_output else None,
        dry_run=not args.send,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_webex_audit(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_webex_audit(
        settings.resolve(settings.db_path),
        settings.pilot_districts,
        room_district=settings.webex_room_district,
        output_csv=settings.resolve(args.output) if args.output else None,
        samples_output=settings.resolve(args.samples_output) if args.samples_output else None,
        max_text_chars=args.max_text_chars,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_planned_notify(args: argparse.Namespace) -> None:
    settings = _settings(args)
    pipeline = AisEtrPipeline(settings)
    reference_time = datetime.fromisoformat(args.now) if args.now else None
    result = pipeline.notify_planned_outages(
        path=args.source,
        reference_time=reference_time,
        min_lead_days=args.min_lead_days,
        limit=args.limit,
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_setup_env(args: argparse.Namespace) -> None:
    result = setup_env(args.example, args.output, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_validate_env(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = validate_env(settings, args.env)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_sample_eval(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = evaluate_sample_messages(args.samples, settings.pilot_districts)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_shadow_report(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_shadow_report(
        settings.resolve(settings.db_path),
        settings.resolve(settings.event_file),
        [settings.resolve(path) for path in settings.etr_files],
        settings.resolve(settings.distance_file),
        settings.resolve(args.output) if args.output else None,
        settings.resolve(args.truth_mapping) if args.truth_mapping else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_shadow_truth_template(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = export_shadow_truth_template(
        settings.resolve(settings.db_path),
        settings.resolve(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_shadow_replay_notifications(args: argparse.Namespace) -> None:
    settings = _settings(args)
    db = RuntimeDb(settings.resolve(settings.db_path))
    db.init()
    statuses = tuple(
        status.strip()
        for status in args.statuses.split(",")
        if status.strip()
    )
    result = replay_failed_shadow_notifications(
        db,
        args.endpoint_url or settings.mock_webhook_url,
        statuses=statuses or DEFAULT_REPLAY_STATUSES,
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_shadow_truth_infer_webex(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = infer_webex_truth_mapping(
        settings.resolve(settings.db_path),
        settings.resolve(args.output),
        settings.resolve(args.candidates_output) if args.candidates_output else None,
        fill_empty_only=not args.overwrite,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_truth_template(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = write_ais_truth_template(
        settings.resolve(args.output),
        include_example=args.example,
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_truth_import(args: argparse.Namespace) -> None:
    settings = _settings(args)
    sheet: str | int | None = args.sheet
    if isinstance(sheet, str) and sheet.isdigit():
        sheet = int(sheet)
    result = import_ais_truth(
        settings.resolve(args.source),
        settings.resolve(args.output),
        settings.resolve(args.rejects_output) if args.rejects_output else None,
        sheet=sheet,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_add_field_truth_import(args: argparse.Namespace) -> None:
    settings = _settings(args)
    sheet: str | int | None = args.sheet
    if isinstance(sheet, str) and sheet.isdigit():
        sheet = int(sheet)
    result = import_ais_add_field_truth(
        settings.resolve(args.source),
        settings.resolve(args.meter_mapping) if args.meter_mapping else None,
        settings.resolve(args.output),
        settings.resolve(args.review_output),
        settings.resolve(args.rejects_output),
        settings.resolve(args.audit_output),
        settings.resolve(args.report_output) if args.report_output else None,
        sheet=sheet,
        date_order=args.date_order,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_truth_match_shadow(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = match_ais_truth_to_shadow(
        settings.resolve(settings.db_path),
        settings.resolve(args.ais_truth),
        settings.resolve(args.output),
        settings.resolve(args.audit) if args.audit else None,
        max_window_minutes=args.max_window_minutes,
        ambiguity_delta_minutes=args.ambiguity_delta_minutes,
        aggregation=args.aggregation,
        include_review=args.include_review,
        allow_feeder=args.allow_feeder,
        overwrite=args.overwrite,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_remaining_truth_match_shadow(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = match_ais_remaining_truth_to_shadow(
        settings.resolve(settings.db_path),
        settings.resolve(args.ais_truth),
        settings.resolve(args.output),
        settings.resolve(args.audit) if args.audit else None,
        start_tolerance_minutes=args.start_tolerance_minutes,
        aggregation=args.aggregation,
        overwrite=args.overwrite,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_site_distance_feature(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_site_distance_features(
        settings.resolve(args.source),
        settings.resolve(args.distance),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        site_id_column=args.site_id_column,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_notification_time_readiness(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_notification_time_readiness(
        settings.resolve(settings.db_path),
        settings.resolve(args.comparison),
        settings.resolve(args.remaining_audit),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        device_state_csv=settings.resolve(args.device_state) if args.device_state else None,
        lifecycle_audit_csv=settings.resolve(args.lifecycle_audit) if args.lifecycle_audit else None,
        segments_output=settings.resolve(args.segments_output) if args.segments_output else None,
        short_threshold_minutes=args.short_threshold_minutes,
        high_error_threshold_minutes=args.high_error_threshold_minutes,
        min_segment_events=args.min_segment_events,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_first_error_triage(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_first_error_triage(
        settings.resolve(settings.db_path),
        settings.resolve(args.readiness),
        settings.resolve(args.remaining_audit),
        settings.resolve(args.ais_truth_audit),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        settings.resolve(args.segments_output) if args.segments_output else None,
        high_error_minutes=args.high_error_minutes,
        late_webex_minutes=args.late_webex_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_momentary_long_diagnostics(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_momentary_long_diagnostics(
        settings.resolve(args.triage),
        settings.resolve(args.readiness),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        settings.resolve(args.segments_output) if args.segments_output else None,
        cluster_gap_minutes=args.cluster_gap_minutes,
        late_webex_minutes=args.late_webex_minutes,
        high_error_minutes=args.high_error_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_data_integrity_audit(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_data_integrity_audit(
        settings.resolve(args.output),
        settings.resolve(args.policy_output),
        settings.resolve(args.governance_output),
        settings.resolve(args.approval_template),
        settings.resolve(args.request_pack),
        ais_truth_csv=settings.resolve(args.ais_truth),
        shadow_comparison_csv=settings.resolve(args.shadow_comparison),
        sfsd_evidence_csv=settings.resolve(args.sfsd_evidence),
        sfsd_decision_csv=settings.resolve(args.sfsd_decision),
        reportpo_etr_csv=settings.resolve(args.reportpo_etr),
        reportpo_feature_audit_csv=settings.resolve(args.reportpo_feature_audit),
        reportpo_lifecycle_audit_csv=settings.resolve(args.reportpo_lifecycle_audit),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_truth_governance_review_status(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_truth_governance_review_status(
        settings.resolve(args.approval_template),
        settings.resolve(args.request_pack),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_only_readiness(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_only_readiness(
        settings.resolve(args.shadow_comparison),
        settings.resolve(args.governance_status),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output),
        settings.resolve(args.quarantine_output),
        reportpo_feature_audit_csv=settings.resolve(args.reportpo_feature_audit),
        reportpo_lifecycle_audit_csv=settings.resolve(args.reportpo_lifecycle_audit),
        sfsd_evidence_csv=settings.resolve(args.sfsd_evidence),
        sfsd_decision_csv=settings.resolve(args.sfsd_decision),
        min_duration_minutes=args.min_duration_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_only_error_segmentation(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_only_error_segmentation(
        settings.resolve(args.ais_only_readiness),
        settings.resolve(args.segments_output),
        settings.resolve(args.queue_output),
        settings.resolve(args.markdown_output),
        notification_time_csv=settings.resolve(args.notification_time) if args.notification_time else None,
        high_error_minutes=args.high_error_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_only_remaining_time_challenger(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_only_remaining_time_challenger(
        settings.resolve(settings.db_path),
        settings.resolve(args.ais_only_readiness),
        settings.resolve(args.notification_time),
        settings.resolve(args.ais_truth),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        settings.resolve(args.segments_output) if args.segments_output else None,
        active_state_csv=settings.resolve(args.active_state) if args.active_state else None,
        min_affected_history_rows=args.min_affected_history_rows,
        min_segment_rows=args.min_segment_rows,
        tail_uplift_threshold_minutes=args.tail_uplift_threshold_minutes,
        high_error_minutes=args.high_error_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_only_lifecycle_challenger(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_only_lifecycle_challenger(
        settings.resolve(args.ais_only_readiness),
        settings.resolve(args.remaining_time),
        settings.resolve(args.lifecycle_review),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        settings.resolve(args.feature_audit_output) if args.feature_audit_output else None,
        settings.resolve(args.valid_output) if args.valid_output else None,
        settings.resolve(args.rejects_output) if args.rejects_output else None,
        settings.resolve(args.segments_output) if args.segments_output else None,
        min_lifecycle_prior_rows=args.min_lifecycle_prior_rows,
        high_error_minutes=args.high_error_minutes,
        first_restore_tolerance_minutes=args.first_restore_tolerance_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_shadow_send_eligibility(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_shadow_send_eligibility(
        settings.resolve(args.ais_only_readiness),
        settings.resolve(args.notification_time),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        settings.resolve(args.production_gate_output) if args.production_gate_output else None,
        lifecycle_challenger_csv=settings.resolve(args.lifecycle_challenger) if args.lifecycle_challenger else None,
        remaining_time_csv=settings.resolve(args.remaining_time) if args.remaining_time else None,
        segments_output=settings.resolve(args.segments_output) if args.segments_output else None,
        min_match_confidence=args.min_match_confidence,
        max_auto_interval_width_minutes=args.max_auto_interval_width_minutes,
        max_auto_q90_minutes=args.max_auto_q90_minutes,
        high_error_minutes=args.high_error_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_green_eligibility_report(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_green_eligibility_report(
        ais_only_readiness=settings.resolve(args.ais_only_readiness),
        notification_time=settings.resolve(args.notification_time),
        lifecycle_challenger=settings.resolve(args.lifecycle_challenger),
        remaining_time=settings.resolve(args.remaining_time),
        threshold_calibration=settings.resolve(args.threshold_calibration),
        output=settings.resolve(args.output),
        markdown_output=settings.resolve(args.markdown_output),
        segments_output=settings.resolve(args.segments_output),
        gate_output=settings.resolve(args.gate_output),
        gate_csv_output=settings.resolve(args.gate_csv_output),
        json_output=settings.resolve(args.json_output),
        min_green_rows=args.min_green_rows,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_production_gate_packet(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_production_gate_packet(
        eligibility_csv=settings.resolve(args.eligibility_csv),
        green_gate_json=settings.resolve(args.green_gate_json),
        real_hit_status_json=settings.resolve(args.real_hit_status_json),
        readiness_gate_json=settings.resolve(args.readiness_gate_json),
        owner_approval_template=settings.resolve(args.owner_approval_template),
        output_csv=settings.resolve(args.output_csv),
        markdown_output=settings.resolve(args.markdown_output),
        json_output=settings.resolve(args.json_output),
        min_green_rows=args.min_green_rows,
        top_blockers=args.top_blockers,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_production_approval_evidence_pack(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_production_approval_evidence_pack(
        gap_actions_csv=settings.resolve(args.gap_actions_csv),
        owner_packet_json=settings.resolve(args.owner_packet_json),
        real_hit_status_json=settings.resolve(args.real_hit_status_json),
        readiness_gate_json=settings.resolve(args.readiness_gate_json),
        ais_truth_queue_output=settings.resolve(args.ais_truth_queue_output),
        topology_queue_output=settings.resolve(args.topology_queue_output),
        ops_report_output=settings.resolve(args.ops_report_output),
        ais_test_window_output=settings.resolve(args.ais_test_window_output),
        markdown_output=settings.resolve(args.markdown_output),
        json_output=settings.resolve(args.json_output),
        top_n=args.top_n,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_mvp_daily_qa(args: argparse.Namespace) -> None:
    settings = _settings(args)
    build_production_approval_evidence_pack(
        gap_actions_csv=settings.resolve(args.gap_actions_csv),
        owner_packet_json=settings.resolve(args.owner_packet_json),
        real_hit_status_json=settings.resolve(args.real_hit_status_json),
        readiness_gate_json=settings.resolve(args.readiness_gate_json),
        ais_truth_queue_output=settings.resolve(args.ais_truth_queue_output),
        topology_queue_output=settings.resolve(args.topology_queue_output),
        ops_report_output=settings.resolve(args.ops_report_output),
        ais_test_window_output=settings.resolve(args.ais_test_window_output),
        markdown_output=settings.resolve(args.approval_markdown_output),
        json_output=settings.resolve(args.approval_json_output),
        top_n=args.top_n,
    )
    result = build_mvp_daily_qa_pack(
        approval_pack_json=settings.resolve(args.approval_json_output),
        owner_packet_json=settings.resolve(args.owner_packet_json),
        real_hit_status_json=settings.resolve(args.real_hit_status_json),
        privacy_scan_json=settings.resolve(args.privacy_scan_json),
        output_json=settings.resolve(args.json_output),
        markdown_output=settings.resolve(args.markdown_output),
        recording_pack_output=settings.resolve(args.recording_pack_output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_cloud_worker_shadow_loop(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = run_cloud_worker_shadow_loop(
        database_url=args.database_url,
        input_json=settings.resolve(args.input_json) if args.input_json else None,
        output_json=settings.resolve(args.output_json),
        markdown_output=settings.resolve(args.markdown_output),
        limit=args.limit,
        dry_run=not args.apply,
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_truth_interval_pairing(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = run_ais_truth_interval_pairing(
        database_url=args.database_url,
        input_json=settings.resolve(args.input_json) if args.input_json else None,
        output_json=settings.resolve(args.output_json),
        markdown_output=settings.resolve(args.markdown_output),
        limit=args.limit,
        dry_run=not args.apply,
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_forward_capture_template(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_forward_capture_template(
        settings.resolve(args.eligibility),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        top_n=args.top_n,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_forward_capture_import(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = import_forward_capture(
        settings.resolve(args.input),
        settings.resolve(args.output_valid),
        settings.resolve(args.rejects),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        ais_only_readiness_csv=settings.resolve(args.ais_only_readiness) if args.ais_only_readiness else None,
        first_restore_tolerance_minutes=args.first_restore_tolerance_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_two_stage_shadow_challenger(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_two_stage_shadow_challenger(
        settings.resolve(args.eligibility),
        settings.resolve(args.lifecycle_challenger),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        settings.resolve(args.segments_output) if args.segments_output else None,
        forward_capture_validated_csv=settings.resolve(args.forward_capture_validated) if args.forward_capture_validated else None,
        high_error_minutes=args.high_error_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_autonomous_evidence_collector(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_autonomous_evidence_collector(
        settings.resolve(args.eligibility),
        settings.resolve(args.reportpo_feature_audit),
        settings.resolve(args.reportpo_lifecycle_audit),
        settings.resolve(args.sfsd_evidence),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        settings.resolve(args.autofill_output) if args.autofill_output else None,
        approved_score_threshold=args.approved_score_threshold,
        partial_score_threshold=args.partial_score_threshold,
        long_conflict_minutes=args.long_conflict_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_daily_intake_workflow(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_daily_intake_workflow(
        settings.resolve(args.intake_dir),
        settings.resolve(args.readme_output) if args.readme_output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_daily_inbox_status(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_daily_inbox_status(
        settings.resolve(args.intake_dir),
        settings.resolve(args.output) if args.output else None,
        settings.resolve(args.manifest) if args.manifest else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_evidence_review_pack(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_evidence_review_reports(
        settings.resolve(args.evidence),
        settings.resolve(args.approved_output),
        settings.resolve(args.conflicts_output),
        settings.resolve(args.approved_markdown) if args.approved_markdown else None,
        settings.resolve(args.conflicts_markdown) if args.conflicts_markdown else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_executive_status_pack(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_executive_status_pack(
        settings.resolve(args.eligibility),
        settings.resolve(args.evidence),
        settings.resolve(args.two_stage),
        settings.resolve(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_context_conflict_deep_dive(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_context_conflict_deep_dive(
        settings.resolve(args.evidence),
        settings.resolve(args.markdown_output),
        settings.resolve(args.output) if args.output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_approved_context_summary(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_approved_context_candidate_summary(
        settings.resolve(args.evidence),
        settings.resolve(args.markdown_output),
        settings.resolve(args.output) if args.output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_daily_shadow_diff(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_daily_shadow_diff(
        settings.resolve(args.eligibility),
        settings.resolve(args.evidence),
        settings.resolve(args.inbox_status),
        settings.resolve(args.history),
        settings.resolve(args.output),
        append_history=not args.no_append,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_daily_synthetic_smoke_test(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = run_synthetic_daily_file_smoke_test(
        settings.resolve(args.output_dir),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_operator_checklist(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_operator_shadow_review_checklist(settings.resolve(args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_green_candidate_error_review(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_green_candidate_error_review(
        settings.resolve(args.eligibility),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_eligibility_threshold_calibration(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_eligibility_threshold_calibration(
        settings.resolve(args.eligibility),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        min_rows_for_decision=args.min_rows,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_context_review_priority(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_context_review_priority_pack(
        settings.resolve(args.evidence),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        top_n=args.top_n,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_webex_only_monitoring(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_webex_only_monitoring_report(
        settings.resolve(args.eligibility),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        top_n=args.top_n,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_operator_console_mock(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_operator_console_mock(
        settings.resolve(args.eligibility),
        settings.resolve(args.evidence),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        max_rows=args.max_rows,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_green_gate_tracker(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_green_gate_tracker(
        settings.resolve(args.eligibility),
        settings.resolve(args.threshold_calibration),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        min_green_rows=args.min_green_rows,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_daily_file_qa(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_daily_file_qa(
        settings.resolve(args.candidates),
        settings.resolve(args.review),
        settings.resolve(args.rejects),
        settings.resolve(args.join_audit),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_mapping_repair_queue(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_mapping_repair_queue(
        settings.resolve(args.join_audit),
        settings.resolve(args.candidates),
        settings.resolve(args.rejects),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        private_output_csv=settings.resolve(args.private_output) if args.private_output else None,
        top_n=args.top_n,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_duplicate_flapping_audit(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_duplicate_flapping_audit(
        settings.resolve(args.candidates),
        settings.resolve(args.review),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        flap_window_minutes=args.flap_window_minutes,
        top_n=args.top_n,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_green_candidate_growth_plan(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_green_candidate_growth_plan(
        settings.resolve(args.eligibility),
        settings.resolve(args.green_gate_tracker),
        settings.resolve(args.webex_monitoring),
        settings.resolve(args.mapping_repair_queue),
        settings.resolve(args.context_priority),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        min_green_rows=args.min_green_rows,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_status_only_payload_templates(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_status_only_payload_templates(
        settings.resolve(args.eligibility),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        max_rows=args.max_rows,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_shadow_status_payload_contract(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_shadow_status_payload_contract(
        settings.resolve(args.payloads),
        settings.resolve(args.eligibility),
        settings.resolve(args.output),
        sample_count=args.sample_count,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_executive_one_pager(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_executive_one_pager(
        settings.resolve(args.eligibility),
        settings.resolve(args.green_gate_tracker),
        settings.resolve(args.ais_daily_qa),
        settings.resolve(args.growth_plan),
        settings.resolve(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_mapping_repair_request_pack(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_mapping_repair_request_pack(
        settings.resolve(args.public_queue),
        settings.resolve(args.private_queue),
        settings.resolve(args.output),
        settings.resolve(args.private_output),
        settings.resolve(args.markdown_output),
        top_n=args.top_n,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_webex_truth_request_pack(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_webex_truth_request_pack(
        settings.resolve(args.webex_monitoring),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output),
        top_n=args.top_n,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_flapping_policy_draft(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_flapping_policy_draft(
        settings.resolve(args.duplicate_flapping),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output),
        phase2_windows=args.phase2_windows,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_owner_handoff_pack(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_owner_handoff_pack(
        settings.resolve(args.executive_one_pager),
        settings.resolve(args.growth_plan),
        settings.resolve(args.mapping_request),
        settings.resolve(args.webex_truth_request),
        settings.resolve(args.flapping_policy),
        settings.resolve(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_owner_message_drafts(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_owner_message_drafts(
        settings.resolve(args.owner_handoff),
        settings.resolve(args.mapping_request),
        settings.resolve(args.webex_truth_request),
        settings.resolve(args.flapping_policy),
        settings.resolve(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_owner_followup_tracker(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_owner_followup_tracker(
        settings.resolve(args.mapping_request),
        settings.resolve(args.webex_truth_request),
        settings.resolve(args.flapping_policy),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_owner_response_templates(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_owner_response_templates(
        settings.resolve(args.mapping_request),
        settings.resolve(args.webex_truth_request),
        settings.resolve(args.mapping_template),
        settings.resolve(args.webex_template),
        settings.resolve(args.markdown_output),
        mapping_top_n=args.mapping_top_n,
        webex_top_n=args.webex_top_n,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_owner_response_validate(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = validate_owner_response_files(
        settings.resolve(args.mapping_response),
        settings.resolve(args.webex_response),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_owner_response_intake(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_owner_response_intake(
        settings.resolve(args.validation),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_owner_response_dry_run_impact(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_owner_response_dry_run_impact(
        settings.resolve(args.eligibility),
        settings.resolve(args.green_gate_tracker),
        settings.resolve(args.owner_response_intake),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output),
        min_green_rows=args.min_green_rows,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_owner_response_examples(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_owner_response_examples(
        settings.resolve(args.output_dir),
        settings.resolve(args.markdown_output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_daily_executive_delta(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_daily_executive_delta(
        settings.resolve(args.diff_history),
        settings.resolve(args.green_gate_tracker),
        settings.resolve(args.owner_followup_tracker),
        settings.resolve(args.owner_response_validation),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_executive_pitch_pack(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_executive_pitch_pack(
        settings.resolve(args.executive_one_pager),
        settings.resolve(args.daily_delta),
        settings.resolve(args.owner_handoff),
        settings.resolve(args.owner_followup_tracker),
        settings.resolve(args.owner_response_validation),
        settings.resolve(args.dry_run_impact),
        settings.resolve(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_current_capability_development_plan(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_current_capability_development_plan(
        settings.resolve(args.green_gate_tracker),
        settings.resolve(args.daily_steps),
        settings.resolve(args.owner_followup_tracker),
        settings.resolve(args.owner_response_intake),
        settings.resolve(args.owner_response_dry_run),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output),
        settings.resolve(args.ais_updated_summary) if args.ais_updated_summary else None,
        settings.resolve(args.ais_updated_mapping_request) if args.ais_updated_mapping_request else None,
        settings.resolve(args.ais_updated_mapping_response_template) if args.ais_updated_mapping_response_template else None,
        settings.resolve(args.ais_updated_mapping_private_lookup) if args.ais_updated_mapping_private_lookup else None,
        settings.resolve(args.ais_updated_mapping_owner_message) if args.ais_updated_mapping_owner_message else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_flapping_sensitivity_plan(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_flapping_sensitivity_plan(
        settings.resolve(args.duplicate_flapping),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output),
        windows=args.windows,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_pitching_narrative_script(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_pitching_narrative_script(
        settings.resolve(args.executive_one_pager),
        settings.resolve(args.owner_handoff),
        settings.resolve(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_operator_console_qa(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_operator_console_qa(
        settings.resolve(args.html),
        settings.resolve(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_daily_shadow_refresh(args: argparse.Namespace) -> None:
    settings = _settings(args)
    poll_result = None
    if args.poll_webex:
        pipeline = AisEtrPipeline(settings)
        poll_result = pipeline.poll_once(max_messages=args.max_messages)
    result = run_daily_shadow_refresh(
        settings.resolve(settings.db_path),
        intake_dir=settings.resolve(args.intake_dir),
        ais_source=settings.resolve(args.ais_source) if args.ais_source else None,
        ais_source_format=args.ais_source_format,
        ais_sheet=int(args.sheet) if isinstance(args.sheet, str) and args.sheet.isdigit() else args.sheet,
        meter_mapping=settings.resolve(args.meter_mapping) if args.meter_mapping else None,
        auto_discover_ais_source=not args.no_auto_discover,
        continue_on_error=not args.stop_on_error,
    )
    if poll_result is not None:
        result = {"webex_poll": poll_result.__dict__, **result}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_notification_lifecycle_bridge_audit(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_notification_lifecycle_bridge_audit(
        settings.resolve(settings.db_path),
        settings.resolve(args.readiness),
        settings.resolve(args.output),
        settings.resolve(args.summary_output) if args.summary_output else None,
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        feature_audit_csv=settings.resolve(args.feature_audit) if args.feature_audit else None,
        high_error_threshold_minutes=args.high_error_threshold_minutes,
        top_limit=args.top_limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_event_bridge_audit(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_reportpo_event_bridge_audit(
        settings.resolve(settings.db_path),
        settings.resolve(args.readiness),
        settings.resolve(args.feature_audit),
        settings.resolve(args.lifecycle),
        settings.resolve(args.output),
        settings.resolve(args.summary_output) if args.summary_output else None,
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        high_error_threshold_minutes=args.high_error_threshold_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_bridge_request_pack(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_reportpo_bridge_request_pack(
        settings.resolve(args.event_bridge),
        settings.resolve(args.output),
        settings.resolve(args.priority_output) if args.priority_output else None,
        top_limit=args.top_limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_shared_key_discovery(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_reportpo_shared_key_discovery(
        settings.resolve(args.model_inventory),
        settings.resolve(args.visual_inventory),
        settings.resolve(args.features),
        settings.resolve(args.lifecycle),
        settings.resolve(args.event_bridge),
        settings.resolve(args.candidates_output),
        settings.resolve(args.overlap_output),
        settings.resolve(args.markdown_output),
        settings.resolve(args.manual_template_output) if args.manual_template_output else None,
        settings.resolve(args.pathfinding_report) if args.pathfinding_report else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_manual_bridge_candidates(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_reportpo_manual_bridge_candidates(
        settings.resolve(args.event_bridge),
        settings.resolve(args.lifecycle),
        settings.resolve(args.manual_template),
        settings.resolve(args.suggestions_output),
        settings.resolve(args.template_output),
        settings.resolve(args.markdown_output),
        settings.resolve(args.pathfinding_report) if args.pathfinding_report else None,
        time_window_minutes=args.time_window_minutes,
        top_limit=args.top_limit,
        min_template_score=args.min_template_score,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_truth_intake_kit(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_truth_intake_kit(
        settings.resolve(args.output_dir),
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_truth_dry_run(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = run_ais_truth_dry_run(
        settings.resolve(args.sample),
        settings.resolve(args.output_dir),
        run_match=not args.skip_match,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_pre_ais_evidence_pack(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_pre_ais_evidence_pack(
        settings.resolve(args.output),
        intake_dir=settings.resolve(args.intake_dir),
        db_path=settings.resolve(settings.db_path),
        truth_quality_audit=settings.resolve(args.truth_quality_audit),
        shadow_model_comparison=settings.resolve(args.shadow_model_comparison),
        no_match_candidates=settings.resolve(args.no_match_candidates),
        station_mapping_review=settings.resolve(args.station_mapping_review),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ais_new_files_profile(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_new_files_profile(
        settings.resolve(args.ac_alarm),
        settings.resolve(args.meter_mapping) if args.meter_mapping else None,
        settings.resolve(args.legacy_workbook) if args.legacy_workbook else None,
        settings.resolve(args.output_dir),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_etr_import(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = import_reportpo_etr(
        settings.resolve(args.source),
        settings.resolve(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_etr_fetch(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = fetch_reportpo_etr_querydata(
        settings.resolve(args.template),
        settings.resolve(args.output),
        settings.resolve(args.request_output) if args.request_output else None,
        settings.resolve(args.headers_output) if args.headers_output else None,
        endpoint_url=args.endpoint_url,
        count=args.count,
        pages=args.pages,
        curl_path=args.curl_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_etr_match_truth(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = match_reportpo_truth(
        settings.resolve(settings.db_path),
        settings.resolve(args.reportpo),
        settings.resolve(args.output),
        settings.resolve(args.audit) if args.audit else None,
        settings.resolve(args.alias_file) if args.alias_file else None,
        settings.resolve(args.candidates_output) if args.candidates_output else None,
        max_window_minutes=args.max_window_minutes,
        ambiguity_delta_minutes=args.ambiguity_delta_minutes,
        overwrite=args.overwrite,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_etr_refresh(args: argparse.Namespace) -> None:
    settings = _settings(args)
    fetch_result = fetch_reportpo_etr_querydata(
        settings.resolve(args.template),
        settings.resolve(args.querydata_output),
        settings.resolve(args.request_output) if args.request_output else None,
        settings.resolve(args.headers_output) if args.headers_output else None,
        endpoint_url=args.endpoint_url,
        count=args.count,
        pages=args.pages,
        curl_path=args.curl_path,
    )
    import_result = import_reportpo_etr(
        settings.resolve(args.querydata_output),
        settings.resolve(args.canonical_output),
    )
    match_result = match_reportpo_truth(
        settings.resolve(settings.db_path),
        settings.resolve(args.canonical_output),
        settings.resolve(args.mapping_output),
        settings.resolve(args.audit_output),
        settings.resolve(args.alias_file) if args.alias_file else None,
        settings.resolve(args.candidates_output) if args.candidates_output else None,
        max_window_minutes=args.max_window_minutes,
        ambiguity_delta_minutes=args.ambiguity_delta_minutes,
        overwrite=True,
    )
    report_result = build_shadow_report(
        settings.resolve(settings.db_path),
        settings.resolve(settings.event_file),
        [settings.resolve(path) for path in settings.etr_files],
        settings.resolve(settings.distance_file),
        settings.resolve(args.report_output),
        settings.resolve(args.mapping_output),
    )
    print(
        json.dumps(
            {
                "fetch": fetch_result,
                "import": import_result,
                "match": match_result,
                "shadow_report": report_result,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def cmd_reportpo_etr_alias_template(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_reportpo_alias_template(
        settings.resolve(args.candidates),
        settings.resolve(args.output),
        settings.resolve(args.existing) if args.existing else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_feature_join(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = join_reportpo_features_to_shadow(
        settings.resolve(settings.db_path),
        settings.resolve(args.reportpo),
        settings.resolve(args.output),
        settings.resolve(args.alias_file) if args.alias_file else None,
        max_window_minutes=args.max_window_minutes,
        ambiguity_delta_minutes=args.ambiguity_delta_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_feature_refresh(args: argparse.Namespace) -> None:
    settings = _settings(args)
    fetch_result = fetch_reportpo_etr_querydata(
        settings.resolve(args.template),
        settings.resolve(args.querydata_output),
        settings.resolve(args.request_output) if args.request_output else None,
        settings.resolve(args.headers_output) if args.headers_output else None,
        endpoint_url=args.endpoint_url,
        count=args.count,
        pages=args.pages,
        curl_path=args.curl_path,
    )
    import_result = import_reportpo_etr(
        settings.resolve(args.querydata_output),
        settings.resolve(args.canonical_output),
    )
    join_result = join_reportpo_features_to_shadow(
        settings.resolve(settings.db_path),
        settings.resolve(args.canonical_output),
        settings.resolve(args.feature_output),
        settings.resolve(args.alias_file) if args.alias_file else None,
        max_window_minutes=args.max_window_minutes,
        ambiguity_delta_minutes=args.ambiguity_delta_minutes,
    )
    print(
        json.dumps(
            {
                "fetch": fetch_result,
                "import": import_result,
                "feature_join": join_result,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def cmd_reportpo_feature_diagnostics(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_reportpo_feature_diagnostics(
        settings.resolve(args.comparison),
        settings.resolve(args.feature_audit),
        settings.resolve(args.output),
        settings.resolve(args.segments_output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        high_error_threshold=args.high_error_threshold,
        min_segment_truth=args.min_segment_truth,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_feature_label_audit(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_reportpo_feature_label_audit(
        settings.resolve(args.features),
        settings.resolve(args.diagnostics),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_feature_gap_audit(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_reportpo_feature_gap_audit(
        settings.resolve(settings.db_path),
        settings.resolve(args.reportpo),
        settings.resolve(args.proxy_challenger),
        settings.resolve(args.output),
        settings.resolve(args.summary_output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        settings.resolve(args.alias_file) if args.alias_file else None,
        max_window_minutes=args.max_window_minutes,
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_semantic_inference(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_reportpo_semantic_inference(
        settings.resolve(args.features),
        settings.resolve(args.diagnostics),
        settings.resolve(args.output),
        settings.resolve(args.field_decisions_output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_proxy_challenger(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_reportpo_proxy_challenger(
        settings.resolve(args.features),
        settings.resolve(args.diagnostics),
        settings.resolve(args.semantic_inference),
        settings.resolve(args.output),
        settings.resolve(args.summary_output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        min_group_rows=args.min_group_rows,
        min_global_rows=args.min_global_rows,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_lifecycle_import(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = import_reportpo_lifecycle(
        settings.resolve(args.source),
        settings.resolve(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_lifecycle_fetch(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = fetch_reportpo_lifecycle_querydata(
        settings.resolve(args.template),
        settings.resolve(args.output),
        settings.resolve(args.request_output) if args.request_output else None,
        settings.resolve(args.headers_output) if args.headers_output else None,
        endpoint_url=args.endpoint_url,
        count=args.count,
        pages=args.pages,
        curl_path=args.curl_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_lifecycle_join(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = join_reportpo_lifecycle_to_shadow(
        settings.resolve(settings.db_path),
        settings.resolve(args.lifecycle),
        settings.resolve(args.output),
        settings.resolve(args.alias_file) if args.alias_file else None,
        max_window_minutes=args.max_window_minutes,
        ambiguity_delta_minutes=args.ambiguity_delta_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_lifecycle_refresh(args: argparse.Namespace) -> None:
    settings = _settings(args)
    fetch_result = fetch_reportpo_lifecycle_querydata(
        settings.resolve(args.template),
        settings.resolve(args.querydata_output),
        settings.resolve(args.request_output) if args.request_output else None,
        settings.resolve(args.headers_output) if args.headers_output else None,
        endpoint_url=args.endpoint_url,
        count=args.count,
        pages=args.pages,
        curl_path=args.curl_path,
    )
    import_result = import_reportpo_lifecycle(
        settings.resolve(args.querydata_output),
        settings.resolve(args.canonical_output),
    )
    join_result = join_reportpo_lifecycle_to_shadow(
        settings.resolve(settings.db_path),
        settings.resolve(args.canonical_output),
        settings.resolve(args.join_output),
        settings.resolve(args.alias_file) if args.alias_file else None,
        max_window_minutes=args.max_window_minutes,
        ambiguity_delta_minutes=args.ambiguity_delta_minutes,
    )
    print(
        json.dumps(
            {
                "fetch": fetch_result,
                "import": import_result,
                "lifecycle_join": join_result,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def cmd_reportpo_model_inventory(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_reportpo_model_inventory(
        settings.resolve(args.network_capture),
        settings.resolve(args.querydata_capture),
        settings.resolve(args.output),
        settings.resolve(args.candidates_output),
        settings.resolve(args.visuals_output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_pending_import(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = import_reportpo_pending(
        settings.resolve(args.source),
        settings.resolve(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_pending_fetch(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = fetch_reportpo_pending_querydata(
        settings.resolve(args.template),
        settings.resolve(args.output),
        settings.resolve(args.request_output) if args.request_output else None,
        settings.resolve(args.headers_output) if args.headers_output else None,
        endpoint_url=args.endpoint_url,
        count=args.count,
        pages=args.pages,
        curl_path=args.curl_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_pending_overlap(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = audit_reportpo_pending_overlap(
        settings.resolve(settings.db_path),
        settings.resolve(args.pending),
        settings.resolve(args.feature_audit),
        settings.resolve(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_reportpo_pending_refresh(args: argparse.Namespace) -> None:
    settings = _settings(args)
    fetch_result = fetch_reportpo_pending_querydata(
        settings.resolve(args.template),
        settings.resolve(args.querydata_output),
        settings.resolve(args.request_output) if args.request_output else None,
        settings.resolve(args.headers_output) if args.headers_output else None,
        endpoint_url=args.endpoint_url,
        count=args.count,
        pages=args.pages,
        curl_path=args.curl_path,
    )
    import_result = import_reportpo_pending(
        settings.resolve(args.querydata_output),
        settings.resolve(args.canonical_output),
    )
    overlap_result = audit_reportpo_pending_overlap(
        settings.resolve(settings.db_path),
        settings.resolve(args.canonical_output),
        settings.resolve(args.feature_audit),
        settings.resolve(args.overlap_output),
    )
    print(
        json.dumps(
            {
                "fetch": fetch_result,
                "import": import_result,
                "overlap": overlap_result,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def cmd_sfsd_import(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = import_sfsd_events(
        settings.resolve(args.source),
        settings.resolve(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_sfsd_model_fetch(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = fetch_sfsd_models_and_exploration(
        settings.resolve(args.output),
        endpoint_url=args.endpoint_url,
        headers_output=settings.resolve(args.headers_output) if args.headers_output else None,
        curl_path=args.curl_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_sfsd_fetch(args: argparse.Namespace) -> None:
    settings = _settings(args)
    event_type = None if args.all_event_types else args.event_type
    result = fetch_sfsd_event_detail_querydata(
        settings.resolve(args.template),
        settings.resolve(args.output),
        settings.resolve(args.request_output) if args.request_output else None,
        settings.resolve(args.headers_output) if args.headers_output else None,
        endpoint_url=args.endpoint_url,
        count=args.count,
        pages=args.pages,
        curl_path=args.curl_path,
        event_type=event_type,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_sfsd_refresh(args: argparse.Namespace) -> None:
    settings = _settings(args)
    event_type = None if args.all_event_types else args.event_type
    result = refresh_sfsd_long_outage_evidence(
        settings.resolve(args.template),
        settings.resolve(args.querydata_output),
        settings.resolve(args.canonical_output),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        request_output=settings.resolve(args.request_output) if args.request_output else None,
        headers_output=settings.resolve(args.headers_output) if args.headers_output else None,
        endpoint_url=args.endpoint_url,
        priority_csv=settings.resolve(args.priority),
        event_bridge_csv=settings.resolve(args.event_bridge) if args.event_bridge else None,
        feature_audit_csv=settings.resolve(args.feature_audit) if args.feature_audit else None,
        count=args.count,
        pages=args.pages,
        curl_path=args.curl_path,
        event_type=event_type,
        max_window_minutes=args.max_window_minutes,
        ambiguity_delta_minutes=args.ambiguity_delta_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_sfsd_long_outage_evidence(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_sfsd_long_outage_evidence(
        settings.resolve(args.priority),
        settings.resolve(args.sfsd),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        event_bridge_csv=settings.resolve(args.event_bridge) if args.event_bridge else None,
        feature_audit_csv=settings.resolve(args.feature_audit) if args.feature_audit else None,
        max_window_minutes=args.max_window_minutes,
        ambiguity_delta_minutes=args.ambiguity_delta_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_sfsd_remaining_gap_review(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_sfsd_remaining_gap_review(
        settings.resolve(args.evidence),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        include_matched_momentary=args.include_matched_momentary,
        high_error_minutes=args.high_error_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_sfsd_gap_resolution_audit(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_sfsd_gap_resolution_audit(
        settings.resolve(args.gap_review),
        settings.resolve(args.sfsd),
        settings.resolve(settings.db_path),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        nearest_window_minutes=args.nearest_window_minutes,
        bridge_window_minutes=args.bridge_window_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_sfsd_source_trace_candidates(args: argparse.Namespace) -> None:
    settings = _settings(args)
    statuses = tuple(status.strip() for status in args.statuses.split(",") if status.strip())
    result = build_sfsd_source_trace_candidates(
        settings.resolve(args.gap_resolution),
        settings.resolve(args.output),
        statuses=statuses or ("source_trace_required_for_topology_gap",),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_sfsd_gap_decision_pack(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_sfsd_gap_decision_pack(
        settings.resolve(args.gap_resolution),
        settings.resolve(args.source_trace_audit),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_readiness_report(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_shadow_readiness_pack(
        settings,
        samples_path=args.samples,
        output_dir=args.output_dir,
        env_path=args.env,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_export_backlog(args: argparse.Namespace) -> None:
    settings = _settings(args)
    db = RuntimeDb(settings.resolve(settings.db_path))
    db.init()
    result = export_no_meter_backlog(db, settings.resolve(args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_no_match_repair_candidates(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_no_match_repair_candidates(
        settings.resolve(settings.db_path),
        settings.resolve(args.output),
        min_events=args.min_events,
        max_sample_ids=args.max_sample_ids,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_trace_no_match_candidates(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = trace_no_match_candidates_against_upstream(
        settings.resolve(args.candidates),
        settings.resolve(args.upstream),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_source_trace_no_match_candidates(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = trace_no_match_candidates_from_source_system(
        settings.resolve(args.candidates),
        settings.resolve(args.upstream),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        redacted_dir=settings.resolve(args.redacted_dir) if args.redacted_dir else None,
        base_url=args.base_url,
        trace_url=args.trace_url,
        timeout_seconds=args.timeout_seconds,
        sleep_seconds=args.sleep_seconds,
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_private_protection_overrides(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_private_protection_mapping_overrides(
        settings.resolve(settings.db_path),
        settings.resolve(args.source_trace_audit),
        settings.resolve(args.output),
        registry_xlsx=settings.resolve(args.registry) if args.registry else None,
        device_id=args.device_id,
        status=args.status,
        reviewed_by=args.reviewed_by,
        reviewed_at=args.reviewed_at,
        base_url=args.base_url,
        trace_url=args.trace_url,
        timeout_seconds=args.timeout_seconds,
        sleep_seconds=args.sleep_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_apply_protection_overrides(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = apply_protection_mapping_overrides(
        settings.resolve(settings.db_path),
        settings.resolve(args.overrides),
        audit_output=settings.resolve(args.audit_output) if args.audit_output else None,
        required_status=args.required_status,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_source_trace_schematic(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_source_trace_schematic(
        settings.resolve(args.source_trace_audit),
        settings.resolve(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_station_mapping(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_station_district_mapping(
        settings.resolve(settings.db_path),
        settings.resolve(settings.event_file),
        [settings.resolve(path) for path in settings.etr_files],
        settings.resolve(settings.distance_file),
        settings.resolve(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_model_scope_comparison(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_model_scope_comparison(
        settings.resolve(settings.event_file),
        [settings.resolve(path) for path in settings.etr_files],
        settings.resolve(settings.distance_file),
        settings.resolve(args.mapping),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_station_mapping_review(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_station_mapping_review(
        settings.resolve(settings.db_path),
        settings.resolve(settings.event_file),
        [settings.resolve(path) for path in settings.etr_files],
        settings.resolve(settings.distance_file),
        settings.resolve(args.mapping),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_model_scope_train_challenger(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = train_scope_challenger_model(
        settings.resolve(settings.event_file),
        [settings.resolve(path) for path in settings.etr_files],
        settings.resolve(settings.distance_file),
        settings.resolve(args.mapping),
        settings.resolve(args.output_model),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        train_scope=args.train_scope,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_shadow_model_compare(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_shadow_model_comparison(
        settings.resolve(settings.db_path),
        settings.resolve(args.current_model),
        settings.resolve(args.challenger_model),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        settings.resolve(args.truth_mapping) if args.truth_mapping else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_shadow_truth_quality_audit(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_truth_quality_audit(
        settings.resolve(args.comparison),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        micro_threshold_minutes=args.micro_threshold_minutes,
        short_threshold_minutes=args.short_threshold_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_shadow_incident_cluster(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_shadow_incident_clusters(
        settings.resolve(settings.db_path),
        settings.resolve(args.comparison),
        settings.resolve(args.audit),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        prediction_policy=args.prediction_policy,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_shadow_incident_replay_report(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_shadow_incident_replay_report(
        settings.resolve(settings.db_path),
        settings.resolve(args.comparison),
        settings.resolve(args.audit),
        settings.resolve(args.incident_comparison),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        high_error_minutes=args.high_error_minutes,
        focus_feeders=tuple(args.focus_feeder or []),
        focus_devices=tuple(args.focus_device or []),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_shadow_error_diagnostics(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_shadow_error_diagnostics(
        settings.resolve(args.comparison),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_shadow_ais_history_challenger(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ais_history_challenger(
        settings.resolve(settings.db_path),
        settings.resolve(args.comparison),
        settings.resolve(args.ais_truth),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        min_history_rows=args.min_history_rows,
        lower_quantile=args.lower_quantile,
        upper_quantile=args.upper_quantile,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_shadow_long_outage_challenger(args: argparse.Namespace) -> None:
    settings = _settings(args)
    horizons = tuple(int(value.strip()) for value in args.horizons.split(",") if value.strip())
    result = build_long_outage_refresh_challenger(
        settings.resolve(settings.db_path),
        settings.resolve(args.comparison),
        settings.resolve(args.ais_truth),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        history_challenger_csv=settings.resolve(args.history_challenger) if args.history_challenger else None,
        horizons_minutes=horizons,
        min_history_rows=args.min_history_rows,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_shadow_webex_elapsed_challenger(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_webex_elapsed_refresh_challenger(
        settings.resolve(settings.db_path),
        settings.resolve(args.comparison),
        settings.resolve(args.audit),
        settings.resolve(args.ais_truth),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        history_challenger_csv=settings.resolve(args.history_challenger) if args.history_challenger else None,
        min_history_rows=args.min_history_rows,
        post_restore_tolerance_minutes=args.post_restore_tolerance_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_shadow_active_state_remaining_challenger(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_active_state_remaining_challenger(
        settings.resolve(settings.db_path),
        settings.resolve(args.readiness),
        settings.resolve(args.ais_truth),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        settings.resolve(args.segments_output) if args.segments_output else None,
        min_segment_rows=args.min_segment_rows,
        min_meter_history_rows=args.min_meter_history_rows,
        high_error_minutes=args.high_error_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_shadow_long_outage_root_cause_pack(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_long_outage_root_cause_pack(
        settings.resolve(args.active_state),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        settings.resolve(args.review_template_output) if args.review_template_output else None,
        shared_key_audit_csv=settings.resolve(args.shared_key_audit) if args.shared_key_audit else None,
        manual_bridge_csv=settings.resolve(args.manual_bridge) if args.manual_bridge else None,
        lifecycle_review_csv=settings.resolve(args.lifecycle_review) if args.lifecycle_review else None,
        high_error_minutes=args.high_error_minutes,
        duration_outlier_minutes=args.duration_outlier_minutes,
        sparse_history_min_rows=args.sparse_history_min_rows,
        top_limit=args.top_limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_shadow_webex_device_state_diagnostics(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_webex_device_state_diagnostic(
        settings.resolve(settings.db_path),
        settings.resolve(args.comparison),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ops_lifecycle_template(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = build_ops_lifecycle_template(
        settings.resolve(args.comparison),
        settings.resolve(args.output),
        settings.resolve(args.markdown_output) if args.markdown_output else None,
        long_outage_csv=settings.resolve(args.long_outage) if args.long_outage else None,
        webex_elapsed_csv=settings.resolve(args.webex_elapsed) if args.webex_elapsed else None,
        horizon_minutes=args.horizon_minutes,
        top_n=args.top_n,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_ops_lifecycle_validate(args: argparse.Namespace) -> None:
    settings = _settings(args)
    result = validate_ops_lifecycle_file(
        settings.resolve(args.input),
        settings.resolve(args.output_valid) if args.output_valid else None,
        settings.resolve(args.rejects) if args.rejects else None,
        settings.resolve(args.markdown_output) if args.markdown_output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_summary(args: argparse.Namespace) -> None:
    settings = _settings(args)
    db = RuntimeDb(settings.resolve(settings.db_path))
    db.init()
    with db.session() as conn:
        summary = {}
        for table in (
            "webex_messages",
            "outage_events",
            "customer_assets",
            "predictions",
            "notifications",
            "model_runs",
            "ais_inbound_requests",
            "ais_inbound_callbacks",
        ):
            try:
                summary[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.OperationalError:
                summary[table] = None
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AIS ETR automation MVP")
    parser.add_argument("--env", default=".env", help="Path to .env file")
    parser.add_argument("--db", default=None, help="Override SQLite path")
    sub = parser.add_subparsers(required=True)

    init_db = sub.add_parser("init-db", help="Create or migrate runtime SQLite schema")
    init_db.set_defaults(func=cmd_init_db)

    build_registry = sub.add_parser("build-registry", help="Load AIS assets from upstream_result.xlsx")
    build_registry.add_argument("--registry", default=None, help="Override upstream result workbook")
    build_registry.set_defaults(func=cmd_build_registry)

    train = sub.add_parser("train", help="Train quantile baseline ETR model")
    train.set_defaults(func=cmd_train)

    poll = sub.add_parser("poll-once", help="Poll Webex once and send shadow notifications")
    poll.add_argument("--max-messages", type=int, default=50)
    poll.set_defaults(func=cmd_poll_once)

    poll_loop = sub.add_parser("poll-loop", help="Poll Webex repeatedly for shadow pilot runs")
    poll_loop.add_argument("--max-messages", type=int, default=50)
    poll_loop.add_argument("--interval-seconds", type=int, default=60)
    poll_loop.add_argument("--iterations", type=int, default=None)
    poll_loop.set_defaults(func=cmd_poll_loop)

    webex_auth = sub.add_parser("webex-auth", help="Authorize Webex OAuth integration and store local token")
    webex_auth.add_argument("--no-browser", action="store_true", help="Print the auth URL but do not open a browser")
    webex_auth.add_argument("--timeout-seconds", type=int, default=300)
    webex_auth.set_defaults(func=cmd_webex_auth)

    webex_refresh = sub.add_parser("webex-refresh-token", help="Refresh the stored Webex OAuth token")
    webex_refresh.set_defaults(func=cmd_webex_refresh_token)

    webex_rooms = sub.add_parser("webex-rooms", help="List visible Webex rooms with the configured token")
    webex_rooms.add_argument("--query", default=None, help="Filter room titles locally")
    webex_rooms.add_argument("--max-rooms", type=int, default=100)
    webex_rooms.set_defaults(func=cmd_webex_rooms)

    webex_export = sub.add_parser("webex-export-history", help="Export Webex room message history to local JSONL/CSV")
    webex_export.add_argument("--output", default="runtime/webex_history_export.jsonl")
    webex_export.add_argument("--csv-output", default="runtime/webex_history_export.csv")
    webex_export.add_argument("--sample-output", default=None, help="Optional JSONL corpus for parser sample curation")
    webex_export.add_argument("--max-messages", type=int, default=500)
    webex_export.add_argument("--page-size", type=int, default=100)
    webex_export.add_argument("--before", default=None, help="Optional Webex API before timestamp, e.g. 2026-06-17T00:00:00Z")
    webex_export.add_argument("--after", default=None, help="Stop after messages older than this timestamp")
    webex_export.add_argument("--sleep-seconds", type=float, default=0.2)
    webex_export.add_argument("--include-room-id", action="store_true", help="Include raw room id in output")
    webex_export.add_argument("--include-actor", action="store_true", help="Include sender id/email/display name in output")
    webex_export.add_argument("--include-raw", action="store_true", help="Include full raw Webex message JSON")
    webex_export.set_defaults(func=cmd_webex_export_history)

    webex_replay = sub.add_parser("webex-replay-history", help="Replay exported Webex history through parser/matcher/predictor offline")
    webex_replay.add_argument("--source", default="runtime/webex_history_export.jsonl")
    webex_replay.add_argument("--audit-output", default="runtime/webex_history_replay_audit.csv")
    webex_replay.add_argument("--limit", type=int, default=None)
    webex_replay.add_argument("--reprocess-existing", action="store_true", help="Reparse messages already present in runtime DB")
    webex_replay.add_argument(
        "--no-notification-capture",
        action="store_true",
        help="Do not record replay shadow payloads in notifications table",
    )
    webex_replay.set_defaults(func=cmd_webex_replay_history)

    line_import = sub.add_parser("line-import-history", help="Normalize approved LINE/OpenChat manual export to sanitized JSONL")
    line_import.add_argument("--source", required=True, help="CSV/JSON/JSONL/TXT/ZIP export approved by group owner/moderator")
    line_import.add_argument("--manifest", required=True, help="Consent/approval manifest JSON")
    line_import.add_argument("--output", default="runtime/line_history_normalized.jsonl")
    line_import.set_defaults(func=cmd_line_import_history)

    line_import_chat = sub.add_parser("line-import-chat-export", help="Normalize approved LINE chat .txt/.zip export to sanitized JSONL")
    line_import_chat.add_argument("--source", required=True, help="LINE chat .txt/.zip export approved by group owner/moderator")
    line_import_chat.add_argument("--manifest", required=True, help="Consent/approval manifest JSON")
    line_import_chat.add_argument("--output", default="runtime/line_history_normalized.jsonl")
    line_import_chat.set_defaults(func=cmd_line_import_history)

    line_webhook = sub.add_parser("line-webhook-server", help="Capture new approved LINE group messages through verified webhook")
    line_webhook.add_argument("--host", default="127.0.0.1")
    line_webhook.add_argument("--port", type=int, default=8091)
    line_webhook.add_argument("--path", default="/line/webhook")
    line_webhook.add_argument("--output", default="runtime/line_webhook_capture.jsonl")
    line_webhook.add_argument("--sqlite-output", default=DEFAULT_WEBHOOK_SQLITE)
    line_webhook.set_defaults(func=cmd_line_webhook_server)

    line_replay = sub.add_parser("line-replay-history", help="Replay sanitized LINE/OpenChat history through parser/matcher/predictor offline")
    line_replay.add_argument("--source", default="runtime/line_history_normalized.jsonl")
    line_replay.add_argument("--audit-output", default="runtime/line_history_replay_audit.csv")
    line_replay.add_argument("--limit", type=int, default=None)
    line_replay.add_argument("--reprocess-existing", action="store_true", help="Reparse messages already present in runtime DB")
    line_replay.add_argument(
        "--no-notification-capture",
        action="store_true",
        help="Do not record replay shadow payloads in notifications table",
    )
    line_replay.set_defaults(func=cmd_line_replay_history)

    line_corpus = sub.add_parser("line-build-training-corpus", help="Build sanitized LINE parser training corpus and QA reports")
    line_corpus.add_argument(
        "--sources",
        nargs="+",
        default=["runtime/line_webhook_capture.jsonl", "runtime/line_history_normalized.jsonl"],
        help="Normalized LINE JSONL/CSV sources",
    )
    line_corpus.add_argument("--output", default=DEFAULT_TRAINING_CORPUS_OUTPUT)
    line_corpus.add_argument("--audit-output", default=DEFAULT_TRAINING_CORPUS_AUDIT)
    line_corpus.add_argument("--markdown-output", default=DEFAULT_TRAINING_CORPUS_REPORT)
    line_corpus.set_defaults(func=cmd_line_build_training_corpus)

    line_train = sub.add_parser(
        "line-train-parser-model",
        help="Train shadow parser candidate classifier from sanitized LINE corpus",
    )
    line_train.add_argument("--source", default=DEFAULT_TRAINING_CORPUS_OUTPUT, help="Sanitized LINE training corpus JSONL")
    line_train.add_argument("--model-output", default=DEFAULT_LINE_PARSER_MODEL_OUTPUT)
    line_train.add_argument("--split-output", default=DEFAULT_LINE_PARSER_SPLIT_OUTPUT)
    line_train.add_argument("--eval-output", default=DEFAULT_LINE_PARSER_EVAL_OUTPUT)
    line_train.add_argument("--markdown-output", default=DEFAULT_LINE_PARSER_REPORT_OUTPUT)
    line_train.add_argument("--review-output", default=DEFAULT_LINE_PARSER_REVIEW_OUTPUT)
    line_train.add_argument("--max-features", type=int, default=4000)
    line_train.add_argument("--threshold", type=float, default=0.5)
    line_train.add_argument("--seed", default="line-parser-shadow-v1")
    line_train.set_defaults(func=cmd_line_train_parser_model)

    line_place = sub.add_parser(
        "line-place-topology-lookup",
        help="Match sanitized LINE place excerpts to local feeder/protection topology evidence",
    )
    line_place.add_argument("--review-source", default=DEFAULT_LINE_PLACE_REVIEW_SOURCE)
    line_place.add_argument("--upstream", default="upstream_result.xlsx")
    line_place.add_argument("--output", default=DEFAULT_LINE_PLACE_OUTPUT)
    line_place.add_argument("--enriched-output", default=DEFAULT_LINE_PLACE_ENRICHED_OUTPUT)
    line_place.add_argument("--markdown-output", default=DEFAULT_LINE_PLACE_MARKDOWN_OUTPUT)
    line_place.add_argument("--owner-review-output", default=DEFAULT_LINE_PLACE_OWNER_REVIEW_OUTPUT)
    line_place.add_argument("--owner-review-markdown-output", default=DEFAULT_LINE_PLACE_OWNER_REVIEW_MARKDOWN_OUTPUT)
    line_place.set_defaults(func=cmd_line_place_topology_lookup)

    line_google_geocode = sub.add_parser(
        "line-google-geocode-missing-places",
        help="Geocode sanitized LINE place queries through Google Maps Geocoding API",
    )
    line_google_geocode.add_argument("--source", default=DEFAULT_LINE_PLACE_OUTPUT)
    line_google_geocode.add_argument("--output", default=DEFAULT_LINE_GOOGLE_GEOCODE_OUTPUT)
    line_google_geocode.add_argument("--markdown-output", default=DEFAULT_LINE_GOOGLE_GEOCODE_MARKDOWN_OUTPUT)
    line_google_geocode.add_argument("--statuses", default="no_local_match")
    line_google_geocode.add_argument("--query-suffix", default="Sakon Nakhon Thailand")
    line_google_geocode.add_argument("--api-key-env", default="GOOGLE_MAPS_API_KEY")
    line_google_geocode.add_argument("--limit", type=int, default=None)
    line_google_geocode.add_argument("--max-candidates-per-row", type=int, default=3)
    line_google_geocode.add_argument("--timeout-seconds", type=float, default=15.0)
    line_google_geocode.add_argument("--sleep-seconds", type=float, default=0.2)
    line_google_geocode.set_defaults(func=cmd_line_google_geocode_missing_places)

    mock_webhook = sub.add_parser("mock-webhook", help="Run a local shadow webhook receiver")
    mock_webhook.add_argument("--host", default="127.0.0.1")
    mock_webhook.add_argument("--port", type=int, default=8080)
    mock_webhook.add_argument("--path", default=MOCK_WEBHOOK_PATH)
    mock_webhook.add_argument("--output", default="runtime/mock_webhook_events.jsonl")
    mock_webhook.set_defaults(func=cmd_mock_webhook)

    ais_inbound = sub.add_parser("ais-inbound-api", help="Run shadow AIS inbound outage verification API")
    ais_inbound.add_argument("--host", default="127.0.0.1")
    ais_inbound.add_argument("--port", type=int, default=8090)
    ais_inbound.add_argument("--path", default=AIS_INBOUND_PATH)
    ais_inbound.add_argument("--api-key", default=None, help="Optional X-API-Key/Bearer credential required from AIS")
    ais_inbound.add_argument("--callback-url", default=None, help="Optional AIS callback URL; omitted means capture only")
    ais_inbound.add_argument("--requests-output", default="runtime/ais_inbound_requests.jsonl")
    ais_inbound.add_argument("--callbacks-output", default="runtime/ais_inbound_callbacks.jsonl")
    ais_inbound.add_argument("--match-window-minutes", type=int, default=360)
    ais_inbound.add_argument(
        "--rate-limit-per-minute",
        type=int,
        default=AIS_INBOUND_DEFAULT_RATE_LIMIT_PER_MINUTE,
        help="Per-client POST limit; 0 disables rate limiting",
    )
    ais_inbound.add_argument("--no-callback-post", action="store_true", help="Capture callback payload without POSTing")
    ais_inbound.set_defaults(func=cmd_ais_inbound_api)

    ais_inbound_verify = sub.add_parser("ais-inbound-verify-file", help="Process one AIS inbound JSON request offline")
    ais_inbound_verify.add_argument("--source", default="runtime/ais_inbound_demo_request.json")
    ais_inbound_verify.add_argument("--callback-url", default=None)
    ais_inbound_verify.add_argument("--requests-output", default="runtime/ais_inbound_requests.jsonl")
    ais_inbound_verify.add_argument("--callbacks-output", default="runtime/ais_inbound_callbacks.jsonl")
    ais_inbound_verify.add_argument("--match-window-minutes", type=int, default=360)
    ais_inbound_verify.add_argument("--no-callback-post", action="store_true")
    ais_inbound_verify.set_defaults(func=cmd_ais_inbound_verify_file)

    ais_inbound_demo = sub.add_parser("ais-inbound-demo-request", help="Write a sample AIS inbound verification JSON")
    ais_inbound_demo.add_argument("--output", default="runtime/ais_inbound_demo_request.json")
    ais_inbound_demo.add_argument("--peano", default="PEANO_SAMPLE")
    ais_inbound_demo.set_defaults(func=cmd_ais_inbound_demo_request)

    ais_inbound_contract = sub.add_parser(
        "ais-inbound-contract-pack",
        help="Write OpenAPI, Postman, demo JSON, and Markdown docs for the AIS inbound API",
    )
    ais_inbound_contract.add_argument("--output-dir", default="runtime")
    ais_inbound_contract.add_argument("--public-base", default=None)
    ais_inbound_contract.add_argument("--status-file", default="runtime/ais_inbound_public_endpoint_status.json")
    ais_inbound_contract.set_defaults(func=cmd_ais_inbound_contract_pack)

    ais_inbound_test_kit = sub.add_parser(
        "ais-inbound-test-kit",
        help="Write a shareable English AIS pilot test kit without the private pilot key",
    )
    ais_inbound_test_kit.add_argument("--output-dir", default="runtime/ais_inbound_test_kit")
    ais_inbound_test_kit.add_argument("--source-dir", default="runtime")
    ais_inbound_test_kit.add_argument("--zip-output", default="runtime/ais_inbound_test_kit.zip")
    ais_inbound_test_kit.add_argument("--public-base", default=None)
    ais_inbound_test_kit.add_argument("--status-file", default="runtime/ais_inbound_public_endpoint_status.json")
    ais_inbound_test_kit.set_defaults(func=cmd_ais_inbound_test_kit)

    ais_inbound_prod_pack = sub.add_parser(
        "ais-inbound-production-pack",
        help="Write English production migration checklist, runbook, and env skeleton for AIS inbound API",
    )
    ais_inbound_prod_pack.add_argument("--output-dir", default="runtime")
    ais_inbound_prod_pack.add_argument("--public-base", default=None)
    ais_inbound_prod_pack.add_argument("--status-file", default="runtime/ais_inbound_public_endpoint_status.json")
    ais_inbound_prod_pack.set_defaults(func=cmd_ais_inbound_production_pack)

    ais_inbound_doc_qa = sub.add_parser(
        "ais-inbound-doc-qa",
        help="Scan AIS-facing API docs for stale URLs, Thai text, and obvious secret leakage",
    )
    ais_inbound_doc_qa.add_argument("--docs-dir", default="runtime")
    ais_inbound_doc_qa.add_argument("--public-base", default=None)
    ais_inbound_doc_qa.add_argument("--status-file", default="runtime/ais_inbound_public_endpoint_status.json")
    ais_inbound_doc_qa.add_argument("--output", default="runtime/ais_inbound_doc_qa.md")
    ais_inbound_doc_qa.set_defaults(func=cmd_ais_inbound_doc_qa)

    ais_inbound_security = sub.add_parser(
        "ais-inbound-security-audit",
        help="Scan shareable AIS inbound artifacts for pilot key, token, room id, and identifier leaks",
    )
    ais_inbound_security.add_argument("--runtime-dir", default="runtime")
    ais_inbound_security.add_argument("--private-key-file", default="runtime/private/ais_inbound_pilot_key.txt")
    ais_inbound_security.add_argument("--output", default="runtime/ais_inbound_security_audit.md")
    ais_inbound_security.add_argument("--json-output", default="runtime/ais_inbound_security_audit.json")
    ais_inbound_security.set_defaults(func=cmd_ais_inbound_security_audit)

    ais_inbound_status = sub.add_parser(
        "ais-inbound-status",
        help="Summarize durable AIS inbound requests from SQLite without exposing raw meter identifiers",
    )
    ais_inbound_status.add_argument("--output", default="runtime/ais_inbound_status_report.md")
    ais_inbound_status.add_argument("--limit", type=int, default=20)
    ais_inbound_status.set_defaults(func=cmd_ais_inbound_status)

    ais_inbound_demo_ready = sub.add_parser(
        "ais-inbound-model-demo-readiness",
        help="Report whether AIS inbound SQLite evidence contains a redacted end-to-end shadow ETR demo path",
    )
    ais_inbound_demo_ready.add_argument("--output", default="runtime/ais_inbound_model_demo_readiness.md")
    ais_inbound_demo_ready.add_argument("--limit", type=int, default=5)
    ais_inbound_demo_ready.set_defaults(func=cmd_ais_inbound_model_demo_readiness)

    ais_inbound_demo_rehearsal = sub.add_parser(
        "ais-inbound-shadow-demo-rehearsal",
        help="Create one redacted smoke/demo AIS inbound request from existing runtime evidence",
    )
    ais_inbound_demo_rehearsal.add_argument("--output", default="runtime/ais_inbound_model_demo_rehearsal.md")
    ais_inbound_demo_rehearsal.add_argument("--request-id", default=None)
    ais_inbound_demo_rehearsal.add_argument("--requests-output", default="runtime/ais_inbound_requests.jsonl")
    ais_inbound_demo_rehearsal.add_argument("--callbacks-output", default="runtime/ais_inbound_callbacks.jsonl")
    ais_inbound_demo_rehearsal.add_argument("--match-window-minutes", type=int, default=360)
    ais_inbound_demo_rehearsal.set_defaults(func=cmd_ais_inbound_shadow_demo_rehearsal)

    ais_inbound_audit = sub.add_parser(
        "ais-inbound-audit-export",
        help="Export safe AIS inbound request evidence for pilot review",
    )
    ais_inbound_audit.add_argument("--output", default="runtime/ais_inbound_audit_export.csv")
    ais_inbound_audit.add_argument("--markdown-output", default="runtime/ais_inbound_audit_export.md")
    ais_inbound_audit.add_argument("--limit", type=int, default=200)
    ais_inbound_audit.add_argument("--include-smoke", action="store_true")
    ais_inbound_audit.set_defaults(func=cmd_ais_inbound_audit_export)

    ais_inbound_snapshot = sub.add_parser(
        "ais-inbound-db-snapshot",
        help="Create an internal SQLite backup snapshot plus redacted evidence report",
    )
    ais_inbound_snapshot.add_argument("--output-dir", default="runtime/snapshots")
    ais_inbound_snapshot.add_argument("--label", default="manual")
    ais_inbound_snapshot.add_argument("--output", default=None, help="Optional fixed Markdown output path")
    ais_inbound_snapshot.add_argument("--json-output", default=None, help="Optional fixed JSON output path")
    ais_inbound_snapshot.set_defaults(func=cmd_ais_inbound_db_snapshot)

    ais_inbound_first_hit = sub.add_parser(
        "ais-inbound-first-hit-packet",
        help="Build a redacted operator packet for the first/latest real AIS inbound request",
    )
    ais_inbound_first_hit.add_argument("--output", default="runtime/ais_inbound_first_hit_packet.md")
    ais_inbound_first_hit.add_argument("--json-output", default="runtime/ais_inbound_first_hit_packet.json")
    ais_inbound_first_hit.set_defaults(func=cmd_ais_inbound_first_hit_packet)

    ais_inbound_gate = sub.add_parser(
        "ais-inbound-readiness-gate",
        help="Build one PASS/WARN/FAIL gate for AIS inbound API pilot and production readiness",
    )
    ais_inbound_gate.add_argument("--status-file", default="runtime/ais_inbound_public_endpoint_status.json")
    ais_inbound_gate.add_argument("--verification-file", default="runtime/ais_inbound_public_endpoint_verification.json")
    ais_inbound_gate.add_argument("--doc-qa-file", default="runtime/ais_inbound_doc_qa.md")
    ais_inbound_gate.add_argument("--first-hit-file", default="runtime/ais_inbound_first_hit_packet.json")
    ais_inbound_gate.add_argument("--output", default="runtime/ais_inbound_readiness_gate.md")
    ais_inbound_gate.add_argument("--json-output", default="runtime/ais_inbound_readiness_gate.json")
    ais_inbound_gate.set_defaults(func=cmd_ais_inbound_readiness_gate)

    pilot_completion = sub.add_parser(
        "pilot-completion-gate",
        help="Build the final Pilot Complete gate while keeping production_send blocked",
    )
    pilot_completion.add_argument("--status-file", default="runtime/ais_inbound_public_endpoint_status.json")
    pilot_completion.add_argument("--verification-file", default="runtime/ais_inbound_public_endpoint_verification.json")
    pilot_completion.add_argument("--security-audit-file", default="runtime/ais_inbound_security_audit.json")
    pilot_completion.add_argument("--db-snapshot-file", default="runtime/ais_inbound_db_snapshot_latest.json")
    pilot_completion.add_argument("--readiness-gate-file", default="runtime/ais_inbound_readiness_gate.json")
    pilot_completion.add_argument("--green-gate-file", default="runtime/green_gate_tracker.md")
    pilot_completion.add_argument("--production-gate-file", default="runtime/production_readiness_gate.md")
    pilot_completion.add_argument("--share-pack-zip", default="runtime/shareable_pea_pitch_pack.zip")
    pilot_completion.add_argument("--share-pack-dir", default="runtime/shareable_pea_pitch_pack")
    pilot_completion.add_argument(
        "--chatgpt-round2-file",
        default="runtime/browser_chatgpt_visual_review_response_round2.md",
    )
    pilot_completion.add_argument(
        "--chatgpt-round3-file",
        default="runtime/browser_chatgpt_visual_review_response_round3.md",
    )
    pilot_completion.add_argument("--output", default="runtime/pilot_completion_gate.md")
    pilot_completion.add_argument("--json-output", default="runtime/pilot_completion_gate.json")
    pilot_completion.set_defaults(func=cmd_pilot_completion_gate)

    sanitized_export = sub.add_parser(
        "export-sanitized-codebase",
        help="Build a ChatGPT-safe source bundle excluding runtime secrets, DBs, logs, and identifiers",
    )
    sanitized_export.add_argument("--output-dir", default="runtime/chatgpt_production_review")
    sanitized_export.add_argument("--zip-output", default="runtime/sanitized_codebase_bundle.zip")
    sanitized_export.add_argument("--manifest-output", default="runtime/sanitized_codebase_manifest.json")
    sanitized_export.add_argument("--prompt-output", default="runtime/chatgpt_production_review_prompt.md")
    sanitized_export.add_argument("--audit-output", default="runtime/chatgpt_production_review_audit.md")
    sanitized_export.set_defaults(func=cmd_export_sanitized_codebase)

    production_gate = sub.add_parser(
        "production-readiness-gate",
        help="Build the cloud production path gate while keeping customer-facing Auto ETR blocked",
    )
    production_gate.add_argument("--cloud-dir", default="runtime/cloud_pilot")
    production_gate.add_argument("--sanitized-manifest", default="runtime/sanitized_codebase_manifest.json")
    production_gate.add_argument("--pilot-gate-file", default="runtime/pilot_completion_gate.json")
    production_gate.add_argument("--green-gate-file", default="runtime/green_gate_tracker.md")
    production_gate.add_argument("--production-gate-file", default="runtime/production_readiness_gate.md")
    production_gate.add_argument("--owner-approval-file", default="runtime/cloud_pilot/owner_approval_status.json")
    production_gate.add_argument("--output", default="runtime/production_path_readiness_gate.md")
    production_gate.add_argument("--json-output", default="runtime/production_path_readiness_gate.json")
    production_gate.set_defaults(func=cmd_production_readiness_gate)

    ais_inbound_replay = sub.add_parser(
        "ais-inbound-replay-callbacks",
        help="Replay stored shadow AIS inbound callback payloads; defaults to dry-run",
    )
    ais_inbound_replay.add_argument("--callback-url", default=None)
    ais_inbound_replay.add_argument("--request-id", default=None)
    ais_inbound_replay.add_argument("--statuses", default="CAPTURED_NO_CALLBACK_URL,ERROR,HTTP_ERROR")
    ais_inbound_replay.add_argument("--limit", type=int, default=20)
    ais_inbound_replay.add_argument("--callbacks-output", default="runtime/ais_inbound_callbacks.jsonl")
    ais_inbound_replay.add_argument("--send", action="store_true", help="Actually POST callbacks; omitted means dry-run")
    ais_inbound_replay.set_defaults(func=cmd_ais_inbound_replay_callbacks)

    webex_audit = sub.add_parser("webex-audit", help="Audit parsed real Webex events from runtime DB")
    webex_audit.add_argument("--output", default="runtime/webex_real_audit.csv")
    webex_audit.add_argument("--samples-output", default="data/webex_shadow_samples_real.jsonl")
    webex_audit.add_argument("--max-text-chars", type=int, default=160)
    webex_audit.set_defaults(func=cmd_webex_audit)

    planned = sub.add_parser("planned-notify", help="Send shadow notifications from planned outage CSV")
    planned.add_argument("--source", default=None, help="Override planned outage CSV path")
    planned.add_argument("--min-lead-days", type=int, default=None, help="Minimum advance notice in days")
    planned.add_argument("--now", default=None, help="Local reference time, e.g. 2026-06-17T08:00:00")
    planned.add_argument("--limit", type=int, default=None, help="Stop after sending this many notifications")
    planned.set_defaults(func=cmd_planned_notify)

    setup = sub.add_parser("setup-env", help="Create .env from .env.example if needed")
    setup.add_argument("--example", default=".env.example")
    setup.add_argument("--output", default=".env")
    setup.add_argument("--force", action="store_true")
    setup.set_defaults(func=cmd_setup_env)

    validate = sub.add_parser("validate-env", help="Check Webex and shadow notification settings")
    validate.set_defaults(func=cmd_validate_env)

    sample_eval = sub.add_parser("sample-eval", help="Evaluate parser on JSONL Webex sample messages")
    sample_eval.add_argument("--samples", default="data/webex_shadow_samples.jsonl")
    sample_eval.set_defaults(func=cmd_sample_eval)

    shadow_report = sub.add_parser("shadow-report", help="Build prediction-vs-ETR report from runtime DB")
    shadow_report.add_argument("--output", default="runtime/shadow_evaluation.csv")
    shadow_report.add_argument("--truth-mapping", default="runtime/shadow_truth_mapping.csv")
    shadow_report.set_defaults(func=cmd_shadow_report)

    truth_template = sub.add_parser("shadow-truth-template", help="Create manual truth mapping CSV for Webex events")
    truth_template.add_argument("--output", default="runtime/shadow_truth_mapping.csv")
    truth_template.set_defaults(func=cmd_shadow_truth_template)

    replay = sub.add_parser("shadow-replay-notifications", help="Replay latest failed shadow notifications to mock webhook")
    replay.add_argument("--endpoint-url", default=None, help="Override AIS_MOCK_WEBHOOK_URL")
    replay.add_argument("--statuses", default=",".join(DEFAULT_REPLAY_STATUSES))
    replay.add_argument("--limit", type=int, default=None)
    replay.set_defaults(func=cmd_shadow_replay_notifications)

    truth_infer = sub.add_parser(
        "shadow-truth-infer-webex",
        help="Fill truth mapping from Webex Close/Normal status candidates",
    )
    truth_infer.add_argument("--output", default="runtime/shadow_truth_mapping.csv")
    truth_infer.add_argument("--candidates-output", default="runtime/shadow_truth_candidates.csv")
    truth_infer.add_argument("--overwrite", action="store_true", help="Overwrite existing actual_restoration_minutes")
    truth_infer.set_defaults(func=cmd_shadow_truth_infer_webex)

    ais_truth_template = sub.add_parser("ais-truth-template", help="Create an AIS outage/restore truth CSV template")
    ais_truth_template.add_argument("--output", default="runtime/ais_truth_template.csv")
    ais_truth_template.add_argument("--example", action="store_true", help="Include one placeholder example row")
    ais_truth_template.add_argument("--force", action="store_true", help="Overwrite an existing template")
    ais_truth_template.set_defaults(func=cmd_ais_truth_template)

    ais_truth_import = sub.add_parser("ais-truth-import", help="Import and validate AIS site outage/restore truth")
    ais_truth_import.add_argument("--source", required=True, help="AIS truth CSV/XLSX from AIS")
    ais_truth_import.add_argument("--output", default="runtime/ais_truth_latest.csv")
    ais_truth_import.add_argument("--rejects-output", default="runtime/ais_truth_rejects.csv")
    ais_truth_import.add_argument("--sheet", default=None, help="Excel sheet name or index; CSV ignores this")
    ais_truth_import.set_defaults(func=cmd_ais_truth_import)

    ais_add_field_import = sub.add_parser(
        "ais-add-field-truth-import",
        help="Import AIS AC MAIN FAIL add-field alarms as canonical truth candidates",
    )
    ais_add_field_import.add_argument("--source", default="AC_MAIN_FAIL_add_field.xlsx")
    ais_add_field_import.add_argument(
        "--meter-mapping",
        default=None,
        help="Optional mapping workbook; default searches Meter_ID_NE For PEA_*LatLong_R01 1.xlsx",
    )
    ais_add_field_import.add_argument("--output", default="runtime/ais_truth_latest_candidate.csv")
    ais_add_field_import.add_argument("--review-output", default="runtime/ais_truth_review_le_5min.csv")
    ais_add_field_import.add_argument("--rejects-output", default="runtime/ais_truth_rejects_add_field.csv")
    ais_add_field_import.add_argument("--audit-output", default="runtime/ais_truth_join_audit.csv")
    ais_add_field_import.add_argument("--report-output", default="runtime/analysis/ais_add_field_truth_import_report.md")
    ais_add_field_import.add_argument("--sheet", default="AC MAIN FAIL", help="Excel sheet name or index; CSV ignores this")
    ais_add_field_import.add_argument(
        "--date-order",
        choices=("mdy", "dmy"),
        default="mdy",
        help="Slash-date interpretation for text timestamps; AIS add-field export examples use mdy",
    )
    ais_add_field_import.set_defaults(func=cmd_ais_add_field_truth_import)

    ais_truth_match = sub.add_parser("ais-truth-match-shadow", help="Match AIS site truth to Webex shadow events")
    ais_truth_match.add_argument("--ais-truth", default="runtime/ais_truth_latest.csv")
    ais_truth_match.add_argument("--output", default="runtime/shadow_truth_mapping_ais.csv")
    ais_truth_match.add_argument("--audit", default="runtime/ais_truth_shadow_match_audit.csv")
    ais_truth_match.add_argument("--max-window-minutes", type=float, default=1440.0)
    ais_truth_match.add_argument("--ambiguity-delta-minutes", type=float, default=5.0)
    ais_truth_match.add_argument("--aggregation", choices=("max", "mean", "median"), default="max")
    ais_truth_match.add_argument("--include-review", action="store_true", help="Allow REVIEW_SHORT AIS rows into matching")
    ais_truth_match.add_argument("--allow-feeder", action="store_true", help="Allow feeder+time fallback to fill truth")
    ais_truth_match.add_argument("--overwrite", action="store_true", help="Overwrite existing mapped actuals with AIS truth")
    ais_truth_match.set_defaults(func=cmd_ais_truth_match_shadow)

    ais_remaining_match = sub.add_parser(
        "ais-remaining-truth-match-shadow",
        help="Match AIS active alarm intervals to Webex events and use remaining restore minutes as truth",
    )
    ais_remaining_match.add_argument("--ais-truth", default="runtime/ais_truth_latest_candidate.csv")
    ais_remaining_match.add_argument("--output", default="runtime/shadow_truth_mapping_ais_remaining.csv")
    ais_remaining_match.add_argument("--audit", default="runtime/ais_remaining_truth_match_audit.csv")
    ais_remaining_match.add_argument("--start-tolerance-minutes", type=float, default=5.0)
    ais_remaining_match.add_argument("--aggregation", choices=("max", "mean", "median"), default="max")
    ais_remaining_match.add_argument("--overwrite", action="store_true", help="Overwrite existing mapped actuals with AIS remaining truth")
    ais_remaining_match.set_defaults(func=cmd_ais_remaining_truth_match_shadow)

    ais_site_distance = sub.add_parser(
        "ais-site-distance-feature",
        help="Join nearest PEA office road distance onto AIS failed-site truth rows for model training",
    )
    ais_site_distance.add_argument("--source", default="runtime/ais_truth_latest_candidate.csv")
    ais_site_distance.add_argument("--distance", default="runtime/ais_site_nearest_pea_office_road_distance.csv")
    ais_site_distance.add_argument("--output", default="runtime/ais_truth_site_distance_features.csv")
    ais_site_distance.add_argument("--markdown-output", default="runtime/ais_truth_site_distance_features.md")
    ais_site_distance.add_argument("--site-id-column", default=None)
    ais_site_distance.set_defaults(func=cmd_ais_site_distance_feature)

    notification_time = sub.add_parser(
        "notification-time-readiness",
        help="Evaluate customer-facing ETR readiness using AIS active intervals at Webex notification time",
    )
    notification_time.add_argument("--comparison", default="runtime/shadow_model_comparison_ais_remaining.csv")
    notification_time.add_argument("--remaining-audit", default="runtime/ais_remaining_truth_match_audit.csv")
    notification_time.add_argument("--device-state", default="runtime/shadow_webex_device_state_diagnostic.csv")
    notification_time.add_argument("--lifecycle-audit", default="runtime/reportpo_lifecycle_join_audit.csv")
    notification_time.add_argument("--output", default="runtime/notification_time_readiness.csv")
    notification_time.add_argument("--segments-output", default="runtime/notification_time_error_segments.csv")
    notification_time.add_argument("--markdown-output", default="runtime/notification_time_readiness.md")
    notification_time.add_argument("--short-threshold-minutes", type=float, default=5.0)
    notification_time.add_argument("--high-error-threshold-minutes", type=float, default=60.0)
    notification_time.add_argument("--min-segment-events", type=int, default=3)
    notification_time.set_defaults(func=cmd_notification_time_readiness)

    ais_first_triage = sub.add_parser(
        "ais-first-error-triage",
        help="Classify customer-facing shadow ETR errors using AIS outage/restore truth first",
    )
    ais_first_triage.add_argument("--readiness", default="runtime/notification_time_readiness.csv")
    ais_first_triage.add_argument("--remaining-audit", default="runtime/ais_remaining_truth_match_audit.csv")
    ais_first_triage.add_argument("--ais-truth-audit", default="runtime/ais_truth_shadow_match_audit.csv")
    ais_first_triage.add_argument("--output", default="runtime/ais_first_error_triage.csv")
    ais_first_triage.add_argument("--markdown-output", default="runtime/ais_first_error_triage.md")
    ais_first_triage.add_argument("--segments-output", default="runtime/ais_first_error_segments.csv")
    ais_first_triage.add_argument("--high-error-minutes", type=float, default=60.0)
    ais_first_triage.add_argument("--late-webex-minutes", type=float, default=30.0)
    ais_first_triage.set_defaults(func=cmd_ais_first_error_triage)

    ais_momentary_long = sub.add_parser(
        "ais-momentary-long-diagnostics",
        help="Diagnose Webex momentary rows that still have sustained AIS active intervals",
    )
    ais_momentary_long.add_argument("--triage", default="runtime/ais_first_error_triage.csv")
    ais_momentary_long.add_argument("--readiness", default="runtime/notification_time_readiness.csv")
    ais_momentary_long.add_argument("--output", default="runtime/ais_momentary_long_diagnostics.csv")
    ais_momentary_long.add_argument("--markdown-output", default="runtime/ais_momentary_long_diagnostics.md")
    ais_momentary_long.add_argument("--segments-output", default="runtime/ais_momentary_long_segments.csv")
    ais_momentary_long.add_argument("--cluster-gap-minutes", type=float, default=180.0)
    ais_momentary_long.add_argument("--late-webex-minutes", type=float, default=30.0)
    ais_momentary_long.add_argument("--high-error-minutes", type=float, default=60.0)
    ais_momentary_long.set_defaults(func=cmd_ais_momentary_long_diagnostics)

    data_integrity = sub.add_parser(
        "data-integrity-audit",
        help="Audit AIS/PEA sources so KPI/reporting data cannot become customer-facing truth",
    )
    data_integrity.add_argument("--ais-truth", default="runtime/ais_truth_latest_candidate.csv")
    data_integrity.add_argument("--shadow-comparison", default="runtime/shadow_model_comparison_ais_remaining.csv")
    data_integrity.add_argument("--sfsd-evidence", default="runtime/sfsd_long_outage_evidence.csv")
    data_integrity.add_argument("--sfsd-decision", default="runtime/sfsd_gap_decision_pack.csv")
    data_integrity.add_argument("--reportpo-etr", default="runtime/reportpo_etr_latest.csv")
    data_integrity.add_argument("--reportpo-feature-audit", default="runtime/reportpo_feature_join_audit.csv")
    data_integrity.add_argument("--reportpo-lifecycle-audit", default="runtime/reportpo_lifecycle_join_audit.csv")
    data_integrity.add_argument("--output", default="runtime/data_integrity_audit.csv")
    data_integrity.add_argument("--policy-output", default="runtime/data_integrity_policy.md")
    data_integrity.add_argument("--governance-output", default="runtime/truth_governance_readiness.md")
    data_integrity.add_argument("--approval-template", default="runtime/sfsd_owner_approval_template.csv")
    data_integrity.add_argument("--request-pack", default="runtime/sfsd_source_request_pack.csv")
    data_integrity.set_defaults(func=cmd_data_integrity_audit)

    governance_status = sub.add_parser(
        "truth-governance-review-status",
        help="Validate SFSD owner approval/request files before using them as context evidence",
    )
    governance_status.add_argument("--approval-template", default="runtime/sfsd_owner_approval_template.csv")
    governance_status.add_argument("--request-pack", default="runtime/sfsd_source_request_pack.csv")
    governance_status.add_argument("--output", default="runtime/truth_governance_review_status.csv")
    governance_status.add_argument("--markdown-output", default="runtime/truth_governance_review_status.md")
    governance_status.set_defaults(func=cmd_truth_governance_review_status)

    ais_only = sub.add_parser(
        "ais-only-readiness",
        help="Separate AIS truth metric rows from WebEx trigger-only and PEA quarantine/context pools",
    )
    ais_only.add_argument("--shadow-comparison", default="runtime/shadow_model_comparison_ais_remaining.csv")
    ais_only.add_argument("--governance-status", default="runtime/truth_governance_review_status.csv")
    ais_only.add_argument("--reportpo-feature-audit", default="runtime/reportpo_feature_join_audit.csv")
    ais_only.add_argument("--reportpo-lifecycle-audit", default="runtime/reportpo_lifecycle_join_audit.csv")
    ais_only.add_argument("--sfsd-evidence", default="runtime/sfsd_long_outage_evidence.csv")
    ais_only.add_argument("--sfsd-decision", default="runtime/sfsd_gap_decision_pack.csv")
    ais_only.add_argument("--output", default="runtime/ais_only_readiness.csv")
    ais_only.add_argument("--markdown-output", default="runtime/ais_only_readiness.md")
    ais_only.add_argument("--quarantine-output", default="runtime/pea_quarantine_audit.csv")
    ais_only.add_argument("--min-duration-minutes", type=float, default=5.0)
    ais_only.set_defaults(func=cmd_ais_only_readiness)

    ais_only_error = sub.add_parser(
        "ais-only-error-segmentation",
        help="Segment AIS-only sustained truth errors and create a high-error challenger queue",
    )
    ais_only_error.add_argument("--ais-only-readiness", default="runtime/ais_only_readiness.csv")
    ais_only_error.add_argument("--notification-time", default="runtime/notification_time_readiness.csv")
    ais_only_error.add_argument("--segments-output", default="runtime/ais_only_error_segments.csv")
    ais_only_error.add_argument("--queue-output", default="runtime/ais_only_high_error_queue.csv")
    ais_only_error.add_argument("--markdown-output", default="runtime/ais_only_error_segmentation.md")
    ais_only_error.add_argument("--high-error-minutes", type=float, default=60.0)
    ais_only_error.set_defaults(func=cmd_ais_only_error_segmentation)

    ais_only_remaining = sub.add_parser(
        "ais-only-remaining-time-challenger",
        help="Test an AIS-only remaining-time challenger for long-outage underprediction",
    )
    ais_only_remaining.add_argument("--ais-only-readiness", default="runtime/ais_only_readiness.csv")
    ais_only_remaining.add_argument("--notification-time", default="runtime/notification_time_readiness.csv")
    ais_only_remaining.add_argument("--ais-truth", default="runtime/ais_truth_latest_candidate.csv")
    ais_only_remaining.add_argument("--active-state", default="runtime/shadow_active_state_remaining_challenger.csv")
    ais_only_remaining.add_argument("--output", default="runtime/ais_only_remaining_time_challenger.csv")
    ais_only_remaining.add_argument("--markdown-output", default="runtime/ais_only_remaining_time_challenger.md")
    ais_only_remaining.add_argument("--segments-output", default="runtime/ais_only_remaining_time_segments.csv")
    ais_only_remaining.add_argument("--min-affected-history-rows", type=int, default=3)
    ais_only_remaining.add_argument("--min-segment-rows", type=int, default=5)
    ais_only_remaining.add_argument("--tail-uplift-threshold-minutes", type=float, default=180.0)
    ais_only_remaining.add_argument("--high-error-minutes", type=float, default=60.0)
    ais_only_remaining.set_defaults(func=cmd_ais_only_remaining_time_challenger)

    ais_only_lifecycle = sub.add_parser(
        "ais-only-lifecycle-challenger",
        help="Validate approved lifecycle/cause review rows and test an AIS-only lifecycle/cause challenger",
    )
    ais_only_lifecycle.add_argument("--ais-only-readiness", default="runtime/ais_only_readiness.csv")
    ais_only_lifecycle.add_argument("--remaining-time", default="runtime/ais_only_remaining_time_challenger.csv")
    ais_only_lifecycle.add_argument("--lifecycle-review", default="runtime/ops_lifecycle_review_top_misses.csv")
    ais_only_lifecycle.add_argument("--output", default="runtime/ais_only_lifecycle_challenger.csv")
    ais_only_lifecycle.add_argument("--markdown-output", default="runtime/ais_only_lifecycle_challenger.md")
    ais_only_lifecycle.add_argument("--feature-audit-output", default="runtime/ais_only_lifecycle_feature_audit.csv")
    ais_only_lifecycle.add_argument("--valid-output", default="runtime/ops_lifecycle_review_validated.csv")
    ais_only_lifecycle.add_argument("--rejects-output", default="runtime/ops_lifecycle_review_rejects.csv")
    ais_only_lifecycle.add_argument("--segments-output", default="runtime/ais_only_lifecycle_segments.csv")
    ais_only_lifecycle.add_argument("--min-lifecycle-prior-rows", type=int, default=2)
    ais_only_lifecycle.add_argument("--high-error-minutes", type=float, default=60.0)
    ais_only_lifecycle.add_argument("--first-restore-tolerance-minutes", type=float, default=120.0)
    ais_only_lifecycle.set_defaults(func=cmd_ais_only_lifecycle_challenger)

    shadow_send = sub.add_parser(
        "shadow-send-eligibility",
        help="Gate shadow ETR sends into green, amber, red, or monitor-only confidence lanes",
    )
    shadow_send.add_argument("--ais-only-readiness", default="runtime/ais_only_readiness.csv")
    shadow_send.add_argument("--notification-time", default="runtime/notification_time_readiness.csv")
    shadow_send.add_argument("--lifecycle-challenger", default="runtime/ais_only_lifecycle_challenger.csv")
    shadow_send.add_argument("--remaining-time", default="runtime/ais_only_remaining_time_challenger.csv")
    shadow_send.add_argument("--output", default="runtime/shadow_send_eligibility.csv")
    shadow_send.add_argument("--markdown-output", default="runtime/shadow_send_eligibility.md")
    shadow_send.add_argument("--segments-output", default="runtime/shadow_send_eligibility_segments.csv")
    shadow_send.add_argument("--production-gate-output", default="runtime/production_readiness_gate.md")
    shadow_send.add_argument("--min-match-confidence", type=float, default=0.8)
    shadow_send.add_argument("--max-auto-interval-width-minutes", type=float, default=120.0)
    shadow_send.add_argument("--max-auto-q90-minutes", type=float, default=180.0)
    shadow_send.add_argument("--high-error-minutes", type=float, default=60.0)
    shadow_send.set_defaults(func=cmd_shadow_send_eligibility)

    green_report = sub.add_parser(
        "green-eligibility-report",
        help="Build cloud-pilot green/amber/red eligibility and green-gate reports",
    )
    green_report.add_argument("--ais-only-readiness", default="runtime/ais_only_readiness.csv")
    green_report.add_argument("--notification-time", default="runtime/notification_time_readiness.csv")
    green_report.add_argument("--lifecycle-challenger", default="runtime/ais_only_lifecycle_challenger.csv")
    green_report.add_argument("--remaining-time", default="runtime/ais_only_remaining_time_challenger.csv")
    green_report.add_argument("--threshold-calibration", default="runtime/eligibility_threshold_calibration.csv")
    green_report.add_argument("--output", default="runtime/cloud_pilot/green_eligibility_report.csv")
    green_report.add_argument("--markdown-output", default="runtime/cloud_pilot/green_eligibility_report.md")
    green_report.add_argument("--segments-output", default="runtime/cloud_pilot/green_eligibility_segments.csv")
    green_report.add_argument("--gate-output", default="runtime/cloud_pilot/green_gate_tracker.md")
    green_report.add_argument("--gate-csv-output", default="runtime/cloud_pilot/green_gate_tracker.csv")
    green_report.add_argument("--json-output", default="runtime/cloud_pilot/green_eligibility_report.json")
    green_report.add_argument("--min-green-rows", type=int, default=30)
    green_report.set_defaults(func=cmd_green_eligibility_report)

    production_packet = sub.add_parser(
        "production-gate-packet",
        help="Build owner-ready production gate packet with green gaps and evidence asks",
    )
    production_packet.add_argument("--eligibility-csv", default="runtime/cloud_pilot/green_eligibility_report.csv")
    production_packet.add_argument("--green-gate-json", default="runtime/cloud_pilot/green_eligibility_report.json")
    production_packet.add_argument("--real-hit-status-json", default="runtime/production_cloud_real_hit_status.json")
    production_packet.add_argument("--readiness-gate-json", default="runtime/production_path_readiness_gate.json")
    production_packet.add_argument("--owner-approval-template", default="runtime/cloud_pilot/owner_approval_status.template.json")
    production_packet.add_argument("--output-csv", default="runtime/cloud_pilot/production_gate_gap_actions.csv")
    production_packet.add_argument("--markdown-output", default="runtime/cloud_pilot/production_gate_owner_packet.md")
    production_packet.add_argument("--json-output", default="runtime/cloud_pilot/production_gate_owner_packet.json")
    production_packet.add_argument("--min-green-rows", type=int, default=30)
    production_packet.add_argument("--top-blockers", type=int, default=12)
    production_packet.set_defaults(func=cmd_production_gate_packet)

    approval_pack = sub.add_parser(
        "production-approval-evidence-pack",
        help="Build AIS test-window, ops blocker, and top owner queues for production approval evidence",
    )
    approval_pack.add_argument("--gap-actions-csv", default="runtime/cloud_pilot/production_gate_gap_actions.csv")
    approval_pack.add_argument("--owner-packet-json", default="runtime/cloud_pilot/production_gate_owner_packet.json")
    approval_pack.add_argument("--real-hit-status-json", default="runtime/production_cloud_real_hit_status.json")
    approval_pack.add_argument("--readiness-gate-json", default="runtime/production_path_readiness_gate.json")
    approval_pack.add_argument("--ais-truth-queue-output", default="runtime/cloud_pilot/green_owner_top30_ais_truth_queue.csv")
    approval_pack.add_argument("--topology-queue-output", default="runtime/cloud_pilot/green_owner_top30_topology_queue.csv")
    approval_pack.add_argument("--ops-report-output", default="runtime/cloud_pilot/ops_controls_blocker_report.md")
    approval_pack.add_argument("--ais-test-window-output", default="runtime/cloud_pilot/ais_real_cloud_test_window_request.md")
    approval_pack.add_argument("--markdown-output", default="runtime/cloud_pilot/production_approval_evidence_next_actions.md")
    approval_pack.add_argument("--json-output", default="runtime/cloud_pilot/production_approval_evidence_next_actions.json")
    approval_pack.add_argument("--top-n", type=int, default=30)
    approval_pack.set_defaults(func=cmd_production_approval_evidence_pack)

    mvp_daily = sub.add_parser(
        "mvp-daily-qa",
        help="Build one-command MVP QA, recording pack, and current approval evidence outputs",
    )
    mvp_daily.add_argument("--gap-actions-csv", default="runtime/cloud_pilot/production_gate_gap_actions.csv")
    mvp_daily.add_argument("--owner-packet-json", default="runtime/cloud_pilot/production_gate_owner_packet.json")
    mvp_daily.add_argument("--real-hit-status-json", default="runtime/production_cloud_real_hit_status.json")
    mvp_daily.add_argument("--readiness-gate-json", default="runtime/production_path_readiness_gate.json")
    mvp_daily.add_argument("--privacy-scan-json", default="runtime/production_cloud_privacy_red_team_scan_report.json")
    mvp_daily.add_argument("--ais-truth-queue-output", default="runtime/cloud_pilot/green_owner_top30_ais_truth_queue.csv")
    mvp_daily.add_argument("--topology-queue-output", default="runtime/cloud_pilot/green_owner_top30_topology_queue.csv")
    mvp_daily.add_argument("--ops-report-output", default="runtime/cloud_pilot/ops_controls_blocker_report.md")
    mvp_daily.add_argument("--ais-test-window-output", default="runtime/cloud_pilot/ais_real_cloud_test_window_request.md")
    mvp_daily.add_argument("--approval-markdown-output", default="runtime/cloud_pilot/production_approval_evidence_next_actions.md")
    mvp_daily.add_argument("--approval-json-output", default="runtime/cloud_pilot/production_approval_evidence_next_actions.json")
    mvp_daily.add_argument("--markdown-output", default="runtime/cloud_pilot/mvp_daily_qa_report.md")
    mvp_daily.add_argument("--json-output", default="runtime/cloud_pilot/mvp_daily_qa_report.json")
    mvp_daily.add_argument("--recording-pack-output", default="runtime/cloud_pilot/mvp_demo_recording_pack.md")
    mvp_daily.add_argument("--top-n", type=int, default=30)
    mvp_daily.set_defaults(func=cmd_mvp_daily_qa)

    cloud_worker = sub.add_parser(
        "cloud-worker-shadow-loop",
        help="Review pending cloud Postgres requests and optionally append safe shadow worker rows",
    )
    cloud_worker.add_argument("--database-url", default=None, help="PostgreSQL URL; omit with --input-json for local dry-run")
    cloud_worker.add_argument("--input-json", default=None, help="Operator payload JSON fixture for dry-run without Postgres")
    cloud_worker.add_argument("--output-json", default="runtime/cloud_pilot/cloud_worker_shadow_loop_report.json")
    cloud_worker.add_argument("--markdown-output", default="runtime/cloud_pilot/cloud_worker_shadow_loop_report.md")
    cloud_worker.add_argument("--limit", type=int, default=50)
    cloud_worker.add_argument("--apply", action="store_true", help="Write append-only evidence/ETR/audit rows; default is dry-run")
    cloud_worker.set_defaults(func=cmd_cloud_worker_shadow_loop)

    truth_pairing = sub.add_parser(
        "ais-truth-interval-pairing",
        help="Pair AIS OUTAGE/RESTORE truth observations into derived shadow intervals",
    )
    truth_pairing.add_argument("--database-url", default=None, help="PostgreSQL URL; omit with --input-json for local dry-run")
    truth_pairing.add_argument("--input-json", default=None, help="Truth observation JSON fixture for dry-run without Postgres")
    truth_pairing.add_argument("--output-json", default="runtime/cloud_pilot/ais_truth_interval_pairing_report.json")
    truth_pairing.add_argument("--markdown-output", default="runtime/cloud_pilot/ais_truth_interval_pairing_report.md")
    truth_pairing.add_argument("--limit", type=int, default=500)
    truth_pairing.add_argument("--apply", action="store_true", help="Upsert derived interval rows; default is dry-run")
    truth_pairing.set_defaults(func=cmd_ais_truth_interval_pairing)

    forward_template = sub.add_parser(
        "forward-capture-template",
        help="Create a forward operational context intake template from amber/red shadow events",
    )
    forward_template.add_argument("--eligibility", default="runtime/shadow_send_eligibility.csv")
    forward_template.add_argument("--output", default="runtime/forward_capture_template.csv")
    forward_template.add_argument("--markdown-output", default="runtime/forward_capture_template.md")
    forward_template.add_argument("--top-n", type=int, default=50)
    forward_template.set_defaults(func=cmd_forward_capture_template)

    forward_import = sub.add_parser(
        "forward-capture-import",
        help="Validate approved forward-capture lifecycle/cause rows before feature use",
    )
    forward_import.add_argument("--input", default="runtime/forward_capture_template.csv")
    forward_import.add_argument("--ais-only-readiness", default="runtime/ais_only_readiness.csv")
    forward_import.add_argument("--output-valid", default="runtime/forward_capture_validated.csv")
    forward_import.add_argument("--rejects", default="runtime/forward_capture_rejects.csv")
    forward_import.add_argument("--markdown-output", default="runtime/forward_capture_import.md")
    forward_import.add_argument("--first-restore-tolerance-minutes", type=float, default=120.0)
    forward_import.set_defaults(func=cmd_forward_capture_import)

    two_stage = sub.add_parser(
        "two-stage-shadow-challenger",
        help="Classify normal/long/uncertain shadow events and expose ETR only for green normal rows",
    )
    two_stage.add_argument("--eligibility", default="runtime/shadow_send_eligibility.csv")
    two_stage.add_argument("--lifecycle-challenger", default="runtime/ais_only_lifecycle_challenger.csv")
    two_stage.add_argument("--forward-capture-validated", default="runtime/forward_capture_validated.csv")
    two_stage.add_argument("--output", default="runtime/two_stage_shadow_challenger.csv")
    two_stage.add_argument("--markdown-output", default="runtime/two_stage_shadow_challenger.md")
    two_stage.add_argument("--segments-output", default="runtime/two_stage_shadow_segments.csv")
    two_stage.add_argument("--high-error-minutes", type=float, default=60.0)
    two_stage.set_defaults(func=cmd_two_stage_shadow_challenger)

    evidence_collector = sub.add_parser(
        "autonomous-evidence-collector",
        help="Collect WebEx/AIS/PowerBI context evidence into pending forward-capture candidates",
    )
    evidence_collector.add_argument("--eligibility", default="runtime/shadow_send_eligibility.csv")
    evidence_collector.add_argument("--reportpo-feature-audit", default="runtime/reportpo_feature_join_audit.csv")
    evidence_collector.add_argument("--reportpo-lifecycle-audit", default="runtime/reportpo_lifecycle_join_audit.csv")
    evidence_collector.add_argument("--sfsd-evidence", default="runtime/sfsd_long_outage_evidence.csv")
    evidence_collector.add_argument("--output", default="runtime/autonomous_evidence_collector.csv")
    evidence_collector.add_argument("--markdown-output", default="runtime/autonomous_evidence_collector.md")
    evidence_collector.add_argument("--autofill-output", default="runtime/forward_capture_autofill_candidates.csv")
    evidence_collector.add_argument("--approved-score-threshold", type=float, default=80.0)
    evidence_collector.add_argument("--partial-score-threshold", type=float, default=45.0)
    evidence_collector.add_argument("--long-conflict-minutes", type=float, default=60.0)
    evidence_collector.set_defaults(func=cmd_autonomous_evidence_collector)

    daily_intake = sub.add_parser(
        "daily-intake-workflow",
        help="Create the non-destructive daily AIS truth intake folder and Thai README",
    )
    daily_intake.add_argument("--intake-dir", default="runtime/daily_ais_intake")
    daily_intake.add_argument("--readme-output", default=None)
    daily_intake.set_defaults(func=cmd_daily_intake_workflow)

    daily_inbox = sub.add_parser(
        "daily-inbox-status",
        help="List pending and processed AIS files in the daily intake inbox",
    )
    daily_inbox.add_argument("--intake-dir", default="runtime/daily_ais_intake")
    daily_inbox.add_argument("--output", default="runtime/daily_ais_intake/inbox_status.csv")
    daily_inbox.add_argument("--manifest", default="runtime/daily_ais_intake/source_manifest.csv")
    daily_inbox.set_defaults(func=cmd_daily_inbox_status)

    evidence_review = sub.add_parser(
        "evidence-review-pack",
        help="Create approved-candidate and conflict review files from autonomous evidence output",
    )
    evidence_review.add_argument("--evidence", default="runtime/autonomous_evidence_collector.csv")
    evidence_review.add_argument("--approved-output", default="runtime/approved_context_candidates_review.csv")
    evidence_review.add_argument("--approved-markdown", default="runtime/approved_context_candidates_review.md")
    evidence_review.add_argument("--conflicts-output", default="runtime/rejected_context_conflicts.csv")
    evidence_review.add_argument("--conflicts-markdown", default="runtime/rejected_context_conflicts.md")
    evidence_review.set_defaults(func=cmd_evidence_review_pack)

    executive_pack = sub.add_parser(
        "executive-status-pack",
        help="Build a concise executive Markdown status pack for the shadow pilot",
    )
    executive_pack.add_argument("--eligibility", default="runtime/shadow_send_eligibility.csv")
    executive_pack.add_argument("--evidence", default="runtime/autonomous_evidence_collector.csv")
    executive_pack.add_argument("--two-stage", default="runtime/two_stage_shadow_challenger.csv")
    executive_pack.add_argument("--output", default="runtime/executive_shadow_status_pack.md")
    executive_pack.set_defaults(func=cmd_executive_status_pack)

    conflict_deep_dive = sub.add_parser(
        "context-conflict-deep-dive",
        help="Build a deep-dive report for AIS truth vs PEA/PowerBI context conflicts",
    )
    conflict_deep_dive.add_argument("--evidence", default="runtime/autonomous_evidence_collector.csv")
    conflict_deep_dive.add_argument("--output", default="runtime/context_conflict_deep_dive.csv")
    conflict_deep_dive.add_argument("--markdown-output", default="runtime/context_conflict_deep_dive.md")
    conflict_deep_dive.set_defaults(func=cmd_context_conflict_deep_dive)

    approved_summary = sub.add_parser(
        "approved-context-summary",
        help="Summarize strong PowerBI/SFSD context candidates for human review",
    )
    approved_summary.add_argument("--evidence", default="runtime/autonomous_evidence_collector.csv")
    approved_summary.add_argument("--output", default="runtime/approved_context_candidate_summary.csv")
    approved_summary.add_argument("--markdown-output", default="runtime/approved_context_candidate_summary.md")
    approved_summary.set_defaults(func=cmd_approved_context_summary)

    daily_diff = sub.add_parser(
        "daily-shadow-diff",
        help="Compare the current shadow status with the previous recorded snapshot",
    )
    daily_diff.add_argument("--eligibility", default="runtime/shadow_send_eligibility.csv")
    daily_diff.add_argument("--evidence", default="runtime/autonomous_evidence_collector.csv")
    daily_diff.add_argument("--inbox-status", default="runtime/daily_ais_intake/inbox_status.csv")
    daily_diff.add_argument("--history", default="runtime/daily_shadow_status_history.csv")
    daily_diff.add_argument("--output", default="runtime/daily_shadow_diff.md")
    daily_diff.add_argument("--no-append", action="store_true", help="Render diff without appending a new snapshot")
    daily_diff.set_defaults(func=cmd_daily_shadow_diff)

    synthetic_smoke = sub.add_parser(
        "daily-synthetic-smoke-test",
        help="Create a synthetic AIS daily file and verify inbox manifest de-duplication",
    )
    synthetic_smoke.add_argument("--output-dir", default="runtime/synthetic_daily_smoke")
    synthetic_smoke.add_argument("--markdown-output", default="runtime/synthetic_daily_smoke/synthetic_daily_smoke_test.md")
    synthetic_smoke.set_defaults(func=cmd_daily_synthetic_smoke_test)

    operator_checklist = sub.add_parser(
        "operator-checklist",
        help="Write the shadow operator review checklist",
    )
    operator_checklist.add_argument("--output", default="runtime/operator_shadow_review_checklist.md")
    operator_checklist.set_defaults(func=cmd_operator_checklist)

    green_review = sub.add_parser(
        "green-candidate-error-review",
        help="Review current green auto-candidate misses and interval coverage",
    )
    green_review.add_argument("--eligibility", default="runtime/shadow_send_eligibility.csv")
    green_review.add_argument("--output", default="runtime/green_candidate_error_review.csv")
    green_review.add_argument("--markdown-output", default="runtime/green_candidate_error_review.md")
    green_review.set_defaults(func=cmd_green_candidate_error_review)

    threshold_calibration = sub.add_parser(
        "eligibility-threshold-calibration",
        help="Backtest stricter shadow send eligibility thresholds without changing model artifacts",
    )
    threshold_calibration.add_argument("--eligibility", default="runtime/shadow_send_eligibility.csv")
    threshold_calibration.add_argument("--output", default="runtime/eligibility_threshold_calibration.csv")
    threshold_calibration.add_argument("--markdown-output", default="runtime/eligibility_threshold_calibration.md")
    threshold_calibration.add_argument("--min-rows", type=int, default=5)
    threshold_calibration.set_defaults(func=cmd_eligibility_threshold_calibration)

    context_priority = sub.add_parser(
        "context-review-priority",
        help="Prioritize approved context candidates for owner/operator review",
    )
    context_priority.add_argument("--evidence", default="runtime/autonomous_evidence_collector.csv")
    context_priority.add_argument("--output", default="runtime/context_review_priority.csv")
    context_priority.add_argument("--markdown-output", default="runtime/context_review_priority.md")
    context_priority.add_argument("--top-n", type=int, default=50)
    context_priority.set_defaults(func=cmd_context_review_priority)

    webex_monitor = sub.add_parser(
        "webex-only-monitoring",
        help="Summarize WebEx triggers that do not yet have AIS outage/restore truth",
    )
    webex_monitor.add_argument("--eligibility", default="runtime/shadow_send_eligibility.csv")
    webex_monitor.add_argument("--output", default="runtime/webex_only_monitoring.csv")
    webex_monitor.add_argument("--markdown-output", default="runtime/webex_only_monitoring.md")
    webex_monitor.add_argument("--top-n", type=int, default=100)
    webex_monitor.set_defaults(func=cmd_webex_only_monitoring)

    console_mock = sub.add_parser(
        "operator-console-mock",
        help="Build a static operator console mock from current shadow outputs",
    )
    console_mock.add_argument("--eligibility", default="runtime/shadow_send_eligibility.csv")
    console_mock.add_argument("--evidence", default="runtime/autonomous_evidence_collector.csv")
    console_mock.add_argument("--output", default="runtime/operator_console_mock.html")
    console_mock.add_argument("--markdown-output", default="runtime/operator_console_mock.md")
    console_mock.add_argument("--max-rows", type=int, default=12)
    console_mock.set_defaults(func=cmd_operator_console_mock)

    green_gate = sub.add_parser(
        "green-gate-tracker",
        help="Track green subset sample size and metric gate readiness",
    )
    green_gate.add_argument("--eligibility", default="runtime/shadow_send_eligibility.csv")
    green_gate.add_argument("--threshold-calibration", default="runtime/eligibility_threshold_calibration.csv")
    green_gate.add_argument("--output", default="runtime/green_gate_tracker.csv")
    green_gate.add_argument("--markdown-output", default="runtime/green_gate_tracker.md")
    green_gate.add_argument("--min-green-rows", type=int, default=30)
    green_gate.set_defaults(func=cmd_green_gate_tracker)

    ais_daily_qa = sub.add_parser(
        "ais-daily-file-qa",
        help="QA latest AIS daily outage/restore truth candidate, review, and reject files",
    )
    ais_daily_qa.add_argument("--candidates", default="runtime/ais_truth_latest_candidate.csv")
    ais_daily_qa.add_argument("--review", default="runtime/ais_truth_review_le_5min.csv")
    ais_daily_qa.add_argument("--rejects", default="runtime/ais_truth_rejects_add_field.csv")
    ais_daily_qa.add_argument("--join-audit", default="runtime/ais_truth_join_audit.csv")
    ais_daily_qa.add_argument("--output", default="runtime/ais_daily_file_qa.csv")
    ais_daily_qa.add_argument("--markdown-output", default="runtime/ais_daily_file_qa.md")
    ais_daily_qa.set_defaults(func=cmd_ais_daily_file_qa)

    mapping_repair = sub.add_parser(
        "mapping-repair-queue",
        help="Build public/private AIS site mapping repair queues from daily truth QA",
    )
    mapping_repair.add_argument("--join-audit", default="runtime/ais_truth_join_audit.csv")
    mapping_repair.add_argument("--candidates", default="runtime/ais_truth_latest_candidate.csv")
    mapping_repair.add_argument("--rejects", default="runtime/ais_truth_rejects_add_field.csv")
    mapping_repair.add_argument("--output", default="runtime/ais_mapping_repair_queue.csv")
    mapping_repair.add_argument("--private-output", default="runtime/private/ais_mapping_repair_queue_private.csv")
    mapping_repair.add_argument("--markdown-output", default="runtime/ais_mapping_repair_queue.md")
    mapping_repair.add_argument("--top-n", type=int, default=100)
    mapping_repair.set_defaults(func=cmd_mapping_repair_queue)

    duplicate_flapping = sub.add_parser(
        "duplicate-flapping-audit",
        help="Audit duplicate and fail-clear-fail AIS truth intervals without merging them",
    )
    duplicate_flapping.add_argument("--candidates", default="runtime/ais_truth_latest_candidate.csv")
    duplicate_flapping.add_argument("--review", default="runtime/ais_truth_review_le_5min.csv")
    duplicate_flapping.add_argument("--output", default="runtime/duplicate_flapping_audit.csv")
    duplicate_flapping.add_argument("--markdown-output", default="runtime/duplicate_flapping_audit.md")
    duplicate_flapping.add_argument("--flap-window-minutes", type=float, default=5.0)
    duplicate_flapping.add_argument("--top-n", type=int, default=100)
    duplicate_flapping.set_defaults(func=cmd_duplicate_flapping_audit)

    growth_plan = sub.add_parser(
        "green-candidate-growth-plan",
        help="Prioritize work needed to grow the safe green auto-candidate subset",
    )
    growth_plan.add_argument("--eligibility", default="runtime/shadow_send_eligibility.csv")
    growth_plan.add_argument("--green-gate-tracker", default="runtime/green_gate_tracker.csv")
    growth_plan.add_argument("--webex-monitoring", default="runtime/webex_only_monitoring.csv")
    growth_plan.add_argument("--mapping-repair-queue", default="runtime/ais_mapping_repair_queue.csv")
    growth_plan.add_argument("--context-priority", default="runtime/context_review_priority.csv")
    growth_plan.add_argument("--output", default="runtime/green_candidate_growth_plan.csv")
    growth_plan.add_argument("--markdown-output", default="runtime/green_candidate_growth_plan.md")
    growth_plan.add_argument("--min-green-rows", type=int, default=30)
    growth_plan.set_defaults(func=cmd_green_candidate_growth_plan)

    status_payloads = sub.add_parser(
        "status-only-payload-templates",
        help="Build shadow status-only payload examples for amber and monitor-only rows",
    )
    status_payloads.add_argument("--eligibility", default="runtime/shadow_send_eligibility.csv")
    status_payloads.add_argument("--output", default="runtime/status_only_payload_templates.jsonl")
    status_payloads.add_argument("--markdown-output", default="runtime/status_only_payload_templates.md")
    status_payloads.add_argument("--max-rows", type=int, default=50)
    status_payloads.set_defaults(func=cmd_status_only_payload_templates)

    payload_contract = sub.add_parser(
        "shadow-status-payload-contract",
        help="Write the status-only and green/amber/red shadow payload contract",
    )
    payload_contract.add_argument("--payloads", default="runtime/status_only_payload_templates.jsonl")
    payload_contract.add_argument("--eligibility", default="runtime/shadow_send_eligibility.csv")
    payload_contract.add_argument("--output", default="runtime/shadow_status_payload_contract.md")
    payload_contract.add_argument("--sample-count", type=int, default=2)
    payload_contract.set_defaults(func=cmd_shadow_status_payload_contract)

    executive_one_pager = sub.add_parser(
        "executive-one-pager",
        help="Build a concise executive one-pager from the latest shadow evidence outputs",
    )
    executive_one_pager.add_argument("--eligibility", default="runtime/shadow_send_eligibility.csv")
    executive_one_pager.add_argument("--green-gate-tracker", default="runtime/green_gate_tracker.csv")
    executive_one_pager.add_argument("--ais-daily-qa", default="runtime/ais_daily_file_qa.csv")
    executive_one_pager.add_argument("--growth-plan", default="runtime/green_candidate_growth_plan.csv")
    executive_one_pager.add_argument("--output", default="runtime/executive_one_pager.md")
    executive_one_pager.set_defaults(func=cmd_executive_one_pager)

    mapping_request = sub.add_parser(
        "mapping-repair-request-pack",
        help="Build public/private owner request files for AIS mapping repair",
    )
    mapping_request.add_argument("--public-queue", default="runtime/ais_mapping_repair_queue.csv")
    mapping_request.add_argument("--private-queue", default="runtime/private/ais_mapping_repair_queue_private.csv")
    mapping_request.add_argument("--output", default="runtime/ais_mapping_repair_request.csv")
    mapping_request.add_argument("--private-output", default="runtime/private/ais_mapping_repair_request_owner.csv")
    mapping_request.add_argument("--markdown-output", default="runtime/ais_mapping_repair_request_pack.md")
    mapping_request.add_argument("--top-n", type=int, default=25)
    mapping_request.set_defaults(func=cmd_mapping_repair_request_pack)

    webex_truth_request = sub.add_parser(
        "webex-truth-request-pack",
        help="Build an AIS truth request queue from high-priority WebEx monitor rows",
    )
    webex_truth_request.add_argument("--webex-monitoring", default="runtime/webex_only_monitoring.csv")
    webex_truth_request.add_argument("--output", default="runtime/webex_ais_truth_request.csv")
    webex_truth_request.add_argument("--markdown-output", default="runtime/webex_ais_truth_request_pack.md")
    webex_truth_request.add_argument("--top-n", type=int, default=100)
    webex_truth_request.set_defaults(func=cmd_webex_truth_request_pack)

    flapping_policy = sub.add_parser(
        "flapping-policy-draft",
        help="Build a duplicate/flapping review policy draft from AIS alarm audit output",
    )
    flapping_policy.add_argument("--duplicate-flapping", default="runtime/duplicate_flapping_audit.csv")
    flapping_policy.add_argument("--output", default="runtime/duplicate_flapping_policy.csv")
    flapping_policy.add_argument("--markdown-output", default="runtime/duplicate_flapping_policy.md")
    flapping_policy.add_argument("--phase2-windows", type=int, nargs="+", default=[5, 15, 30])
    flapping_policy.set_defaults(func=cmd_flapping_policy_draft)

    owner_handoff = sub.add_parser(
        "owner-handoff-pack",
        help="Build a single owner handoff index for the current AIS ETR shadow evidence pack",
    )
    owner_handoff.add_argument("--executive-one-pager", default="runtime/executive_one_pager.md")
    owner_handoff.add_argument("--growth-plan", default="runtime/green_candidate_growth_plan.md")
    owner_handoff.add_argument("--mapping-request", default="runtime/ais_mapping_repair_request_pack.md")
    owner_handoff.add_argument("--webex-truth-request", default="runtime/webex_ais_truth_request_pack.md")
    owner_handoff.add_argument("--flapping-policy", default="runtime/duplicate_flapping_policy.md")
    owner_handoff.add_argument("--output", default="runtime/owner_handoff_pack.md")
    owner_handoff.set_defaults(func=cmd_owner_handoff_pack)

    owner_messages = sub.add_parser(
        "owner-message-drafts",
        help="Build Thai owner message drafts for AIS mapping, AIS truth, and operations/data owners",
    )
    owner_messages.add_argument("--owner-handoff", default="runtime/owner_handoff_pack.md")
    owner_messages.add_argument("--mapping-request", default="runtime/ais_mapping_repair_request_pack.md")
    owner_messages.add_argument("--webex-truth-request", default="runtime/webex_ais_truth_request_pack.md")
    owner_messages.add_argument("--flapping-policy", default="runtime/duplicate_flapping_policy.md")
    owner_messages.add_argument("--output", default="runtime/owner_message_drafts_th.md")
    owner_messages.set_defaults(func=cmd_owner_message_drafts)

    owner_tracker = sub.add_parser(
        "owner-followup-tracker",
        help="Build a public owner follow-up tracker CSV/Markdown from current request packs",
    )
    owner_tracker.add_argument("--mapping-request", default="runtime/ais_mapping_repair_request.csv")
    owner_tracker.add_argument("--webex-truth-request", default="runtime/webex_ais_truth_request.csv")
    owner_tracker.add_argument("--flapping-policy", default="runtime/duplicate_flapping_policy.csv")
    owner_tracker.add_argument("--output", default="runtime/owner_followup_tracker.csv")
    owner_tracker.add_argument("--markdown-output", default="runtime/owner_followup_tracker.md")
    owner_tracker.set_defaults(func=cmd_owner_followup_tracker)

    owner_templates = sub.add_parser(
        "owner-response-templates",
        help="Create owner response templates for mapping repair and WebEx AIS truth requests",
    )
    owner_templates.add_argument("--mapping-request", default="runtime/ais_mapping_repair_request.csv")
    owner_templates.add_argument("--webex-truth-request", default="runtime/webex_ais_truth_request.csv")
    owner_templates.add_argument("--mapping-template", default="runtime/owner_response_templates/mapping_repair_response_template.csv")
    owner_templates.add_argument("--webex-template", default="runtime/owner_response_templates/webex_truth_response_template.csv")
    owner_templates.add_argument("--markdown-output", default="runtime/owner_response_templates.md")
    owner_templates.add_argument("--mapping-top-n", type=int, default=25)
    owner_templates.add_argument("--webex-top-n", type=int, default=100)
    owner_templates.set_defaults(func=cmd_owner_response_templates)

    owner_validate = sub.add_parser(
        "owner-response-validate",
        help="Validate returned owner response files before applying repairs or truth import",
    )
    owner_validate.add_argument("--mapping-response", default="runtime/owner_responses/mapping_repair_response.csv")
    owner_validate.add_argument("--webex-response", default="runtime/owner_responses/webex_truth_response.csv")
    owner_validate.add_argument("--output", default="runtime/owner_response_validation.csv")
    owner_validate.add_argument("--markdown-output", default="runtime/owner_response_validation.md")
    owner_validate.set_defaults(func=cmd_owner_response_validate)

    owner_intake = sub.add_parser(
        "owner-response-intake",
        help="Stage validated owner response rows into safe intake lanes without applying them",
    )
    owner_intake.add_argument("--validation", default="runtime/owner_response_validation.csv")
    owner_intake.add_argument("--output", default="runtime/owner_response_intake.csv")
    owner_intake.add_argument("--markdown-output", default="runtime/owner_response_intake.md")
    owner_intake.set_defaults(func=cmd_owner_response_intake)

    owner_dry_run = sub.add_parser(
        "owner-response-dry-run-impact",
        help="Estimate potential green-row impact from staged owner responses without applying changes",
    )
    owner_dry_run.add_argument("--eligibility", default="runtime/shadow_send_eligibility.csv")
    owner_dry_run.add_argument("--green-gate-tracker", default="runtime/green_gate_tracker.csv")
    owner_dry_run.add_argument("--owner-response-intake", default="runtime/owner_response_intake.csv")
    owner_dry_run.add_argument("--output", default="runtime/owner_response_dry_run_impact.csv")
    owner_dry_run.add_argument("--markdown-output", default="runtime/owner_response_dry_run_impact.md")
    owner_dry_run.add_argument("--min-green-rows", type=int, default=30)
    owner_dry_run.set_defaults(func=cmd_owner_response_dry_run_impact)

    owner_examples = sub.add_parser(
        "owner-response-examples",
        help="Create synthetic owner response examples and an explanation of expected validation outcomes",
    )
    owner_examples.add_argument("--output-dir", default="runtime/owner_response_examples")
    owner_examples.add_argument("--markdown-output", default="runtime/owner_response_examples.md")
    owner_examples.set_defaults(func=cmd_owner_response_examples)

    daily_delta = sub.add_parser(
        "daily-executive-delta",
        help="Build a compact executive daily movement report from refresh history and owner status",
    )
    daily_delta.add_argument("--diff-history", default="runtime/daily_shadow_status_history.csv")
    daily_delta.add_argument("--green-gate-tracker", default="runtime/green_gate_tracker.csv")
    daily_delta.add_argument("--owner-followup-tracker", default="runtime/owner_followup_tracker.csv")
    daily_delta.add_argument("--owner-response-validation", default="runtime/owner_response_validation.csv")
    daily_delta.add_argument("--output", default="runtime/daily_executive_delta.csv")
    daily_delta.add_argument("--markdown-output", default="runtime/daily_executive_delta.md")
    daily_delta.set_defaults(func=cmd_daily_executive_delta)

    pitch_pack = sub.add_parser(
        "executive-pitch-pack",
        help="Build a PDF-ready executive pitch pack from current shadow evidence and owner workflow",
    )
    pitch_pack.add_argument("--executive-one-pager", default="runtime/executive_one_pager.md")
    pitch_pack.add_argument("--daily-delta", default="runtime/daily_executive_delta.md")
    pitch_pack.add_argument("--owner-handoff", default="runtime/owner_handoff_pack.md")
    pitch_pack.add_argument("--owner-followup-tracker", default="runtime/owner_followup_tracker.csv")
    pitch_pack.add_argument("--owner-response-validation", default="runtime/owner_response_validation.csv")
    pitch_pack.add_argument("--dry-run-impact", default="runtime/owner_response_dry_run_impact.csv")
    pitch_pack.add_argument("--output", default="runtime/executive_pitch_pack.md")
    pitch_pack.set_defaults(func=cmd_executive_pitch_pack)

    capability_plan = sub.add_parser(
        "current-capability-development-plan",
        help="Build the current AIS ETR capability/cannot-do/development plan from runtime evidence",
    )
    capability_plan.add_argument("--green-gate-tracker", default="runtime/green_gate_tracker.csv")
    capability_plan.add_argument("--daily-steps", default="runtime/daily_shadow_refresh_steps.csv")
    capability_plan.add_argument("--owner-followup-tracker", default="runtime/owner_followup_tracker.csv")
    capability_plan.add_argument("--owner-response-intake", default="runtime/owner_response_intake.csv")
    capability_plan.add_argument("--owner-response-dry-run", default="runtime/owner_response_dry_run_impact.csv")
    capability_plan.add_argument("--ais-updated-summary", default="runtime/analysis/ais_updated_truth_review_summary.csv")
    capability_plan.add_argument("--ais-updated-mapping-request", default="runtime/analysis/ais_updated_mapping_repair_request.csv")
    capability_plan.add_argument("--ais-updated-mapping-response-template", default="runtime/private/ais_updated_mapping_response_template_simple.csv")
    capability_plan.add_argument("--ais-updated-mapping-private-lookup", default="runtime/private/ais_updated_mapping_repair_request_owner.csv")
    capability_plan.add_argument("--ais-updated-mapping-owner-message", default="runtime/analysis/ais_updated_mapping_question_simple_th.md")
    capability_plan.add_argument("--output", default="runtime/current_capability_development_plan.csv")
    capability_plan.add_argument("--markdown-output", default="runtime/current_capability_development_plan.md")
    capability_plan.set_defaults(func=cmd_current_capability_development_plan)

    flapping_sensitivity = sub.add_parser(
        "flapping-sensitivity-plan",
        help="Build a Phase 2 flapping sensitivity plan without merging source truth",
    )
    flapping_sensitivity.add_argument("--duplicate-flapping", default="runtime/duplicate_flapping_audit.csv")
    flapping_sensitivity.add_argument("--output", default="runtime/flapping_sensitivity_plan.csv")
    flapping_sensitivity.add_argument("--markdown-output", default="runtime/flapping_sensitivity_plan.md")
    flapping_sensitivity.add_argument("--windows", type=int, nargs="+", default=[0, 5, 15, 30])
    flapping_sensitivity.set_defaults(func=cmd_flapping_sensitivity_plan)

    pitching_script = sub.add_parser(
        "pitching-narrative-script",
        help="Build a concise pitching narrative from the current executive and owner handoff outputs",
    )
    pitching_script.add_argument("--executive-one-pager", default="runtime/executive_one_pager.md")
    pitching_script.add_argument("--owner-handoff", default="runtime/owner_handoff_pack.md")
    pitching_script.add_argument("--output", default="runtime/pitching_narrative_script.md")
    pitching_script.set_defaults(func=cmd_pitching_narrative_script)

    console_qa = sub.add_parser(
        "operator-console-qa",
        help="Run static QA checks on the operator console HTML mock",
    )
    console_qa.add_argument("--html", default="runtime/operator_console_mock.html")
    console_qa.add_argument("--output", default="runtime/operator_console_qa.md")
    console_qa.set_defaults(func=cmd_operator_console_qa)

    daily_refresh = sub.add_parser(
        "daily-shadow-refresh",
        help="Run the daily AIS/WebEx/PowerBI shadow evidence refresh in one command",
    )
    daily_refresh.add_argument("--intake-dir", default="runtime/daily_ais_intake")
    daily_refresh.add_argument("--ais-source", default=None, help="Optional AIS daily truth file to import before refresh")
    daily_refresh.add_argument("--ais-source-format", choices=("auto", "add_field", "template"), default="auto")
    daily_refresh.add_argument("--sheet", default="AC MAIN FAIL", help="Excel sheet name or index when importing AIS source")
    daily_refresh.add_argument("--meter-mapping", default=None, help="Optional AIS site-to-meter mapping workbook")
    daily_refresh.add_argument("--no-auto-discover", action="store_true", help="Do not auto-import the newest pending file from the daily inbox")
    daily_refresh.add_argument("--poll-webex", action="store_true", help="Poll WebEx once before rebuilding evidence")
    daily_refresh.add_argument("--max-messages", type=int, default=50)
    daily_refresh.add_argument("--stop-on-error", action="store_true", help="Stop instead of best-effort continuing when a refresh step fails")
    daily_refresh.set_defaults(func=cmd_daily_shadow_refresh)

    lifecycle_bridge = sub.add_parser(
        "notification-lifecycle-bridge-audit",
        help="Prioritize high-error notification-time candidates that need lifecycle bridge evidence",
    )
    lifecycle_bridge.add_argument("--readiness", default="runtime/notification_time_readiness.csv")
    lifecycle_bridge.add_argument("--feature-audit", default="runtime/reportpo_feature_join_audit.csv")
    lifecycle_bridge.add_argument("--output", default="runtime/notification_lifecycle_bridge_candidates.csv")
    lifecycle_bridge.add_argument("--summary-output", default="runtime/notification_lifecycle_bridge_summary.csv")
    lifecycle_bridge.add_argument("--markdown-output", default="runtime/notification_lifecycle_bridge_audit.md")
    lifecycle_bridge.add_argument("--high-error-threshold-minutes", type=float, default=60.0)
    lifecycle_bridge.add_argument("--top-limit", type=int, default=30)
    lifecycle_bridge.set_defaults(func=cmd_notification_lifecycle_bridge_audit)

    event_bridge = sub.add_parser(
        "reportpo-event-bridge-audit",
        help="Check whether ReportPO ETR event numbers bridge high-error notification rows to PO lifecycle rows",
    )
    event_bridge.add_argument("--readiness", default="runtime/notification_time_readiness.csv")
    event_bridge.add_argument("--feature-audit", default="runtime/reportpo_feature_join_audit.csv")
    event_bridge.add_argument("--lifecycle", default="runtime/reportpo_lifecycle_latest.csv")
    event_bridge.add_argument("--output", default="runtime/reportpo_event_bridge_audit.csv")
    event_bridge.add_argument("--summary-output", default="runtime/reportpo_event_bridge_summary.csv")
    event_bridge.add_argument("--markdown-output", default="runtime/reportpo_event_bridge_audit.md")
    event_bridge.add_argument("--high-error-threshold-minutes", type=float, default=60.0)
    event_bridge.set_defaults(func=cmd_reportpo_event_bridge_audit)

    bridge_pack = sub.add_parser(
        "reportpo-bridge-request-pack",
        help="Create a safe shared-key request pack from the ReportPO ETR-to-PO bridge audit",
    )
    bridge_pack.add_argument("--event-bridge", default="runtime/reportpo_event_bridge_audit.csv")
    bridge_pack.add_argument("--output", default="runtime/reportpo_bridge_request_pack.md")
    bridge_pack.add_argument("--priority-output", default="runtime/reportpo_bridge_priority_events.csv")
    bridge_pack.add_argument("--top-limit", type=int, default=20)
    bridge_pack.set_defaults(func=cmd_reportpo_bridge_request_pack)

    shared_key = sub.add_parser(
        "reportpo-shared-key-discovery",
        help="Discover candidate shared keys between ReportPO ETR rows and PO lifecycle rows",
    )
    shared_key.add_argument("--model-inventory", default="runtime/reportpo_model_inventory.csv")
    shared_key.add_argument("--visual-inventory", default="runtime/reportpo_visual_query_inventory.csv")
    shared_key.add_argument("--features", default="runtime/reportpo_features_latest.csv")
    shared_key.add_argument("--lifecycle", default="runtime/reportpo_lifecycle_latest.csv")
    shared_key.add_argument("--event-bridge", default="runtime/reportpo_event_bridge_audit.csv")
    shared_key.add_argument("--candidates-output", default="runtime/reportpo_shared_key_candidates.csv")
    shared_key.add_argument("--overlap-output", default="runtime/reportpo_shared_key_overlap_audit.csv")
    shared_key.add_argument("--markdown-output", default="runtime/reportpo_shared_key_discovery.md")
    shared_key.add_argument("--manual-template-output", default="runtime/reportpo_manual_bridge_template.csv")
    shared_key.add_argument("--pathfinding-report", default="runtime/model_pathfinding_next_report.md")
    shared_key.set_defaults(func=cmd_reportpo_shared_key_discovery)

    manual_bridge = sub.add_parser(
        "reportpo-manual-bridge-candidates",
        help="Suggest audit-only PO lifecycle candidates for manual bridge review",
    )
    manual_bridge.add_argument("--event-bridge", default="runtime/reportpo_event_bridge_audit.csv")
    manual_bridge.add_argument("--lifecycle", default="runtime/reportpo_lifecycle_latest.csv")
    manual_bridge.add_argument("--manual-template", default="runtime/reportpo_manual_bridge_template.csv")
    manual_bridge.add_argument("--suggestions-output", default="runtime/reportpo_manual_bridge_candidate_suggestions.csv")
    manual_bridge.add_argument("--template-output", default="runtime/reportpo_manual_bridge_template_suggested.csv")
    manual_bridge.add_argument("--markdown-output", default="runtime/reportpo_manual_bridge_candidate_suggestions.md")
    manual_bridge.add_argument("--pathfinding-report", default="runtime/model_pathfinding_next_report.md")
    manual_bridge.add_argument("--time-window-minutes", type=float, default=720.0)
    manual_bridge.add_argument("--top-limit", type=int, default=5)
    manual_bridge.add_argument("--min-template-score", type=float, default=95.0)
    manual_bridge.set_defaults(func=cmd_reportpo_manual_bridge_candidates)

    ais_truth_intake = sub.add_parser(
        "ais-truth-intake-kit",
        help="Create the Thai AIS outage/restore truth intake kit",
    )
    ais_truth_intake.add_argument("--output-dir", default="runtime/ais_truth_intake")
    ais_truth_intake.add_argument("--force", action="store_true", help="Overwrite existing intake kit files")
    ais_truth_intake.set_defaults(func=cmd_ais_truth_intake_kit)

    ais_truth_dry_run = sub.add_parser(
        "ais-truth-dry-run",
        help="Validate the AIS truth sample and test shadow matching on a synthetic dry-run runtime",
    )
    ais_truth_dry_run.add_argument("--sample", default="runtime/ais_truth_intake/ais_truth_sample_valid_invalid.csv")
    ais_truth_dry_run.add_argument("--output-dir", default="runtime/ais_truth_intake")
    ais_truth_dry_run.add_argument("--skip-match", action="store_true", help="Only validate import/rejects; skip synthetic match")
    ais_truth_dry_run.set_defaults(func=cmd_ais_truth_dry_run)

    pre_ais_pack = sub.add_parser(
        "pre-ais-evidence-pack",
        help="Build a pre-AIS truth readiness Markdown pack",
    )
    pre_ais_pack.add_argument("--output", default="runtime/pre_ais_truth_readiness_pack.md")
    pre_ais_pack.add_argument("--intake-dir", default="runtime/ais_truth_intake")
    pre_ais_pack.add_argument("--truth-quality-audit", default="runtime/truth_quality_audit.csv")
    pre_ais_pack.add_argument("--shadow-model-comparison", default="runtime/shadow_model_comparison.csv")
    pre_ais_pack.add_argument(
        "--no-match-candidates",
        default="runtime/no_match_registry_repair_candidates_after_pfa05_repair.csv",
    )
    pre_ais_pack.add_argument("--station-mapping-review", default="runtime/station_mapping_review.csv")
    pre_ais_pack.set_defaults(func=cmd_pre_ais_evidence_pack)

    ais_new_files = sub.add_parser(
        "ais-new-files-profile",
        help="Profile new AIS alarm/meter files and build a non-destructive readiness pack",
    )
    ais_new_files.add_argument("--ac-alarm", default="AC MAIN FAIL.csv")
    ais_new_files.add_argument(
        "--meter-mapping",
        default=None,
        help="Optional mapping workbook path; default searches Meter_ID_NE For PEA_*LatLong_R01 1.xlsx",
    )
    ais_new_files.add_argument("--legacy-workbook", default="NE_FAC_AC MAIN FAIL.xlsx")
    ais_new_files.add_argument("--output-dir", default="runtime/analysis")
    ais_new_files.set_defaults(func=cmd_ais_new_files_profile)

    reportpo_import = sub.add_parser("reportpo-etr-import", help="Import ReportPO ETR querydata/CSV to canonical CSV")
    reportpo_import.add_argument("--source", required=True, help="ReportPO CSV export or querydata JSON")
    reportpo_import.add_argument("--output", default="runtime/reportpo_etr_latest.csv")
    reportpo_import.set_defaults(func=cmd_reportpo_etr_import)

    reportpo_fetch = sub.add_parser("reportpo-etr-fetch", help="Fetch ReportPO ETR querydata with Windows NTLM credentials")
    reportpo_fetch.add_argument("--template", default="reportpo_querydata_alltabs.json", help="Captured ReportPO querydata template")
    reportpo_fetch.add_argument("--output", default="runtime/reportpo_etr_querydata_latest.json")
    reportpo_fetch.add_argument("--request-output", default="runtime/reportpo_etr_query_latest.json")
    reportpo_fetch.add_argument("--headers-output", default="runtime/reportpo_etr_query_latest.headers")
    reportpo_fetch.add_argument("--endpoint-url", default=DEFAULT_REPORTPO_QUERYDATA_URL)
    reportpo_fetch.add_argument("--count", type=int, default=30000)
    reportpo_fetch.add_argument("--pages", type=int, default=1)
    reportpo_fetch.add_argument("--curl-path", default="curl.exe")
    reportpo_fetch.set_defaults(func=cmd_reportpo_etr_fetch)

    reportpo_match = sub.add_parser("reportpo-etr-match-truth", help="Match ReportPO actual restoration truth to Webex shadow events")
    reportpo_match.add_argument("--reportpo", default="runtime/reportpo_etr_latest.csv")
    reportpo_match.add_argument("--output", default="runtime/shadow_truth_mapping.csv")
    reportpo_match.add_argument("--audit", default="runtime/reportpo_etr_truth_match_audit.csv")
    reportpo_match.add_argument("--alias-file", default="runtime/reportpo_device_aliases.csv")
    reportpo_match.add_argument("--candidates-output", default="runtime/reportpo_etr_no_match_candidates.csv")
    reportpo_match.add_argument("--max-window-minutes", type=float, default=1440.0)
    reportpo_match.add_argument("--ambiguity-delta-minutes", type=float, default=5.0)
    reportpo_match.add_argument("--overwrite", action="store_true", help="Overwrite existing mapped actuals with ReportPO truth")
    reportpo_match.set_defaults(func=cmd_reportpo_etr_match_truth)

    reportpo_refresh = sub.add_parser("reportpo-etr-refresh", help="Fetch, import, match, and report ReportPO ETR truth")
    reportpo_refresh.add_argument("--template", default="reportpo_querydata_alltabs.json")
    reportpo_refresh.add_argument("--querydata-output", default="runtime/reportpo_etr_querydata_latest.json")
    reportpo_refresh.add_argument("--request-output", default="runtime/reportpo_etr_query_latest.json")
    reportpo_refresh.add_argument("--headers-output", default="runtime/reportpo_etr_query_latest.headers")
    reportpo_refresh.add_argument("--canonical-output", default="runtime/reportpo_etr_latest.csv")
    reportpo_refresh.add_argument("--mapping-output", default="runtime/shadow_truth_mapping_reportpo.csv")
    reportpo_refresh.add_argument("--audit-output", default="runtime/reportpo_etr_truth_match_audit.csv")
    reportpo_refresh.add_argument("--alias-file", default="runtime/reportpo_device_aliases.csv")
    reportpo_refresh.add_argument("--candidates-output", default="runtime/reportpo_etr_no_match_candidates.csv")
    reportpo_refresh.add_argument("--report-output", default="runtime/shadow_evaluation_reportpo.csv")
    reportpo_refresh.add_argument("--endpoint-url", default=DEFAULT_REPORTPO_QUERYDATA_URL)
    reportpo_refresh.add_argument("--count", type=int, default=30000)
    reportpo_refresh.add_argument("--pages", type=int, default=3)
    reportpo_refresh.add_argument("--curl-path", default="curl.exe")
    reportpo_refresh.add_argument("--max-window-minutes", type=float, default=1440.0)
    reportpo_refresh.add_argument("--ambiguity-delta-minutes", type=float, default=5.0)
    reportpo_refresh.set_defaults(func=cmd_reportpo_etr_refresh)

    reportpo_alias = sub.add_parser("reportpo-etr-alias-template", help="Create or update pending ReportPO device alias review CSV")
    reportpo_alias.add_argument("--candidates", default="runtime/reportpo_etr_no_match_candidates.csv")
    reportpo_alias.add_argument("--output", default="runtime/reportpo_device_aliases.csv")
    reportpo_alias.add_argument("--existing", default=None)
    reportpo_alias.set_defaults(func=cmd_reportpo_etr_alias_template)

    reportpo_feature_join = sub.add_parser(
        "reportpo-feature-join",
        help="Join imported ReportPO lifecycle/cause features to Webex shadow events without filling truth",
    )
    reportpo_feature_join.add_argument("--reportpo", default="runtime/reportpo_features_latest.csv")
    reportpo_feature_join.add_argument("--output", default="runtime/reportpo_feature_join_audit.csv")
    reportpo_feature_join.add_argument("--alias-file", default="runtime/reportpo_device_aliases.csv")
    reportpo_feature_join.add_argument("--max-window-minutes", type=float, default=1440.0)
    reportpo_feature_join.add_argument("--ambiguity-delta-minutes", type=float, default=5.0)
    reportpo_feature_join.set_defaults(func=cmd_reportpo_feature_join)

    reportpo_feature_refresh = sub.add_parser(
        "reportpo-feature-refresh",
        help="Fetch ReportPO querydata, import lifecycle/cause features, and join them to Webex shadow events",
    )
    reportpo_feature_refresh.add_argument("--template", default="reportpo_querydata_alltabs.json")
    reportpo_feature_refresh.add_argument("--querydata-output", default="runtime/reportpo_features_querydata_latest.json")
    reportpo_feature_refresh.add_argument("--request-output", default="runtime/reportpo_features_query_latest.json")
    reportpo_feature_refresh.add_argument("--headers-output", default="runtime/reportpo_features_query_latest.headers")
    reportpo_feature_refresh.add_argument("--canonical-output", default="runtime/reportpo_features_latest.csv")
    reportpo_feature_refresh.add_argument("--feature-output", default="runtime/reportpo_feature_join_audit.csv")
    reportpo_feature_refresh.add_argument("--alias-file", default="runtime/reportpo_device_aliases.csv")
    reportpo_feature_refresh.add_argument("--endpoint-url", default=DEFAULT_REPORTPO_QUERYDATA_URL)
    reportpo_feature_refresh.add_argument("--count", type=int, default=30000)
    reportpo_feature_refresh.add_argument("--pages", type=int, default=8)
    reportpo_feature_refresh.add_argument("--curl-path", default="curl.exe")
    reportpo_feature_refresh.add_argument("--max-window-minutes", type=float, default=1440.0)
    reportpo_feature_refresh.add_argument("--ambiguity-delta-minutes", type=float, default=5.0)
    reportpo_feature_refresh.set_defaults(func=cmd_reportpo_feature_refresh)

    reportpo_feature_diag = sub.add_parser(
        "reportpo-feature-diagnostics",
        help="Segment shadow model error by ReportPO feature audit fields",
    )
    reportpo_feature_diag.add_argument("--comparison", default="runtime/shadow_model_comparison_ais.csv")
    reportpo_feature_diag.add_argument("--feature-audit", default="runtime/reportpo_feature_join_audit.csv")
    reportpo_feature_diag.add_argument("--output", default="runtime/reportpo_feature_shadow_diagnostics.csv")
    reportpo_feature_diag.add_argument("--segments-output", default="runtime/reportpo_feature_error_segments.csv")
    reportpo_feature_diag.add_argument("--markdown-output", default="runtime/reportpo_feature_error_diagnostics.md")
    reportpo_feature_diag.add_argument("--high-error-threshold", type=float, default=60.0)
    reportpo_feature_diag.add_argument("--min-segment-truth", type=int, default=3)
    reportpo_feature_diag.set_defaults(func=cmd_reportpo_feature_diagnostics)

    reportpo_feature_label = sub.add_parser(
        "reportpo-feature-label-audit",
        help="Audit ReportPO feature labels for readability and owner-confirmation readiness",
    )
    reportpo_feature_label.add_argument("--features", default="runtime/reportpo_features_latest.csv")
    reportpo_feature_label.add_argument("--diagnostics", default="runtime/reportpo_feature_shadow_diagnostics.csv")
    reportpo_feature_label.add_argument("--output", default="runtime/reportpo_feature_label_audit.csv")
    reportpo_feature_label.add_argument("--markdown-output", default="runtime/reportpo_feature_label_audit.md")
    reportpo_feature_label.set_defaults(func=cmd_reportpo_feature_label_audit)

    reportpo_semantic = sub.add_parser(
        "reportpo-semantic-inference",
        help="Infer ReportPO feature semantics from observed PowerBI distributions when owner confirmation is unavailable",
    )
    reportpo_semantic.add_argument("--features", default="runtime/reportpo_features_latest.csv")
    reportpo_semantic.add_argument("--diagnostics", default="runtime/reportpo_feature_shadow_diagnostics.csv")
    reportpo_semantic.add_argument("--output", default="runtime/reportpo_semantic_inference.csv")
    reportpo_semantic.add_argument("--field-decisions-output", default="runtime/reportpo_semantic_field_decisions.csv")
    reportpo_semantic.add_argument("--markdown-output", default="runtime/reportpo_semantic_inference.md")
    reportpo_semantic.set_defaults(func=cmd_reportpo_semantic_inference)

    reportpo_proxy = sub.add_parser(
        "reportpo-proxy-challenger",
        help="Evaluate a shadow-only ReportPO Group proxy prior against current shadow truth",
    )
    reportpo_proxy.add_argument("--features", default="runtime/reportpo_features_latest.csv")
    reportpo_proxy.add_argument("--diagnostics", default="runtime/reportpo_feature_shadow_diagnostics.csv")
    reportpo_proxy.add_argument("--semantic-inference", default="runtime/reportpo_semantic_inference.csv")
    reportpo_proxy.add_argument("--output", default="runtime/reportpo_proxy_challenger.csv")
    reportpo_proxy.add_argument("--summary-output", default="runtime/reportpo_proxy_challenger_summary.csv")
    reportpo_proxy.add_argument("--markdown-output", default="runtime/reportpo_proxy_challenger.md")
    reportpo_proxy.add_argument("--min-group-rows", type=int, default=100)
    reportpo_proxy.add_argument("--min-global-rows", type=int, default=100)
    reportpo_proxy.set_defaults(func=cmd_reportpo_proxy_challenger)

    reportpo_gap = sub.add_parser(
        "reportpo-feature-gap-audit",
        help="Audit ReportPO/Webex no-match truth rows and export safe candidate review rows",
    )
    reportpo_gap.add_argument("--reportpo", default="runtime/reportpo_features_latest.csv")
    reportpo_gap.add_argument("--proxy-challenger", default="runtime/reportpo_proxy_challenger.csv")
    reportpo_gap.add_argument("--output", default="runtime/reportpo_feature_gap_candidates.csv")
    reportpo_gap.add_argument("--summary-output", default="runtime/reportpo_feature_gap_summary.csv")
    reportpo_gap.add_argument("--markdown-output", default="runtime/reportpo_feature_gap_audit.md")
    reportpo_gap.add_argument("--alias-file", default="runtime/reportpo_device_aliases.csv")
    reportpo_gap.add_argument("--max-window-minutes", type=float, default=1440.0)
    reportpo_gap.add_argument("--limit", type=int, default=5)
    reportpo_gap.set_defaults(func=cmd_reportpo_feature_gap_audit)

    reportpo_lifecycle_import = sub.add_parser(
        "reportpo-lifecycle-import",
        help="Import ReportPO PO lifecycle querydata/CSV to canonical CSV",
    )
    reportpo_lifecycle_import.add_argument("--source", required=True, help="ReportPO PO lifecycle CSV or querydata JSON")
    reportpo_lifecycle_import.add_argument("--output", default="runtime/reportpo_lifecycle_latest.csv")
    reportpo_lifecycle_import.set_defaults(func=cmd_reportpo_lifecycle_import)

    reportpo_lifecycle_fetch = sub.add_parser(
        "reportpo-lifecycle-fetch",
        help="Fetch ReportPO PO lifecycle querydata with Windows NTLM credentials",
    )
    reportpo_lifecycle_fetch.add_argument("--template", default="reportpo_querydata_alltabs.json")
    reportpo_lifecycle_fetch.add_argument("--output", default="runtime/reportpo_lifecycle_querydata_latest.json")
    reportpo_lifecycle_fetch.add_argument("--request-output", default="runtime/reportpo_lifecycle_query_latest.json")
    reportpo_lifecycle_fetch.add_argument("--headers-output", default="runtime/reportpo_lifecycle_query_latest.headers")
    reportpo_lifecycle_fetch.add_argument("--endpoint-url", default=DEFAULT_REPORTPO_QUERYDATA_URL)
    reportpo_lifecycle_fetch.add_argument("--count", type=int, default=30000)
    reportpo_lifecycle_fetch.add_argument("--pages", type=int, default=3)
    reportpo_lifecycle_fetch.add_argument("--curl-path", default="curl.exe")
    reportpo_lifecycle_fetch.set_defaults(func=cmd_reportpo_lifecycle_fetch)

    reportpo_lifecycle_join = sub.add_parser(
        "reportpo-lifecycle-join",
        help="Join imported ReportPO PO lifecycle fields to Webex shadow events without filling truth",
    )
    reportpo_lifecycle_join.add_argument("--lifecycle", default="runtime/reportpo_lifecycle_latest.csv")
    reportpo_lifecycle_join.add_argument("--output", default="runtime/reportpo_lifecycle_join_audit.csv")
    reportpo_lifecycle_join.add_argument("--alias-file", default="runtime/reportpo_device_aliases.csv")
    reportpo_lifecycle_join.add_argument("--max-window-minutes", type=float, default=1440.0)
    reportpo_lifecycle_join.add_argument("--ambiguity-delta-minutes", type=float, default=5.0)
    reportpo_lifecycle_join.set_defaults(func=cmd_reportpo_lifecycle_join)

    reportpo_lifecycle_refresh = sub.add_parser(
        "reportpo-lifecycle-refresh",
        help="Fetch ReportPO PO lifecycle querydata, import it, and join it to Webex shadow events",
    )
    reportpo_lifecycle_refresh.add_argument("--template", default="reportpo_querydata_alltabs.json")
    reportpo_lifecycle_refresh.add_argument("--querydata-output", default="runtime/reportpo_lifecycle_querydata_latest.json")
    reportpo_lifecycle_refresh.add_argument("--request-output", default="runtime/reportpo_lifecycle_query_latest.json")
    reportpo_lifecycle_refresh.add_argument("--headers-output", default="runtime/reportpo_lifecycle_query_latest.headers")
    reportpo_lifecycle_refresh.add_argument("--canonical-output", default="runtime/reportpo_lifecycle_latest.csv")
    reportpo_lifecycle_refresh.add_argument("--join-output", default="runtime/reportpo_lifecycle_join_audit.csv")
    reportpo_lifecycle_refresh.add_argument("--alias-file", default="runtime/reportpo_device_aliases.csv")
    reportpo_lifecycle_refresh.add_argument("--endpoint-url", default=DEFAULT_REPORTPO_QUERYDATA_URL)
    reportpo_lifecycle_refresh.add_argument("--count", type=int, default=30000)
    reportpo_lifecycle_refresh.add_argument("--pages", type=int, default=3)
    reportpo_lifecycle_refresh.add_argument("--curl-path", default="curl.exe")
    reportpo_lifecycle_refresh.add_argument("--max-window-minutes", type=float, default=1440.0)
    reportpo_lifecycle_refresh.add_argument("--ambiguity-delta-minutes", type=float, default=5.0)
    reportpo_lifecycle_refresh.set_defaults(func=cmd_reportpo_lifecycle_refresh)

    reportpo_inventory = sub.add_parser(
        "reportpo-model-inventory",
        help="Inventory ReportPO PowerBI semantic fields and shortlist ETR feature candidates",
    )
    reportpo_inventory.add_argument("--network-capture", default="reportpo_network.json")
    reportpo_inventory.add_argument("--querydata-capture", default="reportpo_querydata_alltabs.json")
    reportpo_inventory.add_argument("--output", default="runtime/reportpo_model_inventory.csv")
    reportpo_inventory.add_argument("--candidates-output", default="runtime/reportpo_model_candidate_fields.csv")
    reportpo_inventory.add_argument("--visuals-output", default="runtime/reportpo_visual_query_inventory.csv")
    reportpo_inventory.add_argument("--markdown-output", default="runtime/reportpo_model_inventory.md")
    reportpo_inventory.set_defaults(func=cmd_reportpo_model_inventory)

    reportpo_pending_import = sub.add_parser(
        "reportpo-pending-import",
        help="Import ReportPO Pending querydata/CSV to canonical CSV",
    )
    reportpo_pending_import.add_argument("--source", required=True, help="ReportPO Pending CSV or querydata JSON")
    reportpo_pending_import.add_argument("--output", default="runtime/reportpo_pending_latest.csv")
    reportpo_pending_import.set_defaults(func=cmd_reportpo_pending_import)

    reportpo_pending_fetch = sub.add_parser(
        "reportpo-pending-fetch",
        help="Fetch ReportPO Pending querydata with Windows NTLM credentials",
    )
    reportpo_pending_fetch.add_argument("--template", default="reportpo_querydata_alltabs.json")
    reportpo_pending_fetch.add_argument("--output", default="runtime/reportpo_pending_querydata_latest.json")
    reportpo_pending_fetch.add_argument("--request-output", default="runtime/reportpo_pending_query_latest.json")
    reportpo_pending_fetch.add_argument("--headers-output", default="runtime/reportpo_pending_query_latest.headers")
    reportpo_pending_fetch.add_argument("--endpoint-url", default=DEFAULT_REPORTPO_QUERYDATA_URL)
    reportpo_pending_fetch.add_argument("--count", type=int, default=30000)
    reportpo_pending_fetch.add_argument("--pages", type=int, default=1)
    reportpo_pending_fetch.add_argument("--curl-path", default="curl.exe")
    reportpo_pending_fetch.set_defaults(func=cmd_reportpo_pending_fetch)

    reportpo_pending_overlap = sub.add_parser(
        "reportpo-pending-overlap",
        help="Audit Pending event/status rows against ReportPO ETR feature join and Webex shadow devices",
    )
    reportpo_pending_overlap.add_argument("--pending", default="runtime/reportpo_pending_latest.csv")
    reportpo_pending_overlap.add_argument("--feature-audit", default="runtime/reportpo_feature_join_audit.csv")
    reportpo_pending_overlap.add_argument("--output", default="runtime/reportpo_pending_overlap_audit.csv")
    reportpo_pending_overlap.set_defaults(func=cmd_reportpo_pending_overlap)

    reportpo_pending_refresh = sub.add_parser(
        "reportpo-pending-refresh",
        help="Fetch ReportPO Pending rows, import them, and audit overlap with current Webex shadow events",
    )
    reportpo_pending_refresh.add_argument("--template", default="reportpo_querydata_alltabs.json")
    reportpo_pending_refresh.add_argument("--querydata-output", default="runtime/reportpo_pending_querydata_latest.json")
    reportpo_pending_refresh.add_argument("--request-output", default="runtime/reportpo_pending_query_latest.json")
    reportpo_pending_refresh.add_argument("--headers-output", default="runtime/reportpo_pending_query_latest.headers")
    reportpo_pending_refresh.add_argument("--canonical-output", default="runtime/reportpo_pending_latest.csv")
    reportpo_pending_refresh.add_argument("--feature-audit", default="runtime/reportpo_feature_join_audit.csv")
    reportpo_pending_refresh.add_argument("--overlap-output", default="runtime/reportpo_pending_overlap_audit.csv")
    reportpo_pending_refresh.add_argument("--endpoint-url", default=DEFAULT_REPORTPO_QUERYDATA_URL)
    reportpo_pending_refresh.add_argument("--count", type=int, default=30000)
    reportpo_pending_refresh.add_argument("--pages", type=int, default=1)
    reportpo_pending_refresh.add_argument("--curl-path", default="curl.exe")
    reportpo_pending_refresh.set_defaults(func=cmd_reportpo_pending_refresh)

    sfsd_import = sub.add_parser(
        "sfsd-import",
        help="Import SFSD PowerBI event-detail CSV/querydata to canonical evidence CSV",
    )
    sfsd_import.add_argument("--source", required=True, help="SFSD CSV export or querydata JSON")
    sfsd_import.add_argument("--output", default="runtime/sfsd_events_latest.csv")
    sfsd_import.set_defaults(func=cmd_sfsd_import)

    sfsd_model = sub.add_parser(
        "sfsd-model-fetch",
        help="Fetch SFSD PowerBI modelsAndExploration metadata with Windows NTLM credentials",
    )
    sfsd_model.add_argument("--output", default="runtime/sfsd_modelsAndExploration.json")
    sfsd_model.add_argument("--headers-output", default="runtime/sfsd_modelsAndExploration.headers")
    sfsd_model.add_argument("--endpoint-url", default=DEFAULT_SFSD_MODELS_URL)
    sfsd_model.add_argument("--curl-path", default="curl.exe")
    sfsd_model.set_defaults(func=cmd_sfsd_model_fetch)

    sfsd_fetch = sub.add_parser(
        "sfsd-fetch",
        help="Fetch SFSD event-detail querydata from the วิเคราะห์ไฟดับ table",
    )
    sfsd_fetch.add_argument("--template", default="runtime/sfsd_modelsAndExploration.json")
    sfsd_fetch.add_argument("--output", default="runtime/sfsd_event_querydata_latest.json")
    sfsd_fetch.add_argument("--request-output", default="runtime/sfsd_event_query_latest.json")
    sfsd_fetch.add_argument("--headers-output", default="runtime/sfsd_event_query_latest.headers")
    sfsd_fetch.add_argument("--endpoint-url", default=DEFAULT_SFSD_QUERYDATA_URL)
    sfsd_fetch.add_argument("--count", type=int, default=30000)
    sfsd_fetch.add_argument("--pages", type=int, default=1)
    sfsd_fetch.add_argument("--event-type", default="ไฟฟ้าขัดข้อง")
    sfsd_fetch.add_argument("--all-event-types", action="store_true")
    sfsd_fetch.add_argument("--curl-path", default="curl.exe")
    sfsd_fetch.set_defaults(func=cmd_sfsd_fetch)

    sfsd_refresh = sub.add_parser(
        "sfsd-refresh",
        help="Fetch, import, and join SFSD event evidence to long-outage AIS shadow misses",
    )
    sfsd_refresh.add_argument("--template", default="runtime/sfsd_modelsAndExploration.json")
    sfsd_refresh.add_argument("--querydata-output", default="runtime/sfsd_event_querydata_latest.json")
    sfsd_refresh.add_argument("--request-output", default="runtime/sfsd_event_query_latest.json")
    sfsd_refresh.add_argument("--headers-output", default="runtime/sfsd_event_query_latest.headers")
    sfsd_refresh.add_argument("--canonical-output", default="runtime/sfsd_events_latest.csv")
    sfsd_refresh.add_argument("--priority", default="runtime/long_outage_root_cause_priority.csv")
    sfsd_refresh.add_argument("--event-bridge", default="runtime/reportpo_event_bridge_audit.csv")
    sfsd_refresh.add_argument("--feature-audit", default="runtime/reportpo_feature_join_audit.csv")
    sfsd_refresh.add_argument("--output", default="runtime/sfsd_long_outage_evidence.csv")
    sfsd_refresh.add_argument("--markdown-output", default="runtime/sfsd_long_outage_evidence.md")
    sfsd_refresh.add_argument("--endpoint-url", default=DEFAULT_SFSD_QUERYDATA_URL)
    sfsd_refresh.add_argument("--count", type=int, default=30000)
    sfsd_refresh.add_argument("--pages", type=int, default=1)
    sfsd_refresh.add_argument("--event-type", default="ไฟฟ้าขัดข้อง")
    sfsd_refresh.add_argument("--all-event-types", action="store_true")
    sfsd_refresh.add_argument("--curl-path", default="curl.exe")
    sfsd_refresh.add_argument("--max-window-minutes", type=float, default=1440.0)
    sfsd_refresh.add_argument("--ambiguity-delta-minutes", type=float, default=5.0)
    sfsd_refresh.set_defaults(func=cmd_sfsd_refresh)

    sfsd_evidence = sub.add_parser(
        "sfsd-long-outage-evidence",
        help="Join SFSD event evidence to long-outage AIS shadow misses without filling truth",
    )
    sfsd_evidence.add_argument("--priority", default="runtime/long_outage_root_cause_priority.csv")
    sfsd_evidence.add_argument("--sfsd", default="runtime/sfsd_events_latest.csv")
    sfsd_evidence.add_argument("--event-bridge", default="runtime/reportpo_event_bridge_audit.csv")
    sfsd_evidence.add_argument("--feature-audit", default="runtime/reportpo_feature_join_audit.csv")
    sfsd_evidence.add_argument("--output", default="runtime/sfsd_long_outage_evidence.csv")
    sfsd_evidence.add_argument("--markdown-output", default="runtime/sfsd_long_outage_evidence.md")
    sfsd_evidence.add_argument("--max-window-minutes", type=float, default=1440.0)
    sfsd_evidence.add_argument("--ambiguity-delta-minutes", type=float, default=5.0)
    sfsd_evidence.set_defaults(func=cmd_sfsd_long_outage_evidence)

    sfsd_gap = sub.add_parser(
        "sfsd-remaining-gap-review",
        help="Build review pack for SFSD rows that are not device-confirmed evidence",
    )
    sfsd_gap.add_argument("--evidence", default="runtime/sfsd_long_outage_evidence.csv")
    sfsd_gap.add_argument("--output", default="runtime/sfsd_remaining_gap_review.csv")
    sfsd_gap.add_argument("--markdown-output", default="runtime/sfsd_remaining_gap_review.md")
    sfsd_gap.add_argument(
        "--include-matched-momentary",
        action="store_true",
        help="Also include exact SFSD matches where PEA operation was <=5 min but AIS remained long",
    )
    sfsd_gap.add_argument("--high-error-minutes", type=float, default=60.0)
    sfsd_gap.set_defaults(func=cmd_sfsd_remaining_gap_review)

    sfsd_resolution = sub.add_parser(
        "sfsd-gap-resolution-audit",
        help="Audit unresolved SFSD gap rows against AIS registry topology and nearest SFSD candidates",
    )
    sfsd_resolution.add_argument("--gap-review", default="runtime/sfsd_remaining_gap_review.csv")
    sfsd_resolution.add_argument("--sfsd", default="runtime/sfsd_events_latest.csv")
    sfsd_resolution.add_argument("--output", default="runtime/sfsd_gap_resolution_audit.csv")
    sfsd_resolution.add_argument("--markdown-output", default="runtime/sfsd_gap_resolution_audit.md")
    sfsd_resolution.add_argument("--nearest-window-minutes", type=float, default=10080.0)
    sfsd_resolution.add_argument("--bridge-window-minutes", type=float, default=1440.0)
    sfsd_resolution.set_defaults(func=cmd_sfsd_gap_resolution_audit)

    sfsd_trace_candidates = sub.add_parser(
        "sfsd-source-trace-candidates",
        help="Export source-trace candidates from unresolved SFSD topology gap rows",
    )
    sfsd_trace_candidates.add_argument("--gap-resolution", default="runtime/sfsd_gap_resolution_audit.csv")
    sfsd_trace_candidates.add_argument("--output", default="runtime/sfsd_source_trace_candidates.csv")
    sfsd_trace_candidates.add_argument("--statuses", default="source_trace_required_for_topology_gap")
    sfsd_trace_candidates.set_defaults(func=cmd_sfsd_source_trace_candidates)

    sfsd_decision = sub.add_parser(
        "sfsd-gap-decision-pack",
        help="Combine SFSD gap resolution and source trace audit into final shadow-only decisions",
    )
    sfsd_decision.add_argument("--gap-resolution", default="runtime/sfsd_gap_resolution_audit.csv")
    sfsd_decision.add_argument("--source-trace-audit", default="runtime/sfsd_source_trace_audit.csv")
    sfsd_decision.add_argument("--output", default="runtime/sfsd_gap_decision_pack.csv")
    sfsd_decision.add_argument("--markdown-output", default="runtime/sfsd_gap_decision_pack.md")
    sfsd_decision.set_defaults(func=cmd_sfsd_gap_decision_pack)

    readiness = sub.add_parser("readiness-report", help="Build shadow readiness Markdown and CSV evidence pack")
    readiness.add_argument("--samples", default="data/webex_shadow_samples.jsonl")
    readiness.add_argument("--output-dir", default="runtime")
    readiness.set_defaults(func=cmd_readiness_report)

    backlog = sub.add_parser("export-backlog", help="Export NO_METER repair backlog")
    backlog.add_argument("--output", default="runtime/no_meter_backlog.csv")
    backlog.set_defaults(func=cmd_export_backlog)

    no_match_repair = sub.add_parser("no-match-repair-candidates", help="Export grouped no-match registry repair candidates")
    no_match_repair.add_argument("--output", default="runtime/no_match_registry_repair_candidates.csv")
    no_match_repair.add_argument("--min-events", type=int, default=1)
    no_match_repair.add_argument("--max-sample-ids", type=int, default=5)
    no_match_repair.set_defaults(func=cmd_no_match_repair_candidates)

    trace_no_match = sub.add_parser("trace-no-match-candidates", help="Trace no-match candidates against upstream_result.xlsx")
    trace_no_match.add_argument("--candidates", default="runtime/no_match_registry_repair_candidates.csv")
    trace_no_match.add_argument("--upstream", default="upstream_result.xlsx")
    trace_no_match.add_argument("--output", default="runtime/no_match_upstream_trace_audit.csv")
    trace_no_match.add_argument("--markdown-output", default="runtime/no_match_upstream_trace_audit.md")
    trace_no_match.set_defaults(func=cmd_trace_no_match_candidates)

    source_trace = sub.add_parser(
        "source-trace-no-match-candidates",
        help="Trace no-match candidates through live ArcGIS source-system downstream trace",
    )
    source_trace.add_argument("--candidates", default="runtime/no_match_registry_repair_candidates.csv")
    source_trace.add_argument("--upstream", default="upstream_result.xlsx")
    source_trace.add_argument("--output", default="runtime/no_match_source_trace_audit.csv")
    source_trace.add_argument("--markdown-output", default="runtime/no_match_source_trace_audit.md")
    source_trace.add_argument("--redacted-dir", default="runtime/source_trace_redacted")
    source_trace.add_argument("--base-url", default=DEFAULT_GIS_BASE_URL)
    source_trace.add_argument("--trace-url", default=DEFAULT_TRACE_DOWN_URL)
    source_trace.add_argument("--timeout-seconds", type=float, default=60.0)
    source_trace.add_argument("--sleep-seconds", type=float, default=0.35)
    source_trace.add_argument("--limit", type=int, default=None)
    source_trace.set_defaults(func=cmd_source_trace_no_match_candidates)

    private_overrides = sub.add_parser(
        "private-protection-overrides",
        help="Create a private PEANO-level protection mapping override CSV from source trace evidence",
    )
    private_overrides.add_argument("--source-trace-audit", default="runtime/no_match_source_trace_audit.csv")
    private_overrides.add_argument("--output", default="runtime/private/protection_mapping_overrides.csv")
    private_overrides.add_argument("--registry", default="upstream_result.xlsx")
    private_overrides.add_argument("--device-id", default=None, help="Optional source-trace device id filter, e.g. PFA05VB-01")
    private_overrides.add_argument("--status", default="pending", choices=("pending", "approved", "rejected"))
    private_overrides.add_argument("--reviewed-by", default="")
    private_overrides.add_argument("--reviewed-at", default=None)
    private_overrides.add_argument("--base-url", default=DEFAULT_GIS_BASE_URL)
    private_overrides.add_argument("--trace-url", default=DEFAULT_TRACE_DOWN_URL)
    private_overrides.add_argument("--timeout-seconds", type=float, default=180.0)
    private_overrides.add_argument("--sleep-seconds", type=float, default=0.35)
    private_overrides.set_defaults(func=cmd_private_protection_overrides)

    apply_overrides = sub.add_parser(
        "apply-protection-overrides",
        help="Apply approved private protection mapping overrides to runtime customer_assets",
    )
    apply_overrides.add_argument("--overrides", default="runtime/private/protection_mapping_overrides.csv")
    apply_overrides.add_argument("--audit-output", default="runtime/private/protection_mapping_apply_audit.csv")
    apply_overrides.add_argument("--required-status", default="approved")
    apply_overrides.set_defaults(func=cmd_apply_protection_overrides)

    schematic = sub.add_parser("source-trace-schematic", help="Create Markdown schematic from source trace audit")
    schematic.add_argument("--source-trace-audit", default="runtime/no_match_source_trace_audit.csv")
    schematic.add_argument("--output", default="runtime/no_match_source_trace_schematic.md")
    schematic.set_defaults(func=cmd_source_trace_schematic)

    station_mapping = sub.add_parser("station-mapping", help="Create station-prefix to district/scope mapping template")
    station_mapping.add_argument("--output", default="runtime/station_district_mapping.csv")
    station_mapping.set_defaults(func=cmd_station_mapping)

    station_review = sub.add_parser("station-mapping-review", help="Review station-prefix evidence before approving scope mapping")
    station_review.add_argument("--mapping", default="runtime/station_district_mapping.csv")
    station_review.add_argument("--output", default="runtime/station_mapping_review.csv")
    station_review.add_argument("--markdown-output", default="runtime/station_mapping_review.md")
    station_review.set_defaults(func=cmd_station_mapping_review)

    scope_compare = sub.add_parser("model-scope-comparison", help="Compare pilot-only vs expanded-six-area model scope")
    scope_compare.add_argument("--mapping", default="runtime/station_district_mapping.csv")
    scope_compare.add_argument("--output", default="runtime/model_scope_comparison.csv")
    scope_compare.add_argument("--markdown-output", default="runtime/model_scope_comparison.md")
    scope_compare.set_defaults(func=cmd_model_scope_comparison)

    scope_challenger = sub.add_parser("model-scope-train-challenger", help="Train a separate shadow challenger model from approved station scopes")
    scope_challenger.add_argument("--mapping", default="runtime/station_district_mapping.csv")
    scope_challenger.add_argument("--train-scope", choices=("pilot_3", "expanded_6"), default="expanded_6")
    scope_challenger.add_argument("--output-model", default="runtime/model_challenger_expanded_quantiles.json")
    scope_challenger.add_argument("--markdown-output", default="runtime/model_challenger_expanded_summary.md")
    scope_challenger.set_defaults(func=cmd_model_scope_train_challenger)

    shadow_compare = sub.add_parser("shadow-model-compare", help="Compare current and challenger model artifacts on runtime shadow events")
    shadow_compare.add_argument("--current-model", default="runtime/model_quantiles.json")
    shadow_compare.add_argument("--challenger-model", default="runtime/model_challenger_expanded_quantiles.json")
    shadow_compare.add_argument("--truth-mapping", default="runtime/shadow_truth_mapping_reportpo.csv")
    shadow_compare.add_argument("--output", default="runtime/shadow_model_comparison.csv")
    shadow_compare.add_argument("--markdown-output", default="runtime/shadow_model_comparison.md")
    shadow_compare.set_defaults(func=cmd_shadow_model_compare)

    truth_quality = sub.add_parser("shadow-truth-quality-audit", help="Audit shadow truth quality and short-restoration sensitivity")
    truth_quality.add_argument("--comparison", default="runtime/shadow_model_comparison.csv")
    truth_quality.add_argument("--output", default="runtime/truth_quality_audit.csv")
    truth_quality.add_argument("--markdown-output", default="runtime/truth_quality_report.md")
    truth_quality.add_argument("--micro-threshold-minutes", type=float, default=1.0)
    truth_quality.add_argument("--short-threshold-minutes", type=float, default=5.0)
    truth_quality.set_defaults(func=cmd_shadow_truth_quality_audit)

    incident_cluster = sub.add_parser(
        "shadow-incident-cluster",
        help="Deduplicate Webex shadow rows into AIS outage incident-level evaluation",
    )
    incident_cluster.add_argument("--comparison", default="runtime/shadow_model_comparison_ais.csv")
    incident_cluster.add_argument("--audit", default="runtime/ais_truth_shadow_match_audit.csv")
    incident_cluster.add_argument("--output", default="runtime/shadow_incident_comparison_ais.csv")
    incident_cluster.add_argument("--markdown-output", default="runtime/shadow_incident_clustering_ais.md")
    incident_cluster.add_argument("--prediction-policy", choices=("first_event",), default="first_event")
    incident_cluster.set_defaults(func=cmd_shadow_incident_cluster)

    incident_replay = sub.add_parser(
        "shadow-incident-replay-report",
        help="Compare raw Webex-message metrics with clustered AIS incident-level metrics",
    )
    incident_replay.add_argument("--comparison", default="runtime/shadow_model_comparison_ais.csv")
    incident_replay.add_argument("--audit", default="runtime/ais_truth_shadow_match_audit.csv")
    incident_replay.add_argument("--incident-comparison", default="runtime/shadow_incident_comparison_ais.csv")
    incident_replay.add_argument("--output", default="runtime/shadow_incident_replay_report.csv")
    incident_replay.add_argument("--markdown-output", default="runtime/shadow_incident_replay_report.md")
    incident_replay.add_argument("--high-error-minutes", type=float, default=60.0)
    incident_replay.add_argument("--focus-feeder", action="append", default=["SEK06"])
    incident_replay.add_argument(
        "--focus-device",
        action="append",
        default=["SEK06VR-103", "SEK06VR-104", "SEK06VR-105"],
    )
    incident_replay.set_defaults(func=cmd_shadow_incident_replay_report)

    error_diag = sub.add_parser(
        "shadow-error-diagnostics",
        help="Explain AIS shadow incident error by duration, feeder, device type, and affected count",
    )
    error_diag.add_argument("--comparison", default="runtime/shadow_incident_comparison_ais.csv")
    error_diag.add_argument("--output", default="runtime/shadow_error_segments_ais.csv")
    error_diag.add_argument("--markdown-output", default="runtime/shadow_error_diagnostics_ais.md")
    error_diag.set_defaults(func=cmd_shadow_error_diagnostics)

    ais_history = sub.add_parser(
        "shadow-ais-history-challenger",
        help="Compare current incident predictions with a time-respecting AIS alarm-history challenger",
    )
    ais_history.add_argument("--comparison", default="runtime/shadow_incident_comparison_ais.csv")
    ais_history.add_argument("--ais-truth", default="runtime/ais_truth_latest_candidate.csv")
    ais_history.add_argument("--output", default="runtime/shadow_ais_history_challenger.csv")
    ais_history.add_argument("--markdown-output", default="runtime/shadow_ais_history_challenger.md")
    ais_history.add_argument("--min-history-rows", type=int, default=10)
    ais_history.add_argument("--lower-quantile", type=float, default=0.05)
    ais_history.add_argument("--upper-quantile", type=float, default=0.95)
    ais_history.set_defaults(func=cmd_shadow_ais_history_challenger)

    long_outage = sub.add_parser(
        "shadow-long-outage-challenger",
        help="Simulate refresh-time ETR updates using AIS alarms still active as of each horizon",
    )
    long_outage.add_argument("--comparison", default="runtime/shadow_incident_comparison_ais.csv")
    long_outage.add_argument("--ais-truth", default="runtime/ais_truth_latest_candidate.csv")
    long_outage.add_argument("--history-challenger", default="runtime/shadow_ais_history_challenger.csv")
    long_outage.add_argument("--output", default="runtime/shadow_long_outage_challenger.csv")
    long_outage.add_argument("--markdown-output", default="runtime/shadow_long_outage_challenger.md")
    long_outage.add_argument("--horizons", default="0,15,30,60,120")
    long_outage.add_argument("--min-history-rows", type=int, default=10)
    long_outage.set_defaults(func=cmd_shadow_long_outage_challenger)

    webex_elapsed = sub.add_parser(
        "shadow-webex-elapsed-challenger",
        help="Simulate refresh-time ETR updates from repeated Webex messages in the same AIS incident",
    )
    webex_elapsed.add_argument("--comparison", default="runtime/shadow_model_comparison_ais.csv")
    webex_elapsed.add_argument("--audit", default="runtime/ais_truth_shadow_match_audit.csv")
    webex_elapsed.add_argument("--ais-truth", default="runtime/ais_truth_latest_candidate.csv")
    webex_elapsed.add_argument("--history-challenger", default="runtime/shadow_ais_history_challenger.csv")
    webex_elapsed.add_argument("--output", default="runtime/shadow_webex_elapsed_challenger.csv")
    webex_elapsed.add_argument("--markdown-output", default="runtime/shadow_webex_elapsed_challenger.md")
    webex_elapsed.add_argument("--min-history-rows", type=int, default=10)
    webex_elapsed.add_argument("--post-restore-tolerance-minutes", type=float, default=5.0)
    webex_elapsed.set_defaults(func=cmd_shadow_webex_elapsed_challenger)

    active_state = sub.add_parser(
        "shadow-active-state-remaining-challenger",
        help="Test a time-respecting active AIS state challenger for remaining restoration minutes",
    )
    active_state.add_argument("--readiness", default="runtime/notification_time_readiness.csv")
    active_state.add_argument("--ais-truth", default="runtime/ais_truth_latest_candidate.csv")
    active_state.add_argument("--output", default="runtime/shadow_active_state_remaining_challenger.csv")
    active_state.add_argument("--markdown-output", default="runtime/shadow_active_state_remaining_challenger.md")
    active_state.add_argument("--segments-output", default="runtime/shadow_active_state_remaining_segments.csv")
    active_state.add_argument("--min-segment-rows", type=int, default=5)
    active_state.add_argument("--min-meter-history-rows", type=int, default=3)
    active_state.add_argument("--high-error-minutes", type=float, default=60.0)
    active_state.set_defaults(func=cmd_shadow_active_state_remaining_challenger)

    root_cause = sub.add_parser(
        "shadow-long-outage-root-cause-pack",
        help="Create a lifecycle/cause evidence pack for long-outage active-state misses",
    )
    root_cause.add_argument("--active-state", default="runtime/shadow_active_state_remaining_challenger.csv")
    root_cause.add_argument("--shared-key-audit", default="runtime/reportpo_shared_key_overlap_audit.csv")
    root_cause.add_argument("--manual-bridge", default="runtime/reportpo_manual_bridge_template.csv")
    root_cause.add_argument("--lifecycle-review", default="runtime/ops_lifecycle_review_top_misses.csv")
    root_cause.add_argument("--output", default="runtime/long_outage_root_cause_priority.csv")
    root_cause.add_argument("--markdown-output", default="runtime/long_outage_root_cause_priority.md")
    root_cause.add_argument("--review-template-output", default="runtime/ops_lifecycle_review_top_misses.csv")
    root_cause.add_argument("--high-error-minutes", type=float, default=60.0)
    root_cause.add_argument("--duration-outlier-minutes", type=float, default=480.0)
    root_cause.add_argument("--sparse-history-min-rows", type=int, default=5)
    root_cause.add_argument("--top-limit", type=int, default=50)
    root_cause.set_defaults(func=cmd_shadow_long_outage_root_cause_pack)

    webex_device_state = sub.add_parser(
        "shadow-webex-device-state-diagnostics",
        help="Segment AIS ETR error by Webex device open/close interruption state",
    )
    webex_device_state.add_argument("--comparison", default="runtime/shadow_model_comparison_ais.csv")
    webex_device_state.add_argument("--output", default="runtime/shadow_webex_device_state_diagnostic.csv")
    webex_device_state.add_argument("--markdown-output", default="runtime/shadow_webex_device_state_diagnostic.md")
    webex_device_state.set_defaults(func=cmd_shadow_webex_device_state_diagnostics)

    ops_template = sub.add_parser(
        "ops-lifecycle-template",
        help="Create an eRespond/field-work lifecycle intake template from the largest remaining AIS ETR misses",
    )
    ops_template.add_argument("--comparison", default="runtime/shadow_incident_comparison_ais.csv")
    ops_template.add_argument("--long-outage", default="runtime/shadow_long_outage_challenger.csv")
    ops_template.add_argument("--webex-elapsed", default="runtime/shadow_webex_elapsed_challenger.csv")
    ops_template.add_argument("--output", default="runtime/ops_lifecycle_intake_template.csv")
    ops_template.add_argument("--markdown-output", default="runtime/ops_lifecycle_intake_template.md")
    ops_template.add_argument("--horizon-minutes", type=int, default=60)
    ops_template.add_argument("--top-n", type=int, default=50)
    ops_template.set_defaults(func=cmd_ops_lifecycle_template)

    ops_validate = sub.add_parser(
        "ops-lifecycle-validate",
        help="Validate a filled eRespond/field-work lifecycle intake file before feature engineering",
    )
    ops_validate.add_argument("--input", default="runtime/ops_lifecycle_intake_template.csv")
    ops_validate.add_argument("--output-valid", default="runtime/ops_lifecycle_valid.csv")
    ops_validate.add_argument("--rejects", default="runtime/ops_lifecycle_rejects.csv")
    ops_validate.add_argument("--markdown-output", default="runtime/ops_lifecycle_validation.md")
    ops_validate.set_defaults(func=cmd_ops_lifecycle_validate)

    summary = sub.add_parser("summary", help="Print runtime table counts")
    summary.set_defaults(func=cmd_summary)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
