import csv
import hashlib
import tempfile
import unittest
from pathlib import Path

from ais_etr.ais_only_readiness import build_ais_only_readiness


class AisOnlyReadinessTests(unittest.TestCase):
    def test_separates_ais_metric_rows_from_webex_and_pea_quarantine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "shadow.csv"
            governance = root / "governance.csv"
            feature = root / "feature.csv"
            lifecycle = root / "lifecycle.csv"
            sfsd = root / "sfsd.csv"
            decision = root / "decision.csv"
            output = root / "readiness.csv"
            markdown = root / "readiness.md"
            quarantine = root / "quarantine.csv"

            approved_ref = _ref("raw-approved")
            _write_rows(
                shadow,
                [
                    "event_id",
                    "webex_message_ref",
                    "event_time",
                    "district",
                    "device_type",
                    "device_id",
                    "feeder",
                    "match_level",
                    "match_confidence",
                    "affected_count",
                    "actual_restoration_minutes",
                    "truth_source",
                    "current_p50",
                    "current_q10",
                    "current_q90",
                    "current_absolute_error",
                    "current_covered_q10_q90",
                ],
                [
                    {
                        "event_id": "event-good",
                        "webex_message_ref": "msg-good",
                        "event_time": "2026-01-01T00:00:00",
                        "device_id": "PFA02R-01",
                        "feeder": "PFA02",
                        "match_level": "recloser",
                        "match_confidence": "0.9",
                        "affected_count": "2",
                        "actual_restoration_minutes": "45",
                        "truth_source": "ais_site_power_status",
                        "current_p50": "40",
                        "current_q10": "20",
                        "current_q90": "70",
                        "current_absolute_error": "5",
                        "current_covered_q10_q90": "true",
                    },
                    {
                        "event_id": "event-webex-only",
                        "webex_message_ref": "msg-webex",
                        "event_time": "2026-01-01T01:00:00",
                        "device_id": "PFA03R-01",
                        "feeder": "PFA03",
                        "match_level": "recloser",
                        "match_confidence": "0.9",
                        "affected_count": "1",
                        "current_p50": "30",
                        "current_absolute_error": "999",
                    },
                    {
                        "event_id": "event-short",
                        "webex_message_ref": "msg-short",
                        "event_time": "2026-01-01T02:00:00",
                        "device_id": "PFA04R-01",
                        "feeder": "PFA04",
                        "match_level": "recloser",
                        "match_confidence": "0.9",
                        "affected_count": "1",
                        "actual_restoration_minutes": "4",
                        "truth_source": "ais_site_power_status",
                        "current_absolute_error": "999",
                        "current_covered_q10_q90": "false",
                    },
                ],
            )
            _write_rows(
                governance,
                [
                    "source_name",
                    "event_ref",
                    "event_time",
                    "feeder",
                    "webex_device_id",
                    "sfsd_candidate_device_id",
                    "request_type",
                    "review_status",
                    "validation_status",
                    "usable_as_context",
                    "unresolved_blocker",
                    "recommended_action",
                ],
                [
                    {
                        "source_name": "sfsd_owner_approval",
                        "event_ref": approved_ref,
                        "feeder": "PFA02",
                        "webex_device_id": "PFA02R-01",
                        "sfsd_candidate_device_id": "PFA02VB-01",
                        "review_status": "approved",
                        "validation_status": "approved_context_only",
                        "usable_as_context": "true",
                        "unresolved_blocker": "false",
                    },
                    {
                        "source_name": "sfsd_owner_approval",
                        "event_ref": "msg-pending",
                        "feeder": "PFA03",
                        "webex_device_id": "PFA03R-01",
                        "sfsd_candidate_device_id": "PFA03VB-01",
                        "review_status": "pending",
                        "validation_status": "pending_owner_approval",
                        "usable_as_context": "false",
                        "unresolved_blocker": "true",
                    },
                ],
            )
            _write_rows(
                feature,
                [
                    "webex_message_id",
                    "webex_event_time",
                    "webex_device_id",
                    "webex_feeder",
                    "reportpo_device_id",
                    "match_status",
                ],
                [
                    {
                        "webex_message_id": "raw-approved",
                        "webex_device_id": "PFA02R-01",
                        "webex_feeder": "PFA02",
                        "reportpo_device_id": "PFA02R-01",
                        "match_status": "matched",
                    },
                    {
                        "webex_message_id": "raw-secret-feature",
                        "webex_device_id": "PFA09R-03",
                        "webex_feeder": "PFA09",
                        "reportpo_device_id": "PFA09F-05/2",
                        "match_status": "no_match",
                    },
                ],
            )
            _write_rows(
                lifecycle,
                ["webex_message_id", "webex_event_time", "webex_device_id", "webex_feeder", "po_device_id", "match_status"],
                [
                    {
                        "webex_message_id": "raw-secret-lifecycle",
                        "webex_device_id": "SEK06VR-103",
                        "webex_feeder": "SEK06",
                        "po_device_id": "SEK06VR-103",
                        "match_status": "matched",
                    }
                ],
            )
            _write_rows(
                sfsd,
                ["event_ref", "event_time", "feeder", "device_id", "sfsd_device_id", "sfsd_match_status"],
                [
                    {
                        "event_ref": "msg-sfsd",
                        "feeder": "BDH03",
                        "device_id": "BDH03VR-103",
                        "sfsd_device_id": "BDH03VR-103",
                        "sfsd_match_status": "no_match",
                    }
                ],
            )
            _write_rows(
                decision,
                ["event_ref", "event_time", "feeder", "webex_device_id", "sfsd_candidate_device_id", "final_decision", "final_action"],
                [
                    {
                        "event_ref": "msg-decision",
                        "feeder": "PFA09",
                        "webex_device_id": "PFA09R-03",
                        "sfsd_candidate_device_id": "PFA09F-05/2",
                        "final_decision": "reject_sfsd_candidate_webex_device_confirmed",
                    }
                ],
            )

            result = build_ais_only_readiness(
                shadow,
                governance,
                output,
                markdown,
                quarantine,
                reportpo_feature_audit_csv=feature,
                reportpo_lifecycle_audit_csv=lifecycle,
                sfsd_evidence_csv=sfsd,
                sfsd_decision_csv=decision,
            )
            readiness_rows = _read_csv(output)
            quarantine_text = quarantine.read_text(encoding="utf-8-sig")

            self.assertEqual(result["ais_truth_matched_rows"], 1)
            self.assertEqual(result["webex_trigger_no_ais_truth_rows"], 2)
            self.assertEqual(result["pea_context_approved_rows"], 1)
            self.assertEqual(result["pea_quarantined_rows"], 5)
            self.assertEqual(result["current_q50_mae_minutes"], 5)
            self.assertEqual(result["current_q10_q90_coverage"], 1.0)
            self.assertEqual(result["model_gate_status"], "blocked_insufficient_ais_truth")
            self.assertEqual(
                [row for row in readiness_rows if row["source_lane"] == "ais_truth_matched"][0]["model_feature_allowed"],
                "true",
            )
            self.assertEqual(
                [row for row in readiness_rows if row["source_lane"] == "webex_trigger_no_ais_truth"][0]["current_absolute_error"],
                "",
            )
            self.assertNotIn("raw-secret-feature", quarantine_text)
            self.assertNotIn("raw-secret-lifecycle", quarantine_text)
            self.assertNotIn("PEANO", quarantine_text)
            self.assertIn("AIS-Only Model Gate", markdown.read_text(encoding="utf-8-sig"))


def _ref(value: str) -> str:
    return "msg-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


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
