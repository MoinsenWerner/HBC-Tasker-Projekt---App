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
import sys
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import requests
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QDialog,
    QDialogButtonBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from windows_tasker import WindowsTaskerRuntime
from error_logging import ErrorLogger
from spotify_oauth import SpotifyOAuth

APP_VERSION = "4.0.7-python"
DEFAULT_API_URL = "https://api.plsreload.de"
FALLBACK_API_URL = "http://37.44.215.123:2050"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hbc-musik-client"
CONFIG_FILE = CONFIG_DIR / "settings.json"
MANIFEST_FILE = Path(__file__).with_name("assets") / "tasker_manifest.json"


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
        self.http = requests.Session()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}))
        if self.session.token:
            headers["Authorization"] = self.session.token
        try:
            response = self.http.request(
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
        # /authorize is the browser-facing GET OAuth endpoint. Direct client
        # credentials belong in a form-encoded POST to /token.
        data = self._request("POST", "/token", data={
            "grant_type": "client_credentials",
            "client_id": user_id,
            "client_secret": secret,
        })
        token = data.get("token") or data.get("authorization") or data.get("access_token") if isinstance(data, dict) else ""
        if not token:
            raise ApiError("Der Server hat kein Anmelde-Token geliefert.")
        return token if " " in token else f"Bearer {token}"

    def passkey_options(self, user_id: str) -> dict[str, Any]:
        return self._request("POST", "/api/authenticate/options", json={"username": user_id})

    def verify_passkey(self, credential: dict[str, Any]) -> str:
        data = self._request("POST", "/api/authenticate/verify", json=credential)
        if not isinstance(data, dict) or not data.get("username") or not data.get("password"):
            raise ApiError("Die Passkey-Antwort enthielt keine Zugangsdaten.")
        return self.login_secret(str(data["username"]), str(data["password"]))

    def player(self) -> dict[str, Any]:
        data = self._request("GET", "/player")
        return data if isinstance(data, dict) else {}

    def action(self, name: str, value: str | None = None) -> Any:
        path = f"/player/{name}" + (f"/{quote(value)}" if value else "")
        method = {"play": "PUT", "pause": "PUT", "repeat": "PUT", "next": "POST", "previous": "POST"}.get(name, "GET")
        return self._request(method, path)

    def playlists(self) -> list[dict[str, Any]]:
        data = self._request("GET", f"/chat/share/playlists/{quote(self.session.user_id)}")
        if isinstance(data, dict):
            return data.get("eigene_playlists", [])
        return []

    def server_playlists(self) -> list[str]:
        data = self._request("GET", "/serverplaylists/list?num=all")
        if isinstance(data, str):
            return [x for x in data.split("°|°") if x]
        return data.get("items", []) if isinstance(data, dict) else []

    def server_playlist_tracks(self, name: str, playlist_id: str) -> list[dict[str, Any]]:
        data = self._request("GET", f"/playlistcontent/get/{quote(name, safe='')}?id={quote(playlist_id, safe='')}")
        if not isinstance(data, str):
            return []
        parts = data.split("\n___\n")
        names = parts[0].split(",") if parts else []
        ids = parts[1].split(",") if len(parts) > 1 else []
        images = parts[2].split(",") if len(parts) > 2 else []
        return [
            {"id": track_id, "uri": f"spotify:track:{track_id}", "name": title, "artists": [],
             "album": {"images": [{"url": images[index]}] if index < len(images) else []}}
            for index, (title, track_id) in enumerate(zip(names, ids))
        ]

    def play_server_playlist(self, name: str, playlist_id: str) -> Any:
        return self._request("POST", f"/playlist/play/{quote(name, safe='')}?id={quote(playlist_id, safe='')}")

    def upload_playlist(self, playlist: dict[str, Any], tracks: list[dict[str, Any]]) -> Any:
        images = [((track.get("album") or {}).get("images") or [{}])[0].get("url", "") for track in tracks]
        params = {
            "name": playlist.get("name", ""), "content": ",".join(track.get("name", "") for track in tracks),
            "ids": ",".join(track.get("id", "") for track in tracks), "bilder": ",".join(images),
            "pl-id": playlist.get("id", ""), "ersteller": self.session.user_id,
        }
        return self._request("POST", "/playlistcontent/list", params=params)


class BrowserCredentialManager:
    """Uses a server-hosted WebAuthn page and the platform credential manager.

    WebAuthn requires a secure RP origin. The API remains the RP and returns a
    token through a loopback callback. No private key or biometric leaves the OS.
    """

    def __init__(self, api_url: str) -> None:
        self.api_url = api_url.rstrip("/")

    def launch(self, operation: str, user_id: str, token: str = "") -> None:
        path = "get" if operation == "authenticate" else "register"
        webbrowser.open(f"{self.api_url}/{path}?username={quote(user_id)}")


class MusikClient(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("HBC Musik Client")
        self.resize(430, 760)
        self.setMinimumSize(380, 620)
        self.session = Session(api_url=self._load().get("api_url", DEFAULT_API_URL))
        self.api = HbcApi(self.session)
        self.error_logger = ErrorLogger()
        self.spotify = SpotifyOAuth()
        sys.excepthook = self._unhandled_exception
        threading.excepthook = lambda args: self._unhandled_exception(args.exc_type, args.exc_value, args.exc_traceback)
        self.cm = BrowserCredentialManager(self.session.api_url)
        self.tasker_project = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
        self.tasker = WindowsTaskerRuntime(
            self.tasker_project,
            self.api,
            self._windows_notify,
            self._show_exported_scene,
            self._ask_value,
        )
        self.user_id = QLineEdit(self._load().get("user_id", ""))
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.status = QLabel("Bereit")
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #101217; color: #f5f5f5; }
            QLineEdit, QListWidget { background: #20242c; padding: 8px; border: 1px solid #343943; border-radius: 5px; }
            QPushButton { background: #292e37; padding: 10px; border-radius: 5px; }
            QPushButton:hover { background: #3a414d; }
            QPushButton#accent { background: #1ed760; color: #07150c; font-weight: bold; }
        """)
        self.show_login()

    @staticmethod
    def _load() -> dict[str, Any]:
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps({"user_id": self.user_id.text(), "api_url": self.session.api_url}), encoding="utf-8")

    @staticmethod
    def _plain_button(text: str, callback: Callable[[], None], accent: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(lambda _checked=False: callback())
        if accent:
            button.setObjectName("accent")
        return button

    def _button(self, text: str, callback: Callable[[], None], accent: bool = False) -> QPushButton:
        def guarded() -> None:
            try:
                callback()
            except Exception as exc:
                self._report_error(exc, f'Button „{text}“ angeklickt', callback)

        return self._plain_button(text, guarded, accent)

    def _execute(
        self,
        work: Callable[[], Any],
        done: Callable[[Any], None] | None = None,
        user_action: str = "Eine Funktion der Oberfläche ausgeführt",
        executed_code: str | None = None,
    ) -> None:
        self.status.setText("Lädt …")
        QApplication.processEvents()
        try:
            result = work()
            self.status.setText("Bereit")
            if done:
                done(result)
        except Exception as exc:
            self.status.setText("Fehler")
            self._report_error(exc, user_action, work, executed_code)

    def _report_error(
        self,
        error: BaseException,
        user_action: str,
        executed: Callable[..., Any] | None = None,
        executed_code: str | None = None,
    ) -> None:
        path = self.error_logger.log(error, user_action, executed, executed_code)
        QMessageBox.critical(self, "HBC Musik Client", f"{error}\n\nEin verständlicher Fehlerbericht wurde gespeichert:\n{path}")

    def _unhandled_exception(self, error_type, error, tb) -> None:
        error.__traceback__ = tb
        self._report_error(error, "Unbehandelter Hintergrund- oder UI-Fehler")

    def show_login(self) -> None:
        page, layout = QWidget(), QVBoxLayout()
        layout.setContentsMargins(28, 45, 28, 28)
        logo = QLabel("♫\nHBC Musik Client")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("font-size: 28px; font-weight: bold; color: #1ed760; margin-bottom: 25px")
        form = QFormLayout()
        form.addRow("User-ID", self.user_id)
        form.addRow("User-Secret", self.secret)
        layout.addWidget(logo)
        layout.addLayout(form)
        layout.addWidget(self._button("Mit User-Secret anmelden", self.login_secret, True))
        layout.addWidget(self._button("🔑  Mit Passkey anmelden", self.login_passkey))
        hint = QLabel("Passkeys werden sicher vom Betriebssystem bzw. Browser verwaltet.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        layout.addWidget(self.status)
        page.setLayout(layout)
        self.setCentralWidget(page)

    def login_secret(self) -> None:
        if not self.user_id.text().strip() or not self.secret.text():
            QMessageBox.warning(self, "Anmeldung", "Bitte User-ID und User-Secret eingeben.")
            return
        self._execute(lambda: self.api.login_secret(self.user_id.text().strip(), self.secret.text()), self._logged_in)

    def login_passkey(self) -> None:
        if not self.user_id.text().strip():
            QMessageBox.warning(self, "Anmeldung", "Bitte zuerst die User-ID eingeben.")
            return
        self.cm.launch("authenticate", self.user_id.text().strip())
        secret, accepted = QInputDialog.getText(self, "Passkey", "Nach erfolgreicher Passkey-Prüfung das vom Vault ausgegebene Passwort einfügen:", QLineEdit.EchoMode.Password)
        if accepted and secret:
            self._execute(lambda: self.api.login_secret(self.user_id.text().strip(), secret), self._logged_in)

    def _logged_in(self, token: str) -> None:
        self.session.user_id, self.session.token = self.user_id.text().strip(), token
        self.secret.clear()
        self._save()
        self.show_main()

    def show_main(self) -> None:
        root, root_layout, notebook = QWidget(), QVBoxLayout(), QTabWidget()
        home, playlists, server, settings = QWidget(), QWidget(), QWidget(), QWidget()
        home_layout, playlist_layout, server_layout, settings_layout = QVBoxLayout(), QVBoxLayout(), QVBoxLayout(), QVBoxLayout()
        self.song = QLabel("Nicht verbunden")
        self.song.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note = QLabel("♫")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setStyleSheet("font-size: 80px; color: #1ed760")
        home_layout.addWidget(QLabel("Aktuelle Wiedergabe"))
        home_layout.addWidget(note)
        home_layout.addWidget(self.song)
        controls = QHBoxLayout()
        for label, action in (("⏮", "previous"), ("⏯", "play"), ("⏭", "next"), ("🔁", "repeat")):
            controls.addWidget(self._button(label, lambda a=action: self._execute(
                lambda: self.api.action(a, "context" if a == "repeat" else None),
                lambda _: self.refresh_player(),
            )))
        home_layout.addLayout(controls)
        home_layout.addWidget(self._button("Aktualisieren", self.refresh_player))
        home.setLayout(home_layout)
        self.playlist_box = QListWidget()
        self.playlist_box.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        playlist_layout.addWidget(self.playlist_box)
        playlist_layout.addWidget(self._button("Spotify-Playlists laden", self.load_spotify_playlists))
        playlist_layout.addWidget(self._button("Ausgewählte Playlist öffnen", lambda: self.open_playlist(False)))
        playlist_layout.addWidget(self._button("Ausgewählte Playlist abspielen", lambda: self.play_selected_playlist(False)))
        playlist_layout.addWidget(self._button("Ausgewählte Playlist auf Server hochladen", self.upload_selected_playlist))
        playlists.setLayout(playlist_layout)
        self.server_box = QListWidget()
        self.server_box.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        server_layout.addWidget(self.server_box)
        server_layout.addWidget(self._button("Server-Playlists laden", lambda: self._execute(self.api.server_playlists, self._render_server)))
        server_layout.addWidget(self._button("Ausgewählte Server-Playlist öffnen", lambda: self.open_playlist(True)))
        server_layout.addWidget(self._button("Ausgewählte Server-Playlist abspielen", lambda: self.play_selected_playlist(True)))
        server_layout.addWidget(self._button("Im eigenen Spotify-Konto speichern", self.save_server_playlist))
        server.setLayout(server_layout)
        api_field = QLineEdit(self.session.api_url)
        settings_layout.addWidget(QLabel(f"Angemeldet als {self.session.user_id}"))
        settings_layout.addWidget(QLabel("API-Adresse"))
        settings_layout.addWidget(api_field)
        settings_layout.addWidget(self._button("API-Adresse speichern", lambda: self._set_api(api_field.text())))
        settings_layout.addWidget(self._button("🔑 Passkey erstellen", self.register_passkey, True))
        settings_layout.addWidget(self._button("Connect your Spotify", self.connect_spotify))
        settings_layout.addWidget(self._button("Webchat öffnen", lambda: webbrowser.open(f"{self.session.api_url}/webchat?caller=python&client-id={quote(self.session.user_id)}")))
        settings_layout.addWidget(self._button("Abmelden", self.logout))
        settings_layout.addStretch()
        settings_layout.addWidget(QLabel(f"Version {APP_VERSION}"))
        settings.setLayout(settings_layout)
        tasker_page = self._build_tasker_scenes_page()
        for page, title in zip(
            (home, playlists, server, tasker_page, settings),
            ("Player", "Playlists", "Server", "Weitere Funktionen", "Einstellungen"),
        ):
            notebook.addTab(page, title)
        root_layout.addWidget(notebook)
        root_layout.addWidget(self.status)
        root.setLayout(root_layout)
        self.setCentralWidget(root)
        self.refresh_player()

    def _set_api(self, value: str) -> None:
        self.session.api_url = value.rstrip("/") or DEFAULT_API_URL
        self.cm = BrowserCredentialManager(self.session.api_url)
        self._save()
        self.status.setText("API-Adresse gespeichert")

    def register_passkey(self) -> None:
        self.cm.launch("register", self.session.user_id, self.session.token)

    def _build_tasker_scenes_page(self) -> QWidget:
        page, layout = QWidget(), QVBoxLayout()
        self.scene_picker = QComboBox()
        for scene in self.tasker_project["scenes"]:
            self.scene_picker.addItem(scene["name"], scene)
        self.scene_content = QWidget()
        self.scene_content_layout = QVBoxLayout(self.scene_content)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.scene_content)
        layout.addWidget(self.scene_picker)
        layout.addWidget(scroll)
        page.setLayout(layout)
        self.scene_picker.currentIndexChanged.connect(lambda _index: self._render_native_scene())
        self._render_native_scene()
        return page

    def _render_native_scene(self) -> None:
        while self.scene_content_layout.count():
            item = self.scene_content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        scene = self.scene_picker.currentData()
        title = QLabel(scene["name"])
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #1ed760")
        self.scene_content_layout.addWidget(title)
        for element in scene["elements"]:
            self.scene_content_layout.addWidget(self._native_element(scene["name"], element))
        self.scene_content_layout.addStretch()

    def _native_element(self, scene: str, element: dict[str, Any]) -> QWidget:
        element_type = element["type"]
        name = element["name"]
        text = element["text"] or name or element_type
        def activate() -> None:
            self._run_tasker_element(scene, element)

        if element_type == "Button":
            return self._button(text, activate)
        if element_type == "EditText":
            widget = QLineEdit()
            widget.setPlaceholderText(text)
            widget.setObjectName(name)
            widget.editingFinished.connect(activate)
            return widget
        if element_type in {"CheckBox", "Switch"}:
            widget = QCheckBox(text)
            widget.setObjectName(name)
            widget.toggled.connect(lambda _checked: activate())
            return widget
        if element_type == "Slider":
            widget = QSlider(Qt.Orientation.Horizontal)
            widget.setObjectName(name)
            widget.sliderReleased.connect(activate)
            return widget
        if element_type in {"Spinner", "Picker"}:
            widget = QComboBox()
            widget.setObjectName(name)
            widget.addItem(text)
            widget.currentIndexChanged.connect(lambda _index: activate())
            return widget
        if element_type == "Image":
            widget = QLabel(f"🖼  {name}")
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            widget.setMinimumHeight(80)
            return widget
        if element_type == "Web":
            return self._button(f"🌐  {name}", activate)
        widget = QLabel(text)
        widget.setObjectName(name)
        widget.setWordWrap(True)
        return widget

    def _run_tasker_element(self, scene: str, element: dict[str, Any]) -> None:
        name = element["name"]
        lowered = name.lower()
        if lowered == "previous":
            self._execute(lambda: self.api.action("previous"), lambda _: self.refresh_player())
        elif lowered == "next":
            self._execute(lambda: self.api.action("next"), lambda _: self.refresh_player())
        elif lowered == "playpause":
            self._execute(lambda: self.api.action("play"), lambda _: self.refresh_player())
        elif lowered == "repeatbtn":
            self._execute(lambda: self.api.action("repeat", "context"), lambda _: self.refresh_player())
        elif lowered in {"back", "knopf4"}:
            self.scene_picker.setCurrentIndex(0)
        elif "chat" in lowered:
            webbrowser.open(f"{self.session.api_url}/webchat?caller=python&client-id={quote(self.session.user_id)}")
        elif "update manuell herunterladen" in lowered or lowered == "install update":
            webbrowser.open(f"{self.session.api_url}/apk/latest")
        elif lowered == "connect spotify":
            self.connect_spotify()
        else:
            handlers = element.get("handlers", {})
            actions = handlers.get("clickTask") or handlers.get("itemselectedTask") or handlers.get("valueTask")
            if actions:
                self._execute(
                    lambda: self.tasker.run_actions(actions),
                    user_action=f'Tasker-Element „{scene} / {name}“ aktiviert',
                    executed_code=json.dumps(actions, ensure_ascii=False, indent=2),
                )
            else:
                QMessageBox.information(self, f"{scene} / {name}", "Für dieses Element ist im Tasker-Export keine Aktion hinterlegt.")

    def _windows_notify(self, title: str, message: str) -> None:
        if os.name == "nt":
            try:
                from winotify import Notification

                Notification(app_id="HBC Musik Client", title=title, msg=message).show()
                return
            except Exception:
                pass
        QMessageBox.information(self, title, message)

    def _show_exported_scene(self, scene: str) -> None:
        if hasattr(self, "scene_picker"):
            index = self.scene_picker.findText(scene)
            if index >= 0:
                self.scene_picker.setCurrentIndex(index)

    def _ask_value(self, title: str, prompt: str) -> str:
        value, accepted = QInputDialog.getText(self, title, prompt)
        return value if accepted else ""

    def refresh_player(self) -> None:
        def show(data: dict[str, Any]) -> None:
            item = data.get("item") or data
            artists = ", ".join(a.get("name", "") for a in item.get("artists", []))
            self.song.setText(f"{item.get('name', 'Keine Wiedergabe')}\n{artists}".strip())
        self._execute(self.api.player, show)

    def connect_spotify(self) -> None:
        self._execute(
            self.spotify.connect,
            lambda _: QMessageBox.information(self, "Spotify", "Spotify wurde erfolgreich verbunden."),
            "„Connect your Spotify“ angeklickt",
        )

    def load_spotify_playlists(self) -> None:
        self._execute(
            self.spotify.playlists,
            self._render_playlists,
            "Im Tab Playlists auf „Spotify-Playlists laden“ geklickt",
        )

    def _render_playlists(self, items: list[dict[str, Any]]) -> None:
        self.playlist_box.clear()
        for item in items:
            row = QListWidgetItem(item.get("name", str(item)))
            row.setData(Qt.ItemDataRole.UserRole, item)
            self.playlist_box.addItem(row)

    def _render_server(self, items: list[Any]) -> None:
        self.server_box.clear()
        for item in items:
            if isinstance(item, dict):
                playlist = item
            else:
                fields = str(item).split("•|•")
                playlist = {"name": fields[0], "db_id": fields[1] if len(fields) > 1 else "", "id": fields[2] if len(fields) > 2 else "", "creator": fields[3] if len(fields) > 3 else ""}
            row = QListWidgetItem(playlist.get("name", str(item)))
            row.setData(Qt.ItemDataRole.UserRole, playlist)
            self.server_box.addItem(row)

    def _selected_playlist(self, server: bool) -> dict[str, Any]:
        box = self.server_box if server else self.playlist_box
        item = box.currentItem()
        if item is None:
            raise ValueError("Bitte zuerst eine Playlist auswählen.")
        return dict(item.data(Qt.ItemDataRole.UserRole))

    def _playlist_tracks(self, playlist: dict[str, Any], server: bool) -> list[dict[str, Any]]:
        if server:
            tracks = self.api.server_playlist_tracks(playlist["name"], playlist.get("id", ""))
            return self.spotify.hydrate_tracks(tracks) if self.spotify.connected else tracks
        return self.spotify.playlist_tracks(playlist["id"])

    def open_playlist(self, server: bool) -> None:
        playlist = self._selected_playlist(server)
        self._execute(
            lambda: self._playlist_tracks(playlist, server),
            lambda tracks: self._show_playlist_dialog(playlist, tracks, server),
            f'Playlist „{playlist.get("name", "") }“ geöffnet',
        )

    def _show_playlist_dialog(self, playlist: dict[str, Any], tracks: list[dict[str, Any]], server: bool) -> None:
        dialog, layout = QDialog(self), QVBoxLayout()
        dialog.setWindowTitle(playlist.get("name", "Playlist"))
        dialog.resize(650, 650)
        songs = QListWidget()
        songs.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        songs.setIconSize(QPixmap(56, 56).size())
        for track in tracks:
            artists = ", ".join(artist.get("name", "") for artist in track.get("artists", [])) or "Künstler über Server-Export nicht verfügbar"
            row = QListWidgetItem(f'{track.get("name", "Unbekannter Song")} — {artists}')
            row.setData(Qt.ItemDataRole.UserRole, track)
            images = (track.get("album") or {}).get("images") or []
            if images and images[0].get("url"):
                try:
                    image = requests.get(images[0]["url"], timeout=10)
                    image.raise_for_status()
                    pixmap = QPixmap()
                    pixmap.loadFromData(image.content)
                    row.setIcon(QIcon(pixmap))
                except requests.RequestException:
                    pass
            songs.addItem(row)
        layout.addWidget(songs)
        layout.addWidget(self._button("Ausgewählte Songs zur Warteschlange hinzufügen", lambda: self._queue_dialog_tracks(songs)))
        layout.addWidget(self._button("Ausgewählte Songs zu Spotify-Playlists hinzufügen", lambda: self._add_dialog_tracks_to_playlists(songs)))
        layout.addWidget(self._button("Diese Playlist abspielen", lambda: self._play_playlist(playlist, server)))
        if server:
            layout.addWidget(self._button("Diese Playlist im Spotify-Konto speichern", lambda: self._save_playlist(playlist, tracks)))
        else:
            layout.addWidget(self._button("Diese Playlist auf den Server hochladen", lambda: self._execute(lambda: self.api.upload_playlist(playlist, tracks))))
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.setLayout(layout)
        dialog.exec()

    @staticmethod
    def _selected_tracks(songs: QListWidget) -> list[dict[str, Any]]:
        selected = songs.selectedItems()
        if not selected:
            raise ValueError("Bitte mindestens einen Song auswählen.")
        return [dict(item.data(Qt.ItemDataRole.UserRole)) for item in selected]

    def _queue_dialog_tracks(self, songs: QListWidget) -> None:
        tracks = self._selected_tracks(songs)
        self._execute(lambda: self.spotify.queue_tracks(tracks), user_action=f"{len(tracks)} Songs zur Warteschlange hinzugefügt")

    def _add_dialog_tracks_to_playlists(self, songs: QListWidget) -> None:
        tracks = self._selected_tracks(songs)
        destinations = self.spotify.playlists()
        dialog, layout, choices = QDialog(self), QVBoxLayout(), QListWidget()
        choices.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        for playlist in destinations:
            row = QListWidgetItem(playlist["name"])
            row.setData(Qt.ItemDataRole.UserRole, playlist["id"])
            choices.addItem(row)
        layout.addWidget(QLabel("Eine oder mehrere Ziel-Playlists auswählen:"))
        layout.addWidget(choices)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.setLayout(layout)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            ids = [item.data(Qt.ItemDataRole.UserRole) for item in choices.selectedItems()]
            if not ids:
                raise ValueError("Bitte mindestens eine Ziel-Playlist auswählen.")
            self._execute(lambda: self.spotify.add_tracks(ids, tracks), user_action=f"{len(tracks)} Songs zu {len(ids)} Spotify-Playlists hinzugefügt")

    def _play_playlist(self, playlist: dict[str, Any], server: bool) -> None:
        work = (lambda: self.api.play_server_playlist(playlist["name"], playlist.get("id", ""))) if server else (lambda: self.spotify.play_playlist(playlist["id"]))
        self._execute(work, user_action=f'Playlist „{playlist["name"]}“ abgespielt')

    def play_selected_playlist(self, server: bool) -> None:
        self._play_playlist(self._selected_playlist(server), server)

    def upload_selected_playlist(self) -> None:
        playlist = self._selected_playlist(False)
        self._execute(lambda: self.spotify.playlist_tracks(playlist["id"]), lambda tracks: self._execute(lambda: self.api.upload_playlist(playlist, tracks)), f'Playlist „{playlist["name"]}“ zum Upload geladen')

    def _save_playlist(self, playlist: dict[str, Any], tracks: list[dict[str, Any]]) -> None:
        self._execute(lambda: self.spotify.save_server_playlist(playlist["name"], tracks), user_action=f'Server-Playlist „{playlist["name"]}“ in Spotify gespeichert')

    def save_server_playlist(self) -> None:
        playlist = self._selected_playlist(True)
        self._execute(lambda: self._playlist_tracks(playlist, True), lambda tracks: self._save_playlist(playlist, tracks), f'Server-Playlist „{playlist["name"]}“ geladen')

    def logout(self) -> None:
        self.session.token = ""
        self.show_login()


if __name__ == "__main__":
    try:
        app = QApplication([])
        window = MusikClient()
        window.show()
        raise SystemExit(app.exec())
    except SystemExit:
        raise
    except Exception as exc:
        log_path = ErrorLogger().log(exc, "Anwendung gestartet")
        print(f"HBC Musik Client konnte nicht starten. Fehlerbericht: {log_path}", file=sys.stderr)
        raise
