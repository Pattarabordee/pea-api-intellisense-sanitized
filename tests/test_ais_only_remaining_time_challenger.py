import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ais_etr.ais_only_remaining_time_challenger import build_ais_only_remaining_time_challenger


class AisOnlyRemainingTimeChallengerTests(unittest.TestCase):
    def test_uses_time_respecting_affected_history_and_tail_uplift_without_meter_leakage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "runtime.sqlite"
            readiness = root / "readiness.csv"
            notification = root / "notification.csv"
            truth = root / "truth.csv"
            active_state = root / "active.csv"
            output = root / "challenger.csv"
            markdown = root / "challenger.md"
            segments = root / "segments.csv"

            _write_runtime_db(db)
            _write_readiness(readiness)
            _write_notification(notification)
            _write_truth(truth)
            _write_active_state(active_state)

            result = build_ais_only_remaining_time_challenger(
                db,
                readiness,
                notification,
                truth,
                output,
                markdown,
                segments,
                active_state_csv=active_state,
                min_affected_history_rows=1,
                min_segment_rows=1,
                tail_uplift_threshold_minutes=180,
                high_error_minutes=60,
            )
            rows = _read_csv(output)
            by_event = {row["event_id"]: row for row in rows}
            out_text = output.read_text(encoding="utf-8-sig")
            md_text = markdown.read_text(encoding="utf-8-sig")

            self.assertEqual(result["candidates"], 3)
            self.assertEqual(by_event["event-current"]["challenger_source"], "affected_meter_history")
            self.assertEqual(by_event["event-current"]["challenger_rows_used"], "1")
            self.assertEqual(by_event["event-current"]["tail_uplift_applied"], "TRUE")
            self.assertEqual(by_event["event-current"]["challenger_p50"], "240")
            self.assertEqual(by_event["event-current"]["challenger_q90"], "240")
            self.assertNotIn("999", by_event["event-current"]["selected_q90"])
            self.assertEqual(by_event["event-device"]["challenger_source"], "prior_same_device_remaining")
            self.assertNotIn("event-webex-only", by_event)
            self.assertNotIn("event-pea", by_event)
            self.assertNotIn("6101000001", out_text)
            self.assertNotIn("verbatim WebEx body", md_text)
            self.assertIn("AIS-Only Remaining-Time Challenger", md_text)


def _write_runtime_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE notifications (id INTEGER PRIMARY KEY, event_id TEXT, payload_json TEXT)")
        payload = {
            "affected_customers": [
                {"customer": "AIS", "peano": "REDACTED-METER-0000"},
            ]
        }
        conn.execute(
            "INSERT INTO notifications (event_id, payload_json) VALUES (?, ?)",
            ("event-current", json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()


def _write_readiness(path: Path) -> None:
    columns = [
        "source_lane",
        "event_id",
        "event_ref",
        "event_time",
        "district",
        "feeder",
        "device_id",
        "match_level",
        "affected_count",
        "actual_restoration_minutes",
        "model_metric_included",
        "current_p50",
        "current_q10",
        "current_q90",
        "current_absolute_error",
        "current_covered_q10_q90",
    ]
    _write_rows(
        path,
        columns,
        [
            {
                "source_lane": "ais_truth_matched",
                "event_id": "event-prior-device",
                "event_ref": "msg-prior-device",
                "event_time": "2026-01-01T00:00:00",
                "district": "พังโคน",
                "feeder": "PFA02",
                "device_id": "PFA02R-01",
                "match_level": "recloser",
                "affected_count": "1",
                "actual_restoration_minutes": "120",
                "model_metric_included": "true",
                "current_p50": "30",
                "current_q10": "10",
                "current_q90": "50",
                "current_absolute_error": "90",
                "current_covered_q10_q90": "FALSE",
            },
            {
                "source_lane": "webex_trigger_no_ais_truth",
                "event_id": "event-webex-only",
                "event_ref": "msg-webex-only",
                "event_time": "2026-01-01T01:00:00",
                "feeder": "PFA02",
                "device_id": "PFA02R-01",
                "model_metric_included": "false",
                "current_p50": "999",
            },
            {
                "source_lane": "pea_quarantined",
                "event_id": "event-pea",
                "event_ref": "msg-pea",
                "event_time": "2026-01-01T01:30:00",
                "feeder": "PFA02",
                "device_id": "PFA02R-01",
                "model_metric_included": "false",
                "current_p50": "999",
            },
            {
                "source_lane": "ais_truth_matched",
                "event_id": "event-current",
                "event_ref": "msg-current",
                "event_time": "2026-01-02T00:00:00",
                "district": "พังโคน",
                "feeder": "PFA02",
                "device_id": "PFA02R-01",
                "match_level": "recloser",
                "affected_count": "1",
                "actual_restoration_minutes": "220",
                "model_metric_included": "true",
                "current_p50": "20",
                "current_q10": "5",
                "current_q90": "30",
                "current_absolute_error": "200",
                "current_covered_q10_q90": "FALSE",
            },
            {
                "source_lane": "ais_truth_matched",
                "event_id": "event-device",
                "event_ref": "msg-device",
                "event_time": "2026-01-03T00:00:00",
                "district": "พังโคน",
                "feeder": "PFA02",
                "device_id": "PFA02R-01",
                "match_level": "recloser",
                "affected_count": "1",
                "actual_restoration_minutes": "130",
                "model_metric_included": "true",
                "current_p50": "40",
                "current_q10": "10",
                "current_q90": "60",
                "current_absolute_error": "90",
                "current_covered_q10_q90": "FALSE",
            },
        ],
    )


def _write_notification(path: Path) -> None:
    _write_rows(
        path,
        ["webex_message_ref", "max_elapsed_since_ais_start_minutes", "event_age_band", "webex_device_interruption_class"],
        [
            {"webex_message_ref": "msg-current", "max_elapsed_since_ais_start_minutes": "0", "event_age_band": "0_5m", "webex_device_interruption_class": "sustained_candidate"},
            {"webex_message_ref": "msg-device", "max_elapsed_since_ais_start_minutes": "0", "event_age_band": "0_5m", "webex_device_interruption_class": "sustained_candidate"},
        ],
    )


def _write_truth(path: Path) -> None:
    _write_rows(
        path,
        [
            "peano",
            "outage_start_time",
            "power_restore_time",
            "actual_restoration_minutes",
            "truth_quality",
        ],
        [
            {
                "peano": "REDACTED-METER-0000",
                "outage_start_time": "2025-12-30 00:00:00",
                "power_restore_time": "2025-12-30 04:00:00",
                "actual_restoration_minutes": "240",
                "truth_quality": "OK",
            },
            {
                "peano": "REDACTED-METER-0000",
                "outage_start_time": "2026-01-04 00:00:00",
                "power_restore_time": "2026-01-04 16:39:00",
                "actual_restoration_minutes": "999",
                "truth_quality": "OK",
            },
        ],
    )


def _write_active_state(path: Path) -> None:
    _write_rows(
        path,
        ["webex_message_ref", "active_elapsed_minutes", "active_p50", "active_absolute_error", "active_covered_q10_q90"],
        [
            {"webex_message_ref": "msg-current", "active_elapsed_minutes": "0", "active_p50": "150", "active_absolute_error": "70", "active_covered_q10_q90": "TRUE"}
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
