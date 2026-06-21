import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.confidence_gate import (
    build_forward_capture_template,
    build_shadow_send_eligibility,
    build_two_stage_shadow_challenger,
    import_forward_capture,
)


class ConfidenceGateTests(unittest.TestCase):
    def test_shadow_send_policy_blocks_unsafe_lanes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readiness = root / "readiness.csv"
            notification = root / "notification.csv"
            lifecycle = root / "lifecycle.csv"
            remaining = root / "remaining.csv"
            output = root / "eligibility.csv"
            markdown = root / "eligibility.md"
            gate = root / "gate.md"
            segments = root / "segments.csv"
            _write_readiness(readiness)
            _write_notification(notification)
            _write_lifecycle(lifecycle)
            _write_remaining(remaining)

            result = build_shadow_send_eligibility(
                readiness,
                notification,
                output,
                markdown,
                gate,
                lifecycle_challenger_csv=lifecycle,
                remaining_time_csv=remaining,
                segments_output=segments,
            )
            rows = {row["event_ref"]: row for row in _read_csv(output)}
            segment_rows = _read_csv(segments)
            pea_segment = next(row for row in segment_rows if row["dimension"] == "source_lane" and row["segment"] == "pea_quarantined")

            self.assertEqual(rows["msg-green"]["eligibility_status"], "green_auto_candidate")
            self.assertEqual(rows["msg-green"]["recommended_send_mode"], "shadow_auto_etr_candidate")
            self.assertEqual(rows["msg-momentary"]["eligibility_status"], "amber_human_review")
            self.assertIn("momentary_webex_requires_review", rows["msg-momentary"]["blocker_reasons"])
            self.assertEqual(rows["msg-long"]["eligibility_status"], "amber_human_review")
            self.assertEqual(rows["msg-long"]["recommended_send_mode"], "status_only_or_human_approved")
            self.assertIn("long_outage_risk", rows["msg-long"]["blocker_reasons"])
            self.assertEqual(rows["msg-feeder"]["eligibility_status"], "red_blocked")
            self.assertIn("feeder_fallback_shadow_only", rows["msg-feeder"]["blocker_reasons"])
            self.assertEqual(rows["msg-noaffected"]["eligibility_status"], "red_blocked")
            self.assertEqual(rows["msg-noactive"]["eligibility_status"], "red_blocked")
            self.assertEqual(rows["msg-webex"]["eligibility_status"], "monitor_only")
            self.assertEqual(rows["msg-pea"]["eligibility_status"], "red_blocked")
            self.assertIn("pea_quarantined", rows["msg-pea"]["blocker_reasons"])
            self.assertEqual(pea_segment["mae"], "")
            self.assertEqual(pea_segment["coverage"], "")
            self.assertGreaterEqual(result["green_auto_candidate_rows"], 1)
            self.assertIn("Production Readiness Gate", gate.read_text(encoding="utf-8-sig"))

    def test_forward_capture_template_and_import_use_only_approved_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readiness = root / "readiness.csv"
            notification = root / "notification.csv"
            lifecycle = root / "lifecycle.csv"
            remaining = root / "remaining.csv"
            eligibility = root / "eligibility.csv"
            template = root / "template.csv"
            valid = root / "valid.csv"
            rejects = root / "rejects.csv"
            _write_readiness(readiness)
            _write_notification(notification)
            _write_lifecycle(lifecycle)
            _write_remaining(remaining)
            build_shadow_send_eligibility(readiness, notification, eligibility, lifecycle_challenger_csv=lifecycle, remaining_time_csv=remaining)

            template_result = build_forward_capture_template(eligibility, template, top_n=10)
            template_rows = _read_csv(template)
            refs = {row["event_ref"] for row in template_rows}
            self.assertIn("msg-long", refs)
            self.assertIn("msg-feeder", refs)
            self.assertNotIn("msg-webex", refs)
            self.assertNotIn("msg-pea", refs)
            self.assertGreater(template_result["template_rows"], 0)

            _write_forward_input(template)
            import_result = import_forward_capture(template, valid, rejects, ais_only_readiness_csv=readiness)
            valid_rows = _read_csv(valid)
            reject_rows = _read_csv(rejects)

            self.assertEqual(import_result["valid_rows"], 1)
            self.assertEqual(valid_rows[0]["event_ref"], "msg-long")
            reject_issues = ";".join(row["validation_issues"] for row in reject_rows)
            self.assertIn("review_status_not_approved", reject_issues)
            self.assertIn("first_restore_conflicts_with_ais_truth", reject_issues)

    def test_two_stage_only_exposes_public_p50_for_green_normal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readiness = root / "readiness.csv"
            notification = root / "notification.csv"
            lifecycle = root / "lifecycle.csv"
            remaining = root / "remaining.csv"
            eligibility = root / "eligibility.csv"
            forward = root / "forward.csv"
            output = root / "two_stage.csv"
            markdown = root / "two_stage.md"
            segments = root / "two_stage_segments.csv"
            _write_readiness(readiness)
            _write_notification(notification)
            _write_lifecycle(lifecycle)
            _write_remaining(remaining)
            _write_forward_validated(forward)
            build_shadow_send_eligibility(readiness, notification, eligibility, lifecycle_challenger_csv=lifecycle, remaining_time_csv=remaining)

            result = build_two_stage_shadow_challenger(eligibility, lifecycle, output, markdown, segments, forward_capture_validated_csv=forward)
            rows = {row["event_ref"]: row for row in _read_csv(output)}

            self.assertEqual(rows["msg-green"]["public_send_allowed"], "TRUE")
            self.assertEqual(rows["msg-green"]["public_message_type"], "etr_range")
            self.assertEqual(rows["msg-green"]["public_p50"], "45")
            self.assertEqual(rows["msg-long"]["public_send_allowed"], "FALSE")
            self.assertEqual(rows["msg-long"]["public_p50"], "")
            self.assertEqual(rows["msg-long"]["public_message_type"], "human_review_required")
            self.assertEqual(rows["msg-webex"]["stage2_mode"], "monitor_only")
            self.assertEqual(rows["msg-pea"]["stage2_mode"], "blocked")
            self.assertEqual(rows["msg-long"]["forward_context_status"], "approved_context_available")
            self.assertNotIn("6101000001", output.read_text(encoding="utf-8-sig"))
            self.assertIn("Two-Stage Shadow Challenger", markdown.read_text(encoding="utf-8-sig"))
            self.assertGreaterEqual(result["auto_etr_range_rows"], 1)


