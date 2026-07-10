from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from ais_etr.ais_v2_source_latency_audit import build_v2_source_latency_audit


class V2SourceLatencyAuditTests(unittest.TestCase):
    @staticmethod
    def _item(ref, prediction_time, p50=60):
        return {"request_ref": ref, "result": {"etr": {"p50_minutes": p50, "prediction_created_at": prediction_time}}}

    @staticmethod
    def _interval(ref, outage, restore, duration=30):
        return {
            "semantic_mapping_version": "alarm_mapping_v2",
            "pair_status": "CLOSED",
            "bridge_status": "METER_STATE_MODEL_READY",
            "outage_request_ref": ref,
            "outage_at": outage,
            "restore_at": restore,
            "duration_minutes": duration,
        }

    def _run(self, items, intervals, metrics=None):
        metrics = metrics or {"production_send": "blocked"}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = build_v2_source_latency_audit(
                metrics,
                items,
                intervals,
                output_csv=root / "audit.csv",
                summary_json=root / "summary.json",
                report_md=root / "report.md",
                peacon_md=root / "peacon.md",
            )
            with (root / "audit.csv").open(encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            bundle = (
                (root / "summary.json").read_text(encoding="utf-8")
                + (root / "report.md").read_text(encoding="utf-8")
                + (root / "peacon.md").read_text(encoding="utf-8")
                + json.dumps(rows)
            )
            return result, rows, bundle

    def test_active_prediction_latency_is_profiled_without_raw_reference(self):
        result, rows, bundle = self._run(
            [self._item("secret-ref", "2026-07-10T01:02:00Z")],
            [self._interval("secret-ref", "2026-07-10T01:00:00Z", "2026-07-10T01:30:00Z")],
        )
        self.assertEqual(1, result["counts"]["active_at_prediction"])
        self.assertEqual(2.0, result["active_prediction_latency_minutes"]["p50_minutes"])
        self.assertEqual("active_at_prediction", rows[0]["timeliness_class"])
        self.assertNotIn("secret-ref", bundle)

    def test_post_restore_prediction_is_review_not_training_evidence(self):
        result, rows, _ = self._run(
            [self._item("r1", "2026-07-10T01:31:00Z")],
            [self._interval("r1", "2026-07-10T01:00:00Z", "2026-07-10T01:30:00Z")],
        )
        self.assertEqual(1, result["counts"]["post_restore_at_prediction"])
        self.assertTrue(result["source_latency_review_required"])
        self.assertEqual("post_restore_at_prediction", rows[0]["timeliness_class"])
        self.assertFalse(result["training_allowed"])

    def test_missing_numeric_prediction_is_counted_but_not_emitted(self):
        result, rows, _ = self._run(
            [self._item("r1", "", p50=None)],
            [self._interval("r1", "2026-07-10T01:00:00Z", "2026-07-10T01:30:00Z")],
        )
        self.assertEqual(1, result["counts"]["missing_numeric_prediction"])
        self.assertEqual([], rows)

    def test_nonblocked_metrics_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "production_send"):
            self._run([], [], {"production_send": "allowed"})


if __name__ == "__main__":
    unittest.main()
