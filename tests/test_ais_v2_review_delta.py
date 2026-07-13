from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from ais_etr.ais_v2_review_delta import build_v2_review_delta


class V2ReviewDeltaTests(unittest.TestCase):
    NOW = datetime(2026, 7, 13, 12, tzinfo=timezone.utc)

    def _metrics(self, **overrides):
        data = {
            "production_send": "blocked",
            "semantic_mapping_version": "alarm_mapping_v2",
            "v2_activation_first_seen_at": "2026-07-10T12:00:00Z",
            "v2_model_ready_rows": 951,
            "v2_open_intervals": 22,
            "truth_stale_open_intervals": 0,
            "truth_review_needed": 233,
            "truth_validation_counts": {
                "REVIEW_IDENTITY_KEY_REQUIRED": 125,
                "REVIEW_EVENT_TYPE": 66,
                "REVIEW_NO_OPEN_INTERVAL": 41,
                "REVIEW_DURATION_OUT_OF_RANGE": 1,
            },
        }
        data.update(overrides)
        return data

    def _run(self, metrics=None, intervals=None, now=None, prior=None):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        history = root / "history.jsonl"
        if prior:
            history.write_text(json.dumps(prior) + "\n", encoding="utf-8")
        result = build_v2_review_delta(
            metrics or self._metrics(), intervals or [], history_jsonl=history,
            delta_csv=root / "delta.csv", summary_json=root / "summary.json",
            report_md=root / "report.md", missing_restore_csv=root / "missing.csv",
            now=now or self.NOW,
        )
        return temp, root, result

    def _prior(self, **overrides):
        row = {
            "run_id": "prior", "generated_at": "2026-07-13T11:00:00Z",
            "v2_model_ready_rows": 951, "v2_open_intervals": 22,
            "truth_stale_open_intervals": 0, "truth_review_needed": 233,
            "review_identity_required": 125, "review_event_type": 66,
            "review_no_open_interval": 41, "review_duration": 1,
        }
        row.update(overrides)
        return row

    def test_first_snapshot_initializes_stable_baseline(self):
        temp, _, result = self._run()
        self.addCleanup(temp.cleanup)
        self.assertEqual("stable_historical_backlog", result["gate_status"])
        self.assertEqual("baseline_initialized", result["comparison_status"])

    def test_unchanged_counts_are_stable(self):
        temp, _, result = self._run(prior=self._prior())
        self.addCleanup(temp.cleanup)
        self.assertEqual("stable_historical_backlog", result["gate_status"])

    def test_identity_or_event_increase_is_payload_regression(self):
        metrics = self._metrics()
        metrics["truth_validation_counts"]["REVIEW_IDENTITY_KEY_REQUIRED"] = 126
        temp, _, result = self._run(metrics=metrics, prior=self._prior())
        self.addCleanup(temp.cleanup)
        self.assertEqual("new_payload_regression", result["gate_status"])

    def test_no_open_or_duration_increase_is_lifecycle_anomaly(self):
        metrics = self._metrics()
        metrics["truth_validation_counts"]["REVIEW_NO_OPEN_INTERVAL"] = 42
        temp, _, result = self._run(metrics=metrics, prior=self._prior())
        self.addCleanup(temp.cleanup)
        self.assertEqual("new_lifecycle_anomaly", result["gate_status"])

    def test_open_increase_without_stale_is_watch(self):
        temp, _, result = self._run(prior=self._prior(v2_open_intervals=21))
        self.addCleanup(temp.cleanup)
        self.assertEqual("open_interval_watch", result["gate_status"])

    def test_stale_open_creates_hash_only_queue(self):
        metrics = self._metrics(truth_stale_open_intervals=1)
        interval = {"semantic_mapping_version": "alarm_mapping_v2", "pair_status": "OPEN", "outage_at": "2026-07-10T00:00:00Z", "interval_ref": "raw-secret-ref"}
        temp, root, result = self._run(metrics=metrics, intervals=[interval], prior=self._prior())
        self.addCleanup(temp.cleanup)
        self.assertEqual("stale_restore_gap", result["gate_status"])
        content = (root / "missing.csv").read_text(encoding="utf-8-sig")
        self.assertNotIn("raw-secret-ref", content)
        self.assertIn("case_", content)

    def test_negative_delta_is_quarantined(self):
        temp, _, result = self._run(prior=self._prior(truth_review_needed=234))
        self.addCleanup(temp.cleanup)
        self.assertEqual("metrics_reset_quarantined", result["gate_status"])
        self.assertIn("truth_review_needed", result["negative_delta_fields"])

    def test_duplicate_run_is_idempotent(self):
        prior = self._prior(run_id=self.NOW.strftime("%Y%m%dT%H%M%S.%fZ"), generated_at="2026-07-13T12:00:00Z")
        temp, root, result = self._run(prior=prior)
        self.addCleanup(temp.cleanup)
        self.assertEqual("duplicate_run_id_noop", result["history_append_status"])
        self.assertEqual(1, len((root / "history.jsonl").read_text().splitlines()))

    def test_seven_day_trigger_is_exact(self):
        metrics = self._metrics(v2_activation_first_seen_at="2026-07-06T12:00:00Z")
        temp, _, result = self._run(metrics=metrics)
        self.addCleanup(temp.cleanup)
        self.assertTrue(result["seven_day_re_evaluation_due"])
        self.assertEqual(168.0, result["data_window_hours"])

    def test_nonblocked_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "production_send"):
            self._run(metrics=self._metrics(production_send="allowed"))


if __name__ == "__main__":
    unittest.main()
