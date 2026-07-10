from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from ais_etr.ais_v2_baseline_trend import build_v2_baseline_trend


class V2BaselineTrendTests(unittest.TestCase):
    def _run(self, entries):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.jsonl"
            registry.write_text(
                "".join(json.dumps(entry, sort_keys=True) + "\n" for entry in entries), encoding="utf-8"
            )
            result = build_v2_baseline_trend(
                registry,
                output_csv=root / "trend.csv",
                report_md=root / "report.md",
                peacon_md=root / "peacon.md",
            )
            with (root / "trend.csv").open(encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            bundle = (root / "report.md").read_text(encoding="utf-8") + (root / "peacon.md").read_text(
                encoding="utf-8"
            )
            return result, rows, bundle

    @staticmethod
    def _entry(evaluation_id, registered_at, incidents, mae):
        return {
            "evaluation_id": evaluation_id,
            "registered_at": registered_at,
            "scorable_independent_incidents": incidents,
            "mae_minutes": mae,
            "median_absolute_error_minutes": mae,
            "p90_absolute_error_minutes": mae + 1,
            "mean_worst_meter_absolute_error_minutes": mae + 2,
            "green_incidents": 0,
            "high_error_incidents": 0,
            "coverage_status": "unavailable_no_q10_q90_baseline",
            "production_send": "blocked",
        }

    def test_low_n_registry_is_smoke_only_and_not_claimable(self):
        entries = [
            self._entry("eval_a", "2026-07-10T01:00:00Z", 1, 52.0),
            self._entry("eval_b", "2026-07-10T02:00:00Z", 2, 53.5),
        ]
        result, rows, bundle = self._run(entries)
        self.assertEqual(2, result["latest_scorable_independent_incidents"])
        self.assertEqual("pilot_smoke_only", result["latest_sample_size_status"])
        self.assertFalse(result["research_metric_claim_allowed"])
        self.assertEqual("1.5", rows[1]["mae_delta_minutes"])
        self.assertIn("ลูกค้าสื่อสารรายสำคัญ", bundle)
        self.assertNotIn("production-ready", bundle)

    def test_duplicate_evaluation_id_is_kept_once(self):
        entry = self._entry("eval_a", "2026-07-10T01:00:00Z", 1, 52.0)
        result, rows, _ = self._run([entry, entry])
        self.assertEqual(1, result["registry_entries"])
        self.assertEqual(1, len(rows))

    def test_thirty_incidents_allow_research_metric_claim_only(self):
        entry = self._entry("eval_ready", "2026-07-10T03:00:00Z", 30, 20.0)
        result, rows, bundle = self._run([entry])
        self.assertTrue(result["research_metric_claim_allowed"])
        self.assertFalse(result["production_accuracy_claim_allowed"])
        self.assertEqual("evaluation_sample_ready", rows[0]["sample_size_status"])
        self.assertIn("research metric claim allowed: `true`", bundle)
        self.assertIn("production accuracy claim allowed: `false`", bundle)

    def test_nonblocked_registry_is_rejected(self):
        entry = self._entry("eval_a", "2026-07-10T01:00:00Z", 1, 52.0)
        entry["production_send"] = "allowed"
        with self.assertRaisesRegex(ValueError, "production_send"):
            self._run([entry])


if __name__ == "__main__":
    unittest.main()
