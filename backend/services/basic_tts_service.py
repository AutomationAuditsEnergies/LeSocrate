"""
Basic TTS service — voix de synthèse gratuite pour tests bout-en-bout.

Utilise edge-tts (Microsoft Edge Text-to-Speech, sans clé API). Voix
neurales fr-FR, beaucoup plus tolérantes que gTTS sur le volume (gTTS =
API non officielle Google Translate, bloque autour de 50k chars/h).

Voix françaises disponibles (configurable via `EDGE_TTS_VOICE`) :
- fr-FR-DeniseNeural (féminine, défaut)
- fr-FR-HenriNeural (masculine)
- fr-FR-VivienneMultilingualNeural (féminine, multilingue)
- fr-FR-RemyMultilingualNeural (masculine, multilingue)

Edge-tts utilise asyncio + websockets en interne. Pour rester compatible
avec l'eventlet+monkey_patch du serveur Flask/SocketIO, on encapsule la
coroutine dans `eventlet.tpool.execute` qui la fait tourner dans un vrai
thread isolé. Le greenlet appelant attend sans bloquer le hub.

Usage : 3ᵉ option dans l'étape 7 de `/formation-pipeline`, à côté de Fish
Audio (payant) et du mock silence (gratuit mais pas écoutable).
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import re
import time

from utils.logger import get_logger

logger = get_logger(__name__)

# Edge-tts gère du long texte mais on chunke pour le progress reporting
# et l'isolation des erreurs réseau sur de gros volumes.
_CHUNK_MAX_CHARS = 4000
_DEFAULT_VOICE = "fr-FR-DeniseNeural"


def _skip_id3v2(audio_bytes: bytes) -> int:
    """Retourne l'offset après un header ID3v2, s'il existe."""
    if len(audio_bytes) < 10 or audio_bytes[:3] != b"ID3":
        return 0
    size = 0
    for b in audio_bytes[6:10]:
        size = (size << 7) | (b & 0x7F)
    footer = 10 if (audio_bytes[5] & 0x10) else 0
    return min(len(audio_bytes), 10 + size + footer)


def _strip_id3v1(audio_bytes: bytes) -> bytes:
    if len(audio_bytes) >= 128 and audio_bytes[-128:-125] == b"TAG":
        return audio_bytes[:-128]
    return audio_bytes


def concat_mp3_bytes(parts: list[bytes]) -> bytes:
    """Concatène des MP3 Edge TTS en gardant un seul header metadata.

    Edge TTS renvoie des MP3 frame-compatible entre appels, mais chaque chunk
    peut porter son propre header ID3. Des headers ID3 au milieu du flux font
    dérailler les durées côté navigateur/WaveSurfer. On garde le premier
    header éventuel, puis on concatène les frames audio des chunks suivants.
    """
    cleaned = []
    for idx, part in enumerate(parts):
        if not part:
            continue
        data = _strip_id3v1(bytes(part))
        if idx > 0:
            data = data[_skip_id3v2(data):]
        if data:
            cleaned.append(data)
    if not cleaned:
        raise ValueError("Aucun chunk MP3 à concaténer")
    return b"".join(cleaned)


def _split_for_tts(text: str, max_chars: int = _CHUNK_MAX_CHARS) -> list:
    """Découpe un texte long en chunks de max_chars caractères, en coupant
    préférentiellement sur des fins de phrases. Sinon sur des fins de
    propositions, sinon sur des espaces."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

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
            while len(s) > max_chars:
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


def _speed_to_rate(speed: float) -> str:
    """Convertit speed=1.28 (multiplicateur) en rate edge-tts '+28%'."""
    pct = int(round((speed - 1.0) * 100))
    return f"{pct:+d}%"


async def _synthesize_chunk_async(text: str, voice: str, rate: str, volume: str) -> bytes:
    """Synthèse d'un chunk via edge-tts, retourne les bytes MP3."""
    import edge_tts

    communicate = edge_tts.Communicate(text, voice=voice, rate=rate, volume=volume)
    audio_chunks = []
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            audio_chunks.append(chunk["data"])
    return b"".join(audio_chunks)


def _synthesize_chunk_sync(text: str, voice: str, rate: str, volume: str) -> bytes:
    """Wrapper synchrone : asyncio.run dans un thread isolé via tpool."""
    import eventlet.tpool

    def _runner():
        return asyncio.run(_synthesize_chunk_async(text, voice, rate, volume))

    return eventlet.tpool.execute(_runner)


