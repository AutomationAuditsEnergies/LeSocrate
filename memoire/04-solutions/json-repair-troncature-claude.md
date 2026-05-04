# Réparation JSON tolérante à la troncature (max_tokens atteint)

**Date** : 2026-04-17
**Thématique** : solution technique
**Statut** : implémenté

## Contexte

Premier test réel de la Couche 1 sur RNCP 35304 (TP CRCD) avec Claude Haiku 4.5 : 10 compétences extraites, 8 enrichies avec succès, **2 en erreur**. Les logs backend :

```
⚠️ Retry 1/3 enrichissement 'Adopter un comportement orienté vers l'autre en relation client à distance' : Unterminated string starting at: line 96 column 23 (char 25096)
⚠️ Retry 2/3 : idem
⚠️ Retry 3/3 : idem
❌ Enrichissement 'Adopter un comportement...' : Unterminated string
```

Les 2 compétences les plus "riches pédagogiquement" (où Claude a beaucoup à dire) sont systématiquement celles qui échouent.

## Diagnostic

### Cause racine

Claude Haiku 4.5 a une limite de sortie de **8 000 tokens** (~24 000 caractères). Le prompt d'enrichissement demande :
- Définition pédagogique (~250 mots)
- 4-6 études de cas (chacune ~300 mots)
- 4-6 pièges fréquents (~130 mots chacun)
- 8-15 termes de vocabulaire (~40 mots chacun)
- Contexte terrain (~200 mots)

Total typique : 2000-3500 mots. Mais sur certaines compétences, Claude génère 4000+ mots et **dépasse les 8 000 tokens**. La réponse est alors **coupée mid-string** par l'API Anthropic :

```json
{
  "definition_pedagogique": "...",
  "etudes_de_cas": [
    {"titre": "Cas 1", "situation": "...", ...},
    {"titre": "Cas 2", "situation": "..."   ← coupure ici, pas de " fermant
```

Le JSON est donc **invalide syntaxiquement** → `json.loads()` lève `JSONDecodeError: Unterminated string` → catch → retry → Claude regénère → même dépassement → coupe au même endroit → boucle d'échec.

### Pourquoi les retries ne résolvent rien

Les retries ont du sens pour les erreurs **non déterministes** (timeout réseau, rate-limit Anthropic, erreur transitoire 500). Mais la troncature est **déterministe** : même input → même output → même troncature. 3 retries identiques = 3 échecs identiques.

## Options envisagées

### 1. Augmenter max_tokens (rejeté pour Haiku)

`max_tokens=12000` fonctionne pour Sonnet 4 mais **refusé par Haiku 4.5** avec erreur 400 "invalid_request_error" car dépasse la limite du modèle.

### 2. Réduire la densité du prompt (rejeté)

Demander "2-3 études de cas" au lieu de "4-6" réduirait la richesse de la KB. Dégradation qualitative pour résoudre un problème de quantité.

### 3. Basculer systématiquement sur Sonnet (rejeté)

Sonnet ~5× plus cher que Haiku. Le use-case Couche 1 bénéficie du coût modéré de Haiku. Mieux : rendre Haiku robuste.

### 4. Réparer le JSON tronqué (retenu)

Principe : si la réponse est coupée mid-field, garder tous les champs précédents complets et fermer proprement les structures ouvertes.

## Implémentation

### Fonction `_repair_truncated_json(text)` — algorithme

1. **Parcours char par char** en suivant :
   - État `in_string` (True entre `"` non échappés)
   - État `escape_next` (True après `\`)
   - Pile des fermants attendus (`]` / `}`)
   - `last_safe` : position après la dernière occurrence de `,`, `}` ou `]` **hors string**

2. **Troncature** à `last_safe` (dernier endroit où on a un élément complet)

3. **Suppression** de la virgule terminale éventuelle

4. **Reconstruction de la pile** sur la portion conservée (pour gérer les structures déjà fermées proprement avant la troncature)

5. **Fermeture** des crochets/accolades restants

### Intégration dans `_parse_json_response`

```python
try:
    return json.loads(text)
except json.JSONDecodeError as first_err:
    logger.warning(f"⚠️ JSON malformé ({first_err}), tentative de réparation")
    repaired = _repair_truncated_json(text)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        raise first_err
```

## Conséquences

### Bénéfice principal

Une compétence "riche" qui produisait auparavant une erreur complète produit maintenant un JSON partiel valide : par exemple 4 études de cas complètes au lieu de 6 (si la 5ème est coupée au milieu). **Contenu partiellement sauvé > contenu totalement perdu**.

### Limite

Si la troncature arrive **avant** la première virgule complète (très tôt dans le JSON), la fonction retourne `{}` (dict vide). Cas rare en pratique.

### Effet secondaire positif

Réduit le nombre de retries inutiles sur les erreurs déterministes de troncature.

## Références code

- `backend/services/knowledge_base_service.py` — fonctions `_parse_json_response` et `_repair_truncated_json`
- Premier cas identifié : job 5 (RNCP 35304), compétences 9 et 10 sur 10

## Leçons / Pour le mémoire

- **Les limites de sortie des LLMs sont hétérogènes** : Haiku 4.5 max 8k tokens, Sonnet 4 max 64k. Toute architecture multi-modèle doit prévoir cette différence.
- **Les retries aveugles sont inutiles sur erreurs déterministes** : distinguer les erreurs transitoires (réseau, rate-limit) des erreurs déterministes (troncature, prompt invalide) et n'appliquer les retries qu'aux premières.
- **Tolérance aux formats dégradés** : accepter un contenu partiel vaut souvent mieux que d'échouer complètement. Principe applicable à tout parsing d'outputs LLM.
- **La réparation ad-hoc de JSON tronqué** est un pattern utile à généraliser à d'autres endroits où on attend du JSON d'un LLM dans le projet.
