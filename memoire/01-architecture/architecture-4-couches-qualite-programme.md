# Architecture qualité programme — 4 couches

**Date** : 2026-04-17
**Thématique** : architecture
**Statut** : couche 1 à implémenter

## Contexte

Le pipeline formation peut être paramétré pour N jours (ex: 14 journées × 7h). Le REAC source fait environ 15 000 mots. À 192 mots/min en TTS, 14 jours × 6h utile = ~968 000 mots générés. **Ratio de dilution : 65:1** (1 mot source → 65 mots sortie).

Sans architecture dédiée à la qualité, ce ratio garantit que Claude doit "broder" pour remplir, menant à :
- Redondance non pédagogique (répétitions creuses)
- Contenu hors-sujet (digressions pour meubler)
- Perte de densité informationnelle en fin de formation

## Problème / Question

Comment produire un programme solide et apportant de la valeur, **quel que soit le nombre de jours choisi** (2, 7, 14, 30) ?

## Options envisagées

### Intuition initiale : RAG sur le REAC

Idée : chunker le REAC, l'indexer dans un vector store (Azure AI Search ou alternative), retrieve au moment de générer chaque sous-partie.

**Verdict : inadapté.** Le REAC (95k caractères) entre entièrement dans la fenêtre de contexte de Claude Sonnet 4 (200k tokens). RAG sert à retrouver l'aiguille dans une botte de foin — ici on a la botte en main. Ajouter RAG = complexité sans bénéfice.

Cf. mémo dédié : [Audit RAG sur REAC](../03-decisions/audit-rag-sur-reac.md).

### Architecture retenue : 4 couches spécialisées

#### Couche 1 — Enrichissement structuré (priorité haute)

Avant la génération du programme, transformer le REAC en **base de connaissances dense** via Claude :

```
Pour chaque compétence du REAC :
  - Définition pédagogique (200 mots)
  - 3-5 études de cas concrètes
  - Erreurs fréquentes / pièges
  - Vocabulaire métier + synonymes
  - Mise en contexte terrain (acteurs, enjeux)
  - Liens vers compétences connexes
```

Stockage : table SQLite `formation_knowledge_base`. Multiplie le matériau exploitable par 8-10× (15k → 120-150k mots).

#### Couche 2 — Alerte densité (quick win)

Dans l'UI, afficher le **ratio de dilution** calculé avant lancement :

> ⚠️ Ratio densité : 65 mots générés / 1 mot source — formation à risque de dilution. Recommandé : enrichir la base de connaissances ou réduire à 9 jours.

L'utilisateur arbitre en connaissance de cause.

#### Couche 3 — Squelette pédagogique imposé

Plutôt que laisser Claude freelancer la structure des journées, imposer un rôle par jour (inspiré taxonomie de Bloom) :

- Jour 1 : Découverte / panorama
- Jours 2-3 : Fondamentaux (savoirs)
- Jours 4 à N-3 : Approfondissements par bloc métier (savoir-faire)
- Jours N-2, N-1 : Études de cas / mise en situation
- Jour N : Synthèse / préparation certification

Template micro-progression par sous-partie : Rappel → Concept → Exemple → Application → Synthèse.

#### Couche 4 — RAG externe optionnel

Un vault **Obsidian par métier** avec notes pédagogiques de référence (manuels, articles, jurisprudence métier). Pipeline embedding local + injection chunks pertinents dans le prompt de la Couche 1.

**Ici** RAG prend son sens : le corpus externe est large, évolutif, et pertinent seulement par extraits.

## Décision finale

Implémenter dans l'ordre :

1. **Couche 1 (enrichissement)** — 1-2 jours dev, résout 80% du problème
2. **Couche 2 (alerte densité)** — 1h dev, évite mauvaises surprises UX
3. **Couche 3 (squelette pédagogique)** — 3-4h dev, cadre Claude
4. **Couche 4 (RAG Obsidian)** — seulement si 1+2+3 insuffisant sur certains métiers

## Rationale technique

- **Priorité au levier qualité / effort** : l'enrichissement est le meilleur ROI car il agit à la source (plus de matière = moins de broderie).
- **Séparation enrichissement / génération** : permet de réutiliser la knowledge base pour plusieurs formations du même métier (ex: TP CRCD 7 jours vs. 14 jours partagent la même base enrichie).
- **RAG réservé aux corpus volumineux** : principe général — n'utiliser RAG que quand le corpus dépasse la fenêtre de contexte du modèle.

## Références code

- `backend/services/formation_pipeline_service.py:556` — `build_daily_programs` actuel (sans Couche 1)
- `backend/services/content_generation_service.py` — point d'injection futur de la knowledge base
- À créer : `backend/services/knowledge_base_service.py` (Couche 1)

## Leçons / Pour le mémoire

- **RAG n'est pas une solution universelle** : c'est un outil adapté à un problème spécifique (corpus > contexte modèle). L'appliquer par défaut est un anti-pattern.
- **Le vrai problème de qualité en génération IA longue est la densité de source**, pas les capacités du modèle. Multiplier la matière source propre bat toutes les optimisations de prompt.
- **L'architecture en couches séparées** permet d'itérer et mesurer le gain de chaque couche indépendamment (principe d'ingénierie expérimentale).
- **La taxonomie de Bloom** reste pertinente 70 ans après : un bon squelette pédagogique imposé vaut mieux qu'une IA sans garde-fous.
