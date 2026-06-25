import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.reportpo_feature_diagnostics import build_reportpo_feature_diagnostics


class ReportPoFeatureDiagnosticsTests(unittest.TestCase):
    def test_build_reportpo_feature_diagnostics_segments_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comparison = root / "comparison.csv"
            feature = root / "feature.csv"
            output = root / "enriched.csv"
            segments = root / "segments.csv"
            markdown = root / "report.md"
            raw_webex_id = "raw-webex-id-1"

            _write_csv(
                comparison,
                [
                    {
                        "event_id": "event-1",
                        "webex_message_ref": "msg-77169c6028b8",
                        "event_time": "2026-06-17T10:00:00",
                        "district": "พังโคน",
                        "device_type": "Recloser",
                        "device_id": "PFA01R-01",
                        "feeder": "PFA01",
                        "match_level": "recloser",
                        "affected_count": "3",
                        "actual_restoration_minutes": "100",
                        "current_p50": "30",
                        "current_q10": "10",
                        "current_q90": "60",
                        "current_risk_level": "HIGH",
                        "current_absolute_error": "70",
                        "current_covered_q10_q90": "FALSE",
                    },
                    {
                        "event_id": "event-2",
                        "webex_message_ref": "msg-no-feature",
                        "event_time": "2026-06-17T11:00:00",
                        "district": "พังโคน",
                        "device_type": "CB",
                        "device_id": "PFA02B-01",
                        "feeder": "PFA02",
                        "match_level": "cb",
                        "affected_count": "1",
                        "actual_restoration_minutes": "20",
                        "current_p50": "25",
                        "current_q10": "10",
                        "current_q90": "60",
                        "current_risk_level": "LOW",
                        "current_absolute_error": "5",
                        "current_covered_q10_q90": "TRUE",
                    },
                ],
            )
            _write_csv(
                feature,
                [
                    {
                        "webex_message_id": raw_webex_id,
                        "match_status": "matched",
                        "event_number": "6847000001",
                        "delta_minutes": "3",
                        "event_type": "OU",
                        "event_status": "RealTime+Fast",
                        "etr_type": "1",
                        "etr_type_description": "ETR RealTime",
                        "work_type": "OU",
                        "feature_quality": "proxy_only",
                    }
                ],
            )

            result = build_reportpo_feature_diagnostics(
                comparison,
                feature,
                output,
                segments,
                markdown,
                min_segment_truth=1,
            )
            with output.open(encoding="utf-8-sig", newline="") as handle:
                enriched = list(csv.DictReader(handle))
            with segments.open(encoding="utf-8-sig", newline="") as handle:
                segment_rows = list(csv.DictReader(handle))
            markdown_text = markdown.read_text(encoding="utf-8")

            self.assertEqual(result["events"], 2)
            self.assertEqual(result["with_reportpo_feature"], 1)
            self.assertEqual(enriched[0]["reportpo_event_type"], "OU")
            self.assertEqual(enriched[0]["diagnostic_bucket"], "high_error")
            self.assertNotIn(raw_webex_id, output.read_text(encoding="utf-8-sig"))
            self.assertTrue(
                any(
                    row["dimension"] == "ReportPO event type"
                    and row["segment"] == "OU"
                    and row["mean_absolute_error"] == "70.0"
                    for row in segment_rows
                )
            )
            self.assertIn("Highest Error Segments", markdown_text)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
