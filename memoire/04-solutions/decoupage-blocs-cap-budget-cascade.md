# Découpage des 7 blocs cours — cap budget par bloc, cascade des paragraphes en surplus

**Date** : 2026-04-30
**Thématique** : solution technique
**Statut** : implémenté
**Problème adressé** : `memoire/02-problemes/coupure-audio-tts-pleine-phrase.md`

---

## Principe

Chaque bloc cours reçoit un **hard cap mots** calé sur son budget audio
(`_estimated_words_budget_for_course(target_sec, api_speed)`). La fonction de choix
de frontière de découpe ne peut **jamais** sélectionner une coupure qui dépasse ce cap.
Les paragraphes en surplus sont automatiquement re-attribués au bloc suivant
(« cascade »), qui refait le calcul avec son propre cap.

Le résultat : zéro coupure brute, zéro appel LLM réactif, zéro non-déterminisme.

## Architecture du fix

### 1. Estimation du budget mots par bloc

```python
def _estimated_words_budget_for_course(target_sec, api_speed):
    voice_minutes = max(0, target_sec - _COURSE_START_SILENCE_SECONDS) / 60
    estimated_wpm = _TTS_REFERENCE_WPM_AT_095 * (api_speed / 0.95)
    return int(voice_minutes * estimated_wpm * _course_preflight_safety())
```

Constantes :
- `_COURSE_START_SILENCE_SECONDS = 17` — chaque bloc démarre par 17 s de silence
  (consigne pédagogique). Ces 17 s sont retirés du temps utile voix.
- `_TTS_REFERENCE_WPM_AT_095 = 192` — calibration empirique Fish Audio à `speed=0.95`.
- `_course_preflight_safety()` — coefficient de sécurité (défaut `0.96`,
  configurable par env var `FORMATION_TTS_PREFLIGHT_SAFETY`).

Pour un bloc de 60 min à `speed=0.90` :
- voice_minutes = (3600 - 17) / 60 ≈ 59.7
- estimated_wpm = 192 × (0.90 / 0.95) ≈ 182
- budget = 59.7 × 182 × 0.96 ≈ **10 430 mots**

Pour un bloc de 45 min : ≈ **7 800 mots**.

### 2. Cap intégré à `_choose_natural_boundary`

Avant : la fonction cherchait la fin de paragraphe la plus proche de la cible mots
dans une **fenêtre symétrique** (±700 mots). La frontière retenue pouvait être
au-dessus du budget.

Après : un nouveau paramètre `word_budget_max` est passé en argument. Tous les filtres
de candidats utilisent `min(cap_w, ...)` au lieu de `min(max_end, ...)`.

```python
if word_budget_max and word_budget_max > 0:
    cap_w = min(max_end, cursor_w + word_budget_max)
    cap_w = max(cap_w, cursor_w + 1)
else:
    cap_w = max_end

# Tous les filtres respectent ce cap :
paragraph_candidates = [
    b for b in paragraph_boundaries
    if max(cursor_w + 1, target_w - paragraph_window) <= b <= min(cap_w, target_w + paragraph_window)
]
```

L'ordre de fallback est conservé :
1. Fin de paragraphe **sous le cap**, dans la fenêtre autour de target.
2. Fin de phrase **sous le cap**, dans la fenêtre autour de target.
3. Fin de paragraphe **sous le cap** (recherche élargie).
4. Fin de phrase **sous le cap** (recherche élargie).
5. Split brut au cap (dernier recours, jamais atteint en pratique avec un texte
   correctement paragraphé).

### 3. Cascade naturelle dans `_build_course_blocs_from_segments`

La boucle principale calcule désormais le budget pour le bloc courant **avant** de
choisir sa frontière :

```python
for bloc_num in range(1, 8):
    duration = cours_durations_min[bloc_num]
    cumulative_duration += duration
    target_sec = next(
        (spec[1] for spec in playlist_spec if spec[3] == bloc_num and spec[2] == "cours"),
        duration * 60
    )
    word_budget = _estimated_words_budget_for_course(target_sec, api_speed)

    if bloc_num == 7:
        # Bloc 7 absorbe le reste : si ça dépasse son budget, c'est volume_safety
        # qui doit alerter en amont
        end_w = total_words
    else:
        target_w = round(total_words * cumulative_duration / total_duration)
        end_w = _choose_natural_boundary(
            cursor_w=cursor_w,
            target_w=target_w,
            total_words=total_words,
            remaining_blocks=7 - bloc_num,
            paragraph_boundaries=paragraph_boundaries,
            sentence_boundaries=sentence_boundaries,
            word_budget_max=word_budget,
        )
```

L'effet cascade est **émergent**, pas codé explicitement : si le bloc N s'arrête
en-dessous de sa cible (parce que la dernière fin de paragraphe sous cap était
distante), le `cursor_w` du bloc N+1 démarre plus tôt. Le bloc N+1 doit alors couvrir
plus de mots, mais il a son propre cap qui empêche le débord à son tour.

### 4. Bloc 7 traité à part

Bloc 7 est le seul à ne pas avoir de cap : il absorbe `total_words - cursor_w`. C'est
volontaire : si le total mots/jour dépasse la somme des budgets, ce n'est plus un
problème de répartition mais de **volume excessif** côté génération. Ce cas doit être
attrapé en amont par `volume_safety` (cf. `claude_code_mission_service.py`,
`_TARGET_WORDS_PER_DAY = 60000`), qui s'assure qu'aucune journée ne descend sous
60 000 mots — symétriquement, il ne devrait pas non plus dépasser largement.

