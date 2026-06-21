import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.reportpo_manual_bridge_candidates import build_reportpo_manual_bridge_candidates


class ReportpoManualBridgeCandidateTests(unittest.TestCase):
    def test_suggests_device_feeder_candidate_and_preserves_approved_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bridge = root / "bridge.csv"
            lifecycle = root / "lifecycle.csv"
            manual = root / "manual.csv"
            suggestions = root / "suggestions.csv"
            template = root / "template.csv"
            markdown = root / "summary.md"
            pathfinding = root / "pathfinding.md"
            _write_bridge(bridge)
            _write_lifecycle(lifecycle)
            _write_manual(manual)

            result = build_reportpo_manual_bridge_candidates(
                bridge,
                lifecycle,
                manual,
                suggestions,
                template,
                markdown,
                pathfinding,
                time_window_minutes=120,
                min_template_score=95,
            )
            suggestion_rows = _read_csv(suggestions)
            template_rows = {row["webex_message_ref"]: row for row in _read_csv(template)}
            first = [row for row in suggestion_rows if row["webex_message_ref"] == "msg-safe-1"][0]

            self.assertEqual(result["focus_rows"], 4)
            self.assertGreaterEqual(result["events_with_any_candidate"], 2)
            self.assertEqual(first["candidate_po_event_number"], "PO-1")
            self.assertEqual(first["match_level"], "device_feeder_time")
            self.assertEqual(first["review_status"], "pending")
            self.assertEqual(template_rows["msg-safe-1"]["po_event_number"], "PO-1")
            self.assertEqual(template_rows["msg-safe-1"]["review_status"], "pending")
            self.assertEqual(template_rows["msg-safe-2"]["po_event_number"], "")
            self.assertIn("context-only", template_rows["msg-safe-2"]["notes"])
            self.assertEqual(template_rows["msg-safe-3"]["po_event_number"], "PO-APPROVED")
            self.assertEqual(template_rows["msg-safe-3"]["review_status"], "approved")
            self.assertEqual(template_rows["msg-safe-4"]["po_event_number"], "")
            self.assertIn("administrative close time", template_rows["msg-safe-4"]["notes"])
            self.assertIn("manual review evidence only", markdown.read_text(encoding="utf-8-sig"))
            self.assertIn("ReportPO Manual Bridge Candidate Suggestions", pathfinding.read_text(encoding="utf-8-sig"))
            self.assertNotIn("raw-message", markdown.read_text(encoding="utf-8-sig"))


def _write_bridge(path: Path) -> None:
    columns = [
        "webex_message_ref",
        "event_time",
        "device_id",
        "feeder",
        "reportpo_etr_event_number",
        "reportpo_etr_device_id",
        "reportpo_etr_event_start_time",
    ]
    rows = [
        ["msg-safe-1", "2026-06-01T10:00:00", "DEV-1", "F01", "E1", "DEV-1", "2026-06-01 10:00:00"],
        ["msg-safe-2", "2026-06-01T10:00:00", "DEV-MISSING", "F02", "E2", "DEV-MISSING", "2026-06-01 10:00:00"],
        ["msg-safe-3", "2026-06-01T11:00:00", "DEV-3", "F03", "E3", "DEV-3", "2026-06-01 11:00:00"],
        ["msg-safe-4", "2026-06-01T12:00:00", "DEV-4", "F04", "E4", "DEV-4", "2026-06-01 12:00:00"],
    ]
    _write_rows(path, columns, rows)


def _write_lifecycle(path: Path) -> None:
    columns = [
        "event_number",
        "op_device_id",
        "op_device_gis_tag",
        "feeder",
        "cr_datetime",
        "no_datetime",
        "ip_datetime",
        "last_restore_datetime",
        "cl_datetime",
        "lifecycle_quality",
        "lifecycle_flags",
    ]
    rows = [
        ["PO-1", "DEV-1", "", "F01", "2026-06-01 10:03:00", "", "", "", "", "restore_available", ""],
        ["PO-FEEDER", "OTHER-2", "", "F02", "2026-06-01 10:04:00", "", "", "", "", "restore_available", ""],
        ["PO-LATE", "DEV-1", "", "F01", "2026-06-02 10:00:00", "", "", "", "", "restore_available", ""],
        ["PO-CLOSE", "DEV-4", "", "F04", "", "", "", "", "2026-06-01 12:04:00", "restore_available", ""],
    ]
    _write_rows(path, columns, rows)


def _write_manual(path: Path) -> None:
    columns = [
        "webex_message_ref",
        "reportpo_etr_event_number",
        "shared_job_id_or_ticket_id",
        "po_event_number",
        "review_status",
        "reviewed_by",
        "reviewed_at",
        "notes",
    ]
    rows = [
        ["msg-safe-3", "E3", "", "PO-APPROVED", "approved", "tester", "2026-06-18", "already reviewed"],
    ]
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
