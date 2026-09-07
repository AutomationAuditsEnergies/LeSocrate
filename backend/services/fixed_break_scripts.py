"""Scripts fixes pour les fichiers Q&A et pauses de la playlist."""

from __future__ import annotations

import re


FIXED_BREAK_SCRIPTS = {
    "qa_9h45_9h55.mp3": {
        "intro": "On prend maintenant dix minutes pour vos questions. Posez-les dans le chat, je les reprends une par une.",
        "outro": "Très bien, on clôt ce temps de questions. On va maintenant prendre dix minutes de pause.",
    },
    "pause_9h55_10h05.mp3": {
        "intro": "On fait maintenant dix minutes de pause. Prenez le temps de souffler et de vous détendre.",
        "outro": "La pause est terminée. On reprend tranquillement le fil du cours.",
    },
    "qa_10h50_11h00.mp3": {
        "intro": "On prend maintenant dix minutes pour vos questions. Vous pouvez les poser dans le chat.",
        "outro": "Très bien, merci pour vos questions. On va maintenant prendre cinq minutes de pause.",
    },
    "pause_11h00_11h05.mp3": {
        "intro": "On fait maintenant une pause de cinq minutes. Profitez-en pour souffler un instant.",
        "outro": "La pause est terminée. On reprend avec la suite du cours.",
    },
    "qa_12h00_12h10.mp3": {
        "intro": "On prend maintenant dix minutes pour vos questions. Posez dans le chat ce que vous voulez clarifier.",
        "outro": "Très bien, on clôt ce temps de questions. Gardez ces repères en tête pour la suite de la journée.",
    },
    "pause_12h10_12h20.mp3": {
        "intro": "On fait maintenant dix minutes de pause. Prenez le temps de souffler.",
        "outro": "On arrive au terme de ce temps de respiration. Gardez simplement le fil pour la suite de la journée.",
    },
    "pause_midi_13h15_14h45.mp3": {
        "intro": "On marque maintenant la pause déjeuner. Prenez le temps de vous reposer et de souffler.",
        "outro": "La pause déjeuner est terminée. On reprend tranquillement la suite de la journée.",
    },
    "qa_13h05_13h15.mp3": {
        "intro": "On prend maintenant dix minutes pour vos questions. Le chat est ouvert, posez ce que vous voulez éclaircir.",
        "outro": "Très bien, on clôt ce temps de questions. Gardez ces repères en tête pour la suite de la journée.",
    },
    "qa_15h45_16h00.mp3": {
        "intro": "On prend maintenant quinze minutes pour vos questions. Posez-les dans le chat, je les reprends dans l'ordre.",
        "outro": "Très bien, merci pour vos questions. On reprend avec la suite du cours.",
    },
    "qa_17h00_17h15.mp3": {
        "intro": "On prend maintenant quinze minutes pour vos questions. Utilisez le chat pour demander les points à clarifier.",
        "outro": "Très bien, on clôt ce temps de questions. On va maintenant prendre dix minutes de pause.",
    },
    "pause_17h15_17h25.mp3": {
        "intro": "On fait maintenant dix minutes de pause. Profitez-en pour souffler avant la dernière partie.",
        "outro": "La pause est terminée. On reprend pour la dernière séquence de la journée.",
    },
    "qa_18h15_18h30.mp3": {
        "intro": "On termine avec quinze minutes de questions. Posez dans le chat les derniers points que vous voulez clarifier.",
        "outro": "Très bien, merci pour vos questions et pour votre attention. On clôture cette journée de formation.",
    },
}


def normalize_break_filename(filename: str) -> str:
    return (filename or "").split("?", 1)[0].rsplit("/", 1)[-1]


def get_fixed_break_script(filename: str, *, intro_owned_by_previous: bool = False) -> dict | None:
    script = FIXED_BREAK_SCRIPTS.get(normalize_break_filename(filename))
    if not script:
        return None
    intro = re.sub(r"\s+", " ", (script.get("intro") or "").strip())
    outro = re.sub(r"\s+", " ", (script.get("outro") or "").strip())
    return {
        "intro": "" if intro_owned_by_previous else intro,
        "outro": outro,
        "handoff": intro,
    }
