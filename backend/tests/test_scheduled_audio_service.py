import sys
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from config import FRANCE_TZ
from services import scheduled_audio_service as service


class ScheduledAudioServiceTest(unittest.TestCase):
    def test_v2_starts_at_h24_while_v1_keeps_h26_buffer(self):
        now = FRANCE_TZ.localize(datetime(2026, 9, 1, 9, 0))

        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now if tz is not None else now.replace(tzinfo=None)

        captured = {}
        due = [
            {
                "id": 1,
                "platform_id": 12,
                "session_index": 1,
                "module_day_id": 401,
                "scheduled_at": now + timedelta(hours=24, minutes=1),
                "formation_job_id": 8,
            },
            {
                "id": 2,
                "platform_id": 12,
                "session_index": 2,
                "module_day_id": 402,
                "scheduled_at": now + timedelta(hours=24),
                "formation_job_id": 8,
            },
            {
                "id": 3,
                "platform_id": 13,
                "session_index": 1,
                "module_day_id": None,
                "scheduled_at": now + timedelta(hours=25, minutes=59),
                "formation_job_id": 9,
            },
            {
                "id": 4,
                "platform_id": 12,
                "session_index": 3,
                "module_day_id": None,
                "local_date": "2026-09-03",
                "scheduled_at": now + timedelta(hours=24, minutes=1),
                "formation_job_id": 8,
            },
        ]

        def fake_list_due(**kwargs):
            captured.update(kwargs)
            return due

        with (
            patch.dict(
                service.os.environ,
                {
                    "SCHEDULED_AUDIO_READY_HOURS_BEFORE": "24",
                    "SCHEDULED_AUDIO_BUILD_BUFFER_HOURS": "2",
                },
            ),
            patch.object(service, "datetime", FrozenDateTime),
            patch.object(
                service,
                "list_due_audio_generation_sessions",
                side_effect=fake_list_due,
            ),
        ):
            results = service.process_due_audio_generations(dry_run=True)

        self.assertEqual(
            [item["session_id"] for item in results],
            [2, 3],
        )
        self.assertEqual(
            captured["upper_bound"] - captured["retry_due_before"],
            timedelta(hours=26),
        )

    def test_due_tick_passes_configured_batch_size_to_repository(self):
        captured = {}
        due = [
            {
                "id": session_id,
                "platform_id": 12,
                "session_index": session_id,
                "scheduled_at": f"2030-01-01 0{session_id}:00:00",
                "formation_job_id": 8,
            }
            for session_id in (1, 2, 3)
        ]

        def fake_list_due(**kwargs):
            captured.update(kwargs)
            return due[:kwargs["batch_size"]]

        with (
            patch.dict(service.os.environ, {"SCHEDULED_AUDIO_BATCH_SIZE": "2"}),
            patch.object(
                service,
                "list_due_audio_generation_sessions",
                side_effect=fake_list_due,
            ),
        ):
            results = service.process_due_audio_generations(dry_run=True)

        self.assertEqual(captured["batch_size"], 2)
        self.assertEqual([item["session_id"] for item in results], [1, 2])

    def test_default_scan_starts_before_j1_readiness_deadline(self):
        captured = {}

        def fake_list_due(**kwargs):
            captured.update(kwargs)
            return []

        with (
            patch.dict(service.os.environ, {
                "SCHEDULED_AUDIO_READY_HOURS_BEFORE": "24",
                "SCHEDULED_AUDIO_BUILD_BUFFER_HOURS": "2",
            }),
            patch.object(
                service,
                "list_due_audio_generation_sessions",
                side_effect=fake_list_due,
            ),
        ):
            service.process_due_audio_generations(dry_run=True)

        # retry_due_before is the tick's `now`; the claim window reaches H-26
        # so the files can be completed by the H-24 business deadline.
        self.assertEqual(
            captured["upper_bound"] - captured["retry_due_before"],
            service.timedelta(hours=26),
        )

    def test_explicit_ready_horizon_keeps_configured_build_buffer(self):
        captured = {}

        def fake_list_due(**kwargs):
            captured.update(kwargs)
            return []

        with (
            patch.dict(
                service.os.environ,
                {"SCHEDULED_AUDIO_BUILD_BUFFER_HOURS": "1.5"},
            ),
            patch.object(
                service,
                "list_due_audio_generation_sessions",
                side_effect=fake_list_due,
            ),
        ):
            service.process_due_audio_generations(
                dry_run=True,
                horizon_hours=10,
            )

        self.assertEqual(
            captured["upper_bound"] - captured["retry_due_before"],
            service.timedelta(hours=11.5),
        )

    def test_backpressure_stops_the_tick_without_claiming_later_sessions(self):
        calls = []

        def fake_launch(session, **_kwargs):
            calls.append(session["id"])
            return {"session_id": session["id"], "success": False, "status": 429}

        due = [
            {"id": 9, "platform_id": 12, "session_index": 1, "scheduled_at": "2030-01-01"},
            {"id": 10, "platform_id": 13, "session_index": 1, "scheduled_at": "2030-01-01"},
        ]
        with (
            patch.object(service, "list_due_audio_generation_sessions", return_value=due),
            patch.object(service, "launch_scheduled_audio_session", side_effect=fake_launch),
        ):
            results = service.process_due_audio_generations()

        self.assertEqual(calls, [9])
        self.assertEqual(results[0]["status"], 429)

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
            results = service.process_due_audio_generations(
                platform_ids=[12],
                wait_for_completion=True,
            )

        self.assertEqual(results[0]["success"], True)
        self.assertEqual(captured["job_id"], 8)
        self.assertEqual(captured["folder_id"], 55)
        self.assertEqual(captured["payload"]["force_all"], True)
        self.assertEqual(captured["payload"]["preserve_existing"], True)
        self.assertEqual(captured["payload"]["sync_slides"], True)
        self.assertEqual(captured["kwargs"]["schedule_session_id"], 9)
        self.assertEqual(captured["kwargs"]["target_platform_id"], 12)
        self.assertTrue(captured["kwargs"]["wait_for_completion"])

    def test_v2_launch_refuses_missing_manifest_before_generation_route(self):
        with (
            patch.object(
                service,
                "get_expected_course_folders",
                return_value={"folder_ids": [55]},
            ),
            patch(
                "services.audio_service.resolve_v2_course_session_manifest",
                side_effect=RuntimeError("manifeste absent"),
            ),
            patch.object(
                service,
                "mark_audio_waiting_for_content",
            ) as mark_waiting,
        ):
            result = service.launch_scheduled_audio_session(
                {
                    "id": 9,
                    "platform_id": 12,
                    "session_index": 1,
                    "module_day_id": 401,
                    "scheduled_at": "2026-09-01 09:00:00",
                    "formation_job_id": 8,
                }
            )

        self.assertFalse(result["success"])
        self.assertTrue(result["skipped"])
        self.assertIn("manifeste absent", result["error"])
        mark_waiting.assert_called_once()

    def test_incomplete_explicit_v2_launch_refuses_legacy_generation_path(self):
        with (
            patch.object(
                service,
                "get_expected_course_folders",
                return_value={"folder_ids": [55]},
            ),
            patch(
                "services.audio_service.resolve_v2_course_session_manifest",
                side_effect=RuntimeError("journée durable non liée"),
            ) as resolve_manifest,
            patch.object(
                service,
                "mark_audio_waiting_for_content",
            ) as mark_waiting,
        ):
            result = service.launch_scheduled_audio_session(
                {
                    "id": 9,
                    "platform_id": 12,
                    "session_index": 1,
                    "module_day_id": None,
                    "local_date": "2026-09-01",
                    "scheduled_at": "2026-09-01 09:00:00",
                    "formation_job_id": 8,
                }
            )

        self.assertFalse(result["success"])
        self.assertTrue(result["skipped"])
        self.assertIn("journée durable non liée", result["error"])
        resolve_manifest.assert_called_once()
        mark_waiting.assert_called_once()

    def test_v2_launch_validates_target_manifest_and_keeps_source_folder(self):
        captured = {}

        def fake_start(job_id, folder_id, payload, **kwargs):
            captured.update(
                {
                    "job_id": job_id,
                    "folder_id": folder_id,
                    "payload": payload,
                    **kwargs,
                }
            )
            return {"message": "ok"}, 202

        with (
            patch.object(
                service,
                "get_expected_course_folders",
                return_value={"folder_ids": [55]},
            ),
            patch(
                "services.audio_service.resolve_v2_course_session_manifest",
                return_value={
                    "folder_id": 66,
                    "module_day_id": 402,
                    "playlist_items": [("course_01.mp3", 3600, "cours", 1)],
                },
            ),
            patch.dict(
                sys.modules,
                {
                    "routes.formation_routes": types.SimpleNamespace(
                        start_folder_audio_generation=fake_start
                    )
                },
            ),
        ):
            result = service.launch_scheduled_audio_session(
                {
                    "id": 9,
                    "platform_id": 12,
                    "session_index": 1,
                    "module_day_id": 402,
                    "scheduled_at": "2026-09-01 09:00:00",
                    "formation_job_id": 8,
                }
            )

        self.assertTrue(result["success"])
        self.assertEqual(captured["folder_id"], 55)


if __name__ == "__main__":
    unittest.main()
