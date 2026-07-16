import sys
import threading
import types
import unittest
from unittest.mock import patch

from routes import formation_routes as formation_routes
from services import scheduled_audio_service
from workers import course_scheduler_worker as worker


class CourseSchedulerWorkerTest(unittest.TestCase):
    def test_autonomous_worker_starts_scheduled_audio_without_eventlet_hub(self):
        audio_started = threading.Event()
        audio_finished = threading.Event()

        def fake_generate_audio(*_args, **_kwargs):
            audio_started.set()
            raise RuntimeError("stop after proving the native audio runner started")

        def run_due_audio(*, wait_for_completion=False):
            self.assertFalse(wait_for_completion)
            _payload, status = formation_routes.start_folder_audio_generation(
                8,
                55,
                {
                    "tts_mode": "mock",
                    "force_all": True,
                    "sync_slides": True,
                    "auto_generate_slides": True,
                },
                schedule_session_id=9,
                target_platform_id=12,
                trigger_source="scheduled_24h",
            )
            return [{"success": status == 202, "status": status}]

        def forbidden_eventlet_spawn(*_args, **_kwargs):
            raise AssertionError("le worker autonome ne doit pas dépendre du hub Eventlet")

        fake_eventlet = types.SimpleNamespace(spawn=forbidden_eventlet_spawn)

        with (
            patch.object(worker, "advance_course_schedules", return_value=[]),
            patch.object(worker, "process_due_audio_generations", side_effect=run_due_audio),
            patch.object(worker, "process_due_reminders", return_value=[]),
            patch.object(
                formation_routes,
                "get_job",
                return_value={
                    "id": 8,
                    "platform_id": 7,
                    "status": "text_ready",
                    "nb_days": 1,
                    "auto_pilot_tts_mode": "mock",
                },
            ),
            patch.object(
                formation_routes,
                "_resolve_continue_after_text_folder",
                return_value=(55, {"strategy": "exact"}),
            ),
            patch.object(
                formation_routes,
                "_folder_text_reviews_ready",
                return_value=(True, {"segments_completed": 1, "reviewed_current": 1}),
            ),
            patch.object(formation_routes, "_try_acquire_scheduled_audio_capacity", return_value=True),
            patch.object(
                formation_routes,
                "_release_scheduled_audio_capacity",
                side_effect=audio_finished.set,
            ),
            patch.object(formation_routes, "update_job"),
            patch.object(formation_routes.logger, "error"),
            patch(
                "services.formation_pipeline_service.get_expected_course_folders",
                return_value={"folder_ids": [55]},
            ),
            patch(
                "services.content_generation_service.generate_audio_from_script",
                side_effect=fake_generate_audio,
            ),
            patch(
                "repositories.course_schedule_repository.claim_audio_generation_session",
                return_value=True,
            ),
            patch(
                "repositories.course_schedule_repository.fail_audio_generation_session",
                return_value=True,
            ),
            patch("services.formation_observability_service.log_pipeline_event"),
            patch.dict(sys.modules, {"eventlet": fake_eventlet}),
        ):
            result = worker.run_scheduler_tick_once()
            self.assertTrue(audio_started.wait(1.0))
            self.assertTrue(audio_finished.wait(1.0))

        self.assertTrue(result["healthy"])
        self.assertEqual(result["steps"]["audio_j_minus_1"]["processed"], 1)

    def test_once_waits_for_claimed_audio_to_finish_before_process_exit(self):
        audio_started = threading.Event()
        allow_audio_to_finish = threading.Event()
        claim_released = threading.Event()
        capacity_released = threading.Event()
        main_returned = threading.Event()
        main_results = []
        main_errors = []

        def fake_generate_audio(*_args, **_kwargs):
            audio_started.set()
            allow_audio_to_finish.wait(3.0)
            raise RuntimeError("forced generation failure after the wait assertion")

        def mark_claim_failed(*_args, **_kwargs):
            claim_released.set()
            return True

        def forbidden_eventlet_spawn(*_args, **_kwargs):
            raise AssertionError("--once doit exécuter l'audio inline, sans daemon Eventlet")

        def run_main():
            try:
                main_results.append(worker.main(["--once"]))
            except BaseException as exc:  # pragma: no cover - asserted below
                main_errors.append(exc)
            finally:
                main_returned.set()

        fake_eventlet = types.SimpleNamespace(spawn=forbidden_eventlet_spawn)
        due_session = {
            "id": 9,
            "platform_id": 12,
            "session_index": 1,
            "scheduled_at": "2030-01-01 09:00:00",
            "formation_job_id": 8,
            "name": "Centre test",
        }

        with (
            patch.object(worker, "configure_logging"),
            patch.object(worker, "advance_course_schedules", return_value=[]),
            patch.object(worker, "process_due_reminders", return_value=[]),
            patch.object(
                scheduled_audio_service,
                "list_due_audio_generation_sessions",
                return_value=[due_session],
            ),
            patch.object(
                scheduled_audio_service,
                "get_expected_course_folders",
                return_value={"folder_ids": [55]},
            ),
            patch.object(scheduled_audio_service, "_scheduled_tts_mode", return_value="mock"),
            patch.object(
                formation_routes,
                "get_job",
                return_value={
                    "id": 8,
                    "platform_id": 7,
                    "status": "text_ready",
                    "nb_days": 1,
                    "auto_pilot_tts_mode": "mock",
                },
            ),
            patch.object(
                formation_routes,
                "_resolve_continue_after_text_folder",
                return_value=(55, {"strategy": "exact"}),
            ),
            patch.object(
                formation_routes,
                "_folder_text_reviews_ready",
                return_value=(True, {"segments_completed": 1, "reviewed_current": 1}),
            ),
            patch.object(formation_routes, "_try_acquire_scheduled_audio_capacity", return_value=True),
            patch.object(
                formation_routes,
                "_release_scheduled_audio_capacity",
                side_effect=capacity_released.set,
            ),
            patch.object(formation_routes, "update_job"),
            patch.object(formation_routes.logger, "error"),
            patch(
                "services.formation_pipeline_service.get_expected_course_folders",
                return_value={"folder_ids": [55]},
            ),
            patch(
                "services.content_generation_service.generate_audio_from_script",
                side_effect=fake_generate_audio,
            ),
            patch(
                "repositories.course_schedule_repository.claim_audio_generation_session",
                return_value=True,
            ),
            patch(
                "repositories.course_schedule_repository.fail_audio_generation_session",
                side_effect=mark_claim_failed,
            ),
            patch("services.formation_observability_service.log_pipeline_event"),
            patch.dict(sys.modules, {"eventlet": fake_eventlet}),
        ):
            runner = threading.Thread(target=run_main, name="test-scheduler-once")
            runner.start()
            try:
                self.assertTrue(audio_started.wait(1.0))
                self.assertTrue(runner.is_alive())
                self.assertFalse(main_returned.is_set())
                self.assertFalse(claim_released.is_set())

                allow_audio_to_finish.set()
                self.assertTrue(claim_released.wait(1.0))
                self.assertTrue(capacity_released.wait(1.0))
                runner.join(1.0)
            finally:
                allow_audio_to_finish.set()
                runner.join(1.0)

        self.assertFalse(runner.is_alive())
        self.assertTrue(main_returned.is_set())
        self.assertEqual(main_errors, [])
        self.assertEqual(main_results, [1])

    def test_tick_runs_schedule_audio_and_reminders_in_order(self):
        calls = []

        with patch.object(
            worker,
            "advance_course_schedules",
            side_effect=lambda: calls.append("schedule") or [{"status": "scheduled"}],
        ), patch.object(
            worker,
            "process_due_audio_generations",
            side_effect=lambda **_kwargs: calls.append("audio") or [{"success": True}],
        ), patch.object(
            worker,
            "process_due_reminders",
            side_effect=lambda: calls.append("reminders") or [{"success": True}],
        ):
            result = worker.run_scheduler_tick_once()

        self.assertEqual(calls, ["schedule", "audio", "reminders"])
        self.assertTrue(result["healthy"])
        self.assertEqual(result["steps"]["schedule"]["processed"], 1)
        self.assertEqual(result["steps"]["audio_j_minus_1"]["processed"], 1)
        self.assertEqual(result["steps"]["reminders"]["processed"], 1)

    def test_tick_continues_after_one_stage_raises(self):
        with patch.object(
            worker,
            "advance_course_schedules",
            side_effect=RuntimeError("database unavailable"),
        ), patch.object(
            worker,
            "process_due_audio_generations",
            return_value=[],
        ) as audio, patch.object(
            worker,
            "process_due_reminders",
            return_value=[],
        ) as reminders:
            result = worker.run_scheduler_tick_once()

        self.assertFalse(result["healthy"])
        self.assertIn("RuntimeError", result["steps"]["schedule"]["error"])
        audio.assert_called_once_with(wait_for_completion=False)
        reminders.assert_called_once_with()

    def test_once_returns_process_status_from_tick_health(self):
        with patch.object(worker, "configure_logging"), patch.object(
            worker,
            "run_scheduler_tick_once",
            return_value={"healthy": True},
        ) as tick:
            self.assertEqual(worker.main(["--once"]), 0)
        tick.assert_called_once_with(wait_for_audio=True)

        with patch.object(worker, "configure_logging"), patch.object(
            worker,
            "run_scheduler_tick_once",
            return_value={"healthy": False},
        ):
            self.assertEqual(worker.main(["--once"]), 1)

    def test_loop_can_be_bounded_without_waiting_or_overlapping(self):
        stop_event = threading.Event()
        with patch.object(worker, "run_scheduler_tick_once", return_value={"healthy": True}) as tick:
            count = worker.run_scheduler_loop(
                stop_event,
                interval_seconds=30,
                max_ticks=1,
            )

        self.assertEqual(count, 1)
        tick.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
