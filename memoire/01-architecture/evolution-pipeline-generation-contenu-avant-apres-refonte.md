# De la génération « slotée » à la pipeline auditable — Le Socrate (mai 2026)

> Analyse de l'évolution de la pipeline de génération de contenu, reconstruite à partir
> de l'historique Git et du code (état pré-refonte `2f39c22` vs état actuel `HEAD`).
> Objectif : comprendre **pourquoi** on est passé d'une génération directe/slotée à une
> pipeline auditable pilotée par un plan JSON, avec artefacts, reviews ciblées,
> calibration budget et slides *anchor-first*. Ce document ne juge pas le code ; il
> reconstitue la logique d'évolution du projet.

---

## Repère temporel

La bascule est nette et datée : **`d93dd02` « Add structured course generation pipeline »,
23 mai 2026 à 20 h 38**. Ce commit supprime ~7 000 lignes (prompts monolithiques, anciens
scripts) pour ~1 500 lignes de pipeline structurée. Tout ce qui précède (jusqu'au
21-23 mai) constitue « l'ancienne pipeline » ; l'arc `d93dd02 → 629cb48` (23 → 31 mai) en
construit la version structurée.

L'évolution s'est faite en **trois paliers**, pas deux :

1. **Mode « expansion » (historique)** — un prompt monolithique, 6 sous-parties +
   conclusion injectée au runtime, workflow de copier-coller manuel sur Claude web
   (~30-45 appels par formation).
2. **Ère « slots » (20-21 mai)** — alignement strict sur **7 créneaux audio horodatés**,
   budget calibré en amont, profils éditoriaux par créneau, génération API parallélisée.
   C'est le prédécesseur immédiat de la refonte.
3. **Pipeline structurée (23 mai →)** — **plan JSON maître**, génération par section,
   artefacts persistés, reviews ciblées en couches, slides *anchor-first*.

### Frontière des commits

| Commit | Date | Rôle |
|---|---|---|
| `033ef9c` | 20 mai 13:20 | budget bloc = budget total, fin du texte calibrée en amont |
| `9a979ab` | 21 mai 12:04 | Align daily generation with course audio slots |
| `eb3123e` | 21 mai 12:20 | Separate planned course preview from generated audio |
| `6396fc7` | 21 mai 12:26 | Add per-slot prompt briefs for course generation |
| `415a95b` | 21 mai 13:17 | Expand per-course slot prompt profiles |
| `dbd31f8` | 21 mai 13:28 | Parallelize course text generation by slot |
| `f0bb187` | 21 mai 15:04 | Fix : ThreadPoolExecutor → eventlet GreenPool |
| `2f39c22` | 21 mai 15:22 | Add restart-from-content step in pipeline UI **(dernier état ancien)** |
| **`d93dd02`** | **23 mai 20:38** | **Add structured course generation pipeline (REFONTE)** |
| `5ecc320` | 23 mai 21:24 | Modularize generation and review prompts |
| `8f3a0d7` | 23 mai 21:08 | Use structured plans in content reviews |
| `52d6b10` | 23 mai 23:57 | Persist structured pipeline artifacts |
| `c71691a` | 24 mai 00:22 | Add plan adherence quality review |
| `460bac0` | 24 mai 00:51 | Parallelize structured course generation |
| `2364973` | 30 mai 19:24 | Calibrage budget texte par section |
| `4c57232` | 31 mai 13:37 | Implement deck slide templates |
| `629cb48` | 31 mai 21:02 | Map slide source text from course blocks |

---

## Q1 — Comment la pipeline générait-elle les cours avant le 23 mai ?

À l'état `2f39c22`, le service `content_generation_service.py` fonctionnait ainsi
(1 dossier = 1 journée) :

- **Extraction de 7 créneaux** par un unique appel Claude (`extract_sub_parts`,
  `_EXTRACT_PROMPT`, `max_tokens=1500`) renvoyant `{title, sub_parts[7]}`. Les 7 créneaux
  et leurs durées sont **codés en dur** (45/45/55/45/60/60/50 min, `NUM_SUB_PARTS=7`).
  C'est la *seule* étape de structuration — pas de plan.
