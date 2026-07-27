import unittest
from pathlib import Path

from database.postgres import PIPELINE_REQUIRED_INDEXES, PIPELINE_REQUIRED_SCHEMA


BACKEND_DIR = Path(__file__).resolve().parents[1]


class PostgresSchemaContractTest(unittest.TestCase):
    def test_schema_contains_every_runtime_pipeline_table_and_column(self):
        schema = (BACKEND_DIR / "database" / "postgres_schema.sql").read_text(encoding="utf-8")
        for table, columns in PIPELINE_REQUIRED_SCHEMA.items():
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", schema)
            for column in columns:
                self.assertRegex(schema, rf"(?m)^\s*{column}\s+")

    def test_existing_course_sessions_receive_all_runtime_columns(self):
        schema = (BACKEND_DIR / "database" / "postgres_schema.sql").read_text(encoding="utf-8")
        for column in (
            "session_password",
            "session_password_generated_at",
            "reminder_previous_evening_claimed_at",
            "reminder_5min_claimed_at",
            "audio_generation_status",
            "audio_generation_started_at",
            "audio_generation_completed_at",
            "audio_generation_error",
            "audio_generation_attempts",
            "audio_generation_next_retry_at",
            "audio_job_id",
            "audio_folder_id",
            "postponed_from",
            "postponed_at",
            "postponement_count",
        ):
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {column}", schema)

    def test_schema_preserves_historical_sqlite_deletion_requests(self):
        schema = (BACKEND_DIR / "database" / "postgres_schema.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS deletion_requests", schema)
        for column in (
            "platform_id",
            "filename",
            "requester_name",
            "reason",
            "status",
            "created_at",
            "resolved_at",
        ):
            self.assertRegex(schema, rf"(?m)^\s*{column}\s+")
        self.assertIn("ALTER TABLE deletion_requests ENABLE ROW LEVEL SECURITY", schema)

    def test_pipeline_access_bootstrap_never_grants_tenant_ownership(self):
        schema = (BACKEND_DIR / "database" / "postgres_schema.sql").read_text(encoding="utf-8")
        self.assertIn("pipeline_permission_was_missing", schema)
        self.assertIn("IF pipeline_permission_was_missing THEN", schema)
        self.assertIn("pipeline_operator_count", schema)
        self.assertIn("IF pipeline_operator_count > 1 THEN", schema)
        self.assertIn("RAISE EXCEPTION", schema)
        self.assertIn("LOWER(username) = 'newpiprod@gmail.com'", schema)
        self.assertIn("pipeline_access_enabled = TRUE", schema)
        permission_bootstrap = schema[
            schema.index("-- Grant the initial Formation3 operator"):
            schema.index("-- Correction one-shot du bootstrap historique")
        ]
        self.assertNotIn(
            "UPDATE platform_config",
            permission_bootstrap,
            "Une permission pipeline ne doit jamais modifier la propriété tenant",
        )

    def test_historical_bulk_ownership_cleanup_is_evidence_based_and_one_time(self):
        schema = (BACKEND_DIR / "database" / "postgres_schema.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS app_schema_migrations", schema)
        self.assertIn("20260727_remove_pipeline_operator_bulk_ownership_v1", schema)
        self.assertIn("SET center_account_id = NULL", schema)
        self.assertIn("center_platform_number = NULL", schema)
        self.assertIn("platform.creation_request_id IS NULL", schema)
        self.assertIn("FROM ai_teacher_orders AS teacher_order", schema)
        self.assertIn("teacher_order.platform_id = platform.id", schema)
        self.assertIn("teacher_order.pipeline_job_id", schema)
        self.assertIn("DISABLE TRIGGER trg_assign_center_platform_number", schema)
        self.assertIn("ENABLE TRIGGER trg_assign_center_platform_number", schema)
        self.assertIn("ALTER TABLE app_schema_migrations ENABLE ROW LEVEL SECURITY", schema)

    def test_pipeline_tables_deny_direct_data_api_access_by_default(self):
        schema = (BACKEND_DIR / "database" / "postgres_schema.sql").read_text(encoding="utf-8")
        for table in PIPELINE_REQUIRED_SCHEMA:
            self.assertIn(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY", schema)

    def test_schema_enforces_one_active_queue_item_per_pipeline_scope(self):
        schema = (BACKEND_DIR / "database" / "postgres_schema.sql").read_text(encoding="utf-8")
        self.assertIn("uq_pipeline_work_items_active_scope", PIPELINE_REQUIRED_INDEXES)
        self.assertIn(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_pipeline_work_items_active_scope",
            schema,
        )
        self.assertIn("ON pipeline_work_items(pipeline_job_id, scope_key)", schema)
        self.assertIn("WHERE status IN ('queued', 'retry_scheduled', 'running')", schema)

    def test_schema_enforces_one_active_queue_item_per_resource_scope(self):
        schema = (BACKEND_DIR / "database" / "postgres_schema.sql").read_text(encoding="utf-8")
        self.assertIn(
            "uq_pipeline_work_items_active_resource_scope",
            PIPELINE_REQUIRED_INDEXES,
        )
        self.assertIn(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_pipeline_work_items_active_resource_scope",
            schema,
        )
        self.assertIn("ON pipeline_work_items(resource_key, scope_key)", schema)

    def test_schema_enforces_one_named_folder_per_pipeline_job(self):
        schema = (BACKEND_DIR / "database" / "postgres_schema.sql").read_text(encoding="utf-8")
        self.assertIn("uq_cours_folders_job_name", PIPELINE_REQUIRED_INDEXES)
        self.assertIn(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_cours_folders_job_name",
            schema,
        )
        self.assertIn("ON cours_folders(formation_job_id, name)", schema)
        self.assertIn("WHERE formation_job_id IS NOT NULL", schema)

    def test_reminder_delivery_join_has_a_covering_lookup_index(self):
        schema = (BACKEND_DIR / "database" / "postgres_schema.sql").read_text(encoding="utf-8")
        self.assertIn("idx_course_reminder_deliveries_lookup", PIPELINE_REQUIRED_INDEXES)
        self.assertIn(
            "ON course_reminder_deliveries(session_id, rule_id, recipient_id)",
            schema,
        )

    def test_attendance_exports_have_explicit_tenant_and_session_identity(self):
        schema = (BACKEND_DIR / "database" / "postgres_schema.sql").read_text(encoding="utf-8")
        self.assertIn("uq_platform_config_center_number", schema)
        self.assertIn("assign_center_platform_number", schema)
        self.assertIn("attendance_daily_exports_owner_required", schema)
        self.assertIn("attendance_daily_exports_platform_owner_fkey", schema)
        self.assertIn("attendance_daily_exports_session_platform_fkey", schema)
        self.assertIn(
            "ON attendance_daily_exports(center_account_id, center_platform_number, course_date DESC)",
            schema,
        )


if __name__ == "__main__":
    unittest.main()
