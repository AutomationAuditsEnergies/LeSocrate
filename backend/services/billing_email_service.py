"""Transactional email delivery for the AI-teacher approval and payment flow."""

from __future__ import annotations

import html
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from typing import Any

from utils.logger import get_logger


logger = get_logger(__name__)
DEFAULT_REVIEW_RECIPIENT = "secretariat@saleshacking.fr"


def _format_eur(cents: int | None) -> str:
    return f"{int(cents or 0) / 100:,.2f} €".replace(",", " ").replace(".", ",")


def _training_days(order: dict[str, Any]) -> int:
    project = order.get("request_payload_json") or {}
    schedule = (
        (project.get("new_formation") or {}).get("schedule")
        or project.get("schedule")
        or {}
    )
    return max(
        1,
        int(
            schedule.get("day_count")
            or schedule.get("total_training_days")
            or len(schedule.get("selected_dates") or [])
            or ((int(order.get("total_hours") or 7) + 6) // 7)
        ),
    )


def _send_html(recipient: str, subject: str, content: str) -> bool:
    username = os.getenv("EMAIL_USERNAME", "").strip()
    password = os.getenv("EMAIL_PASSWORD", "").strip()
    recipient = str(recipient or "").strip()
    if not username or not password or "@" not in recipient:
        logger.error("BILLING_EMAIL_NOT_CONFIGURED recipient=%s", recipient)
        return False

    sender = os.getenv("EMAIL_FROM", "").strip() or username
    sender_name = os.getenv("EMAIL_FROM_NAME", "Le Socrate").strip() or "Le Socrate"
    message = MIMEMultipart("alternative")
    message["Message-ID"] = make_msgid()
    message["Subject"] = subject
    message["From"] = f"{sender_name} <{sender}>"
    message["To"] = recipient
    message.attach(MIMEText(content, "html", "utf-8"))

    try:
        smtp = smtplib.SMTP_SSL(
            os.getenv("SMTP_SERVER", "mail.infomaniak.com"),
            int(os.getenv("SMTP_PORT", "465")),
            timeout=20,
        )
        try:
            smtp.login(username, password)
            smtp.sendmail(sender, recipient, message.as_string())
        finally:
            smtp.quit()
        return True
    except Exception:
        logger.exception("BILLING_EMAIL_SEND_FAILED recipient=%s", recipient)
        return False


def _shell(title: str, lead: str, body: str, *, button_label: str, button_url: str) -> str:
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;background:#f8fafc;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#0f172a">
  <div style="max-width:640px;margin:0 auto;padding:32px 18px">
    <div style="font-size:13px;font-weight:700;letter-spacing:.08em;color:#7c3aed">LE SOCRATE</div>
    <div style="margin-top:14px;background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:30px">
      <h1 style="margin:0;font-size:24px;line-height:1.25">{html.escape(title)}</h1>
      <p style="margin:14px 0 0;color:#475569;font-size:15px;line-height:1.6">{html.escape(lead)}</p>
      {body}
      <p style="margin:26px 0 0"><a href="{html.escape(button_url, quote=True)}" style="display:inline-block;background:#7c3aed;color:#fff;text-decoration:none;padding:13px 18px;border-radius:8px;font-weight:700">{html.escape(button_label)}</a></p>
    </div>
    <p style="margin:16px 0 0;text-align:center;color:#64748b;font-size:12px">Message automatique de la plateforme Le Socrate.</p>
  </div>
</body></html>"""


def send_review_request(order: dict[str, Any], center: dict[str, Any], review_url: str) -> bool:
    project = order.get("request_payload_json") or {}
    teacher = str(project.get("teacher_name") or "Professeur IA")
    days = _training_days(order)
    deepseek_recharge_cents = days * 314
    fish_audio_recharge_cents = days * 625
    body = f"""
      <table role="presentation" style="width:100%;margin-top:22px;border-collapse:collapse;font-size:14px">
        <tr><td style="padding:9px 0;color:#64748b">Centre</td><td style="padding:9px 0;text-align:right;font-weight:600">{html.escape(str(center.get('center_name') or center.get('username') or ''))}</td></tr>
        <tr><td style="padding:9px 0;color:#64748b">Professeur</td><td style="padding:9px 0;text-align:right;font-weight:600">{html.escape(teacher)}</td></tr>
        <tr><td style="padding:9px 0;color:#64748b">Formation</td><td style="padding:9px 0;text-align:right;font-weight:600">{html.escape(str(order.get('training_title') or ''))}</td></tr>
        <tr><td style="padding:9px 0;color:#64748b">Journées</td><td style="padding:9px 0;text-align:right;font-weight:600">{days}</td></tr>
        <tr><td style="padding:9px 0;color:#64748b">Prix client</td><td style="padding:9px 0;text-align:right;font-weight:700">{_format_eur(order.get('catalog_amount_cents'))}</td></tr>
        <tr><td style="padding:9px 0;color:#64748b">Coût API DeepSeek à recharger</td><td style="padding:9px 0;text-align:right;font-weight:700">{_format_eur(deepseek_recharge_cents)}</td></tr>
        <tr><td style="padding:9px 0;color:#64748b">Coût API Fish Audio à recharger</td><td style="padding:9px 0;text-align:right;font-weight:700">{_format_eur(fish_audio_recharge_cents)}</td></tr>
      </table>"""
    recipient = os.getenv("BILLING_REVIEW_NOTIFICATION_EMAIL", DEFAULT_REVIEW_RECIPIENT)
    return _send_html(
        recipient,
        f"Demande professeur IA · {order.get('training_title')}",
        _shell(
            "Nouvelle demande à étudier",
            "Rechargez les crédits API nécessaires, vérifiez la demande puis autorisez le paiement.",
            body,
            button_label="Étudier la demande",
            button_url=review_url,
        ),
    )


def send_payment_link(order: dict[str, Any], center: dict[str, Any], checkout_url: str) -> bool:
    days = _training_days(order)
    body = f"""
      <div style="margin-top:22px;padding:16px;background:#f1f5f9;border-radius:10px;font-size:14px;line-height:1.6">
        <strong>{html.escape(str(order.get('training_title') or 'Professeur IA'))}</strong><br>
        {days} journée{'s' if days > 1 else ''} · {_format_eur(order.get('catalog_amount_cents'))}
      </div>"""
    return _send_html(
        str(center.get("username") or ""),
        "Votre demande de professeur IA est acceptée",
        _shell(
            "Votre professeur IA est confirmé",
            "Votre demande a été étudiée et acceptée. Finalisez maintenant le paiement sécurisé avec Stripe.",
            body,
            button_label="Payer avec Stripe",
            button_url=checkout_url,
        ),
    )
