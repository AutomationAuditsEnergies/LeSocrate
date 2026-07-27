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


CORE_TABLES = [
    "training_center_accounts",
    "platform_config",
    "cours_config",
    "course_schedule_config",
    "course_sessions",
    "course_reminder_recipients",
    "logs",
    "video_visits",
    "student_accounts",
    "student_profiles",
    "student_attendance_records",
    "ai_teacher_orders",
    "deletion_requests",
]

PIPELINE_OPERATOR_USERNAME = "newpiprod@gmail.com"

PRIMARY_KEY_COLUMNS = {
    "course_schedule_config": ("platform_id",),
}

BOOL_COLUMNS = {
    "training_center_accounts": {"is_active", "pipeline_access_enabled"},
    "platform_config": {"upload_locked", "public_access_enabled"},
    "student_accounts": {"is_active"},
    "student_profiles": {"is_active"},
}

JSON_COLUMNS = {
    "course_schedule_config": {"weekdays_json"},
    "student_attendance_records": {"slots_json"},
}

TIMESTAMP_COLUMNS = {
    "training_center_accounts": {"created_at", "updated_at"},
    "platform_config": {"pdf_uploaded_at", "updated_at"},
    "cours_config": {"heure_debut"},
    "course_schedule_config": {"created_at", "updated_at"},
    "course_sessions": {
        "scheduled_at",
        "activated_at",
        "completed_at",
        "reminder_previous_evening_sent_at",
        "reminder_5min_sent_at",
        "reminder_previous_evening_claimed_at",
        "reminder_5min_claimed_at",
        "session_password_generated_at",
        "audio_generation_started_at",
        "audio_generation_completed_at",
        "created_at",
        "updated_at",
    },
    "course_reminder_recipients": {"created_at"},
    "logs": {"arrivee", "depart"},
    "video_visits": {"timestamp"},
    "student_accounts": {"created_at", "updated_at"},
    "student_profiles": {"created_at", "updated_at"},
    "student_attendance_records": {"created_at", "updated_at"},
    "ai_teacher_orders": {"created_at", "updated_at"},
    "deletion_requests": {"created_at", "resolved_at"},
}

UUID_COLUMNS = {
    "student_profiles": {"auth_user_id"},
}

DATE_COLUMNS = {
    "student_attendance_records": {"course_date"},
}

