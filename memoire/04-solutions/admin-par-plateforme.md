# Admin par plateforme — scoping complet des routes admin locales

**Date** : 2026-04-23
**Thématique** : solution
**Statut** : résolu

## Contexte

L'audit multi-tenant (`AUDIT_MULTI_TENANT.md`) a révélé que la page `/admin` locale, historiquement unique (avant multi-tenant), n'avait jamais été correctement scopée par `platform_id` après le passage à 4 plateformes P1–P4. Symptômes :

- `SELECT * FROM logs` sans `WHERE platform_id = ?` dans `get_logs` et `export_excel`
- `get_heure_debut_cours()` / `set_heure_debut_cours()` appelés **sans argument** → default `platform_id=1` dans `time_service.py:34,66`
- `force-logout-finished-users` faisant un `UPDATE logs SET depart = ?` global (toutes plateformes) puis un `socketio.emit(broadcast=True)` qui déconnectait **tous les élèves de toutes les plateformes** à chaque clic
- `simulate-current-time` / `reset-simulation` écrivant dans `state.simulated_time_offset` (global) alors que `time_service.py:17` lit déjà `state.simulated_time_offsets[platform_id]` (dict par plateforme — infra multi-tenant déjà en place mais non utilisée)
- `/api/internal/set-lock` hardcodé `WHERE id=1` (bug B2) — même pattern que l'ancien bug `course-time` corrigé en avril 2026

De plus, **aucun bouton visible** n'existait pour accéder à la page admin depuis l'UI — il fallait taper `/login-admin` à la main.

## Problème / Question

Comment offrir à chaque plateforme sa propre page admin (logs, heure du cours, export, déconnexion forcée) tout en gardant le HR Dashboard comme cockpit central sur P1 ?

## Options envisagées

### Option 1 — Bouton admin visible sur le frontend apprenant

Sur chaque `Index.jsx` / `Attente.jsx` / `Video.jsx`, ajouter un lien « Espace admin » discret en footer. Rejeté : pollue l'UI apprenant, visible pour des utilisateurs à qui ça ne s'adresse pas.

### Option 2 — HR Dashboard dupliqué par plateforme

Chaque plateforme aurait son propre HR Dashboard scopé à elle-même. Rejeté : complexité pour zéro gain — P2 n'a aucune raison de gérer P3. Le HR Dashboard est par nature un cockpit multi-plateformes.

### Option 3 (retenue) — Bouton admin sur chaque carte du HR Dashboard

