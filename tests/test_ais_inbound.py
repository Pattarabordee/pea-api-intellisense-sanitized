import csv
import gc
import json
import shutil
import re
import sqlite3
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from ais_etr.ais_inbound_contract import (
    build_ais_inbound_doc_qa,
    build_ais_inbound_security_audit,
    write_ais_inbound_contract_pack,
    write_ais_inbound_production_migration_pack,
    write_ais_inbound_test_kit,
)
from ais_etr.ais_inbound import (
    build_ais_inbound_audit_export,
    build_ais_inbound_db_snapshot,
    build_ais_inbound_first_hit_packet,
    build_ais_inbound_model_demo_readiness,
    build_ais_inbound_readiness_gate,
    build_ais_inbound_status_report,
    build_pilot_completion_gate,
    create_ais_inbound_server,
    process_ais_inbound_request,
    replay_ais_inbound_callbacks,
    run_ais_inbound_shadow_demo_rehearsal,
)
from ais_etr.db import RuntimeDb
from ais_etr.schemas import (
    CustomerAsset,
    CustomerMatch,
    MatchResult,
    OutageDevice,
    OutageEvent,
    Prediction,
)


class AisInboundTests(unittest.TestCase):
    def test_confirms_pea_outage_from_peano_topology_and_webex(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            request_log = root / "requests.jsonl"
            callback_log = root / "callbacks.jsonl"
            _seed_runtime(db_path)

            result = process_ais_inbound_request(
                db_path=db_path,
                payload={
                    "request_id": "AIS-1",
                    "meter_no": "REDACTED-METER-0000",
                    "timestamp": "2026-06-19T10:04:00+00:00",
                    "province": "Sakon Nakhon",
                    "district": "Phang Khon",
                    "subdistrict": "Demo",
                    "main_cause": "Faulty AC main failed",
                    "subcause": "PEA no back up",
                },
                requests_output=request_log,
                callbacks_output=callback_log,
                post_callback=False,
            )

            self.assertEqual(result.accepted_response["status"], "RECEIVED")
            self.assertEqual(result.callback_payload["status"], "CONFIRMED_PEA_OUTAGE")
            self.assertEqual(result.callback_payload["confidence"], "HIGH")
            self.assertEqual(result.callback_payload["evidence"]["match_level"], "cb")
            self.assertEqual(result.callback_payload["etr"]["status"], "SHADOW_ONLY")
            self.assertNotIn("1234567890", json.dumps(result.callback_payload))
            self.assertEqual(result.callback_payload["received"]["meter_ref"]["last4"], "0000")

            logged = request_log.read_text(encoding="utf-8") + callback_log.read_text(encoding="utf-8")
            self.assertNotIn("1234567890", logged)
            self.assertIn("0000", logged)

    def test_model_demo_readiness_reports_complete_shadow_chain_without_raw_identifiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            _seed_runtime(db_path)
            process_ais_inbound_request(
                db_path=db_path,
                payload={
                    "request_id": "AIS-DEMO-READY",
                    "meter_no": "REDACTED-METER-0000",
                    "timestamp": "2026-06-19T10:04:00+00:00",
                    "main_cause": "Faulty AC main failed",
                    "subcause": "PEA no back up",
                },
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )

            output = root / "demo_readiness.md"
            report = build_ais_inbound_model_demo_readiness(db_path, output=output)

            self.assertEqual(report["status"], "READY_FOR_SHADOW_DEMO")
            self.assertEqual(report["mode"], "shadow")
            self.assertEqual(report["production_send"], "blocked")
            self.assertEqual(report["shadow_etr_demo_candidates"], 1)
            self.assertEqual(report["latest_candidate"]["match_level"], "cb")
            self.assertEqual(report["latest_candidate"]["cause_lane"], "pea_no_backup")
            self.assertEqual(report["latest_candidate"]["etr_minutes_p50"], "45.0")
            self.assertEqual(report["gaps"], [])
            markdown = output.read_text(encoding="utf-8")
            self.assertIn("READY_FOR_SHADOW_DEMO", markdown)
            self.assertIn("Auto ETR production sending remains blocked", markdown)
            self.assertNotIn("1234567890", json.dumps(report, ensure_ascii=False) + markdown)
            self.assertNotIn("room-1", json.dumps(report, ensure_ascii=False) + markdown)

    def test_shadow_demo_rehearsal_creates_redacted_queryable_shadow_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            _seed_runtime(db_path)

            output = root / "rehearsal.md"
            report = run_ais_inbound_shadow_demo_rehearsal(
                db_path,
                output=output,
                request_id="AIS-DEMO-SHADOW-TEST",
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
            )

            self.assertEqual(report["status"], "READY_FOR_SHADOW_DEMO")
            self.assertEqual(report["mode"], "shadow")
            self.assertEqual(report["production_send"], "blocked")
            self.assertTrue(report["created_request"])
            self.assertEqual(report["request_id"], "AIS-DEMO-SHADOW-TEST")
            self.assertEqual(report["verification_status"], "CONFIRMED_PEA_OUTAGE")
            self.assertEqual(report["evidence"]["match_level"], "cb")
            self.assertEqual(report["etr"]["status"], "SHADOW_ONLY")
            self.assertEqual(report["decision"]["production_send"], "blocked")

            markdown = output.read_text(encoding="utf-8")
            combined = json.dumps(report, ensure_ascii=False) + markdown
            self.assertNotIn("1234567890", combined)
            self.assertNotIn("room-1", combined)
            self.assertNotIn("raw_text", combined)

            conn = sqlite3.connect(db_path)
            try:
                request_count = conn.execute("SELECT COUNT(*) FROM ais_inbound_requests").fetchone()[0]
                callback_payload = conn.execute(
                    "SELECT payload_json FROM ais_inbound_callbacks WHERE request_id = ?",
                    ("AIS-DEMO-SHADOW-TEST",),
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(request_count, 1)
            self.assertNotIn("1234567890", callback_payload)
            self.assertIn("SHADOW_ONLY", callback_payload)
            self.assertIn('"production_send": "blocked"', callback_payload)

            readiness = build_ais_inbound_model_demo_readiness(db_path, output=None)
            self.assertEqual(readiness["status"], "READY_FOR_SHADOW_DEMO")
            self.assertEqual(readiness["shadow_etr_demo_candidates"], 1)

    def test_shadow_demo_rehearsal_blocks_without_runtime_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()

            report = run_ais_inbound_shadow_demo_rehearsal(
                db_path,
                output=root / "rehearsal.md",
                request_id="AIS-DEMO-SHADOW-EMPTY",
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
            )

            self.assertEqual(report["status"], "BLOCKED_NO_RUNTIME_CANDIDATE")
            self.assertFalse(report["created_request"])
            self.assertEqual(report["production_send"], "blocked")
            conn = sqlite3.connect(db_path)
            try:
                request_count = conn.execute("SELECT COUNT(*) FROM ais_inbound_requests").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(request_count, 0)

    @unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell integration test")
    def test_local_hit_checker_excludes_shadow_demo_from_real_hits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requests_log = root / "ais_inbound_requests.jsonl"
            rows = [
                {
                    "received_at": "2026-06-22T01:00:00+00:00",
                    "callback_status": "CAPTURED_NO_CALLBACK_URL",
                    "accepted_response": {
                        "request_id": "AIS-REAL-1",
                        "http_status": 202,
                        "status": "RECEIVED",
                    },
                    "request": {"district": "redacted", "peano": {"last4": "1111"}},
                },
                {
                    "received_at": "2026-06-22T01:01:00+00:00",
                    "callback_status": "CAPTURED_NO_CALLBACK_URL",
                    "accepted_response": {
                        "request_id": "AIS-DEMO-SHADOW-20260622T010343Z",
                        "http_status": 202,
                        "status": "RECEIVED",
                    },
                    "request": {"district": "shadow_demo", "peano": {"last4": "6059"}},
                },
            ]
            requests_log.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

            script = Path(__file__).resolve().parents[1] / "runtime" / "ais_inbound_hit_check.ps1"
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-RequestsLog",
                    str(requests_log),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            report = json.loads(result.stdout)

            self.assertEqual(report["total_requests"], 2)
            self.assertEqual(report["non_smoke_requests"], 1)
            self.assertTrue(report["latest_non_smoke_request_ref"].startswith("request_"))
            self.assertNotIn("AIS-REAL-1", result.stdout)

    def test_model_demo_readiness_flags_missing_inbound_evidence_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()
            process_ais_inbound_request(
                db_path=db_path,
                payload={
                    "request_id": "AIS-DEMO-GAP",
                    "meter_no": "REDACTED-METER-0000",
                    "timestamp": "2026-06-19T10:04:00+00:00",
                    "main_cause": "Faulty AC main failed",
                    "subcause": "PEA no back up",
                },
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )

            report = build_ais_inbound_model_demo_readiness(db_path, output=None)

            self.assertEqual(report["status"], "NEEDS_RUNTIME_EVIDENCE")
            self.assertIn("no_inbound_request_matched_webex_topology_evidence", report["gaps"])
            self.assertIn("no_shadow_etr_candidate_returned_to_ais_inbound_callback", report["gaps"])
            self.assertIn("no_single_request_completes_request_trace_evidence_cause_etr_shadow_chain", report["gaps"])
            self.assertEqual(report["chain_counts"]["shadow_response_blocked"], 1)

    def test_no_registry_asset_returns_no_pea_evidence_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()

            result = process_ais_inbound_request(
                db_path=db_path,
                payload={
                    "request_id": "AIS-2",
                    "meter_no": "REDACTED-METER-0000",
                    "timestamp": "2026-06-19T10:04:00+00:00",
                },
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )

            self.assertEqual(result.callback_payload["status"], "NO_PEA_EVIDENCE_FOUND")
            self.assertEqual(result.callback_payload["etr"]["status"], "NOT_READY_FOR_AUTO_SEND")

    def test_duplicate_request_id_is_not_reprocessed_as_new_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()
            payload = {
                "request_id": "AIS-DUP",
                "meter_no": "REDACTED-METER-0000",
                "timestamp": "2026-06-19T10:04:00+00:00",
            }

            first = process_ais_inbound_request(
                db_path=db_path,
                payload=payload,
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )
            second = process_ais_inbound_request(
                db_path=db_path,
                payload=payload,
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )

            self.assertFalse(first.duplicate)
            self.assertTrue(second.duplicate)
            conn = sqlite3.connect(db_path)
            try:
                request_count = conn.execute("SELECT COUNT(*) FROM ais_inbound_requests").fetchone()[0]
                callback_count = conn.execute("SELECT COUNT(*) FROM ais_inbound_callbacks").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(request_count, 1)
            self.assertEqual(callback_count, 2)

    def test_pilot_completion_gate_passes_with_shadow_evidence_and_blocks_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()
            payload = {
                "request_id": "AIS-PILOT-COMPLETE-1",
                "meter_no": "REDACTED-METER-0000",
                "timestamp": "2026-06-19T10:04:00+00:00",
                "province": "Sakon Nakhon",
                "district": "Phang Khon",
                "subdistrict": "Demo",
            }
            process_ais_inbound_request(
                db_path=db_path,
                payload=payload,
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )
            process_ais_inbound_request(
                db_path=db_path,
                payload=payload,
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )

            status_file = root / "status.json"
            status_file.write_text(
                json.dumps(
                    {
                        "mode": "shadow",
                        "production_send": "blocked",
                        "primary_health_smoke": "200_OK",
                        "primary_auth_post_smoke": "202_RECEIVED",
                        "primary_unauth_post_smoke": "401_UNAUTHORIZED",
                    }
                ),
                encoding="utf-8",
            )
            verification_file = root / "verification.json"
            verification_file.write_text(
                json.dumps(
                    {
                        "mode": "shadow",
                        "production_send": "blocked",
                        "all_checks_ok": True,
                        "checks": [
                            {"name": "status_lookup_contract", "ok": True},
                            {"name": "status_lookup", "ok": True},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            security_file = root / "security.json"
            security_file.write_text(
                json.dumps({"status": "PASS", "mode": "shadow", "production_send": "blocked", "failures": []}),
                encoding="utf-8",
            )
            snapshot_file = root / "snapshot.json"
            snapshot_file.write_text(
                json.dumps(
                    {
                        "mode": "shadow",
                        "production_send": "blocked",
                        "integrity_check": "ok",
                        "counts_match": True,
                        "snapshot_path": str(root / "snapshot.sqlite"),
                        "snapshot_sha256": "a" * 64,
                    }
                ),
                encoding="utf-8",
            )
            readiness_file = root / "readiness.json"
            readiness_file.write_text(
                json.dumps({"mode": "shadow", "production_send": "blocked", "pilot_test_status": "READY_FOR_AIS_TEST"}),
                encoding="utf-8",
            )
            green_file = root / "green.md"
            green_file.write_text("Current green rows: 0\nGate status: blocked_too_few_green_rows\n", encoding="utf-8")
            production_file = root / "production.md"
            production_file.write_text("Status: blocked_no_green_subset\n", encoding="utf-8")
            pack_dir = root / "pack"
            pack_dir.mkdir()
            (pack_dir / "package_inventory.json").write_text("[]", encoding="utf-8")
            pack_zip = root / "pack.zip"
            pack_zip.write_bytes(b"zip")
            round2 = root / "round2.md"
            round2.write_text("sanitized ChatGPT review " * 20, encoding="utf-8")
            round3 = root / "round3.md"
            round3.write_text("stalled; local QA fallback logged", encoding="utf-8")

            report = build_pilot_completion_gate(
                db_path,
                status_file=status_file,
                verification_file=verification_file,
                security_audit_file=security_file,
                db_snapshot_file=snapshot_file,
                readiness_gate_file=readiness_file,
                green_gate_file=green_file,
                production_gate_file=production_file,
                share_pack_zip=pack_zip,
                share_pack_dir=pack_dir,
                chatgpt_round2_file=round2,
                chatgpt_round3_file=round3,
                output_markdown=root / "pilot_completion_gate.md",
                output_json=root / "pilot_completion_gate.json",
            )

            self.assertEqual(report["pilot_complete_status"], "PILOT_COMPLETE")
            self.assertEqual(report["production_send"], "blocked")
            self.assertIn("BLOCKED_GREEN_GATE", report["production_auto_etr_status"])
            check_status = {check["name"]: check["status"] for check in report["checks"]}
            self.assertEqual(check_status["duplicate_idempotency"], "PASS")
            self.assertEqual(check_status["green_auto_etr_gate"], "WARN")
            markdown = (root / "pilot_completion_gate.md").read_text(encoding="utf-8")
            self.assertIn("Pilot status: `PILOT_COMPLETE`", markdown)
            self.assertNotIn("1234567890", markdown)
            self.assertIn("0000", markdown)

    def test_http_endpoint_accepts_valid_request_with_202(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            _seed_runtime(db_path)
            server = create_ais_inbound_server(
                db_path=db_path,
                port=0,
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                url = f"http://{host}:{port}/api/v1/ais/outage-verifications"
                req = urllib.request.Request(
                    url,
                    data=json.dumps(
                        {
                            "request_id": "AIS-HTTP-1",
                            "meter_no": "REDACTED-METER-0000",
                            "timestamp": "2026-06-19T10:04:00+00:00",
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    body = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 202)
                self.assertEqual(body["status"], "RECEIVED")
                self.assertEqual(body["request_id"], "AIS-HTTP-1")
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_http_endpoint_accepts_common_ais_alias_fields_and_trailing_slash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            _seed_runtime(db_path)
            server = create_ais_inbound_server(
                db_path=db_path,
                port=0,
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                url = f"http://{host}:{port}/api/v1/ais/outage-verifications/?source=ais"
                req = urllib.request.Request(
                    url,
                    data=json.dumps(
                        {
                            "requestId": "AIS-HTTP-ALIAS-1",
                            "meterNo": "REDACTED-METER-0000",
                            "eventTime": "2026-06-19T17:04:00+07:00",
                            "provinceName": "Sakon Nakhon",
                            "districtName": "Phang Khon",
                            "subDistrict": "Demo",
                            "mainCause": "Faulty AC main failed",
                            "subCause": "PEA no back up",
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    body = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 202)
                self.assertEqual(body["status"], "RECEIVED")
                self.assertEqual(body["request_id"], "AIS-HTTP-ALIAS-1")

                logged = (root / "requests.jsonl").read_text(encoding="utf-8")
                self.assertNotIn("1234567890", logged)
                self.assertIn("0000", logged)
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_naive_ais_timestamp_is_treated_as_bangkok_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            _seed_runtime(db_path)

            result = process_ais_inbound_request(
                db_path=db_path,
                payload={
                    "requestId": "AIS-BKK-NAIVE",
                    "meterNo": "REDACTED-METER-0000",
                    "eventTime": "2026-06-19T17:04:00",
                    "mainCause": "Faulty AC main failed",
                    "subCause": "PEA no back up",
                },
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )

            self.assertEqual(result.callback_payload["status"], "CONFIRMED_PEA_OUTAGE")
            self.assertEqual(result.callback_payload["evidence"]["match_level"], "cb")
            self.assertEqual(result.callback_payload["received"]["timestamp_quality"]["status"], "REVIEW")
            self.assertIn(
                "timezone_assumed_bangkok",
                result.callback_payload["received"]["timestamp_quality"]["flags"],
            )

    def test_timestamp_quality_flags_future_and_stale_without_rejecting_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()

            future = process_ais_inbound_request(
                db_path=db_path,
                payload={
                    "request_id": "AIS-FUTURE-TIME",
                    "meter_no": "REDACTED-METER-0000",
                    "timestamp": "2999-01-01T00:00:00+07:00",
                },
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )
            stale = process_ais_inbound_request(
                db_path=db_path,
                payload={
                    "request_id": "AIS-STALE-TIME",
                    "meter_no": "REDACTED-METER-0000",
                    "timestamp": "2020-01-01T00:00:00+07:00",
                },
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )

            self.assertEqual(future.accepted_response["status"], "RECEIVED")
            self.assertEqual(stale.accepted_response["status"], "RECEIVED")
            self.assertIn(
                "future_timestamp_review",
                future.callback_payload["received"]["timestamp_quality"]["flags"],
            )
            self.assertIn(
                "stale_timestamp_review",
                stale.callback_payload["received"]["timestamp_quality"]["flags"],
            )

            report = build_ais_inbound_status_report(db_path, output=root / "status.md", limit=10)
            self.assertEqual(report["latest_request"]["timestamp_quality"]["status"], "REVIEW")
            export = build_ais_inbound_audit_export(
                db_path,
                output_csv=root / "audit.csv",
                output_markdown=root / "audit.md",
                include_smoke=True,
            )
            self.assertEqual(export["exported_rows"], 2)
            with (root / "audit.csv").open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            by_request = {row["request_id"]: row for row in rows}
            self.assertEqual(by_request["AIS-FUTURE-TIME"]["timestamp_quality_status"], "REVIEW")
            self.assertIn("future_timestamp_review", by_request["AIS-FUTURE-TIME"]["timestamp_quality_flags"])

    def test_options_allows_localtunnel_bypass_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()
            server = create_ais_inbound_server(
                db_path=db_path,
                port=0,
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                req = urllib.request.Request(
                    f"http://{host}:{port}/api/v1/ais/outage-verifications",
                    method="OPTIONS",
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    self.assertEqual(response.status, 204)
                    allow_headers = response.headers.get("Access-Control-Allow-Headers", "")
                self.assertIn("bypass-tunnel-reminder", allow_headers)
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_http_endpoint_exposes_shadow_health_without_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()
            server = create_ais_inbound_server(
                db_path=db_path,
                port=0,
                api_key="<REDACTED_SECRET>",
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=5) as response:
                    body = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(body["status"], "OK")
                self.assertEqual(body["mode"], "shadow")
                self.assertNotIn("secret-key", json.dumps(body))
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_status_lookup_requires_auth_and_returns_stored_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            _seed_runtime(db_path)
            server = create_ais_inbound_server(
                db_path=db_path,
                port=0,
                api_key="<REDACTED_SECRET>",
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                base_url = f"http://{host}:{port}/api/v1/ais/outage-verifications"
                post_req = urllib.request.Request(
                    base_url,
                    data=json.dumps(
                        {
                            "request_id": "AIS-STATUS-1",
                            "meter_no": "REDACTED-METER-0000",
                            "timestamp": "2026-06-19T10:04:00+00:00",
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json", "X-API-Key": "<REDACTED_SECRET>"},
                )
                with urllib.request.urlopen(post_req, timeout=5) as response:
                    accepted = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 202)
                self.assertEqual(accepted["result_path"], "/api/v1/ais/outage-verifications/AIS-STATUS-1")

                unauth_req = urllib.request.Request(f"{base_url}/AIS-STATUS-1")
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(unauth_req, timeout=5)
                self.assertEqual(ctx.exception.code, 401)

                auth_req = urllib.request.Request(
                    f"{base_url}/AIS-STATUS-1",
                    headers={"X-API-Key": "<REDACTED_SECRET>"},
                )
                with urllib.request.urlopen(auth_req, timeout=5) as response:
                    body = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(body["request_id"], "AIS-STATUS-1")
                self.assertEqual(body["status"], "COMPLETED")
                self.assertEqual(body["production_send"], "blocked")
                self.assertEqual(body["result"]["status"], "CONFIRMED_PEA_OUTAGE")
                self.assertNotIn("1234567890", json.dumps(body))
                self.assertIn("0000", json.dumps(body))

                bearer_req = urllib.request.Request(
                    f"{base_url}/AIS-STATUS-1",
                    headers={"Authorization": "Bearer " + "<REDACTED_SECRET>"},
                )
                with urllib.request.urlopen(bearer_req, timeout=5) as response:
                    bearer_body = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(bearer_body["request_id"], "AIS-STATUS-1")
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_contract_pack_writes_openapi_postman_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = write_ais_inbound_contract_pack(tmp, public_base="https://example.test")

            openapi = json.loads(Path(result["openapi_json"]).read_text(encoding="utf-8"))
            self.assertEqual(openapi["openapi"], "3.1.0")
            self.assertIn("/api/v1/ais/outage-verifications", openapi["paths"])
            self.assertIn("/api/v1/ais/outage-verifications/{request_id}", openapi["paths"])
            self.assertEqual(openapi["x-pea-pilot-guardrails"]["production_send"], "blocked")

            markdown = Path(result["contract_markdown"]).read_text(encoding="utf-8")
            self.assertIn("PEA AIS Outage Verification API Contract v1", markdown)
            self.assertIn("production_send", markdown)
            self.assertNotIn("token", markdown.lower())
            self.assertNotIn("room id", markdown.lower())

            postman = json.loads(Path(result["postman_collection"]).read_text(encoding="utf-8"))
            self.assertEqual(postman["variable"][0]["value"], "https://example.test")

            self.assertTrue(result["handoff_markdown"].endswith("ais_inbound_api_handoff.md"))
            self.assertTrue(result["quick_reply"].endswith("ais_inbound_quick_reply_to_ais.txt"))
            ais_facing_files = [
                result["contract_markdown"],
                result["contract_draft_markdown"],
                result["handoff_markdown"],
                result["quick_reply"],
                result["openapi_json"],
                result["openapi_yaml"],
                result["postman_collection"],
            ]
            for path in ais_facing_files:
                text = Path(path).read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"[\u0E00-\u0E7F]", text), path)
                self.assertNotIn("เธ", text, path)
                self.assertNotIn("เน", text, path)
                self.assertNotIn("_th.", path)

    def test_test_kit_is_shareable_without_private_key_or_thai_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "runtime"
            write_ais_inbound_contract_pack(source, public_base="https://pilot.example.test")
            kit_dir = root / "kit"
            zip_path = root / "kit.zip"

            result = write_ais_inbound_test_kit(
                kit_dir,
                public_base="https://pilot.example.test",
                source_dir=source,
                zip_output=zip_path,
            )

            self.assertFalse(result["contains_private_api_key"])
            self.assertTrue((kit_dir / "README.md").exists())
            self.assertTrue((kit_dir / "sample_minimal_request.json").exists())
            self.assertTrue((kit_dir / "powershell_examples.ps1").exists())
            self.assertTrue(zip_path.exists())
            with zipfile.ZipFile(zip_path) as archive:
                names = set(archive.namelist())
            self.assertIn("README.md", names)
            self.assertIn("ais_inbound_openapi.json", names)
            combined = "\n".join(
                path.read_text(encoding="utf-8")
                for path in [
                    kit_dir / "README.md",
                    kit_dir / "current_endpoint.txt",
                    kit_dir / "curl_examples.md",
                    kit_dir / "powershell_examples.ps1",
                ]
            )
            self.assertIn("https://pilot.example.test/api/v1/ais/outage-verifications", combined)
            self.assertIn("<private pilot key provided by PEA>", combined)
            self.assertNotIn("pilot-key", combined)
            self.assertIsNone(re.search(r"[\u0E00-\u0E7F]", combined))

    def test_security_audit_passes_clean_shareable_artifacts_and_fails_on_real_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime"
            private_dir = runtime / "private"
            private_dir.mkdir(parents=True)
            key_file = private_dir / "ais_inbound_pilot_key.txt"
            key_file.write_text("super-secret-pilot-key", encoding="utf-8")
            write_ais_inbound_contract_pack(runtime, public_base="https://pilot.example.test")
            write_ais_inbound_test_kit(
                runtime / "ais_inbound_test_kit",
                public_base="https://pilot.example.test",
                source_dir=runtime,
                zip_output=runtime / "ais_inbound_test_kit.zip",
            )
            (runtime / "ais_inbound_readiness_gate.md").write_text(
                "# Gate\n\n- Mode: `shadow`\n- Production send: `blocked`\n",
                encoding="utf-8",
            )
            (runtime / "ais_inbound_public_endpoint_readiness.md").write_text(
                "# Readiness\n\nPOST https://pilot.example.test/api/v1/ais/outage-verifications\n",
                encoding="utf-8",
            )
            (runtime / "ais_inbound_doc_qa.md").write_text("# QA\n\n- Status: `PASS`\n", encoding="utf-8")
            (runtime / "ais_inbound_db_snapshot_latest.md").write_text(
                "# Snapshot\n\n"
                "- Mode: `shadow`\n"
                "- Production send: `blocked`\n"
                "| `webex_messages` | 500 | 500 |\n",
                encoding="utf-8",
            )
            (runtime / "ais_inbound_db_snapshot_latest.json").write_text(
                json.dumps(
                    {
                        "mode": "shadow",
                        "production_send": "blocked",
                        "snapshot_table_counts": {"webex_messages": 500},
                        "table_counts": {"webex_messages": 500},
                    }
                ),
                encoding="utf-8",
            )

            clean = build_ais_inbound_security_audit(
                runtime,
                private_key_file=key_file,
                output_markdown=runtime / "security.md",
                output_json=runtime / "security.json",
            )

            self.assertEqual(clean["status"], "PASS")
            self.assertEqual(clean["failures"], [])
            self.assertTrue((runtime / "security.md").exists())
            self.assertNotIn("super-secret-pilot-key", (runtime / "security.md").read_text(encoding="utf-8"))

            (runtime / "ais_inbound_test_kit" / "README.md").write_text(
                "bad accidental key: super-secret-pilot-key",
                encoding="utf-8",
            )
            dirty = build_ais_inbound_security_audit(
                runtime,
                private_key_file=key_file,
                output_markdown=runtime / "security_dirty.md",
                output_json=runtime / "security_dirty.json",
            )
            self.assertEqual(dirty["status"], "FAIL")
            self.assertIn("private_pilot_key_found", "\n".join(dirty["failures"]))
            self.assertNotIn("super-secret-pilot-key", (runtime / "security_dirty.md").read_text(encoding="utf-8"))

    def test_production_migration_pack_is_english_and_keeps_production_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = write_ais_inbound_production_migration_pack(
                root,
                public_base="https://pilot.example.test",
            )

            self.assertEqual(result["production_send"], "blocked")
            self.assertEqual(result["production_approval"], "not_approved")
            self.assertIn("stable_https_endpoint", result["minimum_before_production"])
            for key in ("checklist", "runbook", "env_example", "manifest"):
                self.assertTrue(Path(result["files"][key]).exists(), key)
            combined = "\n".join(Path(path).read_text(encoding="utf-8") for path in result["files"].values())
            self.assertIn("Production must remain blocked", combined)
            self.assertIn("AIS_INBOUND_MODE=shadow", combined)
            self.assertIn("AIS_PRODUCTION_SEND=blocked", combined)
            self.assertIn("https://pilot.example.test", combined)
            self.assertNotIn("super-secret", combined)
            self.assertIsNone(re.search(r"[\u0E00-\u0E7F]", combined))

    def test_doc_qa_passes_clean_contract_pack_and_flags_leaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_ais_inbound_contract_pack(root, public_base="https://example.test")

            clean = build_ais_inbound_doc_qa(
                root,
                public_base="https://example.test",
                output=root / "doc_qa.md",
            )
            self.assertEqual(clean["status"], "PASS")
            self.assertEqual(clean["failures"], [])
            self.assertTrue((root / "doc_qa.md").exists())

            bad_doc = root / "ais_inbound_quick_reply_to_ais.txt"
            bad_doc.write_text(
                "https://stale-example.loca.lt/api\nภาษาไทย\nAuthorization: Bearer " + "test-secret-value",
                encoding="utf-8",
            )
            dirty = build_ais_inbound_doc_qa(
                root,
                public_base="https://example.test",
                output=root / "dirty_doc_qa.md",
            )
            self.assertEqual(dirty["status"], "FAIL")
            joined_failures = "\n".join(dirty["failures"])
            self.assertIn("current public host not found", joined_failures)
            self.assertIn("Thai text found", joined_failures)
            self.assertIn("stale tunnel host", joined_failures)
            self.assertIn("possible secret-bearing", joined_failures)

    def test_inbound_status_report_reads_sqlite_and_redacts_meter_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()
            process_ais_inbound_request(
                db_path=db_path,
                payload={
                    "request_id": "AIS-PUBLIC-ALIAS-SMOKE-20260620020000",
                    "meter_no": "REDACTED-METER-0000",
                    "timestamp": "2026-06-20T02:00:00+07:00",
                    "province": "Sakon Nakhon",
                    "district": "Phang Khon",
                },
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )
            process_ais_inbound_request(
                db_path=db_path,
                payload={
                    "request_id": "AIS-BEARER-SMOKE-20260620020030",
                    "meter_no": "REDACTED-METER-0000",
                    "timestamp": "2026-06-20T02:00:30+07:00",
                    "province": "Sakon Nakhon",
                    "district": "Phang Khon",
                },
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )
            process_ais_inbound_request(
                db_path=db_path,
                payload={
                    "request_id": "AIS-REAL-FROM-PARTNER-1",
                    "meter_no": "REDACTED-METER-0000",
                    "timestamp": "2026-06-20T02:01:00+07:00",
                    "province": "Sakon Nakhon",
                    "district": "Phang Khon",
                    "subdistrict": "Demo",
                },
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )

            report_path = root / "status.md"
            report = build_ais_inbound_status_report(db_path, output=report_path, limit=10)

            self.assertEqual(report["total_requests"], 3)
            self.assertEqual(report["smoke_requests"], 2)
            self.assertEqual(report["real_requests"], 1)
            self.assertEqual(report["latest_real_request"]["request_id"], "AIS-REAL-FROM-PARTNER-1")
            self.assertEqual(report["production_send"], "blocked")

            markdown = report_path.read_text(encoding="utf-8")
            self.assertIn("AIS Inbound Request Status", markdown)
            self.assertIn("AIS-REAL-FROM-PARTNER-1", markdown)
            self.assertNotIn("1234567890", markdown)
            self.assertNotIn("1122334455", markdown)
            self.assertNotIn("0987654321", markdown)
            self.assertIn("0000", markdown)

    def test_inbound_audit_export_defaults_to_real_requests_and_redacts_meters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()
            process_ais_inbound_request(
                db_path=db_path,
                payload={
                    "request_id": "AIS-PUBLIC-ALIAS-SMOKE-20260620020000",
                    "meter_no": "REDACTED-METER-0000",
                    "timestamp": "2026-06-20T02:00:00+07:00",
                    "province": "Sakon Nakhon",
                    "district": "Phang Khon",
                },
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )
            process_ais_inbound_request(
                db_path=db_path,
                payload={
                    "request_id": "AIS-REAL-FROM-PARTNER-1",
                    "meter_no": "REDACTED-METER-0000",
                    "timestamp": "2026-06-20T02:01:00+07:00",
                    "province": "=Sakon Nakhon",
                    "district": "Phang Khon",
                    "subdistrict": "Demo",
                },
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )

            output_csv = root / "audit.csv"
            output_md = root / "audit.md"
            result = build_ais_inbound_audit_export(
                db_path,
                output_csv=output_csv,
                output_markdown=output_md,
            )

            self.assertEqual(result["total_requests"], 2)
            self.assertEqual(result["real_requests"], 1)
            self.assertEqual(result["smoke_requests"], 1)
            self.assertEqual(result["exported_rows"], 1)
            with output_csv.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["request_id"], "AIS-REAL-FROM-PARTNER-1")
            self.assertEqual(rows[0]["request_type"], "real")
            self.assertEqual(rows[0]["province"], "'=Sakon Nakhon")
            self.assertEqual(rows[0]["meter_last4"], "0000")
            csv_text = output_csv.read_text(encoding="utf-8-sig")
            markdown = output_md.read_text(encoding="utf-8")
            self.assertNotIn("1234567890", csv_text + markdown)
            self.assertNotIn("0987654321", csv_text + markdown)
            self.assertNotIn("AIS-PUBLIC-ALIAS-SMOKE", csv_text)
            self.assertIn("Production send: `blocked`", markdown)

    def test_db_snapshot_backs_up_sqlite_and_reports_redacted_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()
            process_ais_inbound_request(
                db_path=db_path,
                payload={
                    "request_id": "AIS-REAL-FROM-PARTNER-1",
                    "meter_no": "REDACTED-METER-0000",
                    "timestamp": "2026-06-20T02:01:00+07:00",
                    "province": "Sakon Nakhon",
                    "district": "Phang Khon",
                },
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )

            result = build_ais_inbound_db_snapshot(
                db_path,
                output_dir=root / "snapshots",
                label="unit test",
            )

            snapshot = Path(result["snapshot_path"])
            self.assertTrue(snapshot.exists())
            self.assertEqual(result["integrity_check"], "ok")
            self.assertTrue(result["counts_match"])
            self.assertEqual(result["table_counts"]["ais_inbound_requests"], 1)
            self.assertEqual(result["snapshot_table_counts"]["ais_inbound_callbacks"], 1)
            self.assertEqual(len(result["snapshot_sha256"]), 64)
            conn = sqlite3.connect(snapshot)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM ais_inbound_requests").fetchone()[0], 1)
            finally:
                conn.close()
            markdown = Path(result["output_markdown"]).read_text(encoding="utf-8")
            public_json = Path(result["output_json"]).read_text(encoding="utf-8")
            self.assertIn("AIS-REAL-FROM-PARTNER-1", markdown)
            self.assertIn("0000", markdown)
            self.assertNotIn("0987654321", markdown + public_json)
            self.assertIn("Production send: `blocked`", markdown)

    def test_first_hit_packet_waits_then_reports_real_request_without_full_meter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()
            process_ais_inbound_request(
                db_path=db_path,
                payload={
                    "request_id": "AIS-PUBLIC-ALIAS-SMOKE-20260620020000",
                    "meter_no": "REDACTED-METER-0000",
                    "timestamp": "2026-06-20T02:00:00+07:00",
                    "province": "Sakon Nakhon",
                    "district": "Phang Khon",
                },
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )

            waiting = build_ais_inbound_first_hit_packet(
                db_path,
                output_markdown=root / "first_hit.md",
                output_json=root / "first_hit.json",
            )
            self.assertEqual(waiting["status"], "WAITING_FOR_REAL_AIS_HIT")
            self.assertEqual(waiting["real_requests"], 0)

            process_ais_inbound_request(
                db_path=db_path,
                payload={
                    "request_id": "AIS-REAL-FROM-PARTNER-1",
                    "meter_no": "REDACTED-METER-0000",
                    "timestamp": "2026-06-20T02:01:00+07:00",
                    "province": "Sakon Nakhon",
                    "district": "Phang Khon",
                    "subdistrict": "Demo",
                },
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )

            packet = build_ais_inbound_first_hit_packet(
                db_path,
                output_markdown=root / "first_hit.md",
                output_json=root / "first_hit.json",
            )
            self.assertEqual(packet["status"], "REAL_AIS_HIT_DETECTED")
            self.assertEqual(packet["real_requests"], 1)
            self.assertEqual(packet["latest_real_request"]["request_id"], "AIS-REAL-FROM-PARTNER-1")
            self.assertEqual(packet["production_send"], "blocked")

            markdown = (root / "first_hit.md").read_text(encoding="utf-8")
            json_text = (root / "first_hit.json").read_text(encoding="utf-8")
            self.assertIn("AIS-REAL-FROM-PARTNER-1", markdown)
            self.assertIn("0000", markdown)
            self.assertNotIn("0987654321", markdown + json_text)
            self.assertNotIn("1234567890", markdown + json_text)
            self.assertIn("Production send: `blocked`", markdown)

    def test_replay_callbacks_defaults_to_dry_run_and_can_send_shadow_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()
            process_ais_inbound_request(
                db_path=db_path,
                payload={
                    "request_id": "AIS-REAL-FROM-PARTNER-1",
                    "meter_no": "REDACTED-METER-0000",
                    "timestamp": "2026-06-20T02:01:00+07:00",
                    "province": "Sakon Nakhon",
                    "district": "Phang Khon",
                },
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )
            conn = sqlite3.connect(db_path)
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM ais_inbound_callbacks")
                before_count = cursor.fetchone()[0]
                cursor.close()
            finally:
                conn.close()

            dry_run = replay_ais_inbound_callbacks(
                db_path,
                callback_url="http://127.0.0.1:1/callback",
                callbacks_output=root / "callbacks.jsonl",
                dry_run=True,
            )
            self.assertEqual(dry_run["dry_run"], True)
            self.assertEqual(dry_run["candidate_count"], 1)
            self.assertEqual(dry_run["results"][0]["replay_status"], "DRY_RUN")
            conn = sqlite3.connect(db_path)
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM ais_inbound_callbacks")
                self.assertEqual(cursor.fetchone()[0], before_count)
                cursor.close()
            finally:
                conn.close()

            received: list[dict] = []
            server = HTTPServer(("127.0.0.1", 0), _CallbackCaptureHandler)
            server.received = received  # type: ignore[attr-defined]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                sent = replay_ais_inbound_callbacks(
                    db_path,
                    callback_url=f"http://{host}:{port}/callback",
                    callbacks_output=root / "callbacks.jsonl",
                    dry_run=False,
                )
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertEqual(sent["dry_run"], False)
            self.assertEqual(sent["results"][0]["replay_status"], "SENT")
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0]["mode"], "shadow")
            self.assertEqual(received[0]["decision"]["production_send"], "blocked")
            self.assertNotIn("0987654321", json.dumps(received[0]))
            conn = sqlite3.connect(db_path)
            try:
                cursor = conn.execute("SELECT status, status_code FROM ais_inbound_callbacks ORDER BY id")
                rows = cursor.fetchall()
                cursor.close()
            finally:
                conn.close()
            self.assertEqual(rows[-1][0], "SENT")
            self.assertEqual(rows[-1][1], 200)
            gc.collect()

    def test_http_endpoint_returns_controlled_errors_for_bad_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()
            server = create_ais_inbound_server(
                db_path=db_path,
                port=0,
                api_key="<REDACTED_SECRET>",
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                url = f"http://{host}:{port}/api/v1/ais/outage-verifications"

                cases = [
                    (
                        urllib.request.Request(
                            url,
                            data=json.dumps(
                                {
                                    "request_id": "BAD-NO-CONTENT-TYPE",
                                    "meter_no": "123",
                                    "timestamp": "2026-06-19T10:04:00+00:00",
                                }
                            ).encode("utf-8"),
                            method="POST",
                            headers={"X-API-Key": "<REDACTED_SECRET>"},
                        ),
                        415,
                        "UNSUPPORTED_MEDIA_TYPE",
                    ),
                    (
                        urllib.request.Request(
                            url,
                            data=b"{not-json",
                            method="POST",
                            headers={"Content-Type": "application/json", "X-API-Key": "<REDACTED_SECRET>"},
                        ),
                        400,
                        "INVALID_JSON",
                    ),
                    (
                        urllib.request.Request(
                            url,
                            data=json.dumps({"request_id": "BAD-1", "meter_no": "123"}).encode("utf-8"),
                            method="POST",
                            headers={"Content-Type": "application/json", "X-API-Key": "<REDACTED_SECRET>"},
                        ),
                        400,
                        "INVALID_REQUEST",
                    ),
                    (
                        urllib.request.Request(
                            url,
                            data=json.dumps(
                                {
                                    "request_id": "BAD-2",
                                    "meter_no": "123",
                                    "timestamp": "not-a-time",
                                }
                            ).encode("utf-8"),
                            method="POST",
                            headers={"Content-Type": "application/json", "X-API-Key": "<REDACTED_SECRET>"},
                        ),
                        400,
                        "INVALID_REQUEST",
                    ),
                    (
                        urllib.request.Request(
                            url,
                            data=json.dumps(
                                {
                                    "request_id": "BAD-3",
                                    "meter_no": "123",
                                    "timestamp": "2026-06-19T10:04:00+00:00",
                                }
                            ).encode("utf-8"),
                            method="POST",
                            headers={"Content-Type": "text/plain", "X-API-Key": "<REDACTED_SECRET>"},
                        ),
                        415,
                        "UNSUPPORTED_MEDIA_TYPE",
                    ),
                    (
                        urllib.request.Request(
                            url,
                            data=b" " * 1_000_001,
                            method="POST",
                            headers={"Content-Type": "application/json", "X-API-Key": "<REDACTED_SECRET>"},
                        ),
                        413,
                        "PAYLOAD_TOO_LARGE",
                    ),
                    (
                        urllib.request.Request(
                            url,
                            data=json.dumps(
                                {
                                    "request_id": "BAD/SLASH",
                                    "meter_no": "123",
                                    "timestamp": "2026-06-19T10:04:00+00:00",
                                }
                            ).encode("utf-8"),
                            method="POST",
                            headers={"Content-Type": "application/json", "X-API-Key": "<REDACTED_SECRET>"},
                        ),
                        400,
                        "INVALID_REQUEST",
                    ),
                    (
                        urllib.request.Request(
                            url,
                            data=json.dumps(
                                {
                                    "request_id": "A" * 129,
                                    "meter_no": "123",
                                    "timestamp": "2026-06-19T10:04:00+00:00",
                                }
                            ).encode("utf-8"),
                            method="POST",
                            headers={"Content-Type": "application/json", "X-API-Key": "<REDACTED_SECRET>"},
                        ),
                        400,
                        "INVALID_REQUEST",
                    ),
                    (
                        urllib.request.Request(
                            url,
                            data=json.dumps(
                                {
                                    "request_id": "BAD-METER-LONG",
                                    "meter_no": "9" * 65,
                                    "timestamp": "2026-06-19T10:04:00+00:00",
                                }
                            ).encode("utf-8"),
                            method="POST",
                            headers={"Content-Type": "application/json", "X-API-Key": "<REDACTED_SECRET>"},
                        ),
                        400,
                        "INVALID_REQUEST",
                    ),
                    (
                        urllib.request.Request(
                            url,
                            data=json.dumps(
                                {
                                    "request_id": "BAD-AREA-LONG",
                                    "meter_no": "123",
                                    "timestamp": "2026-06-19T10:04:00+00:00",
                                    "district": "A" * 121,
                                }
                            ).encode("utf-8"),
                            method="POST",
                            headers={"Content-Type": "application/json", "X-API-Key": "<REDACTED_SECRET>"},
                        ),
                        400,
                        "INVALID_REQUEST",
                    ),
                ]

                for request, expected_http, expected_code in cases:
                    with self.subTest(expected_code=expected_code):
                        with self.assertRaises(urllib.error.HTTPError) as ctx:
                            urllib.request.urlopen(request, timeout=5)
                        self.assertEqual(ctx.exception.code, expected_http)
                        body = json.loads(ctx.exception.read().decode("utf-8"))
                        self.assertEqual(body["status"], "ERROR")
                        self.assertEqual(body["error"]["code"], expected_code)
                        self.assertEqual(body["production_send"], "blocked")
                        self.assertNotIn("Traceback", json.dumps(body))
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_http_endpoint_rate_limits_bursts_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()
            server = create_ais_inbound_server(
                db_path=db_path,
                port=0,
                api_key="<REDACTED_SECRET>",
                requests_output=root / "requests.jsonl",
                callbacks_output=root / "callbacks.jsonl",
                post_callback=False,
                rate_limit_per_minute=2,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                url = f"http://{host}:{port}/api/v1/ais/outage-verifications"
                for index in range(2):
                    request = urllib.request.Request(
                        url,
                        data=json.dumps(
                            {
                                "request_id": f"RATE-OK-{index}",
                                "meter_no": "123",
                                "timestamp": "2026-06-19T10:04:00+00:00",
                            }
                        ).encode("utf-8"),
                        method="POST",
                        headers={"Content-Type": "application/json", "X-API-Key": "<REDACTED_SECRET>"},
                    )
                    with urllib.request.urlopen(request, timeout=5) as response:
                        body = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 202)
                    self.assertEqual(body["status"], "RECEIVED")

                blocked = urllib.request.Request(
                    url,
                    data=json.dumps(
                        {
                            "request_id": "RATE-BLOCKED",
                            "meter_no": "123",
                            "timestamp": "2026-06-19T10:04:00+00:00",
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json", "X-API-Key": "<REDACTED_SECRET>"},
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(blocked, timeout=5)
                self.assertEqual(ctx.exception.code, 429)
                self.assertTrue(ctx.exception.headers.get("Retry-After"))
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertEqual(body["status"], "ERROR")
                self.assertEqual(body["error"]["code"], "RATE_LIMITED")
                self.assertEqual(body["production_send"], "blocked")
                self.assertNotIn("Traceback", json.dumps(body))
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_readiness_gate_allows_pilot_test_but_blocks_production_without_real_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()
            status_file = root / "status.json"
            verification_file = root / "verification.json"
            doc_qa_file = root / "doc_qa.md"
            security_audit_file = root / "security_audit.json"
            first_hit_file = root / "first_hit.json"
            db_snapshot_file = root / "db_snapshot.json"
            status_file.write_text(
                json.dumps(
                    {
                        "mode": "shadow",
                        "production_send": "blocked",
                        "primary_public_url": "https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications",
                        "primary_health_url": "https://<REDACTED_TUNNEL>/health",
                        "primary_health_smoke": "200_OK",
                    }
                ),
                encoding="utf-8",
            )
            verification_file.write_text(
                json.dumps(
                    {
                        "mode": "shadow",
                        "production_send": "blocked",
                        "public_url": "https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications",
                        "health_url": "https://<REDACTED_TUNNEL>/health",
                        "all_checks_ok": True,
                        "checks": [{"name": "health", "ok": True}],
                    }
                ),
                encoding="utf-8",
            )
            doc_qa_file.write_text("# QA\n\n- Status: `PASS`\n", encoding="utf-8")
            security_audit_file.write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "mode": "shadow",
                        "production_send": "blocked",
                        "failures": [],
                    }
                ),
                encoding="utf-8",
            )
            first_hit_file.write_text(
                json.dumps({"mode": "shadow", "production_send": "blocked", "real_requests": 0}),
                encoding="utf-8",
            )
            db_snapshot_file.write_text(
                json.dumps(
                    {
                        "mode": "shadow",
                        "production_send": "blocked",
                        "integrity_check": "ok",
                        "counts_match": True,
                        "snapshot_path": str(root / "snapshot.sqlite"),
                        "snapshot_sha256": "a" * 64,
                    }
                ),
                encoding="utf-8",
            )

            result = build_ais_inbound_readiness_gate(
                db_path,
                status_file=status_file,
                verification_file=verification_file,
                doc_qa_file=doc_qa_file,
                security_audit_file=security_audit_file,
                first_hit_file=first_hit_file,
                db_snapshot_file=db_snapshot_file,
                output_markdown=root / "gate.md",
                output_json=root / "gate.json",
            )

            self.assertEqual(result["pilot_test_status"], "READY_FOR_AIS_TEST")
            self.assertEqual(result["production_status"], "BLOCKED_WAITING_FOR_REAL_AIS_HIT")
            self.assertEqual(result["pilot_api_test_readiness_percent"], 100)
            self.assertEqual(result["real_requests"], 0)
            first_hit_check = next(check for check in result["checks"] if check["name"] == "first_real_ais_hit")
            self.assertEqual(first_hit_check["status"], "WARN")
            snapshot_check = next(check for check in result["checks"] if check["name"] == "db_snapshot_evidence")
            self.assertEqual(snapshot_check["status"], "PASS")
            security_check = next(check for check in result["checks"] if check["name"] == "security_audit")
            self.assertEqual(security_check["status"], "PASS")
            markdown = (root / "gate.md").read_text(encoding="utf-8")
            self.assertIn("READY_FOR_AIS_TEST", markdown)
            self.assertIn("Production send: `blocked`", markdown)
            self.assertNotIn("X-API-Key", markdown)

    def test_readiness_gate_fails_when_public_verifier_is_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()
            status_file = root / "status.json"
            verification_file = root / "verification.json"
            doc_qa_file = root / "doc_qa.md"
            first_hit_file = root / "first_hit.json"
            status_file.write_text(
                json.dumps(
                    {
                        "mode": "shadow",
                        "production_send": "blocked",
                        "primary_public_url": "https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications",
                        "primary_health_url": "https://<REDACTED_TUNNEL>/health",
                        "primary_health_smoke": "DOWN",
                    }
                ),
                encoding="utf-8",
            )
            verification_file.write_text(json.dumps({"all_checks_ok": False, "checks": []}), encoding="utf-8")
            doc_qa_file.write_text("# QA\n\n- Status: `PASS`\n", encoding="utf-8")
            first_hit_file.write_text(json.dumps({"real_requests": 1}), encoding="utf-8")

            result = build_ais_inbound_readiness_gate(
                db_path,
                status_file=status_file,
                verification_file=verification_file,
                doc_qa_file=doc_qa_file,
                first_hit_file=first_hit_file,
                output_markdown=root / "gate.md",
                output_json=root / "gate.json",
            )

            self.assertEqual(result["pilot_test_status"], "NOT_READY_FOR_AIS_TEST")
            self.assertEqual(result["production_status"], "BLOCKED_TECHNICAL_FAILURE")
            failed = {check["name"] for check in result["checks"] if check["status"] == "FAIL"}
            self.assertIn("health_smoke", failed)
            self.assertIn("public_verifier", failed)

    def test_readiness_gate_fails_when_security_audit_is_not_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.sqlite"
            RuntimeDb(db_path).init()
            status_file = root / "status.json"
            verification_file = root / "verification.json"
            doc_qa_file = root / "doc_qa.md"
            security_audit_file = root / "security_audit.json"
            first_hit_file = root / "first_hit.json"
            db_snapshot_file = root / "db_snapshot.json"
            status_file.write_text(
                json.dumps(
                    {
                        "mode": "shadow",
                        "production_send": "blocked",
                        "primary_public_url": "https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications",
                        "primary_health_url": "https://<REDACTED_TUNNEL>/health",
                        "primary_health_smoke": "200_OK",
                    }
                ),
                encoding="utf-8",
            )
            verification_file.write_text(
                json.dumps(
                    {
                        "mode": "shadow",
                        "production_send": "blocked",
                        "public_url": "https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications",
                        "health_url": "https://<REDACTED_TUNNEL>/health",
                        "all_checks_ok": True,
                        "checks": [{"name": "health", "ok": True}],
                    }
                ),
                encoding="utf-8",
            )
            doc_qa_file.write_text("# QA\n\n- Status: `PASS`\n", encoding="utf-8")
            security_audit_file.write_text(
                json.dumps(
                    {
                        "status": "FAIL",
                        "mode": "shadow",
                        "production_send": "blocked",
                        "failures": ["ais_inbound_test_kit.zip: private_pilot_key_found"],
                    }
                ),
                encoding="utf-8",
            )
            first_hit_file.write_text(
                json.dumps({"mode": "shadow", "production_send": "blocked", "real_requests": 0}),
                encoding="utf-8",
            )
            db_snapshot_file.write_text(
                json.dumps(
                    {
                        "mode": "shadow",
                        "production_send": "blocked",
                        "integrity_check": "ok",
                        "counts_match": True,
                        "snapshot_path": str(root / "snapshot.sqlite"),
                        "snapshot_sha256": "a" * 64,
                    }
                ),
                encoding="utf-8",
            )

            result = build_ais_inbound_readiness_gate(
                db_path,
                status_file=status_file,
                verification_file=verification_file,
                doc_qa_file=doc_qa_file,
                security_audit_file=security_audit_file,
                first_hit_file=first_hit_file,
                db_snapshot_file=db_snapshot_file,
                output_markdown=root / "gate.md",
                output_json=root / "gate.json",
            )

            self.assertEqual(result["pilot_test_status"], "NOT_READY_FOR_AIS_TEST")
            self.assertEqual(result["production_status"], "BLOCKED_TECHNICAL_FAILURE")
            security_check = next(check for check in result["checks"] if check["name"] == "security_audit")
            self.assertEqual(security_check["status"], "FAIL")

    def test_unattended_real_hit_watcher_is_not_shipped(self):
        self.assertFalse(Path("runtime/watch_ais_inbound_real_hit.ps1").exists())


def _seed_runtime(db_path: Path) -> None:
    db = RuntimeDb(db_path)
    db.init()
    db.upsert_customer_assets(
        [
            CustomerAsset(
                peano="REDACTED-METER-0000",
                customer="AIS",
                feeder="PFA03",
                cb_ids=("PFA03VB-01",),
                trace_status="OK",
                confidence_eligible=True,
            )
        ]
    )
    event = OutageEvent(
        event_id="event-1",
        source="webex",
        webex_message_id="msg-1",
        room_id="<REDACTED_ROOM_ID>",
        raw_text="test",
        outage_device=OutageDevice(device_type="CB", device_id="PFA03VB-01", feeder="PFA03"),
        event_time="2026-06-19T10:00:00+00:00",
    )
    db.upsert_event(event)
    match = MatchResult(
        matches=(CustomerMatch(customer="AIS", peano="REDACTED-METER-0000", feeder="PFA03", match_level="cb"),),
        match_level="cb",
        match_confidence=0.95,
    )
    db.insert_prediction(
        event.event_id,
        Prediction(
            etr_minutes_p50=45,
            q25=32,
            q75=68,
            q10=20,
            q90=95,
            risk_level="LOW",
            model_version="test-model",
        ),
        match,
    )


class _CallbackCaptureHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        self.server.received.append(json.loads(body))  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    unittest.main()
