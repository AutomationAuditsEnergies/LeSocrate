"""HTTP boundary for center billing and Stripe webhooks."""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from database.postgres import postgres_enabled
from services.billing_service import (
    BillingError,
    billing_history,
    billing_context,
    create_teacher_order,
    get_center_order,
    get_center_invoice_link,
    process_stripe_webhook,
    retry_center_order,
    serialize_order,
)
from utils.logger import get_logger
from services.pipeline_worker_health import get_pipeline_worker_health


logger = get_logger(__name__)
billing_bp = Blueprint("billing", __name__)


def _center_id() -> int | None:
    if not session.get("is_admin") or session.get("admin_account_type") != "training_center":
        return None
    try:
        return int(session.get("admin_account_id"))
    except (TypeError, ValueError):
        return None


def _error(exc: BillingError):
    return jsonify({"success": False, "error": str(exc)}), exc.status_code


@billing_bp.get("/api/hr/billing/catalog")
def get_billing_catalog():
    center_id = _center_id()
    if not center_id:
        return jsonify({"success": False, "error": "Compte centre requis"}), 403
    if not postgres_enabled():
        return jsonify({"success": False, "error": "PostgreSQL requis"}), 503
    try:
        return jsonify({"success": True, **billing_context(center_id)}), 200
    except BillingError as exc:
        return _error(exc)


@billing_bp.get("/api/hr/billing/history")
def get_billing_history():
    center_id = _center_id()
    if not center_id:
        return jsonify({"success": False, "error": "Compte centre requis"}), 403
    if not postgres_enabled():
        return jsonify({"success": False, "error": "PostgreSQL requis"}), 503
    try:
        return jsonify({"success": True, "orders": billing_history(center_id)}), 200
    except BillingError as exc:
        return _error(exc)


@billing_bp.get("/api/hr/billing/orders/<uuid:public_id>/invoice")
def get_billing_invoice(public_id):
    center_id = _center_id()
    if not center_id:
        return jsonify({"success": False, "error": "Compte centre requis"}), 403
    try:
        return jsonify({"success": True, **get_center_invoice_link(str(public_id), center_id)}), 200
    except BillingError as exc:
        return _error(exc)


@billing_bp.get("/api/hr/system/worker-health")
def get_worker_health():
    if not _center_id():
        return jsonify({"success": False, "error": "Compte centre requis"}), 403
    health = get_pipeline_worker_health()
    return jsonify({"success": True, "worker": health}), (200 if health["healthy"] else 503)


@billing_bp.post("/api/hr/teacher-orders")
def post_teacher_order():
    center_id = _center_id()
    if not center_id:
        return jsonify({"success": False, "error": "Compte centre requis"}), 403
    if not postgres_enabled():
        return jsonify({"success": False, "error": "PostgreSQL requis"}), 503
    try:
        result = create_teacher_order(center_id, request.get_json(silent=True) or {})
        return jsonify({
            "success": True,
            "order": serialize_order(result["order"], include_project=True),
            "next_action": result["next_action"],
            "checkout_url": result.get("checkout_url"),
        }), 201
    except BillingError as exc:
        return _error(exc)
    except Exception:
        logger.exception("AI_TEACHER_ORDER_CREATE_FAILED center_id=%s", center_id)
        return jsonify({"success": False, "error": "Impossible de préparer la commande."}), 500


@billing_bp.get("/api/hr/teacher-orders/<uuid:public_id>")
def get_teacher_order(public_id):
    center_id = _center_id()
    if not center_id:
        return jsonify({"success": False, "error": "Compte centre requis"}), 403
    try:
        order = get_center_order(str(public_id), center_id)
        return jsonify({"success": True, "order": serialize_order(order, include_project=True)}), 200
    except BillingError as exc:
        return _error(exc)


@billing_bp.post("/api/hr/teacher-orders/<uuid:public_id>/retry")
def retry_teacher_order(public_id):
    center_id = _center_id()
    if not center_id:
        return jsonify({"success": False, "error": "Compte centre requis"}), 403
    if not postgres_enabled():
        return jsonify({"success": False, "error": "PostgreSQL requis"}), 503
    try:
        order = retry_center_order(str(public_id), center_id)
        return jsonify({
            "success": True,
            "order": serialize_order(order, include_project=True),
            "next_action": "track",
        }), 202
    except BillingError as exc:
        return _error(exc)
    except Exception:
        logger.exception(
            "AI_TEACHER_ORDER_RETRY_FAILED center_id=%s order_id=%s",
            center_id,
            public_id,
        )
        return jsonify({"success": False, "error": "Impossible de relancer la préparation."}), 500


@billing_bp.post("/api/billing/stripe/webhook")
def stripe_webhook():
    try:
        process_stripe_webhook(
            request.get_data(cache=False, as_text=False),
            request.headers.get("Stripe-Signature", ""),
        )
        return jsonify({"received": True}), 200
    except BillingError as exc:
        return jsonify({"received": False, "error": str(exc)}), exc.status_code
    except Exception:
        logger.exception("STRIPE_WEBHOOK_PROCESSING_FAILED")
        # Stripe will retry non-2xx responses. The event log remains available
        # for diagnosis, while fulfillment remains idempotent.
        return jsonify({"received": False, "error": "Traitement temporairement indisponible"}), 500
