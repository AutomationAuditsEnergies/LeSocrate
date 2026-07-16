import sys
import types
import unittest
from unittest.mock import patch

from flask import Flask

_export_service = types.ModuleType("services.export_service")
_export_service.generate_attendance_excel_export = lambda *_args, **_kwargs: None
_export_service.generate_excel_export = lambda *_args, **_kwargs: None
sys.modules.setdefault("services.export_service", _export_service)

from routes.hr_routes import create_hr_blueprint


class CenterWorkspaceRoutesTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(create_hr_blueprint(None))
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["is_admin"] = True
            sess["admin_account_type"] = "training_center"
            sess["admin_account_id"] = 42

    def test_onboarding_state_is_versioned_and_persisted_server_side(self):
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.get_center_onboarding_state",
            return_value={
                "id": 42,
                "onboarding_version": 0,
                "onboarding_completed_at": None,
            },
        ):
            response = self.client.get("/api/hr/onboarding")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["completed"])

        completed = {
            "id": 42,
            "onboarding_version": 1,
            "onboarding_completed_at": "2026-07-16T14:00:00Z",
        }
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.complete_center_onboarding",
            return_value=completed,
        ) as persist:
            response = self.client.post("/api/hr/onboarding/complete", json={"version": 1})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["completed"])
        persist.assert_called_once_with(42, 1)

    def test_archive_changes_lifecycle_without_deleting_the_teacher(self):
        lifecycle = {
            "id": 12,
            "lifecycle_status": "archived",
            "completed_at": None,
            "archived_at": "2026-07-16T14:00:00Z",
            "asset_binding_mode": "shared",
        }
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center", return_value=True,
        ), patch(
            "routes.hr_routes.set_platform_lifecycle", return_value=lifecycle,
        ) as set_lifecycle:
            response = self.client.patch(
                "/api/hr/platforms/12/lifecycle",
                json={"lifecycle_status": "archived"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["platform"]["asset_binding_mode"], "shared")
        set_lifecycle.assert_called_once_with(12, 42, "archived")

    def test_training_center_cannot_hard_delete_a_durable_teacher(self):
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center", return_value=True,
        ), patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("hard delete must stop before opening the database"),
        ):
            response = self.client.delete("/api/hr/platforms/12")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "archive_required")


if __name__ == "__main__":
    unittest.main()
