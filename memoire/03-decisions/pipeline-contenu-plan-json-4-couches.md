# Pipeline contenu — plan JSON et 4 couches de prompts/reviews

**Date** : 2026-05-25
**Thématique** : décision | architecture | qualité
**Statut** : actif

## Contexte

La génération de contenu TTS reposait historiquement sur plusieurs couches de
prompting :

1. prompts généraux pour le contenu de la formation ;
2. prompts particuliers par cours ;
3. prompt de revérification conformité ;
4. prompt de revérification humanisation.

Cette architecture avait une intuition correcte : séparer les intentions. Mais elle
devenait insuffisante pour garantir une formation longue, structurée, calibrée au
mot près et facile à auditer.

## Problème / Question

La question était double :

- ces 4 couches sont-elles encore utiles ?
- faut-il les garder telles quelles ou réinventer le mécanisme autour d'un artefact
  plus strict ?

La difficulté venait du fait que le mot "prompt" recouvrait plusieurs fonctions
différentes :

- cadrer le style général ;
- choisir une progression pédagogique ;
- générer un cours ;
- réparer un budget mots ;
- vérifier la conformité ;
- humaniser légèrement ;
- vérifier l'adhérence au plan.

Tout mettre dans quelques prompts longs rendait la pipeline difficile à maintenir
et à diagnostiquer.

## Options envisagées

### Option A — Garder les 4 couches sans changement

Avantage : continuité avec l'existant.

Limite : les couches restent trop floues. Le modèle peut respecter localement une
consigne tout en ratant la progression globale.

### Option B — Supprimer certaines couches

Avantage : pipeline plus courte.

Limite : la qualité finale baisse. La conformité, l'oralité et l'architecture
pédagogique ne contrôlent pas les mêmes risques.

### Option C — Garder les 4 intentions, mais changer le support

Décision retenue : les 4 couches restent utiles, mais elles ne doivent plus être
seulement des prompts monolithiques. Elles deviennent des étapes spécialisées autour
d'un plan JSON verrouillé.

## Décision finale

Le plan JSON devient la source de vérité. Les 4 couches sont réinterprétées ainsi :

### 1. Prompt général

Rôle : fixer le style pédagogique global.

Il définit :

- ton oral professionnel ;
- clarté ;
- registre accessible ;
- exemples fictifs si non sourcés ;
- absence de jargon interne ;
- interdiction de verbaliser les contraintes techniques ;
- logique TTS-ready.

Fichiers :

- `backend/prompts/generation/base-course-style.md`
- ancien fallback : `backend/prompts/prompts-generaux-contenu-formation.md`

### 2. Prompt particulier par cours

Rôle : ne plus être un simple supplément de texte, mais une section du plan JSON.

Chaque cours reçoit :

- `course_number` ;
- `course_title` ;
- `pedagogical_role` ;
- `opening` ;
- `parts` ;
- `course_conclusion` ;
- `day_conclusion` si cours 7 ;
- budgets mots ;
- contraintes d'introduction et de conclusion.

Le modèle peut choisir librement 2 à 4 parties pendant la création du plan. Après
validation, ce plan devient obligatoire.

### 3. Revérification conformité

Rôle : vérifier la conformité stricte sans réinventer le cours.

Elle doit corriger :

- violations éthiques ;
- exemples non sourcés ;
- promesses irréalistes ;
- jargon interne côté apprenant ;
- formulations problématiques ;
- incohérences réglementaires ou de prudence.

Elle ne doit pas changer le plan verrouillé.

Fichiers :

- `backend/prompts/reviews/compliance-review.md`
- `backend/prompts/reviews/compliance-rules.json`

### 4. Revérification humanisation

Rôle : finition orale légère.

La review humanisation ne doit plus restructurer le cours. Elle intervient après le
plan, la génération sectionnée et la review d'adhérence au plan.

Elle corrige seulement :

- rythme trop sec ;
- phrase trop mécanique ;
- transition locale faible ;
- oralité trop écrite ;
- manque de respiration ;
- densité excessive.

Fichiers :

- `backend/prompts/reviews/humanization-polish.md`
- `backend/prompts/reviews/humanization-rules.json`

## Ajout d'une 5e couche : adhérence au plan

La discussion a montré qu'il manquait une review entre génération et humanisation :

`plan-adherence review`

Son rôle :

- vérifier que le cours respecte son plan ;
- vérifier que les parties sont dans l'ordre ;
- vérifier que la conclusion ferme vraiment ;
- vérifier qu'il n'y a pas de contenu après Q/R ;
- vérifier que le cours ne finit pas le précédent ;
- vérifier que le cours ne démarre pas le suivant ;
- détecter répétitions et problèmes de budget.

Cette couche est volontairement différente de la conformité et de l'humanisation.
Elle traite la qualité pédagogique structurelle.

## Rationale technique

Un plan JSON strict apporte trois avantages.

### 1. Inspectabilité

Chaque étape produit un artefact :

- `content-plan.json` ;
- `content-draft-sections.json` ;
- `content-course-scripts.json` ;
- `content-quality-reviews.json` ;
- `content-reviewed-scripts.json` ;
- `content-audio-plan.json` ;
- `content-script-plan.json`.

Si un problème apparaît, on peut savoir s'il vient :

- du plan ;
- d'une section ;
- de l'assemblage ;
- du calibrage ;
- de l'adhérence au plan ;
- de l'humanisation ;
- de la conformité ;
- de l'audio.

### 2. Rejouabilité

Une étape peut être relancée sans tout réinventer. Par exemple :

- garder le plan ;
- régénérer une section ;
- recalibrer un cours ;
- refaire une review ;
- reconstruire l'audio.

### 3. Meilleure séparation des responsabilités

Le modèle n'a plus une seule mission globale. Il reçoit des missions plus courtes :

- planifier ;
- écrire une section ;
- réduire ou enrichir ;
- auditer ;
- réparer ;
- polir ;
- vérifier.

Cela réduit les dérives typiques des prompts longs.

## Références code

- `backend/services/content_generation_service.py`
- `backend/services/content_pipeline/artifacts.py`
- `backend/services/content_pipeline/validators.py`
- `backend/services/content_pipeline/prompts.py`
- `backend/prompts/generation/base-course-style.md`
- `backend/prompts/generation/structured-plan.md`
- `backend/prompts/generation/structured-section.md`
- `backend/prompts/generation/budget-rewrite.md`
- `backend/prompts/reviews/compliance-review.md`
- `backend/prompts/reviews/humanization-polish.md`
- `backend/prompts/reviews/plan-adherence-audit.md`
- `backend/prompts/reviews/plan-adherence-repair.md`
- Commits liés :
  - `5ecc320` — Modularize generation and review prompts
  - `7b5e934` — Refactor content pipeline helpers
  - `c71691a` — Add plan adherence quality review

## Leçons / Pour le mémoire

Le terme "prompt" est trop pauvre pour décrire l'architecture finale. Le système
fonctionne plutôt comme une chaîne d'artefacts et de contrats :

- le plan décide ;
- la génération exécute ;
- le calibrage ajuste ;
- l'audit vérifie ;
- la réparation corrige ;
- l'humanisation polit ;
- la conformité sécurise.

Cette séparation est un point fort pour le mémoire : elle montre le passage d'un
simple prompting à une ingénierie de pipeline pédagogique.

