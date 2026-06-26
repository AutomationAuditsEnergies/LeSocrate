from __future__ import annotations

"""
Generate slide previews from the final generated course script.

This is the text-first replacement for the legacy audio -> Whisper -> events
prototype. It reads `content_generation_segments`, builds source blocks with a
hard density cap, and asks the LLM to turn each block into one template-ready
slide. No timing is estimated in V1.
"""

import json
import math
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

from database.db import get_db_connection
from services.content_pipeline.artifacts import (
    CONTENT_COURSE_SCRIPTS_BLOB,
    CONTENT_DRAFT_SECTIONS_BLOB,
    CONTENT_PLAN_BLOB,
    load_content_artifact,
)
from services.content_pipeline.prompts import load_prompt_file
from utils.anthropic_client import default_model, post_message
from utils.logger import get_logger

logger = get_logger(__name__)


DEFAULT_MAX_SLIDES = 60
DEFAULT_CONTEXT_WORDS = 1800
DEFAULT_BATCH_SIZE = 6
MAX_SOURCE_TEXT_CHARS = 4200
_SLIDE_DECK_TABLES_READY = False

PACE_PROFILES = {
    "dense": {
        "label": "dense",
        "context_multiplier": 1.35,
        "max_slides_per_block": 3,
        "instruction": "Rythme soutenu: conserve les idées pratiques distinctes, sans transformer chaque détail en slide.",
        "density_instruction": (
            "Rythme soutenu: garde les moments pédagogiques distincts et utiles à l'action. "
            "Une fenêtre peut produire plusieurs slides si elle contient plusieurs preuves textuelles fortes, "
            "mais jamais une slide pour une simple reformulation."
        ),
        "selection_threshold": "moyen-haut",
    },
    "normal": {
        "label": "normal",
        "context_multiplier": 2.0,
        "max_slides_per_block": 2,
        "instruction": "Rythme normal: privilégie les thèmes et points pédagogiques forts.",
        "density_instruction": (
            "Rythme normal: sélectionne seulement les grandes idées, méthodes, pièges, exemples ou synthèses "
            "qui aident vraiment la compréhension. La plupart des fenêtres doivent produire 0 ou 1 slide."
        ),
        "selection_threshold": "haut",
    },
    "synthesis": {
        "label": "synthesis",
        "context_multiplier": 3.0,
        "max_slides_per_block": 1,
        "instruction": "Rythme synthèse: ne garde que les thèmes majeurs et les pivots pédagogiques.",
        "density_instruction": (
            "Rythme synthèse: ne garde que les pivots majeurs du raisonnement. "
            "Une slide doit changer la compréhension de l'apprenant ou poser un repère durable."
        ),
        "selection_threshold": "très haut",
    },
}

SUPPORTED_TEMPLATES = {
    "welcome",
    "chapter_opener",
    "program_year",
    "day_program_7_steps",
    "reflection",
    "definition",
    "comparison",
    "casestudy",
    "situations",
    "steps",
    "flow",
    "story",
    "analogy",
    "framework",
    "opinion",
    "recap",
    "reprise_recap",
    "warning",
    "tip",
    "quotable",
    "pause",
    "qa",
}

LAYOUT_VARIANTS = ("source",)

DEFAULT_LAYOUT_BUDGETS = {
    "expressive": {"title": 42, "text": 110, "item_title": 28, "item_desc": 60},
    "balanced": {"title": 64, "text": 180, "item_title": 42, "item_desc": 90},
    "dense": {"title": 84, "text": 260, "item_title": 56, "item_desc": 130},
}

SLIDE_LAYOUT_BUDGETS = {
    "welcome": {
        "expressive": {"title": 32, "subtitle": 70, "formation_name": 70, "day_label": 24},
        "balanced": {"title": 48, "subtitle": 95, "formation_name": 100, "day_label": 32},
        "dense": {"title": 60, "subtitle": 120, "formation_name": 120, "day_label": 40},
    },
    "program_year": {
        "expressive": {"title": 30, "subtitle": 95, "phase_title": 32, "phase_desc": 55, "day_label": 28},
        "balanced": {"title": 45, "subtitle": 135, "phase_title": 46, "phase_desc": 75, "day_label": 36},
        "dense": {"title": 60, "subtitle": 170, "phase_title": 58, "phase_desc": 90, "day_label": 44},
    },
    "day_program_7_steps": {
        "expressive": {"title": 32, "subtitle": 80, "item_title": 42, "day_label": 28},
        "balanced": {"title": 48, "subtitle": 120, "item_title": 58, "day_label": 36},
        "dense": {"title": 64, "subtitle": 150, "item_title": 72, "day_label": 44},
    },
    "chapter_opener": {
        "expressive": {"title": 48, "chapter_label": 28, "axis_title": 44, "axis_desc": 50},
        "balanced": {"title": 70, "chapter_label": 36, "axis_title": 62, "axis_desc": 80},
        "dense": {"title": 88, "chapter_label": 40, "axis_title": 76, "axis_desc": 110},
    },
    "definition": {
        "expressive": {"term": 32, "eyebrow": 32, "definition": 110, "tag": 18},
        "balanced": {"term": 48, "eyebrow": 42, "definition": 170, "tag": 28},
        "dense": {"term": 62, "eyebrow": 50, "definition": 220, "tag": 36},
    },
    "comparison": {
        "expressive": {"title": 40, "col_label": 28, "col_item": 46},
        "balanced": {"title": 60, "col_label": 42, "col_item": 70},
        "dense": {"title": 80, "col_label": 54, "col_item": 95},
    },
    "casestudy": {
        "expressive": {"title": 44, "eyebrow": 36, "case_tag": 20, "case_title": 26, "case_desc": 70, "case_example": 40},
        "balanced": {"title": 64, "eyebrow": 50, "case_tag": 30, "case_title": 42, "case_desc": 110, "case_example": 70},
        "dense": {"title": 82, "eyebrow": 60, "case_tag": 40, "case_title": 56, "case_desc": 150, "case_example": 100},
    },
    "situations": {
        "expressive": {"title": 46, "eyebrow": 40, "item_title": 28, "item_desc": 60},
        "balanced": {"title": 66, "eyebrow": 55, "item_title": 42, "item_desc": 95},
        "dense": {"title": 86, "eyebrow": 64, "item_title": 54, "item_desc": 130},
    },
    "steps": {
        "expressive": {"title": 46, "step_title": 24, "step_desc": 50},
        "balanced": {"title": 70, "step_title": 36, "step_desc": 90},
        "dense": {"title": 90, "step_title": 48, "step_desc": 120},
    },
    "flow": {
        "expressive": {"title": 42, "eyebrow": 36, "step_title": 18, "step_desc": 42},
        "balanced": {"title": 62, "eyebrow": 48, "step_title": 28, "step_desc": 70},
        "dense": {"title": 80, "eyebrow": 60, "step_title": 38, "step_desc": 95},
    },
    "story": {
        "expressive": {"title": 44, "narrative": 120, "moral": 70},
        "balanced": {"title": 65, "narrative": 200, "moral": 110},
        "dense": {"title": 80, "narrative": 280, "moral": 150},
    },
    "analogy": {
        "expressive": {"title": 40, "concept": 36, "comparison": 36, "text": 90},
        "balanced": {"title": 60, "concept": 54, "comparison": 54, "text": 150},
        "dense": {"title": 75, "concept": 70, "comparison": 78, "text": 210},
    },
    "framework": {
        "expressive": {"title": 44, "center_title": 30, "segment_title": 24, "segment_desc": 44},
        "balanced": {"title": 65, "center_title": 46, "segment_title": 36, "segment_desc": 70},
        "dense": {"title": 80, "center_title": 64, "segment_title": 48, "segment_desc": 95},
    },
    "opinion": {
        "expressive": {"title": 52, "text": 120},
        "balanced": {"title": 78, "text": 200},
        "dense": {"title": 100, "text": 280},
    },
    "recap": {
        "expressive": {"title": 42, "point": 50},
        "balanced": {"title": 64, "point": 80},
        "dense": {"title": 84, "point": 110},
    },
    "reprise_recap": {
        "expressive": {"title": 42, "point": 50},
        "balanced": {"title": 64, "point": 80},
        "dense": {"title": 84, "point": 110},
    },
    "warning": {
        "expressive": {"title": 44, "text": 120, "eyebrow": 32},
        "balanced": {"title": 70, "text": 200, "eyebrow": 44},
        "dense": {"title": 90, "text": 300, "eyebrow": 56},
    },
    "tip": {
        "expressive": {"title": 44, "text": 120},
        "balanced": {"title": 70, "text": 200},
        "dense": {"title": 90, "text": 300},
    },
    "quotable": {
        "expressive": {"quote": 80},
        "balanced": {"quote": 130},
        "dense": {"quote": 190},
    },
    "reflection": {
        "expressive": {"title": 42, "text": 110},
        "balanced": {"title": 64, "text": 180},
        "dense": {"title": 84, "text": 260},
    },
}

PEDAGOGICAL_SHAPE_TO_TEMPLATES = {
    "ouverture": ("welcome", "chapter_opener", "program_year", "day_program_7_steps"),
    "definition_notion": ("definition",),
    "idee_forte": ("reflection", "opinion"),
    "maxime_a_ancrer": ("quotable",),
    "recit_avec_morale": ("story",),
    "image_mentale": ("analogy",),
    "conseil_actionnable": ("tip",),
    "mise_en_garde": ("warning",),
    "opposition_deux_modes": ("comparison",),
    "triade_structurante": ("situations",),
    "progression_ordonnee": ("steps", "flow"),
    "cas_comparables": ("casestudy",),
    "synthese_de_reprise": ("reprise_recap",),
    "synthese_apres_developpement": ("recap",),
    "modele_a_leviers": ("framework",),
}
DEFAULT_SHAPE_BY_TEMPLATE = {
    template: shape
    for shape, templates in PEDAGOGICAL_SHAPE_TO_TEMPLATES.items()
    for template in templates
}

TEMPLATE_ALIASES = {
    "context": "reflection",
    "welcome": "welcome",
    "day_welcome": "welcome",
    "opening": "welcome",
    "chapter_opener": "chapter_opener",
    "chapter_intro": "chapter_opener",
    "theme_opening": "chapter_opener",
    "program_year": "program_year",
    "day_year": "program_year",
    "annual_program": "program_year",
    "parcours_annuel": "program_year",
    "day_program": "program_year",
    "day_program_7_steps": "day_program_7_steps",
    "program_7_steps": "day_program_7_steps",
    "roadmap_7_steps": "day_program_7_steps",
    "agenda": "steps",
    "definition": "definition",
    "concept": "reflection",
    "key_message": "reflection",
    "process": "steps",
    "method": "steps",
    "framework": "framework",
    "steps": "steps",
    "flow": "flow",
    "request_flow": "flow",
    "facilitator": "flow",
    "mots_a_bannir": "situations",
    "expressions_interdites": "situations",
    "blacklist_3": "situations",
    "trois_piliers": "situations",
    "piliers": "situations",
    "triade": "situations",
    "triptyque": "situations",
    "trepied": "situations",
    "trépied": "situations",
    "checklist": "recap",
    "recap": "recap",
    "reprise": "reprise_recap",
    "reprise_recap": "reprise_recap",
    "opening_recap": "reprise_recap",
    "rappel": "reprise_recap",
    "takeaways": "recap",
    "example": "casestudy",
    "case": "casestudy",
    "story": "story",
    "scenario": "casestudy",
    "situations": "situations",
    "situation": "situations",
    "three_situations": "situations",
    "comparison": "comparison",
    "beforeafter": "comparison",
    "synchrone_asynchrone": "comparison",
    "synchronous_asynchronous": "comparison",
    "canaux_synchrones": "comparison",
    "canaux_asynchrones": "comparison",
    "deux_familles": "comparison",
    "warning": "warning",
    "mistake": "warning",
    "risk": "warning",
    "blacklist": "warning",
    "forbidden": "warning",
    "interdit": "warning",
    "bannir": "warning",
    "anti_pattern": "warning",
    "trap": "warning",
    "piege": "warning",
    "tip": "tip",
    "advice": "tip",
    "good_practice": "tip",
    "analogy": "analogy",
    "metaphor": "analogy",
    "data": "recap",
    "numbers": "recap",
    "stats": "recap",
    "chart": "comparison",
    "transition": "reflection",
    "opinion": "opinion",
    "quote": "quotable",
    "quotable": "quotable",
    "journal": "quotable",
    "pause": "pause",
    "qa": "qa",
    "q&a": "qa",
}

EVENT_TYPES = {
    "filler",
    "welcome",
    "chapter_opener",
    "chapter_intro",
    "program_year",
    "day_year",
    "day_program",
    "day_program_7_steps",
    "pause",
    "qa",
    "recap",
    "reprise_recap",
    "definition",
    "concept",
    "example",
    "story",
    "analogy",
    "opinion",
    "transition",
    "framework",
    "process",
    "comparison",
    "data",
    "exercise",
    "warning",
    "tip",
    "quote",
}

_FISHAUDIO_TAG_RE = re.compile(r"\[[^\[\]\n]{1,50}\]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")


def _strip_tts_tags(text: str) -> str:
    if not text:
        return ""
    cleaned = _FISHAUDIO_TAG_RE.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n[ \t]+", "\n", cleaned)
    return cleaned.strip()


def _split_paragraphs(text: str) -> list[str]:
    if not text:
        return []
    return [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]


def _safe_int(value, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, parsed))


def _pace_profile(pace: str | None) -> dict:
    key = (pace or "normal").strip().lower()
    aliases = {
        "rythme_dense": "dense",
        "soutenu": "dense",
        "normal": "normal",
        "theme": "normal",
        "themes": "normal",
        "synthese": "synthesis",
        "synthèse": "synthesis",
        "aere": "synthesis",
        "aéré": "synthesis",
    }
    return PACE_PROFILES.get(aliases.get(key, key), PACE_PROFILES["normal"])


def _json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _canonical_template(template: str | None, fallback: str = "reflection") -> str:
    key = str(template or "").strip().lower()
    if key in SUPPORTED_TEMPLATES:
        return key
    mapped = TEMPLATE_ALIASES.get(key)
    if mapped in SUPPORTED_TEMPLATES:
        return mapped
    return fallback


def _load_slide_template_catalog() -> dict:
    raw = load_prompt_file("slides", "template-catalog.json", fallback="")
    if not raw:
        return {"version": "missing", "templates": []}
    try:
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("PIPELINE_SLIDES_TEMPLATE_CATALOG_INVALID error=%s", exc)
        return {"version": "invalid", "templates": []}
    if not isinstance(data.get("templates"), list):
        data["templates"] = []
    return data


def _template_catalog_for_prompt() -> str:
    catalog = _load_slide_template_catalog()
    templates = []
    for item in catalog.get("templates") or []:
        if not isinstance(item, dict):
            continue
        template_id = _canonical_template(item.get("template_id"))
        if template_id != item.get("template_id"):
            continue
        entry = {
            "template_id": template_id,
            "use_cases": item.get("use_cases") or item.get("families") or [],
            "visual_role": item.get("visual_role") or "",
            "use_when": item.get("use_when") or "",
            "avoid_when": item.get("avoid_when") or "",
            "requires": item.get("requires") or {},
        }
        for optional_key in (
            "strong_signals",
            "rejection_rules",
            "confusable_with",
            "good_examples",
            "bad_examples",
            "schema",
        ):
            optional_value = item.get(optional_key)
            if optional_value:
                entry[optional_key] = optional_value
        templates.append(entry)
    return json.dumps(
        {
            "version": catalog.get("version"),
            "principle": catalog.get("principle"),
            "templates": templates,
        },
        ensure_ascii=False,
        indent=2,
    )


def _pedagogical_shape_mapping_for_prompt() -> str:
    rows = []
    for shape, templates in PEDAGOGICAL_SHAPE_TO_TEMPLATES.items():
        template_list = ", ".join(templates)
        if shape == "progression_ordonnee":
            template_list += " (si 2 à 4 gestes métier enchaînés: flow)"
        rows.append(f"- {shape}: {template_list}")
    return "\n".join(rows)


