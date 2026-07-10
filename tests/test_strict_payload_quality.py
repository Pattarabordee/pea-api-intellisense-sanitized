import unittest

from ais_etr.strict_payload_quality import build_report


class StrictPayloadQualityTests(unittest.TestCase):
    def test_legacy_rows_hold_model_gate(self):
        report = build_report(
            {
                "production_send": "blocked",
                "truth_closed_intervals": 1346,
                "truth_strict_identity_intervals": 0,
                "model_ready_clean_truth_rows": 0,
                "model_truth_review_rows": 200,
                "truth_validation_counts": {"REVIEW_IDENTITY_KEY_REQUIRED": 200},
            },
            {
                "production_send": "blocked",
                "items": [
                    {"bridge_status": "LEGACY_UNVERIFIED", "pair_status": "CLOSED"},
                    {"bridge_status": "LEGACY_UNVERIFIED", "pair_status": "OPEN"},
                ],
            },
        )
        self.assertEqual(report["gate_status"], "identity_bridge_insufficient_clean_truth")
        self.assertEqual(report["bridge_status_counts"]["LEGACY_UNVERIFIED"], 2)
        self.assertEqual(report["truth_validation_counts"]["REVIEW_IDENTITY_KEY_REQUIRED"], 200)

    def test_non_blocked_source_is_rejected(self):
        with self.assertRaises(ValueError):
            build_report({"production_send": "sent"}, {"production_send": "blocked", "items": []})


if __name__ == "__main__":
    unittest.main()
