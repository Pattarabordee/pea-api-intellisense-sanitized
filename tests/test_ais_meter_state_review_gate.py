from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from ais_etr.ais_meter_state_review_gate import build_meter_state_review_gate


class MeterStateReviewGateTests(unittest.TestCase):
    def _run(self, intervals, metrics=None, operator_items=None):
        metrics = metrics or {"production_send": "blocked", "semantic_mapping_version": "alarm_mapping_v2"}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = build_meter_state_review_gate(
                metrics,
                intervals,
                operator_items or [],
                queue_csv=root / "queue.csv",
                summary_json=root / "summary.json",
                report_md=root / "report.md",
                handoff_md=root / "handoff.md",
                now=datetime(2026, 7, 13, tzinfo=timezone.utc),
            )
            with (root / "queue.csv").open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            bundle = "".join((root / name).read_text(encoding="utf-8") for name in ("summary.json", "report.md", "handoff.md")) + json.dumps(rows)
            return result, rows, bundle

    @staticmethod
    def _interval(*, bridge, pair="REVIEW", hint="", outage="2026-07-12T00:00:00Z", ref="raw-request"):
        return {
            "semantic_mapping_version": "alarm_mapping_v2",
            "bridge_status": bridge,
            "pair_status": pair,
            "review_hint": hint,
            "outage_at": outage,
            "interval_ref": ref,
        }

    def test_review_classifications_and_clean_exclusion(self):
        intervals = [
            self._interval(bridge="METER_STATE_MODEL_READY", pair="CLOSED", ref="clean"),
            {**self._interval(bridge="LEGACY_UNVERIFIED", pair="CLOSED", ref="legacy"), "semantic_mapping_version": "legacy"},
            self._interval(bridge="REVIEW_IDENTITY_KEY_REQUIRED"),
            self._interval(bridge="REVIEW_EVENT_TYPE"),
            self._interval(bridge="REVIEW_NO_OPEN_INTERVAL"),
            self._interval(bridge="METER_STATE_DURATION_REVIEW"),
            self._interval(bridge="METER_STATE_AWAITING_RESTORE", pair="OPEN", outage="2026-07-12T23:00:00Z"),
            self._interval(bridge="METER_STATE_AWAITING_RESTORE", pair="OPEN", outage="2026-07-10T00:00:00Z"),
        ]
        result, rows, _ = self._run(intervals)
        self.assertEqual(6, result["queue_rows"])
        self.assertEqual(
            {
                "active_outage": 1,
                "duplicate_or_late_restore": 1,
                "duration_review": 1,
                "missing_meter_no": 1,
                "missing_restore": 1,
                "unknown_status_mapping": 1,
            },
            result["queue_classifications"],
        )
        self.assertTrue(all(row["use_for_training"] == "FALSE" for row in rows))

    def test_metric_backlog_remains_separate_from_interval_queue(self):
        metrics = {
            "production_send": "blocked",
            "truth_validation_counts": {
                "REVIEW_IDENTITY_KEY_REQUIRED": 125,
                "REVIEW_EVENT_TYPE": 66,
                "REVIEW_NO_OPEN_INTERVAL": 41,
                "REVIEW_DURATION_OUT_OF_RANGE": 1,
            },
        }
        result, rows, _ = self._run([{**self._interval(bridge="LEGACY_UNVERIFIED", pair="CLOSED"), "semantic_mapping_version": "legacy"}], metrics=metrics)
        self.assertEqual([], rows)
        self.assertEqual(
            {"missing_meter_no": 125, "unknown_status_mapping": 66, "duplicate_or_late_restore": 41, "duration_review": 1},
            result["metric_review_categories"],
        )

    def test_unknown_reference_is_hashed_in_outputs(self):
        _, rows, bundle = self._run([self._interval(bridge="REVIEW_EVENT_TYPE", ref="secret-request-id")])
        self.assertEqual(1, len(rows))
        self.assertRegex(rows[0]["case_ref"], r"^case_[0-9a-f]{16}$")
        self.assertNotIn("secret-request-id", bundle)

    def test_nonblocked_metrics_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "production_send"):
            self._run([], metrics={"production_send": "allowed"})

    def test_handoff_locks_meter_no_and_optional_identity_policy(self):
        _, _, bundle = self._run([])
        self.assertIn("meter_no", bundle)
        self.assertIn("optional", bundle)
        self.assertIn("unknown_status_mapping", bundle)

    def test_operator_sample_is_diagnostic_only(self):
        result, _, _ = self._run([], operator_items=[{"truth_observation": {"validation_status": "REVIEW_EVENT_TYPE"}}])
        self.assertEqual({"REVIEW_EVENT_TYPE": 1}, result["recent_operator_sample_counts"])


if __name__ == "__main__":
    unittest.main()
