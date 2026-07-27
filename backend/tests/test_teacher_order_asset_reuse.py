import sys
import types
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
    def setUp(self):
        self.storage_patcher = patch.object(service, "ensure_platform_storage")
        self.ensure_storage = self.storage_patcher.start()
        self.addCleanup(self.storage_patcher.stop)

    def test_new_pipeline_order_stays_running_until_auto_pilot_text_is_ready(self):
        order = {
            "id": 7,
            "public_id": "order-public-id",
            "center_account_id": 42,
            "operation_type": "new_teacher",
            "payment_status": "paid",
            "fulfillment_status": "running",
            "training_title": "Employé commercial",
            "total_hours": 14,
            "request_payload_json": {
                "name": "Maya · Employé commercial",
                "new_formation": {
                    "tp_name": "Employé commercial",
                    "rncp_code": "RNCP-TEST",
                    "total_hours": 14,
                },
            },
        }
        routes_package = types.ModuleType("routes")
        routes_package.formation_routes = types.SimpleNamespace(
            _determine_next_ap_step=lambda _job_id: "content"
        )

        with patch.dict(sys.modules, {"routes": routes_package}), patch.object(
            service, "claim_order_for_fulfillment", return_value=order
        ), patch.object(
            service, "resolve_compatible_canonical_teacher", return_value=None
        ), patch.object(
            service,
            "create_postgres_pipeline_aggregate",
            return_value={"platform": {"id": 120}, "job_id": 420},
        ), patch.object(service, "update_job"), patch.object(
            service, "update_order_state"
        ) as update_order:
            result = service.fulfill_teacher_order(_work_item(), _Lease())

        self.assertEqual(result.result["status"], "preparing")
        self.assertEqual(result.next_items[0].payload["teacher_order_id"], 7)
        self.ensure_storage.assert_called_once_with({"id": 120})
        self.assertEqual(update_order.call_args.kwargs["status"], "fulfilling")
        self.assertEqual(update_order.call_args.kwargs["fulfillment_status"], "running")

    def test_identical_new_teacher_reuses_canonical_assets_without_new_pipeline(self):
        order = {
            "id": 7,
            "public_id": "order-public-id",
            "center_account_id": 42,
            "operation_type": "new_teacher",
            "payment_status": "paid",
            "fulfillment_status": "pending",
            "training_title": "Employé commercial",
            "total_hours": 14,
            "request_payload_json": {
                "name": "Maya · Employé commercial",
                "teacher_name": "Maya",
                "teacher_color": "green",
                "new_formation": {
                    "tp_name": "Employé commercial",
                    "rncp_code": "RNCP-TEST",
                    "total_hours": 14,
                    "schedule": {
                        "total_training_days": 2,
                        "weekly_course_count": 1,
                        "weekdays": [1],
                        "start_date": "2026-09-01",
                        "start_time": "09:00",
                    },
                },
            },
        }
        lease = _Lease()

        with patch.object(service, "claim_order_for_fulfillment", return_value=order), patch.object(
            service,
            "resolve_compatible_canonical_teacher",
            return_value={"module_id": 44, "asset_count": 38},
        ) as resolve, patch.object(
            service,
            "create_pipeline_platform",
            return_value={"id": 120, "source_module_id": 44},
        ) as create_platform, patch.object(
            service, "clone_canonical_module_course_structure"
        ) as clone, patch.object(
            service, "create_postgres_pipeline_aggregate"
        ) as create_aggregate, patch.object(
            service, "ensure_module_asset_manifest"
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

        self.assertTrue(result.result["canonical_reuse"])
        self.assertEqual(result.result["module_asset_count"], 38)
        self.assertEqual(lease.checkpoints, 2)
        resolve.assert_called_once_with(
            rncp_code="RNCP-TEST",
            tp_name="Employé commercial",
            total_hours=14,
            nb_days=2,
            voice_type="fish_audio",
        )
        create_platform.assert_called_once()
        self.ensure_storage.assert_called_once_with(
            {"id": 120, "source_module_id": 44}
        )
        clone.assert_called_once_with(
            target_platform_id=120,
            module_id=44,
            target_center_account_id=42,
        )
        create_aggregate.assert_not_called()
        ensure_manifest.assert_not_called()
        set_binding.assert_called_once_with(120, "shared")
        create_schedule.assert_called_once()
        set_status.assert_called_once_with(120, "ready", 42, scope_to_center=True)
        self.assertEqual(update_order.call_args.kwargs["fulfillment_status"], "fulfilled")

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
            service,
            "get_reusable_module",
            return_value={"id": 8, "schedule_schema_version": 1},
        ), patch.object(
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
        self.ensure_storage.assert_called_once_with({"id": 120})
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

    def test_transient_fulfillment_error_stays_queued_until_dead_letter(self):
        order = {
            "id": 7,
            "public_id": "order-public-id",
            "center_account_id": 42,
            "operation_type": "new_teacher",
            "payment_status": "paid",
            "fulfillment_status": "queued",
            "training_title": "Employé commercial",
            "total_hours": 14,
            "request_payload_json": {
                "name": "Maya · Employé commercial",
                "teacher_name": "Maya",
                "teacher_color": "green",
                "new_formation": {
                    "tp_name": "Employé commercial",
                    "rncp_code": "RNCP-TEST",
                    "total_hours": 14,
                    "schedule": {"total_training_days": 2},
                },
            },
        }

        with patch.object(service, "claim_order_for_fulfillment", return_value=order), patch.object(
            service,
            "create_postgres_pipeline_aggregate",
            side_effect=RuntimeError("temporary database outage"),
        ), patch.object(service, "update_order_state") as update_order:
            with self.assertRaisesRegex(RuntimeError, "temporary"):
                service.fulfill_teacher_order(_work_item(), _Lease())

        self.assertEqual(update_order.call_args.kwargs["status"], "fulfillment_queued")
        self.assertEqual(update_order.call_args.kwargs["fulfillment_status"], "queued")

        with patch.object(service, "update_order_state") as mark_failed:
            service.mark_teacher_order_dead_letter(_work_item(), "attempts exhausted")
        self.assertEqual(mark_failed.call_args.kwargs["status"], "fulfillment_failed")
        self.assertEqual(mark_failed.call_args.kwargs["fulfillment_status"], "failed")

    def test_storage_failure_prevents_pipeline_enqueue_and_false_fulfilled_state(self):
        order = {
            "id": 7,
            "public_id": "order-public-id",
            "center_account_id": 42,
            "operation_type": "new_teacher",
            "payment_status": "paid",
            "fulfillment_status": "queued",
            "training_title": "Employé commercial",
            "total_hours": 14,
            "request_payload_json": {
                "name": "Maya · Employé commercial",
                "new_formation": {
                    "tp_name": "Employé commercial",
                    "rncp_code": "RNCP-TEST",
                    "total_hours": 14,
                },
            },
        }
        platform = {"id": 120, "audio_container": "formationaudio-p120"}
        self.ensure_storage.side_effect = RuntimeError("azure unavailable")

        with patch.object(
            service, "claim_order_for_fulfillment", return_value=order
        ), patch.object(
            service, "resolve_compatible_canonical_teacher", return_value=None
        ), patch.object(
            service,
            "create_postgres_pipeline_aggregate",
            return_value={"platform": platform, "job_id": 420},
        ), patch.object(service, "update_job") as update_job, patch.object(
            service, "update_order_state"
        ) as update_order:
            with self.assertRaisesRegex(RuntimeError, "azure unavailable"):
                service.fulfill_teacher_order(_work_item(), _Lease())

        self.ensure_storage.assert_called_once_with(platform)
        update_job.assert_not_called()
        self.assertEqual(update_order.call_count, 1)
        self.assertEqual(update_order.call_args.kwargs["status"], "fulfillment_queued")
        self.assertEqual(update_order.call_args.kwargs["fulfillment_status"], "queued")


if __name__ == "__main__":
    unittest.main()
