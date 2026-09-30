# Doublon entre introduction de journée et introduction du premier thème

**Date** : 2026-05-25
**Thématique** : problème | pédagogie | génération structurée
**Statut** : résolu partiellement, à surveiller

## Contexte

La première journée de formation est particulièrement sensible. Elle doit poser :

- le cadre général de la formation ;
- le sens du métier ;
- la logique de la journée ;
- les grands thèmes ;
- puis seulement le premier thème détaillé.

Dans le nouveau workflow structuré, le système génère à la fois :

- une ouverture de journée ;
- une ouverture du premier thème ;
- un plan détaillé du premier thème.

## Problème / Question

Un résultat observé répétait deux fois l'introduction de la journée. Le script
semblait recommencer à poser le cadre général au moment d'entrer dans le premier
thème.

Le problème venait d'une frontière floue :

- l'introduction de journée doit donner la carte globale ;
- l'ouverture du premier thème doit faire le lien et entrer dans le sujet ;
- elle ne doit pas refaire l'accueil, le programme annuel ou tout le programme de
  journée.

## Symptômes

Le texte produit pouvait enchaîner :

1. une introduction générale de la journée ;
2. une nouvelle annonce générale de la journée ;
3. puis seulement le premier thème.

Cela donne une impression de boucle :

- le formateur "recommence" ;
- les apprenants entendent deux cadrages similaires ;
- la progression tarde à démarrer ;
- la première partie semble artificielle.

## Cause probable

La cause n'est pas seulement une phrase mal formulée. Elle vient du chevauchement de
responsabilités entre deux sections.

Si le plan ne précise pas fortement le rôle de chaque ouverture, le LLM remplit
naturellement les deux avec des éléments similaires :

- accueil ;
- objectifs ;
- programme ;
- annonce des thèmes ;
- mise en contexte.

Le problème est accentué par le fait que le premier thème a lui aussi besoin d'un
cadrage. Sans garde-fou, ce cadrage ressemble trop à l'introduction de journée.

## Décision finale

Séparer explicitement les fonctions :

### Introduction de journée

Elle doit :

- accueillir ;
- situer la journée dans la formation ;
- annoncer les grands thèmes ;
- donner le fil conducteur ;
- rester synthétique.

Elle ne doit pas entrer trop profondément dans le premier thème.

### Ouverture du premier thème

Elle doit :

- faire une transition courte depuis le cadre général ;
- annoncer le thème ;
- poser la question centrale ;
- annoncer les axes du thème ;
- commencer le premier point.

Elle ne doit pas :

- refaire l'accueil ;
- réannoncer toute la journée ;
- redire le programme annuel ;
- reparler des horaires ;
- repartir de zéro.

## Formulation cible

Style attendu pour le début du premier thème :

> Maintenant que le cadre général de la journée est posé, on peut entrer dans le
> premier grand thème. On va commencer par les bases de la communication à distance,
> et surtout par la posture professionnelle qui l'accompagne.

Cette phrase reconnaît que le cadre existe déjà. Elle ne le répète pas.

## Contrôle qualité à maintenir

La review d'adhérence au plan doit détecter :

- deux introductions générales successives ;
- un premier thème qui refait le programme de journée ;
- un opening qui mentionne encore la formation annuelle hors de son rôle ;
- une entrée en matière trop longue avant le premier point ;
- une répétition des mêmes objectifs dans deux sections voisines.

## Références code

- `backend/prompts/generation/structured-plan.md`
- `backend/prompts/generation/structured-section.md`
- `backend/prompts/reviews/plan-adherence-audit.md`
- `backend/prompts/reviews/plan-adherence-repair.md`
- `backend/services/content_generation_service.py`
- `backend/services/content_pipeline/validators.py`

## Leçons / Pour le mémoire

Une génération segmentée améliore le contrôle, mais crée un nouveau risque :
l'overlap entre sections. Chaque section doit avoir un rôle pédagogique exclusif.

La qualité ne vient donc pas seulement du contenu de chaque bloc, mais de la
distribution correcte des responsabilités entre blocs.
