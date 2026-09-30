"""Tâche 1.19 : la partie RH ne renvoie plus le texte des exceptions.

Une exception inattendue contenant « secret xyz » ne doit jamais apparaître
dans la réponse ; elle doit apparaître dans les logs, avec la référence
(``error_id``) renvoyée au navigateur. Les 4xx écrits par notre code pour
l'utilisateur gardent leur message.
"""

import json
import logging
import os
import unittest
from unittest.mock import MagicMock, Mock, patch

from flask import Flask

from routes import hr_routes
from services import fish_voice_service, recruitment_conversation_service, script_rules_service
from utils.deepseek_client import DeepSeekAPIError
from utils.errors import register_api_error_handler

SECRET = "secret xyz"
API_KEY = "cle-test"
BLOB_PATH = "platform-3/folder-12/playlist/course_01.mp3"


def _logged(logs):
    return "\n".join(logging.Formatter().format(record) for record in logs.records)


class HrErrorMaskingTest(unittest.TestCase):
    def setUp(self):
        self._hr_enabled = patch.object(hr_routes, "HR_ENABLED", True)
        self._hr_enabled.start()
        self.addCleanup(self._hr_enabled.stop)
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="hr-error-masking")
        register_api_error_handler(app)
        app.register_blueprint(hr_routes.create_hr_blueprint())
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["is_admin"] = True
            session["admin_account_type"] = "legacy_admin"

    def assertSecretOnlyInLogs(self, response, logs):
        self.assertNotIn(SECRET, response.get_data(as_text=True))
        self.assertIn(SECRET, _logged(logs))

    # 500 inattendue ------------------------------------------------------
    def test_unexpected_error_is_a_masked_500(self):
        with patch.object(hr_routes, "_hr_pipeline_reads_use_postgres", return_value=True), patch.object(
            hr_routes, "list_hr_formation_modules", side_effect=RuntimeError(SECRET)
        ), self.assertLogs("utils.errors", level="ERROR") as logs:
            response = self.client.get("/api/hr/formation-modules")

        self.assertEqual(response.status_code, 500)
        payload = response.get_json()
        self.assertRegex(payload["error_id"], r"^[0-9a-f]{8}$")
        self.assertIn(payload["error_id"], _logged(logs))
        self.assertSecretOnlyInLogs(response, logs)

    # 400 gardé : message écrit par notre service ------------------------
    def test_user_facing_validation_message_is_kept(self):
        with patch(
            "services.script_annotation_service.create_script_annotation",
            side_effect=ValueError("Commentaire requis"),
        ):
            response = self.client.post(
                "/api/hr/cours-folders/12/content-job/annotations", json={}
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"success": False, "error": "Commentaire requis"})

    # Erreurs par élément -------------------------------------------------
    def test_per_item_storage_error_keeps_the_target_but_not_the_detail(self):
        blob_service = MagicMock()
        blob_service.get_blob_client.return_value.delete_blob.side_effect = RuntimeError(SECRET)
        env = {"AZURE_TTS_STORAGE_CONNECTION_STRING": "tts-conn"}
        with patch.dict(os.environ, env), patch.object(
            hr_routes, "get_course_folder_identity", return_value={"platform_id": 3}
        ), patch.object(
            hr_routes, "resolve_folder_blob_path", return_value=BLOB_PATH
        ), patch.object(
            hr_routes.BlobServiceClient, "from_connection_string", return_value=blob_service
        ), self.assertLogs("utils.errors", level="ERROR") as logs:
            os.environ.pop("AZURE_AUDIO_STORAGE_CONNECTION_STRING", None)
            os.environ.pop("AZURE_STORAGE_CONNECTION_STRING", None)
            response = self.client.delete("/api/hr/cours-folders/12/audio/course_01.mp3")

        self.assertEqual(response.status_code, 500)
        item = response.get_json()["errors"][0]
        self.assertEqual(item["target"], f"audiostts/{BLOB_PATH}")
        self.assertEqual(item["error"], "Échec de la suppression")
        self.assertIn(item["error_id"], _logged(logs))
        self.assertSecretOnlyInLogs(response, logs)

    def test_internal_blob_not_found_test_still_works(self):
        blob_service = MagicMock()
        blob_service.get_blob_client.return_value.delete_blob.side_effect = RuntimeError(
            "BlobNotFound: The specified blob does not exist."
        )
        with patch.dict(os.environ, {"AZURE_TTS_STORAGE_CONNECTION_STRING": "tts-conn"}), patch.object(
            hr_routes, "get_course_folder_identity", return_value={"platform_id": 3}
        ), patch.object(
            hr_routes, "resolve_folder_blob_path", return_value=BLOB_PATH
        ), patch.object(hr_routes.BlobServiceClient, "from_connection_string", return_value=blob_service):
            os.environ.pop("AZURE_AUDIO_STORAGE_CONNECTION_STRING", None)
            os.environ.pop("AZURE_STORAGE_CONNECTION_STRING", None)
            response = self.client.delete("/api/hr/cours-folders/12/audio/course_01.mp3")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])

    def test_local_auto_schedule_item_error_is_neutral(self):
        with patch.dict(os.environ, {"PLATFORM_API_KEY": API_KEY}), patch.object(
            hr_routes, "_is_local_platform", return_value=True
        ), patch(
            "services.time_service.set_heure_debut_cours", side_effect=RuntimeError(SECRET)
        ), self.assertLogs("utils.errors", level="ERROR") as logs:
            response = self.client.post(
                "/api/internal/auto-schedule",
                json={"schedule": [{"platform_id": 3, "weekday": 0, "hour": 9}]},
                headers={"X-Platform-Key": API_KEY},
            )

        result = response.get_json()["results"][0]
        self.assertEqual(result["platform_id"], 3)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Échec de la programmation du cours")
        self.assertIn(result["error_id"], _logged(logs))
        self.assertSecretOnlyInLogs(response, logs)

    # Pilotage d'une autre plateforme --------------------------------------
    def _remote(self, **request_kwargs):
        return (
            patch.dict(os.environ, {"PLATFORM_API_KEY": API_KEY}),
            patch.object(hr_routes, "_is_local_platform", return_value=False),
            patch.object(hr_routes, "_get_platform_info", return_value={"backend_url": "http://p2.interne:8000"}),
            patch.object(hr_routes.http_requests, "request", **request_kwargs),
        )

    def test_remote_platform_internal_error_is_not_relayed(self):
        remote = Mock(status_code=500, text=f'{{"success": false, "error": "{SECRET}"}}')
        remote.json.return_value = {"success": False, "error": SECRET}
        env, local, info, request = self._remote(return_value=remote)
        with env, local, info, request, self.assertLogs("utils.errors", level="ERROR") as logs:
            response = self.client.get("/api/hr/platforms/2/course-time")

        # Même code HTTP qu'avant (la réponse distante est relayée en 200) ;
        # seul le message devient neutre.
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload["success"])
        self.assertRegex(
            payload["error"],
            r"^Erreur interne sur la plateforme P2 \(réf\. [0-9a-f]{8}\)$",
        )
        self.assertIn(payload["error_id"], _logged(logs))
        self.assertSecretOnlyInLogs(response, logs)

    def test_remote_platform_non_json_error_keeps_the_previous_500(self):
        remote = Mock(status_code=502, text=f"<html>Bad gateway {SECRET}</html>")
        remote.json.side_effect = ValueError("Expecting value")
        env, local, info, request = self._remote(return_value=remote)
        with env, local, info, request, self.assertLogs("utils.errors", level="ERROR") as logs:
            response = self.client.get("/api/hr/platforms/2/course-time")

        self.assertEqual(response.status_code, 500)
        self.assertRegex(response.get_json()["error"], r"^Plateforme P2 injoignable \(réf\. [0-9a-f]{8}\)$")
        self.assertNotIn(SECRET, response.get_data(as_text=True))

    def test_unreachable_remote_platform_hides_the_network_error(self):
        env, local, info, request = self._remote(side_effect=ConnectionError(f"{SECRET} http://p2.interne:8000"))
        with env, local, info, request, self.assertLogs("utils.errors", level="ERROR") as logs:
            response = self.client.get("/api/hr/platforms/2/course-time")

        self.assertEqual(response.status_code, 500)
        self.assertRegex(response.get_json()["error"], r"^Plateforme P2 injoignable \(réf\. [0-9a-f]{8}\)$")
        self.assertNotIn("p2.interne", response.get_data(as_text=True))
        self.assertSecretOnlyInLogs(response, logs)

    def test_remote_platform_validation_message_is_still_relayed(self):
        remote = Mock(status_code=400)
        remote.json.return_value = {"success": False, "error": "Au moins un jour de cours est requis"}
        env, local, info, request = self._remote(return_value=remote)
        with env, local, info, request:
            response = self.client.get("/api/hr/platforms/2/course-time")

        self.assertEqual(response.get_json()["error"], "Au moins un jour de cours est requis")


