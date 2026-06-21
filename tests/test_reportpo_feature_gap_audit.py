import csv
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ais_etr.reportpo_feature_gap_audit import build_reportpo_feature_gap_audit


class ReportPoFeatureGapAuditTests(unittest.TestCase):
    def test_build_reportpo_feature_gap_audit_exports_redacted_feeder_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            reportpo = root / "reportpo.csv"
            proxy = root / "proxy.csv"
            output = root / "candidates.csv"
            summary = root / "summary.csv"
            markdown = root / "audit.md"
            raw_message_id = "raw-webex-id-1"
            redacted = "msg-" + hashlib.sha256(raw_message_id.encode("utf-8")).hexdigest()[:12]

            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE outage_events (
                    webex_message_id TEXT,
                    event_time TEXT,
                    device_id TEXT,
                    feeder TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO outage_events VALUES (?, ?, ?, ?)",
                (raw_message_id, "2026-06-17T10:00:00", "PFA01R-01", "PFA01"),
            )
            conn.commit()
            conn.close()

            _write_csv(
                reportpo,
                [
                    {
                        "event_number": "6847000001",
                        "event_start_time": "2026-06-17 10:05:00",
                        "first_restore_time": "2026-06-17 10:30:00",
                        "device_id": "PFA01R-99",
                        "feeder": "PFA01",
                        "truth_quality": "OK",
                    }
                ],
            )
            _write_csv(
                proxy,
                [
                    {
                        "webex_message_ref": redacted,
                        "event_time": "2026-06-17T10:00:00",
                        "district": "พังโคน",
                        "device_type": "Recloser",
                        "device_id": "PFA01R-01",
                        "feeder": "PFA01",
                        "actual_restoration_minutes": "30",
                        "current_absolute_error": "20",
                        "reportpo_feature_match_status": "no_match",
                        "proxy_source": "no_prediction",
                    }
                ],
            )

            result = build_reportpo_feature_gap_audit(db_path, reportpo, proxy, output, summary, markdown)
            candidate_rows = _read_csv(output)
            summary_rows = _read_csv(summary)
            output_text = output.read_text(encoding="utf-8-sig")

            self.assertEqual(result["target_truth_no_match_rows"], 1)
            self.assertEqual(candidate_rows[0]["webex_message_ref"], redacted)
            self.assertEqual(candidate_rows[0]["gap_bucket"], "feeder_only_candidate_review")
            self.assertEqual(candidate_rows[0]["same_feeder"], "TRUE")
            self.assertNotIn(raw_message_id, output_text)
            self.assertEqual(summary_rows[0]["gap_bucket"], "feeder_only_candidate_review")
            self.assertIn("ReportPO Feature Gap Audit", markdown.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
