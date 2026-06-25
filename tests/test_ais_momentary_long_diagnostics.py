import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.ais_momentary_long_diagnostics import build_ais_momentary_long_diagnostics


class AisMomentaryLongDiagnosticsTests(unittest.TestCase):
    def test_diagnoses_repeat_late_and_early_momentary_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            triage = root / "triage.csv"
            readiness = root / "readiness.csv"
            output = root / "momentary.csv"
            markdown = root / "momentary.md"
            segments = root / "segments.csv"
            _write_triage(triage)
            _write_readiness(readiness)

            result = build_ais_momentary_long_diagnostics(
                triage,
                readiness,
                output,
                markdown,
                segments,
                cluster_gap_minutes=60,
                late_webex_minutes=30,
                high_error_minutes=60,
            )
            rows = {row["event_id"]: row for row in _read_csv(output)}
            pattern_segments = [row for row in _read_csv(segments) if row["dimension"] == "mismatch_pattern"]

            self.assertEqual(result["momentary_long_rows"], 3)
            self.assertEqual(result["repeat_cluster_rows"], 2)
            self.assertEqual(sum(int(row["rows"]) for row in pattern_segments), 3)
            self.assertEqual(rows["event-repeat-2"]["mismatch_pattern"], "repeat_operation_during_active_ais_outage")
            self.assertEqual(rows["event-early"]["mismatch_pattern"], "early_momentary_signal_of_long_ais_outage")
            self.assertEqual(rows["event-repeat-2"]["review_priority"], "P1")
            self.assertNotIn("event-other", rows)
            self.assertNotIn("raw-message", output.read_text(encoding="utf-8-sig"))
            self.assertIn("AIS Momentary-Long Mismatch Diagnostic", markdown.read_text(encoding="utf-8-sig"))


def _write_triage(path: Path) -> None:
    columns = [
        "event_id",
        "webex_message_ref",
        "event_time",
        "district",
        "device_id",
        "feeder",
        "webex_device_interruption_class",
        "event_age_band",
        "ais_elapsed_since_start_minutes",
        "ais_remaining_minutes",
        "current_p50",
        "current_absolute_error",
        "current_covered_q10_q90",
        "ais_matched_site_count",
        "ais_matched_rows",
        "primary_root_cause",
        "root_cause_flags",
    ]
    rows = [
        [
            "event-repeat-1",
            "msg-repeat-1",
            "2026-06-01T10:00:00",
            "พังโคน",
            "SEK06VR-103",
            "SEK06",
            "momentary_le_1m",
            "0_5m",
            "5",
            "160",
            "13",
            "147",
            "FALSE",
            "5",
            "5",
            "webex_momentary_long_ais_interval",
            "webex_momentary_but_ais_sustained",
        ],
        [
            "event-repeat-2",
            "msg-repeat-2",
            "2026-06-01T10:40:00",
            "พังโคน",
            "SEK06VR-103",
            "SEK06",
            "momentary_le_1m",
            "30_60m",
            "45",
            "120",
            "13",
            "107",
            "FALSE",
            "5",
            "5",
            "webex_momentary_long_ais_interval",
            "webex_momentary_but_ais_sustained",
        ],
        [
            "event-early",
            "msg-early",
            "2026-06-01T11:00:00",
            "พังโคน",
            "PFA03VB-01",
            "PFA03",
            "momentary_le_1m",
            "0_5m",
            "1",
            "200",
            "30",
            "170",
            "FALSE",
            "1",
            "1",
            "webex_momentary_long_ais_interval",
            "webex_momentary_but_ais_sustained",
        ],
        [
            "event-other",
            "msg-other",
            "2026-06-01T12:00:00",
            "พังโคน",
            "PFA04R-01",
            "PFA04",
            "sustained_candidate",
            "0_5m",
            "1",
            "70",
            "20",
            "50",
            "FALSE",
            "1",
            "1",
            "model_underestimation",
            "model_underestimated_remaining",
        ],
    ]
    _write_rows(path, columns, rows)


def _write_readiness(path: Path) -> None:
    columns = ["event_id", "webex_open_close_minutes"]
    rows = [
        ["event-repeat-1", "0.08"],
        ["event-repeat-2", "0.08"],
        ["event-early", "0.2"],
        ["event-other", ""],
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
