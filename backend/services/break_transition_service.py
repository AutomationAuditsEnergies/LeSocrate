"""Transitions des fichiers Q&A et pauses, pilotées par leur voisinage.

Chaque bloc facultatif porte désormais sa propre intro et sa propre outro. Le
cours précédent ne l'annonce jamais. L'outro annonce une reprise seulement si
un cours suit directement ; si un autre bloc facultatif suit, elle clôture le
bloc courant sans l'annoncer. Un Q&A final clôt toute la séance.
"""

import json
import re

from utils.deepseek_client import default_model, post_message as _llm_post
from utils.logger import get_logger

logger = get_logger(__name__)


_QA_FALLBACKS = [
    (
        "Nous ouvrons maintenant un temps de questions-réponses. Vous pouvez poser dans le chat les points que vous souhaitez clarifier.",
        "Ce temps de questions-réponses est maintenant terminé.",
    ),
    (
        "C'est le moment des questions. Posez dans le chat ce que vous voulez clarifier sur ce qui vient d'être vu.",
        "Merci pour vos questions. Ce temps d'échange est maintenant terminé.",
    ),
]

_PAUSE_FALLBACKS = [
    (
        "Nous marquons maintenant une courte pause.",
        "Cette pause est maintenant terminée.",
    ),
    (
        "Nous faisons maintenant une courte pause.",
        "Nous arrivons au terme de cette pause.",
    ),
]

_PAUSE_MIDI_FALLBACK = (
    "Nous marquons maintenant la pause déjeuner.",
    "La pause déjeuner est maintenant terminée.",
)

_SCHEDULE_NEUTRAL_BREAK_FILENAMES = {
    "pause_12h10_12h20.mp3",
    "pause_midi_13h15_14h45.mp3",
    "qa_13h05_13h15.mp3",
}

_MINUTE_WORDS = {
    1: "une",
    2: "deux",
    3: "trois",
    4: "quatre",
    5: "cinq",
    6: "six",
    7: "sept",
    8: "huit",
    9: "neuf",
    10: "dix",
    11: "onze",
    12: "douze",
    13: "treize",
    14: "quatorze",
    15: "quinze",
    20: "vingt",
    30: "trente",
}


