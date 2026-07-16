"""PostgreSQL registry and path resolution for immutable teacher assets."""

from __future__ import annotations

from typing import Any, Iterable

from config import PIPELINE_DATABASE_BACKEND
from database.postgres import get_postgres_connection


_POSTGRES_BACKENDS = {"postgres", "postgresql", "supabase"}


def _uses_postgres() -> bool:
    return str(PIPELINE_DATABASE_BACKEND or "").strip().lower() in _POSTGRES_BACKENDS


def get_module_asset_identity(module_id: int, center_account_id: int) -> dict[str, Any] | None:
    if not _uses_postgres():
        return None
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id, m.center_account_id, m.version, m.source_platform_id,
                       m.source_pipeline_job_id, m.asset_namespace, m.voice_type,
                       m.teacher_name, m.teacher_color
                FROM formation_modules m
                WHERE m.id = %s
                  AND m.center_account_id = %s
                  AND m.status = 'validated'
                """,
                (int(module_id), int(center_account_id)),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def register_module_assets(
    module_id: int,
    center_account_id: int,
    assets: Iterable[dict[str, Any]],
) -> int:
    """Upsert one immutable manifest without changing the referenced blobs."""
    if not _uses_postgres():
        return 0
    values = list(assets)
    if not values:
        return 0

    module_id = int(module_id)
    center_id = int(center_account_id)
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM formation_modules
                WHERE id = %s AND center_account_id = %s AND status = 'validated'
                FOR UPDATE
                """,
                (module_id, center_id),
            )
            if cur.fetchone() is None:
                raise ValueError("Module durable introuvable pour ce centre")
            for asset in values:
                cur.execute(
                    """
                    INSERT INTO formation_module_assets (
                        module_id, center_account_id, source_folder_id, asset_kind,
                        logical_key, container_name, blob_path, content_sha256,
                        byte_size, mime_type, language, voice_profile,
                        generator_version, generation_params_json, status,
                        storage_tier, immutable, last_verified_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s::jsonb, 'ready', %s, TRUE, NOW()
                    )
                    ON CONFLICT (module_id, logical_key) DO UPDATE SET
                        container_name = EXCLUDED.container_name,
                        blob_path = EXCLUDED.blob_path,
                        content_sha256 = COALESCE(EXCLUDED.content_sha256, formation_module_assets.content_sha256),
                        byte_size = EXCLUDED.byte_size,
                        mime_type = EXCLUDED.mime_type,
                        voice_profile = COALESCE(EXCLUDED.voice_profile, formation_module_assets.voice_profile),
                        generator_version = COALESCE(EXCLUDED.generator_version, formation_module_assets.generator_version),
                        generation_params_json = EXCLUDED.generation_params_json,
                        status = 'ready',
                        storage_tier = EXCLUDED.storage_tier,
                        last_verified_at = NOW(),
                        updated_at = NOW()
                    """,
                    (
                        module_id,
                        center_id,
                        asset.get("source_folder_id"),
                        asset["asset_kind"],
                        asset["logical_key"],
                        asset["container_name"],
                        asset["blob_path"],
                        asset.get("content_sha256"),
                        asset.get("byte_size"),
                        asset.get("mime_type"),
                        asset.get("language"),
                        asset.get("voice_profile"),
                        asset.get("generator_version"),
                        asset.get("generation_params_json") or "{}",
                        asset.get("storage_tier") or "Hot",
                    ),
                )
    return len(values)


def module_asset_count(module_id: int) -> int:
    if not _uses_postgres():
        return 0
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total FROM formation_module_assets WHERE module_id = %s AND status = 'ready'",
                (int(module_id),),
            )
            row = cur.fetchone()
            return int(row["total"] or 0)


def resolve_folder_asset_origin(folder_id: int) -> dict[str, Any] | None:
    """Resolve a promotion folder to the single canonical module folder."""
    if not _uses_postgres():
        return None
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT target_folder.id AS requested_folder_id,
                       target_folder.platform_id AS requested_platform_id,
                       COALESCE(mapping.source_folder_id, target_folder.id) AS source_folder_id,
                       COALESCE(mapping.source_platform_id, target_folder.platform_id) AS source_platform_id,
                       COALESCE(target_platform.source_module_id, source_module.id) AS module_id,
                       target_platform.asset_binding_mode
                FROM cours_folders target_folder
                JOIN platform_config target_platform ON target_platform.id = target_folder.platform_id
                LEFT JOIN course_clone_folder_map mapping
                  ON mapping.target_folder_id = target_folder.id
                LEFT JOIN formation_modules source_module
                  ON source_module.source_platform_id = COALESCE(mapping.source_platform_id, target_folder.platform_id)
                 AND source_module.status = 'validated'
                WHERE target_folder.id = %s
                ORDER BY source_module.validated_at DESC NULLS LAST, source_module.id DESC
                LIMIT 1
                """,
                (int(folder_id),),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def resolve_registered_blob_path(
    *,
    folder_id: int,
    container_name: str,
    relative_path: str,
) -> dict[str, Any] | None:
    """Resolve a logical folder asset, falling back to its immutable source path."""
    origin = resolve_folder_asset_origin(folder_id)
    if not origin:
        return None
    clean_relative = str(relative_path or "").lstrip("/")
    source_folder_id = int(origin["source_folder_id"])
    source_platform_id = int(origin["source_platform_id"])
    logical_key = f"{container_name}:folder:{source_folder_id}:{clean_relative}"
    module_id = origin.get("module_id")

    if module_id and _uses_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT container_name, blob_path, content_sha256, byte_size,
                           mime_type, storage_tier
                    FROM formation_module_assets
                    WHERE module_id = %s
                      AND logical_key = %s
                      AND container_name = %s
                      AND status = 'ready'
                    """,
                    (int(module_id), logical_key, container_name),
                )
                asset = cur.fetchone()
                if asset:
                    return {**origin, **dict(asset), "logical_key": logical_key, "registered": True}

    return {
        **origin,
        "container_name": container_name,
        "blob_path": f"platform-{source_platform_id}/folder-{source_folder_id}/{clean_relative}",
        "logical_key": logical_key,
        "registered": False,
    }
