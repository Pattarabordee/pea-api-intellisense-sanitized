from __future__ import annotations

import base64
import csv
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable
import zipfile

from .utils import stable_id


SOURCE_LINE = "line"
SOURCE_OPENCHAT_EXPORT = "line_openchat_export"
DEFAULT_WEBHOOK_PATH = "/line/webhook"
DEFAULT_WEBHOOK_OUTPUT = "runtime/line_webhook_capture.jsonl"
DEFAULT_WEBHOOK_SQLITE = "runtime/line_webhook_capture.sqlite"
DEFAULT_TRAINING_CORPUS_OUTPUT = "runtime/line_training_corpus.jsonl"
DEFAULT_TRAINING_CORPUS_AUDIT = "runtime/line_training_corpus_audit.csv"
DEFAULT_TRAINING_CORPUS_REPORT = "runtime/line_training_corpus_redaction_report.md"
MAX_WEBHOOK_BODY_BYTES = 200_000
REQUIRED_MANIFEST_FIELDS = (
    "owner",
    "source_type",
    "date_range",
    "consent_basis",
    "allowed_use",
    "retention",
    "redaction_level",
)


def _text_variants(items: Iterable[str]) -> tuple[str, ...]:
    variants: set[str] = set()
    for item in items:
        variants.add(item)
        try:
            variants.add(item.encode("utf-8").decode("cp874"))
        except UnicodeError:
            pass
    return tuple(sorted(variants, key=lambda value: (-len(value), value.lower())))


URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?66|0)[\s.-]?\d(?:[\s.-]?\d){7,8}(?!\w)")
MENTION_RE = re.compile(r"(?<!\S)@[^\s@]{0,80}(?:\s+[A-Za-z][A-Za-z0-9_.-]{0,80})?")
LONG_NUMBER_RE = re.compile(r"\b\d{8,13}\b")
LINE_ID_RE = re.compile(r"\b[CUR][0-9a-f]{20,64}\b", re.IGNORECASE)
TOKEN_RE = re.compile(r"\b(?:Bearer\s+)?(?:[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_.-]{10,}|[A-Za-z0-9_-]{32,})\b")
PEANO_CONTEXT_RE = re.compile(
    r"\b((?:PEANO|meter|meter_no|meter\s*no\.?|มิเตอร์|เลขมิเตอร์)\s*[:#=]?\s*)([0-9,\s/-]{4,})",
    re.IGNORECASE,
)
WHITESPACE_RE = re.compile(r"\s+")
LINE_EXPORT_DATE_RE = re.compile(r"(?P<date>\d{4}[./-]\d{1,2}[./-]\d{1,2})")
LINE_EXPORT_MESSAGE_RE = re.compile(
    r"^(?:(?P<date>\d{4}[./-]\d{1,2}[./-]\d{1,2})\s+)?"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s+(?P<sender>.+?)\s{2,}(?P<text>.*)$"
)
LINE_EXPORT_TAB_MESSAGE_RE = re.compile(
    r"^(?:(?P<date>\d{4}[./-]\d{1,2}[./-]\d{1,2})\s+)?"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\t(?P<sender>[^\t]+)\t(?P<text>.*)$"
)
LINE_EXPORT_LOOSE_MESSAGE_RE = re.compile(
    r"^(?:(?P<date>\d{4}[./-]\d{1,2}[./-]\d{1,2})\s+)?"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s+(?P<rest>.+)$"
)
LINE_EXPORT_SKIP_PREFIXES = ("[LINE]", "Saved on:", "Save date:", "Chat history", "Talk history")
PERSON_NAME_LABELS = (
    "contact name",
    "customer name",
    "name",
    "\u0e0a\u0e37\u0e48\u0e2d\u0e1c\u0e39\u0e49\u0e15\u0e34\u0e14\u0e15\u0e48\u0e2d",
    "\u0e0a\u0e37\u0e48\u0e2d\u0e1c\u0e39\u0e49\u0e17\u0e35\u0e48\u0e43\u0e2b\u0e49\u0e15\u0e34\u0e14\u0e15\u0e48\u0e2d\u0e01\u0e25\u0e31\u0e1a",
    "\u0e1c\u0e39\u0e49\u0e41\u0e08\u0e49\u0e07",
    "\u0e1c\u0e39\u0e49\u0e15\u0e34\u0e14\u0e15\u0e48\u0e2d",
)
PHONE_LABELS = (
    "phone",
    "tel",
    "telephone",
    "\u0e40\u0e1a\u0e2d\u0e23\u0e4c",
    "\u0e42\u0e17\u0e23",
    "\u0e2b\u0e21\u0e32\u0e22\u0e40\u0e25\u0e02\u0e42\u0e17\u0e23\u0e28\u0e31\u0e1e\u0e17\u0e4c",
)
PERSON_NAME_CONTEXT_RE = re.compile(
    r"((?:"
    + "|".join(re.escape(item) for item in _text_variants(PERSON_NAME_LABELS))
    + r")\s*[:\uff1a]?\s*)(.{1,120}?)(?=(?:\s+N/A)?\s*(?:"
    + "|".join(re.escape(item) for item in _text_variants(PHONE_LABELS))
    + r"|\[PHONE_REDACTED\]))",
    re.IGNORECASE,
)
LINE_EXPORT_MEDIA_TEXTS = {
    "album",
    "file",
    "location",
    "photo",
    "sticker",
    "video",
    "voice message",
    "\u0e02\u0e49\u0e2d\u0e04\u0e27\u0e32\u0e21\u0e40\u0e2a\u0e35\u0e22\u0e07",
    "\u0e15\u0e33\u0e41\u0e2b\u0e19\u0e48\u0e07\u0e17\u0e35\u0e48\u0e15\u0e31\u0e49\u0e07",
    "\u0e23\u0e39\u0e1b",
    "\u0e27\u0e34\u0e14\u0e35\u0e42\u0e2d",
    "\u0e2a\u0e15\u0e34\u0e01\u0e40\u0e01\u0e2d\u0e23\u0e4c",
    "\u0e2d\u0e31\u0e25\u0e1a\u0e31\u0e49\u0e21",
    "\u0e44\u0e1f\u0e25\u0e4c",
}
LINE_EXPORT_FILE_ONLY_RE = re.compile(
    r"^[^\r\n\\/]{1,180}\.(?:csv|docx?|heic|jpe?g|mov|mp4|pdf|png|pptx?|txt|xlsx?)$",
    re.IGNORECASE,
)
LINE_EXPORT_SKIP_LOOSE_MESSAGE = object()
LINE_EXPORT_OPERATIONAL_SIGNAL_RE = re.compile(
    r"\b[A-Z]{3}\d{2}(?:[A-Z]{1,3}[-/][A-Z0-9/.-]+)?\b|"
    r"\b(?:cb|fault|outage|recloser|switch|trip|tripped)\b|"
    r"\u0e01\u0e23\u0e30\u0e41\u0e2a\u0e44\u0e1f\u0e1f\u0e49\u0e32\u0e02\u0e31\u0e14\u0e02\u0e49\u0e2d\u0e07|"
    r"\u0e44\u0e1f\u0e14\u0e31\u0e1a|"
    r"\u0e44\u0e1f\u0e15\u0e01|"
    r"\u0e44\u0e1f\u0e1f\u0e49\u0e32\u0e02\u0e31\u0e14\u0e02\u0e49\u0e2d\u0e07",
    re.IGNORECASE,
)


