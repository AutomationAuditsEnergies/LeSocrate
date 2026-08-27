"""Default handler for the existing auto-pilot state machine.

This module imports formation_routes lazily so the queue infrastructure itself
stays independent from Flask.  The route integration can later replace this
handler without changing the worker runtime.
"""

from __future__ import annotations

import time

from .contracts import PermanentWorkError, WorkItem, WorkItemSpec, WorkResult


def handle_pipeline_work_item(item: WorkItem, lease) -> WorkResult:
    """Dispatch every durable task type handled by the shared worker."""
    if item.task_type == "auto_pilot_tick":
        return handle_auto_pilot_work_item(item, lease)
    if item.task_type in {"hr_playlist_generate", "hr_playlist_item"}:
        from services.hr_playlist_pipeline_service import handle_hr_playlist_work_item

        return handle_hr_playlist_work_item(item, lease)
    if item.task_type == "scheduled_audio_item":
        from services.hr_playlist_pipeline_service import handle_scheduled_audio_work_item

        return handle_scheduled_audio_work_item(item, lease)
    if item.task_type == "ai_teacher_fulfillment":
        from services.teacher_order_fulfillment_service import fulfill_teacher_order

        return fulfill_teacher_order(item, lease)
    if item.task_type == "voice_reference_calibration":
        return handle_voice_reference_calibration_work_item(item, lease)
    raise PermanentWorkError(f"task_type inconnu: {item.task_type}")


def handle_voice_reference_calibration_work_item(item: WorkItem, lease) -> WorkResult:
    """Calibrate the selected voice before the first content pipeline tick."""

    from routes import formation_routes as routes
    from services.voice_reference_calibration_service import calibrate_platform_voice

    job = routes.get_job(item.pipeline_job_id)
    if not job:
        raise PermanentWorkError(f"Job pipeline {item.pipeline_job_id} introuvable")
    platform_id = int(job.get("platform_id") or 0)
    if not platform_id:
        raise PermanentWorkError("Plateforme absente de la calibration vocale")
    lease.checkpoint()
    result = calibrate_platform_voice(platform_id)
    lease.checkpoint()
    next_step = routes._determine_next_ap_step(item.pipeline_job_id)
    if next_step is None:
        raise PermanentWorkError("Le pipeline ne possède aucune étape après la calibration")
    return WorkResult(
        result={**result, "next_step": next_step},
        next_items=(
            WorkItemSpec(
                pipeline_job_id=item.pipeline_job_id,
                run_id=item.run_id,
                task_type="auto_pilot_tick",
                scope_key="pipeline",
                dedupe_key=f"{item.run_id}:auto_pilot:{next_step}",
                payload={
                    "expected_step": next_step,
                    **_teacher_order_chain_payload(item),
                },
                priority=item.priority,
                max_attempts=5,
            ),
        ),
    )


def _log_event(item: WorkItem, event_type: str, **kwargs) -> None:
    try:
        from services.formation_observability_service import log_pipeline_event

        data = dict(kwargs.pop("data", {}) or {})
        data.update(
            {
                "work_item_id": item.id,
                "run_id": item.run_id,
                "attempt": item.attempt_count,
                "fence": item.lease_version,
            }
        )
        log_pipeline_event(
            item.pipeline_job_id,
            event_type,
            data=data,
            **kwargs,
        )
    except Exception:
        # Observability must never make a completed expensive step retry.
        pass


def _log_pipeline_completed(item: WorkItem, job: dict) -> None:
    _log_event(
        item,
        "pipeline_completed",
        step="done",
        status="completed",
        model=job.get("auto_pilot_model"),
        message=(
            "Auto-pilot texte et slides terminé"
            if not job.get("auto_pilot_generate_audio")
            else "Auto-pilot terminé"
        ),
        data={"generate_audio": bool(job.get("auto_pilot_generate_audio"))},
    )


def _teacher_order_chain_payload(item: WorkItem) -> dict:
    order_id = int(item.payload.get("teacher_order_id") or 0)
    return {"teacher_order_id": order_id} if order_id else {}