- **Génération par créneau × 3 passes** (`_generate_segment_text`) : Fondation → Pratique
  → Maîtrise. En mode `from_scratch`, chaque passe régénère depuis le `module_content`
  sans réutiliser la passe précédente ; `max_tokens=16000`, 3 retries avec backoff.
  ⇒ **21 segments** (7 créneaux × 3 passes).
- **Notion de slot** = profil éditorial figé par position (`_COURSE_SLOT_PROMPT_PROFILES`,
  dict `1..7` avec `label/moment/intention/rhythm/structure/avoid/handoff`). C'est une
  *direction artistique par position dans la journée*, injectée dans le prompt
  (`_build_course_slot_generation_context`, contenu prioritaire tronqué à 7000/9000
  caractères).
- **Budget mots** dérivé *a posteriori* de `PLAYLIST_SPEC` (`get_course_day_word_budget` :
  durée − 17 s silence début − 60 s silence fin, × **165,7 mots/min** × marge de sécurité),
  imposé **par passe** dans le texte du prompt, plus une boucle de continuation (max 2
  appels de +350 mots) si sous le seuil.
- **Parallélisation** par créneau via `eventlet.GreenPool` (workers défaut 7, plafond 7) —
  les 3 passes d'un même créneau restent séquentielles.
- **Découpage audio** : le texte des créneaux est concaténé puis **re-tranché
  linéairement** en 7 blocs (`_build_course_blocs_from_segments`, frontière proportionnelle
  à la durée + `_choose_natural_boundary` + `_redistribute_undershoot_backward` +
  `_handle_last_bloc_overflow`).
- **Review au niveau segment** : deux passes (humanisation #101-114, puis conformité
  #1-27) par **patches chirurgicaux** à match textuel unique (rejet si 0 ou ≥2
  occurrences), max 5 patches/appel, avec budget guard de rollback.
- **Sortie** : un **unique `.txt` concaténé** uploadé vers `CONTAINER_DOCUMENTS`. Aucun
  artefact JSON intermédiaire.

## Q2 — Quelle était la structure du contenu généré ?

**Persistance** :

- `content_generation_jobs` (1/journée) : `folder_id`, `sub_parts` (JSON, liste de 7 noms),
  `module_contents`, `from_scratch`, `status`, `current_sub_part`, `current_passe`,
  `total_words`…
- `content_generation_segments` (21 lignes) : `text_content`, `word_count`, flags
  `reviewed`/`humanized` + signatures, snapshot `text_content_pre_review`. Marqueur
  `<<<BLOC_AUDIO_N>>>` préfixant le texte après calibration bloc.

**Sortie modèle** : un **flux oral continu** unique avec tags Fish Audio inline
(`[pause]`, `[emphasis]`…) — **pas de JSON, pas de sections balisées, pas de métadonnées,
pas de slides, pas d'horaires structurés**. La seule trace structurale était la liste des
7 noms de créneaux.

## Q3 — Gros prompt, slots, blocs, ou déjà un plan ?

**Un gros prompt direct + des slots, sans plan.** Précisément :

- **Gros prompt** : `prompt-generation-tts-direct.md` (~1164 lignes),
  `prompt-generation-tts-scratch.md` (~2938 lignes). Un seul appel devait porter
  *simultanément* le paradigme pédagogique, un plan en 11 points, le style oral, les tags
  Fish Audio, le budget mots (table 165,7 mots/min, ex. 60 min ≈ 9940 mots) et **26-27
  règles** éthiques/anti-hallucination/anti-dérive — **recopiées intégralement aux 3
  passes** (stratégie « sandwich » contre le *lost-in-the-middle*).
- **Slots** = unité d'orchestration (7 créneaux × 3 passes), mais le slot était une
  *position fixe*, pas une donnée de plan.
- **Blocs audio** = construits *après coup* par re-découpe linéaire, donc **la frontière de
  bloc ne coïncidait pas avec la frontière de créneau généré**.
- **Plan** : **absent**. Aucun plan JSON, aucun contrat de structure persisté.

## Q4 — Problèmes de cette ancienne approche

