import json
import tempfile
import threading
import unittest
from pathlib import Path

from ais_etr.db import RuntimeDb
from ais_etr.mock_webhook import DEFAULT_PATH, create_mock_webhook_server
from ais_etr.notification_replay import replay_failed_shadow_notifications
from ais_etr.schemas import NotificationRecord


class NotificationReplayTests(unittest.TestCase):
    def test_replay_failed_shadow_notifications_is_idempotent_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = RuntimeDb(root / "runtime.sqlite")
            db.init()
            payload = {
                "mode": "shadow",
                "event_id": "event-1",
                "source": {"webex_message_id": "msg-1", "room_id": "room-secret"},
                "affected_customers": [
                    {"customer": "AIS", "peano": "6101", "feeder": "PFA02", "match_level": "recloser"}
                ],
            }
            db.insert_notification(
                "event-1",
                "http://127.0.0.1:8080/api/v1/etr-notifications",
                "shadow",
                NotificationRecord(payload=payload, status="ERROR"),
            )

            output = root / "captured.jsonl"
            server = create_mock_webhook_server(port=0, output_path=output)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                endpoint = f"http://{host}:{port}{DEFAULT_PATH}"
                first = replay_failed_shadow_notifications(db, endpoint)
                second = replay_failed_shadow_notifications(db, endpoint)
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertEqual(first["candidates"], 1)
            self.assertEqual(first["replayed"], 1)
            self.assertEqual(first["result_status"], {"SENT": 1})
            self.assertEqual(second["candidates"], 0)
            self.assertEqual(second["replayed"], 0)
            with db.session() as conn:
                statuses = [
                    row["status"]
                    for row in conn.execute("SELECT status FROM notifications ORDER BY id").fetchall()
                ]
            self.assertEqual(statuses, ["ERROR", "SENT"])
            captured = output.read_text(encoding="utf-8")
            self.assertIn("affected_customer_count", captured)
            self.assertNotIn("6101", captured)
            self.assertNotIn("room-secret", captured)


if __name__ == "__main__":
    unittest.main()
