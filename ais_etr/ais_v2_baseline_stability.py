from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import median
from typing import Any


MINIMUM_INCIDENTS = 30
MINIMUM_TRAIN_INCIDENTS = 12
TEST_BLOCK_INCIDENTS = 6
FOLD_COLUMNS = (
    "fold_id",
    "train_incidents",
    "test_incidents",
    "test_start_time",
    "test_end_time",
    "mae_minutes",
    "median_absolute_error_minutes",
    "p90_absolute_error_minutes",
    "mean_worst_meter_absolute_error_minutes",
    "green_incidents",
    "high_error_incidents",
    "production_send",
)


def build_v2_baseline_stability_gate(
    incidents_csv: str | Path,
    *,
    output_csv: str | Path,
    summary_json: str | Path,
    report_md: str | Path,
    peacon_md: str | Path,
) -> dict[str, Any]:
    incidents = _load_incidents(Path(incidents_csv))
    folds = _build_folds(incidents)
    sufficient = len(incidents) >= MINIMUM_INCIDENTS
    complete_folds = len(folds)
    if not sufficient:
        gate_status = "insufficient_independent_incidents"
    elif complete_folds < 3:
        gate_status = "insufficient_complete_walk_forward_folds"
    else:
        gate_status = "baseline_stability_observed_not_production_ready"

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FOLD_COLUMNS)
        writer.writeheader()
        writer.writerows(folds)

    aggregate = _aggregate_folds(folds)
    summary = {
        "gate_status": gate_status,
        "scorable_independent_incidents": len(incidents),
        "minimum_independent_incidents": MINIMUM_INCIDENTS,
        "minimum_train_incidents": MINIMUM_TRAIN_INCIDENTS,
        "test_block_incidents": TEST_BLOCK_INCIDENTS,
        "complete_walk_forward_folds": complete_folds,
        "stability_assessed": sufficient and complete_folds >= 3,
        "stability_is_production_evidence": False,
        "aggregate": aggregate,
        "coverage_status": "unavailable_no_q10_q90_baseline",
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
        "# Prospective v2 Baseline Stability Gate\n\n"
        "- Method: fixed chronological walk-forward folds, pre-registered before scoring\n"
        f"- gate status: `{gate_status}`\n"
        f"- independent incidents: `{len(incidents)}` / `{MINIMUM_INCIDENTS}`\n"
        f"- complete folds: `{complete_folds}`\n"
        f"- aggregate MAE: `{aggregate['mae_minutes']}` minutes\n"
        f"- aggregate p90 AE: `{aggregate['p90_absolute_error_minutes']}` minutes\n"
        "- coverage: `unavailable_no_q10_q90_baseline`\n"
        "- no model training, tuning, or promotion occurred\n"
        "- production_send: `blocked`\n",
        encoding="utf-8",
    )
    peacon = Path(peacon_md)
    peacon.parent.mkdir(parents=True, exist_ok=True)
    peacon.write_text(
        "# PEA-CON Stability-Gate Update\n\n"
        "ระบบสำหรับลูกค้าสื่อสารรายสำคัญกำหนดการตรวจความเสถียรแบบ walk-forward ล่วงหน้า "
        "โดยเรียงเหตุการณ์อิสระตามเวลา ใช้ข้อมูลอดีตก่อนแต่ละช่วงทดสอบ และไม่ปรับพารามิเตอร์จากผลของช่วงทดสอบ "
        f"ปัจจุบันมี {len(incidents)} เหตุการณ์อิสระ จึงมีสถานะ `{gate_status}` "
        "ผลนี้เป็นหลักฐานการควบคุมความเสี่ยงของโมเดล ไม่ใช่การยืนยันว่าโมเดลพร้อมใช้งานจริง และ `production_send=blocked`\n",
        encoding="utf-8",
    )
    return summary


def _load_incidents(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"incidents CSV not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    seen_refs = set()
    incidents = []
    for row in rows:
        if str(row.get("production_send") or "") != "blocked":
            raise ValueError("incident production_send must remain blocked")
        ref = str(row.get("incident_group_ref") or "").strip()
        if not ref or ref in seen_refs:
            raise ValueError("incident_group_ref must be unique")
        seen_refs.add(ref)
        event_time = _parse_time(row.get("outage_anchor_time"))
        error = _float(row.get("absolute_error_minutes"))
        worst_error = _float(row.get("worst_meter_absolute_error_minutes"))
        if event_time is None or error is None or worst_error is None:
            raise ValueError("incident requires valid time and error metrics")
        incidents.append({"event_time": event_time, "error": error, "worst_error": worst_error})
    return sorted(incidents, key=lambda row: row["event_time"])


def _build_folds(incidents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(incidents) < MINIMUM_INCIDENTS:
        return []
    folds = []
    fold_number = 1
    test_start = MINIMUM_TRAIN_INCIDENTS
    while test_start + TEST_BLOCK_INCIDENTS <= len(incidents):
        test_rows = incidents[test_start : test_start + TEST_BLOCK_INCIDENTS]
        errors = [row["error"] for row in test_rows]
        worst_errors = [row["worst_error"] for row in test_rows]
        folds.append(
            {
                "fold_id": f"wf_{fold_number:02d}",
                "train_incidents": test_start,
                "test_incidents": len(test_rows),
                "test_start_time": _format_time(test_rows[0]["event_time"]),
                "test_end_time": _format_time(test_rows[-1]["event_time"]),
                "mae_minutes": round(sum(errors) / len(errors), 3),
                "median_absolute_error_minutes": round(float(median(errors)), 3),
                "p90_absolute_error_minutes": round(_nearest_rank(errors, 0.90), 3),
                "mean_worst_meter_absolute_error_minutes": round(sum(worst_errors) / len(worst_errors), 3),
                "green_incidents": sum(1 for value in errors if value <= 16),
                "high_error_incidents": sum(1 for value in worst_errors if value >= 60),
                "production_send": "blocked",
            }
        )
        fold_number += 1
        test_start += TEST_BLOCK_INCIDENTS
    return folds


def _aggregate_folds(folds: list[dict[str, Any]]) -> dict[str, float | int | None]:
    if not folds:
        return {
            "mae_minutes": None,
            "median_absolute_error_minutes": None,
            "p90_absolute_error_minutes": None,
            "mean_worst_meter_absolute_error_minutes": None,
            "green_incidents": 0,
            "high_error_incidents": 0,
        }
    total_tests = sum(int(row["test_incidents"]) for row in folds)
    return {
        "mae_minutes": round(sum(float(row["mae_minutes"]) * int(row["test_incidents"]) for row in folds) / total_tests, 3),
        "median_absolute_error_minutes": round(float(median(float(row["median_absolute_error_minutes"]) for row in folds)), 3),
        "p90_absolute_error_minutes": round(max(float(row["p90_absolute_error_minutes"]) for row in folds), 3),
        "mean_worst_meter_absolute_error_minutes": round(
            sum(float(row["mean_worst_meter_absolute_error_minutes"]) * int(row["test_incidents"]) for row in folds)
            / total_tests,
            3,
        ),
        "green_incidents": sum(int(row["green_incidents"]) for row in folds),
        "high_error_incidents": sum(int(row["high_error_incidents"]) for row in folds),
    }


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nearest_rank(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    rank = max(1, int(len(ordered) * quantile + 0.999999))
    return ordered[min(rank - 1, len(ordered) - 1)]