def _write_readiness(path: Path) -> None:
    columns = [
        "source_lane",
        "event_ref",
        "event_time",
        "district",
        "feeder",
        "device_id",
        "match_level",
        "match_confidence",
        "affected_count",
        "actual_restoration_minutes",
        "model_metric_included",
        "current_p50",
        "current_q10",
        "current_q90",
        "current_absolute_error",
        "current_covered_q10_q90",
    ]
    rows = [
        _readiness_row("ais_truth_matched", "msg-green", "recloser", "0.9", "2", "50", "45", "20", "80"),
        _readiness_row("ais_truth_matched", "msg-momentary", "recloser", "0.9", "2", "150", "145", "100", "190"),
        _readiness_row("ais_truth_matched", "msg-long", "recloser", "0.9", "2", "250", "90", "40", "260"),
        _readiness_row("ais_truth_matched", "msg-feeder", "feeder", "0.9", "3", "70", "60", "30", "100"),
        _readiness_row("ais_truth_matched", "msg-noaffected", "recloser", "0.9", "0", "80", "55", "30", "90"),
        _readiness_row("ais_truth_matched", "msg-noactive", "recloser", "0.9", "2", "90", "55", "30", "90"),
        _readiness_row("webex_trigger_no_ais_truth", "msg-webex", "", "0", "0", "", "40", "20", "80", metric="false"),
        _readiness_row("pea_quarantined", "msg-pea", "recloser", "0.9", "2", "100", "40", "20", "80", metric="false"),
    ]
    _write_csv(path, columns, rows)


def _readiness_row(
    lane: str,
    ref: str,
    match_level: str,
    confidence: str,
    affected: str,
    actual: str,
    p50: str,
    q10: str,
    q90: str,
    *,
    metric: str = "true",
) -> dict[str, str]:
    return {
        "source_lane": lane,
        "event_ref": ref,
        "event_time": "2026-06-01T10:00:00",
        "district": "พังโคน",
        "feeder": "PFA09",
        "device_id": "PFA09R-03",
        "match_level": match_level,
        "match_confidence": confidence,
        "affected_count": affected,
        "actual_restoration_minutes": actual,
        "model_metric_included": metric,
        "current_p50": p50,
        "current_q10": q10,
        "current_q90": q90,
        "current_absolute_error": "",
        "current_covered_q10_q90": "",
    }


def _write_notification(path: Path) -> None:
    columns = ["event_id", "webex_message_ref", "active_ais_outage_confirmed", "event_age_band", "webex_device_interruption_class", "notification_time_gate"]
    rows = [
        _notification_row("msg-green", "TRUE"),
        _notification_row("msg-momentary", "TRUE", webex_state="momentary_le_1m"),
        _notification_row("msg-long", "TRUE"),
        _notification_row("msg-feeder", "TRUE"),
        _notification_row("msg-noaffected", "TRUE"),
        _notification_row("msg-noactive", "FALSE"),
        _notification_row("msg-webex", "FALSE"),
        _notification_row("msg-pea", "TRUE"),
    ]
    _write_csv(path, columns, rows)


