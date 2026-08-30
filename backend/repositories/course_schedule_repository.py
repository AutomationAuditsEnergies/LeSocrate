"""Persistence for course schedules, reminders, and scheduled audio state.

The historical implementation kept this aggregate in SQLite even when the
formation pipeline itself was in Postgres. This repository is the cut-over
boundary: scheduling follows either authoritative PostgreSQL domain, so a
``hybrid`` business backend with a PostgreSQL pipeline never touches SQLite.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
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


def _ensure_sqlite_v2_session_columns(cursor) -> None:
    """Keep direct repository users compatible with pre-V2 SQLite fixtures."""
    cursor.execute("PRAGMA table_info(course_sessions)")
    columns = {str(row[1]) for row in cursor.fetchall()}
    for column, column_type in (
        ("module_day_id", "INTEGER"),
        ("local_date", "TEXT"),
    ):
        if column not in columns:
            cursor.execute(
                f"ALTER TABLE course_sessions ADD COLUMN {column} {column_type}"
            )


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
    replace_after=None,
    fill_remaining_to_total=False,
    guard_lower_bound=None,
    guard_upper_bound=None,
    sqlite_connection=None,
    schedule_schema_version: int = 1,
) -> dict[str, Any]:
    """Replace future planned sessions without deleting course history.

    Completed, failed, cancelled and already-started/past rows are immutable
    audit records.  New session indexes continue after the highest retained
    index so the ``(platform_id, session_index)`` key remains stable.
    """
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                replacement_boundary = replace_after or now
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (f"course-schedule:{int(platform_id)}",),
                )
                cur.execute(
                    """
                    SELECT session_index, scheduled_at, module_day_id, local_date
                    FROM course_sessions
                    WHERE platform_id = %s
                      AND local_date IS NOT NULL
                    ORDER BY session_index ASC
                    """,
                    (platform_id,),
                )
                explicit_rows = [dict(row) for row in cur.fetchall()]
                if explicit_rows:
                    if int(schedule_schema_version or 1) < 2:
                        raise ValueError(
                            "Le calendrier validé de cette formation est immuable."
                        )
                    same_schedule = len(explicit_rows) == len(sessions)
                    if same_schedule:
                        for existing, requested in zip(explicit_rows, sessions):
                            existing_at = format_schedule_datetime(
                                existing["scheduled_at"]
                            )
                            requested_at = format_schedule_datetime(
                                requested["scheduled_at"]
                            )
                            requested_module_day_id = requested.get("module_day_id")
                            if (
                                int(existing["session_index"])
                                != int(requested["session_index"])
                                or existing_at != requested_at
                                or str(existing["local_date"])
                                != str(requested.get("local_date"))
                                or (
                                    requested_module_day_id is not None
                                    and int(existing.get("module_day_id") or 0)
                                    != int(requested_module_day_id)
                                )
                            ):
                                same_schedule = False
                                break
                    if same_schedule:
                        return {
                            "deleted_sessions": 0,
                            "retained_sessions": len(explicit_rows),
                            "locked_future_sessions": len(explicit_rows),
                            "inserted_sessions": 0,
                            "idempotent": True,
                        }
                    raise ValueError(
                        "Le calendrier validé de cette formation est immuable."
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
                      AND audio_generation_started_at IS NULL
                      AND audio_generation_completed_at IS NULL
                    """,
                    (platform_id, replacement_boundary),
                )
                deleted_count = int(cur.rowcount or 0)
                cur.execute(
                    """
                    SELECT COUNT(*) AS retained_count,
                           COUNT(*) FILTER (
                               WHERE status IN ('planned', 'active')
                                 AND scheduled_at >= %s
                           ) AS locked_future_count
                    FROM course_sessions
                    WHERE platform_id = %s
                    """,
                    (now, platform_id),
                )
                counts = cur.fetchone() or {}
                retained_count = int(counts.get("retained_count") or 0)
                locked_future_count = int(counts.get("locked_future_count") or 0)
                cur.execute(
                    """
                    SELECT COALESCE(MAX(session_index), 0) AS max_session_index
                    FROM course_sessions
                    WHERE platform_id = %s
                    """,
                    (platform_id,),
                )
                retained_max_index = int(cur.fetchone()["max_session_index"] or 0)
                remaining_count = (
                    max(0, int(total_training_days) - retained_count)
                    if fill_remaining_to_total
                    else len(sessions)
                )
                sessions_to_insert = list(sessions[:remaining_count])
                if sessions_to_insert:
                    cur.executemany(
                        """
                        INSERT INTO course_sessions (
                            platform_id, session_index, scheduled_at, status,
                            module_day_id, local_date,
                            session_password, session_password_generated_at,
                            created_at, updated_at
                        )
                        VALUES (
                            %s, %s, %s, 'planned', %s, %s, %s, %s, %s, %s
                        )
                        """,
                        [
                            (
                                platform_id,
                                retained_max_index + offset,
                                item["scheduled_at"],
                                item.get("module_day_id"),
                                item.get("local_date"),
                                item["session_password"],
                                now,
                                now,
                                now,
                            )
                            for offset, item in enumerate(sessions_to_insert, start=1)
                        ],
                    )
        return {
            "deleted_sessions": deleted_count,
            "retained_sessions": retained_count,
            "locked_future_sessions": locked_future_count,
            "inserted_sessions": len(sessions_to_insert),
        }

    own_connection = sqlite_connection is None
    conn = sqlite_connection or get_db_connection()
    try:
        cursor = conn.cursor()
        _ensure_sqlite_v2_session_columns(cursor)
        now_sqlite = _sqlite_datetime(now)
        replacement_boundary = _sqlite_datetime(replace_after or now)
        cursor.execute(
            """
            SELECT session_index, scheduled_at, module_day_id, local_date
            FROM course_sessions
            WHERE platform_id = ?
              AND local_date IS NOT NULL
            ORDER BY session_index ASC
            """,
            (platform_id,),
        )
        explicit_rows = cursor.fetchall()
        if explicit_rows:
            if int(schedule_schema_version or 1) < 2:
                raise ValueError(
                    "Le calendrier validé de cette formation est immuable."
                )
            same_schedule = len(explicit_rows) == len(sessions)
            if same_schedule:
                for existing, requested in zip(explicit_rows, sessions):
                    requested_module_day_id = requested.get("module_day_id")
                    existing_module_day_id = existing[2]
                    if (
                        int(existing[0]) != int(requested["session_index"])
                        or str(existing[1])
                        != str(_sqlite_datetime(requested["scheduled_at"]))
                        or str(existing[3]) != str(requested.get("local_date"))
                        or (
                            requested_module_day_id is not None
                            and int(existing_module_day_id or 0)
                            != int(requested_module_day_id)
                        )
                    ):
                        same_schedule = False
                        break
            if same_schedule:
                return {
                    "deleted_sessions": 0,
                    "retained_sessions": len(explicit_rows),
                    "locked_future_sessions": len(explicit_rows),
                    "inserted_sessions": 0,
                    "idempotent": True,
                }
            raise ValueError(
                "Le calendrier validé de cette formation est immuable."
            )
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
              AND audio_generation_started_at IS NULL
              AND audio_generation_completed_at IS NULL
            """,
            (platform_id, replacement_boundary),
        )
        deleted_count = int(cursor.rowcount or 0)
        cursor.execute(
            """
            SELECT COUNT(*),
                   SUM(CASE WHEN status IN ('planned', 'active') AND scheduled_at >= ? THEN 1 ELSE 0 END)
            FROM course_sessions
            WHERE platform_id = ?
            """,
            (now_sqlite, platform_id),
        )
        counts = cursor.fetchone() or (0, 0)
        retained_count = int(counts[0] or 0)
        locked_future_count = int(counts[1] or 0)
        cursor.execute(
            """
            SELECT COALESCE(MAX(session_index), 0)
            FROM course_sessions
            WHERE platform_id = ?
            """,
            (platform_id,),
        )
        retained_max_index = int(cursor.fetchone()[0] or 0)
        remaining_count = (
            max(0, int(total_training_days) - retained_count)
            if fill_remaining_to_total
            else len(sessions)
        )
        sessions_to_insert = list(sessions[:remaining_count])
        cursor.executemany(
            """
            INSERT INTO course_sessions (
                platform_id, session_index, scheduled_at, status,
                module_day_id, local_date,
                session_password, session_password_generated_at,
                created_at, updated_at
            )
            VALUES (?, ?, ?, 'planned', ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    platform_id,
                    retained_max_index + offset,
                    _sqlite_datetime(item["scheduled_at"]),
                    item.get("module_day_id"),
                    item.get("local_date"),
                    item["session_password"],
                    now_sqlite,
                    now_sqlite,
                    now_sqlite,
                )
                for offset, item in enumerate(sessions_to_insert, start=1)
            ],
        )
        if own_connection:
            conn.commit()
        return {
            "deleted_sessions": deleted_count,
            "retained_sessions": retained_count,
            "locked_future_sessions": locked_future_count,
            "inserted_sessions": len(sessions_to_insert),
        }
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


