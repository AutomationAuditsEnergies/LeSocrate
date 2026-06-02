"""
Service de génération de contenu TTS-direct.

Pipeline par dossier (= 1 journée de formation) :
  1. Extraction automatique de 7 cours depuis le programme (1 appel Claude)
  2. Pour chaque cours : Passe 1 → Passe 2 → Passe 3 (volume calibré audio)
  3. Total TTS-ready calibré sur les cours audio Fish Audio → document .txt

Checkpointing : chaque segment complété est sauvegardé en DB immédiatement.
En cas d'interruption, la génération reprend au segment suivant non complété.
"""

from __future__ import annotations

import io
import hashlib
import os
import re
import json
import threading
import time
import uuid as uuid_mod
from datetime import datetime

from database.db import get_db_connection
from utils.anthropic_client import (
    AnthropicAPIError,
    AnthropicRateLimitError,
    default_model,
    post_message as _llm_post,
)
from utils.logger import get_logger
from services.content_pipeline.artifacts import (
    CONTENT_AUDIO_PLAN_BLOB as _CONTENT_AUDIO_PLAN_BLOB,
    CONTENT_BUDGET_CALIBRATION_BLOB as _CONTENT_BUDGET_CALIBRATION_BLOB,
    CONTENT_COURSE_SCRIPTS_BLOB as _CONTENT_COURSE_SCRIPTS_BLOB,
    CONTENT_DRAFT_SECTIONS_BLOB as _CONTENT_DRAFT_SECTIONS_BLOB,
    CONTENT_ETHICAL_MICRO_REVIEW_BLOB as _CONTENT_ETHICAL_MICRO_REVIEW_BLOB,
    CONTENT_PLAN_BLOB as _CONTENT_PLAN_BLOB,
    CONTENT_QUALITY_REVIEWS_BLOB as _CONTENT_QUALITY_REVIEWS_BLOB,
    CONTENT_REVIEWED_SCRIPTS_BLOB as _CONTENT_REVIEWED_SCRIPTS_BLOB,
    COURSE_SCRIPT_PLAN_BLOB as _COURSE_SCRIPT_PLAN_BLOB,
    artifact_payload as _artifact_payload,
    content_artifacts_for_ui as _content_artifacts_for_ui,
    load_content_artifact as _load_content_artifact,
    save_content_artifact as _save_content_artifact,
)
from services.content_pipeline.calibration import (
    course_section_budget_defaults as _pipeline_course_section_budget_defaults,
    load_budget_rewrite_contract,
    structured_generation_max_tokens as _structured_generation_max_tokens,
)
from services.content_pipeline.planning import load_planning_prompt_parts
from services.content_pipeline.prompts import (
    load_prompt_file as _load_prompt_file,
    prompt_file_path as _prompt_file_path,
)
from services.content_pipeline.reviews import (
    AUDIO_BLOCK_MARKER_RE as _AUDIO_BLOCK_MARKER_RE,
    extract_audio_block_number as _extract_audio_block_number,
    load_structured_rule_file as _load_structured_rule_file,
    structured_review_context_for_segment as _structured_review_context_for_segment,
)
from services.content_pipeline.section_generation import load_section_prompt_parts
from services.content_pipeline.validators import (
    validate_structured_course_plan as _validate_structured_course_plan,
)

logger = get_logger(__name__)


CLAUDE_MODEL = default_model()
NUM_SUB_PARTS = 7
_COURSE_START_SILENCE_SECONDS = 17
# Fish Audio S2-Pro mesuré sur 72,2 min / 11 959 mots à speed=0.90.
_DEFAULT_TTS_WORDS_PER_MINUTE = 165.7
# Calibration Fish Audio observée sur les MP3 cours générés avec la voix
# actuelle. Objectif : viser la durée finale affichée à ~slot - 75s
# (ex. 43m30-44m00 pour un fichier de 45 min).
_DEFAULT_TTS_WPM_BY_BLOC = {
    1: 199.9,  # 36:16 -> ~43:45
    2: 197.7,  # 36:40 -> ~43:45
    3: 198.5,  # 44:52 -> ~53:45
    4: 207.4,  # 34:57 -> ~43:45
    5: 194.8,  # 49:58 -> ~58:45
    6: 213.9,  # 45:30 -> ~58:45
    7: 208.3,  # 38:47 -> ~48:45
}
_COURSE_CONCLUSION_START_MARGIN_SECONDS = 0
# Marge utilisée pour calculer moins de mots que la durée théorique.
# Elle ne coupe pas l'audio final : elle réduit seulement la parole générée.
_COURSE_FINAL_SILENCE_SECONDS = 120
_DEFAULT_TTS_SPEED = 0.90
_DEFAULT_TTS_LOCAL_MAX_SPEEDUP = 1.0
_DEFAULT_TTS_PREFLIGHT_SAFETY = 1.0
_SENTENCE_END_RE = re.compile(r"[.!?…][\"'»”’)\]]*$")
_CARRYOVER_INTRO = (
    "Avant d'entrer dans la suite, on reprend le point que nous "
    "n'avons pas terminé la dernière fois. On le pose proprement, puis on "
    "enchaînera naturellement avec le programme prévu."
)
_CARRYOVER_COLUMNS_READY = False
_FISHAUDIO_TAG_RE = re.compile(r"\[[^\[\]\n]{1,50}\]")
_INTERNAL_SCHEDULE_TIME_RANGE_RE = re.compile(
    r"\b(?:[01]?\d|2[0-3])\s*(?:h|:)\s*(?:[0-5]\d)?\s*"
    r"(?:[-–—]|à|a)\s*"
    r"(?:[01]?\d|2[0-3])\s*(?:h|:)\s*(?:[0-5]\d)?\b",
    re.IGNORECASE,
)
_INTERNAL_SCHEDULE_SINGLE_TIME_RE = re.compile(
    r"\b(?:[01]?\d|2[0-3])\s*h\s*(?:[0-5]\d)?\b|"
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b",
    re.IGNORECASE,
)
_LEARNER_FACING_SCHEDULE_LEAK_RE = re.compile(
    r"\b(?:horaires?|créneaux?|creneaux?|planning|emploi\s+du\s+temps)\b|"
    r"\b(?:trois\s+quarts?\s+d['’]heure|45\s+minutes?|quarante-cinq\s+minutes?)\s+"
    r"(?:à\s+venir|qui\s+viennent|prochaines?)\b|"
    r"(?:[01]?\d|2[0-3])\s*(?:h|:)\s*(?:[0-5]\d)?\s*"
    r"(?:[-–—]|à|a)\s*"
    r"(?:[01]?\d|2[0-3])\s*(?:h|:)\s*(?:[0-5]\d)?|"
    r"\b(?:[01]?\d|2[0-3])\s*h\s*(?:[0-5]\d)?\b|"
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b",
    re.IGNORECASE,
)
_LEARNER_FACING_INTERNAL_COURSE_RE = re.compile(
    r"\b(?:tout\s+premier\s+cours|premier\s+cours|ce\s+cours|cours\s+actuel|"
    r"cours\s+qui\s+nous\s+occupe|cours\s+qui\s+va\s+nous\s+occuper|"
    r"pour\s+(?:les\s+)?(?:trois\s+quarts?\s+d['’]heure|45\s+minutes?|quarante-cinq\s+minutes?)(?:\s+à\s+venir)?)\b",
    re.IGNORECASE,
)
_PART_SECTION_OPENING_LEAK_RE = re.compile(
    r"\b(?:bonjour\s+à\s+(?:tous|toutes)|bienvenue|"
    r"cadre\s+g[ée]n[ée]ral\s+(?:de\s+la\s+journ[ée]e|est\s+pos[ée])|"
    r"th[èe]mes?\s+de\s+la\s+journ[ée]e|programme\s+annuel|parcours\s+annuel|"
    r"tout\s+au\s+long\s+de\s+la\s+journ[ée]e|d['’]ici\s+ce\s+soir|"
    r"chemin\s+que\s+nous\s+allons\s+parcourir|"
    r"premi[èe]re\s+journ[ée]e\s+(?:est\s+)?cruciale|"
    r"pose\s+les\s+bases\s+de\s+tout\s+le\s+reste|"
    r"concentrons-nous\s+sur\s+aujourd['’]hui|"
    r"on\s+peut\s+entrer\s+dans\s+le\s+premier\s+grand\s+th[èe]me)\b",
    re.IGNORECASE,
)
_DUPLICATE_OPENING_CATEGORY_PATTERNS = {
    "annual_overview": re.compile(
        r"\b(?:programme\s+annuel|parcours\s+annuel|formation\s+sur\s+l['’]ann[ée]e)\b",
        re.IGNORECASE,
    ),
    "day_overview": re.compile(
        r"\b(?:th[èe]mes?\s+de\s+la\s+journ[ée]e|tout\s+au\s+long\s+de\s+la\s+journ[ée]e|"
        r"d['’]ici\s+ce\s+soir|chemin\s+que\s+nous\s+allons\s+parcourir|"
        r"cadre\s+g[ée]n[ée]ral\s+de\s+la\s+journ[ée]e)\b",
        re.IGNORECASE,
    ),
    "theme_opening": re.compile(
        r"\b(?:premier\s+grand\s+th[èe]me|cette\s+premi[èe]re\s+partie|"
        r"ce\s+premier\s+th[èe]me)\b.{0,260}\b(?:objectif|plan|axes?|fil\s+conducteur)\b",
        re.IGNORECASE | re.DOTALL,
    ),
}
_SLIDE_META_LEAK_RE = re.compile(
    r"\b(?:slides?|power\s*point|powerpoint|templates?|slide_anchor|anchor|teaching\s+beats?|beats?)\b",
    re.IGNORECASE,
)
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


def _fish_audio_course_workers() -> int:
    """Nombre de blocs cours Fish Audio lancés en parallèle dans une journée."""
    try:
        workers = int(os.getenv("FISH_AUDIO_COURSE_WORKERS", "5"))
    except (TypeError, ValueError):
        workers = 5
    return max(1, min(workers, 7))


def _fish_audio_429_retry_config() -> dict:
    try:
        max_retries = int(os.getenv("FISH_AUDIO_429_MAX_RETRIES", "4"))
    except (TypeError, ValueError):
        max_retries = 4
    try:
        base_wait = float(os.getenv("FISH_AUDIO_429_BASE_WAIT_SEC", "45"))
    except (TypeError, ValueError):
        base_wait = 45.0
    try:
        max_wait = float(os.getenv("FISH_AUDIO_429_MAX_WAIT_SEC", "240"))
    except (TypeError, ValueError):
        max_wait = 240.0
    return {
        "max_retries": max(0, max_retries),
        "base_wait_sec": max(1.0, base_wait),
        "max_wait_sec": max(1.0, max_wait),
    }


def _edge_tts_fast_cache_enabled() -> bool:
    value = (os.getenv("EDGE_TTS_FAST_TEST_CACHE", "true") or "").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _edge_tts_fast_cache_key(text: str) -> str:
    payload = json.dumps(
        {
            "text": text,
            "voice": os.getenv("EDGE_TTS_VOICE", "fr-FR-DeniseNeural"),
            "speed": os.getenv("BASIC_TTS_SPEED", "1.15"),
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


def _fish_timestamp_alignment_enabled() -> bool:
    """Utilise Fish Audio SSE timestampé pour mesurer le cours réellement lu."""
    value = (os.getenv("FORMATION_FISH_TIMESTAMP_ALIGNMENT", "true") or "").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _course_words_per_minute():
    """Fish Audio calibrated rate for the configured voice/speed."""
    return _env_float(
        "FORMATION_TTS_WORDS_PER_MINUTE",
        _DEFAULT_TTS_WORDS_PER_MINUTE,
        min_value=100,
        max_value=260,
    )


def _course_wpm_by_bloc_overrides() -> dict[int, float]:
    raw = (os.getenv("FORMATION_TTS_WPM_BY_BLOC") or "").strip()
    if not raw:
        return {}
    overrides: dict[int, float] = {}
    for part in raw.split(","):
        key, sep, value = part.partition(":")
        if not sep:
            continue
        try:
            bloc = int(key.strip())
            wpm = float(value.strip())
        except (TypeError, ValueError):
            continue
        if 1 <= bloc <= 7 and 100 <= wpm <= 260:
            overrides[bloc] = wpm
    return overrides


def _course_words_per_minute_for_bloc(bloc_number=None) -> float:
    """Cadence Fish par cours.

    `FORMATION_TTS_WORDS_PER_MINUTE` reste un override global. Sans override
    global, on applique la calibration par bloc issue des MP3 réels.
    `FORMATION_TTS_WPM_BY_BLOC` peut surcharger finement, ex:
    `1:198,2:196,3:197`.
    """
    global_wpm = _course_words_per_minute()
    if abs(global_wpm - _DEFAULT_TTS_WORDS_PER_MINUTE) > 0.001:
        return global_wpm
    try:
        bloc = int(bloc_number or 0)
    except (TypeError, ValueError):
        bloc = 0
    overrides = _course_wpm_by_bloc_overrides()
    return float(overrides.get(bloc, _DEFAULT_TTS_WPM_BY_BLOC.get(bloc, global_wpm)))


def _content_parallel_subpart_workers(default: int = 7) -> int:
    """Nombre de cours générés en parallèle."""
    try:
        workers = int(os.getenv("FORMATION_CONTENT_PARALLEL_SUBPART_WORKERS", str(default)))
    except (TypeError, ValueError):
        workers = default
    return max(1, min(16, workers))


def _structured_course_parallel_workers(default: int = 3) -> int:
    """Concurrence prudente pour le mode structuré."""
    try:
        workers = int(os.getenv("FORMATION_STRUCTURED_COURSE_WORKERS", str(default)))
    except (TypeError, ValueError):
        workers = default
    return max(1, min(7, workers))


def _runtime_intra_day_carryover_enabled() -> bool:
    """Autorise le report technique d'un reste audio vers le cours suivant.

    Désactivé par défaut : chaque cours doit rester autonome. Si un bloc est
    trop long, on réduit/régénère le texte plutôt que de terminer ce bloc au
    début du cours suivant.
    """
    value = (os.getenv("FORMATION_RUNTIME_INTRA_DAY_CARRYOVER") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _course_conclusion_start_margin_sec():
    return _env_float(
        "FORMATION_TTS_CONCLUSION_START_MARGIN_SEC",
        _COURSE_CONCLUSION_START_MARGIN_SECONDS,
        min_value=0,
        max_value=600,
    )


def _course_final_silence_sec():
    return _env_float(
        "FORMATION_TTS_FINAL_SILENCE_SEC",
        _COURSE_FINAL_SILENCE_SECONDS,
        min_value=60,
        max_value=180,
    )


def _words_budget_for_speaking_window(
    target_sec: int,
    stop_before_end_sec: float,
    *,
    words_per_minute: float | None = None,
) -> int:
    voice_seconds = max(
        0.0,
        float(target_sec) - float(stop_before_end_sec) - _COURSE_START_SILENCE_SECONDS,
    )
    wpm = float(words_per_minute if words_per_minute is not None else _course_words_per_minute())
    return int((voice_seconds / 60.0) * wpm * _course_preflight_safety())


def _course_speech_deadline_sec(target_sec: int | float) -> float:
    """Dernière seconde autorisée pour la parole avant la marge finale."""
    return max(0.0, float(target_sec or 0) - _course_final_silence_sec())


def _course_voice_window_sec(target_sec: int | float) -> float:
    """Durée maximale de voix réelle, hors marge initiale et marge finale."""
    return max(0.0, _course_speech_deadline_sec(target_sec) - _COURSE_START_SILENCE_SECONDS)


def _estimated_words_budget_for_course(target_sec, api_speed, bloc_number=None):
    """Total words allowed for spoken content, stopping before final silence."""
    return _words_budget_for_speaking_window(
        target_sec,
        _course_final_silence_sec(),
        words_per_minute=_course_words_per_minute_for_bloc(bloc_number),
    )


def _estimated_main_words_budget_for_course(target_sec, api_speed, bloc_number=None):
    """Words allowed for the canonical course block text.

    Conclusions and transitions are now part of the generated/calibrated block
    itself, so there is no separate runtime conclusion reserve.
    """
    return _estimated_words_budget_for_course(target_sec, api_speed, bloc_number)


def count_tts_spoken_words(text: str | None) -> int:
    """Compte les mots réellement parlés en ignorant les tags TTS `[pause]`."""
    cleaned = _strip_audio_block_markers(text or "")
    cleaned = _FISHAUDIO_TAG_RE.sub(" ", cleaned)
    return len(cleaned.split())


def _strip_audio_block_markers(text: str | None) -> str:
    """Retire les marqueurs internes de structuration audio du texte utilisateur/TTS."""
    return _AUDIO_BLOCK_MARKER_RE.sub("", text or "").strip()


def _preserve_audio_block_marker(original_text: str, updated_text: str) -> str:
    """Conserve le marqueur canonique `<<<BLOC_AUDIO_N>>>` après review."""
    match = _AUDIO_BLOCK_MARKER_RE.search(original_text or "")
    if not match:
        return updated_text or ""
    marker = match.group(0).strip()
    clean_updated = _strip_audio_block_markers(updated_text or "")
    return f"{marker}\n\n{clean_updated}".strip()


def get_course_day_word_budget(playlist_spec=None) -> dict:
    """Budget mots quotidien dérivé des seuls créneaux `cours`.

    Les Q&A/pauses ne sont pas intégrées au texte de cours et ne doivent donc
    pas gonfler la cible. Pour chaque créneau cours, on retire la marge
    initiale et la marge parole finale avant d'appliquer la cadence calibrée
    Fish Audio. Cette marge réduit le nombre de mots cible ; elle ne retire pas
    de minutes au fichier audio final.
    """
    if playlist_spec is None:
        from services.playlist_tts_service import PLAYLIST_SPEC as playlist_spec

    course_items = [
        (filename, int(duration or 0), int(bloc_num or 0))
        for filename, duration, file_type, bloc_num in playlist_spec
        if file_type == "cours"
    ]
    per_course = []
    target_words = 0
    speakable_seconds = 0.0
    for filename, duration_sec, bloc_num in course_items:
        voice_window = _course_voice_window_sec(duration_sec)
        words = _estimated_words_budget_for_course(duration_sec, _DEFAULT_TTS_SPEED, bloc_num)
        target_words += words
        speakable_seconds += voice_window
        per_course.append({
            "filename": filename,
            "bloc_number": bloc_num,
            "duration_sec": duration_sec,
            "speakable_sec": round(voice_window, 3),
            "words_per_minute": round(_course_words_per_minute_for_bloc(bloc_num), 3),
            "target_words": words,
        })

    min_ratio = _env_float("FORMATION_TTS_DAY_WORD_MIN_RATIO", 0.94, min_value=0.70, max_value=1.0)
    max_ratio = _env_float("FORMATION_TTS_DAY_WORD_MAX_RATIO", 1.02, min_value=1.0, max_value=1.20)
    try:
        max_extra = int(os.getenv("FORMATION_TTS_DAY_WORD_MAX_EXTRA", "350"))
    except (TypeError, ValueError):
        max_extra = 350

    min_words = int(target_words * min_ratio)
    max_words = max(int(target_words * max_ratio), target_words + max(0, max_extra))
    return {
        "target_words": int(target_words),
        "min_words": int(min_words),
        "max_words": int(max_words),
        "words_per_minute": (
            round((target_words / (speakable_seconds / 60.0)), 3)
            if speakable_seconds > 0 else float(_course_words_per_minute())
        ),
        "course_seconds": int(sum(item[1] for item in course_items)),
        "speakable_seconds": round(speakable_seconds, 3),
        "start_silence_sec": int(_COURSE_START_SILENCE_SECONDS),
        "final_silence_sec": float(_course_final_silence_sec()),
        "course_items": per_course,
    }


def _course_block_for_generation_context(generation_context=None) -> dict | None:
    """Retourne le bloc cours associé à la sous-partie générée, si connu."""
    if not generation_context:
        return None
    try:
        sub_idx = int(generation_context.get("sub_part_index", -1))
    except (TypeError, ValueError):
        return None
    bloc_number = sub_idx + 1
    for block in _course_audio_block_plan(
        folder_position=generation_context.get("folder_position"),
    ):
        if int(block.get("bloc_number") or 0) == bloc_number:
            return block
    return None


def get_course_segment_generation_budget(segment_count: int = NUM_SUB_PARTS * 3,
                                         generation_context=None) -> dict:
    """Budget indicatif par segment pour que la journée tombe juste après review."""
    day_budget = get_course_day_word_budget()
    reserve_ratio = _env_float(
        "FORMATION_TTS_GENERATION_REVIEW_RESERVE_RATIO",
        0.97,
        min_value=0.80,
        max_value=1.0,
    )
    block = _course_block_for_generation_context(generation_context)
    if block:
        segment_count = 3
        target = max(800, int(int(block["target_words"]) * reserve_ratio / segment_count))
        minimum = max(700, int(int(block["min_words"]) / segment_count))
        maximum = max(target, int(int(block["max_words"]) / segment_count))
        block_budget = block
    else:
        segment_count = max(1, int(segment_count or 1))
        target = max(800, int(day_budget["target_words"] * reserve_ratio / segment_count))
        minimum = max(700, int(day_budget["min_words"] / segment_count))
        maximum = max(target, int(day_budget["max_words"] / segment_count))
        block_budget = None
    return {
        "target_words": target,
        "min_words": minimum,
        "max_words": maximum,
        "day_budget": day_budget,
        "segment_count": segment_count,
        "block_budget": block_budget,
    }


def _build_generation_volume_context(generation_context=None) -> str:
    budget = get_course_segment_generation_budget(generation_context=generation_context)
    day = budget["day_budget"]
    block = budget.get("block_budget")
    final_margin_sec = int(round(_course_final_silence_sec()))
    final_margin_min = final_margin_sec / 60.0
    final_margin_words = int((final_margin_sec / 60.0) * float(day["words_per_minute"]))
    block_line = ""
    if block:
        block_line = (
            f"\nCette passe appartient au cours interne {block['bloc_number']} "
            f"({block['filename']}, {block['duration_min']} min). Le cours complet "
            f"doit viser {block['target_words']} mots parlés, avec une plage "
            f"{block['min_words']}–{block['max_words']} mots. Les trois passes de "
            "cette unité interne doit donc se compléter sans déborder sur la suivante. "
            "Ces données sont internes : ne les verbalise jamais aux apprenants.\n"
        )
    return f"""
═══════════════════════════════════════════════════════════════════
CONTRAINTE VOLUME AUDIO PRIORITAIRE — FISH AUDIO
═══════════════════════════════════════════════════════════════════
La journée est maintenant calculée au mot près sur les cours internes,
hors Q&A et hors pauses.

Cadence calibrée : {day['words_per_minute']:.0f} mots/minute.
Budget journée cours uniquement : cible {day['target_words']} mots parlés,
tolérance {day['min_words']} à {day['max_words']} mots.
Le budget ne coupe pas l'audio final : il réduit seulement le nombre de mots
demandés. Il retire déjà la marge initiale et une marge parole finale de
{final_margin_sec} secondes ({final_margin_min:.1f} min), soit environ
{final_margin_words} mots en moins par rapport à une parole continue jusqu'à la
fin du cours interne.

Cette passe doit viser environ {budget['target_words']} mots utiles,
avec une plage acceptable de {budget['min_words']} à {budget['max_words']}
mots. Cette consigne remplace toutes les anciennes consignes qui parlaient
de 5 000 mots ou de 90 000 mots par journée.
{block_line}

N'allonge pas artificiellement le texte. Ne cherche pas à remplir les Q&A
ou les pauses : ils ont leurs propres fichiers et ne comptent pas ici.
Ne parle jamais côté apprenant d'horaires, de créneaux, de planning, de durée
de fichier ou de budget mots.
"""


def _structured_content_generation_enabled() -> bool:
    value = (os.getenv("FORMATION_STRUCTURED_CONTENT_GENERATION", "true") or "").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _structured_course_kind(course_number: int) -> str:
    if course_number == 1:
        return "opening_year_day"
    if course_number == 7:
        return "end_of_day"
    return "standard_reprise"


def _clean_llm_text(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    text = _strip_audio_block_markers(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_internal_schedule_from_label(value: str | None) -> str:
    """Retire les horaires techniques des libellés injectés dans les prompts."""
    original = str(value or "").strip()
    if not original:
        return ""
    text = _INTERNAL_SCHEDULE_TIME_RANGE_RE.sub("", original)
    text = _INTERNAL_SCHEDULE_SINGLE_TIME_RE.sub("", text)
    text = re.sub(r"\b(?:45|50|55|60)\s*minutes\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*[-–—]\s*[-–—]\s*", " — ", text)
    text = re.sub(r"\s*[-–—]\s*:\s*", " — ", text)
    text = re.sub(r"\s*:\s*[-–—]\s*", " — ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = re.sub(r"\s*[-–—]\s*$", "", text).strip()
    text = re.sub(r"^\s*[-–—]\s*", "", text).strip()
    text = re.sub(r"^cours\s+\d+\s*[-–—:]\s*", "", text, flags=re.IGNORECASE).strip()
    return text or original


def _sanitize_learner_facing_text(text: str) -> str:
    # Ne fait pas de remplacement lexical automatique : les reformulations
    # sensibles, comme "bloc" côté apprenant, relèvent de la conformité IA afin
    # de choisir naturellement entre "cours", "partie", "séquence" ou "moment".
    return (text or "").strip()


def _parse_structured_course_plan(raw: str) -> dict:
    data = _extract_llm_json(raw)
    if "courses" not in data and "course_plans" in data:
        data["courses"] = data.get("course_plans")
    if not isinstance(data.get("courses"), list):
        raise ValueError("Plan structuré invalide : clé courses absente")
    return data


def _merge_unique_strings(*values) -> list[str]:
    seen = set()
    merged = []
    for value in values:
        if isinstance(value, str):
            candidates = [value]
        elif isinstance(value, list):
            candidates = value
        else:
            candidates = []
        for item in candidates:
            clean = str(item or "").strip()
            key = clean.lower()
            if clean and key not in seen:
                seen.add(key)
                merged.append(clean)
    return merged


_BEAT_TYPE_TO_TEMPLATE = {
    "welcome": "welcome",
    "day_welcome": "welcome",
    "day_program": "day_program",
    "agenda": "day_program",
    "definition": "reflection",
    "concept": "reflection",
    "key_message": "reflection",
    "process": "facilitator",
    "method": "facilitator",
    "framework": "facilitator",
    "steps": "facilitator",
    "checklist": "recap",
    "recap": "recap",
    "takeaways": "recap",
    "example": "casestudy",
    "case": "casestudy",
    "comparison": "casestudy",
    "warning": "warning",
    "mistake": "warning",
    "risk": "warning",
    "tip": "tip",
    "advice": "tip",
    "good_practice": "tip",
    "story": "story",
    "scenario": "story",
    "analogy": "analogy",
    "metaphor": "analogy",
    "data": "stats",
    "numbers": "stats",
    "chart": "chart",
    "transition": "transition",
    "opinion": "opinion",
}
_SUPPORTED_SLIDE_TEMPLATES = {
    "welcome",
    "day_program",
    "reflection",
    "casestudy",
    "facilitator",
    "stats",
    "story",
    "recap",
    "analogy",
    "warning",
    "tip",
    "opinion",
    "transition",
    "chart",
}
_ETHICAL_MICRO_RULE_IDS = [14, 15]
_ETHICAL_MICRO_RULESET_VERSION = "2026-05-31-ethical-micro-v3-minimal"
_ETHICAL_MICRO_RULES_CACHE = {"mtime": None, "text": ""}
_ETHICAL_LEXICAL_TERMS_CACHE = {"mtime": None, "data": None}


def _load_slide_template_catalog() -> dict:
    raw = _load_prompt_file("slides", "template-catalog.json", fallback="")
    if not raw:
        return {"version": "missing", "templates": []}
    try:
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("⚠️ Catalogue templates slides invalide: %s", exc)
        return {"version": "invalid", "templates": []}
    if not isinstance(data.get("templates"), list):
        data["templates"] = []
    return data


def _slide_template_catalog_prompt() -> str:
    catalog = _load_slide_template_catalog()
    templates = []
    for item in catalog.get("templates") or []:
        if not isinstance(item, dict):
            continue
        template_id = item.get("template_id")
        if template_id not in _SUPPORTED_SLIDE_TEMPLATES:
            continue
        templates.append({
            "template_id": template_id,
            "families": item.get("families") or [],
            "use_when": item.get("use_when") or "",
            "avoid_when": item.get("avoid_when") or "",
            "requires": item.get("requires") or {},
        })
    return json.dumps(
        {
            "catalog_version": catalog.get("version"),
            "principle": catalog.get("principle"),
            "templates": templates,
        },
        ensure_ascii=False,
        indent=2,
    )


def _slide_template_for_beat(beat_type: str | None, requested: str | None = None) -> str:
    requested_key = str(requested or "").strip().lower()
    if requested_key in _SUPPORTED_SLIDE_TEMPLATES:
        return requested_key
    alias = _BEAT_TYPE_TO_TEMPLATE.get(requested_key)
    if alias in _SUPPORTED_SLIDE_TEMPLATES:
        return alias
    beat_key = str(beat_type or "").strip().lower()
    return _BEAT_TYPE_TO_TEMPLATE.get(beat_key, "reflection")


def _normalize_teaching_beats(raw_part: dict, *, course_number: int, part_number: int) -> list[dict]:
    raw_beats = raw_part.get("teaching_beats") if isinstance(raw_part.get("teaching_beats"), list) else []
    if not raw_beats:
        raw_beats = [
            {
                "type": "concept",
                "role": "poser l'idée centrale de cette partie",
                "spoken_requirement": (
                    "Présenter clairement l'idée principale de cette partie avec une formulation "
                    "orale concrète et mémorisable."
                ),
                "slide_anchor": {
                    "enabled": True,
                    "template_type": "reflection",
                    "visual_goal": "faire retenir l'idée centrale",
                },
            }
        ]

    normalized = []
    for idx, raw in enumerate(raw_beats[:5], start=1):
        if not isinstance(raw, dict):
            continue
        beat_type = str(raw.get("type") or raw.get("beat_type") or "concept").strip().lower()
        role = str(raw.get("role") or raw.get("intent") or "développer un point pédagogique").strip()
        spoken_requirement = str(
            raw.get("spoken_requirement")
            or raw.get("requirement")
            or raw.get("description")
            or role
        ).strip()
        anchor = raw.get("slide_anchor") if isinstance(raw.get("slide_anchor"), dict) else {}
        enabled = bool(anchor.get("enabled", idx == 1))
        template_type = _slide_template_for_beat(
            beat_type,
            anchor.get("template_type") or anchor.get("template_family") or raw.get("template_type"),
        )
        beat_id = str(raw.get("beat_id") or f"c{course_number}p{part_number}b{idx}").strip()
        slide_anchor = {
            "enabled": enabled,
            "anchor_id": str(anchor.get("anchor_id") or f"{beat_id}-slide").strip(),
            "template_type": template_type,
            "visual_goal": str(anchor.get("visual_goal") or "visualiser le point pédagogique").strip(),
            "items_expected": anchor.get("items_expected"),
            "fields_hint": anchor.get("fields_hint") if isinstance(anchor.get("fields_hint"), dict) else {},
        }
        normalized.append({
            "beat_id": beat_id,
            "type": beat_type,
            "role": role,
            "spoken_requirement": spoken_requirement,
            "slide_anchor": slide_anchor,
        })

    return normalized


def _opening_structure_teaching_beats(
    *,
    course_number: int,
    day_number: int | None,
    job: dict,
    sub_parts: list,
    is_first_day: bool,
) -> list[dict]:
    if course_number != 1:
        return []

    formation_name = (
        job.get("program_title")
        or job.get("tp_name")
        or job.get("title")
        or "formation"
    )
    day_label = f"Journée {day_number}" if day_number else "Journée"
    day_title = job.get("folder_name") or day_label
    program_items = [
        _strip_internal_schedule_from_label(str(item or "")).strip()
        for item in (sub_parts or [])[:7]
    ]
    program_items = [item for item in program_items if item]
    welcome_requirement = (
        f"Accueillir les apprenants en disant clairement qu'ils entrent dans la {day_label.lower()} "
        f"de la formation {formation_name}, avec une formule orale simple et chaleureuse."
    )
    if is_first_day:
        welcome_requirement = (
            f"Accueillir les apprenants au lancement de la formation {formation_name}, puis situer "
            f"cette première journée avec une formule orale simple et chaleureuse."
        )

    return [
        {
            "beat_id": "c1opening-welcome",
            "type": "welcome",
            "role": "accueillir la journée de formation",
            "spoken_requirement": welcome_requirement,
            "slide_anchor": {
                "enabled": True,
                "anchor_id": "day-opening-welcome-slide",
                "template_type": "welcome",
                "visual_goal": "installer immédiatement le cadre de la journée et le nom de la formation",
                "items_expected": None,
                "fields_hint": {
                    "formation_name": formation_name,
                    "day_label": day_label,
                    "title": "Bienvenue",
                    "subtitle": day_title,
                },
            },
        },
        {
            "beat_id": "c1opening-day-program",
            "type": "day_program",
            "role": "annoncer le programme du jour",
            "spoken_requirement": (
                "Présenter les grands thèmes de la journée dans leur ordre pédagogique, sans parler "
                "d'horaires, de durées, de créneaux ou de planning."
            ),
            "slide_anchor": {
                "enabled": True,
                "anchor_id": "day-opening-program-slide",
                "template_type": "day_program",
                "visual_goal": "donner une carte claire des thèmes de la journée avant le premier contenu",
                "items_expected": len(program_items) or None,
                "fields_hint": {
                    "title": "Programme de la journée",
                    "day_label": day_label,
                    "formation_name": formation_name,
                    "items": program_items,
                },
            },
        },
    ]


def _merge_opening_teaching_beats(forced: list[dict], existing: list[dict]) -> list[dict]:
    merged = []
    seen = set()

    def structural_key(beat: dict) -> str:
        anchor = beat.get("slide_anchor") if isinstance(beat.get("slide_anchor"), dict) else {}
        template_type = _slide_template_for_beat(
            beat.get("type"),
            anchor.get("template_type") or anchor.get("template_family") or beat.get("template_type"),
        )
        if template_type in {"welcome", "day_program"}:
            return f"template:{template_type}"
        beat_id = str(beat.get("beat_id") or "").strip()
        anchor_id = str(anchor.get("anchor_id") or "").strip()
        return anchor_id or beat_id or f"beat:{len(merged)}"

    # Prefer the model's opening beats when they already cover the required
    # structure. Forced beats are a fallback, not extra slides.
    for beat in [*(existing or []), *(forced or [])]:
        if not isinstance(beat, dict):
            continue
        key = structural_key(beat)
        if key in seen:
            continue
        seen.add(key)
        merged.append(beat)
    return merged[:5]


def _next_playlist_item_after_index(playlist_spec, idx: int):
    try:
        return playlist_spec[idx + 1] if idx + 1 < len(playlist_spec) else None
    except Exception:
        return None


def _course_block_role(bloc_number: int, *, folder_position=None, next_item=None) -> str:
    """Direction artistique du bloc audio selon sa position dans la journée."""
    day_number = None
    try:
        day_number = int(folder_position) + 1 if folder_position is not None else None
    except Exception:
        day_number = None

    parts = []
    if bloc_number == 1 and day_number == 1:
        parts.append(
            "Ouverture absolue de la formation : accueil calme, présentation "
            "synthétique du parcours annuel, thèmes de la journée dans leur ordre pédagogique, "
            "transition vers le premier grand thème, plan oral en 2 à 4 axes, puis seulement "
            "lancement progressif du premier sujet."
        )
    elif bloc_number == 1:
        parts.append(
            "Ouverture de journée : reprise douce, rappel vague de la progression, "
            "objectifs de la journée, puis transition naturelle vers le premier sujet."
        )
    elif bloc_number == 2:
        parts.append(
            "Reprise autonome après Q&A/pause : ne jamais terminer la partie précédente. "
            "Faire un rappel très bref de ce qui a été vu, relier la posture "
            "d'accueil à distance au nouveau thème, annoncer l'objectif puis "
            "un plan de 2 à 4 axes avant tout exemple."
        )
    else:
        parts.append(
            "Bloc de continuité : reprendre le fil sans rupture, avancer dans la notion, "
            "insérer respirations pédagogiques, exemples terrain et mini-synthèses."
        )

    if bloc_number == 7:
        parts.append(
            "Fin de journée : conclusion progressive, synthèse des idées essentielles, "
            "valorisation du chemin parcouru et projection sobre vers la suite."
        )

    next_type = next_item[2] if next_item and len(next_item) >= 3 else None
    next_duration = int(next_item[1] or 0) if next_item and len(next_item) >= 2 else 0
    if next_type in {"qa", "pause", "pause_midi"}:
        if next_type == "qa":
            qa_outro = (
                "Outro : annoncer que l'on va passer au temps de questions-réponses. "
                "Le Q&A suivant démarre sans introduction propre."
            )
            if bloc_number == 1:
                qa_outro += (
                    " Pour le premier thème interne, après cette annonce, aucun nouveau "
                    "développement ne doit suivre."
                )
            elif bloc_number == 2:
                qa_outro += (
                    " Pour le deuxième thème interne, ne pas ouvrir la suite et ne pas "
                    "réexpliquer la partie précédente après cette annonce."
                )
            parts.append(qa_outro)
        elif next_type == "pause_midi":
            parts.append(
                "Outro : annoncer naturellement la pause déjeuner. "
                "Le fichier pause suivant démarre sans introduction propre."
            )
        else:
            minutes = max(1, round(next_duration / 60)) if next_duration else None
            pause_label = f" de {minutes} minutes" if minutes else ""
            parts.append(
                f"Outro : annoncer naturellement une pause{pause_label}. "
                "Le fichier pause suivant démarre sans introduction propre."
            )

    return " ".join(parts)


_COURSE_SLOT_PROMPT_PROFILES = {
    1: {
        "label": "Cours interne 1 — ouverture de la formation et premier grand thème",
        "moment": "première grande partie de la journée, et potentiellement ouverture absolue de l'année",
        "intention": (
            "installer une carte mentale claire avant le contenu : parcours global, "
            "thèmes de la journée, transition naturelle vers le premier grand thème, "
            "objectif et plan oral en axes"
        ),
        "rhythm": (
            "progressif, accueillant et très clair : accueil humain, cadrage explicite, "
            "plan annoncé, puis exemples courts seulement après la structure"
        ),
        "structure": [
            "accueillir les apprenants sans démarrer par une métaphore ou un cas client",
            "si c'est l'ouverture absolue de l'année, présenter synthétiquement les grands thèmes de la formation",
            "annoncer les thèmes de la journée dans leur ordre pédagogique sans parler d'horaires ni de planning",
            "basculer naturellement vers le premier grand thème de la journée",
            "formuler l'objectif de cette première partie et ce que l'apprenant saura mieux faire ensuite",
            "annoncer un plan oral en 2 à 4 axes et suivre ce plan dans le même ordre",
            "verbaliser chaque changement de partie avec une transition claire",
            "conclure par 3 à 4 minutes équivalent audio : récapitulatif des points vus, utilité concrète, annonce du Q&A dans le tchat",
            "arrêter strictement le texte après l'annonce du Q&A : aucun exemple, aucune mini-synthèse, aucun remplissage après la conclusion",
        ],
        "examples": "exemples simples et explicitement fictifs, uniquement après l'annonce du cadre et du plan",
        "avoid": [
            "démarrage direct par la relation client, la voix de l'entreprise ou un client mécontent",
            "storytelling avant que l'apprenant sache où il est et ce qu'il va apprendre",
            "tunnels émotionnels ou métaphores longues sans idée nouvelle identifiable",
            "vocabulaire littéraire ou trop abstrait pour un cours magistral professionnel",
            "blocs répétés comme 'Prenons quelques secondes pour ancrer cette idée'",
            "dire 'tout premier cours', 'ce cours', 'cours actuel' ou 'trois quarts d'heure à venir'",
            "nouveau développement après la conclusion et l'annonce du Q&A",
        ],
        "handoff": "annoncer uniquement le passage au temps de questions-réponses dans le tchat, sans transition vers le thème suivant",
    },
    2: {
        "label": "Cours interne 2 — reprise autonome et nouveau thème",
        "moment": "reprise après le Q&A et la pause qui suivent la première partie",
        "intention": (
            "ouvrir une nouvelle partie autonome de la journée : rappeler brièvement "
            "ce qui a été posé avant la pause, puis basculer vers le nouveau thème "
            "avec objectif, axes et progression claire"
        ),
        "rhythm": (
            "reprise douce mais nette : quelques phrases de lien, annonce du "
            "nouveau thème, plan oral en 2 à 4 axes, puis développement "
            "méthodique avec transitions visibles"
        ),
        "structure": [
            "commencer par une reprise autonome : ne jamais finir une idée qui appartenait à la partie précédente",
            "rappeler en une ou deux phrases ce qui a été abordé au cours précédent",
            "faire le lien entre le thème précédent et le nouveau thème",
            "annoncer clairement ce que cette nouvelle partie va travailler et pourquoi c'est utile",
            "annoncer un plan de 2 à 4 axes maximum avant tout exemple développé",
            "développer les parties dans l'ordre annoncé, chacune avec une idée nouvelle identifiable",
            "verbaliser les transitions : passons au deuxième point, maintenant que nous avons vu X, intéressons-nous à Y",
            "conclure par 3 à 4 minutes équivalent audio : récapitulatif des points de cette partie, utilité concrète, annonce du Q&A dans le tchat",
        ],
        "examples": "exemples simples et explicitement fictifs si le cas n'est pas issu du programme, uniquement après le rappel, le lien et le plan",
        "avoid": [
            "commencer par 'Et puis', 'Ensuite' ou une phrase qui continue directement la conclusion de la partie précédente",
            "terminer une notion absente du texte écrit de la partie précédente",
            "rejouer la conclusion de la partie précédente ou annoncer son Q&A",
            "démarrer par un exemple comme Monsieur Klein avant d'avoir annoncé le nouveau thème et le plan",
            "faire une double introduction du nouveau thème",
            "dire 'ce cours' ou 'cours actuel' côté apprenant",
            "réexpliquer longuement la partie précédente",
            "changer de thème sans transition explicite",
            "accumuler des conseils non hiérarchisés",
        ],
        "handoff": "annoncer uniquement le passage au temps de questions-réponses dans le tchat si un Q&A suit, sans transition vers le thème suivant",
    },
    3: {
        "label": "Cours 3 — densité avant respiration longue",
        "moment": "troisième cours de la journée, juste avant une respiration plus longue",
        "intention": (
            "traiter un point dense, pousser le raisonnement, faire travailler les "
            "arbitrages et refermer proprement cette première grande séquence"
        ),
        "rhythm": (
            "soutenu mais respirable : séquences d'explication plus longues, pauses pédagogiques, "
            "synthèses intermédiaires pour ne pas saturer"
        ),
        "structure": [
            "rappeler en une phrase où on en est dans la progression de la journée",
            "entrer dans une situation plus exigeante ou un cas plus complet",
            "montrer les décisions successives à prendre",
            "insister sur les pièges, limites et critères de qualité",
            "conclure clairement cette séquence avant le Q&A ou la pause",
        ],
        "examples": "cas complexe, diagnostic, arbitrage, client difficile, erreur de procédure, correction commentée",
        "avoid": [
            "ouvrir un gros sujet qui ne pourra pas être refermé",
            "finir sur une phrase suspendue",
            "enchaîner trop de notions nouvelles sans respiration",
            "annoncer la pause comme une coupure administrative froide",
        ],
        "handoff": "faire sentir que la séquence a une vraie conclusion avant la pause ou le déjeuner",
    },
    4: {
        "label": "Cours 4 — reprise après déjeuner",
        "moment": "début d'après-midi, reprise après déjeuner",
        "intention": (
            "remettre l'apprenant en mouvement sans brutalité, reconnecter au fil de la journée "
            "et ouvrir une séquence autonome plus concrète"
        ),
        "rhythm": (
            "calme et relance douce : phrases plus courtes au départ, exemples accessibles, "
            "puis montée progressive vers l'application"
        ),
        "structure": [
            "reprendre avec une amorce de relance, pas avec un rappel lourd",
            "rattacher ce qui a déjà été vu au nouveau sujet",
            "lancer une application pratique ou un nouveau terrain d'exemple",
            "faire alterner explication et mise en situation",
            "finir sur un point clair pour éviter l'effet tunnel",
        ],
        "examples": "cas simple de reprise, application terrain, situation de service, comparaison avant/après",
        "avoid": [
            "supposer une attention maximale dès la première phrase",
            "reprendre toute la séquence précédente en détail",
            "démarrer par une abstraction lourde",
            "finir sans signal de clôture",
        ],
        "handoff": "préparer la montée en profondeur des cours longs d'après-midi",
    },
    5: {
        "label": "Cours 5 — grand développement de l'après-midi",
        "moment": "cours long d'approfondissement après la reprise",
        "intention": (
            "développer la séquence la plus substantielle : approfondissement, démonstration, variations, "
            "contre-exemples et consolidation"
        ),
        "rhythm": (
            "ample et maîtrisé : accepter des développements longs, mais avec des jalons fréquents "
            "pour garder le fil oral"
        ),
        "structure": [
            "annoncer clairement la compétence travaillée",
            "déployer l'explication en plusieurs sous-situations",
            "alterner principe, exemple, piège, correction",
            "montrer des variantes du même problème pour éviter l'apprentissage superficiel",
            "faire une vraie mini-synthèse avant la transition",
        ],
        "examples": "scénarios professionnels complets, contre-exemples, analyse d'une mauvaise réponse, amélioration progressive",
        "avoid": [
            "remplissage générique pour tenir la durée",
            "redite des parties précédentes",
            "enchaînement de listes sans narration pédagogique",
            "absence de jalons dans un long passage",
        ],
        "handoff": "donner le sentiment d'une séquence maîtrisée, puis préparer la mise en maîtrise",
    },
    6: {
        "label": "Cours 6 — mise en maîtrise",
        "moment": "dernière grande séquence avant la fin de journée",
        "intention": (
            "passer de la compréhension à la maîtrise : relier les compétences, traiter les cas limites "
            "et montrer comment décider dans une vraie situation"
        ),
        "rhythm": (
            "assuré, nuancé, orienté pratique : moins de définitions, plus de décisions, "
            "de comparaisons et de posture professionnelle"
        ),
        "structure": [
            "reprendre le résultat de la partie précédente sans le répéter",
            "mettre les notions en tension dans un cas plus réaliste",
            "montrer les critères de décision et les arbitrages",
            "faire verbaliser la posture attendue",
            "préparer la dernière ligne droite sans conclure toute la journée",
        ],
        "examples": "cas limites, conflit de priorités, décision à prendre, posture professionnelle, reformulation experte",
        "avoid": [
            "revenir à des bases déjà acquises",
            "ouvrir trop de nouveaux sujets",
            "faire une conclusion finale trop tôt",
            "traiter le cas pratique comme une simple illustration décorative",
        ],
        "handoff": "ouvrir naturellement vers la consolidation finale de la journée",
    },
    7: {
        "label": "Cours 7 — consolidation et clôture",
        "moment": "fin de journée, dernier cours avant le Q&A final",
        "intention": (
            "terminer la progression du jour, consolider les apprentissages, faire une synthèse utile "
            "et projeter sobrement vers la suite"
        ),
        "rhythm": (
            "posé, conclusif, valorisant sans emphase : on ralentit légèrement, on relie, "
            "on donne de la lisibilité et on évite d'ouvrir un chantier neuf"
        ),
        "structure": [
            "réactiver le fil de la journée en quelques phrases",
            "terminer le dernier point prévu ou le dernier exemple utile",
            "relier les notions principales sans refaire tout le cours",
            "donner les points clés à retenir pour la pratique",
            "conclure la journée et ouvrir vers la prochaine séance si le programme le demande",
        ],
        "examples": "dernier cas d'intégration, synthèse appliquée, checklist mentale, situation de transfert au poste",
        "avoid": [
            "démarrer un gros sujet neuf",
            "faire un résumé exhaustif de plusieurs heures",
            "finir abruptement",
            "survaloriser artificiellement ou faire une conclusion trop solennelle",
        ],
        "handoff": "annoncer le Q&A final ou la suite de formation avec sobriété",
    },
}


def _course_slot_prompt_profile(bloc_number: int | str | None, passe: int | str | None = None) -> str:
    """Profil éditorial stable par cours audio interne."""
    try:
        bloc = int(bloc_number or 0)
    except (TypeError, ValueError):
        bloc = 0
    try:
        passe_num = int(passe or 0)
    except (TypeError, ValueError):
        passe_num = 0

    profile = _COURSE_SLOT_PROMPT_PROFILES.get(bloc)
    if not profile:
        return ""

    passe_focus = {
        1: "Passe 1 : poser les bases de la partie, clarifier les notions et préparer l'écoute.",
        2: "Passe 2 : développer la pratique, les exemples, les gestes professionnels et les cas terrain.",
        3: "Passe 3 : consolider, nuancer, relier les idées et finir le cours proprement.",
    }.get(passe_num, "Passe : respecter la progression Fondation / Pratique / Maîtrise.")

    lines = [
        f"- Profil : {profile.get('label', f'Cours {bloc}')}.",
        f"- Moment : {profile['moment']}.",
        f"- Intention pédagogique : {profile['intention']}.",
        f"- Rythme et voix : {profile['rhythm']}.",
        "- Structure interne attendue :",
    ]
    lines.extend(f"  {idx}. {item}" for idx, item in enumerate(profile.get("structure", []), 1))
    lines.extend([
        f"- Exemples à privilégier : {profile['examples']}.",
        "- À éviter :",
    ])
    lines.extend(f"  - {item}" for item in profile.get("avoid", []))
    lines.extend([
        f"- Sortie de la partie : {profile['handoff']}.",
        f"- Focus de cette passe : {passe_focus}",
    ])
    return "\n".join(lines)


def _normalize_structured_course_plans(raw_plan: dict, *, job: dict, playlist_items: list, sub_parts: list) -> dict:
    """Valide et complète les plans JSON. Les budgets serveur font autorité."""
    block_plan = _course_audio_block_plan(playlist_items, folder_position=job.get("folder_position"))
    budgets_by_course = {int(b["bloc_number"]): b for b in block_plan}
    raw_by_number = {}
    for item in raw_plan.get("courses") or []:
        try:
            raw_by_number[int(item.get("course_number"))] = item
        except Exception:
            continue

    try:
        day_number = int(job.get("folder_position") or 0) + 1
    except Exception:
        day_number = None
    try:
        nb_days = int(job.get("nb_days") or 0) or None
    except Exception:
        nb_days = None
    is_last_day = bool(nb_days and day_number == nb_days)

    courses = []
    for course_number in range(1, 8):
        raw = raw_by_number.get(course_number) or {}
        budget_block = budgets_by_course.get(course_number) or {}
        target_words = int(budget_block.get("target_words") or budget_block.get("max_words") or 1200)
        title = _strip_internal_schedule_from_label(
            raw.get("course_title")
            or (sub_parts[course_number - 1] if course_number - 1 < len(sub_parts) else f"Cours {course_number}")
        ).strip()
        raw_parts = raw.get("parts") if isinstance(raw.get("parts"), list) else []
        parts_count = max(2, min(4, len(raw_parts) or 3))
        budgets = _pipeline_course_section_budget_defaults(
            course_number,
            target_words,
            parts_count,
            words_per_minute=_course_words_per_minute(),
            is_last_day=is_last_day,
        )

        opening = raw.get("opening") if isinstance(raw.get("opening"), dict) else {}
        opening.setdefault("type", "ouverture_formation" if course_number == 1 else "reprise_apres_qa_pause")
        opening["target_words"] = budgets["opening"]
        if course_number == 1 and day_number == 1:
            forced_opening_include = [
                "accueil oral des apprenants",
                "présentation synthétique du programme annuel",
                "présentation des thèmes de la journée dans leur ordre pédagogique",
                "transition naturelle vers le premier grand thème",
                "objectif de cette première partie",
                "plan oral en axes avant tout exemple",
            ]
            forced_opening_avoid = [
                "démarrer directement par un exemple",
                "storytelling avant carte mentale",
                "mot bloc devant les élèves",
                "dire ce cours ou tout premier cours devant les élèves",
                "mentionner trois quarts d'heure ou une durée",
            ]
        elif course_number == 1:
            forced_opening_include = [
                "accueil oral des apprenants",
                "reprise douce de la progression de formation",
                "présentation des thèmes de la journée dans leur ordre pédagogique",
                "transition naturelle vers le premier grand thème de la journée",
                "objectif de cette première partie",
                "plan oral en axes avant tout exemple",
            ]
            forced_opening_avoid = [
                "refaire la présentation annuelle complète",
                "démarrer directement par un exemple",
                "storytelling avant carte mentale",
                "mot bloc devant les élèves",
                "dire ce cours ou tout premier cours devant les élèves",
                "mentionner trois quarts d'heure ou une durée",
            ]
        else:
            forced_opening_include = [
                "petite reprise naturelle cohérente avec un vocal précédent indiquant que la pause ou le Q/R est terminé",
                "rappel bref de la partie précédente",
                "lien avec le nouveau thème",
                "thème de cette nouvelle partie",
                "objectif de cette partie",
                "plan oral en axes avant tout exemple",
            ]
            forced_opening_avoid = [
                "continuer le cours précédent",
                "double introduction",
                "exemple avant le plan",
                "mot bloc devant les élèves",
                "dire ce cours ou cours actuel devant les élèves",
                "mentionner trois quarts d'heure ou une durée",
            ]
        opening["must_include"] = _merge_unique_strings(opening.get("must_include"), forced_opening_include)
        opening["must_avoid"] = _merge_unique_strings(opening.get("must_avoid"), forced_opening_avoid)
        opening["teaching_beats"] = _merge_opening_teaching_beats(
            _opening_structure_teaching_beats(
                course_number=course_number,
                day_number=day_number,
                job=job,
                sub_parts=sub_parts,
                is_first_day=bool(day_number == 1),
            ),
            opening.get("teaching_beats") if isinstance(opening.get("teaching_beats"), list) else [],
        )

        parts = []
        for idx in range(parts_count):
            raw_part = raw_parts[idx] if idx < len(raw_parts) and isinstance(raw_parts[idx], dict) else {}
            forced_part_avoid = [
                "refaire l'accueil ou l'introduction",
                "réannoncer les thèmes de la journée",
                "réannoncer le programme annuel",
                "répéter l'objectif global ou le plan complet",
                "mentionner les horaires, créneaux, durées ou le planning",
            ]
            if idx == 0:
                forced_part_avoid.extend([
                    "commencer par le cadrage général de la journée",
                    "dire maintenant que le cadre général est posé",
                    "dire on peut entrer dans le premier grand thème",
                ])
            parts.append({
                "part_number": idx + 1,
                "title": (raw_part.get("title") or f"Partie {idx + 1}").strip(),
                "target_words": budgets["parts"][idx],
                "function": (raw_part.get("function") or "Développer une idée pédagogique identifiable.").strip(),
                "must_include": raw_part.get("must_include") if isinstance(raw_part.get("must_include"), list) else [],
                "must_avoid": _merge_unique_strings(
                    raw_part.get("must_avoid") if isinstance(raw_part.get("must_avoid"), list) else [],
                    forced_part_avoid,
                ),
                "teaching_beats": _normalize_teaching_beats(
                    raw_part,
                    course_number=course_number,
                    part_number=idx + 1,
                ),
                "transition_in": (raw_part.get("transition_in") or "").strip(),
                "transition_out": (raw_part.get("transition_out") or "").strip(),
            })

        course_conclusion = raw.get("course_conclusion") if isinstance(raw.get("course_conclusion"), dict) else {}
        course_conclusion["target_words"] = budgets["course_conclusion"]
        if course_number == 7:
            course_conclusion["must_include"] = _merge_unique_strings(
                course_conclusion.get("must_include"),
                ["récapitulatif de la partie", "utilité concrète des points vus"],
            )
            course_conclusion["must_avoid"] = _merge_unique_strings(
                course_conclusion.get("must_avoid"),
                ["annonce Q/R avant la conclusion globale", "transition vers un nouveau développement"],
            )
        else:
            course_conclusion["must_include"] = _merge_unique_strings(
                course_conclusion.get("must_include"),
                ["récapitulatif de la partie", "utilité concrète", "annonce Q/R dans le tchat"],
            )
            course_conclusion["must_avoid"] = _merge_unique_strings(
                course_conclusion.get("must_avoid"),
                ["nouveau développement après annonce Q/R", "transition vers le cours suivant"],
            )

        day_conclusion = None
        if course_number == 7:
            raw_day = raw.get("day_conclusion") if isinstance(raw.get("day_conclusion"), dict) else {}
            day_conclusion = {
                "target_words": budgets["day_conclusion"],
                "must_include": _merge_unique_strings(
                    raw_day.get("must_include"),
                    "récapitulatif global de la journée",
                    "amorce légère de la prochaine séance" if not is_last_day else "clôture finale de formation",
                    "bonne semaine et à la semaine prochaine" if not is_last_day else "bonne continuation",
                    "vous pouvez encore poser vos questions dans le tchat si vous voulez",
                ),
                "must_avoid": _merge_unique_strings(
                    raw_day.get("must_avoid"),
                    ["nouveau développement", "mot bloc devant les élèves"],
                ),
            }

        courses.append({
            "course_number": course_number,
            "course_title": title,
            "filename": budget_block.get("filename") or _course_filename_for_bloc(playlist_items, course_number),
            "duration_minutes": budget_block.get("duration_min") or round(_course_duration_for_bloc(playlist_items, course_number) / 60, 1),
            "target_words": target_words,
            "pedagogical_role": (raw.get("pedagogical_role") or _course_block_role(
                course_number,
                folder_position=job.get("folder_position"),
                next_item=("qa", 0, "qa", course_number),
            )).strip(),
            "course_kind": _structured_course_kind(course_number),
            "opening": opening,
            "learning_objectives": raw.get("learning_objectives") if isinstance(raw.get("learning_objectives"), list) else [],
            "parts": parts,
            "course_conclusion": course_conclusion,
            "day_conclusion": day_conclusion,
            "global_constraints": {
                "parts_min": 2,
                "parts_max": 4,
                "learner_facing_forbidden_words": ["bloc", "créneau", "horaire", "planning"],
                "learner_facing_preferred_units": ["thème", "partie", "chapitre", "séquence", "axe"],
                "learner_facing_internal_course_policy": (
                    "Le mot course/cours désigne une unité interne. Dans le texte "
                    "apprenant, préférer thème, partie, chapitre, séquence ou axe."
                ),
                "examples_policy": (
                    "Les exemples non sourcés doivent être fictifs ou hypothétiques "
                    "avec une formulation naturelle. 'Imaginons...' ou 'Supposons que...' "
                    "suffit quand l'hypothèse est claire."
                ),
                "schedule_policy": (
                    "Les horaires, durées et créneaux sont internes. Le formateur "
                    "présente la progression pédagogique sans les mentionner."
                ),
            },
        })

    return {
        "version": "structured-course-plan-v2",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "title": job.get("program_title") or "",
        "folder_id": job.get("folder_id"),
        "day_number": day_number,
        "nb_days": nb_days,
        "is_last_day": is_last_day,
        "courses": courses,
    }


def _build_structured_course_plan_prompt(job: dict, playlist_items: list, sub_parts: list, module_contents: dict) -> str:
    prompt_parts = load_planning_prompt_parts()
    base_style = prompt_parts["base_style"]
    plan_contract = prompt_parts["plan_contract"]
    slide_template_catalog = _slide_template_catalog_prompt()
    block_plan = _course_audio_block_plan(playlist_items, folder_position=job.get("folder_position"))
    try:
        day_number = int(job.get("folder_position") or 0) + 1
    except Exception:
        day_number = None
    try:
        nb_days = int(job.get("nb_days") or 0) or None
    except Exception:
        nb_days = None
    is_first_day = day_number == 1
    is_last_day = bool(nb_days and day_number == nb_days)
    block_lines = "\n".join(
        f"- Cours {b['bloc_number']} · {b['duration_min']} min · cible {b['target_words']} mots · {b['role']}"
        for b in block_plan
    )
    sub_part_lines = "\n".join(
        f"- Cours {i + 1}: {_strip_internal_schedule_from_label(name)}"
        for i, name in enumerate(sub_parts or [])
    )
    module_summary = "\n\n".join(
        f"## {_strip_internal_schedule_from_label(name)}\n{_compact_words(text, 650)}"
        for name, text in (module_contents or {}).items()
        if (text or "").strip()
    )
    return f"""Tu es ingénieur pédagogique. Tu dois produire le PLAN JSON STRICT de 7 cours audio d'une journée.

SOCLE GÉNÉRAL À RESPECTER :
{base_style}

CONTRAT DE PLANIFICATION :
{plan_contract}

Le plan est libre maintenant, mais il sera verrouillé ensuite : le texte final devra suivre ce plan.

Contraintes générales :
- Chaque cours a 2 à 4 parties, jamais moins, jamais plus.
- Dans ce JSON, "cours" est une unité interne. Devant les élèves, présente ces unités comme des grands thèmes, parties, chapitres ou séquences de journée.
- Devant les élèves, ne jamais utiliser les mots "bloc", "créneau", "horaire" ou "planning" : utiliser "thème", "partie", "chapitre", "séquence", "axe", "moment" ou parler simplement de progression.
- Évite aussi côté apprenant : "tout premier cours", "ce cours", "cours actuel", "le cours qui nous occupe", "pour les trois quarts d'heure à venir".
- Les durées, horaires, budgets mots, noms de fichiers et découpages playlist sont internes. Ils ne doivent jamais apparaître dans les titres, ouvertures, transitions ou conclusions côté apprenant.
- Ne jamais écrire une phrase du type "sans vous soucier des horaires précis" : si tu présentes la journée, énonce seulement les thèmes dans leur ordre pédagogique.
- Un cours est toujours suivi d'un temps de questions-réponses dans le tchat.
- Cours interne 1 de la première journée seulement : accueil, parcours annuel synthétique, thèmes de la journée, transition vers le premier grand thème, objectif/axes, conclusion + Q/R.
- Cours interne 1 d'une journée suivante : accueil de journée, reprise douce de la progression, thèmes de la journée, transition vers le premier grand thème, objectif/axes, conclusion + Q/R. Ne refais pas la présentation annuelle complète.
- Cours internes 2 à 6 : reprise naturelle cohérente avec le vocal précédent de fin de pause/Q/R, rappel bref de la partie précédente, lien avec le nouveau thème, objectif/axes, conclusion + Q/R.
- Cours interne 7 : conclusion de la dernière partie, conclusion globale de journée, amorce prochaine séance, bonne semaine/à la semaine prochaine, puis mention douce du tchat.
- Si c'est la dernière journée de formation, le cours 7 doit souhaiter bonne continuation au lieu d'annoncer la prochaine séance.
- Les exemples non sourcés doivent être fictifs ou hypothétiques avec une
  formulation naturelle. "Imaginons...", "Imaginez qu'un client...",
  "Prenons un exemple fictif..." ou "Supposons que..." suffit.
- Pour chaque partie de développement, crée des `teaching_beats` : 2 à 4 moments pédagogiques structurants qui guideront le texte.
- Chaque teaching beat doit avoir : beat_id, type, role, spoken_requirement, slide_anchor.
- Dans `opening` du cours interne 1, prévois explicitement les moments structurels d'accueil et d'annonce du programme du jour : ils correspondent aux templates `welcome` et `day_program`.
- Un slide_anchor n'est activé que si le moment mérite vraiment une visualisation. N'active pas une slide pour une simple transition orale.
- Le texte final ne doit jamais dire "slide", "PowerPoint", "template", "anchor" ou "teaching beat". Ces anchors sont internes.
- Choisis les templates uniquement dans le catalogue fourni. Ne force pas une roue, une checklist ou des étapes si le contenu ne s'y prête pas.

Position dans la formation :
- Journée courante : {day_number or "inconnue"}
- Nombre total de journées : {nb_days or "inconnu"}
- Première journée : {"oui" if is_first_day else "non"}
- Dernière journée : {"oui" if is_last_day else "non"}

Budget audio par cours :
{block_lines}

Cours détectés, libellés nettoyés des horaires internes :
{sub_part_lines}

Titre professionnel :
{job.get('program_title') or ''}

Intitulé journée :
{job.get('folder_name') or ''}

Programme source :
{_compact_words(job.get('program_text') or '', 3500)}

Contenus module disponibles :
{module_summary or '(aucun contenu module dédié)'}

Catalogue interne des templates de slides :
{slide_template_catalog}

Réponds UNIQUEMENT en JSON valide :
{{
  "courses": [
    {{
      "course_number": 1,
      "course_title": "...",
      "pedagogical_role": "...",
      "opening": {{"type": "...", "must_include": [], "must_avoid": [], "teaching_beats": []}},
      "learning_objectives": ["..."],
      "parts": [
        {{
          "part_number": 1,
          "title": "...",
          "function": "...",
          "must_include": [],
          "must_avoid": [],
          "teaching_beats": [
            {{
              "beat_id": "c1p1b1",
              "type": "concept|definition|process|method|example|comparison|warning|tip|story|analogy|data|recap|opinion",
              "role": "fonction pédagogique du moment",
              "spoken_requirement": "ce que le texte oral devra couvrir naturellement",
              "slide_anchor": {{
                "enabled": true,
                "template_type": "welcome|day_program|reflection|casestudy|facilitator|stats|story|recap|analogy|warning|tip|opinion|transition|chart",
                "visual_goal": "ce que la slide doit aider à retenir",
                "items_expected": null,
                "fields_hint": {{}}
              }}
            }}
          ],
          "transition_in": "...",
          "transition_out": "..."
        }}
      ],
      "course_conclusion": {{"must_include": [], "must_avoid": []}},
      "day_conclusion": null
    }}
  ]
}}"""


def _generate_structured_course_plan(job: dict, playlist_items: list, sub_parts: list, module_contents: dict, model=None) -> dict:
    prompt = _build_structured_course_plan_prompt(job, playlist_items, sub_parts, module_contents)
    for attempt in range(3):
        try:
            raw = _anthropic_post(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=9000,
                model=model,
            )
            return _normalize_structured_course_plans(
                _parse_structured_course_plan(raw),
                job=job,
                playlist_items=playlist_items,
                sub_parts=sub_parts,
            )
        except Exception as e:
            logger.warning("⚠️ Plan structuré tentative %s/3 échouée : %s", attempt + 1, str(e)[:300])
            if attempt == 2:
                raise
    raise ValueError("Plan structuré impossible")


def _section_label(section: dict) -> str:
    kind = section.get("kind")
    if kind == "opening":
        return "introduction"
    if kind == "course_calibrated":
        return "cours complet calibré"
    if kind == "course_conclusion":
        return "conclusion du cours"
    if kind == "day_conclusion":
        return "conclusion globale de la journée"
    return f"partie {section.get('part_number')}"


def _structured_sections_for_course(course_plan: dict) -> list[dict]:
    sections = [{"kind": "opening", **(course_plan.get("opening") or {})}]
    for part in course_plan.get("parts") or []:
        sections.append({"kind": "part", **part})
    sections.append({"kind": "course_conclusion", **(course_plan.get("course_conclusion") or {})})
    if course_plan.get("day_conclusion"):
        sections.append({"kind": "day_conclusion", **course_plan["day_conclusion"]})
    return sections


def _section_artifact_metadata(section: dict) -> dict:
    teaching_beats = section.get("teaching_beats") if isinstance(section.get("teaching_beats"), list) else []
    slide_anchors = []
    for beat in teaching_beats:
        anchor = beat.get("slide_anchor") if isinstance(beat, dict) else None
        if not isinstance(anchor, dict) or not anchor.get("enabled"):
            continue
        slide_anchors.append({
            "beat_id": beat.get("beat_id"),
            "type": beat.get("type"),
            "role": beat.get("role"),
            "spoken_requirement": beat.get("spoken_requirement"),
            "slide_anchor": anchor,
            "text_anchor_scope": "section",
        })
    return {
        "must_include": section.get("must_include") if isinstance(section.get("must_include"), list) else [],
        "must_avoid": section.get("must_avoid") if isinstance(section.get("must_avoid"), list) else [],
        "teaching_beats": teaching_beats,
        "slide_anchors": slide_anchors,
    }


def _block_min_words(word_budget: int) -> int:
    ratio = _env_float("FORMATION_TTS_BLOCK_WORD_MIN_RATIO", 0.97, min_value=0.80, max_value=1.0)
    return max(0, int(int(word_budget or 0) * ratio))


def _structured_course_min_words(word_budget: int) -> int:
    ratio = _env_float("FORMATION_STRUCTURED_COURSE_MIN_RATIO", 0.95, min_value=0.90, max_value=1.0)
    return max(0, int(int(word_budget or 0) * ratio))


def _structured_section_min_words(word_budget: int) -> int:
    ratio = _env_float("FORMATION_STRUCTURED_SECTION_MIN_RATIO", 0.94, min_value=0.90, max_value=1.0)
    return max(0, int(int(word_budget or 0) * ratio))


def _course_audio_block_plan(playlist_spec=None, *, folder_position=None) -> list[dict]:
    if playlist_spec is None:
        from services.playlist_tts_service import PLAYLIST_SPEC as playlist_spec
    api_speed = _course_tts_speed()
    blocks = []
    for idx, item in enumerate(playlist_spec):
        filename, duration_sec, file_type, bloc_num = item
        if file_type != "cours":
            continue
        target_sec = int(duration_sec or 0)
        word_budget = _estimated_words_budget_for_course(target_sec, api_speed, bloc_num)
        min_words = _block_min_words(word_budget)
        next_item = _next_playlist_item_after_index(playlist_spec, idx)
        blocks.append({
            "bloc_number": int(bloc_num or 0),
            "filename": filename,
            "duration_sec": target_sec,
            "duration_min": round(target_sec / 60, 1),
            "min_words": min_words,
            "target_words": word_budget,
            "max_words": word_budget,
            "role": _course_block_role(int(bloc_num or 0), folder_position=folder_position, next_item=next_item),
            "next_item_type": next_item[2] if next_item and len(next_item) >= 3 else None,
        })
    return blocks


def _build_audio_day_plan_context(generation_context=None) -> str:
    """Injecte la direction artistique par blocs playlist dans le prompt initial."""
    folder_position = (generation_context or {}).get("folder_position")
    blocks = _course_audio_block_plan(folder_position=folder_position)
    lines = [
        "═══════════════════════════════════════════════════════════════════",
        "DIRECTION ARTISTIQUE AUDIO — STRUCTURE INTERNE PLAYLIST",
        "═══════════════════════════════════════════════════════════════════",
        "Le texte final sera lu en plusieurs fichiers cours selon la playlist réelle.",
        "Écris donc une journée vécue, fluide, avec des paragraphes qui peuvent se",
        "répartir naturellement dans les cours internes ci-dessous. Ne mets pas de marqueurs",
        "techniques dans ta réponse : le système s'en charge.",
        "Ces durées, budgets et découpages sont invisibles pour les apprenants :",
        "ne les verbalise jamais, même pour dire qu'ils ne sont pas importants.",
        "",
    ]
    for block in blocks:
        lines.append(
            f"- Cours interne {block['bloc_number']} · {block['duration_min']} min · "
            f"budget parole {block['min_words']}–{block['max_words']} mots : {block['role']}"
        )
    lines.extend([
        "",
        "Règles impératives :",
        "- La première partie ne démarre jamais brutalement.",
        "- Chaque partie se ferme proprement : mini-synthèse, transition, ou annonce pause/Q&A si nécessaire.",
        "- Si un Q&A ou une pause suit, son introduction est portée par l'outro du cours précédent.",
        "- Les Q&A et pauses ne comptent pas dans le texte de cours.",
        "- Les références entre cours restent vagues : jamais \"hier\" ni \"demain\".",
        "- Ne jamais dire \"horaire\", \"créneau\", \"planning\" ou \"sans vous soucier des horaires\".",
    ])
    return "\n".join(lines)


def _build_course_slot_generation_context(
    generation_context=None,
    *,
    sub_part_name: str = "",
    module_content: str = "",
    program_text: str = "",
) -> str:
    """Ajoute le cadrage précis du créneau courant au prompt de génération."""
    block = _course_block_for_generation_context(generation_context)
    if not block:
        return ""

    slot_label = (
        f"Cours interne {block['bloc_number']} · {block['filename']} · "
        f"{block['duration_min']} min"
    )
    slot_profile = _course_slot_prompt_profile(
        block.get("bloc_number"),
        (generation_context or {}).get("passe"),
    )
    return f"""
═══════════════════════════════════════════════════════════════════
CADRAGE INTERNE DU COURS COURANT — À RESPECTER STRICTEMENT
═══════════════════════════════════════════════════════════════════
Tu écris uniquement cette unité interne : {slot_label}.
Thème pédagogique : {_strip_internal_schedule_from_label(sub_part_name)}
Rôle oral de cette partie : {block.get('role') or 'continuité pédagogique'}

Attention : le libellé, la durée, le fichier, le budget et la position dans la
playlist sont des données internes. Les apprenants ne doivent jamais entendre
"horaire", "créneau", "planning", une heure précise ou une durée de fichier.

Profil éditorial propre à cette partie :
{slot_profile or '(profil spécifique indisponible)'}

Contenu prioritaire à développer dans CETTE PARTIE :
{(module_content or '').strip()[:7000] or '(contenu spécifique non fourni)'}

Contexte journée complet, seulement pour éviter les doublons et assurer la continuité :
{(program_text or '').strip()[:9000] or '(contexte journée non fourni)'}

Règles de périmètre :
- Ne traite pas les autres cours comme s'ils appartenaient à celui-ci.
- Ne recommence pas toute la journée à chaque passe.
- Si une notion appartient plutôt à une autre partie, garde-la en transition courte.
- La fin de la partie doit être propre : synthèse, chute ou transition naturelle.
"""


def compute_course_day_word_budget_audit(folder_id: int, job: dict | None = None) -> dict:
    """Audit final du nombre de mots réellement parlés pour une journée."""
    job = job or get_job_from_db(folder_id)
    budget = get_course_day_word_budget()
    if not job:
        return {
            "ok": False,
            "status": "content_job_missing",
            "folder_id": folder_id,
            "reason": "content_job_missing",
            "budget": budget,
            "spoken_words": 0,
            "raw_words": 0,
            "deficit": budget["min_words"],
            "overflow": 0,
        }

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COALESCE(text_content, ''), COALESCE(word_count, 0)
        FROM content_generation_segments
        WHERE job_id = ? AND status = 'completed'
        ORDER BY sub_part_index ASC, passe ASC
        """,
        (job["id"],),
    )
    rows = cursor.fetchall()
    conn.close()

    raw_words = 0
    spoken_words = 0
    for row in rows:
        if len(row) >= 4 and not isinstance(row[0], str):
            text, wc = row[2], row[3]
        else:
            text, wc = row[0], row[1]
        raw_words += int(wc or len((text or "").split()))
        spoken_words += count_tts_spoken_words(text)

    carryover_in = (job.get("carryover_in_text") or "").strip()
    if carryover_in:
        raw_words += len(carryover_in.split())
        spoken_words += count_tts_spoken_words(carryover_in)

    deficit = max(0, int(budget["min_words"]) - spoken_words)
    overflow = max(0, spoken_words - int(budget["max_words"]))
    status = "ok"
    if deficit:
        status = "under_budget"
    elif overflow:
        status = "over_budget"

    return {
        "ok": status == "ok",
        "status": status,
        "folder_id": folder_id,
        "content_job_id": job["id"],
        "budget": budget,
        "spoken_words": int(spoken_words),
        "raw_words": int(raw_words),
        "deficit": int(deficit),
        "overflow": int(overflow),
        "segments_count": len(rows),
        "includes_carryover_in": bool(carryover_in),
    }


def assert_course_day_word_budget(folder_id: int, *, context: str = "") -> dict:
    """Bloque la pipeline si le texte final n'est pas dans le budget audio."""
    audit = compute_course_day_word_budget_audit(folder_id)
    if audit.get("ok"):
        logger.info(
            "PIPELINE_DAY_WORD_BUDGET_OK folder_id=%s context=%s spoken=%s target=%s range=%s-%s",
            folder_id,
            context,
            audit["spoken_words"],
            audit["budget"]["target_words"],
            audit["budget"]["min_words"],
            audit["budget"]["max_words"],
        )
        return audit

    budget = audit["budget"]
    if audit["status"] == "under_budget":
        detail = f"manque {audit['deficit']} mots"
    elif audit["status"] == "over_budget":
        detail = f"dépasse de {audit['overflow']} mots"
    else:
        detail = audit.get("reason") or audit["status"]
    raise ValueError(
        "Budget mots journée invalide "
        f"({context or 'pipeline'}): {audit['spoken_words']} mots parlés, "
        f"cible {budget['target_words']} mots, plage autorisée "
        f"{budget['min_words']}–{budget['max_words']} mots, {detail}. "
        "Corrige le texte avant Word 2 / audio pour préserver le calcul au mot près."
    )


def _estimated_audio_seconds_for_words(word_count, api_speed):
    """Durée audio estimée pour un nombre de mots à une vitesse Fish Audio donnée.

    Inclut le silence de début (`_COURSE_START_SILENCE_SECONDS`) qui est ajouté en
    aval par le pipeline TTS. Approximation linéaire — calibration à valider en prod
    (cf. `memoire/02-problemes/pipeline-52-jours-risques-residuels.md`, R1).
    """
    if word_count <= 0:
        return _COURSE_START_SILENCE_SECONDS
    estimated_wpm = _course_words_per_minute()
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
    try:
        one_sec_duration = _mp3_duration_seconds_no_ffprobe(one_sec)
    except Exception:
        one_sec_duration = 1.0
    repeat = max(1, int(round(duration_sec / one_sec_duration)))
    if repeat == 1:
        return one_sec, one_sec_duration
    from services.basic_tts_service import concat_mp3_bytes
    return concat_mp3_bytes([one_sec] * repeat), one_sec_duration * repeat


def _pad_course_mp3_to_duration_no_ffprobe(
    audio_bytes: bytes,
    voice_duration_sec: float,
    target_duration_sec: int | float,
) -> tuple[bytes, float]:
    """Pad course MP3 without pydub/ffprobe by concatenating MP3 frame streams."""
    from services.basic_tts_service import concat_mp3_bytes

    target_duration_sec = float(target_duration_sec or 0)
    voice_duration_sec = max(0.0, float(voice_duration_sec or 0.0))
    start_bytes, start_duration = _silent_mp3_approx_no_ffmpeg(_COURSE_START_SILENCE_SECONDS)
    end_duration_target = max(0.0, target_duration_sec - start_duration - voice_duration_sec)
    end_bytes, end_duration = _silent_mp3_approx_no_ffmpeg(end_duration_target)
    return concat_mp3_bytes([start_bytes, audio_bytes, end_bytes]), start_duration + voice_duration_sec + end_duration


def _edge_muted_padding_audio(duration_sec: float, on_progress=None) -> tuple[bytes, float]:
    """Return Edge-compatible muted padding for course MP3 concatenation."""
    if duration_sec <= 0:
        return b"", 0.0
    return _build_edge_muted_filler_audio(duration_sec, on_progress=on_progress)


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

# Edge TTS calibré à BASIC_TTS_SPEED=1.15 pour matcher Fish Audio (~166 wpm).
# Ensuite on recalcule un wpm réel observé pendant le run.
_BOOTSTRAP_WPM_EDGE_TTS = 166.0

# Tolérance d'arrondi sur la durée mesurée (frames MP3 = ~26 ms).
_TOLERANCE_OVERFLOW_SEC = 2.0
_UPLOAD_DURATION_TOLERANCE_SEC = 0.5

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


def _assert_audio_duration_within_slot(filename: str, duration_sec: float, target_sec: int) -> None:
    """Last safety gate before Azure upload: no generated MP3 may exceed its slot."""
    if not target_sec or duration_sec is None:
        return
    if float(duration_sec) > float(target_sec) + _UPLOAD_DURATION_TOLERANCE_SEC:
        raise ValueError(
            f"{filename} dépasse la durée autorisée "
            f"({float(duration_sec):.1f}s > {int(target_sec)}s). "
            "Audio non uploadé pour éviter un débord de playlist."
        )


def _assert_audio_duration_fills_slot(filename: str, duration_sec: float, target_sec: int) -> None:
    """Runtime-fit course files must include real browser-readable padding."""
    if not target_sec or duration_sec is None:
        return
    if float(duration_sec) < float(target_sec) - _TOLERANCE_OVERFLOW_SEC:
        raise ValueError(
            f"{filename} est trop court après padding "
            f"({float(duration_sec):.1f}s < {int(target_sec)}s). "
            "Audio non uploadé pour éviter une fin de créneau trop précoce."
        )


def _assert_course_voice_duration_within_deadline(
    filename: str,
    voice_duration_sec: float,
    target_sec: int,
    *,
    has_start_silence: bool,
) -> None:
    """Vérifie que la parole reste sous la marge finale configurée."""
    if not target_sec or voice_duration_sec is None:
        return
    final_silence_sec = _course_final_silence_sec()
    limit_sec = (
        _course_voice_window_sec(target_sec)
        if has_start_silence
        else _course_speech_deadline_sec(target_sec)
    )
    if float(voice_duration_sec) > float(limit_sec) + _TOLERANCE_OVERFLOW_SEC:
        raise ValueError(
            f"{filename} dépasse la limite de parole T-{final_silence_sec:.0f}s "
            f"({float(voice_duration_sec):.1f}s > {float(limit_sec):.1f}s). "
            "Audio non uploadé : il faut moins de mots pour garder la marge finale."
        )


def _runtime_conclusions_from_attempts(attempts: list) -> list:
    return [
        {
            "kind": a.get("kind"),
            "duration": a.get("duration"),
            "text": a.get("text") or "",
        }
        for a in (attempts or [])
        if a.get("kind") in {
            "conclusion",
            "conclusion_fallback",
            "conclusion_ultra_fallback",
        } and (a.get("text") or "").strip()
    ]


def _runtime_ai_decisions_from_attempts(attempts: list) -> list:
    return [
        {
            "kind": a.get("kind"),
            "chunk": a.get("chunk"),
            "remaining_sec": a.get("remaining_sec"),
            "words": a.get("words"),
            "reason": a.get("reason") or "",
            "text": a.get("text") or "",
            "original_start": a.get("original_start") or "",
        }
        for a in (attempts or [])
        if str(a.get("kind") or "").startswith("ai_")
    ]


def _actual_reading_from_attempts(attempts: list) -> dict | None:
    """Récupère les métriques Fish timestampées produites pendant le TTS."""
    actual_items = []
    for attempt in attempts or []:
        actual = attempt.get("actual_reading") if isinstance(attempt, dict) else None
        if isinstance(actual, dict) and actual.get("audio_duration_sec"):
            actual_items.append(actual)
    if not actual_items:
        return None
    if len(actual_items) == 1:
        return actual_items[0]

    input_words = sum(int(item.get("input_spoken_word_count") or 0) for item in actual_items)
    fish_words = sum(int(item.get("fish_segment_word_count") or 0) for item in actual_items)
    duration_sec = sum(float(item.get("audio_duration_sec") or 0.0) for item in actual_items)
    wpm = fish_words / (duration_sec / 60.0) if duration_sec > 0 and fish_words > 0 else 0.0
    timeline = []
    for item in actual_items:
        offset = float(item.get("audio_start_sec") or 0.0)
        for segment in item.get("timeline") or []:
            clone = dict(segment)
            clone["start"] = round(float(clone.get("start") or 0.0) + offset, 3)
            clone["end"] = round(float(clone.get("end") or 0.0) + offset, 3)
            timeline.append(clone)
    return {
        "provider": actual_items[0].get("provider") or "fish_audio",
        "endpoint": actual_items[0].get("endpoint") or "",
        "model": actual_items[0].get("model") or "",
        "format": actual_items[0].get("format") or "",
        "speed": actual_items[0].get("speed"),
        "audio_duration_sec": round(duration_sec, 3),
        "input_spoken_word_count": input_words,
        "fish_segment_word_count": fish_words,
        "words_per_minute": round(wpm, 3),
        "words_per_hour": round(wpm * 60.0, 1) if wpm else 0.0,
        "text_read": " ".join((item.get("text_read") or "").strip() for item in actual_items if (item.get("text_read") or "").strip()),
        "timeline": timeline,
        "chunks": [
            chunk
            for item in actual_items
            for chunk in (item.get("chunks") or [])
        ],
    }


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


def _escape_control_chars_in_strings(text: str) -> str:
    """Échappe les caractères de contrôle littéraux à l'intérieur des strings JSON.

    DeepSeek génère parfois des \\n/\\t/\\r littéraux dans les valeurs string,
    ce qui produit un JSONDecodeError 'Expecting , delimiter'.
    """
    result = []
    in_string = False
    escaped = False
    for ch in text:
        if escaped:
            result.append(ch)
            escaped = False
        elif ch == "\\" and in_string:
            result.append(ch)
            escaped = True
        elif ch == '"':
            result.append(ch)
            in_string = not in_string
        elif in_string and ch in "\n\r\t":
            if ch == "\n":
                result.append("\\n")
            elif ch == "\r":
                result.append("\\r")
            else:
                result.append("\\t")
        else:
            result.append(ch)
    return "".join(result)


def _extract_llm_json(raw: str) -> dict:
    raw = (raw or "").strip().replace("```json", "```")
    if "```" in raw:
        raw = max(raw.split("```"), key=len).strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        raw = match.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        sanitized = _escape_control_chars_in_strings(raw)
        try:
            return json.loads(sanitized)
        except json.JSONDecodeError:
            try:
                from json_repair import repair_json
                return json.loads(repair_json(raw))
            except Exception as e:
                raise ValueError(f"JSON LLM invalide après réparation : {e}")


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


def _playlist_item_type(item) -> str | None:
    try:
        return item[2]
    except Exception:
        return None


def _playlist_item_duration(item) -> int:
    try:
        return int(item[1] or 0)
    except Exception:
        return 0


def _next_playlist_item_after(playlist_items: list | None, item_idx: int):
    if not playlist_items or item_idx + 1 >= len(playlist_items):
        return None
    return playlist_items[item_idx + 1]


def _break_intro_text_for_playlist_item(item) -> str:
    """Retourne l'intro prévue du break, à porter par l'audio précédent."""
    next_type = _playlist_item_type(item)
    if next_type not in {"qa", "pause", "pause_midi"}:
        return ""
    try:
        from services.playlist_tts_service import (
            _get_pause_midi_text,
            _get_pause_text,
            _get_qa_text,
        )
        bloc_num = int(item[3] or 1)
        if next_type == "qa":
            intro, _outro = _get_qa_text(bloc_num)
        elif next_type == "pause_midi":
            intro, _outro = _get_pause_midi_text()
        else:
            intro, _outro = _get_pause_text(bloc_num)
        return re.sub(r"\s+", " ", (intro or "").strip())
    except Exception:
        return ""


def _course_playlist_handoff_text(next_item) -> str:
    """Phrase de transition portée par le fichier qui se termine."""
    next_type = _playlist_item_type(next_item)
    duration_sec = _playlist_item_duration(next_item)
    planned_intro = _break_intro_text_for_playlist_item(next_item)
    if planned_intro:
        return planned_intro
    if next_type in {"qa", "pause", "pause_midi"}:
        try:
            from services.break_transition_service import duration_label
            label = duration_label(duration_sec, next_type)
        except Exception:
            label = ""
        if next_type == "qa":
            return (
                "On va maintenant prendre un temps pour vos questions. "
                "Gardez simplement les points importants en tête, et posez ce que vous voulez clarifier."
            )
        if next_type == "pause_midi" or label == "pause déjeuner":
            return (
                "On va maintenant marquer la pause déjeuner. "
                "Prenez le temps de souffler, de vous reposer, et on reprendra ensuite calmement."
            )
        if label:
            return (
                f"On va maintenant prendre une pause de {label}. "
                "Profitez-en pour souffler un peu avant la suite."
            )
        return (
            "On va maintenant prendre une courte pause. "
            "Profitez-en pour souffler un peu avant la suite."
        )
    if next_type == "cours":
        return "On enchaînera ensuite avec la suite du parcours, en gardant cette base comme point d'appui."
    return "On va donc s'arrêter ici pour ce moment, avec ces repères bien en tête."


def _build_runtime_conclusion_text(
    consumed_chunks: list,
    remaining_sec: float,
    bloc_number: int,
    next_playlist_item=None,
) -> str:
    """Conclusion humaine basée sur le contenu réellement enseigné dans le bloc."""
    consumed_text = "\n\n".join(
        (c.get("text") or "").strip()
        for c in (consumed_chunks or [])
        if (c.get("text") or "").strip()
    )
    anchors = _pick_conclusion_anchors(consumed_text, max_anchors=6)
    target_words = int(
        max(
            160,
            min(
                650,
                (max(45.0, remaining_sec) / 60.0) * _course_words_per_minute() * 0.92,
            ),
        )
    )

    lines = [
        "[calm] Avant de s'arrêter, on prend vraiment le temps de refermer cette partie proprement. [pause]",
        "Le cours a été dense, donc l'objectif n'est pas de rajouter une nouvelle idée. On va plutôt remettre en ordre ce qui vient d'être travaillé, tranquillement, pour que ce soit plus facile à réutiliser.",
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
        "À ce stade, ce qui compte, c'est de ne pas retenir ces points comme une liste isolée. [pause] Il faut les relier entre eux : chaque notion prépare la suivante, et c'est cette continuité qui permet de mieux agir dans une situation réelle.",
        "Si vous deviez retenir une méthode simple, ce serait celle-ci : observer d'abord, nommer clairement ce qui se passe, choisir une réponse adaptée, puis vérifier que cette réponse produit bien l'effet recherché.",
        "On va donc s'arrêter ici sur cette base. [pause] Dans la suite, on pourra reprendre ce fil sans repartir de zéro : les repères sont posés, le vocabulaire est en place, et on pourra aller plus loin dans l'application.",
        _course_playlist_handoff_text(next_playlist_item),
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
    next_playlist_item=None,
):
    """Generate one course MP3 by slide-sized chunks and return slide timings.

    Mode `runtime_fit=True` (Edge TTS uniquement) :
        - Mesure la durée Edge TTS réelle de chaque chunk via
          `_mp3_duration_seconds_no_ffprobe`, et calcule un `observed_wpm`
          à mesure (bootstrap _BOOTSTRAP_WPM_EDGE_TTS).
        - Sub-chunke adaptativement (paliers 600/300/150 mots) selon la
          marge restante avant la deadline parole (`target_sec - marge parole finale`).
        - Stoppe la génération avant dépassement et retourne les chunks non
          générés via `unconsumed_chunks`.
        - Par défaut, ces chunks ne sont PAS préfixés au cours suivant :
          chaque cours doit rester autonome. Le report intra-jour n'est actif
          que si `FORMATION_RUNTIME_INTRA_DAY_CARRYOVER=1`.
        - Si `prepended_chunks` est explicitement fourni, il est préfixé en
          tête de la file avec une amorce IA.
        - N'ajoute plus de conclusion runtime : la fin du cours appartient au
          texte calibré en amont, puis à la conformité locale.

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
    from services.tts_service import convert_to_speech, convert_to_speech_with_timestamps

    target_sec = int(bloc["target_sec"])
    final_silence_sec = _course_final_silence_sec()
    speech_deadline_sec = _course_speech_deadline_sec(target_sec)
    api_speed = _course_tts_speed()
    word_count = bloc.get("word_count") or len((bloc.get("text") or "").split())
    word_budget = _estimated_words_budget_for_course(
        target_sec,
        api_speed,
        bloc.get("bloc_number"),
    )

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

    # Le bloc audio est déjà généré/calibré avec sa conclusion. Runtime fit ne
    # réserve donc plus de marge pour fabriquer une conclusion après coup.
    main_speech_deadline_sec = speech_deadline_sec
    main_speech_deadline_sec = max(0.0, main_speech_deadline_sec)

    def _emit(message: str):
        if progress_callback:
            progress_callback(message)

    # Préfixer le carryover intra-jour uniquement en runtime_fit. Si du texte a
    # été reporté du cours précédent, on l'amorce et on reformule son début avant
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
            remaining_sec = main_speech_deadline_sec - cursor_sec
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
                    > main_speech_deadline_sec + _TOLERANCE_OVERFLOW_SEC):
                smaller_max_words = _smaller_runtime_fit_word_limit(
                    chunk,
                    available_sec=main_speech_deadline_sec - cursor_sec,
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
            chunk_actual_reading = None
            if _fish_timestamp_alignment_enabled():
                audio_bytes, timestamp_meta = convert_to_speech_with_timestamps(
                    text,
                    speed=api_speed,
                    format="mp3",
                )
                chunk_actual_reading = _fish_actual_reading_summary(timestamp_meta, input_text=text)
            else:
                audio_bytes = convert_to_speech(text, speed=api_speed)
            segment = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
            mode = (
                f"fish_audio_timestamped_speed={api_speed}"
                if chunk_actual_reading
                else f"fish_audio_speed={api_speed}"
            )

        if not basic_tts:
            duration_sec = len(segment) / 1000

        if (
            use_runtime_fit
            and cursor_sec + duration_sec
            > main_speech_deadline_sec + _TOLERANCE_OVERFLOW_SEC
        ):
            chunk_words = len(text.split())
            measured_wpm = chunk_words * 60.0 / duration_sec if duration_sec > 0 else 0.0
            smaller_max_words = _smaller_runtime_fit_word_limit(
                chunk,
                available_sec=main_speech_deadline_sec - cursor_sec,
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
                "limit_sec": main_speech_deadline_sec,
                "final_silence_sec": final_silence_sec,
            })
            _emit(
                f"Bloc {bloc['bloc_number']}/7 — slide audio {chunk_idx + 1}/{len(chunks)} "
                f"reportée ({duration_sec:.1f}s dépasserait la marge T-{final_silence_sec:.0f}s)"
            )
            break

        if (
            not mock
            and not use_runtime_fit
            and cursor_sec + duration_sec > speech_deadline_sec + _TOLERANCE_OVERFLOW_SEC
        ):
            attempts.append({
                "kind": f"{mode}_rejected_speech_deadline",
                "chunk": chunk_idx + 1,
                "duration": duration_sec,
                "words": len(text.split()),
                "limit_sec": speech_deadline_sec,
                "final_silence_sec": final_silence_sec,
            })
            raise ValueError(
                f"Bloc {bloc['bloc_number']} sync trop long : la parole finirait à "
                f"{cursor_sec + duration_sec:.1f}s, après la limite T-{final_silence_sec:.0f}s "
                f"({speech_deadline_sec:.1f}s). Audio non uploadé."
            )

        start_sec = cursor_sec
        end_sec = start_sec + duration_sec
        if basic_tts:
            audio_parts.append(audio_bytes)
        else:
            full_audio += segment
        cursor_sec = end_sec
        attempt_record = {"kind": mode, "chunk": chunk_idx + 1, "duration": duration_sec}
        if not basic_tts and not mock and "chunk_actual_reading" in locals() and chunk_actual_reading:
            chunk_actual_reading = dict(chunk_actual_reading)
            chunk_actual_reading["audio_start_sec"] = round(start_sec, 3)
            chunk_actual_reading["audio_end_sec"] = round(end_sec, 3)
            attempt_record["actual_reading"] = chunk_actual_reading
        attempts.append(attempt_record)
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

    # ── Assemblage final ────────────────────────────────────────────────────
    if basic_tts:
        if use_runtime_fit and stopped_for_runtime_fit and not audio_parts:
            raise ValueError(
                f"Bloc {bloc['bloc_number']} runtime fit : aucun audio généré "
                "avant le report du texte."
            )
        voice_stop_duration = cursor_sec
        if target_sec > voice_stop_duration:
            if use_runtime_fit:
                silence_bytes, silence_duration = _edge_muted_padding_audio(
                    target_sec - voice_stop_duration,
                    on_progress=_emit,
                )
            else:
                silence_bytes, silence_duration = _silent_mp3_approx_no_ffmpeg(
                    target_sec - voice_stop_duration
                )
            if silence_bytes and silence_duration > 0:
                audio_parts.append(silence_bytes)
                attempts.append({
                    "kind": "final_silence_padding",
                    "chunk": "end",
                    "duration": silence_duration,
                    "target_sec": target_sec,
                })
        output_bytes = concat_mp3_bytes(audio_parts) if audio_parts else b""
        final_duration = voice_stop_duration
    else:
        final_duration = len(full_audio) / 1000
        if final_duration > speech_deadline_sec + _TOLERANCE_OVERFLOW_SEC and not mock:
            raise ValueError(
                f"Bloc {bloc['bloc_number']} sync trop long "
                f"({final_duration:.1f}s > limite parole {speech_deadline_sec:.1f}s, "
                f"marge parole {final_silence_sec:.0f}s)."
            )
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

    if not mock and final_duration > speech_deadline_sec + _TOLERANCE_OVERFLOW_SEC:
        raise ValueError(
            f"Bloc {bloc['bloc_number']} trop long : la parole finirait à "
            f"{final_duration:.1f}s, après la limite T-{final_silence_sec:.0f}s "
            f"({speech_deadline_sec:.1f}s)."
        )

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
    """Réduit le dernier cours interne avant TTS si aucun jour suivant ne peut absorber le surplus."""
    budget = int(bloc.get("main_word_budget") or bloc.get("word_budget") or 0)
    if budget <= 0:
        raise ValueError("Budget TTS indisponible pour réduction du dernier bloc")

    # On vise plus bas que le cap prudent pour absorber l'écart de calibration Fish.
    target_words = max(800, int(budget * 0.90))
    prompt = f"""Tu es un formateur expert. Tu dois REMANIER le dernier cours audio interne
pour qu'il tienne dans sa contrainte TTS, sans jouer sur la vitesse de la voix.

OBJECTIF :
- Réduis le texte à environ {target_words} mots.
- Ne supprime pas l'idée générale : condense, fusionne les exemples redondants,
  garde les notions utiles.
- N'ajoute AUCUNE nouvelle idée.
- Ne dis jamais "hier" ni "demain". Si tu fais référence à la séance
  précédente, dis "la dernière fois" ou "lors du dernier cours".
- Termine par une vraie conclusion de cours.
- Texte oral fluide, naturel, prêt pour TTS.
- Ne mentionne jamais côté apprenant les mots "bloc", "créneau", "horaire",
  "planning", une heure précise, une durée de fichier ou un budget mots.

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


def _reduce_course_bloc_for_runtime_overflow(
    bloc: dict,
    runtime_unconsumed_chunks: list,
    *,
    model=None,
) -> str:
    """Réduit automatiquement un bloc trop long au lieu de reporter sa fin au bloc suivant."""
    text = (bloc.get("text") or "").strip()
    if not text:
        return text

    current_words = count_tts_spoken_words(text)
    overflow_text = "\n\n".join(
        (chunk.get("text") or "").strip()
        for chunk in (runtime_unconsumed_chunks or [])
        if (chunk.get("text") or "").strip()
    )
    overflow_words = max(1, count_tts_spoken_words(overflow_text))
    budget = int(bloc.get("main_word_budget") or bloc.get("word_budget") or current_words)

    # On retire le surplus observé + une marge pour éviter une deuxième dérive.
    target_words = min(
        max(700, int(budget * 0.96)),
        max(700, current_words - overflow_words - 140),
    )
    target_words = max(450, min(target_words, current_words - 80))
    min_words = max(350, int(target_words * 0.90))
    bloc_number = int(bloc.get("bloc_number") or 0)

    prompt = f"""Tu es un réviseur pédagogique spécialisé dans les scripts audio TTS.

PROBLÈME :
La partie interne {bloc_number}/7 est trop longue pour sa contrainte TTS. La fin ne doit JAMAIS
être reportée à la partie suivante. Tu dois réduire le texte de la partie actuelle pour
qu'il tienne dans son propre fichier.

OBJECTIF MOTS :
- Texte actuel : {current_words} mots parlés environ.
- Surplus observé en fin de partie : {overflow_words} mots environ.
- Cible de sortie : entre {min_words} et {target_words} mots.

PARTIE QUI A DÉBORDÉ AU RUNTIME :
---
{_compact_words(overflow_text, 900) or "(non disponible)"}
---

TEXTE COMPLET DE LA PARTIE À RÉDUIRE :
---
{text}
---

MISSION :
Réécris le TEXTE COMPLET DE LA PARTIE À RÉDUIRE en version plus courte.
Réduis prioritairement la fin, les reformulations, les exemples redondants et
les développements qui ouvrent un nouveau sujet trop tard.

CONTRAINTES ABSOLUES :
- Ne reporte rien à la partie suivante.
- Ne supprime pas l'architecture de la partie : reprise, thème, objectif, plan,
  transitions, conclusion.
- Ne crée pas de double introduction.
- Ne termine pas la partie précédente au début de cette partie.
- Ne change pas le fond pédagogique.
- N'ajoute aucune nouvelle idée.
- Si le cours se termine par une Q/R, garde une annonce Q/R sobre à la fin.
- Après l'annonce Q/R, aucun nouveau développement.
- Garde un style oral naturel, professionnel, prêt pour Fish Audio.
- Ne mentionne jamais côté apprenant les mots "bloc", "créneau", "horaire",
  "planning", une heure précise, une durée de fichier ou un budget mots.
- Pas de markdown, pas de commentaire, pas de métadonnées.

Réponds uniquement avec le texte réduit complet."""

    reduced = _llm_post(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=min(14000, int(target_words * 2.1) + 900),
        model=model or default_model(),
    )
    reduced = (reduced or "").replace("```", "").strip()
    if not reduced:
        logger.warning("⚠️ Réduction runtime bloc %s vide, texte original conservé", bloc_number)
        return text

    reduced_words = count_tts_spoken_words(reduced)
    if reduced_words > target_words:
        logger.warning(
            "⚠️ Réduction runtime bloc %s encore longue : %s mots > cible %s",
            bloc_number,
            reduced_words,
            target_words,
        )
    return reduced


_HEADING_RE = re.compile(
    r"""^(?:
        \#{1,3}\s+                              # markdown ## Titre
        |(?:[IVX]+|[A-Z])\.\s+                 # I. II. A. B.
        |\d+(?:\.\d+)*\.\s+                    # 1. 2.1. 3.2.
        |(?:[A-ZÀÂÆÇÉÈÊËÎÏÔŒÙÛÜ][^\n]{0,60}):?\s*$  # TITRE TOUT CAPS court
    )""",
    re.VERBOSE | re.UNICODE,
)


def _is_heading_paragraph(text: str) -> bool:
    """True si le paragraphe ressemble à un titre/numérotation de section."""
    stripped = text.strip()
    if not stripped:
        return False
    first_line = stripped.split("\n")[0].strip()
    if _HEADING_RE.match(first_line):
        return True
    # Ligne courte entièrement en majuscules (≤ 12 mots, sans ponctuation finale)
    words = first_line.split()
    if 1 <= len(words) <= 12 and first_line == first_line.upper() and not first_line[-1] in ".?!,;:":
        return True
    return False


def _section_boundary_positions(units: list) -> list:
    """Retourne les positions (en mots) des fins de section.

    Une fin de section = position de fin du dernier paragraphe qui précède
    un paragraphe-titre (heading). Ce sont les coupures sémantiques les plus
    fortes : on ne coupe jamais entre un titre et son contenu.
    """
    positions = []
    for i, unit in enumerate(units):
        next_unit = units[i + 1] if i + 1 < len(units) else None
        if next_unit and _is_heading_paragraph(next_unit["text"]):
            positions.append(unit["end"])
    return positions


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
    section_boundaries=None,
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
    section_window = max(300, min(1200, int(span * 0.25)))
    paragraph_window = max(160, min(700, int(span * 0.15)))
    sentence_window = max(80, min(250, int(span * 0.08)))

    # Priorité 1 : fin de section (juste avant un titre/numérotation)
    if section_boundaries:
        section_candidates = [
            b for b in section_boundaries
            if max(cursor_w + 1, target_w - section_window) <= b <= min(cap_w, target_w + section_window)
        ]
        if section_candidates:
            chosen = _closest_boundary(section_candidates, target_w)
            logger.info(f"   ✂️ Coupure fin de section: mot {chosen} (cible {target_w})")
            return chosen

    # Priorité 2 : fin de paragraphe
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


def _extract_marked_audio_blocks_from_segments(segments) -> dict[int, str]:
    """Lit les blocs persistés sous forme `<<<BLOC_AUDIO_N>>>`.

    Cette représentation sert après la calibration mots par bloc : elle évite
    de redécouper proportionnellement un texte déjà organisé exactement selon
    la playlist.
    """
    full_text = "\n\n".join((seg.get("text") or "") for seg in segments)
    matches = list(_AUDIO_BLOCK_MARKER_RE.finditer(full_text))
    if not matches:
        return {}
    blocks = {}
    for idx, match in enumerate(matches):
        bloc_num = int(match.group(1))
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(full_text)
        text = _strip_audio_block_markers(full_text[start:end]).strip()
        if text:
            blocks[bloc_num] = text
    return blocks


def _build_course_blocs_from_marked_blocks(
    marked_blocks: dict[int, str],
    playlist_spec,
    *,
    segments,
    force_all=False,
    folder_position=None,
):
    api_speed = _course_tts_speed()
    any_dirty = force_all or any(bool(seg.get("dirty")) for seg in segments)
    blocs = []
    cursor_w = 0
    for item_idx, (filename, duration_sec, file_type, bloc_num) in enumerate(playlist_spec):
        if file_type != "cours":
            continue
        bloc_num = int(bloc_num or 0)
        target_sec = int(duration_sec or 0)
        text = marked_blocks.get(bloc_num, "").strip()
        words = count_tts_spoken_words(text)
        word_budget = _estimated_words_budget_for_course(target_sec, api_speed, bloc_num)
        main_word_budget = _estimated_main_words_budget_for_course(target_sec, api_speed, bloc_num)
        blocs.append({
            "bloc_number": bloc_num,
            "text": text,
            "start_w": cursor_w,
            "end_w": cursor_w + words,
            "word_count": words,
            "contributing_seg_indices": set(range(len(segments))),
            "dirty": any_dirty,
            "target_sec": target_sec,
            "word_budget": word_budget,
            "main_word_budget": main_word_budget,
            "filename": filename,
            "role": _course_block_role(
                bloc_num,
                folder_position=folder_position,
                next_item=_next_playlist_item_after_index(playlist_spec, item_idx),
            ),
            "audio_block_marked": True,
        })
        cursor_w += words
    return blocs, cursor_w


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

    Chaque bloc reçoit un budget calibré Fish Audio. `main_word_budget` et
    `word_budget` restent deux champs pour compatibilité interne, mais ils
    portent désormais la même cible : le texte canonique du bloc, conclusion
    comprise.
    Tout paragraphe en surplus cascade automatiquement vers le bloc suivant.
    """
    marked_blocks = _extract_marked_audio_blocks_from_segments(segments)
    if marked_blocks and all(i in marked_blocks for i in range(1, 8)):
        blocs, total_marked_words = _build_course_blocs_from_marked_blocks(
            marked_blocks,
            playlist_spec,
            segments=segments,
            force_all=force_all,
        )
        logger.info("   🎚️ Découpage blocs audio persisté détecté (%s mots)", total_marked_words)
        return blocs, total_marked_words, ""

    full_words, word_to_seg_idx, units = _build_course_text_units(segments)

    total_words = len(full_words)
    total_duration = sum(cours_durations_min.values())
    sentence_boundaries = _sentence_boundary_positions(full_words)
    paragraph_boundaries = [u["end"] for u in units if u["end"] < total_words]
    section_boundaries = _section_boundary_positions(units)
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
        main_word_budget = _estimated_main_words_budget_for_course(target_sec, api_speed, bloc_num)
        word_budget = _estimated_words_budget_for_course(target_sec, api_speed, bloc_num)

        if bloc_num == 7:
            # Bloc 7 absorbe le reste : si ça dépasse son budget, le calibrage
            # budget texte en amont doit corriger avant conformité et audio.
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
                word_budget_max=main_word_budget,
                section_boundaries=section_boundaries,
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
            "main_word_budget": main_word_budget,
            "filename": next(
                (spec[0] for spec in playlist_spec if spec[3] == bloc_num and spec[2] == "cours"),
                f"cours_bloc{bloc_num}.mp3"
            ),
        })
        block_words = end_w - cursor_w
        budget_str = (
            f"budget principal {main_word_budget}, total {word_budget}"
            if main_word_budget > 0 else "budget n/a"
        )
        if main_word_budget > 0 and block_words > main_word_budget and bloc_num != 7:
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
        section_boundaries=section_boundaries,
    )

    return blocs, total_words, carryover_out


def _course_durations_min_from_playlist(playlist_spec) -> dict[int, float]:
    """Durées cours en minutes depuis la playlist effective, fallback statique."""
    from services.playlist_tts_service import COURS_DURATIONS_MIN

    durations = {int(k): float(v) for k, v in COURS_DURATIONS_MIN.items()}
    for filename, duration_sec, file_type, bloc_num in playlist_spec or []:
        if file_type != "cours":
            continue
        try:
            durations[int(bloc_num)] = max(1.0, float(duration_sec or 0) / 60.0)
        except Exception:
            logger.warning("⚠️ Durée playlist invalide pour %s bloc=%s", filename, bloc_num)
    return durations


def _audio_block_word_status(text: str, block: dict) -> dict:
    words = count_tts_spoken_words(text)
    min_words = int(block.get("min_words") or _block_min_words(block.get("word_budget") or 0))
    max_words = int(block.get("max_words") or block.get("word_budget") or 0)
    target_words = int(block.get("target_words") or max_words)
    if max_words <= 0:
        return {
            "ok": True,
            "status": "no_budget",
            "words": words,
            "min_words": 0,
            "max_words": 0,
            "target_words": 0,
            "delta": 0,
        }
    if words < min_words:
        return {
            "ok": False,
            "status": "under_budget",
            "words": words,
            "min_words": min_words,
            "max_words": max_words,
            "target_words": target_words,
            "delta": min_words - words,
        }
    if words > max_words:
        return {
            "ok": False,
            "status": "over_budget",
            "words": words,
            "min_words": min_words,
            "max_words": max_words,
            "target_words": target_words,
            "delta": words - max_words,
        }
    return {
        "ok": True,
        "status": "ok",
        "words": words,
        "min_words": min_words,
        "max_words": max_words,
        "target_words": target_words,
        "delta": 0,
    }


def _clean_audio_block_rewrite(raw: str) -> str:
    """Nettoie une réponse IA de calibrage bloc sans supprimer les tags TTS."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    text = _strip_audio_block_markers(text)
    text = re.sub(r"^\s*(texte\s+(?:réécrit|calibré)\s*:)\s*", "", text, flags=re.I)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _trim_text_to_max_spoken_words(text: str, max_words: int) -> str:
    """Raccourcit proprement en visant une frontière de paragraphe/phrase."""
    text = (text or "").strip()
    max_words = max(0, int(max_words or 0))
    if max_words <= 0 or count_tts_spoken_words(text) <= max_words:
        return text

    kept = []
    kept_words = 0
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    for paragraph in paragraphs:
        para_words = count_tts_spoken_words(paragraph)
        if kept_words + para_words <= max_words:
            kept.append(paragraph)
            kept_words += para_words
            continue

        sentences = [
            s.strip()
            for s in re.split(r"(?<=[.!?…])\s+", paragraph)
            if s.strip()
        ]
        sentence_added = False
        for sentence in sentences:
            sent_words = count_tts_spoken_words(sentence)
            if kept_words + sent_words <= max_words:
                kept.append(sentence)
                kept_words += sent_words
                sentence_added = True
            else:
                break
        if sentence_added or kept_words >= max_words:
            break

        # Dernier recours : coupe au mot si aucune phrase complète ne rentre.
        remaining = max_words - kept_words
        if remaining > 0:
            raw_tokens = paragraph.split()
            candidate = []
            for token in raw_tokens:
                candidate.append(token)
                if count_tts_spoken_words(" ".join(candidate)) >= remaining:
                    break
            if candidate:
                fragment = " ".join(candidate).strip()
                if fragment and fragment[-1] not in ".!?…":
                    fragment += "."
                kept.append(fragment)
        break

    trimmed = "\n\n".join(kept).strip()
    return trimmed or " ".join(text.split()[:max_words]).strip()


_AUDIO_BLOCK_FILLERS = [
]


def _expand_text_to_min_spoken_words(text: str, min_words: int, max_words: int) -> str:
    """Dernier recours sans remplissage générique.

    Le sous-budget doit être corrigé par l'IA dans les itérations de calibrage.
    Si l'IA n'y arrive pas ou échoue, on conserve le texte existant plutôt que
    d'ajouter des paragraphes génériques qui dégradent la formation.
    """
    return (text or "").strip()


def _build_audio_block_calibration_prompt(
    *,
    block: dict,
    current_text: str,
    status: dict,
    direction: str,
    day_context: str,
) -> str:
    budget_contract = load_budget_rewrite_contract()
    target_words = min(
        int(status.get("max_words") or 0),
        max(int(status.get("min_words") or 0), int(status.get("target_words") or 0) - 40),
    )
    action = (
        "raccourcir sans perdre les idées essentielles"
        if direction == "shorten"
        else "enrichir avec du contenu pédagogique pertinent, directement lié au plan et au sujet"
    )
    if direction == "shorten":
        direction_rules = (
            "- Réduis prioritairement les répétitions, les reformulations faibles, les exemples trop longs et les développements après conclusion.\n"
            "- Si une conclusion est suivie d'un nouveau développement, supprime ou fusionne ce débordement pour que la fin reste propre.\n"
        )
    else:
        direction_rules = (
            "- Le texte est trop court : tu dois l'enrichir en intégrant de vrais apports pédagogiques dans les parties de développement, jamais en ajoutant un appendice à la fin.\n"
            "- Ajoute une idée utile à la fois : nuance terrain, contre-exemple, mini-cas fictif, clarification méthodologique, erreur fréquente ou lien concret avec un teaching beat existant.\n"
            "- Ne rends pas simplement les phrases plus verbeuses. Chaque ajout doit apporter une valeur pédagogique identifiable.\n"
            "- Insère les enrichissements AVANT la conclusion et AVANT toute annonce de questions-réponses ou de tchat.\n"
            "- Respecte les slides/anchors prévus : les enrichissements doivent soutenir les moments pédagogiques existants, pas créer une trajectoire parallèle.\n"
            "- Les exemples ajoutés doivent être fictifs ou hypothétiques et aider une idée précise du plan verrouillé.\n"
        )
    direction_rules += (
        "- Si le texte contient déjà une conclusion/Q-R, elle doit rester la dernière partie du texte final. Aucun nouveau développement après cette conclusion.\n"
        "- N'ajoute jamais de remplissage générique, de répétition automatique ou de paragraphe passe-partout.\n"
    )
    return f"""Tu es directeur éditorial d'un cours audio TTS Fish Audio.

CONTRAT DE RÉÉCRITURE BUDGET :
{budget_contract}

Objectif : réécrire UN bloc de cours pour qu'il tombe dans son budget de mots parlé.
Ce texte sera lu tel quel. Il ne faut PAS répondre en JSON, PAS ajouter de titre,
PAS ajouter de markdown, PAS ajouter de marqueur technique.

Contexte journée :
{day_context}

Cours audio interne :
- Cours {block.get('bloc_number')} · fichier {block.get('filename')}
- Durée interne : {block.get('duration_min')} min
- Budget accepté : {status.get('min_words')} à {status.get('max_words')} mots parlés
- Cible pratique : environ {target_words} mots parlés
- Texte actuel : {status.get('words')} mots
- Écart à corriger : {status.get('delta')} mots
- Direction artistique : {block.get('role') or 'continuité pédagogique orale'}

Mission :
- Tu dois {action}.
- Le texte final doit rester oral, fluide, humain, TTS-ready.
- Garde les tags TTS utiles comme [pause] ou [calm], mais n'en abuse pas.
- Respecte le plan et la fonction pédagogique du cours.
- Ne change pas le niveau RNCP, ne rajoute pas de promesse ou contenu sensible.
- Respecte la logique playlist : si ce cours annonce une pause ou un Q&A, cette annonce
  reste dans l'outro du cours précédent, pas dans le fichier pause/Q&A.
- Les mots "bloc", "créneau", "horaire", "planning", les durées, les fichiers et
  les budgets sont internes : ne les mentionne jamais dans le texte final.
- Ne gonfle pas hors budget : le résultat doit finir entre {status.get('min_words')}
  et {status.get('max_words')} mots parlés.
- Si tu enrichis, garde l'ordre du texte existant : introduction, développement,
  conclusion. Ne prolonge jamais le développement après une annonce Q/R, tchat,
  temps d'échange ou fin de partie.
{direction_rules}

Texte actuel à réécrire :
{current_text}
"""


def _calibrate_single_audio_block(
    *,
    block: dict,
    text: str,
    model=None,
    max_iterations: int = 4,
    day_context: str = "",
) -> tuple[str, dict]:
    """Ajuste un bloc par IA puis fallback déterministe pour garantir le budget."""
    current_text = (text or "").strip()
    history = []
    changed = False

    for iteration in range(1, max(1, int(max_iterations or 1)) + 1):
        status = _audio_block_word_status(current_text, block)
        history.append({
            "iteration": iteration,
            "status": status["status"],
            "words": status["words"],
            "delta": status["delta"],
        })
        if status["ok"]:
            return current_text, {
                **status,
                "changed": changed,
                "iterations": iteration - 1,
                "fallback": None,
                "history": history,
            }

        direction = "shorten" if status["status"] == "over_budget" else "expand"
        prompt = _build_audio_block_calibration_prompt(
            block=block,
            current_text=current_text,
            status=status,
            direction=direction,
            day_context=day_context,
        )
        try:
            raw = _anthropic_post(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=16000,
                model=model,
            )
            candidate = _clean_audio_block_rewrite(raw)
            candidate_words = count_tts_spoken_words(candidate)
            if candidate and candidate_words > 0 and candidate.strip() != current_text.strip():
                current_text = candidate
                changed = True
                logger.info(
                    "PIPELINE_AUDIO_BLOCK_CALIBRATION_ITER bloc=%s iteration=%s direction=%s words=%s",
                    block.get("bloc_number"),
                    iteration,
                    direction,
                    candidate_words,
                )
                continue
            logger.warning(
                "PIPELINE_AUDIO_BLOCK_CALIBRATION_EMPTY bloc=%s iteration=%s direction=%s",
                block.get("bloc_number"),
                iteration,
                direction,
            )
            break
        except Exception as e:
            logger.warning(
                "PIPELINE_AUDIO_BLOCK_CALIBRATION_LLM_FAILED bloc=%s iteration=%s error=%s",
                block.get("bloc_number"),
                iteration,
                str(e)[:300],
            )
            break

    final_status = _audio_block_word_status(current_text, block)
    fallback = None
    if final_status["status"] == "over_budget":
        current_text = _trim_text_to_max_spoken_words(current_text, final_status["max_words"])
        changed = True
        fallback = "trim_to_max_words"
    elif final_status["status"] == "under_budget":
        current_text = _expand_text_to_min_spoken_words(
            current_text,
            final_status["min_words"],
            final_status["max_words"],
        )
        changed = True
        fallback = "expand_to_min_words"

    final_status = _audio_block_word_status(current_text, block)
    return current_text, {
        **final_status,
        "changed": changed,
        "iterations": len(history),
        "fallback": fallback,
        "history": history,
    }


def _persist_calibrated_audio_blocks(job: dict, calibrated_blocks: list[dict]) -> int:
    """Persiste les 7 blocs audio comme source canonique du script TTS prévu."""
    if not calibrated_blocks:
        return 0

    review_signature = _current_humanization_review_signature()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, sub_part_index, sub_part_name, passe
        FROM content_generation_segments
        WHERE job_id = ? AND status = 'completed'
        ORDER BY sub_part_index ASC, passe ASC
        """,
        (job["id"],),
    )
    rows = cursor.fetchall()
    if len(rows) < len(calibrated_blocks):
        conn.close()
        raise ValueError(
            f"Calibrage blocs impossible : {len(rows)} segment(s) disponibles "
            f"pour {len(calibrated_blocks)} bloc(s) audio"
        )

    total_words = 0
    for idx, block in enumerate(calibrated_blocks):
        seg_id = rows[idx][0]
        bloc_num = int(block["bloc_number"])
        text = (block.get("text") or "").strip()
        stored_text = f"<<<BLOC_AUDIO_{bloc_num}>>>\n\n{text}".strip()
        words = count_tts_spoken_words(text)
        total_words += words
        cursor.execute(
            """
            UPDATE content_generation_segments
            SET text_content = ?, word_count = ?, dirty = 1,
                humanized = 1, humanization_error = NULL, humanization_signature = ?,
                reviewed = 0, review_error = NULL, review_signature = NULL
            WHERE id = ?
            """,
            (stored_text, words, review_signature, seg_id),
        )

    for row in rows[len(calibrated_blocks):]:
        cursor.execute(
            """
            UPDATE content_generation_segments
            SET text_content = '', word_count = 0, dirty = 1,
                humanized = 1, humanization_error = NULL, humanization_signature = ?,
                reviewed = 0, review_error = NULL, review_signature = NULL
            WHERE id = ?
            """,
            (review_signature, row[0]),
        )

    cursor.execute(
        """
        UPDATE content_generation_jobs
        SET total_words = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (total_words, job["id"]),
    )
    conn.commit()
    conn.close()
    return total_words


def run_audio_block_word_calibration(
    folder_id: int,
    *,
    on_progress=None,
    model=None,
    max_iterations: int | None = None,
    force: bool = False,
    stage: str = "",
) -> dict:
    """Legacy : calibre les 7 blocs audio au nombre de mots prévu.

    Cette passe n'est plus appelée par le flux API actif. Le calibrage de volume
    se fait désormais avant conformité, directement dans la génération structurée.
    """
    from services.playlist_tts_service import PLAYLIST_SPEC

    job = get_job_from_db(folder_id)
    if not job:
        raise ValueError(f"Aucun content_generation_job pour folder {folder_id}")
    if max_iterations is None:
        max_iterations = int(os.getenv("FORMATION_TTS_BLOCK_CALIBRATION_MAX_ITERATIONS", "4") or "4")

    playlist_spec = _playlist_items_for_platform(job["platform_id"]) or list(PLAYLIST_SPEC)
    cours_durations_min = _course_durations_min_from_playlist(playlist_spec)
    plan = _course_audio_block_plan(playlist_spec, folder_position=job.get("folder_position"))
    plan_by_bloc = {int(block["bloc_number"]): block for block in plan}
    day_context = _build_audio_day_plan_context({"folder_position": job.get("folder_position")})

    segments = _load_segments_for_course_plan(job, sync_slides=False)
    if not segments:
        raise ValueError(f"Aucun segment complété pour calibrer folder {folder_id}")

    next_folder_id = _find_next_folder_id(job["platform_id"], folder_id)
    blocs, _total_words, _carryover_out = _build_course_blocs_from_segments(
        segments,
        cours_durations_min,
        playlist_spec,
        force_all=False,
        source_folder_id=None,
        next_folder_id=next_folder_id,
        is_last_folder=next_folder_id is None,
        model=model,
        preview=True,
    )

    total = len(blocs)
    calibrated_blocks = []
    block_results = []
    changed = False

    for idx, bloc in enumerate(blocs, start=1):
        bloc_num = int(bloc.get("bloc_number") or idx)
        budget_block = {**bloc, **plan_by_bloc.get(bloc_num, {})}
        current_text = (bloc.get("text") or "").strip()
        initial_status = _audio_block_word_status(current_text, budget_block)
        if on_progress:
            on_progress(idx, total, f"Calibrage mots bloc {bloc_num} ({initial_status['words']} mots)…")

        if initial_status["ok"] and not force:
            calibrated_text = current_text
            result = {**initial_status, "changed": False, "iterations": 0, "fallback": None, "history": []}
        else:
            calibrated_text, result = _calibrate_single_audio_block(
                block=budget_block,
                text=current_text,
                model=model,
                max_iterations=max_iterations,
                day_context=day_context,
            )
        if calibrated_text.strip() != current_text.strip() or result.get("changed"):
            changed = True
        calibrated_blocks.append({
            "bloc_number": bloc_num,
            "text": calibrated_text,
        })
        block_results.append({
            "bloc_number": bloc_num,
            "filename": budget_block.get("filename"),
            "initial_words": initial_status["words"],
            "final_words": count_tts_spoken_words(calibrated_text),
            "min_words": result.get("min_words"),
            "max_words": result.get("max_words"),
            "target_words": result.get("target_words"),
            "status": result.get("status"),
            "changed": bool(calibrated_text.strip() != current_text.strip() or result.get("changed")),
            "iterations": result.get("iterations", 0),
            "fallback": result.get("fallback"),
        })

    if changed:
        total_words = _persist_calibrated_audio_blocks(job, calibrated_blocks)
    else:
        total_words = sum(count_tts_spoken_words(block["text"]) for block in calibrated_blocks)

    day_audit = compute_course_day_word_budget_audit(folder_id)
    logger.info(
        "PIPELINE_AUDIO_BLOCK_CALIBRATION_DONE formation_job_id=%s content_job_id=%s folder_id=%s "
        "stage=%s changed=%s total_words=%s day_status=%s spoken=%s",
        job.get("formation_job_id"),
        job["id"],
        folder_id,
        stage,
        bool(changed),
        total_words,
        day_audit.get("status"),
        day_audit.get("spoken_words"),
    )
    return {
        "folder_id": folder_id,
        "content_job_id": job["id"],
        "changed": bool(changed),
        "stage": stage,
        "total_words": int(total_words),
        "blocks": block_results,
        "day_audit": day_audit,
        "max_iterations": int(max_iterations),
    }


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
            cap_words = int(bloc.get("main_word_budget") or bloc.get("word_budget") or 0)
            if cap_words > 0 and new_word_count > cap_words:
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
    section_boundaries=None,
):
    """Si le bloc 7 dépasse, reporte vers le cours suivant ou réduit le dernier jour."""
    if not blocs:
        return ""

    last = blocs[-1]
    budget = int(last.get("main_word_budget") or last.get("word_budget") or 0)
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
            section_boundaries=section_boundaries,
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


def _apply_closing_transitions(blocs, api_speed, model=None, playlist_items=None):
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
    estimated_wpm = _course_words_per_minute()
    course_item_index = {
        int(item[3]): idx
        for idx, item in enumerate(playlist_items or [])
        if len(item) >= 4 and item[2] == "cours"
    }

    for idx, bloc in enumerate(blocs):
        if not bloc.get("dirty"):
            continue  # bloc clean : on ne touche pas à l'existant
        if not (bloc.get("text") or "").strip():
            continue  # bloc vide : rien à clore

        voice_stop_sec = bloc["target_sec"] - _course_final_silence_sec()
        raw_gap_sec = voice_stop_sec - _estimated_audio_seconds_for_words(
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
            next_item=_next_playlist_item_after(
                playlist_items,
                course_item_index.get(int(bloc["bloc_number"]), len(playlist_items or [])),
            ),
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


def _fish_actual_reading_summary(metadata: dict | None, *, input_text: str = "") -> dict:
    """Résumé compact de l'alignement Fish, stockable dans le plan audio."""
    metadata = metadata or {}
    duration_sec = float(metadata.get("audio_duration_sec") or 0.0)
    spoken_words = int(metadata.get("spoken_word_count") or 0)
    input_words = count_tts_spoken_words(input_text)
    wpm = float(metadata.get("words_per_minute") or 0.0)
    if not wpm and duration_sec > 0 and input_words > 0:
        wpm = input_words / (duration_sec / 60.0)
    return {
        "provider": metadata.get("provider") or "fish_audio",
        "endpoint": metadata.get("endpoint") or "",
        "model": metadata.get("model") or "",
        "format": metadata.get("format") or "",
        "speed": metadata.get("speed"),
        "audio_duration_sec": round(duration_sec, 3),
        "input_spoken_word_count": int(input_words),
        "fish_segment_word_count": int(spoken_words),
        "words_per_minute": round(wpm, 3),
        "words_per_hour": round(wpm * 60.0, 1) if wpm else 0.0,
        "text_read": metadata.get("text_read") or "",
        "timeline": metadata.get("timeline") or [],
        "chunks": metadata.get("chunks") or [],
    }


def _synthesize_course_audio_to_fit(
    bloc,
    convert_to_speech,
    measure_duration_ms,
    pad_audio_to_duration,
    convert_to_speech_with_timestamps=None,
):
    """
    Génère un bloc cours sans troncature brutale.
    Par défaut, on n'accélère pas la voix : si le texte est manifestement trop
    long, on échoue avant l'appel Fish Audio pour éviter de payer un TTS inutilisable.
    Un speedup local reste possible seulement si FORMATION_TTS_LOCAL_MAX_SPEEDUP > 1.
    """
    target_sec = int(bloc["target_sec"])
    final_silence_sec = _course_final_silence_sec()
    max_voice_sec = _course_voice_window_sec(target_sec)
    if max_voice_sec <= 0:
        raise ValueError(
            f"Bloc {bloc['bloc_number']} impossible à synthétiser : cible {target_sec}s "
            f"trop courte pour garder {final_silence_sec:.0f}s de marge parole."
        )
    api_speed = _course_tts_speed()
    attempts = []
    word_count = bloc.get("word_count") or len(bloc["text"].split())
    word_budget = _estimated_words_budget_for_course(
        target_sec,
        api_speed,
        bloc.get("bloc_number"),
    )

    if word_budget > 0 and word_count > word_budget:
        raise ValueError(
            f"Bloc {bloc['bloc_number']} trop long avant TTS "
            f"({word_count} mots > budget prudent {word_budget} mots à speed={api_speed}). "
            "Aucun appel Fish Audio lancé. Il faut générer moins de mots en amont "
            "ou réduire ce bloc avant synthèse."
        )

    actual_reading = None
    if convert_to_speech_with_timestamps and _fish_timestamp_alignment_enabled():
        audio_bytes, timestamp_meta = convert_to_speech_with_timestamps(
            bloc["text"],
            speed=api_speed,
            format="mp3",
        )
        actual_reading = _fish_actual_reading_summary(timestamp_meta, input_text=bloc["text"])
    else:
        audio_bytes = convert_to_speech(bloc["text"], speed=api_speed)
    raw_duration = float((actual_reading or {}).get("audio_duration_sec") or 0.0)
    if not raw_duration:
        try:
            raw_duration = _mp3_duration_seconds_no_ffprobe(audio_bytes)
        except Exception:
            raw_duration = measure_duration_ms(audio_bytes) / 1000
    attempts.append({
        "kind": "api_timestamped" if actual_reading else "api",
        "speed": api_speed,
        "duration": raw_duration,
        "actual_reading": actual_reading,
    })

    if raw_duration <= max_voice_sec:
        final_bytes, _final_duration = _pad_course_mp3_to_duration_no_ffprobe(
            audio_bytes,
            raw_duration,
            target_sec,
        )
        return final_bytes, raw_duration, f"api_speed={api_speed}", attempts

    required_speedup = raw_duration / max_voice_sec
    max_speedup = _course_local_max_speedup()
    if max_speedup <= 1.0:
        raise ValueError(
            f"Bloc {bloc['bloc_number']} trop long pour {target_sec}s "
            f"(voix {raw_duration:.1f}s > max {max_voice_sec:.1f}s à speed={api_speed}, "
            f"marge parole {final_silence_sec:.0f}s). "
            "Speedup local désactivé par défaut pour préserver la voix. "
            "Audio non uploadé pour éviter une coupure en pleine phrase."
        )

    if required_speedup > max_speedup:
        raise ValueError(
            f"Bloc {bloc['bloc_number']} trop long pour {target_sec}s "
            f"(voix {raw_duration:.1f}s > max {max_voice_sec:.1f}s, "
            f"speedup requis x{required_speedup:.3f} > limite x{max_speedup:.3f}, "
            f"marge parole {final_silence_sec:.0f}s). "
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
        f"(max voix {max_voice_sec:.1f}s, marge parole {final_silence_sec:.0f}s). "
        f"Tentatives locales: {attempts_str}. "
        "Audio non uploadé pour éviter une coupure en pleine phrase."
    )


def _synthesize_fish_course_audio_observe(
    bloc,
    convert_to_speech,
    measure_duration_ms,
    convert_to_speech_with_timestamps=None,
):
    """
    Génère Fish Audio tel quel et mesure la durée réelle.
    Utilisé pour lancer les cours d'une journée en parallèle sans réduire le
    texte ni rejeter un bloc parce qu'il dépasse son créneau théorique.
    """
    api_speed = _course_tts_speed()
    actual_reading = None
    retry_config = _fish_audio_429_retry_config()
    retry_attempt = 0
    while True:
        try:
            if convert_to_speech_with_timestamps and _fish_timestamp_alignment_enabled():
                audio_bytes, timestamp_meta = convert_to_speech_with_timestamps(
                    bloc["text"],
                    speed=api_speed,
                    format="mp3",
                )
                actual_reading = _fish_actual_reading_summary(timestamp_meta, input_text=bloc["text"])
            else:
                audio_bytes = convert_to_speech(bloc["text"], speed=api_speed)
            break
        except Exception as exc:
            error_text = str(exc)
            is_rate_limited = "429" in error_text or "too many requests" in error_text.lower()
            if not is_rate_limited or retry_attempt >= retry_config["max_retries"]:
                raise
            retry_attempt += 1
            wait_sec = min(
                retry_config["max_wait_sec"],
                retry_config["base_wait_sec"] * (2 ** (retry_attempt - 1)),
            )
            logger.warning(
                "PIPELINE_AUDIO_FISH_429_RETRY bloc=%s attempt=%s/%s wait_sec=%.1f error=%s",
                bloc.get("bloc_number"),
                retry_attempt,
                retry_config["max_retries"],
                wait_sec,
                error_text[:220],
            )
            time.sleep(wait_sec)

    raw_duration = float((actual_reading or {}).get("audio_duration_sec") or 0.0)
    if not raw_duration:
        try:
            raw_duration = _mp3_duration_seconds_no_ffprobe(audio_bytes)
        except Exception:
            raw_duration = measure_duration_ms(audio_bytes) / 1000

    attempts = [{
        "kind": "api_observe_timestamped" if actual_reading else "api_observe",
        "speed": api_speed,
        "duration": raw_duration,
        "actual_reading": actual_reading,
        "rate_limit_retries": retry_attempt,
    }]
    return audio_bytes, raw_duration, f"fish_observe_speed={api_speed}", attempts


# Prompt général de génération du contenu de formation.
# Il reste dans backend/prompts/ pour être embarqué dans l'artifact de déploiement
# backend — le workflow ne package que ./backend/.
_GENERAL_FORMATION_PROMPTS_FILE = os.path.join(
    os.path.dirname(__file__), "..", "prompts", "prompts-generaux-contenu-formation.md"
)

# Cache des prompts invalidé sur mtime du fichier source — permet d'éditer
# les prompts .md sans redémarrer le backend (watchmedo ne watch que *.py).
# Structure : (prompts_list, mtime) ou None.
_PASSE_PROMPTS = None


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
    Retourne les 3 prompts généraux (Passe 1/2/3) depuis le fichier .md.
    Recharge automatiquement si le fichier a été modifié depuis la dernière lecture.
    """
    global _PASSE_PROMPTS
    path = _GENERAL_FORMATION_PROMPTS_FILE
    mtime = os.path.getmtime(path)

    if _PASSE_PROMPTS is not None and _PASSE_PROMPTS[1] == mtime:
        return _PASSE_PROMPTS[0]

    prompts = _parse_passe_prompts_from_file(path)
    _PASSE_PROMPTS = (prompts, mtime)
    logger.info(f"📖 Prompts rechargés depuis {os.path.basename(path)}")
    return prompts


def _build_course_position_context(
    *,
    folder_position=None,
    nb_days=None,
    total_hours=None,
    folder_name="",
    sub_part_index=None,
    passe=None,
) -> str:
    """Ajoute au prompt le contexte qui permet de traiter correctement les ouvertures."""
    try:
        day_number = int(folder_position) + 1 if folder_position is not None else None
    except Exception:
        day_number = None
    try:
        sub_number = int(sub_part_index) + 1 if sub_part_index is not None else None
    except Exception:
        sub_number = None
    try:
        passe_number = int(passe) if passe is not None else None
    except Exception:
        passe_number = None

    is_first_annual_course = day_number == 1 and sub_number == 1 and passe_number == 1
    is_day_opening = sub_number == 1 and passe_number == 1

    lines = [
        "═══════════════════════════════════════════════════════════════════",
        "CONTEXTE POSITIONNEL — OUVERTURES À RESPECTER",
        "═══════════════════════════════════════════════════════════════════",
    ]
    if day_number:
        total_days_label = f"/{nb_days}" if nb_days else ""
        lines.append(f"Journée : {day_number}{total_days_label}.")
    if total_hours:
        lines.append(f"Durée totale de la formation : {total_hours}h.")
    if folder_name:
        lines.append(f"Intitulé de journée : {folder_name}.")
    if sub_number:
        lines.append(f"Cours de la journée : {sub_number}/{NUM_SUB_PARTS}.")
    if passe_number:
        lines.append(f"Passe : {passe_number}/3.")

    if is_first_annual_course:
        lines.extend([
            "",
            "CETTE PASSE EST L'OUVERTURE ABSOLUE DE LA FORMATION.",
            "Avant toute notion métier, écris une vraie introduction de formation",
            "de 220 à 380 mots. Elle doit accueillir, raconter pourquoi cette",
            "formation existe, expliquer en quoi elle sera utile concrètement",
            "dans le métier, présenter synthétiquement le parcours global de",
            "l'année, annoncer les grandes familles de compétences qui seront",
            "travaillées, donner envie de s'engager et rassurer les apprenants",
            "sur le rythme.",
            "Ensuite, annonce les thèmes de la journée dans leur ordre",
            "pédagogique, puis bascule vers le premier grand thème, son objectif",
            "et son plan oral en 2 à 4 axes. Les exemples, cas clients et",
            "métaphores ne doivent venir qu'après cette carte mentale.",
            "Cette ouverture doit ressembler au début d'une année de formation,",
            "pas au début d'un chapitre isolé.",
            "Interdiction de commencer par : \"Bon, on va aborder...\",",
            "\"nouvelle partie\", \"on entre dans le vif du sujet\", ou une",
            "affirmation intense du type \"c'est absolument fondamental\".",
        ])
    elif is_day_opening:
        lines.extend([
            "",
            "CETTE PASSE EST LE DÉBUT D'UNE JOURNÉE DE FORMATION.",
            "Tu dois commencer par une vraie amorce de journée : accueil,",
            "remise en route, lien avec la progression globale, intention du jour,",
            "thèmes de la journée dans leur ordre pédagogique, puis transition",
            "progressive vers le premier sujet.",
            "Côté apprenant, parle de premier grand thème, première partie ou",
            "chapitre, pas de 'premier cours', 'ce cours' ou 'cours actuel'.",
            "Interdiction de démarrer brutalement par \"Bon, on va aborder...\",",
            "\"nouvelle partie du cours\" ou une phrase de conférence.",
        ])
    else:
        lines.extend([
            "",
            "Ce passage n'est pas l'ouverture absolue de la formation. Si tu dois",
            "introduire un sujet, fais-le avec une transition orale douce et jamais",
            "avec une formule mécanique du type \"Bon, on va aborder une nouvelle partie\".",
        ])
    return "\n".join(lines)


# ─── Extraction des sous-parties ─────────────────────────────────────────────

_EXTRACT_PROMPT = """Tu analyses un programme de formation professionnelle.
Ton rôle : identifier exactement 7 cours distincts qui couvrent une journée complète de formation, dans l'ordre pédagogique de la journée.

Réponds UNIQUEMENT en JSON valide, sans aucun texte avant ou après :
{{
  "title": "Nom exact du titre professionnel préparé",
  "sub_parts": [
    "Cours 1 — Nom précis du thème",
    "Cours 2 — Nom précis du thème",
    "Cours 3 — Nom précis du thème",
    "Cours 4 — Nom précis du thème",
    "Cours 5 — Nom précis du thème",
    "Cours 6 — Nom précis du thème",
    "Cours 7 — Nom précis du thème"
  ]
}}

Règles :
- Exactement 7 cours, dans l'ordre pédagogique de la journée.
- Ne mets jamais d'heure, de durée, de créneau, de planning ou de mention de fichier dans les noms.
- Chaque nom doit être suffisamment précis pour orienter la génération au budget audio injecté
- Couvrir l'essentiel du programme sans répétition entre cours
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
    Appelle Claude pour extraire 7 cours depuis le programme.
    Synchrone — retourne {"title": str, "sub_parts": [str×7]} ou lève une exception.
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

            # Forcer exactement 7 cours.
            sub_parts = [
                _strip_internal_schedule_from_label(item)
                for item in data["sub_parts"][:NUM_SUB_PARTS]
            ]
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
                           from_scratch=False, module_content="", model=None,
                           generation_context=None):
    """
    Génère le texte d'un segment via Claude.
    passe : 1, 2 ou 3

    Mode expansion (from_scratch=False) — comportement historique :
      - prev_text : texte passe 1 pour passe 2, texte passe 1+2 pour passe 3

    Mode from_scratch (from_scratch=True) — nouveau pipeline formation :
      - Chaque passe génère depuis module_content (pas du texte précédent)
      - Passe 1 = Fondation, Passe 2 = Pratique, Passe 3 = Maîtrise

    Retourne le texte généré avec un volume calibré sur les cours audio internes.
    """
    prompts = _get_passe_prompts(from_scratch=from_scratch)
    template = prompts[passe - 1]
    learner_safe_sub_part_name = _strip_internal_schedule_from_label(sub_part_name)

    prompt = template
    prompt = prompt.replace("{NOM_DU_TITRE_PROFESSIONNEL}", program_title)
    prompt = prompt.replace("{NOM_DE_LA_SOUS_PARTIE}", learner_safe_sub_part_name)
    prompt = prompt.replace("{CONTENU_DU_MODULE}", (module_content or program_text)[:15000])
    # Compatibilité avec d'anciens placeholders encore présents dans certaines
    # sections documentaires du prompt.
    prompt = prompt.replace("{COLLER_LE_PROGRAMME_ICI}", program_text[:12000])
    prompt = prompt.replace("{COLLER_LE_TEXTE_DE_LA_PASSE_1}", prev_text[:40000])
    prompt = prompt.replace("{COLLER_LE_TEXTE_COMPLET_PASSE_1_ET_2}", prev_text[:60000])

    if generation_context:
        prompt += "\n\n" + _build_course_position_context(**generation_context)
    prompt += "\n\n" + _build_course_slot_generation_context(
        generation_context,
        sub_part_name=learner_safe_sub_part_name,
        module_content=module_content,
        program_text=program_text,
    )
    prompt += "\n\n" + _build_generation_volume_context(generation_context)
    prompt += "\n\n" + _build_audio_day_plan_context(generation_context)

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

    # Couche 2 — Boucle de continuation si volume insuffisant.
    # Le volume est dérivé des créneaux `cours` uniquement, à la cadence TTS
    # calibrée, pour éviter les anciennes journées artificiellement à 90k mots.
    volume_budget = get_course_segment_generation_budget()
    MIN_WORDS = int(volume_budget["min_words"])
    TARGET_WORDS = int(volume_budget["target_words"])
    MAX_WORDS = int(volume_budget["max_words"])
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
            f"Tu as écrit {words} mots sur une cible de {TARGET_WORDS} mots "
            f"(minimum acceptable {MIN_WORDS}, maximum prudent {MAX_WORDS}). "
            f"Continue le cours là où tu t'es arrêté, avec le même ton oral, "
            f"les mêmes règles TTS (tags Fish Audio, pas de musique/alcool/fêtes, "
            f"discours indirect, pas de visuel), et la même voix narrative.\n\n"
            f"CONSIGNE DE DÉVELOPPEMENT (environ {max(350, TARGET_WORDS - words)} "
            f"mots supplémentaires, sans dépasser {MAX_WORDS} mots au total si possible) :\n"
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
    if module_contents:
        normalized_module_contents = {}
        for key, value in (module_contents or {}).items():
            normalized_module_contents[key] = value
            normalized_module_contents[_strip_internal_schedule_from_label(key)] = value
        module_contents = normalized_module_contents

    # Extraction des sous-parties si pas fournie
    if sub_parts_override:
        sub_parts = [
            _strip_internal_schedule_from_label(item)
            for item in sub_parts_override[:NUM_SUB_PARTS]
        ]
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
               cf.formation_job_id, cf.name, cf.position,
               fpj.nb_days, fpj.total_hours
        FROM content_generation_jobs cgj
        LEFT JOIN cours_folders cf ON cf.id = cgj.folder_id
        LEFT JOIN formation_pipeline_jobs fpj ON fpj.id = cf.formation_job_id
        WHERE cgj.folder_id = ?
    """, (folder_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "folder_id": folder_id, "platform_id": row[1], "program_text": row[2],
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
        "folder_position": row[18],
        "nb_days": row[19],
        "total_hours": row[20],
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
    # Un texte nouveau/réécrit doit repasser par conformité locale.
    cursor.execute("""
        INSERT OR REPLACE INTO content_generation_segments
            (job_id, sub_part_index, sub_part_name, passe, status,
             text_content, word_count, dirty,
             humanized, humanization_error, humanization_signature,
             reviewed, review_error, review_signature)
        VALUES (?, ?, ?, ?, 'completed', ?, ?, 1, 0, NULL, NULL, 0, NULL, NULL)
    """, (job_id, sub_idx, sub_part_name, passe, text, word_count))
    conn.commit()
    conn.close()
    logger.info(f"  💾 Checkpoint : sous-partie {sub_idx+1}, passe {passe} ({word_count} mots)")


def mark_segment_modified(job_id: int, sub_idx: int, passe: int) -> None:
    """
    Marque un segment comme modifié : doit être re-synthétisé par le TTS
    (dirty=1), re-passé par conformité locale, et ses anciennes erreurs
    reviewer invalidées.

    À appeler depuis TOUS les endroits où `text_content` change :
    - _save_segment_db (génération/régénération) — déjà couvert via l'INSERT
    - route d'édition UI d'un segment — à appeler explicitement
    - apply_review_patch ci-dessous — à appeler explicitement
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE content_generation_segments
        SET dirty = 1,
            humanized = 0, humanization_error = NULL, humanization_signature = NULL,
            reviewed = 0, review_error = NULL, review_signature = NULL
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


def _content_segments_artifact_snapshot(job_id: int) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sub_part_index, sub_part_name, passe, text_content, word_count, dirty,
               COALESCE(humanized, 0), COALESCE(reviewed, 0),
               humanization_error, review_error
        FROM content_generation_segments
        WHERE job_id = ? AND status = 'completed'
        ORDER BY sub_part_index ASC, passe ASC
    """, (job_id,))
    rows = cursor.fetchall()
    conn.close()

    courses = []
    for row in rows:
        sub_idx, sub_name, passe, text, word_count, dirty, humanized, reviewed, humanization_error, review_error = row
        marker_course_number = _extract_audio_block_number(text or "")
        course_number = marker_course_number or int(sub_idx or 0) + 1
        clean_text = _strip_audio_block_markers(text or "")
        courses.append({
            "course_number": int(course_number),
            "sub_part_index": int(sub_idx or 0),
            "sub_part_name": sub_name or f"Cours {course_number}",
            "passe": int(passe or 0),
            "word_count": count_tts_spoken_words(clean_text),
            "stored_word_count": int(word_count or 0),
            "dirty": bool(dirty),
            "humanized": bool(humanized),
            "reviewed": bool(reviewed),
            "humanization_error": humanization_error or "",
            "review_error": review_error or "",
            "text": clean_text,
            "has_audio_marker": bool(marker_course_number),
        })
    return courses


def _save_reviewed_scripts_artifact(
    job: dict,
    folder_id: int,
    *,
    review_kind: str,
    review_label: str,
    summary: dict,
) -> None:
    artifact_job = {**(job or {}), "folder_id": folder_id}
    _save_content_artifact(
        job["platform_id"],
        folder_id,
        _CONTENT_REVIEWED_SCRIPTS_BLOB,
        _artifact_payload(
            artifact_job,
            "content_reviewed_scripts",
            {
                "last_review_kind": review_kind,
                "last_review_label": review_label,
                "review_summary": summary,
                "courses": _content_segments_artifact_snapshot(job["id"]),
            },
        ),
    )


# ─── Assemblage final ─────────────────────────────────────────────────────────

def _assemble_and_upload(folder_id, platform_id, job_id):
    """
    Concatène tous les segments complétés et uploade le texte final
    vers Azure comme document .txt dans le dossier.
    Retourne le nombre total de mots.
    """
    from services.azure_blob_service import (
        CONTAINER_AUDIOS,
        CONTAINER_DOCUMENTS,
        delete_blob,
        upload_blob,
    )

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

    full_text = _strip_audio_block_markers("\n\n".join(final_parts))
    total_words = count_tts_spoken_words(full_text)

    # Chemin blob unique pour éviter de laisser une version partielle écraser
    # la dernière version valide en cas d'échec d'upload.
    file_uuid = uuid_mod.uuid4()
    blob_path = f"platform-{platform_id}/folder-{folder_id}/{file_uuid}.txt"
    original_name = "script_tts_final.txt"

    upload_blob(CONTAINER_DOCUMENTS, blob_path, full_text.encode("utf-8"))

    # Remplacer les anciennes versions finales du script TTS pour garder un seul
    # document exploitable par cours.
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, filename, audio_filename
        FROM cours_documents
        WHERE folder_id = ?
          AND (doc_type = 'final_script' OR original_name LIKE 'cours_genere_%.txt')
    """, (folder_id,))
    old_final_docs = cursor.fetchall()
    for _doc_id, old_filename, old_audio_filename in old_final_docs:
        try:
            delete_blob(CONTAINER_DOCUMENTS, old_filename)
        except Exception as e:
            logger.warning(f"⚠️ Ancien script final non supprimé ({old_filename}): {e}")
        if old_audio_filename:
            try:
                delete_blob(CONTAINER_AUDIOS, old_audio_filename)
            except Exception as e:
                logger.warning(f"⚠️ Ancien audio final non supprimé ({old_audio_filename}): {e}")
    cursor.execute("""
        DELETE FROM cours_documents
        WHERE folder_id = ?
          AND (doc_type = 'final_script' OR original_name LIKE 'cours_genere_%.txt')
    """, (folder_id,))
    cursor.execute("""
        INSERT INTO cours_documents (folder_id, filename, original_name, doc_type, status)
        VALUES (?, ?, ?, 'final_script', 'uploaded')
    """, (folder_id, blob_path, original_name))
    conn.commit()
    conn.close()

    logger.info(f"✅ Texte final : {total_words} mots → {blob_path}")
    return total_words, original_name


def _build_structured_section_prompt(
    *,
    job: dict,
    course_plan: dict,
    section: dict,
    previous_course_summary: str,
    generated_so_far: str,
    module_content: str,
) -> str:
    prompt_parts = load_section_prompt_parts()
    base_style = prompt_parts["base_style"]
    section_contract = prompt_parts["section_contract"]
    target_words = int(section.get("target_words") or 500)
    min_words = max(120, int(target_words * 0.82))
    max_words = max(min_words + 50, int(target_words * 1.10))
    if section.get("kind") == "opening" and (generated_so_far or "").strip():
        generated_context_label = "Contenu principal déjà généré à cadrer dans cette ouverture"
        generated_context = _compact_words(generated_so_far, 900) or "(aucun)"
    else:
        generated_context_label = "Texte déjà généré dans cette partie interne"
        generated_context = _compact_words(generated_so_far, 900) or "(début de la partie)"
    scope_guard = _structured_section_scope_guard(section)
    teaching_beats_context = _section_teaching_beats_prompt(section)
    return f"""Tu écris UNE SECTION d'une partie audio professionnelle TTS-ready.

SOCLE GÉNÉRAL À RESPECTER :
{base_style}

CONTRAT DE SECTION :
{section_contract}

Tu dois respecter le plan verrouillé. N'écris que la section demandée : {_section_label(section)}.

Budget section :
- cible : {target_words} mots
- plage acceptable : {min_words} à {max_words} mots

Plan complet verrouillé de la partie interne :
{json.dumps(course_plan, ensure_ascii=False, indent=2)}

Section à écrire :
{json.dumps(section, ensure_ascii=False, indent=2)}

Frontière stricte de cette section :
{scope_guard}

Moments pédagogiques internes à couvrir :
{teaching_beats_context}

Contexte utile :
- Titre professionnel : {job.get('program_title') or ''}
- Intitulé journée : {job.get('folder_name') or ''}
- Rappel cours précédent : {previous_course_summary or '(aucun)'}
- {generated_context_label} : {generated_context}

Contenu source à utiliser :
{_compact_words(module_content or job.get('program_text') or '', 4500)}

Contraintes absolues :
- N'utilise jamais le mot "bloc" devant les élèves.
- N'utilise jamais les mots "horaire", "créneau" ou "planning" devant les élèves.
- Ne formule pas l'unité interne comme "ce cours", "premier cours", "cours actuel" ou "le cours qui nous occupe".
- Préfère "premier grand thème", "cette première partie", "ce chapitre", "cette séquence", "ce point" ou "cet axe" selon le contexte.
- Ne dis jamais "trois quarts d'heure", "45 minutes" ou une durée équivalente pour situer la séquence.
- Ne mentionne jamais d'heure précise, de durée de fichier, de budget mots, de nom de fichier ou de découpage technique.
- Ne dis jamais aux apprenants de ne pas se soucier des horaires : présente seulement la progression pédagogique.
- Pour une introduction seulement : ton naturel, posé, proche de "Bien. Maintenant que le cadre général est posé, on peut entrer dans le premier grand thème." Ne recopie pas cette phrase systématiquement. Pour une partie de développement, n'utilise pas ce modèle : entre directement dans l'axe demandé.
- Oral professionnel, clair, chaleureux, sans vocabulaire littéraire excessif.
- Pas de markdown, pas de titre écrit, pas de liste administrative froide.
- Les exemples non sourcés doivent être présentés comme fictifs ou hypothétiques
  avec une formulation naturelle. Si le texte dit déjà "Imaginons..." ou
  "Supposons que...", n'ajoute pas de phrase méta lourde.
- Ne fabrique pas de punchline artificielle et ne durcis pas une formulation
  prudente simplement pour produire plus d'impact. Une nuance comme "peut
  paraître" ou "peut donner l'impression" est correcte si elle sert le sens.
- Ne termine jamais le cours précédent.
- Ne devance pas une section suivante.
- Si cette section est une introduction, elle doit annoncer le plan avant tout exemple, avec une formulation naturelle du type : "Pour avancer progressivement, on va suivre trois grands axes. D'abord... Ensuite... Et enfin...".
- Si cette introduction est générée après le contenu principal, écris-la quand même comme le tout début de la partie, jamais comme une suite.
- Si cette section est une partie, elle doit développer seulement cette partie et apporter une idée nouvelle identifiable. Elle ne doit jamais refaire l'accueil, le cadrage de la journée, l'annonce des thèmes de la journée ou le plan global déjà porté par l'introduction.
- Si cette section contient des teaching_beats, couvre-les dans l'ordre avec naturel. Ne les nomme jamais comme des beats, slides, anchors, PowerPoint ou templates.
- Si cette section est une conclusion, elle doit récapituler sans ouvrir un nouveau développement.
- Après l'annonce Q/R ou la mention du tchat, aucun nouveau développement.

Réponds uniquement avec le texte oral de cette section."""


def _structured_section_scope_guard(section: dict) -> str:
    kind = section.get("kind")
    if kind == "opening":
        return (
            "- Tu écris l'unique ouverture de cette partie interne.\n"
            "- C'est le seul endroit où tu peux accueillir, cadrer la journée, "
            "annoncer le nouveau thème, l'objectif et les axes.\n"
            "- Après cette ouverture, le développement commencera directement : "
            "n'écris pas une ouverture qui appelle une seconde ouverture."
        )
    if kind == "part":
        part_number = int(section.get("part_number") or 0)
        if part_number == 1:
            return (
                "- Tu écris le premier axe de développement, pas l'ouverture.\n"
                "- L'ouverture a déjà accueilli, cadré la journée, présenté le thème, "
                "l'objectif et le plan. Ne répète aucun de ces éléments.\n"
                "- Ne commence pas par 'Bien, maintenant que le cadre général est posé', "
                "'on peut entrer dans le premier grand thème', 'cette journée est cruciale', "
                "ou une formule équivalente.\n"
                "- Commence directement par le contenu du premier axe : une phrase courte "
                "du type 'Commençons par ce qui change concrètement...' suffit."
            )
        return (
            f"- Tu écris l'axe {part_number} de développement, pas une nouvelle introduction.\n"
            "- Fais une transition courte depuis l'axe précédent, puis développe l'idée prévue.\n"
            "- Ne réannonce pas le thème général, la journée, l'objectif global ou le plan complet."
        )
    if kind == "course_conclusion":
        return (
            "- Tu écris seulement la conclusion de cette partie interne.\n"
            "- Récapitule et ferme proprement avant le temps de questions-réponses.\n"
            "- Ne lance pas un nouveau thème et ne refais pas d'introduction."
        )
    if kind == "day_conclusion":
        return (
            "- Tu écris seulement la conclusion globale de journée.\n"
            "- Fais une synthèse de journée, puis ferme. Ne crée pas un nouveau développement."
        )
    return "- Respecte strictement le périmètre de la section demandée."


def _section_teaching_beats_prompt(section: dict) -> str:
    beats = section.get("teaching_beats") if isinstance(section.get("teaching_beats"), list) else []
    if not beats:
        return "- Aucun teaching beat spécifique pour cette section."
    compact = []
    for beat in beats:
        if not isinstance(beat, dict):
            continue
        anchor = beat.get("slide_anchor") if isinstance(beat.get("slide_anchor"), dict) else {}
        compact.append({
            "beat_id": beat.get("beat_id"),
            "type": beat.get("type"),
            "role": beat.get("role"),
            "spoken_requirement": beat.get("spoken_requirement"),
            "slide_anchor": {
                "enabled": bool(anchor.get("enabled")),
                "template_type": anchor.get("template_type"),
                "visual_goal": anchor.get("visual_goal"),
                "items_expected": anchor.get("items_expected"),
            },
        })
    return json.dumps(compact, ensure_ascii=False, indent=2)


def _part_section_opening_leak_evidence(section: dict, text: str) -> str:
    if section.get("kind") != "part":
        return ""
    opening_window = _compact_words(text or "", 220)
    if not opening_window:
        return ""
    match = _PART_SECTION_OPENING_LEAK_RE.search(opening_window)
    if not match:
        return ""
    return _compact_words(opening_window[max(0, match.start() - 90):match.end() + 130], 42)


def _repair_part_section_opening_leak(
    *,
    job: dict,
    course_plan: dict,
    section: dict,
    section_text: str,
    module_content: str,
    model=None,
) -> str:
    target_words = int(section.get("target_words") or 500)
    prompt = f"""Tu corriges une section de développement audio.

Problème : cette section refait une ouverture de journée ou de thème alors que l'ouverture existe déjà.

Objectif :
- garder le fond utile ;
- supprimer l'accueil, le cadrage de journée, l'annonce des thèmes de la journée, le programme annuel et le plan global répété ;
- commencer directement par le contenu de l'axe demandé ;
- ne pas ajouter de markdown ni de titre écrit ;
- ne pas mentionner horaires, créneaux, planning, durée ou budget mots.

Section demandée :
{json.dumps(section, ensure_ascii=False, indent=2)}

Plan verrouillé :
{json.dumps(course_plan, ensure_ascii=False, indent=2)}

Titre professionnel : {job.get('program_title') or ''}
Intitulé journée : {job.get('folder_name') or ''}

Contenu source utile :
{_compact_words(module_content or job.get('program_text') or '', 2500)}

Texte à corriger :
{section_text}

Réponds uniquement avec la section corrigée."""
    try:
        raw = _anthropic_post(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=_structured_generation_max_tokens(target_words),
            model=model,
        )
        repaired = _fit_generated_section_to_budget(raw, target_words)
        if _part_section_opening_leak_evidence(section, repaired):
            return section_text
        return repaired
    except Exception as exc:
        logger.warning(
            "⚠️ Réparation de double ouverture ignorée course=%s part=%s: %s",
            course_plan.get("course_number"),
            section.get("part_number"),
            str(exc)[:220],
        )
        return section_text


def _fit_generated_section_to_budget(text: str, target_words: int) -> str:
    text = _sanitize_learner_facing_text(_clean_llm_text(text))
    target_words = int(target_words or 0)
    if target_words <= 0:
        return text
    max_words = int(target_words * 1.14)
    if count_tts_spoken_words(text) > max_words:
        text = _trim_text_to_max_spoken_words(text, max_words)
    return text.strip()


def _generate_structured_section(
    *,
    job: dict,
    course_plan: dict,
    section: dict,
    previous_course_summary: str,
    generated_so_far: str,
    module_content: str,
    model=None,
) -> str:
    target_words = int(section.get("target_words") or 500)
    prompt = _build_structured_section_prompt(
        job=job,
        course_plan=course_plan,
        section=section,
        previous_course_summary=previous_course_summary,
        generated_so_far=generated_so_far,
        module_content=module_content,
    )
    raw = _anthropic_post(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=_structured_generation_max_tokens(target_words),
        model=model,
    )
    section_text = _fit_generated_section_to_budget(raw, target_words)
    if _part_section_opening_leak_evidence(section, section_text):
        logger.info(
            "PIPELINE_STRUCTURED_SECTION_SCOPE_REPAIR formation_job_id=%s content_job_id=%s course=%s part=%s",
            job.get("formation_job_id"),
            job.get("id"),
            course_plan.get("course_number"),
            section.get("part_number"),
        )
        section_text = _repair_part_section_opening_leak(
            job=job,
            course_plan=course_plan,
            section=section,
            section_text=section_text,
            module_content=module_content,
            model=model,
        )
    return section_text


def _ethical_micro_review_enabled() -> bool:
    value = str(os.getenv("FORMATION_ETHICAL_MICRO_REVIEW_ENABLED", "1")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _load_ethical_micro_rules_text() -> str:
    path = _prompt_file_path("reviews", "compliance-rules.json")
    try:
        mtime = os.path.getmtime(path)
        if _ETHICAL_MICRO_RULES_CACHE["mtime"] == mtime and _ETHICAL_MICRO_RULES_CACHE["text"]:
            return _ETHICAL_MICRO_RULES_CACHE["text"]
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        blocks = []
        for rule in data.get("rules") or []:
            if not isinstance(rule, dict):
                continue
            if rule.get("scope") != "ethics_compliance":
                continue
            body = str(rule.get("body") or "").strip()
            if body:
                blocks.append(body)
        if not blocks:
            raise ValueError("aucune règle ethics_compliance trouvée")
        rules_text = (
            f"SOURCE MODULAIRE: compliance-rules.json · version {data.get('version') or 'unknown'} "
            f"· scope ethics_compliance · micro-review {_ETHICAL_MICRO_RULESET_VERSION}\n\n"
            + "\n\n".join(blocks)
        )
        _ETHICAL_MICRO_RULES_CACHE["mtime"] = mtime
        _ETHICAL_MICRO_RULES_CACHE["text"] = rules_text
        return rules_text
    except Exception as exc:
        logger.warning("⚠️ Règles micro-éthique JSON indisponibles, fallback règles #14/#15: %s", exc)
        return _extract_rules_for_group(_load_review_rules(), _ETHICAL_MICRO_RULE_IDS)


def _ethical_micro_max_patches(section: dict) -> int:
    default = 8 if (section or {}).get("kind") == "course_calibrated" else 3
    return _env_int("FORMATION_ETHICAL_MICRO_REVIEW_MAX_PATCHES", default, min_value=1)


def _build_ethical_micro_review_prompt(*, course_plan: dict, section: dict, section_text: str, rules_text: str) -> str:
    contract = _load_prompt_file("reviews", "ethical-micro-review.md")
    max_patches = _ethical_micro_max_patches(section)
    return f"""Tu es reviewer de conformité ÉTHIQUE en micro-passe.

CONTRAT :
{contract}

Tu vérifies uniquement les règles #14 et #15 du scope ethics_compliance.
Ignore tout le reste : style oral, humanisation, plan, budget, structure, slides,
anchors, templates, horaires, transitions, répétitions ou préférence éditoriale.

Contexte pédagogique minimal :
- Cours interne : {course_plan.get('course_number')} / 7
- Titre : {course_plan.get('course_title') or ''}
- Section : {_section_label(section)}

Section JSON :
{json.dumps(section, ensure_ascii=False, indent=2)}

Format de sortie strict, JSON valide uniquement :
{{
  "patches": [
    {{
      "original": "phrase EXACTE à remplacer, copie verbatim",
      "replacement": "correction minimale, même sens pédagogique",
      "rule_violated": "#14",
      "reason": "raison brève"
    }}
  ]
}}

Contraintes impératives :
- Maximum {max_patches} patches.
- `original` doit être trouvable tel quel dans le texte, une seule fois.
- `replacement` corrige uniquement la violation éthique, sans enrichir, sans restructurer, sans changer la pédagogie.
- N'ajoute pas de nouvelle idée, pas de nouveau chapitre, pas de mention de slide/PowerPoint/template/anchor/teaching beat.
- Si la section est conforme pour #14 et #15, renvoie exactement {{"patches": []}}.
- `rule_violated` doit être "#14" ou "#15".

RÈGLES ÉTHIQUES À VÉRIFIER :
{rules_text}

TEXTE DE LA SECTION :
{section_text}

JSON :"""


def _ethical_lexical_scan_enabled() -> bool:
    value = str(os.getenv("FORMATION_ETHICAL_LEXICAL_SCAN_ENABLED", "1")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _load_ethical_lexical_terms() -> dict:
    path = _prompt_file_path("reviews", "ethical-lexical-terms.json")
    try:
        mtime = os.path.getmtime(path)
        if _ETHICAL_LEXICAL_TERMS_CACHE["mtime"] == mtime and _ETHICAL_LEXICAL_TERMS_CACHE["data"]:
            return _ETHICAL_LEXICAL_TERMS_CACHE["data"]
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data.get("rules"), list):
            raise ValueError("clé rules absente")
        _ETHICAL_LEXICAL_TERMS_CACHE["mtime"] = mtime
        _ETHICAL_LEXICAL_TERMS_CACHE["data"] = data
        return data
    except Exception as exc:
        logger.warning("⚠️ Liste lexicale éthique indisponible: %s", exc)
        return {"version": "missing", "rules": []}


def _ethical_lexical_pattern(term: str):
    escaped = re.escape(str(term or "").strip())
    if not escaped:
        return None
    escaped = escaped.replace(r"\ ", r"\s+")
    return re.compile(r"(?<![\wÀ-ÿ-])" + escaped + r"(?![\wÀ-ÿ-])", re.IGNORECASE)


def _ethical_lexical_excerpt(text: str, start: int, end: int, window: int = 170) -> str:
    source = text or ""
    left = max(0, int(start or 0) - window)
    right = min(len(source), int(end or 0) + window)
    excerpt = re.sub(r"\s+", " ", source[left:right]).strip()
    return _compact_words(excerpt, 58)


def _ethical_lexical_assurance_allowed(text: str, start: int, end: int) -> bool:
    window = (text or "")[max(0, start - 90): min(len(text or ""), end + 90)].lower()
    confidence_markers = [
        "prendre de l'assurance",
        "prend de l'assurance",
        "gagner en assurance",
        "gagne en assurance",
        "avec assurance",
        "avoir de l'assurance",
        "a de l'assurance",
        "manque d'assurance",
        "assurance personnelle",
        "parler avec assurance",
        "répondre avec assurance",
        "plus d'assurance",
        "son assurance",
        "ton assurance",
    ]
    sector_markers = [
        "contrat",
        "souscrire",
        "prime",
        "police",
        "sinistre",
        "assureur",
        "assuré",
        "assurantiel",
        "banque",
        "bancaire",
        "crédit",
        "emprunt",
    ]
    return any(marker in window for marker in confidence_markers) and not any(
        marker in window for marker in sector_markers
    )


def _ethical_lexical_match_allowed(term: str, text: str, start: int, end: int) -> bool:
    normalized = re.sub(r"\s+", " ", str(term or "").strip().lower())
    if normalized == "assurance":
        return _ethical_lexical_assurance_allowed(text, start, end)
    return False


def _scan_ethical_lexical_findings(text: str, *, max_findings: int | None = None) -> list[dict]:
    if not _ethical_lexical_scan_enabled() or not (text or "").strip():
        return []
    data = _load_ethical_lexical_terms()
    limit = max_findings or _env_int("FORMATION_ETHICAL_LEXICAL_MAX_FINDINGS", 8, min_value=1)
    findings = []
    seen = set()
    for rule in data.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        try:
            rule_id = int(rule.get("rule_id") or 0)
        except Exception:
            continue
        if rule_id not in _ETHICAL_MICRO_RULE_IDS:
            continue
        label = str(rule.get("label") or f"Règle #{rule_id}").strip()
        for term in rule.get("terms") or []:
            pattern = _ethical_lexical_pattern(str(term or ""))
            if pattern is None:
                continue
            for match in pattern.finditer(text or ""):
                if _ethical_lexical_match_allowed(str(term), text, match.start(), match.end()):
                    continue
                key = (rule_id, match.start(), match.end(), match.group(0).lower())
                if key in seen:
                    continue
                seen.add(key)
                findings.append({
                    "rule_id": rule_id,
                    "rule": f"#{rule_id}",
                    "rule_label": label,
                    "term": str(term),
                    "match": match.group(0),
                    "start": match.start(),
                    "end": match.end(),
                    "excerpt": _ethical_lexical_excerpt(text, match.start(), match.end()),
                })
                if len(findings) >= limit:
                    return findings
    return findings


def _build_ethical_lexical_rewrite_prompt(
    *,
    course_plan: dict,
    section: dict,
    section_text: str,
    findings: list[dict],
) -> str:
    finding_rules = sorted({int(f.get("rule_id") or 0) for f in findings if f.get("rule_id")})
    rules_text = _extract_rules_for_group(_load_review_rules(), finding_rules) if finding_rules else ""
    max_patches = min(
        len(findings),
        _env_int("FORMATION_ETHICAL_LEXICAL_MAX_PATCHES", _ethical_micro_max_patches(section), min_value=1),
    )
    return f"""Tu es reviewer de conformité ÉTHIQUE en passe lexicale déterministe.

La micro-conformité IA a déjà été passée. Le scan déterministe a ensuite trouvé
des termes interdits qui restent dans le texte oral. Tu dois corriger les
passages détectés en reformulant la situation, l'exemple ou l'explication.

Important :
- Ne supprime jamais seulement le mot interdit.
- Remplace le passage par une formulation naturelle qui change le contexte si nécessaire.
- Garde le même objectif pédagogique.
- Ne crée pas de nouvelle partie, slide, ancre, template ou métadonnée.
- `original` doit être une phrase ou un court passage EXACT, copié du texte.
- `replacement` doit être entendable par les apprenants et conforme aux règles #14 et #15.
- Maximum {max_patches} patches.

Contexte pédagogique :
- Cours interne : {course_plan.get('course_number')} / 7
- Titre : {course_plan.get('course_title') or ''}
- Section : {_section_label(section)}

Détections lexicales à traiter :
{json.dumps(findings[:max_patches], ensure_ascii=False, indent=2)}

Règles concernées :
{rules_text}

Format de sortie strict, JSON valide uniquement :
{{
  "patches": [
    {{
      "original": "phrase ou passage EXACT à remplacer",
      "replacement": "reformulation contextuelle conforme",
      "rule_violated": "#2",
      "reason": "terme interdit détecté et contexte reformulé"
    }}
  ]
}}

TEXTE DE LA SECTION :
{section_text}

JSON :"""


def _lexical_patch_meta(patch: dict, findings: list[dict]) -> dict:
    enriched = {**(patch or {})}
    enriched["source"] = "ethical_lexical_scan"
    original = str(enriched.get("original") or "")
    matched_finding = None
    for finding in findings:
        if str(finding.get("match") or "").lower() in original.lower():
            matched_finding = finding
            break
    if matched_finding:
        enriched["term"] = matched_finding.get("match") or matched_finding.get("term")
        enriched["lexical_rule_id"] = matched_finding.get("rule_id")
    return enriched


def _residual_lexical_rejection(finding: dict) -> dict:
    return {
        "original": finding.get("excerpt") or finding.get("match") or "",
        "replacement": "",
        "rule_violated": finding.get("rule") or f"#{finding.get('rule_id') or '?'}",
        "reason": (
            f"Terme lexical interdit encore détecté après repasse : "
            f"{finding.get('match') or finding.get('term')}"
        ),
        "source": "ethical_lexical_scan",
        "term": finding.get("match") or finding.get("term"),
        "lexical_rule_id": finding.get("rule_id"),
        "reject_reason": "residual_after_lexical_rewrite",
    }


def _run_ethical_lexical_rewrite_for_section(
    *,
    job: dict,
    course_plan: dict,
    section: dict,
    section_text: str,
    model=None,
) -> dict:
    findings = _scan_ethical_lexical_findings(section_text)
    if not findings:
        return {
            "text": section_text,
            "findings": [],
            "residual_findings": [],
            "applied": [],
            "rejected": [],
            "error": "",
        }

    prompt = _build_ethical_lexical_rewrite_prompt(
        course_plan=course_plan,
        section=section,
        section_text=section_text,
        findings=findings,
    )
    max_tokens = _env_int("FORMATION_ETHICAL_LEXICAL_REWRITE_MAX_TOKENS", 1800, min_value=500)
    try:
        raw = _anthropic_post(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            model=model,
        )
    except Exception as exc:
        rejected = [_residual_lexical_rejection(f) for f in findings]
        for item in rejected:
            item["reject_reason"] = f"lexical_rewrite_error: {str(exc)[:180]}"
        logger.warning(
            "PIPELINE_ETHICAL_LEXICAL_REWRITE_ERROR formation_job_id=%s content_job_id=%s course=%s section=%s error=%s",
            job.get("formation_job_id"),
            job.get("id"),
            course_plan.get("course_number"),
            _section_label(section),
            str(exc)[:220],
        )
        return {
            "text": section_text,
            "findings": findings,
            "residual_findings": findings,
            "applied": [],
            "rejected": rejected,
            "error": str(exc),
        }

    patches, parse_error = _parse_patches_response(raw)
    if parse_error:
        rejected = [_residual_lexical_rejection(f) for f in findings]
        for item in rejected:
            item["reject_reason"] = f"lexical_parse_error: {parse_error[:180]}"
        return {
            "text": section_text,
            "findings": findings,
            "residual_findings": findings,
            "applied": [],
            "rejected": rejected,
            "error": parse_error,
        }

    scoped_patches = [
        _lexical_patch_meta(patch, findings)
        for patch in patches
        if (_patch_rule_number(patch) in _ETHICAL_MICRO_RULE_IDS)
    ]
    max_patches = min(
        len(findings),
        _env_int("FORMATION_ETHICAL_LEXICAL_MAX_PATCHES", _ethical_micro_max_patches(section), min_value=1),
    )
    scoped_patches = scoped_patches[:max_patches]
    candidate, applied, rejected = _apply_patches(section_text, scoped_patches)
    candidate, applied, budget_rejected = _apply_review_budget_guard(
        section_text,
        candidate,
        applied,
        "compliance",
    )
    rejected = rejected + budget_rejected
    residual_findings = _scan_ethical_lexical_findings(candidate)
    rejected = rejected + [_residual_lexical_rejection(f) for f in residual_findings]
    return {
        "text": candidate,
        "findings": findings,
        "residual_findings": residual_findings,
        "applied": applied,
        "rejected": rejected,
        "error": "",
    }


def _patch_rule_number(patch: dict) -> int | None:
    match = _re.search(r"#?\s*(\d+)", str((patch or {}).get("rule_violated") or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _micro_review_patch_for_report(patch: dict, status: str) -> dict:
    return {
        "rule": str((patch or {}).get("rule_violated") or (patch or {}).get("rule") or "?"),
        "reason": str((patch or {}).get("reason") or "")[:500],
        "original": str((patch or {}).get("original") or ""),
        "replacement": str((patch or {}).get("replacement") or ""),
        "status": status,
        "reject_reason": (patch or {}).get("reject_reason"),
        "source": (patch or {}).get("source") or "ethical_micro_review",
        "term": (patch or {}).get("term"),
        "lexical_rule_id": (patch or {}).get("lexical_rule_id"),
    }


def _record_ethical_micro_review(job: dict, record: dict) -> None:
    try:
        records = job.setdefault("_ethical_micro_review_records", [])
        records.append(record)
    except Exception:
        pass


def _ethical_micro_review_record(
    *,
    job: dict,
    course_plan: dict,
    section: dict,
    status: str,
    original_text: str,
    final_text: str | None = None,
    proposed: int = 0,
    applied: list | None = None,
    rejected: list | None = None,
    lexical_findings: list | None = None,
    lexical_residual_findings: list | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
) -> dict:
    applied = applied or []
    rejected = rejected or []
    lexical_findings = lexical_findings or []
    lexical_residual_findings = lexical_residual_findings or []
    return {
        "course_number": int(course_plan.get("course_number") or 0),
        "course_title": course_plan.get("course_title") or f"Cours {course_plan.get('course_number') or '?'}",
        "section_label": _section_label(section),
        "section": section,
        "status": status,
        "proposed": int(proposed or 0),
        "patches_applied": len(applied),
        "patches_rejected": len(rejected),
        "patches_detail": (
            [_micro_review_patch_for_report(p, "applied") for p in applied]
            + [_micro_review_patch_for_report(p, "rejected") for p in rejected]
        ),
        "original_text": original_text or "",
        "final_text": final_text if final_text is not None else (original_text or ""),
        "error": str(error or "")[:700],
        "lexical_findings": lexical_findings,
        "lexical_findings_count": len(lexical_findings),
        "lexical_residual_findings": lexical_residual_findings,
        "lexical_residual_count": len(lexical_residual_findings),
        "duration_ms": duration_ms,
        "rules_scope": "ethics_compliance",
        "rules": [f"#{rid}" for rid in _ETHICAL_MICRO_RULE_IDS],
        "ruleset_version": _ETHICAL_MICRO_RULESET_VERSION,
    }


def _ethical_micro_review_summary(records: list[dict]) -> dict:
    return {
        "sections_reviewed": len(records),
        "sections_clean": sum(1 for r in records if r.get("status") == "clean"),
        "sections_patched": sum(1 for r in records if r.get("status") == "patched"),
        "sections_rejected": sum(1 for r in records if r.get("status") == "rejected"),
        "sections_failed": sum(1 for r in records if r.get("status") in {"error", "parse_error"}),
        "patches_proposed": sum(int(r.get("proposed") or 0) for r in records),
        "patches_applied": sum(int(r.get("patches_applied") or 0) for r in records),
        "patches_rejected": sum(int(r.get("patches_rejected") or 0) for r in records),
        "lexical_findings": sum(int(r.get("lexical_findings_count") or 0) for r in records),
        "lexical_residual_findings": sum(int(r.get("lexical_residual_count") or 0) for r in records),
    }


def _sorted_ethical_micro_review_records(job: dict) -> list[dict]:
    records = list(job.get("_ethical_micro_review_records") or [])
    return sorted(
        records,
        key=lambda r: (
            int(r.get("course_number") or 0),
            int(((r.get("section") or {}).get("part_number") or 0)),
            str((r.get("section") or {}).get("section_kind") or ""),
            str(r.get("section_label") or ""),
        ),
    )


def _run_ethical_micro_review_for_section(
    *,
    job: dict,
    course_plan: dict,
    section: dict,
    section_text: str,
    model=None,
) -> str:
    if not _ethical_micro_review_enabled() or not (section_text or "").strip():
        return section_text

    rules_text = _load_ethical_micro_rules_text()
    if not rules_text.strip():
        return section_text

    prompt = _build_ethical_micro_review_prompt(
        course_plan=course_plan,
        section=section,
        section_text=section_text,
        rules_text=rules_text,
    )
    default_max_tokens = 2600 if section.get("kind") == "course_calibrated" else 1600
    max_tokens = _env_int("FORMATION_ETHICAL_MICRO_REVIEW_MAX_TOKENS", default_max_tokens, min_value=400)
    started = time.time()
    try:
        raw = _anthropic_post(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            model=model,
        )
    except Exception as exc:
        logger.warning(
            "PIPELINE_ETHICAL_MICRO_REVIEW_ERROR formation_job_id=%s content_job_id=%s course=%s section=%s error=%s",
            job.get("formation_job_id"),
            job.get("id"),
            course_plan.get("course_number"),
            _section_label(section),
            str(exc)[:220],
        )
        _record_ethical_micro_review(
            job,
            _ethical_micro_review_record(
                job=job,
                course_plan=course_plan,
                section=section,
                status="error",
                original_text=section_text,
                error=str(exc),
                duration_ms=int((time.time() - started) * 1000),
            ),
        )
        return section_text

    patches, parse_error = _parse_patches_response(raw)
    if parse_error:
        logger.warning(
            "PIPELINE_ETHICAL_MICRO_REVIEW_PARSE_ERROR formation_job_id=%s content_job_id=%s course=%s section=%s error=%s",
            job.get("formation_job_id"),
            job.get("id"),
            course_plan.get("course_number"),
            _section_label(section),
            parse_error,
        )
        _record_ethical_micro_review(
            job,
            _ethical_micro_review_record(
                job=job,
                course_plan=course_plan,
                section=section,
                status="parse_error",
                original_text=section_text,
                error=parse_error,
                duration_ms=int((time.time() - started) * 1000),
            ),
        )
        return section_text

    max_patches = _ethical_micro_max_patches(section)
    scoped_patches = [
        patch
        for patch in patches
        if (_patch_rule_number(patch) in _ETHICAL_MICRO_RULE_IDS)
    ][:max_patches]
    candidate = section_text
    applied = []
    rejected = []
    if scoped_patches:
        candidate, applied, rejected = _apply_patches(section_text, scoped_patches)
        candidate, applied, budget_rejected = _apply_review_budget_guard(
            section_text,
            candidate,
            applied,
            "compliance",
        )
        rejected = rejected + budget_rejected

    lexical_result = _run_ethical_lexical_rewrite_for_section(
        job=job,
        course_plan=course_plan,
        section=section,
        section_text=candidate,
        model=model,
    )
    lexical_findings = lexical_result.get("findings") or []
    lexical_residual_findings = lexical_result.get("residual_findings") or []
    if lexical_result.get("applied"):
        candidate = lexical_result.get("text") or candidate
    applied = applied + list(lexical_result.get("applied") or [])
    rejected = rejected + list(lexical_result.get("rejected") or [])
    proposed_count = len(scoped_patches) + len(lexical_findings)

    if applied:
        logger.info(
            "PIPELINE_ETHICAL_MICRO_REVIEW_PATCHED formation_job_id=%s content_job_id=%s course=%s section=%s proposed=%s applied=%s rejected=%s lexical=%s residual=%s duration_ms=%s",
            job.get("formation_job_id"),
            job.get("id"),
            course_plan.get("course_number"),
            _section_label(section),
            proposed_count,
            len(applied),
            len(rejected),
            len(lexical_findings),
            len(lexical_residual_findings),
            int((time.time() - started) * 1000),
        )
        _record_ethical_micro_review(
            job,
            _ethical_micro_review_record(
                job=job,
                course_plan=course_plan,
                section=section,
                status="patched",
                original_text=section_text,
                final_text=candidate,
                proposed=proposed_count,
                applied=applied,
                rejected=rejected,
                lexical_findings=lexical_findings,
                lexical_residual_findings=lexical_residual_findings,
                error=lexical_result.get("error") or "",
                duration_ms=int((time.time() - started) * 1000),
            ),
        )
        return _sanitize_learner_facing_text(candidate)

    if not rejected and not proposed_count:
        logger.info(
            "PIPELINE_ETHICAL_MICRO_REVIEW_CLEAN formation_job_id=%s content_job_id=%s course=%s section=%s duration_ms=%s",
            job.get("formation_job_id"),
            job.get("id"),
            course_plan.get("course_number"),
            _section_label(section),
            int((time.time() - started) * 1000),
        )
        _record_ethical_micro_review(
            job,
            _ethical_micro_review_record(
                job=job,
                course_plan=course_plan,
                section=section,
                status="clean",
                original_text=section_text,
                proposed=0,
                duration_ms=int((time.time() - started) * 1000),
            ),
        )
        return section_text

    logger.info(
        "PIPELINE_ETHICAL_MICRO_REVIEW_REJECTED formation_job_id=%s content_job_id=%s course=%s section=%s proposed=%s rejected=%s lexical=%s residual=%s duration_ms=%s",
        job.get("formation_job_id"),
        job.get("id"),
        course_plan.get("course_number"),
        _section_label(section),
        proposed_count,
        len(rejected),
        len(lexical_findings),
        len(lexical_residual_findings),
        int((time.time() - started) * 1000),
    )
    _record_ethical_micro_review(
        job,
        _ethical_micro_review_record(
            job=job,
            course_plan=course_plan,
            section=section,
            status="rejected",
            original_text=section_text,
            proposed=proposed_count,
            rejected=rejected,
            lexical_findings=lexical_findings,
            lexical_residual_findings=lexical_residual_findings,
            error=lexical_result.get("error") or "",
            duration_ms=int((time.time() - started) * 1000),
        ),
    )
    return section_text


def _summarize_previous_course_for_structured(course_text: str, model=None) -> str:
    text = _compact_words(course_text or "", 900)
    if not text:
        return ""
    prompt = f"""Résume en 2 phrases maximum cette partie pour permettre à la partie suivante de faire un rappel bref.
Ne parle pas de fichier, d'audio ou de bloc.

COURS :
{text}

Réponds uniquement avec le résumé oral court."""
    try:
        return _sanitize_learner_facing_text(_clean_llm_text(_anthropic_post(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=350,
            model=model,
        )))
    except Exception:
        return _compact_words(course_text, 80)


def _calibrate_structured_course_text(course_plan: dict, text: str, model=None) -> tuple[str, dict]:
    target_words = int(course_plan.get("target_words") or 0)
    block = {
        "bloc_number": int(course_plan.get("course_number") or 0),
        "filename": course_plan.get("filename"),
        "duration_min": course_plan.get("duration_minutes"),
        "target_words": target_words,
        "min_words": _structured_course_min_words(target_words),
        "max_words": target_words,
        "word_budget": target_words,
        "role": course_plan.get("pedagogical_role") or "",
    }
    calibrated, result = _calibrate_single_audio_block(
        block=block,
        text=_sanitize_learner_facing_text(text),
        model=model,
        max_iterations=int(os.getenv("FORMATION_STRUCTURED_COURSE_CALIBRATION_ITERATIONS", "6") or "6"),
        day_context=(
            "Plan structuré verrouillé : respecter l'architecture du cours, "
            "compléter/réduire uniquement avec du contenu pertinent, et ne "
            "jamais utiliser le mot bloc devant les élèves.\n\n"
            f"{json.dumps(course_plan, ensure_ascii=False, indent=2)}"
        ),
    )
    return _sanitize_learner_facing_text(calibrated), result


_PLAN_ADHERENCE_REVIEW_VERSION = "2026-05-28-plan-adherence-v6-early"


def _structured_course_budget_status(course_plan: dict, text: str) -> dict:
    target_words = int(course_plan.get("target_words") or 0)
    words = count_tts_spoken_words(text)
    min_words = _structured_course_min_words(target_words) if target_words else 0
    max_words = target_words
    if target_words <= 0:
        status = "unknown"
        ok = True
    elif words < min_words:
        status = "too_short"
        ok = False
    elif words > max_words:
        status = "too_long"
        ok = False
    else:
        status = "ok"
        ok = True
    return {
        "ok": ok,
        "status": status,
        "words": words,
        "min_words": min_words,
        "max_words": max_words,
        "target_words": target_words,
    }


def _structured_section_budget_status(section: dict, text: str) -> dict:
    target_words = int(section.get("target_words") or 0)
    words = count_tts_spoken_words(text)
    min_words = _structured_section_min_words(target_words) if target_words else 0
    max_words = target_words
    if target_words <= 0:
        status = "unknown"
        ok = True
        delta = 0
    elif words < min_words:
        status = "too_short"
        ok = False
        delta = min_words - words
    elif words > max_words:
        status = "too_long"
        ok = False
        delta = words - max_words
    else:
        status = "ok"
        ok = True
        delta = 0
    return {
        "ok": ok,
        "status": status,
        "words": words,
        "min_words": min_words,
        "max_words": max_words,
        "target_words": target_words,
        "delta": delta,
    }


def _build_structured_section_budget_prompt(
    *,
    job: dict,
    course_plan: dict,
    section: dict,
    current_text: str,
    status: dict,
    module_content: str,
    direction: str,
) -> str:
    budget_contract = load_budget_rewrite_contract()
    section_label = _section_label(section)
    action = (
        "réduire cette section sans perdre ses idées essentielles"
        if direction == "shorten"
        else "enrichir cette section avec de vraies valeurs ajoutées pédagogiques"
    )
    if direction == "shorten":
        direction_rules = (
            "- Supprime les répétitions, les reformulations faibles et les exemples trop longs.\n"
            "- Préserve les notions, les transitions utiles et la fonction de la section.\n"
        )
    else:
        direction_rules = (
            "- Ajoute de vraies notions utiles : nuance métier, méthode concrète, erreur fréquente, contre-exemple, mini-cas fictif, clarification ou lien terrain.\n"
            "- Ne rends pas le texte simplement plus verbeux : chaque ajout doit avoir une valeur pédagogique identifiable.\n"
            "- Respecte les teaching beats et les anchors/slides du plan : enrichis ce qui est prévu, ne crée pas une trajectoire parallèle.\n"
            "- Ne modifie pas le plan JSON et ne déplace pas le rôle de cette section vers une autre section.\n"
        )
    return f"""Tu calibres une section d'un cours audio TTS Fish Audio.

CONTRAT DE RÉÉCRITURE BUDGET :
{budget_contract}

Mission : {action}.
Tu dois réécrire uniquement la section demandée, pas le cours complet.
Le texte final doit être oral, fluide, TTS-ready, sans markdown ni titre écrit.

Budget section :
- Section : {section_label}
- Cible : {status.get('target_words')} mots parlés
- Plage acceptée : {status.get('min_words')} à {status.get('max_words')} mots parlés
- Texte actuel : {status.get('words')} mots
- Écart à corriger : {status.get('delta')} mots

Plan complet verrouillé :
{json.dumps(course_plan, ensure_ascii=False, indent=2)}

Section verrouillée à calibrer :
{json.dumps(section, ensure_ascii=False, indent=2)}

Frontière stricte de cette section :
{_structured_section_scope_guard(section)}

Moments pédagogiques internes à couvrir :
{_section_teaching_beats_prompt(section)}

Contexte utile :
- Titre professionnel : {job.get('program_title') or ''}
- Intitulé journée : {job.get('folder_name') or ''}

Contenu source à utiliser si tu ajoutes des notions :
{_compact_words(module_content or job.get('program_text') or '', 4500)}

Contraintes absolues :
- Ne mentionne jamais budget mots, fichier, durée, horaire, créneau, planning ou découpage technique.
- N'utilise jamais le mot "bloc" devant les élèves.
- Les exemples non sourcés doivent être fictifs ou hypothétiques avec une
  formulation naturelle. Si le texte dit déjà "Imaginons..." ou "Supposons que...",
  n'ajoute pas de phrase méta lourde.
- Pour une partie de développement, ne refais pas l'accueil, le cadrage de journée ou le plan global.
- Pour une conclusion, récapitule sans ouvrir un nouveau développement.
- Après une annonce Q/R, tchat ou fin de partie, aucun nouveau développement.
- Le résultat doit finir entre {status.get('min_words')} et {status.get('max_words')} mots parlés.
{direction_rules}

Texte actuel de la section :
{current_text}

Réponds uniquement avec le texte oral calibré de cette section."""


def _calibrate_structured_section_text(
    *,
    job: dict,
    course_plan: dict,
    section: dict,
    text: str,
    module_content: str,
    model=None,
) -> tuple[str, dict]:
    current_text = _sanitize_learner_facing_text(text)
    history = []
    changed = False
    max_iterations = _env_int("FORMATION_STRUCTURED_SECTION_CALIBRATION_ITERATIONS", 4, min_value=1)
    max_iterations = min(8, max_iterations)

    for iteration in range(1, max_iterations + 1):
        status = _structured_section_budget_status(section, current_text)
        history.append({
            "iteration": iteration,
            "status": status["status"],
            "words": status["words"],
            "delta": status["delta"],
        })
        if status["ok"]:
            return current_text, {
                **status,
                "changed": changed,
                "iterations": iteration - 1,
                "fallback": None,
                "history": history,
            }

        direction = "shorten" if status["status"] == "too_long" else "expand"
        prompt = _build_structured_section_budget_prompt(
            job=job,
            course_plan=course_plan,
            section=section,
            current_text=current_text,
            status=status,
            module_content=module_content,
            direction=direction,
        )
        try:
            raw = _anthropic_post(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=_structured_generation_max_tokens(int(section.get("target_words") or 600)),
                model=model,
            )
            candidate = _sanitize_learner_facing_text(_clean_llm_text(raw))
            target_words = int(section.get("target_words") or 0)
            if target_words > 0 and count_tts_spoken_words(candidate) > target_words:
                candidate = _trim_text_to_max_spoken_words(candidate, target_words)
            candidate_words = count_tts_spoken_words(candidate)
            current_words = count_tts_spoken_words(current_text)
            min_candidate_words = min(120, max(20, int(current_words * 0.45)))
            if not candidate or candidate_words < min_candidate_words:
                logger.warning(
                    "PIPELINE_SECTION_BUDGET_CALIBRATION_REJECTED_EMPTY course=%s section=%s iteration=%s",
                    course_plan.get("course_number"),
                    _section_label(section),
                    iteration,
                )
                break
            if direction == "expand" and candidate_words <= current_words:
                logger.warning(
                    "PIPELINE_SECTION_BUDGET_CALIBRATION_NO_EXPANSION course=%s section=%s iteration=%s before=%s after=%s",
                    course_plan.get("course_number"),
                    _section_label(section),
                    iteration,
                    current_words,
                    candidate_words,
                )
                break
            if candidate.strip() != current_text.strip():
                current_text = candidate
                changed = True
                logger.info(
                    "PIPELINE_SECTION_BUDGET_CALIBRATION_ITER course=%s section=%s iteration=%s direction=%s words=%s",
                    course_plan.get("course_number"),
                    _section_label(section),
                    iteration,
                    direction,
                    candidate_words,
                )
                continue
            break
        except Exception as exc:
            logger.warning(
                "PIPELINE_SECTION_BUDGET_CALIBRATION_LLM_FAILED course=%s section=%s iteration=%s error=%s",
                course_plan.get("course_number"),
                _section_label(section),
                iteration,
                str(exc)[:300],
            )
            break

    final_status = _structured_section_budget_status(section, current_text)
    fallback = None
    if final_status["status"] == "too_long":
        current_text = _trim_text_to_max_spoken_words(current_text, final_status["max_words"])
        changed = True
        fallback = "trim_to_max_words"
        final_status = _structured_section_budget_status(section, current_text)

    return current_text, {
        **final_status,
        "changed": changed,
        "iterations": len(history),
        "fallback": fallback,
        "history": history,
    }


def _section_key(section: dict) -> tuple:
    return (section.get("kind"), int(section.get("part_number") or 0))


def _section_plan_by_key(course_plan: dict) -> dict[tuple, dict]:
    return {_section_key(section): section for section in _structured_sections_for_course(course_plan)}


def _join_structured_section_records(sections: list[dict]) -> str:
    return "\n\n".join((section.get("text") or "").strip() for section in sections if (section.get("text") or "").strip()).strip()


def _build_structured_course_deficit_repair_prompt(
    *,
    job: dict,
    course_plan: dict,
    section: dict,
    current_text: str,
    module_content: str,
    additional_words: int,
    max_words: int,
) -> str:
    target_after = min(max_words, count_tts_spoken_words(current_text) + max(0, additional_words))
    min_after = max(1, min(max_words, int(target_after * 0.94)))
    return f"""Tu répares une section trop courte d'un cours audio professionnel.

Objectif : enrichir la section avec de nouvelles idées utiles, sans changer son périmètre.
Tu dois réécrire la section complète, pas seulement ajouter un paragraphe.

Section à enrichir : {_section_label(section)}
Ajout attendu : environ {additional_words} mots parlés utiles.
Plage finale visée pour cette section : {min_after} à {max_words} mots parlés.

Plan verrouillé du cours :
{json.dumps(course_plan, ensure_ascii=False, indent=2)}

Section verrouillée :
{json.dumps(section, ensure_ascii=False, indent=2)}

Frontière stricte :
{_structured_section_scope_guard(section)}

Moments pédagogiques à couvrir :
{_section_teaching_beats_prompt(section)}

Contenu source à exploiter :
{_compact_words(module_content or job.get('program_text') or '', 4500)}

Ajoute seulement des éléments pertinents parmi :
- une nuance métier concrète ;
- une erreur fréquente et sa correction ;
- un mini-cas fictif ou hypothétique ;
- un contre-exemple ;
- une méthode opérationnelle ;
- une clarification de vocabulaire ;
- un lien avec les pratiques terrain.

Contraintes :
- Ne mentionne jamais budget mots, fichier, durée, horaire, créneau, planning ou découpage technique.
- N'utilise jamais le mot "bloc" devant les élèves.
- Ne refais pas l'accueil, l'introduction globale, le plan de journée ou la conclusion.
- Ne crée pas de nouveau thème hors du plan.
- Ne remplis pas avec du bavardage : chaque ajout doit apporter une valeur pédagogique identifiable.
- Oral fluide, TTS-ready, sans markdown ni titre écrit.

Texte actuel :
{current_text}

Réponds uniquement avec la section complète enrichie."""


def _repair_structured_course_word_deficit(
    *,
    job: dict,
    course_plan: dict,
    calibrated_sections: list[dict],
    module_content: str,
    model=None,
) -> tuple[str, list[dict], dict | None]:
    """Rattrape un cours encore trop court après le calibrage standard.

    La réparation est volontairement ciblée sur les sections de développement :
    on préfère ajouter de la valeur pédagogique dans les axes plutôt que gonfler
    artificiellement l'ouverture ou la conclusion.
    """
    current_sections = [dict(section) for section in calibrated_sections]
    attempts = []
    max_attempts = _env_int("FORMATION_STRUCTURED_COURSE_DEFICIT_REPAIR_MAX_ATTEMPTS", 10, min_value=0)
    max_attempts = min(20, max_attempts)
    max_stalled_per_section = _env_int("FORMATION_STRUCTURED_COURSE_DEFICIT_REPAIR_MAX_STALLED_PER_SECTION", 2, min_value=1)
    if max_attempts <= 0:
        return _join_structured_section_records(current_sections), current_sections, None

    stalled_by_key = {}
    for attempt_no in range(1, max_attempts + 1):
        course_text = _join_structured_section_records(current_sections)
        status = _structured_course_budget_status(course_plan, course_text)
        if status.get("status") != "too_short":
            break

        missing = int(status.get("min_words") or 0) - int(status.get("words") or 0)
        if missing <= 0:
            break

        candidates = []
        for idx, record in enumerate(current_sections):
            if record.get("kind") != "part":
                continue
            current_words = count_tts_spoken_words(record.get("text") or "")
            max_words = int(record.get("target_words") or record.get("max_words") or 0)
            if max_words <= 0:
                continue
            room = max_words - current_words
            if room >= 60:
                key = _section_key(record)
                if stalled_by_key.get(key, 0) >= max_stalled_per_section:
                    continue
                candidates.append({
                    "idx": idx,
                    "key": key,
                    "record": record,
                    "current_words": current_words,
                    "max_words": max_words,
                    "room": room,
                    "stalled": stalled_by_key.get(key, 0),
                    "fill_ratio": current_words / max_words if max_words else 1.0,
                })

        if not candidates:
            attempts.append({
                "attempt": attempt_no,
                "status": status,
                "missing_words": missing,
                "error": "no_expandable_part_section",
            })
            break

        candidates.sort(key=lambda item: (item["stalled"], item["fill_ratio"], -item["room"]))
        candidate = candidates[0]
        planned_words = min(candidate["room"], max(120, int(missing * 1.18) + 30))
        attempt = {
            "attempt": attempt_no,
            "status_before": status,
            "missing_words": missing,
            "planned_words": planned_words,
            "sections": [],
        }

        record = candidate["record"]
        section_plan = _section_plan_by_key(course_plan).get(_section_key(record), {})
        section = {**section_plan, **record}
        before_text = record.get("text") or ""
        before_words = count_tts_spoken_words(before_text)
        try:
            raw = _anthropic_post(
                messages=[{
                    "role": "user",
                    "content": _build_structured_course_deficit_repair_prompt(
                        job=job,
                        course_plan=course_plan,
                        section=section,
                        current_text=before_text,
                        module_content=module_content,
                        additional_words=planned_words,
                        max_words=candidate["max_words"],
                    ),
                }],
                max_tokens=_structured_generation_max_tokens(candidate["max_words"]),
                model=model,
            )
            repaired = _sanitize_learner_facing_text(_clean_llm_text(raw))
            if candidate["max_words"] > 0 and count_tts_spoken_words(repaired) > candidate["max_words"]:
                repaired = _trim_text_to_max_spoken_words(repaired, candidate["max_words"])
            after_words = count_tts_spoken_words(repaired)
            min_gain = max(20, min(80, int(planned_words * 0.18)))
            if not repaired or after_words <= before_words or (after_words - before_words) < min_gain:
                stalled_by_key[candidate["key"]] = stalled_by_key.get(candidate["key"], 0) + 1
                attempt["sections"].append({
                    "label": record.get("label") or _section_label(section),
                    "before_words": before_words,
                    "after_words": after_words,
                    "changed": False,
                    "reason": "insufficient_growth",
                    "min_gain": min_gain,
                })
            else:
                updated = {
                    **record,
                    "text": repaired,
                    "word_count": after_words,
                    "deficit_repair_before_words": before_words,
                }
                current_sections[candidate["idx"]] = updated
                gained = after_words - before_words
                attempt["sections"].append({
                    "label": record.get("label") or _section_label(section),
                    "before_words": before_words,
                    "after_words": after_words,
                    "gained_words": gained,
                    "changed": True,
                })
                logger.info(
                    "PIPELINE_COURSE_DEFICIT_REPAIR_ATTEMPT course=%s attempt=%s section=%s before=%s after=%s missing=%s",
                    course_plan.get("course_number"),
                    attempt_no,
                    record.get("label") or _section_label(section),
                    before_words,
                    after_words,
                    missing,
                )
        except Exception as exc:
            stalled_by_key[candidate["key"]] = stalled_by_key.get(candidate["key"], 0) + 1
            attempt["sections"].append({
                "label": record.get("label") or _section_label(section),
                "before_words": before_words,
                "changed": False,
                "error": str(exc)[:300],
            })
            logger.warning(
                "PIPELINE_COURSE_DEFICIT_REPAIR_FAILED course=%s attempt=%s section=%s error=%s",
                course_plan.get("course_number"),
                attempt_no,
                record.get("label") or _section_label(section),
                str(exc)[:300],
            )

        attempt["status_after"] = _structured_course_budget_status(
            course_plan,
            _join_structured_section_records(current_sections),
        )
        attempts.append(attempt)
        if attempt["status_after"].get("ok"):
            break

    final_text = _join_structured_section_records(current_sections)
    final_status = _structured_course_budget_status(course_plan, final_text)
    repair = {
        "mode": "course_deficit_repair",
        "changed": final_text.strip() != _join_structured_section_records(calibrated_sections).strip(),
        "status": final_status.get("status"),
        "words": final_status.get("words"),
        "min_words": final_status.get("min_words"),
        "target_words": final_status.get("target_words"),
        "attempts": attempts,
    }
    return final_text, current_sections, repair


def _calibrate_structured_course_sections(
    *,
    job: dict,
    course_plan: dict,
    draft: dict,
    module_content: str,
    model=None,
) -> tuple[str, dict]:
    plan_sections = _section_plan_by_key(course_plan)
    calibrated_sections = []
    section_results = []
    changed = False

    for record in draft.get("sections") or []:
        section = {**plan_sections.get(_section_key(record), {}), **record}
        before_text = record.get("text") or ""
        before_words = count_tts_spoken_words(before_text)
        calibrated_text, calibration = _calibrate_structured_section_text(
            job=job,
            course_plan=course_plan,
            section=section,
            text=before_text,
            module_content=module_content,
            model=model,
        )
        after_words = count_tts_spoken_words(calibrated_text)
        changed = changed or calibrated_text.strip() != before_text.strip() or bool(calibration.get("changed"))
        calibrated_record = {
            **record,
            "text": calibrated_text,
            "word_count": after_words,
            "before_word_count": before_words,
            "calibration": calibration,
        }
        calibrated_sections.append(calibrated_record)
        section_results.append({
            "kind": record.get("kind"),
            "label": record.get("label") or _section_label(section),
            "part_number": record.get("part_number"),
            "title": record.get("title"),
            "target_words": int(section.get("target_words") or 0),
            "before_words": before_words,
            "after_words": after_words,
            "delta_words": after_words - before_words,
            "status": calibration.get("status"),
            "min_words": calibration.get("min_words"),
            "max_words": calibration.get("max_words"),
            "changed": bool(calibrated_text.strip() != before_text.strip() or calibration.get("changed")),
            "calibration": calibration,
        })

    course_text = _join_structured_section_records(calibrated_sections)
    course_status = _structured_course_budget_status(course_plan, course_text)
    deficit_repair = None
    if course_status.get("status") == "too_short":
        repaired_text, repaired_sections, deficit_repair = _repair_structured_course_word_deficit(
            job=job,
            course_plan=course_plan,
            calibrated_sections=calibrated_sections,
            module_content=module_content,
            model=model,
        )
        repaired_status = _structured_course_budget_status(course_plan, repaired_text)
        if repaired_text.strip() != course_text.strip():
            changed = True
            calibrated_sections = repaired_sections
            course_text = repaired_text
            course_status = repaired_status
            repaired_by_key = {_section_key(section): section for section in calibrated_sections}
            for section_result in section_results:
                repaired_section = repaired_by_key.get(
                    (section_result.get("kind"), int(section_result.get("part_number") or 0))
                )
                if not repaired_section:
                    continue
                after_words = count_tts_spoken_words(repaired_section.get("text") or "")
                status = _structured_section_budget_status(repaired_section, repaired_section.get("text") or "")
                section_result["after_words"] = after_words
                section_result["delta_words"] = after_words - int(section_result.get("before_words") or 0)
                section_result["status"] = status.get("status")
                section_result["min_words"] = status.get("min_words")
                section_result["max_words"] = status.get("max_words")
                section_result["changed"] = bool(section_result["delta_words"])
                if repaired_section.get("deficit_repair_before_words") is not None:
                    section_result["deficit_repaired"] = True

    return course_text, {
        **course_status,
        "changed": changed,
        "mode": "section_budget_calibration",
        "sections": section_results,
        "calibrated_sections": calibrated_sections,
        "deficit_repair": deficit_repair,
    }


def _exact_repetition_issues(text: str, *, max_issues: int = 3) -> list[dict]:
    paragraphs = [
        p.strip()
        for p in re.split(r"\n\s*\n+", text or "")
        if len((p or "").split()) >= 22
    ]
    seen = {}
    issues = []
    for idx, paragraph in enumerate(paragraphs, start=1):
        key = re.sub(r"\s+", " ", paragraph).strip().lower()
        if key in seen:
            issues.append({
                "type": "repetition",
                "severity": "major",
                "section": "whole_course",
                "evidence": _compact_words(paragraph, 32),
                "problem": f"Paragraphe répété presque à l'identique aux positions {seen[key]} et {idx}.",
                "fix_instruction": "Supprimer la redite et recoller naturellement les paragraphes autour.",
            })
            if len(issues) >= max_issues:
                break
        else:
            seen[key] = idx
    return issues


def _learner_schedule_leakage_issues(text: str, *, max_issues: int = 4) -> list[dict]:
    clean_text = _strip_audio_block_markers(text or "")
    issues = []
    seen = set()
    for match in _LEARNER_FACING_SCHEDULE_LEAK_RE.finditer(clean_text):
        leak = re.sub(r"\s+", " ", match.group(0)).strip()
        key = leak.lower()
        if not leak or key in seen:
            continue
        seen.add(key)
        start = max(0, match.start() - 120)
        end = min(len(clean_text), match.end() + 120)
        evidence = _compact_words(clean_text[start:end], 42)
        issues.append({
            "type": "schedule_leakage",
            "severity": "major",
            "section": "whole_course",
            "evidence": evidence,
            "problem": (
                "Le texte fait entendre une contrainte interne de planning "
                f"({leak!r}) au lieu de parler seulement de progression pédagogique."
            ),
            "fix_instruction": (
                "Supprimer la mention d'horaire, créneau, durée ou planning. "
                "Reformuler naturellement : thèmes de la journée dans l'ordre, "
                "reprise après pause, rappel bref, nouveau thème, objectif et plan."
            ),
        })
        if len(issues) >= max_issues:
            break
    return issues


def _learner_internal_course_framing_issues(text: str, *, max_issues: int = 4) -> list[dict]:
    clean_text = _strip_audio_block_markers(text or "")
    issues = []
    seen = set()
    for match in _LEARNER_FACING_INTERNAL_COURSE_RE.finditer(clean_text):
        phrase = re.sub(r"\s+", " ", match.group(0)).strip()
        key = phrase.lower()
        if not phrase or key in seen:
            continue
        seen.add(key)
        start = max(0, match.start() - 120)
        end = min(len(clean_text), match.end() + 140)
        issues.append({
            "type": "internal_course_framing",
            "severity": "major",
            "section": "opening",
            "evidence": _compact_words(clean_text[start:end], 48),
            "problem": (
                "Le texte présente une unité interne comme un cours autonome "
                f"({phrase!r}) au lieu d'un thème ou chapitre naturel de la journée."
            ),
            "fix_instruction": (
                "Reformuler avec une voix plus naturelle : 'premier grand thème', "
                "'cette première partie', 'ce chapitre', 'cette séquence', puis "
                "annoncer les axes avec d'abord, ensuite, enfin."
            ),
        })
        if len(issues) >= max_issues:
            break
    return issues


def _duplicate_opening_issues(text: str, *, max_issues: int = 2) -> list[dict]:
    clean_text = _strip_audio_block_markers(text or "")
    paragraphs = [
        re.sub(r"\s+", " ", p).strip()
        for p in re.split(r"\n\s*\n+", clean_text)
        if len((p or "").split()) >= 14
    ]
    category_hits: dict[str, list[tuple[int, str]]] = {}
    for idx, paragraph in enumerate(paragraphs[:12], start=1):
        for category, pattern in _DUPLICATE_OPENING_CATEGORY_PATTERNS.items():
            if pattern.search(paragraph):
                category_hits.setdefault(category, []).append((idx, _compact_words(paragraph, 44)))

    issues = []
    labels = {
        "annual_overview": "l'introduction annuelle",
        "day_overview": "le cadrage de la journée",
        "theme_opening": "l'ouverture du premier thème",
    }
    for category, hits in category_hits.items():
        if len(hits) < 2:
            continue
        first, second = hits[0], hits[1]
        issues.append({
            "type": "duplicate_opening",
            "severity": "major",
            "section": "whole_course",
            "evidence": f"Paragraphe {first[0]}: {first[1]} / Paragraphe {second[0]}: {second[1]}",
            "problem": (
                f"Le texte semble répéter {labels.get(category, 'une ouverture')} "
                "au lieu de l'annoncer une seule fois puis d'entrer dans le développement."
            ),
            "fix_instruction": (
                "Garder une seule ouverture. Supprimer la deuxième annonce de journée/thème "
                "et commencer directement le développement de l'axe concerné."
            ),
        })
        if len(issues) >= max_issues:
            break
    return issues


def _slide_meta_leakage_issues(text: str, *, max_issues: int = 3) -> list[dict]:
    clean_text = _strip_audio_block_markers(text or "")
    issues = []
    seen = set()
    for match in _SLIDE_META_LEAK_RE.finditer(clean_text):
        leak = re.sub(r"\s+", " ", match.group(0)).strip()
        key = leak.lower()
        if not leak or key in seen:
            continue
        seen.add(key)
        start = max(0, match.start() - 120)
        end = min(len(clean_text), match.end() + 120)
        issues.append({
            "type": "slide_meta_leakage",
            "severity": "major",
            "section": "whole_course",
            "evidence": _compact_words(clean_text[start:end], 42),
            "problem": (
                "Le texte verbalise une mécanique interne de slides ou de templates "
                f"({leak!r}) qui ne doit pas être entendue par les apprenants."
            ),
            "fix_instruction": (
                "Supprimer la méta-formulation slide/template/anchor et garder seulement "
                "l'idée pédagogique naturelle."
            ),
        })
        if len(issues) >= max_issues:
            break
    return issues


def _quality_signature(course_plan: dict, text: str) -> str:
    payload = json.dumps(
        {
            "version": _PLAN_ADHERENCE_REVIEW_VERSION,
            "course_plan": course_plan,
            "text": text or "",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_plan_adherence_audit(
    raw_audit: dict,
    course_plan: dict,
    text: str,
    *,
    include_budget_issues: bool = True,
) -> dict:
    issues = []
    for issue in (raw_audit or {}).get("issues") or []:
        if not isinstance(issue, dict):
            continue
        issue_type = str(issue.get("type") or "other")[:80]
        severity = str(issue.get("severity") or "major").lower()
        if severity not in {"minor", "major", "critical"}:
            severity = "major"
        issues.append({
            "type": issue_type,
            "severity": severity,
            "section": str(issue.get("section") or "whole_course")[:80],
            "evidence": str(issue.get("evidence") or "")[:500],
            "problem": str(issue.get("problem") or "")[:500],
            "fix_instruction": str(issue.get("fix_instruction") or "")[:700],
        })

    budget_status = _structured_course_budget_status(course_plan, text)
    if include_budget_issues and budget_status["status"] == "too_short":
        issues.append({
            "type": "budget",
            "severity": "major",
            "section": "whole_course",
            "evidence": f"{budget_status['words']} mots pour une plage {budget_status['min_words']}-{budget_status['max_words']}",
            "problem": "Le cours est trop court pour le budget audio prévu.",
            "fix_instruction": "Enrichir avec du contenu pédagogique pertinent lié au plan, sans remplissage.",
        })
    elif include_budget_issues and budget_status["status"] == "too_long":
        issues.append({
            "type": "budget",
            "severity": "major",
            "section": "whole_course",
            "evidence": f"{budget_status['words']} mots pour une plage {budget_status['min_words']}-{budget_status['max_words']}",
            "problem": "Le cours dépasse le budget audio prévu.",
            "fix_instruction": "Réduire proprement les répétitions, digressions et développements faibles.",
        })

    issues.extend(_exact_repetition_issues(text))
    issues.extend(_duplicate_opening_issues(text))
    issues.extend(_slide_meta_leakage_issues(text))
    issues.extend(_learner_schedule_leakage_issues(text))
    issues.extend(_learner_internal_course_framing_issues(text))
    ok = not any(issue.get("severity") in {"major", "critical"} for issue in issues)
    return {
        "ok": ok,
        "summary": str((raw_audit or {}).get("summary") or ("Conforme" if ok else "Réparation ciblée requise"))[:700],
        "issues": issues,
        "budget_status": budget_status,
    }


def _build_plan_adherence_audit_prompt(
    *,
    job: dict,
    course_plan: dict,
    text: str,
    previous_course_summary: str,
    include_budget_issues: bool = True,
) -> str:
    contract = _load_prompt_file("reviews", "plan-adherence-audit.md")
    budget_status = _structured_course_budget_status(course_plan, text)
    budget_instruction = (
        "Le budget mots fait partie de l'audit : signale too_short/too_long si nécessaire."
        if include_budget_issues
        else (
            "Le budget mots est seulement informatif ici. Ne signale pas de problème "
            "de volume : le calibrage budget texte est l'étape suivante dédiée."
        )
    )
    return f"""Tu audites l'adhérence pédagogique d'un cours audio à son plan verrouillé.

CONTRAT D'AUDIT :
{contract}

Contexte :
- Titre professionnel : {job.get('program_title') or ''}
- Journée : {job.get('folder_name') or ''}
- Cours : {course_plan.get('course_number')} / 7
- Rappel très bref de la partie précédente : {previous_course_summary or '(aucun)'}
- Portée budget : {budget_instruction}

Statut budget mots :
{json.dumps(budget_status, ensure_ascii=False, indent=2)}

Plan JSON verrouillé :
{json.dumps(course_plan, ensure_ascii=False, indent=2)}

Texte de la partie à auditer :
{text}

Réponds uniquement avec le JSON d'audit."""


def _run_plan_adherence_audit(
    *,
    job: dict,
    course_plan: dict,
    text: str,
    previous_course_summary: str,
    model=None,
    include_budget_issues: bool = True,
) -> dict:
    prompt = _build_plan_adherence_audit_prompt(
        job=job,
        course_plan=course_plan,
        text=text,
        previous_course_summary=previous_course_summary,
        include_budget_issues=include_budget_issues,
    )
    raw = _anthropic_post(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2200,
        model=model,
    )
    return _normalize_plan_adherence_audit(
        _extract_llm_json(raw),
        course_plan,
        text,
        include_budget_issues=include_budget_issues,
    )


def _build_plan_adherence_repair_prompt(
    *,
    job: dict,
    course_plan: dict,
    text: str,
    audit: dict,
    previous_course_summary: str,
) -> str:
    contract = _load_prompt_file("reviews", "plan-adherence-repair.md")
    budget_status = _structured_course_budget_status(course_plan, text)
    return f"""Tu vas réparer un cours audio à partir d'un audit ciblé.

CONTRAT DE RÉPARATION :
{contract}

Contexte :
- Titre professionnel : {job.get('program_title') or ''}
- Journée : {job.get('folder_name') or ''}
- Cours : {course_plan.get('course_number')} / 7
- Rappel très bref de la partie précédente : {previous_course_summary or '(aucun)'}

Budget à respecter :
{json.dumps(budget_status, ensure_ascii=False, indent=2)}

Audit à corriger :
{json.dumps(audit, ensure_ascii=False, indent=2)}

Plan JSON verrouillé :
{json.dumps(course_plan, ensure_ascii=False, indent=2)}

Texte actuel de la partie :
{text}

Texte complet corrigé :"""


def _repair_plan_adherence_course(
    *,
    job: dict,
    course_plan: dict,
    text: str,
    audit: dict,
    previous_course_summary: str,
    model=None,
) -> str:
    prompt = _build_plan_adherence_repair_prompt(
        job=job,
        course_plan=course_plan,
        text=text,
        audit=audit,
        previous_course_summary=previous_course_summary,
    )
    target_words = max(
        int(course_plan.get("target_words") or 0),
        count_tts_spoken_words(text),
    )
    raw = _anthropic_post(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=_structured_generation_max_tokens(target_words),
        model=model,
    )
    candidate = _sanitize_learner_facing_text(_clean_llm_text(raw))
    candidate_words = count_tts_spoken_words(candidate)
    current_words = count_tts_spoken_words(text)
    if not candidate or candidate_words < max(250, int(current_words * 0.45)):
        raise ValueError("Réparation plan-adherence vide ou trop courte")
    return candidate


def _run_plan_adherence_quality_loop(
    *,
    job: dict,
    course_plan: dict,
    text: str,
    previous_course_summary: str,
    model=None,
    max_repairs: int | None = None,
    include_budget_issues: bool = True,
    allow_post_calibration: bool = True,
    review_timing: str | None = None,
) -> tuple[str, dict]:
    if max_repairs is None:
        max_repairs = int(os.getenv("FORMATION_PLAN_ADHERENCE_REPAIR_ITERATIONS", "1") or "1")
    max_repairs = max(0, min(3, int(max_repairs)))
    course_number = int(course_plan.get("course_number") or 0)
    if not review_timing:
        review_timing = (
            "manual_before_humanization"
            if include_budget_issues or allow_post_calibration
            else "after_section_generation_before_budget_calibration"
        )
    current_text = _sanitize_learner_facing_text(text)
    initial_text = current_text
    attempts = []
    changed = False
    final_audit = None

    for attempt in range(1, max_repairs + 1):
        audit = _run_plan_adherence_audit(
            job=job,
            course_plan=course_plan,
            text=current_text,
            previous_course_summary=previous_course_summary,
            model=model,
            include_budget_issues=include_budget_issues,
        )
        final_audit = audit
        record = {
            "attempt": attempt,
            "audit": audit,
            "before_words": count_tts_spoken_words(current_text),
            "repair": None,
        }
        if audit.get("ok"):
            attempts.append(record)
            break
        repaired = _repair_plan_adherence_course(
            job=job,
            course_plan=course_plan,
            text=current_text,
            audit=audit,
            previous_course_summary=previous_course_summary,
            model=model,
        )
        repaired_words = count_tts_spoken_words(repaired)
        record["repair"] = {
            "applied": repaired.strip() != current_text.strip(),
            "after_words": repaired_words,
        }
        attempts.append(record)
        if repaired.strip() != current_text.strip():
            current_text = repaired
            changed = True
        else:
            break

    if changed or final_audit is None:
        final_audit = _run_plan_adherence_audit(
            job=job,
            course_plan=course_plan,
            text=current_text,
            previous_course_summary=previous_course_summary,
            model=model,
            include_budget_issues=include_budget_issues,
        )

    post_calibration = None
    budget_status = _structured_course_budget_status(course_plan, current_text)
    if allow_post_calibration and changed and budget_status.get("status") in {"too_short", "too_long"}:
        calibrated, post_calibration = _calibrate_structured_course_text(course_plan, current_text, model=model)
        if calibrated.strip() != current_text.strip():
            current_text = calibrated
            changed = True
            final_audit = _run_plan_adherence_audit(
                job=job,
                course_plan=course_plan,
                text=current_text,
                previous_course_summary=previous_course_summary,
                model=model,
                include_budget_issues=include_budget_issues,
            )

    result = {
        "course_number": course_number,
        "course_title": course_plan.get("course_title") or f"Cours {course_number}",
        "version": _PLAN_ADHERENCE_REVIEW_VERSION,
        "changed": bool(changed),
        "initial_words": count_tts_spoken_words(initial_text),
        "final_words": count_tts_spoken_words(current_text),
        "initial_signature": _quality_signature(course_plan, initial_text),
        "final_signature": _quality_signature(course_plan, current_text),
        "review_timing": review_timing,
        "budget_issues_included": bool(include_budget_issues),
        "post_calibration_allowed": bool(allow_post_calibration),
        "attempts": attempts,
        "final_audit": final_audit,
        "post_calibration": post_calibration,
    }
    return current_text, result


def _run_plan_adherence_on_generated_drafts(
    *,
    job: dict,
    platform_id: int,
    folder_id: int,
    plan: dict,
    body_results: list[dict],
    course_summaries: dict[int, str],
    workers: int,
    total_words: int,
    on_progress=None,
    model=None,
) -> list[dict]:
    """Corrige l'adhérence au plan juste après génération, avant budget/conformité."""
    started_at = time.time()
    sorted_results = sorted(body_results, key=lambda item: int(item.get("course_number") or 0))
    total = len(sorted_results)
    course_records = []
    details = []
    total_proposed = 0
    total_applied = 0
    total_rejected = 0
    total_failed = 0

    logger.info(
        "PIPELINE_EARLY_PLAN_ADHERENCE_START formation_job_id=%s content_job_id=%s folder_id=%s courses=%s",
        job.get("formation_job_id"),
        job.get("id"),
        folder_id,
        total,
    )

    for step, body_result in enumerate(sorted_results, start=1):
        draft = body_result.get("draft") or {}
        course_plan = draft.get("course_plan") or body_result.get("course_plan") or {}
        course_number = int(course_plan.get("course_number") or body_result.get("course_number") or step)
        before_text = draft.get("course_text") or ""
        previous_summary = course_summaries.get(course_number - 1, "")
        if on_progress:
            on_progress(
                0,
                NUM_SUB_PARTS,
                1,
                total_words,
                f"Adhérence au plan après génération cours {course_number}/7",
            )
        try:
            final_text, quality_result = _run_plan_adherence_quality_loop(
                job=job,
                course_plan=course_plan,
                text=before_text,
                previous_course_summary=previous_summary,
                model=model,
                include_budget_issues=False,
                allow_post_calibration=False,
                review_timing="after_section_generation_before_budget_calibration",
            )
            before_words = count_tts_spoken_words(before_text)
            final_words = count_tts_spoken_words(final_text)
            changed = final_text.strip() != before_text.strip() or bool(quality_result.get("changed"))
            if changed:
                draft["course_text"] = final_text
                draft["draft_word_count"] = final_words
                body_result["draft"] = draft
            body_result["plan_adherence"] = quality_result
            quality_result.update({
                "changed": bool(changed),
                "initial_words": before_words,
                "final_words": final_words,
                "before_text": before_text,
                "after_text": final_text,
                "delta_words": final_words - before_words,
            })
            detail = _quality_detail_from_result(0, max(0, course_number - 1), 1, quality_result)
            details.append(detail)
            total_proposed += int(detail.get("proposed") or 0)
            total_applied += len(detail.get("applied") or [])
            total_rejected += len(detail.get("rejected") or [])
            course_records.append(quality_result)
        except Exception as e:
            total_failed += 1
            logger.warning(
                "PIPELINE_EARLY_PLAN_ADHERENCE_COURSE_FAILED formation_job_id=%s content_job_id=%s folder_id=%s course=%s error=%s",
                job.get("formation_job_id"),
                job.get("id"),
                folder_id,
                course_number,
                str(e)[:300],
            )
            details.append({
                "segment_id": 0,
                "sub_idx": max(0, course_number - 1),
                "passe": 1,
                "proposed": 0,
                "applied": [],
                "rejected": [],
                "error": str(e)[:500],
            })
            course_records.append({
                "course_number": course_number,
                "course_title": course_plan.get("course_title") or f"Cours {course_number}",
                "version": _PLAN_ADHERENCE_REVIEW_VERSION,
                "changed": False,
                "failed": True,
                "error": str(e)[:500],
                "initial_words": count_tts_spoken_words(before_text),
                "final_words": count_tts_spoken_words(before_text),
                "before_text": before_text,
                "after_text": before_text,
                "review_timing": "after_section_generation_before_budget_calibration",
                "budget_issues_included": False,
                "post_calibration_allowed": False,
            })
            body_result["plan_adherence"] = course_records[-1]

        _save_content_artifact(
            platform_id,
            folder_id,
            _CONTENT_QUALITY_REVIEWS_BLOB,
            _artifact_payload(
                job,
                "content_quality_reviews",
                {
                    "review_kind": "plan_adherence",
                    "review_label": "Adhérence au plan après génération par section",
                    "review_timing": "after_section_generation_before_budget_calibration",
                    "budget_scope": "ignored_here_budget_calibration_runs_next",
                    "version": _PLAN_ADHERENCE_REVIEW_VERSION,
                    "structured_course_plan_version": plan.get("version"),
                    "generation_strategy": "parallel_body_then_late_opening",
                    "parallel_workers": workers,
                    "courses": course_records,
                },
            ),
        )

    duration_ms = int((time.time() - started_at) * 1000)
    summary = {
        "segments_reviewed": total - total_failed,
        "segments_failed": total_failed,
        "segments_total_completed": total,
        "segments_already_current": 0,
        "patches_proposed": total_proposed,
        "patches_applied": total_applied,
        "patches_rejected": total_rejected,
        "review_signature": _PLAN_ADHERENCE_REVIEW_VERSION,
        "review_kind": "plan_adherence",
        "review_label": "Adhérence au plan après génération par section",
        "review_timing": "after_section_generation_before_budget_calibration",
        "budget_scope": "ignored_here_budget_calibration_runs_next",
        "force": True,
        "duration_ms": duration_ms,
        "details": details,
    }
    _save_content_artifact(
        platform_id,
        folder_id,
        _CONTENT_QUALITY_REVIEWS_BLOB,
        _artifact_payload(
            job,
            "content_quality_reviews",
            {
                "review_summary": summary,
                "review_kind": "plan_adherence",
                "review_label": "Adhérence au plan après génération par section",
                "review_timing": "after_section_generation_before_budget_calibration",
                "budget_scope": "ignored_here_budget_calibration_runs_next",
                "version": _PLAN_ADHERENCE_REVIEW_VERSION,
                "structured_course_plan_version": plan.get("version"),
                "generation_strategy": "parallel_body_then_late_opening",
                "parallel_workers": workers,
                "duration_ms": duration_ms,
                "courses": course_records,
            },
        ),
    )
    logger.info(
        "PIPELINE_EARLY_PLAN_ADHERENCE_DONE formation_job_id=%s content_job_id=%s folder_id=%s reviewed=%s failed=%s applied=%s rejected=%s duration_ms=%s",
        job.get("formation_job_id"),
        job.get("id"),
        folder_id,
        summary["segments_reviewed"],
        total_failed,
        total_applied,
        total_rejected,
        duration_ms,
    )
    return sorted_results


def _clear_content_segments_for_structured(job_id: int) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM content_generation_segments WHERE job_id = ?", (job_id,))
    conn.commit()
    conn.close()


def _save_structured_course_segment(job_id: int, course_plan: dict, text: str) -> None:
    course_number = int(course_plan.get("course_number") or 0)
    stored_text = f"<<<BLOC_AUDIO_{course_number}>>>\n\n{text}".strip()
    _save_segment_db(
        job_id,
        course_number - 1,
        course_plan.get("course_title") or f"Cours {course_number}",
        1,
        stored_text,
    )


def _module_content_for_structured_course(
    course_plan: dict,
    course_number: int,
    sub_parts: list,
    module_contents: dict,
) -> str:
    module_content = module_contents.get(course_plan.get("course_title") or "", "")
    if not module_content and course_number - 1 < len(sub_parts or []):
        module_content = module_contents.get(sub_parts[course_number - 1], "")
    return module_content or ""


def _structured_opening_section_for_course(course_plan: dict) -> dict:
    return {"kind": "opening", **(course_plan.get("opening") or {})}


def _structured_body_sections_for_course(course_plan: dict) -> list[dict]:
    return [
        section
        for section in _structured_sections_for_course(course_plan)
        if section.get("kind") not in {"opening", "day_conclusion"}
    ]


def _structured_day_conclusion_section_for_course(course_plan: dict) -> dict | None:
    if not course_plan.get("day_conclusion"):
        return None
    return {"kind": "day_conclusion", **course_plan["day_conclusion"]}


def _ethical_micro_section_for_calibrated_course(course_plan: dict) -> dict:
    return {
        "kind": "course_calibrated",
        "title": course_plan.get("course_title") or f"Cours {course_plan.get('course_number') or '?'}",
        "target_words": int(course_plan.get("target_words") or 0),
        "review_scope": "full_course_after_budget_calibration",
        "course_kind": course_plan.get("course_kind"),
        "learning_objectives": course_plan.get("learning_objectives") or [],
        "global_constraints": course_plan.get("global_constraints") or {},
    }


def _run_structured_parallel(items: list, worker, *, workers: int) -> list:
    if not items:
        return []
    workers = max(1, min(int(workers or 1), len(items)))
    if workers <= 1:
        return [worker(item) for item in items]
    import eventlet
    pool = eventlet.GreenPool(size=workers)
    greenlets = [pool.spawn(worker, item) for item in items]
    return [greenlet.wait() for greenlet in greenlets]


def _generate_structured_course_body(
    *,
    job: dict,
    course_plan: dict,
    sub_parts: list,
    module_contents: dict,
    model=None,
) -> dict:
    course_number = int(course_plan.get("course_number") or 0)
    module_content = _module_content_for_structured_course(
        course_plan,
        course_number,
        sub_parts,
        module_contents,
    )
    section_texts = []
    section_records = []
    logger.info(
        "PIPELINE_STRUCTURED_BODY_START formation_job_id=%s content_job_id=%s course=%s",
        job.get("formation_job_id"),
        job.get("id"),
        course_number,
    )
    for section in _structured_body_sections_for_course(course_plan):
        label = _section_label(section)
        section_text = _generate_structured_section(
            job=job,
            course_plan=course_plan,
            section=section,
            previous_course_summary="",
            generated_so_far="\n\n".join(section_texts),
            module_content=module_content,
            model=model,
        )
        section_texts.append(section_text)
        section_records.append({
            "kind": section.get("kind"),
            "label": label,
            "part_number": section.get("part_number"),
            "title": section.get("title"),
            "target_words": int(section.get("target_words") or 0),
            "word_count": count_tts_spoken_words(section_text),
            "text": section_text,
            **_section_artifact_metadata(section),
        })
    body_text = "\n\n".join(s for s in section_texts if s.strip()).strip()
    logger.info(
        "PIPELINE_STRUCTURED_BODY_DONE formation_job_id=%s content_job_id=%s course=%s words=%s",
        job.get("formation_job_id"),
        job.get("id"),
        course_number,
        count_tts_spoken_words(body_text),
    )
    return {
        "course_number": course_number,
        "course_plan": course_plan,
        "module_content": module_content,
        "body_text": body_text,
        "body_sections": section_records,
    }


def _summarize_structured_course_body(body_result: dict, model=None) -> tuple[int, str]:
    course_number = int(body_result.get("course_number") or 0)
    summary = _summarize_previous_course_for_structured(body_result.get("body_text") or "", model=model)
    return course_number, summary


def _generate_late_opening_for_structured_course(
    *,
    job: dict,
    body_result: dict,
    previous_course_summary: str,
    model=None,
) -> dict:
    course_plan = body_result["course_plan"]
    course_number = int(body_result.get("course_number") or 0)
    section = _structured_opening_section_for_course(course_plan)
    opening_text = _generate_structured_section(
        job=job,
        course_plan=course_plan,
        section=section,
        previous_course_summary=previous_course_summary,
        generated_so_far=body_result.get("body_text") or "",
        module_content=body_result.get("module_content") or "",
        model=model,
    )
    return {
        "course_number": course_number,
        "record": {
            "kind": section.get("kind"),
            "label": _section_label(section),
            "part_number": section.get("part_number"),
            "title": section.get("title"),
            "target_words": int(section.get("target_words") or 0),
            "word_count": count_tts_spoken_words(opening_text),
            "text": opening_text,
            "generated_late": True,
            **_section_artifact_metadata(section),
        },
        "text": opening_text,
    }


def _generate_late_day_conclusion_for_structured_course(
    *,
    job: dict,
    body_result: dict,
    day_summary_context: str,
    model=None,
) -> dict | None:
    course_plan = body_result["course_plan"]
    section = _structured_day_conclusion_section_for_course(course_plan)
    if not section:
        return None
    course_number = int(body_result.get("course_number") or 0)
    day_conclusion_text = _generate_structured_section(
        job=job,
        course_plan=course_plan,
        section=section,
        previous_course_summary=day_summary_context,
        generated_so_far=body_result.get("body_text") or "",
        module_content=body_result.get("module_content") or "",
        model=model,
    )
    return {
        "course_number": course_number,
        "record": {
            "kind": section.get("kind"),
            "label": _section_label(section),
            "part_number": section.get("part_number"),
            "title": section.get("title"),
            "target_words": int(section.get("target_words") or 0),
            "word_count": count_tts_spoken_words(day_conclusion_text),
            "text": day_conclusion_text,
            "generated_late": True,
            **_section_artifact_metadata(section),
        },
        "text": day_conclusion_text,
    }


def _assemble_structured_course_draft(body_result: dict, opening_result: dict, day_conclusion_result: dict | None) -> dict:
    section_records = [opening_result["record"], *body_result.get("body_sections", [])]
    section_texts = [opening_result.get("text") or "", body_result.get("body_text") or ""]
    if day_conclusion_result:
        section_records.append(day_conclusion_result["record"])
        section_texts.append(day_conclusion_result.get("text") or "")
    course_text = "\n\n".join(s for s in section_texts if (s or "").strip()).strip()
    return {
        "course_number": int(body_result.get("course_number") or 0),
        "course_plan": body_result["course_plan"],
        "course_text": course_text,
        "sections": section_records,
        "draft_word_count": count_tts_spoken_words(course_text),
    }


def _run_structured_content_generation(
    *,
    job: dict,
    folder_id: int,
    platform_id: int,
    sub_parts: list,
    module_contents: dict,
    on_progress=None,
    model=None,
) -> tuple[int, str, dict]:
    playlist_items = _playlist_items_for_platform(platform_id)
    job["_ethical_micro_review_records"] = []
    plan = _generate_structured_course_plan(job, playlist_items, sub_parts, module_contents, model=model)
    plan_validation = _validate_structured_course_plan(plan)
    _save_content_artifact(
        platform_id,
        folder_id,
        _CONTENT_PLAN_BLOB,
        _artifact_payload(
            job,
            "content_plan",
            {
                "structured_course_plan": plan,
                "validation": plan_validation,
            },
        ),
    )
    if not plan_validation["ok"]:
        logger.warning(
            "PIPELINE_STRUCTURED_PLAN_VALIDATION_WARN content_job_id=%s folder_id=%s errors=%s warnings=%s",
            job["id"],
            folder_id,
            plan_validation.get("errors"),
            plan_validation.get("warnings"),
        )
    _clear_content_segments_for_structured(job["id"])

    generated_blocks = []
    course_scripts = []
    total_words = 0
    course_plans = sorted(
        list(plan.get("courses") or []),
        key=lambda course: int(course.get("course_number") or 0),
    )
    total_courses = len(course_plans)
    workers = _structured_course_parallel_workers()
    logger.info(
        "PIPELINE_STRUCTURED_PARALLEL_CONFIG formation_job_id=%s content_job_id=%s folder_id=%s workers=%s courses=%s strategy=body_then_late_opening",
        job.get("formation_job_id"),
        job["id"],
        folder_id,
        workers,
        total_courses,
    )

    if on_progress:
        on_progress(0, NUM_SUB_PARTS, 1, total_words, f"Génération parallèle des contenus principaux ({workers} cours à la fois)")
    body_results = _run_structured_parallel(
        course_plans,
        lambda course_plan: _generate_structured_course_body(
            job=job,
            course_plan=course_plan,
            sub_parts=sub_parts,
            module_contents=module_contents,
            model=model,
        ),
        workers=workers,
    )
    body_results = sorted(body_results, key=lambda item: int(item.get("course_number") or 0))

    if on_progress:
        on_progress(0, NUM_SUB_PARTS, 1, total_words, "Résumés courts des cours pour les reprises tardives")
    summary_pairs = _run_structured_parallel(
        body_results,
        lambda body_result: _summarize_structured_course_body(body_result, model=model),
        workers=workers,
    )
    course_summaries = {int(course_number): summary for course_number, summary in summary_pairs}
    day_summary_context = "\n".join(
        f"Cours {course_number}: {course_summaries.get(course_number) or ''}"
        for course_number in sorted(course_summaries)
    )

    if on_progress:
        on_progress(0, NUM_SUB_PARTS, 1, total_words, "Génération tardive des introductions et raccords")
    opening_results = _run_structured_parallel(
        body_results,
        lambda body_result: _generate_late_opening_for_structured_course(
            job=job,
            body_result=body_result,
            previous_course_summary=course_summaries.get(int(body_result.get("course_number") or 0) - 1, ""),
            model=model,
        ),
        workers=workers,
    )
    openings_by_course = {
        int(opening.get("course_number") or 0): opening
        for opening in opening_results
    }
    day_conclusion_tasks = [
        body_result
        for body_result in body_results
        if _structured_day_conclusion_section_for_course(body_result["course_plan"])
    ]
    day_conclusion_results = _run_structured_parallel(
        day_conclusion_tasks,
        lambda body_result: _generate_late_day_conclusion_for_structured_course(
            job=job,
            body_result=body_result,
            day_summary_context=day_summary_context,
            model=model,
        ),
        workers=max(1, min(workers, len(day_conclusion_tasks) or 1)),
    )
    day_conclusions_by_course = {
        int(result.get("course_number") or 0): result
        for result in day_conclusion_results
        if result
    }

    draft_courses = []
    for body_result in body_results:
        course_number = int(body_result.get("course_number") or 0)
        draft = _assemble_structured_course_draft(
            body_result,
            openings_by_course[course_number],
            day_conclusions_by_course.get(course_number),
        )
        course_plan = draft["course_plan"]
        draft_courses.append({
            "course_number": course_number,
            "course_title": course_plan.get("course_title") or f"Cours {course_number}",
            "target_words": int(course_plan.get("target_words") or 0),
            "draft_word_count": draft["draft_word_count"],
            "sections": draft["sections"],
            "generation_strategy": "parallel_body_then_late_opening",
        })
        body_result["draft"] = draft

    _save_content_artifact(
        platform_id,
        folder_id,
        _CONTENT_DRAFT_SECTIONS_BLOB,
        _artifact_payload(
            job,
            "content_draft_sections",
            {
                "structured_course_plan_version": plan.get("version"),
                "generation_strategy": "parallel_body_then_late_opening",
                "parallel_workers": workers,
                "course_summaries": course_summaries,
                "courses": draft_courses,
            },
        ),
    )

    if on_progress:
        on_progress(0, NUM_SUB_PARTS, 1, total_words, "Adhérence au plan après génération par section")
    body_results = _run_plan_adherence_on_generated_drafts(
        job=job,
        platform_id=platform_id,
        folder_id=folder_id,
        plan=plan,
        body_results=body_results,
        course_summaries=course_summaries,
        workers=workers,
        total_words=total_words,
        on_progress=on_progress,
        model=model,
    )

    if on_progress:
        on_progress(0, NUM_SUB_PARTS, 1, total_words, "Calibrage parallèle des budgets mots par cours")

    def _calibrate_draft(body_result: dict) -> dict:
        draft = body_result["draft"]
        course_plan = draft["course_plan"]
        module_content = body_result.get("module_content") or ""
        draft_sections_text = _join_structured_section_records(draft.get("sections") or [])
        source_drift = bool(
            draft_sections_text
            and (draft.get("course_text") or "").strip()
            and draft_sections_text.strip() != (draft.get("course_text") or "").strip()
        )
        if draft.get("sections"):
            calibrated_text, calibration = _calibrate_structured_course_sections(
                job=job,
                course_plan=course_plan,
                draft=draft,
                module_content=module_content,
                model=model,
            )
            calibration["source_sections_drifted_from_course_text"] = source_drift
        else:
            calibrated_text, calibration = _calibrate_structured_course_text(
                course_plan,
                draft["course_text"],
                model=model,
            )
        if calibration.get("status") in {"too_short", "too_long"}:
            fallback_text, fallback_calibration = _calibrate_structured_course_text(
                course_plan,
                calibrated_text,
                model=model,
            )
            fallback_calibration["mode"] = "course_budget_safety_net"
            calibration["course_safety_net"] = fallback_calibration
            if fallback_text.strip() != calibrated_text.strip():
                calibrated_text = fallback_text
                calibration = {
                    **fallback_calibration,
                    "primary_section_calibration": calibration,
                    "source_sections_drifted_from_course_text": source_drift,
                }
        final_status = _structured_course_budget_status(course_plan, calibrated_text)
        if not final_status.get("ok") and str(os.getenv("FORMATION_STRUCTURED_CALIBRATION_STRICT", "1")).strip().lower() not in {"0", "false", "no", "off"}:
            if final_status.get("status") == "too_short" and str(os.getenv("FORMATION_STRUCTURED_ALLOW_RESIDUAL_TOO_SHORT", "1")).strip().lower() not in {"0", "false", "no", "off"}:
                calibration["accepted_residual_shortfall"] = True
                calibration["accepted_residual_shortfall_words"] = max(
                    0,
                    int(final_status.get("min_words") or 0) - int(final_status.get("words") or 0),
                )
                logger.warning(
                    "PIPELINE_COURSE_BUDGET_SHORTFALL_ACCEPTED formation_job_id=%s content_job_id=%s course=%s words=%s min=%s target=%s",
                    job.get("formation_job_id"),
                    job.get("id"),
                    course_plan.get("course_number"),
                    final_status.get("words"),
                    final_status.get("min_words"),
                    final_status.get("target_words"),
                )
            else:
                raise ValueError(
                    "Calibrage budget texte insuffisant "
                    f"cours={course_plan.get('course_number')} "
                    f"status={final_status.get('status')} "
                    f"words={final_status.get('words')} "
                    f"target={final_status.get('target_words')} "
                    f"min={final_status.get('min_words')}"
                )
        calibrated_words = count_tts_spoken_words(calibrated_text)
        course_number = int(course_plan.get("course_number") or body_result.get("course_number") or 0)
        return {
            "course_number": course_number,
            "course_plan": course_plan,
            "calibrated_text": calibrated_text,
            "calibrated_words": calibrated_words,
            "course_text": calibrated_text,
            "words": calibrated_words,
            "calibration": calibration,
            "sections": calibration.get("calibrated_sections") or draft.get("sections") or [],
            "plan_adherence": body_result.get("plan_adherence"),
            "draft": draft,
        }

    calibrated_results = _run_structured_parallel(
        body_results,
        _calibrate_draft,
        workers=workers,
    )
    calibrated_results = sorted(calibrated_results, key=lambda item: int(item.get("course_number") or 0))

    budget_calibration_records = []
    for result in calibrated_results:
        course_number = int(result.get("course_number") or 0)
        course_plan = result["course_plan"]
        calibrated_text = result.get("calibrated_text") or result.get("course_text") or ""
        calibrated_words = int(result.get("calibrated_words") or count_tts_spoken_words(calibrated_text))
        calibration = result.get("calibration") or {}
        draft = result.get("draft") or {}
        before_text = draft.get("course_text") or ""
        before_words = int(draft.get("draft_word_count") or count_tts_spoken_words(before_text))
        budget_calibration_records.append({
            "course_number": course_number,
            "course_title": course_plan.get("course_title") or f"Cours {course_number}",
            "filename": course_plan.get("filename"),
            "target_words": int(course_plan.get("target_words") or 0),
            "min_words": calibration.get("min_words"),
            "max_words": calibration.get("max_words"),
            "before_words": before_words,
            "after_words": calibrated_words,
            "delta_words": calibrated_words - before_words,
            "changed": bool((calibrated_text or "").strip() != (before_text or "").strip() or calibration.get("changed")),
            "calibration": calibration,
            "plan_adherence": _compact_plan_adherence_result(result.get("plan_adherence")),
            "before_text": before_text,
            "after_text": calibrated_text,
            "sections": result.get("sections") or draft.get("sections") or [],
            "structured_plan": course_plan,
        })

    _save_content_artifact(
        platform_id,
        folder_id,
        _CONTENT_BUDGET_CALIBRATION_BLOB,
        _artifact_payload(
            job,
            "content_budget_calibration",
            {
                "structured_course_plan_version": plan.get("version"),
                "generation_strategy": "parallel_body_then_late_opening",
                "parallel_workers": workers,
                "summary": {
                    "courses": len(budget_calibration_records),
                    "changed": sum(1 for record in budget_calibration_records if record.get("changed")),
                    "target_words": sum(int(record.get("target_words") or 0) for record in budget_calibration_records),
                    "before_words": sum(int(record.get("before_words") or 0) for record in budget_calibration_records),
                    "after_words": sum(int(record.get("after_words") or 0) for record in budget_calibration_records),
                },
                "courses": budget_calibration_records,
            },
        ),
    )

    if on_progress:
        on_progress(0, NUM_SUB_PARTS, 1, total_words, "Micro-conformité éthique après calibrage budget")

    def _micro_review_calibrated_course(result: dict) -> dict:
        course_plan = result["course_plan"]
        calibrated_text = result.get("calibrated_text") or result.get("course_text") or ""
        final_text = _run_ethical_micro_review_for_section(
            job=job,
            course_plan=course_plan,
            section=_ethical_micro_section_for_calibrated_course(course_plan),
            section_text=calibrated_text,
            model=model,
        )
        return {
            **result,
            "course_text": final_text,
            "words": count_tts_spoken_words(final_text),
            "micro_changed": (final_text or "").strip() != (calibrated_text or "").strip(),
            "post_micro_budget_status": _structured_course_budget_status(course_plan, final_text),
        }

    final_course_results = _run_structured_parallel(
        calibrated_results,
        _micro_review_calibrated_course,
        workers=workers,
    )
    final_course_results = sorted(final_course_results, key=lambda item: int(item.get("course_number") or 0))

    micro_records = _sorted_ethical_micro_review_records(job)
    _save_content_artifact(
        platform_id,
        folder_id,
        _CONTENT_ETHICAL_MICRO_REVIEW_BLOB,
        _artifact_payload(
            job,
            "content_ethical_micro_review",
            {
                "review_kind": "ethical_micro",
                "review_label": "Micro-conformité éthique après calibrage budget",
                "rules_scope": "ethics_compliance",
                "rules": [f"#{rid}" for rid in _ETHICAL_MICRO_RULE_IDS],
                "version": _ETHICAL_MICRO_RULESET_VERSION,
                "structured_course_plan_version": plan.get("version"),
                "review_timing": "after_budget_calibration",
                "summary": _ethical_micro_review_summary(micro_records),
                "records": micro_records,
            },
        ),
    )

    for result in final_course_results:
        course_number = int(result.get("course_number") or 0)
        course_plan = result["course_plan"]
        course_text = result["course_text"]
        words = int(result.get("words") or 0)
        calibration = result.get("calibration") or {}
        _save_structured_course_segment(job["id"], course_plan, course_text)
        total_words += words
        generated_block = {
            "bloc_number": course_number,
            "filename": course_plan.get("filename"),
            "duration_sec": _course_duration_for_bloc(playlist_items, course_number),
            "duration_min": course_plan.get("duration_minutes"),
            "status": "planned",
            "text": course_text,
            "word_count": words,
            "planned_word_count": words,
            "word_budget": int(course_plan.get("target_words") or 0),
            "main_word_budget": int(course_plan.get("target_words") or 0),
            "dirty": True,
            "structured_plan": course_plan,
            "calibration": calibration,
            "plan_adherence": _compact_plan_adherence_result(result.get("plan_adherence")),
            "calibrated_word_count": int(result.get("calibrated_words") or 0),
            "micro_changed": bool(result.get("micro_changed")),
            "post_micro_budget_status": result.get("post_micro_budget_status"),
            "generation_strategy": "parallel_body_then_late_opening",
        }
        generated_blocks.append(generated_block)
        course_scripts.append({
            "course_number": course_number,
            "course_title": course_plan.get("course_title") or f"Cours {course_number}",
            "filename": course_plan.get("filename"),
            "target_words": int(course_plan.get("target_words") or 0),
            "word_count": words,
            "text": course_text,
            "plan_adherence": _compact_plan_adherence_result(result.get("plan_adherence")),
            "calibration": calibration,
            "calibrated_word_count": int(result.get("calibrated_words") or 0),
            "micro_changed": bool(result.get("micro_changed")),
            "post_micro_budget_status": result.get("post_micro_budget_status"),
            "structured_plan": course_plan,
            "generation_strategy": "parallel_body_then_late_opening",
            "previous_course_summary_used": course_summaries.get(course_number - 1, ""),
        })
        _update_job_db(job["id"], total_words=total_words, current_sub_part=course_number - 1, current_passe=1)
        if on_progress:
            on_progress(course_number, NUM_SUB_PARTS, 1, total_words, f"Cours {course_number}/7 calibré et contrôlé ({words} mots)")
        logger.info(
            "PIPELINE_STRUCTURED_COURSE_DONE formation_job_id=%s content_job_id=%s folder_id=%s course=%s/%s words=%s target=%s",
            job.get("formation_job_id"),
            job["id"],
            folder_id,
            course_number,
            total_courses,
            words,
            course_plan.get("target_words"),
        )

    _save_content_artifact(
        platform_id,
        folder_id,
        _CONTENT_COURSE_SCRIPTS_BLOB,
        _artifact_payload(
            job,
            "content_course_scripts",
            {
                "structured_course_plan_version": plan.get("version"),
                "generation_strategy": "parallel_body_then_late_opening",
                "parallel_workers": workers,
                "course_summaries": course_summaries,
                "courses": course_scripts,
            },
        ),
    )

    final_words, filename = _assemble_and_upload(folder_id, platform_id, job["id"])
    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "mode": "structured_content_generation",
        "generation_strategy": "parallel_body_then_late_opening",
        "parallel_workers": workers,
        "structured_course_plan": plan,
        "planned_course_blocs": generated_blocks,
        "course_blocs": [],
    }
    _save_course_script_plan(platform_id, folder_id, payload)
    return final_words, filename, payload


# ─── Pipeline principale ──────────────────────────────────────────────────────

def run_content_generation(folder_id, on_progress=None, mode="normal", model=None):
    """
    Lance ou reprend la génération de contenu pour un dossier.
    Doit être appelé dans un greenlet eventlet (non-bloquant).

    on_progress(sub_idx, total_sub_parts, passe, total_words, message) — callback optionnel.

    mode :
      "normal" — génération complète via Claude (volume calibré audio)
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
        if _structured_content_generation_enabled() and not is_mock and not is_mini:
            structured_job = dict(job)
            structured_job["folder_id"] = folder_id
            _progress(0, 1, job["total_words"] or 0, "Plan JSON structuré — génération des 7 cours")
            total_words, filename, _payload = _run_structured_content_generation(
                job=structured_job,
                folder_id=folder_id,
                platform_id=platform_id,
                sub_parts=sub_parts,
                module_contents=module_contents,
                on_progress=on_progress,
                model=model,
            )
            _update_job_db(job_id, status="completed", total_words=total_words)
            _progress(NUM_SUB_PARTS, 1, total_words, f"✅ Génération structurée terminée : {filename}")
            logger.info(
                "PIPELINE_CONTENT_DONE formation_job_id=%s content_job_id=%s folder_id=%s mode=structured total_words=%s duration_ms=%s",
                formation_job_id,
                job_id,
                folder_id,
                total_words,
                int((time.time() - started_at) * 1000),
            )
            return

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
        parallel_workers = (
            1 if is_mini
            else min(len(sub_parts_to_run), _content_parallel_subpart_workers())
        )
        logger.info(
            "PIPELINE_CONTENT_PARALLEL_CONFIG formation_job_id=%s content_job_id=%s folder_id=%s workers=%s sub_parts=%s passes=%s",
            formation_job_id,
            job_id,
            folder_id,
            parallel_workers,
            len(sub_parts_to_run),
            len(passes_to_run),
        )

        import threading

        total_words_lock = threading.Lock()

        def _generate_sub_part(sub_idx, sub_part_name):
            nonlocal total_words
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
            subpart_words = 0

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
                with total_words_lock:
                    current_total_words = total_words
                _progress(sub_idx, passe, current_total_words, msg)
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
                    current_total_words,
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
                        generation_context={
                            "folder_position": job.get("folder_position"),
                            "nb_days": job.get("nb_days"),
                            "total_hours": job.get("total_hours"),
                            "folder_name": job.get("folder_name") or "",
                            "sub_part_index": sub_idx,
                            "passe": passe,
                        },
                    )
                else:
                    prev = "" if passe == 1 else (passe1_text if passe == 2 else passe1_2_text)
                    text = _generate_segment_text(
                        passe, sub_part_name, program_title, program_text, prev,
                        model=model,
                        generation_context={
                            "folder_position": job.get("folder_position"),
                            "nb_days": job.get("nb_days"),
                            "total_hours": job.get("total_hours"),
                            "folder_name": job.get("folder_name") or "",
                            "sub_part_index": sub_idx,
                            "passe": passe,
                        },
                    )

                _save_segment_db(job_id, sub_idx, sub_part_name, passe, text)
                words_added = len(text.split())
                with total_words_lock:
                    total_words += words_added
                    current_total_words = total_words
                subpart_words += words_added
                _update_job_db(job_id, total_words=current_total_words)
                logger.info(
                    "PIPELINE_CONTENT_SEGMENT_DONE formation_job_id=%s content_job_id=%s folder_id=%s sub_part=%s passe=%s "
                    "words_added=%s total_words=%s duration_ms=%s",
                    formation_job_id,
                    job_id,
                    folder_id,
                    sub_idx + 1,
                    passe,
                    words_added,
                    current_total_words,
                    int((time.time() - segment_started_at) * 1000),
                )

                if passe == 1:
                    passe1_text = text
                elif passe == 2:
                    passe1_2_text = passe1_text + "\n\n" + text
            logger.info(
                "PIPELINE_CONTENT_SUBPART_DONE formation_job_id=%s content_job_id=%s folder_id=%s sub_part=%s/%s words=%s",
                formation_job_id,
                job_id,
                folder_id,
                sub_idx + 1,
                len(sub_parts_to_run),
                subpart_words,
            )
            return subpart_words

        if parallel_workers <= 1:
            for sub_idx, sub_part_name in enumerate(sub_parts_to_run):
                _generate_sub_part(sub_idx, sub_part_name)
        else:
            import eventlet
            pool = eventlet.GreenPool(size=parallel_workers)
            greenlets = [
                pool.spawn(_generate_sub_part, sub_idx, sub_part_name)
                for sub_idx, sub_part_name in enumerate(sub_parts_to_run)
            ]
            for g in greenlets:
                g.wait()

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
        if seed_duration <= duration_sec + _UPLOAD_DURATION_TOLERANCE_SEC:
            repeat = 1
        else:
            return b"", 0.0
    remainder = duration_sec - (repeat * seed_duration)
    if (
        remainder > _UPLOAD_DURATION_TOLERANCE_SEC
        and ((repeat + 1) * seed_duration) <= duration_sec + _UPLOAD_DURATION_TOLERANCE_SEC
    ):
        repeat += 1

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
    elif previous_item_type is None:
        lead = "Bonjour à tous, j'espère que vous allez bien. Installez-vous tranquillement, on va prendre le temps d'entrer dans cette partie."
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
        "cours": "une partie précédente",
        None: "le début de journée",
    }.get(previous_item_type, str(previous_item_type))

    rest_preview = " ".join(rest.split()[:90])
    prompt = f"""Tu écris l'amorce audio d'une partie de journée pour une classe virtuelle.

PARTIE INTERNE : {bloc_number}/7
ÉLÉMENT JUSTE AVANT CETTE PARTIE : {previous_label}

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
- Applique les règles d'humanisation : entrée douce, rythme calme, respiration
  pédagogique, présence humaine, pas de ton conférence.
- Si ce fichier ouvre une journée ou démarre sans élément précédent, commence
  par accueillir et installer le cadre avant de présenter le sujet.
- Ne commence jamais par "Bon, on va aborder", "nouvelle partie du cours",
  "on entre dans le vif du sujet" ou "c'est absolument fondamental".
- Tu peux situer brièvement le fil, mais ne fais pas un résumé long du cours précédent.
- Ne répète pas la conclusion, le Q&A ou la pause qui viennent déjà d'avoir lieu.
- Si l'élément précédent est une pause, ne dis pas "la pause est terminée".
- Ne spoile pas tout le cours : ouvre seulement la porte du sujet.
- Ne change pas le fond : conserve les idées du début actuel.
- Ne recopie pas littéralement le début actuel : reformule sur le vif, naturellement.
- L'amorce doit faire 25 à 55 mots.
- Le début reformulé doit faire 35 à 85 mots.
- Termine le début reformulé de façon à enchaîner naturellement avec la suite immédiate.
- Pas d'horaires, pas de créneau, pas de planning, pas de markdown, pas de guillemets.

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

    prompt = f"""Tu écris l'amorce d'une partie audio qui reprend un passage reporté
depuis le fichier audio précédent.

CONTEXTE :
- Partie interne actuelle : {bloc_number}/7.
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

DÉBUT DU COURS PRÉVU APRÈS LE REPORT :
---
{_compact_words(base_preview, 180) or "(indisponible)"}
---

MISSION :
Crée une amorce orale puis reformule légèrement le début reporté.
On ne doit pas reprendre brutalement à la phrase exacte où le cours précédent
s'était arrêté. Il faut réinstaller l'idée, puis la lancer naturellement.

CONSIGNES :
- Applique les règles d'humanisation : reprise douce, respiration, formateur
  humain, pas de reprise sèche au milieu d'un exemple.
- Ne fais pas semblant de répondre à des questions.
- Ne parle pas de fichier audio, de découpage technique, de chunk ou de report.
- Ne parle pas d'horaire, de créneau, de planning, de durée ou de budget.
- Tu peux dire sobrement qu'on reprend le fil ou qu'on pose le point proprement.
- Ne change pas le fond.
- Ne recopie pas littéralement le début reporté.
- "opening" : 25 à 55 mots.
- "rewritten_start" : 35 à 85 mots.
- Pas d'horaires, pas de créneau, pas de markdown, pas de guillemets.

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
    break_overrides: dict | None = None,
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
        from services.break_transition_service import (
            break_intro_owned_by_previous,
            duration_label,
            is_schedule_neutral_break,
            next_item_type,
        )
        intro_owned = break_intro_owned_by_previous(playlist_items, item_idx, file_type)
        if file_type == "qa":
            intro, outro = _get_qa_text(bloc_num)
            ntype = next_item_type(playlist_items, item_idx)
            if ntype in {"pause", "pause_midi"} and not is_schedule_neutral_break(filename):
                next_item = _next_playlist_item_after(playlist_items, item_idx)
                next_intro = _break_intro_text_for_playlist_item(next_item)
                label = duration_label(_playlist_item_duration(next_item), ntype)
                if next_intro:
                    outro = (
                        "Très bien, on clôt ce temps de questions. "
                        f"{next_intro}"
                    )
                elif ntype == "pause_midi" or label == "pause déjeuner":
                    outro = (
                        "Très bien, on clôt ce temps de questions. "
                        "On va maintenant marquer la pause déjeuner, prenez le temps de souffler."
                    )
                elif label:
                    outro = (
                        f"Très bien, on clôt ce temps de questions. "
                        f"On va maintenant prendre une pause de {label}."
                    )
                else:
                    outro = (
                        "Très bien, on clôt ce temps de questions. "
                        "On va maintenant prendre une courte pause."
                    )
            if intro_owned:
                intro = ""
            return intro, outro
        if file_type == "pause_midi" or filename.startswith("pause_midi_"):
            intro, outro = _get_pause_midi_text()
        else:
            intro, outro = _get_pause_text(bloc_num)
        if intro_owned:
            intro = ""
        return intro, outro

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

    manual_break = (break_overrides or {}).get(filename)
    if manual_break:
        intro = (manual_break.get("intro") or "").strip()
        outro = (manual_break.get("outro") or "").strip()
        _emit(f"{filename} — texte manuel...")
        if basic_tts:
            audio_bytes, final_duration = _build_timed_edge_break_audio(
                intro,
                outro,
                duration_sec,
                on_progress=lambda msg: _emit(f"{filename} — {msg}"),
            )
            _emit(
                f"{filename} — Edge TTS manuel calé ({final_duration:.1f}s/{duration_sec}s)"
            )
            return audio_bytes, "manual_edge_timed"
        return _build_pause_audio(intro, outro, duration_sec), "manual_fish"

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
    target_filename=None,
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
    from services.tts_service import convert_to_speech, convert_to_speech_with_timestamps
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
    saved_script_plan = _load_saved_course_script_plan(platform_id, folder_id) or {}
    target_filename = os.path.basename((target_filename or "").split("?", 1)[0]) or None
    assert_course_day_word_budget(folder_id, context="audio_generation")
    started_at = time.time()
    logger.info(
        "PIPELINE_AUDIO_START formation_job_id=%s content_job_id=%s folder_id=%s platform_id=%s force_all=%s mock=%s basic_tts=%s "
        "sync_slides=%s auto_generate_slides=%s slide_max_slides=%s slide_pace=%s llm_model=%s fast_tts_pipeline=%s target_filename=%s",
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
        target_filename,
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
    _apply_course_bloc_overrides(blocs, saved_script_plan.get("course_bloc_overrides"))
    playlist_items = _playlist_items_for_platform(platform_id)
    if target_filename:
        matching_item = next((item for item in playlist_items if item[0] == target_filename), None)
        if not matching_item:
            raise ValueError(f"Fichier audio introuvable dans la playlist : {target_filename}")
        if matching_item[2] == "cours":
            selected_bloc = next((b for b in blocs if int(b.get("bloc_number") or 0) == int(matching_item[3] or 0)), None)
            if selected_bloc:
                selected_bloc["dirty"] = True
    if carryover_out:
        logger.info(
            f"🔁 Folder {folder_id} : {len(carryover_out.split())} mots reportés "
            f"vers folder {next_folder_id}"
        )

    # Les fins de blocs sont désormais portées par le texte calibré en amont.
    # On n'ajoute plus de closing au moment de l'audio.

    blocs_by_number = {b["bloc_number"]: b for b in blocs}
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
    # Actif pour Edge TTS, avec ou sans sync slides : Edge est plus lent que le
    # budget Fish Audio et doit être calé par durée réelle avant upload.
    intra_day_carryover_chunks = []
    runtime_fit_enabled = bool(basic_tts and not mock)
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
    planned_course_script_plan = []

    def _record_course_bloc(bloc, *, status, text=None, final_duration_sec=None,
                            skipped_reason=None, opening_rewritten=False,
                            opening_text="", opening_original_start="",
                            runtime_conclusions=None, runtime_ai_decisions=None,
                            actual_reading=None, target_plan=None):
        target = course_script_plan if target_plan is None else target_plan
        target.append(
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
                actual_reading=actual_reading,
            )
        )

    def _parallel_fish_course_worker(item_idx, filename, duration_sec, bloc_num):
        step = item_idx + 1
        item_started_at = time.time()
        bloc = blocs_by_number.get(bloc_num)
        audio_bloc = bloc
        opening_rewritten = False
        opening_text = ""
        opening_original_start = ""
        try:
            logger.info(
                "PIPELINE_AUDIO_ITEM_START formation_job_id=%s content_job_id=%s folder_id=%s item=%s/%s filename=%s type=cours bloc=%s target_sec=%s parallel_fish=true",
                formation_job_id,
                job_id,
                folder_id,
                step,
                len(playlist_items),
                filename,
                bloc_num,
                duration_sec,
            )
            if not bloc:
                return {
                    "item_idx": item_idx,
                    "status": "skipped",
                    "skipped_reason": "bloc_missing",
                    "filename": filename,
                    "bloc_num": bloc_num,
                    "duration_ms": int((time.time() - item_started_at) * 1000),
                }
            if not bloc.get("dirty"):
                return {
                    "item_idx": item_idx,
                    "status": "skipped",
                    "skipped_reason": "clean_bloc",
                    "filename": filename,
                    "bloc": bloc,
                    "bloc_num": bloc_num,
                    "duration_ms": int((time.time() - item_started_at) * 1000),
                }
            if not (bloc.get("text") or "").strip():
                return {
                    "item_idx": item_idx,
                    "status": "skipped",
                    "skipped_reason": "empty_text",
                    "filename": filename,
                    "bloc": bloc,
                    "bloc_num": bloc_num,
                    "duration_ms": int((time.time() - item_started_at) * 1000),
                }

            if _course_opening_transitions_enabled():
                from services.break_transition_service import nearest_course_bloc
                prev_course = nearest_course_bloc(playlist_items, item_idx, -1)
                prev_bloc_text = ""
                if prev_course and prev_course in blocs_by_number:
                    prev_data = blocs_by_number.get(prev_course) or {}
                    prev_bloc_text = prev_data.get("text") or ""
                _progress(
                    step,
                    len(playlist_items),
                    f"Bloc {bloc['bloc_number']}/7 — intro IA + Fish parallèle...",
                )
                rewritten_text, opening_meta = _rewrite_course_opening_for_audio(
                    bloc,
                    playlist_items,
                    item_idx,
                    model=llm_model,
                    previous_excerpt=_tail_words(prev_bloc_text, 220),
                )
                if rewritten_text and rewritten_text != (bloc.get("text") or "").strip():
                    audio_bloc = dict(bloc)
                    audio_bloc["text"] = rewritten_text
                    audio_bloc["word_count"] = len(rewritten_text.split())
                    opening_rewritten = True
                    opening_text = (opening_meta or {}).get("opening_text") or ""
                    opening_original_start = (opening_meta or {}).get("original_start") or ""

            _progress(
                step,
                len(playlist_items),
                f"Bloc {bloc['bloc_number']}/7 — Fish Audio parallèle ({len(audio_bloc['text'].split())} mots)...",
            )
            final_bytes, voice_duration, fit_method, attempts = _synthesize_fish_course_audio_observe(
                audio_bloc,
                convert_to_speech,
                _measure_duration_ms,
                convert_to_speech_with_timestamps=convert_to_speech_with_timestamps,
            )
            actual_reading = _actual_reading_from_attempts(attempts)
            final_duration = float(voice_duration)
            blob_path = f"{azure_prefix}{filename}"
            upload_blob(CONTAINER_AUDIOS, blob_path, final_bytes)
            logger.info(
                "PIPELINE_AUDIO_ITEM_DONE formation_job_id=%s content_job_id=%s folder_id=%s filename=%s type=cours bloc=%s final_duration=%.1f words=%s duration_ms=%s parallel_fish=true",
                formation_job_id,
                job_id,
                folder_id,
                filename,
                bloc["bloc_number"],
                final_duration,
                len((audio_bloc.get("text") or "").split()),
                int((time.time() - item_started_at) * 1000),
            )
            return {
                "item_idx": item_idx,
                "status": "generated",
                "filename": filename,
                "bloc": bloc,
                "audio_bloc": audio_bloc,
                "voice_duration": voice_duration,
                "final_duration": final_duration,
                "fit_method": fit_method,
                "attempts": attempts,
                "actual_reading": actual_reading,
                "opening_rewritten": opening_rewritten,
                "opening_text": opening_text,
                "opening_original_start": opening_original_start,
                "duration_ms": int((time.time() - item_started_at) * 1000),
            }
        except Exception as exc:
            logger.exception(
                "PIPELINE_AUDIO_ITEM_FAILED formation_job_id=%s content_job_id=%s folder_id=%s filename=%s bloc=%s parallel_fish=true",
                formation_job_id,
                job_id,
                folder_id,
                filename,
                bloc_num,
            )
            return {
                "item_idx": item_idx,
                "status": "error",
                "filename": filename,
                "bloc_num": bloc_num,
                "error": str(exc),
                "duration_ms": int((time.time() - item_started_at) * 1000),
            }

    parallel_fish_course_results = {}
    fish_course_workers = _fish_audio_course_workers()
    parallel_fish_courses_enabled = (
        not mock
        and not basic_tts
        and not sync_slides
        and fish_course_workers > 1
    )
    if parallel_fish_courses_enabled:
        dirty_course_items = [
            (idx, filename, duration_sec, bloc_num)
            for idx, (filename, duration_sec, file_type, bloc_num) in enumerate(playlist_items)
            if file_type == "cours"
            and (not target_filename or filename == target_filename)
            and (blocs_by_number.get(bloc_num) or {}).get("dirty")
            and ((blocs_by_number.get(bloc_num) or {}).get("text") or "").strip()
        ]
        if len(dirty_course_items) > 1:
            import eventlet as _ev
            workers = min(fish_course_workers, len(dirty_course_items))
            logger.info(
                "PIPELINE_AUDIO_FISH_PARALLEL_COURSES formation_job_id=%s content_job_id=%s folder_id=%s courses=%s workers=%s",
                formation_job_id,
                job_id,
                folder_id,
                len(dirty_course_items),
                workers,
            )
            _progress(
                0,
                len(playlist_items),
                f"Fish Audio — génération parallèle de {len(dirty_course_items)} cours ({workers} workers)...",
            )
            pool = _ev.GreenPool(size=workers)
            pile = _ev.GreenPile(pool)
            for args in dirty_course_items:
                pile.spawn(_parallel_fish_course_worker, *args)
            for result in pile:
                parallel_fish_course_results[result["item_idx"]] = result
        else:
            parallel_fish_courses_enabled = False

    for item_idx, (filename, duration_sec, file_type, bloc_num) in enumerate(playlist_items):
        if target_filename and filename != target_filename:
            continue
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
                break_overrides=saved_script_plan.get("break_overrides"),
            )
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
            _assert_audio_duration_within_slot(filename, final_duration, duration_sec)
            _progress(step, len(playlist_items), f"{filename} — upload audio ({break_mode})...")
            upload_blob(CONTAINER_AUDIOS, f"{azure_prefix}{filename}", final_bytes)
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
            _record_course_bloc(
                {
                    "bloc_number": bloc_num,
                    "filename": filename,
                    "target_sec": duration_sec,
                    "text": "",
                },
                status="skipped",
                skipped_reason="bloc_missing",
                target_plan=planned_course_script_plan,
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

        # Le carryover intra-jour est désactivé par défaut : un cours ne doit
        # pas commencer en terminant le précédent.
        intra_day_carryover_active = (
            runtime_fit_enabled and _runtime_intra_day_carryover_enabled()
        )

        # Si le carryover intra-jour est explicitement activé, on doit
        # régénérer ce bloc même s'il était propre côté texte initial.
        if intra_day_carryover_active and intra_day_carryover_chunks and not bloc["dirty"]:
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
            _record_course_bloc(
                bloc,
                status="planned",
                text=bloc.get("text", ""),
                skipped_reason="clean_bloc",
                target_plan=planned_course_script_plan,
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
            _record_course_bloc(
                bloc,
                status="skipped",
                text="",
                skipped_reason="empty_text",
                target_plan=planned_course_script_plan,
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

        parallel_result = parallel_fish_course_results.get(item_idx)
        if parallel_result:
            if parallel_result.get("status") == "error":
                raise RuntimeError(
                    f"Fish Audio parallèle échoué pour {filename}: "
                    f"{parallel_result.get('error') or 'erreur inconnue'}"
                )
            if parallel_result.get("status") != "generated":
                skipped_reason = parallel_result.get("skipped_reason") or "parallel_skip"
                logger.info(f"   ⏭️ Bloc {bloc['bloc_number']} ({filename}) : {skipped_reason}")
                _record_course_bloc(
                    bloc,
                    status="preserved" if skipped_reason == "clean_bloc" else "skipped",
                    text=bloc.get("text", ""),
                    skipped_reason=skipped_reason,
                )
                _record_course_bloc(
                    bloc,
                    status="planned" if skipped_reason == "clean_bloc" else "skipped",
                    text=bloc.get("text", ""),
                    skipped_reason=skipped_reason,
                    target_plan=planned_course_script_plan,
                )
                skipped.append(filename)
                continue

            audio_bloc = parallel_result["audio_bloc"]
            voice_duration = float(parallel_result.get("voice_duration") or 0.0)
            final_duration = float(parallel_result.get("final_duration") or voice_duration)
            fit_method = parallel_result.get("fit_method") or "fish_observe_parallel"
            attempts = parallel_result.get("attempts") or []
            actual_reading = parallel_result.get("actual_reading")
            if actual_reading:
                audio_bloc["actual_reading"] = actual_reading
                bloc["actual_reading"] = actual_reading
                logger.info(
                    "PIPELINE_AUDIO_ACTUAL_READING formation_job_id=%s content_job_id=%s "
                    "folder_id=%s bloc=%s input_words=%s fish_words=%s voice_duration=%.1f "
                    "wpm=%.1f words_per_hour=%.0f",
                    formation_job_id,
                    job_id,
                    folder_id,
                    bloc["bloc_number"],
                    actual_reading.get("input_spoken_word_count"),
                    actual_reading.get("fish_segment_word_count"),
                    float(actual_reading.get("audio_duration_sec") or 0.0),
                    float(actual_reading.get("words_per_minute") or 0.0),
                    float(actual_reading.get("words_per_hour") or 0.0),
                )
            logger.info(
                f"   ✅ Bloc {bloc['bloc_number']} ({filename}) : Fish parallèle terminé "
                f"({final_duration:.1f}s, {fit_method})"
            )
            _progress(
                step,
                len(playlist_items),
                f"Bloc {bloc['bloc_number']}/7 — terminé Fish parallèle ({final_duration:.1f}s)",
            )
            _record_course_bloc(
                audio_bloc,
                status="planned",
                text=audio_bloc.get("text", ""),
                final_duration_sec=round(final_duration, 3),
                opening_rewritten=parallel_result.get("opening_rewritten", False),
                opening_text=parallel_result.get("opening_text") or "",
                opening_original_start=parallel_result.get("opening_original_start") or "",
                actual_reading=actual_reading,
                target_plan=planned_course_script_plan,
            )
            _record_course_bloc(
                bloc,
                status="generated",
                text=audio_bloc.get("text", ""),
                final_duration_sec=round(final_duration, 3),
                opening_rewritten=parallel_result.get("opening_rewritten", False),
                opening_text=parallel_result.get("opening_text") or "",
                opening_original_start=parallel_result.get("opening_original_start") or "",
                actual_reading=actual_reading,
            )
            generated.append(filename)
            seg_keys = [
                (segments[i]["sub_idx"], segments[i]["passe"])
                for i in bloc["contributing_seg_indices"]
                if segments[i]["dirty"]
            ]
            if seg_keys:
                _mark_content_segments_clean(job_id, seg_keys)
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
                word_budget = int(bloc.get("main_word_budget") or bloc.get("word_budget") or 0)
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
            # Runtime fit : ne reporte pas le surplus au cours suivant par défaut.
            # Si un bloc ne tient pas, il doit être réduit/régénéré.
            runtime_reduction_attempts = []
            synthesis_ok = False
            for reduction_attempt in range(5):
                prepended_for_call = (
                    intra_day_carryover_chunks if intra_day_carryover_active else None
                )
                try:
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
                        next_playlist_item=_next_playlist_item_after(playlist_items, item_idx),
                    )
                    synthesis_ok = True
                except ValueError as e:
                    message = str(e)
                    if "trop long" not in message and "aucun audio généré" not in message:
                        raise
                    current_text = audio_bloc.get("text") or ""
                    pseudo_overflow = [{"text": _tail_words(current_text, 1200)}]
                    _progress(
                        step,
                        len(playlist_items),
                        f"Bloc {bloc['bloc_number']}/7 — réduction IA après dépassement TTS ({reduction_attempt + 1}/5)...",
                    )
                    reduced_text = _reduce_course_bloc_for_runtime_overflow(
                        audio_bloc,
                        pseudo_overflow,
                        model=llm_model,
                    )
                    audio_bloc = dict(audio_bloc)
                    audio_bloc["text"] = reduced_text
                    audio_bloc["word_count"] = count_tts_spoken_words(reduced_text)
                    bloc["text"] = reduced_text
                    bloc["word_count"] = audio_bloc["word_count"]
                    runtime_reduction_attempts.append({
                        "kind": "ai_runtime_exception_reduction",
                        "attempt": reduction_attempt + 1,
                        "error": message[:180],
                        "words_after": audio_bloc["word_count"],
                    })
                    continue
                overflow_words = (
                    sum(len((c.get("text") or "").split()) for c in (runtime_unconsumed_chunks or []))
                    if runtime_fit_enabled and not intra_day_carryover_active
                    else 0
                )
                if not overflow_words:
                    break
                _progress(
                    step,
                    len(playlist_items),
                    f"Bloc {bloc['bloc_number']}/7 — réduction IA du surplus ({overflow_words} mots)...",
                )
                reduced_text = _reduce_course_bloc_for_runtime_overflow(
                    audio_bloc,
                    runtime_unconsumed_chunks,
                    model=llm_model,
                )
                audio_bloc = dict(audio_bloc)
                audio_bloc["text"] = reduced_text
                audio_bloc["word_count"] = count_tts_spoken_words(reduced_text)
                bloc["text"] = reduced_text
                bloc["word_count"] = audio_bloc["word_count"]
                runtime_reduction_attempts.append({
                    "kind": "ai_runtime_overflow_reduction",
                    "attempt": reduction_attempt + 1,
                    "overflow_words": overflow_words,
                    "words_after": audio_bloc["word_count"],
                })
            if not synthesis_ok:
                emergency_words = max(450, int((audio_bloc.get("word_budget") or 1200) * 0.70))
                audio_bloc = dict(audio_bloc)
                audio_bloc["text"] = _limit_text_words_natural(audio_bloc.get("text") or "", emergency_words)
                audio_bloc["word_count"] = count_tts_spoken_words(audio_bloc["text"])
                bloc["text"] = audio_bloc["text"]
                bloc["word_count"] = audio_bloc["word_count"]
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
                    prepended_chunks=None,
                    runtime_fit=runtime_fit_enabled,
                    fast_tts_pipeline=fast_tts_pipeline,
                    llm_model=llm_model,
                    next_playlist_item=_next_playlist_item_after(playlist_items, item_idx),
                )
                runtime_reduction_attempts.append({
                    "kind": "emergency_natural_limit_after_ai_reductions",
                    "words_after": audio_bloc["word_count"],
                })
            attempts = runtime_reduction_attempts + list(attempts or [])
            runtime_conclusions = _runtime_conclusions_from_attempts(attempts)
            runtime_ai_decisions = _runtime_ai_decisions_from_attempts(attempts)
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
                if intra_day_carryover_active:
                    intra_day_carryover_chunks = list(runtime_unconsumed_chunks or [])
                else:
                    overflow_words = sum(
                        len((c.get("text") or "").split())
                        for c in (runtime_unconsumed_chunks or [])
                    )
                    if overflow_words:
                        logger.warning(
                            "PIPELINE_AUDIO_BLOC_RUNTIME_OVERFLOW_AFTER_AI_REDUCE "
                            "formation_job_id=%s content_job_id=%s folder_id=%s "
                            "bloc=%s words=%s action=overflow_remaining_after_5_ai_reductions_no_carryover",
                            formation_job_id, job_id, folder_id, bloc["bloc_number"],
                            overflow_words,
                        )
                    intra_day_carryover_chunks = []
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
            _progress(
                step,
                len(playlist_items),
                f"[BASIC] Bloc {bloc['bloc_number']}/7 — edge-tts runtime fit "
                f"({len(audio_bloc['text'].split())} mots)...",
            )
            logger.info(
                f"   🔊 [BASIC edge-tts] Bloc {bloc['bloc_number']} ({filename}) — "
                "génération calée sur durée réelle…"
            )
            runtime_reduction_attempts = []
            synthesis_ok = False
            for reduction_attempt in range(5):
                prepended_for_call = (
                    intra_day_carryover_chunks if intra_day_carryover_active else None
                )
                try:
                    (
                        final_bytes,
                        voice_duration,
                        fit_method,
                        attempts,
                        _bloc_timings,
                        runtime_unconsumed_chunks,
                        runtime_consumed_chunks,
                    ) = _synthesize_course_audio_synced_to_slides(
                        audio_bloc,
                        [],
                        filename,
                        mock=False,
                        basic_tts=True,
                        progress_callback=lambda msg: _progress(step, len(playlist_items), msg),
                        prepended_chunks=prepended_for_call,
                        runtime_fit=runtime_fit_enabled,
                        fast_tts_pipeline=fast_tts_pipeline,
                        llm_model=llm_model,
                        next_playlist_item=_next_playlist_item_after(playlist_items, item_idx),
                    )
                    synthesis_ok = True
                except ValueError as e:
                    message = str(e)
                    if "trop long" not in message and "aucun audio généré" not in message:
                        raise
                    current_text = audio_bloc.get("text") or ""
                    pseudo_overflow = [{"text": _tail_words(current_text, 1200)}]
                    _progress(
                        step,
                        len(playlist_items),
                        f"Bloc {bloc['bloc_number']}/7 — réduction IA après dépassement TTS ({reduction_attempt + 1}/5)...",
                    )
                    reduced_text = _reduce_course_bloc_for_runtime_overflow(
                        audio_bloc,
                        pseudo_overflow,
                        model=llm_model,
                    )
                    audio_bloc = dict(audio_bloc)
                    audio_bloc["text"] = reduced_text
                    audio_bloc["word_count"] = count_tts_spoken_words(reduced_text)
                    bloc["text"] = reduced_text
                    bloc["word_count"] = audio_bloc["word_count"]
                    runtime_reduction_attempts.append({
                        "kind": "ai_runtime_exception_reduction",
                        "attempt": reduction_attempt + 1,
                        "error": message[:180],
                        "words_after": audio_bloc["word_count"],
                    })
                    continue
                overflow_words = (
                    sum(len((c.get("text") or "").split()) for c in (runtime_unconsumed_chunks or []))
                    if runtime_fit_enabled and not intra_day_carryover_active
                    else 0
                )
                if not overflow_words:
                    break
                _progress(
                    step,
                    len(playlist_items),
                    f"Bloc {bloc['bloc_number']}/7 — réduction IA du surplus ({overflow_words} mots)...",
                )
                reduced_text = _reduce_course_bloc_for_runtime_overflow(
                    audio_bloc,
                    runtime_unconsumed_chunks,
                    model=llm_model,
                )
                audio_bloc = dict(audio_bloc)
                audio_bloc["text"] = reduced_text
                audio_bloc["word_count"] = count_tts_spoken_words(reduced_text)
                bloc["text"] = reduced_text
                bloc["word_count"] = audio_bloc["word_count"]
                runtime_reduction_attempts.append({
                    "kind": "ai_runtime_overflow_reduction",
                    "attempt": reduction_attempt + 1,
                    "overflow_words": overflow_words,
                    "words_after": audio_bloc["word_count"],
                })
            if not synthesis_ok:
                emergency_words = max(450, int((audio_bloc.get("word_budget") or 1200) * 0.70))
                audio_bloc = dict(audio_bloc)
                audio_bloc["text"] = _limit_text_words_natural(audio_bloc.get("text") or "", emergency_words)
                audio_bloc["word_count"] = count_tts_spoken_words(audio_bloc["text"])
                bloc["text"] = audio_bloc["text"]
                bloc["word_count"] = audio_bloc["word_count"]
                (
                    final_bytes,
                    voice_duration,
                    fit_method,
                    attempts,
                    _bloc_timings,
                    runtime_unconsumed_chunks,
                    runtime_consumed_chunks,
                ) = _synthesize_course_audio_synced_to_slides(
                    audio_bloc,
                    [],
                    filename,
                    mock=False,
                    basic_tts=True,
                    progress_callback=lambda msg: _progress(step, len(playlist_items), msg),
                    prepended_chunks=None,
                    runtime_fit=runtime_fit_enabled,
                    fast_tts_pipeline=fast_tts_pipeline,
                    llm_model=llm_model,
                    next_playlist_item=_next_playlist_item_after(playlist_items, item_idx),
                )
                runtime_reduction_attempts.append({
                    "kind": "emergency_natural_limit_after_ai_reductions",
                    "words_after": audio_bloc["word_count"],
                })
            attempts = runtime_reduction_attempts + list(attempts or [])
            runtime_conclusions = _runtime_conclusions_from_attempts(attempts)
            runtime_ai_decisions = _runtime_ai_decisions_from_attempts(attempts)
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
                if intra_day_carryover_active:
                    intra_day_carryover_chunks = list(runtime_unconsumed_chunks or [])
                else:
                    overflow_words = sum(
                        len((c.get("text") or "").split())
                        for c in (runtime_unconsumed_chunks or [])
                    )
                    if overflow_words:
                        logger.warning(
                            "PIPELINE_AUDIO_BLOC_RUNTIME_OVERFLOW_AFTER_AI_REDUCE "
                            "formation_job_id=%s content_job_id=%s folder_id=%s "
                            "bloc=%s words=%s action=overflow_remaining_after_5_ai_reductions_no_carryover",
                            formation_job_id, job_id, folder_id, bloc["bloc_number"],
                            overflow_words,
                        )
                    intra_day_carryover_chunks = []
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
            logger.info(
                f"   TTS Edge voix : {voice_duration:.1f}s "
                f"({fit_method}, chunks={len(attempts)}, cible : {target_sec}s)"
            )
        else:
            _progress(step, len(playlist_items), f"Bloc {bloc['bloc_number']}/7 — génération TTS ({len(audio_bloc['text'].split())} mots)...")
            logger.info(f"   🎙️ Bloc {bloc['bloc_number']} ({filename}) — TTS en cours...")
            tts_errors = []
            for reduction_attempt in range(5):
                try:
                    final_bytes, voice_duration, fit_method, attempts = _synthesize_course_audio_to_fit(
                        audio_bloc,
                        convert_to_speech,
                        _measure_duration_ms,
                        _pad_audio_to_duration,
                        convert_to_speech_with_timestamps=convert_to_speech_with_timestamps,
                    )
                    if tts_errors:
                        attempts = [
                            {
                                "kind": "ai_tts_overflow_reduction",
                                "attempts": len(tts_errors),
                                "words_after": count_tts_spoken_words(audio_bloc.get("text") or ""),
                            }
                        ] + list(attempts or [])
                    break
                except ValueError as e:
                    message = str(e)
                    if "trop long" not in message and "budget prudent" not in message:
                        raise
                    tts_errors.append(message)
                    current_text = audio_bloc.get("text") or ""
                    current_words = count_tts_spoken_words(current_text)
                    budget_words = int(
                        audio_bloc.get("main_word_budget")
                        or audio_bloc.get("word_budget")
                        or current_words
                    )
                    overflow_estimate = max(120, current_words - budget_words + 180)
                    pseudo_overflow = [{"text": _tail_words(current_text, min(1400, overflow_estimate))}]
                    _progress(
                        step,
                        len(playlist_items),
                        f"Bloc {bloc['bloc_number']}/7 — réduction IA avant Fish Audio ({len(tts_errors)}/5)...",
                    )
                    reduced_text = _reduce_course_bloc_for_runtime_overflow(
                        audio_bloc,
                        pseudo_overflow,
                        model=llm_model,
                    )
                    audio_bloc = dict(audio_bloc)
                    audio_bloc["text"] = reduced_text
                    audio_bloc["word_count"] = count_tts_spoken_words(reduced_text)
                    bloc["text"] = reduced_text
                    bloc["word_count"] = audio_bloc["word_count"]
            else:
                logger.warning(
                    "PIPELINE_AUDIO_BLOC_TTS_OVERFLOW_AFTER_AI_REDUCE "
                    "formation_job_id=%s content_job_id=%s folder_id=%s bloc=%s "
                    "errors=%s action=basic_runtime_fallback",
                    formation_job_id, job_id, folder_id, bloc["bloc_number"],
                    len(tts_errors),
                )
                (
                    final_bytes,
                    voice_duration,
                    fit_method,
                    attempts,
                    _bloc_timings,
                    runtime_unconsumed_chunks,
                    runtime_consumed_chunks,
                ) = _synthesize_course_audio_synced_to_slides(
                    audio_bloc,
                    [],
                    filename,
                    mock=False,
                    basic_tts=True,
                    progress_callback=lambda msg: _progress(step, len(playlist_items), msg),
                    prepended_chunks=None,
                    runtime_fit=True,
                    fast_tts_pipeline=fast_tts_pipeline,
                    llm_model=llm_model,
                    next_playlist_item=_next_playlist_item_after(playlist_items, item_idx),
                )
                fit_method = f"{fit_method}, basic_runtime_fallback_after_ai_reduce"
        if len(attempts) > 1:
            logger.info(f"   🔁 Bloc {bloc['bloc_number']} ajusté localement ({fit_method})")
        logger.info(f"   TTS voix : {voice_duration:.1f}s ({fit_method}, cible : {target_sec}s)")

        actual_reading = _actual_reading_from_attempts(attempts)
        if actual_reading:
            audio_bloc["actual_reading"] = actual_reading
            bloc["actual_reading"] = actual_reading
            logger.info(
                "PIPELINE_AUDIO_ACTUAL_READING formation_job_id=%s content_job_id=%s "
                "folder_id=%s bloc=%s input_words=%s fish_words=%s voice_duration=%.1f "
                "wpm=%.1f words_per_hour=%.0f",
                formation_job_id,
                job_id,
                folder_id,
                bloc["bloc_number"],
                actual_reading.get("input_spoken_word_count"),
                actual_reading.get("fish_segment_word_count"),
                float(actual_reading.get("audio_duration_sec") or 0.0),
                float(actual_reading.get("words_per_minute") or 0.0),
                float(actual_reading.get("words_per_hour") or 0.0),
            )

        if not mock:
            _assert_course_voice_duration_within_deadline(
                filename,
                voice_duration,
                target_sec,
                has_start_silence=not basic_tts,
            )

        if basic_tts and runtime_fit_enabled:
            final_duration = _mp3_duration_seconds_no_ffprobe(final_bytes)
            _assert_audio_duration_fills_slot(filename, final_duration, target_sec)
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
            try:
                final_duration = _mp3_duration_seconds_no_ffprobe(final_bytes)
            except Exception:
                final_duration = target_sec
        _assert_audio_duration_within_slot(filename, final_duration, target_sec)
        blob_path = f"{azure_prefix}{filename}"
        upload_blob(CONTAINER_AUDIOS, blob_path, final_bytes)
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
            audio_bloc,
            status="planned",
            text=audio_bloc.get("text", ""),
            final_duration_sec=round(float(final_duration), 3),
            opening_rewritten=opening_rewritten,
            opening_text=opening_text,
            opening_original_start=opening_original_start,
            actual_reading=actual_reading,
            target_plan=planned_course_script_plan,
        )
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
            actual_reading=actual_reading,
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
    # Désactivée par défaut pour préserver les frontières pédagogiques entre
    # cours. Elle ne s'active que via FORMATION_RUNTIME_INTRA_DAY_CARRYOVER=1.
    runtime_carryover_text = ""
    if runtime_fit_enabled and _runtime_intra_day_carryover_enabled() and intra_day_carryover_chunks:
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
    audio_plan_payload = {
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
        "planned_course_blocs": planned_course_script_plan,
    }
    if saved_script_plan.get("course_bloc_overrides"):
        audio_plan_payload["course_bloc_overrides"] = saved_script_plan.get("course_bloc_overrides")
    if saved_script_plan.get("break_overrides"):
        audio_plan_payload["break_overrides"] = saved_script_plan.get("break_overrides")
    if saved_script_plan.get("structured_course_plan"):
        audio_plan_payload["structured_course_plan"] = saved_script_plan.get("structured_course_plan")
    _save_course_script_plan(platform_id, folder_id, audio_plan_payload)
    _save_content_artifact(
        platform_id,
        folder_id,
        _CONTENT_AUDIO_PLAN_BLOB,
        {
            "artifact_type": "content_audio_plan",
            **audio_plan_payload,
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
    actual_reading: dict | None = None,
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
        "main_word_budget": int(bloc.get("main_word_budget") or 0),
        "dirty": bool(bloc.get("dirty")),
        "closing_added": bool(bloc.get("closing_added") or runtime_conclusions),
        "closing_text": bloc.get("closing_text") or "",
        "closing_words": int(bloc.get("closing_words") or 0),
        "runtime_conclusions": runtime_conclusions,
        "runtime_ai_decisions": runtime_ai_decisions,
        "actual_reading": actual_reading or bloc.get("actual_reading") or None,
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


def update_course_script_bloc_text(folder_id: int, bloc_number: int, text: str) -> dict:
    job = get_job_from_db(folder_id)
    if not job:
        raise ValueError("Aucun job pour ce dossier")

    platform_id = job["platform_id"]
    saved = _load_saved_course_script_plan(platform_id, folder_id) or {
        "platform_id": platform_id,
        "folder_id": folder_id,
        "content_job_id": job["id"],
    }
    course_blocs = saved.get("course_blocs") or saved.get("planned_course_blocs") or _build_course_blocs_preview(folder_id, job)
    target = None
    for bloc in course_blocs:
        if int(bloc.get("bloc_number") or 0) == int(bloc_number):
            target = bloc
            break
    if not target:
        raise ValueError("Cours audio introuvable")

    clean_text = (text or "").strip()
    word_count = count_tts_spoken_words(clean_text)
    target.update({
        "text": clean_text,
        "word_count": word_count,
        "manual_edited": True,
        "edited_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    saved["course_blocs"] = course_blocs
    overrides = saved.get("course_bloc_overrides") or {}
    overrides[str(int(bloc_number))] = {
        "text": clean_text,
        "word_count": word_count,
        "edited_at": target["edited_at"],
    }
    saved["course_bloc_overrides"] = overrides
    _save_course_script_plan(platform_id, folder_id, saved)
    return {"bloc": target, "word_count": word_count}


def update_course_script_break_text(folder_id: int, filename: str, intro: str, outro: str) -> dict:
    job = get_job_from_db(folder_id)
    if not job:
        raise ValueError("Aucun job pour ce dossier")

    platform_id = job["platform_id"]
    saved = _load_saved_course_script_plan(platform_id, folder_id) or {
        "platform_id": platform_id,
        "folder_id": folder_id,
        "content_job_id": job["id"],
    }
    breaks = _build_breaks_for_ui(platform_id)
    target = next((br for br in breaks if br.get("filename") == filename), None)
    if not target:
        raise ValueError("Q&A ou pause introuvable")

    override = {
        "intro": (intro or "").strip(),
        "outro": (outro or "").strip(),
        "edited_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    overrides = saved.get("break_overrides") or {}
    overrides[filename] = override
    saved["break_overrides"] = overrides
    _save_course_script_plan(platform_id, folder_id, saved)
    target.update(override)
    target["manual_edited"] = True
    return {"break": target}


def _apply_course_bloc_overrides(blocs: list, overrides: dict | None) -> list:
    overrides = overrides or {}
    if not overrides:
        return blocs
    for bloc in blocs:
        key = str(int(bloc.get("bloc_number") or 0))
        override = overrides.get(key) or {}
        text = (override.get("text") or "").strip()
        if not text:
            continue
        bloc["text"] = text
        bloc["word_count"] = count_tts_spoken_words(text)
        bloc["dirty"] = True
        bloc["manual_edited"] = True
    return blocs


def _apply_break_overrides(breaks: list, overrides: dict | None) -> list:
    overrides = overrides or {}
    if not overrides:
        return breaks
    merged = []
    for br in breaks:
        override = overrides.get(br.get("filename")) or {}
        if override:
            br = {
                **br,
                "intro": override.get("intro", br.get("intro") or ""),
                "outro": override.get("outro", br.get("outro") or ""),
                "manual_edited": True,
                "edited_at": override.get("edited_at"),
            }
        merged.append(br)
    return merged


def _structured_plan_from_artifacts(platform_id: int, folder_id: int) -> dict:
    saved_script_plan = _load_saved_course_script_plan(platform_id, folder_id) or {}
    structured_plan = saved_script_plan.get("structured_course_plan") or {}
    if isinstance(structured_plan, dict) and isinstance(structured_plan.get("courses"), list):
        return structured_plan
    plan_artifact = _load_content_artifact(platform_id, folder_id, _CONTENT_PLAN_BLOB) or {}
    structured_plan = plan_artifact.get("structured_course_plan") or {}
    if isinstance(structured_plan, dict) and isinstance(structured_plan.get("courses"), list):
        return structured_plan
    return {}


def _course_plan_for_number(structured_plan: dict, course_number: int) -> dict | None:
    for course in structured_plan.get("courses") or []:
        try:
            if int(course.get("course_number") or 0) == int(course_number):
                return course
        except Exception:
            continue
    return None


def _update_segment_after_plan_adherence_repair(seg_id: int, original_text: str, final_text: str) -> int:
    stored_text = _preserve_audio_block_marker(original_text, final_text)
    marker_course_number = _extract_audio_block_number(original_text)
    if marker_course_number and not _extract_audio_block_number(stored_text):
        stored_text = f"<<<BLOC_AUDIO_{marker_course_number}>>>\n\n{stored_text}".strip()
    word_count = count_tts_spoken_words(stored_text)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE content_generation_segments
        SET text_content = ?, word_count = ?, dirty = 1,
            humanized = 0, humanization_error = NULL, humanization_signature = NULL,
            reviewed = 0, review_error = NULL, review_signature = NULL
        WHERE id = ?
        """,
        (stored_text, word_count, seg_id),
    )
    conn.commit()
    conn.close()
    return word_count


def _quality_detail_from_result(seg_id: int, sub_idx: int, passe: int, result: dict) -> dict:
    attempts = result.get("attempts") or []
    initial_audit = (attempts[0] or {}).get("audit") if attempts else result.get("final_audit") or {}
    initial_issues = initial_audit.get("issues") or []
    final_audit = result.get("final_audit") or {}
    final_issues = [] if final_audit.get("ok") else (final_audit.get("issues") or [])
    changed = bool(result.get("changed"))
    issue_summary = "; ".join(
        (issue.get("problem") or issue.get("type") or "problème de plan")
        for issue in initial_issues[:3]
    )
    applied = []
    if changed:
        applied.append({
            "rule_violated": "#PLAN",
            "reason": issue_summary or "Réparation ciblée d'adhérence au plan.",
            "original": "",
            "replacement": "",
        })
    rejected = [
        {
            "rule_violated": "#PLAN",
            "reason": issue.get("problem") or issue.get("type") or "Problème non résolu après réparation.",
            "original": issue.get("evidence") or "",
            "replacement": "",
            "reject_reason": "encore signalé au réaudit",
        }
        for issue in final_issues[:5]
    ]
    return {
        "segment_id": seg_id,
        "sub_idx": sub_idx,
        "passe": passe,
        "proposed": max(len(initial_issues), len(applied) + len(rejected)),
        "applied": applied,
        "rejected": rejected,
        "quality_result": {
            "course_number": result.get("course_number"),
            "changed": changed,
            "initial_words": result.get("initial_words"),
            "final_words": result.get("final_words"),
            "final_audit_ok": bool(final_audit.get("ok")),
        },
    }


def _compact_plan_adherence_result(result: dict | None) -> dict | None:
    if not isinstance(result, dict):
        return None
    final_audit = result.get("final_audit") or {}
    issues = final_audit.get("issues") or []
    return {
        "course_number": result.get("course_number"),
        "course_title": result.get("course_title"),
        "version": result.get("version"),
        "changed": bool(result.get("changed")),
        "failed": bool(result.get("failed")),
        "initial_words": result.get("initial_words"),
        "final_words": result.get("final_words"),
        "delta_words": result.get("delta_words"),
        "final_audit_ok": bool(final_audit.get("ok")),
        "issues_count": len(issues),
        "review_timing": result.get("review_timing"),
        "budget_issues_included": bool(result.get("budget_issues_included")),
        "post_calibration_allowed": bool(result.get("post_calibration_allowed")),
    }


def run_plan_adherence_review(folder_id, on_progress=None, model=None, force: bool = False):
    """Review dédiée manuelle : adhérence au plan verrouillé avant budget.

    La génération structurée l'exécute désormais plus tôt, juste après les
    sections et avant le calibrage budget. Cette fonction reste disponible
    pour relance manuelle ou ancien contenu déjà généré.
    """
    def _progress(step, total, msg):
        if on_progress:
            on_progress(step, total, msg)

    job = get_job_from_db(folder_id)
    if not job:
        raise ValueError(f"Aucun content_generation_job pour folder {folder_id}")

    platform_id = job["platform_id"]
    structured_plan = _structured_plan_from_artifacts(platform_id, folder_id)
    if not structured_plan:
        summary = {
            "segments_reviewed": 0,
            "segments_failed": 0,
            "segments_total_completed": 0,
            "segments_already_current": 0,
            "patches_proposed": 0,
            "patches_applied": 0,
            "patches_rejected": 0,
            "review_signature": _PLAN_ADHERENCE_REVIEW_VERSION,
            "review_kind": "plan_adherence",
            "review_label": "Adhérence au plan",
            "force": bool(force),
            "skipped": True,
            "skip_reason": "structured_plan_missing",
            "details": [],
        }
        return summary

    existing_artifact = _load_content_artifact(platform_id, folder_id, _CONTENT_QUALITY_REVIEWS_BLOB) or {}
    existing_by_course = {
        int(record.get("course_number") or 0): record
        for record in (existing_artifact.get("courses") or [])
        if isinstance(record, dict)
    }

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, sub_part_index, sub_part_name, passe, text_content
        FROM content_generation_segments
        WHERE job_id = ? AND status = 'completed'
        ORDER BY sub_part_index ASC, passe ASC
        """,
        (job["id"],),
    )
    rows = cursor.fetchall()
    conn.close()

    total = len(rows)
    details = []
    course_records = []
    total_applied = 0
    total_rejected = 0
    total_proposed = 0
    total_failed = 0
    total_skipped = 0
    previous_summary = ""
    started_at = time.time()

    logger.info(
        "PIPELINE_PLAN_ADHERENCE_START formation_job_id=%s content_job_id=%s folder_id=%s segments=%s force=%s",
        job.get("formation_job_id"),
        job["id"],
        folder_id,
        total,
        bool(force),
    )

    for step, row in enumerate(rows, start=1):
        seg_id, sub_idx, _sub_part_name, passe, text_content = row
        original_text = text_content or ""
        course_number = _extract_audio_block_number(original_text) or int(sub_idx or 0) + 1
        course_plan = _course_plan_for_number(structured_plan, course_number)
        clean_text = _strip_audio_block_markers(original_text)
        if not course_plan:
            previous_summary = _compact_words(clean_text, 100)
            continue

        _progress(step, total, f"Adhérence au plan cours {course_number}/7…")
        signature = _quality_signature(course_plan, clean_text)
        existing = existing_by_course.get(int(course_number)) or {}
        if (
            not force
            and existing.get("final_signature") == signature
            and ((existing.get("final_audit") or {}).get("ok") is True)
        ):
            total_skipped += 1
            skipped_record = {**existing, "skipped": True, "skip_reason": "signature_current"}
            course_records.append(skipped_record)
            details.append({
                "segment_id": seg_id,
                "sub_idx": sub_idx,
                "passe": passe,
                "proposed": 0,
                "applied": [],
                "rejected": [],
            })
            previous_summary = _compact_words(clean_text, 100)
            continue

        try:
            final_text, quality_result = _run_plan_adherence_quality_loop(
                job=job,
                course_plan=course_plan,
                text=clean_text,
                previous_course_summary=previous_summary,
                model=model,
            )
            if final_text.strip() != clean_text.strip() or quality_result.get("changed"):
                final_words = _update_segment_after_plan_adherence_repair(seg_id, original_text, final_text)
                quality_result["changed"] = True
                quality_result["final_words"] = final_words
            detail = _quality_detail_from_result(seg_id, sub_idx, passe, quality_result)
            details.append(detail)
            total_proposed += int(detail.get("proposed") or 0)
            total_applied += len(detail.get("applied") or [])
            total_rejected += len(detail.get("rejected") or [])
            course_records.append(quality_result)
            previous_summary = _compact_words(final_text, 100)
        except Exception as e:
            total_failed += 1
            logger.warning(
                "PIPELINE_PLAN_ADHERENCE_SEGMENT_FAILED formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s error=%s",
                job.get("formation_job_id"),
                job["id"],
                folder_id,
                seg_id,
                str(e)[:300],
            )
            details.append({
                "segment_id": seg_id,
                "sub_idx": sub_idx,
                "passe": passe,
                "proposed": 0,
                "applied": [],
                "rejected": [],
                "error": str(e)[:500],
            })
            previous_summary = _compact_words(clean_text, 100)

        _save_content_artifact(
            platform_id,
            folder_id,
            _CONTENT_QUALITY_REVIEWS_BLOB,
            _artifact_payload(
                {**job, "folder_id": folder_id},
                "content_quality_reviews",
                {
                    "review_kind": "plan_adherence",
                    "review_label": "Adhérence au plan",
                    "version": _PLAN_ADHERENCE_REVIEW_VERSION,
                    "courses": course_records,
                },
            ),
        )

    summary = {
        "segments_reviewed": total - total_failed,
        "segments_failed": total_failed,
        "segments_total_completed": total,
        "segments_already_current": total_skipped,
        "patches_proposed": total_proposed,
        "patches_applied": total_applied,
        "patches_rejected": total_rejected,
        "review_signature": _PLAN_ADHERENCE_REVIEW_VERSION,
        "review_kind": "plan_adherence",
        "review_label": "Adhérence au plan",
        "force": bool(force),
        "details": details,
    }
    _save_content_artifact(
        platform_id,
        folder_id,
        _CONTENT_QUALITY_REVIEWS_BLOB,
        _artifact_payload(
            {**job, "folder_id": folder_id},
            "content_quality_reviews",
            {
                "review_summary": summary,
                "review_kind": "plan_adherence",
                "review_label": "Adhérence au plan",
                "version": _PLAN_ADHERENCE_REVIEW_VERSION,
                "duration_ms": int((time.time() - started_at) * 1000),
                "courses": course_records,
            },
        ),
    )
    logger.info(
        "PIPELINE_PLAN_ADHERENCE_DONE formation_job_id=%s content_job_id=%s folder_id=%s reviewed=%s failed=%s applied=%s rejected=%s duration_ms=%s",
        job.get("formation_job_id"),
        job["id"],
        folder_id,
        summary["segments_reviewed"],
        total_failed,
        total_applied,
        total_rejected,
        int((time.time() - started_at) * 1000),
    )
    return summary


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
    from services.break_transition_service import (
        break_intro_owned_by_previous,
        duration_label,
        is_schedule_neutral_break,
        next_item_type,
    )

    items = _playlist_items_for_platform(platform_id)
    breaks = []
    for idx, (filename, duration, file_type, bloc_num) in enumerate(items):
        if file_type == "cours":
            continue
        intro_owned = break_intro_owned_by_previous(items, idx, file_type)
        if file_type == "qa":
            intro, outro = _get_qa_text(bloc_num)
            ntype = next_item_type(items, idx)
            if ntype in {"pause", "pause_midi"} and not is_schedule_neutral_break(filename):
                next_item = _next_playlist_item_after(items, idx)
                next_intro = _break_intro_text_for_playlist_item(next_item)
                label = duration_label(_playlist_item_duration(next_item), ntype)
                if next_intro:
                    outro = (
                        "Très bien, on clôt ce temps de questions. "
                        f"{next_intro}"
                    )
                elif ntype == "pause_midi" or label == "pause déjeuner":
                    outro = (
                        "Très bien, on clôt ce temps de questions. "
                        "On va maintenant marquer la pause déjeuner, prenez le temps de souffler."
                    )
                elif label:
                    outro = (
                        f"Très bien, on clôt ce temps de questions. "
                        f"On va maintenant prendre une pause de {label}."
                    )
                else:
                    outro = (
                        "Très bien, on clôt ce temps de questions. "
                        "On va maintenant prendre une courte pause."
                    )
        elif file_type == "pause_midi" or filename.startswith("pause_midi_"):
            intro, outro = _get_pause_midi_text()
        elif file_type == "pause":
            intro, outro = _get_pause_text(bloc_num)
        else:
            continue
        if intro_owned:
            intro = ""
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
            "planned_course_blocs": [],
            "planned_course_blocs_source": "none",
            "planned_course_blocs_note": "Aucun job de contenu pour ce dossier.",
            "breaks": [],
            "structured_course_plan": None,
            "content_artifacts": [],
        }

    saved = _load_saved_course_script_plan(job["platform_id"], folder_id)
    breaks = _apply_break_overrides(
        _build_breaks_for_ui(job["platform_id"]),
        (saved or {}).get("break_overrides"),
    )
    content_artifacts = _content_artifacts_for_ui(job["platform_id"], folder_id)

    dirty_info = get_script_dirty_blocs(folder_id)
    dirty_blocs = int(dirty_info.get("dirty_blocs", 0) or 0)
    total_blocs = int(dirty_info.get("total_blocs", 7) or 7)
    if saved and (saved.get("course_blocs") or saved.get("planned_course_blocs")):
        if dirty_blocs:
            note = (
                f"Texte réellement lu lors de la dernière génération TTS. "
                f"{dirty_blocs}/{total_blocs} bloc(s) à régénérer "
                f"(le script a été modifié depuis)."
            )
        else:
            note = "Texte réellement lu lors de la dernière génération TTS."

        planned_course_blocs = saved.get("planned_course_blocs") or []
        if planned_course_blocs:
            planned_source = "last_audio_generation"
            if dirty_blocs:
                planned_note = (
                    f"Texte prévu lors de la dernière génération TTS, avant ajustements runtime. "
                    f"{dirty_blocs}/{total_blocs} bloc(s) à régénérer "
                    f"(le script a été modifié depuis)."
                )
            else:
                planned_note = "Texte prévu lors de la dernière génération TTS, avant ajustements runtime éventuels."
        else:
            planned_course_blocs = _build_course_blocs_preview(folder_id, job)
            planned_source = "preview"
            planned_note = (
                "Prévision recalculée à partir du texte actuel. "
                "L'ancienne génération TTS ne contient pas encore de plan prévu dédié."
            )

        return {
            "course_blocs": saved.get("course_blocs") or planned_course_blocs,
            "course_blocs_source": "last_audio_generation",
            "course_blocs_generated_at": saved.get("generated_at"),
            "course_blocs_mode": saved.get("mode"),
            "course_blocs_note": note,
            "course_blocs_stale": bool(dirty_blocs),
            "planned_course_blocs": planned_course_blocs,
            "planned_course_blocs_source": planned_source,
            "planned_course_blocs_generated_at": saved.get("generated_at") if planned_source == "last_audio_generation" else None,
            "planned_course_blocs_mode": saved.get("mode") if planned_source == "last_audio_generation" else None,
            "planned_course_blocs_note": planned_note,
            "planned_course_blocs_stale": bool(dirty_blocs),
            "dirty_blocs": dirty_blocs,
            "total_blocs": total_blocs,
            "breaks": breaks,
            "structured_course_plan": saved.get("structured_course_plan"),
            "content_artifacts": content_artifacts,
        }

    preview = _build_course_blocs_preview(folder_id, job)
    return {
        "course_blocs": [],
        "course_blocs_source": "none",
        "course_blocs_generated_at": None,
        "course_blocs_mode": None,
        "course_blocs_note": "Aucune génération audio n'a encore été lancée pour ce dossier.",
        "course_blocs_stale": False,
        "planned_course_blocs": preview,
        "planned_course_blocs_source": "preview",
        "planned_course_blocs_generated_at": None,
        "planned_course_blocs_mode": None,
        "planned_course_blocs_note": "Prévision du texte qui serait envoyé au TTS si la génération démarrait maintenant.",
        "planned_course_blocs_stale": False,
        "dirty_blocs": dirty_blocs,
        "total_blocs": total_blocs,
        "breaks": breaks,
        "structured_course_plan": None,
        "content_artifacts": content_artifacts,
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
_HUMANIZATION_MAX_PATCHES = 3
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
_REVIEW_RULESET_VERSION = "2026-05-31-compliance-v8-minimal"
_HUMANIZATION_RULESET_VERSION = "2026-05-23-humanisation-v9-polish-only"
_REVIEW_SIGNATURE_COLUMNS_READY = False

_COMPLIANCE_REVIEW_RULE_GROUPS = [
    {
        "id": "ethique_minimale",
        "label": "Éthique minimale",
        "rules": [14, 15],
        "description": "Respect des tiers et protection des publics vulnérables",
    },
    {
        "id": "anti_hallucination",
        "label": "Anti-hallucination",
        "rules": [17, 18],
        "description": "Anti-hallucination générale et patterns interdits",
    },
    {
        "id": "style_oral_tts",
        "label": "Style oral TTS",
        "rules": [22],
        "description": "Zéro guillemet de discours direct rapporté",
    },
]

_HUMANIZATION_REVIEW_RULE_GROUPS = [
    {
        "id": "humanisation_polish",
        "label": "Finition orale légère",
        "rules": [101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 113, 118],
        "description": "Polish oral : rythme, respirations, transitions locales, densité, présence du formateur, anti-redondance. Ne restructure pas le cours.",
    },
]

_REVIEW_RULE_GROUPS = _COMPLIANCE_REVIEW_RULE_GROUPS

_RULES_CACHE = {"mtime": 0, "text": ""}


def _compliance_review_groups_for_final_pass() -> list[dict]:
    return _COMPLIANCE_REVIEW_RULE_GROUPS


def _load_review_rules() -> str:
    """Charge les règles de review depuis les fichiers modulaires JSON.

    Fallback : ancien markdown monolithique si les fichiers structurés sont
    absents, pour ne pas casser un déploiement incomplet.
    """
    try:
        compliance_text, compliance_mtime = _load_structured_rule_file("compliance-rules.json")
        humanization_text, humanization_mtime = _load_structured_rule_file("humanization-rules.json")
        cache_key = ("modular", compliance_mtime, humanization_mtime)
        if _RULES_CACHE["mtime"] == cache_key and _RULES_CACHE["text"]:
            return _RULES_CACHE["text"]
        rules_text = compliance_text.rstrip() + "\n\n" + humanization_text.strip()
        _RULES_CACHE["mtime"] = cache_key
        _RULES_CACHE["text"] = rules_text
        return rules_text
    except Exception as e:
        logger.warning("⚠️ Règles modulaires indisponibles, fallback markdown historique: %s", e)

    path = _prompt_file_path("prompts-generaux-contenu-formation.md")
    mtime = os.path.getmtime(path)
    cache_key = ("legacy", mtime)
    if _RULES_CACHE["mtime"] == cache_key and _RULES_CACHE["text"]:
        return _RULES_CACHE["text"]
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    m = _re.search(
        r"CONTENU — RÈGLES ABSOLUES\s*\n═+\n(.*?)décroche, les apprentissages ne passent pas\.",
        content,
        _re.DOTALL,
    )
    rules_text = m.group(0) if m else content[:20000]
    _RULES_CACHE["mtime"] = cache_key
    _RULES_CACHE["text"] = rules_text
    return rules_text


def _review_rules_signature(
    rules_text: str,
    groups: list | None = None,
    version: str | None = None,
) -> str:
    payload = _json.dumps(
        {
            "version": version or _REVIEW_RULESET_VERSION,
            "rules": rules_text or "",
            "groups": groups or _REVIEW_RULE_GROUPS,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _current_compliance_review_signature() -> str:
    return _review_rules_signature(
        _load_review_rules(),
        groups=_compliance_review_groups_for_final_pass(),
        version=_REVIEW_RULESET_VERSION,
    )


def _current_humanization_review_signature() -> str:
    return _review_rules_signature(
        _load_review_rules(),
        groups=_HUMANIZATION_REVIEW_RULE_GROUPS,
        version=_HUMANIZATION_RULESET_VERSION,
    )


def _ensure_review_state_columns() -> None:
    """Migrations légères pour tracer les deux passes de review."""
    global _REVIEW_SIGNATURE_COLUMNS_READY
    if _REVIEW_SIGNATURE_COLUMNS_READY:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE content_generation_segments ADD COLUMN review_signature TEXT")
        logger.info("✅ Colonne review_signature ajoutée à content_generation_segments")
    except Exception:
        pass
    for sql, label in (
        ("ALTER TABLE content_generation_segments ADD COLUMN humanized INTEGER DEFAULT 0", "humanized"),
        ("ALTER TABLE content_generation_segments ADD COLUMN humanization_error TEXT", "humanization_error"),
        ("ALTER TABLE content_generation_segments ADD COLUMN humanization_signature TEXT", "humanization_signature"),
    ):
        try:
            cursor.execute(sql)
            logger.info("✅ Colonne %s ajoutée à content_generation_segments", label)
        except Exception:
            pass
    conn.commit()
    conn.close()
    _REVIEW_SIGNATURE_COLUMNS_READY = True


def _ensure_review_signature_column() -> None:
    _ensure_review_state_columns()


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
    chunk_index: int = 1, chunk_total: int = 1, review_context: str = "",
) -> str:
    rules_list = ", ".join(f"#{n}" for n in rule_numbers)
    is_humanization_scope = any(int(n) >= 100 for n in (rule_numbers or []))
    review_contract = _load_prompt_file(
        "reviews",
        "humanization-polish.md" if is_humanization_scope else "compliance-review.md",
    )
    max_patches = _HUMANIZATION_MAX_PATCHES if is_humanization_scope else _REVIEW_MAX_PATCHES
    review_mode = (
        "Pour les règles d'humanisation, tu fais une finition orale légère. "
        "Tu corriges seulement ce qui sonne trop récité, trop dense, trop sec, "
        "trop mécanique, redondant ou mal relié localement. Tu ne restructures "
        "pas le cours et tu ne compenses pas un problème de plan."
        if is_humanization_scope
        else "Tu renvoies un JSON avec uniquement les passages qui violent une règle de ton scope."
    )
    replacement_constraint = (
        "- Pour l'humanisation, `replacement` peut ajouter une courte phrase orale, "
        "une micro-interaction ou un tag comme [pause] si cela corrige vraiment "
        "le rythme, sans changer le fond pédagogique ni le plan verrouillé. "
        "Si la correction exigerait de réécrire toute une section ou de changer "
        "l'architecture, renvoie plutôt {\"patches\": []}. Dans tous les cas, "
        "respecte le budget audio : substitue et condense autant que possible, "
        "ne gonfle pas le segment hors budget mots."
        if is_humanization_scope
        else "- `replacement` corrige la violation sans reformuler le sens, sans ajouter de contenu."
    )
    preference_constraint = (
        "- Ne corrige QUE les non-conformités de rythme/humanisation du scope. "
        "Pas de réécriture complète, pas de préférence personnelle hors règles."
        if is_humanization_scope
        else f"- Ne corrige QUE les vraies violations de {rules_list}. Pas d'autres règles, pas de préférence stylistique."
    )
    return f"""Tu es un reviewer éditorial SPÉCIALISÉ. Tu reçois un extrait de cours oral et un sous-ensemble de règles à vérifier.

CONTRAT DE REVIEW :
{review_contract}

🎯 TON SCOPE EXCLUSIF : {group_label} — {group_desc}
Tu vérifies UNIQUEMENT les règles {rules_list}. Ignore toutes les autres règles.

Tu audites le CHUNK {chunk_index}/{chunk_total} d'un segment plus long. Ne juge que le texte fourni ci-dessous.

TU NE RÉÉCRIS PAS LE TEXTE EN ENTIER. {review_mode}
Si le texte est conforme pour ces règles, renvoie {{"patches": []}}.

{review_context}

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
- Maximum {max_patches} patches. Si tu vois plus de violations, garde les {max_patches} pires.
- `original` doit être trouvable TEL QUEL dans le texte (copie mot pour mot, ponctuation comprise).
{replacement_constraint}
{preference_constraint}
- Le plan JSON verrouillé, s'il est fourni dans le contexte, fait autorité.
- Ne réécris jamais le cours entier. Ne change pas le nombre de parties, ne réordonne pas le plan, ne crée pas de nouveau chapitre.
- Corrige précisément les incohérences, transitions faibles, répétitions, manque d'oralité, conclusion mal fermée, vocabulaire trop abstrait ou problème de périmètre.
- Ne supprime jamais et ne modifie jamais les marqueurs techniques `<<<BLOC_AUDIO_N>>>`.
- Ne gonfle pas le texte : les cours sont calibrés au mot près pour la synthèse audio. Toute correction trop longue sera rejetée par `budget_guard`.
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
    review_context = group.get("_review_context") or ""
    group_rules_text = _extract_rules_for_group(rules_text, group_rules)
    if not group_rules_text.strip():
        return (
            current_text,
            [],
            [],
            f"Règles introuvables pour la salve '{group_label}' ({group_rules})",
            0,
        )
    chunks = _chunk_text(current_text)

    logger.info(
        f"    🔬 Salve '{group_label}' : {len(chunks)} chunk(s), "
        f"concurrency={_REVIEW_CHUNK_CONCURRENCY}"
    )

    def _run_chunk(chunk):
        prompt = _build_review_prompt_focused(
            chunk["text"], group_rules_text, group_label, group_desc, group_rules,
            chunk_index=chunk["index"], chunk_total=chunk["total"],
            review_context=review_context,
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
    group_proposed = 0

    for result in results:
        chunk = result["chunk"]
        if not result.get("ok"):
            return updated_text, group_applied, group_rejected, result.get("error"), group_proposed

        patches = [
            {**p, "review_group": group["id"], "chunk_index": chunk["index"]}
            for p in (result.get("patches") or [])
        ]
        group_proposed += len(patches)
        new_text, applied, rejected = _apply_patches(updated_text, patches)

        updated_text = new_text
        group_applied.extend(applied)
        group_rejected.extend(rejected)

    return updated_text, group_applied, group_rejected, None, group_proposed


def _build_review_prompt(segment_text: str, rules_text: str) -> str:
    return f"""Tu es un reviewer éditorial. Tu reçois un extrait de cours oral \
généré par un autre Claude, et les règles actives que ce cours doit \
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
      "rule_violated": "#22",
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
- `rule_violated` = numéro de règle active (ex: "#14", "#15", "#17", "#18", "#22").

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


def _review_budget_guard_limit(original_word_count: int, review_kind: str) -> int:
    """Cap de croissance mots après une passe review.

    La review peut corriger une intro ou ajouter une respiration, mais elle ne
    doit pas casser le calibrage TTS calculé avant audio. On autorise une petite
    marge, puis on rejette toute salve qui gonfle trop le segment.
    """
    original_word_count = max(0, int(original_word_count or 0))
    is_humanization = (review_kind or "").strip().lower() == "humanization"
    if is_humanization:
        ratio = _env_float("FORMATION_HUMANIZATION_MAX_WORD_GROWTH_RATIO", 0.03, min_value=0.0, max_value=0.20)
        absolute = _env_int("FORMATION_HUMANIZATION_MAX_WORD_GROWTH_WORDS", 120, min_value=1)
    else:
        ratio = _env_float("FORMATION_COMPLIANCE_MAX_WORD_GROWTH_RATIO", 0.04, min_value=0.0, max_value=0.25)
        absolute = _env_int("FORMATION_COMPLIANCE_MAX_WORD_GROWTH_WORDS", 160, min_value=1)
    allowed_extra = max(absolute, int(original_word_count * ratio))
    return original_word_count + allowed_extra


def _apply_review_budget_guard(
    original_text: str,
    candidate_text: str,
    applied: list,
    review_kind: str,
) -> tuple[str, list, list]:
    """Rollback des patches appliqués si la review dépasse le budget mots."""
    if not applied:
        return candidate_text, applied, []
    original_words = count_tts_spoken_words(original_text)
    candidate_words = count_tts_spoken_words(candidate_text)
    max_words = _review_budget_guard_limit(original_words, review_kind)
    if candidate_words <= max_words:
        return candidate_text, applied, []
    rejected = [
        {
            **p,
            "reject_reason": "budget_guard",
            "words_before": original_words,
            "words_after": candidate_words,
            "max_words": max_words,
            "review_kind": review_kind,
        }
        for p in applied
    ]
    return original_text or "", [], rejected


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


def _run_content_review_pass(
    folder_id,
    *,
    on_progress=None,
    model=None,
    force: bool = False,
    groups: list,
    signature_version: str,
    reviewed_column: str,
    error_column: str,
    signature_column: str,
    review_kind: str,
    review_label: str,
    invalidate_compliance_on_change: bool = False,
):
    """
    Révise les segments completed pour un dossier cours.
    Les segments sont relus s'ils n'ont jamais été validés, si les règles ont
    changé depuis leur dernière validation, ou si `force=True`.

    Règles :
    - Skip les segments déjà reviewed=1 uniquement si leur signature de règles
      correspond à la version actuelle.
    - Si patches appliqués : segment.text_content mis à jour, dirty=1 pour
      que le TTS régénère, reviewed=1.
    - Si aucun patch ou tout rejeté : juste reviewed=1, dirty inchangé.

    Renvoie un dict résumé : {segments_reviewed, patches_proposed,
    patches_applied, patches_rejected, details}.
    """
    def _progress(step, total, msg):
        if on_progress:
            on_progress(step, total, msg)

    allowed_columns = {
        "reviewed", "review_error", "review_signature",
        "humanized", "humanization_error", "humanization_signature",
    }
    for col in (reviewed_column, error_column, signature_column):
        if col not in allowed_columns:
            raise ValueError(f"Colonne review non autorisée : {col}")

    job = get_job_from_db(folder_id)
    if not job:
        raise ValueError(f"Aucun content_generation_job pour folder {folder_id}")

    job_id = job["id"]
    formation_job_id = job.get("formation_job_id")
    started_at = time.time()
    logger.info(
        "PIPELINE_REVIEW_START formation_job_id=%s content_job_id=%s folder_id=%s model=%s force=%s",
        formation_job_id,
        job_id,
        folder_id,
        model,
        bool(force),
    )
    rules_text = _load_review_rules()
    review_signature = _review_rules_signature(
        rules_text,
        groups=groups,
        version=signature_version,
    )
    _ensure_review_state_columns()
    _snapshot_pre_review_for_content_job(job_id)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM content_generation_segments WHERE job_id = ? AND status = 'completed'",
        (job_id,),
    )
    total_completed = int(cursor.fetchone()[0] or 0)
    if force:
        cursor.execute(
            """
            SELECT id, sub_part_index, sub_part_name, passe, text_content
            FROM content_generation_segments
            WHERE job_id = ? AND status = 'completed'
            ORDER BY sub_part_index ASC, passe ASC
            """,
            (job_id,),
        )
    else:
        cursor.execute(
            f"""
            SELECT id, sub_part_index, sub_part_name, passe, text_content
            FROM content_generation_segments
            WHERE job_id = ? AND status = 'completed'
              AND (
                    COALESCE({reviewed_column}, 0) = 0
                 OR {signature_column} IS NULL
                 OR {signature_column} != ?
              )
            ORDER BY sub_part_index ASC, passe ASC
            """,
            (job_id, review_signature),
        )
    rows = cursor.fetchall()
    if rows:
        placeholders = ",".join("?" * len(rows))
        cursor.execute(
            f"""
            UPDATE content_generation_segments
            SET {reviewed_column} = 0, {error_column} = NULL
            WHERE id IN ({placeholders})
            """,
            tuple(row[0] for row in rows),
        )
        conn.commit()
    conn.close()

    total = len(rows)
    total_already_current = max(0, total_completed - total) if not force else 0
    if total == 0:
        _progress(0, 0, "Tous les segments sont déjà révisés avec les règles actuelles — rien à faire.")
        logger.info(
            "PIPELINE_REVIEW_DONE formation_job_id=%s content_job_id=%s folder_id=%s reviewed=0 failed=0 proposed=0 applied=0 rejected=0 duration_ms=%s reason=already_current signature=%s",
            formation_job_id,
            job_id,
            folder_id,
            int((time.time() - started_at) * 1000),
            review_signature[:12],
        )
        summary = {
            "segments_reviewed": 0,
            "segments_failed": 0,
            "segments_total_completed": total_completed,
            "segments_already_current": total_already_current,
            "patches_proposed": 0,
            "patches_applied": 0,
            "patches_rejected": 0,
            "review_signature": review_signature,
            "review_kind": review_kind,
            "review_label": review_label,
            "force": bool(force),
            "details": [],
        }
        _save_reviewed_scripts_artifact(
            job,
            folder_id,
            review_kind=review_kind,
            review_label=review_label,
            summary=summary,
        )
        return summary

    logger.info(
        "PIPELINE_REVIEW_PLAN formation_job_id=%s content_job_id=%s folder_id=%s segments_to_review=%s completed=%s already_current=%s groups=%s signature=%s force=%s",
        formation_job_id,
        job_id,
        folder_id,
        total,
        total_completed,
        total_already_current,
        len(groups),
        review_signature[:12],
        bool(force),
    )
    try:
        saved_script_plan = _load_saved_course_script_plan(job["platform_id"], folder_id) or {}
    except Exception:
        saved_script_plan = {}

    total_applied = 0
    total_rejected = 0
    total_proposed = 0
    total_failed = 0
    details = []

    for step, row in enumerate(rows, start=1):
        segment_started_at = time.time()
        seg_id, sub_idx, sub_part_name, passe, text_content = row
        label = f"sous-partie {sub_idx + 1} / passe {passe}"
        _progress(step, total, f"{review_label} {label} ({len(groups)} salves)…")
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

        original_text = text_content or ""
        current_text = original_text
        review_context = _build_course_position_context(
            folder_position=job.get("folder_position"),
            nb_days=job.get("nb_days"),
            total_hours=job.get("total_hours"),
            folder_name=job.get("folder_name") or "",
            sub_part_index=sub_idx,
            passe=passe,
        )
        structured_review_context = _structured_review_context_for_segment(
            saved_script_plan,
            sub_idx,
            original_text,
        )
        if structured_review_context:
            review_context = f"{review_context}\n\n{structured_review_context}"
        all_applied = []
        all_rejected = []
        all_proposed = 0
        segment_error = None  # None = toutes les salves ont réussi jusqu'ici

        for group in groups:
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
            group_with_context = {**group, "_review_context": review_context}
            new_text, applied, rejected, group_error, proposed = _review_group_chunks(
                current_text, rules_text, group_with_context, model=model,
            )
            all_proposed += int(proposed or 0)
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
                    "PIPELINE_REVIEW_GROUP_DONE formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s group=%s proposed=%s applied=%s rejected=%s duration_ms=%s",
                    formation_job_id,
                    job_id,
                    folder_id,
                    seg_id,
                    group_label,
                    proposed,
                    len(applied),
                    len(rejected),
                    int((time.time() - group_started_at) * 1000),
                )
            elif rejected:
                logger.info(
                    "PIPELINE_REVIEW_GROUP_DONE formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s group=%s proposed=%s applied=0 rejected=%s duration_ms=%s",
                    formation_job_id,
                    job_id,
                    folder_id,
                    seg_id,
                    group_label,
                    proposed,
                    len(rejected),
                    int((time.time() - group_started_at) * 1000),
                )
            else:
                logger.info(
                    "PIPELINE_REVIEW_GROUP_DONE formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s group=%s proposed=%s applied=0 rejected=0 duration_ms=%s",
                    formation_job_id,
                    job_id,
                    folder_id,
                    seg_id,
                    group_label,
                    proposed,
                    int((time.time() - group_started_at) * 1000),
                )

        if not segment_error and all_applied:
            guarded_text, guarded_applied, budget_rejected = _apply_review_budget_guard(
                original_text,
                current_text,
                all_applied,
                review_kind,
            )
            if budget_rejected:
                words_before = budget_rejected[0].get("words_before")
                words_after = budget_rejected[0].get("words_after")
                max_words = budget_rejected[0].get("max_words")
                logger.warning(
                    "PIPELINE_REVIEW_BUDGET_GUARD formation_job_id=%s content_job_id=%s "
                    "folder_id=%s segment_id=%s review_kind=%s words_before=%s "
                    "words_after=%s max_words=%s rejected=%s",
                    formation_job_id,
                    job_id,
                    folder_id,
                    seg_id,
                    review_kind,
                    words_before,
                    words_after,
                    max_words,
                    len(budget_rejected),
                )
                current_text = guarded_text
                all_applied = guarded_applied
                all_rejected.extend(budget_rejected)

        current_text = _preserve_audio_block_marker(original_text, current_text)

        # Écriture finale en DB (une seule transaction par segment)
        conn = get_db_connection()
        cursor = conn.cursor()

        if segment_error:
            # Une salve a échoué : review_error, PAS reviewed=1
            cursor.execute(
                f"UPDATE content_generation_segments SET {error_column} = ? WHERE id = ?",
                (segment_error[:500], seg_id),
            )
            conn.commit()
            conn.close()
            total_failed += 1
            details.append({
                "segment_id": seg_id,
                "sub_idx": sub_idx,
                "passe": passe,
                "proposed": all_proposed,
                "error": segment_error,
            })
            logger.warning(
                "PIPELINE_REVIEW_SEGMENT_FAILED formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s proposed=%s applied=%s rejected=%s duration_ms=%s error=%s",
                formation_job_id,
                job_id,
                folder_id,
                seg_id,
                all_proposed,
                len(all_applied),
                len(all_rejected),
                int((time.time() - segment_started_at) * 1000),
                segment_error,
            )
            continue

        # Toutes les salves ont réussi
        if all_applied:
            new_word_count = count_tts_spoken_words(current_text)
            cursor.execute(
                f"""
                UPDATE content_generation_segments
                SET text_content = ?, word_count = ?, dirty = 1,
                    {reviewed_column} = 1, {error_column} = NULL, {signature_column} = ?
                    {", reviewed = 0, review_error = NULL, review_signature = NULL" if invalidate_compliance_on_change else ""}
                WHERE id = ?
                """,
                (current_text, new_word_count, review_signature, seg_id),
            )
            logger.info(
                "PIPELINE_REVIEW_SEGMENT_PATCHED formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s proposed=%s applied=%s rejected=%s new_words=%s",
                formation_job_id,
                job_id,
                folder_id,
                seg_id,
                all_proposed,
                len(all_applied),
                len(all_rejected),
                new_word_count,
            )
        else:
            cursor.execute(
                f"""
                UPDATE content_generation_segments
                SET {reviewed_column} = 1, {error_column} = NULL, {signature_column} = ?
                WHERE id = ?
                """,
                (review_signature, seg_id),
            )
            logger.info(
                "PIPELINE_REVIEW_SEGMENT_CLEAN formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s proposed=%s rejected=%s",
                formation_job_id,
                job_id,
                folder_id,
                seg_id,
                all_proposed,
                len(all_rejected),
            )
        conn.commit()
        conn.close()

        total_applied += len(all_applied)
        total_rejected += len(all_rejected)
        total_proposed += all_proposed
        logger.info(
            "PIPELINE_REVIEW_SEGMENT_DONE formation_job_id=%s content_job_id=%s folder_id=%s segment_id=%s proposed=%s applied=%s rejected=%s duration_ms=%s",
            formation_job_id,
            job_id,
            folder_id,
            seg_id,
            all_proposed,
            len(all_applied),
            len(all_rejected),
            int((time.time() - segment_started_at) * 1000),
        )
        details.append(
            {
                "segment_id": seg_id,
                "sub_idx": sub_idx,
                "passe": passe,
                "proposed": all_proposed,
                "applied": all_applied,
                "rejected": all_rejected,
            }
        )

    _progress(
        total,
        total,
        f"Terminé : {total_proposed} proposés, {total_applied} appliqués, {total_rejected} rejetés, {total_failed} en erreur",
    )
    logger.info(
        "PIPELINE_REVIEW_DONE formation_job_id=%s content_job_id=%s folder_id=%s reviewed=%s/%s proposed=%s applied=%s rejected=%s failed=%s already_current=%s duration_ms=%s signature=%s",
        formation_job_id,
        job_id,
        folder_id,
        total - total_failed,
        total,
        total_proposed,
        total_applied,
        total_rejected,
        total_failed,
        total_already_current,
        int((time.time() - started_at) * 1000),
        review_signature[:12],
    )
    summary = {
        "segments_reviewed": total - total_failed,
        "segments_failed": total_failed,
        "segments_total_completed": total_completed,
        "segments_already_current": total_already_current,
        "patches_proposed": total_proposed,
        "patches_applied": total_applied,
        "patches_rejected": total_rejected,
        "review_signature": review_signature,
        "review_kind": review_kind,
        "review_label": review_label,
        "force": bool(force),
        "details": details,
    }
    _save_reviewed_scripts_artifact(
        job,
        folder_id,
        review_kind=review_kind,
        review_label=review_label,
        summary=summary,
    )
    return summary


def run_humanization_review(folder_id, on_progress=None, model=None, force: bool = False):
    """Passe 1 : finition orale légère avant la conformité stricte."""
    return _run_content_review_pass(
        folder_id,
        on_progress=on_progress,
        model=model,
        force=force,
        groups=_HUMANIZATION_REVIEW_RULE_GROUPS,
        signature_version=_HUMANIZATION_RULESET_VERSION,
        reviewed_column="humanized",
        error_column="humanization_error",
        signature_column="humanization_signature",
        review_kind="humanization",
        review_label="Humanisation",
        invalidate_compliance_on_change=True,
    )


def run_content_review(folder_id, on_progress=None, model=None, force: bool = False):
    """Conformité locale par segment après calibrage budget.

    Passe finale de conformité sur les règles actives minimales :
    #14, #15, #17, #18 et #22.
    """
    return _run_content_review_pass(
        folder_id,
        on_progress=on_progress,
        model=model,
        force=force,
        groups=_compliance_review_groups_for_final_pass(),
        signature_version=_REVIEW_RULESET_VERSION,
        reviewed_column="reviewed",
        error_column="review_error",
        signature_column="review_signature",
        review_kind="local_compliance",
        review_label="Conformité locale",
    )
