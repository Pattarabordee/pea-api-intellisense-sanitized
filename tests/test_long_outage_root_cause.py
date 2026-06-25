import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.long_outage_root_cause import build_long_outage_root_cause_pack


class LongOutageRootCauseTests(unittest.TestCase):
    def test_builds_priority_pack_and_uses_only_approved_lifecycle_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "active.csv"
            shared_key = root / "shared_key.csv"
            manual_bridge = root / "manual_bridge.csv"
            lifecycle_review = root / "review.csv"
            priority = root / "priority.csv"
            markdown = root / "priority.md"
            review_template = root / "review_template.csv"
            _write_active_state(active)
            _write_shared_key(shared_key)
            _write_manual_bridge(manual_bridge)
            _write_lifecycle_review(lifecycle_review)

            result = build_long_outage_root_cause_pack(
                active,
                priority,
                markdown,
                review_template,
                shared_key_audit_csv=shared_key,
                manual_bridge_csv=manual_bridge,
                lifecycle_review_csv=lifecycle_review,
                high_error_minutes=60,
                duration_outlier_minutes=480,
                sparse_history_min_rows=5,
            )
            rows = _read_csv(priority)
            by_ref = {row["event_ref"]: row for row in rows}
            template_rows = {row["event_ref"]: row for row in _read_csv(review_template)}

            self.assertEqual(result["priority_rows"], 3)
            self.assertEqual(rows[0]["event_ref"], "msg-high")
            self.assertIn("missing_lifecycle", rows[0]["suspected_gap"])
            self.assertIn("duration_outlier", rows[0]["suspected_gap"])
            self.assertEqual(by_ref["msg-approved"]["lifecycle_bridge_status"], "owner_approved_manual_bridge_context")
            self.assertIn("outage_cause", by_ref["msg-approved"]["approved_context_fields"])
            self.assertNotIn("missing_cause", by_ref["msg-approved"]["suspected_gap"])
            self.assertEqual(by_ref["msg-cldt"]["lifecycle_bridge_status"], "blocked_cl_datetime_not_truth")
            self.assertIn("missing_lifecycle", by_ref["msg-cldt"]["suspected_gap"])
            self.assertEqual(template_rows["msg-approved"]["review_status"], "approved")
            self.assertEqual(template_rows["msg-approved"]["outage_cause"], "tree")
            self.assertNotIn("Y2lzY29", priority.read_text(encoding="utf-8-sig"))
            self.assertNotIn("6101", priority.read_text(encoding="utf-8-sig"))
            self.assertIn("Top Missing Feature Lanes", markdown.read_text(encoding="utf-8-sig"))

    def test_missing_lifecycle_sources_create_blocker_without_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "active.csv"
            priority = root / "priority.csv"
            _write_active_state(active)

            result = build_long_outage_root_cause_pack(active, priority, top_limit=2)
            rows = _read_csv(priority)

            self.assertEqual(result["priority_rows"], 2)
            self.assertEqual(result["shared_key_bridge_status"], "missing_lifecycle_bridge")
            self.assertTrue(all("missing_lifecycle" in row["suspected_gap"] for row in rows))


