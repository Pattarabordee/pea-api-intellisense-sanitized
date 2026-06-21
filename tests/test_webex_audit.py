import csv
import json
import tempfile
import unittest
from pathlib import Path

from ais_etr.db import RuntimeDb
from ais_etr.notifier import build_notification_payload
from ais_etr.parser import parse_webex_message
from ais_etr.schemas import CustomerMatch, MatchResult, NotificationRecord, Prediction
from ais_etr.webex_audit import build_webex_audit


class WebexAuditTests(unittest.TestCase):
    def test_audit_reparses_runtime_rows_and_exports_sanitized_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = RuntimeDb(root / "runtime.sqlite")
            db.init()
            message = {
                "id": "msg-1",
                "roomId": "<REDACTED_ROOM_ID>",
                "created": "2026-06-17T10:00:00Z",
                "text": "Recloser PFA02VR-101 trip outage " + ("x" * 300),
            }
            db.insert_webex_message(message)
            event = parse_webex_message(message)
            self.assertIsNotNone(event)
            db.upsert_event(event)
            match = MatchResult(
                matches=(CustomerMatch(customer="AIS", peano="6101", feeder="PFA02", match_level="recloser"),),
                match_level="recloser",
                match_confidence=0.95,
            )
            prediction = Prediction(
                etr_minutes_p50=35,
                q25=20,
                q75=50,
                q10=10,
                q90=80,
                risk_level="LOW",
                model_version="test-model",
            )
            db.insert_prediction(event.event_id, prediction, match)
            payload = build_notification_payload(event, match, prediction)
            db.insert_notification(
                event.event_id,
                "http://127.0.0.1:8080/api/v1/etr-notifications",
                "shadow",
                NotificationRecord(payload=payload, status="ERROR"),
            )

            audit_csv = root / "audit.csv"
            samples = root / "samples.jsonl"
            result = build_webex_audit(
                db.path,
                districts=("พังโคน", "วาริชภูมิ", "นิคมน้ำอูน"),
                room_district="พังโคน",
                output_csv=audit_csv,
                samples_output=samples,
                max_text_chars=80,
            )

            self.assertEqual(result["total_events"], 1)
            self.assertEqual(result["counts"]["device"], 1)
            self.assertEqual(result["counts"]["district"], 1)
            self.assertEqual(result["counts"]["event_number"], 0)
            self.assertEqual(result["event_number_missing_reason"], {"not_present_in_message": 1})
            with audit_csv.open(encoding="utf-8-sig") as handle:
                csv_rows = list(csv.DictReader(handle))
            self.assertEqual(csv_rows[0]["district_present"], "True")
            self.assertEqual(csv_rows[0]["district_source"], "room_context")
            self.assertNotIn("x" * 200, audit_csv.read_text(encoding="utf-8-sig"))

            sample = json.loads(samples.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(sample["roomId"], "WEBEX_ROOM_REDACTED")
            self.assertEqual(sample["roomDistrict"], "พังโคน")
            self.assertEqual(sample["expected"]["district"], "พังโคน")


if __name__ == "__main__":
    unittest.main()