def _slide_curation_enabled() -> bool:
    value = str(os.getenv("FORMATION_SLIDE_CURATION_ENABLED", "1")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _context_gap_slides_enabled() -> bool:
    return False


def _section_slide_alignment_enabled() -> bool:
    value = str(os.getenv("FORMATION_SECTION_SLIDE_ALIGNMENT_ENABLED", "1")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _section_slide_alignment_workers() -> int:
    return _safe_int(os.getenv("FORMATION_SECTION_SLIDE_ALIGNMENT_WORKERS"), 4, 1, 8)


def _slide_batch_workers(model: str | None = None) -> int:
    model_key = str(model or "").strip().lower()
    default = 3 if model_key.startswith("deepseek") or model_key in {"flash", "pro"} else 1
    return _safe_int(os.getenv("FORMATION_SLIDE_BATCH_WORKERS"), default, 1, 8)


def _ensure_slide_deck_tables() -> None:
    """Persist generated decks so audio sync can run outside the request."""
    global _SLIDE_DECK_TABLES_READY
    if _SLIDE_DECK_TABLES_READY:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS script_slide_decks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NOT NULL,
            content_job_id INTEGER NOT NULL,
            formation_job_id INTEGER,
            platform_id INTEGER,
            generation_mode TEXT DEFAULT 'script',
            pace TEXT,
            max_slides INTEGER,
            model TEXT,
            slides_json TEXT NOT NULL,
            timeline_json TEXT,
            stats_json TEXT,
            pipeline_debug_json TEXT,
            audio_sync_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_script_slide_decks_folder
        ON script_slide_decks(folder_id, content_job_id, created_at)
        """
    )
    conn.commit()
    conn.close()
    _SLIDE_DECK_TABLES_READY = True


def _persist_script_slide_deck(
    source: dict,
    result: dict,
    *,
    pace: str,
    max_slides: int,
    model: str,
) -> int:
    _ensure_slide_deck_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO script_slide_decks
        (folder_id, content_job_id, formation_job_id, platform_id, generation_mode,
         pace, max_slides, model, slides_json, timeline_json, stats_json,
         pipeline_debug_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source["folder_id"],
            source["content_job_id"],
            source.get("formation_job_id"),
            source.get("platform_id"),
            (result.get("stats") or {}).get("generation_mode") or "script",
            pace,
            max_slides,
            model,
            _json_dumps(result.get("slides", [])),
            _json_dumps(result.get("timeline", [])),
            _json_dumps(result.get("stats", {})),
            _json_dumps(result.get("pipeline_debug", {})),
        ),
    )
    deck_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return deck_id


def _decode_deck_row(row) -> dict | None:
    if not row:
        return None
    (
        deck_id,
        folder_id,
        content_job_id,
        formation_job_id,
        platform_id,
        pace,
        max_slides,
        model,
        slides_json,
        timeline_json,
        stats_json,
        pipeline_debug_json,
        audio_sync_json,
        created_at,
        updated_at,
    ) = row
    stats = json.loads(stats_json or "{}")
    stats["deck_id"] = deck_id
    return {
        "deck_id": deck_id,
        "folder_id": folder_id,
        "content_job_id": content_job_id,
        "formation_job_id": formation_job_id,
        "platform_id": platform_id,
        "pace": pace,
        "max_slides": max_slides,
        "model": model,
        "slides": json.loads(slides_json or "[]"),
        "timeline": json.loads(timeline_json or "[]"),
        "stats": stats,
        "pipeline_debug": json.loads(pipeline_debug_json or "{}"),
        "audio_sync": json.loads(audio_sync_json or "{}"),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def get_latest_script_slide_deck(folder_id: int, content_job_id: int | None = None) -> dict | None:
    _ensure_slide_deck_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    params = [folder_id]
    where = "folder_id = ?"
    if content_job_id is not None:
        where += " AND content_job_id = ?"
        params.append(content_job_id)
    cursor.execute(
        f"""
        SELECT id, folder_id, content_job_id, formation_job_id, platform_id, pace,
               max_slides, model, slides_json, timeline_json, stats_json,
               pipeline_debug_json, audio_sync_json, created_at, updated_at
        FROM script_slide_decks
        WHERE {where}
        ORDER BY id DESC
        LIMIT 1
        """,
        tuple(params),
    )
    row = cursor.fetchone()
    conn.close()
    return _decode_deck_row(row)


def _audio_basename(value: str | None) -> str:
    clean = str(value or "").split("?", 1)[0].split("#", 1)[0]
    return os.path.basename(clean).lower()


def _deck_references_audio(deck: dict | None, audio_filename: str) -> bool:
    if not deck or not audio_filename:
        return False

    def matches(value: str | None) -> bool:
        return _audio_basename(value) == audio_filename

    audio_sync = deck.get("audio_sync") or {}
    for timing in audio_sync.get("timings") or []:
        if matches(timing.get("audio_filename") or timing.get("filename")):
            return True

    for slide in deck.get("slides") or []:
        if matches(slide.get("audio_filename")):
            return True
        for segment in slide.get("audio_segments") or []:
            if matches(segment.get("audio_filename") or segment.get("filename")):
                return True

    return False


_COURSE_AUDIO_SLOT_INDEX_BY_FILENAME = {
    "cours_9h00_9h45.mp3": 0,
    "cours_10h05_10h50.mp3": 1,
    "cours_11h05_12h00.mp3": 2,
    "cours_12h20_13h05.mp3": 3,
    "cours_14h45_15h45.mp3": 4,
    "cours_16h00_17h00.mp3": 5,
    "cours_17h25_18h15.mp3": 6,
}

_COURSE_AUDIO_DURATION_BY_FILENAME = {
    "cours_9h00_9h45.mp3": 2700,
    "cours_10h05_10h50.mp3": 2700,
    "cours_11h05_12h00.mp3": 3300,
    "cours_12h20_13h05.mp3": 2700,
    "cours_14h45_15h45.mp3": 3600,
    "cours_16h00_17h00.mp3": 3600,
    "cours_17h25_18h15.mp3": 3000,
}


def _attach_fallback_audio_sync(deck: dict | None, audio_filename: str) -> dict | None:
    """Attach approximate timings when a deck exists but audio sync was not persisted.

    This keeps the projector usable after an audio generation that produced the
    MP3 but failed before update_script_slide_deck_audio_sync wrote exact
    timings. Exact timings still win whenever present.
    """
    if not deck:
        return deck
    target_audio = _audio_basename(audio_filename)
    duration_sec = _COURSE_AUDIO_DURATION_BY_FILENAME.get(target_audio)
    slides = deck.get("slides") or []
    if not duration_sec or not slides:
        return deck
    if _deck_references_audio(deck, target_audio):
        return deck

    max_word = 0
    parsed = []
    for index, slide in enumerate(slides):
        source_ref = slide.get("source_ref") if isinstance(slide, dict) else {}
        if not isinstance(source_ref, dict):
            source_ref = {}
        try:
            start_word = int(source_ref.get("word_start") or source_ref.get("start_word") or 0)
        except (TypeError, ValueError):
            start_word = 0
        try:
            end_word = int(source_ref.get("word_end") or source_ref.get("end_word") or 0)
        except (TypeError, ValueError):
            end_word = 0
        max_word = max(max_word, start_word, end_word)
        parsed.append((index, slide, max(0, start_word), max(0, end_word)))

    if max_word <= 0:
        max_word = max(1, len(parsed))
        parsed = [
            (index, slide, index, index + 1)
            for index, slide in enumerate(slides)
        ]

    timings = []
    previous_end = 0.0
    for index, slide, start_word, end_word in parsed:
        start = max(previous_end, (start_word / max_word) * duration_sec)
        if end_word <= start_word:
            next_start_word = parsed[index + 1][2] if index + 1 < len(parsed) else max_word
            end_word = max(start_word + 1, next_start_word)
        end = min(duration_sec, max(start + 0.5, (end_word / max_word) * duration_sec))
        if index + 1 < len(parsed):
            next_start = (parsed[index + 1][2] / max_word) * duration_sec
            end = min(end, max(start + 0.5, next_start))
        previous_end = end
        timings.append({
            "slide_id": slide.get("slide_id") or f"slide_{index + 1}",
            "slide_index": index,
            "audio_filename": target_audio,
            "start_time": round(start, 3),
            "end_time": round(end, 3),
            "fallback": True,
        })

    cloned = json.loads(json.dumps(deck, ensure_ascii=False))
    cloned["audio_sync"] = {
        **(cloned.get("audio_sync") or {}),
        "enabled": True,
        "mode": (cloned.get("audio_sync") or {}).get("mode") or "fallback_word_positions",
        "generated_files": [target_audio],
        "timings": timings,
        "fallback": True,
    }
    return cloned


def _fallback_deck_for_course_audio(
    target_audio: str,
    *,
    platform_ids: list[int],
    job_ids: list[int],
) -> dict | None:
    slot_index = _COURSE_AUDIO_SLOT_INDEX_BY_FILENAME.get(target_audio)
    if slot_index is None:
        return None

    where_parts = ["cf.position = ?"]
    params: list[int] = [slot_index]
    if platform_ids:
        placeholders = ", ".join("?" for _ in platform_ids)
        where_parts.append(f"ssd.platform_id IN ({placeholders})")
        params.extend(platform_ids)
    if job_ids:
        placeholders = ", ".join("?" for _ in job_ids)
        where_parts.append(f"(ssd.formation_job_id IN ({placeholders}) OR ssd.content_job_id IN ({placeholders}))")
        params.extend(job_ids)
        params.extend(job_ids)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT ssd.id, ssd.folder_id, ssd.content_job_id, ssd.formation_job_id,
               ssd.platform_id, ssd.pace, ssd.max_slides, ssd.model,
               ssd.slides_json, ssd.timeline_json, ssd.stats_json,
               ssd.pipeline_debug_json, ssd.audio_sync_json,
               ssd.created_at, ssd.updated_at
        FROM script_slide_decks ssd
        JOIN cours_folders cf ON cf.id = ssd.folder_id
        WHERE {' AND '.join(where_parts)}
        ORDER BY ssd.id DESC
        LIMIT 1
        """,
        tuple(params),
    )
    row = cursor.fetchone()
    conn.close()
    return _decode_deck_row(row)


def _unique_ints(values: Iterable[int | None]) -> list[int]:
    seen = set()
    result = []
    for value in values:
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed in seen:
            continue
        seen.add(parsed)
        result.append(parsed)
    return result


def get_latest_script_slide_deck_for_audio(
    audio_filename: str,
    platform_id: int | None = None,
) -> dict | None:
    """Find the latest generated deck that contains timings for an audio file."""
    _ensure_slide_deck_tables()
    target_audio = _audio_basename(audio_filename)
    if not target_audio:
        return None

    conn = get_db_connection()
    cursor = conn.cursor()
    platform_ids = _unique_ints([platform_id])
    job_ids: list[int] = []

    if platform_id:
        cursor.execute(
            """
            SELECT pc.source_formation_id,
                   pc.source_module_id,
                   fm.source_pipeline_job_id,
                   fm.source_platform_id
            FROM platform_config pc
            LEFT JOIN formation_modules fm ON fm.id = pc.source_module_id
            WHERE pc.id = ?
            """,
            (platform_id,),
        )
        row = cursor.fetchone()
        if row:
            (
                source_formation_id,
                _source_module_id,
                module_pipeline_job_id,
                module_source_platform_id,
            ) = row
            platform_ids = _unique_ints([*platform_ids, module_source_platform_id])
            job_ids = _unique_ints([source_formation_id, module_pipeline_job_id])

    where_parts = []
    params: list[int] = []
    if platform_ids:
        placeholders = ", ".join("?" for _ in platform_ids)
        where_parts.append(f"platform_id IN ({placeholders})")
        params.extend(platform_ids)
    if job_ids:
        placeholders = ", ".join("?" for _ in job_ids)
        where_parts.append(f"(formation_job_id IN ({placeholders}) OR content_job_id IN ({placeholders}))")
        params.extend(job_ids)
        params.extend(job_ids)

    where_sql = f"WHERE {' OR '.join(where_parts)}" if where_parts else ""
    cursor.execute(
        f"""
        SELECT id, folder_id, content_job_id, formation_job_id, platform_id, pace,
               max_slides, model, slides_json, timeline_json, stats_json,
               pipeline_debug_json, audio_sync_json, created_at, updated_at
        FROM script_slide_decks
        {where_sql}
        ORDER BY id DESC
        LIMIT 200
        """,
        tuple(params),
    )
    rows = cursor.fetchall()
    conn.close()

    for row in rows:
        deck = _decode_deck_row(row)
        if _deck_references_audio(deck, target_audio):
            return deck

    fallback = _fallback_deck_for_course_audio(
        target_audio,
        platform_ids=platform_ids,
        job_ids=job_ids,
    )
    return _attach_fallback_audio_sync(fallback, target_audio)


def update_script_slide_deck_audio_sync(deck_id: int, audio_sync: dict) -> dict | None:
    _ensure_slide_deck_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, folder_id, content_job_id, formation_job_id, platform_id, pace,
               max_slides, model, slides_json, timeline_json, stats_json,
               pipeline_debug_json, audio_sync_json, created_at, updated_at
        FROM script_slide_decks
        WHERE id = ?
        """,
        (deck_id,),
    )
    deck = _decode_deck_row(cursor.fetchone())
    if not deck:
        conn.close()
        return None

    timings = audio_sync.get("timings", []) or []
    timings_by_slide = {}
    for item in timings:
        slide_id = item.get("slide_id")
        if slide_id:
            timings_by_slide.setdefault(slide_id, []).append(item)

    slides = deck["slides"]
    for slide in slides:
        slide_timings = timings_by_slide.get(slide.get("slide_id"), [])
        if not slide_timings:
            continue
        first = slide_timings[0]
        last = slide_timings[-1]
        slide["audio_segments"] = slide_timings
        slide["audio_filename"] = first.get("audio_filename")
        slide["trigger_time"] = first.get("start_time")
        slide["end_time"] = last.get("end_time")
        slide["audio_start_time"] = first.get("start_time")
        slide["audio_end_time"] = last.get("end_time")

    timeline = deck["timeline"]
    for item in timeline:
        slide_index = item.get("slide_index")
        slide = slides[slide_index] if isinstance(slide_index, int) and slide_index < len(slides) else None
        if not slide:
            continue
        item["start_time"] = slide.get("trigger_time")
        item["end_time"] = slide.get("end_time")
        item["audio_filename"] = slide.get("audio_filename")

    stats = deck["stats"]
    stats["audio_sync"] = {
        "enabled": True,
        "mode": audio_sync.get("mode"),
        "timings_count": len(timings),
        "generated_files": audio_sync.get("generated_files", []),
    }

    pipeline_debug = deck["pipeline_debug"]
    pipeline_debug["audio_sync"] = audio_sync

    cursor.execute(
        """
        UPDATE script_slide_decks
        SET slides_json = ?, timeline_json = ?, stats_json = ?,
            pipeline_debug_json = ?, audio_sync_json = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            _json_dumps(slides),
            _json_dumps(timeline),
            _json_dumps(stats),
            _json_dumps(pipeline_debug),
            _json_dumps(audio_sync),
            deck_id,
        ),
    )
    conn.commit()
    conn.close()

    deck["slides"] = slides
    deck["timeline"] = timeline
    deck["stats"] = stats
    deck["pipeline_debug"] = pipeline_debug
    deck["audio_sync"] = audio_sync
    return deck


def _parse_json_object(raw: str) -> dict:
    content = (raw or "").strip()
    if content.startswith("```"):
        parts = content.split("```")
        content = parts[1] if len(parts) > 1 else content
        if content.lstrip().startswith("json"):
            content = content.lstrip()[4:]
    content = content.strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            return json.loads(content[start : end + 1])
        raise


