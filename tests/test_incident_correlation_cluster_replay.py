from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shared_core.incident_correlation.cluster_replay import (
    OBS_SCHEMA_VERSION,
    TRUTH_SCHEMA_VERSION,
    ClusterObservation,
    ClusterTruth,
    ReplayStep,
    evaluate_replay,
    evaluate_step,
    join_replay,
    load_observations_jsonl,
    load_truth_jsonl,
)


def obs(
    scenario: str,
    step: int,
    refs: tuple[str, ...],
    partition: tuple[tuple[str, ...], ...],
    transition: str = "UNCHANGED",
    lineage: tuple[str, ...] = (),
) -> ClusterObservation:
    return ClusterObservation(
        scenario_ref=scenario,
        step_index=step,
        engine_version="incident-correlation-shadow-v1.0.0",
        active_report_refs=tuple(sorted(refs)),
        observed_partition=tuple(sorted(tuple(sorted(x)) for x in partition)),
        observed_transition=transition,
        observed_lineage_types=tuple(sorted(lineage)),
    )


def truth(
    scenario: str,
    step: int,
    refs: tuple[str, ...],
    partition: tuple[tuple[str, ...], ...],
    transition: str = "UNCHANGED",
    lineage: tuple[str, ...] = (),
    *,
    risk: str = "NORMAL",
    split: str = "EVALUATION",
    case: str = "case_alpha",
) -> ClusterTruth:
    return ClusterTruth(
        scenario_ref=scenario,
        step_index=step,
        review_case_ref=case,
        active_report_refs=tuple(sorted(refs)),
        expected_partition=tuple(sorted(tuple(sorted(x)) for x in partition)),
        expected_transition=transition,
        expected_lineage_types=tuple(sorted(lineage)),
        risk_tier=risk,
        split=split,
    )


