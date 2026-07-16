import unittest
from unittest.mock import Mock, patch
from uuid import UUID

from repositories.billing_repository import _enqueue_fulfillment_in_transaction


class BillingRepositoryRetryTest(unittest.TestCase):
    def test_failed_order_gets_a_fresh_work_item_without_recycling_dead_letter(self):
        order = {
            "id": 73,
            "public_id": "00000000-0000-0000-0000-000000000073",
            "payment_status": "paid",
            "fulfillment_status": "failed",
        }
        queued_order = {**order, "fulfillment_status": "queued"}
        cursor = Mock()
        cursor.fetchone.side_effect = [None, {"id": "work-new"}, queued_order]

        with patch(
            "repositories.billing_repository.uuid.uuid4",
            side_effect=[
                UUID("00000000-0000-0000-0000-000000000001"),
                UUID("00000000-0000-0000-0000-000000000002"),
            ],
        ):
            result = _enqueue_fulfillment_in_transaction(cursor, order)

        self.assertEqual(result["fulfillment_status"], "queued")
        self.assertEqual(cursor.execute.call_count, 3)
        insert_sql, insert_params = cursor.execute.call_args_list[1].args
        self.assertIn("INSERT INTO pipeline_work_items", insert_sql)
        self.assertEqual(insert_params[0], "00000000-0000-0000-0000-000000000002")
        self.assertEqual(
            insert_params[3],
            "ai-teacher-order:73:fulfill:retry:00000000-0000-0000-0000-000000000001",
        )
        self.assertNotIn("UPDATE pipeline_work_items", "\n".join(
            call.args[0] for call in cursor.execute.call_args_list
        ))

    def test_retry_reattaches_an_existing_active_work_item(self):
        order = {
            "id": 74,
            "public_id": "00000000-0000-0000-0000-000000000074",
            "payment_status": "paid",
            "fulfillment_status": "failed",
        }
        cursor = Mock()
        cursor.fetchone.side_effect = [
            {"id": "work-existing", "status": "retry_scheduled"},
            {**order, "fulfillment_status": "queued", "fulfillment_work_item_id": "work-existing"},
        ]

        result = _enqueue_fulfillment_in_transaction(cursor, order)

        self.assertEqual(result["fulfillment_work_item_id"], "work-existing")
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertFalse(any(
            "INSERT INTO pipeline_work_items" in call.args[0]
            for call in cursor.execute.call_args_list
        ))


if __name__ == "__main__":
    unittest.main()
