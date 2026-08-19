"""Calibrate one Fish Audio voice against the canonical 7,069-word course sample."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Callable

from repositories.ai_voice_repository import (
    complete_reference_calibration,
    fail_reference_calibration,
    get_platform_voice_settings,
    mark_reference_calibration_running,
)
from utils.logger import get_logger


logger = get_logger(__name__)

REFERENCE_PATH = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "voice_calibration_reference_fr.txt"
)
REFERENCE_EXPECTED_WORDS = 7069
_TTS_TAG_RE = re.compile(r"\[[^\[\]\n]{1,50}\]")


def count_reference_words(text: str) -> int:
    """Count spoken words exactly like the course TTS budget does."""

    cleaned = _TTS_TAG_RE.sub(" ", text or "")
    return len(cleaned.split())


def load_reference_text() -> tuple[str, str, int]:
    text = REFERENCE_PATH.read_text(encoding="utf-8").strip()
    word_count = count_reference_words(text)
    if word_count != REFERENCE_EXPECTED_WORDS:
        raise ValueError(
            "Le texte de calibration doit contenir exactement "
            f"{REFERENCE_EXPECTED_WORDS} mots parlés, reçu {word_count}."
        )
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return text, f"fr-course-half-v1-{digest}", word_count


def calibration_is_current(voice: dict[str, Any], reference_key: str) -> bool:
    try:
        measured_wpm = float(voice.get("measured_wpm") or 0.0)
        playback_speed = float(voice.get("playback_speed") or 1.0)
        calibrated_speed = float(voice.get("calibration_playback_speed") or 0.0)
    except (TypeError, ValueError):
        return False
    return (
        voice.get("calibration_status") == "completed"
        and voice.get("calibration_reference_key") == reference_key
        and int(voice.get("calibration_word_count") or 0) == REFERENCE_EXPECTED_WORDS
        and measured_wpm > 0
        and abs(playback_speed - calibrated_speed) <= 0.0001
    )


def calibrate_platform_voice(
    platform_id: int,
    *,
    synthesize: Callable[..., tuple[bytes, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Generate the reference audio and persist the voice-specific WPM."""

    voice = get_platform_voice_settings(int(platform_id))
    if not voice:
        raise ValueError("Aucune voix IA n'est associée à ce professeur.")
    text, reference_key, word_count = load_reference_text()
    if calibration_is_current(voice, reference_key):
        return {
            "status": "reused",
            "voice": voice,
            "reference_key": reference_key,
            "word_count": word_count,
            "duration_sec": float(voice["calibration_duration_sec"]),
            "words_per_minute": float(voice["measured_wpm"]),
        }

    center_account_id = int(voice["center_account_id"])
    voice_id = int(voice["id"])
    playback_speed = float(voice.get("playback_speed") or 1.0)
    mark_reference_calibration_running(
        center_account_id,
        voice_id,
        reference_key=reference_key,
    )
    if synthesize is None:
        from services.tts_service import convert_to_speech_with_timestamps

        synthesize = convert_to_speech_with_timestamps

    try:
        _audio, metadata = synthesize(
            text,
            voice_id=voice["fish_reference_id"],
            speed=playback_speed,
            format="mp3",
        )
        duration_sec = float((metadata or {}).get("audio_duration_sec") or 0.0)
        if duration_sec <= 0:
            raise ValueError("Fish Audio n'a renvoyé aucune durée de calibration.")
        words_per_minute = round(word_count / (duration_sec / 60.0), 3)
        if not 60.0 <= words_per_minute <= 300.0:
            raise ValueError(
                f"Le débit mesuré est incohérent ({words_per_minute:.1f} mots/min)."
            )
        updated = complete_reference_calibration(
            center_account_id,
            voice_id,
            reference_key=reference_key,
            word_count=word_count,
            duration_sec=duration_sec,
            measured_wpm=words_per_minute,
            playback_speed=playback_speed,
        )
        if not updated:
            raise ValueError("La voix a disparu pendant sa calibration.")
        logger.info(
            "VOICE_REFERENCE_CALIBRATION_COMPLETED platform_id=%s voice_id=%s "
            "words=%s duration_sec=%.3f wpm=%.3f speed=%.2f",
            platform_id,
            voice_id,
            word_count,
            duration_sec,
            words_per_minute,
            playback_speed,
        )
        return {
            "status": "completed",
            "voice": updated,
            "reference_key": reference_key,
            "word_count": word_count,
            "duration_sec": round(duration_sec, 3),
            "words_per_minute": words_per_minute,
        }
    except Exception as exc:
        fail_reference_calibration(center_account_id, voice_id, str(exc))
        raise
