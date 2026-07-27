import unittest
from unittest.mock import patch

from flask import Flask

from routes import slides_routes


class SlidesTenantScopeTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="slides-tenant-test")
        app.register_blueprint(slides_routes.slides_bp)
        self.client = app.test_client()

    def _login(self, account_type="training_center", account_id=10):
        with self.client.session_transaction() as admin_session:
            admin_session.update({
                "is_admin": True,
                "admin_account_type": account_type,
                "admin_account_id": account_id,
            })

    def test_center_cannot_read_another_centers_persisted_deck(self):
        self._login()
        with patch.object(
            slides_routes,
            "hr_resource_belongs_to_center",
            return_value=False,
        ), patch.object(
            slides_routes,
            "get_latest_script_slide_deck",
        ) as get_deck:
            response = self.client.get("/api/slides/data?folder_id=22")

        self.assertEqual(response.status_code, 404)
        get_deck.assert_not_called()

    def test_center_folder_deck_is_allowed_only_after_tenant_resolution(self):
        self._login()
        deck = {
            "slides": [],
            "stats": {},
            "timeline": [],
            "pipeline_debug": {},
            "audio_sync": {},
            "deck_id": 7,
        }
        with patch.object(
            slides_routes,
            "hr_resource_belongs_to_center",
            return_value=True,
        ) as belongs, patch.object(
            slides_routes,
            "get_latest_script_slide_deck",
            return_value=deck,
        ):
            response = self.client.get("/api/slides/data?folder_id=22")

        self.assertEqual(response.status_code, 200)
        belongs.assert_called_once_with("folder", 22, 10)

    def test_center_cannot_access_process_global_slide_state(self):
        self._login()
        for method, path, expected_status in (
            ("get", "/api/slides/data", 404),
            ("get", "/api/slides/status", 403),
            ("post", "/api/slides/clear", 403),
            ("post", "/api/slides/preview-from-text", 403),
        ):
            with self.subTest(path=path):
                response = getattr(self.client, method)(path, json={"text": "x"})
                self.assertEqual(response.status_code, expected_status)

    def test_script_generation_requires_pipeline_permission_before_tenant_lookup(self):
        self._login()
        with patch.object(
            slides_routes,
            "can_access_formation_pipeline",
            return_value=False,
        ) as permission, patch.object(
            slides_routes,
            "hr_resource_belongs_to_center",
        ) as belongs, patch.object(
            slides_routes,
            "generate_slides_from_script",
        ) as generate:
            response = self.client.post(
                "/api/slides/generate-from-script",
                json={"folder_id": 22, "platform_id": 2},
            )

        self.assertEqual(response.status_code, 403)
        permission.assert_called_once_with("training_center", 10)
        belongs.assert_not_called()
        generate.assert_not_called()

    def test_legacy_admin_cannot_generate_pipeline_slides(self):
        self._login(account_type="legacy_admin", account_id=1)
        with patch.object(
            slides_routes,
            "generate_slides_from_script",
        ) as generate:
            response = self.client.post(
                "/api/slides/generate-from-script",
                json={"folder_id": 22},
            )

        self.assertEqual(response.status_code, 403)
        generate.assert_not_called()

    def test_legacy_superadmin_keeps_prototype_status_access(self):
        self._login(account_type="legacy_admin", account_id=1)
        with patch.object(
            slides_routes,
            "get_generation_status",
            return_value={"status": "ready"},
        ):
            response = self.client.get("/api/slides/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ready")


if __name__ == "__main__":
    unittest.main()
