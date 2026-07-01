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


PIPELINE_TABLES = [
    "formation_pipeline_jobs",
    "formation_knowledge_base",
    "cours_folders",
    "cours_documents",
    "content_generation_jobs",
    "content_generation_segments",
    "content_script_annotations",
    "content_script_rules",
    "content_review_reports",
    "formation_pipeline_events",
    "formation_modules",
    "script_slide_decks",
]

BOOL_COLUMNS = {
    "formation_pipeline_jobs": {
        "global_program_validated",
        "daily_programs_validated",
        "auto_pilot_enabled",
        "auto_pilot_use_cc",
        "auto_pilot_skip_vs",
        "auto_pilot_generate_audio",
        "auto_pilot_volume_done",
        "auto_pilot_post_review_docs_done",
    },
    "formation_knowledge_base": {"dirty"},
    "content_generation_jobs": {"from_scratch"},
    "content_generation_segments": {"dirty", "reviewed", "humanized"},
}


def sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [row[1] for row in rows]


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


def normalize_row(table: str, columns: list[str], row: sqlite3.Row) -> list[object]:
    bool_cols = BOOL_COLUMNS.get(table, set())
    values = []
    for column in columns:
        value = row[column]
        if column in bool_cols and value is not None:
            value = bool(value)
        values.append(value)
    return values


def apply_schema(database_url: str) -> None:
    import psycopg

    schema_path = ROOT / "backend" / "database" / "postgres_schema.sql"
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_path.read_text(encoding="utf-8"))
        conn.commit()


def truncate_pipeline_tables(pg_conn: Any) -> None:
    from psycopg import sql

    with pg_conn.cursor() as cur:
        cur.execute(
            sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                sql.SQL(", ").join(sql.Identifier(table) for table in PIPELINE_TABLES)
            )
        )


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


def copy_table(sqlite_conn: sqlite3.Connection, pg_conn: Any, table: str) -> int:
    from psycopg import sql

    source_cols = sqlite_columns(sqlite_conn, table)
    target_cols = postgres_columns(pg_conn, table)
    if not source_cols:
        print(f"- {table}: ignoree (source absente)")
        return 0
    if not target_cols:
        print(f"- {table}: ignoree (cible absente)")
        return 0

    columns = [column for column in source_cols if column in target_cols]
    if not columns:
        print(f"- {table}: ignoree (aucune colonne commune)")
        return 0

    rows = sqlite_conn.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
    if not rows:
        print(f"- {table}: 0 ligne")
        bump_sequence(pg_conn, table)
        return 0

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

    with pg_conn.cursor() as cur:
        cur.executemany(
            insert_stmt,
            [normalize_row(table, columns, row) for row in rows],
        )
    bump_sequence(pg_conn, table)
    print(f"- {table}: {len(rows)} ligne(s) copiee(s)")
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate SQLite pipeline data to Postgres")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL"))
    parser.add_argument("--sqlite-path", default=DB_PATH)
    parser.add_argument("--apply-schema", action="store_true")
    parser.add_argument("--truncate", action="store_true", help="Truncate pipeline tables before import")
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("DATABASE_URL ou SUPABASE_DB_URL est requis.")
    if not os.path.exists(args.sqlite_path):
        raise SystemExit(f"SQLite introuvable: {args.sqlite_path}")

    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(
            "psycopg est requis pour migrer vers Postgres. "
            "Installez les dependances avec: pip install -r backend/requirements.txt"
        ) from exc

    if args.apply_schema:
        apply_schema(args.database_url)

    sqlite_conn = sqlite3.connect(args.sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    try:
        with psycopg.connect(args.database_url) as pg_conn:
            if args.truncate:
                truncate_pipeline_tables(pg_conn)
            total = 0
            for table in PIPELINE_TABLES:
                total += copy_table(sqlite_conn, pg_conn, table)
            pg_conn.commit()
    finally:
        sqlite_conn.close()

    print(f"Migration pipeline terminee: {total} ligne(s) au total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
