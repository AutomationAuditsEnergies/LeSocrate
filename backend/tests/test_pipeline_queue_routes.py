import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from routes.formation_routes import (
    _normalize_pipeline_model_choice,
    formation_bp,
)


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
        ]
        for route_patch in self.route_patches:
            route_patch.start()

    def tearDown(self):
        for route_patch in reversed(self.route_patches):
            route_patch.stop()

    def test_run_auto_enqueues_durable_work_item(self):
        item = SimpleNamespace(
            id="work-1",
            run_id="run-1",
            status="queued",
            terminal=False,
        )
        with patch.dict(os.environ, {"PIPELINE_EXECUTION_MODE": "queue"}), patch(
            "routes.formation_routes.get_job", return_value=_job()
        ), patch(
            "routes.formation_routes.update_job"
        ), patch(
            "routes.formation_routes._determine_next_ap_step", return_value="reac"
        ), patch(
            "services.pipeline_queue.get_latest_work_item", return_value=None
        ), patch(
            "services.pipeline_queue.enqueue_work_item", return_value=item
        ) as enqueue, patch(
            "services.formation_observability_service.log_pipeline_event"
        ):
            response = self.client.post(
                "/api/formation/42/run-auto",
                json={"model": "pro", "tts_mode": "gtts"},
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["dispatch"]["work_item_id"], "work-1")
        self.assertEqual(enqueue.call_args.kwargs["pipeline_job_id"], 42)
        self.assertEqual(enqueue.call_args.kwargs["payload"]["expected_step"], "reac")

    def test_run_auto_does_not_reset_an_active_queue_item(self):
        active = SimpleNamespace(
            id="work-active",
            run_id="run-active",
            status="running",
            terminal=False,
        )
        with patch.dict(os.environ, {"PIPELINE_EXECUTION_MODE": "queue"}), patch(
            "routes.formation_routes.get_job", return_value=_job(auto_pilot_step="content")
        ), patch(
            "routes.formation_routes.update_job"
        ) as update, patch(
            "services.pipeline_queue.get_latest_work_item", return_value=active
        ):
            response = self.client.post("/api/formation/42/run-auto", json={})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["work_item_id"], "work-active")
        update.assert_not_called()

    def test_stop_returns_cancelled_work_item_id_not_dataclass(self):
        cancelled = SimpleNamespace(id="work-cancelled")
        with patch.dict(os.environ, {"PIPELINE_EXECUTION_MODE": "queue"}), patch(
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
        with patch.dict(os.environ, {"PIPELINE_EXECUTION_MODE": "queue"}), patch(
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
