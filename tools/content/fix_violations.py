#!/usr/bin/env python3
"""
Corrige les violations dans reformulated_text.txt (jour1 et jour2).
- Supprime les références à des études non vérifiables
- Supprime les chiffres précis non sourcés
- Ajoute disclaimer sur les exemples fictifs avec lieux
"""

import re
import sys

def fix_file(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()

    original = text

    # ── 1. ÉTUDES NON VÉRIFIABLES ───────────────────────────────────────────
    # Pattern : "Des études/recherches/chercheurs X ont montré/démontré que [phrase]."
    # → Supprimer l'intro, garder la phrase qui suit (le fait lui-même)

    study_intros = [
        # Supprimer complètement (intro + contenu douteux)
        (r"Des études en comportement du consommateur montrent qu['']un client insatisfait de l['']accueil ne se plaint généralement pas directement\.[^.]*\.", ""),
        (r"Les chercheurs en psychologie sociale ont montré quelque chose d['']assez frappant\. \[pause\] Les premières impressions se forment en moins de quatre secondes\. \[pause\] Quatre secondes\. \[pause\] C['']est moins de temps qu['']il n['']en faut pour dire votre propre prénom\. \[pause\] Et ce phénomène, on l['']appelle le jugement éclair\.", "[calm] On appelle ce phénomène le jugement éclair."),
        # Mehrabian 7-38-55 - toutes les variantes
        (r"Des recherches menées dans les années soixante-dix ont établi que dans une interaction émotionnellement chargée, \[pause\] seulement sept pour cent du message est transmis par les mots\. \[pause\] Trente-huit pour cent par le ton de la voix\. \[pause\] Et cinquante-cinq pour cent par le langage corporel\. \[pause\] Même si ces chiffres font débat dans leur application stricte, \[pause\] ils posent une réalité indiscutable : \[pause\] votre corps parle\. \[pause\] Et vos clients l['']entendent\.", "votre corps parle. [pause] Et vos clients l'entendent."),
        (r"Des recherches en psychologie de la communication ont mis en évidence que lors d['']une communication émotionnelle, seulement sept pour cent du message passe par les mots\. \[pause\] Trente-huit pour cent par le ton de la voix\. Et cinquante-cinq pour cent par le langage corporel\.", ""),
        (r"Des recherches en communication non verbale ont montré que dans une communication émotionnelle, le message est transmis à cinquante-cinq pour cent par le langage corporel, à trente-huit pour cent par le ton de la voix, et à seulement sept pour cent par les mots eux-mêmes\.", ""),
        (r"Des recherches universitaires menées dans les années quatre-vingt sur la communication émotionnelle ont produit un chiffre[^.]+\.", ""),
        (r"Ce chiffre dit que dans une communication émotionnelle, cinquante-cinq pour cent du message est transmis par le langage corporel, trente-huit pour cent par le ton de voix, et seulement sept pour cent par les mots eux-mêmes\.", ""),
        # Avis en ligne 70%
        (r"Les études montrent qu['']environ soixante-dix pour cent des consommateurs \[pause\] consultent les avis en ligne avant de choisir un commerce de proximité pour la première fois\. \[pause\]", ""),
        # Psychologie du travail bien-être
        (r"Des recherches en psychologie du travail ont montré que la qualité de l['']accueil \[pause\] est directement corrélée au niveau de bien-être au travail\. \[pause\]", ""),
        # Hall proxémie
        (r"Elle a été formalisée par des travaux d['']anthropologie dans les années soixante\. \[pause\] Il a identifié quatre zones de distance\.", "On distingue quatre zones de distance."),
        # Effet Pygmalion
        (r"Des recherches classiques en psychologie l['']ont montré avec l['']effet Pygmalion\. \[pause\] Lorsque les enseignants croyaient que certains élèves étaient particulièrement doués, \[pause\] ces élèves progressaient effectivement davantage\. \[pause\] Non pas parce qu['']ils l['']étaient, \[pause\] mais parce que les attentes positives de l['']enseignant modifiaient son comportement envers eux\. \[pause\]", ""),
        # Psychologie de l'attente
        (r"La psychologie de l['']attente a fait l['']objet de nombreuses études dans les années quatre-vingt\. \[pause\] Une première conclusion : \[pause\]", ""),
        # Paradoxe de la réclamation
        (r"Des recherches en relation client ont documenté un phénomène qu['']on appelle le paradoxe de la réclamation\.", "Il existe un phénomène bien connu qu'on appelle le paradoxe de la réclamation."),
        # Psychologie du travail (les recherches ont montré quelque chose de fascinant)
        (r"Les recherches en psychologie du travail ont montré quelque chose de fascinant\. \[pause\]", ""),
        # Satisfaction restauration rapide
        (r"Dans les études sur la satisfaction client dans le secteur de la restauration rapide, \[pause\]", ""),
        # Neurones miroirs 1992 Parme
        (r"Les neurones miroirs ont été découverts par accident en 1992 \[pause\] par une équipe de chercheurs italiens à Parme\.", "Les neurones miroirs ont été mis en évidence par des chercheurs en neurosciences."),
        # Prix Nobel économie comportementale
        (r"Cette règle a été formulée par les recherches en économie comportementale récompensées par le prix Nobel\.", ""),
        # Capital social années 2000
        (r"Des travaux de sociologie publiés dans les années deux mille \[pause\] ont montré que dans les sociétés occidentales contemporaines, \[pause\] le capital social s['']effondre\.", "Dans les sociétés occidentales contemporaines, le capital social s'effondre."),
        # Fatigue décisionnelle
        (r"a été documenté par les recherches en psychologie dans les années deux mille\.", "est bien documenté."),
        # Base sécurisante années 50
        (r"développé par les recherches en psychiatrie des années cinquante,", ""),
        # Bien-être au travail / sens
        (r"Des études sur le bien-être au travail montrent systématiquement \[pause\] que les professionnels", "Les professionnels"),
        # Réciprocité années 80
        (r", documenté par les travaux de psychologie sociale publiés dans les années quatre-vingt,", ""),
        # Intelligence relationnelle
        (r"les recherches montrent que l['']intelligence relationnelle", "l'intelligence relationnelle est considérée comme"),
        # Chronobiologie
        (r"Les chronobiologistes ont montré que le niveau d['']énergie et d['']attention humaine \[pause\] suit des cycles naturels sur vingt-quatre heures\. \[pause\] En général, \[pause\] un pic d['']énergie le matin entre neuf heures et midi\. \[pause\] Une baisse en début d['']après-midi entre treize heures et quinze heures\. \[pause\] Un second pic en fin d['']après-midi entre seize heures et dix-huit heures\. \[pause\] Et une baisse progressive en soirée\.", "Le niveau d'énergie et d'attention suit des cycles naturels. [pause] En général, un pic le matin, une baisse en début d'après-midi, et un second pic en fin d'après-midi."),
        # Psychologie du service 30 secondes
        (r"Des recherches en psychologie du service ont montré \[pause\] qu['']un client se sent accueilli \[pause\] quand au moins deux signaux positifs distincts lui ont été envoyés \[pause\] dans les premières trente secondes\.", "Un client se sent accueilli quand au moins deux signaux positifs distincts lui ont été envoyés rapidement."),
        # 70% avis en ligne (variante)
        (r"Des études menées dans le secteur de la restauration et du commerce alimentaire de détail montrent régulièrement qu['']une vente additionnelle réussie sur un client sur trois peut augmenter le chiffre d['']affaires d['']une boutique de dix à vingt pour cent\.[^.]*\.", ""),
        (r"Dix à vingt pour cent de chiffre d['']affaires en plus\. \[pause\] Retenez bien ce chiffre\.", ""),
        # Psycholinguistique
        (r"Des recherches en psycholinguistique ont montré que les phrases commençant par un mot sensoriel ou concret suscitent une réaction émotionnelle plus rapide que celles commençant par un terme abstrait ou générique\. \[pause\]", ""),
        # Économie comportementale remises
        (r"Des recherches en économie comportementale ont démontré que les remises peuvent parfois réduire la valeur perçue d['']un produit au lieu de l['']augmenter\.", "Les remises peuvent parfois réduire la valeur perçue d'un produit au lieu de l'augmenter."),
        # Fidélisation ×5
        (r"Des recherches sur la fidélisation client montrent qu['']un client qui se sent mémorisé et reconnu est jusqu['']à cinq fois moins susceptible de changer de boulangerie\.", ""),
        # Design commerce 20-30%
        (r"Des recherches menées par des experts en design de commerce de détail ont montré que la disposition des produits dans un espace commercial peut augmenter ou réduire les achats impulsifs de vingt à trente pour cent, indépendamment de tout discours commercial\.", ""),
        # Transportation narrative
        (r"Les recherches en psychologie de la persuasion montrent que quand on entend une histoire, le cerveau entre dans un état qu['']on appelle la transportation narrative\.", "Quand on entend une histoire, le cerveau entre dans un état qu'on appelle la transportation narrative."),
        # Université Ohio excuses
        (r"Une étude de l['']Université d['']Ohio publiée en 2016 a analysé les composantes des excuses efficaces\.", "Les excuses efficaces contiennent plusieurs éléments clés."),
        # Université Yale 2015
        (r"En 2015, une étude menée par des chercheurs de l['']Université de Yale a filmé des interactions dans des points de vente alimentaires pendant plusieurs semaines\. \[pause\] Ils ont mesuré l['']état émotionnel des clients[^.]+\.", ""),
        # 88% avis en ligne 2023
        (r"En 2023, une étude a montré que quatre-vingt-huit pour cent des consommateurs lisent les avis en ligne avant de choisir un commerce alimentaire de proximité\.", ""),
        # Réclamations silencieuses 26-50
        (r"Des études estiment que pour chaque client qui réclame, entre vingt-six et cinquante clients ont vécu le même problème sans rien dire\. \[pause\] Et ont simplement cessé de venir\.", "La grande majorité des clients insatisfaits ne disent rien. [pause] Ils partent simplement."),
        (r"Vingt-six à cinquante clients silencieux pour chaque réclamation visible\.", ""),
        # Richard Larson MIT
        (r"Des recherches menées par le chercheur Richard Larson du MIT ont montré que", "On sait que"),
        # Psychologie comportementale positif
        (r"Des recherches en psychologie comportementale ont montré quelque chose d['']important\. \[pause\] Les individus en état émotionnel positif sont significativement plus réceptifs", "Les individus en état émotionnel positif sont plus réceptifs"),
        # Conformité sociale
        (r"La psychologie sociale a documenté le phénomène de la conformité sociale\. Les individus ont tendance à aligner leurs comportements sur ceux du groupe\.", "Les individus ont tendance à aligner leurs comportements sur ceux du groupe."),
        # Neurosciences de la décision
        (r"Les chercheurs en neurosciences de la décision ont découvert quelque chose de fascinant\. \[pause\]", ""),
        # Comportement consommateur micro-moments
        (r"Avant de vraiment conclure, je veux aborder un dernier sujet que les neurosciences appliquées au comportement du consommateur ont mis en lumière ces dernières années\.", "Avant de vraiment conclure, je veux aborder un dernier sujet."),
        # Proximité physique
        (r"Des études en comportement du consommateur ont montré que la probabilité qu['']un client achète un produit complémentaire augmente de façon significative quand ce produit est physiquement proche du produit principal dans l['']espace de la boutique\. \[pause\]", ""),
        # Psychologie du consommateur toucher
        (r"Des recherches en psychologie du consommateur ont montré que le simple fait de toucher un produit avant de l['']acheter augmente significativement la valeur perçue de ce produit et la probabilité d['']achat\. \[pause\] Quand vous tenez physiquement un objet, votre cerveau développe un sentiment de propriété psychologique\.", "Quand vous tenez physiquement un objet, votre cerveau développe un sentiment de propriété psychologique."),
        # Marketing sensoriel couleur dorée
        (r"Des études en marketing sensoriel ont montré que les produits à dominante dorée sont perçus comme plus désirables et plus appétissants que des produits équivalents à dominante de couleur froide\. \[pause\]", ""),
        # Météo comportement consommateur
        (r"Mais les études sur le comportement du consommateur dans la restauration et le commerce alimentaire ont montré de façon répétée que la météo influence significativement les décisions d['']achat\. \[pause\]", ""),
        # Psychologie de la consommation présentation
        (r"Des études en psychologie de la consommation ont montré que les produits alimentaires présentés de façon esthétiquement soignée sont perçus comme plus frais, plus savoureux et plus précieux\.", "Les produits alimentaires présentés de façon esthétiquement soignée sont perçus comme plus frais, plus savoureux et plus précieux."),
        # Économie comportementale présentation produit
        (r"Des études en économie comportementale ont montré que le même produit peut être perçu comme deux à trois fois plus précieux selon la façon dont il est présenté\. \[pause\] Pas deux fois plus cher parce qu['']il est de meilleure qualité\. Deux fois plus précieux parce que le contexte de présentation a été travaillé\.", "La façon de présenter un produit change radicalement la façon dont il est perçu."),
        # Psychologie sociale réciprocité (intro)
        (r"La recherche en psychologie sociale a identifié plusieurs principes fondamentaux qui gouvernent les comportements humains en situation de demande ou de suggestion\. \[pause\] L['']un des plus puissants est le principe de réciprocité\.", "L'un des principes les plus puissants dans la relation humaine est le principe de réciprocité."),
        # Neurosciences fermentation
        (r"Des études récentes ont confirmé que certaines fermentations longues réduisent l['']index glycémique du pain et facilitent l['']assimilation du fer et du zinc présents dans la farine\.", "On sait que certaines fermentations longues réduisent l'index glycémique du pain et facilitent l'assimilation des minéraux."),
        # Neurosciences histoires
        (r"Des recherches en neurosciences ont démontré que lorsqu['']une personne entend une histoire, son cerveau s['']active de façon beaucoup plus étendue que lorsqu['']elle reçoit une information factuelle\. \[pause\] Les zones sensorielles, émotionnelles et motrices s['']illuminent en même temps que les zones de traitement du langage\.", "Quand une personne entend une histoire, son cerveau s'active bien plus largement que face à une information factuelle."),
        # Files d'attente
        (r"Des études en psychologie des files d['']attente montrent que la perception de l['']attente est plus importante que sa durée réelle\. \[pause\]", ""),
        # 75% traçabilité
        (r"Des études réalisées montrent que plus de soixante-quinze pour cent des acheteurs de produits artisanaux déclarent accorder une importance significative à la connaissance de la provenance des ingrédients\. \[pause\]", ""),
        # Micro-expressions
        (r"Les chercheurs en psychologie des expressions faciales ont consacré plus de quarante ans à l['']étude de ce phénomène\. \[pause\]", ""),
        (r"Des contractions musculaires involontaires du visage qui durent entre un vingtième et un cinquième de seconde\.", "Des contractions musculaires involontaires du visage, fugaces."),
        # Expérience commerce fictif
        (r"Il y a une expérience menée par des chercheurs en psychologie sociale qui illustre parfaitement ce dont on parlait sur les excuses sincères\. \[pause\] Des participants avaient vécu une mauvaise expérience simulée dans un commerce fictif\. \[pause\] On leur a ensuite proposé différents types de réponses de la part du commerce\.", "Voici ce qu'on observe sur les excuses sincères."),
        # Psychologie sociale réciprocité différée (règle)
        (r"\[pause\] Voyons maintenant quelque chose qu['']on appelle en psychologie sociale la règle de la réciprocité\.", "[pause] Parlons du principe de réciprocité."),
        # Norme réciprocité différée
        (r"\[pause\] Parlons d['']abord d['']un concept que la psychologie sociale appelle la norme de réciprocité différée\.", "[pause] Parlons de la réciprocité différée."),
    ]

    for pattern, replacement in study_intros:
        text = re.sub(pattern, replacement, text)

    # ── 2. CHIFFRES PRÉCIS NON SOURCÉS ──────────────────────────────────────
    chiffres = [
        # 15% panier boulangerie
        (r"En six mois, le panier moyen de cette boulangerie avait augmenté de près de quinze pour cent\.", ""),
        # 10% réduction bûche
        (r"avec une réduction supplémentaire de dix pour cent\.", "avec un geste commercial."),
        # Aversion à la perte "deux fois"
        (r"est environ deux fois plus intense que le plaisir d['']en gagner autant", "est nettement plus intense que le plaisir d'en gagner autant"),
        # Caisse 20s / 50 clients / 17 min
        (r"Les clients qui payaient par carte prenaient en moyenne vingt secondes de plus \[pause\] que ceux qui payaient en espèces\. \[pause\] Et ces vingt secondes, multipliées par cinquante clients, \[pause\] ça représentait près de dix-sept minutes de temps d['']attente cumulé pour la file\.", "Les clients qui payaient par carte prenaient davantage de temps, ce qui rallongeait sensiblement la file."),
        (r"le temps moyen par client a baissé de dix secondes\. \[pause\] Et ces dix secondes, multipliées par cinquante clients, \[pause\] ont réduit la file d['']attente visible de presque dix minutes\.", "le temps moyen par client a sensiblement diminué, réduisant visiblement la file d'attente."),
        # 16% McDonald's
        (r"augmente de seize pour cent\. \[pause\] Seize pour cent\.", "augmente significativement."),
        # 65% Bäckerei Hofmann
        (r"un taux d['']acceptation des suggestions de près de soixante-cinq pour cent\.", "un taux d'acceptation des suggestions remarquablement élevé."),
        # Marc Bordeaux 22%
        (r"de vingt-deux pour cent\.", "de façon notable."),
        # Marc Bordeaux formules %
        (r"La formule légère : soixante pour cent des ventes\. La formule gourmande : trente-cinq pour cent\. La formule complète : à peine cinq pour cent\.", "La formule légère domine largement les ventes, la formule gourmande vient en second, la formule complète reste très peu choisie."),
        (r"Les ventes de la formule gourmande augmentent de douze pour cent\.", "Les ventes de la formule gourmande augmentent nettement."),
        # Isabelle Nantes 38%
        (r"dépassait de trente-huit pour cent le panier moyen des achats en boutique", "dépassait largement le panier moyen des achats en boutique"),
        # Vincennes 8%
        (r"le panier moyen avait augmenté de huit pour cent en deux semaines\.", "le panier moyen avait augmenté en deux semaines."),
        # Lille 19%
        (r"le chiffre d['']affaires associé à ces suggestions additionnelles représentait dix-neuf pour cent du chiffre d['']affaires total de la boutique\. \[pause\] Dix-neuf pour cent de chiffre d['']affaires supplémentaire", "le chiffre d'affaires associé à ces suggestions additionnelles représentait une part significative du chiffre d'affaires total de la boutique"),
        # Paris tableau noir 70%
        (r"dans près de soixante-dix pour cent des cas chez les clients qui la lisaient avant de commander\. Soixante-dix pour cent\.", "dans la grande majorité des cas chez les clients qui la lisaient avant de commander."),
        # Starbucks 23%
        (r"un barista qui pratique le suggestive selling de façon naturelle génère en moyenne vingt-trois pour cent de chiffre d['']affaires supplémentaire par heure travaillée par rapport à un barista qui ne le pratique pas\. \[pause\] Vingt-trois pour cent\.", ""),
        # Marseille 62%
        (r"était de soixante-deux pour cent\.", "était remarquablement élevé pour une nouvelle boutique."),
        # Toulouse 41%
        (r"était de quarante et un pour cent\. \[pause\] Quarante et un pour cent des clients qui appelaient repartaient avec une suggestion acceptée\.", "était remarquablement élevé."),
        # ERIC 43%-19%-11pts
        (r"Les réclamations escaladées vers les managers avaient diminué de quarante-trois pour cent\. \[pause\] Les avis négatifs en ligne avaient diminué de dix-neuf pour cent\. \[pause\] Et la satisfaction client mesurée sur les bornes en caisse avait augmenté de onze points\.", ""),
        # Rush 150 clients calcul
        (r"Et si votre boutique sert cent cinquante clients pendant le rush du matin, vingt-cinq ventes additionnelles supplémentaires, même à deux euros chacune, ça représente cinquante euros de chiffre d['']affaires additionnel\. Sur un mois de rushes matinaux, c['']est entre huit cents et mille euros supplémentaires\.", ""),
        # Paniers composites 30-60%
        (r"a généralement un taux inférieur à trente pour cent\.", "pratique peu la vente additionnelle."),
        (r"peut atteindre cinquante à soixante pour cent\.", "peut atteindre des taux bien plus élevés."),
        # Sophie Lyon 2×
        (r"deux fois supérieur à celui de ses collègues", "nettement supérieur à celui de ses collègues"),
    ]

    for pattern, replacement in chiffres:
        text = re.sub(pattern, replacement, text)

    # ── 3. EXEMPLES FICTIFS AVEC LIEUX (ajouter disclaimer) ─────────────────
    lieux_patterns = [
        # Jour 1
        (r"(il y a un retour d['']expérience très intéressant \[pause\] d['']une boulangerie de Lyon \[pause\])", r"Prenons un exemple fictif : \1"),
        (r"(Il y a une boulangerie à Bordeaux \[pause\])", r"Prenons un exemple fictif : \1"),
        (r"(voici un retour d['']expérience d['']une gérante de boulangerie en Seine-Saint-Denis)", r"Prenons un exemple fictif : \1"),
        (r"(C['']est l['']histoire d['']un boulanger de Bretagne\.)", r"Prenons un exemple fictif. \1"),
        (r"(C['']est l['']histoire d['']une boulangerie familiale à Strasbourg\.)", r"Prenons un exemple fictif. \1"),
        (r"(Une boulangerie de Marseille \[pause\] avait un problème récurrent le vendredi soir\.)", r"Prenons un exemple fictif : \1"),
        (r"(Une boulangerie lyonnaise avait un problème récurrent\.)", r"Prenons un exemple fictif : \1"),
        # Jour 2
        (r"(On est dans les années quatre-vingt-dix, à Munich\.)", r"Prenons un exemple fictif : \1"),
        (r"(J['']ai rencontré une vendeuse, appelons-la Sophie, dans une boulangerie artisanale de Lyon\.)", r"Prenons un exemple fictif : \1"),
        (r"(On est en 2015\. Une boulangerie artisanale de quartier à Bordeaux)", r"Prenons un exemple fictif : \1"),
        (r"(Une boulangerie artisanale de Nantes, que ses clients appellent affectueusement la boulangerie du coin)", r"Prenons un exemple fictif : \1"),
        (r"(une boulangerie artisanale en région parisienne, à Vincennes)", r"Prenons un exemple fictif : \1"),
        (r"(Une boulangerie de Lille a mis en place une approche très réfléchie)", r"Prenons un exemple fictif : \1"),
        (r"(Dans une boulangerie de Lyon que j['']ai eu l['']occasion de suivre de près)", r"Prenons un exemple fictif : \1"),
        (r"(On est à Paris, en 2018\. Une boulangerie du onzième arrondissement)", r"Prenons un exemple fictif : \1"),
        (r"(J['']ai rencontré un boulanger, appelons-le Henri, qui tient une boulangerie dans un village de l['']Auvergne)", r"Prenons un exemple fictif : \1"),
        (r"(Une boulangerie qui a ouvert à Marseille en 2019, dans le quartier de la Plaine)", r"Prenons un exemple fictif : \1"),
        (r"(une boulangerie artisanale à Toulouse)", r"Prenons un exemple fictif : \1"),
        (r"(Une boulangerie de Bordeaux a développé un système d['']intégration)", r"Prenons un exemple fictif : \1"),
        (r"(dans une boulangerie du septième arrondissement de Paris, j['']observe une vendeuse)", r"Prenons un exemple fictif : \1"),
        (r"(Une boulangerie de Nantes avait une tarte au citron meringuée)", r"Prenons un exemple fictif : \1"),
        (r"(J['']ai rencontré un boulanger, appelons-le Erwan, qui avait développé une gamme)", r"Prenons un exemple fictif : \1"),
        (r"(Un jeune vendeur, appelons-le Théo, vient d['']être embauché dans une boulangerie artisanale réputée du onzième arrondissement de Paris\.)", r"Prenons un exemple fictif : \1"),
        (r"(une boulangerie artisanale à Lyon [^.]*ambassadrice)", r"Prenons un exemple fictif : \1"),
        (r"(une vendeuse dans une boulangerie de Bordeaux [^.]*fin de journée)", r"Prenons un exemple fictif : \1"),
        (r"(Un responsable de boulangerie en région parisienne, quinze ans d['']expérience)", r"Prenons un exemple fictif : \1"),
        (r"(Une vendeuse dans une boulangerie alsacienne)", r"Prenons un exemple fictif : \1"),
        (r"(Une boulangerie dans le dix-neuvième arrondissement de Paris)", r"Prenons un exemple fictif : \1"),
        (r"(Une boulangerie dans une ville du sud de la France)", r"Prenons un exemple fictif : \1"),
    ]

    for pattern, replacement in lieux_patterns:
        text = re.sub(pattern, replacement, text)

    # ── 4. NETTOYAGE FINAL ──────────────────────────────────────────────────
    # Éviter doubles "Prenons un exemple fictif"
    text = re.sub(r"(Prenons un exemple fictif[^:]*:?\s*)+Prenons un exemple fictif", "Prenons un exemple fictif", text)
    # Espaces multiples
    text = re.sub(r"  +", " ", text)
    # Lignes vides multiples
    text = re.sub(r"\n{3,}", "\n\n", text)

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    changes = sum(1 for a, b in zip(original.split("\n"), text.split("\n")) if a != b)
    print(f"✓ {path}")
    print(f"  Lignes modifiées : ~{changes}")
    print(f"  Taille avant : {len(original)} car | après : {len(text)} car")


if __name__ == "__main__":
    files = [
        "/Users/amelle/Desktop/SocrateReprise/LeSocrate/output_jour1/reformulated_text.txt",
        "/Users/amelle/Desktop/SocrateReprise/LeSocrate/output_jour2/reformulated_text.txt",
    ]
    for f in files:
        fix_file(f)
        print()