def _load_script_source(folder_id: int, job_id: int | None = None, platform_id: int | None = None) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT cf.id, cf.name, cf.platform_id, cg.id, cg.program_title,
               cg.sub_parts, cg.status, cg.total_words
        FROM cours_folders cf
        JOIN content_generation_jobs cg ON cg.folder_id = cf.id
        WHERE cf.id = ?
        """,
        (folder_id,),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Aucun texte généré trouvé pour le dossier {folder_id}")

    folder_id, folder_name, folder_platform_id, cg_job_id, program_title, sub_parts_json, cg_status, total_words = row

    if platform_id is not None and int(folder_platform_id) != int(platform_id):
        conn.close()
        raise ValueError("Ce dossier n'appartient pas à la plateforme active")

    formation_job = None
    if job_id:
        cursor.execute(
            """
            SELECT id, tp_name, platform_id
            FROM formation_pipeline_jobs
            WHERE id = ?
            """,
            (job_id,),
        )
        formation_job = cursor.fetchone()
        if not formation_job:
            conn.close()
            raise ValueError(f"Job formation {job_id} introuvable")
        if int(formation_job[2]) != int(folder_platform_id):
            conn.close()
            raise ValueError("Le dossier ne correspond pas au job formation demandé")

    cursor.execute(
        """
        SELECT sub_part_index, sub_part_name, passe, text_content, word_count,
               COALESCE(reviewed, 0), COALESCE(dirty, 0)
        FROM content_generation_segments
        WHERE job_id = ? AND status = 'completed'
        ORDER BY sub_part_index ASC, passe ASC
        """,
        (cg_job_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        raise ValueError(f"Aucun segment complété pour le dossier {folder_id}")

    try:
        sub_parts = json.loads(sub_parts_json or "[]")
    except json.JSONDecodeError:
        sub_parts = []

    segments = []
    for idx, row in enumerate(rows):
        sub_idx, sub_name, passe, text, words, reviewed, dirty = row
        clean_text = _strip_tts_tags(text or "")
        if not clean_text:
            continue
        segments.append(
            {
                "segment_id": idx,
                "sub_part_index": sub_idx,
                "sub_part_name": sub_name or (sub_parts[sub_idx] if sub_idx < len(sub_parts) else f"Sous-partie {sub_idx + 1}"),
                "passe": passe,
                "text": clean_text,
                "word_count": len(clean_text.split()) if not words else words,
                "reviewed": bool(reviewed),
                "dirty": bool(dirty),
            }
        )

    if not segments:
        raise ValueError(f"Les segments du dossier {folder_id} sont vides")

    title = program_title or (formation_job[1] if formation_job else "") or folder_name

    return {
        "folder_id": folder_id,
        "folder_name": folder_name,
        "platform_id": folder_platform_id,
        "content_job_id": cg_job_id,
        "formation_job_id": job_id,
        "program_title": title,
        "content_status": cg_status,
        "total_words_declared": total_words or 0,
        "segments": segments,
    }


def _load_beat_sections_artifact(source: dict) -> dict | None:
    def _load(filename: str) -> dict | None:
        try:
            artifact = load_content_artifact(
                int(source["platform_id"]),
                int(source["folder_id"]),
                filename,
            )
        except Exception as exc:
            logger.warning(
                "PIPELINE_SLIDES_BEAT_SECTIONS_LOAD_ERROR file=%s folder=%s content_job=%s error=%s",
                filename,
                source.get("folder_id"),
                source.get("content_job_id"),
                str(exc)[:220],
            )
            return None
        return artifact if isinstance(artifact, dict) else None

    final_artifact = _load(CONTENT_COURSE_SCRIPTS_BLOB)
    final_courses = final_artifact.get("courses") if isinstance(final_artifact, dict) else None
    if isinstance(final_courses, list) and any(
        isinstance(section, dict)
        for course in final_courses
        if isinstance(course, dict)
        for section in (course.get("sections") or [])
    ):
        return final_artifact

    try:
        artifact = load_content_artifact(
            int(source["platform_id"]),
            int(source["folder_id"]),
            CONTENT_DRAFT_SECTIONS_BLOB,
        )
    except Exception as exc:
        logger.warning(
            "PIPELINE_SLIDES_DRAFT_SECTIONS_LOAD_ERROR folder=%s content_job=%s error=%s",
            source.get("folder_id"),
            source.get("content_job_id"),
            str(exc)[:220],
        )
        return None
    return artifact if isinstance(artifact, dict) else None


def _beat_aligned_segments_from_draft(source: dict) -> list[dict]:
    artifact = _load_beat_sections_artifact(source)
    if not artifact:
        return []

    segments = []
    for course in artifact.get("courses") or []:
        if not isinstance(course, dict):
            continue
        try:
            course_number = int(course.get("course_number") or 0)
        except (TypeError, ValueError):
            course_number = 0
        sub_part_index = max(0, course_number - 1)
        course_title = course.get("course_title") or f"Cours {course_number or '?'}"
        for section_index, section in enumerate(course.get("sections") or [], start=1):
            if not isinstance(section, dict):
                continue
            alignment_status = str(section.get("beat_alignment_status") or "")
            if alignment_status.startswith("lost_after_"):
                continue
            beat_texts = section.get("beat_texts") if isinstance(section.get("beat_texts"), list) else []
            for beat in beat_texts:
                if not isinstance(beat, dict):
                    continue
                text = _strip_tts_tags(beat.get("text") or "")
                if not text:
                    continue
                word_count = len(text.split())
                if not word_count:
                    continue
                anchor = beat.get("slide_anchor") if isinstance(beat.get("slide_anchor"), dict) else {}
                segments.append({
                    "segment_id": len(segments),
                    "sub_part_index": sub_part_index,
                    "sub_part_name": f"{course_title} · {section.get('label') or section.get('title') or f'Section {section_index}'}",
                    "passe": 1,
                    "text": text,
                    "word_count": word_count,
                    "reviewed": False,
                    "dirty": False,
                    "beat_id": beat.get("beat_id") or "",
                    "beat_type": beat.get("type") or "",
                    "beat_role": beat.get("role") or "",
                    "spoken_requirement": beat.get("spoken_requirement") or "",
                    "slide_anchor": anchor,
                    "slide_anchor_id": beat.get("slide_anchor_id") or (anchor.get("anchor_id") if anchor.get("enabled") else None),
                    "template_type": beat.get("template_type") or (anchor.get("template_type") if anchor.get("enabled") else None),
                    "source_alignment": "draft_beat_aligned",
                })

    return segments


def _prefer_beat_aligned_source(source: dict) -> dict:
    segments = _beat_aligned_segments_from_draft(source)
    anchored_count = sum(1 for item in segments if item.get("slide_anchor_id"))
    if not segments or not anchored_count:
        return source
    return {
        **source,
        "segments": segments,
        "beat_aligned": True,
        "beat_aligned_segments": len(segments),
        "beat_aligned_anchors": anchored_count,
        "total_words_declared": sum(int(item.get("word_count") or 0) for item in segments),
    }


def _load_content_plan(source: dict) -> dict | None:
    try:
        artifact = load_content_artifact(
            int(source["platform_id"]),
            int(source["folder_id"]),
            CONTENT_PLAN_BLOB,
        )
    except Exception as exc:
        logger.warning(
            "PIPELINE_SLIDES_CONTENT_PLAN_LOAD_ERROR folder=%s content_job=%s error=%s",
            source.get("folder_id"),
            source.get("content_job_id"),
            str(exc)[:220],
        )
        return None
    if not isinstance(artifact, dict):
        return None
    plan = artifact.get("structured_course_plan")
    return plan if isinstance(plan, dict) else None


_GENERIC_ANCHOR_PATTERNS = (
    "idée centrale",
    "idee centrale",
    "idée principale",
    "idee principale",
    "point pédagogique",
    "point pedagogique",
    "formulation orale concrète",
    "formulation orale concrete",
)


def _is_generic_anchor_text(text: str | None) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return True
    return any(pattern in normalized for pattern in _GENERIC_ANCHOR_PATTERNS)


def _first_nonempty_list_item(value, fallback: str = "") -> str:
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if text:
                return text
    return fallback


def _anchor_focus_for_section(section: dict, beat: dict, fallback_title: str) -> str:
    anchor = beat.get("slide_anchor") if isinstance(beat.get("slide_anchor"), dict) else {}
    return (
        str(anchor.get("must_cover") or "").strip()
        or _first_nonempty_list_item(section.get("must_include"), "")
        or str(beat.get("role") or "").strip()
        or fallback_title
    )


def _repair_anchor_context(
    *,
    section: dict,
    beat: dict,
    anchor: dict,
    fallback_part_title: str,
) -> tuple[str, str, str, str, str]:
    section_title = str(section.get("title") or fallback_part_title or "cette section").strip()
    focus = _anchor_focus_for_section(section, beat, section_title)
    role = str(beat.get("role") or "").strip()
    spoken = str(beat.get("spoken_requirement") or "").strip()
    visual_goal = str(anchor.get("visual_goal") or "").strip()
    must_cover = str(anchor.get("must_cover") or "").strip()
    must_not_cover = str(anchor.get("must_not_cover") or "").strip()

    if _is_generic_anchor_text(role):
        role = f"traiter précisément {focus} dans {section_title}"
    if _is_generic_anchor_text(spoken):
        spoken = (
            f"Développer {focus} avec une explication métier concrète, un exemple ou "
            "une règle d'action directement utilisable."
        )
    if _is_generic_anchor_text(visual_goal):
        visual_goal = f"faire mémoriser {focus} dans le cadre de {section_title}"
    if not must_cover:
        must_cover = focus
    if not must_not_cover:
        must_not_cover = "une reformulation générique du titre sans contenu opérationnel"

    return role, spoken, visual_goal, must_cover, must_not_cover


def _extract_slide_anchors_from_plan(plan: dict | None) -> list[dict]:
    anchors = []
    if not isinstance(plan, dict):
        return anchors
    for course in plan.get("courses") or []:
        if not isinstance(course, dict):
            continue
        course_number = _safe_int(course.get("course_number"), 0, 0, 10**6)
        opening = course.get("opening") if isinstance(course.get("opening"), dict) else {}
        for order, beat in enumerate(opening.get("teaching_beats") or [], start=1):
            if not isinstance(beat, dict):
                continue
            slide_anchor = beat.get("slide_anchor") if isinstance(beat.get("slide_anchor"), dict) else {}
            if not slide_anchor.get("enabled"):
                continue
            role, spoken, visual_goal, must_cover, must_not_cover = _repair_anchor_context(
                section=opening,
                beat=beat,
                anchor=slide_anchor,
                fallback_part_title="Introduction",
            )
            template_type = _canonical_template(
                slide_anchor.get("template_type")
                or slide_anchor.get("template_family")
                or beat.get("type")
            )
            anchors.append({
                "anchor_id": str(slide_anchor.get("anchor_id") or f"c{course_number}opening-b{order}-slide"),
                "beat_id": str(beat.get("beat_id") or f"c{course_number}opening-b{order}"),
                "course_number": course_number,
                "course_title": course.get("course_title") or "",
                "part_number": 0,
                "part_title": "Introduction",
                "section_kind": "opening",
                "beat_order": order,
                "beat_type": str(beat.get("type") or "welcome"),
                "role": role,
                "spoken_requirement": spoken,
                "template_type": template_type,
                "pedagogical_shape": _normalize_pedagogical_shape(slide_anchor.get("pedagogical_shape"), template_type),
                "visual_goal": visual_goal,
                "items_expected": slide_anchor.get("items_expected"),
                "must_cover": must_cover,
                "must_not_cover": must_not_cover,
                "fields_hint": slide_anchor.get("fields_hint") if isinstance(slide_anchor.get("fields_hint"), dict) else {},
            })
        for part in course.get("parts") or []:
            if not isinstance(part, dict):
                continue
            part_number = _safe_int(part.get("part_number"), 0, 0, 100)
            for order, beat in enumerate(part.get("teaching_beats") or [], start=1):
                if not isinstance(beat, dict):
                    continue
                slide_anchor = beat.get("slide_anchor") if isinstance(beat.get("slide_anchor"), dict) else {}
                if not slide_anchor.get("enabled"):
                    continue
                role, spoken, visual_goal, must_cover, must_not_cover = _repair_anchor_context(
                    section=part,
                    beat=beat,
                    anchor=slide_anchor,
                    fallback_part_title=part.get("title") or "",
                )
                template_type = _canonical_template(
                    slide_anchor.get("template_type")
                    or slide_anchor.get("template_family")
                    or beat.get("type")
                )
                anchors.append({
                    "anchor_id": str(slide_anchor.get("anchor_id") or f"c{course_number}p{part_number}b{order}-slide"),
                    "beat_id": str(beat.get("beat_id") or f"c{course_number}p{part_number}b{order}"),
                    "course_number": course_number,
                    "course_title": course.get("course_title") or "",
                    "part_number": part_number,
                    "part_title": part.get("title") or "",
                    "section_kind": "part",
                    "beat_order": order,
                    "beat_type": str(beat.get("type") or "concept"),
                    "role": role,
                    "spoken_requirement": spoken,
                    "template_type": template_type,
                    "pedagogical_shape": _normalize_pedagogical_shape(slide_anchor.get("pedagogical_shape"), template_type),
                    "visual_goal": visual_goal,
                    "items_expected": slide_anchor.get("items_expected"),
                    "must_cover": must_cover,
                    "must_not_cover": must_not_cover,
                    "fields_hint": slide_anchor.get("fields_hint") if isinstance(slide_anchor.get("fields_hint"), dict) else {},
                })
        course_conclusion = course.get("course_conclusion") if isinstance(course.get("course_conclusion"), dict) else {}
        for order, beat in enumerate(course_conclusion.get("teaching_beats") or [], start=1):
            if not isinstance(beat, dict):
                continue
            slide_anchor = beat.get("slide_anchor") if isinstance(beat.get("slide_anchor"), dict) else {}
            if not slide_anchor.get("enabled"):
                continue
            role, spoken, visual_goal, must_cover, must_not_cover = _repair_anchor_context(
                section=course_conclusion,
                beat=beat,
                anchor=slide_anchor,
                fallback_part_title="Conclusion du cours",
            )
            template_type = _canonical_template(
                slide_anchor.get("template_type")
                or slide_anchor.get("template_family")
                or beat.get("type")
            )
            anchors.append({
                "anchor_id": str(slide_anchor.get("anchor_id") or f"c{course_number}conclusion-b{order}-slide"),
                "beat_id": str(beat.get("beat_id") or f"c{course_number}conclusion-b{order}"),
                "course_number": course_number,
                "course_title": course.get("course_title") or "",
                "part_number": 900,
                "part_title": "Conclusion du cours",
                "section_kind": "course_conclusion",
                "beat_order": order,
                "beat_type": str(beat.get("type") or "recap"),
                "role": role,
                "spoken_requirement": spoken,
                "template_type": template_type,
                "pedagogical_shape": _normalize_pedagogical_shape(slide_anchor.get("pedagogical_shape"), template_type),
                "visual_goal": visual_goal,
                "items_expected": slide_anchor.get("items_expected"),
                "must_cover": must_cover,
                "must_not_cover": must_not_cover,
                "fields_hint": slide_anchor.get("fields_hint") if isinstance(slide_anchor.get("fields_hint"), dict) else {},
            })
    return anchors


def _assign_slide_anchors_to_source_blocks(source_blocks: list[dict], anchors: list[dict]) -> None:
    for block in source_blocks:
        block["slide_anchors"] = []
    if not source_blocks or not anchors:
        return

    blocks_by_course: dict[int, list[dict]] = {}
    for block in source_blocks:
        try:
            course_number = int(block.get("sub_part_index") or 0) + 1
        except Exception:
            continue
        blocks_by_course.setdefault(course_number, []).append(block)

    anchors_by_course: dict[int, list[dict]] = {}
    for anchor in anchors:
        course_number = int(anchor.get("course_number") or 0)
        anchors_by_course.setdefault(course_number, []).append(anchor)

    for course_number, course_anchors in anchors_by_course.items():
        blocks = sorted(blocks_by_course.get(course_number) or [], key=lambda item: int(item.get("source_block_id") or 0))
        if not blocks:
            continue
        course_anchors = sorted(
            course_anchors,
            key=lambda item: (int(item.get("part_number") or 0), int(item.get("beat_order") or 0)),
        )
        opening_anchors = [anchor for anchor in course_anchors if int(anchor.get("part_number") or 0) == 0]
        conclusion_anchors = [
            anchor for anchor in course_anchors
            if anchor.get("section_kind") == "course_conclusion" or int(anchor.get("part_number") or 0) >= 900
        ]
        body_anchors = [
            anchor for anchor in course_anchors
            if int(anchor.get("part_number") or 0) != 0
            and anchor.get("section_kind") != "course_conclusion"
            and int(anchor.get("part_number") or 0) < 900
        ]
        if opening_anchors:
            blocks[0]["slide_anchors"].extend(opening_anchors)
        course_anchors = body_anchors
        if not course_anchors:
            if conclusion_anchors:
                blocks[-1]["slide_anchors"].extend(conclusion_anchors)
            continue
        if len(blocks) == 1:
            blocks[0]["slide_anchors"].extend(course_anchors)
            if conclusion_anchors:
                blocks[0]["slide_anchors"].extend(conclusion_anchors)
            continue
        total = max(1, len(course_anchors))
        for idx, anchor in enumerate(course_anchors):
            block_idx = min(len(blocks) - 1, int((idx + 0.5) * len(blocks) / total))
            blocks[block_idx]["slide_anchors"].append(anchor)
        if conclusion_anchors:
            blocks[-1]["slide_anchors"].extend(conclusion_anchors)


def _anchor_sort_key(anchor: dict) -> tuple[int, int, str]:
    return (
        int(anchor.get("part_number") or 0),
        int(anchor.get("beat_order") or 0),
        str(anchor.get("anchor_id") or ""),
    )


def _section_part_number(section: dict, section_index: int) -> int:
    kind = str(section.get("kind") or "").strip().lower()
    if kind in {"opening", "intro", "introduction"}:
        return 0
    if kind == "course_conclusion":
        return 900
    if kind == "day_conclusion":
        return 901
    if section.get("part_number") is not None:
        return _safe_int(section.get("part_number"), section_index, 0, 1000)
    return section_index


def _course_section_records_from_artifact(source: dict) -> list[dict]:
    artifact = _load_beat_sections_artifact(source)
    if not artifact:
        return []

    records = []
    for course in artifact.get("courses") or []:
        if not isinstance(course, dict):
            continue
        course_number = _safe_int(course.get("course_number"), 0, 0, 10**6)
        if not course_number:
            continue
        course_title = course.get("course_title") or f"Cours {course_number}"
        sub_part_index = max(0, course_number - 1)
        for section_index, section in enumerate(course.get("sections") or [], start=1):
            if not isinstance(section, dict):
                continue
            text = _strip_tts_tags(section.get("text") or "")
            if not text:
                continue
            part_number = _section_part_number(section, section_index)
            label = section.get("label") or section.get("title") or f"Section {section_index}"
            records.append(
                {
                    "course_number": course_number,
                    "course_title": course_title,
                    "sub_part_index": sub_part_index,
                    "sub_part_name": f"{course_title} · {label}",
                    "section_index": section_index,
                    "section_label": label,
                    "part_number": part_number,
                    "kind": section.get("kind") or "",
                    "title": section.get("title") or label,
                    "text": text,
                    "slide_display_map": (
                        section.get("slide_display_map")
                        if isinstance(section.get("slide_display_map"), list)
                        else []
                    ),
                    "display_order_declared": (
                        section.get("display_order_declared")
                        if isinstance(section.get("display_order_declared"), list)
                        else []
                    ),
                    "display_map_status": section.get("display_map_status") or "none",
                }
            )
    return records


def _split_text_for_alignment(text: str, max_unit_words: int, min_units: int) -> list[str]:
    pieces = []
    for paragraph in _split_paragraphs(text):
        pieces.extend(_split_long_paragraph(paragraph, max_unit_words))
    pieces = [piece.strip() for piece in pieces if piece.strip()]

    while len(pieces) < min_units:
        split_idx = -1
        split_words = 0
        for idx, piece in enumerate(pieces):
            words = piece.split()
            if len(words) > split_words:
                split_idx = idx
                split_words = len(words)
        if split_idx < 0 or split_words <= 1:
            break

        words = pieces[split_idx].split()
        mid = max(1, len(words) // 2)
        left = " ".join(words[:mid]).strip()
        right = " ".join(words[mid:]).strip()
        if not left or not right:
            break
        pieces = pieces[:split_idx] + [left, right] + pieces[split_idx + 1 :]

    return pieces


def _section_alignment_units(section: dict, word_cursor: int, min_units: int = 0) -> tuple[list[dict], int]:
    units = []
    cursor = word_cursor
    pieces = _split_text_for_alignment(section.get("text") or "", max_unit_words=90, min_units=min_units)
    for unit_id, piece in enumerate(pieces):
        words = piece.split()
        if not words:
            continue
        units.append(
            {
                "unit_id": unit_id,
                "text": piece,
                "word_count": len(words),
                "word_start": cursor,
                "word_end": cursor + len(words),
            }
        )
        cursor += len(words)
    return units, cursor


def _display_map_mode() -> str:
    value = str(os.getenv("FORMATION_SLIDES_DISPLAY_MAP_MODE", "shadow")).strip().lower()
    if value in {"off", "0", "false", "no"}:
        return "off"
    if value in {"on", "1", "true", "yes"}:
        return "on"
    return "shadow"


def _fold_display_text(text: str | None) -> str:
    cleaned = _strip_tts_tags(text or "")
    cleaned = cleaned.replace("\u00a0", " ")
    cleaned = cleaned.replace("’", "'").replace("‘", "'").replace("`", "'")
    cleaned = cleaned.replace("«", '"').replace("»", '"').replace("“", '"').replace("”", '"')
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip().lower()


def _fold_display_token(text: str | None) -> str:
    folded = _fold_display_text(text)
    return re.sub(r"^[^\wÀ-ÖØ-öø-ÿ]+|[^\wÀ-ÖØ-öø-ÿ]+$", "", folded)


def _display_text_tokens(text: str) -> list[dict]:
    tokens = []
    for match in re.finditer(r"\S+", text or ""):
        folded = _fold_display_token(match.group(0))
        if not folded:
            continue
        tokens.append({
            "text": match.group(0),
            "folded": folded,
            "start": match.start(),
            "end": match.end(),
        })
    return tokens


def _display_anchor_matches(text: str, anchor_text: str) -> list[dict]:
    tokens = _display_text_tokens(text)
    anchor_tokens = [token["folded"] for token in _display_text_tokens(anchor_text)]
    if not tokens or not anchor_tokens:
        return []
    folded_tokens = [token["folded"] for token in tokens]
    matches = []
    span_len = len(anchor_tokens)
    for idx in range(0, len(folded_tokens) - span_len + 1):
        if folded_tokens[idx:idx + span_len] == anchor_tokens:
            matches.append({
                "word_start": idx,
                "word_end": idx + span_len,
                "char_start": tokens[idx]["start"],
                "char_end": tokens[idx + span_len - 1]["end"],
            })
    return matches


def _display_map_entry_by_beat(section: dict) -> dict[str, dict]:
    entries = section.get("slide_display_map") if isinstance(section.get("slide_display_map"), list) else []
    by_beat = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        beat_id = str(entry.get("beat_id") or "").strip()
        anchor_text = str(entry.get("anchor_text") or "").strip()
        if beat_id and anchor_text:
            by_beat[beat_id] = entry
    return by_beat


def _anchor_with_display_map_fields(anchor: dict, entry: dict) -> dict:
    fields_hint = anchor.get("fields_hint") if isinstance(anchor.get("fields_hint"), dict) else {}
    merged_fields = {**fields_hint}
    quote = str(entry.get("quote") or "").strip()
    items = entry.get("items") if isinstance(entry.get("items"), list) else []
    if quote:
        merged_fields["quote"] = quote
    if items:
        merged_fields["items"] = [str(item).strip() for item in items if str(item).strip()]
    return {
        **anchor,
        "fields_hint": merged_fields,
        "display_map_anchor_text": entry.get("anchor_text") or "",
        "display_map_status": entry.get("status") or "",
    }


def _build_display_map_source_blocks(section: dict, anchors: list[dict], section_word_start: int) -> tuple[list[dict], dict] | None:
    status = str(section.get("display_map_status") or "").strip().lower()
    if status not in {"ok", "repaired", "relocated_patch"}:
        return None
    text = section.get("text") or ""
    tokens = _display_text_tokens(text)
    if not tokens or not anchors:
        return None

    entries_by_beat = _display_map_entry_by_beat(section)
    located = []
    for anchor in anchors:
        beat_id = str(anchor.get("beat_id") or "").strip()
        entry = entries_by_beat.get(beat_id)
        if not entry:
            return None
        matches = _display_anchor_matches(text, entry.get("anchor_text") or "")
        if len(matches) != 1:
            return None
        located.append({
            "anchor": _anchor_with_display_map_fields(anchor, entry),
            "entry": entry,
            "match": matches[0],
        })
    located.sort(key=lambda item: (item["match"]["word_start"], str(item["anchor"].get("anchor_id") or "")))

    blocks = []
    for idx, item in enumerate(located):
        local_word_start = 0 if idx == 0 else int(item["match"]["word_start"])
        local_word_end = (
            int(located[idx + 1]["match"]["word_start"])
            if idx + 1 < len(located)
            else len(tokens)
        )
        if local_word_end <= local_word_start:
            return None
        char_start = 0 if idx == 0 else int(item["match"]["char_start"])
        char_end = (
            int(located[idx + 1]["match"]["char_start"])
            if idx + 1 < len(located)
            else len(text)
        )
        block_text = text[char_start:char_end].strip()
        if not block_text:
            return None
        anchor = item["anchor"]
        assignment = {
            "anchor_id": anchor.get("anchor_id"),
            "unit_start": local_word_start,
            "unit_end": max(local_word_start, local_word_end - 1),
            "fit_reason": "display_map_anchor",
        }
        blocks.append({
            "source_block_id": -1,
            "word_start": section_word_start + local_word_start,
            "word_end": section_word_start + local_word_end,
            "word_count": local_word_end - local_word_start,
            "sub_part_index": section.get("sub_part_index"),
            "sub_part_name": section.get("sub_part_name"),
            "text": block_text,
            "source_refs": [
                {
                    "sub_part_index": section.get("sub_part_index"),
                    "sub_part_name": section.get("sub_part_name"),
                    "passe": 1,
                    "course_number": section.get("course_number"),
                    "part_number": section.get("part_number"),
                    "section_index": section.get("section_index"),
                    "section_label": section.get("section_label"),
                    "slide_anchor_id": anchor.get("anchor_id"),
                    "source_alignment": "section_slide_alignment",
                    "alignment_status": "display_map",
                    "alignment_method": "display_map",
                    "unit_start": assignment["unit_start"],
                    "unit_end": assignment["unit_end"],
                }
            ],
            "slide_anchors": [anchor],
            "source_alignment": "section_slide_alignment",
            "section_alignment": {
                "course_number": section.get("course_number"),
                "part_number": section.get("part_number"),
                "section_index": section.get("section_index"),
                "section_label": section.get("section_label"),
                "anchor_id": anchor.get("anchor_id"),
                "unit_start": assignment["unit_start"],
                "unit_end": assignment["unit_end"],
                "fit_reason": assignment["fit_reason"],
                "status": "display_map",
                "alignment_method": "display_map",
            },
        })
    return blocks, {
        "status": "display_map",
        "alignment_method": "display_map",
        "assignments": [
            {
                "anchor_id": (item["anchor"].get("anchor_id") or ""),
                "word_start": item["match"]["word_start"],
            }
            for item in located
        ],
    }


def _alignment_anchor_payload(anchor: dict) -> dict:
    return {
        "anchor_id": anchor.get("anchor_id"),
        "beat_id": anchor.get("beat_id"),
        "template_type": anchor.get("template_type"),
        "pedagogical_shape": anchor.get("pedagogical_shape"),
        "beat_type": anchor.get("beat_type"),
        "role": anchor.get("role"),
        "visual_goal": anchor.get("visual_goal"),
        "spoken_requirement": anchor.get("spoken_requirement"),
        "must_cover": anchor.get("must_cover"),
        "must_not_cover": anchor.get("must_not_cover"),
        "fields_hint": anchor.get("fields_hint") or {},
    }


def _section_alignment_prompt(section: dict, units: list[dict], anchors: list[dict]) -> str:
    payload_units = [
        {
            "unit_id": unit["unit_id"],
            "word_count": unit["word_count"],
            "text": _shorten(unit["text"], 950),
        }
        for unit in units
    ]
    payload_anchors = [_alignment_anchor_payload(anchor) for anchor in anchors]
    return f"""Tu es un agent d'alignement chronologique texte -> slides.

Objectif: découper le texte final d'une section en plages contiguës, une plage par slide prévue.

RÈGLES NON NÉGOCIABLES:
- Utilise exactement toutes les slides prévues: chaque `anchor_id` doit apparaître une seule fois.
- Utilise toutes les unités de texte: aucune unité ne doit rester non attribuée.
- Les plages doivent être contiguës, sans trou et sans chevauchement.
- La première plage commence à `unit_start = 0`.
- Chaque plage suivante commence exactement à `unit_end précédent + 1`.
- La dernière plage se termine à `unit_end = {max(0, len(units) - 1)}`.
- Tu peux réordonner les slides prévues si le texte le demande, mais tu ne peux jamais revenir à une slide déjà utilisée.
- Exemple autorisé: B puis C puis A. Exemple interdit: A puis B puis A puis C.
- N'utilise pas de cible de mots. Ne cherche pas à équilibrer artificiellement au mot près.
- Pour choisir les bornes, lis surtout `visual_goal`, `spoken_requirement`, `must_cover`, `must_not_cover` et le contenu réel du texte.
- Les phrases de liaison, transitions et nuances doivent être attachées à la slide la plus proche dans le flux oral.
- Réponds uniquement en JSON valide.

FORMAT EXACT:
{{
  "assignments": [
    {{
      "anchor_id": "id exact",
      "unit_start": 0,
      "unit_end": 2,
      "fit_reason": "raison courte"
    }}
  ]
}}

SECTION:
{json.dumps({
    "course_number": section.get("course_number"),
    "course_title": section.get("course_title"),
    "section_label": section.get("section_label"),
    "part_number": section.get("part_number"),
}, ensure_ascii=False)}

SLIDES PRÉVUES:
{json.dumps(payload_anchors, ensure_ascii=False)}

UNITÉS DE TEXTE:
{json.dumps(payload_units, ensure_ascii=False)}
"""


def _fallback_section_assignments(anchors: list[dict], units: list[dict], reason: str) -> list[dict]:
    if not anchors or not units:
        return []
    if len(units) < len(anchors):
        anchors = anchors[: len(units)]
    assignments = []
    cursor = 0
    total_units = len(units)
    for idx, anchor in enumerate(anchors):
        remaining_anchors = len(anchors) - idx
        remaining_units = total_units - cursor
        span = max(1, math.ceil(remaining_units / max(1, remaining_anchors)))
        end = total_units - 1 if idx == len(anchors) - 1 else min(total_units - remaining_anchors, cursor + span - 1)
        assignments.append(
            {
                "anchor_id": anchor.get("anchor_id"),
                "unit_start": cursor,
                "unit_end": end,
                "fit_reason": reason,
                "fallback": True,
            }
        )
        cursor = end + 1
    return assignments


def _validate_section_assignments(raw: dict, anchors: list[dict], units: list[dict]) -> list[dict] | None:
    assignments = raw.get("assignments") if isinstance(raw, dict) else None
    if not isinstance(assignments, list) or len(assignments) != len(anchors):
        return None
    anchor_ids = {str(anchor.get("anchor_id") or "") for anchor in anchors if anchor.get("anchor_id")}
    seen = set()
    cursor = 0
    normalized = []
    last_unit_id = len(units) - 1

    for item in assignments:
        if not isinstance(item, dict):
            return None
        anchor_id = str(item.get("anchor_id") or "").strip()
        if anchor_id not in anchor_ids or anchor_id in seen:
            return None
        try:
            start = int(item.get("unit_start"))
            end = int(item.get("unit_end"))
        except (TypeError, ValueError):
            return None
        if start != cursor or end < start or end > last_unit_id:
            return None
        normalized.append(
            {
                "anchor_id": anchor_id,
                "unit_start": start,
                "unit_end": end,
                "fit_reason": _as_text(item.get("fit_reason"), "")[:240],
            }
        )
        seen.add(anchor_id)
        cursor = end + 1

    if seen != anchor_ids or cursor != len(units):
        return None
    return normalized


def _align_section_to_slide_anchors(section: dict, units: list[dict], anchors: list[dict], model: str) -> tuple[list[dict], dict]:
    ordered_anchors = sorted(anchors, key=_anchor_sort_key)
    if not units or not ordered_anchors:
        return [], {"status": "skipped"}
    if len(units) < len(ordered_anchors):
        return _fallback_section_assignments(ordered_anchors, units, "fallback_units_insufficient"), {
            "status": "fallback",
            "reason": "units_insufficient",
        }

    base_prompt = _section_alignment_prompt(section, units, ordered_anchors)
    last_reason = "invalid_or_failed_alignment"
    for attempt in range(2):
        prompt = base_prompt
        if attempt:
            prompt = f"""{base_prompt}

