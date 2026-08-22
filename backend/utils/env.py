"""Helpers for reading typed values from environment variables."""

import os


_TRUE_ENV_VALUES = frozenset({"1", "true", "yes", "on"})


def env_bool(name: str, default: bool = False) -> bool:
    """Return a boolean flag while preserving common deployment spellings."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_ENV_VALUES
