import csv
import hashlib
import tempfile
import unittest
from pathlib import Path

from ais_etr.autonomous_evidence import build_autonomous_evidence_collector


class AutonomousEvidenceTests(unittest.TestCase):
    def test_strong_sfsd_context_creates_pending_autofill_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_id = "webex-raw-secret-id-1"
            event_ref = _redacted_ref(raw_id)
            eligibility = root / "eligibility.csv"
            feature = root / "feature.csv"
            lifecycle = root / "lifecycle.csv"
            sfsd = root / "sfsd.csv"
            output = root / "evidence.csv"
            markdown = root / "evidence.md"
            autofill = root / "autofill.csv"
            _write_eligibility(
                eligibility,
                [
                    _eligibility_row(event_ref, "ais_truth_matched", "amber_human_review", "TRUE", "240"),
                ],
            )
            _write_feature(feature, [_feature_row(raw_id, "no_match", "", "")])
            _write_lifecycle(lifecycle, [])
            _write_sfsd(
                sfsd,
                [
                    _sfsd_row(
                        event_ref,
                        "matched",
                        "event_number",
                        "PEA_SUSTAINED",
                        "cause_available",
                        main_cause="tree_contact",
                        sub_cause="line_repair",
                        weather="rain",
                    )
                ],
            )

            result = build_autonomous_evidence_collector(
                eligibility,
                feature,
                lifecycle,
                sfsd,
                output,
                markdown,
                autofill,
            )
            rows = _read_csv(output)
            autofill_rows = _read_csv(autofill)

            self.assertEqual(result["approved_candidate_rows"], 1)
            self.assertEqual(rows[0]["evidence_status"], "approved_candidate")
            self.assertEqual(rows[0]["cause_group"], "tree_contact")
            self.assertEqual(rows[0]["work_type"], "line_repair")
            self.assertEqual(autofill_rows[0]["review_status"], "pending")
            self.assertEqual(autofill_rows[0]["first_restore_time"], "")
            self.assertIn("PEA context is not restoration truth", autofill_rows[0]["notes"])
            self.assertNotIn(raw_id, output.read_text(encoding="utf-8-sig"))
            self.assertNotIn(raw_id, markdown.read_text(encoding="utf-8-sig"))

    def test_momentary_pea_context_conflicts_with_long_ais_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_ref = "msg-conflict"
            eligibility = root / "eligibility.csv"
            feature = root / "feature.csv"
            lifecycle = root / "lifecycle.csv"
            sfsd = root / "sfsd.csv"
            output = root / "evidence.csv"
            autofill = root / "autofill.csv"
            _write_eligibility(
                eligibility,
                [_eligibility_row(event_ref, "ais_truth_matched", "amber_human_review", "TRUE", "240")],
            )
            _write_feature(feature, [])
            _write_lifecycle(lifecycle, [])
            _write_sfsd(
                sfsd,
                [
                    _sfsd_row(
                        event_ref,
                        "matched",
                        "event_number",
                        "PEA_MOMENTARY_OR_SHORT",
                        "cause_available",
                    )
                ],
            )

            build_autonomous_evidence_collector(eligibility, feature, lifecycle, sfsd, output, autofill_output=autofill)
            rows = _read_csv(output)

            self.assertEqual(rows[0]["evidence_status"], "rejected_conflict")
            self.assertIn("pea_momentary_ais_sustained_conflict", rows[0]["evidence_reasons"])
            self.assertEqual(_read_csv(autofill), [])

    def test_feeder_only_sfsd_and_reportpo_proxy_do_not_auto_approve(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_id = "webex-raw-secret-id-2"
            ref_proxy = _redacted_ref(raw_id)
            ref_feeder = "msg-feeder"
            eligibility = root / "eligibility.csv"
            feature = root / "feature.csv"
            lifecycle = root / "lifecycle.csv"
            sfsd = root / "sfsd.csv"
            output = root / "evidence.csv"
            autofill = root / "autofill.csv"
            _write_eligibility(
                eligibility,
                [
                    _eligibility_row(ref_proxy, "ais_truth_matched", "amber_human_review", "TRUE", "100"),
                    _eligibility_row(ref_feeder, "ais_truth_matched", "amber_human_review", "TRUE", "100"),
                ],
            )
            _write_feature(
                feature,
                [
                    _feature_row(
                        raw_id,
                        "matched",
                        "proxy_only",
                        "cause_missing;webex_first_notification_status_assumption",
                    )
                ],
            )
            _write_lifecycle(lifecycle, [])
            _write_sfsd(
                sfsd,
                [
                    _sfsd_row(
                        ref_feeder,
                        "matched",
                        "feeder_time_audit_only",
                        "PEA_SUSTAINED",
                        "cause_available",
                    )
                ],
            )

            build_autonomous_evidence_collector(eligibility, feature, lifecycle, sfsd, output, autofill_output=autofill)
            rows = {row["event_ref"]: row for row in _read_csv(output)}
            autofill_refs = {row["event_ref"] for row in _read_csv(autofill)}

            self.assertEqual(rows[ref_proxy]["evidence_status"], "pending_insufficient_evidence")
            self.assertIn("reportpo_feature_proxy_context_only", rows[ref_proxy]["evidence_reasons"])
            self.assertEqual(rows[ref_feeder]["evidence_status"], "pending_insufficient_evidence")
            self.assertIn("sfsd_feeder_time_audit_only", rows[ref_feeder]["evidence_reasons"])
            self.assertNotEqual(rows[ref_feeder]["evidence_status"], "approved_candidate")
            self.assertIn(ref_proxy, autofill_refs)
            self.assertNotIn(ref_feeder, autofill_refs)
            self.assertNotIn(raw_id, output.read_text(encoding="utf-8-sig"))

    def test_webex_only_and_pea_quarantine_are_not_forward_autofilled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            eligibility = root / "eligibility.csv"
            feature = root / "feature.csv"
            lifecycle = root / "lifecycle.csv"
            sfsd = root / "sfsd.csv"
            output = root / "evidence.csv"
            autofill = root / "autofill.csv"
            _write_eligibility(
                eligibility,
                [
                    _eligibility_row("msg-webex", "webex_trigger_no_ais_truth", "monitor_only", "FALSE", ""),
                    _eligibility_row("msg-pea", "pea_quarantined", "red_blocked", "TRUE", "100"),
                ],
            )
            _write_feature(feature, [])
            _write_lifecycle(lifecycle, [])
            _write_sfsd(sfsd, [])

            build_autonomous_evidence_collector(eligibility, feature, lifecycle, sfsd, output, autofill_output=autofill)
            rows = {row["event_ref"]: row for row in _read_csv(output)}

            self.assertEqual(rows["msg-webex"]["evidence_status"], "monitor_only")
            self.assertEqual(rows["msg-pea"]["evidence_status"], "blocked_no_customer_send")
            self.assertEqual(_read_csv(autofill), [])


def _write_eligibility(path: Path, rows: list[dict[str, str]]) -> None:
    _write_csv(
        path,
        [
            "event_ref",
            "event_time",
            "feeder",
            "device_id",
            "source_lane",
            "eligibility_status",
            "stage1_class",
            "active_ais_outage_confirmed",
            "actual_restoration_minutes",
            "selected_p50",
            "selected_q10",
            "selected_q90",
            "selected_absolute_error",
        ],
        rows,
    )


def _eligibility_row(ref: str, lane: str, status: str, active: str, actual: str) -> dict[str, str]:
    return {
        "event_ref": ref,
        "event_time": "2026-06-01T10:00:00",
        "feeder": "PFA09",
        "device_id": "PFA09R-03",
        "source_lane": lane,
        "eligibility_status": status,
        "stage1_class": "uncertain",
        "active_ais_outage_confirmed": active,
        "actual_restoration_minutes": actual,
        "selected_p50": "60",
        "selected_q10": "20",
        "selected_q90": "180",
        "selected_absolute_error": "180",
    }


def _write_feature(path: Path, rows: list[dict[str, str]]) -> None:
    _write_csv(
        path,
        ["webex_message_id", "match_status", "feature_quality", "feature_flags"],
        rows,
    )


def _feature_row(raw_id: str, status: str, quality: str, flags: str) -> dict[str, str]:
    return {
        "webex_message_id": raw_id,
        "match_status": status,
        "feature_quality": quality,
        "feature_flags": flags,
    }


def _write_lifecycle(path: Path, rows: list[dict[str, str]]) -> None:
    _write_csv(
        path,
        ["webex_message_id", "match_status", "lifecycle_quality", "job_status_at_notification", "cl_datetime"],
        rows,
    )


def _write_sfsd(path: Path, rows: list[dict[str, str]]) -> None:
    _write_csv(
        path,
        [
            "event_ref",
            "sfsd_match_status",
            "sfsd_match_level",
            "sfsd_evidence_quality",
            "cause_status",
            "sfsd_main_cause",
            "sfsd_sub_cause",
            "sfsd_weather",
        ],
        rows,
    )


def _sfsd_row(
    ref: str,
    status: str,
    level: str,
    quality: str,
    cause_status: str,
    *,
    main_cause: str = "",
    sub_cause: str = "",
    weather: str = "",
) -> dict[str, str]:
    return {
        "event_ref": ref,
        "sfsd_match_status": status,
        "sfsd_match_level": level,
        "sfsd_evidence_quality": quality,
        "cause_status": cause_status,
        "sfsd_main_cause": main_cause,
        "sfsd_sub_cause": sub_cause,
        "sfsd_weather": weather,
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


def _redacted_ref(value: str) -> str:
    return "msg-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
