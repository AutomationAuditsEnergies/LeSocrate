"""Compact, display-safe summaries derived from immutable V2 schedules."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _uniform(values: list[int]) -> int | None:
    return values[0] if values and len(set(values)) == 1 else None


def summarize_v2_schedule(
    schedule: Any,
    *,
    schema_version: Any = None,
) -> dict[str, Any] | None:
    """Return real course counts/minutes for a V2 schedule, else ``None``.

    The helper intentionally ignores pauses and Q&A blocks.  It accepts both
    billing schedules and the immutable snapshot stored on pipeline jobs.
    """

    schedule = _json_value(schedule)
    if not isinstance(schedule, Mapping):
        return None

    raw_version = (
        schema_version
        if schema_version not in (None, "")
        else schedule.get(
            "schedule_schema_version",
            schedule.get("schema_version"),
        )
    )
    try:
        version = int(raw_version or 1)
    except (TypeError, ValueError):
        return None
    if version != 2:
        return None

    days = _json_value(schedule.get("days"))
    if not isinstance(days, list) or not days:
        return None

    daily_course_counts: list[int] = []
    daily_course_minutes: list[int] = []
    course_durations: list[int] = []
    for day in days:
        if not isinstance(day, Mapping):
            return None
        blocks = _json_value(
            day.get("blocks")
            or day.get("schedule_blocks")
            or day.get("blocks_snapshot_json")
            or []
        )
        if not isinstance(blocks, list):
            return None
        durations = [
            duration
            for block in blocks
            if isinstance(block, Mapping)
            and str(block.get("block_type") or "").strip().lower() == "course"
            and (duration := _positive_int(block.get("duration_minutes"))) is not None
        ]
        daily_course_counts.append(len(durations))
        daily_course_minutes.append(sum(durations))
        course_durations.extend(durations)

    if not course_durations:
        return None

    return {
        "source": "schedule_v2",
        "day_count": len(days),
        "course_count": len(course_durations),
        "course_minutes": sum(course_durations),
        "daily_course_counts": daily_course_counts,
        "daily_course_minutes": daily_course_minutes,
        "uniform_daily_course_count": _uniform(daily_course_counts),
        "uniform_daily_course_minutes": _uniform(daily_course_minutes),
        "uniform_course_duration_minutes": _uniform(course_durations),
    }
