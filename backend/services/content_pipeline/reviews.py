from __future__ import annotations

import json
import os
import re

from .prompts import prompt_file_path

AUDIO_BLOCK_MARKER_RE = re.compile(r"^\s*<<<BLOC_AUDIO_(\d+)>>>\s*$", re.MULTILINE)


def extract_audio_block_number(text: str | None) -> int | None:
    match = AUDIO_BLOCK_MARKER_RE.search(text or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def section_label(section: dict) -> str:
    kind = section.get("kind")
    if kind == "opening":
        return "introduction"
    if kind == "course_conclusion":
        return "conclusion du cours"
    if kind == "day_conclusion":
        return "conclusion globale de la journée"
    return f"partie {section.get('part_number')}"


def structured_sections_for_course(course_plan: dict) -> list[dict]:
    sections = [{"kind": "opening", **(course_plan.get("opening") or {})}]
    for part in course_plan.get("parts") or []:
        sections.append({"kind": "part", **part})
    sections.append({"kind": "course_conclusion", **(course_plan.get("course_conclusion") or {})})
    if course_plan.get("day_conclusion"):
        sections.append({"kind": "day_conclusion", **course_plan["day_conclusion"]})
    return sections


def structured_review_context_for_segment(
    saved_script_plan: dict | None,
    sub_idx: int,
    segment_text: str,
) -> str:
    """Build locked-plan context for one canonical course review segment."""
    saved_script_plan = saved_script_plan or {}
    structured_plan = saved_script_plan.get("structured_course_plan") or {}
    courses = structured_plan.get("courses") if isinstance(structured_plan, dict) else None
    if not isinstance(courses, list) or not courses:
        return ""

    marker_course_number = extract_audio_block_number(segment_text)
    course_number = marker_course_number or int(sub_idx or 0) + 1
    course_plan = next(
        (course for course in courses if int(course.get("course_number") or 0) == course_number),
        None,
    )
    if not course_plan:
        return ""

    sections = structured_sections_for_course(course_plan)
    section_summary = "\n".join(
        f"- {section_label(section)} · cible {int(section.get('target_words') or 0)} mots"
        for section in sections
    )
    return f"""
═══════════════════════════════════════════════════════════════════
PLAN JSON VERROUILLÉ DU COURS — CONTEXTE REVIEW
═══════════════════════════════════════════════════════════════════
Tu révises le cours {course_number}/7 : {course_plan.get('course_title') or ''}.
Ce segment correspond à UN cours canonique complet, pas à un morceau arbitraire.

Le plan ci-dessous fait autorité. Tu peux corriger une phrase, une transition,
une redondance, une conclusion mal fermée ou une incohérence locale, mais tu ne
dois pas réinventer le cours, changer le plan, supprimer une partie annoncée,
ajouter un nouveau chapitre, ni déplacer le périmètre pédagogique.

Points à vérifier avec ce plan :
- l'ouverture remplit bien sa fonction ;
- le plan annoncé est respecté dans l'ordre général ;
- les parties restent dans leur périmètre ;
- la conclusion arrive au bon endroit et ne relance pas un développement ;
- le cours ne termine pas le cours précédent et ne démarre pas le suivant ;
- les formulations côté apprenant restent naturelles, notamment sans jargon
  technique comme "bloc", "créneau", "horaire" ou "planning".
- les unités internes ne sont pas nommées "ce cours", "premier cours" ou
  "cours actuel" côté apprenant ; préférer thème, partie, chapitre, séquence ou
  axe.

Sections attendues :
{section_summary}

Plan complet du cours :
{json.dumps(course_plan, ensure_ascii=False, indent=2)}
""".strip()


def load_structured_rule_file(filename: str) -> tuple[str, float]:
    path = prompt_file_path("reviews", filename)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    rules = data.get("rules") or []
    if not isinstance(rules, list):
        raise ValueError(f"Fichier règles invalide: {filename}")
    blocks = []
    for rule in rules:
        body = (rule.get("body") or "").strip() if isinstance(rule, dict) else ""
        if body:
            blocks.append(body)
    if not blocks:
        raise ValueError(f"Aucune règle exploitable dans {filename}")
    header = f"SOURCE MODULAIRE: {filename} · version {data.get('version') or 'unknown'}"
    return header + "\n\n" + "\n\n".join(blocks), os.path.getmtime(path)
