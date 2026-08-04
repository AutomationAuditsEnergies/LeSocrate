import unittest
from unittest.mock import patch
from uuid import uuid4

from flask import Flask

from routes import billing_routes


class BillingRetryRoutesTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="billing-retry-test")
        app.register_blueprint(billing_routes.billing_bp)
        self.client = app.test_client()
        self.public_id = uuid4()

    def _login_center(self, center_id=42):
        with self.client.session_transaction() as session:
            session["is_admin"] = True
            session["admin_account_type"] = "training_center"
            session["admin_account_id"] = center_id

    def test_center_can_retry_only_its_paid_failed_order(self):
        self._login_center()
        order = {
            "id": 7,
            "public_id": self.public_id,
            "operation_type": "new_teacher",
            "creation_request_id": "request_1234567890abcdef",
            "training_title": "TP CRCD",
            "rncp_code": "35304",
            "total_hours": 14,
            "catalog_amount_cents": 6000,
            "charged_amount_cents": 6000,
            "currency": "eur",
            "authorization_kind": "stripe",
            "payment_status": "paid",
            "fulfillment_status": "queued",
            "platform_id": None,
            "pipeline_job_id": None,
            "last_error": None,
            "created_at": None,
            "updated_at": None,
            "request_payload_json": {},
        }
        with patch.object(billing_routes, "postgres_enabled", return_value=True), patch.object(
            billing_routes, "retry_center_order", return_value=order
        ) as retry:
            response = self.client.post(f"/api/hr/teacher-orders/{self.public_id}/retry")

        self.assertEqual(response.status_code, 202, response.get_json())
        self.assertEqual(response.get_json()["order"]["fulfillment_status"], "queued")
        retry.assert_called_once_with(str(self.public_id), 42)

    def test_anonymous_retry_is_rejected_before_repository_access(self):
        with patch.object(billing_routes, "retry_center_order") as retry:
            response = self.client.post(f"/api/hr/teacher-orders/{self.public_id}/retry")

        self.assertEqual(response.status_code, 403, response.get_json())
        retry.assert_not_called()

    def test_center_can_observe_an_unhealthy_embedded_worker(self):
        self._login_center()
        with patch.object(
            billing_routes,
            "get_pipeline_worker_health",
            return_value={
                "enabled": True,
                "monitored": True,
                "healthy": False,
                "status": "stale",
                "phase": "working",
                "last_heartbeat_at": "2026-07-16T12:00:00+00:00",
                "heartbeat_age_seconds": 300,
                "current_work_item_id": "work-1",
            },
        ):
            response = self.client.get("/api/hr/system/worker-health")

        self.assertEqual(response.status_code, 503, response.get_json())
        self.assertFalse(response.get_json()["worker"]["healthy"])
        self.assertEqual(response.get_json()["worker"]["status"], "stale")

    def test_center_can_list_only_its_billing_history(self):
        self._login_center()
        orders = [{"id": str(self.public_id), "payment_status": "paid"}]
        with patch.object(billing_routes, "postgres_enabled", return_value=True), patch.object(
            billing_routes, "billing_history", return_value=orders
        ) as history:
            response = self.client.get("/api/hr/billing/history")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["orders"], orders)
        history.assert_called_once_with(42)

    def test_invoice_lookup_is_scoped_to_the_logged_in_center(self):
        self._login_center()
        with patch.object(
            billing_routes,
            "get_center_invoice_link",
            return_value={"url": "https://invoice.test/1", "document_type": "invoice"},
        ) as invoice:
            response = self.client.get(f"/api/hr/billing/orders/{self.public_id}/invoice")

        self.assertEqual(response.status_code, 200, response.get_json())
        invoice.assert_called_once_with(str(self.public_id), 42)


if __name__ == "__main__":
    unittest.main()
