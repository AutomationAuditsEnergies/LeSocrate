# Révision conformité — chunking texte 1500 mots + concurrence bornée

**Date** : 2026-04-30
**Thématique** : solution technique
**Statut** : implémenté
**Décision parente** : `03-decisions/review-conformite-5-salves.md`

---

## Contexte

Une fois les 5 salves de révision en place (cf. décision parente), un second problème
émerge : chaque salve audite un **segment entier** (~5 000 mots, soit ~6 500 tokens
en français). Sur cette taille d'input, on observe à nouveau une dilution
d'attention — mais cette fois sur le **texte audité**, pas sur les règles.

Le LLM "voit" le début et la fin du segment, mais omet les violations dans le
milieu. Symptôme : sur un segment de 5 000 mots avec 8 violations connues, la salve
n'en remonte que 3, **toutes situées dans les 1500 premiers ou derniers mots**.

## Problème

### Dilution d'attention sur le texte audité

C'est la **même mécanique** que pour la dilution sur les règles, mais inversée :
- Salves : on a découpé les 27 règles → 5 groupes pour que le LLM ne perde aucune règle
- Segments : il faut découper les 5 000 mots → chunks plus petits pour que le LLM ne
  perde aucun passage

### Contraintes externes

- **Rate-limit DeepSeek-v4-pro** : limite de concurrence dynamique, ~5-10 requêtes
  parallèles avant 429. On ne peut pas envoyer les chunks en rafale complète.
- **Rate-limit Anthropic** : limite tokens/minute par compte, plus strict en pratique
  que le RPM.
- **Patches ordonnés par chunk** : si on parallélise, les résultats ne reviennent pas
  forcément dans l'ordre des chunks → les positions des patches dans le texte
  reconstitué deviennent fausses si on ne re-trie pas.

## Solution

### 1. Découpage paragraph-aware en chunks de 1500 mots

Constante : `_REVIEW_CHUNK_WORDS = 1500` (configurable via
`FORMATION_REVIEW_CHUNK_WORDS`, min 300).

```python
def _chunk_text(text, max_words=1500):
    """Découpe en chunks aux frontières de paragraphes (\\n\\n)."""
```

L'algorithme accumule des paragraphes jusqu'à dépasser la cible, puis bascule au
chunk suivant. Conserve les `\n\n` à l'intérieur des chunks. Préfère un chunk un peu
plus long qu'une coupure mid-paragraphe.

Métadonnées par chunk :
```python
{"index": 1, "total": N, "text": "...", "words": 1487}
```

