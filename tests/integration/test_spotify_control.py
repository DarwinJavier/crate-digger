"""Real ASGI transport checks, run separately from the dependency-free stub suite."""

import asyncio
import base64
import hashlib
import json
import os
import threading
import time
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException

from spotify_control import COOKIE, PENDING_COOKIE, SCOPES, SpotifyControl, register_spotify

TRACK = "spotify:track:" + "a" * 22
PLAYLIST = "b" * 22


class SpotifyTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.control = register_spotify(self.app, "test-client", "http://127.0.0.1:8000/spotify/callback")
        self.session = {
            "expires": time.time() + 3600, "token_expires": time.time() + 3600,
            "access_token": "private-token", "refresh_token": "private-refresh",
            "csrf": "csrf-test", "account": {"id": "owner", "name": "Listener"},
            "lock": threading.RLock(),
        }
        self.control.sessions["test-session"] = self.session

    def call(self, path, *, method="GET", data=None, cookies=None, headers=None, host="127.0.0.1:8000"):
        """Exercise routing, request validation, cookies, errors, and serialization."""
        body = json.dumps(data).encode() if data is not None else b""
        parsed = urlsplit(path)
        fields = {"host": host, **(headers or {})}
        if data is not None:
            fields["content-type"] = "application/json"
        if cookies:
            fields["cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())
        messages = []

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": method, "scheme": "http", "path": parsed.path,
                 "raw_path": parsed.path.encode(), "query_string": parsed.query.encode(),
                 "root_path": "", "headers": [(key.encode(), value.encode()) for key, value in fields.items()],
                 "server": ("127.0.0.1", 8000), "client": ("127.0.0.1", 12345)}
        asyncio.run(self.app(scope, receive, send))
        response = next(message for message in messages if message["type"] == "http.response.start")
        content = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        response_headers = [(key.decode(), value.decode()) for key, value in response["headers"]]
        return response["status"], response_headers, content

    def action(self, data, **kwargs):
        return self.call("/spotify/action", method="POST", data=data,
                         cookies={COOKIE: "test-session"},
                         headers={"origin": self.control.origin, "x-spotify-csrf": "csrf-test"}, **kwargs)

    def test_disabled_and_wrong_host(self):
        self.control.configured = False
        status, headers, body = self.call("/spotify/status")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"configured": False, "connected": False})
        self.assertIn(("cache-control", "no-store"), headers)
        self.assertEqual(self.call("/spotify/connect")[0], 503)
        self.control.configured = True
        self.assertEqual(self.call("/spotify/status", host="attacker.example")[0], 403)

    def test_redirect_validation(self):
        for uri in ("http://localhost:8000/spotify/callback", "http://example.com/spotify/callback",
                    "https://example.com/evil", "https://example.com/spotify/callback?next=evil"):
            with self.assertRaises(ValueError):
                SpotifyControl("client", uri)

    def test_pkce_callback_binding_rotation_and_replay(self):
        status, headers, _ = self.call("/spotify/connect")
        self.assertEqual(status, 303)
        query = parse_qs(urlsplit(dict(headers)["location"]).query)
        state = query["state"][0]
        pending = self.control.pending[state]
        verifier = pending["verifier"]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(query["code_challenge"], [challenge])
        self.assertEqual(set(query["scope"][0].split()), SCOPES)
        self.assertNotIn("client_secret", query)
        cookie_header = next(value for key, value in headers if key == "set-cookie")
        self.assertIn("HttpOnly", cookie_header)
        self.assertIn("SameSite=lax", cookie_header)
        callback = f"/spotify/callback?state={state}&code=one-use-code"
        self.assertEqual(self.call(callback)[0], 400)
        self.assertIn(state, self.control.pending)
        token = {"access_token": "secret", "refresh_token": "refresh", "token_expires": time.time() + 3600,
                 "scope": " ".join(SCOPES)}
        with patch.object(self.control, "exchange", return_value=token) as exchange, patch.object(
            self.control, "api", return_value={"id": "owner", "display_name": "Listener"}
        ):
            status, headers, body = self.call(callback, cookies={PENDING_COOKIE: pending["nonce"], COOKIE: "test-session"})
        self.assertEqual(status, 303)
        exchange.assert_called_once()
        self.assertEqual(exchange.call_args.args[0]["code_verifier"], verifier)
        self.assertNotIn("test-session", self.control.sessions)
        self.assertNotIn(state, self.control.pending)
        self.assertNotIn(b"secret", body)
        self.assertEqual(self.call(callback, cookies={PENDING_COOKIE: pending["nonce"]})[0], 400)

    def test_denial_and_expired_session(self):
        self.control.pending["state"] = {"nonce": "browser", "expires": time.time() + 60}
        self.assertEqual(self.call("/spotify/callback?state=state&error=access_denied",
                                   cookies={PENDING_COOKIE: "browser"})[0], 303)
        self.session["expires"] = time.time() - 1
        self.assertFalse(json.loads(self.call("/spotify/status", cookies={COOKIE: "test-session"})[2])["connected"])

    def test_status_never_exposes_tokens(self):
        status, _, body = self.call("/spotify/status", cookies={COOKIE: "test-session"})
        self.assertEqual(status, 200)
        self.assertNotIn(b"private-token", body)
        self.assertNotIn(b"private-refresh", body)
        self.assertEqual(json.loads(body)["csrf"], "csrf-test")

    def test_actions_require_session_origin_and_csrf(self):
        with patch.object(self.control, "api") as upstream:
            self.assertEqual(self.call("/spotify/action", method="POST", data={"action": "pause"})[0], 403)
            for headers in ({"origin": "https://attacker.example", "x-spotify-csrf": "csrf-test"},
                            {"origin": self.control.origin}):
                self.assertEqual(self.call("/spotify/action", method="POST", data={"action": "pause"},
                                           cookies={COOKIE: "test-session"}, headers=headers)[0], 403)
            upstream.assert_not_called()

    def test_track_and_path_validation_before_mutation(self):
        with patch.object(self.control, "api") as upstream:
            for data in ({"action": "queue", "uris": []}, {"action": "play", "uris": ["https://evil"]},
                         {"action": "play", "uris": [TRACK] * 101}, {"action": "arbitrary"},
                         {"action": "pause", "path": "/me"}, {"action": ["pause"]},
                         {"action": "create_playlist", "name": "Mix", "uris": []}):
                self.assertEqual(self.action(data)[0], 400)
            upstream.assert_not_called()

    def test_private_playlist_creation_and_current_items_endpoint(self):
        playlist = {"id": PLAYLIST, "type": "playlist", "name": "Mix"}
        with patch.object(self.control, "api", side_effect=[playlist, {"snapshot_id": "ok"}]) as upstream:
            status, _, body = self.action({"action": "create_playlist", "name": "Mix", "uris": [TRACK]})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["added"], 1)
        self.assertEqual(upstream.call_args_list[0].args[2], "/me/playlists")
        self.assertFalse(upstream.call_args_list[0].kwargs["body"]["public"])
        self.assertEqual(upstream.call_args_list[1].args[2], f"/playlists/{PLAYLIST}/items")

    def test_playlist_partial_success_reports_existing_destination(self):
        playlist = {"id": PLAYLIST, "type": "playlist", "name": "Mix"}
        with patch.object(self.control, "api", side_effect=[playlist, HTTPException(429, "quota")]):
            status, _, body = self.action({"action": "create_playlist", "name": "Mix", "uris": [TRACK]})
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(body)["playlist"]["id"], PLAYLIST)
        self.assertFalse(json.loads(body)["ok"])

    def test_cannot_modify_public_or_someone_elses_playlist(self):
        for playlist in ({"public": True, "owner": {"id": "owner"}},
                         {"public": False, "owner": {"id": "someone-else"}}):
            with patch.object(self.control, "api", return_value=playlist) as upstream:
                self.assertEqual(self.action({"action": "add_to_playlist", "playlist_id": PLAYLIST, "uris": [TRACK]})[0], 403)
                self.assertEqual(upstream.call_count, 1)

    def test_player_absent_item_and_queue_device(self):
        with patch.object(self.control, "api", side_effect=[{"item": None}, {"devices": []}]):
            self.assertEqual(self.call("/spotify/player", cookies={COOKIE: "test-session"})[0], 200)
        with patch.object(self.control, "api", return_value={}) as upstream:
            self.assertEqual(self.action({"action": "queue", "uris": [TRACK], "device_id": "speaker"})[0], 200)
            self.assertEqual(upstream.call_args.kwargs["params"], {"uri": TRACK, "device_id": "speaker"})

    def test_refresh_and_no_automatic_retry_on_rate_limit(self):
        self.session["token_expires"] = 0
        response = Mock(status_code=429, headers={"Retry-After": "60"})
        with patch.object(self.control, "exchange", return_value={"access_token": "new", "token_expires": time.time() + 3600}), patch(
            "spotify_control.requests.request", return_value=response
        ) as upstream:
            with self.assertRaises(HTTPException) as caught:
                self.control.api(self.session, "POST", "/me/player/next")
            self.assertEqual(caught.exception.status_code, 429)
            self.assertEqual(caught.exception.headers["Retry-After"], "60")
            self.assertEqual(upstream.call_count, 1)
            self.assertEqual(upstream.call_args.kwargs["headers"]["Authorization"], "Bearer new")
            self.assertFalse(upstream.call_args.kwargs["allow_redirects"])
            self.assertEqual(self.session["refresh_token"], "private-refresh")

    def test_disconnect_removes_server_session(self):
        status, headers, _ = self.call("/spotify/disconnect", method="POST", data={},
                                      cookies={COOKIE: "test-session"},
                                      headers={"origin": self.control.origin, "x-spotify-csrf": "csrf-test"})
        self.assertEqual(status, 200)
        self.assertNotIn("test-session", self.control.sessions)
        self.assertTrue(any("Max-Age=0" in value for key, value in headers if key == "set-cookie"))

    def test_real_app_health_and_recommendation_contracts(self):
        with patch.dict(os.environ, {"CRATE_DIGGER_SKIP_DOTENV": "1", "OPENAI_API_KEY": "",
                                    "MUSICBRAINZ_CONTACT": "", "LASTFM_API_KEY": "",
                                    "ANTHROPIC_API_KEY": "", "SPOTIFY_CLIENT_ID": "", "PUBLIC_MODE": "false"}):
            import app as application
        self.app = application.app
        with patch("requests.get", side_effect=AssertionError("unexpected network call")), patch(
            "requests.post", side_effect=AssertionError("unexpected network call")
        ):
            status, _, body = self.call("/health")
            health = json.loads(body)
            self.assertEqual(status, 200)
            self.assertTrue(health["ok"])
            self.assertGreater(health["albums"], 0)
            payload = {"brief": "nocturnal elegant reverb-drenched", "seeds": [{"artist": "The Cure"}],
                       "novelty": "non_obvious", "use_lastfm": False,
                       "features": {"outside_discovery": False}}
            status, _, body = self.call("/recommendations", method="POST", data=payload)
            self.assertEqual(status, 200, body)
            results = json.loads(body)["results"]
            self.assertGreaterEqual(len(results), 3)
            self.assertTrue(all(result["reasons"] for result in results))
            payload["hard_constraints"] = {"year_min": 2030}
            status, _, body = self.call("/recommendations", method="POST", data=payload)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["coverage"]["status"], "no_match")
            payload["hard_constraints"] = {}
            payload["seeds"] = [{"artist": "Taylor Swift"}]
            status, _, body = self.call("/recommendations", method="POST", data=payload)
            self.assertEqual(status, 200)
            response = json.loads(body)
            self.assertIn(response["seeds"][0]["status"], {"unknown", "known_outside_corpus"})
            for path in ("/listen", "/spotify"):
                status, _, body = self.call(path)
                self.assertEqual(status, 200)
                self.assertIn(b"Spotify", body)


if __name__ == "__main__":
    unittest.main()