Sur chaque carte plateforme du HR Dashboard (uniquement sur P1, comme aujourd'hui), ajouter un bouton **Admin** qui ouvre `{frontend_url}/login-admin?p={id}` dans un nouvel onglet. L'admin atterrit sur le frontend de la plateforme, se logue, et arrive sur la page admin locale de **cette** plateforme. Session admin créée sur le bon backend, isolation naturelle par App Service.

## Décision finale

Option 3 retenue. Trois précisions critiques :

1. **`?p={id}` obligatoire dans l'URL** — chaque frontend plateforme vit sur un domaine Azure distinct (`thankful-wave`, `brave-mud`, `polite-bush`, `victorious-smoke`), donc le `localStorage` n'est pas partagé. Sans `?p=`, `api.js:10` retombe sur le default `'1'` et l'admin se logue pour P1 alors qu'il est sur le frontend P2.

2. **Helper `_get_platform_id()` backend** avec priorité explicite **header → query → session → fallback 1** (log warning) pour remplacer tous les `session.get("platform_id", 1)` cachés.

3. **Fix systématique** de toutes les routes admin (8 au total) + du endpoint `/api/internal/set-lock` (bug B2) + des deux appelants de `set-lock` dans `hr_routes.py`.

## Rationale technique

### Pourquoi le helper avec priorité header → query → session

Le bug passé (`hr-dashboard-heure-cours-figee-p2-p3`) et les bugs B1/B2 révèlent tous le même anti-pattern : `platform_id=1` comme default dans la signature d'une fonction. Quand l'appelant oublie, **l'exécution n'échoue pas** — elle écrit silencieusement dans P1. Dans un système multi-tenant, **tout default = danger**.

Le nouveau helper :
- Essaie d'abord le **header `X-Platform-Id`** (source canonique, injectée par `apiFetch` côté frontend)
- Puis la **query `?platform_id=` ou `?p=`** (pour les appels externes / bookmarks / premier chargement)
- Puis la **session** (fallback normal après premier appel avec header)
- En dernier recours, **fallback 1 avec `logger.warning`** — l'erreur remonte dans les logs au lieu d'être silencieuse

### Pourquoi refuser `/api/internal/set-lock` sans `platform_id`

Historiquement, cet endpoint était hardcodé `WHERE id=1`. Le fix pouvait être :
- (a) Lire `platform_id` depuis le body avec un default=1 → reproduit le bug latent
- (b) **Exiger `platform_id` explicite, refuser 400 sinon** ← choix retenu

L'option (b) force les appelants (`hr_routes.py:toggle_lock` et `backup-and-unlock`) à expliciter leur intention. Un nouvel appelant qui oublierait verrait son appel échouer **immédiatement** au lieu de corrompre silencieusement la ligne P1.

### Pourquoi le bouton est sur le HR Dashboard et pas sur le frontend apprenant

- L'admin est déjà dans un univers admin-only (HR Dashboard protégé par `ProtectedAdminRoute`) → cohérence d'entrée.
- Les élèves ne voient jamais le bouton → UX propre, pas de lien tentant vers une page à laquelle ils n'ont pas accès.
- Un seul point d'entrée → pas de prolifération de liens d'admin sur différentes pages.

### Session admin cross-domaine

Chaque plateforme a son propre domaine Azure Static Web Apps et son propre backend App Service. Les cookies de session ne sont **pas partagés** entre domaines. Conséquence : quand l'admin clique « Admin P2 » depuis P1, il doit se re-loguer sur P2. Accepté comme compromis : rare, transparent, aucun risque de session leak entre plateformes.

## Références code

- Helper : `backend/routes/admin_routes.py:20-40` (`_get_platform_id`)
- Routes admin fixées : `backend/routes/admin_routes.py` — `get_logs` (l.47-65), `get_course_time` (l.134-140), `config_cours` (l.185-192), `internal_set_lock` (l.214-244), `internal_get_course_time` (déjà OK, l.280), `export_excel` (l.303-318), `simulate-current-time` (l.390-405), `reset-simulation` (l.429-435), `force-logout-finished-users` (l.445-475)
- Appelants `set-lock` mis à jour : `backend/routes/hr_routes.py:395-400, 988-993`
- Frontend login admin : `frontend/src/pages/LoginAdmin.jsx:1-60` (lecture `?p=`, migration `apiFetch`, redirection `/admin?p={pid}`)
- Frontend page admin : `frontend/src/pages/Admin.jsx:28-40` (lecture `?p=`), et migration des 4 fetchs critiques vers `apiFetch`
- Frontend bouton : `frontend/src/pages/HRDashboard.jsx:~1189` (bouton Admin outline sur chaque carte)

## Leçons / Pour le mémoire

- **Tout default `platform_id=1` est un bug latent.** Dans un système qui a démarré single-tenant et qui devient multi-tenant, les defaults "compat rétro" deviennent des mines. Il faut les retirer au plus vite ou au minimum les rendre bruyants (log warning systématique). Le silence tue.

- **L'isolation par déploiement est une arme puissante.** Chaque plateforme a son App Service, son backend, sa DB SQLite. Ça veut dire que même du code buggé (admin sans filtre) ne peut leaker que sur la plateforme courante — jamais entre plateformes. Cette propriété a sauvé le projet plusieurs fois. C'est un argument fort pour la granularité "1 tenant = 1 déploiement" versus "1 gros backend mutualisé".

- **`broadcast=True` vs `room=...` — ne jamais broadcaster dans un système multi-tenant.** Le bug `force-logout` émettait vers toutes les plateformes. La règle : chaque `socketio.emit` doit préciser une `room`, jamais omettre.

- **Le pattern `?p=` dans l'URL est une ceinture de sécurité.** Le frontend a déjà `localStorage` (rapide, persistant) et les cookies de session (stables). Mais entre deux domaines Azure, aucun des deux ne traverse. Le `?p=` dans l'URL est le seul canal qui survit à un click-through cross-domain. À rigueur, c'est l'équivalent d'un **query-string-pour-l'essentiel** — pattern à généraliser.

- **Un helper central tue une famille de bugs.** Les 3 chemins précédents d'extraction de `platform_id` (`main_app.py` before_request, `formation_routes.py`, `video_routes.py`) pouvaient chacun avoir leurs propres bugs. Un helper unique avec priorité explicite (header → query → session → warning) rend le comportement **testable en un endroit**. Candidat évident : le refactoriser en middleware Flask `@require_platform` dans une prochaine itération.
