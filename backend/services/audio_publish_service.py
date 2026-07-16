import os
import re
import time
from datetime import datetime, timedelta, timezone

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient, BlobSasPermissions, ContentSettings, generate_blob_sas

from config import FRANCE_TZ
from utils.logger import get_logger

logger = get_logger(__name__)

_ARCHIVE_DEFAULTS = {
    1: "formationaudio-archives",
    2: "formationaudio-archives-p2",
    3: "formationaudio-p3-archives",
    4: "formationaudio-p4-archives",
}


def _platform_audio_container(platform_id):
    platform_id = int(platform_id)
    if platform_id == 1:
        return os.environ.get("AZURE_AUDIO_CONTAINER", "formationaudio-dev")
    return os.environ.get(f"PLATFORM_{platform_id}_AUDIO_CONTAINER", f"formationaudio-p{platform_id}")


def _platform_archive_container(platform_id):
    platform_id = int(platform_id)
    if platform_id == 1:
        return os.environ.get("AZURE_AUDIO_ARCHIVE_CONTAINER", _ARCHIVE_DEFAULTS[1])
    return os.environ.get(
        f"PLATFORM_{platform_id}_AUDIO_ARCHIVE_CONTAINER",
        _ARCHIVE_DEFAULTS.get(platform_id, f"formationaudio-archives-p{platform_id}"),
    )


def _audio_storage_connection_string():
    return os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING") or os.environ.get("AZURE_STORAGE_CONNECTION_STRING")


def _safe_archive_reason(reason):
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(reason or "auto-publish")).strip("-").lower()
    return cleaned or "auto-publish"


def archive_public_platform_audios(platform_id, *, reason="auto-publish", blob_service_client=None):
    """Archive puis vide les audios actuellement visibles par la classe."""
    audio_conn = _audio_storage_connection_string()
    if not audio_conn and blob_service_client is None:
        raise ValueError("Connexion Azure audio manquante")

    platform_id = int(platform_id)
    bsc = blob_service_client or BlobServiceClient.from_connection_string(audio_conn)
    source_container = _platform_audio_container(platform_id)
    archive_container = _platform_archive_container(platform_id)
    source_cc = bsc.get_container_client(source_container)
    archive_cc = bsc.get_container_client(archive_container)

    try:
        # Archives de séance et versions précédentes restent privées. Seul le
        # cache de diffusion courant peut être exposé derrière Front Door.
        archive_cc.create_container()
    except ResourceExistsError:
        pass

    source_blobs = list(source_cc.list_blobs())
    if not source_blobs:
        return {
            "archived": 0,
            "deleted": 0,
            "archive_container": archive_container,
            "archive_folder": None,
        }

    archive_folder = (
        datetime.now(FRANCE_TZ).strftime("%Y-%m-%d_%Hh%M%S")
        + f"/plateforme-{platform_id}/{_safe_archive_reason(reason)}"
    )
    account_name = bsc.account_name
    account_key = bsc.credential.account_key
    expiry = datetime.now(timezone.utc) + timedelta(hours=2)
    copied_names = []

    logger.info("📦 Archive audio automatique P%s: %s fichier(s) -> %s/%s", platform_id, len(source_blobs), archive_container, archive_folder)
    for blob in source_blobs:
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=source_container,
            blob_name=blob.name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=expiry,
        )
        source_url = f"https://{account_name}.blob.core.windows.net/{source_container}/{blob.name}?{sas_token}"
        dest_name = f"{archive_folder}/{blob.name}"
        dest_blob = archive_cc.get_blob_client(dest_name)
        dest_blob.start_copy_from_url(source_url)

        for _ in range(60):
            props = dest_blob.get_blob_properties()
            if props.copy.status == "success":
                break
            if props.copy.status == "failed":
                raise RuntimeError(f"Copie archive échouée pour {blob.name}: {props.copy.status_description}")
            time.sleep(0.5)
        else:
            raise RuntimeError(f"Timeout lors de l'archive de {blob.name}")

        copied_names.append(blob.name)

    archive_names = {
        item.name.replace(f"{archive_folder}/", "", 1)
        for item in archive_cc.list_blobs(name_starts_with=archive_folder + "/")
    }
    source_names = {blob.name for blob in source_blobs}
    missing = source_names - archive_names
    if missing:
        raise RuntimeError(f"Archive audio incomplète: {len(missing)} fichier(s) manquant(s)")

    deleted = 0
    for blob in source_blobs:
        source_cc.delete_blob(blob.name)
        deleted += 1

    return {
        "archived": len(copied_names),
        "deleted": deleted,
        "archive_container": archive_container,
        "archive_folder": archive_folder,
    }


def publish_playlist_audio_to_platform(
    platform_id,
    folder_id,
    filenames=None,
    *,
    source_platform_id=None,
    archive_existing=False,
    archive_reason="auto-publish",
):
    """Copie les MP3 générés depuis audiostts vers le container audio public."""
    tts_conn = os.environ.get("AZURE_TTS_STORAGE_CONNECTION_STRING")
    audio_conn = _audio_storage_connection_string()
    if not tts_conn or not audio_conn:
        raise ValueError("Connexions Azure audio manquantes")

    platform_id = int(platform_id)
    source_platform_id = int(source_platform_id or platform_id)
    folder_id = int(folder_id)
    wanted = {os.path.basename(str(name).split("?", 1)[0]) for name in (filenames or []) if name}
    dest_container = _platform_audio_container(platform_id)
    prefix = f"platform-{source_platform_id}/folder-{folder_id}/playlist/"

    tts_bsc = BlobServiceClient.from_connection_string(tts_conn)
    audio_bsc = BlobServiceClient.from_connection_string(audio_conn)
    source_cc = tts_bsc.get_container_client("audiostts")
    dest_cc = audio_bsc.get_container_client(dest_container)

    source_blobs = [
        blob for blob in source_cc.list_blobs(name_starts_with=prefix)
        if blob.name.endswith(".mp3")
        and (not wanted or blob.name.split("/")[-1] in wanted)
    ]
    if archive_existing and not source_blobs:
        raise ValueError("Aucun nouveau fichier MP3 généré à publier")

    archive_result = None
    if archive_existing:
        archive_result = archive_public_platform_audios(
            platform_id,
            reason=archive_reason,
            blob_service_client=audio_bsc,
        )

    copied = []
    errors = []
    for blob in source_blobs:
        filename = blob.name.split("/")[-1]
        try:
            audio_bytes = source_cc.get_blob_client(blob.name).download_blob().readall()
            dest_cc.get_blob_client(filename).upload_blob(
                audio_bytes,
                overwrite=True,
                content_settings=ContentSettings(
                    content_type="audio/mpeg",
                    content_disposition=f'inline; filename="{filename}"',
                ),
            )
            copied.append(filename)
            logger.info("📣 Audio publié vers %s/%s", dest_container, filename)
        except Exception as exc:
            logger.error("❌ Publication audio %s échouée: %s", filename, exc)
            errors.append({"filename": filename, "error": str(exc)})

    return {
        "published": copied,
        "publish_errors": errors,
        "archive": archive_result,
    }
