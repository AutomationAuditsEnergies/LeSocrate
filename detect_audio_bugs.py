#!/usr/bin/env python3
"""
Détecte les passages où la voix TTS change de caractère (timbre, pitch anormal).
Utilise les MFCCs (empreinte vocale) + pitch + centroïde spectral,
uniquement sur les frames vocalisées (ignore silences, début et fin de fichier).

Usage:
    python detect_audio_bugs.py fichier.mp3
    python detect_audio_bugs.py dossier/         (scanne tous les MP3)
    python detect_audio_bugs.py fichier.mp3 --seuil 3.5 --duree-min 1.5
"""

import sys
import os
import argparse
import numpy as np
import librosa


def fmt(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m:02d}m{s:02d}s"


def analyser_fichier(chemin, seuil=3.5, duree_min=1.5, ignorer_debut=30, ignorer_fin=30):
    """
    Analyse un fichier MP3 et retourne les timestamps des bugs vocaux.

    seuil         : sensibilité (écarts-types) — plus bas = plus sensible
    duree_min     : durée minimale (s) pour signaler un segment
    ignorer_debut : secondes à ignorer au début (silence intentionnel + intro)
    ignorer_fin   : secondes à ignorer à la fin (padding)
    """
    print(f"\n→ Analyse : {os.path.basename(chemin)}")

    y, sr = librosa.load(chemin, sr=22050, mono=True)
    hop_length = 512  # ~23ms par frame
    duree_totale = librosa.get_duration(y=y, sr=sr)

    print(f"   Durée totale : {fmt(duree_totale)}")
    print(f"   Zone analysée : {fmt(ignorer_debut)} → {fmt(duree_totale - ignorer_fin)}")

    # ── Masque de silence ────────────────────────────────────────────────────
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    seuil_silence = np.percentile(rms, 20)
    voiced_mask = rms > (seuil_silence * 3)

    # ── Features vocales ────────────────────────────────────────────────────
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, hop_length=hop_length)
    centroide = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop_length)[0]
    pitch = librosa.yin(y, fmin=60, fmax=400, hop_length=hop_length)

    n_frames = min(len(voiced_mask), mfcc.shape[1], len(centroide), len(pitch))

    # ── Masque de zone valide (ignore début et fin) ──────────────────────────
    frames_temps = librosa.frames_to_time(np.arange(n_frames), sr=sr, hop_length=hop_length)
    zone_mask = (frames_temps >= ignorer_debut) & (frames_temps <= (duree_totale - ignorer_fin))

    # ── Calcul des anomalies ─────────────────────────────────────────────────
    suspicion = np.zeros(n_frames, dtype=float)

    # Stats calculées uniquement sur les frames vocalisées dans la zone valide
    analyse_mask = voiced_mask[:n_frames] & zone_mask
    voiced_indices = np.where(analyse_mask)[0]

    if len(voiced_indices) < 50:
        print("   ⚠ Pas assez de frames vocalisées pour analyser.")
        return []

    # MFCCs — timbre vocal (13 coefficients)
    for i in range(mfcc.shape[0]):
        coef = mfcc[i, :n_frames]
        vals = coef[voiced_indices]
        median = np.median(vals)
        std = np.std(vals)
        if std < 1e-6:
            continue
        z = np.abs((coef - median) / std)
        suspicion += (z > seuil) * analyse_mask

    # Centroïde spectral — aigus/graves anormaux (poids double)
    c_vals = centroide[:n_frames][voiced_indices]
    c_median = np.median(c_vals)
    c_std = np.std(c_vals)
    if c_std > 1e-6:
        z_c = np.abs((centroide[:n_frames] - c_median) / c_std)
        suspicion += (z_c > seuil) * analyse_mask * 2

    # Pitch — hauteur fondamentale (poids double)
    p_vals = pitch[:n_frames][voiced_indices]
    p_vals_voiced = p_vals[p_vals > 0]
    if len(p_vals_voiced) > 10:
        p_median = np.median(p_vals_voiced)
        p_std = np.std(p_vals_voiced)
        if p_std > 1e-6:
            z_p = np.abs((pitch[:n_frames] - p_median) / p_std)
            suspicion += (z_p > seuil) * analyse_mask * 2

    # ── Seuil global de bug ──────────────────────────────────────────────────
    seuil_bug = 2  # points cumulés pour marquer une frame
    bug_frames = suspicion > seuil_bug

    # ── Regroupement en segments continus ───────────────────────────────────
    bugs = []
    en_bug = False
    debut_bug = 0.0
    score_max = 0.0

    for i in range(n_frames):
        t = float(frames_temps[i])
        is_bug = bool(bug_frames[i])
        score = float(suspicion[i])

        if is_bug and not en_bug:
            en_bug = True
            debut_bug = t
            score_max = score
        elif is_bug and en_bug:
            score_max = max(score_max, score)
        elif not is_bug and en_bug:
            duree = t - debut_bug
            if duree >= duree_min:
                severity = 3 if score_max > 15 else 2 if score_max > 8 else 1
                bugs.append((debut_bug, t, severity))
            en_bug = False
            score_max = 0.0

    if en_bug and n_frames > 0:
        duree = float(frames_temps[-1]) - debut_bug
        if duree >= duree_min:
            severity = 3 if score_max > 15 else 2 if score_max > 8 else 1
            bugs.append((debut_bug, float(frames_temps[-1]), severity))

    # ── Affichage ────────────────────────────────────────────────────────────
    print(f"   Bugs détectés : {len(bugs)}")

    if not bugs:
        print("   ✓ Aucune anomalie vocale détectée.")
    else:
        print()
        for debut, fin, severity in bugs:
            icone = "🔴" if severity == 3 else "⚠⚠" if severity == 2 else "⚠ "
            print(f"   {icone}  {fmt(debut)} → {fmt(fin)}  (durée {fmt(fin - debut)}, sévérité {severity}/3)")

    return bugs


