"""Durable, centre-scoped test clock storage."""

from __future__ import annotations

from datetime import datetime

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
