#!/usr/bin/env python3
"""Copy core SaaS data from the current SQLite DB to Postgres/Supabase.

This is intentionally limited to the multi-tenant runtime core. Heavy pipeline
tables can be migrated later once the app runtime has moved to Postgres.

Usage:
  DATABASE_URL='postgresql://...' python backend/tools/database/migrate_sqlite_core_to_postgres.py --apply-schema
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import psycopg
from psycopg import sql


ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import DB_PATH  # noqa: E402


CORE_TABLES = [
    "training_center_accounts",
    "platform_config",
    "cours_config",
    "logs",
    "video_visits",
    "student_accounts",
    "student_profiles",
]

BOOL_COLUMNS = {
    "training_center_accounts": {"is_active"},
    "platform_config": {"upload_locked", "public_access_enabled"},
    "student_accounts": {"is_active"},
    "student_profiles": {"is_active"},
}


def sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [row[1] for row in rows]


def postgres_columns(conn: psycopg.Connection, table: str) -> list[str]:
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


def copy_table(sqlite_conn: sqlite3.Connection, pg_conn: psycopg.Connection, table: str, truncate: bool) -> int:
    source_cols = sqlite_columns(sqlite_conn, table)
    target_cols = postgres_columns(pg_conn, table)
    if not source_cols or not target_cols:
        print(f"- {table}: ignoree (table absente)")
        return 0

    columns = [column for column in source_cols if column in target_cols]
    if not columns:
        print(f"- {table}: ignoree (aucune colonne commune)")
        return 0

    if truncate:
        with pg_conn.cursor() as cur:
            cur.execute(sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(sql.Identifier(table)))

    rows = sqlite_conn.execute(
        f"SELECT {', '.join(columns)} FROM {table}"
    ).fetchall()
    if not rows:
        print(f"- {table}: 0 ligne")
        return 0

    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in columns)
    insert_stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
        placeholders,
    )

    with pg_conn.cursor() as cur:
        cur.executemany(
            insert_stmt,
            [normalize_row(table, columns, row) for row in rows],
        )

    print(f"- {table}: {len(rows)} ligne(s) copiee(s)")
    return len(rows)


def apply_schema(database_url: str) -> None:
    schema_path = ROOT / "backend" / "database" / "postgres_schema.sql"
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_path.read_text(encoding="utf-8"))
        conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate core SQLite data to Postgres")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL"))
    parser.add_argument("--sqlite-path", default=DB_PATH)
    parser.add_argument("--apply-schema", action="store_true")
    parser.add_argument("--truncate", action="store_true", help="Truncate core tables before import")
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("DATABASE_URL ou SUPABASE_DB_URL est requis.")
    if not os.path.exists(args.sqlite_path):
        raise SystemExit(f"SQLite introuvable: {args.sqlite_path}")

    if args.apply_schema:
        apply_schema(args.database_url)

    sqlite_conn = sqlite3.connect(args.sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    try:
        with psycopg.connect(args.database_url) as pg_conn:
            total = 0
            for table in CORE_TABLES:
                total += copy_table(sqlite_conn, pg_conn, table, truncate=args.truncate)
            pg_conn.commit()
    finally:
        sqlite_conn.close()

    print(f"Migration terminee: {total} ligne(s) au total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
