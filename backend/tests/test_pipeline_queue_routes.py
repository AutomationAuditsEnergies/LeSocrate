import unittest
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

    def test_inline_runner_and_watchdog_are_removed(self):
        self.assertFalse(hasattr(formation_routes, "_tick_auto_pilot"))
        self.assertFalse(hasattr(formation_routes, "start_auto_pilot_watchdog"))

    def test_stop_returns_cancelled_work_item_id_not_dataclass(self):
        cancelled = SimpleNamespace(id="work-cancelled")
        with patch(
            "routes.formation_routes.get_job", return_value=_job(auto_pilot_step="review")
        ), patch(
            "routes.formation_routes.update_job"
        ), patch(
            "services.pipeline_queue.cancel_latest_work_item", return_value=cancelled
        ), patch(
            "services.formation_observability_service.log_pipeline_event"
        ):
            response = self.client.post("/api/formation/42/run-auto/stop")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["queue_work_item_cancelled"])
        self.assertEqual(payload["queue_work_item_id"], "work-cancelled")

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
            ),
        ), patch(
            "routes.formation_routes.update_job",
        ), patch(
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
