#!/usr/bin/env python3
"""Apply the Postgres/Supabase schema.

Usage:
  DATABASE_URL='postgresql://...' python backend/tools/database/apply_postgres_schema.py
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SCHEMA = ROOT / "backend" / "database" / "postgres_schema.sql"


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply Le Socrate Postgres schema")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL"))
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("DATABASE_URL ou SUPABASE_DB_URL est requis.")

    schema_path = Path(args.schema)
    sql = schema_path.read_text(encoding="utf-8")

    with psycopg.connect(args.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()

    print(f"Schema applique: {schema_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
