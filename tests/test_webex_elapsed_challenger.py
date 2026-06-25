import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ais_etr.webex_elapsed_challenger import build_webex_elapsed_refresh_challenger


class WebexElapsedChallengerTests(unittest.TestCase):
    def test_refresh_uses_latest_pre_restore_webex_elapsed_without_exporting_peano_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "runtime.sqlite"
            _write_runtime(db, {"event-1": "message-1", "event-2": "message-2"}, {"event-1": ["6101"]})
            audit = root / "audit.csv"
            _write_audit(audit)
            comparison = root / "comparison.csv"
            _write_comparison(comparison)
            history = root / "history.csv"
            _write_history(history)
            truth = root / "ais_truth.csv"
            _write_truth(
                truth,
                [
                    ("6101", "2026-01-01 00:00:00", "2026-01-01 02:00:00", "120"),
                    ("6101", "2026-01-02 00:00:00", "2026-01-02 04:00:00", "240"),
                    ("9999", "2026-01-03 00:00:00", "2026-01-03 06:00:00", "360"),
                ],
            )
            output = root / "webex_elapsed.csv"
            markdown = root / "webex_elapsed.md"

            result = build_webex_elapsed_refresh_challenger(
                db,
                comparison,
                audit,
                truth,
                output,
                markdown,
                history_challenger_csv=history,
                min_history_rows=2,
            )

            rows = _read_csv(output)
            self.assertEqual(result["incidents"], 1)
            self.assertEqual(result["incidents_with_elapsed_refresh"], 1)
            self.assertEqual(rows[0]["event_count"], "2")
            self.assertEqual(rows[0]["eligible_refresh_event_count"], "2")
            self.assertEqual(rows[0]["latest_eligible_elapsed_minutes"], "60")
            self.assertGreater(float(rows[0]["refresh_p50"]), float(rows[0]["history_p50"]))
            self.assertLess(float(rows[0]["refresh_absolute_error"]), float(rows[0]["history_absolute_error"]))
            self.assertNotIn("6101", output.read_text(encoding="utf-8-sig"))
            self.assertNotIn("6101", markdown.read_text(encoding="utf-8-sig"))


def _write_runtime(path: Path, message_by_event: dict[str, str], peanos_by_event: dict[str, list[str]]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE outage_events (event_id TEXT, webex_message_id TEXT)")
        conn.execute(
            """
            CREATE TABLE notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT,
                payload_json TEXT
            )
            """
        )
        for event_id, message_id in message_by_event.items():
            conn.execute(
                "INSERT INTO outage_events (event_id, webex_message_id) VALUES (?, ?)",
                (event_id, message_id),
            )
        for event_id, peanos in peanos_by_event.items():
            payload = {
                "mode": "shadow",
                "affected_customers": [{"customer": "AIS", "peano": peano} for peano in peanos],
            }
            conn.execute(
                "INSERT INTO notifications (event_id, payload_json) VALUES (?, ?)",
                (event_id, json.dumps(payload)),
            )
        conn.commit()
    finally:
        conn.close()


def _write_audit(path: Path) -> None:
    columns = ["webex_message_id", "truth_notes"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow({"webex_message_id": "message-1", "truth_notes": "affected_peano_time; truth_cluster_id=ais-same"})
        writer.writerow({"webex_message_id": "message-2", "truth_notes": "affected_peano_time; truth_cluster_id=ais-same"})


def _write_comparison(path: Path) -> None:
    columns = [
        "event_id",
        "event_time",
        "district",
        "device_type",
        "feeder",
        "affected_count",
        "actual_restoration_minutes",
        "current_p50",
        "current_q10",
        "current_q90",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow(
            {
                "event_id": "event-1",
                "event_time": "2026-01-10T10:00:00",
                "district": "พังโคน",
                "device_type": "Recloser",
                "feeder": "PFA01",
                "affected_count": "1",
                "actual_restoration_minutes": "300",
                "current_p50": "30",
                "current_q10": "10",
                "current_q90": "90",
            }
        )
        writer.writerow(
            {
                "event_id": "event-2",
                "event_time": "2026-01-10T11:00:00",
                "district": "พังโคน",
                "device_type": "Recloser",
                "feeder": "PFA01",
                "affected_count": "1",
                "actual_restoration_minutes": "300",
                "current_p50": "30",
                "current_q10": "10",
                "current_q90": "90",
            }
        )


def _write_history(path: Path) -> None:
    columns = ["event_id", "history_p50", "history_q10", "history_q90"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow({"event_id": "event-1", "history_p50": "30", "history_q10": "10", "history_q90": "90"})


def _write_truth(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
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
        for index, (peano, start, restore, actual) in enumerate(rows, 1):
            writer.writerow(
                {
                    "site_id": f"site-{index}",
                    "peano": peano,
                    "outage_start_time": start,
                    "power_restore_time": restore,
                    "actual_restoration_minutes": actual,
                    "truth_quality": "OK",
                }
            )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
