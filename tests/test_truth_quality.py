import unittest

from ais_etr.truth_quality import audit_truth_quality, summarize_truth_quality


class TruthQualityTests(unittest.TestCase):
    def test_audit_truth_quality_labels_micro_short_and_usable_rows(self):
        rows = [
            _row("evt-micro-very-short", 0.02, 50, 49.98, "FALSE"),
            _row("evt-micro", 0.08, 50, 49.92, "FALSE"),
            _row("evt-micro-boundary", 1.0, 45, 44, "FALSE"),
            _row("evt-short", 2.5, 30, 27.5, "FALSE"),
            _row("evt-short-boundary", 5.0, 30, 25, "FALSE"),
            _row("evt-sustained", 5.01, 6, 0.99, "TRUE"),
            _row("evt-usable", 30, 32, 2, "TRUE"),
            _row("evt-missing", "", "", "", ""),
        ]

        audit = audit_truth_quality(rows)

        policies = {row["event_id"]: row["evaluation_policy"] for row in audit}
        self.assertEqual(policies["evt-micro-very-short"], "momentary_micro_review")
        self.assertEqual(policies["evt-micro"], "momentary_micro_review")
        self.assertEqual(policies["evt-micro-boundary"], "momentary_micro_review")
        self.assertEqual(policies["evt-short"], "short_interruption_review")
        self.assertEqual(policies["evt-short-boundary"], "short_interruption_review")
        self.assertEqual(policies["evt-sustained"], "sustained_outage_eligible")
        self.assertEqual(policies["evt-usable"], "sustained_outage_eligible")
        self.assertNotIn("evt-missing", policies)

    def test_summary_reports_sensitivity_segments(self):
        rows = [
            _row("evt-micro", 0.08, 50, 49.92, "FALSE"),
            _row("evt-usable", 30, 32, 2, "TRUE"),
        ]
        audit = audit_truth_quality(rows)

        summary = summarize_truth_quality(rows, audit)

        self.assertEqual(summary["with_truth"], 2)
        self.assertEqual(summary["sustained_rows"], 1)
        self.assertEqual(summary["review_rows"], 1)
        self.assertEqual(summary["all_truth_metrics"]["current_q50_mae_minutes"], 25.96)
        self.assertEqual(summary["sustained_truth_metrics"]["current_q50_mae_minutes"], 2.0)
        self.assertEqual(summary["sustained_gate_status"], "insufficient_sustained_truth")
        self.assertGreater(summary["micro_error_share"], 0.9)

    def test_sustained_gate_uses_only_sustained_rows(self):
        rows = [
            _row(f"evt-{i}", 10 + i, 10 + i, 0, "TRUE" if i < 24 else "FALSE")
            for i in range(30)
        ]
        rows.append(_row("evt-micro-high-error", 0.08, 90, 89.92, "FALSE"))
        audit = audit_truth_quality(rows)

        summary = summarize_truth_quality(rows, audit)

        self.assertEqual(summary["with_truth"], 31)
        self.assertEqual(summary["sustained_rows"], 30)
        self.assertEqual(summary["review_rows"], 1)
        self.assertEqual(summary["all_truth_metrics"]["current_q50_mae_minutes"], 2.9)
        self.assertEqual(summary["sustained_truth_metrics"]["current_q50_mae_minutes"], 0.0)
        self.assertEqual(summary["sustained_gate_status"], "gate_pass")


def _row(event_id, actual, p50, error, covered):
    return {
        "event_id": event_id,
        "webex_message_ref": "msg-redacted",
        "event_time": "2026-06-17T10:00:00",
        "district": "pilot",
        "device_type": "Recloser",
        "device_id": "PFA01R-01",
        "feeder": "PFA01",
        "match_level": "recloser",
        "affected_count": "1",
        "actual_restoration_minutes": str(actual),
        "current_p50": str(p50),
        "current_q10": "10",
        "current_q90": "90",
        "current_absolute_error": str(error),
        "current_covered_q10_q90": covered,
        "challenger_p50": str(p50),
        "challenger_q10": "10",
        "challenger_q90": "90",
        "challenger_absolute_error": str(error),
        "challenger_covered_q10_q90": covered,
        "absolute_error_delta_challenger_minus_current": "0",
    }


if __name__ == "__main__":
    unittest.main()