def _write_active_state(path: Path) -> None:
    columns = [
        "webex_message_ref",
        "event_time",
        "district",
        "feeder",
        "device_id",
        "event_age_band",
        "active_elapsed_minutes",
        "remaining_actual_minutes",
        "current_p50",
        "active_p50",
        "active_absolute_error",
        "active_covered_q10_q90",
        "error_delta_active_minus_current",
        "active_source",
        "active_rows_used",
    ]
    rows = [
        {
            "webex_message_ref": "msg-high",
            "event_time": "2026-05-13T10:30:06",
            "district": "พังโคน",
            "feeder": "WWA10",
            "device_id": "WWA10VR-101",
            "event_age_band": "0_5m",
            "active_elapsed_minutes": "0",
            "remaining_actual_minutes": "804.48",
            "current_p50": "28",
            "active_p50": "28",
            "active_absolute_error": "776.48",
            "active_covered_q10_q90": "FALSE",
            "error_delta_active_minus_current": "0",
            "active_source": "affected_meter_conditional_duration_prior",
            "active_rows_used": "3",
        },
        {
            "webex_message_ref": "msg-approved",
            "event_time": "2026-04-28T23:27:43",
            "district": "พังโคน",
            "feeder": "SEK06",
            "device_id": "SEK06VR-105",
            "event_age_band": "0_5m",
            "active_elapsed_minutes": "0",
            "remaining_actual_minutes": "530.84",
            "current_p50": "13",
            "active_p50": "148.47",
            "active_absolute_error": "382.37",
            "active_covered_q10_q90": "FALSE",
            "error_delta_active_minus_current": "-135.47",
            "active_source": "prior_same_device_remaining",
            "active_rows_used": "8",
        },
        {
            "webex_message_ref": "msg-cldt",
            "event_time": "2026-03-24T17:34:33",
            "district": "พังโคน",
            "feeder": "PFA09",
            "device_id": "PFA09R-03",
            "event_age_band": "0_5m",
            "active_elapsed_minutes": "0",
            "remaining_actual_minutes": "811",
            "current_p50": "36",
            "active_p50": "36",
            "active_absolute_error": "775",
            "active_covered_q10_q90": "FALSE",
            "error_delta_active_minus_current": "0",
            "active_source": "affected_meter_conditional_duration_prior",
            "active_rows_used": "2",
        },
        {
            "webex_message_ref": "msg-low",
            "event_time": "2026-03-24T18:00:00",
            "district": "พังโคน",
            "feeder": "PFA01",
            "device_id": "PFA01R-01",
            "event_age_band": "0_5m",
            "active_elapsed_minutes": "0",
            "remaining_actual_minutes": "20",
            "current_p50": "18",
            "active_p50": "18",
            "active_absolute_error": "2",
            "active_covered_q10_q90": "TRUE",
            "error_delta_active_minus_current": "0",
            "active_source": "prior_same_feeder_remaining",
            "active_rows_used": "10",
        },
    ]
    _write_rows(path, columns, rows)


def _write_shared_key(path: Path) -> None:
    columns = ["status", "decision", "focus_overlap_rows", "overlap_left_rows", "overlap_right_rows"]
    _write_rows(path, columns, [{"status": "no_overlap", "decision": "not_usable_for_lifecycle_bridge"}])


def _write_manual_bridge(path: Path) -> None:
    columns = ["webex_message_ref", "shared_job_id_or_ticket_id", "po_event_number", "review_status"]
    _write_rows(
        path,
        columns,
        [
            {
                "webex_message_ref": "msg-high",
                "shared_job_id_or_ticket_id": "",
                "po_event_number": "",
                "review_status": "pending",
            },
            {
                "webex_message_ref": "msg-approved",
                "shared_job_id_or_ticket_id": "JOB-1",
                "po_event_number": "PO-1",
                "review_status": "approved",
            },
        ],
    )


def _write_lifecycle_review(path: Path) -> None:
    columns = [
        "event_ref",
        "outage_cause",
        "work_type",
        "crew_dispatch_time",
        "first_restore_time",
        "review_status",
        "cl_datetime",
    ]
    _write_rows(
        path,
        columns,
        [
            {
                "event_ref": "msg-high",
                "outage_cause": "storm",
                "work_type": "repair",
                "crew_dispatch_time": "2026-05-13 10:50:00",
                "first_restore_time": "2026-05-13 23:55:00",
                "review_status": "pending",
                "cl_datetime": "",
            },
            {
                "event_ref": "msg-approved",
                "outage_cause": "tree",
                "work_type": "cut_clear",
                "crew_dispatch_time": "2026-04-29 00:00:00",
                "first_restore_time": "2026-04-29 08:00:00",
                "review_status": "approved",
                "cl_datetime": "",
            },
            {
                "event_ref": "msg-cldt",
                "outage_cause": "",
                "work_type": "",
                "crew_dispatch_time": "",
                "first_restore_time": "",
                "review_status": "approved",
                "cl_datetime": "2026-03-25 08:00:00",
            },
        ],
    )


def _write_rows(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
