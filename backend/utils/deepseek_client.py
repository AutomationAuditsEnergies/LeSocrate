"""Client HTTP DeepSeek mutualisé via le protocole Anthropic-compatible.

Toutes les requêtes partent vers l'API DeepSeek avec ``DEEPSEEK_API_KEY``.
"""

import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import requests as _http

from utils.logger import get_logger

logger = get_logger(__name__)

DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"
_LLM_SEMAPHORES = {}
_LLM_SEMAPHORES_LOCK = threading.Lock()


def default_model() -> str:
    """Retourne le modèle DeepSeek configuré, ou V4 Flash par défaut."""
    configured = (os.environ.get("FORMATION_LLM_MODEL") or "").strip()
    return _normalize_model_alias(configured) if configured else DEEPSEEK_DEFAULT_MODEL


def _normalize_model_alias(model: str) -> str:
    alias = (model or "").strip().lower()
    if alias in ("flash", "haiku"):
        return "deepseek-v4-flash"
    if alias in ("pro", "sonnet"):
        return "deepseek-v4-pro"
    if alias.startswith("claude-haiku"):
        return "deepseek-v4-flash"
    if alias.startswith(("claude-sonnet", "claude-opus")):
        return "deepseek-v4-pro"
    normalized = (model or "").strip()
    if not normalized.lower().startswith("deepseek"):
        raise ValueError(
            f"Modèle non pris en charge: {model!r}. "
            "La formation utilise uniquement DeepSeek."
        )
    return normalized


def _provider_config(model: str) -> dict:
    del model  # Le fournisseur n'est plus déduit du modèle.
    base_url = (
        os.environ.get("DEEPSEEK_ANTHROPIC_BASE_URL")
        or "https://api.deepseek.com/anthropic"
    ).strip()
    return {
        "provider": "DeepSeek",
        "url": f"{base_url.rstrip('/')}/v1/messages",
        "api_key": (os.getenv("DEEPSEEK_API_KEY") or "").strip(),
        "missing_key": "DEEPSEEK_API_KEY",
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
    del provider
    return _deepseek_concurrency_limit(model)


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


class DeepSeekRateLimitError(Exception):
    """Erreur DeepSeek 429 portant le nombre de secondes avant retry."""

    def __init__(self, wait_seconds: float, message: str = ""):
        super().__init__(message or f"Rate limit DeepSeek, attendre {wait_seconds:.0f}s")
        self.wait_seconds = wait_seconds


class DeepSeekAPIError(Exception):
    """Erreur HTTP non-429 DeepSeek avec statut et message déterministe.

    Utile pour distinguer les erreurs *retryables* (network, timeout, 5xx) des
    erreurs *déterministes* (400 invalid_request_error, 401 auth, 403 perms).
    Sur déterministe, retry est inutile — fail fast et propage le vrai message.
    """

    def __init__(self, status_code: int, error_type: str = "", message: str = ""):
        full = f"{error_type}: {message}" if error_type else message
        super().__init__(full or f"DeepSeek API {status_code}")
        self.status_code = status_code
        self.error_type = error_type
        self.message = message

    @property
    def is_deterministic(self) -> bool:
        """True si retry n'aidera pas (mauvaise requête, auth, crédits…)."""
        return self.status_code in (400, 401, 402, 403, 404, 422)


def is_deterministic_deepseek_error(exc: BaseException) -> bool:
    """Reconnaît les erreurs DeepSeek qu'une nouvelle tentative ne corrigera pas."""
    current = exc
    visited = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, DeepSeekAPIError) and current.is_deterministic:
            return True
        if isinstance(current, ValueError):
            message = str(current)
            if (
                "DEEPSEEK_API_KEY" in message
                or "Modèle non pris en charge" in message
                or "post_message: 'model' est requis" in message
            ):
                return True
        current = current.__cause__ or current.__context__
    return False


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

    # L'interface Anthropic-compatible peut exposer ces buckets ; on prend le
    # reset le plus tardif parmi ceux qui sont épuisés (remaining=0).
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


def post_message(
    messages,
    max_tokens=8000,
    model=None,
    timeout=600,
    temperature=None,
    http_max_attempts=None,
) -> str:
    """
    Appelle l'interface DeepSeek compatible ``POST /v1/messages``.

    - Lève `DeepSeekRateLimitError(wait_seconds)` sur 429, avec délai parsé
      depuis les headers.
    - Lève `DeepSeekAPIError` sur les autres erreurs HTTP.
    """
    if not model:
        raise ValueError("post_message: 'model' est requis")

    model = _normalize_model_alias(model)

    config = _provider_config(model)
    if not config["api_key"]:
        raise ValueError(f"{config['missing_key']} non définie pour {config['provider']}")

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    user_id = _deepseek_user_id()
    if user_id:
        payload["metadata"] = {"user_id": user_id}
    thinking = os.environ.get("DEEPSEEK_THINKING", "disabled").strip().lower()
    if thinking in ("enabled", "disabled"):
        payload["thinking"] = {"type": thinking}
    effort = os.environ.get("DEEPSEEK_REASONING_EFFORT", "").strip().lower()
    if thinking == "enabled" and effort in ("high", "max"):
        payload["output_config"] = {"effort": effort}

    max_attempts = (
        _llm_http_max_attempts()
        if http_max_attempts is None
        else max(1, min(6, int(http_max_attempts)))
    )
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
                raise DeepSeekRateLimitError(wait)

            if not resp.ok:
                try:
                    error_body = resp.json()
                except Exception:
                    error_body = resp.text[:500]
                logger.error(
                    f"❌ {config['provider']} API {resp.status_code} ({model}, max_tokens={max_tokens}) : {error_body}"
                )
                # Extrait un message lisible depuis le JSON d'erreur DeepSeek :
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
                api_error = DeepSeekAPIError(resp.status_code, err_type, err_msg)
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
            raise DeepSeekAPIError(200, "invalid_response", f"Réponse {config['provider']} sans bloc texte")
        except transient_errors as exc:
            if attempt >= max_attempts:
                raise
            wait = _transient_http_wait(attempt)
            logger.warning(
                f"⚠️ {config['provider']} réseau interrompu ({model}, tentative {attempt}/{max_attempts}) — "
                f"{type(exc).__name__}: {str(exc)[:200]} — retry dans {wait:.1f}s"
            )
            _sleep(wait)

    raise DeepSeekAPIError(500, "retry_exhausted", f"{config['provider']} retry épuisé")
