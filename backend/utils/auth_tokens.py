"""Stateless signed API tokens shared safely across App Service instances."""

from __future__ import annotations

import os
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
    try:
        max_age = max(60, int(os.getenv("AUTH_TOKEN_MAX_AGE_SECONDS", "43200")))
    except (TypeError, ValueError):
        max_age = 43200
    try:
        payload = _serializer(kind).loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict) or payload.get("kind") != kind:
        return None
    payload.pop("kind", None)
    return payload
