from __future__ import annotations

import os
import threading

from utils.logger import get_logger

logger = get_logger(__name__)

_PROMPTS_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "prompts")
)
_PROMPT_CACHE: dict[tuple[str, float], str] = {}
_PROMPT_CACHE_LOCK = threading.Lock()


def prompt_file_path(*parts: str) -> str:
    return os.path.join(_PROMPTS_ROOT, *parts)


def load_prompt_file(*parts: str, fallback: str = "") -> str:
    path = prompt_file_path(*parts)
    try:
        mtime = os.path.getmtime(path)
        cache_key = (path, mtime)
        with _PROMPT_CACHE_LOCK:
            cached = _PROMPT_CACHE.get(cache_key)
        if cached is not None:
            return cached

        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()

        with _PROMPT_CACHE_LOCK:
            stale_keys = [key for key in _PROMPT_CACHE if key[0] == path and key != cache_key]
            for key in stale_keys:
                _PROMPT_CACHE.pop(key, None)
            _PROMPT_CACHE[cache_key] = content
        return content
    except Exception as e:
        logger.warning("⚠️ Prompt modulaire indisponible %s: %s", "/".join(parts), e)
        return fallback

