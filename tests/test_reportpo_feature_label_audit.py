import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.reportpo_feature_label_audit import build_reportpo_feature_label_audit


class ReportPoFeatureLabelAuditTests(unittest.TestCase):
    def test_build_reportpo_feature_label_audit_flags_encoded_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            features = root / "features.csv"
            diagnostics = root / "diagnostics.csv"
            output = root / "audit.csv"
            markdown = root / "audit.md"

            _write_csv(
                features,
                [
                    {
                        "event_type": "นฉ",
                        "work_type": "นฉ",
                        "event_status": "RealTime+Fast",
                        "etr_type": "1",
                        "etr_type_description": "ETR RealTime",
                        "cause_group": "",
                        "cause_code": "",
                        "job_status_at_notification": "not_dispatched_yet",
                        "feature_quality": "proxy_only",
                    },
                    {
                        "event_type": "กต",
                        "work_type": "กต",
                        "event_status": "Do Nothing",
                        "etr_type": "3",
                        "etr_type_description": "Do Nothing",
                        "cause_group": "",
                        "cause_code": "",
                        "job_status_at_notification": "not_dispatched_yet",
                        "feature_quality": "proxy_only",
                    },
                ],
            )
            _write_csv(
                diagnostics,
                [
                    {
                        "reportpo_event_type": "นฉ",
                        "reportpo_etr_type_description": "ETR RealTime",
                        "current_absolute_error": "70",
                        "current_covered_q10_q90": "FALSE",
                    }
                ],
            )

            result = build_reportpo_feature_label_audit(features, diagnostics, output, markdown)
            rows = _read_csv(output)
            by_feature = {row["feature_name"]: row for row in rows}
            markdown_text = markdown.read_text(encoding="utf-8")

            self.assertEqual(result["features_profiled"], 9)
            self.assertEqual(by_feature["event_type"]["readability_status"], "code_like_proxy")
            self.assertEqual(by_feature["event_type"]["model_action"], "exclude_until_decoded")
            self.assertEqual(by_feature["work_type"]["model_action"], "exclude_until_decoded")
            self.assertEqual(by_feature["etr_type_description"]["model_action"], "diagnostic_only")
            self.assertEqual(by_feature["cause_group"]["model_action"], "owner_source_gap")
            self.assertIn("Owner Question Pack", markdown_text)


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
