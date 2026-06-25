import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.reportpo_semantic_inference import build_reportpo_semantic_inference


class ReportPoSemanticInferenceTests(unittest.TestCase):
    def test_build_reportpo_semantic_inference_maps_group_by_area_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            features = root / "features.csv"
            diagnostics = root / "diagnostics.csv"
            output = root / "semantic.csv"
            decisions = root / "decisions.csv"
            markdown = root / "semantic.md"

            _write_csv(
                features,
                [
                    {
                        "event_type": "นฉ",
                        "area": "กฟฉ.1",
                        "office": "office-a",
                        "etr_type_description": "ETR RealTime",
                        "reportpo_first_restore_minutes": "20",
                    },
                    {
                        "event_type": "นฉ",
                        "area": "กฟน.2",
                        "office": "office-b",
                        "etr_type_description": "ETR RealTime",
                        "reportpo_first_restore_minutes": "30",
                    },
                    {
                        "event_type": "กต",
                        "area": "กฟก.1",
                        "office": "office-c",
                        "etr_type_description": "Fast ETR",
                        "reportpo_first_restore_minutes": "40",
                    },
                    {
                        "event_type": "กต",
                        "area": "กฟต.2",
                        "office": "office-d",
                        "etr_type_description": "Fast ETR",
                        "reportpo_first_restore_minutes": "50",
                    },
                ],
            )
            _write_csv(
                diagnostics,
                [
                    {
                        "reportpo_event_type": "นฉ",
                        "current_absolute_error": "10",
                        "current_covered_q10_q90": "TRUE",
                    }
                ],
            )

            result = build_reportpo_semantic_inference(features, diagnostics, output, decisions, markdown)
            rows = {row["raw_value"]: row for row in _read_csv(output)}
            decision_rows = _read_csv(decisions)
            markdown_text = markdown.read_text(encoding="utf-8")

            self.assertEqual(result["group_values"], 2)
            self.assertEqual(rows["นฉ"]["inferred_label"], "north_northeast_area_group")
            self.assertEqual(rows["กต"]["inferred_label"], "central_south_area_group")
            self.assertEqual(rows["นฉ"]["webex_truth_rows"], "1")
            self.assertTrue(any(row["field_name"] == "ETR_OU.Group" for row in decision_rows))
            self.assertIn("Inferred Group Code Map", markdown_text)


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
