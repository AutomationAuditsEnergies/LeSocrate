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


def _placeholder() -> str:
    return "%s" if _pipeline_primary_backend() == "postgres" else "?"


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
    query = f"""
        SELECT sub_part_index, sub_part_name, passe, text_content, word_count, dirty,
               COALESCE(humanized, 0) AS humanized, COALESCE(reviewed, 0) AS reviewed,
               humanization_error, review_error
        FROM content_generation_segments
        WHERE job_id = {ph} AND status = 'completed'
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
