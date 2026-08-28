"""Server-authoritative Stripe Checkout and order authorization."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, time, timedelta, timezone
from typing import Any

from config import FRANCE_TZ
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pytz.exceptions import AmbiguousTimeError, NonExistentTimeError
from repositories.billing_repository import (
    approve_order_review,
    apply_stripe_webhook_event,
    attach_checkout_session,
    create_order,
    enqueue_order_fulfillment,
    get_center_billing_account,
    get_order,
    get_reusable_module,
    list_center_billing_orders,
    list_center_order_messages,
    list_teacher_order_reviews,
    mark_center_order_message_seen,
    mark_teacher_order_admin_seen,
    mark_order_notification_sent,
    reconcile_stripe_checkout_session,
    record_webhook_failure,
    reject_order_review,
    retry_order_fulfillment,
)
from repositories.day_schedule_repository import get_template, mark_template_used
from services.dynamic_day_schedule_service import (
    SCHEDULE_SCHEMA_VERSION,
    ScheduleValidationError,
    compile_module_schedule,
    validate_new_module_lead_time,
)
from services.billing_email_service import send_payment_link, send_review_request
from utils.logger import get_logger
from utils.planning_summary import summarize_v2_schedule


logger = get_logger(__name__)


class BillingError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


PRODUCTS = {
    "new_teacher": {
        "pricing_key": "new_teacher",
        "label": "Nouveau professeur IA",
    },
    "reuse_teacher": {
        "pricing_key": "reuse_teacher",
        "label": "Réutilisation d’un professeur IA",
    },
}

SERVER_EXEMPT_CENTER_EMAILS = frozenset()
SERVER_REVIEW_EXEMPT_CENTER_EMAILS = frozenset({"newpiprod@gmail.com"})
SERVER_ORDER_REVIEW_CENTER_EMAILS = frozenset({"newpiprod@gmail.com"})
WEEKDAY_IDS = {
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
}


def _schedule_schema_version(schedule: Any) -> int:
    if not isinstance(schedule, Mapping):
        return 1
    raw = schedule.get(
        "schedule_schema_version",
        schedule.get("schema_version"),
    )
    if raw in (None, ""):
        return 2 if "selected_dates" in schedule else 1
    try:
        version = int(raw)
    except (TypeError, ValueError) as exc:
        raise BillingError("La version du planning est invalide.") from exc
    if version not in (1, SCHEDULE_SCHEMA_VERSION):
        raise BillingError("La version du planning n’est pas prise en charge.")
    return version


def _normalize_template_assignments(assignments: Any) -> dict[Any, int]:
    if isinstance(assignments, Mapping):
        raw_items = assignments.items()
    elif isinstance(assignments, Sequence) and not isinstance(
        assignments,
        (str, bytes),
    ):
        raw_items = []
        for index, assignment in enumerate(assignments):
            if not isinstance(assignment, Mapping):
                raise BillingError(
                    f"L’affectation de template n°{index + 1} est invalide."
                )
            raw_items.append(
                (
                    assignment.get("date"),
                    assignment.get(
                        "template_id",
                        assignment.get("template_key"),
                    ),
                )
            )
    else:
        raise BillingError(
            "Chaque date doit être affectée à un template de journée."
        )

    normalized: dict[Any, int] = {}
    for raw_date, raw_template_id in raw_items:
        if raw_date in normalized:
            raise BillingError(
                "Une date ne peut recevoir qu’une seule affectation de template."
            )
        try:
            template_id = int(raw_template_id)
        except (TypeError, ValueError) as exc:
            raise BillingError("Un identifiant de template est invalide.") from exc
        if template_id <= 0:
            raise BillingError("Un identifiant de template est invalide.")
        normalized[raw_date] = template_id
    return normalized


def _normalize_template_hashes(
    template_hashes: Any,
    template_ids: Sequence[int],
) -> dict[int, str]:
    if not isinstance(template_hashes, Mapping):
        raise BillingError(
            "Rechargez les templates de journée avant de valider le planning."
        )
    expected_ids = {int(template_id) for template_id in template_ids}
    normalized: dict[int, str] = {}
    for raw_template_id, raw_hash in template_hashes.items():
        try:
            template_id = int(raw_template_id)
        except (TypeError, ValueError) as exc:
            raise BillingError("Un identifiant de template est invalide.") from exc
        blocks_hash = str(raw_hash or "").strip().lower()
        if (
            template_id not in expected_ids
            or not re.fullmatch(r"[0-9a-f]{64}", blocks_hash)
        ):
            raise BillingError(
                "La version confirmée d’un template de journée est invalide."
            )
        normalized[template_id] = blocks_hash
    if set(normalized) != expected_ids:
        raise BillingError(
            "La version confirmée de chaque template est requise."
        )
    return normalized


def _normalize_custom_days(custom_days: Any) -> dict[Any, dict[str, Any]]:
    if custom_days in (None, {}):
        return {}
    if not isinstance(custom_days, Mapping):
        raise BillingError("Les journées personnalisées doivent être indexées par date.")

    normalized: dict[Any, dict[str, Any]] = {}
    for raw_date, raw_definition in custom_days.items():
        if not isinstance(raw_definition, Mapping):
            raise BillingError("Le déroulé d’une journée personnalisée est invalide.")
        blocks = raw_definition.get("blocks")
        if (
            isinstance(blocks, (str, bytes))
            or not isinstance(blocks, Sequence)
        ):
            raise BillingError("Les séquences d’une journée personnalisée sont invalides.")
        normalized[raw_date] = {
            "name": str(raw_definition.get("name") or "Journée personnalisée"),
            "blocks": list(blocks),
        }
    return normalized


def _day_start_at(day: Mapping[str, Any]) -> datetime:
    try:
        day_date = datetime.strptime(str(day["date"]), "%Y-%m-%d").date()
        first_start_minute = int(day["blocks"][0]["start_minute"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise BillingError("La première journée compilée est invalide.") from exc
    try:
        return FRANCE_TZ.localize(
            datetime.combine(
                day_date,
                time(first_start_minute // 60, first_start_minute % 60),
            ),
            is_dst=None,
        )
    except (AmbiguousTimeError, NonExistentTimeError) as exc:
        raise BillingError(
            "L’heure choisie n’existe pas sans ambiguïté à cette date."
        ) from exc


def _normalize_v2_new_schedule(
    schedule: Any,
    *,
    center_account_id: int,
) -> dict[str, Any]:
    if not isinstance(schedule, Mapping):
        raise BillingError("Le planning détaillé de la formation est requis.")
    selected_dates = schedule.get("selected_dates")
    assignments = _normalize_template_assignments(
        schedule.get("template_assignments")
    )
    custom_days = _normalize_custom_days(schedule.get("custom_days"))
    overlapping_dates = set(assignments).intersection(custom_days)
    if overlapping_dates:
        raise BillingError(
            "Une journée ne peut pas utiliser un template et un déroulé personnalisé."
        )
    template_ids = sorted(set(assignments.values()))
    template_hashes = _normalize_template_hashes(
        schedule.get("template_hashes"),
        template_ids,
    )
    templates: dict[int, dict[str, Any]] = {}
    for template_id in template_ids:
        template = get_template(center_account_id, template_id)
        if not template:
            raise BillingError(
                f"Le template de journée {template_id} est introuvable pour ce centre.",
                status_code=404,
            )
        if str(template.get("blocks_hash") or "").strip().lower() != (
            template_hashes[template_id]
        ):
            raise BillingError(
                "Un template a changé depuis votre confirmation. "
                "Rechargez le planning avant de continuer.",
                status_code=409,
            )
        templates[template_id] = {
            "name": template.get("name"),
            "blocks": template.get("blocks") or [],
        }
    compiled_assignments: dict[Any, Any] = dict(assignments)
    for custom_index, (raw_date, definition) in enumerate(custom_days.items(), start=1):
        custom_key = f"custom-day-{custom_index}"
        compiled_assignments[raw_date] = custom_key
        templates[custom_key] = definition
    try:
        snapshot = compile_module_schedule(
            selected_dates,
            compiled_assignments,
            templates,
        )
        validate_new_module_lead_time(
            _billing_now(),
            _day_start_at(snapshot["days"][0]),
        )
    except ScheduleValidationError as exc:
        raise BillingError(str(exc)) from exc

    return {
        **snapshot,
        "schedule_schema_version": SCHEDULE_SCHEMA_VERSION,
        "selected_dates": [day["date"] for day in snapshot["days"]],
        "template_assignments": {
            day["date"]: int(day["template_key"])
            for day in snapshot["days"]
            if isinstance(day["template_key"], int)
        },
        "template_hashes": {
            str(template_id): blocks_hash
            for template_id, blocks_hash in template_hashes.items()
        },
        "custom_days": {
            day["date"]: {"blocks": day["blocks"]}
            for day in snapshot["days"]
            if isinstance(day["template_key"], str)
            and day["template_key"].startswith("custom-day-")
        },
    }


def _normalize_v2_reuse_schedule(
    schedule: Any,
    *,
    module: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(schedule, Mapping):
        raise BillingError("Les nouvelles dates de la formation sont requises.")
    selected_dates = schedule.get("selected_dates")
    if (
        isinstance(selected_dates, (str, bytes))
        or not isinstance(selected_dates, Sequence)
        or not selected_dates
    ):
        raise BillingError("Sélectionnez les dates de toutes les journées.")

    normalized_dates: list[str] = []
    for index, raw_date in enumerate(selected_dates):
        try:
            parsed = datetime.strptime(str(raw_date), "%Y-%m-%d").date()
        except ValueError as exc:
            raise BillingError(
                f"La date n°{index + 1} est invalide."
            ) from exc
        canonical = parsed.isoformat()
        if canonical != str(raw_date):
            raise BillingError(
                f"La date n°{index + 1} doit respecter le format YYYY-MM-DD."
            )
        normalized_dates.append(canonical)
    if len(set(normalized_dates)) != len(normalized_dates):
        raise BillingError("Une même date ne peut pas être sélectionnée deux fois.")
    normalized_dates.sort()

    expected_days = int(
        module.get("nb_days")
        or module.get("module_day_count")
        or module.get("nb_folders")
        or 0
    )
    if expected_days <= 0:
        raise BillingError(
            "Le nombre de journées de ce module est introuvable.",
            status_code=409,
        )
    if len(normalized_dates) != expected_days:
        raise BillingError(
            f"Ce module doit être replacé sur exactement {expected_days} journées."
        )

    module_schema_version = int(module.get("schedule_schema_version") or 1)
    if module_schema_version < SCHEDULE_SCHEMA_VERSION:
        raise BillingError(
            "Ce module historique conserve son calendrier de réutilisation classique.",
            status_code=409,
        )
    if module_schema_version >= SCHEDULE_SCHEMA_VERSION:
        if int(module.get("module_day_count") or 0) != expected_days:
            raise BillingError(
                "Le déroulé durable de ce module est incomplet.",
                status_code=409,
            )
        reusable_at = module.get("reusable_at")
        if reusable_at is None:
            raise BillingError(
                "Ce module ne peut pas encore être réutilisé.",
                status_code=409,
            )
        if not isinstance(reusable_at, datetime):
            try:
                reusable_at = datetime.fromisoformat(str(reusable_at))
            except ValueError as exc:
                raise BillingError(
                    "La date de réutilisation du module est invalide.",
                    status_code=409,
                ) from exc
        if reusable_at.tzinfo is None:
            reusable_at = FRANCE_TZ.localize(reusable_at)
        if reusable_at.astimezone(FRANCE_TZ) > _billing_now():
            raise BillingError(
                "Ce module sera réutilisable après la fin de sa formation initiale.",
                status_code=409,
            )

    return {
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "schedule_schema_version": SCHEDULE_SCHEMA_VERSION,
        "selected_dates": normalized_dates,
        "day_count": expected_days,
    }


def _authoritative_reuse_schedule_version(
    schedule: Any,
    *,
    module: Mapping[str, Any],
) -> int:
    """Require the promotion calendar to use the durable module's contract."""
    try:
        module_version = int(module.get("schedule_schema_version") or 1)
    except (TypeError, ValueError) as exc:
        raise BillingError(
            "La version du planning durable de ce module est invalide.",
            status_code=409,
        ) from exc
    if module_version not in (1, SCHEDULE_SCHEMA_VERSION):
        raise BillingError(
            "La version du planning durable de ce module n’est pas prise en charge.",
            status_code=409,
        )

    payload_version = _schedule_schema_version(schedule)
    if payload_version == module_version:
        return module_version
    if module_version == SCHEDULE_SCHEMA_VERSION:
        raise BillingError(
            "Ce module durable V2 exige un calendrier de réutilisation V2.",
            status_code=409,
        )
    raise BillingError(
        "Ce module historique V1 conserve son calendrier de réutilisation classique.",
        status_code=409,
    )


