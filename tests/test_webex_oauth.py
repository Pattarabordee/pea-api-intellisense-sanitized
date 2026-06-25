import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import urllib.parse

from ais_etr.config import Settings
from ais_etr.operations import validate_env
from ais_etr.webex import (
    WebexClient,
    WebexOAuthError,
    WebexOAuthTokenManager,
    build_authorization_url,
    generate_pkce_pair,
    validate_oauth_callback,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class WebexOAuthTests(unittest.TestCase):
    def test_authorization_url_includes_state_redirect_scopes_and_pkce(self):
        verifier, challenge = generate_pkce_pair()
        url = build_authorization_url(
            client_id="client-id",
            redirect_uri="http://127.0.0.1:8765/oauth/callback",
            scopes=("spark:rooms_read", "spark:messages_read"),
            state="state-123",
            code_challenge=challenge,
        )
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))

        self.assertEqual(query["response_type"], "code")
        self.assertEqual(query["client_id"], "client-id")
        self.assertEqual(query["redirect_uri"], "http://127.0.0.1:8765/oauth/callback")
        self.assertEqual(query["scope"], "spark:rooms_read spark:messages_read")
        self.assertEqual(query["state"], "state-123")
        self.assertEqual(query["code_challenge"], challenge)
        self.assertEqual(query["code_challenge_method"], "S256")
        self.assertGreater(len(verifier), 40)

    def test_callback_rejects_state_mismatch(self):
        with self.assertRaises(WebexOAuthError):
            validate_oauth_callback({"state": "wrong", "code": "abc"}, "expected")

    def test_token_exchange_and_refresh_store_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "webex_token.json"
            manager = WebexOAuthTokenManager("cid", "secret", token_path)
            requests = []

            def fake_urlopen(req, timeout=30):
                requests.append(req)
                return FakeResponse(
                    {
                        "access_token": "access-1",
                        "refresh_token": "refresh-1",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "refresh_token_expires_in": 86400,
                        "scope": "spark:rooms_read spark:messages_read",
                    }
                )

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                token = manager.exchange_code("auth-code", "http://127.0.0.1/callback", "verifier")

            stored = json.loads(token_path.read_text(encoding="utf-8"))
            body = urllib.parse.parse_qs(requests[0].data.decode("utf-8"))
            self.assertEqual(body["grant_type"], ["authorization_code"])
            self.assertEqual(body["code_verifier"], ["verifier"])
            self.assertEqual(stored["access_token"], "access-1")
            self.assertEqual(stored["refresh_token"], "refresh-1")
            self.assertIn("expires_at", stored)
            self.assertEqual(token["token_type"], "Bearer")

            def fake_refresh(req, timeout=30):
                requests.append(req)
                return FakeResponse(
                    {
                        "access_token": "access-2",
                        "refresh_token": "refresh-2",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "refresh_token_expires_in": 86400,
                    }
                )

            with patch("urllib.request.urlopen", side_effect=fake_refresh):
                refreshed = manager.refresh_access_token()
            body = urllib.parse.parse_qs(requests[-1].data.decode("utf-8"))
            self.assertEqual(body["grant_type"], ["refresh_token"])
            self.assertEqual(body["refresh_token"], ["refresh-1"])
            self.assertEqual(refreshed["access_token"], "access-2")

    def test_access_token_auto_refreshes_when_expired(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "webex_token.json"
            token_path.write_text(
                json.dumps(
                    {
                        "access_token": "expired-access",
                        "refresh_token": "refresh-1",
                        "expires_at": 1,
                    }
                ),
                encoding="utf-8",
            )
            manager = WebexOAuthTokenManager("cid", "secret", token_path)

            def fake_refresh(req, timeout=30):
                return FakeResponse(
                    {
                        "access_token": "fresh-access",
                        "refresh_token": "fresh-refresh",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    }
                )

            with patch("urllib.request.urlopen", side_effect=fake_refresh):
                token = manager.access_token()

            self.assertEqual(token, "fresh-access")

    def test_oauth_polling_omits_mentioned_people_and_bot_polling_keeps_it(self):
        requests = []

        def fake_urlopen(req, timeout=30):
            requests.append(req)
            return FakeResponse({"items": []})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            WebexClient(token_provider=lambda: "oauth-token", room_id="room-1", require_mention=False).list_messages(
                before_message="message-123"
            )
            WebexClient(bot_token="bot-token", room_id="room-2", require_mention=True).list_messages()
            WebexClient(token_provider=lambda: "oauth-token").list_rooms(query="outage")

        oauth_query = urllib.parse.parse_qs(urllib.parse.urlparse(requests[0].full_url).query)
        bot_query = urllib.parse.parse_qs(urllib.parse.urlparse(requests[1].full_url).query)
        rooms_path = urllib.parse.urlparse(requests[2].full_url).path

        self.assertNotIn("mentionedPeople", oauth_query)
        self.assertEqual(oauth_query["beforeMessage"], ["message-123"])
        self.assertEqual(bot_query["mentionedPeople"], ["me"])
        self.assertEqual(rooms_path, "/v1/rooms")

    def test_validate_env_accepts_oauth_config_with_token_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            token = root / "runtime" / "token.json"
            token.parent.mkdir()
            token.write_text(
                json.dumps({"access_token": "x", "refresh_token": "y", "expires_at": 9999999999}),
                encoding="utf-8",
            )
            settings = Settings(
                workspace=root,
                webex_auth_mode="oauth",
                webex_client_id="cid",
                webex_client_secret="secret",
                webex_room_id="room",
                webex_token_path=Path("runtime/token.json"),
                notification_mode="shadow",
            )
            result = validate_env(settings, root / ".env")
            self.assertTrue(result["ok"])
            self.assertEqual(result["missing"], [])
            self.assertEqual(result["webex_auth_mode"], "oauth")
            self.assertTrue(result["webex_token"]["exists"])


if __name__ == "__main__":
    unittest.main()
