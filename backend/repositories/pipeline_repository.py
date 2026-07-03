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

CONTENT_REVIEW_STATE_COLUMNS = {
    "reviewed",
    "review_error",
    "review_signature",
    "humanized",
    "humanization_error",
    "humanization_signature",
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


def _placeholder() -> str:
    return "%s" if _pipeline_primary_backend() == "postgres" else "?"


def _validate_content_review_columns(*columns: str) -> None:
    for column in columns:
        if column not in CONTENT_REVIEW_STATE_COLUMNS:
            raise ValueError(f"Colonne review non autorisée : {column}")


def _normalize_job_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    for column in PIPELINE_JOB_BOOL_COLUMNS:
        if payload.get(column) is not None:
            payload[column] = _coerce_bool(payload[column])
    return payload


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _normalize_job_update_fields(fields: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(fields)
    for column in PIPELINE_JOB_BOOL_COLUMNS:
        if column in normalized and normalized[column] is not None:
            normalized[column] = _coerce_bool(normalized[column])
    return normalized


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


def list_expected_course_folder_matches(job_id: int, folder_name: str) -> list[dict[str, Any]]:
    """Return candidate folders for one expected day, best candidate first."""
    ph = _placeholder()
    query = f"""
        SELECT
            cf.id,
            cf.name,
            cf.position,
            cf.platform_id,
            cf.formation_job_id,
            cgj.id AS content_job_id,
            cgj.status AS content_status,
            COALESCE(cgj.total_words, 0) AS total_words,
            COALESCE(SUM(CASE WHEN cgs.status = 'completed' THEN 1 ELSE 0 END), 0) AS segments_completed
        FROM cours_folders cf
        LEFT JOIN content_generation_jobs cgj ON cgj.folder_id = cf.id
        LEFT JOIN content_generation_segments cgs ON cgs.job_id = cgj.id
        WHERE cf.formation_job_id = {ph} AND cf.name = {ph}
        GROUP BY cf.id, cf.name, cf.position, cf.platform_id, cf.formation_job_id,
                 cgj.id, cgj.status, cgj.total_words
        ORDER BY
            CASE
                WHEN cgj.status = 'completed' THEN 0
                WHEN COALESCE(cgj.total_words, 0) > 0 THEN 1
                WHEN cgj.status = 'running' THEN 2
                WHEN cgj.status = 'idle' THEN 3
                WHEN cgj.id IS NULL THEN 5
                ELSE 4
            END,
            COALESCE(cgj.total_words, 0) DESC,
            COALESCE(SUM(CASE WHEN cgs.status = 'completed' THEN 1 ELSE 0 END), 0) DESC,
            cf.position ASC,
            cf.id ASC
    """

    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id, folder_name))
                return [dict(row) for row in cur.fetchall()]

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (job_id, folder_name))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def create_course_folder_for_job(
    *,
    platform_id: int,
    folder_name: str,
    formation_job_id: int,
) -> dict[str, Any]:
    """Create a course folder at the next platform position."""
    ph = _placeholder()
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COALESCE(MAX(position), -1) + 1 AS position FROM cours_folders WHERE platform_id = {ph}",
                    (platform_id,),
                )
                position = int(cur.fetchone()["position"])
                cur.execute(
                    """
                    INSERT INTO cours_folders (platform_id, name, position, formation_job_id)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, name, position, platform_id, formation_job_id
                    """,
                    (platform_id, folder_name, position, formation_job_id),
                )
                row = dict(cur.fetchone())
    else:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM cours_folders WHERE platform_id = ?",
                (platform_id,),
            )
            position = int(cursor.fetchone()[0])
            cursor.execute(
                "INSERT INTO cours_folders (platform_id, name, position, formation_job_id) VALUES (?, ?, ?, ?)",
                (platform_id, folder_name, position, formation_job_id),
            )
            folder_id = int(cursor.lastrowid)
            conn.commit()
            row = {
                "id": folder_id,
                "name": folder_name,
                "position": position,
                "platform_id": platform_id,
                "formation_job_id": formation_job_id,
            }
        finally:
            conn.close()

    return {
        **row,
        "content_job_id": None,
        "content_status": None,
        "total_words": 0,
        "segments_completed": 0,
    }


def course_folder_exists_for_job(job_id: int, folder_name: str) -> bool:
    ph = _placeholder()
    query = f"""
        SELECT 1
        FROM cours_folders
        WHERE formation_job_id = {ph} AND name = {ph}
        LIMIT 1
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id, folder_name))
                return cur.fetchone() is not None

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, (job_id, folder_name))
        return cursor.fetchone() is not None
    finally:
        conn.close()


def find_orphan_course_folder(platform_id: int, folder_name: str) -> int | None:
    ph = _placeholder()
    query = f"""
        SELECT cf.id
        FROM cours_folders cf
        LEFT JOIN content_generation_jobs cgj ON cgj.folder_id = cf.id
        WHERE cf.platform_id = {ph}
          AND cf.name = {ph}
          AND cf.formation_job_id IS NULL
        ORDER BY CASE WHEN cgj.id IS NULL THEN 1 ELSE 0 END,
                 cf.created_at DESC,
                 cf.id DESC
        LIMIT 1
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (platform_id, folder_name))
                row = cur.fetchone()
                return int(row["id"]) if row else None

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, (platform_id, folder_name))
        row = cursor.fetchone()
        return int(row[0]) if row else None
    finally:
        conn.close()


def attach_course_folder_to_job(job_id: int, folder_id: int) -> bool:
    ph = _placeholder()
    query = f"""
        UPDATE cours_folders
        SET formation_job_id = {ph}
        WHERE id = {ph} AND formation_job_id IS NULL
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id, folder_id))
                return cur.rowcount > 0

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, (job_id, folder_id))
        changed = cursor.rowcount > 0
        conn.commit()
        return changed
    finally:
        conn.close()


def ensure_pipeline_observability_tables() -> None:
    """Create observability tables for SQLite deployments.

    Postgres deployments rely on postgres_schema.sql so schema management stays
    explicit and migration-friendly.
    """
    if _pipeline_primary_backend() == "postgres":
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS content_review_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                folder_id INTEGER NOT NULL,
                source TEXT DEFAULT 'api',
                generated_via TEXT,
                summary_json TEXT DEFAULT '{}',
                report_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_content_review_reports_job_folder
            ON content_review_reports(job_id, folder_id, created_at)
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS formation_pipeline_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                folder_id INTEGER,
                step TEXT,
                event_type TEXT NOT NULL,
                status TEXT DEFAULT 'info',
                message TEXT,
                model TEXT,
                duration_ms INTEGER,
                data_json TEXT DEFAULT '{}',
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_formation_pipeline_events_job
            ON formation_pipeline_events(job_id, created_at)
            """
        )
        conn.commit()
    finally:
        conn.close()


def insert_review_report(
    *,
    job_id: int,
    folder_id: int,
    source: str,
    generated_via: str | None,
    summary_json: str,
    report_json: str,
) -> int:
    ensure_pipeline_observability_tables()
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO content_review_reports
                    (job_id, folder_id, source, generated_via, summary_json, report_json)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (job_id, folder_id, source, generated_via, summary_json, report_json),
                )
                return int(cur.fetchone()["id"])

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO content_review_reports
            (job_id, folder_id, source, generated_via, summary_json, report_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job_id, folder_id, source, generated_via, summary_json, report_json),
        )
        report_id = int(cursor.lastrowid)
        conn.commit()
        return report_id
    finally:
        conn.close()


