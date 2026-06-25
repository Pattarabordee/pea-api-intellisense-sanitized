import csv
import json
import tempfile
import unittest
from pathlib import Path

from ais_etr.webex_export import export_webex_room_history


class FakePagedWebexClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def list_messages(self, max_items=50, before=None, before_message=None):
        self.calls.append(
            {
                "max_items": max_items,
                "before": before,
                "before_message": before_message,
            }
        )
        page = self.pages.get(before_message)
        if page is None:
            return []
        return page[:max_items]


class WebexExportTests(unittest.TestCase):
    def test_export_paginates_and_omits_sensitive_metadata_by_default(self):
        pages = {
            None: [
                _message("msg-3", "2026-06-17T10:03:00Z", "RC 01"),
                _message("msg-2", "2026-06-17T10:02:00Z", "RC 02"),
            ],
            "msg-2": [
                _message("msg-1", "2026-06-17T10:01:00Z", "RC 03"),
            ],
            "msg-1": [],
        }
        client = FakePagedWebexClient(pages)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = export_webex_room_history(
                client,
                root / "history.jsonl",
                root / "history.csv",
                max_messages=3,
                page_size=2,
                sleep_seconds=0,
            )

            rows = [
                json.loads(line)
                for line in (root / "history.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            with (root / "history.csv").open(encoding="utf-8-sig", newline="") as handle:
                csv_rows = list(csv.DictReader(handle))

        self.assertEqual(result["exported"], 3)
        self.assertEqual([call["before_message"] for call in client.calls], [None, "msg-2"])
        self.assertEqual([row["id"] for row in rows], ["msg-3", "msg-2", "msg-1"])
        self.assertEqual(len(csv_rows), 3)
        self.assertNotIn("room_id", rows[0])
        self.assertNotIn("person_email", rows[0])
        self.assertNotIn("raw_json", rows[0])

    def test_export_stops_at_after_boundary(self):
        pages = {
            None: [
                _message("msg-2", "2026-06-17T10:02:00Z", "new"),
                _message("msg-1", "2026-06-17T09:59:00Z", "old"),
            ],
            "msg-1": [],
        }
        client = FakePagedWebexClient(pages)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = export_webex_room_history(
                client,
                root / "history.jsonl",
                max_messages=10,
                page_size=10,
                after="2026-06-17T10:00:00Z",
                sleep_seconds=0,
            )
            rows = [
                json.loads(line)
                for line in (root / "history.jsonl").read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(result["exported"], 1)
        self.assertTrue(result["after_boundary_reached"])
        self.assertEqual(rows[0]["id"], "msg-2")


def _message(message_id, created, text):
    return {
        "id": message_id,
        "roomId": "secret-room-id",
        "personId": "person-id",
        "personEmail": "operator@example.com",
        "personDisplayName": "Operator",
        "created": created,
        "updated": created,
        "text": text,
        "markdown": f"**{text}**",
        "files": ["https://example.invalid/file"],
    }


if __name__ == "__main__":
    unittest.main()
