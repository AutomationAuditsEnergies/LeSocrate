"""Azure manifesting for reusable, immutable AI-teacher resources."""

from __future__ import annotations

import json
import mimetypes
import os
from pathlib import PurePosixPath
from typing import Any, Iterable

from azure.core.exceptions import ResourceExistsError

from repositories.teacher_asset_repository import (
    CANONICAL_AUDIO_PLAYLIST_PATHS,
    get_module_asset_identity,
    get_module_audio_manifest_readiness,
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


def _snapshot_blob_once(container: Any, source_path: str, destination_path: str) -> Any:
    """Stream one private blob into its immutable teacher namespace once.

    The stream stays chunked, so a long training day never has to fit in worker
    memory. ``overwrite=False`` also protects the first validated version when
    a retry races with another worker.
    """
    source = container.get_blob_client(source_path)
    destination = container.get_blob_client(destination_path)
    if destination.exists():
        return destination.get_blob_properties()

    source_props = source.get_blob_properties()
    metadata = dict(getattr(source_props, "metadata", None) or {})
    metadata.update({"canonical": "true", "source_layout": "platform-folder-v1"})
    downloader = source.download_blob(max_concurrency=2)
    try:
        destination.upload_blob(
            downloader.chunks(),
            overwrite=False,
            length=int(getattr(source_props, "size", 0) or 0) or None,
            content_settings=getattr(source_props, "content_settings", None),
            metadata=metadata,
            max_concurrency=2,
        )
    except ResourceExistsError:
        # Idempotent concurrent finalization: the winning writer owns the
        # immutable copy and this worker simply inventories it.
        pass
    return destination.get_blob_properties()


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
    """Snapshot and register the immutable assets owned by one AI teacher.

    Audio is copied once from the mutable pipeline layout into the module's
    durable namespace. Every future promotion or centre resolves that same
    canonical blob through the manifest; no new TTS generation is required.
    """
    module_id = int(module_id)
    center_id = int(center_account_id)
    source_platform_id = int(source_platform_id)
    identity = get_module_asset_identity(module_id, center_id)
    if not identity:
        raise ValueError("Module durable introuvable pour ce centre")

    existing_count = module_asset_count(module_id)
    if existing_count and not force:
        readiness = get_module_audio_manifest_readiness(module_id)
        if readiness.get("ready"):
            return {
                "module_id": module_id,
                "registered": existing_count,
                "reused_manifest": True,
                "audio_ready": True,
                "audio_asset_count": int(readiness.get("audio_asset_count") or 0),
                "required_folder_count": int(readiness.get("required_folder_count") or 0),
            }
        logger.warning(
            "TEACHER_ASSET_MANIFEST_REPAIR module_id=%s assets=%s",
            module_id,
            existing_count,
        )

    blob_service = _get_blob_service_client()
    manifest: list[dict[str, Any]] = []
    voice_profile = identity.get("voice_type")
    generator_version = os.getenv("TEACHER_ASSET_GENERATOR_VERSION", "pipeline-v1")
    asset_namespace = str(identity.get("asset_namespace") or "").strip().strip("/")
    if not asset_namespace:
        raise ValueError("Namespace durable du professeur IA absent")

    requested_folder_ids = sorted({int(folder_id) for folder_id in source_folder_ids})
    from services.day_playlist_service import required_audio_filenames

    required_audio_paths_by_folder = {
        folder_id: {
            f"playlist/{filename}"
            for filename in required_audio_filenames(folder_id)
        }
        for folder_id in requested_folder_ids
    }
    for source_folder_id in requested_folder_ids:
        prefix = f"platform-{source_platform_id}/folder-{source_folder_id}/"
        for container_name in (CONTAINER_DOCUMENTS, CONTAINER_AUDIOS):
            container = blob_service.get_container_client(container_name)
            for blob in container.list_blobs(name_starts_with=prefix, include=["metadata"]):
                relative_path = str(blob.name)[len(prefix):]
                if not relative_path:
                    continue
                manifest_blob = blob
                blob_path = str(blob.name)
                source_layout = "platform-folder-v1"
                if container_name == CONTAINER_AUDIOS:
                    blob_path = (
                        f"{asset_namespace}/folders/{source_folder_id}/{relative_path}"
                    )
                    manifest_blob = _snapshot_blob_once(
                        container,
                        str(blob.name),
                        blob_path,
                    )
                    source_layout = "teacher-module-v1"
                manifest.append({
                    "source_folder_id": source_folder_id,
                    "asset_kind": _asset_kind(container_name, relative_path),
                    "logical_key": f"{container_name}:folder:{source_folder_id}:{relative_path}",
                    "container_name": container_name,
                    "blob_path": blob_path,
                    "content_sha256": _blob_sha256(manifest_blob),
                    "byte_size": int(getattr(manifest_blob, "size", 0) or 0),
                    "mime_type": _content_type(manifest_blob, relative_path),
                    "language": "fr-FR",
                    "voice_profile": voice_profile if container_name == CONTAINER_AUDIOS else None,
                    "generator_version": generator_version,
                    "generation_params_json": json.dumps({
                        "etag": str(getattr(manifest_blob, "etag", "") or ""),
                        "source_layout": source_layout,
                        "source_blob_path": str(blob.name),
                    }),
                    "storage_tier": str(getattr(manifest_blob, "blob_tier", None) or "Hot"),
                })

    playlist_paths_by_folder: dict[int, set[str]] = {}
    for asset in manifest:
        if asset.get("asset_kind") != "audio":
            continue
        logical_key = str(asset.get("logical_key") or "")
        relative_path = logical_key.split(":", 3)[-1].lstrip("/")
        if relative_path in required_audio_paths_by_folder.get(
            int(asset["source_folder_id"]),
            CANONICAL_AUDIO_PLAYLIST_PATHS,
        ):
            playlist_paths_by_folder.setdefault(int(asset["source_folder_id"]), set()).add(
                relative_path
            )
    incomplete_folders = [
        folder_id
        for folder_id in requested_folder_ids
        if not required_audio_paths_by_folder.get(
            folder_id,
            CANONICAL_AUDIO_PLAYLIST_PATHS,
        ).issubset(playlist_paths_by_folder.get(folder_id, set()))
    ]
    if incomplete_folders:
        raise RuntimeError(
            "Snapshot audio professeur incomplet pour le(s) dossier(s) : "
            + ", ".join(str(folder_id) for folder_id in incomplete_folders)
        )

    registered = register_module_assets(module_id, center_id, manifest)
    logger.info(
        "TEACHER_ASSET_MANIFEST_READY module_id=%s center_id=%s assets=%s",
        module_id,
        center_id,
        registered,
    )
    readiness = get_module_audio_manifest_readiness(module_id)
    return {
        "module_id": module_id,
        "registered": registered,
        "reused_manifest": False,
        "folder_audio_ready": True,
        "audio_ready": bool(readiness.get("ready")),
        "audio_asset_count": int(readiness.get("audio_asset_count") or 0),
        "required_folder_count": int(readiness.get("required_folder_count") or 0),
    }


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
