from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ais_v2_baseline_evaluation import run_v2_baseline_evaluation
from .ais_v2_baseline_stability import build_v2_baseline_stability_gate
from .ais_v2_history_quantile_challenger import build_v2_history_quantile_challenger
from .ais_v2_review_delta import run_v2_review_delta


MAE_GATE_MINUTES = 16.0
COVERAGE_MIN = 0.75
COVERAGE_MAX = 0.90
MIN_GREEN_INCIDENTS = 30


def run_v2_seven_day_regate(
    *,
    base_url: str,
    output_dir: str | Path,
    history_jsonl: str | Path,
    api_key: str | None = None,
) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    delta = run_v2_review_delta(
        base_url=base_url,
        history_jsonl=history_jsonl,
        delta_csv=root / "review_delta.csv",
        summary_json=root / "review_delta_summary.json",
        report_md=root / "review_delta_report.md",
        missing_restore_csv=root / "missing_restore_queue.csv",
        api_key=api_key,
    )
    if not delta["seven_day_re_evaluation_due"]:
        result = build_seven_day_decision(delta=delta)
        return _write_decision(root, result)

    baseline = run_v2_baseline_evaluation(
        base_url=base_url,
        output_csv=root / "baseline_incidents.csv",
        summary_json=root / "baseline_summary.json",
        report_md=root / "baseline_report.md",
        peacon_md=root / "peacon_baseline_update.md",
        registry_jsonl=root / "baseline_registry.jsonl",
        rejection_csv=root / "baseline_target_time_rejections.csv",
        api_key=api_key,
    )
    challenger = build_v2_history_quantile_challenger(
        root / "baseline_incidents.csv",
        predictions_csv=root / "history_challenger_predictions.csv",
        folds_csv=root / "history_challenger_folds.csv",
        summary_json=root / "history_challenger_summary.json",
        report_md=root / "history_challenger_report.md",
        peacon_md=root / "peacon_history_challenger_update.md",
    )
    stability = build_v2_baseline_stability_gate(
        root / "baseline_incidents.csv",
        output_csv=root / "baseline_stability_folds.csv",
        summary_json=root / "baseline_stability_summary.json",
        report_md=root / "baseline_stability_report.md",
        peacon_md=root / "peacon_baseline_stability.md",
    )
    result = build_seven_day_decision(delta=delta, baseline=baseline, challenger=challenger, stability=stability)
    return _write_decision(root, result)


def build_seven_day_decision(
    *,
    delta: dict[str, Any],
    baseline: dict[str, Any] | None = None,
    challenger: dict[str, Any] | None = None,
    stability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if delta.get("production_send") != "blocked":
        raise ValueError("production_send must remain blocked")
    due = bool(delta.get("seven_day_re_evaluation_due"))
    if not due:
        return {
            "gate_status": "waiting_for_seven_day_window",
            "data_window_hours": delta.get("data_window_hours"),
            "review_delta_status": delta.get("gate_status"),
            "re_evaluation_executed": False,
            "feature_sufficiency_audit_required": False,
            "interval_calibration_review_required": False,
            "history_only_policy_action": "evaluate_only_never_tune_or_promote",
            "production_gate_passed": False,
            "mode": "shadow",
            "production_send": "blocked",
        }
    if not all((baseline, challenger, stability)):
        raise ValueError("due re-evaluation requires baseline, challenger, and stability summaries")
    for label, payload in (("baseline", baseline), ("challenger", challenger), ("stability", stability)):
        if payload.get("production_send") != "blocked":
            raise ValueError(f"{label} production_send must remain blocked")

    baseline_mae = _number(baseline.get("mae_minutes"))
    challenger_mae = _number(challenger.get("challenger_mae_minutes"))
    coverage = _number(challenger.get("challenger_q10_q90_coverage"))
    baseline_green = _integer(challenger.get("baseline_green_incidents"))
    challenger_green = _integer(challenger.get("challenger_green_incidents"))
    baseline_high = _integer(challenger.get("baseline_high_error_incidents"))
    challenger_high = _integer(challenger.get("challenger_high_error_incidents"))
    policy_harm = challenger_green < baseline_green or challenger_high > baseline_high
    mae_failed = baseline_mae is None or baseline_mae > MAE_GATE_MINUTES
    coverage_failed = coverage is None or not COVERAGE_MIN <= coverage <= COVERAGE_MAX
    green_failed = _integer(baseline.get("green_incidents")) < MIN_GREEN_INCIDENTS
    stability_passed = bool(stability.get("stability_assessed"))
    if policy_harm:
        status = "policy_harm_blocked"
    elif mae_failed:
        status = "feature_sufficiency_required"
    elif coverage_failed:
        status = "interval_calibration_review_required"
    elif green_failed or not stability_passed:
        status = "model_risk_blocked"
    else:
        status = "shadow_evidence_complete_not_production_approved"
    return {
        "gate_status": status,
        "data_window_hours": delta.get("data_window_hours"),
        "review_delta_status": delta.get("gate_status"),
        "re_evaluation_executed": True,
        "baseline": {
            "independent_incidents": baseline.get("scorable_independent_incidents"),
            "mae_minutes": baseline_mae,
            "median_absolute_error_minutes": baseline.get("median_absolute_error_minutes"),
            "p90_absolute_error_minutes": baseline.get("p90_absolute_error_minutes"),
            "green_incidents": baseline.get("green_incidents"),
            "high_error_incidents": baseline.get("high_error_incidents"),
        },
        "history_challenger": {
            "mae_minutes": challenger_mae,
            "coverage": coverage,
            "baseline_green_incidents": baseline_green,
            "challenger_green_incidents": challenger_green,
            "baseline_high_error_incidents": baseline_high,
            "challenger_high_error_incidents": challenger_high,
            "policy_harm": policy_harm,
            "action": "evaluate_only_never_tune_or_promote",
        },
        "stability": {
            "gate_status": stability.get("gate_status"),
            "stability_assessed": stability_passed,
            "complete_walk_forward_folds": stability.get("complete_walk_forward_folds"),
            "aggregate": stability.get("aggregate"),
        },
        "feature_sufficiency_audit_required": mae_failed,
        "feature_lane_policy": "pre_prediction_only; gis_report52_protection_context_only_until_exact_bridge_coverage_gte_0_80",
        "interval_calibration_review_required": coverage_failed,
        "production_gate_passed": False,
        "mode": "shadow",
        "production_send": "blocked",
    }


def _write_decision(root: Path, result: dict[str, Any]) -> dict[str, Any]:
    summary = root / "seven_day_regate_decision.json"
    report = root / "seven_day_regate_decision.md"
    summary.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report.write_text(
        "# Seven-Day v2 Re-evaluation Decision\n\n"
        f"- status: `{result['gate_status']}`\n"
        f"- data window hours: `{result.get('data_window_hours')}`\n"
        f"- re-evaluation executed: `{str(result['re_evaluation_executed']).lower()}`\n"
        f"- feature sufficiency audit required: `{str(result['feature_sufficiency_audit_required']).lower()}`\n"
        f"- interval calibration review required: `{str(result['interval_calibration_review_required']).lower()}`\n"
        "- history-only challenger is evaluation-only and cannot be tuned or promoted\n"
        "- clean high-error incidents remain in evaluation\n"
        "- GIS, Report52, and protection remain context-only until exact pre-prediction bridge coverage is at least 80%\n"
        "- mode: `shadow`; production_send: `blocked`\n",
        encoding="utf-8",
    )
    return {**result, "decision_json": str(summary), "decision_report": str(report)}


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
