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
            audio_storage_prefix TEXT,
            postponed_from TEXT,
            postponed_at TEXT,
            postponement_count INTEGER NOT NULL DEFAULT 0,
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
        CREATE TABLE course_session_postponements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL,
            session_id INTEGER NOT NULL,
            session_index INTEGER NOT NULL,
            previous_scheduled_at TEXT NOT NULL,
            new_scheduled_at TEXT NOT NULL,
            mode TEXT NOT NULL,
            reason TEXT,
            affected_session_count INTEGER NOT NULL DEFAULT 1,
            idempotency_key TEXT,
            actor_account_id INTEGER,
            impact_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            UNIQUE(platform_id, idempotency_key)
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

    def test_materialized_delivery_resolves_recipient_and_is_not_reclaimed_after_success(self):
        db_path = _make_schedule_db()
        try:
            now = datetime.now(FRANCE_TZ)
            with (
                patch.object(repo, "schedule_store_is_postgres", lambda: False),
                patch.object(repo, "get_db_connection", side_effect=lambda: sqlite3.connect(db_path)),
            ):
                recipients = repo.add_explicit_course_reminder_recipients(
                    12,
                    ["eleve@example.test"],
                    created_at=now,
                )
                repo.ensure_default_course_reminder_rules(12, now=now)
                rule = repo.list_course_reminder_rules(12)[0]
                delivery_id = repo.claim_course_reminder_delivery(
                    platform_id=12,
                    session_id=9,
                    rule_id=rule["id"],
                    recipient_id=recipients[0]["id"],
                    recipient_hash="a" * 64,
                    due_at=now,
                    claimed_at=now,
                    lease_seconds=900,
                    max_attempts=3,
                )

                self.assertIsNotNone(delivery_id)
                resolved = repo.get_course_reminder_delivery_recipient(delivery_id)
                self.assertEqual(resolved["email"], "eleve@example.test")
                self.assertTrue(repo.complete_course_reminder_delivery(
                    delivery_id,
                    claimed_at=now,
                    sent_at=now + timedelta(seconds=1),
                ))
                self.assertIsNone(repo.claim_course_reminder_delivery(
                    platform_id=12,
                    session_id=9,
                    rule_id=rule["id"],
                    recipient_id=recipients[0]["id"],
                    recipient_hash="a" * 64,
                    due_at=now,
                    claimed_at=now + timedelta(hours=1),
                    lease_seconds=900,
                    max_attempts=3,
                ))
        finally:
            os.unlink(db_path)

    def test_repository_rejects_oversized_recipient_batch_before_database_access(self):
        with patch.object(
            repo,
            "get_db_connection",
            side_effect=AssertionError("database must not be opened"),
        ), self.assertRaisesRegex(ValueError, "1000 emails maximum"):
            repo.add_explicit_course_reminder_recipients(
                12,
                [f"eleve{index}@example.test" for index in range(1001)],
                created_at=datetime.now(FRANCE_TZ),
            )

    def test_due_delivery_query_does_not_starve_j365_behind_500_nearer_sessions(self):
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        service.ensure_course_schedule_tables(cursor)
        now = FRANCE_TZ.localize(datetime(2026, 1, 1, 12, 0))
        created = now.strftime("%Y-%m-%d %H:%M:%S")
        near_at = (now + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        far_at = (now + timedelta(days=300)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.executemany(
            """
            INSERT INTO course_sessions (
                platform_id, session_index, scheduled_at, status, session_password,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'planned', 'CODE1234', ?, ?)
            """,
            [(1, index, near_at, created, created) for index in range(1, 501)]
            + [(2, 1, far_at, created, created)],
        )
        cursor.executemany(
            "INSERT INTO course_reminder_recipients (platform_id, email, created_at) VALUES (?, ?, ?)",
            [(1, "near@example.test", created), (2, "far@example.test", created)],
        )
        cursor.executemany(
            """
            INSERT INTO course_reminder_rules (
                platform_id, name, trigger_mode, days_before, local_time,
                subject_template, content_template, recipient_scope,
                is_active, created_at, updated_at
            ) VALUES (?, ?, 'local_day_time', ?, '09:00', 'Rappel', 'Cours {date}', 'all', 1, ?, ?)
            """,
            [
                (1, "J-1", 1, created, created),
                (2, "J-365", 365, created, created),
            ],
        )

        with patch.object(repo, "schedule_store_is_postgres", lambda: False):
            rows = repo.list_due_reminder_delivery_candidates(
                now=now,
                active_hours=12,
                limit=10,
                sqlite_cursor=cursor,
            )

        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["platform_id"], 2)
        self.assertEqual(rows[0]["rule_name"], "J-365")

    def test_relative_reminder_is_never_candidate_after_course_has_started(self):
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        service.ensure_course_schedule_tables(cursor)
        now = FRANCE_TZ.localize(datetime(2026, 1, 1, 9, 2))
        scheduled_at = (now - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")
        created = now.strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            """
            INSERT INTO course_sessions (
                platform_id, session_index, scheduled_at, status, session_password,
                created_at, updated_at
            ) VALUES (1, 1, ?, 'active', 'CODE1234', ?, ?)
            """,
            (scheduled_at, created, created),
        )
        cursor.execute(
            "INSERT INTO course_reminder_recipients (platform_id, email, created_at) VALUES (1, 'late@example.test', ?)",
            (created,),
        )
        cursor.execute(
            """
            INSERT INTO course_reminder_rules (
                platform_id, name, trigger_mode, minutes_before,
                subject_template, content_template, recipient_scope,
                is_active, created_at, updated_at
            ) VALUES (1, '5 minutes', 'relative_minutes', 5, 'Rappel', 'Cours', 'all', 1, ?, ?)
            """,
            (created, created),
        )

        with patch.object(repo, "schedule_store_is_postgres", lambda: False):
            rows = repo.list_due_reminder_delivery_candidates(
                now=now,
                active_hours=12,
                limit=10,
                sqlite_cursor=cursor,
            )

        conn.close()
        self.assertEqual(rows, [])

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
                       audio_storage_prefix,
                       audio_generation_completed_at, audio_generation_error
                FROM course_sessions WHERE id = 9
                """
            ).fetchone()
            conn.close()
            self.assertEqual(row[0], "completed")
            self.assertEqual(row[1:3], (41, 55))
            self.assertEqual(row[3], "course-sessions/9")
            self.assertIsNotNone(row[4])
            self.assertIsNone(row[5])
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

    def test_scheduled_audio_readiness_requires_every_non_cancelled_day(self):
        db_path = _make_schedule_db()
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                UPDATE course_sessions
                SET audio_generation_status = 'completed',
                    audio_generation_completed_at = '2026-07-10 08:30:00',
                    audio_job_id = 41, audio_folder_id = 55
                WHERE id = 9
                """
            )
            conn.execute(
                """
                INSERT INTO course_sessions (
                    id, platform_id, session_index, scheduled_at, status,
                    created_at, updated_at
                ) VALUES (10, 12, 2, '2026-07-18 09:00:00', 'planned',
                          '2026-07-10 09:00:00', '2026-07-10 09:00:00')
                """
            )
            conn.commit()
            conn.close()

            with (
                patch.object(repo, "schedule_store_is_postgres", lambda: False),
                patch.object(repo, "get_db_connection", side_effect=lambda: sqlite3.connect(db_path)),
            ):
                pending = repo.get_scheduled_audio_completion_readiness(
                    12, 41, required_session_count=2
                )

            self.assertFalse(pending["ready"])
            self.assertEqual(pending["completed_count"], 1)

            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                UPDATE course_sessions
                SET audio_generation_status = 'running',
                    audio_generation_started_at = '2026-07-17 08:00:00',
                    audio_job_id = 41, audio_folder_id = 56
                WHERE id = 10
                """
            )
            conn.commit()
            conn.close()
            with (
                patch.object(repo, "schedule_store_is_postgres", lambda: False),
                patch.object(repo, "get_db_connection", side_effect=lambda: sqlite3.connect(db_path)),
            ):
                completing = repo.get_scheduled_audio_completion_readiness(
                    12, 41, required_session_count=2, completing_session_id=10
                )
            self.assertTrue(completing["ready"])

            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                UPDATE course_sessions
                SET audio_generation_status = 'completed',
                    audio_generation_completed_at = '2026-07-17 08:30:00',
                    audio_job_id = 41, audio_folder_id = 56
                WHERE id = 10
                """
            )
            conn.commit()
            conn.close()
            with (
                patch.object(repo, "schedule_store_is_postgres", lambda: False),
                patch.object(repo, "get_db_connection", side_effect=lambda: sqlite3.connect(db_path)),
            ):
                ready = repo.get_scheduled_audio_completion_readiness(
                    12, 41, required_session_count=2
                )

            self.assertTrue(ready["ready"])
            self.assertEqual(ready["remaining_count"], 0)
        finally:
            os.unlink(db_path)

    def test_postponement_keeps_lesson_audio_and_is_idempotent(self):
        db_path = _make_schedule_db()
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                UPDATE course_sessions
                SET audio_generation_status = 'completed',
                    audio_generation_started_at = '2026-07-10 08:00:00',
                    audio_generation_completed_at = '2026-07-10 08:30:00',
                    audio_job_id = 41, audio_folder_id = 55,
                    reminder_previous_evening_sent_at = '2026-07-10 18:00:00'
                WHERE id = 9
                """
            )
            conn.execute(
                """
                INSERT INTO course_sessions (
                    id, platform_id, session_index, scheduled_at, status,
                    created_at, updated_at
                ) VALUES (10, 12, 2, '2026-07-18 09:00:00', 'planned',
                          '2026-07-10 09:00:00', '2026-07-10 09:00:00')
                """
            )
            conn.commit()
            conn.close()
            now = FRANCE_TZ.localize(datetime(2026, 7, 10, 12, 0))
            changes = [
                {
                    "id": 9,
                    "session_index": 1,
                    "expected_scheduled_at": FRANCE_TZ.localize(datetime(2026, 7, 11, 9, 0)),
                    "new_scheduled_at": FRANCE_TZ.localize(datetime(2026, 7, 18, 9, 0)),
                },
                {
                    "id": 10,
                    "session_index": 2,
                    "expected_scheduled_at": FRANCE_TZ.localize(datetime(2026, 7, 18, 9, 0)),
                    "new_scheduled_at": FRANCE_TZ.localize(datetime(2026, 7, 25, 9, 0)),
                },
            ]
            with (
                patch.object(repo, "schedule_store_is_postgres", lambda: False),
                patch.object(repo, "get_db_connection", side_effect=lambda: sqlite3.connect(db_path)),
            ):
                first = repo.apply_course_session_postponement(
                    12,
                    9,
                    changes=changes,
                    mode="next_occurrence",
                    reason="Formateur indisponible",
                    idempotency_key="report-unique-1",
                    actor_account_id=3,
                    postponed_at=now,
                )
                second = repo.apply_course_session_postponement(
                    12,
                    9,
                    changes=changes,
                    mode="next_occurrence",
                    reason="Formateur indisponible",
                    idempotency_key="report-unique-1",
                    actor_account_id=3,
                    postponed_at=now,
                )

            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                """
                SELECT session_index, scheduled_at, status, audio_generation_status,
                       audio_job_id, audio_folder_id, reminder_previous_evening_sent_at,
                       postponement_count
                FROM course_sessions WHERE platform_id = 12 ORDER BY session_index
                """
            ).fetchall()
            audit_count = conn.execute("SELECT COUNT(*) FROM course_session_postponements").fetchone()[0]
            conn.close()

            self.assertFalse(first["idempotent"])
            self.assertTrue(second["idempotent"])
            self.assertEqual(audit_count, 1)
            self.assertEqual(rows[0][0:3], (1, "2026-07-18 09:00:00", "planned"))
            self.assertEqual(rows[0][3:6], ("completed", 41, 55))
            self.assertIsNone(rows[0][6])
            self.assertEqual(rows[0][7], 1)
            self.assertEqual(rows[1][0:3], (2, "2026-07-25 09:00:00", "planned"))
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

    def test_postgres_postponement_is_locked_and_preserves_audio_columns(self):
        executed = []
        old_j2 = FRANCE_TZ.localize(datetime(2026, 7, 20, 9, 0))
        old_j3 = FRANCE_TZ.localize(datetime(2026, 7, 23, 9, 0))
        new_j2 = old_j3
        new_j3 = FRANCE_TZ.localize(datetime(2026, 7, 27, 9, 0))

        class FakeCursor:
            rowcount = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, params=None):
                self.query = query
                self.params = params
                executed.append((query, params))
                self.rowcount = 1 if "UPDATE course_sessions" in query else 0

            def fetchone(self):
                if "idempotency_key = %s" in self.query:
                    return None
                if "ORDER BY scheduled_at ASC" in self.query:
                    return {"scheduled_at": new_j2}
                if "RETURNING id" in self.query:
                    return {"id": 77}
                return None

            def fetchall(self):
                if "id = ANY" in self.query:
                    return [
                        {"id": 22, "session_index": 2, "scheduled_at": old_j2, "status": "planned"},
                        {"id": 23, "session_index": 3, "scheduled_at": old_j3, "status": "planned"},
                    ]
                return []

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
            patch.object(repo, "get_db_connection", side_effect=AssertionError("SQLite must not be opened")),
        ):
            result = repo.apply_course_session_postponement(
                12,
                22,
                changes=[
                    {"id": 22, "session_index": 2, "expected_scheduled_at": old_j2, "new_scheduled_at": new_j2},
                    {"id": 23, "session_index": 3, "expected_scheduled_at": old_j3, "new_scheduled_at": new_j3},
                ],
                mode="next_occurrence",
                reason=None,
                idempotency_key="pg-report",
                actor_account_id=42,
                postponed_at=FRANCE_TZ.localize(datetime(2026, 7, 16, 10, 0)),
            )

        update_sql = [query for query, _params in executed if "UPDATE course_sessions" in query]
        self.assertEqual(len(update_sql), 2)
        self.assertTrue(any("pg_advisory_xact_lock" in query for query, _params in executed))
        self.assertTrue(all("audio_generation" not in query for query in update_sql))
        self.assertTrue(all("reminder_previous_evening_sent_at = NULL" in query for query in update_sql))
        self.assertEqual(result["audit_id"], 77)
        self.assertFalse(result["idempotent"])

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
                    "start_time": "09:00",
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
        dispatched_payloads = []

        def claim(**kwargs):
            claims.append(kwargs)
            return len(claims)

        def dispatch(payloads):
            dispatched_payloads.extend(payloads)
            dispatched.extend(payload["type"] for payload in payloads)
            return {int(payload["delivery_id"]): (True, None) for payload in payloads}

        rules = [
            {
                "id": 1,
                "platform_id": 12,
                "system_key": "previous_evening",
                "name": "La veille",
                "trigger_mode": "local_day_time",
                "days_before": 1,
                "minutes_before": None,
                "local_time": "18:00",
                "subject_template": "Demain",
                "content_template": "Cours le {date} à {time}",
                "recipient_scope": "all",
                "recipient_ids": [],
                "is_active": True,
            },
            {
                "id": 2,
                "platform_id": 12,
                "system_key": "five_minutes_before",
                "name": "5 minutes",
                "trigger_mode": "relative_minutes",
                "days_before": None,
                "minutes_before": 5,
                "local_time": None,
                "subject_template": "Dans 5 minutes",
                "content_template": "Cours à {time}",
                "recipient_scope": "all",
                "recipient_ids": [],
                "is_active": True,
            },
        ]

        with (
            patch.dict("os.environ", {
                "WEBSITE_SITE_NAME": "Formation3",
                "PLATFORM_1_FRONTEND_URL": "https://example.test",
            }),
            patch.object(service.schedule_repo, "schedule_store_is_postgres", lambda: True),
            patch.object(
                service.schedule_repo,
                "ensure_default_course_reminder_rules_for_schedules",
            ) as seed_default_rules,
            patch.object(
                service.schedule_repo,
                "list_due_reminder_delivery_candidates",
                return_value=[
                    {
                        "session_id": 9,
                        "platform_id": 12,
                        "session_index": 1,
                        "scheduled_at": scheduled_at,
                        "session_password": "ABC123",
                        "rule_id": rule["id"],
                        "system_key": rule["system_key"],
                        "subject_template": rule["subject_template"],
                        "content_template": rule["content_template"],
                        "recipient_id": 4,
                        "email": "eleve@example.com",
                        "due_at": scheduled_at - (
                            timedelta(days=1)
                            if rule["system_key"] == "previous_evening"
                            else timedelta(minutes=5)
                        ),
                    }
                    for rule in rules
                ],
            ),
            patch.object(
                service.schedule_repo,
                "get_platform_class_identity",
                return_value={"platform_slug": "classe-test", "center_slug": "centre-test"},
            ),
            patch.object(service.schedule_repo, "claim_course_reminder_delivery", side_effect=claim),
            patch.object(service.schedule_repo, "complete_course_reminder_delivery", return_value=True),
            patch.object(service, "_dispatch_reminder_batch", side_effect=dispatch),
            patch.object(
                service,
                "get_db_connection",
                side_effect=AssertionError("SQLite must not be opened"),
            ),
        ):
            results = service.process_due_reminders()

        self.assertEqual({item["type"] for item in results}, {"previous_evening", "five_minutes_before"})
        self.assertEqual(set(dispatched), {"previous_evening", "five_minutes_before"})
        self.assertEqual({item["rule_id"] for item in claims}, {1, 2})
        self.assertTrue(all(item["claimed_at"].tzinfo is not None for item in claims))
        self.assertTrue(all(item["recipient_id"] == 4 for item in claims))
        self.assertTrue(all(item["class_url"].startswith("https://example.test/classe/") for item in results))
        self.assertTrue(all(item["class_url"].startswith("https://example.test/classe/") for item in dispatched_payloads))
        self.assertTrue(all("invite=" in item["class_url"] for item in dispatched_payloads))
        self.assertTrue(all("{time}" not in item["content"] for item in dispatched_payloads))
        self.assertTrue(all(scheduled_at.strftime("%H:%M") in item["content"] for item in dispatched_payloads))
        seed_default_rules.assert_called_once()

    def test_partial_reminder_batch_does_not_resend_successful_recipient(self):
        scheduled_at = datetime.now(FRANCE_TZ) + timedelta(minutes=2)
        base_candidate = {
            "session_id": 9,
            "platform_id": 12,
            "session_index": 1,
            "scheduled_at": scheduled_at,
            "session_password": "ABC123",
            "rule_id": 2,
            "system_key": "five_minutes_before",
            "subject_template": "Dans 5 minutes",
            "content_template": "Cours à {time}",
            "due_at": scheduled_at - timedelta(minutes=5),
        }
        candidates = [
            {**base_candidate, "recipient_id": 4, "email": "ok@example.test"},
            {**base_candidate, "recipient_id": 5, "email": "retry@example.test"},
        ]
        dispatched_recipient_batches = []

        def dispatch(payloads):
            dispatched_recipient_batches.append([
                payload["recipient"]["email"] for payload in payloads
            ])
            if len(dispatched_recipient_batches) == 1:
                return {101: (True, None), 102: (False, "temporaire")}
            return {102: (True, None)}

        with (
            patch.dict("os.environ", {
                "WEBSITE_SITE_NAME": "Formation3",
                "PLATFORM_1_FRONTEND_URL": "https://example.test",
            }),
            patch.object(service.schedule_repo, "schedule_store_is_postgres", lambda: True),
            patch.object(
                service.schedule_repo,
                "ensure_default_course_reminder_rules_for_schedules",
            ),
            patch.object(
                service.schedule_repo,
                "list_due_reminder_delivery_candidates",
                side_effect=[candidates, [candidates[1]]],
            ),
            patch.object(
                service.schedule_repo,
                "get_platform_class_identity",
                return_value={"platform_slug": "classe-test", "center_slug": "centre-test"},
            ),
            patch.object(
                service.schedule_repo,
                "claim_course_reminder_delivery",
                side_effect=lambda **kwargs: {4: 101, 5: 102}[kwargs["recipient_id"]],
            ),
            patch.object(
                service.schedule_repo,
                "complete_course_reminder_delivery",
                return_value=True,
            ) as complete_delivery,
            patch.object(
                service.schedule_repo,
                "release_course_reminder_delivery",
                return_value=True,
            ) as release_delivery,
            patch.object(service, "_dispatch_reminder_batch", side_effect=dispatch),
            patch.object(
                service,
                "get_db_connection",
                side_effect=AssertionError("SQLite must not be opened"),
            ),
        ):
            first_results = service.process_due_reminders()
            second_results = service.process_due_reminders()

        self.assertEqual(
            dispatched_recipient_batches,
            [["ok@example.test", "retry@example.test"], ["retry@example.test"]],
        )
        self.assertEqual([item["success"] for item in first_results], [True, False])
        self.assertEqual([item["success"] for item in second_results], [True])
        self.assertEqual(
            [call.args[0] for call in complete_delivery.call_args_list],
            [101, 102],
        )
        release_delivery.assert_called_once()
        self.assertEqual(release_delivery.call_args.args[0], 102)

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
