"""Generate and cache lightweight waveform manifests for large audio files.

The browser can render WaveSurfer from these peaks while the native media
element streams the MP3 with HTTP Range requests.  This avoids downloading and
decoding an entire (often 50-70 MB) course file just to draw its waveform.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime, timezone

import numpy as np
import soundfile as sf
from azure.storage.blob import ContentSettings


WAVEFORM_SCHEMA_VERSION = 1
DEFAULT_WAVEFORM_POINTS = 4096


def waveform_cache_blob_path(audio_blob_path: str) -> str:
    return f"{audio_blob_path}.waveform-v{WAVEFORM_SCHEMA_VERSION}.json"


def _normalise_etag(value) -> str:
    return str(value or "").strip('"')


def extract_waveform(path: str, *, points: int = DEFAULT_WAVEFORM_POINTS) -> dict:
    """Decode an audio file incrementally and return one peak per time bucket."""
    requested_points = max(128, min(int(points), 16_384))

    with sf.SoundFile(path) as audio:
        total_frames = int(len(audio))
        sample_rate = int(audio.samplerate)
        if total_frames <= 0 or sample_rate <= 0:
            raise ValueError("Fichier audio vide ou durée invalide")

        output_points = min(requested_points, total_frames)
        frames_per_peak = max(1, math.ceil(total_frames / output_points))
        peaks = []

        while True:
            frames = audio.read(
                frames_per_peak,
                dtype="float32",
                always_2d=True,
            )
            if not len(frames):
                break
            peak = float(np.max(np.abs(frames)))
            peaks.append(round(min(1.0, max(0.0, peak)), 5))

    return {
        "duration": total_frames / sample_rate,
        "peaks": peaks,
        "points": len(peaks),
        "sample_rate": sample_rate,
    }


def get_or_create_waveform(
    audio_blob_client,
    cache_blob_client,
    *,
    audio_properties=None,
    points: int = DEFAULT_WAVEFORM_POINTS,
    generate_if_missing: bool = True,
) -> dict:
    """Read a valid cached manifest or generate it using bounded memory."""
    props = audio_properties or audio_blob_client.get_blob_properties()
    source_etag = _normalise_etag(getattr(props, "etag", ""))
    source_size = int(getattr(props, "size", 0) or 0)

    try:
        cached = json.loads(cache_blob_client.download_blob().readall())
        if (
            int(cached.get("schema_version") or 0) == WAVEFORM_SCHEMA_VERSION
            and _normalise_etag(cached.get("source_etag")) == source_etag
            and int(cached.get("source_size") or 0) == source_size
            and cached.get("peaks")
            and float(cached.get("duration") or 0) > 0
        ):
            cached["cache_hit"] = True
            return cached
    except Exception:
        # Missing, stale or malformed cache: regenerate from the source MP3.
        pass

    if not generate_if_missing:
        raise FileNotFoundError("Waveform cache missing or stale")

    suffix = os.path.splitext(getattr(audio_blob_client, "blob_name", "") or "")[1] or ".mp3"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
            temp_path = temp_file.name
            audio_blob_client.download_blob(max_concurrency=2).readinto(temp_file)

        waveform = extract_waveform(temp_path, points=points)
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    manifest = {
        "schema_version": WAVEFORM_SCHEMA_VERSION,
        "source_etag": source_etag,
        "source_size": source_size,
        "duration": round(float(waveform["duration"]), 4),
        "peaks": waveform["peaks"],
        "points": waveform["points"],
        "sample_rate": waveform["sample_rate"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cache_hit": False,
    }
    cache_blob_client.upload_blob(
        json.dumps(manifest, separators=(",", ":")).encode("utf-8"),
        overwrite=True,
        content_settings=ContentSettings(
            content_type="application/json",
            cache_control="private, max-age=86400",
        ),
    )
    return manifest


def create_waveform_for_uploaded_bytes(
    audio_blob_client,
    cache_blob_client,
    audio_bytes: bytes,
    *,
    audio_properties=None,
    points: int = DEFAULT_WAVEFORM_POINTS,
) -> dict:
    """Create the cache while upload bytes are already available in memory."""
    props = audio_properties or audio_blob_client.get_blob_properties()
    payload = bytes(audio_bytes or b"")
    if not payload:
        raise ValueError("Fichier audio vide")

    suffix = os.path.splitext(getattr(audio_blob_client, "blob_name", "") or "")[1] or ".mp3"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
            temp_path = temp_file.name
            temp_file.write(payload)
        waveform = extract_waveform(temp_path, points=points)
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    manifest = {
        "schema_version": WAVEFORM_SCHEMA_VERSION,
        "source_etag": _normalise_etag(getattr(props, "etag", "")),
        "source_size": int(getattr(props, "size", 0) or len(payload)),
        "duration": round(float(waveform["duration"]), 4),
        "peaks": waveform["peaks"],
        "points": waveform["points"],
        "sample_rate": waveform["sample_rate"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cache_hit": False,
    }
    cache_blob_client.upload_blob(
        json.dumps(manifest, separators=(",", ":")).encode("utf-8"),
        overwrite=True,
        content_settings=ContentSettings(
            content_type="application/json",
            cache_control="private, max-age=86400",
        ),
    )
    return manifest
