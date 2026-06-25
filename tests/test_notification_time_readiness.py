import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ais_etr.notification_time_readiness import build_notification_time_readiness


class NotificationTimeReadinessTests(unittest.TestCase):
    def test_builds_customer_facing_gate_from_active_ais_remaining_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "runtime.sqlite"
            _write_runtime(db)
            comparison = root / "comparison.csv"
            remaining = root / "remaining_audit.csv"
            device_state = root / "device_state.csv"
            lifecycle = root / "lifecycle.csv"
            output = root / "notification_time.csv"
            segments = root / "segments.csv"
            markdown = root / "notification_time.md"
            _write_comparison(comparison)
            _write_remaining_audit(remaining)
            _write_device_state(device_state)
            _write_lifecycle(lifecycle)

            result = build_notification_time_readiness(
                db,
                comparison,
                remaining,
                output,
                markdown,
                device_state_csv=device_state,
                lifecycle_audit_csv=lifecycle,
                segments_output=segments,
                min_segment_events=1,
            )
            rows = {row["event_id"]: row for row in _read_csv(output)}

            self.assertEqual(result["events"], 3)
            self.assertEqual(result["active_ais_interval_rows"], 2)
            self.assertEqual(result["sustained_eligible_rows"], 1)
            self.assertEqual(result["customer_facing_candidate_rows"], 1)
            self.assertEqual(rows["event-active"]["notification_time_gate"], "shadow_etr_candidate")
            self.assertEqual(rows["event-no-active"]["notification_time_reason"], "no_active_ais_interval_at_webex_time")
            self.assertEqual(
                rows["event-short"]["notification_time_reason"],
                "short_interruption_review_not_customer_facing_etr_gate",
            )
            self.assertEqual(rows["event-active"]["reportpo_lifecycle_bridge_use"], "matched_audit_only")
            self.assertTrue(segments.exists())
            self.assertIn("Notification-Time ETR Readiness", markdown.read_text(encoding="utf-8-sig"))
            self.assertNotIn("raw-message-active", output.read_text(encoding="utf-8-sig"))
            self.assertNotIn("raw-message-active", markdown.read_text(encoding="utf-8-sig"))


def _write_runtime(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE outage_events (event_id TEXT, webex_message_id TEXT, parsed_json TEXT)")
        rows = [
            ("event-active", "raw-message-active", "sustained_candidate", None),
            ("event-no-active", "raw-message-no-active", "sustained_candidate", None),
            ("event-short", "raw-message-short", "momentary_le_1m", 0.2),
        ]
        for event_id, message_id, device_class, open_close in rows:
            payload = {
                "parsed_fields": {
                    "webex_device_interruption_class": device_class,
                    "webex_open_close_minutes": open_close,
                }
            }
            conn.execute(
                "INSERT INTO outage_events (event_id, webex_message_id, parsed_json) VALUES (?, ?, ?)",
                (event_id, message_id, json.dumps(payload)),
            )
        conn.commit()
    finally:
        conn.close()


def _write_comparison(path: Path) -> None:
    columns = [
        "event_id",
        "webex_message_ref",
        "event_time",
        "district",
        "device_type",
        "device_id",
        "feeder",
        "match_level",
        "match_confidence",
        "affected_count",
        "actual_restoration_minutes",
        "current_p50",
        "current_q10",
        "current_q90",
        "current_absolute_error",
        "current_covered_q10_q90",
        "challenger_p50",
        "challenger_q10",
        "challenger_q90",
        "challenger_absolute_error",
        "challenger_covered_q10_q90",
    ]
    rows = [
        ("event-active", "msg-active", "2026-06-01T10:00:00", "พังโคน", "Recloser", "PFA01R-01", "PFA01", "recloser", "0.95", "1", "45", "30", "10", "60", "15", "TRUE"),
        ("event-no-active", "msg-no-active", "2026-06-01T10:05:00", "พังโคน", "Recloser", "PFA01R-01", "PFA01", "recloser", "0.95", "1", "", "30", "10", "60", "", ""),
        ("event-short", "msg-short", "2026-06-01T10:10:00", "พังโคน", "Recloser", "PFA01R-01", "PFA01", "recloser", "0.95", "1", "3", "30", "10", "60", "27", "FALSE"),
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            data = dict(zip(columns[:16], row))
            data.update(
                {
                    "challenger_p50": data["current_p50"],
                    "challenger_q10": data["current_q10"],
                    "challenger_q90": data["current_q90"],
                    "challenger_absolute_error": data["current_absolute_error"],
                    "challenger_covered_q10_q90": data["current_covered_q10_q90"],
                }
            )
            writer.writerow(data)


def _write_remaining_audit(path: Path) -> None:
    columns = [
        "webex_message_id",
        "match_status",
        "actual_restoration_minutes",
        "max_elapsed_since_ais_start_minutes",
        "truth_quality",
    ]
    rows = [
        ("raw-message-active", "matched", "45", "20", "OK"),
        ("raw-message-no-active", "no_match", "", "", ""),
        ("raw-message-short", "matched", "3", "0.2", "OK"),
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(zip(columns, row)))


def _write_device_state(path: Path) -> None:
    columns = ["event_id", "webex_device_interruption_class", "webex_open_close_minutes"]
    rows = [
        ("event-active", "sustained_candidate", ""),
        ("event-no-active", "sustained_candidate", ""),
        ("event-short", "momentary_le_1m", "0.2"),
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(zip(columns, row)))


def _write_lifecycle(path: Path) -> None:
    columns = ["webex_message_id", "match_status", "job_status_at_notification", "lifecycle_quality"]
    rows = [
        ("raw-message-active", "matched", "in_progress", "restore_available"),
        ("raw-message-no-active", "no_match", "", ""),
        ("raw-message-short", "no_match", "", ""),
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
