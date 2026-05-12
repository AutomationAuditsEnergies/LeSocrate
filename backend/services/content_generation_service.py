"""
Service de génération de contenu TTS-direct.

Pipeline par dossier (= 1 journée de formation) :
  1. Extraction automatique de 6 sous-parties depuis le programme (1 appel Claude)
  2. Pour chaque sous-partie : Passe 1 → Passe 2 → Passe 3 (~5 000 mots chacune)
  3. Total ~90 000 mots TTS-ready → sauvegardé comme document .txt dans le dossier

Checkpointing : chaque segment complété est sauvegardé en DB immédiatement.
En cas d'interruption, la génération reprend au segment suivant non complété.
"""

import io
import hashlib
import os
import re
import json
import threading
import time
import uuid as uuid_mod

from database.db import get_db_connection
from utils.anthropic_client import (
    AnthropicAPIError,
    AnthropicRateLimitError,
    default_model,
    post_message as _llm_post,
)
from utils.logger import get_logger

logger = get_logger(__name__)

CLAUDE_MODEL = default_model()
NUM_SUB_PARTS = 6
_COURSE_START_SILENCE_SECONDS = 17
_TTS_REFERENCE_WPM_AT_095 = 192
_DEFAULT_TTS_SPEED = 0.90
_DEFAULT_TTS_LOCAL_MAX_SPEEDUP = 1.0
_DEFAULT_TTS_PREFLIGHT_SAFETY = 0.96
_SENTENCE_END_RE = re.compile(r"[.!?…][\"'»”’)\]]*$")
_CARRYOVER_INTRO = (
    "Avant d'entrer dans la suite de ce cours, on reprend le point que nous "
    "n'avons pas terminé au cours dernier. On le pose proprement, puis on "
    "enchaînera naturellement avec le programme prévu."
)
_CARRYOVER_COLUMNS_READY = False
_FISHAUDIO_TAG_RE = re.compile(r"\[[^\[\]\n]{1,50}\]")
_EDGE_TTS_FAST_CACHE = {}
_EDGE_TTS_FAST_CACHE_LOCK = threading.Lock()


