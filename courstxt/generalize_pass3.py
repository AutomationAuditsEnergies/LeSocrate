#!/usr/bin/env python3
"""Passe 3 : nettoyage final et corrections grammaticales."""

import re
from pathlib import Path

SRC = Path(__file__).parent / "formation_jour1.txt"

REPLACEMENTS = [
    # Reste "pâtisserie/pâtissier" simple
    (r"\bdans une grande pâtisserie\b", "dans un grand magasin"),
    (r"\bd'une grande pâtisserie\b", "d'un grand magasin"),
    (r"\bla pâtisserie de saison\b", "le produit de saison"),
    (r"\bpâtisserie de saison\b", "produit de saison"),
    (r"\bcette pâtisserie\b", "ce produit"),
    (r"\bune simple pâtisserie\b", "un simple produit"),
    (r"\bune pâtisserie\b", "un produit du rayon"),
    (r"\bpâtisserie\b", "rayon"),  # final
    (r"\bpâtissier\b", "responsable"),
    (r"\bpâtissière\b", "responsable"),

    # ---- Cohérence grammaticale post-substitution ----
    (r"\bdu un\b", "d'un"),
    (r"\bDu un\b", "D'un"),
    (r"\bde un\b", "d'un"),
    (r"\bDe un\b", "D'un"),

    # ---- Article rayon ----
    (r"\bla rayon\b", "le rayon"),
    (r"\bune rayon\b", "un rayon"),
    (r"\bcette rayon\b", "ce rayon"),
    (r"\bce rayon de tradition\b", "ce produit phare"),
    (r"\bce rayon a cette forme\b", "ce produit a cette forme"),
    (r"\ble rayon de tradition\b", "le produit phare"),
    (r"\ble rayon de campagne\b", "le produit phare"),

    # ---- Produits du rayon résiduel grammaire ----
    (r"\bdes produits du rayon aux\b", "des produits aux"),
    (r"\bdes produit du rayon aux\b", "des produits aux"),
    (r"\bproduits du rayon aux poires\b", "produits aux poires"),
    (r"\bproduit du rayon aux fraises\b", "produit aux fraises"),
    (r"\barticle aux framboises\b", "article aux framboises"),

    # ---- "four" résiduel (à généraliser ou contextualiser) ----
    (r"\bun four\b", "un équipement professionnel"),
    (r"\ble four\b", "l'équipement"),
    (r"\bnotre four\b", "notre équipement"),
    (r"\bdans le four\b", "dans l'équipement"),
    (r"\bau four\b", "à l'atelier"),
    (r"\bd'un four\b", "d'un équipement"),
    (r"\bdu four de l'atelier\b", "de l'atelier"),
    (r"\bquatre vingt-dix-cinq pour cent\b", "quatre-vingt-quinze pour cent"),
    (r"\bvoûte\b", "élément technique"),
    (r"\bbuée\b", "vapeur"),
    (r"\bpâtons\b", "préparations"),

    # ---- Caramélise / four de l'atelier ----
    (r"\bcaramélise les sucres naturels\b", "met en valeur les ingrédients naturels"),

    # Fix "pâte" résiduel
    (r"\bpâte à cuire\b", "préparation à cuire"),
    (r"\bla pâte\b", "le produit"),
    (r"\bde la pâte\b", "du produit"),
    (r"\bsa propre pâte\b", "leurs propres préparations"),

    # T55 cleanup
    (r"\bProduit standard\b", "produit standard"),
    (r"\bla produit standard\b", "le produit standard"),

    # Cas spéciaux ligne 53 — paragraphe "Pour les produits..."
    # On laisse au manuel.

    # Cohérence "atelier" résiduel
    (r"\batelier à bûches\b", "équipement professionnel"),

    # "grande pâtisserie parisienne" déjà fait
    (r"\ble responsable\b", "le responsable"),  # neutral

    # Phrase mal formée "une magasin"
    (r"\bnotre fabrication\b", "notre fabrication"),  # neutral

    # ---- "comme la crème d'amande" résiduel ----
    (r"\bla crème d'amande\b", "des ingrédients de qualité"),

    # Fix "pâte" pour pâtes alimentaires
    (r"\bdes pâtes fines\b", "des préparations délicates"),
    (r"\bpâtes alimentaires\b", "produits alimentaires"),

    # "Une maison de référence vend"
    (r"\bCe que Une maison de référence vend\b", "Ce que cette maison de référence vend"),
    (r"\bCe que cette enseigne vend n'est pas un simple rayon\b", "Ce que cette enseigne vend n'est pas un simple produit"),

    # cleanup divers
    (r"\bdans une grande magasin\b", "dans un grand magasin"),
]


def smart_case(replacement: str, original: str) -> str:
    if not original or not replacement:
        return replacement
    if original[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def apply_replacements(text: str) -> tuple[str, int]:
    total = 0
    for pattern, replacement in REPLACEMENTS:
        def repl(m):
            return smart_case(replacement, m.group(0))
        text, n = re.subn(pattern, repl, text, flags=re.IGNORECASE)
        total += n
    return text, total


def main() -> None:
    text = SRC.read_text(encoding="utf-8")
    new_text, count = apply_replacements(text)
    SRC.write_text(new_text, encoding="utf-8")
    print(f"Pass 3 — remplacements appliqués : {count}")


if __name__ == "__main__":
    main()
