import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.ais_only_error_segmentation import build_ais_only_error_segmentation


class AisOnlyErrorSegmentationTests(unittest.TestCase):
    def test_uses_only_ais_truth_matched_rows_for_error_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readiness = root / "readiness.csv"
            notification = root / "notification.csv"
            segments = root / "segments.csv"
            queue = root / "queue.csv"
            markdown = root / "segmentation.md"

            _write_rows(
                readiness,
                [
                    "source_lane",
                    "event_ref",
                    "event_time",
                    "district",
                    "feeder",
                    "device_id",
                    "source_name",
                    "event_role",
                    "match_level",
                    "match_confidence",
                    "affected_count",
                    "actual_restoration_minutes",
                    "truth_source",
                    "sustained_outage_eligible",
                    "model_metric_included",
                    "model_feature_allowed",
                    "current_p50",
                    "current_q10",
                    "current_q90",
                    "current_absolute_error",
                    "current_covered_q10_q90",
                    "quarantine_reason",
                    "recommended_action",
                ],
                [
                    {
                        "source_lane": "ais_truth_matched",
                        "event_ref": "msg-high",
                        "event_time": "2026-01-01T00:00:00",
                        "district": "พังโคน",
                        "feeder": "PFA09",
                        "device_id": "PFA09R-03",
                        "match_level": "recloser",
                        "affected_count": "3",
                        "actual_restoration_minutes": "240",
                        "model_metric_included": "true",
                        "current_p50": "40",
                        "current_q10": "10",
                        "current_q90": "80",
                        "current_absolute_error": "200",
                        "current_covered_q10_q90": "false",
                    },
                    {
                        "source_lane": "ais_truth_matched",
                        "event_ref": "msg-ok",
                        "event_time": "2026-01-01T01:00:00",
                        "district": "พังโคน",
                        "feeder": "PFA02",
                        "device_id": "PFA02R-01",
                        "match_level": "recloser",
                        "affected_count": "1",
                        "actual_restoration_minutes": "30",
                        "model_metric_included": "true",
                        "current_p50": "28",
                        "current_q10": "15",
                        "current_q90": "45",
                        "current_absolute_error": "2",
                        "current_covered_q10_q90": "true",
                    },
                    {
                        "source_lane": "webex_trigger_no_ais_truth",
                        "event_ref": "msg-webex",
                        "feeder": "PFA03",
                        "device_id": "PFA03R-01",
                        "model_metric_included": "false",
                        "current_absolute_error": "999",
                    },
                    {
                        "source_lane": "pea_quarantined",
                        "event_ref": "msg-pea",
                        "feeder": "PFA04",
                        "device_id": "PFA04R-01",
                        "model_metric_included": "false",
                        "current_absolute_error": "999",
                    },
                ],
            )
            _write_rows(
                notification,
                [
                    "webex_message_ref",
                    "device_type",
                    "webex_device_interruption_class",
                    "event_age_band",
                ],
                [
                    {
                        "webex_message_ref": "msg-high",
                        "device_type": "Recloser",
                        "webex_device_interruption_class": "sustained_candidate",
                        "event_age_band": "late_30m_plus",
                    },
                    {
                        "webex_message_ref": "msg-ok",
                        "device_type": "Recloser",
                        "webex_device_interruption_class": "sustained_candidate",
                        "event_age_band": "fresh_0_5m",
                    },
                ],
            )

            result = build_ais_only_error_segmentation(
                readiness,
                segments,
                queue,
                markdown,
                notification_time_csv=notification,
                high_error_minutes=60,
            )
            segment_rows = _read_csv(segments)
            queue_rows = _read_csv(queue)
            all_segment = [row for row in segment_rows if row["dimension"] == "all"][0]

            self.assertEqual(result["ais_truth_matched_rows"], 2)
            self.assertEqual(result["high_error_rows"], 1)
            self.assertEqual(result["current_q50_mae_minutes"], 101)
            self.assertEqual(result["current_q10_q90_coverage"], 0.5)
            self.assertEqual(queue_rows[0]["event_ref"], "msg-high")
            self.assertEqual(queue_rows[0]["recommended_challenger_lane"], "long_outage_tail_challenger")
            self.assertEqual(all_segment["rows"], "2")
            self.assertEqual(all_segment["high_error_rows"], "1")
            self.assertNotIn("msg-webex", queue.read_text(encoding="utf-8-sig"))
            self.assertNotIn("msg-pea", queue.read_text(encoding="utf-8-sig"))
            self.assertNotIn("6101000001", markdown.read_text(encoding="utf-8-sig"))


def _write_rows(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
