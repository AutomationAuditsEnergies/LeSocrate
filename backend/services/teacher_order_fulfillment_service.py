"""Durable, idempotent provisioning for authorized AI-teacher orders."""

from __future__ import annotations

from services.pipeline_queue.contracts import PermanentWorkError, WorkItemSpec, WorkResult
from repositories.billing_repository import (
    claim_order_for_fulfillment,
    complete_order_pipeline_fulfillment,
    fail_order_pipeline_fulfillment,
    update_order_state,
)
from repositories.pipeline_repository import (
    create_pipeline_platform,
    create_postgres_pipeline_aggregate,
)
from repositories.hr_write_repository import (
    clone_canonical_module_course_structure,
    clone_postgres_course_structure,
    set_postgres_platform_status,
)
from services.course_schedule_service import create_course_schedule
from services.formation_pipeline_service import update_job
from repositories.center_workspace_repository import set_platform_asset_binding_mode
from services.teacher_asset_service import ensure_module_asset_manifest
from services.canonical_teacher_service import resolve_compatible_canonical_teacher
from services.platform_storage_service import ensure_platform_storage


def complete_teacher_order_pipeline(item, job: dict) -> dict:
    """Complete an order only after its text/structure auto-pilot is ready."""
    order_id = int(item.payload.get("teacher_order_id") or 0)
    if not order_id:
        return {}
    pipeline_job_id = int(item.pipeline_job_id or job.get("id") or 0)
    platform_id = int(job.get("platform_id") or 0)
    if not pipeline_job_id or not platform_id:
        raise PermanentWorkError(
            "Pipeline ou plateforme absent de la finalisation de commande professeur IA"
        )
    order = complete_order_pipeline_fulfillment(
        order_id,
        pipeline_job_id=pipeline_job_id,
        platform_id=platform_id,
    )
    if not order:
        raise PermanentWorkError(f"Commande professeur IA {order_id} introuvable")
    if order.get("fulfillment_status") != "fulfilled":
        raise PermanentWorkError(
            f"Commande professeur IA {order_id} liée à un autre pipeline ou non payée"
        )
    return order


def fail_teacher_order_pipeline(item, error: str) -> dict:
    """Expose a terminal auto-pilot failure as retryable without repaying."""
    order_id = int(item.payload.get("teacher_order_id") or 0)
    pipeline_job_id = int(item.pipeline_job_id or 0)
    if not order_id or not pipeline_job_id:
        return {}
    return fail_order_pipeline_fulfillment(
        order_id,
        pipeline_job_id=pipeline_job_id,
        error=error,
    ) or {}


