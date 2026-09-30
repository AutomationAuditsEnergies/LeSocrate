import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services import scheduled_audio_service as service


class ScheduledAudioReconciliationTest(unittest.TestCase):
    def setUp(self):
        self.session = {
            "id": 91,
            "platform_id": 12,
            "session_index": 1,
            "scheduled_at": "2026-08-28T09:00:00+02:00",
            "formation_job_id": 8,
            "audio_generation_status": "completed",
            "audio_generation_completed_at": "2026-08-26T08:00:00+02:00",
        }

    def test_only_missing_manifest_file_is_put_back_in_durable_queue(self):
        expected = {"cours_01.mp3", "cours_02.mp3", "pause_01.mp3"}
        state = {
            "ready": False,
            "expected": sorted(expected),
            "present": {
                "cours_01.mp3": {"size_bytes": 100},
                "pause_01.mp3": {"size_bytes": 100},
            },
            "missing": ["cours_02.mp3"],
            "invalid": {},
        }
        item = SimpleNamespace(id="work-1", run_id="new-run", status="queued")
        with (
            patch.object(service, "_resolve_scheduled_folder", return_value=(8, 55)),
            patch("services.day_playlist_service.required_audio_filenames", return_value=expected),
            patch("services.audio_publish_service.inspect_published_audio_manifest", return_value=state),
            patch.object(service, "_scheduled_voice_type", return_value="gtts"),
            patch.object(service, "_folder_content_ready", return_value=True),
            patch.object(service, "_enqueue_scheduled_audio_file", return_value=(item, False)) as enqueue,
            patch.object(service, "mark_audio_generation_queued", return_value=True) as mark_queued,
        ):
            result = service.reconcile_scheduled_audio_session(self.session)

        self.assertTrue(result["success"])
        self.assertEqual(result["missing_files"], ["cours_02.mp3"])
        self.assertEqual(len(result["queued_files"]), 1)
        self.assertEqual(enqueue.call_args.kwargs["filename"], "cours_02.mp3")
        self.assertTrue(mark_queued.call_args.kwargs["reset_completed"])

    def test_missing_content_resumes_ai_pipeline_without_queuing_tts(self):
        state = {
            "ready": False,
            "expected": ["cours_01.mp3"],
            "present": {},
            "missing": ["cours_01.mp3"],
            "invalid": {},
        }
        with (
            patch.object(service, "_resolve_scheduled_folder", return_value=(8, 55)),
            patch("services.day_playlist_service.required_audio_filenames", return_value={"cours_01.mp3"}),
            patch("services.audio_publish_service.inspect_published_audio_manifest", return_value=state),
            patch.object(service, "_scheduled_voice_type", return_value="gtts"),
            patch.object(service, "_folder_content_ready", return_value=False),
            patch.object(service, "mark_audio_waiting_for_content", return_value=True),
            patch.object(service, "_resume_text_pipeline_if_needed", return_value={"work_item_id": "ai-1"}) as resume,
            patch.object(service, "_enqueue_scheduled_audio_file") as enqueue,
        ):
            result = service.reconcile_scheduled_audio_session(self.session)

        self.assertFalse(result["success"])
        self.assertTrue(result["waiting_for_content"])
        self.assertEqual(result["pipeline_recovery"]["work_item_id"], "ai-1")
        resume.assert_called_once_with(8)
        enqueue.assert_not_called()

    def test_complete_mp3_manifest_requeues_courses_when_slide_sync_is_incomplete(self):
        expected = {"course_01.mp3", "qa_01.mp3"}
        state = {
            "ready": True,
            "expected": sorted(expected),
            "present": {name: {"size_bytes": 2_000_000} for name in expected},
            "missing": [],
            "invalid": {},
        }
        item = SimpleNamespace(id="work-sync", run_id="new-run", status="queued")
        with (
            patch.object(service, "_resolve_scheduled_folder", return_value=(8, 55)),
            patch(
                "services.day_playlist_service.required_audio_filenames",
                return_value=expected,
            ),
            patch(
                "services.audio_publish_service.inspect_published_audio_manifest",
                return_value=state,
            ),
            patch.object(service, "_scheduled_voice_type", return_value="gtts"),
            patch.object(
                service,
                "finalize_scheduled_audio_session_if_ready",
                return_value={
                    **state,
                    "ready": False,
                    "completed": False,
                    "reason": "audio_sync_incomplete",
                    "audio_sync_status": {
                        "expected_course_files": ["course_01.mp3"],
                        "missing_course_files": ["course_01.mp3"],
                        "missing_slide_ids": ["s2"],
                    },
                },
            ),
            patch.object(service, "_folder_content_ready", return_value=True),
            patch.object(
                service,
                "_enqueue_scheduled_audio_file",
                return_value=(item, False),
            ) as enqueue,
            patch.object(service, "mark_audio_generation_queued", return_value=True),
        ):
            result = service.reconcile_scheduled_audio_session(self.session)

        self.assertTrue(result["success"])
        self.assertEqual(result["missing_files"], ["course_01.mp3"])
        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.kwargs["filename"], "course_01.mp3")

    def test_complete_database_row_is_physically_rechecked(self):
        with patch.object(
            service,
            "list_due_audio_generation_sessions",
            return_value=[self.session],
        ) as due, patch.object(
            service,
            "reconcile_scheduled_audio_session",
            return_value={"success": True, "skipped": True},
        ) as reconcile, patch.object(
            service,
            "_scheduled_tts_mode",
            return_value="gtts",
        ):
            result = service.process_due_audio_generations(horizon_hours=72)

        self.assertEqual(len(result), 1)
        self.assertTrue(due.call_args.kwargs["reconcile_manifest"])
        reconcile.assert_called_once()


if __name__ == "__main__":
    unittest.main()
