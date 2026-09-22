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
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import requests
from PySide6.QtCore import Qt
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
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from windows_tasker import WindowsTaskerRuntime

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
    def _button(text: str, callback: Callable[[], None], accent: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(lambda _checked=False: callback())
        if accent:
            button.setObjectName("accent")
        return button

    def _execute(self, work: Callable[[], Any], done: Callable[[Any], None] | None = None) -> None:
        self.status.setText("Lädt …")
        QApplication.processEvents()
        try:
            result = work()
            self.status.setText("Bereit")
            if done:
                done(result)
        except Exception as exc:
            self.status.setText("Fehler")
            QMessageBox.critical(self, "HBC Musik Client", str(exc))

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
        playlist_layout.addWidget(self.playlist_box)
        playlist_layout.addWidget(self._button("Playlists laden", lambda: self._execute(self.api.playlists, self._render_playlists)))
        playlists.setLayout(playlist_layout)
        self.server_box = QListWidget()
        server_layout.addWidget(self.server_box)
        server_layout.addWidget(self._button("Server-Playlists laden", lambda: self._execute(self.api.server_playlists, self._render_server)))
        server.setLayout(server_layout)
        api_field = QLineEdit(self.session.api_url)
        settings_layout.addWidget(QLabel(f"Angemeldet als {self.session.user_id}"))
        settings_layout.addWidget(QLabel("API-Adresse"))
        settings_layout.addWidget(api_field)
        settings_layout.addWidget(self._button("API-Adresse speichern", lambda: self._set_api(api_field.text())))
        settings_layout.addWidget(self._button("🔑 Passkey erstellen", self.register_passkey, True))
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
        else:
            handlers = element.get("handlers", {})
            actions = handlers.get("clickTask") or handlers.get("itemselectedTask") or handlers.get("valueTask")
            if actions:
                self._execute(lambda: self.tasker.run_actions(actions))
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

    def _render_playlists(self, items: list[dict[str, Any]]) -> None:
        self.playlist_box.clear()
        for item in items:
            self.playlist_box.addItem(item.get("name", str(item)))

    def _render_server(self, items: list[Any]) -> None:
        self.server_box.clear()
        for item in items:
            self.server_box.addItem(item.get("name", str(item)) if isinstance(item, dict) else str(item))

    def logout(self) -> None:
        self.session.token = ""
        self.show_login()


if __name__ == "__main__":
    app = QApplication([])
    window = MusikClient()
    window.show()
    raise SystemExit(app.exec())