class LineIngestError(ValueError):
    pass


def verify_line_signature(body: bytes, signature: str | None, channel_secret: str | None) -> bool:
    if not signature or not channel_secret:
        return False
    digest = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(signature, expected)


def normalize_line_webhook_event(
    event: dict[str, Any],
    allowed_group_ids: Iterable[str],
    allowed_chat_hashes: Iterable[str] = (),
    consent_manifest_id: str = "line-webhook",
) -> dict[str, Any]:
    if event.get("type") != "message":
        raise LineIngestError("ignored_event_type")
    message = event.get("message")
    if not isinstance(message, dict) or message.get("type") != "text":
        raise LineIngestError("ignored_non_text_message")
    source = event.get("source")
    if not isinstance(source, dict) or source.get("type") not in {"group", "room"}:
        raise LineIngestError("ignored_non_group_source")

    chat_id = str(source.get("groupId") or source.get("roomId") or "")
    if not chat_id:
        raise LineIngestError("missing_group_id")
    allowed = {str(item).strip() for item in allowed_group_ids if str(item).strip()}
    chat_hash = _hash_identifier(chat_id, "chat")
    allowed_hashes = {str(item).strip() for item in allowed_chat_hashes if str(item).strip()}
    if chat_id not in allowed and chat_hash not in allowed_hashes:
        raise LineIngestError("group_not_allowlisted")

    return _normalized_record(
        source_kind=SOURCE_LINE,
        message_id=message.get("id"),
        created=_timestamp_to_iso(event.get("timestamp")),
        text=message.get("text"),
        chat_id=chat_id,
        sender_id=source.get("userId"),
        room_district=None,
        consent_manifest_id=consent_manifest_id,
    )


def import_line_history_export(
    source: str | Path,
    manifest: str | Path,
    output: str | Path,
) -> dict[str, Any]:
    source_path = Path(source)
    output_path = Path(output)
    manifest_data = load_consent_manifest(manifest)
    source_kind = manifest_data["source_kind"]
    if manifest_data.get("status") == "blocked_needs_owner_approval":
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("", encoding="utf-8")
        return {
            "status": "blocked_needs_owner_approval",
            "reason": manifest_data.get("blocked_reason"),
            "source": str(source_path),
            "output": str(output_path),
            "records_read": 0,
            "records_exported": 0,
            "skipped": 0,
            "consent_manifest_id": manifest_data["manifest_id"],
            "source_kind": source_kind,
        }

    records_read = records_exported = skipped = 0
    redaction_counts: dict[str, int] = {}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for raw in _iter_export_records(source_path):
            records_read += 1
            try:
                record = normalize_line_export_record(raw, manifest_data)
            except LineIngestError:
                skipped += 1
                continue
            for flag in record["raw_redaction_flags"]:
                redaction_counts[flag] = redaction_counts.get(flag, 0) + 1
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            records_exported += 1

    return {
        "status": "ok",
        "source": str(source_path),
        "output": str(output_path),
        "records_read": records_read,
        "records_exported": records_exported,
        "skipped": skipped,
        "redaction_counts": dict(sorted(redaction_counts.items())),
        "consent_manifest_id": manifest_data["manifest_id"],
        "source_kind": source_kind,
    }


