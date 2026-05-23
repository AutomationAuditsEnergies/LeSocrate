# Audit global projet — Le Socrate

**Date** : 2026-04-22  
**Scope** : repo complet local, vault Obsidian, backend Flask/SocketIO, frontend React/Vite, DB SQLite, workflows Azure, tests disponibles.  
**Nature** : audit statique + vérifications locales non destructives.

## Verdict

Le Socrate a une architecture produit cohérente : le principe **1 RNCP = 1 module durable** est clair, la pipeline RNCP -> REAC -> KB -> programmes -> texte TTS -> audio est bien orientée, et le projet a déjà une documentation rare pour un projet solo (`CHANGELOG.md`, `memoire/`, vault Obsidian).

Le risque principal n'est pas le manque de features. C'est la stabilisation avant extension : plusieurs chemins critiques fonctionnent par convention implicite plutôt que par garde-fous. Les priorités sont donc :

1. **Fiabiliser le multi-tenant** : supprimer les defaults silencieux vers P1 et les broadcasts globaux.
2. **Fiabiliser la génération longue** : `content_generation_service.py` n'a pas encore la protection 429 mutualisée, alors qu'il lance potentiellement des dizaines/centaines d'appels Claude.
3. **Rendre le frontend vérifiable** : lint en échec, build bloqué par environnement Node/deps Rollup.
4. **Nettoyer le workspace** : beaucoup d'artefacts lourds/non versionnés (`venv/`, MP3, outputs, cours) brouillent l'état réel du projet.
5. **Durcir l'admin** : identifiants hardcodés et actions globales cross-tenant.

## Cartographie rapide

### Backend

- Entrée : `backend/run.py` charge `eventlet.monkey_patch()` puis `main_app.py`.
- App : Flask + SocketIO + CORS, blueprints `auth`, `video`, `admin`, `debug`, `slides`, `chat`, `hr`, `formation`.
- DB : SQLite via `backend/database/db.py`, migrations idempotentes au démarrage.
- Services structurants :
  - `formation_pipeline_service.py` : RNCP/REAC/programme/journées.
  - `knowledge_base_service.py` : enrichissement Couche 1.
  - `content_generation_service.py` : texte TTS par journée.
  - `playlist_tts_service.py` + `tts_service.py` : MP3 Fish Audio.
  - `azure_blob_service.py` : storage TTS.

### Frontend

- React 19 + Vite 7 + Tailwind v4.
- Routes principales : `/`, `/video`, `/admin`, `/hr-dashboard`, `/schedule-config`, `/formation-pipeline`.
- Composants les plus lourds :
  - `CoursFolders.jsx` : 1991 lignes.
  - `HRDashboard.jsx` : 1772 lignes.
  - `FormationPipeline.jsx` : 1486 lignes.
  - `AudioEditor.jsx` : 685 lignes.

### Infra

- 10 workflows GitHub Actions.
- Staging backends OK en structure : installation depuis `./backend`.
- Frontends Static Web Apps injectent `VITE_API_URL`.
- Function App `scheduleHourClass3` appelle `/api/internal/auto-schedule` avec `X-Platform-Key`.

## Points forts

- **Domaine très bien cadré** : la règle "1 RNCP = 1 module durable" évite une mauvaise architecture orientée promo.
- **Documentation durable** : le vault et `memoire/` réduisent le risque de perdre les décisions.
- **Checkpointing réel** : `content_generation_segments`, `formation_knowledge_base`, statuts de jobs.
- **API HTTP directe** pour IA/TTS : cohérent avec la contrainte eventlet.
- **Azure OIDC** sur les backends staging : meilleur que les publish profiles.
- **Séparation texte TTS / audio Fish Audio** : bonne décision produit, car elle permet la relecture avant coût TTS.

## Findings prioritaires

### P0 — Admin hardcodé en clair

**Références** :
- `backend/routes/admin_routes.py:335`
- `frontend/tests/e2e/admin.spec.js:6`
- `API_ROUTES.md:175`

