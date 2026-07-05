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
DATABASE_BACKEND=postgres
PIPELINE_DATABASE_BACKEND=postgres
PIPELINE_POSTGRES_MIRROR=0
DB_PATH=/home/database-saas-copy.db
```

`DB_PATH` reste volontairement separe de l'ancienne base Formation3 pour eviter
de reutiliser l'etat SQLite de la plateforme formation 3.

Les valeurs sensibles doivent exister soit dans Azure App Settings de
`Formation3`, soit dans les secrets GitHub :

```text
SAAS_POSTGRES_DATABASE_URL ou DATABASE_URL ou SUPABASE_DB_URL
SAAS_SUPABASE_URL ou SUPABASE_URL
SAAS_SUPABASE_ANON_KEY ou SUPABASE_ANON_KEY
SAAS_SUPABASE_SERVICE_ROLE_KEY ou SUPABASE_SERVICE_ROLE_KEY
```

Le workflow echoue avant le deploiement si ces reglages ne sont pas disponibles
dans Azure ni dans GitHub Secrets.

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
