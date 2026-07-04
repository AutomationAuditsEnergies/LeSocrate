import os

from azure.storage.blob import BlobServiceClient, ContentSettings

from utils.logger import get_logger

logger = get_logger(__name__)


def _platform_audio_container(platform_id):
    platform_id = int(platform_id)
    if platform_id == 1:
        return os.environ.get("AZURE_AUDIO_CONTAINER", "formationaudio-dev")
    return os.environ.get(f"PLATFORM_{platform_id}_AUDIO_CONTAINER", f"formationaudio-p{platform_id}")


def publish_playlist_audio_to_platform(platform_id, folder_id, filenames=None):
    """Copie les MP3 générés depuis audiostts vers le container audio public."""
    tts_conn = os.environ.get("AZURE_TTS_STORAGE_CONNECTION_STRING")
    audio_conn = os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING") or os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not tts_conn or not audio_conn:
        raise ValueError("Connexions Azure audio manquantes")

    platform_id = int(platform_id)
    folder_id = int(folder_id)
    wanted = {os.path.basename(str(name).split("?", 1)[0]) for name in (filenames or []) if name}
    dest_container = _platform_audio_container(platform_id)
    prefix = f"platform-{platform_id}/folder-{folder_id}/playlist/"

    tts_bsc = BlobServiceClient.from_connection_string(tts_conn)
    audio_bsc = BlobServiceClient.from_connection_string(audio_conn)
    source_cc = tts_bsc.get_container_client("audiostts")
    dest_cc = audio_bsc.get_container_client(dest_container)

    copied = []
    errors = []
    for blob in source_cc.list_blobs(name_starts_with=prefix):
        filename = blob.name.split("/")[-1]
        if not filename.endswith(".mp3"):
            continue
        if wanted and filename not in wanted:
            continue
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

    return {"published": copied, "publish_errors": errors}
