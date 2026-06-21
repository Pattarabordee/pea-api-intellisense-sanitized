import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ais_etr.incident_clustering import build_shadow_incident_clusters, build_shadow_incident_replay_report


class IncidentClusteringTests(unittest.TestCase):
    def test_clusters_repeated_webex_events_by_truth_cluster_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "runtime.sqlite"
            _write_db(
                db,
                {
                    "event-1": "full-msg-1",
                    "event-2": "full-msg-2",
                    "event-3": "full-msg-3",
                },
            )
            comparison = root / "comparison.csv"
            _write_comparison(
                comparison,
                [
                    {
                        "event_id": "event-1",
                        "webex_message_ref": "msg-redacted-1",
                        "event_time": "2026-06-17T10:00:00",
                        "feeder": "PFA01",
                        "device_type": "Recloser",
                        "device_id": "PFA01R-01",
                        "actual_restoration_minutes": "100.0",
                        "current_p50": "40.0",
                        "current_q10": "20.0",
                        "current_q90": "90.0",
                        "challenger_p50": "50.0",
                        "challenger_q10": "30.0",
                        "challenger_q90": "120.0",
                        "affected_count": "2",
                    },
                    {
                        "event_id": "event-2",
                        "webex_message_ref": "msg-redacted-2",
                        "event_time": "2026-06-17T10:30:00",
                        "feeder": "PFA01",
                        "device_type": "Recloser",
                        "device_id": "PFA01R-02",
                        "actual_restoration_minutes": "100.0",
                        "current_p50": "80.0",
                        "current_q10": "60.0",
                        "current_q90": "110.0",
                        "challenger_p50": "80.0",
                        "challenger_q10": "60.0",
                        "challenger_q90": "110.0",
                        "affected_count": "4",
                    },
                    {
                        "event_id": "event-3",
                        "webex_message_ref": "msg-redacted-3",
                        "event_time": "2026-06-17T11:00:00",
                        "feeder": "PFA02",
                        "device_type": "CB",
                        "device_id": "PFA02VB-01",
                        "actual_restoration_minutes": "30.0",
                        "current_p50": "20.0",
                        "current_q10": "10.0",
                        "current_q90": "40.0",
                        "challenger_p50": "20.0",
                        "challenger_q10": "10.0",
                        "challenger_q90": "40.0",
                        "affected_count": "1",
                    },
                ],
            )
            audit = root / "audit.csv"
            _write_audit(
                audit,
                [
                    ("full-msg-1", "truth_cluster_id=ais-same; best_delta_min=1"),
                    ("full-msg-2", "truth_cluster_id=ais-same; best_delta_min=31"),
                    ("full-msg-3", "truth_cluster_id=ais-other; best_delta_min=2"),
                ],
            )

            output = root / "incident.csv"
            markdown = root / "incident.md"
            result = build_shadow_incident_clusters(db, comparison, audit, output, markdown)
            rows = _read_csv(output)

            self.assertEqual(result["source_events_with_truth"], 3)
            self.assertEqual(result["incidents"], 2)
            self.assertEqual(result["compressed_events"], 1)
            self.assertEqual(rows[0]["incident_id"], "ais-same")
            self.assertEqual(rows[0]["event_count"], "2")
            self.assertEqual(rows[0]["event_id"], "event-1")
            self.assertEqual(rows[0]["affected_count"], "4")
            self.assertEqual(rows[0]["current_absolute_error"], "60.0")
            self.assertEqual(rows[0]["current_covered_q10_q90"], "FALSE")
            self.assertEqual(rows[0]["challenger_covered_q10_q90"], "TRUE")
            self.assertNotIn("full-msg-1", output.read_text(encoding="utf-8-sig"))
            self.assertIn("Incident clusters: 2", markdown.read_text(encoding="utf-8-sig"))

    def test_replay_report_compares_raw_rows_to_clustered_incidents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "runtime.sqlite"
            _write_db(
                db,
                {
                    "event-1": "full-msg-1",
                    "event-2": "full-msg-2",
                    "event-3": "full-msg-3",
                },
            )
            comparison = root / "comparison.csv"
            _write_comparison(
                comparison,
                [
                    {
                        "event_id": "event-1",
                        "webex_message_ref": "msg-redacted-1",
                        "event_time": "2026-06-17T10:00:00",
                        "feeder": "SEK06",
                        "device_type": "Recloser",
                        "device_id": "SEK06VR-103",
                        "actual_restoration_minutes": "100.0",
                        "current_p50": "40.0",
                        "current_q10": "20.0",
                        "current_q90": "90.0",
                        "current_absolute_error": "60.0",
                        "current_covered_q10_q90": "FALSE",
                        "affected_count": "2",
                    },
                    {
                        "event_id": "event-2",
                        "webex_message_ref": "msg-redacted-2",
                        "event_time": "2026-06-17T10:30:00",
                        "feeder": "SEK06",
                        "device_type": "Recloser",
                        "device_id": "SEK06VR-105",
                        "actual_restoration_minutes": "100.0",
                        "current_p50": "80.0",
                        "current_q10": "60.0",
                        "current_q90": "110.0",
                        "current_absolute_error": "20.0",
                        "current_covered_q10_q90": "TRUE",
                        "affected_count": "4",
                    },
                    {
                        "event_id": "event-3",
                        "webex_message_ref": "msg-redacted-3",
                        "event_time": "2026-06-17T11:00:00",
                        "feeder": "PFA02",
                        "device_type": "CB",
                        "device_id": "PFA02VB-01",
                        "actual_restoration_minutes": "30.0",
                        "current_p50": "20.0",
                        "current_q10": "10.0",
                        "current_q90": "40.0",
                        "current_absolute_error": "10.0",
                        "current_covered_q10_q90": "TRUE",
                        "affected_count": "1",
                    },
                ],
            )
            audit = root / "audit.csv"
            _write_audit(
                audit,
                [
                    ("full-msg-1", "truth_cluster_id=ais-same; best_delta_min=1"),
                    ("full-msg-2", "truth_cluster_id=ais-same; best_delta_min=31"),
                    ("full-msg-3", "truth_cluster_id=ais-other; best_delta_min=2"),
                ],
            )
            incident = root / "incident.csv"
            build_shadow_incident_clusters(db, comparison, audit, incident)

            output = root / "replay.csv"
            markdown = root / "replay.md"
            result = build_shadow_incident_replay_report(
                db,
                comparison,
                audit,
                incident,
                output,
                markdown,
                focus_feeders=("SEK06",),
                focus_devices=("SEK06VR-103",),
            )
            rows = {(row["segment"], row["grain"]): row for row in _read_csv(output)}

            self.assertEqual(result["raw_webex_events_with_truth"], 3)
            self.assertEqual(result["clustered_incidents"], 2)
            self.assertEqual(result["compressed_events"], 1)
            self.assertEqual(rows[("all_truth", "raw_webex_events")]["q50_mae_minutes"], "30.0")
            self.assertEqual(rows[("all_truth", "clustered_incidents")]["q50_mae_minutes"], "35.0")
            self.assertEqual(rows[("repeated_incidents", "raw_webex_events")]["source_webex_events"], "2")
            self.assertEqual(rows[("repeated_incidents", "clustered_incidents")]["incidents"], "1")
            self.assertEqual(rows[("feeder:SEK06", "clustered_incidents")]["source_webex_events"], "2")
            self.assertNotIn("full-msg-1", output.read_text(encoding="utf-8-sig"))
            self.assertIn("AIS Shadow Incident Replay Report", markdown.read_text(encoding="utf-8-sig"))


