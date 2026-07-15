import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from config import FRANCE_TZ
from repositories import course_schedule_repository as repo
from services import course_schedule_service as service
from services import time_service


def _make_schedule_db():
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.executescript(
        """
        CREATE TABLE course_sessions (
            id INTEGER PRIMARY KEY,
            platform_id INTEGER NOT NULL,
            session_index INTEGER NOT NULL,
            scheduled_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'planned',
            reminder_previous_evening_sent_at TEXT,
            reminder_5min_sent_at TEXT,
            reminder_previous_evening_claimed_at TEXT,
            reminder_5min_claimed_at TEXT,
            session_password TEXT,
            session_password_generated_at TEXT,
            audio_generation_status TEXT DEFAULT 'pending',
            audio_generation_started_at TEXT,
            audio_generation_completed_at TEXT,
            audio_generation_error TEXT,
            audio_generation_attempts INTEGER NOT NULL DEFAULT 0,
            audio_generation_next_retry_at TEXT,
            audio_job_id INTEGER,
            audio_folder_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(platform_id, session_index)
        );
        CREATE TABLE course_schedule_config (
            platform_id INTEGER PRIMARY KEY,
            total_training_days INTEGER NOT NULL,
            weekly_course_count INTEGER NOT NULL,
            weekdays_json TEXT NOT NULL,
            start_time TEXT NOT NULL,
            timezone TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO course_sessions (
            id, platform_id, session_index, scheduled_at, status, created_at, updated_at
        ) VALUES (
            9, 12, 1, '2026-07-11 09:00:00', 'planned',
            '2026-07-10 09:00:00', '2026-07-10 09:00:00'
        );
        """
    )
    conn.commit()
    conn.close()
    return tmp.name


