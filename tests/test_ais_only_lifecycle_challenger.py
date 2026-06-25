import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.ais_only_lifecycle_challenger import build_ais_only_lifecycle_challenger


class AisOnlyLifecycleChallengerTests(unittest.TestCase):
    def test_validates_review_rows_and_uses_only_prior_approved_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readiness = root / "readiness.csv"
            remaining = root / "remaining.csv"
            review = root / "review.csv"
            output = root / "challenger.csv"
            markdown = root / "challenger.md"
            feature_audit = root / "feature_audit.csv"
            valid = root / "valid.csv"
            rejects = root / "rejects.csv"
            segments = root / "segments.csv"
            _write_readiness(readiness)
            _write_remaining(remaining)
            _write_review(review)

            result = build_ais_only_lifecycle_challenger(
                readiness,
                remaining,
                review,
                output,
                markdown,
                feature_audit,
                valid,
                rejects,
                segments,
                min_lifecycle_prior_rows=1,
            )

            rows = {row["event_ref"]: row for row in _read_csv(output)}
            reject_rows = _read_csv(rejects)
            audit_refs = {row["event_ref"] for row in _read_csv(feature_audit)}

            self.assertEqual(result["candidates"], 6)
            self.assertEqual(result["validated_review_rows"], 3)
            self.assertEqual(result["rejected_review_rows"], 3)
            self.assertNotIn("msg-webex-only", audit_refs)
            self.assertNotIn("msg-pea", audit_refs)

            current = rows["msg-current"]
            self.assertEqual(current["lifecycle_feature_status"], "approved_context_used")
            self.assertEqual(current["lifecycle_source"], "prior_same_cause_work")
            self.assertEqual(current["lifecycle_prior_rows_used"], "1")
            self.assertEqual(current["selected_q90"], "240")
            self.assertEqual(current["lifecycle_v3_p50"], "240")
            self.assertEqual(current["lifecycle_v3_absolute_error"], "20")
            self.assertNotEqual(current["selected_q90"], "999")

            issue_text = ";".join(row["validation_issues"] for row in reject_rows)
            self.assertIn("review_status_not_approved", issue_text)
            self.assertIn("blocked_truth_field_cl_datetime", issue_text)
            self.assertIn("first_restore_conflicts_with_ais_truth", issue_text)
            self.assertEqual(rows["msg-pending"]["lifecycle_feature_status"], "review_rejected")
            self.assertIn("AIS-Only Lifecycle/Cause Challenger", markdown.read_text(encoding="utf-8-sig"))
            self.assertNotIn("6101000001", output.read_text(encoding="utf-8-sig"))


def _write_readiness(path: Path) -> None:
    columns = [
        "source_lane",
        "event_id",
        "event_ref",
        "event_time",
        "district",
        "feeder",
        "device_id",
        "model_metric_included",
        "actual_restoration_minutes",
        "current_p50",
        "current_q10",
        "current_q90",
    ]
    rows = [
        _readiness_row("ais_truth_matched", "event-old", "msg-old", "2026-01-01T10:00:00", "PFA09", "PFA09R-03", "240", "30", "10", "50"),
        _readiness_row("ais_truth_matched", "event-current", "msg-current", "2026-01-02T10:00:00", "PFA09", "PFA09R-03", "260", "30", "10", "50"),
        _readiness_row("ais_truth_matched", "event-future", "msg-future", "2026-01-03T10:00:00", "PFA09", "PFA09R-03", "999", "30", "10", "50"),
        _readiness_row("ais_truth_matched", "event-pending", "msg-pending", "2026-01-04T10:00:00", "SEK05", "SEK05VR-101", "120", "40", "20", "60"),
        _readiness_row("ais_truth_matched", "event-blocked", "msg-blocked", "2026-01-05T10:00:00", "SEK06", "SEK06VR-105", "100", "35", "15", "65"),
        _readiness_row("ais_truth_matched", "event-conflict", "msg-conflict", "2026-01-06T10:00:00", "WWA10", "WWA10VR-101", "100", "35", "15", "65"),
        _readiness_row("webex_trigger_no_ais_truth", "event-webex", "msg-webex-only", "2026-01-06T12:00:00", "PFA01", "PFA01R-01", "", "35", "15", "65", metric="false"),
        _readiness_row("pea_quarantined", "event-pea", "msg-pea", "2026-01-07T12:00:00", "PFA01", "PFA01R-02", "100", "35", "15", "65", metric="false"),
    ]
    _write_csv(path, columns, rows)


