from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_AUTHORIZE_URL = "https://webexapis.com/v1/authorize"
DEFAULT_TOKEN_REFRESH_MARGIN_SECONDS = 300


class WebexOAuthError(RuntimeError):
    pass


def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def build_authorization_url(
    client_id: str,
    redirect_uri: str,
    scopes: tuple[str, ...],
    state: str,
    code_challenge: str,
    authorization_url: str = DEFAULT_AUTHORIZE_URL,
) -> str:
    parsed = urllib.parse.urlparse(authorization_url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def validate_oauth_callback(params: dict[str, str], expected_state: str) -> str:
    if params.get("error"):
        detail = params.get("error_description") or params["error"]
        raise WebexOAuthError(f"Webex authorization failed: {detail}")
    if params.get("state") != expected_state:
        raise WebexOAuthError("OAuth state mismatch; authorization response was rejected")
    code = params.get("code")
    if not code:
        raise WebexOAuthError("OAuth callback did not include an authorization code")
    return code


class WebexOAuthTokenManager:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_path: str | Path,
        api_base: str = "https://webexapis.com/v1",
        timeout: int = 30,
        refresh_margin_seconds: int = DEFAULT_TOKEN_REFRESH_MARGIN_SECONDS,
    ):
        self.client_id = client_id
        self.client_secret = "<REDACTED_SECRET>"
        self.token_path = Path(token_path)
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self.refresh_margin_seconds = refresh_margin_seconds

    @property
    def token_url(self) -> str:
        return f"{self.api_base}/access_token"

    def load(self) -> dict[str, Any]:
        if not self.token_path.exists():
            return {}
        return json.loads(self.token_path.read_text(encoding="utf-8-sig"))

    def save_token_response(self, response: dict[str, Any], now: int | None = None) -> dict[str, Any]:
        now = int(time.time()) if now is None else now
        existing = self.load()
        refresh_token = "<REDACTED_SECRET>"refresh_token") or existing.get("refresh_token")
        token = {
            "access_token": response.get("access_token"),
            "refresh_token": refresh_token,
            "token_type": response.get("token_type"),
            "scope": response.get("scope"),
            "expires_in": response.get("expires_in"),
            "refresh_token_expires_in": response.get("refresh_token_expires_in"),
            "obtained_at": now,
            "expires_at": now + int(response.get("expires_in") or 0),
        }
        if response.get("refresh_token_expires_in") is not None:
            token["refresh_expires_at"] = now + int(response["refresh_token_expires_in"])
        elif existing.get("refresh_expires_at") is not None:
            token["refresh_expires_at"] = existing["refresh_expires_at"]
        if not token["access_token"]:
            raise WebexOAuthError("Webex token response did not include an access token")
        if not token["refresh_token"]:
            raise WebexOAuthError("Webex token response did not include a refresh token")

        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(json.dumps(token, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        try:
            os.chmod(self.token_path, 0o600)
        except OSError:
            pass
        return token

    def token_metadata(self) -> dict[str, Any]:
        token = "<REDACTED_SECRET>"
        return {
            "token_path": str(self.token_path),
            "exists": bool(token),
            "expires_at": token.get("expires_at"),
            "refresh_expires_at": token.get("refresh_expires_at"),
            "scope": token.get("scope"),
            "token_type": token.get("token_type"),
        }

    def access_token(self) -> str:
        token = "<REDACTED_SECRET>"
        if token.get("access_token") and self._valid_access_token(token):
            return str(token["access_token"])
        refreshed = self.refresh_access_token()
        return str(refreshed["access_token"])

    def exchange_code(self, code: str, redirect_uri: str, code_verifier: str) -> dict[str, Any]:
        response = _post_form(
            self.token_url,
            {
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            timeout=self.timeout,
        )
        return self.save_token_response(response)

    def refresh_access_token(self) -> dict[str, Any]:
        token = "<REDACTED_SECRET>"
        refresh_token = "<REDACTED_SECRET>"refresh_token")
        if not refresh_token:
            raise WebexOAuthError("No Webex refresh token is stored; run webex-auth again")
        response = _post_form(
            self.token_url,
            {
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token,
            },
            timeout=self.timeout,
        )
        return self.save_token_response(response)

    def _valid_access_token(self, token: "<REDACTED_SECRET>" Any]) -> bool:
        expires_at = token.get("expires_at")
        if expires_at is None:
            return False
        return int(expires_at) - self.refresh_margin_seconds > int(time.time())


def _post_form(url: str, data: dict[str, str], timeout: int = 30) -> dict[str, Any]:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=encoded,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    return _request_json(req, timeout=timeout)


def _request_json(req: urllib.request.Request, timeout: int = 30) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Webex API error {exc.code}: {body}") from exc


class WebexClient:
    def __init__(
        self,
        bot_token: str | None = None,
        room_id: str | None = None,
        api_base: str = "https://webexapis.com/v1",
        require_mention: bool = True,
        token_provider: Callable[[], str] | None = None,
        timeout: int = 30,
    ):
        self.bot_token = bot_token
        self.room_id = room_id
        self.api_base = api_base.rstrip("/")
        self.require_mention = require_mention
        self.token_provider = token_provider
        self.timeout = timeout

    def list_messages(
        self,
        max_items: int = 50,
        before: str | None = None,
        before_message: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.room_id:
            raise RuntimeError("WEBEX_ROOM_ID is required for polling messages")
        params = {
            "roomId": self.room_id,
            "max": str(max_items),
        }
        if self.require_mention:
            params["mentionedPeople"] = "me"
        if before:
            params["before"] = before
        if before_message:
            params["beforeMessage"] = before_message
        url = f"{self.api_base}/messages?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Accept": "application/json",
            },
        )
        data = _request_json(req, timeout=self.timeout)
        return list(data.get("items", []))

    def list_rooms(self, max_items: int = 100, query: str | None = None) -> list[dict[str, Any]]:
        params = {"max": str(max_items)}
        url = f"{self.api_base}/rooms?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Accept": "application/json",
            },
        )
        data = _request_json(req, timeout=self.timeout)
        rooms = list(data.get("items", []))
        if query:
            needle = query.lower()
            rooms = [room for room in rooms if needle in str(room.get("title", "")).lower()]
        return rooms

    def _token(self) -> str:
        if self.token_provider is not None:
            return self.token_provider()
        if self.bot_token:
            return self.bot_token
        raise RuntimeError("A Webex token or token provider is required")


class NullWebexClient:
    """Test helper and offline fallback."""

    def __init__(self, messages: list[dict[str, Any]] | None = None):
        self.messages = messages or []

    def list_messages(
        self,
        max_items: int = 50,
        before: str | None = None,
        before_message: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.messages[:max_items]
