#!/usr/bin/env python3
"""Mesure le débit réel (mots/minute) de Fish Audio S2-Pro.

But : remplacer la constante de calibration supposée (192 wpm) par une mesure
réelle, faite sur ~1h de script de formation TTS-ready, au rythme exact de la
formation (speed=0.90). Utilise l'endpoint with-timestamp pour récupérer la
durée audio exacte et le découpage mot à mot.

Sortie : fish_1h_audio.mp3 (audio généré) + fish_wpm_report.json (les stats).
"""
import base64
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
ENV = ROOT / "backend" / ".env"
SRC = ROOT / "courstxt" / "Module1_accueil_boulangerie_TTS_ready.txt"
OUT_AUDIO = ROOT / "fish_1h_audio.mp3"
OUT_REPORT = ROOT / "fish_wpm_report.json"

API_URL = "https://api.fish.audio/v1/tts/stream/with-timestamp"
MODEL = "s2-pro"
SPEED = 0.90              # rythme réel de la formation (_DEFAULT_TTS_SPEED)
TARGET_SEC = 3600         # on s'arrête dès qu'on a ~1h d'audio
BATCH_WORDS = 4000        # mots parlés par requête (~ taille d'un bloc cours)

TAG_RE = re.compile(r"\[[^\[\]\n]{1,50}\]")


def load_env(key):
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key + "="):
            return line[len(key) + 1:].strip().strip('"').strip("'")
    return None


def spoken_words(text):
    """Compte les mots réellement parlés, hors tags [pause]/[emphasis]/..."""
    return len(TAG_RE.sub(" ", text).split())


def load_paragraphs():
    raw = SRC.read_text(encoding="utf-8")
    paras = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    # On saute la ligne placeholder « [Le texte de base sera ici - ...] »
    return [p for p in paras if not p.startswith("[Le texte de base")]


def build_batches(paragraphs, batch_words):
    """Regroupe les paragraphes en lots de ~batch_words mots, sans couper
    un paragraphe en deux."""
    batches, cur, cur_w = [], [], 0
    for p in paragraphs:
        w = spoken_words(p)
        if cur and cur_w + w > batch_words:
            batches.append("\n\n".join(cur))
            cur, cur_w = [], 0
        cur.append(p)
        cur_w += w
    if cur:
        batches.append("\n\n".join(cur))
    return batches


def synthesize(text, api_key, voice_id):
    """Appelle l'endpoint with-timestamp. Retourne (audio_bytes, duration_sec,
    fish_word_count) — fish_word_count = nb de mots réellement vocalisés
    d'après les segments d'alignement."""
    payload = {
        "text": text,
        "reference_id": voice_id,
        "temperature": 0.7,
        "top_p": 0.7,
        "prosody": {"speed": SPEED, "volume": 0, "normalize_loudness": True},
        "chunk_length": 300,
        "normalize": False,
        "format": "mp3",
        "mp3_bitrate": 128,
        "latency": "balanced",
    }
    headers = {
        "model": MODEL,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        API_URL, json=payload, headers=headers, stream=True, timeout=(30, 900)
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Fish API {resp.status_code}: {resp.text[:300]}")

    audio_chunks = []
    align = {}  # chunk_seq -> {offset, audio_duration, n_segments} (latest-wins)
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        ev = json.loads(line[6:])
        if ev.get("audio_base64"):
            audio_chunks.append(base64.b64decode(ev["audio_base64"]))
        if ev.get("alignment"):
            a = ev["alignment"]
            align[ev["chunk_seq"]] = {
                "offset": ev["chunk_audio_offset_sec"],
                "audio_duration": a["audio_duration"],
                "n_segments": len(a["segments"]),
            }

    audio = b"".join(audio_chunks)
    if not align:
        raise RuntimeError("Aucun alignement reçu — durée non mesurable")
    duration = max(v["offset"] + v["audio_duration"] for v in align.values())
    fish_words = sum(v["n_segments"] for v in align.values())
    return audio, duration, fish_words


def main():
    api_key = load_env("FISH_AUDIO_API_KEY")
    voice_id = load_env("FISH_AUDIO_VOICE_ID") or "90a39a3f3c0a45c38502fa1d99dabf96"
    if not api_key:
        sys.exit("FISH_AUDIO_API_KEY absente du .env")

    paragraphs = load_paragraphs()
    batches = build_batches(paragraphs, BATCH_WORDS)
    total_available = sum(spoken_words(p) for p in paragraphs)
    print(
        f"Source : {SRC.name} — {len(paragraphs)} paragraphes, "
        f"{total_available} mots parlés, {len(batches)} batches de ~{BATCH_WORDS} mots",
        flush=True,
    )

    all_audio = []
    total_dur = 0.0
    total_input_words = 0
    total_fish_words = 0
    per_batch = []

    for i, batch in enumerate(batches, 1):
        in_words = spoken_words(batch)
        print(
            f"[batch {i}/{len(batches)}] {in_words} mots, {len(batch)} chars — envoi…",
            flush=True,
        )
        t0 = time.time()
        audio, dur, fish_words = synthesize(batch, api_key, voice_id)
        elapsed = time.time() - t0

        all_audio.append(audio)
        total_dur += dur
        total_input_words += in_words
        total_fish_words += fish_words
        wpm = in_words / (dur / 60) if dur else 0.0
        per_batch.append({
            "batch": i,
            "input_spoken_words": in_words,
            "fish_segment_words": fish_words,
            "audio_duration_sec": round(dur, 2),
            "wpm": round(wpm, 1),
            "gen_time_sec": round(elapsed, 1),
        })
        print(
            f"   → {dur:.1f}s audio ({dur / 60:.2f} min) · wpm={wpm:.1f} · "
            f"généré en {elapsed:.0f}s · cumul {total_dur / 60:.1f} min",
            flush=True,
        )
        if total_dur >= TARGET_SEC:
            print("   ✓ cible ~1h atteinte, on s'arrête.", flush=True)
            break

    OUT_AUDIO.write_bytes(b"".join(all_audio))

    overall_wpm = total_input_words / (total_dur / 60)
    fish_wpm = total_fish_words / (total_dur / 60)
    words_per_hour = total_input_words / (total_dur / 3600)

    report = {
        "speed": SPEED,
        "model": MODEL,
        "voice_id": voice_id,
        "source_file": SRC.name,
        "batches_used": len(per_batch),
        "total_audio_sec": round(total_dur, 2),
        "total_audio_min": round(total_dur / 60, 2),
        "total_input_spoken_words": total_input_words,
        "total_fish_segment_words": total_fish_words,
        "wpm_input_basis": round(overall_wpm, 2),
        "wpm_fish_segments_basis": round(fish_wpm, 2),
        "words_per_hour": round(words_per_hour, 1),
        "pipeline_assumed_wpm": 192,
        "per_batch": per_batch,
    }
    OUT_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 60, flush=True)
    print(f"RÉSULTAT — Fish Audio S2-Pro @ speed={SPEED}", flush=True)
    print("=" * 60, flush=True)
    print(f"  Audio total      : {total_dur / 60:.2f} min ({total_dur:.0f}s)", flush=True)
    print(f"  Mots parlés      : {total_input_words} (input) / {total_fish_words} (segments Fish)", flush=True)
    print(f"  wpm réel         : {overall_wpm:.1f} mots/min  (pipeline suppose 192)", flush=True)
    print(f"  Mots / heure     : {words_per_hour:.0f}", flush=True)
    print(f"  Audio   → {OUT_AUDIO.name}", flush=True)
    print(f"  Rapport → {OUT_REPORT.name}", flush=True)


if __name__ == "__main__":
    main()