def list_course_sessions(platform_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
    """Return the product-facing session state for one owned platform."""
    safe_limit = max(1, min(int(limit or 50), 1000))
    base_columns = """
        id, platform_id, session_index, scheduled_at, status,
        audio_generation_status, audio_generation_started_at,
        audio_generation_completed_at, audio_generation_attempts,
        audio_generation_next_retry_at, audio_job_id, audio_folder_id,
        audio_storage_prefix,
        postponed_from, postponed_at, postponement_count,
        created_at, updated_at
    """
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {base_columns}, module_day_id, local_date
                    FROM course_sessions
                    WHERE platform_id = %s
                    ORDER BY session_index ASC
                    LIMIT %s
                    """,
                    (platform_id, safe_limit),
                )
                return [dict(row) for row in cur.fetchall()]
    conn = get_db_connection()
    try:
        conn.row_factory = __import__("sqlite3").Row
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(course_sessions)")
        sqlite_columns = {str(row[1]) for row in cursor.fetchall()}
        v2_columns = (
            "module_day_id, local_date"
            if {"module_day_id", "local_date"}.issubset(sqlite_columns)
            else "NULL AS module_day_id, NULL AS local_date"
        )
        cursor.execute(
            f"""
            SELECT {base_columns}, {v2_columns}
            FROM course_sessions
            WHERE platform_id = ?
            ORDER BY session_index ASC
            LIMIT ?
            """,
            (platform_id, safe_limit),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_audio_generation_session(platform_id: int, session_id: int) -> dict[str, Any] | None:
    """Resolve a scheduled audio job through its platform boundary."""
    postgres = schedule_store_is_postgres()
    ph = "%s" if postgres else "?"
    query = f"""
        SELECT cs.id, cs.platform_id, cs.session_index, cs.scheduled_at,
               cs.module_day_id, cs.local_date,
               cs.status, cs.audio_generation_status,
               cs.audio_generation_started_at, cs.audio_generation_completed_at,
               cs.audio_generation_attempts, cs.audio_generation_next_retry_at,
               cs.audio_storage_prefix,
               pc.name,
               COALESCE(
                   pc.source_formation_id,
                   (
                       SELECT fm.source_pipeline_job_id
                       FROM formation_modules fm
                       WHERE fm.id = pc.source_module_id
                       LIMIT 1
                   ),
                   (
                       SELECT j.id FROM formation_pipeline_jobs j
                       WHERE j.platform_id = cs.platform_id
                       ORDER BY j.id DESC LIMIT 1
                   )
               ) AS formation_job_id
        FROM course_sessions cs
        JOIN platform_config pc ON pc.id = cs.platform_id
        WHERE cs.platform_id = {ph} AND cs.id = {ph}
    """
    if postgres:
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (platform_id, session_id))
                row = cur.fetchone()
                return dict(row) if row else None
    conn = get_db_connection()
    try:
        conn.row_factory = __import__("sqlite3").Row
        cursor = conn.cursor()
        cursor.execute(query, (platform_id, session_id))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_scheduled_audio_completion_readiness(
    platform_id: int,
    formation_job_id: int,
    *,
    required_session_count: int,
    completing_session_id: int | None = None,
) -> dict[str, Any]:
    """Return whether every required occurrence owns a completed audio asset.

    Course-session status is deliberately not restricted to ``planned`` and
    ``active``: the room lifecycle can mark an occurrence ``completed`` after
    the course while its immutable audio bookkeeping must still count. A
    cancelled occurrence is the sole exclusion.
    """
    postgres = schedule_store_is_postgres()
    ph = "%s" if postgres else "?"
    completing_sql = ""
    params: list[Any] = [int(formation_job_id)]
    if completing_session_id is not None:
        completing_sql = f"""
                    OR (
                        id = {ph}
                        AND audio_generation_status IN ('running', 'processing')
                        AND audio_job_id = {ph}
                        AND audio_folder_id IS NOT NULL
                    )
        """
        params.extend([int(completing_session_id), int(formation_job_id)])
    query = f"""
        SELECT
            COUNT(*) AS session_count,
            COALESCE(SUM(
                CASE
                    WHEN (
                        audio_generation_status = 'completed'
                        AND audio_generation_completed_at IS NOT NULL
                        AND audio_job_id = {ph}
                        AND audio_folder_id IS NOT NULL
                    )
                    {completing_sql}
                    THEN 1 ELSE 0
                END
            ), 0) AS completed_count
        FROM course_sessions
        WHERE platform_id = {ph}
          AND status != 'cancelled'
    """
    params.append(int(platform_id))
    if postgres:
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                row = dict(cur.fetchone())
    else:
        conn = get_db_connection()
        try:
            conn.row_factory = __import__("sqlite3").Row
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            row = dict(cursor.fetchone())
        finally:
            conn.close()

    required = max(1, int(required_session_count or 1))
    session_count = int(row.get("session_count") or 0)
    completed_count = int(row.get("completed_count") or 0)
    ready = session_count >= required and completed_count >= required
    return {
        "ready": ready,
        "platform_id": int(platform_id),
        "formation_job_id": int(formation_job_id),
        "required_session_count": required,
        "session_count": session_count,
        "completed_count": completed_count,
        "remaining_count": max(0, required - completed_count),
    }


def get_course_session_postponement_by_key(platform_id: int, idempotency_key: str | None) -> dict[str, Any] | None:
    """Return a prior report so retries remain stable even after the course ends."""
    clean_key = str(idempotency_key or "").strip()[:120]
    if not clean_key:
        return None
    columns = """
        id, platform_id, session_id, session_index, previous_scheduled_at,
        new_scheduled_at, mode, affected_session_count, idempotency_key,
        impact_json, created_at
    """
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {columns} FROM course_session_postponements "
                    "WHERE platform_id = %s AND idempotency_key = %s",
                    (platform_id, clean_key),
                )
                row = cur.fetchone()
                return dict(row) if row else None
    conn = get_db_connection()
    try:
        conn.row_factory = __import__("sqlite3").Row
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT {columns} FROM course_session_postponements "
            "WHERE platform_id = ? AND idempotency_key = ?",
            (platform_id, clean_key),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def apply_course_session_postponement(
    platform_id: int,
    session_id: int,
    *,
    changes: list[dict[str, Any]],
    mode: str,
    reason: str | None,
    idempotency_key: str | None,
    actor_account_id: int | None,
    postponed_at,
) -> dict[str, Any]:
    """Move one pedagogical lesson and its successors as one durable operation.

    Audio ownership is deliberately untouched: every row keeps its stable id,
    session_index and audio fields. Reminder claims are cleared because their
    former delivery dates are no longer valid.
    """
    normalized_changes = [dict(item) for item in changes]
    if not normalized_changes or int(normalized_changes[0]["id"]) != int(session_id):
        raise ValueError("Le report ne contient aucune séance valide")
    impact_json = json.dumps(
        [
            {
                "id": int(item["id"]),
                "session_index": int(item["session_index"]),
                "previous_scheduled_at": format_schedule_datetime(item["expected_scheduled_at"]),
                "new_scheduled_at": format_schedule_datetime(item["new_scheduled_at"]),
            }
            for item in normalized_changes
        ],
        ensure_ascii=False,
    )
    clean_reason = str(reason or "").strip()[:500] or None
    clean_key = str(idempotency_key or "").strip()[:120] or None

    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (f"course-schedule:{int(platform_id)}",),
                )
                if clean_key:
                    cur.execute(
                        """
                        SELECT id, session_id, impact_json
                        FROM course_session_postponements
                        WHERE platform_id = %s AND idempotency_key = %s
                        """,
                        (platform_id, clean_key),
                    )
                    existing = cur.fetchone()
                    if existing:
                        if int(existing["session_id"]) != int(session_id):
                            raise ValueError("Cette demande de report a déjà été utilisée")
                        return {
                            "audit_id": int(existing["id"]),
                            "idempotent": True,
                            "changes": json.loads(existing.get("impact_json") or "[]"),
                        }
                cur.execute(
                    """
                    SELECT id, session_index, scheduled_at, status
                    FROM course_sessions
                    WHERE platform_id = %s AND id = ANY(%s)
                    FOR UPDATE
                    """,
                    (platform_id, [int(item["id"]) for item in normalized_changes]),
                )
                locked = {int(row["id"]): dict(row) for row in cur.fetchall()}
                target = locked.get(int(session_id))
                if not target or target.get("status") != "planned":
                    raise ValueError("Ce cours ne peut plus être reporté")
                if len(locked) != len(normalized_changes):
                    raise ValueError("Le planning a changé. Rechargez-le avant de confirmer")
                for item in normalized_changes:
                    cur.execute(
                        """
                        UPDATE course_sessions
                        SET scheduled_at = %s,
                            postponed_from = scheduled_at,
                            postponed_at = %s,
                            postponement_count = COALESCE(postponement_count, 0) + 1,
                            reminder_previous_evening_sent_at = NULL,
                            reminder_5min_sent_at = NULL,
                            reminder_previous_evening_claimed_at = NULL,
                            reminder_5min_claimed_at = NULL,
                            updated_at = %s
                        WHERE id = %s AND platform_id = %s
                          AND status = 'planned' AND scheduled_at = %s
                        """,
                        (
                            item["new_scheduled_at"],
                            postponed_at,
                            postponed_at,
                            int(item["id"]),
                            platform_id,
                            item["expected_scheduled_at"],
                        ),
                    )
                    if cur.rowcount != 1:
                        raise ValueError("Le planning a changé. Rechargez-le avant de confirmer")
                cur.execute(
                    "DELETE FROM course_reminder_deliveries WHERE session_id = ANY(%s)",
                    ([int(item["id"]) for item in normalized_changes],),
                )
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
                next_session = cur.fetchone()
                if next_session:
                    cur.execute(
                        """
                        INSERT INTO cours_config (id, platform_id, heure_debut)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            platform_id = EXCLUDED.platform_id,
                            heure_debut = EXCLUDED.heure_debut
                        """,
                        (platform_id, platform_id, next_session["scheduled_at"]),
                    )
                target_change = normalized_changes[0]
                cur.execute(
                    """
                    INSERT INTO course_session_postponements (
                        platform_id, session_id, session_index,
                        previous_scheduled_at, new_scheduled_at, mode, reason,
                        affected_session_count, idempotency_key, actor_account_id,
                        impact_json, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        platform_id,
                        session_id,
                        int(target_change["session_index"]),
                        target_change["expected_scheduled_at"],
                        target_change["new_scheduled_at"],
                        mode,
                        clean_reason,
                        len(normalized_changes),
                        clean_key,
                        actor_account_id,
                        impact_json,
                        postponed_at,
                    ),
                )
                audit = cur.fetchone()
                return {
                    "audit_id": int(audit["id"]),
                    "idempotent": False,
                    "changes": json.loads(impact_json),
                }
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        _ensure_sqlite_reminder_tables(cursor)
        if clean_key:
            cursor.execute(
                """
                SELECT id, session_id, impact_json
                FROM course_session_postponements
                WHERE platform_id = ? AND idempotency_key = ?
                """,
                (platform_id, clean_key),
            )
            existing = cursor.fetchone()
            if existing:
                if int(existing[1]) != int(session_id):
                    raise ValueError("Cette demande de report a déjà été utilisée")
                conn.commit()
                return {
                    "audit_id": int(existing[0]),
                    "idempotent": True,
                    "changes": json.loads(existing[2] or "[]"),
                }
        cursor.execute(
            "SELECT status FROM course_sessions WHERE id = ? AND platform_id = ?",
            (session_id, platform_id),
        )
        target = cursor.fetchone()
        if not target or target[0] != "planned":
            raise ValueError("Ce cours ne peut plus être reporté")
        postponed_value = _sqlite_datetime(postponed_at)
        for item in normalized_changes:
            cursor.execute(
                """
                UPDATE course_sessions
                SET scheduled_at = ?, postponed_from = scheduled_at,
                    postponed_at = ?, postponement_count = COALESCE(postponement_count, 0) + 1,
                    reminder_previous_evening_sent_at = NULL,
                    reminder_5min_sent_at = NULL,
                    reminder_previous_evening_claimed_at = NULL,
                    reminder_5min_claimed_at = NULL,
                    updated_at = ?
                WHERE id = ? AND platform_id = ?
                  AND status = 'planned' AND scheduled_at = ?
                """,
                (
                    _sqlite_datetime(item["new_scheduled_at"]),
                    postponed_value,
                    postponed_value,
                    int(item["id"]),
                    platform_id,
                    _sqlite_datetime(item["expected_scheduled_at"]),
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("Le planning a changé. Rechargez-le avant de confirmer")
        placeholders = ",".join("?" for _ in normalized_changes)
        cursor.execute(
            f"DELETE FROM course_reminder_deliveries WHERE session_id IN ({placeholders})",
            [int(item["id"]) for item in normalized_changes],
        )
        target_change = normalized_changes[0]
        cursor.execute(
            """
            INSERT INTO course_session_postponements (
                platform_id, session_id, session_index,
                previous_scheduled_at, new_scheduled_at, mode, reason,
                affected_session_count, idempotency_key, actor_account_id,
                impact_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                platform_id,
                session_id,
                int(target_change["session_index"]),
                _sqlite_datetime(target_change["expected_scheduled_at"]),
                _sqlite_datetime(target_change["new_scheduled_at"]),
                mode,
                clean_reason,
                len(normalized_changes),
                clean_key,
                actor_account_id,
                impact_json,
                postponed_value,
            ),
        )
        audit_id = int(cursor.lastrowid)
        conn.commit()
        return {"audit_id": audit_id, "idempotent": False, "changes": json.loads(impact_json)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_audio_waiting_for_content(session_id: int, *, updated_at) -> bool:
    """Expose a recoverable J-1 warning while course material is not ready."""
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE course_sessions
                    SET audio_generation_status = 'waiting_content', updated_at = %s
                    WHERE id = %s
                      AND status IN ('planned', 'active')
                      AND audio_generation_started_at IS NULL
                      AND audio_generation_completed_at IS NULL
                    """,
                    (updated_at, session_id),
                )
                return cur.rowcount == 1
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE course_sessions
            SET audio_generation_status = 'waiting_content', updated_at = ?
            WHERE id = ?
              AND status IN ('planned', 'active')
              AND audio_generation_started_at IS NULL
              AND audio_generation_completed_at IS NULL
            """,
            (_sqlite_datetime(updated_at), session_id),
        )
        changed = cursor.rowcount == 1
        conn.commit()
        return changed
    finally:
        conn.close()


def list_course_schedule_dashboard_states(platform_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Batch-load upcoming occurrences and recent completed history."""
    ids = sorted({int(platform_id) for platform_id in platform_ids if platform_id})
    if not ids or not schedule_store_is_postgres():
        return {}
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cfg.platform_id, cfg.timezone, cfg.start_time,
                       next_session.id AS session_id,
                       next_session.session_index,
                       next_session.scheduled_at,
                       next_session.audio_generation_status,
                       next_session.audio_generation_started_at,
                       next_session.audio_generation_completed_at,
                       next_session.audio_generation_attempts,
                       next_session.audio_generation_next_retry_at,
                       upcoming_sessions.items AS upcoming_sessions,
                       past_sessions.items AS past_sessions
                FROM course_schedule_config cfg
                LEFT JOIN LATERAL (
                    SELECT cs.*
                    FROM course_sessions cs
                    WHERE cs.platform_id = cfg.platform_id
                      AND cs.status IN ('planned', 'active')
                    ORDER BY cs.scheduled_at ASC
                    LIMIT 1
                ) next_session ON TRUE
                LEFT JOIN LATERAL (
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'id', items.id,
                            'session_index', items.session_index,
                            'scheduled_at', items.scheduled_at,
                            'status', items.status,
                            'audio_generation_status', items.audio_generation_status,
                            'audio_generation_started_at', items.audio_generation_started_at,
                            'audio_generation_completed_at', items.audio_generation_completed_at,
                            'audio_generation_attempts', items.audio_generation_attempts,
                            'audio_generation_next_retry_at', items.audio_generation_next_retry_at,
                            'postponement_count', items.postponement_count,
                            'postponed_from', items.postponed_from,
                            'postponed_at', items.postponed_at
                        ) ORDER BY items.scheduled_at ASC
                    ) AS items
                    FROM (
                        SELECT cs.*
                        FROM course_sessions cs
                        WHERE cs.platform_id = cfg.platform_id
                          AND cs.status IN ('planned', 'active')
                        ORDER BY cs.scheduled_at ASC
                        LIMIT 3
                    ) items
                ) upcoming_sessions ON TRUE
                LEFT JOIN LATERAL (
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'id', items.id,
                            'session_index', items.session_index,
                            'scheduled_at', items.scheduled_at,
                            'status', items.status,
                            'audio_generation_status', items.audio_generation_status,
                            'audio_generation_started_at', items.audio_generation_started_at,
                            'audio_generation_completed_at', items.audio_generation_completed_at,
                            'audio_generation_attempts', items.audio_generation_attempts,
                            'audio_generation_next_retry_at', items.audio_generation_next_retry_at,
                            'postponement_count', items.postponement_count,
                            'postponed_from', items.postponed_from,
                            'postponed_at', items.postponed_at
                        ) ORDER BY items.scheduled_at DESC
                    ) AS items
                    FROM (
                        SELECT cs.*
                        FROM course_sessions cs
                        WHERE cs.platform_id = cfg.platform_id
                          AND cs.status = 'completed'
                        ORDER BY cs.scheduled_at DESC
                        LIMIT 20
                    ) items
                ) past_sessions ON TRUE
                WHERE cfg.platform_id = ANY(%s)
                """,
                (ids,),
            )
            return {
                int(row["platform_id"]): dict(row)
                for row in cur.fetchall()
            }


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
                    "SELECT email, nom, prenom FROM course_reminder_recipients WHERE platform_id = %s ORDER BY LOWER(email)",
                    (platform_id,),
                )
                for row in cur.fetchall():
                    email = str(row["email"] or "").strip().lower()
                    if email:
                        recipients[email] = {"email": email, "nom": row.get("nom") or "", "prenom": row.get("prenom") or ""}
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
            "SELECT email, nom, prenom FROM course_reminder_recipients WHERE platform_id = ? ORDER BY email COLLATE NOCASE",
            (platform_id,),
        )
        for email, nom, prenom in cursor.fetchall():
            email = str(email or "").strip().lower()
            if email:
                recipients[email] = {"email": email, "nom": nom or "", "prenom": prenom or ""}
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


def _ensure_sqlite_reminder_recipient_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS course_reminder_recipients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL,
            email TEXT NOT NULL,
            nom TEXT NOT NULL DEFAULT '',
            prenom TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(platform_id, email)
        )
        """
    )
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(course_reminder_recipients)").fetchall()}
    if "nom" not in columns:
        cursor.execute("ALTER TABLE course_reminder_recipients ADD COLUMN nom TEXT NOT NULL DEFAULT ''")
    if "prenom" not in columns:
        cursor.execute("ALTER TABLE course_reminder_recipients ADD COLUMN prenom TEXT NOT NULL DEFAULT ''")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_course_reminder_recipients_platform "
        "ON course_reminder_recipients(platform_id)"
    )


