from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .ais_v2_lifecycle_audit import _get_json, _parse_time


MAPPING_VERSION = "alarm_mapping_v2"
OPEN_REVIEW_HOURS = 24.0
QUEUE_COLUMNS = (
    "case_ref",
    "event_time",
    "classification",
    "evidence_source",
    "age_hours",
    "use_for_training",
    "use_for_evaluation",
    "use_for_context",
    "production_send",
)


def run_meter_state_review_gate(
    *,
    base_url: str,
    queue_csv: str | Path,
    summary_json: str | Path,
    report_md: str | Path,
    handoff_md: str | Path,
    api_key: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    key = str(api_key or os.environ.get("AIS_INBOUND_API_KEY") or "").strip()
    if not key:
        raise ValueError("AIS_INBOUND_API_KEY is required")
    root = base_url.rstrip("/")
    metrics = _get_json(root + "/metrics", key)
    intervals = _fetch_all_intervals(root, key, limit)
    operator = _get_json(
        root + "/api/v1/ais/outage-verifications?" + urlencode({"view": "operator", "limit": str(max(1, min(limit, 200)))}),
        key,
    )
    for label, payload in (("metrics", metrics), ("intervals", intervals), ("operator", operator)):
        if payload.get("production_send") != "blocked":
            raise ValueError(f"{label} production_send must remain blocked")
    return build_meter_state_review_gate(
        metrics,
        intervals.get("items") or [],
        operator.get("items") or [],
        queue_csv=queue_csv,
        summary_json=summary_json,
        report_md=report_md,
        handoff_md=handoff_md,
    )


def _fetch_all_intervals(root: str, api_key: str, limit: int) -> dict[str, Any]:
    page_limit = max(1, min(limit, 200))
    items: list[dict[str, Any]] = []
    cursor = ""
    seen = set()
    for _ in range(50):
        query = {"status": "ALL", "limit": str(page_limit)}
        if cursor:
            query["cursor"] = cursor
        payload = _get_json(root + "/api/v1/ais/truth-intervals?" + urlencode(query), api_key)
        if payload.get("production_send") != "blocked":
            raise ValueError("intervals production_send must remain blocked")
        page = payload.get("items") or []
        items.extend(page)
        next_cursor = str(payload.get("next_cursor") or "").strip()
        if not next_cursor or next_cursor in seen or not page:
            return {"production_send": "blocked", "items": items}
        seen.add(next_cursor)
        cursor = next_cursor
    raise ValueError("truth_interval_cursor_limit_exceeded")


def build_meter_state_review_gate(
    metrics: dict[str, Any],
    intervals: list[dict[str, Any]],
    operator_items: list[dict[str, Any]],
    *,
    queue_csv: str | Path,
    summary_json: str | Path,
    report_md: str | Path,
    handoff_md: str | Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    if metrics.get("production_send") != "blocked":
        raise ValueError("production_send must remain blocked")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    queue = []
    for interval in intervals:
        item = _queue_row(interval, now)
        if item is not None:
            queue.append(item)

    validation_counts = dict(metrics.get("truth_validation_counts") or {})
    semantic_counts = dict(metrics.get("truth_event_semantic_counts") or {})
    metric_review_categories = {
        "missing_meter_no": _integer(validation_counts.get("REVIEW_IDENTITY_KEY_REQUIRED")),
        "unknown_status_mapping": _integer(validation_counts.get("REVIEW_EVENT_TYPE")),
        "duplicate_or_late_restore": _integer(validation_counts.get("REVIEW_NO_OPEN_INTERVAL")),
        "duration_review": _integer(validation_counts.get("REVIEW_DURATION_OUT_OF_RANGE")),
    }
    recent_operator_counts = _operator_diagnostic_counts(operator_items)
    classifications = _counts(queue, "classification")
    summary = {
        "mapping_version": str(metrics.get("semantic_mapping_version") or ""),
        "review_queue_metric_rows": _integer(metrics.get("truth_review_needed")),
        "v2_open_interval_metric_rows": _integer(metrics.get("v2_open_intervals")),
        "truth_stale_open_interval_metric_rows": _integer(metrics.get("truth_stale_open_intervals")),
        "queue_rows": len(queue),
        "queue_classifications": classifications,
        "metric_review_categories": metric_review_categories,
        "validation_counts": validation_counts,
        "semantic_counts": semantic_counts,
        "recent_operator_sample_counts": recent_operator_counts,
        "operator_detail_note": "Operator endpoint is a latest-window diagnostic sample; metric counts remain the full-count authority.",
        "integration_contract": {
            "required": ["meter_no (PEANO)", "timestamp", "explicit event_type or allowlisted status/alarm"],
            "optional": ["source_event_id", "site_id", "location_id"],
            "unknown_alarm_policy": "audit_only_review_event_type",
        },
        "use_for_training": False,
        "use_for_evaluation": False,
        "production_send": "blocked",
        "next_model_action": "wait_for_seven_day_re_evaluation; do_not_tune_rejected_history_only_policy",
    }
    _write_csv(Path(queue_csv), queue)
    Path(summary_json).parent.mkdir(parents=True, exist_ok=True)
    Path(summary_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    Path(report_md).parent.mkdir(parents=True, exist_ok=True)
    Path(report_md).write_text(_render_report(summary), encoding="utf-8")
    Path(handoff_md).parent.mkdir(parents=True, exist_ok=True)
    Path(handoff_md).write_text(_render_handoff(summary), encoding="utf-8")
    return {
        **summary,
        "queue_csv": str(queue_csv),
        "summary_json": str(summary_json),
        "report_md": str(report_md),
        "handoff_md": str(handoff_md),
    }


def _queue_row(interval: dict[str, Any], now: datetime) -> dict[str, str] | None:
    mapping = str(interval.get("semantic_mapping_version") or "legacy")
    pair = str(interval.get("pair_status") or "").upper()
    bridge = str(interval.get("bridge_status") or "").upper()
    hint = str(interval.get("review_hint") or "").upper()
    policy = str(interval.get("review_policy") or "").upper()
    if mapping != MAPPING_VERSION:
        return None
    if pair == "CLOSED" and bridge == "METER_STATE_MODEL_READY":
        return None
    event_time = _parse_time(interval.get("outage_at") or interval.get("updated_at"))
    age = ""
    if event_time is not None:
        age = f"{max(0.0, (now - event_time).total_seconds() / 3600.0):.3f}"
    classification = _classification(pair, bridge, hint, policy, event_time, now)
    raw_ref = str(interval.get("interval_ref") or interval.get("outage_request_ref") or interval.get("restore_request_ref") or "")
    return {
        "case_ref": _case_ref(raw_ref, event_time),
        "event_time": _format_time(event_time),
        "classification": classification,
        "evidence_source": "redacted_truth_interval",
        "age_hours": age,
        "use_for_training": "FALSE",
        "use_for_evaluation": "FALSE",
        "use_for_context": "TRUE",
        "production_send": "blocked",
    }


def _classification(pair: str, bridge: str, hint: str, policy: str, event_time: datetime | None, now: datetime) -> str:
    evidence = "|".join((pair, bridge, hint, policy))
    if "IDENTITY" in evidence or "METER" in evidence and "MISSING" in evidence:
        return "missing_meter_no"
    if "EVENT_TYPE" in evidence or "SEMANTIC" in evidence or "UNKNOWN" in evidence:
        return "unknown_status_mapping"
    if "NO_OPEN" in evidence or "MULTIPLE_OPEN" in evidence:
        return "duplicate_or_late_restore"
    if "DURATION" in evidence:
        return "duration_review"
    if pair == "OPEN" or "AWAITING_RESTORE" in bridge:
        if event_time is not None and now - event_time > timedelta(hours=OPEN_REVIEW_HOURS):
            return "missing_restore"
        return "active_outage"
    return "review_required"


def _operator_diagnostic_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        truth = item.get("truth_observation") or {}
        status = str(truth.get("validation_status") or "missing").strip() or "missing"
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _case_ref(value: str, event_time: datetime | None) -> str:
    seed = value + "|" + _format_time(event_time)
    return "case_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _counts(rows: list[dict[str, str]], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        value = row[key]
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _format_time(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _render_report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Meter-State Review Gate",
            "",
            f"- mapping version: `{summary['mapping_version']}`",
            f"- review metric rows: `{summary['review_queue_metric_rows']}`",
            f"- v2 open intervals: `{summary['v2_open_interval_metric_rows']}`",
            f"- stale open intervals: `{summary['truth_stale_open_interval_metric_rows']}`",
            f"- redacted queue rows: `{summary['queue_rows']}`",
            f"- classifications: `{json.dumps(summary['queue_classifications'], sort_keys=True)}`",
            f"- metric review categories: `{json.dumps(summary['metric_review_categories'], sort_keys=True)}`",
            f"- validation counts: `{json.dumps(summary['validation_counts'], sort_keys=True)}`",
            "- review rows are context-only and excluded from train/evaluation/MAE/coverage/green incidents",
            "- production_send: `blocked`",
            "",
        ]
    )


def _render_handoff(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Internal AIS Integration Handoff",
            "",
            "## Required for every outage or restore event",
            "- `meter_no`: PEA PEANO for the affected meter",
            "- `timestamp`: ISO 8601 with offset; Asia/Bangkok only when the source has no offset",
            "- one of: explicit `event_type=OUTAGE|RESTORE`, or an allowlisted status/alarm code",
            "",
            "## Optional evidence",
            "- `source_event_id`, `site_id`, and `location_id` are optional. Their absence must not block meter-state pairing.",
            "- Do not include customer name, address, PEANO list, token, or raw chat text in operational handoffs.",
            "",
            "## Review behavior",
            "- Missing `meter_no` enters `missing_meter_no` review and cannot create model truth.",
            "- Unknown alarm/status enters `unknown_status_mapping` audit-only review; no automatic mapping is enabled.",
            "- RESTORE without one open meter-state interval enters duplicate/late-restore review.",
            "",
            "## Current control",
            "- `mode=shadow`, `production_send=blocked`, and callback transport remains dry-run.",
            "",
        ]
    )
