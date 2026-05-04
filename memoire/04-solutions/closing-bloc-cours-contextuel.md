# Closing contextuel de bloc cours — redistribution backward + texte de fin adaptatif

**Date** : 2026-04-30
**Thématique** : solution technique
**Statut** : implémenté
**Décision parente** : `02-problemes/coupure-audio-tts-pleine-phrase.md` + extension
**Mémo connexe** : `04-solutions/decoupage-blocs-cap-budget-cascade.md`

---

## Contexte

Après l'introduction du cap budget cascade (cf. mémo connexe), un cas restait :
**les blocs qui terminent trop tôt** (undershoot). Le code original paddait le MP3
avec du silence à la fin du fichier — l'apprenant entend la fin du cours sur une
phrase, puis 30 secondes à 4 minutes de silence, puis l'audio de pause.

Cas typique : un bloc de 45 min (target 7 800 mots) où la fin de paragraphe la plus
proche du cap se trouve à 7 200 mots ⇒ 600 mots d'undershoot ⇒ ~3 min de silence
final.

## Problème

### Le silence padding casse la pédagogie

Pédagogiquement, terminer un bloc cours sur 3 minutes de silence est pire qu'inutile :
- L'apprenant croit que c'est un bug
- Coupe la dynamique de cours
- Casse l'illusion d'un "vrai prof" qui clôt sa séance proprement

### Le bouchage symétrique cap budget ne résout pas l'undershoot

Le cap budget protège **contre l'overshoot** (bloc trop long → cascade vers
suivant). L'**undershoot** (bloc trop court) n'est pas symétrique — il n'y a rien à
"recevoir" mécaniquement, juste du silence à éviter.

### Première intuition rejetée : combler par du blabla générique

Mettre 4 min de "voilà pour cette partie, prenez votre temps" est aussi mauvais que
le silence : du remplissage perçu comme tel. Pas pédagogique.

## Solution en deux passes

### Passe 2 — Redistribution backward (déterministe, gratuite)

**Avant de générer du texte synthétique, on essaie de combler le bloc avec du VRAI
contenu** : tirer les premiers paragraphes du bloc suivant tant qu'ils rentrent
dans le budget.

Algorithme dans `_redistribute_undershoot_backward(...)` :

```python
THRESHOLD = 30  # gap > 30s déclenche

for bloc N in 1..6:
    while gap_sec(bloc N) > THRESHOLD:
        first_para_end_in_next = première fin de paragraphe dans bloc N+1
        additional_words = first_para_end_in_next - bloc[N+1].start_w

        if bloc N.word_count + additional_words > bloc N.word_budget:
            break  # paragraphe trop gros
        if next_bloc n'a qu'un seul paragraphe:
            break  # ne pas vider entièrement le bloc suivant

        bloc[N].end_w = first_para_end_in_next
        bloc[N+1].start_w = first_para_end_in_next
        # boucle, tente le suivant
```

Préserve **les unités d'idée pédagogiques** : jamais de paragraphe coupé. Si un
paragraphe est trop gros pour rentrer, on s'arrête. Marque les blocs touchés
`dirty=1` (audio à régénérer).

### Passe 3 — Closing contextuel (LLM ou template adapté au gap résiduel)

Pour le gap qui reste après passe 2, on **ajoute du texte au bloc** avant le seul
appel TTS Fish Audio. Le service dédié est `closing_transition_service.py`.

Le registre du closing **dépend de la taille du gap** :

| Gap résiduel    | Registre                  | Cible mots | Source       |
|-----------------|---------------------------|------------|--------------|
| < 15 s          | Aucun (silence padding)   | 0          | —            |
| 15–45 s         | Phrase de clôture courte  | 30–100     | Template     |
| 45–120 s        | Transition pédagogique    | 130–360    | LLM Sonnet   |
| 120–300 s       | Recap + respiration       | 360–700    | LLM Sonnet   |
| Bloc 7 (final)  | Conclusion de journée     | selon gap  | LLM Sonnet   |

Cap absolu : **700 mots max** (≈ 4 min audio). Si le gap dépasse 5 min, le résidu
reste silence — c'est le signe que le volume_safety en amont a été insuffisant, pas
le job du closing de combler.