def _as_permanent_pipeline_error(
    exc: BaseException,
) -> PermanentWorkError | None:
    """Classe les erreurs qu'aucune relance de la file ne peut corriger."""
    if isinstance(exc, PermanentWorkError):
        return exc

    from utils.deepseek_client import is_deterministic_deepseek_error

    if is_deterministic_deepseek_error(exc):
        return PermanentWorkError(str(exc))

    current = exc
    visited = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        response = getattr(current, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code in (400, 401, 402, 403, 404, 410, 422):
            return PermanentWorkError(
                f"Erreur HTTP définitive {status_code} : {current}"
            )
        current = current.__cause__ or current.__context__
    return None


def _complete_teacher_order_if_present(item: WorkItem, job: dict) -> None:
    if not item.payload.get("teacher_order_id"):
        return
    from services.teacher_order_fulfillment_service import complete_teacher_order_pipeline

    complete_teacher_order_pipeline(item, job)


def handle_auto_pilot_work_item(item: WorkItem, lease) -> WorkResult:
    if item.task_type != "auto_pilot_tick":
        raise PermanentWorkError(f"task_type inconnu: {item.task_type}")

    from routes import formation_routes as routes

    job = routes.get_job(item.pipeline_job_id)
    if not job:
        raise PermanentWorkError(f"Job pipeline {item.pipeline_job_id} introuvable")
    if not job.get("auto_pilot_enabled"):
        if item.payload.get("teacher_order_id"):
            raise PermanentWorkError(
                f"Auto-pilot désactivé pour la commande du pipeline {item.pipeline_job_id}"
            )
        return WorkResult(result={"status": "stopped", "step": None})

    step = routes._determine_next_ap_step(item.pipeline_job_id)
    if step is None:
        routes.update_job(
            item.pipeline_job_id,
            auto_pilot_step="done",
            auto_pilot_error=None,
        )
        _log_pipeline_completed(item, job)
        _complete_teacher_order_if_present(item, job)
        return WorkResult(result={"status": "done", "step": None})

    expected_step = item.payload.get("expected_step")
    if expected_step is not None:
        expected_step = str(expected_step)
    if expected_step is not None and expected_step != step:
        # The persisted pipeline state is authoritative.  Complete this stale
        # tick without executing any expensive step, then atomically replace it
        # with a fresh tick aimed at the current step.  Including the stale
        # item id avoids colliding with a historical terminal dedupe key.
        routes.update_job(
            item.pipeline_job_id,
            auto_pilot_step=step,
            auto_pilot_error=None,
        )
        lease.checkpoint()
        _log_event(
            item,
            "step_reconciled",
            step=step,
            status="queued",
            model=job.get("auto_pilot_model"),
            message=(
                f"Tick obsolète ignoré ({expected_step}); "
                f"reprise planifiée sur {step}"
            ),
            data={
                "expected_step": expected_step,
                "current_step": step,
            },
        )
        current_step_item = WorkItemSpec(
            pipeline_job_id=item.pipeline_job_id,
            run_id=item.run_id,
            task_type="auto_pilot_tick",
            scope_key=item.scope_key,
            dedupe_key=(
                f"{item.run_id}:auto_pilot:{step}:reconcile:{item.id}"
            ),
            payload={
                "expected_step": step,
                "reconciled_from_step": expected_step,
                "reconciled_from_work_item_id": item.id,
                **_teacher_order_chain_payload(item),
            },
            priority=item.priority,
            max_attempts=item.max_attempts,
        )
        return WorkResult(
            result={
                "status": "step_reconciled",
                "skipped_step": expected_step,
                "next_step": step,
            },
            next_items=(current_step_item,),
        )

    routes.update_job(
        item.pipeline_job_id,
        auto_pilot_step=step,
        auto_pilot_error=None,
    )
    lease.checkpoint()
    started_at = time.time()
    _log_event(
        item,
        "step_started",
        step=step,
        status="running",
        model=job.get("auto_pilot_model"),
        message=f"Étape auto-pilot démarrée : {step}",
        data={
            "tts_mode": job.get("auto_pilot_tts_mode"),
            "generate_audio": bool(job.get("auto_pilot_generate_audio")),
            "expected_step": expected_step,
        },
    )
    try:
        routes._execute_ap_step(
            item.pipeline_job_id,
            step,
            job,
            checkpoint=lease.checkpoint,
        )
    except Exception as exc:
        _log_event(
            item,
            "step_failed",
            step=step,
            status="error",
            model=job.get("auto_pilot_model"),
            duration_ms=int((time.time() - started_at) * 1000),
            message=f"Étape auto-pilot échouée : {step}",
            error=str(exc)[:500],
        )
        permanent_error = _as_permanent_pipeline_error(exc)
        if permanent_error is not None:
            raise permanent_error from exc
        raise
    lease.checkpoint()
    _log_event(
        item,
        "step_completed",
        step=step,
        status="completed",
        model=job.get("auto_pilot_model"),
        duration_ms=int((time.time() - started_at) * 1000),
        message=f"Étape auto-pilot terminée : {step}",
    )

    next_step = routes._determine_next_ap_step(item.pipeline_job_id)
    if next_step is None:
        routes.update_job(
            item.pipeline_job_id,
            auto_pilot_step="done",
            auto_pilot_error=None,
        )
        latest_job = routes.get_job(item.pipeline_job_id) or job
        _log_pipeline_completed(item, latest_job)
        _complete_teacher_order_if_present(item, latest_job)
        return WorkResult(result={"status": "done", "step": step})

    next_item = WorkItemSpec(
        pipeline_job_id=item.pipeline_job_id,
        run_id=item.run_id,
        task_type="auto_pilot_tick",
        scope_key="pipeline",
        dedupe_key=f"{item.run_id}:auto_pilot:{next_step}",
        payload={
            "expected_step": next_step,
            "previous_step": step,
            **_teacher_order_chain_payload(item),
        },
        priority=item.priority,
        max_attempts=item.max_attempts,
    )
    return WorkResult(
        result={"status": "step_completed", "step": step, "next_step": next_step},
        next_items=(next_item,),
    )


def mark_auto_pilot_dead_letter(item: WorkItem, error: str) -> None:
    if item.task_type != "auto_pilot_tick":
        return
    from services.formation_pipeline_service import update_job

    update_job(item.pipeline_job_id, auto_pilot_error=error[:500])
    if item.payload.get("teacher_order_id"):
        from services.teacher_order_fulfillment_service import fail_teacher_order_pipeline

        fail_teacher_order_pipeline(item, error)


def mark_pipeline_dead_letter(item: WorkItem, error: str) -> None:
    if item.task_type == "auto_pilot_tick":
        mark_auto_pilot_dead_letter(item, error)
        return
    if item.task_type in {"hr_playlist_generate", "hr_playlist_item", "scheduled_audio_item"}:
        _log_event(
            item,
            "hr_playlist_dead_lettered",
            step="audio",
            status="error",
            message="Pipeline audio HR abandonnée après épuisement des tentatives",
            error=error[:500],
            data={"folder_id": item.folder_id, "task_type": item.task_type},
        )
        if item.task_type == "scheduled_audio_item" and item.payload.get("session_id"):
            try:
                from datetime import datetime
                from config import FRANCE_TZ
                from repositories.course_schedule_repository import fail_audio_generation_session

                fail_audio_generation_session(
                    int(item.payload["session_id"]),
                    error=error,
                    failed_at=datetime.now(FRANCE_TZ),
                )
            except Exception:
                pass
        return
    if item.task_type == "ai_teacher_fulfillment":
        from services.teacher_order_fulfillment_service import mark_teacher_order_dead_letter

        mark_teacher_order_dead_letter(item, error)
        return
    if item.task_type == "voice_reference_calibration":
        if item.payload.get("teacher_order_id"):
            from services.teacher_order_fulfillment_service import fail_teacher_order_pipeline

            fail_teacher_order_pipeline(item, error)
