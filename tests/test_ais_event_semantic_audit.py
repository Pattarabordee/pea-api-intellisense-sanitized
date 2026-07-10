from __future__ import annotations

from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path
import unittest

from ais_etr.ais_event_semantic_audit import build_event_semantic_audit


class EventSemanticAuditTests(unittest.TestCase):
    def _run(self, items, metrics=None, *, days=0, minimum_requests=100):
        metrics = metrics or {
            "production_send": "blocked",
            "truth_open_intervals": 1,
            "truth_meter_state_open_intervals": 1,
            "truth_stale_open_intervals": 0,
            "model_ready_clean_truth_rows": 0,
        }
        now = datetime(2026, 7, 10, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            result = build_event_semantic_audit(
                metrics,
                items,
                output_csv=Path(temp) / "audit.csv",
                report_md=Path(temp) / "audit.md",
                minimum_requests=minimum_requests,
                now=now + timedelta(days=days),
            )
            csv_text = (Path(temp) / "audit.csv").read_text(encoding="utf-8-sig")
            report_text = (Path(temp) / "audit.md").read_text(encoding="utf-8")
        return result, csv_text, report_text

    @staticmethod
    def _item(event_type, source, value="AC_MAIN_FAIL", field="alarm_type"):
        return {
            "request_ref": "must-not-be-written",
            "semantic_capture_version": "v1",
            "received_at": "2026-07-10T00:00:00Z",
            "meter": {"last4": "9999"},
            "truth_observation": {
                "event_type": event_type,
                "event_type_source": source,
                "validation_status": "READY_FOR_LEDGER" if event_type in {"OUTAGE", "RESTORE"} else "REVIEW_EVENT_TYPE",
            },
            "semantic_signals": {
                field: {"present": True, "value": value, "value_ref": "semantic_ref"},
            },
        }

    def test_outage_only_stays_insufficient_before_threshold(self):
        result, csv_text, _ = self._run([self._item("OUTAGE", "mapped_alarm_type")])
        self.assertEqual("insufficient_semantic_observations", result["gate_status"])
        self.assertNotIn("must-not-be-written", csv_text)
        self.assertNotIn("9999", csv_text)

    def test_pre_capture_rows_do_not_satisfy_threshold(self):
        legacy = [self._item("OUTAGE", "mapped_alarm_type") for _ in range(100)]
        for item in legacy:
            item.pop("semantic_capture_version")
        result, _, _ = self._run(legacy)
        self.assertEqual(0, result["observed_requests"])
        self.assertEqual("insufficient_semantic_observations", result["gate_status"])

    def test_missing_restore_after_threshold_is_explicit(self):
        items = [self._item("OUTAGE", "mapped_alarm_type") for _ in range(100)]
        result, _, _ = self._run(items)
        self.assertEqual("restore_signal_missing", result["gate_status"])

    def test_restore_candidate_requires_review(self):
        items = [self._item("OUTAGE", "mapped_alarm_type") for _ in range(99)]
        items.append(self._item("STATUS", "mapped_unknown", value="CLEAR", field="alarm_status"))
        result, _, _ = self._run(items)
        self.assertEqual("restore_candidate_review_required", result["gate_status"])

    def test_structured_restore_alarm_is_candidate_not_truth(self):
        item = self._item("STATUS", "mapped_unknown", value="AC_MAIN_RESTORE", field="alarm_type")
        result, _, _ = self._run([item])
        self.assertEqual(1, result["restore_candidate_count"])
        self.assertEqual("insufficient_semantic_observations", result["gate_status"])

    def test_valid_pair_with_model_ready_can_pass_semantic_gate(self):
        metrics = {
            "production_send": "blocked",
            "truth_open_intervals": 0,
            "truth_meter_state_open_intervals": 0,
            "truth_stale_open_intervals": 0,
            "model_ready_clean_truth_rows": 1,
        }
        items = [
            self._item("OUTAGE", "mapped_alarm_type"),
            self._item("RESTORE", "mapped_status", value="ON", field="power_status"),
        ]
        result, _, _ = self._run(items, metrics)
        self.assertEqual("semantic_mapping_ready", result["gate_status"])

    def test_nonblocked_production_state_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "production_send"):
            self._run([], {"production_send": "allowed"})


if __name__ == "__main__":
    unittest.main()
