"""Smoke test local pour verifier que gTTS genere bien un MP3.

Usage:
    PYTHONPATH=backend venv/bin/python tools/dev/smoke_gtts.py
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from services.basic_tts_service import convert_to_speech_basic


DEFAULT_TEXT = """
Bonjour, ceci est un test local de la voix gTTS pour la pipeline Le Socrate.
Le but est simple : vérifier que le backend peut transformer un texte court
en fichier MP3 sans passer par Fish Audio. Si vous entendez cette phrase,
le mode gTTS fonctionne au moins sur un exemple isolé.
""".strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parent / "output_gtts_smoke.mp3"),
        help="Chemin du MP3 de sortie.",
    )
    parser.add_argument(
        "--text",
        default=DEFAULT_TEXT,
        help="Texte a convertir en audio.",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=None,
        help="Facteur d'acceleration gTTS. Defaut: BASIC_TTS_SPEED ou 1.12.",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    audio_bytes = convert_to_speech_basic(args.text, lang="fr", speed=args.speed)
    output_path.write_bytes(audio_bytes)

    duration = None
    try:
        from pydub import AudioSegment

        duration = len(AudioSegment.from_mp3(output_path)) / 1000
    except Exception:
        pass

    if duration is None:
        print(f"OK: {output_path} ({len(audio_bytes)} bytes)")
    else:
        print(f"OK: {output_path} ({len(audio_bytes)} bytes, {duration:.1f}s)")


if __name__ == "__main__":
    main()
