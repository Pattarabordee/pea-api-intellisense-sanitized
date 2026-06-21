import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.db import RuntimeDb
from ais_etr.registry_repair import build_no_match_repair_candidates
from ais_etr.schemas import CustomerAsset, MatchResult, OutageDevice, OutageEvent, Prediction


class RegistryRepairTests(unittest.TestCase):
    def test_no_match_repair_candidates_group_without_raw_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = RuntimeDb(root / "runtime.sqlite")
            db.init()
            db.upsert_customer_assets(
                [
                    CustomerAsset(
                        peano="6101",
                        feeder="PFA04",
                        recloser_ids=("PFA04VR-101",),
                        cb_ids=(),
                        trace_status="OK",
                        confidence_eligible=True,
                    )
                ]
            )
            message = {
                "id": "msg-1",
                "roomId": "<REDACTED_ROOM_ID>",
                "created": "2026-06-17T10:00:00Z",
                "text": "CB PFA04VB-01 outage raw text should not be exported",
            }
            db.insert_webex_message(message)
            event = OutageEvent(
                event_id="event-1",
                source="webex",
                webex_message_id="msg-1",
                room_id="<REDACTED_ROOM_ID>",
                raw_text=message["text"],
                event_time="2026-06-17T10:00:00",
                district="Phang Khon",
                outage_device=OutageDevice(device_type="CB", device_id="PFA04VB-01", feeder="PFA04"),
            )
            db.upsert_event(event)
            db.insert_prediction(
                event.event_id,
                Prediction(
                    etr_minutes_p50=45,
                    q25=30,
                    q75=60,
                    q10=20,
                    q90=90,
                    risk_level="MEDIUM",
                    model_version="test",
                ),
                MatchResult(matches=(), match_level=None, match_confidence=0.0),
            )
            output = root / "candidates.csv"

            result = build_no_match_repair_candidates(db.path, output)

            self.assertEqual(result["no_match_events"], 1)
            self.assertEqual(result["candidate_rows"], 1)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["device_id"], "PFA04VB-01")
            self.assertEqual(rows[0]["repair_category"], "protection_device_not_in_registry_trace")
            self.assertEqual(rows[0]["registry_confident_assets_on_feeder"], "1")
            self.assertNotIn("raw_text", rows[0])
            self.assertNotIn("peano", rows[0])


if __name__ == "__main__":
    unittest.main()