SOURCE_INTEGRITY_CHECKS = (
    (
        "platform_config.center_account_id sans centre",
        {"platform_config", "training_center_accounts"},
        """
        SELECT COUNT(*) FROM platform_config c
        LEFT JOIN training_center_accounts p ON p.id = c.center_account_id
        WHERE c.center_account_id IS NOT NULL AND p.id IS NULL
        """,
    ),
    (
        "cours_config.platform_id sans plateforme",
        {"cours_config", "platform_config"},
        """
        SELECT COUNT(*) FROM cours_config c
        LEFT JOIN platform_config p ON p.id = c.platform_id
        WHERE c.platform_id IS NULL OR p.id IS NULL
        """,
    ),
    (
        "cours_config.platform_id dupliqué",
        {"cours_config"},
        """
        SELECT COUNT(*)
        FROM (
            SELECT platform_id
            FROM cours_config
            WHERE platform_id IS NOT NULL
            GROUP BY platform_id
            HAVING COUNT(*) > 1
        ) duplicates
        """,
    ),
    (
        "course_schedule_config.platform_id sans plateforme",
        {"course_schedule_config", "platform_config"},
        """
        SELECT COUNT(*) FROM course_schedule_config c
        LEFT JOIN platform_config p ON p.id = c.platform_id
        WHERE p.id IS NULL
        """,
    ),
    (
        "course_sessions.platform_id sans plateforme",
        {"course_sessions", "platform_config"},
        """
        SELECT COUNT(*) FROM course_sessions c
        LEFT JOIN platform_config p ON p.id = c.platform_id
        WHERE p.id IS NULL
        """,
    ),
    (
        "course_reminder_recipients.platform_id sans plateforme",
        {"course_reminder_recipients", "platform_config"},
        """
        SELECT COUNT(*) FROM course_reminder_recipients c
        LEFT JOIN platform_config p ON p.id = c.platform_id
        WHERE p.id IS NULL
        """,
    ),
    (
        "logs.platform_id sans plateforme",
        {"logs", "platform_config"},
        """
        SELECT COUNT(*) FROM logs c
        LEFT JOIN platform_config p ON p.id = c.platform_id
        WHERE c.platform_id IS NOT NULL AND p.id IS NULL
        """,
    ),
    (
        "video_visits sans log/plateforme",
        {"video_visits", "logs", "platform_config"},
        """
        SELECT COUNT(*) FROM video_visits c
        LEFT JOIN platform_config p ON p.id = c.platform_id
        LEFT JOIN logs l ON l.id = c.log_id
        WHERE (c.platform_id IS NOT NULL AND p.id IS NULL)
           OR (c.log_id IS NOT NULL AND l.id IS NULL)
        """,
    ),
    (
        "student_accounts.platform_id sans plateforme",
        {"student_accounts", "platform_config"},
        """
        SELECT COUNT(*) FROM student_accounts c
        LEFT JOIN platform_config p ON p.id = c.platform_id
        WHERE p.id IS NULL
        """,
    ),
    (
        "student_profiles.platform_id sans plateforme",
        {"student_profiles", "platform_config"},
        """
        SELECT COUNT(*) FROM student_profiles c
        LEFT JOIN platform_config p ON p.id = c.platform_id
        WHERE p.id IS NULL
        """,
    ),
    (
        "student_attendance_records sans profil/plateforme cohérent",
        {"student_attendance_records", "student_profiles", "platform_config"},
        """
        SELECT COUNT(*) FROM student_attendance_records c
        LEFT JOIN platform_config p ON p.id = c.platform_id
        LEFT JOIN student_profiles s ON s.id = c.student_profile_id
        WHERE p.id IS NULL OR s.id IS NULL OR s.platform_id != c.platform_id
        """,
    ),
    (
        "deletion_requests.platform_id sans plateforme",
        {"deletion_requests", "platform_config"},
        """
        SELECT COUNT(*) FROM deletion_requests c
        LEFT JOIN platform_config p ON p.id = c.platform_id
        WHERE p.id IS NULL
        """,
    ),
    (
        "ai_teacher_orders sans centre/plateforme cohérent",
        {"ai_teacher_orders", "training_center_accounts", "platform_config"},
        """
        SELECT COUNT(*) FROM ai_teacher_orders c
        LEFT JOIN training_center_accounts t ON t.id = c.center_account_id
        LEFT JOIN platform_config p ON p.id = c.platform_id
        WHERE t.id IS NULL OR (c.platform_id IS NOT NULL AND p.id IS NULL)
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
    values = normalize_sqlite_row(
        table=table,
        columns=columns,
        row=row,
        bool_columns=BOOL_COLUMNS.get(table),
        json_columns=JSON_COLUMNS.get(table),
        timestamp_columns=TIMESTAMP_COLUMNS.get(table),
        uuid_columns=UUID_COLUMNS.get(table),
        date_columns=DATE_COLUMNS.get(table),
        assumed_timezone=assumed_timezone,
    )
    # Never migrate the historical debug copy of a password into production.
    if table == "training_center_accounts" and "password_debug_plaintext" in columns:
        values[columns.index("password_debug_plaintext")] = None
    # Planning V2 parents are imported by the second (pipeline) migration.
    # Keeping the source id here would violate the immediate PostgreSQL FK on
    # course_sessions.module_day_id.  The pipeline migration restores and
    # verifies every non-null binding after formation_module_days is present.
    if table == "course_sessions" and "module_day_id" in columns:
        values[columns.index("module_day_id")] = None
    return values


def bump_sequence(pg_conn: Any, table: str) -> None:
    """Move a BIGSERIAL sequence past explicitly imported SQLite ids."""
    from psycopg import sql

    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = 'id'
            """,
            (table,),
        )
        if cur.fetchone() is None:
            return
        cur.execute("SELECT pg_get_serial_sequence(%s, 'id')", (table,))
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


def truncate_core_tables(pg_conn: Any) -> None:
    """Clear the target once, before importing any parent/child row."""
    from psycopg import sql

    with pg_conn.cursor() as cur:
        cur.execute(
            sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                sql.SQL(", ").join(sql.Identifier(table) for table in CORE_TABLES)
            )
        )


