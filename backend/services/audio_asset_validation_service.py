"""Fail-closed validation for generated teaching-audio blobs."""

from __future__ import annotations

import math
import os
import threading
from collections import OrderedDict

from services.day_playlist_service import is_course_audio_filename


_CACHE_MAX_ITEMS = 512
_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _property(props, name, default=None):
    if isinstance(props, dict):
        return props.get(name, default)
    return getattr(props, name, default)


def _content_type(props) -> str:
    settings = _property(props, "content_settings")
    if isinstance(settings, dict):
        value = settings.get("content_type")
    else:
        value = getattr(settings, "content_type", None)
    return str(value or "").strip().lower()


def _metadata(props) -> dict:
    value = _property(props, "metadata", {}) or {}
    return dict(value) if isinstance(value, dict) else {}


def _measure_sample(sample: bytes) -> float:
    from services.content_generation_service import _mp3_duration_seconds_no_ffprobe

    return float(_mp3_duration_seconds_no_ffprobe(sample))


def _cache_get(key: tuple) -> dict | None:
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is None:
            return None
        _CACHE.move_to_end(key)
        return dict(cached)


def _cache_put(key: tuple, value: dict) -> dict:
    with _CACHE_LOCK:
        _CACHE[key] = dict(value)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX_ITEMS:
            _CACHE.popitem(last=False)
    return value


def inspect_mp3_blob(
    blob_client,
    filename: str,
    *,
    props=None,
    expected_duration_seconds: float | int | None = None,
) -> dict:
    """Validate MP3 headers near both ends and estimate the media duration.

    Only bounded ranges are downloaded, so a dashboard readiness check never
    downloads hours of audio. The ETag cache makes repeated polling free until
    the blob changes.
    """
    props = props or blob_client.get_blob_properties()
    size = int(_property(props, "size", 0) or 0)
    etag = str(_property(props, "etag", "") or "")
    content_type = _content_type(props)
    metadata = _metadata(props)
    expected = float(expected_duration_seconds or 0.0)
    cache_key = (str(filename or ""), etag, size, round(expected, 3))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    result = {
        "filename": str(filename or ""),
        "ready": False,
        "physical_ready": False,
        "reason": None,
        "size_bytes": size,
        "content_type": content_type,
        "estimated_duration_seconds": 0.0,
        "etag": etag,
        "sha256": metadata.get("sha256"),
    }
    if size <= 0:
        result["reason"] = "empty_audio"
        return _cache_put(cache_key, result)
    if content_type and content_type not in {"audio/mpeg", "audio/mp3"}:
        result["reason"] = "invalid_content_type"
        return _cache_put(cache_key, result)
    if is_course_audio_filename(filename) and size < 100_000:
        result["reason"] = "course_audio_too_small"
        return _cache_put(cache_key, result)

    head_length = min(size, 512 * 1024)
    tail_length = min(size, 128 * 1024)
    try:
        head = blob_client.download_blob(offset=0, length=head_length).readall()
        head_duration = _measure_sample(head)
        if head_duration <= 0:
            raise ValueError("durée MP3 nulle")
        if size > head_length:
            tail = blob_client.download_blob(
                offset=max(0, size - tail_length),
                length=tail_length,
            ).readall()
            if _measure_sample(tail) <= 0:
                raise ValueError("fin MP3 illisible")
    except Exception as exc:
        result["reason"] = "undecodable_mp3"
        result["detail"] = str(exc)[:240]
        return _cache_put(cache_key, result)

    estimated_duration = head_duration * (size / max(1, len(head)))
    metadata_duration = metadata.get("duration_seconds")
    try:
        metadata_duration = float(metadata_duration or 0.0)
    except (TypeError, ValueError):
        metadata_duration = 0.0
    if metadata_duration > 0:
        estimated_duration = metadata_duration
    result["estimated_duration_seconds"] = round(float(estimated_duration), 3)

    if is_course_audio_filename(filename):
        minimum_duration = max(5.0, min(120.0, expected * 0.05 if expected > 0 else 5.0))
        if estimated_duration < minimum_duration:
            result["reason"] = "course_audio_too_short"
            result["minimum_duration_seconds"] = round(minimum_duration, 3)
            return _cache_put(cache_key, result)

    result["ready"] = True
    result["physical_ready"] = True
    return _cache_put(cache_key, result)


