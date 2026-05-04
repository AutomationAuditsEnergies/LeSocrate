# SQLite local vs Azure SQL — arbitrage persistance

**Date** : 2026-04-17
**Thématique** : décision technique
**Statut** : arbitré (SQLite retenu)

## Contexte

Lors de l'ajout de la table `formation_knowledge_base` (Couche 1 — enrichissement REAC), la question de la persistance s'est posée : faut-il stocker cette nouvelle table en SQLite local (comme le reste du projet) ou l'exposer à Azure SQL Database / Azure Database for PostgreSQL pour bénéficier d'un backup managé, d'une haute disponibilité, de la scalabilité horizontale ?

## État de l'art côté projet

Le Socrate utilise **SQLite uniformément** :
- **En développement** : `backend/database/socrate.db`
- **En production Azure** : `/home/database.db` (disque persistant d'Azure App Service)
- Les migrations sont exécutées au démarrage du backend (`init_db()` dans `backend/database/db.py`), donc identiques en dev et prod.
- Architecture multi-tenant : chaque plateforme P1/P2/P3/P4 a son propre App Service et son propre fichier SQLite. Pas de base partagée entre plateformes.

## Options envisagées

### Option A — Garder SQLite (retenu)

**Avantages :**
- Cohérence architecturale : toutes les tables du projet restent au même endroit
- Coût : zéro (fichier local sur App Service)
- Performance : lecture locale, pas de latence réseau
- Volume maîtrisé : ~225 KB par job formation (15 compétences × 2500 mots × overhead JSON), soit ~22 MB pour 100 formations
- Backup : snapshot disque Azure App Service suffit
- Le pattern checkpointing avec flag `dirty` (issu de `content_generation_segments`) est déjà éprouvé sur SQLite

**Limites :**
- Pas de scaling horizontal (1 App Service = 1 fichier DB). Déjà le cas pour toutes les autres tables du projet.
- Concurrence en écriture limitée (locking fichier). Pas un problème pour l'usage actuel (quelques utilisateurs admin).

### Option B — Migrer uniquement `formation_knowledge_base` vers Azure SQL

**Rejeté** car :
- Crée une incohérence architecturale (DB mixte SQLite + Azure SQL dans le même backend)
- Complexité maintenance (deux clients DB, deux sets de migrations)
- Latence réseau pour une table majoritairement lue/écrite en batch
- Volume trop faible pour justifier le coût (~$5-15/mois minimum pour Azure SQL Basic)

### Option C — Migrer TOUTE la DB vers Azure SQL / PostgreSQL

**Reporté**. Pertinent si les conditions suivantes apparaissent :
- Multi-instance backend (scaling horizontal nécessaire)
- Volume de données > 1 GB
- Besoin de backup managé avec RPO/RTO garantis
- Requêtes analytiques complexes (BI, dashboard agrégé multi-plateformes)

Aucune de ces conditions n'est remplie aujourd'hui.

## Décision finale

Conserver SQLite pour la table `formation_knowledge_base` — aligné avec le reste du projet. La migration vers une DB managée, si elle devient nécessaire, sera faite **pour toutes les tables d'un coup**, pas par morceaux.

## Rationale technique

**Principe général retenu** : la cohérence architecturale l'emporte sur l'optimisation ponctuelle. Mélanger deux systèmes de persistance pour une seule table crée une dette technique disproportionnée par rapport aux bénéfices.

**Seuils de bascule** (pour décision future) :
- Volume cumulé toutes plateformes > 1 GB
- Besoin d'au moins 2 instances backend simultanées
- Incident de perte de données SQLite avéré (ex: App Service recréé)

## Références code

- `backend/database/db.py` — init_db() avec migrations idempotentes
- `CLAUDE.md` — documentation officielle du choix SQLite
- Tables actuelles en SQLite : `logs`, `cours_config`, `platform_config`, `cours_folders`, `cours_documents`, `content_generation_jobs`, `content_generation_segments`, `deletion_requests`, `video_visits`, `formation_pipeline_jobs`, `formation_knowledge_base`

## Leçons / Pour le mémoire

- **La cohérence architecturale est une valeur en soi** : une stack homogène (même si sub-optimale localement) se maintient mieux qu'une stack hybride parfaitement optimisée par composant.
- **SQLite est sous-estimé** : pour des projets mono-instance avec des volumes < 1 GB, il suffit largement et évite une dépendance cloud.
- **Les seuils de bascule doivent être explicites** : sans critères définis, on migre trop tôt (over-engineering) ou trop tard (dette accumulée). Définir les seuils maintenant permet de trancher rationnellement plus tard.
- **Azure App Service + SQLite au `/home`** : architecture légitime mais à documenter explicitement car contre-intuitive par rapport à la norme cloud-native (DB séparée systématiquement).
