"""
Transitions contextuelles pour fichiers Q&A et pauses.

Chaque break produit deux textes :
- intro : annonce uniquement la fonction du fichier courant (questions ou pause)
- outro : clôture le fichier courant et raccorde vers le cours suivant

La logique est pilotée par la playlist effective. Quand le fichier précédent
annonce déjà une pause, le fichier pause ne refait pas d'intro : il garde
seulement son outro en fin de créneau.
"""

import json
import re

from utils.anthropic_client import default_model, post_message as _llm_post
from utils.logger import get_logger

logger = get_logger(__name__)


_QA_FALLBACKS = [
    (
        "On prend maintenant un temps pour vos questions sur la partie que l'on vient de travailler. Vous pouvez les poser dans le chat.",
        "Très bien, on clôt ce temps de questions. On reprend ensuite le fil du cours.",
    ),
    (
        "C'est le moment des questions. Posez dans le chat ce que vous voulez clarifier sur ce qui vient d'être vu.",
        "Merci pour ce temps d'échange. On va maintenant continuer avec la suite du programme.",
    ),
]

_PAUSE_FALLBACKS = [
    (
        "On fait maintenant une courte pause. Prenez le temps de souffler.",
        "La pause est terminée. On reprend maintenant la suite du cours.",
    ),
    (
        "On marque une petite pause. Profitez-en pour vous reposer un instant.",
        "La pause est finie. On reprend avec la suite.",
    ),
]

