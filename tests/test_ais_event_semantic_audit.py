from __future__ import annotations

from datetime import datetime, timedelta, timezone
import argparse
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from ais_etr.ais_event_semantic_audit import build_event_semantic_audit
from ais_etr.cli import cmd_ais_event_semantic_audit


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
            summary = Path(temp) / "summary.json"
            result = build_event_semantic_audit(
                metrics,
                items,
                output_csv=Path(temp) / "audit.csv",
                report_md=Path(temp) / "audit.md",
                summary_json=summary,
                minimum_requests=minimum_requests,
                now=now + timedelta(days=days),
            )
            csv_text = (Path(temp) / "audit.csv").read_text(encoding="utf-8-sig")
            report_text = (Path(temp) / "audit.md").read_text(encoding="utf-8")
            summary_payload = json.loads(summary.read_text(encoding="utf-8"))
            self.assertNotIn("must-not-be-written", json.dumps(summary_payload))
        return result, csv_text, report_text

    @staticmethod
    def _item(
        event_type,
        source,
        value="AC_MAIN_FAIL",
        field="alarm_type",
        meter_hash="meter_hash",
        event_time="2026-07-10T00:00:00Z",
    ):
        return {
            "request_ref": "must-not-be-written",
            "semantic_capture_version": "v1",
            "received_at": event_time,
            "detected_at": event_time,
            "meter": {"hash": meter_hash, "last4": "9999"},
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
        self.assertEqual("observation_incomplete", result["contract_gate_status"])

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

    def test_twenty_valid_pairs_pass_contract_after_observation_threshold(self):
        items = []
        for index in range(20):
            meter = f"meter_{index}"
            items.append(self._item("OUTAGE", "mapped_alarm_type", meter_hash=meter, event_time="2026-07-10T00:00:00Z"))
            items.append(self._item("STATUS", "mapped_unknown", value="AC_MAIN_RESTORE", meter_hash=meter, event_time="2026-07-10T00:30:00Z"))
        for index in range(60):
            items.append(self._item("STATUS", "mapped_unknown", value="AC_MAIN_RESTORE", meter_hash=f"prior_{index}", event_time="2026-07-10T00:15:00Z"))
        result, _, _ = self._run(items)
        self.assertEqual("contract_ready_for_activation", result["contract_gate_status"])
        self.assertTrue(result["activation_candidate_ready"])
        self.assertEqual(20, result["candidate_pair_audit"]["valid_pairs"])
        self.assertEqual(60, result["candidate_pair_audit"]["restore_without_prior_outage"])
        self.assertEqual("audit_only", result["preactivation_pair_policy"])

    def test_invalid_pair_duration_blocks_contract(self):
        items = []
        for index in range(20):
            meter = f"meter_{index}"
            restore_time = "2026-07-10T00:02:00Z" if index == 0 else "2026-07-10T00:30:00Z"
            items.append(self._item("OUTAGE", "mapped_alarm_type", meter_hash=meter, event_time="2026-07-10T00:00:00Z"))
            items.append(self._item("STATUS", "mapped_unknown", value="AC_MAIN_RESTORE", meter_hash=meter, event_time=restore_time))
        items.extend(self._item("OUTAGE", "mapped_alarm_type", meter_hash=f"extra_{index}") for index in range(60))
        result, _, _ = self._run(items)
        self.assertEqual("contract_blocked_pair_quality", result["contract_gate_status"])
        self.assertFalse(result["activation_candidate_ready"])
        self.assertEqual(1, result["candidate_pair_audit"]["invalid_pairs"])

    def test_restore_semantic_conflict_blocks_contract(self):
        items = []
        for index in range(20):
            meter = f"meter_{index}"
            items.append(self._item("OUTAGE", "mapped_alarm_type", meter_hash=meter))
            items.append(self._item("STATUS", "mapped_unknown", value="AC_MAIN_RESTORE", meter_hash=meter, event_time="2026-07-10T00:30:00Z"))
        conflict = self._item("OUTAGE", "mapped_alarm_type", value="AC_MAIN_RESTORE", meter_hash="conflict")
        items.append(conflict)
        items.extend(self._item("OUTAGE", "mapped_alarm_type", meter_hash=f"extra_{index}") for index in range(59))
        result, _, _ = self._run(items)
        self.assertEqual("contract_blocked_semantic_conflict", result["contract_gate_status"])
        self.assertFalse(result["activation_candidate_ready"])

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

    def test_cli_routes_summary_json_to_semantic_audit(self):
        args = argparse.Namespace(
            base_url="https://example.invalid",
            output="audit.csv",
            report="audit.md",
            summary_json="gate.json",
            limit=200,
            minimum_requests=100,
            minimum_days=7,
        )
        with patch("ais_etr.cli.run_event_semantic_audit", return_value={"production_send": "blocked"}) as run:
            cmd_ais_event_semantic_audit(args)
        self.assertEqual("gate.json", run.call_args.kwargs["summary_json"])


if __name__ == "__main__":
    unittest.main()
