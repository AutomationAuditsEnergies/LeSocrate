"""Platform-operator role (tâches 1.12–1.14).

The review inbox, the review exemption and the test clock depend only on the
``is_platform_operator`` column of an active centre, never on its e-mail.
"""

import sqlite3
import unittest
from unittest.mock import patch

from flask import Flask

from repositories import test_clock_repository
from routes import billing_routes
from routes.hr_routes import create_hr_blueprint
from services import admin_access_service, billing_service


def _center(center_id, username, *, operator, active=True):
    return {
        "id": center_id,
        "username": username,
        "center_name": f"Centre {center_id}",
        "is_active": active,
        "is_platform_operator": operator,
        "pipeline_access_enabled": False,
        "billing_mode": "stripe_required",
    }


OPERATOR = _center(7, "operateur@example.test", operator=True)
NORMAL_CENTER = _center(8, "centre@example.test", operator=False)
# L'ancien e-mail codé en dur ne donne plus aucun droit sans le rôle.
HISTORICAL_EMAIL_WITHOUT_ROLE = _center(9, "newpiprod@gmail.com", operator=False)
INACTIVE_OPERATOR = _center(10, "ancien@example.test", operator=True, active=False)
DENIED_CENTERS = (NORMAL_CENTER, HISTORICAL_EMAIL_WITHOUT_ROLE, INACTIVE_OPERATOR)


def _login(client, center):
    with client.session_transaction() as session:
        session["is_admin"] = True
        session["admin_account_type"] = "training_center"
        session["admin_account_id"] = center["id"]


class OrderReviewInboxTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="platform-operator-billing")
        app.register_blueprint(billing_routes.billing_bp)
        self.client = app.test_client()

    def _open_inbox(self, center):
        _login(self.client, center)
        inbox = {"requests": [], "unread_count": 0, "pending_count": 0}
        with patch.object(
            billing_service, "get_center_billing_account", return_value=center
        ), patch.object(
            billing_routes, "postgres_enabled", return_value=True
        ), patch.object(
            billing_routes, "admin_review_inbox", return_value=inbox
        ) as review_inbox:
            response = self.client.get("/api/admin/teacher-order-validations")
        return response, review_inbox

    def test_platform_operator_sees_the_review_inbox(self):
        response, review_inbox = self._open_inbox(OPERATOR)

        self.assertEqual(response.status_code, 200, response.get_json())
        review_inbox.assert_called_once()

    def test_other_centers_get_403(self):
        for center in DENIED_CENTERS:
            with self.subTest(username=center["username"], active=center["is_active"]):
                response, review_inbox = self._open_inbox(center)

                self.assertEqual(response.status_code, 403, response.get_json())
                review_inbox.assert_not_called()


class TestClockAccessTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="platform-operator-clock")
        app.register_blueprint(create_hr_blueprint())
        self.client = app.test_client()

    def _get_clock(self, center):
        _login(self.client, center)
        with patch("routes.hr_routes.HR_ENABLED", True), patch.object(
            admin_access_service, "postgres_enabled", return_value=True
        ), patch.object(
            admin_access_service, "get_training_center_by_id", return_value=center
        ), patch("services.time_service.get_center_test_time", return_value=None):
            return self.client.get("/api/hr/test-clock")

    def test_platform_operator_sees_the_test_clock(self):
        response = self._get_clock(OPERATOR)

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertFalse(response.get_json()["active"])

    def test_other_centers_get_403(self):
        for center in DENIED_CENTERS:
            with self.subTest(username=center["username"], active=center["is_active"]):
                response = self._get_clock(center)

                self.assertEqual(response.status_code, 403, response.get_json())
                self.assertEqual(response.get_json()["code"], "TEST_CLOCK_FORBIDDEN")


class ReviewExemptionTest(unittest.TestCase):
    def _context(self, center):
        with patch.object(
            billing_service, "get_center_billing_account", return_value=center
        ), patch.object(billing_service, "get_product_catalog", return_value={}):
            return billing_service.billing_context(center["id"])

    def test_platform_operator_orders_without_review(self):
        self.assertFalse(self._context(OPERATOR)["review_required"])

    def test_historical_email_without_role_still_needs_review(self):
        for center in (NORMAL_CENTER, HISTORICAL_EMAIL_WITHOUT_ROLE):
            with self.subTest(username=center["username"]):
                self.assertTrue(self._context(center)["review_required"])


class SessionPermissionTest(unittest.TestCase):
    def _permissions(self, center):
        with patch.object(
            admin_access_service, "postgres_enabled", return_value=True
        ), patch.object(
            admin_access_service, "get_training_center_by_id", return_value=center
        ):
            return admin_access_service.get_admin_permissions("training_center", center["id"])

    def test_session_exposes_the_operator_role(self):
        self.assertTrue(self._permissions(OPERATOR)["platform_operator"])
        for center in DENIED_CENTERS:
            with self.subTest(username=center["username"], active=center["is_active"]):
                self.assertFalse(self._permissions(center)["platform_operator"])

    def test_internal_admin_session_is_not_a_platform_operator(self):
        permissions = admin_access_service.get_admin_permissions("superadmin", None)

        self.assertFalse(permissions["platform_operator"])


class _KeepOpenConnection(sqlite3.Connection):
    def close(self):
        pass


class AuthorizedTestClocksTest(unittest.TestCase):
    def test_only_active_operator_clocks_drive_the_scheduler(self):
        conn = sqlite3.connect(":memory:", factory=_KeepOpenConnection)
        conn.execute(
            """
            CREATE TABLE training_center_accounts (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                is_active INTEGER NOT NULL,
                is_platform_operator INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.executemany(
            "INSERT INTO training_center_accounts VALUES (?, ?, ?, ?)",
            [
                (c["id"], c["username"], int(c["is_active"]), int(c["is_platform_operator"]))
                for c in (OPERATOR, *DENIED_CENTERS)
            ],
        )
        test_clock_repository._ensure_sqlite_table(conn.cursor())
        conn.executemany(
            "INSERT INTO center_test_clocks VALUES (?, ?, ?, ?)",
            [
                (c["id"], "2026-01-05T09:00:00", "2026-09-29T09:00:00", "2026-09-29T09:00:00")
                for c in (OPERATOR, *DENIED_CENTERS)
            ],
        )

        with patch.object(
            test_clock_repository, "postgres_enabled", return_value=False
        ), patch.object(test_clock_repository, "get_db_connection", return_value=conn):
            clocks = test_clock_repository.list_authorized_active_test_clocks()

        self.assertEqual([clock["center_account_id"] for clock in clocks], [OPERATOR["id"]])


if __name__ == "__main__":
    unittest.main()
