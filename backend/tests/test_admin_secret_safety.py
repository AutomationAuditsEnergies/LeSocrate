import os
import unittest
from unittest.mock import Mock, patch

from flask import Flask
from werkzeug.security import generate_password_hash

from routes import admin_routes


class AdminSecretSafetyTest(unittest.TestCase):
    def test_historical_hardcoded_password_is_not_a_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(admin_routes._internal_admin_password_valid("secret123"))

    def test_deployment_hash_authenticates_without_plaintext_storage(self):
        password_hash = generate_password_hash("a-long-deployment-secret")
        with patch.dict(
            os.environ,
            {"INTERNAL_ADMIN_PASSWORD_HASH": password_hash},
            clear=True,
        ):
            self.assertTrue(
                admin_routes._internal_admin_password_valid("a-long-deployment-secret")
            )
            self.assertFalse(admin_routes._internal_admin_password_valid("wrong"))

    def test_unknown_center_never_falls_back_to_sqlite_in_pure_postgres(self):
        app = Flask(__name__)
        app.secret_key = "test-secret"
        app.register_blueprint(admin_routes.create_admin_blueprint(Mock()))

        with app.test_client() as client, patch.object(
            admin_routes, "DATABASE_BACKEND", "postgres"
        ), patch.object(admin_routes, "postgres_enabled", return_value=True), patch.object(
            admin_routes, "get_training_center_by_username", return_value=None
        ), patch.object(
            admin_routes,
            "get_db_connection",
            side_effect=AssertionError("SQLite must not be opened"),
        ):
            response = client.post(
                "/api/admin/login",
                json={"username": "unknown-center", "password": "wrong"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "Identifiants incorrects")


if __name__ == "__main__":
    unittest.main()
