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
        now_sqlite = _sqlite_datetime(now)
        replacement_boundary = _sqlite_datetime(replace_after or now)
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
    columns = """
        id, platform_id, session_index, scheduled_at, status,
        audio_generation_status, audio_generation_started_at,
        audio_generation_completed_at, audio_generation_attempts,
        audio_generation_next_retry_at, audio_job_id, audio_folder_id,
        postponed_from, postponed_at, postponement_count,
        created_at, updated_at
    """
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {columns}
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
        cursor.execute(
            f"""
            SELECT {columns}
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
               cs.status, cs.audio_generation_status,
               cs.audio_generation_started_at, cs.audio_generation_completed_at,
               cs.audio_generation_attempts, cs.audio_generation_next_retry_at,
               pc.name,
               COALESCE(
                   pc.source_formation_id,
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
    """Batch-load the next occurrence for dashboard cards without N+1 reads."""
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
                       next_session.audio_generation_next_retry_at
                FROM course_schedule_config cfg
                LEFT JOIN LATERAL (
                    SELECT cs.*
                    FROM course_sessions cs
                    WHERE cs.platform_id = cfg.platform_id
                      AND cs.status IN ('planned', 'active')
                    ORDER BY cs.scheduled_at ASC
                    LIMIT 1
                ) next_session ON TRUE
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


def _ensure_sqlite_reminder_recipient_table(cursor) -> None:
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
        "CREATE INDEX IF NOT EXISTS idx_course_reminder_recipients_platform "
        "ON course_reminder_recipients(platform_id)"
    )


def list_explicit_course_reminder_recipients(platform_id: int) -> list[dict[str, Any]]:
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, email, created_at
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
            SELECT id, email, created_at
            FROM course_reminder_recipients
            WHERE platform_id = ?
            ORDER BY email COLLATE NOCASE
            """,
            (int(platform_id),),
        )
        return [
            {"id": int(row[0]), "email": row[1], "created_at": row[2]}
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def add_explicit_course_reminder_recipients(
    platform_id: int,
    emails: list[str],
    *,
    created_at,
) -> list[dict[str, Any]]:
    normalized = sorted({str(email or "").strip().lower() for email in emails if email})
    if schedule_store_is_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO course_reminder_recipients (platform_id, email, created_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (platform_id, email) DO NOTHING
                    """,
                    [(int(platform_id), email, created_at) for email in normalized],
                )
        return list_explicit_course_reminder_recipients(platform_id)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        _ensure_sqlite_reminder_recipient_table(cursor)
        cursor.executemany(
            """
            INSERT OR IGNORE INTO course_reminder_recipients (platform_id, email, created_at)
            VALUES (?, ?, ?)
            """,
            [
                (int(platform_id), email, _sqlite_datetime(created_at))
                for email in normalized
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
        _ensure_sqlite_reminder_recipient_table(cursor)
        cursor.execute(
            "DELETE FROM course_reminder_recipients WHERE id = ? AND platform_id = ?",
            (int(recipient_id), int(platform_id)),
        )
        changed = cursor.rowcount == 1
        conn.commit()
        return changed
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
                        audio_generation_attempts = COALESCE(audio_generation_attempts, 0) + 1,
                        audio_generation_next_retry_at = NULL,
                        audio_job_id = %s,
                        audio_folder_id = %s,
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
                audio_generation_attempts = COALESCE(audio_generation_attempts, 0) + 1,
                audio_generation_next_retry_at = NULL,
                audio_job_id = ?,
                audio_folder_id = ?,
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
