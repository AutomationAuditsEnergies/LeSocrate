import os
import unittest
from unittest.mock import patch

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

    def test_legacy_center_login_is_rejected_before_any_database_lookup(self):
        app = Flask(__name__)
        app.secret_key = "test-secret"
        app.register_blueprint(admin_routes.create_admin_blueprint())

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
        self.assertEqual(response.get_json()["error"], "Utilisez la connexion Supabase Auth.")

    def test_registration_never_opens_sqlite_in_pure_postgres(self):
        app = Flask(__name__)
        app.secret_key = "test-secret"
        app.register_blueprint(admin_routes.create_admin_blueprint())
        account = {
            "id": 42,
            "username": "centre@example.test",
            "password_hash": "hash",
            "center_name": "Centre Test",
            "slug": "centre-test",
            "is_active": True,
        }

        with app.test_client() as client, patch.object(
            admin_routes, "postgres_enabled", return_value=True
        ), patch.object(
            admin_routes,
            "_create_training_center_supabase_user",
            return_value=({"id": "auth-user-42"}, None, 201),
        ), patch.object(
            admin_routes, "sqlite_runtime_enabled", return_value=False
        ), patch.object(
            admin_routes, "create_training_center", return_value=account
        ) as create_center, patch.object(
            admin_routes,
            "get_db_connection",
            side_effect=AssertionError("SQLite must not be opened"),
        ):
            response = client.post(
                "/api/admin/register",
                json={
                    "username": "centre@example.test",
                    "password": "correct-password",
                    "center_name": "Centre Test",
                },
            )

        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertTrue(response.get_json()["success"])
        self.assertEqual(response.get_json()["account"]["id"], 42)
        self.assertNotIn("token", response.get_json())
        create_center.assert_called_once()
        self.assertEqual(
            create_center.call_args.kwargs["auth_user_id"],
            "auth-user-42",
        )

    def test_unknown_password_reset_never_opens_sqlite_in_pure_postgres(self):
        app = Flask(__name__)
        app.secret_key = "test-secret"
        app.register_blueprint(admin_routes.create_admin_blueprint())

        with app.test_client() as client, patch.object(
            admin_routes, "DATABASE_BACKEND", "postgres"
        ), patch.object(
            admin_routes, "postgres_enabled", return_value=True
        ), patch.object(
            admin_routes, "get_training_center_by_username", return_value=None
        ), patch.object(
            admin_routes,
            "get_db_connection",
            side_effect=AssertionError("SQLite must not be opened"),
        ):
            response = client.post(
                "/api/admin/forgot-password",
                json={"username": "unknown@example.test"},
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()["success"])
        self.assertIn("Si un compte existe", response.get_json()["message"])

    def test_postgres_registration_ignores_optional_sqlite_mirror_failure(self):
        app = Flask(__name__)
        app.secret_key = "test-secret"
        app.register_blueprint(admin_routes.create_admin_blueprint())
        account = {
            "id": 43,
            "username": "hybrid@example.test",
            "password_hash": "hash",
            "center_name": "Centre Hybride",
            "slug": "centre-hybride",
            "is_active": True,
        }

        with app.test_client() as client, patch.object(
            admin_routes, "postgres_enabled", return_value=True
        ), patch.object(
            admin_routes,
            "_create_training_center_supabase_user",
            return_value=({"id": "auth-user-43"}, None, 201),
        ), patch.object(
            admin_routes, "sqlite_runtime_enabled", return_value=True
        ), patch.object(
            admin_routes, "create_training_center", return_value=account
        ), patch.object(
            admin_routes, "get_db_connection", side_effect=RuntimeError("mirror unavailable")
        ):
            response = client.post(
                "/api/admin/register",
                json={
                    "username": "hybrid@example.test",
                    "password": "correct-password",
                    "center_name": "Centre Hybride",
                },
            )

        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertTrue(response.get_json()["success"])


if __name__ == "__main__":
    unittest.main()