def get_latest_review_report_row(
    *,
    job_id: int,
    folder_id: int,
    kind: str = "compliance",
) -> dict[str, Any] | None:
    ensure_pipeline_observability_tables()
    ph = _placeholder()
    source_filter = "source LIKE '%humanization%'" if kind == "humanization" else "source NOT LIKE '%humanization%'"
    query = f"""
        SELECT id, source, generated_via, report_json, created_at
        FROM content_review_reports
        WHERE job_id = {ph} AND folder_id = {ph} AND {source_filter}
        ORDER BY created_at DESC, id DESC
        LIMIT 1
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id, folder_id))
                row = cur.fetchone()
                return dict(row) if row else None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (job_id, folder_id))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def insert_pipeline_event(
    *,
    job_id: int,
    event_type: str,
    step: str | None,
    status: str,
    folder_id: int | None,
    message: str | None,
    model: str | None,
    duration_ms: int | None,
    data_json: str,
    error: str | None,
) -> int:
    ensure_pipeline_observability_tables()
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO formation_pipeline_events
                    (job_id, folder_id, step, event_type, status, message, model,
                     duration_ms, data_json, error)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        job_id,
                        folder_id,
                        step,
                        event_type,
                        status,
                        message,
                        model,
                        duration_ms,
                        data_json,
                        error,
                    ),
                )
                return int(cur.fetchone()["id"])

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO formation_pipeline_events
            (job_id, folder_id, step, event_type, status, message, model,
             duration_ms, data_json, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                folder_id,
                step,
                event_type,
                status,
                message,
                model,
                duration_ms,
                data_json,
                error,
            ),
        )
        event_id = int(cursor.lastrowid)
        conn.commit()
        return event_id
    finally:
        conn.close()


def list_pipeline_event_rows(job_id: int, *, limit: int = 200) -> list[dict[str, Any]]:
    ensure_pipeline_observability_tables()
    limit = max(1, min(int(limit or 200), 500))
    ph = _placeholder()
    query = f"""
        SELECT id, job_id, folder_id, step, event_type, status, message, model,
               duration_ms, data_json, error, created_at
        FROM formation_pipeline_events
        WHERE job_id = {ph}
        ORDER BY created_at DESC, id DESC
        LIMIT {ph}
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id, limit))
                return [dict(row) for row in cur.fetchall()]

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (job_id, limit))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def delete_pipeline_events(
    *,
    job_id: int,
    folder_id: int | None = None,
    include_global_events: bool = True,
) -> int:
    ensure_pipeline_observability_tables()
    ph = _placeholder()
    if folder_id is None:
        query = f"DELETE FROM formation_pipeline_events WHERE job_id = {ph}"
        params = (job_id,)
    elif include_global_events:
        query = f"""
            DELETE FROM formation_pipeline_events
            WHERE job_id = {ph} AND (folder_id = {ph} OR folder_id IS NULL)
        """
        params = (job_id, folder_id)
    else:
        query = f"DELETE FROM formation_pipeline_events WHERE job_id = {ph} AND folder_id = {ph}"
        params = (job_id, folder_id)

    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return int(cur.rowcount or 0)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        deleted = int(cursor.rowcount or 0)
        conn.commit()
        return deleted
    finally:
        conn.close()


def clear_knowledge_base(job_id: int) -> None:
    ph = _placeholder()
    query = f"DELETE FROM formation_knowledge_base WHERE job_id = {ph}"
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id,))
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, (job_id,))
        conn.commit()
    finally:
        conn.close()


def upsert_pending_knowledge_base_entries(job_id: int, competences: list[dict[str, Any]]) -> None:
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                for idx, competence in enumerate(competences):
                    cur.execute(
                        """
                        INSERT INTO formation_knowledge_base
                            (job_id, competence_index, competence_key, competence_title,
                             bloc, raw_source, status, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, 'pending', NOW())
                        ON CONFLICT (job_id, competence_index) DO UPDATE SET
                            competence_key = EXCLUDED.competence_key,
                            competence_title = EXCLUDED.competence_title,
                            bloc = EXCLUDED.bloc,
                            raw_source = EXCLUDED.raw_source,
                            status = 'pending',
                            updated_at = NOW()
                        """,
                        (
                            job_id,
                            idx,
                            competence["competence_key"],
                            competence["competence_title"],
                            competence.get("bloc", ""),
                            competence.get("raw_source", ""),
                        ),
                    )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        for idx, competence in enumerate(competences):
            cursor.execute(
                """INSERT OR REPLACE INTO formation_knowledge_base
                   (job_id, competence_index, competence_key, competence_title, bloc, raw_source, status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP)""",
                (
                    job_id,
                    idx,
                    competence["competence_key"],
                    competence["competence_title"],
                    competence.get("bloc", ""),
                    competence.get("raw_source", ""),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def save_enriched_knowledge_base_entry(
    *,
    job_id: int,
    competence_index: int,
    definition_pedagogique: str,
    etudes_de_cas_json: str,
    pieges_frequents_json: str,
    vocabulaire_metier_json: str,
    contexte_terrain: str,
    liens_connexes_json: str,
    word_count: int,
) -> None:
    ph = _placeholder()
    now_sql = "NOW()" if _pipeline_primary_backend() == "postgres" else "CURRENT_TIMESTAMP"
    query = f"""
        UPDATE formation_knowledge_base
        SET definition_pedagogique = {ph},
            etudes_de_cas = {ph},
            pieges_frequents = {ph},
            vocabulaire_metier = {ph},
            contexte_terrain = {ph},
            liens_connexes = {ph},
            total_words = {ph},
            status = 'completed',
            dirty = {ph},
            error_message = NULL,
            updated_at = {now_sql}
        WHERE job_id = {ph} AND competence_index = {ph}
    """
    params = (
        definition_pedagogique,
        etudes_de_cas_json,
        pieges_frequents_json,
        vocabulaire_metier_json,
        contexte_terrain,
        liens_connexes_json,
        word_count,
        False if _pipeline_primary_backend() == "postgres" else 0,
        job_id,
        competence_index,
    )
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def mark_knowledge_base_entry_error(job_id: int, competence_index: int, error_msg: str) -> None:
    ph = _placeholder()
    now_sql = "NOW()" if _pipeline_primary_backend() == "postgres" else "CURRENT_TIMESTAMP"
    query = f"""
        UPDATE formation_knowledge_base
        SET status = 'error', error_message = {ph}, updated_at = {now_sql}
        WHERE job_id = {ph} AND competence_index = {ph}
    """
    params = (error_msg, job_id, competence_index)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def list_knowledge_base_rows(job_id: int) -> list[dict[str, Any]]:
    ph = _placeholder()
    query = f"""
        SELECT id, competence_index, competence_key, competence_title, bloc,
               definition_pedagogique, etudes_de_cas, pieges_frequents,
               vocabulaire_metier, contexte_terrain, liens_connexes,
               status, total_words, error_message, raw_source
        FROM formation_knowledge_base
        WHERE job_id = {ph}
        ORDER BY competence_index
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id,))
                return [dict(row) for row in cur.fetchall()]

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (job_id,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def knowledge_base_stats_rows(job_id: int) -> list[dict[str, Any]]:
    ph = _placeholder()
    query = f"""
        SELECT status, COUNT(*) AS count, COALESCE(SUM(total_words), 0) AS words
        FROM formation_knowledge_base
        WHERE job_id = {ph}
        GROUP BY status
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id,))
                return [dict(row) for row in cur.fetchall()]

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (job_id,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def reset_and_upsert_content_generation_job(
    *,
    folder_id: int,
    platform_id: int,
    program_text: str,
    program_title: str,
    sub_parts_json: str,
    from_scratch: bool,
    module_contents_json: str,
) -> None:
    """Reset segments for a folder and create/update its content generation job."""
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM content_generation_segments
                    WHERE job_id IN (
                        SELECT id FROM content_generation_jobs WHERE folder_id = %s
                    )
                    """,
                    (folder_id,),
                )
                cur.execute(
                    """
                    INSERT INTO content_generation_jobs
                        (folder_id, platform_id, program_text, program_title, sub_parts,
                         from_scratch, module_contents,
                         status, current_sub_part, current_passe, total_words, error_message,
                         updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'idle', 0, 1, 0, NULL, NOW())
                    ON CONFLICT (folder_id) DO UPDATE SET
                        platform_id = EXCLUDED.platform_id,
                        program_text = EXCLUDED.program_text,
                        program_title = EXCLUDED.program_title,
                        sub_parts = EXCLUDED.sub_parts,
                        from_scratch = EXCLUDED.from_scratch,
                        module_contents = EXCLUDED.module_contents,
                        status = 'idle',
                        current_sub_part = 0,
                        current_passe = 1,
                        total_words = 0,
                        error_message = NULL,
                        updated_at = NOW()
                    """,
                    (
                        folder_id,
                        platform_id,
                        program_text,
                        program_title,
                        sub_parts_json,
                        bool(from_scratch),
                        module_contents_json,
                    ),
                )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            DELETE FROM content_generation_segments WHERE job_id IN (
                SELECT id FROM content_generation_jobs WHERE folder_id = ?
            )
            """,
            (folder_id,),
        )
        cursor.execute(
            """
            INSERT OR REPLACE INTO content_generation_jobs
                (folder_id, platform_id, program_text, program_title, sub_parts,
                 from_scratch, module_contents,
                 status, current_sub_part, current_passe, total_words, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'idle', 0, 1, 0, NULL)
            """,
            (
                folder_id,
                platform_id,
                program_text,
                program_title,
                sub_parts_json,
                1 if from_scratch else 0,
                module_contents_json,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_content_generation_job_by_folder(folder_id: int) -> dict[str, Any] | None:
    ph = _placeholder()
    query = f"""
        SELECT cgj.id, cgj.platform_id, cgj.program_text, cgj.program_title,
               cgj.sub_parts, cgj.status, cgj.current_sub_part,
               cgj.current_passe, cgj.total_words, cgj.error_message,
               cgj.from_scratch, cgj.module_contents,
               cgj.carryover_in_text, cgj.carryover_in_source_folder_id,
               cgj.carryover_out_text, cgj.carryover_out_target_folder_id,
               cf.formation_job_id, cf.name, cf.position,
               fpj.nb_days, fpj.total_hours
        FROM content_generation_jobs cgj
        LEFT JOIN cours_folders cf ON cf.id = cgj.folder_id
        LEFT JOIN formation_pipeline_jobs fpj ON fpj.id = cf.formation_job_id
        WHERE cgj.folder_id = {ph}
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (folder_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (folder_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_content_segment_status_rows(job_id: int) -> list[dict[str, Any]]:
    ph = _placeholder()
    query = f"""
        SELECT sub_part_index, sub_part_name, passe, status, word_count
        FROM content_generation_segments
        WHERE job_id = {ph}
        ORDER BY sub_part_index ASC, passe ASC
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id,))
                return [dict(row) for row in cur.fetchall()]

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (job_id,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def update_content_generation_job(job_id: int, **kwargs) -> None:
    if not kwargs:
        return
    ph = _placeholder()
    now_sql = "NOW()" if _pipeline_primary_backend() == "postgres" else "CURRENT_TIMESTAMP"
    set_clause = ", ".join(f"{key} = {ph}" for key in kwargs)
    query = f"""
        UPDATE content_generation_jobs
        SET {set_clause}, updated_at = {now_sql}
        WHERE id = {ph}
    """
    values = list(kwargs.values()) + [job_id]
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, values)
        conn.commit()
    finally:
        conn.close()


