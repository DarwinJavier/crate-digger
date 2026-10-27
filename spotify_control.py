"""Optional Spotify transport. No corpus, recommendation, or LLM dependencies.

Tokens and search results live only in process memory. A restart disconnects users.
This deliberately supports one worker, with bounded sessions and no new dependencies.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from spotify_ui import spotify_page

API_ROOT = "https://api.spotify.com/v1"
TOKEN_URL = "https://accounts.spotify.com/api/token"
COOKIE = "crate_spotify"
PENDING_COOKIE = "crate_spotify_oauth"
SCOPES = {
    "playlist-read-private", "playlist-modify-private",
    "user-read-playback-state", "user-modify-playback-state",
}
SESSION_SECONDS = 8 * 60 * 60
PENDING_SECONDS = 600
MAX_SESSIONS = 100
SPOTIFY_ID = re.compile(r"[A-Za-z0-9]{22}\Z")
TRACK_URI = re.compile(r"spotify:track:[A-Za-z0-9]{22}\Z")
CONTEXT_URI = re.compile(r"spotify:(?:album|playlist):[A-Za-z0-9]{22}\Z")


def json_response(value: Any, status_code: int = 200) -> Response:
    return Response(json.dumps(value), status_code=status_code,
                    media_type="application/json", headers={"Cache-Control": "no-store"})


def item_view(item: dict[str, Any]) -> dict[str, Any]:
    """Return only fields needed for a human to choose a Spotify destination."""
    kind = item.get("type")
    identifier = item.get("id", "")
    if kind not in {"track", "album", "playlist"} or not SPOTIFY_ID.fullmatch(identifier):
        raise HTTPException(502, "Spotify returned an invalid item.")
    return {
        "id": identifier, "uri": f"spotify:{kind}:{identifier}", "type": kind,
        "name": item.get("name", ""),
        "artists": ", ".join(artist.get("name", "") for artist in item.get("artists", [])),
        "album": item.get("album", {}).get("name", ""),
        "url": f"https://open.spotify.com/{kind}/{identifier}",
    }


class SpotifyControl:
    def __init__(self, client_id: str, redirect_uri: str) -> None:
        self.client_id = client_id.strip()
        self.redirect_uri = redirect_uri.strip()
        parsed = urlsplit(self.redirect_uri)
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.secure = parsed.scheme == "https"
        self.configured = bool(self.client_id)
        if self.configured and (
            parsed.scheme not in {"http", "https"} or not parsed.hostname
            or (not self.secure and parsed.hostname not in {"127.0.0.1", "::1"})
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path != "/spotify/callback"
        ):
            raise ValueError("SPOTIFY_REDIRECT_URI must use HTTPS or HTTP loopback and /spotify/callback.")
        self.sessions: dict[str, dict[str, Any]] = {}
        self.pending: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()

    def prune(self) -> None:
        with self.lock:
            now = time.time()
            for collection in (self.sessions, self.pending):
                for key in list(collection):
                    if collection[key]["expires"] <= now:
                        del collection[key]

    def require_origin(self, request: Request, write: bool = False) -> None:
        if not self.configured:
            raise HTTPException(503, "Spotify is not configured. Set SPOTIFY_CLIENT_ID on the server.")
        if str(request.base_url).rstrip("/") != self.origin:
            raise HTTPException(403, "Open Crate Digger at the origin registered for Spotify.")
        if write and request.headers.get("origin") != self.origin:
            raise HTTPException(403, "Spotify actions require a request from this app.")

    def session(self, request: Request, write: bool = False) -> dict[str, Any]:
        self.require_origin(request, write)
        self.prune()
        with self.lock:
            session = self.sessions.get(request.cookies.get(COOKIE, ""))
        if not session:
            raise HTTPException(401, "Connect Spotify first. Reconnect after a server restart.")
        if write and not hmac.compare_digest(request.headers.get("x-spotify-csrf", ""), session["csrf"]):
            raise HTTPException(403, "Invalid Spotify action token. Reload the page.")
        return session

    def exchange(self, values: dict[str, str]) -> dict[str, Any]:
        try:
            response = requests.post(TOKEN_URL, data={"client_id": self.client_id, **values},
                                     timeout=20, allow_redirects=False)
            if response.status_code != 200:
                raise HTTPException(401, "Spotify authorization expired or failed. Connect again.")
            token = response.json()
            if not isinstance(token.get("access_token"), str) or not token["access_token"]:
                raise ValueError("missing token")
            token["token_expires"] = time.time() + max(0, float(token["expires_in"]) - 60)
            return token
        except (requests.RequestException, ValueError, KeyError, TypeError):
            raise HTTPException(502, "Could not complete Spotify authorization. Try connecting again.") from None

    def api(self, session: dict[str, Any], method: str, path: str,
            *, params: dict[str, Any] | None = None, body: Any = None) -> Any:
        """Never follow upstream redirects or automatically retry mutations."""
        with session["lock"]:
            if session["token_expires"] <= time.time():
                if not session.get("refresh_token"):
                    raise HTTPException(401, "Spotify authorization expired. Connect again.")
                token = self.exchange({"grant_type": "refresh_token", "refresh_token": session["refresh_token"]})
                session.update({key: token[key] for key in ("access_token", "refresh_token", "token_expires") if key in token})
            try:
                response = requests.request(
                    method, API_ROOT + path, params=params, json=body,
                    headers={"Authorization": f"Bearer {session['access_token']}"},
                    timeout=20, allow_redirects=False,
                )
            except requests.RequestException:
                raise HTTPException(502, "Spotify did not respond. An action may have completed; check Spotify before retrying.") from None
            status = response.status_code
            if status == 429:
                retry = response.headers.get("Retry-After", "")
                headers = {"Retry-After": retry} if retry.isdigit() else {}
                raise HTTPException(429, "Spotify's request quota was reached. Wait before retrying.", headers=headers)
            if status == 401:
                raise HTTPException(401, "Spotify authorization expired or was revoked. Connect again.")
            if status == 403:
                raise HTTPException(403, "Spotify denied this action. Check app allowlisting, granted permissions, Premium, and endpoint access.")
            if status == 404:
                raise HTTPException(404, "Spotify item or device unavailable. For playback, open Spotify and start a track first.")
            if not 200 <= status < 300:
                raise HTTPException(502, "Spotify could not complete the action. Check Spotify before retrying.")
            if status == 204 or not response.content:
                return {}
            try:
                return response.json()
            except ValueError:
                raise HTTPException(502, "Spotify returned an unreadable response.") from None


def register_spotify(app: FastAPI, client_id: str, redirect_uri: str) -> SpotifyControl:
    control = SpotifyControl(client_id, redirect_uri)

    @app.get("/spotify", response_class=HTMLResponse)
    def home() -> HTMLResponse:
        return HTMLResponse(spotify_page(), headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    @app.get("/spotify/status")
    def status(request: Request) -> Response:
        if not control.configured:
            return json_response({"configured": False, "connected": False})
        control.require_origin(request)
        control.prune()
        with control.lock:
            session = control.sessions.get(request.cookies.get(COOKIE, ""))
            return json_response({"configured": True, "connected": bool(session),
                                  "csrf": session["csrf"] if session else None,
                                  "account": session["account"] if session else None})

    @app.get("/spotify/connect")
    def connect(request: Request) -> RedirectResponse:
        control.require_origin(request)
        control.prune()
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        browser_nonce = secrets.token_urlsafe(32)
        with control.lock:
            if len(control.pending) >= MAX_SESSIONS:
                raise HTTPException(429, "Too many pending connections. Try again later.")
            control.pending[state] = {"verifier": verifier, "nonce": browser_nonce,
                                      "expires": time.time() + PENDING_SECONDS}
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        query = urlencode({"client_id": control.client_id, "response_type": "code",
                           "redirect_uri": control.redirect_uri, "state": state,
                           "code_challenge_method": "S256", "code_challenge": challenge,
                           "scope": " ".join(sorted(SCOPES))})
        response = RedirectResponse("https://accounts.spotify.com/authorize?" + query, status_code=303)
        response.set_cookie(PENDING_COOKIE, browser_nonce, max_age=PENDING_SECONDS,
                            httponly=True, secure=control.secure, samesite="lax", path="/spotify")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/spotify/callback")
    def callback(request: Request, state: str = "", code: str = "", error: str = "") -> RedirectResponse:
        control.require_origin(request)
        control.prune()
        with control.lock:
            pending = control.pending.get(state)
            if not pending or not hmac.compare_digest(pending["nonce"], request.cookies.get(PENDING_COOKIE, "")):
                raise HTTPException(400, "Spotify connection state invalid or expired. Start again.")
            del control.pending[state]
        if error:
            response = RedirectResponse("/spotify?connection=denied", status_code=303)
        else:
            if not code or len(code) > 4096:
                raise HTTPException(400, "Spotify authorization code missing or invalid.")
            token = control.exchange({"grant_type": "authorization_code", "code": code,
                                      "redirect_uri": control.redirect_uri, "code_verifier": pending["verifier"]})
            if not SCOPES.issubset(set(token.get("scope", "").split())):
                raise HTTPException(403, "Spotify permissions are incomplete. Connect again and grant the requested permissions.")
            session = {**token, "expires": time.time() + SESSION_SECONDS,
                       "csrf": secrets.token_urlsafe(32), "lock": threading.RLock()}
            profile = control.api(session, "GET", "/me")
            session["account"] = {"id": profile["id"], "name": profile.get("display_name") or profile["id"]}
            session_id = secrets.token_urlsafe(32)
            with control.lock:
                old_id = request.cookies.get(COOKIE, "")
                if len(control.sessions) >= MAX_SESSIONS and old_id not in control.sessions:
                    raise HTTPException(429, "Spotify session capacity reached. Try again later.")
                control.sessions.pop(old_id, None)
                control.sessions[session_id] = session
            response = RedirectResponse("/spotify?connection=ok", status_code=303)
            response.set_cookie(COOKIE, session_id, max_age=SESSION_SECONDS, httponly=True,
                                secure=control.secure, samesite="lax", path="/spotify")
        response.delete_cookie(PENDING_COOKIE, path="/spotify")
        response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
        return response

    @app.post("/spotify/disconnect")
    def disconnect(request: Request) -> Response:
        control.session(request, write=True)
        with control.lock:
            control.sessions.pop(request.cookies.get(COOKIE, ""), None)
        response = json_response({"connected": False})
        response.delete_cookie(COOKIE, path="/spotify")
        return response

    @app.get("/spotify/search")
    def search(request: Request, q: str = "", kind: str = "track") -> Response:
        session = control.session(request)
        if kind not in {"track", "album"} or not 1 <= len(q.strip()) <= 200:
            raise HTTPException(400, "Enter a search of 1-200 characters and choose tracks or albums.")
        result = control.api(session, "GET", "/search", params={"q": q.strip(), "type": kind, "limit": 10})
        return json_response({"items": [item_view(item) for item in result.get(kind + "s", {}).get("items", [])],
                              "provider": "spotify", "purpose": "listening_selection"})

    @app.get("/spotify/albums/{album_id}/tracks")
    def album_tracks(request: Request, album_id: str, offset: int = 0) -> Response:
        session = control.session(request)
        if not SPOTIFY_ID.fullmatch(album_id) or not 0 <= offset <= 10000:
            raise HTTPException(400, "Invalid album or track offset.")
        result = control.api(session, "GET", f"/albums/{album_id}/tracks", params={"limit": 50, "offset": offset})
        items = [item_view(item) for item in result.get("items", [])]
        next_offset = offset + len(items) if result.get("next") and items else None
        return json_response({"items": items, "next_offset": next_offset})

    @app.get("/spotify/playlists")
    def playlists(request: Request, offset: int = 0) -> Response:
        session = control.session(request)
        if not 0 <= offset <= 11000:
            raise HTTPException(400, "Invalid playlist offset.")
        result = control.api(session, "GET", "/me/playlists", params={"limit": 50, "offset": offset})
        # Only private, owned playlists: public editing would require another scope.
        items = [item_view(item) for item in result.get("items", []) if item
                 and item.get("public") is False and item.get("owner", {}).get("id") == session["account"]["id"]]
        next_offset = offset + len(result.get("items", [])) if result.get("next") else None
        return json_response({"items": items, "next_offset": next_offset})

    @app.get("/spotify/player")
    def player(request: Request) -> Response:
        session = control.session(request)
        state = control.api(session, "GET", "/me/player")
        devices = control.api(session, "GET", "/me/player/devices")
        return json_response({
            "is_playing": bool(state.get("is_playing")),
            "item": item_view(state["item"]) if (state.get("item") or {}).get("type") == "track" else None,
            "devices": [{"id": device.get("id"), "name": device.get("name"),
                         "is_active": device.get("is_active")} for device in devices.get("devices", [])
                        if device.get("id") and not device.get("is_restricted")],
        })

    @app.post("/spotify/action")
    async def action(request: Request) -> Response:
        session = control.session(request, write=True)
        # Bound input before parsing and reject extra fields; never accept arbitrary API paths.
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16000:
                raise HTTPException(413, "Spotify action too large.")
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, "Invalid Spotify action JSON.") from None
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(perform_action, session, data)

    def perform_action(session: dict[str, Any], data: Any) -> Response:
        if not isinstance(data, dict) or set(data) - {"action", "uris", "context_uri", "device_id", "playlist_id", "name"}:
            raise HTTPException(400, "Invalid Spotify action fields.")
        operation = data.get("action")
        if not isinstance(operation, str) or operation not in {"play", "pause", "next", "previous", "queue", "create_playlist", "add_to_playlist"}:
            raise HTTPException(400, "Unsupported Spotify action.")
        uris = data.get("uris", [])
        if not isinstance(uris, list) or len(uris) > 100 or any(not isinstance(uri, str) or not TRACK_URI.fullmatch(uri) for uri in uris):
            raise HTTPException(400, "Choose up to 100 valid Spotify tracks.")
        device = data.get("device_id", "")
        if not isinstance(device, str) or len(device) > 256:
            raise HTTPException(400, "Invalid device.")
        params = {"device_id": device} if device else None
        context = data.get("context_uri", "")
        if not isinstance(context, str) or (context and not CONTEXT_URI.fullmatch(context)) or (context and uris):
            raise HTTPException(400, "Choose either tracks or an album/playlist context.")
        if operation == "queue":
            if len(uris) != 1:
                raise HTTPException(400, "Choose exactly one track for the queue.")
            control.api(session, "POST", "/me/player/queue", params={**(params or {}), "uri": uris[0]})
        elif operation in {"play", "pause", "next", "previous"}:
            body = ({"context_uri": context} if context else {"uris": uris} if uris else None) if operation == "play" else None
            method = "PUT" if operation in {"play", "pause"} else "POST"
            control.api(session, method, "/me/player/" + operation, params=params, body=body)
        else:
            if not uris:
                raise HTTPException(400, "Select tracks before sending them to a playlist.")
            if operation == "create_playlist":
                name = data.get("name", "")
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
                    raise HTTPException(400, "Enter a playlist name of 1-100 characters.")
                playlist = control.api(session, "POST", "/me/playlists", body={"name": name.strip(), "public": False})
            else:
                playlist_id = data.get("playlist_id", "")
                if not isinstance(playlist_id, str) or not SPOTIFY_ID.fullmatch(playlist_id):
                    raise HTTPException(400, "Choose a valid private playlist.")
                playlist = control.api(session, "GET", "/playlists/" + playlist_id)
                if playlist.get("public") is not False or playlist.get("owner", {}).get("id") != session["account"]["id"]:
                    raise HTTPException(403, "Choose a private playlist that you own.")
            view = item_view(playlist)
            try:
                control.api(session, "POST", f"/playlists/{view['id']}/items", body={"uris": uris})
            except HTTPException:
                # Creation and population are separate requests. Do not hide partial success.
                return json_response({"ok": False, "playlist": view,
                                      "message": "The playlist exists, but adding tracks could not be confirmed. Open Spotify before retrying; do not create it again."}, 502)
            return json_response({"ok": True, "playlist": view, "added": len(uris)})
        return json_response({"ok": True})

    return control
