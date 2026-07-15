import os
from datetime import datetime, timedelta

from config import FRANCE_TZ
from repositories.course_schedule_repository import (
    get_audio_generation_session,
    mark_audio_waiting_for_content,
)
from repositories.pipeline_repository import list_due_audio_generation_sessions
from services.formation_pipeline_service import get_expected_course_folders
from utils.logger import get_logger

logger = get_logger(__name__)


def _scheduled_tts_mode():
    value = (os.environ.get("SCHEDULED_AUDIO_TTS_MODE") or "").strip().lower() or None
    if value and value not in {"fish_audio", "gtts", "mock"}:
        raise ValueError("SCHEDULED_AUDIO_TTS_MODE doit être fish_audio, gtts ou mock")
    return value


def launch_scheduled_audio_session(
    session,
    *,
    tts_mode=None,
    stale_started_before=None,
    trigger_source="scheduled_24h",
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
    folder_index = session_index - 1
    if folder_index < 0 or folder_index >= len(folder_ids):
        mark_audio_waiting_for_content(session_id, updated_at=datetime.now(FRANCE_TZ))
        return {
            **result,
            "success": False,
            "skipped": True,
            "error": "Aucun dossier cours pour cette séance",
            "available_folder_count": len(folder_ids),
        }

    folder_id = int(folder_ids[folder_index])
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
            trigger_source=trigger_source,
            stale_started_before=stale_started_before,
        )
        if status == 400:
            mark_audio_waiting_for_content(session_id, updated_at=datetime.now(FRANCE_TZ))
        return {
            **result,
            "success": status == 202,
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

    result = launch_scheduled_audio_session(
        session,
        tts_mode=_scheduled_tts_mode(),
        trigger_source="manual_schedule_retry",
    )
    return result, int(result.get("status") or (202 if result.get("success") else 500))


def process_due_audio_generations(platform_ids=None, dry_run=False, horizon_hours=None):
    """Launch audio once for occurrences entering the 24-hour window.

    Database claims, fencing tokens and retry timestamps make repeated timer
    calls safe across restarts and multiple Azure instances.
    """
    horizon = float(horizon_hours or os.environ.get("SCHEDULED_AUDIO_HORIZON_HOURS", "24"))
    late_grace = float(os.environ.get("SCHEDULED_AUDIO_LATE_GRACE_HOURS", "2"))
    stale_retry_minutes = float(os.environ.get("SCHEDULED_AUDIO_STALE_RETRY_MINUTES", "10"))
    max_auto_attempts = max(1, int(os.environ.get("SCHEDULED_AUDIO_MAX_AUTO_ATTEMPTS", "4")))
    tts_mode = _scheduled_tts_mode()

    now = datetime.now(FRANCE_TZ)
    lower_bound = now - timedelta(hours=late_grace)
    upper_bound = now + timedelta(hours=horizon)
    stale_started_before = now - timedelta(minutes=stale_retry_minutes)

    due_sessions = list_due_audio_generation_sessions(
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        platform_ids=platform_ids,
        stale_updated_before=stale_started_before,
        retry_due_before=now,
        max_auto_attempts=max_auto_attempts,
    )

    results = []
    for session in due_sessions:
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
        results.append(
            launch_scheduled_audio_session(
                session,
                tts_mode=tts_mode,
                stale_started_before=stale_started_before,
            )
        )
    return results
