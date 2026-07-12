from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from ais_etr.ais_v2_history_quantile_challenger import build_v2_history_quantile_challenger


class V2HistoryQuantileChallengerTests(unittest.TestCase):
    def _row(self, index: int, *, actual: float = 30, target_minutes: int = 10, prediction_minutes: int = 0) -> dict[str, str]:
        return {
            "incident_group_ref": f"incident_{index:016x}",
            "outage_anchor_time": f"2026-07-01T00:{index % 60:02d}:00Z",
            "incident_prediction_created_at": f"2026-07-01T00:{prediction_minutes % 60:02d}:00Z",
            "incident_target_available_at": f"2026-07-01T00:{target_minutes % 60:02d}:00Z",
            "actual_remaining_minutes": str(actual),
            "predicted_p50_minutes": "60",
            "production_send": "blocked",
        }

    def _run(self, rows):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "incidents.csv"
            with source.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            result = build_v2_history_quantile_challenger(
                source,
                predictions_csv=root / "predictions.csv",
                folds_csv=root / "folds.csv",
                summary_json=root / "summary.json",
                report_md=root / "report.md",
                peacon_md=root / "peacon.md",
            )
            with (root / "predictions.csv").open(encoding="utf-8-sig", newline="") as handle:
                predictions = list(csv.DictReader(handle))
            with (root / "folds.csv").open(encoding="utf-8-sig", newline="") as handle:
                folds = list(csv.DictReader(handle))
            bundle = "".join((root / name).read_text(encoding="utf-8") for name in ("summary.json", "report.md", "peacon.md")) + json.dumps(predictions) + json.dumps(folds)
            return result, predictions, folds, bundle

    def test_cold_start_then_history_quantiles(self):
        rows = [self._row(index, actual=float(index + 10), target_minutes=index + 1, prediction_minutes=index) for index in range(13)]
        result, predictions, _, _ = self._run(rows)
        self.assertEqual(12, result["cold_start_incidents"])
        self.assertEqual(1, result["challenger_scored_incidents"])
        self.assertEqual("history_quantile", predictions[-1]["candidate_status"])
        self.assertEqual("12", predictions[-1]["prior_completed_incidents"])

    def test_target_not_available_before_prediction_is_excluded_from_history(self):
        rows = [self._row(index, actual=30, target_minutes=index + 1, prediction_minutes=index) for index in range(12)]
        rows.append(self._row(12, actual=30, target_minutes=59, prediction_minutes=11))
        rows.append(self._row(13, actual=30, target_minutes=14, prediction_minutes=12))
        _, predictions, _, _ = self._run(rows)
        self.assertEqual("cold_start_fallback", predictions[-2]["candidate_status"])
        self.assertEqual("history_quantile", predictions[-1]["candidate_status"])
        self.assertEqual("12", predictions[-1]["prior_completed_incidents"])

    def test_high_error_clean_incident_is_retained(self):
        rows = [self._row(index, actual=30, target_minutes=index + 1, prediction_minutes=index) for index in range(12)]
        rows.append(self._row(12, actual=300, target_minutes=13, prediction_minutes=12))
        _, predictions, _, _ = self._run(rows)
        self.assertEqual("TRUE", predictions[-1]["challenger_high_error_incident"])

    def test_window_short_status_does_not_claim_research_success(self):
        rows = [self._row(index, actual=30, target_minutes=index + 1, prediction_minutes=index) for index in range(50)]
        result, _, _, _ = self._run(rows)
        self.assertEqual("research_window_too_short", result["research_gate_status"])
        self.assertFalse(result["research_metric_claim_allowed"])

    def test_policy_harm_is_not_hidden_by_short_window(self):
        rows = [self._row(index, actual=30, target_minutes=index + 1, prediction_minutes=index) for index in range(12)]
        rows.extend(self._row(index, actual=60, target_minutes=index + 1, prediction_minutes=index) for index in range(12, 50))
        result, _, _, _ = self._run(rows)
        self.assertEqual("model_risk_confirmed_policy_harm", result["research_gate_status"])

    def test_invalid_or_unredacted_reference_is_rejected(self):
        rows = [self._row(index) for index in range(13)]
        rows[-1]["incident_group_ref"] = "raw-request-id"
        with self.assertRaisesRegex(ValueError, "redacted"):
            self._run(rows)

    def test_output_uses_only_redacted_references_and_blocked_send(self):
        rows = [self._row(index, actual=30, target_minutes=index + 1, prediction_minutes=index) for index in range(18)]
        _, _, _, bundle = self._run(rows)
        self.assertNotIn("raw-request", bundle)
        self.assertIn("production_send", bundle)
        self.assertIn("blocked", bundle)


if __name__ == "__main__":
    unittest.main()
