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
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import requests as _http

from utils.logger import get_logger

logger = get_logger(__name__)

ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"
_LLM_SEMAPHORES = {}
_LLM_SEMAPHORES_LOCK = threading.Lock()


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


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _deepseek_concurrency_limit(model: str) -> int:
    model_lower = (model or "").lower()
    generic = os.getenv("DEEPSEEK_MAX_CONCURRENT")
    if "v4-pro" in model_lower:
        default = _int_env("DEEPSEEK_MAX_CONCURRENT", 450)
        return max(1, min(500, _int_env("DEEPSEEK_V4_PRO_MAX_CONCURRENT", default)))
    if "v4-flash" in model_lower:
        default = _int_env("DEEPSEEK_MAX_CONCURRENT", 2200)
        return max(1, min(2500, _int_env("DEEPSEEK_V4_FLASH_MAX_CONCURRENT", default)))
    if generic:
        return max(1, _int_env("DEEPSEEK_MAX_CONCURRENT", 450))
    return 450


def _provider_concurrency_limit(provider: str, model: str) -> int:
    if provider == "DeepSeek":
        return _deepseek_concurrency_limit(model)
    return max(0, _int_env("ANTHROPIC_MAX_CONCURRENT", 0))


def _new_semaphore(limit: int):
    try:
        from eventlet.semaphore import Semaphore
        return Semaphore(limit)
    except Exception:
        return threading.BoundedSemaphore(limit)


def _get_llm_semaphore(provider: str, model: str, limit: int):
    key = (provider, model, limit)
    with _LLM_SEMAPHORES_LOCK:
        sem = _LLM_SEMAPHORES.get(key)
        if sem is None:
            sem = _new_semaphore(limit)
            _LLM_SEMAPHORES[key] = sem
        return sem


@contextmanager
def _llm_concurrency_slot(provider: str, model: str):
    limit = _provider_concurrency_limit(provider, model)
    if limit <= 0:
        yield
        return
    sem = _get_llm_semaphore(provider, model, limit)
    sem.acquire()
    try:
        yield
    finally:
        sem.release()


def _deepseek_user_id() -> str:
    raw = (
        os.getenv("DEEPSEEK_USER_ID")
        or os.getenv("FORMATION_LLM_USER_ID")
        or os.getenv("LLM_USER_ID")
        or ""
    ).strip()
    if not raw:
        return ""
    safe = "".join(ch for ch in raw if ch.isalnum() or ch in "-_")
    return safe[:512]


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
        return self.status_code in (400, 401, 402, 403, 404, 422)


def _sleep(seconds: float) -> None:
    try:
        import eventlet
        eventlet.sleep(seconds)
    except Exception:
        time.sleep(seconds)


def _transient_http_wait(attempt: int) -> float:
    base = max(0.25, float(os.getenv("LLM_HTTP_RETRY_BASE_WAIT_SEC", "2")))
    cap = max(base, float(os.getenv("LLM_HTTP_RETRY_MAX_WAIT_SEC", "20")))
    return min(cap, base * (2 ** max(0, attempt - 1)))


def _llm_http_max_attempts() -> int:
    return max(1, min(6, _int_env("LLM_HTTP_MAX_ATTEMPTS", 3)))


def _is_retryable_http_status(status_code: int) -> bool:
    return status_code in (408, 409, 425, 500, 502, 503, 504, 520, 522, 524)


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


def _is_local_dev() -> bool:
    return os.getenv("LOCAL_DEV", "").lower() == "true"


def _messages_to_prompt(messages: list) -> str:
    """Convertit le format messages Anthropic en prompt texte pour claude -p."""
    parts = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        if role == "system":
            parts.insert(0, content)
        else:
            parts.append(content)
    return "\n\n".join(p for p in parts if p)


def _call_via_claude_cli(messages: list, model: str, timeout: int = 600) -> str:
    """Route l'appel vers le binaire `claude` (forfait OAuth) au lieu de l'API HTTP.

    Strips ANTHROPIC_API_KEY du child_env pour forcer l'auth OAuth du forfait.
    """
    prompt = _messages_to_prompt(messages)
    child_env = os.environ.copy()
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        child_env.pop(k, None)

    cmd = ["claude", "-p", prompt, "--model", model, "--dangerously-skip-permissions"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=child_env
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "")[:400]
            raise AnthropicAPIError(500, "cli_error", err)
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise AnthropicAPIError(500, "timeout", f"Claude CLI timeout après {timeout}s")
    except FileNotFoundError:
        raise AnthropicAPIError(500, "cli_not_found", "Binaire `claude` introuvable dans le PATH")


def post_message(messages, max_tokens=8000, model=None, timeout=600, temperature=None) -> str:
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

    # LOCAL_DEV=true → forfait Claude Code (OAuth) — uniquement pour les modèles Claude
    if _is_local_dev() and shutil.which("claude") and not model.lower().startswith("deepseek"):
        logger.info(f"🖥️  LOCAL_DEV: routing via claude CLI (model={model})")
        return _call_via_claude_cli(messages, model, timeout)

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
    if temperature is not None:
        payload["temperature"] = temperature
    if config["provider"] == "DeepSeek":
        user_id = _deepseek_user_id()
        if user_id:
            payload["metadata"] = {"user_id": user_id}
        thinking = os.environ.get("DEEPSEEK_THINKING", "disabled").strip().lower()
        if thinking in ("enabled", "disabled"):
            payload["thinking"] = {"type": thinking}
        effort = os.environ.get("DEEPSEEK_REASONING_EFFORT", "").strip().lower()
        if thinking == "enabled" and effort in ("high", "max"):
            payload["output_config"] = {"effort": effort}

    max_attempts = _llm_http_max_attempts()
    transient_errors = (
        _http.exceptions.ChunkedEncodingError,
        _http.exceptions.ConnectionError,
        _http.exceptions.Timeout,
    )
    for attempt in range(1, max_attempts + 1):
        try:
            with _llm_concurrency_slot(config["provider"], model):
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
                api_error = AnthropicAPIError(resp.status_code, err_type, err_msg)
                if (
                    api_error.is_deterministic
                    or not _is_retryable_http_status(resp.status_code)
                    or attempt >= max_attempts
                ):
                    raise api_error
                wait = _transient_http_wait(attempt)
                logger.warning(
                    f"⚠️ {config['provider']} API {resp.status_code} transitoire "
                    f"({model}, tentative {attempt}/{max_attempts}) — retry dans {wait:.1f}s"
                )
                _sleep(wait)
                continue

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
        except transient_errors as exc:
            if attempt >= max_attempts:
                raise
            wait = _transient_http_wait(attempt)
            logger.warning(
                f"⚠️ {config['provider']} réseau interrompu ({model}, tentative {attempt}/{max_attempts}) — "
                f"{type(exc).__name__}: {str(exc)[:200]} — retry dans {wait:.1f}s"
            )
            _sleep(wait)

    raise AnthropicAPIError(500, "retry_exhausted", f"{config['provider']} retry épuisé")
