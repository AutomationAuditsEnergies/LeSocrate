import unittest
from unittest.mock import patch
from uuid import uuid4

from flask import Flask

from routes import billing_routes


class BillingMessageRoutesTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="billing-message-test")
        app.register_blueprint(billing_routes.billing_bp)
        self.client = app.test_client()
        self.public_id = uuid4()

    def _login(self, account_type, account_id=None):
        with self.client.session_transaction() as session:
            session["is_admin"] = True
            session["admin_account_type"] = account_type
            if account_id is not None:
                session["admin_account_id"] = account_id

    def test_internal_admin_can_list_every_review_request(self):
        self._login("legacy_admin")
        inbox = {
            "requests": [{"id": str(self.public_id), "review_status": "pending"}],
            "unread_count": 1,
            "pending_count": 1,
            "deepseek_url": "https://deepseek.test",
            "audio_url": "https://audio.test",
        }
        with patch.object(billing_routes, "postgres_enabled", return_value=True), patch.object(
            billing_routes, "admin_review_inbox", return_value=inbox
        ):
            response = self.client.get("/api/admin/teacher-order-validations")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["unread_count"], 1)

    def test_training_center_cannot_open_internal_validation_inbox(self):
        self._login("training_center", 42)
        with patch.object(
            billing_routes, "center_can_review_orders", return_value=False
        ), patch.object(billing_routes, "admin_review_inbox") as inbox:
            response = self.client.get("/api/admin/teacher-order-validations")

        self.assertEqual(response.status_code, 403, response.get_json())
        inbox.assert_not_called()

    def test_privileged_center_can_review_requests_from_other_centers(self):
        self._login("training_center", 42)
        inbox = {
            "requests": [{"id": str(self.public_id), "review_status": "pending"}],
            "unread_count": 1,
            "pending_count": 1,
            "deepseek_url": "https://deepseek.test",
            "audio_url": "https://audio.test",
        }
        with patch.object(
            billing_routes, "center_can_review_orders", return_value=True
        ) as can_review, patch.object(
            billing_routes, "postgres_enabled", return_value=True
        ), patch.object(
            billing_routes, "admin_review_inbox", return_value=inbox
        ) as review_inbox:
            response = self.client.get("/api/admin/teacher-order-validations")

        self.assertEqual(response.status_code, 200, response.get_json())
        can_review.assert_called_once_with(42)
        review_inbox.assert_called_once_with(exclude_center_account_id=42)

    def test_internal_admin_approval_uses_the_authenticated_endpoint(self):
        self._login("legacy_admin")
        with patch.object(billing_routes, "postgres_enabled", return_value=True), patch.object(
            billing_routes,
            "approve_teacher_order_from_admin",
            return_value={"order": {"public_id": self.public_id}, "payment_email_sent": True},
        ) as approve, patch.object(
            billing_routes, "serialize_order", return_value={"id": str(self.public_id)}
        ):
            response = self.client.post(
                f"/api/admin/teacher-order-validations/{self.public_id}/approve"
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()["payment_email_sent"])
        approve.assert_called_once()

    def test_privileged_center_can_approve_a_review_request(self):
        self._login("training_center", 42)
        with patch.object(
            billing_routes, "center_can_review_orders", return_value=True
        ), patch.object(
            billing_routes, "center_can_manage_review", return_value=True
        ), patch.object(
            billing_routes, "postgres_enabled", return_value=True
        ), patch.object(
            billing_routes,
            "approve_teacher_order_from_admin",
            return_value={"order": {"public_id": self.public_id}, "payment_email_sent": True},
        ) as approve, patch.object(
            billing_routes, "serialize_order", return_value={"id": str(self.public_id)}
        ):
            response = self.client.post(
                f"/api/admin/teacher-order-validations/{self.public_id}/approve"
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        approve.assert_called_once()

    def test_privileged_center_cannot_approve_its_own_request(self):
        self._login("training_center", 42)
        with patch.object(
            billing_routes, "center_can_review_orders", return_value=True
        ), patch.object(
            billing_routes, "center_can_manage_review", return_value=False
        ), patch.object(
            billing_routes, "approve_teacher_order_from_admin"
        ) as approve:
            response = self.client.post(
                f"/api/admin/teacher-order-validations/{self.public_id}/approve"
            )

        self.assertEqual(response.status_code, 404, response.get_json())
        approve.assert_not_called()

    def test_center_message_inbox_is_scoped_to_logged_in_center(self):
        self._login("training_center", 42)
        inbox = {"messages": [{"id": str(self.public_id)}], "unread_count": 1}
        with patch.object(billing_routes, "postgres_enabled", return_value=True), patch.object(
            billing_routes, "center_message_inbox", return_value=inbox
        ) as messages:
            response = self.client.get("/api/hr/messages")

        self.assertEqual(response.status_code, 200, response.get_json())
        messages.assert_called_once_with(42)

    def test_center_can_only_mark_its_own_message_seen(self):
        self._login("training_center", 42)
        with patch.object(
            billing_routes,
            "mark_center_message_seen",
            return_value={"id": str(self.public_id), "read": True},
        ) as seen:
            response = self.client.post(f"/api/hr/messages/{self.public_id}/seen")

        self.assertEqual(response.status_code, 200, response.get_json())
        seen.assert_called_once_with(str(self.public_id), 42)


if __name__ == "__main__":
    unittest.main()
