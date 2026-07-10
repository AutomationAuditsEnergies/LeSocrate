"""Persistence for course schedules, reminders, and scheduled audio state.

The historical implementation kept this aggregate in SQLite even when the
formation pipeline itself was in Postgres. This repository is the cut-over
boundary: scheduling follows either authoritative PostgreSQL domain, so a
``hybrid`` business backend with a PostgreSQL pipeline never touches SQLite.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import os
from typing import Any

from config import DATABASE_BACKEND, FRANCE_TZ, PIPELINE_DATABASE_BACKEND
from database.db import get_db_connection
from database.postgres import get_postgres_connection
from utils.logger import get_logger


POSTGRES_SCHEDULE_BACKENDS = {"postgres", "postgresql", "supabase"}
logger = get_logger(__name__)
_LAST_LOGGED_SCHEDULE_BACKEND = None
REMINDER_SENT_COLUMNS = {
    "previous_evening": "reminder_previous_evening_sent_at",
    "five_minutes_before": "reminder_5min_sent_at",
}
REMINDER_CLAIM_COLUMNS = {
    "previous_evening": "reminder_previous_evening_claimed_at",
    "five_minutes_before": "reminder_5min_claimed_at",
}


def schedule_store_is_postgres() -> bool:
    """Return whether operational scheduling is authoritative in Postgres."""
    global _LAST_LOGGED_SCHEDULE_BACKEND
    use_postgres = (
        DATABASE_BACKEND in POSTGRES_SCHEDULE_BACKENDS
        or PIPELINE_DATABASE_BACKEND in POSTGRES_SCHEDULE_BACKENDS
    )
    selection = (
        "postgres" if use_postgres else "sqlite",
        DATABASE_BACKEND,
        PIPELINE_DATABASE_BACKEND,
    )
    if selection != _LAST_LOGGED_SCHEDULE_BACKEND:
        logger.info(
            "COURSE_SCHEDULE_BACKEND_SELECTED storage=%s database_backend=%s "
            "pipeline_database_backend=%s",
            *selection,
        )
        _LAST_LOGGED_SCHEDULE_BACKEND = selection
    return use_postgres


def _sqlite_datetime(value):
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(FRANCE_TZ).replace(tzinfo=None)
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value


def format_schedule_datetime(value):
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(FRANCE_TZ)
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value


def replace_course_schedule(
    *,
    platform_id: int,
    total_training_days: int,
    weekly_course_count: int,
    weekdays_json: str,
    start_time: str,
    timezone_name: str,
    sessions: list[dict[str, Any]],
    now,
    guard_lower_bound=None,
    guard_upper_bound=None,
    sqlite_connection=None,
) -> None:
    """Replace future planned sessions without deleting course history.

    Completed, failed, cancelled and already-started/past rows are immutable
    audit records.  New session indexes continue after the highest retained
    index so the ``(platform_id, session_index)`` key remains stable.
    """
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (f"course-schedule:{int(platform_id)}",),
                )
                if guard_lower_bound is not None and guard_upper_bound is not None:
                    cur.execute(
                        """
                        SELECT id
                        FROM course_sessions
                        WHERE platform_id = %s
                          AND status IN ('planned', 'active')
                          AND (
                            scheduled_at BETWEEN %s AND %s
                            OR (
                                audio_generation_started_at IS NOT NULL
                                AND audio_generation_completed_at IS NULL
                            )
                            OR COALESCE(audio_generation_status, 'pending') IN ('queued', 'running', 'processing')
                          )
                        LIMIT 1
                        FOR UPDATE
                        """,
                        (platform_id, guard_lower_bound, guard_upper_bound),
                    )
                    if cur.fetchone():
                        raise ValueError(
                            "Planning verrouillé: une séance proche ou une génération audio est en cours."
                        )
                cur.execute(
                    """
                    INSERT INTO course_schedule_config (
                        platform_id, total_training_days, weekly_course_count,
                        weekdays_json, start_time, timezone, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (platform_id) DO UPDATE SET
                        total_training_days = EXCLUDED.total_training_days,
                        weekly_course_count = EXCLUDED.weekly_course_count,
                        weekdays_json = EXCLUDED.weekdays_json,
                        start_time = EXCLUDED.start_time,
                        timezone = EXCLUDED.timezone,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        platform_id,
                        total_training_days,
                        weekly_course_count,
                        weekdays_json,
                        start_time,
                        timezone_name,
                        now,
                        now,
                    ),
                )
                cur.execute(
                    """
                    DELETE FROM course_sessions
                    WHERE platform_id = %s
                      AND status IN ('planned', 'active')
                      AND scheduled_at >= %s
                    """,
                    (platform_id, now),
                )
                cur.execute(
                    """
                    SELECT COALESCE(MAX(session_index), 0) AS max_session_index
                    FROM course_sessions
                    WHERE platform_id = %s
                    """,
                    (platform_id,),
                )
                retained_max_index = int(cur.fetchone()["max_session_index"] or 0)
                if sessions:
                    cur.executemany(
                        """
                        INSERT INTO course_sessions (
                            platform_id, session_index, scheduled_at, status,
                            session_password, session_password_generated_at,
                            created_at, updated_at
                        )
                        VALUES (%s, %s, %s, 'planned', %s, %s, %s, %s)
                        """,
                        [
                            (
                                platform_id,
                                retained_max_index + offset,
                                item["scheduled_at"],
                                item["session_password"],
                                now,
                                now,
                                now,
                            )
                            for offset, item in enumerate(sessions, start=1)
                        ],
                    )
        return

    own_connection = sqlite_connection is None
    conn = sqlite_connection or get_db_connection()
    try:
        cursor = conn.cursor()
        now_sqlite = _sqlite_datetime(now)
        cursor.execute(
            """
            INSERT INTO course_schedule_config (
                platform_id, total_training_days, weekly_course_count, weekdays_json,
                start_time, timezone, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform_id) DO UPDATE SET
                total_training_days = excluded.total_training_days,
                weekly_course_count = excluded.weekly_course_count,
                weekdays_json = excluded.weekdays_json,
                start_time = excluded.start_time,
                timezone = excluded.timezone,
                updated_at = excluded.updated_at
            """,
            (
                platform_id,
                total_training_days,
                weekly_course_count,
                weekdays_json,
                start_time,
                timezone_name,
                now_sqlite,
                now_sqlite,
            ),
        )
        cursor.execute(
            """
            DELETE FROM course_sessions
            WHERE platform_id = ?
              AND status IN ('planned', 'active')
              AND scheduled_at >= ?
            """,
            (platform_id, now_sqlite),
        )
        cursor.execute(
            """
            SELECT COALESCE(MAX(session_index), 0)
            FROM course_sessions
            WHERE platform_id = ?
            """,
            (platform_id,),
        )
        retained_max_index = int(cursor.fetchone()[0] or 0)
        cursor.executemany(
            """
            INSERT INTO course_sessions (
                platform_id, session_index, scheduled_at, status,
                session_password, session_password_generated_at,
                created_at, updated_at
            )
            VALUES (?, ?, ?, 'planned', ?, ?, ?, ?)
            """,
            [
                (
                    platform_id,
                    retained_max_index + offset,
                    _sqlite_datetime(item["scheduled_at"]),
                    item["session_password"],
                    now_sqlite,
                    now_sqlite,
                    now_sqlite,
                )
                for offset, item in enumerate(sessions, start=1)
            ],
        )
        if own_connection:
            conn.commit()
    finally:
        if own_connection:
            conn.close()


