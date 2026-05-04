# HR Dashboard — heure du cours P2/P3 figée après reload

**Date** : 2026-04-17
**Thématique** : problème
**Statut** : résolu

## Contexte

Le Dashboard RH (hébergé par P1) pilote les plateformes distantes P2/P3/P4 via des appels service-to-service (`/api/internal/*` protégés par `X-Platform-Key`). L'utilisateur règle l'heure de début du cours par plateforme depuis une modale du dashboard.

## Problème

Symptôme reporté : sur P2 (Formation 2 TPCE) et P3 (Formation 3 TPCE), modifier l'heure du cours dans la modale affichait bien un toast "enregistré", mais au rafraîchissement de la page l'heure réaffichée était l'ancienne (bloquée au 13 avril 2026). La BDD distante était pourtant mise à jour.

## Cause racine

Asymétrie de gestion du `platform_id` entre la route POST et la route GET côté backend distant (`admin_routes.py`) :

- **POST `/api/internal/config-cours`** (écriture) : lit `platform_id` depuis le body JSON et appelle `set_heure_debut_cours(heure, platform_id)` → la bonne ligne `cours_config WHERE platform_id=2` est mise à jour sur la BDD locale de P2. ✅
- **GET `/api/internal/course-time`** (lecture) : appelait `get_heure_debut_cours()` **sans argument** → le paramètre par défaut `platform_id=1` s'appliquait → sur la BDD locale de P2, la fonction relisait la ligne `platform_id=1` (créée à l'init, jamais écrite depuis le dashboard). ❌

Conséquence : l'écriture et la lecture ciblaient deux lignes différentes de la même table sur le même backend distant. D'où l'illusion d'une sauvegarde perdue.

Note importante : chaque backend (P1/P2/P3) a sa propre BDD SQLite. Sur la BDD de P2, les lignes pertinentes sont `platform_id=2` (écriture) vs `platform_id=1` (lecture). C'est un bug purement "local" au backend distant, pas un problème réseau.

## Options envisagées

1. **Passer `platform_id` en query string pour le GET** (symétrique au POST qui l'a dans le body). Correction minimale, cohérente avec le reste.
2. **Déduire le `platform_id` depuis une variable d'environnement sur chaque backend distant** (ex : `PLATFORM_ID=2`). Plus propre à long terme mais demande une variable d'env par App Service, et modifie le contrat implicite "le backend distant ne connaît pas sa propre identité".
3. **Ajouter un champ `PLATFORM_ID` à `platform_config`** sur chaque BDD distante. Plus invasif, migration nécessaire.

## Décision

Option 1 retenue : on passe `?platform_id=<id>` en query string dans l'appel proxy `_call_platform`, et le handler distant lit `request.args.get("platform_id")` puis le passe à `get_heure_debut_cours(platform_id)`.

Raison : changement de 2 lignes, symétrique à la logique POST déjà en place, pas de nouvelle config d'infra, pas de migration.

## Rationale technique

- Le multi-tenant actuel fonctionne sur le principe "1 backend distant = 1 plateforme", donc en théorie l'ID pourrait être implicite. Mais le code existant a déjà choisi de le rendre **explicite dans les appels service-to-service** (cf. POST config-cours, set-lock). Rester dans cette convention évite d'introduire une exception.
- L'asymétrie a probablement été introduite lors d'un correctif antérieur (cf. CHANGELOG ligne 293 : POST `config-cours` corrigé mais pas GET `course-time`). C'est un bug de cohérence, pas un choix de design.

## Références code

- `backend/routes/hr_routes.py:1088` — appel proxy GET, ajout de `?platform_id={platform_id}`
- `backend/routes/admin_routes.py:259-277` — lecture de `platform_id` depuis `request.args`, propagation à `get_heure_debut_cours`
- `backend/services/time_service.py:66-92` — `get_heure_debut_cours(platform_id=1)` déjà multi-tenant, le bug était uniquement sur l'appelant

## Leçons / Pour le mémoire

- **Les endpoints read/write d'une même ressource doivent être symétriques sur leur modèle d'identification.** Si POST attend `platform_id` dans le body, GET doit l'attendre en query (ou inversement). Une asymétrie invisible côté code produit une incohérence visible côté utilisateur.
- **Bug typique du multi-tenant à démarrage progressif** : quand on passe d'un mode single-tenant (`platform_id=1` partout) à multi-tenant, les "defaults = 1" sont des mines. Ils masquent le bug tant qu'on ne teste que P1, et cassent silencieusement sur P2/P3.
- **Symptôme trompeur** : "ça dit enregistré mais rien ne persiste" → réflexe naturel de chercher un problème d'écriture (transaction non commitée, cache, permissions). Ici l'écriture fonctionne, c'est la lecture qui ment. Vérifier lecture ET écriture avant de conclure.
- **Valeur des logs structurés** : `set_heure_debut_cours` logge `⏰ Mise à jour heure début cours P{platform_id}`, ce qui aurait permis de voir immédiatement "on écrit P2, on lit P1" en corrélant logs distants.
