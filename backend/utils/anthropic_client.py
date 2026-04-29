"""
Client HTTP mutualisé pour les LLM compatibles Anthropic (/v1/messages).

Fournit :
  - `AnthropicRateLimitError` : exception typée sur 429 portant `wait_seconds`
  - `parse_retry_after(resp)` : extrait le délai conseillé par le provider
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

ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"


def default_model() -> str:
    """
    Modèle par défaut pour la pipeline formation.

    Priorité :
      1. FORMATION_LLM_MODEL (nouveau nom générique)
      2. FORMATION_CLAUDE_MODEL (compatibilité existante)
      3. deepseek-v4-flash si DEEPSEEK_API_KEY est configurée sans clé Anthropic
      4. Claude Sonnet historique
    """
    configured = os.environ.get("FORMATION_LLM_MODEL") or os.environ.get("FORMATION_CLAUDE_MODEL")
    if configured:
        return configured
    provider = (
        os.environ.get("FORMATION_LLM_PROVIDER")
        or os.environ.get("LLM_PROVIDER")
        or ""
    ).strip().lower()
    if provider == "deepseek":
        return DEEPSEEK_DEFAULT_MODEL
    if os.getenv("DEEPSEEK_API_KEY") and not os.getenv("ANTHROPIC_API_KEY"):
        return DEEPSEEK_DEFAULT_MODEL
    return ANTHROPIC_DEFAULT_MODEL


def _resolve_provider(model: str) -> str:
    provider = (
        os.environ.get("FORMATION_LLM_PROVIDER")
        or os.environ.get("LLM_PROVIDER")
        or ""
    ).strip().lower()
    if provider in ("deepseek", "anthropic"):
        return provider
    if (model or "").lower().startswith("deepseek"):
        return "deepseek"
    if os.getenv("DEEPSEEK_API_KEY") and not os.getenv("ANTHROPIC_API_KEY"):
        return "deepseek"
    return "anthropic"


def _normalize_model_alias(model: str) -> str:
    alias = (model or "").strip().lower()
    if alias == "flash":
        return "deepseek-v4-flash"
    if alias == "pro":
        return "deepseek-v4-pro"
    if alias == "haiku":
        return "claude-haiku-4-5-20251001"
    if alias == "sonnet":
        resolved = default_model()
        return resolved if resolved.lower() != "sonnet" else ANTHROPIC_DEFAULT_MODEL
    return model


def _provider_config(model: str) -> dict:
    provider = _resolve_provider(model)
    if provider == "deepseek":
        base_url = os.environ.get("DEEPSEEK_ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
        return {
            "provider": "DeepSeek",
            "url": f"{base_url.rstrip('/')}/v1/messages",
            "api_key": os.getenv("DEEPSEEK_API_KEY") or os.getenv("ANTHROPIC_API_KEY"),
            "missing_key": "DEEPSEEK_API_KEY",
        }

    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    return {
        "provider": "Anthropic",
        "url": f"{base_url.rstrip('/')}/v1/messages",
        "api_key": os.getenv("ANTHROPIC_API_KEY"),
        "missing_key": "ANTHROPIC_API_KEY",
    }


class AnthropicRateLimitError(Exception):
    """429 d'Anthropic — porte le nombre de secondes à attendre avant retry."""

    def __init__(self, wait_seconds: float, message: str = ""):
        super().__init__(message or f"Rate limit Anthropic, attendre {wait_seconds:.0f}s")
        self.wait_seconds = wait_seconds


class AnthropicAPIError(Exception):
    """Erreur HTTP non-429 d'Anthropic — porte le statut + message déterministe.

    Utile pour distinguer les erreurs *retryables* (network, timeout, 5xx) des
    erreurs *déterministes* (400 invalid_request_error, 401 auth, 403 perms).
    Sur déterministe, retry est inutile — fail fast et propage le vrai message.
    """

    def __init__(self, status_code: int, error_type: str = "", message: str = ""):
        full = f"{error_type}: {message}" if error_type else message
        super().__init__(full or f"Anthropic API {status_code}")
        self.status_code = status_code
        self.error_type = error_type
        self.message = message

    @property
    def is_deterministic(self) -> bool:
        """True si retry n'aidera pas (mauvaise requête, auth, crédits…)."""
        return self.status_code in (400, 401, 403, 404, 422)


def parse_retry_after(resp) -> float:
    """
    Extrait le délai d'attente conseillé par le provider sur un 429.
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
    - Lève `AnthropicAPIError` sur les autres erreurs HTTP.
    """
    if not model:
        raise ValueError("post_message: 'model' est requis")

    model = _normalize_model_alias(model)
    config = _provider_config(model)
    if not config["api_key"]:
        raise ValueError(f"{config['missing_key']} non définie pour {config['provider']}")

    # Cap par modèle : Haiku 4.5 max 8192 tokens output, Sonnet 4 beaucoup plus.
    if "haiku" in model.lower():
        max_tokens = min(max_tokens, 8000)

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if config["provider"] == "DeepSeek":
        thinking = os.environ.get("DEEPSEEK_THINKING", "disabled").strip().lower()
        if thinking in ("enabled", "disabled"):
            payload["thinking"] = {"type": thinking}
        effort = os.environ.get("DEEPSEEK_REASONING_EFFORT", "").strip().lower()
        if thinking == "enabled" and effort in ("high", "max"):
            payload["output_config"] = {"effort": effort}

    resp = _http.post(
        config["url"],
        headers={
            "x-api-key": config["api_key"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )

    if resp.status_code == 429:
        wait = parse_retry_after(resp)
        try:
            error_body = resp.json()
        except Exception:
            error_body = resp.text[:500]
        logger.warning(
            f"⏳ {config['provider']} 429 ({model}, max_tokens={max_tokens}) — "
            f"retry conseillé dans {wait:.0f}s : {error_body}"
        )
        raise AnthropicRateLimitError(wait)

    if not resp.ok:
        try:
            error_body = resp.json()
        except Exception:
            error_body = resp.text[:500]
        logger.error(
            f"❌ {config['provider']} API {resp.status_code} ({model}, max_tokens={max_tokens}) : {error_body}"
        )
        # Extrait un message lisible depuis le JSON Anthropic standard :
        #   {"type": "error", "error": {"type": "...", "message": "..."}}
        err_type = ""
        err_msg = ""
        if isinstance(error_body, dict):
            err = error_body.get("error", {})
            if isinstance(err, dict):
                err_type = err.get("type", "") or ""
                err_msg = err.get("message", "") or ""
        if not err_msg:
            err_msg = str(error_body)[:300]
        raise AnthropicAPIError(resp.status_code, err_type, err_msg)

    data = resp.json()
    content = data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
            if isinstance(block, dict) and "text" in block:
                return block.get("text", "")
    raise AnthropicAPIError(200, "invalid_response", f"Réponse {config['provider']} sans bloc texte")