def main():
    parser = argparse.ArgumentParser(description="Détecte les bugs de voix TTS dans des fichiers MP3")
    parser.add_argument("cible", help="Fichier MP3 ou dossier à analyser")
    parser.add_argument("--seuil", type=float, default=3.5,
        help="Sensibilité : écarts-types (défaut: 3.5 — baisser pour plus de résultats)")
    parser.add_argument("--duree-min", type=float, default=1.5,
        help="Durée minimale d'un bug en secondes (défaut: 1.5s)")
    parser.add_argument("--ignorer-debut", type=float, default=30,
        help="Secondes à ignorer au début de chaque fichier (défaut: 30s)")
    parser.add_argument("--ignorer-fin", type=float, default=30,
        help="Secondes à ignorer à la fin de chaque fichier (défaut: 30s)")
    args = parser.parse_args()

    if os.path.isfile(args.cible):
        fichiers = [args.cible]
    elif os.path.isdir(args.cible):
        fichiers = sorted([
            os.path.join(args.cible, f)
            for f in os.listdir(args.cible)
            if f.endswith(".mp3")
        ])
        if not fichiers:
            print(f"Aucun fichier MP3 trouvé dans {args.cible}")
            sys.exit(1)
        print(f"{len(fichiers)} fichier(s) MP3 trouvé(s) dans {args.cible}")
    else:
        print(f"Erreur : '{args.cible}' n'existe pas.")
        sys.exit(1)

    resultats = {}
    for fichier in fichiers:
        bugs = analyser_fichier(
            fichier,
            seuil=args.seuil,
            duree_min=args.duree_min,
            ignorer_debut=args.ignorer_debut,
            ignorer_fin=args.ignorer_fin,
        )
        resultats[os.path.basename(fichier)] = bugs

    print("\n" + "=" * 60)
    print("RÉSUMÉ")
    print("=" * 60)
    total = sum(len(b) for b in resultats.values())
    print(f"Total anomalies : {total}\n")
    for nom, bugs in resultats.items():
        if bugs:
            print(f"  {nom} : {len(bugs)} bug(s)")
            for debut, fin, sev in bugs:
                print(f"    → {fmt(debut)} – {fmt(fin)}  (sévérité {sev}/3)")
        else:
            print(f"  {nom} : ✓ RAS")


if __name__ == "__main__":
    main()
