# Audit multi-tenant — Le Socrate

**Date** : 2026-04-22
**Auditeur** : Claude (Opus 4.7, 1M context)
**Scope** : architecture multi-tenant (P1–P4), propagation `platform_id`, auth, sockets, perf
**Sources vault consultées** :
- `wiki/Context/architecture-multi-tenant.md`
- `wiki/Context/projet-le-socrate.md`
- `wiki/Intelligence/infra-azure-3-comptes-blob.md`
- `memoire/01-architecture/multi-tenant-plateforme-par-pipeline.md`
- `memoire/02-problemes/hr-dashboard-heure-cours-figee-p2-p3.md`

**Verdict global** : le multi-tenant fonctionne mais porte encore la même famille de bug que le memoire décrit — des « defaults = 1 » et des SQL sans filtre qui leak cross-tenant sur les chemins de l'admin local. Le proxy HR→distant est, lui, bien corrigé.

---

## Périmètre audité

### Fichiers lus intégralement

- `backend/database/db.py` — schéma (17 tables, migrations `platform_id`)
- `backend/main_app.py` — bootstrap, CORS, `before_request`, injection `X-Platform-Id`
- `backend/routes/admin_routes.py` — routes admin locales + 3 endpoints `/api/internal/*`
- `backend/routes/hr_routes.py` — proxy `_call_platform` et routes HR Dashboard (~2939 l.)
- `backend/routes/video_routes.py` — routes cours/audio côté élève
- `backend/routes/formation_routes.py` (début) — création de plateforme via pipeline
- `backend/services/time_service.py` — `get/set_heure_debut_cours`
- `backend/socketio_handlers/handlers.py` — gestion rooms SocketIO
- `frontend/src/api.js` — wrapper `apiFetch`

### Dimensions scannées

1. **Schéma DB** — tables avec/sans `platform_id`, colonnes de migration, index
2. **Defaults `platform_id=1`** — signatures de fonctions, extraction header/session/body
3. **Requêtes SQL** — filtrage par tenant manquant, UPDATE hardcodés `WHERE id=1`
4. **Symétrie GET/POST** sur `/api/internal/*`
5. **Proxy HR → plateformes distantes** — propagation `platform_id` (URL vs body)
6. **Auth** — headers `X-Platform-Id` (frontend→backend), `X-Platform-Key` (service-to-service)
7. **SocketIO rooms** — join/leave, scoping des emits, fallbacks
8. **Duplications / incohérences** — 2 chemins de création de plateforme, 3 fonctions `_get_platform_id`, prompt TTS global
9. **Perf / optimisations** — N+1, appels séquentiels parallélisables, index manquants, cache

### Non couvert (par économie de contexte)

- `hr_routes.py` lignes 900–1060 et 1320–2820 (zones survolées par grep, pas lues ligne à ligne)
- Services : `azure_blob_service.py`, `audio_service.py`, `rag_service.py`, `playlist_tts_service.py` (grep only)
- Routes : `slides_routes.py`, `chat_routes.py`, `debug_routes.py` (non lues)
- Composants frontend (vérification `fetch` direct vs `apiFetch` uniquement, pas de lecture détaillée)

---

## 🔴 Bugs confirmés (priorité haute)

### B1 — Admin panel lit/écrit toujours P1, indépendamment du tenant

**Fichiers** : `backend/routes/admin_routes.py:40, 51, 121, 171, 295, 298`

- `get_logs` → `SELECT * FROM logs` **sans** `WHERE platform_id = ?` → l'admin d'une plateforme voit les logs de toutes.
- `get_logs:40` + `get_course_time:121` appellent `get_heure_debut_cours()` **sans argument** → `default platform_id=1`. Exactement le pattern du bug d'avril corrigé sur `/api/internal/course-time`, mais jamais corrigé côté admin local.
- `config_cours:171` appelle `set_heure_debut_cours(nouvelle_heure_fr)` sans `platform_id` → écrit toujours la ligne P1.
- `export_excel:295, 298` : mêmes `SELECT * FROM logs` sans filtre → leak cross-tenant à l'export Excel.

