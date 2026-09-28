import os
import unittest
from unittest.mock import patch

from flask import Flask

from routes import admin_routes


LOCAL_ACCOUNT = {
    "id": 42,
    "username": "local-dev@cadrenza.test",
    "center_name": "Environnement local",
    "slug": "local-dev",
    "is_active": 1,
    "pipeline_access_enabled": 0,
}


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

    def _dev_login(self, env, remote_addr="127.0.0.1"):
        """POST dev-login with exactly LOCAL_DEV / WEBSITE_SITE_NAME from ``env``."""
        with patch.dict("os.environ", env), patch.object(
            admin_routes,
            "_get_or_create_local_dev_center",
            return_value=LOCAL_ACCOUNT,
        ) as create_account:
            if "WEBSITE_SITE_NAME" not in env:
                os.environ.pop("WEBSITE_SITE_NAME", None)
            response = self.client.post(
                "/api/admin/dev-login",
                environ_base={"REMOTE_ADDR": remote_addr},
            )
        return response, create_account

    def test_dev_login_is_refused_on_azure_even_with_local_dev(self):
        response, create_account = self._dev_login(
            {"LOCAL_DEV": "true", "WEBSITE_SITE_NAME": "cadrenza-p3"}
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json(),
            {"success": False, "error": "Accès local indisponible"},
        )
        create_account.assert_not_called()

    def test_dev_login_works_locally_on_loopback(self):
        response, _ = self._dev_login({"LOCAL_DEV": "true"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])

    def test_dev_login_is_refused_locally_without_local_dev(self):
        response, create_account = self._dev_login({"LOCAL_DEV": "false"})

        self.assertEqual(response.status_code, 404)
        create_account.assert_not_called()

    def test_dev_login_is_refused_locally_from_another_ip(self):
        response, create_account = self._dev_login(
            {"LOCAL_DEV": "true"}, remote_addr="192.168.1.50"
        )

        self.assertEqual(response.status_code, 404)
        create_account.assert_not_called()


class LocalDevStartupGuardTest(unittest.TestCase):
    def test_local_dev_is_switched_off_and_logged_on_azure(self):
        with patch.dict(
            "os.environ", {"LOCAL_DEV": "1", "WEBSITE_SITE_NAME": "cadrenza-p3"}
        ), self.assertLogs(admin_routes.logger, level="WARNING") as logs:
            disabled = admin_routes.disable_local_dev_login_on_azure()
            local_dev_after = os.environ["LOCAL_DEV"]

        self.assertTrue(disabled)
        self.assertEqual(local_dev_after, "false")
        self.assertIn("LOCAL_DEV_IGNORED_ON_AZURE", logs.output[0])

    def test_local_dev_is_kept_outside_azure(self):
        with patch.dict("os.environ", {"LOCAL_DEV": "1"}):
            os.environ.pop("WEBSITE_SITE_NAME", None)
            disabled = admin_routes.disable_local_dev_login_on_azure()
            local_dev_after = os.environ["LOCAL_DEV"]

        self.assertFalse(disabled)
        self.assertEqual(local_dev_after, "1")


if __name__ == "__main__":
    unittest.main()
