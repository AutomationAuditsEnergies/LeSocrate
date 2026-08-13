"""Build and persist an occurrence-bound, two-stage learner timeline.

Course MP3s are allowed to keep their natural generated duration.  The Q&A or
pause immediately following a course is the elastic buffer: it starts as soon
as speech ends, grows when speech ends early, and shrinks when speech runs
late.  A type-specific minimum is always protected; beyond that boundary the
course is hard-stopped. Break MP3s are then generated to the computed effective
duration, so the browser can play every asset normally without seeking or
looping silence.
"""

from __future__ import annotations

import json
import math
import re
import threading
from typing import Any, Iterable

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings

from services.platform_storage_service import (
    _audio_connection_string,
    platform_audio_container,
)


PLAYBACK_MANIFEST_FILENAME = "playback-manifest.json"
PLAYBACK_MANIFEST_SCHEMA_VERSION = 1
_OCCURRENCE_PREFIX_RE = re.compile(r"^course-sessions/[1-9][0-9]*$")
_MANIFEST_CACHE: dict[tuple[int, str], dict[str, Any]] = {}
_MANIFEST_CACHE_LOCK = threading.Lock()


def _playlist_item(item: Any) -> tuple[str, int, str, int]:
    if isinstance(item, dict):
        return (
            str(item.get("filename") or ""),
            int(item.get("planned_duration") or item.get("duration") or 0),
            str(item.get("type") or ""),
            int(item.get("course_index") or 0),
        )
    filename, duration, file_type, course_index = item
    return str(filename), int(duration), str(file_type), int(course_index)


def minimum_flexible_duration_seconds(file_type: str, planned_duration: int) -> int:
    """Return the protected minimum for the elastic Q&A/pause block."""
    from services.dynamic_day_schedule_service import (
        MIN_LUNCH_MINUTES,
        MIN_QA_MINUTES,
        MIN_SHORT_PAUSE_MINUTES,
    )

    if file_type == "pause_midi":
        minimum = MIN_LUNCH_MINUTES * 60
    elif file_type == "qa":
        minimum = MIN_QA_MINUTES * 60
    else:
        minimum = MIN_SHORT_PAUSE_MINUTES * 60
    return max(1, min(int(planned_duration or 0), int(minimum)))


def course_playback_cap_seconds(
    playlist_items: Iterable[Any],
    course_item_index: int,
) -> int:
    """Maximum course duration that preserves the next flexible block."""
    items = [_playlist_item(item) for item in playlist_items]
    index = int(course_item_index)
    if index < 0 or index >= len(items) or items[index][2] != "cours":
        raise ValueError("Index de cours invalide pour le calcul de la limite audio")

    course_duration = items[index][1]
    next_course_index = next(
        (cursor for cursor in range(index + 1, len(items)) if items[cursor][2] == "cours"),
        len(items),
    )
    flexible = items[index + 1:next_course_index]
    if not flexible:
        return max(1, course_duration)

    elastic = flexible[0]
    preserved_after_elastic = sum(item[1] for item in flexible[1:])
    protected_minimum = minimum_flexible_duration_seconds(elastic[2], elastic[1])
    group_duration = course_duration + sum(item[1] for item in flexible)
    return max(1, group_duration - preserved_after_elastic - protected_minimum)


def build_occurrence_playback_manifest(
    playlist_items: Iterable[Any],
    media_durations: dict[str, float],
    *,
    folder_id: int | None = None,
) -> dict[str, Any]:
    """Compile natural course durations into a fixed-anchor daily timeline."""
    items = [_playlist_item(item) for item in playlist_items]
    if not items:
        raise ValueError("Playlist vide pour le manifeste de lecture")

    segments: list[dict[str, Any]] = []
    cursor = 0
    index = 0
    while index < len(items):
        filename, planned_duration, file_type, course_index = items[index]
        measured = float(media_durations.get(filename) or 0.0)
        asset_duration = measured if measured > 0 else float(planned_duration)

        if file_type != "cours":
            effective_duration = max(1, int(planned_duration))
            segments.append(
                {
                    "filename": filename,
                    "type": file_type,
                    "course_index": course_index,
                    "planned_duration_sec": int(planned_duration),
                    "asset_duration_sec": round(asset_duration, 3),
                    "effective_start_sec": cursor,
                    "effective_duration_sec": effective_duration,
                    "generation_target_duration_sec": effective_duration,
                    "effective_end_sec": cursor + effective_duration,
                    "hard_stopped": False,
                }
            )
            cursor += effective_duration
            index += 1
            continue

        course_start = cursor
        next_course_index = next(
            (
                candidate
                for candidate in range(index + 1, len(items))
                if items[candidate][2] == "cours"
            ),
            len(items),
        )
        flexible = items[index + 1:next_course_index]
        course_cap = course_playback_cap_seconds(items, index)
        # Ceil avoids shaving the last partial MP3 second from a naturally
        # ending course.  The learner may see at most one silent fraction of a
        # second before the server-owned boundary advances.
        natural_duration = max(1, int(math.ceil(asset_duration)))
        effective_course_duration = min(natural_duration, course_cap)
        segments.append(
            {
                "filename": filename,
                "type": file_type,
                "course_index": course_index,
                "planned_duration_sec": int(planned_duration),
                "asset_duration_sec": round(asset_duration, 3),
                "effective_start_sec": cursor,
                "effective_duration_sec": effective_course_duration,
                "effective_end_sec": cursor + effective_course_duration,
                "hard_stop_sec": course_cap,
                "hard_stopped": natural_duration > course_cap,
            }
        )
        cursor += effective_course_duration

        if flexible:
            for flex_index, flex in enumerate(flexible):
                flex_filename, flex_planned, flex_type, flex_course_index = flex
                flex_measured = float(media_durations.get(flex_filename) or 0.0)
                flex_asset_duration = flex_measured if flex_measured > 0 else float(flex_planned)
                is_elastic = flex_index == 0
                if is_elastic:
                    planned_group_duration = planned_duration + sum(
                        item[1] for item in flexible
                    )
                    group_end = course_start + planned_group_duration
                    preserved_after_elastic = sum(
                        item[1] for item in flexible[flex_index + 1:]
                    )
                    effective_flex_duration = max(
                        1,
                        group_end - cursor - preserved_after_elastic,
                    )
                else:
                    effective_flex_duration = max(1, int(flex_planned))
                segments.append(
                    {
                        "filename": flex_filename,
                        "type": flex_type,
                        "course_index": flex_course_index,
                        "planned_duration_sec": int(flex_planned),
                        "asset_duration_sec": round(flex_asset_duration, 3),
                        "effective_start_sec": cursor,
                    "effective_duration_sec": effective_flex_duration,
                    "generation_target_duration_sec": effective_flex_duration,
                        "effective_end_sec": cursor + effective_flex_duration,
                        "elastic": is_elastic,
                        "hard_stopped": False,
                    }
                )
                cursor += effective_flex_duration

        index = next_course_index

    planned_total = sum(item[1] for item in items)
    if cursor != planned_total:
        raise ValueError(
            f"Timeline adaptative incohérente ({cursor}s au lieu de {planned_total}s)"
        )
    return {
        "schema_version": PLAYBACK_MANIFEST_SCHEMA_VERSION,
        "strategy": "natural_course_then_exact_elastic_break_assets",
        "folder_id": int(folder_id) if folder_id is not None else None,
        "planned_total_duration_sec": planned_total,
        "effective_total_duration_sec": cursor,
        "segments": segments,
    }


