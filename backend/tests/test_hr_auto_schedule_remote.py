"""Tâche 1.36 : auto_schedule (ancien mode `schedule`) ne compte plus comme un
succès une plateforme distante qui répond en erreur.

`_call_platform` est simulé : il renvoie (payload, None) quand la plateforme
répond (200, 4xx relayé, 5xx sous forme neutre avec `error_id`) et
(None, message) quand elle n'est pas joignable.
"""

import os
import unittest
from unittest.mock import patch

from flask import Flask

from routes import hr_routes

API_KEY = "cle-test"
SCHEDULE = {"schedule": [{"platform_id": 2, "weekday": 0, "hour": 9}]}


class AutoScheduleRemotePlatformTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="auto-schedule-remote")
        app.register_blueprint(hr_routes.create_hr_blueprint())
        self.client = app.test_client()

    def _run(self, call_platform_result):
        with patch.dict(os.environ, {"PLATFORM_API_KEY": API_KEY}), patch.object(
            hr_routes, "_is_local_platform", return_value=False
        ), patch.object(
            hr_routes, "_call_platform", return_value=call_platform_result
        ) as call_platform, self.assertLogs(hr_routes.logger, level="INFO") as logs:
            response = self.client.post(
                "/api/internal/auto-schedule",
                json=SCHEDULE,
                headers={"X-Platform-Key": API_KEY},
            )
        self.assertEqual(response.status_code, 200)
        call_platform.assert_called_once()
        self.assertEqual(call_platform.call_args.args[1], "/api/internal/config-cours")
        payload = response.get_json()
        self.assertEqual(len(payload["results"]), 1)
        return payload, payload["results"][0], "\n".join(logs.output)

    def test_remote_success_is_counted_as_success(self):
        payload, result, logs = self._run(({"success": True, "message": "Heure mise à jour"}, None))

        self.assertTrue(payload["success"])
        self.assertTrue(result["success"])
        self.assertIn("scheduled", result)
        self.assertIn("📅 Auto-schedule P2", logs)

    def test_remote_4xx_is_a_failure_with_its_validation_message(self):
        payload, result, logs = self._run(({"success": False, "error": "heure_cours requis"}, None))

        self.assertFalse(payload["success"])
        self.assertEqual(
            result, {"platform_id": 2, "success": False, "error": "heure_cours requis"}
        )
        self.assertIn("ERROR", logs)
        self.assertIn("❌ Auto-schedule P2 : heure_cours requis", logs)

    def test_remote_5xx_is_a_neutral_failure_with_its_reference(self):
        neutral_5xx = {
            "success": False,
            "error": "Erreur interne sur la plateforme P2 (réf. 1a2b3c4d)",
            "error_id": "1a2b3c4d",
        }
        payload, result, logs = self._run((neutral_5xx, None))

        self.assertFalse(payload["success"])
        self.assertEqual(
            result,
            {
                "platform_id": 2,
                "success": False,
                "error": "Échec de la programmation sur la plateforme P2",
                "error_id": "1a2b3c4d",
            },
        )
        self.assertIn("ERROR", logs)
        self.assertIn("réf. 1a2b3c4d", logs)

    def test_unexpected_remote_payload_is_a_neutral_failure(self):
        payload, result, _logs = self._run((["pas", "un", "objet"], None))

        self.assertFalse(payload["success"])
        self.assertEqual(result["error"], "Échec de la programmation sur la plateforme P2")
        self.assertNotIn("error_id", result)

    def test_network_error_is_still_a_failure(self):
        payload, result, logs = self._run((None, "Plateforme P2 injoignable (réf. 9f8e7d6c)"))

        self.assertFalse(payload["success"])
        self.assertEqual(
            result,
            {"platform_id": 2, "success": False, "error": "Plateforme P2 injoignable (réf. 9f8e7d6c)"},
        )
        self.assertIn("ERROR", logs)


if __name__ == "__main__":
    unittest.main()
