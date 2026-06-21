from __future__ import annotations

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any


DEFAULT_PATH = "/api/v1/etr-notifications"
MAX_BODY_BYTES = 1_000_000
SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "client_secret",
    "authorization",
    "token",
    "secret",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _count_by(values: list[str | None]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        label = value or "<missing>"
        counts[label] = counts.get(label, 0) + 1
    return counts


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep shadow evidence useful without storing PEANO lists or secrets."""
    redacted = _redact_value(payload)
    if not isinstance(redacted, dict):
        return {"payload_type": type(payload).__name__}

    source = redacted.get("source")
    if isinstance(source, dict) and source.get("room_id"):
        source["room_id"] = "REDACTED"

    affected = payload.get("affected_customers") or []
    if isinstance(affected, list):
        redacted["affected_customer_count"] = len(affected)
        redacted["affected_match_levels"] = _count_by(
            [item.get("match_level") for item in affected if isinstance(item, dict)]
        )
        redacted.pop("affected_customers", None)
    return redacted


def _redact_value(value: Any, key: str | None = None) -> Any:
    if key and key.lower() in SENSITIVE_KEYS:
        return "REDACTED"
    if key and key.lower() == "peano":
        return "REDACTED"
    if isinstance(value, dict):
        return {name: _redact_value(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, key) for item in value]
    return value


class MockWebhookHandler(BaseHTTPRequestHandler):
    server_version = "AisEtrMockWebhook/1.0"

    def do_POST(self) -> None:
        if self.path != getattr(self.server, "notification_path", DEFAULT_PATH):
            self._send_json(404, {"status": "NOT_FOUND"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"status": "INVALID_CONTENT_LENGTH"})
            return
        if length > MAX_BODY_BYTES:
            self._send_json(413, {"status": "PAYLOAD_TOO_LARGE"})
            return

        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            self._send_json(400, {"status": "INVALID_JSON"})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"status": "INVALID_PAYLOAD"})
            return
        if payload.get("mode") != "shadow":
            self._send_json(400, {"status": "REJECTED_NON_SHADOW"})
            return

        received_at = utc_now_iso()
        event = {
            "received_at": received_at,
            "path": self.path,
            "payload": redact_payload(payload),
        }
        output_path: Path = getattr(self.server, "output_path")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        self._send_json(200, {"status": "CAPTURED", "received_at": received_at})

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def create_mock_webhook_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    output_path: str | Path = "runtime/mock_webhook_events.jsonl",
    notification_path: str = DEFAULT_PATH,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), MockWebhookHandler)
    server.output_path = Path(output_path)  # type: ignore[attr-defined]
    server.notification_path = notification_path  # type: ignore[attr-defined]
    return server


def serve_mock_webhook(
    host: str = "127.0.0.1",
    port: int = 8080,
    output_path: str | Path = "runtime/mock_webhook_events.jsonl",
    notification_path: str = DEFAULT_PATH,
) -> None:
    server = create_mock_webhook_server(host, port, output_path, notification_path)
    try:
        server.serve_forever()
    finally:
        server.server_close()