def build_line_training_corpus(
    sources: Iterable[str | Path],
    output: str | Path = DEFAULT_TRAINING_CORPUS_OUTPUT,
    audit_output: str | Path | None = DEFAULT_TRAINING_CORPUS_AUDIT,
    markdown_output: str | Path | None = DEFAULT_TRAINING_CORPUS_REPORT,
    districts: tuple[str, ...] = (),
) -> dict[str, Any]:
    from .parser import parse_webex_message

    source_paths = [Path(source) for source in sources]
    output_path = Path(output)
    seen: set[tuple[str, str]] = set()
    rows_written = rows_read = duplicates = skipped = 0
    source_counts: dict[str, int] = {}
    parser_counts: dict[str, int] = {}
    redaction_counts: dict[str, int] = {}
    audit_rows: list[dict[str, Any]] = []

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for source_path in source_paths:
            for record in _iter_normalized_line_records(source_path):
                rows_read += 1
                try:
                    corpus_row, audit_row = _training_corpus_row(record, parse_webex_message, districts)
                except LineIngestError as exc:
                    skipped += 1
                    audit_rows.append(
                        {
                            "message_ref": "",
                            "source_kind": str(record.get("source_kind") or record.get("source") or ""),
                            "created": str(record.get("created") or ""),
                            "status": f"skipped_{exc}",
                            "parser_status": "",
                            "redaction_flags": "",
                            "device_id": "",
                            "feeder": "",
                            "district": "",
                            "event_time": "",
                        }
                    )
                    continue
                dedupe_key = (corpus_row["source_kind"], audit_row["message_ref"])
                if dedupe_key in seen:
                    duplicates += 1
                    audit_row["status"] = "duplicate"
                    audit_rows.append(audit_row)
                    continue
                seen.add(dedupe_key)
                handle.write(json.dumps(corpus_row, ensure_ascii=False, sort_keys=True) + "\n")
                rows_written += 1
                source_counts[corpus_row["source_kind"]] = source_counts.get(corpus_row["source_kind"], 0) + 1
                parser_status = audit_row["parser_status"]
                parser_counts[parser_status] = parser_counts.get(parser_status, 0) + 1
                for flag in corpus_row["raw_redaction_flags"]:
                    redaction_counts[flag] = redaction_counts.get(flag, 0) + 1
                audit_rows.append(audit_row)

    if audit_output:
        _write_training_audit(Path(audit_output), audit_rows)
    leak_scan = _scan_corpus_for_sensitive_patterns(output_path)
    report = {
        "status": "FAIL" if any(leak_scan.values()) else "PASS",
        "sources": [str(path) for path in source_paths],
        "output": str(output_path),
        "rows_read": rows_read,
        "rows_written": rows_written,
        "duplicates": duplicates,
        "skipped": skipped,
        "source_counts": dict(sorted(source_counts.items())),
        "parser_counts": dict(sorted(parser_counts.items())),
        "redaction_counts": dict(sorted(redaction_counts.items())),
        "leak_scan": leak_scan,
    }
    if markdown_output:
        _write_training_redaction_report(Path(markdown_output), report)

    return {
        "status": "ok" if report["status"] == "PASS" else "needs_redaction_review",
        "sources": report["sources"],
        "output": str(output_path),
        "audit_output": str(audit_output) if audit_output else None,
        "markdown_output": str(markdown_output) if markdown_output else None,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "duplicates": duplicates,
        "skipped": skipped,
        "source_counts": report["source_counts"],
        "parser_counts": report["parser_counts"],
        "redaction_counts": report["redaction_counts"],
        "leak_scan": leak_scan,
        "mode": "shadow",
        "production_send": "blocked",
        "label_policy": "parser_training_only_not_customer_truth",
    }


def normalize_line_export_record(raw: dict[str, Any], manifest_data: dict[str, Any]) -> dict[str, Any]:
    source_kind = manifest_data["source_kind"]
    if _looks_like_webhook_event(raw):
        event = raw
        message = event.get("message") or {}
        source = event.get("source") or {}
        return _normalized_record(
            source_kind=source_kind,
            message_id=message.get("id") or raw.get("message_id") or raw.get("id"),
            created=_timestamp_to_iso(event.get("timestamp")) or _first_present(raw, ("created", "datetime", "date")),
            text=message.get("text") or raw.get("text"),
            chat_id=source.get("groupId") or source.get("roomId") or raw.get("chat_id"),
            sender_id=source.get("userId") or raw.get("sender_id") or raw.get("sender"),
            room_district=_first_present(raw, ("roomDistrict", "room_district", "district")),
            consent_manifest_id=manifest_data["manifest_id"],
        )
    return _normalized_record(
        source_kind=source_kind,
        message_id=_first_present(raw, ("message_id", "messageId", "id")),
        created=_timestamp_to_iso(_first_present(raw, ("timestamp",))) or _first_present(
            raw, ("created", "datetime", "date", "time")
        ),
        text=_first_present(raw, ("text", "message", "content", "text_sanitized")),
        chat_id=_first_present(raw, ("chat_id", "group_id", "groupId", "room_id", "roomId", "openchat_id"))
        or _manifest_chat_surrogate(manifest_data),
        sender_id=_first_present(raw, ("sender_id", "user_id", "userId", "sender", "author", "person")),
        room_district=_first_present(raw, ("roomDistrict", "room_district", "district")),
        consent_manifest_id=manifest_data["manifest_id"],
    )