def get_postgres_course_schedule_summary(platform_id: int) -> dict[str, Any] | None:
    """Read a schedule explicitly from Postgres, independent of migration mode."""
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT total_training_days, weekly_course_count, weekdays_json,
                       start_time, timezone
                FROM course_schedule_config
                WHERE platform_id = %s
                """,
                (platform_id,),
            )
            config = cur.fetchone()
            if not config:
                return None
            cur.execute(
                """
                SELECT scheduled_at
                FROM course_sessions
                WHERE platform_id = %s AND status IN ('planned', 'active')
                ORDER BY scheduled_at ASC
                LIMIT 1
                """,
                (platform_id,),
            )
            next_row = cur.fetchone()
            cur.execute(
                """
                SELECT scheduled_at
                FROM course_sessions
                WHERE platform_id = %s
                ORDER BY session_index DESC
                LIMIT 1
                """,
                (platform_id,),
            )
            last_row = cur.fetchone()
            return {
                **dict(config),
                "next_session_at": format_schedule_datetime(next_row["scheduled_at"]) if next_row else None,
                "last_session_at": format_schedule_datetime(last_row["scheduled_at"]) if last_row else None,
            }


def list_postgres_course_schedule_configs(platform_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Batch-load schedule configuration for Postgres dashboard read models."""
    normalized_ids = sorted({int(platform_id) for platform_id in platform_ids if platform_id})
    if not normalized_ids:
        return {}
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT platform_id, total_training_days, weekly_course_count,
                       weekdays_json, start_time, timezone
                FROM course_schedule_config
                WHERE platform_id = ANY(%s)
                """,
                (normalized_ids,),
            )
            return {
                int(row["platform_id"]): dict(row)
                for row in cur.fetchall()
            }


def get_course_schedule_summary(platform_id: int, *, sqlite_connection=None) -> dict[str, Any] | None:
    if schedule_store_is_postgres():
        return get_postgres_course_schedule_summary(platform_id)

    conn = sqlite_connection or get_db_connection()
    own_connection = sqlite_connection is None
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT total_training_days, weekly_course_count, weekdays_json, start_time, timezone
            FROM course_schedule_config
            WHERE platform_id = ?
            """,
            (platform_id,),
        )
        config = cursor.fetchone()
        if not config:
            return None
        cursor.execute(
            """
            SELECT scheduled_at FROM course_sessions
            WHERE platform_id = ? AND status IN ('planned', 'active')
            ORDER BY scheduled_at ASC LIMIT 1
            """,
            (platform_id,),
        )
        next_row = cursor.fetchone()
        cursor.execute(
            """
            SELECT scheduled_at FROM course_sessions
            WHERE platform_id = ? ORDER BY session_index DESC LIMIT 1
            """,
            (platform_id,),
        )
        last_row = cursor.fetchone()
        return {
            "total_training_days": config[0],
            "weekly_course_count": config[1],
            "weekdays_json": config[2],
            "start_time": config[3],
            "timezone": config[4],
            "next_session_at": next_row[0] if next_row else None,
            "last_session_at": last_row[0] if last_row else None,
        }
    finally:
        if own_connection:
            conn.close()


