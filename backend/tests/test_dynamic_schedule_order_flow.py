import unittest
import sys
import types
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from config import FRANCE_TZ
from repositories import billing_repository
from services import billing_service
from services import course_schedule_service
from services import teacher_order_fulfillment_service
from repositories import course_schedule_repository
from services.dynamic_day_schedule_service import compile_module_schedule


def _valid_blocks(start_minute=9 * 60):
    durations = (
        ("course", None, 60),
        ("qa", None, 10),
        ("pause", "short", 15),
        ("course", None, 60),
        ("qa", None, 10),
        ("pause", "lunch", 60),
        ("course", None, 60),
        ("qa", None, 10),
        ("pause", "short", 15),
        ("course", None, 60),
        ("qa", None, 10),
    )
    blocks = []
    cursor = start_minute
    for index, (block_type, pause_kind, duration) in enumerate(
        durations,
        start=1,
    ):
        blocks.append(
            {
                "block_key": f"draft-{index}",
                "position": index,
                "block_type": block_type,
                "pause_kind": pause_kind,
                "start_minute": cursor,
                "duration_minutes": duration,
            }
        )
        cursor += duration
    return blocks


def _new_v2_payload(dates):
    template_hash = "a" * 64
    return {
        "operation_type": "new_teacher",
        "creation_request_id": "request_v2_1234567890abcd",
        "project": {
            "name": "Module dynamique",
            "teacher_name": "Lina",
            "teacher_color": "blue",
            "new_formation": {
                "tp_name": "TP CRCD",
                "rncp_code": "RNCP-TEST",
                # Deliberately wrong: V2 must not derive anything from it.
                "total_hours": 999,
                "schedule": {
                    "schedule_schema_version": 2,
                    "selected_dates": dates,
                    "template_assignments": {
                        date_value: "11" for date_value in dates
                    },
                    "template_hashes": {"11": template_hash},
                },
            },
        },
    }


def _new_v2_custom_payload(date_value):
    payload = _new_v2_payload([date_value])
    schedule = payload["project"]["new_formation"]["schedule"]
    schedule["template_assignments"] = {}
    schedule["template_hashes"] = {}
    schedule["custom_days"] = {
        date_value: {"blocks": _valid_blocks()},
    }
    return payload


