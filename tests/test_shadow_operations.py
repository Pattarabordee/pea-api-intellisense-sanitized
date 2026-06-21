import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.shadow_operations import (
    build_ais_daily_file_qa,
    build_context_review_priority_pack,
    build_current_capability_development_plan,
    build_duplicate_flapping_audit,
    build_eligibility_threshold_calibration,
    build_executive_one_pager,
    build_flapping_policy_draft,
    build_flapping_sensitivity_plan,
    build_green_candidate_error_review,
    build_green_candidate_growth_plan,
    build_green_gate_tracker,
    build_mapping_repair_queue,
    build_mapping_repair_request_pack,
    build_operator_console_qa,
    build_operator_console_mock,
    build_owner_followup_tracker,
    build_owner_handoff_pack,
    build_owner_message_drafts,
    build_owner_response_dry_run_impact,
    build_owner_response_examples,
    build_owner_response_intake,
    build_owner_response_templates,
    build_daily_executive_delta,
    build_executive_pitch_pack,
    build_pitching_narrative_script,
    build_shadow_status_payload_contract,
    build_status_only_payload_templates,
    validate_owner_response_files,
    build_webex_truth_request_pack,
    build_webex_only_monitoring_report,
)


class ShadowOperationsTests(unittest.TestCase):
    def test_green_review_and_threshold_calibration_keep_gate_blocked_when_coverage_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            eligibility = root / "eligibility.csv"
            _write_csv(
                eligibility,
                [
                    "event_ref",
                    "event_time",
                    "district",
                    "feeder",
                    "device_id",
                    "source_lane",
                    "match_level",
                    "match_confidence",
                    "affected_count",
                    "active_ais_outage_confirmed",
                    "webex_device_interruption_class",
                    "actual_restoration_minutes",
                    "selected_p50",
                    "selected_q10",
                    "selected_q90",
                    "prediction_interval_width",
                    "selected_absolute_error",
                    "selected_covered_q10_q90",
                    "eligibility_status",
                    "stage1_class",
                    "blocker_reasons",
                ],
                [
                    _eligibility_row("msg-green-1", "green_auto_candidate", "ais_truth_matched", "SEK06", "155", "153", "80", "180", "100", "2", "TRUE", "sustained_candidate"),
                    _eligibility_row("msg-green-2", "green_auto_candidate", "ais_truth_matched", "WWA09", "32", "107", "75", "166", "91", "75", "FALSE", "momentary_le_1m"),
                    _eligibility_row("msg-amber", "amber_human_review", "ais_truth_matched", "SEK06", "220", "40", "5", "170", "165", "180", "FALSE", "sustained_candidate"),
                    _eligibility_row("msg-webex", "monitor_only", "webex_trigger_no_ais_truth", "PFA01", "", "36", "14", "71", "57", "", "", "sustained_candidate"),
                ],
            )

            review = build_green_candidate_error_review(eligibility, root / "green.csv", root / "green.md")
            calibration = build_eligibility_threshold_calibration(eligibility, root / "cal.csv", root / "cal.md")

            self.assertEqual(review["rows"], 2)
            self.assertIn("momentary_webex_but_ais_sustained", (root / "green.md").read_text(encoding="utf-8-sig"))
            rows = _read_csv(root / "cal.csv")
            self.assertTrue(any(row["variant"] == "current_policy" for row in rows))
            self.assertIn(calibration["best_gate_status"], {"blocked_metric_gate_failed", "blocked_too_few_green_rows"})

    def test_context_priority_and_webex_monitoring_do_not_promote_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence.csv"
            eligibility = root / "eligibility.csv"
            _write_csv(
                evidence,
                [
                    "event_ref",
                    "event_time",
                    "feeder",
                    "device_id",
                    "actual_restoration_minutes",
                    "selected_absolute_error",
                    "evidence_status",
                    "evidence_score",
                    "context_sources",
                    "cause_group",
                    "work_type",
                    "weather_or_lightning",
                    "evidence_reasons",
                ],
                [
                    {
                        "event_ref": "msg-approved",
                        "event_time": "2026-06-19T08:00:00",
                        "feeder": "SEK06",
                        "device_id": "SEK06VR-104",
                        "actual_restoration_minutes": "200",
                        "selected_absolute_error": "160",
                        "evidence_status": "approved_candidate",
                        "evidence_score": "80",
                        "context_sources": "sfsd",
                        "cause_group": "weather",
                        "work_type": "tree",
                        "weather_or_lightning": "TRUE",
                        "evidence_reasons": "sfsd_context_candidate",
                    },
                    {
                        "event_ref": "msg-conflict",
                        "event_time": "2026-06-19T09:00:00",
                        "feeder": "PFA02",
                        "device_id": "PFA02VR-101",
                        "actual_restoration_minutes": "180",
                        "selected_absolute_error": "120",
                        "evidence_status": "rejected_conflict",
                        "evidence_score": "0",
                        "context_sources": "sfsd",
                        "cause_group": "",
                        "work_type": "",
                        "weather_or_lightning": "",
                        "evidence_reasons": "pea_momentary_ais_sustained_conflict",
                    },
                ],
            )
            _write_csv(
                eligibility,
                [
                    "event_ref",
                    "event_time",
                    "district",
                    "feeder",
                    "device_id",
                    "source_lane",
                    "match_level",
                    "match_confidence",
                    "affected_count",
                    "webex_device_interruption_class",
                    "selected_p50",
                    "selected_q90",
                    "prediction_interval_width",
                    "eligibility_status",
                    "blocker_reasons",
                ],
                [
                    {
                        "event_ref": "msg-webex",
                        "event_time": "2026-06-19T08:00:00",
                        "district": "พังโคน",
                        "feeder": "PFA01",
                        "device_id": "PFA01YB-101",
                        "source_lane": "webex_trigger_no_ais_truth",
                        "match_level": "recloser",
                        "match_confidence": "0.9",
                        "affected_count": "4",
                        "webex_device_interruption_class": "sustained_candidate",
                        "selected_p50": "40",
                        "selected_q90": "180",
                        "prediction_interval_width": "120",
                        "eligibility_status": "monitor_only",
                        "blocker_reasons": "missing_ais_truth",
                    }
                ],
            )

            priority = build_context_review_priority_pack(evidence, root / "priority.csv", root / "priority.md")
            monitor = build_webex_only_monitoring_report(eligibility, root / "monitor.csv", root / "monitor.md")

            self.assertEqual(priority["rows"], 1)
            self.assertIn("AIS outage/restore remains the restoration truth", (root / "priority.md").read_text(encoding="utf-8-sig"))
            self.assertEqual(monitor["rows"], 1)
            self.assertIn("Do not use these rows for MAE", (root / "monitor.md").read_text(encoding="utf-8-sig"))

    def test_operator_console_mock_renders_static_shadow_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            eligibility = root / "eligibility.csv"
            evidence = root / "evidence.csv"
            _write_csv(
                eligibility,
                [
                    "event_ref",
                    "event_time",
                    "feeder",
                    "device_id",
                    "source_lane",
                    "eligibility_status",
                    "stage1_class",
                    "selected_p50",
                    "selected_absolute_error",
                    "selected_covered_q10_q90",
                    "blocker_reasons",
                ],
                [
                    {"event_ref": "msg-green", "event_time": "2026-06-19T08:00:00", "feeder": "SEK06", "device_id": "SEK06VR-104", "source_lane": "ais_truth_matched", "eligibility_status": "green_auto_candidate", "stage1_class": "normal", "selected_p50": "20", "selected_absolute_error": "10", "selected_covered_q10_q90": "TRUE", "blocker_reasons": ""},
                    {"event_ref": "msg-red", "event_time": "2026-06-19T08:10:00", "feeder": "PFA02", "device_id": "PFA02VR-101", "source_lane": "pea_quarantined", "eligibility_status": "red_blocked", "stage1_class": "uncertain", "selected_p50": "", "selected_absolute_error": "", "selected_covered_q10_q90": "", "blocker_reasons": "pea_quarantined"},
                ],
            )
            _write_csv(
                evidence,
                ["event_ref", "feeder", "device_id", "evidence_status", "evidence_score", "evidence_reasons", "cause_group", "work_type"],
                [{"event_ref": "msg-approved", "feeder": "SEK06", "device_id": "SEK06VR-104", "evidence_status": "approved_candidate", "evidence_score": "80", "evidence_reasons": "context", "cause_group": "weather", "work_type": "tree"}],
            )

            result = build_operator_console_mock(eligibility, evidence, root / "console.html", root / "console.md")

            self.assertEqual(result["green"], 1)
            html = (root / "console.html").read_text(encoding="utf-8-sig")
            self.assertIn("AIS ETR Shadow Ops Console", html)
            self.assertIn("No production send", html)
            self.assertNotIn("PEANO", html)

    def test_green_gate_tracker_counts_additional_rows_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            eligibility = root / "eligibility.csv"
            threshold = root / "threshold.csv"
            _write_csv(
                eligibility,
                ["event_ref", "source_lane", "eligibility_status", "actual_restoration_minutes", "selected_absolute_error", "selected_covered_q10_q90"],
                [
                    {"event_ref": "msg-1", "source_lane": "ais_truth_matched", "eligibility_status": "green_auto_candidate", "actual_restoration_minutes": "30", "selected_absolute_error": "10", "selected_covered_q10_q90": "TRUE"},
                    {"event_ref": "msg-2", "source_lane": "ais_truth_matched", "eligibility_status": "amber_human_review", "actual_restoration_minutes": "90", "selected_absolute_error": "60", "selected_covered_q10_q90": "FALSE"},
                ],
            )
            _write_csv(
                threshold,
                ["variant", "green_rows", "mae", "coverage", "gate_status"],
                [{"variant": "current_policy", "green_rows": "1", "mae": "10", "coverage": "1", "gate_status": "blocked_too_few_green_rows"}],
            )

            result = build_green_gate_tracker(eligibility, threshold, root / "gate.csv", root / "gate.md", min_green_rows=5)

            self.assertEqual(result["green_rows"], 1)
            self.assertEqual(result["additional_green_rows_needed"], 4)
            self.assertIn("Additional green rows needed: 4", (root / "gate.md").read_text(encoding="utf-8-sig"))

    def test_ais_daily_file_qa_splits_usable_review_and_reject_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "candidate.csv"
            review = root / "review.csv"
            rejects = root / "rejects.csv"
            audit = root / "audit.csv"
            columns = ["site_id", "peano", "outage_start_time", "power_restore_time", "actual_restoration_minutes", "truth_quality"]
            _write_csv(
                candidates,
                columns,
                [
                    {"site_id": "site-1", "peano": "REDACTED-METER-0000", "outage_start_time": "2026-06-19T08:00:00", "power_restore_time": "2026-06-19T08:30:00", "actual_restoration_minutes": "30", "truth_quality": "OK"},
                    {"site_id": "site-2", "peano": "", "outage_start_time": "2026-06-19T08:00:00", "power_restore_time": "2026-06-19T08:10:00", "actual_restoration_minutes": "10", "truth_quality": "MISSING_PEANO_MAPPING"},
                ],
            )
            _write_csv(review, columns, [{"site_id": "site-3", "peano": "REDACTED-METER-0000", "outage_start_time": "2026-06-19T08:00:00", "power_restore_time": "2026-06-19T08:03:00", "actual_restoration_minutes": "3", "truth_quality": "REVIEW_SHORT"}])
            _write_csv(rejects, columns, [{"site_id": "site-4", "peano": "", "outage_start_time": "2026-06-19T08:00:00", "power_restore_time": "", "actual_restoration_minutes": "", "truth_quality": "MISSING_RESTORE"}])
            _write_csv(audit, ["mapping_status"], [{"mapping_status": "matched_single_peano"}, {"mapping_status": "no_mapped_peano"}])

            result = build_ais_daily_file_qa(candidates, review, rejects, audit, root / "qa.csv", root / "qa.md")

            self.assertEqual(result["usable_sustained_ok_rows"], 1)
            self.assertEqual(result["review_le_5min_rows"], 1)
            self.assertEqual(result["reject_rows"], 1)
            self.assertIn("AIS Daily File QA", (root / "qa.md").read_text(encoding="utf-8-sig"))

    def test_status_only_payloads_omit_etr_quantiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            eligibility = root / "eligibility.csv"
            _write_csv(
                eligibility,
                [
                    "event_ref",
                    "event_time",
                    "feeder",
                    "device_id",
                    "source_lane",
                    "match_level",
                    "affected_count",
                    "eligibility_status",
                    "blocker_reasons",
                    "selected_p50",
                    "selected_q10",
                    "selected_q90",
                ],
                [
                    {"event_ref": "msg-amber", "event_time": "2026-06-19T08:00:00", "feeder": "SEK06", "device_id": "SEK06VR-104", "source_lane": "ais_truth_matched", "match_level": "recloser", "affected_count": "9", "eligibility_status": "amber_human_review", "blocker_reasons": "momentary_webex_requires_review", "selected_p50": "100", "selected_q10": "50", "selected_q90": "180"},
                    {"event_ref": "msg-monitor", "event_time": "2026-06-19T08:10:00", "feeder": "PFA01", "device_id": "PFA01YB-101", "source_lane": "webex_trigger_no_ais_truth", "match_level": "", "affected_count": "0", "eligibility_status": "monitor_only", "blocker_reasons": "missing_ais_truth", "selected_p50": "40", "selected_q10": "20", "selected_q90": "70"},
                ],
            )

            result = build_status_only_payload_templates(eligibility, root / "payloads.jsonl", root / "payloads.md")
            text = (root / "payloads.jsonl").read_text(encoding="utf-8")

            self.assertEqual(result["payload_rows"], 2)
            self.assertIn("status_only", text)
            self.assertNotIn("selected_p50", text)
            self.assertNotIn("q90", text)

    def test_operator_console_qa_checks_required_labels_and_sensitive_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            eligibility = root / "eligibility.csv"
            evidence = root / "evidence.csv"
            _write_csv(
                eligibility,
                ["event_ref", "source_lane", "eligibility_status", "selected_absolute_error", "selected_covered_q10_q90"],
                [{"event_ref": "msg-green", "source_lane": "ais_truth_matched", "eligibility_status": "green_auto_candidate", "selected_absolute_error": "10", "selected_covered_q10_q90": "TRUE"}],
            )
            _write_csv(evidence, ["event_ref", "evidence_status"], [])
            build_operator_console_mock(eligibility, evidence, root / "console.html")

            result = build_operator_console_qa(root / "console.html", root / "console_qa.md")

            self.assertTrue(result["passed"])
            self.assertIn("Operator Console QA", (root / "console_qa.md").read_text(encoding="utf-8-sig"))

    def test_mapping_repair_queue_redacts_public_and_keeps_private_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = root / "audit.csv"
            candidates = root / "candidate.csv"
            rejects = root / "rejects.csv"
            _write_csv(
                audit,
                [
                    "location_id",
                    "sitecode",
                    "outage_start_time",
                    "power_restore_time",
                    "actual_restoration_minutes",
                    "mapping_status",
                    "truth_quality",
                    "alarm_type",
                ],
                [
                    {"location_id": "870237", "sitecode": "NTWPC", "outage_start_time": "2026-06-19 08:00:00", "power_restore_time": "2026-06-19 09:00:00", "actual_restoration_minutes": "60", "mapping_status": "no_mapped_meter", "truth_quality": "MISSING_MAPPING", "alarm_type": "AC MAIN FAIL-C1"},
                    {"location_id": "870237", "sitecode": "NTWPC", "outage_start_time": "2026-06-20 08:00:00", "power_restore_time": "2026-06-20 09:00:00", "actual_restoration_minutes": "60", "mapping_status": "no_mapped_meter", "truth_quality": "MISSING_MAPPING", "alarm_type": "AC MAIN FAIL-C1"},
                    {"location_id": "123456", "sitecode": "OKSITE", "outage_start_time": "2026-06-19 08:00:00", "power_restore_time": "2026-06-19 08:30:00", "actual_restoration_minutes": "30", "mapping_status": "matched_single_peano", "truth_quality": "OK", "alarm_type": "AC MAIN FAIL-C1"},
                ],
            )
            _write_csv(candidates, ["site_id"], [])
            _write_csv(rejects, ["site_id"], [])

            result = build_mapping_repair_queue(audit, candidates, rejects, root / "public.csv", root / "repair.md", private_output_csv=root / "private.csv")
            public_text = (root / "public.csv").read_text(encoding="utf-8-sig")
            private_text = (root / "private.csv").read_text(encoding="utf-8-sig")

            self.assertEqual(result["repair_groups"], 1)
            self.assertIn("site-", public_text)
            self.assertNotIn("870237", public_text)
            self.assertNotIn("NTWPC", public_text)
            self.assertIn("870237", private_text)
            self.assertIn("Mapping Repair Queue", (root / "repair.md").read_text(encoding="utf-8-sig"))

    def test_duplicate_flapping_audit_flags_duplicates_and_close_fail_clear_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "candidate.csv"
            review = root / "review.csv"
            cols = ["site_id", "outage_start_time", "power_restore_time", "actual_restoration_minutes"]
            _write_csv(
                candidates,
                cols,
                [
                    {"site_id": "site-a", "outage_start_time": "2026-06-19 08:00:00", "power_restore_time": "2026-06-19 08:20:00", "actual_restoration_minutes": "20"},
                    {"site_id": "site-a", "outage_start_time": "2026-06-19 08:00:00", "power_restore_time": "2026-06-19 08:20:00", "actual_restoration_minutes": "20"},
                    {"site_id": "site-a", "outage_start_time": "2026-06-19 08:24:00", "power_restore_time": "2026-06-19 08:40:00", "actual_restoration_minutes": "16"},
                ],
            )
            _write_csv(review, cols, [{"site_id": "site-b", "outage_start_time": "2026-06-19 08:00:00", "power_restore_time": "2026-06-19 08:03:00", "actual_restoration_minutes": "3"}])

            result = build_duplicate_flapping_audit(candidates, review, root / "flap.csv", root / "flap.md")
            rows = _read_csv(root / "flap.csv")

            self.assertEqual(result["sites_with_findings"], 1)
            self.assertEqual(rows[0]["duplicate_exact_rows"], "2")
            self.assertEqual(rows[0]["flapping_pairs"], "1")
            self.assertIn("Phase 1 still keeps one alarm row", (root / "flap.md").read_text(encoding="utf-8-sig"))

    def test_growth_plan_uses_existing_queues_without_relaxing_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            eligibility = root / "eligibility.csv"
            gate = root / "gate.csv"
            monitor = root / "monitor.csv"
            mapping = root / "mapping.csv"
            context = root / "context.csv"
            _write_csv(
                eligibility,
                ["event_ref", "eligibility_status", "source_lane", "prediction_interval_width", "selected_q90", "blocker_reasons", "webex_device_interruption_class"],
                [
                    {"event_ref": "g1", "eligibility_status": "green_auto_candidate", "source_lane": "ais_truth_matched", "prediction_interval_width": "80", "selected_q90": "120", "blocker_reasons": "", "webex_device_interruption_class": "sustained_candidate"},
                    {"event_ref": "a1", "eligibility_status": "amber_human_review", "source_lane": "ais_truth_matched", "prediction_interval_width": "100", "selected_q90": "160", "blocker_reasons": "momentary_webex_requires_review", "webex_device_interruption_class": "momentary_le_1m"},
                ],
            )
            _write_csv(gate, ["metric", "value"], [{"metric": "production_gate_status", "value": "blocked_too_few_green_rows"}])
            _write_csv(monitor, ["event_ref", "monitor_priority"], [{"event_ref": "w1", "monitor_priority": "high"}])
            _write_csv(mapping, ["site_ref", "repair_priority", "sustained_rows"], [{"site_ref": "site-x", "repair_priority": "high", "sustained_rows": "7"}])
            _write_csv(context, ["event_ref", "priority_tier"], [{"event_ref": "c1", "priority_tier": "high"}])

            result = build_green_candidate_growth_plan(eligibility, gate, monitor, mapping, context, root / "growth.csv", root / "growth.md", min_green_rows=5)
            text = (root / "growth.md").read_text(encoding="utf-8-sig")

            self.assertEqual(result["additional_green_needed"], 4)
            self.assertIn("collect_ais_truth_for_high_priority_webex", text)
            self.assertIn("better evidence, not looser thresholds", text)

    def test_shadow_status_contract_and_one_pager_are_safe_decision_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            eligibility = root / "eligibility.csv"
            payloads = root / "payloads.jsonl"
            gate = root / "gate.csv"
            qa = root / "qa.csv"
            growth = root / "growth.csv"
            _write_csv(
                eligibility,
                ["event_ref", "eligibility_status", "source_lane"],
                [
                    {"event_ref": "g1", "eligibility_status": "green_auto_candidate", "source_lane": "ais_truth_matched"},
                    {"event_ref": "m1", "eligibility_status": "monitor_only", "source_lane": "webex_trigger_no_ais_truth"},
                ],
            )
            payloads.write_text(
                '{"mode":"shadow","message_type":"status_only","event_ref":"m1","status":"MONITORING_ONLY","source_lane":"webex_trigger_no_ais_truth","outage_device":{"id":"PFA01","feeder":"PFA01"},"affected_summary":{"affected_count":2,"match_level":"recloser"}}\n',
                encoding="utf-8",
            )
            _write_csv(
                gate,
                ["metric", "value"],
                [
                    {"metric": "production_gate_status", "value": "blocked_too_few_green_rows"},
                    {"metric": "green_q50_mae_minutes", "value": "11.59"},
                    {"metric": "green_q10_q90_coverage", "value": "0.667"},
                    {"metric": "additional_green_rows_needed", "value": "27"},
                ],
            )
            _write_csv(qa, ["check", "rows"], [{"check": "usable_sustained_ok_rows", "rows": "10"}, {"check": "missing_meter_mapping_rows", "rows": "3"}, {"check": "duplicate_interval_rows", "rows": "2"}])
            _write_csv(growth, ["growth_lane", "current_rows", "potential_rows", "priority", "owner", "next_action"], [{"growth_lane": "collect_ais_truth_for_high_priority_webex", "current_rows": "1", "potential_rows": "1", "priority": "high", "owner": "AIS", "next_action": "collect truth"}])

            contract = build_shadow_status_payload_contract(payloads, eligibility, root / "contract.md")
            one_pager = build_executive_one_pager(eligibility, gate, qa, growth, root / "one_pager.md")
            contract_text = (root / "contract.md").read_text(encoding="utf-8-sig")
            one_pager_text = (root / "one_pager.md").read_text(encoding="utf-8-sig")

            self.assertEqual(contract["payload_rows"], 1)
            self.assertEqual(one_pager["green"], 1)
            self.assertIn("Status-only messages intentionally omit", contract_text)
            self.assertIn("Production ETR send remains", one_pager_text)
            self.assertNotIn("PEANO", contract_text + one_pager_text)

    def test_mapping_repair_request_pack_splits_public_and_private_owner_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public_queue = root / "mapping.csv"
            private_queue = root / "mapping_private.csv"
            _write_csv(
                public_queue,
                [
                    "site_ref",
                    "mapping_status",
                    "truth_quality",
                    "rows",
                    "sustained_rows",
                    "total_sustained_minutes",
                    "repair_priority",
                ],
                [
                    {"site_ref": "site-a", "mapping_status": "no_mapped_meter", "truth_quality": "MISSING_MAPPING", "rows": "10", "sustained_rows": "9", "total_sustained_minutes": "900", "repair_priority": "critical"},
                    {"site_ref": "site-b", "mapping_status": "matched_single_meter", "truth_quality": "OK", "rows": "2", "sustained_rows": "2", "total_sustained_minutes": "80", "repair_priority": "low"},
                ],
            )
            _write_csv(
                private_queue,
                ["site_ref", "location_id", "sitecode", "mapping_status", "truth_quality", "rows", "sustained_rows", "total_sustained_minutes", "repair_priority"],
                [{"site_ref": "site-a", "location_id": "870237", "sitecode": "NTWPC", "mapping_status": "no_mapped_meter", "truth_quality": "MISSING_MAPPING", "rows": "10", "sustained_rows": "9", "total_sustained_minutes": "900", "repair_priority": "critical"}],
            )

            result = build_mapping_repair_request_pack(public_queue, private_queue, root / "request.csv", root / "private_request.csv", root / "request.md")
            public_text = (root / "request.csv").read_text(encoding="utf-8-sig")
            private_text = (root / "private_request.csv").read_text(encoding="utf-8-sig")

            self.assertEqual(result["selected_rows"], 1)
            self.assertNotIn("870237", public_text)
            self.assertNotIn("NTWPC", public_text)
            self.assertIn("870237", private_text)
            self.assertIn("Mapping Repair Request Pack", (root / "request.md").read_text(encoding="utf-8-sig"))

    def test_webex_truth_request_pack_is_monitor_only_until_ais_truth_arrives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            monitor = root / "monitor.csv"
            _write_csv(
                monitor,
                [
                    "event_ref",
                    "event_time",
                    "district",
                    "feeder",
                    "device_id",
                    "match_level",
                    "affected_count",
                    "webex_device_interruption_class",
                    "selected_q90",
                    "monitor_priority",
                ],
                [
                    {"event_ref": "msg-1", "event_time": "2026-06-19T08:00:00", "district": "พังโคน", "feeder": "PFA01", "device_id": "PFA01VB-01", "match_level": "cb", "affected_count": "6", "webex_device_interruption_class": "sustained_candidate", "selected_q90": "180", "monitor_priority": "high"}
                ],
            )

            result = build_webex_truth_request_pack(monitor, root / "truth_request.csv", root / "truth_request.md")
            text = (root / "truth_request.md").read_text(encoding="utf-8-sig")

            self.assertEqual(result["selected_rows"], 1)
            self.assertIn("Do not use WebEx-only rows for MAE", text)
            self.assertNotIn("room_id", text)
            self.assertNotIn("token", text.lower())

    def test_flapping_policy_and_owner_handoff_keep_phase1_conservative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = root / "flapping.csv"
            _write_csv(
                audit,
                ["site_ref", "rows", "sustained_rows", "review_short_rows", "duplicate_exact_rows", "flapping_pairs", "review_priority"],
                [{"site_ref": "site-a", "rows": "100", "sustained_rows": "60", "review_short_rows": "40", "duplicate_exact_rows": "20", "flapping_pairs": "30", "review_priority": "high"}],
            )
            result = build_flapping_policy_draft(audit, root / "policy.csv", root / "policy.md", phase2_windows=[5, 15, 30])
            for name in ("executive.md", "growth.md", "mapping.md", "webex.md"):
                (root / name).write_text(f"# {name}\n", encoding="utf-8-sig")
            handoff = build_owner_handoff_pack(root / "executive.md", root / "growth.md", root / "mapping.md", root / "webex.md", root / "policy.md", root / "handoff.md")
            policy_text = (root / "policy.md").read_text(encoding="utf-8-sig")
            handoff_text = (root / "handoff.md").read_text(encoding="utf-8-sig")

            self.assertEqual(result["flapping_pairs"], 30)
            self.assertEqual(handoff["ready_sources"], 5)
            self.assertIn("No automatic merge in Phase 1", policy_text)
            self.assertIn("No production AIS send", handoff_text)

    def test_owner_message_drafts_and_tracker_are_owner_workflow_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("handoff.md", "mapping.md", "webex.md", "policy.md"):
                (root / name).write_text(f"# {name}\n", encoding="utf-8-sig")
            _write_csv(
                root / "mapping_request.csv",
                ["priority_rank", "site_ref", "repair_priority", "requested_owner_action", "acceptance_criteria"],
                [
                    {
                        "priority_rank": "1",
                        "site_ref": "site-a",
                        "repair_priority": "critical",
                        "requested_owner_action": "confirm one mapped site",
                        "acceptance_criteria": "single approved mapping",
                    }
                ],
            )
            _write_csv(
                root / "webex_request.csv",
                ["priority_rank", "event_ref", "request_priority", "acceptance_criteria"],
                [{"priority_rank": "1", "event_ref": "evt-a", "request_priority": "high", "acceptance_criteria": "AIS restore timestamp"}],
            )
            _write_csv(
                root / "policy.csv",
                ["policy_topic", "owner_decision_needed"],
                [{"policy_topic": "phase1_no_auto_merge", "owner_decision_needed": "approve policy"}],
            )

            draft = build_owner_message_drafts(root / "handoff.md", root / "mapping.md", root / "webex.md", root / "policy.md", root / "drafts.md")
            tracker = build_owner_followup_tracker(root / "mapping_request.csv", root / "webex_request.csv", root / "policy.csv", root / "tracker.csv", root / "tracker.md")
            draft_text = (root / "drafts.md").read_text(encoding="utf-8-sig")
            tracker_text = (root / "tracker.md").read_text(encoding="utf-8-sig")

            self.assertEqual(draft["ready_sources"], 4)
            self.assertEqual(tracker["rows"], 3)
            self.assertIn("credentials", draft_text)
            self.assertNotIn("token", draft_text.lower())
            self.assertNotIn("room_id", draft_text)
            self.assertIn("follow-up tasks only", tracker_text)

    def test_owner_response_templates_and_validator_keep_short_truth_out_of_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_csv(
                root / "mapping_request.csv",
                ["site_ref"],
                [{"site_ref": "site-a"}],
            )
            _write_csv(
                root / "webex_request.csv",
                ["event_ref", "device_id", "feeder"],
                [{"event_ref": "evt-sustained", "device_id": "PFA01VB-01", "feeder": "PFA01"}],
            )

            templates = build_owner_response_templates(
                root / "mapping_request.csv",
                root / "webex_request.csv",
                root / "mapping_template.csv",
                root / "webex_template.csv",
                root / "templates.md",
            )
            _write_csv(
                root / "mapping_response.csv",
                [
                    "response_type",
                    "source_ref",
                    "owner_decision",
                    "mapped_site_id",
                    "mapped_site_code",
                    "outage_start_time",
                    "power_restore_time",
                    "device_id",
                    "feeder",
                    "owner_notes",
                    "reviewed_by",
                    "reviewed_at",
                ],
                [
                    {
                        "response_type": "mapping_repair",
                        "source_ref": "site-a",
                        "owner_decision": "approved",
                        "mapped_site_id": "site-approved",
                        "reviewed_by": "owner",
                        "reviewed_at": "2026-06-19",
                    }
                ],
            )
            _write_csv(
                root / "webex_response.csv",
                [
                    "response_type",
                    "source_ref",
                    "owner_decision",
                    "mapped_site_id",
                    "mapped_site_code",
                    "outage_start_time",
                    "power_restore_time",
                    "device_id",
                    "feeder",
                    "owner_notes",
                    "reviewed_by",
                    "reviewed_at",
                ],
                [
                    {
                        "response_type": "webex_truth",
                        "source_ref": "evt-sustained",
                        "owner_decision": "approved",
                        "outage_start_time": "2026-06-19T08:00:00",
                        "power_restore_time": "2026-06-19T08:30:00",
                        "reviewed_by": "owner",
                        "reviewed_at": "2026-06-19",
                    },
                    {
                        "response_type": "webex_truth",
                        "source_ref": "evt-short",
                        "owner_decision": "approved",
                        "outage_start_time": "2026-06-19T09:00:00",
                        "power_restore_time": "2026-06-19T09:03:00",
                        "reviewed_by": "owner",
                        "reviewed_at": "2026-06-19",
                    },
                ],
            )

            validation = validate_owner_response_files(root / "mapping_response.csv", root / "webex_response.csv", root / "validation.csv", root / "validation.md")
            statuses = {row["source_ref"]: row["validation_status"] for row in _read_csv(root / "validation.csv")}

            self.assertEqual(templates["mapping_template_rows"], 1)
            self.assertEqual(templates["webex_template_rows"], 1)
            self.assertEqual(validation["rows"], 3)
            self.assertEqual(statuses["site-a"], "ready_for_review")
            self.assertEqual(statuses["evt-sustained"], "ready_for_import")
            self.assertEqual(statuses["evt-short"], "review_only")
            self.assertIn("sustained >5 minutes", (root / "validation.md").read_text(encoding="utf-8-sig"))

    def test_simple_ais_mapping_response_validation_only_stages_confirmed_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_csv(
                root / "mapping_response.csv",
                [
                    "site_ref",
                    "location_id",
                    "sitecode",
                    "ais_answer",
                    "confirmed_peano_or_meter_id",
                    "confirmed_site_code_if_different",
                    "notes",
                    "reviewed_by",
                    "reviewed_at",
                ],
                [
                    {
                        "site_ref": "site-confirmed",
                        "location_id": "445243",
                        "sitecode": "BRKOM",
                        "ais_answer": "confirmed",
                        "confirmed_peano_or_meter_id": "meter-ok",
                        "reviewed_by": "owner",
                        "reviewed_at": "2026-06-19",
                    },
                    {
                        "site_ref": "site-not-found",
                        "location_id": "808871",
                        "sitecode": "ARSMT",
                        "ais_answer": "not_found",
                        "notes": "not active",
                        "reviewed_by": "owner",
                        "reviewed_at": "2026-06-19",
                    },
                    {
                        "site_ref": "site-uncertain",
                        "location_id": "883898",
                        "sitecode": "ONDMD",
                        "ais_answer": "uncertain",
                        "notes": "duplicate",
                        "reviewed_by": "owner",
                        "reviewed_at": "2026-06-19",
                    },
                    {
                        "site_ref": "site-blank",
                        "location_id": "881834",
                        "sitecode": "NSPSW",
                    },
                ],
            )
            _write_csv(root / "webex_response.csv", ["response_type", "source_ref"], [])

            validation = validate_owner_response_files(root / "mapping_response.csv", root / "webex_response.csv", root / "validation.csv", root / "validation.md")
            statuses = {row["source_ref"]: row["validation_status"] for row in _read_csv(root / "validation.csv")}

            self.assertEqual(validation["rows"], 3)
            self.assertEqual(statuses["site-confirmed"], "ready_for_review")
            self.assertEqual(statuses["site-not-found"], "review_only")
            self.assertEqual(statuses["site-uncertain"], "review")
            self.assertNotIn("site-blank", statuses)

    def test_owner_response_intake_and_dry_run_stage_only_validated_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_csv(
                root / "validation.csv",
                ["response_type", "source_ref", "validation_status", "issue", "recommended_action"],
                [
                    {"response_type": "mapping_repair", "source_ref": "site-a", "validation_status": "ready_for_review", "issue": "ok", "recommended_action": "review privately"},
                    {"response_type": "webex_truth", "source_ref": "evt-a", "validation_status": "ready_for_import", "issue": "ok", "recommended_action": "import"},
                    {"response_type": "webex_truth", "source_ref": "evt-short", "validation_status": "review_only", "issue": "short", "recommended_action": "keep out"},
                    {"response_type": "webex_truth", "source_ref": "evt-bad", "validation_status": "reject", "issue": "bad", "recommended_action": "fix"},
                ],
            )
            _write_csv(
                root / "eligibility.csv",
                ["event_ref", "eligibility_status", "source_lane"],
                [{"event_ref": "g1", "eligibility_status": "green_auto_candidate", "source_lane": "ais_truth_matched"}],
            )
            _write_csv(
                root / "gate.csv",
                ["metric", "value"],
                [
                    {"metric": "green_rows", "value": "3"},
                    {"metric": "additional_green_rows_needed", "value": "27"},
                    {"metric": "production_gate_status", "value": "blocked_too_few_green_rows"},
                ],
            )

            intake = build_owner_response_intake(root / "validation.csv", root / "intake.csv", root / "intake.md")
            dry_run = build_owner_response_dry_run_impact(root / "eligibility.csv", root / "gate.csv", root / "intake.csv", root / "dry.csv", root / "dry.md", min_green_rows=5)
            intake_rows = _read_csv(root / "intake.csv")
            dry_rows = _read_csv(root / "dry.csv")

            self.assertEqual(intake["stage_truth_rows"], 1)
            self.assertEqual(intake["stage_mapping_rows"], 1)
            self.assertEqual(intake["reject_rows"], 1)
            self.assertIn("stage_ais_truth_import", {row["intake_lane"] for row in intake_rows})
            self.assertEqual(dry_run["ready_truth_rows"], 1)
            self.assertEqual(dry_rows[-1]["optimistic_green_rows"], "5")
            self.assertIn("planning estimate", (root / "dry.md").read_text(encoding="utf-8-sig"))

    def test_response_examples_daily_delta_and_pitch_pack_are_safe_public_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            examples = build_owner_response_examples(root / "examples", root / "examples.md")
            _write_csv(
                root / "history.csv",
                ["run_at", "green_auto_candidate", "amber_human_review", "red_blocked", "monitor_only", "green_q50_mae_minutes", "green_q10_q90_coverage", "production_gate_status"],
                [
                    {"run_at": "2026-06-19T08:00:00", "green_auto_candidate": "2", "amber_human_review": "5", "red_blocked": "9", "monitor_only": "10", "green_q50_mae_minutes": "12", "green_q10_q90_coverage": "0.6", "production_gate_status": "blocked_too_few_green_rows"},
                    {"run_at": "2026-06-19T09:00:00", "green_auto_candidate": "3", "amber_human_review": "4", "red_blocked": "9", "monitor_only": "11", "green_q50_mae_minutes": "11.5", "green_q10_q90_coverage": "0.667", "production_gate_status": "blocked_too_few_green_rows"},
                ],
            )
            _write_csv(root / "gate.csv", ["metric", "value"], [{"metric": "production_gate_status", "value": "blocked_too_few_green_rows"}])
            _write_csv(root / "tracker.csv", ["workstream", "current_status"], [{"workstream": "mapping_repair", "current_status": "waiting_owner_response"}])
            _write_csv(root / "validation.csv", ["response_type", "source_ref", "validation_status"], [{"response_type": "all", "source_ref": "", "validation_status": "waiting_for_owner_response"}])
            _write_csv(
                root / "dry.csv",
                [
                    "scenario",
                    "current_green_rows",
                    "ready_mapping_rows",
                    "ready_truth_rows",
                    "optimistic_green_rows",
                    "additional_green_rows_needed",
                    "gate_status",
                    "decision_note",
                ],
                [{"scenario": "current_baseline", "current_green_rows": "3", "ready_mapping_rows": "0", "ready_truth_rows": "0", "optimistic_green_rows": "3", "additional_green_rows_needed": "27", "gate_status": "blocked_too_few_green_rows", "decision_note": "baseline"}],
            )
            for name in ("one_pager.md", "delta.md", "handoff.md"):
                (root / name).write_text(f"# {name}\n", encoding="utf-8-sig")

            delta = build_daily_executive_delta(root / "history.csv", root / "gate.csv", root / "tracker.csv", root / "validation.csv", root / "delta.csv", root / "delta.md")
            pitch = build_executive_pitch_pack(root / "one_pager.md", root / "delta.md", root / "handoff.md", root / "tracker.csv", root / "validation.csv", root / "dry.csv", root / "pitch_pack.md")
            combined = (root / "examples.md").read_text(encoding="utf-8-sig") + (root / "delta.md").read_text(encoding="utf-8-sig") + (root / "pitch_pack.md").read_text(encoding="utf-8-sig")

            self.assertEqual(examples["example_rows"], 6)
            self.assertTrue(delta["has_previous"])
            self.assertEqual(pitch["current_green_rows"], "3")
            self.assertIn("AIS outage/restore only", combined)
            self.assertNotIn("PEANO", combined)
            self.assertNotIn("room_id", combined)

    def test_current_capability_development_plan_reflects_runtime_gate_and_guardrails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_csv(
                root / "gate.csv",
                ["metric", "value", "status", "note"],
                [
                    {"metric": "ais_truth_metric_rows", "value": "79", "status": "info", "note": ""},
                    {"metric": "green_rows", "value": "3", "status": "blocked", "note": ""},
                    {"metric": "additional_green_rows_needed", "value": "27", "status": "blocked", "note": ""},
                    {"metric": "green_q50_mae_minutes", "value": "11.59", "status": "pass", "note": ""},
                    {"metric": "green_q10_q90_coverage", "value": "0.667", "status": "blocked", "note": ""},
                    {"metric": "production_gate_status", "value": "blocked_too_few_green_rows", "status": "blocked", "note": ""},
                ],
            )
            _write_csv(
                root / "steps.csv",
                ["step", "status", "detail"],
                [
                    {"step": "daily", "status": "ok", "detail": ""},
                    {"step": "ais_truth_import", "status": "skipped", "detail": "no pending file"},
                ],
            )
            _write_csv(
                root / "tracker.csv",
                ["workstream", "current_status"],
                [
                    {"workstream": "mapping_repair", "current_status": "waiting_owner_response"},
                    {"workstream": "webex_truth_request", "current_status": "waiting_owner_response"},
                    {"workstream": "flapping_policy", "current_status": "waiting_owner_decision"},
                ],
            )
            _write_csv(root / "intake.csv", ["intake_lane"], [{"intake_lane": "waiting"}])
            _write_csv(
                root / "dry.csv",
                [
                    "scenario",
                    "current_green_rows",
                    "ready_mapping_rows",
                    "ready_truth_rows",
                    "optimistic_green_rows",
                    "additional_green_rows_needed",
                    "gate_status",
                    "decision_note",
                ],
                [
                    {"scenario": "current_baseline", "current_green_rows": "3", "ready_mapping_rows": "0", "ready_truth_rows": "0", "optimistic_green_rows": "3", "additional_green_rows_needed": "27", "gate_status": "blocked_too_few_green_rows", "decision_note": ""},
                    {"scenario": "mapping_plus_truth_upper_bound", "current_green_rows": "3", "ready_mapping_rows": "0", "ready_truth_rows": "0", "optimistic_green_rows": "3", "additional_green_rows_needed": "27", "gate_status": "blocked_too_few_green_rows", "decision_note": ""},
                ],
            )

            result = build_current_capability_development_plan(root / "gate.csv", root / "steps.csv", root / "tracker.csv", root / "intake.csv", root / "dry.csv", root / "capability.csv", root / "capability.md")
            rows = _read_csv(root / "capability.csv")
            text = (root / "capability.md").read_text(encoding="utf-8-sig")

            self.assertEqual(result["green_rows"], 3)
            self.assertEqual(result["additional_green_rows_needed"], 27)
            self.assertTrue(any(row["section"] == "cannot_do" and row["item"] == "Send automatic production AIS ETR" for row in rows))
            self.assertIn("Current Capability & Development Plan", text)
            self.assertIn("Close the owner response loop first", text)
            self.assertNotIn("PEANO", text)
            self.assertNotIn("room_id", text)
            self.assertNotIn("token", text.lower())

    def test_current_capability_development_plan_includes_ais_updated_context_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_csv(
                root / "gate.csv",
                ["metric", "value", "status", "note"],
                [
                    {"metric": "ais_truth_metric_rows", "value": "79", "status": "info", "note": ""},
                    {"metric": "green_rows", "value": "0", "status": "blocked", "note": ""},
                    {"metric": "additional_green_rows_needed", "value": "30", "status": "blocked", "note": ""},
                    {"metric": "green_q50_mae_minutes", "value": "", "status": "blocked", "note": ""},
                    {"metric": "green_q10_q90_coverage", "value": "", "status": "blocked", "note": ""},
                    {"metric": "production_gate_status", "value": "blocked_too_few_green_rows", "status": "blocked", "note": ""},
                ],
            )
            _write_csv(root / "steps.csv", ["step", "status", "detail"], [{"step": "daily", "status": "ok", "detail": ""}])
            _write_csv(root / "tracker.csv", ["workstream", "current_status"], [])
            _write_csv(root / "intake.csv", ["intake_lane"], [{"intake_lane": "waiting"}])
            _write_csv(
                root / "dry.csv",
                ["scenario", "additional_green_rows_needed"],
                [{"scenario": "current_baseline", "additional_green_rows_needed": "30"}],
            )
            _write_csv(
                root / "updated.csv",
                ["section", "key", "value"],
                [
                    {"section": "summary", "key": "rows", "value": "736"},
                    {"section": "summary", "key": "ok_rows", "value": "457"},
                    {"section": "summary", "key": "reject_rows", "value": "279"},
                    {"section": "summary", "key": "webex_matched_rows", "value": "4"},
                    {"section": "summary", "key": "webex_no_match_rows", "value": "496"},
                    {"section": "cause_all", "key": "pea_no_backup", "value": "165"},
                    {"section": "cause_all", "key": "pea_have_backup", "value": "555"},
                    {"section": "cause_all", "key": "pea_activity", "value": "16"},
                    {"section": "top_unmapped_sitecode", "key": "BRKOM", "value": "8"},
                ],
            )
            _write_csv(
                root / "mapping_request.csv",
                ["priority_rank", "site_ref", "repair_priority", "sustained_rows"],
                [
                    {"priority_rank": "1", "site_ref": "site-a", "repair_priority": "high", "sustained_rows": "8"},
                    {"priority_rank": "2", "site_ref": "site-b", "repair_priority": "high", "sustained_rows": "5"},
                ],
            )

            result = build_current_capability_development_plan(
                root / "gate.csv",
                root / "steps.csv",
                root / "tracker.csv",
                root / "intake.csv",
                root / "dry.csv",
                root / "capability.csv",
                root / "capability.md",
                root / "updated.csv",
                root / "mapping_request.csv",
                root / "mapping_response_template.csv",
                root / "private_lookup.csv",
                root / "owner_message.md",
            )
            rows = _read_csv(root / "capability.csv")
            text = (root / "capability.md").read_text(encoding="utf-8-sig")

            self.assertTrue(result["ais_updated_available"])
            self.assertTrue(result["ais_updated_mapping_request_available"])
            self.assertEqual(result["ais_updated_mapping_request_rows"], 2)
            self.assertEqual(result["ais_updated_mapping_request_potential_rows"], 13)
            self.assertIn("AIS Updated File Analysis", text)
            self.assertIn("AIS Mapping Response Loop", text)
            self.assertIn("analysis/history context only", text)
            self.assertIn("waiting for AIS owner response", text)
            self.assertTrue(any(row["item"] == "Promote AIS updated file directly to production gate" and row["status"] == "blocked" for row in rows))
            self.assertNotIn("PEANO", text)
            self.assertNotIn("room_id", text)
            self.assertNotIn("Y2lzY29zcGFyaz", text)

    def test_flapping_sensitivity_and_pitch_script_do_not_apply_model_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_csv(
                root / "flapping.csv",
                ["site_ref", "review_priority", "flapping_pairs"],
                [
                    {"site_ref": "site-a", "review_priority": "high", "flapping_pairs": "7"},
                    {"site_ref": "site-b", "review_priority": "low", "flapping_pairs": "2"},
                ],
            )
            (root / "one_pager.md").write_text("# one pager\n", encoding="utf-8-sig")
            (root / "handoff.md").write_text("# handoff\n", encoding="utf-8-sig")

            sensitivity = build_flapping_sensitivity_plan(root / "flapping.csv", root / "sensitivity.csv", root / "sensitivity.md", windows=[0, 5, 15])
            pitch = build_pitching_narrative_script(root / "one_pager.md", root / "handoff.md", root / "pitch.md")
            scenarios = [row["scenario"] for row in _read_csv(root / "sensitivity.csv")]
            sensitivity_text = (root / "sensitivity.md").read_text(encoding="utf-8-sig")
            pitch_text = (root / "pitch.md").read_text(encoding="utf-8-sig")

            self.assertEqual(sensitivity["high_priority_sites"], 1)
            self.assertEqual(sensitivity["flapping_pairs"], 9)
            self.assertEqual(pitch["executive_one_pager_exists"], True)
            self.assertEqual(scenarios, ["no_merge_baseline", "merge_within_5m", "merge_within_15m"])
            self.assertIn("No merge is applied", sensitivity_text)
            self.assertIn("production ยัง blocked", pitch_text)


def _eligibility_row(ref, status, lane, feeder, actual, p50, q10, q90, width, error, covered, webex_state):
    return {
        "event_ref": ref,
        "event_time": "2026-06-19T08:00:00",
        "district": "พังโคน",
        "feeder": feeder,
        "device_id": f"{feeder}VR-104",
        "source_lane": lane,
        "match_level": "recloser" if lane == "ais_truth_matched" else "",
        "match_confidence": "0.9" if lane == "ais_truth_matched" else "0",
        "affected_count": "9" if lane == "ais_truth_matched" else "0",
        "active_ais_outage_confirmed": "TRUE" if lane == "ais_truth_matched" else "FALSE",
        "webex_device_interruption_class": webex_state,
        "actual_restoration_minutes": actual,
        "selected_p50": p50,
        "selected_q10": q10,
        "selected_q90": q90,
        "prediction_interval_width": width,
        "selected_absolute_error": error,
        "selected_covered_q10_q90": covered,
        "eligibility_status": status,
        "stage1_class": "normal" if status == "green_auto_candidate" else "uncertain",
        "blocker_reasons": "" if status == "green_auto_candidate" else "wide_prediction_interval",
    }


def _read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path, columns, rows):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})
