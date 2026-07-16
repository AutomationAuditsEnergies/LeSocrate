import unittest
from unittest.mock import patch

from services.pipeline_queue.contracts import WorkItem, WorkResult
from services import teacher_order_fulfillment_service as service


class _Lease:
    def __init__(self):
        self.checkpoints = 0

    def checkpoint(self):
        self.checkpoints += 1


def _work_item():
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


class TeacherOrderAssetReuseTest(unittest.TestCase):
    def test_reuse_binds_to_shared_manifest_without_copying_blobs(self):
        order = {
            "id": 7,
            "public_id": "order-public-id",
            "center_account_id": 42,
            "operation_type": "reuse_teacher",
            "payment_status": "paid",
            "fulfillment_status": "pending",
            "source_module_id": 8,
            "training_title": "Employé commercial",
            "request_payload_json": {
                "name": "Maya · Promo septembre",
                "teacher_name": "Maya",
                "teacher_color": "green",
                "module_id": 8,
                "schedule": {
                    "total_training_days": 2,
                    "weekly_course_count": 1,
                    "weekdays": [1],
                    "start_date": "2026-09-01",
                    "start_time": "09:00",
                },
            },
        }
        lease = _Lease()

        with patch.object(service, "claim_order_for_fulfillment", return_value=order), patch.object(
            service, "create_pipeline_platform", return_value={"id": 120}
        ) as create_platform, patch.object(
            service,
            "clone_postgres_course_structure",
            return_value={"source_platform_id": 12, "folder_id_map": {91: 301, 92: 302}},
        ), patch.object(
            service,
            "ensure_module_asset_manifest",
            return_value={"registered": 37},
        ) as ensure_manifest, patch.object(
            service, "set_platform_asset_binding_mode"
        ) as set_binding, patch.object(
            service, "create_course_schedule"
        ) as create_schedule, patch.object(
            service, "set_postgres_platform_status"
        ) as set_status, patch.object(
            service, "update_order_state"
        ) as update_order:
            result = service.fulfill_teacher_order(_work_item(), lease)

        self.assertIsInstance(result, WorkResult)
        self.assertEqual(result.result["asset_binding_mode"], "shared")
        self.assertEqual(result.result["module_asset_count"], 37)
        self.assertEqual(lease.checkpoints, 2)
        create_platform.assert_called_once()
        ensure_manifest.assert_called_once()
        manifest_call = ensure_manifest.call_args.kwargs
        self.assertEqual(manifest_call["module_id"], 8)
        self.assertEqual(manifest_call["center_account_id"], 42)
        self.assertEqual(manifest_call["source_platform_id"], 12)
        self.assertEqual(set(manifest_call["source_folder_ids"]), {91, 92})
        set_binding.assert_called_once_with(120, "shared")
        create_schedule.assert_called_once()
        set_status.assert_called_once_with(120, "ready", 42, scope_to_center=True)
        self.assertEqual(update_order.call_args.kwargs["fulfillment_status"], "fulfilled")

    def test_copy_on_write_prefers_only_the_promotion_override(self):
        resolved = {
            "blob_path": "platform-12/folder-91/playlist/cours_1.mp3",
            "requested_platform_id": 120,
            "requested_folder_id": 301,
            "asset_binding_mode": "copy_on_write",
        }
        with patch(
            "services.teacher_asset_service.resolve_registered_blob_path",
            return_value=resolved,
        ), patch(
            "services.teacher_asset_service.blob_exists",
            return_value=True,
        ) as exists:
            from services.teacher_asset_service import resolve_folder_blob_path

            path = resolve_folder_blob_path(301, "audiostts", "playlist/cours_1.mp3")

        self.assertEqual(path, "platform-120/folder-301/playlist/cours_1.mp3")
        exists.assert_called_once_with(
            "audiostts",
            "platform-120/folder-301/playlist/cours_1.mp3",
        )


if __name__ == "__main__":
    unittest.main()
