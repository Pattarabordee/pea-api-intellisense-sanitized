from __future__ import annotations

import base64
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any

WEBHOOK_PATH = "/line/webhook"
MAX_BODY_BYTES = 200_000
OUTPUT_JSONL = Path(os.environ.get("LINE_CAPTURE_JSONL", "runtime/line_webhook_capture.jsonl"))
OUTPUT_SQLITE = Path(os.environ.get("LINE_CAPTURE_SQLITE", "runtime/line_webhook_capture.sqlite"))

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?66|0)\d{8,9}(?!\w)")
LONG_NUMBER_RE = re.compile(r"\b\d{8,13}\b")
LINE_ID_RE = re.compile(r"\b[CUR][0-9a-f]{20,64}\b", re.IGNORECASE)
TOKEN_RE = re.compile(r"\b(?:Bearer\s+)?(?:[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_.-]{10,}|[A-Za-z0-9_-]{32,})\b")
PEANO_CONTEXT_RE = re.compile(r"\b((?:PEANO|meter|meter_no|meter\s*no\.?)\s*[:#=]?\s*)([0-9,\s/-]{4,})", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def settings() -> dict[str, Any]:
    allowed = tuple(part.strip() for part in os.environ.get("LINE_ALLOWED_GROUP_IDS", "").replace("\n", ",").split(",") if part.strip())
    return {
        "secret": os.environ.get("LINE_CHANNEL_SECRET", ""),
        "allowed": allowed,
        "mode": os.environ.get("LINE_CAPTURE_MODE", "shadow").strip().lower(),
    }


def verify_signature(body: bytes, signature: str | None, secret: str) -> bool:
    if not signature or not secret:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(signature, expected)


def sanitize_text(value: Any) -> tuple[str, list[str]]:
    text = "" if value is None else str(value)
    flags: set[str] = set()

    def replace(pattern: re.Pattern[str], replacement: str, flag: str) -> None:
        nonlocal text
        if pattern.search(text):
            flags.add(flag)
            text = pattern.sub(replacement, text)

    replace(URL_RE, "[URL_REDACTED]", "url")
    replace(EMAIL_RE, "[EMAIL_REDACTED]", "email")
    replace(PHONE_RE, "[PHONE_REDACTED]", "phone")
    if PEANO_CONTEXT_RE.search(text):
        flags.add("meter_context")
        text = PEANO_CONTEXT_RE.sub(lambda match: match.group(1) + "[METER_ID_REDACTED]", text)
    replace(LINE_ID_RE, "[LINE_ID_REDACTED]", "line_id")
    replace(LONG_NUMBER_RE, "[LONG_NUMBER_REDACTED]", "long_number")
    replace(TOKEN_RE, "[TOKEN_REDACTED]", "token_like")
    return WHITESPACE_RE.sub(" ", text).strip(), sorted(flags)


def iso_from_line_ts(value: Any) -> str | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value).strip() or None
    seconds = number / 1000.0 if number > 10_000_000_000 else number
    return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=0).isoformat()


