"""Durable handlers for HR dashboard playlist generation.

The HTTP process only validates and enqueues. All expensive audio work runs
under the PostgreSQL queue lease so progress, retries and duplicate exclusion
survive Azure restarts and multiple instances.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import os
from typing import Any

from azure.storage.blob import BlobServiceClient

from config import FRANCE_TZ, PIPELINE_DATABASE_BACKEND
from database.db import get_db_connection
from database.postgres import get_postgres_connection
from repositories.pipeline_repository import get_course_folder_identity
from services.audio_publish_service import publish_playlist_audio_to_platform
from services.pipeline_queue.contracts import (
    PermanentWorkError,
    RetryableWorkError,
    WorkItem,
    WorkResult,
)
from utils.logger import get_logger


logger = get_logger(__name__)
_POSTGRES_BACKENDS = {"postgres", "postgresql", "supabase"}


@contextmanager
def _pipeline_connection():
    if PIPELINE_DATABASE_BACKEND in _POSTGRES_BACKENDS:
        with get_postgres_connection() as conn:
            yield conn, "%s", True
        return
    conn = get_db_connection()
    try:
        yield conn, "?", False
    finally:
        conn.close()


def _finalize_module_if_ready(folder_id: int, voice_type: str) -> dict | None:
    if voice_type in (None, "", "mock"):
        return None

    with _pipeline_connection() as (conn, ph, is_postgres):
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT cf.platform_id, cf.formation_job_id, j.tp_name, j.rncp_code,
                   COALESCE(j.schedule_schema_version, 1) AS schedule_schema_version
            FROM cours_folders cf
            LEFT JOIN formation_pipeline_jobs j ON j.id = cf.formation_job_id
            WHERE cf.id = {ph}
            """,
            (folder_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        if is_postgres:
            platform_id = row["platform_id"]
            formation_job_id = row["formation_job_id"]
            tp_name = row["tp_name"]
            rncp = row["rncp_code"]
            schedule_schema_version = int(row["schedule_schema_version"] or 1)
        else:
            platform_id, formation_job_id, tp_name, rncp, schedule_schema_version = row
            schedule_schema_version = int(schedule_schema_version or 1)
        if not formation_job_id:
            return None
        cursor.execute(
            f"""
            SELECT id FROM cours_folders
            WHERE formation_job_id = {ph}
            ORDER BY position ASC, id ASC
            """,
            (formation_job_id,),
        )
        folder_ids = [int(r["id"] if is_postgres else r[0]) for r in cursor.fetchall()]

    if not folder_ids:
        return None
    tts_connection = os.environ.get("AZURE_TTS_STORAGE_CONNECTION_STRING")
    if not tts_connection:
        return {"ready": False, "reason": "AZURE_TTS_STORAGE_CONNECTION_STRING manquant"}

    container = BlobServiceClient.from_connection_string(tts_connection).get_container_client(
        "audiostts"
    )
    manifest_issues = []
    from services.day_playlist_service import is_course_audio_filename

    for candidate_folder_id in folder_ids:
        prefix = f"platform-{platform_id}/folder-{candidate_folder_id}/playlist/"
        if schedule_schema_version == 2:
            from services.day_playlist_service import required_audio_filenames

            expected_names = set(required_audio_filenames(candidate_folder_id))
            available_names = {
                os.path.basename(blob.name)
                for blob in container.list_blobs(name_starts_with=prefix)
                if blob.name.endswith(".mp3")
            }
            missing_names = sorted(expected_names - available_names)
            extra_names = sorted(available_names - expected_names)
            if missing_names or extra_names:
                issue = {
                    "folder_id": candidate_folder_id,
                }
                if missing_names:
                    issue["missing_files"] = missing_names
                if extra_names:
                    issue["extra_files"] = extra_names
                manifest_issues.append(issue)
            continue
        course_count = sum(
            1
            for blob in container.list_blobs(name_starts_with=prefix)
            if is_course_audio_filename(os.path.basename(blob.name))
        )
        if course_count < 7:
            manifest_issues.append({
                "folder_id": candidate_folder_id,
                "course_mp3": course_count,
            })
    if manifest_issues:
        # Keep the historic ``missing`` response key for callers while V2
        # entries can now describe either side of an exact-manifest mismatch.
        return {"ready": False, "missing": manifest_issues}

    if schedule_schema_version == 2:
        # Reuse the canonical V2 finalizer once every immutable day manifest is
        # present. The legacy SQL below intentionally remains V1-only.
        from routes.formation_routes import _finalize_audio_ready_state

        return _finalize_audio_ready_state(int(formation_job_id), voice_type)

    with _pipeline_connection() as (conn, ph, is_postgres):
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT center_account_id FROM platform_config WHERE id = {ph}",
            (platform_id,),
        )
        center_row = cursor.fetchone()
        center_account_id = (
            center_row["center_account_id"] if is_postgres and center_row else center_row[0] if center_row else None
        )
        cursor.execute(
            f"UPDATE platform_config SET status = 'ready' WHERE id = {ph} AND status = 'pending'",
            (platform_id,),
        )
        cursor.execute(
            f"SELECT id, version FROM formation_modules WHERE source_pipeline_job_id = {ph}",
            (formation_job_id,),
        )
        existing = cursor.fetchone()
        if existing:
            module_id = existing["id"] if is_postgres else existing[0]
            version = existing["version"] if is_postgres else existing[1]
            cursor.execute(
                f"""
                UPDATE formation_modules
                SET source_platform_id = COALESCE(source_platform_id, {ph}),
                    center_account_id = COALESCE(center_account_id, {ph}),
                    voice_type = {ph}, voice_updated_at = CURRENT_TIMESTAMP,
                    status = 'validated',
                    validated_at = COALESCE(validated_at, CURRENT_TIMESTAMP)
                WHERE id = {ph}
                """,
                (platform_id, center_account_id, voice_type, module_id),
            )
            module_created = False
        else:
            if center_account_id is None:
                cursor.execute(
                    f"SELECT COUNT(*) AS n FROM formation_modules WHERE rncp_code = {ph} AND center_account_id IS NULL",
                    (rncp or "",),
                )
            else:
                cursor.execute(
                    f"SELECT COUNT(*) AS n FROM formation_modules WHERE rncp_code = {ph} AND center_account_id = {ph}",
                    (rncp or "", center_account_id),
                )
            count_row = cursor.fetchone()
            count = int(count_row["n"] if is_postgres else count_row[0])
            version = f"{datetime.now(FRANCE_TZ).year}-v{count + 1}"
            insert_sql = f"""
                INSERT INTO formation_modules
                    (rncp_code, tp_name, version, status, source_pipeline_job_id,
                     source_platform_id, center_account_id, voice_type,
                     voice_updated_at, validated_at)
                VALUES ({ph}, {ph}, {ph}, 'validated', {ph}, {ph}, {ph}, {ph},
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
            params = (
                rncp or "",
                tp_name or f"Job {formation_job_id}",
                version,
                formation_job_id,
                platform_id,
                center_account_id,
                voice_type,
            )
            if is_postgres:
                cursor.execute(insert_sql + " RETURNING id", params)
                module_id = int(cursor.fetchone()["id"])
            else:
                cursor.execute(insert_sql, params)
                module_id = int(cursor.lastrowid)
            module_created = True
        conn.commit()

    logger.info(
        "HR_PLAYLIST_MODULE_FINALIZED work_item_folder=%s pipeline_job_id=%s "
        "platform_id=%s module_id=%s created=%s voice_type=%s",
        folder_id,
        formation_job_id,
        platform_id,
        module_id,
        module_created,
        voice_type,
    )
    return {
        "ready": True,
        "formation_job_id": formation_job_id,
        "module_id": module_id,
        "module_created": module_created,
        "module_version": version,
        "voice_type": voice_type,
    }


def _base_progress(item: WorkItem, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "running",
        "step": 0,
        "total_steps": int(payload.get("total_steps") or 24),
        "message": payload.get("initial_message") or "Démarrage audio...",
        "result": None,
        "voice_type": payload.get("voice_type"),
        "filename": payload.get("filename"),
        "sync_slides": bool(payload.get("sync_slides")),
        "work_item_id": item.id,
        "attempt": item.attempt_count,
    }


def _validate_item_identity(item: WorkItem, payload: dict[str, Any]) -> tuple[int, int]:
    folder_id = int(item.folder_id or payload.get("folder_id") or 0)
    if folder_id <= 0:
        raise PermanentWorkError("folder_id manquant dans le job audio HR")
    folder = get_course_folder_identity(folder_id)
    if not folder:
        raise PermanentWorkError(f"Dossier {folder_id} introuvable")
    platform_id = int(folder["platform_id"])
    expected_platform_id = int(payload.get("platform_id") or platform_id)
    if platform_id != expected_platform_id:
        raise PermanentWorkError(
            f"Plateforme du dossier modifiée: attendue P{expected_platform_id}, actuelle P{platform_id}"
        )
    if item.pipeline_job_id is not None and folder.get("formation_job_id") != item.pipeline_job_id:
        raise PermanentWorkError(
            f"Le dossier {folder_id} n'appartient plus au pipeline {item.pipeline_job_id}"
        )
    return folder_id, platform_id


def _folder_schedule_schema_version(folder_id: int) -> int:
    with _pipeline_connection() as (conn, ph, is_postgres):
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT COALESCE(j.schedule_schema_version, 1) AS schedule_schema_version
            FROM cours_folders cf
            LEFT JOIN formation_pipeline_jobs j ON j.id = cf.formation_job_id
            WHERE cf.id = {ph}
            """,
            (int(folder_id),),
        )
        row = cursor.fetchone()
        if not row:
            return 1
        value = row["schedule_schema_version"] if is_postgres else row[0]
        return int(value or 1)


