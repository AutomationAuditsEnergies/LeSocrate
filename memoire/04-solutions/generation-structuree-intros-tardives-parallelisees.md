# Génération structurée — intros tardives, quality loop et parallélisation

**Date** : 2026-05-25
**Thématique** : solution | performance | qualité
**Statut** : actif

## Contexte

Après la refonte en plan JSON, la pipeline de contenu est devenue plus robuste, mais
plus prudente. Le premier mode structuré générait les cours dans l'ordre :

1. plan JSON ;
2. cours 1 ;
3. résumé du cours 1 ;
4. cours 2 ;
5. résumé du cours 2 ;
6. etc.

Cette séquence améliorait la continuité, mais elle ralentissait fortement la
pipeline. La question était donc : comment accélérer sans perdre la qualité des
raccords pédagogiques ?

## Problème / Question

La génération d'un cours complet est coûteuse en temps, car elle appelle l'IA pour
plusieurs sections et pour le calibrage. Générer 7 cours strictement en série impose
d'attendre la fin de chaque cours avant de commencer le suivant.

Mais paralléliser naïvement les 7 cours crée un risque de qualité :

- les reprises après pause peuvent devenir génériques ;
- le cours 2 peut ne plus faire référence correctement au cours 1 ;
- les introductions peuvent être écrites sans connaître le contenu réel ;
- la conclusion globale de journée peut résumer un plan théorique plutôt que les
  cours effectivement produits.

## Idée retenue

La solution est de déplacer les parties sensibles dans le temps :

1. générer le plan JSON complet ;
2. générer en parallèle les contenus principaux des cours ;
3. résumer les vrais contenus générés ;
4. générer ensuite les introductions et reprises ;
5. générer tardivement la conclusion globale de journée ;
6. assembler ;
7. calibrer ;
8. auditer l'adhérence au plan ;
9. humaniser ;
10. vérifier la conformité.

Autrement dit : les corps de cours sont parallélisés, mais les raccords sont écrits
après coup avec le recul nécessaire.

## Décision finale

La stratégie retenue est nommée :

`parallel_body_then_late_opening`

Elle repose sur quatre principes.

### 1. Les sections internes d'un cours restent séquentielles

On ne génère pas `part_1`, `part_2`, `part_3` en parallèle à l'intérieur d'un même
cours. Cela préserverait mal la progression locale.

Dans un cours, les sections principales restent donc générées dans l'ordre :

- partie 1 ;
- partie 2 ;
- partie 3 ou 4 ;
- conclusion du cours.

### 2. Les cours sont parallélisés entre eux

Les 7 cours peuvent être générés en parallèle, avec une limite de concurrence.

Valeur par défaut :

`FORMATION_STRUCTURED_COURSE_WORKERS=3`

Ce choix vise le compromis :

- assez de parallélisme pour gagner du temps ;
- pas trop pour éviter les rate limits API ;
- pas de parallélisation interne excessive qui dégraderait la cohérence.

### 3. Les introductions sont générées tardivement

L'introduction ou reprise de chaque cours est générée après les corps de cours.

Elle reçoit :

- le plan verrouillé du cours ;
- le contenu principal déjà généré du cours actuel ;
- le résumé réel du cours précédent ;
- le module source ;
- les contraintes d'ouverture.

Cela permet de faire une ouverture qui sonne comme le début du cours, mais qui
s'appuie sur le vrai contenu produit.

Cas typique du cours 2 :

- le vocal précédent dit que la pause est terminée ;
- le cours 2 doit reprendre naturellement ;
- il rappelle brièvement ce qui a été vu ;
- il fait le lien avec le nouveau thème ;
- il annonce le plan avant les exemples.

### 4. La conclusion globale de journée est aussi générée tardivement

Pour le cours 7, la conclusion globale ne doit pas résumer seulement le plan prévu.
Elle doit s'appuyer sur les contenus réellement générés dans la journée.

La pipeline génère donc un contexte de synthèse à partir des résumés réels des cours
1 à 7, puis écrit la conclusion de journée à la fin.

## Quality repair loop

Une review dédiée intervient avant humanisation :

`plan-adherence review`

Elle suit une boucle :

1. audit ciblé ;
2. si problème, correction IA ciblée ;
3. réaudit ;
4. recalibrage si le budget mots bouge.

Types de problèmes traités :

- cours trop court : enrichissement pertinent ;
- cours trop long : réduction propre ;
- répétitions : déduplication ;
- conclusion cassée : correction de fin ;
- contenu après Q/R : suppression ou fusion propre ;
- intro incohérente : réécriture ciblée ;
- cours qui termine le précédent : recentrage ;
- cours qui démarre le suivant : suppression du débordement.

La pipeline ne doit pas échouer simplement parce qu'un cours dépasse ou manque de
mots. Elle appelle l'IA pour réparer et retente.

## Rationale technique

### Pourquoi cela accélère

La partie longue est la génération IA. En série, 7 cours attendent les uns après les
autres. Avec 3 workers, la pipeline peut produire plusieurs cours en même temps.

Le gain attendu n'est pas un facteur 7, car il reste :

- la planification ;
- les résumés ;
- les intros tardives ;
- le calibrage ;
- les reviews ;
- l'audio.

Mais la grosse masse de génération est désormais parallélisée.

### Pourquoi cela ne doit pas dégrader la qualité

La qualité aurait baissé si les intros étaient générées avant de connaître le vrai
contenu. La solution évite cela :

- les corps sont indépendants ;
- les introductions ont besoin du cours précédent ;
- donc les introductions sont générées après les résumés.

On gagne en vitesse sur ce qui est parallélisable, tout en gardant du séquentiel sur
ce qui porte la continuité pédagogique.

### Pourquoi ne pas transmettre les autres cours complets

La réduction ou réparation d'un cours ne reçoit pas les autres cours complets.

Raisons :

- limiter le contexte ;
- éviter les contaminations ;
- éviter qu'un cours finisse ou démarre un autre cours ;
- garder un périmètre clair ;
- réduire les coûts.

Le seul contexte inter-cours utile est un résumé court du cours précédent, pour les
reprises.

## Artefacts produits

La stratégie est visible dans les artefacts :

- `content-draft-sections.json` indique les sections générées et les intros tardives ;
- `content-course-scripts.json` indique `generation_strategy` et les résumés utilisés ;
- `content-quality-reviews.json` garde les audits et réparations ;
- `content-script-plan.json` garde le plan compatible UI ;
- `content-audio-plan.json` indique le texte audio final.

## Références code

- `backend/services/content_generation_service.py`
  - `_run_structured_content_generation`
  - `_generate_structured_course_body`
  - `_generate_late_opening_for_structured_course`
  - `_generate_late_day_conclusion_for_structured_course`
  - `_run_structured_parallel`
  - `run_plan_adherence_review`
- `backend/services/content_pipeline/artifacts.py`
- `backend/prompts/reviews/plan-adherence-audit.md`
- `backend/prompts/reviews/plan-adherence-repair.md`
- Variable d'environnement :
  - `FORMATION_STRUCTURED_COURSE_WORKERS`
- Commits liés :
  - `c71691a` — Add plan adherence quality review
  - `460bac0` — Parallelize structured course generation

## Leçons / Pour le mémoire

Cette solution illustre un principe important d'ingénierie IA : tout ne doit pas
être parallélisé. Il faut distinguer :

- les tâches indépendantes, parallélisables ;
- les tâches de raccord, qui exigent un contexte réel ;
- les tâches de contrôle, qui vérifient après coup.

Le résultat est une architecture hybride : rapide sur les gros volumes, prudente sur
les transitions pédagogiques.

