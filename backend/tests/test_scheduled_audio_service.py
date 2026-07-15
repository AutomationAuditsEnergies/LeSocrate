import sys
import types
import unittest
from unittest.mock import patch

from services import scheduled_audio_service as service


class ScheduledAudioServiceTest(unittest.TestCase):
    def test_manual_retry_reuses_the_failed_occurrence(self):
        captured = {}

        def fake_start(job_id, folder_id, payload, **kwargs):
            captured.update({"job_id": job_id, "folder_id": folder_id, "payload": payload, **kwargs})
            return {"message": "ok"}, 202

        with (
            patch.object(service, "get_audio_generation_session", return_value={
                "id": 9,
                "platform_id": 12,
                "session_index": 1,
                "scheduled_at": "2026-07-20 09:00:00",
                "status": "planned",
                "audio_generation_status": "error",
                "audio_generation_completed_at": None,
                "formation_job_id": 8,
                "name": "Centre test",
            }),
            patch.object(service, "get_expected_course_folders", return_value={"folder_ids": [55]}),
            patch.dict(sys.modules, {
                "routes.formation_routes": types.SimpleNamespace(start_folder_audio_generation=fake_start),
            }),
        ):
            payload, status = service.retry_scheduled_audio_generation(12, 9)

        self.assertEqual(status, 202)
        self.assertTrue(payload["success"])
        self.assertEqual(captured["schedule_session_id"], 9)
        self.assertEqual(captured["trigger_source"], "manual_schedule_retry")
        self.assertTrue(captured["payload"]["preserve_existing"])

    def test_missing_pipeline_marks_occurrence_as_waiting_for_content(self):
        with patch.object(service, "mark_audio_waiting_for_content") as mark_waiting:
            result = service.launch_scheduled_audio_session({
                "id": 9,
                "platform_id": 12,
                "session_index": 1,
                "scheduled_at": "2026-07-20 09:00:00",
                "name": "Centre test",
                "formation_job_id": None,
            })

        self.assertFalse(result["success"])
        mark_waiting.assert_called_once()

    def test_scheduled_launch_preserves_existing_playlist_files(self):
        captured = {}

        def fake_start_folder_audio_generation(job_id, folder_id, payload, **kwargs):
            captured["job_id"] = job_id
            captured["folder_id"] = folder_id
            captured["payload"] = payload
            captured["kwargs"] = kwargs
            return {"message": "ok"}, 202

        fake_routes = types.SimpleNamespace(
            start_folder_audio_generation=fake_start_folder_audio_generation
        )

        with (
            patch.object(
                service,
                "list_due_audio_generation_sessions",
                return_value=[
                    {
                        "id": 9,
                        "platform_id": 12,
                        "session_index": 1,
                        "scheduled_at": "2026-07-05 13:45:00",
                        "name": "Centre test",
                        "formation_job_id": 8,
                    }
                ],
            ),
            patch.object(
                service,
                "get_expected_course_folders",
                return_value={"folder_ids": [55]},
            ),
            patch.dict(sys.modules, {"routes.formation_routes": fake_routes}),
        ):
            results = service.process_due_audio_generations(platform_ids=[12])

        self.assertEqual(results[0]["success"], True)
        self.assertEqual(captured["job_id"], 8)
        self.assertEqual(captured["folder_id"], 55)
        self.assertEqual(captured["payload"]["force_all"], True)
        self.assertEqual(captured["payload"]["preserve_existing"], True)
        self.assertEqual(captured["payload"]["sync_slides"], True)
        self.assertEqual(captured["kwargs"]["schedule_session_id"], 9)


if __name__ == "__main__":
    unittest.main()
