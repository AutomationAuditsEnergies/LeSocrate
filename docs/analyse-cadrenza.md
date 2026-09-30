# Analyse Cadrenza (`codex/current-saas-postgres-20260705`)

Analyse en lecture seule (aucun checkout, aucune modification, aucun commit/push/déploiement). Toutes les commandes utilisées : `git show/log/ls-tree/grep/diff/merge-base` sur les références distantes, jamais sur le working tree. Vérifié à chaque étape : `git branch --show-current` inchangé.

**Convention** : chaque fait cite son fichier:ligne. Quand une preuve directe n'a pas pu être obtenue, c'est marqué **non vérifié** explicitement plutôt que supposé.

---

## Résumé exécutif

Le code de Cadrenza est **nettement plus abouti qu'un simple prototype** : auth Supabase réellement vérifiée côté serveur, paiement Stripe complet et testé, schéma Postgres avec repositories dédiés, workers séparés, CI qui fait tourner un vrai Postgres. Aucun `TODO`/`FIXME`/`NotImplementedError` bloquant trouvé dans le cœur du pipeline. Le point faible structurel reste le même que celui identifié précédemment : **l'isolation multi-tenant dépend à 100% du code applicatif** (RLS activé sans policies). Le déploiement est un vrai pipeline CI/CD avec garde-fous (tests Postgres bloquants, arrêt/redémarrage propre de l'App Service pendant la migration de schéma). Sur l'écart avec `staging` : sur 55 commits de retard, **un seul** est un correctif à porter tel quel (watchdog Edge TTS) ; tout le reste est soit déjà mieux couvert côté Cadrenza, soit spécifique à la plateforme interne.

---

## 1. Déploiement actuel de P3

**Frontend** — `.github/workflows/azure-static-web-apps-polite-bush-07d4fdd03.yml` (identique sur `staging` et `codex`, diff vide) :
- Déclencheur : `push` sur `codex/current-saas-postgres-20260705`, `pull_request` sur la même branche, `workflow_dispatch`.
- Cible : Static Web App `polite-bush-07d4fdd03`.
- `env:` au build : `VITE_API_URL=https://formation3-cpdhezh4cdcqecfy.francecentral-01.azurewebsites.net`, `VITE_FORMATION_NAME="Le Socrate"` (nom legacy en dur, pas "Cadrenza" — incohérence déjà signalée), `VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY` (secrets `SAAS_*` avec repli sur les secrets génériques).

**Backend** — `.github/workflows/staging_formation3.yml`, **mais la branche codex a sa propre version de ce fichier, différente de celle sur `staging`** (~450 lignes de diff). GitHub Actions exécute la version présente dans le commit poussé — c'est donc la version codex qui tourne réellement :
- Déclencheur : `push` sur `codex/current-saas-postgres-20260705`, `workflow_dispatch`. `concurrency.cancel-in-progress: false` (commentaire : ne jamais annuler un run pendant une migration de schéma Postgres).
- Cible : App Service `Formation3`. Startup command : `python run_saas.py` (point d'entrée dédié, différent de `run.py`).
- Pipeline : `recover-app` (redémarre si arrêté) → `postgres-integration` (appelle `postgres-ci.yml` en gate obligatoire) → `build` → `deploy` (`az webapp stop` → applique `tools/database/apply_postgres_schema.py` → `az webapp start` → ~60 `appsettings set`, avec **suppression explicite de `ANTHROPIC_API_KEY`** commentée *"empêcher tout retour silencieux à Anthropic"* → `healthCheckPath: /readyz` → déploiement → vérification `/readyz` en boucle).
- Secrets injectés : `DATABASE_URL`, `SUPABASE_URL`/`ANON_KEY`/`SERVICE_ROLE_KEY`, `AZURE_TTS_STORAGE_CONNECTION_STRING`, `INTERNAL_ADMIN_PASSWORD_HASH`, `SECRET_KEY`, `AUTO_LOGOUT_WEBHOOK_SECRET`, `DEEPSEEK_API_KEY`, `FISH_AUDIO_API_KEY`/`VOICE_ID`, `AZURE_AUDIO_STORAGE_CONNECTION_STRING`, `AZURE_STORAGE_CONNECTION_STRING`, `STRIPE_SECRET_KEY`/`WEBHOOK_SECRET`, `AI_TEACHER_STRIPE_PRICE_ID`, `REMINDER_WEBHOOK_URL`/`KEY`, `EMAIL_USERNAME`/`PASSWORD`.

**Élément additionnel** : `.github/workflows/deploy_pipeline_workers.yml` (uniquement sur codex) déploie des Container Apps (`cadrenza-ai-worker`, `cadrenza-audio-worker`) via Bicep, `workflow_dispatch` manuel. **Confirmé par l'utilisateur (23/09/2026) : le cutover a été exécuté avec succès, les workers fonctionnent en prod.** `BASE_NAME: cadrenza` est la première occurrence du nom produit trouvée dans l'infra.

---

## 2. Périmètre pour l'extraction dans un nouveau repo

Diff `staging` vs `codex` sur `backend/` : **237 fichiers, +79 249/-18 892 lignes**.

**À garder (spécifique Cadrenza)** : `backend/database/postgres.py`+`postgres_schema.sql`, `backend/repositories/*` (12 fichiers), `backend/routes/billing_routes.py`, ~20 services SaaS (`billing_service.py`, `center_auth_service.py`, `attendance_service.py`, `teacher_order_fulfillment_service.py`, etc.), `backend/services/pipeline_queue/*`, `backend/workers/*`, `backend/utils/{supabase_auth,auth_tokens,cors_config,deepseek_client,env,concurrency,slug}.py`, `backend/tools/database/*`, `backend/run_saas.py`, `Dockerfile.worker`, workflows (`staging_formation3.yml` version codex, `azure-static-web-apps-polite-bush-*.yml`, `postgres-ci.yml`, `deploy_pipeline_workers.yml`), `infra/azure/*`, docs SaaS (`docs/architecture/*`, `docs/database/SUPABASE_POSTGRES.md`, `docs/deployment/{COPIE_SAAS_POSTGRES_FORMATION3,STRIPE_FORMATION3,FORMATION_PIPELINE_ACCESS}.md`), `frontend/src/supabaseClient.js` + ~15 modules API frontend SaaS, pages (`AIVoicesView`, `AdminValidations`, `ClassEntry`, `DayScheduleTemplates`, `FormationSchedulePlanner`), `frontend/src/limovaClone/` (landing marketing), assets `cadrenza-*`.

**Partagé avec `staging`** (à garder, cœur métier) : `content_generation_service.py`, `content_pipeline/*`, `formation_pipeline_service.py`, `audio_service.py`, `basic_tts_service.py`, `tts_service.py`, `script_*_service.py`, `knowledge_base_service.py`, `formation_{docx,pdf}_service.py`, `main_app.py`, `database/db.py`+`db_safety.py`, `config.py`, la quasi-totalité de `routes/{admin,auth,chat,formation,hr,slides,video,debug}_routes.py` (modifiés, pas ajoutés), la plupart de `frontend/src/components/slides/`.

**Supprimé côté Cadrenza** (donc à ne pas réintégrer) : `claude_code_mission_service.py`, `event_mapper.py`, `slide_generation_service.py`, `slideshow_planner.py`, `timeline_fusion.py`, `socketio_handlers/`, `anthropic_client.py` (remplacé par `deepseek_client.py`).

**Candidats à exclusion, intention produit non confirmée (non vérifié)** : `cours/`, `courstxt/` (contenu métier "boulangerie" one-shot), `memoire/` (mémoire d'études, sans rapport), `rag_eval_runs/`, `tools/` racine et `tools/rag|tts/*` (scripts one-shot), `azure-function/` (non vérifié si encore appelée), fichiers de debug UI ponctuels.

**Workflows à garder** : `azure-static-web-apps-polite-bush-07d4fdd03.yml`, `staging_formation3.yml` (à renommer), `postgres-ci.yml`, `deploy_pipeline_workers.yml` (si le cutover workers est retenu).
**Workflows à supprimer** : tout ce qui cible P1 (`socrate1`, `thankful-wave`), P2 (`socrate-backend-p2`, `brave-mud`), P4 (`Plateforme4`, `victorious-smoke`), et le legacy `main_socrate-backend-v.yml`/`staging_schedulehourclass3.yml`.

---

## 3. Configuration nécessaire (noms uniquement)

| Groupe | Variables |
|---|---|
| Supabase | `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_DB_URL` + `VITE_SUPABASE_URL`/`ANON_KEY`/`PUBLISHABLE_KEY` (front) |
| Postgres | `DATABASE_URL`, `DATABASE_BACKEND`, `PIPELINE_DATABASE_BACKEND`, `POSTGRES_POOL_*` (6 variables), `POSTGRES_FORCE_IPV4`, `POSTGRES_TEST_DATABASE_URL` |
| Stripe | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `AI_TEACHER_STRIPE_PRICE_ID`, `AI_TEACHER_COST_PER_DAY_CENTS`, `AI_TEACHER_PRICE_PER_DAY_CENTS` |
| LLM (DeepSeek, Anthropic retiré) | `DEEPSEEK_API_KEY`, `FORMATION_LLM_MODEL`, `FORMATION_LLM_PROVIDER`, `SCRIPT_ANNOTATION_MODEL`, `SCRIPT_RULES_MODEL` (+ variantes) |
| TTS | `FISH_AUDIO_API_KEY`/`VOICE_ID`, `EDGE_TTS_VOICE`/`VOLUME`/`SUBPROCESS_TIMEOUT_SEC`, `BASIC_TTS_SPEED` (+ variantes retry) |
| Stockage Azure Blob | `AZURE_STORAGE_CONNECTION_STRING`, `AZURE_AUDIO_STORAGE_CONNECTION_STRING`, `AZURE_TTS_STORAGE_CONNECTION_STRING` (+ containers associés) |
| Azure Search/OpenAI | `AZURE_OPENAI_*`, `AZURE_SEARCH_*` — **présents dans `chat_routes.py`/`admin_routes.py` mais absents des secrets injectés par le workflow de déploiement → probablement du code mort en prod, non vérifié si le frontend l'appelle encore** |
| Service Bus (workers) | `AZURE_SERVICE_BUS_*`, `PIPELINE_SERVICE_BUS_*`, `PIPELINE_QUEUE_BACKEND`, `PIPELINE_WORKER_KIND` |
| Auth/sécurité | `SECRET_KEY`, `INTERNAL_ADMIN_PASSWORD_HASH`, `AUTO_LOGOUT_WEBHOOK_SECRET`, `AUTH_TOKEN_MAX_AGE_SECONDS`, `PLATFORM_API_KEY` |
| Email/rappels | `EMAIL_USERNAME`/`PASSWORD`, `SMTP_SERVER`/`PORT`, `REMINDER_WEBHOOK_URL`/`KEY` |
| Divers | `PORT`, `FRANCE_TRAVAIL_CLIENT_ID`/`SECRET`, `HR_DASHBOARD_*` |

---

## 4. Secrets dans le code et l'historique

**Sur le code actuel de la branche : aucun secret réel en dur.** Les seules occurrences de `secret123` trouvées sont dans des tests (`test_admin_secret_safety.py:14`, vérifie que ce mot de passe est **rejeté**) et un test e2e front (`admin.spec.js:6`, donnée de test).

**Dans l'historique git : oui, un vrai mot de passe en dur a existé**, et fait partie de l'ancêtre direct de cette branche (confirmé : `git merge-base --is-ancestor c83eba0 origin/codex/...` → vrai). Le commit `9239126` exposait `"password_status": "secret123"` en clair dans une réponse API ; corrigé par `c83eba0` qui remplace la comparaison en dur par `_internal_admin_password_valid()` (hash Werkzeug via `INTERNAL_ADMIN_PASSWORD_HASH`). **Conséquence pour le nouveau repo** : un simple nouveau commit ne suffit pas à effacer ça — il faudra soit repartir avec un historique squashé/tronqué, soit accepter que `secret123` reste visible dans `git log -p` d'un clone complet. **Décision confirmée par l'utilisateur (23/09/2026) : le nouveau repo démarre avec l'historique complet, pas tronqué.** Sans risque réel puisque ce mot de passe est déjà rejeté par le code actuel, mais à mentionner lors de l'onboarding d'un futur développeur externe pour éviter toute confusion.

---

## 5. Sécurité détaillée

| Sujet | Fichier:ligne | Gravité | Effort |
|---|---|---|---|
| Auth JWT Supabase | `backend/utils/supabase_auth.py:95-134` | ✅ Sain | — |
| Gate par préfixe (`/api/admin\|hr\|formation\|slides`) | `backend/main_app.py:163-238` | Majeur (risque de régression future) | Faible |
| RLS activé sans `CREATE POLICY` (41 tables, 0 policy) | `backend/database/postgres_schema.sql:1494-1650` | **Majeur, structurel** | Élevé |
| Mot de passe admin en dur | Historique git (`9239126`, `c83eba0`) | Résolu dans le code / Critique dans l'historique | Faible (code) / Élevé (purge historique) |
| Fuites `str(e)` (~124 occurrences) | `hr_routes.py` (118), `formation_routes.py` (21), `admin_routes.py` (15), `slides_routes.py` (4) | Mineur à majeur | Moyen |
| Absence de rate limiting (login/register/webhook) | Confirmé par absence de `flask-limiter` | Majeur (login/register) | Faible |
| Sessions/expiration (`itsdangerous`, `max_age`) | `backend/utils/auth_tokens.py:27-45` | ✅ Sain | — |
| Route `dev-login` | `admin_routes.py:77-80,1072-1099` | Mineur | Faible |
| Routes billing hors gate (protégées par token/signature) | `billing_routes.py:92,140,164,441` | Mineur (à confirmer) | — |
| Routes `/api/debug/*` (vérif inline) | `debug_routes.py:38-40,124-126` | Mineur | — |

**Limite explicite** : pas de lecture ligne par ligne de l'intégralité de `admin_routes.py` (~2100 l.) et `hr_routes.py` (~4900 l.) — seule la gate globale a été vérifiée, pas chaque handler individuellement.

---

## 6. État fonctionnel pour un MVP

| Flux | État | Preuve |
|---|---|---|
| Inscription centre | Complet, pattern saga avec compensation | `admin_routes.py:196-244`, testé (`test_admin_secret_safety.py`) |
| Paiement Stripe | Complet et soigné (idempotency, webhook signé, réconciliation) | `billing_service.py:1134-1437`, testé (`test_billing_service.py` etc.) |
| Génération de formation | Code structuré, aucun TODO/FIXME bloquant, workers dédiés | `content_generation_service.py` (15k+ lignes), un seul `NotImplementedError` et c'est une garde volontaire (`:5341`) |
| Consultation élève | Route protégée par token, cas limites non audités exhaustivement | `video_routes.py:67,324,473` — **non vérifié exhaustivement** |

**Démarrage local** : possible sans Postgres réel (SQLite utilisable en transition selon `.env.example:29`). Variables obligatoires pour un flux complet : `SECRET_KEY`, `SUPABASE_*`, `DEEPSEEK_API_KEY` (obligatoire selon commentaire), `FISH_AUDIO_API_KEY`, `AZURE_*_STORAGE_CONNECTION_STRING`, `STRIPE_*`.

**Tests** : `postgres-ci.yml` lance un vrai Postgres 16 en conteneur, applique le schéma deux fois (test d'idempotence), fait tourner ~30 modules d'intégration réels (tenant scope, billing, auth, workers). Pas de test HTTP de bout en bout via vrais appels réseau Stripe/Supabase — **non vérifié en détail** le niveau de mocking exact.

---

## 7. Écart avec `staging` — commits à reporter ou à ignorer

55 commits de `staging` absents de la branche Cadrenza depuis la divergence (`323ee24`, 10/07/2026).

**Catégorie A — à examiner (6 commits)**, dont un seul directement portable :
- **`9150609` "Prevent Edge TTS subprocess hangs"** → **applicable tel quel**, `basic_tts_service.py` sur Cadrenza a encore l'ancien code sans watchdog. **À porter en Phase 1** (bug de fiabilité réel, correction peu coûteuse).
- `660fc70` "Load long course audio in resilient ranges" → partiellement déjà couvert (CORS/vérif taille blob plus robustes côté Cadrenza), le reste (front) a été réarchitecturé, pas de portage direct.
- `f299b24` "Fix day 3/4 audio publication" → **déjà couvert, plus robuste** côté Cadrenza (`validate_mp3_bytes`).
- `c5e4705` "Align pipeline health with structured content" → **déjà intégré**.
- `867e5d5`/`8279e81` (DeepSeek V4.1 Flash) → réadaptation nécessaire, l'architecture cible (`deepseek_client.py`) diffère ; le nom de modèle incorrect corrigé par ce commit (`"deepseek-v4-flash"` → `"deepseek-flash"`) **existe encore comme bug potentiel côté Cadrenza** — à vérifier.

**Catégorie B (47 commits)** : rollbacks d'incident P1 du 7 septembre, branding/UI propre à l'usage interne quotidien, CI/déploiement P1/P2/P4, migration SQLite→Postgres de l'ancienne architecture (Cadrenza est nativement Postgres, non concerné) — à ignorer pour Cadrenza.

---

## 8bis. Point vérifié (24/09/2026) — confirmé : la prod tourne bien sur Postgres

`backend/config.py:39` : `DATABASE_BACKEND = os.getenv("DATABASE_BACKEND", "sqlite")` — défaut SQLite si absent, et cette variable n'apparaît nulle part dans `.github/workflows/staging_formation3.yml`, ce qui avait fait craindre que la prod tourne encore sur SQLite par défaut. **Vérifié directement dans le portail Azure (App Service Formation3 → Configuration) par l'utilisateur : `DATABASE_BACKEND=postgres` est bien positionné manuellement.** La production utilise donc réellement la base Postgres/Supabase documentée dans ce rapport — fausse alerte, mais qui valait la peine d'être vérifiée avant de toucher au code.

**Conséquence pour la demande de suppression de SQLite du code** : c'est maintenant sûr de planifier ce retrait, puisque la prod ne dépend pas du chemin SQLite par défaut. Reste que SQLite est profondément intégré dans le code (25+ fichiers, dont `pipeline_repository.py` avec 107 occurrences et `pipeline_queue/repository.py` avec 38) via un vrai mode "hybride" (`DATABASE_BACKEND` accepte `sqlite`/`hybrid`/`postgres`) — un retrait complet reste un chantier non trivial, pas une suppression de code mort ponctuelle.

## 8. Triage MVP-bloquant vs industrialisation

| Item | Bloquant pour un MVP commercialisable ? | Phase recommandée |
|---|---|---|
| Watchdog Edge TTS (subprocess hangs) | **Oui** — bug de fiabilité sur un flux central | Phase 1 (sécurité/remise en ordre) |
| Mot de passe admin en dur (historique) | Non pour un usage interne fermé ; **oui avant d'ouvrir le repo à un nouveau développeur** (recrutement fin octobre) | Phase 1 |
| Absence de rate limiting login/register | **Oui avant ouverture publique** ; tolérable pour un client pilote fermé et surveillé | Phase 1-2 |
| RLS sans policies (isolation multi-tenant) | **Oui — confirmé bloquant.** Le modèle business réel implique plusieurs centres de formation clients simultanés, chacun avec ses propres étudiants. Le mécanisme d'invitation étudiant (`auth_routes.py:222-244`, `utils/auth_tokens.py`) vérifié : correctement scopé par `platform_id`, bien conçu. Mais c'est le SEUL flux vérifié en détail — l'absence de policies RLS signifie qu'un oubli de filtrage sur n'importe quelle autre route (`hr_routes.py`, `admin_routes.py`, `formation_routes.py`) expose directement les données d'un centre à un autre, sans filet de rattrapage côté base. | **Phase 2, bloquant.** Minimum : audit systématique du filtrage `platform_id` sur les routes sensibles + tests automatisés d'accès croisé entre centres sur chaque route à risque. Les vraies policies RLS comme défense supplémentaire peuvent suivre en Phase 4. |
| Fuites `str(e)` | Non bloquant, mais facile à corriger | Phase 1-2 |
| Nom de modèle DeepSeek potentiellement incorrect côté Cadrenza | **Déprioritisé par décision explicite (23/09/2026)** : le modèle actuel fonctionne sans problème visible, pas de priorité à vérifier/corriger maintenant. À rediscuter plus tard, possiblement avec une évolution vers une architecture microservice pour le LLM. | Reporté, hors planning actuel |
| Variable `VITE_FORMATION_NAME="Le Socrate"` sur le build P3 | Non bloquant techniquement, mais incohérence de marque à corriger avant tout support client externe | Phase 2 |
| Azure Search/OpenAI — RAG questions-réponses | **Réévalué, potentiellement bloquant.** Le mémoire de fin d'études de Nassim ISSAD (`m_moire_de_fin_d_ann_e.md`) confirme que le système de questions-réponses (RAG hybride BM25+vectoriel, évalué avec de vraies métriques) est **une des deux fonctions centrales du produit**, pas un détail. Or ces variables sont absentes de la configuration de déploiement de `staging_formation3.yml` — à vérifier d'urgence si le chat/RAG fonctionne réellement pour un élève sur Cadrenza aujourd'hui, ou s'il reste à brancher. Le mémoire indique aussi que cette fonction n'avait "pas encore été déployée auprès de promotions réelles" au moment de sa rédaction. | **Phase 2, à vérifier en premier** — si non fonctionnel, c'est un vrai trou de fonctionnalité MVP, pas juste du nettoyage |
| Tests réels de bout en bout (lancer des pipelines complets, item 1 du backlog) | **Oui** — aucun blocage de code trouvé, mais rien ne remplace un test réel avant un vrai client | Phase 2 |
| Cutover Container Apps (workers) | **Confirmé fonctionnel en prod** (23/09/2026) — rien à faire, retiré du planning | — |
| Purge de l'historique git (secret123) | Non bloquant pour usage interne actuel ; à faire avant le nouveau repo propre si des développeurs externes y auront accès | Phase 1, au moment de l'extraction du nouveau repo |