class DynamicBillingScheduleTest(unittest.TestCase):
    def test_new_v2_uses_checked_dates_and_server_template_as_authority(self):
        now = FRANCE_TZ.localize(datetime(2026, 7, 26, 8, 0))
        dates = ["2026-08-02", "2026-07-30"]
        with patch.object(
            billing_service,
            "_billing_now",
            return_value=now,
        ), patch.object(
            billing_service,
            "get_template",
            return_value={
                "id": 11,
                "name": "Journée standard",
                "blocks_hash": "a" * 64,
                "blocks": _valid_blocks(),
            },
        ):
            _, project, details = billing_service._normalize_project(
                _new_v2_payload(dates),
                42,
            )

        formation = project["new_formation"]
        self.assertEqual(
            formation["schedule"]["selected_dates"],
            ["2026-07-30", "2026-08-02"],
        )
        self.assertEqual(formation["schedule"]["day_count"], 2)
        self.assertEqual(details["training_days"], 2)
        self.assertEqual(formation["total_hours"], 14)
        self.assertEqual(
            formation["schedule"]["days"][0]["blocks"][0]["start_minute"],
            9 * 60,
        )

    def test_new_v2_requires_a_first_date_at_j_plus_3(self):
        now = FRANCE_TZ.localize(datetime(2026, 7, 26, 12, 0))
        with patch.object(
            billing_service,
            "_billing_now",
            return_value=now,
        ), patch.object(
            billing_service,
            "get_template",
            return_value={
                "id": 11,
                "name": "Journée standard",
                "blocks_hash": "a" * 64,
                "blocks": _valid_blocks(),
            },
        ):
            with self.assertRaisesRegex(
                billing_service.BillingError,
                r"J\+3",
            ):
                billing_service._normalize_project(
                    _new_v2_payload(["2026-07-28"]),
                    42,
                )

    def test_new_v2_compiles_a_custom_day_without_creating_a_template(self):
        now = FRANCE_TZ.localize(datetime(2026, 7, 26, 8, 0))
        with patch.object(
            billing_service,
            "_billing_now",
            return_value=now,
        ), patch.object(
            billing_service,
            "get_template",
        ) as get_template:
            _, project, details = billing_service._normalize_project(
                _new_v2_custom_payload("2026-07-30"),
                42,
            )

        schedule = project["new_formation"]["schedule"]
        self.assertEqual(details["training_days"], 1)
        self.assertEqual(schedule["template_assignments"], {})
        self.assertEqual(len(schedule["custom_days"]["2026-07-30"]["blocks"]), 11)
        self.assertEqual(schedule["days"][0]["template_name"], "Journée personnalisée")
        get_template.assert_not_called()

    def test_new_v2_rejects_a_template_changed_after_confirmation(self):
        payload = _new_v2_payload(["2030-08-02"])
        with patch.object(
            billing_service,
            "get_template",
            return_value={
                "id": 11,
                "name": "Journée standard modifiée",
                "blocks_hash": "b" * 64,
                "blocks": _valid_blocks(),
            },
        ):
            with self.assertRaisesRegex(
                billing_service.BillingError,
                "a changé",
            ):
                billing_service._normalize_project(payload, 42)

    def test_reuse_v2_requires_exact_module_day_count(self):
        module = {
            "id": 7,
            "tp_name": "TP CRCD",
            "rncp_code": "RNCP-TEST",
            "total_hours": 112,
            "status": "validated",
            "nb_folders": 16,
            "nb_days": 16,
            "module_day_count": 16,
            "voice_type": "fish_audio",
            "schedule_schema_version": 2,
            "reusable_at": datetime.now(FRANCE_TZ) - timedelta(days=1),
        }
        payload = {
            "operation_type": "reuse_teacher",
            "creation_request_id": "request_reuse_1234567890",
            "project": {
                "name": "Promo suivante",
                "teacher_name": "Lina",
                "teacher_color": "blue",
                "module_id": 7,
                "schedule": {
                    "schedule_schema_version": 2,
                    "selected_dates": [
                        f"2030-09-{day:02d}" for day in range(1, 16)
                    ],
                },
            },
        }
        with patch.object(
            billing_service,
            "get_reusable_module",
            return_value=module,
        ):
            with self.assertRaisesRegex(
                billing_service.BillingError,
                "exactement 16",
            ):
                billing_service._normalize_project(payload, 42)

    def test_legacy_module_cannot_be_reused_through_v2_calendar_contract(self):
        module = {
            "id": 7,
            "tp_name": "TP historique",
            "rncp_code": "RNCP-OLD",
            "total_hours": 14,
            "status": "validated",
            "nb_folders": 2,
            "voice_type": "fish_audio",
            "schedule_schema_version": 1,
        }
        payload = {
            "operation_type": "reuse_teacher",
            "creation_request_id": "request_legacy_123456789",
            "project": {
                "name": "Promo suivante",
                "teacher_name": "Lina",
                "teacher_color": "blue",
                "module_id": 7,
                "schedule": {
                    "schedule_schema_version": 2,
                    "selected_dates": ["2030-09-03", "2030-09-06"],
                },
            },
        }
        with patch.object(
            billing_service,
            "get_reusable_module",
            return_value=module,
        ):
            with self.assertRaisesRegex(
                billing_service.BillingError,
                "historique",
            ):
                billing_service._normalize_project(payload, 42)

    def test_durable_v2_module_cannot_be_reused_through_v1_calendar_contract(self):
        module = {
            "id": 7,
            "tp_name": "TP durable",
            "rncp_code": "RNCP-V2",
            "total_hours": 14,
            "status": "validated",
            "nb_folders": 2,
            "nb_days": 2,
            "module_day_count": 2,
            "voice_type": "fish_audio",
            "schedule_schema_version": 2,
            "reusable_at": datetime.now(FRANCE_TZ) - timedelta(days=1),
        }
        payload = {
            "operation_type": "reuse_teacher",
            "creation_request_id": "request_durable_123456789",
            "project": {
                "name": "Promo suivante",
                "teacher_name": "Lina",
                "teacher_color": "blue",
                "module_id": 7,
                "schedule": {
                    "schedule_schema_version": 1,
                    "weekly_course_count": 1,
                    "weekdays": ["lundi"],
                    "start_date": "2030-09-02",
                    "start_time": "09:00",
                },
            },
        }
        with patch.object(
            billing_service,
            "get_reusable_module",
            return_value=module,
        ):
            with self.assertRaisesRegex(
                billing_service.BillingError,
                "durable.*V2",
            ):
                billing_service._normalize_project(payload, 42)

    def test_reuse_order_rejects_a_module_hidden_by_end_or_manifest_guards(self):
        payload = {
            "operation_type": "reuse_teacher",
            "creation_request_id": "request_ineligible_123456",
            "project": {
                "name": "Promo suivante",
                "teacher_name": "Lina",
                "teacher_color": "blue",
                "module_id": 7,
                "schedule": {
                    "schedule_schema_version": 2,
                    "selected_dates": ["2030-09-03"],
                },
            },
        }
        with patch.object(
            billing_service,
            "get_reusable_module",
            return_value=None,
        ):
            with self.assertRaisesRegex(
                billing_service.BillingError,
                "n’est pas réutilisable",
            ):
                billing_service._normalize_project(payload, 42)


