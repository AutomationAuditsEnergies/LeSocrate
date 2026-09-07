import os
import uuid
from datetime import datetime, timedelta

from config import FRANCE_TZ
from repositories.course_schedule_repository import (
    complete_audio_generation_session,
    get_audio_generation_session,
    mark_audio_generation_queued,
    mark_audio_waiting_for_content,
)
from repositories.pipeline_repository import list_due_audio_generation_sessions
from services.audio_service import is_explicit_schedule_occurrence
from services.day_playlist_service import is_course_audio_filename
from services.formation_pipeline_service import get_expected_course_folders
from utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_SCHEDULED_AUDIO_BATCH_SIZE = 50
_MAX_SCHEDULED_AUDIO_BATCH_SIZE = 1000
_DEFAULT_AUDIO_READY_HOURS_BEFORE = 72.0
_DEFAULT_AUDIO_BUILD_BUFFER_HOURS = 0.0


def _resolve_scheduled_folder(session: dict) -> tuple[int, int]:
    """Resolve the immutable day folder for one scheduled occurrence."""
    job_id = int(session.get("formation_job_id") or 0)
    if not job_id:
        raise ValueError("Aucun job pipeline lié")
    folder_ids = get_expected_course_folders(job_id).get("folder_ids") or []
    index = int(session.get("session_index") or 0) - 1
    if index < 0 or index >= len(folder_ids):
        raise ValueError("Aucun dossier cours pour cette séance")
    return job_id, int(folder_ids[index])


def _resume_text_pipeline_if_needed(job_id: int) -> dict | None:
    """Ensure a late H-72 reconciliation also catches an unfinished AI run."""
    try:
        from routes import formation_routes

        job = formation_routes.get_job(int(job_id))
        if not job or not job.get("auto_pilot_enabled"):
            return None
        if formation_routes._determine_next_ap_step(int(job_id)) is None:
            return None
        return formation_routes._dispatch_auto_pilot_tick(
            int(job_id),
            reason="scheduled_audio_h72_content_recovery",
        )
    except Exception:
        logger.exception("SCHEDULED_AUDIO_PIPELINE_RECOVERY_FAILED job=%s", job_id)
        return None


def _folder_content_ready(folder_id: int) -> bool:
    from services.content_generation_service import get_job_from_db

    content_job = get_job_from_db(int(folder_id))
    return bool(content_job and content_job.get("status") == "completed")


def _scheduled_voice_type(job_id: int, explicit_mode=None) -> str:
    mode = explicit_mode or _scheduled_tts_mode()
    if mode:
        return str(mode)
    try:
        from routes import formation_routes

        job = formation_routes.get_job(int(job_id)) or {}
        return str(job.get("auto_pilot_tts_mode") or "gtts").lower()
    except Exception:
        return "gtts"


def _enqueue_scheduled_audio_file(
    session: dict,
    *,
    job_id: int,
    folder_id: int,
    filename: str,
    expected_files: list[str],
    voice_type: str,
):
    from repositories.pipeline_repository import get_course_folder_identity
    from services.pipeline_queue import enqueue_work_item

    folder = get_course_folder_identity(int(folder_id))
    if not folder:
        raise ValueError(f"Dossier {folder_id} introuvable")
    session_id = int(session["id"])
    run_id = uuid.uuid4().hex
    clean_name = os.path.basename(str(filename).split("?", 1)[0])
    scope_key = f"scheduled_audio:{session_id}:{clean_name}"
    item = enqueue_work_item(
        pipeline_job_id=int(job_id),
        folder_id=int(folder_id),
        resource_key=f"course-session:{session_id}:audio:{clean_name}",
        task_type="scheduled_audio_item",
        scope_key=scope_key,
        run_id=run_id,
        dedupe_key=f"course-session:{session_id}:audio:{clean_name}:run:{run_id}",
        payload={
            "session_id": session_id,
            "folder_id": int(folder_id),
            "source_platform_id": int(folder["platform_id"]),
            "target_platform_id": int(session["platform_id"]),
            "filename": clean_name,
            "expected_files": list(expected_files),
            "destination_prefix": f"course-sessions/{session_id}",
            "voice_type": voice_type,
            "sync_slides": is_course_audio_filename(clean_name),
            "auto_generate_slides": True,
        },
        priority=100,
        max_attempts=5,
    )
    return item, item.run_id != run_id


