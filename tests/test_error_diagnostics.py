import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.error_diagnostics import build_shadow_error_diagnostics


class ErrorDiagnosticsTests(unittest.TestCase):
    def test_error_diagnostics_quantifies_duration_and_feeder_contribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comparison = root / "incident.csv"
            _write_comparison(
                comparison,
                [
                    {"event_id": "a", "feeder": "F1", "device_type": "Recloser", "actual": "10", "p50": "20", "err": "10", "covered": "TRUE"},
                    {"event_id": "b", "feeder": "F1", "device_type": "Recloser", "actual": "240", "p50": "40", "err": "200", "covered": "FALSE"},
                    {"event_id": "c", "feeder": "F2", "device_type": "CB", "actual": "50", "p50": "30", "err": "20", "covered": "TRUE"},
                ],
            )
            output = root / "segments.csv"
            markdown = root / "diagnostic.md"

            result = build_shadow_error_diagnostics(comparison, output, markdown)
            rows = _read_csv(output)

            self.assertEqual(result["incidents"], 3)
            self.assertEqual(result["mean_absolute_error_minutes"], 76.67)
            duration_long = next(row for row in rows if row["segment_type"] == "duration_band" and row["segment"] == ">180")
            self.assertEqual(duration_long["incidents"], "1")
            self.assertEqual(duration_long["share_of_total_absolute_error"], "0.87")
            feeder_f1 = next(row for row in rows if row["segment_type"] == "feeder" and row["segment"] == "F1")
            self.assertEqual(feeder_f1["long_gt_180_rows"], "1")
            text = markdown.read_text(encoding="utf-8-sig")
            self.assertIn("Dominant driver", text)
            self.assertNotIn("PEA001", text)


def _write_comparison(path: Path, rows: list[dict[str, str]]) -> None:
    columns = [
        "event_id",
        "webex_message_ref",
        "event_time",
        "district",
        "device_type",
        "device_id",
        "feeder",
        "match_level",
        "affected_count",
        "actual_restoration_minutes",
        "current_p50",
        "current_q10",
        "current_q90",
        "current_absolute_error",
        "current_covered_q10_q90",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "event_id": row["event_id"],
                    "webex_message_ref": "msg-redacted",
                    "event_time": "2026-06-17T10:00:00",
                    "district": "pilot",
                    "device_type": row["device_type"],
                    "device_id": "DEV",
                    "feeder": row["feeder"],
                    "match_level": "affected_peano_time",
                    "affected_count": "1",
                    "actual_restoration_minutes": row["actual"],
                    "current_p50": row["p50"],
                    "current_q10": "5",
                    "current_q90": "90",
                    "current_absolute_error": row["err"],
                    "current_covered_q10_q90": row["covered"],
                }
            )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
