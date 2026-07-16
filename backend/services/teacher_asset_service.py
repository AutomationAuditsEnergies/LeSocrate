"""Azure manifesting for reusable, immutable AI-teacher resources."""

from __future__ import annotations

import json
import mimetypes
import os
from pathlib import PurePosixPath
from typing import Any, Iterable

from repositories.teacher_asset_repository import (
    get_module_asset_identity,
    module_asset_count,
    register_module_assets,
    resolve_registered_blob_path,
)
from services.azure_blob_service import (
    CONTAINER_AUDIOS,
    CONTAINER_DOCUMENTS,
    _get_blob_service_client,
    blob_exists,
)
from utils.logger import get_logger


logger = get_logger(__name__)


def _asset_kind(container_name: str, relative_path: str) -> str:
    suffix = PurePosixPath(relative_path).suffix.lower()
    lowered = relative_path.lower()
    if suffix in {".mp3", ".wav", ".m4a", ".ogg"}:
        return "audio"
    if "slide" in lowered or suffix in {".ppt", ".pptx"}:
        return "slides"
    if suffix in {".json", ".jsonl"}:
        return "manifest"
    if container_name == CONTAINER_DOCUMENTS:
        return "document"
    return "artifact"


def _content_type(blob: Any, relative_path: str) -> str | None:
    settings = getattr(blob, "content_settings", None)
    explicit = getattr(settings, "content_type", None) if settings else None
    if explicit:
        return str(explicit)
    guessed, _encoding = mimetypes.guess_type(relative_path)
    return guessed


def _blob_sha256(blob: Any) -> str | None:
    metadata = getattr(blob, "metadata", None) or {}
    value = metadata.get("sha256") or metadata.get("content_sha256")
    return str(value) if value else None


def ensure_module_asset_manifest(
    *,
    module_id: int,
    center_account_id: int,
    source_platform_id: int,
    source_folder_ids: Iterable[int],
    force: bool = False,
) -> dict[str, Any]:
    """Record the canonical source blobs once, without copying them per reuse.

    The first version deliberately supports existing ``platform-X/folder-Y``
    blobs. New readers resolve through this manifest, so paths can later move to
    the module namespace without changing promotions or course schedules.
    """
    module_id = int(module_id)
    center_id = int(center_account_id)
    source_platform_id = int(source_platform_id)
    identity = get_module_asset_identity(module_id, center_id)
    if not identity:
        raise ValueError("Module durable introuvable pour ce centre")

    existing_count = module_asset_count(module_id)
    if existing_count and not force:
        return {"module_id": module_id, "registered": existing_count, "reused_manifest": True}

    blob_service = _get_blob_service_client()
    manifest: list[dict[str, Any]] = []
    voice_profile = identity.get("voice_type")
    generator_version = os.getenv("TEACHER_ASSET_GENERATOR_VERSION", "pipeline-v1")

    for source_folder_id in sorted({int(folder_id) for folder_id in source_folder_ids}):
        prefix = f"platform-{source_platform_id}/folder-{source_folder_id}/"
        for container_name in (CONTAINER_DOCUMENTS, CONTAINER_AUDIOS):
            container = blob_service.get_container_client(container_name)
            for blob in container.list_blobs(name_starts_with=prefix, include=["metadata"]):
                relative_path = str(blob.name)[len(prefix):]
                if not relative_path:
                    continue
                manifest.append({
                    "source_folder_id": source_folder_id,
                    "asset_kind": _asset_kind(container_name, relative_path),
                    "logical_key": f"{container_name}:folder:{source_folder_id}:{relative_path}",
                    "container_name": container_name,
                    "blob_path": str(blob.name),
                    "content_sha256": _blob_sha256(blob),
                    "byte_size": int(getattr(blob, "size", 0) or 0),
                    "mime_type": _content_type(blob, relative_path),
                    "language": "fr-FR",
                    "voice_profile": voice_profile if container_name == CONTAINER_AUDIOS else None,
                    "generator_version": generator_version,
                    "generation_params_json": json.dumps({
                        "etag": str(getattr(blob, "etag", "") or ""),
                        "source_layout": "platform-folder-v1",
                    }),
                    "storage_tier": str(getattr(blob, "blob_tier", None) or "Hot"),
                })

    registered = register_module_assets(module_id, center_id, manifest)
    logger.info(
        "TEACHER_ASSET_MANIFEST_READY module_id=%s center_id=%s assets=%s",
        module_id,
        center_id,
        registered,
    )
    return {"module_id": module_id, "registered": registered, "reused_manifest": False}


def resolve_folder_blob_path(
    folder_id: int,
    container_name: str,
    relative_path: str,
    *,
    fallback_platform_id: int | None = None,
) -> str:
    """Return the shared source path for a promotion folder.

    SQLite-only development has no clone mapping table and keeps the historical
    path. PostgreSQL deployments resolve a clone to its module source.
    """
    resolved = resolve_registered_blob_path(
        folder_id=int(folder_id),
        container_name=container_name,
        relative_path=str(relative_path or "").lstrip("/"),
    )
    if resolved:
        # Reused teachers share the immutable module by default. An audio edit
        # writes only the changed file under the promotion path; prefer that
        # per-asset override while every untouched file still resolves to the
        # canonical module. This is true copy-on-write, not a full blob clone.
        requested_platform_id = resolved.get("requested_platform_id")
        requested_folder_id = resolved.get("requested_folder_id")
        if (
            resolved.get("asset_binding_mode") == "copy_on_write"
            and requested_platform_id is not None
            and requested_folder_id is not None
        ):
            override_path = (
                f"platform-{int(requested_platform_id)}/folder-{int(requested_folder_id)}/"
                f"{str(relative_path or '').lstrip('/')}"
            )
            if override_path != resolved.get("blob_path") and blob_exists(container_name, override_path):
                return override_path
        return str(resolved["blob_path"])
    if fallback_platform_id is None:
        raise ValueError("Plateforme requise pour résoudre la ressource")
    return f"platform-{int(fallback_platform_id)}/folder-{int(folder_id)}/{str(relative_path).lstrip('/')}"
