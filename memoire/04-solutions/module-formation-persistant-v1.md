# Module formation persistant — V1

**Date** : 2026-04-23
**Thématique** : solution — implémentation du principe "1 RNCP = 1 module durable"
**Statut** : implémenté (staging), en observation

## Contexte

Le principe [un-rncp-un-module-durable.md](../01-architecture/un-rncp-un-module-durable.md) était posé comme doctrine mais rien dans le code ne matérialisait un "module" comme entité distincte d'une plateforme / d'un job pipeline. Résultat : pour "créer une nouvelle promo CRCD", il fallait soit relancer la pipeline complète (coût Claude + Fish Audio + ~1h), soit cloner manuellement les blobs d'une plateforme existante via une copie artisanale (formation-source → nouvelle plateforme). Les deux options trahissaient le principe.

## Problème

- Pas d'identité "module" séparée des plateformes consommatrices.
- La modale "Nouvelle plateforme" proposait de cloner à partir d'une `formation_id` (entité interne pipeline), ce qui mélangeait la couche "factory" (pipeline) et la couche "catalog" (produits livrables).
- Aucun moyen de lister les modules disponibles indépendamment des plateformes actives.
- Risque de re-générer sans s'en rendre compte : rien ne signalait "ce RNCP a déjà un module, ne relance pas la pipeline".

## Décision V1

Séparation explicite des 3 couches :

| Couche     | Entité                 | Responsabilité                                    |
| ---------- | ---------------------- | ------------------------------------------------- |
| Factory    | `pipeline_jobs`        | Exécution de la pipeline (process jetable)         |
| Catalog    | `formation_modules`    | Produit persistant validé (1 ligne par RNCP+version) |
| Consumer   | `platform_config`      | Plateforme consommatrice (instance de promo)       |

### Table `formation_modules` (nouvelle)

```
id, rncp_code, tp_name, version (ex: "2026-v1"),
status ('draft'|'validated'|'archived'),
source_pipeline_job_id UNIQUE,
source_platform_id,
created_at, validated_at, archived_at
```

L'UNIQUE sur `source_pipeline_job_id` garantit qu'un même job ne peut pas créer 2 modules (idempotence des relances de `launch_audio`).

### Auto-création au `audio_launched`

Dès que `launch_audio` passe le job en `audio_launched`, un `INSERT OR IGNORE` crée la ligne `formation_modules` avec `status='validated'` et version `{year}-v{n}` (n = count existant sur ce RNCP + 1). Le module devient sélectionnable immédiatement dans la modale "Nouvelle plateforme" — pas besoin d'attendre la fin du TTS.

### Modale "Nouvelle plateforme" pilotée par modules

La modale HR Dashboard n'offre plus `{formation_id}` (legacy, gardé pour compat), mais un select `module_id` listant les `formation_modules` validés. Création d'une plateforme avec `module_id` → clone serveur-side Azure des blobs de la plateforme-source du module (`source_platform_id`) + copie des `cours_folders` / `cours_documents` via `_clone_formation_async` dans `hr_routes.py`.

### Migration rétroactive

Dans `database/db.py`, à la création de la table, scan des `pipeline_jobs` avec `status IN ('audio_launched', 'completed')` → `INSERT OR IGNORE` pour créer un module rétroactif par job existant. Évite la discontinuité avec les modules déjà "produits de fait" avant V1.

### UI — retours visuels

- Bannière "Module créé et disponible" sur `/formation-pipeline` quand `linkedModule` existe.
- Bouton "Modules" dans le header HR Dashboard → modale catalog listant les modules disponibles.
- Badge sur carte plateforme : indique si la plateforme est `source_module_id` (module origine) ou `source_formation_id` (legacy clone).

## Ce qui est différé (V2)

- **Copy-on-write réel** : aujourd'hui la clone = copie physique des blobs. À terme, résolution en cascade côté lecture (plateforme regarde d'abord son container, puis fallback sur le module). Économie de stockage mais refactor lecture complet.
- **États draft/validated/archived gérés par UI** : actuellement tous les modules sont auto-`validated`. Pas de flow "valider un module après relecture".
- **Versioning multi-variantes** : un seul module par RNCP aujourd'hui (sauf re-run forcé). Pas de gestion de variantes (court/long, public débutant/avancé).

## Points d'attention connus (au moment de l'implémentation)

- **TTS silencieux** : le 2026-04-23 en fin de session, la pipeline passe bien en `audio_launched` et le module est bien créé, mais les MP3 ne sont pas produits côté Azure malgré le fix ffmpeg (`silence_1s.mp3` embarqué) et le fix `force_all=True`. Les requêtes `launch-audio` renvoient 200 mais le greenlet async échoue silencieusement. **À creuser à la reprise** : logs Azure juste après click, probablement une exception silencieuse dans le greenlet de `playlist_tts_service`.

## Références code

- `backend/database/db.py` — migration `formation_modules` + rétroactive
- `backend/routes/hr_routes.py` — `_clone_formation_async`, `create_platform` (4 modes), `GET /api/hr/formation-modules`
- `backend/routes/formation_routes.py` — auto-création module au `audio_launched`
- `frontend/src/pages/HRDashboard.jsx` — modale modules + badge plateforme
- `frontend/src/pages/FormationPipeline.jsx` — bannière "Module créé"

## Leçons

1. **Matérialiser les doctrines dans le schéma.** Tant que "module durable" n'était qu'un principe dans `CLAUDE.md`, il était contournable. Ajouter la table + l'UI force la discipline.
2. **Auto-création > validation manuelle pour la V1.** Ajouter un flow de validation humaine aurait bloqué l'adoption. L'auto-`validated` permet d'observer l'usage réel avant de décider si un flow de draft est utile.
3. **Idempotence via contrainte SQL > logique applicative.** L'UNIQUE sur `source_pipeline_job_id` rend les relances de `launch_audio` sûres sans devoir raisonner sur l'état.
