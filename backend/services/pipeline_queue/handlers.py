"""Default handler for the existing auto-pilot state machine.

This module imports formation_routes lazily so the queue infrastructure itself
stays independent from Flask.  The route integration can later replace this
handler without changing the worker runtime.
"""

from __future__ import annotations

import time

from .contracts import PermanentWorkError, WorkItem, WorkItemSpec, WorkResult


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


def handle_auto_pilot_work_item(item: WorkItem, lease) -> WorkResult:
    if item.task_type != "auto_pilot_tick":
        raise PermanentWorkError(f"task_type inconnu: {item.task_type}")

    from routes import formation_routes as routes

    job = routes.get_job(item.pipeline_job_id)
    if not job:
        raise PermanentWorkError(f"Job pipeline {item.pipeline_job_id} introuvable")
    if not job.get("auto_pilot_enabled"):
        return WorkResult(result={"status": "stopped", "step": None})

    step = routes._determine_next_ap_step(item.pipeline_job_id)
    if step is None:
        routes.update_job(
            item.pipeline_job_id,
            auto_pilot_step="done",
            auto_pilot_error=None,
        )
        _log_pipeline_completed(item, job)
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
            "use_claude_code": bool(job.get("auto_pilot_use_cc")),
            "generate_audio": bool(job.get("auto_pilot_generate_audio")),
            "expected_step": expected_step,
        },
    )
    try:
        routes._execute_ap_step(item.pipeline_job_id, step, job)
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
        return WorkResult(result={"status": "done", "step": step})

    next_item = WorkItemSpec(
        pipeline_job_id=item.pipeline_job_id,
        run_id=item.run_id,
        task_type="auto_pilot_tick",
        scope_key="pipeline",
        dedupe_key=f"{item.run_id}:auto_pilot:{next_step}",
        payload={"expected_step": next_step, "previous_step": step},
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
