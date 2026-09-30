import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from flask import Flask

from config import FRANCE_TZ
from routes import debug_routes


class DebugPlaybackTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="debug-v2-playback-test")
        app.register_blueprint(debug_routes.debug_bp)
        self.client = app.test_client()
        with self.client.session_transaction() as admin_session:
            admin_session.update({"is_admin": True, "platform_id": 7})
        self.start = FRANCE_TZ.localize(datetime(2026, 9, 1, 9, 0))

    def _v2_playback(self):
        audio = {
            "id": 1,
            "filename": "course_01.mp3",
            "duration": 3600,
            "title": "Cours 1 (09:00-10:00)",
            "type": "cours",
            "folder_id": 52,
            "module_day_id": 404,
            "schedule_schema_version": 2,
        }
        return {
            "schedule_schema_version": 2,
            "occurrence": {
                "id": 701,
                "module_day_id": 404,
                "scheduled_at": self.start,
            },
            "playlist": [audio],
            "course_start": self.start,
            "now": self.start + timedelta(seconds=30),
            "audio_info": audio,
            "offset": 30,
            "time_remaining": 0,
        }

    def test_debug_endpoints_use_the_current_v2_manifest(self):
        playback = self._v2_playback()
        with patch.object(
            debug_routes,
            "get_current_playback_context",
            return_value=playback,
        ) as resolver:
            info = self.client.get("/api/debug/cours-info")
            playlist = self.client.get("/api/debug/playlist")

        self.assertEqual(info.status_code, 200, info.get_json())
        debug_info = info.get_json()["debug_info"]
        self.assertEqual(debug_info["schedule_schema_version"], 2)
        self.assertEqual(debug_info["module_day_id"], 404)
        self.assertEqual(debug_info["folder_id"], 52)
        self.assertEqual(debug_info["audio_actuel_titre"], "Cours 1 (09:00-10:00)")

        self.assertEqual(playlist.status_code, 200, playlist.get_json())
        playlist_payload = playlist.get_json()
        self.assertEqual(playlist_payload["schedule_schema_version"], 2)
        self.assertEqual(playlist_payload["module_day_id"], 404)
        self.assertEqual(
            [item["filename"] for item in playlist_payload["playlist"]],
            ["course_01.mp3"],
        )
        self.assertEqual(resolver.call_count, 2)

    def test_debug_playlist_keeps_the_v1_response_shape(self):
        legacy_audio = {
            "id": 1,
            "filename": "legacy.mp3",
            "duration": 3600,
            "title": "Cours historique",
            "type": "cours",
        }
        playback = {
            "schedule_schema_version": 1,
            "occurrence": None,
            "playlist": [legacy_audio],
            "course_start": self.start,
            "now": self.start,
            "audio_info": legacy_audio,
            "offset": 0,
            "time_remaining": 0,
        }
        with patch.object(
            debug_routes,
            "get_current_playback_context",
            return_value=playback,
        ):
            response = self.client.get("/api/debug/playlist")

        self.assertEqual(
            response.get_json(),
            {
                "success": True,
                "platform_id": 7,
                "playlist": [legacy_audio],
            },
        )


if __name__ == "__main__":
    unittest.main()
