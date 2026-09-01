# Supabase Postgres Migration

## Decision

Le Socrate doit passer progressivement de SQLite vers PostgreSQL pour le SaaS multi-tenant :

- `SQLite` reste utilisable en local et pendant la transition.
- un `PostgreSQL managé` (Supabase ou Azure Database for PostgreSQL) devient la cible staging / production SaaS.
- Azure Blob Storage reste la source des fichiers lourds : audio, PDF, DOCX, archives.
- Postgres garde les donnees metier : centres, plateformes, eleves, logs, commandes IA, paiements.

## Choix du fournisseur

Supabase Auth peut rester côté élèves indépendamment du fournisseur de la base
métier. Lorsque le backend et Blob sont déjà sur Azure, Azure Database for
PostgreSQL est une cible naturelle pour le réseau privé, la haute disponibilité
et l'exploitation. Le code n'utilise aucune extension propriétaire et accepte
les deux via `DATABASE_URL`.

## Required Access

Pour executer la migration reelle, il faut une URL Postgres, jamais committee :

```bash
export DATABASE_URL='postgresql://postgres.<project-ref>:<password>@<pooler-host>:6543/postgres?sslmode=require'
```

Pour Azure App Service (processus backend persistant), prendre de preference le
pooler Supavisor en mode **Session** (`:5432`), ou la connexion directe si le
reseau IPv6 est disponible. Le mode Transaction (`:6543`) est surtout adapte
aux fonctions serverless/ephemeres ; il reste supporte ici avec les prepared
statements psycopg desactives. Garder le mot de passe dans Azure App Settings
ou dans `backend/.env` local.

## Files

- `backend/database/postgres_schema.sql` : schema Postgres cible pour le coeur SaaS.
- `backend/tools/database/apply_postgres_schema.py` : applique le schema sur Supabase/Postgres.
- `backend/tools/database/migrate_sqlite_core_to_postgres.py` : copie les donnees coeur depuis SQLite.
- `backend/tools/database/migrate_sqlite_pipeline_to_postgres.py` : copie les donnees pipeline depuis SQLite.
- `backend/.env.example` : variables attendues.

## Bootstrap Supabase

Installer les dependances backend :

```bash
pip install -r backend/requirements.txt
```

Appliquer le schema :

```bash
DATABASE_URL='postgresql://...' \
python backend/tools/database/apply_postgres_schema.py
```

Copier les donnees coeur depuis SQLite :

```bash
DATABASE_URL='postgresql://...' \
python backend/tools/database/migrate_sqlite_core_to_postgres.py --apply-schema
```

Copier ensuite les donnees pipeline :

```bash
DATABASE_URL='postgresql://...' \
python backend/tools/database/migrate_sqlite_pipeline_to_postgres.py --apply-schema
```

Pour repartir d'une base cible vide sur les tables coeur :

```bash
DATABASE_URL='postgresql://...' \
python backend/tools/database/migrate_sqlite_core_to_postgres.py --apply-schema --truncate
```

## Migrated Core Tables

Le script migre volontairement le coeur SaaS :

- `training_center_accounts`
- `platform_config`
- `cours_config`
- `logs`
- `video_visits`
- `student_accounts`
- `student_profiles`
- `course_schedule_config`
- `course_sessions`
- `course_reminder_recipients`
- `student_attendance_records`
- `ai_teacher_orders`
- `deletion_requests`

Les tables de pipeline sont migrées dans une seconde passe. PostgreSQL conserve
les métadonnées/checkpoints ; Azure Blob conserve les binaires et artefacts
lourds.

## Pipeline Migration

La pipeline dispose d'un repository commun SQLite/Postgres :

- `PIPELINE_DATABASE_BACKEND=sqlite` : la pipeline lit/ecrit SQLite.
- `PIPELINE_POSTGRES_MIRROR=1` : la pipeline garde SQLite comme source de verite
  mais miroir-ecrit `formation_pipeline_jobs` vers Postgres quand
  `DATABASE_BACKEND` et `DATABASE_URL` activent Postgres.
- `PIPELINE_DATABASE_BACKEND=postgres` : jobs, plateformes creees par la
  pipeline, dossiers, segments, reviews, evenements, slides et modules utilisent
  Postgres comme source de verite. Le demarrage valide le contrat de schema et
  echoue explicitement si une table/colonne requise manque.

