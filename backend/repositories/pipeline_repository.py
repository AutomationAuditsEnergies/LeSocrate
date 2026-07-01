"""Storage adapter for formation pipeline jobs.

The historical pipeline still has many SQLite-specific queries around folders,
segments and generated artifacts. This repository moves the centralized job
state behind a small adapter first, so Postgres can be enabled progressively
without changing the pipeline contract.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from config import PIPELINE_DATABASE_BACKEND, PIPELINE_POSTGRES_MIRROR
from database.db import get_db_connection
from database.postgres import get_postgres_connection, postgres_enabled
from utils.logger import get_logger


logger = get_logger(__name__)


PIPELINE_JOB_COLUMNS = [
    "id",
    "platform_id",
    "tp_name",
    "rncp_code",
    "total_hours",
    "nb_days",
    "reac_text",
    "rc_text",
    "rome_text",
    "global_program",
    "global_program_validated",
    "daily_programs",
    "daily_programs_validated",
    "status",
    "error_message",
    "kb_generated_via",
    "global_program_generated_via",
    "daily_programs_generated_via",
    "auto_pilot_enabled",
    "auto_pilot_step",
    "auto_pilot_model",
    "auto_pilot_tts_mode",
    "auto_pilot_use_cc",
    "auto_pilot_skip_vs",
    "auto_pilot_generate_audio",
    "auto_pilot_volume_done",
    "auto_pilot_post_review_docs_done",
    "auto_pilot_error",
    "auto_pilot_locked_at",
    "auto_pilot_lock_owner",
    "created_at",
    "updated_at",
]

PIPELINE_JOB_UPDATE_COLUMNS = {
    "status",
    "rncp_code",
    "reac_text",
    "rc_text",
    "rome_text",
    "global_program",
    "global_program_validated",
    "daily_programs",
    "daily_programs_validated",
    "error_message",
    "kb_generated_via",
    "global_program_generated_via",
    "daily_programs_generated_via",
    "auto_pilot_enabled",
    "auto_pilot_step",
    "auto_pilot_model",
    "auto_pilot_tts_mode",
    "auto_pilot_use_cc",
    "auto_pilot_skip_vs",
    "auto_pilot_generate_audio",
    "auto_pilot_volume_done",
    "auto_pilot_post_review_docs_done",
    "auto_pilot_error",
    "auto_pilot_locked_at",
    "auto_pilot_lock_owner",
}

PIPELINE_JOB_BOOL_COLUMNS = {
    "global_program_validated",
    "daily_programs_validated",
    "auto_pilot_enabled",
    "auto_pilot_use_cc",
    "auto_pilot_skip_vs",
    "auto_pilot_generate_audio",
    "auto_pilot_volume_done",
    "auto_pilot_post_review_docs_done",
}


def _pipeline_primary_backend() -> str:
    if PIPELINE_DATABASE_BACKEND in {"postgres", "postgresql", "supabase"}:
        return "postgres"
    return "sqlite"


def _pipeline_mirror_enabled() -> bool:
    return (
        _pipeline_primary_backend() == "sqlite"
        and PIPELINE_POSTGRES_MIRROR
        and postgres_enabled()
    )


def _normalize_job_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    for column in PIPELINE_JOB_BOOL_COLUMNS:
        if payload.get(column) is not None:
            payload[column] = bool(payload[column])
    return payload


def _as_sqlite_row_connection():
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_sqlite_job_payload(job_id: int) -> dict[str, Any] | None:
    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT {', '.join(PIPELINE_JOB_COLUMNS)} FROM formation_pipeline_jobs WHERE id = ?",
            (job_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _upsert_postgres_job(payload: dict[str, Any]) -> None:
    payload = _normalize_job_payload(payload)
    columns = [column for column in PIPELINE_JOB_COLUMNS if column in payload]
    update_columns = [column for column in columns if column != "id"]
    insert_columns = ", ".join(columns)
    placeholders = ", ".join(f"%({column})s" for column in columns)
    updates = ", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO formation_pipeline_jobs ({insert_columns})
                VALUES ({placeholders})
                ON CONFLICT (id) DO UPDATE SET {updates}
                """,
                payload,
            )
            cur.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('formation_pipeline_jobs', 'id')::regclass,
                    COALESCE((SELECT MAX(id) FROM formation_pipeline_jobs), 1),
                    TRUE
                )
                """
            )


def _mirror_sqlite_job_to_postgres(job_id: int) -> None:
    if not _pipeline_mirror_enabled():
        return
    try:
        payload = _fetch_sqlite_job_payload(job_id)
        if payload:
            _upsert_postgres_job(payload)
    except Exception:
        logger.warning(
            "⚠️ Miroir Postgres ignoré pour formation_pipeline_jobs.id=%s",
            job_id,
            exc_info=True,
        )


def _job_result(row: dict[str, Any] | sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    data = dict(row)
    job_id = data.get("id")
    platform_id = data.get("platform_id")
    return {
        "id": job_id,
        "job_label": f"Job #{job_id}",
        "platform_id": platform_id,
        "platform_label": f"P{platform_id}" if platform_id is not None else None,
        "tp_name": data.get("tp_name"),
        "rncp_code": data.get("rncp_code"),
        "total_hours": data.get("total_hours"),
        "nb_days": data.get("nb_days"),
        "reac_text": data.get("reac_text"),
        "rc_text": data.get("rc_text"),
        "rome_text": data.get("rome_text"),
        "global_program": data.get("global_program"),
        "global_program_validated": bool(data.get("global_program_validated")),
        "daily_programs": data.get("daily_programs"),
        "daily_programs_validated": bool(data.get("daily_programs_validated")),
        "status": data.get("status"),
        "error_message": data.get("error_message"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "kb_generated_via": data.get("kb_generated_via"),
        "global_program_generated_via": data.get("global_program_generated_via"),
        "daily_programs_generated_via": data.get("daily_programs_generated_via"),
        "platform_name": data.get("platform_name"),
        "auto_pilot_enabled": bool(data.get("auto_pilot_enabled")),
        "auto_pilot_step": data.get("auto_pilot_step"),
        "auto_pilot_model": data.get("auto_pilot_model"),
        "auto_pilot_tts_mode": data.get("auto_pilot_tts_mode"),
        "auto_pilot_use_cc": bool(data.get("auto_pilot_use_cc")),
        "auto_pilot_skip_vs": bool(data.get("auto_pilot_skip_vs")),
        "auto_pilot_generate_audio": bool(data.get("auto_pilot_generate_audio")),
        "auto_pilot_volume_done": bool(data.get("auto_pilot_volume_done")),
        "auto_pilot_post_review_docs_done": bool(data.get("auto_pilot_post_review_docs_done")),
        "auto_pilot_error": data.get("auto_pilot_error"),
        "auto_pilot_locked_at": data.get("auto_pilot_locked_at"),
        "auto_pilot_lock_owner": data.get("auto_pilot_lock_owner"),
    }


def create_pipeline_job(
    *,
    platform_id: int,
    tp_name: str,
    rncp_code: str,
    total_hours: int,
    nb_days: int,
) -> int:
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO formation_pipeline_jobs
                        (platform_id, tp_name, rncp_code, total_hours, nb_days, status)
                    VALUES (%s, %s, %s, %s, %s, 'init')
                    RETURNING id
                    """,
                    (platform_id, tp_name, rncp_code, total_hours, nb_days),
                )
                return int(cur.fetchone()["id"])

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO formation_pipeline_jobs
                (platform_id, tp_name, rncp_code, total_hours, nb_days, status)
            VALUES (?, ?, ?, ?, ?, 'init')
            """,
            (platform_id, tp_name, rncp_code, total_hours, nb_days),
        )
        job_id = int(cursor.lastrowid)
        conn.commit()
    finally:
        conn.close()
    _mirror_sqlite_job_to_postgres(job_id)
    return job_id


def update_pipeline_job(job_id: int, **kwargs) -> None:
    fields = {k: v for k, v in kwargs.items() if k in PIPELINE_JOB_UPDATE_COLUMNS}
    if "status" in fields and fields["status"] != "error" and "error_message" not in fields:
        fields["error_message"] = None
    if not fields:
        return

    if _pipeline_primary_backend() == "postgres":
        set_clause = ", ".join(f"{column} = %s" for column in fields)
        values = list(fields.values()) + [job_id]
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE formation_pipeline_jobs
                    SET {set_clause}, updated_at = NOW()
                    WHERE id = %s
                    """,
                    values,
                )
        return

    set_clause = ", ".join(f"{column} = ?" for column in fields)
    values = list(fields.values()) + [job_id]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            UPDATE formation_pipeline_jobs
            SET {set_clause}, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            values,
        )
        conn.commit()
    finally:
        conn.close()
    _mirror_sqlite_job_to_postgres(job_id)