def _ensure_sqlite_reminder_tables(cursor) -> None:
    _ensure_sqlite_reminder_recipient_table(cursor)
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


def list_explicit_course_reminder_recipients(platform_id: int) -> list[dict[str, Any]]:
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, email, nom, prenom, created_at
                    FROM course_reminder_recipients
                    WHERE platform_id = %s
                    ORDER BY LOWER(email)
                    """,
                    (int(platform_id),),
                )
                return [
                    {
                        "id": int(row["id"]),
                        "email": row["email"],
                        "nom": row.get("nom") or "",
                        "prenom": row.get("prenom") or "",
                        "created_at": format_schedule_datetime(row["created_at"]),
                    }
                    for row in cur.fetchall()
                ]

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        _ensure_sqlite_reminder_recipient_table(cursor)
        cursor.execute(
            """
            SELECT id, email, nom, prenom, created_at
            FROM course_reminder_recipients
            WHERE platform_id = ?
            ORDER BY email COLLATE NOCASE
            """,
            (int(platform_id),),
        )
        return [
            {"id": int(row[0]), "email": row[1], "nom": row[2] or "", "prenom": row[3] or "", "created_at": row[4]}
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def add_explicit_course_reminder_recipients(
    platform_id: int,
    emails: list[Any],
    *,
    created_at,
) -> list[dict[str, Any]]:
    if len(emails or []) > 1000:
        raise ValueError("1000 emails maximum par lot")
    normalized_by_email: dict[str, dict[str, str]] = {}
    for item in emails or []:
        if isinstance(item, dict):
            email = str(item.get("email") or "").strip().lower()
            nom = str(item.get("nom") or "").strip()
            prenom = str(item.get("prenom") or "").strip()
        else:
            email = str(item or "").strip().lower()
            nom = ""
            prenom = ""
        if email:
            normalized_by_email[email] = {"email": email, "nom": nom, "prenom": prenom}
    normalized = [normalized_by_email[email] for email in sorted(normalized_by_email)]
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO course_reminder_recipients (platform_id, email, nom, prenom, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (platform_id, email) DO UPDATE SET
                        nom = CASE WHEN EXCLUDED.nom <> '' THEN EXCLUDED.nom ELSE course_reminder_recipients.nom END,
                        prenom = CASE WHEN EXCLUDED.prenom <> '' THEN EXCLUDED.prenom ELSE course_reminder_recipients.prenom END
                    """,
                    [(int(platform_id), item["email"], item["nom"], item["prenom"], created_at) for item in normalized],
                )
        return list_explicit_course_reminder_recipients(platform_id)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        _ensure_sqlite_reminder_recipient_table(cursor)
        cursor.executemany(
            """
            INSERT INTO course_reminder_recipients (platform_id, email, nom, prenom, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(platform_id, email) DO UPDATE SET
                nom = CASE WHEN excluded.nom <> '' THEN excluded.nom ELSE course_reminder_recipients.nom END,
                prenom = CASE WHEN excluded.prenom <> '' THEN excluded.prenom ELSE course_reminder_recipients.prenom END
            """,
            [
                (int(platform_id), item["email"], item["nom"], item["prenom"], _sqlite_datetime(created_at))
                for item in normalized
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return list_explicit_course_reminder_recipients(platform_id)


def delete_explicit_course_reminder_recipient(platform_id: int, recipient_id: int) -> bool:
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM course_reminder_recipients
                    WHERE id = %s AND platform_id = %s
                    """,
                    (int(recipient_id), int(platform_id)),
                )
                return cur.rowcount == 1

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        _ensure_sqlite_reminder_tables(cursor)
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "DELETE FROM course_reminder_deliveries WHERE recipient_id = ? AND platform_id = ?",
            (int(recipient_id), int(platform_id)),
        )
        cursor.execute(
            "DELETE FROM course_reminder_rule_recipients WHERE recipient_id = ?",
            (int(recipient_id),),
        )
        cursor.execute(
            "DELETE FROM course_reminder_recipients WHERE id = ? AND platform_id = ?",
            (int(recipient_id), int(platform_id)),
        )
        changed = cursor.rowcount == 1
        conn.commit()
        return changed
    finally:
        conn.close()


DEFAULT_COURSE_REMINDER_RULES = (
    {
        "system_key": "previous_evening",
        "name": "La veille au soir",
        "trigger_mode": "local_day_time",
        "days_before": 1,
        "minutes_before": None,
        "subject_template": "Votre formation commence demain",
        "content_template": (
            "Votre cours commence le {date} à {time}.\n\n"
            "Cliquez ici pour vous connecter directement : {class_url_connexion}\n\n"
            "Cliquez ici pour vous connecter avec votre code {session_code} : "
            "{class_url_accueil}"
        ),
    },
    {
        "system_key": "five_minutes_before",
        "name": "5 minutes avant",
        "trigger_mode": "relative_minutes",
        "days_before": None,
        "minutes_before": 5,
        "subject_template": "Le cours commence dans 5 minutes !",
        "content_template": (
            "Votre cours commence le {date} à {time}.\n\n"
            "Cliquez ici pour vous connecter directement : {class_url_connexion}\n\n"
            "Cliquez ici pour vous connecter avec votre code {session_code} : "
            "{class_url_accueil}"
        ),
    },
)


def ensure_default_course_reminder_rules(
    platform_id: int,
    *,
    previous_evening_hour: int = 18,
    now=None,
) -> None:
    """Seed the two historical reminders without overwriting center edits."""
    now = now or datetime.now(FRANCE_TZ)
    local_time = f"{max(0, min(int(previous_evening_hour), 23)):02d}:00"
    rows = []
    for rule in DEFAULT_COURSE_REMINDER_RULES:
        rows.append(
            (
                int(platform_id),
                rule["system_key"],
                rule["name"],
                rule["trigger_mode"],
                rule["days_before"],
                rule["minutes_before"],
                local_time if rule["trigger_mode"] == "local_day_time" else None,
                rule["subject_template"],
                rule["content_template"],
                "all",
                now,
                now,
            )
        )
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO course_reminder_rules (
                        platform_id, system_key, name, trigger_mode, days_before,
                        minutes_before, local_time, subject_template, content_template,
                        recipient_scope, is_active, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s)
                    ON CONFLICT (platform_id, system_key) WHERE system_key IS NOT NULL
                    DO NOTHING
                    """,
                    rows,
                )
        return
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        _ensure_sqlite_reminder_tables(cursor)
        cursor.executemany(
            """
            INSERT OR IGNORE INTO course_reminder_rules (
                platform_id, system_key, name, trigger_mode, days_before,
                minutes_before, local_time, subject_template, content_template,
                recipient_scope, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            [
                (*row[:-2], _sqlite_datetime(row[-2]), _sqlite_datetime(row[-1]))
                for row in rows
            ],
        )
        conn.commit()
    finally:
        conn.close()


def ensure_default_course_reminder_rules_for_schedules(
    *,
    previous_evening_hour: int = 18,
    now=None,
    sqlite_cursor=None,
) -> None:
    """Bulk-seed defaults for every scheduled platform in constant queries."""
    now = now or datetime.now(FRANCE_TZ)
    local_time = f"{max(0, min(int(previous_evening_hour), 23)):02d}:00"
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                for rule in DEFAULT_COURSE_REMINDER_RULES:
                    cur.execute(
                        """
                        INSERT INTO course_reminder_rules (
                            platform_id, system_key, name, trigger_mode, days_before,
                            minutes_before, local_time, subject_template, content_template,
                            recipient_scope, is_active, created_at, updated_at
                        )
                        SELECT scheduled.platform_id, %s, %s, %s, %s, %s, %s,
                               %s, %s, 'all', TRUE, %s, %s
                        FROM (
                            SELECT DISTINCT platform_id
                            FROM course_sessions
                            WHERE status IN ('planned', 'active')
                        ) scheduled
                        WHERE TRUE
                        ON CONFLICT (platform_id, system_key) WHERE system_key IS NOT NULL
                        DO NOTHING
                        """,
                        (
                            rule["system_key"], rule["name"], rule["trigger_mode"],
                            rule["days_before"], rule["minutes_before"],
                            local_time if rule["trigger_mode"] == "local_day_time" else None,
                            rule["subject_template"], rule["content_template"], now, now,
                        ),
                    )
        return

    own_connection = sqlite_cursor is None
    conn = get_db_connection() if own_connection else None
    cursor = conn.cursor() if conn is not None else sqlite_cursor
    try:
        _ensure_sqlite_reminder_tables(cursor)
        for rule in DEFAULT_COURSE_REMINDER_RULES:
            cursor.execute(
                """
                INSERT OR IGNORE INTO course_reminder_rules (
                    platform_id, system_key, name, trigger_mode, days_before,
                    minutes_before, local_time, subject_template, content_template,
                    recipient_scope, is_active, created_at, updated_at
                )
                SELECT scheduled.platform_id, ?, ?, ?, ?, ?, ?, ?, ?, 'all', 1, ?, ?
                FROM (
                    SELECT DISTINCT platform_id
                    FROM course_sessions
                    WHERE status IN ('planned', 'active')
                ) scheduled
                """,
                (
                    rule["system_key"], rule["name"], rule["trigger_mode"],
                    rule["days_before"], rule["minutes_before"],
                    local_time if rule["trigger_mode"] == "local_day_time" else None,
                    rule["subject_template"], rule["content_template"],
                    _sqlite_datetime(now), _sqlite_datetime(now),
                ),
            )
        if conn is not None:
            conn.commit()
    finally:
        if conn is not None:
            conn.close()


def _normalize_rule_row(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["id"] = int(result["id"])
    result["platform_id"] = int(result["platform_id"])
    result["is_active"] = bool(result.get("is_active"))
    local_time = result.get("local_time")
    if local_time is not None and hasattr(local_time, "strftime"):
        result["local_time"] = local_time.strftime("%H:%M")
    elif local_time:
        result["local_time"] = str(local_time)[:5]
    result["created_at"] = format_schedule_datetime(result.get("created_at"))
    result["updated_at"] = format_schedule_datetime(result.get("updated_at"))
    result["recipient_ids"] = []
    return result


def list_course_reminder_rules(platform_id: int) -> list[dict[str, Any]]:
    columns = (
        "id, platform_id, system_key, name, trigger_mode, days_before, minutes_before, "
        "local_time, subject_template, content_template, recipient_scope, is_active, "
        "created_at, updated_at"
    )
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {columns} FROM course_reminder_rules "
                    "WHERE platform_id = %s ORDER BY created_at, id",
                    (int(platform_id),),
                )
                rules = [_normalize_rule_row(dict(row)) for row in cur.fetchall()]
                if rules:
                    by_id = {rule["id"]: rule for rule in rules}
                    cur.execute(
                        """
                        SELECT rr.rule_id, rr.recipient_id
                        FROM course_reminder_rule_recipients rr
                        JOIN course_reminder_rules r ON r.id = rr.rule_id
                        WHERE r.platform_id = %s
                        ORDER BY rr.recipient_id
                        """,
                        (int(platform_id),),
                    )
                    for row in cur.fetchall():
                        if int(row["rule_id"]) in by_id:
                            by_id[int(row["rule_id"])]["recipient_ids"].append(int(row["recipient_id"]))
                return rules
    conn = get_db_connection()
    try:
        conn.row_factory = __import__("sqlite3").Row
        cursor = conn.cursor()
        _ensure_sqlite_reminder_tables(cursor)
        cursor.execute(
            f"SELECT {columns} FROM course_reminder_rules "
            "WHERE platform_id = ? ORDER BY created_at, id",
            (int(platform_id),),
        )
        rules = [_normalize_rule_row(dict(row)) for row in cursor.fetchall()]
        by_id = {rule["id"]: rule for rule in rules}
        if rules:
            cursor.execute(
                """
                SELECT rr.rule_id, rr.recipient_id
                FROM course_reminder_rule_recipients rr
                JOIN course_reminder_rules r ON r.id = rr.rule_id
                WHERE r.platform_id = ? ORDER BY rr.recipient_id
                """,
                (int(platform_id),),
            )
            for row in cursor.fetchall():
                if int(row[0]) in by_id:
                    by_id[int(row[0])]["recipient_ids"].append(int(row[1]))
        return rules
    finally:
        conn.close()


def save_course_reminder_rule(
    platform_id: int,
    *,
    rule_id: int | None,
    name: str,
    trigger_mode: str,
    days_before: int | None,
    minutes_before: int | None,
    local_time: str | None,
    subject_template: str,
    content_template: str,
    recipient_scope: str,
    recipient_ids: list[int],
    is_active: bool,
    now,
) -> dict[str, Any] | None:
    """Create/update one rule and atomically replace its explicit audience."""
    normalized_ids = sorted({int(value) for value in recipient_ids or []})
    values = (
        str(name), str(trigger_mode), days_before, minutes_before, local_time,
        str(subject_template), str(content_template), str(recipient_scope), bool(is_active), now,
    )
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                if normalized_ids:
                    cur.execute(
                        "SELECT id FROM course_reminder_recipients WHERE platform_id = %s AND id = ANY(%s)",
                        (int(platform_id), normalized_ids),
                    )
                    if {int(row["id"]) for row in cur.fetchall()} != set(normalized_ids):
                        raise ValueError("Un destinataire sélectionné n'appartient pas à cette plateforme")
                if rule_id is None:
                    cur.execute(
                        """
                        INSERT INTO course_reminder_rules (
                            platform_id, name, trigger_mode, days_before, minutes_before,
                            local_time, subject_template, content_template, recipient_scope,
                            is_active, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (int(platform_id), *values[:-1], now, now),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE course_reminder_rules
                        SET name = %s, trigger_mode = %s, days_before = %s,
                            minutes_before = %s, local_time = %s, subject_template = %s,
                            content_template = %s, recipient_scope = %s, is_active = %s,
                            updated_at = %s
                        WHERE id = %s AND platform_id = %s
                        RETURNING id
                        """,
                        (*values, int(rule_id), int(platform_id)),
                    )
                saved = cur.fetchone()
                if not saved:
                    return None
                saved_id = int(saved["id"])
                cur.execute("DELETE FROM course_reminder_rule_recipients WHERE rule_id = %s", (saved_id,))
                if recipient_scope == "selected_explicit" and normalized_ids:
                    cur.executemany(
                        "INSERT INTO course_reminder_rule_recipients (rule_id, recipient_id) VALUES (%s, %s)",
                        [(saved_id, recipient_id) for recipient_id in normalized_ids],
                    )
                # A changed unsent occurrence must be recalculated from the
                # new trigger/audience/template on the next scheduler tick.
                cur.execute(
                    "DELETE FROM course_reminder_deliveries WHERE rule_id = %s AND status != 'sent'",
                    (saved_id,),
                )
        return next((rule for rule in list_course_reminder_rules(platform_id) if rule["id"] == saved_id), None)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        _ensure_sqlite_reminder_tables(cursor)
        cursor.execute("BEGIN IMMEDIATE")
        if normalized_ids:
            placeholders = ",".join("?" for _ in normalized_ids)
            cursor.execute(
                f"SELECT id FROM course_reminder_recipients WHERE platform_id = ? AND id IN ({placeholders})",
                (int(platform_id), *normalized_ids),
            )
            if {int(row[0]) for row in cursor.fetchall()} != set(normalized_ids):
                raise ValueError("Un destinataire sélectionné n'appartient pas à cette plateforme")
        sqlite_values = (*values[:8], int(bool(is_active)), _sqlite_datetime(now))
        if rule_id is None:
            cursor.execute(
                """
                INSERT INTO course_reminder_rules (
                    platform_id, name, trigger_mode, days_before, minutes_before,
                    local_time, subject_template, content_template, recipient_scope,
                    is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (int(platform_id), *sqlite_values[:-1], _sqlite_datetime(now), _sqlite_datetime(now)),
            )
            saved_id = int(cursor.lastrowid)
        else:
            cursor.execute(
                """
                UPDATE course_reminder_rules
                SET name = ?, trigger_mode = ?, days_before = ?, minutes_before = ?,
                    local_time = ?, subject_template = ?, content_template = ?,
                    recipient_scope = ?, is_active = ?, updated_at = ?
                WHERE id = ? AND platform_id = ?
                """,
                (*sqlite_values, int(rule_id), int(platform_id)),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return None
            saved_id = int(rule_id)
        cursor.execute("DELETE FROM course_reminder_rule_recipients WHERE rule_id = ?", (saved_id,))
        if recipient_scope == "selected_explicit" and normalized_ids:
            cursor.executemany(
                "INSERT INTO course_reminder_rule_recipients (rule_id, recipient_id) VALUES (?, ?)",
                [(saved_id, recipient_id) for recipient_id in normalized_ids],
            )
        cursor.execute(
            "DELETE FROM course_reminder_deliveries WHERE rule_id = ? AND status != 'sent'",
            (saved_id,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return next((rule for rule in list_course_reminder_rules(platform_id) if rule["id"] == saved_id), None)


def delete_course_reminder_rule(platform_id: int, rule_id: int) -> bool:
    """Delete custom rules; built-in defaults can instead be deactivated."""
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM course_reminder_rules WHERE id = %s AND platform_id = %s AND system_key IS NULL",
                    (int(rule_id), int(platform_id)),
                )
                return cur.rowcount == 1
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        _ensure_sqlite_reminder_tables(cursor)
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "SELECT id FROM course_reminder_rules WHERE id = ? AND platform_id = ? AND system_key IS NULL",
            (int(rule_id), int(platform_id)),
        )
        exists = cursor.fetchone() is not None
        if exists:
            cursor.execute("DELETE FROM course_reminder_deliveries WHERE rule_id = ?", (int(rule_id),))
            cursor.execute("DELETE FROM course_reminder_rule_recipients WHERE rule_id = ?", (int(rule_id),))
            cursor.execute("DELETE FROM course_reminder_rules WHERE id = ?", (int(rule_id),))
        changed = exists
        conn.commit()
        return changed
    finally:
        conn.close()


def list_due_reminder_delivery_candidates(
    *,
    now,
    active_hours: float = 12.0,
    limit: int = 100,
    sqlite_cursor=None,
    platform_ids=None,
) -> list[dict[str, Any]]:
    """Return only claimable recipient deliveries ordered by their real due_at.

    Computing the rule occurrence in SQL avoids starving a far-away course
    whose J-365 reminder is due behind many nearer courses with J-1 rules.
    Sent, dead-lettered, backoff and live-lease rows never consume the batch.
    """
    safe_limit = max(1, min(int(limit or 100), 1000))
    scoped_platform_ids = [int(value) for value in (platform_ids or [])]
    if platform_ids is not None and not scoped_platform_ids:
        return []
    if schedule_store_is_postgres():
        platform_scope_sql = (
            "AND cs.platform_id = ANY(%(platform_ids)s)"
            if scoped_platform_ids
            else ""
        )
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    WITH occurrences AS (
                        SELECT
                            cs.id AS session_id,
                            cs.platform_id,
                            cs.session_index,
                            cs.scheduled_at,
                            cs.session_password,
                            r.id AS rule_id,
                            r.system_key,
                            r.name AS rule_name,
                            r.trigger_mode,
                            r.days_before,
                            r.minutes_before,
                            r.local_time,
                            r.subject_template,
                            r.content_template,
                            r.recipient_scope,
                            CASE
                                WHEN r.trigger_mode = 'relative_minutes' THEN
                                    cs.scheduled_at - make_interval(mins => COALESCE(r.minutes_before, 0))
                                ELSE
                                    (
                                        (
                                            (cs.scheduled_at AT TIME ZONE 'Europe/Paris')::date
                                            - COALESCE(r.days_before, 0)
                                        ) + COALESCE(r.local_time, TIME '18:00')
                                    ) AT TIME ZONE 'Europe/Paris'
                            END AS due_at
                        FROM course_sessions cs
                        JOIN course_reminder_rules r
                          ON r.platform_id = cs.platform_id AND r.is_active = TRUE
                        WHERE cs.status IN ('planned', 'active')
                          AND cs.scheduled_at + (%(active_hours)s * INTERVAL '1 hour') >= %(now)s
                          {platform_scope_sql}
                          AND (
                            COALESCE(r.system_key, '') != 'previous_evening'
                            OR cs.reminder_previous_evening_sent_at IS NULL
                          )
                          AND (
                            COALESCE(r.system_key, '') != 'five_minutes_before'
                            OR cs.reminder_5min_sent_at IS NULL
                          )
                    ),
                    due_occurrences AS MATERIALIZED (
                        SELECT *
                        FROM occurrences
                        WHERE due_at <= %(now)s
                          AND %(now)s < scheduled_at
                    ),
                    candidates AS (
                        SELECT
                            occurrence.*,
                            rec.id AS recipient_id,
                            rec.email,
                            rec.nom,
                            rec.prenom,
                            d.id AS existing_delivery_id,
                            d.status AS delivery_status,
                            d.attempts AS delivery_attempts,
                            d.max_attempts AS delivery_max_attempts,
                            d.next_retry_at,
                            d.lease_expires_at
                        FROM due_occurrences occurrence
                        JOIN course_reminder_recipients rec
                          ON rec.platform_id = occurrence.platform_id
                        LEFT JOIN course_reminder_rule_recipients selected
                          ON selected.rule_id = occurrence.rule_id
                         AND selected.recipient_id = rec.id
                        LEFT JOIN course_reminder_deliveries d
                          ON d.session_id = occurrence.session_id
                         AND d.rule_id = occurrence.rule_id
                         AND d.recipient_id = rec.id
                        WHERE (
                            occurrence.recipient_scope = 'all'
                            OR selected.recipient_id IS NOT NULL
                        )
                    )
                    SELECT *
                    FROM candidates
                    WHERE (
                        existing_delivery_id IS NULL
                        OR (
                          COALESCE(delivery_attempts, 0) < COALESCE(delivery_max_attempts, 5)
                          AND (
                            (delivery_status IN ('pending', 'retry_scheduled')
                             AND (next_retry_at IS NULL OR next_retry_at <= %(now)s))
                            OR
                            (delivery_status = 'claimed'
                             AND (lease_expires_at IS NULL OR lease_expires_at <= %(now)s))
                          )
                        )
                      )
                    ORDER BY due_at ASC, session_id ASC, rule_id ASC, recipient_id ASC
                    LIMIT %(limit)s
                    """,
                    {
                        "now": now,
                        "active_hours": float(active_hours),
                        "limit": safe_limit,
                        "platform_ids": scoped_platform_ids,
                    },
                )
                return [dict(row) for row in cur.fetchall()]

    own_connection = sqlite_cursor is None
    conn = get_db_connection() if own_connection else None
    cursor = conn.cursor() if conn is not None else sqlite_cursor
    try:
        if own_connection:
            _ensure_sqlite_reminder_tables(cursor)
        now_value = _sqlite_datetime(now)
        platform_scope_sql = (
            f"AND cs.platform_id IN ({','.join('?' for _ in scoped_platform_ids)})"
            if scoped_platform_ids
            else ""
        )
        cursor.execute(
            f"""
            WITH occurrences AS (
                SELECT
                    cs.id AS session_id,
                    cs.platform_id,
                    cs.session_index,
                    cs.scheduled_at,
                    cs.session_password,
                    r.id AS rule_id,
                    r.system_key,
                    r.name AS rule_name,
                    r.trigger_mode,
                    r.days_before,
                    r.minutes_before,
                    r.local_time,
                    r.subject_template,
                    r.content_template,
                    r.recipient_scope,
                    CASE
                        WHEN r.trigger_mode = 'relative_minutes' THEN
                            datetime(cs.scheduled_at, printf('-%d minutes', COALESCE(r.minutes_before, 0)))
                        ELSE
                            datetime(
                                date(cs.scheduled_at, printf('-%d days', COALESCE(r.days_before, 0)))
                                || ' ' || COALESCE(substr(r.local_time, 1, 5), '18:00')
                            )
                    END AS due_at
                FROM course_sessions cs
                JOIN course_reminder_rules r
                  ON r.platform_id = cs.platform_id AND r.is_active = 1
                WHERE cs.status IN ('planned', 'active')
                  AND datetime(cs.scheduled_at, printf('+%f hours', ?)) >= ?
                  {platform_scope_sql}
                  AND (
                    COALESCE(r.system_key, '') != 'previous_evening'
                    OR cs.reminder_previous_evening_sent_at IS NULL
                  )
                  AND (
                    COALESCE(r.system_key, '') != 'five_minutes_before'
                    OR cs.reminder_5min_sent_at IS NULL
                  )
            ),
            due_occurrences AS MATERIALIZED (
                SELECT *
                FROM occurrences
                WHERE due_at <= ?
                  AND ? < scheduled_at
            ),
            candidates AS (
                SELECT
                    occurrence.*,
                    rec.id AS recipient_id,
                    rec.email,
                    rec.nom,
                    rec.prenom,
                    d.id AS existing_delivery_id,
                    d.status AS delivery_status,
                    d.attempts AS delivery_attempts,
                    d.max_attempts AS delivery_max_attempts,
                    d.next_retry_at,
                    d.lease_expires_at
                FROM due_occurrences occurrence
                JOIN course_reminder_recipients rec
                  ON rec.platform_id = occurrence.platform_id
                LEFT JOIN course_reminder_rule_recipients selected
                  ON selected.rule_id = occurrence.rule_id
                 AND selected.recipient_id = rec.id
                LEFT JOIN course_reminder_deliveries d
                  ON d.session_id = occurrence.session_id
                 AND d.rule_id = occurrence.rule_id
                 AND d.recipient_id = rec.id
                WHERE (
                    occurrence.recipient_scope = 'all'
                    OR selected.recipient_id IS NOT NULL
                )
            )
            SELECT *
            FROM candidates
            WHERE (
                existing_delivery_id IS NULL
                OR (
                  COALESCE(delivery_attempts, 0) < COALESCE(delivery_max_attempts, 5)
                  AND (
                    (delivery_status IN ('pending', 'retry_scheduled')
                     AND (next_retry_at IS NULL OR next_retry_at <= ?))
                    OR
                    (delivery_status = 'claimed'
                     AND (lease_expires_at IS NULL OR lease_expires_at <= ?))
                  )
                )
              )
            ORDER BY due_at ASC, session_id ASC, rule_id ASC, recipient_id ASC
            LIMIT ?
            """,
            (
                float(active_hours), now_value, *scoped_platform_ids, now_value, now_value,
                now_value, now_value, safe_limit,
            ),
        )
        columns = [description[0] for description in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        if conn is not None:
            conn.close()


def claim_course_reminder_delivery(
    *,
    platform_id: int,
    session_id: int,
    rule_id: int,
    recipient_id: int,
    recipient_hash: str,
    due_at,
    claimed_at,
    lease_seconds: int = 900,
    max_attempts: int = 5,
) -> int | None:
    lease_expires_at = claimed_at + timedelta(seconds=max(60, int(lease_seconds)))
    max_attempts = max(1, min(int(max_attempts), 20))
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO course_reminder_deliveries (
                        platform_id, session_id, rule_id, recipient_id, recipient_hash, due_at,
                        status, claimed_at, lease_expires_at, attempts, max_attempts,
                        created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'claimed', %s, %s, 1, %s, %s, %s)
                    ON CONFLICT (session_id, rule_id, recipient_hash) DO NOTHING
                    RETURNING id
                    """,
                    (
                        int(platform_id), int(session_id), int(rule_id), int(recipient_id),
                        recipient_hash, due_at, claimed_at, lease_expires_at, max_attempts,
                        claimed_at, claimed_at,
                    ),
                )
                inserted = cur.fetchone()
                if inserted:
                    return int(inserted["id"])
                cur.execute(
                    """
                    UPDATE course_reminder_deliveries
                    SET status = 'claimed', claimed_at = %s, lease_expires_at = %s,
                        recipient_id = %s, due_at = %s, attempts = attempts + 1,
                        last_error = NULL, next_retry_at = NULL, updated_at = %s
                    WHERE session_id = %s AND rule_id = %s AND recipient_hash = %s
                      AND status IN ('pending', 'retry_scheduled', 'claimed')
                      AND attempts < max_attempts
                      AND (next_retry_at IS NULL OR next_retry_at <= %s)
                      AND (status != 'claimed' OR lease_expires_at IS NULL OR lease_expires_at <= %s)
                    RETURNING id
                    """,
                    (
                        claimed_at, lease_expires_at, int(recipient_id), due_at, claimed_at,
                        int(session_id), int(rule_id), recipient_hash, claimed_at, claimed_at,
                    ),
                )
                row = cur.fetchone()
                return int(row["id"]) if row else None
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        _ensure_sqlite_reminder_tables(cursor)
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            """
            SELECT id, status, lease_expires_at, next_retry_at, attempts, max_attempts
            FROM course_reminder_deliveries
            WHERE session_id = ? AND rule_id = ? AND recipient_hash = ?
            """,
            (int(session_id), int(rule_id), recipient_hash),
        )
        row = cursor.fetchone()
        claimed_value = _sqlite_datetime(claimed_at)
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
                    int(platform_id), int(session_id), int(rule_id), int(recipient_id),
                    recipient_hash, _sqlite_datetime(due_at), claimed_value,
                    _sqlite_datetime(lease_expires_at), max_attempts, claimed_value, claimed_value,
                ),
            )
            delivery_id = int(cursor.lastrowid)
        elif (
            row[1] in {"sent", "dead_lettered"}
            or int(row[4] or 0) >= int(row[5] or max_attempts)
            or (row[1] == "claimed" and row[2] and row[2] > claimed_value)
            or (row[3] and row[3] > claimed_value)
        ):
            conn.commit()
            return None
        else:
            delivery_id = int(row[0])
            cursor.execute(
                """
                UPDATE course_reminder_deliveries
                SET status = 'claimed', claimed_at = ?, lease_expires_at = ?,
                    recipient_id = ?, due_at = ?, attempts = attempts + 1,
                    last_error = NULL, next_retry_at = NULL, updated_at = ? WHERE id = ?
                """,
                (
                    claimed_value, _sqlite_datetime(lease_expires_at), int(recipient_id),
                    _sqlite_datetime(due_at), claimed_value, delivery_id,
                ),
            )
        conn.commit()
        return delivery_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def complete_course_reminder_delivery(delivery_id: int, *, claimed_at, sent_at) -> bool:
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE course_reminder_deliveries
                    SET status = 'sent', sent_at = %s, claimed_at = NULL,
                        lease_expires_at = NULL, next_retry_at = NULL,
                        last_error = NULL, updated_at = %s
                    WHERE id = %s AND status = 'claimed' AND claimed_at = %s
                    """,
                    (sent_at, sent_at, int(delivery_id), claimed_at),
                )
                return cur.rowcount == 1
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        sent_value = _sqlite_datetime(sent_at)
        cursor.execute(
            """
            UPDATE course_reminder_deliveries
            SET status = 'sent', sent_at = ?, claimed_at = NULL,
                lease_expires_at = NULL, next_retry_at = NULL,
                last_error = NULL, updated_at = ?
            WHERE id = ? AND status = 'claimed' AND claimed_at = ?
            """,
            (sent_value, sent_value, int(delivery_id), _sqlite_datetime(claimed_at)),
        )
        changed = cursor.rowcount == 1
        conn.commit()
        return changed
    finally:
        conn.close()


def release_course_reminder_delivery(
    delivery_id: int,
    *,
    claimed_at,
    error: str | None,
    retry_clock=None,
) -> bool:
    clean_error = str(error or "Erreur d'envoi")[:1000]
    # Keep the retry timestamp in the same clock domain as the scheduler that
    # claimed the delivery. In production ``retry_clock`` is the real clock;
    # for the centre-scoped test clock it is the simulated clock. Mixing the
    # two makes a retry scheduled at (for example) 15:48 permanently invisible
    # to a simulated 08:10 scheduler before the course starts.
    now = retry_clock or datetime.now(FRANCE_TZ)
    try:
        retry_base = max(10, int(os.getenv("COURSE_REMINDER_RETRY_BASE_SECONDS", "60")))
    except (TypeError, ValueError):
        retry_base = 60
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT attempts, max_attempts
                    FROM course_reminder_deliveries
                    WHERE id = %s AND status = 'claimed' AND claimed_at = %s
                    FOR UPDATE
                    """,
                    (int(delivery_id), claimed_at),
                )
                row = cur.fetchone()
                if not row:
                    return False
                attempts = int(row["attempts"] or 0)
                terminal = attempts >= int(row["max_attempts"] or 5)
                delay = min(3600, retry_base * (2 ** max(0, attempts - 1)))
                next_retry_at = None if terminal else now + timedelta(seconds=delay)
                cur.execute(
                    """
                    UPDATE course_reminder_deliveries
                    SET status = %s, claimed_at = NULL, lease_expires_at = NULL,
                        next_retry_at = %s, last_error = %s, updated_at = %s
                    WHERE id = %s AND status = 'claimed' AND claimed_at = %s
                    """,
                    (
                        "dead_lettered" if terminal else "retry_scheduled",
                        next_retry_at, clean_error, now, int(delivery_id), claimed_at,
                    ),
                )
                return cur.rowcount == 1
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT attempts, max_attempts FROM course_reminder_deliveries
            WHERE id = ? AND status = 'claimed' AND claimed_at = ?
            """,
            (int(delivery_id), _sqlite_datetime(claimed_at)),
        )
        row = cursor.fetchone()
        if not row:
            return False
        attempts = int(row[0] or 0)
        terminal = attempts >= int(row[1] or 5)
        delay = min(3600, retry_base * (2 ** max(0, attempts - 1)))
        next_retry_at = None if terminal else now + timedelta(seconds=delay)
        cursor.execute(
            """
            UPDATE course_reminder_deliveries
            SET status = ?, claimed_at = NULL, lease_expires_at = NULL,
                next_retry_at = ?, last_error = ?, updated_at = ?
            WHERE id = ? AND status = 'claimed' AND claimed_at = ?
            """,
            (
                "dead_lettered" if terminal else "retry_scheduled",
                _sqlite_datetime(next_retry_at) if next_retry_at else None,
                clean_error, _sqlite_datetime(now), int(delivery_id), _sqlite_datetime(claimed_at),
            ),
        )
        changed = cursor.rowcount == 1
        conn.commit()
        return changed
    finally:
        conn.close()


def get_course_reminder_delivery_recipient(delivery_id: int) -> dict[str, Any] | None:
    """Resolve a persisted delivery to its recipient in one indexed lookup."""
    query = """
        SELECT d.id, d.platform_id, d.session_id, d.rule_id, d.status,
               d.attempts, d.max_attempts, r.id AS recipient_id, r.email
        FROM course_reminder_deliveries d
        JOIN course_reminder_recipients r ON r.id = d.recipient_id
        WHERE d.id = {placeholder}
    """
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query.format(placeholder="%s"), (int(delivery_id),))
                row = cur.fetchone()
                return dict(row) if row else None
    conn = get_db_connection()
    try:
        conn.row_factory = __import__("sqlite3").Row
        cursor = conn.cursor()
        _ensure_sqlite_reminder_tables(cursor)
        cursor.execute(query.format(placeholder="?"), (int(delivery_id),))
        row = cursor.fetchone()
        return dict(row) if row else None
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


def list_course_session_credentials_for_window(
    platform_id: int,
    *,
    lower_bound,
    upper_bound,
    sqlite_cursor=None,
) -> list[dict[str, Any]]:
    """Return occurrence-scoped credentials so auth can bind a student token."""
    columns = "id, platform_id, scheduled_at, status, session_password"
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {columns}
                    FROM course_sessions
                    WHERE platform_id = %s
                      AND status IN ('planned', 'active')
                      AND scheduled_at BETWEEN %s AND %s
                      AND session_password IS NOT NULL
                      AND session_password != ''
                    ORDER BY scheduled_at ASC, id ASC
                    """,
                    (int(platform_id), lower_bound, upper_bound),
                )
                return [dict(row) for row in cur.fetchall()]
    own_connection = sqlite_cursor is None
    conn = get_db_connection() if own_connection else None
    cursor = conn.cursor() if conn is not None else sqlite_cursor
    try:
        cursor.execute(
            f"""
            SELECT {columns}
            FROM course_sessions
            WHERE platform_id = ?
              AND status IN ('planned', 'active')
              AND scheduled_at BETWEEN ? AND ?
              AND session_password IS NOT NULL
              AND session_password != ''
            ORDER BY scheduled_at ASC, id ASC
            """,
            (
                int(platform_id),
                _sqlite_datetime(lower_bound),
                _sqlite_datetime(upper_bound),
            ),
        )
        return [
            {
                "id": int(row[0]),
                "platform_id": int(row[1]),
                "scheduled_at": row[2],
                "status": row[3],
                "session_password": row[4],
            }
            for row in cursor.fetchall()
        ]
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
    storage_prefix = f"course-sessions/{int(session_id)}"
    if schedule_store_is_postgres():
        stale_sql = ""
        params: list[Any] = [
            started_at,
            job_id,
            folder_id,
            storage_prefix,
            started_at,
            session_id,
        ]
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
                        audio_generation_attempts = COALESCE(audio_generation_attempts, 0) + 1,
                        audio_generation_next_retry_at = NULL,
                        audio_job_id = %s,
                        audio_folder_id = %s,
                        audio_storage_prefix = %s,
                        updated_at = %s
                    WHERE id = %s
                      AND status IN ('planned', 'active')
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
    params = [
        started_value,
        job_id,
        folder_id,
        storage_prefix,
        started_value,
        session_id,
    ]
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
                audio_generation_attempts = COALESCE(audio_generation_attempts, 0) + 1,
                audio_generation_next_retry_at = NULL,
                audio_job_id = ?,
                audio_folder_id = ?,
                audio_storage_prefix = ?,
                updated_at = ?
            WHERE id = ?
              AND status IN ('planned', 'active')
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


