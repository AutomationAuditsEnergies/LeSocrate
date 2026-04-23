"""
Client HTTP mutualisé pour l'API Anthropic (/v1/messages).

Fournit :
  - `AnthropicRateLimitError` : exception typée sur 429 portant `wait_seconds`
  - `parse_retry_after(resp)` : extrait le délai conseillé par Anthropic
  - `post_message(...)` : wrapper requests avec gestion 429 + logs unifiés

Utilisé par `knowledge_base_service` et `formation_pipeline_service` pour que
les deux couches partagent exactement le même comportement anti-rate-limit.
Un service qui attrape `AnthropicRateLimitError` doit dormir `e.wait_seconds`
avant de retenter (plutôt qu'un sleep aveugle qui cascade en 429).
"""

import os
from datetime import datetime, timezone

import requests as _http

from utils.logger import get_logger

logger = get_logger(__name__)


class AnthropicRateLimitError(Exception):
    """429 d'Anthropic — porte le nombre de secondes à attendre avant retry."""

    def __init__(self, wait_seconds: float, message: str = ""):
        super().__init__(message or f"Rate limit Anthropic, attendre {wait_seconds:.0f}s")
        self.wait_seconds = wait_seconds


def parse_retry_after(resp) -> float:
    """
    Extrait le délai d'attente conseillé par Anthropic sur un 429.
    Priorité : header HTTP `retry-after` (secondes) > reset ISO 8601 des
    buckets output/input tokens > fallback 60s (taille d'une fenêtre).
    """
    retry_after = resp.headers.get("retry-after")
    if retry_after:
        try:
            return max(1.0, float(retry_after))
        except ValueError:
            pass

    # Anthropic expose plusieurs buckets ; on prend le reset le plus tardif
    # parmi ceux qui sont épuisés (remaining=0).
    candidates = []
    for bucket in ("output-tokens", "input-tokens", "tokens", "requests"):
        remaining = resp.headers.get(f"anthropic-ratelimit-{bucket}-remaining")
        reset_iso = resp.headers.get(f"anthropic-ratelimit-{bucket}-reset")
        if reset_iso and remaining is not None and remaining.strip() in ("0", "0.0"):
            try:
                reset_dt = datetime.fromisoformat(reset_iso.replace("Z", "+00:00"))
                delta = (reset_dt - datetime.now(timezone.utc)).total_seconds()
                if delta > 0:
                    candidates.append(delta)
            except ValueError:
                pass
    if candidates:
        return max(candidates) + 1.0  # petit buffer

    return 60.0


def post_message(messages, max_tokens=8000, model=None, timeout=600) -> str:
    """
    Appelle POST /v1/messages et retourne le texte du premier bloc de la réponse.

    - Cap automatique de `max_tokens` à 8000 pour Haiku (limite modèle).
    - Lève `AnthropicRateLimitError(wait_seconds)` sur 429, avec délai parsé
      depuis les headers.
    - `resp.raise_for_status()` sur les autres erreurs HTTP.
    """
    if not model:
        raise ValueError("post_message: 'model' est requis")

    # Cap par modèle : Haiku 4.5 max 8192 tokens output, Sonnet 4 beaucoup plus.
    if "haiku" in model.lower():
        max_tokens = min(max_tokens, 8000)

    resp = _http.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": os.getenv("ANTHROPIC_API_KEY"),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        },
        timeout=timeout,
    )

    if resp.status_code == 429:
        wait = parse_retry_after(resp)
        try:
            error_body = resp.json()
        except Exception:
            error_body = resp.text[:500]
        logger.warning(
            f"⏳ Anthropic 429 ({model}, max_tokens={max_tokens}) — "
            f"retry conseillé dans {wait:.0f}s : {error_body}"
        )
        raise AnthropicRateLimitError(wait)

    if not resp.ok:
        try:
            error_body = resp.json()
        except Exception:
            error_body = resp.text[:500]
        logger.error(
            f"❌ Anthropic API {resp.status_code} ({model}, max_tokens={max_tokens}) : {error_body}"
        )
        resp.raise_for_status()

    return resp.json()["content"][0]["text"]
