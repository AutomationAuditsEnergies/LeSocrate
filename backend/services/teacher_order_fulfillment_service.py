"""Durable, idempotent provisioning for authorized AI-teacher orders."""

from __future__ import annotations

from datetime import datetime, time

from config import FRANCE_TZ
from services.pipeline_queue.contracts import PermanentWorkError, WorkItemSpec, WorkResult
from repositories.billing_repository import (
    claim_order_for_fulfillment,
    complete_order_pipeline_fulfillment,
    fail_order_pipeline_fulfillment,
    get_reusable_module,
    update_order_state,
)
from repositories.pipeline_repository import (
    create_pipeline_platform,
    create_postgres_pipeline_aggregate,
    list_course_folder_ids_for_platform,
)
from repositories.hr_write_repository import (
    clone_canonical_module_course_structure,
    clone_postgres_course_structure,
    set_postgres_platform_status,
)
from services.course_schedule_service import create_course_schedule
from repositories.day_schedule_repository import (
    bind_module_days_to_platform,
    list_module_days,
    lock_pipeline_schedule_snapshot,
)
from services.dynamic_day_schedule_service import (
    SCHEDULE_SCHEMA_VERSION,
    validate_new_module_lead_time,
)
from services.formation_pipeline_service import update_job
from repositories.center_workspace_repository import set_platform_asset_binding_mode
from repositories.ai_voice_repository import assign_voice_to_platform, get_voice
from services.teacher_asset_service import ensure_module_asset_manifest
from services.canonical_teacher_service import resolve_compatible_canonical_teacher
from services.platform_storage_service import ensure_platform_storage


# Les nouvelles pipelines utilisent le profil économique par défaut. La valeur
# courte est celle persistée dans auto_pilot_model et normalisée par les routes.
DEFAULT_PIPELINE_MODEL = "flash"


def _schedule_schema_version(schedule) -> int:
    if not isinstance(schedule, dict):
        return 1
    raw_version = schedule.get(
        "schedule_schema_version",
        schedule.get("schema_version"),
    )
    if raw_version in (None, ""):
        return SCHEDULE_SCHEMA_VERSION if "selected_dates" in schedule else 1
    try:
        version = int(raw_version)
    except (TypeError, ValueError) as exc:
        raise PermanentWorkError(
            "La version du calendrier de la commande est invalide"
        ) from exc
    if version not in (1, SCHEDULE_SCHEMA_VERSION):
        raise PermanentWorkError(
            "La version du calendrier de la commande n’est pas prise en charge"
        )
    return version


def _is_v2_schedule(schedule) -> bool:
    return _schedule_schema_version(schedule) == SCHEDULE_SCHEMA_VERSION


def _authoritative_reuse_schedule_version(module: dict, schedule) -> int:
    try:
        module_version = int(module.get("schedule_schema_version") or 1)
    except (TypeError, ValueError) as exc:
        raise PermanentWorkError(
            "La version du planning durable du module est invalide"
        ) from exc
    if module_version not in (1, SCHEDULE_SCHEMA_VERSION):
        raise PermanentWorkError(
            "La version du planning durable du module n’est pas prise en charge"
        )

    payload_version = _schedule_schema_version(schedule)
    if payload_version != module_version:
        raise PermanentWorkError(
            f"Le calendrier de réutilisation V{payload_version} ne correspond pas "
            f"au module durable V{module_version}"
        )
    return module_version


def _fulfillment_now() -> datetime:
    return datetime.now(FRANCE_TZ)


