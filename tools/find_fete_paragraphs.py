"""Identifie les paragraphes à supprimer dans les 2 cours (passages de fête)."""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path("/Users/amelle/Desktop/SocrateReprise/LeSocrate/courstxt")
FILES = ["formation_jour1.txt", "formation_jour2.txt"]

# Marqueurs qui trahissent un passage « de fête » à supprimer.
MARKERS = re.compile(
    r"\b("
    r"gâteau personnalisé"
    r"|repas de réception"
    r"|produits saisonniers de fin d'année"
    r"|produits d'exception saisonniers?"
    r"|produit d'exception saisonnier"
    r"|produit signature saisonnier"
    r"|produits saisonniers décorés"
    r"|commandes de réception"
    r"|veilles de jours fériés"
    r"|fêt(?:e|es|er|ait|aient|ions|és|ée|ées)"
    r"|célébr"
    r"|réveillon"
    r")\b",
    re.IGNORECASE,
)


def main() -> int:
    for fname in FILES:
        path = ROOT / fname
        text = path.read_text(encoding="utf-8")
        # On découpe en paragraphes (séparés par \n\n)
        paragraphs = text.split("\n\n")
        hits = []
        for i, para in enumerate(paragraphs):
            m = MARKERS.search(para)
            if m:
                hits.append((i, m.group(), para))
        print(f"\n=== {fname} : {len(hits)} paragraphes candidats ===")
        for i, marker, para in hits:
            preview = para.replace("\n", " ")[:220]
            print(f"  [{i:4d}] ({marker:20s}) {preview}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
