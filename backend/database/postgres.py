"""Postgres access helpers for the multi-tenant SaaS and formation pipeline."""
from contextlib import contextmanager
from functools import lru_cache
import os
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from config import DATABASE_BACKEND, DATABASE_URL

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - local env may still be SQLite-only.
    psycopg = None
    dict_row = None

try:
    from psycopg_pool import ConnectionPool
except ImportError:  # pragma: no cover - SQLite-only/local bootstrap.
    ConnectionPool = None


POSTGRES_BACKENDS = {"postgres", "postgresql", "postgres_core", "hybrid", "supabase"}

PIPELINE_REQUIRED_SCHEMA = {
    "training_center_accounts": {
        "id",
        "auth_user_id",
        "username",
        "billing_mode",
        "stripe_customer_id",
        "onboarding_version",
        "onboarding_completed_at",
        "pipeline_access_enabled",
    },
    "platform_config": {
        "id",
        "center_account_id",
        "center_platform_number",
        "status",
        "source_formation_id",
        "source_module_id",
        "lifecycle_status",
        "completed_at",
        "archived_at",
        "asset_binding_mode",
    },
    "formation_pipeline_jobs": {
        "id",
        "platform_id",
        "status",
        "daily_programs",
        "auto_pilot_enabled",
        "auto_pilot_post_review_docs_done",
        "auto_pilot_locked_at",
        "schedule_schema_version",
        "schedule_snapshot_json",
        "schedule_hash",
        "schedule_locked_at",
    },
    "formation_knowledge_base": {"id", "job_id", "competence_index", "status", "dirty"},
    "cours_folders": {
        "id",
        "platform_id",
        "formation_job_id",
        "module_day_id",
        "position",
    },
    "cours_documents": {"id", "folder_id", "filename", "doc_type", "status"},
    "course_clone_folder_map": {
        "target_platform_id",
        "source_platform_id",
        "source_folder_id",
        "target_folder_id",
    },
    "course_schedule_config": {"platform_id", "total_training_days", "weekdays_json", "start_time"},
    "course_sessions": {
        "id",
        "platform_id",
        "session_index",
        "scheduled_at",
        "session_password",
        "reminder_previous_evening_claimed_at",
        "reminder_5min_claimed_at",
        "audio_generation_status",
        "audio_generation_started_at",
        "audio_generation_completed_at",
        "audio_generation_error",
        "audio_generation_attempts",
        "audio_generation_next_retry_at",
        "audio_job_id",
        "audio_folder_id",
        "audio_storage_prefix",
        "postponed_from",
        "postponed_at",
        "postponement_count",
        "module_day_id",
        "local_date",
    },
    "course_session_postponements": {
        "id",
        "platform_id",
        "session_id",
        "session_index",
        "previous_scheduled_at",
        "new_scheduled_at",
        "mode",
        "affected_session_count",
        "idempotency_key",
        "impact_json",
    },
    "course_reminder_recipients": {"id", "platform_id", "email"},
    "course_reminder_rules": {
        "id",
        "platform_id",
        "trigger_mode",
        "subject_template",
        "content_template",
        "recipient_scope",
        "is_active",
    },
    "course_reminder_rule_recipients": {"rule_id", "recipient_id"},
    "course_reminder_deliveries": {
        "id",
        "platform_id",
        "session_id",
        "rule_id",
        "recipient_id",
        "recipient_hash",
        "due_at",
        "status",
        "claimed_at",
        "lease_expires_at",
        "sent_at",
        "attempts",
        "max_attempts",
        "next_retry_at",
    },
    "logs": {
        "id",
        "platform_id",
        "course_session_id",
        "recipient_hash",
        "attendance_started_at",
        "last_seen_at",
        "depart",
        "closed_reason",
    },
    "attendance_daily_exports": {
        "id",
        "center_account_id",
        "platform_id",
        "center_platform_number",
        "course_session_id",
        "teacher_module_id",
        "course_date",
        "available_at",
        "status",
        "lease_expires_at",
        "attempts",
        "blob_key",
        "participant_count",
        "generated_at",
    },
    "ai_teacher_orders": {
        "id",
        "public_id",
        "center_account_id",
        "operation_type",
        "creation_request_id",
        "payment_status",
        "fulfillment_status",
        "request_payload_json",
    },
    "stripe_webhook_events": {"event_id", "event_type", "status", "payload_json"},
    "content_generation_jobs": {"id", "folder_id", "status", "module_contents"},
    "content_generation_segments": {
        "id",
        "job_id",
        "status",
        "text_content",
        "reviewed",
        "review_signature",
        "humanized",
        "dirty",
    },
    "content_review_reports": {"id", "job_id", "folder_id", "report_json"},
    "content_script_annotations": {"id", "folder_id", "job_id", "status", "selected_text"},
    "content_script_rules": {"id", "folder_id", "job_id", "rules_markdown"},
    "formation_pipeline_events": {"id", "job_id", "folder_id", "event_type", "created_at"},
    "formation_modules": {
        "id",
        "center_account_id",
        "source_pipeline_job_id",
        "source_platform_id",
        "status",
        "teacher_name",
        "teacher_color",
        "asset_namespace",
        "immutable",
        "canonical_fingerprint",
        "canonical_signature_json",
        "canonical_generator_version",
        "canonical_reuse_allowed",
        "nb_days",
        "schedule_schema_version",
        "schedule_hash",
        "schedule_locked_at",
        "reusable_at",
    },
    "day_schedule_templates": {
        "id",
        "center_account_id",
        "name",
        "status",
        "schedule_schema_version",
        "blocks_snapshot_json",
        "blocks_hash",
        "block_count",
        "total_duration_minutes",
        "course_duration_minutes",
        "used_at",
        "locked_at",
        "deleted_at",
    },
    "day_schedule_template_blocks": {
        "id",
        "template_id",
        "block_key",
        "position",
        "block_type",
        "pause_kind",
        "start_minute",
        "end_minute",
        "duration_minutes",
        "metadata_json",
    },
    "formation_module_days": {
        "id",
        "module_id",
        "center_account_id",
        "day_index",
        "source_template_id",
        "template_name",
        "schedule_schema_version",
        "schedule_hash",
        "blocks_snapshot_json",
        "block_count",
        "total_duration_minutes",
        "course_duration_minutes",
        "immutable",
        "locked_at",
    },
    "formation_module_assets": {
        "id",
        "module_id",
        "center_account_id",
        "source_folder_id",
        "asset_kind",
        "logical_key",
        "container_name",
        "blob_path",
        "content_sha256",
        "status",
        "storage_tier",
        "immutable",
    },
    "script_slide_decks": {"id", "folder_id", "content_job_id", "slides_json", "audio_sync_json"},
    "pipeline_work_items": {
        "id",
        "pipeline_job_id",
        "folder_id",
        "resource_key",
        "run_id",
        "task_type",
        "scope_key",
        "dedupe_key",
        "status",
        "lease_token",
        "lease_version",
        "lease_expires_at",
    },
    "pipeline_work_outbox": {"id", "work_item_id", "delivery_id", "status", "payload_json"},
}