CORRECTION OBLIGATOIRE:
La réponse précédente était invalide ({last_reason}).
Cette fois, tu dois fournir exactement {len(ordered_anchors)} assignations:
- tous les anchor_id prévus, une seule fois chacun;
- aucune unité oubliée;
- des plages contiguës qui couvrent de 0 à {len(units) - 1};
- JSON valide uniquement.
Choisis les frontières les plus cohérentes avec le texte, sans inventer de contenu.
"""
        try:
            response = post_message(
                [{"role": "user", "content": prompt}],
                max_tokens=2200,
                model=model,
                timeout=180,
                temperature=0 if attempt else None,
            )
            parsed = _parse_json_object(response)
            assignments = _validate_section_assignments(parsed, ordered_anchors, units)
            if assignments:
                return assignments, {
                    "status": "llm_retry" if attempt else "llm",
                    "assignments": len(assignments),
                    "attempts": attempt + 1,
                }
            last_reason = "invalid_assignments"
            logger.warning(
                "PIPELINE_SLIDES_SECTION_ALIGNMENT_INVALID course=%s section=%s anchors=%s units=%s attempt=%s",
                section.get("course_number"),
                section.get("section_label"),
                len(ordered_anchors),
                len(units),
                attempt + 1,
            )
        except Exception as exc:
            last_reason = f"{exc.__class__.__name__}: {str(exc)[:180]}"
            logger.exception(
                "PIPELINE_SLIDES_SECTION_ALIGNMENT_ERROR course=%s section=%s attempt=%s error=%s",
                section.get("course_number"),
                section.get("section_label"),
                attempt + 1,
                exc,
            )

    return _fallback_section_assignments(ordered_anchors, units, "fallback_invalid_alignment"), {
        "status": "fallback",
        "reason": last_reason,
        "attempts": 2,
    }


def _section_alignment_block(
    *,
    block_id: int,
    section: dict,
    units: list[dict],
    assignment: dict,
    anchor: dict | None,
    alignment_status: str,
) -> dict:
    selected = units[int(assignment["unit_start"]) : int(assignment["unit_end"]) + 1]
    first = selected[0]
    last = selected[-1]
    text = "\n\n".join(unit["text"] for unit in selected if unit.get("text")).strip()
    slide_anchors = [anchor] if isinstance(anchor, dict) and anchor.get("anchor_id") else []
    return {
        "source_block_id": block_id,
        "word_start": first["word_start"],
        "word_end": last["word_end"],
        "word_count": sum(int(unit.get("word_count") or 0) for unit in selected),
        "sub_part_index": section.get("sub_part_index"),
        "sub_part_name": section.get("sub_part_name"),
        "text": text,
        "source_refs": [
            {
                "sub_part_index": section.get("sub_part_index"),
                "sub_part_name": section.get("sub_part_name"),
                "passe": 1,
                "course_number": section.get("course_number"),
                "part_number": section.get("part_number"),
                "section_index": section.get("section_index"),
                "section_label": section.get("section_label"),
                "slide_anchor_id": assignment.get("anchor_id"),
                "source_alignment": "section_slide_alignment",
                "alignment_status": alignment_status,
                "unit_start": assignment.get("unit_start"),
                "unit_end": assignment.get("unit_end"),
            }
        ],
        "slide_anchors": slide_anchors,
        "source_alignment": "section_slide_alignment" if slide_anchors else "section_unanchored",
        "section_alignment": {
            "course_number": section.get("course_number"),
            "part_number": section.get("part_number"),
            "section_index": section.get("section_index"),
            "section_label": section.get("section_label"),
            "anchor_id": assignment.get("anchor_id"),
            "unit_start": assignment.get("unit_start"),
            "unit_end": assignment.get("unit_end"),
            "fit_reason": assignment.get("fit_reason") or "",
            "status": alignment_status,
        },
    }


def _build_section_aligned_source_blocks(source: dict, anchors: list[dict], model: str) -> tuple[list[dict], int, dict] | None:
    if not anchors:
        return None

    sections = _course_section_records_from_artifact(source)
    if not sections:
        return None

    logger.info(
        "PIPELINE_SLIDES_SECTION_ALIGNMENT_START folder=%s content_job=%s sections=%s anchors=%s workers=%s model=%s display_map_mode=%s",
        source.get("folder_id"),
        source.get("content_job_id"),
        len(sections),
        len(anchors),
        _section_slide_alignment_workers(),
        model,
        _display_map_mode(),
    )

    anchors_by_section: dict[tuple[int, int], list[dict]] = {}
    for anchor in anchors:
        key = (int(anchor.get("course_number") or 0), int(anchor.get("part_number") or 0))
        anchors_by_section.setdefault(key, []).append(anchor)

    display_map_mode = _display_map_mode()
    display_map_stats = {
        "mode": display_map_mode,
        "sections_available": 0,
        "sections_used": 0,
        "fallback_llm": 0,
        "divergence_p50": None,
        "divergence_p95": None,
    }
    display_map_divergences = []
    word_cursor = 0
    prepared_sections = []

    for section_order, section in enumerate(sections):
        key = (int(section.get("course_number") or 0), int(section.get("part_number") or 0))
        section_anchors = sorted(anchors_by_section.get(key) or [], key=_anchor_sort_key)
        units, word_cursor = _section_alignment_units(section, word_cursor, min_units=len(section_anchors))
        if not units:
            continue
        display_map_result = None
        if display_map_mode != "off" and section_anchors:
            display_map_result = _build_display_map_source_blocks(
                section,
                section_anchors,
                int(units[0].get("word_start") or 0),
            )
            if display_map_result:
                display_map_stats["sections_available"] += 1
        prepared_sections.append(
            {
                "section_order": section_order,
                "section": section,
                "units": units,
                "anchors": section_anchors,
                "display_map_result": display_map_result,
            }
        )

    def _align_prepared_section(prepared: dict) -> tuple[int, list[dict], dict]:
        section = prepared["section"]
        units = prepared["units"]
        section_anchors = prepared["anchors"]
        section_started_at = time.time()
        logger.info(
            "PIPELINE_SLIDES_SECTION_ALIGNMENT_SECTION_START folder=%s content_job=%s course=%s part=%s section=%s anchors=%s units=%s",
            source.get("folder_id"),
            source.get("content_job_id"),
            section.get("course_number"),
            section.get("part_number"),
            section.get("section_label"),
            len(section_anchors),
            len(units),
        )
        assignments, debug = _align_section_to_slide_anchors(section, units, section_anchors, model)
        logger.info(
            "PIPELINE_SLIDES_SECTION_ALIGNMENT_SECTION_DONE folder=%s content_job=%s course=%s part=%s status=%s assignments=%s duration_ms=%s",
            source.get("folder_id"),
            source.get("content_job_id"),
            section.get("course_number"),
            section.get("part_number"),
            debug.get("status"),
            len(assignments),
            int((time.time() - section_started_at) * 1000),
        )
        return prepared["section_order"], assignments, debug

    anchored_sections = [
        prepared
        for prepared in prepared_sections
        if prepared["anchors"]
        and not (display_map_mode == "on" and prepared.get("display_map_result"))
    ]
    alignment_results: dict[int, tuple[list[dict], dict]] = {}
    workers = min(_section_slide_alignment_workers(), max(1, len(anchored_sections)))
    if anchored_sections and workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(_align_prepared_section, prepared): prepared
                for prepared in anchored_sections
            }
            for future in as_completed(future_map):
                prepared = future_map[future]
                try:
                    section_order, assignments, debug = future.result()
                except Exception as exc:
                    section = prepared["section"]
                    logger.exception(
                        "PIPELINE_SLIDES_SECTION_ALIGNMENT_FUTURE_ERROR folder=%s content_job=%s course=%s part=%s error=%s",
                        source.get("folder_id"),
                        source.get("content_job_id"),
                        section.get("course_number"),
                        section.get("part_number"),
                        exc,
                    )
                    section_order = prepared["section_order"]
                    assignments = _fallback_section_assignments(
                        prepared["anchors"],
                        prepared["units"],
                        "fallback_parallel_alignment_error",
                    )
                    debug = {"status": "fallback", "reason": "parallel_alignment_error"}
                alignment_results[section_order] = (assignments, debug)
    else:
        for prepared in anchored_sections:
            section_order, assignments, debug = _align_prepared_section(prepared)
            alignment_results[section_order] = (assignments, debug)

    blocks = []
    alignment_debug = []
    aligned_anchor_count = 0

    for prepared in prepared_sections:
        section = prepared["section"]
        units = prepared["units"]
        section_anchors = prepared["anchors"]

        if not section_anchors:
            blocks.append(
                _section_alignment_block(
                    block_id=len(blocks),
                    section=section,
                    units=units,
                    assignment={
                        "anchor_id": "",
                        "unit_start": 0,
                        "unit_end": len(units) - 1,
                        "fit_reason": "section_without_planned_slide",
                    },
                    anchor=None,
                    alignment_status="unanchored",
                )
            )
            continue

        if display_map_mode == "on" and prepared.get("display_map_result"):
            display_blocks, display_debug = prepared["display_map_result"]
            for display_block in display_blocks:
                display_block = {**display_block, "source_block_id": len(blocks)}
                blocks.append(display_block)
                aligned_anchor_count += 1
            display_map_stats["sections_used"] += 1
            alignment_debug.append(
                {
                    "course_number": section.get("course_number"),
                    "part_number": section.get("part_number"),
                    "section_index": section.get("section_index"),
                    "section_label": section.get("section_label"),
                    "anchors": len(section_anchors),
                    "units": len(units),
                    "status": "display_map",
                    "alignment_method": "display_map",
                    "assignments": display_debug.get("assignments") or [],
                }
            )
            continue

        assignments, debug = alignment_results.get(
            prepared["section_order"],
            (
                _fallback_section_assignments(section_anchors, units, "fallback_missing_parallel_result"),
                {"status": "fallback", "reason": "missing_parallel_result"},
            ),
        )
        if display_map_mode == "on":
            display_map_stats["fallback_llm"] += 1
        anchor_by_id = {str(anchor.get("anchor_id") or ""): anchor for anchor in section_anchors}
        shadow_display_by_anchor = {}
        if display_map_mode == "shadow" and prepared.get("display_map_result"):
            display_blocks, _display_debug = prepared["display_map_result"]
            shadow_display_by_anchor = {
                str((block.get("slide_anchors") or [{}])[0].get("anchor_id") or ""): int(block.get("word_start") or 0)
                for block in display_blocks
                if block.get("slide_anchors")
            }
        for assignment in assignments:
            anchor = anchor_by_id.get(str(assignment.get("anchor_id") or ""))
            if not anchor:
                continue
            if shadow_display_by_anchor:
                try:
                    llm_word_start = int(units[int(assignment.get("unit_start") or 0)].get("word_start") or 0)
                    display_word_start = shadow_display_by_anchor.get(str(anchor.get("anchor_id") or ""))
                    if display_word_start is not None:
                        display_map_divergences.append(abs(display_word_start - llm_word_start))
                except (TypeError, ValueError, IndexError):
                    pass
            blocks.append(
                _section_alignment_block(
                    block_id=len(blocks),
                    section=section,
                    units=units,
                    assignment=assignment,
                    anchor=anchor,
                    alignment_status=debug.get("status") or "unknown",
                )
            )
            aligned_anchor_count += 1
        alignment_debug.append(
            {
                "course_number": section.get("course_number"),
                "part_number": section.get("part_number"),
                "section_index": section.get("section_index"),
                "section_label": section.get("section_label"),
                "anchors": len(section_anchors),
                "units": len(units),
                "status": debug.get("status"),
                "reason": debug.get("reason"),
                "alignment_method": "llm_fallback" if display_map_mode == "on" else "llm",
                "display_map_shadow": (
                    "available"
                    if display_map_mode == "shadow" and prepared.get("display_map_result")
                    else ""
                ),
                "assignments": assignments,
            }
        )

    if not blocks or not aligned_anchor_count:
        return None

    if display_map_divergences:
        sorted_deltas = sorted(display_map_divergences)
        p50_idx = min(len(sorted_deltas) - 1, int(round((len(sorted_deltas) - 1) * 0.50)))
        p95_idx = min(len(sorted_deltas) - 1, int(math.ceil((len(sorted_deltas) - 1) * 0.95)))
        display_map_stats["divergence_p50"] = sorted_deltas[p50_idx]
        display_map_stats["divergence_p95"] = sorted_deltas[p95_idx]

    logger.info(
        "PIPELINE_SLIDES_SECTION_ALIGNMENT_DONE folder=%s content_job=%s blocks=%s aligned_anchors=%s sections=%s",
        source.get("folder_id"),
        source.get("content_job_id"),
        len(blocks),
        aligned_anchor_count,
        len(alignment_debug),
    )

    return blocks, word_cursor, {
        "enabled": True,
        "sections": len(sections),
        "aligned_sections": sum(1 for item in alignment_debug if item.get("anchors")),
        "aligned_anchors": aligned_anchor_count,
        "blocks": len(blocks),
        "workers": workers,
        "display_map": display_map_stats,
        "records": alignment_debug,
    }


def _split_long_paragraph(text: str, max_words: int) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if len(sentences) <= 1:
        return [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)]

    chunks = []
    current = []
    current_words = 0
    for sentence in sentences:
        sentence_words = len(sentence.split())
        if current and current_words + sentence_words > max_words:
            chunks.append(" ".join(current).strip())
            current = []
            current_words = 0
        current.append(sentence)
        current_words += sentence_words
    if current:
        chunks.append(" ".join(current).strip())
    return chunks


def _build_text_units(segments: list[dict], max_unit_words: int) -> tuple[list[dict], int]:
    units = []
    word_cursor = 0

    for segment in segments:
        paragraphs = _split_paragraphs(segment["text"])
        for para_idx, paragraph in enumerate(paragraphs):
            for part_idx, part in enumerate(_split_long_paragraph(paragraph, max_unit_words)):
                words = part.split()
                if not words:
                    continue
                unit = {
                    "unit_id": len(units),
                    "text": part,
                    "word_count": len(words),
                    "word_start": word_cursor,
                    "word_end": word_cursor + len(words),
                    "sub_part_index": segment["sub_part_index"],
                    "sub_part_name": segment["sub_part_name"],
                    "passe": segment["passe"],
                    "paragraph_index": para_idx,
                    "paragraph_part_index": part_idx,
                    "segment_id": segment["segment_id"],
                }
                units.append(unit)
                word_cursor += len(words)

    return units, word_cursor


def _combine_blocks(blocks: Iterable[dict], block_id: int) -> dict:
    blocks = list(blocks)
    if not blocks:
        raise ValueError("Impossible de fusionner une liste de blocs vide")

    first = blocks[0]
    last = blocks[-1]
    source_refs = []
    for block in blocks:
        source_refs.extend(block.get("source_refs", []))

    # Preserve order while removing duplicate source refs.
    unique_refs = []
    seen = set()
    for ref in source_refs:
        key = (ref.get("sub_part_index"), ref.get("passe"))
        if key in seen:
            continue
        seen.add(key)
        unique_refs.append(ref)

    text = "\n\n".join(block["text"] for block in blocks if block.get("text"))
    return {
        "source_block_id": block_id,
        "word_start": first["word_start"],
        "word_end": last["word_end"],
        "word_count": sum(block["word_count"] for block in blocks),
        "sub_part_index": first.get("sub_part_index"),
        "sub_part_name": first.get("sub_part_name"),
        "text": text.strip(),
        "source_refs": unique_refs,
    }


def _build_source_blocks(units: list[dict], total_words: int, target_words: int, max_slides: int) -> tuple[list[dict], int]:
    if not units:
        return [], target_words

    effective_target = max(target_words, math.ceil(total_words / max(1, max_slides)))
    min_words = max(140, int(effective_target * 0.55))
    hard_max = max(effective_target + 160, int(effective_target * 1.35))

    raw_blocks = []
    current = []
    current_words = 0

    for unit in units:
        should_flush = current and current_words >= min_words and current_words + unit["word_count"] > hard_max
        if should_flush:
            raw_blocks.append(_combine_units(current, len(raw_blocks)))
            current = []
            current_words = 0

        current.append(unit)
        current_words += unit["word_count"]

    if current:
        raw_blocks.append(_combine_units(current, len(raw_blocks)))

    if len(raw_blocks) <= max_slides:
        return raw_blocks, effective_target

    merged = []
    count = len(raw_blocks)
    for idx in range(max_slides):
        start = round(idx * count / max_slides)
        end = round((idx + 1) * count / max_slides)
        if end <= start:
            end = min(start + 1, count)
        merged.append(_combine_blocks(raw_blocks[start:end], idx))
    return merged, effective_target


def _build_beat_source_blocks(segments: list[dict]) -> tuple[list[dict], int]:
    blocks = []
    word_cursor = 0
    for segment in segments:
        words = str(segment.get("text") or "").split()
        if not words:
            continue
        word_count = len(words)
        anchor = segment.get("slide_anchor") if isinstance(segment.get("slide_anchor"), dict) else {}
        slide_anchors = []
        if anchor.get("enabled"):
            template_type = _canonical_template(segment.get("template_type") or anchor.get("template_type"))
            slide_anchors.append({
                "anchor_id": str(segment.get("slide_anchor_id") or anchor.get("anchor_id") or "").strip(),
                "beat_id": str(segment.get("beat_id") or "").strip(),
                "course_number": int(segment.get("sub_part_index") or 0) + 1,
                "course_title": "",
                "part_number": 0,
                "part_title": segment.get("sub_part_name") or "",
                "beat_order": len(blocks) + 1,
                "beat_type": str(segment.get("beat_type") or "concept"),
                "role": segment.get("beat_role") or "",
                "spoken_requirement": segment.get("spoken_requirement") or "",
                "template_type": template_type,
                "pedagogical_shape": _normalize_pedagogical_shape(anchor.get("pedagogical_shape"), template_type),
                "visual_goal": anchor.get("visual_goal") or "",
                "items_expected": anchor.get("items_expected"),
                "must_cover": anchor.get("must_cover") or "",
                "must_not_cover": anchor.get("must_not_cover") or "",
                "fields_hint": anchor.get("fields_hint") if isinstance(anchor.get("fields_hint"), dict) else {},
            })
        blocks.append({
            "source_block_id": len(blocks),
            "word_start": word_cursor,
            "word_end": word_cursor + word_count,
            "word_count": word_count,
            "sub_part_index": segment.get("sub_part_index"),
            "sub_part_name": segment.get("sub_part_name"),
            "text": segment.get("text") or "",
            "source_refs": [{
                "sub_part_index": segment.get("sub_part_index"),
                "sub_part_name": segment.get("sub_part_name"),
                "passe": segment.get("passe"),
                "beat_id": segment.get("beat_id"),
                "slide_anchor_id": segment.get("slide_anchor_id"),
                "source_alignment": segment.get("source_alignment"),
            }],
            "slide_anchors": [item for item in slide_anchors if item.get("anchor_id")],
            "beat_id": segment.get("beat_id"),
            "source_alignment": segment.get("source_alignment"),
        })
        word_cursor += word_count
    return blocks, word_cursor


def _combine_units(units: list[dict], block_id: int) -> dict:
    first = units[0]
    last = units[-1]
    source_refs = []
    seen = set()
    for unit in units:
        key = (unit["sub_part_index"], unit["passe"])
        if key in seen:
            continue
        seen.add(key)
        source_refs.append(
            {
                "sub_part_index": unit["sub_part_index"],
                "sub_part_name": unit["sub_part_name"],
                "passe": unit["passe"],
            }
        )

    return {
        "source_block_id": block_id,
        "word_start": first["word_start"],
        "word_end": last["word_end"],
        "word_count": sum(unit["word_count"] for unit in units),
        "sub_part_index": first["sub_part_index"],
        "sub_part_name": first["sub_part_name"],
        "text": "\n\n".join(unit["text"] for unit in units).strip(),
        "source_refs": source_refs,
    }


def _shorten(text: str, max_chars: int = MAX_SOURCE_TEXT_CHARS) -> str:
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "…"


def _shorten_for_layout(value, max_chars: int) -> str:
    clean = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_chars <= 0 or len(clean) <= max_chars:
        return clean
    truncated = clean[: max_chars - 1].rstrip()
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0].rstrip() or truncated
    return truncated + "…"


def _layout_budgets_for(template: str) -> dict:
    return SLIDE_LAYOUT_BUDGETS.get(template) or DEFAULT_LAYOUT_BUDGETS


def _layout_budget_for(template: str, variant: str) -> dict:
    budgets = _layout_budgets_for(template)
    return budgets.get("source") or budgets.get("balanced") or budgets.get("dense") or DEFAULT_LAYOUT_BUDGETS["balanced"]


def _text_exceeds(value, limit: int) -> bool:
    return len(re.sub(r"\s+", " ", str(value or "")).strip()) > limit


def _layout_overages(template: str, data: dict, budget: dict) -> list[str]:
    overages: list[str] = []

    def check(key: str, label: str | None = None):
        if key in data and _text_exceeds(data.get(key), int(budget.get(label or key, 10_000))):
            overages.append(label or key)

    def check_items(items, title_key: str, desc_key: str, title_label: str, desc_label: str):
        if not isinstance(items, list):
            return
        for item in items:
            if isinstance(item, dict):
                if title_key and _text_exceeds(item.get(title_key), int(budget.get(title_label, 10_000))):
                    overages.append(title_label)
                if desc_key and _text_exceeds(item.get(desc_key), int(budget.get(desc_label, 10_000))):
                    overages.append(desc_label)
            elif title_key and _text_exceeds(item, int(budget.get(title_label, 10_000))):
                overages.append(title_label)

    if template in {"pause", "qa"}:
        return []
    if template == "program_year":
        check("title")
        check("subtitle")
        check("day_label")
        check_items(data.get("phases"), "title", "desc", "phase_title", "phase_desc")
        return sorted(set(overages))
    if template == "day_program_7_steps":
        check("title")
        check("subtitle")
        check("day_label")
        for item in data.get("items") or []:
            if _text_exceeds(item, int(budget.get("item_title", 10_000))):
                overages.append("item_title")
        return sorted(set(overages))
    if template == "chapter_opener":
        check("title")
        check("chapter_label")
        check_items(data.get("axes"), "title", "desc", "axis_title", "axis_desc")
        return sorted(set(overages))
    if template == "definition":
        check("term")
        check("eyebrow")
        check("definition")
        for item in data.get("isItems") or []:
            if _text_exceeds(item, int(budget.get("tag", 10_000))):
                overages.append("tag")
        return sorted(set(overages))
    if template == "comparison":
        check("title")
        cols = data.get("cols") if isinstance(data.get("cols"), list) else []
        for col in cols:
            if not isinstance(col, dict):
                continue
            if _text_exceeds(col.get("label"), int(budget.get("col_label", 10_000))):
                overages.append("col_label")
            for item in col.get("items") or []:
                if _text_exceeds(item, int(budget.get("col_item", 10_000))):
                    overages.append("col_item")
        return sorted(set(overages))
    if template == "casestudy":
        check("title")
        check("eyebrow")
        cases = data.get("cases") if isinstance(data.get("cases"), list) else []
        for item in cases:
            if not isinstance(item, dict):
                continue
            for key, label in (("tag", "case_tag"), ("title", "case_title"), ("desc", "case_desc"), ("example", "case_example")):
                if _text_exceeds(item.get(key), int(budget.get(label, 10_000))):
                    overages.append(label)
        return sorted(set(overages))
    if template == "situations":
        check("title")
        check("eyebrow")
        check_items(data.get("items"), "title", "desc", "item_title", "item_desc")
        return sorted(set(overages))
    if template in {"steps", "flow"}:
        check("title")
        check("eyebrow")
        check_items(data.get("steps"), "title", "desc", "step_title", "step_desc")
        return sorted(set(overages))
    if template == "story":
        check("title")
        check("narrative")
        check("moral")
        return sorted(set(overages))
    if template == "analogy":
        for key in ("title", "concept", "comparison", "text"):
            check(key)
        return sorted(set(overages))
    if template == "framework":
        check("title")
        center = data.get("center") if isinstance(data.get("center"), dict) else {}
        if _text_exceeds(center.get("title"), int(budget.get("center_title", 10_000))):
            overages.append("center_title")
        check_items(data.get("segments"), "title", "desc", "segment_title", "segment_desc")
        return sorted(set(overages))
    if template in {"recap", "reprise_recap"}:
        check("title")
        for point in data.get("points") or []:
            if _text_exceeds(point, int(budget.get("point", 10_000))):
                overages.append("point")
        return sorted(set(overages))
    if template == "quotable":
        check("quote")
        return sorted(set(overages))

    check("title")
    check("text")
    check("eyebrow")
    return sorted(set(overages))


def _data_fits_layout(template: str, data: dict, variant: str) -> bool:
    return not _layout_overages(template, data, _layout_budget_for(template, variant))


def _fit_data_to_budget(template: str, data: dict, budget: dict) -> tuple[dict, bool]:
    # Do not silently truncate final slide copy. The LLM receives strict budgets
    # and must reformulate content upstream; if it still exceeds a budget, keep
    # the text intact and expose the over-budget status for review/retry.
    return json.loads(json.dumps(data, ensure_ascii=False)), False


def _resolve_slide_layout(template: str, data: dict, requested_variant: str = "") -> tuple[str, dict, dict]:
    source_budget = _layout_budget_for(template, "source")
    if not _layout_overages(template, data, source_budget):
        return "source", data, {
            "status": "ok",
            "requested_variant": "",
            "over_budget_fields": [],
        }

    overages = _layout_overages(template, data, source_budget)
    fitted_data, changed = _fit_data_to_budget(template, data, source_budget)
    return "source", fitted_data, {
        "status": "compressed_to_source" if changed else "source_over_budget",
        "requested_variant": "",
        "over_budget_fields": overages,
    }


def _layout_budget_prompt() -> str:
    compact = {}
    for template in sorted(SUPPORTED_TEMPLATES):
        compact[template] = _layout_budget_for(template, "source")
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def _prompt_for_blocks(blocks: list[dict], source_title: str, pace_profile: dict, max_batch_slides: int) -> str:
    payload = [
        {
            "source_block_id": block["source_block_id"],
            "sub_part_name": block.get("sub_part_name"),
            "word_count": block.get("word_count"),
            "source_alignment": block.get("source_alignment") or "source_window",
            "text": _shorten(block.get("text", ""), 3600),
            "slide_anchors": [
                {
                    "anchor_id": anchor.get("anchor_id"),
                    "beat_id": anchor.get("beat_id"),
                    "part_title": anchor.get("part_title"),
                    "beat_type": anchor.get("beat_type"),
                    "spoken_requirement": anchor.get("spoken_requirement"),
                    "planned_template_type": anchor.get("template_type"),
                    "planned_pedagogical_shape": anchor.get("pedagogical_shape"),
                    "visual_goal": anchor.get("visual_goal"),
                    "items_expected": anchor.get("items_expected"),
                    "must_cover": anchor.get("must_cover"),
                    "must_not_cover": anchor.get("must_not_cover"),
                    "fields_hint": anchor.get("fields_hint") or {},
                }
                for anchor in block.get("slide_anchors") or []
            ],
        }
        for block in blocks
    ]
    anchors_count = sum(len(block.get("slide_anchors") or []) for block in blocks)

    curation_enabled = _slide_curation_enabled()
    curation_rules = """
