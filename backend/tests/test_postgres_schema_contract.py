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
        ):
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {column}", schema)

    def test_schema_covers_operational_sqlite_deletion_requests(self):
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


if __name__ == "__main__":
    unittest.main()
