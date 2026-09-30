# Micro-conformité éthique locale avant les reviews globales

**Date** : 2026-05-25
**Thématique** : décision | conformité | qualité
**Statut** : actif

## Contexte

La pipeline possède déjà une conformité finale. Elle vérifie les hallucinations, les
règles TTS, les formulations problématiques, les contraintes éthiques et
l'architecture globale.

Mais une question s'est posée : pour les règles éthiques strictes, faut-il attendre
la fin du cours complet ou intervenir plus tôt, juste après la génération d'une
portion de texte ?

## Problème / Question

Une conformité globale en fin de pipeline a plusieurs limites :

- le texte est long ;
- les violations peuvent être localisées ;
- les corrections peuvent devenir trop larges ;
- le LLM peut rater des règles par dilution d'attention ;
- il est difficile d'expliquer précisément ce qui a été corrigé.

Le besoin exprimé était d'avoir une "salle de conformité" éthique qui agit sur de
petites portions, pas un audit massif qui transforme tout le cours.

## Options envisagées

### Option A — Tout faire en conformité finale

Avantage :

- pipeline plus simple ;
- un seul endroit pour corriger.

Limite :

- moins précis ;
- plus risqué ;
- plus difficile à auditer ;
- corrections potentiellement trop tardives.

### Option B — Micro-review éthique section par section

Avantage :

- contexte court ;
- détection plus précise ;
- patchs localisés ;
- traçabilité avant/après ;
- moins de risque de casser la structure globale.

Limite :

- ajoute des appels API ;
- nécessite un artefact de suivi ;
- ne remplace pas la conformité finale.

Décision retenue : option B.

## Décision finale

La micro-conformité éthique est appliquée après génération de section, sur les règles
éthiques strictes #1 à #16.

Elle produit un rapport local :

- section concernée ;
- texte original ;
- texte corrigé ;
- règle violée ;
- passage problématique ;
- remplacement proposé ;
- statut du patch ;
- raison si un patch est rejeté.

La conformité finale reste nécessaire ensuite, mais elle ne porte plus seule toute la
charge éthique.

## Rationale technique

Les règles éthiques doivent être traitées tôt parce qu'elles sont substantielles. Une
fois le texte assemblé, humanisé et calibré, une correction éthique peut perturber :

- le budget mots ;
- la cohérence d'une partie ;
- les transitions ;
- les exemples ;
- le futur audio.

Sur une section courte, le modèle peut corriger précisément sans réécrire tout le
cours.

## Relation avec les autres reviews

Ordre logique :

1. génération de section ;
2. micro-conformité éthique ;
3. assemblage ;
4. calibrage ;
5. adhérence au plan ;
6. humanisation orale ;
7. conformité finale.

La micro-review corrige les risques éthiques locaux. La conformité finale contrôle
le produit fini.

## Références code

- `backend/prompts/reviews/ethical-micro-review.md`
- `backend/prompts/reviews/compliance-rules.json`
- `backend/services/content_generation_service.py`
  - `_run_ethical_micro_review_for_section`
  - `_record_ethical_micro_review`
  - `_ethical_micro_review_summary`
- `backend/services/content_pipeline/artifacts.py`
  - `content-ethical-micro-review.json`
- `frontend/src/pages/FormationPipeline.jsx`
- Commit lié :
  - `e48d2b1` — Add clickable pipeline audit modals

## Leçons / Pour le mémoire

La conformité IA ne doit pas être pensée comme une seule barrière finale. Les risques
éthiques, pédagogiques, stylistiques et techniques ne se contrôlent pas au même
moment.

La micro-conformité illustre une stratégie de contrôle local : corriger tôt,
documenter précisément, puis auditer globalement.