def finalize_scheduled_audio_session_if_ready(
    session: dict,
    *,
    job_id: int,
    folder_id: int,
    expected_files: list[str],
    voice_type: str,
) -> dict:
    """Verify every physical file before committing aggregate completion."""
    from services.audio_publish_service import (
        ensure_occurrence_playback_manifest,
        inspect_published_audio_manifest,
    )

    session_id = int(session["id"])
    platform_id = int(session["platform_id"])
    destination_prefix = f"course-sessions/{session_id}"
    state = inspect_published_audio_manifest(
        platform_id,
        destination_prefix,
        expected_files,
    )
    if not state["ready"]:
        return {**state, "completed": False}

    from services.audio_asset_validation_service import inspect_audio_sync_readiness

    sync_readiness = inspect_audio_sync_readiness(folder_id, expected_files)
    if not sync_readiness.get("ready"):
        return {
            **state,
            "ready": False,
            "completed": False,
            "reason": "audio_sync_incomplete",
            "audio_sync_status": sync_readiness,
        }

    playback = ensure_occurrence_playback_manifest(
        platform_id,
        int(folder_id),
        destination_prefix,
        expected_files,
    )
    from routes.formation_routes import (
        _finalize_scheduled_audio_module_if_ready,
        _persist_daily_teacher_audio_assets,
    )

    daily_manifest = _persist_daily_teacher_audio_assets(int(job_id), int(folder_id))
    module_readiness = _finalize_scheduled_audio_module_if_ready(
        int(job_id),
        voice_type,
        completing_session_id=session_id,
    )
    completed_at = datetime.now(FRANCE_TZ)
    completed = complete_audio_generation_session(
        session_id,
        completed_at=completed_at,
    )
    # Another file worker may have won the final compare-and-set. The manifest
    # is nevertheless complete, so this is an idempotent success.
    current = get_audio_generation_session(platform_id, session_id) or {}
    aggregate_completed = bool(
        completed or current.get("audio_generation_completed_at")
    )
    return {
        **state,
        "completed": aggregate_completed,
        "completed_at": completed_at.isoformat(),
        "playback_manifest": playback,
        "daily_asset_manifest": daily_manifest,
        "module_readiness": module_readiness,
    }


