"""
Génère tous les vocaux Q&A et Pauses pour 2 jours de formation.
Structure : 10s silence → intro TTS → silence → outro TTS (20s avant la fin) → padding exact.
"""

import io
import os
import time
import requests
from dotenv import load_dotenv
from pydub import AudioSegment

load_dotenv("backend/.env")

FISH_API_KEY = os.getenv("FISH_AUDIO_API_KEY")
FISH_VOICE_ID = os.getenv("FISH_AUDIO_VOICE_ID", "90a39a3f3c0a45c38502fa1d99dabf96")

# ─── Playlist Q&A et Pauses ──────────────────────────────────────────────────

QA_SLOTS = [
    ("qa_9h45_9h55.mp3", 600),
    ("qa_10h50_11h00.mp3", 600),
    ("qa_12h00_12h10.mp3", 600),
    ("qa_13h05_13h15.mp3", 600),
    ("qa_15h45_16h00.mp3", 900),
    ("qa_17h00_17h15.mp3", 900),
    ("qa_18h15_18h30.mp3", 900),
]

PAUSE_SLOTS = [
    ("pause_9h55_10h05.mp3", 600),
    ("pause_11h00_11h05.mp3", 300),
    ("pause_12h10_12h20.mp3", 600),
    ("pause_midi_13h15_14h45.mp3", 5400),
    ("pause_17h15_17h25.mp3", 600),
]

# ─── Variantes de phrases ────────────────────────────────────────────────────

QA_INTROS = [
    "C'est le moment pour vos questions. N'hésitez pas à poser tout ce que vous voulez dans le chat, je serai ravi d'y répondre.",
    "On passe maintenant à une séance de questions-réponses. Si vous avez des interrogations, c'est le moment, posez-les dans le chat.",
    "Très bien, on ouvre maintenant un temps d'échange. Posez toutes vos questions dans le chat, on est là pour ça.",
    "C'est l'heure des questions. Profitez de ce moment pour poser tout ce qui vous passe par la tête dans le chat.",
    "On fait une petite pause dans le cours pour répondre à vos questions. Allez-y, le chat est ouvert, posez tout ce que vous voulez.",
    "C'est le moment de vos questions. N'hésitez surtout pas, il n'y a pas de question bête, posez tout dans le chat.",
    "On va prendre un moment pour échanger. Si vous avez des questions, des doutes, des choses à éclaircir, c'est maintenant, dans le chat.",
]

QA_OUTROS = [
    "Très bien, la séance de questions-réponses est maintenant terminée. J'espère que vous avez pu poser toutes vos questions. On reprend le cours.",
    "Voilà, on clôture cette session de questions. Merci pour vos questions, elles étaient très pertinentes. On continue.",
    "C'est la fin de ce temps d'échange. J'espère avoir répondu à toutes vos interrogations. On reprend.",
    "La séance de questions-réponses touche à sa fin. Si vous avez d'autres questions, n'hésitez pas à les noter pour la prochaine session. On continue le cours.",
    "Très bien, on va s'arrêter là pour les questions. Merci à tous pour votre participation. On reprend le cours ensemble.",
    "Voilà, cette session de questions est terminée. J'espère que ça vous a aidé à y voir plus clair. On continue.",
    "On termine ce temps de questions-réponses. Merci pour vos questions, on reprend maintenant la suite du cours.",
]

def get_pause_intro(duration_s):
    """Retourne une intro de pause avec la durée indiquée."""
    minutes = duration_s // 60
    variants = [
        f"On va faire une pause de {minutes} minutes. Profitez-en pour vous détendre et vous reposer.",
        f"C'est l'heure d'une petite pause de {minutes} minutes. Prenez le temps de souffler, de vous étirer, on se retrouve juste après.",
        f"On s'accorde une pause de {minutes} minutes. Reposez-vous bien, on reprend très bientôt.",
        f"Très bien, on fait une pause de {minutes} minutes. Profitez-en pour boire un verre d'eau, prendre l'air.",
        f"On va maintenant prendre une pause de {minutes} minutes. Détendez-vous, on se retrouve après.",
    ]
    return variants


PAUSE_INTROS = None  # Remplacé par get_pause_intro()

PAUSE_OUTROS = [
    "La pause est maintenant terminée. J'espère que vous en avez bien profité. On reprend le cours.",
    "Très bien, la pause est finie. On se retrouve pour la suite, j'espère que vous êtes bien reposés.",
    "Voilà, la pause touche à sa fin. On va reprendre ensemble, j'espère que vous avez pu souffler un peu.",
    "C'est la fin de la pause. On reprend le cours, j'espère que vous êtes prêts pour la suite.",
    "La pause est terminée, on reprend. J'espère que ce petit moment de repos vous a fait du bien.",
]


# ─── TTS ─────────────────────────────────────────────────────────────────────

