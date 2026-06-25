import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ais_etr.long_outage_challenger import build_long_outage_refresh_challenger


class LongOutageChallengerTests(unittest.TestCase):
    def test_refresh_uses_active_alarm_state_without_exporting_peano_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "runtime.sqlite"
            _write_notifications(db, {"event-1": ["6101"]})
            comparison = root / "incident.csv"
            _write_comparison(comparison)
            history = root / "history.csv"
            _write_history(history)
            truth = root / "ais_truth.csv"
            _write_truth(
                truth,
                [
                    ("6101", "2026-01-01 00:00:00", "2026-01-01 02:00:00", "120"),
                    ("6101", "2026-01-02 00:00:00", "2026-01-02 04:00:00", "240"),
                    ("6101", "2026-01-10 09:30:00", "2026-01-10 14:30:00", "300"),
                ],
            )
            output = root / "long.csv"
            markdown = root / "long.md"

            result = build_long_outage_refresh_challenger(
                db,
                comparison,
                truth,
                output,
                markdown,
                history_challenger_csv=history,
                horizons_minutes=(0, 60),
                min_history_rows=2,
            )
            rows = _read_csv(output)
            horizon_60 = next(row for row in rows if row["horizon_minutes"] == "60")

            self.assertEqual(result["incidents"], 1)
            self.assertEqual(horizon_60["active_alarm_count"], "1")
            self.assertEqual(horizon_60["active_peano_count"], "1")
            self.assertEqual(horizon_60["max_active_elapsed_minutes"], "90")
            self.assertGreater(float(horizon_60["refresh_p50"]), float(horizon_60["baseline_p50"]))
            self.assertNotIn("6101", output.read_text(encoding="utf-8-sig"))
            self.assertNotIn("6101", markdown.read_text(encoding="utf-8-sig"))


def _write_notifications(path: Path, peanos_by_event: dict[str, list[str]]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT,
                payload_json TEXT
            )
            """
        )
        for event_id, peanos in peanos_by_event.items():
            payload = {
                "mode": "shadow",
                "affected_customers": [{"customer": "AIS", "peano": peano} for peano in peanos],
            }
            conn.execute("INSERT INTO notifications (event_id, payload_json) VALUES (?, ?)", (event_id, json.dumps(payload)))
        conn.commit()
    finally:
        conn.close()


def _write_comparison(path: Path) -> None:
    columns = [
        "event_id",
        "incident_id",
        "event_time",
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
                "incident_id": "incident-1",
                "event_time": "2026-01-10T10:00:00",
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
