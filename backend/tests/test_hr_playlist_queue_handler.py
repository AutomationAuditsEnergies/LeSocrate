import sys
import types
import unittest
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import Mock, patch

from services.hr_playlist_pipeline_service import (
    _finalize_module_if_ready,
    handle_hr_playlist_work_item,
    handle_scheduled_audio_work_item,
)
from services.pipeline_queue.contracts import PermanentWorkError, WorkItem


class _Lease:
    def __init__(self):
        self.progress = []
        self.checkpoints = 0

    def report_progress(self, value):
        self.progress.append(dict(value))

    def checkpoint(self):
        self.checkpoints += 1


def _item(attempt=1):
    return WorkItem(
        id="11111111-1111-1111-1111-111111111111",
        pipeline_job_id=None,
        folder_id=118,
        resource_key="folder:118",
        run_id="run-118",
        task_type="hr_playlist_item",
        scope_key="hr_audio:118",
        dedupe_key="folder:118:audio:run-118",
        payload={
            "folder_id": 118,
            "platform_id": 16,
            "filename": "cours_9h00_9h45.mp3",
            "voice_type": "gtts",
            "voice_label": "gTTS",
            "sync_slides": False,
            "auto_generate_slides": False,
        },
        status="running",
        priority=0,
        attempt_count=attempt,
        max_attempts=5,
        available_at=None,
        lease_owner="worker",
        lease_token="22222222-2222-2222-2222-222222222222",
        lease_version=attempt,
        lease_expires_at=None,
        last_error=None,
        result={},
        created_at=None,
        updated_at=None,
    )