def _clean_text(text: str) -> str:
    text = (text or "").strip()
    text = text.replace("```json", "").replace("```", "").strip()
    text = re.sub(r"^(voici|here is|here's)[^.\n]*[:.]\s*", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _extract_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if "```" in raw:
        raw = raw.replace("```json", "```")
        parts = raw.split("```")
        raw = max(parts, key=len).strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        raw = match.group(0)
    data = json.loads(raw)
    return {
        "intro": _clean_text(data.get("intro", "")),
        "outro": _clean_text(data.get("outro", "")),
    }


def duration_label(duration_sec: int, break_type: str = "") -> str:
    """Retourne une durée orale fiable, sans inventer si le slot est atypique."""
    if break_type == "pause_midi" or duration_sec >= 3600:
        return "pause déjeuner"
    duration_sec = int(duration_sec)
    if duration_sec % 60 != 0:
        return ""
    minutes = duration_sec // 60
    word = _MINUTE_WORDS.get(minutes)
    if not word:
        return ""
    return f"{word} minute" if minutes == 1 else f"{word} minutes"


def is_schedule_neutral_break(filename: str) -> bool:
    """Vrai pour les breaks dont le voisinage change selon le mode été/hiver."""
    filename = (filename or "").split("?", 1)[0].rsplit("/", 1)[-1]
    return filename in _SCHEDULE_NEUTRAL_BREAK_FILENAMES


def _strip_tts_tags_for_context(text: str) -> str:
    return re.sub(r"\[[^\]]+\]", "", text or "")


def _tail_words_for_context(text: str, n: int = 150) -> str:
    words = _strip_tts_tags_for_context(text).split()
    return " ".join(words[-n:])


def _head_words_for_context(text: str, n: int = 150) -> str:
    words = _strip_tts_tags_for_context(text).split()
    return " ".join(words[:n])


def nearest_course_bloc(playlist_items: list, start_idx: int, direction: int) -> int | None:
    """Retourne le numéro du cours voisin dans une playlist effective."""
    idx = start_idx + direction
    while 0 <= idx < len(playlist_items):
        _filename, _duration, file_type, bloc_num = playlist_items[idx]
        if file_type == "cours":
            return bloc_num
        idx += direction
    return None


def next_item_type(playlist_items: list, start_idx: int) -> str | None:
    """Retourne le type du fichier suivant dans une playlist effective."""
    if start_idx + 1 >= len(playlist_items):
        return None
    return playlist_items[start_idx + 1][2]


def previous_item_type(playlist_items: list, start_idx: int) -> str | None:
    """Retourne le type du fichier précédent dans une playlist effective."""
    if start_idx <= 0:
        return None
    return playlist_items[start_idx - 1][2]


def _item_filename(playlist_items: list, idx: int) -> str:
    if idx < 0 or idx >= len(playlist_items):
        return ""
    return str(playlist_items[idx][0] or "")


def _planned_break_intro(break_type: str, bloc_num: int) -> str:
    """Intro statique prévue pour un break, réutilisable par l'audio précédent."""
    try:
        from services.playlist_tts_service import (
            _get_pause_midi_text,
            _get_pause_text,
            _get_qa_text,
        )
        if break_type == "qa":
            intro, _outro = _get_qa_text(bloc_num)
        elif break_type == "pause_midi":
            intro, _outro = _get_pause_midi_text()
        elif break_type == "pause":
            intro, _outro = _get_pause_text(bloc_num)
        else:
            return ""
        return re.sub(r"\s+", " ", (intro or "").strip())
    except Exception:
        return ""


def _planned_intro_for_next_item(playlist_items: list, item_idx: int) -> str:
    if item_idx + 1 >= len(playlist_items):
        return ""
    _filename, _duration, next_type, next_bloc = playlist_items[item_idx + 1]
    return _planned_break_intro(str(next_type or ""), int(next_bloc or 1))


def break_intro_owned_by_previous(
    playlist_items: list,
    start_idx: int,
    break_type: str,
) -> bool:
    """Les blocs facultatifs possèdent toujours leur propre intro."""
    return False


def should_announce_next_break_in_outro(
    filename: str,
    current_type: str,
    next_type: str | None,
) -> bool:
    """Aucun audio ne vole désormais l'intro du bloc facultatif suivant."""
    return False


def fallback_break_transition(
    break_type: str,
    bloc_num: int,
    duration_sec: int,
    schedule_neutral: bool = False,
    next_item_type: str | None = None,
    intro_owned_by_previous: bool = False,
) -> tuple[str, str]:
    """Fallback statique sans appel LLM."""
    if break_type == "pause_midi":
        intro, outro = _PAUSE_MIDI_FALLBACK
    else:
        variants = _QA_FALLBACKS if break_type == "qa" else _PAUSE_FALLBACKS
        intro, outro = variants[(max(1, int(bloc_num or 1)) - 1) % len(variants)]

    if next_item_type == "cours":
        if break_type == "qa":
            outro = "Ce temps de questions-réponses est terminé. Nous allons maintenant reprendre le cours."
        elif break_type == "pause_midi":
            outro = "La pause déjeuner est terminée. Nous allons maintenant reprendre le cours."
        else:
            outro = "La pause est terminée. Nous allons maintenant reprendre le cours."
    elif next_item_type is None and break_type == "qa":
        outro = (
            "Ce temps de questions-réponses conclut notre séance. "
            "Nous nous retrouverons lors de la prochaine séance."
        )
    return intro, outro


def _build_prompt(
    break_type: str,
    bloc_num: int,
    prev_excerpt: str,
    next_excerpt: str,
    duration_sec: int,
    next_item_type: str | None,
    is_last_break: bool,
    schedule_neutral: bool,
    intro_owned_by_previous: bool,
) -> str:
    label = duration_label(duration_sec, break_type)
    duration_instruction = (
        f"Tu peux mentionner explicitement la durée : {label}."
        if label and break_type != "pause_midi"
        else "Ne mentionne pas de durée précise."
    )

    if break_type == "qa":
        intro_role = (
            "INTRO : annonce sobrement le temps de questions-réponses et indique "
            "que les questions peuvent être posées dans le chat."
        )
        target = "intro 20-45 mots, outro 20-55 mots"
    elif break_type == "pause_midi":
        intro_role = "INTRO : annonce uniquement la pause déjeuner, sobrement."
        target = "intro 12-30 mots, outro 15-45 mots"
    else:
        intro_role = "INTRO : annonce uniquement la pause, en une phrase courte."
        target = "intro 10-25 mots, outro 15-45 mots"

    if next_item_type == "cours":
        outro_role = (
            "OUTRO : clôture le bloc courant puis annonce simplement la reprise "
            "du cours, sans inventer son thème."
        )
    elif next_item_type is None and break_type == "qa":
        outro_role = (
            "OUTRO : clôture le temps de questions puis toute la séance de la "
            "journée, avec une formule sobre vers la prochaine séance."
        )
    else:
        outro_role = (
            "OUTRO : clôture uniquement le bloc courant. N'annonce pas le bloc "
            "facultatif qui suit : il possède sa propre intro."
        )
    role = f"{intro_role}\n{outro_role}"

    next_label = {
        "cours": "un cours",
        "qa": "un temps de questions",
        "pause": "une pause",
        "pause_midi": "la pause déjeuner",
        None: "la fin de journée",
    }.get(next_item_type, str(next_item_type))

    previous_context = (
        "(contexte précédent volontairement omis : l'intro de pause déjeuner "
        "doit rester neutre et ne pas résumer le matin)"
        if break_type == "pause_midi"
        else (prev_excerpt or "(indisponible)")
    )
    if schedule_neutral and break_type != "qa":
        previous_context = (
            "(contexte précédent volontairement omis : ce fichier doit rester neutre "
            "car son voisinage change selon le mode été/hiver)"
        )

    next_context = next_excerpt or "(aucun prochain cours disponible)"
    if schedule_neutral:
        next_context = (
            "(contexte suivant volontairement omis : ce fichier doit rester valable "
            "quel que soit le mode été/hiver)"
        )

    return f"""Tu écris les phrases d'un fichier audio de transition pour une classe virtuelle audio.

TYPE DE FICHIER : {break_type}
BLOC PRÉCÉDENT : {bloc_num}
DURÉE DU FICHIER : {duration_sec} secondes
ÉLÉMENT QUI SUIT CE FICHIER : {next_label}
DERNIER BREAK DE LA JOURNÉE : {"oui" if is_last_break else "non"}
TRANSITION SENSIBLE ÉTÉ/HIVER : {"oui" if schedule_neutral else "non"}
INTRO PORTÉE PAR CE FICHIER : oui

FIN DU COURS PRÉCÉDENT :
---
{previous_context}
---

DÉBUT DU PROCHAIN COURS :
---
{next_context}
---

RÔLE DES TEXTES :
{role}

CONSIGNES :
- {duration_instruction}
- Ne fais pas parler les apprenants et ne prétends pas répondre réellement aux questions.
- Pour les Q&A, mentionne que les questions peuvent être posées dans le chat.
- Pour les pauses, ne parle pas trop : l'intro doit rester courte.
- Pour la pause déjeuner, l'intro NE doit faire AUCUNE référence au contenu du
  matin ou au cours précédent. Elle annonce uniquement la pause déjeuner.
- Ne suppose jamais que les apprenants mangent, boivent, prennent un encas,
  se reposent, soufflent ou se détendent.
- N'annonce l'élément suivant que s'il s'agit directement d'un cours.
- Si un Q&R termine la journée, son outro clôt toute la séance.
- Ton de formateur adulte, sobre, clair, professionnel.
- Pas de "super", "génial", "bravo", "je vous vois", "levez la main", "vous m'entendez".
- Pas d'horaires, de créneaux ou de planning.
- Pas de guillemets, pas de JSON imbriqué, pas de markdown.
- Cibles : {target}.

Réponds uniquement avec ce JSON valide :
{{
  "intro": "texte d'intro",
  "outro": "texte d'outro"
}}"""


def generate_break_transition(
    break_type: str,
    bloc_num: int,
    prev_excerpt: str,
    next_excerpt: str | None,
    duration_sec: int,
    next_item_type: str | None = None,
    is_last_break: bool = False,
    model: str | None = None,
    schedule_neutral: bool = False,
    intro_owned_by_previous: bool = False,
) -> tuple[str, str]:
    """Génère une paire (intro, outro) contextuelle pour Q&A/pause."""
    break_type = (break_type or "").strip().lower()
    if break_type not in {"qa", "pause", "pause_midi"}:
        raise ValueError(f"break_type invalide: {break_type}")

    prompt = _build_prompt(
        break_type=break_type,
        bloc_num=bloc_num,
        prev_excerpt=prev_excerpt,
        next_excerpt=next_excerpt or "",
        duration_sec=duration_sec,
        next_item_type=next_item_type,
        is_last_break=is_last_break,
        schedule_neutral=schedule_neutral,
        intro_owned_by_previous=intro_owned_by_previous,
    )

    try:
        raw = _llm_post(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=900,
            model=model or default_model(),
            timeout=120,
        )
        data = _extract_json(raw)
        if intro_owned_by_previous:
            data["intro"] = ""
        if (not data["intro"] and not intro_owned_by_previous) or not data["outro"]:
            raise ValueError("intro/outro vide")
        logger.info(
            f"🧩 Transition {break_type} bloc {bloc_num}: "
            f"{len(data['intro'].split())}+{len(data['outro'].split())} mots"
        )
        return data["intro"], data["outro"]
    except Exception as e:
        logger.warning(
            f"⚠️ Transition {break_type} bloc {bloc_num} fallback "
            f"({type(e).__name__}: {str(e)[:160]})"
        )
        return fallback_break_transition(
            break_type,
            bloc_num,
            duration_sec,
            schedule_neutral=schedule_neutral,
            next_item_type=next_item_type,
            intro_owned_by_previous=intro_owned_by_previous,
        )


def build_break_transition_texts(
    filename: str,
    duration_sec: int,
    break_type: str,
    bloc_num: int,
    item_idx: int,
    playlist_items: list,
    get_bloc_text,
    model: str | None = None,
) -> tuple[str, str]:
    """Construit les textes intro/outro depuis une playlist effective.

    `get_bloc_text(bloc_num)` est injecté pour laisser chaque pipeline exposer
    son propre modèle de données sans dupliquer la logique de transition.
    """
    # Dynamic schedule assets deliberately use deterministic generic copy: the
    # same pedagogical content remains reusable while the occurrence decides
    # only which contextual outro variant is needed.
    dynamic_filename = re.fullmatch(r"(?:qa|pause)_\d{2}\.mp3", _item_filename([[filename, 0, break_type, bloc_num]], 0))
    if dynamic_filename:
        return fallback_break_transition(
            break_type,
            bloc_num,
            duration_sec,
            next_item_type=next_item_type(playlist_items, item_idx),
        )

    try:
        from services.fixed_break_scripts import get_fixed_break_script

        fixed = get_fixed_break_script(
            filename,
            intro_owned_by_previous=break_intro_owned_by_previous(
                playlist_items,
                item_idx,
                break_type,
            ),
        )
        if fixed:
            return fixed["intro"], fixed["outro"]
    except Exception as e:
        logger.warning("⚠️ Script fixe break indisponible pour %s: %s", filename, e)

    prev_bloc = nearest_course_bloc(playlist_items, item_idx, -1) or bloc_num
    next_bloc = nearest_course_bloc(playlist_items, item_idx, 1)
    prev_text = get_bloc_text(prev_bloc) if prev_bloc else ""
    next_text = get_bloc_text(next_bloc) if next_bloc else ""
    intro_owned = break_intro_owned_by_previous(playlist_items, item_idx, break_type)

    intro, outro = generate_break_transition(
        break_type=break_type,
        bloc_num=prev_bloc or bloc_num,
        prev_excerpt=_tail_words_for_context(prev_text, 150),
        next_excerpt=_head_words_for_context(next_text, 150) if next_bloc else "",
        duration_sec=duration_sec,
        next_item_type=next_item_type(playlist_items, item_idx),
        is_last_break=next_bloc is None,
        model=model,
        schedule_neutral=is_schedule_neutral_break(filename),
        intro_owned_by_previous=intro_owned,
    )
    ntype = next_item_type(playlist_items, item_idx)
    if should_announce_next_break_in_outro(filename, break_type, ntype):
        next_intro = _planned_intro_for_next_item(playlist_items, item_idx)
        if next_intro and next_intro.lower() not in (outro or "").lower():
            outro = f"{(outro or '').rstrip()} {next_intro}".strip()
    return intro, outro
