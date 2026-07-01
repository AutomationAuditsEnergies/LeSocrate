import json
import os
from datetime import datetime, time, timedelta

import requests as http_requests

from config import FRANCE_TZ
from database.db import get_db_connection
from utils.logger import get_logger

logger = get_logger(__name__)

WEEKDAY_IDS = {
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
    "samedi": 5,
    "dimanche": 6,
}


def ensure_course_schedule_tables(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS course_schedule_config (
            platform_id INTEGER PRIMARY KEY,
            total_training_days INTEGER NOT NULL,
            weekly_course_count INTEGER NOT NULL,
            weekdays_json TEXT NOT NULL,
            start_time TEXT NOT NULL DEFAULT '09:00',
            timezone TEXT NOT NULL DEFAULT 'Europe/Paris',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS course_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL,
            session_index INTEGER NOT NULL,
            scheduled_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'planned',
            activated_at TEXT,
            completed_at TEXT,
            reminder_previous_evening_sent_at TEXT,
            reminder_5min_sent_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(platform_id, session_index)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_course_sessions_platform_scheduled ON course_sessions(platform_id, scheduled_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_course_sessions_status_scheduled ON course_sessions(status, scheduled_at)"
    )


def _now_str():
    return datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _parse_start_time(value):
    raw = str(value or "09:00").strip()
    try:
        hour, minute = raw.split(":", 1)
        return time(int(hour), int(minute[:2]))
    except Exception:
        raise ValueError("start_time invalide, format attendu HH:MM")


def _normalize_weekdays(weekdays, weekly_course_count=None):
    result = []
    for item in weekdays or []:
        key = str(item).strip().lower()
        if key in WEEKDAY_IDS:
            result.append(WEEKDAY_IDS[key])
            continue
        try:
            value = int(key)
        except (TypeError, ValueError):
            raise ValueError(f"Jour de cours invalide: {item}")
        if value < 0 or value > 6:
            raise ValueError(f"Jour de cours invalide: {item}")
        result.append(value)

    ordered = sorted(set(result))
    if not ordered:
        raise ValueError("Au moins un jour de cours est requis")
    if weekly_course_count and int(weekly_course_count) != len(ordered):
        raise ValueError("Le nombre de cours par semaine doit correspondre aux jours sélectionnés")
    return ordered


def _generate_session_datetimes(total_training_days, weekdays, start_time, start_date=None):
    total = int(total_training_days)
    if total <= 0:
        raise ValueError("total_training_days doit être positif")

    course_time = _parse_start_time(start_time)
    now = datetime.now(FRANCE_TZ)
    if start_date:
        cursor_date = datetime.strptime(str(start_date), "%Y-%m-%d").date()
    else:
        cursor_date = now.date()

    sessions = []
    max_days = total * 14 + 370
    for _ in range(max_days):
        if cursor_date.weekday() in weekdays:
            scheduled = FRANCE_TZ.localize(datetime.combine(cursor_date, course_time))
            if scheduled > now:
                sessions.append(scheduled)
                if len(sessions) >= total:
                    break
        cursor_date += timedelta(days=1)

    if len(sessions) < total:
        raise ValueError("Impossible de générer toutes les séances demandées")
    return sessions


def save_course_schedule(cursor, platform_id, schedule):
    ensure_course_schedule_tables(cursor)

    schedule = schedule or {}
    total_training_days = int(schedule.get("total_training_days") or 0)
    weekly_course_count = int(schedule.get("weekly_course_count") or 0)
    weekdays = _normalize_weekdays(schedule.get("weekdays"), weekly_course_count)
    start_time = str(schedule.get("start_time") or "09:00").strip()
    start_date = schedule.get("start_date") or None

    sessions = _generate_session_datetimes(
        total_training_days=total_training_days,
        weekdays=weekdays,
        start_time=start_time,
        start_date=start_date,
    )
    now = _now_str()
    weekdays_json = json.dumps(weekdays)

    cursor.execute(
        """
        INSERT INTO course_schedule_config (
            platform_id, total_training_days, weekly_course_count, weekdays_json,
            start_time, timezone, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, 'Europe/Paris', ?, ?)
        ON CONFLICT(platform_id) DO UPDATE SET
            total_training_days = excluded.total_training_days,
            weekly_course_count = excluded.weekly_course_count,
            weekdays_json = excluded.weekdays_json,
            start_time = excluded.start_time,
            timezone = excluded.timezone,
            updated_at = excluded.updated_at
        """,
        (platform_id, total_training_days, weekly_course_count, weekdays_json, start_time, now, now),
    )
    cursor.execute("DELETE FROM course_sessions WHERE platform_id = ?", (platform_id,))
    for index, scheduled in enumerate(sessions, start=1):
        cursor.execute(
            """
            INSERT INTO course_sessions (
                platform_id, session_index, scheduled_at, status, created_at, updated_at
            )
            VALUES (?, ?, ?, 'planned', ?, ?)
            """,
            (platform_id, index, scheduled.strftime("%Y-%m-%d %H:%M:%S"), now, now),
        )
    return {
        "total_sessions": len(sessions),
        "first_session_at": sessions[0].strftime("%Y-%m-%d %H:%M:%S") if sessions else None,
        "last_session_at": sessions[-1].strftime("%Y-%m-%d %H:%M:%S") if sessions else None,
    }


def create_course_schedule(platform_id, schedule):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        result = save_course_schedule(cursor, platform_id, schedule)
        conn.commit()
        return result
    finally:
        conn.close()


def _parse_local_datetime(value):
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return FRANCE_TZ.localize(dt)


def _upsert_course_time(cursor, platform_id, scheduled_at):
    cursor.execute(
        "UPDATE cours_config SET heure_debut = ? WHERE platform_id = ?",
        (scheduled_at, platform_id),
    )
    if cursor.rowcount == 0:
        cursor.execute(
            "INSERT INTO cours_config (id, heure_debut, platform_id) VALUES (?, ?, ?)",
            (platform_id, scheduled_at, platform_id),
        )


def advance_platform_schedule(cursor, platform_id, now=None):
    ensure_course_schedule_tables(cursor)
    now = now or datetime.now(FRANCE_TZ)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    active_hours = float(os.environ.get("COURSE_SESSION_ACTIVE_HOURS", "12"))
    stale_before = (now - timedelta(hours=active_hours)).strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        """
        UPDATE course_sessions
        SET status = 'completed', completed_at = ?, updated_at = ?
        WHERE platform_id = ?
          AND status IN ('planned', 'active')
          AND scheduled_at < ?
        """,
        (now_str, now_str, platform_id, stale_before),
    )

    cursor.execute(
        """
        SELECT id, scheduled_at
        FROM course_sessions
        WHERE platform_id = ?
          AND status IN ('planned', 'active')
          AND scheduled_at <= ?
          AND scheduled_at >= ?
        ORDER BY scheduled_at DESC
        LIMIT 1
        """,
        (platform_id, now_str, stale_before),
    )
    row = cursor.fetchone()
    if row:
        session_id, scheduled_at = row
        cursor.execute(
            """
            UPDATE course_sessions
            SET status = 'active',
                activated_at = COALESCE(activated_at, ?),
                updated_at = ?
            WHERE id = ?
            """,
            (now_str, now_str, session_id),
        )
        _upsert_course_time(cursor, platform_id, scheduled_at)
        return {"platform_id": platform_id, "session_id": session_id, "status": "active", "scheduled_at": scheduled_at}

    cursor.execute(
        """
        SELECT id, scheduled_at
        FROM course_sessions
        WHERE platform_id = ?
          AND status = 'planned'
          AND scheduled_at > ?
        ORDER BY scheduled_at ASC
        LIMIT 1
        """,
        (platform_id, now_str),
    )
    row = cursor.fetchone()
    if row:
        session_id, scheduled_at = row
        _upsert_course_time(cursor, platform_id, scheduled_at)
        return {"platform_id": platform_id, "session_id": session_id, "status": "scheduled", "scheduled_at": scheduled_at}

    return {"platform_id": platform_id, "status": "empty"}


def run_scheduler_tick(platform_ids=None):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        ensure_course_schedule_tables(cursor)
        if platform_ids:
            ids = [int(pid) for pid in platform_ids]
        else:
            cursor.execute("SELECT platform_id FROM course_schedule_config ORDER BY platform_id")
            ids = [row[0] for row in cursor.fetchall()]

        results = [advance_platform_schedule(cursor, pid) for pid in ids]
        conn.commit()
        return results
    finally:
        conn.close()


def _platform_class_url(cursor, platform_id, base_url=None):
    cursor.execute(
        """
        SELECT pc.slug, COALESCE(tca.slug, 'le-socrate')
        FROM platform_config pc
        LEFT JOIN training_center_accounts tca ON tca.id = pc.center_account_id
        WHERE pc.id = ?
        """,
        (platform_id,),
    )
    row = cursor.fetchone()
    if not row:
        return ""
    platform_slug, center_slug = row
    path = f"/classe/{center_slug or 'le-socrate'}/{platform_slug}"
    return f"{str(base_url).rstrip('/')}{path}" if base_url else path


def _student_recipients(cursor, platform_id):
    recipients = {}
    cursor.execute(
        """
        SELECT email, nom, prenom
        FROM student_profiles
        WHERE platform_id = ? AND COALESCE(is_active, 1) = 1 AND email IS NOT NULL
        """,
        (platform_id,),
    )
    for email, nom, prenom in cursor.fetchall():
        email = str(email or "").strip().lower()
        if email:
            recipients[email] = {"email": email, "nom": nom or "", "prenom": prenom or ""}

    cursor.execute(
        """
        SELECT username, nom, prenom
        FROM student_accounts
        WHERE platform_id = ? AND COALESCE(is_active, 1) = 1 AND username LIKE '%@%'
        """,
        (platform_id,),
    )
    for email, nom, prenom in cursor.fetchall():
        email = str(email or "").strip().lower()
        if email and email not in recipients:
            recipients[email] = {"email": email, "nom": nom or "", "prenom": prenom or ""}
    return list(recipients.values())


def _post_reminder_webhook(payload):
    webhook_url = os.environ.get("REMINDER_WEBHOOK_URL")
    if not webhook_url:
        return False, "REMINDER_WEBHOOK_URL non configuré"

    headers = {"Content-Type": "application/json"}
    webhook_key = os.environ.get("REMINDER_WEBHOOK_KEY")
    if webhook_key:
        headers["X-Reminder-Key"] = webhook_key

    response = http_requests.post(webhook_url, json=payload, headers=headers, timeout=20)
    if response.status_code >= 400:
        return False, f"Webhook rappel HTTP {response.status_code}: {response.text[:300]}"
    return True, None


def process_due_reminders(base_url=None, dry_run=False):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        ensure_course_schedule_tables(cursor)
        now = datetime.now(FRANCE_TZ)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        evening_hour = int(os.environ.get("REMINDER_PREVIOUS_EVENING_HOUR", "18"))
        active_hours = float(os.environ.get("COURSE_SESSION_ACTIVE_HOURS", "12"))
        active_until = now + timedelta(hours=active_hours)

        cursor.execute(
            """
            SELECT id, platform_id, session_index, scheduled_at,
                   reminder_previous_evening_sent_at, reminder_5min_sent_at
            FROM course_sessions
            WHERE status IN ('planned', 'active')
              AND scheduled_at <= ?
            ORDER BY scheduled_at ASC
            """,
            (active_until.strftime("%Y-%m-%d %H:%M:%S"),),
        )

        results = []
        for session_id, platform_id, session_index, scheduled_at_str, previous_sent, five_sent in cursor.fetchall():
            scheduled_at = _parse_local_datetime(scheduled_at_str)
            due_types = []
            previous_evening_at = FRANCE_TZ.localize(
                datetime.combine((scheduled_at - timedelta(days=1)).date(), time(evening_hour, 0))
            )
            if not previous_sent and now >= previous_evening_at and now < scheduled_at:
                due_types.append(("previous_evening", "reminder_previous_evening_sent_at"))

            five_min_at = scheduled_at - timedelta(minutes=5)
            if not five_sent and now >= five_min_at and now <= scheduled_at + timedelta(hours=active_hours):
                due_types.append(("five_minutes_before", "reminder_5min_sent_at"))

            if not due_types:
                continue

            recipients = _student_recipients(cursor, platform_id)
            class_url = _platform_class_url(cursor, platform_id, base_url)
            for reminder_type, sent_column in due_types:
                payload = {
                    "type": reminder_type,
                    "platform_id": platform_id,
                    "session_id": session_id,
                    "session_index": session_index,
                    "scheduled_at": scheduled_at_str,
                    "class_url": class_url,
                    "recipients": recipients,
                }
                if dry_run:
                    results.append({**payload, "success": True, "dry_run": True})
                    continue

                ok, error = _post_reminder_webhook(payload)
                if ok:
                    cursor.execute(
                        f"UPDATE course_sessions SET {sent_column} = ?, updated_at = ? WHERE id = ?",
                        (now_str, now_str, session_id),
                    )
                results.append({**payload, "success": ok, "error": error})

        conn.commit()
        return results
    finally:
        conn.close()
