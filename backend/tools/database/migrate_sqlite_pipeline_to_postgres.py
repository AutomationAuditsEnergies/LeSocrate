#!/usr/bin/env python3
"""Copy pipeline tables from the current SQLite DB to Postgres/Supabase.

Run the core migration first so referenced centres/platforms already exist:

  DATABASE_URL='postgresql://...' \
  python backend/tools/database/migrate_sqlite_core_to_postgres.py --apply-schema

Then run this script:

  DATABASE_URL='postgresql://...' \
  python backend/tools/database/migrate_sqlite_pipeline_to_postgres.py --apply-schema
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import DB_PATH  # noqa: E402
from tools.database.migration_utils import (  # noqa: E402
    MigrationValidationError,
    normalize_sqlite_row,
    timezone_from_name,
)


PIPELINE_TABLES = [
    "formation_pipeline_jobs",
    "formation_modules",
    "day_schedule_templates",
    "day_schedule_template_blocks",
    "formation_module_days",
    "formation_knowledge_base",
    "cours_folders",
    "formation_module_assets",
    "cours_documents",
    "content_generation_jobs",
    "content_generation_segments",
    "content_script_annotations",
    "content_script_rules",
    "content_review_reports",
    "formation_pipeline_events",
    "script_slide_decks",
]

BOOL_COLUMNS = {
    "formation_pipeline_jobs": {
        "global_program_validated",
        "daily_programs_validated",
        "auto_pilot_enabled",
        "auto_pilot_post_review_docs_done",
    },
    "formation_knowledge_base": {"dirty"},
    "content_generation_jobs": {"from_scratch"},
    "content_generation_segments": {"dirty", "reviewed"},
    "formation_modules": {"immutable", "canonical_reuse_allowed"},
    "formation_module_days": {"immutable"},
    "formation_module_assets": {"immutable"},
}

JSON_COLUMNS = {
    "formation_pipeline_jobs": {"daily_programs", "schedule_snapshot_json"},
    "formation_knowledge_base": {
        "etudes_de_cas",
        "pieges_frequents",
        "vocabulaire_metier",
        "liens_connexes",
    },
    "formation_modules": {"canonical_signature_json"},
    "day_schedule_templates": {"blocks_snapshot_json"},
    "day_schedule_template_blocks": {"metadata_json"},
    "formation_module_days": {"blocks_snapshot_json"},
    "formation_module_assets": {"generation_params_json"},
    "content_generation_jobs": {
        "sub_parts",
        "module_contents",
        "structured_plan_json",
    },
    "content_generation_segments": {"structured_checkpoint_json"},
    "content_review_reports": {"summary_json", "report_json"},
    "formation_pipeline_events": {"data_json"},
    "script_slide_decks": {
        "slides_json",
        "timeline_json",
        "stats_json",
        "pipeline_debug_json",
        "audio_sync_json",
    },
}

# psycopg must receive a JSON adapter for actual JSONB target columns.  The
# generic JSON normalization above still validates and canonicalizes text-only
# JSON columns used by the historical pipeline.
JSONB_COLUMNS = {
    "formation_pipeline_jobs": {"schedule_snapshot_json"},
    "formation_modules": {"canonical_signature_json"},
    "day_schedule_templates": {"blocks_snapshot_json"},
    "day_schedule_template_blocks": {"metadata_json"},
    "formation_module_days": {"blocks_snapshot_json"},
    "formation_module_assets": {"generation_params_json"},
    "content_generation_jobs": {"structured_plan_json"},
    "content_generation_segments": {"structured_checkpoint_json"},
}

TIMESTAMP_COLUMNS = {
    "formation_pipeline_jobs": {
        "auto_pilot_locked_at",
        "schedule_locked_at",
        "created_at",
        "updated_at",
    },
    "formation_knowledge_base": {"created_at", "updated_at"},
    "cours_folders": {"created_at"},
    "day_schedule_templates": {
        "used_at",
        "locked_at",
        "deleted_at",
        "created_at",
        "updated_at",
    },
    "day_schedule_template_blocks": {"created_at"},
    "formation_module_days": {"locked_at", "created_at"},
    "formation_module_assets": {
        "last_verified_at",
        "created_at",
        "updated_at",
    },
    "cours_documents": {"created_at"},
    "content_generation_jobs": {"created_at", "updated_at"},
    "content_generation_segments": {"created_at"},
    "content_script_annotations": {"applied_at", "created_at", "updated_at"},
    "content_script_rules": {"generated_at", "updated_at"},
    "content_review_reports": {"created_at"},
    "formation_pipeline_events": {"created_at"},
    "formation_modules": {
        "voice_updated_at",
        "schedule_locked_at",
        "reusable_at",
        "created_at",
        "validated_at",
        "archived_at",
    },
    "script_slide_decks": {"created_at", "updated_at"},
}

SOURCE_INTEGRITY_CHECKS = (
    (
        "formation_pipeline_jobs.platform_id sans plateforme",
        {"formation_pipeline_jobs", "platform_config"},
        """
        SELECT COUNT(*) FROM formation_pipeline_jobs c
        LEFT JOIN platform_config p ON p.id = c.platform_id
        WHERE p.id IS NULL
        """,
    ),
    (
        "formation_knowledge_base.job_id sans job",
        {"formation_knowledge_base", "formation_pipeline_jobs"},
        """
        SELECT COUNT(*) FROM formation_knowledge_base c
        LEFT JOIN formation_pipeline_jobs p ON p.id = c.job_id
        WHERE p.id IS NULL
        """,
    ),
    (
        "cours_folders sans plateforme/job cohérent",
        {"cours_folders", "platform_config", "formation_pipeline_jobs"},
        """
        SELECT COUNT(*) FROM cours_folders c
        LEFT JOIN platform_config p ON p.id = c.platform_id
        LEFT JOIN formation_pipeline_jobs j ON j.id = c.formation_job_id
        WHERE p.id IS NULL
           OR (c.formation_job_id IS NOT NULL AND j.id IS NULL)
           OR (j.id IS NOT NULL AND j.platform_id != c.platform_id)
        """,
    ),
    (
        "cours_folders (formation_job_id, name) dupliqué",
        {"cours_folders"},
        """
        SELECT COALESCE(SUM(duplicate_count - 1), 0)
        FROM (
            SELECT COUNT(*) AS duplicate_count
            FROM cours_folders
            WHERE formation_job_id IS NOT NULL
            GROUP BY formation_job_id, name
            HAVING COUNT(*) > 1
        ) duplicates
        """,
    ),
    (
        "cours_documents.folder_id sans dossier",
        {"cours_documents", "cours_folders"},
        """
        SELECT COUNT(*) FROM cours_documents c
        LEFT JOIN cours_folders p ON p.id = c.folder_id
        WHERE p.id IS NULL
        """,
    ),
    (
        "content_generation_jobs sans dossier/plateforme cohérent",
        {"content_generation_jobs", "cours_folders", "platform_config"},
        """
        SELECT COUNT(*) FROM content_generation_jobs c
        LEFT JOIN cours_folders f ON f.id = c.folder_id
        LEFT JOIN platform_config p ON p.id = c.platform_id
        WHERE f.id IS NULL OR p.id IS NULL
           OR (f.id IS NOT NULL AND f.platform_id != c.platform_id)
        """,
    ),
    (
        "content_generation_segments.job_id sans job contenu",
        {"content_generation_segments", "content_generation_jobs"},
        """
        SELECT COUNT(*) FROM content_generation_segments c
        LEFT JOIN content_generation_jobs p ON p.id = c.job_id
        WHERE p.id IS NULL
        """,
    ),
    (
        "content_script_annotations sans dossier/job cohérent",
        {"content_script_annotations", "cours_folders", "content_generation_jobs"},
        """
        SELECT COUNT(*) FROM content_script_annotations c
        LEFT JOIN cours_folders f ON f.id = c.folder_id
        LEFT JOIN content_generation_jobs j ON j.id = c.job_id
        WHERE f.id IS NULL OR j.id IS NULL OR j.folder_id != c.folder_id
        """,
    ),
    (
        "content_script_rules sans dossier/job cohérent",
        {"content_script_rules", "cours_folders", "content_generation_jobs"},
        """
        SELECT COUNT(*) FROM content_script_rules c
        LEFT JOIN cours_folders f ON f.id = c.folder_id
        LEFT JOIN content_generation_jobs j ON j.id = c.job_id
        WHERE f.id IS NULL OR j.id IS NULL OR j.folder_id != c.folder_id
        """,
    ),
    (
        "content_review_reports sans job/dossier cohérent",
        {"content_review_reports", "formation_pipeline_jobs", "cours_folders"},
        """
        SELECT COUNT(*) FROM content_review_reports c
        LEFT JOIN formation_pipeline_jobs j ON j.id = c.job_id
        LEFT JOIN cours_folders f ON f.id = c.folder_id
        WHERE j.id IS NULL OR f.id IS NULL
           OR (f.formation_job_id IS NOT NULL AND f.formation_job_id != c.job_id)
        """,
    ),
    (
        "formation_pipeline_events sans job/dossier cohérent",
        {"formation_pipeline_events", "formation_pipeline_jobs", "cours_folders"},
        """
        SELECT COUNT(*) FROM formation_pipeline_events c
        LEFT JOIN formation_pipeline_jobs j ON j.id = c.job_id
        LEFT JOIN cours_folders f ON f.id = c.folder_id
        WHERE j.id IS NULL
           OR (c.folder_id IS NOT NULL AND f.id IS NULL)
           OR (f.formation_job_id IS NOT NULL AND f.formation_job_id != c.job_id)
        """,
    ),
    (
        "formation_modules sans source/centre cohérent",
        {"formation_modules", "formation_pipeline_jobs", "platform_config", "training_center_accounts"},
        """
        SELECT COUNT(*) FROM formation_modules c
        LEFT JOIN formation_pipeline_jobs j ON j.id = c.source_pipeline_job_id
        LEFT JOIN platform_config p ON p.id = c.source_platform_id
        LEFT JOIN training_center_accounts a ON a.id = c.center_account_id
        WHERE (c.source_pipeline_job_id IS NOT NULL AND j.id IS NULL)
           OR (c.source_platform_id IS NOT NULL AND p.id IS NULL)
           OR (c.center_account_id IS NOT NULL AND a.id IS NULL)
        """,
    ),
    (
        "script_slide_decks sans références cohérentes",
        {"script_slide_decks", "cours_folders", "content_generation_jobs", "formation_pipeline_jobs", "platform_config"},
        """
        SELECT COUNT(*) FROM script_slide_decks c
        LEFT JOIN cours_folders f ON f.id = c.folder_id
        LEFT JOIN content_generation_jobs g ON g.id = c.content_job_id
        LEFT JOIN formation_pipeline_jobs j ON j.id = c.formation_job_id
        LEFT JOIN platform_config p ON p.id = c.platform_id
        WHERE f.id IS NULL OR g.id IS NULL OR g.folder_id != c.folder_id
           OR (c.formation_job_id IS NOT NULL AND j.id IS NULL)
           OR (c.platform_id IS NOT NULL AND p.id IS NULL)
           OR (c.platform_id IS NOT NULL AND f.platform_id != c.platform_id)
        """,
    ),
)


def sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [row[1] for row in rows]


def validate_source_integrity(conn: sqlite3.Connection) -> None:
    existing_tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    violations = []
    for label, required_tables, query in SOURCE_INTEGRITY_CHECKS:
        if not required_tables.issubset(existing_tables):
            continue
        try:
            count = int(conn.execute(query).fetchone()[0])
        except sqlite3.OperationalError as exc:
            if "no such column" in str(exc).lower():
                continue
            raise
        if count:
            violations.append(f"{label}: {count} ligne(s)")
    if violations:
        raise MigrationValidationError(
            "Intégrité SQLite incompatible avec les clés étrangères Postgres: "
            + "; ".join(violations)
        )


def postgres_columns(conn: Any, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        return [row[0] for row in cur.fetchall()]


def normalize_row(
    table: str,
    columns: list[str],
    row: sqlite3.Row,
    *,
    assumed_timezone,
) -> list[object]:
    return normalize_sqlite_row(
        table=table,
        columns=columns,
        row=row,
        bool_columns=BOOL_COLUMNS.get(table),
        json_columns=JSON_COLUMNS.get(table),
        timestamp_columns=TIMESTAMP_COLUMNS.get(table),
        assumed_timezone=assumed_timezone,
    )


def prepare_postgres_row(
    table: str,
    columns: list[str],
    values: list[object],
) -> list[object]:
    """Adapt validated JSON text to PostgreSQL JSONB parameters."""
    jsonb_columns = JSONB_COLUMNS.get(table, set())
    if not jsonb_columns:
        return values

    from psycopg.types.json import Jsonb

    prepared = list(values)
    for column in jsonb_columns:
        if column not in columns:
            continue
        index = columns.index(column)
        value = prepared[index]
        if value is None:
            continue
        prepared[index] = Jsonb(json.loads(str(value)))
    return prepared


def apply_schema(database_url: str) -> None:
    import psycopg

    schema_path = ROOT / "backend" / "database" / "postgres_schema.sql"
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_path.read_text(encoding="utf-8"))
        conn.commit()


def truncate_pipeline_tables(pg_conn: Any) -> None:
    """Clear pipeline rows without cascading into the already imported core.

    ``formation_module_days`` is referenced by ``course_sessions``.  A
    ``TRUNCATE ... CASCADE`` would therefore erase the core occurrences loaded
    by the first migration.  Null the temporary bindings, delete children in
    reverse FK order, then reset only the pipeline sequences.
    """
    from psycopg import sql

    with pg_conn.cursor() as cur:
        cur.execute(
            "UPDATE course_sessions SET module_day_id = NULL "
            "WHERE module_day_id IS NOT NULL"
        )
        for table in reversed(PIPELINE_TABLES):
            cur.execute(
                sql.SQL("DELETE FROM {}").format(sql.Identifier(table))
            )
    for table in PIPELINE_TABLES:
        bump_sequence(pg_conn, table)


def bump_sequence(pg_conn: Any, table: str) -> None:
    from psycopg import sql

    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_get_serial_sequence(%s, 'id')
            """,
            (table,),
        )
        row = cur.fetchone()
        sequence_name = row[0] if row else None
        if not sequence_name:
            return
        cur.execute(
            sql.SQL(
                """
                SELECT setval(
                    %s::regclass,
                    COALESCE((SELECT MAX(id) FROM {}), 1),
                    (SELECT COUNT(*) > 0 FROM {})
                )
                """
            ).format(sql.Identifier(table), sql.Identifier(table)),
            (sequence_name,),
        )