def get_pipeline_job(job_id: int) -> dict[str, Any] | None:
    columns = ", ".join(f"j.{column}" for column in PIPELINE_JOB_COLUMNS)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {columns}, p.name AS platform_name
                    FROM formation_pipeline_jobs j
                    LEFT JOIN platform_config p ON p.id = j.platform_id
                    WHERE j.id = %s
                    """,
                    (job_id,),
                )
                return _job_result(cur.fetchone())

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT {columns}, p.name AS platform_name
            FROM formation_pipeline_jobs j
            LEFT JOIN platform_config p ON p.id = j.platform_id
            WHERE j.id = ?
            """,
            (job_id,),
        )
        return _job_result(cursor.fetchone())
    finally:
        conn.close()


def list_pipeline_jobs(platform_id: int | None = None) -> list[dict[str, Any]]:
    where_sql = ""
    params: tuple[Any, ...] = ()
    if platform_id is not None:
        where_sql = "WHERE j.platform_id = %s" if _pipeline_primary_backend() == "postgres" else "WHERE j.platform_id = ?"
        params = (platform_id,)
    columns = ", ".join(
        f"j.{column}"
        for column in (
            "id",
            "tp_name",
            "rncp_code",
            "total_hours",
            "nb_days",
            "status",
            "global_program_validated",
            "daily_programs_validated",
            "created_at",
            "updated_at",
            "platform_id",
        )
    )

    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {columns}, p.name AS platform_name
                    FROM formation_pipeline_jobs j
                    LEFT JOIN platform_config p ON p.id = j.platform_id
                    {where_sql}
                    ORDER BY j.created_at DESC
                    """,
                    params,
                )
                rows = cur.fetchall()
    else:
        conn = _as_sqlite_row_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT {columns}, p.name AS platform_name
                FROM formation_pipeline_jobs j
                LEFT JOIN platform_config p ON p.id = j.platform_id
                {where_sql}
                ORDER BY j.created_at DESC
                """,
                params,
            )
            rows = cursor.fetchall()
        finally:
            conn.close()

    result = []
    for row in rows:
        data = dict(row)
        platform = data.get("platform_id")
        result.append(
            {
                "id": data.get("id"),
                "tp_name": data.get("tp_name"),
                "rncp_code": data.get("rncp_code"),
                "job_label": f"Job #{data.get('id')}",
                "total_hours": data.get("total_hours"),
                "nb_days": data.get("nb_days"),
                "status": data.get("status"),
                "global_program_validated": bool(data.get("global_program_validated")),
                "daily_programs_validated": bool(data.get("daily_programs_validated")),
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
                "platform_id": platform,
                "platform_label": f"P{platform}" if platform is not None else None,
                "platform_name": data.get("platform_name"),
            }
        )
    return result


def get_auto_pilot_pipeline_jobs_to_resume() -> list[int]:
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id
                    FROM formation_pipeline_jobs
                    WHERE auto_pilot_enabled = TRUE
                      AND (auto_pilot_step IS NULL OR auto_pilot_step != 'done')
                      AND auto_pilot_error IS NULL
                      AND (
                            auto_pilot_locked_at IS NULL
                            OR auto_pilot_locked_at < NOW() - INTERVAL '5 minutes'
                          )
                    """
                )
                return [int(row["id"]) for row in cur.fetchall()]

    stale_cutoff = int(time.time()) - 300
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id FROM formation_pipeline_jobs
            WHERE auto_pilot_enabled = 1
              AND (auto_pilot_step IS NULL OR auto_pilot_step != 'done')
              AND auto_pilot_error IS NULL
              AND (auto_pilot_locked_at IS NULL
                   OR CAST(strftime('%s', auto_pilot_locked_at) AS INTEGER) < ?)
            """,
            (stale_cutoff,),
        )
        rows = cursor.fetchall()
        return [int(row[0]) for row in rows]
    finally:
        conn.close()