class ServiceErrorMaskingTest(unittest.TestCase):
    """Fuites corrigées à la source, dans les services appelés par les routes RH."""

    def test_fish_audio_response_detail_stays_in_the_logs(self):
        response = Mock(ok=False, status_code=400)
        response.json.return_value = {"message": SECRET}
        with self.assertLogs("services.fish_voice_service", level="WARNING") as logs:
            with self.assertRaises(fish_voice_service.FishVoiceError) as raised:
                fish_voice_service._raise_for_fish(response, "Clonage")

        self.assertEqual(str(raised.exception), "Clonage impossible via Fish Audio (400).")
        self.assertEqual(raised.exception.code, "fish_audio_request_failed")
        self.assertIn(SECRET, _logged(logs))

    def test_deepseek_extraction_error_is_replaced_by_a_neutral_message(self):
        with patch.object(script_rules_service, "_fetch_context", return_value={"job_id": 7}), patch.object(
            script_rules_service, "_fetch_applied_annotations", return_value=[{"id": 1}]
        ), patch.object(script_rules_service, "_build_llm_prompt", return_value="prompt"), patch.object(
            script_rules_service, "post_message", side_effect=DeepSeekAPIError(500, "server_error", SECRET)
        ):
            with self.assertRaises(ValueError) as raised:
                script_rules_service.extract_rules_from_annotations(12)

        self.assertNotIn(SECRET, str(raised.exception))
        self.assertIn("DeepSeek n'a pas pu extraire les règles", str(raised.exception))

    def test_invalid_model_json_keeps_our_message(self):
        with self.assertRaises(ValueError) as raised:
            recruitment_conversation_service._parse_json_object('{"champ": secret xyz}')

        self.assertEqual(str(raised.exception), "Réponse NLP invalide")
        self.assertIsInstance(raised.exception.__cause__, json.JSONDecodeError)


if __name__ == "__main__":
    unittest.main()
