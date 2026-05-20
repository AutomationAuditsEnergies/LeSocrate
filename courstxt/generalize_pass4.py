#!/usr/bin/env python3
"""Passe 4 : nettoyage final des termes résiduels (fromage, kouglof, frasage, etc.)."""

import re
from pathlib import Path

SRC = Path(__file__).parent / "formation_jour1.txt"

REPLACEMENTS = [
    # Fromages → produits complémentaires
    (r"\bfromage de chèvre\b", "produit complémentaire"),
    (r"\bun fromage à pâte molle et finition lavée comme un Munster\b", "un produit complémentaire fort en goût"),
    (r"\bun camembert affiné ou un chèvre de Loire\b", "des produits complémentaires de caractère"),
    (r"\bcamembert\b", "produit complémentaire"),
    (r"\bchèvre de Loire\b", "produit complémentaire"),
    (r"\bun morceau de fromage affiné\b", "un produit complémentaire de qualité"),
    (r"\bdu fromage\b", "des produits complémentaires"),
    (r"\ble fromage\b", "le produit complémentaire"),
    (r"\bdes fromages\b", "des produits complémentaires"),
    (r"\bun fromage\b", "un produit complémentaire"),
    (r"\bce fromage\b", "ce produit complémentaire"),
    (r"\bMême fromage\b", "Même produit"),
    (r"\bfromages affinés\b", "produits complémentaires"),
    (r"\bfromage frais\b", "produit doux"),
    (r"\bfromage et les olives\b", "produits complémentaires"),
    (r"\bfromages?\b", "produits complémentaires"),
    (r"\bMunster\b", "produit complémentaire fort"),

    # Kouglof / kouign-amann / specialités régionales restantes
    (r"\bkouign-amann\b", "spécialité régionale"),
    (r"\bkouglof\b", "spécialité régionale"),
    (r"\bune nouvelle recette de spécialité régionale\b", "une nouvelle référence"),
    (r"\bla recette de spécialité régionale\b", "la nouvelle référence"),

    # Etapes panification résiduelles (lignes 2882, 2894, 2896)
    (r"\bOn commence par le frasage\.\s*\[pause\]\s*Le frasage,\s*c'est le tout premier geste\.\s*\[pause\]\s*Le professionnel verse la matière première dans la cuve du pétrin, il ajoute l'eau, il ajoute le sel, il ajoute parfois l'ingrédient ou le savoir-faire\.\s*\[pause\]\s*Et il mélange\.\s*\[pause\]\s*Doucement\.\s*\[pause\]\s*Juste pour que tous les ingrédients se rencontrent, pour que la matière première absorbe l'eau\.\s*\[pause\]\s*C'est une étape qui dure quelques minutes seulement\.\s*\[pause\]\s*Mais si elle est mal faite, tout le reste est compromis\.\s*\[emphasis\] C'est la fondation\.\s*\[pause\]",
     "On commence par la réception. [pause] La réception, c'est le tout premier geste de la journée. [pause] L'employé commercial vérifie la livraison, contrôle les quantités, vérifie les dates. [pause] Et il enregistre. [pause] Méthodiquement. [pause] Juste pour que tous les produits soient bien comptabilisés, pour que rien ne manque. [pause] C'est une étape qui dure quelques minutes seulement. [pause] Mais si elle est mal faite, tout le reste est compromis. [emphasis] C'est la fondation. [pause]"),
    (r"\bMaintenant, après le préparation, on arrive au pointage\.\s*\[pause\] Le pointage, c'est la première préparation\.\s*\[pause\] Le produit est mise au repos, dans un endroit tempéré, à l'abri des courants d'air\.\s*\[pause\] Et pendant ce temps, quelque chose de magnifique se passe\.\s*\[pause\] Les levures, ou le savoir-faire, se mettent à travailler\.\s*\[pause\] Elles consomment les sucres de la matière première, elles produisent du gaz carbonique, et ce gaz fait gonfler le produit\.\s*\[pause\] Mais ce n'est pas qu'une question de volume\.\s*\[pause\] Pendant ce pointage, le produit développe ses arômes\.\s*\[pause\] Ses acides\.\s*\[pause\] Ses notes de préparation\.\s*\[pause\]",
     "Maintenant, après la réception, on arrive à la mise en rayon. [pause] La mise en rayon, c'est la première phase visible. [pause] Le produit est mis en place, dans un emplacement défini, à l'endroit prévu. [pause] Et pendant ce temps, quelque chose d'important se passe. [pause] Le rayon prend vie, il s'organise, il se structure. [pause] Les facings se remplissent, les références reprennent leur place, le rayon retrouve son équilibre. [pause] Mais ce n'est pas qu'une question de volume. [pause] Pendant cette mise en rayon, le magasin développe son identité. [pause] Son organisation. [pause] Son professionnalisme. [pause]"),
    (r"\bEt plus le pointage est long, plus le produit sera bon\.\s*\[emphasis\] Retenez ça\.\s*\[pause\] Un pointage court, une heure ou deux, ça donne un produit plat, sans relief, sans profondeur\.\s*\[pause\] Un pointage long, quatre, six, huit heures, parfois toute une nuit au froid, ça donne un produit avec du caractère, avec de la longueur en bouche, avec une texture crème et crémeuse\.\s*\[pause\] C'est ce qu'on appelle la préparation longue\.\s*\[pause\] Et c'est elle qui fait la différence entre un produit industriel et un produit de professionnel\.\s*\[pause\]",
     "Et plus la mise en rayon est soignée, plus le rayon sera attractif. [emphasis] Retenez ça. [pause] Une mise en rayon expédiée, c'est un rayon désordonné, sans relief, sans cohérence. [pause] Une mise en rayon soignée, prenant le temps de bien placer chaque référence, ça donne un rayon avec du caractère, avec une vraie lisibilité, avec une présentation accueillante. [pause] C'est ce qu'on appelle la mise en rayon soignée. [pause] Et c'est elle qui fait la différence entre un rayon banal et un rayon de magasin sérieux. [pause]"),

    # Etapes restantes (ligne 2900+)
    (r"\bpointage\b", "phase de réception"),
    (r"\bfrasage\b", "réception"),
    (r"\bfaçonnage\b", "mise en place"),
    (r"\bapprêt sur la couche en lin\b", "préparation finale"),
    (r"\bscarification d'un geste précis\b", "vérification précise"),
    (r"\bressuage sur la grille en bois\b", "phase de finalisation"),
    (r"\bressuage\b", "finalisation"),

    # "espace de production" → "atelier" ou "réserve"
    (r"\bdu espace de production\b", "de l'atelier"),
    (r"\bde l'espace de production\b", "de l'atelier"),
    (r"\bl'espace de production\b", "l'atelier"),
    (r"\bun espace de production\b", "l'atelier"),
    (r"\bespace de production\b", "atelier"),

    # Gateau roulé résiduel
    (r"\bgâteau roulé\b", "produit de fête"),
    (r"\bgâteaux roulés\b", "produits de fête"),
    (r"\bgâteau roulé signature\b", "produit de fête signature"),

    # Produits régionaux et produits boulangerie restants dans contextes
    (r"\bproduit de produit régional\b", "produit régional"),
    (r"\bUn produit de produit régional de qualité\b", "Un produit régional de qualité"),
    (r"\bCe produit de produit régional\b", "Ce produit régional"),

    # Articles spécifiques boulangerie
    (r"\barticle phare beurré, un article gourmand beurrée\b", "article de qualité, une référence soignée"),
    (r"\bBeurré, c'est le premier mot pour un produit du rayon\b", "Soigné, c'est le premier mot pour un produit du rayon"),
    (r"\bBeurré\b", "Soigné"),
    (r"\bbeurré\b", "soigné"),
    (r"\bbeurrée\b", "soignée"),
    (r"\bLacté\b", "Authentique"),
    (r"\blacté\b", "authentique"),

    # Mosaïque diverses
    (r"\ble savoir-faire apporte une acidité caractéristique\b", "le savoir-faire apporte un caractère particulier"),
    (r"\bil a ce petit goût légèrement acidulé, comme un produit doux,\b", "il a ce petit caractère particulier"),
    (r"\bcomme un produit doux, qui vient du savoir-faire authentique\b", "qui vient du savoir-faire authentique"),

    # Préparations contextes
    (r"\barticles snacking végétariens\b", "articles snacking aux légumes"),
    (r"\bpréparation au produit doux et au miel\b", "préparation sucrée-salée"),
    (r"\bpréparation à la tomate, à l'huile d'olive et au basilic\b", "préparation méditerranéenne"),
    (r"\bpréparation d'avocat écrasé avec un peu de citron et de poivre\b", "préparation fraîche"),
    (r"\bproduit aux figues ou un produit aux noix\b", "produit aux fruits ou un produit signature"),
    (r"\bune belle tranche de produit phare légèrement frottée d'ail\b", "un article de qualité bien valorisé"),
    (r"\bproduit aux céréales ou un produit complet bien dense\b", "produit aux céréales ou un produit complet"),
    (r"\bproduit aux graines, produit signature, produit complet\b", "produit aux graines, produit signature, produit complet"),

    # Houmous → produit complémentaire
    (r"\bhoumous\b", "préparation"),
    (r"\bavocat\b", "préparation fraîche"),

    # Gros pains, miches, fougasses, etc.
    (r"\bgros pains ronds\b", "produits volumineux"),
    (r"\bmiches\b", "produits volumineux"),
    (r"\bune fougasse\b", "un produit régional"),
    (r"\bfougasses?\b", "produits régionaux"),
    (r"\bciabatta\b", "produit régional"),
    (r"\bpavés de campagne\b", "produits rustiques"),

    # Trésor de référencement
    (r"\bsavoir-faire authentique\b", "savoir-faire reconnu"),

    # Final cleanup
    (r"\bun produit complémentaire de chèvre\b", "un produit complémentaire"),
    (r"\bd'un produit complémentaire\b", "d'un produit complémentaire"),
    (r"\bcoeur coulant de chocolat\b", "garniture gourmande"),
    (r"\bmousse de marron\b", "préparation gourmande"),
    (r"\bcrème d'amande\b", "préparation"),

    # "professionnel artisan"
    (r"\bprofessionnel artisan\b", "professionnel sérieux"),

    # "kouglof" / "kouign" cleanup
    (r"\bspécialité régionale\b", "produit signature"),

    # Frasage et autres mots techniques boulangerie pris en compte
    (r"\bla cuve du pétrin\b", "le matériel"),
    (r"\bpétrin\b", "matériel"),
    (r"\bpétri\b", "préparé"),
    (r"\bpétrir\b", "préparer"),

    # "Du Pain et Des Idées" résiduels
    (r"\bun produit complémentaire\b", "un produit complémentaire"),  # neutral

    # "matière première" → quand devient lourd : "produit"
    # Mais on garde le mot car contextuel.

    # Cleanup grammatical
    (r"\bde le \b", "du "),
    (r"\bdans le un \b", "dans un "),
    (r"\bun un \b", "un "),
    (r"\bune une \b", "une "),
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
    print(f"Pass 4 — remplacements appliqués : {count}")


if __name__ == "__main__":
    main()