class ReusableModuleRepositoryGuardTest(unittest.TestCase):
    def _repository_row(self):
        return {
            "id": 7,
            "status": "validated",
            "immutable": True,
            "reusable_at": datetime.now(FRANCE_TZ) - timedelta(days=1),
            "schedule_schema_version": 2,
        }

    def test_lookup_requires_module_end_and_a_complete_audio_manifest(self):
        connection = MagicMock()
        cursor = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchone.return_value = self._repository_row()

        with patch.object(
            billing_repository,
            "get_postgres_connection",
            return_value=connection,
        ), patch.object(
            billing_repository,
            "get_module_audio_manifest_readiness",
            return_value={"ready": False},
        ) as readiness:
            module = billing_repository.get_reusable_module(7, 42)

        self.assertIsNone(module)
        readiness.assert_called_once_with(7)
        sql = cursor.execute.call_args.args[0]
        self.assertIn("m.status = 'validated'", sql)
        self.assertIn("m.immutable = TRUE", sql)
        self.assertIn("m.reusable_at <= NOW()", sql)
        self.assertIn("m.archived_at IS NULL", sql)
        self.assertIn("m.voice_type IS DISTINCT FROM 'mock'", sql)
        self.assertIn("EXISTS", sql)

    def test_lookup_returns_only_a_module_with_a_ready_manifest(self):
        connection = MagicMock()
        cursor = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        expected = self._repository_row()
        cursor.fetchone.return_value = expected

        with patch.object(
            billing_repository,
            "get_postgres_connection",
            return_value=connection,
        ), patch.object(
            billing_repository,
            "get_module_audio_manifest_readiness",
            return_value={"ready": True},
        ):
            module = billing_repository.get_reusable_module(7, 42)

        self.assertEqual(module, expected)


