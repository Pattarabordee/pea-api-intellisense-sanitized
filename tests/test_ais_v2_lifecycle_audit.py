from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from ais_etr.ais_v2_lifecycle_audit import MAPPING_VERSION, _get_json, build_v2_lifecycle_audit


class V2LifecycleAuditTests(unittest.TestCase):
    def _item(
        self,
        *,
        request_ref: str,
        meter_hash: str,
        event_time: str,
        event_type: str,
        validation: str = "READY_FOR_LEDGER",
        mapping: str = MAPPING_VERSION,
    ):
        return {
            "request_ref": request_ref,
            "semantic_mapping_version": mapping,
            "detected_at": event_time,
            "received_at": event_time,
            "meter": {"hash": meter_hash, "last4": "9999"},
            "truth_observation": {
                "event_type": event_type,
                "event_type_source": "mapped_alarm_type",
                "validation_status": validation,
            },
        }

    @staticmethod
    def _interval(duration=30, *, status="CLOSED", bridge="METER_STATE_MODEL_READY"):
        return {
            "semantic_mapping_version": MAPPING_VERSION,
            "pair_status": status,
            "bridge_status": bridge,
            "duration_minutes": duration,
            "outage_at": "2026-07-10T01:00:00Z",
            "restore_at": "2026-07-10T01:30:00Z" if status == "CLOSED" else "",
        }

    def _run(self, items, intervals, metrics=None):
        metrics = metrics or {
            "production_send": "blocked",
            "v2_activation_first_seen_at": "2026-07-10T01:00:00Z",
            "v2_outage_events": 1,
            "v2_restore_events": 1,
            "v2_open_intervals": 0,
            "v2_model_ready_rows": 1,
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = build_v2_lifecycle_audit(
                metrics,
                items,
                intervals,
                output_csv=root / "cases.csv",
                report_md=root / "report.md",
                summary_json=root / "summary.json",
                peacon_md=root / "peacon.md",
                incident_csv=root / "incidents.csv",
            )
            with (root / "cases.csv").open(encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            report = (root / "report.md").read_text(encoding="utf-8")
            peacon = (root / "peacon.md").read_text(encoding="utf-8")
            summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
            return result, rows, report, peacon, summary

    def test_preactivation_restore_is_audit_only(self):
        items = [
            self._item(
                request_ref="historical-secret",
                meter_hash="meter-a",
                event_time="2026-07-10T00:30:00Z",
                event_type="OUTAGE",
                mapping="capture_v1",
            ),
            self._item(
                request_ref="restore-secret",
                meter_hash="meter-a",
                event_time="2026-07-10T01:30:00Z",
                event_type="RESTORE",
                validation="REVIEW_NO_OPEN_INTERVAL",
            ),
        ]
        result, rows, report, peacon, summary = self._run(items, [])
        self.assertEqual("activation_backlog_or_duplicate_restore_observed", result["gate_status"])
        self.assertEqual("preactivation_backlog_restore", rows[0]["classification"])
        self.assertEqual("FALSE", rows[0]["use_for_training"])
        encoded = json.dumps(summary) + report + peacon + json.dumps(rows)
        self.assertNotIn("historical-secret", encoded)
        self.assertNotIn("restore-secret", encoded)
        self.assertNotIn("9999", encoded)

    def test_duplicate_restore_is_classified(self):
        items = [
            self._item(request_ref="r1", meter_hash="meter-a", event_time="2026-07-10T01:10:00Z", event_type="RESTORE"),
            self._item(
                request_ref="r2",
                meter_hash="meter-a",
                event_time="2026-07-10T01:20:00Z",
                event_type="RESTORE",
                validation="REVIEW_NO_OPEN_INTERVAL",
            ),
        ]
        result, rows, *_ = self._run(items, [])
        self.assertEqual("duplicate_restore_after_v2_restore", rows[0]["classification"])
        self.assertEqual("activation_backlog_or_duplicate_restore_observed", result["gate_status"])

    def test_preactivation_interval_explains_restore_when_request_is_outside_window(self):
        restore = self._item(
            request_ref="r1",
            meter_hash="meter-a",
            event_time="2026-07-10T01:20:00Z",
            event_type="RESTORE",
            validation="REVIEW_NO_OPEN_INTERVAL",
        )
        historical_interval = {
            "semantic_mapping_version": "capture_v1",
            "pair_status": "REVIEW",
            "bridge_status": "REVIEW_PREACTIVATION_OPEN",
            "outage_at": "2026-07-10T00:30:00Z",
            "meter": {"hash": "meter-a", "last4": "9999"},
        }
        result, rows, *_ = self._run([restore], [historical_interval])
        self.assertEqual("preactivation_backlog_restore", rows[0]["classification"])
        self.assertEqual("activation_backlog_or_duplicate_restore_observed", result["gate_status"])

    def test_v2_outage_followed_by_no_open_restore_is_conflict(self):
        items = [
            self._item(request_ref="o1", meter_hash="meter-a", event_time="2026-07-10T01:10:00Z", event_type="OUTAGE"),
            self._item(
                request_ref="r1",
                meter_hash="meter-a",
                event_time="2026-07-10T01:20:00Z",
                event_type="RESTORE",
                validation="REVIEW_NO_OPEN_INTERVAL",
            ),
        ]
        result, rows, *_ = self._run(items, [])
        self.assertEqual("v2_sequence_conflict", rows[0]["classification"])
        self.assertEqual("bounded_lifecycle_evidence_review_required", result["gate_status"])

    def test_unexplained_restore_requires_review(self):
        item = self._item(
            request_ref="r1",
            meter_hash="meter-a",
            event_time="2026-07-10T01:20:00Z",
            event_type="RESTORE",
            validation="REVIEW_NO_OPEN_INTERVAL",
        )
        result, rows, *_ = self._run([item], [])
        self.assertEqual("bounded_window_evidence_missing", rows[0]["classification"])
        self.assertEqual("bounded_lifecycle_evidence_review_required", result["gate_status"])

    def test_clean_pair_without_prediction_snapshot_is_blocked(self):
        metrics = {
            "production_send": "blocked",
            "v2_activation_first_seen_at": "2026-07-10T01:00:00Z",
            "v2_outage_events": 1,
            "v2_restore_events": 1,
            "v2_open_intervals": 0,
            "v2_model_ready_rows": 1,
        }
        outage = self._item(
            request_ref="outage-ref",
            meter_hash="meter-a",
            event_time="2026-07-10T01:00:00Z",
            event_type="OUTAGE",
        )
        interval = self._interval()
        interval["outage_request_ref"] = "outage-ref"
        result, rows, *_ = self._run([outage], [interval], metrics)
        self.assertEqual([], rows)
        self.assertEqual(1, result["clean_intervals_in_window"])
        self.assertEqual("prediction_snapshot_missing", result["gate_status"])
        self.assertEqual(1, result["missing_prediction_snapshots"])
        self.assertFalse(result["training_allowed"])

    def test_numeric_prediction_before_restore_is_valid_snapshot(self):
        outage = self._item(
            request_ref="outage-ref",
            meter_hash="meter-a",
            event_time="2026-07-10T01:00:00Z",
            event_type="OUTAGE",
        )
        outage["received_at"] = "2026-07-10T01:00:00Z"
        outage["etr_status"] = "SHADOW_BASELINE_CAPTURED"
        outage["result"] = {"etr": {"p50_minutes": 60, "prediction_created_at": "2026-07-10T01:00:00Z"}}
        interval = self._interval()
        interval["outage_request_ref"] = "outage-ref"
        result, *_ = self._run([outage], [interval])
        self.assertEqual(1, result["valid_prediction_snapshots"])
        self.assertEqual(0, result["missing_prediction_snapshots"])
        self.assertEqual("prospective_capture_accumulating", result["gate_status"])

    def test_invalid_closed_pair_blocks_integrity(self):
        result, _, *_ = self._run([], [self._interval(duration=3, bridge="METER_STATE_DURATION_REVIEW")])
        self.assertEqual("closed_pair_integrity_blocked", result["gate_status"])

    def test_conservative_incident_grouping_counts_independent_events(self):
        items = []
        intervals = []
        for index, outage_time in enumerate(
            ("2026-07-10T01:00:00Z", "2026-07-10T01:03:00Z", "2026-07-10T01:10:00Z")
        ):
            ref = f"outage-{index}"
            item = self._item(
                request_ref=ref,
                meter_hash=f"meter-{index}",
                event_time=outage_time,
                event_type="OUTAGE",
            )
            item["received_at"] = outage_time
            item["etr_status"] = "SHADOW_BASELINE_CAPTURED"
            item["result"] = {"etr": {"p50_minutes": 60, "prediction_created_at": outage_time}}
            interval = self._interval()
            interval["outage_at"] = outage_time
            interval["outage_request_ref"] = ref
            items.append(item)
            intervals.append(interval)
        result, *_ = self._run(items, intervals)
        self.assertEqual(2, result["clean_independent_incident_groups"])
        self.assertEqual(2, result["scorable_independent_incident_groups"])

    def test_nonblocked_metrics_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "production_send"):
            self._run([], [], {"production_send": "allowed"})

    def test_http_helper_is_get_only(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"production_send":"blocked"}'
        with patch("ais_etr.ais_v2_lifecycle_audit.urlopen", return_value=response) as open_url:
            payload = _get_json("https://example.invalid/metrics", "private-key")
        request = open_url.call_args.args[0]
        self.assertEqual("GET", request.get_method())
        self.assertEqual("blocked", payload["production_send"])


if __name__ == "__main__":
    unittest.main()
