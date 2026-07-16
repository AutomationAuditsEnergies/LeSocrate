"""Backend-neutral storage for formation pipeline state and artifacts.

SQLite remains supported for local/stable deployments. When the pipeline
backend is Postgres, every formation aggregate handled here stays in Postgres;
the temporary hybrid mirror only exists for legacy HR/schedule routes.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from typing import Any, Mapping

from config import DATABASE_BACKEND, PIPELINE_DATABASE_BACKEND, PIPELINE_POSTGRES_MIRROR
from database.db import get_db_connection
from database.postgres import get_postgres_connection, postgres_enabled
from repositories.course_schedule_repository import schedule_store_is_postgres
from utils.logger import get_logger
from utils.slug import slugify


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

POSTGRES_TRANSIENT_ERROR_MARKERS = (
    "connection timeout",
    "timeout expired",
    "could not connect",
    "connection refused",
    "connection reset",
    "server closed the connection",
    "terminating connection",
    "the connection is closed",
    "couldn't get a connection",
    "pool timeout",
    "remaining connection slots are reserved",
    "too many connections",
)


class PlatformIdentityConflictError(RuntimeError):
    """An ID already belongs to another tenant/slug platform identity."""


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


def _is_transient_postgres_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in POSTGRES_TRANSIENT_ERROR_MARKERS)


def _run_postgres_with_retry(label: str, operation, *, attempts: int = 3):
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:
            if attempt >= attempts or not _is_transient_postgres_error(exc):
                raise
            wait_seconds = min(10.0, 1.5 * attempt)
            logger.warning(
                "PIPELINE_POSTGRES_RETRY label=%s attempt=%s/%s wait=%.1fs error=%s",
                label,
                attempt,
                attempts,
                wait_seconds,
                str(exc)[:300],
            )
            time.sleep(wait_seconds)


def _sqlite_pipeline_mirror_required() -> bool:
    """Keep the temporary hybrid UI/scheduler mirror out of pure Postgres mode."""
    return _pipeline_primary_backend() == "postgres" and DATABASE_BACKEND == "hybrid"


def platform_ids_use_postgres_allocator() -> bool:
    """Whether hybrid writers must reserve platform IDs in PostgreSQL first.

    This deliberately follows the configured authority rather than connection
    availability. A broken PostgreSQL configuration must fail closed instead
    of allocating a potentially colliding SQLite ID.
    """
    return _sqlite_pipeline_mirror_required()


def _upsert_pipeline_platform_sqlite(platform: dict[str, Any]) -> None:
    """Compatibility mirror for routes that have not left SQLite yet.

    Postgres remains authoritative when the pipeline backend is Postgres. This
    mirror is deliberately one-way and only enabled in the temporary hybrid
    deployment mode.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT center_account_id, slug FROM platform_config WHERE id = ?",
            (platform["id"],),
        )
        existing = cursor.fetchone()
        incoming_identity = (platform.get("center_account_id"), platform.get("slug"))
        if existing is not None and tuple(existing) != incoming_identity:
            raise PlatformIdentityConflictError(
                "Refus d'écraser le miroir SQLite: "
                f"platform_config.id={platform['id']} appartient déjà à "
                f"l'identité {tuple(existing)!r}, reçue={incoming_identity!r}"
            )
        cursor.execute(
            """
            INSERT INTO platform_config (
                id, center_account_id, name, slug, upload_locked,
                public_access_enabled, updated_at, playlist_mode,
                audio_container, pdf_container, archive_container,
                audio_base_url, status, source_formation_id, source_module_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                center_account_id = excluded.center_account_id,
                name = excluded.name,
                slug = excluded.slug,
                upload_locked = excluded.upload_locked,
                public_access_enabled = excluded.public_access_enabled,
                updated_at = excluded.updated_at,
                playlist_mode = excluded.playlist_mode,
                audio_container = excluded.audio_container,
                pdf_container = excluded.pdf_container,
                archive_container = excluded.archive_container,
                audio_base_url = excluded.audio_base_url,
                status = excluded.status,
                source_formation_id = excluded.source_formation_id,
                source_module_id = excluded.source_module_id
            WHERE platform_config.center_account_id IS excluded.center_account_id
              AND platform_config.slug IS excluded.slug
            """,
            (
                platform["id"],
                platform.get("center_account_id"),
                platform["name"],
                platform["slug"],
                1 if platform.get("upload_locked", True) else 0,
                1 if platform.get("public_access_enabled", True) else 0,
                platform["updated_at"],
                platform.get("playlist_mode"),
                platform.get("audio_container"),
                platform.get("pdf_container"),
                platform.get("archive_container"),
                platform.get("audio_base_url") or "",
                platform.get("status") or "pending",
                platform.get("source_formation_id"),
                platform.get("source_module_id"),
            ),
        )
        if cursor.rowcount != 1:
            raise PlatformIdentityConflictError(
                "Refus d'écraser le miroir SQLite: collision concurrente sur "
                f"platform_config.id={platform['id']}"
            )
        conn.commit()
    finally:
        conn.close()


def _sqlite_platform_max_id() -> int:
    """Read the committed SQLite high-water mark used during hybrid cutover."""
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM platform_config").fetchone()
        return int(row[0] if row else 0)
    finally:
        conn.close()


def _row_scalar(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, IndexError):
        return row[0]


def _allocate_platform_id_postgres(cur, *, sqlite_max_id: int = 0) -> int:
    """Reserve the next collision-free platform ID from PostgreSQL.

    ``nextval`` is monotonic and non-transactional. The advisory lock makes the
    one-time SQLite high-water reconciliation atomic across every creator that
    uses this allocator. We never move the sequence backwards: an already
    reserved sequence value wins over both table maxima.
    """
    cur.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        ("platform-config-id-allocator:v1",),
    )
    cur.execute(
        "SELECT pg_get_serial_sequence(%s, %s) AS sequence_name",
        ("platform_config", "id"),
    )
    sequence_row = cur.fetchone()
    sequence_name = _row_scalar(sequence_row, "sequence_name") if sequence_row else None
    if not sequence_name:
        raise RuntimeError("Séquence PostgreSQL de platform_config.id introuvable")

    cur.execute("SELECT COALESCE(MAX(id), 0) AS max_id FROM platform_config")
    pg_max_row = cur.fetchone()
    pg_max_id = int(_row_scalar(pg_max_row, "max_id") if pg_max_row else 0)
    required_floor = max(0, int(sqlite_max_id or 0), pg_max_id)

    cur.execute("SELECT nextval(%s::regclass) AS id", (sequence_name,))
    candidate = int(_row_scalar(cur.fetchone(), "id"))
    if candidate <= required_floor:
        cur.execute(
            "SELECT setval(%s::regclass, %s, TRUE)",
            (sequence_name, required_floor),
        )
        cur.execute("SELECT nextval(%s::regclass) AS id", (sequence_name,))
        candidate = int(_row_scalar(cur.fetchone(), "id"))
    return candidate


def allocate_platform_id_from_postgres(*, sqlite_max_id: int | None = None) -> int:
    """Public allocator used by the legacy HR writer during hybrid cutover."""
    if _pipeline_primary_backend() != "postgres":
        raise RuntimeError("L'allocateur PostgreSQL exige PIPELINE_DATABASE_BACKEND=postgres")
    if sqlite_max_id is None:
        sqlite_max_id = _sqlite_platform_max_id() if _sqlite_pipeline_mirror_required() else 0
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            return _allocate_platform_id_postgres(cur, sqlite_max_id=int(sqlite_max_id))