def find_schedule_update_lock(
    platform_id: int,
    *,
    lower_bound,
    upper_bound,
    sqlite_connection=None,
) -> dict[str, Any] | None:
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT scheduled_at, audio_generation_status,
                           audio_generation_started_at, audio_generation_completed_at
                    FROM course_sessions
                    WHERE platform_id = %s
                      AND status IN ('planned', 'active')
                      AND (
                        scheduled_at BETWEEN %s AND %s
                        OR (audio_generation_started_at IS NOT NULL AND audio_generation_completed_at IS NULL)
                        OR COALESCE(audio_generation_status, 'pending') IN ('queued', 'running', 'processing')
                      )
                    ORDER BY scheduled_at ASC
                    LIMIT 1
                    """,
                    (platform_id, lower_bound, upper_bound),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    conn = sqlite_connection or get_db_connection()
    own_connection = sqlite_connection is None
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT scheduled_at, audio_generation_status,
                   audio_generation_started_at, audio_generation_completed_at
            FROM course_sessions
            WHERE platform_id = ?
              AND status IN ('planned', 'active')
              AND (
                scheduled_at BETWEEN ? AND ?
                OR (audio_generation_started_at IS NOT NULL AND audio_generation_completed_at IS NULL)
                OR COALESCE(audio_generation_status, 'pending') IN ('queued', 'running', 'processing')
              )
            ORDER BY scheduled_at ASC
            LIMIT 1
            """,
            (platform_id, _sqlite_datetime(lower_bound), _sqlite_datetime(upper_bound)),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "scheduled_at": row[0],
            "audio_generation_status": row[1],
            "audio_generation_started_at": row[2],
            "audio_generation_completed_at": row[3],
        }
    finally:
        if own_connection:
            conn.close()