def convert_to_speech_basic(
    text: str,
    lang: str = "fr",
    speed: float | None = None,
    progress_callback=None,
    max_429_retries: int | None = None,
    retry_base_wait_sec: float | None = None,
    parallel_workers: int | None = None,
    volume: str | None = None,
) -> bytes:
    """
    Génère un MP3 à partir d'un texte via edge-tts.

    Pour les textes longs, découpe en chunks et concatène les frames MP3 en
    retirant les headers ID3 intermédiaires. Les paramètres audio Edge TTS
    restent cohérents entre appels.

    Edge-tts est nettement plus tolérant que gTTS sur le volume, mais on
    garde le retry exponentiel pour les erreurs réseau transitoires.

    Args:
        text: texte à synthétiser.
        lang: code de langue (conservé pour compat — la voix par défaut
            est fr-FR-DeniseNeural, override via EDGE_TTS_VOICE).
        speed: facteur d'accélération multiplicatif. Si absent, lit
            BASIC_TTS_SPEED, défaut 1.0 (voix neurales naturelles).
        parallel_workers: nombre de chunks Edge TTS à synthétiser en parallèle.
            Par défaut, reste séquentiel. À utiliser uniquement pour les
            pipelines de test, car Edge TTS peut throttler si on monte trop haut.
        volume: volume Edge TTS (`+0%` par défaut). Utilisé notamment pour
            générer du filler muet compatible avec les MP3 Edge.

    Returns:
        bytes du MP3 complet.

    Raises:
        ImportError si edge-tts n'est pas installé.
        Exception si tous les retries échouent.
    """
    chunks = _split_for_tts(text)

    inter_chunk_delay = float(os.getenv("BASIC_TTS_CHUNK_DELAY_SEC", "0.5"))
    if max_429_retries is None:
        max_429_retries = int(os.getenv("BASIC_TTS_MAX_429_RETRIES", "3"))
    if retry_base_wait_sec is None:
        retry_base_wait_sec = float(os.getenv("BASIC_TTS_429_BASE_WAIT_SEC", "5"))
    speed = float(speed if speed is not None else os.getenv("BASIC_TTS_SPEED", "1.0"))
    try:
        parallel_workers = int(parallel_workers or 1)
    except (TypeError, ValueError):
        parallel_workers = 1
    parallel_workers = max(1, min(parallel_workers, len(chunks) or 1))

    voice = os.getenv("EDGE_TTS_VOICE", _DEFAULT_VOICE)
    rate = _speed_to_rate(speed)
    volume = volume or os.getenv("EDGE_TTS_VOLUME", "+0%")

    logger.info(
        f"🎙️ edge-tts : synthèse de {len(text)} caractères en {len(chunks)} chunk(s) "
        f"(voice={voice}, rate={rate}, volume={volume}, max_retries={max_429_retries})"
    )

    def _synthesize_one(i: int, chunk: str) -> bytes:
        chunk_bytes = None
        last_error = None
        for attempt in range(max_429_retries + 1):
            try:
                chunk_bytes = _synthesize_chunk_sync(chunk, voice, rate, volume)
                if not chunk_bytes:
                    raise RuntimeError("edge-tts a renvoyé 0 bytes")
                return chunk_bytes
            except Exception as e:
                last_error = e
                if attempt >= max_429_retries:
                    raise
                wait = retry_base_wait_sec * (2 ** attempt)
                err_short = str(e)[:200]
                logger.warning(
                    f"⏳ edge-tts chunk {i}/{len(chunks)} a échoué : {err_short}. "
                    f"Attente {wait}s avant retry {attempt + 1}/{max_429_retries}"
                )
                if progress_callback:
                    progress_callback(
                        f"edge-tts chunk {i}/{len(chunks)} — erreur, "
                        f"attente {int(wait)}s avant retry {attempt + 1}/{max_429_retries}"
                    )
                time.sleep(wait)
        raise last_error or RuntimeError(f"Chunk {i} échoué sans erreur identifiée")

    prepared_chunks = [(i, chunk) for i, chunk in enumerate(chunks, start=1) if chunk.strip()]
    if not prepared_chunks:
        raise ValueError("Aucun chunk produit (texte vide ?)")

    parts_by_index = {}

    if parallel_workers > 1 and len(prepared_chunks) > 1:
        logger.info(
            f"⚡ edge-tts test rapide : {len(prepared_chunks)} chunk(s) "
            f"avec {parallel_workers} worker(s)"
        )
        if progress_callback:
            progress_callback(
                f"edge-tts parallèle — {len(prepared_chunks)} chunks / {parallel_workers} workers"
            )
        with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
            futures = {}
            for i, chunk in prepared_chunks:
                if progress_callback:
                    progress_callback(f"edge-tts chunk {i}/{len(chunks)} — synthèse")
                futures[executor.submit(_synthesize_one, i, chunk)] = (i, chunk)
            for future in as_completed(futures):
                i, chunk = futures[future]
                chunk_bytes = future.result()
                parts_by_index[i] = chunk_bytes
                logger.debug(
                    f"   chunk {i}/{len(chunks)} ({len(chunk)} chars) → {len(chunk_bytes)} bytes MP3"
                )
                if progress_callback:
                    progress_callback(f"edge-tts chunk {i}/{len(chunks)} — OK")
    else:
        for i, chunk in prepared_chunks:
            if progress_callback:
                progress_callback(f"edge-tts chunk {i}/{len(chunks)} — synthèse")

            chunk_bytes = _synthesize_one(i, chunk)
            parts_by_index[i] = chunk_bytes
            logger.debug(
                f"   chunk {i}/{len(chunks)} ({len(chunk)} chars) → {len(chunk_bytes)} bytes MP3"
            )
            if progress_callback:
                progress_callback(f"edge-tts chunk {i}/{len(chunks)} — OK")

            # Petit délai entre chunks pour rester courtois (edge-tts est tolérant
            # mais on évite de saturer le service Microsoft). Le mode parallèle
            # est réservé au bouton test rapide, donc il saute ce délai séquentiel.
            if i < prepared_chunks[-1][0] and inter_chunk_delay > 0:
                time.sleep(inter_chunk_delay)

    parts = [parts_by_index[i] for i, _chunk in prepared_chunks if i in parts_by_index]
    if not parts:
        raise ValueError("Aucun chunk produit (texte vide ?)")

    return concat_mp3_bytes(parts)