Si bloc 7 dépasse malgré tout, le pré-check Fish Audio
(`_synthesize_course_audio_to_fit`) le rejette avec un message explicite, et l'erreur
remonte à l'auto-pilot — comportement souhaité (pas de coupure brute, pas d'audio
malformé en prod).

## Validation

### Tests unitaires manuels

Quatre cas couverts dans le smoke test post-implémentation :

| Cas | Configuration | end_w attendu | Résultat |
|---|---|---|---|
| 1 | Sans budget, target=500, paragraphes [480, 1200, 1800] | 480 | ✅ 480 |
| 2 | Budget large 600, target=500 | 480 | ✅ 480 |
| 3 | Budget 600, paragraphes seulement à [1200, 1800] | fin de phrase ≤ 600 | ✅ 480 |
| 4 | Budget 800, target=1000, paragraphe à 1500 | ≤ 800 | ✅ 400 (cascade vers bloc suivant de 1100 mots) |

### Vérification syntaxique

`py_compile` passe sur `content_generation_service.py`.

### Logs enrichis pour debug en prod

Le log de découpage affiche désormais le budget par bloc :

```
✂️ Bloc 1: mots 0-7842 (7842 mots / budget 7805)
✂️ Bloc 2: mots 7842-15644 (7802 mots / budget 7805)
...
```

Si un bloc 1-6 dépasse son budget (ne devrait jamais arriver avec le cap en place),
un `WARNING` explicite est loggé pour signaler la cascade attendue.

## Comparaison avec les alternatives

| Critère | LLM raccourcit (option D) | Cap budget + cascade (retenu) |
|---|---|---|
| Coût/jour de cours | ~7 appels LLM × ~5k tokens si débord systématique | 0 |
| Risque sur le contenu | LLM peut couper une notion clé jugée à tort secondaire | Aucun, paragraphes déplacés verbatim |
| Déterminisme | LLM peut produire des variantes | 100% reproductible |
| Vitesse d'exécution | +10-30 s par bloc en débord | Instantané |
| Cas d'erreur ajoutés | timeout LLM, parse error, content not found | Aucun |
| Lignes de code | ~150 (boucle de retry + prompt + parser) | ~30 (paramètre + filtres) |

## Limites

### Cas pathologique : un seul paragraphe > budget

Si le texte généré contient un paragraphe unique de 9 000 mots et que le budget du
bloc est 7 800 mots, le cap ne peut pas trouver de fin de paragraphe en-dessous. La
fonction tombe sur le fallback "fin de phrase sous cap", puis "split brut au cap".

Cas rare en pratique (les prompts demandent un découpage en paragraphes naturels
toutes les ~150-300 mots), mais possible si Claude génère un long monologue sans
double saut de ligne.

### Bloc 7 toujours risqué

Le bloc 7 n'a pas de cap. Si le total dépasse la somme des budgets, il échoue au
pré-check. La pipeline `volume_safety` doit garantir que le total reste sous le seuil,
mais elle ne vérifie actuellement que le **plancher** (60k minimum), pas le **plafond**.

À ajouter : un check symétrique côté volume_safety qui alerte si total > seuil haut
(par exemple 64k mots/jour, soit ~6% au-dessus de la cible).

## Références code

- `backend/services/content_generation_service.py` :
  - `_estimated_words_budget_for_course` (ligne ~107)
  - `_choose_natural_boundary` avec paramètre `word_budget_max` (ligne ~126)
  - `_build_course_blocs_from_segments` avec calcul du budget par bloc (ligne ~257)
- CHANGELOG 2026-04-30 : entrée *"fix: découpage TTS — cap budget par bloc, cascade
  des paragraphes en surplus"*

## Leçons / Pour le mémoire

- **Préférer le déterministe au réactif quand c'est possible.** Un fix algorithmique
  bat souvent une boucle de correction LLM, à la fois en coût, en robustesse et en
  prévisibilité.

- **Les contraintes asymétriques exigent des fenêtres asymétriques.** Quand le coût
  d'être au-dessus est très différent du coût d'être en-dessous, la recherche de
  frontière doit refléter cette asymétrie — sinon on optimise dans le mauvais sens
  une fois sur deux.

- **La cascade émergente est souvent plus robuste que l'optimisation locale.** Plutôt
  que de "faire tenir" chaque bloc dans sa cible exacte, laisser le surplus glisser
  vers le suivant produit un système plus stable face aux perturbations (variations
  de paragraphes, taille de phrases).

- **Un hard cap est souvent plus utile qu'un objectif fin.** Cibler une valeur exacte
  invite à dépasser ; plafonner garantit qu'on ne casse rien. Pour un système
  pipelined où chaque étage a une contrainte dure (ici : durée du créneau audio), le
  cap est l'invariant à protéger.

- **Le code mort à supprimer post-fix.** Avec le cap en place, plusieurs blocs de
  fallback dans `_choose_natural_boundary` (`late_paragraph`, `late_sentence` qui
  cherchaient au-delà de `max_end`) sont devenus inutiles : ils ne peuvent plus être
  atteints. Ils ont été supprimés dans la même PR pour éviter la confusion future.
