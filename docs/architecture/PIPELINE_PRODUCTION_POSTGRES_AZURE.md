# Architecture production de la pipeline

## Décision

La logique qui fonctionnait avec SQLite est conservée : mêmes étapes,
checkpoints, reprises et artefacts. Le changement nécessaire pour le SaaS est
la séparation des responsabilités :

- PostgreSQL managé est la source de vérité des données métier et de l'état de
  la pipeline ;
- Azure Blob stocke les DOCX, JSON de diagnostic, slides et audios ;
- une file durable exécute les étapes longues hors du cycle HTTP ;
- SQLite reste un backend local/test et un mode de transition explicite, jamais
  un miroir faisant autorité en production.

Le code reste compatible avec Supabase Postgres et Azure Database for
PostgreSQL via `DATABASE_URL`. Si le backend tourne déjà sur Azure et que la
charge augmente, Azure Database for PostgreSQL Flexible Server simplifie le
réseau privé, l'observabilité et la haute disponibilité. Supabase Auth peut
rester utilisé sans que les données métier y soient stockées.

## Flux d'exécution

```text
API /run-auto
  -> work-item + outbox dans PostgreSQL (transaction)
  -> worker claim avec lease + jeton de fencing
  -> une étape idempotente de la machine d'état
  -> checkpoints PostgreSQL + artefacts Azure Blob
  -> completion + work-item suivant (transaction)
  -> retries avec backoff, puis dead-letter si épuisé
```

Azure Service Bus est optionnel et ne contient que des identifiants. PostgreSQL
reste la source de vérité, ce qui rend une notification perdue ou dupliquée
inoffensive. Sans Service Bus, le worker poll la même file PostgreSQL.

## Modes supportés

### Développement local

```dotenv
DATABASE_BACKEND=sqlite
PIPELINE_DATABASE_BACKEND=sqlite
PIPELINE_EXECUTION_MODE=inline
PIPELINE_QUEUE_BACKEND=database
```

### Staging immédiatement exploitable

Le worker est embarqué dans l'App Service, mais les jobs sont déjà durables. Ce
mode est une transition contrôlée : la pipeline est PostgreSQL, tandis que les
dernières mutations RH historiques restent SQLite jusqu'à leur portage.
Le planning opérationnel, les séances, les mots de passe de séance et les
rappels suivent toutefois `PIPELINE_DATABASE_BACKEND` : ils sont donc déjà
autoritaires dans PostgreSQL dans ce mode et ne retombent jamais sur SQLite.

```dotenv
DATABASE_BACKEND=hybrid
PIPELINE_DATABASE_BACKEND=postgres
PIPELINE_EXECUTION_MODE=queue
PIPELINE_QUEUE_BACKEND=database
PIPELINE_EMBEDDED_WORKER=1
```

### Cible production sous charge

À activer après la migration des dernières mutations RH legacy. L'API et le
worker sont alors déployés séparément, sans dépendance SQLite :

```dotenv
DATABASE_BACKEND=postgres
PIPELINE_DATABASE_BACKEND=postgres
PIPELINE_EXECUTION_MODE=queue
PIPELINE_QUEUE_BACKEND=service_bus
PIPELINE_EMBEDDED_WORKER=0
AZURE_SERVICE_BUS_NAMESPACE=<namespace>.servicebus.windows.net
PIPELINE_SERVICE_BUS_QUEUE=formation-pipeline
```

Commande du worker :

```bash
cd backend
python -m workers.pipeline_worker
```

L'identité managée du worker doit avoir les rôles Azure Service Bus Data Sender
et Data Receiver. Le container d'artefacts Blob doit rester privé.

## Stockage des artefacts

```dotenv
AZURE_TTS_STORAGE_CONNECTION_STRING=...
AZURE_PIPELINE_ARTIFACT_CONTAINER=pipeline-artifacts
PIPELINE_ARTIFACTS_REQUIRED=1
PIPELINE_BLOB_MAX_ATTEMPTS=3
```

Les écritures Blob sont idempotentes (`overwrite`) et retentées. En production,
un artefact obligatoire non sauvegardé fait échouer l'étape au lieu de produire
un succès trompeur. Les gros binaires ne doivent pas être placés dans
PostgreSQL.

## Concurrence

La concurrence interne d'un job est bornée à trois journées par défaut et huit
au maximum. Le débit SaaS vient du nombre de workers, pas d'un fan-out de 52
journées dans un seul process :

```dotenv
FORMATION_CONTENT_DAY_WORKERS=3
FORMATION_CONTENT_DAY_WORKERS_MAX=8
POSTGRES_POOL_MAX_SIZE=12
```

Chaque worker possède une lease renouvelée et un jeton de fencing. Une instance
ancienne ne peut ni terminer ni libérer le travail repris par une nouvelle
instance.

## Migration et cutover

1. Geler les écritures SQLite et réaliser une sauvegarde cohérente.
2. Appliquer `backend/database/postgres_schema.sql`.
3. Exécuter la migration core, puis pipeline, sur une base staging.
4. Comparer les compteurs, tester un job complet avec artefacts et reprise.
5. Basculer d'abord la pipeline en PostgreSQL, puis les derniers domaines
   legacy, sans dual-write bidirectionnel.
6. Garder l'ancienne SQLite en lecture seule pendant la fenêtre de retour
   arrière.

```bash
cd backend
python tools/database/migrate_sqlite_core_to_postgres.py \
  --database-url "$DATABASE_URL" \
  --sqlite-path database/socrate.db \
  --apply-schema

python tools/database/migrate_sqlite_pipeline_to_postgres.py \
  --database-url "$DATABASE_URL" \
  --sqlite-path database/socrate.db
```

Les scripts valident les FK, tenants, JSON, booléens, UUID et timestamps avant
toute mutation, migrent par lots et recalent les séquences `BIGSERIAL`.

### Blocage détecté sur la base actuelle

Le préflight refuse actuellement le cutover core : `platform_id=12` est absent
de `platform_config`, mais une ligne subsiste dans `cours_config`,
`course_schedule_config` et `course_sessions`. Il faut décider explicitement de
restaurer cette plateforme ou de supprimer ces trois lignes si elles sont des
données de test. Aucune suppression automatique n'est faite.

## Sécurité de déploiement

- `SECRET_KEY`, `INTERNAL_ADMIN_PASSWORD_HASH` et
  `AUTO_LOGOUT_WEBHOOK_SECRET` sont obligatoires sur Azure ;
- aucun mot de passe centre en clair n'est migré ou conservé ;
- le fallback REST Supabase est désactivé lorsque la base métier est Azure ;
- les tokens API sont signés et valides entre plusieurs instances ;
- l'appartenance d'un élève à une plateforme vient exclusivement du profil
  serveur, jamais des `user_metadata` Supabase modifiables par l'utilisateur ;
- RLS bloque l'accès Data API direct aux tables métier ;
- `/healthz` teste le process et `/readyz` la base et la configuration Blob.

## Vérification continue

Le workflow `postgres-ci.yml` démarre PostgreSQL 16, applique deux fois le
schéma idempotent, puis exécute les tests d'intégration, de migration, de RLS,
de queue et de repository avant tout déploiement staging.

Références Azure : [WebJobs](https://learn.microsoft.com/azure/app-service/webjobs-create),
[identité managée Service Bus](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-managed-service-identity),
[livraison et déduplication](https://learn.microsoft.com/azure/service-bus-messaging/duplicate-detection).
