"""Tenant-scoped persistence for reusable day schedules and module snapshots.

The library template is mutable only until its first use.  A durable formation
module never reads a live template: ``formation_module_days`` stores the exact
ordered block list that was locked for each pedagogical day.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import math
import re
import sqlite3
from typing import Any, Iterable, Mapping

from config import DATABASE_BACKEND, FRANCE_TZ, PIPELINE_DATABASE_BACKEND
from database.db import get_db_connection
from database.postgres import get_postgres_connection


POSTGRES_BACKENDS = {
    "postgres",
    "postgresql",
    "supabase",
}
ALLOWED_BLOCK_TYPES = {"course", "qa", "pause"}
ALLOWED_PAUSE_KINDS = {"short", "lunch"}
DEFAULT_SCHEMA_VERSION = 2
_CLOCK_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class DayScheduleError(RuntimeError):
    """Base error for day schedule persistence."""


class TemplateImmutableError(DayScheduleError):
    """Raised when code attempts to edit a template that has already been used."""


class ImmutableModuleScheduleError(DayScheduleError):
    """Raised when code attempts to replace a durable module-day snapshot."""


class ImmutablePipelineScheduleError(DayScheduleError):
    """Raised when code attempts to replace a locked pipeline snapshot."""


def day_schedule_store_is_postgres() -> bool:
    """Keep schedule V2 in Postgres whenever either business store uses it."""
    return (
        DATABASE_BACKEND in POSTGRES_BACKENDS
        or PIPELINE_DATABASE_BACKEND in POSTGRES_BACKENDS
    )


def _positive_id(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} invalide")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} invalide") from exc
    if normalized <= 0:
        raise ValueError(f"{label} invalide")
    return normalized


def _now() -> datetime:
    return datetime.now(FRANCE_TZ)


def _db_datetime(value: datetime, *, postgres: bool):
    if postgres:
        return value
    if value.tzinfo is not None:
        value = value.astimezone(FRANCE_TZ).replace(tzinfo=None)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _row_dict(row) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _decode_json(value: Any, fallback):
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _minute_from_clock(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} invalide")
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or int(value) != value:
            raise ValueError(f"{label} doit utiliser la minute entière")
        minute = int(value)
    elif isinstance(value, str) and _CLOCK_RE.fullmatch(value):
        try:
            hours, minutes = value.strip().split(":", 1)
            minute = int(hours) * 60 + int(minutes)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} invalide") from exc
    else:
        raise ValueError(f"{label} invalide")
    if minute < 0 or minute > 24 * 60:
        raise ValueError(f"{label} doit être compris entre 0 et 1440")
    return minute


def _canonicalize_blocks(
    blocks: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(blocks, (str, bytes, Mapping)):
        raise ValueError("blocks doit être une liste")
    normalized: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for index, raw in enumerate(blocks):
        if not isinstance(raw, Mapping):
            raise ValueError(f"Bloc {index + 1} invalide")
        position_value = raw.get("position", index + 1)
        if (
            isinstance(position_value, bool)
            or not isinstance(position_value, (int, float))
            or not math.isfinite(position_value)
            or int(position_value) != position_value
        ):
            raise ValueError("La position d'un bloc doit être un entier")
        position = int(position_value)
        if position != index + 1:
            raise ValueError("Les positions des blocs doivent être continues et ordonnées")

        block_type = str(raw.get("block_type") or raw.get("type") or "").strip().lower()
        if block_type not in ALLOWED_BLOCK_TYPES:
            raise ValueError(f"Type de bloc invalide : {block_type or '(vide)'}")

        pause_kind = raw.get("pause_kind", raw.get("subtype"))
        if pause_kind is None and raw.get("is_lunch") is True:
            pause_kind = "lunch"
        pause_kind = str(pause_kind).strip().lower() if pause_kind else None
        if block_type == "pause":
            pause_kind = pause_kind or "short"
            if pause_kind not in ALLOWED_PAUSE_KINDS:
                raise ValueError(f"Type de pause invalide : {pause_kind}")
        elif pause_kind is not None:
            raise ValueError("pause_kind est réservé aux blocs pause")

        start_value = raw.get(
            "start_minute",
            raw.get("startMinute", raw.get("start_time", raw.get("startTime"))),
        )
        end_value = raw.get(
            "end_minute",
            raw.get("endMinute", raw.get("end_time", raw.get("endTime"))),
        )
        duration_value = raw.get(
            "duration_minutes",
            raw.get("durationMinutes", raw.get("duration_min")),
        )
        if start_value is None:
            raise ValueError(f"Bloc {index + 1}: heure de début absente")
        start_minute = _minute_from_clock(start_value, "Heure de début")
        if start_minute >= 24 * 60:
            raise ValueError(f"Bloc {index + 1}: heure de début invalide")
        if end_value is None and duration_value is None:
            raise ValueError(f"Bloc {index + 1}: heure de fin absente")
        if end_value is None:
            if (
                isinstance(duration_value, bool)
                or not isinstance(duration_value, (int, float))
                or not math.isfinite(duration_value)
                or int(duration_value) != duration_value
            ):
                raise ValueError(f"Bloc {index + 1}: durée invalide")
            duration_minutes = int(duration_value)
            end_minute = start_minute + duration_minutes
        else:
            end_minute = _minute_from_clock(end_value, "Heure de fin")
            duration_minutes = end_minute - start_minute
            if duration_value is not None:
                if (
                    isinstance(duration_value, bool)
                    or not isinstance(duration_value, (int, float))
                    or not math.isfinite(duration_value)
                    or int(duration_value) != duration_value
                ):
                    raise ValueError(f"Bloc {index + 1}: durée invalide")
                if int(duration_value) != duration_minutes:
                    raise ValueError(f"Bloc {index + 1}: durée incohérente")
        if duration_minutes <= 0 or end_minute > 24 * 60:
            raise ValueError(f"Bloc {index + 1}: durée invalide")

        block_key = str(
            raw.get("block_key") or raw.get("blockKey") or f"block-{index + 1}"
        ).strip()
        if not block_key or block_key in seen_keys:
            raise ValueError("Les identifiants de blocs doivent être uniques")
        seen_keys.add(block_key)

        metadata = raw.get("metadata") or _decode_json(raw.get("metadata_json"), {})
        if not isinstance(metadata, Mapping):
            raise ValueError(f"Bloc {index + 1}: metadata invalide")
        normalized.append(
            {
                "block_key": block_key,
                "position": position,
                "block_type": block_type,
                "pause_kind": pause_kind,
                "start_minute": start_minute,
                "end_minute": end_minute,
                "duration_minutes": duration_minutes,
                "metadata": dict(metadata),
            }
        )
    if not normalized:
        raise ValueError("Un template doit contenir au moins un bloc")
    return normalized


def _validated_canonical_blocks(
    blocks: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Apply the complete V2 domain contract before persistence or playback."""
    from services.dynamic_day_schedule_service import compile_day_schedule

    normalized = _canonicalize_blocks(blocks)
    compiled = compile_day_schedule({"blocks": normalized})
    # Keep the repository's compact storage shape while retaining deterministic
    # keys/positions produced by the domain compiler.
    return _canonicalize_blocks(compiled["blocks"])


