import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ais_etr.ais_active_state_challenger import build_active_state_remaining_challenger


class AisActiveStateChallengerTests(unittest.TestCase):
    def test_active_state_remaining_uses_time_respecting_prior_without_meter_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "runtime.sqlite"
            _write_runtime(db, {"event-early": ["6101"], "event-later": ["6101"]})
            readiness = root / "readiness.csv"
            _write_readiness(readiness)
            truth = root / "ais_truth.csv"
            _write_truth(
                truth,
                [
                    ("6101", "2026-01-01 00:00:00", "2026-01-01 02:30:00", "150"),
                    ("6101", "2026-01-02 00:00:00", "2026-01-02 03:00:00", "180"),
                ],
            )
            output = root / "active.csv"
            markdown = root / "active.md"
            segments = root / "segments.csv"

            result = build_active_state_remaining_challenger(
                db,
                readiness,
                truth,
                output,
                markdown,
                segments,
                min_segment_rows=1,
                min_meter_history_rows=1,
                high_error_minutes=60,
            )
            rows = {row["event_id"]: row for row in _read_csv(output)}

            self.assertEqual(result["candidates"], 2)
            self.assertEqual(rows["event-early"]["active_source"], "affected_meter_conditional_duration_prior")
            self.assertEqual(rows["event-later"]["active_source"], "prior_same_device_remaining")
            self.assertGreater(float(rows["event-later"]["active_p50"]), float(rows["event-later"]["current_p50"]))
            self.assertLess(float(rows["event-later"]["active_absolute_error"]), float(rows["event-later"]["current_absolute_error"]))
            self.assertNotIn("6101", output.read_text(encoding="utf-8-sig"))
            self.assertNotIn("6101", markdown.read_text(encoding="utf-8-sig"))
            self.assertIn("active_source", segments.read_text(encoding="utf-8-sig"))


def _write_runtime(path: Path, meters_by_event: dict[str, list[str]]) -> None:
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
        for event_id, meters in meters_by_event.items():
            payload = {
                "mode": "shadow",
                "affected_customers": [{"customer": "AIS", "peano": meter} for meter in meters],
            }
            conn.execute(
                "INSERT INTO notifications (event_id, payload_json) VALUES (?, ?)",
                (event_id, json.dumps(payload)),
            )
        conn.commit()
    finally:
        conn.close()


def _write_readiness(path: Path) -> None:
    columns = [
        "event_id",
        "webex_message_ref",
        "event_time",
        "district",
        "device_type",
        "device_id",
        "feeder",
        "event_age_band",
        "max_elapsed_since_ais_start_minutes",
        "remaining_actual_minutes",
        "affected_count",
        "active_ais_outage_confirmed",
        "notification_time_gate",
        "current_p50",
        "current_q10",
        "current_q90",
    ]
    rows = [
        {
            "event_id": "event-early",
            "webex_message_ref": "msg-early",
            "event_time": "2026-01-10T10:00:00",
            "district": "พังโคน",
            "device_type": "Recloser",
            "device_id": "PFA01R-01",
            "feeder": "PFA01",
            "event_age_band": "15_30m",
            "max_elapsed_since_ais_start_minutes": "30",
            "remaining_actual_minutes": "130",
            "affected_count": "1",
            "active_ais_outage_confirmed": "TRUE",
            "notification_time_gate": "shadow_etr_candidate",
            "current_p50": "20",
            "current_q10": "10",
            "current_q90": "60",
        },
        {
            "event_id": "event-later",
            "webex_message_ref": "msg-later",
            "event_time": "2026-01-10T11:00:00",
            "district": "พังโคน",
            "device_type": "Recloser",
            "device_id": "PFA01R-01",
            "feeder": "PFA01",
            "event_age_band": "15_30m",
            "max_elapsed_since_ais_start_minutes": "45",
            "remaining_actual_minutes": "118",
            "affected_count": "1",
            "active_ais_outage_confirmed": "TRUE",
            "notification_time_gate": "shadow_etr_candidate",
            "current_p50": "20",
            "current_q10": "10",
            "current_q90": "60",
        },
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


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
        for index, (meter, start, restore, actual) in enumerate(rows, 1):
            writer.writerow(
                {
                    "site_id": f"site-{index}",
                    "peano": meter,
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
