# Multi-tenant : une plateforme par pipeline de formation

**Date** : 2026-04-16
**Thématique** : architecture
**Statut** : résolu

## Contexte

Le Socrate est historiquement multi-tenant avec 4 plateformes fixes (P1, P2, P3, P4). Chaque plateforme = ses containers Azure Blob, ses utilisateurs, sa configuration horaire. Quand le pipeline formation a été introduit, la première implémentation versait les cours générés dans une plateforme existante (P1 par défaut), ce qui polluait le contenu de référence et mélangeait les formations.

## Problème / Question

Où versent les cours générés par le pipeline ? Doivent-ils rejoindre une plateforme existante ou créer un espace dédié ?

## Options envisagées

1. **Verser dans une plateforme existante (P1/P2/P3/P4)** — Simple, pas de changement DB. Mais pollution des plateformes référence, risque d'écrasement, impossible de gérer plusieurs promos en parallèle.
2. **Créer un espace éphémère "sandbox"** pour chaque pipeline — Évite la pollution mais perd les cours à la fin.
3. **Créer une nouvelle plateforme permanente à chaque pipeline** (retenu) — Chaque formation = son propre module isolé, durable, réutilisable.

## Décision finale

Chaque création de pipeline demande à l'utilisateur un **nom de plateforme**. Le backend :
1. Crée une nouvelle ligne dans `platform_config` avec ce nom
2. Auto-génère les noms de containers Azure (`formationaudio-p{id}`, `formationpdf-p{id}`, `formationaudio-p{id}-archives`)
3. Crée le job pipeline lié à ce nouveau `platform_id`
4. À la fin du TTS, les `cours_folders` sont créés dans cette nouvelle plateforme

L'utilisateur retrouve ses cours dans **HR Dashboard → Cours Folders** en sélectionnant son nouveau module.

## Rationale technique

- **Isolation** : chaque promo/session/client a son propre module, aucun risque de mélange
- **Parallélisme** : plusieurs pipelines en même temps sans conflit
- **Traçabilité** : 1 pipeline ↔ 1 plateforme ↔ 1 set de cours, relation 1:1:1 lisible en DB
- **Limite actuelle** : les containers Azure Blob ne sont pas auto-créés — il faut les créer manuellement dans Azure Portal. Automatisation à prévoir.

## Références code

- `backend/routes/formation_routes.py` — `init_formation` : INSERT dans `platform_config` puis création du job
- `backend/services/formation_pipeline_service.py` — `get_job` et `list_jobs` : `LEFT JOIN platform_config ON p.id = j.platform_id` pour enrichir avec `platform_name`
- `frontend/src/pages/FormationPipeline.jsx` — `NewJobForm` : champ "Nom de la plateforme (nouveau module)"

## Leçons / Pour le mémoire

- **La granularité du multi-tenant doit être choisie consciemment** : tenant-par-client, tenant-par-projet, tenant-par-session sont des choix architecturaux aux conséquences opérationnelles très différentes.
- **Une fonctionnalité "créer une plateforme" n'est jamais qu'une ligne DB** — il faut aussi auto-provisionner l'infrastructure (containers, CDN, DNS). Ici c'est la moitié fait en DB, l'autre moitié reste manuelle sur Azure.
- **L'UI doit refléter l'architecture** : afficher `platform_name` partout (sidebar, header, confirmations) aide l'utilisateur à comprendre où sont ses données.