def load_consent_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    if not manifest_path.exists():
        raise LineIngestError(f"consent manifest does not exist: {manifest_path}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise LineIngestError(f"invalid consent manifest JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LineIngestError("consent manifest must be a JSON object")
    missing = [field for field in REQUIRED_MANIFEST_FIELDS if not data.get(field)]
    if missing:
        raise LineIngestError("consent manifest missing required fields: " + ", ".join(missing))
    if not _truthy(data.get("approved") or data.get("owner_approved") or data.get("moderator_approved")):
        raise LineIngestError("consent manifest approval is required")

    source_kind = _canonical_source_kind(data.get("source_type"))
    manifest_id = str(data.get("manifest_id") or stable_id("line-manifest", data.get("owner"), data.get("source_type")))
    result = dict(data)
    result["manifest_id"] = manifest_id
    result["source_kind"] = source_kind
    if source_kind == SOURCE_OPENCHAT_EXPORT and not _department_controlled(data):
        result["status"] = "blocked_needs_owner_approval"
        result["blocked_reason"] = "line_openchat_export_requires_department_controlled_owner_approval"
    return result


def sanitize_line_text(text: Any) -> tuple[str, list[str]]:
    if text is None:
        return "", []
    value = str(text)
    flags: list[str] = []

    def replace(pattern: re.Pattern[str], replacement: str, flag: str, source: str) -> str:
        nonlocal flags
        if pattern.search(source):
            flags.append(flag)
        return pattern.sub(replacement, source)

    value = replace(URL_RE, "[URL_REDACTED]", "url", value)
    value = replace(EMAIL_RE, "[EMAIL_REDACTED]", "email", value)
    value = replace(PHONE_RE, "[PHONE_REDACTED]", "phone", value)
    if PERSON_NAME_CONTEXT_RE.search(value):
        flags.append("person_name")
        value = PERSON_NAME_CONTEXT_RE.sub(lambda match: match.group(1) + "[PERSON_NAME_REDACTED] ", value)
    value = replace(MENTION_RE, "[MENTION_REDACTED]", "mention", value)
    value = PEANO_CONTEXT_RE.sub(lambda match: match.group(1) + "[METER_ID_REDACTED]", value)
    if PEANO_CONTEXT_RE.search(str(text)):
        flags.append("meter_context")
    value = replace(LINE_ID_RE, "[LINE_ID_REDACTED]", "line_id", value)
    value = replace(LONG_NUMBER_RE, "[LONG_NUMBER_REDACTED]", "long_number", value)
    value = replace(TOKEN_RE, "[TOKEN_REDACTED]", "token_like", value)
    value = WHITESPACE_RE.sub(" ", value).strip()
    return value, sorted(set(flags))


def process_line_webhook_body(
    body: bytes,
    signature: str | None,
    channel_secret: str,
    allowed_group_ids: Iterable[str],
    output_jsonl: str | Path,
    output_sqlite: str | Path | None = None,
    allowed_chat_hashes: Iterable[str] = (),
) -> dict[str, Any]:
    if not verify_line_signature(body, signature, channel_secret):
        raise LineIngestError("invalid_line_signature")
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise LineIngestError(f"invalid_json: {exc}") from exc
    if not isinstance(payload, dict):
        raise LineIngestError("invalid_webhook_payload")

    events = payload.get("events") or []
    if not isinstance(events, list):
        raise LineIngestError("webhook_events_must_be_list")
    accepted: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    for event in events:
        if not isinstance(event, dict):
            rejected["invalid_event"] = rejected.get("invalid_event", 0) + 1
            continue
        try:
            accepted.append(
                normalize_line_webhook_event(
                    event,
                    allowed_group_ids=allowed_group_ids,
                    allowed_chat_hashes=allowed_chat_hashes,
                )
            )
        except LineIngestError as exc:
            reason = str(exc)
            rejected[reason] = rejected.get(reason, 0) + 1

    output = Path(output_jsonl)
    if accepted:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("a", encoding="utf-8") as handle:
            for record in accepted:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    sqlite_inserted = 0
    if accepted and output_sqlite:
        sqlite_inserted = write_line_capture_sqlite(accepted, output_sqlite)
    return {
        "status": "captured",
        "accepted": len(accepted),
        "rejected": dict(sorted(rejected.items())),
        "output": str(output),
        "sqlite": str(output_sqlite) if output_sqlite else None,
        "sqlite_inserted": sqlite_inserted,
    }


def create_line_webhook_server(
    host: str,
    port: int,
    channel_secret: str,
    allowed_group_ids: Iterable[str],
    output_jsonl: str | Path = DEFAULT_WEBHOOK_OUTPUT,
    output_sqlite: str | Path | None = DEFAULT_WEBHOOK_SQLITE,
    allowed_chat_hashes: Iterable[str] = (),
    path: str = DEFAULT_WEBHOOK_PATH,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), LineWebhookHandler)
    server.channel_secret = channel_secret  # type: ignore[attr-defined]
    server.allowed_group_ids = tuple(allowed_group_ids)  # type: ignore[attr-defined]
    server.allowed_chat_hashes = tuple(allowed_chat_hashes)  # type: ignore[attr-defined]
    server.output_jsonl = Path(output_jsonl)  # type: ignore[attr-defined]
    server.output_sqlite = Path(output_sqlite) if output_sqlite else None  # type: ignore[attr-defined]
    server.webhook_path = path  # type: ignore[attr-defined]
    return server