def _center_is_exempt(center: dict[str, Any]) -> bool:
    normalized_username = str(center.get("username") or "").strip().lower()
    return (
        normalized_username in SERVER_EXEMPT_CENTER_EMAILS
        or center.get("billing_mode") == "exempt"
    )


def _center_review_is_exempt(center: dict[str, Any]) -> bool:
    normalized_username = str(center.get("username") or "").strip().lower()
    return (
        _center_is_exempt(center)
        or normalized_username in SERVER_REVIEW_EXEMPT_CENTER_EMAILS
    )


def center_can_review_orders(center_account_id: int) -> bool:
    """Grant the cross-centre review inbox only to explicitly trusted centres."""
    center = get_center_billing_account(center_account_id)
    if not center or not center.get("is_active"):
        return False
    normalized_username = str(center.get("username") or "").strip().lower()
    return normalized_username in SERVER_ORDER_REVIEW_CENTER_EMAILS


def center_can_manage_review(public_id: str, center_account_id: int) -> bool:
    """Keep delegated reviewers scoped to requests owned by another centre."""
    order = get_order(public_id)
    if not order:
        return False
    try:
        owner_center_id = int(order.get("center_account_id"))
    except (TypeError, ValueError):
        return False
    return owner_center_id != int(center_account_id)


