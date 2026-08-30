from datetime import datetime, timedelta
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from config import FRANCE_TZ
from repositories import course_schedule_repository
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
