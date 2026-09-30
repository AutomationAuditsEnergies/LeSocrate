"""Tâches 1.17 et 1.18 : les routes ne renvoient plus le texte des exceptions.

Pour une route de chaque fichier traité, une exception inattendue contenant
« secret xyz » donne un 500 avec ``error_id`` : le texte reste dans les logs et
n'apparaît jamais dans la réponse. Les 400 dont le message est écrit par notre
code pour l'utilisateur gardent ce message.
"""

import logging
import os
import unittest
from unittest.mock import Mock, patch

from flask import Flask

from routes import admin_routes, billing_routes, debug_routes, formation_routes, slides_routes
from services import billing_service
from utils.errors import register_api_error_handler

SECRET = "secret xyz"


def _app(*blueprints, account_type="legacy_admin", account_id=None):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="error-masking-test")
    register_api_error_handler(app)
    for blueprint in blueprints:
        app.register_blueprint(blueprint)
    client = app.test_client()
    with client.session_transaction() as session:
        session["is_admin"] = True
        session["admin_account_type"] = account_type
        if account_id is not None:
            session["admin_account_id"] = account_id
        session["platform_id"] = 3
    return client


def _pipeline_center(*blueprints):
    """Centre avec accès pipeline : seul profil admis sur formation et slides."""
    return _app(*blueprints, account_type="training_center", account_id=7)


def _slides_guards_pass():
    return (
        patch.object(slides_routes, "can_access_formation_pipeline", return_value=True),
        patch.object(slides_routes, "hr_resource_belongs_to_center", return_value=True),
    )


class MaskedInternalErrorTest(unittest.TestCase):
    def assertMasked(self, send):
        with self.assertLogs("utils.errors", level="ERROR") as logs:
            response = send()

        self.assertEqual(response.status_code, 500, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertFalse(payload["success"])
        self.assertRegex(payload["error_id"], r"^[0-9a-f]{8}$")
        self.assertNotIn(SECRET, response.get_data(as_text=True))
        logged = logging.Formatter().format(logs.records[0])
        self.assertIn(payload["error_id"], logged)
        self.assertIn(SECRET, logged)
        return payload

    def test_formation_routes(self):
        client = _pipeline_center(formation_routes.formation_bp)
        with patch.object(
            formation_routes, "can_access_formation_pipeline", return_value=True
        ), patch.object(formation_routes, "search_rncp", side_effect=RuntimeError(SECRET)):
            self.assertMasked(
                lambda: client.post("/api/formation/search-rncp", json={"query": "TP CRCD"})
            )

    def test_slides_routes(self):
        client = _pipeline_center(slides_routes.slides_bp)
        access, ownership = _slides_guards_pass()
        with access, ownership, patch.object(
            slides_routes, "generate_slides_from_script", side_effect=RuntimeError(SECRET)
        ):
            self.assertMasked(
                lambda: client.post("/api/slides/generate-from-script", json={"folder_id": 12})
            )

    def test_admin_routes(self):
        client = _app(admin_routes.create_admin_blueprint())
        with patch.object(admin_routes, "get_heure_debut_cours", side_effect=RuntimeError(SECRET)):
            self.assertMasked(lambda: client.get("/api/admin/course-time"))

    def test_debug_routes(self):
        client = _app(debug_routes.debug_bp)
        with patch.object(
            debug_routes, "get_current_playback_context", side_effect=RuntimeError(SECRET)
        ):
            self.assertMasked(lambda: client.get("/api/debug/cours-info"))


class UserFacingValidationMessageTest(unittest.TestCase):
    """400 : un message écrit par notre code pour l'utilisateur est conservé."""

    def test_slides_validation_message_is_kept(self):
        client = _pipeline_center(slides_routes.slides_bp)
        message = "Aucun segment complété pour le dossier 12"
        access, ownership = _slides_guards_pass()
        with access, ownership, patch.object(
            slides_routes, "generate_slides_from_script", side_effect=ValueError(message)
        ):
            response = client.post("/api/slides/generate-from-script", json={"folder_id": 12})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["message"], message)

    def test_internal_schedule_validation_message_is_kept(self):
        client = _app(admin_routes.create_admin_blueprint())
        message = "Au moins un jour de cours est requis"
        with patch.dict(os.environ, {"PLATFORM_API_KEY": "cle-test"}), patch.object(
            admin_routes, "schedule_store_is_postgres", return_value=True
        ), patch.object(
            admin_routes, "update_course_schedule", side_effect=ValueError(message)
        ):
            response = client.post(
                "/api/internal/config-cours",
                json={"platform_id": 3, "heure_cours": "09:00", "weekdays": []},
                headers={"X-Platform-Key": "cle-test"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"success": False, "error": message})


class StripeWebhookErrorTest(unittest.TestCase):
    def test_rejected_event_detail_stays_on_the_server(self):
        client = _app(billing_routes.billing_bp)
        stripe = Mock()
        stripe.Webhook.construct_event.return_value = {"id": "evt_test", "type": "checkout.session.completed"}
        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "whsec_test"}), patch.object(
            billing_service, "_stripe_sdk", return_value=stripe
        ), patch.object(
            billing_service, "apply_stripe_webhook_event", side_effect=ValueError(SECRET)
        ), patch.object(billing_service, "record_webhook_failure") as record_failure:
            response = client.post(
                "/api/billing/stripe/webhook",
                data=b"{}",
                headers={"Stripe-Signature": "t=1,v1=test"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(), {"received": False, "error": "Événement Stripe invalide."}
        )
        self.assertNotIn(SECRET, response.get_data(as_text=True))
        record_failure.assert_called_once()
        self.assertIn(SECRET, record_failure.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
