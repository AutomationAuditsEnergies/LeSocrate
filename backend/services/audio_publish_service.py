import os
import re
import time
import hashlib
from datetime import datetime, timedelta, timezone

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient, BlobSasPermissions, ContentSettings, generate_blob_sas

from config import FRANCE_TZ
from services.platform_storage_service import (
    ensure_platform_audio_storage,
    platform_archive_container as _platform_archive_container,
    platform_audio_container as _platform_audio_container,
)
from utils.logger import get_logger

logger = get_logger(__name__)


def inspect_published_audio_manifest(platform_id, destination_prefix, filenames):
    """Compare an occurrence's immutable manifest with Blob Storage.

    PostgreSQL owns the expected filenames; Blob Storage is checked for the
    physical proof.  Empty objects and non-MP3 content types are considered
    missing/corrupt so a completed database flag can never hide a lost upload.
    """
    audio_conn = _audio_storage_connection_string()
    if not audio_conn:
        raise ValueError("Connexion Azure audio manquante")
    platform_id = int(platform_id)
    occurrence_prefix = _safe_occurrence_prefix(destination_prefix)
    if not occurrence_prefix:
        raise ValueError("Préfixe de séance audio requis")
    expected = {
        os.path.basename(str(name).split("?", 1)[0])
        for name in filenames
        if name
    }
    bsc = BlobServiceClient.from_connection_string(audio_conn)
    container = bsc.get_container_client(_platform_audio_container(platform_id))
    present = {}
    invalid = {}
    for filename in sorted(expected):
        blob_name = f"{occurrence_prefix}/{filename}"
        client = container.get_blob_client(blob_name)
        try:
            props = client.get_blob_properties()
        except Exception as exc:
            # Azure returns ResourceNotFoundError for a normal cache miss.  A
            # transient storage failure must still fail the scheduler tick so
            # it is retried instead of being mistaken for hundreds of misses.
            if (
                getattr(exc, "status_code", None) == 404
                or exc.__class__.__name__ == "ResourceNotFoundError"
            ):
                continue
            raise
        size = int(getattr(props, "size", 0) or 0)
        content_type = str(
            getattr(getattr(props, "content_settings", None), "content_type", "")
            or ""
        ).lower()
        proof = {
            "blob_name": blob_name,
            "etag": str(getattr(props, "etag", "") or ""),
            "size_bytes": size,
            "content_type": content_type,
        }
        if size <= 0 or (
            content_type and content_type not in {"audio/mpeg", "audio/mp3"}
        ):
            invalid[filename] = proof
        else:
            present[filename] = proof
    missing = sorted(expected - set(present))
    return {
        "expected": sorted(expected),
        "present": present,
        "missing": missing,
        "invalid": invalid,
        "ready": not missing,
        "destination_prefix": occurrence_prefix,
    }


def verify_published_audio_file(platform_id, destination_prefix, filename):
    """Return durable physical proofs only after reading the uploaded MP3."""
    state = inspect_published_audio_manifest(
        platform_id,
        destination_prefix,
        [filename],
    )
    clean_name = os.path.basename(str(filename).split("?", 1)[0])
    if not state["ready"]:
        raise RuntimeError(f"Fichier audio publié absent ou invalide: {clean_name}")
    audio_conn = _audio_storage_connection_string()
    bsc = BlobServiceClient.from_connection_string(audio_conn)
    container = bsc.get_container_client(
        _platform_audio_container(int(platform_id))
    )
    blob_name = state["present"][clean_name]["blob_name"]
    audio_bytes = container.get_blob_client(blob_name).download_blob().readall()
    if not audio_bytes:
        raise RuntimeError(f"Fichier audio publié vide: {clean_name}")
    return {
        **state["present"][clean_name],
        "filename": clean_name,
        "sha256": hashlib.sha256(audio_bytes).hexdigest(),
        "verified": True,
    }


def ensure_occurrence_playback_manifest(
    platform_id,
    folder_id,
    destination_prefix,
    filenames,
):
    """Build the playback manifest from already verified occurrence blobs."""
    state = inspect_published_audio_manifest(
        platform_id,
        destination_prefix,
        filenames,
    )
    if not state["ready"]:
        raise RuntimeError(
            "Manifeste de séance incomplet: " + ", ".join(state["missing"])
        )
    audio_conn = _audio_storage_connection_string()
    bsc = BlobServiceClient.from_connection_string(audio_conn)
    container = bsc.get_container_client(
        _platform_audio_container(int(platform_id))
    )
    from services.content_generation_service import _mp3_duration_seconds_no_ffprobe
    from services.adaptive_playback_service import (
        build_occurrence_playback_manifest,
        upload_occurrence_playback_manifest,
    )
    from services.day_playlist_service import resolve_folder_playlist

    resolved = resolve_folder_playlist(int(folder_id))
    if int(resolved.get("schema_version") or 1) != 2:
        return {"created": False, "reason": "legacy_v1"}
    durations = {}
    for filename, proof in state["present"].items():
        audio_bytes = (
            container.get_blob_client(proof["blob_name"])
            .download_blob()
            .readall()
        )
        durations[filename] = _mp3_duration_seconds_no_ffprobe(audio_bytes)
    manifest = build_occurrence_playback_manifest(
        resolved["playlist_items"],
        durations,
        folder_id=int(folder_id),
    )
    blob_name = upload_occurrence_playback_manifest(
        int(platform_id),
        state["destination_prefix"],
        manifest,
        blob_service_client=bsc,
    )
    return {"created": True, "blob_name": blob_name, "manifest": manifest}


