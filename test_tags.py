#!/usr/bin/env python3
"""
Test des tags Fish Audio S2-Pro.
Génère un MP3 par tag pour écouter l'effet réel.

Usage:
    cd backend && python ../test_tags.py
    ou depuis la racine avec les variables d'env chargées :
    python test_tags.py
"""

import os
import sys
import requests
from dotenv import load_dotenv

# Charge les variables d'env depuis backend/.env
load_dotenv(os.path.join(os.path.dirname(__file__), "backend", ".env"))

API_KEY   = os.getenv("FISH_AUDIO_API_KEY")
VOICE_ID  = os.getenv("FISH_AUDIO_VOICE_ID", "90a39a3f3c0a45c38502fa1d99dabf96")
API_URL   = "https://api.fish.audio/v1/tts"
OUT_DIR   = "test_tags_output"

os.makedirs(OUT_DIR, exist_ok=True)

# ─── Phrase de référence (sans aucun tag) ───────────────────────────────────
BASE = "Bonjour, voici une phrase de référence, pour comprendre le ton de base de la voix."

# ─── Tests : (nom_fichier, texte_avec_tag) ──────────────────────────────────
TESTS = [
    # -- Référence --
    ("00_reference",
     BASE),

    # -- Tags de rythme --
    ("01_pause",
     "On avance sur un point important. [pause] Et maintenant on continue."),

    ("02_sigh",
     "[sigh] Voilà, c'est exactement ce genre de situation qu'on rencontre souvent."),

    ("03_inhale",
     "[inhale] Ce qui va suivre est vraiment essentiel à comprendre."),

    ("04_exhale",
     "Voilà, on a fait le tour de cette notion. [exhale] On peut passer à la suite."),

    ("05_breath",
     "Le client arrive, il pose sa question. [breath] Et vous, qu'est-ce que vous répondez ?"),

    # -- Tags émotionnels courts --
    ("06_whisper",
     "[whisper] Et là, entre nous, c'est souvent là que tout se joue."),

    ("07_emphasis",
     "[emphasis] Ce point est absolument non négociable dans la relation client."),

    ("08_excited",
     "[excited] Et les résultats, ils sont vraiment au-delà des attentes !"),

    ("09_calm",
     "[calm] Prenez le temps de bien assimiler ce que l'on vient de voir ensemble."),

    ("10_laugh",
     "[laugh] Ha ha, oui, ça paraît évident comme ça, mais sur le terrain c'est une autre histoire."),

    ("11_gasp",
     "[gasp] Oh, vous voyez ce que je veux dire ? C'est exactement ça le problème."),

    # -- Tags libres (langage naturel) --
    ("12_speaking_with_conviction",
     "[speaking with conviction] Les équipes qui réussissent, c'est celles qui ont une vraie culture du feedback."),

    ("13_slightly_amused",
     "[slightly amused] Bon, disons que cette réunion de trois heures aurait pu être un email."),

    ("14_as_if_sharing_a_secret",
     "[as if sharing a secret] Ce que je vais vous dire maintenant, peu de gens le font vraiment sur le terrain."),

    ("15_building_anticipation",
     "[building anticipation] Et la suite, vous ne l'avez pas encore vue venir..."),

    ("16_warm_and_reassuring",
     "[warm and reassuring] Ne vous inquiétez pas, vous allez progresser naturellement avec la pratique."),

    ("17_speaking_slowly_and_clearly",
     "[speaking slowly and clearly] Retenez bien ceci : chaque interaction compte."),

    ("18_with_authority",
     "[with authority] Dans un contexte de gestion de crise, il n'y a pas de place pour l'improvisation."),

    ("19_gently",
     "[gently] Si jamais vous vous sentez bloqué, c'est tout à fait normal à ce stade."),

    # -- Tags libres inventés (pour voir si S2-Pro les interprète) --
    ("20_pensively",
     "[pensively] C'est une question qui mérite qu'on y réfléchisse vraiment."),

    ("21_with_enthusiasm",
     "[with enthusiasm] Ce module va transformer votre façon d'aborder les entretiens !"),

    ("22_matter_of_factly",
     "[matter-of-factly] Les faits sont là : 80% des problèmes viennent de la communication."),
]


def tts(text, filename):
    payload = {
        "text": text,
        "reference_id": VOICE_ID,
        "temperature": 0.7,
        "top_p": 0.7,
        "prosody": {"speed": 0.95, "volume": 0, "normalize_loudness": True},
        "chunk_length": 300,
        "normalize": False,
        "format": "mp3",
        "mp3_bitrate": 128,
        "latency": "balanced",
    }
    headers = {
        "model": "s2-pro",
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    r = requests.post(API_URL, json=payload, headers=headers, timeout=60)
    if r.status_code != 200:
        print(f"  ✗ ERREUR {r.status_code}: {r.text[:200]}")
        return False
    path = os.path.join(OUT_DIR, f"{filename}.mp3")
    with open(path, "wb") as f:
        f.write(r.content)
    print(f"  ✓ {path}  ({len(r.content)//1024} Ko)")
    return True


def main():
    if not API_KEY:
        print("❌ FISH_AUDIO_API_KEY non trouvée. Lance depuis backend/ ou charge le .env.")
        sys.exit(1)

    print(f"🎙  Fish Audio S2-Pro — test de {len(TESTS)} tags")
    print(f"   Voix : {VOICE_ID}")
    print(f"   Dossier de sortie : {OUT_DIR}/\n")

    ok = 0
    for name, text in TESTS:
        tag_label = name.split("_", 1)[1].replace("_", " ")
        print(f"→ [{tag_label}]")
        print(f"   \"{text[:80]}{'...' if len(text)>80 else ''}\"")
        if tts(text, name):
            ok += 1

    print(f"\n{'='*50}")
    print(f"Générés : {ok}/{len(TESTS)}")
    print(f"Écoute : open {OUT_DIR}/  (ou ls {OUT_DIR}/)")


if __name__ == "__main__":
    main()