def completed_content_segment_keys(job_id: int) -> set[tuple[int, int]]:
    ph = _placeholder()
    query = f"""
        SELECT sub_part_index, passe
        FROM content_generation_segments
        WHERE job_id = {ph} AND status = 'completed'
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id,))
                return {(int(row["sub_part_index"]), int(row["passe"])) for row in cur.fetchall()}

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, (job_id,))
        return {(int(row[0]), int(row[1])) for row in cursor.fetchall()}
    finally:
        conn.close()


def save_completed_content_segment(
    *,
    job_id: int,
    sub_part_index: int,
    sub_part_name: str,
    passe: int,
    text_content: str,
    word_count: int,
) -> None:
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO content_generation_segments
                        (job_id, sub_part_index, sub_part_name, passe, status,
                         text_content, word_count, dirty,
                         humanized, humanization_error, humanization_signature,
                         reviewed, review_error, review_signature)
                    VALUES (%s, %s, %s, %s, 'completed', %s, %s, TRUE, FALSE, NULL, NULL, FALSE, NULL, NULL)
                    ON CONFLICT (job_id, sub_part_index, passe) DO UPDATE SET
                         sub_part_name = EXCLUDED.sub_part_name,
                         status = 'completed',
                         text_content = EXCLUDED.text_content,
                         word_count = EXCLUDED.word_count,
                         dirty = TRUE,
                         humanized = FALSE,
                         humanization_error = NULL,
                         humanization_signature = NULL,
                         reviewed = FALSE,
                         review_error = NULL,
                         review_signature = NULL
                    """,
                    (job_id, sub_part_index, sub_part_name, passe, text_content, word_count),
                )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT OR REPLACE INTO content_generation_segments
                (job_id, sub_part_index, sub_part_name, passe, status,
                 text_content, word_count, dirty,
                 humanized, humanization_error, humanization_signature,
                 reviewed, review_error, review_signature)
            VALUES (?, ?, ?, ?, 'completed', ?, ?, 1, 0, NULL, NULL, 0, NULL, NULL)
            """,
            (job_id, sub_part_index, sub_part_name, passe, text_content, word_count),
        )
        conn.commit()
    finally:
        conn.close()


def mark_content_segment_modified(job_id: int, sub_part_index: int, passe: int) -> None:
    ph = _placeholder()
    query = f"""
        UPDATE content_generation_segments
        SET dirty = {ph},
            humanized = {ph}, humanization_error = NULL, humanization_signature = NULL,
            reviewed = {ph}, review_error = NULL, review_signature = NULL
        WHERE job_id = {ph} AND sub_part_index = {ph} AND passe = {ph}
    """
    if _pipeline_primary_backend() == "postgres":
        params = (True, False, False, job_id, sub_part_index, passe)
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
        return

    params = (1, 0, 0, job_id, sub_part_index, passe)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def get_content_segment_text(job_id: int, sub_part_index: int, passe: int) -> str:
    ph = _placeholder()
    query = f"""
        SELECT text_content
        FROM content_generation_segments
        WHERE job_id = {ph} AND sub_part_index = {ph} AND passe = {ph}
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id, sub_part_index, passe))
                row = cur.fetchone()
                return row["text_content"] if row else ""

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, (job_id, sub_part_index, passe))
        row = cursor.fetchone()
        return row[0] if row else ""
    finally:
        conn.close()


def list_completed_content_segment_rows(job_id: int) -> list[dict[str, Any]]:
    ph = _placeholder()
    if _pipeline_primary_backend() == "postgres":
        query = f"""
            SELECT id, sub_part_index, sub_part_name, passe, text_content, word_count, dirty,
                   COALESCE(humanized, FALSE) AS humanized,
                   COALESCE(reviewed, FALSE) AS reviewed,
                   humanization_error, review_error
            FROM content_generation_segments
            WHERE job_id = {ph} AND status = 'completed'
            ORDER BY sub_part_index ASC, passe ASC
        """
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id,))
                return [dict(row) for row in cur.fetchall()]

    query = f"""
        SELECT id, sub_part_index, sub_part_name, passe, text_content, word_count, dirty,
               COALESCE(humanized, 0) AS humanized, COALESCE(reviewed, 0) AS reviewed,
               humanization_error, review_error
        FROM content_generation_segments
        WHERE job_id = {ph} AND status = 'completed'
        ORDER BY sub_part_index ASC, passe ASC
    """
    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (job_id,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def delete_content_segments_for_job(job_id: int) -> None:
    ph = _placeholder()
    query = f"DELETE FROM content_generation_segments WHERE job_id = {ph}"
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id,))
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, (job_id,))
        conn.commit()
    finally:
        conn.close()


def mark_content_segments_clean(job_id: int, seg_keys) -> None:
    unique_keys = sorted(set(seg_keys or []))
    if not unique_keys:
        return

    ph = _placeholder()
    query = f"""
        UPDATE content_generation_segments
        SET dirty = {ph}
        WHERE job_id = {ph} AND sub_part_index = {ph} AND passe = {ph}
    """
    clean_value = False if _pipeline_primary_backend() == "postgres" else 0
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                for sub_idx, passe in unique_keys:
                    cur.execute(query, (clean_value, job_id, sub_idx, passe))
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        for sub_idx, passe in unique_keys:
            cursor.execute(query, (clean_value, job_id, sub_idx, passe))
        conn.commit()
    finally:
        conn.close()


def update_content_segment_audio_calibration(
    *,
    segment_id: int,
    text_content: str,
    word_count: int,
    humanization_signature: str,
) -> None:
    ph = _placeholder()
    query = f"""
        UPDATE content_generation_segments
        SET text_content = {ph}, word_count = {ph}, dirty = {ph},
            humanized = {ph}, humanization_error = NULL, humanization_signature = {ph},
            reviewed = {ph}, review_error = NULL, review_signature = NULL
        WHERE id = {ph}
    """
    if _pipeline_primary_backend() == "postgres":
        params = (
            text_content,
            word_count,
            True,
            True,
            humanization_signature,
            False,
            segment_id,
        )
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
        return

    params = (text_content, word_count, 1, 1, humanization_signature, 0, segment_id)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def update_content_segment_plan_repair(
    *,
    segment_id: int,
    text_content: str,
    word_count: int,
) -> None:
    ph = _placeholder()
    query = f"""
        UPDATE content_generation_segments
        SET text_content = {ph}, word_count = {ph}, dirty = {ph},
            humanized = {ph}, humanization_error = NULL, humanization_signature = NULL,
            reviewed = {ph}, review_error = NULL, review_signature = NULL
        WHERE id = {ph}
    """
    if _pipeline_primary_backend() == "postgres":
        params = (text_content, word_count, True, False, False, segment_id)
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
        return

    params = (text_content, word_count, 1, 0, 0, segment_id)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def ensure_content_review_state_columns() -> None:
    """Ensure SQLite has the review state columns. Postgres schema owns this."""
    if _pipeline_primary_backend() == "postgres":
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        for sql in (
            "ALTER TABLE content_generation_segments ADD COLUMN review_signature TEXT",
            "ALTER TABLE content_generation_segments ADD COLUMN humanized INTEGER DEFAULT 0",
            "ALTER TABLE content_generation_segments ADD COLUMN humanization_error TEXT",
            "ALTER TABLE content_generation_segments ADD COLUMN humanization_signature TEXT",
        ):
            try:
                cursor.execute(sql)
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()


