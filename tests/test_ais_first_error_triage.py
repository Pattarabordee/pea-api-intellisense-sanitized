import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ais_etr.ais_first_error_triage import build_ais_first_error_triage


class AisFirstErrorTriageTests(unittest.TestCase):
    def test_classifies_customer_facing_candidates_without_raw_message_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "runtime.sqlite"
            readiness = root / "readiness.csv"
            remaining = root / "remaining.csv"
            ais_truth = root / "ais_truth.csv"
            output = root / "triage.csv"
            markdown = root / "triage.md"
            segments = root / "segments.csv"
            _write_db(db)
            _write_readiness(readiness)
            _write_remaining(remaining)
            _write_ais_truth(ais_truth)

            result = build_ais_first_error_triage(
                db,
                readiness,
                remaining,
                ais_truth,
                output,
                markdown,
                segments,
                high_error_minutes=60,
                late_webex_minutes=30,
            )
            rows = {row["event_id"]: row for row in _read_csv(output)}
            segment_rows = _read_csv(segments)
            root_segments = [row for row in segment_rows if row["dimension"] == "primary_root_cause"]

            self.assertEqual(result["readiness_rows"], 4)
            self.assertEqual(result["customer_facing_candidate_rows"], 3)
            self.assertEqual(result["review_only_rows"], 1)
            self.assertEqual(sum(int(row["candidate_rows"]) for row in root_segments), 3)
            self.assertEqual(rows["event-late"]["primary_root_cause"], "webex_late_after_ais_start")
            self.assertEqual(rows["event-momentary"]["primary_root_cause"], "webex_momentary_long_ais_interval")
            self.assertEqual(rows["event-topology"]["primary_root_cause"], "topology_or_matching_review")
            self.assertIn("blocked_no_shared_key_do_not_use_cl_datetime", rows["event-late"]["reportpo_bridge_policy"])
            self.assertNotIn("event-review", rows)
            self.assertNotIn("raw-message", output.read_text(encoding="utf-8-sig"))
            self.assertNotIn("raw-message", markdown.read_text(encoding="utf-8-sig"))
            self.assertIn("AIS-First Shadow Error Triage", markdown.read_text(encoding="utf-8-sig"))


def _write_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE outage_events (event_id TEXT, webex_message_id TEXT)")
        rows = [
            ("event-late", "raw-message-late"),
            ("event-momentary", "raw-message-momentary"),
            ("event-topology", "raw-message-topology"),
            ("event-review", "raw-message-review"),
        ]
        conn.executemany("INSERT INTO outage_events VALUES (?, ?)", rows)
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
        "match_level",
        "match_confidence",
        "affected_count",
        "webex_device_interruption_class",
        "event_age_band",
        "max_elapsed_since_ais_start_minutes",
        "remaining_actual_minutes",
        "evaluation_policy",
        "notification_time_gate",
        "current_p50",
        "current_q10",
        "current_q90",
        "current_absolute_error",
        "current_covered_q10_q90",
    ]
    rows = [
        [
            "event-late",
            "msg-late",
            "2026-06-01T10:00:00",
            "พังโคน",
            "Recloser",
            "SEK06VR-104",
            "SEK06",
            "recloser",
            "0.9",
            "5",
            "sustained_candidate",
            "30_60m",
            "45",
            "180",
            "sustained_outage_eligible",
            "shadow_etr_candidate",
            "30",
            "10",
            "90",
            "150",
            "FALSE",
        ],
        [
            "event-momentary",
            "msg-momentary",
            "2026-06-01T10:05:00",
            "พังโคน",
            "Recloser",
            "SEK06VR-105",
            "SEK06",
            "recloser",
            "0.9",
            "5",
            "momentary_le_1m",
            "0_5m",
            "5",
            "120",
            "sustained_outage_eligible",
            "shadow_etr_candidate",
            "20",
            "10",
            "80",
            "100",
            "FALSE",
        ],
        [
            "event-topology",
            "msg-topology",
            "2026-06-01T10:10:00",
            "พังโคน",
            "Unknown",
            "PFA01F-01",
            "PFA01",
            "feeder",
            "0.4",
            "1",
            "sustained_candidate",
            "5_15m",
            "10",
            "70",
            "sustained_outage_eligible",
            "shadow_etr_candidate",
            "5",
            "2",
            "25",
            "65",
            "FALSE",
        ],
        [
            "event-review",
            "msg-review",
            "2026-06-01T10:15:00",
            "พังโคน",
            "Recloser",
            "PFA02R-01",
            "PFA02",
            "recloser",
            "0.9",
            "1",
            "sustained_candidate",
            "unknown",
            "",
            "",
            "no_active_ais_interval",
            "review_only",
            "",
            "",
            "",
            "",
            "",
        ],
    ]
    _write_rows(path, columns, rows)


def _write_remaining(path: Path) -> None:
    columns = [
        "webex_message_id",
        "match_status",
        "match_level",
        "matched_ais_rows",
        "matched_site_count",
        "actual_restoration_minutes",
        "max_elapsed_since_ais_start_minutes",
        "truth_quality",
        "truth_notes",
    ]
    rows = [
        ["raw-message-late", "matched", "affected_peano_active_time", "5", "5", "180", "45", "OK", "affected_peano_active_time"],
        ["raw-message-momentary", "matched", "affected_peano_active_time", "5", "5", "120", "5", "OK", "affected_peano_active_time"],
        ["raw-message-topology", "matched", "affected_peano_active_time", "1", "1", "70", "10", "OK", "affected_peano_active_time"],
        ["raw-message-review", "no_match", "", "0", "0", "", "", "", "no active AIS interval"],
    ]
    _write_rows(path, columns, rows)


def _write_ais_truth(path: Path) -> None:
    columns = [
        "webex_message_id",
        "match_status",
        "match_level",
        "matched_ais_rows",
        "matched_site_count",
        "actual_restoration_minutes",
        "truth_quality",
        "truth_notes",
    ]
    rows = [
        ["raw-message-late", "matched", "affected_peano_time", "5", "5", "225", "OK", "truth_cluster_id=x"],
        ["raw-message-momentary", "matched", "affected_peano_time", "5", "5", "125", "OK", "truth_cluster_id=y"],
        ["raw-message-topology", "matched", "affected_peano_time", "1", "1", "80", "OK", "truth_cluster_id=z"],
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
