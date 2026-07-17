"""Durable PostgreSQL storage for room presence and daily Excel exports."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from database.postgres import get_postgres_connection


def get_accessible_platform(platform_id: int, center_account_id: int | None = None):
    where = "pc.id = %s"
    params: list[Any] = [int(platform_id)]
    if center_account_id is not None:
        where += " AND pc.center_account_id = %s"
        params.append(int(center_account_id))
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT pc.id, pc.name, pc.center_account_id FROM platform_config pc WHERE {where}",
                params,
            )
            return cur.fetchone()


def close_stale_presence_logs(*, cutoff: datetime) -> int:
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE logs
                SET depart = last_seen_at,
                    closed_reason = 'heartbeat_timeout'
                WHERE attendance_started_at IS NOT NULL
                  AND depart IS NULL
                  AND last_seen_at IS NOT NULL
                  AND last_seen_at < %s
                """,
                (cutoff,),
            )
            return int(cur.rowcount)


def materialize_daily_export_candidates(*, now: datetime) -> int:
    """Create one durable J+1 06:00 export job for every course occurrence."""
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO attendance_daily_exports (
                    platform_id, course_session_id, course_date, available_at,
                    status, created_at, updated_at
                )
                SELECT
                    cs.platform_id,
                    cs.id,
                    (cs.scheduled_at AT TIME ZONE COALESCE(csc.timezone, 'Europe/Paris'))::date,
                    (
                        (
                            (cs.scheduled_at AT TIME ZONE COALESCE(csc.timezone, 'Europe/Paris'))::date
                            + TIME '06:00' + INTERVAL '1 day'
                        ) AT TIME ZONE COALESCE(csc.timezone, 'Europe/Paris')
                    ),
                    'pending',
                    %s,
                    %s
                FROM course_sessions cs
                LEFT JOIN course_schedule_config csc ON csc.platform_id = cs.platform_id
                WHERE cs.status = 'completed'
                  AND (
                        (
                            (cs.scheduled_at AT TIME ZONE COALESCE(csc.timezone, 'Europe/Paris'))::date
                            + TIME '06:00' + INTERVAL '1 day'
                        ) AT TIME ZONE COALESCE(csc.timezone, 'Europe/Paris')
                      ) <= %s
                ON CONFLICT (course_session_id) DO NOTHING
                """,
                (now, now, now),
            )
            return int(cur.rowcount)


def claim_due_daily_export(*, now: datetime, lease_seconds: int = 900):
    lease_expires_at = now + timedelta(seconds=max(60, int(lease_seconds)))
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH candidate AS (
                    SELECT id
                    FROM attendance_daily_exports
                    WHERE (
                            status IN ('pending', 'retry_scheduled')
                            AND available_at <= %s
                            AND (next_retry_at IS NULL OR next_retry_at <= %s)
                          )
                       OR (
                            status = 'claimed'
                            AND lease_expires_at IS NOT NULL
                            AND lease_expires_at <= %s
                          )
                    ORDER BY available_at ASC, id ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE attendance_daily_exports target
                SET status = 'claimed',
                    claimed_at = %s,
                    lease_expires_at = %s,
                    attempts = target.attempts + 1,
                    last_error = NULL,
                    updated_at = %s
                FROM candidate
                WHERE target.id = candidate.id
                RETURNING target.*
                """,
                (now, now, now, now, lease_expires_at, now),
            )
            return cur.fetchone()