### Distinction grosse sous-idée vs petite

Pas de logique explicite. C'est le LLM qui adapte le ton selon le `prev_excerpt`
fourni (les ~200 derniers mots du bloc). S'il s'agit d'une grosse sous-idée pleinement
développée, le LLM produira un récap substantiel. Si c'est une petite section, il
produira une transition légère. Le **prompt cadre** demande explicitement *"PAS de
'Voilà pour cette partie' générique. Sois spécifique sur ce qui vient d'être vu."*

## Architecture du flux complet

```
generate_audio_from_script(folder_id, ...)
  │
  ├── 1. Charger les segments completed
  ├── 2. _build_course_blocs_from_segments(...)
  │     │
  │     ├── Passe 1 forward cascade (cap_w empêche l'overshoot)
  │     └── Passe 2 _redistribute_undershoot_backward (tire paragraphes)
  │
  ├── 3. _apply_closing_transitions(blocs, api_speed)   ← Passe 3 (LLM)
  │     │
  │     └── Pour chaque bloc dirty avec gap > 15s :
  │           closing = generate_closing(bloc_num, prev_excerpt, next_excerpt, gap_sec, is_last_bloc)
  │           bloc.text = bloc.text + "\n\n" + closing
  │
  └── 4. Pour chaque bloc dirty : _synthesize_course_audio_to_fit(bloc, ...)
                                  (un seul appel Fish Audio, audio prêt à uploader)
```

## Pourquoi pas de cache DB pour V1

Le closing dépend du contenu du bloc + du début du bloc suivant. Cache key naturelle :
`(folder_id, bloc_num, hash(prev_excerpt + next_excerpt + gap_bucket))`. Mais :
- Sur 52 jours × 7 blocs = 364 blocs, ~300 closings nécessitent du LLM (les autres
  sont des templates ou rien). Coût : ~600k tokens / RNCP, soit ~$2-5 sur Sonnet —
  **négligeable**.
- Une régénération est rare en pratique (un audio est régénéré seulement si dirty).
  Donc l'amortissement d'un cache est faible.
- Ajouter un cache impose une logique d'invalidation cross-blocs (modifier le bloc N
  invalide le closing du bloc N et du bloc N-1). Complexité non justifiée pour V1.

À reconsidérer si la facture LLM monte.

## Validation

### Smoke test backward redistribution

Cas testé : bloc 1 à 5000 mots (gap 17 min), bloc 2 à 8000 mots, paragraphes à
3000/5000/6500/8500/10000/13000.

- Avant : bloc 1 = 5000, gap 1034s
- Après : bloc 1 = 6500, gap 539s, bloc 2 = 6500
- Tirage stoppé car le paragraphe suivant (8500) ferait passer bloc 1 à 8500 mots,
  au-dessus du budget 7800.
- Les deux blocs marqués `dirty=True`.

Comportement attendu validé : on ne déborde pas le budget, on s'arrête sur des
paragraphes complets.

### Smoke test closing service

Cas testé : seuils et caps :
- Gap 10s → target 24 mots, registre "aucun" (silence padding)
- Gap 35s → target 84 mots, registre "court" (template)
- Gap 90s → target 218 mots, registre "moyen" (LLM)
- Gap 540s → target 700 mots cappé, registre "long" (LLM, cappé)

Fallback statique testé pour les 3 registres + conclusion bloc 7.

## Limites

### Calibration wpm partagée avec le cap budget

Le `_estimated_audio_seconds_for_words` utilise le même `192 × (speed/0.95)` que le
cap budget. Si la calibration empirique est off, l'undershoot sera mal estimé et la
redistribution backward + closing ne combleront pas le bon montant. **Risque R1** du
mémo `pipeline-52-jours-risques-residuels.md` — à valider avant prod.

### Le LLM peut générer un closing hors-ton

Si le prompt n'est pas assez serré, le LLM peut produire un closing qui sonne
artificiel. Atténué par : prompt strict, fallback statique sur erreur, et la passe 2
qui réduit déjà la quantité de closing nécessaire. Mais si on observe en prod des
closings "robotiques", il faudra renforcer le prompt avec des contre-exemples.