_MP3_BITRATES_KBPS = {
    # key = (mpeg_version, layer)
    # version: 1 = MPEG-1, 2 = MPEG-2, 2.5 = MPEG-2.5
    # layer: 1 = Layer I, 2 = Layer II, 3 = Layer III
    (1, 1): [None, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
    (1, 2): [None, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
    (1, 3): [None, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    (2, 1): [None, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
    (2, 2): [None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
    (2, 3): [None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}

_MP3_SAMPLE_RATES = {
    1: [44100, 48000, 32000],
    2: [22050, 24000, 16000],
    2.5: [11025, 12000, 8000],
}


def _basic_tts_pipeline_retry_kwargs() -> dict:
    """Retry gTTS pour les pipelines — backoff exponentiel sur 429 Google."""
    try:
        max_retries = int(os.getenv("BASIC_TTS_PIPELINE_MAX_429_RETRIES", "3"))
    except ValueError:
        max_retries = 3
    try:
        base_wait = float(os.getenv("BASIC_TTS_PIPELINE_429_BASE_WAIT_SEC", "30"))
    except ValueError:
        base_wait = 30.0
    return {
        "max_429_retries": max(0, max_retries),
        "retry_base_wait_sec": max(1.0, base_wait),
    }


def _edge_tts_fast_workers() -> int:
    """Parallélisme Edge TTS pour le bouton test rapide uniquement."""
    try:
        workers = int(os.getenv("EDGE_TTS_FAST_TEST_WORKERS", "3"))
    except (TypeError, ValueError):
        workers = 3
    return max(1, min(workers, 6))


def _edge_tts_fast_cache_enabled() -> bool:
    value = (os.getenv("EDGE_TTS_FAST_TEST_CACHE", "true") or "").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _edge_tts_fast_cache_key(text: str) -> str:
    payload = json.dumps(
        {
            "text": text,
            "voice": os.getenv("EDGE_TTS_VOICE", "fr-FR-DeniseNeural"),
            "speed": os.getenv("BASIC_TTS_SPEED", "1.0"),
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _clear_edge_tts_fast_cache_for_tests():
    with _EDGE_TTS_FAST_CACHE_LOCK:
        _EDGE_TTS_FAST_CACHE.clear()


# ─── Texte mock pour les tests ───────────────────────────────────────────────

_MOCK_PASSE_LABELS = ["fondation", "expansion", "enrichissement"]
_MOCK_PHRASES = [
    "Ce module aborde les fondamentaux essentiels de cette thématique.",
    "Chaque notion est construite progressivement pour faciliter l'assimilation.",
    "Les exemples concrets viennent illustrer la théorie à chaque étape.",
    "Le formateur insiste sur les points clés à retenir pour la pratique professionnelle.",
    "Des mises en situation permettront de consolider les apprentissages.",
    "Il est important de bien comprendre le contexte avant d'aller plus loin.",
    "Les compétences acquises ici seront réutilisées tout au long de la formation.",
    "Prenez le temps d'assimiler chaque notion avant de passer à la suivante.",
]

def _generate_mock_text(passe, sub_part_name, sub_idx):
    """Génère ~220 mots de texte factice structuré pour les tests (sans appel Claude)."""
    label = _MOCK_PASSE_LABELS[passe - 1]
    lines = [
        f"Bonjour et bienvenue dans cette partie consacrée à {sub_part_name}.",
        f"Nous abordons ici la {label} de ce module. [MODE TEST — Passe {passe}/3 — Sous-partie {sub_idx + 1}]",
        "",
    ]
    # Répéter les phrases pour atteindre ~200 mots
    for i, phrase in enumerate(_MOCK_PHRASES * 3):
        lines.append(f"{phrase} ({sub_part_name}, itération {i + 1}.)")
    lines += [
        "",
        f"Voilà pour cette passe {passe} dédiée à {sub_part_name}.",
        f"Nous avons couvert l'essentiel de la {label}. Passons à la suite.",
    ]
    return "\n".join(lines)


def _env_float(name, default, min_value=None, max_value=None):
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        logger.warning(f"⚠️ {name} invalide, fallback {default}")
        return default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def _course_tts_speed():
    return _env_float("FORMATION_TTS_SPEED", _DEFAULT_TTS_SPEED, min_value=0.5, max_value=2.0)


def _course_local_max_speedup():
    return _env_float(
        "FORMATION_TTS_LOCAL_MAX_SPEEDUP",
        _DEFAULT_TTS_LOCAL_MAX_SPEEDUP,
        min_value=1.0,
        max_value=1.5,
    )


def _course_preflight_safety():
    return _env_float(
        "FORMATION_TTS_PREFLIGHT_SAFETY",
        _DEFAULT_TTS_PREFLIGHT_SAFETY,
        min_value=0.80,
        max_value=1.05,
    )


def _estimated_words_budget_for_course(target_sec, api_speed):
    voice_minutes = max(0, target_sec - _COURSE_START_SILENCE_SECONDS) / 60
    estimated_wpm = _TTS_REFERENCE_WPM_AT_095 * (api_speed / 0.95)
    return int(voice_minutes * estimated_wpm * _course_preflight_safety())


def _estimated_audio_seconds_for_words(word_count, api_speed):
    """Durée audio estimée pour un nombre de mots à une vitesse Fish Audio donnée.

    Inclut le silence de début (`_COURSE_START_SILENCE_SECONDS`) qui est ajouté en
    aval par le pipeline TTS. Approximation linéaire — calibration à valider en prod
    (cf. `memoire/02-problemes/pipeline-52-jours-risques-residuels.md`, R1).
    """
    if word_count <= 0:
        return _COURSE_START_SILENCE_SECONDS
    estimated_wpm = _TTS_REFERENCE_WPM_AT_095 * (api_speed / 0.95)
    voice_seconds = (word_count / estimated_wpm) * 60
    return voice_seconds + _COURSE_START_SILENCE_SECONDS


def _strip_tts_tags_for_sync(text: str) -> str:
    """Use clean text for slide-synced word coordinates in V1."""
    cleaned = _FISHAUDIO_TAG_RE.sub("", text or "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n[ \t]+", "\n", cleaned)
    return cleaned.strip()


def _skip_id3v2(audio_bytes: bytes) -> int:
    """Return byte offset after an ID3v2 header, if present."""
    if len(audio_bytes) < 10 or audio_bytes[:3] != b"ID3":
        return 0
    size = 0
    for b in audio_bytes[6:10]:
        size = (size << 7) | (b & 0x7F)
    footer = 10 if (audio_bytes[5] & 0x10) else 0
    return min(len(audio_bytes), 10 + size + footer)


def _mp3_duration_seconds_no_ffprobe(audio_bytes: bytes) -> float:
    """Estimate MP3 duration by summing MPEG frame durations.

    This avoids pydub/ffprobe in Azure App Service, where ffmpeg binaries are
    not installed. It is used only for already-encoded MP3 bytes from Edge TTS
    and the bundled silence asset.
    """
    data = audio_bytes or b""
    i = _skip_id3v2(data)
    duration = 0.0
    frames = 0
    limit = len(data) - 4

    while i < limit:
        b1, b2, b3, b4 = data[i], data[i + 1], data[i + 2], data[i + 3]
        if b1 != 0xFF or (b2 & 0xE0) != 0xE0:
            i += 1
            continue

        version_bits = (b2 >> 3) & 0x03
        layer_bits = (b2 >> 1) & 0x03
        bitrate_idx = (b3 >> 4) & 0x0F
        sample_rate_idx = (b3 >> 2) & 0x03
        padding = (b3 >> 1) & 0x01

        if version_bits == 1 or layer_bits == 0 or bitrate_idx in (0, 15) or sample_rate_idx == 3:
            i += 1
            continue

        version = {3: 1, 2: 2, 0: 2.5}.get(version_bits)
        layer = {3: 1, 2: 2, 1: 3}.get(layer_bits)
        bitrate_kbps = _MP3_BITRATES_KBPS.get((1 if version == 1 else 2, layer), [None])[bitrate_idx]
        sample_rate = _MP3_SAMPLE_RATES[version][sample_rate_idx]
        if not bitrate_kbps or not sample_rate:
            i += 1
            continue

        bitrate = bitrate_kbps * 1000
        if layer == 1:
            samples_per_frame = 384
            frame_size = int(((12 * bitrate) / sample_rate + padding) * 4)
        elif layer == 2:
            samples_per_frame = 1152
            frame_size = int((144 * bitrate) / sample_rate + padding)
        else:
            samples_per_frame = 1152 if version == 1 else 576
            coeff = 144 if version == 1 else 72
            frame_size = int((coeff * bitrate) / sample_rate + padding)

        if frame_size <= 4:
            i += 1
            continue

        duration += samples_per_frame / sample_rate
        frames += 1
        i += frame_size

    if frames == 0:
        raise ValueError("Durée MP3 impossible à mesurer sans ffprobe (aucune frame MPEG trouvée)")
    return duration


def _silent_mp3_approx_no_ffmpeg(duration_sec: float) -> tuple[bytes, float]:
    """Return bundled silent MP3 bytes repeated close to the requested duration."""
    from services.playlist_tts_service import _generate_silence_mp3

    if duration_sec <= 0:
        return b"", 0.0
    one_sec = _generate_silence_mp3(1)
    one_sec_duration = _mp3_duration_seconds_no_ffprobe(one_sec)
    repeat = max(1, int(round(duration_sec / one_sec_duration)))
    return one_sec * repeat, one_sec_duration * repeat


def _word_slice(text: str, start: int, end: int) -> str:
    words = (text or "").split()
    start = max(0, min(len(words), start))
    end = max(start, min(len(words), end))
    return " ".join(words[start:end]).strip()


def _slides_for_bloc(slides: list, bloc: dict) -> list:
    bloc_start = int(bloc.get("start_w") or 0)
    bloc_end = int(bloc.get("end_w") or bloc_start)
    raw_relevant = []
    seen = set()

    for slide_idx, slide in enumerate(slides or []):
        source_ref = slide.get("source_ref") or {}
        try:
            start = int(source_ref.get("word_start"))
            end = int(source_ref.get("word_end"))
        except (TypeError, ValueError):
            continue
        if end <= bloc_start or start >= bloc_end:
            continue
        slide_id = slide.get("slide_id")
        if not slide_id or slide_id in seen:
            continue
        seen.add(slide_id)
        raw_relevant.append({
            "slide_id": slide_id,
            "slide_index": slide_idx,
            "source_word_start": start,
            "source_word_end": end,
            "word_start": max(bloc_start, start),
            "word_end": min(bloc_end, end),
        })

    raw_relevant.sort(key=lambda item: (item["source_word_start"], item["slide_index"]))
    relevant = []
    idx = 0
    while idx < len(raw_relevant):
        item = raw_relevant[idx]
        group = [item]
        idx += 1
        while (
            idx < len(raw_relevant)
            and raw_relevant[idx]["source_word_start"] == item["source_word_start"]
            and raw_relevant[idx]["source_word_end"] == item["source_word_end"]
        ):
            group.append(raw_relevant[idx])
            idx += 1

        if len(group) == 1:
            relevant.append(group[0])
            continue

        interval_start = max(bloc_start, item["source_word_start"])
        interval_end = min(bloc_end, item["source_word_end"])
        span = max(1, interval_end - interval_start)
        for group_idx, grouped in enumerate(group):
            start = interval_start + round(group_idx * span / len(group))
            end = interval_start + round((group_idx + 1) * span / len(group))
            if end <= start:
                continue
            clone = dict(grouped)
            clone["word_start"] = start
            clone["word_end"] = end
            relevant.append(clone)

    relevant.sort(key=lambda item: item["word_start"])
    if relevant and relevant[0]["word_start"] > bloc_start:
        relevant[0]["word_start"] = bloc_start
    elif relevant and relevant[0]["word_start"] < bloc_start:
        relevant[0]["word_start"] = bloc_start
    return relevant


# ── Runtime fit Edge TTS : sub-chunking adaptatif + frontières naturelles ───
# Plafonds de mots par chunk en fonction du temps restant dans le bloc.
# Plus on s'approche de la cible, plus les chunks doivent être petits pour
# pouvoir s'arrêter pile à la limite sans dépasser.
_MAX_CHUNK_WORDS_HIGH = 600          # remaining > 12 min : chunks confortables
_MAX_CHUNK_WORDS_MID = 300           # 5–12 min : on resserre
_MAX_CHUNK_WORDS_LOW = 150           # 2–5 min : phrase par phrase
_MAX_CHUNK_WORDS_TINY = 60           # < 2 min : micro-chunks pour viser la marge
_REMAINING_HIGH_SEC = 12 * 60
_REMAINING_MID_SEC = 5 * 60
_REMAINING_LOW_SEC = 2 * 60
_REMAINING_TINY_SEC = 25

# Edge TTS lit autour de 170 mots/min en français rate=+0%. Bootstrap pour
# l'estimation runtime, ensuite on calcule un wpm réel observé.
_BOOTSTRAP_WPM_EDGE_TTS = 170.0

# Tolérance d'arrondi sur la durée mesurée (frames MP3 = ~26 ms).
_TOLERANCE_OVERFLOW_SEC = 2.0

# Marge cible en fin de bloc pour une conclusion humaine et récapitulative.
_DEFAULT_CONCLUSION_MARGIN_SEC = 150

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")


def _max_chunk_words_for_remaining(remaining_sec: float) -> int:
    """Plafond de mots adaptatif selon la marge restante avant target_sec - margin.

    Retourne 0 uniquement dans les toutes dernières secondes. Avant ça, on
    continue avec des micro-chunks pour éviter un arrêt trop tôt (ex: 41:40
    sur un créneau de 45 min).
    """
    if remaining_sec >= _REMAINING_HIGH_SEC:
        return _MAX_CHUNK_WORDS_HIGH
    if remaining_sec >= _REMAINING_MID_SEC:
        return _MAX_CHUNK_WORDS_MID
    if remaining_sec >= _REMAINING_LOW_SEC:
        return _MAX_CHUNK_WORDS_LOW
    if remaining_sec >= _REMAINING_TINY_SEC:
        return _MAX_CHUNK_WORDS_TINY
    return 0


def _split_text_natural(text: str, max_words: int) -> list:
    """Découpe `text` en sous-segments ≤ max_words sur frontières naturelles.

    Règles strictes (validées par l'utilisateur) :
    1. Découpe d'abord par paragraphes (`\\n\\n`).
    2. Un paragraphe ≤ max_words forme un sous-segment.
    3. Sinon, découpe par phrases ; on accumule les phrases tant que ≤ max_words.
    4. Si une phrase isolée dépasse max_words, on la garde **entière** —
       on ne split jamais au milieu d'une phrase juste pour respecter le seuil.
    """
    if max_words <= 0 or not text or not text.strip():
        return [text] if (text and text.strip()) else []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    sub_chunks = []

    for para in paragraphs:
        para_words = para.split()
        if len(para_words) <= max_words:
            sub_chunks.append(para)
            continue

        # Paragraphe trop gros : on découpe par phrases sans jamais splitter une phrase.
        sentences = _SENTENCE_SPLIT_RE.split(para)
        current = []
        current_count = 0

        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            sent_count = len(sent.split())

            if not current:
                # Toujours commencer un sous-chunk avec la phrase, même si elle dépasse seule.
                current = [sent]
                current_count = sent_count
                continue

            if current_count + sent_count <= max_words:
                current.append(sent)
                current_count += sent_count
            else:
                sub_chunks.append(" ".join(current))
                current = [sent]
                current_count = sent_count

        if current:
            sub_chunks.append(" ".join(current))

    return sub_chunks


def _split_chunk_for_runtime_fit(chunk: dict, max_words: int) -> list:
    """Découpe un chunk slide en sous-chunks naturels en propageant `slide_id`.

    Recalcule `word_start` / `word_end` en avançant un curseur depuis le
    `word_start` original. Les sous-chunks restent attachés à la même slide
    parente — le frontend affiche cette slide pendant tout le segment, peu
    importe combien d'appels Edge TTS ont été nécessaires.
    """
    text = chunk.get("text") or ""
    if max_words <= 0 or not text.strip():
        return [chunk]

    if len(text.split()) <= max_words:
        return [chunk]

    sub_texts = _split_text_natural(text, max_words)
    if len(sub_texts) <= 1:
        return [chunk]

    word_start = int(chunk.get("word_start") or 0)
    sub_chunks = []
    cursor = word_start

    for sub_text in sub_texts:
        sub_count = len(sub_text.split())
        sub_chunks.append({
            "slide_id": chunk.get("slide_id"),
            "word_start": cursor,
            "word_end": cursor + sub_count,
            "text": sub_text,
        })
        cursor += sub_count

    return sub_chunks


def _smaller_runtime_fit_word_limit(chunk: dict, available_sec: float, observed_wpm: float) -> int:
    words = len((chunk.get("text") or "").split())
    if words <= 1 or available_sec <= 0 or observed_wpm <= 0:
        return 0
    fit_words = int((available_sec * observed_wpm / 60.0) * 0.80)
    if fit_words >= words:
        fit_words = words - 1
    return max(8, min(words - 1, fit_words))


def _build_slide_audio_chunks(bloc: dict, slides: list) -> list:
    """Partition a course bloc into text chunks driven by slide start markers."""
    bloc_start = int(bloc.get("start_w") or 0)
    bloc_end = int(bloc.get("end_w") or bloc_start)
    bloc_text = bloc.get("text") or ""
    bloc_words = bloc_text.split()
    if not bloc_words:
        return []

    relevant = _slides_for_bloc(slides, bloc)
    if not relevant:
        return [{
            "slide_id": None,
            "word_start": bloc_start,
            "word_end": bloc_end,
            "text": bloc_text,
        }]

    chunks = []
    for idx, item in enumerate(relevant):
        start_w = item["word_start"]
        next_start = relevant[idx + 1]["word_start"] if idx + 1 < len(relevant) else bloc_end
        end_w = max(start_w, min(bloc_end, next_start))
        if end_w <= start_w:
            continue
        local_start = start_w - bloc_start
        local_end = end_w - bloc_start
        text = _word_slice(bloc_text, local_start, local_end)
        if text:
            chunks.append({
                "slide_id": item["slide_id"],
                "word_start": start_w,
                "word_end": end_w,
                "text": text,
            })
    return chunks


def _merge_adjacent_slide_timings(timings: list) -> list:
    merged = []
    for item in timings:
        if not item.get("slide_id"):
            continue
        if (
            merged
            and merged[-1].get("slide_id") == item.get("slide_id")
            and merged[-1].get("audio_filename") == item.get("audio_filename")
            and abs(float(merged[-1].get("end_time") or 0) - float(item.get("start_time") or 0)) < 0.05
        ):
            merged[-1]["end_time"] = item.get("end_time")
            merged[-1]["word_end"] = item.get("word_end")
            merged[-1]["duration"] = round(
                float(merged[-1]["end_time"]) - float(merged[-1]["start_time"]),
                3,
            )
            continue
        merged.append(item)
    return merged


_DEFAULT_CONCLUSION_TEMPLATE = (
    "Avant de s'arrêter, on prend un vrai temps de recul. "
    "On vient de traverser une séquence dense, et l'objectif maintenant est de remettre de l'ordre "
    "dans les idées importantes, pour repartir avec une vision claire et utilisable. "
    "Ce qu'il faut retenir, c'est d'abord la logique générale du cours : comprendre la situation, "
    "repérer les points d'attention, puis transformer ces repères en gestes professionnels concrets. "
    "Gardez aussi en tête que les exemples vus pendant cette partie ne sont pas seulement des détails : "
    "ils servent à reconnaître plus vite les bons réflexes quand une situation similaire se présente. "
    "Pour la suite, l'idée sera de s'appuyer sur ces bases, de les rendre plus naturelles, puis de les "
    "appliquer avec davantage de précision."
)
_FALLBACK_CONCLUSION_TEMPLATE = (
    "On s'arrête ici pour cette partie. Retenez surtout le fil général : on a posé les repères, "
    "on les a reliés à des situations concrètes, et on reprendra ensuite à partir de cette base."
)


def _trim_sentence(sentence: str, max_chars: int = 240) -> str:
    sentence = re.sub(r"\s+", " ", sentence or "").strip()
    if len(sentence) <= max_chars:
        return sentence
    cut = sentence.rfind(",", 0, max_chars)
    if cut < 80:
        cut = sentence.rfind(" ", 0, max_chars)
    if cut < 80:
        cut = max_chars
    return sentence[:cut].strip().rstrip(",;:") + "."


def _pick_conclusion_anchors(text: str, max_anchors: int = 6) -> list:
    cleaned = _strip_tts_tags_for_sync(text or "")
    sentences = [
        _trim_sentence(s)
        for s in _SENTENCE_SPLIT_RE.split(cleaned)
        if len((s or "").split()) >= 8
    ]
    if not sentences:
        return []

    # Échantillonnage début / milieu / fin pour refléter le cours complet sans
    # dépendre d'un appel LLM dans la boucle TTS.
    if len(sentences) <= max_anchors:
        return sentences
    positions = [
        round(i * (len(sentences) - 1) / max(1, max_anchors - 1))
        for i in range(max_anchors)
    ]
    anchors = []
    seen = set()
    for pos in positions:
        sentence = sentences[int(pos)]
        key = sentence.lower()
        if key not in seen:
            anchors.append(sentence)
            seen.add(key)
    return anchors


def _limit_text_words_natural(text: str, max_words: int) -> str:
    if max_words <= 0:
        return text.strip()
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]
    if not sentences:
        return text.strip()
    selected = []
    total = 0
    for sentence in sentences:
        count = len(sentence.split())
        if selected and total + count > max_words:
            break
        selected.append(sentence)
        total += count
    return " ".join(selected or [sentences[0]]).strip()


def _compact_words(text: str, max_words: int) -> str:
    words = _strip_tts_tags_for_sync(text or "").split()
    if max_words <= 0 or len(words) <= max_words:
        return " ".join(words).strip()
    return " ".join(words[:max_words]).strip()


def _tail_words(text: str, max_words: int) -> str:
    words = _strip_tts_tags_for_sync(text or "").split()
    if max_words <= 0 or len(words) <= max_words:
        return " ".join(words).strip()
    return " ".join(words[-max_words:]).strip()


def _extract_llm_json(raw: str) -> dict:
    raw = (raw or "").strip().replace("```json", "```")
    if "```" in raw:
        raw = max(raw.split("```"), key=len).strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        raw = match.group(0)
    return json.loads(raw)


def _course_ai_stop_decision_enabled() -> bool:
    value = (os.getenv("COURSE_AI_STOP_DECISION", "true") or "").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _course_ai_stop_window_sec() -> float:
    return _env_float("COURSE_AI_STOP_WINDOW_SEC", 420, min_value=60, max_value=900)


def _ai_should_defer_chunk_before_conclusion(
    *,
    bloc_number: int,
    remaining_before_conclusion_sec: float,
    consumed_chunks: list,
    candidate_chunk: dict,
    next_chunk: dict | None = None,
    model: str | None = None,
) -> tuple[bool, str]:
    """Ask the LLM whether the next chunk should be deferred before closing.

    This is intentionally used only inside the end-of-block window. The goal is
    to avoid starting a new pedagogical section just before the closing, without
    relying on keyword heuristics.
    """
    if not _course_ai_stop_decision_enabled():
        return False, ""

    candidate_text = (candidate_chunk.get("text") or "").strip()
    if len(candidate_text.split()) < 35:
        return False, ""

    consumed_text = "\n\n".join(
        (chunk.get("text") or "").strip()
        for chunk in (consumed_chunks or [])
        if (chunk.get("text") or "").strip()
    )
    if len(consumed_text.split()) < 120:
        return False, ""

    prompt = f"""Tu es monteur pédagogique pour un cours audio horodaté.

On approche de la conclusion du bloc {bloc_number}/7. Il reste environ
{int(max(0, remaining_before_conclusion_sec))} secondes avant la marge réservée
à la conclusion.

TA MISSION :
Décider si le PROCHAIN PASSAGE doit être lu maintenant, ou reporté au cours
suivant pour permettre une conclusion propre.

Juge pédagogiquement, PAS par mots-clés :
- CONTINUE si le passage prolonge, illustre ou referme clairement l'idée en cours.
- REPORTE si le passage ouvre un nouveau grand sujet, une nouvelle section, ou
  une idée qui mérite une vraie introduction au début du prochain fichier audio.
- REPORTE aussi si le passage commencerait brutalement une idée que la conclusion
  interromprait aussitôt.

FIN DE CE QUI A ÉTÉ LU :
---
{_tail_words(consumed_text, 260)}
---

PROCHAIN PASSAGE CANDIDAT :
---
{_compact_words(candidate_text, 260)}
---

PASSAGE QUI SUIT ÉVENTUELLEMENT :
---
{_compact_words((next_chunk or {}).get("text") or "", 120) or "(indisponible)"}
---

Réponds uniquement avec ce JSON valide :
{{
  "decision": "continue" ou "defer",
  "reason": "raison courte en français"
}}"""

    try:
        raw = _llm_post(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            model=model or CLAUDE_MODEL,
            timeout=90,
        )
        data = _extract_llm_json(raw)
        decision = str(data.get("decision") or "").strip().lower()
        reason = re.sub(r"\s+", " ", str(data.get("reason") or "")).strip()
        return decision == "defer", reason
    except Exception as e:
        logger.warning(
            "⚠️ Décision IA de fin de bloc indisponible bloc %s (%s: %s)",
            bloc_number,
            type(e).__name__,
            str(e)[:160],
        )
        return False, ""


def _build_runtime_conclusion_text(consumed_chunks: list, remaining_sec: float, bloc_number: int) -> str:
    """Conclusion humaine basée sur le contenu réellement enseigné dans le bloc."""
    consumed_text = "\n\n".join(
        (c.get("text") or "").strip()
        for c in (consumed_chunks or [])
        if (c.get("text") or "").strip()
    )
    anchors = _pick_conclusion_anchors(consumed_text, max_anchors=6)
    target_words = int(max(180, min(480, max(45.0, remaining_sec) * 2.75)))

    lines = [
        "Avant de s'arrêter, on prend vraiment le temps de refermer cette partie proprement.",
        "Le cours a été dense, donc l'objectif n'est pas de rajouter une nouvelle idée, mais de remettre en ordre ce qui vient d'être travaillé et de le rendre plus facile à réutiliser.",
    ]

    labels = [
        "Premier repère important",
        "Deuxième point à garder en tête",
        "Troisième élément utile pour la pratique",
        "Autre idée à ne pas perdre",
        "Point de vigilance pour la suite",
        "Dernier repère avant de passer à la suite",
    ]
    for idx, anchor in enumerate(anchors):
        label = labels[idx] if idx < len(labels) else "Autre point important"
        lines.append(f"{label} : {anchor}")

    if not anchors:
        lines.append(
            "Ce qu'il faut retenir, c'est surtout le cheminement : on part d'une situation, "
            "on identifie ce qui compte vraiment, puis on transforme cette compréhension en action concrète."
        )

    lines.extend([
        "À ce stade, ce qui compte, c'est de ne pas retenir ces points comme une liste isolée. Il faut les relier entre eux : chaque notion prépare la suivante, et c'est cette continuité qui permet de mieux agir dans une situation réelle.",
        "Si vous deviez retenir une méthode simple, ce serait celle-ci : observer d'abord, nommer clairement ce qui se passe, choisir une réponse adaptée, puis vérifier que cette réponse produit bien l'effet recherché.",
        "On va donc s'arrêter ici sur cette base. Dans la suite, on pourra reprendre ce fil sans repartir de zéro : les repères sont posés, le vocabulaire est en place, et on pourra aller plus loin dans l'application.",
    ])

    return _limit_text_words_natural(" ".join(lines), target_words)


def _synthesize_short_conclusion_audio(
    basic_tts: bool,
    progress_callback=None,
    template: str | None = None,
    fast_tts_pipeline: bool = False,
) -> tuple:
    """Génère un MP3 court de transition à coller en fin de bloc tronqué.

    Utilisé uniquement en mode `basic_tts` (Edge TTS) pour boucher la marge
    réservée par `conclusion_margin_sec` quand le runtime fit a stoppé la
    génération avant la fin du créneau. Le texte vient de la variable d'env
    `EDGE_TTS_CONCLUSION_TEMPLATE` ou du template par défaut.

    Retourne `(audio_bytes, duration_sec)`. Lève si appelé hors basic_tts —
    Fish Audio garde son comportement actuel sans cette branche.
    """
    if not basic_tts:
        raise NotImplementedError(
            "_synthesize_short_conclusion_audio n'est implémenté que pour basic_tts (Edge TTS)"
        )

    from services.basic_tts_service import convert_to_speech_basic

    template = (
        template
        if template is not None
        else os.getenv("EDGE_TTS_CONCLUSION_TEMPLATE", _DEFAULT_CONCLUSION_TEMPLATE)
    ).strip()
    if not template:
        template = _DEFAULT_CONCLUSION_TEMPLATE

    if progress_callback:
        progress_callback("génération conclusion de transition")

    audio_bytes = convert_to_speech_basic(
        template,
        progress_callback=lambda msg: progress_callback(f"conclusion · {msg}") if progress_callback else None,
        parallel_workers=_edge_tts_fast_workers() if fast_tts_pipeline else 1,
        **_basic_tts_pipeline_retry_kwargs(),
    )
    duration_sec = _mp3_duration_seconds_no_ffprobe(audio_bytes)
    return audio_bytes, duration_sec


def _synthesize_course_audio_synced_to_slides(
    bloc: dict,
    slides: list,
    filename: str,
    *,
    mock: bool,
    basic_tts: bool,
    progress_callback=None,
    prepended_chunks: list = None,
    conclusion_margin_sec: int = None,
    runtime_fit: bool = False,
    fast_tts_pipeline: bool = False,
    llm_model: str | None = None,
):
    """Generate one course MP3 by slide-sized chunks and return slide timings.

    Mode `runtime_fit=True` (Edge TTS uniquement) :
        - Mesure la durée Edge TTS réelle de chaque chunk via
          `_mp3_duration_seconds_no_ffprobe`, et calcule un `observed_wpm`
          à mesure (bootstrap _BOOTSTRAP_WPM_EDGE_TTS).
        - Sub-chunke adaptativement (paliers 600/300/150 mots) selon la
          marge restante avant `target_sec - conclusion_margin_sec`.
        - Stoppe la génération avant dépassement et reporte les chunks
          non générés via le retour `unconsumed_chunks` (cascade vers le
          bloc suivant ou le carryover inter-jours).
        - Préfixe `prepended_chunks` (carryover intra-jour des blocs
          précédents) en tête de la file.
        - Ajoute une conclusion courte juste avant la fin si stop volontaire,
          en étendant le `end_time` du dernier timing slide pour que le
          frontend continue d'afficher la slide pendant la transition.

    Mode classique (Fish Audio sync slides, ou basic_tts sans runtime_fit) :
        - Comportement d'origine inchangé : génère tous les chunks slide.
        - `prepended_chunks` ignoré, `unconsumed_chunks` toujours [].

    Returns:
        (
            audio_bytes,
            voice_duration_sec,
            fit_method,
            attempts,
            timings,
            unconsumed_chunks,
            consumed_chunks,
        )
    """
    from services.tts_service import convert_to_speech

    target_sec = int(bloc["target_sec"])
    api_speed = _course_tts_speed()
    word_count = bloc.get("word_count") or len((bloc.get("text") or "").split())
    word_budget = _estimated_words_budget_for_course(target_sec, api_speed)

    # Garde-fou Fish Audio : préserve le comportement existant.
    if not mock and not basic_tts and word_budget > 0 and word_count > word_budget:
        raise ValueError(
            f"Bloc {bloc['bloc_number']} trop long avant TTS sync "
            f"({word_count} mots > budget prudent {word_budget} mots à speed={api_speed})."
        )

    if basic_tts:
        from services.basic_tts_service import convert_to_speech_basic, concat_mp3_bytes
    if not basic_tts or mock:
        from pydub import AudioSegment

    base_chunks = _build_slide_audio_chunks(bloc, slides)
    if not base_chunks:
        raise ValueError(f"Bloc {bloc['bloc_number']} vide pour sync slides")

    # Runtime fit n'est supporté qu'en basic_tts (Edge TTS). Sinon ignoré.
    use_runtime_fit = bool(runtime_fit and basic_tts)

    if conclusion_margin_sec is None:
        conclusion_margin_sec = int(os.getenv(
            "EDGE_TTS_CONCLUSION_MARGIN_SEC",
            _DEFAULT_CONCLUSION_MARGIN_SEC,
        ))
        min_conclusion_margin = int(os.getenv("EDGE_TTS_MIN_CONCLUSION_MARGIN_SEC", "120"))
        conclusion_margin_sec = max(conclusion_margin_sec, min_conclusion_margin)

    def _emit(message: str):
        if progress_callback:
            progress_callback(message)

    # Préfixer le carryover intra-jour uniquement en runtime_fit. Si du texte a
    # été reporté du bloc précédent, on l'amorce et on reformule son début avant
    # de l'envoyer au TTS.
    runtime_handoff_meta = {}
    if use_runtime_fit and prepended_chunks:
        _emit(f"Bloc {bloc['bloc_number']}/7 — rédaction amorce IA du passage reporté...")
        rewritten_prepended, runtime_handoff_meta = _rewrite_runtime_carryover_chunks(
            prepended_chunks,
            base_chunks,
            bloc_number=int(bloc.get("bloc_number") or 0),
            model=llm_model,
        )
        if runtime_handoff_meta:
            _emit(f"Bloc {bloc['bloc_number']}/7 — amorce IA du passage reporté ajoutée")
        chunks = list(rewritten_prepended) + list(base_chunks)
    else:
        chunks = list(base_chunks)

    fast_tts_pipeline = bool(fast_tts_pipeline and use_runtime_fit)

    if basic_tts:
        # Pas de silence d'amorce (cf. fix 302:01 — encodages incompatibles).
        audio_parts = []
        cursor_sec = 0.0
    else:
        full_audio = AudioSegment.silent(duration=_COURSE_START_SILENCE_SECONDS * 1000)
        cursor_sec = float(_COURSE_START_SILENCE_SECONDS)
    timings = []
    attempts = []
    if runtime_handoff_meta:
        attempts.append({
            "kind": "ai_runtime_handoff_opening",
            "chunk": "start",
            "text": runtime_handoff_meta.get("opening_text") or "",
            "original_start": runtime_handoff_meta.get("original_start") or "",
        })
    unconsumed_chunks = []
    consumed_chunks = []

    # Tracking pour observed_wpm (runtime_fit uniquement).
    total_words_generated = 0
    total_duration_generated = 0.0
    stopped_for_runtime_fit = False
    ai_stop_checks = 0
    try:
        ai_stop_check_limit = max(0, int(os.getenv("COURSE_AI_STOP_CHECKS_PER_BLOCK", "2")))
    except (TypeError, ValueError):
        ai_stop_check_limit = 2

    def _synthesize_basic_measured(text: str, progress_prefix: str) -> tuple:
        cache_key = None
        if fast_tts_pipeline and _edge_tts_fast_cache_enabled():
            cache_key = _edge_tts_fast_cache_key(text)
            with _EDGE_TTS_FAST_CACHE_LOCK:
                cached = _EDGE_TTS_FAST_CACHE.get(cache_key)
            if cached:
                _emit(f"{progress_prefix} · cache rapide OK")
                return cached[0], cached[1], True

        audio_bytes = convert_to_speech_basic(
            text,
            progress_callback=(
                lambda msg: _emit(f"{progress_prefix} · {msg}")
                if not fast_tts_pipeline
                else None
            ),
            parallel_workers=_edge_tts_fast_workers() if fast_tts_pipeline else 1,
            **_basic_tts_pipeline_retry_kwargs(),
        )
        duration_sec = _mp3_duration_seconds_no_ffprobe(audio_bytes)
        if cache_key:
            with _EDGE_TTS_FAST_CACHE_LOCK:
                _EDGE_TTS_FAST_CACHE[cache_key] = (audio_bytes, duration_sec)
        return audio_bytes, duration_sec, False

    # Index manuel pour pouvoir capturer le reste de la file en cas de stop.
    chunk_idx = 0
    while chunk_idx < len(chunks):
        chunk = chunks[chunk_idx]
        text = (chunk.get("text") or "").strip()
        if not text:
            chunk_idx += 1
            continue

        # ── Runtime fit : décision de stop + sub-chunk JIT ──────────────────
        if use_runtime_fit:
            remaining_sec = target_sec - conclusion_margin_sec - cursor_sec
            max_words = _max_chunk_words_for_remaining(remaining_sec)

            if max_words == 0:
                # Plus assez de place pour ajouter même un micro-chunk proprement :
                # on reporte le reste et on garde la fin pour la conclusion.
                stopped_for_runtime_fit = True
                unconsumed_chunks.extend(chunks[chunk_idx:])
                break

            # Sub-chunk JIT si le chunk dépasse le plafond du palier courant.
            # Garantit la coupe sur frontière naturelle (paragraphe → phrase).
            if len(text.split()) > max_words:
                sub_chunks = _split_chunk_for_runtime_fit(chunk, max_words)
                if len(sub_chunks) > 1:
                    chunks = chunks[:chunk_idx] + list(sub_chunks) + chunks[chunk_idx + 1:]
                    chunk = chunks[chunk_idx]
                    text = (chunk.get("text") or "").strip()

            # Décision pédagogique IA : dans la fenêtre de fin, on demande si le
            # passage candidat doit être reporté pour éviter d'ouvrir un grand
            # pan juste avant la conclusion.
            if (
                ai_stop_checks < ai_stop_check_limit
                and remaining_sec <= _course_ai_stop_window_sec()
                and consumed_chunks
            ):
                ai_stop_checks += 1
                should_defer, defer_reason = _ai_should_defer_chunk_before_conclusion(
                    bloc_number=int(bloc.get("bloc_number") or 0),
                    remaining_before_conclusion_sec=remaining_sec,
                    consumed_chunks=consumed_chunks,
                    candidate_chunk=chunk,
                    next_chunk=chunks[chunk_idx + 1] if chunk_idx + 1 < len(chunks) else None,
                    model=llm_model,
                )
                attempts.append({
                    "kind": "ai_boundary_defer" if should_defer else "ai_boundary_continue",
                    "chunk": chunk_idx + 1,
                    "remaining_sec": round(float(remaining_sec), 3),
                    "words": len(text.split()),
                    "reason": defer_reason,
                })
                if should_defer:
                    stopped_for_runtime_fit = True
                    unconsumed_chunks.extend(chunks[chunk_idx:])
                    _emit(
                        f"Bloc {bloc['bloc_number']}/7 — décision IA : nouveau pan reporté "
                        f"avant conclusion ({defer_reason or 'raison non fournie'})"
                    )
                    break
                _emit(
                    f"Bloc {bloc['bloc_number']}/7 — décision IA : passage gardé "
                    f"avant conclusion ({defer_reason or 'continuité pédagogique'})"
                )

            # Estimer la durée de ce sous-chunk avec le wpm réel observé.
            observed_wpm = (
                (total_words_generated * 60.0 / total_duration_generated)
                if total_duration_generated > 0
                else _BOOTSTRAP_WPM_EDGE_TTS
            )
            chunk_words = len(text.split())
            estimated_chunk_sec = (
                chunk_words * 60.0 / observed_wpm if observed_wpm > 0 else 0.0
            )

            # Si le sous-chunk (déjà découpé sur frontière naturelle) dépasse
            # encore : on stoppe et on le reporte ENTIER (jamais de coupe
            # intra-phrase). Tolérance technique 2s pour arrondis frame MP3.
            if (cursor_sec + estimated_chunk_sec
                    > (target_sec - conclusion_margin_sec) + _TOLERANCE_OVERFLOW_SEC):
                smaller_max_words = _smaller_runtime_fit_word_limit(
                    chunk,
                    available_sec=(target_sec - conclusion_margin_sec) - cursor_sec,
                    observed_wpm=observed_wpm,
                )
                if smaller_max_words > 0 and smaller_max_words < len(text.split()):
                    sub_chunks = _split_chunk_for_runtime_fit(chunk, smaller_max_words)
                    if len(sub_chunks) > 1:
                        chunks = chunks[:chunk_idx] + list(sub_chunks) + chunks[chunk_idx + 1:]
                        _emit(
                            f"Bloc {bloc['bloc_number']}/7 — slide audio {chunk_idx + 1}/{len(chunks)} "
                            f"redécoupée en micro-chunks ({smaller_max_words} mots max)"
                        )
                        continue
                stopped_for_runtime_fit = True
                unconsumed_chunks.extend(chunks[chunk_idx:])
                break

        # ── Génération du chunk (mock / basic_tts / fish_audio) ─────────────
        _emit(
            f"Bloc {bloc['bloc_number']}/7 — slide audio {chunk_idx + 1}/{len(chunks)} "
            f"({len(text.split())} mots)"
        )

        if mock:
            segment = AudioSegment.silent(duration=1000)
            mode = "mock"
        elif basic_tts:
            progress_prefix = f"Bloc {bloc['bloc_number']}/7 — slide {chunk_idx + 1}/{len(chunks)}"
            audio_bytes, duration_sec, cache_hit = _synthesize_basic_measured(text, progress_prefix)
            mode = "gtts_fast_cache" if cache_hit else "gtts_fast" if fast_tts_pipeline else "gtts"
        else:
            audio_bytes = convert_to_speech(text, speed=api_speed)
            segment = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
            mode = f"fish_audio_speed={api_speed}"

        if not basic_tts:
            duration_sec = len(segment) / 1000

        if (
            use_runtime_fit
            and cursor_sec + duration_sec
            > (target_sec - conclusion_margin_sec) + _TOLERANCE_OVERFLOW_SEC
        ):
            chunk_words = len(text.split())
            measured_wpm = chunk_words * 60.0 / duration_sec if duration_sec > 0 else 0.0
            smaller_max_words = _smaller_runtime_fit_word_limit(
                chunk,
                available_sec=(target_sec - conclusion_margin_sec) - cursor_sec,
                observed_wpm=measured_wpm,
            )
            if smaller_max_words > 0 and smaller_max_words < chunk_words:
                sub_chunks = _split_chunk_for_runtime_fit(chunk, smaller_max_words)
                if len(sub_chunks) > 1:
                    chunks = chunks[:chunk_idx] + list(sub_chunks) + chunks[chunk_idx + 1:]
                    attempts.append({
                        "kind": f"{mode}_split_after_measured_overflow",
                        "chunk": chunk_idx + 1,
                        "duration": duration_sec,
                        "words": chunk_words,
                        "retry_max_words": smaller_max_words,
                    })
                    _emit(
                        f"Bloc {bloc['bloc_number']}/7 — slide audio {chunk_idx + 1}/{len(chunks)} "
                        f"trop longue, redécoupage ({smaller_max_words} mots max)"
                    )
                    continue
            stopped_for_runtime_fit = True
            unconsumed_chunks.extend(chunks[chunk_idx:])
            attempts.append({
                "kind": f"{mode}_rejected_overflow",
                "chunk": chunk_idx + 1,
                "duration": duration_sec,
                "words": len(text.split()),
                "limit_sec": target_sec - conclusion_margin_sec,
            })
            _emit(
                f"Bloc {bloc['bloc_number']}/7 — slide audio {chunk_idx + 1}/{len(chunks)} "
                f"reportée ({duration_sec:.1f}s dépasserait la marge)"
            )
            break

        start_sec = cursor_sec
        end_sec = start_sec + duration_sec
        if basic_tts:
            audio_parts.append(audio_bytes)
        else:
            full_audio += segment
        cursor_sec = end_sec
        attempts.append({"kind": mode, "chunk": chunk_idx + 1, "duration": duration_sec})
        _emit(
            f"Bloc {bloc['bloc_number']}/7 — slide audio {chunk_idx + 1}/{len(chunks)} OK "
            f"({duration_sec:.1f}s)"
        )

        timings.append({
            "slide_id": chunk.get("slide_id"),
            "audio_filename": filename,
            "start_time": round(start_sec, 3),
            "end_time": round(end_sec, 3),
            "duration": round(duration_sec, 3),
            "word_start": chunk.get("word_start"),
            "word_end": chunk.get("word_end"),
        })

        if use_runtime_fit:
            total_words_generated += len(text.split())
            total_duration_generated += duration_sec
            consumed_chunks.append(dict(chunk))

        chunk_idx += 1

    # ── Conclusion automatique : soit on a stoppé avec surplus, soit tout le
    # texte du bloc est consommé mais il reste une vraie marge à occuper.
    min_conclusion_room_sec = float(os.getenv("EDGE_TTS_MIN_CONCLUSION_ROOM_SEC", "25"))
    should_append_runtime_conclusion = bool(
        use_runtime_fit
        and (stopped_for_runtime_fit or (target_sec - cursor_sec) >= min_conclusion_room_sec)
    )
    if should_append_runtime_conclusion:
        def _runtime_conclusion_template(scale: float = 1.0) -> str | None:
            env_template = (os.getenv("EDGE_TTS_CONCLUSION_TEMPLATE") or "").strip()
            if env_template:
                return env_template
            remaining_for_conclusion = max(0.0, target_sec - cursor_sec) * max(0.35, scale)
            return _build_runtime_conclusion_text(
                consumed_chunks,
                remaining_sec=remaining_for_conclusion,
                bloc_number=int(bloc.get("bloc_number") or 0),
            )

        def _try_append_conclusion(kind: str, template: str | None = None) -> bool:
            nonlocal cursor_sec
            conclusion_bytes, conclusion_dur = _synthesize_short_conclusion_audio(
                basic_tts=True,
                progress_callback=_emit,
                template=template,
                fast_tts_pipeline=fast_tts_pipeline,
            )
            if cursor_sec + conclusion_dur > target_sec + _TOLERANCE_OVERFLOW_SEC:
                attempts.append({
                    "kind": f"{kind}_rejected_overflow",
                    "chunk": "end",
                    "duration": conclusion_dur,
                    "limit_sec": target_sec,
                    "text": template or "",
                })
                _emit(
                    f"Bloc {bloc['bloc_number']}/7 — conclusion {kind} ignorée "
                    f"({conclusion_dur:.1f}s dépasserait la cible)"
                )
                return False

            audio_parts.append(conclusion_bytes)
            attempts.append({
                "kind": kind,
                "chunk": "end",
                "duration": conclusion_dur,
                "text": template or "",
            })
            if timings:
                last = timings[-1]
                last["end_time"] = round(float(last["end_time"]) + conclusion_dur, 3)
                last["duration"] = round(float(last["duration"]) + conclusion_dur, 3)
            cursor_sec += conclusion_dur
            _emit(
                f"Bloc {bloc['bloc_number']}/7 — conclusion ajoutée ({conclusion_dur:.1f}s)"
            )
            return True

        try:
            appended = _try_append_conclusion(
                "conclusion",
                template=_runtime_conclusion_template(scale=1.0),
            )
            if not appended:
                appended = _try_append_conclusion(
                    "conclusion_fallback",
                    template=_runtime_conclusion_template(scale=0.55),
                )
            if not appended:
                appended = _try_append_conclusion(
                    "conclusion_ultra_fallback",
                    template=_FALLBACK_CONCLUSION_TEMPLATE,
                )
            if not appended:
                logger.warning(
                    f"⚠️ Bloc {bloc['bloc_number']} — aucune conclusion ajoutée "
                    "(elles dépassaient la cible)"
                )
        except Exception as e:
            logger.warning(
                f"⚠️ Bloc {bloc['bloc_number']} — génération conclusion échouée : "
                f"{e} (on continue sans)"
            )

    # ── Assemblage final ────────────────────────────────────────────────────
    if basic_tts:
        if use_runtime_fit and stopped_for_runtime_fit and not audio_parts:
            raise ValueError(
                f"Bloc {bloc['bloc_number']} runtime fit : aucun audio généré "
                "avant le report du texte."
            )
        final_duration = cursor_sec
        output_bytes = concat_mp3_bytes(audio_parts) if audio_parts else b""
    else:
        final_duration = len(full_audio) / 1000
        if final_duration < target_sec:
            full_audio += AudioSegment.silent(duration=int((target_sec - final_duration) * 1000))
        elif final_duration > target_sec and not mock:
            raise ValueError(
                f"Bloc {bloc['bloc_number']} sync trop long "
                f"({final_duration:.1f}s > cible {target_sec}s)."
            )

        output = io.BytesIO()
        full_audio.export(output, format="mp3", bitrate="128k")
        output_bytes = output.getvalue()

    fit_method = (
        "slide_sync_mock"
        if mock
        else "slide_sync_edge_runtime_fit_fast"
        if use_runtime_fit and fast_tts_pipeline
        else "slide_sync_edge_runtime_fit"
        if use_runtime_fit
        else "slide_sync_edge_no_padding"
        if basic_tts
        else f"slide_sync_fish_speed={api_speed}"
    )
    voice_start_sec = 0.0 if basic_tts else _COURSE_START_SILENCE_SECONDS
    return (
        output_bytes,
        cursor_sec - voice_start_sec,
        fit_method,
        attempts,
        _merge_adjacent_slide_timings(timings),
        unconsumed_chunks,
        consumed_chunks,
    )


def _format_carryover_for_next_course(text: str) -> str:
    """Prépare le texte reporté pour ouvrir le cours suivant sans dire "hier"."""
    clean = (text or "").strip()
    if not clean:
        return ""
    return f"{_CARRYOVER_INTRO}\n\n{clean}"


def _ensure_carryover_columns() -> None:
    """Migration lazy pour les champs de report inter-journées."""
    global _CARRYOVER_COLUMNS_READY
    if _CARRYOVER_COLUMNS_READY:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(content_generation_jobs)")
    cols = {row[1] for row in cursor.fetchall()}
    wanted = {
        "carryover_in_text": "TEXT DEFAULT ''",
        "carryover_in_source_folder_id": "INTEGER",
        "carryover_out_text": "TEXT DEFAULT ''",
        "carryover_out_target_folder_id": "INTEGER",
    }
    for col, col_type in wanted.items():
        if col not in cols:
            cursor.execute(f"ALTER TABLE content_generation_jobs ADD COLUMN {col} {col_type}")
    conn.commit()
    conn.close()
    _CARRYOVER_COLUMNS_READY = True


def _find_next_folder_id(platform_id: int, folder_id: int) -> int | None:
    """Retourne le dossier suivant de la même plateforme, selon position/id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT position, id FROM cours_folders WHERE id = ? AND platform_id = ?",
        (folder_id, platform_id),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    position, current_id = row
    cursor.execute(
        """
        SELECT id FROM cours_folders
        WHERE platform_id = ?
          AND (position > ? OR (position = ? AND id > ?))
        ORDER BY position ASC, id ASC
        LIMIT 1
        """,
        (platform_id, position, position, current_id),
    )
    next_row = cursor.fetchone()
    conn.close()
    return next_row[0] if next_row else None


def _store_cross_day_carryover(source_folder_id: int, target_folder_id: int, text: str) -> None:
    """Persiste le report J→J+1 de manière idempotente."""
    _ensure_carryover_columns()
    clean = (text or "").strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE content_generation_jobs
        SET carryover_out_text = ?, carryover_out_target_folder_id = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE folder_id = ?
        """,
        (clean, target_folder_id if clean else None, source_folder_id),
    )
    cursor.execute(
        """
        UPDATE content_generation_jobs
        SET carryover_in_text = ?, carryover_in_source_folder_id = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE folder_id = ?
        """,
        (_format_carryover_for_next_course(clean) if clean else "", source_folder_id if clean else None, target_folder_id),
    )
    cursor.execute(
        """
        UPDATE content_generation_segments
        SET dirty = 1
        WHERE job_id = (SELECT id FROM content_generation_jobs WHERE folder_id = ?)
          AND sub_part_index = 0 AND passe = 1
        """,
        (target_folder_id,),
    )
    conn.commit()
    conn.close()


def _clear_cross_day_carryover_from_source(source_folder_id: int, target_folder_id: int | None = None) -> None:
    """Nettoie un ancien report si le nouveau découpage n'en produit plus."""
    _ensure_carryover_columns()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE content_generation_jobs
        SET carryover_out_text = '', carryover_out_target_folder_id = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE folder_id = ?
        """,
        (source_folder_id,),
    )
    if target_folder_id:
        cursor.execute(
            """
            UPDATE content_generation_jobs
            SET carryover_in_text = '', carryover_in_source_folder_id = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE folder_id = ? AND carryover_in_source_folder_id = ?
            """,
            (target_folder_id, source_folder_id),
        )
        cursor.execute(
            """
            UPDATE content_generation_segments
            SET dirty = 1
            WHERE job_id = (SELECT id FROM content_generation_jobs WHERE folder_id = ?)
              AND sub_part_index = 0 AND passe = 1
            """,
            (target_folder_id,),
        )
    else:
        cursor.execute(
            """
            SELECT folder_id FROM content_generation_jobs
            WHERE carryover_in_source_folder_id = ?
            """,
            (source_folder_id,),
        )
        target_rows = cursor.fetchall()
        cursor.execute(
            """
            UPDATE content_generation_jobs
            SET carryover_in_text = '', carryover_in_source_folder_id = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE carryover_in_source_folder_id = ?
            """,
            (source_folder_id,),
        )
        for (target_id,) in target_rows:
            cursor.execute(
                """
                UPDATE content_generation_segments
                SET dirty = 1
                WHERE job_id = (SELECT id FROM content_generation_jobs WHERE folder_id = ?)
                  AND sub_part_index = 0 AND passe = 1
                """,
                (target_id,),
            )
    conn.commit()
    conn.close()


def _get_existing_carryover_out(source_folder_id: int, target_folder_id: int | None) -> str:
    _ensure_carryover_columns()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT carryover_out_text, carryover_out_target_folder_id
        FROM content_generation_jobs
        WHERE folder_id = ?
        """,
        (source_folder_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return ""
    text, stored_target = row
    if target_folder_id is not None and stored_target != target_folder_id:
        return ""
    return (text or "").strip()


def _reduce_last_bloc_to_budget(bloc: dict, model=None) -> str:
    """Réduit le dernier bloc avant TTS si aucun jour suivant ne peut absorber le surplus."""
    budget = int(bloc.get("word_budget") or 0)
    if budget <= 0:
        raise ValueError("Budget TTS indisponible pour réduction du dernier bloc")

    # On vise plus bas que le cap prudent pour absorber l'écart de calibration Fish.
    target_words = max(800, int(budget * 0.90))
    prompt = f"""Tu es un formateur expert. Tu dois REMANIER le dernier bloc d'un cours audio
pour qu'il tienne dans son créneau TTS, sans jouer sur la vitesse de la voix.

OBJECTIF :
- Réduis le texte à environ {target_words} mots.
- Ne supprime pas l'idée générale : condense, fusionne les exemples redondants,
  garde les notions utiles.
- N'ajoute AUCUNE nouvelle idée.
- Ne dis jamais "hier". Si tu fais référence à la séance précédente, dis
  "au cours dernier".
- Termine par une vraie conclusion de cours.
- Texte oral fluide, naturel, prêt pour TTS.

TEXTE À REMANIER :
---
{bloc.get("text", "")}
---

Réponds uniquement avec le texte remanié, sans commentaire."""

    reduced = _llm_post(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=min(12000, int(target_words * 2.2) + 500),
        model=model or default_model(),
    )
    reduced = (reduced or "").replace("```", "").strip()
    if not reduced:
        raise ValueError("Réduction dernier bloc vide")
    if len(reduced.split()) > budget:
        raise ValueError(
            f"Réduction dernier bloc encore trop longue ({len(reduced.split())} mots > budget {budget})"
        )
    return reduced


def _sentence_boundary_positions(words):
    """Retourne les positions de mots situées juste après une fin de phrase."""
    positions = []
    for i, word in enumerate(words):
        if _SENTENCE_END_RE.search(word.strip()):
            positions.append(i + 1)
    return positions


def _closest_boundary(candidates, target_w):
    return min(candidates, key=lambda b: (abs(b - target_w), b < target_w))


def _choose_natural_boundary(
    cursor_w,
    target_w,
    total_words,
    remaining_blocks,
    paragraph_boundaries,
    sentence_boundaries,
    word_budget_max=None,
):
    """
    Choisit une coupure naturelle proche de la cible, en respectant le budget TTS.

    1. fin de paragraphe SOUS le cap budget, car c'est l'unité pédagogique la plus fiable ;
    2. fin de phrase SOUS le cap budget, si aucun paragraphe convenable n'existe ;
    3. split brut au cap seulement en dernier recours.

    `word_budget_max` est le hard cap : le bloc ne dépasse JAMAIS ce nombre de mots.
    Les paragraphes en surplus tombent automatiquement dans le bloc suivant — pas besoin
    de raccourcir au LLM ni de tronquer l'audio.
    """
    if target_w >= total_words:
        return total_words

    # Évite de donner tout le texte au bloc courant si les blocs suivants doivent
    # encore recevoir du contenu. En prod les blocs sont énormes ; ce plancher ne
    # sert qu'à éviter les cas dégénérés sur des tests courts.
    min_words_per_remaining_block = 50 if total_words >= 700 else 1
    max_end = max(cursor_w + 1, total_words - remaining_blocks * min_words_per_remaining_block)

    # Hard cap : on plafonne au budget TTS pour garantir que `_synthesize_course_audio_to_fit`
    # ne refusera jamais ce bloc à cause d'un sur-volume. Le surplus cascade au bloc suivant.
    if word_budget_max and word_budget_max > 0:
        cap_w = min(max_end, cursor_w + word_budget_max)
        cap_w = max(cap_w, cursor_w + 1)
    else:
        cap_w = max_end

    target_w = min(max(target_w, cursor_w + 1), cap_w)

    span = max(1, target_w - cursor_w)
    paragraph_window = max(160, min(700, int(span * 0.15)))
    sentence_window = max(80, min(250, int(span * 0.08)))

    paragraph_candidates = [
        b for b in paragraph_boundaries
        if max(cursor_w + 1, target_w - paragraph_window) <= b <= min(cap_w, target_w + paragraph_window)
    ]
    if paragraph_candidates:
        return _closest_boundary(paragraph_candidates, target_w)

    sentence_candidates = [
        b for b in sentence_boundaries
        if max(cursor_w + 1, target_w - sentence_window) <= b <= min(cap_w, target_w + sentence_window)
    ]
    if sentence_candidates:
        chosen = _closest_boundary(sentence_candidates, target_w)
        logger.warning(
            f"   ⚠️ Pas de fin de paragraphe proche: cible mot {target_w}, "
            f"fin de phrase retenue {chosen}"
        )
        return chosen

    paragraph_fallback = [b for b in paragraph_boundaries if cursor_w < b <= cap_w]
    if paragraph_fallback:
        chosen = _closest_boundary(paragraph_fallback, target_w)
        logger.warning(
            f"   ⚠️ Fin de paragraphe éloignée: cible mot {target_w}, "
            f"frontière retenue {chosen} (cap budget {cap_w})"
        )
        return chosen

    sentence_fallback = [b for b in sentence_boundaries if cursor_w < b <= cap_w]
    if sentence_fallback:
        chosen = _closest_boundary(sentence_fallback, target_w)
        logger.warning(
            f"   ⚠️ Fin de phrase éloignée: cible mot {target_w}, "
            f"frontière retenue {chosen} (cap budget {cap_w})"
        )
        return chosen

    logger.warning(
        f"   ⚠️ Aucune frontière naturelle sous cap {cap_w}; split brut au cap"
    )
    return cap_w


def _build_course_text_units(segments):
    """Construit les paragraphes TTS avec mapping mots → segment."""
    full_words = []
    word_to_seg_idx = []
    units = []

    for seg_idx, seg in enumerate(segments):
        raw_paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", seg["text"] or "") if p.strip()]
        paragraphs = raw_paragraphs or [(seg["text"] or "").strip()]

        for paragraph in paragraphs:
            words = paragraph.split()
            if not words:
                continue
            start = len(full_words)
            end = start + len(words)
            units.append({"start": start, "end": end, "text": paragraph, "seg_idx": seg_idx})
            full_words.extend(words)
            word_to_seg_idx.extend([seg_idx] * len(words))

    return full_words, word_to_seg_idx, units


def _render_course_slice(full_words, units, start_w, end_w):
    """Reconstruit un bloc en conservant les paragraphes complets quand possible."""
    parts = []
    for unit in units:
        if unit["end"] <= start_w:
            continue
        if unit["start"] >= end_w:
            break

        overlap_start = max(start_w, unit["start"])
        overlap_end = min(end_w, unit["end"])
        if overlap_start >= overlap_end:
            continue

        if overlap_start == unit["start"] and overlap_end == unit["end"]:
            parts.append(unit["text"])
        else:
            parts.append(" ".join(full_words[overlap_start:overlap_end]))

    return "\n\n".join(p.strip() for p in parts if p.strip())


def _build_course_blocs_from_segments(
    segments,
    cours_durations_min,
    playlist_spec,
    force_all=False,
    source_folder_id=None,
    next_folder_id=None,
    is_last_folder=False,
    model=None,
    preview=False,
):
    """Découpe le script en 7 blocs en respectant les fins d'idées ET le budget TTS.

    Chaque bloc reçoit un cap mots calé sur le budget TTS (`_estimated_words_budget_for_course`).
    Tout paragraphe en surplus cascade automatiquement vers le bloc suivant — déterministe,
    gratuit, sans appel LLM réactif. Si le bloc 7 finit malgré tout au-dessus de son cap,
    c'est que le total mots/jour dépasse le budget TTS → ressort de l'ajustement audio en aval.
    """
    full_words, word_to_seg_idx, units = _build_course_text_units(segments)

    total_words = len(full_words)
    total_duration = sum(cours_durations_min.values())
    sentence_boundaries = _sentence_boundary_positions(full_words)
    paragraph_boundaries = [u["end"] for u in units if u["end"] < total_words]
    api_speed = _course_tts_speed()
    blocs = []
    cursor_w = 0
    cumulative_duration = 0

    for bloc_num in range(1, 8):
        duration = cours_durations_min[bloc_num]
        cumulative_duration += duration
        target_sec = next(
            (spec[1] for spec in playlist_spec if spec[3] == bloc_num and spec[2] == "cours"),
            duration * 60
        )
        word_budget = _estimated_words_budget_for_course(target_sec, api_speed)

        if bloc_num == 7:
            # Bloc 7 absorbe le reste : si ça dépasse son budget, c'est volume_safety qui doit alerter
            end_w = total_words
        else:
            target_w = round(total_words * cumulative_duration / total_duration)
            end_w = _choose_natural_boundary(
                cursor_w=cursor_w,
                target_w=target_w,
                total_words=total_words,
                remaining_blocks=7 - bloc_num,
                paragraph_boundaries=paragraph_boundaries,
                sentence_boundaries=sentence_boundaries,
                word_budget_max=word_budget,
            )

        if end_w <= cursor_w and cursor_w < total_words:
            end_w = min(cursor_w + 1, total_words)

        contributing_seg_indices = set(word_to_seg_idx[cursor_w:end_w])
        is_dirty = force_all or any(segments[i]["dirty"] for i in contributing_seg_indices)

        blocs.append({
            "bloc_number": bloc_num,
            "text": _render_course_slice(full_words, units, cursor_w, end_w),
            "start_w": cursor_w,
            "end_w": end_w,
            "word_count": end_w - cursor_w,
            "contributing_seg_indices": contributing_seg_indices,
            "dirty": is_dirty,
            "target_sec": target_sec,
            "word_budget": word_budget,
            "filename": next(
                (spec[0] for spec in playlist_spec if spec[3] == bloc_num and spec[2] == "cours"),
                f"cours_bloc{bloc_num}.mp3"
            ),
        })
        block_words = end_w - cursor_w
        budget_str = f"budget {word_budget}" if word_budget > 0 else "budget n/a"
        if word_budget > 0 and block_words > word_budget and bloc_num != 7:
            logger.warning(
                f"   ⚠️ Bloc {bloc_num}: {block_words} mots > {budget_str} (cascade attendue)"
            )
        else:
            logger.info(
                f"   ✂️ Bloc {bloc_num}: mots {cursor_w}-{end_w} "
                f"({block_words} mots / {budget_str})"
            )
        cursor_w = end_w

    # ── Passe 2 : redistribution backward des paragraphes complets pour combler les undershoots ──
    _redistribute_undershoot_backward(
        blocs, paragraph_boundaries, full_words, units, word_to_seg_idx, segments,
        api_speed, force_all,
    )

    carryover_out = _handle_last_bloc_overflow(
        blocs=blocs,
        full_words=full_words,
        units=units,
        word_to_seg_idx=word_to_seg_idx,
        segments=segments,
        paragraph_boundaries=paragraph_boundaries,
        sentence_boundaries=sentence_boundaries,
        api_speed=api_speed,
        source_folder_id=source_folder_id,
        next_folder_id=next_folder_id,
        is_last_folder=is_last_folder,
        model=model,
        preview=preview,
    )

    return blocs, total_words, carryover_out


_BACKWARD_UNDERSHOOT_THRESHOLD_SEC = 30  # gap > 30s déclenche la redistribution


def _redistribute_undershoot_backward(
    blocs, paragraph_boundaries, full_words, units, word_to_seg_idx, segments,
    api_speed, force_all,
):
    """Tire des paragraphes complets de bloc N+1 vers bloc N pour combler les undershoots.

    Préserve les unités d'idée pédagogiques (paragraphes entiers, jamais split).
    Boucle tant que :
      - le bloc N a un gap > seuil
      - ET le premier paragraphe de bloc N+1 rentre dans le budget restant de bloc N
      - ET bloc N+1 garde au moins 1 paragraphe pour lui-même

    Marque les blocs touchés comme `dirty` (texte modifié → audio à régénérer).
    """
    para_set = set(paragraph_boundaries)

    for i in range(len(blocs) - 1):  # tous sauf le dernier (bloc 7 absorbe le résidu, pas de cible où tirer)
        bloc = blocs[i]
        next_bloc = blocs[i + 1]

        moved = False
        while True:
            gap_sec = bloc["target_sec"] - _estimated_audio_seconds_for_words(
                bloc["word_count"], api_speed
            )
            if gap_sec <= _BACKWARD_UNDERSHOOT_THRESHOLD_SEC:
                break

            # Trouver la première fin de paragraphe à l'intérieur de next_bloc
            next_start = next_bloc["start_w"]
            next_end = next_bloc["end_w"]
            first_para_end = next(
                (b for b in paragraph_boundaries if next_start < b < next_end),
                None,
            )
            if first_para_end is None:
                break  # next_bloc n'a qu'un seul paragraphe : on ne le vide pas entièrement

            additional_words = first_para_end - next_start
            if additional_words <= 0:
                break

            # Le paragraphe rentre-t-il dans le budget de bloc ?
            new_word_count = bloc["word_count"] + additional_words
            if bloc["word_budget"] > 0 and new_word_count > bloc["word_budget"]:
                break  # paragraphe trop gros pour le budget restant

            # Déplacer
            bloc["end_w"] = first_para_end
            bloc["word_count"] = new_word_count
            next_bloc["start_w"] = first_para_end
            next_bloc["word_count"] = next_bloc["end_w"] - next_bloc["start_w"]
            moved = True

            logger.info(
                f"   ↩️ Bloc {bloc['bloc_number']}: tire un paragraphe ({additional_words} mots) "
                f"de bloc {next_bloc['bloc_number']} (gap était {gap_sec:.0f}s)"
            )

        if moved:
            # Re-render texts + recompute contributing segs / dirty pour les deux blocs
            for b in (bloc, next_bloc):
                b["text"] = _render_course_slice(full_words, units, b["start_w"], b["end_w"])
                b["contributing_seg_indices"] = set(word_to_seg_idx[b["start_w"]:b["end_w"]])
                b["dirty"] = True if not force_all else b["dirty"]
                # force_all=True implique déjà dirty ; sinon redistribution = nouvelle audio
                if not force_all:
                    b["dirty"] = True


def _handle_last_bloc_overflow(
    blocs,
    full_words,
    units,
    word_to_seg_idx,
    segments,
    paragraph_boundaries,
    sentence_boundaries,
    api_speed,
    source_folder_id=None,
    next_folder_id=None,
    is_last_folder=False,
    model=None,
    preview=False,
):
    """Si le bloc 7 dépasse, reporte vers le cours suivant ou réduit le dernier jour."""
    if not blocs:
        return ""

    last = blocs[-1]
    budget = int(last.get("word_budget") or 0)
    if budget <= 0 or last["word_count"] <= budget:
        if source_folder_id and not preview:
            _clear_cross_day_carryover_from_source(source_folder_id, next_folder_id)
        return ""

    if next_folder_id and not is_last_folder:
        old_end = last["end_w"]
        target_w = last["start_w"] + budget
        cut_w = _choose_natural_boundary(
            cursor_w=last["start_w"],
            target_w=target_w,
            total_words=old_end,
            remaining_blocks=0,
            paragraph_boundaries=paragraph_boundaries,
            sentence_boundaries=sentence_boundaries,
            word_budget_max=budget,
        )
        cut_w = max(last["start_w"] + 1, min(cut_w, old_end))
        carryover_text = _render_course_slice(full_words, units, cut_w, old_end).strip()
        existing_carryover = (
            _get_existing_carryover_out(source_folder_id, next_folder_id)
            if source_folder_id else ""
        )
        same_clean_carryover = (
            bool(existing_carryover)
            and existing_carryover == carryover_text
            and not last.get("dirty")
        )

        last["end_w"] = cut_w
        last["word_count"] = cut_w - last["start_w"]
        last["text"] = _render_course_slice(full_words, units, last["start_w"], cut_w)
        last["contributing_seg_indices"] = set(word_to_seg_idx[last["start_w"]:cut_w])
        if not same_clean_carryover:
            last["dirty"] = True

        if source_folder_id and not same_clean_carryover and not preview:
            _store_cross_day_carryover(source_folder_id, next_folder_id, carryover_text)
        logger.warning(
            f"   🔁 Bloc 7 trop chargé : {len(carryover_text.split())} mots reportés "
            f"vers folder {next_folder_id}"
        )
        return carryover_text

    if preview:
        last["overflow_unresolved"] = True
        last["overflow_words"] = max(0, last["word_count"] - budget)
        logger.warning(
            f"   👁️ Preview : dernier bloc au-dessus du budget "
            f"({last['word_count']} mots / budget {budget}), sans remaniement API"
        )
        return ""

    # Dernier jour : pas de J+1, on remanie ce bloc par API avant TTS.
    reduced_text = _reduce_last_bloc_to_budget(last, model=model)
    last["text"] = reduced_text
    last["word_count"] = len(reduced_text.split())
    last["dirty"] = True
    last["closing_added"] = True
    last["closing_words"] = 0
    if source_folder_id:
        _clear_cross_day_carryover_from_source(source_folder_id, next_folder_id)
    logger.warning(
        f"   ✂️ Dernier bloc remanié par API : {last['word_count']} mots / budget {budget}"
    )
    return ""


def _apply_closing_transitions(blocs, api_speed, model=None):
    """Concatène à chaque bloc dirty un closing calibré sur le gap résiduel.

    Le closing comble (partiellement) le silence qui aurait été laissé en fin de bloc.
    Distinct des pauses dynamiques : on enrichit le fichier cours, pas la pause.

    Cf. `backend/services/closing_transition_service.py` pour la logique de génération.
    """
    from services.closing_transition_service import (
        generate_closing,
        GAP_NEGLIGIBLE_SEC,
    )

    last_bloc_num = max(b["bloc_number"] for b in blocs) if blocs else 7
    estimated_wpm = _TTS_REFERENCE_WPM_AT_095 * (api_speed / 0.95)

    for idx, bloc in enumerate(blocs):
        if not bloc.get("dirty"):
            continue  # bloc clean : on ne touche pas à l'existant
        if not (bloc.get("text") or "").strip():
            continue  # bloc vide : rien à clore

        raw_gap_sec = bloc["target_sec"] - _estimated_audio_seconds_for_words(
            bloc["word_count"], api_speed
        )
        remaining_budget_words = max(0, int(bloc.get("word_budget") or 0) - int(bloc["word_count"]))
        budget_gap_sec = (remaining_budget_words / estimated_wpm) * 60 if estimated_wpm > 0 else 0
        gap_sec = min(raw_gap_sec, budget_gap_sec)

        if gap_sec < GAP_NEGLIGIBLE_SEC or remaining_budget_words < 20:
            continue  # gap imperceptible : silence padding suffit

        # Excerpts pour le contexte LLM
        words_in_bloc = bloc["text"].split()
        prev_excerpt = " ".join(words_in_bloc[-200:]) if words_in_bloc else ""
        next_excerpt = ""
        if idx + 1 < len(blocs):
            next_words = (blocs[idx + 1].get("text") or "").split()
            next_excerpt = " ".join(next_words[:200])

        is_last = bloc["bloc_number"] == last_bloc_num

        closing = generate_closing(
            bloc_num=bloc["bloc_number"],
            prev_excerpt=prev_excerpt,
            next_excerpt=next_excerpt,
            gap_sec=gap_sec,
            is_last_bloc=is_last,
            model=model,
            max_words=remaining_budget_words,
        )
        if closing:
            closing_words = len(closing.split())
            if closing_words > remaining_budget_words:
                logger.warning(
                    f"   ⚠️ Closing bloc {bloc['bloc_number']} ignoré : "
                    f"{closing_words} mots > budget restant {remaining_budget_words}"
                )
                continue
            bloc["text"] = bloc["text"].rstrip() + "\n\n" + closing.strip()
            bloc["closing_added"] = True
            bloc["closing_text"] = closing.strip()
            bloc["closing_words"] = closing_words
            new_word_count = len(bloc["text"].split())
            bloc["word_count"] = new_word_count


def _synthesize_course_audio_to_fit(bloc, convert_to_speech, measure_duration_ms, pad_audio_to_duration):
    """
    Génère un bloc cours sans troncature brutale.
    Par défaut, on n'accélère pas la voix : si le texte est manifestement trop
    long, on échoue avant l'appel Fish Audio pour éviter de payer un TTS inutilisable.
    Un speedup local reste possible seulement si FORMATION_TTS_LOCAL_MAX_SPEEDUP > 1.
    """
    target_sec = bloc["target_sec"]
    max_voice_sec = target_sec - _COURSE_START_SILENCE_SECONDS
    api_speed = _course_tts_speed()
    attempts = []
    word_count = bloc.get("word_count") or len(bloc["text"].split())
    word_budget = _estimated_words_budget_for_course(target_sec, api_speed)

    if word_budget > 0 and word_count > word_budget:
        raise ValueError(
            f"Bloc {bloc['bloc_number']} trop long avant TTS "
            f"({word_count} mots > budget prudent {word_budget} mots à speed={api_speed}). "
            "Aucun appel Fish Audio lancé. Il faut générer moins de mots en amont "
            "ou réduire ce bloc avant synthèse."
        )

    audio_bytes = convert_to_speech(bloc["text"], speed=api_speed)
    raw_duration = measure_duration_ms(audio_bytes) / 1000
    attempts.append({"kind": "api", "speed": api_speed, "duration": raw_duration})

    if raw_duration <= max_voice_sec:
        final_bytes = pad_audio_to_duration(
            audio_bytes,
            target_sec,
            truncate_overflow=False,
        )
        return final_bytes, raw_duration, f"api_speed={api_speed}", attempts

    required_speedup = raw_duration / max_voice_sec
    max_speedup = _course_local_max_speedup()
    if max_speedup <= 1.0:
        raise ValueError(
            f"Bloc {bloc['bloc_number']} trop long pour {target_sec}s "
            f"(voix {raw_duration:.1f}s > max {max_voice_sec:.1f}s à speed={api_speed}). "
            "Speedup local désactivé par défaut pour préserver la voix. "
            "Audio non uploadé pour éviter une coupure en pleine phrase."
        )

    if required_speedup > max_speedup:
        raise ValueError(
            f"Bloc {bloc['bloc_number']} trop long pour {target_sec}s "
            f"(voix {raw_duration:.1f}s > max {max_voice_sec:.1f}s, "
            f"speedup requis x{required_speedup:.3f} > limite x{max_speedup:.3f}). "
            "Audio non uploadé pour éviter une coupure en pleine phrase."
        )

    import io
    from pydub import AudioSegment, effects

    source_audio = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
    # Petite marge parce que pydub.effects.speedup est approximatif.
    factors = [min(max_speedup, required_speedup * 1.005)]
    if factors[0] < max_speedup:
        factors.append(min(max_speedup, required_speedup * 1.02))

    for factor in factors:
        sped_audio = effects.speedup(
            source_audio,
            playback_speed=factor,
            chunk_size=150,
            crossfade=25,
        )
        out = io.BytesIO()
        sped_audio.export(out, format="mp3", bitrate="128k")
        sped_bytes = out.getvalue()
        sped_duration = measure_duration_ms(sped_bytes) / 1000
        attempts.append({"kind": "local_speedup", "factor": factor, "duration": sped_duration})

        if sped_duration <= max_voice_sec:
            final_bytes = pad_audio_to_duration(
                sped_bytes,
                target_sec,
                truncate_overflow=False,
            )
            return final_bytes, sped_duration, f"api_speed={api_speed}, local_x{factor:.3f}", attempts

    attempts_str = ", ".join(
        f"{a['kind']}={a.get('speed', a.get('factor'))}: {a['duration']:.1f}s"
        for a in attempts
    )
    raise ValueError(
        f"Bloc {bloc['bloc_number']} trop long pour {target_sec}s "
        f"(max voix {max_voice_sec:.1f}s). Tentatives locales: {attempts_str}. "
        "Audio non uploadé pour éviter une coupure en pleine phrase."
    )

# Chemins vers les fichiers de prompts (dans backend/prompts/ pour qu'ils soient
# embarqués dans l'artifact de déploiement backend — le workflow ne package que
# ./backend/, donc des fichiers à la racine du repo seraient introuvables en prod).
_PROMPT_FILE = os.path.join(
    os.path.dirname(__file__), "..", "prompts", "prompt-generation-tts-direct.md"
)
_PROMPT_FILE_SCRATCH = os.path.join(
    os.path.dirname(__file__), "..", "prompts", "prompt-generation-tts-scratch.md"
)

# Cache des prompts invalidé sur mtime du fichier source — permet d'éditer
# les prompts .md sans redémarrer le backend (watchmedo ne watch que *.py).
# Structure : (prompts_list, mtime) ou None.
_PASSE_PROMPTS = None           # mode expansion
_PASSE_PROMPTS_SCRATCH = None   # mode from_scratch


def _parse_passe_prompts_from_file(path: str) -> list:
    """Extrait les 3 blocs ``` ``` sous les titres ## PASSE N du fichier."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    pattern = r"## PASSE \d[^`]*```(.*?)```"
    matches = re.findall(pattern, content, re.DOTALL)
    if len(matches) < 3:
        raise ValueError(f"Impossible de trouver les 3 prompts dans {path} ({len(matches)} trouvés)")
    return [m.strip() for m in matches[:3]]


def _get_passe_prompts(from_scratch=False):
    """
    Retourne les 3 prompts (Passe 1/2/3) depuis le bon fichier .md.
    Recharge automatiquement si le fichier a été modifié depuis la dernière lecture.
    """
    global _PASSE_PROMPTS, _PASSE_PROMPTS_SCRATCH
    path = _PROMPT_FILE_SCRATCH if from_scratch else _PROMPT_FILE
    mtime = os.path.getmtime(path)

    cached = _PASSE_PROMPTS_SCRATCH if from_scratch else _PASSE_PROMPTS
    if cached is not None and cached[1] == mtime:
        return cached[0]

    prompts = _parse_passe_prompts_from_file(path)
    if from_scratch:
        _PASSE_PROMPTS_SCRATCH = (prompts, mtime)
    else:
        _PASSE_PROMPTS = (prompts, mtime)
    logger.info(f"📖 Prompts rechargés depuis {os.path.basename(path)}")
    return prompts


# ─── Extraction des sous-parties ─────────────────────────────────────────────

_EXTRACT_PROMPT = """Tu analyses un programme de formation professionnelle.
Ton rôle : identifier exactement 6 sous-parties distinctes qui couvriront une journée complète de formation.

Réponds UNIQUEMENT en JSON valide, sans aucun texte avant ou après :
{{
  "title": "Nom exact du titre professionnel préparé",
  "sub_parts": [
    "Nom précis de la sous-partie 1",
    "Nom précis de la sous-partie 2",
    "Nom précis de la sous-partie 3",
    "Nom précis de la sous-partie 4",
    "Nom précis de la sous-partie 5",
    "Nom précis de la sous-partie 6"
  ]
}}

Règles :
- Exactement 6 sous-parties (ni plus ni moins)
- Chaque nom doit être suffisamment précis pour orienter la génération d'environ 15 000 mots de cours oral
- Couvrir l'essentiel du programme sans répétition entre sous-parties
- Si le programme couvre 2 journées, prendre uniquement les sous-parties de la première moitié

PROGRAMME :
{program_text}"""


def _anthropic_post(messages, max_tokens, model=None):
    """Appel LLM compatible Anthropic (Anthropic ou DeepSeek selon config)."""
    return _llm_post(
        messages=messages,
        max_tokens=max_tokens,
        model=model or CLAUDE_MODEL,
        timeout=600,
    )


def extract_sub_parts(program_text):
    """
    Appelle Claude pour extraire 6 sous-parties depuis le programme.
    Synchrone — retourne {"title": str, "sub_parts": [str×6]} ou lève une exception.
    """
    prompt = _EXTRACT_PROMPT.replace("{program_text}", program_text[:15000])

    logger.info("🔍 Extraction des sous-parties avec Claude...")

    for attempt in range(3):
        try:
            raw = _anthropic_post(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
            ).strip()

            # Nettoyer au cas où Claude ajoute du texte avant/après le JSON
            json_match = re.search(r"\{[\s\S]*\}", raw)
            if not json_match:
                raise ValueError("Pas de JSON valide dans la réponse")

            data = json.loads(json_match.group())
            if "sub_parts" not in data or len(data["sub_parts"]) < 1:
                raise ValueError(f"Format incorrect : {list(data.keys())}")

            # Forcer exactement 6 sous-parties
            sub_parts = data["sub_parts"][:NUM_SUB_PARTS]
            while len(sub_parts) < NUM_SUB_PARTS:
                sub_parts.append(f"Sous-partie {len(sub_parts) + 1}")

            result = {"title": data.get("title", "Formation professionnelle"), "sub_parts": sub_parts}
            logger.info(f"✅ {len(result['sub_parts'])} sous-parties extraites pour : {result['title']}")
            return result

        except Exception as e:
            if attempt < 2:
                logger.warning(f"⚠️ Tentative extraction {attempt+1}/3 échouée : {e}, retry...")
                time.sleep(3)
            else:
                raise ValueError(f"Extraction échouée après 3 tentatives : {e}")


# ─── Génération d'un segment (une passe) ─────────────────────────────────────

def _generate_segment_text(passe, sub_part_name, program_title, program_text, prev_text,
                           from_scratch=False, module_content="", model=None):
    """
    Génère le texte d'un segment via Claude.
    passe : 1, 2 ou 3

    Mode expansion (from_scratch=False) — comportement historique :
      - prev_text : texte passe 1 pour passe 2, texte passe 1+2 pour passe 3

    Mode from_scratch (from_scratch=True) — nouveau pipeline formation :
      - Chaque passe génère depuis module_content (pas du texte précédent)
      - Passe 1 = Fondation, Passe 2 = Pratique, Passe 3 = Maîtrise

    Retourne le texte généré (~5 000 mots).
    """
    prompts = _get_passe_prompts(from_scratch=from_scratch)
    template = prompts[passe - 1]

    if from_scratch:
        # Mode from_scratch : toutes les passes reçoivent le contenu du module
        prompt = template
        prompt = prompt.replace("{NOM_DU_TITRE_PROFESSIONNEL}", program_title)
        prompt = prompt.replace("{NOM_DE_LA_SOUS_PARTIE}", sub_part_name)
        prompt = prompt.replace("{CONTENU_DU_MODULE}", (module_content or program_text)[:15000])
    else:
        # Mode expansion (comportement historique)
        if passe == 1:
            prompt = template
            prompt = prompt.replace("{NOM_DU_TITRE_PROFESSIONNEL}", program_title)
            prompt = prompt.replace("{NOM_DE_LA_SOUS_PARTIE}", sub_part_name)
            prompt = prompt.replace("{COLLER_LE_PROGRAMME_ICI}", program_text[:12000])
        elif passe == 2:
            prompt = template
            prompt = prompt.replace("{NOM_DU_TITRE_PROFESSIONNEL}", program_title)
            prompt = prompt.replace("{NOM_DE_LA_SOUS_PARTIE}", sub_part_name)
            prompt = prompt.replace("{COLLER_LE_TEXTE_DE_LA_PASSE_1}", prev_text[:40000])
        else:  # passe 3
            prompt = template
            prompt = prompt.replace("{NOM_DU_TITRE_PROFESSIONNEL}", program_title)
            prompt = prompt.replace("{NOM_DE_LA_SOUS_PARTIE}", sub_part_name)
            prompt = prompt.replace("{COLLER_LE_TEXTE_COMPLET_PASSE_1_ET_2}", prev_text[:60000])

    mode_label = "from_scratch" if from_scratch else "expansion"
    logger.info(f"  📝 Génération passe {passe} [{mode_label}] pour '{sub_part_name}'...")

    generated = None
    for attempt in range(3):
        try:
            generated = _anthropic_post(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=16000,
                model=model,
            )
            break
        except Exception as e:
            if attempt < 2:
                wait = 15 * (attempt + 1)
                logger.warning(f"  ⚠️ Retry {attempt+1}/3 dans {wait}s : {e}")
                time.sleep(wait)
            else:
                raise

    # Couche 2 — Boucle de continuation si volume insuffisant
    # La cible par passe est ~5 000 mots. Si Claude rend moins de 4 500,
    # on relance une continuation pour compléter. Max 2 continuations pour
    # éviter une boucle infinie + coût maîtrisé.
    MIN_WORDS = 4500
    TARGET_WORDS = 5000
    MAX_CONTINUATIONS = 2

    words = len(generated.split())
    logger.info(f"  ✅ Passe {passe} — 1er rendu : {words} mots")

    continuations = 0
    while words < MIN_WORDS and continuations < MAX_CONTINUATIONS:
        continuations += 1
        logger.info(f"  🔁 Passe {passe} sous seuil ({words}/{TARGET_WORDS} mots) — continuation {continuations}/{MAX_CONTINUATIONS}")

        # Prompt de continuation : on rappelle le contexte, on donne le texte
        # déjà écrit, on demande de poursuivre SANS reprendre le début.
        # Les règles éthiques/style sont héritées du premier prompt (même conversation).
        continuation_prompt = (
            f"Tu as écrit {words} mots sur un minimum exigé de {TARGET_WORDS}. "
            f"Continue le cours là où tu t'es arrêté, avec le même ton oral, "
            f"les mêmes règles TTS (tags Fish Audio, pas de musique/alcool/fêtes, "
            f"discours indirect, pas de visuel), et la même voix narrative.\n\n"
            f"CONSIGNE DE DÉVELOPPEMENT (minimum 1 800 mots supplémentaires) :\n"
            f"- 2 à 4 exemples fictifs supplémentaires dans des contextes variés\n"
            f"- 1 cas contraste explicite : ce qu'il ne FAUT PAS faire + pourquoi\n"
            f"- Nuances selon le profil client (novice vs expert, pressé vs exploratoire)\n"
            f"- Mini-récap oral à la fin de chaque nouvelle section\n\n"
            f"NE RÉPÈTE PAS ce qui a déjà été dit. Continue vraiment — enchaîne "
            f"avec une transition naturelle type \"Allons plus loin maintenant…\" "
            f"ou \"On va creuser un autre angle…\".\n\n"
            f"═══ TEXTE DÉJÀ ÉCRIT (à ne pas répéter) ═══\n"
            f"{generated[-6000:]}"  # on envoie juste la fin pour contexte
        )

        try:
            additional = _anthropic_post(
                messages=[{"role": "user", "content": continuation_prompt}],
                max_tokens=16000,
                model=model,
            )
            generated = generated.strip() + "\n\n" + additional.strip()
            words = len(generated.split())
            logger.info(f"  ➕ Passe {passe} après continuation {continuations} : {words} mots")
        except Exception as e:
            logger.warning(f"  ⚠️ Continuation {continuations} échouée : {e} — on garde le rendu actuel")
            break

    logger.info(f"  ✅ Passe {passe} terminée : {words} mots ({continuations} continuation(s))")
    return generated.strip()


# ─── Helpers DB ──────────────────────────────────────────────────────────────

def start_generation_job(folder_id: int, platform_id: int, program_text: str,
                         program_title: str, sub_parts_override: list = None,
                         module_contents: dict = None, from_scratch: bool = False,
                         model: str = None):
    """
    Crée le job DB et lance la génération en background thread.
    Utilisé par le pipeline formation automatisé.

    sub_parts_override : liste de noms de sous-parties (bypass extraction Claude)
    module_contents    : dict {sub_part_name: contenu_module} pour le mode from_scratch
    from_scratch       : True = passes indépendantes depuis module_content (nouveau paradigme)
    """
    import threading

    # Extraction des sous-parties si pas fournie
    if sub_parts_override:
        sub_parts = sub_parts_override[:NUM_SUB_PARTS]
        while len(sub_parts) < NUM_SUB_PARTS:
            sub_parts.append(f"Sous-partie {len(sub_parts) + 1}")
        title = program_title
    else:
        extracted = extract_sub_parts(program_text)
        sub_parts = extracted["sub_parts"]
        title = extracted.get("title", program_title) or program_title

    conn = get_db_connection()
    cursor = conn.cursor()
    # Supprimer anciens segments si réinitialisation
    cursor.execute("""
        DELETE FROM content_generation_segments WHERE job_id IN (
            SELECT id FROM content_generation_jobs WHERE folder_id = ?
        )
    """, (folder_id,))
    cursor.execute("""
        INSERT OR REPLACE INTO content_generation_jobs
            (folder_id, platform_id, program_text, program_title, sub_parts,
             from_scratch, module_contents,
             status, current_sub_part, current_passe, total_words, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'idle', 0, 1, 0, NULL)
    """, (
        folder_id, platform_id, program_text, title,
        json.dumps(sub_parts, ensure_ascii=False),
        1 if from_scratch else 0,
        json.dumps(module_contents or {}, ensure_ascii=False),
    ))
    conn.commit()
    conn.close()

    # Lancer génération en background
    def _run():
        try:
            run_content_generation(folder_id, mode="normal", model=model)
        except Exception as e:
            logger.error(f"❌ Génération background dossier {folder_id} : {e}")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    logger.info(f"🚀 Génération lancée en background pour dossier {folder_id} (from_scratch={from_scratch})")


def get_job_from_db(folder_id):
    """Retourne le job DB pour un dossier, ou None."""
    _ensure_carryover_columns()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT cgj.id, cgj.platform_id, cgj.program_text, cgj.program_title,
               cgj.sub_parts, cgj.status, cgj.current_sub_part,
               cgj.current_passe, cgj.total_words, cgj.error_message,
               cgj.from_scratch, cgj.module_contents,
               cgj.carryover_in_text, cgj.carryover_in_source_folder_id,
               cgj.carryover_out_text, cgj.carryover_out_target_folder_id,
               cf.formation_job_id, cf.name
        FROM content_generation_jobs cgj
        LEFT JOIN cours_folders cf ON cf.id = cgj.folder_id
        WHERE cgj.folder_id = ?
    """, (folder_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "platform_id": row[1], "program_text": row[2],
        "program_title": row[3], "sub_parts": json.loads(row[4] or "[]"),
        "status": row[5], "current_sub_part": row[6], "current_passe": row[7],
        "total_words": row[8], "error_message": row[9],
        "from_scratch": bool(row[10]),
        "module_contents": json.loads(row[11] or "{}"),
        "carryover_in_text": row[12] or "",
        "carryover_in_source_folder_id": row[13],
        "carryover_out_text": row[14] or "",
        "carryover_out_target_folder_id": row[15],
        "formation_job_id": row[16],
        "folder_name": row[17],
    }


def get_segments_status(job_id):
    """Retourne la liste des segments avec leur statut."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sub_part_index, sub_part_name, passe, status, word_count
        FROM content_generation_segments
        WHERE job_id = ?
        ORDER BY sub_part_index ASC, passe ASC
    """, (job_id,))
    rows = cursor.fetchall()
    conn.close()
    return [
        {"sub_part_index": r[0], "sub_part_name": r[1], "passe": r[2],
         "status": r[3], "word_count": r[4]}
        for r in rows
    ]


def _update_job_db(job_id, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [job_id]
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE content_generation_jobs SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        values,
    )
    conn.commit()
    conn.close()


def _get_completed_segments(job_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sub_part_index, passe FROM content_generation_segments
        WHERE job_id = ? AND status = 'completed'
    """, (job_id,))
    done = set((r[0], r[1]) for r in cursor.fetchall())
    conn.close()
    return done


def _save_segment_db(job_id, sub_idx, sub_part_name, passe, text):
    word_count = len(text.split())
    conn = get_db_connection()
    cursor = conn.cursor()
    # Un texte nouveau/réécrit doit être repris par le TTS (dirty=1), re-passé
    # par la révision conformité (reviewed=0) et invalider toute ancienne
    # erreur reviewer (review_error=NULL). Règle centrale héritée de
    # memoire/03-decisions/pipeline-dual-api-et-claude-code.md.
    cursor.execute("""
        INSERT OR REPLACE INTO content_generation_segments
            (job_id, sub_part_index, sub_part_name, passe, status,
             text_content, word_count, dirty, reviewed, review_error)
        VALUES (?, ?, ?, ?, 'completed', ?, ?, 1, 0, NULL)
    """, (job_id, sub_idx, sub_part_name, passe, text, word_count))
    conn.commit()
    conn.close()
    logger.info(f"  💾 Checkpoint : sous-partie {sub_idx+1}, passe {passe} ({word_count} mots)")


def mark_segment_modified(job_id: int, sub_idx: int, passe: int) -> None:
    """
    Marque un segment comme modifié : doit être re-synthétisé par le TTS
    (dirty=1), re-passé par la révision conformité (reviewed=0), et ses
    anciennes erreurs reviewer invalidées (review_error=NULL).

    À appeler depuis TOUS les endroits où `text_content` change :
    - _save_segment_db (génération/régénération) — déjà couvert via l'INSERT
    - route d'édition UI d'un segment — à appeler explicitement
    - apply_review_patch ci-dessous — à appeler explicitement
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE content_generation_segments
        SET dirty = 1, reviewed = 0, review_error = NULL
        WHERE job_id = ? AND sub_part_index = ? AND passe = ?
    """, (job_id, sub_idx, passe))
    conn.commit()
    conn.close()


def _get_segment_text(job_id, sub_idx, passe):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT text_content FROM content_generation_segments
        WHERE job_id = ? AND sub_part_index = ? AND passe = ?
    """, (job_id, sub_idx, passe))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else ""


# ─── Assemblage final ─────────────────────────────────────────────────────────

def _assemble_and_upload(folder_id, platform_id, job_id):
    """
    Concatène tous les segments complétés et uploade le texte final
    vers Azure comme document .txt dans le dossier.
    Retourne le nombre total de mots.
    """
    from services.azure_blob_service import upload_blob, CONTAINER_DOCUMENTS

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sub_part_index, passe, text_content
        FROM content_generation_segments
        WHERE job_id = ? AND status = 'completed'
        ORDER BY sub_part_index ASC, passe ASC
    """, (job_id,))
    rows = cursor.fetchall()
    conn.close()

    # Assembler dans l'ordre sous-partie → passe
    parts_by_idx = {}
    for sub_idx, passe, text in rows:
        parts_by_idx.setdefault(sub_idx, {})[passe] = text

    final_parts = []
    for sub_idx in sorted(parts_by_idx.keys()):
        for passe in sorted(parts_by_idx[sub_idx].keys()):
            final_parts.append(parts_by_idx[sub_idx][passe])

    full_text = "\n\n".join(final_parts)
    total_words = len(full_text.split())

    # Chemin blob unique
    file_uuid = uuid_mod.uuid4()
    blob_path = f"platform-{platform_id}/folder-{folder_id}/{file_uuid}.txt"
    original_name = f"cours_genere_{uuid_mod.uuid4().hex[:6]}.txt"

    upload_blob(CONTAINER_DOCUMENTS, blob_path, full_text.encode("utf-8"))

    # Enregistrer comme document dans la DB
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO cours_documents (folder_id, filename, original_name, status)
        VALUES (?, ?, ?, 'uploaded')
    """, (folder_id, blob_path, original_name))
    conn.commit()
    conn.close()

    logger.info(f"✅ Texte final : {total_words} mots → {blob_path}")
    return total_words, original_name


# ─── Pipeline principale ──────────────────────────────────────────────────────

def run_content_generation(folder_id, on_progress=None, mode="normal", model=None):
    """
    Lance ou reprend la génération de contenu pour un dossier.
    Doit être appelé dans un greenlet eventlet (non-bloquant).

    on_progress(sub_idx, total_sub_parts, passe, total_words, message) — callback optionnel.

    mode :
      "normal" — génération complète via Claude (~90 000 mots)
      "mock"   — texte factice instantané, 0 appel Claude (pour tests)
      "mini"   — 1 seule sous-partie × 1 seule passe, max_tokens 300 (~0.02€)
    """

    def _progress(sub_idx, passe, total_words, message):
        if on_progress:
            on_progress(sub_idx, NUM_SUB_PARTS, passe, total_words, message)

    job = get_job_from_db(folder_id)
    if not job:
        raise ValueError(f"Aucun job trouvé pour le dossier {folder_id}")

    job_id = job["id"]
    formation_job_id = job.get("formation_job_id")
    platform_id = job["platform_id"]
    program_text = job["program_text"]
    program_title = job["program_title"]
    sub_parts = job["sub_parts"]
    from_scratch = job.get("from_scratch", False)
    module_contents = job.get("module_contents", {})

    is_mock = mode == "mock"
    is_mini = mode == "mini"

    started_at = time.time()
    logger.info(
        "PIPELINE_CONTENT_START formation_job_id=%s content_job_id=%s folder_id=%s platform_id=%s mode=%s model=%s "
        "from_scratch=%s sub_parts=%s existing_words=%s",
        formation_job_id,
        job_id,
        folder_id,
        platform_id,
        mode,
        model or CLAUDE_MODEL,
        bool(from_scratch),
        len(sub_parts or []),
        job.get("total_words") or 0,
    )

    if formation_job_id:
        try:
            from services.formation_pipeline_service import is_expected_course_folder
            if not is_expected_course_folder(formation_job_id, folder_id):
                msg = (
                    "Folder doublon ignore : il ne correspond pas a une "
                    "journee canonique du programme valide."
                )
                _update_job_db(job_id, status="ignored_duplicate", error_message=msg)
                logger.warning(
                    "PIPELINE_CONTENT_DUPLICATE_SKIPPED formation_job_id=%s content_job_id=%s folder_id=%s",
                    formation_job_id,
                    job_id,
                    folder_id,
                )
                return
        except Exception:
            logger.warning(
                "PIPELINE_CONTENT_CANONICAL_GUARD_FAILED formation_job_id=%s content_job_id=%s folder_id=%s",
                formation_job_id,
                job_id,
                folder_id,
                exc_info=True,
            )

    if is_mock:
        logger.info(f"🧪 MODE MOCK — génération factice pour dossier {folder_id}")
    elif is_mini:
        logger.info(f"🧪 MODE MINI — 1 sous-partie × 1 passe, 300 tokens")

    _update_job_db(job_id, status="running", error_message=None)

    try:
        done_set = _get_completed_segments(job_id)
        total_words = job["total_words"] or 0
        logger.info(
            "PIPELINE_CONTENT_RESUME_STATE formation_job_id=%s content_job_id=%s folder_id=%s completed_segments=%s total_words=%s",
            formation_job_id,
            job_id,
            folder_id,
            len(done_set),
            total_words,
        )

        # En mode mini : seulement la première sous-partie, passe 1
        sub_parts_to_run = [sub_parts[0]] if is_mini else sub_parts
        passes_to_run = [1] if is_mini else [1, 2, 3]

        for sub_idx, sub_part_name in enumerate(sub_parts_to_run):
            logger.info(
                "PIPELINE_CONTENT_SUBPART_START formation_job_id=%s content_job_id=%s folder_id=%s sub_part=%s/%s name=%s",
                formation_job_id,
                job_id,
                folder_id,
                sub_idx + 1,
                len(sub_parts_to_run),
                sub_part_name,
            )
            passe1_text = _get_segment_text(job_id, sub_idx, 1) if (sub_idx, 1) in done_set else ""
            passe1_2_text = (
                passe1_text + "\n\n" + _get_segment_text(job_id, sub_idx, 2)
                if (sub_idx, 2) in done_set else ""
            )

            for passe in passes_to_run:
                if (sub_idx, passe) in done_set:
                    logger.info(
                        "PIPELINE_CONTENT_SEGMENT_SKIP formation_job_id=%s content_job_id=%s folder_id=%s sub_part=%s passe=%s reason=already_completed",
                        formation_job_id,
                        job_id,
                        folder_id,
                        sub_idx + 1,
                        passe,
                    )
                    continue

                msg = f"Sous-partie {sub_idx + 1}/{NUM_SUB_PARTS} · Passe {passe}/3 — {sub_part_name}"
                if is_mock:
                    msg = f"[MOCK] {msg}"
                _progress(sub_idx, passe, total_words, msg)
                _update_job_db(job_id, current_sub_part=sub_idx, current_passe=passe)
                segment_started_at = time.time()
                logger.info(
                    "PIPELINE_CONTENT_SEGMENT_START formation_job_id=%s content_job_id=%s folder_id=%s sub_part=%s/%s passe=%s/%s mode=%s total_words_before=%s",
                    formation_job_id,
                    job_id,
                    folder_id,
                    sub_idx + 1,
                    len(sub_parts_to_run),
                    passe,
                    len(passes_to_run),
                    mode,
                    total_words,
                )

                if is_mock:
                    time.sleep(0.8)  # Simule un délai réaliste
                    text = _generate_mock_text(passe, sub_part_name, sub_idx)
                elif is_mini:
                    text = _generate_segment_mini(sub_part_name, program_title, program_text)
                elif from_scratch:
                    # Mode from_scratch : chaque passe génère depuis le contenu du module
                    module_content = module_contents.get(sub_part_name, "")
                    text = _generate_segment_text(
                        passe, sub_part_name, program_title, program_text,
                        prev_text="", from_scratch=True, module_content=module_content,
                        model=model,
                    )
                else:
                    prev = "" if passe == 1 else (passe1_text if passe == 2 else passe1_2_text)
                    text = _generate_segment_text(passe, sub_part_name, program_title, program_text, prev, model=model)

                _save_segment_db(job_id, sub_idx, sub_part_name, passe, text)
                words_added = len(text.split())
                total_words += words_added
                _update_job_db(job_id, total_words=total_words)
                logger.info(
                    "PIPELINE_CONTENT_SEGMENT_DONE formation_job_id=%s content_job_id=%s folder_id=%s sub_part=%s passe=%s "
                    "words_added=%s total_words=%s duration_ms=%s",
                    formation_job_id,
                    job_id,
                    folder_id,
                    sub_idx + 1,
                    passe,
                    words_added,
                    total_words,
                    int((time.time() - segment_started_at) * 1000),
                )

                if passe == 1:
                    passe1_text = text
                elif passe == 2:
                    passe1_2_text = passe1_text + "\n\n" + text

        # En mode mini : marquer completed sans upload (pas de texte complet)
        if is_mini:
            _update_job_db(job_id, status="completed", total_words=total_words)
            _progress(1, 1, total_words, f"✅ [MINI] 1 segment généré ({total_words} mots) — pas d'upload Azure")
            logger.info(
                "PIPELINE_CONTENT_DONE formation_job_id=%s content_job_id=%s folder_id=%s mode=mini total_words=%s duration_ms=%s",
                formation_job_id,
                job_id,
                folder_id,
                total_words,
                int((time.time() - started_at) * 1000),
            )
            return

        # Assemblage + upload
        _progress(NUM_SUB_PARTS, 3, total_words, "Assemblage et upload du texte final...")
        logger.info(
            "PIPELINE_CONTENT_ASSEMBLY_START formation_job_id=%s content_job_id=%s folder_id=%s words_before_assembly=%s",
            formation_job_id,
            job_id,
            folder_id,
            total_words,
        )
        final_words, filename = _assemble_and_upload(folder_id, platform_id, job_id)

        _update_job_db(job_id, status="completed", total_words=final_words)
        _progress(NUM_SUB_PARTS, 3, final_words, f"✅ Terminé : {final_words} mots — fichier {filename} ajouté aux sources")
        logger.info(
            "PIPELINE_CONTENT_DONE formation_job_id=%s content_job_id=%s folder_id=%s final_words=%s filename=%s duration_ms=%s",
            formation_job_id,
            job_id,
            folder_id,
            final_words,
            filename,
            int((time.time() - started_at) * 1000),
        )

    except Exception as e:
        logger.exception(
            "PIPELINE_CONTENT_ERROR formation_job_id=%s content_job_id=%s folder_id=%s duration_ms=%s error=%s",
            formation_job_id,
            job_id,
            folder_id,
            int((time.time() - started_at) * 1000),
            e,
        )
        _update_job_db(job_id, status="error", error_message=str(e))
        raise


def _playlist_items_for_platform(platform_id: int) -> list:
    """Retourne la playlist effective de la plateforme au format PLAYLIST_SPEC."""
    from services.playlist_tts_service import PLAYLIST_SPEC
    bloc_by_filename = {spec[0]: spec[3] for spec in PLAYLIST_SPEC}

    try:
        from services.audio_service import get_playlist
        playlist = get_playlist(platform_id)
    except Exception as e:
        logger.warning(f"⚠️ Playlist plateforme indisponible, fallback PLAYLIST_SPEC : {e}")
        return list(PLAYLIST_SPEC)

    items = []
    for item in playlist:
        filename = os.path.basename((item.get("filename") or "").split("?", 1)[0])
        file_type = item.get("type")
        duration = int(item.get("duration") or 0)
        bloc_num = bloc_by_filename.get(filename)
        if bloc_num is None:
            # Fallback : extraire depuis le nom des fichiers cours_N impossible ici,
            # donc garder 1 pour éviter None dans les prompts.
            bloc_num = 1
        items.append((filename, duration, file_type, bloc_num))
    return items or list(PLAYLIST_SPEC)


def _build_edge_muted_filler_audio(duration_sec: float, on_progress=None) -> tuple[bytes, float]:
    """Build near-silence with Edge TTS itself, keeping the MP3 format uniform.

    We deliberately do not reuse `assets/silence_1s.mp3`: that file has a
    different sample rate/bitrate and was the root of the 302:01 browser bug.
    Edge TTS with volume=-100% gives compatible 24 kHz / 48 kbps frames.
    """
    if duration_sec <= 0:
        return b"", 0.0

    from services.basic_tts_service import convert_to_speech_basic, concat_mp3_bytes

    filler_text = os.getenv("EDGE_TTS_MUTED_FILLER_TEXT", "un.").strip() or "un."
    filler_volume = os.getenv("EDGE_TTS_MUTED_FILLER_VOLUME", "-100%").strip() or "-100%"

    if on_progress:
        on_progress(f"filler muet Edge TTS ({duration_sec:.1f}s cible)")

    seed = convert_to_speech_basic(
        filler_text,
        volume=filler_volume,
        **_basic_tts_pipeline_retry_kwargs(),
    )
    seed_duration = _mp3_duration_seconds_no_ffprobe(seed)
    if seed_duration <= 0:
        return b"", 0.0

    repeat = int(duration_sec // seed_duration)
    if repeat <= 0:
        return b"", 0.0

    filler = concat_mp3_bytes([seed] * repeat)
    return filler, seed_duration * repeat


def _build_timed_edge_break_audio(
    intro_text: str,
    outro_text: str,
    duration_sec: int,
    *,
    on_progress=None,
) -> tuple[bytes, float]:
    """Build an Edge TTS break with intro at start and outro at slot end."""
    from services.basic_tts_service import convert_to_speech_basic, concat_mp3_bytes

    intro_text = (intro_text or "").strip()
    outro_text = (outro_text or "").strip()
    if not intro_text and not outro_text:
        raise ValueError("Break Edge vide")

    parts = []
    cursor_sec = 0.0
    lead_in_sec = _env_float("EDGE_TTS_BREAK_LEAD_IN_SEC", 5.0, min_value=0.0, max_value=30.0)

    lead_bytes, lead_duration = _build_edge_muted_filler_audio(
        lead_in_sec,
        on_progress=on_progress,
    )
    if lead_bytes:
        parts.append(lead_bytes)
        cursor_sec += lead_duration

    if intro_text:
        if on_progress:
            on_progress("Edge TTS intro")
        intro_bytes = convert_to_speech_basic(
            intro_text,
            progress_callback=on_progress,
            **_basic_tts_pipeline_retry_kwargs(),
        )
        cursor_sec += _mp3_duration_seconds_no_ffprobe(intro_bytes)
        parts.append(intro_bytes)

    outro_bytes = b""
    outro_duration = 0.0
    if outro_text:
        if on_progress:
            on_progress("Edge TTS outro")
        outro_bytes = convert_to_speech_basic(
            outro_text,
            progress_callback=on_progress,
            **_basic_tts_pipeline_retry_kwargs(),
        )
        outro_duration = _mp3_duration_seconds_no_ffprobe(outro_bytes)

    target = float(max(int(duration_sec or 0), 0))
    filler_target = max(0.0, target - cursor_sec - outro_duration)
    filler_bytes, filler_duration = _build_edge_muted_filler_audio(
        filler_target,
        on_progress=on_progress,
    )
    if filler_bytes:
        parts.append(filler_bytes)
        cursor_sec += filler_duration

    if outro_bytes:
        parts.append(outro_bytes)
        cursor_sec += outro_duration

    return concat_mp3_bytes(parts), cursor_sec


def _course_opening_transitions_enabled() -> bool:
    value = (os.getenv("COURSE_OPENING_TRANSITIONS", "true") or "").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _split_opening_for_rewrite(text: str, max_sentences: int = 3, max_words: int = 90) -> tuple[str, str]:
    clean = (text or "").strip()
    if not clean:
        return "", ""

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(clean) if s.strip()]
    if not sentences:
        return clean, ""

    opening_parts = []
    opening_words = 0
    for sentence in sentences:
        opening_parts.append(sentence)
        opening_words += len(sentence.split())
        if len(opening_parts) >= max_sentences or opening_words >= max_words:
            break

    opening = " ".join(opening_parts).strip()
    rest = " ".join(sentences[len(opening_parts):]).strip()
    return opening, rest


def _parse_course_opening_json(raw: str) -> str:
    data = _extract_llm_json(raw)
    opening = re.sub(r"\s+", " ", (data.get("opening") or "").strip())
    if len(opening.split()) < 12:
        raise ValueError("opening trop courte")
    return opening


def _parse_course_handoff_json(raw: str) -> tuple[str, str]:
    data = _extract_llm_json(raw)
    opening = re.sub(r"\s+", " ", (data.get("opening") or "").strip())
    rewritten_start = re.sub(r"\s+", " ", (data.get("rewritten_start") or "").strip())
    if len(opening.split()) < 10:
        raise ValueError("opening trop courte")
    if len(rewritten_start.split()) < 12:
        raise ValueError("rewritten_start trop court")
    return opening, rewritten_start


def _fallback_course_opening(opening: str, previous_item_type: str | None) -> tuple[str, str]:
    if previous_item_type in {"pause", "pause_midi"}:
        lead = "Très bien, on se remet tranquillement dans le fil."
    elif previous_item_type == "qa":
        lead = "Très bien, on garde vos questions en tête et on avance dans la suite."
    else:
        lead = "Très bien, on continue avec la suite."
    opening = re.sub(r"\s+", " ", (opening or "").strip())
    return lead, f"Pour entrer dans cette partie, on va reprendre l'idée proprement : {opening}"


def _rewrite_course_opening_for_audio(
    bloc: dict,
    playlist_items: list,
    item_idx: int,
    *,
    model: str | None = None,
    previous_excerpt: str = "",
) -> tuple[str, dict]:
    """Build an oral handoff and rewrite the first sentences of a course audio."""
    text = (bloc.get("text") or "").strip()
    bloc_number = int(bloc.get("bloc_number") or 0)
    if not text or not _course_opening_transitions_enabled():
        return text, {}

    opening, rest = _split_opening_for_rewrite(text)
    if not opening:
        return text, {}

    previous_item_type = playlist_items[item_idx - 1][2] if item_idx > 0 else None
    previous_label = {
        "qa": "une séance de questions-réponses",
        "pause": "une pause courte",
        "pause_midi": "la pause déjeuner",
        "cours": "un cours",
        None: "le début de journée",
    }.get(previous_item_type, str(previous_item_type))

    rest_preview = " ".join(rest.split()[:90])
    prompt = f"""Tu écris l'amorce audio d'un bloc de cours pour une classe virtuelle.

BLOC COURS : {bloc_number}/7
ÉLÉMENT JUSTE AVANT CE COURS : {previous_label}

CONTEXTE PRÉCÉDENT DISPONIBLE :
---
{previous_excerpt or "(aucun contexte précédent disponible)"}
---

DÉBUT ACTUEL À AMORCER ET REMANIER :
---
{opening}
---

SUITE IMMÉDIATE QUI VIENDRA APRÈS TON OUVERTURE :
---
{rest_preview}
---

MISSION :
Crée une vraie amorce orale, puis reformule légèrement le début actuel.
Le fichier ne doit pas reprendre brutalement à la phrase exacte où le cours s'était arrêté.
Il faut relancer l'idée proprement, comme un formateur qui reprend le fil en direct.

CONSIGNES STRICTES :
- Tu peux situer brièvement le fil, mais ne fais pas un résumé long du cours précédent.
- Ne répète pas la conclusion, le Q&A ou la pause qui viennent déjà d'avoir lieu.
- Si l'élément précédent est une pause, ne dis pas "la pause est terminée".
- Ne spoile pas tout le bloc : ouvre seulement la porte du sujet.
- Ne change pas le fond : conserve les idées du début actuel.
- Ne recopie pas littéralement le début actuel : reformule sur le vif, naturellement.
- L'amorce doit faire 25 à 55 mots.
- Le début reformulé doit faire 35 à 85 mots.
- Termine le début reformulé de façon à enchaîner naturellement avec la suite immédiate.
- Pas d'horaires, pas de markdown, pas de guillemets.

Réponds uniquement avec ce JSON valide :
{{
  "opening": "amorce de transition",
  "rewritten_start": "début actuel reformulé"
}}"""

    try:
        raw = _llm_post(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=700,
            model=model or CLAUDE_MODEL,
            timeout=90,
        )
        opening_text, rewritten_start = _parse_course_handoff_json(raw)
    except Exception as e:
        logger.warning(
            "⚠️ Ouverture bloc %s fallback (%s: %s)",
            bloc_number,
            type(e).__name__,
            str(e)[:160],
        )
        opening_text, rewritten_start = _fallback_course_opening(opening, previous_item_type)

    rewritten_text = "\n\n".join(
        part.strip()
        for part in (opening_text, rewritten_start, rest)
        if part and part.strip()
    ).strip()
    return rewritten_text, {
        "opening_text": opening_text,
        "rewritten_start": rewritten_start,
        "original_start": opening,
    }


def _rewrite_runtime_carryover_chunks(
    prepended_chunks: list,
    base_chunks: list,
    *,
    bloc_number: int,
    model: str | None = None,
) -> tuple[list, dict]:
    """Amorce and lightly rewrites text carried from the previous audio block."""
    if not prepended_chunks or not _course_opening_transitions_enabled():
        return list(prepended_chunks or []), {}

    chunks = [dict(chunk) for chunk in prepended_chunks]
    first = chunks[0]
    first_text = (first.get("text") or "").strip()
    if not first_text:
        return chunks, {}

    opening, rest = _split_opening_for_rewrite(first_text)
    if not opening:
        return chunks, {}

    carried_preview = "\n\n".join(
        (chunk.get("text") or "").strip()
        for chunk in chunks[:3]
        if (chunk.get("text") or "").strip()
    )
    base_preview = "\n\n".join(
        (chunk.get("text") or "").strip()
        for chunk in (base_chunks or [])[:2]
        if (chunk.get("text") or "").strip()
    )

    prompt = f"""Tu écris l'amorce d'un cours audio qui reprend un passage reporté
depuis le fichier audio précédent.

CONTEXTE :
- Bloc cours actuel : {bloc_number}/7.
- Le début ci-dessous n'est pas un nouveau texte indépendant : c'est un passage
  qui n'a pas été lu dans le cours précédent, et qui doit maintenant être relancé
  proprement.

DÉBUT REPORTÉ À AMORCER ET REMANIER :
---
{_compact_words(opening, 140)}
---

PASSAGE REPORTÉ AUTOUR :
---
{_compact_words(carried_preview, 320)}
---

DÉBUT DU BLOC PRÉVU APRÈS LE REPORT :
---
{_compact_words(base_preview, 180) or "(indisponible)"}
---

MISSION :
Crée une amorce orale puis reformule légèrement le début reporté.
On ne doit pas reprendre brutalement à la phrase exacte où le cours précédent
s'était arrêté. Il faut réinstaller l'idée, puis la lancer naturellement.

CONSIGNES :
- Ne fais pas semblant de répondre à des questions.
- Ne parle pas de fichier audio, de découpage technique, de chunk ou de report.
- Tu peux dire sobrement qu'on reprend le fil ou qu'on pose le point proprement.
- Ne change pas le fond.
- Ne recopie pas littéralement le début reporté.
- "opening" : 25 à 55 mots.
- "rewritten_start" : 35 à 85 mots.
- Pas d'horaires, pas de markdown, pas de guillemets.

Réponds uniquement avec ce JSON valide :
{{
  "opening": "amorce de reprise",
  "rewritten_start": "début reporté reformulé"
}}"""

    try:
        raw = _llm_post(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=700,
            model=model or CLAUDE_MODEL,
            timeout=90,
        )
        opening_text, rewritten_start = _parse_course_handoff_json(raw)
    except Exception as e:
        logger.warning(
            "⚠️ Amorce runtime carryover bloc %s fallback (%s: %s)",
            bloc_number,
            type(e).__name__,
            str(e)[:160],
        )
        clean_opening = re.sub(r"\s+", " ", opening).strip()
        opening_text = "On reprend maintenant le fil du point que nous avions gardé pour la suite."
        rewritten_start = f"Pour le poser clairement, {clean_opening}"

    first["text"] = "\n\n".join(
        part.strip()
        for part in (opening_text, rewritten_start, rest)
        if part and part.strip()
    ).strip()
    chunks[0] = first
    return chunks, {
        "opening_text": opening_text,
        "rewritten_start": rewritten_start,
        "original_start": opening,
    }


def _build_contextual_break_audio(
    filename: str,
    duration_sec: int,
    file_type: str,
    bloc_num: int,
    item_idx: int,
    playlist_items: list,
    blocs_by_number: dict,
    mock: bool = False,
    basic_tts: bool = False,
    llm_model: str | None = None,
    on_progress=None,
    use_runtime_consumed_text: bool = False,
):
    """Génère un Q&A/pause contextuel, fallback vers audioqapause si nécessaire."""
    from services.playlist_tts_service import (
        _build_pause_audio,
        _generate_silence_mp3,
        _get_recycled_qa_pause,
    )

    def _emit(message: str):
        if on_progress:
            on_progress(message)

    def _fallback(reason: str):
        _emit(f"{filename} — audio pause réutilisable ({reason})...")
        try:
            return _get_recycled_qa_pause(filename), "audioqapause_fallback"
        except Exception as fallback_error:
            logger.warning(
                f"⚠️ Break fallback {filename} indisponible ({fallback_error}); "
                "silence de secours"
            )
            _emit(f"{filename} — audio pause réutilisable indisponible, silence de secours")
            return _generate_silence_mp3(min(max(int(duration_sec or 1), 1), 10)), "silence_fallback"

    def _generic_break_texts():
        from services.playlist_tts_service import (
            _get_pause_midi_text,
            _get_pause_text,
            _get_qa_text,
        )
        if file_type == "qa":
            return _get_qa_text(bloc_num)
        if file_type == "pause_midi" or filename.startswith("pause_midi_"):
            return _get_pause_midi_text()
        return _get_pause_text(bloc_num)

    def _generic_basic_tts_break():
        intro, outro = _generic_break_texts()
        audio_bytes, final_duration = _build_timed_edge_break_audio(
            intro,
            outro,
            duration_sec,
            on_progress=lambda msg: _emit(f"{filename} — {msg}"),
        )
        _emit(
            f"{filename} — Edge TTS générique calé ({final_duration:.1f}s/{duration_sec}s)"
        )
        return audio_bytes, "generic_edge_timed"

    if mock:
        return _generate_silence_mp3(1), "mock"

    contextual_basic_tts = os.getenv("BASIC_TTS_CONTEXTUAL_BREAKS", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if basic_tts and not contextual_basic_tts:
        try:
            return _generic_basic_tts_break()
        except Exception as e:
            logger.warning(
                f"⚠️ Break générique Edge {filename} échoué : {e}; fallback audioqapause"
            )
            return _fallback("generic_edge_failed")

    try:
        from services.break_transition_service import build_break_transition_texts

        _emit(f"{filename} — rédaction transition LLM...")
        def _get_bloc_text_for_break(n):
            bloc = blocs_by_number.get(n, {})
            if use_runtime_consumed_text:
                return bloc.get("runtime_consumed_text", "")
            return bloc.get("text", "")

        intro, outro = build_break_transition_texts(
            filename=filename,
            duration_sec=duration_sec,
            break_type=file_type,
            bloc_num=bloc_num,
            item_idx=item_idx,
            playlist_items=playlist_items,
            get_bloc_text=_get_bloc_text_for_break,
            model=llm_model,
        )
        _emit(f"{filename} — synthèse audio transition...")
        if basic_tts:
            audio_bytes, final_duration = _build_timed_edge_break_audio(
                intro,
                outro,
                duration_sec,
                on_progress=lambda msg: _emit(f"{filename} — {msg}"),
            )
            _emit(
                f"{filename} — transition Edge TTS calée "
                f"({final_duration:.1f}s/{duration_sec}s)"
            )
            return audio_bytes, "contextual_edge_timed"
        return _build_pause_audio(intro, outro, duration_sec), "contextual_fish"
    except Exception as e:
        logger.warning(f"⚠️ Break contextuel {filename} échoué : {e}; fallback audioqapause")
        return _fallback(type(e).__name__)


def _mark_content_segments_clean(job_id: int, seg_keys) -> None:
    unique_keys = sorted(set(seg_keys or []))
    if not unique_keys:
        return

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        for sub_idx, passe in unique_keys:
            cur.execute("""
                UPDATE content_generation_segments
                SET dirty = 0
                WHERE job_id = ? AND sub_part_index = ? AND passe = ?
            """, (job_id, sub_idx, passe))
        conn.commit()
    finally:
        conn.close()


def _allow_audio_overflow_lost() -> bool:
    return os.getenv("ALLOW_AUDIO_OVERFLOW_LOST", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _finalize_runtime_fit_carryover_and_clean(
    *,
    job_id: int,
    pending_clean_seg_keys,
    runtime_carryover_text: str,
    carryover_out: str,
    folder_id: int,
    next_folder_id: int | None,
    is_last_folder: bool,
    formation_job_id: int | None,
) -> str:
    runtime_carryover_text = (runtime_carryover_text or "").strip()

    if runtime_carryover_text:
        runtime_words = len(runtime_carryover_text.split())
        if next_folder_id and not is_last_folder:
            fused_carryover = runtime_carryover_text
            if carryover_out:
                fused_carryover = runtime_carryover_text + "\n\n" + carryover_out
            _store_cross_day_carryover(folder_id, next_folder_id, fused_carryover)
            carryover_out = fused_carryover
            logger.info(
                "PIPELINE_AUDIO_RUNTIME_CARRYOVER formation_job_id=%s folder_id=%s "
                "next_folder_id=%s runtime_words=%s total_carryover_words=%s",
                formation_job_id, folder_id, next_folder_id,
                runtime_words, len(fused_carryover.split()),
            )
        elif _allow_audio_overflow_lost():
            logger.warning(
                "PIPELINE_AUDIO_OVERFLOW_LOST formation_job_id=%s folder_id=%s "
                "lost_words=%s reason=no_next_folder is_last_folder=%s",
                formation_job_id, folder_id, runtime_words, is_last_folder,
            )
        else:
            raise ValueError(
                "Surplus audio runtime non consommé sans jour suivant "
                f"({runtime_words} mots, folder_id={folder_id}). "
                "Définir ALLOW_AUDIO_OVERFLOW_LOST=true pour autoriser une perte explicite."
            )

    _mark_content_segments_clean(job_id, pending_clean_seg_keys)
    return carryover_out


def generate_audio_from_script(
    folder_id,
    on_progress=None,
    force_all=False,
    mock=False,
    basic_tts=False,
    next_folder_id=None,
    is_last_folder=None,
    sync_slides=False,
    auto_generate_slides=False,
    slide_max_slides=60,
    slide_pace="normal",
    slide_model=None,
    llm_model=None,
    fast_tts_pipeline=False,
):
    """
    Génère (ou régénère) la playlist MP3 depuis le script TTS stocké en DB :
    7 blocs cours + Q&A/pauses contextuels quand le mode n'est pas mock.

    3 modes possibles (priorité décroissante) :
    - mock=True        → MP3 silence 1s, test gratuit (pas d'audio réel)
    - basic_tts=True   → gTTS (Google TTS gratuit), voix naturelle basique
    - (défaut)         → Fish Audio S2-Pro, voix studio payante

    Logique de régénération sélective :
    - Assemble les segments en ordre (sub_part × passe)
    - Découpe le texte total en 7 blocs proportionnels, sur fins de paragraphes/phrases
    - Pour chaque bloc, vérifie si au moins un segment contributeur est dirty=1
    - Si dirty (ou force_all=True) → génère le TTS + upload Azure
    - sync_slides=True découpe les blocs cours selon le dernier deck de slides
      persistant, puis stocke les timings slide → audio.
    - Si propre → conserve l'ancien MP3

    Après génération réussie d'un bloc : marque ses segments dirty=0.
    """
    from services.playlist_tts_service import (
        COURS_DURATIONS_MIN, PLAYLIST_SPEC, _pad_audio_to_duration, _measure_duration_ms
    )
    from services.tts_service import convert_to_speech
    from services.azure_blob_service import upload_blob, CONTAINER_AUDIOS

    def _progress(step, total, msg):
        if on_progress:
            on_progress(step, total, msg)

    # 1er event audio_progress émis dès l'entrée pour que la barre
    # « Playlist TTS X/19 » apparaisse côté frontend, avant les ~6 min de
    # préparation (chargement segments, découpage en blocs, transitions,
    # slides). Sinon l'utilisateur voit « Aucun événement audio reçu »
    # tout le temps de la préparation et croit que rien ne tourne.
    # `total` corrigera tout seul plus bas une fois `playlist_items` calculé.
    _progress(0, len(PLAYLIST_SPEC), "Préparation TTS — chargement du script et découpage…")

    job = get_job_from_db(folder_id)
    if not job:
        raise ValueError(f"Aucun script TTS pour le dossier {folder_id}")

    platform_id = job["platform_id"]
    job_id = job["id"]
    formation_job_id = job.get("formation_job_id")
    started_at = time.time()
    logger.info(
        "PIPELINE_AUDIO_START formation_job_id=%s content_job_id=%s folder_id=%s platform_id=%s force_all=%s mock=%s basic_tts=%s "
        "sync_slides=%s auto_generate_slides=%s slide_max_slides=%s slide_pace=%s llm_model=%s fast_tts_pipeline=%s",
        formation_job_id,
        job_id,
        folder_id,
        platform_id,
        force_all,
        mock,
        basic_tts,
        sync_slides,
        auto_generate_slides,
        slide_max_slides,
        slide_pace,
        llm_model,
        bool(fast_tts_pipeline),
    )
    if next_folder_id is None:
        next_folder_id = _find_next_folder_id(platform_id, folder_id)
    if is_last_folder is None:
        is_last_folder = next_folder_id is None

    slide_deck = None
    if sync_slides:
        from services.script_slide_generation_service import (
            generate_slides_from_script,
            get_latest_script_slide_deck,
        )
        slide_deck = get_latest_script_slide_deck(folder_id, content_job_id=job_id)
        if not slide_deck and auto_generate_slides:
            logger.info(
                f"🖼️ Folder {folder_id}: aucun deck slides, génération automatique avant TTS sync"
            )
            generate_slides_from_script(
                folder_id=folder_id,
                platform_id=platform_id,
                max_slides=slide_max_slides,
                pace=slide_pace,
                model=slide_model,
            )
            slide_deck = get_latest_script_slide_deck(folder_id, content_job_id=job_id)
        if not slide_deck:
            raise ValueError(
                f"Aucun deck de slides persistant pour le dossier {folder_id}. "
                "Générez les slides d'abord ou relancez avec auto_generate_slides=true."
            )
        logger.info(
            f"🖼️ Folder {folder_id}: TTS sync slides activé "
            f"(deck={slide_deck['deck_id']}, slides={len(slide_deck.get('slides') or [])})"
        )

    # ── 1. Charger tous les segments complétés dans l'ordre ──
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sub_part_index, passe, text_content, word_count, dirty
        FROM content_generation_segments
        WHERE job_id = ? AND status = 'completed'
        ORDER BY sub_part_index ASC, passe ASC
    """, (job_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        raise ValueError("Aucun segment généré — lancez d'abord la génération du script")

    # Construire la liste ordonnée des segments avec leur index global
    segments = []
    for r in rows:
        text = r[2] or ""
        if sync_slides:
            text = _strip_tts_tags_for_sync(text)
        segments.append({
            "sub_idx": r[0],
            "passe": r[1],
            "text": text,
            "word_count": len(text.split()) if sync_slides else r[3],
            "dirty": bool(r[4]),
        })

    carryover_in = (job.get("carryover_in_text") or "").strip()
    if carryover_in and segments:
        sync_carryover_words = len(_strip_tts_tags_for_sync(carryover_in).split()) if sync_slides else 0
        segments[0]["text"] = carryover_in + "\n\n" + (segments[0]["text"] or "")
        segments[0]["word_count"] = len(segments[0]["text"].split())
        segments[0]["dirty"] = True
        if sync_slides and sync_carryover_words and slide_deck:
            adjusted_slides = []
            for slide in slide_deck.get("slides", []):
                clone = json.loads(json.dumps(slide, ensure_ascii=False))
                source_ref = clone.get("source_ref") or {}
                if source_ref.get("word_start") is not None:
                    source_ref["word_start"] = int(source_ref["word_start"]) + sync_carryover_words
                if source_ref.get("word_end") is not None:
                    source_ref["word_end"] = int(source_ref["word_end"]) + sync_carryover_words
                clone["source_ref"] = source_ref
                adjusted_slides.append(clone)
            slide_deck["slides"] = adjusted_slides
        logger.info(
            f"🔁 Folder {folder_id} : carryover entrant depuis folder "
            f"{job.get('carryover_in_source_folder_id')} ({len(carryover_in.split())} mots)"
        )

    total_words = sum(len(seg["text"].split()) for seg in segments)
    logger.info(f"📝 Script total : {total_words} mots, {len(segments)} segments")

    # ── 3. Découper en 7 blocs proportionnels, sur fins d'idées + redistribution ──
    # Passe 1 (forward cascade) + Passe 2 (backward redistribution) sont dans la fonction.
    blocs, _, carryover_out = _build_course_blocs_from_segments(
        segments,
        COURS_DURATIONS_MIN,
        PLAYLIST_SPEC,
        force_all=force_all,
        source_folder_id=folder_id,
        next_folder_id=next_folder_id,
        is_last_folder=is_last_folder,
        model=llm_model,
    )
    if carryover_out:
        logger.info(
            f"🔁 Folder {folder_id} : {len(carryover_out.split())} mots reportés "
            f"vers folder {next_folder_id}"
        )

    # ── 3.5. Closings contextuels — texte de fin de bloc adaptatif au gap résiduel.
    # Désactivé en mock/basic_tts et en sync slides: les bornes slides doivent
    # rester alignées sur le texte qui a servi au deck.
    if not mock and not basic_tts and not sync_slides:
        try:
            _apply_closing_transitions(blocs, _course_tts_speed(), model=llm_model)
        except Exception as e:
            logger.warning(f"⚠️ Closings contextuels — erreur globale, on continue sans : {e}")

    blocs_by_number = {b["bloc_number"]: b for b in blocs}
    playlist_items = _playlist_items_for_platform(platform_id)
    dirty_count = sum(1 for b in blocs if b["dirty"])
    clean_count = 7 - dirty_count
    logger.info(f"🎯 {dirty_count}/7 blocs à régénérer, {clean_count}/7 conservés")
    logger.info(
        "PIPELINE_AUDIO_PLAN formation_job_id=%s content_job_id=%s folder_id=%s playlist_items=%s total_words=%s blocs=%s dirty_blocs=%s clean_blocs=%s "
        "next_folder_id=%s is_last_folder=%s",
        formation_job_id,
        job_id,
        folder_id,
        len(playlist_items),
        total_words,
        len(blocs),
        dirty_count,
        clean_count,
        next_folder_id,
        is_last_folder,
    )

    _progress(0, len(playlist_items), f"{dirty_count}/7 blocs cours à régénérer ({clean_count} conservés)...")

    # ── 4. Générer la playlist : cours dirty + Q&A/pauses contextuels ──
    azure_prefix = f"platform-{platform_id}/folder-{folder_id}/playlist/"
    generated = []
    skipped = []
    slide_audio_timings = []
    slide_sync_files = []

    # Tampon intra-jour : chunks structurés non consommés par un bloc cours
    # précédent (runtime_fit a stoppé avant la fin) → préfixés au bloc suivant.
    # Uniquement actif en mode `basic_tts + sync_slides` (Edge TTS runtime fit).
    intra_day_carryover_chunks = []
    runtime_fit_enabled = bool(basic_tts and not mock and sync_slides)
    fast_tts_pipeline = bool(fast_tts_pipeline and runtime_fit_enabled)
    if fast_tts_pipeline:
        logger.info(
            "PIPELINE_AUDIO_FAST_TEST_ENABLED formation_job_id=%s content_job_id=%s folder_id=%s workers=%s cache=%s",
            formation_job_id,
            job_id,
            folder_id,
            _edge_tts_fast_workers(),
            _edge_tts_fast_cache_enabled(),
        )
    pending_clean_seg_keys = set()
    course_script_plan = []

    def _record_course_bloc(bloc, *, status, text=None, final_duration_sec=None,
                            skipped_reason=None, opening_rewritten=False,
                            opening_text="", opening_original_start="",
                            runtime_conclusions=None, runtime_ai_decisions=None):
        course_script_plan.append(
            _serialize_course_bloc(
                bloc,
                playlist_items,
                status=status,
                text=text,
                final_duration_sec=final_duration_sec,
                skipped_reason=skipped_reason,
                opening_rewritten=opening_rewritten,
                opening_text=opening_text,
                opening_original_start=opening_original_start,
                runtime_conclusions=runtime_conclusions,
                runtime_ai_decisions=runtime_ai_decisions,
            )
        )

    for item_idx, (filename, duration_sec, file_type, bloc_num) in enumerate(playlist_items):
        step = item_idx + 1
        bloc = blocs_by_number.get(bloc_num)
        item_started_at = time.time()
        logger.info(
            "PIPELINE_AUDIO_ITEM_START formation_job_id=%s content_job_id=%s folder_id=%s item=%s/%s filename=%s type=%s bloc=%s target_sec=%s",
            formation_job_id,
            job_id,
            folder_id,
            step,
            len(playlist_items),
            filename,
            file_type,
            bloc_num,
            duration_sec,
        )

        if file_type != "cours":
            if mock:
                logger.info(f"   🧪 [MOCK] {filename}: skip Q&A/pause contextuel")
                logger.info(
                    "PIPELINE_AUDIO_ITEM_SKIP formation_job_id=%s content_job_id=%s folder_id=%s filename=%s reason=mock_break duration_ms=%s",
                    formation_job_id,
                    job_id,
                    folder_id,
                    filename,
                    int((time.time() - item_started_at) * 1000),
                )
                skipped.append(filename)
                continue
            if not force_all and dirty_count == 0:
                logger.info(f"   ⏭️ {filename}: break conservé (aucun bloc cours dirty)")
                _progress(step, len(playlist_items), f"{filename} — conservé")
                logger.info(
                    "PIPELINE_AUDIO_ITEM_SKIP formation_job_id=%s content_job_id=%s folder_id=%s filename=%s reason=no_dirty_bloc duration_ms=%s",
                    formation_job_id,
                    job_id,
                    folder_id,
                    filename,
                    int((time.time() - item_started_at) * 1000),
                )
                skipped.append(filename)
                continue

            _progress(step, len(playlist_items), f"{filename} — génération {file_type} contextuel...")
            final_bytes, break_mode = _build_contextual_break_audio(
                filename=filename,
                duration_sec=duration_sec,
                file_type=file_type,
                bloc_num=bloc_num,
                item_idx=item_idx,
                playlist_items=playlist_items,
                blocs_by_number=blocs_by_number,
                mock=mock,
                basic_tts=basic_tts,
                llm_model=llm_model,
                on_progress=lambda msg: _progress(step, len(playlist_items), msg),
                use_runtime_consumed_text=runtime_fit_enabled,
            )
            _progress(step, len(playlist_items), f"{filename} — upload audio ({break_mode})...")
            upload_blob(CONTAINER_AUDIOS, f"{azure_prefix}{filename}", final_bytes)
            try:
                final_duration = _mp3_duration_seconds_no_ffprobe(final_bytes)
            except Exception:
                try:
                    final_duration = _measure_duration_ms(final_bytes) / 1000
                except Exception:
                    final_duration = (
                        duration_sec
                        if break_mode == "audioqapause_fallback"
                        else len(final_bytes) / 6000
                    )
            logger.info(f"   ✅ {filename} : {final_duration:.1f}s uploadé ({break_mode})")
            _progress(step, len(playlist_items), f"{filename} — terminé ({break_mode}, {final_duration:.1f}s)")
            logger.info(
                "PIPELINE_AUDIO_ITEM_DONE formation_job_id=%s content_job_id=%s folder_id=%s filename=%s type=%s mode=%s final_duration=%.1f duration_ms=%s",
                formation_job_id,
                job_id,
                folder_id,
                filename,
                file_type,
                break_mode,
                final_duration,
                int((time.time() - item_started_at) * 1000),
            )
            generated.append(filename)
            continue

        if not bloc:
            logger.info(f"   ⏭️ {filename}: bloc {bloc_num} introuvable, skip")
            _record_course_bloc(
                {
                    "bloc_number": bloc_num,
                    "filename": filename,
                    "target_sec": duration_sec,
                    "text": "",
                },
                status="skipped",
                skipped_reason="bloc_missing",
            )
            logger.info(
                "PIPELINE_AUDIO_ITEM_SKIP formation_job_id=%s content_job_id=%s folder_id=%s filename=%s reason=bloc_missing duration_ms=%s",
                formation_job_id,
                job_id,
                folder_id,
                filename,
                int((time.time() - item_started_at) * 1000),
            )
            skipped.append(filename)
            continue

        target_sec = bloc["target_sec"]

        # Si on a un carryover intra-jour à injecter, on doit régénérer ce bloc
        # même s'il était propre côté texte initial (sinon l'ancien MP3 ne
        # contiendra pas le carryover qu'on doit lire au début).
        if runtime_fit_enabled and intra_day_carryover_chunks and not bloc["dirty"]:
            bloc["dirty"] = True
            logger.info(
                f"   🔁 Bloc {bloc['bloc_number']} ({filename}) : forcé dirty=True "
                f"(carryover intra-jour à injecter, "
                f"{sum(len((c.get('text') or '').split()) for c in intra_day_carryover_chunks)} mots)"
            )

        if not bloc["dirty"]:
            if runtime_fit_enabled:
                bloc["runtime_consumed_text"] = bloc.get("text", "")
            logger.info(f"   ⏭️ Bloc {bloc['bloc_number']} ({filename}) : non modifié, conservé")
            _progress(step, len(playlist_items), f"Bloc {bloc['bloc_number']}/7 — conservé (non modifié)")
            _record_course_bloc(
                bloc,
                status="preserved",
                text=bloc.get("runtime_consumed_text") or bloc.get("text", ""),
                skipped_reason="clean_bloc",
            )
            logger.info(
                "PIPELINE_AUDIO_ITEM_SKIP formation_job_id=%s content_job_id=%s folder_id=%s filename=%s bloc=%s reason=clean_bloc duration_ms=%s",
                formation_job_id,
                job_id,
                folder_id,
                filename,
                bloc["bloc_number"],
                int((time.time() - item_started_at) * 1000),
            )
            skipped.append(filename)
            continue

        if not bloc["text"].strip():
            logger.info(f"   ⏭️ Bloc {bloc['bloc_number']} : texte vide, skip")
            _record_course_bloc(
                bloc,
                status="skipped",
                text="",
                skipped_reason="empty_text",
            )
            logger.info(
                "PIPELINE_AUDIO_ITEM_SKIP formation_job_id=%s content_job_id=%s folder_id=%s filename=%s bloc=%s reason=empty_text duration_ms=%s",
                formation_job_id,
                job_id,
                folder_id,
                filename,
                bloc["bloc_number"],
                int((time.time() - item_started_at) * 1000),
            )
            skipped.append(filename)
            continue

        audio_bloc = bloc
        opening_rewritten = False
        opening_text = ""
        opening_original_start = ""
        runtime_conclusions = []
        runtime_ai_decisions = []
        if not mock and _course_opening_transitions_enabled():
            from services.break_transition_service import nearest_course_bloc
            prev_course = nearest_course_bloc(playlist_items, item_idx, -1)
            prev_bloc_text = ""
            if prev_course and prev_course in blocs_by_number:
                prev_data = blocs_by_number.get(prev_course) or {}
                prev_bloc_text = (
                    prev_data.get("runtime_consumed_text")
                    or prev_data.get("text")
                    or ""
                )
            _progress(
                step,
                len(playlist_items),
                f"Bloc {bloc['bloc_number']}/7 — rédaction intro/amorce IA...",
            )
            rewritten_text, opening_meta = _rewrite_course_opening_for_audio(
                bloc,
                playlist_items,
                item_idx,
                model=llm_model,
                previous_excerpt=_tail_words(prev_bloc_text, 220),
            )
            if rewritten_text and rewritten_text != (bloc.get("text") or "").strip():
                rewritten_words = len(rewritten_text.split())
                word_budget = int(bloc.get("word_budget") or 0)
                if word_budget and rewritten_words > word_budget and not runtime_fit_enabled:
                    logger.warning(
                        "⚠️ Intro/amorce bloc %s ignorée : %s mots > budget %s",
                        bloc["bloc_number"],
                        rewritten_words,
                        word_budget,
                    )
                    _progress(
                        step,
                        len(playlist_items),
                        f"Bloc {bloc['bloc_number']}/7 — intro/amorce IA ignorée (budget TTS)",
                    )
                else:
                    audio_bloc = dict(bloc)
                    audio_bloc["text"] = rewritten_text
                    audio_bloc["word_count"] = rewritten_words
                    opening_rewritten = True
                    opening_text = (opening_meta or {}).get("opening_text") or ""
                    opening_original_start = (opening_meta or {}).get("original_start") or ""
                    _progress(
                        step,
                        len(playlist_items),
                        f"Bloc {bloc['bloc_number']}/7 — intro/amorce IA ajoutée avant TTS",
                    )
                    logger.info(
                        "PIPELINE_AUDIO_COURSE_OPENING_REWRITTEN formation_job_id=%s "
                        "content_job_id=%s folder_id=%s bloc=%s filename=%s words_before=%s words_after=%s",
                        formation_job_id,
                        job_id,
                        folder_id,
                        bloc["bloc_number"],
                        filename,
                        len((bloc.get("text") or "").split()),
                        rewritten_words,
                    )

        if sync_slides:
            mode_label = "MOCK" if mock else "BASIC edge-tts" if basic_tts else "Fish Audio"
            _progress(
                step,
                len(playlist_items),
                f"[SYNC SLIDES] Bloc {bloc['bloc_number']}/7 — {mode_label} ({len(audio_bloc['text'].split())} mots)...",
            )
            logger.info(f"   🖼️ Bloc {bloc['bloc_number']} ({filename}) — TTS synchronisé slides")
            # Runtime fit : préfixe le tampon intra-jour, capture le surplus
            # non consommé pour cascade au bloc suivant.
            prepended_for_call = intra_day_carryover_chunks if runtime_fit_enabled else None
            (
                final_bytes,
                voice_duration,
                fit_method,
                attempts,
                bloc_timings,
                runtime_unconsumed_chunks,
                runtime_consumed_chunks,
            ) = _synthesize_course_audio_synced_to_slides(
                audio_bloc,
                slide_deck.get("slides", []) if slide_deck else [],
                filename,
                mock=mock,
                basic_tts=basic_tts,
                progress_callback=lambda msg: _progress(step, len(playlist_items), msg),
                prepended_chunks=prepended_for_call,
                runtime_fit=runtime_fit_enabled,
                fast_tts_pipeline=fast_tts_pipeline,
                llm_model=llm_model,
            )
            runtime_conclusions = [
                {
                    "kind": a.get("kind"),
                    "duration": a.get("duration"),
                    "text": a.get("text") or "",
                }
                for a in attempts
                if a.get("kind") in {
                    "conclusion",
                    "conclusion_fallback",
                    "conclusion_ultra_fallback",
                } and (a.get("text") or "").strip()
            ]
            runtime_ai_decisions = [
                {
                    "kind": a.get("kind"),
                    "chunk": a.get("chunk"),
                    "remaining_sec": a.get("remaining_sec"),
                    "words": a.get("words"),
                    "reason": a.get("reason") or "",
                    "text": a.get("text") or "",
                    "original_start": a.get("original_start") or "",
                }
                for a in attempts
                if str(a.get("kind") or "").startswith("ai_")
            ]
            # Le tampon est consommé par cet appel ; le runtime peut en
            # produire un nouveau pour le prochain bloc cours.
            if runtime_fit_enabled:
                consumed_chunks = len(intra_day_carryover_chunks)
                consumed_words = sum(
                    len((c.get("text") or "").split()) for c in intra_day_carryover_chunks
                )
                bloc["runtime_consumed_text"] = "\n\n".join(
                    (c.get("text") or "").strip()
                    for c in (runtime_consumed_chunks or [])
                    if (c.get("text") or "").strip()
                )
                intra_day_carryover_chunks = list(runtime_unconsumed_chunks or [])
                unconsumed_words = sum(
                    len((c.get("text") or "").split()) for c in intra_day_carryover_chunks
                )
                logger.info(
                    "PIPELINE_AUDIO_BLOC_RUNTIME formation_job_id=%s content_job_id=%s "
                    "folder_id=%s bloc=%s target_sec=%s voice_duration=%.1f "
                    "chunks_generated=%s prepended_chunks=%s prepended_words=%s "
                    "unconsumed_chunks=%s unconsumed_words=%s fit_method=%s",
                    formation_job_id, job_id, folder_id, bloc["bloc_number"],
                    target_sec, voice_duration, len(attempts),
                    consumed_chunks, consumed_words,
                    len(intra_day_carryover_chunks), unconsumed_words,
                    fit_method,
                )
            slide_audio_timings.extend(bloc_timings)
            slide_sync_files.append(filename)
            logger.info(
                f"   TTS sync voix : {voice_duration:.1f}s "
                f"({fit_method}, chunks={len(attempts)}, cible : {target_sec}s)"
            )
        elif mock:
            _progress(step, len(playlist_items), f"[MOCK] Bloc {bloc['bloc_number']}/7 — silence 1s...")
            logger.info(f"   🧪 [MOCK] Bloc {bloc['bloc_number']} ({filename}) — silence 1s")
            from services.playlist_tts_service import _generate_silence_mp3
            final_bytes = _generate_silence_mp3(1)
        elif basic_tts:
            _progress(step, len(playlist_items), f"[BASIC] Bloc {bloc['bloc_number']}/7 — edge-tts ({len(audio_bloc['text'].split())} mots)...")
            logger.info(f"   🔊 [BASIC edge-tts] Bloc {bloc['bloc_number']} ({filename}) — génération via edge-tts…")
            from services.basic_tts_service import convert_to_speech_basic
            # Pas de padding : la durée gTTS ne matche pas les créneaux cours,
            # mais acceptable pour des tests. L'audio est plus court que la
            # playlist cible (ex: 33 min de gTTS vs 45 min de bloc cours) —
            # le reste sera du silence côté playlist horodatée.
            final_bytes = convert_to_speech_basic(
                audio_bloc["text"],
                progress_callback=lambda msg: _progress(
                    step,
                    len(playlist_items),
                    f"Bloc {bloc['bloc_number']}/7 — {msg}",
                ),
                parallel_workers=_edge_tts_fast_workers() if fast_tts_pipeline else 1,
                **_basic_tts_pipeline_retry_kwargs(),
            )
        else:
            _progress(step, len(playlist_items), f"Bloc {bloc['bloc_number']}/7 — génération TTS ({len(audio_bloc['text'].split())} mots)...")
            logger.info(f"   🎙️ Bloc {bloc['bloc_number']} ({filename}) — TTS en cours...")
            final_bytes, voice_duration, fit_method, attempts = _synthesize_course_audio_to_fit(
                audio_bloc,
                convert_to_speech,
                _measure_duration_ms,
                _pad_audio_to_duration,
            )
            if len(attempts) > 1:
                logger.info(f"   🔁 Bloc {bloc['bloc_number']} ajusté localement ({fit_method})")
            logger.info(f"   TTS voix : {voice_duration:.1f}s ({fit_method}, cible : {target_sec}s)")
        blob_path = f"{azure_prefix}{filename}"
        upload_blob(CONTAINER_AUDIOS, blob_path, final_bytes)

        if sync_slides and basic_tts:
            final_duration = voice_duration
        elif sync_slides:
            try:
                final_duration = _measure_duration_ms(final_bytes) / 1000
            except Exception:
                final_duration = target_sec
        elif mock:
            final_duration = 1.0
        elif basic_tts:
            # gTTS produit un MP3 valide ; mesure possible via pydub si ffmpeg
            # dispo, sinon on renvoie une estimation basée sur le volume bytes.
            try:
                final_duration = _measure_duration_ms(final_bytes) / 1000
            except Exception:
                # Estimation fallback : ~1 KB/s pour un MP3 mono 32 kbps
                final_duration = len(final_bytes) / 4000
        else:
            final_duration = _measure_duration_ms(final_bytes) / 1000
        logger.info(f"   ✅ {filename} : {final_duration:.1f}s uploadé")
        logger.info(
            "PIPELINE_AUDIO_ITEM_DONE formation_job_id=%s content_job_id=%s folder_id=%s filename=%s type=cours bloc=%s final_duration=%.1f "
            "words=%s duration_ms=%s",
            formation_job_id,
            job_id,
            folder_id,
            filename,
            bloc["bloc_number"],
            final_duration,
            len(bloc["text"].split()),
            int((time.time() - item_started_at) * 1000),
        )
        course_text_for_ui = audio_bloc.get("text", "")
        if runtime_fit_enabled:
            consumed_text_for_ui = (bloc.get("runtime_consumed_text") or "").strip()
            if consumed_text_for_ui:
                course_text_for_ui = consumed_text_for_ui
            elif runtime_conclusions:
                course_text_for_ui = ""
            conclusion_texts = [
                (item.get("text") or "").strip()
                for item in runtime_conclusions
                if (item.get("text") or "").strip()
            ]
            if conclusion_texts:
                course_text_for_ui = (
                    course_text_for_ui.rstrip()
                    + "\n\n"
                    + "\n\n".join(conclusion_texts)
                ).strip()
        _record_course_bloc(
            bloc,
            status="generated",
            text=course_text_for_ui,
            final_duration_sec=round(float(final_duration), 3),
            opening_rewritten=opening_rewritten,
            opening_text=opening_text,
            opening_original_start=opening_original_start,
            runtime_conclusions=runtime_conclusions,
            runtime_ai_decisions=runtime_ai_decisions,
        )
        generated.append(filename)

        # Marquer les segments contributeurs comme propres (dirty=0)
        seg_keys = [
            (segments[i]["sub_idx"], segments[i]["passe"])
            for i in bloc["contributing_seg_indices"]
            if segments[i]["dirty"]
        ]
        if seg_keys:
            if runtime_fit_enabled:
                pending_clean_seg_keys.update(seg_keys)
            else:
                _mark_content_segments_clean(job_id, seg_keys)

    if sync_slides and slide_deck:
        from services.script_slide_generation_service import update_script_slide_deck_audio_sync
        audio_mode = "mock" if mock else "gtts" if basic_tts else "fish_audio"
        update_script_slide_deck_audio_sync(
            slide_deck["deck_id"],
            {
                "enabled": True,
                "mode": audio_mode,
                "folder_id": folder_id,
                "content_job_id": job_id,
                "generated_files": slide_sync_files,
                "timings": slide_audio_timings,
            },
        )

    # ── 5. Cascade finale : runtime carryover après le dernier bloc cours ──
    # Si runtime_fit a stoppé un bloc avant la fin et qu'il reste du surplus
    # après le dernier cours de la journée, on doit le reporter au folder
    # suivant (en plus du carryover statique calculé en pré-allocation).
    runtime_carryover_text = ""
    if runtime_fit_enabled and intra_day_carryover_chunks:
        runtime_carryover_text = "\n\n".join(
            (c.get("text") or "").strip()
            for c in intra_day_carryover_chunks
            if (c.get("text") or "").strip()
        )

    carryover_out = _finalize_runtime_fit_carryover_and_clean(
        job_id=job_id,
        pending_clean_seg_keys=pending_clean_seg_keys,
        runtime_carryover_text=runtime_carryover_text,
        carryover_out=carryover_out,
        folder_id=folder_id,
        next_folder_id=next_folder_id,
        is_last_folder=bool(is_last_folder),
        formation_job_id=formation_job_id,
    )

    _progress(len(playlist_items), len(playlist_items), f"✅ Terminé — {len(generated)} générés, {len(skipped)} conservés")
    logger.info(
        "PIPELINE_AUDIO_DONE formation_job_id=%s content_job_id=%s folder_id=%s generated=%s skipped=%s slide_sync=%s slide_timings=%s fast_tts_pipeline=%s duration_ms=%s",
        formation_job_id,
        job_id,
        folder_id,
        len(generated),
        len(skipped),
        bool(sync_slides),
        len(slide_audio_timings),
        bool(fast_tts_pipeline),
        int((time.time() - started_at) * 1000),
    )

    mode = "mock" if mock else "edge_tts_sync" if (basic_tts and sync_slides) else "edge_tts" if basic_tts else "fish_audio"
    _save_course_script_plan(
        platform_id,
        folder_id,
        {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "platform_id": platform_id,
            "folder_id": folder_id,
            "content_job_id": job_id,
            "formation_job_id": formation_job_id,
            "mode": mode,
            "sync_slides": bool(sync_slides),
            "basic_tts": bool(basic_tts),
            "mock": bool(mock),
            "course_blocs": course_script_plan,
        },
    )

    return {
        "generated": len(generated),
        "skipped": len(skipped),
        "files": generated,
        "slide_sync_enabled": bool(sync_slides),
        "slide_deck_id": slide_deck["deck_id"] if slide_deck else None,
        "slide_timings": len(slide_audio_timings),
        "carryover_out_words": len(carryover_out.split()) if carryover_out else 0,
        "carryover_target_folder_id": next_folder_id if carryover_out else None,
        "runtime_carryover_words": len(runtime_carryover_text.split()) if runtime_carryover_text else 0,
        "fast_tts_pipeline": bool(fast_tts_pipeline),
        "fast_tts_workers": _edge_tts_fast_workers() if fast_tts_pipeline else 1,
    }


_COURSE_SCRIPT_PLAN_BLOB = "content-script-plan.json"


def _course_filename_for_bloc(playlist_spec, bloc_number: int) -> str:
    return next(
        (
            filename
            for filename, _duration, file_type, spec_bloc in playlist_spec
            if file_type == "cours" and spec_bloc == bloc_number
        ),
        f"cours_bloc{bloc_number}.mp3",
    )


def _course_duration_for_bloc(playlist_spec, bloc_number: int) -> int:
    from services.playlist_tts_service import COURS_DURATIONS_MIN

    return next(
        (
            int(duration)
            for _filename, duration, file_type, spec_bloc in playlist_spec
            if file_type == "cours" and spec_bloc == bloc_number
        ),
        int(COURS_DURATIONS_MIN.get(bloc_number, 0) * 60),
    )


def _serialize_course_bloc(
    bloc: dict,
    playlist_spec,
    *,
    status: str,
    text: str | None = None,
    final_duration_sec: float | None = None,
    skipped_reason: str | None = None,
    opening_rewritten: bool = False,
    opening_text: str = "",
    opening_original_start: str = "",
    runtime_conclusions: list | None = None,
    runtime_ai_decisions: list | None = None,
) -> dict:
    from services.playlist_tts_service import COURS_DURATIONS_MIN

    bloc_number = int(bloc.get("bloc_number") or 0)
    bloc_text = text if text is not None else (bloc.get("text") or "")
    runtime_conclusions = runtime_conclusions or []
    runtime_ai_decisions = runtime_ai_decisions or []
    return {
        "bloc_number": bloc_number,
        "filename": bloc.get("filename") or _course_filename_for_bloc(playlist_spec, bloc_number),
        "duration_sec": int(bloc.get("target_sec") or _course_duration_for_bloc(playlist_spec, bloc_number)),
        "duration_min": round(int(bloc.get("target_sec") or 0) / 60, 1) if bloc.get("target_sec") else COURS_DURATIONS_MIN.get(bloc_number),
        "status": status,
        "text": bloc_text,
        "word_count": len((bloc_text or "").split()),
        "planned_word_count": int(bloc.get("word_count") or len((bloc.get("text") or "").split())),
        "word_budget": int(bloc.get("word_budget") or 0),
        "dirty": bool(bloc.get("dirty")),
        "closing_added": bool(bloc.get("closing_added") or runtime_conclusions),
        "closing_text": bloc.get("closing_text") or "",
        "closing_words": int(bloc.get("closing_words") or 0),
        "runtime_conclusions": runtime_conclusions,
        "runtime_ai_decisions": runtime_ai_decisions,
        "opening_rewritten": bool(opening_rewritten),
        "opening_text": opening_text or "",
        "opening_original_start": opening_original_start or "",
        "final_duration_sec": final_duration_sec,
        "skipped_reason": skipped_reason or "",
        "overflow_unresolved": bool(bloc.get("overflow_unresolved")),
        "overflow_words": int(bloc.get("overflow_words") or 0),
    }


def _load_segments_for_course_plan(job: dict, *, sync_slides: bool = False) -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sub_part_index, passe, text_content, word_count, dirty
        FROM content_generation_segments
        WHERE job_id = ? AND status = 'completed'
        ORDER BY sub_part_index ASC, passe ASC
    """, (job["id"],))
    rows = cursor.fetchall()
    conn.close()

    segments = []
    for r in rows:
        text = r[2] or ""
        if sync_slides:
            text = _strip_tts_tags_for_sync(text)
        segments.append({
            "sub_idx": r[0],
            "passe": r[1],
            "text": text,
            "word_count": len(text.split()) if sync_slides else r[3],
            "dirty": bool(r[4]),
        })

    carryover_in = (job.get("carryover_in_text") or "").strip()
    if carryover_in and segments:
        segments[0]["text"] = carryover_in + "\n\n" + (segments[0]["text"] or "")
        segments[0]["word_count"] = len(segments[0]["text"].split())
        segments[0]["dirty"] = True

    return segments


def _build_course_blocs_preview(folder_id: int, job: dict) -> list:
    from services.playlist_tts_service import COURS_DURATIONS_MIN, PLAYLIST_SPEC

    segments = _load_segments_for_course_plan(job, sync_slides=False)
    if not segments:
        return []

    next_folder_id = _find_next_folder_id(job["platform_id"], folder_id)
    blocs, _total_words, _carryover_out = _build_course_blocs_from_segments(
        segments,
        COURS_DURATIONS_MIN,
        PLAYLIST_SPEC,
        force_all=False,
        source_folder_id=None,
        next_folder_id=next_folder_id,
        is_last_folder=next_folder_id is None,
        preview=True,
    )
    return [
        _serialize_course_bloc(bloc, PLAYLIST_SPEC, status="preview")
        for bloc in blocs
    ]


def _load_saved_course_script_plan(platform_id: int, folder_id: int) -> dict | None:
    try:
        from services.azure_blob_service import download_blob, CONTAINER_AUDIOS

        blob_path = f"platform-{platform_id}/folder-{folder_id}/playlist/{_COURSE_SCRIPT_PLAN_BLOB}"
        raw = download_blob(CONTAINER_AUDIOS, blob_path)
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        if "BlobNotFound" not in str(e) and "The specified blob does not exist" not in str(e):
            logger.warning(f"⚠️ Lecture plan script cours impossible folder={folder_id}: {e}")
        return None


def _save_course_script_plan(platform_id: int, folder_id: int, payload: dict) -> None:
    try:
        from services.azure_blob_service import upload_blob, CONTAINER_AUDIOS

        blob_path = f"platform-{platform_id}/folder-{folder_id}/playlist/{_COURSE_SCRIPT_PLAN_BLOB}"
        upload_blob(
            CONTAINER_AUDIOS,
            blob_path,
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        )
    except Exception as e:
        logger.warning(f"⚠️ Sauvegarde plan script cours impossible folder={folder_id}: {e}")


def _build_breaks_for_ui(platform_id: int) -> list:
    """Retourne les textes intro/outro des Q&A et pauses (variants génériques).

    Reflète la playlist effective de la plateforme (été/hiver). Les textes
    rendus correspondent aux variants statiques utilisés en Edge TTS et en
    fallback Fish Audio ; les versions LLM contextuelles ne sont pas
    persistées et ne peuvent donc pas être affichées ici.
    """
    from services.playlist_tts_service import (
        _playlist_items_for_platform,
        _get_pause_midi_text,
        _get_pause_text,
        _get_qa_text,
    )

    items = _playlist_items_for_platform(platform_id)
    breaks = []
    for filename, duration, file_type, bloc_num in items:
        if file_type == "cours":
            continue
        if file_type == "qa":
            intro, outro = _get_qa_text(bloc_num)
        elif file_type == "pause_midi" or filename.startswith("pause_midi_"):
            intro, outro = _get_pause_midi_text()
        elif file_type == "pause":
            intro, outro = _get_pause_text(bloc_num)
        else:
            continue
        breaks.append({
            "filename": filename,
            "duration_sec": int(duration or 0),
            "type": file_type,
            "bloc_number": int(bloc_num or 0),
            "intro": intro,
            "outro": outro,
        })
    return breaks


def get_course_script_plan_for_ui(folder_id: int, job: dict | None = None) -> dict:
    """Retourne les 7 textes cours affichables dans la modale Script TTS.

    Priorité à la dernière génération audio persistée, car elle contient les
    closings et conclusions réellement envoyés au TTS. Si elle n'existe pas ou
    si le texte a été modifié depuis, on retombe sur une prévisualisation sans
    appel LLM et sans effet de bord.
    """
    job = job or get_job_from_db(folder_id)
    if not job:
        return {
            "course_blocs": [],
            "course_blocs_source": "none",
            "course_blocs_note": "Aucun job de contenu pour ce dossier.",
            "breaks": [],
        }

    breaks = _build_breaks_for_ui(job["platform_id"])

    dirty_info = get_script_dirty_blocs(folder_id)
    dirty_blocs = int(dirty_info.get("dirty_blocs", 0) or 0)
    total_blocs = int(dirty_info.get("total_blocs", 7) or 7)
    saved = _load_saved_course_script_plan(job["platform_id"], folder_id)
    if saved and saved.get("course_blocs"):
        if dirty_blocs:
            note = (
                f"Texte réellement lu lors de la dernière génération TTS. "
                f"{dirty_blocs}/{total_blocs} bloc(s) à régénérer "
                f"(le script a été modifié depuis)."
            )
        else:
            note = "Texte réellement lu lors de la dernière génération TTS."
        return {
            "course_blocs": saved.get("course_blocs") or [],
            "course_blocs_source": "last_audio_generation",
            "course_blocs_generated_at": saved.get("generated_at"),
            "course_blocs_mode": saved.get("mode"),
            "course_blocs_note": note,
            "course_blocs_stale": bool(dirty_blocs),
            "dirty_blocs": dirty_blocs,
            "total_blocs": total_blocs,
            "breaks": breaks,
        }

    preview = _build_course_blocs_preview(folder_id, job)
    return {
        "course_blocs": preview,
        "course_blocs_source": "preview",
        "course_blocs_generated_at": None,
        "course_blocs_mode": None,
        "course_blocs_note": "Prévisualisation du découpage actuel, avant génération audio.",
        "course_blocs_stale": False,
        "dirty_blocs": dirty_blocs,
        "total_blocs": total_blocs,
        "breaks": breaks,
    }


def get_script_dirty_blocs(folder_id):
    """
    Retourne le nombre de blocs cours qui seraient régénérés si on lance la génération audio.
    Utilisé par le frontend pour afficher un indicateur.
    """
    from services.playlist_tts_service import COURS_DURATIONS_MIN

    job = get_job_from_db(folder_id)
    if not job:
        return {"dirty_blocs": 0, "total_blocs": 7, "has_script": False}

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sub_part_index, passe, word_count, dirty
        FROM content_generation_segments
        WHERE job_id = ? AND status = 'completed'
        ORDER BY sub_part_index ASC, passe ASC
    """, (job["id"],))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return {"dirty_blocs": 0, "total_blocs": 7, "has_script": True}

    segments = [{"sub_idx": r[0], "passe": r[1], "wc": r[2], "dirty": bool(r[3])} for r in rows]
    total_words = sum(s["wc"] for s in segments)

    word_to_seg_idx = []
    for si, seg in enumerate(segments):
        word_to_seg_idx.extend([si] * seg["wc"])

    total_duration = sum(COURS_DURATIONS_MIN.values())
    dirty_blocs = 0
    cursor_w = 0

    for bloc_num in range(1, 8):
        proportion = COURS_DURATIONS_MIN[bloc_num] / total_duration
        end_w = min(cursor_w + round(total_words * proportion), total_words)
        contributing = set(word_to_seg_idx[cursor_w:end_w])
        if any(segments[i]["dirty"] for i in contributing):
            dirty_blocs += 1
        cursor_w = end_w

    return {"dirty_blocs": dirty_blocs, "total_blocs": 7, "has_script": True}


def _generate_segment_mini(sub_part_name, program_title, program_text):
    """Génère un court segment via Claude (300 tokens max) pour tester l'intégration."""
    prompts = _get_passe_prompts()
    prompt = prompts[0]  # Passe 1
    prompt = prompt.replace("{NOM_DU_TITRE_PROFESSIONNEL}", program_title)
    prompt = prompt.replace("{NOM_DE_LA_SOUS_PARTIE}", sub_part_name)
    prompt = prompt.replace("{COLLER_LE_PROGRAMME_ICI}", program_text[:3000])
    prompt += "\n\nIMPORTANT : génère SEULEMENT une introduction de 150 mots maximum, c'est un test."
    return _anthropic_post(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300,
    ).strip()


# ─── Révision conformité (Phase 1 — API Claude) ──────────────────────────────
# Spec : memoire/03-decisions/pipeline-dual-api-et-claude-code.md
# Format patches : {original, replacement, rule_violated, reason} avec match
# textuel unique. Max 5 patches par appel. Idempotent via reviewed=1.

import json as _json
import re as _re

_REVIEW_MAX_PATCHES = 5
_REVIEW_MAX_TOKENS = 2000


def _env_int(name: str, default: int, min_value: int = 1) -> int:
    try:
        return max(min_value, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        logger.warning(f"⚠️ {name} invalide, fallback {default}")
        return default


_REVIEW_CHUNK_WORDS = _env_int("FORMATION_REVIEW_CHUNK_WORDS", 1500, min_value=300)
_REVIEW_CHUNK_CONCURRENCY = _env_int("FORMATION_REVIEW_CHUNK_CONCURRENCY", 2, min_value=1)
_REVIEW_MAX_ATTEMPTS = 3

_REVIEW_RULE_GROUPS = [
    {
        "id": "ethique_culturelle",
        "label": "Éthique culturelle",
        "rules": [1, 2, 3, 9, 14],
        "description": "Spirituel/religieux, alcool/musique/banques, fêtes, humour, respect des tiers",
    },
    {
        "id": "ethique_commerciale",
        "label": "Éthique commerciale",
        "rules": [4, 5, 6, 7, 8],
        "description": "Manipulation, closing manipulatoire, flirt/séduction, chance/destin, célébrités",
    },
    {
        "id": "legal_integrite",
        "label": "Légal et intégrité",
        "rules": [10, 11, 12, 13, 15, 16],
        "description": "Cohérence interne, discrimination, RGPD, promesses irréalistes, détresse, conseils médicaux/juridiques",
    },
    {
        "id": "anti_hallucination",
        "label": "Anti-hallucination",
        "rules": [17, 18, 19, 20],
        "description": "Exemples fictifs, chiffres non sourcés, expressions de prudence, posture pédagogique",
    },
    {
        "id": "style_oral_tts",
        "label": "Style oral TTS",
        "rules": [21, 22, 23, 24, 25, 26, 27],
        "description": "Fusion syntaxique, guillemets, posture dialogale, punchlines, cours à distance, énumérations, registre oral",
    },
]

_RULES_CACHE = {"mtime": 0, "text": ""}


def _load_review_rules() -> str:
    """Extrait le bloc 'RÈGLES ABSOLUES #1 à #27' de la passe 1 du prompt
    (les règles sont identiques dans les 3 passes, une seule extraction
    suffit). Mise en cache par mtime du fichier."""
    path = os.path.join(
        os.path.dirname(__file__), "..", "prompts", "prompt-generation-tts-scratch.md"
    )
    mtime = os.path.getmtime(path)
    if _RULES_CACHE["mtime"] == mtime and _RULES_CACHE["text"]:
        return _RULES_CACHE["text"]
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    m = _re.search(
        r"CONTENU — RÈGLES ABSOLUES\s*\n═+\n(.*?)décroche, les apprentissages ne passent pas\.",
        content,
        _re.DOTALL,
    )
    rules_text = m.group(0) if m else content[:20000]
    _RULES_CACHE["mtime"] = mtime
    _RULES_CACHE["text"] = rules_text
    return rules_text


def _extract_rules_for_group(full_rules_text: str, rule_numbers: list) -> str:
    """Extrait uniquement les règles demandées du bloc RÈGLES complet (split sur RÈGLE #N)."""
    parts = _re.split(r"(?=RÈGLE #\d+)", full_rules_text)
    extracted = []
    for part in parts:
        m = _re.match(r"RÈGLE #(\d+)", part)
        if m and int(m.group(1)) in rule_numbers:
            extracted.append(part.strip())
    return "\n\n".join(extracted)


def _build_review_prompt_focused(
    segment_text: str, rules_text: str, group_label: str, group_desc: str, rule_numbers: list,
    chunk_index: int = 1, chunk_total: int = 1,
) -> str:
    rules_list = ", ".join(f"#{n}" for n in rule_numbers)
    return f"""Tu es un reviewer éditorial SPÉCIALISÉ. Tu reçois un extrait de cours oral et un sous-ensemble de règles à vérifier.

🎯 TON SCOPE EXCLUSIF : {group_label} — {group_desc}
Tu vérifies UNIQUEMENT les règles {rules_list}. Ignore toutes les autres règles.

Tu audites le CHUNK {chunk_index}/{chunk_total} d'un segment plus long. Ne juge que le texte fourni ci-dessous.

TU NE RÉÉCRIS PAS LE TEXTE. Tu renvoies un JSON avec uniquement les passages qui violent une règle de ton scope.
Si le texte est conforme pour ces règles, renvoie {{"patches": []}}.

Format de sortie strict (JSON valide, rien d'autre avant ou après) :

{{
  "patches": [
    {{
      "original": "phrase EXACTE à remplacer (copie verbatim, 3 à 40 mots)",
      "replacement": "phrase corrigée, même esprit, même registre oral",
      "rule_violated": "#1",
      "reason": "explication brève (1 phrase)"
    }}
  ]
}}

Contraintes impératives :
- Maximum {_REVIEW_MAX_PATCHES} patches. Si tu vois plus de violations, garde les {_REVIEW_MAX_PATCHES} pires.
- `original` doit être trouvable TEL QUEL dans le texte (copie mot pour mot, ponctuation comprise).
- `replacement` corrige la violation sans reformuler le sens, sans ajouter de contenu.
- Ne corrige QUE les vraies violations de {rules_list}. Pas d'autres règles, pas de préférence stylistique.
- `rule_violated` = numéro parmi {rules_list} (ex: "#1", "#9").

─── RÈGLES DE TON SCOPE ({group_label}) ───
{rules_text}

─── TEXTE À AUDITER ───
{segment_text}

─── TON JSON ───
"""


def _cooperative_sleep(seconds: float) -> None:
    """Sleep compatible eventlet si disponible, sinon sleep standard."""
    try:
        import eventlet
        eventlet.sleep(seconds)
    except Exception:
        time.sleep(seconds)


def _chunk_text(text: str, max_words: int = _REVIEW_CHUNK_WORDS) -> list:
    """Découpe un segment en chunks paragraph-aware d'environ max_words mots."""
    words = text.split()
    if len(words) <= max_words:
        return [{"index": 1, "total": 1, "text": text, "words": len(words)}]

    parts = _re.split(r"(\n\s*\n+)", text)
    units = []
    for i in range(0, len(parts), 2):
        unit = parts[i]
        if i + 1 < len(parts):
            unit += parts[i + 1]
        if unit.strip():
            units.append(unit)

    chunks = []
    buf = []
    buf_words = 0

    def _flush():
        nonlocal buf, buf_words
        if buf:
            chunk_text = "".join(buf).strip()
            chunks.append({"text": chunk_text, "words": len(chunk_text.split())})
            buf = []
            buf_words = 0

    for unit in units:
        unit_words = len(unit.split())
        if buf and buf_words + unit_words > max_words:
            _flush()
        buf.append(unit)
        buf_words += unit_words
        if buf_words >= max_words:
            _flush()
    _flush()

    total = len(chunks) or 1
    if not chunks:
        chunks = [{"text": text, "words": len(words)}]
        total = 1
    for i, chunk in enumerate(chunks, start=1):
        chunk["index"] = i
        chunk["total"] = total
    return chunks


def _review_chunk_with_retries(prompt: str, group_label: str, chunk_index: int, model=None) -> dict:
    """Appelle le reviewer API avec retries sur erreurs transitoires et parse JSON."""
    last_error = None
    for attempt in range(_REVIEW_MAX_ATTEMPTS):
        try:
            raw = _anthropic_post(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=_REVIEW_MAX_TOKENS,
                model=model,
            )
            patches, parse_error = _parse_patches_response(raw)
            if not parse_error:
                return {"ok": True, "patches": patches}
            last_error = f"[{group_label} chunk {chunk_index}] parse: {parse_error}"
            wait = 15 * (attempt + 1)
        except AnthropicRateLimitError as e:
            last_error = f"[{group_label} chunk {chunk_index}] rate_limit: {str(e)[:200]}"
            wait = max(float(getattr(e, "wait_seconds", 0) or 0), 15 * (attempt + 1))
        except AnthropicAPIError as e:
            last_error = f"[{group_label} chunk {chunk_index}] API {e.status_code}: {str(e)[:200]}"
            if getattr(e, "is_deterministic", False):
                return {"ok": False, "error": last_error}
            wait = 15 * (attempt + 1)
        except Exception as e:
            last_error = f"[{group_label} chunk {chunk_index}] API error: {str(e)[:200]}"
            wait = 15 * (attempt + 1)

        if attempt < _REVIEW_MAX_ATTEMPTS - 1:
            logger.warning(
                f"    ⚠️ Salve '{group_label}' chunk {chunk_index} tentative "
                f"{attempt + 1}/{_REVIEW_MAX_ATTEMPTS} : {last_error} — retry dans {wait:.0f}s"
            )
            _cooperative_sleep(wait)

    return {"ok": False, "error": last_error or f"[{group_label} chunk {chunk_index}] échec inconnu"}


def _review_group_chunks(current_text: str, rules_text: str, group: dict, model=None) -> tuple:
    """Audite tous les chunks d'un segment pour un groupe de règles."""
    group_label = group["label"]
    group_rules = group["rules"]
    group_desc = group["description"]
    group_rules_text = _extract_rules_for_group(rules_text, group_rules)
    chunks = _chunk_text(current_text)

    logger.info(
        f"    🔬 Salve '{group_label}' : {len(chunks)} chunk(s), "
        f"concurrency={_REVIEW_CHUNK_CONCURRENCY}"
    )

    def _run_chunk(chunk):
        prompt = _build_review_prompt_focused(
            chunk["text"], group_rules_text, group_label, group_desc, group_rules,
            chunk_index=chunk["index"], chunk_total=chunk["total"],
        )
        result = _review_chunk_with_retries(prompt, group_label, chunk["index"], model=model)
        result["chunk"] = chunk
        return result

    if len(chunks) == 1 or _REVIEW_CHUNK_CONCURRENCY <= 1:
        results = [_run_chunk(chunk) for chunk in chunks]
    else:
        import eventlet
        pool = eventlet.GreenPool(size=_REVIEW_CHUNK_CONCURRENCY)
        pile = eventlet.GreenPile(pool)
        for chunk in chunks:
            pile.spawn(_run_chunk, chunk)
        results = list(pile)
        results.sort(key=lambda r: r["chunk"]["index"])

    updated_text = current_text
    group_applied = []
    group_rejected = []

    for result in results:
        chunk = result["chunk"]
        if not result.get("ok"):
            return updated_text, group_applied, group_rejected, result.get("error")

        patches = [
            {**p, "review_group": group["id"], "chunk_index": chunk["index"]}
            for p in (result.get("patches") or [])
        ]
        new_text, applied, rejected = _apply_patches(updated_text, patches)

        updated_text = new_text
        group_applied.extend(applied)
        group_rejected.extend(rejected)

    return updated_text, group_applied, group_rejected, None


def _build_review_prompt(segment_text: str, rules_text: str) -> str:
    return f"""Tu es un reviewer éditorial. Tu reçois un extrait de cours oral \
généré par un autre Claude, et les règles #1 à #27 que ce cours doit \
respecter. Ton unique rôle : identifier les passages qui VIOLENT une règle, \
et proposer une correction minimale.

TU NE RÉÉCRIS PAS LE TEXTE. Tu renvoies un JSON contenant uniquement les \
passages non conformes. Si le texte est conforme, renvoie {{"patches": []}}.

Format de sortie strict (JSON valide, rien d'autre avant ou après) :

{{
  "patches": [
    {{
      "original": "phrase EXACTE à remplacer (copie verbatim, 3 à 40 mots)",
      "replacement": "phrase corrigée, même esprit, même registre oral",
      "rule_violated": "#27",
      "reason": "explication brève (1 phrase)"
    }}
  ]
}}

Contraintes impératives :
- Maximum {_REVIEW_MAX_PATCHES} patches. Si tu vois plus de violations, garde les {_REVIEW_MAX_PATCHES} pires.
- `original` doit être trouvable TEL QUEL dans le texte (copie mot pour mot, \
ponctuation comprise). Évite les phrases trop courantes qui apparaîtraient \
plusieurs fois.
- `replacement` corrige la violation sans reformuler le sens, sans ajouter \
de contenu, sans raccourcir ni allonger au-delà du strict nécessaire.
- Ne corrige QUE les vraies violations des règles ci-dessous. Pas de \
préférence stylistique personnelle.
- `rule_violated` = numéro de règle (ex: "#1", "#7", "#21", "#27").

─── RÈGLES À FAIRE RESPECTER ───
{rules_text}

─── TEXTE À AUDITER ───
{segment_text}

─── TON JSON ───
"""


def _parse_patches_response(raw: str):
    """Parse la réponse reviewer. Tolère du texte autour du JSON.

    Retour : (patches, parse_error)
    - Succès : (list_de_patches, None) — list peut être vide (vraie conformité)
    - Échec  : ([], 'raison') — JSON illisible ou structure invalide
    """
    raw = (raw or "").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return [], "aucun objet JSON détecté dans la réponse reviewer"
    try:
        obj = _json.loads(raw[start : end + 1])
    except Exception as e:
        return [], f"JSON invalide : {str(e)[:200]}"
    if not isinstance(obj, dict) or "patches" not in obj:
        return [], "la réponse n'a pas de clé 'patches'"
    patches = obj.get("patches", [])
    if not isinstance(patches, list):
        return [], "'patches' n'est pas une liste"
    clean = []
    for p in patches[:_REVIEW_MAX_PATCHES]:
        if not isinstance(p, dict):
            continue
        if "original" not in p or "replacement" not in p:
            continue
        if not isinstance(p["original"], str) or not isinstance(p["replacement"], str):
            continue
        clean.append(
            {
                "original": p["original"],
                "replacement": p["replacement"],
                "rule_violated": str(p.get("rule_violated", ""))[:20],
                "reason": str(p.get("reason", ""))[:300],
            }
        )
    return clean, None


def _apply_patches(text: str, patches: list) -> tuple:
    """Applique les patches par match textuel UNIQUE. Renvoie (nouveau_texte,
    applied, rejected) où applied/rejected sont des listes enrichies du
    résultat (status + reason pour les rejected)."""
    applied = []
    rejected = []
    for p in patches:
        original = p["original"]
        replacement = p["replacement"]
        count = text.count(original)
        if count == 1:
            text = text.replace(original, replacement, 1)
            applied.append(p)
        elif count == 0:
            rejected.append({**p, "reject_reason": "original not found"})
        else:
            rejected.append({**p, "reject_reason": f"ambiguous ({count} occurrences)"})
    return text, applied, rejected


def _snapshot_pre_review_for_content_job(job_id: int) -> int:
    """Persist the exact text state before API review mutates segments."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "ALTER TABLE content_generation_segments ADD COLUMN text_content_pre_review TEXT"
        )
        conn.commit()
    except Exception:
        pass
    cursor.execute(
        """
        UPDATE content_generation_segments
        SET text_content_pre_review = text_content
        WHERE job_id = ?
          AND status = 'completed'
          AND text_content_pre_review IS NULL
        """,
        (job_id,),
    )
    snapshotted = cursor.rowcount or 0
    conn.commit()
    conn.close()
    if snapshotted:
        logger.info(
            "PIPELINE_REVIEW_SNAPSHOT content_job_id=%s segments=%s",
            job_id,
            snapshotted,
        )
    return int(snapshotted)


def run_content_review(folder_id, on_progress=None, model=None):
    """
    Révise la conformité des segments completed non encore reviewed pour un
    dossier cours. Boucle : pour chaque segment, appel reviewer Claude,
    application des patches uniques, log. Marque reviewed=1 à la fin quel
    que soit le résultat (idempotent).

    Règles :
    - Skip les segments déjà reviewed=1 (idempotence).
    - Si patches appliqués : segment.text_content mis à jour, dirty=1 pour
      que le TTS régénère, reviewed=1.
    - Si aucun patch ou tout rejeté : juste reviewed=1, dirty inchangé.

    Renvoie un dict résumé : {segments_reviewed, patches_applied, patches_rejected, details}.
    """
    def _progress(step, total, msg):
        if on_progress:
            on_progress(step, total, msg)

    job = get_job_from_db(folder_id)
    if not job:
        raise ValueError(f"Aucun content_generation_job pour folder {folder_id}")

    job_id = job["id"]
    formation_job_id = job.get("formation_job_id")
    started_at = time.time()
    logger.info(
        "PIPELINE_REVIEW_START formation_job_id=%s content_job_id=%s folder_id=%s model=%s",
        formation_job_id,
        job_id,
        folder_id,
        model,
    )
    _snapshot_pre_review_for_content_job(job_id)
    conn = get_db_connection()
    cursor = conn.cursor()
    # Sont éligibles à la révision : les segments completed dont reviewed=0.
    # Ça inclut naturellement les segments qui avaient échoué précédemment
    # (review_error != NULL ET reviewed=0) — relancer la route = retry.
    cursor.execute(
        """
        SELECT id, sub_part_index, sub_part_name, passe, text_content
        FROM content_generation_segments
        WHERE job_id = ? AND status = 'completed' AND COALESCE(reviewed, 0) = 0
        ORDER BY sub_part_index ASC, passe ASC
        """,
        (job_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    total = len(rows)
    if total == 0:
        _progress(0, 0, "Tous les segments déjà révisés — rien à faire.")
        logger.info(
            "PIPELINE_REVIEW_DONE formation_job_id=%s content_job_id=%s folder_id=%s reviewed=0 failed=0 applied=0 rejected=0 duration_ms=%s reason=already_reviewed",
            formation_job_id,
            job_id,
            folder_id,
            int((time.time() - started_at) * 1000),
        )
        return {
            "segments_reviewed": 0,
            "segments_failed": 0,
            "patches_applied": 0,
            "patches_rejected": 0,
            "details": [],
        }

    logger.info(
        "PIPELINE_REVIEW_PLAN formation_job_id=%s content_job_id=%s folder_id=%s segments_to_review=%s groups=%s",
        formation_job_id,
        job_id,
        folder_id,
        total,
        len(_REVIEW_RULE_GROUPS),
    )
    rules_text = _load_review_rules()

    total_applied = 0
    total_rejected = 0
    total_failed = 0
    details = []

    for step, row in enumerate(rows, start=1):
        segment_started_at = time.time()
        seg_id, sub_idx, sub_part_name, passe, text_content = row
        label = f"sous-partie {sub_idx + 1} / passe {passe}"
        _progress(step, total, f"Audit {label} (5 salves)…")
        logger.info(
            "PIPELINE_REVIEW_SEGMENT_START formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s step=%s/%s sub_part=%s passe=%s words=%s",
            formation_job_id,
            job_id,
            folder_id,
            seg_id,
            step,
            total,
            sub_idx + 1,
            passe,
            len((text_content or "").split()),
        )

        current_text = text_content
        all_applied = []
        all_rejected = []
        segment_error = None  # None = toutes les salves ont réussi jusqu'ici

        for group in _REVIEW_RULE_GROUPS:
            group_started_at = time.time()
            group_label = group["label"]
            logger.info(
                "PIPELINE_REVIEW_GROUP_START formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s group=%s rules=%s",
                formation_job_id,
                job_id,
                folder_id,
                seg_id,
                group_label,
                ",".join(str(rule) for rule in (group.get("rules") or [])),
            )
            new_text, applied, rejected, group_error = _review_group_chunks(
                current_text, rules_text, group, model=model
            )
            if group_error:
                segment_error = group_error
                logger.warning(
                    "PIPELINE_REVIEW_GROUP_ERROR formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s group=%s duration_ms=%s error=%s",
                    formation_job_id,
                    job_id,
                    folder_id,
                    seg_id,
                    group_label,
                    int((time.time() - group_started_at) * 1000),
                    group_error,
                )
                break

            current_text = new_text
            all_applied.extend(applied)
            all_rejected.extend(rejected)

            if applied:
                logger.info(
                    "PIPELINE_REVIEW_GROUP_DONE formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s group=%s applied=%s rejected=%s duration_ms=%s",
                    formation_job_id,
                    job_id,
                    folder_id,
                    seg_id,
                    group_label,
                    len(applied),
                    len(rejected),
                    int((time.time() - group_started_at) * 1000),
                )
            elif rejected:
                logger.info(
                    "PIPELINE_REVIEW_GROUP_DONE formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s group=%s applied=0 rejected=%s duration_ms=%s",
                    formation_job_id,
                    job_id,
                    folder_id,
                    seg_id,
                    group_label,
                    len(rejected),
                    int((time.time() - group_started_at) * 1000),
                )
            else:
                logger.info(
                    "PIPELINE_REVIEW_GROUP_DONE formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s group=%s applied=0 rejected=0 duration_ms=%s",
                    formation_job_id,
                    job_id,
                    folder_id,
                    seg_id,
                    group_label,
                    int((time.time() - group_started_at) * 1000),
                )

        # Écriture finale en DB (une seule transaction par segment)
        conn = get_db_connection()
        cursor = conn.cursor()

        if segment_error:
            # Une salve a échoué : review_error, PAS reviewed=1
            cursor.execute(
                "UPDATE content_generation_segments SET review_error = ? WHERE id = ?",
                (segment_error[:500], seg_id),
            )
            conn.commit()
            conn.close()
            total_failed += 1
            details.append({"segment_id": seg_id, "sub_idx": sub_idx, "passe": passe, "error": segment_error})
            logger.warning(
                "PIPELINE_REVIEW_SEGMENT_FAILED formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s applied=%s rejected=%s duration_ms=%s error=%s",
                formation_job_id,
                job_id,
                folder_id,
                seg_id,
                len(all_applied),
                len(all_rejected),
                int((time.time() - segment_started_at) * 1000),
                segment_error,
            )
            continue

        # Toutes les 5 salves ont réussi
        if all_applied:
            new_word_count = len(current_text.split())
            cursor.execute(
                """
                UPDATE content_generation_segments
                SET text_content = ?, word_count = ?, dirty = 1,
                    reviewed = 1, review_error = NULL
                WHERE id = ?
                """,
                (current_text, new_word_count, seg_id),
            )
            logger.info(
                "PIPELINE_REVIEW_SEGMENT_PATCHED formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s applied=%s rejected=%s new_words=%s",
                formation_job_id,
                job_id,
                folder_id,
                seg_id,
                len(all_applied),
                len(all_rejected),
                new_word_count,
            )
        else:
            cursor.execute(
                "UPDATE content_generation_segments SET reviewed = 1, review_error = NULL WHERE id = ?",
                (seg_id,),
            )
            logger.info(
                "PIPELINE_REVIEW_SEGMENT_CLEAN formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s rejected=%s",
                formation_job_id,
                job_id,
                folder_id,
                seg_id,
                len(all_rejected),
            )
        conn.commit()
        conn.close()

        total_applied += len(all_applied)
        total_rejected += len(all_rejected)
        logger.info(
            "PIPELINE_REVIEW_SEGMENT_DONE formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s applied=%s rejected=%s duration_ms=%s",
            formation_job_id,
            job_id,
            folder_id,
            seg_id,
            len(all_applied),
            len(all_rejected),
            int((time.time() - segment_started_at) * 1000),
        )
        details.append(
            {"segment_id": seg_id, "sub_idx": sub_idx, "passe": passe, "applied": all_applied, "rejected": all_rejected}
        )

    _progress(
        total,
        total,
        f"Terminé : {total_applied} appliqués, {total_rejected} rejetés, {total_failed} en erreur",
    )
    logger.info(
        "PIPELINE_REVIEW_DONE formation_job_id=%s content_job_id=%s folder_id=%s reviewed=%s/%s applied=%s rejected=%s failed=%s duration_ms=%s",
        formation_job_id,
        job_id,
        folder_id,
        total - total_failed,
        total,
        total_applied,
        total_rejected,
        total_failed,
        int((time.time() - started_at) * 1000),
    )
    return {
        "segments_reviewed": total - total_failed,
        "segments_failed": total_failed,
        "patches_applied": total_applied,
        "patches_rejected": total_rejected,
        "details": details,
    }