def tts_text(text):
    """Convertit un texte en audio via Fish Audio S2-Pro."""
    payload = {
        "text": text,
        "reference_id": FISH_VOICE_ID,
        "temperature": 0.9,
        "top_p": 0.7,
        "prosody": {"speed": 0.95, "volume": 0, "normalize_loudness": True},
        "chunk_length": 300,
        "normalize": False,
        "format": "mp3",
        "mp3_bitrate": 128,
        "latency": "normal",
    }
    headers = {
        "model": "s2-pro",
        "Authorization": f"Bearer {FISH_API_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(5):
        try:
            resp = requests.post("https://api.fish.audio/v1/tts", json=payload, headers=headers)
            if resp.status_code == 429:
                wait = 3 * (attempt + 1)
                print(f"    ⏳ Rate limit, attente {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                raise Exception(f"Erreur Fish Audio ({resp.status_code}): {resp.text[:200]}")
            time.sleep(0.5)
            return resp.content
        except Exception as e:
            if attempt < 4:
                time.sleep(2)
            else:
                raise
    raise Exception("Échec après 5 tentatives")


# ─── Construction d'un vocal ─────────────────────────────────────────────────

def build_vocal(intro_text, outro_text, total_duration_s, outro_offset_s=20):
    """
    Construit un vocal complet :
    - 10s silence
    - intro TTS
    - silence
    - outro TTS (outro_offset_s secondes avant la fin)
    - padding exact à total_duration_s
    """
    # Générer les audios TTS
    print(f"    🎤 Intro: \"{intro_text[:50]}...\"")
    intro_bytes = tts_text(intro_text)
    intro_audio = AudioSegment.from_mp3(io.BytesIO(intro_bytes)).fade_out(150)

    print(f"    🎤 Outro: \"{outro_text[:50]}...\"")
    outro_bytes = tts_text(outro_text)
    outro_audio = AudioSegment.from_mp3(io.BytesIO(outro_bytes)).fade_out(150)

    target_ms = total_duration_s * 1000

    # Construction : 10s silence + intro + silence milieu + outro + silence fin
    start_silence = AudioSegment.silent(duration=10000)

    # Calculer le silence du milieu
    # outro doit commencer à (target_ms - outro_offset_s*1000 - len(outro))
    outro_start_ms = target_ms - (outro_offset_s * 1000) - len(outro_audio)
    intro_end_ms = 10000 + len(intro_audio)
    mid_silence_ms = max(outro_start_ms - intro_end_ms, 1000)

    mid_silence = AudioSegment.silent(duration=mid_silence_ms)

    full_audio = start_silence + intro_audio + mid_silence + outro_audio

    # Padding ou troncature à la durée exacte
    if len(full_audio) < target_ms:
        full_audio = full_audio + AudioSegment.silent(duration=target_ms - len(full_audio))
    elif len(full_audio) > target_ms:
        full_audio = full_audio[:target_ms]

    # Export
    output = io.BytesIO()
    full_audio.export(output, format="mp3", bitrate="128k")
    return output.getvalue()


# ─── Pipeline ────────────────────────────────────────────────────────────────

def generate_all(output_dir="output_qa_pauses"):
    """Génère tous les vocaux Q&A et Pauses pour 2 jours."""

    print("=" * 60)
    print("  GÉNÉRATION Q&A + PAUSES — 2 jours de formation")
    print("=" * 60)

    for jour in [1, 2]:
        jour_dir = os.path.join(output_dir, f"jour{jour}")
        os.makedirs(jour_dir, exist_ok=True)

        print(f"\n{'='*60}")
        print(f"  JOUR {jour}")
        print(f"{'='*60}")

        # ── Q&A ──────────────────────────────────────────────────────
        print(f"\n  📋 Génération des Q&A")
        for i, (filename, duration) in enumerate(QA_SLOTS):
            print(f"\n  ── {filename} ({duration//60}min) ──")
            intro = QA_INTROS[(i + (jour - 1) * len(QA_SLOTS)) % len(QA_INTROS)]
            outro = QA_OUTROS[(i + (jour - 1) * len(QA_SLOTS)) % len(QA_OUTROS)]

            audio_bytes = build_vocal(intro, outro, duration)
            filepath = os.path.join(jour_dir, filename)
            with open(filepath, "wb") as f:
                f.write(audio_bytes)
            print(f"    ✅ {filename} généré ({duration//60}min)")

        # ── Pauses ───────────────────────────────────────────────────
        print(f"\n  📋 Génération des Pauses")
        for i, (filename, duration) in enumerate(PAUSE_SLOTS):
            print(f"\n  ── {filename} ({duration//60}min) ──")
            pause_intros = get_pause_intro(duration)
            intro = pause_intros[(i + (jour - 1) * len(PAUSE_SLOTS)) % len(pause_intros)]
            outro = PAUSE_OUTROS[(i + (jour - 1) * len(PAUSE_SLOTS)) % len(PAUSE_OUTROS)]

            audio_bytes = build_vocal(intro, outro, duration)
            filepath = os.path.join(jour_dir, filename)
            with open(filepath, "wb") as f:
                f.write(audio_bytes)
            print(f"    ✅ {filename} généré ({duration//60}min)")

    print(f"\n{'='*60}")
    print(f"  TERMINÉ — Fichiers dans {output_dir}/jour1/ et {output_dir}/jour2/")
    print(f"{'='*60}")


if __name__ == "__main__":
    generate_all()
