"""
Service pipeline formation automatisé.

Flux complet :
  1. Recherche RNCP sur France Compétences à partir du nom TP
  2. Téléchargement + extraction texte du REAC PDF
  3. Génération programme global (DeepSeek) → validation humaine
  4. Découpage programme par journée (DeepSeek) → validation humaine
  5. Lancement génération TTS pour chaque journée (pipeline existant)
"""

import io
import os
import re
import math
import json
import time
from html import unescape
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable
from urllib.parse import quote, urljoin

import requests as _http

from repositories.pipeline_repository import (
    attach_course_folder_to_job,
    course_folder_exists_for_job,
    create_pipeline_job,
    create_course_folder_for_job,
    find_orphan_course_folder,
    get_pipeline_job,
    list_expected_course_folder_matches,
    list_pipeline_jobs,
    update_pipeline_job,
)
from utils.deepseek_client import (
    DeepSeekAPIError,
    DeepSeekRateLimitError,
    default_model,
    post_message as _post_deepseek_message,
)
from utils.logger import get_logger
from services.dynamic_day_schedule_service import (
    SCHEDULE_SCHEMA_VERSION,
    build_day_audio_manifest,
    compile_day_schedule,
)
from services.pipeline_queue.contracts import LeaseLostError

logger = get_logger(__name__)

# Modèle utilisé pour la génération du pipeline formation.
# Configure `FORMATION_LLM_MODEL=deepseek-v4-flash` ou `deepseek-v4-pro`.
DEEPSEEK_MODEL = default_model()
HOURS_PER_DAY = 7


class DailySplitGenerationError(RuntimeError):
    """Le modèle n'a pas produit de programme journalier valide après les retries locaux."""


COURSE_AUDIO_SLOTS = [
    {"index": 0, "label": "Cours 1", "start": "9h00", "end": "9h45", "duration_min": 45, "filename": "cours_9h00_9h45.mp3"},
    {"index": 1, "label": "Cours 2", "start": "10h05", "end": "10h50", "duration_min": 45, "filename": "cours_10h05_10h50.mp3"},
    {"index": 2, "label": "Cours 3", "start": "11h05", "end": "12h00", "duration_min": 55, "filename": "cours_11h05_12h00.mp3"},
    {"index": 3, "label": "Cours 4", "start": "12h20", "end": "13h05", "duration_min": 45, "filename": "cours_12h20_13h05.mp3"},
    {"index": 4, "label": "Cours 5", "start": "14h45", "end": "15h45", "duration_min": 60, "filename": "cours_14h45_15h45.mp3"},
    {"index": 5, "label": "Cours 6", "start": "16h00", "end": "17h00", "duration_min": 60, "filename": "cours_16h00_17h00.mp3"},
    {"index": 6, "label": "Cours 7", "start": "17h25", "end": "18h15", "duration_min": 50, "filename": "cours_17h25_18h15.mp3"},
]


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


def _strip_internal_schedule_from_label(value: str | None) -> str:
    original = str(value or "").strip()
    if not original:
        return ""
    text = _INTERNAL_SCHEDULE_TIME_RANGE_RE.sub("", original)
    text = _INTERNAL_SCHEDULE_SINGLE_TIME_RE.sub("", text)
    text = re.sub(r"\b(?:45|50|55|60)\s*minutes\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*[-–—]\s*[-–—]\s*", " — ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = re.sub(r"\s*[-–—]\s*$", "", text).strip()
    text = re.sub(r"^\s*[-–—]\s*", "", text).strip()
    text = re.sub(r"^cours\s+\d+\s*[-–—:]\s*", "", text, flags=re.IGNORECASE).strip()
    return text or original


def _json_object(value, *, field_name: str) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} contient un JSON invalide") from exc
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"{field_name} doit être un objet JSON")


def _json_list(value, *, field_name: str) -> list:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} contient un JSON invalide") from exc
        if isinstance(parsed, list):
            return parsed
    raise ValueError(f"{field_name} doit être une liste JSON")