def _insert_pipeline_platform_postgres(
    cur,
    *,
    platform_name: str,
    center_account_id: int | None,
    teacher_name: str | None = None,
    teacher_color: str | None = None,
    creation_request_id: str | None = None,
    source_module_id: int | None = None,
) -> dict[str, Any]:
    """Insert a platform using the caller's transaction."""
    if creation_request_id:
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (f"pipeline-platform-request:{creation_request_id}",),
        )
        cur.execute(
            """
            SELECT id, center_account_id, name, slug, upload_locked,
                   public_access_enabled, updated_at, playlist_mode, status,
                   source_formation_id, source_module_id, teacher_name,
                   teacher_color, creation_request_id, audio_container,
                   pdf_container, archive_container, audio_base_url
            FROM platform_config
            WHERE creation_request_id = %s
              AND center_account_id IS NOT DISTINCT FROM %s
            """,
            (creation_request_id, center_account_id),
        )
        existing = cur.fetchone()
        if existing:
            return {**dict(existing), "deduplicated": True}
    sqlite_max_id = _sqlite_platform_max_id() if _sqlite_pipeline_mirror_required() else 0
    allocated_id = _allocate_platform_id_postgres(cur, sqlite_max_id=sqlite_max_id)
    base_slug = slugify(platform_name, fallback="formation")[:48]
    lock_key = f"pipeline-platform:{center_account_id or 0}:{base_slug}"
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock_key,))
    candidate = base_slug
    suffix = 2
    while True:
        cur.execute(
            """
            SELECT 1
            FROM platform_config
            WHERE slug = %s
              AND center_account_id IS NOT DISTINCT FROM %s
            LIMIT 1
            """,
            (candidate, center_account_id),
        )
        if cur.fetchone() is None:
            break
        suffix_text = f"-{suffix}"
        candidate = f"{base_slug[:48 - len(suffix_text)]}{suffix_text}"
        suffix += 1

    cur.execute(
        """
        INSERT INTO platform_config (
            id, center_account_id, name, slug, upload_locked,
            public_access_enabled, updated_at, status, audio_base_url,
            teacher_name, teacher_color, creation_request_id, source_module_id
        )
        VALUES (%s, %s, %s, %s, TRUE, TRUE, NOW(), 'pending', '', %s, %s, %s, %s)
        RETURNING id, center_account_id, name, slug, upload_locked,
                  public_access_enabled, updated_at, playlist_mode,
                  status, source_formation_id, source_module_id, teacher_name,
                  teacher_color, creation_request_id
        """,
        (
            allocated_id, center_account_id, platform_name, candidate,
            teacher_name, teacher_color, creation_request_id, source_module_id,
        ),
    )
    platform = dict(cur.fetchone())
    platform_id = int(platform["id"])
    platform.update(
        {
            "audio_container": f"formationaudio-p{platform_id}",
            "pdf_container": f"formationpdf-p{platform_id}",
            "archive_container": f"formationaudio-p{platform_id}-archives",
            "audio_base_url": "",
        }
    )
    cur.execute(
        """
        UPDATE platform_config
        SET audio_container = %s,
            pdf_container = %s,
            archive_container = %s
        WHERE id = %s
        """,
        (
            platform["audio_container"],
            platform["pdf_container"],
            platform["archive_container"],
            platform_id,
        ),
    )
    return platform


def create_pipeline_platform(
    *,
    name: str,
    center_account_id: int | None = None,
    teacher_name: str | None = None,
    teacher_color: str | None = None,
    creation_request_id: str | None = None,
    source_module_id: int | None = None,
) -> dict[str, Any]:
    """Create the platform in the same authoritative store as its pipeline.

    The previous implementation inserted the platform in SQLite and then the
    job in Postgres. The Postgres foreign key therefore rejected every fresh
    pipeline whose platform had not been migrated beforehand.
    """
    platform_name = str(name or "").strip()
    if not platform_name:
        raise ValueError("Le nom de plateforme est requis")
    base_slug = slugify(platform_name, fallback="formation")[:48]

    if _pipeline_primary_backend() == "postgres":
        def _postgres_operation():
            with get_postgres_connection() as conn:
                with conn.cursor() as cur:
                    return _insert_pipeline_platform_postgres(
                        cur,
                        platform_name=platform_name,
                        center_account_id=center_account_id,
                        teacher_name=teacher_name,
                        teacher_color=teacher_color,
                        creation_request_id=creation_request_id,
                        source_module_id=source_module_id,
                    )

        platform = _run_postgres_with_retry("create_pipeline_platform", _postgres_operation)
        if _sqlite_pipeline_mirror_required():
            try:
                _upsert_pipeline_platform_sqlite(platform)
            except Exception:
                logger.warning(
                    "PIPELINE_PLATFORM_SQLITE_MIRROR_FAILED platform_id=%s",
                    platform.get("id"),
                    exc_info=True,
                )
        return platform

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        candidate = base_slug
        suffix = 2
        while cursor.execute(
            "SELECT 1 FROM platform_config WHERE slug = ? AND center_account_id IS ? LIMIT 1",
            (candidate, center_account_id),
        ).fetchone():
            suffix_text = f"-{suffix}"
            candidate = f"{base_slug[:48 - len(suffix_text)]}{suffix_text}"
            suffix += 1
        cursor.execute(
            """
            INSERT INTO platform_config (
                center_account_id, name, slug, upload_locked,
                public_access_enabled, updated_at, status, audio_base_url
            )
            VALUES (?, ?, ?, 1, 1, ?, 'pending', '')
            """,
            (center_account_id, platform_name, candidate, now),
        )
        platform_id = int(cursor.lastrowid)
        platform = {
            "id": platform_id,
            "center_account_id": center_account_id,
            "name": platform_name,
            "slug": candidate,
            "upload_locked": True,
            "public_access_enabled": True,
            "updated_at": now,
            "playlist_mode": None,
            "audio_container": f"formationaudio-p{platform_id}",
            "pdf_container": f"formationpdf-p{platform_id}",
            "archive_container": f"formationaudio-p{platform_id}-archives",
            "audio_base_url": "",
            "status": "pending",
            "source_formation_id": None,
            "source_module_id": None,
        }
        cursor.execute(
            """
            UPDATE platform_config
            SET audio_container = ?, pdf_container = ?, archive_container = ?
            WHERE id = ?
            """,
            (
                platform["audio_container"],
                platform["pdf_container"],
                platform["archive_container"],
                platform_id,
            ),
        )
        conn.commit()
        return platform
    finally:
        conn.close()


