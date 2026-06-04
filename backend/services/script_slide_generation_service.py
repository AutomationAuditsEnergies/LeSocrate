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
    "context",
    "welcome",
    "day_program",
    "day_program_7_steps",
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
TEMPLATE_ALIASES = {
    "welcome": "welcome",
    "day_welcome": "welcome",
    "day_program": "day_program",
    "day_program_7_steps": "day_program_7_steps",
    "program_7_steps": "day_program_7_steps",
    "roadmap_7_steps": "day_program_7_steps",
    "agenda": "day_program",
    "definition": "reflection",
    "concept": "reflection",
    "key_message": "reflection",
    "process": "facilitator",
    "method": "facilitator",
    "framework": "facilitator",
    "steps": "facilitator",
    "checklist": "recap",
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

EVENT_TYPES = {
    "filler",
    "welcome",
    "day_program",
    "day_program_7_steps",
    "recap",
    "story",
    "definition",
    "concept",
    "example",
    "process",
    "comparison",
    "data",
    "analogy",
    "warning",
    "tip",
    "opinion",
    "transition",
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
        templates.append({
            "template_id": template_id,
            "families": item.get("families") or [],
            "visual_role": item.get("visual_role") or "",
            "use_when": item.get("use_when") or "",
            "avoid_when": item.get("avoid_when") or "",
            "strong_signals": item.get("strong_signals") or [],
            "weak_signals": item.get("weak_signals") or [],
            "selection_rules": item.get("selection_rules") or [],
            "rejection_rules": item.get("rejection_rules") or [],
            "requires": item.get("requires") or {},
            "schema": item.get("schema") or {},
            "good_examples": item.get("good_examples") or [],
            "bad_examples": item.get("bad_examples") or [],
        })
    return json.dumps(
        {
            "version": catalog.get("version"),
            "principle": catalog.get("principle"),
            "templates": templates,
        },
        ensure_ascii=False,
        indent=2,
    )


def _slide_curation_enabled() -> bool:
    value = str(os.getenv("FORMATION_SLIDE_CURATION_ENABLED", "1")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _context_gap_slides_enabled() -> bool:
    value = str(os.getenv("FORMATION_SLIDE_CONTEXT_GAPS_ENABLED", "0")).strip().lower()
    return value not in {"0", "false", "no", "off"}


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
                "beat_order": order,
                "beat_type": str(beat.get("type") or "welcome"),
                "role": beat.get("role") or "",
                "spoken_requirement": beat.get("spoken_requirement") or "",
                "template_type": template_type,
                "visual_goal": slide_anchor.get("visual_goal") or "",
                "items_expected": slide_anchor.get("items_expected"),
                "must_cover": slide_anchor.get("must_cover") or "",
                "must_not_cover": slide_anchor.get("must_not_cover") or "",
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
                    "beat_order": order,
                    "beat_type": str(beat.get("type") or "concept"),
                    "role": beat.get("role") or "",
                    "spoken_requirement": beat.get("spoken_requirement") or "",
                    "template_type": template_type,
                    "visual_goal": slide_anchor.get("visual_goal") or "",
                    "items_expected": slide_anchor.get("items_expected"),
                    "must_cover": slide_anchor.get("must_cover") or "",
                    "must_not_cover": slide_anchor.get("must_not_cover") or "",
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
        body_anchors = [anchor for anchor in course_anchors if int(anchor.get("part_number") or 0) != 0]
        if opening_anchors:
            blocks[0]["slide_anchors"].extend(opening_anchors)
        course_anchors = body_anchors
        if not course_anchors:
            continue
        if len(blocks) == 1:
            blocks[0]["slide_anchors"].extend(course_anchors)
            continue
        total = max(1, len(course_anchors))
        for idx, anchor in enumerate(course_anchors):
            block_idx = min(len(blocks) - 1, int((idx + 0.5) * len(blocks) / total))
            blocks[block_idx]["slide_anchors"].append(anchor)


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
                "template_type": _canonical_template(segment.get("template_type") or anchor.get("template_type")),
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


def _prompt_for_blocks(blocks: list[dict], source_title: str, pace_profile: dict, max_batch_slides: int) -> str:
    payload = [
        {
            "source_block_id": block["source_block_id"],
            "sub_part_name": block.get("sub_part_name"),
            "word_count": block.get("word_count"),
            "text": _shorten(block.get("text", ""), 3600),
            "slide_anchors": [
                {
                    "anchor_id": anchor.get("anchor_id"),
                    "beat_id": anchor.get("beat_id"),
                    "part_title": anchor.get("part_title"),
                    "beat_type": anchor.get("beat_type"),
                    "spoken_requirement": anchor.get("spoken_requirement"),
                    "template_type": anchor.get("template_type"),
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
- Le texte final est la source de vérité. Les `slide_anchors` du plan sont des indices pédagogiques forts, pas des obligations.
- Si un anchor prévu ne correspond pas clairement au texte réel, ignore-le.
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
- Si une fenêtre contient `slide_anchors`, ils t'indiquent l'intention initiale du plan. Utilise-les si le texte source couvre réellement leur intention.
- Si un anchor n'est pas couvert par le texte source, ignore-le au lieu d'inventer.
- Quand tu utilises un anchor, recopie exactement `slide_anchor_id` et `beat_id` dans la slide générée.
- Un anchor correspond à une intention pédagogique précise, pas à toute la fenêtre.
- Pour chaque anchor utilisé, choisis `source_quote` dans la portion exacte du texte qui réalise cette intention.
- Ne rattache jamais une slide au passage d'un anchor voisin parce qu'il contient des mots proches, une image répétée ou le même thème général.
- Si deux anchors voisins sont présents, vérifie leur ordre narratif : la première slide doit pointer vers le premier mouvement oral, la deuxième vers le mouvement oral suivant.
- `analogy` s'utilise seulement quand le passage raconte une situation hors métier pour expliquer une notion. Un passage qui commence par "Imaginez que..." peut être une analogie si la scène imaginée n'est pas le métier lui-même. Un exemple client/conseiller/usager, même fictif, relève plutôt de `casestudy`, `reflection`, `warning` ou d'un autre template compatible.
- Si aucun anchor n'est disponible pour une fenêtre, sélectionne les thèmes, points et idées pédagogiques qui méritent vraiment un visuel.
- Tu peux produire 0, 1 ou plusieurs slides par fenêtre selon la densité réelle des idées.
- Maximum {max_batch_slides} slides pour tout ce batch.
- Maximum {pace_profile["max_slides_per_block"]} slides pour une même fenêtre source, sauf si plusieurs slide_anchors explicites y sont attachés.
- {pace_profile["instruction"]}
- Ne rajoute aucun timing. Ne crée pas de slide absente du texte.
- Le JSON de plan peut orienter le choix, mais le texte final reste le contrôle : une slide doit correspondre à ce qui est vraiment dit.
- Le deck doit être lisible: titres courts, contenu très synthétique, aucun pavé.
- Si deux idées sont proches, regroupe-les. Si une fenêtre répète une idée déjà traitée, saute-la.
- Pour chaque slide, ajoute `source_quote`: une citation exacte, copiée mot pour mot depuis la fenêtre source, qui justifie cette slide.
- `source_quote` doit être courte mais suffisante pour localiser la slide dans le texte: idéalement 15 à 60 mots.
- Ajoute `curation_reason`: pourquoi ce passage mérite un visuel plutôt qu'un simple oral.
- Réponds uniquement en JSON valide.

{curation_rules}

PROCESSUS OBLIGATOIRE:
1. Lis toutes les fenêtres du batch et repère seulement les moments qui méritent vraiment un visuel.
2. Vérifie chaque moment contre les `slide_anchors` éventuels: anchor couvert, anchor ignoré, ou moment non prévu mais meilleur.
3. Pour chaque moment retenu, choisis le template existant depuis le catalogue en appliquant `use_when`, `avoid_when`, `strong_signals`, `weak_signals`, `selection_rules` et `rejection_rules`.
4. Produis uniquement les slides retenues. Ne remplis pas le quota si le texte ne le justifie pas.
5. Si le meilleur rendu demanderait un template absent, renseigne `ideal_template_gap`, mais utilise quand même le meilleur template existant.

{density_rules}

CATALOGUE TEMPLATES:
{_template_catalog_for_prompt()}

TEMPLATES AUTORISÉS ET SCHÉMAS:
- reflection: data={{"title":"3-6 mots","text":"1-2 phrases"}}
- casestudy: data={{"title":"3-6 mots","cases":[{{"title":"court","desc":"1 phrase"}}]}} avec 2-3 cases
- facilitator: data={{"title":"3-6 mots","steps":[{{"title":"court","desc":"1 phrase","icon":"target|gear|flash|flag","color":"orange|purple|lime|blue"}}]}} avec 2-4 steps
- stats: data={{"title":"3-6 mots","description":"1 phrase","stats":[{{"number":"chiffre"}}],"columns":["phrase courte","phrase courte"]}}
- story: data={{"title":"3-6 mots","narrative":"1-2 phrases","moral":"1 phrase"}}
- recap: data={{"title":"3-6 mots","points":["point court","point court","point court"]}}
- analogy: data={{"title":"5-10 mots","analogy_label":"situation concrète, 2-5 mots","concept_label":"notion métier, 2-5 mots","text":"1 phrase courte","takeaway":"1 phrase clé","image_prompt":"prompt PNG sans texte ni humains","image_alt":"description accessible"}}
- warning: data={{"title":"3-6 mots","text":"1-2 phrases"}}
- tip: data={{"title":"3-6 mots","text":"1-2 phrases"}}
- opinion: data={{"title":"3-6 mots","text":"1-2 phrases"}}
- transition: data={{"title":"3-6 mots","from_topic":"2-4 mots","to_topic":"2-4 mots"}}
- chart: data={{"title":"3-6 mots","description":"1 phrase","chartData":null}}

Choisis `event_type` parmi:
recap, story, definition, concept, example, process, comparison, data, analogy, warning, tip, opinion, transition.

FORMAT EXACT:
{{
  "slides": [
    {{
      "source_block_id": 0,
      "slide_anchor_id": "anchor optionnel si utilisé",
      "beat_id": "beat optionnel si utilisé",
      "template_type": "reflection",
      "event_type": "concept",
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


def _as_text(value, fallback: str = "") -> str:
    text = str(value or fallback).strip()
    return text or fallback


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

    if template == "welcome":
        return {
            "title": _as_text(data.get("title"), "Bienvenue")[:60],
            "subtitle": _as_text(data.get("subtitle") or data.get("day_label"), fallback_title)[:120],
            "formation_name": _as_text(data.get("formation_name"), fallback_text)[:120],
            "day_label": _as_text(data.get("day_label"), "")[:40],
        }

    if template in {"day_program", "day_program_7_steps"}:
        max_items = 7 if template == "day_program_7_steps" else 7
        items = []
        for item in _limit_list(data.get("items") or data.get("points"), max_items):
            if isinstance(item, dict):
                label = _as_text(item.get("title") or item.get("label"), "")
            else:
                label = _as_text(item, "")
            if label:
                items.append(label[:120])
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
        for item in _limit_list(data.get("cases"), 3):
            if isinstance(item, dict):
                cases.append({"title": _as_text(item.get("title"), "Point clé")[:50], "desc": _as_text(item.get("desc"), fallback_text)[:180]})
        return {"title": title, "cases": cases or [{"title": "Point clé", "desc": text}]}

    if template == "facilitator":
        steps = []
        for idx, item in enumerate(_limit_list(data.get("steps"), 4)):
            if isinstance(item, dict):
                steps.append(
                    {
                        "title": _as_text(item.get("title"), f"Étape {idx + 1}")[:50],
                        "desc": _as_text(item.get("desc") or item.get("detail"), fallback_text)[:160],
                        "icon": item.get("icon") if item.get("icon") in ("target", "gear", "flash", "flag") else "target",
                        "color": item.get("color") if item.get("color") in ("orange", "purple", "lime", "blue") else "orange",
                    }
                )
        return {"title": title, "steps": steps or [{"title": "Étape clé", "desc": text, "icon": "target", "color": "orange"}]}

    if template == "stats":
        stats = []
        for item in _limit_list(data.get("stats"), 3):
            if isinstance(item, dict):
                stats.append({"number": _as_text(item.get("number") or item.get("value"), "1")[:16]})
        columns = [_as_text(item, fallback_text)[:180] for item in _limit_list(data.get("columns"), 3)]
        return {"title": title, "description": text, "stats": stats or [{"number": "1"}], "columns": columns or [text]}

    if template == "story":
        return {
            "title": title,
            "narrative": _as_text(data.get("narrative"), text)[:360],
            "moral": _as_text(data.get("moral"), "À retenir pour la pratique.")[:180],
        }

    if template == "recap":
        points = [_as_text(item, "")[:140] for item in _limit_list(data.get("points"), 4)]
        points = [point for point in points if point]
        return {"title": title, "points": points or [text]}

    if template == "analogy":
        analogy_label = _as_text(data.get("analogy_label") or data.get("comparison"), "Situation concrète")[:80]
        concept_label = _as_text(data.get("concept_label") or data.get("concept"), "Notion métier")[:80]
        return {
            "title": title,
            "analogy_label": analogy_label,
            "concept_label": concept_label,
            "concept": concept_label,
            "comparison": analogy_label,
            "text": text,
            "takeaway": _as_text(data.get("takeaway"), "Moins il y a de repères, plus le cerveau interprète.")[:180],
            "image_url": _as_text(data.get("image_url"), "")[:500],
            "image_prompt": _as_text(
                data.get("image_prompt"),
                (
                    f"Illustration PNG 16:9, no text, no humans, no faces, no silhouettes, "
                    f"no characters. Professional sober visual analogy: {analogy_label}. "
                    f"Clean editorial style, institutional training, readable composition."
                ),
            )[:600],
            "image_alt": _as_text(data.get("image_alt"), f"Illustration de l'analogie : {analogy_label}")[:180],
        }

    if template == "transition":
        return {
            "title": title,
            "from_topic": _as_text(data.get("from_topic"), "")[:45],
            "to_topic": _as_text(data.get("to_topic"), "")[:45],
        }

    if template == "chart":
        return {"title": title, "description": text, "chartData": data.get("chartData") or data.get("chart_data") or None}

    return {"title": title, "text": text}


def _fallback_title(block: dict) -> str:
    first_sentence = _SENTENCE_SPLIT_RE.split(_shorten(block.get("text", ""), 240))[0]
    words = re.findall(r"\w+", first_sentence, flags=re.UNICODE)
    return " ".join(words[:6]).strip().capitalize() or "Point clé"


def _fallback_slide(block: dict, reason: str = "fallback") -> dict:
    title = _fallback_title(block)
    text = _shorten(block.get("text", ""), 280)
    return {
        "source_block_id": block["source_block_id"],
        "template_type": "reflection",
        "event_type": "concept",
        "event_summary": title,
        "importance": 2,
        "data": {"title": title, "text": text},
        "slide_anchor_id": None,
        "beat_id": "",
        "fallback_reason": reason,
    }


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
    if not anchor and not slide_anchor_id and len(anchor_by_id) == 1:
        anchor = next(iter(anchor_by_id.values()))
        slide_anchor_id = str(anchor.get("anchor_id") or "")
    template = _canonical_template(
        raw.get("template_type")
        or raw.get("selected_existing_template")
        or raw.get("template")
        or (anchor or {}).get("template_type"),
        fallback="reflection",
    )

    event_type = raw.get("event_type") or "concept"
    if event_type not in EVENT_TYPES:
        event_type = "concept"

    fallback_title = _fallback_title(block)
    fallback_text = _shorten(block.get("text", ""), 260)
    raw_data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    anchor_fields = (anchor or {}).get("fields_hint") if isinstance((anchor or {}).get("fields_hint"), dict) else {}
    data = _normalize_slide_data(template, {**anchor_fields, **raw_data}, fallback_title, fallback_text)

    return {
        "source_block_id": block["source_block_id"],
        "template_type": template,
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
    prompt = _prompt_for_blocks(blocks, source_title, pace_profile, max_batch_slides)
    response = post_message(
        [{"role": "user", "content": prompt}],
        max_tokens=5000,
        model=model,
        timeout=240,
    )
    parsed = _parse_json_object(response)
    raw_slides = parsed.get("slides", [])
    if not isinstance(raw_slides, list):
        raise ValueError("Réponse LLM sans tableau slides")
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

    for slide in slides:
        gap = slide.get("ideal_template_gap") or {}
        if gap.get("needed") and gap.get("suggested_template_name") and gap.get("reason"):
            template_backlog.extend(_normalize_template_backlog([gap], max_items=1))

    return slides, {
        "template_backlog": _normalize_template_backlog(template_backlog),
        "raw_backlog_count": len(parsed.get("template_backlog") or []) if isinstance(parsed.get("template_backlog"), list) else 0,
        "curation_enabled": _slide_curation_enabled(),
    }


def _build_final_slide(slide: dict, block: dict, slide_number: int) -> dict:
    slide_kind = slide.get("slide_kind") or ("anchor" if slide.get("slide_anchor_id") else "generated")
    source_text = block["text"]
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
        "selection_method": "source_window",
    }
    quote = slide.get("source_quote") or ""
    quote_offsets = _quote_word_offsets(block.get("text", ""), quote)
    if quote_offsets:
        local_start, local_end = quote_offsets
        quote_start = block["word_start"] + local_start
        quote_end = block["word_start"] + local_end
        source_ref["word_start"] = quote_start
        source_ref["word_end"] = quote_end
        source_ref["word_count"] = max(1, quote_end - quote_start)
        source_ref["highlight_word_start"] = quote_start
        source_ref["highlight_word_end"] = quote_end
        source_ref["source_quote"] = quote
        source_ref["selection_method"] = "source_quote"
        source_text = quote

    return {
        "slide_id": f"script-s{slide_number + 1:03d}-b{block['source_block_id'] + 1:03d}",
        "trigger_time": None,
        "end_time": None,
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
        "template_type": "context",
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
    selected = sorted(
        indexed,
        key=lambda item: (item[1].get("importance", 3), -item[0]),
        reverse=True,
    )[:max_slides]
    selected_indices = {idx for idx, _ in selected}
    capped = [slide for idx, slide in indexed if idx in selected_indices]
    return capped, len(slides) - len(capped)


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

    max_slides = _safe_int(max_slides, DEFAULT_MAX_SLIDES, 5, 140)
    pace_config = _pace_profile(pace)
    batch_size = _safe_int(batch_size, DEFAULT_BATCH_SIZE, 1, 10)
    model = model or default_model()

    if source.get("beat_aligned"):
        source_blocks, total_words = _build_beat_source_blocks(source["segments"])
        effective_words_per_slide = 0
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
    if content_plan is None and not source.get("preview_only") and not source.get("beat_aligned"):
        content_plan = _load_content_plan(source)
    slide_anchors = _extract_slide_anchors_from_plan(content_plan)
    if source.get("beat_aligned"):
        slide_anchors = [
            anchor
            for block in source_blocks
            for anchor in (block.get("slide_anchors") or [])
        ]
    else:
        _assign_slide_anchors_to_source_blocks(source_blocks, slide_anchors)

    if not source_blocks:
        raise ValueError("Aucun bloc source exploitable")

    logger.info(
        "PIPELINE_SLIDES_START folder=%s content_job=%s platform=%s words=%s source_segments=%s "
        "context_windows=%s max_slides=%s pace=%s context_words=%s batch_size=%s model=%s anchors=%s",
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
        model,
        len(slide_anchors),
    )

    planned = []
    batches_debug = []
    template_backlog = []
    for start in range(0, len(source_blocks), batch_size):
        batch = source_blocks[start : start + batch_size]
        batch_started_at = time.time()
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
            batch_slides = []
            curation_debug = {"template_backlog": [], "curation_enabled": _slide_curation_enabled()}
            status = "fallback"
        template_backlog.extend(curation_debug.get("template_backlog") or [])
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
        planned.extend(batch_slides)
        batches_debug.append(
            {
                "start_block": batch[0]["source_block_id"],
                "end_block": batch[-1]["source_block_id"],
                "blocks": len(batch),
                "max_slides": max_batch_slides,
                "anchors": batch_anchor_count,
                "status": status,
                "curation": curation_debug,
            }
        )

    dropped_unanchored = 0
    if not planned and source_blocks and not slide_anchors:
        planned = [_fallback_slide(source_blocks[0], "empty_curation_deck")]

    planned, dropped_by_cap = _cap_planned_slides(planned, max_slides)
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
            "source_alignment": "draft_beat_aligned" if source.get("beat_aligned") else "text_windows",
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
            "max_slides": max_slides,
            "slides_generated": len(final_slides),
            "context_slides_inserted": context_slides_inserted,
            "slides_dropped_by_cap": dropped_by_cap,
            "slides_dropped_unanchored": dropped_unanchored,
            "slide_curation_enabled": _slide_curation_enabled(),
            "template_backlog_count": len(template_backlog),
            "llm_batches": len(batches_debug),
            "model": model,
        },
        "pipeline_debug": {
            "generation_mode": "script_anchor_guided_curation" if slide_anchors else "script_curation",
            "slide_anchors": slide_anchors,
            "template_backlog": template_backlog,
            "source_blocks": source_block_debug,
            "slide_plan": [
                {
                    "source_block_id": slide["source_block_id"],
                    "slide_anchor_id": slide.get("slide_anchor_id"),
                    "beat_id": slide.get("beat_id"),
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