def mark_audio_generation_queued(
    session_id: int,
    *,
    job_id: int,
    folder_id: int,
    queued_at,
    reset_completed: bool = False,
) -> bool:
    """Record one scheduler reconciliation batch before its file tasks run."""
    storage_prefix = f"course-sessions/{int(session_id)}"
    if schedule_store_is_postgres():
        completed_sql = "NULL" if reset_completed else "audio_generation_completed_at"
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE course_sessions
                    SET audio_generation_status = 'queued',
                        audio_generation_completed_at = {completed_sql},
                        audio_generation_error = NULL,
                        audio_generation_next_retry_at = NULL,
                        audio_generation_attempts = COALESCE(audio_generation_attempts, 0) + 1,
                        audio_job_id = %s,
                        audio_folder_id = %s,
                        audio_storage_prefix = %s,
                        updated_at = %s
                    WHERE id = %s AND status IN ('planned', 'active')
                      AND (
                          COALESCE(audio_generation_status, 'pending') NOT IN ('queued', 'processing')
                          OR audio_generation_completed_at IS NOT NULL
                      )
                    RETURNING id
                    """,
                    (job_id, folder_id, storage_prefix, queued_at, session_id),
                )
                return cur.fetchone() is not None
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        completed_sql = "NULL" if reset_completed else "audio_generation_completed_at"
        value = _sqlite_datetime(queued_at)
        cursor.execute(
            f"""
            UPDATE course_sessions
            SET audio_generation_status = 'queued',
                audio_generation_completed_at = {completed_sql},
                audio_generation_error = NULL,
                audio_generation_next_retry_at = NULL,
                audio_generation_attempts = COALESCE(audio_generation_attempts, 0) + 1,
                audio_job_id = ?, audio_folder_id = ?, audio_storage_prefix = ?,
                updated_at = ?
            WHERE id = ? AND status IN ('planned', 'active')
              AND (
                  COALESCE(audio_generation_status, 'pending') NOT IN ('queued', 'processing')
                  OR audio_generation_completed_at IS NOT NULL
              )
            """,
            (job_id, folder_id, storage_prefix, value, session_id),
        )
        changed = cursor.rowcount == 1
        conn.commit()
        return changed
    finally:
        conn.close()


def mark_audio_generation_processing(session_id: int, *, updated_at) -> bool:
    """Heartbeat aggregate session state while an individual file is running."""
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE course_sessions
                    SET audio_generation_status = 'processing',
                        audio_generation_started_at = COALESCE(audio_generation_started_at, %s),
                        updated_at = %s
                    WHERE id = %s AND status IN ('planned', 'active')
                      AND audio_generation_completed_at IS NULL
                    """,
                    (updated_at, updated_at, session_id),
                )
                return cur.rowcount == 1
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        value = _sqlite_datetime(updated_at)
        cursor.execute(
            """
            UPDATE course_sessions
            SET audio_generation_status = 'processing',
                audio_generation_started_at = COALESCE(audio_generation_started_at, ?),
                updated_at = ?
            WHERE id = ? AND status IN ('planned', 'active')
              AND audio_generation_completed_at IS NULL
            """,
            (value, value, session_id),
        )
        changed = cursor.rowcount == 1
        conn.commit()
        return changed
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
                        audio_generation_next_retry_at = NULL,
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
                audio_generation_completed_at = ?, audio_generation_error = NULL,
                audio_generation_next_retry_at = NULL, updated_at = ?
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


