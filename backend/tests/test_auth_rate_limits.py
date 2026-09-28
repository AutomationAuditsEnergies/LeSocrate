import os
import unittest
from unittest.mock import Mock, patch

from flask import Flask
from werkzeug.security import generate_password_hash

from routes import admin_routes, auth_routes
from utils.rate_limit import (
    RATE_LIMIT_ERROR,
    apply_auth_rate_limits,
    client_ip,
    init_rate_limiter,
)


STUDENT_ACCOUNT = {
    "id": 8,
    "username": "lina",
    "password_hash": generate_password_hash("correct-password"),
    "nom": "Martin",
    "prenom": "Lina",
    "is_active": True,
}


class AuthRateLimitTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="rate-limit-test")
        limiter = init_rate_limiter(app)
        app.register_blueprint(auth_routes.create_auth_blueprint())
        app.register_blueprint(admin_routes.create_admin_blueprint())
        apply_auth_rate_limits(app, limiter)
        self.app = app
        self.client = app.test_client()

    def _student_login(self, password, ip="203.0.113.10"):
        with patch.multiple(
            auth_routes,
            DATABASE_BACKEND="postgres",
            get_db_connection=Mock(side_effect=AssertionError("SQLite must not be opened")),
        ), patch.object(
            auth_routes, "get_student_account", return_value=STUDENT_ACCOUNT
        ), patch.object(auth_routes, "create_log", return_value=91):
            return self.client.post(
                "/api/auth/login",
                json={"platform_id": 4, "username": "lina", "password": password},
                environ_base={"REMOTE_ADDR": ip},
            )

    def test_eleventh_student_login_in_a_minute_is_rejected(self):
        for attempt in range(10):
            response = self._student_login("wrong-password")
            self.assertNotEqual(response.status_code, 429, f"essai {attempt + 1}")

        response = self._student_login("correct-password")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            response.get_json(), {"success": False, "error": RATE_LIMIT_ERROR}
        )

    def test_normal_student_login_still_works(self):
        response = self._student_login("correct-password")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()["success"])

    def test_limit_is_counted_per_ip(self):
        for _ in range(11):
            self._student_login("wrong-password", ip="203.0.113.10")

        response = self._student_login("correct-password", ip="198.51.100.20")

        self.assertEqual(response.status_code, 200, response.get_json())

    def test_supabase_session_is_limited_to_ten_per_minute(self):
        statuses = [
            self.client.post("/api/auth/supabase-session", json={}).status_code
            for _ in range(11)
        ]

        self.assertNotIn(429, statuses[:10])
        self.assertEqual(statuses[10], 429)

    def test_internal_admin_login_is_limited_to_five_per_minute(self):
        with patch.dict(
            os.environ,
            {"INTERNAL_ADMIN_PASSWORD_HASH": "", "INTERNAL_ADMIN_PASSWORD": ""},
        ):
            statuses = [
                self.client.post(
                    "/api/admin/login",
                    json={"username": "admin", "password": "wrong-password"},
                ).status_code
                for _ in range(6)
            ]

        self.assertNotIn(429, statuses[:5])
        self.assertEqual(statuses[5], 429)

    def test_center_registration_is_limited_to_five_per_hour(self):
        statuses = [
            self.client.post("/api/admin/register", json={}).status_code
            for _ in range(6)
        ]

        self.assertEqual(statuses[:5], [400] * 5)
        self.assertEqual(statuses[5], 429)

    def test_apps_do_not_share_counters(self):
        for _ in range(11):
            self._student_login("wrong-password")

        self.setUp()
        response = self._student_login("correct-password")

        self.assertEqual(response.status_code, 200, response.get_json())


class ClientIpTest(unittest.TestCase):
    def _ip(self, remote_addr):
        app = Flask(__name__)
        with app.test_request_context(environ_base={"REMOTE_ADDR": remote_addr}):
            return client_ip()

    def test_port_is_dropped_from_forwarded_addresses(self):
        self.assertEqual(self._ip("203.0.113.10:51234"), "203.0.113.10")
        self.assertEqual(self._ip("[2001:db8::1]:51234"), "2001:db8::1")

    def test_plain_addresses_are_unchanged(self):
        self.assertEqual(self._ip("203.0.113.10"), "203.0.113.10")
        self.assertEqual(self._ip("2001:db8::1"), "2001:db8::1")


if __name__ == "__main__":
    unittest.main()
