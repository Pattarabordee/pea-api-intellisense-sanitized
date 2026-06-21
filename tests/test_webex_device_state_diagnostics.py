import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ais_etr.webex_device_state_diagnostics import build_webex_device_state_diagnostic


class WebexDeviceStateDiagnosticTests(unittest.TestCase):
    def test_segments_error_by_parsed_device_state_without_raw_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "runtime.sqlite"
            _write_events(db)
            comparison = root / "comparison.csv"
            _write_comparison(comparison)
            output = root / "device_state.csv"
            markdown = root / "device_state.md"

            result = build_webex_device_state_diagnostic(db, comparison, output, markdown)
            rows = _read_csv(output)

            self.assertEqual(result["with_truth"], 2)
            self.assertEqual(result["class_counts"]["momentary_le_1m"], 1)
            self.assertEqual(result["class_counts"]["sustained_candidate"], 1)
            self.assertEqual(rows[0]["review_action"], "review_before_customer_etr")
            self.assertNotIn("raw text", output.read_text(encoding="utf-8-sig").lower())
            self.assertIn("Webex Device-State Error Diagnostic", markdown.read_text(encoding="utf-8-sig"))


def _write_events(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE outage_events (event_id TEXT, parsed_json TEXT)")
        rows = [
            (
                "event-a",
                {
                    "parsed_fields": {
                        "webex_device_interruption_class": "momentary_le_1m",
                        "webex_open_close_minutes": 0.25,
                    }
                },
            ),
            (
                "event-b",
                {
                    "parsed_fields": {
                        "webex_device_interruption_class": "sustained_candidate",
                        "webex_open_close_minutes": None,
                    }
                },
            ),
        ]
        for event_id, payload in rows:
            conn.execute("INSERT INTO outage_events (event_id, parsed_json) VALUES (?, ?)", (event_id, json.dumps(payload)))
        conn.commit()
    finally:
        conn.close()


def _write_comparison(path: Path) -> None:
    columns = [
        "event_id",
        "webex_message_ref",
        "event_time",
        "device_type",
        "device_id",
        "feeder",
        "actual_restoration_minutes",
        "current_p50",
        "current_absolute_error",
        "current_covered_q10_q90",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow(
            {
                "event_id": "event-a",
                "webex_message_ref": "msg-a",
                "event_time": "2026-06-01T10:00:00",
                "device_type": "Recloser",
                "device_id": "PFA01R-01",
                "feeder": "PFA01",
                "actual_restoration_minutes": "200",
                "current_p50": "20",
                "current_absolute_error": "180",
                "current_covered_q10_q90": "FALSE",
            }
        )
        writer.writerow(
            {
                "event_id": "event-b",
                "webex_message_ref": "msg-b",
                "event_time": "2026-06-01T11:00:00",
                "device_type": "Recloser",
                "device_id": "PFA02R-01",
                "feeder": "PFA02",
                "actual_restoration_minutes": "50",
                "current_p50": "40",
                "current_absolute_error": "10",
                "current_covered_q10_q90": "TRUE",
            }
        )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
