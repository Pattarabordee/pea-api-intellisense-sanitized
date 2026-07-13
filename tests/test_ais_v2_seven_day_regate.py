from __future__ import annotations

import unittest

from ais_etr.ais_v2_seven_day_regate import build_seven_day_decision


class SevenDayRegateDecisionTests(unittest.TestCase):
    def _delta(self, due=True):
        return {"production_send": "blocked", "seven_day_re_evaluation_due": due, "data_window_hours": 168.0, "gate_status": "stable_historical_backlog"}

    def _baseline(self, mae=20, green=30):
        return {"production_send": "blocked", "mae_minutes": mae, "median_absolute_error_minutes": 15, "p90_absolute_error_minutes": 80, "green_incidents": green, "high_error_incidents": 8, "scorable_independent_incidents": 100}

    def _challenger(self, coverage=.8, baseline_green=30, challenger_green=30, baseline_high=8, challenger_high=8):
        return {"production_send": "blocked", "challenger_mae_minutes": 18, "challenger_q10_q90_coverage": coverage, "baseline_green_incidents": baseline_green, "challenger_green_incidents": challenger_green, "baseline_high_error_incidents": baseline_high, "challenger_high_error_incidents": challenger_high}

    def _stability(self, assessed=True):
        return {"production_send": "blocked", "gate_status": "baseline_stability_observed_not_production_ready", "stability_assessed": assessed, "complete_walk_forward_folds": 4, "aggregate": {"mae_minutes": 20}}

    def test_under_168_hours_stops_without_evaluation(self):
        result = build_seven_day_decision(delta=self._delta(False))
        self.assertEqual("waiting_for_seven_day_window", result["gate_status"])
        self.assertFalse(result["re_evaluation_executed"])

    def test_due_requires_all_summaries(self):
        with self.assertRaisesRegex(ValueError, "requires baseline"):
            build_seven_day_decision(delta=self._delta())

    def test_green_or_high_error_regression_is_policy_harm(self):
        result = build_seven_day_decision(delta=self._delta(), baseline=self._baseline(), challenger=self._challenger(challenger_green=29), stability=self._stability())
        self.assertEqual("policy_harm_blocked", result["gate_status"])
        result = build_seven_day_decision(delta=self._delta(), baseline=self._baseline(), challenger=self._challenger(challenger_high=9), stability=self._stability())
        self.assertEqual("policy_harm_blocked", result["gate_status"])

    def test_mae_failure_opens_feature_sufficiency_lane(self):
        result = build_seven_day_decision(delta=self._delta(), baseline=self._baseline(mae=20), challenger=self._challenger(), stability=self._stability())
        self.assertEqual("feature_sufficiency_required", result["gate_status"])
        self.assertTrue(result["feature_sufficiency_audit_required"])

    def test_coverage_failure_is_separate_from_p50(self):
        result = build_seven_day_decision(delta=self._delta(), baseline=self._baseline(mae=15), challenger=self._challenger(coverage=.7), stability=self._stability())
        self.assertEqual("interval_calibration_review_required", result["gate_status"])
        self.assertTrue(result["interval_calibration_review_required"])

    def test_green_or_stability_blocks_model_risk(self):
        result = build_seven_day_decision(delta=self._delta(), baseline=self._baseline(mae=15, green=29), challenger=self._challenger(), stability=self._stability())
        self.assertEqual("model_risk_blocked", result["gate_status"])

    def test_no_decision_can_enable_production(self):
        result = build_seven_day_decision(delta=self._delta(), baseline=self._baseline(mae=15), challenger=self._challenger(), stability=self._stability())
        self.assertEqual("shadow_evidence_complete_not_production_approved", result["gate_status"])
        self.assertFalse(result["production_gate_passed"])
        self.assertEqual("blocked", result["production_send"])

    def test_nonblocked_input_is_rejected(self):
        delta = self._delta(False)
        delta["production_send"] = "allowed"
        with self.assertRaisesRegex(ValueError, "production_send"):
            build_seven_day_decision(delta=delta)


if __name__ == "__main__":
    unittest.main()
