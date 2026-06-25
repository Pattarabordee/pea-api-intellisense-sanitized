import base64
import csv
import hmac
import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
import zipfile
from pathlib import Path

from ais_etr.config import Settings
from ais_etr.db import RuntimeDb
from ais_etr.line_ingest import (
    LineIngestError,
    build_line_training_corpus,
    create_line_webhook_server,
    import_line_history_export,
    normalize_line_webhook_event,
    process_line_webhook_body,
    verify_line_signature,
)
from ais_etr.pipeline import AisEtrPipeline
from ais_etr.schemas import CustomerAsset


class LineIngestTests(unittest.TestCase):
    def test_line_signature_validates_exact_body(self):
        secret = "line-secret"
        body = b'{"events":[]}'
        signature = base64.b64encode(hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()).decode("ascii")

        self.assertTrue(verify_line_signature(body, signature, secret))
        self.assertFalse(verify_line_signature(body + b" ", signature, secret))
        self.assertFalse(verify_line_signature(body, "bad", secret))

    def test_webhook_accepts_only_allowlisted_text_group_and_hashes_ids(self):
        event = _line_event(
            group_id="C1234567890abcdef1234567890abcdef",
            user_id="U1234567890abcdef1234567890abcdef",
            text="Recloser PFA02VR-101 trip outage https://example.invalid operator@example.com 0812345678",
        )

        record = normalize_line_webhook_event(event, allowed_group_ids=("C1234567890abcdef1234567890abcdef",))

        self.assertEqual(record["source"], "line")
        self.assertEqual(record["source_kind"], "line")
        self.assertNotIn("C1234567890abcdef", json.dumps(record))
        self.assertNotIn("U1234567890abcdef", json.dumps(record))
        self.assertIn("url", record["raw_redaction_flags"])
        self.assertIn("email", record["raw_redaction_flags"])
        self.assertIn("phone", record["raw_redaction_flags"])

        with self.assertRaises(LineIngestError):
            normalize_line_webhook_event(event, allowed_group_ids=("Cother",))

    def test_webhook_accepts_hash_allowlisted_group_without_raw_group_id_config(self):
        event = _line_event(group_id="Cgroup-never-stored-raw")
        chat_hash = "chat_" + hashlib.sha256("Cgroup-never-stored-raw".encode("utf-8")).hexdigest()[:16]

        record = normalize_line_webhook_event(event, allowed_group_ids=(), allowed_chat_hashes=(chat_hash,))

        self.assertEqual(record["chat_id_hash"], chat_hash)
        self.assertNotIn("Cgroup-never-stored-raw", json.dumps(record))

    def test_process_webhook_rejects_bad_signature_and_writes_sanitized_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = "line-secret"
            body = json.dumps({"events": [_line_event(text="Recloser PFA02VR-101 trip outage")]}).encode("utf-8")
            signature = base64.b64encode(hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()).decode("ascii")

            result = process_line_webhook_body(
                body,
                signature,
                secret,
                allowed_group_ids=("Cgroup",),
                output_jsonl=root / "capture.jsonl",
                output_sqlite=root / "capture.sqlite",
            )

            self.assertEqual(result["accepted"], 1)
            self.assertEqual(result["sqlite_inserted"], 1)
            rows = [json.loads(line) for line in (root / "capture.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["message_id"], "line-msg-1")
            conn = sqlite3.connect(root / "capture.sqlite")
            try:
                stored = conn.execute(
                    "SELECT event_json, mode, production_send FROM line_webhook_capture"
                ).fetchone()
            finally:
                conn.close()
            self.assertIsNotNone(stored)
            self.assertNotIn("Cgroup", stored[0])
            self.assertNotIn("Uuser", stored[0])
            self.assertEqual(stored[1], "shadow")
            self.assertEqual(stored[2], "blocked")

            with self.assertRaises(LineIngestError):
                process_line_webhook_body(body, "bad", secret, ("Cgroup",), root / "bad.jsonl")

    def test_webhook_health_endpoint_is_render_ready(self):
        server = create_line_webhook_server(
            "127.0.0.1",
            0,
            channel_secret="line-secret",
            allowed_group_ids=("Cgroup",),
            output_jsonl="runtime/test_line_capture.jsonl",
            output_sqlite="runtime/test_line_capture.sqlite",
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/health"
            with urllib.request.urlopen(url, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["mode"], "shadow")
            self.assertEqual(payload["production_send"], "blocked")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_manual_export_requires_approval_and_redacts_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "line.csv"
            with source.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["id", "created", "chat_id", "sender", "text"])
                writer.writeheader()
                writer.writerow(
                    {
                        "id": "m1",
                        "created": "2026-06-23T08:00:00+07:00",
                        "chat_id": "CroomSecret",
                        "sender": "Somchai Operator",
                        "text": "PEANO 6101,6102 Recloser PFA02VR-101 trip outage 0123456789 operator@example.com",
                    }
                )
            missing_approval = root / "missing_approval.json"
            missing_approval.write_text(
                json.dumps(_manifest(source_type="line", approved=False), ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(LineIngestError):
                import_line_history_export(source, missing_approval, root / "out.jsonl")

            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(_manifest(source_type="line"), ensure_ascii=False), encoding="utf-8")
            result = import_line_history_export(source, manifest, root / "out.jsonl")

            self.assertEqual(result["records_exported"], 1)
            raw_output = (root / "out.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("CroomSecret", raw_output)
            self.assertNotIn("Somchai", raw_output)
            self.assertNotIn("0123456789", raw_output)
            self.assertNotIn("operator@example.com", raw_output)
            row = json.loads(raw_output)
            self.assertEqual(row["source_kind"], "line")
            self.assertIn("meter_context", row["raw_redaction_flags"])

    def test_openchat_manual_export_requires_department_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "openchat.jsonl"
            source.write_text(json.dumps({"id": "m1", "text": "Recloser PFA02VR-101 trip outage"}) + "\n", encoding="utf-8")

            blocked_manifest = root / "blocked.json"
            blocked_manifest.write_text(
                json.dumps(_manifest(source_type="line_openchat_export", department_controlled=False), ensure_ascii=False),
                encoding="utf-8",
            )
            blocked = import_line_history_export(source, blocked_manifest, root / "blocked_out.jsonl")
            self.assertEqual(blocked["status"], "blocked_needs_owner_approval")
            self.assertEqual((root / "blocked_out.jsonl").read_text(encoding="utf-8"), "")

            ok_manifest = root / "ok.json"
            ok_manifest.write_text(
                json.dumps(_manifest(source_type="line_openchat_export", department_controlled=True), ensure_ascii=False),
                encoding="utf-8",
            )
            result = import_line_history_export(source, ok_manifest, root / "openchat_out.jsonl")
            self.assertEqual(result["records_exported"], 1)
            row = json.loads((root / "openchat_out.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(row["source_kind"], "line_openchat_export")

    def test_line_text_export_imports_multiline_and_skips_system_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "line_export.txt"
            source.write_text(
                "\n".join(
                    [
                        "[LINE] Approved group Chat history",
                        "2026.06.23 Tuesday",
                        "09:01\tSomchai Operator\tRecloser PFA02VR-101 trip outage 0812345678 @Tom Nittawat contact name: Jane Doe phone 065-391-4393",
                        "continued detail with PEANO 6101,6102 and 065-391-4393",
                        "09:02\tLINE\tBob joined the group",
                    ]
                ),
                encoding="utf-8",
            )
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps({**_manifest(source_type="line"), "chat_name": "approved-department-group"}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = import_line_history_export(source, manifest, root / "out.jsonl")

            self.assertEqual(result["records_read"], 1)
            self.assertEqual(result["records_exported"], 1)
            raw_output = (root / "out.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("Somchai", raw_output)
            self.assertNotIn("0812345678", raw_output)
            self.assertNotIn("065-391-4393", raw_output)
            self.assertNotIn("Tom", raw_output)
            self.assertNotIn("Nittawat", raw_output)
            self.assertNotIn("Jane Doe", raw_output)
            self.assertNotIn("6101,6102", raw_output)
            self.assertNotIn("approved-department-group", raw_output)
            row = json.loads(raw_output)
            self.assertIn("continued detail", row["text_sanitized"])
            self.assertIn("phone", row["raw_redaction_flags"])
            self.assertIn("mention", row["raw_redaction_flags"])
            self.assertIn("person_name", row["raw_redaction_flags"])
            self.assertIn("meter_context", row["raw_redaction_flags"])
            self.assertTrue(row["chat_id_hash"].startswith("chat_"))

    def test_line_text_export_skips_media_file_and_admin_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "line_export.txt"
            photo = "\u0e23\u0e39\u0e1b"
            sticker = "\u0e2a\u0e15\u0e34\u0e01\u0e40\u0e01\u0e2d\u0e23\u0e4c"
            time_record_notice = (
                "\u0e41\u0e08\u0e49\u0e07\u0e40\u0e15\u0e37\u0e2d\u0e19: "
                "\u0e23\u0e30\u0e1a\u0e1a\u0e25\u0e07\u0e40\u0e27\u0e25\u0e32\u0e1b"
                "\u0e0f\u0e34\u0e1a\u0e31\u0e15\u0e34\u0e07\u0e32\u0e19"
            )
            source.write_text(
                "\n".join(
                    [
                        "[LINE] Approved group Chat history",
                        "2026.06.23 Tuesday",
                        f"09:00\tOperator A\t{photo}",
                        f"09:01\tOperator A\t{sticker}",
                        "09:02\tOperator A\tcrew_report.pdf",
                        f"09:03\tUnknown\t{time_record_notice}",
                        "Link URL :",
                        "https://example.invalid",
                        "Created by IT_PKN",
                        "09:04\tOperator A\tRecloser PFA02VR-101 trip outage",
                    ]
                ),
                encoding="utf-8",
            )
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps({**_manifest(source_type="line"), "chat_name": "approved-department-group"}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = import_line_history_export(source, manifest, root / "out.jsonl")

            self.assertEqual(result["records_read"], 1)
            self.assertEqual(result["records_exported"], 1)
            raw_output = (root / "out.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("crew_report.pdf", raw_output)
            self.assertNotIn("example.invalid", raw_output)
            row = json.loads(raw_output)
            self.assertEqual(row["text_sanitized"], "Recloser PFA02VR-101 trip outage")

    def test_line_text_export_imports_single_space_messages_without_sender_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "line_export.txt"
            photo = "\u0e23\u0e39\u0e1b"
            outage = "\u0e44\u0e1f\u0e14\u0e31\u0e1a"
            time_record_notice = (
                "\u0e41\u0e08\u0e49\u0e07\u0e40\u0e15\u0e37\u0e2d\u0e19: "
                "\u0e23\u0e30\u0e1a\u0e1a\u0e25\u0e07\u0e40\u0e27\u0e25\u0e32\u0e1b"
                "\u0e0f\u0e34\u0e1a\u0e31\u0e15\u0e34\u0e07\u0e32\u0e19"
            )
            source.write_text(
                "\n".join(
                    [
                        "2026.06.23 Tuesday",
                        f"09:00 Operator A {photo}",
                        "09:01 Operator A Recloser PFA02VR-101 trip outage",
                        "09:02 Operator A crew_report.pdf",
                        f"09:03 Unknown {time_record_notice}",
                        f"09:04 New Sender {outage} transformer area",
                        "09:05 New Sender routine chat without operational signal",
                    ]
                ),
                encoding="utf-8",
            )
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps({**_manifest(source_type="line"), "chat_name": "approved-department-group"}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = import_line_history_export(source, manifest, root / "out.jsonl")

            self.assertEqual(result["records_read"], 2)
            self.assertEqual(result["records_exported"], 2)
            raw_output = (root / "out.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("Operator A", raw_output)
            self.assertNotIn("New Sender", raw_output)
            self.assertNotIn("crew_report.pdf", raw_output)
            rows = [json.loads(line) for line in raw_output.splitlines()]
            self.assertEqual(rows[0]["text_sanitized"], "Recloser PFA02VR-101 trip outage")
            self.assertTrue(rows[1]["text_sanitized"].startswith(outage))

    def test_line_zip_export_imports_text_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "line_export.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr(
                    "chat.txt",
                    "2026/06/23 Tuesday\n09:01\tOperator A\tRecloser PFA02VR-101 trip outage\n",
                )
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(_manifest(source_type="line"), ensure_ascii=False), encoding="utf-8")

            result = import_line_history_export(source, manifest, root / "out.jsonl")

            self.assertEqual(result["records_exported"], 1)
            row = json.loads((root / "out.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(row["source_kind"], "line")
            self.assertIn("PFA02VR-101", row["text_sanitized"])

    def test_build_training_corpus_uses_hash_refs_and_redaction_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "line_normalized.jsonl"
            normalized = {
                "source": "line",
                "source_kind": "line",
                "message_id": "line-m1",
                "created": "2026-06-23T08:00:00+00:00",
                "text_sanitized": "Recloser PFA02VR-101 trip outage 0123456789 065-391-4393 operator@example.com @Tom Nittawat contact name: Jane Doe phone 0812345678",
                "chat_id_hash": "chat_safehash",
                "sender_hash": "sender_safehash",
                "roomDistrict": "Phang Khon",
                "consent_manifest_id": "manifest-1",
                "raw_redaction_flags": [],
            }
            source.write_text(json.dumps(normalized, ensure_ascii=False) + "\n" + json.dumps(normalized, ensure_ascii=False) + "\n", encoding="utf-8-sig")

            result = build_line_training_corpus(
                [source],
                output=root / "corpus.jsonl",
                audit_output=root / "audit.csv",
                markdown_output=root / "report.md",
                districts=("Phang Khon",),
            )

            self.assertEqual(result["rows_read"], 2)
            self.assertEqual(result["rows_written"], 1)
            self.assertEqual(result["duplicates"], 1)
            self.assertEqual(result["status"], "ok")
            raw_corpus = (root / "corpus.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("line-m1", raw_corpus)
            self.assertNotIn("0123456789", raw_corpus)
            self.assertNotIn("065-391-4393", raw_corpus)
            self.assertNotIn("operator@example.com", raw_corpus)
            self.assertNotIn("Tom", raw_corpus)
            self.assertNotIn("Nittawat", raw_corpus)
            self.assertNotIn("Jane Doe", raw_corpus)
            row = json.loads(raw_corpus)
            self.assertTrue(row["message_ref"].startswith("msg_"))
            self.assertEqual(row["parser_candidate"]["status"], "parsed")
            self.assertEqual(row["parser_candidate"]["device_id"], "PFA02VR-101")
            self.assertIn("phone", row["raw_redaction_flags"])
            self.assertIn("email", row["raw_redaction_flags"])
            self.assertIn("mention", row["raw_redaction_flags"])
            self.assertIn("person_name", row["raw_redaction_flags"])
            self.assertIn("Status: `PASS`", (root / "report.md").read_text(encoding="utf-8"))

    def test_replay_sanitized_line_history_captures_shadow_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "line.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "source": "line",
                        "source_kind": "line",
                        "message_id": "line-m1",
                        "created": "2026-06-23T08:00:00+07:00",
                        "text_sanitized": "Recloser PFA02VR-101 trip outage",
                        "chat_id_hash": "chat_hash",
                        "sender_hash": "sender_hash",
                        "roomDistrict": "Phang Khon",
                        "consent_manifest_id": "manifest-1",
                        "raw_redaction_flags": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            settings = Settings(
                workspace=root,
                db_path=Path("runtime/test.sqlite"),
                model_path=Path("runtime/missing_model.json"),
                notification_mode="shadow",
                mock_webhook_url="http://127.0.0.1:1/api/v1/etr-notifications",
                pilot_districts=("Phang Khon",),
            )
            db = RuntimeDb(settings.resolve(settings.db_path))
            db.init()
            db.upsert_customer_assets(
                [
                    CustomerAsset(
                        peano="6101",
                        feeder="PFA02",
                        recloser_ids=("PFA02VR-101",),
                        trace_status="OK",
                        confidence_eligible=True,
                    )
                ]
            )
            result = AisEtrPipeline(settings, db=db).replay_webex_history(source, audit_output=root / "audit.csv")

            self.assertEqual(result.new_messages, 1)
            self.assertEqual(result.parsed_events, 1)
            self.assertEqual(result.notifications_captured, 1)
            conn = sqlite3.connect(settings.resolve(settings.db_path))
            try:
                payload_json, status = conn.execute("SELECT payload_json, status FROM notifications").fetchone()
                parsed_json = conn.execute("SELECT parsed_json FROM outage_events").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(status, "REPLAY_CAPTURED")
            self.assertEqual(json.loads(payload_json)["mode"], "shadow")
            self.assertEqual(json.loads(parsed_json)["source"], "line")


def _line_event(group_id="Cgroup", user_id="Uuser", text="Recloser PFA02VR-101 trip outage"):
    return {
        "type": "message",
        "timestamp": 1_782_177_600_000,
        "source": {"type": "group", "groupId": group_id, "userId": user_id},
        "message": {"id": "line-msg-1", "type": "text", "text": text},
    }


def _manifest(source_type="line", approved=True, department_controlled=True):
    return {
        "manifest_id": f"{source_type}-manifest",
        "owner": "department-owner",
        "source_type": source_type,
        "date_range": {"start": "2026-06-01", "end": "2026-06-23"},
        "consent_basis": "department owner approved parser training corpus",
        "allowed_use": "AIS ETR parser shadow training only",
        "retention": "runtime evidence only",
        "redaction_level": "sanitized",
        "approved": approved,
        "department_controlled": department_controlled,
    }


if __name__ == "__main__":
    unittest.main()
