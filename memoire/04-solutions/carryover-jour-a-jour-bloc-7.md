# Carryover bloc 7 → folder suivant (+ rebalancing LLM du dernier jour)

**Date** : 2026-04-30
**Thématique** : solution technique
**Statut** : implémenté
**Mémos connexes** :
- `04-solutions/decoupage-blocs-cap-budget-cascade.md` (cap forward)
- `04-solutions/closing-bloc-cours-contextuel.md` (closing)
- `02-problemes/coupure-audio-tts-pleine-phrase.md` (problème mère)

---

## Contexte

Avec le cap budget cascade, les blocs 1 à 6 ne peuvent jamais déborder leur budget
TTS — le surplus est cascadé au bloc suivant. Mais le **bloc 7 n'a personne
après lui** dans la journée : il absorbe tout le résidu de la cascade. S'il
déborde son propre budget, le pré-check Fish Audio rejette et la pipeline
s'arrête.

Le mémo connexe `decoupage-blocs-cap-budget-cascade.md` notait cela comme limite
résiduelle ("Si bloc 7 dépasse, c'est un problème de volume_safety amont"). Ce
mémo documente la solution adoptée pour ne pas faire planter la pipeline dans
ce cas.

## Problème

### Symptôme

Sur un total mots/jour légèrement excessif (ex. 64 000 mots au lieu des 60 000
ciblés), tous les blocs 1-6 remplissent leur budget, et bloc 7 hérite du surplus
(~3 000-4 000 mots de trop). Pré-check rejette → `auto_pilot_error` →
intervention manuelle requise.

Sur 52 jours × probabilité non-nulle, ce cas arriverait quelques fois par
formation et bloquerait la pipeline en plein milieu.

### Pourquoi le pur "volume_safety amont" ne suffit pas

`volume_safety` vise une cible de 60k mots/jour comme **plancher** (au moins X
mots), pas comme **plafond**. Sur certaines journées particulièrement riches en
contenu, le LLM peut générer 64-65k mots si les sous-parties sont denses. Le
volume_safety trouve ça acceptable (≥ plancher), mais le découpage TTS lui le
trouvera trop.

Idéalement on ajouterait un check plafond à `volume_safety`. Mais ça déplace le
problème côté génération sans le résoudre côté audio. Mieux : avoir une
**stratégie de débord** côté pipeline audio.

## Solution

### Idée centrale

Si bloc 7 du jour N déborde, on **reporte les paragraphes excédentaires vers le
jour N+1**. Le contenu n'est ni perdu ni résumé : il est joué le lendemain (ou
au cours suivant). L'intro du jour N+1 mentionne explicitement la reprise.

Si on est sur le **dernier jour** (pas de N+1), on **remanie le bloc 7 par LLM**
pour le condenser à 90 % du budget — sans ajouter d'idées, sans changer la
substance, juste en fusionnant les redites et exemples redondants.

### Architecture

**1. Stockage en DB.**

Migration sur `content_generation_jobs` (mémo connexe : utilise les jobs et non
les folders, parce qu'un job est associé à un folder mais porte aussi le statut
de génération). Quatre colonnes ajoutées :

```sql
carryover_out_text TEXT DEFAULT ''      -- côté SOURCE : texte exporté
carryover_out_target_folder_id INTEGER  -- côté SOURCE : vers quel folder
carryover_in_text TEXT DEFAULT ''       -- côté CIBLE : texte importé (avec intro)
carryover_in_source_folder_id INTEGER   -- côté CIBLE : depuis quel folder
```

L'écriture est **bilatérale** : `_store_cross_day_carryover(source_id, target_id, text)`
écrit les deux côtés en une transaction. La cible reçoit déjà l'intro fixe
préfixée via `_format_carryover_for_next_course()`.

**2. Génération du carryover (côté SOURCE).**

`_handle_last_bloc_overflow(blocs, ...)` est appelé après la passe 2 (backward
redistribution). Si le bloc 7 dépasse son `word_budget` :

- Cherche la **dernière fin de paragraphe sous le cap** via `_choose_natural_boundary`
  (le plus tardive possible pour minimiser le carryover).
- Tronque le bloc 7 à cette position.
- Le texte au-delà devient `carryover_text`.
- Si `next_folder_id` existe : `_store_cross_day_carryover(...)` écrit la DB.
- Sinon (dernier jour) : appel à `_reduce_last_bloc_to_budget(bloc, model)`.

**3. Application du carryover (côté CIBLE).**

Au début de `generate_audio_from_script` du folder cible :

```python
carryover_in = (job.get("carryover_in_text") or "").strip()
if carryover_in and segments:
    segments[0]["text"] = carryover_in + "\n\n" + segments[0]["text"]
    segments[0]["dirty"] = True
```

