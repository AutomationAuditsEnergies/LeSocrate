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
from services import course_schedule_service as css
from services.course_schedule_service import (
    create_missing_course_schedule,
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
    cursor.execute(
        """
        CREATE TABLE platform_config (
            id INTEGER PRIMARY KEY,
            slug TEXT,
            center_account_id INTEGER
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE training_center_accounts (
            id INTEGER PRIMARY KEY,
            slug TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE student_profiles (
            id INTEGER PRIMARY KEY,
            platform_id INTEGER,
            email TEXT,
            nom TEXT,
            prenom TEXT,
            is_active INTEGER DEFAULT 1
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE student_accounts (
            id INTEGER PRIMARY KEY,
            platform_id INTEGER,
            username TEXT,
            nom TEXT,
            prenom TEXT,
            is_active INTEGER DEFAULT 1
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE course_reminder_recipients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL,
            email TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(platform_id, email)
        )
        """
    )
    cursor.execute("INSERT INTO platform_config (id, slug, center_account_id) VALUES (12, 'classe-test', NULL)")
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
    def test_create_missing_course_schedule_from_existing_pipeline_days(self):
        conn = _connect()
        cursor = conn.cursor()
        first_day = datetime.now(FRANCE_TZ) + timedelta(days=3)

        result = create_missing_course_schedule(
            cursor,
            12,
            total_training_days=2,
            start_time="10:30",
            date_str=first_day.strftime("%Y-%m-%d"),
        )

        self.assertEqual(result["total_sessions"], 2)
        self.assertEqual(result["total_training_days"], 2)
        self.assertEqual(result["weekly_course_count"], 1)
        self.assertEqual(result["weekdays"], [first_day.weekday()])
        cursor.execute("SELECT COUNT(*) FROM course_sessions WHERE platform_id = ?", (12,))
        self.assertEqual(cursor.fetchone()[0], 2)
        cursor.execute("SELECT heure_debut FROM cours_config WHERE platform_id = ?", (12,))
        self.assertIsNotNone(cursor.fetchone())
        conn.close()

    def test_save_course_schedule_generates_session_passwords(self):
        conn = _connect()
        cursor = conn.cursor()
        base = datetime.now(FRANCE_TZ) + timedelta(days=3)
        save_course_schedule(
            cursor,
            12,
            {
                "total_training_days": 2,
                "weekly_course_count": 1,
                "weekdays": [base.weekday()],
                "start_time": "10:00",
                "start_date": base.strftime("%Y-%m-%d"),
            },
        )

        cursor.execute("SELECT session_password FROM course_sessions WHERE platform_id = 12 ORDER BY session_index")
        passwords = [row[0] for row in cursor.fetchall()]

        self.assertEqual(len(passwords), 2)
        self.assertTrue(all(password and len(password) == 6 for password in passwords))
        self.assertEqual(len(set(passwords)), 2)
        conn.close()

    def test_due_reminder_payload_includes_session_password(self):
        conn = _connect()
        cursor = conn.cursor()
        _seed_schedule(cursor)
        scheduled_at = (datetime.now(FRANCE_TZ) + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "UPDATE course_sessions SET scheduled_at = ? WHERE platform_id = ?",
            (scheduled_at, 12),
        )
        cursor.execute(
            "INSERT INTO course_reminder_recipients (platform_id, email, created_at) VALUES (?, ?, ?)",
            (12, "eleve@example.com", datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")),
        )

        with patch.object(css, "get_db_connection", lambda: conn):
            results = css.process_due_reminders(base_url="https://example.test", dry_run=True)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["type"], "previous_evening")
        self.assertTrue(results[0]["session_password"])
        self.assertEqual(results[0]["recipients"][0]["email"], "eleve@example.com")

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

    def test_update_rejects_new_next_session_inside_audio_preparation_window(self):
        conn = _connect()
        cursor = conn.cursor()
        _seed_schedule(cursor)
        future_at = (datetime.now(FRANCE_TZ) + timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "UPDATE course_sessions SET scheduled_at = ? WHERE platform_id = ?",
            (future_at, 12),
        )

        due_soon = datetime.now(FRANCE_TZ) + timedelta(hours=12)
        with patch.dict("os.environ", {"SCHEDULED_AUDIO_HORIZON_HOURS": "24"}):
            with self.assertRaisesRegex(ValueError, "Planning refusé"):
                update_course_schedule(
                    cursor,
                    12,
                    start_time=due_soon.strftime("%H:%M"),
                    weekdays=[due_soon.weekday()],
                )
        conn.close()

    def test_admin_override_accepts_next_session_inside_audio_preparation_window(self):
        conn = _connect()
        cursor = conn.cursor()
        _seed_schedule(cursor)
        due_soon = datetime.now(FRANCE_TZ) + timedelta(hours=12)

        result = update_course_schedule(
            cursor,
            12,
            start_time=due_soon.strftime("%H:%M"),
            weekdays=[due_soon.weekday()],
            allow_imminent=True,
        )

        self.assertEqual(result["weekdays"], [due_soon.weekday()])
        self.assertEqual(result["start_time"], due_soon.strftime("%H:%M"))
        conn.close()


if __name__ == "__main__":
    unittest.main()
