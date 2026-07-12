from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .truth_quality import GATE_COVERAGE_MAX, GATE_COVERAGE_MIN


CHALLENGER_VERSION = "v2_available_history_quantiles_v1"
MIN_HISTORY_INCIDENTS = 12
TEST_BLOCK_INCIDENTS = 6
MIN_RESEARCH_INCIDENTS = 30
MIN_RESEARCH_WINDOW_DAYS = 7.0
RESEARCH_MAE_IMPROVEMENT_MIN = 0.20
HIGH_ERROR_MINUTES = 60.0
GREEN_ERROR_MAX = 16.0

PREDICTION_COLUMNS = (
    "incident_group_ref",
    "outage_anchor_time",
    "incident_prediction_created_at",
    "incident_target_available_at",
    "prior_completed_incidents",
    "candidate_status",
    "baseline_p50_minutes",
    "baseline_absolute_error_minutes",
    "challenger_p50_minutes",
    "challenger_q10_minutes",
    "challenger_q90_minutes",
    "challenger_absolute_error_minutes",
    "challenger_covered_q10_q90",
    "challenger_green_incident",
    "challenger_high_error_incident",
    "fold_id",
    "production_send",
)
FOLD_COLUMNS = (
    "fold_id",
    "test_incidents",
    "baseline_mae_minutes",
    "challenger_mae_minutes",
    "challenger_q10_q90_coverage",
    "baseline_green_incidents",
    "challenger_green_incidents",
    "baseline_high_error_incidents",
    "challenger_high_error_incidents",
    "production_send",
)


