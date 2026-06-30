# Supabase Postgres Migration

## Decision

Le Socrate doit passer progressivement de SQLite vers PostgreSQL pour le SaaS multi-tenant :

- `SQLite` reste utilisable en local et pendant la transition.
- `Supabase Postgres` devient la cible staging / production SaaS.
- Azure Blob Storage reste la source des fichiers lourds : audio, PDF, DOCX, archives.
- Postgres garde les donnees metier : centres, plateformes, eleves, logs, commandes IA, paiements.

## Why Supabase First

Supabase est le bon choix maintenant parce que le projet utilise deja Supabase Auth cote eleves, et parce que Postgres reste standard. Si besoin, une migration ulterieure vers Azure Database for PostgreSQL restera possible.

Azure PostgreSQL pourra devenir pertinent plus tard si toute l'infra doit etre consolidee dans Azure avec plus de controle reseau/ops.

## Required Access

Pour executer la migration reelle, il faut une URL Postgres, jamais committee :

```bash
export DATABASE_URL='postgresql://postgres.<project-ref>:<password>@<pooler-host>:6543/postgres?sslmode=require'
```

Dans Supabase, prendre de preference le connection string du pooler transaction pour une app web hebergee. Garder le mot de passe dans Azure App Settings ou dans `backend/.env` local.

## Files

- `backend/database/postgres_schema.sql` : schema Postgres cible pour le coeur SaaS.
- `backend/tools/database/apply_postgres_schema.py` : applique le schema sur Supabase/Postgres.
- `backend/tools/database/migrate_sqlite_core_to_postgres.py` : copie les donnees coeur depuis SQLite.
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

Les tables lourdes de pipeline pedagogique restent a migrer dans une seconde passe. Elles contiennent beaucoup de JSON/artefacts intermediaires et demandent une decision produit : tout garder dans Postgres, archiver une partie en Blob, ou repartir uniquement des modules valides.

## Runtime Switch

Ne pas basculer tout le runtime en Postgres tout de suite. Le code contient encore beaucoup de SQL SQLite specifique dans la pipeline :

- placeholders `?`
- `PRAGMA table_info`
- migrations inline au demarrage
- `lastrowid`
- quelques patterns `INSERT OR ...`

Modes supportes :

- `DATABASE_BACKEND=sqlite` : mode historique/local, Postgres ignore.
- `DATABASE_BACKEND=hybrid` : phase 1 actuelle. Le coeur SaaS utilise Postgres quand disponible, tout en gardant SQLite pour la pipeline.
- `DATABASE_BACKEND=postgres` : cible future, a reserver au moment ou la pipeline aura aussi son adapter Postgres.

En mode `hybrid`, les chemins suivants passent par `repositories/core_repository.py` :

1. Auth centre et session admin.
2. Resolution publique `/classe/:centerSlug/:platformSlug`.
3. Creation de plateformes centre : SQLite reste le support pipeline, Postgres recoit la fiche SaaS avec le meme `platform_id`.
4. Profils eleves Supabase et logs de presence : miroir Postgres progressif.
5. Commandes IA : creation/listing en Postgres, paiement Stripe a brancher ensuite.

## Security: RLS

Supabase signale actuellement que RLS est desactive sur les tables publiques du coeur SaaS. Ne pas activer RLS sans politiques : cela bloquerait les acces applicatifs.

La remediation brute indiquee par Supabase est :

```sql
ALTER TABLE public.training_center_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cours_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.video_visits ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.student_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.student_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_teacher_orders ENABLE ROW LEVEL SECURITY;
```

Avant de l'executer, definir les policies par role :

- acces serveur via service role pour les routes Flask ;
- lecture publique tres limitee pour la resolution des classes publiees, ou mieux aucun acces direct client et tout via Flask ;
- isolation stricte par `center_account_id` pour les centres ;
- isolation par `platform_id` pour les eleves.
