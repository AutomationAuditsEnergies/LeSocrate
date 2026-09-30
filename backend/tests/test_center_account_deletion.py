import unittest
from unittest.mock import patch

from flask import Flask

from routes import admin_routes


class CenterAccountDeletionTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="center-delete-test")
        app.register_blueprint(admin_routes.create_admin_blueprint())
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["is_admin"] = True
            session["admin_account_type"] = "training_center"
            session["admin_account_id"] = 42
            session["center_name"] = "Centre Atlas"

    def test_requires_exact_center_name_before_deletion(self):
        with patch.object(admin_routes, "postgres_enabled", return_value=True), patch.object(
            admin_routes, "delete_training_center_account"
        ) as delete:
            response = self.client.delete(
                "/api/admin/account",
                json={"confirmation": "Centre incorrect"},
            )

        self.assertEqual(response.status_code, 400, response.get_json())
        delete.assert_not_called()

    def test_deletes_the_authenticated_center_and_clears_session(self):
        with patch.object(admin_routes, "postgres_enabled", return_value=True), patch.object(
            admin_routes, "delete_training_center_account", return_value=True
        ) as delete, patch.object(
            admin_routes, "_delete_training_center_supabase_user", return_value=True
        ):
            response = self.client.delete(
                "/api/admin/account",
                json={"confirmation": "Centre Atlas"},
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        delete.assert_called_once_with(42, None)
        with self.client.session_transaction() as session:
            self.assertNotIn("is_admin", session)
            self.assertNotIn("admin_account_id", session)


if __name__ == "__main__":
    unittest.main()
