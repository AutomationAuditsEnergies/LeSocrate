"""HTTP boundary for center billing and Stripe webhooks."""

from __future__ import annotations

import html
import os

from flask import Blueprint, jsonify, request, session

from database.postgres import postgres_enabled
from services.billing_service import (
    BillingError,
    billing_history,
    billing_context,
    admin_review_inbox,
    approve_teacher_order_from_admin,
    approve_teacher_order_review,
    center_message_inbox,
    center_can_manage_review,
    center_can_review_orders,
    create_teacher_order,
    get_review_order,
    get_center_checkout_link,
    get_center_order,
    get_center_invoice_link,
    mark_admin_review_seen,
    mark_center_message_seen,
    process_stripe_webhook,
    reconcile_center_checkout_payment,
    reject_teacher_order_review,
    reject_teacher_order_from_admin,
    retry_center_order,
    serialize_order,
    training_days_for_order,
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


def _internal_admin() -> bool:
    return bool(
        session.get("is_admin")
        and str(session.get("admin_account_type") or "").lower()
        in {"legacy_admin", "superadmin"}
    )


def _review_admin_context() -> tuple[bool, int | None]:
    if _internal_admin():
        return True, None
    center_id = _center_id()
    if center_id and center_can_review_orders(center_id):
        return True, center_id
    return False, None


def _delegated_review_target_allowed(public_id, reviewing_center_id: int | None) -> bool:
    return reviewing_center_id is None or center_can_manage_review(
        str(public_id),
        reviewing_center_id,
    )


def _error(exc: BillingError):
    return jsonify({"success": False, "error": str(exc)}), exc.status_code


def _review_html(title: str, content: str, *, status_code: int = 200):
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · Le Socrate</title></head>
<body style="margin:0;background:#f8fafc;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#0f172a">
<main style="max-width:720px;margin:0 auto;padding:40px 18px">
<p style="font-size:13px;font-weight:700;letter-spacing:.08em;color:#7c3aed">LE SOCRATE · VALIDATION INTERNE</p>
<section style="margin-top:14px;background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:30px">
<h1 style="margin:0;font-size:26px">{html.escape(title)}</h1>{content}</section></main></body></html>""", status_code, {"Content-Type": "text/html; charset=utf-8"}


@billing_bp.get("/billing/review/<uuid:public_id>")
def review_teacher_order_page(public_id):
    token = request.args.get("token", "")
    try:
        context = get_review_order(str(public_id), token)
    except BillingError as exc:
        return _review_html("Lien indisponible", f'<p style="color:#475569">{html.escape(str(exc))}</p>', status_code=exc.status_code)
    order, center = context["order"], context["center"]
    project = order.get("request_payload_json") or {}
    teacher = project.get("teacher_name") or "Professeur IA"
    days = training_days_for_order(order)
    deepseek_recharge_cents = days * 314
    fish_audio_recharge_cents = days * 625
    status = order.get("review_status") or "pending"
    deepseek_url = os.getenv("AI_TEXT_API_RECHARGE_URL", "https://platform.deepseek.com/top_up")
    fish_url = os.getenv("AI_AUDIO_API_RECHARGE_URL", "https://fish.audio/app/credits/")
    disabled = " disabled" if status != "pending" else ""
    status_label = {
        "pending": "En attente de décision",
        "approved": "Demande déjà approuvée",
        "rejected": "Demande refusée",
    }.get(status, status)
    body = f"""
<p style="margin:12px 0 0;color:#475569">{html.escape(status_label)}</p>
<table style="width:100%;margin-top:22px;border-collapse:collapse;font-size:14px">
<tr><td style="padding:9px 0;color:#64748b">Centre</td><td style="text-align:right;font-weight:600">{html.escape(str(center.get('center_name') or center.get('username') or ''))}</td></tr>
<tr><td style="padding:9px 0;color:#64748b">Professeur</td><td style="text-align:right;font-weight:600">{html.escape(str(teacher))}</td></tr>
<tr><td style="padding:9px 0;color:#64748b">Formation</td><td style="text-align:right;font-weight:600">{html.escape(str(order.get('training_title') or ''))}</td></tr>
<tr><td style="padding:9px 0;color:#64748b">Journées</td><td style="text-align:right;font-weight:600">{days}</td></tr>
<tr><td style="padding:9px 0;color:#64748b">Prix client</td><td style="text-align:right;font-weight:700">{int(order.get('catalog_amount_cents') or 0) / 100:.2f} €</td></tr>
<tr><td style="padding:9px 0;color:#64748b">Coût API DeepSeek à recharger</td><td style="text-align:right;font-weight:700">{deepseek_recharge_cents / 100:.2f} €</td></tr>
<tr><td style="padding:9px 0;color:#64748b">Coût API Fish Audio à recharger</td><td style="text-align:right;font-weight:700">{fish_audio_recharge_cents / 100:.2f} €</td></tr>
</table>
<div style="display:flex;flex-wrap:wrap;gap:10px;margin-top:24px">
<a href="{html.escape(deepseek_url, quote=True)}" target="_blank" rel="noreferrer" style="padding:11px 14px;border:1px solid #cbd5e1;border-radius:8px;color:#334155;text-decoration:none;font-weight:600">Recharger DeepSeek</a>
<a href="{html.escape(fish_url, quote=True)}" target="_blank" rel="noreferrer" style="padding:11px 14px;border:1px solid #cbd5e1;border-radius:8px;color:#334155;text-decoration:none;font-weight:600">Recharger Fish Audio</a>
</div>
<form method="post" action="/billing/review/{public_id}/approve" style="margin-top:28px">
<input type="hidden" name="token" value="{html.escape(token, quote=True)}">
<button type="submit"{disabled} style="width:100%;padding:14px;border:0;border-radius:8px;background:#7c3aed;color:#fff;font-size:15px;font-weight:700;cursor:pointer">Confirmer le professeur IA et envoyer le paiement</button>
</form>
<form method="post" action="/billing/review/{public_id}/reject" style="margin-top:10px">
<input type="hidden" name="token" value="{html.escape(token, quote=True)}">
<button type="submit"{disabled} style="width:100%;padding:12px;border:1px solid #fecaca;border-radius:8px;background:#fff;color:#b42318;font-size:14px;font-weight:600;cursor:pointer">Refuser la demande</button>
</form>"""
    return _review_html("Étudier la demande", body)


@billing_bp.post("/billing/review/<uuid:public_id>/approve")
def approve_teacher_order_page(public_id):
    try:
        result = approve_teacher_order_review(str(public_id), request.form.get("token", ""))
        checkout_url = html.escape(str(result.get("checkout_url") or ""), quote=True)
        if result.get("payment_email_sent"):
            message = (
                "Le lien Stripe a été créé et envoyé au centre. "
                f'<a href="{checkout_url}">Ouvrir le paywall</a>.'
            )
        else:
            message = (
                "Le lien Stripe a été créé, mais l’e-mail n’a pas pu être envoyé. "
                f'<a href="{checkout_url}">Ouvrez le paywall</a> pour transmettre '
                "le lien manuellement."
            )
        return _review_html(
            "Demande approuvée",
            f'<p style="margin-top:14px;color:#475569;line-height:1.6">{message}</p>',
        )
    except BillingError as exc:
        return _review_html("Validation impossible", f'<p style="color:#b42318">{html.escape(str(exc))}</p>', status_code=exc.status_code)


@billing_bp.post("/billing/review/<uuid:public_id>/reject")
def reject_teacher_order_page(public_id):
    try:
        reject_teacher_order_review(str(public_id), request.form.get("token", ""))
        return _review_html("Demande refusée", '<p style="margin-top:14px;color:#475569">Aucun paiement ne sera demandé au centre.</p>')
    except BillingError as exc:
        return _review_html("Refus impossible", f'<p style="color:#b42318">{html.escape(str(exc))}</p>', status_code=exc.status_code)


@billing_bp.get("/api/admin/teacher-order-validations")
def get_admin_teacher_order_validations():
    authorized, reviewing_center_id = _review_admin_context()
    if not authorized:
        return jsonify({"success": False, "error": "Compte administrateur requis"}), 403
    if not postgres_enabled():
        return jsonify({"success": False, "error": "PostgreSQL requis"}), 503
    try:
        inbox = (
            admin_review_inbox()
            if reviewing_center_id is None
            else admin_review_inbox(exclude_center_account_id=reviewing_center_id)
        )
        return jsonify({"success": True, **inbox}), 200
    except BillingError as exc:
        return _error(exc)
    except Exception:
        logger.exception("AI_TEACHER_ADMIN_INBOX_FAILED")
        return jsonify({"success": False, "error": "Impossible de charger les demandes."}), 500


@billing_bp.post("/api/admin/teacher-order-validations/<uuid:public_id>/seen")
def see_admin_teacher_order_validation(public_id):
    authorized, reviewing_center_id = _review_admin_context()
    if not authorized:
        return jsonify({"success": False, "error": "Compte administrateur requis"}), 403
    if not _delegated_review_target_allowed(public_id, reviewing_center_id):
        return jsonify({"success": False, "error": "Demande introuvable"}), 404
    try:
        return jsonify({"success": True, "order": mark_admin_review_seen(str(public_id))}), 200
    except BillingError as exc:
        return _error(exc)


@billing_bp.post("/api/admin/teacher-order-validations/<uuid:public_id>/approve")
def approve_admin_teacher_order_validation(public_id):
    authorized, reviewing_center_id = _review_admin_context()
    if not authorized:
        return jsonify({"success": False, "error": "Compte administrateur requis"}), 403
    if not _delegated_review_target_allowed(public_id, reviewing_center_id):
        return jsonify({"success": False, "error": "Demande introuvable"}), 404
    if not postgres_enabled():
        return jsonify({"success": False, "error": "PostgreSQL requis"}), 503
    try:
        result = approve_teacher_order_from_admin(
            str(public_id),
            os.getenv("BILLING_REVIEW_NOTIFICATION_EMAIL", "secretariat@saleshacking.fr"),
        )
        return jsonify({
            "success": True,
            "order": serialize_order(result["order"], include_project=True),
            "payment_email_sent": result["payment_email_sent"],
        }), 200
    except BillingError as exc:
        return _error(exc)
    except Exception:
        logger.exception("AI_TEACHER_ADMIN_APPROVAL_FAILED order_id=%s", public_id)
        return jsonify({"success": False, "error": "Impossible d’accepter la demande."}), 500


@billing_bp.post("/api/admin/teacher-order-validations/<uuid:public_id>/reject")
def reject_admin_teacher_order_validation(public_id):
    authorized, reviewing_center_id = _review_admin_context()
    if not authorized:
        return jsonify({"success": False, "error": "Compte administrateur requis"}), 403
    if not _delegated_review_target_allowed(public_id, reviewing_center_id):
        return jsonify({"success": False, "error": "Demande introuvable"}), 404
    if not postgres_enabled():
        return jsonify({"success": False, "error": "PostgreSQL requis"}), 503
    note = str((request.get_json(silent=True) or {}).get("note") or "").strip()
    try:
        order = reject_teacher_order_from_admin(
            str(public_id),
            os.getenv("BILLING_REVIEW_NOTIFICATION_EMAIL", "secretariat@saleshacking.fr"),
            note,
        )
        return jsonify({"success": True, "order": serialize_order(order, include_project=True)}), 200
    except BillingError as exc:
        return _error(exc)
    except Exception:
        logger.exception("AI_TEACHER_ADMIN_REJECTION_FAILED order_id=%s", public_id)
        return jsonify({"success": False, "error": "Impossible de refuser la demande."}), 500


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


@billing_bp.get("/api/hr/messages")
def get_center_messages():
    center_id = _center_id()
    if not center_id:
        return jsonify({"success": False, "error": "Compte centre requis"}), 403
    if not postgres_enabled():
        return jsonify({"success": False, "error": "PostgreSQL requis"}), 503
    try:
        return jsonify({"success": True, **center_message_inbox(center_id)}), 200
    except BillingError as exc:
        return _error(exc)
    except Exception:
        logger.exception("CENTER_MESSAGE_INBOX_FAILED center_id=%s", center_id)
        return jsonify({"success": False, "error": "Impossible de charger la messagerie."}), 500


@billing_bp.post("/api/hr/messages/<uuid:public_id>/seen")
def see_center_message(public_id):
    center_id = _center_id()
    if not center_id:
        return jsonify({"success": False, "error": "Compte centre requis"}), 403
    try:
        return jsonify({
            "success": True,
            "message": mark_center_message_seen(str(public_id), center_id),
        }), 200
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


@billing_bp.post("/api/hr/billing/orders/<uuid:public_id>/checkout")
def post_billing_checkout(public_id):
    center_id = _center_id()
    if not center_id:
        return jsonify({"success": False, "error": "Compte centre requis"}), 403
    try:
        return jsonify({
            "success": True,
            **get_center_checkout_link(str(public_id), center_id),
        }), 200
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


@billing_bp.post("/api/hr/teacher-orders/<uuid:public_id>/confirm-payment")
def confirm_teacher_order_payment(public_id):
    center_id = _center_id()
    if not center_id:
        return jsonify({"success": False, "error": "Compte centre requis"}), 403
    if not postgres_enabled():
        return jsonify({"success": False, "error": "PostgreSQL requis"}), 503
    payload = request.get_json(silent=True) or {}
    try:
        order = reconcile_center_checkout_payment(
            str(public_id),
            center_id,
            returned_session_id=payload.get("session_id"),
        )
        return jsonify({
            "success": True,
            "order": serialize_order(order, include_project=True),
        }), 200
    except BillingError as exc:
        return _error(exc)
    except Exception:
        logger.exception(
            "AI_TEACHER_CHECKOUT_RECONCILIATION_FAILED order=%s center_id=%s",
            public_id,
            center_id,
        )
        return jsonify({
            "success": False,
            "error": "Impossible de confirmer le paiement pour le moment.",
        }), 500


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
