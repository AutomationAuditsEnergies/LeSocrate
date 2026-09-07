"""Idempotent Azure Storage provisioning for dynamically-created platforms.

The paid teacher worker creates its tenant row in PostgreSQL, outside the
legacy HR route which historically created Blob containers as a side effect.
This module keeps storage provisioning explicit, retry-safe and independent
from the HTTP process.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    generate_blob_sas,
)

from utils.logger import get_logger


logger = get_logger(__name__)

_CONTAINER_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$")
_ARCHIVE_DEFAULTS = {
    1: "formationaudio-archives",
    2: "formationaudio-archives-p2",
    3: "formationaudio-p3-archives",
    4: "formationaudio-p4-archives",
}


def _platform_id(platform: int | dict[str, Any]) -> int:
    raw = platform.get("id") if isinstance(platform, dict) else platform
    if raw is None or isinstance(raw, bool):
        raise ValueError("Identifiant de plateforme Azure invalide")
    parsed = int(raw)
    if parsed <= 0:
        raise ValueError("Identifiant de plateforme Azure invalide")
    return parsed


def _platform_value(platform: int | dict[str, Any], key: str) -> str | None:
    if not isinstance(platform, dict):
        return None
    value = str(platform.get(key) or "").strip()
    return value or None


def _validated_container_name(value: str) -> str:
    name = str(value or "").strip()
    if (
        len(name) < 3
        or len(name) > 63
        or "--" in name
        or not _CONTAINER_NAME_RE.fullmatch(name)
    ):
        raise ValueError("Nom de container Azure invalide")
    return name


def platform_audio_container(platform: int | dict[str, Any]) -> str:
    platform_id = _platform_id(platform)
    env_name = "AZURE_AUDIO_CONTAINER" if platform_id == 1 else f"PLATFORM_{platform_id}_AUDIO_CONTAINER"
    default = "formationaudio-dev" if platform_id == 1 else f"formationaudio-p{platform_id}"
    return _validated_container_name(
        os.environ.get(env_name) or _platform_value(platform, "audio_container") or default
    )


def platform_archive_container(platform: int | dict[str, Any]) -> str:
    platform_id = _platform_id(platform)
    env_name = (
        "AZURE_AUDIO_ARCHIVE_CONTAINER"
        if platform_id == 1
        else f"PLATFORM_{platform_id}_AUDIO_ARCHIVE_CONTAINER"
    )
    default = _ARCHIVE_DEFAULTS.get(platform_id, f"formationaudio-p{platform_id}-archives")
    return _validated_container_name(
        os.environ.get(env_name) or _platform_value(platform, "archive_container") or default
    )


def platform_pdf_container(platform: int | dict[str, Any]) -> str:
    platform_id = _platform_id(platform)
    env_name = f"PLATFORM_{platform_id}_PDF_CONTAINER"
    default = "formationpdf" if platform_id == 1 else f"formationpdf-p{platform_id}"
    return _validated_container_name(
        os.environ.get(env_name) or _platform_value(platform, "pdf_container") or default
    )


def _audio_connection_string() -> str:
    value = (
        os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING")
        or os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        or ""
    ).strip()
    if not value:
        raise ValueError("Connexion Azure audio manquante")
    return value


def _pdf_connection_string() -> str:
    value = (os.environ.get("AZURE_STORAGE_CONNECTION_STRING") or "").strip()
    if not value:
        raise ValueError("Connexion Azure PDF manquante")
    return value


def _ensure_private_container(blob_service_client, container_name: str) -> bool:
    """Create one private container; never rewrite an existing container ACL."""
    container = blob_service_client.get_container_client(container_name)
    try:
        # Omitting public_access creates a private container.  On an idempotent
        # retry ResourceExistsError is deliberately ignored: changing the ACL
        # of an existing tenant would be a destructive migration.
        container.create_container()
        logger.info("PLATFORM_STORAGE_CONTAINER_CREATED container=%s access=private", container_name)
        return True
    except ResourceExistsError:
        return False


def ensure_platform_audio_storage(
    platform: int | dict[str, Any],
    *,
    blob_service_client=None,
) -> dict[str, Any]:
    """Provision private playback and archive containers, safely on every retry."""
    client = blob_service_client or BlobServiceClient.from_connection_string(
        _audio_connection_string()
    )
    audio_container = platform_audio_container(platform)
    archive_container = platform_archive_container(platform)
    created = {
        "audio": _ensure_private_container(client, audio_container),
        "archive": _ensure_private_container(client, archive_container),
    }
    return {
        "audio_container": audio_container,
        "archive_container": archive_container,
        "created": created,
    }


def ensure_platform_storage(
    platform: int | dict[str, Any],
    *,
    audio_blob_service_client=None,
    pdf_blob_service_client=None,
) -> dict[str, Any]:
    """Provision every per-platform container before fulfillment continues.

    Partial creation is intentional and safe: if Azure fails after one
    container, the durable order retry observes ResourceExistsError for that
    container and resumes with the missing ones.
    """
    audio_result = ensure_platform_audio_storage(
        platform,
        blob_service_client=audio_blob_service_client,
    )
    pdf_client = pdf_blob_service_client or BlobServiceClient.from_connection_string(
        _pdf_connection_string()
    )
    pdf_container = platform_pdf_container(platform)
    pdf_created = _ensure_private_container(pdf_client, pdf_container)
    return {
        **audio_result,
        "pdf_container": pdf_container,
        "created": {**audio_result["created"], "pdf": pdf_created},
    }


def issue_platform_audio_read_url(
    platform: int | dict[str, Any],
    audio_key: str,
    *,
    expires_at: int | float,
    blob_service_client=None,
) -> str:
    """Return a short, read-only SAS URL for one server-selected audio blob.

    The URL is issued only after occurrence-bound authorization.  It contains
    no student identity and cannot read another blob or write to storage.
    """
    key = str(audio_key or "").strip().strip("/")
    parts = key.split("/") if key else []
    root_key = len(parts) == 1
    occurrence_key = (
        len(parts) == 3
        and parts[0] == "course-sessions"
        and parts[1].isdigit()
        and int(parts[1]) > 0
    )
    filename = parts[-1] if parts else ""
    if (
        not (root_key or occurrence_key)
        or "\\" in key
        or filename != os.path.basename(filename)
        or not filename.lower().endswith(".mp3")
    ):
        raise ValueError("Clé audio invalide")

    expiry_epoch = int(expires_at)
    if expiry_epoch <= int(time.time()):
        raise ValueError("Expiration audio invalide")

    client = blob_service_client or BlobServiceClient.from_connection_string(
        _audio_connection_string()
    )
    credential = getattr(client, "credential", None)
    account_key = getattr(credential, "account_key", None)
    account_name = str(getattr(client, "account_name", "") or "").strip()
    if not account_name or not account_key:
        # User-delegation SAS with managed identity can be added independently;
        # current audio publishing already requires a connection string/key.
        raise RuntimeError("Clé Azure requise pour signer le flux audio privé")

    container = platform_audio_container(platform)
    sas = generate_blob_sas(
        account_name=account_name,
        container_name=container,
        blob_name=key,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.fromtimestamp(expiry_epoch, tz=timezone.utc),
    )
    blob_url = client.get_blob_client(container=container, blob=key).url
    return f"{blob_url}?{sas}"
