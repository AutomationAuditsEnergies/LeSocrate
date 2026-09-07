import sys
import types
import unittest
from unittest.mock import patch

from services.pipeline_queue.contracts import WorkItem, WorkResult
from services.pipeline_queue.handlers import handle_pipeline_work_item, mark_pipeline_dead_letter


def _item():
    return WorkItem(
        id="11111111-1111-1111-1111-111111111111",
        pipeline_job_id=None,
        folder_id=None,
        resource_key="ai-teacher-order:7",
        run_id="teacher-order-public-id",
        task_type="ai_teacher_fulfillment",
        scope_key="fulfillment",
        dedupe_key="ai-teacher-order:7:fulfill",
        payload={"order_id": 7},
        status="running",
        priority=20,
        attempt_count=1,
        max_attempts=5,
        available_at=None,
        lease_owner="worker",
        lease_token="22222222-2222-2222-2222-222222222222",
        lease_version=1,
        lease_expires_at=None,
        last_error=None,
        result={},
        created_at=None,
        updated_at=None,
    )


class TeacherOrderQueueHandlerTest(unittest.TestCase):
    def test_dispatches_fulfillment_without_pipeline_job_id(self):
        calls = []
        module = types.ModuleType("services.teacher_order_fulfillment_service")
        module.fulfill_teacher_order = lambda item, lease: (
            calls.append((item, lease)) or WorkResult(result={"status": "fulfilled"})
        )
        module.mark_teacher_order_dead_letter = lambda item, error: calls.append((item, error))
        lease = object()
        with patch.dict(sys.modules, {"services.teacher_order_fulfillment_service": module}):
            result = handle_pipeline_work_item(_item(), lease)
        self.assertEqual(result.result["status"], "fulfilled")
        self.assertEqual(calls, [(_item(), lease)])

    def test_dead_letter_is_persisted_on_the_order(self):
        calls = []
        module = types.ModuleType("services.teacher_order_fulfillment_service")
        module.fulfill_teacher_order = lambda item, lease: WorkResult()
        module.mark_teacher_order_dead_letter = lambda item, error: calls.append((item, error))
        with patch.dict(sys.modules, {"services.teacher_order_fulfillment_service": module}):
            mark_pipeline_dead_letter(_item(), "blob unavailable")
        self.assertEqual(calls, [(_item(), "blob unavailable")])


if __name__ == "__main__":
    unittest.main()
