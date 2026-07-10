import unittest
import tempfile
from pathlib import Path

from ais_etr.db import RuntimeDb
from ais_etr.evaluation import build_shadow_report, evaluate_sample_messages, export_shadow_truth_template
from ais_etr.schemas import CustomerMatch, MatchResult, NotificationRecord, OutageDevice, OutageEvent, Prediction


class EvaluationTests(unittest.TestCase):
    def test_sample_corpus_expectations(self):
        result = evaluate_sample_messages(
            "data/webex_shadow_samples.jsonl",
            ("พังโคน", "วาริชภูมิ", "นิคมน้ำอูน"),
        )
        self.assertEqual(result["failed"], 0, result["failures"])
        self.assertGreaterEqual(result["total"], 20)
        self.assertGreaterEqual(result["expectation_pass_rate"], 0.95)

    def test_shadow_report_uses_manual_truth_mapping_without_event_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = RuntimeDb(root / "runtime.sqlite")
            db.init()
            event = OutageEvent(
                event_id="event-1",
                source="webex",
                webex_message_id="msg-1",
                room_id="<REDACTED_ROOM_ID>",
                raw_text="Recloser PFA02VR-101 trip outage",
                event_time="2026-06-17T10:00:00Z",
                outage_device=OutageDevice(device_type="Recloser", device_id="PFA02VR-101", feeder="PFA02"),
                parsed_fields={"event_number": None},
            )
            db.upsert_event(event)
            match = MatchResult(
                matches=(CustomerMatch(customer="AIS", peano="6101", feeder="PFA02", match_level="recloser"),),
                match_level="recloser",
                match_confidence=0.95,
            )
            prediction = Prediction(
                etr_minutes_p50=40,
                q25=30,
                q75=50,
                q10=20,
                q90=70,
                risk_level="LOW",
                model_version="test",
            )
            db.insert_prediction(event.event_id, prediction, match)
            db.insert_notification(
                event.event_id,
                "http://127.0.0.1:8080/api/v1/etr-notifications",
                "shadow",
                NotificationRecord(payload={"mode": "shadow"}, status="SENT", status_code=200),
            )
            mapping = root / "shadow_truth_mapping.csv"
            mapping.write_text(
                "webex_message_id,event_number,actual_restoration_minutes,truth_source,truth_target,truth_definition,truth_quality,truth_notes\n"
                "msg-1,,55,ais_meter_state,ais_event_remaining_restoration_minutes,AIS_RESTORE-prediction_created_at,HIGH,strict meter-state truth\n",
                encoding="utf-8",
            )
            output = root / "shadow_report.csv"

            result = build_shadow_report(
                db.path,
                root / "missing_event.xlsx",
                (),
                root / "missing_distance.csv",
                output,
                mapping,
            )

            self.assertEqual(result["with_event_number"], 0)
            self.assertEqual(result["with_truth"], 1)
            self.assertEqual(result["mapped_truth_rows"], 1)
            self.assertEqual(result["q50_mae_minutes"], 15.0)
            self.assertEqual(result["q10_q90_coverage"], 1.0)
            report_text = output.read_text(encoding="utf-8-sig")
            self.assertIn("ais_meter_state", report_text)
            self.assertIn("ais_event_remaining_restoration_minutes", report_text)

    def test_shadow_truth_template_exports_current_webex_message_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = RuntimeDb(root / "runtime.sqlite")
            db.init()
            event = OutageEvent(
                event_id="event-1",
                source="webex",
                webex_message_id="msg-1",
                room_id="<REDACTED_ROOM_ID>",
                raw_text="Recloser PFA02VR-101 trip outage",
                outage_device=OutageDevice(device_type="Recloser", device_id="PFA02VR-101", feeder="PFA02"),
                parsed_fields={"event_number": None},
            )
            db.upsert_event(event)
            match = MatchResult(matches=(), match_level=None, match_confidence=0)
            prediction = Prediction(
                etr_minutes_p50=40,
                q25=30,
                q75=50,
                q10=20,
                q90=70,
                risk_level="LOW",
                model_version="test",
            )
            db.insert_prediction(event.event_id, prediction, match)

            output = root / "shadow_truth_mapping.csv"
            result = export_shadow_truth_template(db.path, output)

            self.assertEqual(result["rows"], 1)
            self.assertIn("webex_message_id,event_number,actual_restoration_minutes", output.read_text(encoding="utf-8-sig"))
            self.assertIn("msg-1", output.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