def _notification_row(ref: str, active: str, *, webex_state: str = "sustained_candidate") -> dict[str, str]:
    return {
        "event_id": "event-" + ref,
        "webex_message_ref": ref,
        "active_ais_outage_confirmed": active,
        "event_age_band": "0_5m",
        "webex_device_interruption_class": webex_state,
        "notification_time_gate": "shadow_etr_candidate",
    }


def _write_lifecycle(path: Path) -> None:
    columns = [
        "event_ref",
        "event_id",
        "lifecycle_v3_p50",
        "lifecycle_v3_q10",
        "lifecycle_v3_q90",
        "lifecycle_v3_absolute_error",
        "lifecycle_v3_covered_q10_q90",
    ]
    rows = [
        _lifecycle_row("msg-green", "45", "20", "80", "5", "TRUE"),
        _lifecycle_row("msg-long", "90", "40", "260", "160", "TRUE"),
        _lifecycle_row("msg-feeder", "60", "30", "100", "10", "TRUE"),
        _lifecycle_row("msg-noaffected", "55", "30", "90", "25", "TRUE"),
        _lifecycle_row("msg-noactive", "55", "30", "90", "35", "FALSE"),
        _lifecycle_row("msg-pea", "40", "20", "80", "60", "FALSE"),
    ]
    _write_csv(path, columns, rows)


def _lifecycle_row(ref: str, p50: str, q10: str, q90: str, error: str, covered: str) -> dict[str, str]:
    return {
        "event_ref": ref,
        "event_id": "event-" + ref,
        "lifecycle_v3_p50": p50,
        "lifecycle_v3_q10": q10,
        "lifecycle_v3_q90": q90,
        "lifecycle_v3_absolute_error": error,
        "lifecycle_v3_covered_q10_q90": covered,
    }


def _write_remaining(path: Path) -> None:
    columns = ["event_ref", "challenger_p50", "challenger_q10", "challenger_q90", "challenger_absolute_error", "challenger_covered_q10_q90"]
    rows = [_remaining_row(ref) for ref in ("msg-green", "msg-long", "msg-feeder", "msg-noaffected", "msg-noactive", "msg-webex", "msg-pea")]
    _write_csv(path, columns, rows)


def _remaining_row(ref: str) -> dict[str, str]:
    return {
        "event_ref": ref,
        "challenger_p50": "50",
        "challenger_q10": "20",
        "challenger_q90": "100",
        "challenger_absolute_error": "10",
        "challenger_covered_q10_q90": "TRUE",
    }


def _write_forward_input(path: Path) -> None:
    columns = [
        "event_ref",
        "event_time",
        "feeder",
        "device_id",
        "eligibility_status",
        "stage1_class",
        "blocker_reasons",
        "cause_group",
        "work_type",
        "switching_or_isolation",
        "material_repair_required",
        "weather_or_lightning",
        "crew_dispatch_time",
        "arrival_time",
        "first_restore_time",
        "review_status",
        "reviewer",
        "reviewed_at",
        "notes",
    ]
    rows = [
        _forward_row("msg-long", "approved", "storm", "repair", "2026-06-01T14:10:00"),
        _forward_row("msg-feeder", "pending", "tree", "switching", "2026-06-01T11:10:00"),
        _forward_row("msg-noaffected", "approved", "storm", "repair", "2026-06-02T10:00:00"),
    ]
    _write_csv(path, columns, rows)


def _write_forward_validated(path: Path) -> None:
    columns = FORWARD_COLUMNS_FOR_TEST
    rows = [_forward_row("msg-long", "approved", "storm", "repair", "2026-06-01T14:10:00")]
    _write_csv(path, columns, rows)


FORWARD_COLUMNS_FOR_TEST = [
    "event_ref",
    "event_time",
    "feeder",
    "device_id",
    "eligibility_status",
    "stage1_class",
    "blocker_reasons",
    "cause_group",
    "work_type",
    "switching_or_isolation",
    "material_repair_required",
    "weather_or_lightning",
    "crew_dispatch_time",
    "arrival_time",
    "first_restore_time",
    "review_status",
    "reviewer",
    "reviewed_at",
    "notes",
]


def _forward_row(ref: str, status: str, cause: str, work: str, restore: str) -> dict[str, str]:
    return {
        "event_ref": ref,
        "event_time": "2026-06-01T10:00:00",
        "feeder": "PFA09",
        "device_id": "PFA09R-03",
        "eligibility_status": "amber_human_review",
        "stage1_class": "long_outage_risk",
        "blocker_reasons": "long_outage_risk",
        "cause_group": cause,
        "work_type": work,
        "switching_or_isolation": "",
        "material_repair_required": "yes",
        "weather_or_lightning": "yes",
        "crew_dispatch_time": "",
        "arrival_time": "",
        "first_restore_time": restore,
        "review_status": status,
        "reviewer": "owner",
        "reviewed_at": "2026-06-19",
        "notes": "",
    }


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
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
