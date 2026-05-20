#!/usr/bin/env python3
"""Généralise le texte de cours boulangerie vers TP Employé Commercial (RNCP 37099).

Stratégie : remplacements regex ciblés en deux passes :
1. Remplacements vocabulaire (boulangerie → unité marchande, etc.)
2. Réécriture de paragraphes ultra-spécifiques (types de pains, farines, recettes)
   marqués par des sentinelles.

Le script est idempotent : on peut le relancer sans risque.
"""

import re
from pathlib import Path

SRC = Path(__file__).parent / "formation_jour1.txt"

# -------------------------------------------------------------------
# PASSE 1 : remplacements vocabulaire (ordre important : du plus
# spécifique au plus général)
# -------------------------------------------------------------------

# Liste de (pattern_regex, replacement)
# Note: on respecte la casse via flags=re.IGNORECASE puis on rétablit
# la casse initiale via une fonction.

REPLACEMENTS = [
    # ---- Expressions composées (à traiter en premier) ----
    (r"\bboulangerie-pâtisserie\b", "magasin"),
    (r"\bvendeur en boulangerie\b", "employé commercial"),
    (r"\bvendeuse en boulangerie\b", "employée commerciale"),
    (r"\bvendeurs en boulangerie\b", "employés commerciaux"),
    (r"\bvendeuses en boulangerie\b", "employées commerciales"),
    (r"\bvotre boulangerie\b", "votre magasin"),
    (r"\bvotre boulanger\b", "votre responsable"),
    (r"\bnotre boulangerie\b", "notre magasin"),
    (r"\bnotre boulanger\b", "notre responsable"),
    (r"\bla boulangerie\b", "le magasin"),
    (r"\bla pâtisserie\b", "le rayon"),
    (r"\bla viennoiserie\b", "le rayon"),
    (r"\bune boulangerie\b", "un magasin"),
    (r"\bune pâtisserie\b", "un magasin"),
    (r"\bla boulangerie artisanale\b", "le commerce de proximité"),
    (r"\bboulangerie artisanale\b", "commerce de proximité"),
    (r"\bboulangeries artisanales\b", "commerces de proximité"),
    (r"\bchef boulanger\b", "responsable"),
    (r"\bchef pâtissier\b", "responsable"),
    (r"\bdu vrai boulanger\b", "du vrai professionnel"),
    (r"\bvrai boulanger\b", "vrai professionnel"),
    (r"\bvotre comptoir de boulangerie\b", "votre comptoir"),
    (r"\bderrière un comptoir de boulangerie\b", "derrière votre comptoir"),
    (r"\bderrière votre comptoir\b", "derrière votre comptoir"),
    (r"\bderrière le comptoir\b", "derrière le comptoir"),
    (r"\bcomptoir de la boulangerie\b", "comptoir du magasin"),
    (r"\bcomptoir de boulangerie\b", "comptoir"),
    (r"\bclient en boulangerie\b", "client en magasin"),
    (r"\bclients en boulangerie\b", "clients en magasin"),
    (r"\bvendeur en pâtisserie\b", "employé commercial"),
    (r"\baccueil en boulangerie\b", "accueil en magasin"),
    (r"\baccueil client en boulangerie\b", "accueil client en magasin"),
    (r"\bla file d'attente en boulangerie\b", "la file d'attente en magasin"),
    (r"\bvendeuse en boulangerie\b", "employée commerciale"),

    # ---- Mots simples ----
    (r"\bboulangerie\b", "magasin"),
    (r"\bboulangeries\b", "magasins"),
    (r"\bboulanger\b", "professionnel"),
    (r"\bboulangers\b", "professionnels"),
    (r"\bboulangère\b", "professionnelle"),
    (r"\bboulangères\b", "professionnelles"),
    (r"\bpâtissier\b", "professionnel"),
    (r"\bpâtissiers\b", "professionnels"),
    (r"\bpâtissière\b", "professionnelle"),
    (r"\bla boutique\b", "le magasin"),
    (r"\bvotre boutique\b", "votre magasin"),
    (r"\bnotre boutique\b", "notre magasin"),
    (r"\bla pâtisserie\b", "le rayon"),
    (r"\bdes pâtisseries\b", "des produits du rayon"),
    (r"\bles pâtisseries\b", "les produits du rayon"),
    (r"\bune pâtisserie\b", "un produit du rayon"),
    (r"\bvitrine des pâtisseries\b", "rayon"),

    # ---- Produits boulangerie génériques ----
    (r"\bla baguette tradition\b", "un produit phare"),
    (r"\bbaguette tradition\b", "produit phare"),
    (r"\bbaguette de tradition\b", "produit phare"),
    (r"\bune baguette\b", "un article"),
    (r"\bla baguette\b", "l'article"),
    (r"\bdes baguettes\b", "des articles"),
    (r"\bles baguettes\b", "les articles"),
    (r"\bbaguettes\b", "articles"),
    (r"\bbaguette\b", "article"),
    (r"\bun croissant\b", "un article phare"),
    (r"\ble croissant\b", "l'article phare"),
    (r"\bdes croissants\b", "des produits phares"),
    (r"\bles croissants\b", "les produits phares"),
    (r"\bcroissants\b", "produits phares"),
    (r"\bcroissant\b", "article phare"),
    (r"\bdu pain\b", "un produit"),
    (r"\ble pain\b", "le produit"),
    (r"\bles pains\b", "les produits"),
    (r"\bun pain\b", "un produit"),
    (r"\bdes pains\b", "des produits"),
    (r"\bun pain au chocolat\b", "un produit gourmand"),
    (r"\bpain au chocolat\b", "produit gourmand"),
    (r"\bpains au chocolat\b", "produits gourmands"),
    (r"\bune brioche\b", "un article gourmand"),
    (r"\bla brioche\b", "l'article gourmand"),
    (r"\bdes brioches\b", "des articles gourmands"),
    (r"\bles brioches\b", "les articles gourmands"),
    (r"\bbrioches\b", "articles gourmands"),
    (r"\bbrioche\b", "article gourmand"),
    (r"\bviennoiseries\b", "produits du rayon"),
    (r"\bviennoiserie\b", "produit du rayon"),
    (r"\béclairs?\b", "article du rayon"),
    (r"\bmille-feuilles?\b", "produit du rayon"),
    (r"\bune tarte\b", "un produit du rayon"),
    (r"\bdes tartes\b", "des produits du rayon"),
    (r"\bles tartes\b", "les produits du rayon"),
    (r"\bla tarte\b", "le produit du rayon"),
    (r"\btartes\b", "produits du rayon"),
    (r"\btarte\b", "produit du rayon"),
    (r"\bsandwich\b", "article snacking"),
    (r"\bsandwiches\b", "articles snacking"),
    (r"\bsandwichs\b", "articles snacking"),
    (r"\bquiche\b", "plat préparé"),
    (r"\bquiches\b", "plats préparés"),

    # ---- Enseignes/personnalités à remplacer ----
    (r"\bMaison Poilâne\b", "enseigne reconnue"),
    (r"\b[Pp]oilâne\b", "enseigne reconnue"),
    (r"\b[Ll]ionel Poilâne\b", "un commerçant historique"),
    (r"\b[Pp]ierre Poilâne\b", "le fondateur"),
    (r"\b[Cc]hristophe Vasseur\b", "un commerçant reconnu"),
    (r"\bDu Pain et des Idées\b", "une enseigne de référence"),
    (r"\bDu Pain et Des Idées\b", "une enseigne de référence"),
    (r"\b[Ll]adurée\b", "une maison de référence"),
    (r"\b[Ll]enôtre\b", "une maison de référence"),
    (r"\bGaston Lenôtre\b", "un commerçant historique"),
    (r"\b[Mm]amiche\b", "une enseigne reconnue"),
    (r"\bVictoria Effantin\b", "une fondatrice"),
    (r"\bCécile Khayat\b", "une fondatrice"),
    (r"\bEric Kayser\b", "une enseigne internationale"),
    (r"\b[Dd]ominique Ansel\b", "un commerçant reconnu"),
    (r"\b[Tt]artine Bakery\b", "une enseigne internationale"),
    (r"\bChad Robertson\b", "un commerçant reconnu"),
    (r"\bElisabeth Prueitt\b", "une commerçante reconnue"),
    (r"\bGontran Cherrier\b", "un commerçant reconnu"),
    (r"\b[Uu]topie\b", "une enseigne reconnue"),
    (r"\bSébastien Bruno\b", "un commerçant reconnu"),
    (r"\bBenoît Castel\b", "un commerçant reconnu"),
    (r"\b[Ll]iberté\b", "une enseigne engagée"),
    (r"\bMonsieur Leconte\b", "un producteur local"),
    (r"\bMonsieur Guérin\b", "un producteur local"),
    (r"\bMadame Guérin\b", "une productrice locale"),
    (r"\bAhmed\b", "le préparateur"),
    (r"\bJulien\b", "le préparateur"),
    (r"\bMarie\b", "la préparatrice"),  # contexte boulanger

    # ---- Lieux/quartiers boulangerie ----
    (r"\brue du Cherche-Midi\b", "dans un quartier de Paris"),
    (r"\bdixième arrondissement de Paris\b", "un arrondissement parisien"),
    (r"\bsixième arrondissement de Paris\b", "un arrondissement parisien"),
    (r"\bquatorzième arrondissement de Paris\b", "un arrondissement parisien"),
    (r"\bquatorzième arrondissement\b", "un arrondissement parisien"),
    (r"\btreizième arrondissement de Paris\b", "un arrondissement parisien"),
    (r"\btreizième arrondissement\b", "un arrondissement parisien"),
    (r"\bonzième arrondissement de Paris\b", "un arrondissement parisien"),
    (r"\bonzième arrondissement\b", "un arrondissement parisien"),
    (r"\bdixième arrondissement\b", "un arrondissement parisien"),
    (r"\bdix-huitième arrondissement\b", "un arrondissement parisien"),
    (r"\bneuvième arrondissement de Paris\b", "un arrondissement parisien"),
    (r"\bneuvième arrondissement\b", "un arrondissement parisien"),
    (r"\bseptième arrondissement\b", "un arrondissement parisien"),
    (r"\brue Caulaincourt\b", "un quartier parisien"),

    # ---- Termes techniques boulangerie ----
    (r"\bfournil\b", "espace de production"),
    (r"\bfournée\b", "réassort"),
    (r"\bfournées\b", "réassorts"),
    (r"\bla mie\b", "la texture"),
    (r"\bla croûte\b", "la finition"),
    (r"\bdorée et lustrée\b", "soignée"),
    (r"\bla trancheuse à pain\b", "le matériel professionnel"),
    (r"\bfeuilletage\b", "savoir-faire"),
    (r"\bfeuilleté à la main\b", "préparé avec soin"),
    (r"\bpétrissage\b", "préparation"),
    (r"\ble levain\b", "le savoir-faire"),
    (r"\bau levain\b", "de qualité"),
    (r"\blevain\b", "savoir-faire"),
    (r"\blevure\b", "ingrédient"),
    (r"\bfermentation\b", "préparation"),
    (r"\bfermente\b", "se prépare"),
    (r"\bfermente pendant\b", "se prépare pendant"),
    (r"\bfermentent\b", "se préparent"),
    (r"\bfermenté\b", "préparé"),
    (r"\bfermentée\b", "préparée"),
    (r"\bcuisson\b", "fabrication"),
    (r"\bcuit ce matin\b", "préparé ce matin"),
    (r"\bcuit\b", "préparé"),
    (r"\bcuite\b", "préparée"),
    (r"\bsorti du four\b", "préparé"),
    (r"\bsortie du four\b", "préparée"),
    (r"\bsortis du four\b", "préparés"),
    (r"\bsorties du four\b", "préparées"),
    (r"\bdu four\b", "de l'atelier"),
    (r"\ble four\b", "l'atelier"),
    (r"\bau four\b", "à l'atelier"),
    (r"\bfour à bûches\b", "matériel professionnel"),

    # ---- Trancheuse, vitrine, etc. ----
    (r"\bvitrine des pâtisseries\b", "rayon"),
    (r"\bvitrine de pâtisseries\b", "rayon"),

    # ---- Termes liés à la nourriture spécifique ----
    (r"\bla pâte\b", "le produit"),
    (r"\bde la pâte\b", "du produit"),
    (r"\bune pâte\b", "un produit"),
    (r"\bdes pâtes alimentaires\b", "des produits alimentaires"),
    (r"\bbeurre AOP\b", "ingrédient de qualité"),
    (r"\bbeurre frais\b", "ingrédient frais"),
    (r"\bbeurre chaud\b", "produit chaud"),
    (r"\bbeurre fondu\b", "produit doré"),
    (r"\bbeurre caramélisé\b", "produit doré"),
    (r"\bbeurre salé\b", "ingrédient régional"),
    (r"\bdu beurre\b", "d'un ingrédient de qualité"),
    (r"\ble beurre\b", "l'ingrédient phare"),
    (r"\bavec du beurre\b", "avec un ingrédient phare"),
    (r"\bganache\b", "préparation"),
    (r"\bcrème mousseline\b", "préparation"),
    (r"\bdacquoise\b", "préparation"),
    (r"\bcompotée de fruits\b", "préparation aux fruits"),
    (r"\bcrème pâtissière\b", "préparation"),
    (r"\bcrème d'amandes\b", "préparation"),
    (r"\bcrème de marron\b", "préparation"),

    # ---- Subway et autres références spécifiques ----
    (r"\benseignes comme Subway\b", "des enseignes nationales"),
    (r"\bSubway\b", "une enseigne nationale"),
    (r"\bStarbucks\b", "une chaîne internationale"),
    (r"\bYoshinoya\b", "une chaîne internationale"),
    (r"\bTrader Joe's\b", "une chaîne internationale"),
    (r"\bRitz-Carlton\b", "une chaîne hôtelière de référence"),

    # ---- Phrases "vente de pain" ----
    (r"\bvente de pain\b", "vente"),
    (r"\bvendre du pain\b", "vendre"),
    (r"\bvend du pain\b", "vend"),
    (r"\bvendent du pain\b", "vendent"),
    (r"\bvendait du pain\b", "vendait"),
    (r"\bvendu du pain\b", "fait votre travail"),
    (r"\bacheter du pain\b", "acheter un produit"),
    (r"\bachète du pain\b", "achète un produit"),
    (r"\bachètent du pain\b", "achètent un produit"),
    (r"\bacheté du pain\b", "fait un achat"),
    (r"\bnourrir un quartier\b", "servir un quartier"),
    (r"\bdéguster\b", "essayer"),
    (r"\bdégustation\b", "essai"),
    (r"\bdégustations\b", "essais"),
]


def apply_replacements(text: str) -> tuple[str, int]:
    """Applique tous les remplacements et retourne (texte, nb_total)."""
    total = 0
    for pattern, replacement in REPLACEMENTS:
        # Pour préserver la majuscule en début de phrase :
        def smart_replace(m):
            original = m.group(0)
            new = replacement
            # Si le mot original commence par une majuscule, capitaliser le remplacement
            if original and original[0].isupper() and new:
                new = new[0].upper() + new[1:]
            return new

        text, n = re.subn(pattern, smart_replace, text, flags=re.IGNORECASE)
        total += n
    return text, total


def main() -> None:
    text = SRC.read_text(encoding="utf-8")
    new_text, count = apply_replacements(text)
    SRC.write_text(new_text, encoding="utf-8")
    print(f"Remplacements appliqués : {count}")


if __name__ == "__main__":
    main()
