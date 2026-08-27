from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ais_etr.incident_correlation_review_queue import (
    CANDIDATE_SCHEMA,
    LABEL_SCHEMA,
    ReviewQueueError,
    assign_cases,
    build_queue,
    build_review_rows,
    load_candidates,
    validate_labels_file,
)


ENGINE = "incident-correlation-shadow-v1.0.0"


def candidate(
    pair: str,
    a: str,
    b: str,
    *,
    feeder: str = "SAME_FEEDER",
    transformer: str = "ONE_OR_BOTH_UNKNOWN",
    admin: str = "SAME_VILLAGE",
    minutes: float = 3,
    engine: str = ENGINE,
) -> dict:
    return {
        "schema_version": CANDIDATE_SCHEMA,
        "pair_ref": pair,
        "report_ref_a": a,
        "report_ref_b": b,
        "engine_version": engine,
        "evidence": {
            "temporal_delta_minutes": minutes,
            "channel_relation": "DIFFERENT_CHANNEL",
            "admin_relation": admin,
            "feeder_relation": feeder,
            "transformer_relation": transformer,
            "upstream_relation": "DIFFERENT_OR_UNKNOWN",
            "topology_freshness_relation": "BOTH_NOT_FRESH",
            "topology_authoritative_relation": "BOTH_AUTHORITATIVE",
            "planned_outage_relation": "BOTH_UNPLANNED_OR_NOT_CHECKED",
        },
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


class IncidentCorrelationReviewQueueTests(unittest.TestCase):
    def test_connected_pairs_share_case_and_split(self) -> None:
        rows = [
            candidate("pair_aaaaaaaa", "report_aaaaaaaa", "report_bbbbbbbb"),
            candidate("pair_bbbbbbbb", "report_bbbbbbbb", "report_cccccccc"),
            candidate("pair_cccccccc", "report_dddddddd", "report_eeeeeeee"),
        ]
        cases = assign_cases(rows)
        self.assertEqual(cases["pair_aaaaaaaa"], cases["pair_bbbbbbbb"])
        self.assertNotEqual(cases["pair_aaaaaaaa"], cases["pair_cccccccc"])
        review_rows = build_review_rows(rows, split_seed="stable", calibration_fraction=0.7)
        by_pair = {row["pair_ref"]: row for row in review_rows}
        self.assertEqual(by_pair["pair_aaaaaaaa"]["split"], by_pair["pair_bbbbbbbb"]["split"])

    def test_build_queue_is_blind_and_records_manifest(self) -> None:
        rows = [
            candidate("pair_aaaaaaaa", "report_aaaaaaaa", "report_bbbbbbbb", transformer="SAME_TRANSFORMER"),
            candidate("pair_bbbbbbbb", "report_bbbbbbbb", "report_cccccccc", transformer="DIFFERENT_TRANSFORMER"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "candidates.jsonl"
            output = root / "queue"
            write_jsonl(candidates, rows)
            manifest = build_queue(candidates, output, split_seed="review-seed", calibration_fraction=0.5)
            html_text = (output / "incident_correlation_review_queue.html").read_text(encoding="utf-8")
            manifest_disk = json.loads((output / "incident_correlation_review_queue_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["queue_ref"], manifest_disk["queue_ref"])
            self.assertEqual(manifest["candidate_count"], 2)
            self.assertTrue(manifest["blind_review"])
            self.assertFalse(manifest["score_fields_exposed"])
            self.assertFalse(manifest["customer_data_exposed"])
            self.assertFalse(manifest["raw_asset_ids_exposed"])
            self.assertFalse(manifest["threshold_promotion_authorized"])
            self.assertNotIn("confidence_score", html_text)
            self.assertNotIn("confidence_level", html_text)
            self.assertNotIn("ticket_id", html_text)
            self.assertIn("SAME_INCIDENT", html_text)
            self.assertIn("INSUFFICIENT_EVIDENCE", html_text)
            self.assertIn("join('\\n')+'\\n'", html_text)
            self.assertIn("JSON.stringify(audit,null,2)+'\\n'", html_text)

    def test_candidate_rejects_model_score_or_extra_customer_field(self) -> None:
        base = candidate("pair_aaaaaaaa", "report_aaaaaaaa", "report_bbbbbbbb")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.jsonl"
            bad = dict(base)
            bad["confidence_score"] = 99
            write_jsonl(path, [bad])
            with self.assertRaisesRegex(ReviewQueueError, "schema key mismatch"):
                load_candidates(path)

            bad = candidate("pair_aaaaaaaa", "report_aaaaaaaa", "report_bbbbbbbb")
            bad["evidence"] = dict(bad["evidence"])
            bad["evidence"]["customer_phone"] = "SYNTHETIC_PHONE_VALUE"
            write_jsonl(path, [bad])
            with self.assertRaisesRegex(ReviewQueueError, "schema key mismatch"):
                load_candidates(path)

    def test_candidate_rejects_mixed_engine_versions(self) -> None:
        rows = [
            candidate("pair_aaaaaaaa", "report_aaaaaaaa", "report_bbbbbbbb"),
            candidate("pair_bbbbbbbb", "report_cccccccc", "report_dddddddd", engine="incident-correlation-shadow-v2"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mixed.jsonl"
            write_jsonl(path, rows)
            with self.assertRaisesRegex(ReviewQueueError, "mixed engine versions"):
                load_candidates(path)

    def test_candidate_rejects_duplicate_report_pair(self) -> None:
        rows = [
            candidate("pair_aaaaaaaa", "report_aaaaaaaa", "report_bbbbbbbb"),
            candidate("pair_bbbbbbbb", "report_bbbbbbbb", "report_aaaaaaaa"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.jsonl"
            write_jsonl(path, rows)
            with self.assertRaisesRegex(ReviewQueueError, "duplicate report pair"):
                load_candidates(path)

    def test_label_validation_matches_manifest_assignment(self) -> None:
        rows = [
            candidate("pair_aaaaaaaa", "report_aaaaaaaa", "report_bbbbbbbb"),
            candidate("pair_bbbbbbbb", "report_bbbbbbbb", "report_cccccccc"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "candidates.jsonl"
            output = root / "queue"
            write_jsonl(candidates, rows)
            manifest = build_queue(candidates, output, split_seed="review-seed")
            assignments = {item["pair_ref"]: item for item in manifest["pair_assignments"]}
            labels = []
            for pair in sorted(assignments):
                item = assignments[pair]
                labels.append(
                    {
                        "schema_version": LABEL_SCHEMA,
                        "pair_ref": pair,
                        "review_case_ref": item["review_case_ref"],
                        "label": "INSUFFICIENT_EVIDENCE",
                        "risk_tier": "HIGH",
                        "split": item["split"],
                    }
                )
            labels_path = root / "labels.jsonl"
            write_jsonl(labels_path, labels)
            result = validate_labels_file(
                labels_path, output / "incident_correlation_review_queue_manifest.json"
            )
            self.assertTrue(result["valid"])
            self.assertEqual(result["label_count"], 2)
            self.assertEqual(result["insufficient_evidence"], 2)

    def test_label_validation_rejects_manifest_split_tampering(self) -> None:
        rows = [candidate("pair_aaaaaaaa", "report_aaaaaaaa", "report_bbbbbbbb")]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "candidates.jsonl"
            output = root / "queue"
            write_jsonl(candidates, rows)
            manifest = build_queue(candidates, output, split_seed="review-seed")
            item = manifest["pair_assignments"][0]
            wrong_split = "EVALUATION" if item["split"] == "CALIBRATION" else "CALIBRATION"
            label = {
                "schema_version": LABEL_SCHEMA,
                "pair_ref": item["pair_ref"],
                "review_case_ref": item["review_case_ref"],
                "label": "SAME_INCIDENT",
                "risk_tier": "NORMAL",
                "split": wrong_split,
            }
            labels_path = root / "labels.jsonl"
            write_jsonl(labels_path, [label])
            with self.assertRaisesRegex(ReviewQueueError, "manifest assignment mismatch"):
                validate_labels_file(labels_path, output / "incident_correlation_review_queue_manifest.json")

    def test_label_validation_rejects_incomplete_queue_unless_explicit(self) -> None:
        rows = [
            candidate("pair_aaaaaaaa", "report_aaaaaaaa", "report_bbbbbbbb"),
            candidate("pair_bbbbbbbb", "report_cccccccc", "report_dddddddd"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "candidates.jsonl"
            output = root / "queue"
            write_jsonl(candidates, rows)
            manifest = build_queue(candidates, output)
            item = manifest["pair_assignments"][0]
            label = {
                "schema_version": LABEL_SCHEMA,
                "pair_ref": item["pair_ref"],
                "review_case_ref": item["review_case_ref"],
                "label": "DIFFERENT_INCIDENT",
                "risk_tier": "CRITICAL",
                "split": item["split"],
            }
            labels_path = root / "labels.jsonl"
            write_jsonl(labels_path, [label])
            manifest_path = output / "incident_correlation_review_queue_manifest.json"
            with self.assertRaisesRegex(ReviewQueueError, "labels are incomplete"):
                validate_labels_file(labels_path, manifest_path)
            result = validate_labels_file(labels_path, manifest_path, allow_partial=True)
            self.assertTrue(result["valid"])
            self.assertEqual(result["label_count"], 1)


if __name__ == "__main__":
    unittest.main()
