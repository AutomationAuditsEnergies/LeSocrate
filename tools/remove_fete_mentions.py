"""Supprime/remplace les mentions de fête et de célébration dans les 2 cours.

Stratégie : substitutions ciblées avec word boundaries, en distinguant :
- « fête » au sens « jour férié / célébration » → remplacer par « jour férié »,
  « pic commercial », « grande occasion », « réception », etc.
- « célébrer / célébration » → remplacer par « valoriser / reconnaître / valorisation ».
- « repas de fête » → « repas de réception » ou « repas exceptionnel ».
- « gâteau de fête » → « gâteau personnalisé ».
- « produits de fête » → « produits saisonniers » ou « produits d'exception ».
- « c'est une vraie fête » (sens figuré) → « c'est un vrai régal ».
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path("/Users/amelle/Desktop/SocrateReprise/LeSocrate/courstxt")
FILES = ["formation_jour1.txt", "formation_jour2.txt"]

SUBS: list[tuple[str, str]] = [
    # Patterns longs/spécifiques d'abord
    (r"\bgâteau de fête glacé\b", "gâteau personnalisé glacé"),
    (r"\bgâteau de fête identique\b", "gâteau personnalisé identique"),
    (r"\bgâteau de fête chocolat-caramel\b", "gâteau chocolat-caramel"),
    (r"\bgâteau de fête personnalisé\b", "gâteau personnalisé"),
    (r"\bgâteau de fête\b", "gâteau personnalisé"),
    (r"\bun gâteau de fête\b", "un gâteau personnalisé"),
    (r"\ble gâteau de fête\b", "le gâteau personnalisé"),
    (r"\bce gâteau de fête\b", "ce gâteau personnalisé"),

    (r"\brepas de fête\b", "repas de réception"),
    (r"\bvotre repas de fête\b", "votre repas de réception"),
    (r"\brepas de fin d'année\b", "repas de fin d'année"),  # neutre, on garde

    (r"\bproduits de fête de fin d'année\b", "produits saisonniers de fin d'année"),
    (r"\bproduits de fête signature\b", "produits signature saisonniers"),
    (r"\bproduit de fête signature\b", "produit signature saisonnier"),
    (r"\bproduits de fête décorés\b", "produits saisonniers décorés"),
    (r"\bproduit de fête\b", "produit d'exception saisonnier"),
    (r"\bproduits de fête\b", "produits d'exception saisonniers"),

    (r"\bcommandes de produits de fête\b", "commandes de produits saisonniers"),
    (r"\bcommandes de célébration\b", "commandes de réception"),

    (r"\bvotre produit de fête\b", "votre produit signature"),

    # Périodes
    (r"\bLes veilles de fêtes\b", "Les veilles de jours fériés"),
    (r"\bles veilles de fêtes\b", "les veilles de jours fériés"),
    (r"\bpériode de fête\b", "période de forte affluence"),
    (r"\bpériodes de fête\b", "périodes de forte affluence"),
    (r"\bjour de fête\b", "jour férié"),
    (r"\bjours de fête\b", "jours fériés"),
    (r"\bLes fêtes, les vacances scolaires\b", "Les pics commerciaux, les vacances scolaires"),
    (r"\bLes saisons, les fêtes, les rentrées\b", "Les saisons, les pics commerciaux, les rentrées"),
    (r"\bLes saisons, les fêtes\b", "Les saisons, les pics commerciaux"),
    (r"\bles familles, les naissances, les deuils, les fêtes\b",
     "les familles, les naissances, les deuils, les grandes occasions"),
    (r"\bles fêtes\b", "les grandes occasions"),
    (r"\bune fête\b", "une grande occasion"),
    (r"\bla fête\b", "le grand moment"),
    (r"\bdes fêtes\b", "des grandes occasions"),

    # Sens figuré
    (r"\bc'est une vraie fête\b", "c'est un vrai régal"),
    (r"\bC'est une vraie fête\b", "C'est un vrai régal"),

    # Célébrer / célébration → valoriser / reconnaître
    (r"\bcélébrer les petites victoires\b", "savourer les petites victoires"),
    (r"\bcélébrées mentalement\b", "reconnues mentalement"),
    (r"\bce que vous célébrez\b", "ce que vous valorisez"),
    (r"\bCe que vous célébrez\b", "Ce que vous valorisez"),
    (r"\bla célébration des succès\b", "la reconnaissance des succès"),
    (r"\bcélébration des succès\b", "reconnaissance des succès"),
    (r"\bla célébration des bonnes pratiques\b", "la valorisation des bonnes pratiques"),
    (r"\bcélébration des bonnes pratiques\b", "valorisation des bonnes pratiques"),
    (r"\bcélébration\b", "valorisation"),
    (r"\bcélébrations\b", "valorisations"),
    (r"\bcélébrer\b", "valoriser"),
    (r"\bcélèbre\b", "valorise"),
    (r"\bcélébré\b", "valorisé"),
    (r"\bcélébrés\b", "valorisés"),
    (r"\bcélébrée\b", "valorisée"),

    # Reste pris au mot
    (r"\bfête\b", "occasion"),
    (r"\bfêtes\b", "grandes occasions"),
    (r"\bFête\b", "Occasion"),
    (r"\bFêtes\b", "Grandes occasions"),
]


def fix_file(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    total = 0
    for pattern, repl in SUBS:
        text, n = re.subn(pattern, repl, text)
        if n:
            total += n
            print(f"  {pattern!r:55} → {repl!r:40} ({n}×)")
    path.write_text(text, encoding="utf-8")
    return total


def main() -> int:
    for fname in FILES:
        print(f"\n=== {fname} ===")
        n = fix_file(ROOT / fname)
        print(f"  → {n} substitutions appliquées")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
