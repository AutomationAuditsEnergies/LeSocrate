"""Validation locale des jetons d'accès émis par Supabase Auth."""

from __future__ import annotations

import time
from typing import Any

import jwt
import requests
from jwt import InvalidTokenError, PyJWKClient

from config import (
    SUPABASE_ANON_KEY,
    SUPABASE_PUBLISHABLE_KEY,
    SUPABASE_URL,
)
from utils.logger import get_logger


logger = get_logger(__name__)
_ASYMMETRIC_ALGORITHMS = {"ES256", "RS256"}
_issuer = f"{SUPABASE_URL}/auth/v1" if SUPABASE_URL else ""
_jwks_client = (
    PyJWKClient(
        f"{_issuer}/.well-known/jwks.json",
        cache_keys=True,
        cache_jwk_set=True,
        lifespan=300,
    )
    if _issuer
    else None
)


def extract_bearer_token(authorization_header: str | None) -> str | None:
    value = str(authorization_header or "").strip()
    if not value:
        return None
    scheme, separator, token = value.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _claims_are_for_authenticated_user(claims: dict[str, Any]) -> bool:
    audience = claims.get("aud")
    valid_audience = audience == "authenticated" or (
        isinstance(audience, list) and "authenticated" in audience
    )
    try:
        expires_at = int(claims.get("exp") or 0)
    except (TypeError, ValueError):
        return False
    return bool(
        valid_audience
        and claims.get("iss") == _issuer
        and claims.get("role") == "authenticated"
        and claims.get("sub")
        and claims.get("session_id")
        and expires_at > int(time.time())
    )


def _verify_legacy_hs256_with_auth_server(token: str) -> dict[str, Any] | None:
    """Ask Auth to validate legacy HS256 tokens without sharing its secret."""
    api_key = SUPABASE_PUBLISHABLE_KEY or SUPABASE_ANON_KEY
    if not _issuer or not api_key:
        return None
    response = requests.get(
        f"{_issuer}/user",
        headers={
            "apikey": api_key,
            "Authorization": f"Bearer {token}",
        },
        timeout=8,
    )
    if response.status_code != 200:
        return None

    claims = jwt.decode(
        token,
        options={
            "verify_signature": False,
            "verify_aud": False,
            "verify_exp": False,
        },
        algorithms=["HS256"],
    )
    user = response.json()
    if str(user.get("id") or "") != str(claims.get("sub") or ""):
        return None
    return claims if _claims_are_for_authenticated_user(claims) else None


def verify_supabase_access_token(token: str | None) -> dict[str, Any] | None:
    """Verify signature and mandatory session claims for a Supabase user JWT."""
    if not token or not _issuer:
        return None
    try:
        header = jwt.get_unverified_header(token)
        algorithm = str(header.get("alg") or "")
        if algorithm == "HS256":
            return _verify_legacy_hs256_with_auth_server(token)
        if algorithm not in _ASYMMETRIC_ALGORITHMS or _jwks_client is None:
            return None

        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=[algorithm],
            audience="authenticated",
            issuer=_issuer,
            options={
                "require": [
                    "aud",
                    "exp",
                    "iat",
                    "iss",
                    "role",
                    "session_id",
                    "sub",
                ],
            },
        )
        return claims if _claims_are_for_authenticated_user(claims) else None
    except (InvalidTokenError, ValueError, TypeError):
        return None
    except requests.RequestException:
        logger.warning("SUPABASE_AUTH_VALIDATION_UNAVAILABLE")
        return None
    except Exception:
        logger.warning("SUPABASE_JWKS_VALIDATION_FAILED", exc_info=True)
        return None
