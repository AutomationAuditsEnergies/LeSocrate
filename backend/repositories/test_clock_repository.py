"""Durable, centre-scoped test clock storage."""

from __future__ import annotations

from datetime import datetime, timedelta

from config import FRANCE_TZ
from database.db import get_db_connection
from database.postgres import get_postgres_connection, postgres_enabled


def _ensure_sqlite_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS center_test_clocks (
            center_account_id INTEGER PRIMARY KEY,
            simulated_anchor TEXT NOT NULL,
            real_anchor TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def get_center_test_clock(center_account_id: int):
    if postgres_enabled():
        with get_postgres_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT center_account_id, simulated_anchor, real_anchor, updated_at
                    FROM center_test_clocks
                    WHERE center_account_id = %s
                    """,
                    (int(center_account_id),),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        _ensure_sqlite_table(cursor)
        cursor.execute(
            """
            SELECT center_account_id, simulated_anchor, real_anchor, updated_at
            FROM center_test_clocks
            WHERE center_account_id = ?
            """,
            (int(center_account_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "center_account_id": row[0],
            "simulated_anchor": row[1],
            "real_anchor": row[2],
            "updated_at": row[3],
        }
    finally:
        conn.close()


def set_center_test_clock(center_account_id: int, simulated_anchor: datetime, real_anchor: datetime):
    updated_at = datetime.now(FRANCE_TZ)
    if postgres_enabled():
        with get_postgres_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO center_test_clocks (
                        center_account_id, simulated_anchor, real_anchor, updated_at
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (center_account_id) DO UPDATE SET
                        simulated_anchor = EXCLUDED.simulated_anchor,
                        real_anchor = EXCLUDED.real_anchor,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (int(center_account_id), simulated_anchor, real_anchor, updated_at),
                )
        return get_center_test_clock(center_account_id)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        _ensure_sqlite_table(cursor)
        values = tuple(
            value.isoformat()
            for value in (simulated_anchor, real_anchor, updated_at)
        )
        cursor.execute(
            """
            INSERT INTO center_test_clocks (
                center_account_id, simulated_anchor, real_anchor, updated_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(center_account_id) DO UPDATE SET
                simulated_anchor = excluded.simulated_anchor,
                real_anchor = excluded.real_anchor,
                updated_at = excluded.updated_at
            """,
            (int(center_account_id), *values),
        )
        conn.commit()
    finally:
        conn.close()
    return get_center_test_clock(center_account_id)


def delete_center_test_clock(center_account_id: int) -> bool:
    if postgres_enabled():
        with get_postgres_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM center_test_clocks WHERE center_account_id = %s",
                    (int(center_account_id),),
                )
                return cursor.rowcount == 1

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        _ensure_sqlite_table(cursor)
        cursor.execute(
            "DELETE FROM center_test_clocks WHERE center_account_id = ?",
            (int(center_account_id),),
        )
        changed = cursor.rowcount == 1
        conn.commit()
        return changed
    finally:
        conn.close()


def get_platform_center_account_id(platform_id: int):
    placeholder = "%s" if postgres_enabled() else "?"
    query = f"SELECT center_account_id FROM platform_config WHERE id = {placeholder}"
    if postgres_enabled():
        with get_postgres_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (int(platform_id),))
                row = cursor.fetchone()
                return int(row["center_account_id"]) if row and row["center_account_id"] else None
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (int(platform_id),))
        row = cursor.fetchone()
        return int(row[0]) if row and row[0] else None
    finally:
        conn.close()


def list_center_platform_ids(center_account_id: int) -> list[int]:
    if postgres_enabled():
        with get_postgres_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM platform_config WHERE center_account_id = %s ORDER BY id",
                    (int(center_account_id),),
                )
                return [int(row["id"]) for row in cursor.fetchall()]
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM platform_config WHERE center_account_id = ? ORDER BY id",
            (int(center_account_id),),
        )
        return [int(row[0]) for row in cursor.fetchall()]
    finally:
        conn.close()


def reset_center_test_state(
    center_account_id: int,
    simulated_now: datetime,
    *,
    active_hours: float = 12.0,
) -> dict[str, int]:
    """Rewind centre-owned schedule state for a deterministic clock test.

    Only deliveries whose due time is at or after the new clock anchor are
    cleared. Older reminders stay recorded and are also excluded by the test
    clock lower bound, so jumping to H-6 cannot backfill a J-1 reminder.
    """
    platform_ids = list_center_platform_ids(int(center_account_id))
    if not platform_ids:
        return {"platform_count": 0, "session_count": 0, "delivery_count": 0}

    stale_before = simulated_now - timedelta(hours=max(1.0, float(active_hours)))
    if postgres_enabled():
        with get_postgres_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM course_reminder_deliveries delivery
                    USING course_sessions session
                    WHERE delivery.session_id = session.id
                      AND session.platform_id = ANY(%s)
                      AND delivery.due_at >= %s
                    """,
                    (platform_ids, simulated_now),
                )
                delivery_count = cursor.rowcount
                cursor.execute(
                    """
                    UPDATE course_sessions
                    SET status = CASE
                            WHEN scheduled_at > %s THEN 'planned'
                            WHEN scheduled_at >= %s THEN 'active'
                            ELSE 'completed'
                        END,
                        activated_at = CASE
                            WHEN scheduled_at > %s THEN NULL
                            WHEN scheduled_at >= %s THEN COALESCE(activated_at, %s)
                            ELSE activated_at
                        END,
                        completed_at = CASE
                            WHEN scheduled_at >= %s THEN NULL
                            ELSE COALESCE(completed_at, %s)
                        END,
                        reminder_previous_evening_sent_at = CASE
                            WHEN scheduled_at > %s THEN NULL
                            ELSE reminder_previous_evening_sent_at
                        END,
                        reminder_5min_sent_at = CASE
                            WHEN scheduled_at > %s THEN NULL
                            ELSE reminder_5min_sent_at
                        END,
                        reminder_previous_evening_claimed_at = NULL,
                        reminder_5min_claimed_at = NULL,
                        updated_at = %s
                    WHERE platform_id = ANY(%s)
                      AND status IN ('planned', 'active', 'completed')
                    """,
                    (
                        simulated_now,
                        stale_before,
                        simulated_now,
                        stale_before,
                        simulated_now,
                        stale_before,
                        simulated_now,
                        simulated_now,
                        simulated_now,
                        simulated_now,
                        platform_ids,
                    ),
                )
                session_count = cursor.rowcount
        return {
            "platform_count": len(platform_ids),
            "session_count": session_count,
            "delivery_count": delivery_count,
        }

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        existing_tables = {
            row[0]
            for row in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "course_sessions" not in existing_tables:
            return {
                "platform_count": len(platform_ids),
                "session_count": 0,
                "delivery_count": 0,
            }
        placeholders = ",".join("?" for _ in platform_ids)
        simulated_value = simulated_now.strftime("%Y-%m-%d %H:%M:%S")
        stale_value = stale_before.strftime("%Y-%m-%d %H:%M:%S")
        delivery_count = 0
        if "course_reminder_deliveries" in existing_tables:
            cursor.execute(
                f"""
                DELETE FROM course_reminder_deliveries
                WHERE session_id IN (
                    SELECT id FROM course_sessions
                    WHERE platform_id IN ({placeholders})
                ) AND datetime(due_at) >= datetime(?)
                """,
                (*platform_ids, simulated_value),
            )
            delivery_count = cursor.rowcount
        cursor.execute(
            f"""
            UPDATE course_sessions
            SET status = CASE
                    WHEN datetime(scheduled_at) > datetime(?) THEN 'planned'
                    WHEN datetime(scheduled_at) >= datetime(?) THEN 'active'
                    ELSE 'completed'
                END,
                activated_at = CASE
                    WHEN datetime(scheduled_at) > datetime(?) THEN NULL
                    WHEN datetime(scheduled_at) >= datetime(?) THEN COALESCE(activated_at, ?)
                    ELSE activated_at
                END,
                completed_at = CASE
                    WHEN datetime(scheduled_at) >= datetime(?) THEN NULL
                    ELSE COALESCE(completed_at, ?)
                END,
                reminder_previous_evening_sent_at = CASE
                    WHEN datetime(scheduled_at) > datetime(?) THEN NULL
                    ELSE reminder_previous_evening_sent_at
                END,
                reminder_5min_sent_at = CASE
                    WHEN datetime(scheduled_at) > datetime(?) THEN NULL
                    ELSE reminder_5min_sent_at
                END,
                reminder_previous_evening_claimed_at = NULL,
                reminder_5min_claimed_at = NULL,
                updated_at = ?
            WHERE platform_id IN ({placeholders})
              AND status IN ('planned', 'active', 'completed')
            """,
            (
                simulated_value,
                stale_value,
                simulated_value,
                stale_value,
                simulated_value,
                stale_value,
                simulated_value,
                simulated_value,
                simulated_value,
                simulated_value,
                *platform_ids,
            ),
        )
        session_count = cursor.rowcount
        conn.commit()
        return {
            "platform_count": len(platform_ids),
            "session_count": session_count,
            "delivery_count": delivery_count,
        }
    finally:
        conn.close()


def list_authorized_active_test_clocks() -> list[dict]:
    """Return clocks for the single server-authorized test account."""
    query = """
        SELECT clock.center_account_id, clock.simulated_anchor, clock.real_anchor
        FROM center_test_clocks clock
        JOIN training_center_accounts center ON center.id = clock.center_account_id
        WHERE LOWER(center.username) = LOWER({placeholder})
          AND center.is_active = {active_value}
    """
    if postgres_enabled():
        with get_postgres_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    query.format(placeholder="%s", active_value="TRUE"),
                    ("newpiprod@gmail.com",),
                )
                return [dict(row) for row in cursor.fetchall()]
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        _ensure_sqlite_table(cursor)
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'training_center_accounts'"
        )
        if cursor.fetchone() is None:
            # Some isolated scheduler tests intentionally use a minimal DB.
            # With no centre registry, no centre-scoped clock can be active.
            return []
        cursor.execute(
            query.format(placeholder="?", active_value="1"),
            ("newpiprod@gmail.com",),
        )
        return [
            {
                "center_account_id": row[0],
                "simulated_anchor": row[1],
                "real_anchor": row[2],
            }
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()