Le couple `admin` / `secret123` est codé dans le backend et documenté/testé. Même si les frontends sont connus dans CORS, c'est un vrai point faible : une fuite d'URL suffit pour essayer l'admin.

**Action** : lire `ADMIN_USERNAME` / `ADMIN_PASSWORD_HASH` depuis l'env, hasher le mot de passe, et mettre à jour les tests via secrets/env locaux.

### P0 — Multi-tenant encore fragile

L'audit dédié `AUDIT_MULTI_TENANT.md` reste valide. Bugs confirmés :

- Admin local lit/écrit les logs et l'heure sans filtre `platform_id` (`admin_routes.py:40`, `:51`, `:121`, `:171`, `:295`, `:298`).
- `internal_set_lock` écrit toujours `WHERE id = 1` (`admin_routes.py:207-210`).
- SocketIO broadcast global sur connect (`socketio_handlers/handlers.py:33`).
- Actions de déconnexion globale non scopées tenant (`admin_routes.py:440-455`, `auth_routes.py:142-159`).

**Action** : livrer le paquet bug-fix multi-tenant avant toute nouvelle feature RH/admin.

### P0 — Génération TTS texte : risque massif de rate-limit Anthropic

**Références** :
- `backend/services/content_generation_service.py:137-154`
- `backend/services/formation_pipeline_service.py:797-816`
- `backend/services/content_generation_service.py:317-324`

La protection 429 mutualisée existe dans `backend/utils/anthropic_client.py`, mais `content_generation_service.py` appelle encore Anthropic directement avec `resp.raise_for_status()`. Or `launch_tts_for_all_days()` lance un job par journée, chaque job lance un thread, et chaque journée peut faire 18 appels Claude.

Sur une formation longue, on peut donc déclencher beaucoup plus d'appels simultanés que le bucket Anthropic ne peut absorber. C'est le même problème que celui corrigé pour la KB, mais sur une surface plus coûteuse.

**Action** : brancher `content_generation_service.py` sur `utils/anthropic_client.py`, puis ajouter une limite globale de concurrence pour les jobs texte (par exemple 1-2 journées à la fois selon modèle/tier).

### P1 — Frontend non vérifiable localement

Commandes exécutées :

- `./venv/bin/python -m compileall -q backend` : OK.
- `npm run lint` : échec, 59 erreurs et 12 warnings.
- `npm run build` : échec avant build Vite.

Build bloqué par :

- Node local `20.11.1`, alors que Vite 7 demande `20.19+` ou `22.12+`.
- module optionnel Rollup manquant : `@rollup/rollup-darwin-arm64`.

Lint bloqué notamment par :

- `frontend/src/components/CoursFolders.jsx:795` et `:807` : `setLoadingScript` non défini.
- Beaucoup d'unused vars dans `AudioEditor.jsx`, `CoursFolders.jsx`, `HRDashboard.jsx`, `FormationPipeline.jsx`.
- `HRDashboard.jsx:886` : setState synchrone dans effet.
- `HRDashboard.jsx:1453` : accès à ref pendant render.

**Action** : corriger d'abord les erreurs qui peuvent casser runtime (`setLoadingScript`), puis fixer l'environnement Node/deps, puis seulement nettoyer les unused.

### P1 — Worktree très chargé, état stable difficile à lire

Le repo contient beaucoup de changements et artefacts non commités :

- 10 fichiers modifiés pour +1207/-322 lignes.
- Beaucoup de nouveaux fichiers applicatifs non trackés : pipeline formation, KB, PDF, prompts, memoire.
- Beaucoup d'artefacts non trackés : `venv/`, `cours/`, `courstxt/`, `output_*`, MP3 de tests.

`frontend/.gitignore` ignore bien `dist`, mais `.gitignore` racine n'ignore pas `venv/`, `cours/`, `courstxt/`, `output_*`, ni les MP3 de test.

**Action** : ajouter les patterns d'artefacts à `.gitignore`, puis séparer un commit "code produit" d'un commit "documentation/memoire". Ne pas versionner `venv/`.

### P1 — Pipeline formation pas idempotente sur relance partielle