def create_postgres_pipeline_aggregate(
    *,
    platform_name: str,
    center_account_id: int | None,
    tp_name: str,
    rncp_code: str,
    total_hours: int,
    nb_days: int,
    model: str | None = None,
    teacher_name: str | None = None,
    teacher_color: str | None = None,
    creation_request_id: str | None = None,
) -> dict[str, Any]:
    """Atomically create the Postgres platform, pipeline job, and their link.

    This closes the orphan window left by three separate HTTP-layer writes. The
    optional SQLite compatibility mirror is updated only *after* the Postgres
    transaction commits and is never authoritative.
    """
    if _pipeline_primary_backend() != "postgres":
        raise RuntimeError("create_postgres_pipeline_aggregate requiert PostgreSQL")
    platform_name = str(platform_name or "").strip()
    tp_name = str(tp_name or "").strip()
    rncp_code = str(rncp_code or "").strip()
    if not platform_name or not tp_name or not rncp_code:
        raise ValueError("platform_name, tp_name et rncp_code sont requis")
    if int(total_hours) <= 0 or int(nb_days) <= 0:
        raise ValueError("total_hours et nb_days doivent être positifs")

    def _operation():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                platform = _insert_pipeline_platform_postgres(
                    cur,
                    platform_name=platform_name,
                    center_account_id=center_account_id,
                    teacher_name=teacher_name,
                    teacher_color=teacher_color,
                    creation_request_id=creation_request_id,
                )
                if platform.get("deduplicated"):
                    job_id = platform.get("source_formation_id")
                    if not job_id:
                        cur.execute(
                            "SELECT id FROM formation_pipeline_jobs WHERE platform_id = %s ORDER BY id LIMIT 1",
                            (int(platform["id"]),),
                        )
                        row = cur.fetchone()
                        job_id = row and row["id"]
                    if not job_id:
                        raise RuntimeError("Plateforme idempotente sans pipeline associée")
                    return {"platform": platform, "job_id": int(job_id), "deduplicated": True}
                cur.execute(
                    """
                    INSERT INTO formation_pipeline_jobs
                        (platform_id, tp_name, rncp_code, total_hours, nb_days,
                         status, auto_pilot_model)
                    VALUES (%s, %s, %s, %s, %s, 'init', %s)
                    RETURNING id
                    """,
                    (
                        int(platform["id"]),
                        tp_name,
                        rncp_code,
                        int(total_hours),
                        int(nb_days),
                        model,
                    ),
                )
                job_id = int(cur.fetchone()["id"])
                cur.execute(
                    """
                    UPDATE platform_config
                    SET source_formation_id = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (job_id, int(platform["id"])),
                )
                platform["source_formation_id"] = job_id
                return {"platform": platform, "job_id": job_id}

    # INSERT+commit is deliberately not transport-retried: after an ambiguous
    # commit a blind retry could create a second platform. The transaction is
    # atomic; callers may safely query/retry with an explicit API idempotency key
    # when that contract is introduced.
    result = _operation()
    if _sqlite_pipeline_mirror_required():
        try:
            _upsert_pipeline_platform_sqlite(result["platform"])
        except Exception:
            logger.warning(
                "PIPELINE_AGGREGATE_SQLITE_MIRROR_FAILED platform_id=%s job_id=%s",
                result["platform"].get("id"),
                result["job_id"],
                exc_info=True,
            )
    return result


def link_pipeline_platform_to_job(platform_id: int, job_id: int) -> None:
    """Persist the platform/job relationship in the authoritative backend."""
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE platform_config
                    SET source_formation_id = COALESCE(source_formation_id, %s),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (job_id, platform_id),
                )
                if cur.rowcount != 1:
                    raise ValueError(f"Plateforme Postgres introuvable: {platform_id}")
        if _sqlite_pipeline_mirror_required():
            conn = get_db_connection()
            try:
                conn.execute(
                    "UPDATE platform_config SET source_formation_id = ? WHERE id = ?",
                    (job_id, platform_id),
                )
                conn.commit()
            finally:
                conn.close()
        return

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE platform_config
            SET source_formation_id = COALESCE(source_formation_id, ?)
            WHERE id = ?
            """,
            (job_id, platform_id),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"Plateforme SQLite introuvable: {platform_id}")
        conn.commit()
    finally:
        conn.close()


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
    """Create a course folder at the next platform position.

    PostgreSQL creation is idempotent for ``(formation_job_id, name)``.  The
    platform advisory lock serializes both the identity re-check and position
    allocation, while the partial unique index in ``postgres_schema.sql`` is
    the final guard for writers which do not use this repository.

    SQLite deliberately keeps its historical behaviour: old databases may
    contain duplicate day folders and the read path still ranks those rows to
    select a canonical folder.
    """
    ph = _placeholder()
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    (int(platform_id),),
                )
                cur.execute(
                    """
                    SELECT
                        cf.id,
                        cf.name,
                        cf.position,
                        cf.platform_id,
                        cf.formation_job_id,
                        cgj.id AS content_job_id,
                        cgj.status AS content_status,
                        COALESCE(cgj.total_words, 0) AS total_words,
                        COALESCE((
                            SELECT COUNT(*)
                            FROM content_generation_segments cgs
                            WHERE cgs.job_id = cgj.id AND cgs.status = 'completed'
                        ), 0) AS segments_completed
                    FROM cours_folders cf
                    LEFT JOIN content_generation_jobs cgj ON cgj.folder_id = cf.id
                    WHERE cf.formation_job_id = %s AND cf.name = %s
                    ORDER BY cf.id ASC
                    LIMIT 1
                    """,
                    (formation_job_id, folder_name),
                )
                existing = cur.fetchone()
                if existing:
                    return dict(existing)
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


def list_course_folder_rows_for_platform(platform_id: int) -> dict[str, Any]:
    """List course folders for a platform using the pipeline storage backend."""
    ph = _placeholder()

    def _row_to_folder(row: dict[str, Any]) -> dict[str, Any]:
        created_at = row.get("created_at")
        if hasattr(created_at, "isoformat"):
            created_at = created_at.isoformat()
        return {
            "id": int(row["id"]),
            "name": row["name"],
            "created_at": created_at,
            "document_count": int(row.get("document_count") or 0),
            "position": int(row.get("position") or 0),
        }

    count_query = f"SELECT COUNT(*) AS count FROM cours_folders WHERE platform_id = {ph}"
    source_query = f"""
        SELECT pc.id
        FROM platform_config pc
        JOIN cours_folders cf ON cf.platform_id = pc.id
        WHERE pc.source_formation_id = {ph}
        GROUP BY pc.id
        ORDER BY pc.id DESC
        LIMIT 1
    """
    folders_query = f"""
        SELECT
            cf.id,
            cf.name,
            cf.created_at,
            CASE
                WHEN SUM(
                    CASE
                        WHEN cd.doc_type = 'final_script'
                          OR cd.original_name LIKE 'cours_genere_%%.txt'
                        THEN 1
                        ELSE 0
                    END
                ) > 0
                THEN 1
                ELSE COUNT(cd.id)
            END AS document_count,
            cf.position
        FROM cours_folders cf
        LEFT JOIN cours_documents cd ON cf.id = cd.folder_id
        WHERE cf.platform_id = {ph}
        GROUP BY cf.id, cf.name, cf.created_at, cf.position
        ORDER BY cf.position ASC, cf.created_at ASC
    """

    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                effective_platform_id = int(platform_id)
                cur.execute(count_query, (platform_id,))
                direct_count = int((cur.fetchone() or {}).get("count") or 0)
                if direct_count == 0:
                    cur.execute(source_query, (platform_id,))
                    source_row = cur.fetchone()
                    if source_row:
                        effective_platform_id = int(source_row["id"])

                cur.execute(folders_query, (effective_platform_id,))
                rows = [dict(row) for row in cur.fetchall()]

        return {
            "folders": [_row_to_folder(row) for row in rows],
            "platform_id": int(platform_id),
            "source_platform_id": effective_platform_id if effective_platform_id != int(platform_id) else None,
        }

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        effective_platform_id = int(platform_id)
        cursor.execute(count_query, (platform_id,))
        direct_count = int((cursor.fetchone() or {"count": 0})["count"] or 0)
        if direct_count == 0:
            cursor.execute(source_query, (platform_id,))
            source_row = cursor.fetchone()
            if source_row:
                effective_platform_id = int(source_row["id"])

        cursor.execute(folders_query, (effective_platform_id,))
        rows = [dict(row) for row in cursor.fetchall()]
        return {
            "folders": [_row_to_folder(row) for row in rows],
            "platform_id": int(platform_id),
            "source_platform_id": effective_platform_id if effective_platform_id != int(platform_id) else None,
        }
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
    source_filter = "source LIKE '%%humanization%%'" if kind == "humanization" else "source NOT LIKE '%%humanization%%'"
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


def get_latest_pipeline_event_created_at(
    *,
    job_id: int,
    folder_id: int,
    event_type: str,
) -> Any | None:
    ensure_pipeline_observability_tables()
    ph = _placeholder()
    query = f"""
        SELECT created_at
        FROM formation_pipeline_events
        WHERE job_id = {ph} AND folder_id = {ph} AND event_type = {ph}
        ORDER BY created_at DESC, id DESC
        LIMIT 1
    """
    params = (job_id, folder_id, event_type)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                return row["created_at"] if row else None

    conn = _as_sqlite_row_connection()
    try:
        row = conn.execute(query, params).fetchone()
        return row["created_at"] if row else None
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
    reset_and_upsert_content_generation_jobs([{
        "folder_id": folder_id,
        "platform_id": platform_id,
        "program_text": program_text,
        "program_title": program_title,
        "sub_parts_json": sub_parts_json,
        "from_scratch": from_scratch,
        "module_contents_json": module_contents_json,
    }])