COUCHE DE CURATION IA:
- Tu n'es pas en train de résumer mécaniquement le texte. Tu sélectionnes les moments qui gagnent vraiment à devenir visuels.
- Le texte final est la source de vérité.
- Quand `source_alignment` vaut `section_slide_alignment`, les `slide_anchors` imposent l'existence et l'emplacement de la slide: exactement 1 slide par fenêtre alignée.
- Le `planned_template_type` d'un anchor est seulement le choix initial du plan. Tu dois le remplacer si le texte réel correspond mieux à un autre template du catalogue.
- Le `planned_pedagogical_shape` d'un anchor explique pourquoi le beat existe: utilise-le comme indice fort, mais change-le si le texte réel le contredit et explique-le dans `template_decision_reason`.
- Hors `section_slide_alignment`, les `slide_anchors` restent des indices pédagogiques forts.
- Si un anchor hors section alignée ne correspond pas clairement au texte réel, ignore-le.
- Si le texte réel contient un meilleur moment visuel non prévu par un anchor, tu peux le sélectionner.
- Pendant cette génération, tu dois utiliser uniquement un `template_type` présent dans le catalogue autorisé.
- Si tu estimes qu'un nouveau template serait meilleur, indique-le dans `ideal_template_gap`, mais garde `template_type` sur le meilleur template existant.
- `ideal_template_gap.needed` vaut true seulement si le catalogue actuel force un compromis visible.
""" if curation_enabled else ""
    density_rules = f"""
CADRAGE DU NOMBRE DE SLIDES:
- Le maximum de {max_batch_slides} slides est un plafond, pas un objectif à remplir.
- Seuil de sélection attendu: {pace_profile.get("selection_threshold")}.
- {pace_profile.get("density_instruction") or pace_profile["instruction"]}
- Ne crée pas de slide pour une simple phrase de liaison, une reformulation, une annonce administrative ou une idée déjà couverte.
- Si deux passages portent la même idée pédagogique, garde seulement le passage le plus clair et le plus visuel.
- Une slide doit être justifiée par une `source_quote` exacte. Sans citation exacte convaincante, ne crée pas la slide.
- En cas de doute entre deux templates, choisis le template le plus simple qui respecte le texte. Ne force pas un template spectaculaire.
"""

    return f"""Tu conçois des slides pédagogiques pour Le Socrate.

Source: {source_title}

RÈGLES:
- Tu reçois des fenêtres de contexte. Elles servent à te donner le texte, pas à imposer le nombre de slides.
- Si une fenêtre contient `slide_anchors`, ils t'indiquent l'intention initiale du plan.
- Si `source_alignment` vaut `section_slide_alignment`, la fenêtre est déjà la plage chronologique exacte attribuée à l'unique slide prévue: produis exactement 1 slide pour cette fenêtre, recopie son unique anchor, et ne crée pas de deuxième slide.
- Dans une fenêtre `section_slide_alignment`, conserve donc le même nombre de slides et le même rattachement texte, mais choisis librement le meilleur `template_type` parmi le catalogue selon le texte réel. Le `planned_template_type` est un indice faible, jamais une obligation.
- Si un anchor hors `section_slide_alignment` n'est pas couvert par le texte source, ignore-le au lieu d'inventer.
- Quand tu utilises un anchor, recopie exactement `slide_anchor_id` et `beat_id` dans la slide générée, mais ne recopie pas automatiquement son template prévu.
- Si l'anchor fournit `planned_pedagogical_shape`, pars de cette forme pédagogique avant de choisir `template_type`; si tu changes de forme, dis pourquoi dans `template_decision_reason`.
- Un anchor correspond à une intention pédagogique précise, pas à toute la fenêtre.
- Pour chaque anchor utilisé, choisis `source_quote` dans la portion exacte du texte qui réalise cette intention.
- Ne rattache jamais une slide au passage d'un anchor voisin parce qu'il contient des mots proches, une image répétée ou le même thème général.
- Si deux anchors voisins sont présents, vérifie leur ordre narratif : la première slide doit pointer vers le premier mouvement oral, la deuxième vers le mouvement oral suivant.
- Le deck source exact est la seule référence visuelle autorisée: utilise uniquement les templates du catalogue.
- Les nouvelles formes du deck source exact ont leur propre attribution: `story` pour un mini-récit avec morale, `analogy` pour une image mentale, `framework` pour un modèle à leviers, `opinion` pour une prise de position, `situations` pour trois profils ou situations, `flow` pour 2 à 4 gestes métier enchaînés.
- Si le texte introduit une maxime, une phrase clé, une formule exacte ou un repère à mémoriser avec des signaux comme "la voici", "phrase à retenir", "maxime", "repère", "souvenez-vous", utilise `quotable` et copie la phrase exacte dans `quote`.
- `story` peut être la déclinaison narrative d'une maxime: utilise-le seulement si le passage raconte ensuite une scène, une expérience client ou une conséquence concrète qui illustre cette phrase.
- Une structure nouvelle en trois piliers, trois repères, trois profils, trois postures, trois situations ou trois expressions n'est pas un `recap`: utilise `situations`. Les signaux forts sont "trois piliers", "les trois", "les voici", "trépied", "triptyque".
- Ne mets pas `casestudy` par défaut dès qu'il y a un exemple. Utilise `casestudy` seulement pour 2 à 4 cas comparables ou situations métier concrètes en cartes.
- Si le passage raconte un seul cas fictif ou une seule situation pour amener un conseil, une astuce, un réflexe métier ou une phrase de conduite à tenir, utilise `tip`. Si ce cas unique sert surtout de récit avec morale, utilise `story`.
- Pour deux versions opposées, préfère `comparison`. Pour une progression en étapes, préfère `steps` ou `flow`.
- Si le passage pose une distinction en deux familles ou deux modes, comme synchrone/asynchrone, téléphone/courriel, immédiat/différé, rapidité/exhaustivité, utilise `comparison`.
- Une liste de mots/formules à bannir, expressions interdites, pièges de langage ou erreurs à éviter n'est pas un `recap`: utilise `situations` s'il y a exactement 3 éléments, sinon `warning`.
- `recap` est réservé à une vraie synthèse après un développement déjà traité: "ce qu'on retient", "en résumé", "nous avons vu".
- Exception stricte: si l'anchor est une conclusion de cours (`anchor_id` de type `cX-conclusion-recap-slide`), le template doit rester `recap`, même si la synthèse contient trois axes, trois repères ou trois points.
- Si aucun anchor n'est disponible pour une fenêtre, sélectionne les thèmes, points et idées pédagogiques qui méritent vraiment un visuel.
- Tu peux produire 0, 1 ou plusieurs slides par fenêtre selon la densité réelle des idées.
- Maximum {max_batch_slides} slides pour tout ce batch.
- Maximum {pace_profile["max_slides_per_block"]} slides pour une même fenêtre source, sauf si plusieurs slide_anchors explicites y sont attachés.
- {pace_profile["instruction"]}
- Ne crée jamais une deuxième slide parce que son texte est long. Reformule les champs pour rentrer dans le template source exact.
- Ne rajoute aucun timing. Ne crée pas de slide absente du texte.
- Le JSON de plan peut orienter le choix, mais le texte final reste le contrôle : une slide doit correspondre à ce qui est vraiment dit.
- Le deck doit être lisible: titres courts, contenu très synthétique, aucun pavé.
- Aucun champ ne doit se terminer par "..." ou "…": écris des phrases complètes. Si un contenu dépasse son budget, reformule-le plus court, ne le coupe jamais.
- `definition` exige que le texte source pose réellement une définition: le champ `definition` reformule fidèlement le sens donné par la source (justifié par `source_quote`), jamais une définition inventée. Si la source ne définit pas la notion, choisis un autre template.
- Si deux idées sont proches, regroupe-les. Si une fenêtre répète une idée déjà traitée, saute-la.
- Pour chaque slide, ajoute `source_quote`: une citation exacte, copiée mot pour mot depuis la fenêtre source, qui justifie cette slide.
- `source_quote` doit être courte mais suffisante pour localiser la slide dans le texte: idéalement 15 à 60 mots.
- Ajoute `curation_reason`: pourquoi ce passage mérite un visuel plutôt qu'un simple oral.
- Réponds uniquement en JSON valide.

{curation_rules}

TAXONOMIE `pedagogical_shape`:
Classe d'abord la fonction pédagogique du passage: qu'est-ce que ce passage fait faire au cerveau de l'apprenant ? Ne classe pas selon le thème.
{_pedagogical_shape_mapping_for_prompt()}

PROCESSUS OBLIGATOIRE:
1. Lis toutes les fenêtres du batch et repère seulement les moments qui méritent vraiment un visuel.
2. Vérifie chaque moment contre les `slide_anchors` éventuels: anchor couvert, anchor ignoré, ou moment non prévu mais meilleur.
3. Pour chaque moment retenu, renseigne d'abord `pedagogical_shape` avec une valeur de la taxonomie, puis `shape_evidence` avec une citation très courte qui prouve cette forme.
4. À partir de cette forme, choisis le template existant depuis le catalogue en appliquant `use_when`, `avoid_when`, `strong_signals`, `rejection_rules`, `requires` et les éventuels exemples positifs/négatifs. En cas d'hésitation, compare explicitement les templates listés dans `confusable_with`. Le template prévu par l'anchor ne sert qu'à comprendre l'intention initiale.
5. Renseigne `template_decision_reason` en une phrase et `rejected_templates` pour les templates plausibles mais écartés.
6. Produis uniquement les slides retenues. Ne remplis pas le quota si le texte ne le justifie pas.
7. Si le meilleur rendu demanderait un template absent, renseigne `ideal_template_gap`, mais utilise quand même le meilleur template existant.

{density_rules}

BUDGETS DE TEXTE DES TEMPLATES SOURCE:
- Il n'y a pas de variante visuelle: le deck source exact reste inchangé.
- Les budgets ci-dessous sont les limites de texte du template actuel.
- Si le contenu dépasse, reformule `data` pour respecter ces limites.
- Ne compense jamais par une slide supplémentaire ou par un pavé de texte.
- Budgets par template, en caractères maximum:
{_layout_budget_prompt()}

CATALOGUE TEMPLATES:
{_template_catalog_for_prompt()}

TEMPLATES AUTORISÉS ET SCHÉMAS:
- welcome: data={{"title":"Bienvenue","formation_name":"nom formation","day_label":"Journée X","meta_note":"note courte"}}
- program_year: data={{"title":"3-6 mots","subtitle":"phrase courte","day_label":"Parcours annuel","phases":[{{"title":"phase","desc":"1 phrase"}}]}} avec exactement 2 phases
- day_program_7_steps: data={{"title":"3-6 mots","subtitle":"phrase courte","day_label":"Feuille de route","active_item":1,"items":["thème 1","thème 2"]}} avec exactement 7 items
- reflection: data={{"title":"3-6 mots","text":"1-2 phrases"}}
- chapter_opener: data={{"chapter_label":"Chapitre X","title":"titre du thème","axes":[{{"title":"axe court","desc":"optionnel"}}]}}
- definition: data={{"term":"mot ou notion","eyebrow":"contexte court","definition":"1 phrase","isItems":["critère","critère"]}}
- comparison: data={{"title":"3-6 mots","cols":[{{"label":"contexte court","title":"titre fort 1-3 mots","items":["point court"]}},{{"label":"contexte court","title":"titre fort 1-3 mots","items":["point court"]}}]}} — `label` est le petit eyebrow, `title` le grand titre de colonne
- casestudy: data={{"title":"3-6 mots","eyebrow":"contexte","cases":[{{"tag":"01 · Canal","title":"court","desc":"1 phrase","example":"optionnel"}}]}} avec 2 à 4 cases comparables
- situations: data={{"title":"3-6 mots","eyebrow":"contexte","items":[{{"title":"pilier, profil, posture ou situation","desc":"rôle ou règle courte"}}]}} avec exactement 3 items
- steps: data={{"title":"3-6 mots","steps":[{{"title":"court","desc":"1 phrase"}}]}} avec 2-4 steps
- flow: data={{"title":"3-6 mots","eyebrow":"contexte","steps":[{{"title":"geste court","desc":"1 phrase"}}]}} avec 2 à 4 gestes métier
- story: data={{"title":"3-6 mots","narrative":"1-2 phrases de situation","moral":"phrase de conclusion qui relie la scène au principe"}}
- analogy: data={{"title":"3-6 mots","concept":"notion source","comparison":"image mentale","text":"1 phrase d'explication"}}
- framework: data={{"title":"3-8 mots","center":{{"title":"coeur du modèle"}},"segments":[{{"title":"court","desc":"1 phrase"}}]}} avec 4-6 segments
- opinion: data={{"title":"3-8 mots","text":"1-2 phrases de point de vue argumenté"}}
- recap: data={{"title":"3-6 mots","points":["point court"]}} avec 2 à 4 points
- reprise_recap: data={{"title":"3-6 mots","points":["point court"]}} avec 2 à 4 points repris du chapitre précédent
- warning: data={{"title":"3-6 mots","text":"1-2 phrases"}}
- tip: data={{"title":"3-6 mots","text":"1-2 phrases"}}
- quotable: data={{"quote":"phrase exacte courte à ancrer, copiée telle quelle depuis le texte source"}}
- pause: data={{}}
- qa: data={{}}

Choisis `event_type` parmi:
welcome, chapter_opener, recap, reprise_recap, definition, reflection, casestudy, story, analogy, opinion, framework, steps, comparison, warning, tip, quotable.

FORMAT EXACT:
{{
  "slides": [
    {{
      "source_block_id": 0,
      "slide_anchor_id": "anchor optionnel si utilisé",
      "beat_id": "beat optionnel si utilisé",
      "pedagogical_shape": "idee_forte",
      "shape_evidence": "Citation très courte qui prouve la forme pédagogique",
      "template_decision_reason": "Pourquoi ce template correspond mieux au passage",
      "rejected_templates": [
        {{"template": "recap", "why": "Le passage introduit une structure nouvelle, ce n'est pas une synthèse."}}
      ],
      "template_type": "reflection",
      "event_type": "reflection",
      "event_summary": "Phrase courte décrivant l'idée source",
      "source_quote": "Citation exacte du passage source qui correspond à cette slide",
      "curation_reason": "Pourquoi ce moment mérite une slide",
      "importance": 4,
      "ideal_template_gap": {{
        "needed": false,
        "suggested_template_name": "",
        "reason": "",
        "design_prompt": "",
        "fields": {{}}
      }},
      "data": {{"title": "...", "text": "..."}}
    }}
  ],
  "template_backlog": [
    {{
      "suggested_template_name": "Nom court du template idéal",
      "reason": "Pourquoi les templates actuels sont insuffisants",
      "design_prompt": "Brief de design réutilisable pour créer ce template plus tard",
      "best_current_template": "reflection",
      "fields": {{}}
    }}
  ]
}}

Nombre d'anchors dans ce batch: {anchors_count}