_PAUSE_MIDI_FALLBACK = (
    "On marque maintenant la pause déjeuner. Prenez le temps de souffler et de vous reposer.",
    "La pause déjeuner est terminée. On reprend tranquillement le fil de la journée.",
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
    """Vrai si le break doit commencer sans intro.

    Les fichiers sensibles été/hiver restent neutres : si le fichier précédent
    est lui-même sensible, on ne suppose pas qu'il a annoncé ce break.
    """
    if break_type not in {"qa", "pause", "pause_midi"}:
        return False
    if previous_item_type(playlist_items, start_idx) not in {"cours", "qa"}:
        return False
    prev_filename = _item_filename(playlist_items, start_idx - 1)
    return not is_schedule_neutral_break(prev_filename)


def should_announce_next_break_in_outro(
    filename: str,
    current_type: str,
    next_type: str | None,
) -> bool:
    """Vrai si l'audio courant doit annoncer le break qui arrive ensuite."""
    if next_type not in {"qa", "pause", "pause_midi"}:
        return False
    if current_type not in {"cours", "qa"}:
        return False
    return not is_schedule_neutral_break(filename)


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
        return ("", outro) if intro_owned_by_previous else (intro, outro)

    variants = _QA_FALLBACKS if break_type == "qa" else _PAUSE_FALLBACKS
    intro, outro = variants[(max(1, int(bloc_num or 1)) - 1) % len(variants)]
    label = duration_label(duration_sec, break_type)
    if intro_owned_by_previous:
        intro = ""
    elif break_type == "pause" and label:
        intro = f"On fait maintenant une pause de {label}. Prenez le temps de souffler."
    if break_type == "pause" and label:
        pause_sentence = f"On va maintenant prendre une pause de {label}."
    else:
        pause_sentence = "On va maintenant prendre une courte pause."
    if break_type == "qa" and label and not intro_owned_by_previous:
        intro = f"On prend maintenant {label} pour vos questions sur la partie que l'on vient de travailler. Vous pouvez les poser dans le chat."
    if break_type == "qa" and next_item_type in {"pause", "pause_midi"}:
        next_intro = _planned_break_intro(next_item_type, bloc_num)
        if next_intro:
            pause_sentence = next_intro
        outro = (
            "Très bien, on clôt ce temps de questions. Merci pour vos retours, "
            f"gardez simplement ces repères en tête. {pause_sentence}"
        )
    if schedule_neutral:
        if break_type == "qa":
            outro = "Très bien, on clôt ce temps de questions. Gardez ces repères en tête pour la suite de la journée."
        elif break_type == "pause":
            outro = "On arrive au terme de ce temps de respiration. Gardez simplement le fil pour la suite de la journée."
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

    if intro_owned_by_previous and break_type in {"qa", "pause", "pause_midi"}:
        role = (
            "INTRO : chaîne vide obligatoire, car le fichier précédent annonce déjà ce moment.\n"
            "OUTRO : clôture seulement ce moment. Si ce n'est pas une "
            "transition sensible été/hiver, raccorde sobrement vers la suite."
        )
        target = "intro 0 mot, outro 25-65 mots"
    elif schedule_neutral and break_type == "qa":
        role = (
            "INTRO : annonce le temps de questions, mentionne le chat, et contextualise "
            "brièvement avec le thème qui vient d'être travaillé.\n"
            "OUTRO : clôture le temps de questions SANS annoncer ce qui vient après. "
            "Ne parle ni de pause déjeuner, ni de prochain cours, ni de reprise immédiate."
        )
        target = "intro 35-70 mots, outro 25-55 mots"
    elif schedule_neutral and break_type == "pause_midi":
        role = (
            "INTRO : annonce seulement la pause déjeuner, sobrement.\n"
            "OUTRO : annonce seulement la fin de la pause déjeuner, sans annoncer "
            "le cours ou le thème qui suit."
        )
        target = "intro 30-60 mots, outro 25-55 mots"
    elif schedule_neutral:
        role = (
            "INTRO : annonce uniquement la pause. Reste court.\n"
            "OUTRO : clôture ce temps de respiration SANS annoncer ce qui vient après. "
            "Ne parle ni de pause déjeuner, ni de prochain cours, ni de reprise immédiate."
        )
        target = "intro 20-45 mots, outro 20-50 mots"
    elif break_type == "qa" and next_item_type in {"pause", "pause_midi"}:
        role = (
            "INTRO : annonce le temps de questions, mentionne le chat, et contextualise "
            "brièvement avec le thème qui vient d'être travaillé.\n"
            "OUTRO : clôture chaleureusement le temps de questions, puis annonce "
            "sobrement la pause qui arrive. Le fichier pause suivant ne refera pas "
            "d'intro ; il gardera seulement son outro."
        )
        target = "intro 35-70 mots, outro 35-70 mots"
    elif break_type == "qa":
        role = (
            "INTRO : annonce le temps de questions, mentionne le chat, et contextualise "
            "brièvement avec le thème qui vient d'être travaillé.\n"
            "OUTRO : clôture le temps de questions. Si ce n'est pas la fin de journée, "
            "annonce sobrement ce qui vient après et, si un prochain cours existe, "
            "raccorde vers son thème."
        )
        target = "intro 35-70 mots, outro 35-80 mots"
    elif break_type == "pause_midi":
        role = (
            "INTRO : annonce seulement la pause déjeuner, sobrement.\n"
            "OUTRO : annonce la reprise après la pause déjeuner et raccorde vers le prochain thème."
        )
        target = "intro 35-70 mots, outro 45-90 mots"
    else:
        role = (
            "INTRO : annonce uniquement la pause. Reste court.\n"
            "OUTRO : annonce que la pause est terminée et raccorde vers le prochain cours."
        )
        target = "intro 20-45 mots, outro 35-80 mots"

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
INTRO DÉJÀ PORTÉE PAR LE FICHIER PRÉCÉDENT : {"oui" if intro_owned_by_previous else "non"}

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
- Si TRANSITION SENSIBLE ÉTÉ/HIVER vaut oui, l'outro ne doit jamais annoncer
  l'élément suivant : ni prochain cours, ni pause déjeuner, ni reprise immédiate,
  ni thème à venir. Le fichier doit rester valable si l'ordre change.
- Si INTRO DÉJÀ PORTÉE PAR LE FICHIER PRÉCÉDENT vaut oui, mets exactement
  "intro": "" dans le JSON. Ne recrée aucune intro de pause.
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
