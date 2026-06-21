import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ais_etr.reportpo_event_bridge import build_reportpo_event_bridge_audit


class ReportpoEventBridgeAuditTests(unittest.TestCase):
    def test_audits_etr_event_number_to_po_lifecycle_bridge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "runtime.sqlite"
            readiness = root / "readiness.csv"
            features = root / "features.csv"
            lifecycle = root / "lifecycle.csv"
            output = root / "event_bridge.csv"
            summary = root / "summary.csv"
            markdown = root / "event_bridge.md"
            _write_db(db)
            _write_readiness(readiness)
            _write_features(features)
            _write_lifecycle(lifecycle)

            result = build_reportpo_event_bridge_audit(
                db,
                readiness,
                features,
                lifecycle,
                output,
                summary,
                markdown,
            )
            rows = {row["webex_message_ref"]: row for row in _read_csv(output)}

            self.assertEqual(result["high_error_rows"], 2)
            self.assertEqual(result["bridge_status_counts"]["event_number_bridge_found"], 1)
            self.assertEqual(result["bridge_status_counts"]["etr_event_number_not_found_in_po"], 1)
            self.assertEqual(rows["msg-safe-1"]["po_event_number_match_status"], "matched")
            self.assertEqual(rows["msg-safe-2"]["po_event_number_match_status"], "no_match")
            self.assertNotIn("raw-message-1", output.read_text(encoding="utf-8-sig"))
            self.assertNotIn("raw-message-1", markdown.read_text(encoding="utf-8-sig"))
            self.assertIn("ReportPO ETR-to-PO Event Bridge Audit", markdown.read_text(encoding="utf-8-sig"))


def _write_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE outage_events (event_id TEXT, webex_message_id TEXT)")
        conn.execute("INSERT INTO outage_events VALUES (?, ?)", ("event-1", "raw-message-1"))
        conn.execute("INSERT INTO outage_events VALUES (?, ?)", ("event-2", "raw-message-2"))
        conn.commit()
    finally:
        conn.close()


def _write_readiness(path: Path) -> None:
    columns = [
        "event_id",
        "webex_message_ref",
        "event_time",
        "device_id",
        "feeder",
        "remaining_actual_minutes",
        "current_absolute_error",
        "notification_time_gate",
    ]
    rows = [
        ["event-1", "msg-safe-1", "2026-06-01T10:00:00", "PFA01R-01", "PFA01", "300", "270", "shadow_etr_candidate"],
        ["event-2", "msg-safe-2", "2026-06-01T10:05:00", "PFA02R-01", "PFA02", "200", "180", "shadow_etr_candidate"],
    ]
    _write_rows(path, columns, rows)


def _write_features(path: Path) -> None:
    columns = [
        "webex_message_id",
        "match_status",
        "event_number",
        "reportpo_device_id",
        "reportpo_event_start_time",
    ]
    rows = [
        ["raw-message-1", "matched", "E1", "PFA01R-01", "2026-06-01 10:00:00"],
        ["raw-message-2", "matched", "E2", "PFA02R-01", "2026-06-01 10:05:00"],
    ]
    _write_rows(path, columns, rows)


def _write_lifecycle(path: Path) -> None:
    columns = [
        "event_number",
        "op_device_id",
        "cr_datetime",
        "ip_datetime",
        "last_restore_datetime",
        "cl_datetime",
        "lifecycle_quality",
    ]
    rows = [["E1", "PFA01R-01", "2026-06-01 10:00:00", "2026-06-01 10:10:00", "2026-06-01 15:00:00", "2026-06-01 16:00:00", "restore_available"]]
    _write_rows(path, columns, rows)


def _write_rows(path: Path, columns: list[str], rows: list[list[str]]) -> None:
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