def assign_fallback_audio_to_session(
    platform_id: int,
    session_id: int,
    *,
    module_day_id: int,
    folder_id: int,
    completed_at,
) -> bool:
    """Bind a reviewed older day to one failed/upcoming occurrence."""
    storage_prefix = f"course-sessions/{int(session_id)}"
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
                    SET module_day_id = %s,
                        audio_folder_id = %s,
                        audio_storage_prefix = %s,
                        audio_generation_status = 'completed',
                        audio_generation_started_at = COALESCE(audio_generation_started_at, %s),
                        audio_generation_completed_at = %s,
                        audio_generation_error = NULL,
                        audio_generation_next_retry_at = NULL,
                        updated_at = %s
                    WHERE id = %s AND platform_id = %s
                      AND status IN ('planned', 'active')
                    RETURNING id
                    """,
                    (
                        int(module_day_id),
                        int(folder_id),
                        storage_prefix,
                        completed_at,
                        completed_at,
                        completed_at,
                        int(session_id),
                        int(platform_id),
                    ),
                )
                return cur.fetchone() is not None

    conn = get_db_connection()
    try:
        value = _sqlite_datetime(completed_at)
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE course_sessions
            SET module_day_id = ?, audio_folder_id = ?, audio_storage_prefix = ?,
                audio_generation_status = 'completed',
                audio_generation_started_at = COALESCE(audio_generation_started_at, ?),
                audio_generation_completed_at = ?, audio_generation_error = NULL,
                audio_generation_next_retry_at = NULL, updated_at = ?
            WHERE id = ? AND platform_id = ?
              AND status IN ('planned', 'active')
            """,
            (
                int(module_day_id),
                int(folder_id),
                storage_prefix,
                value,
                value,
                value,
                int(session_id),
                int(platform_id),
            ),
        )
        changed = cursor.rowcount == 1
        conn.commit()
        return changed
    finally:
        conn.close()