def _readiness_row(
    lane: str,
    event_id: str,
    ref: str,
    event_time: str,
    feeder: str,
    device: str,
    actual: str,
    p50: str,
    q10: str,
    q90: str,
    *,
    metric: str = "true",
) -> dict[str, str]:
    return {
        "source_lane": lane,
        "event_id": event_id,
        "event_ref": ref,
        "event_time": event_time,
        "district": "พังโคน",
        "feeder": feeder,
        "device_id": device,
        "model_metric_included": metric,
        "actual_restoration_minutes": actual,
        "current_p50": p50,
        "current_q10": q10,
        "current_q90": q90,
    }


def _write_remaining(path: Path) -> None:
    columns = [
        "event_ref",
        "challenger_p50",
        "challenger_q10",
        "challenger_q90",
        "challenger_absolute_error",
        "challenger_covered_q10_q90",
        "active_state_p50",
        "active_state_absolute_error",
        "active_state_covered_q10_q90",
    ]
    rows = [
        _remaining_row("msg-old", "80", "20", "120", "160"),
        _remaining_row("msg-current", "80", "20", "120", "180"),
        _remaining_row("msg-future", "80", "20", "120", "919"),
        _remaining_row("msg-pending", "70", "20", "100", "50"),
        _remaining_row("msg-blocked", "70", "20", "100", "30"),
        _remaining_row("msg-conflict", "70", "20", "100", "30"),
    ]
    _write_csv(path, columns, rows)


def _remaining_row(ref: str, p50: str, q10: str, q90: str, error: str) -> dict[str, str]:
    return {
        "event_ref": ref,
        "challenger_p50": p50,
        "challenger_q10": q10,
        "challenger_q90": q90,
        "challenger_absolute_error": error,
        "challenger_covered_q10_q90": "FALSE",
        "active_state_p50": p50,
        "active_state_absolute_error": error,
        "active_state_covered_q10_q90": "FALSE",
    }


def _write_review(path: Path) -> None:
    columns = [
        "event_ref",
        "event_time",
        "feeder",
        "device_id",
        "active_error_minutes",
        "suspected_gap",
        "outage_cause",
        "work_type",
        "crew_dispatch_time",
        "arrival_time",
        "first_restore_time",
        "switching_or_isolation",
        "material_or_repair_required",
        "weather_or_lightning",
        "review_status",
        "reviewer",
        "reviewed_at",
        "cl_datetime",
        "notes",
    ]
    rows = [
        _review_row("msg-old", "2026-01-01T10:00:00", "2026-01-01T14:00:00", "approved"),
        _review_row("msg-current", "2026-01-02T10:00:00", "2026-01-02T14:20:00", "approved"),
        _review_row("msg-future", "2026-01-03T10:00:00", "2026-01-04T02:39:00", "approved"),
        _review_row("msg-pending", "2026-01-04T10:00:00", "2026-01-04T12:00:00", "pending"),
        {**_review_row("msg-blocked", "2026-01-05T10:00:00", "2026-01-05T11:40:00", "approved"), "cl_datetime": "2026-01-05T12:30:00"},
        _review_row("msg-conflict", "2026-01-06T10:00:00", "2026-01-06T20:00:00", "approved"),
    ]
    _write_csv(path, columns, rows)


def _review_row(ref: str, event_time: str, first_restore: str, status: str) -> dict[str, str]:
    return {
        "event_ref": ref,
        "event_time": event_time,
        "feeder": "PFA09",
        "device_id": "PFA09R-03",
        "active_error_minutes": "100",
        "suspected_gap": "missing_lifecycle;missing_cause",
        "outage_cause": "storm",
        "work_type": "repair",
        "crew_dispatch_time": "",
        "arrival_time": "",
        "first_restore_time": first_restore,
        "switching_or_isolation": "",
        "material_or_repair_required": "yes",
        "weather_or_lightning": "yes",
        "review_status": status,
        "reviewer": "owner",
        "reviewed_at": "2026-06-18",
        "cl_datetime": "",
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