def _verify_primary_keys(
    pg_conn: Any,
    *,
    table: str,
    rows: list[sqlite3.Row],
) -> int:
    from psycopg import sql

    expected_ids = {row["id"] for row in rows}
    if not expected_ids:
        return 0
    with pg_conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM {} WHERE id = ANY(%s)").format(
                sql.Identifier(table)
            ),
            (list(expected_ids),),
        )
        verified = int(cur.fetchone()[0])
    if verified != len(expected_ids):
        raise MigrationValidationError(
            f"Comptage cible incohérent pour {table}: "
            f"{verified}/{len(expected_ids)} identifiants retrouvés"
        )
    return verified


def copy_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn: Any,
    table: str,
    *,
    assumed_timezone,
    batch_size: int = 1000,
) -> int:
    from psycopg import sql

    source_cols = sqlite_columns(sqlite_conn, table)
    target_cols = postgres_columns(pg_conn, table)
    if not source_cols:
        print(f"- {table}: ignoree (source absente)")
        return 0
    if not target_cols:
        raise MigrationValidationError(
            f"Table cible Postgres absente: {table}. Appliquez le schéma avant la migration."
        )

    missing_target_columns = sorted(set(source_cols) - set(target_cols))
    if missing_target_columns:
        raise MigrationValidationError(
            f"Schéma cible incomplet pour {table}: colonne(s) SQLite absente(s) de Postgres: "
            + ", ".join(missing_target_columns)
        )

    columns = list(source_cols)
    if not columns:
        raise MigrationValidationError(f"Table source sans colonne migrable: {table}")

    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in columns)
    identifiers = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
    update_columns = [column for column in columns if column != "id"]
    if "id" in columns and update_columns:
        update_clause = sql.SQL(", ").join(
            sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(column), sql.Identifier(column))
            for column in update_columns
        )
        conflict_clause = sql.SQL("ON CONFLICT (id) DO UPDATE SET {}").format(update_clause)
    elif "id" in columns:
        conflict_clause = sql.SQL("ON CONFLICT (id) DO NOTHING")
    else:
        conflict_clause = sql.SQL("")

    insert_stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({}) {}").format(
        sql.Identifier(table),
        identifiers,
        placeholders,
        conflict_clause,
    )

    source_cursor = sqlite_conn.execute(f"SELECT {', '.join(columns)} FROM {table}")
    source_count = 0
    verified = 0
    while True:
        rows = source_cursor.fetchmany(batch_size)
        if not rows:
            break
        with pg_conn.cursor() as cur:
            cur.executemany(
                insert_stmt,
                [
                    prepare_postgres_row(
                        table,
                        columns,
                        normalize_row(
                            table,
                            columns,
                            row,
                            assumed_timezone=assumed_timezone,
                        ),
                    )
                    for row in rows
                ],
            )
        source_count += len(rows)
        verified += _verify_primary_keys(pg_conn, table=table, rows=rows)

    bump_sequence(pg_conn, table)
    if source_count == 0:
        print(f"- {table}: 0 ligne")
        return 0
    print(f"- {table}: source={source_count}, cible_verifiee={verified}")
    return source_count


