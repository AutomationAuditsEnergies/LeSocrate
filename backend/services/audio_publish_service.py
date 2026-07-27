import os

from azure.storage.blob import BlobServiceClient, ContentSettings

from utils.logger import get_logger

logger = get_logger(__name__)


def _platform_audio_container(platform_id):
    platform_id = int(platform_id)
    if platform_id == 1:
        return os.environ.get("AZURE_AUDIO_CONTAINER", "formationaudio-dev")
    return os.environ.get(
        f"PLATFORM_{platform_id}_AUDIO_CONTAINER",
        f"formationaudio-p{platform_id}",
    )


def publish_playlist_audio_to_platform(platform_id, folder_id, filenames=None):
    """Publie la playlist privée d'un cours vers le container audio des élèves."""
    tts_conn = os.environ.get("AZURE_TTS_STORAGE_CONNECTION_STRING")
    audio_conn = (
        os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING")
        or os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    )
    if not tts_conn or not audio_conn:
        raise ValueError("Connexions Azure audio manquantes")

    platform_id = int(platform_id)
    folder_id = int(folder_id)
    wanted = {
        os.path.basename(str(name).split("?", 1)[0])
        for name in (filenames or [])
        if name
    }
    destination_container = _platform_audio_container(platform_id)
    source_prefix = f"platform-{platform_id}/folder-{folder_id}/playlist/"

    tts_service = BlobServiceClient.from_connection_string(tts_conn)
    audio_service = BlobServiceClient.from_connection_string(audio_conn)
    source_container = tts_service.get_container_client("audiostts")
    destination = audio_service.get_container_client(destination_container)

    published = []
    errors = []
    for source_blob in source_container.list_blobs(name_starts_with=source_prefix):
        filename = source_blob.name.rsplit("/", 1)[-1]
        if not filename.lower().endswith(".mp3"):
            continue
        if wanted and filename not in wanted:
            continue
        try:
            audio_bytes = (
                source_container
                .get_blob_client(source_blob.name)
                .download_blob()
                .readall()
            )
            if not audio_bytes:
                raise ValueError("fichier source vide")
            destination.get_blob_client(filename).upload_blob(
                audio_bytes,
                overwrite=True,
                content_settings=ContentSettings(
                    content_type="audio/mpeg",
                    content_disposition=f'inline; filename="{filename}"',
                ),
            )
            published.append(filename)
            logger.info(
                "AUDIO_PUBLISH_SUCCESS platform_id=%s folder_id=%s container=%s filename=%s bytes=%s",
                platform_id,
                folder_id,
                destination_container,
                filename,
                len(audio_bytes),
            )
        except Exception as exc:
            logger.error(
                "AUDIO_PUBLISH_FAILED platform_id=%s folder_id=%s filename=%s error=%s",
                platform_id,
                folder_id,
                filename,
                exc,
            )
            errors.append({"filename": filename, "error": str(exc)})

    return {
        "published": published,
        "publish_errors": errors,
        "destination_container": destination_container,
    }
