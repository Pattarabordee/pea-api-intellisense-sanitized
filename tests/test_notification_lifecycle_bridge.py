import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ais_etr.notification_lifecycle_bridge import build_notification_lifecycle_bridge_audit


class NotificationLifecycleBridgeAuditTests(unittest.TestCase):
    def test_prioritizes_high_error_rows_without_raw_message_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "runtime.sqlite"
            readiness = root / "readiness.csv"
            features = root / "features.csv"
            output = root / "bridge.csv"
            summary = root / "summary.csv"
            markdown = root / "bridge.md"
            _write_db(db)
            _write_readiness(readiness)
            _write_features(features)

            result = build_notification_lifecycle_bridge_audit(
                db,
                readiness,
                output,
                summary,
                markdown,
                feature_audit_csv=features,
                high_error_threshold_minutes=60,
            )
            rows = _read_csv(output)

            self.assertEqual(result["high_error_candidate_rows"], 2)
            self.assertEqual(result["exported_priority_rows"], 2)
            self.assertEqual(rows[0]["webex_message_ref"], "msg-safe-1")
            self.assertEqual(rows[0]["bridge_gap"], "feature_match_without_po_lifecycle")
            self.assertEqual(rows[1]["bridge_gap"], "momentary_webex_but_long_active_ais")
            self.assertNotIn("raw-message-1", output.read_text(encoding="utf-8-sig"))
            self.assertNotIn("raw-message-1", markdown.read_text(encoding="utf-8-sig"))
            self.assertIn("Notification Lifecycle Bridge Audit", markdown.read_text(encoding="utf-8-sig"))


def _write_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE outage_events (event_id TEXT, webex_message_id TEXT)")
        conn.execute("INSERT INTO outage_events VALUES (?, ?)", ("event-1", "raw-message-1"))
        conn.execute("INSERT INTO outage_events VALUES (?, ?)", ("event-2", "raw-message-2"))
        conn.execute("INSERT INTO outage_events VALUES (?, ?)", ("event-3", "raw-message-3"))
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
        "webex_device_interruption_class",
        "event_age_band",
        "remaining_actual_minutes",
        "current_p50",
        "current_absolute_error",
        "current_covered_q10_q90",
        "notification_time_gate",
        "reportpo_lifecycle_bridge_use",
        "reportpo_lifecycle_match_status",
        "reportpo_job_status_at_notification",
        "reportpo_lifecycle_quality",
    ]
    rows = [
        ["event-1", "msg-safe-1", "2026-06-01T10:00:00", "พังโคน", "Recloser", "PFA01R-01", "PFA01", "sustained_candidate", "0_5m", "300", "30", "270", "FALSE", "shadow_etr_candidate", "not_available", "no_match", "", ""],
        ["event-2", "msg-safe-2", "2026-06-01T10:05:00", "พังโคน", "Recloser", "PFA02R-01", "PFA02", "momentary_le_1m", "0_5m", "200", "20", "180", "FALSE", "shadow_etr_candidate", "matched_audit_only", "matched", "in_progress", "restore_available"],
        ["event-3", "msg-safe-3", "2026-06-01T10:10:00", "พังโคน", "Recloser", "PFA03R-01", "PFA03", "sustained_candidate", "0_5m", "30", "25", "5", "TRUE", "shadow_etr_candidate", "not_available", "no_match", "", ""],
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(zip(columns, row)))


def _write_features(path: Path) -> None:
    columns = ["webex_message_id", "match_status", "event_status", "etr_type_description"]
    rows = [
        ["raw-message-1", "matched", "RealTime+Fast", "ETR RealTime"],
        ["raw-message-2", "no_match", "", ""],
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
