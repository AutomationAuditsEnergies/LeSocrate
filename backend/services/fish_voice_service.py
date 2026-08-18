"""Fish Audio voice cloning, verification, ASR calibration and previews."""

from __future__ import annotations

import hashlib
import io
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
MAX_CONSENT_BYTES = 10 * 1024 * 1024
CONSENT_STATEMENT = (
    "Je confirme être propriétaire de cette voix ou disposer de son autorisation "
    "expresse pour créer et utiliser cette voix IA."
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
) -> float:
    if len(audio_bytes) > max_bytes:
        raise FishVoiceError(
            "Le fichier audio dépasse la taille autorisée.",
            status_code=413,
            code="audio_too_large",
        )
    duration = audio_duration_seconds(audio_bytes, filename)
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
