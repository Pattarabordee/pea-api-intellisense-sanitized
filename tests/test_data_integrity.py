import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.data_integrity import (
    build_data_integrity_audit,
    build_truth_governance_review_status,
    truth_gate_for_row,
)


class DataIntegrityTests(unittest.TestCase):
    def test_truth_gate_allows_only_sustained_ais_outage_restore_truth(self):
        good = truth_gate_for_row(
            {
                "truth_source": "ais_site_power_status",
                "truth_target": "ais_site_actual_restoration_minutes",
                "truth_definition": "AIS_POWER_RESTORE_TIME - AIS_POWER_OUTAGE_TIME",
                "truth_quality": "OK",
                "actual_restoration_minutes": "45",
            },
            source_name="ais_truth",
        )
        short = truth_gate_for_row(
            {
                "truth_source": "ais_site_power_status",
                "truth_target": "ais_site_actual_restoration_minutes",
                "truth_definition": "AIS_POWER_RESTORE_TIME - AIS_POWER_OUTAGE_TIME",
                "truth_quality": "REVIEW_SHORT",
                "actual_restoration_minutes": "4.5",
            },
            source_name="ais_truth",
        )
        reportpo = truth_gate_for_row(
            {
                "truth_source": "reportpo",
                "truth_target": "reportpo_first_restore_minutes",
                "truth_definition": "FIRST_RESTORE_TIME - EVENT_START_TIME",
                "truth_quality": "OK",
                "actual_restoration_minutes": "30",
            },
            source_name="reportpo_etr",
        )

        self.assertEqual(good["truth_gate_status"], "model_ready_truth")
        self.assertEqual(good["model_use"], "eligible_truth")
        self.assertEqual(short["truth_gate_status"], "review_short_not_model_truth")
        self.assertIn("short_interruption_review", short["risk_flags"])
        self.assertEqual(reportpo["source_class"], "pea_kpi_reporting_context")
        self.assertEqual(reportpo["model_use"], "context_only")
        self.assertIn("event_end_time_not_truth", reportpo["risk_flags"])

    def test_builds_policy_governance_and_approval_outputs_without_peano_leakage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ais = root / "ais.csv"
            shadow = root / "shadow.csv"
            sfsd = root / "sfsd.csv"
            decision = root / "decision.csv"
            reportpo = root / "reportpo.csv"
            feature = root / "feature.csv"
            lifecycle = root / "lifecycle.csv"
            output = root / "audit.csv"
            policy = root / "policy.md"
            governance = root / "governance.md"
            approval = root / "approval.csv"
            request = root / "request.csv"
            _write_inputs(ais, shadow, sfsd, decision, reportpo, feature, lifecycle)

            result = build_data_integrity_audit(
                output,
                policy,
                governance,
                approval,
                request,
                ais_truth_csv=ais,
                shadow_comparison_csv=shadow,
                sfsd_evidence_csv=sfsd,
                sfsd_decision_csv=decision,
                reportpo_etr_csv=reportpo,
                reportpo_feature_audit_csv=feature,
                reportpo_lifecycle_audit_csv=lifecycle,
            )
            rows = _read_csv(output)
            approval_rows = _read_csv(approval)
            request_rows = _read_csv(request)
            by_source = {(row["source_name"], row["record_ref"]): row for row in rows}

            self.assertEqual(result["model_ready_truth_rows"], 1)
            self.assertEqual(result["owner_approval_rows"], 1)
            self.assertEqual(result["source_request_rows"], 2)
            self.assertEqual(approval_rows[0]["event_ref"], "msg-pfa02")
            self.assertEqual(request_rows[0]["status"], "open")
            self.assertEqual(
                by_source[("sfsd_gap_decision", "msg-pfa09")]["truth_gate_status"],
                "bridge_rejected_or_unusable",
            )
            self.assertEqual(
                by_source[("reportpo_lifecycle_join", "msg-close")]["truth_gate_status"],
                "blocked_close_time_not_truth",
            )
            audit_text = output.read_text(encoding="utf-8-sig")
            self.assertNotIn("6101000001", audit_text)
            self.assertIn("Truth Source Gate", policy.read_text(encoding="utf-8-sig"))
            self.assertIn("Production send: blocked", governance.read_text(encoding="utf-8-sig"))

    def test_truth_governance_review_status_validates_owner_review_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            approval = root / "approval.csv"
            request = root / "request.csv"
            output = root / "status.csv"
            markdown = root / "status.md"
            _write_rows(
                approval,
                [
                    "event_ref",
                    "event_time",
                    "feeder",
                    "webex_device_id",
                    "sfsd_candidate_device_id",
                    "final_decision",
                    "approval_scope",
                    "review_status",
                    "reviewer",
                    "reviewed_at",
                    "approved_context_fields",
                    "notes",
                ],
                [
                    {
                        "event_ref": "msg-approved",
                        "feeder": "PFA02",
                        "webex_device_id": "PFA02R-01",
                        "sfsd_candidate_device_id": "PFA02VB-01",
                        "approval_scope": "use_sfsd_lifecycle_cause_context_only_not_truth",
                        "review_status": "approved",
                        "reviewer": "topology-owner",
                        "reviewed_at": "2026-06-18",
                        "approved_context_fields": "cause;work_type",
                    },
                    {
                        "event_ref": "msg-bad-approved",
                        "feeder": "PFA03",
                        "webex_device_id": "PFA03VB-01",
                        "sfsd_candidate_device_id": "PFA03F-0789",
                        "approval_scope": "use_sfsd_lifecycle_cause_context_only_not_truth",
                        "review_status": "approved",
                        "reviewer": "topology-owner",
                        "approved_context_fields": "cause",
                    },
                    {
                        "event_ref": "msg-pending",
                        "feeder": "PFA04",
                        "webex_device_id": "PFA04R-01",
                        "sfsd_candidate_device_id": "PFA04VB-01",
                        "approval_scope": "use_sfsd_lifecycle_cause_context_only_not_truth",
                        "review_status": "pending",
                    },
                ],
            )
            _write_rows(
                request,
                [
                    "event_ref",
                    "event_time",
                    "feeder",
                    "webex_device_id",
                    "request_type",
                    "final_decision",
                    "recommended_question",
                    "status",
                    "owner_response",
                ],
                [
                    {
                        "event_ref": "msg-closed",
                        "feeder": "SEK06",
                        "webex_device_id": "SEK06VR-103",
                        "request_type": "exact_sfsd_event_key",
                        "status": "closed",
                        "owner_response": "No SFSD event is available inside bridge window.",
                    },
                    {
                        "event_ref": "msg-missing-response",
                        "feeder": "BDH03",
                        "webex_device_id": "BDH03VR-103",
                        "request_type": "exact_sfsd_event_key",
                        "status": "closed",
                    },
                    {
                        "event_ref": "msg-open",
                        "feeder": "PFA09",
                        "webex_device_id": "PFA09R-03",
                        "request_type": "exact_sfsd_event_key",
                        "status": "open",
                    },
                ],
            )

            result = build_truth_governance_review_status(approval, request, output, markdown)
            rows = _read_csv(output)
            by_event = {row["event_ref"]: row for row in rows}

            self.assertEqual(result["approved_context_rows"], 1)
            self.assertEqual(result["pending_approval_rows"], 1)
            self.assertEqual(result["open_source_request_rows"], 1)
            self.assertEqual(result["invalid_review_rows"], 2)
            self.assertTrue(result["governance_review_blocked"])
            self.assertEqual(by_event["msg-approved"]["validation_status"], "approved_context_only")
            self.assertEqual(by_event["msg-approved"]["usable_as_context"], "true")
            self.assertEqual(
                by_event["msg-missing-response"]["validation_status"],
                "invalid_resolved_missing_owner_response",
            )
            status_text = output.read_text(encoding="utf-8-sig")
            self.assertNotIn("6101000001", status_text)
            self.assertIn("AIS outage/restore remains", markdown.read_text(encoding="utf-8-sig"))


