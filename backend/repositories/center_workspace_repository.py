"""Durable centre-workspace preferences and teacher lifecycle state."""

from __future__ import annotations

from typing import Any

from config import PIPELINE_DATABASE_BACKEND
from database.db import get_db_connection
from database.postgres import get_postgres_connection


_POSTGRES_BACKENDS = {"postgres", "postgresql", "supabase"}
_LIFECYCLE_STATUSES = {"active", "completed", "archived"}


def _uses_postgres() -> bool:
    return str(PIPELINE_DATABASE_BACKEND or "").strip().lower() in _POSTGRES_BACKENDS


def get_center_onboarding_state(center_account_id: int) -> dict[str, Any] | None:
    center_id = int(center_account_id)
    if _uses_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, onboarding_version, onboarding_completed_at
                    FROM training_center_accounts
                    WHERE id = %s AND is_active = TRUE
                    """,
                    (center_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, COALESCE(onboarding_version, 0), onboarding_completed_at
            FROM training_center_accounts
            WHERE id = ? AND is_active = 1
            """,
            (center_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "onboarding_version": int(row[1] or 0),
            "onboarding_completed_at": row[2],
        }
    finally:
        conn.close()


def complete_center_onboarding(center_account_id: int, version: int) -> dict[str, Any] | None:
    center_id = int(center_account_id)
    completed_version = max(1, int(version))
    if _uses_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE training_center_accounts
                    SET onboarding_version = GREATEST(onboarding_version, %s),
                        onboarding_completed_at = NOW(),
                        updated_at = NOW()
                    WHERE id = %s AND is_active = TRUE
                    RETURNING id, onboarding_version, onboarding_completed_at
                    """,
                    (completed_version, center_id),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE training_center_accounts
            SET onboarding_version = MAX(COALESCE(onboarding_version, 0), ?),
                onboarding_completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND is_active = 1
            """,
            (completed_version, center_id),
        )
        conn.commit()
        if not cursor.rowcount:
            return None
        cursor.execute(
            """
            SELECT id, COALESCE(onboarding_version, 0), onboarding_completed_at
            FROM training_center_accounts WHERE id = ?
            """,
            (center_id,),
        )
        row = cursor.fetchone()
        return {
            "id": row[0],
            "onboarding_version": int(row[1] or 0),
            "onboarding_completed_at": row[2],
        }
    finally:
        conn.close()


def set_platform_lifecycle(
    platform_id: int,
    center_account_id: int,
    lifecycle_status: str,
) -> dict[str, Any] | None:
    platform_id = int(platform_id)
    center_id = int(center_account_id)
    lifecycle = str(lifecycle_status or "").strip().lower()
    if lifecycle not in _LIFECYCLE_STATUSES:
        raise ValueError("Statut de cycle de vie invalide")

    if _uses_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE platform_config
                    SET lifecycle_status = %s,
                        completed_at = CASE
                            WHEN %s = 'completed' THEN COALESCE(completed_at, NOW())
                            WHEN %s = 'active' THEN NULL
                            ELSE completed_at
                        END,
                        archived_at = CASE
                            WHEN %s = 'archived' THEN COALESCE(archived_at, NOW())
                            WHEN %s = 'active' THEN NULL
                            ELSE archived_at
                        END,
                        updated_at = NOW()
                    WHERE id = %s AND center_account_id = %s
                    RETURNING id, lifecycle_status, completed_at, archived_at,
                              asset_binding_mode
                    """,
                    (lifecycle, lifecycle, lifecycle, lifecycle, lifecycle, platform_id, center_id),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE platform_config
            SET lifecycle_status = ?,
                completed_at = CASE
                    WHEN ? = 'completed' THEN COALESCE(completed_at, CURRENT_TIMESTAMP)
                    WHEN ? = 'active' THEN NULL
                    ELSE completed_at
                END,
                archived_at = CASE
                    WHEN ? = 'archived' THEN COALESCE(archived_at, CURRENT_TIMESTAMP)
                    WHEN ? = 'active' THEN NULL
                    ELSE archived_at
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND center_account_id = ?
            """,
            (lifecycle, lifecycle, lifecycle, lifecycle, lifecycle, platform_id, center_id),
        )
        if not cursor.rowcount:
            return None
        conn.commit()
        cursor.execute(
            """
            SELECT id, lifecycle_status, completed_at, archived_at, asset_binding_mode
            FROM platform_config WHERE id = ?
            """,
            (platform_id,),
        )
        row = cursor.fetchone()
        return {
            "id": row[0],
            "lifecycle_status": row[1],
            "completed_at": row[2],
            "archived_at": row[3],
            "asset_binding_mode": row[4],
        }
    finally:
        conn.close()


def set_platform_asset_binding_mode(platform_id: int, mode: str) -> None:
    binding_mode = str(mode or "").strip().lower()
    if binding_mode not in {"canonical", "shared", "copy_on_write"}:
        raise ValueError("Mode de liaison des ressources invalide")
    if _uses_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE platform_config
                    SET asset_binding_mode = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (binding_mode, int(platform_id)),
                )
        return

    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE platform_config SET asset_binding_mode = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (binding_mode, int(platform_id)),
        )
        conn.commit()
    finally:
        conn.close()