def upsert_course_start(platform_id: int, scheduled_at, *, sqlite_connection=None) -> None:
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cours_config (id, platform_id, heure_debut)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        platform_id = EXCLUDED.platform_id,
                        heure_debut = EXCLUDED.heure_debut
                    """,
                    (platform_id, platform_id, scheduled_at),
                )
        return

    conn = sqlite_connection or get_db_connection()
    own_connection = sqlite_connection is None
    try:
        cursor = conn.cursor()
        value = _sqlite_datetime(scheduled_at)
        cursor.execute("UPDATE cours_config SET heure_debut = ? WHERE platform_id = ?", (value, platform_id))
        if cursor.rowcount == 0:
            cursor.execute(
                "INSERT INTO cours_config (id, heure_debut, platform_id) VALUES (?, ?, ?)",
                (platform_id, value, platform_id),
            )
        if own_connection:
            conn.commit()
    finally:
        if own_connection:
            conn.close()


def get_course_start(platform_id: int, *, sqlite_connection=None):
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT heure_debut FROM cours_config WHERE platform_id = %s", (platform_id,))
                row = cur.fetchone()
                return row["heure_debut"] if row else None

    conn = sqlite_connection or get_db_connection()
    own_connection = sqlite_connection is None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT heure_debut FROM cours_config WHERE platform_id = ?", (platform_id,))
        row = cursor.fetchone()
        if not row:
            cursor.execute("SELECT heure_debut FROM cours_config WHERE id = 1")
            row = cursor.fetchone()
        return row[0] if row else None
    finally:
        if own_connection:
            conn.close()


def list_schedule_platform_ids() -> list[int]:
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT platform_id FROM course_schedule_config ORDER BY platform_id")
                return [int(row["platform_id"]) for row in cur.fetchall()]
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT platform_id FROM course_schedule_config ORDER BY platform_id")
        return [int(row[0]) for row in cursor.fetchall()]
    finally:
        conn.close()


def advance_platform_schedule(platform_id: int, *, now, stale_before) -> dict[str, Any]:
    """Advance one platform while serializing competing scheduler workers."""
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (f"course-schedule:{int(platform_id)}",),
                )
                cur.execute(
                    """
                    UPDATE course_sessions
                    SET status = 'completed', completed_at = %s, updated_at = %s
                    WHERE platform_id = %s
                      AND status IN ('planned', 'active')
                      AND scheduled_at < %s
                    """,
                    (now, now, platform_id, stale_before),
                )
                cur.execute(
                    """
                    SELECT id, scheduled_at
                    FROM course_sessions
                    WHERE platform_id = %s
                      AND status IN ('planned', 'active')
                      AND scheduled_at <= %s AND scheduled_at >= %s
                    ORDER BY scheduled_at DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (platform_id, now, stale_before),
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        """
                        UPDATE course_sessions
                        SET status = 'active', activated_at = COALESCE(activated_at, %s), updated_at = %s
                        WHERE id = %s
                        """,
                        (now, now, row["id"]),
                    )
                    cur.execute(
                        """
                        INSERT INTO cours_config (id, platform_id, heure_debut)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET heure_debut = EXCLUDED.heure_debut
                        """,
                        (platform_id, platform_id, row["scheduled_at"]),
                    )
                    return {
                        "platform_id": platform_id,
                        "session_id": int(row["id"]),
                        "status": "active",
                        "scheduled_at": format_schedule_datetime(row["scheduled_at"]),
                    }
                cur.execute(
                    """
                    SELECT id, scheduled_at
                    FROM course_sessions
                    WHERE platform_id = %s AND status = 'planned' AND scheduled_at > %s
                    ORDER BY scheduled_at ASC
                    LIMIT 1
                    """,
                    (platform_id, now),
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        """
                        INSERT INTO cours_config (id, platform_id, heure_debut)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET heure_debut = EXCLUDED.heure_debut
                        """,
                        (platform_id, platform_id, row["scheduled_at"]),
                    )
                    return {
                        "platform_id": platform_id,
                        "session_id": int(row["id"]),
                        "status": "scheduled",
                        "scheduled_at": format_schedule_datetime(row["scheduled_at"]),
                    }
        return {"platform_id": platform_id, "status": "empty"}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        now_value = _sqlite_datetime(now)
        stale_value = _sqlite_datetime(stale_before)
        cursor.execute(
            """
            UPDATE course_sessions
            SET status = 'completed', completed_at = ?, updated_at = ?
            WHERE platform_id = ? AND status IN ('planned', 'active') AND scheduled_at < ?
            """,
            (now_value, now_value, platform_id, stale_value),
        )
        cursor.execute(
            """
            SELECT id, scheduled_at FROM course_sessions
            WHERE platform_id = ? AND status IN ('planned', 'active')
              AND scheduled_at <= ? AND scheduled_at >= ?
            ORDER BY scheduled_at DESC LIMIT 1
            """,
            (platform_id, now_value, stale_value),
        )
        row = cursor.fetchone()
        if row:
            cursor.execute(
                """
                UPDATE course_sessions
                SET status = 'active', activated_at = COALESCE(activated_at, ?), updated_at = ?
                WHERE id = ?
                """,
                (now_value, now_value, row[0]),
            )
            upsert_course_start(platform_id, row[1], sqlite_connection=conn)
            conn.commit()
            return {"platform_id": platform_id, "session_id": row[0], "status": "active", "scheduled_at": row[1]}
        cursor.execute(
            """
            SELECT id, scheduled_at FROM course_sessions
            WHERE platform_id = ? AND status = 'planned' AND scheduled_at > ?
            ORDER BY scheduled_at ASC LIMIT 1
            """,
            (platform_id, now_value),
        )
        row = cursor.fetchone()
        if row:
            upsert_course_start(platform_id, row[1], sqlite_connection=conn)
            conn.commit()
            return {"platform_id": platform_id, "session_id": row[0], "status": "scheduled", "scheduled_at": row[1]}
        conn.commit()
        return {"platform_id": platform_id, "status": "empty"}
    finally:
        conn.close()