### B2 — `set-lock` service-to-service ignore `platform_id`

**Fichier** : `backend/routes/admin_routes.py:207-210`

```python
cursor.execute("UPDATE platform_config SET upload_locked=?, updated_at=? WHERE id = 1", ...)
```

Hardcodé à `id=1`. Appelé par `_call_platform(pid, "/api/internal/set-lock", ...)` mais le backend distant ignore le `platform_id` du body et écrit toujours sa ligne P1 locale. Même pattern de bug que l'ancien `course-time`.

### B3 — Suppression de blob Azure réservée à P1

**Fichier** : `backend/routes/hr_routes.py:766`

```python
if platform_id == 1:
    _, container_client = _get_azure_audio_clients()
    ...
```

`approve_deletion` marque la demande « approved » pour toutes les plateformes mais ne supprime le blob **que pour P1**. Pour P2/P3/P4, le fichier reste sur Azure.

### B4 — SocketIO `participants_update` leak sur `connect`

**Fichier** : `backend/socketio_handlers/handlers.py:33`

```python
emit("participants_update", {"count": nb_participants}, broadcast=True)
```

Le premier emit à la connexion est `broadcast=True` (pas de `to=room`) → un user P2 reçoit le compte quand un user P3 se connecte. Les emits suivants (l. 52, 79) sont bien scopés.

---

## 🟠 Risques latents — defaults `=1` qui peuvent mordre

| Fichier:ligne | Pattern |
|---|---|
| `backend/services/time_service.py:34, 66` | `def set/get_heure_debut_cours(platform_id=1)` — source des bugs B1, B2 |
| `backend/routes/auth_routes.py:23` | `data.get("platform_id", 1)` au login — un front qui oublie d'envoyer = login silencieusement sur P1 |
| `backend/main_app.py:108, 123` | Reconstitution session et `/api/platform-info` avec fallback 1 |
| `backend/routes/video_routes.py:18` | `session.get("platform_id", 1)` |
| `backend/routes/formation_routes.py:57` | `session.get("platform_id", 1)` |
| `backend/socketio_handlers/handlers.py:14, 61, 89, 107` | Multiples fallbacks 1 |

Aucun de ces defaults ne panique — ils masquent un oubli d'injection en **écrivant silencieusement dans P1**. Même mécanique que le bug passé.

---

## 🟡 Incohérences / duplications

### I1 — Trois chemins distincts d'extraction `platform_id`

- `main_app.py:99-116` — `before_request` : header → query → session
- `formation_routes.py:51-57` — header → session
- `video_routes.py:13-18` — query → session, **pas de header**

Aucun middleware unifié. Un helper central `get_platform_id()` dans `utils/` + un décorateur `@require_platform` réglerait l'affaire.

### I2 — Deux chemins de création de plateforme divergents

- `hr_routes.py:270-364` (`POST /api/hr/platforms`) — crée bien les containers Azure Blob.
- `formation_routes.py:92-153` (`POST /api/formation/init`) — crée la ligne DB mais **pas les containers** (commentaire l.135 : « à créer manuellement dans Azure »).

Le memoire `multi-tenant-plateforme-par-pipeline.md` note ce point ouvert. Il est à moitié résolu : l'UI HR auto-provisionne, la pipeline formation non. À unifier.

### I3 — Frontend : 84 appels `fetch` directs contournent `apiFetch`

`frontend/src/api.js:29-42` expose `apiFetch` qui injecte `X-Platform-Id`, mais la majorité des composants (`AudioEditor.jsx`, `CoursFolders.jsx`, `HRDashboard.jsx`, etc.) utilisent `fetch(apiUrl(...))` direct. Ces appels ne posent **pas** le header → le backend retombe sur la session Flask. Ça marche **par chance** parce que les routes HR passent `platform_id` dans l'URL, mais la moindre route qui dépend de `session["platform_id"]` sur ces chemins est exposée à un cache de session obsolète.

### I4 — Le prompt TTS est global, pas par tenant