def reset_and_upsert_content_generation_jobs(jobs: list[dict[str, Any]]) -> None:
    """Reset segments and create/update several content generation jobs in one DB round-trip."""
    if not jobs:
        return

    rows = [
        (
            int(job["folder_id"]),
            int(job["platform_id"]),
            str(job.get("program_text") or ""),
            str(job.get("program_title") or ""),
            str(job.get("sub_parts_json") or "[]"),
            bool(job.get("from_scratch")),
            str(job.get("module_contents_json") or "{}"),
        )
        for job in jobs
    ]
    folder_ids = [row[0] for row in rows]

    if _pipeline_primary_backend() == "postgres":
        def _postgres_operation():
            placeholders = ", ".join(["%s"] * len(folder_ids))
            with get_postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        DELETE FROM content_generation_segments
                        WHERE job_id IN (
                            SELECT id FROM content_generation_jobs
                            WHERE folder_id IN ({placeholders})
                        )
                        """,
                        folder_ids,
                    )
                    cur.executemany(
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
                        rows,
                    )
            return None

        _run_postgres_with_retry("reset_and_upsert_content_generation_jobs", _postgres_operation)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        placeholders = ", ".join(["?"] * len(folder_ids))
        cursor.execute(
            f"""
            DELETE FROM content_generation_segments WHERE job_id IN (
                SELECT id FROM content_generation_jobs WHERE folder_id IN ({placeholders})
            )
            """,
            folder_ids,
        )
        cursor.executemany(
            """
            INSERT OR REPLACE INTO content_generation_jobs
                (folder_id, platform_id, program_text, program_title, sub_parts,
                 from_scratch, module_contents,
                 status, current_sub_part, current_passe, total_words, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'idle', 0, 1, 0, NULL)
            """,
            [
                (
                    folder_id,
                    platform_id,
                    program_text,
                    program_title,
                    sub_parts_json,
                    1 if from_scratch else 0,
                    module_contents_json,
                )
                for (
                    folder_id,
                    platform_id,
                    program_text,
                    program_title,
                    sub_parts_json,
                    from_scratch,
                    module_contents_json,
                ) in rows
            ],
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
    allowed_columns = {
        "status",
        "current_sub_part",
        "current_passe",
        "total_words",
        "error_message",
    }
    unknown_columns = sorted(set(kwargs) - allowed_columns)
    if unknown_columns:
        raise ValueError(
            "Colonnes content_generation_jobs non modifiables: "
            + ", ".join(unknown_columns)
        )
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


def save_completed_content_segments(segments: list[dict[str, Any]]) -> None:
    """Persist a batch of completed segments in one transaction.

    This is used by the test/bootstrap pipeline and avoids opening one remote
    Postgres connection per segment (21 connections per training day before
    this helper existed).
    """
    if not segments:
        return
    rows = [
        (
            int(segment["job_id"]),
            int(segment["sub_part_index"]),
            str(segment["sub_part_name"]),
            int(segment["passe"]),
            str(segment.get("text_content") or ""),
            int(segment.get("word_count") or 0),
        )
        for segment in segments
    ]
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO content_generation_segments
                        (job_id, sub_part_index, sub_part_name, passe, status,
                         text_content, word_count, dirty,
                         humanized, humanization_error, humanization_signature,
                         reviewed, review_error, review_signature)
                    VALUES (%s, %s, %s, %s, 'completed', %s, %s,
                            TRUE, FALSE, NULL, NULL, FALSE, NULL, NULL)
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
                    rows,
                )
        return

    conn = get_db_connection()
    try:
        conn.executemany(
            """
            INSERT OR REPLACE INTO content_generation_segments
                (job_id, sub_part_index, sub_part_name, passe, status,
                 text_content, word_count, dirty,
                 humanized, humanization_error, humanization_signature,
                 reviewed, review_error, review_signature)
            VALUES (?, ?, ?, ?, 'completed', ?, ?, 1, 0, NULL, NULL, 0, NULL, NULL)
            """,
            rows,
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
                   text_content_pre_review,
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
               text_content_pre_review,
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


def list_completed_segment_review_rows_for_folder(
    *,
    formation_job_id: int,
    folder_id: int,
) -> list[dict[str, Any]]:
    """Read the persisted review state without leaking a SQLite connection."""
    ph = _placeholder()
    query = f"""
        SELECT
            cf.name AS folder_name,
            cf.position,
            s.id AS segment_id,
            s.sub_part_index,
            s.passe,
            s.reviewed,
            s.review_error,
            COALESCE(s.text_content, '') AS text_content,
            COALESCE(s.text_content_pre_review, '') AS text_content_pre_review,
            COALESCE(s.word_count, 0) AS word_count
        FROM cours_folders cf
        JOIN content_generation_jobs cj ON cj.folder_id = cf.id
        JOIN content_generation_segments s ON s.job_id = cj.id
        WHERE cf.id = {ph}
          AND cf.formation_job_id = {ph}
          AND s.status = 'completed'
        ORDER BY s.sub_part_index ASC, s.passe ASC
    """
    params = (folder_id, formation_job_id)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]

    conn = _as_sqlite_row_connection()
    try:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
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
          AND (doc_type = 'final_script' OR original_name LIKE 'cours_genere_%%.txt')
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
          AND (doc_type = 'final_script' OR original_name LIKE 'cours_genere_%%.txt')
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
    stale_started_before=None,
    stale_updated_before=None,
    retry_due_before=None,
    max_auto_attempts: int = 4,
) -> list[dict[str, Any]]:
    postgres_schedule = schedule_store_is_postgres()
    ph = "%s" if postgres_schedule else "?"
    params: list[Any] = [lower_bound, upper_bound]
    stale_heartbeat_before = stale_updated_before or stale_started_before
    retry_due_before = retry_due_before or upper_bound
    retry_conditions = f"""
              cs.audio_generation_started_at IS NULL
              OR (
                  COALESCE(cs.audio_generation_status, 'pending') = 'error'
                  AND cs.audio_generation_completed_at IS NULL
                  AND (cs.audio_generation_next_retry_at IS NULL OR cs.audio_generation_next_retry_at <= {ph})
                  AND COALESCE(cs.audio_generation_attempts, 0) < {ph}
              )
    """
    params.extend([retry_due_before, int(max_auto_attempts)])
    if stale_heartbeat_before:
        retry_conditions += f"""
              OR (
                  COALESCE(cs.audio_generation_status, 'pending') IN ('running', 'processing')
                  AND cs.audio_generation_completed_at IS NULL
                  AND COALESCE(cs.updated_at, cs.audio_generation_started_at) <= {ph}
              )
        """
        params.append(stale_heartbeat_before)

    platform_filter = ""
    if platform_ids:
        ids = [int(pid) for pid in platform_ids]
        if postgres_schedule:
            platform_filter = "AND cs.platform_id = ANY(%s)"
            params.append(ids)
        else:
            placeholders = ", ".join(["?"] * len(ids))
            platform_filter = f"AND cs.platform_id IN ({placeholders})"
            params.extend(ids)

    query = f"""
        SELECT
            cs.id,
            cs.platform_id,
            cs.session_index,
            cs.scheduled_at,
            cs.audio_generation_status,
            cs.audio_generation_started_at,
            cs.audio_generation_attempts,
            cs.audio_generation_next_retry_at,
            cs.updated_at,
            pc.name,
            COALESCE(
                pc.source_formation_id,
                fm.source_pipeline_job_id,
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
        LEFT JOIN formation_modules fm ON fm.id = pc.source_module_id
        WHERE cs.status IN ('planned', 'active')
          AND cs.scheduled_at >= {ph}
          AND cs.scheduled_at <= {ph}
          AND (
              {retry_conditions}
          )
          {platform_filter}
        ORDER BY cs.scheduled_at ASC, cs.platform_id ASC
    """
    if postgres_schedule:
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = [dict(row) for row in cur.fetchall()]
    else:
        conn = _as_sqlite_row_connection()
        try:
            from services.course_schedule_service import ensure_course_schedule_tables

            cursor = conn.cursor()
            ensure_course_schedule_tables(cursor)
            cursor.execute(query, params)
            rows = [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    for row in rows:
        if row.get("formation_job_id"):
            continue
        row["formation_job_id"] = find_latest_pipeline_job_id_for_platform(int(row["platform_id"]))

    return rows


def find_latest_pipeline_job_id_for_platform(platform_id: int) -> int | None:
    ph = _placeholder()
    query = f"""
        SELECT id
        FROM formation_pipeline_jobs
        WHERE platform_id = {ph}
        ORDER BY id DESC
        LIMIT 1
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (platform_id,))
                row = cur.fetchone()
                return int(row["id"]) if row else None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, (platform_id,))
        row = cursor.fetchone()
        return int(row["id"]) if row else None
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


