import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ais_etr.ais_remaining_truth import match_ais_remaining_truth_to_shadow


class AisRemainingTruthTests(unittest.TestCase):
    def test_matches_only_active_interval_and_uses_remaining_minutes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "runtime.sqlite"
            _write_runtime(db)
            truth = root / "ais_truth.csv"
            _write_truth(truth)
            mapping = root / "mapping.csv"
            audit = root / "audit.csv"

            result = match_ais_remaining_truth_to_shadow(
                db,
                truth,
                mapping,
                audit,
                start_tolerance_minutes=0,
                overwrite=True,
            )
            rows = _read_csv(mapping)
            audit_rows = _read_csv(audit)
            mapped = {row["webex_message_id"]: row for row in rows}

            self.assertEqual(result["matched_rows"], 1)
            self.assertEqual(mapped["message-active"]["actual_restoration_minutes"], "45.0")
            self.assertEqual(mapped["message-active"]["truth_target"], "ais_remaining_restoration_minutes")
            self.assertEqual(mapped["message-cleared"]["actual_restoration_minutes"], "")
            self.assertEqual(audit_rows[1]["match_status"], "no_match")


def _write_runtime(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE outage_events (
                event_id TEXT,
                webex_message_id TEXT,
                event_time TEXT,
                device_id TEXT,
                feeder TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT,
                payload_json TEXT
            )
            """
        )
        events = [
            ("event-active", "message-active", "2026-06-01T10:15:00", "PFA01R-01", "PFA01"),
            ("event-cleared", "message-cleared", "2026-06-01T12:00:00", "PFA01R-01", "PFA01"),
        ]
        for event in events:
            conn.execute(
                "INSERT INTO outage_events (event_id, webex_message_id, event_time, device_id, feeder) VALUES (?, ?, ?, ?, ?)",
                event,
            )
            payload = {"affected_customers": [{"customer": "AIS", "peano": "6101"}]}
            conn.execute(
                "INSERT INTO notifications (event_id, payload_json) VALUES (?, ?)",
                (event[0], json.dumps(payload)),
            )
        conn.commit()
    finally:
        conn.close()


def _write_truth(path: Path) -> None:
    columns = [
        "site_id",
        "peano",
        "outage_start_time",
        "power_restore_time",
        "actual_restoration_minutes",
        "truth_quality",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow(
            {
                "site_id": "site-1",
                "peano": "6101",
                "outage_start_time": "2026-06-01 10:00:00",
                "power_restore_time": "2026-06-01 11:00:00",
                "actual_restoration_minutes": "60",
                "truth_quality": "OK",
            }
        )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
