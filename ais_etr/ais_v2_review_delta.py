from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .ais_meter_state_review_gate import _fetch_all_intervals
from .ais_v2_lifecycle_audit import _get_json, _parse_time


MAPPING_VERSION = "alarm_mapping_v2"
WINDOW_HOURS = 168.0
COUNT_FIELDS = (
    "v2_model_ready_rows",
    "v2_open_intervals",
    "truth_stale_open_intervals",
    "truth_review_needed",
    "review_identity_required",
    "review_event_type",
    "review_no_open_interval",
    "review_duration",
)
DELTA_COLUMNS = ("metric", "previous", "current", "delta")
MISSING_RESTORE_COLUMNS = (
    "case_ref",
    "event_time",
    "age_hours",
    "classification",
    "use_for_training",
    "use_for_evaluation",
    "use_for_context",
    "production_send",
)


def run_v2_review_delta(
    *,
    base_url: str,
    history_jsonl: str | Path,
    delta_csv: str | Path,
    summary_json: str | Path,
    report_md: str | Path,
    missing_restore_csv: str | Path,
    api_key: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    key = str(api_key or os.environ.get("AIS_INBOUND_API_KEY") or "").strip()
    if not key:
        raise ValueError("AIS_INBOUND_API_KEY is required")
    root = base_url.rstrip("/")
    metrics = _get_json(root + "/metrics", key)
    if metrics.get("production_send") != "blocked":
        raise ValueError("production_send must remain blocked")
    stale = _integer(metrics.get("truth_stale_open_intervals"))
    intervals: list[dict[str, Any]] = []
    if stale > 0:
        intervals = _fetch_all_intervals(root, key, 200).get("items") or []
    return build_v2_review_delta(
        metrics,
        intervals,
        history_jsonl=history_jsonl,
        delta_csv=delta_csv,
        summary_json=summary_json,
        report_md=report_md,
        missing_restore_csv=missing_restore_csv,
        now=now,
    )


def build_v2_review_delta(
    metrics: dict[str, Any],
    intervals: list[dict[str, Any]],
    *,
    history_jsonl: str | Path,
    delta_csv: str | Path,
    summary_json: str | Path,
    report_md: str | Path,
    missing_restore_csv: str | Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    if metrics.get("production_send") != "blocked":
        raise ValueError("production_send must remain blocked")
    generated = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    validation = dict(metrics.get("truth_validation_counts") or {})
    snapshot = {
        "run_id": generated.strftime("%Y%m%dT%H%M%S.%fZ"),
        "generated_at": _format_time(generated),
        "semantic_mapping_version": str(metrics.get("semantic_mapping_version") or ""),
        "v2_activation_first_seen_at": str(metrics.get("v2_activation_first_seen_at") or ""),
        "v2_model_ready_rows": _integer(metrics.get("v2_model_ready_rows") or metrics.get("model_ready_clean_truth_rows")),
        "v2_open_intervals": _integer(metrics.get("v2_open_intervals")),
        "truth_stale_open_intervals": _integer(metrics.get("truth_stale_open_intervals")),
        "truth_review_needed": _integer(metrics.get("truth_review_needed")),
        "review_identity_required": _integer(validation.get("REVIEW_IDENTITY_KEY_REQUIRED")),
        "review_event_type": _integer(validation.get("REVIEW_EVENT_TYPE")),
        "review_no_open_interval": _integer(validation.get("REVIEW_NO_OPEN_INTERVAL")),
        "review_duration": _integer(validation.get("REVIEW_DURATION_OUT_OF_RANGE")),
        "production_send": "blocked",
    }
    history_path = Path(history_jsonl)
    history = _read_history(history_path)
    previous = history[-1] if history else None
    if previous and generated < _required_time(previous.get("generated_at"), "previous generated_at"):
        raise ValueError("snapshot timestamp must not move backwards")
    duplicate = bool(previous and snapshot["run_id"] == previous.get("run_id"))
    deltas = {field: snapshot[field] - _integer(previous.get(field)) if previous else 0 for field in COUNT_FIELDS}
    negative = sorted(field for field, value in deltas.items() if value < 0)
    reasons: list[str] = []
    if negative:
        status = "metrics_reset_quarantined"
        reasons.append("negative_metric_delta:" + ",".join(negative))
    elif snapshot["truth_stale_open_intervals"] > 0:
        status = "stale_restore_gap"
        reasons.append("stale_open_interval_present")
    elif deltas["review_identity_required"] > 0 or deltas["review_event_type"] > 0:
        status = "new_payload_regression"
        reasons.append("identity_or_event_review_increased")
    elif deltas["review_no_open_interval"] > 0 or deltas["review_duration"] > 0:
        status = "new_lifecycle_anomaly"
        reasons.append("no_open_or_duration_review_increased")
    elif deltas["v2_open_intervals"] > 0:
        status = "open_interval_watch"
        reasons.append("open_intervals_increased_without_stale_rows")
    else:
        status = "stable_historical_backlog"
        reasons.append("review_counts_unchanged_or_improved")

    activation = _parse_time(snapshot["v2_activation_first_seen_at"])
    window_hours = max(0.0, (generated - activation).total_seconds() / 3600.0) if activation else 0.0
    missing_rows = _missing_restore_rows(intervals, generated) if snapshot["truth_stale_open_intervals"] else []
    summary = {
        **snapshot,
        "comparison_status": "baseline_initialized" if previous is None else "compared_with_previous_snapshot",
        "gate_status": status,
        "escalation_reasons": reasons,
        "metric_deltas": deltas,
        "negative_delta_fields": negative,
        "history_append_status": "duplicate_run_id_noop" if duplicate else "appended",
        "data_window_hours": round(window_hours, 3),
        "seven_day_re_evaluation_due": bool(activation and window_hours >= WINDOW_HOURS),
        "missing_restore_queue_rows": len(missing_rows),
        "mode": "shadow",
        "production_send": "blocked",
        "history_only_policy_action": "evaluate_only_never_tune_or_promote",
    }
    if not duplicate:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot, ensure_ascii=False, sort_keys=True) + "\n")
    _write_csv(Path(delta_csv), [
        {"metric": field, "previous": _integer(previous.get(field)) if previous else snapshot[field], "current": snapshot[field], "delta": deltas[field]}
        for field in COUNT_FIELDS
    ], DELTA_COLUMNS)
    _write_csv(Path(missing_restore_csv), missing_rows, MISSING_RESTORE_COLUMNS)
    _write_text(Path(summary_json), json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _write_text(Path(report_md), _render_report(summary))
    return {**summary, "history_jsonl": str(history_path), "delta_csv": str(delta_csv), "summary_json": str(summary_json), "report_md": str(report_md), "missing_restore_csv": str(missing_restore_csv)}


def _read_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    prior: datetime | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        current = _required_time(row.get("generated_at"), "history generated_at")
        if prior and current < prior:
            raise ValueError("history timestamps must be ordered")
        prior = current
        rows.append(row)
    return rows


def _missing_restore_rows(intervals: list[dict[str, Any]], now: datetime) -> list[dict[str, str]]:
    rows = []
    for interval in intervals:
        if interval.get("semantic_mapping_version") != MAPPING_VERSION or str(interval.get("pair_status") or "").upper() != "OPEN":
            continue
        event_time = _parse_time(interval.get("outage_at") or interval.get("updated_at"))
        if event_time is None or now - event_time <= timedelta(hours=24):
            continue
        raw_ref = str(interval.get("interval_ref") or interval.get("outage_request_ref") or "")
        seed = raw_ref + "|" + _format_time(event_time)
        rows.append({
            "case_ref": "case_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16],
            "event_time": _format_time(event_time),
            "age_hours": f"{(now - event_time).total_seconds() / 3600.0:.3f}",
            "classification": "missing_restore",
            "use_for_training": "FALSE",
            "use_for_evaluation": "FALSE",
            "use_for_context": "TRUE",
            "production_send": "blocked",
        })
    return rows


def _required_time(value: Any, label: str) -> datetime:
    parsed = _parse_time(value)
    if parsed is None:
        raise ValueError(f"{label} is required")
    return parsed


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _render_report(summary: dict[str, Any]) -> str:
    return (
        "# Prospective v2 Review Delta Gate\n\n"
        f"- gate status: `{summary['gate_status']}`\n"
        f"- comparison: `{summary['comparison_status']}`\n"
        f"- model-ready rows: `{summary['v2_model_ready_rows']}`\n"
        f"- open / stale: `{summary['v2_open_intervals']}` / `{summary['truth_stale_open_intervals']}`\n"
        f"- cumulative review rows: `{summary['truth_review_needed']}`\n"
        f"- deltas: `{json.dumps(summary['metric_deltas'], sort_keys=True)}`\n"
        f"- data window hours: `{summary['data_window_hours']}`\n"
        f"- seven-day re-evaluation due: `{str(summary['seven_day_re_evaluation_due']).lower()}`\n"
        "- cumulative review counts are not treated as new incidents without a positive delta\n"
        "- review and stale rows are context-only; excluded from train/evaluation/MAE/coverage/green incidents\n"
        "- mode: `shadow`; production_send: `blocked`\n"
    )
