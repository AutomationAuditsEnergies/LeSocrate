"""Fish Audio voice cloning, verification, ASR calibration and previews."""

from __future__ import annotations

import hashlib
import io
import math
import os
import re
from typing import Any

import requests as http_requests
from pydub import AudioSegment


FISH_MODEL_URL = "https://api.fish.audio/model"
FISH_ASR_URL = "https://api.fish.audio/v1/asr"
FISH_TTS_URL = "https://api.fish.audio/v1/tts"
MAX_CLONE_BYTES = 25 * 1024 * 1024
MAX_CALIBRATION_BYTES = 100 * 1024 * 1024
RIGHTS_DECLARATION = (
    "Je certifie que cette voix est la mienne ou que je dispose d’une autorisation "
    "écrite, valide et suffisante de son titulaire pour la cloner et l’utiliser sur la "
    "plateforme. Je m’engage à ne pas l’utiliser de manière illicite, trompeuse ou "
    "portant atteinte aux droits d’un tiers. Je reconnais être responsable des fichiers "
    "fournis et de l’utilisation de cette voix, conformément aux conditions d’utilisation."
)


class FishVoiceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502, code: str = "fish_audio_error"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _api_key() -> str:
    value = (os.getenv("FISH_AUDIO_API_KEY") or "").strip()
    if not value:
        raise FishVoiceError(
            "La clé API Fish Audio n'est pas configurée.",
            status_code=503,
            code="fish_audio_not_configured",
        )
    return value


def _authorization_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_api_key()}"}


def _raise_for_fish(response, action: str) -> None:
    if response.ok:
        return
    try:
        payload = response.json()
        detail = payload.get("message") or payload.get("detail") or payload.get("error")
    except Exception:
        detail = response.text
    if response.status_code in {401, 403}:
        code = "fish_audio_auth_failed"
    elif response.status_code == 402:
        code = "fish_audio_credits_required"
    elif response.status_code == 429:
        code = "fish_audio_rate_limited"
    else:
        code = "fish_audio_request_failed"
    raise FishVoiceError(
        f"{action} impossible via Fish Audio ({response.status_code})"
        + (f" : {str(detail)[:300]}" if detail else "."),
        status_code=502,
        code=code,
    )


def audio_sha256(audio_bytes: bytes) -> str:
    return hashlib.sha256(audio_bytes).hexdigest()


def _matches_browser_audio_container(audio_bytes: bytes, suffix: str) -> bool:
    if suffix == "webm":
        return audio_bytes.startswith(b"\x1a\x45\xdf\xa3")
    if suffix in {"m4a", "mp4"}:
        return len(audio_bytes) >= 12 and audio_bytes[4:8] == b"ftyp"
    return False


def audio_duration_seconds(audio_bytes: bytes, filename: str = "audio") -> float:
    if not audio_bytes:
        raise FishVoiceError("Le fichier audio est vide.", status_code=400, code="empty_audio")
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else None
    try:
        segment = AudioSegment.from_file(io.BytesIO(audio_bytes), format=suffix)
    except Exception:
        try:
            segment = AudioSegment.from_file(io.BytesIO(audio_bytes))
        except Exception as exc:
            raise FishVoiceError(
                "Impossible de lire cet audio. Utilisez MP3, WAV, M4A, FLAC ou WEBM.",
                status_code=422,
                code="unsupported_audio",
            ) from exc
    return round(len(segment) / 1000.0, 3)


def validate_audio(
    audio_bytes: bytes,
    filename: str,
    *,
    min_seconds: float,
    max_seconds: float,
    max_bytes: int,
    duration_hint: float | str | None = None,
) -> float:
    if len(audio_bytes) > max_bytes:
        raise FishVoiceError(
            "Le fichier audio dépasse la taille autorisée.",
            status_code=413,
            code="audio_too_large",
        )
    try:
        duration = audio_duration_seconds(audio_bytes, filename)
    except FishVoiceError as exc:
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        try:
            hinted_duration = float(duration_hint) if duration_hint not in (None, "") else 0.0
        except (TypeError, ValueError):
            hinted_duration = 0.0
        if (
            exc.code != "unsupported_audio"
            or suffix not in {"webm", "m4a", "mp4"}
            or not _matches_browser_audio_container(audio_bytes, suffix)
            or not math.isfinite(hinted_duration)
            or hinted_duration <= 0
        ):
            raise
        # MediaRecorder produces valid Opus/WebM files that Fish Audio accepts,
        # while the App Service image may not include an FFmpeg WebM decoder.
        # The browser has already decoded the same blob to display its duration.
        duration = round(hinted_duration, 3)
    if duration < min_seconds or duration > max_seconds:
        raise FishVoiceError(
            f"La durée doit être comprise entre {int(min_seconds)} et {int(max_seconds)} secondes.",
            status_code=422,
            code="audio_duration_invalid",
        )
    return duration