def complete_daily_export(
    export_id: int,
    *,
    now: datetime,
    container_name: str,
    blob_key: str,
    filename: str,
    size_bytes: int,
    sha256: str,
    participant_count: int,
) -> bool:
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE attendance_daily_exports
                SET status = 'ready',
                    container_name = %s,
                    blob_key = %s,
                    filename = %s,
                    size_bytes = %s,
                    sha256 = %s,
                    participant_count = %s,
                    generated_at = %s,
                    claimed_at = NULL,
                    lease_expires_at = NULL,
                    next_retry_at = NULL,
                    last_error = NULL,
                    updated_at = %s
                WHERE id = %s AND status = 'claimed'
                """,
                (
                    container_name,
                    blob_key,
                    filename,
                    int(size_bytes),
                    sha256,
                    int(participant_count),
                    now,
                    now,
                    int(export_id),
                ),
            )
            return cur.rowcount == 1


def fail_daily_export(export_id: int, *, now: datetime, error: str) -> dict[str, Any] | None:
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT attempts, max_attempts
                FROM attendance_daily_exports
                WHERE id = %s
                FOR UPDATE
                """,
                (int(export_id),),
            )
            row = cur.fetchone()
            if not row:
                return None
            attempts = int(row["attempts"] or 0)
            max_attempts = int(row["max_attempts"] or 5)
            dead = attempts >= max_attempts
            retry_at = None if dead else now + timedelta(minutes=min(60, 2 ** max(0, attempts - 1)))
            cur.execute(
                """
                UPDATE attendance_daily_exports
                SET status = %s,
                    next_retry_at = %s,
                    claimed_at = NULL,
                    lease_expires_at = NULL,
                    last_error = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (
                    "dead_lettered" if dead else "retry_scheduled",
                    retry_at,
                    str(error or "Erreur inconnue")[:1000],
                    now,
                    int(export_id),
                ),
            )
            return {"dead_lettered": dead, "next_retry_at": retry_at, "attempts": attempts}


def get_course_session(session_id: int):
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cs.id, cs.platform_id, cs.session_index, cs.scheduled_at,
                       cs.completed_at, pc.name AS platform_name,
                       COALESCE(csc.timezone, 'Europe/Paris') AS timezone
                FROM course_sessions cs
                JOIN platform_config pc ON pc.id = cs.platform_id
                LEFT JOIN course_schedule_config csc ON csc.platform_id = cs.platform_id
                WHERE cs.id = %s
                """,
                (int(session_id),),
            )
            return cur.fetchone()


def get_course_session_for_date(platform_id: int, course_date: str):
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cs.id, cs.platform_id, cs.session_index, cs.scheduled_at,
                       cs.completed_at, cs.status,
                       COALESCE(csc.timezone, 'Europe/Paris') AS timezone
                FROM course_sessions cs
                LEFT JOIN course_schedule_config csc ON csc.platform_id = cs.platform_id
                WHERE cs.platform_id = %s
                  AND (cs.scheduled_at AT TIME ZONE COALESCE(csc.timezone, 'Europe/Paris'))::date = %s::date
                ORDER BY cs.scheduled_at ASC
                LIMIT 1
                """,
                (int(platform_id), course_date),
            )
            return cur.fetchone()


def list_presence_logs_for_session(platform_id: int, session_id: int) -> list[dict[str, Any]]:
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    l.id, l.platform_id, l.course_session_id, l.recipient_hash,
                    l.nom, l.prenom, l.attendance_started_at, l.last_seen_at,
                    l.depart, l.closed_reason, invited.email
                FROM logs l
                LEFT JOIN LATERAL (
                    SELECT recipient.email
                    FROM course_reminder_deliveries delivery
                    JOIN course_reminder_recipients recipient ON recipient.id = delivery.recipient_id
                    WHERE delivery.session_id = l.course_session_id
                      AND delivery.recipient_hash = l.recipient_hash
                    ORDER BY delivery.sent_at DESC NULLS LAST, delivery.id DESC
                    LIMIT 1
                ) invited ON TRUE
                WHERE l.platform_id = %s
                  AND l.course_session_id = %s
                  AND l.attendance_started_at IS NOT NULL
                ORDER BY l.attendance_started_at ASC, l.id ASC
                """,
                (int(platform_id), int(session_id)),
            )
            return list(cur.fetchall())


def list_daily_exports(platform_id: int, *, limit: int = 120) -> list[dict[str, Any]]:
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, platform_id, course_session_id, course_date, available_at,
                       status, filename, size_bytes, participant_count, generated_at,
                       attempts, last_error
                FROM attendance_daily_exports
                WHERE platform_id = %s
                ORDER BY course_date DESC, id DESC
                LIMIT %s
                """,
                (int(platform_id), max(1, min(500, int(limit)))),
            )
            return list(cur.fetchall())


def get_daily_export(export_id: int, *, platform_id: int | None = None):
    where = "id = %s"
    params: list[Any] = [int(export_id)]
    if platform_id is not None:
        where += " AND platform_id = %s"
        params.append(int(platform_id))
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM attendance_daily_exports WHERE {where}", params)
            return cur.fetchone()


def get_ready_daily_export_for_date(platform_id: int, course_date: str):
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM attendance_daily_exports
                WHERE platform_id = %s AND course_date = %s::date AND status = 'ready'
                ORDER BY id DESC
                LIMIT 1
                """,
                (int(platform_id), course_date),
            )
            return cur.fetchone()
