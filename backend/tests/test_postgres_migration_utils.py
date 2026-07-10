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
