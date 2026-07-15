import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask

try:
    import psycopg
except ImportError:  # pragma: no cover - exercised in PostgreSQL CI.
    psycopg = None

from tools.database import migrate_sqlite_core_to_postgres as core_migration
from tools.database import migrate_sqlite_pipeline_to_postgres as pipeline_migration
from tools.database.migration_utils import timezone_from_name
from routes import admin_routes


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BACKEND_DIR / "database" / "postgres_schema.sql"


@unittest.skipUnless(
    psycopg is not None
    and os.getenv("POSTGRES_TEST_DATABASE_URL")
    and os.getenv("POSTGRES_TEST_RESET_SCHEMA") == "1",
    "Nécessite un PostgreSQL jetable et POSTGRES_TEST_RESET_SCHEMA=1",
)
class RealPostgresIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database_url = os.environ["POSTGRES_TEST_DATABASE_URL"]
        cls.schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    def setUp(self):
        # This suite is deliberately destructive and only runs when the caller
        # explicitly marks the database as disposable.
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("DROP SCHEMA public CASCADE")
                cur.execute("CREATE SCHEMA public")
        self._apply_schema()
        self._apply_schema()  # Idempotency is part of the contract.

    def _apply_schema(self):
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(self.schema_sql)

    def _sqlite_fixture(self, ddl_and_rows: str):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        conn = sqlite3.connect(tmp.name)
        conn.row_factory = sqlite3.Row
        conn.executescript(ddl_and_rows)
        conn.commit()
        return tmp.name, conn

    def test_training_center_can_register_then_reconnect_in_pure_postgres(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="postgres-center-auth-test")
        app.register_blueprint(admin_routes.create_admin_blueprint(Mock()))

        with patch.object(
            admin_routes, "sqlite_runtime_enabled", return_value=False
        ), patch.object(
            admin_routes,
            "get_db_connection",
            side_effect=AssertionError("SQLite must not be opened"),
        ), patch.object(
            admin_routes,
            "_ensure_training_center_supabase_user",
            return_value=(True, None),
        ):
            with app.test_client() as registration_client:
                registration = registration_client.post(
                    "/api/admin/register",
                    json={
                        "center_name": "Centre PostgreSQL",
                        "username": "direction@centre.test",
                        "password": "correct-password",
                    },
                )

            self.assertEqual(registration.status_code, 201, registration.get_json())
            self.assertEqual(
                registration.get_json()["account"]["type"],
                "training_center",
            )

            with app.test_client() as login_client:
                login = login_client.post(
                    "/api/admin/login",
                    json={
                        "username": "direction@centre.test",
                        "password": "correct-password",
                    },
                )

            self.assertEqual(login.status_code, 200, login.get_json())
            self.assertEqual(login.get_json()["account"]["type"], "training_center")

        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT password_hash, password_debug_plaintext
                    FROM training_center_accounts
                    WHERE username = %s
                    """,
                    ("direction@centre.test",),
                )
                password_hash, plaintext = cur.fetchone()
        self.assertTrue(password_hash)
        self.assertIsNone(plaintext)

    def test_catalog_contains_runtime_types_indexes_and_rls(self):
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'course_sessions'
                      AND column_name = 'scheduled_at'
                    """
                )
                self.assertEqual(cur.fetchone()[0], "timestamp with time zone")
                cur.execute("SELECT to_regclass('public.deletion_requests')")
                self.assertEqual(cur.fetchone()[0], "deletion_requests")
                cur.execute(
                    """
                    SELECT c.relname
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relkind IN ('r', 'p')
                      AND c.relrowsecurity = FALSE
                    ORDER BY c.relname
                    """
                )
                self.assertEqual(cur.fetchall(), [])
                cur.execute(
                    """
                    SELECT 1
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND indexname = 'idx_formation_pipeline_jobs_auto_pilot_resume'
                    """
                )
                self.assertIsNotNone(cur.fetchone())

    def test_core_migration_preserves_instant_counts_and_sequences(self):
        path, sqlite_conn = self._sqlite_fixture(
            """
            CREATE TABLE training_center_accounts (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                center_name TEXT NOT NULL,
                slug TEXT NOT NULL,
                is_active INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO training_center_accounts VALUES
                (41, 'centre@example.test', 'hash', 'Centre test', 'centre-test', 1,
                 '2026-01-15 10:30:00', '2026-01-15 10:30:00');

            CREATE TABLE platform_config (
                id INTEGER PRIMARY KEY,
                center_account_id INTEGER,
                name TEXT NOT NULL,
                slug TEXT NOT NULL,
                upload_locked INTEGER,
                public_access_enabled INTEGER,
                updated_at TEXT NOT NULL,
                status TEXT
            );
            INSERT INTO platform_config VALUES
                (71, 41, 'Formation test', 'formation-test', 1, 1,
                 '2026-01-15 10:30:00', 'ready'),
                (72, 41, 'Formation test 2', 'formation-test-2', 1, 1,
                 '2026-01-15 10:35:00', 'ready');

            CREATE TABLE deletion_requests (
                id INTEGER PRIMARY KEY,
                platform_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                requester_name TEXT NOT NULL,
                reason TEXT,
                status TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );
            INSERT INTO deletion_requests VALUES
                (91, 71, 'support.pdf', 'Alice', 'doublon', 'pending',
                 '2026-01-15 10:30:00', NULL);
            """
        )
        try:
            paris = timezone_from_name("Europe/Paris")
            with psycopg.connect(self.database_url) as pg_conn:
                self.assertEqual(
                    core_migration.copy_table(
                        sqlite_conn,
                        pg_conn,
                        "training_center_accounts",
                        assumed_timezone=paris,
                    ),
                    1,
                )
                core_migration.copy_table(
                    sqlite_conn,
                    pg_conn,
                    "platform_config",
                    assumed_timezone=paris,
                    batch_size=1,
                )
                core_migration.copy_table(
                    sqlite_conn,
                    pg_conn,
                    "deletion_requests",
                    assumed_timezone=paris,
                )
                # A second pass must update the same ids without duplicating them.
                core_migration.copy_table(
                    sqlite_conn,
                    pg_conn,
                    "platform_config",
                    assumed_timezone=paris,
                    batch_size=1,
                )
                with pg_conn.cursor() as cur:
                    cur.execute(
                        "SELECT updated_at AT TIME ZONE 'UTC' FROM platform_config WHERE id = 71"
                    )
                    self.assertEqual(cur.fetchone()[0], datetime(2026, 1, 15, 9, 30))
                    cur.execute("SELECT COUNT(*) FROM platform_config WHERE id = 71")
                    self.assertEqual(cur.fetchone()[0], 1)
                    cur.execute(
                        """
                        INSERT INTO platform_config
                            (center_account_id, name, slug, updated_at)
                        VALUES (41, 'Formation suivante', 'formation-suivante', NOW())
                        RETURNING id
                        """
                    )
                    self.assertGreater(cur.fetchone()[0], 72)
        finally:
            sqlite_conn.close()
            os.unlink(path)

    def test_pipeline_migration_treats_sqlite_current_timestamp_as_utc(self):
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO platform_config (id, name, slug, updated_at)
                    VALUES (7, 'Pipeline test', 'pipeline-test', NOW())
                    """
                )

        path, sqlite_conn = self._sqlite_fixture(
            """
            CREATE TABLE formation_pipeline_jobs (
                id INTEGER PRIMARY KEY,
                platform_id INTEGER NOT NULL,
                tp_name TEXT NOT NULL,
                rncp_code TEXT,
                total_hours INTEGER NOT NULL,
                nb_days INTEGER NOT NULL,
                daily_programs TEXT,
                global_program_validated INTEGER,
                daily_programs_validated INTEGER,
                auto_pilot_enabled INTEGER,
                auto_pilot_use_cc INTEGER,
                auto_pilot_skip_vs INTEGER,
                auto_pilot_generate_audio INTEGER,
                auto_pilot_volume_done INTEGER,
                auto_pilot_post_review_docs_done INTEGER,
                status TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            INSERT INTO formation_pipeline_jobs VALUES
                (90, 7, 'TP Test', 'RNCP00001', 14, 2, '[{"day": 1}]',
                 0, 0, 1, 0, 0, 0, 0, 0, 'daily_ready',
                 '2026-01-15 09:00:00', '2026-01-15 09:05:00');
            """
        )
        try:
            with psycopg.connect(self.database_url) as pg_conn:
                pipeline_migration.copy_table(
                    sqlite_conn,
                    pg_conn,
                    "formation_pipeline_jobs",
                    assumed_timezone=timezone_from_name("UTC"),
                )
                with pg_conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT created_at AT TIME ZONE 'UTC', auto_pilot_enabled
                        FROM formation_pipeline_jobs WHERE id = 90
                        """
                    )
                    created_at, enabled = cur.fetchone()
                    self.assertEqual(created_at, datetime(2026, 1, 15, 9, 0))
                    self.assertTrue(enabled)
                    cur.execute(
                        """
                        INSERT INTO formation_pipeline_jobs
                            (platform_id, tp_name, total_hours, nb_days)
                        VALUES (7, 'TP suivant', 7, 1)
                        RETURNING id
                        """
                    )
                    self.assertGreater(cur.fetchone()[0], 90)
        finally:
            sqlite_conn.close()
            os.unlink(path)

    def test_rls_without_policy_hides_rows_from_unprivileged_role(self):
        role_name = "socrate_anon_ci"
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f"DROP ROLE IF EXISTS {role_name}")
                cur.execute(f"CREATE ROLE {role_name} NOLOGIN")
                try:
                    cur.execute(
                        """
                        INSERT INTO platform_config (name, slug, updated_at)
                        VALUES ('RLS visible owner', 'rls-owner', NOW())
                        """
                    )
                    cur.execute(f"GRANT USAGE ON SCHEMA public TO {role_name}")
                    cur.execute(f"GRANT SELECT ON platform_config TO {role_name}")
                    cur.execute(f"SET ROLE {role_name}")
                    cur.execute("SELECT COUNT(*) FROM platform_config")
                    self.assertEqual(cur.fetchone()[0], 0)
                    cur.execute("RESET ROLE")
                finally:
                    cur.execute("RESET ROLE")
                    cur.execute(f"REVOKE ALL ON platform_config FROM {role_name}")
                    cur.execute(f"REVOKE ALL ON SCHEMA public FROM {role_name}")
                    cur.execute(f"DROP ROLE {role_name}")


if __name__ == "__main__":
    unittest.main()
