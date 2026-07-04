import os
from datetime import datetime, timedelta

from config import FRANCE_TZ
from repositories.pipeline_repository import list_due_audio_generation_sessions
from services.formation_pipeline_service import get_expected_course_folders
from utils.logger import get_logger

logger = get_logger(__name__)


def process_due_audio_generations(platform_ids=None, dry_run=False, horizon_hours=None):
    """Lance l'audio des journées prévues dans la fenêtre de préparation.

    Une séance terminée ne peut pas être relancée automatiquement. Une séance
    passée en erreur avant finalisation reste retentable par le timer suivant.
    """
    horizon = float(horizon_hours or os.environ.get("SCHEDULED_AUDIO_HORIZON_HOURS", "24"))
    late_grace = float(os.environ.get("SCHEDULED_AUDIO_LATE_GRACE_HOURS", "2"))
    tts_mode = (os.environ.get("SCHEDULED_AUDIO_TTS_MODE") or "").strip().lower() or None
    if tts_mode and tts_mode not in {"fish_audio", "gtts", "mock"}:
        raise ValueError("SCHEDULED_AUDIO_TTS_MODE doit être fish_audio, gtts ou mock")

    now = datetime.now(FRANCE_TZ)
    lower_bound = (now - timedelta(hours=late_grace)).strftime("%Y-%m-%d %H:%M:%S")
    upper_bound = (now + timedelta(hours=horizon)).strftime("%Y-%m-%d %H:%M:%S")

    due_sessions = list_due_audio_generation_sessions(
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        platform_ids=platform_ids,
    )

    results = []
    for session in due_sessions:
        session_id = session["id"]
        platform_id = session["platform_id"]
        session_index = session["session_index"]
        scheduled_at = session["scheduled_at"]
        platform_name = session["name"]
        job_id = session["formation_job_id"]
        result = {
            "session_id": session_id,
            "platform_id": platform_id,
            "platform_name": platform_name,
            "session_index": session_index,
            "scheduled_at": scheduled_at,
            "formation_job_id": job_id,
        }
        if not job_id:
            results.append({**result, "success": False, "skipped": True, "error": "Aucun job pipeline lié"})
            continue

        folder_ids = get_expected_course_folders(job_id).get("folder_ids") or []
        folder_index = int(session_index or 0) - 1
        if folder_index < 0 or folder_index >= len(folder_ids):
            results.append({
                **result,
                "success": False,
                "skipped": True,
                "error": "Aucun dossier cours pour cette séance",
                "available_folder_count": len(folder_ids),
            })
            continue

        folder_id = folder_ids[folder_index]
        result["folder_id"] = folder_id
        if dry_run:
            results.append({**result, "success": True, "dry_run": True})
            continue

        try:
            from routes.formation_routes import start_folder_audio_generation

            payload = {
                "force_all": True,
                "sync_slides": True,
                "auto_generate_slides": True,
                **({"tts_mode": tts_mode} if tts_mode else {}),
            }
            launch_payload, status = start_folder_audio_generation(
                int(job_id),
                int(folder_id),
                payload,
                schedule_session_id=int(session_id),
                trigger_source="scheduled_24h",
            )
            results.append({
                **result,
                "success": status == 202,
                "status": status,
                "launch": launch_payload,
            })
        except Exception as exc:
            logger.error("❌ Audio planifié non lancé session=%s: %s", session_id, exc, exc_info=True)
            results.append({**result, "success": False, "error": str(exc)})

    return results