def apply_occurrence_playback_manifest(
    playlist: list[dict[str, Any]],
    manifest: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Overlay effective and decoded durations onto a canonical playlist."""
    if not manifest:
        return playlist
    by_filename = {
        str(segment.get("filename") or ""): segment
        for segment in manifest.get("segments") or []
        if isinstance(segment, dict)
    }
    if not by_filename:
        return playlist

    adapted = []
    for item in playlist:
        segment = by_filename.get(str(item.get("filename") or ""))
        if not segment:
            adapted.append(dict(item))
            continue
        clone = dict(item)
        clone["planned_duration"] = int(item.get("duration") or 0)
        clone["duration"] = int(segment.get("effective_duration_sec") or clone["planned_duration"])
        clone["asset_duration"] = float(segment.get("asset_duration_sec") or clone["planned_duration"])
        clone["effective_start"] = int(segment.get("effective_start_sec") or 0)
        clone["effective_end"] = int(segment.get("effective_end_sec") or 0)
        clone["hard_stopped"] = bool(segment.get("hard_stopped"))
        clone["elastic"] = bool(segment.get("elastic"))
        adapted.append(clone)
    return adapted


def _validated_occurrence_prefix(value: str) -> str:
    prefix = str(value or "").strip().strip("/")
    if not _OCCURRENCE_PREFIX_RE.fullmatch(prefix):
        raise ValueError("Préfixe de manifeste de lecture invalide")
    return prefix


def upload_occurrence_playback_manifest(
    platform_id: int,
    occurrence_prefix: str,
    manifest: dict[str, Any],
    *,
    blob_service_client=None,
) -> str:
    prefix = _validated_occurrence_prefix(occurrence_prefix)
    client = blob_service_client or BlobServiceClient.from_connection_string(
        _audio_connection_string()
    )
    blob_name = f"{prefix}/{PLAYBACK_MANIFEST_FILENAME}"
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    client.get_blob_client(
        container=platform_audio_container(int(platform_id)),
        blob=blob_name,
    ).upload_blob(
        payload,
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json; charset=utf-8"),
    )
    with _MANIFEST_CACHE_LOCK:
        _MANIFEST_CACHE[(int(platform_id), prefix)] = dict(manifest)
    return blob_name


def load_occurrence_playback_manifest(
    platform_id: int,
    occurrence_prefix: str,
    *,
    blob_service_client=None,
) -> dict[str, Any] | None:
    prefix = _validated_occurrence_prefix(occurrence_prefix)
    cache_key = (int(platform_id), prefix)
    with _MANIFEST_CACHE_LOCK:
        cached = _MANIFEST_CACHE.get(cache_key)
    if cached is not None:
        return cached

    client = blob_service_client or BlobServiceClient.from_connection_string(
        _audio_connection_string()
    )
    blob = client.get_blob_client(
        container=platform_audio_container(int(platform_id)),
        blob=f"{prefix}/{PLAYBACK_MANIFEST_FILENAME}",
    )
    try:
        payload = json.loads(blob.download_blob().readall().decode("utf-8"))
    except ResourceNotFoundError:
        # Historic occurrences predate adaptive manifests.  Do not cache the
        # miss: a J-1 publisher may still be completing this immutable prefix.
        return None
    if (
        not isinstance(payload, dict)
        or int(payload.get("schema_version") or 0) != PLAYBACK_MANIFEST_SCHEMA_VERSION
        or not isinstance(payload.get("segments"), list)
    ):
        raise ValueError("Manifeste de lecture adaptative invalide")
    with _MANIFEST_CACHE_LOCK:
        _MANIFEST_CACHE[cache_key] = payload
    return payload
