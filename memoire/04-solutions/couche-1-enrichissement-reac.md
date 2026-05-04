# Couche 1 — Enrichissement REAC → Knowledge Base

**Date** : 2026-04-17
**Thématique** : solution technique
**Statut** : implémenté (à tester en conditions réelles)

## Contexte

Répond au problème de [dilution REAC → formation TTS](../02-problemes/ratio-dilution-reac.md) identifié dans l'[architecture 4 couches](../01-architecture/architecture-4-couches-qualite-programme.md). Première couche implémentée, visant à réduire le ratio de dilution en multipliant la matière source par 8-10× avant génération du programme.

## Problème / Question

Comment transformer un REAC brut (~15 000 mots, extrait PyPDF2 d'un PDF officiel France Compétences) en une base de connaissances pédagogique dense (~120-150k mots) structurée et exploitable par Claude pour la génération du programme de formation ?

## Décision finale

**Pipeline en 2 étapes Claude**, checkpointé en DB, insérable dans le pipeline formation existant entre "Téléchargement REAC" et "Programme global".

### Étape 1 — Extraction structurée

Un seul appel Claude sur le REAC entier (80k caractères max, entre largement dans la fenêtre de contexte). Sortie : JSON listant 8-20 compétences clés, avec pour chacune :
- `bloc` (CCP ou bloc de compétences)
- `competence_title` (titre exact)
- `competence_key` (slug kebab-case)
- `raw_source` (extrait fidèle du REAC, 200-500 mots)

### Étape 2 — Enrichissement par compétence

Un appel Claude **par compétence** (séquentiel pour respecter les rate-limits Anthropic). Chaque appel produit :
- `definition_pedagogique` (~250 mots)
- `etudes_de_cas` (4-6 études, chacune avec titre/situation/enjeu/résolution/variantes)
- `pieges_frequents` (4-6 pièges avec pourquoi + comment éviter)
- `vocabulaire_metier` (8-15 termes)
- `contexte_terrain` (200 mots immersifs)
- `liens_connexes` (liste de competence_keys reliées)

**Volume attendu** : ~1500-2500 mots enrichis par compétence × 15 compétences ≈ **23-38k mots par bloc** × plusieurs blocs = **120-150k mots** au total.

## Rationale technique

### Pourquoi séquentiel et non parallèle

Les appels Claude à 15 compétences en parallèle = 15 requêtes simultanées sur un même API key, risque rate-limiting (429) sur l'endpoint Anthropic. Séquentiel = temps total ~15×15s = 4 min, acceptable pour une étape de background.

### Pourquoi checkpointing + flag `dirty`

Si une compétence échoue (timeout, JSON invalide), on ne refait pas les 14 autres. Même pattern que `content_generation_segments` pour les passes TTS. Permet aussi régénération sélective si l'utilisateur édite une compétence.

### Pourquoi garder le REAC brut en référence

Dans le prompt du programme global, on injecte la KB enrichie **en source primaire** mais on garde 8k chars de REAC brut **en source secondaire**. Claude peut ainsi vérifier la fidélité au REAC officiel (évite les hallucinations pédagogiques introduites par la Couche 1).

### Pourquoi `max_tokens=8000` par enrichissement

Calibration : 1500-2500 mots produits ≈ 2000-3500 tokens output. 8000 laisse de la marge sans exploser le coût.

## Détails d'implémentation

### Base de données

Nouvelle table `formation_knowledge_base` (migration dans `backend/database/db.py`) :

```sql
CREATE TABLE formation_knowledge_base (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    competence_index INTEGER NOT NULL,
    competence_key TEXT NOT NULL,
    competence_title TEXT NOT NULL,
    bloc TEXT,
    raw_source TEXT,
    definition_pedagogique TEXT DEFAULT '',
    etudes_de_cas TEXT DEFAULT '[]',         -- JSON array
    pieges_frequents TEXT DEFAULT '[]',      -- JSON array
    vocabulaire_metier TEXT DEFAULT '{}',    -- JSON dict
    contexte_terrain TEXT DEFAULT '',
    liens_connexes TEXT DEFAULT '[]',        -- JSON array
    status TEXT DEFAULT 'pending',           -- pending | processing | completed | error
    dirty INTEGER DEFAULT 0,
    error_message TEXT,
    total_words INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES formation_pipeline_jobs(id),
    UNIQUE(job_id, competence_index)
);
```

### Nouveaux statuts jobs

- `kb_building` : enrichissement en cours (polling 3s côté front)
- `kb_ready` : KB complète, programme global peut être lancé

### Nouvelles routes

- `POST /api/formation/<id>/enrich-reac` — lance l'enrichissement (body `{model?}` pour choisir Sonnet/Haiku)
- `GET /api/formation/<id>/kb` — retourne entrées + stats (total, completed, error, total_words)

### Modification du prompt programme global

Dans `_generate_global_program_thread` (`formation_pipeline_service.py`), injection conditionnelle :
- Si KB existe → source primaire = KB enrichie structurée + source secondaire = REAC brut (8k chars)
- Sinon → fallback comportement précédent (REAC 15k chars)

## UI

Nouveau `StepBlock` stepIndex=2 dans `frontend/src/pages/FormationPipeline.jsx`, intercalé entre "Téléchargement REAC" et "Programme global" :
- Barre de progression live pendant `kb_building` (compétences completed/total)
- Stats affichées en `kb_ready` : nb compétences enrichies, mots totaux, erreurs
- Détail expandable listant chaque compétence avec son statut
- Boutons "Relancer (Sonnet)" / "Relancer (Haiku)"

Décalage des stepIndex suivants : Programme global 2→3, Journées 3→4, TTS 4→5.

## Références code

- `backend/database/db.py:338-370` — migration table `formation_knowledge_base`
- `backend/services/knowledge_base_service.py` (nouveau, 300 lignes) — orchestration complète
- `backend/routes/formation_routes.py:272-312` — routes `enrich-reac` + `kb`
- `backend/services/formation_pipeline_service.py:472-495` — injection KB dans prompt global
- `frontend/src/pages/FormationPipeline.jsx:17-45` — `statusToStep` + `STEP_LABELS` mis à jour
- `frontend/src/pages/FormationPipeline.jsx:493` — state `kb`
- `frontend/src/pages/FormationPipeline.jsx:773-880` — StepBlock enrichissement KB

## Cohérence éditoriale avec la génération TTS

**Problème identifié après implémentation initiale** : la Couche 1 produit du contenu (études de cas, pièges, vocabulaire, contexte) qui sera injecté dans la génération du cours audio final. Si ce contenu viole les règles éditoriales (religion, alcool, paris, hallucination, manipulation, etc.), ces violations se propagent dans le cours TTS — et les règles éditoriales des 3 passes TTS n'arriveront plus à "nettoyer" après coup car elles travaillent à partir de la source enrichie.

**Solution** : les prompts d'enrichissement chargent **dynamiquement** la section "CONTENU — RÈGLES ABSOLUES" + "HALLUCINATION" (règles #1 à #20) depuis le fichier `prompt-generation-tts-direct.md`, éditable par l'utilisateur via `/schedule-config` → `POST /api/hr/tts-prompt`.

**Conséquences** :
- Une seule source de vérité pour les règles éditoriales (le fichier markdown)
- Quand l'utilisateur édite les règles dans l'UI, la Couche 1 les applique au prochain appel (cache invalidé par `mtime`)
- Pas de duplication ni de divergence possible entre les 2 phases du pipeline

**Implémentation** : fonction `_load_editorial_rules()` dans `knowledge_base_service.py` avec cache invalidé sur mtime. Regex extrait la section entre "CONTENU — RÈGLES ABSOLUES" et "FORMAT DE SORTIE". Rules injectées via placeholder `{EDITORIAL_RULES}` dans `_EXTRACT_COMPETENCES_PROMPT` et `_ENRICH_COMPETENCE_PROMPT`.

**Points d'attention spécifiques ajoutés au prompt d'enrichissement** :
- Études de cas fictives doivent être annoncées comme telles dans la clé `situation`
- Vocabulaire métier : factuel, pas de références proscrites
- Pièges fréquents : décrire des comportements à éviter, pas à maîtriser
- Contexte terrain : strictement professionnel

## Impact attendu sur le ratio de dilution

Pour une formation 14 jours (644k mots output) :
- Avant Couche 1 : ratio 15k → 644k = **43:1** (zone critique)
- Après Couche 1 : ratio 150k → 644k = **4.3:1** (zone sûre)

À valider par mesure empirique sur le premier job réel.

## Leçons / Pour le mémoire

- **La dilution est combattue à la source, pas à la sortie** : multiplier la matière propre en amont bat toutes les optimisations de prompt en aval.
- **Le pattern "appel Claude par unité" (ici compétence) + checkpointing** permet des pipelines longs robustes, où chaque échec isolé coûte 1 retry au lieu de tout recommencer.
- **La structure JSON explicite dans les prompts** (schema attendu montré au modèle) donne une fiabilité de parsing supérieure à un format libre, et facilite l'évolution du schéma.
- **Décaler des stepIndex UI sans régression** requiert d'auditer tous les `currentStep > N` et `currentStep === N` — le test manuel ne suffit pas, il faut grepper.
- **Le coût par formation** va augmenter (15 compétences × ~5k tokens input + 3k output = ~120k tokens Claude Sonnet 4, soit ~$0.50-1 par formation) mais reste négligeable par rapport au coût TTS Fish Audio (~$5-15 par formation).
