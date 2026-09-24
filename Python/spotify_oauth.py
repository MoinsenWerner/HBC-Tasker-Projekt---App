"""Spotify Authorization Code with PKCE for the Windows desktop client."""

from __future__ import annotations

import base64
import hashlib
import http.server
import secrets
import threading
import time
import urllib.parse
import webbrowser
from typing import Any

import requests

CALLBACK_URL = "http://127.0.0.1:60105/spotify/callback"
DEFAULT_CLIENT_ID = "b8f9f76a43e942dc8501097e12663dd5"
SCOPES = "playlist-read-private playlist-read-collaborative user-read-playback-state user-modify-playback-state"


class SpotifyOAuth:
    def __init__(self, client_id: str = DEFAULT_CLIENT_ID) -> None:
        self.client_id = client_id
        self.tokens: dict[str, Any] = {}

    def connect(self, timeout: int = 180) -> None:
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(24)
        result: dict[str, str] = {}
        event = threading.Event()

        class Callback(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/spotify/callback":
                    self.send_error(404)
                    return
                query = urllib.parse.parse_qs(parsed.query)
                result.update({key: values[0] for key, values in query.items()})
                body = "Spotify wurde verbunden. Dieses Fenster kann geschlossen werden."
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(body.encode())
                event.set()

            def log_message(self, _format: str, *args: object) -> None:
                return

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 60105), Callback)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        query = urllib.parse.urlencode({
            "client_id": self.client_id, "response_type": "code", "redirect_uri": CALLBACK_URL,
            "scope": SCOPES, "state": state, "code_challenge_method": "S256", "code_challenge": challenge,
        })
        webbrowser.open(f"https://accounts.spotify.com/authorize?{query}")
        if not event.wait(timeout):
            server.shutdown()
            raise TimeoutError("Spotify-Anmeldung wurde nicht innerhalb von drei Minuten abgeschlossen.")
        server.shutdown()
        if result.get("state") != state:
            raise ValueError("Spotify hat einen ungültigen OAuth-State zurückgegeben.")
        if result.get("error"):
            raise ValueError(f"Spotify-Anmeldung abgebrochen: {result['error']}")
        response = requests.post("https://accounts.spotify.com/api/token", data={
            "client_id": self.client_id, "grant_type": "authorization_code", "code": result.get("code", ""),
            "redirect_uri": CALLBACK_URL, "code_verifier": verifier,
        }, timeout=20)
        response.raise_for_status()
        self.tokens = response.json()
        self.tokens["expires_at"] = time.time() + int(self.tokens.get("expires_in", 3600))

    def playlists(self) -> list[dict[str, Any]]:
        self._refresh_if_needed()
        if not self.tokens.get("access_token"):
            raise ValueError("Spotify ist noch nicht verbunden. Bitte zuerst „Connect your Spotify“ ausführen.")
        items: list[dict[str, Any]] = []
        url: str | None = "https://api.spotify.com/v1/me/playlists?limit=50"
        while url:
            response = requests.get(url, headers={"Authorization": f"Bearer {self.tokens['access_token']}"}, timeout=20)
            response.raise_for_status()
            data = response.json()
            items.extend(data.get("items", []))
            url = data.get("next")
        return items

    def _refresh_if_needed(self) -> None:
        if time.time() < float(self.tokens.get("expires_at", 0)) - 60 or not self.tokens.get("refresh_token"):
            return
        response = requests.post("https://accounts.spotify.com/api/token", data={
            "client_id": self.client_id, "grant_type": "refresh_token", "refresh_token": self.tokens["refresh_token"],
        }, timeout=20)
        response.raise_for_status()
        refreshed = response.json()
        self.tokens.update(refreshed)
        self.tokens["expires_at"] = time.time() + int(refreshed.get("expires_in", 3600))