def get_course_folder_identity(folder_id: int) -> dict[str, Any] | None:
    """Return the folder/platform identity from the active pipeline storage."""
    ph = _placeholder()
    query = f"""
        SELECT id, platform_id, name, position, formation_job_id
        FROM cours_folders
        WHERE id = {ph}
        LIMIT 1
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


def list_effective_course_documents(folder_id: int) -> list[tuple[int, str, str]]:
    """Return the final script when present, otherwise every source document."""
    ph = _placeholder()
    final_query = f"""
        SELECT id, filename, original_name
        FROM cours_documents
        WHERE folder_id = {ph}
          AND (doc_type = 'final_script' OR original_name LIKE 'cours_genere_%%.txt')
        ORDER BY created_at DESC, id DESC
        LIMIT 1
    """
    source_query = f"""
        SELECT id, filename, original_name
        FROM cours_documents
        WHERE folder_id = {ph}
        ORDER BY id
    """

    def _read(cursor):
        cursor.execute(final_query, (int(folder_id),))
        final_row = cursor.fetchone()
        rows = [final_row] if final_row else None
        if rows is None:
            cursor.execute(source_query, (int(folder_id),))
            rows = cursor.fetchall()
        return [
            (
                int(row["id"]),
                str(row["filename"]),
                str(row["original_name"]),
            )
            if isinstance(row, Mapping)
            else (int(row[0]), str(row[1]), str(row[2]))
            for row in rows
        ]

    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cursor:
                return _read(cursor)

    conn = _as_sqlite_row_connection()
    try:
        return _read(conn.cursor())
    finally:
        conn.close()


def course_folder_belongs_to_job(folder_id: int, job_id: int) -> bool:
    """Return whether ``folder_id`` is durably attached to ``job_id``.

    This narrow predicate is used by the HTTP boundary before any route can
    read text, reports, DOCX data or Blob artifacts for a caller-controlled
    folder identifier.
    """
    ph = _placeholder()
    query = f"""
        SELECT 1
        FROM cours_folders
        WHERE id = {ph} AND formation_job_id = {ph}
        LIMIT 1
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (folder_id, job_id))
                return cur.fetchone() is not None

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, (folder_id, job_id))
        return cursor.fetchone() is not None
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
        def _postgres_operation():
            with get_postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    return [dict(row) for row in cur.fetchall()]

        return _run_postgres_with_retry("list_health_course_folder_rows", _postgres_operation)

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
    if _pipeline_primary_backend() == "postgres":
        reviewed_true = "COALESCE(cgs.reviewed, FALSE) = TRUE"
        reviewed_false = "COALESCE(cgs.reviewed, FALSE) = FALSE"
        humanized_true = "COALESCE(cgs.humanized, FALSE) = TRUE"
        dirty_true = "COALESCE(cgs.dirty, FALSE) = TRUE"
    else:
        reviewed_true = "COALESCE(cgs.reviewed, 0) = 1"
        reviewed_false = "COALESCE(cgs.reviewed, 0) = 0"
        humanized_true = "COALESCE(cgs.humanized, 0) = 1"
        dirty_true = "COALESCE(cgs.dirty, 0) = 1"
    query = f"""
        SELECT
            cf.id AS folder_id,
            cgj.id AS content_job_id,
            cgj.status,
            COALESCE(cgj.total_words, 0) AS total_words,
            cgj.current_sub_part,
            cgj.current_passe,
            cgj.error_message,
            COUNT(cgs.id) AS segments_total,
            COALESCE(SUM(CASE WHEN cgs.status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_segments,
            COALESCE(SUM(CASE WHEN cgs.status = 'completed' AND {reviewed_true} THEN 1 ELSE 0 END), 0) AS reviewed_segments,
            COALESCE(SUM(CASE WHEN cgs.status = 'completed' AND {humanized_true} THEN 1 ELSE 0 END), 0) AS humanized_segments,
            COALESCE(SUM(CASE WHEN cgs.status = 'completed' AND {reviewed_false} AND cgs.review_error IS NOT NULL THEN 1 ELSE 0 END), 0) AS review_error_segments,
            COALESCE(SUM(CASE WHEN cgs.status = 'completed' AND {dirty_true} THEN 1 ELSE 0 END), 0) AS dirty_segments
        FROM cours_folders cf
        LEFT JOIN content_generation_jobs cgj ON cgj.folder_id = cf.id
        LEFT JOIN content_generation_segments cgs ON cgs.job_id = cgj.id
        WHERE cf.id IN ({placeholders})
        GROUP BY cf.id, cgj.id, cgj.status, cgj.total_words,
                 cgj.current_sub_part, cgj.current_passe, cgj.error_message
    """
    if _pipeline_primary_backend() == "postgres":
        def _postgres_operation():
            with get_postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    return [dict(row) for row in cur.fetchall()]

        return _run_postgres_with_retry("list_content_completion_rows_for_folders", _postgres_operation)

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def list_text_folder_states_for_folders(
    folder_ids: list[int],
    *,
    completed_only: bool = False,
) -> list[dict[str, Any]]:
    placeholders, params = _in_clause([int(fid) for fid in folder_ids])
    if not placeholders:
        return []
    having_sql = ""
    if completed_only:
        having_sql = """
        HAVING cgj.status = 'completed'
           AND COALESCE(SUM(CASE WHEN cgs.status = 'completed' THEN 1 ELSE 0 END), 0) > 0
        """
    query = f"""
        SELECT
            cf.id AS folder_id,
            cf.name AS folder_name,
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
        WHERE cf.id IN ({placeholders})
        GROUP BY cf.id, cf.name, cf.position, cf.platform_id, cf.formation_job_id,
                 cgj.id, cgj.status, cgj.total_words
        {having_sql}
        ORDER BY cf.position ASC, cf.id ASC
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


def list_volume_audit_rows_for_folders(folder_ids: list[int]) -> list[dict[str, Any]]:
    """Return completed segment text from the authoritative pipeline store."""
    placeholders, params = _in_clause([int(folder_id) for folder_id in folder_ids])
    if not placeholders:
        return []
    backend = _pipeline_primary_backend()
    logger.info(
        "VOLUME_AUDIT_STORAGE_SELECTED storage=%s folder_count=%s",
        backend,
        len(params),
    )
    query = f"""
        SELECT
            cf.id AS folder_id,
            cf.name AS folder_name,
            cf.position,
            cgs.id AS segment_id,
            cgs.sub_part_index,
            cgs.sub_part_name,
            cgs.passe,
            COALESCE(cgs.text_content, '') AS text_content,
            COALESCE(cgs.word_count, 0) AS word_count
        FROM cours_folders cf
        JOIN content_generation_jobs cgj ON cgj.folder_id = cf.id
        JOIN content_generation_segments cgs ON cgs.job_id = cgj.id
        WHERE cf.id IN ({placeholders})
          AND cgs.status = 'completed'
        ORDER BY cf.position ASC, cf.id ASC,
                 cgs.sub_part_index ASC, cgs.passe ASC
    """
    if backend == "postgres":
        def _postgres_operation():
            with get_postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    return [dict(row) for row in cur.fetchall()]

        return _run_postgres_with_retry(
            "list_volume_audit_rows_for_folders",
            _postgres_operation,
        )

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_text_folder_state(folder_id: int) -> dict[str, Any] | None:
    rows = list_text_folder_states_for_folders([int(folder_id)])
    return rows[0] if rows else None


def claim_single_completed_orphan_folder(
    *,
    formation_job_id: int,
    platform_id: int,
    day_number: int | None = None,
) -> dict[str, Any] | None:
    """Atomically attach the only viable orphan folder to a pipeline job."""
    ph = _placeholder()
    day_filter = f"AND cf.name LIKE {ph}" if day_number is not None else ""
    params: list[Any] = [platform_id]
    if day_number is not None:
        params.append(f"Jour {int(day_number)}%")
    query = f"""
        SELECT
            cf.id AS folder_id,
            cf.name AS folder_name,
            cf.position,
            cf.platform_id,
            cgj.id AS content_job_id,
            cgj.status AS content_status,
            COALESCE(cgj.total_words, 0) AS total_words,
            COALESCE(SUM(CASE WHEN cgs.status = 'completed' THEN 1 ELSE 0 END), 0)
                AS segments_completed
        FROM cours_folders cf
        JOIN content_generation_jobs cgj ON cgj.folder_id = cf.id
        LEFT JOIN content_generation_segments cgs ON cgs.job_id = cgj.id
        WHERE cf.platform_id = {ph}
          AND cf.formation_job_id IS NULL
          {day_filter}
        GROUP BY cf.id, cf.name, cf.position, cf.platform_id,
                 cgj.id, cgj.status, cgj.total_words
        HAVING cgj.status = 'completed'
           AND COALESCE(SUM(CASE WHEN cgs.status = 'completed' THEN 1 ELSE 0 END), 0) > 0
        ORDER BY cf.created_at DESC, cf.id DESC
    """

    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = [dict(row) for row in cur.fetchall()]
                if len(rows) != 1:
                    return None
                row = rows[0]
                cur.execute(
                    """
                    UPDATE cours_folders
                    SET formation_job_id = %s
                    WHERE id = %s AND formation_job_id IS NULL
                    """,
                    (formation_job_id, row["folder_id"]),
                )
                return row if cur.rowcount == 1 else None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = [dict(row) for row in cursor.fetchall()]
        if len(rows) != 1:
            return None
        row = rows[0]
        cursor.execute(
            """
            UPDATE cours_folders
            SET formation_job_id = ?
            WHERE id = ? AND formation_job_id IS NULL
            """,
            (formation_job_id, row["folder_id"]),
        )
        conn.commit()
        return row if cursor.rowcount == 1 else None
    finally:
        conn.close()


def delete_script_slide_decks_for_content_job(folder_id: int, content_job_id: int) -> int:
    ph = _placeholder()
    query = f"DELETE FROM script_slide_decks WHERE folder_id = {ph} AND content_job_id = {ph}"
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (folder_id, content_job_id))
                return int(cur.rowcount or 0)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(query, (folder_id, content_job_id))
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return 0
            raise
        deleted = int(cursor.rowcount or 0)
        conn.commit()
        return deleted
    finally:
        conn.close()


def reset_folder_downstream_state(
    *,
    formation_job_id: int,
    folder_id: int,
) -> dict[str, Any]:
    """Restore pre-review text and clear every downstream persisted artifact."""
    ph = _placeholder()
    identity_query = f"""
        SELECT cf.id AS folder_id, cf.name AS folder_name, cf.position,
               cj.id AS content_job_id, cj.platform_id
        FROM cours_folders cf
        JOIN content_generation_jobs cj ON cj.folder_id = cf.id
        WHERE cf.id = {ph} AND cf.formation_job_id = {ph} AND cj.status = 'completed'
    """
    segments_query = f"""
        SELECT id, COALESCE(text_content, '') AS text_content, text_content_pre_review
        FROM content_generation_segments
        WHERE job_id = {ph} AND status = 'completed'
        ORDER BY sub_part_index ASC, passe ASC
    """

    def _run(cursor, *, postgres: bool) -> dict[str, Any]:
        cursor.execute(identity_query, (folder_id, formation_job_id))
        raw_identity = cursor.fetchone()
        if not raw_identity:
            raise ValueError("Journée introuvable ou texte non généré")
        identity = dict(raw_identity)
        cursor.execute(segments_query, (identity["content_job_id"],))
        segments = [dict(row) for row in cursor.fetchall()]
        if not segments:
            raise ValueError("Aucun segment texte complété pour cette journée")

        update_segment_query = (
            """
            UPDATE content_generation_segments
            SET text_content = %s, word_count = %s, dirty = TRUE,
                humanized = FALSE, humanization_error = NULL, humanization_signature = NULL,
                reviewed = FALSE, review_error = NULL, review_signature = NULL
            WHERE id = %s
            """
            if postgres
            else
            """
            UPDATE content_generation_segments
            SET text_content = ?, word_count = ?, dirty = 1,
                humanized = 0, humanization_error = NULL, humanization_signature = NULL,
                reviewed = 0, review_error = NULL, review_signature = NULL
            WHERE id = ?
            """
        )
        restored = 0
        total_words = 0
        for segment in segments:
            current_text = segment.get("text_content") or ""
            original_text = segment.get("text_content_pre_review")
            base_text = original_text if original_text is not None else current_text
            word_count = len((base_text or "").split())
            total_words += word_count
            if original_text is not None and original_text != current_text:
                restored += 1
            cursor.execute(update_segment_query, (base_text or "", word_count, segment["id"]))

        now_sql = "NOW()" if postgres else "CURRENT_TIMESTAMP"
        cursor.execute(
            f"""
            UPDATE content_generation_jobs
            SET total_words = {ph}, status = 'completed', error_message = NULL,
                updated_at = {now_sql}
            WHERE id = {ph}
            """,
            (total_words, identity["content_job_id"]),
        )
        cursor.execute(
            f"DELETE FROM content_review_reports WHERE job_id = {ph} AND folder_id = {ph}",
            (formation_job_id, folder_id),
        )
        deleted_reports = int(cursor.rowcount or 0)
        cursor.execute(
            f"DELETE FROM script_slide_decks WHERE folder_id = {ph} AND content_job_id = {ph}",
            (folder_id, identity["content_job_id"]),
        )
        deleted_decks = int(cursor.rowcount or 0)
        return {
            **identity,
            "segments": len(segments),
            "segments_restored": restored,
            "total_words": total_words,
            "deleted_review_reports": deleted_reports,
            "deleted_slide_decks": deleted_decks,
        }

    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                return _run(cur, postgres=True)

    conn = _as_sqlite_row_connection()
    try:
        try:
            result = _run(conn.cursor(), postgres=False)
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            ensure_pipeline_observability_tables()
            ensure_script_slide_decks_table()
            result = _run(conn.cursor(), postgres=False)
        conn.commit()
        return result
    finally:
        conn.close()


def get_folder_text_review_readiness(
    *,
    job_id: int,
    folder_id: int,
    review_signature: str,
) -> dict[str, int]:
    if _pipeline_primary_backend() == "postgres":
        reviewed_current_sql = "COALESCE(cgs.reviewed, FALSE) = TRUE AND cgs.review_signature = %s"
    else:
        reviewed_current_sql = "COALESCE(cgs.reviewed, 0) = 1 AND cgs.review_signature = ?"
    ph = _placeholder()
    query = f"""
        SELECT
            COUNT(*) AS segments_completed,
            COALESCE(SUM(CASE WHEN {reviewed_current_sql} THEN 1 ELSE 0 END), 0) AS reviewed_current,
            COALESCE(SUM(CASE WHEN cgs.review_error IS NOT NULL THEN 1 ELSE 0 END), 0) AS review_errors
        FROM content_generation_segments cgs
        JOIN content_generation_jobs cgj ON cgj.id = cgs.job_id
        JOIN cours_folders cf ON cf.id = cgj.folder_id
        WHERE cf.id = {ph} AND cf.formation_job_id = {ph}
          AND cgs.status = 'completed'
    """
    params = (review_signature, folder_id, job_id)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone() or {}
    else:
        conn = _as_sqlite_row_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone() or {}
        finally:
            conn.close()
    return {
        "segments_completed": int(row["segments_completed"] or 0),
        "reviewed_current": int(row["reviewed_current"] or 0),
        "review_errors": int(row["review_errors"] or 0),
    }


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


def finalize_pipeline_module(
    *,
    formation_job_id: int,
    platform_id: int,
    rncp_code: str,
    tp_name: str,
    audio_ready: bool,
    voice_type: str | None = None,
) -> dict[str, Any]:
    """Finalize platform/module state in the pipeline's authoritative DB."""
    year = datetime.now().year

    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT center_account_id, teacher_name, teacher_color "
                    "FROM platform_config WHERE id = %s FOR UPDATE",
                    (platform_id,),
                )
                platform_row = cur.fetchone()
                if not platform_row:
                    raise ValueError(f"Plateforme Postgres introuvable: {platform_id}")
                center_account_id = platform_row["center_account_id"]
                teacher_name = platform_row.get("teacher_name")
                teacher_color = platform_row.get("teacher_color")
                cur.execute(
                    "UPDATE platform_config SET status = 'ready', updated_at = NOW() WHERE id = %s",
                    (platform_id,),
                )
                platform_ready_updated = int(cur.rowcount or 0)
                cur.execute(
                    """
                    SELECT id, version, status
                    FROM formation_modules
                    WHERE source_pipeline_job_id = %s
                    FOR UPDATE
                    """,
                    (formation_job_id,),
                )
                existing = cur.fetchone()

                desired_status = "validated" if audio_ready else "draft"
                if existing:
                    module_id = int(existing["id"])
                    version = existing["version"]
                    module_status = (
                        "validated"
                        if audio_ready or existing["status"] == "validated"
                        else "draft"
                    )
                    cur.execute(
                        """
                        UPDATE formation_modules
                        SET source_platform_id = COALESCE(source_platform_id, %s),
                            center_account_id = COALESCE(center_account_id, %s),
                            status = %s,
                            voice_type = CASE WHEN %s THEN %s ELSE voice_type END,
                            voice_updated_at = CASE WHEN %s THEN NOW() ELSE voice_updated_at END,
                            validated_at = CASE
                                WHEN %s THEN COALESCE(validated_at, NOW())
                                ELSE validated_at
                            END
                        WHERE id = %s
                        """,
                        (
                            platform_id,
                            center_account_id,
                            module_status,
                            audio_ready,
                            voice_type,
                            audio_ready,
                            audio_ready,
                            module_id,
                        ),
                    )
                    module_created = False
                else:
                    lock_key = f"pipeline-module:{center_account_id or 0}:{rncp_code or tp_name}"
                    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock_key,))
                    cur.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM formation_modules
                        WHERE rncp_code = %s
                          AND center_account_id IS NOT DISTINCT FROM %s
                        """,
                        (rncp_code, center_account_id),
                    )
                    version = f"{year}-v{int(cur.fetchone()['count']) + 1}"
                    cur.execute(
                        """
                        INSERT INTO formation_modules (
                            rncp_code, tp_name, version, status,
                            source_pipeline_job_id, source_platform_id,
                            center_account_id, voice_type, voice_updated_at, validated_at
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s,
                            CASE WHEN %s THEN %s ELSE NULL END,
                            CASE WHEN %s THEN NOW() ELSE NULL END,
                            CASE WHEN %s THEN NOW() ELSE NULL END
                        )
                        ON CONFLICT (source_pipeline_job_id) DO UPDATE SET
                            source_platform_id = COALESCE(formation_modules.source_platform_id, EXCLUDED.source_platform_id),
                            center_account_id = COALESCE(formation_modules.center_account_id, EXCLUDED.center_account_id),
                            status = CASE
                                WHEN EXCLUDED.status = 'validated' THEN 'validated'
                                ELSE formation_modules.status
                            END,
                            voice_type = COALESCE(EXCLUDED.voice_type, formation_modules.voice_type),
                            voice_updated_at = COALESCE(EXCLUDED.voice_updated_at, formation_modules.voice_updated_at),
                            validated_at = COALESCE(EXCLUDED.validated_at, formation_modules.validated_at)
                        RETURNING id, version, status, (xmax = 0) AS created
                        """,
                        (
                            rncp_code,
                            tp_name,
                            version,
                            desired_status,
                            formation_job_id,
                            platform_id,
                            center_account_id,
                            audio_ready,
                            voice_type,
                            audio_ready,
                            audio_ready,
                        ),
                    )
                    inserted = cur.fetchone()
                    module_id = int(inserted["id"])
                    version = inserted["version"]
                    module_status = inserted["status"]
                    module_created = bool(inserted["created"])

                cur.execute(
                    """
                    UPDATE formation_modules
                    SET teacher_name = COALESCE(teacher_name, %s),
                        teacher_color = COALESCE(teacher_color, %s),
                        asset_namespace = COALESCE(
                            asset_namespace,
                            'centres/' || COALESCE(center_account_id, 0)::text
                                || '/modules/' || id::text
                                || '/versions/' || version
                        ),
                        immutable = TRUE
                    WHERE id = %s
                    """,
                    (teacher_name, teacher_color, module_id),
                )

                result = {
                    "platform_id": platform_id,
                    "platform_ready_updated": platform_ready_updated,
                    "module_id": module_id,
                    "module_created": module_created,
                    "module_version": version,
                    "module_status": module_status,
                    "voice_type": voice_type if audio_ready else None,
                }

        if _sqlite_pipeline_mirror_required():
            mirror_conn = None
            try:
                mirror_conn = get_db_connection()
                mirror_conn.execute(
                    "UPDATE platform_config SET status = 'ready' WHERE id = ?",
                    (platform_id,),
                )
                mirror_conn.commit()
            except Exception:
                logger.warning(
                    "PIPELINE_FINALIZE_SQLITE_MIRROR_FAILED platform_id=%s",
                    platform_id,
                    exc_info=True,
                )
            finally:
                if mirror_conn is not None:
                    mirror_conn.close()
        return result

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT center_account_id, teacher_name, teacher_color FROM platform_config WHERE id = ?",
            (platform_id,),
        )
        platform_row = cursor.fetchone()
        if not platform_row:
            raise ValueError(f"Plateforme SQLite introuvable: {platform_id}")
        center_account_id = platform_row[0]
        teacher_name = platform_row[1] if len(platform_row) > 1 else None
        teacher_color = platform_row[2] if len(platform_row) > 2 else None
        cursor.execute("UPDATE platform_config SET status = 'ready' WHERE id = ?", (platform_id,))
        platform_ready_updated = int(cursor.rowcount or 0)
        cursor.execute(
            "SELECT id, version, status FROM formation_modules WHERE source_pipeline_job_id = ?",
            (formation_job_id,),
        )
        existing = cursor.fetchone()
        desired_status = "validated" if audio_ready else "draft"
        if existing:
            module_id, version, existing_status = existing
            module_status = "validated" if audio_ready or existing_status == "validated" else "draft"
            cursor.execute(
                """
                UPDATE formation_modules
                SET source_platform_id = COALESCE(source_platform_id, ?),
                    center_account_id = COALESCE(center_account_id, ?),
                    status = ?,
                    voice_type = CASE WHEN ? THEN ? ELSE voice_type END,
                    voice_updated_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE voice_updated_at END,
                    validated_at = CASE
                        WHEN ? THEN COALESCE(validated_at, CURRENT_TIMESTAMP)
                        ELSE validated_at
                    END
                WHERE id = ?
                """,
                (
                    platform_id,
                    center_account_id,
                    module_status,
                    1 if audio_ready else 0,
                    voice_type,
                    1 if audio_ready else 0,
                    1 if audio_ready else 0,
                    module_id,
                ),
            )
            module_created = False
        else:
            if center_account_id is None:
                cursor.execute(
                    "SELECT COUNT(*) FROM formation_modules WHERE rncp_code = ? AND center_account_id IS NULL",
                    (rncp_code,),
                )
            else:
                cursor.execute(
                    "SELECT COUNT(*) FROM formation_modules WHERE rncp_code = ? AND center_account_id = ?",
                    (rncp_code, center_account_id),
                )
            version = f"{year}-v{int(cursor.fetchone()[0]) + 1}"
            cursor.execute(
                """
                INSERT INTO formation_modules (
                    rncp_code, tp_name, version, status, source_pipeline_job_id,
                    source_platform_id, center_account_id, voice_type,
                    voice_updated_at, validated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                        CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,
                        CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END)
                """,
                (
                    rncp_code,
                    tp_name,
                    version,
                    desired_status,
                    formation_job_id,
                    platform_id,
                    center_account_id,
                    voice_type if audio_ready else None,
                    1 if audio_ready else 0,
                    1 if audio_ready else 0,
                ),
            )
            module_id = int(cursor.lastrowid)
            module_status = desired_status
            module_created = True
        cursor.execute(
            """
            UPDATE formation_modules
            SET teacher_name = COALESCE(teacher_name, ?),
                teacher_color = COALESCE(teacher_color, ?),
                asset_namespace = COALESCE(
                    asset_namespace,
                    'centres/' || COALESCE(center_account_id, 0)
                        || '/modules/' || id || '/versions/' || version
                ),
                immutable = 1
            WHERE id = ?
            """,
            (teacher_name, teacher_color, module_id),
        )
        conn.commit()
        return {
            "platform_id": platform_id,
            "platform_ready_updated": platform_ready_updated,
            "module_id": int(module_id),
            "module_created": module_created,
            "module_version": version,
            "module_status": module_status,
            "voice_type": voice_type if audio_ready else None,
        }
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


def update_script_rules_markdown_path(*, folder_id: int, job_id: int, markdown_path: str) -> None:
    ensure_script_rules_table()
    ph = _placeholder()
    query = f"""
        UPDATE content_script_rules
        SET markdown_path = {ph}, updated_at = CURRENT_TIMESTAMP
        WHERE folder_id = {ph} AND job_id = {ph}
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