### Pas de prévisualisation du closing

Le closing n'est pas exposé à l'admin avant TTS. Il est inclus dans le texte envoyé
à Fish Audio puis uploaded en MP3. Pour debug : il faudrait logger le `closing_added`
+ `closing_words` dans le bloc dict (déjà fait). À terme, exposer dans le Word
généré pour relecture éditoriale.

## Bénéfices clés

- **Une seule génération TTS par bloc.** Pas de double appel Fish Audio coûteux.
- **Real content first, synthetic only as residual.** Maximise le contenu pédagogique
  réel avant de générer du synthétique.
- **Le cours porte sa propre clôture.** La pause peut rester un sas mental simple,
  pas besoin de la rendre dynamique. Architecture plus simple.
- **Adaptatif au gap.** Petit gap = petite phrase ; grand gap = vrai recap. Pas
  d'over- ni d'under-filling.

## Articulation avec les pauses dynamiques (rang priorité revu)

Avant ce mémo : les pauses dynamiques étaient priorisées comme prochaine itération
qualitative. Maintenant que le bloc cours porte sa propre clôture pédagogique
contextuelle, la pause peut rester générique sans gros impact.

Les pauses dynamiques restent **un nice-to-have** mais leur ROI est réduit : la
discontinuité auditive entre cours et pause est déjà beaucoup atténuée par le
closing. Cf. `03-decisions/transitions-pause-dynamiques.md` pour le design encore
valide, à reprendre si on veut polir l'expérience plus tard.

## Références code

- `backend/services/closing_transition_service.py` (nouveau, ~180 lignes) :
  - `generate_closing(bloc_num, prev_excerpt, next_excerpt, gap_sec, is_last_bloc)`
  - Templates `_SHORT_CLOSINGS`
  - Prompts `_build_medium_prompt`, `_build_long_prompt`, `_build_conclusion_prompt`
  - Constantes seuils `GAP_NEGLIGIBLE_SEC`, `GAP_SHORT_SEC`, `GAP_MEDIUM_SEC`,
    `MAX_CLOSING_WORDS`
- `backend/services/content_generation_service.py` :
  - `_estimated_audio_seconds_for_words` (helper)
  - `_redistribute_undershoot_backward` (passe 2)
  - `_apply_closing_transitions` (passe 3)
  - Wire dans `generate_audio_from_script` (étape 3.5)
- CHANGELOG 2026-04-30 : *"feat: blocs cours — redistribution backward + closing
  contextuel adaptatif"*

## Leçons / Pour le mémoire

- **Le silence n'est pas neutre, c'est une donnée pédagogique.** Concevoir un système
  audio sans une stratégie explicite sur les silences finaux = laisser un défaut
  perçu comme un bug.

- **Real content first, synthetic only as residual.** Principe transposable bien
  au-delà : avant d'inventer du contenu pour combler, voir si du contenu existant
  voisin peut être réorganisé. La redistribution déterministe coûte zéro et garde
  toute la valeur pédagogique.

- **L'adaptation du registre selon la quantité à produire est sous-utilisée.** Un
  même prompt LLM pour 30 mots ou 700 mots produit des résultats hétérogènes. Avoir
  3 prompts distincts (court/moyen/long) + conclusion de journée donne des outputs
  cohérents.

- **Cap absolu sur le synthétique.** Sans `MAX_CLOSING_WORDS`, un gap de 10 min
  produirait un closing de 1500 mots ridicule. Le cap absorbe les cas dégénérés
  (volume_safety défaillant en amont) sans casser la pédagogie.

- **Ne pas faire dépendre la pause de la pédagogie de fin de cours.** Le découplage
  cours-finit-proprement / pause-est-un-sas a simplifié toute l'architecture pause
  prévue. Décider quel fichier porte quelle responsabilité est un acte d'archi
  fondamental.

- **Le LLM peut adapter le registre selon le contexte si on l'aide.** En passant
  `prev_excerpt`, on permet au LLM de juger lui-même si c'est une grosse sous-idée
  ou pas, sans logique manuelle de classification. Fait confiance au modèle, mais
  cadre par le prompt.
