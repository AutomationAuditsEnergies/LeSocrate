#!/usr/bin/env python3
"""Passe 2 : nettoyage des résidus boulangerie et corrections de cohérence."""

import re
from pathlib import Path

SRC = Path(__file__).parent / "formation_jour1.txt"

# Patterns à corriger pour cohérence grammaticale et résidus
REPLACEMENTS = [
    # Corrections grammaticales liées aux substitutions précédentes
    (r"\bvotre magasin artisanale\b", "votre magasin"),
    (r"\bun magasin artisanale\b", "un magasin"),
    (r"\ble magasin artisanale\b", "le magasin"),
    (r"\bce magasin artisanale\b", "ce magasin"),
    (r"\bvotre magasin artisanal\b", "votre magasin"),
    (r"\bun magasin artisanal\b", "un magasin"),
    (r"\ble magasin artisanal\b", "le magasin"),
    (r"\ble magasin artisanale\b", "le magasin"),
    (r"\bdans une magasin\b", "dans un magasin"),
    (r"\bcette magasin\b", "ce magasin"),
    (r"\bla magasin\b", "le magasin"),
    (r"\bdes magasin\b", "des magasins"),
    (r"\bd'un magasin\b", "d'un magasin"),
    (r"\bde la magasin\b", "du magasin"),
    (r"\bsa magasin\b", "son magasin"),
    (r"\bde sa magasin\b", "de son magasin"),
    (r"\bdans sa magasin\b", "dans son magasin"),
    (r"\bune magasin\b", "un magasin"),
    (r"\bUne magasin\b", "Un magasin"),
    (r"\bLa magasin\b", "Le magasin"),
    (r"\bDans une magasin\b", "Dans un magasin"),

    # Cohérences "le rayon" / "un rayon" / etc.
    (r"\bun rayon des essais\b", "un essai produit"),
    (r"\bvitrine des article du rayon\b", "rayon"),
    (r"\bvitrine des produits du rayon\b", "rayon"),
    (r"\barticles du rayon\b", "articles"),
    (r"\barticle du rayon\b", "article"),

    # Phrases résiduelles "pain"
    (r"\bce pain\b", "ce produit"),
    (r"\bun pain\b", "un produit"),
    (r"\ble pain\b", "le produit"),
    (r"\bles pains\b", "les produits"),
    (r"\bdes pains\b", "des produits"),
    (r"\bdu pain\b", "du produit"),
    (r"\bnos pains\b", "nos produits"),
    (r"\bvos pains\b", "vos produits"),
    (r"\bson pain\b", "son produit"),
    (r"\bsa pain\b", "son produit"),
    (r"\bpain spécial\b", "produit spécial"),
    (r"\bpains spéciaux\b", "produits spéciaux"),
    (r"\bpain au levain\b", "produit phare"),
    (r"\bpain de tradition\b", "produit phare"),
    (r"\bpain de campagne\b", "produit phare"),
    (r"\bpain complet\b", "produit complet"),
    (r"\bpain intégral\b", "produit complet"),
    (r"\bpain aux noix\b", "produit signature"),
    (r"\bpain aux céréales\b", "produit aux céréales"),
    (r"\bpain au seigle\b", "produit régional"),
    (r"\bpain de seigle\b", "produit régional"),
    (r"\bpain de mie\b", "produit standard"),
    (r"\bpain rustique\b", "produit rustique"),
    (r"\bpains rustiques\b", "produits rustiques"),
    (r"\bpain blanc\b", "produit standard"),
    (r"\bpain aux figues\b", "produit aux fruits"),
    (r"\bpain aux fruits\b", "produit aux fruits"),
    (r"\bpain aux graines\b", "produit aux graines"),
    (r"\bpain au khorasan\b", "produit phare"),
    (r"\bpain à la châtaigne\b", "produit régional"),
    (r"\bpain aux châtaignes\b", "produit régional"),
    (r"\bpain aux raisins\b", "produit aux fruits"),
    (r"\bpain aux fruits confits\b", "produit aux fruits"),
    (r"\bpain au sarrasin\b", "produit régional"),
    (r"\bpain au lait\b", "produit standard"),
    (r"\bpain au yuzu\b", "produit original"),
    (r"\bpain au miso\b", "produit original"),
    (r"\bpain au beurre\b", "produit gourmand"),
    (r"\bpain au caramel\b", "produit gourmand"),
    (r"\bpain à l'encre de seiche\b", "produit original"),
    (r"\bpain aux épices\b", "produit aux épices"),
    (r"\bpain bio\b", "produit bio"),
    (r"\bpain frais\b", "produit frais"),
    (r"\bpain chaud\b", "produit chaud"),
    (r"\bpain industriel\b", "produit industriel"),
    (r"\bpain artisanal\b", "produit artisanal"),
    (r"\bpain panifiable\b", "produit phare"),
    (r"\bpain noir\b", "produit"),
    (r"\bpain perdu\b", "préparation traditionnelle"),
    (r"\bpain d'épices\b", "produit aux épices"),
    (r"\bun bon pain\b", "un bon produit"),
    (r"\bbon pain\b", "bon produit"),

    # Fin: "pain" tout seul → "produit"
    (r"\bdu pain frais\b", "des produits frais"),
    (r"\bde pain\b", "de produit"),
    (r"\bavec du pain\b", "avec ce produit"),
    (r"\bsans pain\b", "sans le produit"),
    (r"\bpain\b", "produit"),  # nettoyage final

    # ---- Farines / céréales ----
    (r"\bla farine\b", "la matière première"),
    (r"\bde la farine\b", "de la matière première"),
    (r"\bune farine\b", "une matière première"),
    (r"\bdes farines\b", "des matières premières"),
    (r"\bles farines\b", "les matières premières"),
    (r"\bvotre farine\b", "votre approvisionnement"),
    (r"\bnotre farine\b", "notre approvisionnement"),
    (r"\bcette farine\b", "ce produit"),
    (r"\bfarines anciennes\b", "matières premières traditionnelles"),
    (r"\bfarine ancienne\b", "matière première traditionnelle"),
    (r"\bfarine paysanne\b", "matière première locale"),
    (r"\bfarine locale\b", "matière première locale"),
    (r"\bfarine industrielle\b", "produit industriel"),
    (r"\bfarine bio\b", "matière première bio"),
    (r"\bfarine de tradition\b", "matière première traditionnelle"),
    (r"\bfarine complète\b", "produit complet"),
    (r"\bfarine intégrale\b", "produit complet"),
    (r"\bfarine de blé\b", "produit céréalier"),
    (r"\bfarine de seigle\b", "produit régional"),
    (r"\bfarine de riz\b", "produit alternatif"),
    (r"\bfarine de maïs\b", "produit alternatif"),
    (r"\bfarine de châtaigne\b", "produit régional"),
    (r"\bfarine de sarrasin\b", "produit alternatif"),
    (r"\bfarine de pois chiche\b", "produit alternatif"),
    (r"\bfarine\b", "matière première"),

    # ---- Mots techniques ----
    (r"\ble seigle\b", "le produit régional"),
    (r"\bdu seigle\b", "du produit régional"),
    (r"\bseigle\b", "produit régional"),
    (r"\bl'épeautre\b", "un produit alternatif"),
    (r"\bépeautre\b", "produit alternatif"),
    (r"\bkamut\b", "produit alternatif"),
    (r"\bkhorasan\b", "produit alternatif"),
    (r"\bsarrasin\b", "produit alternatif"),
    (r"\ble blé\b", "la céréale"),
    (r"\bdu blé\b", "de la céréale"),
    (r"\bblé tendre\b", "céréale standard"),
    (r"\bblé dur\b", "céréale spécifique"),
    (r"\bblé noir\b", "céréale alternative"),
    (r"\bblé Rouge de Bordeaux\b", "une variété traditionnelle"),
    (r"\bRouge de Bordeaux\b", "variété traditionnelle"),
    (r"\bblé\b", "céréale"),
    (r"\bcéréales reine\b", "céréale de référence"),

    # ---- Termes techniques de cuisson/préparation ----
    (r"\bmie\b", "texture"),
    (r"\bla croûte\b", "la finition"),
    (r"\bune croûte\b", "une finition"),
    (r"\bcette croûte\b", "cette finition"),
    (r"\bcroûte\b", "finition"),
    (r"\bcroûton\b", "produit transformé"),
    (r"\bcroûtons\b", "produits transformés"),
    (r"\btartine\b", "préparation"),
    (r"\btartines\b", "préparations"),
    (r"\bclub-sandwich\b", "article snacking"),
    (r"\bclub-sandwichs\b", "articles snacking"),
    (r"\bclubs-sandwichs\b", "articles snacking"),
    (r"\bchausson aux pommes\b", "article du rayon"),
    (r"\bchaussons aux pommes\b", "articles du rayon"),
    (r"\bpain perdu\b", "préparation traditionnelle"),
    (r"\bpangrattato\b", "préparation traditionnelle"),
    (r"\bpudding\b", "préparation"),
    (r"\bpuddings\b", "préparations"),
    (r"\bgalette\b", "préparation"),
    (r"\bgalettes\b", "préparations"),
    (r"\bcrêpe\b", "préparation"),
    (r"\bcrêpes\b", "préparations"),

    # ---- Saisonnier ----
    (r"\bgalette des Rois\b", "produit de saison"),
    (r"\bgalettes des Rois\b", "produits de saison"),

    # ---- Cas particuliers et résidus ----
    (r"\bIl ne fait pas de produit phare\b", "Il propose une offre différenciée"),
    (r"\bIl ne fait pas de produit\b", "Il propose autre chose"),
    (r"\barticles tradition\b", "produits phares"),
    (r"\bun produit phare est plus chère que celle\b", "un article est plus cher que celui"),
    (r"\bvotre article est plus chère\b", "votre article est plus cher"),
    (r"\bnotre article est façonnée\b", "notre article est préparé"),
    (r"\bCette article\b", "Cet article"),
    (r"\bcette article\b", "cet article"),
    (r"\bun produit phare\b", "un produit phare"),

    # ---- Phrases résiduelles spécifiques ----
    (r"\bproduit phare,\b", "produit phare,"),
    (r"\bune produit\b", "un produit"),
    (r"\bUne produit\b", "Un produit"),
    (r"\b'un produit\b", "'un produit"),
    (r"\bnotre produit phare, on le fait avec\b", "notre produit phare, on le prépare avec"),
    (r"\bil est feuilleté à la main par notre boulanger\b", "il est préparé soigneusement par notre équipe"),
    (r"\bvous allez entendre le son caractéristique des vrais produits phares\b", "vous allez ressentir la qualité caractéristique des vrais produits artisanaux"),

    # ---- Réactions chimiques et termes techniques restant ----
    (r"\bréaction de Maillard\b", "savoir-faire de fabrication"),
    (r"\bréaction chimique\b", "transformation"),
    (r"\bautolyse\b", "technique professionnelle"),

    # ---- "Vente de pain" déjà fait mais résiduels ----
    (r"\bvente du produit\b", "vente"),
    (r"\bvente de produit\b", "vente"),
    (r"\bvend le produit\b", "vend"),
    (r"\bvend du produit\b", "vend"),
    (r"\bvendre le produit\b", "vendre"),

    # ---- Préparateurs / boulangers résiduels ----
    (r"\bvotre préparateur\b", "votre responsable"),
    (r"\bnotre préparateur\b", "notre responsable"),
    (r"\bLe préparateur\b", "un collaborateur"),
    (r"\bLa préparatrice\b", "une collaboratrice"),
    (r"\bpréparateur\b", "collaborateur"),
    (r"\bpréparatrice\b", "collaboratrice"),
    (r"\bdu meunier\b", "du fournisseur"),
    (r"\ble meunier\b", "le fournisseur"),
    (r"\bun meunier\b", "un fournisseur"),
    (r"\bvotre meunier\b", "votre fournisseur"),
    (r"\bnotre meunier\b", "notre fournisseur"),
    (r"\bmeunier\b", "fournisseur"),
    (r"\bmeuniers\b", "fournisseurs"),
    (r"\bmoulin\b", "atelier de production"),
    (r"\bmoulins\b", "ateliers de production"),

    # ---- Famille de produits ----
    (r"\bla famille des produits phares\b", "la famille des articles principaux"),
    (r"\bfamilles des produits phares\b", "familles des articles principaux"),
    (r"\bfamille des produits spéciaux\b", "famille des produits spécifiques"),

    # ---- Ingredients spécifiques ----
    (r"\bingrédient professionnelle\b", "ingrédient professionnel"),
    (r"\bingrédient industrielle\b", "produit industriel"),
    (r"\b la ingrédient\b", " l'ingrédient"),
    (r"\bla ingrédient\b", "l'ingrédient"),
    (r"\bavec du savoir-faire et du sel\b", "avec des ingrédients essentiels"),
    (r"\bsavoir-faire naturel\b", "savoir-faire authentique"),
    (r"\bsavoir-faire de qualité\b", "savoir-faire authentique"),
    (r"\bun savoir-faire plus jeune\b", "une technique différente"),
    (r"\bnotre savoir-faire\b", "notre savoir-faire"),  # neutral
    (r"\bsavoir-faire travaille lentement\b", "le travail est lent et méticuleux"),

    # ---- T55, T65 etc. ----
    (r"\bT45\b", "produit standard"),
    (r"\bT55\b", "produit standard"),
    (r"\bT65\b", "produit standard"),
    (r"\bT80\b", "produit standard"),
    (r"\bT110\b", "produit standard"),
    (r"\bT150\b", "produit standard"),
    (r"\btype cinquante-cinq\b", "référence standard"),
    (r"\btype soixante-cinq\b", "référence standard"),
    (r"\btaux de cendres\b", "indicateur de qualité"),
    (r"\bW 150\b", "indicateur faible"),
    (r"\bW 220\b", "indicateur standard"),
    (r"\bW 250\b", "indicateur moyen"),
    (r"\bW 350\b", "indicateur élevé"),

    # ---- Lieux résiduels ----
    (r"\bun arrondissement parisien\b", "un quartier parisien"),
    (r"\bd'un arrondissement parisien\b", "d'un quartier parisien"),
    (r"\bdu un arrondissement parisien\b", "d'un quartier parisien"),
    (r"\bdu quartier parisien\b", "d'un quartier parisien"),

    # ---- Cas grammaticaux multiples ----
    (r"\bdes des enseignes\b", "des enseignes"),
    (r"\bvers le magasin\b", "vers le magasin"),
    (r"\bdans un magasin\b", "dans un magasin"),
    (r"\bdans le magasin\b", "dans le magasin"),
    (r"\bde le magasin\b", "du magasin"),
    (r"\bà le magasin\b", "au magasin"),
    (r"\bà le rayon\b", "au rayon"),
    (r"\bde le rayon\b", "du rayon"),
    (r"\bde le produit\b", "du produit"),
    (r"\bà le produit\b", "au produit"),
    (r"\bsur le produit\b", "sur le produit"),
    (r"\ble produit phare\b", "le produit phare"),
    (r"\bla produit phare\b", "le produit phare"),
    (r"\bune produit phare\b", "un produit phare"),
    (r"\bUn produit phare est plus chère que celui\b", "Un article est plus cher que celui"),

    # Vendeur en boulangerie résiduel
    (r"\bvendeur en magasin artisanale\b", "employé commercial"),
    (r"\bemployé commercial artisanale\b", "employé commercial"),
    (r"\bemployé commercial en magasin\b", "employé commercial"),

    # 192 → un quartier parisien grammar fix
    (r"\bun a quartier parisien\b", "un quartier parisien"),

    # Cohésion finale "essai" / "dégustation"
    (r"\bessais imaginaire\b", "essai imaginaire"),
    (r"\bune essai\b", "un essai"),
    (r"\bun essai\b", "un essai"),

    # Réassort résiduel
    (r"\bréassort de produit\b", "réassort"),
    (r"\bRéassort de produit\b", "Réassort"),

    # ---- Subway, etc. déjà fait ----

    # ---- Profil culture spécifique boulangerie ----
    (r"\baccueil en magasin\b", "accueil en magasin"),

    # Cas "Enseigne reconnue" répétée (dûe à substitution Poilâne)
    (r"\bLionel Enseigne reconnue\b", "le fondateur de cette enseigne"),
    (r"\bchez Enseigne reconnue\b", "chez cette enseigne"),
    (r"\bla maison Enseigne reconnue\b", "cette enseigne"),
    (r"\bmaison Enseigne reconnue\b", "cette enseigne"),
    (r"\bl'équipe Enseigne reconnue\b", "l'équipe de cette enseigne"),
    (r"\bla boulangerie Enseigne reconnue\b", "cette enseigne"),
    (r"\bUne maison de référence\b", "Une maison de référence"),
    (r"\bUne enseigne reconnue\b", "Une enseigne reconnue"),
    (r"\bEnseigne reconnue\b", "cette enseigne"),

    # ---- "moulin de tel endroit" etc. ----
    (r"\batelier de production de tel endroit\b", "fournisseur local"),
    (r"\bdans un atelier de production qui existe\b", "chez un partenaire qui existe"),

    # ---- Cuisson / sole etc. ----
    (r"\bla sole\b", "le four de l'atelier"),  # contexte boulangerie
    (r"\bla vapeur d'enfournement\b", "la technique professionnelle"),
    (r"\bla finition dorée\b", "la finition soignée"),

    # Stays:
    (r"\baspect visuel\b", "aspect visuel"),
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
    print(f"Pass 2 — remplacements appliqués : {count}")


if __name__ == "__main__":
    main()
