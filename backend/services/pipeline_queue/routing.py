"""Task routing shared by database workers and Azure Service Bus."""

from __future__ import annotations

from collections.abc import Iterable


AI_TASK_TYPES = frozenset(
    {
        "auto_pilot_tick",
        "ai_teacher_fulfillment",
    }
)
AUDIO_TASK_TYPES = frozenset(
    {
        "hr_playlist_generate",
        "hr_playlist_item",
        "scheduled_audio_item",
        "voice_reference_calibration",
    }
)
WORKER_KINDS = frozenset({"general", "ai", "audio"})


def normalize_worker_kind(value: str | None) -> str:
    kind = (value or "general").strip().lower()
    aliases = {
        "all": "general",
        "default": "general",
        "generation": "ai",
        "tts": "audio",
    }
    kind = aliases.get(kind, kind)
    if kind not in WORKER_KINDS:
        allowed = ", ".join(sorted(WORKER_KINDS))
        raise ValueError(f"PIPELINE_WORKER_KIND doit être parmi: {allowed}")
    return kind


def task_types_for_worker(worker_kind: str | None) -> frozenset[str] | None:
    kind = normalize_worker_kind(worker_kind)
    if kind == "ai":
        return AI_TASK_TYPES
    if kind == "audio":
        return AUDIO_TASK_TYPES
    return None


def normalize_task_types(task_types: Iterable[str] | None) -> tuple[str, ...]:
    """Return a stable, duplicate-free tuple suitable for SQL parameters."""
    if task_types is None:
        return ()
    return tuple(
        sorted(
            {
                str(task_type).strip()
                for task_type in task_types
                if str(task_type).strip()
            }
        )
    )


def worker_kind_for_task(task_type: str | None) -> str:
    normalized = (task_type or "").strip()
    if normalized in AI_TASK_TYPES:
        return "ai"
    if normalized in AUDIO_TASK_TYPES:
        return "audio"
    # Unknown task types keep the legacy queue so a general worker can
    # dead-letter them explicitly instead of making them disappear.
    return "general"