def _audio_retry_delay_minutes(attempts: int) -> float:
    base = max(1.0, float(os.environ.get("SCHEDULED_AUDIO_RETRY_BASE_MINUTES", "5")))
    maximum = max(base, float(os.environ.get("SCHEDULED_AUDIO_RETRY_MAX_MINUTES", "60")))
    return min(maximum, base * (2 ** max(0, int(attempts or 1) - 1)))


def fail_audio_generation_session(
    session_id: int,
    *,
    error: str,
    failed_at,
    expected_started_at=None,
) -> bool:
    message = str(error or "")[:500]
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                owner_sql = " AND audio_generation_started_at = %s" if expected_started_at is not None else ""
                owner_params = [session_id]
                if expected_started_at is not None:
                    owner_params.append(expected_started_at)
                cur.execute(
                    f"""
                    SELECT COALESCE(audio_generation_attempts, 1) AS attempts
                    FROM course_sessions
                    WHERE id = %s AND audio_generation_completed_at IS NULL
                    {owner_sql}
                    FOR UPDATE
                    """,
                    owner_params,
                )
                row = cur.fetchone()
                if not row:
                    return False
                next_retry_at = failed_at + timedelta(
                    minutes=_audio_retry_delay_minutes(int(row["attempts"] or 1))
                )
                cur.execute(
                    """
                    UPDATE course_sessions
                    SET audio_generation_status = 'error', audio_generation_error = %s,
                        audio_generation_next_retry_at = %s, updated_at = %s
                    WHERE id = %s AND audio_generation_completed_at IS NULL
                    """,
                    (message, next_retry_at, failed_at, session_id),
                )
                return cur.rowcount == 1
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        owner_sql = " AND audio_generation_started_at = ?" if expected_started_at is not None else ""
        owner_params = [session_id]
        if expected_started_at is not None:
            owner_params.append(_sqlite_datetime(expected_started_at))
        cursor.execute(
            f"""
            SELECT COALESCE(audio_generation_attempts, 1)
            FROM course_sessions
            WHERE id = ? AND audio_generation_completed_at IS NULL
            {owner_sql}
            """,
            owner_params,
        )
        row = cursor.fetchone()
        if not row:
            return False
        next_retry_at = failed_at + timedelta(
            minutes=_audio_retry_delay_minutes(int(row[0] or 1))
        )
        cursor.execute(
            """
            UPDATE course_sessions
            SET audio_generation_status = 'error', audio_generation_error = ?,
                audio_generation_next_retry_at = ?, updated_at = ?
            WHERE id = ? AND audio_generation_completed_at IS NULL
            """,
            (
                message,
                _sqlite_datetime(next_retry_at),
                _sqlite_datetime(failed_at),
                session_id,
            ),
        )
        changed = cursor.rowcount == 1
        conn.commit()
        return changed
    finally:
        conn.close()