PIPELINE_REQUIRED_INDEXES = {
    "uq_cours_folders_job_name",
    "uq_ai_teacher_orders_creation_request",
    "uq_ai_teacher_orders_public_id",
    "uq_pipeline_work_items_active_scope",
    "uq_pipeline_work_items_active_resource_scope",
    "uq_course_reminder_rules_system_key",
    "idx_course_reminder_deliveries_lookup",
    "idx_logs_open_presence",
    "idx_attendance_daily_exports_due",
    "idx_attendance_daily_exports_center_platform_date",
    "idx_formation_modules_canonical_reuse",
    "idx_day_schedule_templates_center_status",
    "idx_day_schedule_template_blocks_template",
    "idx_formation_module_days_center_module",
}


def postgres_enabled():
    return bool(DATABASE_URL) and DATABASE_BACKEND in POSTGRES_BACKENDS


def require_postgres():
    if not postgres_enabled():
        raise RuntimeError("Postgres n'est pas activé (DATABASE_BACKEND/DATABASE_URL).")
    if psycopg is None:
        raise RuntimeError("psycopg n'est pas installé. Lancez: pip install -r requirements.txt")


@lru_cache(maxsize=1)
def _connection_url() -> str:
    """Build a bounded connection URL without defeating managed DNS failover.

    ``hostaddr`` pins one resolved IP and therefore must be an explicit escape
    hatch only. Persistent Azure/Supabase services should normally use the DNS
    hostname (or the provider's session pooler) so HA failover remains usable.
    """
    if not DATABASE_URL:
        return DATABASE_URL

    parts = urlsplit(DATABASE_URL)
    if parts.scheme not in {"postgres", "postgresql"} or not parts.hostname:
        return DATABASE_URL

    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if "connect_timeout" not in query:
        query["connect_timeout"] = os.getenv("POSTGRES_CONNECT_TIMEOUT_SECONDS", "20")

    force_ipv4 = os.getenv("POSTGRES_FORCE_IPV4", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if query.get("hostaddr") or not force_ipv4:
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    try:
        infos = socket.getaddrinfo(
            parts.hostname,
            parts.port or 5432,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
    except OSError:
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    if not infos:
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    query["hostaddr"] = infos[0][4][0]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@lru_cache(maxsize=1)
def _connection_pool():
    if ConnectionPool is None:
        return None
    min_size = max(0, int(os.getenv("POSTGRES_POOL_MIN_SIZE", "1")))
    max_size = max(min_size or 1, int(os.getenv("POSTGRES_POOL_MAX_SIZE", "12")))
    timeout = max(1.0, float(os.getenv("POSTGRES_POOL_TIMEOUT_SECONDS", "30")))
    max_lifetime = max(60.0, float(os.getenv("POSTGRES_POOL_MAX_LIFETIME_SECONDS", "1800")))
    max_idle = max(30.0, float(os.getenv("POSTGRES_POOL_MAX_IDLE_SECONDS", "300")))
    reconnect_timeout = max(5.0, float(os.getenv("POSTGRES_POOL_RECONNECT_TIMEOUT_SECONDS", "60")))
    session_timezone = os.getenv("POSTGRES_TIMEZONE", "Europe/Paris").strip() or "Europe/Paris"
    pool = ConnectionPool(
        conninfo=_connection_url(),
        min_size=min_size,
        max_size=max_size,
        timeout=timeout,
        max_lifetime=max_lifetime,
        max_idle=max_idle,
        reconnect_timeout=reconnect_timeout,
        open=False,
        kwargs={
            "row_factory": dict_row,
            # Supabase's transaction pooler must not receive named prepared
            # statements tied to a previous server-side session.
            "prepare_threshold": None,
            "application_name": os.getenv("POSTGRES_APPLICATION_NAME", "le-socrate-api"),
            "options": f"-c timezone={session_timezone}",
        },
        check=ConnectionPool.check_connection,
        name="le-socrate-postgres",
    )
    pool.open(wait=True, timeout=timeout)
    return pool


@contextmanager
def get_postgres_connection():
    require_postgres()
    pool = _connection_pool()
    if pool is not None:
        timeout = max(1.0, float(os.getenv("POSTGRES_POOL_TIMEOUT_SECONDS", "30")))
        with pool.connection(timeout=timeout) as conn:
            yield conn
        return

    # Safe fallback for local environments that have psycopg but have not yet
    # installed the pool extra. Production requirements include psycopg_pool.
    with psycopg.connect(
        _connection_url(),
        row_factory=dict_row,
        prepare_threshold=None,
        application_name=os.getenv("POSTGRES_APPLICATION_NAME", "le-socrate-api"),
        options=f"-c timezone={os.getenv('POSTGRES_TIMEZONE', 'Europe/Paris')}",
    ) as conn:
        yield conn


def validate_pipeline_postgres_schema() -> None:
    """Fail fast when the applied Supabase schema lags behind runtime code."""
    require_postgres()
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = ANY(%s)
                """,
                (list(PIPELINE_REQUIRED_SCHEMA),),
            )
            actual: dict[str, set[str]] = {}
            for row in cur.fetchall():
                actual.setdefault(row["table_name"], set()).add(row["column_name"])
            cur.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND indexname = ANY(%s)
                """,
                (list(PIPELINE_REQUIRED_INDEXES),),
            )
            actual_indexes = {
                row["indexname"]: row["indexdef"]
                for row in cur.fetchall()
            }

    missing = []
    for table, required_columns in PIPELINE_REQUIRED_SCHEMA.items():
        if table not in actual:
            missing.append(f"table {table}")
            continue
        for column in sorted(required_columns - actual[table]):
            missing.append(f"{table}.{column}")
    for index_name in sorted(PIPELINE_REQUIRED_INDEXES - set(actual_indexes)):
        missing.append(f"index {index_name}")
    active_scope_index = actual_indexes.get("uq_pipeline_work_items_active_scope", "")
    normalized_index = active_scope_index.replace('"', "")
    if active_scope_index and not all(
        fragment in normalized_index
        for fragment in (
            "CREATE UNIQUE INDEX",
            "(pipeline_job_id, scope_key)",
            "queued",
            "retry_scheduled",
            "running",
        )
    ):
        missing.append("index uq_pipeline_work_items_active_scope (définition invalide)")
    active_resource_scope_index = actual_indexes.get(
        "uq_pipeline_work_items_active_resource_scope", ""
    )
    normalized_resource_index = active_resource_scope_index.replace('"', "")
    if active_resource_scope_index and not all(
        fragment in normalized_resource_index
        for fragment in (
            "CREATE UNIQUE INDEX",
            "(resource_key, scope_key)",
            "queued",
            "retry_scheduled",
            "running",
        )
    ):
        missing.append(
            "index uq_pipeline_work_items_active_resource_scope (définition invalide)"
        )
    folder_identity_index = actual_indexes.get("uq_cours_folders_job_name", "")
    normalized_folder_index = folder_identity_index.replace('"', "")
    if folder_identity_index and not all(
        fragment in normalized_folder_index
        for fragment in (
            "CREATE UNIQUE INDEX",
            "(formation_job_id, name)",
            "formation_job_id IS NOT NULL",
        )
    ):
        missing.append("index uq_cours_folders_job_name (définition invalide)")
    if missing:
        detail = ", ".join(missing)
        raise RuntimeError(
            "Schéma Postgres pipeline incomplet: "
            f"{detail}. Appliquez backend/database/postgres_schema.sql avant le démarrage."
        )