def _write_inputs(
    ais: Path,
    shadow: Path,
    sfsd: Path,
    decision: Path,
    reportpo: Path,
    feature: Path,
    lifecycle: Path,
) -> None:
    _write_rows(
        ais,
        [
            "site_id",
            "peano",
            "outage_start_time",
            "power_restore_time",
            "actual_restoration_minutes",
            "event_number",
            "device_id",
            "feeder",
            "source",
            "truth_source",
            "truth_target",
            "truth_definition",
            "truth_quality",
            "truth_notes",
            "source_file",
            "source_row_number",
        ],
        [
            {
                "site_id": "site-1",
                "peano": "<REDACTED_METER_REF>",
                "outage_start_time": "2026-01-01 00:00:00",
                "power_restore_time": "2026-01-01 00:45:00",
                "actual_restoration_minutes": "45",
                "truth_source": "ais_site_power_status",
                "truth_target": "ais_site_actual_restoration_minutes",
                "truth_definition": "AIS_POWER_RESTORE_TIME - AIS_POWER_OUTAGE_TIME",
                "truth_quality": "OK",
                "source_row_number": "2",
            },
            {
                "site_id": "site-2",
                "peano": "<REDACTED_METER_REF>",
                "outage_start_time": "2026-01-01 01:00:00",
                "power_restore_time": "2026-01-01 01:04:00",
                "actual_restoration_minutes": "4",
                "truth_source": "ais_site_power_status",
                "truth_target": "ais_site_actual_restoration_minutes",
                "truth_definition": "AIS_POWER_RESTORE_TIME - AIS_POWER_OUTAGE_TIME",
                "truth_quality": "REVIEW_SHORT",
                "source_row_number": "3",
            },
        ],
    )
    _write_rows(
        shadow,
        ["event_id", "webex_message_ref", "event_time", "feeder", "device_id", "match_level", "actual_restoration_minutes", "truth_source"],
        [
            {
                "event_id": "event-1",
                "webex_message_ref": "msg-shadow",
                "event_time": "2026-01-01T00:00:00",
                "feeder": "PFA02",
                "device_id": "PFA02R-01",
                "match_level": "recloser",
                "actual_restoration_minutes": "45",
                "truth_source": "ais_site_power_status",
            }
        ],
    )
    _write_rows(
        sfsd,
        [
            "event_ref",
            "event_time",
            "feeder",
            "device_id",
            "remaining_actual_minutes",
            "sfsd_duration_minutes",
            "sfsd_match_level",
            "pea_ais_pattern",
        ],
        [
            {
                "event_ref": "msg-short-long",
                "event_time": "2026-01-01T00:00:00",
                "feeder": "PFA02",
                "device_id": "PFA02R-01",
                "remaining_actual_minutes": "300",
                "sfsd_duration_minutes": "0.5",
                "sfsd_match_level": "event_number",
                "pea_ais_pattern": "pea_momentary_or_short_ais_long",
            }
        ],
    )
    _write_rows(
        decision,
        [
            "event_ref",
            "event_time",
            "feeder",
            "webex_device_id",
            "sfsd_candidate_device_id",
            "resolution_status",
            "final_decision",
            "final_action",
        ],
        [
            {
                "event_ref": "msg-pfa02",
                "event_time": "2026-01-01T00:00:00",
                "feeder": "PFA02",
                "webex_device_id": "PFA02R-01",
                "sfsd_candidate_device_id": "PFA02VB-01",
                "resolution_status": "topology_supported_pending_owner_approval",
                "final_decision": "topology_supported_owner_approval_needed",
            },
            {
                "event_ref": "msg-pfa09",
                "event_time": "2026-01-01T02:00:00",
                "feeder": "PFA09",
                "webex_device_id": "PFA09R-03",
                "sfsd_candidate_device_id": "PFA09F-05/2",
                "resolution_status": "source_trace_required_for_topology_gap",
                "final_decision": "reject_sfsd_candidate_webex_device_confirmed",
            },
            {
                "event_ref": "msg-sek06",
                "event_time": "2026-01-01T03:00:00",
                "feeder": "SEK06",
                "webex_device_id": "SEK06VR-103",
                "resolution_status": "same_device_far_sfsd_candidate_context_only",
                "final_decision": "do_not_bridge_time_gap_too_large",
            },
        ],
    )
    _write_rows(
        reportpo,
        [
            "event_number",
            "event_start_time",
            "first_restore_time",
            "event_etr_time",
            "event_end_time",
            "device_id",
            "feeder",
            "actual_restoration_minutes",
            "truth_source",
            "truth_target",
            "truth_definition",
            "truth_quality",
            "truth_flags",
        ],
        [
            {
                "event_number": "1001",
                "event_start_time": "2026-01-01 00:00:00",
                "event_etr_time": "2026-01-01 02:00:00",
                "event_end_time": "2026-01-01 01:00:00",
                "device_id": "PFA02R-01",
                "feeder": "PFA02",
                "actual_restoration_minutes": "45",
                "truth_source": "reportpo",
                "truth_target": "reportpo_first_restore_minutes",
                "truth_definition": "FIRST_RESTORE_TIME - EVENT_START_TIME",
                "truth_quality": "OK",
                "truth_flags": "event_etr_time_not_truth;event_end_time_not_truth",
            }
        ],
    )
    _write_rows(
        feature,
        ["webex_message_id", "webex_event_time", "webex_device_id", "webex_feeder", "match_status", "feature_flags"],
        [{"webex_message_id": "msg-feature", "webex_event_time": "2026-01-01", "webex_device_id": "PFA02R-01", "webex_feeder": "PFA02", "match_status": "matched"}],
    )
    _write_rows(
        lifecycle,
        ["webex_message_id", "webex_event_time", "webex_device_id", "webex_feeder", "match_status", "cl_datetime", "lifecycle_flags"],
        [{"webex_message_id": "msg-close", "webex_event_time": "2026-01-01", "webex_device_id": "PFA02R-01", "webex_feeder": "PFA02", "match_status": "matched", "cl_datetime": "2026-01-01 01:00:00"}],
    )


def _write_rows(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
