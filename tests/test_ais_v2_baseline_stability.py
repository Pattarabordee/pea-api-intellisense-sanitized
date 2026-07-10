from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from ais_etr.ais_v2_baseline_stability import build_v2_baseline_stability_gate


class V2BaselineStabilityTests(unittest.TestCase):
    @staticmethod
    def _row(index: int, *, error: float = 20.0, send: str = "blocked") -> dict[str, str]:
        return {
            "incident_group_ref": f"secret-incident-{index}",
            "outage_anchor_time": f"2026-07-10T{index // 60:02d}:{index % 60:02d}:00Z",
            "meter_interval_count": "1",
            "actual_remaining_minutes": "40",
            "predicted_p50_minutes": "60",
            "absolute_error_minutes": str(error),
            "worst_meter_absolute_error_minutes": str(error + 1),
            "green_incident": "FALSE",
            "high_error_incident": "FALSE",
            "model_version": "fixed_naive_60m_v1",
            "production_send": send,
        }

    def _run(self, rows):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "incidents.csv"
            with source.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            result = build_v2_baseline_stability_gate(
                source,
                output_csv=root / "folds.csv",
                summary_json=root / "summary.json",
                report_md=root / "report.md",
                peacon_md=root / "peacon.md",
            )
            with (root / "folds.csv").open(encoding="utf-8-sig") as handle:
                folds = list(csv.DictReader(handle))
            bundle = (
                (root / "summary.json").read_text(encoding="utf-8")
                + (root / "report.md").read_text(encoding="utf-8")
                + (root / "peacon.md").read_text(encoding="utf-8")
                + json.dumps(folds)
            )
            return result, folds, bundle

    def test_low_n_does_not_score_folds(self):
        result, folds, bundle = self._run([self._row(index) for index in range(12)])
        self.assertEqual("insufficient_independent_incidents", result["gate_status"])
        self.assertEqual([], folds)
        self.assertFalse(result["stability_assessed"])
        self.assertNotIn("secret-incident", bundle)

    def test_thirty_incidents_create_three_fixed_walk_forward_folds(self):
        result, folds, _ = self._run([self._row(index, error=float(index)) for index in range(30)])
        self.assertEqual("baseline_stability_observed_not_production_ready", result["gate_status"])
        self.assertEqual(3, len(folds))
        self.assertEqual(["12", "18", "24"], [row["train_incidents"] for row in folds])
        self.assertEqual(["6", "6", "6"], [row["test_incidents"] for row in folds])
        self.assertTrue(result["stability_assessed"])
        self.assertFalse(result["stability_is_production_evidence"])

    def test_nonblocked_incident_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "production_send"):
            self._run([self._row(index, send="allowed") for index in range(30)])

    def test_duplicate_incident_reference_is_rejected(self):
        rows = [self._row(index) for index in range(30)]
        rows[-1]["incident_group_ref"] = rows[0]["incident_group_ref"]
        with self.assertRaisesRegex(ValueError, "unique"):
            self._run(rows)


if __name__ == "__main__":
    unittest.main()
