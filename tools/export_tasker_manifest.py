#!/usr/bin/env python3
"""Convert every exported Tasker scene, task, profile and project variable to JSON."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_manifest() -> dict:
    manifest = {"start_task": "HBC Starttask", "project_variables": {}, "scenes": [], "tasks": [], "profiles": []}
    project = ET.parse(ROOT / "Musik_Client.prj.xml").getroot()
    for variable in project.findall(".//ProfileVariable"):
        name = variable.findtext("pvn")
        if name:
            manifest["project_variables"][name] = variable.findtext("pvv") or ""
    for source in sorted((ROOT / "scenes").glob("*.xml")):
        root = ET.parse(source).getroot()
        scene = root.find(".//Scene")
        local_tasks = {task.findtext("id"): task for task in root.findall("./Task")}
        elements = []
        for element in list(scene):
            if not element.tag.endswith("Element") or element.tag in {"RectElement", "PropertiesElement"}:
                continue
            strings = [item.text or "" for item in element.findall("Str")]
            handlers = {}
            for event in ("clickTask", "longclickTask", "itemselectedTask", "valueTask", "mapTask", "strokeTask"):
                task_id = element.findtext(event)
                task = local_tasks.get(task_id)
                if task is not None:
                    handlers[event] = serialize_actions(task)
            elements.append({"type": element.tag.removesuffix("Element"), "name": strings[0] if strings else "", "text": strings[1] if len(strings) > 1 else "", "handlers": handlers})
        manifest["scenes"].append({"name": scene.findtext("nme"), "elements": elements})
    for source in sorted((ROOT / "tasks").glob("*.xml")):
        task = ET.parse(source).find(".//Task")
        manifest["tasks"].append({"name": task.findtext("nme"), "actions": serialize_actions(task)})
    for source in sorted((ROOT / "profiles").glob("*.xml")):
        profile = ET.parse(source).find(".//Profile")
        manifest["profiles"].append({"name": profile.findtext("nme")})
    return manifest


def serialize_actions(task: ET.Element) -> list[dict]:
    actions = []
    for action in task.findall("Action"):
        arguments = [item.text or "" for item in action.findall("Str")]
        actions.append({"code": int(action.findtext("code") or 0), "label": action.findtext("label") or "", "arguments": arguments})
    return actions


def main() -> None:
    output = json.dumps(build_manifest(), ensure_ascii=False, separators=(",", ":")) + "\n"
    for target in (ROOT / "Python/assets/tasker_manifest.json", ROOT / "apk/assets/tasker_manifest.json"):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
