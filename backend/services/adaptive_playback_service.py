"""Build and persist an occurrence-bound, adaptive learner timeline.

Course MP3s keep their natural duration and their advance/delay propagates
through an adjacent course chain.  A hidden jointure is inserted between two
courses and counts as technical delay.  The first Q&A/pause after that chain is
the elastic buffer: it grows when the chain ends early and shrinks by at most
five minutes (without crossing its absolute type minimum).  Any remaining
delay hard-stops the last course immediately preceding that flexible block.
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
    planned = max(1, int(planned_duration or 0))
    # A flexible block can lose at most five minutes and must also respect its
    # absolute planning minimum (ten minutes for Q&A/short pause).
    return max(1, min(planned, max(int(minimum), planned - 300)))


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
    following = items[index + 1] if index + 1 < len(items) else None
    if following and following[2] in {"qa", "pause", "pause_midi"}:
        protected = minimum_flexible_duration_seconds(
            following[2], following[1]
        )
        return max(1, course_duration + following[1] - protected)

    # An earlier course in a contiguous chain is intentionally not capped:
    # its drift propagates to n+1.  The occurrence manifest will perform the
    # only required hard stop on the last course before the elastic block.
    return max(1, course_duration + 24 * 60 * 60)


def build_occurrence_playback_manifest(
    playlist_items: Iterable[Any],
    media_durations: dict[str, float],
    *,
    folder_id: int | None = None,
) -> dict[str, Any]:
    """Compile natural course durations using the recurrence defined above."""
    items = [_playlist_item(item) for item in playlist_items]
    if not items:
        raise ValueError("Playlist vide pour le manifeste de lecture")

    segments: list[dict[str, Any]] = []
    actual_cursor = 0
    scheduled_cursor = 0
    elastic_available = False

    for filename, planned_duration, file_type, course_index in items:
        measured = float(media_durations.get(filename) or 0.0)
        asset_duration = measured if measured > 0 else float(planned_duration)

        if file_type == "cours":
            natural_duration = max(1, int(math.ceil(asset_duration)))
            segments.append(
                {
                    "filename": filename,
                    "type": file_type,
                    "course_index": course_index,
                    "planned_duration_sec": int(planned_duration),
                    "asset_duration_sec": round(asset_duration, 3),
                    "scheduled_start_sec": scheduled_cursor,
                    "effective_start_sec": actual_cursor,
                    "effective_duration_sec": natural_duration,
                    "effective_end_sec": actual_cursor + natural_duration,
                    "hard_stop_sec": None,
                    "hard_stopped": False,
                }
            )
            actual_cursor += natural_duration
            scheduled_cursor += max(1, int(planned_duration))
            elastic_available = True
            continue

        if file_type == "jointure":
            effective_duration = max(
                1,
                min(10, int(planned_duration), int(math.ceil(asset_duration))),
            )
            segments.append(
                {
                    "filename": filename,
                    "type": file_type,
                    "course_index": course_index,
                    "planned_duration_sec": int(planned_duration),
                    "scheduled_duration_sec": 0,
                    "asset_duration_sec": round(asset_duration, 3),
                    "scheduled_start_sec": scheduled_cursor,
                    "effective_start_sec": actual_cursor,
                    "effective_duration_sec": effective_duration,
                    "generation_target_duration_sec": effective_duration,
                    "effective_end_sec": actual_cursor + effective_duration,
                    "technical_delay_sec": effective_duration,
                    "hard_stopped": False,
                }
            )
            actual_cursor += effective_duration
            continue

        planned = max(1, int(planned_duration))
        is_elastic = elastic_available and file_type in {
            "qa",
            "pause",
            "pause_midi",
        }
        drift_before = actual_cursor - scheduled_cursor
        if is_elastic:
            protected = minimum_flexible_duration_seconds(file_type, planned)
            maximum_shrink = planned - protected
            surplus = max(0, drift_before - maximum_shrink)
            if surplus:
                last_course_index = next(
                    (
                        candidate
                        for candidate in range(len(segments) - 1, -1, -1)
                        if segments[candidate]["type"] == "cours"
                    ),
                    None,
                )
                if last_course_index is not None:
                    course_segment = segments[last_course_index]
                    removable = max(
                        0,
                        int(course_segment["effective_duration_sec"]) - 1,
                    )
                    cut = min(int(surplus), removable)
                    if cut:
                        course_segment["effective_duration_sec"] -= cut
                        course_segment["effective_end_sec"] -= cut
                        course_segment["hard_stop_sec"] = course_segment[
                            "effective_duration_sec"
                        ]
                        course_segment["hard_stopped"] = True
                        for later in segments[last_course_index + 1:]:
                            later["effective_start_sec"] -= cut
                            later["effective_end_sec"] -= cut
                        actual_cursor -= cut
                        drift_before -= cut
            effective_duration = max(protected, planned - drift_before)
        else:
            effective_duration = planned

        segments.append(
            {
                "filename": filename,
                "type": file_type,
                "course_index": course_index,
                "planned_duration_sec": planned,
                "asset_duration_sec": round(asset_duration, 3),
                "scheduled_start_sec": scheduled_cursor,
                "effective_start_sec": actual_cursor,
                "effective_duration_sec": int(effective_duration),
                "generation_target_duration_sec": int(effective_duration),
                "effective_end_sec": actual_cursor + int(effective_duration),
                "drift_before_sec": drift_before,
                "elastic": is_elastic,
                "hard_stopped": False,
            }
        )
        actual_cursor += int(effective_duration)
        scheduled_cursor += planned
        if is_elastic:
            elastic_available = False

    planned_total = sum(
        item[1] for item in items if item[2] != "jointure"
    )
    technical_total = sum(
        segment["effective_duration_sec"]
        for segment in segments
        if segment["type"] == "jointure"
    )
    return {
        "schema_version": PLAYBACK_MANIFEST_SCHEMA_VERSION,
        "strategy": "recursive_course_drift_then_first_optional_flexible_block",
        "folder_id": int(folder_id) if folder_id is not None else None,
        "planned_total_duration_sec": planned_total,
        "technical_jointure_duration_sec": technical_total,
        "effective_total_duration_sec": actual_cursor,
        "final_drift_sec": actual_cursor - scheduled_cursor,
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
        # miss: an H-72 publisher may still be completing this immutable prefix.
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