Le segment 0 du folder cible est préfixé par le carryover entrant (intro + texte
reporté). Marqué `dirty=True` pour forcer la régénération du bloc 1 audio.

**4. Intro fixe — règle "au cours dernier".**

```python
_CARRYOVER_INTRO = (
    "Avant d'entrer dans la suite de ce cours, on reprend le point que nous "
    "n'avons pas terminé au cours dernier. On le pose proprement, puis on "
    "enchaînera naturellement avec le programme prévu."
)
```

Choix éditorial **important** : on ne dit **jamais** "hier".

Raison : la formation peut être suivie sur des jours non-consécutifs (week-end,
absence apprenant, planning irrégulier de l'entreprise). "Hier" serait faux
dans ces cas. "Au cours dernier" reste valable quel que soit l'écart temporel.

**5. Rebalancing LLM du dernier jour.**

`_reduce_last_bloc_to_budget(bloc, model)` envoie le texte du bloc 7 au LLM avec
ce prompt (extrait) :

> "Tu es un formateur expert. Tu dois REMANIER le dernier bloc d'un cours audio
> pour qu'il tienne dans son créneau TTS, sans jouer sur la vitesse de la voix.
>
> OBJECTIF :
> - Réduis le texte à environ {target_words} mots.
> - Ne supprime pas l'idée générale : condense, fusionne les exemples redondants,
>   garde les notions utiles.
> - N'ajoute AUCUNE nouvelle idée.
> - Ne dis jamais "hier". Si tu fais référence à la séance précédente, dis
>   "au cours dernier".
> - Termine par une vraie conclusion de cours.
> - Texte oral fluide, naturel, prêt pour TTS."

`target_words = max(800, int(budget * 0.90))` — vise ~90 % du budget pour
absorber les écarts de calibration TTS résiduels.

Refus si le résultat dépasse encore (ValueError) : signal qu'il y a vraiment
trop de contenu et que volume_safety en amont devra être renforcé.

## Hiérarchie complète des fallbacks (vue d'ensemble)

```
Génération texte (LLM)
        │
        ▼
Volume_safety (cible 60k mots/jour)
        │
        ▼
_build_course_blocs_from_segments :
  ├─ Passe 1 : forward cascade (cap_w empêche overshoot bloc 1..6)
  ├─ Passe 2 : backward redistribution (paragraphes complets si undershoot)
  └─ Passe 3 : _handle_last_bloc_overflow (bloc 7)
        ├─ Cas "next_folder existe" → carryover vers J+1
        └─ Cas "dernier folder" → _reduce_last_bloc_to_budget (LLM)
        │
        ▼
_apply_closing_transitions (gap résiduel sur blocs dirty)
        │
        ▼
TTS Fish Audio (1 appel par bloc)
```

## Idempotence et cas limites

### Re-run du folder source

Si on relance `generate_audio_from_script(folder_id_N)`, le `_handle_last_bloc_overflow`
recalcule le découpage. Trois cas :
- **Plus de débord** : `_clear_cross_day_carryover_from_source(source_folder_id)`
  vide le report stocké, et nettoie aussi côté cible (`carryover_in_text=''`).
- **Toujours débord, même contenu** : écrase le report avec un texte identique
  → nullop sur la cible.
- **Toujours débord, contenu différent** : écrase le report avec le nouveau
  contenu → la cible appliquera le nouveau au prochain run.

### Re-run du folder cible alors que le report a déjà été appliqué

C'est le cas non-idempotent restant. La cible lit `carryover_in_text` à chaque
run et le préfixe à `segments[0]`. Si le folder cible a déjà tourné une fois :
- Run 1 : `segments[0].text` réécrit avec carryover. **Ne persiste pas en DB**
  car les segments en DB ne sont pas modifiés (on travaille sur la liste en mémoire).
- Run 2 : la DB a toujours le texte original sans carryover, on le re-préfixe.

Donc en pratique, **le carryover est appliqué à chaque run du folder cible**,
mais comme on lit `segments[0].text` depuis la DB à chaque fois, on n'accumule
pas. ✅

### Cas pathologique : aucune fin de paragraphe sous le cap

Si bloc 7 contient un seul énorme paragraphe > budget, `_handle_last_bloc_overflow`
fallback sur fin de phrase. Si même ça n'existe pas, la fonction laisse le bloc
intact (le pré-check Fish Audio rejettera). Très rare en pratique.

## Bénéfices

- **Aucune information pédagogique perdue** : le contenu reporté est joué le
  lendemain, intégralement.
- **Pas de coupure brutale en pleine phrase** côté audio.
- **Pas de pipeline qui s'arrête sur un débord modéré** : la formation tient,
  même si le volume_safety amont n'a pas été parfaitement calibré.
- **Le LLM intervient seulement quand inévitable** (dernier jour) : 1 appel
  potentiel par RNCP, négligeable en coût.

## Limites

### Effet domino

Si jour N déborde, le report cascade au jour N+1. Si jour N+1 déborde aussi
(volume excessif + carryover entrant), il cascade au jour N+2. La probabilité
d'un débord cumulatif sur le dernier jour augmente avec la taille de la cascade.
Le rebalancing LLM final attrape ce cas mais c'est moins propre qu'un
volume_safety bien calibré en amont.

### Le carryover entrant alourdit le bloc 1

L'apprenant entend les premières minutes du jour N+1 sur du contenu reporté de
J. Si le report fait 2 minutes, le contenu "neuf" du jour N+1 démarre à 19h02
au lieu de 19h00 (effectivement). Sur la durée totale (45 min de bloc 1), c'est
4-5 % de pédagogie déplacée. Acceptable.

### Pas d'option "résumé du carryover"

On reporte le texte verbatim. Si le carryover fait 3 000 mots, c'est 3 000 mots
qui occupent le bloc 1 du jour suivant. On pourrait imaginer un mode "résumé du
carryover" via LLM (style "récap de ce qu'on n'a pas eu le temps de voir"), mais
ça réintroduit du LLM réactif et risque de perdre de la précision pédagogique.
Choix V1 : verbatim.

## Coordination avec les autres passes

| Passe | Cible | Effet sur carryover |
|---|---|---|
| Forward cascade (cap_w) | Bloc 1..6 | Garantit que seul bloc 7 peut déborder |
| Backward redistribution | Bloc 1..6 | Tire des paragraphes du **bloc 7** vers bloc 6 → réduit la pression sur bloc 7 → moins de carryover |
| `_handle_last_bloc_overflow` | Bloc 7 | Crée le carryover ou réduit par LLM |
| Closing contextuel | Tous dirty | Comble le gap résiduel après tronquation bloc 7 |

La passe 2 (backward redistribution) **réduit indirectement** la fréquence des
carryover : en aspirant des paragraphes du bloc 7 vers le bloc 6 quand bloc 6
est sous-rempli, on désengorge bloc 7 avant le check overflow.

## Références code

- `backend/database/db.py` : migration des 4 colonnes carryover sur
  `content_generation_jobs` (~ligne 357)
- `backend/services/content_generation_service.py` :
  - `_CARRYOVER_INTRO` (constante, ~ligne 38)
  - `_format_carryover_for_next_course` (~ligne 132)
  - `_find_next_folder_id` (~ligne 140)
  - `_store_cross_day_carryover` (~ligne 168)
  - `_clear_cross_day_carryover_from_source` (~ligne 195)
  - `_reduce_last_bloc_to_budget` (~ligne 232)
  - `_handle_last_bloc_overflow` (~ligne 602)
  - Application du carryover entrant dans `generate_audio_from_script` (~ligne 1505)
- CHANGELOG 2026-04-30 : *"feat: carryover bloc 7 → folder suivant"*

## Leçons / Pour le mémoire

- **Une cascade J→J+1 réduit la pression sur les contraintes de chaque jour.**
  Sans elle, chaque jour doit être parfaitement calibré. Avec elle, les écarts
  de volume du LLM (jour riche vs jour pauvre) s'amortissent naturellement.

- **L'éditorial fait partie de l'architecture.** Le choix de "au cours dernier"
  vs "hier" n'est pas cosmétique : il rend le système robuste aux usages
  réels (formations non-quotidiennes, week-ends, absences). Capturer ce détail
  dans une constante (`_CARRYOVER_INTRO`) plutôt qu'un literal in-line est
  important.

- **Le LLM-shortening est légitime quand c'est le dernier recours.** On l'a
  rejeté pour les blocs 1-6 (cap budget cascade fait mieux), mais pour le
  dernier bloc du dernier jour, il n'y a pas d'alternative déterministe — le
  LLM est la bonne fit. Reconnaître quand l'inverse est vrai évite le dogmatisme
  ("toujours déterministe" vs "toujours LLM").

- **Les invariants éditoriaux remontent dans le prompt.** Le prompt de
  `_reduce_last_bloc_to_budget` réinstaure explicitement la règle "ne dis jamais
  hier". Sinon le LLM glisse vers le langage naturel et casse l'invariant.
  Toujours **rappeler les contraintes pédagogiques au LLM**, même quand on
  pense que c'est évident.

- **Idempotence partielle est souvent acceptable.** L'application du carryover
  côté cible n'est pas strictement idempotente entre runs, mais le fait que la
  DB des segments n'évolue pas évite l'accumulation. Connaître le périmètre
  exact de la non-idempotence permet d'évaluer si c'est un problème ou non.
