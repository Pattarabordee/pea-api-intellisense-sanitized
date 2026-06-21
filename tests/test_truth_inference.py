import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.db import RuntimeDb
from ais_etr.schemas import OutageDevice, OutageEvent
from ais_etr.truth_inference import infer_webex_truth_mapping, infer_restoration_from_message


class TruthInferenceTests(unittest.TestCase):
    def test_infer_restoration_from_first_close_after_event_time(self):
        row = {
            "webex_message_id": "msg-1",
            "event_time": "2026-06-17T10:00:00",
            "device_id": "PFA02VR-101",
            "feeder": "PFA02",
            "raw_text": (
                "2026-06-17 10:00:00.000  Open  Switch status\n"
                "2026-06-17 10:04:30.000  Close Switch status"
            ),
        }
        candidate = infer_restoration_from_message(row)
        self.assertEqual(candidate["actual_restoration_minutes"], 4.5)
        self.assertEqual(candidate["truth_confidence"], "REVIEW")
        self.assertEqual(candidate["truth_source"], "webex_switch_status")

    def test_infer_command_fills_zero_minute_review_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = RuntimeDb(root / "runtime.sqlite")
            db.init()
            message = {
                "id": "msg-0",
                "roomId": "<REDACTED_ROOM_ID>",
                "created": "2026-06-17T10:00:00Z",
                "text": (
                    "2026-06-17 10:00:00.000  Open  Switch status\n"
                    "2026-06-17 10:00:00.000  Close Switch status"
                ),
            }
            db.insert_webex_message(message)
            db.upsert_event(
                OutageEvent(
                    event_id="event-0",
                    source="webex",
                    webex_message_id="msg-0",
                    room_id="<REDACTED_ROOM_ID>",
                    raw_text=message["text"],
                    event_time="2026-06-17T10:00:00",
                    outage_device=OutageDevice(device_type="Recloser", device_id="PFA02VR-101", feeder="PFA02"),
                )
            )
            mapping = root / "shadow_truth_mapping.csv"

            result = infer_webex_truth_mapping(db.path, mapping)

            self.assertEqual(result["candidate_rows"], 1)
            self.assertEqual(result["filled_rows"], 1)
            with mapping.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["actual_restoration_minutes"], "0.0")
            self.assertEqual(rows[0]["truth_quality"], "REVIEW")

    def test_infer_command_fills_empty_mapping_and_preserves_existing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = RuntimeDb(root / "runtime.sqlite")
            db.init()
            message = {
                "id": "msg-1",
                "roomId": "<REDACTED_ROOM_ID>",
                "created": "2026-06-17T10:00:00Z",
                "text": (
                    "2026-06-17 10:00:00.000  Open  Switch status\n"
                    "2026-06-17 10:07:00.000  Close Switch status"
                ),
            }
            db.insert_webex_message(message)
            db.upsert_event(
                OutageEvent(
                    event_id="event-1",
                    source="webex",
                    webex_message_id="msg-1",
                    room_id="<REDACTED_ROOM_ID>",
                    raw_text=message["text"],
                    event_time="2026-06-17T10:00:00",
                    outage_device=OutageDevice(device_type="Recloser", device_id="PFA02VR-101", feeder="PFA02"),
                )
            )
            mapping = root / "shadow_truth_mapping.csv"
            candidates = root / "shadow_truth_candidates.csv"

            first = infer_webex_truth_mapping(db.path, mapping, candidates)
            second = infer_webex_truth_mapping(db.path, mapping, candidates)

            self.assertEqual(first["filled_rows"], 1)
            self.assertEqual(second["filled_rows"], 0)
            self.assertEqual(second["preserved_existing_rows"], 1)
            with mapping.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["actual_restoration_minutes"], "7.0")
            self.assertIn("webex_switch_status", candidates.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