def _block_metrics(blocks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "block_count": len(blocks),
        "total_duration_minutes": sum(block["duration_minutes"] for block in blocks),
        "course_duration_minutes": sum(
            block["duration_minutes"]
            for block in blocks
            if block["block_type"] == "course"
        ),
    }


@contextmanager
def _connection():
    postgres = day_schedule_store_is_postgres()
    if postgres:
        with get_postgres_connection() as conn:
            yield conn, True
        return

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    try:
        yield conn, False
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _fetch_blocks(cursor, template_id: int, *, postgres: bool) -> list[dict[str, Any]]:
    ph = "%s" if postgres else "?"
    cursor.execute(
        f"""
        SELECT id, block_key, position, block_type, pause_kind,
               start_minute, end_minute, duration_minutes, metadata_json
        FROM day_schedule_template_blocks
        WHERE template_id = {ph}
        ORDER BY position ASC
        """,
        (template_id,),
    )
    blocks = []
    for row in cursor.fetchall():
        block = dict(row)
        block["metadata"] = _decode_json(block.get("metadata_json"), {})
        blocks.append(block)
    return blocks


def _hydrate_template(cursor, row, *, postgres: bool) -> dict[str, Any] | None:
    template = _row_dict(row)
    if template is None:
        return None
    template["blocks_snapshot_json"] = _decode_json(
        template.get("blocks_snapshot_json"),
        [],
    )
    template["blocks"] = _fetch_blocks(
        cursor,
        int(template["id"]),
        postgres=postgres,
    )
    return template


def _select_template(
    cursor,
    center_account_id: int,
    template_id: int,
    *,
    postgres: bool,
    include_deleted: bool,
    for_update: bool = False,
):
    ph = "%s" if postgres else "?"
    status_clause = "" if include_deleted else "AND status = 'active'"
    lock_clause = "FOR UPDATE" if postgres and for_update else ""
    cursor.execute(
        f"""
        SELECT *
        FROM day_schedule_templates
        WHERE id = {ph}
          AND center_account_id = {ph}
          {status_clause}
        {lock_clause}
        """,
        (template_id, center_account_id),
    )
    return cursor.fetchone()


