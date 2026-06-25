import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.reportpo_proxy_challenger import build_reportpo_proxy_challenger


class ReportPoProxyChallengerTests(unittest.TestCase):
    def test_build_reportpo_proxy_challenger_uses_time_respecting_group_prior(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            features = root / "features.csv"
            diagnostics = root / "diagnostics.csv"
            semantic = root / "semantic.csv"
            output = root / "proxy.csv"
            summary = root / "summary.csv"
            markdown = root / "proxy.md"

            _write_csv(
                features,
                [
                    {
                        "event_number": "1",
                        "event_start_time": "2026-01-01 00:00:00",
                        "event_type": "นฉ",
                        "reportpo_first_restore_minutes": "20",
                    },
                    {
                        "event_number": "2",
                        "event_start_time": "2026-01-02 00:00:00",
                        "event_type": "นฉ",
                        "reportpo_first_restore_minutes": "40",
                    },
                    {
                        "event_number": "future",
                        "event_start_time": "2026-01-04 00:00:00",
                        "event_type": "นฉ",
                        "reportpo_first_restore_minutes": "400",
                    },
                ],
            )
            _write_csv(
                diagnostics,
                [
                    {
                        "event_id": "event-1",
                        "webex_message_ref": "msg-a",
                        "event_time": "2026-01-03T00:00:00",
                        "district": "พังโคน",
                        "device_type": "Recloser",
                        "feeder": "PFA01",
                        "actual_restoration_minutes": "30",
                        "current_p50": "50",
                        "current_q10": "10",
                        "current_q90": "80",
                        "current_absolute_error": "20",
                        "current_covered_q10_q90": "TRUE",
                        "reportpo_feature_match_status": "matched",
                        "reportpo_event_type": "นฉ",
                    }
                ],
            )
            _write_csv(semantic, [{"raw_value": "นฉ", "inferred_label": "north_northeast_area_group"}])

            result = build_reportpo_proxy_challenger(
                features,
                diagnostics,
                semantic,
                output,
                summary,
                markdown,
                min_group_rows=2,
                min_global_rows=2,
            )
            rows = _read_csv(output)
            summary_rows = {row["segment"]: row for row in _read_csv(summary)}
            markdown_text = markdown.read_text(encoding="utf-8")

            self.assertEqual(result["events"], 1)
            self.assertEqual(rows[0]["proxy_source"], "reportpo_group_time_prior")
            self.assertEqual(rows[0]["proxy_training_rows"], "2")
            self.assertEqual(rows[0]["proxy_p50"], "20.0")
            self.assertEqual(rows[0]["evaluation_scope"], "pilot_3")
            self.assertEqual(summary_rows["pilot_3"]["proxy_usable_rows"], "1")
            self.assertIn("ReportPO Proxy Shadow Challenger", markdown_text)


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
