from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

from config import FRANCE_TZ
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


if __name__ == "__main__":
    unittest.main()
