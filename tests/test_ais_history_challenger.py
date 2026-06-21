import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ais_etr.ais_history_challenger import build_ais_history_challenger


class AisHistoryChallengerTests(unittest.TestCase):
    def test_uses_only_prior_affected_peano_history_and_redacts_peano_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "runtime.sqlite"
            _write_notifications(
                db,
                {
                    "event-1": ["6101"],
                    "event-2": ["9999"],
                },
            )
            comparison = root / "incident.csv"
            _write_comparison(
                comparison,
                [
                    {
                        "event_id": "event-1",
                        "incident_id": "incident-1",
                        "event_time": "2026-01-10T10:00:00",
                        "actual": "30",
                        "current_p50": "100",
                        "current_error": "70",
                    },
                    {
                        "event_id": "event-2",
                        "incident_id": "incident-2",
                        "event_time": "2026-01-10T10:00:00",
                        "actual": "20",
                        "current_p50": "50",
                        "current_error": "30",
                    },
                ],
            )
            truth = root / "ais_truth.csv"
            _write_truth(
                truth,
                [
                    ("6101", "2026-01-01 10:00:00", "20"),
                    ("6101", "2026-01-02 10:00:00", "40"),
                    ("6101", "2026-01-11 10:00:00", "500"),
                    ("6102", "2026-01-03 10:00:00", "60"),
                ],
            )
            output = root / "history.csv"
            markdown = root / "history.md"

            result = build_ais_history_challenger(
                db,
                comparison,
                truth,
                output,
                markdown,
                min_history_rows=2,
                lower_quantile=0.05,
                upper_quantile=0.95,
            )
            rows = _read_csv(output)

            self.assertEqual(result["incidents"], 2)
            self.assertEqual(result["history_usable_incidents"], 2)
            self.assertEqual(rows[0]["history_source"], "affected_peano_history")
            self.assertEqual(rows[0]["history_rows_used"], "2")
            self.assertEqual(rows[0]["history_p50"], "30")
            self.assertEqual(rows[0]["history_absolute_error"], "0")
            self.assertEqual(rows[1]["history_source"], "global_prior")
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
            conn.execute(
                "INSERT INTO notifications (event_id, payload_json) VALUES (?, ?)",
                (event_id, json.dumps(payload)),
            )
        conn.commit()
    finally:
        conn.close()


def _write_comparison(path: Path, rows: list[dict[str, str]]) -> None:
    columns = [
        "event_id",
        "incident_id",
        "event_time",
        "district",
        "device_type",
        "feeder",
        "affected_count",
        "actual_restoration_minutes",
        "current_p50",
        "current_absolute_error",
        "current_covered_q10_q90",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "event_id": row["event_id"],
                    "incident_id": row["incident_id"],
                    "event_time": row["event_time"],
                    "district": "pilot",
                    "device_type": "Recloser",
                    "feeder": "PFA01",
                    "affected_count": "1",
                    "actual_restoration_minutes": row["actual"],
                    "current_p50": row["current_p50"],
                    "current_absolute_error": row["current_error"],
                    "current_covered_q10_q90": "FALSE",
                }
            )


def _write_truth(path: Path, rows: list[tuple[str, str, str]]) -> None:
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
        for index, (peano, outage_start, actual) in enumerate(rows, 1):
            restore = _restore_time(outage_start, actual)
            writer.writerow(
                {
                    "site_id": f"site-{index}",
                    "peano": peano,
                    "outage_start_time": outage_start,
                    "power_restore_time": restore,
                    "actual_restoration_minutes": actual,
                    "truth_quality": "OK",
                }
            )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _restore_time(outage_start: str, actual: str) -> str:
    from datetime import datetime, timedelta

    return (datetime.strptime(outage_start, "%Y-%m-%d %H:%M:%S") + timedelta(minutes=float(actual))).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


if __name__ == "__main__":
    unittest.main()
