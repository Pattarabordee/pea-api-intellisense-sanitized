from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from statistics import median
from typing import Any

from .ais_v2_lifecycle_audit import MAPPING_VERSION, _float_or_none, _get_json, _parse_time


MODEL_VERSION = "fixed_naive_60m_v1"
EVALUATOR_VERSION = "v2_baseline_eval_v1"
GROUP_COLUMNS = (
    "incident_group_ref",
    "outage_anchor_time",
    "meter_interval_count",
    "actual_remaining_minutes",
    "predicted_p50_minutes",
    "absolute_error_minutes",
    "worst_meter_absolute_error_minutes",
    "green_incident",
    "high_error_incident",
    "model_version",
    "production_send",
)


def run_v2_baseline_evaluation(
    *,
    base_url: str,
    output_csv: str | Path,
    summary_json: str | Path,
    report_md: str | Path,
    peacon_md: str | Path,
    registry_jsonl: str | Path,
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
    return build_v2_baseline_evaluation(
        metrics,
        requests.get("items") or [],
        intervals.get("items") or [],
        output_csv=output_csv,
        summary_json=summary_json,
        report_md=report_md,
        peacon_md=peacon_md,
        registry_jsonl=registry_jsonl,
    )


def build_v2_baseline_evaluation(
    metrics: dict[str, Any],
    items: list[dict[str, Any]],
    intervals: list[dict[str, Any]],
    *,
    output_csv: str | Path,
    summary_json: str | Path,
    report_md: str | Path,
    peacon_md: str | Path,
    registry_jsonl: str | Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    if metrics.get("production_send") != "blocked":
        raise ValueError("production_send must remain blocked")
    request_index = {str(item.get("request_ref") or "").strip(): item for item in items}
    candidates = []
    rejection_counts = {
        "excluded_non_v2_audit": 0,
        "not_clean_v2_interval": 0,
        "missing_outage_request": 0,
        "missing_numeric_prediction": 0,
        "wrong_model_version": 0,
        "prediction_time_leakage": 0,
        "invalid_remaining_target": 0,
        "missing_outage_time": 0,
    }
    for row in intervals:
        if row.get("semantic_mapping_version") != MAPPING_VERSION:
            rejection_counts["excluded_non_v2_audit"] += 1
            continue
        duration = _float_or_none(row.get("duration_minutes"))
        clean = (
            row.get("pair_status") == "CLOSED"
            and row.get("bridge_status") == "METER_STATE_MODEL_READY"
            and duration is not None
            and 5 < duration <= 1440
        )
        if not clean:
            rejection_counts["not_clean_v2_interval"] += 1
            continue
        outage_ref = str(row.get("outage_request_ref") or "").strip()
        item = request_index.get(outage_ref)
        if item is None:
            rejection_counts["missing_outage_request"] += 1
            continue
        etr = ((item.get("result") or {}).get("etr") or {})
        p50 = _float_or_none(etr.get("p50_minutes"))
        if p50 is None:
            rejection_counts["missing_numeric_prediction"] += 1
            continue
        if str(etr.get("model_version") or "") != MODEL_VERSION:
            rejection_counts["wrong_model_version"] += 1
            continue
        prediction_time = _parse_time(etr.get("prediction_created_at"))
        restore_time = _parse_time(row.get("restore_at"))
        outage_time = _parse_time(row.get("outage_at"))
        if prediction_time is None or restore_time is None or prediction_time >= restore_time:
            rejection_counts["prediction_time_leakage"] += 1
            continue
        if outage_time is None:
            rejection_counts["missing_outage_time"] += 1
            continue
        actual = (restore_time - prediction_time).total_seconds() / 60.0
        if not 0 < actual <= 1440:
            rejection_counts["invalid_remaining_target"] += 1
            continue
        candidates.append(
            {
                "outage_ref": outage_ref,
                "outage_time": outage_time,
                "actual": actual,
                "p50": p50,
            }
        )

    groups = _group_predictions(candidates)
    errors = [float(row["absolute_error_minutes"]) for row in groups]
    worst_errors = [float(row["worst_meter_absolute_error_minutes"]) for row in groups]
    mae = sum(errors) / len(errors) if errors else None
    median_ae = median(errors) if errors else None
    p90_ae = _nearest_rank(errors, 0.90) if errors else None
    green = sum(1 for row in groups if row["green_incident"] == "TRUE")
    high_error = sum(1 for row in groups if row["high_error_incident"] == "TRUE")
    if not groups:
        gate_status = "awaiting_first_scorable_incident"
    elif len(groups) < 30:
        gate_status = "research_baseline_accumulating"
    else:
        gate_status = "baseline_interval_coverage_unavailable"

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=GROUP_COLUMNS)
        writer.writeheader()
        writer.writerows(groups)

    group_artifact_sha256 = _sha256_file(output)
    metric_semantics = {
        "target": "restore_at_minus_prediction_created_at",
        "incident_grouping": "fixed_anchor_5_minutes",
        "incident_point_metric": "median_actual_vs_median_p50_absolute_error",
        "worst_meter_guardrail": "max_member_absolute_error",
        "green_threshold_minutes": 16,
        "high_error_threshold_minutes": 60,
        "coverage": "unavailable_no_q10_q90_baseline",
    }
    evaluation_seed = MODEL_VERSION + "|" + EVALUATOR_VERSION + "|" + group_artifact_sha256 + "|" + json.dumps(metric_semantics, sort_keys=True)
    evaluation_id = "eval_" + hashlib.sha256(evaluation_seed.encode("utf-8")).hexdigest()[:20]

    summary = {
        "gate_status": gate_status,
        "evaluation_id": evaluation_id,
        "evaluator_version": EVALUATOR_VERSION,
        "model_version": MODEL_VERSION,
        "clean_interval_candidates": sum(
            1
            for row in intervals
            if row.get("semantic_mapping_version") == MAPPING_VERSION
            and row.get("pair_status") == "CLOSED"
            and row.get("bridge_status") == "METER_STATE_MODEL_READY"
        ),
        "scorable_meter_rows": len(candidates),
        "scorable_independent_incidents": len(groups),
        "mae_minutes": round(mae, 3) if mae is not None else None,
        "median_absolute_error_minutes": round(median_ae, 3) if median_ae is not None else None,
        "p90_absolute_error_minutes": round(p90_ae, 3) if p90_ae is not None else None,
        "mean_worst_meter_absolute_error_minutes": round(sum(worst_errors) / len(worst_errors), 3) if worst_errors else None,
        "green_incidents": green,
        "high_error_incidents": high_error,
        "coverage": None,
        "coverage_status": "unavailable_no_q10_q90_baseline",
        "metric_semantics": metric_semantics,
        "group_artifact_sha256": group_artifact_sha256,
        "rejection_counts": rejection_counts,
        "minimum_independent_incidents": 30,
        "production_gate_passed": False,
        "training_allowed": False,
        "production_send": "blocked",
        "output_csv": str(output),
        "report_md": str(report_md),
        "peacon_md": str(peacon_md),
        "registry_jsonl": str(registry_jsonl),
    }
    registry_entry = {
        "evaluation_id": evaluation_id,
        "registered_at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "evaluator_version": EVALUATOR_VERSION,
        "model_version": MODEL_VERSION,
        "group_artifact_sha256": group_artifact_sha256,
        "data_window_start": groups[0]["outage_anchor_time"] if groups else "",
        "data_window_end": groups[-1]["outage_anchor_time"] if groups else "",
        "scorable_independent_incidents": len(groups),
        "mae_minutes": summary["mae_minutes"],
        "median_absolute_error_minutes": summary["median_absolute_error_minutes"],
        "p90_absolute_error_minutes": summary["p90_absolute_error_minutes"],
        "mean_worst_meter_absolute_error_minutes": summary["mean_worst_meter_absolute_error_minutes"],
        "green_incidents": green,
        "high_error_incidents": high_error,
        "coverage_status": summary["coverage_status"],
        "gate_status": gate_status,
        "metric_semantics": metric_semantics,
        "production_send": "blocked",
    }
    registry_added = _append_registry_once(Path(registry_jsonl), registry_entry)
    summary["registry_entry_added"] = registry_added
    summary_path = Path(summary_json)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report = Path(report_md)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "# Prospective v2 Fixed Baseline Evaluation\n\n"
        f"- สถานะ: `{gate_status}`\n"
        f"- scorable meter rows: `{len(candidates)}`\n"
        f"- scorable independent incidents: `{len(groups)}`\n"
        f"- MAE: `{summary['mae_minutes']}` นาที\n"
        f"- median AE: `{summary['median_absolute_error_minutes']}` นาที\n"
        f"- p90 AE: `{summary['p90_absolute_error_minutes']}` นาที\n"
        f"- green incidents (AE <= 16): `{green}`\n"
        f"- high-error incidents (worst meter AE >= 60): `{high_error}`\n"
        f"- mean worst-meter AE: `{summary['mean_worst_meter_absolute_error_minutes']}` นาที\n"
        "- coverage: `unavailable_no_q10_q90_baseline`\n"
        "- high-error clean incidents: retained\n"
        "- production_send: `blocked`\n",
        encoding="utf-8",
    )
    peacon = Path(peacon_md)
    peacon.parent.mkdir(parents=True, exist_ok=True)
    peacon.write_text(
        "# PEA-CON Prospective Baseline Evaluation Update\n\n"
        "ระบบสำหรับลูกค้าสื่อสารรายสำคัญประเมิน benchmark เฉพาะเหตุการณ์ที่มี prediction snapshot ก่อน RESTORE "
        "และรวม meter rows ที่เริ่มใกล้กันภายใน 5 นาทีเป็นเหตุการณ์อิสระเดียว ข้อมูลที่ไม่มี prediction หรือมีความเสี่ยง "
        "ด้าน time leakage จะไม่ถูกคำนวณย้อนหลัง เหตุการณ์ที่ error สูงแต่ truth สะอาดยังคงอยู่ในผลประเมิน "
        "โดย coverage ยังไม่รายงานจนกว่าจะมี q10/q90 baseline และ `production_send=blocked`\n",
        encoding="utf-8",
    )
    return summary


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _append_registry_once(path: Path, entry: dict[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            existing_ids.add(str(payload.get("evaluation_id") or ""))
    if entry["evaluation_id"] in existing_ids:
        return False
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return True


def _group_predictions(candidates: list[dict[str, Any]], window_minutes: float = 5.0) -> list[dict[str, Any]]:
    grouped: list[list[dict[str, Any]]] = []
    for candidate in sorted(candidates, key=lambda row: (row["outage_time"], row["outage_ref"])):
        if not grouped or (candidate["outage_time"] - grouped[-1][0]["outage_time"]).total_seconds() > window_minutes * 60:
            grouped.append([candidate])
        else:
            grouped[-1].append(candidate)
    rows = []
    for group in grouped:
        anchor: datetime = group[0]["outage_time"]
        actual = float(median(row["actual"] for row in group))
        p50 = float(median(row["p50"] for row in group))
        error = abs(actual - p50)
        worst_error = max(abs(float(row["actual"]) - float(row["p50"])) for row in group)
        seed = anchor.isoformat() + "|" + "|".join(sorted(row["outage_ref"] for row in group))
        rows.append(
            {
                "incident_group_ref": "incident_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16],
                "outage_anchor_time": anchor.isoformat().replace("+00:00", "Z"),
                "meter_interval_count": len(group),
                "actual_remaining_minutes": round(actual, 3),
                "predicted_p50_minutes": round(p50, 3),
                "absolute_error_minutes": round(error, 3),
                "worst_meter_absolute_error_minutes": round(worst_error, 3),
                "green_incident": "TRUE" if error <= 16 else "FALSE",
                "high_error_incident": "TRUE" if worst_error >= 60 else "FALSE",
                "model_version": MODEL_VERSION,
                "production_send": "blocked",
            }
        )
    return rows


def _nearest_rank(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    rank = max(1, int(len(ordered) * quantile + 0.999999))
    return ordered[min(rank - 1, len(ordered) - 1)]
