# Parallélisme enrichissement KB (3 workers)

**Date** : 2026-04-18
**Thématique** : solution technique — performance
**Statut** : implémenté

## Contexte

Test réel de la Couche 1 sur RNCP 35304 (10 compétences Haiku) : **~12 minutes** de bout en bout. Au-delà de 10 compétences (formations plus riches), le temps deviendrait prohibitif (20+ min). L'utilisateur veut raccourcir l'attente sans compromettre la qualité.

## Audit technique

### Dépendances entre appels

Chaque `enrich_competence(c)` est **totalement indépendant** :
- Entrées : `competence` + `tp_name` + `rncp_code` + règles éditoriales (statiques)
- Pas de partage d'état entre appels
- Pas de dépendance sur le résultat d'une autre compétence

→ **Parallélisable sans compromettre la qualité du contenu par compétence**.

### Ce qu'on perd (très marginal)

Théoriquement, en séquentiel Claude pourrait utiliser le résultat de compétences précédentes pour mieux remplir `liens_connexes`. Mais l'implémentation actuelle ne lui passe que son propre extract REAC — pas de cross-référence réelle → **aucune régression qualitative**.

### Contrainte bloquante : rate-limits Anthropic

Plan Anthropic payant standard (Tier 1) :
- ~50 requêtes/minute
- ~50 000 tokens input/minute

1 appel enrichissement consomme ~20k tokens input (prompt + règles + REAC extract). Donc :
- 3 appels simultanés = ~60k TPM → **tangent** au plafond, acceptable avec throttling naturel
- 5 appels = 100k TPM → **429 probable**
- 10 appels = 200k TPM → **429 garanti**

### Impact SQLite

Multiples workers écrivant simultanément dans `formation_knowledge_base` → risque "database is locked". Gérable avec un `threading.Lock` partagé sur les fonctions d'écriture (`save_enriched_competence`, `mark_competence_error`).

## Options envisagées

| Concurrence | Temps estimé (10 compétences Haiku) | Risque 429 | Complexité |
|-------------|-------------------------------------|------------|------------|
| 1 (actuel)  | 12 min                              | nul        | triviale   |
| **3**       | **~4 min**                          | **faible** | basse      |
| 5           | ~2.5 min                            | modéré     | basse      |
| 10          | ~1.5 min                            | élevé      | basse      |

## Décision finale

**Pool de 3 workers** via `concurrent.futures.ThreadPoolExecutor`. Sweet spot entre :
- Gain de temps significatif (speedup ~×3, ~66% de réduction)
- Aucun risque pratique de rate-limit sur tier standard
- Pas d'asyncio (compatible eventlet, pas de conflit trio)

Valeur paramétrable via `KB_ENRICH_CONCURRENCY` (env var) pour ajuster selon le tier Anthropic du client.

## Implémentation

### Modifications `backend/services/knowledge_base_service.py`

1. **Import** `from concurrent.futures import ThreadPoolExecutor, as_completed`
2. **Constante** `KB_ENRICH_CONCURRENCY = int(os.environ.get("KB_ENRICH_CONCURRENCY", "3"))`
3. **Lock DB** global `_DB_WRITE_LOCK = threading.Lock()` wrappé autour de `save_enriched_competence` et `mark_competence_error`
4. **Refactor `_build_kb_thread`** : boucle for séquentielle → `ThreadPoolExecutor(max_workers=KB_ENRICH_CONCURRENCY)` avec `as_completed`
5. **Fonction interne `_enrich_one(c)`** encapsule : appel Claude + save DB + gestion erreur + retour `(status, words)`

### Compatibilité eventlet

Le backend tourne en eventlet (pour SocketIO). Les `threading.Thread` standards fonctionnent car :
- `requests` HTTP lib utilise le monkey-patching eventlet → non-bloquant
- Pas de primitives asyncio (pas de conflit trio)
- Le `threading.Lock` fonctionne en eventlet

### Checkpointing préservé

Les workers écrivent chacun leur résultat en DB **au fur et à mesure**. Si crash backend pendant run :
- Les compétences déjà sauvegardées restent
- Relance → la logique résumable pré-existante (cf. mémo Couche 1) ne re-traite que `pending`/`error`
- **Pas de régression** sur la robustesse

## Conséquences observables

### UI

La barre de progression ne bouge plus linéairement 1/10 → 2/10 → 3/10 mais par "bursts" : 0/10 → 3/10 (~80s) → 6/10 → 9/10 → 10/10. Pas de changement côté code front — la barre reflète simplement la DB.

### Logs backend

Les messages `🔄 enrichissement '...'` apparaissent groupés par 3, puis `✅ ... enrichi` peuvent sortir dans un ordre différent de l'ordre d'extraction (selon vitesse de réponse Claude). Lisibilité réduite mais tolérable (chaque ligne porte le titre de la compétence).

### Coût

Inchangé (mêmes appels, mêmes tokens, juste en parallèle).

## Références code

- `backend/services/knowledge_base_service.py` :
  - Imports : ajout `concurrent.futures`
  - Constantes : `KB_ENRICH_CONCURRENCY`, `_DB_WRITE_LOCK`
  - `save_enriched_competence`, `mark_competence_error` : wrappés par le lock
  - `_build_kb_thread` : refactor boucle → pool

## Leçons / Pour le mémoire

- **Parallélisme sûr vs ambitieux** : viser le "sweet spot" (ici 3 workers) plutôt que la concurrence max permet de gagner significativement en temps sans exposer à des erreurs externes (rate-limits). Le pessimum optimum.
- **Analyser les dépendances avant de paralléliser** : ici les appels étaient déjà indépendants par conception. Dans un pipeline où chaque étape utilise la précédente, ce serait différent.
- **Les locks DB partagés dans les workers** sont une précaution simple (SQLite gère bien mais `database is locked` peut survenir sous contention). Gratuit à ajouter, évite des bugs transitoires.
- **Paramétrer via env var** (`KB_ENRICH_CONCURRENCY`) permet d'ajuster selon le contexte (tier Anthropic client, environnement dev vs prod) sans redéployer du code.
- **Observer le changement d'expérience UX** : la barre de progression devient "par bursts" → accepter cette dégradation mineure de lisibilité au profit du gain de temps global est un trade-off pragmatique.