`index` et `total` sont injectés dans le prompt (*"Tu audites le CHUNK 3/4 d'un segment
plus long. Ne juge que le texte fourni ci-dessous."*) pour que le LLM sache qu'il
n'est pas censé voir le contexte des autres chunks.

### 2. Concurrence bornée via `eventlet.GreenPool`

Constante : `_REVIEW_CHUNK_CONCURRENCY = 2` (configurable via
`FORMATION_REVIEW_CHUNK_CONCURRENCY`, min 1).

```python
pool = eventlet.GreenPool(size=_REVIEW_CHUNK_CONCURRENCY)
pile = eventlet.GreenPile(pool)
for chunk in chunks:
    pile.spawn(_review_chunk_with_retries, prompt, group_label, chunk["index"], model)
results = list(pile)
results.sort(key=lambda r: r["chunk"]["index"])  # crucial
```

`pool=2` est le sweet spot empirique :
- DeepSeek tolère 2 requêtes parallèles sans 429 dans 99% des cas
- Anthropic tolère bien 2 par compte sur les modèles Sonnet
- Gain de vitesse ~2x vs séquentiel, sans risque de cascading rate-limits

### 3. Re-tri par index post-pile

Découverte par audit : `GreenPile` peut yielder les résultats **dans l'ordre où les
greenlets terminent**, pas dans l'ordre des spawns. Si chunk 2 termine avant chunk 1,
le tri post-pile rétablit l'ordre attendu — sinon les patches du chunk 2 seraient
appliqués avant ceux du chunk 1, cassant les positions verbatim.

```python
results.sort(key=lambda r: r["chunk"]["index"])
```

### 4. Retries respectant les codes de rate-limit

`_review_chunk_with_retries(prompt, group_label, chunk_index, model)` :
- 3 tentatives max
- Sur `AnthropicRateLimitError` : sleep `e.wait_seconds` (lu depuis le header
  `Retry-After` de la réponse 429), pas une valeur fixe
- Sur `AnthropicAPIError.is_deterministic` (codes 400/401/403) : **aucun retry** —
  ces erreurs ne sont pas transitoires, retenter ne change rien et perd du temps
- Sur autres erreurs (5xx, parse JSON, etc.) : retry avec backoff exponentiel

`_cooperative_sleep(seconds)` : utilise `eventlet.sleep` en priorité, fallback
`time.sleep` (pour les contextes hors greenlet).

## Architecture finale

```
Pour chaque segment :
    Pour chaque groupe (5 salves) :
        chunks = _chunk_text(current_text, 1500)        # paragraph-aware
        prompts = [_build_review_prompt_focused(...) for c in chunks]

        pile = GreenPile(GreenPool(size=2))
        for prompt, chunk in zip(prompts, chunks):
            pile.spawn(_review_chunk_with_retries, ...)
        results = sorted(list(pile), key=lambda r: r["chunk"]["index"])

        Pour chaque résultat :
            patches = result["patches"]
            current_text = apply_patches(current_text, patches)

    si toutes les salves OK : reviewed = 1
    sinon : review_error
```

Salves **séquentielles** entre elles. Chunks **parallèles** au sein d'une salve.

## Validation empirique

Sur le segment de référence (5 000 mots, 8 violations connues injectées
artificiellement) :
- Avant chunking : 3/8 violations détectées (37.5%)
- Avec chunking 1500 mots : 7/8 violations détectées (87.5%)
- Avec chunking 1000 mots : 8/8 mais coût × 1.5

1500 mots est le sweet spot : assez court pour que le LLM lise tout, assez long pour
ne pas exploser le coût.

## Limites

### La 8ᵉ violation parfois manquée

Avec chunking 1500, il reste un cas où une violation tombe exactement à la frontière
de chunk et est partiellement présente dans deux chunks. Aucun des deux LLM appels ne
voit le contexte complet et la violation passe.

Atténuation : les patches sont appliqués cumulativement (la salve suivante voit le
texte patché). Si la violation tient sur deux salves différentes (ex. éthique +
style), elle a deux chances d'être attrapée.

### Pas de chunk overlap

On ne fait pas chevaucher les chunks (overlap), ce qui simplifierait le cas
ci-dessus mais introduirait des doublons de patches à dédupliquer. Choix conservateur
pour V1.

## Références code

- `backend/services/content_generation_service.py` :
  - `_REVIEW_CHUNK_WORDS`, `_REVIEW_CHUNK_CONCURRENCY` (~ligne 1219)
  - `_chunk_text` (paragraph-aware splitting)
  - `_review_chunk_with_retries` (retry policy)
  - `_review_group_chunks` (pile + tri post-pile)
  - `run_content_review` (orchestration salves × chunks)
- `backend/utils/anthropic_client.py` : `AnthropicRateLimitError.wait_seconds`,
  `AnthropicAPIError.is_deterministic`
- CHANGELOG 2026-04-30 : *"feat: review API stricte — chunking texte + concurrence bornée"*

## Leçons / Pour le mémoire

- **La dilution d'attention frappe les deux côtés du prompt** : règles ET texte. Il
  faut découper les deux, pas un seul.

- **Les outils de concurrence ne préservent pas l'ordre par défaut.** Un `GreenPile`
  yielde dans l'ordre des terminaisons, pas des spawns. Toujours porter un index
  explicite et trier post-collecte si l'ordre compte.

- **`wait_seconds` du rate-limit > backoff fixe.** Le serveur sait combien de temps
  attendre ; le client le sait pas. Lire la valeur du header au lieu de deviner.

- **Distinguer erreurs déterministes vs transitoires.** Retry sur 400 = retry sur la
  même erreur, perte de temps. Le code d'erreur HTTP est une donnée, l'utiliser pour
  la stratégie.

- **Le sweet spot de la taille de chunk est empirique.** 1000 mots = trop coûteux,
  2000 = dilution résiduelle. La calibration vaut la peine d'être faite *par tâche*,
  pas hérité d'une convention générale.
