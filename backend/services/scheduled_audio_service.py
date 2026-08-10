import os
from datetime import datetime, timedelta

from config import FRANCE_TZ
from repositories.course_schedule_repository import (
    get_audio_generation_session,
    mark_audio_waiting_for_content,
)
from repositories.pipeline_repository import list_due_audio_generation_sessions
from services.audio_service import is_explicit_schedule_occurrence
from services.formation_pipeline_service import get_expected_course_folders
from utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_SCHEDULED_AUDIO_BATCH_SIZE = 50
_MAX_SCHEDULED_AUDIO_BATCH_SIZE = 1000
_DEFAULT_AUDIO_READY_HOURS_BEFORE = 72.0
_DEFAULT_AUDIO_BUILD_BUFFER_HOURS = 0.0


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
    """Return the readiness target and the proactive generation buffer.

    The product contract starts each day's generation exactly 72 hours before
    class. The scheduler claim is idempotent, so inclusive H-72 ticks are safe.
    ``SCHEDULED_AUDIO_HORIZON_HOURS`` remains a compatibility fallback for
    existing deployments and internal callers can override the target through
    ``horizon_hours``.
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

    result = launch_scheduled_audio_session(
        session,
        tts_mode=_scheduled_tts_mode(),
        trigger_source="manual_schedule_retry",
    )
    return result, int(result.get("status") or (202 if result.get("success") else 500))


def process_due_audio_generations(
    platform_ids=None,
    dry_run=False,
    horizon_hours=None,
    *,
    wait_for_completion=False,
):
    """Launch one day's audio when its H-72 generation window opens.

    Database claims, fencing tokens and retry timestamps make repeated timer
    calls safe across restarts and multiple Azure instances. V2 occurrences
    enter at H-72 for their immutable day manifest. Historic V1 occurrences
    keep the proactive build buffer and enter at the full claim horizon.
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
        launched = launch_scheduled_audio_session(
            session,
            tts_mode=tts_mode,
            stale_started_before=stale_started_before,
            wait_for_completion=wait_for_completion,
        )
        results.append(launched)
        if int(launched.get("status") or 0) == 429:
            # Remaining rows were never claimed and stay due. Avoid hammering
            # the route while this process has reached its provider capacity.
            break
    return results
