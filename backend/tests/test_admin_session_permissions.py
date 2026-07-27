import unittest
from unittest.mock import Mock, patch

from flask import Flask

from routes import admin_routes


class AdminSessionPermissionsTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "admin-session-permissions"
        app.register_blueprint(admin_routes.create_admin_blueprint(Mock()))
        self.client = app.test_client()

    def test_session_exposes_current_database_permissions(self):
        with self.client.session_transaction() as session:
            session["is_admin"] = True
            session["admin_account_type"] = "training_center"
            session["admin_account_id"] = 12
            session["center_name"] = "Lyon"

        with patch.object(
            admin_routes,
            "get_admin_permissions",
            return_value={"formation_pipeline": True},
        ) as permissions:
            response = self.client.get("/api/admin/session")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["account"]["permissions"],
            {"formation_pipeline": True},
        )
        permissions.assert_called_once_with("training_center", 12)

    def test_incomplete_session_never_falls_back_to_legacy_admin(self):
        with self.client.session_transaction() as session:
            session["is_admin"] = True

        response = self.client.get("/api/admin/session")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()["account"]["type"])
        self.assertEqual(
            response.get_json()["account"]["permissions"],
            {"formation_pipeline": False},
        )


if __name__ == "__main__":
    unittest.main()
