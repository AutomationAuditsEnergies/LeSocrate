"""
Basic TTS service — voix de synthèse gratuite pour tests bout-en-bout.

Utilise gTTS (Google Text-to-Speech, API web gratuite). Sortie MP3 directe,
pas de dépendance ffmpeg/pydub. Voix naturelle acceptable pour du test.

Rate-limit possible côté Google (non-officielle). Pour du volume important,
retomber sur Fish Audio S2-Pro (qualité, payant).

Usage : 3ᵉ option dans l'étape 7 de `/formation-pipeline`, à côté de Fish
Audio (payant) et du mock silence (gratuit mais pas écoutable).
"""

import io
import re

from utils.logger import get_logger

logger = get_logger(__name__)

# gTTS limite chaque requête à ~5000 caractères. On garde une marge.
_CHUNK_MAX_CHARS = 4000


def _split_for_gtts(text: str, max_chars: int = _CHUNK_MAX_CHARS) -> list:
    """Découpe un texte long en chunks de max_chars caractères, en coupant
    préférentiellement sur des fins de phrases. Sinon sur des fins de
    propositions, sinon sur des espaces."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    # Tente d'abord par phrase (. ? !)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = []
    current = ""
    for s in sentences:
        if not s:
            continue
        if len(current) + len(s) + 1 > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            # Si une seule phrase est trop longue, la couper brutalement
            while len(s) > max_chars:
                # Cherche un espace proche de max_chars pour couper proprement
                cut = s.rfind(" ", 0, max_chars)
                if cut == -1:
                    cut = max_chars
                chunks.append(s[:cut].strip())
                s = s[cut:].strip()
            current = s
        else:
            current = (current + " " + s).strip() if current else s
    if current:
        chunks.append(current.strip())
    return [c for c in chunks if c]


def _speedup_mp3(audio_bytes: bytes, speed: float) -> bytes:
    """Accélère légèrement un MP3 gTTS pour se rapprocher d'un débit cours."""
    if speed <= 1.0:
        return audio_bytes
    try:
        from pydub import AudioSegment, effects

        audio = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
        sped = effects.speedup(
            audio,
            playback_speed=speed,
            chunk_size=150,
            crossfade=25,
        )
        output = io.BytesIO()
        sped.export(output, format="mp3", bitrate="128k")
        return output.getvalue()
    except Exception as exc:
        logger.warning(f"⚠️ gTTS speedup ignoré (speed={speed}) : {exc}")
        return audio_bytes


def convert_to_speech_basic(
    text: str,
    lang: str = "fr",
    speed: float | None = None,
    progress_callback=None,
    max_429_retries: int | None = None,
    retry_base_wait_sec: float | None = None,
) -> bytes:
    """
    Génère un MP3 à partir d'un texte via gTTS.

    Pour les textes longs, découpe en chunks et concatène les MP3 octet-
    par-octet. La concaténation naïve fonctionne car gTTS produit des MP3
    avec des paramètres cohérents entre appels.

    **Rate limit Google** : gTTS est une API non-officielle avec protections
    anti-abuse. Sur du gros volume, Google jette des 429 (Too Many Requests).
    On gère ça avec :
    - Sleep entre chaque chunk (`BASIC_TTS_CHUNK_DELAY_SEC`, défaut 1.5s)
    - Retry exponentiel sur 429 (`BASIC_TTS_MAX_429_RETRIES`, défaut 2)
      avec wait configuré par `BASIC_TTS_429_BASE_WAIT_SEC` (défaut 20s).

    Args:
        text: texte à synthétiser.
        lang: code de langue ISO 639 ('fr', 'en', 'es', ...).
        speed: facteur d'accélération optionnel. Si absent, lit
            BASIC_TTS_SPEED, défaut 1.28.

    Returns:
        bytes du MP3 complet.

    Raises:
        ImportError si gTTS n'est pas installé.
        gtts.tts.gTTSError si Google renvoie un 429 après tous les retries.
    """
    import os
    import time
    from gtts import gTTS
    from gtts.tts import gTTSError

    chunks = _split_for_gtts(text)
    # Google peut bloquer longtemps sur abuse. Les pipelines passent des
    # retries plus courts pour échouer lisiblement plutôt que rester invisibles.
    inter_chunk_delay = float(os.getenv("BASIC_TTS_CHUNK_DELAY_SEC", "3.0"))
    if max_429_retries is None:
        max_429_retries = int(os.getenv("BASIC_TTS_MAX_429_RETRIES", "2"))
    if retry_base_wait_sec is None:
        retry_base_wait_sec = float(os.getenv("BASIC_TTS_429_BASE_WAIT_SEC", "20"))
    speed = float(speed if speed is not None else os.getenv("BASIC_TTS_SPEED", "1.28"))

    logger.info(
        f"🎙️ gTTS : synthèse de {len(text)} caractères en {len(chunks)} chunk(s) "
        f"(delay={inter_chunk_delay}s, max_retries={max_429_retries}, speed={speed})"
    )

    parts = []
    for i, chunk in enumerate(chunks, start=1):
        if not chunk.strip():
            continue
        if progress_callback:
            progress_callback(f"gTTS chunk {i}/{len(chunks)} — synthèse")

        # Retry loop sur 429
        chunk_bytes = None
        last_error = None
        for attempt in range(max_429_retries + 1):
            try:
                tts = gTTS(text=chunk, lang=lang, slow=False)
                buf = io.BytesIO()
                tts.write_to_fp(buf)
                chunk_bytes = buf.getvalue()
                break
            except gTTSError as e:
                last_error = e
                err_str = str(e)
                is_429 = "429" in err_str or "Too Many Requests" in err_str
                if not is_429 or attempt >= max_429_retries:
                    raise
                wait = retry_base_wait_sec * (2 ** attempt)
                logger.warning(
                    f"⏳ gTTS chunk {i}/{len(chunks)} : 429 Google. "
                    f"Attente {wait}s avant retry {attempt + 1}/{max_429_retries}"
                )
                if progress_callback:
                    progress_callback(
                        f"gTTS chunk {i}/{len(chunks)} — 429 Google, "
                        f"attente {int(wait)}s avant retry {attempt + 1}/{max_429_retries}"
                    )
                time.sleep(wait)

        if chunk_bytes is None:
            raise last_error or RuntimeError(f"Chunk {i} échoué sans erreur identifiée")

        parts.append(chunk_bytes)
        logger.debug(f"   chunk {i}/{len(chunks)} ({len(chunk)} chars) → {len(chunk_bytes)} bytes MP3")
        if progress_callback:
            progress_callback(f"gTTS chunk {i}/{len(chunks)} — OK")

        # Sleep entre chunks (sauf après le dernier) pour ne pas saturer Google.
        # Sous eventlet+monkey_patch, time.sleep yield au scheduler.
        if i < len(chunks) and inter_chunk_delay > 0:
            time.sleep(inter_chunk_delay)

    if not parts:
        raise ValueError("Aucun chunk produit (texte vide ?)")

    return _speedup_mp3(b"".join(parts), speed)
