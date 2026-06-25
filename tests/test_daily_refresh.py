import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.daily_refresh import (
    build_approved_context_candidate_summary,
    build_context_conflict_deep_dive,
    build_daily_intake_workflow,
    build_daily_inbox_status,
    build_daily_shadow_diff,
    build_evidence_review_reports,
    build_executive_status_pack,
    build_operator_shadow_review_checklist,
    discover_daily_ais_source,
    run_synthetic_daily_file_smoke_test,
)


class DailyRefreshTests(unittest.TestCase):
    def test_daily_intake_workflow_creates_safe_readme_and_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "daily"
            result = build_daily_intake_workflow(root)
            readme = Path(result["readme_output"])

            self.assertTrue((root / "inbox").exists())
            self.assertTrue((root / "processed").exists())
            self.assertTrue((root / "rejected").exists())
            self.assertIn("AIS outage/restore", readme.read_text(encoding="utf-8-sig"))
            self.assertIn("PowerBI/SFSD/ReportPO", readme.read_text(encoding="utf-8-sig"))

    def test_daily_inbox_status_detects_pending_and_processed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "daily"
            build_daily_intake_workflow(root)
            source = root / "inbox" / "AIS_AC_MAIN_FAIL_2026-06-19.xlsx"
            source.write_text("placeholder", encoding="utf-8")
            status_csv = root / "inbox_status.csv"
            manifest = root / "source_manifest.csv"

            first = build_daily_inbox_status(root, status_csv, manifest)
            first_rows = _read_csv(status_csv)

            self.assertEqual(first["pending_files"], 1)
            self.assertEqual(first["next_pending_source"], str(source))
            self.assertEqual(first_rows[0]["status"], "pending")

            _write_csv(
                manifest,
                [
                    "file_name",
                    "file_path",
                    "file_size_bytes",
                    "modified_at",
                    "fingerprint",
                    "status",
                    "processed_at",
                    "source_format",
                    "notes",
                ],
                [
                    {
                        **first_rows[0],
                        "status": "processed",
                        "processed_at": "2026-06-19T08:30:00",
                        "notes": "test import",
                    }
                ],
            )
            second = discover_daily_ais_source(root, manifest, status_csv)

            self.assertEqual(second["pending_files"], 0)
            self.assertIsNone(second["selected_source"])
            self.assertEqual(second["discovery_status"], "no_pending_file")

    def test_evidence_review_reports_split_candidates_and_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence.csv"
            approved = root / "approved.csv"
            conflicts = root / "conflicts.csv"
            approved_md = root / "approved.md"
            conflicts_md = root / "conflicts.md"
            _write_csv(
                evidence,
                [
                    "event_ref",
                    "event_time",
                    "feeder",
                    "device_id",
                    "evidence_status",
                    "evidence_score",
                    "context_sources",
                    "cause_group",
                    "work_type",
                    "weather_or_lightning",
                    "sfsd_match_status",
                    "sfsd_match_level",
                    "sfsd_evidence_quality",
                    "sfsd_cause_status",
                    "evidence_reasons",
                ],
                [
                    _evidence_row("msg-aaa", "SEK06", "approved_candidate", "sfsd"),
                    _evidence_row("msg-bbb", "PFA02", "rejected_conflict", "sfsd;reportpo_feature"),
                    _evidence_row("msg-ccc", "PFA09", "pending_insufficient_evidence", "reportpo_feature"),
                ],
            )

            result = build_evidence_review_reports(evidence, approved, conflicts, approved_md, conflicts_md)
            approved_rows = _read_csv(approved)
            conflict_rows = _read_csv(conflicts)

            self.assertEqual(result["approved_rows"], 1)
            self.assertEqual(result["conflict_rows"], 1)
            self.assertEqual(approved_rows[0]["review_decision"], "pending_owner_review")
            self.assertEqual(conflict_rows[0]["review_decision"], "blocked_until_resolved")
            self.assertIn("Approved Context Candidate Review", approved_md.read_text(encoding="utf-8-sig"))
            self.assertIn("Rejected Context Conflicts", conflicts_md.read_text(encoding="utf-8-sig"))

    def test_context_conflict_and_approved_summaries_render_safe_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence.csv"
            conflict_csv = root / "conflict.csv"
            conflict_md = root / "conflict.md"
            approved_csv = root / "approved.csv"
            approved_md = root / "approved.md"
            _write_csv(
                evidence,
                [
                    "event_ref",
                    "event_time",
                    "feeder",
                    "device_id",
                    "actual_restoration_minutes",
                    "selected_p50",
                    "selected_q10",
                    "selected_q90",
                    "selected_absolute_error",
                    "evidence_status",
                    "evidence_score",
                    "context_sources",
                    "cause_group",
                    "work_type",
                    "weather_or_lightning",
                    "sfsd_match_status",
                    "sfsd_match_level",
                    "sfsd_evidence_quality",
                    "sfsd_cause_status",
                    "reportpo_feature_status",
                    "reportpo_feature_quality",
                    "reportpo_lifecycle_status",
                    "reportpo_lifecycle_quality",
                    "evidence_reasons",
                    "recommended_action",
                ],
                [
                    {
                        **_evidence_row("msg-aaa", "SEK06", "approved_candidate", "sfsd"),
                        "actual_restoration_minutes": "120",
                        "evidence_reasons": "reportpo_feature_proxy_context_only",
                    },
                    {
                        **_evidence_row("msg-bbb", "PFA02", "rejected_conflict", "sfsd;reportpo_feature"),
                        "actual_restoration_minutes": "240",
                        "evidence_reasons": "pea_momentary_ais_sustained_conflict",
                    },
                ],
            )

            conflict = build_context_conflict_deep_dive(evidence, conflict_md, conflict_csv)
            approved = build_approved_context_candidate_summary(evidence, approved_md, approved_csv)

            self.assertEqual(conflict["rows"], 1)
            self.assertEqual(approved["rows"], 1)
            self.assertIn("Context Conflict Deep Dive", conflict_md.read_text(encoding="utf-8-sig"))
            self.assertIn("Approved Context Candidate Summary", approved_md.read_text(encoding="utf-8-sig"))
            self.assertNotIn("6101234567", conflict_md.read_text(encoding="utf-8-sig"))

    def test_daily_shadow_diff_writes_history_and_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            eligibility = root / "eligibility.csv"
            evidence = root / "evidence.csv"
            inbox = root / "inbox.csv"
            history = root / "history.csv"
            output = root / "diff.md"
            _write_csv(
                eligibility,
                ["event_ref", "source_lane", "eligibility_status", "selected_absolute_error", "selected_covered_q10_q90"],
                [
                    {"event_ref": "msg-1", "source_lane": "ais_truth_matched", "eligibility_status": "green_auto_candidate", "selected_absolute_error": "10", "selected_covered_q10_q90": "TRUE"},
                    {"event_ref": "msg-2", "source_lane": "webex_trigger_no_ais_truth", "eligibility_status": "monitor_only", "selected_absolute_error": "", "selected_covered_q10_q90": ""},
                ],
            )
            _write_csv(
                evidence,
                ["event_ref", "evidence_status"],
                [{"event_ref": "msg-1", "evidence_status": "approved_candidate"}],
            )
            _write_csv(inbox, ["status"], [{"status": "pending"}])

            first = build_daily_shadow_diff(eligibility, evidence, inbox, history, output, run_at="2026-06-19T08:00:00")
            second = build_daily_shadow_diff(eligibility, evidence, inbox, history, output, run_at="2026-06-19T09:00:00")

            self.assertFalse(first["has_previous"])
            self.assertTrue(second["has_previous"])
            self.assertEqual(len(_read_csv(history)), 2)
            self.assertIn("Daily Shadow Diff", output.read_text(encoding="utf-8-sig"))

    def test_synthetic_daily_file_smoke_test_marks_manifest_processed(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_synthetic_daily_file_smoke_test(Path(tmp) / "smoke")

            self.assertTrue(result["passed"])
            self.assertTrue(Path(result["markdown_output"]).exists())
            self.assertEqual(result["second_discovery"]["pending_files"], 0)

    def test_operator_checklist_renders_guardrails(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "checklist.md"
            result = build_operator_shadow_review_checklist(output)

            self.assertEqual(result["output_markdown"], str(output))
            text = output.read_text(encoding="utf-8-sig")
            self.assertIn("AIS outage/restore", text)
            self.assertIn("Production Gate", text)

    def test_executive_status_pack_keeps_production_blocked_when_gate_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            eligibility = root / "eligibility.csv"
            evidence = root / "evidence.csv"
            two_stage = root / "two_stage.csv"
            output = root / "executive.md"
            _write_csv(
                eligibility,
                [
                    "event_ref",
                    "source_lane",
                    "eligibility_status",
                    "selected_absolute_error",
                    "selected_covered_q10_q90",
                ],
                [
                    {"event_ref": "msg-green", "source_lane": "ais_truth_matched", "eligibility_status": "green_auto_candidate", "selected_absolute_error": "22", "selected_covered_q10_q90": "TRUE"},
                    {"event_ref": "msg-red", "source_lane": "pea_quarantined", "eligibility_status": "red_blocked", "selected_absolute_error": "", "selected_covered_q10_q90": ""},
                    {"event_ref": "msg-webex", "source_lane": "webex_trigger_no_ais_truth", "eligibility_status": "monitor_only", "selected_absolute_error": "", "selected_covered_q10_q90": ""},
                ],
            )
            _write_csv(
                evidence,
                ["event_ref", "evidence_status"],
                [
                    {"event_ref": "msg-green", "evidence_status": "approved_candidate"},
                    {"event_ref": "msg-red", "evidence_status": "blocked_no_customer_send"},
                ],
            )
            _write_csv(
                two_stage,
                ["event_ref", "public_send_allowed"],
                [{"event_ref": "msg-green", "public_send_allowed": "TRUE"}],
            )

            result = build_executive_status_pack(eligibility, evidence, two_stage, output)

            self.assertEqual(result["production_gate_status"], "blocked_metric_gate_failed")
            self.assertEqual(result["approved_context_candidate_rows"], 1)
            text = output.read_text(encoding="utf-8-sig")
            self.assertIn("AIS outage/restore only", text)
            self.assertIn("blocked_metric_gate_failed", text)
            self.assertNotIn("PEANO", text)


def _evidence_row(ref: str, feeder: str, status: str, sources: str) -> dict[str, str]:
    return {
        "event_ref": ref,
        "event_time": "2026-06-19T08:00:00",
        "feeder": feeder,
        "device_id": feeder + "R-01",
        "evidence_status": status,
        "evidence_score": "90",
        "context_sources": sources,
        "cause_group": "weather",
        "work_type": "repair",
        "weather_or_lightning": "rain",
        "sfsd_match_status": "matched",
        "sfsd_match_level": "event_number",
        "sfsd_evidence_quality": "PEA_SUSTAINED",
        "sfsd_cause_status": "cause_available",
        "evidence_reasons": "test_reason",
    }


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]
