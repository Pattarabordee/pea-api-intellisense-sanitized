import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ais_etr.config import Settings
from ais_etr.db import RuntimeDb
from ais_etr.pipeline import AisEtrPipeline
from ais_etr.schemas import CustomerAsset


class WebexHistoryReplayTests(unittest.TestCase):
    def test_replay_history_captures_shadow_payload_without_http_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "history.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "id": "m1",
                        "created": "2026-06-17T10:00:00Z",
                        "text": "Recloser PFA02VR-101 trip outage",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            settings = Settings(
                workspace=root,
                db_path=Path("runtime/test.sqlite"),
                model_path=Path("runtime/missing_model.json"),
                notification_mode="shadow",
                mock_webhook_url="http://127.0.0.1:1/api/v1/etr-notifications",
                webex_room_district="Phang Khon",
                pilot_districts=("Phang Khon",),
            )
            db = RuntimeDb(settings.resolve(settings.db_path))
            db.init()
            db.upsert_customer_assets(
                [
                    CustomerAsset(
                        peano="6101",
                        feeder="PFA02",
                        recloser_ids=("PFA02VR-101",),
                        trace_status="OK",
                        confidence_eligible=True,
                    )
                ]
            )
            pipeline = AisEtrPipeline(settings, db=db)

            result = pipeline.replay_webex_history(source, audit_output=root / "audit.csv")

            self.assertEqual(result.rows_read, 1)
            self.assertEqual(result.new_messages, 1)
            self.assertEqual(result.parsed_events, 1)
            self.assertEqual(result.notifications_captured, 1)
            self.assertEqual(result.match_level_counts, {"recloser": 1})
            self.assertTrue((root / "audit.csv").exists())

            conn = sqlite3.connect(settings.resolve(settings.db_path))
            try:
                status, endpoint_url = conn.execute(
                    "SELECT status, endpoint_url FROM notifications"
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(status, "REPLAY_CAPTURED")
            self.assertIsNone(endpoint_url)

            second = pipeline.replay_webex_history(source)
            self.assertEqual(second.new_messages, 0)
            self.assertEqual(second.skipped_existing, 1)
            self.assertEqual(second.notifications_captured, 0)


if __name__ == "__main__":
    unittest.main()