Le workflow Formation3 applique maintenant le schema idempotent avant le
deploiement. Il ne faut plus compter sur `CREATE TABLE IF NOT EXISTS` seul pour
faire evoluer une table deja provisionnee : les ajouts de colonnes sont exprimes
avec `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.

Le rollback le plus simple est de remettre `PIPELINE_DATABASE_BACKEND=sqlite`
et de desactiver `PIPELINE_POSTGRES_MIRROR`.

## Runtime Switch

Le planning opérationnel (`course_schedule_*`, `course_sessions`, rappels et
audio planifié) utilise désormais PostgreSQL dès que
`PIPELINE_DATABASE_BACKEND=postgres`. Les GET principaux du dashboard RH lisent
également PostgreSQL. `DATABASE_BACKEND=hybrid` reste nécessaire tant que les
dernières routes RH mutatives et quelques fonctions historiques ne sont pas
portées ; il ne faut basculer en mode pur qu'après leurs tests de cutover.

Les motifs SQLite a ne plus introduire dans un chemin Postgres sont :

- placeholders `?`
- `PRAGMA table_info`
- migrations inline au demarrage
- `lastrowid`
- quelques patterns `INSERT OR ...`

Modes supportes :

- `DATABASE_BACKEND=sqlite` : mode historique/local, Postgres ignore.
- `DATABASE_BACKEND=hybrid` : phase de transition actuelle. Postgres est la
  source de verite de la fabrication ; SQLite garde temporairement les routes
  HR/planning non migrees.
- `DATABASE_BACKEND=postgres` : cible finale, sans initialisation, backup ni
  fallback SQLite silencieux.

## Connection Pool

Chaque worker Azure reutilise un pool psycopg borne au lieu d'ouvrir une
connexion par checkpoint :

```text
POSTGRES_POOL_MIN_SIZE=1
POSTGRES_POOL_MAX_SIZE=12
POSTGRES_POOL_TIMEOUT_SECONDS=30
```

Dimensionner `POSTGRES_POOL_MAX_SIZE × nombre_de_workers` sous la limite de
connexions du projet Supabase.

## Architecture cible

- Postgres/Supabase : etat transactionnel, relations multi-tenant, checkpoints,
  index de recherche et metadonnees interrogeables.
- Azure Blob Storage : MP3, PDF, DOCX, archives et gros artefacts immuables.
- Une seule source de verite par agregat : aucune lecture SQLite de secours
  silencieuse lorsqu'un job est Postgres.
- Conserver temporairement les JSON historiques en `TEXT` maintient le contrat
  Python (`json.loads`). Migrer ensuite vers `JSONB` uniquement pour les champs
  effectivement filtres/requetes, avec une migration et des index GIN cibles.

En mode `hybrid`, les chemins suivants passent par `repositories/core_repository.py` :

1. Auth centre et session admin.
2. Resolution publique `/classe/:centerSlug/:platformSlug`.
3. Creation de plateformes centre : SQLite reste le support pipeline, Postgres recoit la fiche SaaS avec le meme `platform_id`.
4. Profils eleves Supabase et logs de presence : miroir Postgres progressif.
5. Commandes IA : creation/listing en Postgres, paiement Stripe a brancher ensuite.

Le fallback PostgREST est désactivé par défaut. Il ne doit jamais rediriger une
panne d'Azure PostgreSQL vers le projet Supabase utilisé uniquement pour Auth.
La file durable et le runbook complet sont documentés dans
`docs/architecture/PIPELINE_PRODUCTION_POSTGRES_AZURE.md`.

## Security: RLS

Le schema active RLS sur toutes les tables exposees dans `public`, sans policy
`anon` ni `authenticated`. C'est volontaire : le navigateur utilise Supabase
Auth, mais toutes les donnees metier passent par Flask. Le role proprietaire de
la connexion Postgres et la `service_role` utilisee par le fallback serveur
conservent leur acces privilegie ; un client muni de la cle publique ne peut pas
lire les tables via PostgREST.

Les anciens mots de passe en clair de debug sont effacés lors de l'application
du schéma et ne sont plus migrés ni écrits. `SECRET_KEY` et le hash du
super-admin sont des secrets obligatoires de déploiement.

Si une lecture directe depuis le frontend est introduite plus tard, ajouter une
policy minimale et testee pour cette table uniquement, avec isolation stricte
par `center_account_id` ou `platform_id`. Ne jamais ajouter une policy globale
permissive pour contourner une erreur d'autorisation.