def hash_id(prefix: str, value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def normalize_event(event: dict[str, Any], allowed: tuple[str, ...]) -> tuple[dict[str, Any] | None, str | None]:
    if event.get("type") != "message":
        return None, "ignored_event_type"
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    if message.get("type") != "text":
        return None, "ignored_non_text_message"
    source = event.get("source") if isinstance(event.get("source"), dict) else {}
    if source.get("type") not in {"group", "room"}:
        return None, "ignored_non_group_source"
    chat_id = str(source.get("groupId") or source.get("roomId") or "").strip()
    if not chat_id:
        return None, "missing_group_id"
    if chat_id not in set(allowed):
        return None, "group_not_allowlisted"
    text, flags = sanitize_text(message.get("text"))
    if not text:
        return None, "missing_text"
    created = iso_from_line_ts(event.get("timestamp"))
    chat_hash = hash_id("chat", chat_id)
    sender_hash = hash_id("sender", source.get("userId"))
    message_id = str(message.get("id") or "").strip()
    if not message_id:
        message_id = "line-" + hashlib.sha256(f"{chat_hash}|{sender_hash}|{created}|{text[:120]}".encode("utf-8")).hexdigest()[:16]
    record = {
        "source": "line",
        "source_kind": "line",
        "message_id": message_id,
        "created": created,
        "text_sanitized": text,
        "chat_id_hash": chat_hash,
        "sender_hash": sender_hash,
        "roomDistrict": None,
        "consent_manifest_id": "line-webhook",
        "raw_redaction_flags": flags,
    }
    return record, None


def write_records(records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    OUTPUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_JSONL.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    OUTPUT_SQLITE.parent.mkdir(parents=True, exist_ok=True)
    inserted = 0
    conn = sqlite3.connect(OUTPUT_SQLITE)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS line_webhook_capture (
                source_kind TEXT NOT NULL CHECK (source_kind = 'line'),
                message_id TEXT NOT NULL,
                created TEXT,
                captured_at TEXT NOT NULL,
                text_sanitized TEXT NOT NULL,
                chat_id_hash TEXT,
                sender_hash TEXT,
                consent_manifest_id TEXT NOT NULL,
                raw_redaction_flags TEXT NOT NULL,
                event_json TEXT NOT NULL,
                mode TEXT NOT NULL CHECK (mode = 'shadow'),
                production_send TEXT NOT NULL CHECK (production_send = 'blocked'),
                UNIQUE(source_kind, message_id)
            )
            """
        )
        for record in records:
            event_json = dict(record, mode="shadow", production_send="blocked")
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO line_webhook_capture (
                    source_kind, message_id, created, captured_at, text_sanitized,
                    chat_id_hash, sender_hash, consent_manifest_id, raw_redaction_flags,
                    event_json, mode, production_send
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'shadow', 'blocked')
                """,
                (
                    record["source_kind"],
                    record["message_id"],
                    record.get("created"),
                    utc_now(),
                    record["text_sanitized"],
                    record.get("chat_id_hash"),
                    record.get("sender_hash"),
                    record["consent_manifest_id"],
                    json.dumps(record.get("raw_redaction_flags") or [], ensure_ascii=False, sort_keys=True),
                    json.dumps(event_json, ensure_ascii=False, sort_keys=True),
                ),
            )
            inserted += cursor.rowcount
        conn.commit()
    finally:
        conn.close()
    return inserted


class Handler(BaseHTTPRequestHandler):
    server_version = "AisLineWebhook/1.0"

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_json(404, {"status": "NOT_FOUND"})
            return
        cfg = settings()
        self.send_json(200, {
            "status": "ok",
            "service": "pea-line-webhook",
            "mode": "shadow",
            "production_send": "blocked",
            "secret_configured": bool(cfg["secret"]),
            "allowed_group_count": len(cfg["allowed"]),
        })

    def do_POST(self) -> None:
        if self.path != WEBHOOK_PATH:
            self.send_json(404, {"status": "NOT_FOUND"})
            return
        cfg = settings()
        if cfg["mode"] != "shadow":
            self.send_json(503, {"status": "LINE_CAPTURE_MODE_NOT_SHADOW"})
            return
        if not cfg["secret"]:
            self.send_json(503, {"status": "LINE_CHANNEL_SECRET_REQUIRED"})
            return
        if not cfg["allowed"]:
            self.send_json(503, {"status": "LINE_ALLOWED_GROUP_IDS_REQUIRED"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"status": "INVALID_CONTENT_LENGTH"})
            return
        if length > MAX_BODY_BYTES:
            self.send_json(413, {"status": "PAYLOAD_TOO_LARGE"})
            return
        body = self.rfile.read(length)
        if not verify_signature(body, self.headers.get("X-Line-Signature"), cfg["secret"]):
            self.send_json(401, {"status": "INVALID_LINE_SIGNATURE"})
            return
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_json(400, {"status": "INVALID_JSON"})
            return
        events = payload.get("events") if isinstance(payload, dict) else None
        if not isinstance(events, list):
            self.send_json(400, {"status": "WEBHOOK_EVENTS_MUST_BE_LIST"})
            return
        accepted: list[dict[str, Any]] = []
        rejected: dict[str, int] = {}
        for event in events:
            if not isinstance(event, dict):
                rejected["invalid_event"] = rejected.get("invalid_event", 0) + 1
                continue
            record, reason = normalize_event(event, cfg["allowed"])
            if record:
                accepted.append(record)
            elif reason:
                rejected[reason] = rejected.get(reason, 0) + 1
        inserted = write_records(accepted)
        self.send_json(200, {
            "status": "CAPTURED",
            "accepted": len(accepted),
            "inserted": inserted,
            "rejected": dict(sorted(rejected.items())),
            "mode": "shadow",
            "production_send": "blocked",
            "generated_at": utc_now(),
        })

    def send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8091"))
    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