**Référence** : `backend/services/formation_pipeline_service.py:740-819`

`launch_tts_for_all_days()` crée les dossiers en DB, commit, puis lance la génération pour chaque journée. Si le process tombe après création des dossiers mais avant fin de génération, une relance peut recréer des dossiers "Jour N" supplémentaires plutôt que reprendre les dossiers existants.

**Action** : stocker le lien job -> folder_id ou rendre la création idempotente par `(platform_id, job_id, day_number)`.

### P1 — DB sans index métier

SQLite local ne contient que les index automatiques `UNIQUE`. Les tables filtrées fréquemment par `platform_id`, `folder_id`, `job_id`, `status` n'ont pas d'index explicites.

**Action** : ajouter des migrations `CREATE INDEX IF NOT EXISTS` pour :

- `logs(platform_id)`
- `video_visits(platform_id)`
- `cours_folders(platform_id, position)`
- `cours_documents(folder_id)`
- `content_generation_jobs(platform_id)`
- `content_generation_segments(job_id, status)`
- `formation_pipeline_jobs(platform_id, status)`
- `deletion_requests(platform_id, status)`

### P2 — Main prod workflow probablement cassé

**Référence** : `.github/workflows/main_socrate-backend-v.yml`

Le workflow `main` exécute `pip install -r requirements.txt` à la racine, mais le repo actuel n'a pas de `requirements.txt` racine ; le fichier est dans `backend/requirements.txt`. Les workflows staging utilisent bien `working-directory: ./backend`.

**Action** : soit supprimer/archiver l'ancien workflow main, soit l'aligner sur les workflows staging.

### P2 — E2E pointe sur Azure, pas local

**Référence** : `frontend/playwright.config.js`

`baseURL` pointe sur `https://thankful-wave-043aa3b03.4.azurestaticapps.net`. Utile pour smoke test staging, mais pas pour valider les changements locaux. Les tests peuvent modifier une base distante (login, config cours).

**Action** : créer deux configs : `playwright.local.config.js` et `playwright.staging.config.js`.

## Plan d'action conseillé

### Lot 1 — Stabilisation immédiate

1. Fix multi-tenant B1-B4 de `AUDIT_MULTI_TENANT.md`.
2. Remplacer admin hardcodé par env + hash.
3. Corriger `setLoadingScript` et rendre `npm run lint` au moins exécutable sans erreurs bloquantes.
4. Mettre à jour Node local ou `.nvmrc`, puis `npm install` pour restaurer Rollup.

### Lot 2 — Fiabilité pipeline longue

1. Mutualiser Anthropic dans `content_generation_service.py`.
2. Ajouter une limite de concurrence globale pour génération texte.
3. Rendre `launch_tts_for_all_days()` idempotent.
4. Ajouter tests unitaires backend sur statuts et relances.

### Lot 3 — Hygiène et industrialisation

1. `.gitignore` : `venv/`, outputs, MP3 générés, corpus locaux.
2. Index SQLite.
3. Split Playwright local/staging.
4. Découper progressivement `hr_routes.py`, `CoursFolders.jsx`, `HRDashboard.jsx` par domaines.

## Vérifications réalisées

- Vault chargé : `wiki/index.md`, `Context/*`, `Resources/conventions-repo.md`, `Intelligence/pipeline-tts-19-mp3.md`, `architecture-4-couches-qualite.md`, `infra-azure-3-comptes-blob.md`, `decisions-persistance-sqlite.md`.
- `./venv/bin/python -m compileall -q backend` : OK.
- `npm run lint` : KO, 59 erreurs, 12 warnings.
- `npm run build` : KO, Node trop ancien + Rollup optional dependency manquante.
- SQLite schema/index inspecté : pas d'index métier explicites.

## Non couvert

- Pas de test fonctionnel live des endpoints Azure.
- Pas de lecture exhaustive ligne par ligne de tous les fichiers frontend volumineux.
- Pas de scan de secrets dans fichiers ignorés (`.env`, `backend/.env`) par respect du périmètre repo.
