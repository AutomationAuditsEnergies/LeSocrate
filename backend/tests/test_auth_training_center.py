import unittest
from unittest.mock import Mock, patch

from flask import Flask
from werkzeug.security import check_password_hash, generate_password_hash

from repositories.core_repository import DuplicateTrainingCenterUsername
from routes import admin_routes


class TrainingCenterAuthTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="training-center-auth-test")
        app.register_blueprint(admin_routes.create_admin_blueprint(Mock()))
        self.client = app.test_client()

    def _postgres_only(self):
        return patch.multiple(
            admin_routes,
            DATABASE_BACKEND="postgres",
            get_db_connection=Mock(
                side_effect=AssertionError("SQLite must not be opened")
            ),
        )

    def test_registration_requires_an_email_address(self):
        with patch.object(admin_routes, "create_training_center") as create_account:
            response = self.client.post(
                "/api/admin/register",
                json={
                    "center_name": "Centre test",
                    "username": "admin",
                    "password": "correct-password",
                },
            )

        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(
            response.get_json()["error"],
            "Une adresse email valide est requise",
        )
        create_account.assert_not_called()

    def test_postgres_registration_hashes_password_and_never_opens_sqlite(self):
        account = {
            "id": 17,
            "username": "contact@centre.test",
            "password_hash": "not-returned",
            "center_name": "Centre test",
            "slug": "centre-test",
            "is_active": True,
        }
        with self._postgres_only(), patch.object(
            admin_routes, "postgres_enabled", return_value=True
        ), patch.object(
            admin_routes, "sqlite_runtime_enabled", return_value=False
        ), patch.object(
            admin_routes, "create_training_center", return_value=account
        ) as create_account, patch.object(
            admin_routes,
            "_ensure_training_center_supabase_user",
            return_value=(True, None),
        ):
            response = self.client.post(
                "/api/admin/register",
                json={
                    "center_name": "Centre test",
                    "username": " CONTACT@CENTRE.TEST ",
                    "password": "correct-password",
                },
            )

        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["account"]["type"], "training_center")
        self.assertNotIn("password", response.get_json()["account"])
        kwargs = create_account.call_args.kwargs
        self.assertEqual(kwargs["username"], "contact@centre.test")
        self.assertIsNone(kwargs["password_debug_plaintext"])
        self.assertTrue(check_password_hash(kwargs["password_hash"], "correct-password"))

    def test_registered_postgres_center_can_reconnect_with_its_password(self):
        account = {
            "id": 18,
            "username": "direction@centre.test",
            "password_hash": generate_password_hash("correct-password"),
            "center_name": "Centre durable",
            "slug": "centre-durable",
            "is_active": True,
        }
        with self._postgres_only(), patch.object(
            admin_routes, "postgres_enabled", return_value=True
        ), patch.object(
            admin_routes, "get_training_center_by_username", return_value=account
        ) as get_account:
            response = self.client.post(
                "/api/admin/login",
                json={
                    "username": "DIRECTION@CENTRE.TEST",
                    "password": "correct-password",
                },
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["account"]["type"], "training_center")
        self.assertEqual(response.get_json()["account"]["id"], 18)
        get_account.assert_called_once_with("direction@centre.test")

    def test_wrong_center_password_is_rejected_without_sqlite_fallback(self):
        account = {
            "id": 19,
            "username": "direction@centre.test",
            "password_hash": generate_password_hash("correct-password"),
            "center_name": "Centre durable",
            "slug": "centre-durable",
            "is_active": True,
        }
        with self._postgres_only(), patch.object(
            admin_routes, "postgres_enabled", return_value=True
        ), patch.object(
            admin_routes, "get_training_center_by_username", return_value=account
        ), patch.object(
            admin_routes, "_authenticate_training_center_with_supabase", return_value=False
        ):
            response = self.client.post(
                "/api/admin/login",
                json={
                    "username": "direction@centre.test",
                    "password": "wrong-password",
                },
            )

        self.assertEqual(response.status_code, 401, response.get_json())
        self.assertEqual(response.get_json()["error"], "Identifiants incorrects")

    def test_duplicate_center_email_is_rejected(self):
        with patch.object(
            admin_routes, "postgres_enabled", return_value=True
        ), patch.object(
            admin_routes,
            "create_training_center",
            side_effect=DuplicateTrainingCenterUsername,
        ):
            response = self.client.post(
                "/api/admin/register",
                json={
                    "center_name": "Centre test",
                    "username": "contact@centre.test",
                    "password": "correct-password",
                },
            )

        self.assertEqual(response.status_code, 409, response.get_json())


if __name__ == "__main__":
    unittest.main()
