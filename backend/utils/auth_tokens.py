"""Stateless signed API tokens shared safely across App Service instances."""

from __future__ import annotations

import os
import hashlib
import hmac
from datetime import datetime
from typing import Any, Mapping

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config import SECRET_KEY


def _serializer(kind: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(SECRET_KEY, salt=f"le-socrate:{kind}:v1")


def issue_auth_token(kind: str, payload: Mapping[str, Any]) -> str:
    if not kind:
        raise ValueError("kind est requis")
    return _serializer(kind).dumps({"kind": kind, **dict(payload)})


def verify_auth_token(kind: str, token: str) -> dict[str, Any] | None:
    if not kind or not token:
        return None
    max_age_env = (
        "COURSE_INVITATION_TOKEN_MAX_AGE_SECONDS"
        if kind == "course_invitation"
        else "AUTH_TOKEN_MAX_AGE_SECONDS"
    )
    # Rules may notify up to J-365. Keep the serializer timestamp valid a bit
    # longer than the explicit business expiration embedded in the token.
    max_age_default = "32000000" if kind == "course_invitation" else "43200"
    try:
        max_age = max(60, int(os.getenv(max_age_env, max_age_default)))
    except (TypeError, ValueError):
        max_age = int(max_age_default)
    try:
        payload = _serializer(kind).loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict) or payload.get("kind") != kind:
        return None
    payload.pop("kind", None)
    return payload


def course_invitation_recipient_hash(email: str) -> str:
    """Return a stable, non-reversible recipient identifier for invite tokens.

    The e-mail address is deliberately absent from both the signed URL and the
    delivery queue.  A keyed digest still makes two recipients distinct while
    preventing an attacker from testing a small list of known addresses.
    """
    normalized = str(email or "").strip().lower().encode("utf-8")
    return hmac.new(
        str(SECRET_KEY).encode("utf-8"),
        b"course-invitation-recipient:v1:" + normalized,
        hashlib.sha256,
    ).hexdigest()


def issue_course_invitation_token(
    *,
    platform_id: int,
    session_id: int,
    scheduled_at: datetime,
    recipient_email: str,
    expires_at: datetime,
) -> str:
    """Issue a link credential bound to one recipient and one occurrence."""
    if scheduled_at.tzinfo is None or expires_at.tzinfo is None:
        raise ValueError("Les dates d'invitation doivent inclure leur fuseau horaire")
    return issue_auth_token(
        "course_invitation",
        {
            "platform_id": int(platform_id),
            "session_id": int(session_id),
            "scheduled_at": int(scheduled_at.timestamp()),
            "recipient": course_invitation_recipient_hash(recipient_email),
            "exp": int(expires_at.timestamp()),
        },
    )


def verify_course_invitation_token(token: str) -> dict[str, Any] | None:
    payload = verify_auth_token("course_invitation", token)
    if not payload:
        return None
    required = {"platform_id", "session_id", "scheduled_at", "recipient", "exp"}
    if not required.issubset(payload):
        return None
    try:
        normalized = {
            **payload,
            "platform_id": int(payload["platform_id"]),
            "session_id": int(payload["session_id"]),
            "scheduled_at": int(payload["scheduled_at"]),
            "exp": int(payload["exp"]),
        }
    except (TypeError, ValueError):
        return None
    recipient = str(normalized.get("recipient") or "")
    if len(recipient) != 64:
        return None
    return normalized