def fulfill_teacher_order(item, lease) -> WorkResult:
    order_id = int(item.payload.get("order_id") or 0)
    if not order_id:
        raise PermanentWorkError("Commande professeur IA absente du travail durable")

    order = claim_order_for_fulfillment(order_id)
    if not order:
        raise PermanentWorkError(f"Commande professeur IA {order_id} introuvable")
    if order.get("fulfillment_status") == "fulfilled":
        return WorkResult(result={"status": "fulfilled", "platform_id": order.get("platform_id")})
    if order.get("payment_status") not in {"paid", "not_required"}:
        raise PermanentWorkError("Commande non autorisée au paiement")

    payload = dict(order.get("request_payload_json") or {})
    center_id = int(order["center_account_id"])
    platform_name = str(payload.get("name") or order.get("training_title") or "Professeur IA").strip()
    teacher_name = str(payload.get("teacher_name") or "").strip() or None
    teacher_color = str(payload.get("teacher_color") or "violet").strip().lower()
    creation_request_id = f"teacher-order-{order['public_id']}"
    lease.checkpoint()

    try:
        if order["operation_type"] == "new_teacher":
            formation = dict(payload.get("new_formation") or {})
            total_hours = int(formation.get("total_hours") or order["total_hours"])
            nb_days = int((formation.get("schedule") or {}).get("total_training_days") or max(1, total_hours // 7))
            tp_name = str(formation.get("tp_name") or order["training_title"])
            rncp_code = str(formation.get("rncp_code") or order.get("rncp_code") or "")
            canonical_match = resolve_compatible_canonical_teacher(
                rncp_code=rncp_code,
                tp_name=tp_name,
                total_hours=total_hours,
                nb_days=nb_days,
                voice_type="fish_audio",
            )
            if canonical_match:
                module_id = int(canonical_match["module_id"])
                platform = create_pipeline_platform(
                    name=platform_name,
                    center_account_id=center_id,
                    teacher_name=teacher_name,
                    teacher_color=teacher_color,
                    creation_request_id=creation_request_id,
                    source_module_id=module_id,
                )
                existing_module_id = int(platform.get("source_module_id") or 0)
                if platform.get("deduplicated") and existing_module_id != module_id:
                    # An earlier attempt atomically chose the full generation
                    # path. Never rebind that target to another source later.
                    canonical_match = None
                else:
                    platform_id = int(platform["id"])
                    ensure_platform_storage(platform)
                    clone_canonical_module_course_structure(
                        target_platform_id=platform_id,
                        module_id=module_id,
                        target_center_account_id=center_id,
                    )
                    lease.checkpoint()
                    set_platform_asset_binding_mode(platform_id, "shared")
                    schedule = formation.get("schedule")
                    if schedule:
                        create_course_schedule(platform_id, schedule)
                    set_postgres_platform_status(
                        platform_id,
                        "ready",
                        center_id,
                        scope_to_center=True,
                    )
                    update_order_state(
                        order_id,
                        status="fulfilled",
                        fulfillment_status="fulfilled",
                        platform_id=platform_id,
                        last_error=None,
                    )
                    return WorkResult(result={
                        "status": "fulfilled",
                        "platform_id": platform_id,
                        "asset_binding_mode": "shared",
                        "canonical_reuse": True,
                        "module_asset_count": int(canonical_match.get("asset_count") or 0),
                    })

            aggregate = create_postgres_pipeline_aggregate(
                platform_name=platform_name,
                center_account_id=center_id,
                tp_name=tp_name,
                rncp_code=rncp_code,
                total_hours=total_hours,
                nb_days=nb_days,
                model="pro",
                teacher_name=teacher_name,
                teacher_color=teacher_color,
                creation_request_id=creation_request_id,
            )
            platform_id = int(aggregate["platform"]["id"])
            pipeline_job_id = int(aggregate["job_id"])
            ensure_platform_storage(aggregate["platform"])
            schedule = formation.get("schedule")
            if schedule:
                create_course_schedule(platform_id, schedule)
            update_job(
                pipeline_job_id,
                auto_pilot_enabled=1,
                auto_pilot_model="pro",
                auto_pilot_tts_mode="fish_audio",
                auto_pilot_use_cc=0,
                auto_pilot_skip_vs=0,
                auto_pilot_generate_audio=0,
                auto_pilot_volume_done=0,
                auto_pilot_post_review_docs_done=0,
                auto_pilot_error=None,
            )
            update_order_state(
                order_id,
                status="fulfilling",
                fulfillment_status="running",
                platform_id=platform_id,
                pipeline_job_id=pipeline_job_id,
                last_error=None,
            )
            from routes import formation_routes

            next_step = formation_routes._determine_next_ap_step(pipeline_job_id)
            if next_step is None:
                completed = complete_order_pipeline_fulfillment(
                    order_id,
                    pipeline_job_id=pipeline_job_id,
                    platform_id=platform_id,
                )
                if not completed or completed.get("fulfillment_status") != "fulfilled":
                    raise PermanentWorkError(
                        f"Commande professeur IA {order_id} impossible à finaliser"
                    )
                return WorkResult(result={"status": "fulfilled", "platform_id": platform_id})
            return WorkResult(
                result={
                    "status": "preparing",
                    "platform_id": platform_id,
                    "pipeline_job_id": pipeline_job_id,
                },
                next_items=(
                    WorkItemSpec(
                        pipeline_job_id=pipeline_job_id,
                        run_id=f"teacher-order-{order['public_id']}",
                        task_type="auto_pilot_tick",
                        scope_key="pipeline",
                        dedupe_key=f"teacher-order:{order['public_id']}:auto-pilot:{next_step}",
                        payload={"expected_step": next_step, "teacher_order_id": order_id},
                        priority=10,
                        max_attempts=5,
                    ),
                ),
            )

        if order["operation_type"] != "reuse_teacher":
            raise PermanentWorkError("Type de commande professeur IA inconnu")

        module_id = int(order.get("source_module_id") or payload.get("module_id") or 0)
        if not module_id:
            raise PermanentWorkError("Ancien professeur IA absent de la commande")
        platform = create_pipeline_platform(
            name=platform_name,
            center_account_id=center_id,
            teacher_name=teacher_name,
            teacher_color=teacher_color,
            creation_request_id=creation_request_id,
            source_module_id=module_id,
        )
        platform_id = int(platform["id"])
        ensure_platform_storage(platform)
        clone = clone_postgres_course_structure(
            target_platform_id=platform_id,
            module_id=module_id,
            center_account_id=center_id,
            scope_to_center=True,
        )
        lease.checkpoint()
        # A reuse creates a lightweight promotion binding. The module's
        # documents, slides and audio stay immutable in Azure and are referenced
        # through course_clone_folder_map + formation_module_assets. This keeps
        # storage proportional to unique teacher versions, not promotion count.
        manifest = ensure_module_asset_manifest(
            module_id=module_id,
            center_account_id=center_id,
            source_platform_id=int(clone["source_platform_id"]),
            source_folder_ids=clone["folder_id_map"].keys(),
        )
        set_platform_asset_binding_mode(platform_id, "shared")
        schedule = payload.get("schedule")
        if schedule:
            create_course_schedule(platform_id, schedule)
        set_postgres_platform_status(platform_id, "ready", center_id, scope_to_center=True)
        update_order_state(
            order_id,
            status="fulfilled",
            fulfillment_status="fulfilled",
            platform_id=platform_id,
            last_error=None,
        )
        return WorkResult(result={
            "status": "fulfilled",
            "platform_id": platform_id,
            "asset_binding_mode": "shared",
            "module_asset_count": manifest.get("registered", 0),
        })
    except PermanentWorkError:
        raise
    except Exception as exc:
        # The durable worker owns retry scheduling. Keep the order trackable
        # while attempts remain; only the dead-letter callback marks it failed.
        update_order_state(
            order_id,
            status="fulfillment_queued",
            fulfillment_status="queued",
            last_error=str(exc)[:500],
        )
        raise


def mark_teacher_order_dead_letter(item, error: str) -> None:
    order_id = int(item.payload.get("order_id") or 0)
    if order_id:
        update_order_state(
            order_id,
            status="fulfillment_failed",
            fulfillment_status="failed",
            last_error=str(error)[:500],
        )
