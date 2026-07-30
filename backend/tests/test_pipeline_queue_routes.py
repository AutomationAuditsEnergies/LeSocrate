import unittest
import inspect
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from routes.formation_routes import (
    _normalize_pipeline_model_choice,
    formation_bp,
)
from routes import formation_routes


def _job(**overrides):
    value = {
        "id": 42,
        "platform_id": 7,
        "status": "init",
        "auto_pilot_step": None,
        "auto_pilot_model": "pro",
        "auto_pilot_tts_mode": "gtts",
        "auto_pilot_generate_audio": False,
        "auto_pilot_locked_at": None,
    }
    value.update(overrides)
    return value


class PipelineQueueRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(formation_bp)
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["is_admin"] = True
            session["admin_account_type"] = "training_center"
            session["admin_account_id"] = 42
        self.route_patches = [
            patch(
                "routes.formation_routes.can_access_formation_pipeline",
                return_value=True,
            ),
            patch(
                "repositories.pipeline_repository.pipeline_job_belongs_to_center",
                return_value=True,
            ),
            patch(
                "repositories.pipeline_repository.course_folder_belongs_to_job",
                return_value=True,
            ),
        ]
        for route_patch in self.route_patches:
            route_patch.start()

    def tearDown(self):
        for route_patch in reversed(self.route_patches):
            route_patch.stop()

    def test_manual_start_requires_a_teacher_order(self):
        response = self.client.post("/api/formation/42/run-auto", json={})

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.get_json()["code"], "teacher_order_required")

    def test_legacy_partial_resume_is_retired(self):
        response = self.client.post(
            "/api/formation/42/content/301/continue-after-text",
            json={"from_step": "slides"},
        )

        self.assertEqual(response.status_code, 410)
        self.assertEqual(
            response.get_json()["code"],
            "durable_pipeline_resume_required",
        )

    def test_legacy_resume_content_cannot_bypass_the_durable_queue(self):
        with patch(
            "services.content_generation_service.run_content_generation",
        ) as run_content, patch(
            "routes.formation_routes.get_job",
        ) as get_job:
            response = self.client.post(
                "/api/formation/42/resume-content",
                json={"model": "pro"},
            )

        self.assertEqual(response.status_code, 410)
        payload = response.get_json()
        self.assertEqual(
            payload["code"],
            "durable_pipeline_resume_required",
        )
        self.assertEqual(
            payload["resume_endpoint"],
            "/api/formation/42/run-auto/resume",
        )
        run_content.assert_not_called()
        get_job.assert_not_called()

    def test_inline_runner_and_watchdog_are_removed(self):
        self.assertFalse(hasattr(formation_routes, "_tick_auto_pilot"))
        self.assertFalse(hasattr(formation_routes, "start_auto_pilot_watchdog"))

    def test_monitoring_diagnostic_has_no_repairs_or_finalization(self):
        source = inspect.getsource(formation_routes.formation_pipeline_diagnostic)

        self.assertNotIn("repair_orphan_content_folders", source)
        self.assertNotIn("_finalize_scheduled_audio_module_if_ready", source)
        self.assertNotIn("update_job(", source)

        with patch(
            "routes.formation_routes.get_job",
            return_value=_job(auto_pilot_enabled=True, auto_pilot_step="content"),
        ), patch(
            "services.formation_health_service.compute_health",
            return_value={"ok": True, "blocking": [], "warnings": [], "checks": {}},
        ), patch(
            "services.formation_volume_audit_service.compute_volume_audit",
            return_value={"folders": []},
        ), patch(
            "services.formation_observability_service.list_pipeline_events",
            return_value=[],
        ), patch(
            "services.formation_pipeline_service.get_expected_course_folders",
            return_value={
                "expected_count": 0,
                "folder_ids": [],
                "duplicates": [],
                "missing": [],
            },
        ), patch(
            "routes.formation_routes._determine_next_ap_step",
            return_value="content",
        ), patch(
            "services.formation_pipeline_service.repair_orphan_content_folders",
        ) as repair, patch.object(
            formation_routes,
            "_finalize_scheduled_audio_module_if_ready",
        ) as finalize, patch(
            "routes.formation_routes.update_job",
        ) as update:
            response = self.client.get("/api/formation/42/diagnostic")

        self.assertEqual(response.status_code, 200)
        repair.assert_not_called()
        finalize.assert_not_called()
        update.assert_not_called()

    def test_manual_stop_cannot_cancel_the_durable_worker(self):
        with patch(
            "routes.formation_routes.get_job",
        ) as get_job, patch(
            "routes.formation_routes.update_job",
        ) as update_job, patch(
            "services.pipeline_queue.cancel_latest_work_item",
        ) as cancel:
            response = self.client.post("/api/formation/42/run-auto/stop")

        self.assertEqual(response.status_code, 410)
        payload = response.get_json()
        self.assertEqual(payload["code"], "durable_pipeline_only")
        get_job.assert_not_called()
        update_job.assert_not_called()
        cancel.assert_not_called()

    def test_all_historical_stage_commands_are_retired_before_side_effects(self):
        paths = [
            "/api/formation/init",
            "/api/formation/init-test",
            "/api/formation/42/fetch-reac",
            "/api/formation/42/enrich-reac",
            "/api/formation/42/generate-global",
            "/api/formation/42/validate-global",
            "/api/formation/42/split-daily",
            "/api/formation/42/validate-daily",
            "/api/formation/42/launch-tts",
            "/api/formation/42/refine",
            "/api/formation/42/content/301/volume-safety",
            "/api/formation/42/content/301/review",
            "/api/formation/42/content/301/generate-audio",
            "/api/formation/42/launch-audio",
            "/api/formation/42/run-auto/stop",
        ]
        with patch(
            "routes.formation_routes.get_job",
        ) as get_job, patch(
            "routes.formation_routes.update_job",
        ) as update_job, patch(
            "repositories.pipeline_repository.create_postgres_pipeline_aggregate",
        ) as create_aggregate:
            responses = [self.client.post(path, json={}) for path in paths]

        self.assertTrue(all(response.status_code == 410 for response in responses))
        self.assertEqual(
            [response.get_json()["code"] for response in responses[:2]],
            ["teacher_order_required", "teacher_order_required"],
        )
        self.assertTrue(
            all(
                response.get_json()["code"] == "durable_pipeline_only"
                for response in responses[2:]
            )
        )
        get_job.assert_not_called()
        update_job.assert_not_called()
        create_aggregate.assert_not_called()

    def test_resume_preserves_paid_teacher_order_until_terminal_completion(self):
        dead_lettered = SimpleNamespace(
            id="work-dead",
            run_id="run-dead",
            status="dead_lettered",
            terminal=True,
        )
        resumed = SimpleNamespace(
            id="work-resumed",
            run_id="run-resumed",
            status="queued",
            terminal=False,
        )
        linked_order = {
            "id": 73,
            "public_id": "order-public-id",
            "payment_status": "paid",
            "fulfillment_status": "failed",
        }
        with patch(
            "routes.formation_routes.get_job",
            return_value=_job(
                status="error",
                auto_pilot_step="content",
                auto_pilot_error="attempts exhausted",
                daily_programs_validated=1,
            ),
        ), patch(
            "routes.formation_routes.update_job",
        ) as update_job, patch(
            "routes.formation_routes._determine_next_ap_step",
            return_value="content",
        ), patch(
            "services.pipeline_queue.get_latest_work_item",
            return_value=dead_lettered,
        ), patch(
            "services.pipeline_queue.enqueue_work_item",
            return_value=resumed,
        ) as enqueue, patch(
            "repositories.billing_repository.get_order_by_pipeline_job_id",
            return_value=linked_order,
        ) as lookup_order, patch(
            "repositories.billing_repository.mark_order_pipeline_resume_requested",
        ) as mark_order_resumed, patch(
            "services.formation_observability_service.log_pipeline_event",
        ):
            response = self.client.post(
                "/api/formation/42/run-auto/resume",
                json={"force": False},
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            enqueue.call_args.kwargs["payload"]["teacher_order_id"],
            73,
        )
        self.assertEqual(
            enqueue.call_args.kwargs["payload"]["expected_step"],
            "content",
        )
        lookup_order.assert_called_once_with(42, center_account_id=42)
        mark_order_resumed.assert_called_once_with(73, pipeline_job_id=42)
        update_job.assert_called_once_with(
            42,
            auto_pilot_enabled=1,
            auto_pilot_error=None,
            auto_pilot_step="content",
            status="daily_validated",
            error_message=None,
        )

    def test_historical_claude_model_names_resume_on_deepseek_profiles(self):
        self.assertEqual(_normalize_pipeline_model_choice("sonnet"), "pro")
        self.assertEqual(
            _normalize_pipeline_model_choice("claude-sonnet-4-20250514"),
            "pro",
        )
        self.assertEqual(_normalize_pipeline_model_choice("haiku"), "flash")
        self.assertEqual(
            _normalize_pipeline_model_choice("claude-haiku-4-5-20251001"),
            "flash",
        )


if __name__ == "__main__":
    unittest.main()
