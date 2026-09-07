"""Resolve a Supabase identity to the server-owned training-center account."""

from __future__ import annotations

from database.db import get_db_connection
from database.postgres import postgres_enabled
from repositories.core_repository import (
    bind_training_center_auth_user,
    get_training_center_by_auth_user_id,
)


def _sqlite_center_from_row(row):
    if row is None:
        return None
    return {
        "id": row[0],
        "auth_user_id": row[1],
        "username": row[2],
        "center_name": row[3],
        "slug": row[4],
        "is_active": bool(row[5]),
        "pipeline_access_enabled": bool(row[6]),
    }


def _resolve_sqlite_center(auth_user_id, email):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, auth_user_id, username, center_name, slug, is_active,
                   pipeline_access_enabled
            FROM training_center_accounts
            WHERE auth_user_id = ?
            """,
            (auth_user_id,),
        )
        account = _sqlite_center_from_row(cursor.fetchone())
        if account:
            return account

        cursor.execute(
            """
            UPDATE training_center_accounts
            SET auth_user_id = ?,
                updated_at = datetime('now')
            WHERE LOWER(username) = LOWER(?)
              AND (auth_user_id IS NULL OR auth_user_id = ?)
            """,
            (auth_user_id, email, auth_user_id),
        )
        if cursor.rowcount <= 0:
            return None
        conn.commit()
        cursor.execute(
            """
            SELECT id, auth_user_id, username, center_name, slug, is_active,
                   pipeline_access_enabled
            FROM training_center_accounts
            WHERE auth_user_id = ?
            """,
            (auth_user_id,),
        )
        return _sqlite_center_from_row(cursor.fetchone())
    finally:
        conn.close()


def resolve_training_center_identity(auth_user_id, email):
    """Find an existing binding or atomically bind a matching verified email."""
    if not auth_user_id or not email:
        return None
    if not postgres_enabled():
        return _resolve_sqlite_center(str(auth_user_id), str(email).strip().lower())

    account = get_training_center_by_auth_user_id(auth_user_id)
    if account:
        return account
    return bind_training_center_auth_user(
        str(auth_user_id),
        str(email).strip().lower(),
    )