class IncidentCorrelationClusterReplayTests(unittest.TestCase):
    def test_exact_partition_ignores_cluster_ids_and_order(self) -> None:
        step = ReplayStep(
            obs("s1", 0, ("r1", "r2", "r3"), (("r3",), ("r2", "r1"))),
            truth("s1", 0, ("r1", "r2", "r3"), (("r1", "r2"), ("r3",))),
        )
        m = evaluate_step(step)
        self.assertTrue(m.exact_partition_match)
        self.assertEqual(m.false_merge_pairs, 0)
        self.assertEqual(m.false_split_pairs, 0)
        self.assertEqual(m.pair_precision, 1.0)
        self.assertEqual(m.pair_recall, 1.0)

    def test_false_merge_is_precision_safety_violation(self) -> None:
        step = ReplayStep(
            obs("s1", 1, ("r1", "r2", "r3"), (("r1", "r2", "r3"),)),
            truth("s1", 1, ("r1", "r2", "r3"), (("r1", "r2"), ("r3",)), risk="CRITICAL"),
        )
        m = evaluate_step(step)
        self.assertEqual(m.false_merge_pairs, 2)
        self.assertTrue(m.high_critical_false_merge)
        result = evaluate_replay([step])
        self.assertFalse(result["preferred_summary"]["hard_safety_pass"])

    def test_false_split_is_measured_separately(self) -> None:
        step = ReplayStep(
            obs("s1", 2, ("r1", "r2", "r3"), (("r1",), ("r2",), ("r3",))),
            truth("s1", 2, ("r1", "r2", "r3"), (("r1", "r2", "r3"),)),
        )
        m = evaluate_step(step)
        self.assertEqual(m.false_merge_pairs, 0)
        self.assertEqual(m.false_split_pairs, 3)
        self.assertEqual(m.pair_recall, 0.0)

    def test_merge_transition_requires_lineage(self) -> None:
        step = ReplayStep(
            obs("merge", 2, ("r1", "r2", "r3"), (("r1", "r2", "r3"),), "MERGE", ()),
            truth("merge", 2, ("r1", "r2", "r3"), (("r1", "r2", "r3"),), "MERGE", ("MERGE",)),
        )
        m = evaluate_step(step)
        self.assertTrue(m.transition_match)
        self.assertFalse(m.lineage_match)
        self.assertEqual(len(evaluate_replay([step])["transition_gaps"]), 1)

    def test_expected_reopen_surfaces_current_runtime_gap(self) -> None:
        step = ReplayStep(
            obs("reopen", 4, ("r1", "r2"), (("r1", "r2"),), "NEW"),
            truth("reopen", 4, ("r1", "r2"), (("r1", "r2"),), "REOPEN", ("RECURRENCE",)),
        )
        result = evaluate_replay([step])
        self.assertEqual(result["preferred_summary"]["transition_accuracy"], 0.0)
        self.assertIn("REOPENED", result["known_runtime_gap"])

    def test_join_requires_same_active_universe(self) -> None:
        observation = obs("s1", 0, ("r1", "r2"), (("r1",), ("r2",)))
        expected = truth("s1", 0, ("r1",), (("r1",),))
        with self.assertRaisesRegex(ValueError, "active_report_refs mismatch"):
            join_replay([observation], [expected])

    def test_loader_requires_partition_to_cover_singletons(self) -> None:
        payload = {
            "schema_version": OBS_SCHEMA_VERSION,
            "scenario_ref": "scenario_1",
            "step_index": 0,
            "engine_version": "incident-correlation-shadow-v1.0.0",
            "active_report_refs": ["r1", "r2", "r3"],
            "observed_partition": [["r1", "r2"]],
            "observed_transition": "NEW",
            "observed_lineage_types": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.jsonl"
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "including singletons"):
                load_observations_jsonl(path)

    def test_unknown_fields_are_rejected_to_prevent_pii_creep(self) -> None:
        payload = {
            "schema_version": OBS_SCHEMA_VERSION,
            "scenario_ref": "scenario_1",
            "step_index": 0,
            "engine_version": "incident-correlation-shadow-v1.0.0",
            "active_report_refs": ["r1"],
            "observed_partition": [["r1"]],
            "observed_transition": "NEW",
            "observed_lineage_types": [],
            "raw_customer_message": "must never be accepted",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.jsonl"
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown observation fields"):
                load_observations_jsonl(path)

    def test_mixed_engine_versions_are_rejected(self) -> None:
        base = {
            "schema_version": OBS_SCHEMA_VERSION,
            "scenario_ref": "scenario_1",
            "active_report_refs": ["r1"],
            "observed_partition": [["r1"]],
            "observed_transition": "NEW",
            "observed_lineage_types": [],
        }
        rows = [
            {**base, "step_index": 0, "engine_version": "v1"},
            {**base, "step_index": 1, "engine_version": "v2"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.jsonl"
            path.write_text("\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mixed engine_version"):
                load_observations_jsonl(path)

    def test_case_split_leakage_is_rejected(self) -> None:
        rows = [
            {
                "schema_version": TRUTH_SCHEMA_VERSION,
                "scenario_ref": "scenario_1",
                "step_index": 0,
                "review_case_ref": "case_shared",
                "active_report_refs": ["r1"],
                "expected_partition": [["r1"]],
                "expected_transition": "NEW",
                "expected_lineage_types": [],
                "risk_tier": "NORMAL",
                "split": "CALIBRATION",
            },
            {
                "schema_version": TRUTH_SCHEMA_VERSION,
                "scenario_ref": "scenario_1",
                "step_index": 1,
                "review_case_ref": "case_shared",
                "active_report_refs": ["r1", "r2"],
                "expected_partition": [["r1"], ["r2"]],
                "expected_transition": "ADD_SINGLETON",
                "expected_lineage_types": [],
                "risk_tier": "NORMAL",
                "split": "EVALUATION",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "truth.jsonl"
            path.write_text("\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "leakage"):
                load_truth_jsonl(path)

    def test_rolling_arrival_then_late_unrelated_singleton_stays_safe(self) -> None:
        steps = [
            ReplayStep(
                obs("rolling", 0, ("r1",), (("r1",),), "NEW"),
                truth("rolling", 0, ("r1",), (("r1",),), "NEW", case="case_rolling"),
            ),
            ReplayStep(
                obs("rolling", 1, ("r1", "r2"), (("r1", "r2"),), "EXPAND"),
                truth("rolling", 1, ("r1", "r2"), (("r1", "r2"),), "EXPAND", case="case_rolling"),
            ),
            ReplayStep(
                obs("rolling", 2, ("r1", "r2", "r3"), (("r1", "r2"), ("r3",)), "ADD_SINGLETON"),
                truth("rolling", 2, ("r1", "r2", "r3"), (("r1", "r2"), ("r3",)), "ADD_SINGLETON", case="case_rolling"),
            ),
        ]
        result = evaluate_replay(steps)
        summary = result["preferred_summary"]
        self.assertEqual(summary["false_merge_pairs"], 0)
        self.assertEqual(summary["false_split_pairs"], 0)
        self.assertEqual(summary["exact_partition_rate"], 1.0)
        self.assertEqual(summary["transition_accuracy"], 1.0)

    def test_loader_rejects_missing_timeline_step(self) -> None:
        base = {
            "schema_version": OBS_SCHEMA_VERSION,
            "scenario_ref": "scenario_gap",
            "engine_version": "incident-correlation-shadow-v1.0.0",
            "active_report_refs": ["r1"],
            "observed_partition": [["r1"]],
            "observed_transition": "NEW",
            "observed_lineage_types": [],
        }
        rows = [{**base, "step_index": 0}, {**base, "step_index": 2}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.jsonl"
            path.write_text("\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "contiguous from 0"):
                load_observations_jsonl(path)

    def test_evaluation_split_is_preferred(self) -> None:
        c = ReplayStep(
            obs("c", 0, ("r1", "r2"), (("r1", "r2"),)),
            truth("c", 0, ("r1", "r2"), (("r1", "r2"),), split="CALIBRATION", case="case_c"),
        )
        e = ReplayStep(
            obs("e", 0, ("r3", "r4"), (("r3",), ("r4",))),
            truth("e", 0, ("r3", "r4"), (("r3", "r4"),), split="EVALUATION", case="case_e"),
        )
        result = evaluate_replay([c, e])
        self.assertEqual(result["preferred_analysis_split"], "EVALUATION")
        self.assertEqual(result["preferred_summary"]["false_split_pairs"], 1)

    def test_empty_replay_does_not_claim_success(self) -> None:
        result = evaluate_replay([])
        self.assertEqual(result["status"], "NO_REVIEWED_DATA")
        self.assertFalse(result["automatic_promotion"])
        self.assertEqual(result["preferred_summary"]["steps"], 0)
        self.assertIsNone(result["preferred_summary"]["hard_safety_pass"])


if __name__ == "__main__":
    unittest.main()