def list_due_reminder_sessions(*, active_until) -> list[dict[str, Any]]:
    columns = (
        "id, platform_id, session_index, scheduled_at, "
        "reminder_previous_evening_sent_at, reminder_5min_sent_at, session_password"
    )
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {columns}
                    FROM course_sessions
                    WHERE status IN ('planned', 'active') AND scheduled_at <= %s
                    ORDER BY scheduled_at ASC
                    """,
                    (active_until,),
                )
                return [dict(row) for row in cur.fetchall()]
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT {columns}
            FROM course_sessions
            WHERE status IN ('planned', 'active') AND scheduled_at <= ?
            ORDER BY scheduled_at ASC
            """,
            (_sqlite_datetime(active_until),),
        )
        return [
            {
                "id": row[0],
                "platform_id": row[1],
                "session_index": row[2],
                "scheduled_at": row[3],
                "reminder_previous_evening_sent_at": row[4],
                "reminder_5min_sent_at": row[5],
                "session_password": row[6],
            }
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def list_course_reminder_recipients(platform_id: int) -> list[dict[str, str]]:
    recipients: dict[str, dict[str, str]] = {}
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT email FROM course_reminder_recipients WHERE platform_id = %s ORDER BY LOWER(email)",
                    (platform_id,),
                )
                for row in cur.fetchall():
                    email = str(row["email"] or "").strip().lower()
                    if email:
                        recipients[email] = {"email": email, "nom": "", "prenom": ""}
                cur.execute(
                    """
                    SELECT email, nom, prenom FROM student_profiles
                    WHERE platform_id = %s AND COALESCE(is_active, TRUE) = TRUE AND email IS NOT NULL
                    """,
                    (platform_id,),
                )
                for row in cur.fetchall():
                    email = str(row["email"] or "").strip().lower()
                    if email:
                        recipients[email] = {
                            "email": email,
                            "nom": row["nom"] or "",
                            "prenom": row["prenom"] or "",
                        }
                cur.execute(
                    """
                    SELECT username, nom, prenom FROM student_accounts
                    WHERE platform_id = %s AND COALESCE(is_active, TRUE) = TRUE AND username LIKE '%%@%%'
                    """,
                    (platform_id,),
                )
                for row in cur.fetchall():
                    email = str(row["username"] or "").strip().lower()
                    if email and email not in recipients:
                        recipients[email] = {
                            "email": email,
                            "nom": row["nom"] or "",
                            "prenom": row["prenom"] or "",
                        }
        return list(recipients.values())

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT email FROM course_reminder_recipients WHERE platform_id = ? ORDER BY email COLLATE NOCASE",
            (platform_id,),
        )
        for (email,) in cursor.fetchall():
            email = str(email or "").strip().lower()
            if email:
                recipients[email] = {"email": email, "nom": "", "prenom": ""}
        cursor.execute(
            """
            SELECT email, nom, prenom FROM student_profiles
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
            SELECT username, nom, prenom FROM student_accounts
            WHERE platform_id = ? AND COALESCE(is_active, 1) = 1 AND username LIKE '%@%'
            """,
            (platform_id,),
        )
        for email, nom, prenom in cursor.fetchall():
            email = str(email or "").strip().lower()
            if email and email not in recipients:
                recipients[email] = {"email": email, "nom": nom or "", "prenom": prenom or ""}
        return list(recipients.values())
    finally:
        conn.close()


