import csv
import json
import os
import tempfile
import unittest
from pathlib import Path

from ais_etr.cloud_production import (
    build_mvp_daily_qa_pack,
    build_green_eligibility_report,
    build_production_approval_evidence_pack,
    build_production_gate_packet,
    run_ais_truth_interval_pairing,
    run_cloud_worker_shadow_loop,
)


class CloudProductionTests(unittest.TestCase):
    def test_ais_truth_interval_pairing_closes_and_reviews_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "truth.json"
            source.write_text(
                json.dumps(
                    {
                        "observations": [
                            {
                                "request_id": "OUT-1",
                                "source": "AIS",
                                "source_event_id": "EV-1",
                                "site_hash": "site-a",
                                "site_last4": "1234",
                                "meter_hash": "meter-a",
                                "meter_last4": "5678",
                                "event_type": "OUTAGE",
                                "detected_at": "2026-07-07T01:00:00+07:00",
                                "outage_at": "2026-07-07T01:00:00+07:00",
                                "validation_status": "READY_FOR_LEDGER",
                                "production_send": "blocked",
                                "customer_name": "PRIVATE CUSTOMER SHOULD NOT APPEAR",
                            },
                            {
                                "request_id": "REST-1",
                                "source": "AIS",
                                "source_event_id": "EV-1R",
                                "site_hash": "site-a",
                                "site_last4": "1234",
                                "meter_hash": "meter-a",
                                "meter_last4": "5678",
                                "event_type": "RESTORE",
                                "detected_at": "2026-07-07T01:45:00+07:00",
                                "restore_at": "2026-07-07T01:45:00+07:00",
                                "validation_status": "READY_FOR_LEDGER",
                                "production_send": "blocked",
                            },
                            {
                                "request_id": "OUT-2",
                                "source": "AIS",
                                "site_hash": "site-b",
                                "event_type": "OUTAGE",
                                "detected_at": "2026-07-07T02:00:00+07:00",
                                "outage_at": "2026-07-07T02:00:00+07:00",
                                "validation_status": "READY_FOR_LEDGER",
                                "production_send": "blocked",
                            },
                            {
                                "request_id": "UNK-1",
                                "source": "AIS",
                                "site_hash": "site-c",
                                "event_type": "UNKNOWN",
                                "detected_at": "2026-07-07T03:00:00+07:00",
                                "validation_status": "REVIEW",
                                "production_send": "blocked",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            output = root / "pairing.json"
            markdown = root / "pairing.md"

            result = run_ais_truth_interval_pairing(input_json=source, output_json=output, markdown_output=markdown)

            self.assertEqual(result["status"], "DRY_RUN")
            self.assertEqual(result["production_send"], "blocked")
            self.assertEqual(result["action_counts"]["CLOSE_INTERVAL"], 1)
            self.assertEqual(result["action_counts"]["OPEN_INTERVAL"], 1)
            self.assertEqual(result["action_counts"]["REVIEW"], 1)
            closed = [item for item in result["decisions"] if item["action"] == "CLOSE_INTERVAL"][0]
            self.assertEqual(closed["duration_minutes"], 45.0)
            self.assertEqual(closed["pair_status"], "CLOSED")
            self.assertEqual(closed["production_send"], "blocked")
            output_text = output.read_text(encoding="utf-8").lower()
            self.assertNotIn("private customer should not appear", output_text)
            self.assertIn("Pairing does not send customer-facing ETR", markdown.read_text(encoding="utf-8"))

    def test_cloud_worker_dry_run_keeps_guardrails_and_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "operator.json"
            source.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "request_id": "AIS-CLOUD-1",
                                "meter": {"hash": "abc123", "last4": "7890"},
                                "result": {"evidence": {"reason": "worker pending"}},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            output = root / "worker.json"
            markdown = root / "worker.md"

            result = run_cloud_worker_shadow_loop(input_json=source, output_json=output, markdown_output=markdown)

            self.assertEqual(result["status"], "DRY_RUN")
            self.assertEqual(result["production_send"], "blocked")
            self.assertEqual(result["decisions"][0]["etr_candidate"]["status"], "NOT_READY_FOR_AUTO_SEND")
            text = output.read_text(encoding="utf-8")
            self.assertIn("7890", text)
            self.assertNotIn("METER-", text)
            self.assertIn("No customer-facing callback is sent", markdown.read_text(encoding="utf-8"))

    def test_green_eligibility_report_builds_cloud_gate_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readiness = root / "readiness.csv"
            notification = root / "notification.csv"
            lifecycle = root / "lifecycle.csv"
            remaining = root / "remaining.csv"
            calibration = root / "calibration.csv"
            _write_readiness(readiness)
            _write_notification(notification)
            _write_lifecycle(lifecycle)
            _write_remaining(remaining)
            _write_csv(calibration, ["variant", "gate_status"], [])

            result = build_green_eligibility_report(
                ais_only_readiness=readiness,
                notification_time=notification,
                lifecycle_challenger=lifecycle,
                remaining_time=remaining,
                threshold_calibration=calibration,
                output=root / "green.csv",
                markdown_output=root / "green.md",
                segments_output=root / "segments.csv",
                gate_output=root / "gate.md",
                gate_csv_output=root / "gate.csv",
                json_output=root / "summary.json",
                min_green_rows=30,
            )

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["production_send"], "blocked")
            self.assertEqual(result["green_gate"]["green_rows"], 1)
            self.assertEqual(result["green_gate"]["additional_green_rows_needed"], 29)
            self.assertIn("No production AIS send", (root / "green.md").read_text(encoding="utf-8-sig"))

    def test_production_gate_packet_prioritizes_owner_evidence_without_greenwashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            eligibility = root / "eligibility.csv"
            gate = root / "green.json"
            real_hit = root / "real_hit.json"
            readiness = root / "readiness.json"
            owner = root / "owner.json"
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
                    "blocker_reasons",
                    "selected_absolute_error",
                    "selected_covered_q10_q90",
                ],
                [
                    {
                        "event_ref": "msg-a",
                        "event_time": "2026-06-01T10:00:00",
                        "feeder": "PFA09",
                        "device_id": "PFA09R-03",
                        "source_lane": "ais_truth_matched",
                        "eligibility_status": "amber_human_review",
                        "stage1_class": "uncertain",
                        "blocker_reasons": "wide_prediction_interval",
                        "selected_absolute_error": "10",
                        "selected_covered_q10_q90": "TRUE",
                    },
                    {
                        "event_ref": "msg-b",
                        "event_time": "2026-06-01T10:05:00",
                        "feeder": "PFA10",
                        "device_id": "PFA10R-01",
                        "source_lane": "webex_trigger_no_ais_truth",
                        "eligibility_status": "monitor_only",
                        "stage1_class": "uncertain",
                        "blocker_reasons": "missing_ais_truth",
                    },
                ],
            )
            gate.write_text(
                json.dumps(
                    {
                        "green_gate": {
                            "green_rows": 0,
                            "additional_green_rows_needed": 30,
                            "gate_status": "blocked_too_few_green_rows",
                        }
                    }
                ),
                encoding="utf-8",
            )
            real_hit.write_text(
                json.dumps(
                    {
                        "total_requests": 5,
                        "non_smoke_requests": 0,
                        "health_status": "ok",
                        "database": "ok",
                        "latest_request": {
                            "request_id": "AIS-CLOUD-SMOKE-1",
                            "status": "COMPLETED",
                            "production_send": "blocked",
                        },
                    }
                ),
                encoding="utf-8",
            )
            readiness.write_text(
                json.dumps(
                    {
                        "cloud_endpoint_ready": "READY_FOR_DEPLOYMENT_PACKAGE",
                        "production_infra_ready": "BLOCKED_PENDING_OWNER_OR_CONTROL",
                        "auto_etr_ready": "BLOCKED_GREEN_GATE",
                    }
                ),
                encoding="utf-8",
            )
            owner.write_text(json.dumps({"approvals": {"model_owner": False}}), encoding="utf-8")

            result = build_production_gate_packet(
                eligibility_csv=eligibility,
                green_gate_json=gate,
                real_hit_status_json=real_hit,
                readiness_gate_json=readiness,
                owner_approval_template=owner,
                output_csv=root / "gap.csv",
                markdown_output=root / "packet.md",
                json_output=root / "packet.json",
            )

            self.assertEqual(result["decision"], "AUTO_ETR_NO_GO")
            self.assertEqual(result["production_send"], "blocked")
            self.assertEqual(result["green_rows"], 0)
            self.assertEqual(result["owner_lane_counts"]["model_owner"], 1)
            self.assertEqual(result["owner_lane_counts"]["ais_truth_owner"], 1)
            packet = (root / "packet.md").read_text(encoding="utf-8")
            self.assertIn("do not count toward green model gate", packet)
            gap_text = (root / "gap.csv").read_text(encoding="utf-8-sig")
            self.assertIn("non_metric_smoke_demo_not_green_gate", gap_text)
            self.assertNotIn("production_send,real", gap_text)

    def test_production_approval_evidence_pack_builds_safe_owner_queues(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gap = root / "gap.csv"
            packet = root / "packet.json"
            real_hit = root / "real_hit.json"
            readiness = root / "readiness.json"
            _write_csv(
                gap,
                [
                    "event_ref",
                    "event_time",
                    "feeder",
                    "device_id",
                    "source_lane",
                    "eligibility_status",
                    "blocker_reasons",
                    "owner_lane",
                    "next_evidence_needed",
                    "conversion_rank",
                    "production_send",
                ],
                [
                    {
                        "event_ref": "msg-ais",
                        "event_time": "2026-06-01T10:00:00",
                        "feeder": "PFA09",
                        "device_id": "PFA09R-03",
                        "source_lane": "ais_truth_matched",
                        "eligibility_status": "red_blocked",
                        "blocker_reasons": "no_active_ais_evidence",
                        "owner_lane": "ais_truth_owner",
                        "next_evidence_needed": "AIS confirms active site outage at event time, or marks not affected.",
                        "conversion_rank": "200",
                        "production_send": "blocked",
                    },
                    {
                        "event_ref": "msg-topology",
                        "event_time": "2026-06-01T10:05:00",
                        "feeder": "PFA10",
                        "device_id": "PFA10R-01",
                        "source_lane": "pea_quarantined",
                        "eligibility_status": "red_blocked",
                        "blocker_reasons": "no_affected_ais;low_match_confidence",
                        "owner_lane": "pea_topology_owner",
                        "next_evidence_needed": "PEA topology owner confirms downstream AIS scope.",
                        "conversion_rank": "180",
                        "production_send": "blocked",
                    },
                    {
                        "event_ref": "msg-topology",
                        "event_time": "2026-06-01T10:05:00",
                        "feeder": "PFA10",
                        "device_id": "PFA10R-01",
                        "source_lane": "pea_quarantined",
                        "eligibility_status": "red_blocked",
                        "blocker_reasons": "no_affected_ais;low_match_confidence",
                        "owner_lane": "pea_topology_owner",
                        "next_evidence_needed": "PEA topology owner confirms downstream AIS scope.",
                        "conversion_rank": "180",
                        "production_send": "blocked",
                    },
                ],
            )
            packet.write_text(
                json.dumps(
                    {
                        "green_rows": 0,
                        "min_green_rows": 30,
                        "additional_green_rows_needed": 30,
                        "cloud_status": {"api_base_url": "https://example.invalid", "health_status": "ok", "database": "ok"},
                    }
                ),
                encoding="utf-8",
            )
            real_hit.write_text(json.dumps({"non_smoke_requests": 0, "total_requests": 5}), encoding="utf-8")
            readiness.write_text(
                json.dumps(
                    {
                        "cloud_endpoint_ready": "READY_FOR_DEPLOYMENT_PACKAGE",
                        "production_infra_ready": "BLOCKED_PENDING_OWNER_OR_CONTROL",
                        "auto_etr_ready": "BLOCKED_GREEN_GATE",
                    }
                ),
                encoding="utf-8",
            )
            old_database_url = os.environ.get("DATABASE_URL")
            os.environ["DATABASE_URL"] = "postgres://secret-user:secret-pass@example/db"
            try:
                result = build_production_approval_evidence_pack(
                    gap_actions_csv=gap,
                    owner_packet_json=packet,
                    real_hit_status_json=real_hit,
                    readiness_gate_json=readiness,
                    ais_truth_queue_output=root / "ais.csv",
                    topology_queue_output=root / "topology.csv",
                    ops_report_output=root / "ops.md",
                    ais_test_window_output=root / "ais_request.md",
                    markdown_output=root / "summary.md",
                    json_output=root / "summary.json",
                    top_n=30,
                )
            finally:
                if old_database_url is None:
                    os.environ.pop("DATABASE_URL", None)
                else:
                    os.environ["DATABASE_URL"] = old_database_url

            self.assertEqual(result["decision"], "AUTO_ETR_NO_GO")
            self.assertEqual(result["production_send"], "blocked")
            self.assertEqual(result["owner_queues"]["ais_truth_owner_rows"], 1)
            self.assertEqual(result["owner_queues"]["pea_topology_owner_rows"], 1)
            self.assertIn("msg-ais", (root / "ais.csv").read_text(encoding="utf-8-sig"))
            topology_text = (root / "topology.csv").read_text(encoding="utf-8-sig")
            self.assertIn("msg-topology", topology_text)
            self.assertEqual(topology_text.count("msg-topology"), 1)
            combined = "\n".join(
                [
                    (root / "ops.md").read_text(encoding="utf-8"),
                    (root / "ais_request.md").read_text(encoding="utf-8"),
                    (root / "summary.md").read_text(encoding="utf-8"),
                    (root / "summary.json").read_text(encoding="utf-8"),
                ]
            )
            self.assertNotIn("secret-pass", combined)
            self.assertNotIn("postgres://secret-user", combined)
            self.assertIn("X-API-Key: <cloud pilot key via secure channel only>", combined)

    def test_mvp_daily_qa_pack_keeps_blocked_truth_and_writes_recording_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            approval = root / "approval.json"
            packet = root / "packet.json"
            real_hit = root / "real_hit.json"
            privacy = root / "privacy.json"
            approval.write_text(
                json.dumps(
                    {
                        "mode": "shadow",
                        "production_send": "blocked",
                        "decision": "AUTO_ETR_NO_GO",
                        "cloud": {
                            "api_base_url": "https://example.invalid",
                            "web_console_url": "https://web.example.invalid",
                            "health_status": "ok",
                            "database": "ok",
                            "total_requests": 5,
                            "non_smoke_requests": 0,
                        },
                        "green_gate": {"green_rows": 0, "min_green_rows": 30, "additional_green_rows_needed": 30},
                        "owner_queues": {"ais_truth_owner_rows": 30, "pea_topology_owner_rows": 30},
                        "ops_controls": {
                            "backup_restore_drill": "BLOCKED_MISSING_POSTGRES_TOOLS_OR_URLS",
                            "missing_tools": ["pg_dump"],
                            "missing_env": ["DATABASE_URL"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            packet.write_text(json.dumps({"production_send": "blocked"}), encoding="utf-8")
            real_hit.write_text(json.dumps({"latest_request": {"request_id": "SMOKE", "production_send": "blocked"}}), encoding="utf-8")
            privacy.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            old_database_url = os.environ.get("DATABASE_URL")
            os.environ["DATABASE_URL"] = "postgres://secret-user:secret-pass@example/db"
            try:
                result = build_mvp_daily_qa_pack(
                    approval_pack_json=approval,
                    owner_packet_json=packet,
                    real_hit_status_json=real_hit,
                    privacy_scan_json=privacy,
                    output_json=root / "qa.json",
                    markdown_output=root / "qa.md",
                    recording_pack_output=root / "recording.md",
                )
            finally:
                if old_database_url is None:
                    os.environ.pop("DATABASE_URL", None)
                else:
                    os.environ["DATABASE_URL"] = old_database_url

            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["production_send"], "blocked")
            self.assertIn("green_model_gate", {check["name"] for check in result["checks"]})
            combined = "\n".join(
                [
                    (root / "qa.json").read_text(encoding="utf-8"),
                    (root / "qa.md").read_text(encoding="utf-8"),
                    (root / "recording.md").read_text(encoding="utf-8"),
                ]
            )
            self.assertIn("customer-facing Auto ETR", combined)
            self.assertIn("production_send", combined)
            self.assertNotIn("secret-pass", combined)
            self.assertNotIn("postgres://secret-user", combined)


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
    _write_csv(
        path,
        columns,
        [
            {
                "source_lane": "ais_truth_matched",
                "event_ref": "evt-green",
                "event_time": "2026-06-01T10:00:00",
                "district": "Phang Khon",
                "feeder": "PFA09",
                "device_id": "PFA09R-03",
                "match_level": "recloser",
                "match_confidence": "0.9",
                "affected_count": "2",
                "actual_restoration_minutes": "50",
                "model_metric_included": "true",
                "current_p50": "45",
                "current_q10": "20",
                "current_q90": "80",
                "current_absolute_error": "5",
                "current_covered_q10_q90": "TRUE",
            }
        ],
    )


def _write_notification(path: Path) -> None:
    _write_csv(
        path,
        ["event_id", "webex_message_ref", "active_ais_outage_confirmed", "event_age_band", "webex_device_interruption_class", "notification_time_gate"],
        [
            {
                "event_id": "event-evt-green",
                "webex_message_ref": "evt-green",
                "active_ais_outage_confirmed": "TRUE",
                "event_age_band": "0_5m",
                "webex_device_interruption_class": "sustained_candidate",
                "notification_time_gate": "shadow_etr_candidate",
            }
        ],
    )


def _write_lifecycle(path: Path) -> None:
    _write_csv(
        path,
        ["event_ref", "event_id", "lifecycle_v3_p50", "lifecycle_v3_q10", "lifecycle_v3_q90", "lifecycle_v3_absolute_error", "lifecycle_v3_covered_q10_q90"],
        [
            {
                "event_ref": "evt-green",
                "event_id": "event-evt-green",
                "lifecycle_v3_p50": "45",
                "lifecycle_v3_q10": "20",
                "lifecycle_v3_q90": "80",
                "lifecycle_v3_absolute_error": "5",
                "lifecycle_v3_covered_q10_q90": "TRUE",
            }
        ],
    )


def _write_remaining(path: Path) -> None:
    _write_csv(path, ["event_ref", "challenger_p50", "challenger_q10", "challenger_q90"], [])


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


if __name__ == "__main__":
    unittest.main()
