import os
import hashlib
from functools import lru_cache
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.core.exceptions import ResourceExistsError
from utils.logger import get_logger

logger = get_logger(__name__)

CONTAINER_DOCUMENTS = os.getenv("AZURE_TTS_DOCUMENT_CONTAINER", "documenttts")
CONTAINER_AUDIOS = os.getenv("AZURE_TTS_AUDIO_CONTAINER", "audiostts")
CONTAINER_ARTIFACTS = os.getenv("AZURE_PIPELINE_ARTIFACT_CONTAINER", "pipeline-artifacts")


def _content_settings_for_blob(blob_path):
    """Headers Azure adaptés aux fichiers servis directement au navigateur."""
    lower = (blob_path or "").lower()
    if lower.endswith(".mp3"):
        return ContentSettings(
            content_type="audio/mpeg",
            content_disposition=f'inline; filename="{os.path.basename(blob_path)}"',
        )
    if lower.endswith(".json"):
        return ContentSettings(content_type="application/json; charset=utf-8")
    if lower.endswith(".txt"):
        return ContentSettings(content_type="text/plain; charset=utf-8")
    if lower.endswith(".md"):
        return ContentSettings(content_type="text/markdown; charset=utf-8")
    if lower.endswith(".pdf"):
        return ContentSettings(content_type="application/pdf")
    return None


@lru_cache(maxsize=1)
def _get_blob_service_client():
    """Reuse the SDK transport/pool and prefer Azure Managed Identity.

    A connection string remains a local/legacy fallback. Production can set
    ``AZURE_TTS_STORAGE_ACCOUNT_URL`` and optionally
    ``AZURE_MANAGED_IDENTITY_CLIENT_ID`` without storing an account key.
    """
    account_url = (
        os.getenv("AZURE_TTS_STORAGE_ACCOUNT_URL")
        or os.getenv("AZURE_STORAGE_ACCOUNT_URL")
    )
    if account_url:
        from azure.identity import DefaultAzureCredential

        client_id = (os.getenv("AZURE_MANAGED_IDENTITY_CLIENT_ID") or "").strip() or None
        credential = DefaultAzureCredential(managed_identity_client_id=client_id)
        return BlobServiceClient(account_url=account_url.rstrip("/"), credential=credential)
    conn_str = (
        os.getenv("AZURE_TTS_STORAGE_CONNECTION_STRING")
        or os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    )
    if not conn_str:
        raise ValueError(
            "AZURE_TTS_STORAGE_CONNECTION_STRING/AZURE_STORAGE_CONNECTION_STRING non définie"
        )
    return BlobServiceClient.from_connection_string(conn_str)


def build_blob_path(platform_id, folder_id, filename):
    """Construit le chemin du blob: platform-{id}/folder-{id}/{filename}"""
    return f"platform-{platform_id}/folder-{folder_id}/{filename}"


@lru_cache(maxsize=32)
def ensure_private_container(container_name):
    """Create a private container once; never enable anonymous access."""
    client = _get_blob_service_client()
    try:
        client.create_container(container_name)
        logger.info("✅ Container Blob privé créé: %s", container_name)
    except ResourceExistsError:
        pass
    return container_name


def upload_blob(container_name, blob_path, data, *, metadata=None):
    """Upload des bytes ou un file-like vers Azure Blob Storage"""
    client = _get_blob_service_client()
    blob_client = client.get_blob_client(container=container_name, blob=blob_path)
    effective_metadata = dict(metadata or {})
    if isinstance(data, (bytes, bytearray, memoryview)):
        effective_metadata["sha256"] = hashlib.sha256(bytes(data)).hexdigest()
    blob_client.upload_blob(
        data,
        overwrite=True,
        content_settings=_content_settings_for_blob(blob_path),
        metadata=effective_metadata or None,
    )
    if (
        container_name == CONTAINER_AUDIOS
        and str(blob_path or "").lower().endswith(".mp3")
        and isinstance(data, (bytes, bytearray, memoryview))
    ):
        try:
            from services.audio_waveform_service import (
                create_waveform_for_uploaded_bytes,
                waveform_cache_blob_path,
            )

            cache_client = client.get_blob_client(
                container=container_name,
                blob=waveform_cache_blob_path(blob_path),
            )
            create_waveform_for_uploaded_bytes(
                blob_client,
                cache_client,
                bytes(data),
                audio_properties=blob_client.get_blob_properties(),
            )
        except Exception as exc:
            # Audio publication must remain available even if peak extraction
            # is unsupported for an unusual codec.
            logger.warning("⚠️ Forme d'onde non générée pour %s: %s", blob_path, exc)
    logger.info(f"✅ Blob uploadé: {container_name}/{blob_path}")
    return blob_path


def download_blob(container_name, blob_path):
    """Télécharge un blob et retourne les bytes"""
    client = _get_blob_service_client()
    blob_client = client.get_blob_client(container=container_name, blob=blob_path)
    return blob_client.download_blob().readall()


def blob_exists(container_name, blob_path):
    """Retourne True si le blob existe dans Azure Storage."""
    client = _get_blob_service_client()
    blob_client = client.get_blob_client(container=container_name, blob=blob_path)
    return blob_client.exists()


def delete_blob(container_name, blob_path):
    """Supprime un blob"""
    client = _get_blob_service_client()
    blob_client = client.get_blob_client(container=container_name, blob=blob_path)
    try:
        blob_client.delete_blob()
        logger.info(f"🗑️ Blob supprimé: {container_name}/{blob_path}")
    except Exception as e:
        logger.warning(f"⚠️ Blob introuvable: {container_name}/{blob_path}: {e}")


def delete_blobs_by_prefix(container_name, prefix):
    """Supprime tous les blobs avec un préfixe donné"""
    client = _get_blob_service_client()
    container_client = client.get_container_client(container_name)
    blobs = container_client.list_blobs(name_starts_with=prefix)
    count = 0
    for blob in blobs:
        container_client.delete_blob(blob.name)
        count += 1
    if count:
        logger.info(f"🗑️ {count} blob(s) supprimé(s) avec préfixe {container_name}/{prefix}")
    return count


def copy_blobs_by_prefix(container_name, source_prefix, target_prefix):
    """Copie tous les blobs d'un préfixe source vers un préfixe target (server-side copy).

    Utilisé pour cloner les cours d'une plateforme source vers une plateforme cible
    (principe 1 RNCP = 1 module durable réutilisé par N promos).

    Retourne le nombre de blobs copiés.
    """
    client = _get_blob_service_client()
    container_client = client.get_container_client(container_name)
    blobs = list(container_client.list_blobs(name_starts_with=source_prefix))
    count = 0
    for blob in blobs:
        # Reconstruire le chemin cible en remplaçant le préfixe
        target_path = target_prefix + blob.name[len(source_prefix):]
        source_blob = container_client.get_blob_client(blob.name)
        target_blob = container_client.get_blob_client(target_path)
        # Server-side copy Azure (rapide, pas de download local)
        target_blob.start_copy_from_url(source_blob.url)
        count += 1
    if count:
        logger.info(f"📋 {count} blob(s) copiés : {container_name}/{source_prefix} → {target_prefix}")
    return count
