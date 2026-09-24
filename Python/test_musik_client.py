import importlib.util
import os
import pathlib
import sys
import tempfile
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

    def test_server_playlist_content_is_decoded(self):
        api = module.HbcApi(module.Session())
        exported = "Song One,Song Two\n___\nid1,id2\n___\nhttps://img/1,https://img/2\n___\nPlaylist\n___\nspotify-id"
        with patch.object(api, "_request", return_value=exported):
            tracks = api.server_playlist_tracks("Playlist", "spotify-id")
        self.assertEqual([track["name"] for track in tracks], ["Song One", "Song Two"])
        self.assertEqual(tracks[1]["uri"], "spotify:track:id2")


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


class ErrorLoggingTests(unittest.TestCase):
    def test_log_contains_human_and_technical_error_details(self):
        from error_logging import ErrorLogger

        with tempfile.TemporaryDirectory() as directory:
            logger = ErrorLogger(pathlib.Path(directory) / "error-log.md")

            def failing_action():
                raise PermissionError("Zugriff verweigert")

            try:
                failing_action()
            except PermissionError as error:
                path = logger.log(error, "Benutzer klickte auf Speichern", failing_action)
            report = path.read_text(encoding="utf-8")
        self.assertIn("Benutzer klickte auf Speichern", report)
        self.assertIn("PermissionError: Zugriff verweigert", report)
        self.assertIn("Windows hat den Zugriff", report)
        self.assertIn("def failing_action", report)
        self.assertIn("Technische Aufrufkette", report)

    def test_nested_dns_error_gets_plain_language_explanation(self):
        from error_logging import ErrorLogger

        try:
            try:
                raise module.requests.ConnectionError("DNS name could not resolve")
            except module.requests.ConnectionError as cause:
                raise module.ApiError("Request failed") from cause
        except module.ApiError as error:
            explanation = ErrorLogger.explain(error)
        self.assertIn("DNS-Name nicht gefunden", explanation)


class SpotifyTests(unittest.TestCase):
    def test_callback_url_is_the_requested_loopback_url(self):
        import spotify_oauth

        self.assertEqual(spotify_oauth.CALLBACK_URL, "http://127.0.0.1:60105/spotify/callback")

    def test_playlists_follow_spotify_pagination(self):
        from spotify_oauth import SpotifyOAuth

        spotify = SpotifyOAuth()
        spotify.tokens = {"access_token": "token", "expires_at": 9999999999}
        first = Mock()
        first.json.return_value = {"items": [{"name": "One"}], "next": "https://api.spotify.com/page2"}
        first.raise_for_status.return_value = None
        second = Mock()
        second.json.return_value = {"items": [{"name": "Two"}], "next": None}
        second.raise_for_status.return_value = None
        with patch("spotify_oauth.requests.get", side_effect=[first, second]) as request:
            playlists = spotify.playlists()
        self.assertEqual([item["name"] for item in playlists], ["One", "Two"])
        self.assertEqual(request.call_count, 2)

    def test_queue_play_and_multi_playlist_add_use_spotify_endpoints(self):
        from spotify_oauth import SpotifyOAuth

        spotify = SpotifyOAuth()
        spotify.tokens = {"access_token": "token", "expires_at": 9999999999}
        response = Mock()
        response.raise_for_status.return_value = None
        with patch("spotify_oauth.requests.request", return_value=response) as request:
            spotify.queue_tracks([{"id": "track1", "uri": "spotify:track:track1"}])
            spotify.play_playlist("playlist1")
            spotify.add_tracks(["playlist1", "playlist2"], [{"id": "track1"}])
        calls = [(call.args[0], call.args[1]) for call in request.call_args_list]
        self.assertEqual(calls[0][0], "POST")
        self.assertIn("/me/player/queue", calls[0][1])
        self.assertEqual(calls[1], ("PUT", "https://api.spotify.com/v1/me/player/play"))
        self.assertIn(("POST", "https://api.spotify.com/v1/playlists/playlist2/items"), calls)

    def test_playlist_items_uses_2026_endpoint_and_response_shape(self):
        from spotify_oauth import SpotifyOAuth

        spotify = SpotifyOAuth()
        spotify.tokens = {"access_token": "token", "expires_at": 9999999999}
        response = Mock()
        response.json.return_value = {
            "items": [{"item": {"id": "track1", "name": "Song"}}],
            "next": None,
        }
        response.raise_for_status.return_value = None
        with patch("spotify_oauth.requests.request", return_value=response) as request:
            tracks = spotify.playlist_tracks("playlist1")
        self.assertEqual(tracks, [{"id": "track1", "name": "Song"}])
        self.assertIn("/playlists/playlist1/items?", request.call_args.args[1])
        self.assertNotIn("/tracks?", request.call_args.args[1])

    def test_hydration_uses_individual_track_endpoint(self):
        from spotify_oauth import SpotifyOAuth

        spotify = SpotifyOAuth()
        spotify.tokens = {"access_token": "token", "expires_at": 9999999999}
        response = Mock()
        response.json.return_value = {"id": "track1", "name": "Song"}
        response.raise_for_status.return_value = None
        with patch("spotify_oauth.requests.request", return_value=response) as request:
            tracks = spotify.hydrate_tracks([{"id": "track1"}])
        self.assertEqual(tracks[0]["name"], "Song")
        self.assertEqual(request.call_args.args[1], "https://api.spotify.com/v1/tracks/track1")

    def test_spotify_403_has_specific_explanation(self):
        from error_logging import ErrorLogger

        response = Mock(status_code=403, url="https://api.spotify.com/v1/playlists/id/items")
        error = module.requests.HTTPError("Forbidden", response=response)
        self.assertIn("Spotify", ErrorLogger.explain(error))
        self.assertIn("Februar 2026", ErrorLogger.explain(error))


if __name__ == "__main__":
    unittest.main()
