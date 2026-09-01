"""Postgres read models used by the HR dashboard.

The HR routes historically assembled these views directly from SQLite.  This
module provides the equivalent read-only queries for deployments whose
formation pipeline is authoritative in Postgres.  It deliberately has no
SQLite fallback: choosing the provider happens in the route, before calling
these functions, so a production read cannot silently return stale local data.
"""

from __future__ import annotations

import json
from typing import Any

from database.postgres import get_postgres_connection
from repositories.course_schedule_repository import list_postgres_course_schedule_configs


def _center_scope(
    alias: str,
    center_account_id: int | None,
    *,
    scope_to_center: bool,
) -> tuple[str, tuple[Any, ...]]:
    """Return a fail-closed tenant predicate for a dashboard query."""
    if not scope_to_center:
        return "", ()
    if center_account_id is None:
        return " AND FALSE", ()
    return f" AND {alias}.center_account_id = %s", (center_account_id,)


def list_formation_modules(
    center_account_id: int | None = None,
    *,
    scope_to_center: bool = False,
) -> list[dict[str, Any]]:
    """Return reusable formation modules from the authoritative Postgres DB."""
    scope_sql, scope_params = _center_scope(
        "m",
        center_account_id,
        scope_to_center=scope_to_center,
    )
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT m.id, m.rncp_code, m.tp_name, m.version, m.status,
                       m.source_pipeline_job_id, m.source_platform_id, m.created_at,
                       j.total_hours,
                       (
                           SELECT COUNT(*)
                           FROM cours_folders cf
                           WHERE cf.platform_id = m.source_platform_id
                       ) AS nb_folders,
                       pc.name AS source_platform_name,
                       m.voice_type, m.voice_updated_at,
                       m.teacher_name, m.teacher_color, m.asset_namespace,
                       m.immutable,
                       m.nb_days, m.schedule_schema_version, m.schedule_hash,
                       m.schedule_locked_at, m.reusable_at,
                       (
                           SELECT COUNT(*)
                           FROM formation_module_days module_day
                           WHERE module_day.module_id = m.id
                             AND module_day.center_account_id = m.center_account_id
                       ) AS module_day_count,
                       (
                           SELECT COUNT(*)
                           FROM formation_module_assets asset
                           WHERE asset.module_id = m.id AND asset.status = 'ready'
                       ) AS asset_count,
                       (
                           SELECT COUNT(*)
                           FROM platform_config usage_platform
                           WHERE (
                               usage_platform.source_module_id = m.id
                               OR usage_platform.id = m.source_platform_id
                           )
                             AND usage_platform.lifecycle_status = 'active'
                       ) AS active_use_count,
                       (
                           SELECT COUNT(*)
                           FROM platform_config usage_platform
                           WHERE (
                               usage_platform.source_module_id = m.id
                               OR usage_platform.id = m.source_platform_id
                           )
                             AND usage_platform.lifecycle_status IN ('completed', 'archived')
                       ) AS completed_use_count
                FROM formation_modules m
                LEFT JOIN platform_config pc ON pc.id = m.source_platform_id
                LEFT JOIN formation_pipeline_jobs j ON j.id = m.source_pipeline_job_id
                WHERE m.status != 'archived'
                {scope_sql}
                ORDER BY m.created_at DESC
                """,
                scope_params,
            )
            rows = [dict(row) for row in cur.fetchall()]

    # Do not keep a Postgres connection checked out while schedule repository
    # calls acquire their own pooled connection (important when pool_min=1).
    source_platform_ids = sorted({row["source_platform_id"] for row in rows if row["source_platform_id"]})
    schedule_configs = list_postgres_course_schedule_configs(source_platform_ids)
    schedules_by_platform: dict[int, dict[str, Any] | None] = {}
    for platform_id in source_platform_ids:
        schedule = schedule_configs.get(int(platform_id))
        if not schedule:
            schedules_by_platform[int(platform_id)] = None
            continue
        try:
            weekdays = json.loads(schedule.get("weekdays_json") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            weekdays = []
        schedules_by_platform[int(platform_id)] = {
            "total_training_days": schedule.get("total_training_days"),
            "weekly_course_count": schedule.get("weekly_course_count"),
            "weekdays": weekdays,
            "start_time": schedule.get("start_time"),
        }

    for row in rows:
        source_platform_id = row.get("source_platform_id")
        row["schedule"] = schedules_by_platform.get(int(source_platform_id)) if source_platform_id else None
    return rows


def list_formations(
    center_account_id: int | None = None,
    *,
    scope_to_center: bool = False,
) -> list[dict[str, Any]]:
    """Return legacy pipeline-job choices from Postgres, tenant scoped."""
    scope_sql, scope_params = _center_scope(
        "pc",
        center_account_id,
        scope_to_center=scope_to_center,
    )
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT j.id, j.tp_name, j.rncp_code, j.total_hours, j.nb_days,
                       j.status, j.platform_id, pc.name AS platform_name,
                       (
                           SELECT COUNT(*)
                           FROM cours_folders cf
                           WHERE cf.platform_id = j.platform_id
                       ) AS nb_folders,
                       j.created_at
                FROM formation_pipeline_jobs j
                LEFT JOIN platform_config pc ON pc.id = j.platform_id
                WHERE TRUE
                {scope_sql}
                ORDER BY j.created_at DESC
                """,
                scope_params,
            )
            return [dict(row) for row in cur.fetchall()]