class DynamicCourseScheduleTest(unittest.TestCase):
    def test_explicit_sessions_keep_dates_order_and_module_day_binding(self):
        captured = {}

        def replace(**kwargs):
            captured.update(kwargs)
            return {"inserted_sessions": len(kwargs["sessions"])}

        days = [
            {
                "day_index": 1,
                "date": "2030-09-03",
                "module_day_id": 301,
                "blocks": _valid_blocks(8 * 60 + 7),
            },
            {
                "day_index": 2,
                "date": "2030-09-06",
                "module_day_id": 302,
                "blocks": _valid_blocks(10 * 60 + 13),
            },
        ]
        with patch.object(
            course_schedule_service.schedule_repo,
            "schedule_store_is_postgres",
            return_value=True,
        ), patch.object(
            course_schedule_service.schedule_repo,
            "replace_course_schedule",
            side_effect=replace,
        ):
            result = course_schedule_service.create_course_schedule(
                77,
                {
                    "schedule_schema_version": 2,
                    "day_count": 2,
                    "selected_dates": ["2030-09-03", "2030-09-06"],
                    "days": days,
                },
            )

        self.assertEqual(result["total_sessions"], 2)
        self.assertEqual(captured["schedule_schema_version"], 2)
        self.assertEqual(
            [row["local_date"] for row in captured["sessions"]],
            ["2030-09-03", "2030-09-06"],
        )
        self.assertEqual(
            [row["module_day_id"] for row in captured["sessions"]],
            [301, 302],
        )
        self.assertEqual(
            captured["sessions"][0]["scheduled_at"].strftime("%H:%M"),
            "08:07",
        )
        self.assertEqual(
            captured["sessions"][1]["scheduled_at"].strftime("%H:%M"),
            "10:13",
        )

    def test_validated_explicit_calendar_is_idempotent_but_not_replaceable(self):
        connection = sqlite3.connect(":memory:")
        cursor = connection.cursor()
        with patch.object(
            course_schedule_repository,
            "schedule_store_is_postgres",
            return_value=False,
        ):
            course_schedule_service.ensure_course_schedule_tables(cursor)
            now = FRANCE_TZ.localize(datetime(2026, 7, 26, 8, 0))
            base = {
                "platform_id": 77,
                "total_training_days": 1,
                "weekly_course_count": 0,
                "weekdays_json": "[]",
                "start_time": "09:00",
                "timezone_name": "Europe/Paris",
                "sessions": [
                    {
                        "session_index": 1,
                        "scheduled_at": FRANCE_TZ.localize(
                            datetime(2030, 9, 3, 9, 0)
                        ),
                        "local_date": "2030-09-03",
                        "module_day_id": 301,
                        "session_password": "ABC123",
                    }
                ],
                "now": now,
                "sqlite_connection": connection,
                "schedule_schema_version": 2,
            }
            first = course_schedule_repository.replace_course_schedule(**base)
            repeated = course_schedule_repository.replace_course_schedule(**base)
            changed = {
                **base,
                "sessions": [
                    {
                        **base["sessions"][0],
                        "scheduled_at": FRANCE_TZ.localize(
                            datetime(2030, 9, 4, 9, 0)
                        ),
                        "local_date": "2030-09-04",
                    }
                ],
            }
            with self.assertRaisesRegex(ValueError, "immuable"):
                course_schedule_repository.replace_course_schedule(**changed)
        connection.close()

        self.assertEqual(first["inserted_sessions"], 1)
        self.assertTrue(repeated["idempotent"])


class _Lease:
    def checkpoint(self):
        return None


