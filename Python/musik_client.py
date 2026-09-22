#!/usr/bin/env python3
"""Desktop client for the HBC music service.

The file intentionally contains the complete application so it can be copied and
started directly.  Only ``requests`` is required; Tk is part of most Python
installations. Passkeys are delegated to the operating-system/browser WebAuthn
credential manager because private passkey material must never be handled here.
"""

from __future__ import annotations

import json
import os
import threading
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable
from urllib.parse import quote

import requests

APP_VERSION = "4.0.7-python"
DEFAULT_API_URL = "https://api.plsreload.de"
FALLBACK_API_URL = "http://37.44.215.123:2050"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hbc-musik-client"
CONFIG_FILE = CONFIG_DIR / "settings.json"


class ApiError(RuntimeError):
    """A user-presentable API failure."""


@dataclass
class Session:
    user_id: str = ""
    token: str = ""
    api_url: str = DEFAULT_API_URL


class HbcApi:
    """Small, testable adapter for the endpoints used by the Tasker export."""

    def __init__(self, session: Session, timeout: int = 15) -> None:
        self.session = session
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}))
        if self.session.token:
            headers["Authorization"] = self.session.token
        try:
            response = requests.request(
                method, f"{self.session.api_url.rstrip('/')}/{path.lstrip('/')}",
                headers=headers, timeout=self.timeout, **kwargs,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            detail = getattr(exc.response, "text", "") if getattr(exc, "response", None) else ""
            raise ApiError(detail or str(exc)) from exc
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return response.text

    def login_secret(self, user_id: str, secret: str) -> str:
        # Tasker's HTTP Auth action returns its Authorization header from /authorize.
        data = self._request("POST", "/authorize", json={"user_id": user_id, "user_secret": secret})
        token = data.get("token") or data.get("authorization") or data.get("access_token") if isinstance(data, dict) else ""
        if not token:
            # Compatibility with Basic-auth servers used by older HBC deployments.
            response = requests.post(f"{self.session.api_url}/authorize", auth=(user_id, secret), timeout=self.timeout)
            response.raise_for_status()
            token = response.headers.get("Authorization", "")
            if not token:
                body = response.json()
                token = body.get("token") or body.get("access_token", "")
        if not token:
            raise ApiError("Der Server hat kein Anmelde-Token geliefert.")
        return token if " " in token else f"Bearer {token}"

    def passkey_options(self, user_id: str) -> dict[str, Any]:
        return self._request("POST", "/passkeys/authentication/options", json={"user_id": user_id})

    def verify_passkey(self, credential: dict[str, Any]) -> str:
        data = self._request("POST", "/passkeys/authentication/verify", json=credential)
        token = data.get("token") or data.get("access_token", "")
        if not token:
            raise ApiError("Die Passkey-Antwort wurde nicht bestätigt.")
        return token if " " in token else f"Bearer {token}"

    def player(self) -> dict[str, Any]:
        data = self._request("GET", "/player")
        return data if isinstance(data, dict) else {}

    def action(self, name: str, value: str | None = None) -> Any:
        path = f"/player/{name}" + (f"/{quote(value)}" if value else "")
        return self._request("POST", path)

    def playlists(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/playlists")
        if isinstance(data, dict):
            return data.get("items", data.get("playlists", []))
        return []

    def server_playlists(self) -> list[str]:
        data = self._request("GET", "/serverplaylists/list?num=all")
        if isinstance(data, str):
            return [x for x in data.split("°|°") if x]
        return data.get("items", []) if isinstance(data, dict) else []


class BrowserCredentialManager:
    """Uses a server-hosted WebAuthn page and the platform credential manager.

    WebAuthn requires a secure RP origin. The API remains the RP and returns a
    token through a loopback callback. No private key or biometric leaves the OS.
    """

    def __init__(self, api_url: str) -> None:
        self.api_url = api_url.rstrip("/")

    def launch(self, operation: str, user_id: str, token: str = "") -> None:
        query = f"user_id={quote(user_id)}&client=python"
        if token:
            query += f"&session={quote(token)}"
        webbrowser.open(f"{self.api_url}/passkeys/{operation}?{query}")


class MusikClient(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("HBC Musik Client")
        self.geometry("430x760")
        self.minsize(380, 620)
        self.configure(bg="#101217")
        self.session = Session(api_url=self._load().get("api_url", DEFAULT_API_URL))
        self.api = HbcApi(self.session)
        self.cm = BrowserCredentialManager(self.session.api_url)
        self.status = tk.StringVar(value="Bereit")
        self.user_id = tk.StringVar(value=self._load().get("user_id", ""))
        self.secret = tk.StringVar()
        self.song = tk.StringVar(value="Nicht verbunden")
        self._style()
        self.show_login()

    def _style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background="#101217", foreground="#f5f5f5", fieldbackground="#20242c")
        style.configure("Accent.TButton", background="#1ed760", foreground="#07150c", padding=10)
        style.configure("TButton", padding=8)
        style.configure("TNotebook.Tab", padding=(12, 8))

    @staticmethod
    def _load() -> dict[str, Any]:
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps({"user_id": self.user_id.get(), "api_url": self.session.api_url}), encoding="utf-8")

    def _clear(self) -> ttk.Frame:
        for widget in self.winfo_children():
            widget.destroy()
        frame = ttk.Frame(self, padding=24)
        frame.pack(fill="both", expand=True)
        return frame

    def _async(self, work: Callable[[], Any], done: Callable[[Any], None] | None = None) -> None:
        self.status.set("Lädt …")
        def run() -> None:
            try:
                result = work()
                self.after(0, lambda: (self.status.set("Bereit"), done and done(result)))
            except Exception as exc:  # network errors are presented on the UI thread
                error = str(exc)
                self.after(0, lambda: (self.status.set("Fehler"), messagebox.showerror("HBC Musik Client", error)))
        threading.Thread(target=run, daemon=True).start()

    def show_login(self) -> None:
        frame = self._clear()
        ttk.Label(frame, text="♫", font=("TkDefaultFont", 48), foreground="#1ed760").pack(pady=(35, 4))
        ttk.Label(frame, text="HBC Musik Client", font=("TkDefaultFont", 22, "bold")).pack(pady=(0, 28))
        ttk.Label(frame, text="User-ID").pack(anchor="w")
        ttk.Entry(frame, textvariable=self.user_id).pack(fill="x", pady=(4, 14), ipady=7)
        ttk.Label(frame, text="User-Secret").pack(anchor="w")
        ttk.Entry(frame, textvariable=self.secret, show="•").pack(fill="x", pady=(4, 20), ipady=7)
        ttk.Button(frame, text="Mit User-Secret anmelden", style="Accent.TButton", command=self.login_secret).pack(fill="x")
        ttk.Separator(frame).pack(fill="x", pady=20)
        ttk.Button(frame, text="🔑  Mit Passkey anmelden", command=self.login_passkey).pack(fill="x")
        ttk.Label(frame, text="Passkeys werden sicher vom Betriebssystem bzw. Browser verwaltet.", wraplength=340).pack(pady=18)
        ttk.Label(frame, textvariable=self.status).pack(side="bottom")

    def login_secret(self) -> None:
        if not self.user_id.get().strip() or not self.secret.get():
            messagebox.showwarning("Anmeldung", "Bitte User-ID und User-Secret eingeben.")
            return
        self._async(lambda: self.api.login_secret(self.user_id.get().strip(), self.secret.get()), self._logged_in)

    def login_passkey(self) -> None:
        if not self.user_id.get().strip():
            messagebox.showwarning("Anmeldung", "Bitte zuerst die User-ID eingeben.")
            return
        self.cm.launch("authenticate", self.user_id.get().strip())
        token = simpledialog.askstring("Passkey", "Nach erfolgreicher Passkey-Anmeldung das vom Server angezeigte Session-Token einfügen:", show="•")
        if token:
            self._logged_in(token)

    def _logged_in(self, token: str) -> None:
        self.session.user_id, self.session.token = self.user_id.get().strip(), token
        self.secret.set("")
        self._save()
        self.show_main()

    def show_main(self) -> None:
        root = self._clear()
        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)
        home, playlists, server, settings = (ttk.Frame(notebook, padding=16) for _ in range(4))
        for page, title in zip((home, playlists, server, settings), ("Player", "Playlists", "Server", "Einstellungen")):
            notebook.add(page, text=title)
        ttk.Label(home, text="Aktuelle Wiedergabe", font=("TkDefaultFont", 15, "bold")).pack(pady=(16, 30))
        ttk.Label(home, text="♫", font=("TkDefaultFont", 70), foreground="#1ed760").pack()
        ttk.Label(home, textvariable=self.song, font=("TkDefaultFont", 14), wraplength=320).pack(pady=22)
        controls = ttk.Frame(home)
        controls.pack()
        for label, action in (("⏮", "previous"), ("⏯", "play"), ("⏭", "next"), ("🔁", "repeat")):
            ttk.Button(controls, text=label, command=lambda a=action: self._async(lambda: self.api.action(a), lambda _: self.refresh_player())).pack(side="left", padx=4)
        ttk.Button(home, text="Aktualisieren", command=self.refresh_player).pack(pady=20)
        self.playlist_box = tk.Listbox(playlists, bg="#20242c", fg="white", selectbackground="#1ed760")
        self.playlist_box.pack(fill="both", expand=True)
        ttk.Button(playlists, text="Playlists laden", command=lambda: self._async(self.api.playlists, self._render_playlists)).pack(fill="x", pady=8)
        self.server_box = tk.Listbox(server, bg="#20242c", fg="white", selectbackground="#1ed760")
        self.server_box.pack(fill="both", expand=True)
        ttk.Button(server, text="Server-Playlists laden", command=lambda: self._async(self.api.server_playlists, self._render_server)).pack(fill="x", pady=8)
        ttk.Label(settings, text=f"Angemeldet als {self.session.user_id}", font=("TkDefaultFont", 14, "bold")).pack(anchor="w", pady=12)
        ttk.Label(settings, text="API-Adresse").pack(anchor="w")
        api_var = tk.StringVar(value=self.session.api_url)
        ttk.Entry(settings, textvariable=api_var).pack(fill="x", pady=6)
        ttk.Button(settings, text="API-Adresse speichern", command=lambda: self._set_api(api_var.get())).pack(fill="x", pady=6)
        ttk.Button(settings, text="🔑 Passkey erstellen", style="Accent.TButton", command=lambda: self.cm.launch("register", self.session.user_id, self.session.token)).pack(fill="x", pady=(22, 8))
        ttk.Button(settings, text="Webchat öffnen", command=lambda: webbrowser.open(f"{self.session.api_url}/webchat?caller=python&client-id={quote(self.session.user_id)}")).pack(fill="x", pady=8)
        ttk.Button(settings, text="Abmelden", command=self.logout).pack(fill="x", pady=8)
        ttk.Label(settings, text=f"Version {APP_VERSION}").pack(side="bottom")
        ttk.Label(root, textvariable=self.status).pack(pady=(8, 0))
        self.refresh_player()

    def _set_api(self, value: str) -> None:
        self.session.api_url = value.rstrip("/") or DEFAULT_API_URL
        self.cm = BrowserCredentialManager(self.session.api_url)
        self._save()
        self.status.set("API-Adresse gespeichert")

    def refresh_player(self) -> None:
        def show(data: dict[str, Any]) -> None:
            item = data.get("item") or data
            artists = ", ".join(a.get("name", "") for a in item.get("artists", []))
            self.song.set(f"{item.get('name', 'Keine Wiedergabe')}\n{artists}".strip())
        self._async(self.api.player, show)

    def _render_playlists(self, items: list[dict[str, Any]]) -> None:
        self.playlist_box.delete(0, "end")
        for item in items:
            self.playlist_box.insert("end", item.get("name", str(item)))

    def _render_server(self, items: list[Any]) -> None:
        self.server_box.delete(0, "end")
        for item in items:
            self.server_box.insert("end", item.get("name", str(item)) if isinstance(item, dict) else item)

    def logout(self) -> None:
        self.session.token = ""
        self.show_login()


if __name__ == "__main__":
    MusikClient().mainloop()