def restore_course_session_module_days(
    sqlite_conn: sqlite3.Connection,
    pg_conn: Any,
) -> int:
    """Restore V2 occurrence bindings after their durable parents are copied.

    The core migration intentionally imports these values as NULL.  Each
    restoration is guarded by the existence of both the target occurrence and
    its formation_module_days parent; any mismatch aborts the surrounding
    PostgreSQL transaction.
    """
    source_columns = sqlite_columns(sqlite_conn, "course_sessions")
    if "module_day_id" not in source_columns:
        print("- course_sessions.module_day_id: colonne V1 absente, aucune restauration")
        return 0

    rows = sqlite_conn.execute(
        """
        SELECT id, module_day_id
        FROM course_sessions
        WHERE module_day_id IS NOT NULL
        ORDER BY id ASC
        """
    ).fetchall()
    if not rows:
        print("- course_sessions.module_day_id: 0 liaison V2")
        return 0

    restored = 0
    with pg_conn.cursor() as cur:
        for row in rows:
            session_id = int(row["id"])
            module_day_id = int(row["module_day_id"])
            cur.execute(
                """
                UPDATE course_sessions AS session
                SET module_day_id = %s
                WHERE session.id = %s
                  AND EXISTS (
                      SELECT 1
                      FROM formation_module_days AS module_day
                      WHERE module_day.id = %s
                  )
                RETURNING session.id, session.module_day_id
                """,
                (module_day_id, session_id, module_day_id),
            )
            restored_row = cur.fetchone()
            if (
                restored_row is None
                or int(restored_row[0]) != session_id
                or int(restored_row[1]) != module_day_id
            ):
                raise MigrationValidationError(
                    "Restauration course_sessions.module_day_id impossible: "
                    f"session={session_id}, module_day={module_day_id}. "
                    "Vérifiez que les parents V2 ont tous été importés."
                )
            restored += 1

    print(
        "- course_sessions.module_day_id: "
        f"source={len(rows)}, cible_verifiee={restored}"
    )
    return restored


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate SQLite pipeline data to Postgres")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL"))
    parser.add_argument("--sqlite-path", default=DB_PATH)
    parser.add_argument("--apply-schema", action="store_true")
    parser.add_argument("--truncate", action="store_true", help="Truncate pipeline tables before import")
    parser.add_argument(
        "--sqlite-timezone",
        default="UTC",
        help=(
            "Fuseau des timestamps pipeline SQLite sans offset (défaut: UTC, "
            "car SQLite CURRENT_TIMESTAMP est UTC)."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Nombre de lignes normalisées et écrites par lot (défaut: 1000).",
    )
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("DATABASE_URL ou SUPABASE_DB_URL est requis.")
    if not os.path.exists(args.sqlite_path):
        raise SystemExit(f"SQLite introuvable: {args.sqlite_path}")

    try:
        assumed_timezone = timezone_from_name(args.sqlite_timezone)
    except MigrationValidationError as exc:
        raise SystemExit(str(exc)) from exc
    if args.batch_size < 1:
        raise SystemExit("--batch-size doit être supérieur ou égal à 1")

    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(
            "psycopg est requis pour migrer vers Postgres. "
            "Installez les dependances avec: pip install -r backend/requirements.txt"
        ) from exc

    sqlite_conn = sqlite3.connect(args.sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    try:
        # Pin one coherent source snapshot while the live SQLite DB may still
        # receive writes. The production cutover must still freeze writers.
        sqlite_conn.execute("BEGIN")
        validate_source_integrity(sqlite_conn)
        if args.apply_schema:
            apply_schema(args.database_url)
        with psycopg.connect(args.database_url) as pg_conn:
            if args.truncate:
                truncate_pipeline_tables(pg_conn)
            total = 0
            for table in PIPELINE_TABLES:
                total += copy_table(
                    sqlite_conn,
                    pg_conn,
                    table,
                    assumed_timezone=assumed_timezone,
                    batch_size=args.batch_size,
                )
            restore_course_session_module_days(sqlite_conn, pg_conn)
            pg_conn.commit()
    finally:
        sqlite_conn.close()

    print(f"Migration pipeline terminee: {total} ligne(s) au total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
