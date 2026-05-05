"""
Generate slide previews from the final generated course script.

This is the text-first replacement for the legacy audio -> Whisper -> events
prototype. It reads `content_generation_segments`, builds source blocks with a
hard density cap, and asks the LLM to turn each block into one template-ready
slide. No timing is estimated in V1.
"""

import json
import math
import re
import time
from typing import Iterable

from database.db import get_db_connection
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
    },
    "normal": {
        "label": "normal",
        "context_multiplier": 2.0,
        "max_slides_per_block": 2,
        "instruction": "Rythme normal: privilégie les thèmes et points pédagogiques forts.",
    },
    "synthesis": {
        "label": "synthesis",
        "context_multiplier": 3.0,
        "max_slides_per_block": 1,
        "instruction": "Rythme synthèse: ne garde que les thèmes majeurs et les pivots pédagogiques.",
    },
}

SUPPORTED_TEMPLATES = {
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

EVENT_TYPES = {
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
        VALUES (?, ?, ?, ?, 'script', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source["folder_id"],
            source["content_job_id"],
            source.get("formation_job_id"),
            source.get("platform_id"),
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
        }
        for block in blocks
    ]

    return f"""Tu conçois des slides pédagogiques pour Le Socrate.

Source: {source_title}

RÈGLES:
- Tu reçois des fenêtres de contexte. Elles servent à te donner le texte, pas à imposer le nombre de slides.
- Sélectionne les thèmes, points et idées pédagogiques qui méritent vraiment un visuel.
- Tu peux produire 0, 1 ou plusieurs slides par fenêtre selon la densité réelle des idées.
- Maximum {max_batch_slides} slides pour tout ce batch.
- Maximum {pace_profile["max_slides_per_block"]} slides pour une même fenêtre source.
- {pace_profile["instruction"]}
- Ne rajoute aucun timing. Ne crée pas de slide absente du texte.
- Le deck doit être lisible: titres courts, contenu très synthétique, aucun pavé.
- Si deux idées sont proches, regroupe-les. Si une fenêtre répète une idée déjà traitée, saute-la.
- Réponds uniquement en JSON valide.

TEMPLATES AUTORISÉS ET SCHÉMAS:
- reflection: data={{"title":"3-6 mots","text":"1-2 phrases"}}
- casestudy: data={{"title":"3-6 mots","cases":[{{"title":"court","desc":"1 phrase"}}]}} avec 2-3 cases
- facilitator: data={{"title":"3-6 mots","steps":[{{"title":"court","desc":"1 phrase","icon":"target|gear|flash|flag","color":"orange|purple|lime|blue"}}]}} avec 2-4 steps
- stats: data={{"title":"3-6 mots","description":"1 phrase","stats":[{{"number":"chiffre"}}],"columns":["phrase courte","phrase courte"]}}
- story: data={{"title":"3-6 mots","narrative":"1-2 phrases","moral":"1 phrase"}}
- recap: data={{"title":"3-6 mots","points":["point court","point court","point court"]}}
- analogy: data={{"title":"3-6 mots","concept":"2-4 mots","comparison":"2-4 mots","text":"1-2 phrases"}}
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
      "template_type": "reflection",
      "event_type": "concept",
      "event_summary": "Phrase courte décrivant l'idée source",
      "importance": 4,
      "data": {{"title": "...", "text": "..."}}
    }}
  ]
}}

FENÊTRES DE CONTEXTE:
{json.dumps(payload, ensure_ascii=False)}
"""


def _as_text(value, fallback: str = "") -> str:
    text = str(value or fallback).strip()
    return text or fallback


def _limit_list(value, max_len: int) -> list:
    if not isinstance(value, list):
        return []
    return value[:max_len]


def _normalize_slide_data(template: str, data: dict, fallback_title: str, fallback_text: str) -> dict:
    if not isinstance(data, dict):
        data = {}

    title = _as_text(data.get("title"), fallback_title)[:90]
    text = _as_text(data.get("text") or data.get("description"), fallback_text)[:420]

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
        return {
            "title": title,
            "concept": _as_text(data.get("concept"), "Concept")[:40],
            "comparison": _as_text(data.get("comparison"), "Repère")[:40],
            "text": text,
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
        "fallback_reason": reason,
    }


def _normalize_slide(raw: dict, block: dict) -> dict:
    if not isinstance(raw, dict):
        return _fallback_slide(block, "invalid_slide")

    template = raw.get("template_type") or raw.get("template") or "reflection"
    if template not in SUPPORTED_TEMPLATES:
        template = "reflection"

    event_type = raw.get("event_type") or "concept"
    if event_type not in EVENT_TYPES:
        event_type = "concept"

    fallback_title = _fallback_title(block)
    fallback_text = _shorten(block.get("text", ""), 260)
    data = _normalize_slide_data(template, raw.get("data") or {}, fallback_title, fallback_text)

    return {
        "source_block_id": block["source_block_id"],
        "template_type": template,
        "event_type": event_type,
        "event_summary": _as_text(raw.get("event_summary"), fallback_title)[:180],
        "importance": _safe_int(raw.get("importance"), 3, 1, 5),
        "data": data,
    }


def _generate_batch(blocks: list[dict], source_title: str, model: str, pace_profile: dict, max_batch_slides: int) -> list[dict]:
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
        if per_block_counts.get(source_block_id, 0) >= pace_profile["max_slides_per_block"]:
            continue
        slides.append(_normalize_slide(raw, block))
        per_block_counts[source_block_id] = per_block_counts.get(source_block_id, 0) + 1
        if len(slides) >= max_batch_slides:
            break

    if not slides:
        return [_fallback_slide(blocks[0], "empty_theme_batch")]
    return slides


def _build_final_slide(slide: dict, block: dict, slide_number: int) -> dict:
    return {
        "slide_id": f"script-s{slide_number + 1:03d}-b{block['source_block_id'] + 1:03d}",
        "trigger_time": None,
        "end_time": None,
        "template_type": slide["template_type"],
        "data": slide["data"],
        "event_type": slide["event_type"],
        "event_summary": slide["event_summary"],
        "source_text": block["text"],
        "source_ref": {
            "source_block_id": block["source_block_id"],
            "word_start": block["word_start"],
            "word_end": block["word_end"],
            "word_count": block["word_count"],
            "sub_part_index": block.get("sub_part_index"),
            "sub_part_name": block.get("sub_part_name"),
            "segments": block.get("source_refs", []),
        },
        "importance": slide.get("importance", 3),
        **({"fallback_reason": slide["fallback_reason"]} if slide.get("fallback_reason") else {}),
    }


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
    started_at = time.time()
    folder_id = _safe_int(folder_id, 0, 1, 10**9)
    if folder_id <= 0:
        raise ValueError("folder_id est requis")

    max_slides = _safe_int(max_slides, DEFAULT_MAX_SLIDES, 5, 140)
    pace_config = _pace_profile(pace)
    batch_size = _safe_int(batch_size, DEFAULT_BATCH_SIZE, 1, 10)
    model = model or default_model()

    source = _load_script_source(folder_id, job_id=job_id, platform_id=platform_id)
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

    if not source_blocks:
        raise ValueError("Aucun bloc source exploitable")

    logger.info(
        "PIPELINE_SLIDES_START folder=%s content_job=%s platform=%s words=%s source_segments=%s "
        "context_windows=%s max_slides=%s pace=%s context_words=%s batch_size=%s model=%s",
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
    )

    planned = []
    batches_debug = []
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
        logger.info(
            "PIPELINE_SLIDES_BATCH_START folder=%s content_job=%s batch=%s-%s blocks=%s max_batch_slides=%s",
            folder_id,
            source.get("content_job_id"),
            start,
            start + len(batch) - 1,
            len(batch),
            max_batch_slides,
        )
        try:
            batch_slides = _generate_batch(batch, source["program_title"], model, pace_config, max_batch_slides)
            status = "llm"
        except Exception as exc:
            logger.exception("PIPELINE_SLIDES_BATCH_ERROR folder=%s batch=%s-%s error=%s", folder_id, start, start + len(batch) - 1, exc)
            batch_slides = [_fallback_slide(block, "batch_error") for block in batch]
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
        planned.extend(batch_slides)
        batches_debug.append(
            {
                "start_block": batch[0]["source_block_id"],
                "end_block": batch[-1]["source_block_id"],
                "blocks": len(batch),
                "max_slides": max_batch_slides,
                "status": status,
            }
        )

    planned, dropped_by_cap = _cap_planned_slides(planned, max_slides)

    block_by_id = {block["source_block_id"]: block for block in source_blocks}
    final_slides = []
    for slide_idx, slide in enumerate(planned):
        block = block_by_id.get(slide["source_block_id"])
        if block:
            final_slides.append(_build_final_slide(slide, block, slide_idx))

    timeline = [
        {
            "slide_index": idx,
            "slide_id": slide["slide_id"],
            "type": slide["event_type"],
            "summary": slide["event_summary"],
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
            "excerpt": _shorten(block.get("text", ""), 360),
        }
        for block in source_blocks
    ]

    result = {
        "slides": final_slides,
        "timeline": timeline,
        "stats": {
            "generation_mode": "script",
            "folder_id": source["folder_id"],
            "folder_name": source["folder_name"],
            "job_id": job_id,
            "source": "content_generation_segments",
            "source_words": total_words,
            "source_segments": len(source["segments"]),
            "source_blocks": len(source_blocks),
            "source_windows": len(source_blocks),
            "pace": pace_config["label"],
            "context_words": effective_words_per_slide,
            "max_slides": max_slides,
            "slides_generated": len(final_slides),
            "slides_dropped_by_cap": dropped_by_cap,
            "llm_batches": len(batches_debug),
            "model": model,
        },
        "pipeline_debug": {
            "generation_mode": "script",
            "source_blocks": source_block_debug,
            "slide_plan": [
                {
                    "source_block_id": slide["source_block_id"],
                    "template": slide["template_type"],
                    "event_type": slide["event_type"],
                    "title_hint": slide["data"].get("title", ""),
                    "content_hint": slide["event_summary"],
                }
                for slide in planned
            ],
            "batches": batches_debug,
        },
    }
    deck_id = _persist_script_slide_deck(
        source,
        result,
        pace=pace_config["label"],
        max_slides=max_slides,
        model=model,
    )
    result["stats"]["deck_id"] = deck_id
    result["pipeline_debug"]["deck_id"] = deck_id
    logger.info(
        "PIPELINE_SLIDES_DONE folder=%s content_job=%s deck_id=%s slides=%s dropped_by_cap=%s duration_ms=%s",
        folder_id,
        source.get("content_job_id"),
        deck_id,
        len(final_slides),
        dropped_by_cap,
        int((time.time() - started_at) * 1000),
    )
    return result
