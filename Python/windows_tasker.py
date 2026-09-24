"""Windows-native replacements for portable Tasker actions."""

from __future__ import annotations

import os
import re
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable

import requests


class WindowsTaskerRuntime:
    """Execute the portable subset of Tasker actions without Tasker or Android."""

    def __init__(
        self,
        project: dict[str, Any],
        api: Any,
        notify: Callable[[str, str], None],
        show_scene: Callable[[str], None],
        ask: Callable[[str, str], str] | None = None,
    ) -> None:
        self.api = api
        self.notify = notify
        self.show_scene = show_scene
        self.ask = ask
        self.variables = dict(project.get("project_variables", {}))
        self.tasks = {task["name"]: task["actions"] for task in project.get("tasks", [])}
        self.data_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "HBC Musik Client"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def expand(self, value: str) -> str:
        for name in sorted(self.variables, key=len, reverse=True):
            value = value.replace(name, str(self.variables[name]))
        return value.replace("Tasker/HBC", str(self.data_dir))

    def run_task(self, name: str) -> None:
        actions = self.tasks.get(name)
        if actions is None:
            raise ValueError(f"Unbekannter Task: {name}")
        self.run_actions(actions)

    def run_actions(self, actions: list[dict[str, Any]]) -> None:
        for action in actions:
            code = action["code"]
            args = [self.expand(value) for value in action.get("arguments", [])]
            if code == 130 and args:
                self.run_task(args[0])
            elif code == 547 and len(args) >= 2:
                self.variables[args[0]] = args[1]
            elif code in {46, 47, 48, 49} and args:
                self.show_scene(args[0])
            elif code == 104 and args:
                webbrowser.open(args[0])
            elif code == 548 and args:
                self.notify("HBC Musik Client", args[0])
            elif code in {523, 779}:
                self.notify(args[0] if args else "HBC Musik Client", args[1] if len(args) > 1 else "")
            elif code == 30:
                time.sleep(min(float(args[0] or 0) if args else 0, 2))
            elif code in {409, 408} and args:
                Path(args[0]).mkdir(parents=True, exist_ok=True)
            elif code == 410 and args:
                path = Path(args[0])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(args[1] if len(args) > 1 else "", encoding="utf-8")
            elif code == 406 and args:
                Path(args[0]).unlink(missing_ok=True)
            elif code == 417 and args:
                self.variables[args[1] if len(args) > 1 else "%file_data"] = Path(args[0]).read_text(encoding="utf-8")
            elif code == 598 and len(args) >= 3:
                current = str(self.variables.get(args[0], args[0]))
                self.variables[args[0]] = re.sub(args[1], args[2], current)
            elif code == 590 and len(args) >= 2:
                values = str(self.variables.get(args[0], "")).split(args[1])
                for index, value in enumerate(values, 1):
                    self.variables[f"{args[0]}{index}"] = value
            elif code == 339 and args and args[0].startswith(("http://", "https://")):
                response = requests.get(args[0], headers=self._auth_headers(), timeout=20)
                response.raise_for_status()
                self.variables["%http_data"] = response.text
                self.variables["%http_response_code"] = response.status_code
            elif code == 351:
                self.variables["%hbc_auth_header"] = self.api.session.token
            elif code == 360 and self.ask and args:
                self.variables["%input"] = self.ask(args[0], args[1] if len(args) > 1 else "")
            elif code == 877 and args:
                self.open_android_intent_replacement(next((value for value in args if value), args[0]))
            elif code in {166160670, 2046367074, 1291811855}:
                self.notify("HBC Musik Client", next((value for value in args if value), "Tasker-Plug-in-Aktion"))
            elif code in {37, 38, 43, 135, 137, 159, 300, 319, 337, 342, 344, 354, 355, 356, 357, 366, 369, 378, 390, 399, 400, 404, 420, 422, 474, 549, 592, 888, 890}:
                # Flow-control, array and UI bookkeeping is represented by the
                # native Qt widgets/state and needs no OS operation here.
                continue

    def open_android_intent_replacement(self, target: str) -> None:
        """Replace Android intents with Windows URI/file association dispatch."""
        target = self.expand(target)
        if target.startswith(("http://", "https://", "mailto:", "spotify:")):
            webbrowser.open(target)
        elif os.name == "nt":
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", target])

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": self.api.session.token} if self.api.session.token else {}