FENÊTRES DE CONTEXTE:
{json.dumps(payload, ensure_ascii=False)}
"""


class _SlideText(str):
    """String wrapper that prevents silent final-copy truncation via [:N].

    Layout budgets are still computed after normalization; over-budget fields are
    reported in layout metadata instead of being amputated here.
    """

    def __getitem__(self, key):
        if (
            isinstance(key, slice)
            and key.start is None
            and key.stop is not None
            and key.step is None
        ):
            return str(self)
        return super().__getitem__(key)


def _as_text(value, fallback: str = "") -> str:
    text = str(value or fallback).strip()
    return _SlideText(text or fallback)


def _normalize_pedagogical_shape(value, template: str = "") -> str:
    shape = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    template = _canonical_template(template, fallback="")
    if shape in PEDAGOGICAL_SHAPE_TO_TEMPLATES:
        if not template or template in PEDAGOGICAL_SHAPE_TO_TEMPLATES[shape]:
            return shape
    return DEFAULT_SHAPE_BY_TEMPLATE.get(template, "")


def _normalize_rejected_templates(value, max_items: int = 4) -> list[dict]:
    if not isinstance(value, list):
        return []
    rejected = []
    seen = set()
    for item in value:
        if isinstance(item, dict):
            template = _canonical_template(
                item.get("template") or item.get("template_type") or item.get("name"),
                fallback="",
            )
            why = _as_text(item.get("why") or item.get("reason") or item.get("rationale"), "")[:240]
        else:
            template = _canonical_template(item, fallback="")
            why = ""
        if not template or template in seen:
            continue
        rejected.append({"template": template, "why": why})
        seen.add(template)
        if len(rejected) >= max_items:
            break
    return rejected


def _quote_word_offsets(block_text: str, quote: str) -> tuple[int, int] | None:
    quote_norm = re.sub(r"\s+", " ", quote or "").strip()
    block_norm = re.sub(r"\s+", " ", block_text or "").strip()
    if not quote_norm or not block_norm:
        return None

    pos = block_norm.find(quote_norm)
    if pos < 0:
        return None

    before = block_norm[:pos].strip()
    quote_words = quote_norm.split()
    start = len(before.split()) if before else 0
    end = start + len(quote_words)
    if end <= start:
        return None
    return start, end


def _limit_list(value, max_len: int) -> list:
    if not isinstance(value, list):
        return []
    return value[:max_len]


_FORBIDDEN_EXPRESSION_SIGNALS = (
    "a bannir",
    "bannir",
    "expression interdite",
    "expressions interdites",
    "mot interdit",
    "mots interdits",
    "interdit",
    "interdits",
    "interdites",
    "a eviter",
    "ne dites pas",
    "ne jamais dire",
    "pieges de langage",
    "tue l ecoute",
    "tue-l ecoute",
    "interrupteur de dialogue",
    "interrupteurs de dialogue",
    "sabotent la desescalade",
    "calmez vous",
    "ne vous inquietez pas",
)

_THREE_PART_STRUCTURE_SIGNALS = (
    "trois piliers",
    "3 piliers",
    "les trois piliers",
    "trois reperes",
    "3 reperes",
    "trois profils",
    "3 profils",
    "trois postures",
    "3 postures",
    "trois situations",
    "3 situations",
    "trois expressions",
    "3 expressions",
    "trois elements",
    "3 elements",
    "triade",
    "triptyque",
    "trepied",
)

_ADVICE_FROM_SINGLE_CASE_SIGNALS = (
    "astuce",
    "conseil",
    "reflexe",
    "reflexe metier",
    "a adopter",
    "dans ce cas",
    "faire table rase",
    "suspendez votre jugement",
    "oubliez l'etiquette",
    "micro-pause",
    "micro pause",
    "respirez",
    "dites-vous",
    "je ne sais rien de ce client",
    "ecoute neuve",
    "ecoute propre",
    "condition sine qua non",
    "ce qu'il faut retenir",
)

_TWO_FAMILY_COMPARISON_SIGNALS = (
    "synchrone",
    "synchrones",
    "asynchrone",
    "asynchrones",
    "deux grandes familles",
    "deux familles",
    "deux modes",
    "deux canaux",
    "d'un cote",
    "de l'autre cote",
    "en revanche",
    "a l'inverse",
    "interaction se fait en temps reel",
    "interaction se fait en temps differe",
    "temps reel",
    "temps differe",
    "reaction immediate",
    "reponse complete",
    "autoportante",
    "rapidite",
    "exhaustivite",
)


def _fold_for_matching(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_text = ascii_text.lower().replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", ascii_text).strip()


def _forbidden_expression_template(raw_data: dict, *text_parts) -> str:
    raw_payload = _json_dumps(raw_data) if isinstance(raw_data, dict) else ""
    haystack = _fold_for_matching(" ".join([raw_payload, *[_as_text(part, "") for part in text_parts]]))
    if not any(signal in haystack for signal in _FORBIDDEN_EXPRESSION_SIGNALS):
        return ""

    source_items = []
    if isinstance(raw_data, dict):
        for key in ("items", "points", "cases", "profiles", "scenes"):
            source_items = _limit_list(raw_data.get(key), 4)
            if source_items:
                break
    has_three_items = len(source_items) == 3 or bool(
        re.search(r"\b(3|trois)\s+(mots?|expressions?|formules?)\b", haystack)
    )
    return "situations" if has_three_items else "warning"


def _three_part_structure_template(raw_data: dict, *text_parts) -> str:
    raw_payload = _json_dumps(raw_data) if isinstance(raw_data, dict) else ""
    haystack = _fold_for_matching(" ".join([raw_payload, *[_as_text(part, "") for part in text_parts]]))
    if not any(signal in haystack for signal in _THREE_PART_STRUCTURE_SIGNALS):
        return ""

    source_items = []
    if isinstance(raw_data, dict):
        for key in ("items", "points", "cases", "profiles", "scenes"):
            source_items = _limit_list(raw_data.get(key), 4)
            if source_items:
                break
    has_three_items = len(source_items) == 3 or bool(
        re.search(r"\b(3|trois)\s+(piliers?|reperes?|profils?|postures?|situations?|expressions?|elements?)\b", haystack)
    )
    return "situations" if has_three_items else ""


def _source_items_from_payload(raw_data: dict) -> list:
    if not isinstance(raw_data, dict):
        return []
    for key in ("cases", "items", "points", "profiles", "scenes"):
        source_items = _limit_list(raw_data.get(key), 4)
        if source_items:
            return source_items
    return []


def _single_case_template(raw_data: dict, *text_parts) -> str:
    source_items = _source_items_from_payload(raw_data)
    if len(source_items) >= 2:
        return ""

    raw_payload = _json_dumps(raw_data) if isinstance(raw_data, dict) else ""
    haystack = _fold_for_matching(" ".join([raw_payload, *[_as_text(part, "") for part in text_parts]]))
    if any(signal in haystack for signal in _ADVICE_FROM_SINGLE_CASE_SIGNALS):
        return "tip"
    return "story"


def _two_family_comparison_template(raw_data: dict, *text_parts) -> str:
    raw_payload = _json_dumps(raw_data) if isinstance(raw_data, dict) else ""
    haystack = _fold_for_matching(" ".join([raw_payload, *[_as_text(part, "") for part in text_parts]]))
    has_sync_pair = "synchrone" in haystack and "asynchrone" in haystack
    has_two_family_signal = any(signal in haystack for signal in (
        "deux grandes familles",
        "deux familles",
        "deux modes",
        "deux canaux",
        "d'un cote",
        "de l'autre cote",
    ))
    has_expectation_contrast = any(signal in haystack for signal in (
        "reaction immediate",
        "reponse complete",
        "temps reel",
        "temps differe",
        "rapidite",
        "exhaustivite",
        "autoportante",
    ))
    if has_sync_pair or (has_two_family_signal and has_expectation_contrast):
        return "comparison"
    return ""


def _two_family_comparison_data(data: dict, fallback_title: str, fallback_text: str) -> dict:
    if isinstance(data, dict) and isinstance(data.get("cols"), list) and len(data["cols"]) >= 2:
        return data
    haystack = _fold_for_matching(" ".join([
        _json_dumps(data) if isinstance(data, dict) else "",
        fallback_title,
        fallback_text,
    ]))
    title = _as_text((data or {}).get("title") if isinstance(data, dict) else "", fallback_title)
    if "synchrone" in haystack or "asynchrone" in haystack or "temps reel" in haystack or "temps differe" in haystack:
        return {
            **(data if isinstance(data, dict) else {}),
            "title": title,
            "cols": [
                {
                    "label": "Canaux synchrones",
                    "items": ["Temps réel", "Réactivité immédiate", "Maintenir le lien pendant l'échange"],
                },
                {
                    "label": "Canaux asynchrones",
                    "items": ["Temps différé", "Réponse complète", "Message autonome"],
                },
            ],
        }
    return data if isinstance(data, dict) else {"title": title, "text": fallback_text}


def _normalize_template_gap(value: dict | None, selected_template: str) -> dict:
    if not isinstance(value, dict):
        value = {}
    needed = bool(value.get("needed"))
    suggested_name = _as_text(value.get("suggested_template_name") or value.get("name"), "")[:80]
    reason = _as_text(value.get("reason"), "")[:360]
    design_prompt = _as_text(value.get("design_prompt") or value.get("prompt"), "")[:900]
    fields = value.get("fields") if isinstance(value.get("fields"), dict) else {}
    if not suggested_name and not reason and not design_prompt:
        needed = False
    return {
        "needed": needed,
        "suggested_template_name": suggested_name,
        "reason": reason,
        "design_prompt": design_prompt,
        "best_current_template": _canonical_template(
            value.get("best_current_template") or value.get("current_template") or selected_template,
            fallback=selected_template,
        ),
        "fields": fields,
    }


def _normalize_template_backlog(items: list, max_items: int = 12) -> list[dict]:
    backlog = []
    seen = set()
    for item in _limit_list(items, max_items * 2):
        if not isinstance(item, dict):
            continue
        selected_template = _canonical_template(item.get("best_current_template") or item.get("template_type"))
        gap = _normalize_template_gap(
            {
                **item,
                "needed": True,
                "suggested_template_name": item.get("suggested_template_name") or item.get("name"),
            },
            selected_template,
        )
        if not gap["suggested_template_name"] or not gap["reason"]:
            continue
        key = gap["suggested_template_name"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        backlog.append(gap)
        if len(backlog) >= max_items:
            break
    return backlog


def _normalize_slide_data(template: str, data: dict, fallback_title: str, fallback_text: str) -> dict:
    if not isinstance(data, dict):
        data = {}

    title = _as_text(data.get("title"), fallback_title)[:90]
    text = _as_text(data.get("text") or data.get("description"), fallback_text)[:420]

    def _items_from(*keys: str, max_len: int = 4) -> list[dict]:
        source = []
        for key in keys:
            candidate = data.get(key)
            if isinstance(candidate, list):
                source = candidate
                break
        items = []
        for idx, item in enumerate(_limit_list(source, max_len)):
            if isinstance(item, dict):
                item_title = _as_text(item.get("title") or item.get("label") or item.get("name"), f"Point {idx + 1}")[:80]
                item_desc = _as_text(item.get("desc") or item.get("description") or item.get("text") or item.get("detail"), "")[:180]
            else:
                item_title = _as_text(item, "")[:80]
                item_desc = ""
            if item_title:
                items.append({"title": item_title, "desc": item_desc})
        return items

    if template == "welcome":
        return {
            "title": _as_text(data.get("title"), "Bienvenue")[:60],
            "subtitle": _as_text(data.get("subtitle") or data.get("day_label"), fallback_title)[:120],
            "formation_name": _as_text(data.get("formation_name"), fallback_text)[:120],
            "day_label": _as_text(data.get("day_label"), "")[:40],
        }

    if template == "chapter_opener":
        axes = []
        for item in _limit_list(data.get("axes") or data.get("items") or data.get("points"), 4):
            if isinstance(item, dict):
                axis_title = _as_text(item.get("title") or item.get("label"), "")
                axis_desc = _as_text(item.get("desc") or item.get("description") or item.get("text"), "")
            else:
                axis_title = _as_text(item, "")
                axis_desc = ""
            if axis_title:
                axes.append({"title": axis_title[:80], "desc": axis_desc[:160]})
        return {
            "chapter_label": _as_text(data.get("chapter_label") or data.get("chapter"), "Chapitre")[:40],
            "title": _as_text(data.get("title"), fallback_title)[:90],
            "axes": axes or [{"title": _shorten(fallback_text, 70), "desc": ""}],
        }

    if template in {"program_year", "day_program", "day_program_7_steps"}:
        max_items = 7 if template == "day_program_7_steps" else 2
        items = []
        for item in _limit_list(data.get("phases") or data.get("items") or data.get("points"), max_items):
            if isinstance(item, dict):
                label = _as_text(item.get("title") or item.get("label"), "")
                desc = _as_text(item.get("desc") or item.get("description") or item.get("text"), "")
            else:
                label = _as_text(item, "")
                desc = ""
            if label:
                items.append({"title": label[:120], "desc": desc[:220]} if template == "program_year" else label[:120])
        if template == "program_year":
            return {
                "title": _as_text(data.get("title"), "Programme de l'année")[:80],
                "subtitle": _as_text(data.get("subtitle") or data.get("description"), "")[:180],
                "formation_name": _as_text(data.get("formation_name"), "")[:120],
                "day_label": _as_text(data.get("day_label"), "Parcours annuel")[:40],
                "phases": items or [
                    {
                        "title": "Assistance et relation client à distance",
                        "desc": "Accueillir, écouter, comprendre et résoudre les demandes clients, quel que soit le canal utilisé.",
                    },
                    {
                        "title": "Actions commerciales en relation client à distance",
                        "desc": "Identifier un besoin, éveiller un intérêt et proposer une solution adaptée avec éthique et justesse.",
                    },
                ],
            }
        normalized = {
            "title": _as_text(data.get("title"), "Programme de la journée")[:80],
            "subtitle": _as_text(data.get("subtitle") or data.get("description"), "")[:180],
            "formation_name": _as_text(data.get("formation_name"), "")[:120],
            "day_label": _as_text(data.get("day_label"), "")[:40],
            "items": items or [_shorten(fallback_text, 90)],
        }
        if template == "day_program_7_steps":
            normalized["active_item"] = _safe_int(data.get("active_item"), 1, 1, 7)
        return normalized

    if template == "casestudy":
        cases = []
        for item in _limit_list(data.get("cases") or data.get("items") or data.get("points"), 4):
            if isinstance(item, dict):
                cases.append({
                    "tag": _as_text(item.get("tag") or item.get("label"), "")[:40],
                    "title": _as_text(item.get("title"), "Point clé")[:60],
                    "desc": _as_text(item.get("desc") or item.get("description") or item.get("text"), fallback_text)[:220],
                    "example": _as_text(item.get("example") or item.get("quote"), "")[:160],
                })
            else:
                label = _as_text(item, "")
                if label:
                    cases.append({"title": label[:60], "desc": "", "tag": "", "example": ""})
        return {
            "title": title,
            "eyebrow": _as_text(data.get("eyebrow"), "Analyse comparative")[:60],
            "cases": cases or [{"title": "Point clé", "desc": text, "tag": "", "example": ""}],
        }

    if template == "situations":
        items = _items_from("items", "cases", "profiles", "scenes", "points", max_len=4)
        return {
            "title": title,
            "eyebrow": _as_text(data.get("eyebrow"), "Adapter sa posture")[:60],
            "items": items or [{"title": "Situation clé", "desc": text}],
        }

    if template == "definition":
        tags = [_as_text(item, "")[:40] for item in _limit_list(data.get("isItems") or data.get("items"), 4)]
        return {
            "term": _as_text(data.get("term") or data.get("title"), title)[:70],
            "eyebrow": _as_text(data.get("eyebrow"), "Définition")[:50],
            "definition": _as_text(data.get("definition") or data.get("text"), text)[:260],
            "isItems": [tag for tag in tags if tag],
        }

    if template in {"comparison", "beforeafter"}:
        source_cols = data.get("cols") if isinstance(data.get("cols"), list) else []
        cols = []
        for index, item in enumerate(_limit_list(source_cols, 3)):
            if isinstance(item, dict):
                values = [_as_text(value, "")[:120] for value in _limit_list(item.get("items"), 5)]
                cols.append({
                    "label": _as_text(item.get("label") or item.get("title"), f"Option {index + 1}")[:60],
                    "items": [value for value in values if value],
                })
        if not cols:
            rows = _limit_list(data.get("rows"), 4)
            before_items = []
            after_items = []
            for row in rows:
                if isinstance(row, dict):
                    before_items.append(_as_text(row.get("before") or row.get("a"), "")[:120])
                    after_items.append(_as_text(row.get("after") or row.get("b"), "")[:120])
            if before_items or after_items:
                cols = [
                    {"label": "Avant", "items": [item for item in before_items if item]},
                    {"label": "Après", "items": [item for item in after_items if item]},
                ]
        return {
            "title": title,
            "cols": cols or [
                {"label": "Point de départ", "items": [text]},
                {"label": "Repère attendu", "items": ["Bonne pratique à appliquer"]},
            ],
        }

    if template == "story":
        return {
            "title": title,
            "narrative": _as_text(data.get("narrative") or data.get("text") or data.get("description"), text)[:360],
            "moral": _as_text(data.get("moral") or data.get("takeaway") or data.get("quote"), "")[:180],
        }

    if template == "analogy":
        return {
            "title": title,
            "concept": _as_text(data.get("concept") or data.get("term") or data.get("a"), title)[:80],
            "comparison": _as_text(data.get("comparison") or data.get("image") or data.get("metaphor") or data.get("b"), "Image mentale")[:90],
            "text": _as_text(data.get("text") or data.get("description") or data.get("explanation"), text)[:260],
        }

    if template == "opinion":
        return {
            "title": _as_text(data.get("title") or data.get("claim"), title)[:100],
            "text": _as_text(data.get("text") or data.get("description") or data.get("takeaway"), text)[:320],
        }

    if template == "transition":
        return {
            "title": title,
            "from_topic": _as_text(data.get("from_topic") or data.get("from") or data.get("previous"), "")[:70],
            "to_topic": _as_text(data.get("to_topic") or data.get("to") or data.get("next"), "")[:90],
        }

    if template == "framework":
        segments = _items_from("segments", "items", "points", "steps", max_len=6)
        return {
            "title": title,
            "center": data.get("center") if isinstance(data.get("center"), dict) else {
                "title": _as_text(data.get("center_title") or data.get("core") or data.get("topic"), "Point central")[:80],
            },
            "segments": segments or [{"title": "Repère clé", "desc": text}],
        }

    if template in {"steps", "facilitator", "flow"}:
        steps = []
        for idx, item in enumerate(_limit_list(data.get("steps") or data.get("items") or data.get("points"), 4)):
            if isinstance(item, dict):
                steps.append(
                    {
                        "title": _as_text(item.get("title"), f"Étape {idx + 1}")[:50],
                        "desc": _as_text(item.get("desc") or item.get("detail"), fallback_text)[:160],
                    }
                )
            else:
                label = _as_text(item, "")
                if label:
                    steps.append({"title": label[:50], "desc": ""})
        payload = {"title": title, "steps": steps or [{"title": "Étape clé", "desc": text}]}
        if template == "flow":
            payload["eyebrow"] = _as_text(data.get("eyebrow"), "Le flux en quatre temps")[:60]
        return payload

    if template == "exercise":
        return {
            "title": title,
            "duration": _as_text(data.get("duration"), "10 minutes")[:40],
            "objective": _as_text(data.get("objective") or data.get("text") or data.get("description"), text)[:220],
            "steps": _items_from("steps", "items", "points", max_len=4) or [{"title": "Consigne", "desc": text}],
        }

    if template == "checklist":
        source_points = data.get("points") or data.get("items") or data.get("checklist") or data.get("steps") or []
        points = []
        for item in _limit_list(source_points, 5):
            if isinstance(item, dict):
                points.append(_as_text(item.get("title") or item.get("label") or item.get("text") or item.get("desc"), "")[:140])
            else:
                points.append(_as_text(item, "")[:140])
        return {"title": title, "points": [point for point in points if point] or [text]}

    if template == "stats":
        stats = []
        for idx, item in enumerate(_limit_list(data.get("stats") or data.get("items") or data.get("points"), 4)):
            if isinstance(item, dict):
                stats.append({
                    "number": _as_text(item.get("number") or item.get("value"), str(idx + 1))[:30],
                    "label": _as_text(item.get("label") or item.get("title") or item.get("text"), "Repère clé")[:100],
                })
            else:
                stats.append({"number": str(idx + 1), "label": _as_text(item, "Repère clé")[:100]})
        return {
            "title": title,
            "description": _as_text(data.get("description") or data.get("source"), "")[:140],
            "stats": stats or [{"number": "1", "label": text}],
        }

    if template == "chart":
        return {
            "title": title,
            "description": _as_text(data.get("description") or data.get("text"), text)[:220],
            "chartData": data.get("chartData") or data.get("chart_data") or data.get("data_points") or [],
        }

    if template == "matrix":
        rows = []
        for item in _limit_list(data.get("rows") or data.get("items") or data.get("points"), 4):
            if isinstance(item, dict):
                solutions = item.get("solutions")
                if not isinstance(solutions, list):
                    solutions = item.get("responses") or item.get("answers") or []
                rows.append({
                    "cause": _as_text(item.get("cause") or item.get("title") or item.get("label"), "Situation")[:80],
                    "solutions": [_as_text(solution, "")[:90] for solution in _limit_list(solutions, 4) if _as_text(solution, "")],
                })
            else:
                rows.append({"cause": _as_text(item, "Situation")[:80], "solutions": []})
        return {"title": title, "rows": rows or [{"cause": title, "solutions": [text]}]}

    if template == "script":
        lines = []
        for item in _limit_list(data.get("lines") or data.get("dialogue") or data.get("items"), 6):
            if isinstance(item, dict):
                speaker = _as_text(item.get("speaker"), "conseiller").lower()
                if speaker not in {"client", "conseiller"}:
                    speaker = "conseiller"
                lines.append({
                    "speaker": speaker,
                    "text": _as_text(item.get("text") or item.get("line") or item.get("quote"), "")[:180],
                    "annotation": _as_text(item.get("annotation") or item.get("note"), "")[:120],
                })
            else:
                lines.append({"speaker": "conseiller", "text": _as_text(item, "")[:180], "annotation": ""})
        return {
            "title": title,
            "context": _as_text(data.get("context") or data.get("situation"), "")[:180],
            "lines": [line for line in lines if line["text"]] or [{"speaker": "conseiller", "text": text, "annotation": ""}],
        }

    if template == "profiles":
        profiles = []
        for item in _limit_list(data.get("profiles") or data.get("items") or data.get("points"), 3):
            if isinstance(item, dict):
                signals = item.get("signals") if isinstance(item.get("signals"), list) else []
                profiles.append({
                    "name": _as_text(item.get("name") or item.get("title") or item.get("label"), "Profil")[:50],
                    "signals": [_as_text(signal, "")[:70] for signal in _limit_list(signals, 4) if _as_text(signal, "")],
                    "posture": _as_text(item.get("posture") or item.get("desc") or item.get("description"), "")[:180],
                    "phrase": _as_text(item.get("phrase") or item.get("example") or item.get("quote"), "")[:140],
                })
        return {"title": title, "profiles": profiles} if profiles else {"title": title}

    if template == "channel":
        criteria = [_as_text(item, "")[:50] for item in _limit_list(data.get("criteria"), 5) if _as_text(item, "")]
        channels = []
        for item in _limit_list(data.get("channels") or data.get("items"), 4):
            if isinstance(item, dict):
                cells = item.get("cells") if isinstance(item.get("cells"), dict) else {}
                channels.append({
                    "name": _as_text(item.get("name") or item.get("title") or item.get("label"), "Canal")[:50],
                    "cells": {str(key): _as_text(value, "")[:120] for key, value in cells.items()},
                })
        if criteria and channels:
            return {"title": title, "criteria": criteria, "channels": channels}
        return {"title": title}

    if template == "timeline":
        milestones = []
        for item in _limit_list(data.get("milestones") or data.get("items") or data.get("steps"), 5):
            if isinstance(item, dict):
                actions = item.get("actions") if isinstance(item.get("actions"), list) else []
                milestones.append({
                    "when": _as_text(item.get("when") or item.get("period") or item.get("date"), "")[:40],
                    "title": _as_text(item.get("title") or item.get("label"), "Jalon")[:70],
                    "actions": [_as_text(action, "")[:100] for action in _limit_list(actions, 3) if _as_text(action, "")],
                })
        if milestones:
            return {"title": title, "subtitle": _as_text(data.get("subtitle") or data.get("description"), "")[:160], "milestones": milestones}
        return {"title": title, "subtitle": _as_text(data.get("subtitle") or data.get("description"), "")[:160]}

    if template == "decisiontree":
        branches = data.get("branches") if isinstance(data.get("branches"), list) else []
        if not branches:
            return {"title": title, "root": _as_text(data.get("root") or data.get("question"), text)[:180]}
        return {
            "title": title,
            "root": _as_text(data.get("root") or data.get("question"), text)[:180],
            "branches": branches,
        }

    if template in {"recap", "reprise_recap"}:
        source_points = data.get("points") or data.get("columns") or data.get("items") or data.get("checklist") or data.get("steps") or []
        points = []
        for item in _limit_list(source_points, 4):
            if isinstance(item, dict):
                points.append(_as_text(item.get("title") or item.get("label") or item.get("text") or item.get("desc"), "")[:140])
            else:
                points.append(_as_text(item, "")[:140])
        points = [point for point in points if point]
        return {"title": title, "points": points or [text]}

    if template == "tip":
        first_case = _limit_list(data.get("cases"), 1)
        first_item = first_case[0] if first_case else None
        if first_item is None:
            source_items = _limit_list(data.get("items") or data.get("points"), 1)
            first_item = source_items[0] if source_items else None
        if isinstance(first_item, dict):
            tip_text = _as_text(
                first_item.get("example")
                or first_item.get("takeaway")
                or first_item.get("desc")
                or first_item.get("description")
                or first_item.get("text"),
                text,
            )
        else:
            tip_text = _as_text(first_item, text)
        return {"title": title, "text": tip_text[:420]}

    if template == "quotable":
        return {"quote": _as_text(data.get("quote") or data.get("text") or data.get("title"), text)[:260]}

    return {"title": title, "text": text}


def _fallback_title(block: dict) -> str:
    first_sentence = _SENTENCE_SPLIT_RE.split(_shorten(block.get("text", ""), 240))[0]
    words = re.findall(r"\w+", first_sentence, flags=re.UNICODE)
    return " ".join(words[:6]).strip().capitalize() or "Point clé"


def _fallback_slide(block: dict, reason: str = "fallback") -> dict:
    anchor = None
    anchors = block.get("slide_anchors") or []
    if len(anchors) == 1 and isinstance(anchors[0], dict):
        anchor = anchors[0]
    title = _fallback_title(block)
    text = _shorten(block.get("text", ""), 280)
    template = _canonical_template((anchor or {}).get("template_type"), fallback="reflection")
    data = _normalize_slide_data(template, {"title": title, "text": text}, title, text)
    layout_variant, data, layout_fit = _resolve_slide_layout(template, data, "source")
    return {
        "source_block_id": block["source_block_id"],
        "pedagogical_shape": _normalize_pedagogical_shape((anchor or {}).get("pedagogical_shape"), template),
        "shape_evidence": "",
        "template_decision_reason": "",
        "rejected_templates": [],
        "template_type": template,
        "layout_variant": layout_variant,
        "layout_fit": {
            "status": "fallback_source" if layout_fit.get("status") == "ok" else layout_fit.get("status"),
            "requested_variant": "",
            "over_budget_fields": layout_fit.get("over_budget_fields") or [],
        },
        "event_type": "concept",
        "event_summary": title,
        "importance": 2,
        "data": data,
        "slide_anchor_id": (anchor or {}).get("anchor_id"),
        "beat_id": (anchor or {}).get("beat_id") or "",
        "anchor_role": (anchor or {}).get("role") or "",
        "source_quote": _shorten(block.get("text", ""), 700),
        "curation_reason": reason,
        "fallback_reason": reason,
        "ideal_template_gap": _normalize_template_gap(None, template),
    }


def _recap_points_from_text(text: str, max_points: int = 4) -> list[str]:
    points = []
    for paragraph in _split_paragraphs(text):
        clean = re.sub(r"\s+", " ", paragraph).strip()
        if not clean:
            continue
        words = clean.split()
        lowered = clean.lower()
        if len(words) <= 4 and lowered.rstrip(".!?,;:") in {"bien", "très bien", "tres bien"}:
            continue
        points.append(_shorten(clean, 140))
        if len(points) >= max_points:
            break

    if points:
        return points

    for sentence in _SENTENCE_SPLIT_RE.split(re.sub(r"\s+", " ", text or "").strip()):
        clean = sentence.strip()
        if len(clean.split()) >= 5:
            points.append(_shorten(clean, 140))
        if len(points) >= max_points:
            break
    return points


def _coverage_repair_slide(block: dict, reason: str) -> dict:
    refs = block.get("source_refs") or []
    first_ref = refs[0] if refs and isinstance(refs[0], dict) else {}
    section_label = _as_text(first_ref.get("section_label") or block.get("sub_part_name"), "")
    is_conclusion = "conclusion" in section_label.lower()
    title = "Ce qu'on retient" if is_conclusion else _fallback_title(block)
    text = _shorten(block.get("text", ""), 280)
    points = _recap_points_from_text(block.get("text", ""))
    template = "recap" if is_conclusion or points else "reflection"
    data = {"title": title, "points": points or [text]} if template == "recap" else {"title": title, "text": text}
    return {
        "source_block_id": block["source_block_id"],
        "pedagogical_shape": _normalize_pedagogical_shape("", template),
        "shape_evidence": "",
        "template_decision_reason": "",
        "rejected_templates": [],
        "template_type": template,
        "event_type": "recap" if template == "recap" else "concept",
        "event_summary": title,
        "importance": 2,
        "data": data,
        "slide_anchor_id": None,
        "beat_id": "",
        "anchor_role": "",
        "source_quote": _shorten(block.get("text", ""), 700),
        "curation_reason": reason,
        "fallback_reason": reason,
        "coverage_repair": True,
        "ideal_template_gap": _normalize_template_gap(None, template),
    }


def _strict_anchor_blocks(blocks: Iterable[dict]) -> list[dict]:
    return [
        block
        for block in blocks
        if block.get("source_alignment") == "section_slide_alignment"
        and block.get("slide_anchors")
    ]


def _fallback_slide_for_anchor(block: dict, anchor: dict, reason: str) -> dict:
    block_for_anchor = {**block, "slide_anchors": [anchor]}
    return _fallback_slide(block_for_anchor, reason)


def _ensure_strict_anchor_slides(slides: list[dict], blocks: Iterable[dict], reason: str) -> tuple[list[dict], int]:
    present = set()
    for slide in slides:
        try:
            source_block_id = int(slide.get("source_block_id"))
        except (TypeError, ValueError):
            continue
        anchor_id = str(slide.get("slide_anchor_id") or slide.get("anchor_id") or "").strip()
        if anchor_id:
            present.add((source_block_id, anchor_id))

    ensured = list(slides)
    inserted = 0
    for block in _strict_anchor_blocks(blocks):
        try:
            source_block_id = int(block.get("source_block_id"))
        except (TypeError, ValueError):
            continue
        for anchor in block.get("slide_anchors") or []:
            if not isinstance(anchor, dict):
                continue
            anchor_id = str(anchor.get("anchor_id") or "").strip()
            if not anchor_id or (source_block_id, anchor_id) in present:
                continue
            ensured.append(_fallback_slide_for_anchor(block, anchor, reason))
            present.add((source_block_id, anchor_id))
            inserted += 1
    return ensured, inserted


def _ensure_unanchored_coverage_slides(slides: list[dict], blocks: Iterable[dict], reason: str) -> tuple[list[dict], int]:
    covered_block_ids = set()
    for slide in slides:
        try:
            covered_block_ids.add(int(slide.get("source_block_id")))
        except (TypeError, ValueError):
            continue

    ensured = list(slides)
    inserted = 0
    for block in blocks:
        if block.get("source_alignment") != "section_unanchored":
            continue
        if not str(block.get("text") or "").strip():
            continue
        try:
            source_block_id = int(block.get("source_block_id"))
        except (TypeError, ValueError):
            continue
        if source_block_id in covered_block_ids:
            continue
        ensured.append(_coverage_repair_slide(block, reason))
        covered_block_ids.add(source_block_id)
        inserted += 1
    return ensured, inserted


def _sort_slides_by_source_order(slides: list[dict], source_blocks: Iterable[dict]) -> list[dict]:
    block_order = {}
    for idx, block in enumerate(source_blocks):
        try:
            source_block_id = int(block.get("source_block_id"))
        except (TypeError, ValueError):
            continue
        word_start = block.get("word_start")
        block_order[source_block_id] = (
            int(word_start if word_start is not None else 10**12),
            idx,
        )

    def sort_key(item: tuple[int, dict]) -> tuple[int, int, int]:
        idx, slide = item
        try:
            source_block_id = int(slide.get("source_block_id"))
        except (TypeError, ValueError):
            return 10**12, 10**12, idx
        start, block_idx = block_order.get(source_block_id, (10**12, 10**12))
        return start, block_idx, idx

    return [slide for _, slide in sorted(enumerate(slides), key=sort_key)]


def _is_mandatory_course_recap_anchor(anchor: dict | None) -> bool:
    if not isinstance(anchor, dict):
        return False
    anchor_id = str(anchor.get("anchor_id") or "").strip().lower()
    beat_id = str(anchor.get("beat_id") or "").strip().lower()
    section_kind = str(anchor.get("section_kind") or "").strip().lower()
    template_type = _canonical_template(anchor.get("template_type"), fallback="")
    return (
        template_type == "recap"
        and (
            anchor_id.endswith("-conclusion-recap-slide")
            or "conclusion-recap" in anchor_id
            or beat_id.endswith("conclusion-recap")
            or section_kind == "course_conclusion"
        )
    )


def _normalize_slide(raw: dict, block: dict) -> dict:
    if not isinstance(raw, dict):
        return _fallback_slide(block, "invalid_slide")

    anchor_by_id = {
        str(anchor.get("anchor_id")): anchor
        for anchor in block.get("slide_anchors") or []
        if anchor.get("anchor_id")
    }
    slide_anchor_id = str(raw.get("slide_anchor_id") or raw.get("anchor_id") or "").strip()
    anchor = anchor_by_id.get(slide_anchor_id)
    if slide_anchor_id and not anchor and anchor_by_id:
        if len(anchor_by_id) == 1:
            anchor = next(iter(anchor_by_id.values()))
            slide_anchor_id = str(anchor.get("anchor_id") or "")
        else:
            slide_anchor_id = ""
    if not anchor and not slide_anchor_id and len(anchor_by_id) == 1:
        anchor = next(iter(anchor_by_id.values()))
        slide_anchor_id = str(anchor.get("anchor_id") or "")
    requested_template = _canonical_template(
        raw.get("template_type")
        or raw.get("selected_existing_template")
        or raw.get("template")
        or (anchor or {}).get("template_type"),
        fallback="reflection",
    )
    template = requested_template
    mandatory_course_recap = _is_mandatory_course_recap_anchor(anchor)
    if mandatory_course_recap:
        template = "recap"

    event_type = raw.get("event_type") or "concept"
    if event_type not in EVENT_TYPES:
        event_type = "concept"
    if mandatory_course_recap:
        event_type = "recap"

    fallback_title = _fallback_title(block)
    fallback_text = _shorten(block.get("text", ""), 260)
    raw_data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    anchor_fields = (anchor or {}).get("fields_hint") if isinstance((anchor or {}).get("fields_hint"), dict) else {}
    slide_data_payload = {**anchor_fields, **raw_data}
    if template == "quotable" and anchor_fields.get("quote"):
        slide_data_payload["quote"] = anchor_fields["quote"]
    if template == "recap" and not mandatory_course_recap:
        reroute_event_type = "warning"
        rerouted_template = _forbidden_expression_template(
            slide_data_payload,
            fallback_title,
            fallback_text,
            raw.get("event_summary"),
            raw.get("source_quote"),
            raw.get("curation_reason"),
            (anchor or {}).get("role"),
            (anchor or {}).get("visual_goal"),
            (anchor or {}).get("must_cover"),
        )
        if not rerouted_template:
            reroute_event_type = "concept"
            rerouted_template = _three_part_structure_template(
                slide_data_payload,
                fallback_title,
                fallback_text,
                raw.get("event_summary"),
                raw.get("source_quote"),
                raw.get("curation_reason"),
                (anchor or {}).get("role"),
                (anchor or {}).get("visual_goal"),
                (anchor or {}).get("must_cover"),
            )
        if rerouted_template:
            template = rerouted_template
            if event_type == "recap":
                event_type = reroute_event_type
    if template == "casestudy":
        rerouted_template = _single_case_template(
            slide_data_payload,
            fallback_title,
            fallback_text,
            raw.get("event_summary"),
            raw.get("source_quote"),
            raw.get("curation_reason"),
            (anchor or {}).get("role"),
            (anchor or {}).get("visual_goal"),
            (anchor or {}).get("must_cover"),
        )
        if rerouted_template:
            template = rerouted_template
            if event_type in {"example", "concept"}:
                event_type = "tip" if rerouted_template == "tip" else "story"
    if template != "comparison" and not mandatory_course_recap:
        rerouted_template = _two_family_comparison_template(
            slide_data_payload,
            fallback_title,
            fallback_text,
            raw.get("event_summary"),
            raw.get("source_quote"),
            raw.get("curation_reason"),
            (anchor or {}).get("role"),
            (anchor or {}).get("visual_goal"),
            (anchor or {}).get("must_cover"),
        )
        if rerouted_template:
            template = rerouted_template
            if event_type in {"concept", "definition", "recap", "example"}:
                event_type = "comparison"
            slide_data_payload = _two_family_comparison_data(slide_data_payload, fallback_title, fallback_text)
    data = _normalize_slide_data(template, slide_data_payload, fallback_title, fallback_text)
    layout_variant, data, layout_fit = _resolve_slide_layout(
        template,
        data,
        raw.get("layout_variant") or slide_data_payload.get("layout_variant") or "",
    )
    rejected_templates = _normalize_rejected_templates(raw.get("rejected_templates"))
    template_decision_reason = _as_text(raw.get("template_decision_reason"), "")[:360]
    if requested_template != template:
        if not any(item.get("template") == requested_template for item in rejected_templates):
            rejected_templates.insert(0, {
                "template": requested_template,
                "why": f"Reclassement backend vers `{template}` après vérification des contraintes du passage.",
            })
            rejected_templates = rejected_templates[:4]
        if not template_decision_reason:
            template_decision_reason = (
                f"Reclassement backend: `{requested_template}` ne respecte pas les contraintes du passage; "
                f"`{template}` correspond mieux."
            )

    return {
        "source_block_id": block["source_block_id"],
        "pedagogical_shape": _normalize_pedagogical_shape(
            (anchor or {}).get("pedagogical_shape") if mandatory_course_recap else raw.get("pedagogical_shape") or (anchor or {}).get("pedagogical_shape"),
            template,
        ),
        "shape_evidence": _as_text(raw.get("shape_evidence"), "")[:260],
        "template_decision_reason": template_decision_reason,
        "rejected_templates": rejected_templates,
        "template_type": template,
        "layout_variant": layout_variant,
        "layout_fit": layout_fit,
        "event_type": event_type,
        "event_summary": _as_text(raw.get("event_summary"), fallback_title)[:180],
        "curation_reason": _as_text(raw.get("curation_reason"), "")[:360],
        "importance": _safe_int(raw.get("importance"), 3, 1, 5),
        "data": data,
        "slide_anchor_id": slide_anchor_id or (anchor or {}).get("anchor_id"),
        "beat_id": _as_text(raw.get("beat_id"), (anchor or {}).get("beat_id") or "")[:100],
        "anchor_role": (anchor or {}).get("role") or "",
        "source_quote": _as_text(raw.get("source_quote"), "")[:900],
        "ideal_template_gap": _normalize_template_gap(raw.get("ideal_template_gap"), template),
    }


def _generate_batch(blocks: list[dict], source_title: str, model: str, pace_profile: dict, max_batch_slides: int) -> tuple[list[dict], dict]:
    base_prompt = _prompt_for_blocks(blocks, source_title, pace_profile, max_batch_slides)
    last_error = None

    for attempt in range(2):
        prompt = base_prompt
        if attempt:
            prompt = f"""{base_prompt}