def _publish(platform_id: int, folder_id: int, filenames=None, *, archive=False) -> dict:
    try:
        result = publish_playlist_audio_to_platform(
            platform_id,
            folder_id,
            filenames,
            archive_existing=archive,
            archive_reason=f"folder-{folder_id}-playlist",
        )
        errors = result.get("publish_errors") or []
        if errors:
            raise RetryableWorkError(
                f"Publication audio incomplète P{platform_id}/F{folder_id}: {errors[:3]}"
            )
        return result
    except RetryableWorkError:
        logger.exception(
            "HR_PLAYLIST_PUBLISH_INCOMPLETE platform_id=%s folder_id=%s filenames=%s",
            platform_id,
            folder_id,
            filenames,
        )
        raise
    except Exception as exc:
        logger.exception(
            "HR_PLAYLIST_PUBLISH_FAILED platform_id=%s folder_id=%s filenames=%s",
            platform_id,
            folder_id,
            filenames,
        )
        raise RetryableWorkError(
            f"Publication audio impossible P{platform_id}/F{folder_id}: {exc}"
        ) from exc


def handle_hr_playlist_work_item(item: WorkItem, lease) -> WorkResult:
    if item.task_type not in {"hr_playlist_generate", "hr_playlist_item"}:
        raise PermanentWorkError(f"task_type audio HR inconnu: {item.task_type}")

    payload = dict(item.payload or {})
    folder_id, platform_id = _validate_item_identity(item, payload)
    schedule_schema_version = _folder_schedule_schema_version(folder_id)
    if (
        item.task_type == "hr_playlist_generate"
        and schedule_schema_version == 2
        and (
            not bool(payload.get("has_script"))
            or bool(payload.get("playlist_mock"))
        )
    ):
        raise PermanentWorkError(
            "Une journée V2 doit être synthétisée depuis son script et son "
            "manifeste immuable ; la playlist historique fixe est interdite."
        )
    progress_state = _base_progress(item, payload)

    def on_progress(step, total, message):
        progress_state.update(
            {
                "status": "running",
                "step": int(step),
                "total_steps": int(total),
                "message": str(message),
                "attempt": item.attempt_count,
            }
        )
        lease.report_progress(progress_state)

    lease.report_progress(progress_state)
    if item.attempt_count > 1:
        logger.warning(
            "HR_PLAYLIST_JOB_RESUMED work_item_id=%s folder_id=%s attempt=%s fence=%s",
            item.id,
            folder_id,
            item.attempt_count,
            item.lease_version,
        )

    voice_type = str(payload.get("voice_type") or "fish_audio")
    voice_label = str(payload.get("voice_label") or voice_type)
    use_basic_tts = voice_type == "gtts"

    if item.task_type == "hr_playlist_item":
        filename = os.path.basename(str(payload.get("filename") or "").split("?", 1)[0])
        if not filename:
            raise PermanentWorkError("filename manquant dans le job audio HR")
        from services.content_generation_service import generate_audio_from_script

        generated = generate_audio_from_script(
            folder_id,
            on_progress=on_progress,
            force_all=True,
            basic_tts=use_basic_tts,
            target_filename=filename,
            sync_slides=bool(payload.get("sync_slides")),
            auto_generate_slides=bool(payload.get("auto_generate_slides")),
            slide_max_slides=int(payload.get("slide_max_slides") or 60),
            slide_pace=str(payload.get("slide_pace") or "normal"),
            preserve_existing=item.attempt_count > 1,
        )
        result = {
            "status": "completed",
            "generated": generated["generated"],
            "skipped": generated["skipped"],
            "source": "script",
            "voice_type": voice_type,
            "filename": filename,
            "sync_slides": bool(payload.get("sync_slides")),
            "publish": _publish(platform_id, folder_id, [filename]),
        }
        message = f"✅ {filename} généré en {voice_label}"
        total_steps = 1
    elif bool(payload.get("has_script")) and not bool(payload.get("playlist_mock")):
        from services.content_generation_service import generate_audio_from_script

        include_breaks = bool(payload.get("include_breaks", True))
        preserve_existing = bool(payload.get("preserve_existing")) or item.attempt_count > 1
        generated = generate_audio_from_script(
            folder_id,
            on_progress=on_progress,
            force_all=bool(payload.get("force_all")),
            mock=bool(payload.get("script_mock")),
            basic_tts=use_basic_tts,
            sync_slides=bool(payload.get("sync_slides")),
            auto_generate_slides=bool(payload.get("auto_generate_slides")),
            slide_max_slides=int(payload.get("slide_max_slides") or 60),
            slide_pace=str(payload.get("slide_pace") or "normal"),
            include_breaks=include_breaks,
            parallel_breaks=bool(payload.get("parallel_breaks")),
            preserve_existing=preserve_existing,
        )
        result = {
            "status": "completed",
            "generated": generated["generated"],
            "skipped": generated["skipped"],
            "files": generated.get("files", []),
            "source": "script",
            "voice_type": voice_type,
            "include_breaks": include_breaks,
            "parallel_breaks": bool(payload.get("parallel_breaks")),
            "preserve_existing": preserve_existing,
        }
        if schedule_schema_version == 2:
            # V2 is an immutable manifest contract. ``generated["files"]`` is
            # only the subset synthesized during this run, so it must never be
            # used as the publication allow-list. Passing the complete locked
            # manifest also makes the publisher ignore any stale source MP3.
            from services.day_playlist_service import required_audio_filenames

            publish_filenames = sorted(required_audio_filenames(folder_id))
        else:
            # Preserve the historical V1 behavior: a full run publishes every
            # MP3 found under the folder prefix, while course-only runs publish
            # the generated subset.
            publish_filenames = None if include_breaks else result["files"]
        if voice_type == "mock":
            result["publish"] = {
                "skipped": True,
                "reason": "mock_audio_is_never_learner_visible",
            }
        else:
            result["publish"] = _publish(
                platform_id,
                folder_id,
                publish_filenames,
                archive=True,
            )
            module_finalize = _finalize_module_if_ready(folder_id, voice_type)
            if module_finalize:
                result["module_finalize"] = module_finalize
        file_count = len(result.get("files") or [])
        scope_label = (
            f"{file_count} audios"
            if include_breaks
            else f"{file_count} cours"
        )
        message = (
            f"✅ Terminé ({voice_label}, {scope_label}) : {result['generated']} généré(s), "
            f"{result.get('skipped', 0)} conservé(s)"
        )
        total_steps = int(progress_state.get("total_steps") or 24)
    else:
        from services.playlist_tts_service import generate_playlist_for_folder

        result = generate_playlist_for_folder(
            platform_id,
            folder_id,
            progress_callback=on_progress,
            mock=bool(payload.get("playlist_mock")),
        )
        result["voice_type"] = voice_type
        result["publish"] = _publish(platform_id, folder_id, archive=True)
        message = f"✅ Terminé ({voice_label}) : {result.get('generated', '?')} fichiers générés"
        total_steps = int(progress_state.get("total_steps") or 24)

    lease.checkpoint()
    return WorkResult(
        result={
            **progress_state,
            "status": "completed",
            "step": total_steps,
            "total_steps": total_steps,
            "message": message,
            "result": result,
            "attempt": item.attempt_count,
        }
    )