def _v2_schedule_days(job: dict) -> list[dict] | None:
    """Return validated immutable V2 days, or ``None`` for a legacy job."""

    try:
        schema_version = int(job.get("schedule_schema_version") or 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("schedule_schema_version invalide") from exc
    if schema_version != SCHEDULE_SCHEMA_VERSION:
        return None

    snapshot = _json_object(
        job.get("schedule_snapshot_json") or job.get("schedule_snapshot"),
        field_name="schedule_snapshot_json",
    )
    snapshot_version = int(
        snapshot.get("schema_version") or schema_version
    )
    if snapshot_version != SCHEDULE_SCHEMA_VERSION:
        raise ValueError(
            "Le snapshot ne correspond pas à schedule_schema_version=2"
        )

    raw_days = snapshot.get("days")
    if not isinstance(raw_days, list) or not raw_days:
        raise ValueError("Le snapshot V2 doit contenir au moins une journée")

    numbered_days = []
    for fallback_index, raw_day in enumerate(raw_days, start=1):
        if not isinstance(raw_day, dict):
            raise ValueError(f"Journée V2 {fallback_index} invalide")
        try:
            day_index = int(
                raw_day.get("day_index")
                or raw_day.get("day_number")
                or fallback_index
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Numéro de journée V2 invalide à la position {fallback_index}"
            ) from exc
        raw_blocks = (
            raw_day.get("blocks")
            or raw_day.get("schedule_blocks")
            or raw_day.get("blocks_snapshot_json")
            or []
        )
        canonical = compile_day_schedule(
            _json_list(
                raw_blocks,
                field_name=f"schedule_snapshot_json.days[{fallback_index - 1}].blocks",
            )
        )
        numbered_days.append(
            {
                **raw_day,
                **canonical,
                "day_index": day_index,
                "day_number": day_index,
            }
        )

    numbered_days.sort(key=lambda day: day["day_index"])
    actual_indexes = [day["day_index"] for day in numbered_days]
    expected_indexes = list(range(1, len(numbered_days) + 1))
    if actual_indexes != expected_indexes:
        raise ValueError(
            "Les journées du snapshot V2 doivent être numérotées "
            f"sans interruption : attendu {expected_indexes}, reçu {actual_indexes}"
        )
    return numbered_days


def _schedule_day(
    schedule_days: list[dict] | None,
    day_number: int,
) -> dict | None:
    if not schedule_days:
        return None
    return next(
        (
            day
            for day in schedule_days
            if int(day.get("day_index") or day.get("day_number") or 0)
            == int(day_number)
        ),
        None,
    )


def _minute_label(value: int) -> str:
    hours, minutes = divmod(int(value), 60)
    return f"{hours:02d}:{minutes:02d}"


def _v2_course_slots(schedule_day: dict) -> list[dict]:
    canonical = compile_day_schedule(schedule_day)
    manifest_by_key = {
        item["block_key"]: item
        for item in build_day_audio_manifest(canonical)
    }
    slots = []
    for block in canonical["blocks"]:
        if block["block_type"] != "course":
            continue
        manifest_item = manifest_by_key[block["block_key"]]
        slots.append(
            {
                "index": len(slots),
                "course_index": int(block["course_index"]),
                "label": f"Cours {block['course_index']}",
                "block_key": block["block_key"],
                "start": _minute_label(block["start_minute"]),
                "end": _minute_label(block["end_minute"]),
                "start_minute": block["start_minute"],
                "end_minute": block["end_minute"],
                "duration_min": block["duration_minutes"],
                "target_words": block["target_words"],
                "filename": manifest_item["filename"],
            }
        )
    return slots


def _course_audio_slots_prompt(
    schedule_days: list[dict] | None = None,
) -> str:
    if schedule_days is not None:
        day_lines = []
        for day in schedule_days:
            slots = _v2_course_slots(day)
            day_number = int(
                day.get("day_index") or day.get("day_number") or 0
            )
            day_lines.append(
                f"Journée {day_number} : {len(slots)} cours vocaux, "
                f"{sum(slot['duration_min'] for slot in slots)} minutes "
                "de cours au total."
            )
            day_lines.extend(
                (
                    f"- Cours {slot['course_index']}/{len(slots)} · "
                    f"{slot['duration_min']} min · cible "
                    f"{slot['target_words']} mots · identifiant "
                    f"{slot['block_key']} · fichier {slot['filename']}."
                )
                for slot in slots
            )
        return "\n".join(day_lines)

    return "\n".join(
        f"- {slot['label']} · données internes: {slot['start']}-{slot['end']}, "
        f"{slot['duration_min']} min, fichier {slot['filename']}. "
        "Le nom pédagogique ne doit jamais reprendre ces données."
        for slot in COURSE_AUDIO_SLOTS
    )


def _normalize_v2_day_audio_slots(
    day_data: dict,
    schedule_day: dict,
) -> dict:
    """Overlay generated pedagogy on the exact immutable V2 course slots."""

    canonical_day = compile_day_schedule(schedule_day)
    slots = _v2_course_slots(canonical_day)
    raw_sub_parts = list(day_data.get("sub_parts") or [])
    normalized = []
    for idx, slot in enumerate(slots):
        raw = raw_sub_parts[idx] if idx < len(raw_sub_parts) else {}
        src = raw if isinstance(raw, dict) else {}
        name = (src.get("name") or "").strip()
        if not name and isinstance(raw, str):
            name = raw.strip()
        name = _strip_internal_schedule_from_label(name)
        if not name:
            name = f"{slot['label']} — Sujet à préciser"
        elif not name.lower().startswith("cours"):
            name = f"{slot['label']} — {name}"
        module_content = (src.get("module_content") or "").strip()
        if not module_content:
            module_content = (
                "Développer le contenu prévu pour ce chapitre en respectant "
                "son budget de mots interne, sans mentionner le planning."
            )
        normalized.append(
            {
                **src,
                "index": idx,
                "course_index": slot["course_index"],
                "course_count": len(slots),
                "is_last_course": idx == len(slots) - 1,
                "audio_slot": slot["label"],
                "block_key": slot["block_key"],
                "start_time": slot["start"],
                "end_time": slot["end"],
                "start_minute": slot["start_minute"],
                "end_minute": slot["end_minute"],
                "duration_min": slot["duration_min"],
                "duration_minutes": slot["duration_min"],
                "target_words": slot["target_words"],
                "filename": slot["filename"],
                "name": name,
                "module_content": module_content,
            }
        )

    day_data["sub_parts"] = normalized
    day_data["audio_slots"] = slots
    day_data["audio_manifest"] = build_day_audio_manifest(canonical_day)
    day_data["audio_file_count"] = canonical_day["audio_file_count"]
    day_data["schedule_blocks"] = canonical_day["blocks"]
    day_data["schedule_schema_version"] = SCHEDULE_SCHEMA_VERSION
    day_data["schedule_hash"] = canonical_day["schedule_hash"]
    day_data["day_index"] = int(
        schedule_day.get("day_index")
        or schedule_day.get("day_number")
        or day_data.get("day_number")
        or 0
    )
    day_data["hours"] = canonical_day["total_course_minutes"] / 60
    day_data["course_minutes"] = canonical_day["total_course_minutes"]
    day_data["amplitude_minutes"] = canonical_day["amplitude_minutes"]
    return day_data


def _normalize_day_audio_slots(
    day_data: dict,
    schedule_day: dict | None = None,
) -> dict:
    """Normalize one day, dynamically for V2 and identically to legacy V1."""

    if (
        schedule_day is None
        and str(day_data.get("schedule_schema_version") or "1")
        == str(SCHEDULE_SCHEMA_VERSION)
    ):
        embedded_blocks = day_data.get("schedule_blocks")
        if embedded_blocks:
            schedule_day = {
                "day_index": (
                    day_data.get("day_index") or day_data.get("day_number")
                ),
                "blocks": embedded_blocks,
            }
    if schedule_day is not None:
        return _normalize_v2_day_audio_slots(day_data, schedule_day)

    sub_parts = list(day_data.get("sub_parts") or [])
    normalized = []
    for idx, slot in enumerate(COURSE_AUDIO_SLOTS):
        raw = sub_parts[idx] if idx < len(sub_parts) else {}
        src = raw if isinstance(raw, dict) else {}
        name = (src.get("name") or "").strip()
        if not name and isinstance(raw, str):
            name = raw.strip()
        name = _strip_internal_schedule_from_label(name)
        if not name:
            name = f"{slot['label']} — Sujet à préciser"
        elif not name.lower().startswith("cours"):
            name = f"{slot['label']} — {name}"
        module_content = (src.get("module_content") or "").strip()
        if not module_content:
            module_content = (
                "Développer le contenu prévu pour cette partie de la journée "
                "en respectant le budget interne du cours, sans mentionner le planning."
            )
        normalized.append({
            **src,
            "index": idx,
            "audio_slot": slot["label"],
            "start_time": slot["start"],
            "end_time": slot["end"],
            "duration_min": slot["duration_min"],
            "filename": slot["filename"],
            "name": name,
            "module_content": module_content,
        })
    day_data["sub_parts"] = normalized
    day_data["audio_slots"] = COURSE_AUDIO_SLOTS
    day_data["hours"] = HOURS_PER_DAY
    return day_data


def _format_slot_generation_source(slot_data: dict) -> str:
    """Texte source injecté dans le prompt TTS pour un cours interne."""
    brief = slot_data.get("generation_brief") or {}
    course_count = int(slot_data.get("course_count") or 0)
    course_index = int(
        slot_data.get("course_index") or slot_data.get("index") or 0
    )
    if course_count:
        internal_label = (
            f"Cours {course_index} sur {course_count}"
            + (" (dernier cours de la journée)" if slot_data.get("is_last_course") else "")
        )
    else:
        internal_label = slot_data.get("audio_slot")
    lines = [
        f"COURS AUDIO INTERNE : {internal_label}.",
        "Les horaires, durées et fichiers associés à ce cours sont internes et ne doivent jamais être verbalisés.",
        f"OBJECTIF DU COURS : {_strip_internal_schedule_from_label(slot_data.get('name') or '')}",
        "",
        "CONTENU PRIORITAIRE :",
        slot_data.get("module_content", "") or "",
    ]
    if course_count:
        lines.extend(
            [
                "",
                (
                    "CONTRAINTE DE VOLUME INTERNE : "
                    f"{slot_data.get('duration_min')} minutes, cible "
                    f"{slot_data.get('target_words')} mots après la marge "
                    "technique de 30 secondes."
                ),
            ]
        )
    if isinstance(brief, dict) and brief:
        lines.extend(["", "BRIEF DE GÉNÉRATION DU COURS :"])
        for key, label in (
            ("must_cover", "À couvrir"),
            ("examples", "Exemples à intégrer"),
            ("finish", "Fin attendue"),
            ("avoid", "À éviter / ne pas répéter"),
            ("handoff", "Transition"),
        ):
            value = brief.get(key)
            if isinstance(value, list):
                value = "; ".join(str(item).strip() for item in value if str(item).strip())
            if value:
                lines.append(f"- {label} : {value}")
    return "\n".join(lines).strip()

# ─── Prompts DeepSeek ─────────────────────────────────────────────────────────

_GLOBAL_PROGRAM_PROMPT = """Tu es un expert en ingénierie pédagogique spécialisé dans les titres professionnels du Ministère du Travail.

Tu vas créer un programme de formation complet et structuré pour le titre professionnel suivant :

TITRE PROFESSIONNEL : {TP_NAME}
DURÉE TOTALE : {TOTAL_HOURS} heures ({NB_DAYS} journées de 7h)

RÉFÉRENTIEL REAC :
{REAC_TEXT}

CONSIGNE :
Crée un programme de formation détaillé et pédagogiquement structuré, orienté cours magistral TTS.
Le programme doit couvrir 100% des compétences du REAC.
La formation est composée exclusivement de cours expliqués oralement par le professeur.
Les savoir-faire du REAC doivent être enseignés, démontrés et commentés, jamais transformés en activité à réaliser par l'apprenant.

STRUCTURE ATTENDUE (suis ce format précisément) :

# PROGRAMME DE FORMATION — {TP_NAME}
Durée totale : {TOTAL_HOURS} heures | {NB_DAYS} journées

## OBJECTIF GLOBAL
[2-3 phrases décrivant ce que le stagiaire saura faire à l'issue de la formation]

## TABLE DES MATIÈRES
[Liste des blocs et modules avec durées en heures]

## BLOC 1 : [Nom du bloc — reprend le premier bloc de compétences du REAC]
Durée : Xh | Compétences REAC couvertes : CP1, CP2...

### MODULE 1.1 : [Nom précis du module] (Xh)
**Compétences visées :**
- [Compétence 1]
- [Compétence 2]

**Contenu théorique :**
1. [Section 1 — titre précis]
   - [Sous-thème A]
   - [Sous-thème B]
2. [Section 2 — titre précis]
   - [Sous-thème A]
   - [Sous-thème B]
[... autant de sections que nécessaire]

**Exemples professionnels commentés à intégrer au cours :**
- [Situation fictive racontée puis expliquée par le professeur]
- [Autre exemple professionnel analysé oralement]

[Répéter pour chaque module et chaque bloc]

## MODULES TRANSVERSAUX
[Communication professionnelle, outils numériques, etc.]

## REPÈRES SUR LA CERTIFICATION [hors TTS]
[Présentation informative des attendus et du dossier professionnel]

RÈGLES :
- Chaque module doit avoir une durée réaliste (entre 5h et 25h maximum)
- La somme des durées hors [hors TTS] doit être égale à {TOTAL_HOURS}h
- Chaque sous-thème doit être assez précis pour générer 15 minutes de cours oral
- Évite les répétitions entre modules
- Intègre les savoir-faire et savoirs du REAC dans les sous-thèmes
- 100% du volume pédagogique est du cours magistral audio : aucune séance d'exercice, cas pratique, étude de cas, atelier, mise en situation, simulation, jeu de rôle, QCM ou quiz
- Un exemple professionnel est uniquement raconté et commenté par le professeur à l'intérieur d'un cours ; il ne devient jamais un module, une séance ou une consigne apprenant"""

_DAILY_SPLIT_PROMPT = """Tu es un expert en ingénierie pédagogique.

Tu vas découper ce programme de formation en fiches journée pour les jours {DAY_START} à {DAY_END} (sur {NB_DAYS} journées au total).

TITRE PROFESSIONNEL : {TP_NAME}
JOURNÉES À GÉNÉRER : jours {DAY_START} à {DAY_END}

PROGRAMME GLOBAL :
{GLOBAL_PROGRAM}

CONSIGNE :
Génère uniquement les journées {DAY_START} à {DAY_END}, en répartissant le programme de façon cohérente.

RÈGLES :
- Chaque journée = exactement 7 heures de contenu
- Chaque journée a EXACTEMENT 7 cours dans "sub_parts", alignés sur la playlist audio interne ci-dessous.
- Chaque entrée de "sub_parts" est exclusivement un cours magistral expliqué par le professeur.
- Ne crée jamais de séance d'exercice, cas pratique, étude de cas, atelier, mise en situation, simulation, jeu de rôle, QCM ou quiz.
- Les exemples métier sont racontés et commentés par le professeur à l'intérieur du cours ; l'apprenant n'a aucune activité à réaliser.
- Les durées pédagogiques du programme global doivent être redistribuées sur ces cours internes.
- Un module peut occuper plusieurs cours, ou plusieurs petits modules peuvent partager un cours si c'est pédagogiquement cohérent.
- Ne coupe jamais une idée au hasard : chaque cours doit avoir une fin propre, avec chute, synthèse ou transition naturelle.
- Jour 1 : pas de rappel. Autres jours : bref rappel de la séance précédente.
- "day_recap" : commence par "Lors de la dernière séance, nous avons vu…" (sauf jour 1)
- "day_transition" : commence par "À la prochaine séance, nous aborderons…" (jamais "demain" ni "la semaine prochaine")
- "module_content" : 5-8 phrases détaillées : compétences visées, notions clés, exemples concrets, points de vigilance, progression interne du cours. Ce contenu sera la base directe de la génération TTS.
- "generation_brief" : objet opérationnel qui servira au prompt TTS du cours. Il doit dire quoi couvrir, quels exemples intégrer, comment finir, quoi éviter pour ne pas répéter les autres cours.
- Les horaires, durées et fichiers sont strictement internes. Ils peuvent rester dans les champs techniques start_time/end_time/duration_min/filename, mais ne doivent jamais apparaître dans "name", "module_content" ou "generation_brief".
- "name" doit contenir seulement "Cours N — thème pédagogique précis", sans heure, sans durée, sans mot "créneau" et sans planning.

COURS AUDIO INTERNES À RESPECTER STRICTEMENT :
{COURSE_AUDIO_SLOTS}

FORMAT DE SORTIE : JSON valide uniquement, sans texte avant ni après.

{{
  "days": [
    {{
      "day_number": {DAY_START},
      "title": "Titre descriptif de la journée",
      "hours": 7,
      "modules_covered": ["MODULE 1.1 : Nom"],
      "sub_parts": [
        {{
          "index": 0,
          "audio_slot": "Cours 1",
          "start_time": "9h00",
          "end_time": "9h45",
          "duration_min": 45,
          "filename": "cours_9h00_9h45.mp3",
          "name": "Cours 1 — Nom précis du thème",
          "module_content": "Contenu condensé et structuré de ce cours, sans mentionner l'horaire ni la durée.",
          "generation_brief": {{
            "must_cover": ["notion prioritaire 1", "notion prioritaire 2"],
            "examples": ["exemple métier à développer"],
            "finish": "Type de chute ou synthèse attendue à la fin du cours",
            "avoid": ["notion réservée à un autre cours", "redite à éviter"],
            "handoff": "Lien naturel avec le Q&A, la pause ou le cours suivant"
          }}
        }}
      ],
      "day_recap": "Rappel de la veille (vide pour le jour 1)",
      "day_transition": "Annonce de la prochaine journée"
    }}
  ]
}}"""


_DAILY_SPLIT_PROMPT_V2 = """Tu es un expert en ingénierie pédagogique.

Tu vas découper ce programme de formation en fiches journée pour les jours {DAY_START} à {DAY_END} (sur {NB_DAYS} journées au total).

TITRE PROFESSIONNEL : {TP_NAME}
JOURNÉES À GÉNÉRER : jours {DAY_START} à {DAY_END}

PROGRAMME GLOBAL :
{GLOBAL_PROGRAM}

PLANNING PÉDAGOGIQUE IMMUABLE :
{COURSE_AUDIO_SLOTS}

CONSIGNE :
Génère uniquement les journées {DAY_START} à {DAY_END}, en répartissant le programme de façon cohérente.

RÈGLES :
- Pour chaque journée, crée exactement le nombre de cours vocaux indiqué dans le planning ci-dessus.
- Respecte la durée et le budget de mots propres à chaque cours. Ne fusionne, ne supprime et n'ajoute aucun cours.
- Un cours correspond à un chapitre pédagogique autonome.
- Chaque chapitre est exclusivement un cours magistral expliqué par le professeur.
- Ne crée jamais de séance d'exercice, cas pratique, étude de cas, atelier, mise en situation, simulation, jeu de rôle, QCM ou quiz.
- Les exemples métier sont racontés et commentés par le professeur à l'intérieur du cours ; l'apprenant n'a aucune activité à réaliser.
- Un module peut occuper plusieurs cours, ou plusieurs petits modules peuvent partager un cours si c'est pédagogiquement cohérent.
- Ne coupe jamais une idée au hasard : chaque cours doit avoir une fin propre, avec chute, synthèse ou transition naturelle.
- Le dernier cours de chaque journée doit conclure la journée. Lui seul annonce la prochaine séance, sauf lors de la dernière journée de la formation.
- Jour 1 : pas de rappel. Autres jours : bref rappel de la séance précédente.
- "day_recap" : commence par "Lors de la dernière séance, nous avons vu…" (sauf jour 1).
- "day_transition" : commence par "À la prochaine séance, nous aborderons…" (jamais "demain" ni "la semaine prochaine").
- "module_content" : 5-8 phrases détaillées : compétences visées, notions clés, exemples concrets, points de vigilance et progression du chapitre.
- "generation_brief" : précise quoi couvrir, quels exemples intégrer, comment finir et quelles redites éviter.
- Les horaires, durées, budgets, identifiants et fichiers sont strictement internes : ne les mentionne jamais dans le texte pédagogique.
- "name" doit contenir seulement "Cours N — thème pédagogique précis", sans heure, durée, budget, mot "créneau" ou planning.

FORMAT DE SORTIE : JSON valide uniquement, sans texte avant ni après.

{{
  "days": [
    {{
      "day_number": {DAY_START},
      "title": "Titre descriptif de la journée",
      "modules_covered": ["MODULE 1.1 : Nom"],
      "sub_parts": [
        {{
          "course_index": 1,
          "name": "Cours 1 — Nom précis du thème",
          "module_content": "Contenu condensé et structuré de ce chapitre.",
          "generation_brief": {{
            "must_cover": ["notion prioritaire 1", "notion prioritaire 2"],
            "examples": ["exemple métier à développer"],
            "finish": "Type de chute ou synthèse attendue",
            "avoid": ["notion réservée à un autre cours", "redite à éviter"],
            "handoff": "Lien naturel avec le Q&R suivant"
          }}
        }}
      ],
      "day_recap": "Rappel de la séance précédente (vide pour le jour 1)",
      "day_transition": "Annonce de la prochaine séance"
    }}
  ]
}}"""


_LEARNER_ACTIVITY_PATTERNS = (
    (
        "exercice",
        re.compile(
            r"\bexercices?\s+(?:pratiques?|guid[ée]s?|"
            r"d['’]application|d['’]entra[iî]nement|"
            r"[àa]\s+r[ée]aliser|en\s+groupe|individuels?|interactifs?)\b|"
            r"(?m:^\s*(?:cours|module|s[ée]ance|journ[ée]e)\b"
            r"[^\n]{0,120}\bexercices?\b)",
            re.IGNORECASE,
        ),
    ),
    ("cas pratique", re.compile(r"\bcas\s+pratiques?\b", re.IGNORECASE)),
    ("étude de cas", re.compile(r"\b[ée]tudes?\s+de\s+cas\b", re.IGNORECASE)),
    ("travaux pratiques", re.compile(r"\btravaux?\s+pratiques?\b", re.IGNORECASE)),
    ("mise en situation", re.compile(r"\bmises?\s+en\s+situation\b", re.IGNORECASE)),
    ("jeu de rôle", re.compile(r"\bjeux?\s+de\s+r[oô]les?\b", re.IGNORECASE)),
    ("QCM", re.compile(r"\bqcm\b", re.IGNORECASE)),
    ("quiz", re.compile(r"\bquiz\b", re.IGNORECASE)),
    (
        "atelier pédagogique",
        re.compile(
            r"\bateliers?\s+(?:pratiques?|p[ée]dagogiques?|"
            r"d['’]application|d['’]entra[iî]nement|participatifs?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "simulation pédagogique",
        re.compile(
            r"\bsimulations?\s+(?:pratiques?|p[ée]dagogiques?|"
            r"d['’](?:entretien|examen|situation))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "activité pratique",
        re.compile(
            r"\bactivit[ée]s?\s+(?:pratiques?|p[ée]dagogiques?|"
            r"d['’]application)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "séance pratique",
        re.compile(
            r"\bs[ée]ances?\s+(?:pratiques?|d['’]exercices?|"
            r"d['’]application|d['’]entra[iî]nement)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "entraînement",
        re.compile(
            r"\bentra[iî]nements?\s+(?:pratiques?|[àa]\s+l['’]examen|"
            r"[àa]\s+la\s+certification|guid[ée]s?)\b|"
            r"\bs[ée]ances?\s+d['’]entra[iî]nement\b",
            re.IGNORECASE,
        ),
    ),
)

_LEGITIMATE_EXERCISE_CONTEXT_RE = re.compile(
    r"\b(?:conditions?|modalit[ée]s?|cadres?|contextes?)\s+"
    r"d['’]exercice\b|"
    r"\bexercice\s+(?:du|de\s+la)\s+(?:m[ée]tier|profession)\b|"
    r"\bexercice\s+de\s+l['’]activit[ée]\b|"
    r"\bdans\s+l['’]exercice\s+de\s+(?:ses|leurs)\s+fonctions\b",
    re.IGNORECASE,
)


def _learner_activity_violations(text: str) -> list[str]:
    """Détecte les activités apprenant, sans confondre l'exercice d'un métier."""
    scan_text = _LEGITIMATE_EXERCISE_CONTEXT_RE.sub("", str(text or ""))
    return [
        label
        for label, pattern in _LEARNER_ACTIVITY_PATTERNS
        if pattern.search(scan_text)
    ]


def _assert_lecture_only_program(text: str, *, context: str) -> None:
    violations = _learner_activity_violations(text)
    if violations:
        raise ValueError(
            f"{context} contient une activité apprenant interdite : "
            + ", ".join(violations)
        )


def _iter_daily_teaching_text(days: list[dict]):
    for day in days:
        for key in ("title", "day_recap", "day_transition"):
            yield day.get(key)
        for module in day.get("modules_covered") or []:
            yield module
        for part in day.get("sub_parts") or []:
            for key in ("name", "module_content"):
                yield part.get(key)
            brief = part.get("generation_brief") or {}
            # `avoid` peut légitimement nommer une activité à ne pas produire.
            for key in ("must_cover", "examples", "finish", "handoff"):
                value = brief.get(key)
                if isinstance(value, list):
                    yield from value
                else:
                    yield value


def _assert_lecture_only_days(days: list[dict]) -> None:
    combined = "\n".join(
        str(value).strip()
        for value in _iter_daily_teaching_text(days)
        if str(value or "").strip()
    )
    _assert_lecture_only_program(combined, context="Le programme journée")


def _build_global_program_prompt(
    job: dict,
    sources: str,
    schedule_days: list[dict] | None = None,
) -> str:
    """Build a dynamic V2 prompt while preserving the legacy prompt verbatim."""

    nb_days = len(schedule_days) if schedule_days else int(job["nb_days"])
    if not schedule_days:
        return (
            _GLOBAL_PROGRAM_PROMPT
            .replace("{TP_NAME}", job["tp_name"])
            .replace("{TOTAL_HOURS}", str(job["total_hours"]))
            .replace("{NB_DAYS}", str(nb_days))
            .replace("{REAC_TEXT}", sources)
        )

    total_course_minutes = sum(
        int(day["total_course_minutes"]) for day in schedule_days
    )
    schedule_summary = "\n".join(
        (
            f"- Journée {day['day_index']} : {day['course_count']} cours, "
            f"{day['total_course_minutes']} minutes de cours vocal, "
            f"amplitude {day['amplitude_minutes']} minutes."
        )
        for day in schedule_days
    )
    prompt = _GLOBAL_PROGRAM_PROMPT
    prompt = prompt.replace(
        "DURÉE TOTALE : {TOTAL_HOURS} heures ({NB_DAYS} journées de 7h)",
        (
            "VOLUME TOTAL DE COURS VOCAL : "
            f"{total_course_minutes} minutes sur {nb_days} journées\n"
            "ORGANISATION DES JOURNÉES :\n"
            f"{schedule_summary}"
        ),
    )
    prompt = prompt.replace(
        "Durée totale : {TOTAL_HOURS} heures | {NB_DAYS} journées",
        (
            f"Volume total de cours vocal : {total_course_minutes} minutes "
            f"| {nb_days} journées"
        ),
    )
    prompt = prompt.replace(
        "Durée : Xh | Compétences REAC couvertes : CP1, CP2...",
        "Volume de cours vocal : X minutes | Compétences REAC couvertes : CP1, CP2...",
    )
    prompt = prompt.replace(
        "### MODULE 1.1 : [Nom précis du module] (Xh)",
        "### MODULE 1.1 : [Nom précis du module] (X minutes de cours vocal)",
    )
    prompt = prompt.replace(
        "- La somme des durées hors [hors TTS] doit être égale à {TOTAL_HOURS}h",
        (
            "- La somme des volumes hors [hors TTS] doit être égale à "
            f"{total_course_minutes} minutes de cours vocal"
        ),
    )
    return (
        prompt
        .replace("{TP_NAME}", job["tp_name"])
        .replace("{NB_DAYS}", str(nb_days))
        .replace("{REAC_TEXT}", sources)
    )


# ─── France Compétences ───────────────────────────────────────────────────────

_FC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def get_rncp_certification(rncp_code: str) -> dict | None:
    """Return the exact France Compétences record for one RNCP code."""
    code = re.sub(r"^RNCP", "", str(rncp_code or "").strip(), flags=re.IGNORECASE)
    if not re.fullmatch(r"\d{4,6}", code):
        raise ValueError("Le code RNCP doit contenir entre 4 et 6 chiffres")

    source_url = f"https://www.francecompetences.fr/recherche/rncp/{code}/"
    response = _http.get(source_url, headers=_FC_HEADERS, timeout=20)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    page = response.text

    title_match = re.search(
        r'<h2[^>]*class="[^"]*title--page--generic[^"]*"[^>]*>(.*?)</h2>',
        page,
        flags=re.IGNORECASE | re.DOTALL,
    )
    code_match = re.search(
        r'tag--fcpt-certification__status[^>]*>\s*RNCP\s*(\d{4,6})\s*<',
        page,
        flags=re.IGNORECASE,
    )
    status_match = re.search(
        r'Etat\s*:</span>\s*<span[^>]*tag--fcpt-certification__status[^>]*>(.*?)</span>',
        page,
        flags=re.IGNORECASE | re.DOTALL,
    )
    reac_match = re.search(
        r'<a[^>]+href="([^"]+)"[^>]+title="Référentiel d[’\'’]activité[^\"]*"',
        page,
        flags=re.IGNORECASE,
    )

    if not title_match or not code_match or code_match.group(1) != code:
        return None

    clean_html = lambda value: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", unescape(value))).strip()
    title = clean_html(title_match.group(1))
    status = clean_html(status_match.group(1)) if status_match else ""
    reac_url = urljoin(source_url, unescape(reac_match.group(1))) if reac_match else None
    return {
        "rncp_code": code,
        "title": title,
        "status": status,
        "active": status.casefold() == "active",
        "reac_available": bool(reac_url),
        "reac_url": reac_url,
        "source_url": source_url,
    }


def search_rncp(query: str) -> list:
    """
    Recherche des titres RNCP via l'API officielle France Compétences.
    Retourne une liste de dicts : [{rncp_code, title}]
    """
    # API officielle — renvoie du JSON, pas de scraping HTML
    api_url = (
        "https://www.francecompetences.fr/wp-json/fc/v1/certifications"
        f"?search={quote(query)}&type=RNCP&active=true&per_page=8"
    )
    try:
        resp = _http.get(api_url, headers=_FC_HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        results = []
        items = data if isinstance(data, list) else data.get("items", data.get("results", []))
        for item in items[:8]:
            # Différents formats possibles selon la version de l'API
            code = (
                item.get("numero_fiche") or
                item.get("rncp_code") or
                item.get("code") or
                str(item.get("id", ""))
            )
            # Supprimer le préfixe "RNCP" si présent
            code = re.sub(r'^RNCP', '', str(code)).strip()
            title = (
                item.get("intitule") or
                item.get("titre") or
                item.get("title") or
                item.get("label") or
                f"RNCP {code}"
            )
            if code:
                results.append({"rncp_code": code, "title": title})

        if not results:
            logger.warning(f"⚠️ API France Compétences : aucun résultat pour '{query}' — fallback scraping HTML")
            return _search_rncp_html_fallback(query)

        return results

    except Exception as e:
        logger.warning(f"⚠️ API France Compétences échouée ({e}) — fallback scraping HTML")
        return _search_rncp_html_fallback(query)


def _search_rncp_html_fallback(query: str) -> list:
    """
    Fallback : scrape la page de résultats HTML de France Compétences.
    Utilisé si l'API JSON échoue ou retourne vide.
    """
    # Essayer plusieurs URL patterns
    urls_to_try = [
        f"https://www.francecompetences.fr/recherche-resultats/?types=certification&search={quote(query)}&pageType=certification&active=1",
        f"https://www.francecompetences.fr/recherche/?search={quote(query)}&type=RNCP",
    ]
    for url in urls_to_try:
        try:
            resp = _http.get(url, headers=_FC_HEADERS, timeout=20)
            resp.raise_for_status()
            codes = re.findall(r'/recherche/rncp/(\d+)/', resp.text)
            codes = list(dict.fromkeys(codes))[:8]
            if not codes:
                continue
            results = []
            for code in codes:
                pattern = rf'href="[^"]*rncp/{code}/[^"]*"[^>]*>([^<]+)</a>'
                match = re.search(pattern, resp.text)
                title = match.group(1).strip() if match else f"RNCP {code}"
                title = title.replace("&amp;", "&").replace("&#039;", "'").replace("&eacute;", "é")
                results.append({"rncp_code": code, "title": title})
            if results:
                return results
        except Exception as e:
            logger.warning(f"⚠️ Fallback HTML échoué pour {url} : {e}")
            continue
    return []


def get_reac_export_url(rncp_code: str) -> str:
    """
    Récupère l'URL d'export REAC PDF depuis la page d'une fiche RNCP.
    """
    page_url = f"https://www.francecompetences.fr/recherche/rncp/{rncp_code}/"
    try:
        resp = _http.get(page_url, headers=_FC_HEADERS, timeout=20)
        resp.raise_for_status()

        # L'URL d'export a la forme /wp-json/api/v1/activity/export/XXXXX/YYYYY
        match = re.search(r'/wp-json/api/v1/activity/export/(\d+)/(\d+)', resp.text)
        if not match:
            raise ValueError(f"URL export REAC introuvable pour RNCP {rncp_code}")

        return f"https://www.francecompetences.fr/wp-json/api/v1/activity/export/{match.group(1)}/{match.group(2)}"

    except Exception as e:
        logger.error(f"❌ Erreur récupération URL REAC pour RNCP {rncp_code} : {e}")
        raise


def download_reac_text(rncp_code: str) -> str:
    """
    Télécharge le REAC PDF et en extrait le texte brut.
    """
    import PyPDF2

    reac_url = get_reac_export_url(rncp_code)
    logger.info(f"📥 Téléchargement REAC depuis {reac_url}")

    resp = _http.get(reac_url, timeout=60)
    resp.raise_for_status()

    reader = PyPDF2.PdfReader(io.BytesIO(resp.content))
    pages_text = []
    for page in reader.pages:
        txt = page.extract_text()
        if txt:
            pages_text.append(txt)

    full_text = "\n".join(pages_text)
    logger.info(f"✅ REAC extrait : {len(full_text)} caractères ({len(reader.pages)} pages)")
    return full_text


def _cooperative_sleep(seconds: float) -> None:
    time.sleep(seconds)


def _reac_retry_delays(attempts: int) -> list[float]:
    raw = (os.getenv("FORMATION_REAC_RETRY_DELAYS_SEC") or "").strip()
    if raw:
        values = []
        for part in raw.split(","):
            try:
                values.append(max(0.0, float(part.strip())))
            except (TypeError, ValueError):
                continue
        if values:
            return values[: max(0, attempts - 1)]
    return [30.0, 90.0][: max(0, attempts - 1)]


def download_reac_text_with_retry(
    rncp_code: str,
    *,
    attempts: int = 3,
    delays_sec: list[float] | None = None,
    on_attempt=None,
) -> str:
    """Télécharge le REAC avec retries bornés et erreur finale explicite."""
    attempts = max(1, int(attempts or 1))
    delays = list(delays_sec) if delays_sec is not None else _reac_retry_delays(attempts)
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            if on_attempt:
                on_attempt(attempt=attempt, total=attempts, status="running", wait_seconds=0, error=None)
            text = download_reac_text(rncp_code)
            if not (text or "").strip():
                raise RuntimeError("REAC extrait vide")
            if on_attempt:
                on_attempt(attempt=attempt, total=attempts, status="success", wait_seconds=0, error=None)
            return text
        except Exception as e:
            last_error = e
            is_last = attempt >= attempts
            wait = 0.0 if is_last else (delays[attempt - 1] if attempt - 1 < len(delays) else delays[-1] if delays else 0.0)
            status = "failed" if is_last else "retrying"
            logger.warning(
                "REAC_DOWNLOAD_ATTEMPT rncp=%s attempt=%s/%s status=%s wait=%.1fs error=%s",
                rncp_code,
                attempt,
                attempts,
                status,
                wait,
                str(e)[:300],
            )
            if on_attempt:
                on_attempt(
                    attempt=attempt,
                    total=attempts,
                    status=status,
                    wait_seconds=wait,
                    error=str(e),
                )
            if is_last:
                break
            _cooperative_sleep(wait)

    raise RuntimeError(
        f"REAC indisponible après {attempts} tentatives pour RNCP {rncp_code}. "
        f"Dernière erreur : {str(last_error)[:300]}"
    ) from last_error


# ─── Référentiel de Certification (RC) ───────────────────────────────────────

def download_rc_text(rncp_code: str) -> str:
    """
    Télécharge le RC (Référentiel de Certification) PDF depuis France Compétences.
    Le RC est le document complémentaire au REAC : critères d'évaluation, modalités d'examen.
    """
    import PyPDF2
    page_url = f"https://www.francecompetences.fr/recherche/rncp/{rncp_code}/"
    try:
        resp = _http.get(page_url, headers=_FC_HEADERS, timeout=20)
        resp.raise_for_status()

        # Le RC a un pattern différent du REAC dans les URLs
        rc_patterns = [
            r'/wp-json/api/v1/evaluation/export/(\d+)/(\d+)',
            r'/wp-json/api/v1/certification/export/(\d+)/(\d+)',
            r'href="([^"]+/RC[^"]*\.pdf)"',
            r'href="([^"]+referentiel[^"]*certification[^"]*\.pdf)"',
        ]
        rc_url = None
        for pattern in rc_patterns:
            match = re.search(pattern, resp.text, re.IGNORECASE)
            if match:
                if match.lastindex == 2:
                    rc_url = f"https://www.francecompetences.fr/wp-json/api/v1/evaluation/export/{match.group(1)}/{match.group(2)}"
                else:
                    rc_url = match.group(1)
                    if not rc_url.startswith('http'):
                        rc_url = f"https://www.francecompetences.fr{rc_url}"
                break

        if not rc_url:
            logger.warning(f"⚠️ RC introuvable pour RNCP {rncp_code}")
            return ""

        logger.info(f"📥 Téléchargement RC depuis {rc_url}")
        rc_resp = _http.get(rc_url, timeout=60)
        rc_resp.raise_for_status()

        reader = PyPDF2.PdfReader(io.BytesIO(rc_resp.content))
        pages_text = [p.extract_text() for p in reader.pages if p.extract_text()]
        text = "\n".join(pages_text)
        logger.info(f"✅ RC extrait : {len(text)} caractères")
        return text

    except Exception as e:
        logger.warning(f"⚠️ RC non disponible pour RNCP {rncp_code} : {e}")
        return ""


# ─── Données ROME (France Travail) ───────────────────────────────────────────

def _get_france_travail_token() -> str:
    """Obtient un token OAuth2 France Travail (nécessite FRANCE_TRAVAIL_CLIENT_ID + SECRET)."""
    client_id = os.getenv("FRANCE_TRAVAIL_CLIENT_ID")
    client_secret = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET")
    if not client_id or not client_secret:
        return ""
    try:
        resp = _http.post(
            "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
            "?realm=%2Fpartenaire",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "api_rome-metiersv1",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("access_token", "")
    except Exception as e:
        logger.warning(f"⚠️ Token France Travail impossible : {e}")
        return ""


def _get_rome_codes_from_rncp_page(rncp_code: str) -> list:
    """Extrait les codes ROME associés à une fiche RNCP."""
    try:
        resp = _http.get(
            f"https://www.francecompetences.fr/recherche/rncp/{rncp_code}/",
            headers=_FC_HEADERS, timeout=20
        )
        resp.raise_for_status()
        # Codes ROME = lettre + 4 chiffres (ex: D1408, E1206)
        codes = re.findall(r'\b([A-Z]\d{4})\b', resp.text)
        # Filtrer les faux positifs (garder seulement les codes ROME valides A-Z + 4 chiffres)
        valid = [c for c in dict.fromkeys(codes) if c[0].isalpha()][:5]
        logger.info(f"📋 Codes ROME trouvés pour RNCP {rncp_code} : {valid}")
        return valid
    except Exception as e:
        logger.warning(f"⚠️ Codes ROME introuvables : {e}")
        return []


def fetch_rome_data(rncp_code: str) -> str:
    """
    Récupère les fiches ROME associées au titre RNCP.
    Utilise l'API France Travail si les credentials sont disponibles,
    sinon tente un scraping de la page candidat.
    """
    rome_codes = _get_rome_codes_from_rncp_page(rncp_code)
    if not rome_codes:
        return ""

    token = _get_france_travail_token()
    results = []

    for rome_code in rome_codes[:3]:  # Max 3 codes ROME
        text = ""

        # Tentative 1 : API officielle France Travail
        if token:
            try:
                resp = _http.get(
                    f"https://api.francetravail.io/partenaire/rome-metiers/v1/metiers/metier/{rome_code}",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    timeout=15,
                )
                if resp.ok:
                    data = resp.json()
                    parts = []
                    if data.get("libelle"):
                        parts.append(f"Métier : {data['libelle']}")
                    if data.get("definition"):
                        parts.append(f"Définition : {data['definition']}")
                    for cat in ["savoirs", "savoirsFaire", "savoirsEtre"]:
                        items = data.get(cat, [])
                        if items:
                            parts.append(f"{cat} : " + ", ".join(i.get("libelle", "") for i in items[:15]))
                    text = "\n".join(parts)
                    logger.info(f"✅ ROME {rome_code} récupéré via API")
            except Exception as e:
                logger.warning(f"⚠️ API ROME {rome_code} : {e}")

        # Tentative 2 : scraping page candidat France Travail
        if not text:
            try:
                resp = _http.get(
                    f"https://candidat.francetravail.fr/metierform/accueil?codeRome={rome_code}",
                    headers=_FC_HEADERS, timeout=15,
                )
                if resp.ok and len(resp.text) > 500:
                    # Extraire le texte brut (la page peut être partiellement rendue)
                    clean = re.sub(r'<[^>]+>', ' ', resp.text)
                    clean = re.sub(r'\s+', ' ', clean).strip()
                    text = clean[:3000]
                    logger.info(f"✅ ROME {rome_code} scraping page candidat")
            except Exception as e:
                logger.warning(f"⚠️ Scraping ROME {rome_code} : {e}")

        if text:
            results.append(f"=== FICHE ROME {rome_code} ===\n{text}")

    combined = "\n\n".join(results)
    logger.info(f"✅ Données ROME : {len(combined)} caractères pour {len(results)} code(s)")
    return combined


# ─── Appel DeepSeek ───────────────────────────────────────────────────────────

def _deepseek_post(messages, max_tokens=16000, model=None):
    """Un seul appel HTTP ; la file durable possède la politique de retry."""
    return _post_deepseek_message(
        messages,
        max_tokens=max_tokens,
        model=model or DEEPSEEK_MODEL,
        http_max_attempts=1,
    )


# ─── Génération programme global ──────────────────────────────────────────────

def generate_global_program(
    job_id: int,
    model: str = None,
    checkpoint: Callable[[], None] | None = None,
) -> None:
    """Génère le programme global dans le work-item durable courant."""
    try:
        if checkpoint:
            checkpoint()
        job = get_job(job_id)
        if not job:
            raise RuntimeError(f"Job {job_id} introuvable")

        update_job(job_id, status="global_generating")
        used_model = model or DEEPSEEK_MODEL
        logger.info(f"🔄 Job {job_id} : génération programme global (modèle: {used_model})...")

        schedule_days = _v2_schedule_days(job)
        nb_days = len(schedule_days) if schedule_days else job["nb_days"]

        # ── Couche 1 : prioriser la Knowledge Base enrichie si dispo ──
        # Si l'utilisateur a lancé l'enrichissement (status kb_ready), on
        # injecte la KB dense (~120-150k mots structurés) plutôt que le REAC
        # brut (15k). Réduit le ratio de dilution sur formations longues.
        from services.knowledge_base_service import build_kb_context
        kb_context = build_kb_context(job_id)

        if kb_context:
            sources = (
                f"=== SOURCE PRIMAIRE : Base de connaissances pédagogique enrichie ===\n"
                f"(Extraite du REAC officiel puis expansée : définitions, études de cas, "
                f"pièges, vocabulaire métier, contexte terrain pour chaque compétence)\n\n"
                f"{kb_context}\n\n"
                f"=== SOURCE SECONDAIRE : REAC brut (référence) ===\n"
                f"{job['reac_text'][:8000]}"
            )
            logger.info(f"📚 Job {job_id} : programme global généré depuis KB enrichie ({len(kb_context)} chars)")
        else:
            # Fallback REAC brut (anciens jobs ou KB non construite)
            sources = f"=== REAC (Référentiel Emploi Activités Compétences) ===\n{job['reac_text'][:15000]}"
            if job.get("rc_text"):
                sources += f"\n\n=== RC (Référentiel de Certification) ===\n{job['rc_text'][:8000]}"
            if job.get("rome_text"):
                sources += f"\n\n=== FICHES ROME (France Travail) ===\n{job['rome_text'][:5000]}"
            logger.info(f"📄 Job {job_id} : programme global généré depuis REAC brut (KB non disponible)")

        prompt = _build_global_program_prompt(
            job,
            sources,
            schedule_days=schedule_days,
        )

        if checkpoint:
            checkpoint()
        program = _deepseek_post(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=16000,
            model=used_model,
        )
        _assert_lecture_only_program(
            program,
            context="Le programme global",
        )
        if checkpoint:
            checkpoint()
        update_job(
            job_id,
            status="global_ready",
            global_program=program,
            global_program_generated_via="api",
        )
        logger.info(f"✅ Job {job_id} : programme global généré ({len(program)} chars)")

    except LeaseLostError:
        logger.warning("PIPELINE_GLOBAL_PROGRAM_LEASE_LOST job=%s", job_id)
        raise
    except Exception as e:
        logger.error(f"❌ Job {job_id} génération global échouée : {e}")
        update_job(job_id, status="error", error_message=str(e))
        raise


# ─── Découpage en journées ────────────────────────────────────────────────────

def _env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


# Le daily split était historiquement batché par 5 jours. C'est rapide, mais une
# seule réponse JSON longue et mal fermée bloque toute la pipeline. Par défaut on
# privilégie donc la robustesse : 1 jour par réponse, avec concurrence bornée.
BATCH_SIZE = _env_int("FORMATION_DAILY_BATCH_SIZE", 1, min_value=1, max_value=5)
DAILY_SPLIT_WORKERS = _env_int("FORMATION_DAILY_SPLIT_WORKERS", 3, min_value=1, max_value=6)
DAILY_SPLIT_MAX_TOKENS = _env_int("FORMATION_DAILY_SPLIT_MAX_TOKENS", 12000, min_value=4000, max_value=24000)


def _escape_control_chars_in_strings(text: str) -> str:
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
            result.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[ch])
        else:
            result.append(ch)
    return "".join(result)


def _balanced_json_slice(text: str) -> str:
    """Retourne le premier objet/array JSON complet, en ignorant les accolades en string."""
    text = str(text or "").strip()
    starts = [(idx, ch) for idx, ch in ((text.find("{"), "{"), (text.find("["), "[")) if idx >= 0]
    if not starts:
        raise ValueError("Aucun début JSON détectable")
    start, _ = min(starts, key=lambda item: item[0])

    stack = []
    in_string = False
    escaped = False
    for i, ch in enumerate(text[start:], start=start):
        if escaped:
            escaped = False
            continue
        if in_string:
            if ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in ("}", "]"):
            if stack and stack[-1] == ch:
                stack.pop()
                if not stack:
                    return text[start:i + 1]

    # JSON tronqué : on garde la zone JSON la plus probable pour json_repair.
    end = max(text.rfind("}"), text.rfind("]"))
    if end > start:
        return text[start:end + 1]
    return text[start:]


def _json_candidates(raw: str) -> list[str]:
    raw = str(raw or "").strip()
    candidates = []
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE):
        candidates.append(match.group(1).strip())
    candidates.append(raw)

    expanded = []
    for candidate in candidates:
        if not candidate:
            continue
        expanded.append(candidate)
        try:
            expanded.append(_balanced_json_slice(candidate))
        except ValueError:
            pass

    seen = set()
    unique = []
    for candidate in expanded:
        candidate = candidate.strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _loads_lenient_json(candidate: str):
    errors = []
    for text in (candidate, _escape_control_chars_in_strings(candidate)):
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            errors.append(str(e))

    try:
        from json_repair import repair_json
        repaired = repair_json(candidate)
        return json.loads(repaired)
    except Exception as e:
        errors.append(str(e))

    raise ValueError(errors[-1] if errors else "JSON invalide")


def _clean_json(raw: str):
    """Extrait et répare une réponse LLM JSON avec plusieurs stratégies."""
    errors = []
    for candidate in _json_candidates(raw):
        try:
            return _loads_lenient_json(candidate)
        except Exception as e:
            errors.append(str(e))
    raise ValueError(
        "JSON invalide même après réparation : "
        + (errors[-1] if errors else "aucun JSON détectable")
    )


def _coerce_day_number(value) -> int | None:
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value or ""))
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _ensure_list(value) -> list:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _normalize_daily_payload(
    data,
    day_start: int,
    day_end: int,
    tp_name: str,
    schedule_days: list[dict] | None = None,
) -> list[dict]:
    expected = list(range(day_start, day_end + 1))
    if isinstance(data, dict):
        raw_days = data.get("days")
        if raw_days is None and "day_number" in data:
            raw_days = [data]
    elif isinstance(data, list):
        raw_days = data
    else:
        raise ValueError("Le JSON daily doit être un objet {days:[...]} ou une liste")

    days = [dict(day) for day in _ensure_list(raw_days) if isinstance(day, dict)]
    if len(days) == len(expected):
        for idx, day in enumerate(days):
            if _coerce_day_number(day.get("day_number")) is None:
                day["day_number"] = expected[idx]

    by_number = {}
    for day in days:
        number = _coerce_day_number(day.get("day_number"))
        if number is not None:
            day["day_number"] = number
            by_number[number] = day

    selected = []
    missing = []
    for number in expected:
        day = by_number.get(number)
        if not day:
            missing.append(number)
            continue
        schedule_day = _schedule_day(schedule_days, number)
        if schedule_days and schedule_day is None:
            raise ValueError(
                f"Planning V2 introuvable pour la journée {number}"
            )
        selected.append(
            _complete_day_program_shape(
                day,
                number,
                tp_name,
                schedule_day=schedule_day,
            )
        )

    if missing:
        raise ValueError(f"Journée(s) manquante(s) dans le JSON : {missing}")
    return selected


def _complete_day_program_shape(
    day: dict,
    day_number: int,
    tp_name: str,
    schedule_day: dict | None = None,
) -> dict:
    day = dict(day or {})
    day["day_number"] = day_number
    if schedule_day is None:
        day["hours"] = HOURS_PER_DAY
    title = _strip_internal_schedule_from_label(day.get("title") or "")
    day["title"] = title or f"Journée {day_number} — Progression {tp_name}"
    modules = day.get("modules_covered")
    if not isinstance(modules, list):
        day["modules_covered"] = [str(modules).strip()] if modules else []
    if day_number == 1 and not str(day.get("day_recap") or "").strip():
        day["day_recap"] = ""
    elif not str(day.get("day_recap") or "").strip():
        day["day_recap"] = "Lors de la dernière séance, nous avons vu les bases nécessaires pour aborder cette nouvelle étape."
    if not str(day.get("day_transition") or "").strip():
        day["day_transition"] = "À la prochaine séance, nous aborderons la suite logique de cette progression."
    return _normalize_day_audio_slots(day, schedule_day=schedule_day)


def daily_programs_checkpoint_state(job: dict) -> dict:
    """Retourne les journées valides déjà persistées pour ce job immuable."""
    schedule_days = _v2_schedule_days(job)
    try:
        expected_count = (
            len(schedule_days)
            if schedule_days
            else int(job.get("nb_days") or 0)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Nombre de journées invalide") from exc
    if expected_count <= 0:
        raise ValueError("Le pipeline doit contenir au moins une journée")

    raw_value = job.get("daily_programs")
    if isinstance(raw_value, list):
        raw_days = raw_value
        invalid_count = 0
    else:
        try:
            raw_days = json.loads(raw_value or "[]")
            invalid_count = 0
        except (TypeError, json.JSONDecodeError):
            raw_days = []
            invalid_count = 1
    if not isinstance(raw_days, list):
        raw_days = []
        invalid_count += 1

    expected_numbers = list(range(1, expected_count + 1))
    by_number = {}
    for raw_day in raw_days:
        if not isinstance(raw_day, dict):
            invalid_count += 1
            continue
        number = _coerce_day_number(
            raw_day.get("day_number") or raw_day.get("day_index")
        )
        if number not in expected_numbers or number in by_number:
            invalid_count += 1
            continue

        schedule_day = _schedule_day(schedule_days, number)
        expected_course_count = (
            len(_v2_course_slots(schedule_day))
            if schedule_day
            else len(COURSE_AUDIO_SLOTS)
        )
        sub_parts = raw_day.get("sub_parts")
        if (
            not isinstance(sub_parts, list)
            or len(sub_parts) != expected_course_count
            or any(not isinstance(part, dict) for part in sub_parts)
        ):
            invalid_count += 1
            continue

        try:
            day = _complete_day_program_shape(
                raw_day,
                number,
                job.get("tp_name") or "Formation",
                schedule_day=schedule_day,
            )
            _assert_lecture_only_days([day])
        except Exception:
            invalid_count += 1
            continue
        by_number[number] = day

    days = [by_number[number] for number in expected_numbers if number in by_number]
    missing_numbers = [
        number for number in expected_numbers if number not in by_number
    ]
    return {
        "days": days,
        "by_number": by_number,
        "expected_count": expected_count,
        "expected_numbers": expected_numbers,
        "missing_numbers": missing_numbers,
        "invalid_count": invalid_count,
        "complete": not missing_numbers and invalid_count == 0,
        "schedule_days": schedule_days,
    }


def daily_programs_are_complete(job: dict) -> bool:
    """Indique si toutes les journées attendues sont présentes et valides."""
    try:
        return bool(daily_programs_checkpoint_state(job)["complete"])
    except (TypeError, ValueError):
        return False


def _missing_day_batches(
    missing_numbers: list[int],
    batch_size: int,
) -> list[tuple[int, int]]:
    """Regroupe uniquement les journées manquantes, sans englober un checkpoint."""
    numbers = sorted({int(number) for number in missing_numbers})
    if not numbers:
        return []
    size = max(1, int(batch_size or 1))
    batches = []
    batch_start = numbers[0]
    batch_end = numbers[0]
    for number in numbers[1:]:
        if number == batch_end + 1 and number - batch_start + 1 <= size:
            batch_end = number
            continue
        batches.append((batch_start, batch_end))
        batch_start = batch_end = number
    batches.append((batch_start, batch_end))
    return batches


def _split_batch(tp_name: str, nb_days: int, global_program: str,
                 day_start: int, day_end: int, model: str,
                 reac_text: str = "", rc_text: str = "", rome_text: str = "",
                 schedule_days: list[dict] | None = None) -> list:
    """Génère un batch de journées (day_start à day_end inclus)."""
    # Bloc sources enrichies pour le module_content
    enrichment = ""
    if reac_text:
        enrichment += f"\n\n=== EXTRAITS REAC (compétences et savoirs associés) ===\n{reac_text[:6000]}"
    if rc_text:
        enrichment += f"\n\n=== EXTRAITS RC (critères d'évaluation) ===\n{rc_text[:3000]}"
    if rome_text:
        enrichment += f"\n\n=== FICHES ROME ===\n{rome_text[:3000]}"

    prompt_template = (
        _DAILY_SPLIT_PROMPT_V2 if schedule_days else _DAILY_SPLIT_PROMPT
    )
    prompt_schedule_days = (
        [
            day
            for day in schedule_days
            if day_start
            <= int(day.get("day_index") or day.get("day_number") or 0)
            <= day_end
        ]
        if schedule_days
        else None
    )
    prompt = (
        prompt_template
        .replace("{TP_NAME}", tp_name)
        .replace("{NB_DAYS}", str(nb_days))
        .replace("{DAY_START}", str(day_start))
        .replace("{DAY_END}", str(day_end))
        .replace(
            "{COURSE_AUDIO_SLOTS}",
            _course_audio_slots_prompt(prompt_schedule_days),
        )
        .replace("{GLOBAL_PROGRAM}", global_program[:20000] + enrichment)
    )
    try:
        raw = _deepseek_post(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=DAILY_SPLIT_MAX_TOKENS,
            model=model,
        )
        data = _clean_json(raw)
        days = _normalize_daily_payload(
            data,
            day_start,
            day_end,
            tp_name,
            schedule_days=schedule_days,
        )
        _assert_lecture_only_days(days)
        return days
    except (LeaseLostError, DeepSeekRateLimitError, DeepSeekAPIError):
        raise
    except Exception as exc:
        label = (
            f"Journée {day_start}"
            if day_start == day_end
            else f"Journées {day_start}-{day_end}"
        )
        message = f"{label} impossible à générer correctement : {exc}"
        logger.error("❌ %s", message)
        raise DailySplitGenerationError(message) from exc


def run_daily_split(
    job_id: int,
    model: str = None,
    checkpoint: Callable[[], None] | None = None,
) -> dict:
    """Reprend les journées persistées et sauvegarde chaque nouveau batch valide."""
    try:
        if checkpoint:
            checkpoint()
        job = get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} introuvable")

        used_model = model or DEEPSEEK_MODEL
        state = daily_programs_checkpoint_state(job)
        schedule_days = state["schedule_days"]
        nb_days = state["expected_count"]
        days_by_number = dict(state["by_number"])
        resumed_count = len(days_by_number)
        update_job(
            job_id,
            status="daily_splitting",
            daily_programs=json.dumps(state["days"], ensure_ascii=False),
            daily_programs_validated=0,
            error_message=None,
        )
        if checkpoint:
            checkpoint()
        logger.info(
            "🔄 Job %s : découpage en %s journée(s), reprises=%s, "
            "batch=%s, workers=%s (modèle: %s)...",
            job_id,
            nb_days,
            resumed_count,
            BATCH_SIZE,
            DAILY_SPLIT_WORKERS,
            used_model,
        )

        batches = _missing_day_batches(
            state["missing_numbers"],
            BATCH_SIZE,
        )
        errors = []

        def run_batch(day_start, day_end):
            return _split_batch(
                tp_name=job["tp_name"],
                nb_days=nb_days,
                global_program=job["global_program"],
                day_start=day_start,
                day_end=day_end,
                model=used_model,
                reac_text=job.get("reac_text") or "",
                rc_text=job.get("rc_text") or "",
                rome_text=job.get("rome_text") or "",
                schedule_days=schedule_days,
            )

        if batches:
            workers = min(max(1, DAILY_SPLIT_WORKERS), len(batches))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                future_map = {
                    pool.submit(run_batch, start, end): (start, end)
                    for start, end in batches
                }
                for future in as_completed(future_map):
                    start, end = future_map[future]
                    try:
                        days = future.result()
                        for day in sorted(
                            days,
                            key=lambda item: _coerce_day_number(
                                item.get("day_number")
                            ) or 0,
                        ):
                            number = _coerce_day_number(day.get("day_number"))
                            if (
                                number not in state["expected_numbers"]
                                or not start <= number <= end
                            ):
                                raise ValueError(
                                    f"Journée inattendue {number} pour le batch "
                                    f"{start}-{end}"
                                )
                            days_by_number[number] = day

                            partial_days = [
                                days_by_number[expected_number]
                                for expected_number in state["expected_numbers"]
                                if expected_number in days_by_number
                            ]
                            _assert_lecture_only_days(partial_days)
                            if checkpoint:
                                checkpoint()
                            update_job(
                                job_id,
                                status="daily_splitting",
                                daily_programs=json.dumps(
                                    partial_days,
                                    ensure_ascii=False,
                                ),
                                daily_programs_validated=0,
                                error_message=None,
                            )
                            if checkpoint:
                                checkpoint()
                            logger.info(
                                "✅ Job %s : checkpoint journée %s (%s/%s)",
                                job_id,
                                number,
                                len(partial_days),
                                nb_days,
                            )
                    except LeaseLostError:
                        raise
                    except Exception as e:
                        errors.append((start, end, e))

        if errors:
            for _start, _end, exc in errors:
                if isinstance(
                    exc,
                    (DeepSeekRateLimitError, DeepSeekAPIError),
                ):
                    raise exc
            raise DailySplitGenerationError(
                "; ".join(
                    f"Batch {start}-{end} : {exc}"
                    for start, end, exc in errors
                )
            )

        all_days = [
            days_by_number[number]
            for number in state["expected_numbers"]
            if number in days_by_number
        ]
        actual_numbers = [_coerce_day_number(day.get("day_number")) for day in all_days]
        if actual_numbers != state["expected_numbers"]:
            raise ValueError(
                "Daily split incohérent : attendu jours "
                f"{state['expected_numbers']}, reçu {actual_numbers}"
            )
        _assert_lecture_only_days(all_days)

        if checkpoint:
            checkpoint()
        logger.info(f"✅ Job {job_id} : {len(all_days)} journées générées au total")
        update_job(
            job_id,
            status="daily_validated",
            daily_programs=json.dumps(all_days, ensure_ascii=False),
            daily_programs_validated=1,
            daily_programs_generated_via="api",
            error_message=None,
        )
        if checkpoint:
            checkpoint()
        return {
            "ok": True,
            "days": len(all_days),
            "resumed_days": resumed_count,
            "generated_days": len(all_days) - resumed_count,
            "generated_via": "api",
        }

    except LeaseLostError:
        logger.warning("PIPELINE_DAILY_SPLIT_LEASE_LOST job=%s", job_id)
        raise
    except Exception as e:
        logger.error(f"❌ Job {job_id} découpage journées échoué : {e}")
        update_job(job_id, status="error", error_message=str(e))
        raise


# ─── Affinage IA (refine) ─────────────────────────────────────────────────────

_REFINE_PROMPT = """Tu es un expert en ingénierie pédagogique spécialisé dans les titres professionnels.

Voici un {CONTENT_TYPE} que tu as généré pour la formation "{TP_NAME}" :

--- CONTENU ACTUEL ---
{CURRENT_CONTENT}
--- FIN DU CONTENU ---

INSTRUCTION DE MODIFICATION :
{INSTRUCTION}

Modifie le contenu en suivant exactement cette instruction.
- Conserve le même format et la même structure
- Ne commente pas les changements, retourne uniquement le contenu modifié
- Si le contenu est du JSON, retourne du JSON valide"""


def refine_content(
    content_type: str,
    current_content: str,
    instruction: str,
    tp_name: str,
    model: str = None,
) -> str:
    """
    Affine un contenu généré (programme global ou programme journée) via une instruction.
    Appel synchrone — l'utilisateur attend la réponse.
    """
    label = "programme de formation global" if content_type == "global" else "programme de journée"
    prompt = (
        _REFINE_PROMPT
        .replace("{CONTENT_TYPE}", label)
        .replace("{TP_NAME}", tp_name)
        .replace("{CURRENT_CONTENT}", current_content[:30000])
        .replace("{INSTRUCTION}", instruction)
    )
    used_model = model or DEEPSEEK_MODEL
    logger.info(f"🔧 Affinage contenu ({content_type}) avec {used_model} : '{instruction[:80]}'")
    return _deepseek_post(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=16000,
        model=used_model,
    )


# ─── Lancement TTS par journée ────────────────────────────────────────────────

def expected_course_folder_name(day_data: dict, fallback_day_number: int) -> str:
    """Nom stable du dossier cours attendu pour une journée validée."""
    day_data = day_data or {}
    day_num = day_data.get("day_number") or fallback_day_number
    day_title = day_data.get("title") or f"Jour {day_num}"
    return f"Jour {day_num} — {day_title}"


def _folder_row_to_dict(row, day_data: dict, day_index: int, duplicate_of: int = None) -> dict:
    return {
        "folder_id": row["id"],
        "name": row["name"],
        "position": row["position"],
        "platform_id": row["platform_id"],
        "formation_job_id": row["formation_job_id"],
        "content_job_id": row.get("content_job_id"),
        "content_status": row.get("content_status"),
        "total_words": row.get("total_words") or 0,
        "segments_completed": row.get("segments_completed") or 0,
        "day_number": (day_data or {}).get("day_number") or day_index + 1,
        "day_title": (day_data or {}).get("title") or row["name"],
        "expected_name": expected_course_folder_name(day_data, day_index + 1),
        "duplicate_of": duplicate_of,
    }


def get_expected_course_folders(
    job_id: int,
    *,
    create_missing: bool = False,
    platform_id: int = None,
) -> dict:
    """Résout les folders canoniques d'un job, un seul par journée attendue.

    Si des doublons existent pour un même nom de journée, on garde le folder le
    plus avancé, puis le plus ancien. Les doublons restent en base mais les
    étapes aval peuvent les ignorer proprement.
    """
    job = get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} introuvable")

    daily_programs = json.loads(job.get("daily_programs") or "[]")
    resolved_platform_id = platform_id or job.get("platform_id")
    folders = []
    duplicates = []
    missing = []
    created = []

    for idx, day_data in enumerate(daily_programs):
        folder_name = expected_course_folder_name(day_data, idx + 1)
        matches = list_expected_course_folder_matches(job_id, folder_name)

        if not matches and create_missing:
            created_row = create_course_folder_for_job(
                platform_id=resolved_platform_id,
                folder_name=folder_name,
                formation_job_id=job_id,
            )
            created.append({"folder_id": created_row["id"], "name": folder_name})
            matches = [created_row]

        if not matches:
            missing.append({
                "day_number": (day_data or {}).get("day_number") or idx + 1,
                "name": folder_name,
            })
            continue

        canonical = _folder_row_to_dict(matches[0], day_data, idx)
        folders.append(canonical)
        for duplicate in matches[1:]:
            duplicates.append(
                _folder_row_to_dict(
                    duplicate,
                    day_data,
                    idx,
                    duplicate_of=canonical["folder_id"],
                )
            )

    return {
        "expected_count": len(daily_programs),
        "folders": folders,
        "folder_ids": [f["folder_id"] for f in folders],
        "duplicates": duplicates,
        "missing": missing,
        "created": created,
    }


def is_expected_course_folder(job_id: int, folder_id: int) -> bool:
    """True si le folder est le folder canonique d'une journée attendue."""
    try:
        state = get_expected_course_folders(job_id)
    except Exception:
        logger.warning(
            "PIPELINE_FOLDER_CANONICAL_CHECK_FAILED job=%s folder=%s",
            job_id,
            folder_id,
            exc_info=True,
        )
        return True
    expected_ids = set(state.get("folder_ids") or [])
    return not expected_ids or folder_id in expected_ids


def repair_orphan_content_folders(job_id: int) -> dict:
    """Rattache les dossiers cours créés par l'ancien launch-tts sans job_id.

    Bug historique : la route manuelle de génération texte créait les
    `cours_folders` avec `platform_id` uniquement. Le texte existait, mais le
    dashboard filtrait par `formation_job_id` et voyait donc 0 journée.
    """
    job = get_job(job_id)
    if not job:
        return {"repaired": 0, "missing": 0, "folders": []}

    daily_programs = json.loads(job.get("daily_programs") or "[]")
    if not daily_programs:
        return {"repaired": 0, "missing": 0, "folders": []}

    repaired = []
    missing = 0
    for day_data in daily_programs:
        day_num = day_data.get("day_number", len(repaired) + missing + 1)
        day_title = day_data.get("title", f"Jour {day_num}")
        folder_name = f"Jour {day_num} — {day_title}"

        if course_folder_exists_for_job(job_id, folder_name):
            continue

        folder_id = find_orphan_course_folder(job["platform_id"], folder_name)
        if not folder_id:
            missing += 1
            continue

        if attach_course_folder_to_job(job_id, folder_id):
            repaired.append({"folder_id": folder_id, "name": folder_name})

    if repaired:
        logger.warning(
            "PIPELINE_FOLDER_REPAIR job=%s repaired=%s missing=%s folders=%s",
            job_id,
            len(repaired),
            missing,
            repaired,
        )
    return {"repaired": len(repaired), "missing": missing, "folders": repaired}


def _format_day_program_text(
    day_data: dict,
    tp_name: str,
    schedule_day: dict | None = None,
) -> str:
    """Formate le programme d'une journée en texte pour le job TTS."""
    day_data = _normalize_day_audio_slots(
        day_data,
        schedule_day=schedule_day,
    )
    lines = [
        f"TITRE PROFESSIONNEL : {tp_name}",
        f"JOURNÉE {day_data.get('day_number', '?')} : {day_data.get('title', '')}",
        "",
    ]
    if day_data.get("day_recap"):
        lines.append(f"RAPPEL DE LA VEILLE : {day_data['day_recap']}")
        lines.append("")

    for sp in day_data.get("sub_parts", []):
        lines.append(_format_slot_generation_source(sp))
        lines.append("")

    if day_data.get("day_transition"):
        lines.append(f"TRANSITION : {day_data['day_transition']}")

    return "\n".join(lines)


# ─── Helpers DB ───────────────────────────────────────────────────────────────

def create_job(platform_id: int, tp_name: str, rncp_code: str,
               total_hours: int, nb_days: int) -> int:
    """Crée un job pipeline formation en DB. Retourne l'id."""
    return create_pipeline_job(
        platform_id=platform_id,
        tp_name=tp_name,
        rncp_code=rncp_code,
        total_hours=total_hours,
        nb_days=nb_days,
    )


def update_job(job_id: int, **kwargs):
    """Met à jour les champs d'un job."""
    update_pipeline_job(job_id, **kwargs)


def get_job(job_id: int) -> dict | None:
    """Retourne le job ou None."""
    return get_pipeline_job(job_id)


def list_jobs(platform_id: int = None) -> list:
    """Liste tous les jobs (toutes plateformes), avec le nom de la plateforme."""
    return list_pipeline_jobs(platform_id)