def _stripe():
    try:
        import stripe
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise BillingError("Le service de paiement n’est pas installé.", status_code=503) from exc
    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret:
        raise BillingError("Le paiement n’est pas encore configuré.", status_code=503)
    return stripe.StripeClient(secret)


def _stripe_sdk():
    try:
        import stripe
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise BillingError("Le service de paiement n’est pas installé.", status_code=503) from exc
    return stripe


def _stripe_object_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict_recursive"):
        return dict(value.to_dict_recursive())
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if isinstance(value, Mapping):
        return dict(value)
    raise BillingError("Réponse Stripe invalide.", status_code=502)


def _stripe_checkout_configured() -> bool:
    """Only advertise Checkout when both payment and fulfillment are usable.

    A secret API key alone can create and capture a Checkout payment, but the
    application must also receive the signed webhook before it is allowed to
    provision the paid service.  Failing closed here prevents accepting money
    into an environment that cannot authorize fulfillment.
    """
    return bool(
        os.getenv("STRIPE_SECRET_KEY", "").strip()
        and os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    )


def _production_cost_per_day_cents() -> int:
    raw = os.getenv("AI_TEACHER_COST_PER_DAY_CENTS", "1500").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise BillingError("Le coût de production journalier est invalide.", status_code=503)
    if value <= 0:
        raise BillingError("Le coût de production journalier doit être positif.", status_code=503)
    return value


def _selling_price_per_day_cents() -> int:
    """Return the temporary fixed public price for one training day."""
    raw = os.getenv("AI_TEACHER_PRICE_PER_DAY_CENTS", "2000").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise BillingError("Le tarif journalier est invalide.", status_code=503)
    if value <= 0:
        raise BillingError("Le tarif journalier doit être positif.", status_code=503)
    return value


def get_product_catalog(*, allow_fallback: bool = True) -> dict[str, dict[str, Any]]:
    del allow_fallback  # kept for compatibility with older callers
    production_cost = _production_cost_per_day_cents()
    selling_price = _selling_price_per_day_cents()
    stripe_configured = _stripe_checkout_configured()
    catalog = {}
    for operation_type, product in PRODUCTS.items():
        catalog[operation_type] = {
            "operation_type": operation_type,
            "label": product["label"],
            "pricing_key": product["pricing_key"],
            "stripe_price_id": os.getenv("AI_TEACHER_STRIPE_PRICE_ID", "").strip() or None,
            "production_cost_per_day_cents": production_cost,
            "unit_amount_cents": selling_price,
            "currency": "eur",
            "configured": stripe_configured,
        }
    return catalog


def serialize_order(order: dict[str, Any], *, include_project: bool = False) -> dict[str, Any]:
    result = {
        "id": str(order["public_id"]),
        "operation_type": order["operation_type"],
        "creation_request_id": order["creation_request_id"],
        "training_title": order["training_title"],
        "rncp_code": order.get("rncp_code"),
        "total_hours": order["total_hours"],
        "catalog_amount_cents": order.get("catalog_amount_cents"),
        "charged_amount_cents": order.get("charged_amount_cents"),
        "currency": order.get("currency") or "eur",
        "authorization_kind": order.get("authorization_kind"),
        "payment_status": order.get("payment_status"),
        "review_status": order.get("review_status"),
        "fulfillment_status": order.get("fulfillment_status"),
        "platform_id": order.get("platform_id"),
        "pipeline_job_id": order.get("pipeline_job_id"),
        "last_error": order.get("last_error"),
        "paid_at": order.get("paid_at"),
        "refunded_at": order.get("refunded_at"),
        "created_at": order.get("created_at"),
        "updated_at": order.get("updated_at"),
    }
    if include_project:
        result["project"] = order.get("request_payload_json") or {}
    return result


def billing_context(center_account_id: int) -> dict[str, Any]:
    center = get_center_billing_account(center_account_id)
    if not center or not center.get("is_active"):
        raise BillingError("Compte centre introuvable ou désactivé.", status_code=403)
    exempt = _center_is_exempt(center)
    review_exempt = _center_review_is_exempt(center)
    return {
        "center_account_id": int(center["id"]),
        "billing_mode": "exempt" if exempt else "stripe_required",
        "payment_required": not exempt,
        "review_required": not review_exempt,
        "exemption_label": "Compte interne, paiement non requis" if exempt else None,
        "review_exemption_label": (
            "Compte administrateur, validation non requise" if review_exempt else None
        ),
        "products": get_product_catalog(),
    }


def billing_history(center_account_id: int) -> list[dict[str, Any]]:
    return [serialize_order(order) for order in list_center_billing_orders(center_account_id)]


def _teacher_name(order: dict[str, Any]) -> str:
    project = order.get("request_payload_json") or {}
    return str(project.get("teacher_name") or "Professeur IA").strip() or "Professeur IA"


def _training_day_count(order: dict[str, Any]) -> int:
    return training_days_for_order(order)


