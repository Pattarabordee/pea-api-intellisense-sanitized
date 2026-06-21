import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.reportpo_bridge_request_pack import build_reportpo_bridge_request_pack


class ReportpoBridgeRequestPackTests(unittest.TestCase):
    def test_builds_shared_key_request_pack_without_raw_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_bridge = root / "event_bridge.csv"
            markdown = root / "pack.md"
            priority = root / "priority.csv"
            _write_event_bridge(event_bridge)

            result = build_reportpo_bridge_request_pack(event_bridge, markdown, priority, top_limit=1)
            rows = _read_csv(priority)

            self.assertEqual(result["rows"], 2)
            self.assertEqual(result["priority_rows"], 1)
            self.assertEqual(rows[0]["webex_message_ref"], "msg-safe-1")
            self.assertIn("shared_job_id_or_ticket_id", markdown.read_text(encoding="utf-8-sig"))
            self.assertNotIn("raw-message", markdown.read_text(encoding="utf-8-sig"))
            self.assertNotIn("raw-message", priority.read_text(encoding="utf-8-sig"))


def _write_event_bridge(path: Path) -> None:
    columns = [
        "webex_message_ref",
        "event_time",
        "device_id",
        "feeder",
        "reportpo_etr_event_number",
        "remaining_actual_minutes",
        "current_absolute_error",
        "bridge_status",
    ]
    rows = [
        ["msg-safe-1", "2026-06-01T10:00:00", "SEK06VR-104", "SEK06", "E1", "300", "270", "etr_event_number_not_found_in_po"],
        ["msg-safe-2", "2026-06-01T10:05:00", "PFA01R-01", "PFA01", "E2", "100", "80", "no_etr_feature_match"],
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(zip(columns, row)))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