def reconcile_scheduled_audio_session(session: dict, *, tts_mode=None) -> dict:
    """Queue exactly the missing files for one occurrence and nothing else."""
    session_id = int(session["id"])
    platform_id = int(session["platform_id"])
    result = {
        "session_id": session_id,
        "platform_id": platform_id,
        "session_index": int(session.get("session_index") or 0),
        "scheduled_at": session.get("scheduled_at"),
    }
    try:
        job_id, folder_id = _resolve_scheduled_folder(session)
        result.update({"formation_job_id": job_id, "folder_id": folder_id})
        from services.day_playlist_service import required_audio_filenames
        from services.audio_publish_service import inspect_published_audio_manifest

        expected_files = sorted(required_audio_filenames(folder_id))
        if not expected_files:
            raise ValueError("Le manifeste audio attendu est vide")
        state = inspect_published_audio_manifest(
            platform_id,
            f"course-sessions/{session_id}",
            expected_files,
        )
        voice_type = _scheduled_voice_type(job_id, tts_mode)
        if state["ready"]:
            finalized = finalize_scheduled_audio_session_if_ready(
                session,
                job_id=job_id,
                folder_id=folder_id,
                expected_files=expected_files,
                voice_type=voice_type,
            )
            if finalized.get("completed"):
                return {
                    **result,
                    "success": True,
                    "skipped": True,
                    "reason": "manifest_already_complete",
                    "manifest": finalized,
                }
            sync_status = finalized.get("audio_sync_status") or {}
            missing_sync_files = sync_status.get("missing_course_files") or []
            if sync_status.get("missing_slide_ids") and not missing_sync_files:
                missing_sync_files = sync_status.get("expected_course_files") or []
            if not missing_sync_files:
                return {
                    **result,
                    "success": False,
                    "skipped": True,
                    "reason": finalized.get("reason") or "manifest_not_ready",
                    "manifest": finalized,
                }
            state = {
                **state,
                "ready": False,
                "missing": sorted(set(missing_sync_files)),
                "audio_sync_status": sync_status,
            }

        if not _folder_content_ready(folder_id):
            mark_audio_waiting_for_content(
                session_id,
                updated_at=datetime.now(FRANCE_TZ),
            )
            recovery = _resume_text_pipeline_if_needed(job_id)
            return {
                **result,
                "success": False,
                "skipped": True,
                "waiting_for_content": True,
                "missing_files": state["missing"],
                "pipeline_recovery": recovery,
            }

        # Persist aggregate intent before publishing outbox notifications. A
        # very fast audio replica can therefore never finish a file while the
        # session still claims to be completed from an older manifest.
        mark_audio_generation_queued(
            session_id,
            job_id=job_id,
            folder_id=folder_id,
            queued_at=datetime.now(FRANCE_TZ),
            reset_completed=bool(session.get("audio_generation_completed_at")),
        )
        queued = []
        active = []
        for filename in state["missing"]:
            item, deduplicated = _enqueue_scheduled_audio_file(
                session,
                job_id=job_id,
                folder_id=folder_id,
                filename=filename,
                expected_files=expected_files,
                voice_type=voice_type,
            )
            target = active if deduplicated else queued
            target.append({
                "filename": filename,
                "work_item_id": item.id,
                "status": item.status,
            })
        return {
            **result,
            "success": True,
            "missing_files": state["missing"],
            "queued_files": queued,
            "active_files": active,
            "expected_file_count": len(expected_files),
        }
    except Exception as exc:
        logger.exception("SCHEDULED_AUDIO_RECONCILIATION_FAILED session=%s", session_id)
        return {**result, "success": False, "error": str(exc)}


def _scheduled_tts_mode():
    value = (os.environ.get("SCHEDULED_AUDIO_TTS_MODE") or "").strip().lower() or None
    if value and value not in {"fish_audio", "gtts", "mock"}:
        raise ValueError("SCHEDULED_AUDIO_TTS_MODE doit être fish_audio, gtts ou mock")
    return value


def _scheduled_audio_batch_size() -> int:
    raw = os.environ.get(
        "SCHEDULED_AUDIO_BATCH_SIZE",
        str(_DEFAULT_SCHEDULED_AUDIO_BATCH_SIZE),
    )
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "SCHEDULED_AUDIO_BATCH_SIZE invalide (%r), fallback=%s",
            raw,
            _DEFAULT_SCHEDULED_AUDIO_BATCH_SIZE,
        )
        value = _DEFAULT_SCHEDULED_AUDIO_BATCH_SIZE
    return max(1, min(value, _MAX_SCHEDULED_AUDIO_BATCH_SIZE))