def _review_schedule_summary(order: Mapping[str, Any]) -> dict[str, Any]:
    project = order.get("request_payload_json") or {}
    new_formation = project.get("new_formation")
    if isinstance(new_formation, Mapping):
        schedule = new_formation.get("schedule") or {}
    else:
        schedule = project.get("schedule") or {}
    if not isinstance(schedule, Mapping):
        schedule = {}

    parsed_dates = []
    for raw_date in schedule.get("selected_dates") or []:
        try:
            parsed_dates.append(datetime.fromisoformat(str(raw_date)).date())
        except (TypeError, ValueError):
            continue
    parsed_dates.sort()

    training_days = _training_day_count(dict(order))
    try:
        weekly_course_count = int(schedule.get("weekly_course_count") or 0)
    except (TypeError, ValueError):
        weekly_course_count = 0

    if parsed_dates:
        span_days = (parsed_dates[-1] - parsed_dates[0]).days + 1
        training_weeks = max(1, (span_days + 6) // 7)
        schedule_start_date = parsed_dates[0].isoformat()
        schedule_end_date = parsed_dates[-1].isoformat()
    else:
        training_weeks = (
            max(1, (training_days + weekly_course_count - 1) // weekly_course_count)
            if training_days and weekly_course_count
            else None
        )
        schedule_start_date = str(schedule.get("start_date") or "").strip() or None
        schedule_end_date = None

    return {
        "training_weeks": training_weeks,
        "schedule_start_date": schedule_start_date,
        "schedule_end_date": schedule_end_date,
        "weekly_course_count": weekly_course_count or None,
        "scheduled_dates": [value.isoformat() for value in parsed_dates],
    }


def serialize_review_request(order: dict[str, Any]) -> dict[str, Any]:
    project = order.get("request_payload_json") or {}
    new_formation = project.get("new_formation")
    schedule = (
        new_formation.get("schedule")
        if isinstance(new_formation, Mapping)
        else project.get("schedule")
    ) or {}
    schedule_schema_version = _schedule_schema_version(schedule)
    return {
        **serialize_order(order),
        **_review_schedule_summary(order),
        "teacher_name": _teacher_name(order),
        "training_days": _training_day_count(order),
        "schedule_schema_version": schedule_schema_version,
        "planning_summary": summarize_v2_schedule(
            schedule,
            schema_version=schedule_schema_version,
        ),
        "center_name": order.get("center_name") or "Centre de formation",
        "center_email": order.get("center_email") or "",
        "internal_api_cost_cents": order.get("internal_api_cost_cents"),
        "review_note": order.get("review_note") or "",
        "reviewed_at": order.get("reviewed_at"),
        "reviewed_by": order.get("reviewed_by"),
        "unread": order.get("admin_seen_at") is None,
    }


def admin_review_inbox(*, exclude_center_account_id: int | None = None) -> dict[str, Any]:
    orders = [
        serialize_review_request(order)
        for order in list_teacher_order_reviews(
            exclude_center_account_id=exclude_center_account_id,
        )
    ]
    return {
        "requests": orders,
        "unread_count": sum(1 for order in orders if order["unread"]),
        "pending_count": sum(1 for order in orders if order["review_status"] == "pending"),
        "deepseek_url": os.getenv(
            "AI_TEXT_API_RECHARGE_URL", "https://platform.deepseek.com/top_up"
        ),
        "audio_url": os.getenv(
            "AI_AUDIO_API_RECHARGE_URL", "https://fish.audio/app/credits/"
        ),
    }


def mark_admin_review_seen(public_id: str) -> dict[str, Any]:
    order = mark_teacher_order_admin_seen(public_id)
    if not order:
        raise BillingError("Demande introuvable.", status_code=404)
    return serialize_order(order)


def _center_message_copy(order: dict[str, Any]) -> tuple[str, str, str, str | None]:
    teacher = _teacher_name(order)
    training_title = str(order.get("training_title") or "la formation concernée").strip()
    rncp_code = re.sub(
        r"^RNCP\s*",
        "",
        str(order.get("rncp_code") or "").strip(),
        flags=re.IGNORECASE,
    )
    review_status = order.get("review_status")
    payment_status = order.get("payment_status")
    fulfillment_status = order.get("fulfillment_status")
    if fulfillment_status == "fulfilled":
        return (
            f"{teacher} est disponible",
            f"Votre demande pour le professeur {teacher} a bien été acceptée. Il est maintenant disponible dans l’onglet Mes professeurs.",
            "success",
            "teachers",
        )
    if fulfillment_status == "failed":
        return (
            f"Préparation de {teacher} interrompue",
            "Votre paiement est conservé. Vous pouvez relancer la préparation sans effectuer un nouveau paiement.",
            "error",
            "teachers",
        )
    if payment_status == "paid":
        return (
            f"{teacher} est en préparation",
            "Le paiement est confirmé. Les cours sont en cours de préparation et le professeur apparaîtra automatiquement dans Mes professeurs.",
            "info",
            "teachers",
        )
    if review_status == "approved":
        return (
            "Votre demande est acceptée",
            f"La demande pour {teacher} a été validée.",
            "success",
            "payment",
        )
    if review_status == "rejected":
        note = str(order.get("review_note") or "").strip()
        suffix = f" Motif : {note}" if note else ""
        return (
            "Votre demande n’a pas été acceptée",
            f"Aucun paiement ne sera demandé pour {teacher}.{suffix}",
            "warning",
            None,
        )
    return (
        "Demande reçue",
        (
            f"La demande pour le professeur IA nommé {teacher}, pour la formation du titre "
            f"professionnel « {training_title} »"
            f"{f' au code RNCP numéro {rncp_code}' if rncp_code else ''}, est en cours de "
            "vérification par nos équipes. Vous recevrez un message très vite dès qu’une "
            "décision sera prise."
        ),
        "info",
        None,
    )


def serialize_center_message(order: dict[str, Any]) -> dict[str, Any]:
    title, body, tone, action = _center_message_copy(order)
    return {
        "id": str(order["public_id"]),
        "order_id": str(order["public_id"]),
        "title": title,
        "body": body,
        "tone": tone,
        "action": action,
        "teacher_name": _teacher_name(order),
        "training_title": order.get("training_title"),
        "rncp_code": order.get("rncp_code"),
        "review_status": order.get("review_status"),
        "payment_status": order.get("payment_status"),
        "fulfillment_status": order.get("fulfillment_status"),
        "created_at": order.get("created_at"),
        "updated_at": order.get("updated_at"),
        "read": order.get("center_seen_at") is not None,
    }


def center_message_inbox(center_account_id: int) -> dict[str, Any]:
    messages = [
        serialize_center_message(order)
        for order in list_center_order_messages(center_account_id)
    ]
    return {
        "messages": messages,
        "unread_count": sum(1 for message in messages if not message["read"]),
    }


def mark_center_message_seen(public_id: str, center_account_id: int) -> dict[str, Any]:
    order = mark_center_order_message_seen(public_id, center_account_id)
    if not order:
        raise BillingError("Message introuvable.", status_code=404)
    return serialize_center_message(order)


def get_center_invoice_link(public_id: str, center_account_id: int) -> dict[str, str]:
    """Resolve a hosted Stripe invoice, with the card receipt as a fallback."""
    order = get_center_order(public_id, center_account_id)
    if order.get("payment_status") not in {"paid", "refunded"}:
        raise BillingError("Aucune facture n’est disponible pour cette commande.", status_code=404)

    stripe = _stripe()
    checkout_session_id = order.get("stripe_checkout_session_id")
    if checkout_session_id:
        checkout = stripe.v1.checkout.sessions.retrieve(
            checkout_session_id,
            {"expand": ["invoice", "payment_intent.latest_charge"]},
        )
        invoice = getattr(checkout, "invoice", None)
        invoice_url = getattr(invoice, "hosted_invoice_url", None)
        if invoice_url:
            return {"url": invoice_url, "document_type": "invoice"}
        payment_intent = getattr(checkout, "payment_intent", None)
        latest_charge = getattr(payment_intent, "latest_charge", None)
        receipt_url = getattr(latest_charge, "receipt_url", None)
        if receipt_url:
            return {"url": receipt_url, "document_type": "receipt"}

    payment_intent_id = order.get("stripe_payment_intent_id")
    if payment_intent_id:
        payment_intent = stripe.v1.payment_intents.retrieve(
            payment_intent_id,
            {"expand": ["latest_charge"]},
        )
        latest_charge = getattr(payment_intent, "latest_charge", None)
        receipt_url = getattr(latest_charge, "receipt_url", None)
        if receipt_url:
            return {"url": receipt_url, "document_type": "receipt"}

    raise BillingError("La facture n’est pas encore disponible.", status_code=404)


def _billing_now():
    return datetime.now(FRANCE_TZ)


def _scheduled_audio_preparation_window_hours() -> tuple[float, float, float]:
    legacy_ready = os.getenv("SCHEDULED_AUDIO_HORIZON_HOURS", "72")
    try:
        ready_hours = float(
            os.getenv("SCHEDULED_AUDIO_READY_HOURS_BEFORE", legacy_ready)
        )
        build_buffer_hours = float(
            os.getenv("SCHEDULED_AUDIO_BUILD_BUFFER_HOURS", "2")
        )
    except (TypeError, ValueError) as exc:
        raise BillingError(
            "Le délai de préparation audio est invalide.",
            status_code=503,
        ) from exc
    if ready_hours <= 0 or build_buffer_hours < 0:
        raise BillingError(
            "La cible de disponibilité audio doit être positive et sa marge ne peut pas être négative.",
            status_code=503,
        )
    return ready_hours, build_buffer_hours, ready_hours + build_buffer_hours


def _first_schedule_occurrence_at_nine(start_date, weekdays):
    selected = {WEEKDAY_IDS[day] for day in weekdays}
    cursor_date = start_date
    for day_offset in range(7):
        candidate = cursor_date + timedelta(days=day_offset)
        if candidate.weekday() in selected:
            return FRANCE_TZ.localize(datetime.combine(candidate, time(9, 0)))
    raise BillingError("Aucun premier jour de formation n'a pu être calculé.")


def _assert_schedule_has_audio_preparation_horizon(start_date, weekdays):
    first_occurrence = _first_schedule_occurrence_at_nine(start_date, weekdays)
    ready_hours, build_buffer_hours, minimum_hours = (
        _scheduled_audio_preparation_window_hours()
    )
    now = _billing_now()
    if first_occurrence <= now + timedelta(hours=minimum_hours):
        label = first_occurrence.strftime("%d/%m/%Y à %H:%M")
        ready_label = int(ready_hours) if ready_hours.is_integer() else ready_hours
        buffer_label = (
            int(build_buffer_hours)
            if build_buffer_hours.is_integer()
            else build_buffer_hours
        )
        minimum_label = (
            int(minimum_hours) if minimum_hours.is_integer() else minimum_hours
        )
        raise BillingError(
            f"Planning impossible à préparer : la première journée tomberait le {label}. "
            f"Elle doit être à plus de {minimum_label}h : audio disponible H-{ready_label} "
            f"avec {buffer_label}h de marge de fabrication."
        )


def _normalize_schedule(schedule: Any, *, total_training_days: int) -> dict[str, Any]:
    if not isinstance(schedule, dict):
        raise BillingError("Le planning de la formation est requis.")
    try:
        weekly_count = int(schedule.get("weekly_course_count") or 0)
    except (TypeError, ValueError):
        weekly_count = 0
    weekdays = [str(day).strip().lower() for day in (schedule.get("weekdays") or [])]
    allowed_weekdays = {"lundi", "mardi", "mercredi", "jeudi", "vendredi"}
    if (
        weekly_count < 1
        or weekly_count > 5
        or len(weekdays) != weekly_count
        or len(set(weekdays)) != len(weekdays)
        or any(day not in allowed_weekdays for day in weekdays)
    ):
        raise BillingError("La cadence et les jours de cours sont incohérents.")
    start_date = str(schedule.get("start_date") or "").strip()
    try:
        parsed_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise BillingError("La date de début est invalide.") from exc
    if parsed_date < _billing_now().date():
        raise BillingError("La date de début ne peut pas être passée.")
    start_time = str(schedule.get("start_time") or "").strip()
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", start_time):
        raise BillingError("L’heure des cours est invalide.")
    start_time_policy = str(
        os.getenv("COURSE_START_TIME_POLICY") or "fixed_09"
    ).strip().lower()
    if start_time_policy not in {"fixed_09", "configured"}:
        raise BillingError(
            "La politique d’heure de cours est invalide.",
            status_code=503,
        )
    if start_time_policy == "fixed_09" and start_time != "09:00":
        raise BillingError(
            "Les journées de formation commencent obligatoirement à 09:00."
        )
    _assert_schedule_has_audio_preparation_horizon(parsed_date, weekdays)
    return {
        "total_training_days": int(total_training_days),
        "weekly_course_count": weekly_count,
        "weekdays": weekdays,
        "start_date": start_date,
        "start_time": start_time,
        "timezone": "Europe/Paris",
    }


def _normalize_project(data: dict[str, Any], center_account_id: int) -> tuple[str, dict[str, Any], dict[str, Any]]:
    operation_type = str(data.get("operation_type") or "").strip()
    if operation_type not in PRODUCTS:
        raise BillingError("Type de commande invalide.")
    creation_request_id = str(data.get("creation_request_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", creation_request_id):
        raise BillingError("Identifiant de demande invalide.")

    project = dict(data.get("project") or {})
    project["name"] = str(project.get("name") or "").strip()[:160]
    project["teacher_name"] = str(project.get("teacher_name") or "").strip()[:80]
    project["teacher_color"] = str(project.get("teacher_color") or "violet").strip().lower()
    project["teacher_description"] = str(project.get("teacher_description") or "").strip()[:600]
    raw_slide_brand_name = project.get("slide_brand_name")
    project["slide_brand_name"] = (
        "Le Socrate"
        if raw_slide_brand_name is None
        else str(raw_slide_brand_name).strip()[:120]
    )
    raw_ai_voice_id = project.get("ai_voice_id")
    if raw_ai_voice_id in (None, ""):
        project["ai_voice_id"] = None
    else:
        try:
            project["ai_voice_id"] = int(raw_ai_voice_id)
        except (TypeError, ValueError) as exc:
            raise BillingError("Voix IA invalide.") from exc
        from repositories.ai_voice_repository import get_voice

        if get_voice(center_account_id, project["ai_voice_id"]) is None:
            raise BillingError("Cette voix IA n’est pas disponible pour ce centre.", status_code=404)
    if not project["name"] or not project["teacher_name"]:
        raise BillingError("Le nom du professeur et celui du projet sont requis.")
    if project["teacher_color"] not in {"violet", "blue", "pink", "green", "amber"}:
        raise BillingError("Couleur de professeur invalide.")

    if operation_type == "new_teacher":
        formation = dict(project.get("new_formation") or {})
        formation["tp_name"] = str(formation.get("tp_name") or "").strip()[:200]
        formation["rncp_code"] = str(formation.get("rncp_code") or "").strip()[:80]
        schedule_version = _schedule_schema_version(formation.get("schedule"))
        if not formation["tp_name"] or not formation["rncp_code"]:
            raise BillingError("La formation et le code RNCP sont requis.")
        if schedule_version == SCHEDULE_SCHEMA_VERSION:
            formation["schedule"] = _normalize_v2_new_schedule(
                formation.get("schedule"),
                center_account_id=center_account_id,
            )
            training_days = int(formation["schedule"]["day_count"])
            # ``ai_teacher_orders`` and a few legacy diagnostics still require
            # an integer total_hours. V2 never derives a day count or a price
            # from it; the immutable snapshot is authoritative.
            formation["total_hours"] = training_days * 7
        else:
            try:
                formation["total_hours"] = int(formation.get("total_hours") or 0)
            except (TypeError, ValueError):
                formation["total_hours"] = 0
            if (
                formation["total_hours"] <= 0
                or formation["total_hours"] % 7 != 0
            ):
                raise BillingError(
                    "La formation, le code RNCP et la durée sont requis."
                )
            training_days = formation["total_hours"] // 7
            formation["schedule"] = _normalize_schedule(
                formation.get("schedule"),
                total_training_days=training_days,
            )
        project["new_formation"] = formation
        details = {
            "training_title": formation["tp_name"],
            "rncp_code": formation["rncp_code"],
            "total_hours": formation["total_hours"],
            "training_days": training_days,
            "source_module_id": None,
        }
    else:
        try:
            module_id = int(project.get("module_id") or 0)
        except (TypeError, ValueError):
            module_id = 0
        module = get_reusable_module(module_id, center_account_id) if module_id else None
        if (
            not module
            or module.get("status") != "validated"
            or int(module.get("nb_folders") or 0) <= 0
            or module.get("voice_type") == "mock"
        ):
            raise BillingError("Cet ancien professeur n’est pas réutilisable.", status_code=404)
        total_hours = max(7, int(module.get("total_hours") or 0))
        schedule_version = _authoritative_reuse_schedule_version(
            project.get("schedule"),
            module=module,
        )
        if schedule_version == SCHEDULE_SCHEMA_VERSION:
            project["schedule"] = _normalize_v2_reuse_schedule(
                project.get("schedule"),
                module=module,
            )
            training_days = int(project["schedule"]["day_count"])
        else:
            training_days = max(1, (total_hours + 6) // 7)
            project["schedule"] = _normalize_schedule(
                project.get("schedule"),
                total_training_days=training_days,
            )
        project["module_id"] = module_id
        details = {
            "training_title": module["tp_name"],
            "rncp_code": module.get("rncp_code"),
            "total_hours": total_hours,
            "training_days": training_days,
            "source_module_id": module_id,
        }
    canonical = json.dumps(
        {"operation_type": operation_type, "project": project},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    details["request_fingerprint"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    details["creation_request_id"] = creation_request_id
    return operation_type, project, details


def _enqueue_fulfillment(order: dict[str, Any]) -> dict[str, Any]:
    return enqueue_order_fulfillment(int(order["id"])) or order


def _review_serializer() -> URLSafeTimedSerializer:
    secret = os.getenv("SECRET_KEY", "fallback_secret_key_for_dev")
    return URLSafeTimedSerializer(secret, salt="ai-teacher-order-review-v1")


def create_review_token(public_id: str) -> str:
    return _review_serializer().dumps({"order": str(public_id)})


def validate_review_token(public_id: str, token: str) -> None:
    try:
        payload = _review_serializer().loads(token, max_age=14 * 24 * 60 * 60)
    except SignatureExpired as exc:
        raise BillingError("Ce lien de validation a expiré.", status_code=410) from exc
    except BadSignature as exc:
        raise BillingError("Lien de validation invalide.", status_code=403) from exc
    if str(payload.get("order") or "") != str(public_id):
        raise BillingError("Lien de validation invalide.", status_code=403)


def get_review_order(public_id: str, token: str) -> dict[str, Any]:
    validate_review_token(public_id, token)
    order = get_order(public_id)
    if not order:
        raise BillingError("Demande introuvable.", status_code=404)
    center = get_center_billing_account(int(order["center_account_id"]))
    if not center:
        raise BillingError("Centre introuvable.", status_code=404)
    return {"order": order, "center": center}


def training_days_for_order(order: Mapping[str, Any]) -> int:
    project = order.get("request_payload_json") or {}
    schedule = (project.get("new_formation") or {}).get("schedule") or project.get("schedule") or {}
    return max(
        1,
        int(
            schedule.get("day_count")
            or schedule.get("total_training_days")
            or len(schedule.get("selected_dates") or [])
            or ((int(order.get("total_hours") or 7) + 6) // 7)
        ),
    )


def _create_checkout_for_order(order: dict[str, Any], center: dict[str, Any]) -> dict[str, Any]:
    stripe = _stripe()
    existing_session_id = order.get("stripe_checkout_session_id")
    if existing_session_id:
        existing = stripe.v1.checkout.sessions.retrieve(existing_session_id)
        if getattr(existing, "status", None) == "open" and getattr(existing, "url", None):
            return {"order": order, "checkout_url": existing.url}

    training_days = training_days_for_order(order)
    total_amount = int(order.get("catalog_amount_cents") or 0)
    unit_amount = total_amount // training_days
    if unit_amount <= 0 or unit_amount * training_days != total_amount:
        raise BillingError("Le montant approuvé est invalide.", status_code=409)

    frontend_url = os.getenv("PLATFORM_1_FRONTEND_URL", "").strip().rstrip("/")
    if not frontend_url:
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173").strip().rstrip("/")
    public_id = str(order["public_id"])
    stripe_price_id = str(order.get("stripe_price_id") or "").strip()
    line_item = (
        {"price": stripe_price_id, "quantity": training_days}
        if stripe_price_id
        else {
            "price_data": {
                "currency": order.get("currency") or "eur",
                "unit_amount": unit_amount,
                "product_data": {
                    "name": "Professeur IA · journée de formation",
                    "description": f"{training_days} journée(s) de formation IA",
                },
            },
            "quantity": training_days,
        }
    )
    checkout_params = dict(
        mode="payment",
        locale="fr",
        submit_type="pay",
        invoice_creation={"enabled": True},
        line_items=[line_item],
        client_reference_id=public_id,
        billing_address_collection="required",
        tax_id_collection={"enabled": True},
        metadata={"ai_teacher_order_id": str(order["id"]), "order_public_id": public_id},
        payment_intent_data={"metadata": {"ai_teacher_order_id": str(order["id"]), "order_public_id": public_id}},
        success_url=(
            f"{frontend_url}/dashboard-centre?checkout=success&order={public_id}"
            "&session_id={CHECKOUT_SESSION_ID}"
        ),
        cancel_url=f"{frontend_url}/dashboard-centre?checkout=cancelled&order={public_id}",
    )
    if "@" in str(center.get("username") or ""):
        checkout_params["customer_email"] = center["username"]
    checkout = stripe.v1.checkout.sessions.create(
        checkout_params,
        {
            "idempotency_key": (
                f"ai-teacher-order-{order['id']}-checkout-"
                f"{int(order.get('checkout_attempt_count') or 0) + 1}"
            ),
        },
    )
    expires_at = datetime.fromtimestamp(checkout.expires_at, tz=timezone.utc) if checkout.expires_at else None
    stored = attach_checkout_session(
        int(order["id"]),
        checkout_session_id=checkout.id,
        payment_intent_id=getattr(checkout, "payment_intent", None),
        expires_at=expires_at,
    )
    return {"order": stored, "checkout_url": checkout.url}


def approve_teacher_order_review(public_id: str, token: str) -> dict[str, Any]:
    validate_review_token(public_id, token)
    order = approve_order_review(public_id, os.getenv("BILLING_REVIEW_NOTIFICATION_EMAIL", "secretariat@saleshacking.fr"))
    if not order:
        raise BillingError("Demande introuvable.", status_code=404)
    if order.get("review_status") != "approved":
        raise BillingError("Cette demande ne peut plus être approuvée.", status_code=409)
    center = get_center_billing_account(int(order["center_account_id"]))
    if not center:
        raise BillingError("Centre introuvable.", status_code=404)
    result = _create_checkout_for_order(order, center)
    payment_email_sent = bool(order.get("payment_email_sent_at"))
    if not payment_email_sent:
        payment_email_sent = send_payment_link(
            result["order"], center, result["checkout_url"]
        )
        if payment_email_sent:
            mark_order_notification_sent(int(order["id"]), "payment_email_sent_at")
    return {**result, "payment_email_sent": payment_email_sent}


def approve_teacher_order_from_admin(
    public_id: str,
    reviewed_by: str = "admin",
) -> dict[str, Any]:
    """Approve from the authenticated internal inbox, without an e-mail token."""
    current = get_order(public_id)
    if not current:
        raise BillingError("Demande introuvable.", status_code=404)
    if current.get("review_status") != "pending":
        raise BillingError("Cette demande a déjà été traitée.", status_code=409)
    order = approve_order_review(public_id, reviewed_by)
    if not order or order.get("review_status") != "approved":
        raise BillingError("Cette demande ne peut plus être approuvée.", status_code=409)
    center = get_center_billing_account(int(order["center_account_id"]))
    if not center:
        raise BillingError("Centre introuvable.", status_code=404)
    result = _create_checkout_for_order(order, center)
    payment_email_sent = send_payment_link(
        result["order"], center, result["checkout_url"]
    )
    if payment_email_sent:
        mark_order_notification_sent(int(order["id"]), "payment_email_sent_at")
    return {**result, "payment_email_sent": payment_email_sent}


def reject_teacher_order_review(public_id: str, token: str, note: str = "") -> dict[str, Any]:
    validate_review_token(public_id, token)
    order = reject_order_review(
        public_id,
        os.getenv("BILLING_REVIEW_NOTIFICATION_EMAIL", "secretariat@saleshacking.fr"),
        note,
    )
    if not order:
        raise BillingError("Demande introuvable.", status_code=404)
    return order


def reject_teacher_order_from_admin(
    public_id: str,
    reviewed_by: str = "admin",
    note: str = "",
) -> dict[str, Any]:
    current = get_order(public_id)
    if not current:
        raise BillingError("Demande introuvable.", status_code=404)
    if current.get("review_status") != "pending":
        raise BillingError("Cette demande a déjà été traitée.", status_code=409)
    order = reject_order_review(public_id, reviewed_by, note)
    if not order:
        raise BillingError("Demande introuvable.", status_code=404)
    return order


def create_teacher_order(center_account_id: int, data: dict[str, Any]) -> dict[str, Any]:
    center = get_center_billing_account(center_account_id)
    if not center or not center.get("is_active"):
        raise BillingError("Compte centre introuvable ou désactivé.", status_code=403)
    operation_type, project, details = _normalize_project(data, center_account_id)
    product = get_product_catalog()[operation_type]
    training_days = int(details["training_days"])
    catalog_amount_cents = int(product["unit_amount_cents"]) * training_days
    internal_api_cost_cents = int(
        product.get("production_cost_per_day_cents") or _production_cost_per_day_cents()
    ) * training_days
    payment_exempt = _center_is_exempt(center)
    review_exempt = _center_review_is_exempt(center)
    if not payment_exempt and not product["configured"]:
        raise BillingError("Le paiement de ce service n’est pas encore configuré.", status_code=503)

    order, created = create_order({
        "center_account_id": int(center_account_id),
        "operation_type": operation_type,
        "source_module_id": details["source_module_id"],
        "status": (
            "authorized" if payment_exempt
            else "awaiting_payment" if review_exempt
            else "awaiting_review"
        ),
        "payment_status": (
            "not_required" if payment_exempt
            else "awaiting_payment" if review_exempt
            else "not_requested"
        ),
        "review_status": "not_required" if review_exempt else "pending",
        "training_title": details["training_title"],
        "rncp_code": details["rncp_code"],
        "total_hours": details["total_hours"],
        "request_payload": project,
        "creation_request_id": details["creation_request_id"],
        "request_fingerprint": details["request_fingerprint"],
        "pricing_key": product["pricing_key"],
        "stripe_price_id": product.get("stripe_price_id"),
        "catalog_amount_cents": catalog_amount_cents,
        "internal_api_cost_cents": internal_api_cost_cents,
        "charged_amount_cents": 0 if payment_exempt else None,
        "currency": product["currency"],
        "authorization_kind": "center_exemption" if payment_exempt else "stripe",
    })
    if not created and order["request_fingerprint"] != details["request_fingerprint"]:
        raise BillingError("Cette demande existe déjà avec un autre contenu.", status_code=409)
    new_schedule = (project.get("new_formation") or {}).get("schedule") or {}
    if (
        operation_type == "new_teacher"
        and _schedule_schema_version(new_schedule) == SCHEDULE_SCHEMA_VERSION
    ):
        template_ids = {
            int(template_id)
            for template_id in (
                new_schedule.get("template_assignments") or {}
            ).values()
        }
        for template_id in sorted(template_ids):
            expected_hash = str(
                (new_schedule.get("template_hashes") or {}).get(
                    str(template_id)
                )
                or ""
            )
            if not mark_template_used(
                center_account_id,
                template_id,
                expected_blocks_hash=expected_hash,
            ):
                raise BillingError(
                    f"Le template de journée {template_id} n’est plus "
                    "disponible dans la version confirmée.",
                    status_code=409,
                )
    if order.get("fulfillment_status") in {"queued", "running", "fulfilled"}:
        return {"order": order, "next_action": "track"}
    if order.get("payment_status") in {"paid", "not_required"}:
        return {"order": _enqueue_fulfillment(order), "next_action": "track"}
    if order.get("review_status") in {"approved", "not_required"}:
        checkout = _create_checkout_for_order(order, center)
        return {**checkout, "next_action": "redirect"}
    if not order.get("review_email_sent_at"):
        base_url = os.getenv(
            "BILLING_REVIEW_BASE_URL",
            "http://localhost:5000",
        ).strip().rstrip("/")
        token = create_review_token(str(order["public_id"]))
        review_url = f"{base_url}/billing/review/{order['public_id']}?token={token}"
        if send_review_request(order, center, review_url):
            mark_order_notification_sent(int(order["id"]), "review_email_sent_at")
    return {"order": order, "next_action": "pending_review"}


def process_stripe_webhook(raw_payload: bytes, signature: str) -> None:
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise BillingError("Webhook Stripe non configuré.", status_code=503)
    stripe = _stripe_sdk()
    try:
        event_obj = stripe.Webhook.construct_event(raw_payload, signature, secret)
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        raise BillingError("Signature Stripe invalide.", status_code=400) from exc
    if hasattr(event_obj, "to_dict_recursive"):
        event = event_obj.to_dict_recursive()
    elif isinstance(event_obj, dict):
        event = event_obj
    else:  # pragma: no cover - compatibility with older Stripe SDK objects
        event = json.loads(raw_payload.decode("utf-8"))
    try:
        apply_stripe_webhook_event(event)
    except ValueError as exc:
        record_webhook_failure(event, str(exc))
        raise BillingError(str(exc), status_code=400) from exc
    except Exception as exc:
        try:
            record_webhook_failure(event, str(exc))
        except Exception:
            # Preserve the processing error so Stripe retries even if the
            # diagnostic write is temporarily unavailable too.
            pass
        raise


def get_center_order(public_id: str, center_account_id: int) -> dict[str, Any]:
    order = get_order(public_id, center_account_id=center_account_id)
    if not order:
        raise BillingError("Commande introuvable.", status_code=404)
    return order


def reconcile_center_checkout_payment(
    public_id: str,
    center_account_id: int,
    *,
    returned_session_id: str | None = None,
) -> dict[str, Any]:
    """Confirm Checkout server-side as a reliable success-page fallback."""
    order = get_center_order(public_id, center_account_id)
    session_id = str(order.get("stripe_checkout_session_id") or "").strip()
    if not session_id:
        raise BillingError("Session Stripe introuvable.", status_code=409)
    if returned_session_id and str(returned_session_id).strip() != session_id:
        raise BillingError("Session Stripe incohérente.", status_code=409)

    checkout = _stripe().v1.checkout.sessions.retrieve(session_id)
    reconciled = reconcile_stripe_checkout_session(
        _stripe_object_dict(checkout),
        center_account_id=int(center_account_id),
    )
    if not reconciled:
        raise BillingError("Commande Stripe introuvable.", status_code=404)
    return reconciled


def get_center_checkout_link(public_id: str, center_account_id: int) -> dict[str, str]:
    """Open or renew the Stripe Checkout session for an approved center order."""
    order = get_center_order(public_id, center_account_id)
    if order.get("review_status") != "approved":
        raise BillingError("Cette demande n’est pas prête au paiement.", status_code=409)
    if order.get("payment_status") != "awaiting_payment":
        raise BillingError("Cette commande ne peut plus être payée.", status_code=409)

    center = get_center_billing_account(center_account_id)
    if not center or not center.get("is_active"):
        raise BillingError("Compte centre introuvable ou désactivé.", status_code=403)

    result = _create_checkout_for_order(order, center)
    return {"url": result["checkout_url"]}


def retry_center_order(public_id: str, center_account_id: int) -> dict[str, Any]:
    """Requeue a paid failed fulfillment without creating a second charge."""
    order = get_center_order(public_id, center_account_id)
    if order.get("payment_status") not in {"paid", "not_required"}:
        raise BillingError("Cette commande n’est pas autorisée au paiement.", status_code=409)
    if order.get("fulfillment_status") == "fulfilled":
        return order
    if order.get("fulfillment_status") in {"queued", "running"}:
        return order
    if order.get("fulfillment_status") != "failed":
        raise BillingError("Cette commande ne peut pas être relancée.", status_code=409)

    retried = retry_order_fulfillment(int(order["id"]), int(center_account_id))
    if not retried:
        raise BillingError("Commande introuvable.", status_code=404)
    if retried.get("fulfillment_status") not in {"queued", "running", "fulfilled"}:
        raise BillingError("La préparation n’a pas pu être remise en file.", status_code=409)
    return retried
