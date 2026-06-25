import json
from pathlib import Path
import tempfile
import unittest

from ais_etr.line_training import train_line_parser_shadow_model


class LineTrainingTests(unittest.TestCase):
    def test_train_shadow_parser_model_writes_hashed_artifact_without_raw_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "corpus.jsonl"
            rows = [
                _row("m1", "parsed", "Recloser PFA02VR-101 trip outage @Tom Nittawat 0812345678"),
                _row("m2", "parsed", "CB PFA03VB-01 operated fault"),
                _row("m3", "parsed", "Switch PFA04VF-22 outage"),
                _row("m4", "unparsed", "routine meeting schedule [PERSON_NAME_REDACTED]"),
                _row("m5", "unparsed", "thank you acknowledged"),
                _row("m6", "unparsed", "monthly KPI file uploaded"),
                _row("m7", "unparsed", "PFA02 followup without outage word"),
                _row("m8", "unparsed", "\u0e15\u0e31\u0e14\u0e15\u0e49\u0e19\u0e44\u0e21\u0e49\u0e43\u0e01\u0e25\u0e49\u0e41\u0e19\u0e27\u0e23\u0e30\u0e1a\u0e1a\u0e44\u0e1f\u0e1f\u0e49\u0e32 PFA08"),
            ]
            source.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

            result = train_line_parser_shadow_model(
                source,
                model_output=root / "model.json",
                split_output=root / "splits.jsonl",
                eval_output=root / "eval.csv",
                markdown_output=root / "report.md",
                review_output=root / "review.csv",
                max_features=128,
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["rows_read"], 8)
            self.assertEqual(result["rows_used"], 7)
            self.assertEqual(result["rows_excluded_tree_maintenance"], 1)
            self.assertEqual(result["rows_review"], 1)
            self.assertTrue((root / "model.json").exists())
            self.assertTrue((root / "review.csv").exists())
            combined = "\n".join(
                path.read_text(encoding="utf-8-sig")
                for path in (root / "model.json", root / "splits.jsonl", root / "eval.csv", root / "report.md", root / "review.csv")
            )
            self.assertNotIn("PFA02VR-101", combined)
            self.assertNotIn("Tom", combined)
            self.assertNotIn("Nittawat", combined)
            self.assertNotIn("0812345678", combined)
            self.assertNotIn("routine meeting", combined)
            review_text = (root / "review.csv").read_text(encoding="utf-8-sig")
            self.assertIn("text_sanitized_excerpt", review_text)
            self.assertIn("review_label", review_text)
            self.assertIn("review_device_id", review_text)
            self.assertIn("PFA02 followup", review_text)
            self.assertNotIn("PFA08", review_text)
            model = json.loads((root / "model.json").read_text(encoding="utf-8"))
            self.assertEqual(model["mode"], "shadow")
            self.assertEqual(model["production_send"], "blocked")
            self.assertEqual(model["feature_encoding"], "sha256_16_of_internal_parser_features")


def _row(message_ref: str, parser_status: str, text: str):
    return {
        "message_ref": message_ref,
        "source": "line",
        "source_kind": "line",
        "created": "2026-06-23T08:00:00+00:00",
        "text_sanitized": text,
        "raw_redaction_flags": [],
        "consent_manifest_id": "manifest-1",
        "parser_candidate": {"status": parser_status},
    }


if __name__ == "__main__":
    unittest.main()
