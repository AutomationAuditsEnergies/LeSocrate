import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask


_export_service = types.ModuleType("services.export_service")
_export_service.generate_attendance_excel_export = lambda *_args, **_kwargs: None
sys.modules.setdefault("services.export_service", _export_service)

from routes import hr_routes


class HrAudioReadinessTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(hr_routes.create_hr_blueprint())
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["is_admin"] = True
            session["admin_account_type"] = "legacy_admin"

    def test_sync_readiness_requires_every_course_and_every_slide(self):
        deck = {
            "deck_id": 7,
            "slides": [{"slide_id": "s1"}, {"slide_id": "s2"}],
            "audio_sync": {
                "timings": [{
                    "slide_id": "s1",
                    "audio_filename": "course_01.mp3",
                    "start_time": 0,
                    "end_time": 10,
                }],
            },
        }
        with patch(
            "services.script_slide_generation_service.get_latest_script_slide_deck",
            return_value=deck,
        ):
            result = hr_routes._generated_audio_sync_readiness(
                91,
                ["course_01.mp3", "course_02.mp3", "qa_01.mp3"],
            )

        self.assertFalse(result["ready"])
        self.assertEqual(result["missing_course_files"], ["course_02.mp3"])
        self.assertEqual(result["missing_slide_ids"], ["s2"])

    def test_decodable_course_without_complete_sync_is_not_exposed_as_ready(self):
        listed_blob = SimpleNamespace(
            name="platform-5/folder-91/playlist/course_01.mp3",
            size=2_000_000,
        )
        blob_client = Mock()
        blob_client.get_blob_properties.return_value = SimpleNamespace(
            size=2_000_000,
            last_modified=None,
        )
        container = Mock()
        container.list_blobs.return_value = [listed_blob]
        container.get_blob_client.return_value = blob_client
        blob_service = Mock()
        blob_service.get_container_client.return_value = container
        playlist = {
            "schema_version": 2,
            "playlist_items": [("course_01.mp3", 2100, "cours", 1)],
        }
        sync_status = {
            "ready": False,
            "timing_files": ["course_01.mp3"],
            "missing_slide_ids": ["s2"],
        }

        with patch.dict(
            hr_routes.os.environ,
            {"AZURE_TTS_STORAGE_CONNECTION_STRING": "tts"},
            clear=False,
        ), patch(
            "routes.hr_routes.resolve_folder_asset_origin",
            return_value={},
        ), patch.object(
            hr_routes.BlobServiceClient,
            "from_connection_string",
            return_value=blob_service,
        ), patch(
            "routes.hr_routes._generated_audio_sync_readiness",
            return_value=sync_status,
        ), patch(
            "services.audio_asset_validation_service.inspect_mp3_blob",
            return_value={
                "filename": "course_01.mp3",
                "ready": True,
                "physical_ready": True,
                "reason": None,
                "size_bytes": 2_000_000,
                "estimated_duration_seconds": 1800.0,
            },
        ):
            result = hr_routes._inspect_generated_audio_assets(
                91,
                {"id": 91, "platform_id": 5},
                playlist,
            )

        self.assertEqual(result["audios"], [])
        self.assertEqual(result["invalid_audios"][0]["reason"], "missing_audio_sync")
        self.assertEqual(result["audio_playlist_items"][0]["readiness"], "invalid")

    def test_cleanup_copies_to_recoverable_quarantine_before_deleting_source(self):
        events = []
        source = Mock()
        source.get_blob_properties.return_value = SimpleNamespace(
            content_settings=SimpleNamespace(content_type="audio/mpeg")
        )
        source.download_blob.return_value.readall.return_value = b"broken-mp3"
        source.delete_blob.side_effect = lambda: events.append("delete")
        target = Mock()
        target.upload_blob.side_effect = lambda *_args, **_kwargs: events.append("upload")
        container = Mock()
        source_path = "platform-5/folder-91/playlist/course_01.mp3"
        container.get_blob_client.side_effect = lambda path: (
            source if path == source_path else target
        )
        inspection = {
            "audios": [],
            "invalid_audios": [{
                "filename": "course_01.mp3",
                "blob_path": source_path,
                "physical_ready": False,
                "reason": "course_audio_too_small",
            }],
            "_storage": {
                "container_client": container,
                "source_platform_id": 5,
                "source_folder_id": 91,
            },
        }

        with patch(
            "routes.hr_routes.HR_ENABLED",
            True,
        ), patch(
            "routes.hr_routes.get_course_folder_identity",
            return_value={"id": 91, "platform_id": 5},
        ), patch(
            "services.day_playlist_service.resolve_folder_playlist",
            return_value={"schema_version": 2, "playlist_items": []},
        ), patch(
            "routes.hr_routes._inspect_generated_audio_assets",
            return_value=inspection,
        ):
            response = self.client.post(
                "/api/hr/cours-folders/91/cleanup-invalid-audios"
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["quarantined"][0]["recoverable"])
        target.upload_blob.assert_called_once()
        source.delete_blob.assert_called_once_with()
        self.assertEqual(events, ["upload", "delete"])

    def test_playback_manifest_returns_cached_peaks_and_fresh_stream_url(self):
        audio_blob = Mock()
        audio_blob.get_blob_properties.return_value = SimpleNamespace(
            size=70_000_000,
            etag='"audio-etag"',
            content_settings=SimpleNamespace(
                content_type="audio/mpeg",
                content_disposition=None,
            ),
        )
        cache_blob = Mock()
        blob_service = Mock()
        blob_service.account_name = "ttsaccount"
        blob_service.credential = SimpleNamespace(account_key="secret")
        blob_service.get_blob_client.side_effect = lambda **kwargs: (
            cache_blob if kwargs["blob"].endswith(".json") else audio_blob
        )
        ready_audio = {
            "filename": "course_01.mp3",
            "estimated_duration_seconds": 2100,
        }

        with patch(
            "routes.hr_routes.HR_ENABLED",
            True,
        ), patch(
            "routes.hr_routes.get_course_folder_identity",
            return_value={"id": 91, "platform_id": 5},
        ), patch(
            "services.day_playlist_service.resolve_folder_playlist",
            return_value={"schema_version": 2, "playlist_items": []},
        ), patch(
            "routes.hr_routes._inspect_generated_audio_assets",
            return_value={"audios": [ready_audio], "invalid_audios": []},
        ), patch(
            "routes.hr_routes.resolve_folder_blob_path",
            return_value="platform-5/folder-91/playlist/course_01.mp3",
        ), patch.dict(
            hr_routes.os.environ,
            {"AZURE_TTS_STORAGE_CONNECTION_STRING": "tts"},
            clear=False,
        ), patch.object(
            hr_routes.BlobServiceClient,
            "from_connection_string",
            return_value=blob_service,
        ), patch(
            "services.audio_waveform_service.get_or_create_waveform",
            return_value={
                "duration": 2100.0,
                "peaks": [0.1, 0.4, 0.2],
                "points": 3,
                "cache_hit": True,
            },
        ), patch(
            "routes.hr_routes.generate_blob_sas",
            return_value="sig=fresh",
        ):
            response = self.client.get(
                "/api/hr/cours-folders/91/audio-playback-manifest/course_01.mp3"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["peaks"], [0.1, 0.4, 0.2])
        self.assertEqual(payload["duration"], 2100.0)
        self.assertEqual(payload["waveform_source"], "cache")
        self.assertIn("sig=fresh", payload["url"])


if __name__ == "__main__":
    unittest.main()
