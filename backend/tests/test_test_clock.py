from datetime import datetime, timedelta
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from config import FRANCE_TZ
from repositories import course_schedule_repository
from repositories import test_clock_repository
from services import course_schedule_service, time_service


class TestClockTest(unittest.TestCase):
    def setUp(self):
        self.simulated_anchor = FRANCE_TZ.localize(datetime(2026, 9, 4, 8, 30))
        self.real_anchor = FRANCE_TZ.localize(datetime(2026, 8, 30, 14, 0))

    def test_platform_clock_advances_from_durable_center_anchor(self):
        observed_real_time = self.real_anchor + timedelta(minutes=7)
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return observed_real_time

        with (
            patch("repositories.test_clock_repository.get_platform_center_account_id", return_value=12),
            patch(
                "repositories.test_clock_repository.get_center_test_clock",
                return_value={
                    "simulated_anchor": self.simulated_anchor,
                    "real_anchor": self.real_anchor,
                },
            ),
            patch("services.time_service.datetime", FixedDateTime),
        ):
            result = time_service.get_current_simulated_time(42)

        self.assertEqual(result, self.simulated_anchor + timedelta(minutes=7))

    def test_empty_platform_scope_never_falls_back_to_all_platforms(self):
        with (
            patch.object(course_schedule_service.schedule_repo, "schedule_store_is_postgres", return_value=True),
            patch.object(course_schedule_service.schedule_repo, "list_schedule_platform_ids") as list_all,
        ):
            result = course_schedule_service.run_scheduler_tick(platform_ids=[])

        self.assertEqual(result, [])
        list_all.assert_not_called()

    def test_empty_reminder_scope_is_a_noop(self):
        with patch.object(course_schedule_service, "get_db_connection") as connect:
            result = course_schedule_service.process_due_reminders(platform_ids=[])
        self.assertEqual(result, [])
        connect.assert_not_called()

    def test_clock_worker_keeps_anchor_as_reminder_lower_bound(self):
        observed_real_time = self.real_anchor + timedelta(minutes=7)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return observed_real_time

        with (
            patch(
                "repositories.test_clock_repository.list_authorized_active_test_clocks",
                return_value=[{
                    "center_account_id": 12,
                    "simulated_anchor": self.simulated_anchor,
                    "real_anchor": self.real_anchor,
                }],
            ),
            patch(
                "repositories.test_clock_repository.list_center_platform_ids",
                return_value=[42],
            ),
            patch("services.course_schedule_service.datetime", FixedDateTime),
            patch.object(
                course_schedule_service,
                "process_due_reminders",
                return_value=[],
            ) as process,
        ):
            course_schedule_service.process_due_test_clock_reminders()

        self.assertEqual(process.call_args.kwargs["platform_ids"], [42])
        self.assertEqual(
            process.call_args.kwargs["due_not_before"],
            self.simulated_anchor,
        )
        self.assertEqual(
            process.call_args.kwargs["now"],
            self.simulated_anchor + timedelta(minutes=7),
        )

    def test_rewinding_clock_restores_future_session_and_delivery(self):
        handle, db_path = tempfile.mkstemp()
        os.close(handle)
        try:
            conn = sqlite3.connect(db_path)
            course_schedule_service.ensure_course_schedule_tables(conn.cursor())
            conn.execute(
                """
                INSERT INTO course_sessions (
                    id, platform_id, session_index, scheduled_at, status,
                    activated_at, completed_at, created_at, updated_at
                ) VALUES (1, 20, 1, '2026-09-01 08:00:00', 'active',
                          '2026-09-01 08:00:00', NULL,
                          '2026-09-01 08:00:00', '2026-09-01 08:00:00')
                """
            )
            conn.execute(
                "INSERT INTO course_reminder_recipients (id, platform_id, email, created_at) VALUES (1, 20, 'clock@example.test', '2026-09-01 07:00:00')"
            )
            conn.execute(
                """
                INSERT INTO course_reminder_rules (
                    id, platform_id, system_key, name, trigger_mode, minutes_before,
                    subject_template, content_template, recipient_scope,
                    is_active, created_at, updated_at
                ) VALUES (1, 20, 'five_minutes_before', '5 minutes',
                          'relative_minutes', 5, 'Rappel', 'Cours', 'all', 1,
                          '2026-09-01 07:00:00', '2026-09-01 07:00:00')
                """
            )
            conn.execute(
                """
                INSERT INTO course_reminder_deliveries (
                    platform_id, session_id, rule_id, recipient_id, recipient_hash,
                    due_at, status, created_at, updated_at
                ) VALUES (20, 1, 1, 1, 'hash', '2026-09-01 07:55:00',
                          'sent', '2026-09-01 07:55:00', '2026-09-01 07:55:00')
                """
            )
            conn.commit()
            conn.close()

            with (
                patch.object(test_clock_repository, "postgres_enabled", return_value=False),
                patch.object(test_clock_repository, "list_center_platform_ids", return_value=[20]),
                patch.object(
                    test_clock_repository,
                    "get_db_connection",
                    side_effect=lambda: sqlite3.connect(db_path),
                ),
            ):
                result = test_clock_repository.reset_center_test_state(
                    12,
                    FRANCE_TZ.localize(datetime(2026, 9, 1, 7, 54)),
                )

            conn = sqlite3.connect(db_path)
            session = conn.execute(
                "SELECT status, activated_at, completed_at FROM course_sessions WHERE id = 1"
            ).fetchone()
            delivery_count = conn.execute(
                "SELECT COUNT(*) FROM course_reminder_deliveries"
            ).fetchone()[0]
            conn.close()
            self.assertEqual(session, ("planned", None, None))
            self.assertEqual(delivery_count, 0)
            self.assertEqual(result["delivery_count"], 1)
        finally:
            os.unlink(db_path)

    def test_failed_reminder_retry_stays_on_the_simulated_clock(self):
        claimed_at = FRANCE_TZ.localize(datetime(2026, 8, 30, 8, 10))
        handle, db_path = tempfile.mkstemp()
        os.close(handle)
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE course_reminder_deliveries (
                    id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL,
                    claimed_at TEXT,
                    lease_expires_at TEXT,
                    attempts INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    next_retry_at TEXT,
                    last_error TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO course_reminder_deliveries (
                    id, status, claimed_at, attempts, max_attempts
                ) VALUES (1, 'claimed', '2026-08-30 08:10:00', 1, 5)
                """
            )
            conn.commit()
            conn.close()

            with (
                patch.object(
                    course_schedule_repository,
                    "schedule_store_is_postgres",
                    return_value=False,
                ),
                patch.object(
                    course_schedule_repository,
                    "get_db_connection",
                    side_effect=lambda: sqlite3.connect(db_path),
                ),
            ):
                released = course_schedule_repository.release_course_reminder_delivery(
                    1,
                    claimed_at=claimed_at,
                    error="SMTP indisponible",
                    retry_clock=claimed_at,
                )

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT status, next_retry_at FROM course_reminder_deliveries WHERE id = 1"
            ).fetchone()
            conn.close()
            self.assertTrue(released)
            self.assertEqual(row, ("retry_scheduled", "2026-08-30 08:11:00"))
        finally:
            os.unlink(db_path)


if __name__ == "__main__":
    unittest.main()
