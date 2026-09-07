import unittest
from unittest.mock import patch

from flask import Flask

from routes import admin_routes


class AdminSessionPermissionsTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "admin-session-permissions"
        app.register_blueprint(admin_routes.create_admin_blueprint())
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

    def test_local_dev_login_creates_center_session_on_loopback(self):
        local_account = {
            "id": 42,
            "username": "local-dev@cadrenza.test",
            "center_name": "Environnement local",
            "slug": "local-dev",
            "is_active": 1,
            "pipeline_access_enabled": 0,
        }
        with patch.dict("os.environ", {"LOCAL_DEV": "true"}), patch.object(
            admin_routes,
            "_get_or_create_local_dev_center",
            return_value=local_account,
        ):
            response = self.client.post("/api/admin/dev-login")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        self.assertEqual(response.get_json()["account"]["type"], "training_center")

        session_response = self.client.get("/api/admin/session")
        self.assertEqual(session_response.status_code, 200)
        self.assertTrue(session_response.get_json()["authenticated"])

    def test_local_dev_login_is_hidden_outside_dev_mode(self):
        with patch.dict("os.environ", {"LOCAL_DEV": "false"}):
            response = self.client.post("/api/admin/dev-login")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