| Symptôme du brief | Mécanisme précis (ancienne pipeline) |
|---|---|
| **Dérive pédagogique** | Cours TTS longs sans architecture imposée ; profil de slot à cheval sur deux blocs audio ; intros régénérées « à l'aveugle » en `from_scratch` ⇒ doublon d'intro (intro journée répétée au 1er thème), fuite d'abstraction (horaires/blocs verbalisés), contenu après la conclusion. Aucune vérification de doublon inter-créneaux. |
| **Manque de traçabilité** | Sortie = 1 `.txt` concaténé, aucun artefact JSON intermédiaire ; review persistée seulement en snapshot `text_content_pre_review`. Impossible d'auditer *pourquoi* un bloc fait telle longueur ou *quel* patch a été appliqué sans relire les logs. |
| **Budgets audio difficiles** | Budget imposé à **3 endroits** avec des ratios distincts (génération réserve 0,97 ; calibration bloc ; audit jour), porté par le *texte* du prompt (auto-limitation du LLM), **sans garde-fou programmatique**. Double-correction possible ; la calibration bloc **invalidait la conformité** (`reviewed=0`) car elle modifiait le texte après review. |
| **Slides incohérentes** | *(baseline inférée — `script_slide_generation_service` existait déjà à `2f39c22` mais **sans** `_extract_slide_anchors_from_plan`)* : slides extraites du `.txt` concaténé final par *text-mining libre*, sans plan ni catalogue verrouillé, sans lien vérifiable au passage source. |
| **Reviews trop globales** | Une review mêlant structure + éthique + oralité ; patches souvent **rejetés silencieusement** (paraphrase ⇒ 0 match) ; un correctif d'oralité pouvait casser la structure ; couverture limitée par le plafond de 5 patches/chunk. |
| **Répétitions** | Boucle de continuation (raccord visible) + 3 passes régénérant la journée sans coordination inter-créneaux. |
| **Erreurs détectées trop tard** | Conformité/humanisation vérifiées seulement au *gate* `launch-audio` ; un problème de contenu n'apparaissait qu'après génération du texte **et** des passes review aval — souvent à l'oreille, après TTS. Status global opaque. |

Limites « méta » notables pour le mémoire :

- **Duplication non maintenable** : les 26 règles recopiées 3× et entre `direct.md` /
  `scratch.md`, qui avaient déjà **divergé** (`scratch.md` portait une règle #27 absente de
  `direct.md`).
- **Contradiction interne** explicite : Passe 2 « cite des entreprises réelles avec leur
  nom » (`direct.md:938`) vs règle #18 « si doute → fictif » (`direct.md:560-568`).
- **Fausse parallélisation** : `ThreadPoolExecutor` sérialisé silencieusement par le
  monkey-patching eventlet, corrigé en `GreenPool` (`f0bb187`).
- **Process manuel** initial : copier-coller des passes sur Claude web (placeholders
  `{COLLER_LE_TEXTE_DE_LA_PASSE_1}`…), ~30-45 appels par formation, sans trace.

## Q5 — Améliorations apportées par la pipeline structurée

L'arc `d93dd02 → 629cb48` pose les briques d'une **pipeline auditable pilotée par un plan
JSON maître** :

1. **Plan JSON verrouillé à 4 couches** (`structured-course-plan-v2`) :
   **jour → 7 cours → sections (`opening` / `parts`[2-4] / `conclusions`) →
   `teaching_beats`** (typés : concept, définition, méthode, exemple, piège…, chacun avec
   un `slide_anchor`). Le plan devient le *contrat pédagogique*.
2. **Génération par section isolée** (`structured-section`) avec `scope_guard` et budget
   propre, au lieu de re-découper du texte. **1 section = 1 unité native** ⇒ frontières
   pédagogiques nettes.
3. **Autorité serveur sur les budgets** : `_normalize_structured_course_plans` écrase les
   budgets proposés par le LLM ; `validators.py` **rejette** le plan si Σ(budgets sections)
   ≠ `target_words` du cours. Cohérence mathématique garantie. *(Au niveau cours, dépasser
   `target_words` = statut `too_long` — pas de tolérance +10 % ; seuils min : section 0,94
   / bloc 0,97 / cours 0,95. La plage 0,82/1,10 n'est qu'une instruction de prompt pour une
   section.)*
