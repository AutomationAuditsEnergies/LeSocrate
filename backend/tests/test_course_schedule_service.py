import json
import sqlite3
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import FRANCE_TZ
from services.course_schedule_service import (
    ensure_course_schedule_tables,
    save_course_schedule,
    update_course_schedule,
)


def _connect():
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE cours_config (
            id INTEGER PRIMARY KEY,
            heure_debut TEXT NOT NULL,
            platform_id INTEGER
        )
        """
    )
    ensure_course_schedule_tables(cursor)
    return conn


def _seed_schedule(cursor, platform_id=12):
    base = datetime.now(FRANCE_TZ) + timedelta(days=3)
    weekday = base.weekday()
    save_course_schedule(
        cursor,
        platform_id,
        {
            "total_training_days": 1,
            "weekly_course_count": 1,
            "weekdays": [weekday],
            "start_time": "10:00",
            "start_date": base.strftime("%Y-%m-%d"),
        },
    )
    return weekday


class CourseScheduleServiceTest(unittest.TestCase):
    def test_update_is_blocked_inside_audio_preparation_window(self):
        conn = _connect()
        cursor = conn.cursor()
        weekday = _seed_schedule(cursor)
        locked_at = (datetime.now(FRANCE_TZ) + timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "UPDATE course_sessions SET scheduled_at = ? WHERE platform_id = ?",
            (locked_at, 12),
        )

        with patch.dict("os.environ", {"SCHEDULED_AUDIO_HORIZON_HOURS": "24"}):
            with self.assertRaisesRegex(ValueError, "Planning verrouillé"):
                update_course_schedule(cursor, 12, weekdays=[(weekday + 1) % 7])

        cursor.execute("SELECT scheduled_at FROM course_sessions WHERE platform_id = ?", (12,))
        self.assertEqual(cursor.fetchone()[0], locked_at)
        conn.close()

    def test_update_can_change_weekdays_when_next_session_is_not_due_for_audio(self):
        conn = _connect()
        cursor = conn.cursor()
        weekday = _seed_schedule(cursor)
        future_at = (datetime.now(FRANCE_TZ) + timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "UPDATE course_sessions SET scheduled_at = ? WHERE platform_id = ?",
            (future_at, 12),
        )

        new_weekday = (weekday + 1) % 7
        result = update_course_schedule(cursor, 12, weekdays=[new_weekday])

        self.assertEqual(result["weekdays"], [new_weekday])
        cursor.execute("SELECT weekdays_json FROM course_schedule_config WHERE platform_id = ?", (12,))
        self.assertEqual(json.loads(cursor.fetchone()[0]), [new_weekday])
        cursor.execute("SELECT COUNT(*) FROM course_sessions WHERE platform_id = ?", (12,))
        self.assertEqual(cursor.fetchone()[0], 1)
        conn.close()


if __name__ == "__main__":
    unittest.main()
