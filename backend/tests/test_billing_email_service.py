import os
import unittest
from unittest.mock import patch

from services import billing_email_service


class BillingEmailServiceTest(unittest.TestCase):
    @patch.object(billing_email_service, "_send_html", return_value=True)
    def test_review_requests_always_target_the_secretariat_by_default(self, send_html):
        order = {
            "training_title": "TP CRCD",
            "total_hours": 378,
            "catalog_amount_cents": 108000,
            "internal_api_cost_cents": 81000,
            "request_payload_json": {"teacher_name": "Lina"},
        }
        center = {"center_name": "Centre test", "username": "centre@example.test"}

        with patch.dict(os.environ, {}, clear=True):
            delivered = billing_email_service.send_review_request(
                order,
                center,
                "https://formation.test/billing/review/order?token=signed",
            )

        self.assertTrue(delivered)
        self.assertEqual(send_html.call_args.args[0], "secretariat@saleshacking.fr")

    def test_email_day_count_uses_the_schedule_snapshot(self):
        order = {
            "total_hours": 70,
            "request_payload_json": {
                "new_formation": {"schedule": {"selected_dates": ["2026-09-01"] * 54}},
            },
        }

        self.assertEqual(billing_email_service._training_days(order), 54)


if __name__ == "__main__":
    unittest.main()