4. **Stratégie `parallel_body_then_late_opening`** : corps des 7 cours en parallèle,
   **puis** résumés, **puis** intros *tardives* recevant `course_summaries[n-1]`, et
   `day_conclusion` tardive avec le `day_summary_context`. ⇒ raccords fondés sur le contenu
   *réel*, fin du double accueil. `scope_guard` anti-fuite + vocabulaire learner-facing
   interdit (`bloc`, `créneau`, `horaire`, `planning`).
5. **Prompts modularisés** : l'ancien monolithe éclaté en `base-course-style` (socle
   mutualisé) + `structured-plan` (contrat plan) + `structured-section` (contrat section) +
   `budget-rewrite` (réécriture budget).
6. **Reviews ciblées en couches** *(≈ 5 étapes à l'exécution : les 4 couches historiques
   réinterprétées + 1 ajoutée)* — ordre figé :
   **plan-adherence** (avant budget) → **budget-rewrite** → **micro-conformité éthique**
   (#1-16, après budget) + scan lexical déterministe (`ethical-lexical-terms.json`) →
   **humanisation** *polish-only* (v9, ne restructure plus) → **conformité finale**
   (5 règles : #14, #15, #17, #18, #22). Chaque passe corrige *une* chose sur le texte que
   la suivante recevra.
7. **10 artefacts JSON persistés** (`content-plan`, `draft-sections`, `quality-reviews`,
   `budget-calibration`, `ethical-micro-review`, `course-scripts`, `reviewed-scripts`,
   `audio-plan`, `script-plan`…), enveloppés par `artifact_payload` avec
   `formation_job_id` / `content_job_id` / `folder_id`.
8. **Slides *anchor-first*** : `teaching_beat → slide_anchor` décidé **au plan**,
   `template_type` choisi dans un **catalogue fermé**, slide tracée mot-pour-mot au passage
   source (`source_quote` + offsets `highlight_word_start/end`), slides sans
   `slide_anchor_id` **supprimées**, trous comblés par *context slides*. Décodage audio
   découplé (`d829260`).
9. **Auditabilité UI** : *roadmap* d'étapes cliquables, modales exposant artefacts +
   **diffs avant/après**, persistance DB d'événements (`formation_pipeline_events`,
   `content_review_reports`), `EventDetailModal` montrant l'étape / le modèle / le folder,
   traçabilité par IDs explicites.
10. **Parallélisation propre** : `GreenPool` natif + gate de concurrence client
    (`ANTHROPIC_MAX_CONCURRENT`) + retries 429 typés (`460bac0`, `835a357`).

## Q6 — Tableau comparatif

| # | Ancienne pipeline | Problème | Nouvelle solution (structurée) | Bénéfice | Métrique possible |
|---|---|---|---|---|---|
| 1 | Texte généré par 7 créneaux × 3 passes, puis **re-découpe linéaire** en 7 blocs (frontière bloc ≠ frontière créneau) | Profil/handoff de créneau à cheval sur 2 blocs ; texte de bloc non autonome | Génération **par section isolée** depuis le plan JSON, assemblage sans re-découpe | Chaque bloc audio = unité native, frontières pédagogiques nettes | Taux de blocs dont l'intro/outro est tronquée (≈ aléatoire → ~0) |
| 2 | Budget imposé à **3 endroits** (ratios distincts), porté par le texte du prompt, sans contrôle programmatique | Triple correction incohérente, calibration bloc invalide la conformité | **Budgets serveur font autorité**, validés par Σ(sections)=`target_words`, calibrage par section | Cohérence mathématique plan↔audio ; ordre figé, plus de re-run conformité | Taux de cours/sections hors-budget (`too_short`/`too_long`) ; points d'imposition 3→1 |
| 3 | Slides extraites du `.txt` concaténé (*text-mining* libre) | Slides « libres », non tracées au passage source (hallucination visuelle) | **Anchor-first** : `teaching_beat→slide_anchor` au plan, template catalogue fermé, `source_quote`+offsets | Deck 100 % piloté par le plan, traçabilité slide→extrait | % de slides traçables à un passage source exact (cible 100 % anchor+context) |
| 4 | 2 passes review **globales** au niveau segment, patches à match unique (rejet silencieux) | Mélange structure/éthique/oralité ; couverture partielle ; correctif casse la structure | **5 passes ciblées ordonnées** + scan lexical déterministe (~250 termes) | Chaque passe corrige une chose ; réécriture contextuelle au lieu de suppression | Nb de dimensions (1→5) ; taux de patches rejetés par ambiguïté ; couverture lexicale |
| 5 | **Aucun artefact** intermédiaire ; 1 `.txt` + 21 segments DB | Audit impossible sans relire texte/logs | **10 artefacts JSON** par étape + diffs avant/après, IDs explicites | Chaîne de preuves bout-en-bout, diffs consultables | Nb d'artefacts auditables/journée (1→10) ; profondeur de traçabilité |
| 6 | Intros régénérées « à l'aveugle » (`from_scratch`), 3 passes non coordonnées | **Doublon d'intro**, fuite d'abstraction (horaires/blocs), cours N qui finit N-1 | `parallel_body_then_late_opening` (intros tardives + `summaries[n-1]`) + `scope_guard` | Raccords cohérents, fin du double accueil, vocabulaire interne masqué | Taux de répétition inter-sections (cosinus/n-grammes) ; occurrences de `bloc/horaire` côté apprenant (→0) |
| 7 | `ThreadPoolExecutor` **sérialisé** par eventlet | Fausse parallélisation non détectée, latence cumulée | `GreenPool` natif + gate concurrence + retries 429 (workers 3, plafond 7) | 7 cours générés réellement en parallèle | Temps de génération journée (séquentiel → ~⌈7/3⌉ lots) ; appels concurrents réels |
| 8 | Conformité vérifiée seulement au *gate* `launch-audio` | **Erreurs vues trop tard** (après TTS / relecture) | Observabilité **par étape** (events DB + `EventDetailModal` + diagnostic) | Erreur vue là où elle survient, corrélable log↔artefact↔UI | Délai de détection (après TTS → temps réel) ; granularité status (1 global → 16 étapes) |
| 9 | Cours longs sans architecture visible (exemples avant cadrage, contenu après conclusion) | **Dérive pédagogique**, conclusion cassée, pas d'audit de couverture | Plan JSON verrouillé + review **plan-adherence** (ordre, double intro, contenu post-Q/R) | Architecture imposée et auditée *avant* le budget | Nb d'issues d'adhérence détectées/corrigées par cours (`content-quality-reviews.json`) |

---

## ⚠️ Honnêteté méthodologique (à mentionner dans le mémoire)

- Les chiffres du code (**3 workers, 7 cours, 165,7 mots/min, silences 17 s/60 s, ratios
  0,94/0,97/0,95**) sont des **paramètres**, pas des mesures de résultat. Les métriques de
  la colonne 6 sont **« à mesurer en prod »**, pas mesurées dans le repo. À étiqueter comme
  telles.
- La fiabilité de l'**audio final** n'est pas démontrée dans le code : la conversion
  mots→secondes à 165,7 mots/min est une *approximation linéaire à valider* (commentaire
  `R1` dans le service).
- La **baseline « slides incohérentes »** (ligne 3 du tableau) est **partiellement
  inférée** : `script_slide_generation_service` existait à `2f39c22` mais sans extraction
  d'ancres ni `source_quote`. Le contraste pertinent est *text-mining libre* →
  *anchor-first ancré au plan* (et non « audio couplé → découplé », qui est un changement
  *intra*-nouvelle-pipeline).
- Le **coût API** (« ~13,50 $ / formation » cité côté ancien workflow manuel) n'a pas été
  recoupé par un calcul de tokens réel ; le surcoût de la parallélisation (7 cours × N
  sections × 5 passes) n'est pas chiffré — mais le principe **« 1 RNCP = 1 module
  durable »** (CLAUDE.md) justifie d'amortir ce coût sur toutes les promos.
- La rigidité **« 7 cours/jour »** subsiste : `validators.py` force `expected_courses=7`
  (`range(1,8)`) — un REAC à structure différente sortirait du cadre validé. Angle à
  signaler.

---

## Annexe — Structures de données clés

### Ancienne pipeline (`2f39c22`)

- `content_generation_jobs` : `folder_id, platform_id, program_text, sub_parts (JSON 7
  noms), from_scratch, module_contents, status, current_sub_part, current_passe,
  total_words, formation_job_id, nb_days…`
- `content_generation_segments` (21) : `job_id, sub_part_index, passe (1/2/3), status,
  text_content, word_count, dirty, humanized/humanization_signature,
  reviewed/review_signature, text_content_pre_review`.
- `_COURSE_SLOT_PROMPT_PROFILES` : `{1..7 : {label, moment, intention, rhythm, structure[],
  examples, avoid[], handoff}}`.
- `budget` (dérivé playlist) : `{target_words, min_words, max_words,
  words_per_minute=165.7, course_seconds, speakable_seconds, start_silence_sec=17,
  final_silence_sec=60}`.
- `bloc audio` (à la volée, non persisté comme plan) : `{bloc_number 1..7, text, start_w,
  end_w, word_count, contributing_seg_indices, target_sec, word_budget, filename, role,
  next_item_type}`.
- `patch review` (transient) : `{original (3-40 mots verbatim), replacement, rule_violated
  '#N', reason, review_group}` — max 5/appel, appliqué si match unique.

### Nouvelle pipeline (`HEAD`) — le plan JSON à 4 couches

- **Racine** (`structured-course-plan-v2`) : `{version, generated_at, title, folder_id,
  day_number, nb_days, is_last_day, courses:[7]}`.
- **Couche 2 — cours/bloc** : `{course_number(1-7), course_title, filename,
  duration_minutes, target_words (=budget bloc audio), pedagogical_role, course_kind,
  learning_objectives[], opening{}, parts:[2-4], course_conclusion{}, day_conclusion{|null
  cours 7}, global_constraints{}}`.
- **Couche 3 — section** : `opening{type, target_words, must_include[], must_avoid[],
  teaching_beats[]}` ; `part{part_number, title, target_words, function, must_include[],
  must_avoid[], teaching_beats[], transition_in, transition_out}` ; `course_conclusion{…}`
  ; `day_conclusion{…}`.
- **Couche 4 — teaching_beat + slide_anchor** : `{beat_id, type
  (concept|definition|process|method|example|comparison|warning|tip|story|analogy|data|recap|opinion),
  role, spoken_requirement, slide_anchor:{enabled, anchor_id, template_type, visual_goal,
  items_expected, fields_hint}}`.
- **`global_constraints`** : `{parts_min:2, parts_max:4,
  learner_facing_forbidden_words:['bloc','créneau','horaire','planning'],
  learner_facing_preferred_units:['thème','partie','chapitre','séquence','axe'],
  examples_policy, schedule_policy}`.
- **slide finale** : `{slide_id, template_type, event_type, slide_anchor_id, beat_id,
  slide_kind:'anchor|generated|context', data:{…}, source_text, source_quote,
  source_ref:{source_block_id, word_start, word_end, highlight_word_start/end…},
  importance}`.

---

## Sources pour citation

- **Ancien service** : `git show 2f39c22:backend/services/content_generation_service.py`
  — extraction `3864-3905`, slots `474-666`, budget `228-321`, re-découpe `2714-2845`,
  review `7163-7330`, calibration bloc `3233-3354`.
- **Anciens prompts** : `git show 2f39c22:backend/prompts/prompt-generation-tts-direct.md`
  (table budget `373-382`, règles `388-866`, sortie `889-905`).
- **Nouveau service** : `backend/services/content_generation_service.py` — plan
  `1457-1562`, ordre pipeline `8333-8761`, budgets `1764-1775`, conformité finale
  `11938-11957` + `13002-13007`.
- **Modules pipeline** : `backend/services/content_pipeline/{validators,artifacts,calibration}.py`.
- **Prompts modulaires** : `backend/prompts/{generation,reviews,slides}/`.
- **Notes mémoire cohérentes** : `pipeline-contenu-plan-json-4-couches.md`,
  `slides-json-maitre-anchor-first.md`,
  `fuite-abstraction-cours-horaires-script-oral.md`,
  `micro-conformite-ethique-locale.md`,
  `generation-structuree-intros-tardives-parallelisees.md`,
  `modales-audit-pipeline-artefacts-diffs.md`.
