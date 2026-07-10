from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


OUTPUT_COLUMNS = (
    "signal_field",
    "signal_value",
    "signal_value_ref",
    "event_type",
    "event_type_source",
    "validation_status",
    "count",
    "use_for_training",
    "production_send",
)
RESTORE_CANDIDATE_VALUES = {
    "clear",
    "cleared",
    "normal",
    "on",
    "power_on",
    "recover",
    "recovered",
    "restore",
    "restored",
}
RESTORE_ALARM_TYPE_CANDIDATES = {"AC_MAIN_RESTORE"}


def run_event_semantic_audit(
    *,
    base_url: str,
    output_csv: str | Path,
    report_md: str | Path,
    api_key: str | None = None,
    limit: int = 200,
    minimum_requests: int = 100,
    minimum_days: int = 7,
) -> dict[str, Any]:
    key = str(api_key or os.environ.get("AIS_INBOUND_API_KEY") or "").strip()
    if not key:
        raise ValueError("AIS_INBOUND_API_KEY is required")
    root = base_url.rstrip("/")
    metrics = _get_json(root + "/metrics", key)
    requests = _get_json(
        root + f"/api/v1/ais/outage-verifications?view=operator&limit={max(1, min(limit, 200))}",
        key,
    )
    return build_event_semantic_audit(
        metrics,
        requests.get("items") or [],
        output_csv=output_csv,
        report_md=report_md,
        minimum_requests=minimum_requests,
        minimum_days=minimum_days,
    )


def build_event_semantic_audit(
    metrics: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    output_csv: str | Path,
    report_md: str | Path,
    minimum_requests: int = 100,
    minimum_days: int = 7,
    now: datetime | None = None,
) -> dict[str, Any]:
    if metrics.get("production_send") != "blocked":
        raise ValueError("production_send must remain blocked")

    aggregates: Counter[tuple[str, str, str, str, str, str]] = Counter()
    event_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    validation_counts: Counter[str] = Counter()
    received_times: list[datetime] = []
    restore_candidates = 0

    captured_items = [item for item in items if item.get("semantic_capture_version") == "v1"]
    for item in captured_items:
        truth = item.get("truth_observation") or {}
        event_type = str(truth.get("event_type") or "UNKNOWN").strip().upper()
        event_source = str(truth.get("event_type_source") or "missing").strip()
        validation = str(truth.get("validation_status") or "REVIEW_EVENT_TYPE").strip()
        event_counts[event_type] += 1
        source_counts[event_source] += 1
        validation_counts[validation] += 1
        received = _parse_time(item.get("received_at"))
        if received:
            received_times.append(received)

        signals = item.get("semantic_signals") or {}
        for field, raw_signal in sorted(signals.items()):
            if not isinstance(raw_signal, dict):
                continue
            value = str(raw_signal.get("value") or "").strip()
            value_ref = str(raw_signal.get("value_ref") or "").strip()
            aggregates[(field, value, value_ref, event_type, event_source, validation)] += 1
            if field in {"alarm_status", "event_status", "power_status", "status"} and value.lower() in RESTORE_CANDIDATE_VALUES:
                restore_candidates += 1
            if field == "alarm_type" and value.upper() in RESTORE_ALARM_TYPE_CANDIDATES:
                restore_candidates += 1

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    observation_days = 0.0
    if received_times:
        observation_days = max(0.0, (current - min(received_times)).total_seconds() / 86400.0)
    observation_complete = len(captured_items) >= minimum_requests or observation_days >= minimum_days
    mapped_outages = event_counts["OUTAGE"]
    mapped_restores = event_counts["RESTORE"]
    model_ready = int(metrics.get("model_ready_clean_truth_rows") or 0)

    if mapped_outages > 0 and mapped_restores > 0 and model_ready > 0:
        gate_status = "semantic_mapping_ready"
    elif observation_complete and mapped_restores == 0 and restore_candidates > 0:
        gate_status = "restore_candidate_review_required"
    elif observation_complete and mapped_restores == 0:
        gate_status = "restore_signal_missing"
    else:
        gate_status = "insufficient_semantic_observations"

    rows = [
        {
            "signal_field": key[0],
            "signal_value": key[1],
            "signal_value_ref": key[2],
            "event_type": key[3],
            "event_type_source": key[4],
            "validation_status": key[5],
            "count": count,
            "use_for_training": "FALSE",
            "production_send": "blocked",
        }
        for key, count in sorted(aggregates.items())
    ]
    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    report = Path(report_md)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "# AIS Event Semantic Audit\n\n"
        "- วิธีรัน: one-shot และใช้ authenticated GET เท่านั้น\n"
        f"- สถานะ gate: `{gate_status}`\n"
        f"- request หลัง semantic capture v1: `{len(captured_items)}`\n"
        f"- ช่วงเวลาที่สังเกต: `{observation_days:.2f}` วัน\n"
        f"- OUTAGE ที่ map ได้: `{mapped_outages}`\n"
        f"- RESTORE ที่ map ได้: `{mapped_restores}`\n"
        f"- restore candidate ที่ยังต้อง review: `{restore_candidates}`\n"
        f"- open meter-state interval: `{int(metrics.get('truth_meter_state_open_intervals') or 0)}`\n"
        f"- stale open interval (>24h): `{int(metrics.get('truth_stale_open_intervals') or 0)}`\n"
        f"- model-ready interval: `{model_ready}`\n"
        "- ใช้ train/evaluation: `FALSE`\n"
        "- production_send: `blocked`\n\n"
        "ข้อมูลในรายงานนี้เป็น aggregate semantic evidence เท่านั้น ไม่มีเลขมิเตอร์หรือรหัสเหตุการณ์ดิบ\n",
        encoding="utf-8",
    )
    return {
        "gate_status": gate_status,
        "observed_requests": len(captured_items),
        "observation_days": round(observation_days, 3),
        "event_type_counts": dict(sorted(event_counts.items())),
        "event_type_source_counts": dict(sorted(source_counts.items())),
        "validation_counts": dict(sorted(validation_counts.items())),
        "restore_candidate_count": restore_candidates,
        "model_ready_clean_truth_rows": model_ready,
        "output_csv": str(output),
        "report_md": str(report),
        "production_send": "blocked",
    }


def _get_json(url: str, api_key: str) -> dict[str, Any]:
    request = Request(url, method="GET", headers={"X-API-Key": api_key, "Accept": "application/json"})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