class CourseScheduleRepositoryTest(unittest.TestCase):
    def test_legacy_save_schedule_also_keeps_completed_history(self):
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        service.ensure_course_schedule_tables(cursor)
        cursor.execute(
            """
            INSERT INTO course_sessions (
                platform_id, session_index, scheduled_at, status,
                created_at, updated_at
            ) VALUES (12, 1, '2020-01-01 09:00:00', 'completed',
                      '2020-01-01 08:00:00', '2020-01-01 10:00:00')
            """
        )

        service.save_course_schedule(
            cursor,
            12,
            {
                "total_training_days": 1,
                "weekly_course_count": 1,
                "weekdays": [0],
                "start_time": "10:00",
                "start_date": "2030-01-07",
            },
        )

        rows = cursor.execute(
            """
            SELECT session_index, status
            FROM course_sessions
            WHERE platform_id = 12
            ORDER BY session_index
            """
        ).fetchall()
        conn.close()
        self.assertEqual(rows, [(1, "completed"), (2, "planned")])

    def test_schedule_replacement_preserves_history_and_reindexes_new_sessions(self):
        db_path = _make_schedule_db()
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                UPDATE course_sessions
                SET scheduled_at = '2026-07-01 09:00:00', status = 'completed'
                WHERE id = 9
                """
            )
            conn.execute(
                """
                INSERT INTO course_sessions (
                    id, platform_id, session_index, scheduled_at, status,
                    created_at, updated_at
                ) VALUES (10, 12, 2, '2026-08-01 09:00:00', 'planned',
                          '2026-07-10 09:00:00', '2026-07-10 09:00:00')
                """
            )
            conn.commit()
            conn.close()

            now = datetime(2026, 7, 10, 12, 0, tzinfo=FRANCE_TZ)
            with (
                patch.object(repo, "schedule_store_is_postgres", lambda: False),
                patch.object(repo, "get_db_connection", side_effect=lambda: sqlite3.connect(db_path)),
            ):
                repo.replace_course_schedule(
                    platform_id=12,
                    total_training_days=1,
                    weekly_course_count=1,
                    weekdays_json="[0]",
                    start_time="10:00",
                    timezone_name="Europe/Paris",
                    sessions=[{
                        "session_index": 1,
                        "scheduled_at": now + timedelta(days=7),
                        "session_password": "NEW123",
                    }],
                    now=now,
                )

            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                """
                SELECT session_index, scheduled_at, status, session_password
                FROM course_sessions
                WHERE platform_id = 12
                ORDER BY session_index
                """
            ).fetchall()
            conn.close()

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][:3], (1, "2026-07-01 09:00:00", "completed"))
            self.assertEqual(rows[1][0], 2)
            self.assertEqual(rows[1][2:], ("planned", "NEW123"))
        finally:
            os.unlink(db_path)

    def test_schedule_backend_follows_pipeline_postgres_in_hybrid_mode(self):
        with patch.object(repo, "DATABASE_BACKEND", "hybrid"), patch.object(
            repo, "PIPELINE_DATABASE_BACKEND", "sqlite"
        ):
            self.assertFalse(repo.schedule_store_is_postgres())
        with patch.object(repo, "DATABASE_BACKEND", "hybrid"), patch.object(
            repo, "PIPELINE_DATABASE_BACKEND", "postgres"
        ):
            self.assertTrue(repo.schedule_store_is_postgres())
        with patch.object(repo, "DATABASE_BACKEND", "sqlite"), patch.object(
            repo, "PIPELINE_DATABASE_BACKEND", "supabase"
        ):
            self.assertTrue(repo.schedule_store_is_postgres())
        for backend in ("postgres", "postgresql", "supabase"):
            with self.subTest(backend=backend), patch.object(
                repo, "DATABASE_BACKEND", backend
            ), patch.object(repo, "PIPELINE_DATABASE_BACKEND", "sqlite"):
                self.assertTrue(repo.schedule_store_is_postgres())

    def test_hybrid_pipeline_postgres_schedule_summary_never_opens_sqlite(self):
        expected = {"total_training_days": 3, "next_session_at": "2026-07-11 09:00:00"}
        with patch.object(repo, "DATABASE_BACKEND", "hybrid"), patch.object(
            repo, "PIPELINE_DATABASE_BACKEND", "postgres"
        ), patch.object(
            repo, "get_postgres_course_schedule_summary", return_value=expected
        ) as postgres_read, patch.object(
            repo,
            "get_db_connection",
            side_effect=AssertionError("SQLite must not be opened"),
        ):
            self.assertEqual(repo.get_course_schedule_summary(12), expected)

        postgres_read.assert_called_once_with(12)

    def test_hybrid_pipeline_postgres_reminders_never_open_sqlite(self):
        scheduled_at = datetime.now(FRANCE_TZ) + timedelta(minutes=3)

        class FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, params):
                self.query = query
                self.params = params

            def fetchall(self):
                return [{
                    "id": 9,
                    "platform_id": 12,
                    "session_index": 1,
                    "scheduled_at": scheduled_at,
                    "reminder_previous_evening_sent_at": None,
                    "reminder_5min_sent_at": None,
                    "session_password": "ABC123",
                }]

        class FakeConnection:
            def cursor(self):
                return FakeCursor()

        class FakeContext:
            def __enter__(self):
                return FakeConnection()

            def __exit__(self, *_args):
                return False

        with patch.object(repo, "DATABASE_BACKEND", "hybrid"), patch.object(
            repo, "PIPELINE_DATABASE_BACKEND", "postgres"
        ), patch.object(
            repo, "get_postgres_connection", return_value=FakeContext()
        ), patch.object(
            repo,
            "get_db_connection",
            side_effect=AssertionError("SQLite must not be opened"),
        ):
            rows = repo.list_due_reminder_sessions(active_until=scheduled_at)

        self.assertEqual(rows[0]["id"], 9)
        self.assertEqual(rows[0]["session_password"], "ABC123")

    def test_hybrid_explicit_reminder_recipients_use_postgres(self):
        created_at = datetime.now(FRANCE_TZ)

        class FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, params):
                self.query = query
                self.params = params

            def fetchall(self):
                return [{
                    "id": 4,
                    "email": "eleve@example.com",
                    "created_at": created_at,
                }]

        class FakeConnection:
            def cursor(self):
                return FakeCursor()

        class FakeContext:
            def __enter__(self):
                return FakeConnection()

            def __exit__(self, *_args):
                return False

        with patch.object(repo, "DATABASE_BACKEND", "hybrid"), patch.object(
            repo, "PIPELINE_DATABASE_BACKEND", "postgres"
        ), patch.object(
            repo, "get_postgres_connection", return_value=FakeContext()
        ), patch.object(
            repo,
            "get_db_connection",
            side_effect=AssertionError("SQLite must not be opened"),
        ):
            rows = repo.list_explicit_course_reminder_recipients(12)

        self.assertEqual(rows, [{
            "id": 4,
            "email": "eleve@example.com",
            "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }])

    def test_sqlite_audio_claim_is_atomic_and_completed_session_cannot_fail(self):
        db_path = _make_schedule_db()
        try:
            with (
                patch.object(repo, "schedule_store_is_postgres", lambda: False),
                patch.object(repo, "get_db_connection", side_effect=lambda: sqlite3.connect(db_path)),
            ):
                started = datetime.now(FRANCE_TZ)
                self.assertTrue(repo.claim_audio_generation_session(
                    session_id=9,
                    job_id=41,
                    folder_id=55,
                    started_at=started,
                ))
                self.assertFalse(repo.claim_audio_generation_session(
                    session_id=9,
                    job_id=41,
                    folder_id=55,
                    started_at=started,
                ))
                replacement_started = started + timedelta(minutes=20)
                self.assertTrue(repo.claim_audio_generation_session(
                    session_id=9,
                    job_id=41,
                    folder_id=55,
                    started_at=replacement_started,
                    stale_started_before=started + timedelta(minutes=10),
                ))
                self.assertFalse(repo.touch_audio_generation_session(
                    9,
                    updated_at=started + timedelta(minutes=21),
                    expected_started_at=started,
                ))
                self.assertTrue(repo.touch_audio_generation_session(
                    9,
                    updated_at=started + timedelta(minutes=21),
                    expected_started_at=replacement_started,
                ))
                self.assertFalse(repo.complete_audio_generation_session(
                    9,
                    completed_at=started + timedelta(minutes=22),
                    expected_started_at=started,
                ))
                self.assertTrue(repo.complete_audio_generation_session(
                    9,
                    completed_at=started + timedelta(minutes=22),
                    expected_started_at=replacement_started,
                ))
                self.assertFalse(repo.fail_audio_generation_session(
                    9,
                    error="late worker error",
                    failed_at=started + timedelta(minutes=3),
                ))

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                """
                SELECT audio_generation_status, audio_job_id, audio_folder_id,
                       audio_generation_completed_at, audio_generation_error
                FROM course_sessions WHERE id = 9
                """
            ).fetchone()
            conn.close()
            self.assertEqual(row[0], "completed")
            self.assertEqual(row[1:3], (41, 55))
            self.assertIsNotNone(row[3])
            self.assertIsNone(row[4])
        finally:
            os.unlink(db_path)

    def test_audio_failures_receive_exponential_retry_deadlines(self):
        db_path = _make_schedule_db()
        try:
            started = datetime.now(FRANCE_TZ)
            with (
                patch.object(repo, "schedule_store_is_postgres", lambda: False),
                patch.object(repo, "get_db_connection", side_effect=lambda: sqlite3.connect(db_path)),
                patch.dict("os.environ", {
                    "SCHEDULED_AUDIO_RETRY_BASE_MINUTES": "5",
                    "SCHEDULED_AUDIO_RETRY_MAX_MINUTES": "60",
                }),
            ):
                self.assertTrue(repo.claim_audio_generation_session(
                    session_id=9,
                    job_id=41,
                    folder_id=55,
                    started_at=started,
                ))
                self.assertTrue(repo.fail_audio_generation_session(
                    9,
                    error="provider timeout",
                    failed_at=started + timedelta(minutes=1),
                    expected_started_at=started,
                ))

            conn = sqlite3.connect(db_path)
            attempts, retry_at = conn.execute(
                "SELECT audio_generation_attempts, audio_generation_next_retry_at FROM course_sessions WHERE id = 9"
            ).fetchone()
            conn.close()
            self.assertEqual(attempts, 1)
            self.assertEqual(
                retry_at,
                (started + timedelta(minutes=6)).strftime("%Y-%m-%d %H:%M:%S"),
            )
        finally:
            os.unlink(db_path)

    def test_cancel_is_atomic_with_audio_claim(self):
        db_path = _make_schedule_db()
        try:
            with (
                patch.object(repo, "schedule_store_is_postgres", lambda: False),
                patch.object(repo, "get_db_connection", side_effect=lambda: sqlite3.connect(db_path)),
            ):
                self.assertTrue(repo.cancel_course_session(
                    12,
                    9,
                    cancelled_at=datetime.now(FRANCE_TZ),
                ))
                self.assertFalse(repo.claim_audio_generation_session(
                    session_id=9,
                    job_id=41,
                    folder_id=55,
                    started_at=datetime.now(FRANCE_TZ),
                ))
        finally:
            os.unlink(db_path)

    def test_postgres_audio_claim_uses_update_returning_without_sqlite(self):
        executed = {}

        class FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, params):
                self.query = query
                if "UPDATE course_sessions" in query:
                    executed["query"] = query
                    executed["params"] = params

            def fetchone(self):
                if "SELECT platform_id" in self.query:
                    return {"platform_id": 12}
                return {"id": 9}

        class FakeConnection:
            def cursor(self):
                return FakeCursor()

        class FakeContext:
            def __enter__(self):
                return FakeConnection()

            def __exit__(self, *_args):
                return False

        with (
            patch.object(repo, "schedule_store_is_postgres", lambda: True),
            patch.object(repo, "get_postgres_connection", lambda: FakeContext()),
            patch.object(
                repo,
                "get_db_connection",
                side_effect=AssertionError("SQLite must not be opened"),
            ),
        ):
            claimed = repo.claim_audio_generation_session(
                session_id=9,
                job_id=41,
                folder_id=55,
                started_at=datetime.now(FRANCE_TZ),
                stale_started_before=datetime.now(FRANCE_TZ) - timedelta(minutes=10),
            )

        self.assertTrue(claimed)
        self.assertIn("RETURNING id", executed["query"])
        self.assertIn("COALESCE(updated_at, audio_generation_started_at) <= %s", executed["query"])
        self.assertEqual(executed["params"][1:3], [41, 55])

    def test_missing_postgres_course_start_never_falls_back_to_platform_one_or_sqlite(self):
        queries = []

        class FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, params=()):
                queries.append((query, params))

            def fetchone(self):
                return None

        class FakeConnection:
            def cursor(self):
                return FakeCursor()

        class FakeContext:
            def __enter__(self):
                return FakeConnection()

            def __exit__(self, *_args):
                return False

        with (
            patch.object(repo, "schedule_store_is_postgres", lambda: True),
            patch.object(repo, "get_postgres_connection", lambda: FakeContext()),
            patch.object(repo, "get_db_connection", side_effect=AssertionError("SQLite must not open")),
        ):
            self.assertIsNone(repo.get_course_start(12))

        self.assertEqual(len(queries), 1)
        self.assertIn("platform_id = %s", queries[0][0])
        self.assertNotIn("id = 1", queries[0][0])

        with (
            patch.object(time_service.schedule_repo, "schedule_store_is_postgres", lambda: True),
            patch.object(time_service.schedule_repo, "get_course_start", return_value=None),
            patch.object(
                time_service,
                "get_db_connection",
                side_effect=AssertionError("SQLite must not open"),
            ),
        ):
            with self.assertRaisesRegex(LookupError, "plateforme 12"):
                time_service.get_heure_debut_cours(12)

    def test_service_creates_postgres_schedule_without_opening_sqlite(self):
        captured = {}

        def replace(**kwargs):
            captured.update(kwargs)

        first_day = datetime.now(FRANCE_TZ) + timedelta(days=3)
        with (
            patch.object(service.schedule_repo, "schedule_store_is_postgres", lambda: True),
            patch.object(service.schedule_repo, "replace_course_schedule", side_effect=replace),
            patch.object(
                service,
                "get_db_connection",
                side_effect=AssertionError("SQLite must not be opened"),
            ),
        ):
            result = service.create_course_schedule(
                12,
                {
                    "total_training_days": 2,
                    "weekly_course_count": 1,
                    "weekdays": [first_day.weekday()],
                    "start_time": "10:00",
                    "start_date": first_day.strftime("%Y-%m-%d"),
                },
            )

        self.assertEqual(result["total_sessions"], 2)
        self.assertEqual(captured["platform_id"], 12)
        self.assertEqual(len(captured["sessions"]), 2)
        self.assertTrue(all(item["scheduled_at"].tzinfo is not None for item in captured["sessions"]))
        self.assertTrue(all(item["session_password"] for item in captured["sessions"]))

    def test_postgres_reminder_tick_claims_before_dispatch_without_sqlite(self):
        scheduled_at = datetime.now(FRANCE_TZ) + timedelta(minutes=2)
        claims = []
        dispatched = []

        def claim(session_id, reminder_type, *, claimed_at):
            claims.append((session_id, reminder_type, claimed_at))
            return True

        def dispatch(payload):
            dispatched.append(payload["type"])
            return True, None

        with (
            patch.object(service.schedule_repo, "schedule_store_is_postgres", lambda: True),
            patch.object(
                service.schedule_repo,
                "list_due_reminder_sessions",
                return_value=[{
                    "id": 9,
                    "platform_id": 12,
                    "session_index": 1,
                    "scheduled_at": scheduled_at,
                    "reminder_previous_evening_sent_at": None,
                    "reminder_5min_sent_at": None,
                    "session_password": "ABC123",
                }],
            ),
            patch.object(
                service.schedule_repo,
                "list_course_reminder_recipients",
                return_value=[{"email": "eleve@example.com", "nom": "", "prenom": ""}],
            ),
            patch.object(
                service.schedule_repo,
                "get_platform_class_identity",
                return_value={"platform_slug": "classe-test", "center_slug": "centre-test"},
            ),
            patch.object(service.schedule_repo, "claim_course_reminder", side_effect=claim),
            patch.object(service.schedule_repo, "complete_course_reminder", return_value=True),
            patch.object(service, "_dispatch_reminder", side_effect=dispatch),
            patch.object(
                service,
                "get_db_connection",
                side_effect=AssertionError("SQLite must not be opened"),
            ),
        ):
            results = service.process_due_reminders(base_url="https://example.test")

        self.assertEqual({item["type"] for item in results}, {"previous_evening", "five_minutes_before"})
        self.assertEqual(set(dispatched), {"previous_evening", "five_minutes_before"})
        self.assertEqual({item[1] for item in claims}, {"previous_evening", "five_minutes_before"})
        self.assertTrue(all(item[2].tzinfo is not None for item in claims))

    def test_reminder_claim_is_a_lease_and_sent_timestamp_is_written_after_success(self):
        db_path = _make_schedule_db()
        try:
            claimed_at = datetime.now(FRANCE_TZ)
            with (
                patch.object(repo, "schedule_store_is_postgres", lambda: False),
                patch.object(repo, "get_db_connection", side_effect=lambda: sqlite3.connect(db_path)),
            ):
                self.assertTrue(repo.claim_course_reminder(
                    9,
                    "previous_evening",
                    claimed_at=claimed_at,
                    lease_seconds=900,
                ))
                self.assertFalse(repo.claim_course_reminder(
                    9,
                    "previous_evening",
                    claimed_at=claimed_at + timedelta(minutes=1),
                    lease_seconds=900,
                ))

                conn = sqlite3.connect(db_path)
                row = conn.execute(
                    """
                    SELECT reminder_previous_evening_sent_at,
                           reminder_previous_evening_claimed_at
                    FROM course_sessions WHERE id = 9
                    """
                ).fetchone()
                conn.close()
                self.assertIsNone(row[0])
                self.assertIsNotNone(row[1])

                self.assertTrue(repo.complete_course_reminder(
                    9,
                    "previous_evening",
                    claimed_at=claimed_at,
                    sent_at=claimed_at + timedelta(minutes=2),
                ))

            conn = sqlite3.connect(db_path)
            sent_at, active_claim = conn.execute(
                """
                SELECT reminder_previous_evening_sent_at,
                       reminder_previous_evening_claimed_at
                FROM course_sessions WHERE id = 9
                """
            ).fetchone()
            conn.close()
            self.assertIsNotNone(sent_at)
            self.assertIsNone(active_claim)
        finally:
            os.unlink(db_path)


if __name__ == "__main__":
    unittest.main()
