import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from routes.formation_routes import formation_bp


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
            session["admin_account_type"] = "legacy_admin"

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


if __name__ == "__main__":
    unittest.main()
