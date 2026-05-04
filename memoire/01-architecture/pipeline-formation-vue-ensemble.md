# Pipeline Formation Automatisé — Vue d'ensemble

**Date** : 2026-04-16 → 2026-04-17
**Thématique** : architecture
**Statut** : actif (itératif)

## Contexte

Le Socrate est une plateforme de formation en ligne délivrant des cours audio synchronisés (playlist MP3 horodatée). L'objectif pédagogique est d'avoir pour chaque titre professionnel (TP) un programme de formation complet, découpé en journées, généré automatiquement en TTS.

Avant le pipeline automatisé, chaque formation demandait un effort manuel conséquent : extraction de contenu depuis les PDFs métier, structuration en journées, génération TTS cours par cours. Non scalable.

## Problème / Question

Comment transformer un code RNCP (identifiant officiel d'un titre professionnel en France) en une formation audio complète, sans intervention humaine ?

## Options envisagées

1. **Pipeline linéaire** (retenu) : RNCP → REAC PDF → programme global → split journalier → TTS 3 passes
2. **Édition manuelle assistée** : l'utilisateur uploade les PDFs, IA propose une structure, l'utilisateur valide à chaque étape (trop lent, non scalable)
3. **Pipeline entièrement généré par un seul prompt** : donner REAC entier à Claude et demander la formation complète d'un coup (échec qualité : contexte de sortie trop long, pas de contrôle intermédiaire)

## Décision finale

**Pipeline modulaire 5 étapes avec validation humaine aux points critiques** (validation à terme optionnelle quand l'automatisation sera mature) :

1. **Recherche RNCP & initialisation** — scraping France Compétences pour retrouver le titre
2. **Téléchargement sources** — REAC PDF (obligatoire), RC + ROME tentés mais optionnels
3. **Programme global** — génération par Claude Sonnet 4 d'un programme structuré depuis le REAC
4. **Split journalier** — découpage en N journées × 6 sous-parties, génération parallèle
5. **Génération TTS** — pipeline from-scratch 3 passes (Fondation / Expansion / Enrichissement) + assemblage playlist 19 fichiers

## Rationale technique

- **Modularité** = capacité à relancer/retry une étape sans tout recommencer (checkpointing DB via `formation_pipeline_jobs`)
- **Validations intermédiaires** = qualité contrôlée à chaque étape (l'utilisateur peut éditer programme global et journalier)
- **Choix du modèle par étape** : Sonnet par défaut, Haiku disponible pour test rapide/coût réduit
- **Une plateforme par pipeline** (cf. [mémo dédié](./multi-tenant-plateforme-par-pipeline.md)) : chaque formation crée son propre module isolé

## Références code

- `backend/services/formation_pipeline_service.py` — orchestration pipeline (927 lignes)
- `backend/routes/formation_routes.py` — 10 routes admin (`/api/formation/*`)
- `backend/database/db.py` — table `formation_pipeline_jobs`
- `frontend/src/pages/FormationPipeline.jsx` — UI stepper + éditeur
- `CHANGELOG.md` 2026-04-16 — feature initiale

## Leçons / Pour le mémoire

- **L'automatisation totale vs. humain-dans-la-boucle** est un spectre, pas un binaire. On a commencé avec humain-dans-la-boucle à chaque étape pour vérifier la qualité, avec l'objectif à terme de retirer progressivement les points de validation.
- **Le checkpointing DB est non négociable** quand une étape peut prendre 2-5 minutes : sans lui, chaque échec réseau force à tout recommencer. Apprentissage clé pour tout pipeline IA long.
- **Séparation claire "sources externes / traitement / sortie"** : les 3 phases ont des modes de défaillance très différents. Les mélanger rendrait le debugging impossible.