CORRECTION STRICTE:
La génération précédente du batch a échoué ({last_error}).
Cette fois, pour toute fenêtre dont `source_alignment` vaut `section_slide_alignment`, tu n'as pas le choix:
- produis exactement 1 slide pour cette fenêtre;
- recopie son unique `slide_anchor_id`;
- utilise son `source_block_id`;
- n'invente pas de contenu;
- choisis le meilleur `template_type` depuis le catalogue selon le texte réel, même s'il diffère du `planned_template_type`.
- exception stricte: un anchor de conclusion de cours (`cX-conclusion-recap-slide`) doit rester en `recap`.
- renseigne aussi `pedagogical_shape`, `shape_evidence`, `template_decision_reason` et `rejected_templates`.
Les autres fenêtres restent facultatives.
Réponds uniquement avec le JSON demandé.
"""
        try:
            response = post_message(
                [{"role": "user", "content": prompt}],
                max_tokens=5000,
                model=model,
                timeout=240,
                temperature=0 if attempt else None,
            )
            parsed = _parse_json_object(response)
            raw_slides = parsed.get("slides", [])
            if not isinstance(raw_slides, list):
                raise ValueError("Réponse LLM sans tableau slides")
        except Exception as exc:
            last_error = f"{exc.__class__.__name__}: {str(exc)[:180]}"
            if attempt == 0 and _strict_anchor_blocks(blocks):
                logger.warning(
                    "PIPELINE_SLIDES_BATCH_RETRY_STRICT blocks=%s-%s error=%s",
                    blocks[0].get("source_block_id") if blocks else None,
                    blocks[-1].get("source_block_id") if blocks else None,
                    exc,
                )
                continue
            raise

        template_backlog = _normalize_template_backlog(parsed.get("template_backlog") if isinstance(parsed.get("template_backlog"), list) else [])

        block_by_id = {block["source_block_id"]: block for block in blocks}
        per_block_counts = {}
        slides = []

        for raw in raw_slides:
            if not isinstance(raw, dict):
                continue
            try:
                source_block_id = int(raw.get("source_block_id"))
            except (TypeError, ValueError):
                continue
            block = block_by_id.get(source_block_id)
            if not block:
                continue
            if block.get("source_alignment") == "section_slide_alignment":
                per_block_limit = 1
            else:
                per_block_limit = max(
                    pace_profile["max_slides_per_block"],
                    len(block.get("slide_anchors") or []),
                )
            if per_block_counts.get(source_block_id, 0) >= per_block_limit:
                continue
            slides.append(_normalize_slide(raw, block))
            per_block_counts[source_block_id] = per_block_counts.get(source_block_id, 0) + 1
            if len(slides) >= max_batch_slides:
                break

        slides, strict_fallback_slides = _ensure_strict_anchor_slides(
            slides,
            blocks,
            "missing_strict_section_slide",
        )

        for slide in slides:
            gap = slide.get("ideal_template_gap") or {}
            if gap.get("needed") and gap.get("suggested_template_name") and gap.get("reason"):
                template_backlog.extend(_normalize_template_backlog([gap], max_items=1))

        return slides, {
            "template_backlog": _normalize_template_backlog(template_backlog),
            "raw_backlog_count": len(parsed.get("template_backlog") or []) if isinstance(parsed.get("template_backlog"), list) else 0,
            "curation_enabled": _slide_curation_enabled(),
            "attempts": attempt + 1,
            "strict_fallback_slides": strict_fallback_slides,
        }

    raise RuntimeError(last_error or "batch_generation_failed")


def _build_final_slide(slide: dict, block: dict, slide_number: int) -> dict:
    slide_kind = slide.get("slide_kind") or ("anchor" if slide.get("slide_anchor_id") else "generated")
    source_text = block["text"]
    source_alignment = block.get("source_alignment") or "source_window"
    source_ref = {
        "source_block_id": block["source_block_id"],
        "word_start": block["word_start"],
        "word_end": block["word_end"],
        "word_count": block["word_count"],
        "source_window_word_start": block["word_start"],
        "source_window_word_end": block["word_end"],
        "source_window_word_count": block["word_count"],
        "sub_part_index": block.get("sub_part_index"),
        "sub_part_name": block.get("sub_part_name"),
        "segments": block.get("source_refs", []),
        "slide_anchors": block.get("slide_anchors") or [],
        "selection_method": source_alignment,
        "source_alignment": source_alignment,
    }
    quote = slide.get("source_quote") or ""
    quote_offsets = _quote_word_offsets(block.get("text", ""), quote)
    if quote_offsets:
        local_start, local_end = quote_offsets
        quote_start = block["word_start"] + local_start
        quote_end = block["word_start"] + local_end
        source_ref["highlight_word_start"] = quote_start
        source_ref["highlight_word_end"] = quote_end
        source_ref["source_quote"] = quote
        if source_alignment not in {"section_slide_alignment", "section_unanchored"}:
            source_ref["word_start"] = quote_start
            source_ref["word_end"] = quote_end
            source_ref["word_count"] = max(1, quote_end - quote_start)
            source_ref["selection_method"] = "source_quote"
            source_text = quote

    return {
        "slide_id": f"script-s{slide_number + 1:03d}-b{block['source_block_id'] + 1:03d}",
        "trigger_time": None,
        "end_time": None,
        "pedagogical_shape": slide.get("pedagogical_shape") or _normalize_pedagogical_shape("", slide["template_type"]),
        "shape_evidence": slide.get("shape_evidence") or "",
        "template_decision_reason": slide.get("template_decision_reason") or "",
        "rejected_templates": slide.get("rejected_templates") or [],
        "template_type": slide["template_type"],
        "data": slide["data"],
        "event_type": slide["event_type"],
        "event_summary": slide["event_summary"],
        "slide_anchor_id": slide.get("slide_anchor_id"),
        "beat_id": slide.get("beat_id"),
        "anchor_role": slide.get("anchor_role"),
        "slide_kind": slide_kind,
        "transition_effect": slide.get("transition_effect") or ("swipe-left-to-right" if slide_kind == "anchor" else "fade"),
        "source_text": source_text,
        "source_ref": source_ref,
        "importance": slide.get("importance", 3),
        "curation_reason": slide.get("curation_reason") or "",
        "ideal_template_gap": slide.get("ideal_template_gap") or _normalize_template_gap(None, slide["template_type"]),
        **({"fallback_reason": slide["fallback_reason"]} if slide.get("fallback_reason") else {}),
    }


def _slide_word_range(slide: dict) -> tuple[int, int] | None:
    source_ref = slide.get("source_ref") or {}
    try:
        start = int(source_ref.get("word_start"))
        end = int(source_ref.get("word_end"))
    except (TypeError, ValueError):
        return None
    if end <= start:
        return None
    return start, end


def _blocks_for_word_range(source_blocks: list[dict], start: int, end: int) -> list[dict]:
    return [
        block
        for block in source_blocks
        if int(block.get("word_end") or 0) > start and int(block.get("word_start") or 0) < end
    ]


def _chapter_label_for_blocks(blocks: list[dict]) -> str:
    names = []
    seen = set()
    for block in blocks:
        name = str(block.get("sub_part_name") or "").strip()
        if not name or name in seen:
            continue
        names.append(name)
        seen.add(name)
        if len(names) >= 3:
            break
    return " · ".join(names) if names else "Séquence en cours"


def _text_for_word_range(blocks: list[dict], start: int, end: int) -> str:
    excerpts = []
    for block in blocks:
        block_start = int(block.get("word_start") or 0)
        words = str(block.get("text") or "").split()
        local_start = max(0, start - block_start)
        local_end = min(len(words), end - block_start)
        if local_end > local_start:
            excerpts.append(" ".join(words[local_start:local_end]))
    return "\n\n".join(excerpts).strip()


def _build_context_slide(source: dict, source_blocks: list[dict], start: int, end: int, slide_number: int) -> dict | None:
    gap_blocks = _blocks_for_word_range(source_blocks, start, end)
    if not gap_blocks:
        return None

    source_text = _shorten(_text_for_word_range(gap_blocks, start, end), 1200)
    word_count = max(0, end - start)
    chapter = _chapter_label_for_blocks(gap_blocks)
    first = gap_blocks[0]
    last = gap_blocks[-1]
    source_refs = []
    for block in gap_blocks:
        source_refs.extend(block.get("source_refs") or [])

    return {
        "slide_id": f"script-s{slide_number + 1:03d}-context-w{start:05d}",
        "trigger_time": None,
        "end_time": None,
        "pedagogical_shape": "idee_forte",
        "shape_evidence": "",
        "template_decision_reason": "",
        "rejected_templates": [],
        "template_type": "reflection",
        "data": {
            "formation_name": source.get("program_title") or source.get("folder_name") or "Formation",
            "chapter": chapter,
            "label": source.get("folder_name") or "",
        },
        "event_type": "filler",
        "event_summary": f"Contexte visuel pendant : {chapter}",
        "slide_anchor_id": None,
        "beat_id": "",
        "anchor_role": "",
        "slide_kind": "context",
        "transition_effect": "fade",
        "source_text": source_text,
        "source_ref": {
            "source_block_id": first["source_block_id"],
            "word_start": start,
            "word_end": end,
            "word_count": word_count,
            "sub_part_index": first.get("sub_part_index"),
            "sub_part_name": chapter,
            "segments": source_refs,
            "slide_anchors": [],
            "context_gap": True,
            "source_block_start": first.get("source_block_id"),
            "source_block_end": last.get("source_block_id"),
        },
        "importance": 1,
    }


def _insert_context_slides_for_gaps(final_slides: list[dict], source_blocks: list[dict], source: dict, total_words: int) -> tuple[list[dict], int]:
    if not _context_gap_slides_enabled() and final_slides:
        return final_slides, 0

    if not final_slides:
        context = _build_context_slide(source, source_blocks, 0, total_words, 0)
        return ([context] if context else []), 1 if context else 0

    ordered = sorted(final_slides, key=lambda slide: (_slide_word_range(slide) or (10**12, 10**12))[0])
    with_context = []
    cursor = 0
    inserted = 0

    for slide in ordered:
        word_range = _slide_word_range(slide)
        if not word_range:
            continue
        start, end = word_range
        if start > cursor:
            context = _build_context_slide(source, source_blocks, cursor, start, len(with_context))
            if context:
                with_context.append(context)
                inserted += 1
        slide["slide_kind"] = "anchor" if slide.get("slide_anchor_id") else "generated"
        slide["transition_effect"] = "swipe-left-to-right" if slide["slide_kind"] == "anchor" else "fade"
        with_context.append(slide)
        cursor = max(cursor, end)

    if total_words > cursor:
        context = _build_context_slide(source, source_blocks, cursor, total_words, len(with_context))
        if context:
            with_context.append(context)
            inserted += 1

    for idx, slide in enumerate(with_context):
        old_id = slide.get("slide_id") or f"script-s{idx + 1:03d}"
        if slide.get("slide_kind") == "context":
            slide["slide_id"] = f"script-s{idx + 1:03d}-context"
        else:
            suffix = old_id.split("-b", 1)[1] if "-b" in old_id else f"{idx + 1:03d}"
            slide["slide_id"] = f"script-s{idx + 1:03d}-b{suffix}"

    return with_context, inserted


def _cap_planned_slides(slides: list[dict], max_slides: int) -> tuple[list[dict], int]:
    if len(slides) <= max_slides:
        return slides, 0

    indexed = list(enumerate(slides))
    anchored = [
        item for item in indexed
        if item[1].get("slide_anchor_id") or item[1].get("anchor_id")
    ]

    if len(anchored) <= max_slides:
        selected = list(anchored)
        selected_indices = {idx for idx, _ in selected}
        unanchored = [
            item for item in indexed
            if item[0] not in selected_indices
        ]
        selected.extend(
            sorted(
                unanchored,
                key=lambda item: (item[1].get("importance", 3), -item[0]),
                reverse=True,
            )[: max_slides - len(selected)]
        )
    else:
        selected = sorted(
            anchored,
            key=lambda item: (item[1].get("importance", 3), -item[0]),
            reverse=True,
        )[:max_slides]

    selected_indices = {idx for idx, _ in selected}
    capped = [slide for idx, slide in indexed if idx in selected_indices]
    return capped, len(slides) - len(capped)


def _raise_max_slides_for_anchors(
    max_slides: int,
    anchors: list[dict],
    *,
    folder_id: int | None = None,
    content_job_id: int | None = None,
    source: str = "plan",
) -> int:
    anchor_count = len(anchors or [])
    if anchor_count <= max_slides:
        return max_slides
    logger.info(
        "PIPELINE_SLIDES_MAX_RAISED_FOR_ANCHORS folder=%s content_job=%s source=%s requested_max_slides=%s anchors=%s",
        folder_id,
        content_job_id,
        source,
        max_slides,
        anchor_count,
    )
    return anchor_count


def _run_slide_generation_from_source(
    source: dict,
    *,
    job_id: int | None = None,
    max_slides: int = DEFAULT_MAX_SLIDES,
    pace: str = "normal",
    target_words_per_slide: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    model: str | None = None,
    content_plan: dict | None = None,
    persist: bool = True,
) -> dict:
    started_at = time.time()
    folder_id = source.get("folder_id")

    requested_max_slides = _safe_int(max_slides, DEFAULT_MAX_SLIDES, 5, 140)
    max_slides = requested_max_slides
    pace_config = _pace_profile(pace)
    batch_size = _safe_int(batch_size, DEFAULT_BATCH_SIZE, 1, 10)
    model = model or default_model()
    section_alignment_debug = {}

    if content_plan is None and not source.get("preview_only") and not source.get("beat_aligned"):
        content_plan = _load_content_plan(source)
    slide_anchors = _extract_slide_anchors_from_plan(content_plan)
    max_slides = _raise_max_slides_for_anchors(
        max_slides,
        slide_anchors,
        folder_id=folder_id,
        content_job_id=source.get("content_job_id"),
        source="content_plan",
    )
    source_alignment_mode = "draft_beat_aligned" if source.get("beat_aligned") else "text_windows"

    if source.get("beat_aligned"):
        source_blocks, total_words = _build_beat_source_blocks(source["segments"])
        effective_words_per_slide = 0
    else:
        aligned = None
        if (
            _section_slide_alignment_enabled()
            and not source.get("preview_only")
            and slide_anchors
        ):
            aligned = _build_section_aligned_source_blocks(source, slide_anchors, model)
        if aligned:
            source_blocks, total_words, section_alignment_debug = aligned
            effective_words_per_slide = 0
            source_alignment_mode = "section_slide_alignment"
        else:
            units, total_words = _build_text_units(source["segments"], max_unit_words=900)
            average_words_cap = max(180, math.ceil(total_words / max(1, max_slides)))
            context_words = _safe_int(
                target_words_per_slide,
                max(DEFAULT_CONTEXT_WORDS, int(average_words_cap * pace_config["context_multiplier"])),
                700,
                5000,
            )
            source_blocks, effective_words_per_slide = _build_source_blocks(
                units,
                total_words=total_words,
                target_words=context_words,
                max_slides=max_slides,
            )
    if source.get("beat_aligned"):
        slide_anchors = [
            anchor
            for block in source_blocks
            for anchor in (block.get("slide_anchors") or [])
        ]
        max_slides = _raise_max_slides_for_anchors(
            max_slides,
            slide_anchors,
            folder_id=folder_id,
            content_job_id=source.get("content_job_id"),
            source="beat_aligned_source",
        )
    elif source_alignment_mode != "section_slide_alignment":
        _assign_slide_anchors_to_source_blocks(source_blocks, slide_anchors)

    if not source_blocks:
        raise ValueError("Aucun bloc source exploitable")

    batch_jobs = []
    for batch_index, start in enumerate(range(0, len(source_blocks), batch_size)):
        batch = source_blocks[start : start + batch_size]
        max_batch_slides = max(
            1,
            min(
                len(batch) * pace_config["max_slides_per_block"],
                math.ceil(max_slides * (len(batch) / max(1, len(source_blocks)))) + 1,
            ),
        )
        batch_anchor_count = sum(len(block.get("slide_anchors") or []) for block in batch)
        if batch_anchor_count:
            max_batch_slides = max(max_batch_slides, min(batch_anchor_count, max_slides))
        batch_jobs.append(
            {
                "batch_index": batch_index,
                "start": start,
                "batch": batch,
                "max_batch_slides": max_batch_slides,
                "anchor_count": batch_anchor_count,
            }
        )
    slide_batch_workers = min(_slide_batch_workers(model), max(1, len(batch_jobs)))

    logger.info(
        "PIPELINE_SLIDES_START folder=%s content_job=%s platform=%s words=%s source_segments=%s "
        "context_windows=%s max_slides=%s pace=%s context_words=%s batch_size=%s batch_workers=%s model=%s anchors=%s",
        folder_id,
        source.get("content_job_id"),
        source.get("platform_id"),
        total_words,
        len(source["segments"]),
        len(source_blocks),
        max_slides,
        pace_config["label"],
        effective_words_per_slide,
        batch_size,
        slide_batch_workers,
        model,
        len(slide_anchors),
    )

    planned = []
    batches_debug = []
    template_backlog = []

    def _run_slide_batch(job: dict) -> dict:
        batch = job["batch"]
        start = job["start"]
        max_batch_slides = job["max_batch_slides"]
        batch_anchor_count = job["anchor_count"]
        batch_started_at = time.time()
        logger.info(
            "PIPELINE_SLIDES_BATCH_START folder=%s content_job=%s batch=%s-%s blocks=%s max_batch_slides=%s anchors=%s",
            folder_id,
            source.get("content_job_id"),
            start,
            start + len(batch) - 1,
            len(batch),
            max_batch_slides,
            batch_anchor_count,
        )
        try:
            batch_slides, curation_debug = _generate_batch(batch, source["program_title"], model, pace_config, max_batch_slides)
            status = "llm"
        except Exception as exc:
            logger.exception("PIPELINE_SLIDES_BATCH_ERROR folder=%s batch=%s-%s error=%s", folder_id, start, start + len(batch) - 1, exc)
            batch_slides, strict_fallback_slides = _ensure_strict_anchor_slides(
                [],
                batch,
                "batch_error_strict_anchor_fallback",
            )
            curation_debug = {
                "template_backlog": [],
                "curation_enabled": _slide_curation_enabled(),
                "strict_fallback_slides": strict_fallback_slides,
                "fallback_reason": f"{exc.__class__.__name__}: {str(exc)[:180]}",
            }
            status = "fallback"
        logger.info(
            "PIPELINE_SLIDES_BATCH_DONE folder=%s content_job=%s batch=%s-%s status=%s slides=%s duration_ms=%s",
            folder_id,
            source.get("content_job_id"),
            start,
            start + len(batch) - 1,
            status,
            len(batch_slides),
            int((time.time() - batch_started_at) * 1000),
        )
        return {
            "batch_index": job["batch_index"],
            "slides": batch_slides,
            "debug": {
                "start_block": batch[0]["source_block_id"],
                "end_block": batch[-1]["source_block_id"],
                "blocks": len(batch),
                "max_slides": max_batch_slides,
                "anchors": batch_anchor_count,
                "status": status,
                "curation": curation_debug,
            },
        }

    batch_results = [None] * len(batch_jobs)
    if batch_jobs and slide_batch_workers > 1:
        logger.info(
            "PIPELINE_SLIDES_BATCH_PARALLEL_START folder=%s content_job=%s batches=%s workers=%s",
            folder_id,
            source.get("content_job_id"),
            len(batch_jobs),
            slide_batch_workers,
        )
        with ThreadPoolExecutor(max_workers=slide_batch_workers) as executor:
            future_map = {
                executor.submit(_run_slide_batch, job): job
                for job in batch_jobs
            }
            for future in as_completed(future_map):
                job = future_map[future]
                try:
                    result = future.result()
                except Exception as exc:
                    logger.exception(
                        "PIPELINE_SLIDES_BATCH_FUTURE_ERROR folder=%s content_job=%s batch=%s-%s error=%s",
                        folder_id,
                        source.get("content_job_id"),
                        job["start"],
                        job["start"] + len(job["batch"]) - 1,
                        exc,
                    )
                    batch_slides, strict_fallback_slides = _ensure_strict_anchor_slides(
                        [],
                        job["batch"],
                        "batch_future_error_strict_anchor_fallback",
                    )
                    result = {
                        "batch_index": job["batch_index"],
                        "slides": batch_slides,
                        "debug": {
                            "start_block": job["batch"][0]["source_block_id"],
                            "end_block": job["batch"][-1]["source_block_id"],
                            "blocks": len(job["batch"]),
                            "max_slides": job["max_batch_slides"],
                            "anchors": job["anchor_count"],
                            "status": "fallback",
                            "curation": {
                                "template_backlog": [],
                                "curation_enabled": _slide_curation_enabled(),
                                "strict_fallback_slides": strict_fallback_slides,
                                "fallback_reason": f"{exc.__class__.__name__}: {str(exc)[:180]}",
                            },
                        },
                    }
                batch_results[job["batch_index"]] = result
    else:
        for job in batch_jobs:
            batch_results[job["batch_index"]] = _run_slide_batch(job)

    for result in batch_results:
        if not result:
            continue
        curation_debug = result["debug"].get("curation") or {}
        template_backlog.extend(curation_debug.get("template_backlog") or [])
        planned.extend(result["slides"])
        batches_debug.append(result["debug"])

    dropped_unanchored = 0
    if not planned and source_blocks and not slide_anchors:
        planned = [_fallback_slide(source_blocks[0], "empty_curation_deck")]

    strict_anchor_fallback_slides = sum(
        int((batch.get("curation") or {}).get("strict_fallback_slides") or 0)
        for batch in batches_debug
    )
    planned, global_strict_fallback_slides = _ensure_strict_anchor_slides(
        planned,
        source_blocks,
        "global_missing_strict_anchor_fallback",
    )
    strict_anchor_fallback_slides += global_strict_fallback_slides
    if global_strict_fallback_slides:
        logger.warning(
            "PIPELINE_SLIDES_STRICT_ANCHOR_GLOBAL_FALLBACK folder=%s content_job=%s inserted=%s",
            folder_id,
            source.get("content_job_id"),
            global_strict_fallback_slides,
        )

    planned, dropped_by_cap = _cap_planned_slides(planned, max_slides)
    planned, post_cap_strict_fallback_slides = _ensure_strict_anchor_slides(
        planned,
        source_blocks,
        "post_cap_missing_strict_anchor_fallback",
    )
    strict_anchor_fallback_slides += post_cap_strict_fallback_slides
    if post_cap_strict_fallback_slides:
        logger.warning(
            "PIPELINE_SLIDES_STRICT_ANCHOR_POST_CAP_FALLBACK folder=%s content_job=%s inserted=%s",
            folder_id,
            source.get("content_job_id"),
            post_cap_strict_fallback_slides,
        )
    planned, coverage_repair_slides = _ensure_unanchored_coverage_slides(
        planned,
        source_blocks,
        "unanchored_section_coverage_repair",
    )
    if coverage_repair_slides:
        logger.warning(
            "PIPELINE_SLIDES_UNANCHORED_COVERAGE_REPAIR folder=%s content_job=%s inserted=%s",
            folder_id,
            source.get("content_job_id"),
            coverage_repair_slides,
        )
    planned = _sort_slides_by_source_order(planned, source_blocks)
    template_backlog = _normalize_template_backlog(template_backlog)

    block_by_id = {block["source_block_id"]: block for block in source_blocks}
    final_slides = []
    for slide_idx, slide in enumerate(planned):
        block = block_by_id.get(slide["source_block_id"])
        if block:
            final_slides.append(_build_final_slide(slide, block, slide_idx))
    context_slides_inserted = 0
    if slide_anchors:
        final_slides, context_slides_inserted = _insert_context_slides_for_gaps(
            final_slides,
            source_blocks,
            source,
            total_words,
        )

    timeline = [
        {
            "slide_index": idx,
            "slide_id": slide["slide_id"],
            "type": slide["event_type"],
            "summary": slide["event_summary"],
            "slide_anchor_id": slide.get("slide_anchor_id"),
            "beat_id": slide.get("beat_id"),
            "slide_kind": slide.get("slide_kind"),
            "transition_effect": slide.get("transition_effect"),
            "start_time": None,
            "end_time": None,
            "source_block_id": slide["source_ref"]["source_block_id"],
            "word_start": slide["source_ref"]["word_start"],
            "word_end": slide["source_ref"]["word_end"],
            "word_count": slide["source_ref"]["word_count"],
        }
        for idx, slide in enumerate(final_slides)
    ]

    source_block_debug = [
        {
            "source_block_id": block["source_block_id"],
            "sub_part_name": block.get("sub_part_name"),
            "word_start": block["word_start"],
            "word_end": block["word_end"],
            "word_count": block["word_count"],
            "source_alignment": block.get("source_alignment"),
            "section_alignment": block.get("section_alignment") or {},
            "source_refs": block.get("source_refs", []),
            "slide_anchors": block.get("slide_anchors") or [],
            "excerpt": _shorten(block.get("text", ""), 360),
        }
        for block in source_blocks
    ]

    result = {
        "slides": final_slides,
        "timeline": timeline,
        "stats": {
            "generation_mode": "script_anchor_guided_curation" if slide_anchors else "script_curation",
            "folder_id": source["folder_id"],
            "folder_name": source["folder_name"],
            "job_id": job_id,
            "source": "preview_text" if source.get("preview_only") else "content_generation_segments",
            "source_alignment": source_alignment_mode,
            "content_plan_source": CONTENT_PLAN_BLOB if content_plan else None,
            "source_words": total_words,
            "source_segments": len(source["segments"]),
            "beat_aligned_segments": source.get("beat_aligned_segments"),
            "beat_aligned_anchors": source.get("beat_aligned_anchors"),
            "source_blocks": len(source_blocks),
            "source_windows": len(source_blocks),
            "slide_anchors_found": len(slide_anchors),
            "slide_anchors_attached": sum(len(block.get("slide_anchors") or []) for block in source_blocks),
            "pace": pace_config["label"],
            "context_words": effective_words_per_slide,
            "max_slides_requested": requested_max_slides,
            "max_slides": max_slides,
            "slides_generated": len(final_slides),
            "context_slides_inserted": context_slides_inserted,
            "slides_dropped_by_cap": dropped_by_cap,
            "slides_dropped_unanchored": dropped_unanchored,
            "strict_anchor_fallback_slides": strict_anchor_fallback_slides,
            "coverage_repair_slides_inserted": coverage_repair_slides,
            "slide_curation_enabled": _slide_curation_enabled(),
            "section_slide_alignment_enabled": _section_slide_alignment_enabled(),
            "section_slide_alignment": section_alignment_debug,
            "template_backlog_count": len(template_backlog),
            "llm_batches": len(batches_debug),
            "slide_batch_workers": slide_batch_workers,
            "model": model,
        },
        "pipeline_debug": {
            "generation_mode": "script_anchor_guided_curation" if slide_anchors else "script_curation",
            "slide_anchors": slide_anchors,
            "section_slide_alignment": section_alignment_debug,
            "template_backlog": template_backlog,
            "source_blocks": source_block_debug,
            "slide_plan": [
                {
                    "source_block_id": slide["source_block_id"],
                    "slide_anchor_id": slide.get("slide_anchor_id"),
                    "beat_id": slide.get("beat_id"),
                    "pedagogical_shape": slide.get("pedagogical_shape") or "",
                    "shape_evidence": slide.get("shape_evidence") or "",
                    "template_decision_reason": slide.get("template_decision_reason") or "",
                    "rejected_templates": slide.get("rejected_templates") or [],
                    "template": slide["template_type"],
                    "event_type": slide["event_type"],
                    "title_hint": slide["data"].get("title", ""),
                    "content_hint": slide["event_summary"],
                    "curation_reason": slide.get("curation_reason") or "",
                    "ideal_template_gap": slide.get("ideal_template_gap") or {},
                }
                for slide in planned
            ],
            "final_slides": [
                {
                    "slide_id": slide.get("slide_id"),
                    "slide_kind": slide.get("slide_kind"),
                    "transition_effect": slide.get("transition_effect"),
                    "pedagogical_shape": slide.get("pedagogical_shape") or "",
                    "shape_evidence": slide.get("shape_evidence") or "",
                    "template_decision_reason": slide.get("template_decision_reason") or "",
                    "rejected_templates": slide.get("rejected_templates") or [],
                    "template": slide.get("template_type"),
                    "event_type": slide.get("event_type"),
                    "slide_anchor_id": slide.get("slide_anchor_id"),
                    "curation_reason": slide.get("curation_reason") or "",
                    "ideal_template_gap": slide.get("ideal_template_gap") or {},
                    "word_start": (slide.get("source_ref") or {}).get("word_start"),
                    "word_end": (slide.get("source_ref") or {}).get("word_end"),
                }
                for slide in final_slides
            ],
            "batches": batches_debug,
        },
    }
    deck_id = None
    if persist:
        deck_id = _persist_script_slide_deck(
            source,
            result,
            pace=pace_config["label"],
            max_slides=max_slides,
            model=model,
        )
        result["stats"]["deck_id"] = deck_id
        result["pipeline_debug"]["deck_id"] = deck_id
    else:
        result["stats"]["preview_only"] = True
        result["pipeline_debug"]["preview_only"] = True
    logger.info(
        "PIPELINE_SLIDES_DONE folder=%s content_job=%s deck_id=%s preview=%s slides=%s template_backlog=%s dropped_by_cap=%s duration_ms=%s",
        folder_id,
        source.get("content_job_id"),
        deck_id,
        bool(source.get("preview_only")),
        len(final_slides),
        len(template_backlog),
        dropped_by_cap,
        int((time.time() - started_at) * 1000),
    )
    return result


def preview_slides_from_text(
    text: str,
    *,
    title: str = "Prévisualisation passage",
    template_type: str | None = None,
    visual_goal: str | None = None,
    fields_hint: dict | None = None,
    max_slides: int = 8,
    pace: str = "dense",
    model: str | None = None,
) -> dict:
    clean_text = _strip_tts_tags(text or "")
    if len(clean_text.split()) < 20:
        raise ValueError("Collez un passage d'au moins 20 mots pour générer une prévisualisation")
    if len(clean_text) > 30000:
        raise ValueError("Passage trop long pour le mode temporaire : limitez à environ 30 000 caractères")

    anchor = None
    template = _canonical_template(template_type, fallback="")
    if template:
        anchor = {
            "anchor_id": "preview-anchor-1",
            "beat_id": "preview-beat-1",
            "course_number": 1,
            "course_title": title,
            "part_number": 1,
            "part_title": "Passage isolé",
            "beat_order": 1,
            "beat_type": template,
            "role": visual_goal or "",
            "spoken_requirement": "",
            "template_type": template,
            "pedagogical_shape": _normalize_pedagogical_shape("", template),
            "visual_goal": visual_goal or "",
            "items_expected": None,
            "must_cover": "",
            "must_not_cover": "",
            "fields_hint": fields_hint if isinstance(fields_hint, dict) else {},
        }

    source = {
        "folder_id": 0,
        "folder_name": "Prévisualisation temporaire",
        "platform_id": 0,
        "content_job_id": 0,
        "formation_job_id": None,
        "program_title": _as_text(title, "Prévisualisation passage")[:120],
        "content_status": "preview",
        "total_words_declared": len(clean_text.split()),
        "preview_only": True,
        "segments": [
            {
                "segment_id": 0,
                "sub_part_index": 0,
                "sub_part_name": "Passage isolé",
                "passe": 1,
                "text": clean_text,
                "word_count": len(clean_text.split()),
                "reviewed": False,
                "dirty": False,
            }
        ],
    }

    content_plan = None
    if anchor:
        content_plan = {
            "courses": [
                {
                    "course_number": 1,
                    "course_title": title,
                    "parts": [
                        {
                            "part_number": 1,
                            "title": "Passage isolé",
                            "teaching_beats": [
                                {
                                    "beat_id": anchor["beat_id"],
                                    "type": template,
                                    "role": visual_goal or "",
                                    "spoken_requirement": "",
                                    "slide_anchor": {
                                        "enabled": True,
                                        "anchor_id": anchor["anchor_id"],
                                        "template_type": template,
                                        "pedagogical_shape": anchor["pedagogical_shape"],
                                        "visual_goal": visual_goal or "",
                                        "items_expected": None,
                                        "fields_hint": anchor["fields_hint"],
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        }

    return _run_slide_generation_from_source(
        source,
        job_id=None,
        max_slides=max_slides,
        pace=pace,
        model=model,
        content_plan=content_plan,
        persist=False,
    )


def generate_slides_from_script(
    folder_id: int,
    *,
    job_id: int | None = None,
    platform_id: int | None = None,
    max_slides: int = DEFAULT_MAX_SLIDES,
    pace: str = "normal",
    target_words_per_slide: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    model: str | None = None,
) -> dict:
    folder_id = _safe_int(folder_id, 0, 1, 10**9)
    if folder_id <= 0:
        raise ValueError("folder_id est requis")

    source = _prefer_beat_aligned_source(
        _load_script_source(folder_id, job_id=job_id, platform_id=platform_id)
    )
    return _run_slide_generation_from_source(
        source,
        job_id=job_id,
        max_slides=max_slides,
        pace=pace,
        target_words_per_slide=target_words_per_slide,
        batch_size=batch_size,
        model=model,
        persist=True,
    )
