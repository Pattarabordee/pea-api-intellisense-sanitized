from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .ais_v2_lifecycle_audit import MAPPING_VERSION, _float_or_none, _get_json, _parse_time


AUDIT_COLUMNS = (
    "case_ref",
    "source_latency_minutes",
    "timeliness_class",
    "production_send",
)


def run_v2_source_latency_audit(
    *,
    base_url: str,
    output_csv: str | Path,
    summary_json: str | Path,
    report_md: str | Path,
    peacon_md: str | Path,
    api_key: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    key = str(api_key or os.environ.get("AIS_INBOUND_API_KEY") or "").strip()
    if not key:
        raise ValueError("AIS_INBOUND_API_KEY is required")
    root = base_url.rstrip("/")
    metrics = _get_json(root + "/metrics", key)
    requests = _get_json(
        root + f"/api/v1/ais/outage-verifications?view=operator&limit={max(1, min(limit, 200))}", key
    )
    intervals = _get_json(
        root + f"/api/v1/ais/truth-intervals?status=ALL&limit={max(1, min(limit, 200))}", key
    )
    for label, payload in (("metrics", metrics), ("requests", requests), ("intervals", intervals)):
        if payload.get("production_send") != "blocked":
            raise ValueError(f"{label} production_send must remain blocked")
    return build_v2_source_latency_audit(
        metrics,
        requests.get("items") or [],
        intervals.get("items") or [],
        output_csv=output_csv,
        summary_json=summary_json,
        report_md=report_md,
        peacon_md=peacon_md,
    )


def build_v2_source_latency_audit(
    metrics: dict[str, Any],
    items: list[dict[str, Any]],
    intervals: list[dict[str, Any]],
    *,
    output_csv: str | Path,
    summary_json: str | Path,
    report_md: str | Path,
    peacon_md: str | Path,
) -> dict[str, Any]:
    if metrics.get("production_send") != "blocked":
        raise ValueError("production_send must remain blocked")
    request_index = {str(item.get("request_ref") or "").strip(): item for item in items}
    rows = []
    counts = {
        "clean_intervals": 0,
        "missing_outage_request": 0,
        "missing_numeric_prediction": 0,
        "invalid_timestamp": 0,
        "active_at_prediction": 0,
        "post_restore_at_prediction": 0,
    }
    active_latencies = []
    all_latencies = []
    for interval in intervals:
        if not _is_clean_v2_interval(interval):
            continue
        counts["clean_intervals"] += 1
        outage_ref = str(interval.get("outage_request_ref") or "").strip()
        item = request_index.get(outage_ref)
        if item is None:
            counts["missing_outage_request"] += 1
            continue
        etr = ((item.get("result") or {}).get("etr") or {})
        if _float_or_none(etr.get("p50_minutes")) is None:
            counts["missing_numeric_prediction"] += 1
            continue
        outage_time = _parse_time(interval.get("outage_at"))
        restore_time = _parse_time(interval.get("restore_at"))
        prediction_time = _parse_time(etr.get("prediction_created_at"))
        if outage_time is None or restore_time is None or prediction_time is None:
            counts["invalid_timestamp"] += 1
            continue
        latency_minutes = (prediction_time - outage_time).total_seconds() / 60.0
        if latency_minutes < 0:
            counts["invalid_timestamp"] += 1
            continue
        timeliness_class = "active_at_prediction" if prediction_time < restore_time else "post_restore_at_prediction"
        counts[timeliness_class] += 1
        all_latencies.append(latency_minutes)
        if timeliness_class == "active_at_prediction":
            active_latencies.append(latency_minutes)
        rows.append(
            {
                "case_ref": _case_ref(outage_ref),
                "source_latency_minutes": round(latency_minutes, 3),
                "timeliness_class": timeliness_class,
                "production_send": "blocked",
            }
        )

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    latency_summary = _latency_summary(active_latencies)
    all_latency_summary = _latency_summary(all_latencies)
    summary = {
        "semantic_mapping_version": MAPPING_VERSION,
        "counts": counts,
        "active_prediction_latency_minutes": latency_summary,
        "all_numeric_prediction_latency_minutes": all_latency_summary,
        "source_latency_review_required": counts["post_restore_at_prediction"] > 0,
        "source_latency_threshold_configured": False,
        "training_allowed": False,
        "production_send": "blocked",
        "output_csv": str(output),
        "report_md": str(report_md),
        "peacon_md": str(peacon_md),
    }
    summary_path = Path(summary_json)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report = Path(report_md)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "# Prospective AIS Source-Latency Audit\n\n"
        "- Scope: clean v2 meter-state intervals with numeric pre-registered baseline snapshots\n"
        f"- clean intervals: `{counts['clean_intervals']}`\n"
        f"- active at prediction: `{counts['active_at_prediction']}`\n"
        f"- post-restore at prediction: `{counts['post_restore_at_prediction']}`\n"
        f"- active-prediction latency p50: `{latency_summary['p50_minutes']}` minutes\n"
        f"- active-prediction latency p90: `{latency_summary['p90_minutes']}` minutes\n"
        f"- active-prediction latency max: `{latency_summary['max_minutes']}` minutes\n"
        "- no latency threshold is configured; this report is evidence, not an automatic rejection rule\n"
        "- production_send: `blocked`\n",
        encoding="utf-8",
    )
    peacon = Path(peacon_md)
    peacon.parent.mkdir(parents=True, exist_ok=True)
    peacon.write_text(
        "# PEA-CON Source-Timeliness Governance Update\n\n"
        "ระบบสำหรับลูกค้าสื่อสารรายสำคัญแยกความคลาดเคลื่อนของโมเดลออกจากความหน่วงของข้อมูลต้นทาง "
        "โดยวัดเวลาระหว่าง outage timestamp กับเวลาสร้าง prediction และแยกกรณีที่ข้อมูล OUTAGE เข้าระบบหลัง RESTORE "
        "ออกเป็น operational review ข้อมูลดังกล่าวไม่ถูกนำไปทำให้ผลประเมินดูดีขึ้น และ `production_send=blocked`\n",
        encoding="utf-8",
    )
    return summary


def _is_clean_v2_interval(row: dict[str, Any]) -> bool:
    duration = _float_or_none(row.get("duration_minutes"))
    return (
        row.get("semantic_mapping_version") == MAPPING_VERSION
        and row.get("pair_status") == "CLOSED"
        and row.get("bridge_status") == "METER_STATE_MODEL_READY"
        and duration is not None
        and 5 < duration <= 1440
    )


def _latency_summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p50_minutes": None, "p90_minutes": None, "max_minutes": None}
    ordered = sorted(values)
    return {
        "p50_minutes": round(_nearest_rank(ordered, 0.50), 3),
        "p90_minutes": round(_nearest_rank(ordered, 0.90), 3),
        "max_minutes": round(max(ordered), 3),
    }


def _nearest_rank(values: list[float], quantile: float) -> float:
    rank = max(1, int(len(values) * quantile + 0.999999))
    return values[min(rank - 1, len(values) - 1)]


def _case_ref(outage_ref: str) -> str:
    return "latency_" + hashlib.sha256(outage_ref.encode("utf-8")).hexdigest()[:16]