def release_auto_pilot_lock(job_id: int, *, owner: str | None = None) -> bool:
    """Release a runner lock without letting a stale worker unlock its successor.

    ``owner`` is optional only for backwards-compatible maintenance calls. The
    production runner always supplies its unique fencing token.
    """
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                owner_clause = " AND auto_pilot_lock_owner = %s" if owner is not None else ""
                params = (job_id, owner) if owner is not None else (job_id,)
                cur.execute(
                    f"""
                    UPDATE formation_pipeline_jobs
                    SET auto_pilot_locked_at = NULL,
                        auto_pilot_lock_owner = NULL
                    WHERE id = %s{owner_clause}
                    """,
                    params,
                )
                return cur.rowcount == 1

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        owner_clause = " AND auto_pilot_lock_owner = ?" if owner is not None else ""
        params = (job_id, owner) if owner is not None else (job_id,)
        cursor.execute(
            f"""
            UPDATE formation_pipeline_jobs
            SET auto_pilot_locked_at = NULL, auto_pilot_lock_owner = NULL
            WHERE id = ?{owner_clause}
            """,
            params,
        )
        released = cursor.rowcount == 1
        conn.commit()
        return released
    finally:
        conn.close()


def refresh_auto_pilot_lock(job_id: int, *, owner: str) -> bool:
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
                return cur.rowcount == 1

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
        refreshed = cursor.rowcount == 1
        conn.commit()
        return refreshed
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


