import json
import html
import os
import secrets
import smtplib
import imaplib
import time as time_module
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests as http_requests
from pytz.exceptions import AmbiguousTimeError, NonExistentTimeError

from config import FRANCE_TZ
from database.db import get_db_connection
from repositories import course_schedule_repository as schedule_repo
from utils.auth_tokens import (
    course_invitation_recipient_hash,
    issue_course_invitation_token,
)
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

SESSION_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def ensure_course_schedule_tables(cursor):
    # Postgres schema changes are applied during deployment. Runtime DDL and
    # SQLite PRAGMAs must never run against the production store.
    if schedule_repo.schedule_store_is_postgres():
        return
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
            module_day_id INTEGER,
            local_date TEXT,
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
    cursor.execute("PRAGMA table_info(course_sessions)")
    columns = [col[1] for col in cursor.fetchall()]
    for col, col_type in {
        "session_password": "TEXT",
        "session_password_generated_at": "TEXT",
        "reminder_previous_evening_claimed_at": "TEXT",
        "reminder_5min_claimed_at": "TEXT",
        "audio_generation_status": "TEXT DEFAULT 'pending'",
        "audio_generation_started_at": "TEXT",
        "audio_generation_completed_at": "TEXT",
        "audio_generation_error": "TEXT",
        "audio_generation_attempts": "INTEGER NOT NULL DEFAULT 0",
        "audio_generation_next_retry_at": "TEXT",
        "audio_job_id": "INTEGER",
        "audio_folder_id": "INTEGER",
        "audio_storage_prefix": "TEXT",
        "postponed_from": "TEXT",
        "postponed_at": "TEXT",
        "postponement_count": "INTEGER NOT NULL DEFAULT 0",
        "module_day_id": "INTEGER",
        "local_date": "TEXT",
    }.items():
        if col not in columns:
            cursor.execute(f"ALTER TABLE course_sessions ADD COLUMN {col} {col_type}")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_course_sessions_audio_due "
        "ON course_sessions(audio_generation_status, audio_generation_next_retry_at, scheduled_at)"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS course_session_postponements (
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
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_course_session_postponements_session "
        "ON course_session_postponements(platform_id, session_id, created_at)"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS course_reminder_recipients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL,
            email TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(platform_id, email)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS course_reminder_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL,
            system_key TEXT,
            name TEXT NOT NULL,
            trigger_mode TEXT NOT NULL,
            days_before INTEGER,
            minutes_before INTEGER,
            local_time TEXT,
            subject_template TEXT NOT NULL,
            content_template TEXT NOT NULL,
            recipient_scope TEXT NOT NULL DEFAULT 'all',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(platform_id, system_key)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS course_reminder_rule_recipients (
            rule_id INTEGER NOT NULL,
            recipient_id INTEGER NOT NULL,
            PRIMARY KEY(rule_id, recipient_id),
            FOREIGN KEY(rule_id) REFERENCES course_reminder_rules(id) ON DELETE CASCADE,
            FOREIGN KEY(recipient_id) REFERENCES course_reminder_recipients(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS course_reminder_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL,
            session_id INTEGER NOT NULL,
            rule_id INTEGER NOT NULL,
            recipient_id INTEGER NOT NULL,
            recipient_hash TEXT NOT NULL,
            due_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            claimed_at TEXT,
            lease_expires_at TEXT,
            sent_at TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 5,
            next_retry_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(session_id, rule_id, recipient_hash),
            FOREIGN KEY(session_id) REFERENCES course_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY(rule_id) REFERENCES course_reminder_rules(id) ON DELETE CASCADE,
            FOREIGN KEY(recipient_id) REFERENCES course_reminder_recipients(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_course_reminder_rules_platform "
        "ON course_reminder_rules(platform_id, is_active)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_course_reminder_deliveries_due "
        "ON course_reminder_deliveries(status, due_at, claimed_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_course_reminder_deliveries_lookup "
        "ON course_reminder_deliveries(session_id, rule_id, recipient_id)"
    )


def _generate_session_password():
    length = int(os.environ.get("COURSE_SESSION_PASSWORD_LENGTH", "6"))
    length = max(4, min(length, 16))
    return "".join(secrets.choice(SESSION_PASSWORD_ALPHABET) for _ in range(length))


def _ensure_session_password(cursor, session_id, now_str=None):
    if schedule_repo.schedule_store_is_postgres():
        generated_at = now_str or _now_str()
        return schedule_repo.ensure_session_password(
            int(session_id),
            password=_generate_session_password(),
            generated_at=generated_at,
        )
    cursor.execute(
        "SELECT session_password FROM course_sessions WHERE id = ?",
        (session_id,),
    )
    row = cursor.fetchone()
    if row and row[0]:
        return row[0]

    generated_at = now_str or _now_str()
    password = _generate_session_password()
    cursor.execute(
        """
        UPDATE course_sessions
        SET session_password = ?,
            session_password_generated_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (password, generated_at, generated_at, session_id),
    )
    return password


def _now_str():
    return datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _parse_start_time(value):
    raw = str(value or "09:00").strip()
    try:
        hour, minute = raw.split(":", 1)
        return time(int(hour), int(minute[:2]))
    except Exception:
        raise ValueError("start_time invalide, format attendu HH:MM")


def course_start_time_policy():
    configured = str(os.environ.get("COURSE_START_TIME_POLICY") or "").strip().lower()
    if not configured:
        configured = "fixed_09" if schedule_repo.schedule_store_is_postgres() else "configured"
    if configured not in {"fixed_09", "configured"}:
        raise ValueError("COURSE_START_TIME_POLICY doit valoir fixed_09 ou configured")
    return configured


def _validated_course_write_start_time(value):
    parsed = _parse_start_time(value)
    if course_start_time_policy() == "fixed_09" and parsed != time(9, 0):
        raise ValueError(
            "Les journées Formation3 commencent obligatoirement à 09:00 "
            "et suivent la playlist pédagogique jusqu'à 18:30."
        )
    return parsed.strftime("%H:%M")


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


def _audio_schedule_window_hours():
    horizon = float(
        os.environ.get(
            "SCHEDULED_AUDIO_READY_HOURS_BEFORE",
            os.environ.get("SCHEDULED_AUDIO_HORIZON_HOURS", "72"),
        )
    )
    late_grace = float(os.environ.get("SCHEDULED_AUDIO_LATE_GRACE_HOURS", "2"))
    return horizon, late_grace


def schedule_change_cutoff_hours():
    """Business cutoff before which an occurrence becomes immutable."""
    value = float(os.environ.get("COURSE_SCHEDULE_CHANGE_CUTOFF_HOURS", "72"))
    return max(24.0, value)


def _format_session_for_error(scheduled_at):
    try:
        dt = _parse_local_datetime(str(scheduled_at))
        return dt.strftime("%d/%m/%Y à %H:%M")
    except Exception:
        return str(scheduled_at or "prochaine séance")


def _find_schedule_update_lock(cursor, platform_id):
    """Bloque une modification qui pourrait déplacer une génération audio proche."""
    horizon, late_grace = _audio_schedule_window_hours()
    now = datetime.now(FRANCE_TZ)
    lower_dt = now - timedelta(hours=late_grace)
    upper_dt = now + timedelta(hours=horizon)
    if schedule_repo.schedule_store_is_postgres():
        row = schedule_repo.find_schedule_update_lock(
            int(platform_id),
            lower_bound=lower_dt,
            upper_bound=upper_dt,
        )
        if not row:
            return None
        return {
            **row,
            "scheduled_at": schedule_repo.format_schedule_datetime(row.get("scheduled_at")),
            "horizon_hours": horizon,
            "late_grace_hours": late_grace,
        }

    ensure_course_schedule_tables(cursor)
    lower_bound = lower_dt.strftime("%Y-%m-%d %H:%M:%S")
    upper_bound = upper_dt.strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        """
        SELECT scheduled_at, audio_generation_status, audio_generation_started_at, audio_generation_completed_at
        FROM course_sessions
        WHERE platform_id = ?
          AND status IN ('planned', 'active')
          AND (
            scheduled_at BETWEEN ? AND ?
            OR (
              audio_generation_started_at IS NOT NULL
              AND audio_generation_completed_at IS NULL
            )
            OR COALESCE(audio_generation_status, 'pending') IN ('queued', 'running', 'processing')
          )
        ORDER BY scheduled_at ASC
        LIMIT 1
        """,
        (platform_id, lower_bound, upper_bound),
    )
    row = cursor.fetchone()
    if not row:
        return None

    scheduled_at, audio_status, audio_started_at, audio_completed_at = row
    return {
        "scheduled_at": scheduled_at,
        "audio_generation_status": audio_status,
        "audio_generation_started_at": audio_started_at,
        "audio_generation_completed_at": audio_completed_at,
        "horizon_hours": horizon,
        "late_grace_hours": late_grace,
    }


def _assert_schedule_can_be_changed(cursor, platform_id):
    lock = _find_schedule_update_lock(cursor, platform_id)
    if not lock:
        return
    session_label = _format_session_for_error(lock.get("scheduled_at"))
    horizon = int(lock.get("horizon_hours") or 24)
    raise ValueError(
        f"Planning verrouillé: une journée est prévue le {session_label}. "
        f"Le planning ne peut plus être modifié dans les {horizon}h avant une séance, "
        "car l'audio peut être préparé automatiquement."
    )


def _assert_requested_sessions_are_not_due_soon(sessions):
    if not sessions:
        return
    horizon, late_grace = _audio_schedule_window_hours()
    now = datetime.now(FRANCE_TZ)
    lower_bound = now - timedelta(hours=late_grace)
    upper_bound = now + timedelta(hours=horizon)
    first_session = sessions[0]
    if lower_bound <= first_session <= upper_bound:
        session_label = first_session.strftime("%d/%m/%Y à %H:%M")
        raise ValueError(
            f"Planning refusé: la nouvelle prochaine journée tomberait le {session_label}. "
            f"Choisissez un planning dont la prochaine journée est à plus de {int(horizon)}h, "
            "pour laisser le temps à l'audio de se préparer."
        )


def _generate_session_datetimes(
    total_training_days,
    weekdays,
    start_time,
    start_date=None,
    not_before=None,
):
    total = int(total_training_days)
    if total <= 0:
        raise ValueError("total_training_days doit être positif")

    course_time = _parse_start_time(start_time)
    now = datetime.now(FRANCE_TZ)
    minimum = _parse_local_datetime(not_before) if not_before is not None else now
    if start_date:
        cursor_date = datetime.strptime(str(start_date), "%Y-%m-%d").date()
    else:
        cursor_date = now.date()

    sessions = []
    max_days = total * 14 + 370
    for _ in range(max_days):
        if cursor_date.weekday() in weekdays:
            try:
                scheduled = FRANCE_TZ.localize(
                    datetime.combine(cursor_date, course_time),
                    is_dst=None,
                )
            except NonExistentTimeError as exc:
                raise ValueError(
                    "Cette heure n'existe pas le jour du passage à l'heure d'été. "
                    "Choisissez une autre heure."
                ) from exc
            except AmbiguousTimeError as exc:
                raise ValueError(
                    "Cette heure est ambiguë le jour du passage à l'heure d'hiver. "
                    "Choisissez une autre heure."
                ) from exc
            if scheduled > minimum:
                sessions.append(scheduled)
                if len(sessions) >= total:
                    break
        cursor_date += timedelta(days=1)

    if len(sessions) < total:
        raise ValueError("Impossible de générer toutes les séances demandées")
    return sessions


def save_course_schedule(cursor, platform_id, schedule):
    schedule = schedule or {}
    total_training_days = int(schedule.get("total_training_days") or 0)
    weekly_course_count = int(schedule.get("weekly_course_count") or 0)
    weekdays = _normalize_weekdays(schedule.get("weekdays"), weekly_course_count)
    start_time = _validated_course_write_start_time(schedule.get("start_time") or "09:00")
    start_date = schedule.get("start_date") or None
    replace_after = schedule.get("_replace_after")
    not_before = schedule.get("_not_before") or replace_after
    fill_remaining_to_total = bool(schedule.get("_fill_remaining_to_total"))

    sessions = _generate_session_datetimes(
        total_training_days=total_training_days,
        weekdays=weekdays,
        start_time=start_time,
        start_date=start_date,
        not_before=not_before,
    )
    now_dt = datetime.now(FRANCE_TZ)
    weekdays_json = json.dumps(weekdays)
    session_rows = [
        {
            "session_index": index,
            "scheduled_at": scheduled,
            "session_password": _generate_session_password(),
        }
        for index, scheduled in enumerate(sessions, start=1)
    ]
    sqlite_connection = None
    if not schedule_repo.schedule_store_is_postgres():
        ensure_course_schedule_tables(cursor)
        sqlite_connection = getattr(cursor, "connection", None)
        if sqlite_connection is None:
            raise RuntimeError("Connexion SQLite du planning indisponible")
    storage_result = schedule_repo.replace_course_schedule(
        platform_id=int(platform_id),
        total_training_days=total_training_days,
        weekly_course_count=weekly_course_count,
        weekdays_json=weekdays_json,
        start_time=start_time,
        timezone_name="Europe/Paris",
        sessions=session_rows,
        now=now_dt,
        replace_after=replace_after,
        fill_remaining_to_total=fill_remaining_to_total,
        sqlite_connection=sqlite_connection,
    )
    horizon, _ = _audio_schedule_window_hours()
    immediate_audio = bool(
        sessions and sessions[0] <= now_dt + timedelta(hours=horizon)
    )
    return {
        "total_sessions": total_training_days,
        "first_session_at": sessions[0].strftime("%Y-%m-%d %H:%M:%S") if sessions else None,
        "last_session_at": sessions[-1].strftime("%Y-%m-%d %H:%M:%S") if sessions else None,
        "audio_generation_immediate": immediate_audio,
        **(storage_result or {}),
    }


def save_explicit_course_schedule(cursor, platform_id, schedule):
    """Persist an immutable V2 calendar from its exact checked dates.

    Recurrence helpers are deliberately absent here: one canonical day in the
    snapshot produces one dated session, in chronological order.
    """
    from services.dynamic_day_schedule_service import (
        SCHEDULE_SCHEMA_VERSION,
        compile_day_schedule,
    )

    schedule = schedule or {}
    days = schedule.get("days")
    if not isinstance(days, list) or not days:
        raise ValueError("Le planning V2 doit contenir une liste days non vide")

    requested_dates = schedule.get("selected_dates")
    if requested_dates is not None:
        if not isinstance(requested_dates, list):
            raise ValueError("selected_dates doit être une liste")
        requested_dates = [str(value) for value in requested_dates]

    normalized_days = []
    seen_dates = set()
    for expected_index, raw_day in enumerate(days, start=1):
        if not isinstance(raw_day, dict):
            raise ValueError(f"Journée {expected_index} invalide")
        day_index = int(
            raw_day.get("day_index", raw_day.get("day_number", expected_index))
        )
        if day_index != expected_index:
            raise ValueError("Les journées doivent être ordonnées sans interruption")
        raw_date = str(raw_day.get("date") or "").strip()
        try:
            local_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(
                f"La date de la journée {expected_index} est invalide"
            ) from exc
        if local_date.isoformat() != raw_date or raw_date in seen_dates:
            raise ValueError("Les dates doivent être uniques au format YYYY-MM-DD")
        seen_dates.add(raw_date)

        compiled_day = compile_day_schedule(raw_day)
        start_minute = int(compiled_day["start_minute"])
        try:
            scheduled_at = FRANCE_TZ.localize(
                datetime.combine(
                    local_date,
                    time(start_minute // 60, start_minute % 60),
                ),
                is_dst=None,
            )
        except NonExistentTimeError as exc:
            raise ValueError(
                "L’heure de début n’existe pas le jour du passage à l’heure d’été"
            ) from exc
        except AmbiguousTimeError as exc:
            raise ValueError(
                "L’heure de début est ambiguë le jour du passage à l’heure d’hiver"
            ) from exc
        normalized_days.append(
            {
                "day_index": day_index,
                "date": raw_date,
                "scheduled_at": scheduled_at,
                "module_day_id": raw_day.get("module_day_id"),
            }
        )

    normalized_days.sort(key=lambda day: (day["scheduled_at"], day["day_index"]))
    if [day["day_index"] for day in normalized_days] != list(
        range(1, len(normalized_days) + 1)
    ):
        raise ValueError("Les journées doivent suivre l’ordre chronologique des dates")
    canonical_dates = [day["date"] for day in normalized_days]
    if requested_dates is not None and requested_dates != canonical_dates:
        raise ValueError("selected_dates doit suivre l’ordre chronologique des journées")
    if len(normalized_days) != int(
        schedule.get("day_count") or len(normalized_days)
    ):
        raise ValueError("day_count ne correspond pas aux journées")

    now_dt = datetime.now(FRANCE_TZ)
    if normalized_days[0]["scheduled_at"] <= now_dt:
        raise ValueError("La première journée doit commencer dans le futur")
    session_rows = [
        {
            "session_index": day["day_index"],
            "scheduled_at": day["scheduled_at"],
            "local_date": day["date"],
            "module_day_id": (
                int(day["module_day_id"])
                if day.get("module_day_id") is not None
                else None
            ),
            "session_password": _generate_session_password(),
        }
        for day in normalized_days
    ]
    sqlite_connection = None
    if not schedule_repo.schedule_store_is_postgres():
        ensure_course_schedule_tables(cursor)
        sqlite_connection = getattr(cursor, "connection", None)
        if sqlite_connection is None:
            raise RuntimeError("Connexion SQLite du planning indisponible")
    storage_result = schedule_repo.replace_course_schedule(
        platform_id=int(platform_id),
        total_training_days=len(normalized_days),
        weekly_course_count=0,
        weekdays_json="[]",
        start_time=normalized_days[0]["scheduled_at"].strftime("%H:%M"),
        timezone_name="Europe/Paris",
        sessions=session_rows,
        now=now_dt,
        replace_after=now_dt,
        fill_remaining_to_total=False,
        sqlite_connection=sqlite_connection,
        schedule_schema_version=SCHEDULE_SCHEMA_VERSION,
    )
    horizon, _ = _audio_schedule_window_hours()
    immediate_audio = (
        normalized_days[0]["scheduled_at"]
        <= now_dt + timedelta(hours=horizon)
    )
    return {
        "total_sessions": len(normalized_days),
        "first_session_at": normalized_days[0]["scheduled_at"].strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "last_session_at": normalized_days[-1]["scheduled_at"].strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "audio_generation_immediate": immediate_audio,
        "schedule_schema_version": SCHEDULE_SCHEMA_VERSION,
        **(storage_result or {}),
    }


def create_missing_course_schedule(
    cursor,
    platform_id,
    *,
    total_training_days,
    start_time,
    date_str=None,
    weekdays=None,
    allow_imminent=False,
):
    """Crée un planning persistant pour une plateforme pipeline qui en est dépourvue."""
    ensure_course_schedule_tables(cursor)
    if get_course_schedule_summary(cursor, platform_id):
        return None

    total = int(total_training_days or 0)
    if total <= 0:
        return None

    if weekdays is not None:
        requested_weekdays = _normalize_weekdays(weekdays)
        start_date = date_str or None
    elif date_str:
        start_date = str(date_str)
        requested_weekdays = [datetime.strptime(start_date, "%Y-%m-%d").date().weekday()]
    else:
        return None

    requested_start_time = _validated_course_write_start_time(start_time or "09:00")
    requested_sessions = _generate_session_datetimes(
        total_training_days=total,
        weekdays=requested_weekdays,
        start_time=requested_start_time,
        start_date=start_date,
    )
    horizon, _ = _audio_schedule_window_hours()
    immediate_audio = bool(
        requested_sessions
        and requested_sessions[0] <= datetime.now(FRANCE_TZ) + timedelta(hours=horizon)
    )
    if allow_imminent or immediate_audio:
        logger.warning(
            "COURSE_SCHEDULE_IMMINENT_CREATE platform_id=%s operation=create first_session=%s",
            platform_id,
            requested_sessions[0].isoformat() if requested_sessions else None,
        )

    result = save_course_schedule(
        cursor,
        platform_id,
        {
            "total_training_days": total,
            "weekly_course_count": len(requested_weekdays),
            "weekdays": requested_weekdays,
            "start_time": requested_start_time,
            "start_date": start_date,
        },
    )
    if result.get("first_session_at"):
        _upsert_course_time(cursor, platform_id, result["first_session_at"])
    return {
        **result,
        "total_training_days": total,
        "weekly_course_count": len(requested_weekdays),
        "weekdays": requested_weekdays,
        "start_time": requested_start_time,
        "timezone": "Europe/Paris",
        "audio_generation_immediate": immediate_audio,
    }


def get_course_schedule_summary(cursor, platform_id):
    if schedule_repo.schedule_store_is_postgres():
        row = schedule_repo.get_course_schedule_summary(int(platform_id))
        if not row:
            return None
        try:
            weekdays = json.loads(row.get("weekdays_json") or "[]")
        except Exception:
            weekdays = []
        return {
            "total_training_days": row.get("total_training_days"),
            "weekly_course_count": row.get("weekly_course_count"),
            "weekdays": weekdays,
            "start_time": row.get("start_time"),
            "timezone": row.get("timezone"),
            "next_session_at": row.get("next_session_at"),
            "last_session_at": row.get("last_session_at"),
        }

    ensure_course_schedule_tables(cursor)
    cursor.execute(
        """
        SELECT total_training_days, weekly_course_count, weekdays_json, start_time, timezone
        FROM course_schedule_config
        WHERE platform_id = ?
        """,
        (platform_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    total_training_days, weekly_course_count, weekdays_json, start_time, timezone_name = row
    try:
        weekdays = json.loads(weekdays_json or "[]")
    except Exception:
        weekdays = []
    cursor.execute(
        """
        SELECT scheduled_at
        FROM course_sessions
        WHERE platform_id = ?
          AND status IN ('planned', 'active')
        ORDER BY scheduled_at ASC
        LIMIT 1
        """,
        (platform_id,),
    )
    next_row = cursor.fetchone()
    cursor.execute(
        """
        SELECT scheduled_at
        FROM course_sessions
        WHERE platform_id = ?
        ORDER BY session_index DESC
        LIMIT 1
        """,
        (platform_id,),
    )
    last_row = cursor.fetchone()
    return {
        "total_training_days": total_training_days,
        "weekly_course_count": weekly_course_count,
        "weekdays": weekdays,
        "start_time": start_time,
        "timezone": timezone_name,
        "next_session_at": next_row[0] if next_row else None,
        "last_session_at": last_row[0] if last_row else None,
    }


def _schedule_datetime_iso(value):
    if not value:
        return None
    return _parse_local_datetime(value).isoformat()


def build_course_session_state(row, *, now=None):
    """Map durable technical fields to the centre-facing occurrence state."""
    now = now or datetime.now(FRANCE_TZ)
    scheduled_at = _parse_local_datetime(row.get("scheduled_at"))
    raw_audio = str(row.get("audio_generation_status") or "pending").lower()
    raw_status = str(row.get("status") or "planned").lower()
    if raw_status == "cancelled":
        audio_status = "cancelled"
    elif row.get("audio_generation_completed_at") or raw_audio == "completed":
        audio_status = "ready"
    elif raw_audio in {"running", "processing", "queued"}:
        audio_status = "preparing"
    elif raw_audio == "error":
        audio_status = "error"
    elif raw_audio == "waiting_content":
        audio_status = "waiting_content"
    else:
        audio_status = "scheduled"

    horizon, _ = _audio_schedule_window_hours()
    cutoff_hours = schedule_change_cutoff_hours()
    change_cutoff_at = scheduled_at - timedelta(hours=cutoff_hours)
    trigger_at = scheduled_at - timedelta(hours=horizon)
    audio_started = bool(row.get("audio_generation_started_at"))
    audio_completed = bool(row.get("audio_generation_completed_at"))
    postponement_count = int(row.get("postponement_count") or 0)
    return {
        "id": int(row["id"]),
        "session_index": int(row.get("session_index") or 0),
        "scheduled_at": scheduled_at.isoformat(),
        "status": raw_status,
        "audio_status": audio_status,
        "audio_trigger_at": trigger_at.isoformat(),
        "change_cutoff_at": change_cutoff_at.isoformat(),
        "is_locked": now >= change_cutoff_at or audio_started,
        "can_retry_audio": audio_status == "error" and raw_status in {"planned", "active"},
        "can_postpone": raw_status == "planned" and scheduled_at > now,
        "was_postponed": postponement_count > 0,
        "postponement_count": postponement_count,
        "postponed_from": _schedule_datetime_iso(row.get("postponed_from")),
        "postponed_at": _schedule_datetime_iso(row.get("postponed_at")),
        "audio_attempts": int(row.get("audio_generation_attempts") or 0),
        "audio_next_retry_at": _schedule_datetime_iso(row.get("audio_generation_next_retry_at")),
    }


def get_course_schedule_details(cursor, platform_id):
    summary = get_course_schedule_summary(cursor, platform_id)
    if not summary:
        return None
    sessions = schedule_repo.list_course_sessions(int(platform_id), limit=1000)
    public_sessions = [build_course_session_state(row) for row in sessions]
    next_session = next(
        (item for item in public_sessions if item["status"] in {"planned", "active"}),
        None,
    )
    return {
        **summary,
        "next_session_at": next_session["scheduled_at"] if next_session else None,
        "next_audio_status": next_session["audio_status"] if next_session else None,
        "sessions": public_sessions,
        "change_cutoff_hours": int(schedule_change_cutoff_hours()),
        "audio_horizon_hours": int(_audio_schedule_window_hours()[0]),
    }


def get_course_schedule_details_for_platform(platform_id):
    """Load product schedule details without leaking backend-specific cursors."""
    if schedule_repo.schedule_store_is_postgres():
        return get_course_schedule_details(None, int(platform_id))
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        ensure_course_schedule_tables(cursor)
        conn.commit()
        return get_course_schedule_details(cursor, int(platform_id))
    finally:
        conn.close()


def _parse_postponement_datetime(value):
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Choisissez une nouvelle date")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("La nouvelle date est invalide") from exc
    if parsed.tzinfo is not None:
        return parsed.astimezone(FRANCE_TZ)
    try:
        return FRANCE_TZ.localize(parsed, is_dst=None)
    except NonExistentTimeError as exc:
        raise ValueError("Cette heure n’existe pas le jour du changement d’heure") from exc
    except AmbiguousTimeError as exc:
        raise ValueError("Cette heure est ambiguë le jour du changement d’heure") from exc


V2_POSTPONEMENT_UNSUPPORTED_MESSAGE = (
    "Le report des journées pour les formations au planning V2 "
    "n’est pas encore pris en charge."
)


def _assert_legacy_postponement_supported(summary, rows):
    """Stop legacy recurrence logic before it receives an explicit V2 calendar."""
    try:
        schema_version = int((summary or {}).get("schedule_schema_version") or 1)
    except (TypeError, ValueError):
        schema_version = 1
    has_v2_occurrence = any(
        row.get("module_day_id") is not None or row.get("local_date") is not None
        for row in (rows or [])
    )
    if schema_version >= 2 or has_v2_occurrence:
        raise ValueError(V2_POSTPONEMENT_UNSUPPORTED_MESSAGE)


def _build_course_session_postponement_plan(
    platform_id,
    session_id,
    *,
    mode,
    scheduled_at=None,
    now=None,
):
    """Build a deterministic preview while preserving pedagogical indexes."""
    now = now or datetime.now(FRANCE_TZ)
    normalized_mode = str(mode or "next_occurrence").strip().lower()
    if normalized_mode not in {"next_occurrence", "specific_date"}:
        raise ValueError("Choisissez une option de report valide")
    if schedule_repo.schedule_store_is_postgres():
        summary = get_course_schedule_summary(None, int(platform_id))
    else:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            ensure_course_schedule_tables(cursor)
            conn.commit()
            summary = get_course_schedule_summary(cursor, int(platform_id))
        finally:
            conn.close()
    if not summary:
        raise ValueError("Le planning de cette formation est introuvable")
    rows = schedule_repo.list_course_sessions(int(platform_id), limit=1000)
    _assert_legacy_postponement_supported(summary, rows)
    target_position = next(
        (index for index, row in enumerate(rows) if int(row.get("id") or 0) == int(session_id)),
        None,
    )
    if target_position is None:
        raise ValueError("Ce cours est introuvable")
    target = rows[target_position]
    target_at = _parse_local_datetime(target.get("scheduled_at"))
    if str(target.get("status") or "") != "planned" or target_at <= now:
        raise ValueError("Ce cours a déjà commencé et ne peut plus être reporté")

    future_rows = rows[target_position:]
    if any(str(row.get("status") or "") != "planned" for row in future_rows):
        raise ValueError("Le planning a changé. Rechargez-le avant de reporter ce cours")
    old_dates = [_parse_local_datetime(row.get("scheduled_at")) for row in future_rows]
    weekdays = _normalize_weekdays(summary.get("weekdays"), summary.get("weekly_course_count"))

    if normalized_mode == "next_occurrence":
        last_date = old_dates[-1]
        write_start_time = (
            "09:00" if course_start_time_policy() == "fixed_09"
            else summary.get("start_time") or "09:00"
        )
        appended = _generate_session_datetimes(
            total_training_days=1,
            weekdays=weekdays,
            start_time=write_start_time,
            start_date=last_date.strftime("%Y-%m-%d"),
            not_before=last_date,
        )[0]
        new_dates = old_dates[1:] + [appended]
    else:
        requested = _parse_postponement_datetime(scheduled_at)
        _validated_course_write_start_time(requested.strftime("%H:%M"))
        if requested <= now:
            raise ValueError("La nouvelle date doit être dans le futur")
        if requested <= target_at:
            raise ValueError("La nouvelle date doit être après la date actuelle du cours")
        later_dates = []
        if len(future_rows) > 1:
            later_dates = _generate_session_datetimes(
                total_training_days=len(future_rows) - 1,
                weekdays=weekdays,
                start_time=(
                    "09:00" if course_start_time_policy() == "fixed_09"
                    else summary.get("start_time") or "09:00"
                ),
                start_date=requested.strftime("%Y-%m-%d"),
                not_before=requested,
            )
        new_dates = [requested] + later_dates

    changes = [
        {
            "id": int(row["id"]),
            "session_index": int(row.get("session_index") or 0),
            "expected_scheduled_at": old_date,
            "new_scheduled_at": new_date,
        }
        for row, old_date, new_date in zip(future_rows, old_dates, new_dates)
        if old_date != new_date
    ]
    public_changes = [
        {
            "session_id": item["id"],
            "lesson_number": item["session_index"],
            "previous_scheduled_at": item["expected_scheduled_at"].isoformat(),
            "new_scheduled_at": item["new_scheduled_at"].isoformat(),
        }
        for item in changes
    ]
    raw_audio = str(target.get("audio_generation_status") or "pending").lower()
    if target.get("audio_generation_completed_at") or raw_audio == "completed":
        audio_preservation = "ready"
    elif target.get("audio_generation_started_at") or raw_audio in {"queued", "running", "processing"}:
        audio_preservation = "preparing"
    else:
        audio_preservation = "scheduled"
    return {
        "platform_id": int(platform_id),
        "session_id": int(session_id),
        "lesson_number": int(target.get("session_index") or 0),
        "mode": normalized_mode,
        "previous_scheduled_at": target_at.isoformat(),
        "new_scheduled_at": new_dates[0].isoformat(),
        "affected_session_count": len(changes),
        "changes": public_changes,
        "audio_preservation": audio_preservation,
        "warning_imminent": now >= target_at - timedelta(hours=schedule_change_cutoff_hours()),
        "_storage_changes": changes,
    }


def preview_course_session_postponement(platform_id, session_id, *, mode, scheduled_at=None):
    plan = _build_course_session_postponement_plan(
        platform_id,
        session_id,
        mode=mode,
        scheduled_at=scheduled_at,
    )
    return {key: value for key, value in plan.items() if not key.startswith("_")}


def postpone_course_session(
    platform_id,
    session_id,
    *,
    mode,
    scheduled_at=None,
    reason=None,
    idempotency_key=None,
    actor_account_id=None,
):
    clean_key = str(idempotency_key or "").strip()[:120] or None
    if clean_key:
        if not schedule_repo.schedule_store_is_postgres():
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                ensure_course_schedule_tables(cursor)
                conn.commit()
            finally:
                conn.close()
        prior = schedule_repo.get_course_session_postponement_by_key(int(platform_id), clean_key)
        if prior:
            if int(prior.get("session_id") or 0) != int(session_id):
                raise ValueError("Cette demande de report a déjà été utilisée")
            stored_changes = json.loads(prior.get("impact_json") or "[]")
            public_changes = [
                {
                    "session_id": int(item["id"]),
                    "lesson_number": int(item["session_index"]),
                    "previous_scheduled_at": _parse_local_datetime(item["previous_scheduled_at"]).isoformat(),
                    "new_scheduled_at": _parse_local_datetime(item["new_scheduled_at"]).isoformat(),
                }
                for item in stored_changes
            ]
            return {
                "platform_id": int(platform_id),
                "session_id": int(session_id),
                "lesson_number": int(prior.get("session_index") or 0),
                "mode": prior.get("mode") or str(mode or "next_occurrence"),
                "previous_scheduled_at": _parse_local_datetime(prior.get("previous_scheduled_at")).isoformat(),
                "new_scheduled_at": _parse_local_datetime(prior.get("new_scheduled_at")).isoformat(),
                "affected_session_count": int(prior.get("affected_session_count") or len(public_changes)),
                "changes": public_changes,
                "audio_preservation": "scheduled",
                "warning_imminent": False,
                "audit_id": int(prior["id"]),
                "idempotent": True,
            }
    now = datetime.now(FRANCE_TZ)
    plan = _build_course_session_postponement_plan(
        platform_id,
        session_id,
        mode=mode,
        scheduled_at=scheduled_at,
        now=now,
    )
    storage_result = schedule_repo.apply_course_session_postponement(
        int(platform_id),
        int(session_id),
        changes=plan["_storage_changes"],
        mode=plan["mode"],
        reason=reason,
        idempotency_key=clean_key,
        actor_account_id=actor_account_id,
        postponed_at=now,
    )
    logger.info(
        "COURSE_SESSION_POSTPONED platform_id=%s session_id=%s lesson=%s affected=%s mode=%s idempotent=%s",
        platform_id,
        session_id,
        plan["lesson_number"],
        plan["affected_session_count"],
        plan["mode"],
        storage_result.get("idempotent"),
    )
    if storage_result.get("idempotent"):
        stored_changes = storage_result.get("changes") or []
        public_changes = [
            {
                "session_id": int(item["id"]),
                "lesson_number": int(item["session_index"]),
                "previous_scheduled_at": _parse_local_datetime(item["previous_scheduled_at"]).isoformat(),
                "new_scheduled_at": _parse_local_datetime(item["new_scheduled_at"]).isoformat(),
            }
            for item in stored_changes
        ]
        if public_changes:
            plan = {
                **plan,
                "lesson_number": public_changes[0]["lesson_number"],
                "previous_scheduled_at": public_changes[0]["previous_scheduled_at"],
                "new_scheduled_at": public_changes[0]["new_scheduled_at"],
                "affected_session_count": len(public_changes),
                "changes": public_changes,
            }
    return {
        **{key: value for key, value in plan.items() if not key.startswith("_")},
        "audit_id": storage_result.get("audit_id"),
        "idempotent": bool(storage_result.get("idempotent")),
    }


def update_course_schedule_start_time(cursor, platform_id, start_time):
    return update_course_schedule(cursor, platform_id, start_time=start_time)


def update_course_schedule(
    cursor,
    platform_id,
    start_time=None,
    weekdays=None,
    allow_imminent=False,
):
    ensure_course_schedule_tables(cursor)
    summary = get_course_schedule_summary(cursor, platform_id)
    if not summary:
        return None

    if start_time is None and course_start_time_policy() == "fixed_09":
        requested_start_time = "09:00"
    else:
        requested_start_time = str(start_time or summary["start_time"] or "09:00").strip()
    requested_start_time = _validated_course_write_start_time(requested_start_time)
    requested_weekdays = (
        _normalize_weekdays(weekdays, summary["weekly_course_count"])
        if weekdays is not None
        else _normalize_weekdays(summary["weekdays"], summary["weekly_course_count"])
    )
    current_weekdays = _normalize_weekdays(summary["weekdays"], summary["weekly_course_count"])

    if requested_start_time == summary.get("start_time") and requested_weekdays == current_weekdays:
        return {
            **summary,
            "total_sessions": summary["total_training_days"],
            "first_session_at": summary.get("next_session_at"),
            "last_session_at": summary.get("last_session_at"),
            "start_time": requested_start_time,
            "weekdays": requested_weekdays,
        }

    now = datetime.now(FRANCE_TZ)
    cutoff_hours = 0.0 if allow_imminent else schedule_change_cutoff_hours()
    replace_after = now + timedelta(hours=cutoff_hours)
    requested_sessions = _generate_session_datetimes(
        total_training_days=summary["total_training_days"],
        weekdays=requested_weekdays,
        start_time=requested_start_time,
        start_date=replace_after.strftime("%Y-%m-%d"),
        not_before=replace_after,
    )
    if allow_imminent:
        logger.warning(
            "COURSE_SCHEDULE_IMMINENT_OVERRIDE platform_id=%s operation=update first_session=%s",
            platform_id,
            requested_sessions[0].isoformat() if requested_sessions else None,
        )
    result = save_course_schedule(
        cursor,
        platform_id,
        {
            "total_training_days": summary["total_training_days"],
            "weekly_course_count": summary["weekly_course_count"],
            "weekdays": requested_weekdays,
            "start_time": requested_start_time,
            "start_date": replace_after.strftime("%Y-%m-%d"),
            "_replace_after": replace_after,
            "_not_before": replace_after,
            "_fill_remaining_to_total": True,
        },
    )
    refreshed = get_course_schedule_summary(cursor, platform_id) or {}
    if refreshed.get("next_session_at"):
        _upsert_course_time(cursor, platform_id, refreshed["next_session_at"])
    return {
        **summary,
        **refreshed,
        **result,
        "start_time": requested_start_time,
        "weekdays": requested_weekdays,
        "change_cutoff_hours": int(schedule_change_cutoff_hours()),
        "effective_from": replace_after.isoformat(),
    }


def create_course_schedule(platform_id, schedule):
    schedule_version = int(
        (schedule or {}).get(
            "schedule_schema_version",
            (schedule or {}).get("schema_version", 1),
        )
        or 1
    )
    if schedule_repo.schedule_store_is_postgres():
        if schedule_version >= 2:
            return save_explicit_course_schedule(None, platform_id, schedule)
        return save_course_schedule(None, platform_id, schedule)
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if schedule_version >= 2:
            result = save_explicit_course_schedule(cursor, platform_id, schedule)
        else:
            result = save_course_schedule(cursor, platform_id, schedule)
        conn.commit()
        return result
    finally:
        conn.close()


def _parse_local_datetime(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return FRANCE_TZ.localize(value)
        return value.astimezone(FRANCE_TZ)
    raw = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    if parsed.tzinfo is None:
        return FRANCE_TZ.localize(parsed)
    return parsed.astimezone(FRANCE_TZ)


def _upsert_course_time(cursor, platform_id, scheduled_at):
    if schedule_repo.schedule_store_is_postgres():
        schedule_repo.upsert_course_start(int(platform_id), scheduled_at)
        return
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
    now = now or datetime.now(FRANCE_TZ)
    if schedule_repo.schedule_store_is_postgres():
        active_hours = float(os.environ.get("COURSE_SESSION_ACTIVE_HOURS", "12"))
        stale_before = now - timedelta(hours=active_hours)
        return schedule_repo.advance_platform_schedule(
            int(platform_id),
            now=now,
            stale_before=stale_before,
        )

    ensure_course_schedule_tables(cursor)
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
    if schedule_repo.schedule_store_is_postgres():
        ids = (
            [int(pid) for pid in platform_ids]
            if platform_ids
            else schedule_repo.list_schedule_platform_ids()
        )
        return [advance_platform_schedule(None, pid) for pid in ids]

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
    if schedule_repo.schedule_store_is_postgres():
        row = schedule_repo.get_platform_class_identity(int(platform_id))
        if not row:
            return ""
        path = f"/classe/{row.get('center_slug') or 'le-socrate'}/{row.get('platform_slug')}"
        return f"{str(base_url).rstrip('/')}{path}" if base_url else path

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


def _post_reminder_webhook(payload):
    webhook_url = os.environ.get("REMINDER_WEBHOOK_URL")
    if not webhook_url:
        return False, "REMINDER_WEBHOOK_URL non configuré"

    headers = {"Content-Type": "application/json"}
    if payload.get("delivery_id") is not None:
        headers["Idempotency-Key"] = f"course-reminder-{int(payload['delivery_id'])}"
    webhook_key = os.environ.get("REMINDER_WEBHOOK_KEY")
    if webhook_key:
        headers["X-Reminder-Key"] = webhook_key

    response = http_requests.post(webhook_url, json=payload, headers=headers, timeout=20)
    if response.status_code >= 400:
        return False, f"Webhook rappel HTTP {response.status_code}: {response.text[:300]}"
    return True, None


def _email_configured():
    return bool(os.environ.get("EMAIL_USERNAME") and os.environ.get("EMAIL_PASSWORD"))


def _bounded_network_timeout(env_name, default=25.0):
    try:
        value = float(os.environ.get(env_name, str(default)))
    except (TypeError, ValueError):
        value = float(default)
    return max(1.0, min(value, 60.0))


def _class_invitation_url(class_url, invitation_token):
    parts = urlsplit(str(class_url or ""))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["invite"] = invitation_token
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class _ReminderTemplateValues(dict):
    def __missing__(self, key):
        return "{" + str(key) + "}"


def _format_reminder_template(template, values):
    try:
        return str(template or "").format_map(_ReminderTemplateValues(values))
    except (ValueError, KeyError):
        return str(template or "")


def _build_reminder_html(payload):
    scheduled = _parse_local_datetime(payload.get("scheduled_at"))
    values = {
        "date": scheduled.strftime("%d/%m/%Y"),
        "time": scheduled.strftime("%H:%M"),
        "session_code": str(payload.get("session_password") or ""),
        "class_url": str(payload.get("class_url") or ""),
    }
    content = html.escape(
        payload.get("content")
        or _format_reminder_template(payload.get("content_template"), values)
    ).replace("\n", "<br>")
    class_url = html.escape(values["class_url"], quote=True)
    session_code = html.escape(values["session_code"])
    code_block = (
        f'<div class="meta">Code secret (si vous saisissez l’adresse manuellement) : '
        f"<strong>{session_code}</strong></div>"
        if session_code
        else ""
    )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {{ margin:0; padding:0; background:#f6f7fb; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif; color:#0f172a; }}
    .wrap {{ max-width:680px; margin:0 auto; padding:28px 18px; }}
    .header {{ background:linear-gradient(135deg,#5b4bff,#8b5cf6); color:#fff; padding:34px 36px; border-radius:18px 18px 0 0; }}
    .brand {{ font-size:24px; font-weight:800; margin:0; }}
    .card {{ background:#fff; padding:38px 36px; border:1px solid #e2e8f0; border-top:0; border-radius:0 0 18px 18px; box-shadow:0 12px 32px rgba(15,23,42,.08); }}
    h1 {{ font-size:30px; line-height:1.15; margin:0 0 20px; color:#111827; }}
    p {{ font-size:16px; line-height:1.65; margin:0 0 22px; color:#334155; }}
    .cta {{ display:inline-block; background:#8b5cf6; color:#fff !important; text-decoration:none; padding:15px 24px; border-radius:12px; font-weight:700; }}
    .meta {{ margin-top:18px; padding:14px 16px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px; font-size:14px; color:#64748b; }}
    .footer {{ text-align:center; color:#94a3b8; font-size:12px; margin-top:18px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header"><p class="brand">Le Socrate</p></div>
    <div class="card">
      <h1>{html.escape(str(payload.get("subject") or "Rappel de formation"))}</h1>
      <p>Bonjour,</p>
      <p>{content}</p>
      <p><a class="cta" href="{class_url}" target="_blank">Accéder à la formation</a></p>
      <div class="meta">Horaire prévu : {values["date"]} à {values["time"]}</div>
      {code_block}
      <p style="margin-top:26px;">L'équipe Le Socrate</p>
    </div>
    <div class="footer">E-mail automatique de rappel de formation.</div>
  </div>
</body>
</html>"""


def _send_reminder_email_batch(payloads):
    """Send a bounded batch over one SMTP and, optionally, one IMAP session."""
    if not payloads:
        return {}
    if not _email_configured():
        return {
            int(payload["delivery_id"]): (False, "EMAIL_USERNAME/EMAIL_PASSWORD non configurés")
            for payload in payloads
        }

    smtp_server = os.environ.get("SMTP_SERVER", "mail.infomaniak.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    imap_server = os.environ.get("IMAP_SERVER", "mail.infomaniak.com")
    imap_port = int(os.environ.get("IMAP_PORT", "993"))
    username = os.environ.get("EMAIL_USERNAME")
    password = os.environ.get("EMAIL_PASSWORD")
    sender = os.environ.get("EMAIL_FROM") or username
    sender_name = os.environ.get("EMAIL_FROM_NAME", "Le Socrate")
    smtp_timeout = _bounded_network_timeout("COURSE_REMINDER_SMTP_TIMEOUT_SECONDS")
    imap_timeout = _bounded_network_timeout("COURSE_REMINDER_IMAP_TIMEOUT_SECONDS")
    results = {}

    try:
        smtp = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=smtp_timeout)
        smtp.login(username, password)
    except Exception as exc:
        logger.error("❌ Connexion SMTP rappels impossible: %s", exc)
        return {int(payload["delivery_id"]): (False, str(exc)) for payload in payloads}

    imap = None
    if os.environ.get("EMAIL_COPY_TO_SENT", "1") != "0":
        try:
            imap = imaplib.IMAP4_SSL(imap_server, imap_port, timeout=imap_timeout)
            imap.login(username, password)
        except Exception as exc:
            logger.warning("⚠️ Copie IMAP des rappels désactivée pour ce lot: %s", exc)
            imap = None

    try:
        for payload in payloads:
            delivery_id = int(payload["delivery_id"])
            receiver = str(payload.get("recipient", {}).get("email") or "").strip()
            try:
                msg = MIMEMultipart("alternative")
                msg["Message-ID"] = make_msgid()
                msg["Subject"] = str(payload.get("subject") or "Rappel de formation")
                msg["From"] = f"{sender_name} <{sender}>"
                msg["To"] = receiver
                msg.attach(MIMEText(_build_reminder_html(payload), "html", "utf-8"))
                raw_message = msg.as_string()
                smtp.sendmail(sender, receiver, raw_message)
                results[delivery_id] = (True, None)
                if imap is not None:
                    try:
                        imap.append(
                            '"Sent"',
                            "",
                            imaplib.Time2Internaldate(time_module.time()),
                            raw_message.encode("utf8"),
                        )
                    except Exception as exc:
                        logger.warning("⚠️ Copie IMAP du rappel %s impossible: %s", delivery_id, exc)
                pause = max(0.0, float(os.environ.get("EMAIL_SEND_PAUSE_SECONDS", "0")))
                if pause:
                    time_module.sleep(pause)
            except Exception as exc:
                logger.error("❌ Rappel email non envoyé (delivery=%s): %s", delivery_id, exc)
                results[delivery_id] = (False, str(exc))
    finally:
        try:
            smtp.quit()
        except Exception:
            pass
        if imap is not None:
            try:
                imap.logout()
            except Exception:
                pass
    return results


def _dispatch_reminder_batch(payloads):
    if os.environ.get("REMINDER_WEBHOOK_URL"):
        try:
            workers = max(1, min(16, int(os.environ.get("REMINDER_WEBHOOK_MAX_CONCURRENCY", "8"))))
        except (TypeError, ValueError):
            workers = 8
        results = {}
        with ThreadPoolExecutor(max_workers=min(workers, max(1, len(payloads)))) as executor:
            futures = {
                executor.submit(_post_reminder_webhook, payload): int(payload["delivery_id"])
                for payload in payloads
            }
            for future in as_completed(futures):
                delivery_id = futures[future]
                try:
                    results[delivery_id] = future.result()
                except Exception as exc:
                    results[delivery_id] = (False, str(exc))
        return results
    return _send_reminder_email_batch(payloads)


def _sqlite_claim_reminder_delivery(
    cursor,
    *,
    platform_id,
    session_id,
    rule_id,
    recipient_id,
    recipient_hash,
    due_at,
    claimed_at,
    lease_seconds,
    max_attempts,
):
    claimed_value = claimed_at.strftime("%Y-%m-%d %H:%M:%S.%f%z")
    lease_value = (claimed_at + timedelta(seconds=lease_seconds)).strftime("%Y-%m-%d %H:%M:%S.%f%z")
    cursor.execute(
        """
        SELECT id, status, lease_expires_at, next_retry_at, attempts, max_attempts
        FROM course_reminder_deliveries
        WHERE session_id = ? AND rule_id = ? AND recipient_hash = ?
        """,
        (session_id, rule_id, recipient_hash),
    )
    row = cursor.fetchone()
    if not row:
        cursor.execute(
            """
            INSERT INTO course_reminder_deliveries (
                platform_id, session_id, rule_id, recipient_id, recipient_hash, due_at,
                status, claimed_at, lease_expires_at, attempts, max_attempts,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'claimed', ?, ?, 1, ?, ?, ?)
            """,
            (
                platform_id, session_id, rule_id, recipient_id, recipient_hash,
                due_at.strftime("%Y-%m-%d %H:%M:%S%z"), claimed_value, lease_value,
                max_attempts, claimed_value, claimed_value,
            ),
        )
        return int(cursor.lastrowid)
    if (
        row[1] in {"sent", "dead_lettered"}
        or int(row[4] or 0) >= int(row[5] or max_attempts)
        or (row[1] == "claimed" and row[2] and row[2] > claimed_value)
        or (row[3] and row[3] > claimed_value)
    ):
        return None
    cursor.execute(
        """
        UPDATE course_reminder_deliveries
        SET status = 'claimed', claimed_at = ?, lease_expires_at = ?, recipient_id = ?,
            due_at = ?, attempts = attempts + 1, next_retry_at = NULL,
            last_error = NULL, updated_at = ? WHERE id = ?
        """,
        (
            claimed_value, lease_value, recipient_id,
            due_at.strftime("%Y-%m-%d %H:%M:%S%z"), claimed_value, int(row[0]),
        ),
    )
    return int(row[0])


def _sqlite_finish_reminder_delivery(cursor, delivery_id, *, claimed_at, success, error=None):
    claimed_value = claimed_at.strftime("%Y-%m-%d %H:%M:%S.%f%z")
    now = datetime.now(FRANCE_TZ)
    now_value = now.strftime("%Y-%m-%d %H:%M:%S.%f%z")
    if success:
        cursor.execute(
            """
            UPDATE course_reminder_deliveries
            SET status = 'sent', sent_at = ?, claimed_at = NULL, lease_expires_at = NULL,
                next_retry_at = NULL, last_error = NULL, updated_at = ?
            WHERE id = ? AND status = 'claimed' AND claimed_at = ?
            """,
            (now_value, now_value, delivery_id, claimed_value),
        )
        return cursor.rowcount == 1
    cursor.execute(
        "SELECT attempts, max_attempts FROM course_reminder_deliveries WHERE id = ?",
        (delivery_id,),
    )
    row = cursor.fetchone()
    if not row:
        return False
    attempts = int(row[0] or 0)
    terminal = attempts >= int(row[1] or 5)
    retry_base = max(10, int(os.environ.get("COURSE_REMINDER_RETRY_BASE_SECONDS", "60")))
    retry_at = None if terminal else now + timedelta(seconds=min(3600, retry_base * (2 ** max(0, attempts - 1))))
    cursor.execute(
        """
        UPDATE course_reminder_deliveries
        SET status = ?, claimed_at = NULL, lease_expires_at = NULL,
            next_retry_at = ?, last_error = ?, updated_at = ?
        WHERE id = ? AND status = 'claimed' AND claimed_at = ?
        """,
        (
            "dead_lettered" if terminal else "retry_scheduled",
            retry_at.strftime("%Y-%m-%d %H:%M:%S.%f%z") if retry_at else None,
            str(error or "Erreur d'envoi")[:1000], now_value, delivery_id, claimed_value,
        ),
    )
    return cursor.rowcount == 1


def _process_due_delivery_candidates(
    *,
    postgres_store,
    conn,
    cursor,
    now,
    base_url,
    dry_run,
    previous_evening_hour,
    active_hours,
    batch_size,
    lease_seconds,
    max_attempts,
):
    """Process the DB-ranked due queue without scanning unrelated sessions."""
    schedule_repo.ensure_default_course_reminder_rules_for_schedules(
        previous_evening_hour=previous_evening_hour,
        now=now,
        sqlite_cursor=cursor,
    )
    if not postgres_store:
        conn.commit()

    candidates = schedule_repo.list_due_reminder_delivery_candidates(
        now=now,
        active_hours=active_hours,
        limit=min(1000, max(batch_size, batch_size * 2)),
        sqlite_cursor=cursor,
    )
    claimed_payloads = []
    results = []
    base_url_by_platform = {}
    password_by_session = {}

    for candidate in candidates:
        if len(claimed_payloads) >= batch_size:
            break
        session_id = int(candidate["session_id"])
        platform_id = int(candidate["platform_id"])
        rule_id = int(candidate["rule_id"])
        recipient = {
            "id": int(candidate["recipient_id"]),
            "email": str(candidate.get("email") or "").strip().lower(),
        }
        if not recipient["email"]:
            continue
        scheduled_at = _parse_local_datetime(candidate["scheduled_at"])
        due_at = _parse_local_datetime(candidate["due_at"])

        if platform_id not in base_url_by_platform:
            base_url_by_platform[platform_id] = _platform_class_url(cursor, platform_id, base_url)
        if session_id not in password_by_session:
            session_password = candidate.get("session_password")
            if not session_password and not dry_run:
                if postgres_store:
                    session_password = schedule_repo.ensure_session_password(
                        session_id,
                        password=_generate_session_password(),
                        generated_at=now,
                    )
                else:
                    session_password = _ensure_session_password(
                        cursor,
                        session_id,
                        now.strftime("%Y-%m-%d %H:%M:%S"),
                    )
                    conn.commit()
            password_by_session[session_id] = session_password
        session_password = password_by_session[session_id]
        recipient_hash = course_invitation_recipient_hash(recipient["email"])

        if dry_run:
            delivery_id = -len(results) - 1
        elif postgres_store:
            delivery_id = schedule_repo.claim_course_reminder_delivery(
                platform_id=platform_id,
                session_id=session_id,
                rule_id=rule_id,
                recipient_id=recipient["id"],
                recipient_hash=recipient_hash,
                due_at=due_at,
                claimed_at=now,
                lease_seconds=lease_seconds,
                max_attempts=max_attempts,
            )
        else:
            delivery_id = _sqlite_claim_reminder_delivery(
                cursor,
                platform_id=platform_id,
                session_id=session_id,
                rule_id=rule_id,
                recipient_id=recipient["id"],
                recipient_hash=recipient_hash,
                due_at=due_at,
                claimed_at=now,
                lease_seconds=lease_seconds,
                max_attempts=max_attempts,
            )
            conn.commit()
        if delivery_id is None:
            continue

        invitation_token = issue_course_invitation_token(
            platform_id=platform_id,
            session_id=session_id,
            scheduled_at=scheduled_at,
            recipient_email=recipient["email"],
            expires_at=scheduled_at + timedelta(hours=active_hours),
        )
        invitation_url = _class_invitation_url(
            base_url_by_platform[platform_id], invitation_token
        )
        values = {
            "date": scheduled_at.strftime("%d/%m/%Y"),
            "time": scheduled_at.strftime("%H:%M"),
            "session_code": str(session_password or ""),
            "class_url": invitation_url,
        }
        system_key = candidate.get("system_key")
        payload = {
            "delivery_id": delivery_id,
            "type": system_key or f"rule_{rule_id}",
            "rule_id": rule_id,
            "platform_id": platform_id,
            "session_id": session_id,
            "session_index": candidate.get("session_index"),
            "scheduled_at": schedule_repo.format_schedule_datetime(scheduled_at),
            "class_url": invitation_url,
            "session_password": session_password,
            "subject": _format_reminder_template(candidate.get("subject_template"), values),
            "content_template": candidate.get("content_template"),
            "content": _format_reminder_template(candidate.get("content_template"), values),
            "recipient": recipient,
            "recipients": [recipient],
        }
        if dry_run:
            results.append({
                **payload,
                "class_url": base_url_by_platform[platform_id],
                "success": True,
                "dry_run": True,
            })
        else:
            claimed_payloads.append(payload)

    if dry_run:
        return results

    delivery_results = _dispatch_reminder_batch(claimed_payloads)
    for payload in claimed_payloads:
        delivery_id = int(payload["delivery_id"])
        ok, error = delivery_results.get(delivery_id, (False, "Résultat de livraison absent"))
        if postgres_store:
            if ok:
                ok = schedule_repo.complete_course_reminder_delivery(
                    delivery_id,
                    claimed_at=now,
                    sent_at=datetime.now(FRANCE_TZ),
                )
                if not ok:
                    error = "Le lease du rappel a expiré avant confirmation"
            else:
                schedule_repo.release_course_reminder_delivery(
                    delivery_id,
                    claimed_at=now,
                    error=error,
                )
        else:
            completed = _sqlite_finish_reminder_delivery(
                cursor,
                delivery_id,
                claimed_at=now,
                success=ok,
                error=error,
            )
            conn.commit()
            if ok and not completed:
                ok = False
                error = "Le lease du rappel a expiré avant confirmation"
        results.append({
            **payload,
            "class_url": base_url_by_platform[int(payload["platform_id"])],
            "success": bool(ok),
            "error": error,
        })
    return results


def process_due_reminders(base_url=None, dry_run=False):
    """Materialize, claim and drain bounded reminder delivery batches.

    One scheduler tick may need to notify thousands of recipients at the same
    requested minute. Draining several independently leased batches avoids a
    five-minute delay per hundred students while preserving a hard per-tick
    cap for provider and database backpressure.
    """
    base_url = (
        base_url
        or os.environ.get("FRONTEND_PUBLIC_URL")
        or os.environ.get("FRONTEND_URL")
        or os.environ.get("PLATFORM_1_FRONTEND_URL")
    )
    if os.environ.get("WEBSITE_SITE_NAME"):
        parsed_base = urlsplit(str(base_url or ""))
        if parsed_base.scheme not in {"http", "https"} or not parsed_base.netloc:
            raise RuntimeError(
                "FRONTEND_PUBLIC_URL ou PLATFORM_1_FRONTEND_URL absolue requise pour les invitations"
            )
    postgres_store = schedule_repo.schedule_store_is_postgres()
    conn = None if postgres_store else get_db_connection()
    cursor = None if conn is None else conn.cursor()
    try:
        if cursor is not None:
            ensure_course_schedule_tables(cursor)
        now = datetime.now(FRANCE_TZ)
        try:
            previous_evening_hour = max(0, min(23, int(os.environ.get("REMINDER_PREVIOUS_EVENING_HOUR", "18"))))
        except (TypeError, ValueError):
            previous_evening_hour = 18
        try:
            active_hours = max(1.0, float(os.environ.get("COURSE_SESSION_ACTIVE_HOURS", "12")))
        except (TypeError, ValueError):
            active_hours = 12.0
        try:
            batch_size = max(1, min(500, int(os.environ.get("COURSE_REMINDER_DELIVERY_BATCH_SIZE", "100"))))
        except (TypeError, ValueError):
            batch_size = 100
        try:
            lease_seconds = max(60, int(os.environ.get("COURSE_REMINDER_CLAIM_LEASE_SECONDS", "900")))
        except (TypeError, ValueError):
            lease_seconds = 900
        try:
            max_attempts = max(1, min(20, int(os.environ.get("COURSE_REMINDER_MAX_ATTEMPTS", "5"))))
        except (TypeError, ValueError):
            max_attempts = 5
        try:
            max_batches = max(
                1,
                min(
                    100,
                    int(os.environ.get("COURSE_REMINDER_MAX_BATCHES_PER_TICK", "20")),
                ),
            )
        except (TypeError, ValueError):
            max_batches = 20
        if not os.environ.get("REMINDER_WEBHOOK_URL"):
            try:
                smtp_max_batches = max(
                    1,
                    min(
                        10,
                        int(
                            os.environ.get(
                                "COURSE_REMINDER_SMTP_MAX_BATCHES_PER_TICK",
                                "2",
                            )
                        ),
                    ),
                )
            except (TypeError, ValueError):
                smtp_max_batches = 2
            max_batches = min(max_batches, smtp_max_batches)

        results = []
        # A dry run does not persist claims, so repeating it would return the
        # same recipients. Keep previews to one representative batch.
        batch_limit = 1 if dry_run else max_batches
        for _batch_number in range(batch_limit):
            batch_results = _process_due_delivery_candidates(
                postgres_store=postgres_store,
                conn=conn,
                cursor=cursor,
                now=now,
                base_url=base_url,
                dry_run=dry_run,
                previous_evening_hour=previous_evening_hour,
                active_hours=active_hours,
                batch_size=batch_size,
                lease_seconds=lease_seconds,
                max_attempts=max_attempts,
            )
            results.extend(batch_results)
            if len(batch_results) < batch_size:
                break
        return results
    finally:
        if conn is not None:
            conn.close()


def _validated_reminder_rule(data):
    payload = dict(data or {})
    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 120:
        raise ValueError("Le nom du rappel est requis (120 caractères maximum)")
    trigger_mode = str(payload.get("trigger_mode") or "relative_minutes").strip()
    if trigger_mode not in {"local_day_time", "relative_minutes"}:
        raise ValueError("Mode de déclenchement invalide")

    days_before = None
    minutes_before = None
    local_time = None
    if trigger_mode == "local_day_time":
        try:
            days_before = int(payload.get("days_before", 1))
        except (TypeError, ValueError):
            raise ValueError("Le nombre de jours avant doit être un entier")
        if days_before < 0 or days_before > 365:
            raise ValueError("Le nombre de jours avant doit être compris entre 0 et 365")
        parsed_time = _parse_start_time(payload.get("local_time") or "18:00")
        if days_before == 0 and parsed_time >= time(9, 0):
            raise ValueError(
                "Le jour même, le rappel doit être programmé avant le cours fixe de 09:00"
            )
        local_time = parsed_time.strftime("%H:%M")
    else:
        try:
            minutes_before = int(payload.get("minutes_before", 5))
        except (TypeError, ValueError):
            raise ValueError("Le délai avant la séance doit être un entier")
        if minutes_before < 1 or minutes_before > 525600:
            raise ValueError("Le délai doit être compris entre 1 et 525600 minutes")

    subject_template = str(payload.get("subject_template") or "").strip()
    content_template = str(payload.get("content_template") or "").strip()
    if not subject_template or len(subject_template) > 200:
        raise ValueError("L'objet du mail est requis (200 caractères maximum)")
    if "\r" in subject_template or "\n" in subject_template:
        raise ValueError("L'objet du mail ne peut pas contenir de saut de ligne")
    if not content_template or len(content_template) > 5000:
        raise ValueError("Le contenu du mail est requis (5000 caractères maximum)")
    recipient_scope = str(payload.get("recipient_scope") or "all")
    if recipient_scope not in {"all", "selected_explicit"}:
        raise ValueError("Audience du rappel invalide")
    raw_ids = payload.get("recipient_ids") or []
    if not isinstance(raw_ids, list):
        raise ValueError("recipient_ids doit être une liste")
    try:
        recipient_ids = sorted({int(value) for value in raw_ids})
    except (TypeError, ValueError):
        raise ValueError("Un destinataire sélectionné est invalide")
    if recipient_scope == "selected_explicit" and not recipient_ids:
        raise ValueError("Sélectionnez au moins un destinataire")
    return {
        "name": name,
        "trigger_mode": trigger_mode,
        "days_before": days_before,
        "minutes_before": minutes_before,
        "local_time": local_time,
        "subject_template": subject_template,
        "content_template": content_template,
        "recipient_scope": recipient_scope,
        "recipient_ids": recipient_ids,
        "is_active": bool(payload.get("is_active", True)),
    }


def get_course_reminder_rules(platform_id):
    try:
        evening_hour = int(os.environ.get("REMINDER_PREVIOUS_EVENING_HOUR", "18"))
    except (TypeError, ValueError):
        evening_hour = 18
    schedule_repo.ensure_default_course_reminder_rules(
        int(platform_id),
        previous_evening_hour=evening_hour,
        now=datetime.now(FRANCE_TZ),
    )
    return schedule_repo.list_course_reminder_rules(int(platform_id))


def save_course_reminder_rule(platform_id, data, *, rule_id=None):
    values = _validated_reminder_rule(data)
    return schedule_repo.save_course_reminder_rule(
        int(platform_id),
        rule_id=int(rule_id) if rule_id is not None else None,
        now=datetime.now(FRANCE_TZ),
        **values,
    )


def delete_course_reminder_rule(platform_id, rule_id):
    return schedule_repo.delete_course_reminder_rule(int(platform_id), int(rule_id))