def _authorization_datetime(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise PermanentWorkError(
                "La date d’autorisation de la commande est invalide"
            ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return FRANCE_TZ.localize(parsed)
    return parsed.astimezone(FRANCE_TZ)


def _new_module_validation_at(order: dict) -> datetime:
    """Use the latest real authorization/worker time, never order creation."""
    now = _fulfillment_now()
    if now.tzinfo is None or now.utcoffset() is None:
        now = FRANCE_TZ.localize(now)
    else:
        now = now.astimezone(FRANCE_TZ)
    authorized_at = _authorization_datetime(order.get("authorized_at"))
    return max(now, authorized_at) if authorized_at is not None else now


def _v2_first_start_at(schedule: dict) -> datetime:
    try:
        first_day = schedule["days"][0]
        first_date = datetime.strptime(first_day["date"], "%Y-%m-%d").date()
        start_minute = int(first_day["blocks"][0]["start_minute"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise PermanentWorkError("Premier créneau V2 invalide") from exc
    return FRANCE_TZ.localize(
        datetime.combine(
            first_date,
            time(start_minute // 60, start_minute % 60),
        )
    )


def _reuse_schedule_with_module_days(
    schedule: dict,
    module_days: list[dict],
) -> dict:
    dates = list(schedule.get("selected_dates") or [])
    dates = sorted(str(value) for value in dates)
    if len(dates) != len(module_days):
        raise PermanentWorkError(
            "La réutilisation doit conserver exactement le nombre de journées du module"
        )
    days = []
    for expected_index, (local_date, module_day) in enumerate(
        zip(dates, module_days),
        start=1,
    ):
        day_index = int(module_day.get("day_index") or 0)
        if day_index != expected_index:
            raise PermanentWorkError(
                "Les journées durables du module ne sont pas ordonnées"
            )
        days.append(
            {
                "day_index": expected_index,
                "date": local_date,
                "module_day_id": int(module_day["id"]),
                "blocks": module_day.get("blocks")
                or module_day.get("blocks_snapshot_json")
                or [],
            }
        )
    return {
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "schedule_schema_version": SCHEDULE_SCHEMA_VERSION,
        "day_count": len(days),
        "selected_dates": dates,
        "days": days,
    }


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
    ai_voice_id = int(payload.get("ai_voice_id") or 0) or None
    if ai_voice_id is not None and get_voice(center_id, ai_voice_id) is None:
        raise PermanentWorkError("La voix IA de cette commande n’est plus disponible")

    def assign_order_voice(platform_id: int) -> None:
        if ai_voice_id is None:
            return
        if not assign_voice_to_platform(center_id, platform_id, ai_voice_id):
            raise PermanentWorkError("Impossible d’associer la voix IA au professeur")
    creation_request_id = f"teacher-order-{order['public_id']}"
    lease.checkpoint()

    try:
        if order["operation_type"] == "new_teacher":
            formation = dict(payload.get("new_formation") or {})
            total_hours = int(formation.get("total_hours") or order["total_hours"])
            schedule = formation.get("schedule") or {}
            v2_schedule = _is_v2_schedule(schedule)
            if v2_schedule:
                nb_days = int(schedule.get("day_count") or len(schedule.get("days") or []))
                if nb_days <= 0 or nb_days != len(schedule.get("days") or []):
                    raise PermanentWorkError("Le planning V2 de la commande est incomplet")
                try:
                    validate_new_module_lead_time(
                        _new_module_validation_at(order),
                        _v2_first_start_at(schedule),
                    )
                except ValueError as exc:
                    raise PermanentWorkError(
                        "Le délai de 48 heures du planning V2 n’est pas respecté"
                    ) from exc
            else:
                nb_days = int(
                    schedule.get("total_training_days")
                    or max(1, total_hours // 7)
                )
            tp_name = str(formation.get("tp_name") or order["training_title"])
            rncp_code = str(formation.get("rncp_code") or order.get("rncp_code") or "")
            canonical_match = None
            if not v2_schedule:
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
                    assign_order_voice(platform_id)
                    ensure_platform_storage(platform)
                    clone_canonical_module_course_structure(
                        target_platform_id=platform_id,
                        module_id=module_id,
                        target_center_account_id=center_id,
                    )
                    lease.checkpoint()
                    set_platform_asset_binding_mode(platform_id, "shared")
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
                model=DEFAULT_PIPELINE_MODEL,
                teacher_name=teacher_name,
                teacher_color=teacher_color,
                creation_request_id=creation_request_id,
            )
            platform_id = int(aggregate["platform"]["id"])
            assign_order_voice(platform_id)
            pipeline_job_id = int(aggregate["job_id"])
            if v2_schedule:
                try:
                    lock_pipeline_schedule_snapshot(
                        center_id,
                        pipeline_job_id,
                        schedule,
                    )
                except ValueError as exc:
                    raise PermanentWorkError(
                        "Le snapshot V2 de la commande ne peut pas être verrouillé"
                    ) from exc
            ensure_platform_storage(aggregate["platform"])
            if schedule:
                try:
                    create_course_schedule(platform_id, schedule)
                except ValueError as exc:
                    if v2_schedule:
                        raise PermanentWorkError(
                            "Le calendrier V2 de la commande est invalide"
                        ) from exc
                    raise
            update_job(
                pipeline_job_id,
                auto_pilot_enabled=1,
                auto_pilot_model=DEFAULT_PIPELINE_MODEL,
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
        schedule = payload.get("schedule")
        module = get_reusable_module(module_id, center_id)
        if not module:
            raise PermanentWorkError(
                "Le module durable de la commande n’est plus disponible ou "
                "réutilisable pour ce centre"
            )
        module_schedule_version = _authoritative_reuse_schedule_version(
            dict(module),
            schedule,
        )
        explicit_schedule = None
        if module_schedule_version == SCHEDULE_SCHEMA_VERSION:
            module_days = list_module_days(
                module_id,
                center_account_id=center_id,
            )
            explicit_schedule = _reuse_schedule_with_module_days(
                schedule,
                module_days,
            )
        platform = create_pipeline_platform(
            name=platform_name,
            center_account_id=center_id,
            teacher_name=teacher_name,
            teacher_color=teacher_color,
            creation_request_id=creation_request_id,
            source_module_id=module_id,
        )
        platform_id = int(platform["id"])
        assign_order_voice(platform_id)
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
        if module_schedule_version == SCHEDULE_SCHEMA_VERSION:
            try:
                create_course_schedule(platform_id, explicit_schedule)
                bind_module_days_to_platform(
                    center_id,
                    module_id,
                    platform_id,
                    list_course_folder_ids_for_platform(platform_id),
                )
            except ValueError as exc:
                raise PermanentWorkError(
                    "Le calendrier de réutilisation ne correspond pas au module"
                ) from exc
        elif schedule:
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