def serve_line_webhook(
    host: str,
    port: int,
    channel_secret: str,
    allowed_group_ids: Iterable[str],
    output_jsonl: str | Path = DEFAULT_WEBHOOK_OUTPUT,
    output_sqlite: str | Path | None = DEFAULT_WEBHOOK_SQLITE,
    allowed_chat_hashes: Iterable[str] = (),
    path: str = DEFAULT_WEBHOOK_PATH,
) -> None:
    server = create_line_webhook_server(
        host,
        port,
        channel_secret,
        allowed_group_ids,
        output_jsonl,
        output_sqlite,
        allowed_chat_hashes,
        path,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


class LineWebhookHandler(BaseHTTPRequestHandler):
    server_version = "AisEtrLineWebhook/1.0"

    def do_GET(self) -> None:
        if self.path != "/health":
            self._send_json(404, {"status": "NOT_FOUND"})
            return
        self._send_json(
            200,
            {
                "status": "ok",
                "service": "ais-etr-line-webhook",
                "mode": "shadow",
                "production_send": "blocked",
                "path": getattr(self.server, "webhook_path", DEFAULT_WEBHOOK_PATH),
                "output": str(getattr(self.server, "output_jsonl", "")),
                "sqlite": str(getattr(self.server, "output_sqlite", "")),
                "allowed_group_count": len(getattr(self.server, "allowed_group_ids", ())),
                "allowed_chat_hash_count": len(getattr(self.server, "allowed_chat_hashes", ())),
            },
        )

    def do_POST(self) -> None:
        if self.path != getattr(self.server, "webhook_path", DEFAULT_WEBHOOK_PATH):
            self._send_json(404, {"status": "NOT_FOUND"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"status": "INVALID_CONTENT_LENGTH"})
            return
        if length > MAX_WEBHOOK_BODY_BYTES:
            self._send_json(413, {"status": "PAYLOAD_TOO_LARGE"})
            return
        body = self.rfile.read(length)
        try:
            result = process_line_webhook_body(
                body,
                self.headers.get("X-Line-Signature"),
                getattr(self.server, "channel_secret"),
                getattr(self.server, "allowed_group_ids"),
                getattr(self.server, "output_jsonl"),
                getattr(self.server, "output_sqlite", None),
                getattr(self.server, "allowed_chat_hashes", ()),
            )
        except LineIngestError as exc:
            status = 401 if str(exc) == "invalid_line_signature" else 400
            self._send_json(status, {"status": str(exc)})
            return
        self._send_json(200, result)

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def _normalized_record(
    source_kind: str,
    message_id: Any,
    created: Any,
    text: Any,
    chat_id: Any,
    sender_id: Any,
    room_district: Any,
    consent_manifest_id: str,
) -> dict[str, Any]:
    text_sanitized, flags = sanitize_line_text(text)
    if not text_sanitized:
        raise LineIngestError("missing_text")
    created_iso = _timestamp_to_iso(created) or (str(created).strip() if created else None)
    chat_hash = _hash_identifier(chat_id, "chat")
    sender_hash = _hash_identifier(sender_id, "sender")
    safe_message_id = str(message_id or "").strip()
    if not safe_message_id:
        safe_message_id = stable_id(source_kind, chat_hash, sender_hash, created_iso, text_sanitized[:120])
    return {
        "source": source_kind,
        "source_kind": source_kind,
        "message_id": safe_message_id,
        "created": created_iso,
        "text_sanitized": text_sanitized,
        "chat_id_hash": chat_hash,
        "sender_hash": sender_hash,
        "roomDistrict": str(room_district).strip() if room_district else None,
        "consent_manifest_id": consent_manifest_id,
        "raw_redaction_flags": flags,
    }


def write_line_capture_sqlite(records: Iterable[dict[str, Any]], output_sqlite: str | Path) -> int:
    path = Path(output_sqlite)
    path.parent.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    inserted = 0
    conn = sqlite3.connect(path)
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
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_line_webhook_capture_created ON line_webhook_capture(created)"
        )
        for record in records:
            event_json = dict(record)
            event_json["mode"] = "shadow"
            event_json["production_send"] = "blocked"
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO line_webhook_capture (
                    source_kind,
                    message_id,
                    created,
                    captured_at,
                    text_sanitized,
                    chat_id_hash,
                    sender_hash,
                    consent_manifest_id,
                    raw_redaction_flags,
                    event_json,
                    mode,
                    production_send
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'shadow', 'blocked')
                """,
                (
                    record.get("source_kind"),
                    record.get("message_id"),
                    record.get("created"),
                    captured_at,
                    record.get("text_sanitized"),
                    record.get("chat_id_hash"),
                    record.get("sender_hash"),
                    record.get("consent_manifest_id"),
                    json.dumps(record.get("raw_redaction_flags") or [], ensure_ascii=False, sort_keys=True),
                    json.dumps(event_json, ensure_ascii=False, sort_keys=True),
                ),
            )
            inserted += cursor.rowcount
        conn.commit()
    finally:
        conn.close()
    return inserted


def _iter_export_records(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"LINE history source does not exist: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                yield dict(row)
        return
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    yield item
            return
        if isinstance(data, dict):
            for key in ("events", "messages", "items"):
                values = data.get(key)
                if isinstance(values, list):
                    for item in values:
                        if isinstance(item, dict):
                            yield item
                    return
            yield data
            return
        raise LineIngestError("JSON export must be an object or array")
    if suffix == ".txt":
        yield from _iter_line_text_export(path.read_text(encoding="utf-8-sig"))
        return
    if suffix == ".zip":
        yield from _iter_zip_export_records(path)
        return
    with path.open(encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid LINE JSONL at {path}:{line_no}: {exc}") from exc
            if isinstance(item, dict):
                yield item


def _iter_zip_export_records(path: Path):
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if name.endswith("/"):
                continue
            suffix = Path(name).suffix.lower()
            if suffix not in {".csv", ".json", ".jsonl", ".txt"}:
                continue
            text = archive.read(name).decode("utf-8-sig")
            if suffix == ".csv":
                for row in csv.DictReader(text.splitlines()):
                    item = dict(row)
                    item.setdefault("source_file", name)
                    yield item
                continue
            if suffix == ".json":
                data = json.loads(text)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            item.setdefault("source_file", name)
                            yield item
                    continue
                if isinstance(data, dict):
                    items = data.get("events") or data.get("messages") or data.get("items")
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict):
                                item.setdefault("source_file", name)
                                yield item
                        continue
                    data.setdefault("source_file", name)
                    yield data
                    continue
                raise LineIngestError("JSON export in zip must be an object or array")
            if suffix == ".txt":
                yield from _iter_line_text_export(text, source_file=name)
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                item = json.loads(line)
                if isinstance(item, dict):
                    item.setdefault("source_file", name)
                    item.setdefault("line_no", line_no)
                    yield item


def _iter_line_text_export(text: str, source_file: str | None = None):
    current_date: str | None = None
    current: dict[str, Any] | None = None
    known_senders = _collect_line_export_senders(text)
    counter = 0
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r\n")
        if not line.strip():
            continue
        stripped = line.strip()
        if any(stripped.startswith(prefix) for prefix in LINE_EXPORT_SKIP_PREFIXES):
            continue
        date_match = LINE_EXPORT_DATE_RE.match(stripped)
        if date_match and "\t" not in stripped and not re.search(r"\d{1,2}:\d{2}", stripped):
            current_date = date_match.group("date")
            continue
        message_match = LINE_EXPORT_TAB_MESSAGE_RE.match(line) or LINE_EXPORT_MESSAGE_RE.match(line)
        if message_match:
            if current is not None:
                yield current
            sender = message_match.group("sender").strip()
            text_value = message_match.group("text").strip()
            if _is_line_system_message(sender, text_value) or _is_line_export_non_text_payload(text_value):
                current = None
                continue
            counter += 1
            date_text = message_match.group("date") or current_date
            created = _line_export_created(date_text, message_match.group("time"))
            current = {
                "message_id": stable_id("line-text-export", source_file, counter, created, sender),
                "created": created,
                "sender": sender,
                "text": text_value,
                "source_file": source_file,
            }
            continue
        loose_message = _parse_line_export_loose_message(line, known_senders)
        if loose_message is LINE_EXPORT_SKIP_LOOSE_MESSAGE:
            if current is not None:
                yield current
            current = None
            continue
        if loose_message is not None:
            if current is not None:
                yield current
            sender, text_value, time_text, date_text = loose_message
            if _is_line_system_message(sender, text_value) or _is_line_export_non_text_payload(text_value):
                current = None
                continue
            counter += 1
            created = _line_export_created(date_text or current_date, time_text)
            current = {
                "message_id": stable_id("line-text-export", source_file, counter, created, sender),
                "created": created,
                "sender": sender,
                "text": text_value,
                "source_file": source_file,
            }
            continue
        if current is not None:
            if _is_line_export_metadata_line(stripped):
                continue
            current["text"] = (str(current.get("text") or "") + "\n" + stripped).strip()
    if current is not None:
        yield current


def _is_line_system_message(sender: str, text: str) -> bool:
    sender_text = sender.strip().lower()
    message_text = text.strip().lower()
    if sender_text in {"line", "system"}:
        return True
    system_phrases = (
        "joined the group",
        "left the group",
        "invited",
        "changed the group name",
        "unsent a message",
    )
    return any(phrase in message_text for phrase in system_phrases)


def _collect_line_export_senders(text: str) -> tuple[str, ...]:
    senders: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r\n")
        message_match = LINE_EXPORT_TAB_MESSAGE_RE.match(line) or LINE_EXPORT_MESSAGE_RE.match(line)
        if message_match:
            sender = message_match.group("sender").strip()
            if sender:
                senders.add(sender)
            continue
        loose_match = LINE_EXPORT_LOOSE_MESSAGE_RE.match(line)
        if not loose_match:
            continue
        rest = loose_match.group("rest").strip()
        sender = _infer_sender_from_loose_rest(rest)
        if sender:
            senders.add(sender)
    return tuple(sorted(senders, key=lambda item: (-len(item), item.lower())))


def _parse_line_export_loose_message(
    line: str,
    known_senders: tuple[str, ...],
) -> tuple[str, str, str, str | None] | object | None:
    loose_match = LINE_EXPORT_LOOSE_MESSAGE_RE.match(line)
    if not loose_match:
        return None
    rest = loose_match.group("rest").strip()
    sender, text_value = _split_loose_sender_text(rest, known_senders)
    if text_value:
        return sender, text_value, loose_match.group("time"), loose_match.group("date")
    signal_match = LINE_EXPORT_OPERATIONAL_SIGNAL_RE.search(rest)
    if signal_match:
        return "unknown-export-sender", rest[signal_match.start() :].strip(), loose_match.group("time"), loose_match.group("date")
    return LINE_EXPORT_SKIP_LOOSE_MESSAGE


def _split_loose_sender_text(rest: str, known_senders: tuple[str, ...]) -> tuple[str, str]:
    for sender in known_senders:
        if rest == sender:
            return sender, ""
        prefix = sender + " "
        if rest.startswith(prefix):
            return sender, rest[len(prefix) :].strip()
    sender = _infer_sender_from_loose_rest(rest)
    if sender:
        return sender, rest[len(sender) :].strip()
    return "unknown-export-sender", ""


def _infer_sender_from_loose_rest(rest: str) -> str | None:
    lowered = rest.lower()
    for media_text in sorted(LINE_EXPORT_MEDIA_TEXTS, key=len, reverse=True):
        suffix = " " + media_text.lower()
        if lowered.endswith(suffix):
            sender = rest[: -len(suffix)].strip()
            return sender or None
    if _is_line_export_time_record_notice(rest):
        return None
    notice = (
        " "
        "\u0e41\u0e08\u0e49\u0e07\u0e40\u0e15\u0e37\u0e2d\u0e19: "
        "\u0e23\u0e30\u0e1a\u0e1a\u0e25\u0e07\u0e40\u0e27\u0e25\u0e32\u0e1b"
        "\u0e0f\u0e34\u0e1a\u0e31\u0e15\u0e34\u0e07\u0e32\u0e19"
    )
    index = rest.find(notice)
    if index > 0:
        return rest[:index].strip() or None
    file_match = re.search(r"\s+[^\s\\/]{1,180}\.(?:csv|docx?|heic|jpe?g|mov|mp4|pdf|png|pptx?|txt|xlsx?)$", rest, re.IGNORECASE)
    if file_match:
        return rest[: file_match.start()].strip() or None
    return None


def _is_line_export_non_text_payload(text: str) -> bool:
    stripped = text.strip()
    lowered = stripped.lower()
    if not stripped:
        return True
    if _is_line_export_metadata_line(stripped):
        return True
    if lowered in LINE_EXPORT_MEDIA_TEXTS:
        return True
    if _is_line_export_time_record_notice(stripped):
        return True
    if LINE_EXPORT_FILE_ONLY_RE.fullmatch(stripped) and not LINE_EXPORT_OPERATIONAL_SIGNAL_RE.search(stripped):
        return True
    return False


def _is_line_export_metadata_line(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered == "link url :" or lowered.startswith("created by ")


def _is_line_export_time_record_notice(text: str) -> bool:
    return text.strip().startswith(
        "\u0e41\u0e08\u0e49\u0e07\u0e40\u0e15\u0e37\u0e2d\u0e19: "
        "\u0e23\u0e30\u0e1a\u0e1a\u0e25\u0e07\u0e40\u0e27\u0e25\u0e32\u0e1b"
        "\u0e0f\u0e34\u0e1a\u0e31\u0e15\u0e34\u0e07\u0e32\u0e19"
    )


def _line_export_created(date_text: str | None, time_text: str | None) -> str | None:
    if not time_text:
        return None
    if not date_text:
        return time_text
    normalized_date = date_text.replace(".", "-").replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(f"{normalized_date} {time_text}", fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=timezone.utc).isoformat()
    return f"{normalized_date} {time_text}"


def _iter_normalized_line_records(path: Path):
    if not path.exists():
        return
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                yield dict(row)
        return
    with path.open(encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid normalized LINE JSONL at {path}:{line_no}: {exc}") from exc
            if isinstance(item, dict):
                yield item


def _training_corpus_row(record: dict[str, Any], parser_func: Any, districts: tuple[str, ...]) -> tuple[dict[str, Any], dict[str, Any]]:
    source_kind = str(record.get("source_kind") or record.get("source") or "").strip()
    if source_kind not in {SOURCE_LINE, SOURCE_OPENCHAT_EXPORT}:
        raise LineIngestError("unsupported_source_kind")
    message_id = str(record.get("message_id") or record.get("id") or "").strip()
    text, new_flags = sanitize_line_text(record.get("text_sanitized") or record.get("text"))
    if not text:
        raise LineIngestError("missing_text")
    message_ref = _hash_identifier(f"{source_kind}:{message_id or text[:120]}", "msg")
    parser_message = {
        "id": message_ref,
        "created": record.get("created"),
        "text": text,
        "roomId": record.get("chat_id_hash"),
        "roomDistrict": record.get("roomDistrict"),
        "source": source_kind,
    }
    event = parser_func(parser_message, districts=districts) if districts else parser_func(parser_message)
    parser_status = "parsed" if event else "unparsed"
    parser_candidate = {
        "status": parser_status,
        "device_id": event.outage_device.device_id if event else None,
        "feeder": event.outage_device.feeder if event else None,
        "district": event.district if event else None,
        "event_time": event.event_time if event else None,
        "device_type": event.outage_device.device_type if event else None,
        "looks_like_outage": (event.parsed_fields or {}).get("looks_like_outage") if event else False,
    }
    flags = sorted(set(_coerce_flags(record.get("raw_redaction_flags")) + new_flags))
    corpus_row = {
        "training_id": stable_id("line-training", source_kind, message_ref, text[:120]),
        "source": source_kind,
        "source_kind": source_kind,
        "message_ref": message_ref,
        "created": record.get("created"),
        "text_sanitized": text,
        "chat_id_hash": record.get("chat_id_hash"),
        "sender_hash": record.get("sender_hash"),
        "roomDistrict": record.get("roomDistrict"),
        "consent_manifest_id": record.get("consent_manifest_id"),
        "raw_redaction_flags": flags,
        "parser_candidate": parser_candidate,
        "label_policy": "parser_training_only_not_customer_truth",
        "mode": "shadow",
        "production_send": "blocked",
    }
    audit_row = {
        "message_ref": message_ref,
        "source_kind": source_kind,
        "created": str(record.get("created") or ""),
        "status": "written",
        "parser_status": parser_status,
        "redaction_flags": ",".join(flags),
        "device_id": parser_candidate["device_id"] or "",
        "feeder": parser_candidate["feeder"] or "",
        "district": parser_candidate["district"] or "",
        "event_time": parser_candidate["event_time"] or "",
    }
    return corpus_row, audit_row


def _write_training_audit(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "message_ref",
        "source_kind",
        "created",
        "status",
        "parser_status",
        "redaction_flags",
        "device_id",
        "feeder",
        "district",
        "event_time",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_training_redaction_report(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# LINE Training Corpus Redaction Report",
        "",
        f"Status: `{report['status']}`",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Rows read | {report['rows_read']} |",
        f"| Rows written | {report['rows_written']} |",
        f"| Duplicates | {report['duplicates']} |",
        f"| Skipped | {report['skipped']} |",
        "",
        "## Source Counts",
        "",
        "| Source kind | Rows |",
        "| --- | ---: |",
    ]
    for key, count in report["source_counts"].items():
        lines.append(f"| `{key}` | {count} |")
    lines.extend(["", "## Parser Counts", "", "| Parser status | Rows |", "| --- | ---: |"])
    for key, count in report["parser_counts"].items():
        lines.append(f"| `{key}` | {count} |")
    lines.extend(["", "## Redaction Flags", "", "| Flag | Count |", "| --- | ---: |"])
    for key, count in report["redaction_counts"].items():
        lines.append(f"| `{key}` | {count} |")
    lines.extend(["", "## Leak Scan", "", "| Pattern | Count |", "| --- | ---: |"])
    for key, count in report["leak_scan"].items():
        lines.append(f"| `{key}` | {count} |")
    lines.extend(
        [
            "",
            "LINE text is parser-training evidence only. AIS outage/restore remains the customer-facing truth source.",
            "Mode remains `shadow`; production send remains `blocked`.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _scan_corpus_for_sensitive_patterns(path: Path) -> dict[str, int]:
    chunks: list[str] = []
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    chunks.append(line)
                    continue
                if isinstance(item, dict):
                    chunks.append(str(item.get("text_sanitized") or ""))
    text = "\n".join(chunks)
    return {
        "url": len(URL_RE.findall(text)),
        "email": len(EMAIL_RE.findall(text)),
        "phone": len(PHONE_RE.findall(text)),
        "mention": len(MENTION_RE.findall(text)),
        "long_number": len(LONG_NUMBER_RE.findall(text)),
        "line_id": len(LINE_ID_RE.findall(text)),
        "token_like": len(TOKEN_RE.findall(text)),
    }


def _coerce_flags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return [part.strip() for part in text.split(",") if part.strip()]
            if isinstance(data, list):
                return [str(item) for item in data if str(item).strip()]
        return [part.strip() for part in text.split(",") if part.strip()]
    return []


def _manifest_chat_surrogate(manifest_data: dict[str, Any]) -> str:
    return str(
        manifest_data.get("chat_id")
        or manifest_data.get("chat_name")
        or manifest_data.get("source_name")
        or manifest_data.get("manifest_id")
    )


def _canonical_source_kind(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {SOURCE_LINE, "line_group", "line_export", "line_regular"}:
        return SOURCE_LINE
    if text in {SOURCE_OPENCHAT_EXPORT, "line_openchat", "openchat", "open_chat"}:
        return SOURCE_OPENCHAT_EXPORT
    raise LineIngestError(f"unsupported LINE source_type: {value}")


def _department_controlled(data: dict[str, Any]) -> bool:
    return _truthy(
        data.get("department_controlled")
        or data.get("controlled_by_department")
        or data.get("owner_is_department")
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "approved"}


def _looks_like_webhook_event(raw: dict[str, Any]) -> bool:
    return isinstance(raw.get("message"), dict) and isinstance(raw.get("source"), dict)


def _first_present(raw: dict[str, Any], keys: tuple[str, ...]) -> Any | None:
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return value
    return None


def _timestamp_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000.0 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=0).isoformat()
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _timestamp_to_iso(int(text))
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _hash_identifier(value: Any, prefix: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:16]}"