def snapshot_content_segments_pre_review(job_id: int) -> int:
    ph = _placeholder()
    if _pipeline_primary_backend() == "postgres":
        query = f"""
            UPDATE content_generation_segments
            SET text_content_pre_review = text_content
            WHERE job_id = {ph}
              AND status = 'completed'
              AND text_content_pre_review IS NULL
        """
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id,))
                return int(cur.rowcount or 0)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        try:
            cursor.execute(
                "ALTER TABLE content_generation_segments ADD COLUMN text_content_pre_review TEXT"
            )
            conn.commit()
        except Exception:
            pass
        cursor.execute(
            f"""
            UPDATE content_generation_segments
            SET text_content_pre_review = text_content
            WHERE job_id = {ph}
              AND status = 'completed'
              AND text_content_pre_review IS NULL
            """,
            (job_id,),
        )
        snapshotted = int(cursor.rowcount or 0)
        conn.commit()
        return snapshotted
    finally:
        conn.close()


def select_content_segments_for_review(
    *,
    job_id: int,
    reviewed_column: str,
    signature_column: str,
    review_signature: str,
    force: bool,
) -> tuple[int, list[dict[str, Any]]]:
    _validate_content_review_columns(reviewed_column, signature_column)
    ph = _placeholder()
    total_query = f"""
        SELECT COUNT(*) AS total
        FROM content_generation_segments
        WHERE job_id = {ph} AND status = 'completed'
    """
    base_select = f"""
        SELECT id, sub_part_index, sub_part_name, passe, text_content
        FROM content_generation_segments
        WHERE job_id = {ph} AND status = 'completed'
    """
    order_sql = " ORDER BY sub_part_index ASC, passe ASC"

    if _pipeline_primary_backend() == "postgres":
        if force:
            select_query = base_select + order_sql
            params = (job_id,)
        else:
            select_query = (
                base_select
                + f"""
                  AND (
                        COALESCE({reviewed_column}, FALSE) = FALSE
                     OR {signature_column} IS NULL
                     OR {signature_column} != {ph}
                  )
                """
                + order_sql
            )
            params = (job_id, review_signature)
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(total_query, (job_id,))
                total_completed = int(cur.fetchone()["total"] or 0)
                cur.execute(select_query, params)
                return total_completed, [dict(row) for row in cur.fetchall()]

    if force:
        select_query = base_select + order_sql
        params = (job_id,)
    else:
        select_query = (
            base_select
            + f"""
              AND (
                    COALESCE({reviewed_column}, 0) = 0
                 OR {signature_column} IS NULL
                 OR {signature_column} != {ph}
              )
            """
            + order_sql
        )
        params = (job_id, review_signature)

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(total_query, (job_id,))
        total_completed = int(cursor.fetchone()["total"] or 0)
        cursor.execute(select_query, params)
        return total_completed, [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def reset_content_segments_review_state(
    *,
    segment_ids: list[int],
    reviewed_column: str,
    error_column: str,
) -> None:
    _validate_content_review_columns(reviewed_column, error_column)
    if not segment_ids:
        return

    ph = _placeholder()
    placeholders = ", ".join([ph] * len(segment_ids))
    query = f"""
        UPDATE content_generation_segments
        SET {reviewed_column} = {ph}, {error_column} = NULL
        WHERE id IN ({placeholders})
    """
    reviewed_value = False if _pipeline_primary_backend() == "postgres" else 0
    params = [reviewed_value, *segment_ids]
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def record_content_segment_review_error(
    *,
    segment_id: int,
    error_column: str,
    error_message: str,
) -> None:
    _validate_content_review_columns(error_column)
    ph = _placeholder()
    query = f"UPDATE content_generation_segments SET {error_column} = {ph} WHERE id = {ph}"
    params = ((error_message or "")[:500], segment_id)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def mark_content_segment_review_patched(
    *,
    segment_id: int,
    text_content: str,
    word_count: int,
    reviewed_column: str,
    error_column: str,
    signature_column: str,
    review_signature: str,
    invalidate_compliance_on_change: bool,
) -> None:
    _validate_content_review_columns(reviewed_column, error_column, signature_column)
    ph = _placeholder()
    if _pipeline_primary_backend() == "postgres":
        bool_dirty = True
        bool_reviewed = True
        query = f"""
            UPDATE content_generation_segments
            SET text_content = {ph}, word_count = {ph}, dirty = {ph},
                {reviewed_column} = {ph}, {error_column} = NULL, {signature_column} = {ph}
                {", reviewed = FALSE, review_error = NULL, review_signature = NULL" if invalidate_compliance_on_change else ""}
            WHERE id = {ph}
        """
    else:
        bool_dirty = 1
        bool_reviewed = 1
        query = f"""
            UPDATE content_generation_segments
            SET text_content = {ph}, word_count = {ph}, dirty = {ph},
                {reviewed_column} = {ph}, {error_column} = NULL, {signature_column} = {ph}
                {", reviewed = 0, review_error = NULL, review_signature = NULL" if invalidate_compliance_on_change else ""}
            WHERE id = {ph}
        """
    params = (text_content, word_count, bool_dirty, bool_reviewed, review_signature, segment_id)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def mark_content_segment_review_clean(
    *,
    segment_id: int,
    reviewed_column: str,
    error_column: str,
    signature_column: str,
    review_signature: str,
) -> None:
    _validate_content_review_columns(reviewed_column, error_column, signature_column)
    ph = _placeholder()
    reviewed_value = True if _pipeline_primary_backend() == "postgres" else 1
    query = f"""
        UPDATE content_generation_segments
        SET {reviewed_column} = {ph}, {error_column} = NULL, {signature_column} = {ph}
        WHERE id = {ph}
    """
    params = (reviewed_value, review_signature, segment_id)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def list_final_script_document_rows(folder_id: int) -> list[dict[str, Any]]:
    ph = _placeholder()
    query = f"""
        SELECT id, filename, audio_filename
        FROM cours_documents
        WHERE folder_id = {ph}
          AND (doc_type = 'final_script' OR original_name LIKE 'cours_genere_%.txt')
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (folder_id,))
                return [dict(row) for row in cur.fetchall()]

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (folder_id,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def replace_final_script_document_record(
    *,
    folder_id: int,
    filename: str,
    original_name: str,
) -> None:
    ph = _placeholder()
    delete_query = f"""
        DELETE FROM cours_documents
        WHERE folder_id = {ph}
          AND (doc_type = 'final_script' OR original_name LIKE 'cours_genere_%.txt')
    """
    insert_query = f"""
        INSERT INTO cours_documents (folder_id, filename, original_name, doc_type, status)
        VALUES ({ph}, {ph}, {ph}, 'final_script', 'uploaded')
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(delete_query, (folder_id,))
                cur.execute(insert_query, (folder_id, filename, original_name))
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(delete_query, (folder_id,))
        cursor.execute(insert_query, (folder_id, filename, original_name))
        conn.commit()
    finally:
        conn.close()


def list_due_audio_generation_sessions(
    *,
    lower_bound,
    upper_bound,
    platform_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    ph = _placeholder()
    params: list[Any] = [lower_bound, upper_bound]
    platform_filter = ""
    if platform_ids:
        ids = [int(pid) for pid in platform_ids]
        placeholders = ", ".join([ph] * len(ids))
        platform_filter = f"AND cs.platform_id IN ({placeholders})"
        params.extend(ids)

    query = f"""
        SELECT
            cs.id,
            cs.platform_id,
            cs.session_index,
            cs.scheduled_at,
            pc.name,
            COALESCE(
                pc.source_formation_id,
                (
                    SELECT j.id
                    FROM formation_pipeline_jobs j
                    WHERE j.platform_id = cs.platform_id
                    ORDER BY j.id DESC
                    LIMIT 1
                )
            ) AS formation_job_id
        FROM course_sessions cs
        JOIN platform_config pc ON pc.id = cs.platform_id
        WHERE cs.status IN ('planned', 'active')
          AND cs.scheduled_at >= {ph}
          AND cs.scheduled_at <= {ph}
          AND cs.audio_generation_started_at IS NULL
          {platform_filter}
        ORDER BY cs.scheduled_at ASC, cs.platform_id ASC
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]

    conn = _as_sqlite_row_connection()
    try:
        from services.course_schedule_service import ensure_course_schedule_tables

        cursor = conn.cursor()
        ensure_course_schedule_tables(cursor)
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def find_next_course_folder_id(platform_id: int, folder_id: int) -> int | None:
    ph = _placeholder()
    current_query = f"SELECT position, id FROM cours_folders WHERE id = {ph} AND platform_id = {ph}"
    next_query = f"""
        SELECT id
        FROM cours_folders
        WHERE platform_id = {ph}
          AND (position > {ph} OR (position = {ph} AND id > {ph}))
        ORDER BY position ASC, id ASC
        LIMIT 1
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(current_query, (folder_id, platform_id))
                row = cur.fetchone()
                if not row:
                    return None
                cur.execute(next_query, (platform_id, row["position"], row["position"], row["id"]))
                next_row = cur.fetchone()
                return int(next_row["id"]) if next_row else None

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(current_query, (folder_id, platform_id))
        row = cursor.fetchone()
        if not row:
            return None
        position, current_id = row
        cursor.execute(next_query, (platform_id, position, position, current_id))
        next_row = cursor.fetchone()
        return int(next_row[0]) if next_row else None
    finally:
        conn.close()


def list_course_folder_ids_for_platform(platform_id: int) -> list[int]:
    ph = _placeholder()
    query = f"""
        SELECT id
        FROM cours_folders
        WHERE platform_id = {ph}
        ORDER BY position ASC, id ASC
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (platform_id,))
                return [int(row["id"]) for row in cur.fetchall()]

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, (platform_id,))
        return [int(row[0]) for row in cursor.fetchall()]
    finally:
        conn.close()


def _in_clause(values: list[Any] | tuple[Any, ...]) -> tuple[str, list[Any]]:
    items = list(values or [])
    if not items:
        return "", []
    return ", ".join([_placeholder()] * len(items)), items


def list_health_course_folder_rows(folder_ids: list[int]) -> list[dict[str, Any]]:
    placeholders, params = _in_clause([int(fid) for fid in folder_ids])
    if not placeholders:
        return []
    query = f"""
        SELECT cf.id, cf.name, cf.position,
               cj.id AS content_job_id, cj.status AS content_status
        FROM cours_folders cf
        LEFT JOIN content_generation_jobs cj ON cj.folder_id = cf.id
        WHERE cf.id IN ({placeholders})
        ORDER BY cf.position ASC
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def _count_completed_segments_for_folder_filter(folder_ids: list[int], extra_sql: str = "") -> int:
    placeholders, params = _in_clause([int(fid) for fid in folder_ids])
    if not placeholders:
        return 0
    query = f"""
        SELECT COUNT(*) AS total
        FROM content_generation_segments s
        JOIN content_generation_jobs cj ON cj.id = s.job_id
        WHERE cj.folder_id IN ({placeholders})
          AND s.status = 'completed'
          {extra_sql}
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return int(cur.fetchone()["total"] or 0)

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return int(cursor.fetchone()["total"] or 0)
    finally:
        conn.close()


def count_completed_segments_for_folders(folder_ids: list[int]) -> int:
    return _count_completed_segments_for_folder_filter(folder_ids)


def count_segments_with_pre_review_snapshot_for_folders(folder_ids: list[int]) -> int:
    return _count_completed_segments_for_folder_filter(
        folder_ids,
        "AND s.text_content_pre_review IS NOT NULL",
    )


def count_unhumanized_segments_without_error_for_folders(folder_ids: list[int]) -> int:
    if _pipeline_primary_backend() == "postgres":
        return _count_completed_segments_for_folder_filter(
            folder_ids,
            "AND COALESCE(s.humanized, FALSE) = FALSE AND s.humanization_error IS NULL",
        )
    return _count_completed_segments_for_folder_filter(
        folder_ids,
        "AND COALESCE(s.humanized, 0) = 0 AND s.humanization_error IS NULL",
    )


def count_unreviewed_segments_without_error_for_folders(folder_ids: list[int]) -> int:
    if _pipeline_primary_backend() == "postgres":
        return _count_completed_segments_for_folder_filter(
            folder_ids,
            "AND COALESCE(s.reviewed, FALSE) = FALSE AND s.review_error IS NULL",
        )
    return _count_completed_segments_for_folder_filter(
        folder_ids,
        "AND COALESCE(s.reviewed, 0) = 0 AND s.review_error IS NULL",
    )


def count_dirty_completed_segments_for_folders(folder_ids: list[int]) -> int:
    if _pipeline_primary_backend() == "postgres":
        return _count_completed_segments_for_folder_filter(folder_ids, "AND s.dirty = TRUE")
    return _count_completed_segments_for_folder_filter(folder_ids, "AND s.dirty = 1")


def list_content_completion_rows_for_folders(folder_ids: list[int]) -> list[dict[str, Any]]:
    placeholders, params = _in_clause([int(fid) for fid in folder_ids])
    if not placeholders:
        return []
    query = f"""
        SELECT
            cf.id AS folder_id,
            cgj.id AS content_job_id,
            cgj.status,
            COALESCE(cgj.total_words, 0) AS total_words,
            COALESCE(SUM(CASE WHEN cgs.status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_segments
        FROM cours_folders cf
        LEFT JOIN content_generation_jobs cgj ON cgj.folder_id = cf.id
        LEFT JOIN content_generation_segments cgs ON cgs.job_id = cgj.id
        WHERE cf.id IN ({placeholders})
        GROUP BY cf.id, cgj.id, cgj.status, cgj.total_words
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def list_completed_content_jobs_for_folders(folder_ids: list[int]) -> list[dict[str, Any]]:
    placeholders, params = _in_clause([int(fid) for fid in folder_ids])
    if not placeholders:
        return []
    query = f"""
        SELECT cf.id AS folder_id, cgj.id AS content_job_id
        FROM cours_folders cf
        JOIN content_generation_jobs cgj ON cgj.folder_id = cf.id
        WHERE cf.id IN ({placeholders}) AND cgj.status = 'completed'
        ORDER BY cf.position ASC
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def count_segments_pending_review_for_folders(folder_ids: list[int], review_signature: str) -> int:
    placeholders, params = _in_clause([int(fid) for fid in folder_ids])
    if not placeholders:
        return 0
    if _pipeline_primary_backend() == "postgres":
        reviewed_false = "COALESCE(cgs.reviewed, FALSE) = FALSE"
    else:
        reviewed_false = "COALESCE(cgs.reviewed, 0) = 0"
    query = f"""
        SELECT COUNT(*) AS total
        FROM content_generation_segments cgs
        JOIN content_generation_jobs cgj ON cgj.id = cgs.job_id
        JOIN cours_folders cf ON cf.id = cgj.folder_id
        WHERE cf.id IN ({placeholders}) AND cgs.status = 'completed'
          AND (
                {reviewed_false}
             OR cgs.review_signature IS NULL
             OR cgs.review_signature != {_placeholder()}
          )
    """
    params.append(review_signature)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return int(cur.fetchone()["total"] or 0)

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return int(cursor.fetchone()["total"] or 0)
    finally:
        conn.close()


def get_content_job_docx_state(content_job_id: int) -> dict[str, Any] | None:
    ph = _placeholder()
    query = f"""
        SELECT COUNT(*) AS completed_count, cj.sub_parts
        FROM content_generation_jobs cj
        LEFT JOIN content_generation_segments s
          ON s.job_id = cj.id AND s.status = 'completed'
        WHERE cj.id = {ph}
        GROUP BY cj.id, cj.sub_parts
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (content_job_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (content_job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_formation_module_for_pipeline_job(job_id: int) -> dict[str, Any] | None:
    ph = _placeholder()
    query = f"""
        SELECT id, version, status
        FROM formation_modules
        WHERE source_pipeline_job_id = {ph}
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


SCRIPT_ANNOTATION_COLUMNS = """
    id, folder_id, job_id, source_type, sub_part_index, passe,
    bloc_number, filename, selected_text, comment, status,
    markdown_path, created_at, updated_at,
    original_paragraph, proposed_text, correction_status,
    correction_error, applied_at,
    splice_status, splice_error, splice_blob_path
"""


def ensure_script_annotations_table() -> None:
    """Ensure SQLite has script annotation storage. Postgres schema owns this."""
    if _pipeline_primary_backend() == "postgres":
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS content_script_annotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_id INTEGER NOT NULL,
                job_id INTEGER NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'course',
                sub_part_index INTEGER,
                passe INTEGER,
                bloc_number INTEGER,
                filename TEXT,
                selected_text TEXT NOT NULL,
                comment TEXT NOT NULL,
                status TEXT DEFAULT 'open',
                markdown_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (folder_id) REFERENCES cours_folders(id),
                FOREIGN KEY (job_id) REFERENCES content_generation_jobs(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_content_script_annotations_folder_job
            ON content_script_annotations(folder_id, job_id, status)
            """
        )
        for ddl in (
            "ALTER TABLE content_script_annotations ADD COLUMN original_paragraph TEXT",
            "ALTER TABLE content_script_annotations ADD COLUMN proposed_text TEXT",
            "ALTER TABLE content_script_annotations ADD COLUMN correction_status TEXT DEFAULT 'pending'",
            "ALTER TABLE content_script_annotations ADD COLUMN correction_error TEXT",
            "ALTER TABLE content_script_annotations ADD COLUMN applied_at TIMESTAMP",
            "ALTER TABLE content_script_annotations ADD COLUMN splice_status TEXT",
            "ALTER TABLE content_script_annotations ADD COLUMN splice_error TEXT",
            "ALTER TABLE content_script_annotations ADD COLUMN splice_blob_path TEXT",
        ):
            try:
                cursor.execute(ddl)
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()


def get_script_annotation_context(folder_id: int) -> dict[str, Any] | None:
    ph = _placeholder()
    query = f"""
        SELECT j.id AS job_id, j.platform_id, j.program_title,
               f.name AS folder_name, pc.name AS platform_name
        FROM content_generation_jobs j
        JOIN cours_folders f ON f.id = j.folder_id
        LEFT JOIN platform_config pc ON pc.id = j.platform_id
        WHERE j.folder_id = {ph}
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (folder_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (folder_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_script_annotation_rows(
    *,
    folder_id: int,
    job_id: int,
    include_deleted: bool = False,
) -> list[dict[str, Any]]:
    ph = _placeholder()
    where_deleted = "" if include_deleted else "AND status != 'deleted'"
    query = f"""
        SELECT {SCRIPT_ANNOTATION_COLUMNS}
        FROM content_script_annotations
        WHERE folder_id = {ph} AND job_id = {ph} {where_deleted}
        ORDER BY created_at ASC, id ASC
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (folder_id, job_id))
                return [dict(row) for row in cur.fetchall()]

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (folder_id, job_id))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def update_script_annotations_markdown_path(*, folder_id: int, job_id: int, markdown_path: str) -> None:
    ph = _placeholder()
    now_sql = "NOW()" if _pipeline_primary_backend() == "postgres" else "CURRENT_TIMESTAMP"
    query = f"""
        UPDATE content_script_annotations
        SET markdown_path = {ph}, updated_at = {now_sql}
        WHERE folder_id = {ph} AND job_id = {ph} AND status != 'deleted'
    """
    params = (markdown_path, folder_id, job_id)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def create_script_annotation_row(
    *,
    folder_id: int,
    job_id: int,
    source_type: str,
    sub_part_index,
    passe,
    bloc_number,
    filename: str,
    selected_text: str,
    comment: str,
    original_paragraph: str,
) -> int:
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO content_script_annotations
                        (folder_id, job_id, source_type, sub_part_index, passe, bloc_number,
                         filename, selected_text, comment, status, original_paragraph,
                         correction_status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'open', %s, 'pending', NOW(), NOW())
                    RETURNING id
                    """,
                    (
                        folder_id,
                        job_id,
                        source_type,
                        sub_part_index,
                        passe,
                        bloc_number,
                        filename,
                        selected_text,
                        comment,
                        original_paragraph,
                    ),
                )
                return int(cur.fetchone()["id"])

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO content_script_annotations
                (folder_id, job_id, source_type, sub_part_index, passe, bloc_number,
                 filename, selected_text, comment, status, original_paragraph,
                 correction_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                folder_id,
                job_id,
                source_type,
                sub_part_index,
                passe,
                bloc_number,
                filename,
                selected_text,
                comment,
                original_paragraph,
            ),
        )
        annotation_id = int(cursor.lastrowid)
        conn.commit()
        return annotation_id
    finally:
        conn.close()


def mark_script_annotation_deleted(*, annotation_id: int, folder_id: int, job_id: int) -> int:
    ph = _placeholder()
    now_sql = "NOW()" if _pipeline_primary_backend() == "postgres" else "CURRENT_TIMESTAMP"
    query = f"""
        UPDATE content_script_annotations
        SET status = 'deleted', updated_at = {now_sql}
        WHERE id = {ph} AND folder_id = {ph} AND job_id = {ph}
    """
    params = (annotation_id, folder_id, job_id)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return int(cur.rowcount or 0)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        changed = int(cursor.rowcount or 0)
        conn.commit()
        return changed
    finally:
        conn.close()


def update_script_annotation_correction(
    *,
    annotation_id: int,
    folder_id: int,
    job_id: int,
    original_paragraph: str,
    proposed_text: str,
    correction_status: str,
    correction_error: str | None,
) -> None:
    ph = _placeholder()
    now_sql = "NOW()" if _pipeline_primary_backend() == "postgres" else "CURRENT_TIMESTAMP"
    query = f"""
        UPDATE content_script_annotations
        SET original_paragraph = {ph}, proposed_text = {ph}, correction_status = {ph},
            correction_error = {ph}, updated_at = {now_sql}
        WHERE id = {ph} AND folder_id = {ph} AND job_id = {ph}
    """
    params = (
        original_paragraph,
        proposed_text,
        correction_status,
        correction_error,
        annotation_id,
        folder_id,
        job_id,
    )
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def get_script_annotation_for_apply(
    *,
    annotation_id: int,
    folder_id: int,
    job_id: int,
) -> dict[str, Any] | None:
    ph = _placeholder()
    query = f"""
        SELECT source_type, sub_part_index, passe, selected_text,
               proposed_text, original_paragraph, correction_status,
               bloc_number, filename
        FROM content_script_annotations
        WHERE id = {ph} AND folder_id = {ph} AND job_id = {ph} AND status != 'deleted'
    """
    params = (annotation_id, folder_id, job_id)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                return dict(row) if row else None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_content_segment_row_for_key(
    *,
    job_id: int,
    sub_part_index: int,
    passe: int,
) -> dict[str, Any] | None:
    ph = _placeholder()
    query = f"""
        SELECT id, text_content
        FROM content_generation_segments
        WHERE job_id = {ph} AND sub_part_index = {ph} AND passe = {ph}
    """
    params = (job_id, sub_part_index, passe)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                return dict(row) if row else None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_content_segment_text_by_id(segment_id: int) -> str:
    ph = _placeholder()
    query = f"SELECT text_content FROM content_generation_segments WHERE id = {ph}"
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (segment_id,))
                row = cur.fetchone()
                return (row["text_content"] or "") if row else ""

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, (segment_id,))
        row = cursor.fetchone()
        return (row[0] or "") if row else ""
    finally:
        conn.close()


def mark_script_annotation_applied(annotation_id: int) -> None:
    ph = _placeholder()
    now_sql = "NOW()" if _pipeline_primary_backend() == "postgres" else "CURRENT_TIMESTAMP"
    query = f"""
        UPDATE content_script_annotations
        SET correction_status = 'applied', applied_at = {now_sql},
            updated_at = {now_sql}
        WHERE id = {ph}
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (annotation_id,))
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, (annotation_id,))
        conn.commit()
    finally:
        conn.close()


def update_script_annotation_splice_result(
    *,
    annotation_id: int,
    splice_status: str,
    splice_error: str | None,
    splice_blob_path: str | None,
) -> None:
    ph = _placeholder()
    now_sql = "NOW()" if _pipeline_primary_backend() == "postgres" else "CURRENT_TIMESTAMP"
    query = f"""
        UPDATE content_script_annotations
        SET splice_status = {ph}, splice_error = {ph}, splice_blob_path = {ph},
            updated_at = {now_sql}
        WHERE id = {ph}
    """
    params = (splice_status, splice_error, splice_blob_path, annotation_id)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def mark_script_annotation_rejected(*, annotation_id: int, folder_id: int, job_id: int) -> int:
    ph = _placeholder()
    now_sql = "NOW()" if _pipeline_primary_backend() == "postgres" else "CURRENT_TIMESTAMP"
    query = f"""
        UPDATE content_script_annotations
        SET correction_status = 'rejected', updated_at = {now_sql}
        WHERE id = {ph} AND folder_id = {ph} AND job_id = {ph} AND status != 'deleted'
    """
    params = (annotation_id, folder_id, job_id)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return int(cur.rowcount or 0)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        changed = int(cursor.rowcount or 0)
        conn.commit()
        return changed
    finally:
        conn.close()


def ensure_script_rules_table() -> None:
    """Ensure SQLite has script rules storage. Postgres schema owns this."""
    if _pipeline_primary_backend() == "postgres":
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS content_script_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_id INTEGER NOT NULL,
                job_id INTEGER NOT NULL,
                rules_markdown TEXT NOT NULL DEFAULT '',
                rules_count INTEGER DEFAULT 0,
                source_annotations_count INTEGER DEFAULT 0,
                model TEXT,
                markdown_path TEXT,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(folder_id, job_id)
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_content_script_rules_folder_job
            ON content_script_rules(folder_id, job_id)
            """
        )
        conn.commit()
    finally:
        conn.close()


def get_script_rules_context(folder_id: int) -> dict[str, Any] | None:
    ph = _placeholder()
    query = f"""
        SELECT j.id AS job_id, j.platform_id, j.program_title, f.name AS folder_name
        FROM content_generation_jobs j
        JOIN cours_folders f ON f.id = j.folder_id
        WHERE j.folder_id = {ph}
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (folder_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (folder_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_script_rule_annotation_rows(*, folder_id: int, job_id: int) -> list[dict[str, Any]]:
    ensure_script_annotations_table()
    ph = _placeholder()
    query = f"""
        SELECT id, source_type, selected_text, comment, original_paragraph,
               proposed_text, correction_status, bloc_number, filename
        FROM content_script_annotations
        WHERE folder_id = {ph} AND job_id = {ph}
          AND status != 'deleted'
          AND correction_status IN ('applied', 'rejected', 'proposed')
        ORDER BY created_at ASC, id ASC
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (folder_id, job_id))
                return [dict(row) for row in cur.fetchall()]

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (folder_id, job_id))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def upsert_generated_script_rules(
    *,
    folder_id: int,
    job_id: int,
    rules_markdown: str,
    rules_count: int,
    source_annotations_count: int,
    model: str,
    markdown_path: str,
) -> None:
    ensure_script_rules_table()
    ph = _placeholder()
    query = f"""
        INSERT INTO content_script_rules
            (folder_id, job_id, rules_markdown, rules_count, source_annotations_count,
             model, markdown_path, generated_at, updated_at)
        VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(folder_id, job_id) DO UPDATE SET
            rules_markdown = excluded.rules_markdown,
            rules_count = excluded.rules_count,
            source_annotations_count = excluded.source_annotations_count,
            model = excluded.model,
            markdown_path = excluded.markdown_path,
            generated_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
    """
    params = (
        folder_id,
        job_id,
        rules_markdown,
        rules_count,
        source_annotations_count,
        model,
        markdown_path,
    )
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def upsert_manual_script_rules(
    *,
    folder_id: int,
    job_id: int,
    rules_markdown: str,
    rules_count: int,
    markdown_path: str,
) -> None:
    ensure_script_rules_table()
    ph = _placeholder()
    query = f"""
        INSERT INTO content_script_rules
            (folder_id, job_id, rules_markdown, rules_count, source_annotations_count,
             model, markdown_path, generated_at, updated_at)
        VALUES ({ph}, {ph}, {ph}, {ph}, 0, 'manual', {ph}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(folder_id, job_id) DO UPDATE SET
            rules_markdown = excluded.rules_markdown,
            rules_count = excluded.rules_count,
            markdown_path = excluded.markdown_path,
            updated_at = CURRENT_TIMESTAMP
    """
    params = (folder_id, job_id, rules_markdown, rules_count, markdown_path)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def get_script_rules_row(*, folder_id: int, job_id: int) -> dict[str, Any] | None:
    ensure_script_rules_table()
    ph = _placeholder()
    query = f"""
        SELECT rules_markdown, rules_count, source_annotations_count,
               model, markdown_path, generated_at, updated_at
        FROM content_script_rules
        WHERE folder_id = {ph} AND job_id = {ph}
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (folder_id, job_id))
                row = cur.fetchone()
                return dict(row) if row else None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (folder_id, job_id))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


SCRIPT_SLIDE_DECK_COLUMNS = """
    id, folder_id, content_job_id, formation_job_id, platform_id, pace,
    max_slides, model, slides_json, timeline_json, stats_json,
    pipeline_debug_json, audio_sync_json, created_at, updated_at
"""


def ensure_script_slide_decks_table() -> None:
    """Ensure SQLite has script slide deck storage. Postgres schema owns this."""
    if _pipeline_primary_backend() == "postgres":
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS script_slide_decks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_id INTEGER NOT NULL,
                content_job_id INTEGER NOT NULL,
                formation_job_id INTEGER,
                platform_id INTEGER,
                generation_mode TEXT DEFAULT 'script',
                pace TEXT,
                max_slides INTEGER,
                model TEXT,
                slides_json TEXT NOT NULL,
                timeline_json TEXT,
                stats_json TEXT,
                pipeline_debug_json TEXT,
                audio_sync_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_script_slide_decks_folder
            ON script_slide_decks(folder_id, content_job_id, created_at)
            """
        )
        conn.commit()
    finally:
        conn.close()


def insert_script_slide_deck(
    *,
    folder_id: int,
    content_job_id: int,
    formation_job_id: int | None,
    platform_id: int | None,
    generation_mode: str,
    pace: str,
    max_slides: int,
    model: str,
    slides_json: str,
    timeline_json: str,
    stats_json: str,
    pipeline_debug_json: str,
) -> int:
    ensure_script_slide_decks_table()
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO script_slide_decks
                    (folder_id, content_job_id, formation_job_id, platform_id, generation_mode,
                     pace, max_slides, model, slides_json, timeline_json, stats_json,
                     pipeline_debug_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        folder_id,
                        content_job_id,
                        formation_job_id,
                        platform_id,
                        generation_mode,
                        pace,
                        max_slides,
                        model,
                        slides_json,
                        timeline_json,
                        stats_json,
                        pipeline_debug_json,
                    ),
                )
                return int(cur.fetchone()["id"])

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO script_slide_decks
            (folder_id, content_job_id, formation_job_id, platform_id, generation_mode,
             pace, max_slides, model, slides_json, timeline_json, stats_json,
             pipeline_debug_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                folder_id,
                content_job_id,
                formation_job_id,
                platform_id,
                generation_mode,
                pace,
                max_slides,
                model,
                slides_json,
                timeline_json,
                stats_json,
                pipeline_debug_json,
            ),
        )
        deck_id = int(cursor.lastrowid)
        conn.commit()
        return deck_id
    finally:
        conn.close()


def get_latest_script_slide_deck_row(
    *,
    folder_id: int,
    content_job_id: int | None = None,
) -> dict[str, Any] | None:
    ensure_script_slide_decks_table()
    ph = _placeholder()
    params: list[Any] = [folder_id]
    where = f"folder_id = {ph}"
    if content_job_id is not None:
        where += f" AND content_job_id = {ph}"
        params.append(content_job_id)
    query = f"""
        SELECT {SCRIPT_SLIDE_DECK_COLUMNS}
        FROM script_slide_decks
        WHERE {where}
        ORDER BY id DESC
        LIMIT 1
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                return dict(row) if row else None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_script_slide_deck_row(deck_id: int) -> dict[str, Any] | None:
    ensure_script_slide_decks_table()
    ph = _placeholder()
    query = f"""
        SELECT {SCRIPT_SLIDE_DECK_COLUMNS}
        FROM script_slide_decks
        WHERE id = {ph}
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (deck_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (deck_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_script_slide_deck_rows_for_audio_lookup(
    *,
    platform_ids: list[int] | None = None,
    job_ids: list[int] | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    ensure_script_slide_decks_table()
    where_parts: list[str] = []
    params: list[Any] = []
    platform_placeholders, platform_params = _in_clause([int(pid) for pid in (platform_ids or [])])
    if platform_placeholders:
        where_parts.append(f"platform_id IN ({platform_placeholders})")
        params.extend(platform_params)
    job_placeholders, job_params = _in_clause([int(jid) for jid in (job_ids or [])])
    if job_placeholders:
        where_parts.append(
            f"(formation_job_id IN ({job_placeholders}) OR content_job_id IN ({job_placeholders}))"
        )
        params.extend(job_params)
        params.extend(job_params)
    where_sql = f"WHERE {' OR '.join(where_parts)}" if where_parts else ""
    ph = _placeholder()
    query = f"""
        SELECT {SCRIPT_SLIDE_DECK_COLUMNS}
        FROM script_slide_decks
        {where_sql}
        ORDER BY id DESC
        LIMIT {ph}
    """
    params.append(limit)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def update_script_slide_deck_audio_sync_row(
    *,
    deck_id: int,
    slides_json: str,
    timeline_json: str,
    stats_json: str,
    pipeline_debug_json: str,
    audio_sync_json: str,
) -> None:
    ph = _placeholder()
    now_sql = "NOW()" if _pipeline_primary_backend() == "postgres" else "CURRENT_TIMESTAMP"
    query = f"""
        UPDATE script_slide_decks
        SET slides_json = {ph}, timeline_json = {ph}, stats_json = {ph},
            pipeline_debug_json = {ph}, audio_sync_json = {ph},
            updated_at = {now_sql}
        WHERE id = {ph}
    """
    params = (slides_json, timeline_json, stats_json, pipeline_debug_json, audio_sync_json, deck_id)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def get_script_slide_source_row(folder_id: int) -> dict[str, Any] | None:
    ph = _placeholder()
    query = f"""
        SELECT cf.id AS folder_id, cf.name AS folder_name, cf.platform_id AS folder_platform_id,
               cg.id AS content_job_id, cg.program_title, cg.sub_parts,
               cg.status AS content_status, cg.total_words
        FROM cours_folders cf
        JOIN content_generation_jobs cg ON cg.folder_id = cf.id
        WHERE cf.id = {ph}
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (folder_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (folder_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_formation_pipeline_job_identity(job_id: int) -> dict[str, Any] | None:
    ph = _placeholder()
    query = f"""
        SELECT id, tp_name, platform_id
        FROM formation_pipeline_jobs
        WHERE id = {ph}
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_platform_slide_source_refs(platform_id: int) -> dict[str, Any] | None:
    ph = _placeholder()
    query = f"""
        SELECT pc.source_formation_id,
               pc.source_module_id,
               fm.source_pipeline_job_id,
               fm.source_platform_id
        FROM platform_config pc
        LEFT JOIN formation_modules fm ON fm.id = pc.source_module_id
        WHERE pc.id = {ph}
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (platform_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (platform_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def ensure_content_generation_carryover_columns() -> None:
    """Ensure SQLite has cross-day carryover columns. Postgres schema owns this."""
    if _pipeline_primary_backend() == "postgres":
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA table_info(content_generation_jobs)")
        cols = {row[1] for row in cursor.fetchall()}
        wanted = {
            "carryover_in_text": "TEXT DEFAULT ''",
            "carryover_in_source_folder_id": "INTEGER",
            "carryover_out_text": "TEXT DEFAULT ''",
            "carryover_out_target_folder_id": "INTEGER",
        }
        for col, col_type in wanted.items():
            if col not in cols:
                cursor.execute(f"ALTER TABLE content_generation_jobs ADD COLUMN {col} {col_type}")
        conn.commit()
    finally:
        conn.close()


def store_cross_day_carryover(
    *,
    source_folder_id: int,
    target_folder_id: int,
    carryover_out_text: str,
    carryover_in_text: str,
) -> None:
    ph = _placeholder()
    now_sql = "NOW()" if _pipeline_primary_backend() == "postgres" else "CURRENT_TIMESTAMP"
    clean = (carryover_out_text or "").strip()
    source_target = target_folder_id if clean else None
    source_query = f"""
        UPDATE content_generation_jobs
        SET carryover_out_text = {ph}, carryover_out_target_folder_id = {ph},
            updated_at = {now_sql}
        WHERE folder_id = {ph}
    """
    target_query = f"""
        UPDATE content_generation_jobs
        SET carryover_in_text = {ph}, carryover_in_source_folder_id = {ph},
            updated_at = {now_sql}
        WHERE folder_id = {ph}
    """
    dirty_query = f"""
        UPDATE content_generation_segments
        SET dirty = {ph}
        WHERE job_id = (SELECT id FROM content_generation_jobs WHERE folder_id = {ph})
          AND sub_part_index = 0 AND passe = 1
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(source_query, (clean, source_target, source_folder_id))
                cur.execute(
                    target_query,
                    (carryover_in_text if clean else "", source_folder_id if clean else None, target_folder_id),
                )
                cur.execute(dirty_query, (True, target_folder_id))
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(source_query, (clean, source_target, source_folder_id))
        cursor.execute(
            target_query,
            (carryover_in_text if clean else "", source_folder_id if clean else None, target_folder_id),
        )
        cursor.execute(dirty_query, (1, target_folder_id))
        conn.commit()
    finally:
        conn.close()


def clear_cross_day_carryover(
    *,
    source_folder_id: int,
    target_folder_id: int | None = None,
) -> None:
    ph = _placeholder()
    now_sql = "NOW()" if _pipeline_primary_backend() == "postgres" else "CURRENT_TIMESTAMP"
    source_query = f"""
        UPDATE content_generation_jobs
        SET carryover_out_text = '', carryover_out_target_folder_id = NULL,
            updated_at = {now_sql}
        WHERE folder_id = {ph}
    """
    target_query = f"""
        UPDATE content_generation_jobs
        SET carryover_in_text = '', carryover_in_source_folder_id = NULL,
            updated_at = {now_sql}
        WHERE folder_id = {ph} AND carryover_in_source_folder_id = {ph}
    """
    select_targets_query = f"""
        SELECT folder_id
        FROM content_generation_jobs
        WHERE carryover_in_source_folder_id = {ph}
    """
    clear_all_targets_query = f"""
        UPDATE content_generation_jobs
        SET carryover_in_text = '', carryover_in_source_folder_id = NULL,
            updated_at = {now_sql}
        WHERE carryover_in_source_folder_id = {ph}
    """
    dirty_query = f"""
        UPDATE content_generation_segments
        SET dirty = {ph}
        WHERE job_id = (SELECT id FROM content_generation_jobs WHERE folder_id = {ph})
          AND sub_part_index = 0 AND passe = 1
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(source_query, (source_folder_id,))
                if target_folder_id:
                    cur.execute(target_query, (target_folder_id, source_folder_id))
                    cur.execute(dirty_query, (True, target_folder_id))
                else:
                    cur.execute(select_targets_query, (source_folder_id,))
                    target_rows = [int(row["folder_id"]) for row in cur.fetchall()]
                    cur.execute(clear_all_targets_query, (source_folder_id,))
                    for target_id in target_rows:
                        cur.execute(dirty_query, (True, target_id))
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(source_query, (source_folder_id,))
        if target_folder_id:
            cursor.execute(target_query, (target_folder_id, source_folder_id))
            cursor.execute(dirty_query, (1, target_folder_id))
        else:
            cursor.execute(select_targets_query, (source_folder_id,))
            target_rows = [int(row[0]) for row in cursor.fetchall()]
            cursor.execute(clear_all_targets_query, (source_folder_id,))
            for target_id in target_rows:
                cursor.execute(dirty_query, (1, target_id))
        conn.commit()
    finally:
        conn.close()


def get_existing_carryover_out_row(source_folder_id: int) -> dict[str, Any] | None:
    ph = _placeholder()
    query = f"""
        SELECT carryover_out_text, carryover_out_target_folder_id
        FROM content_generation_jobs
        WHERE folder_id = {ph}
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (source_folder_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (source_folder_id,))
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
        fields = _normalize_job_update_fields(fields)
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


def acquire_auto_pilot_lock(job_id: int, *, owner: str, ttl_seconds: int) -> bool:
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE formation_pipeline_jobs
                    SET auto_pilot_locked_at = NOW(),
                        auto_pilot_lock_owner = %s
                    WHERE id = %s
                      AND auto_pilot_enabled = TRUE
                      AND (
                            auto_pilot_locked_at IS NULL
                            OR auto_pilot_locked_at < NOW() - (%s * INTERVAL '1 second')
                          )
                    """,
                    (owner, job_id, ttl_seconds),
                )
                return cur.rowcount == 1

    stale_cutoff = int(time.time()) - ttl_seconds
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE formation_pipeline_jobs
            SET auto_pilot_locked_at = CURRENT_TIMESTAMP,
                auto_pilot_lock_owner = ?
            WHERE id = ?
              AND auto_pilot_enabled = 1
              AND (auto_pilot_locked_at IS NULL
                   OR CAST(strftime('%s', auto_pilot_locked_at) AS INTEGER) < ?)
            """,
            (owner, job_id, stale_cutoff),
        )
        acquired = cursor.rowcount == 1
        conn.commit()
        return acquired
    finally:
        conn.close()


def release_auto_pilot_lock(job_id: int) -> None:
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE formation_pipeline_jobs
                    SET auto_pilot_locked_at = NULL,
                        auto_pilot_lock_owner = NULL
                    WHERE id = %s
                    """,
                    (job_id,),
                )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE formation_pipeline_jobs
            SET auto_pilot_locked_at = NULL, auto_pilot_lock_owner = NULL
            WHERE id = ?
            """,
            (job_id,),
        )
        conn.commit()
    finally:
        conn.close()


def refresh_auto_pilot_lock(job_id: int, *, owner: str) -> None:
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE formation_pipeline_jobs
                    SET auto_pilot_locked_at = NOW()
                    WHERE id = %s AND auto_pilot_lock_owner = %s
                    """,
                    (job_id, owner),
                )
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE formation_pipeline_jobs
            SET auto_pilot_locked_at = CURRENT_TIMESTAMP
            WHERE id = ? AND auto_pilot_lock_owner = ?
            """,
            (job_id, owner),
        )
        conn.commit()
    finally:
        conn.close()


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