def _scheduled_audio_window_hours(horizon_hours=None) -> tuple[float, float]:
    """Return the rolling H-72 reconciliation window.

    At every tick, every validated day at or below H-72 is inspected and each
    missing file is queued immediately. An optional build buffer remains for
    deployments that deliberately want to enter the window earlier, but the
    product default is exactly 72 hours.
    """
    ready_raw = (
        horizon_hours
        if horizon_hours is not None
        else os.environ.get(
            "SCHEDULED_AUDIO_READY_HOURS_BEFORE",
            os.environ.get(
                "SCHEDULED_AUDIO_HORIZON_HOURS",
                str(_DEFAULT_AUDIO_READY_HOURS_BEFORE),
            ),
        )
    )
    buffer_raw = os.environ.get(
        "SCHEDULED_AUDIO_BUILD_BUFFER_HOURS",
        str(_DEFAULT_AUDIO_BUILD_BUFFER_HOURS),
    )
    try:
        ready_hours = float(ready_raw)
        buffer_hours = float(buffer_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("La fenêtre de préparation audio H-72 est invalide") from exc
    if ready_hours <= 0 or buffer_hours < 0:
        raise ValueError("La fenêtre de préparation audio H-72 est invalide")
    return ready_hours, buffer_hours


def launch_scheduled_audio_session(
    session,
    *,
    tts_mode=None,
    stale_started_before=None,
    trigger_source="scheduled_h72_preparation",
    wait_for_completion=False,
):
    """Launch one occurrence through the durable session claim."""
    session_id = int(session["id"])
    platform_id = int(session["platform_id"])
    session_index = int(session["session_index"])
    job_id = session.get("formation_job_id")
    result = {
        "session_id": session_id,
        "platform_id": platform_id,
        "platform_name": session.get("name") or "",
        "session_index": session_index,
        "scheduled_at": session.get("scheduled_at"),
        "formation_job_id": job_id,
    }
    if not job_id:
        mark_audio_waiting_for_content(session_id, updated_at=datetime.now(FRANCE_TZ))
        return {**result, "success": False, "skipped": True, "error": "Aucun job pipeline lié"}

    folder_ids = get_expected_course_folders(int(job_id)).get("folder_ids") or []
    module_day_id = session.get("module_day_id")
    if is_explicit_schedule_occurrence(session):
        try:
            from services.audio_service import (
                resolve_v2_course_session_manifest,
            )

            resolve_v2_course_session_manifest(
                platform_id,
                session,
            )
        except Exception as exc:
            mark_audio_waiting_for_content(
                session_id,
                updated_at=datetime.now(FRANCE_TZ),
            )
            logger.error(
                "SCHEDULED_AUDIO_V2_MANIFEST_UNAVAILABLE "
                "session=%s module_day_id=%s error=%s",
                session_id,
                module_day_id,
                exc,
                exc_info=True,
            )
            return {
                **result,
                "success": False,
                "skipped": True,
                "error": str(exc),
                "module_day_id": module_day_id,
            }

    # The generation source can differ from the occurrence's target folder
    # when a durable module is reused. Keep the historic source-folder mapping
    # after validating that the target occurrence owns a sound V2 manifest.
    folder_index = session_index - 1
    folder_id = (
        int(folder_ids[folder_index])
        if 0 <= folder_index < len(folder_ids)
        else None
    )

    if folder_id is None:
        mark_audio_waiting_for_content(session_id, updated_at=datetime.now(FRANCE_TZ))
        return {
            **result,
            "success": False,
            "skipped": True,
            "error": "Aucun dossier cours pour cette séance",
            "available_folder_count": len(folder_ids),
        }

    result["folder_id"] = folder_id
    try:
        from routes.formation_routes import start_folder_audio_generation

        payload = {
            "force_all": True,
            "preserve_existing": True,
            "sync_slides": True,
            "auto_generate_slides": True,
            **({"tts_mode": tts_mode} if tts_mode else {}),
        }
        launch_payload, status = start_folder_audio_generation(
            int(job_id),
            folder_id,
            payload,
            schedule_session_id=session_id,
            target_platform_id=platform_id,
            trigger_source=trigger_source,
            stale_started_before=stale_started_before,
            wait_for_completion=wait_for_completion,
        )
        if status == 400:
            mark_audio_waiting_for_content(session_id, updated_at=datetime.now(FRANCE_TZ))
        return {
            **result,
            "success": status in {200, 202},
            "status": status,
            "launch": launch_payload,
        }
    except Exception as exc:
        logger.error(
            "Audio planifié non lancé session=%s: %s",
            session_id,
            exc,
            exc_info=True,
        )
        return {**result, "success": False, "error": str(exc)}


def retry_scheduled_audio_generation(platform_id: int, session_id: int):
    """Manually resume a failed occurrence without erasing completed files."""
    session = get_audio_generation_session(int(platform_id), int(session_id))
    if not session:
        return {"success": False, "error": "Séance introuvable"}, 404
    if session.get("status") not in {"planned", "active"}:
        return {"success": False, "error": "Cette séance ne peut plus être relancée"}, 409
    if session.get("audio_generation_completed_at"):
        return {"success": True, "already_completed": True}, 200
    if str(session.get("audio_generation_status") or "pending") != "error":
        return {"success": False, "error": "La génération audio n'est pas en erreur"}, 409

    result = reconcile_scheduled_audio_session(
        session,
        tts_mode=_scheduled_tts_mode(),
    )
    return result, (202 if result.get("success") else 500)


def process_due_audio_generations(
    platform_ids=None,
    dry_run=False,
    horizon_hours=None,
    *,
    wait_for_completion=False,
):
    """Reconcile every expected audio file inside the rolling H-72 window.

    Database claims, fencing tokens and retry timestamps make repeated timer
    calls safe across restarts and multiple Azure instances. Every pass also
    revisits completed occurrences so a Blob missing after a prior success is
    put back into PostgreSQL/outbox/Service Bus immediately.
    """
    ready_hours, build_buffer_hours = _scheduled_audio_window_hours(horizon_hours)
    claim_horizon_hours = ready_hours + build_buffer_hours
    late_grace = float(os.environ.get("SCHEDULED_AUDIO_LATE_GRACE_HOURS", "2"))
    stale_retry_minutes = float(os.environ.get("SCHEDULED_AUDIO_STALE_RETRY_MINUTES", "10"))
    max_auto_attempts = max(1, int(os.environ.get("SCHEDULED_AUDIO_MAX_AUTO_ATTEMPTS", "4")))
    batch_size = _scheduled_audio_batch_size()
    tts_mode = _scheduled_tts_mode()

    now = datetime.now(FRANCE_TZ)
    lower_bound = now - timedelta(hours=late_grace)
    upper_bound = now + timedelta(hours=claim_horizon_hours)
    stale_started_before = now - timedelta(minutes=stale_retry_minutes)

    due_sessions = list_due_audio_generation_sessions(
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        platform_ids=platform_ids,
        stale_updated_before=stale_started_before,
        retry_due_before=now,
        max_auto_attempts=max_auto_attempts,
        batch_size=batch_size,
        reconcile_manifest=True,
    )

    results = []
    for session in due_sessions:
        # V2 contract: TTS starts at H-72 for the exact immutable day
        # manifest. V1 keeps its historic proactive build buffer.
        if is_explicit_schedule_occurrence(session):
            scheduled_at = session.get("scheduled_at")
            if not isinstance(scheduled_at, datetime):
                scheduled_at = datetime.fromisoformat(
                    str(scheduled_at).replace("Z", "+00:00")
                )
            if scheduled_at.tzinfo is None:
                scheduled_at = FRANCE_TZ.localize(scheduled_at)
            else:
                scheduled_at = scheduled_at.astimezone(FRANCE_TZ)
            if scheduled_at > now + timedelta(hours=ready_hours):
                continue
        if dry_run:
            results.append({
                "session_id": session["id"],
                "platform_id": session["platform_id"],
                "session_index": session["session_index"],
                "scheduled_at": session["scheduled_at"],
                "formation_job_id": session.get("formation_job_id"),
                "success": True,
                "dry_run": True,
            })
            continue
        launched = reconcile_scheduled_audio_session(session, tts_mode=tts_mode)
        results.append(launched)
    return results
