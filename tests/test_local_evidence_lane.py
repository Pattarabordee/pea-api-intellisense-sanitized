import csv
from pathlib import Path
import tempfile
import unittest

from ais_etr.local_evidence_lane import build_local_evidence_report


class LocalEvidenceLaneTests(unittest.TestCase):
    def test_evidence_is_pre_event_context_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "evidence.csv"
            with snapshot.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["meter_ref", "evidence_time", "evidence_status"])
                writer.writeheader()
                writer.writerows([
                    {"meter_ref": "hash-a", "evidence_time": "2026-07-10T01:00:00Z", "evidence_status": "pea_evidence_supported"},
                    {"meter_ref": "hash-b", "evidence_time": "2026-07-10T03:00:00Z", "evidence_status": "pea_evidence_supported"},
                ])
            items = [
                {"request_ref": "request_a", "detected_at": "2026-07-10T02:00:00Z", "meter": {"hash": "hash-a"}},
                {"request_ref": "request_b", "detected_at": "2026-07-10T02:00:00Z", "meter": {"hash": "hash-b"}},
            ]
            output = root / "result.csv"
            result = build_local_evidence_report(items, snapshot_csvs=[snapshot], output_csv=output, report_md=root / "report.md")
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["evidence_status"], "pea_evidence_supported")
            self.assertEqual(rows[1]["evidence_status"], "insufficient_evidence")
            self.assertTrue(all(row["use_for_training_target"] == "FALSE" for row in rows))
            self.assertEqual(result["production_send"], "blocked")


if __name__ == "__main__":
    unittest.main()