def list_platforms(
    center_account_id: int | None = None,
    *,
    scope_to_center: bool = False,
) -> list[dict[str, Any]]:
    """Return the database portion of the HR platform dashboard from Postgres."""
    scope_sql, scope_params = _center_scope(
        "pc",
        center_account_id,
        scope_to_center=scope_to_center,
    )
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    pc.id,
                    pc.name,
                    pc.teacher_name,
                    pc.teacher_color,
                    pc.creation_request_id,
                    pc.slug,
                    pc.upload_locked,
                    pc.pdf_filename,
                    pc.pdf_uploaded_at,
                    pc.updated_at,
                    pc.status,
                    pc.source_formation_id,
                    pc.source_module_id,
                    pc.center_account_id,
                    pc.center_platform_number,
                    COALESCE(tca.slug, 'le-socrate') AS center_slug,
                    COALESCE(fm.rncp_code, fpj.rncp_code) AS source_rncp_code,
                    COALESCE(fm.tp_name, fpj.tp_name) AS source_tp_name,
                    fpj.status AS pipeline_status,
                    fpj.auto_pilot_step AS pipeline_auto_pilot_step,
                    fpj.auto_pilot_error AS pipeline_auto_pilot_error,
                    fpj.auto_pilot_enabled AS pipeline_auto_pilot_enabled,
                    pc.lifecycle_status,
                    pc.completed_at,
                    pc.archived_at,
                    pc.asset_binding_mode,
                    (
                        SELECT COUNT(*) FROM course_sessions cs
                        WHERE cs.platform_id = pc.id
                    ) AS total_session_count,
                    (
                        SELECT COUNT(*) FROM course_sessions cs
                        WHERE cs.platform_id = pc.id
                          AND cs.status IN ('planned', 'active')
                          AND cs.scheduled_at >= NOW()
                    ) AS remaining_session_count
                FROM platform_config pc
                LEFT JOIN training_center_accounts tca ON tca.id = pc.center_account_id
                LEFT JOIN formation_modules fm ON fm.id = pc.source_module_id
                LEFT JOIN formation_pipeline_jobs fpj ON fpj.id = pc.source_formation_id
                WHERE TRUE
                {scope_sql}
                ORDER BY pc.id
                """,
                scope_params,
            )
            return [dict(row) for row in cur.fetchall()]
