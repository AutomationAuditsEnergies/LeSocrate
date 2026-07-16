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
    def test_postponing_j2_to_next_slot_keeps_j2_and_shifts_following_lessons(self):
        now = FRANCE_TZ.localize(datetime(2026, 7, 16, 8, 0))
        rows = [
            {
                "id": 22,
                "session_index": 2,
                "scheduled_at": FRANCE_TZ.localize(datetime(2026, 7, 16, 9, 0)),
                "status": "planned",
                "audio_generation_status": "completed",
                "audio_generation_completed_at": now - timedelta(hours=1),
            },
            {
                "id": 23,
                "session_index": 3,
                "scheduled_at": FRANCE_TZ.localize(datetime(2026, 7, 20, 9, 0)),
                "status": "planned",
                "audio_generation_status": "pending",
            },
            {
                "id": 24,
                "session_index": 4,
                "scheduled_at": FRANCE_TZ.localize(datetime(2026, 7, 23, 9, 0)),
                "status": "planned",
                "audio_generation_status": "pending",
            },
        ]
        summary = {
            "weekly_course_count": 2,
            "weekdays": [0, 3],
            "start_time": "09:00",
        }
        with (
            patch.object(css.schedule_repo, "schedule_store_is_postgres", lambda: True),
            patch.object(css, "get_course_schedule_summary", return_value=summary),
            patch.object(css.schedule_repo, "list_course_sessions", return_value=rows),
        ):
            plan = css._build_course_session_postponement_plan(
                12,
                22,
                mode="next_occurrence",
                now=now,
            )

        self.assertEqual(plan["lesson_number"], 2)
        self.assertEqual(plan["audio_preservation"], "ready")
        self.assertEqual(
            [item["lesson_number"] for item in plan["changes"]],
            [2, 3, 4],
        )
        self.assertTrue(plan["changes"][0]["new_scheduled_at"].startswith("2026-07-20T09:00"))
        self.assertTrue(plan["changes"][1]["new_scheduled_at"].startswith("2026-07-23T09:00"))
        self.assertTrue(plan["changes"][2]["new_scheduled_at"].startswith("2026-07-27T09:00"))

    def test_custom_postponement_accepts_exception_date_then_resumes_recurrence(self):
        now = FRANCE_TZ.localize(datetime(2026, 7, 16, 8, 0))
        rows = [
            {"id": 22, "session_index": 2, "scheduled_at": "2026-07-16 09:00:00", "status": "planned"},
            {"id": 23, "session_index": 3, "scheduled_at": "2026-07-20 09:00:00", "status": "planned"},
        ]
        with (
            patch.object(css.schedule_repo, "schedule_store_is_postgres", lambda: True),
            patch.object(css, "get_course_schedule_summary", return_value={
                "weekly_course_count": 2,
                "weekdays": [0, 3],
                "start_time": "09:00",
            }),
            patch.object(css.schedule_repo, "list_course_sessions", return_value=rows),
        ):
            plan = css._build_course_session_postponement_plan(
                12,
                22,
                mode="specific_date",
                scheduled_at="2026-07-17T14:30",
                now=now,
            )

        self.assertTrue(plan["changes"][0]["new_scheduled_at"].startswith("2026-07-17T14:30"))
        self.assertEqual(len(plan["changes"]), 1)

    def test_idempotent_retry_returns_original_report_without_shifting_again(self):
        prior = {
            "id": 7,
            "session_id": 22,
            "session_index": 2,
            "previous_scheduled_at": "2026-07-20 09:00:00",
            "new_scheduled_at": "2026-07-23 09:00:00",
            "mode": "next_occurrence",
            "affected_session_count": 2,
            "impact_json": json.dumps([
                {
                    "id": 22,
                    "session_index": 2,
                    "previous_scheduled_at": "2026-07-20 09:00:00",
                    "new_scheduled_at": "2026-07-23 09:00:00",
                },
                {
                    "id": 23,
                    "session_index": 3,
                    "previous_scheduled_at": "2026-07-23 09:00:00",
                    "new_scheduled_at": "2026-07-27 09:00:00",
                },
            ]),
        }
        with (
            patch.object(css.schedule_repo, "schedule_store_is_postgres", lambda: True),
            patch.object(css.schedule_repo, "get_course_session_postponement_by_key", return_value=prior),
            patch.object(css, "_build_course_session_postponement_plan") as build_plan,
        ):
            result = css.postpone_course_session(
                12,
                22,
                mode="next_occurrence",
                idempotency_key="same-request",
            )

        self.assertTrue(result["idempotent"])
        self.assertEqual(result["lesson_number"], 2)
        self.assertEqual(result["affected_session_count"], 2)
        self.assertTrue(result["new_scheduled_at"].startswith("2026-07-23T09:00"))
        build_plan.assert_not_called()

    def test_public_session_state_exposes_cutoffs_without_internal_error(self):
        now = FRANCE_TZ.localize(datetime(2026, 7, 15, 9, 0))
        scheduled = now + timedelta(days=4)
        state = css.build_course_session_state({
            "id": 9,
            "session_index": 1,
            "scheduled_at": scheduled,
            "status": "planned",
            "audio_generation_status": "error",
            "audio_generation_started_at": now,
            "audio_generation_completed_at": None,
            "audio_generation_attempts": 2,
            "audio_generation_next_retry_at": now + timedelta(minutes=10),
            "audio_generation_error": "secret provider failure",
        }, now=now)

        self.assertEqual(state["audio_status"], "error")
        self.assertTrue(state["can_retry_audio"])
        self.assertTrue(state["can_postpone"])
        self.assertTrue(state["is_locked"])
        self.assertEqual(state["audio_attempts"], 2)
        self.assertNotIn("secret", json.dumps(state))

    def test_dst_nonexistent_and_ambiguous_times_are_rejected(self):
        for start_date, error in (
            ("2027-03-28", "heure d'été"),
            ("2026-10-25", "heure d'hiver"),
        ):
            with self.subTest(start_date=start_date):
                with self.assertRaisesRegex(ValueError, error):
                    css._generate_session_datetimes(
                        1,
                        [6],
                        "02:30",
                        start_date=start_date,
                    )

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

    def test_update_preserves_occurrence_inside_72_hour_cutoff(self):
        conn = _connect()
        cursor = conn.cursor()
        weekday = _seed_schedule(cursor)
        locked_at = (datetime.now(FRANCE_TZ) + timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "UPDATE course_sessions SET scheduled_at = ? WHERE platform_id = ?",
            (locked_at, 12),
        )

        with patch.dict("os.environ", {"COURSE_SCHEDULE_CHANGE_CUTOFF_HOURS": "72"}):
            result = update_course_schedule(cursor, 12, weekdays=[(weekday + 1) % 7])

        cursor.execute("SELECT scheduled_at FROM course_sessions WHERE platform_id = ?", (12,))
        self.assertEqual(cursor.fetchone()[0], locked_at)
        self.assertEqual(result["locked_future_sessions"], 1)
        cursor.execute("SELECT weekdays_json FROM course_schedule_config WHERE platform_id = ?", (12,))
        self.assertEqual(json.loads(cursor.fetchone()[0]), [(weekday + 1) % 7])
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

    def test_update_never_creates_replacement_inside_72_hour_cutoff(self):
        conn = _connect()
        cursor = conn.cursor()
        _seed_schedule(cursor)
        future_at = (datetime.now(FRANCE_TZ) + timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "UPDATE course_sessions SET scheduled_at = ? WHERE platform_id = ?",
            (future_at, 12),
        )

        due_soon = datetime.now(FRANCE_TZ) + timedelta(hours=12)
        with patch.dict("os.environ", {"COURSE_SCHEDULE_CHANGE_CUTOFF_HOURS": "72"}):
            update_course_schedule(
                cursor,
                12,
                start_time=due_soon.strftime("%H:%M"),
                weekdays=[due_soon.weekday()],
            )
        cursor.execute("SELECT scheduled_at FROM course_sessions WHERE platform_id = ?", (12,))
        replacement = FRANCE_TZ.localize(datetime.strptime(cursor.fetchone()[0], "%Y-%m-%d %H:%M:%S"))
        self.assertGreater(replacement, datetime.now(FRANCE_TZ) + timedelta(hours=71))
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