`backend/routes/hr_routes.py:2893-2937` — `_TTS_PROMPT_FILE` est un fichier unique sur disque partagé entre plateformes. Si on tient le principe « 1 RNCP = 1 module durable », chaque plateforme devrait avoir son prompt (ou au moins pouvoir surcharger).

### I5 — `set_schedule_config` reset global

`backend/routes/hr_routes.py:2875` — `UPDATE platform_config SET playlist_mode = NULL` (sans WHERE) avant de réappliquer. Probablement intentionnel (mode été/hiver géré depuis un seul dashboard) mais à commenter sinon c'est un WTF à la lecture.

---

## ⚡ Optimisations candidates (classées par ROI)

### O1 — Parallélisation `get_platforms` — **ROI élevé**

`hr_routes.py:143-267` — pour N plateformes, 2 appels Azure Blob **en boucle séquentielle** (audio + PDF container). Sur 4 plateformes : 8 appels Azure synchrones pour afficher le dashboard. Eventlet est en place → `concurrent.futures.ThreadPoolExecutor(max_workers=8)` ferait passer ça en ~1 round-trip.

### O2 — Parallélisation `auto_schedule` — **ROI moyen**

`hr_routes.py:1170-1209` — `for item in schedule: _call_platform(...)` séquentiel. Même remède.

### O3 — Index DB sur `platform_id` — **ROI moyen, coût ~0**

Aucune table avec `platform_id` n'a d'index dessus. Tables concernées : `logs`, `video_visits`, `cours_folders`, `cours_config`, `deletion_requests`, `formation_pipeline_jobs`, `content_generation_jobs`. Avec SQLite WAL + multi-tenant, même quelques centaines de lignes bénéficient d'un `CREATE INDEX idx_logs_platform ON logs(platform_id)`.

### O4 — Cache `platform_config` — **ROI faible à moyen**

Lu à chaque requête via SQL. 4-10 lignes quasi statiques → `functools.lru_cache` + invalidation sur `update_platform_config()`. Gain par requête = 1 round-trip SQLite. Non critique mais gratuit.

### O5 — Factoriser la génération de SAS URLs — **ROI code-quality**

`hr_routes.py` crée des SAS URLs dans 5+ endroits avec copier-coller (audio list, PDF list, stream, etc.). Un helper `generate_sas_url(container, blob, hours=1)` réduit ~80 lignes.

### O6 — Middleware `@require_platform` — **ROI architectural**

Remplace les 3 fonctions `_get_platform_id()` + l'étape manuelle `session.get("platform_id")` par un décorateur qui :

- lit header ou query,
- valide que le tenant existe en `platform_config`,
- **pas de default=1** (retourne 400 si absent),
- injecte `g.platform_id`.

Tue la famille de bugs « defaults=1 » d'un coup.

---

## Synthèse — priorisation

| # | Action | Effort | Impact |
|---|---|---|---|
| 1 | B1 + B2 — fixer les appels `get/set_heure_debut_cours` et le `UPDATE WHERE id=1` | petit | bug actif aujourd'hui |
| 2 | B3 — faire marcher la suppression de blob pour P2/P3/P4 | petit | orphelins Azure |
| 3 | B4 — `broadcast=True` → `to=room` | 1 ligne | leak mineur |
| 4 | O6 + I1 — middleware unifié `@require_platform` | moyen | tue la famille de bugs |
| 5 | I3 — migrer les 84 `fetch` vers `apiFetch` | moyen | cohérence auth |
| 6 | O1 — paralléliser `get_platforms` | petit | dashboard plus rapide |
| — | O3, O4, O5, I2, I4, I5 | — | polish |

## Trois paquets cohérents à livrer

- **Bug-fix** : B1 + B2 + B3 + B4 (petit, délimité, prioritaire)
- **Middleware** : O6 + I1 + migration frontend I3 (plus gros, touche beaucoup de fichiers, mais élimine une famille entière de bugs)
- **Perf** : O1 + O3 (orthogonal aux deux autres)