class DynamicOrderFulfillmentTest(unittest.TestCase):
    def test_new_v2_locks_snapshot_and_never_uses_legacy_canonical_match(self):
        snapshot = compile_module_schedule(
            ["2030-09-03", "2030-09-06"],
            {"2030-09-03": 11, "2030-09-06": 11},
            {11: {"name": "Standard", "blocks": _valid_blocks()}},
        )
        snapshot["schedule_schema_version"] = 2
        snapshot["selected_dates"] = ["2030-09-03", "2030-09-06"]
        order = {
            "id": 7,
            "public_id": "order-v2",
            "center_account_id": 42,
            "operation_type": "new_teacher",
            "payment_status": "paid",
            "fulfillment_status": "queued",
            "training_title": "TP CRCD",
            "total_hours": 14,
            "created_at": FRANCE_TZ.localize(datetime(2026, 7, 26, 8, 0)),
            "request_payload_json": {
                "name": "Module dynamique",
                "new_formation": {
                    "tp_name": "TP CRCD",
                    "rncp_code": "RNCP-TEST",
                    "total_hours": 14,
                    "schedule": snapshot,
                },
            },
        }
        item = SimpleNamespace(
            payload={"order_id": 7},
            pipeline_job_id=None,
        )
        routes_package = types.ModuleType("routes")
        routes_package.formation_routes = types.SimpleNamespace(
            _determine_next_ap_step=lambda _job_id: "content"
        )

        with patch.dict(sys.modules, {"routes": routes_package}), patch.object(
            teacher_order_fulfillment_service,
            "claim_order_for_fulfillment",
            return_value=order,
        ), patch.object(
            teacher_order_fulfillment_service,
            "resolve_compatible_canonical_teacher",
        ) as canonical, patch.object(
            teacher_order_fulfillment_service,
            "create_postgres_pipeline_aggregate",
            return_value={"platform": {"id": 120}, "job_id": 420},
        ) as aggregate, patch.object(
            teacher_order_fulfillment_service,
            "lock_pipeline_schedule_snapshot",
        ) as lock_snapshot, patch.object(
            teacher_order_fulfillment_service,
            "ensure_platform_storage",
        ), patch.object(
            teacher_order_fulfillment_service,
            "create_course_schedule",
        ) as create_schedule, patch.object(
            teacher_order_fulfillment_service,
            "update_job",
        ), patch.object(
            teacher_order_fulfillment_service,
            "update_order_state",
        ):
            result = teacher_order_fulfillment_service.fulfill_teacher_order(
                item,
                _Lease(),
            )

        self.assertEqual(result.result["status"], "preparing")
        canonical.assert_not_called()
        self.assertEqual(aggregate.call_args.kwargs["nb_days"], 2)
        lock_snapshot.assert_called_once_with(42, 420, snapshot)
        create_schedule.assert_called_once_with(120, snapshot)

    def test_reuse_v2_rebinds_exact_durable_days_to_new_dates(self):
        order = {
            "id": 7,
            "public_id": "reuse-v2",
            "center_account_id": 42,
            "operation_type": "reuse_teacher",
            "payment_status": "paid",
            "fulfillment_status": "queued",
            "source_module_id": 8,
            "training_title": "TP CRCD",
            "request_payload_json": {
                "name": "Promo suivante",
                "module_id": 8,
                "schedule": {
                    "schedule_schema_version": 2,
                    "selected_dates": ["2030-09-03", "2030-09-06"],
                },
            },
        }
        item = SimpleNamespace(
            payload={"order_id": 7},
            pipeline_job_id=None,
        )
        module_days = [
            {"id": 301, "day_index": 1, "blocks": _valid_blocks()},
            {"id": 302, "day_index": 2, "blocks": _valid_blocks(10 * 60)},
        ]

        with patch.object(
            teacher_order_fulfillment_service,
            "claim_order_for_fulfillment",
            return_value=order,
        ), patch.object(
            teacher_order_fulfillment_service,
            "get_reusable_module",
            return_value={"id": 8, "schedule_schema_version": 2},
        ), patch.object(
            teacher_order_fulfillment_service,
            "_fulfillment_now",
            return_value=FRANCE_TZ.localize(datetime(2030, 9, 2, 23, 0)),
        ), patch.object(
            teacher_order_fulfillment_service,
            "create_pipeline_platform",
            return_value={"id": 120},
        ), patch.object(
            teacher_order_fulfillment_service,
            "ensure_platform_storage",
        ), patch.object(
            teacher_order_fulfillment_service,
            "clone_postgres_course_structure",
            return_value={
                "source_platform_id": 12,
                "folder_id_map": {91: 401, 92: 402},
            },
        ), patch.object(
            teacher_order_fulfillment_service,
            "ensure_module_asset_manifest",
            return_value={"registered": 38},
        ), patch.object(
            teacher_order_fulfillment_service,
            "set_platform_asset_binding_mode",
        ), patch.object(
            teacher_order_fulfillment_service,
            "list_module_days",
            return_value=module_days,
        ), patch.object(
            teacher_order_fulfillment_service,
            "create_course_schedule",
        ) as create_schedule, patch.object(
            teacher_order_fulfillment_service,
            "list_course_folder_ids_for_platform",
            return_value=[401, 402],
        ), patch.object(
            teacher_order_fulfillment_service,
            "bind_module_days_to_platform",
        ) as bind_days, patch.object(
            teacher_order_fulfillment_service,
            "set_postgres_platform_status",
        ), patch.object(
            teacher_order_fulfillment_service,
            "update_order_state",
        ):
            result = teacher_order_fulfillment_service.fulfill_teacher_order(
                item,
                _Lease(),
            )

        self.assertEqual(result.result["status"], "fulfilled")
        explicit_schedule = create_schedule.call_args.args[1]
        self.assertEqual(
            [day["module_day_id"] for day in explicit_schedule["days"]],
            [301, 302],
        )
        self.assertEqual(
            [day["date"] for day in explicit_schedule["days"]],
            ["2030-09-03", "2030-09-06"],
        )
        bind_days.assert_called_once_with(42, 8, 120, [401, 402])

    def test_new_v2_revalidates_48_hours_from_fulfillment_time(self):
        snapshot = compile_module_schedule(
            ["2026-07-28"],
            {"2026-07-28": 11},
            {11: {"name": "Standard", "blocks": _valid_blocks()}},
        )
        snapshot["schedule_schema_version"] = 2
        snapshot["selected_dates"] = ["2026-07-28"]
        order = {
            "id": 7,
            "public_id": "order-v2-late",
            "center_account_id": 42,
            "operation_type": "new_teacher",
            "payment_status": "paid",
            "fulfillment_status": "queued",
            "training_title": "TP CRCD",
            "total_hours": 7,
            # The order itself was created early enough, but it was only
            # authorized and fulfilled after the 48-hour deadline.
            "created_at": FRANCE_TZ.localize(datetime(2026, 7, 24, 8, 0)),
            "authorized_at": FRANCE_TZ.localize(datetime(2026, 7, 26, 10, 0)),
            "request_payload_json": {
                "name": "Module dynamique",
                "new_formation": {
                    "tp_name": "TP CRCD",
                    "rncp_code": "RNCP-TEST",
                    "total_hours": 7,
                    "schedule": snapshot,
                },
            },
        }
        item = SimpleNamespace(payload={"order_id": 7}, pipeline_job_id=None)

        with patch.object(
            teacher_order_fulfillment_service,
            "claim_order_for_fulfillment",
            return_value=order,
        ), patch.object(
            teacher_order_fulfillment_service,
            "_fulfillment_now",
            return_value=FRANCE_TZ.localize(datetime(2026, 7, 26, 8, 0)),
        ), patch.object(
            teacher_order_fulfillment_service,
            "create_postgres_pipeline_aggregate",
        ) as aggregate:
            with self.assertRaisesRegex(
                teacher_order_fulfillment_service.PermanentWorkError,
                r"J\+3",
            ):
                teacher_order_fulfillment_service.fulfill_teacher_order(
                    item,
                    _Lease(),
                )

        aggregate.assert_not_called()

    def test_new_module_validation_time_never_precedes_the_worker_clock(self):
        worker_time = FRANCE_TZ.localize(datetime(2026, 7, 26, 10, 0))
        with patch.object(
            teacher_order_fulfillment_service,
            "_fulfillment_now",
            return_value=worker_time,
        ):
            validation_at = (
                teacher_order_fulfillment_service._new_module_validation_at(
                    {
                        "authorized_at": FRANCE_TZ.localize(
                            datetime(2026, 7, 26, 8, 0)
                        )
                    }
                )
            )

        self.assertEqual(validation_at, worker_time)

    def test_reuse_worker_rejects_every_v1_v2_schema_mismatch_before_creation(self):
        cases = (
            (
                2,
                {
                    "schedule_schema_version": 1,
                    "total_training_days": 2,
                    "weekly_course_count": 1,
                    "weekdays": ["lundi"],
                    "start_date": "2030-09-02",
                    "start_time": "09:00",
                },
            ),
            (
                1,
                {
                    "schedule_schema_version": 2,
                    "selected_dates": ["2030-09-03", "2030-09-06"],
                    "day_count": 2,
                },
            ),
        )
        item = SimpleNamespace(payload={"order_id": 7}, pipeline_job_id=None)

        for module_schema_version, schedule in cases:
            with self.subTest(
                module_schema_version=module_schema_version,
                payload_schema_version=schedule["schedule_schema_version"],
            ):
                order = {
                    "id": 7,
                    "public_id": "reuse-mismatch",
                    "center_account_id": 42,
                    "operation_type": "reuse_teacher",
                    "payment_status": "paid",
                    "fulfillment_status": "queued",
                    "source_module_id": 8,
                    "training_title": "TP CRCD",
                    "request_payload_json": {
                        "name": "Promo suivante",
                        "module_id": 8,
                        "schedule": schedule,
                    },
                }
                with patch.object(
                    teacher_order_fulfillment_service,
                    "claim_order_for_fulfillment",
                    return_value=order,
                ), patch.object(
                    teacher_order_fulfillment_service,
                    "get_reusable_module",
                    return_value={
                        "id": 8,
                        "schedule_schema_version": module_schema_version,
                    },
                ), patch.object(
                    teacher_order_fulfillment_service,
                    "create_pipeline_platform",
                ) as create_platform:
                    with self.assertRaisesRegex(
                        teacher_order_fulfillment_service.PermanentWorkError,
                        "ne correspond pas",
                    ):
                        teacher_order_fulfillment_service.fulfill_teacher_order(
                            item,
                            _Lease(),
                        )

                create_platform.assert_not_called()

    def test_reuse_worker_rechecks_eligibility_before_any_platform_mutation(self):
        order = {
            "id": 7,
            "public_id": "reuse-ineligible",
            "center_account_id": 42,
            "operation_type": "reuse_teacher",
            "payment_status": "paid",
            "fulfillment_status": "queued",
            "source_module_id": 8,
            "training_title": "TP CRCD",
            "request_payload_json": {
                "name": "Promo suivante",
                "module_id": 8,
                "schedule": {
                    "schedule_schema_version": 2,
                    "selected_dates": ["2030-09-03", "2030-09-06"],
                },
            },
        }
        item = SimpleNamespace(payload={"order_id": 7}, pipeline_job_id=None)

        with patch.object(
            teacher_order_fulfillment_service,
            "claim_order_for_fulfillment",
            return_value=order,
        ), patch.object(
            teacher_order_fulfillment_service,
            "get_reusable_module",
            return_value=None,
        ), patch.object(
            teacher_order_fulfillment_service,
            "create_pipeline_platform",
        ) as create_platform, patch.object(
            teacher_order_fulfillment_service,
            "clone_postgres_course_structure",
        ) as clone:
            with self.assertRaisesRegex(
                teacher_order_fulfillment_service.PermanentWorkError,
                "n’est plus.*réutilisable",
            ):
                teacher_order_fulfillment_service.fulfill_teacher_order(
                    item,
                    _Lease(),
                )

        create_platform.assert_not_called()
        clone.assert_not_called()

    def test_reuse_worker_rechecks_exact_day_count_before_platform_creation(self):
        order = {
            "id": 7,
            "public_id": "reuse-wrong-day-count",
            "center_account_id": 42,
            "operation_type": "reuse_teacher",
            "payment_status": "paid",
            "fulfillment_status": "queued",
            "source_module_id": 8,
            "training_title": "TP CRCD",
            "request_payload_json": {
                "name": "Promo suivante",
                "module_id": 8,
                "schedule": {
                    "schedule_schema_version": 2,
                    "selected_dates": ["2030-09-03"],
                },
            },
        }
        module_days = [
            {"id": 301, "day_index": 1, "blocks": _valid_blocks()},
            {"id": 302, "day_index": 2, "blocks": _valid_blocks()},
        ]
        item = SimpleNamespace(payload={"order_id": 7}, pipeline_job_id=None)

        with patch.object(
            teacher_order_fulfillment_service,
            "claim_order_for_fulfillment",
            return_value=order,
        ), patch.object(
            teacher_order_fulfillment_service,
            "get_reusable_module",
            return_value={"id": 8, "schedule_schema_version": 2},
        ), patch.object(
            teacher_order_fulfillment_service,
            "list_module_days",
            return_value=module_days,
        ), patch.object(
            teacher_order_fulfillment_service,
            "create_pipeline_platform",
        ) as create_platform:
            with self.assertRaisesRegex(
                teacher_order_fulfillment_service.PermanentWorkError,
                "exactement",
            ):
                teacher_order_fulfillment_service.fulfill_teacher_order(
                    item,
                    _Lease(),
                )

        create_platform.assert_not_called()


if __name__ == "__main__":
    unittest.main()
