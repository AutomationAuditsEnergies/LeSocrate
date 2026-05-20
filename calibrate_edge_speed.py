#!/usr/bin/env python3
"""Calibre la vitesse d'Edge TTS sur le débit réel de Fish Audio.

But : la "voix de synthèse" gratuite (Edge TTS) doit débiter autant de mots
par minute que Fish Audio (mesuré par measure_fish_wpm.py), pour servir de
voix de remplacement fidèle au rythme de la formation.

Edge TTS n'honore pas les tags [pause] : on calibre donc sur le texte nettoyé
(mots réellement parlés). Cible = wpm Fish, qui inclut déjà ses silences ;
résultat : Edge parle en continu mais remplit la même durée.

Sortie : edge_calibration_report.json
"""
import asyncio
import json
import re
import sys
from pathlib import Path

import edge_tts

import measure_fish_wpm as fish  # réutilise TAG_RE / load_paragraphs / build_batches

ROOT = Path(__file__).resolve().parent
REPORT_FISH = ROOT / "fish_wpm_report.json"
OUT_REPORT = ROOT / "edge_calibration_report.json"
VOICE = "fr-FR-DeniseNeural"   # défaut EDGE_TTS_VOICE de basic_tts_service
SAMPLE_WORDS = 4000
SUBCHUNK_CHARS = 3500          # Edge TTS : on découpe les longs textes


def strip_tags(text):
    """Retire les tags [pause]/[calm]/... — Edge TTS les vocaliserait."""
    return re.sub(r"[ \t]{2,}", " ", fish.TAG_RE.sub("", text)).strip()


def split_chars(text, max_chars):
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks, cur = [], ""
    for s in sentences:
        if cur and len(cur) + len(s) + 1 > max_chars:
            chunks.append(cur)
            cur = ""
        cur = (cur + " " + s).strip() if cur else s
    if cur:
        chunks.append(cur)
    return chunks


async def edge_measure(text, rate):
    """Génère via edge-tts. Retourne (n_boundary_words, duration_sec).

    edge-tts 7.x émet des événements *Boundary (Word/Sentence) avec offset et
    duration en unités 100 ns. La durée = fin du dernier boundary ; le nombre
    de mots = somme des mots des textes de boundary (contrôle croisé)."""
    total_words = 0
    total_dur = 0.0
    for sub in split_chars(text, SUBCHUNK_CHARS):
        comm = edge_tts.Communicate(sub, voice=VOICE, rate=rate)
        last_end = 0
        n = 0
        async for chunk in comm.stream():
            if str(chunk.get("type", "")).endswith("Boundary"):
                n += len(str(chunk.get("text", "")).split())
                end = chunk["offset"] + chunk["duration"]
                if end > last_end:
                    last_end = end
        total_words += n
        total_dur += last_end / 1e7
    return total_words, total_dur


def main():
    if not REPORT_FISH.exists():
        sys.exit("fish_wpm_report.json manquant — lance d'abord measure_fish_wpm.py")
    fish_report = json.loads(REPORT_FISH.read_text(encoding="utf-8"))
    target_wpm = fish_report["wpm_input_basis"]
    print(f"Cible : {target_wpm} wpm — Fish Audio @ speed={fish_report['speed']}", flush=True)

    paras = fish.load_paragraphs()
    batch = fish.build_batches(paras, SAMPLE_WORDS)[0]
    clean = strip_tags(batch)
    n_input = len(clean.split())
    print(f"Échantillon : {n_input} mots (Module1, texte nettoyé sans tags)\n", flush=True)

    # ── 1. Débit natif d'Edge TTS (rate +0%) ────────────────────────────────
    print("[1] Mesure Edge TTS natif (rate +0%)…", flush=True)
    n_wb, dur = asyncio.run(edge_measure(clean, "+0%"))
    native_wpm = n_input / (dur / 60)
    print(
        f"    → {dur:.1f}s ({dur / 60:.2f} min) · {n_wb} mots détectés · "
        f"wpm natif = {native_wpm:.1f}",
        flush=True,
    )

    # ── 2. Multiplicateur de vitesse cible ──────────────────────────────────
    m = target_wpm / native_wpm
    rate_pct = round((m - 1) * 100)          # edge-tts : granularité 1 %
    rate = f"{rate_pct:+d}%"
    speed_val = round(1 + rate_pct / 100, 2)  # valeur pour BASIC_TTS_SPEED
    print(
        f"\n[2] Pour {target_wpm} wpm → BASIC_TTS_SPEED={speed_val}  "
        f"(rate edge-tts {rate})",
        flush=True,
    )

    # ── 3. Vérification : on régénère à la vitesse calibrée ──────────────────
    print(f"\n[3] Vérification — régénération à {rate}…", flush=True)
    n_wb2, dur2 = asyncio.run(edge_measure(clean, rate))
    verified_wpm = n_input / (dur2 / 60)
    err = (verified_wpm - target_wpm) / target_wpm * 100
    print(
        f"    → {dur2:.1f}s ({dur2 / 60:.2f} min) · wpm vérifié = {verified_wpm:.1f} "
        f"(écart {err:+.1f}% vs cible)",
        flush=True,
    )

    report = {
        "target_wpm_fish": target_wpm,
        "fish_speed": fish_report["speed"],
        "edge_voice": VOICE,
        "sample_words": n_input,
        "edge_native_wpm": round(native_wpm, 2),
        "edge_native_duration_sec": round(dur, 2),
        "recommended_basic_tts_speed": speed_val,
        "recommended_edge_rate": rate,
        "verified_wpm": round(verified_wpm, 2),
        "verified_duration_sec": round(dur2, 2),
        "verification_error_pct": round(err, 2),
    }
    OUT_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 60, flush=True)
    print("RÉSULTAT — Calibration Edge TTS", flush=True)
    print("=" * 60, flush=True)
    print(f"  Voix Edge          : {VOICE}", flush=True)
    print(f"  wpm natif (1.0)    : {native_wpm:.1f}", flush=True)
    print(f"  Cible (Fish)       : {target_wpm}", flush=True)
    print(f"  → BASIC_TTS_SPEED  : {speed_val}   (rate {rate})", flush=True)
    print(f"  wpm vérifié        : {verified_wpm:.1f}  (écart {err:+.1f}%)", flush=True)
    print(f"  Rapport → {OUT_REPORT.name}", flush=True)


if __name__ == "__main__":
    main()
