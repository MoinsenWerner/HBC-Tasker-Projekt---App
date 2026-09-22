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
        with patch.object(module.requests, "request", return_value=response) as request:
            result = module.HbcApi(session).player()
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
        with patch.object(api, "_request", return_value="/player;/token"):
            with self.assertRaisesRegex(module.ApiError, "keine Passkey-API"):
                api.passkey_options("felix")


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = module.QApplication.instance() or module.QApplication([])

    def test_login_window_starts_without_tcl(self):
        window = module.MusikClient()
        self.assertEqual(window.windowTitle(), "HBC Musik Client")
        self.assertIsNotNone(window.centralWidget())
        window.close()


if __name__ == "__main__":
    unittest.main()
