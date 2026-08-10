import sys
import types
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

from flask import Flask


# ``hr_routes`` imports the export service at module load time. The route under
# test does not need its optional spreadsheet dependencies.
_export_service = types.ModuleType("services.export_service")
_export_service.generate_attendance_excel_export = lambda *_args, **_kwargs: None
sys.modules.setdefault("services.export_service", _export_service)

from repositories.teacher_asset_repository import CANONICAL_AUDIO_PLAYLIST_PATHS
from routes.hr_routes import create_hr_blueprint
from services.playlist_tts_service import PLAYLIST_SPEC


class _Downloader:
    def __init__(self, value, events, label):
        self.value = value
        self.events = events
        self.label = label

    def readall(self):
        self.events.append(f"read:{self.label}")
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class _BlobClient:
    def __init__(self, container, name):
        self.container = container
        self.name = name

    def exists(self):
        self.container.events.append(
            f"exists:{self.container.label}:{self.name}"
        )
        return self.name in self.container.store

    def download_blob(self):
        value = self.container.store.get(
            self.name,
            FileNotFoundError(self.name),
        )
        return _Downloader(
            value,
            self.container.events,
            f"{self.container.label}:{self.name}",
        )

    def upload_blob(self, value, *, overwrite=False):
        self.container.events.append(
            f"upload:{self.container.label}:{self.name}"
        )
        self.container.store[self.name] = value
        self.container.uploads.append((self.name, value, overwrite))


class _Container:
    def __init__(self, label, store, events):
        self.label = label
        self.store = dict(store)
        self.events = events
        self.uploads = []

    def get_blob_client(self, name):
        return _BlobClient(self, name)


class _BlobService:
    def __init__(self, containers):
        self.containers = containers

    def get_container_client(self, name):
        return self.containers[name]


class _Cursor:
    def execute(self, *_args, **_kwargs):
        return None

    def fetchone(self):
        return ("Journée test", 5)


class _Connection:
    def cursor(self):
        return _Cursor()

    def close(self):
        return None


class HrFillFromFolderTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(create_hr_blueprint())
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["is_admin"] = True
            sess["admin_account_type"] = "legacy_admin"
            sess["admin_account_id"] = 1

    def _post(self, contract, *, source_store, static_store=None):
        events = []
        source = _Container("source", source_store, events)
        static = _Container("static", static_store or {}, events)
        destination = _Container("destination", {}, events)
        tts_service = _BlobService({"audiostts": source})
        audio_service = _BlobService({
            "formationaudio-test": destination,
            "audioqapause": static,
        })
        archive = Mock(
            side_effect=lambda *_args, **_kwargs: (
                events.append("archive") or {"archived": 19}
            )
        )

        with ExitStack() as stack:
            stack.enter_context(patch("routes.hr_routes.HR_ENABLED", True))
            stack.enter_context(
                patch.dict(
                    "os.environ",
                    {
                        "AZURE_TTS_STORAGE_CONNECTION_STRING": "tts",
                        "AZURE_AUDIO_STORAGE_CONNECTION_STRING": "audio",
                    },
                    clear=False,
                )
            )
            stack.enter_context(
                patch(
                    "routes.hr_routes.get_db_connection",
                    return_value=_Connection(),
                )
            )
            stack.enter_context(
                patch(
                    "routes.hr_routes.resolve_folder_asset_origin",
                    return_value={"source_platform_id": 5},
                )
            )
            stack.enter_context(
                patch(
                    "routes.hr_routes._get_platform_info",
                    return_value={"audio_container": "formationaudio-test"},
                )
            )
            stack.enter_context(
                patch(
                    "routes.hr_routes.resolve_folder_blob_path",
                    side_effect=lambda _folder, _container, relative, **_kwargs: relative,
                )
            )
            stack.enter_context(
                patch(
                    "services.day_playlist_service.resolve_folder_playlist",
                    return_value=contract,
                )
            )
            stack.enter_context(
                patch(
                    "azure.storage.blob.BlobServiceClient.from_connection_string",
                    side_effect=[tts_service, audio_service],
                )
            )
            stack.enter_context(
                patch(
                    "routes.hr_routes.archive_public_platform_audios",
                    archive,
                )
            )
            response = self.client.post(
                "/api/hr/platforms/5/fill-from-folder",
                json={"folder_id": 91},
            )

        return response, events, source, static, destination, archive

    def test_v2_reads_exact_manifest_before_archive_and_never_uses_static_fallback(self):
        playlist_items = [
            ("course_01.mp3", 2700, "cours", 1),
            ("qa_01.mp3", 600, "qa", 1),
            ("pause_01.mp3", 600, "pause", 1),
            ("course_02.mp3", 2700, "cours", 2),
            ("qa_02.mp3", 600, "qa", 2),
        ]
        expected_names = [item[0] for item in playlist_items]
        source_store = {
            f"playlist/{name}": f"bytes:{name}".encode()
            for name in expected_names
        }
        source_store.update({
            "playlist/extra.mp3": b"must-not-be-copied",
            "playlist/cours_9h00_9h45.mp3": b"legacy-must-not-be-copied",
        })

        response, events, source, static, destination, archive = self._post(
            {
                "schema_version": 2,
                "playlist_items": playlist_items,
            },
            source_store=source_store,
            static_store={
                "qa_01.mp3": b"static-must-not-be-used",
                "pause_01.mp3": b"static-must-not-be-used",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["files"], expected_names)
        self.assertEqual(
            [name for name, _value, _overwrite in destination.uploads],
            expected_names,
        )
        self.assertFalse(static.uploads)
        self.assertFalse(any(event.startswith("read:static:") for event in events))
        self.assertFalse(
            any("extra.mp3" in event or "cours_9h00_9h45.mp3" in event for event in events)
        )
        archive.assert_called_once_with(
            5,
            reason="fill-from-folder-91",
        )
        archive_index = events.index("archive")
        read_indices = [
            index
            for index, event in enumerate(events)
            if event.startswith("read:source:")
        ]
        upload_indices = [
            index
            for index, event in enumerate(events)
            if event.startswith("upload:destination:")
        ]
        self.assertEqual(len(read_indices), len(expected_names))
        self.assertTrue(all(index < archive_index for index in read_indices))
        self.assertTrue(all(index > archive_index for index in upload_indices))
        self.assertEqual(
            set(destination.store),
            set(expected_names),
        )
        self.assertEqual(
            {
                event.removeprefix("read:source:")
                for event in events
                if event.startswith("read:source:")
            },
            {f"playlist/{name}" for name in expected_names},
        )
        self.assertEqual(
            len(source.store),
            len(expected_names) + 2,
        )

    def test_generated_audio_library_exposes_the_exact_v2_manifest_without_storage(self):
        playlist_items = [
            ("course_01.mp3", 2700, "cours", 1),
            ("qa_01.mp3", 600, "qa", 1),
            ("pause_01.mp3", 3600, "pause_midi", 1),
            ("course_02.mp3", 3600, "cours", 2),
            ("qa_02.mp3", 900, "qa", 2),
        ]
        with ExitStack() as stack:
            stack.enter_context(patch("routes.hr_routes.HR_ENABLED", True))
            stack.enter_context(
                patch.dict(
                    "os.environ",
                    {"AZURE_TTS_STORAGE_CONNECTION_STRING": ""},
                    clear=False,
                )
            )
            stack.enter_context(
                patch(
                    "routes.hr_routes.get_course_folder_identity",
                    return_value={"id": 91, "platform_id": 5},
                )
            )
            stack.enter_context(
                patch(
                    "services.day_playlist_service.resolve_folder_playlist",
                    return_value={
                        "schema_version": 2,
                        "playlist_items": playlist_items,
                    },
                )
            )
            response = self.client.get(
                "/api/hr/cours-folders/91/generated-audios"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["schedule_schema_version"], 2)
        self.assertEqual(payload["audios"], [])
        self.assertEqual(
            [item["filename"] for item in payload["audio_playlist_items"]],
            [item[0] for item in playlist_items],
        )
        self.assertEqual(
            payload["audio_playlist_items"][2],
            {
                "filename": "pause_01.mp3",
                "duration_seconds": 3600,
                "type": "pause_midi",
                "course_index": 1,
            },
        )

    def test_v2_missing_file_does_not_archive_or_write_public_audio(self):
        playlist_items = [
            ("course_01.mp3", 2700, "cours", 1),
            ("qa_01.mp3", 600, "qa", 1),
            ("pause_01.mp3", 600, "pause", 1),
        ]
        response, events, _source, static, destination, archive = self._post(
            {
                "schema_version": 2,
                "playlist_items": playlist_items,
            },
            source_store={
                "playlist/course_01.mp3": b"course",
                "playlist/qa_01.mp3": b"qa",
            },
            static_store={"pause_01.mp3": b"forbidden-fallback"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["missing_files"], ["pause_01.mp3"])
        archive.assert_not_called()
        self.assertNotIn("archive", events)
        self.assertFalse(destination.uploads)
        self.assertFalse(any(event.startswith("read:static:") for event in events))
        self.assertFalse(static.uploads)

    def test_v2_unreadable_file_does_not_archive_or_write_public_audio(self):
        playlist_items = [
            ("course_01.mp3", 2700, "cours", 1),
            ("qa_01.mp3", 600, "qa", 1),
        ]
        response, events, _source, _static, destination, archive = self._post(
            {
                "schema_version": 2,
                "playlist_items": playlist_items,
            },
            source_store={
                "playlist/course_01.mp3": b"course",
                "playlist/qa_01.mp3": OSError("source read failed"),
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.get_json()["unreadable_files"][0]["filename"],
            "qa_01.mp3",
        )
        archive.assert_not_called()
        self.assertNotIn("archive", events)
        self.assertFalse(destination.uploads)

    def test_v1_keeps_legacy_static_qa_pause_fallback(self):
        playlist_items = list(PLAYLIST_SPEC)
        course_names = {
            filename
            for filename, _duration, file_type, _course_index in playlist_items
            if file_type == "cours"
        }
        static_names = {
            filename
            for filename, _duration, file_type, _course_index in playlist_items
            if file_type in ("qa", "pause", "pause_midi")
        }
        response, events, _source, _static, destination, archive = self._post(
            {
                "schema_version": 1,
                "playlist_items": playlist_items,
            },
            source_store={
                f"playlist/{name}": f"course:{name}".encode()
                for name in course_names
            },
            static_store={
                name: f"static:{name}".encode()
                for name in static_names
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["schedule_schema_version"], 1)
        self.assertEqual(payload["copied"], 19)
        self.assertEqual(
            payload["files"],
            [item[0] for item in playlist_items],
        )
        self.assertEqual(
            set(destination.store),
            {
                path.split("/", 1)[1]
                for path in CANONICAL_AUDIO_PLAYLIST_PATHS
            },
        )
        archive.assert_called_once()
        archive_index = events.index("archive")
        self.assertTrue(
            all(
                index < archive_index
                for index, event in enumerate(events)
                if event.startswith("read:")
            )
        )


if __name__ == "__main__":
    unittest.main()
