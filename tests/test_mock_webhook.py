import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from ais_etr.mock_webhook import DEFAULT_PATH, create_mock_webhook_server


class MockWebhookTests(unittest.TestCase):
    def test_shadow_payload_is_captured_and_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "events.jsonl"
            server = create_mock_webhook_server(port=0, output_path=output)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                url = f"http://{host}:{port}{DEFAULT_PATH}"
                payload = {
                    "mode": "shadow",
                    "event_id": "event-1",
                    "source": {"webex_message_id": "msg-1", "room_id": "<REDACTED_SECRET>"},
                    "affected_customers": [
                        {"customer": "AIS", "peano": "6101", "feeder": "PFA02", "match_level": "recloser"}
                    ],
                    "prediction": {"etr_minutes_p50": 45, "risk_level": "LOW"},
                    "client_secret": "<REDACTED_SECRET>",
                }
                response = urllib.request.urlopen(
                    urllib.request.Request(
                        url,
                        data=json.dumps(payload).encode("utf-8"),
                        method="POST",
                        headers={"Content-Type": "application/json"},
                    ),
                    timeout=5,
                )

                self.assertEqual(response.status, 200)
                lines = output.read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(lines), 1)
                captured = json.loads(lines[0])
                captured_payload = captured["payload"]
                self.assertEqual(captured_payload["mode"], "shadow")
                self.assertEqual(captured_payload["affected_customer_count"], 1)
                self.assertNotIn("affected_customers", captured_payload)
                self.assertEqual(captured_payload["source"]["room_id"], "REDACTED")
                self.assertEqual(captured_payload["client_secret"], "REDACTED")
                self.assertNotIn("6101", lines[0])
                self.assertNotIn("should-not-log", lines[0])
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_non_shadow_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "events.jsonl"
            server = create_mock_webhook_server(port=0, output_path=output)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                url = f"http://{host}:{port}{DEFAULT_PATH}"
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(
                        urllib.request.Request(
                            url,
                            data=json.dumps({"mode": "production"}).encode("utf-8"),
                            method="POST",
                            headers={"Content-Type": "application/json"},
                        ),
                        timeout=5,
                    )
                self.assertEqual(raised.exception.code, 400)
                self.assertFalse(output.exists())
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()


if __name__ == "__main__":
    unittest.main()
