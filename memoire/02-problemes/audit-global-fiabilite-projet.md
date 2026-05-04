# Audit global — dette de fiabilité avant extension

**Date** : 2026-04-22  
**Thématique** : problème  
**Statut** : actif

## Contexte

Le projet Le Socrate a franchi un seuil de complexité : multi-tenant P1-P4, pipeline RNCP automatisée, knowledge base enrichie, génération texte TTS, synthèse Fish Audio, PDF LaTeX, HR Dashboard et déploiements Azure multiples.

Un audit global du repo a été demandé pour distinguer ce qui relève du produit stable, de la dette normale, et des risques qui bloqueront les prochaines extensions.

## Problème / Question

La question n'est plus "quelle feature ajouter ?", mais "quels garde-fous faut-il mettre avant de continuer à étendre ?".

Quatre familles de risques ressortent :

1. Multi-tenant encore permissif : defaults silencieux vers P1 et actions globales.
2. Génération longue non bornée : `content_generation_service.py` peut lancer trop d'appels Claude simultanés.
3. Frontend non vérifiable : lint et build échouent localement.
4. Workspace chargé : artefacts et changements non commités brouillent l'état réel.

## Options envisagées

Option A — Continuer à développer les features et corriger au fil de l'eau.  
Rejetée : les bugs sont transverses, surtout `platform_id` et rate-limits. Les repousser augmente le coût de correction.

Option B — Faire un gel court de stabilisation.  
Retenue : un lot de stabilisation ciblé réduit fortement le risque sans refactor massif.

Option C — Refactor complet backend/frontend.  
Rejetée à court terme : `hr_routes.py`, `CoursFolders.jsx` et `HRDashboard.jsx` méritent d'être découpés, mais ce n'est pas le premier levier. Les bugs confirmés se corrigent plus vite chirurgicalement.

## Décision finale

Prioriser un **lot de stabilisation** avant nouvelle feature majeure :

1. Fix multi-tenant B1-B4 de `AUDIT_MULTI_TENANT.md`.
2. Admin par env + hash, plus aucun `secret123` en backend.
3. Brancher `content_generation_service.py` sur le client Anthropic mutualisé et limiter la concurrence des journées.
4. Rendre le frontend build/lint vérifiable.
5. Nettoyer `.gitignore` et séparer les commits code/documentation/artefacts.

## Rationale technique

Le projet a déjà les bonnes abstractions métier : RNCP durable, KB enrichie, checkpointing DB, séparation texte/audio. Les risques actuels viennent plutôt de l'absence de barrières explicites :

- `platform_id=1` comme fallback transforme les oublis en écritures P1.
- Les jobs en thread sans queue globale transforment une formation longue en burst d'appels Anthropic.
- Le frontend peut contenir des erreurs runtime non détectées si lint/build ne passent pas.
- Les artefacts locaux masquent les vrais changements à relire.

La meilleure stratégie est donc de poser les garde-fous avant d'ajouter de nouveaux flux.

## Références code

- `AUDIT_PROJET_GLOBAL.md`
- `AUDIT_MULTI_TENANT.md`
- `backend/routes/admin_routes.py:335`
- `backend/services/content_generation_service.py:137`
- `backend/services/formation_pipeline_service.py:797`
- `frontend/src/components/CoursFolders.jsx:795`
- `.github/workflows/main_socrate-backend-v.yml`

## Leçons / Pour le mémoire

Un projet IA ne devient pas fragile uniquement à cause du modèle. Il devient fragile quand les coûts et états longs (jobs, tenants, fichiers, appels API, génération audio) ne sont pas bornés par des invariants.

Dans Le Socrate, la robustesse passe maintenant par des invariants explicites : tenant obligatoire, queue de génération, relance idempotente, vérification automatisée, et hygiène de workspace.