def _audio_storage_connection_string():
    return os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING") or os.environ.get("AZURE_STORAGE_CONNECTION_STRING")


def _safe_archive_reason(reason):
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(reason or "auto-publish")).strip("-").lower()
    return cleaned or "auto-publish"


def _safe_occurrence_prefix(value):
    clean = str(value or "").strip().strip("/")
    if not clean:
        return ""
    if not re.fullmatch(r"course-sessions/[1-9][0-9]*", clean):
        raise ValueError("Préfixe de séance audio invalide")
    return clean


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

    # The legacy/current playlist lives at the container root. Occurrence
    # assets are immutable playback snapshots and must never be archived or
    # deleted when an operator republishes that legacy root playlist.
    source_blobs = [
        blob for blob in source_cc.list_blobs()
        if "/" not in str(blob.name or "").strip("/")
    ]
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
    destination_prefix=None,
    create_playback_manifest=False,
):
    """Copie les MP3 vers le cache privé global ou celui d'une occurrence."""
    tts_conn = os.environ.get("AZURE_TTS_STORAGE_CONNECTION_STRING")
    audio_conn = _audio_storage_connection_string()
    if not tts_conn or not audio_conn:
        raise ValueError("Connexions Azure audio manquantes")

    platform_id = int(platform_id)
    source_platform_id = int(source_platform_id or platform_id)
    folder_id = int(folder_id)
    wanted = {os.path.basename(str(name).split("?", 1)[0]) for name in (filenames or []) if name}
    dest_container = _platform_audio_container(platform_id)
    occurrence_prefix = _safe_occurrence_prefix(destination_prefix)
    if create_playback_manifest and not occurrence_prefix:
        raise ValueError("Le manifeste adaptatif exige un préfixe de séance")
    prefix = f"platform-{source_platform_id}/folder-{folder_id}/playlist/"

    tts_bsc = BlobServiceClient.from_connection_string(tts_conn)
    audio_bsc = BlobServiceClient.from_connection_string(audio_conn)
    ensure_platform_audio_storage(platform_id, blob_service_client=audio_bsc)
    source_cc = tts_bsc.get_container_client("audiostts")
    dest_cc = audio_bsc.get_container_client(dest_container)

    source_blobs = [
        blob for blob in source_cc.list_blobs(name_starts_with=prefix)
        if blob.name.endswith(".mp3")
        and (not wanted or blob.name.split("/")[-1] in wanted)
    ]
    source_entries = [
        {
            "container": source_cc,
            "blob_path": str(blob.name),
            "filename": str(blob.name).split("/")[-1],
            "registered": False,
        }
        for blob in source_blobs
    ]
    found_names = {entry["filename"] for entry in source_entries}

    # Reused modules keep their MP3s in the immutable teacher manifest. If the
    # mutable pipeline prefix has been archived or cleaned, publish directly
    # from that registered durable path without invoking TTS again.
    missing_wanted = wanted - found_names
    if missing_wanted:
        from repositories.teacher_asset_repository import resolve_registered_blob_path

        for filename in sorted(missing_wanted):
            asset = resolve_registered_blob_path(
                folder_id=folder_id,
                container_name="audiostts",
                relative_path=f"playlist/{filename}",
            )
            if not asset:
                continue
            asset_container = tts_bsc.get_container_client(asset["container_name"])
            asset_path = str(asset["blob_path"])
            if not asset_container.get_blob_client(asset_path).exists():
                continue
            source_entries.append(
                {
                    "container": asset_container,
                    "blob_path": asset_path,
                    "filename": filename,
                    "registered": bool(asset.get("registered")),
                }
            )

    unresolved_wanted = wanted - {
        entry["filename"] for entry in source_entries
    }
    if unresolved_wanted:
        raise ValueError(
            "Fichiers MP3 requis introuvables : "
            + ", ".join(sorted(unresolved_wanted))
        )

    if archive_existing and not source_entries:
        raise ValueError("Aucun nouveau fichier MP3 généré à publier")

    from repositories.teacher_asset_repository import resolve_folder_asset_origin
    from services.audio_asset_validation_service import (
        audio_sync_timing_files,
        inspect_audio_sync_readiness,
        validate_mp3_bytes,
    )
    from services.day_playlist_service import (
        is_course_audio_filename,
        resolve_folder_playlist,
    )

    playlist_contract = resolve_folder_playlist(folder_id)
    expected_duration_by_name = {
        filename: int(duration_seconds)
        for filename, duration_seconds, _file_type, _course_index
        in playlist_contract.get("playlist_items") or []
    }
    source_entries = [
        entry for entry in source_entries
        if entry["filename"] in expected_duration_by_name
    ]
    if not source_entries:
        raise ValueError("Aucun MP3 du manifeste verrouillé à publier")
    if wanted - {entry["filename"] for entry in source_entries}:
        raise ValueError("Un fichier demandé n'appartient pas au manifeste audio verrouillé")

    origin = resolve_folder_asset_origin(folder_id) or {}
    sync_folder_id = int(origin.get("source_folder_id") or folder_id)
    synced_course_files = audio_sync_timing_files(sync_folder_id)
    validation_errors = []
    media_durations = {}
    for entry in source_entries:
        filename = entry["filename"]
        try:
            audio_bytes = (
                entry["container"]
                .get_blob_client(entry["blob_path"])
                .download_blob()
                .readall()
            )
            proof = validate_mp3_bytes(
                filename,
                audio_bytes,
                expected_duration_seconds=expected_duration_by_name.get(filename),
            )
            if is_course_audio_filename(filename) and filename not in synced_course_files:
                raise ValueError(f"Synchronisation slides absente pour {filename}")
            entry["audio_bytes"] = audio_bytes
            media_durations[filename] = proof["duration_seconds"]
        except Exception as exc:
            validation_errors.append({"filename": filename, "error": str(exc)[:300]})
    if validation_errors:
        raise ValueError(f"Validation audio avant publication échouée: {validation_errors[:5]}")

    expected_course_files = {
        filename for filename in expected_duration_by_name
        if is_course_audio_filename(filename)
    }
    publishing_files = {entry["filename"] for entry in source_entries}
    if expected_course_files and expected_course_files.issubset(publishing_files):
        sync_readiness = inspect_audio_sync_readiness(
            sync_folder_id,
            expected_duration_by_name,
        )
        if not sync_readiness.get("ready"):
            raise ValueError(
                "Synchronisation slides incomplète avant publication: "
                f"{sync_readiness}"
            )

    archive_result = None
    if archive_existing and not occurrence_prefix:
        archive_result = archive_public_platform_audios(
            platform_id,
            reason=archive_reason,
            blob_service_client=audio_bsc,
        )

    copied = []
    copied_blob_names = []
    errors = []
    for entry in source_entries:
        filename = entry["filename"]
        try:
            audio_bytes = entry["audio_bytes"]
            destination_name = (
                f"{occurrence_prefix}/{filename}"
                if occurrence_prefix
                else filename
            )
            dest_cc.get_blob_client(destination_name).upload_blob(
                audio_bytes,
                overwrite=True,
                content_settings=ContentSettings(
                    content_type="audio/mpeg",
                    content_disposition=f'inline; filename="{filename}"',
                ),
            )
            copied.append(filename)
            copied_blob_names.append(destination_name)
            logger.info(
                "📣 Audio publié vers %s/%s (source_durable=%s)",
                dest_container,
                destination_name,
                bool(entry.get("registered")),
            )
        except Exception as exc:
            logger.error("❌ Publication audio %s échouée: %s", filename, exc)
            errors.append({"filename": filename, "error": str(exc)})

    playback_manifest = None
    playback_manifest_blob = None
    if create_playback_manifest and not errors:
        from services.adaptive_playback_service import (
            build_occurrence_playback_manifest,
            upload_occurrence_playback_manifest,
        )
        from services.day_playlist_service import resolve_folder_playlist

        resolved_playlist = resolve_folder_playlist(folder_id)
        if int(resolved_playlist.get("schema_version") or 1) != 2:
            raise ValueError(
                "Le manifeste adaptatif est réservé aux journées audio V2"
            )
        playback_manifest = build_occurrence_playback_manifest(
            resolved_playlist["playlist_items"],
            media_durations,
            folder_id=folder_id,
        )
        playback_manifest_blob = upload_occurrence_playback_manifest(
            platform_id,
            occurrence_prefix,
            playback_manifest,
            blob_service_client=audio_bsc,
        )

    return {
        "published": copied,
        "published_blob_names": copied_blob_names,
        "destination_prefix": occurrence_prefix or None,
        "publish_errors": errors,
        "archive": archive_result,
        "playback_manifest": playback_manifest,
        "playback_manifest_blob": playback_manifest_blob,
    }
