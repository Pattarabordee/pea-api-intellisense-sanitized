import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ais_etr.production_path import build_production_readiness_gate, export_sanitized_codebase


class ProductionPathTests(unittest.TestCase):
    def test_sanitized_codebase_export_excludes_runtime_secrets_and_redacts_identifiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ais_etr").mkdir()
            (root / "tests").mkdir()
            (root / "runtime" / "private").mkdir(parents=True)
            (root / "runtime" / "cloud_pilot").mkdir(parents=True)
            (root / "AGENTS.md").write_text("rules", encoding="utf-8")
            (root / "ais_etr" / "service.py").write_text(
                'PAYLOAD = {"meter_no": "<REDACTED_METER_REF>", "roomId": "<REDACTED_ROOM_ID>"}\n',
                encoding="utf-8",
            )
            (root / "tests" / "test_service.py").write_text("def test_ok(): pass\n", encoding="utf-8")
            (root / "runtime" / "ais_inbound_api_contract_v1.md").write_text(
                "POST /api/v1/ais/outage-verifications\n",
                encoding="utf-8",
            )
            (root / "runtime" / "pea_api_intellisense_technical_brief.md").write_text(
                "mode = shadow\nproduction_send = blocked\n",
                encoding="utf-8",
            )
            (root / "runtime" / "pea_api_intellisense_pitch_answers.md").write_text(
                "planning scenario / strategic estimate\n",
                encoding="utf-8",
            )
            (root / "runtime" / "private" / "ais_inbound_pilot_key.txt").write_text(
                "DO_NOT_EXPORT",
                encoding="utf-8",
            )
            (root / "runtime" / "ais_etr.sqlite").write_bytes(b"sqlite")
            (root / "runtime" / "ais_inbound_callbacks.jsonl").write_text(
                '{"access_token": "<REDACTED_SECRET>"}\n',
                encoding="utf-8",
            )
            (root / "runtime" / "cloud_pilot" / "README.md").write_text(
                "cloud package",
                encoding="utf-8",
            )

            manifest = export_sanitized_codebase(root)

            self.assertEqual(manifest["status"], "PASS")
            self.assertGreaterEqual(manifest["redaction_count"], 2)
            self.assertTrue((root / "runtime" / "sanitized_codebase_bundle.zip").exists())
            with zipfile.ZipFile(root / "runtime" / "sanitized_codebase_bundle.zip") as archive:
                names = set(archive.namelist())
                self.assertIn("ais_etr/service.py", names)
                self.assertIn("tests/test_service.py", names)
                self.assertIn("runtime/pea_api_intellisense_technical_brief.md", names)
                self.assertIn("runtime/pea_api_intellisense_pitch_answers.md", names)
                self.assertNotIn("runtime/private/ais_inbound_pilot_key.txt", names)
                self.assertNotIn("runtime/ais_etr.sqlite", names)
                service_text = archive.read("ais_etr/service.py").decode("utf-8")
            self.assertNotIn("1234567890", service_text)
            self.assertNotIn("room-secret", service_text)
            self.assertIn("<REDACTED_METER_REF>", service_text)

    def test_production_readiness_gate_blocks_auto_etr_until_green_and_owner_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cloud = root / "runtime" / "cloud_pilot"
            cloud.mkdir(parents=True)
            for name in [
                "Dockerfile",
                "docker-compose.yml",
                "README.md",
                "cloud_operator_runbook.md",
                "incident_playbook.md",
                "monitoring_policy.md",
                "backup_restore_commands.md",
            ]:
                (cloud / name).write_text("ok", encoding="utf-8")
            (cloud / ".env.cloud.example").write_text(
                "AIS_INBOUND_API_KEY="<REDACTED_SECRET>",
                encoding="utf-8",
            )
            (root / "runtime" / "sanitized_codebase_manifest.json").write_text(
                json.dumps({"status": "PASS", "zip_output": "bundle.zip"}),
                encoding="utf-8",
            )
            (root / "runtime" / "pilot_completion_gate.json").write_text(
                json.dumps({"pilot_complete_status": "PILOT_COMPLETE", "production_send": "blocked"}),
                encoding="utf-8",
            )
            (root / "runtime" / "green_gate_tracker.md").write_text(
                "Current green rows: 0\nGate status: blocked_too_few_green_rows\n",
                encoding="utf-8",
            )
            (root / "runtime" / "production_readiness_gate.md").write_text(
                "Status: blocked_no_green_subset\n",
                encoding="utf-8",
            )

            report = build_production_readiness_gate(root)

            self.assertEqual(report["production_send"], "blocked")
            self.assertEqual(report["cloud_endpoint_ready"], "READY_FOR_DEPLOYMENT_PACKAGE")
            self.assertEqual(report["production_infra_ready"], "BLOCKED_PENDING_OWNER_OR_CONTROL")
            self.assertEqual(report["auto_etr_ready"], "BLOCKED_GREEN_GATE")
            status_by_name = {check["name"]: check["status"] for check in report["checks"]}
            self.assertEqual(status_by_name["owner_approval"], "BLOCKED")
            self.assertEqual(status_by_name["green_auto_etr_gate"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
