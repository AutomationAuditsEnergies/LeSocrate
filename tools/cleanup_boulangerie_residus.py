"""Nettoyage final des termes boulangerie résiduels dans les 2 cours.

Après passage des 2 agents de généralisation, il reste ~32 occurrences ciblées.
Ce script applique des substitutions exactes avec word boundaries strictes,
en préservant les faux positifs (« financier » comme adjectif, « tradition »
comme nom commun, etc.).
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path("/Users/amelle/Desktop/SocrateReprise/LeSocrate/courstxt")
FILES = ["formation_jour1.txt", "formation_jour2.txt"]

# Substitutions ciblées (l'ordre compte : long avant court)
SUBS: list[tuple[str, str]] = [
    # Patterns longs ultra-spécifiques d'abord
    (r"\bun morceau de financier\b", "un petit article gourmand"),
    (r"\bUn financier aux noisettes, un moelleux aux amandes\b",
     "Un produit aux noisettes, un produit aux amandes"),
    (r"\bune miche entière\b", "un produit en grand format"),
    (r"\bune miche\b", "un produit en grand format"),
    (r"\bla miche\b", "le produit en grand format"),
    (r"\bd'une miche\b", "d'un produit en grand format"),
    (r"\b[Bb]aguette tradition\b", "produit phare"),
    (r"\b[Pp]ain de mie\b", "produit moelleux"),
    (r"\b[Pp]ain de campagne\b", "produit phare"),
    # Mots simples résiduels
    (r"\bune viennoiserie\b", "un article moelleux"),
    (r"\bla viennoiserie\b", "l'article moelleux"),
    (r"\bdes viennoiseries\b", "des articles moelleux"),
    (r"\bles viennoiseries\b", "les articles moelleux"),
    (r"\bviennoiseries\b", "articles moelleux"),
    (r"\bviennoiserie\b", "article moelleux"),
    (r"\bune baguette\b", "un produit du quotidien"),
    (r"\bla baguette\b", "le produit du quotidien"),
    (r"\bdes baguettes\b", "des produits du quotidien"),
    (r"\bBaguette\b", "Produit phare"),
    (r"\bbaguette\b", "produit phare"),
    (r"\bun croissant\b", "un article du petit-déjeuner"),
    (r"\bdes croissants\b", "des articles du petit-déjeuner"),
    (r"\bcroissant\b", "article du petit-déjeuner"),
    (r"\bun sandwich\b", "un produit de snacking"),
    (r"\bles sandwichs\b", "les produits de snacking"),
    (r"\bdes sandwichs\b", "des produits de snacking"),
    (r"\bsandwich\b", "produit de snacking"),
    (r"\bune tartine\b", "un article tartiné"),
    (r"\bdes tartines\b", "des articles tartinés"),
    (r"\bla tartine\b", "l'article tartiné"),
    (r"\btartine\b", "article tartiné"),
    (r"\bla mie\b", "le cœur du produit"),
    (r"\bdes mies\b", "des cœurs de produit"),
    (r"\bles mies tendres\b", "des textures tendres"),
    (r"\bsa mie\b", "son cœur"),
    (r"\bune mie\b", "un cœur"),
    (r"\bla farine\b", "la matière première"),
    (r"\bde farine\b", "de matière première"),
    (r"\bune farine\b", "une matière première"),
    (r"\bfarine\b", "matière première"),
    (r"\bdu fromage\b", "du produit complémentaire affiné"),
    (r"\ble fromage\b", "le produit complémentaire affiné"),
    (r"\bce fromage\b", "ce produit complémentaire"),
    (r"\bun fromage\b", "un produit complémentaire"),
    (r"\bun chèvre frais\b", "un produit régional frais"),
]

# Faux positifs à NE PAS toucher : « financier » comme adjectif
# (déjà géré par regex spécifique ci-dessus qui matche « morceau de financier »)


def fix_file(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    total = 0
    for pattern, repl in SUBS:
        text, n = re.subn(pattern, repl, text)
        if n:
            total += n
            print(f"  {pattern!r:50} → {repl!r:35} ({n}×)")
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