def pipeline_job_belongs_to_center(job_id: int, center_account_id: int) -> bool:
    """Vérifie l'appartenance tenant d'un job via sa plateforme.

    L'INNER JOIN est intentionnel : un job orphelin, une plateforme sans centre
    ou une erreur de correspondance sont tous refusés. Ce helper est réservé à
    la frontière HTTP ; les workers internes conservent leurs helpers non
    scopés afin de pouvoir reprendre les jobs de tous les tenants.
    """
    ph = _placeholder()
    query = f"""
        SELECT 1
        FROM formation_pipeline_jobs j
        JOIN platform_config p ON p.id = j.platform_id
        WHERE j.id = {ph}
          AND p.center_account_id = {ph}
        LIMIT 1
    """
    params = (job_id, center_account_id)
    if _pipeline_primary_backend() == "postgres":
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchone() is not None

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone() is not None
    finally:
        conn.close()


def hr_resource_belongs_to_center(
    resource_type: str,
    resource_id: int,
    center_account_id: int,
) -> bool:
    """Resolve an HR resource through its authoritative tenant ownership.

    HTTP routes often receive an indirect identifier (folder, document or
    deletion request) rather than a platform id.  Authorising only the path's
    direct ids makes it possible for one training centre to operate on another
    centre's resource.  These static JOINs always resolve the resource back to
    ``platform_config.center_account_id`` in the active pipeline store.

    Catalogue modules can exist without a source platform, so their own
    non-null ``center_account_id`` is authoritative; when a source platform is
    present its tenant must also match. Unknown resource types and malformed
    ids fail closed.
    """
    if isinstance(resource_id, bool) or isinstance(center_account_id, bool):
        return False
    try:
        resource_id = int(resource_id)
        center_account_id = int(center_account_id)
    except (TypeError, ValueError):
        return False
    if resource_id <= 0 or center_account_id <= 0:
        return False

    ph = _placeholder()
    queries = {
        "platform": f"""
            SELECT 1
            FROM platform_config p
            WHERE p.id = {ph}
              AND p.center_account_id = {ph}
            LIMIT 1
        """,
        "folder": f"""
            SELECT 1
            FROM cours_folders r
            JOIN platform_config p ON p.id = r.platform_id
            WHERE r.id = {ph}
              AND p.center_account_id = {ph}
            LIMIT 1
        """,
        "document": f"""
            SELECT 1
            FROM cours_documents r
            JOIN cours_folders f ON f.id = r.folder_id
            JOIN platform_config p ON p.id = f.platform_id
            WHERE r.id = {ph}
              AND p.center_account_id = {ph}
            LIMIT 1
        """,
        "deletion_request": f"""
            SELECT 1
            FROM deletion_requests r
            JOIN platform_config p ON p.id = r.platform_id
            WHERE r.id = {ph}
              AND p.center_account_id = {ph}
            LIMIT 1
        """,
        "module": f"""
            SELECT 1
            FROM formation_modules r
            LEFT JOIN platform_config p ON p.id = r.source_platform_id
            WHERE r.id = {ph}
              AND r.center_account_id = {ph}
              AND (
                    r.source_platform_id IS NULL
                    OR p.center_account_id = r.center_account_id
                  )
            LIMIT 1
        """,
    }
    query = queries.get(str(resource_type or "").strip().lower())
    if not query:
        return False
    params = (resource_id, center_account_id)

    if _pipeline_primary_backend() == "postgres":
        def _postgres_operation():
            with get_postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    return cur.fetchone() is not None

        return bool(_run_postgres_with_retry("hr_resource_belongs_to_center", _postgres_operation))

    conn = _as_sqlite_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone() is not None
    finally:
        conn.close()


def list_pipeline_jobs(
    platform_id: int | None = None,
    *,
    center_account_id: int | None = None,
) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params_list: list[Any] = []
    ph = _placeholder()
    if platform_id is not None:
        conditions.append(f"j.platform_id = {ph}")
        params_list.append(platform_id)
    if center_account_id is not None:
        conditions.append(f"p.center_account_id = {ph}")
        params_list.append(center_account_id)
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params = tuple(params_list)
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