def build_v2_history_quantile_challenger(
    incidents_csv: str | Path,
    *,
    predictions_csv: str | Path,
    folds_csv: str | Path,
    summary_json: str | Path,
    report_md: str | Path,
    peacon_md: str | Path,
) -> dict[str, Any]:
    incidents = _load_incidents(Path(incidents_csv))
    predictions = _build_predictions(incidents)
    scored = [row for row in predictions if row["candidate_status"] == "history_quantile"]
    folds = _build_folds(scored)
    summary = _summary(incidents, predictions, scored, folds)

    _write_csv(Path(predictions_csv), PREDICTION_COLUMNS, predictions)
    _write_csv(Path(folds_csv), FOLD_COLUMNS, folds)
    Path(summary_json).parent.mkdir(parents=True, exist_ok=True)
    Path(summary_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    Path(report_md).parent.mkdir(parents=True, exist_ok=True)
    Path(report_md).write_text(_render_report(summary), encoding="utf-8")
    Path(peacon_md).parent.mkdir(parents=True, exist_ok=True)
    Path(peacon_md).write_text(_render_peacon(summary), encoding="utf-8")

    return {
        **summary,
        "predictions_csv": str(predictions_csv),
        "folds_csv": str(folds_csv),
        "summary_json": str(summary_json),
        "report_md": str(report_md),
        "peacon_md": str(peacon_md),
    }


def _load_incidents(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"incidents CSV not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    seen = set()
    incidents = []
    for row in rows:
        if row.get("production_send") != "blocked":
            raise ValueError("incident production_send must remain blocked")
        ref = str(row.get("incident_group_ref") or "").strip()
        if not ref.startswith("incident_") or len(ref) != len("incident_") + 16:
            raise ValueError("incident_group_ref must be a redacted incident reference")
        if ref in seen:
            raise ValueError("incident_group_ref must be unique")
        seen.add(ref)
        outage = _parse_time(row.get("outage_anchor_time"))
        prediction = _parse_time(row.get("incident_prediction_created_at"))
        target_available = _parse_time(row.get("incident_target_available_at"))
        actual = _number(row.get("actual_remaining_minutes"))
        baseline = _number(row.get("predicted_p50_minutes"))
        if None in (outage, prediction, target_available, actual, baseline):
            raise ValueError("incident requires valid timestamps, actual target, and baseline prediction")
        if prediction >= target_available:
            raise ValueError("incident prediction must be before target availability")
        if actual <= 0 or actual > 1440:
            raise ValueError("incident actual remaining target must be in (0, 1440]")
        incidents.append(
            {
                "ref": ref,
                "outage": outage,
                "prediction": prediction,
                "target_available": target_available,
                "actual": actual,
                "baseline": baseline,
            }
        )
    return sorted(incidents, key=lambda row: (row["prediction"], row["ref"]))


def _build_predictions(incidents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    scored_count = 0
    for incident in incidents:
        history = [row["actual"] for row in incidents if row["target_available"] <= incident["prediction"]]
        baseline_error = abs(incident["actual"] - incident["baseline"])
        row = {
            "incident_group_ref": incident["ref"],
            "outage_anchor_time": _format_time(incident["outage"]),
            "incident_prediction_created_at": _format_time(incident["prediction"]),
            "incident_target_available_at": _format_time(incident["target_available"]),
            "prior_completed_incidents": str(len(history)),
            "baseline_p50_minutes": _fmt(incident["baseline"]),
            "baseline_absolute_error_minutes": _fmt(baseline_error),
            "production_send": "blocked",
        }
        if len(history) < MIN_HISTORY_INCIDENTS:
            row.update(
                {
                    "candidate_status": "cold_start_fallback",
                    "challenger_p50_minutes": _fmt(incident["baseline"]),
                    "challenger_q10_minutes": "",
                    "challenger_q90_minutes": "",
                    "challenger_absolute_error_minutes": _fmt(baseline_error),
                    "challenger_covered_q10_q90": "",
                    "challenger_green_incident": "TRUE" if baseline_error <= GREEN_ERROR_MAX else "FALSE",
                    "challenger_high_error_incident": "TRUE" if baseline_error >= HIGH_ERROR_MINUTES else "FALSE",
                    "fold_id": "",
                }
            )
        else:
            p10, p50, p90 = (_quantile(history, point) for point in (0.10, 0.50, 0.90))
            error = abs(incident["actual"] - p50)
            scored_count += 1
            row.update(
                {
                    "candidate_status": "history_quantile",
                    "challenger_p50_minutes": _fmt(p50),
                    "challenger_q10_minutes": _fmt(p10),
                    "challenger_q90_minutes": _fmt(p90),
                    "challenger_absolute_error_minutes": _fmt(error),
                    "challenger_covered_q10_q90": "TRUE" if p10 <= incident["actual"] <= p90 else "FALSE",
                    "challenger_green_incident": "TRUE" if error <= GREEN_ERROR_MAX else "FALSE",
                    "challenger_high_error_incident": "TRUE" if error >= HIGH_ERROR_MINUTES else "FALSE",
                    "fold_id": f"wf_{((scored_count - 1) // TEST_BLOCK_INCIDENTS) + 1:02d}",
                }
            )
        rows.append(row)
    return rows


def _build_folds(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    folds = []
    for start in range(0, len(rows), TEST_BLOCK_INCIDENTS):
        block = rows[start : start + TEST_BLOCK_INCIDENTS]
        if len(block) < TEST_BLOCK_INCIDENTS:
            continue
        baseline_errors = [_number(row["baseline_absolute_error_minutes"]) for row in block]
        challenger_errors = [_number(row["challenger_absolute_error_minutes"]) for row in block]
        covered = [row["challenger_covered_q10_q90"] == "TRUE" for row in block]
        folds.append(
            {
                "fold_id": block[0]["fold_id"],
                "test_incidents": str(len(block)),
                "baseline_mae_minutes": _fmt(_mean(baseline_errors)),
                "challenger_mae_minutes": _fmt(_mean(challenger_errors)),
                "challenger_q10_q90_coverage": _fmt(sum(covered) / len(covered), digits=3),
                "baseline_green_incidents": str(sum(error <= GREEN_ERROR_MAX for error in baseline_errors)),
                "challenger_green_incidents": str(sum(row["challenger_green_incident"] == "TRUE" for row in block)),
                "baseline_high_error_incidents": str(sum(error >= HIGH_ERROR_MINUTES for error in baseline_errors)),
                "challenger_high_error_incidents": str(sum(row["challenger_high_error_incident"] == "TRUE" for row in block)),
                "production_send": "blocked",
            }
        )
    return folds


def _summary(incidents: list[dict[str, Any]], predictions: list[dict[str, str]], scored: list[dict[str, str]], folds: list[dict[str, str]]) -> dict[str, Any]:
    baseline_errors = [_number(row["baseline_absolute_error_minutes"]) for row in scored]
    challenger_errors = [_number(row["challenger_absolute_error_minutes"]) for row in scored]
    coverage = _coverage(scored)
    baseline_mae = _mean(baseline_errors)
    challenger_mae = _mean(challenger_errors)
    improvement = None if baseline_mae in (None, 0) or challenger_mae is None else (baseline_mae - challenger_mae) / baseline_mae
    window_days = 0.0
    if incidents:
        window_days = (incidents[-1]["prediction"] - incidents[0]["prediction"]).total_seconds() / 86400.0
    baseline_high = sum(error >= HIGH_ERROR_MINUTES for error in baseline_errors)
    challenger_high = sum(error >= HIGH_ERROR_MINUTES for error in challenger_errors)
    research_gate = _research_gate(len(scored), window_days, improvement, coverage, baseline_high, challenger_high)
    return {
        "challenger_version": CHALLENGER_VERSION,
        "policy": "available_completed_incident_history_quantiles",
        "minimum_history_incidents": MIN_HISTORY_INCIDENTS,
        "test_block_incidents": TEST_BLOCK_INCIDENTS,
        "source_incidents": len(incidents),
        "cold_start_incidents": sum(row["candidate_status"] == "cold_start_fallback" for row in predictions),
        "challenger_scored_incidents": len(scored),
        "complete_walk_forward_folds": len(folds),
        "data_window_days": round(window_days, 3),
        "baseline_mae_minutes": _round_or_none(baseline_mae),
        "challenger_mae_minutes": _round_or_none(challenger_mae),
        "mae_improvement_ratio": _round_or_none(improvement, digits=3),
        "challenger_q10_q90_coverage": _round_or_none(coverage, digits=3),
        "baseline_green_incidents": sum(error <= GREEN_ERROR_MAX for error in baseline_errors),
        "challenger_green_incidents": sum(error <= GREEN_ERROR_MAX for error in challenger_errors),
        "baseline_high_error_incidents": baseline_high,
        "challenger_high_error_incidents": challenger_high,
        "research_gate_status": research_gate,
        "research_metric_claim_allowed": research_gate == "research_pass_shadow_only",
        "production_gate_passed": False,
        "training_allowed": False,
        "runtime_model_changed": False,
        "production_send": "blocked",
        "context_sources": "excluded_gis_report52_topology_protection",
    }


def _research_gate(scored: int, window_days: float, improvement: float | None, coverage: float | None, baseline_high: int, challenger_high: int) -> str:
    if scored < MIN_RESEARCH_INCIDENTS:
        return "insufficient_challenger_scored_incidents"
    if improvement is None or improvement < 0:
        return "model_risk_confirmed_policy_harm"
    if challenger_high > baseline_high:
        return "model_risk_confirmed_high_error_regression"
    if window_days < MIN_RESEARCH_WINDOW_DAYS:
        return "research_window_too_short"
    if improvement is None or improvement < RESEARCH_MAE_IMPROVEMENT_MIN:
        return "model_risk_confirmed_no_material_mae_improvement"
    if coverage is None or not GATE_COVERAGE_MIN <= coverage <= GATE_COVERAGE_MAX:
        return "model_risk_confirmed_coverage"
    return "research_pass_shadow_only"


def _render_report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Prospective v2 History Quantile Challenger",
            "",
            f"- status: `{summary['research_gate_status']}`",
            f"- source independent incidents: `{summary['source_incidents']}`",
            f"- challenger-scored incidents: `{summary['challenger_scored_incidents']}`",
            f"- data window days: `{summary['data_window_days']}`",
            f"- baseline MAE: `{summary['baseline_mae_minutes']}` minutes",
            f"- challenger MAE: `{summary['challenger_mae_minutes']}` minutes",
            f"- MAE improvement: `{summary['mae_improvement_ratio']}`",
            f"- challenger q10-q90 coverage: `{summary['challenger_q10_q90_coverage']}`",
            f"- baseline/challenger high-error incidents: `{summary['baseline_high_error_incidents']}/{summary['challenger_high_error_incidents']}`",
            "- history policy: use only targets available before each prediction timestamp",
            "- GIS, Report52, topology, and protection context: excluded from this metric",
            "- runtime model changed: `false`",
            "- production_send: `blocked`",
            "",
        ]
    )


def _render_peacon(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# PEA-CON Quantile Challenger Update",
            "",
            "ระบบสำหรับลูกค้าสื่อสารรายสำคัญประเมิน challenger แบบ walk-forward โดยใช้เฉพาะผลการคืนไฟที่พร้อมใช้งานก่อนเวลา prediction ของเหตุถัดไป เพื่อป้องกัน time leakage.",
            f"ผลล่าสุดมี incident ที่ challenger ประเมินได้ {summary['challenger_scored_incidents']} เหตุการณ์ ภายใต้สถานะ `{summary['research_gate_status']}`.",
            "ผลนี้เป็นหลักฐาน model-risk control ใน shadow mode ไม่ใช่การอ้างว่า production-ready และ `production_send=blocked`.",
            "",
        ]
    )


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _quantile(values: list[float], point: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * point
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _coverage(rows: list[dict[str, str]]) -> float | None:
    if not rows:
        return None
    return sum(row["challenger_covered_q10_q90"] == "TRUE" for row in rows) / len(rows)


def _mean(values: list[float | None]) -> float | None:
    usable = [value for value in values if value is not None]
    return sum(usable) / len(usable) if usable else None


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _round_or_none(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _fmt(value: float | None, digits: int = 3) -> str:
    return "" if value is None else f"{value:.{digits}f}"
