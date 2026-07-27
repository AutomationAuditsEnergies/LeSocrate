import json
import sqlite3
import unittest
from unittest.mock import patch
from datetime import timezone

from tools.database import migrate_sqlite_core_to_postgres as core_migration
from tools.database import migrate_sqlite_pipeline_to_postgres as pipeline_migration
from tools.database.migrate_sqlite_core_to_postgres import CORE_TABLES, normalize_row
from tools.database.migration_utils import (
    MigrationValidationError,
    normalize_bool,
    normalize_json_text,
    normalize_timestamp,
    normalize_uuid,
    timezone_from_name,
)


class PostgresMigrationUtilsTest(unittest.TestCase):
    def test_false_string_is_not_migrated_as_true(self):
        self.assertFalse(normalize_bool("0", context="test.flag"))
        self.assertFalse(normalize_bool("false", context="test.flag"))
        self.assertTrue(normalize_bool("1", context="test.flag"))
        with self.assertRaises(MigrationValidationError):
            normalize_bool("maybe", context="test.flag")

    def test_paris_naive_timestamp_is_converted_to_an_aware_utc_instant(self):
        migrated = normalize_timestamp(
            "2026-01-15 10:30:00",
            assumed_timezone=timezone_from_name("Europe/Paris"),
            context="platform_config.updated_at",
        )
        self.assertEqual(migrated.tzinfo, timezone.utc)
        self.assertEqual(migrated.isoformat(), "2026-01-15T09:30:00+00:00")

    def test_explicit_offset_is_preserved_independently_of_assumed_timezone(self):
        migrated = normalize_timestamp(
            "2026-07-15T10:30:00+02:00",
            assumed_timezone=timezone_from_name("UTC"),
            context="platform_config.updated_at",
        )
        self.assertEqual(migrated.isoformat(), "2026-07-15T08:30:00+00:00")

    def test_dst_ambiguous_or_nonexistent_local_times_require_an_offset(self):
        paris = timezone_from_name("Europe/Paris")
        for local_time in ("2026-03-29 02:30:00", "2026-10-25 02:30:00"):
            with self.subTest(local_time=local_time):
                with self.assertRaises(MigrationValidationError):
                    normalize_timestamp(
                        local_time,
                        assumed_timezone=paris,
                        context="course_sessions.scheduled_at",
                    )

    def test_invalid_json_and_uuid_fail_before_postgres(self):
        with self.assertRaises(MigrationValidationError):
            normalize_json_text("{broken", context="formation_pipeline_jobs.daily_programs")
        with self.assertRaises(MigrationValidationError):
            normalize_uuid("student-not-a-uuid", context="student_profiles.auth_user_id")
        self.assertEqual(json.loads(normalize_json_text('["é"]', context="test.json")), ["é"])

    def test_core_migration_includes_every_operational_sqlite_table(self):
        for table in (
            "course_schedule_config",
            "course_sessions",
            "course_reminder_recipients",
            "student_attendance_records",
            "ai_teacher_orders",
            "deletion_requests",
        ):
            self.assertIn(table, CORE_TABLES)

    def test_core_row_normalization_validates_json_and_timezone(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT 7 AS platform_id,
                   '[1, 3]' AS weekdays_json,
                   '2026-07-15 10:30:00' AS created_at
            """
        ).fetchone()
        values = normalize_row(
            "course_schedule_config",
            ["platform_id", "weekdays_json", "created_at"],
            row,
            assumed_timezone=timezone_from_name("Europe/Paris"),
        )
        conn.close()
        self.assertEqual(values[0], 7)
        self.assertEqual(json.loads(values[1]), [1, 3])
        self.assertEqual(values[2].isoformat(), "2026-07-15T08:30:00+00:00")

    def test_plaintext_password_is_never_migrated(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT 1 AS id, 'hash' AS password_hash, 'secret' AS password_debug_plaintext"
        ).fetchone()
        values = normalize_row(
            "training_center_accounts",
            ["id", "password_hash", "password_debug_plaintext"],
            row,
            assumed_timezone=timezone_from_name("Europe/Paris"),
        )
        conn.close()
        self.assertEqual(values, [1, "hash", None])

    def test_pipeline_permission_is_normalized_as_a_boolean(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT 1 AS id, 0 AS pipeline_access_enabled"
        ).fetchone()
        values = normalize_row(
            "training_center_accounts",
            ["id", "pipeline_access_enabled"],
            row,
            assumed_timezone=timezone_from_name("Europe/Paris"),
        )
        conn.close()
        self.assertEqual(values[0], 1)
        self.assertIs(values[1], False)

    def test_legacy_pipeline_bootstrap_preserves_an_explicit_revocation(self):
        decision = core_migration.should_bootstrap_legacy_pipeline_operator

        self.assertTrue(
            decision(
                source_has_permission_column=False,
                previous_target_permission=None,
            )
        )
        self.assertTrue(
            decision(
                source_has_permission_column=False,
                previous_target_permission=True,
            )
        )
        self.assertFalse(
            decision(
                source_has_permission_column=False,
                previous_target_permission=False,
            )
        )
        self.assertFalse(
            decision(
                source_has_permission_column=True,
                previous_target_permission=None,
            )
        )

    def test_reconcile_restores_target_revocation_after_stale_source_grant(self):
        class FakeCursor:
            def __init__(self, connection):
                self.connection = connection
                self.rows = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def execute(self, query, params):
                normalized = " ".join(str(query).split())
                if "SET pipeline_access_enabled = FALSE" in normalized:
                    self.connection.permission_enabled = False
                    self.rows = []
                elif normalized.startswith(
                    "SELECT id, is_active, pipeline_access_enabled"
                ):
                    self.rows = [
                        (7, True, self.connection.permission_enabled)
                    ]
                elif normalized.startswith("UPDATE platform_config"):
                    self.connection.platform_update_called = True
                    self.rows = [(101,)]
                else:
                    raise AssertionError(f"Requête inattendue: {normalized} {params}")

            def fetchall(self):
                return list(self.rows)

        class FakeConnection:
            def __init__(self):
                # Simule copy_table venant de réimporter TRUE depuis SQLite.
                self.permission_enabled = True
                self.platform_update_called = False

            def cursor(self):
                return FakeCursor(self)

        sqlite_conn = sqlite3.connect(":memory:")
        sqlite_conn.executescript(
            """
            CREATE TABLE training_center_accounts (
                id INTEGER PRIMARY KEY,
                pipeline_access_enabled INTEGER NOT NULL
            );
            CREATE TABLE formation_pipeline_jobs (
                id INTEGER PRIMARY KEY,
                platform_id INTEGER NOT NULL
            );
            INSERT INTO formation_pipeline_jobs VALUES (1, 101);
            """
        )
        target = FakeConnection()

        enabled, attached = (
            core_migration.reconcile_pipeline_operator_after_core_copy(
                sqlite_conn,
                target,
                previous_target_permission=False,
            )
        )

        sqlite_conn.close()
        self.assertFalse(enabled)
        self.assertEqual(attached, 0)
        self.assertFalse(target.permission_enabled)
        self.assertFalse(target.platform_update_called)

    def test_core_temporarily_neutralizes_v2_module_day_binding(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT 81 AS id, 42 AS module_day_id, "
            "'2026-07-15 10:30:00' AS scheduled_at"
        ).fetchone()
        columns = ["id", "module_day_id", "scheduled_at"]

        values = core_migration.normalize_row(
            "course_sessions",
            columns,
            row,
            assumed_timezone=timezone_from_name("Europe/Paris"),
        )

        conn.close()
        self.assertEqual(values[0:2], [81, None])
        self.assertEqual(values[2].isoformat(), "2026-07-15T08:30:00+00:00")

    def test_pipeline_tables_follow_v2_foreign_key_order(self):
        tables = pipeline_migration.PIPELINE_TABLES
        for table in (
            "day_schedule_templates",
            "day_schedule_template_blocks",
            "formation_module_days",
            "formation_module_assets",
        ):
            self.assertIn(table, tables)
        self.assertLess(tables.index("formation_pipeline_jobs"), tables.index("formation_modules"))
        self.assertLess(tables.index("formation_modules"), tables.index("formation_module_days"))
        self.assertLess(tables.index("day_schedule_templates"), tables.index("formation_module_days"))
        self.assertLess(tables.index("formation_module_days"), tables.index("cours_folders"))
        self.assertLess(tables.index("cours_folders"), tables.index("formation_module_assets"))

    def test_pipeline_declares_every_v2_type_normalization(self):
        self.assertEqual(
            pipeline_migration.BOOL_COLUMNS["formation_module_days"],
            {"immutable"},
        )
        self.assertEqual(
            pipeline_migration.BOOL_COLUMNS["formation_module_assets"],
            {"immutable"},
        )
        self.assertTrue(
            {"immutable", "canonical_reuse_allowed"}.issubset(
                pipeline_migration.BOOL_COLUMNS["formation_modules"]
            )
        )
        expected_json = {
            "formation_pipeline_jobs": "schedule_snapshot_json",
            "formation_modules": "canonical_signature_json",
            "day_schedule_templates": "blocks_snapshot_json",
            "day_schedule_template_blocks": "metadata_json",
            "formation_module_days": "blocks_snapshot_json",
            "formation_module_assets": "generation_params_json",
        }
        for table, column in expected_json.items():
            self.assertIn(column, pipeline_migration.JSON_COLUMNS[table])
            self.assertIn(column, pipeline_migration.JSONB_COLUMNS[table])
        expected_timestamps = {
            "formation_pipeline_jobs": {"schedule_locked_at"},
            "formation_modules": {"schedule_locked_at", "reusable_at"},
            "day_schedule_templates": {
                "used_at",
                "locked_at",
                "deleted_at",
                "created_at",
                "updated_at",
            },
            "day_schedule_template_blocks": {"created_at"},
            "formation_module_days": {"locked_at", "created_at"},
            "formation_module_assets": {
                "last_verified_at",
                "created_at",
                "updated_at",
            },
        }
        for table, columns in expected_timestamps.items():
            self.assertTrue(columns.issubset(pipeline_migration.TIMESTAMP_COLUMNS[table]))

    def test_pipeline_v2_values_are_normalized_and_jsonb_adapted(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT 7 AS id,
                   1 AS immutable,
                   '{"voice":"stable"}' AS canonical_signature_json,
                   '2026-07-15 10:30:00' AS schedule_locked_at,
                   '2026-07-16 10:30:00' AS reusable_at
            """
        ).fetchone()
        columns = [
            "id",
            "immutable",
            "canonical_signature_json",
            "schedule_locked_at",
            "reusable_at",
        ]

        values = pipeline_migration.normalize_row(
            "formation_modules",
            columns,
            row,
            assumed_timezone=timezone_from_name("Europe/Paris"),
        )
        prepared = pipeline_migration.prepare_postgres_row(
            "formation_modules",
            columns,
            values,
        )

        conn.close()
        self.assertIs(values[1], True)
        self.assertEqual(values[3].isoformat(), "2026-07-15T08:30:00+00:00")
        self.assertEqual(values[4].isoformat(), "2026-07-16T08:30:00+00:00")
        self.assertEqual(prepared[2].obj, {"voice": "stable"})

    def test_pipeline_restores_and_verifies_course_session_module_days(self):
        class FakeCursor:
            def __init__(self, session_ids, module_day_ids):
                self.session_ids = set(session_ids)
                self.module_day_ids = set(module_day_ids)
                self.restored = {}
                self.current = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def execute(self, _query, params):
                module_day_id, session_id, checked_module_day_id = params
                if (
                    module_day_id == checked_module_day_id
                    and session_id in self.session_ids
                    and module_day_id in self.module_day_ids
                ):
                    self.restored[session_id] = module_day_id
                    self.current = (session_id, module_day_id)
                else:
                    self.current = None

            def fetchone(self):
                return self.current

        class FakeConnection:
            def __init__(self, cursor):
                self._cursor = cursor

            def cursor(self):
                return self._cursor

        sqlite_conn = sqlite3.connect(":memory:")
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_conn.executescript(
            """
            CREATE TABLE course_sessions (
                id INTEGER PRIMARY KEY,
                module_day_id INTEGER
            );
            INSERT INTO course_sessions VALUES (10, 100), (11, NULL);
            """
        )
        cursor = FakeCursor(session_ids={10, 11}, module_day_ids={100})

        restored = pipeline_migration.restore_course_session_module_days(
            sqlite_conn,
            FakeConnection(cursor),
        )

        self.assertEqual(restored, 1)
        self.assertEqual(cursor.restored, {10: 100})
        cursor.module_day_ids.clear()
        with self.assertRaisesRegex(
            MigrationValidationError,
            "session=10, module_day=100",
        ):
            pipeline_migration.restore_course_session_module_days(
                sqlite_conn,
                FakeConnection(cursor),
            )
        sqlite_conn.close()

    def test_core_preflight_reports_orphan_platform_data_before_copy(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE platform_config (id INTEGER PRIMARY KEY);
            CREATE TABLE cours_config (
                id INTEGER PRIMARY KEY,
                platform_id INTEGER,
                heure_debut TEXT
            );
            INSERT INTO cours_config VALUES (12, 12, '2026-01-15 10:00:00');
            """
        )
        with self.assertRaisesRegex(MigrationValidationError, "cours_config.*1 ligne"):
            core_migration.validate_source_integrity(conn)
        conn.close()

    def test_pipeline_preflight_reports_orphan_job_before_copy(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE platform_config (id INTEGER PRIMARY KEY);
            CREATE TABLE formation_pipeline_jobs (
                id INTEGER PRIMARY KEY,
                platform_id INTEGER NOT NULL
            );
            INSERT INTO formation_pipeline_jobs VALUES (90, 999);
            """
        )
        with self.assertRaisesRegex(
            MigrationValidationError,
            "formation_pipeline_jobs.platform_id.*1 ligne",
        ):
            pipeline_migration.validate_source_integrity(conn)
        conn.close()

    def test_pipeline_preflight_rejects_duplicate_folder_identity(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE cours_folders (
                id INTEGER PRIMARY KEY,
                formation_job_id INTEGER,
                name TEXT NOT NULL
            );
            INSERT INTO cours_folders VALUES (1, 90, 'Jour 1');
            INSERT INTO cours_folders VALUES (2, 90, 'Jour 1');
            INSERT INTO cours_folders VALUES (3, NULL, 'Jour 1');
            INSERT INTO cours_folders VALUES (4, NULL, 'Jour 1');
            """
        )
        with self.assertRaisesRegex(
            MigrationValidationError,
            r"cours_folders \(formation_job_id, name\) dupliqué: 1 ligne",
        ):
            pipeline_migration.validate_source_integrity(conn)
        conn.close()

    def test_core_preflight_rejects_duplicate_course_config_per_platform(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE platform_config (id INTEGER PRIMARY KEY);
            CREATE TABLE cours_config (
                id INTEGER PRIMARY KEY,
                platform_id INTEGER,
                heure_debut TEXT
            );
            INSERT INTO platform_config VALUES (12);
            INSERT INTO cours_config VALUES (12, 12, '2026-01-15 10:00:00');
            INSERT INTO cours_config VALUES (13, 12, '2026-01-16 10:00:00');
            """
        )
        with self.assertRaisesRegex(MigrationValidationError, "cours_config.platform_id dupliqué"):
            core_migration.validate_source_integrity(conn)
        conn.close()

    def test_copy_fails_when_postgres_would_silently_drop_a_source_column(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE logs (id INTEGER PRIMARY KEY, nom TEXT, legacy_only TEXT)"
        )
        with patch.object(
            core_migration,
            "postgres_columns",
            return_value=["id", "nom"],
        ):
            with self.assertRaisesRegex(MigrationValidationError, "legacy_only"):
                core_migration.copy_table(
                    conn,
                    object(),
                    "logs",
                    assumed_timezone=timezone_from_name("Europe/Paris"),
                )
        conn.close()


if __name__ == "__main__":
    unittest.main()