def get_platform_class_identity(platform_id: int) -> dict[str, str] | None:
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pc.slug AS platform_slug, COALESCE(tca.slug, 'le-socrate') AS center_slug
                    FROM platform_config pc
                    LEFT JOIN training_center_accounts tca ON tca.id = pc.center_account_id
                    WHERE pc.id = %s
                    """,
                    (platform_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
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
        return {"platform_slug": row[0], "center_slug": row[1]} if row else None
    finally:
        conn.close()


def list_session_passwords_for_window(
    platform_id: int,
    *,
    lower_bound,
    upper_bound,
    sqlite_cursor=None,
) -> list[str]:
    """Return usable session passwords without crossing persistence backends."""
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_password
                    FROM course_sessions
                    WHERE platform_id = %s
                      AND status IN ('planned', 'active')
                      AND scheduled_at >= %s
                      AND scheduled_at <= %s
                      AND session_password IS NOT NULL
                      AND session_password != ''
                    ORDER BY scheduled_at ASC
                    """,
                    (platform_id, lower_bound, upper_bound),
                )
                return [
                    str(row["session_password"])
                    for row in cur.fetchall()
                    if row.get("session_password")
                ]

    own_connection = sqlite_cursor is None
    conn = get_db_connection() if own_connection else None
    cursor = conn.cursor() if conn is not None else sqlite_cursor
    try:
        cursor.execute(
            """
            SELECT session_password
            FROM course_sessions
            WHERE platform_id = ?
              AND status IN ('planned', 'active')
              AND scheduled_at >= ?
              AND scheduled_at <= ?
              AND session_password IS NOT NULL
              AND session_password != ''
            ORDER BY scheduled_at ASC
            """,
            (
                platform_id,
                _sqlite_datetime(lower_bound),
                _sqlite_datetime(upper_bound),
            ),
        )
        return [str(row[0]) for row in cursor.fetchall() if row[0]]
    finally:
        if conn is not None:
            conn.close()


def ensure_session_password(session_id: int, *, password: str, generated_at) -> str | None:
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE course_sessions
                    SET session_password = COALESCE(session_password, %s),
                        session_password_generated_at = CASE
                            WHEN session_password IS NULL THEN %s
                            ELSE session_password_generated_at
                        END,
                        updated_at = CASE WHEN session_password IS NULL THEN %s ELSE updated_at END
                    WHERE id = %s
                    RETURNING session_password
                    """,
                    (password, generated_at, generated_at, session_id),
                )
                row = cur.fetchone()
                return row["session_password"] if row else None
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT session_password FROM course_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        if not row:
            return None
        if row[0]:
            return row[0]
        value = _sqlite_datetime(generated_at)
        cursor.execute(
            """
            UPDATE course_sessions
            SET session_password = ?, session_password_generated_at = ?, updated_at = ?
            WHERE id = ? AND session_password IS NULL
            """,
            (password, value, value, session_id),
        )
        conn.commit()
        cursor.execute("SELECT session_password FROM course_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def claim_course_reminder(
    session_id: int,
    reminder_type: str,
    *,
    claimed_at,
    lease_seconds: int | None = None,
) -> bool:
    column = REMINDER_SENT_COLUMNS.get(reminder_type)
    claim_column = REMINDER_CLAIM_COLUMNS.get(reminder_type)
    if not column or not claim_column:
        raise ValueError(f"Type de rappel inconnu: {reminder_type}")
    if lease_seconds is None:
        try:
            lease_seconds = int(os.getenv("COURSE_REMINDER_CLAIM_LEASE_SECONDS", "900"))
        except (TypeError, ValueError):
            lease_seconds = 900
    stale_before = claimed_at - timedelta(seconds=max(60, int(lease_seconds)))
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE course_sessions
                    SET {claim_column} = %s, updated_at = %s
                    WHERE id = %s
                      AND {column} IS NULL
                      AND ({claim_column} IS NULL OR {claim_column} <= %s)
                    RETURNING id
                    """,
                    (claimed_at, claimed_at, session_id, stale_before),
                )
                return cur.fetchone() is not None
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        value = _sqlite_datetime(claimed_at)
        stale_value = _sqlite_datetime(stale_before)
        cursor.execute(
            f"""
            UPDATE course_sessions
            SET {claim_column} = ?, updated_at = ?
            WHERE id = ? AND {column} IS NULL
              AND ({claim_column} IS NULL OR {claim_column} <= ?)
            """,
            (value, value, session_id, stale_value),
        )
        claimed = cursor.rowcount == 1
        conn.commit()
        return claimed
    finally:
        conn.close()


