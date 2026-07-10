from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from ais_etr.ais_v2_baseline_evaluation import MODEL_VERSION, build_v2_baseline_evaluation


class V2BaselineEvaluationTests(unittest.TestCase):
    @staticmethod
    def _item(ref, prediction_time, p50=60):
        return {
            "request_ref": ref,
            "result": {
                "etr": {
                    "p50_minutes": p50,
                    "model_version": MODEL_VERSION,
                    "prediction_created_at": prediction_time,
                }
            },
        }

    @staticmethod
    def _interval(ref, outage_time, restore_time, duration=30):
        return {
            "semantic_mapping_version": "alarm_mapping_v2",
            "pair_status": "CLOSED",
            "bridge_status": "METER_STATE_MODEL_READY",
            "outage_request_ref": ref,
            "outage_at": outage_time,
            "restore_at": restore_time,
            "duration_minutes": duration,
        }

    def _run(self, items, intervals, metrics=None):
        metrics = metrics or {"production_send": "blocked"}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = build_v2_baseline_evaluation(
                metrics,
                items,
                intervals,
                output_csv=root / "groups.csv",
                summary_json=root / "summary.json",
                report_md=root / "report.md",
                peacon_md=root / "peacon.md",
                registry_jsonl=root / "registry.jsonl",
                rejection_csv=root / "rejections.csv",
                now=datetime(2026, 7, 10, tzinfo=timezone.utc),
            )
            with (root / "groups.csv").open(encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            bundle = (
                (root / "summary.json").read_text(encoding="utf-8")
                + (root / "report.md").read_text(encoding="utf-8")
                + (root / "peacon.md").read_text(encoding="utf-8")
                + (root / "registry.jsonl").read_text(encoding="utf-8")
                + (root / "rejections.csv").read_text(encoding="utf-8-sig")
                + json.dumps(rows)
            )
            return result, rows, bundle

    def test_first_clean_prediction_is_scorable(self):
        items = [self._item("secret-ref", "2026-07-10T01:00:00Z")]
        intervals = [self._interval("secret-ref", "2026-07-10T01:00:00Z", "2026-07-10T01:45:00Z", 45)]
        result, rows, bundle = self._run(items, intervals)
        self.assertEqual(1, result["scorable_independent_incidents"])
        self.assertEqual(15.0, result["mae_minutes"])
        self.assertEqual("TRUE", rows[0]["green_incident"])
        self.assertNotIn("secret-ref", bundle)
        self.assertEqual("research_baseline_accumulating", result["gate_status"])
        self.assertEqual("pilot_smoke_only", result["sample_size_status"])
        self.assertFalse(result["research_metric_claim_allowed"])
        self.assertFalse(result["production_accuracy_claim_allowed"])

    def test_meter_rows_within_five_minutes_form_one_incident(self):
        items = [
            self._item("r1", "2026-07-10T01:00:00Z"),
            self._item("r2", "2026-07-10T01:03:00Z"),
            self._item("r3", "2026-07-10T01:10:00Z"),
        ]
        intervals = [
            self._interval("r1", "2026-07-10T01:00:00Z", "2026-07-10T01:45:00Z", 45),
            self._interval("r2", "2026-07-10T01:03:00Z", "2026-07-10T01:48:00Z", 45),
            self._interval("r3", "2026-07-10T01:10:00Z", "2026-07-10T02:10:00Z", 60),
        ]
        result, rows, _ = self._run(items, intervals)
        self.assertEqual(2, result["scorable_independent_incidents"])
        self.assertEqual(2, len(rows))
        self.assertEqual("2", rows[0]["meter_interval_count"])

    def test_prediction_at_or_after_restore_is_rejected(self):
        items = [self._item("r1", "2026-07-10T02:00:00Z")]
        intervals = [self._interval("r1", "2026-07-10T01:00:00Z", "2026-07-10T02:00:00Z", 60)]
        result, rows, bundle = self._run(items, intervals)
        self.assertEqual([], rows)
        self.assertEqual(1, result["rejection_counts"]["late_arriving_outage_after_restore"])
        self.assertEqual(0, result["rejection_counts"]["prediction_time_leakage"])
        self.assertFalse(result["time_leakage_detected"])
        self.assertIn("late_arriving_outage_after_restore", bundle)
        self.assertNotIn("r1", bundle)
        self.assertEqual("awaiting_first_scorable_incident", result["gate_status"])

    def test_missing_prediction_is_not_scored_retroactively(self):
        intervals = [self._interval("r1", "2026-07-10T01:00:00Z", "2026-07-10T02:00:00Z", 60)]
        result, rows, _ = self._run([], intervals)
        self.assertEqual([], rows)
        self.assertEqual(1, result["rejection_counts"]["missing_outage_request"])

    def test_high_error_clean_incident_is_retained(self):
        items = [self._item("r1", "2026-07-10T01:00:00Z")]
        intervals = [self._interval("r1", "2026-07-10T01:00:00Z", "2026-07-10T04:20:00Z", 200)]
        result, rows, _ = self._run(items, intervals)
        self.assertEqual(140.0, result["mae_minutes"])
        self.assertEqual("FALSE", rows[0]["green_incident"])
        self.assertEqual("TRUE", rows[0]["high_error_incident"])
        self.assertEqual(140.0, result["mean_worst_meter_absolute_error_minutes"])

    def test_worst_meter_guardrail_survives_incident_median(self):
        items = [
            self._item("r1", "2026-07-10T01:00:00Z"),
            self._item("r2", "2026-07-10T01:02:00Z"),
            self._item("r3", "2026-07-10T01:03:00Z"),
        ]
        intervals = [
            self._interval("r1", "2026-07-10T01:00:00Z", "2026-07-10T02:00:00Z", 60),
            self._interval("r2", "2026-07-10T01:02:00Z", "2026-07-10T02:02:00Z", 60),
            self._interval("r3", "2026-07-10T01:03:00Z", "2026-07-10T03:03:00Z", 120),
        ]
        result, rows, _ = self._run(items, intervals)
        self.assertEqual(1, len(rows))
        self.assertEqual(0.0, result["mae_minutes"])
        self.assertEqual(60.0, result["mean_worst_meter_absolute_error_minutes"])
        self.assertEqual("TRUE", rows[0]["high_error_incident"])

    def test_nonblocked_metrics_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "production_send"):
            self._run([], [], {"production_send": "allowed"})

    def test_registry_is_deterministic_and_idempotent(self):
        items = [self._item("r1", "2026-07-10T01:00:00Z")]
        intervals = [self._interval("r1", "2026-07-10T01:00:00Z", "2026-07-10T01:45:00Z", 45)]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kwargs = {
                "output_csv": root / "groups.csv",
                "summary_json": root / "summary.json",
                "report_md": root / "report.md",
                "peacon_md": root / "peacon.md",
                "registry_jsonl": root / "registry.jsonl",
                "rejection_csv": root / "rejections.csv",
                "now": datetime(2026, 7, 10, tzinfo=timezone.utc),
            }
            first = build_v2_baseline_evaluation({"production_send": "blocked"}, items, intervals, **kwargs)
            second = build_v2_baseline_evaluation({"production_send": "blocked"}, items, intervals, **kwargs)
            lines = (root / "registry.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(first["evaluation_id"], second["evaluation_id"])
        self.assertTrue(first["registry_entry_added"])
        self.assertFalse(second["registry_entry_added"])
        self.assertEqual(1, len(lines))

    def test_sample_size_reaches_research_claim_threshold_at_thirty_incidents(self):
        items = []
        intervals = []
        for index in range(30):
            hour = index // 2
            minute = (index % 2) * 10
            outage = datetime(2026, 7, 8, hour, minute, tzinfo=timezone.utc)
            restore = outage.replace(minute=minute + 6)
            ref = f"r{index}"
            items.append(self._item(ref, outage.isoformat().replace("+00:00", "Z")))
            intervals.append(
                self._interval(
                    ref,
                    outage.isoformat().replace("+00:00", "Z"),
                    restore.isoformat().replace("+00:00", "Z"),
                    6,
                )
            )
        result, rows, _ = self._run(items, intervals)
        self.assertEqual(30, len(rows))
        self.assertEqual("evaluation_sample_ready", result["sample_size_status"])
        self.assertTrue(result["research_metric_claim_allowed"])
        self.assertFalse(result["production_accuracy_claim_allowed"])


if __name__ == "__main__":
    unittest.main()
