# Copie SaaS Postgres sur Formation3

Objectif : utiliser l'infrastructure Azure qui servait a `Formation3` comme
copie de travail du SaaS actuel, avec Postgres/Supabase, pendant que `staging`
peut revenir a une version SQLite stable pour la formation live.

## Branche de copie

La branche de copie est :

```text
codex/current-saas-postgres-20260705
```

Elle part de `4af0581`, l'etat courant de `staging` au 2026-07-05.

Les workflows suivants sont rattaches a cette branche, pas a `staging` :

- backend Azure App Service `Formation3` :
  `.github/workflows/staging_formation3.yml`
- frontend Azure Static Web App `polite-bush-07d4fdd03` :
  `.github/workflows/azure-static-web-apps-polite-bush-07d4fdd03.yml`

## Backend

Le workflow backend configure `Formation3` comme copie SaaS :

```text
DATABASE_BACKEND=hybrid
PIPELINE_DATABASE_BACKEND=postgres
PIPELINE_POSTGRES_MIRROR=0
DB_PATH=/home/database.db
SQLITE_SAFETY_STRICT=0
POSTGRES_POOL_MIN_SIZE=1
POSTGRES_POOL_MAX_SIZE=12
POSTGRES_POOL_TIMEOUT_SECONDS=30
PIPELINE_EXECUTION_MODE=queue
PIPELINE_QUEUE_BACKEND=database
PIPELINE_EMBEDDED_WORKER=1
PIPELINE_ARTIFACTS_REQUIRED=1
```

`DATABASE_BACKEND=hybrid` garde le comportement actuel de `socrate1` : le coeur
SaaS utilise Postgres quand il est disponible, et la pipeline est forcee sur
Postgres via `PIPELINE_DATABASE_BACKEND=postgres`.

Avant chaque deploiement, le workflow applique
`backend/database/postgres_schema.sql`. Au boot, le backend verifie ensuite les
tables et colonnes indispensables a la pipeline ; un schema incomplet bloque le
demarrage avec la liste exacte des elements manquants.

Le garde-fou SQLite historique bloque l'application si la base pointee par
`DB_PATH` est neuve ou trop petite. Pour eviter une maintenance artificielle
sur cette copie Postgres, `SQLITE_SAFETY_STRICT=0` autorise le demarrage meme
si la SQLite fallback est petite. La source cible reste Postgres/Supabase via
`DATABASE_BACKEND=hybrid` et `PIPELINE_DATABASE_BACKEND=postgres`.

`hybrid` reste un mode de transition pour les dernières routes historiques,
mais la pipeline et les GET RH principaux utilisent maintenant PostgreSQL. Le
planning et les rappels basculent eux aussi sur PostgreSQL lorsque
`DATABASE_BACKEND=postgres`; ils restent volontairement SQLite pendant le mode
`hybrid`. La file DB durable est traitée par un worker embarqué ; sous forte
charge, passer ce worker dans un App Service ou WebJob séparé et activer Azure
Service Bus.

Les valeurs sensibles doivent exister soit dans Azure App Settings de
`Formation3`, soit dans les secrets GitHub :

```text
SAAS_POSTGRES_DATABASE_URL ou DATABASE_URL ou SUPABASE_DB_URL
SAAS_SUPABASE_URL ou SUPABASE_URL
SAAS_SUPABASE_ANON_KEY ou SUPABASE_ANON_KEY
SAAS_SUPABASE_SERVICE_ROLE_KEY ou SUPABASE_SERVICE_ROLE_KEY
SAAS_AZURE_TTS_STORAGE_CONNECTION_STRING ou AZURE_TTS_STORAGE_CONNECTION_STRING
SAAS_INTERNAL_ADMIN_PASSWORD_HASH ou INTERNAL_ADMIN_PASSWORD_HASH
SAAS_AUTO_LOGOUT_WEBHOOK_SECRET ou AUTO_LOGOUT_WEBHOOK_SECRET
SAAS_SECRET_KEY ou SECRET_KEY
```

Le workflow echoue avant le deploiement si ces reglages ne sont pas disponibles
dans Azure ni dans GitHub Secrets.

L'Azure Logic App qui appelle `POST /deconnexion-auto-tous` doit envoyer le
header `X-Internal-Secret` avec la valeur de `AUTO_LOGOUT_WEBHOOK_SECRET`.

## Frontend

Le frontend `polite-bush-07d4fdd03` pointe vers :

```text
https://formation3-cpdhezh4cdcqecfy.francecentral-01.azurewebsites.net
```

Il devient le frontend unique de la copie SaaS. Les URLs publiques des
plateformes 1 a 9 sont donc configurees cote backend vers ce meme frontend.

## Rollback staging prevu

Le point SQLite stable cible est :

```text
8f8740e 2026-06-29 12:06:23 +0200 Improve mobile responsive training pages
```

Il n'y a pas de commit entre 13h30 et 14h00 le 2026-06-29 dans l'historique
visible. Il faut donc utiliser `8f8740e` comme etat "lundi dernier vers 14h".

Ne pas rollback `staging` tant que la copie Formation3/Postgres n'a pas ete
deployee et verifiee.