def read_target_pipeline_operator_permission(pg_conn: Any) -> bool | None:
    """Return the pre-import permission, or None when the operator is absent.

    Reading this before an optional truncate lets a legacy SQLite import retain
    an explicit PostgreSQL revocation instead of treating every rerun as a
    first-time bootstrap.
    """
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT pipeline_access_enabled
            FROM training_center_accounts
            WHERE LOWER(username) = %s
            ORDER BY id
            LIMIT 2
            """,
            (PIPELINE_OPERATOR_USERNAME,),
        )
        rows = cur.fetchall()
    if len(rows) > 1:
        raise MigrationValidationError(
            "Plusieurs comptes correspondent à "
            f"{PIPELINE_OPERATOR_USERNAME}; migration interrompue."
        )
    return bool(rows[0][0]) if rows else None


def should_bootstrap_legacy_pipeline_operator(
    *,
    source_has_permission_column: bool,
    previous_target_permission: bool | None,
) -> bool:
    """Bootstrap only a legacy source and never override a known revocation."""
    return (
        not source_has_permission_column
        and previous_target_permission is not False
    )


def reconcile_pipeline_operator_after_core_copy(
    sqlite_conn: sqlite3.Connection,
    pg_conn: Any,
    *,
    previous_target_permission: bool | None,
) -> tuple[bool, int]:
    """Preserve/grant pipeline access and attach only historical pipeline data.

    A source that already contains the permission column is authoritative. For
    an older source, the Lyon operator is enabled only on the initial import
    (or when the target was already enabled). Ownership is restricted to
    orphan platforms referenced by an actual source pipeline job.
    """
    account_columns = set(sqlite_columns(sqlite_conn, "training_center_accounts"))
    source_has_permission_column = "pipeline_access_enabled" in account_columns
    should_bootstrap = should_bootstrap_legacy_pipeline_operator(
        source_has_permission_column=source_has_permission_column,
        previous_target_permission=previous_target_permission,
    )

    with pg_conn.cursor() as cur:
        if previous_target_permission is False:
            # A PostgreSQL revocation is authoritative. This also restores it
            # after copy_table imported a stale TRUE from SQLite, including
            # when --truncate recreated the account.
            cur.execute(
                """
                UPDATE training_center_accounts
                SET pipeline_access_enabled = FALSE
                WHERE LOWER(username) = %s
                """,
                (PIPELINE_OPERATOR_USERNAME,),
            )
        elif should_bootstrap:
            cur.execute(
                """
                UPDATE training_center_accounts
                SET pipeline_access_enabled = TRUE
                WHERE LOWER(username) = %s
                  AND is_active = TRUE
                """,
                (PIPELINE_OPERATOR_USERNAME,),
            )

        cur.execute(
            """
            SELECT id, is_active, pipeline_access_enabled
            FROM training_center_accounts
            WHERE LOWER(username) = %s
            ORDER BY id
            LIMIT 2
            """,
            (PIPELINE_OPERATOR_USERNAME,),
        )
        operator_rows = cur.fetchall()

    if len(operator_rows) > 1:
        raise MigrationValidationError(
            "Plusieurs comptes correspondent à "
            f"{PIPELINE_OPERATOR_USERNAME}; rattachement interrompu."
        )
    if not operator_rows:
        return False, 0

    operator_id, is_active, permission_enabled = operator_rows[0]
    can_access_pipeline = bool(is_active) and bool(permission_enabled)
    job_columns = set(sqlite_columns(sqlite_conn, "formation_pipeline_jobs"))
    if not can_access_pipeline or "platform_id" not in job_columns:
        return can_access_pipeline, 0

    platform_ids = [
        int(row[0])
        for row in sqlite_conn.execute(
            """
            SELECT DISTINCT platform_id
            FROM formation_pipeline_jobs
            WHERE platform_id IS NOT NULL
            ORDER BY platform_id
            """
        ).fetchall()
    ]
    if not platform_ids:
        return can_access_pipeline, 0

    with pg_conn.cursor() as cur:
        cur.execute(
            """
            UPDATE platform_config
            SET center_account_id = %s
            WHERE center_account_id IS NULL
              AND id = ANY(%s)
            RETURNING id
            """,
            (operator_id, platform_ids),
        )
        attached_count = len(cur.fetchall())
    return can_access_pipeline, attached_count


def _verify_primary_keys(
    pg_conn: Any,
    *,
    table: str,
    primary_key: str,
    rows: list[sqlite3.Row],
) -> int:
    from psycopg import sql

    expected_keys = {row[primary_key] for row in rows}
    if not expected_keys:
        return 0
    with pg_conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM {} WHERE {} = ANY(%s)").format(
                sql.Identifier(table),
                sql.Identifier(primary_key),
            ),
            (list(expected_keys),),
        )
        verified = int(cur.fetchone()[0])
    if verified != len(expected_keys):
        raise MigrationValidationError(
            f"Comptage cible incohérent pour {table}: "
            f"{verified}/{len(expected_keys)} clés primaires retrouvées"
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

    primary_keys = PRIMARY_KEY_COLUMNS.get(table, ("id",))
    if len(primary_keys) != 1 or primary_keys[0] not in columns:
        raise MigrationValidationError(
            f"Clé primaire source absente ou non supportée pour {table}: {primary_keys}"
        )
    primary_key = primary_keys[0]
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in columns)
    update_columns = [column for column in columns if column != primary_key]
    if update_columns:
        update_clause = sql.SQL(", ").join(
            sql.SQL("{} = EXCLUDED.{}").format(
                sql.Identifier(column),
                sql.Identifier(column),
            )
            for column in update_columns
        )
        conflict_clause = sql.SQL("ON CONFLICT ({}) DO UPDATE SET {}").format(
            sql.Identifier(primary_key),
            update_clause,
        )
    else:
        conflict_clause = sql.SQL("ON CONFLICT ({}) DO NOTHING").format(
            sql.Identifier(primary_key)
        )

    insert_stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({}) {}").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
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
                    normalize_row(
                        table,
                        columns,
                        row,
                        assumed_timezone=assumed_timezone,
                    )
                    for row in rows
                ],
            )
        source_count += len(rows)
        verified += _verify_primary_keys(
            pg_conn,
            table=table,
            primary_key=primary_key,
            rows=rows,
        )

    bump_sequence(pg_conn, table)
    if source_count == 0:
        print(f"- {table}: 0 ligne")
        return 0
    print(f"- {table}: source={source_count}, cible_verifiee={verified}")
    return source_count


def apply_schema(database_url: str) -> None:
    import psycopg

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
    parser.add_argument(
        "--sqlite-timezone",
        default="Europe/Paris",
        help=(
            "Fuseau des timestamps SQLite sans offset (défaut: Europe/Paris). "
            "Ils sont convertis en UTC avant insertion dans TIMESTAMPTZ."
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
            "Installez les dépendances avec: pip install -r backend/requirements.txt"
        ) from exc

    sqlite_conn = sqlite3.connect(args.sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    try:
        # A read transaction pins one coherent SQLite snapshot for every table.
        sqlite_conn.execute("BEGIN")
        validate_source_integrity(sqlite_conn)
        if args.apply_schema:
            apply_schema(args.database_url)
        with psycopg.connect(args.database_url) as pg_conn:
            previous_pipeline_permission = read_target_pipeline_operator_permission(pg_conn)
            if args.truncate:
                truncate_core_tables(pg_conn)
            total = 0
            for table in CORE_TABLES:
                total += copy_table(
                    sqlite_conn,
                    pg_conn,
                    table,
                    assumed_timezone=assumed_timezone,
                    batch_size=args.batch_size,
                )
            pipeline_enabled, attached_platforms = (
                reconcile_pipeline_operator_after_core_copy(
                    sqlite_conn,
                    pg_conn,
                    previous_target_permission=previous_pipeline_permission,
                )
            )
            pg_conn.commit()
    finally:
        sqlite_conn.close()

    print(
        "Acces pipeline Lyon: "
        f"{'actif' if pipeline_enabled else 'inactif'}, "
        f"{attached_platforms} plateforme(s) historique(s) rattachee(s)"
    )
    print(f"Migration terminee: {total} ligne(s) au total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
