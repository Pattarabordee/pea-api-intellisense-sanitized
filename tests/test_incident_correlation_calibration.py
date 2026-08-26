from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ais_etr.incident_correlation_calibration import (
    LABEL_SCHEMA_VERSION,
    SCORE_SCHEMA_VERSION,
    ReviewLabel,
    ReviewRecord,
    ScoredRelationship,
    evaluate_records,
    evaluate_threshold,
    join_review_records,
    load_labels_jsonl,
    load_scored_jsonl,
    pareto_frontier,
    write_outputs,
)


ENGINE = "incident-correlation-shadow-v1.0.0"


def rec(
    pair: str,
    score: float,
    label: str,
    *,
    risk: str = "NORMAL",
    split: str = "EVALUATION",
    hard_veto: bool = False,
    eligible: bool = True,
) -> ReviewRecord:
    return ReviewRecord(
        pair_ref=pair,
        review_case_ref="case_" + pair,
        engine_version=ENGINE,
        decision_hash=(pair[-1] * 64 if pair[-1] in "abcdef0123456789" else "a" * 64),
        confidence_score=score,
        hard_veto=hard_veto,
        eligible_for_unplanned=eligible,
        label=label,
        risk_tier=risk,
        split=split,
        flags=(),
    )


class IncidentCorrelationCalibrationTests(unittest.TestCase):
    def test_threshold_metrics_are_precision_first(self) -> None:
        rows = [
            rec("pair_a00001", 90, "SAME_INCIDENT"),
            rec("pair_b00002", 80, "SAME_INCIDENT"),
            rec("pair_c00003", 60, "SAME_INCIDENT"),
            rec("pair_d00004", 70, "DIFFERENT_INCIDENT"),
            rec("pair_e00005", 40, "DIFFERENT_INCIDENT", risk="CRITICAL"),
            rec("pair_f00006", 20, "DIFFERENT_INCIDENT"),
        ]
        high = evaluate_threshold(rows, 75)
        self.assertEqual((high.tp, high.fp, high.tn, high.fn), (2, 0, 3, 1))
        self.assertEqual(high.precision, 1.0)
        self.assertTrue(high.zero_false_merge_pass)
        self.assertEqual(high.false_merge_high_critical, 0)

        medium = evaluate_threshold(rows, 60)
        self.assertEqual((medium.tp, medium.fp, medium.fn), (3, 1, 0))
        self.assertFalse(medium.zero_false_merge_pass)
        self.assertEqual(medium.false_merge_high_critical, 0)

        unsafe = evaluate_threshold(rows, 40)
        self.assertEqual(unsafe.false_merge_count, 2)
        self.assertEqual(unsafe.false_merge_high_critical, 1)
        self.assertFalse(unsafe.hard_safety_pass)

    def test_hard_veto_and_ineligible_never_predict_same(self) -> None:
        rows = [
            rec("pair_a00001", 100, "SAME_INCIDENT", hard_veto=True),
            rec("pair_b00002", 100, "SAME_INCIDENT", eligible=False),
        ]
        metrics = evaluate_threshold(rows, 0)
        self.assertEqual(metrics.tp, 0)
        self.assertEqual(metrics.fn, 2)
        self.assertEqual(metrics.fp, 0)

    def test_insufficient_evidence_is_excluded_from_decisive_metrics(self) -> None:
        rows = [
            rec("pair_a00001", 99, "INSUFFICIENT_EVIDENCE"),
            rec("pair_b00002", 90, "SAME_INCIDENT"),
            rec("pair_c00003", 10, "DIFFERENT_INCIDENT"),
        ]
        result = evaluate_records(rows, step=10)
        self.assertEqual(result["review_rows"], 3)
        self.assertEqual(result["decisive_rows"], 2)
        self.assertEqual(result["insufficient_evidence_rows"], 1)

    def test_prefers_held_out_evaluation_split(self) -> None:
        rows = [
            rec("pair_a00001", 90, "SAME_INCIDENT", split="CALIBRATION"),
            rec("pair_b00002", 10, "DIFFERENT_INCIDENT", split="CALIBRATION"),
            rec("pair_c00003", 85, "SAME_INCIDENT", split="EVALUATION"),
            rec("pair_d00004", 25, "DIFFERENT_INCIDENT", split="EVALUATION"),
        ]
        result = evaluate_records(rows, step=5)
        self.assertEqual(result["status"], "READY_FOR_REVIEWED_THRESHOLD_ANALYSIS")
        self.assertEqual(result["preferred_analysis_split"], "EVALUATION")
        self.assertIn("CALIBRATION", result["sweeps"])
        self.assertIn("EVALUATION", result["sweeps"])
        self.assertFalse(result["automatic_threshold_promotion"])

    def test_same_review_case_cannot_cross_calibration_and_evaluation(self) -> None:
        a = rec("pair_a00001", 90, "SAME_INCIDENT", split="CALIBRATION")
        b0 = rec("pair_b00002", 85, "SAME_INCIDENT", split="EVALUATION")
        b = ReviewRecord(
            pair_ref=b0.pair_ref, review_case_ref=a.review_case_ref, engine_version=b0.engine_version,
            decision_hash=b0.decision_hash, confidence_score=b0.confidence_score, hard_veto=b0.hard_veto,
            eligible_for_unplanned=b0.eligible_for_unplanned, label=b0.label, risk_tier=b0.risk_tier,
            split=b0.split, flags=b0.flags,
        )
        with self.assertRaisesRegex(ValueError, "leakage"):
            evaluate_records([a, b], step=10)

    def test_no_evaluation_split_is_explicitly_calibration_only(self) -> None:
        rows = [
            rec("pair_a00001", 90, "SAME_INCIDENT", split="CALIBRATION"),
            rec("pair_b00002", 10, "DIFFERENT_INCIDENT", split="CALIBRATION"),
        ]
        result = evaluate_records(rows, step=10)
        self.assertEqual(result["status"], "CALIBRATION_ONLY_NO_HELD_OUT_EVALUATION")
        self.assertEqual(result["preferred_analysis_split"], "CALIBRATION")

    def test_score_and_label_files_are_separate_and_joined_by_pair_ref(self) -> None:
        scored = [
            ScoredRelationship("pair_a00001", ENGINE, "a" * 64, 88, False, True, ("FLAG_A",)),
        ]
        labels = [
            ReviewLabel("pair_a00001", "case_a00001", "SAME_INCIDENT", "HIGH", "EVALUATION"),
        ]
        records = join_review_records(scored, labels)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].confidence_score, 88)
        self.assertEqual(records[0].label, "SAME_INCIDENT")
        self.assertEqual(records[0].risk_tier, "HIGH")

    def test_join_rejects_label_for_unknown_runtime_pair(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown score pairs"):
            join_review_records(
                [ScoredRelationship("pair_a00001", ENGINE, "a" * 64, 88, False, True, ())],
                [ReviewLabel("pair_z99999", "case_z99999", "SAME_INCIDENT", "NORMAL", "EVALUATION")],
            )

    def test_score_loader_rejects_unknown_fields_to_prevent_pii_creep(self) -> None:
        payload = {
            "schema_version": SCORE_SCHEMA_VERSION,
            "pair_ref": "pair_a00001",
            "engine_version": ENGINE,
            "decision_hash": "a" * 64,
            "confidence_score": 80,
            "hard_veto": False,
            "eligible_for_unplanned": True,
            "flags": [],
            "customer_phone": "0000000000",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scores.jsonl"
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported score fields"):
                load_scored_jsonl(path)

    def test_label_loader_requires_explicit_split(self) -> None:
        payload = {
            "schema_version": LABEL_SCHEMA_VERSION,
            "pair_ref": "pair_a00001",
            "review_case_ref": "case_a00001",
            "label": "SAME_INCIDENT",
            "risk_tier": "NORMAL",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "labels.jsonl"
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing label fields"):
                load_labels_jsonl(path)

    def test_label_loader_cannot_contain_score_or_customer_data(self) -> None:
        payload = {
            "schema_version": LABEL_SCHEMA_VERSION,
            "pair_ref": "pair_a00001",
            "review_case_ref": "case_a00001",
            "label": "SAME_INCIDENT",
            "risk_tier": "NORMAL",
            "split": "EVALUATION",
            "confidence_score": 99,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "labels.jsonl"
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported label fields"):
                load_labels_jsonl(path)

    def test_loader_rejects_mixed_engine_versions(self) -> None:
        rows = [
            {
                "schema_version": SCORE_SCHEMA_VERSION,
                "pair_ref": "pair_a00001",
                "engine_version": ENGINE,
                "decision_hash": "a" * 64,
                "confidence_score": 80,
                "hard_veto": False,
                "eligible_for_unplanned": True,
                "flags": [],
            },
            {
                "schema_version": SCORE_SCHEMA_VERSION,
                "pair_ref": "pair_b00002",
                "engine_version": "incident-correlation-shadow-v2",
                "decision_hash": "b" * 64,
                "confidence_score": 75,
                "hard_veto": False,
                "eligible_for_unplanned": True,
                "flags": [],
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scores.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mixed engine_version"):
                load_scored_jsonl(path)

    def test_outputs_are_reproducible_and_do_not_promote_threshold(self) -> None:
        rows = [
            rec("pair_a00001", 90, "SAME_INCIDENT"),
            rec("pair_b00002", 80, "SAME_INCIDENT"),
            rec("pair_c00003", 30, "DIFFERENT_INCIDENT"),
        ]
        result = evaluate_records(rows, step=10)
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_outputs(result, tmp)
            summary = json.loads(Path(outputs["summary"]).read_text(encoding="utf-8"))
            report = Path(outputs["report"]).read_text(encoding="utf-8")
            self.assertFalse(summary["automatic_threshold_promotion"])
            self.assertIn("does not promote a threshold automatically", report)
            self.assertTrue(Path(outputs["sweep_evaluation"]).exists())
            self.assertTrue(Path(outputs["pareto"]).exists())

    def test_pareto_frontier_removes_dominated_thresholds(self) -> None:
        rows = [
            rec("pair_a00001", 90, "SAME_INCIDENT"),
            rec("pair_b00002", 70, "SAME_INCIDENT"),
            rec("pair_c00003", 65, "DIFFERENT_INCIDENT"),
            rec("pair_d00004", 20, "DIFFERENT_INCIDENT"),
        ]
        metrics = [evaluate_threshold(rows, value) for value in (0, 60, 70, 80, 95)]
        frontier = pareto_frontier(metrics)
        self.assertTrue(frontier)
        self.assertTrue(all(item.precision is not None and item.recall is not None for item in frontier))


if __name__ == "__main__":
    unittest.main()
