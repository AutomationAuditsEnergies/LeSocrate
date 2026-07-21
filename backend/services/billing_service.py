"""Server-authoritative Stripe Checkout and order authorization."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, time, timedelta, timezone
from typing import Any

from config import FRANCE_TZ
from repositories.billing_repository import (
    apply_stripe_webhook_event,
    attach_checkout_session,
    create_order,
    enqueue_order_fulfillment,
    get_center_billing_account,
    get_order,
    get_reusable_module,
    record_webhook_failure,
    retry_order_fulfillment,
)


class BillingError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


PRODUCTS = {
    "new_teacher": {
        "pricing_key": "new_teacher",
        "label": "Nouveau professeur IA",
        "multiplier_numerator": 2,
        "multiplier_denominator": 1,
    },
    "reuse_teacher": {
        "pricing_key": "reuse_teacher",
        "label": "Réutilisation d’un professeur IA",
        "multiplier_numerator": 3,
        "multiplier_denominator": 2,
    },
}

SERVER_EXEMPT_CENTER_EMAILS = frozenset({"newpiprod@gmail.com"})
WEEKDAY_IDS = {
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
}


def _center_is_exempt(center: dict[str, Any]) -> bool:
    normalized_username = str(center.get("username") or "").strip().lower()
    return (
        normalized_username in SERVER_EXEMPT_CENTER_EMAILS
        or center.get("billing_mode") == "exempt"
    )


def _stripe():
    try:
        import stripe
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise BillingError("Le service de paiement n’est pas installé.", status_code=503) from exc
    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret:
        raise BillingError("Le paiement n’est pas encore configuré.", status_code=503)
    stripe.api_key = secret
    return stripe


def _production_cost_per_day_cents() -> int:
    raw = os.getenv("AI_TEACHER_COST_PER_DAY_CENTS", "1500").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise BillingError("Le coût de production journalier est invalide.", status_code=503)
    if value <= 0:
        raise BillingError("Le coût de production journalier doit être positif.", status_code=503)
    return value


def get_product_catalog(*, allow_fallback: bool = True) -> dict[str, dict[str, Any]]:
    del allow_fallback  # kept for compatibility with older callers
    production_cost = _production_cost_per_day_cents()
    stripe_configured = bool(os.getenv("STRIPE_SECRET_KEY", "").strip())
    catalog = {}
    for operation_type, product in PRODUCTS.items():
        unit_amount = (
            production_cost
            * int(product["multiplier_numerator"])
            // int(product["multiplier_denominator"])
        )
        catalog[operation_type] = {
            "operation_type": operation_type,
            "label": product["label"],
            "pricing_key": product["pricing_key"],
            "production_cost_per_day_cents": production_cost,
            "unit_amount_cents": unit_amount,
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
        "fulfillment_status": order.get("fulfillment_status"),
        "platform_id": order.get("platform_id"),
        "pipeline_job_id": order.get("pipeline_job_id"),
        "last_error": order.get("last_error"),
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
    return {
        "center_account_id": int(center["id"]),
        "billing_mode": "exempt" if exempt else "stripe_required",
        "payment_required": not exempt,
        "exemption_label": "Compte interne, paiement non requis" if exempt else None,
        "products": get_product_catalog(),
    }


def _billing_now():
    return datetime.now(FRANCE_TZ)


def _scheduled_audio_preparation_window_hours() -> tuple[float, float, float]:
    legacy_ready = os.getenv("SCHEDULED_AUDIO_HORIZON_HOURS", "24")
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
    if not project["name"] or not project["teacher_name"]:
        raise BillingError("Le nom du professeur et celui du projet sont requis.")
    if project["teacher_color"] not in {"violet", "blue", "pink", "green", "amber"}:
        raise BillingError("Couleur de professeur invalide.")

    if operation_type == "new_teacher":
        formation = dict(project.get("new_formation") or {})
        formation["tp_name"] = str(formation.get("tp_name") or "").strip()[:200]
        formation["rncp_code"] = str(formation.get("rncp_code") or "").strip()[:80]
        try:
            formation["total_hours"] = int(formation.get("total_hours") or 0)
        except (TypeError, ValueError):
            formation["total_hours"] = 0
        if (
            not formation["tp_name"]
            or not formation["rncp_code"]
            or formation["total_hours"] <= 0
            or formation["total_hours"] % 7 != 0
        ):
            raise BillingError("La formation, le code RNCP et la durée sont requis.")
        formation["schedule"] = _normalize_schedule(
            formation.get("schedule"),
            total_training_days=formation["total_hours"] // 7,
        )
        project["new_formation"] = formation
        details = {
            "training_title": formation["tp_name"],
            "rncp_code": formation["rncp_code"],
            "total_hours": formation["total_hours"],
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
        project["schedule"] = _normalize_schedule(
            project.get("schedule"),
            total_training_days=max(1, (total_hours + 6) // 7),
        )
        project["module_id"] = module_id
        details = {
            "training_title": module["tp_name"],
            "rncp_code": module.get("rncp_code"),
            "total_hours": total_hours,
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


def create_teacher_order(center_account_id: int, data: dict[str, Any]) -> dict[str, Any]:
    center = get_center_billing_account(center_account_id)
    if not center or not center.get("is_active"):
        raise BillingError("Compte centre introuvable ou désactivé.", status_code=403)
    operation_type, project, details = _normalize_project(data, center_account_id)
    product = get_product_catalog()[operation_type]
    training_days = max(1, (int(details["total_hours"]) + 6) // 7)
    catalog_amount_cents = int(product["unit_amount_cents"]) * training_days
    exempt = _center_is_exempt(center)
    if not exempt and not product["configured"]:
        raise BillingError("Le paiement de ce service n’est pas encore configuré.", status_code=503)

    order, created = create_order({
        "center_account_id": int(center_account_id),
        "operation_type": operation_type,
        "source_module_id": details["source_module_id"],
        "status": "authorized" if exempt else "awaiting_payment",
        "payment_status": "not_required" if exempt else "awaiting_payment",
        "training_title": details["training_title"],
        "rncp_code": details["rncp_code"],
        "total_hours": details["total_hours"],
        "request_payload": project,
        "creation_request_id": details["creation_request_id"],
        "request_fingerprint": details["request_fingerprint"],
        "pricing_key": product["pricing_key"],
        "stripe_price_id": None,
        "catalog_amount_cents": catalog_amount_cents,
        "charged_amount_cents": 0 if exempt else None,
        "currency": product["currency"],
        "authorization_kind": "center_exemption" if exempt else "stripe",
    })
    if not created and order["request_fingerprint"] != details["request_fingerprint"]:
        raise BillingError("Cette demande existe déjà avec un autre contenu.", status_code=409)
    if order.get("fulfillment_status") in {"queued", "running", "fulfilled"}:
        return {"order": order, "next_action": "track"}
    if order.get("payment_status") in {"paid", "not_required"}:
        return {"order": _enqueue_fulfillment(order), "next_action": "track"}

    stripe = _stripe()
    existing_session_id = order.get("stripe_checkout_session_id")
    if existing_session_id:
        existing = stripe.checkout.Session.retrieve(existing_session_id)
        if getattr(existing, "status", None) == "open" and getattr(existing, "url", None):
            return {"order": order, "next_action": "redirect", "checkout_url": existing.url}

    frontend_url = os.getenv("PLATFORM_1_FRONTEND_URL", "").strip().rstrip("/")
    if not frontend_url:
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173").strip().rstrip("/")
    public_id = str(order["public_id"])
    checkout_params = dict(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": order["currency"],
                "unit_amount": int(product["unit_amount_cents"]),
                "product_data": {
                    "name": product["label"],
                    "description": f"{training_days} journée(s) de formation IA",
                },
            },
            "quantity": training_days,
        }],
        client_reference_id=public_id,
        billing_address_collection="required",
        tax_id_collection={"enabled": True},
        metadata={"ai_teacher_order_id": str(order["id"]), "order_public_id": public_id},
        payment_intent_data={"metadata": {"ai_teacher_order_id": str(order["id"]), "order_public_id": public_id}},
        success_url=f"{frontend_url}/dashboard-centre?checkout=success&order={public_id}",
        cancel_url=f"{frontend_url}/dashboard-centre?checkout=cancelled&order={public_id}",
        idempotency_key=f"ai-teacher-order-{order['id']}-checkout-{int(order.get('checkout_attempt_count') or 0) + 1}",
    )
    if "@" in str(center["username"]):
        checkout_params["customer_email"] = center["username"]
    checkout = stripe.checkout.Session.create(**checkout_params)
    expires_at = datetime.fromtimestamp(checkout.expires_at, tz=timezone.utc) if checkout.expires_at else None
    order = attach_checkout_session(
        int(order["id"]),
        checkout_session_id=checkout.id,
        payment_intent_id=getattr(checkout, "payment_intent", None),
        expires_at=expires_at,
    )
    return {"order": order, "next_action": "redirect", "checkout_url": checkout.url}


def process_stripe_webhook(raw_payload: bytes, signature: str) -> None:
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise BillingError("Webhook Stripe non configuré.", status_code=503)
    stripe = _stripe()
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
