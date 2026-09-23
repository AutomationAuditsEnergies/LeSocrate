"""A resumed pipeline can change model without restarting completed work."""

import unittest
from unittest.mock import patch

from flask import Flask

from routes.formation_routes import formation_bp


class AutoPilotResumeModelTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(formation_bp)
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["is_admin"] = True
        self.job = {
            "id": 6,
            "auto_pilot_model": "pro",
            "auto_pilot_step": "content",
            "auto_pilot_tts_mode": "gtts",
            "auto_pilot_use_cc": 0,
            "auto_pilot_generate_audio": 0,
        }

    def test_resume_switches_remaining_steps_to_flash(self):
        with patch("routes.formation_routes.get_job", return_value=self.job), \
             patch("routes.formation_routes._ap_lock_age_seconds", return_value=None), \
             patch("routes.formation_routes._determine_next_ap_step", return_value="review"), \
             patch("routes.formation_routes.update_job") as update_job, \
             patch("services.formation_observability_service.log_pipeline_event") as log_event, \
             patch("eventlet.spawn") as spawn:
            response = self.client.post(
                "/api/formation/6/run-auto/resume", json={"model": "flash"}
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["model"], "flash")
        update_job.assert_called_once_with(
            6,
            auto_pilot_enabled=1,
            auto_pilot_error=None,
            auto_pilot_locked_at=None,
            auto_pilot_lock_owner=None,
            auto_pilot_step="review",
            auto_pilot_model="flash",
            auto_pilot_use_cc=0,
        )
        self.assertEqual(log_event.call_args.kwargs["model"], "flash")
        spawn.assert_called_once()

    def test_invalid_model_does_not_resume(self):
        with patch("routes.formation_routes.get_job", return_value=self.job), \
             patch("routes.formation_routes._ap_lock_age_seconds", return_value=None), \
             patch("routes.formation_routes.update_job") as update_job, \
             patch("eventlet.spawn") as spawn:
            response = self.client.post(
                "/api/formation/6/run-auto/resume", json={"model": "unknown"}
            )

        self.assertEqual(response.status_code, 400)
        update_job.assert_not_called()
        spawn.assert_not_called()

    def test_active_lock_keeps_existing_model(self):
        with patch("routes.formation_routes.get_job", return_value=self.job), \
             patch("routes.formation_routes._ap_lock_age_seconds", return_value=1), \
             patch("routes.formation_routes.update_job") as update_job:
            response = self.client.post(
                "/api/formation/6/run-auto/resume", json={"model": "flash"}
            )

        self.assertEqual(response.status_code, 409)
        update_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
