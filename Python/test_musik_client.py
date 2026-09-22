import importlib.util
import os
import pathlib
import sys
import unittest
from unittest.mock import Mock, patch

PATH = pathlib.Path(__file__).with_name("musik_client.py")
spec = importlib.util.spec_from_file_location("musik_client", PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ApiTests(unittest.TestCase):
    def test_player_uses_authorization_header(self):
        session = module.Session(token="Bearer test")
        response = Mock(content=b"{}")
        response.json.return_value = {"item": {"name": "Song"}}
        api = module.HbcApi(session)
        with patch.object(api.http, "request", return_value=response) as request:
            result = api.player()
        self.assertEqual(result["item"]["name"], "Song")
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer test")

    def test_action_encodes_value(self):
        api = module.HbcApi(module.Session())
        with patch.object(api, "_request", return_value={}) as request:
            api.action("repeat", "context mode")
        request.assert_called_once_with("PUT", "/player/repeat/context%20mode")

    def test_login_uses_form_encoded_token_route(self):
        api = module.HbcApi(module.Session())
        with patch.object(api, "_request", return_value={"access_token": "abc"}) as request:
            token = api.login_secret("felix", "secret")
        self.assertEqual(token, "Bearer abc")
        request.assert_called_once_with("POST", "/token", data={
            "grant_type": "client_credentials",
            "client_id": "felix",
            "client_secret": "secret",
        })

    def test_missing_passkey_route_has_clear_error(self):
        api = module.HbcApi(module.Session())
        with patch.object(api, "_request", return_value={"challenge": "abc"}) as request:
            self.assertEqual(api.passkey_options("felix"), {"challenge": "abc"})
        request.assert_called_once_with("POST", "/api/authenticate/options", json={"username": "felix"})


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = module.QApplication.instance() or module.QApplication([])

    def test_login_window_starts_without_tcl(self):
        window = module.MusikClient()
        self.assertEqual(window.windowTitle(), "HBC Musik Client")
        self.assertIsNotNone(window.centralWidget())
        window.close()

    def test_archive_contains_every_exported_scene(self):
        import json
        import xml.etree.ElementTree as ET

        archive = json.loads(module.MANIFEST_FILE.read_text(encoding="utf-8"))
        exported = {ET.parse(path).findtext(".//Scene/nme") for path in PATH.parents[1].joinpath("scenes").glob("*.scn.xml")}
        included = {scene["name"] for scene in archive["scenes"]}
        self.assertEqual(len(archive["scenes"]), 17)
        self.assertEqual(included, exported)
        self.assertEqual(archive["start_task"], "HBC Starttask")
        handled = [element for scene in archive["scenes"] for element in scene["elements"] if element["handlers"]]
        self.assertGreater(len(handled), 50)

    def test_tasker_elements_are_embedded_in_main_ui(self):
        window = module.MusikClient()
        window.user_id.setText("felix")
        with patch.object(window.api, "player", return_value={}):
            window._logged_in("Bearer test")
        first_scene = window.tasker_project["scenes"][0]
        self.assertEqual(window.scene_picker.currentText(), first_scene["name"])
        self.assertEqual(window.scene_content_layout.count() - 2, len(first_scene["elements"]))
        button_texts = {button.text() for button in window.findChildren(module.QPushButton)}
        self.assertNotIn("Alle Tasker-Oberflächen & Funktionen", button_texts)
        window.close()


class WindowsRuntimeTests(unittest.TestCase):
    def test_runtime_sets_variables_and_calls_subtask(self):
        from windows_tasker import WindowsTaskerRuntime

        project = {"tasks": [{"name": "Child", "actions": [{"code": 547, "arguments": ["%value", "ready"]}]}]}
        api = Mock(session=module.Session())
        runtime = WindowsTaskerRuntime(project, api, Mock(), Mock())
        runtime.run_actions([{"code": 130, "arguments": ["Child"]}])
        self.assertEqual(runtime.variables["%value"], "ready")

    def test_android_intent_replacement_opens_uri_on_windows(self):
        from windows_tasker import WindowsTaskerRuntime

        runtime = WindowsTaskerRuntime({}, Mock(session=module.Session()), Mock(), Mock())
        with patch("windows_tasker.webbrowser.open") as opened:
            runtime.open_android_intent_replacement("spotify:track:123")
        opened.assert_called_once_with("spotify:track:123")


if __name__ == "__main__":
    unittest.main()
