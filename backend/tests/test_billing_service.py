import os
import json
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from services import billing_service
from config import FRANCE_TZ


def _project():
    return {
        "operation_type": "new_teacher",
        "creation_request_id": "request_1234567890abcdef",
        "project": {
            "name": "Lina · TP CRCD",
            "teacher_name": "Lina",
            "teacher_color": "violet",
            "new_formation": {
                "tp_name": "TP CRCD",
                "rncp_code": "35304",
                "total_hours": 70,
                "schedule": {
                    "total_training_days": 10,
                    "weekly_course_count": 2,
                    "weekdays": ["lundi", "jeudi"],
                    "start_date": (date.today() + timedelta(days=8)).isoformat(),
                    "start_time": "09:00",
                },
            },
        },
    }


class BillingServiceTest(unittest.TestCase):
    def test_teacher_description_is_trimmed_and_bounded_in_order_payload(self):
        payload = _project()
        payload["project"]["teacher_description"] = f"  {'x' * 700}  "

        _, project, _ = billing_service._normalize_project(payload, 42)

        self.assertEqual(len(project["teacher_description"]), 600)
        self.assertFalse(project["teacher_description"].startswith(" "))

    def test_catalog_applies_margin_to_daily_production_cost(self):
        with patch.dict(os.environ, {"AI_TEACHER_COST_PER_DAY_CENTS": "1500", "STRIPE_SECRET_KEY": "sk_test"}):
            catalog = billing_service.get_product_catalog()
        self.assertEqual(catalog["new_teacher"]["unit_amount_cents"], 3000)
        self.assertEqual(catalog["reuse_teacher"]["unit_amount_cents"], 2250)

    def test_audio_preparation_window_supports_new_settings_and_legacy_fallback(self):
        with patch.dict(os.environ, {
            "SCHEDULED_AUDIO_HORIZON_HOURS": "30",
        }, clear=True):
            self.assertEqual(
                billing_service._scheduled_audio_preparation_window_hours(),
                (30.0, 2.0, 32.0),
            )
        with patch.dict(os.environ, {
            "SCHEDULED_AUDIO_HORIZON_HOURS": "30",
            "SCHEDULED_AUDIO_READY_HOURS_BEFORE": "20",
            "SCHEDULED_AUDIO_BUILD_BUFFER_HOURS": "3",
        }, clear=True):
            self.assertEqual(
                billing_service._scheduled_audio_preparation_window_hours(),
                (20.0, 3.0, 23.0),
            )

    def test_schedule_rejects_mismatched_weekly_cadence_before_payment(self):
        with self.assertRaisesRegex(billing_service.BillingError, "cadence"):
            billing_service._normalize_schedule(
                {
                    "weekly_course_count": 2,
                    "weekdays": ["lundi"],
                    "start_date": (date.today() + timedelta(days=1)).isoformat(),
                    "start_time": "09:00",
                },
                total_training_days=10,
            )

    def test_fixed_09_rejects_order_before_persistence_or_stripe(self):
        payload = _project()
        payload["project"]["new_formation"]["schedule"]["start_time"] = "14:30"
        center = {
            "id": 42,
            "username": "centre@example.com",
            "center_name": "Centre",
            "is_active": True,
            "billing_mode": "stripe_required",
        }

        with patch.dict(os.environ, {"COURSE_START_TIME_POLICY": "fixed_09"}), patch.object(
            billing_service,
            "get_center_billing_account",
            return_value=center,
        ), patch.object(billing_service, "create_order") as create_order, patch.object(
            billing_service,
            "_stripe",
        ) as stripe_client:
            with self.assertRaisesRegex(billing_service.BillingError, "09:00"):
                billing_service.create_teacher_order(42, payload)

        create_order.assert_not_called()
        stripe_client.assert_not_called()

    def test_first_occurrence_inside_audio_horizon_is_rejected_before_stripe(self):
        payload = _project()
        payload["project"]["new_formation"]["schedule"].update({
            "weekly_course_count": 1,
            "weekdays": ["lundi"],
            "start_date": "2026-07-13",
            "start_time": "09:00",
        })
        now = FRANCE_TZ.localize(datetime(2026, 7, 13, 8, 0, 0))
        center = {
            "id": 42,
            "username": "centre@example.com",
            "center_name": "Centre",
            "is_active": True,
            "billing_mode": "stripe_required",
        }

        with patch.dict(os.environ, {
            "COURSE_START_TIME_POLICY": "fixed_09",
            "SCHEDULED_AUDIO_HORIZON_HOURS": "24",
        }, clear=True), patch.object(
            billing_service, "_billing_now", return_value=now
        ), patch.object(
            billing_service, "get_center_billing_account", return_value=center
        ), patch.object(
            billing_service, "create_order"
        ) as create_order, patch.object(
            billing_service, "_stripe"
        ) as stripe_client:
            with self.assertRaisesRegex(billing_service.BillingError, "plus de 26h") as raised:
                billing_service.create_teacher_order(42, payload)

        self.assertIn("H-24", str(raised.exception))
        self.assertIn("2h de marge", str(raised.exception))
        create_order.assert_not_called()
        stripe_client.assert_not_called()

    @patch.object(billing_service, "create_order")
    @patch.object(billing_service, "get_product_catalog")
    @patch.object(billing_service, "get_reusable_module")
    @patch.object(billing_service, "get_center_billing_account")
    def test_reuse_price_rounds_partial_training_day_up(
        self, get_center, get_module, get_catalog, create_order,
    ):
        get_center.return_value = {
            "id": 9,
            "username": "centre@example.com",
            "is_active": True,
            "billing_mode": "exempt",
        }
        get_module.return_value = {
            "id": 4,
            "tp_name": "TP Vente",
            "rncp_code": "RNCP1",
            "total_hours": 10,
            "status": "validated",
            "nb_folders": 2,
            "voice_type": "fish_audio",
        }
        get_catalog.return_value = {
            "reuse_teacher": {
                "pricing_key": "reuse_teacher",
                "unit_amount_cents": 2250,
                "currency": "eur",
                "configured": False,
            }
        }

        def capture(values):
            self.assertEqual(values["catalog_amount_cents"], 4500)
            self.assertEqual(values["request_payload"]["schedule"]["total_training_days"], 2)
            return {
                "id": 14,
                "public_id": uuid4(),
                "request_fingerprint": values["request_fingerprint"],
                "payment_status": "not_required",
                "fulfillment_status": "queued",
            }, True

        create_order.side_effect = capture
        future_date = date.today() + timedelta(days=8)
        future_monday = future_date + timedelta(days=(7 - future_date.weekday()) % 7)
        result = billing_service.create_teacher_order(9, {
            "operation_type": "reuse_teacher",
            "creation_request_id": "request_abcdefghijklmnop",
            "project": {
                "name": "Lina · TP Vente",
                "teacher_name": "Lina",
                "teacher_color": "violet",
                "module_id": 4,
                "schedule": {
                    "weekly_course_count": 1,
                    "weekdays": ["lundi"],
                    "start_date": future_monday.isoformat(),
                    "start_time": "09:00",
                },
            },
        })
        self.assertEqual(result["next_action"], "track")

    @patch.object(billing_service, "_stripe")
    @patch.object(billing_service, "_enqueue_fulfillment")
    @patch.object(billing_service, "create_order")
    @patch.object(billing_service, "get_product_catalog")
    @patch.object(billing_service, "get_center_billing_account")
    def test_exempt_center_skips_stripe_and_queues_once(
        self, get_center, get_catalog, create_order, enqueue, stripe_client,
    ):
        get_center.return_value = {
            "id": 42,
            "username": "  NEWPIPROD@GMAIL.COM  ",
            "center_name": "Le Socrate",
            "is_active": True,
            "billing_mode": "stripe_required",
        }
        get_catalog.return_value = {
            "new_teacher": {
                "pricing_key": "new_teacher",
                "unit_amount_cents": 3000,
                "currency": "eur",
                "configured": False,
            }
        }
        order = {
            "id": 7,
            "public_id": uuid4(),
            "request_fingerprint": "unused",
            "payment_status": "not_required",
            "fulfillment_status": "not_started",
        }

        def capture(values):
            order["request_fingerprint"] = values["request_fingerprint"]
            self.assertEqual(values["authorization_kind"], "center_exemption")
            self.assertEqual(values["charged_amount_cents"], 0)
            return order, True

        create_order.side_effect = capture
        enqueue.return_value = {**order, "fulfillment_status": "queued"}

        result = billing_service.create_teacher_order(42, _project())

        self.assertEqual(result["next_action"], "track")
        enqueue.assert_called_once_with(order)
        stripe_client.assert_not_called()

    @patch.object(billing_service, "attach_checkout_session")
    @patch.object(billing_service, "_stripe")
    @patch.object(billing_service, "create_order")
    @patch.object(billing_service, "get_product_catalog")
    @patch.object(billing_service, "get_center_billing_account")
    def test_stripe_checkout_uses_server_price_not_browser_amount(
        self, get_center, get_catalog, create_order, stripe_client, attach,
    ):
        get_center.return_value = {
            "id": 9,
            "username": "centre@example.com",
            "center_name": "Centre",
            "is_active": True,
            "billing_mode": "stripe_required",
        }
        get_catalog.return_value = {
            "new_teacher": {
                "pricing_key": "new_teacher",
                "label": "Nouveau professeur IA",
                "unit_amount_cents": 3000,
                "currency": "eur",
                "configured": True,
            }
        }
        order = {
            "id": 11,
            "public_id": uuid4(),
            "request_fingerprint": "unused",
            "payment_status": "awaiting_payment",
            "fulfillment_status": "not_started",
            "currency": "eur",
            "stripe_price_id": None,
            "stripe_checkout_session_id": None,
            "checkout_attempt_count": 0,
        }

        def capture(values):
            order["request_fingerprint"] = values["request_fingerprint"]
            self.assertEqual(values["catalog_amount_cents"], 30000)
            return order, True

        create_order.side_effect = capture
        checkout_create = Mock(return_value=SimpleNamespace(
            id="cs_test_1", url="https://checkout.stripe.test/session",
            expires_at=None, payment_intent=None,
        ))
        stripe_client.return_value = SimpleNamespace(
            checkout=SimpleNamespace(Session=SimpleNamespace(create=checkout_create, retrieve=Mock())),
        )
        attach.return_value = order
        payload = _project()
        payload["quoted_amount_cents"] = 1

        with patch.dict(os.environ, {"PLATFORM_1_FRONTEND_URL": "https://formation.test"}):
            result = billing_service.create_teacher_order(9, payload)

        self.assertEqual(result["next_action"], "redirect")
        line_items = checkout_create.call_args.kwargs["line_items"]
        self.assertEqual(line_items[0]["price_data"]["unit_amount"], 3000)
        self.assertEqual(line_items[0]["quantity"], 10)

    @patch.object(billing_service, "create_order")
    @patch.object(billing_service, "get_product_catalog")
    @patch.object(billing_service, "get_center_billing_account")
    def test_idempotency_key_cannot_be_reused_for_another_project(
        self, get_center, get_catalog, create_order,
    ):
        get_center.return_value = {
            "id": 9, "username": "centre@example.com", "is_active": True,
            "billing_mode": "exempt",
        }
        get_catalog.return_value = {
            "new_teacher": {
                "pricing_key": "new_teacher", "unit_amount_cents": 3000,
                "currency": "eur", "configured": False,
            }
        }
        create_order.return_value = ({
            "id": 12,
            "public_id": uuid4(),
            "request_fingerprint": "different",
            "payment_status": "not_required",
            "fulfillment_status": "not_started",
        }, False)

        with self.assertRaises(billing_service.BillingError) as raised:
            billing_service.create_teacher_order(9, _project())
        self.assertEqual(raised.exception.status_code, 409)

    @patch.object(billing_service, "apply_stripe_webhook_event")
    @patch.object(billing_service, "_stripe")
    def test_signed_webhook_uses_verified_event_object(self, stripe_client, apply_event):
        event = {
            "id": "evt_test_1",
            "type": "checkout.session.completed",
            "livemode": False,
            "data": {"object": {"id": "cs_test_1", "payment_status": "paid"}},
        }
        stripe_client.return_value = SimpleNamespace(
            Webhook=SimpleNamespace(construct_event=Mock(return_value=event)),
            error=SimpleNamespace(SignatureVerificationError=ValueError),
        )

        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "whsec_placeholder"}):
            billing_service.process_stripe_webhook(json.dumps(event).encode(), "signed")

        stripe_client.return_value.Webhook.construct_event.assert_called_once()
        apply_event.assert_called_once_with(event)

    @patch.object(billing_service, "record_webhook_failure")
    @patch.object(billing_service, "apply_stripe_webhook_event", side_effect=ValueError("Montant Stripe incohérent"))
    @patch.object(billing_service, "_stripe")
    def test_invalid_verified_event_is_recorded_for_retry(
        self, stripe_client, apply_event, record_failure,
    ):
        event = {
            "id": "evt_test_2",
            "type": "checkout.session.completed",
            "livemode": False,
            "data": {"object": {"id": "cs_test_2", "payment_status": "paid"}},
        }
        stripe_client.return_value = SimpleNamespace(
            Webhook=SimpleNamespace(construct_event=Mock(return_value=event)),
            error=SimpleNamespace(SignatureVerificationError=ValueError),
        )

        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "whsec_placeholder"}):
            with self.assertRaisesRegex(billing_service.BillingError, "Montant") as raised:
                billing_service.process_stripe_webhook(json.dumps(event).encode(), "signed")

        self.assertEqual(raised.exception.status_code, 400)
        record_failure.assert_called_once_with(event, "Montant Stripe incohérent")

    @patch.object(billing_service, "retry_order_fulfillment")
    @patch.object(billing_service, "get_center_order")
    def test_paid_failed_order_can_be_requeued_without_a_second_charge(
        self, get_order, retry_fulfillment,
    ):
        public_id = str(uuid4())
        failed_order = {
            "id": 73,
            "public_id": public_id,
            "payment_status": "paid",
            "fulfillment_status": "failed",
            "charged_amount_cents": 3000,
        }
        get_order.return_value = failed_order
        retry_fulfillment.return_value = {
            **failed_order,
            "fulfillment_status": "queued",
            "status": "fulfillment_queued",
        }

        retried = billing_service.retry_center_order(public_id, 42)

        self.assertEqual(retried["fulfillment_status"], "queued")
        self.assertEqual(retried["charged_amount_cents"], 3000)
        retry_fulfillment.assert_called_once_with(73, 42)

    @patch.object(billing_service, "retry_order_fulfillment")
    @patch.object(billing_service, "get_center_order")
    def test_unpaid_order_cannot_be_retried(self, get_order, retry_fulfillment):
        get_order.return_value = {
            "id": 74,
            "public_id": str(uuid4()),
            "payment_status": "awaiting_payment",
            "fulfillment_status": "failed",
        }

        with self.assertRaises(billing_service.BillingError) as raised:
            billing_service.retry_center_order(str(uuid4()), 42)

        self.assertEqual(raised.exception.status_code, 409)
        retry_fulfillment.assert_not_called()


if __name__ == "__main__":
    unittest.main()
