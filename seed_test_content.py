"""
seed_test_content.py — Insère des segments de test directement en DB.

Usage :
    python seed_test_content.py <folder_id>

Effet : crée (ou réinitialise) un content_generation_job pour le folder_id
donné, puis insère 18 segments factices (6 sous-parties × 3 passes).
Ne touche pas à Azure, ne fait aucun appel Claude.

Idéal pour tester la modale de script, l'édition de segments (PATCH),
et le polling sans rien générer.
"""

import sys
import os
import json
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "backend", "database", "socrate.db")

MOCK_SUB_PARTS = [
    "Introduction et contexte professionnel",
    "Les fondamentaux théoriques",
    "Méthodes et outils pratiques",
    "Études de cas et mises en situation",
    "Réglementation et cadre légal",
    "Évaluation et certification",
]

MOCK_PASSE_LABELS = ["fondation", "expansion", "enrichissement"]

MOCK_PHRASES = [
    "Ce module aborde les fondamentaux essentiels de cette thématique.",
    "Chaque notion est construite progressivement pour faciliter l'assimilation.",
    "Les exemples concrets viennent illustrer la théorie à chaque étape.",
    "Le formateur insiste sur les points clés à retenir pour la pratique professionnelle.",
    "Des mises en situation permettront de consolider les apprentissages.",
    "Il est important de bien comprendre le contexte avant d'aller plus loin.",
    "Les compétences acquises ici seront réutilisées tout au long de la formation.",
    "Prenez le temps d'assimiler chaque notion avant de passer à la suivante.",
]


def generate_mock_text(passe, sub_part_name, sub_idx):
    label = MOCK_PASSE_LABELS[passe - 1]
    lines = [
        f"Bonjour et bienvenue dans cette partie consacrée à {sub_part_name}.",
        f"Nous abordons ici la {label} de ce module. [SEED TEST — Passe {passe}/3 — Sous-partie {sub_idx + 1}]",
        "",
    ]
    for i, phrase in enumerate(MOCK_PHRASES * 4):
        lines.append(f"{phrase} ({sub_part_name}, itération {i + 1}.)")
    lines += [
        "",
        f"Voilà pour cette passe {passe} dédiée à {sub_part_name}.",
        f"Nous venons de couvrir l'essentiel de la {label}. Passons à la suite.",
    ]
    return "\n".join(lines)


def seed(folder_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Vérifier que le dossier existe et récupérer platform_id
    cur.execute("SELECT platform_id, name FROM cours_folders WHERE id = ?", (folder_id,))
    row = cur.fetchone()
    if not row:
        print(f"❌ Dossier {folder_id} introuvable dans la DB.")
        conn.close()
        sys.exit(1)
    platform_id, folder_name = row
    print(f"📁 Dossier trouvé : {folder_name} (platform {platform_id})")

    program_title = "[TEST] Formation Professionnelle - Seed"
    program_text = "Programme de formation factice généré par seed_test_content.py pour les tests."
    sub_parts_json = json.dumps(MOCK_SUB_PARTS)

    # Supprimer l'ancien job s'il existe
    cur.execute("SELECT id FROM content_generation_jobs WHERE folder_id = ?", (folder_id,))
    old_job = cur.fetchone()
    if old_job:
        print(f"  🗑️  Suppression de l'ancien job (id={old_job[0]}) et ses segments...")
        cur.execute("DELETE FROM content_generation_segments WHERE job_id = ?", (old_job[0],))
        cur.execute("DELETE FROM content_generation_jobs WHERE id = ?", (old_job[0],))
        conn.commit()

    # Créer le job
    cur.execute("""
        INSERT INTO content_generation_jobs
            (folder_id, platform_id, program_text, program_title, sub_parts, status, current_sub_part, current_passe, total_words)
        VALUES (?, ?, ?, ?, ?, 'completed', 5, 3, 0)
    """, (folder_id, platform_id, program_text, program_title, sub_parts_json))
    job_id = cur.lastrowid
    conn.commit()
    print(f"  ✅ Job créé (id={job_id})")

    # Insérer les 18 segments
    total_words = 0
    for sub_idx, sub_part_name in enumerate(MOCK_SUB_PARTS):
        for passe in [1, 2, 3]:
            text = generate_mock_text(passe, sub_part_name, sub_idx)
            word_count = len(text.split())
            total_words += word_count
            cur.execute("""
                INSERT INTO content_generation_segments
                    (job_id, sub_part_index, sub_part_name, passe, status, text_content, word_count)
                VALUES (?, ?, ?, ?, 'completed', ?, ?)
            """, (job_id, sub_idx, sub_part_name, passe, text, word_count))
            print(f"  📝 Sous-partie {sub_idx+1}/6 · Passe {passe}/3 → {word_count} mots")

    # Mettre à jour le total_words
    cur.execute("UPDATE content_generation_jobs SET total_words = ? WHERE id = ?", (total_words, job_id))
    conn.commit()
    conn.close()

    print(f"\n✅ Seed terminé : 18 segments, {total_words} mots au total.")
    print(f"   Ouvre le dossier {folder_id} dans l'interface HR → 'Voir le script'.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage : python seed_test_content.py <folder_id>")
        sys.exit(1)
    try:
        fid = int(sys.argv[1])
    except ValueError:
        print("❌ folder_id doit être un entier.")
        sys.exit(1)
    seed(fid)