def _write_db(path: Path, message_by_event: dict[str, str]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE outage_events (event_id TEXT, webex_message_id TEXT)")
        conn.executemany(
            "INSERT INTO outage_events (event_id, webex_message_id) VALUES (?, ?)",
            list(message_by_event.items()),
        )
        conn.commit()
    finally:
        conn.close()


def _write_comparison(path: Path, rows: list[dict[str, str]]) -> None:
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
        "truth_source",
        "current_model_version",
        "current_p50",
        "current_q10",
        "current_q90",
        "current_risk_level",
        "current_absolute_error",
        "current_covered_q10_q90",
        "challenger_model_version",
        "challenger_p50",
        "challenger_q10",
        "challenger_q90",
        "challenger_risk_level",
        "challenger_absolute_error",
        "challenger_covered_q10_q90",
        "p50_delta_challenger_minus_current",
        "absolute_error_delta_challenger_minus_current",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            defaults = {
                "district": "พังโคน",
                "match_level": "affected_peano_time",
                "match_confidence": "0.9",
                "truth_source": "ais_site_power_status",
                "current_model_version": "current",
                "challenger_model_version": "challenger",
            }
            values = defaults | row
            writer.writerow({column: values.get(column, "") for column in columns})


def _write_audit(path: Path, rows: list[tuple[str, str]]) -> None:
    columns = [
        "webex_message_id",
        "webex_event_time",
        "webex_event_number",
        "webex_device_id",
        "webex_feeder",
        "match_status",
        "match_level",
        "matched_ais_rows",
        "matched_site_count",
        "matched_peano_count",
        "actual_restoration_minutes",
        "selected_event_number",
        "truth_quality",
        "truth_notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for message_id, notes in rows:
            writer.writerow(
                {
                    "webex_message_id": message_id,
                    "match_status": "matched",
                    "match_level": "affected_peano_time",
                    "truth_quality": "OK",
                    "truth_notes": notes,
                }
            )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
