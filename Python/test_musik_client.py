import importlib.util
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
        request.assert_called_once_with("POST", "/player/repeat/context%20mode")


if __name__ == "__main__":
    unittest.main()