def release_course_reminder_claim(session_id: int, reminder_type: str, *, claimed_at) -> None:
    claim_column = REMINDER_CLAIM_COLUMNS.get(reminder_type)
    if not claim_column:
        raise ValueError(f"Type de rappel inconnu: {reminder_type}")
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE course_sessions SET {claim_column} = NULL WHERE id = %s AND {claim_column} = %s",
                    (session_id, claimed_at),
                )
        return
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE course_sessions SET {claim_column} = NULL WHERE id = ? AND {claim_column} = ?",
            (session_id, _sqlite_datetime(claimed_at)),
        )
        conn.commit()
    finally:
        conn.close()


def complete_course_reminder(
    session_id: int,
    reminder_type: str,
    *,
    claimed_at,
    sent_at,
) -> bool:
    """Set the delivery timestamp only while the caller still owns the claim."""
    column = REMINDER_SENT_COLUMNS.get(reminder_type)
    claim_column = REMINDER_CLAIM_COLUMNS.get(reminder_type)
    if not column or not claim_column:
        raise ValueError(f"Type de rappel inconnu: {reminder_type}")
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE course_sessions
                    SET {column} = %s, {claim_column} = NULL, updated_at = %s
                    WHERE id = %s AND {column} IS NULL AND {claim_column} = %s
                    """,
                    (sent_at, sent_at, session_id, claimed_at),
                )
                return cur.rowcount == 1
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        sent_value = _sqlite_datetime(sent_at)
        cursor.execute(
            f"""
            UPDATE course_sessions
            SET {column} = ?, {claim_column} = NULL, updated_at = ?
            WHERE id = ? AND {column} IS NULL AND {claim_column} = ?
            """,
            (sent_value, sent_value, session_id, _sqlite_datetime(claimed_at)),
        )
        completed = cursor.rowcount == 1
        conn.commit()
        return completed
    finally:
        conn.close()


def claim_audio_generation_session(
    *,
    session_id: int,
    job_id: int,
    folder_id: int,
    started_at,
    stale_started_before=None,
) -> bool:
    if schedule_store_is_postgres():
        stale_sql = ""
        params: list[Any] = [started_at, job_id, folder_id, started_at, session_id]
        if stale_started_before is not None:
            stale_sql = """
                OR (
                    COALESCE(audio_generation_status, 'pending') IN ('running', 'processing')
                    AND audio_generation_completed_at IS NULL
                    AND COALESCE(updated_at, audio_generation_started_at) <= %s
                )
            """
            params.append(stale_started_before)
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT platform_id FROM course_sessions WHERE id = %s",
                    (session_id,),
                )
                session_row = cur.fetchone()
                if not session_row:
                    return False
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (f"course-schedule:{int(session_row['platform_id'])}",),
                )
                cur.execute(
                    f"""
                    UPDATE course_sessions
                    SET audio_generation_status = 'running',
                        audio_generation_started_at = %s,
                        audio_generation_completed_at = NULL,
                        audio_generation_error = NULL,
                        audio_job_id = %s,
                        audio_folder_id = %s,
                        updated_at = %s
                    WHERE id = %s
                      AND (
                        audio_generation_started_at IS NULL
                        OR (
                            COALESCE(audio_generation_status, 'pending') = 'error'
                            AND audio_generation_completed_at IS NULL
                        )
                        {stale_sql}
                      )
                    RETURNING id
                    """,
                    params,
                )
                return cur.fetchone() is not None

    stale_sql = ""
    started_value = _sqlite_datetime(started_at)
    params = [started_value, job_id, folder_id, started_value, session_id]
    if stale_started_before is not None:
        stale_sql = """
            OR (
                COALESCE(audio_generation_status, 'pending') IN ('running', 'processing')
                AND audio_generation_completed_at IS NULL
                AND COALESCE(updated_at, audio_generation_started_at) <= ?
            )
        """
        params.append(_sqlite_datetime(stale_started_before))
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            UPDATE course_sessions
            SET audio_generation_status = 'running',
                audio_generation_started_at = ?,
                audio_generation_completed_at = NULL,
                audio_generation_error = NULL,
                audio_job_id = ?,
                audio_folder_id = ?,
                updated_at = ?
            WHERE id = ?
              AND (
                audio_generation_started_at IS NULL
                OR (
                    COALESCE(audio_generation_status, 'pending') = 'error'
                    AND audio_generation_completed_at IS NULL
                )
                {stale_sql}
              )
            """,
            params,
        )
        claimed = cursor.rowcount == 1
        conn.commit()
        return claimed
    finally:
        conn.close()


