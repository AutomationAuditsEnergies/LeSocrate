import os
from azure.storage.blob import BlobServiceClient
from utils.logger import get_logger

logger = get_logger(__name__)

CONTAINER_DOCUMENTS = "documenttts"
CONTAINER_AUDIOS = "audiostts"


def _get_blob_service_client():
    conn_str = os.getenv("AZURE_TTS_STORAGE_CONNECTION_STRING")
    if not conn_str:
        raise ValueError("AZURE_TTS_STORAGE_CONNECTION_STRING non définie dans .env")
    return BlobServiceClient.from_connection_string(conn_str)


def build_blob_path(platform_id, folder_id, filename):
    """Construit le chemin du blob: platform-{id}/folder-{id}/{filename}"""
    return f"platform-{platform_id}/folder-{folder_id}/{filename}"


def upload_blob(container_name, blob_path, data):
    """Upload des bytes ou un file-like vers Azure Blob Storage"""
    client = _get_blob_service_client()
    blob_client = client.get_blob_client(container=container_name, blob=blob_path)
    blob_client.upload_blob(data, overwrite=True)
    logger.info(f"✅ Blob uploadé: {container_name}/{blob_path}")
    return blob_path


def download_blob(container_name, blob_path):
    """Télécharge un blob et retourne les bytes"""
    client = _get_blob_service_client()
    blob_client = client.get_blob_client(container=container_name, blob=blob_path)
    return blob_client.download_blob().readall()


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