def create_instant_clone(
    *,
    name: str,
    audio_bytes: bytes,
    filename: str,
    mime_type: str,
    transcript: str | None = None,
) -> dict[str, Any]:
    data: list[tuple[str, str]] = [
        ("type", "tts"),
        ("title", name),
        ("train_mode", "fast"),
        ("visibility", "private"),
        ("description", "Voix pédagogique privée créée depuis Le Socrate"),
        ("enhance_audio_quality", "true"),
        ("generate_sample", "false"),
        ("tags", "le-socrate"),
        ("tags", "formation"),
    ]
    if transcript:
        data.append(("texts", transcript.strip()))
    response = http_requests.post(
        FISH_MODEL_URL,
        headers=_authorization_headers(),
        data=data,
        files=[("voices", (filename or "voix.wav", audio_bytes, mime_type or "audio/wav"))],
        timeout=(30, 180),
    )
    _raise_for_fish(response, "Le clonage de la voix")
    payload = response.json()
    reference_id = str(payload.get("_id") or payload.get("id") or "").strip()
    if not reference_id:
        raise FishVoiceError("Fish Audio n'a renvoyé aucun identifiant de voix.")
    return {
        "reference_id": reference_id,
        "state": payload.get("state") or "created",
        "title": payload.get("title") or name,
    }


def verify_reference_id(reference_id: str) -> dict[str, Any]:
    response = http_requests.get(
        f"{FISH_MODEL_URL}/{reference_id}",
        headers=_authorization_headers(),
        timeout=(15, 45),
    )
    _raise_for_fish(response, "La vérification de l'identifiant")
    payload = response.json()
    return {
        "reference_id": str(payload.get("_id") or payload.get("id") or reference_id),
        "state": payload.get("state") or "created",
        "title": payload.get("title") or "Voix importée",
    }


def transcribe_and_measure_wpm(
    *,
    audio_bytes: bytes,
    filename: str,
    mime_type: str,
    language: str = "fr",
) -> dict[str, Any]:
    response = http_requests.post(
        FISH_ASR_URL,
        headers=_authorization_headers(),
        data={"language": language, "ignore_timestamps": "false"},
        files=[("audio", (filename or "calibrage.wav", audio_bytes, mime_type or "audio/wav"))],
        timeout=(30, 300),
    )
    _raise_for_fish(response, "L'analyse du débit")
    payload = response.json()
    text = str(payload.get("text") or "").strip()
    duration = float(payload.get("duration") or 0.0)
    if duration <= 0:
        duration = audio_duration_seconds(audio_bytes, filename)
    words = re.findall(r"[^\W_]+(?:['’\-][^\W_]+)*", text, flags=re.UNICODE)
    wpm = len(words) / (duration / 60.0) if duration > 0 else 0.0
    if not words or wpm <= 0:
        raise FishVoiceError(
            "Aucun discours exploitable n'a été détecté dans l'enregistrement.",
            status_code=422,
            code="speech_not_detected",
        )
    return {
        "text": text,
        "duration_sec": round(duration, 3),
        "word_count": len(words),
        "words_per_minute": round(wpm, 1),
        "segments": payload.get("segments") or [],
    }


def synthesize_preview(
    *,
    reference_id: str,
    speed: float,
    text: str,
) -> bytes:
    response = http_requests.post(
        FISH_TTS_URL,
        headers={
            **_authorization_headers(),
            "Content-Type": "application/json",
            "model": "s2-pro",
        },
        json={
            "text": text,
            "reference_id": reference_id,
            "prosody": {
                "speed": speed,
                "volume": 0,
                "normalize_loudness": True,
            },
            "format": "mp3",
            "mp3_bitrate": 128,
            "normalize": True,
            "latency": "balanced",
        },
        timeout=(30, 180),
    )
    _raise_for_fish(response, "La génération de l'aperçu")
    return response.content