def _insert_blocks(
    cursor,
    template_id: int,
    blocks: list[dict[str, Any]],
    *,
    postgres: bool,
    created_at,
) -> None:
    if postgres:
        cursor.executemany(
            """
            INSERT INTO day_schedule_template_blocks (
                template_id, block_key, position, block_type, pause_kind,
                start_minute, end_minute, duration_minutes, metadata_json,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            """,
            [
                (
                    template_id,
                    block["block_key"],
                    block["position"],
                    block["block_type"],
                    block["pause_kind"],
                    block["start_minute"],
                    block["end_minute"],
                    block["duration_minutes"],
                    _canonical_json(block["metadata"]),
                    created_at,
                )
                for block in blocks
            ],
        )
        return
    cursor.executemany(
        """
        INSERT INTO day_schedule_template_blocks (
            template_id, block_key, position, block_type, pause_kind,
            start_minute, end_minute, duration_minutes, metadata_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                template_id,
                block["block_key"],
                block["position"],
                block["block_type"],
                block["pause_kind"],
                block["start_minute"],
                block["end_minute"],
                block["duration_minutes"],
                _canonical_json(block["metadata"]),
                created_at,
            )
            for block in blocks
        ],
    )


def list_templates(
    center_account_id: int,
    *,
    include_deleted: bool = False,
) -> list[dict[str, Any]]:
    center_account_id = _positive_id(center_account_id, "center_account_id")
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        ph = "%s" if postgres else "?"
        status_clause = "" if include_deleted else "AND status = 'active'"
        cursor.execute(
            f"""
            SELECT *
            FROM day_schedule_templates
            WHERE center_account_id = {ph}
              {status_clause}
            ORDER BY updated_at DESC, id DESC
            """,
            (center_account_id,),
        )
        return [
            _hydrate_template(cursor, row, postgres=postgres)
            for row in cursor.fetchall()
        ]


def get_template(
    center_account_id: int,
    template_id: int,
    *,
    include_deleted: bool = False,
) -> dict[str, Any] | None:
    center_account_id = _positive_id(center_account_id, "center_account_id")
    template_id = _positive_id(template_id, "template_id")
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        row = _select_template(
            cursor,
            center_account_id,
            template_id,
            postgres=postgres,
            include_deleted=include_deleted,
        )
        return _hydrate_template(cursor, row, postgres=postgres)


def create_template(
    center_account_id: int,
    name: str,
    blocks: Iterable[Mapping[str, Any]],
    *,
    schedule_schema_version: int = DEFAULT_SCHEMA_VERSION,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    center_account_id = _positive_id(center_account_id, "center_account_id")
    name = str(name or "").strip()
    if not name:
        raise ValueError("Le nom du template est obligatoire")
    if len(name) > 160:
        raise ValueError("Le nom du template est trop long")
    schedule_schema_version = int(schedule_schema_version)
    if schedule_schema_version < 2:
        raise ValueError("Un nouveau template doit utiliser le schéma V2")
    normalized_blocks = _validated_canonical_blocks(blocks)
    snapshot_json = _canonical_json(normalized_blocks)
    blocks_hash = _sha256_json(normalized_blocks)
    metrics = _block_metrics(normalized_blocks)
    created_at = created_at or _now()

    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        db_now = _db_datetime(created_at, postgres=postgres)
        params = (
            center_account_id,
            name,
            schedule_schema_version,
            snapshot_json,
            blocks_hash,
            metrics["block_count"],
            metrics["total_duration_minutes"],
            metrics["course_duration_minutes"],
            db_now,
            db_now,
        )
        if postgres:
            cursor.execute(
                """
                INSERT INTO day_schedule_templates (
                    center_account_id, name, schedule_schema_version,
                    blocks_snapshot_json, blocks_hash, block_count,
                    total_duration_minutes, course_duration_minutes,
                    created_at, updated_at
                )
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                params,
            )
            row = cursor.fetchone()
            template_id = int(row["id"])
        else:
            cursor.execute(
                """
                INSERT INTO day_schedule_templates (
                    center_account_id, name, schedule_schema_version,
                    blocks_snapshot_json, blocks_hash, block_count,
                    total_duration_minutes, course_duration_minutes,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
            template_id = int(cursor.lastrowid)
        _insert_blocks(
            cursor,
            template_id,
            normalized_blocks,
            postgres=postgres,
            created_at=db_now,
        )
        row = _select_template(
            cursor,
            center_account_id,
            template_id,
            postgres=postgres,
            include_deleted=True,
        )
        return _hydrate_template(cursor, row, postgres=postgres)


def update_template(
    center_account_id: int,
    template_id: int,
    *,
    name: str | None = None,
    blocks: Iterable[Mapping[str, Any]] | None = None,
    updated_at: datetime | None = None,
) -> dict[str, Any] | None:
    center_account_id = _positive_id(center_account_id, "center_account_id")
    template_id = _positive_id(template_id, "template_id")
    updated_at = updated_at or _now()
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        existing_row = _select_template(
            cursor,
            center_account_id,
            template_id,
            postgres=postgres,
            include_deleted=True,
            for_update=True,
        )
        existing = _row_dict(existing_row)
        if existing is None:
            return None
        if existing["status"] != "active":
            raise ValueError("Un template supprimé ne peut plus être modifié")
        if existing.get("used_at") is not None or existing.get("locked_at") is not None:
            raise TemplateImmutableError(
                "Ce template a déjà été utilisé et ne peut plus être modifié"
            )

        next_name = existing["name"] if name is None else str(name).strip()
        if not next_name:
            raise ValueError("Le nom du template est obligatoire")
        if len(next_name) > 160:
            raise ValueError("Le nom du template est trop long")
        next_blocks = (
            _decode_json(existing.get("blocks_snapshot_json"), [])
            if blocks is None
            else _validated_canonical_blocks(blocks)
        )
        snapshot_json = _canonical_json(next_blocks)
        blocks_hash = _sha256_json(next_blocks)
        metrics = _block_metrics(next_blocks)
        db_now = _db_datetime(updated_at, postgres=postgres)
        ph = "%s" if postgres else "?"
        json_value = f"{ph}::jsonb" if postgres else ph
        cursor.execute(
            f"""
            UPDATE day_schedule_templates
            SET name = {ph},
                blocks_snapshot_json = {json_value},
                blocks_hash = {ph},
                block_count = {ph},
                total_duration_minutes = {ph},
                course_duration_minutes = {ph},
                updated_at = {ph}
            WHERE id = {ph}
              AND center_account_id = {ph}
              AND status = 'active'
              AND used_at IS NULL
              AND locked_at IS NULL
            """,
            (
                next_name,
                snapshot_json,
                blocks_hash,
                metrics["block_count"],
                metrics["total_duration_minutes"],
                metrics["course_duration_minutes"],
                db_now,
                template_id,
                center_account_id,
            ),
        )
        if cursor.rowcount != 1:
            raise TemplateImmutableError(
                "Le template a été verrouillé pendant la modification"
            )
        if blocks is not None:
            cursor.execute(
                f"DELETE FROM day_schedule_template_blocks WHERE template_id = {ph}",
                (template_id,),
            )
            _insert_blocks(
                cursor,
                template_id,
                next_blocks,
                postgres=postgres,
                created_at=db_now,
            )
        row = _select_template(
            cursor,
            center_account_id,
            template_id,
            postgres=postgres,
            include_deleted=True,
        )
        return _hydrate_template(cursor, row, postgres=postgres)


def mark_template_used(
    center_account_id: int,
    template_id: int,
    *,
    expected_blocks_hash: str | None = None,
    used_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Idempotently freeze a template at its first assignment to a formation."""
    center_account_id = _positive_id(center_account_id, "center_account_id")
    template_id = _positive_id(template_id, "template_id")
    expected_blocks_hash = str(expected_blocks_hash or "").strip() or None
    used_at = used_at or _now()
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        ph = "%s" if postgres else "?"
        hash_clause = (
            f"AND blocks_hash = {ph}"
            if expected_blocks_hash is not None
            else ""
        )
        db_now = _db_datetime(used_at, postgres=postgres)
        cursor.execute(
            f"""
            UPDATE day_schedule_templates
            SET used_at = COALESCE(used_at, {ph}),
                locked_at = COALESCE(locked_at, {ph}),
                updated_at = CASE
                    WHEN locked_at IS NULL THEN {ph}
                    ELSE updated_at
                END
            WHERE id = {ph}
              AND center_account_id = {ph}
              AND status = 'active'
              {hash_clause}
            """,
            (
                db_now,
                db_now,
                db_now,
                template_id,
                center_account_id,
                *(
                    (expected_blocks_hash,)
                    if expected_blocks_hash is not None
                    else ()
                ),
            ),
        )
        if cursor.rowcount != 1:
            return None
        row = _select_template(
            cursor,
            center_account_id,
            template_id,
            postgres=postgres,
            include_deleted=True,
        )
        return _hydrate_template(cursor, row, postgres=postgres)


def soft_delete_template(
    center_account_id: int,
    template_id: int,
    *,
    deleted_at: datetime | None = None,
) -> bool:
    """Hide a template without removing blocks or durable module snapshots."""
    center_account_id = _positive_id(center_account_id, "center_account_id")
    template_id = _positive_id(template_id, "template_id")
    deleted_at = deleted_at or _now()
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        ph = "%s" if postgres else "?"
        db_now = _db_datetime(deleted_at, postgres=postgres)
        cursor.execute(
            f"""
            UPDATE day_schedule_templates
            SET status = 'deleted',
                deleted_at = COALESCE(deleted_at, {ph}),
                updated_at = {ph}
            WHERE id = {ph}
              AND center_account_id = {ph}
            """,
            (db_now, db_now, template_id, center_account_id),
        )
        return cursor.rowcount == 1


def _canonical_pipeline_snapshot(
    snapshot: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    if not isinstance(snapshot, Mapping):
        raise ValueError("Le snapshot de planning doit être un objet")
    normalized = _decode_json(_canonical_json(snapshot), {})
    if int(normalized.get("schema_version") or 0) != DEFAULT_SCHEMA_VERSION:
        raise ValueError("Le snapshot doit utiliser schedule schema_version=2")
    raw_days = normalized.get("days")
    if not isinstance(raw_days, list) or not raw_days:
        raise ValueError("Le snapshot doit contenir une liste days non vide")

    hash_days: list[dict[str, Any]] = []
    for offset, day in enumerate(raw_days, start=1):
        if not isinstance(day, dict):
            raise ValueError(f"Journée {offset} invalide")
        day_index = int(day.get("day_index", day.get("day_number", offset)))
        if day_index != offset:
            raise ValueError("Les journées du snapshot doivent être ordonnées")
        blocks = _validated_canonical_blocks(day.get("blocks") or [])
        day["day_index"] = day_index
        day["blocks"] = blocks
        hash_days.append({"blocks": blocks})

    expected_hash = _module_schedule_fingerprint(hash_days)
    provided_hash = str(normalized.get("schedule_hash") or "").strip()
    if not provided_hash:
        raise ValueError("Le snapshot canonique doit contenir schedule_hash")
    if provided_hash != expected_hash:
        raise ValueError("Le schedule_hash ne correspond pas aux journées")
    if normalized.get("day_count") not in (None, len(raw_days)):
        raise ValueError("day_count ne correspond pas à la liste days")
    normalized["day_count"] = len(raw_days)
    return normalized, expected_hash


def _hydrate_pipeline_schedule(row) -> dict[str, Any] | None:
    result = _row_dict(row)
    if result is None:
        return None
    snapshot = _decode_json(
        result.get("schedule_snapshot_json"),
        {},
    )
    result["schedule_snapshot_json"] = snapshot
    if int(result.get("schedule_schema_version") or 1) != DEFAULT_SCHEMA_VERSION:
        return result
    if result.get("schedule_locked_at") in (None, ""):
        raise ImmutablePipelineScheduleError(
            "Le snapshot V2 du pipeline n'est pas verrouillé"
        )
    try:
        canonical_snapshot, expected_hash = _canonical_pipeline_snapshot(snapshot)
    except Exception as exc:
        raise ImmutablePipelineScheduleError(
            "Le snapshot V2 verrouillé du pipeline est invalide"
        ) from exc
    stored_hash = str(result.get("schedule_hash") or "").strip()
    if not stored_hash or stored_hash != expected_hash:
        raise ImmutablePipelineScheduleError(
            "Le hash du snapshot V2 verrouillé du pipeline est invalide"
        )
    if result.get("nb_days") not in (None, canonical_snapshot["day_count"]):
        raise ImmutablePipelineScheduleError(
            "Le nombre de journées du pipeline ne correspond pas au snapshot"
        )
    result["schedule_snapshot_json"] = canonical_snapshot
    return result


def lock_pipeline_schedule_snapshot(
    center_account_id: int,
    job_id: int,
    snapshot: Mapping[str, Any],
    *,
    locked_at: datetime | None = None,
) -> dict[str, Any]:
    """Atomically freeze a validated canonical V2 snapshot on a pipeline job."""
    center_account_id = _positive_id(center_account_id, "center_account_id")
    job_id = _positive_id(job_id, "job_id")
    canonical_snapshot, schedule_hash = _canonical_pipeline_snapshot(snapshot)
    locked_at = locked_at or _now()
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        ph = "%s" if postgres else "?"
        lock_clause = "FOR UPDATE" if postgres else ""
        cursor.execute(
            f"""
            SELECT j.id, j.platform_id, j.nb_days,
                   j.schedule_schema_version, j.schedule_snapshot_json,
                   j.schedule_hash, j.schedule_locked_at
            FROM formation_pipeline_jobs j
            JOIN platform_config pc
              ON pc.id = j.platform_id
            WHERE j.id = {ph}
              AND pc.center_account_id = {ph}
            {lock_clause}
            """,
            (job_id, center_account_id),
        )
        existing = _hydrate_pipeline_schedule(cursor.fetchone())
        if existing is None:
            raise ValueError("Pipeline introuvable pour ce centre")
        if existing.get("schedule_locked_at") is not None:
            if existing.get("schedule_hash") != schedule_hash:
                raise ImmutablePipelineScheduleError(
                    "Le planning de ce pipeline est déjà verrouillé"
                )
            return existing
        if existing.get("schedule_hash") not in (None, "", schedule_hash):
            raise ImmutablePipelineScheduleError(
                "Un autre planning est déjà associé à ce pipeline"
            )

        db_now = _db_datetime(locked_at, postgres=postgres)
        snapshot_json = _canonical_json(canonical_snapshot)
        json_value = f"{ph}::jsonb" if postgres else ph
        cursor.execute(
            f"""
            UPDATE formation_pipeline_jobs
            SET nb_days = {ph},
                schedule_schema_version = {ph},
                schedule_snapshot_json = {json_value},
                schedule_hash = {ph},
                schedule_locked_at = {ph},
                updated_at = {ph}
            WHERE id = {ph}
              AND platform_id = {ph}
              AND schedule_locked_at IS NULL
              AND (schedule_hash IS NULL OR schedule_hash = {ph})
            """,
            (
                canonical_snapshot["day_count"],
                DEFAULT_SCHEMA_VERSION,
                snapshot_json,
                schedule_hash,
                db_now,
                db_now,
                job_id,
                existing["platform_id"],
                schedule_hash,
            ),
        )
        if cursor.rowcount != 1:
            raise ImmutablePipelineScheduleError(
                "Le planning a été verrouillé par une autre opération"
            )
        cursor.execute(
            f"""
            SELECT j.id, j.platform_id, j.nb_days,
                   j.schedule_schema_version, j.schedule_snapshot_json,
                   j.schedule_hash, j.schedule_locked_at
            FROM formation_pipeline_jobs j
            JOIN platform_config pc
              ON pc.id = j.platform_id
            WHERE j.id = {ph}
              AND pc.center_account_id = {ph}
            """,
            (job_id, center_account_id),
        )
        return _hydrate_pipeline_schedule(cursor.fetchone())


def get_pipeline_schedule_snapshot(
    center_account_id: int,
    job_id: int,
) -> dict[str, Any] | None:
    center_account_id = _positive_id(center_account_id, "center_account_id")
    job_id = _positive_id(job_id, "job_id")
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        ph = "%s" if postgres else "?"
        cursor.execute(
            f"""
            SELECT j.id, j.platform_id, j.nb_days,
                   j.schedule_schema_version, j.schedule_snapshot_json,
                   j.schedule_hash, j.schedule_locked_at
            FROM formation_pipeline_jobs j
            JOIN platform_config pc
              ON pc.id = j.platform_id
            WHERE j.id = {ph}
              AND pc.center_account_id = {ph}
            """,
            (job_id, center_account_id),
        )
        return _hydrate_pipeline_schedule(cursor.fetchone())


def _normalize_module_days(
    cursor,
    center_account_id: int,
    days: Iterable[Mapping[str, Any]],
    *,
    postgres: bool,
    default_schema_version: int,
) -> list[dict[str, Any]]:
    if isinstance(days, (str, bytes, Mapping)):
        raise ValueError("days doit être une liste")
    normalized = []
    for offset, raw in enumerate(days, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError(f"Journée {offset} invalide")
        day_index = int(raw.get("day_index", raw.get("day_number", offset)))
        if day_index != offset:
            raise ValueError("Les journées doivent être numérotées sans interruption")
        template_id_value = raw.get("source_template_id", raw.get("template_id"))
        if template_id_value is None:
            template_key = raw.get("template_key")
            if isinstance(template_key, int) and not isinstance(template_key, bool):
                template_id_value = template_key
            elif isinstance(template_key, str) and template_key.isdigit():
                template_id_value = template_key
        template_id = (
            _positive_id(template_id_value, "template_id")
            if template_id_value is not None
            else None
        )
        template = None
        if template_id is not None:
            template_row = _select_template(
                cursor,
                center_account_id,
                template_id,
                postgres=postgres,
                # A soft-delete only removes the template from the library.
                # An already assigned formation must still be finalizable from
                # the exact frozen block snapshot.
                include_deleted=True,
                for_update=True,
            )
            template = _row_dict(template_row)
            if template is None:
                raise ValueError(f"Template {template_id} introuvable pour ce centre")

        raw_blocks = raw.get("blocks")
        if raw_blocks is None:
            if template is None:
                raw_blocks = _decode_json(raw.get("blocks_snapshot_json"), [])
            else:
                raw_blocks = _decode_json(template["blocks_snapshot_json"], [])
        blocks = _validated_canonical_blocks(raw_blocks)
        metrics = _block_metrics(blocks)
        default_day_schema_version = (
            raw.get("schema_version")
            if raw.get("schema_version") is not None
            else template.get("schedule_schema_version")
            if template
            else default_schema_version
        )
        schedule_schema_version = int(
            raw.get("schedule_schema_version", default_day_schema_version)
        )
        template_name = str(
            raw.get("template_name")
            or (template.get("name") if template else "")
            or f"Journée {day_index}"
        ).strip()
        normalized.append(
            {
                "day_index": day_index,
                "source_template_id": template_id,
                "template_name": template_name,
                "schedule_schema_version": schedule_schema_version,
                "schedule_hash": _module_schedule_fingerprint(
                    [{"blocks": blocks}]
                ),
                "blocks": blocks,
                **metrics,
            }
        )
    if not normalized:
        raise ValueError("Le module doit contenir au moins une journée")
    return normalized


def _hydrate_module_day(row) -> dict[str, Any] | None:
    day = _row_dict(row)
    if day is None:
        return None
    if day.get("immutable") not in (True, 1):
        raise ImmutableModuleScheduleError(
            "Le snapshot de journée durable n'est plus marqué immuable"
        )
    if int(day.get("schedule_schema_version") or 0) != DEFAULT_SCHEMA_VERSION:
        raise ImmutableModuleScheduleError(
            "Le snapshot de journée durable n'utilise pas le schéma V2"
        )
    if day.get("locked_at") in (None, ""):
        raise ImmutableModuleScheduleError(
            "Le snapshot de journée durable n'est pas verrouillé"
        )
    try:
        blocks = _validated_canonical_blocks(
            _decode_json(day.get("blocks_snapshot_json"), [])
        )
        expected_hash = _module_schedule_fingerprint([{"blocks": blocks}])
    except Exception as exc:
        raise ImmutableModuleScheduleError(
            "Le snapshot de journée durable est illisible"
        ) from exc
    stored_hash = str(day.get("schedule_hash") or "").strip()
    if not stored_hash or stored_hash != expected_hash:
        raise ImmutableModuleScheduleError(
            "Le hash du snapshot de journée durable est invalide"
        )
    metrics = _block_metrics(blocks)
    for field, expected_value in metrics.items():
        try:
            stored_value = int(day.get(field))
        except (TypeError, ValueError) as exc:
            raise ImmutableModuleScheduleError(
                f"La métrique {field} du snapshot durable est invalide"
            ) from exc
        if stored_value != expected_value:
            raise ImmutableModuleScheduleError(
                f"La métrique {field} du snapshot durable ne correspond pas aux blocs"
            )
    day["blocks_snapshot_json"] = blocks
    day["blocks"] = blocks
    if day.get("schedule_snapshot_json") is not None:
        day["schedule_snapshot_json"] = _decode_json(
            day["schedule_snapshot_json"],
            {},
        )
    return day


def validate_module_day_snapshot(row) -> dict[str, Any] | None:
    """Validate and hydrate a durable module-day row for other repositories."""
    return _hydrate_module_day(row)


def _module_schedule_fingerprint(days: list[dict[str, Any]]) -> str:
    """Match the domain hash: dates, template labels and technical IDs excluded."""
    return _sha256_json(
        {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "days": [
                {
                    "blocks": [
                        {
                            "block_type": block["block_type"],
                            "pause_kind": block["pause_kind"],
                            "start_minute": block["start_minute"],
                            "duration_minutes": block["duration_minutes"],
                        }
                        for block in day["blocks"]
                    ],
                }
                for day in days
            ],
        }
    )


def create_module_day_snapshots(
    center_account_id: int,
    module_id: int,
    days: Iterable[Mapping[str, Any]],
    *,
    schedule_schema_version: int = DEFAULT_SCHEMA_VERSION,
    locked_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Atomically lock one self-contained schedule snapshot per module day.

    Repeating the exact same call is idempotent.  A different second snapshot
    is rejected instead of mutating already generated pedagogical content.
    """
    center_account_id = _positive_id(center_account_id, "center_account_id")
    module_id = _positive_id(module_id, "module_id")
    locked_at = locked_at or _now()
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        ph = "%s" if postgres else "?"
        lock_clause = "FOR UPDATE" if postgres else ""
        cursor.execute(
            f"""
            SELECT id, center_account_id, nb_days, schedule_schema_version,
                   schedule_hash, schedule_locked_at
            FROM formation_modules
            WHERE id = {ph}
              AND center_account_id = {ph}
            {lock_clause}
            """,
            (module_id, center_account_id),
        )
        module = _row_dict(cursor.fetchone())
        if module is None:
            raise ValueError("Module introuvable pour ce centre")

        normalized_days = _normalize_module_days(
            cursor,
            center_account_id,
            days,
            postgres=postgres,
            default_schema_version=schedule_schema_version,
        )
        aggregate_hash = _module_schedule_fingerprint(normalized_days)
        cursor.execute(
            f"""
            SELECT *
            FROM formation_module_days
            WHERE module_id = {ph}
              AND center_account_id = {ph}
            ORDER BY day_index ASC
            """,
            (module_id, center_account_id),
        )
        existing_days = [_hydrate_module_day(row) for row in cursor.fetchall()]
        if existing_days:
            existing_hash = _module_schedule_fingerprint(existing_days)
            if existing_hash != aggregate_hash:
                raise ImmutableModuleScheduleError(
                    "Le planning durable de ce module est déjà verrouillé"
                )
            return existing_days

        existing_nb_days = module.get("nb_days")
        if existing_nb_days not in (None, 0, len(normalized_days)):
            raise ValueError(
                "Le nombre de journées ne correspond pas au module"
            )
        existing_hash = module.get("schedule_hash")
        if existing_hash and existing_hash != aggregate_hash:
            raise ImmutableModuleScheduleError(
                "Le hash de planning du module est déjà verrouillé"
            )

        db_now = _db_datetime(locked_at, postgres=postgres)
        for day in normalized_days:
            payload = (
                module_id,
                center_account_id,
                day["day_index"],
                day["source_template_id"],
                day["template_name"],
                day["schedule_schema_version"],
                day["schedule_hash"],
                _canonical_json(day["blocks"]),
                day["block_count"],
                day["total_duration_minutes"],
                day["course_duration_minutes"],
                db_now,
                db_now,
            )
            if postgres:
                cursor.execute(
                    """
                    INSERT INTO formation_module_days (
                        module_id, center_account_id, day_index,
                        source_template_id, template_name,
                        schedule_schema_version, schedule_hash,
                        blocks_snapshot_json, block_count,
                        total_duration_minutes, course_duration_minutes,
                        locked_at, created_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                        %s, %s, %s, %s, %s
                    )
                    """,
                    payload,
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO formation_module_days (
                        module_id, center_account_id, day_index,
                        source_template_id, template_name,
                        schedule_schema_version, schedule_hash,
                        blocks_snapshot_json, block_count,
                        total_duration_minutes, course_duration_minutes,
                        locked_at, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    payload,
                )
            if day["source_template_id"] is not None:
                cursor.execute(
                    f"""
                    UPDATE day_schedule_templates
                    SET used_at = COALESCE(used_at, {ph}),
                        locked_at = COALESCE(locked_at, {ph}),
                        updated_at = CASE
                            WHEN locked_at IS NULL THEN {ph}
                            ELSE updated_at
                        END
                    WHERE id = {ph}
                      AND center_account_id = {ph}
                      AND status = 'active'
                    """,
                    (
                        db_now,
                        db_now,
                        db_now,
                        day["source_template_id"],
                        center_account_id,
                    ),
                )

        cursor.execute(
            f"""
            UPDATE formation_modules
            SET nb_days = {ph},
                schedule_schema_version = {ph},
                schedule_hash = {ph},
                schedule_locked_at = COALESCE(schedule_locked_at, {ph})
            WHERE id = {ph}
              AND center_account_id = {ph}
              AND (schedule_hash IS NULL OR schedule_hash = {ph})
            """,
            (
                len(normalized_days),
                int(schedule_schema_version),
                aggregate_hash,
                db_now,
                module_id,
                center_account_id,
                aggregate_hash,
            ),
        )
        if cursor.rowcount != 1:
            raise ImmutableModuleScheduleError(
                "Le module a été verrouillé par une autre opération"
            )
        cursor.execute(
            f"""
            SELECT *
            FROM formation_module_days
            WHERE module_id = {ph}
              AND center_account_id = {ph}
            ORDER BY day_index ASC
            """,
            (module_id, center_account_id),
        )
        return [_hydrate_module_day(row) for row in cursor.fetchall()]


def list_module_days(
    module_id: int,
    *,
    center_account_id: int | None = None,
) -> list[dict[str, Any]]:
    module_id = _positive_id(module_id, "module_id")
    if center_account_id is not None:
        center_account_id = _positive_id(center_account_id, "center_account_id")
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        ph = "%s" if postgres else "?"
        params: list[Any] = [module_id]
        center_clause = ""
        if center_account_id is not None:
            center_clause = f"AND md.center_account_id = {ph}"
            params.append(center_account_id)
        cursor.execute(
            f"""
            SELECT md.*
            FROM formation_module_days md
            JOIN formation_modules fm
              ON fm.id = md.module_id
             AND fm.center_account_id = md.center_account_id
            WHERE md.module_id = {ph}
              {center_clause}
            ORDER BY md.day_index ASC
            """,
            tuple(params),
        )
        return [_hydrate_module_day(row) for row in cursor.fetchall()]


def bind_module_days_to_platform(
    center_account_id: int,
    module_id: int,
    platform_id: int,
    folder_ids: Iterable[int],
) -> list[dict[str, int]]:
    """Bind immutable pedagogical days to folders and dated occurrences.

    ``folder_ids`` must already be in pedagogical order. The update is
    idempotent and refuses a count mismatch instead of shifting later days.
    """
    center_account_id = _positive_id(center_account_id, "center_account_id")
    module_id = _positive_id(module_id, "module_id")
    platform_id = _positive_id(platform_id, "platform_id")
    ordered_folder_ids = [
        _positive_id(folder_id, "folder_id")
        for folder_id in folder_ids
    ]
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        ph = "%s" if postgres else "?"
        cursor.execute(
            f"""
            SELECT id, day_index
            FROM formation_module_days
            WHERE module_id = {ph}
              AND center_account_id = {ph}
            ORDER BY day_index ASC
            """,
            (module_id, center_account_id),
        )
        module_days = [dict(row) for row in cursor.fetchall()]
        if len(module_days) != len(ordered_folder_ids):
            raise ValueError(
                "Le nombre de dossiers ne correspond pas au planning durable"
            )

        bindings = []
        for folder_id, module_day in zip(ordered_folder_ids, module_days):
            module_day_id = int(module_day["id"])
            day_index = int(module_day["day_index"])
            cursor.execute(
                f"""
                UPDATE cours_folders
                SET module_day_id = {ph}
                WHERE id = {ph}
                  AND platform_id = {ph}
                  AND EXISTS (
                      SELECT 1
                      FROM platform_config pc
                      WHERE pc.id = cours_folders.platform_id
                        AND pc.center_account_id = {ph}
                  )
                  AND (module_day_id IS NULL OR module_day_id = {ph})
                """,
                (
                    module_day_id,
                    folder_id,
                    platform_id,
                    center_account_id,
                    module_day_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ImmutableModuleScheduleError(
                    "Un dossier est déjà lié à une autre journée durable"
                )
            cursor.execute(
                f"""
                UPDATE course_sessions
                SET module_day_id = {ph}
                WHERE platform_id = {ph}
                  AND session_index = {ph}
                  AND (module_day_id IS NULL OR module_day_id = {ph})
                """,
                (module_day_id, platform_id, day_index, module_day_id),
            )
            if cursor.rowcount != 1:
                raise ImmutableModuleScheduleError(
                    "Aucune occurrence compatible avec la journée durable"
                )
            bindings.append({
                "day_index": day_index,
                "module_day_id": module_day_id,
                "folder_id": folder_id,
            })
        return bindings


def get_module_day_for_folder(
    folder_id: int,
    *,
    center_account_id: int | None = None,
) -> dict[str, Any] | None:
    """Resolve the immutable V2 manifest bound to a concrete course folder."""
    folder_id = _positive_id(folder_id, "folder_id")
    if center_account_id is not None:
        center_account_id = _positive_id(center_account_id, "center_account_id")
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        ph = "%s" if postgres else "?"
        params: list[Any] = [folder_id]
        center_clause = ""
        if center_account_id is not None:
            center_clause = f"AND md.center_account_id = {ph}"
            params.append(center_account_id)
        cursor.execute(
            f"""
            SELECT md.*, cf.position AS folder_position
            FROM cours_folders cf
            JOIN platform_config pc
              ON pc.id = cf.platform_id
            JOIN formation_module_days md
              ON md.id = cf.module_day_id
             AND md.center_account_id = pc.center_account_id
            WHERE cf.id = {ph}
              {center_clause}
            """,
            tuple(params),
        )
        return _hydrate_module_day(cursor.fetchone())


def get_schedule_snapshot_for_folder(
    folder_id: int,
    *,
    center_account_id: int | None = None,
) -> dict[str, Any] | None:
    """Pre-finalization fallback: resolve the pipeline job's V2 day snapshot."""
    folder_id = _positive_id(folder_id, "folder_id")
    if center_account_id is not None:
        center_account_id = _positive_id(center_account_id, "center_account_id")
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        ph = "%s" if postgres else "?"
        params: list[Any] = [folder_id]
        center_clause = ""
        if center_account_id is not None:
            center_clause = f"AND pc.center_account_id = {ph}"
            params.append(center_account_id)
        cursor.execute(
            f"""
            SELECT j.id AS formation_job_id,
                   j.nb_days,
                   j.schedule_schema_version,
                   j.schedule_snapshot_json,
                   j.schedule_hash,
                   j.schedule_locked_at,
                   cf.position AS folder_position
            FROM cours_folders cf
            JOIN platform_config pc
              ON pc.id = cf.platform_id
            JOIN formation_pipeline_jobs j
              ON j.id = cf.formation_job_id
             AND j.platform_id = cf.platform_id
            WHERE cf.id = {ph}
              {center_clause}
            """,
            tuple(params),
        )
        return _hydrate_pipeline_schedule(cursor.fetchone())
