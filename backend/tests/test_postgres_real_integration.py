import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover - exercised in PostgreSQL CI.
    psycopg = None

from tools.database import migrate_sqlite_core_to_postgres as core_migration
from tools.database import migrate_sqlite_pipeline_to_postgres as pipeline_migration
from tools.database.migration_utils import timezone_from_name


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

    def test_supabase_auth_binding_is_added_when_auth_users_exists(self):
        auth_user_id = "9d388c09-07f7-46c8-ae1b-4de5d847f845"
        try:
            with psycopg.connect(self.database_url, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO training_center_accounts
                            (username, password_hash, center_name, slug)
                        VALUES
                            ('centre-auth@example.test', 'hash', 'Centre Auth', 'centre-auth')
                        """
                    )
                    cur.execute("CREATE SCHEMA auth")
                    cur.execute(
                        """
                        CREATE TABLE auth.users (
                            id UUID PRIMARY KEY,
                            email TEXT
                        )
                        """
                    )
                    cur.execute(
                        "INSERT INTO auth.users (id, email) VALUES (%s, %s)",
                        (auth_user_id, "centre-auth@example.test"),
                    )

            self._apply_schema()
            self._apply_schema()

            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT auth_user_id
                        FROM training_center_accounts
                        WHERE username = 'centre-auth@example.test'
                        """
                    )
                    self.assertEqual(str(cur.fetchone()[0]), auth_user_id)
                    cur.execute(
                        """
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'training_center_accounts_auth_user_id_fkey'
                          AND conrelid = 'training_center_accounts'::regclass
                        """
                    )
                    self.assertIsNotNone(cur.fetchone())
                    cur.execute("DELETE FROM auth.users WHERE id = %s", (auth_user_id,))
                    cur.execute(
                        """
                        SELECT auth_user_id
                        FROM training_center_accounts
                        WHERE username = 'centre-auth@example.test'
                        """
                    )
                    self.assertIsNone(cur.fetchone()[0])
        finally:
            with psycopg.connect(self.database_url, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("DROP SCHEMA IF EXISTS auth CASCADE")

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

    def test_platform_numbers_restart_per_center_and_exports_reject_cross_tenant_identity(self):
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO training_center_accounts
                        (id, username, password_hash, center_name, slug)
                    VALUES
                        (501, 'centre-a@example.test', 'hash', 'Centre A', 'centre-a'),
                        (502, 'centre-b@example.test', 'hash', 'Centre B', 'centre-b')
                    """
                )
                cur.execute(
                    """
                    INSERT INTO platform_config (center_account_id, name, slug)
                    VALUES
                        (501, 'A1', 'a1'),
                        (501, 'A2', 'a2'),
                        (502, 'B1', 'b1')
                    RETURNING id, center_account_id, center_platform_number
                    """
                )
                platforms = cur.fetchall()
                center_a = [row for row in platforms if row[1] == 501]
                center_b = [row for row in platforms if row[1] == 502]
                self.assertEqual([row[2] for row in center_a], [1, 2])
                self.assertEqual([row[2] for row in center_b], [1])

                platform_a_id = center_a[0][0]
                cur.execute(
                    """
                    INSERT INTO course_sessions
                        (platform_id, session_index, scheduled_at, status)
                    VALUES (%s, 1, '2026-07-17 07:00:00+00', 'completed')
                    RETURNING id
                    """,
                    (platform_a_id,),
                )
                session_id = cur.fetchone()[0]
                with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                    with conn.transaction():
                        cur.execute(
                            """
                            INSERT INTO attendance_daily_exports
                                (center_account_id, platform_id, center_platform_number,
                                 course_session_id, course_date, available_at)
                            VALUES (502, %s, 1, %s, '2026-07-17', '2026-07-18 04:00:00+00')
                            """,
                            (platform_a_id, session_id),
                        )

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
                auto_pilot_post_review_docs_done INTEGER,
                status TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            INSERT INTO formation_pipeline_jobs VALUES
                (90, 7, 'TP Test', 'RNCP00001', 14, 2, '[{"day": 1}]',
                 0, 0, 1, 0, 'daily_ready',
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
