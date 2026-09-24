"""Human-readable, append-only application error log."""

from __future__ import annotations

import datetime as dt
import inspect
import os
import socket
import traceback
from pathlib import Path
from typing import Any, Callable

import requests


class ErrorLogger:
    def __init__(self, path: Path | None = None) -> None:
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "HBC Musik Client"
        self.path = path or root / "error-log.md"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        error: BaseException,
        user_action: str,
        executed: Callable[..., Any] | None = None,
        executed_code: str | None = None,
    ) -> Path:
        frames = traceback.extract_tb(error.__traceback__)
        throwing = frames[-1] if frames else None
        client_frame = next((frame for frame in reversed(frames) if Path(frame.filename).name == "musik_client.py"), None)
        code = executed_code or self._source(executed)
        trace_sources = self._trace_sources(error.__traceback__)
        if trace_sources:
            code = f"{code.rstrip()}\n\n# Tatsächlich durchlaufene Funktionen bis zum Fehler\n{trace_sources}"
        timestamp = dt.datetime.now().astimezone().strftime("%d.%m.%Y um %H:%M:%S %Z")
        entry = [
            "\n---\n",
            f"# Fehler vom {timestamp}\n",
            f"**Was hat der Benutzer gemacht?**  \n{user_action or 'Keine Benutzeraktion bekannt (Hintergrundfehler).'}\n",
            f"**Was ist schiefgegangen?**  \n{type(error).__name__}: {error}\n",
            f"**Einfache Erklärung**  \n{self.explain(error)}\n",
            "**Welche Stelle hat den Fehler ausgelöst?**  ",
            f"\n`{throwing.filename}:{throwing.lineno}` in `{throwing.name}`\n" if throwing else "\nNicht ermittelbar.\n",
            "**Zeile in musik_client.py**  ",
            f"\nZeile {client_frame.lineno}: `{client_frame.line or ''}`\n" if client_frame else "\nDer Fehler entstand außerhalb von musik_client.py; dort gibt es keine auslösende Zeile.\n",
            "**Durch die Benutzeraktion ausgeführter Code**\n```python\n",
            code.rstrip() or "# Quelltext konnte nicht automatisch ermittelt werden.",
            "\n```\n",
            "**Technische Aufrufkette (für Support/Entwicklung)**\n```text\n",
            "".join(traceback.format_exception(type(error), error, error.__traceback__)).rstrip(),
            "\n```\n",
        ]
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(entry))
        return self.path

    @staticmethod
    def _source(executed: Callable[..., Any] | None) -> str:
        if executed is None:
            return ""
        try:
            return inspect.getsource(executed)
        except (OSError, TypeError):
            return repr(executed)

    @staticmethod
    def _trace_sources(tb) -> str:
        sources: list[str] = []
        seen: set[tuple[str, str]] = set()
        while tb is not None:
            frame = tb.tb_frame
            key = (frame.f_code.co_filename, frame.f_code.co_name)
            if key not in seen:
                seen.add(key)
                try:
                    source = inspect.getsource(frame.f_code).rstrip()
                except (OSError, TypeError):
                    source = f"# {frame.f_code.co_filename}:{tb.tb_lineno} in {frame.f_code.co_name}"
                sources.append(source)
            tb = tb.tb_next
        return "\n\n".join(sources)

    @staticmethod
    def explain(error: BaseException) -> str:
        if error.__cause__ is not None:
            return ErrorLogger.explain(error.__cause__)
        if isinstance(error, requests.HTTPError):
            status = error.response.status_code if error.response is not None else None
            url = error.response.url if error.response is not None else ""
            if status == 403 and "api.spotify.com" in url:
                return (
                    "Spotify hat diese Funktion abgelehnt. Bei Spotify-Apps im Entwicklungsmodus "
                    "muss der angemeldete Benutzer freigeschaltet sein und Premium besitzen; außerdem "
                    "dürfen seit Februar 2026 nur noch eigene oder gemeinsam bearbeitete Playlists "
                    "ausgelesen werden. Spotify neu verbinden, falls Berechtigungen ergänzt wurden."
                )
            if status in {401, 403}:
                return "Die Anmeldung wurde abgelehnt. User-ID, Secret oder Sitzung sind ungültig beziehungsweise abgelaufen."
            if status == 404:
                return "Die angeforderte URL oder API-Funktion wurde auf dem Server nicht gefunden."
            if status == 405:
                return "Die URL existiert, erlaubt aber die verwendete HTTP-Methode nicht."
            return f"Der Server hat die Anfrage mit HTTP-Status {status or 'unbekannt'} abgelehnt."
        if isinstance(error, (requests.Timeout, TimeoutError)):
            return "Der Server hat nicht rechtzeitig geantwortet. Internetverbindung oder Server sind möglicherweise langsam."
        if isinstance(error, (requests.ConnectionError, socket.gaierror)):
            text = str(error).lower()
            if "name" in text or "dns" in text or "resolve" in text:
                return "Die URL konnte nicht aufgerufen werden, weil der DNS-Name nicht gefunden wurde."
            return "Es konnte keine Netzwerkverbindung zum Server hergestellt werden."
        if isinstance(error, PermissionError):
            return "Windows hat den Zugriff auf eine Datei oder einen Ordner verweigert."
        if isinstance(error, FileNotFoundError):
            return "Eine benötigte Datei oder ein Ordner wurde nicht gefunden."
        if isinstance(error, ValueError):
            return "Die Anwendung hat einen Wert in einem unerwarteten oder ungültigen Format erhalten."
        return "Ein unerwarteter Fehler ist aufgetreten. Die technische Aufrufkette darunter zeigt der Entwicklung die genaue Ursache."