def handle_scheduled_audio_work_item(item: WorkItem, lease) -> WorkResult:
    """Generate, publish and prove one missing file for a scheduled day."""
    if item.task_type != "scheduled_audio_item":
        raise PermanentWorkError(f"task_type audio planifié inconnu: {item.task_type}")
    payload = dict(item.payload or {})
    session_id = int(payload.get("session_id") or 0)
    folder_id = int(item.folder_id or payload.get("folder_id") or 0)
    target_platform_id = int(payload.get("target_platform_id") or 0)
    source_platform_id = int(payload.get("source_platform_id") or 0)
    filename = os.path.basename(str(payload.get("filename") or "").split("?", 1)[0])
    if not session_id or not folder_id or not target_platform_id or not source_platform_id or not filename:
        raise PermanentWorkError("Identité incomplète du fichier audio planifié")

    folder = get_course_folder_identity(folder_id)
    if not folder or int(folder["platform_id"]) != source_platform_id:
        raise PermanentWorkError("Le dossier source de l'audio planifié a changé")
    from repositories.course_schedule_repository import (
        get_audio_generation_session,
        mark_audio_generation_processing,
    )
    session = get_audio_generation_session(target_platform_id, session_id)
    if not session or int(session.get("platform_id") or 0) != target_platform_id:
        raise PermanentWorkError("Séance audio planifiée introuvable")
    if session.get("status") not in {"planned", "active"}:
        raise PermanentWorkError("La séance audio n'est plus générable")

    from services.day_playlist_service import required_audio_filenames
    expected_files = sorted(required_audio_filenames(folder_id))
    if filename not in expected_files:
        raise PermanentWorkError(
            f"Le fichier {filename} n'appartient pas au manifeste verrouillé"
        )
    destination_prefix = f"course-sessions/{session_id}"
    voice_type = str(payload.get("voice_type") or "gtts").lower()
    if voice_type not in {"fish_audio", "gtts", "mock"}:
        raise PermanentWorkError(f"Moteur TTS planifié invalide: {voice_type}")

    now = datetime.now(FRANCE_TZ)
    mark_audio_generation_processing(session_id, updated_at=now)
    progress = {
        "status": "running",
        "step": 0,
        "total_steps": 1,
        "message": f"Rattrapage de {filename}",
        "filename": filename,
        "session_id": session_id,
        "attempt": item.attempt_count,
    }
    lease.report_progress(progress)
    lease.checkpoint()

    from services.audio_publish_service import (
        inspect_published_audio_manifest,
        publish_playlist_audio_to_platform,
        verify_published_audio_file,
    )
    before = inspect_published_audio_manifest(
        target_platform_id,
        destination_prefix,
        [filename],
    )
    generation = {"generated": 0, "skipped": 1, "reason": "already_published"}
    publish = {"published": [], "publish_errors": []}
    if not before["ready"]:
        from services.content_generation_service import generate_audio_from_script

        generation = generate_audio_from_script(
            folder_id,
            on_progress=lambda step, total, message: lease.report_progress({
                **progress,
                "step": int(step),
                "total_steps": max(1, int(total)),
                "message": str(message),
            }),
            force_all=True,
            mock=voice_type == "mock",
            basic_tts=voice_type == "gtts",
            target_filename=filename,
            sync_slides=bool(payload.get("sync_slides")),
            auto_generate_slides=bool(payload.get("auto_generate_slides")),
            preserve_existing=True,
        )
        lease.checkpoint()
        publish = publish_playlist_audio_to_platform(
            target_platform_id,
            folder_id,
            filenames=[filename],
            source_platform_id=source_platform_id,
            archive_existing=False,
            destination_prefix=destination_prefix,
            create_playback_manifest=False,
        )
        if publish.get("publish_errors") or filename not in set(publish.get("published") or []):
            raise RetryableWorkError(
                f"Publication incomplète du fichier planifié {filename}"
            )
    lease.checkpoint()
    proof = verify_published_audio_file(
        target_platform_id,
        destination_prefix,
        filename,
    )
    lease.checkpoint()

    from services.scheduled_audio_service import finalize_scheduled_audio_session_if_ready

    finalization = finalize_scheduled_audio_session_if_ready(
        session,
        job_id=int(item.pipeline_job_id or session.get("formation_job_id") or 0),
        folder_id=folder_id,
        expected_files=expected_files,
        voice_type=voice_type,
    )
    return WorkResult(result={
        "status": "completed",
        "step": 1,
        "total_steps": 1,
        "message": f"{filename} vérifié",
        "session_id": session_id,
        "filename": filename,
        "generation": generation,
        "publish": publish,
        "proof": proof,
        "manifest_ready": bool(finalization.get("ready")),
        "session_completed": bool(finalization.get("completed")),
        "finalization": finalization,
        "attempt": item.attempt_count,
    })