class HrPlaylistQueueHandlerTest(unittest.TestCase):
    def test_scheduled_item_records_blob_proof_before_completion(self):
        item = replace(
            _item(),
            pipeline_job_id=8,
            task_type="scheduled_audio_item",
            resource_key="course-session:91:audio:course_01.mp3",
            scope_key="scheduled_audio:91:course_01.mp3",
            payload={
                "session_id": 91,
                "folder_id": 118,
                "source_platform_id": 16,
                "target_platform_id": 12,
                "filename": "course_01.mp3",
                "voice_type": "gtts",
            },
        )
        proof = {
            "filename": "course_01.mp3",
            "etag": "etag-1",
            "size_bytes": 1234,
            "sha256": "abc",
            "verified": True,
        }
        with (
            patch(
                "services.hr_playlist_pipeline_service.get_course_folder_identity",
                return_value={"id": 118, "platform_id": 16, "formation_job_id": 8},
            ),
            patch(
                "repositories.course_schedule_repository.get_audio_generation_session",
                return_value={
                    "id": 91,
                    "platform_id": 12,
                    "status": "planned",
                    "formation_job_id": 8,
                },
            ),
            patch(
                "repositories.course_schedule_repository.mark_audio_generation_processing",
                return_value=True,
            ),
            patch(
                "services.day_playlist_service.required_audio_filenames",
                return_value={"course_01.mp3", "course_02.mp3"},
            ),
            patch(
                "services.audio_publish_service.inspect_published_audio_manifest",
                return_value={"ready": False, "missing": ["course_01.mp3"]},
            ),
            patch(
                "services.audio_asset_validation_service.audio_sync_timing_files",
                return_value=set(),
            ),
            patch(
                "services.content_generation_service.generate_audio_from_script",
                return_value={"generated": 1, "skipped": 0},
            ) as generate,
            patch(
                "services.audio_publish_service.publish_playlist_audio_to_platform",
                return_value={"published": ["course_01.mp3"], "publish_errors": []},
            ),
            patch(
                "services.audio_publish_service.verify_published_audio_file",
                return_value=proof,
            ),
            patch(
                "services.scheduled_audio_service.finalize_scheduled_audio_session_if_ready",
                return_value={"ready": False, "completed": False},
            ),
        ):
            result = handle_scheduled_audio_work_item(item, _Lease())

        self.assertTrue(generate.call_args.kwargs["preserve_existing"])
        self.assertEqual(generate.call_args.kwargs["target_filename"], "course_01.mp3")
        self.assertTrue(generate.call_args.kwargs["sync_slides"])
        self.assertTrue(generate.call_args.kwargs["auto_generate_slides"])
        self.assertEqual(result.result["proof"], proof)
        self.assertFalse(result.result["session_completed"])

    def test_retry_resumes_item_without_regenerating_existing_audio(self):
        calls = []
        content = types.ModuleType("services.content_generation_service")

        def generate(folder_id, **kwargs):
            calls.append((folder_id, kwargs))
            kwargs["on_progress"](1, 1, "Audio généré")
            return {"generated": 0, "skipped": 1}

        content.generate_audio_from_script = generate
        lease = _Lease()
        with patch(
            "services.hr_playlist_pipeline_service.get_course_folder_identity",
            return_value={
                "id": 118,
                "platform_id": 16,
                "formation_job_id": None,
            },
        ), patch.dict(
            sys.modules,
            {"services.content_generation_service": content},
        ), patch(
            "services.hr_playlist_pipeline_service._folder_schedule_schema_version",
            return_value=1,
        ), patch(
            "services.hr_playlist_pipeline_service._publish",
            return_value={"published": ["cours_9h00_9h45.mp3"]},
        ):
            result = handle_hr_playlist_work_item(_item(attempt=2), lease)

        self.assertTrue(calls[0][1]["preserve_existing"])
        self.assertTrue(calls[0][1]["sync_slides"])
        self.assertTrue(calls[0][1]["auto_generate_slides"])
        self.assertGreaterEqual(len(lease.progress), 2)
        self.assertEqual(lease.progress[-1]["step"], 1)
        self.assertEqual(lease.checkpoints, 1)
        self.assertEqual(result.result["status"], "completed")
        self.assertEqual(result.result["result"]["skipped"], 1)

    def test_v2_whole_playlist_refuses_the_legacy_fixed_generator(self):
        item = replace(
            _item(),
            task_type="hr_playlist_generate",
            payload={
                "folder_id": 118,
                "platform_id": 16,
                "voice_type": "gtts",
                "has_script": False,
                "playlist_mock": False,
            },
        )
        with patch(
            "services.hr_playlist_pipeline_service.get_course_folder_identity",
            return_value={
                "id": 118,
                "platform_id": 16,
                "formation_job_id": None,
            },
        ), patch(
            "services.hr_playlist_pipeline_service._folder_schedule_schema_version",
            return_value=2,
        ):
            with self.assertRaisesRegex(PermanentWorkError, "playlist historique"):
                handle_hr_playlist_work_item(item, _Lease())

    def test_v2_whole_playlist_publishes_the_complete_locked_manifest(self):
        content = types.ModuleType("services.content_generation_service")
        content.generate_audio_from_script = lambda _folder_id, **_kwargs: {
            "generated": 1,
            "skipped": 4,
            # This is only the subset generated by the current run.
            "files": ["course_01.mp3"],
        }
        item = replace(
            _item(),
            task_type="hr_playlist_generate",
            payload={
                "folder_id": 118,
                "platform_id": 16,
                "voice_type": "gtts",
                "voice_label": "gTTS",
                "has_script": True,
                "playlist_mock": False,
                "include_breaks": True,
            },
        )
        required = {
            "course_01.mp3",
            "qa_01.mp3",
            "pause_01.mp3",
            "course_02.mp3",
            "qa_02.mp3",
        }
        with patch(
            "services.hr_playlist_pipeline_service.get_course_folder_identity",
            return_value={
                "id": 118,
                "platform_id": 16,
                "formation_job_id": None,
            },
        ), patch.dict(
            sys.modules,
            {"services.content_generation_service": content},
        ), patch(
            "services.hr_playlist_pipeline_service._folder_schedule_schema_version",
            return_value=2,
        ), patch(
            "services.day_playlist_service.required_audio_filenames",
            return_value=required,
        ), patch(
            "services.hr_playlist_pipeline_service._publish",
            return_value={"published": sorted(required)},
        ) as publish, patch(
            "services.hr_playlist_pipeline_service._finalize_module_if_ready",
            return_value=None,
        ):
            handle_hr_playlist_work_item(item, _Lease())

        publish.assert_called_once_with(
            16,
            118,
            sorted(required),
            archive=True,
        )

    def test_v1_whole_playlist_keeps_the_historical_publish_all_behavior(self):
        content = types.ModuleType("services.content_generation_service")
        content.generate_audio_from_script = lambda _folder_id, **_kwargs: {
            "generated": 1,
            "skipped": 18,
            "files": ["cours_9h00_9h45.mp3"],
        }
        item = replace(
            _item(),
            task_type="hr_playlist_generate",
            payload={
                "folder_id": 118,
                "platform_id": 16,
                "voice_type": "gtts",
                "voice_label": "gTTS",
                "has_script": True,
                "playlist_mock": False,
                "include_breaks": True,
            },
        )
        with patch(
            "services.hr_playlist_pipeline_service.get_course_folder_identity",
            return_value={
                "id": 118,
                "platform_id": 16,
                "formation_job_id": None,
            },
        ), patch.dict(
            sys.modules,
            {"services.content_generation_service": content},
        ), patch(
            "services.hr_playlist_pipeline_service._folder_schedule_schema_version",
            return_value=1,
        ), patch(
            "services.hr_playlist_pipeline_service._publish",
            return_value={"published": ["cours_9h00_9h45.mp3"]},
        ) as publish, patch(
            "services.hr_playlist_pipeline_service._finalize_module_if_ready",
            return_value=None,
        ):
            handle_hr_playlist_work_item(item, _Lease())

        publish.assert_called_once_with(16, 118, None, archive=True)

    def test_v2_finalizer_rejects_extra_mp3_outside_the_locked_manifest(self):
        class _Cursor:
            def __init__(self):
                self.query = ""

            def execute(self, query, _params):
                self.query = query

            def fetchone(self):
                if "SELECT cf.platform_id" in self.query:
                    return (16, 900, "TP Test", "RNCP123", 2)
                raise AssertionError(f"fetchone inattendu: {self.query}")

            def fetchall(self):
                if "SELECT id FROM cours_folders" in self.query:
                    return [(118,)]
                raise AssertionError(f"fetchall inattendu: {self.query}")

        connection = Mock()
        connection.cursor.return_value = _Cursor()

        @contextmanager
        def pipeline_connection():
            yield connection, "?", False

        prefix = "platform-16/folder-118/playlist/"
        container = Mock()
        container.list_blobs.return_value = [
            types.SimpleNamespace(name=prefix + "course_01.mp3"),
            types.SimpleNamespace(name=prefix + "qa_01.mp3"),
            types.SimpleNamespace(name=prefix + "stale_legacy.mp3"),
        ]
        blob_service = Mock()
        blob_service.get_container_client.return_value = container

        with patch(
            "services.hr_playlist_pipeline_service._pipeline_connection",
            side_effect=pipeline_connection,
        ), patch.dict(
            "services.hr_playlist_pipeline_service.os.environ",
            {"AZURE_TTS_STORAGE_CONNECTION_STRING": "tts"},
            clear=False,
        ), patch(
            "services.hr_playlist_pipeline_service.BlobServiceClient.from_connection_string",
            return_value=blob_service,
        ), patch(
            "services.day_playlist_service.required_audio_filenames",
            return_value={"course_01.mp3", "qa_01.mp3"},
        ):
            result = _finalize_module_if_ready(118, "gtts")

        self.assertFalse(result["ready"])
        self.assertEqual(
            result["missing"],
            [{
                "folder_id": 118,
                "extra_files": ["stale_legacy.mp3"],
            }],
        )


if __name__ == "__main__":
    unittest.main()