def touch_audio_generation_session(session_id: int, *, updated_at, expected_started_at=None) -> bool:
    if schedule_store_is_postgres():
        owner_sql = " AND audio_generation_started_at = %s" if expected_started_at is not None else ""
        params = [updated_at, session_id]
        if expected_started_at is not None:
            params.append(expected_started_at)
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE course_sessions
                    SET audio_generation_status = 'running', updated_at = %s
                    WHERE id = %s AND audio_generation_completed_at IS NULL
                    {owner_sql}
                    """,
                    params,
                )
                return cur.rowcount == 1
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        owner_sql = " AND audio_generation_started_at = ?" if expected_started_at is not None else ""
        params = [_sqlite_datetime(updated_at), session_id]
        if expected_started_at is not None:
            params.append(_sqlite_datetime(expected_started_at))
        cursor.execute(
            f"""
            UPDATE course_sessions
            SET audio_generation_status = 'running', updated_at = ?
            WHERE id = ? AND audio_generation_completed_at IS NULL
            {owner_sql}
            """,
            params,
        )
        changed = cursor.rowcount == 1
        conn.commit()
        return changed
    finally:
        conn.close()


def complete_audio_generation_session(session_id: int, *, completed_at, expected_started_at=None) -> bool:
    if schedule_store_is_postgres():
        owner_sql = " AND audio_generation_started_at = %s" if expected_started_at is not None else ""
        params = [completed_at, completed_at, session_id]
        if expected_started_at is not None:
            params.append(expected_started_at)
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE course_sessions
                    SET audio_generation_status = 'completed',
                        audio_generation_completed_at = %s,
                        audio_generation_error = NULL,
                        updated_at = %s
                    WHERE id = %s AND audio_generation_completed_at IS NULL
                    {owner_sql}
                    """,
                    params,
                )
                return cur.rowcount == 1
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        value = _sqlite_datetime(completed_at)
        owner_sql = " AND audio_generation_started_at = ?" if expected_started_at is not None else ""
        params = [value, value, session_id]
        if expected_started_at is not None:
            params.append(_sqlite_datetime(expected_started_at))
        cursor.execute(
            f"""
            UPDATE course_sessions
            SET audio_generation_status = 'completed',
                audio_generation_completed_at = ?, audio_generation_error = NULL, updated_at = ?
            WHERE id = ? AND audio_generation_completed_at IS NULL
            {owner_sql}
            """,
            params,
        )
        changed = cursor.rowcount == 1
        conn.commit()
        return changed
    finally:
        conn.close()


def fail_audio_generation_session(
    session_id: int,
    *,
    error: str,
    failed_at,
    expected_started_at=None,
) -> bool:
    message = str(error or "")[:500]
    if schedule_store_is_postgres():
        owner_sql = " AND audio_generation_started_at = %s" if expected_started_at is not None else ""
        params = [message, failed_at, session_id]
        if expected_started_at is not None:
            params.append(expected_started_at)
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE course_sessions
                    SET audio_generation_status = 'error', audio_generation_error = %s, updated_at = %s
                    WHERE id = %s AND audio_generation_completed_at IS NULL
                    {owner_sql}
                    """,
                    params,
                )
                return cur.rowcount == 1
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        owner_sql = " AND audio_generation_started_at = ?" if expected_started_at is not None else ""
        params = [message, _sqlite_datetime(failed_at), session_id]
        if expected_started_at is not None:
            params.append(_sqlite_datetime(expected_started_at))
        cursor.execute(
            f"""
            UPDATE course_sessions
            SET audio_generation_status = 'error', audio_generation_error = ?, updated_at = ?
            WHERE id = ? AND audio_generation_completed_at IS NULL
            {owner_sql}
            """,
            params,
        )
        changed = cursor.rowcount == 1
        conn.commit()
        return changed
    finally:
        conn.close()
