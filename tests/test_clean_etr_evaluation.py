import csv
import json
from pathlib import Path
import tempfile
import unittest

from ais_etr.clean_etr_evaluation import build_clean_etr_evaluation_frame


class CleanEtrEvaluationTests(unittest.TestCase):
    def test_only_meter_state_truth_is_eligible_and_incidents_are_grouped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["interval_id", "bridge_status", "outage_at", "restore_at", "prediction_created_at"])
                writer.writeheader()
                writer.writerows([
                    {"interval_id": "a", "bridge_status": "METER_STATE_MODEL_READY", "outage_at": "2026-07-10T01:00:00Z", "restore_at": "2026-07-10T03:00:00Z", "prediction_created_at": "2026-07-10T01:30:00Z"},
                    {"interval_id": "b", "bridge_status": "METER_STATE_MODEL_READY", "outage_at": "2026-07-10T01:03:00Z", "restore_at": "2026-07-10T03:02:00Z", "prediction_created_at": "2026-07-10T01:35:00Z"},
                    {"interval_id": "legacy", "bridge_status": "LEGACY_UNVERIFIED", "outage_at": "2026-07-10T01:00:00Z", "restore_at": "2026-07-10T02:00:00Z", "prediction_created_at": "2026-07-10T01:10:00Z"},
                ])
            output = root / "frame.csv"
            summary_path = root / "summary.json"
            summary = build_clean_etr_evaluation_frame(source, output, summary_path)
            self.assertEqual(summary["eligible_rows"], 2)
            self.assertEqual(summary["rejected_rows"], 1)
            self.assertEqual(summary["independent_incident_groups"], 1)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["incident_group_ref"], rows[1]["incident_group_ref"])
            self.assertNotIn("interval_id", rows[0])
            self.assertEqual(json.loads(summary_path.read_text(encoding="utf-8"))["production_send"], "blocked")


if __name__ == "__main__":
    unittest.main()