def validate_mp3_bytes(
    filename: str,
    audio_bytes: bytes,
    *,
    expected_duration_seconds: float | int | None = None,
) -> dict:
    """Fully validate bytes immediately before publishing learner-visible audio."""
    payload = bytes(audio_bytes or b"")
    if not payload:
        raise ValueError(f"Audio vide: {filename}")
    if is_course_audio_filename(filename) and len(payload) < 100_000:
        raise ValueError(f"Audio de cours trop petit: {filename} ({len(payload)} octets)")
    duration = _measure_sample(payload)
    expected = float(expected_duration_seconds or 0.0)
    if is_course_audio_filename(filename):
        minimum_duration = max(5.0, min(120.0, expected * 0.05 if expected > 0 else 5.0))
        if duration < minimum_duration:
            raise ValueError(
                f"Audio de cours trop court: {filename} ({duration:.1f}s, minimum {minimum_duration:.1f}s)"
            )
    return {
        "filename": filename,
        "size_bytes": len(payload),
        "duration_seconds": round(duration, 3),
        "physical_ready": True,
    }


def inspect_audio_sync_payload(
    deck: dict | None,
    expected_filenames,
    *,
    require_all_slides: bool = True,
) -> dict:
    """Validate the persisted slide/audio contract without trusting its flags."""
    expected_courses = {
        os.path.basename(str(filename or "").split("?", 1)[0]).lower()
        for filename in expected_filenames
        if is_course_audio_filename(filename)
    }
    if not expected_courses:
        return {
            "ready": True,
            "deck_id": None,
            "expected_course_files": [],
            "missing_course_files": [],
            "missing_slide_ids": [],
            "timing_files": [],
        }

    if not deck:
        return {
            "ready": False,
            "deck_id": None,
            "expected_course_files": sorted(expected_courses),
            "missing_course_files": sorted(expected_courses),
            "missing_slide_ids": [],
            "timing_files": [],
            "reason": "missing_slide_deck",
        }

    slide_ids = {
        str(slide.get("slide_id"))
        for slide in (deck.get("slides") or [])
        if slide.get("slide_id")
    }
    timing_files = set()
    synced_slide_ids = set()
    for timing in (deck.get("audio_sync") or {}).get("timings") or []:
        if not isinstance(timing, dict):
            continue
        filename = str(timing.get("audio_filename") or timing.get("filename") or "")
        filename = os.path.basename(filename.split("?", 1)[0]).lower()
        try:
            start = float(timing.get("start_time"))
            end = float(timing.get("end_time"))
        except (TypeError, ValueError):
            continue
        slide_id = str(timing.get("slide_id") or "")
        if (
            filename not in expected_courses
            or not math.isfinite(start)
            or not math.isfinite(end)
            or end <= start
            or slide_id not in slide_ids
        ):
            continue
        timing_files.add(filename)
        synced_slide_ids.add(slide_id)

    missing_course_files = sorted(expected_courses - timing_files)
    missing_slide_ids = sorted(slide_ids - synced_slide_ids)
    ready = bool(slide_ids) and not missing_course_files
    if require_all_slides:
        ready = ready and not missing_slide_ids
    return {
        "ready": ready,
        "deck_id": deck.get("deck_id"),
        "expected_course_files": sorted(expected_courses),
        "missing_course_files": missing_course_files,
        "missing_slide_ids": missing_slide_ids,
        "timing_files": sorted(timing_files),
        "slide_count": len(slide_ids),
        "synced_slide_count": len(slide_ids & synced_slide_ids),
    }


def inspect_audio_sync_readiness(
    folder_id: int,
    expected_filenames,
) -> dict:
    """Require every course file and every persisted slide to have timings."""
    from services.script_slide_generation_service import get_latest_script_slide_deck

    return inspect_audio_sync_payload(
        get_latest_script_slide_deck(int(folder_id)),
        expected_filenames,
        require_all_slides=True,
    )


def audio_sync_timing_files(folder_id: int) -> set[str]:
    """Return course filenames backed by at least one valid persisted timing."""
    from services.script_slide_generation_service import get_latest_script_slide_deck

    deck = get_latest_script_slide_deck(int(folder_id))
    if not deck:
        return set()
    filenames = {
        os.path.basename(
            str(timing.get("audio_filename") or timing.get("filename") or "")
            .split("?", 1)[0]
        ).lower()
        for timing in (deck.get("audio_sync") or {}).get("timings") or []
        if isinstance(timing, dict)
        and is_course_audio_filename(
            timing.get("audio_filename") or timing.get("filename")
        )
    }
    return set(
        inspect_audio_sync_payload(
            deck,
            filenames,
            require_all_slides=False,
        ).get("timing_files") or []
    )
