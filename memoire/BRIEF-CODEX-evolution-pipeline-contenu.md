# BRIEF CODEX — Évolution de la pipeline de génération de contenu (Le Socrate)

> **À l'attention de Codex.** Ce document est une passation. Il répond aux ordres
> d'analyse que tu as émis (état de la pipeline de génération de contenu **au 22 mai 2026
> et avant**, vs la refonte structurée du 23-24 mai). L'investigation Git + code est
> **déjà faite et vérifiée** (12 agents de lecture sur l'état `2f39c22` et `HEAD`, plus une
> passe critique de vérification). Utilise les faits ci-dessous comme **vérité de terrain**.

---

## 1. Comment agir (instructions pour Codex)

**Objectif** : rédiger une partie de **mémoire d'ingénieur** qui reconstruit la *logique
d'évolution* de la pipeline. Le but n'est **pas** de juger le code, mais d'expliquer
**pourquoi** on est passé d'une génération directe/slotée à une pipeline auditable (plan
JSON, artefacts, reviews ciblées, calibration budget, slides *anchor-first*).

**Règles à respecter impérativement :**

1. **Lecture seule du code.** Ne modifie aucun fichier source. L'analyse est terminée ;
   ta tâche est rédactionnelle.
2. **Langue** : français, accents complets (jamais d'ASCII dégradé).
3. **Distingue 3 niveaux d'affirmation** (déjà étiquetés plus bas) :
   - ✅ **Vérifié** (référence `fichier:ligne` ou SHA) → tu peux l'affirmer.
   - ❓ **Inféré** (baseline slides anciennes) → formule au conditionnel / signale-le.
   - 📏 **Paramètre, pas métrique** (165,7 mots/min, 3 workers, ratios…) → ne le présente
     **jamais** comme un résultat mesuré ; étiquette « cible / à mesurer en prod ».
4. **Ne réintroduis pas les erreurs corrigées** (cf. §6) :
   - Il y a **5 passes de review** à l'exécution, *pas 4*.
   - La version courante du plan est **`structured-course-plan-v2`** (v1 = 23 mai).
   - Au niveau **cours**, dépasser `target_words` = statut `too_long` (**pas** de
     tolérance +10 %). La plage 0,82/1,10 n'est qu'une instruction de prompt par section.
   - Le découplage slide↔audio est un changement *intra*-nouvelle-pipeline, **pas** le
     contraste ancien↔nouveau (le vrai contraste = *text-mining libre* → *anchor-first*).
5. **Cite les sources** fournies au §7 (le jury attend des références traçables).
6. **N'invente aucun chiffre.** Si une donnée manque, signale-le.
7. **Cadre directeur** : « 1 RNCP = 1 module durable » (cf. `CLAUDE.md`) — la pipeline
   tourne **une fois par RNCP**, le coût est amorti sur toutes les promos. C'est ce qui
   justifie de payer la qualité/concurrence.

**Plan de section suggéré** : (1) repère temporel → (2) ancienne pipeline = gros prompt +
slots, sans plan → (3) problèmes → (4) refonte structurée → (5) tableau comparatif →
(6) limites/honnêteté méthodologique. Le matériau ci-dessous suit cet ordre.

---

## 2. Repère temporel

Bascule nette et datée : **`d93dd02` « Add structured course generation pipeline »,
23 mai 2026 à 20 h 38** (supprime ~7 000 lignes, ajoute ~1 500). Trois paliers :

1. **Mode « expansion » (historique)** — prompt monolithique, 6 sous-parties + conclusion
   runtime, copier-coller manuel sur Claude web (~30-45 appels/formation).
2. **Ère « slots » (20-21 mai)** — 7 créneaux audio horodatés, budget calibré amont,
   profils éditoriaux par créneau, génération API parallélisée. **Prédécesseur immédiat.**
3. **Pipeline structurée (23 mai →)** — plan JSON maître, génération par section,
   artefacts persistés, reviews ciblées, slides *anchor-first*.

| Commit | Date | Rôle |
|---|---|---|
| `033ef9c` | 20 mai 13:20 | budget bloc = budget total, fin calibrée en amont |
| `9a979ab` | 21 mai 12:04 | Align daily generation with course audio slots |
| `eb3123e` | 21 mai 12:20 | Separate planned course preview from generated audio |
| `6396fc7` | 21 mai 12:26 | Add per-slot prompt briefs |
| `415a95b` | 21 mai 13:17 | Expand per-course slot prompt profiles |
| `dbd31f8` | 21 mai 13:28 | Parallelize course text generation by slot |
| `f0bb187` | 21 mai 15:04 | Fix : ThreadPoolExecutor → eventlet GreenPool |
| `2f39c22` | 21 mai 15:22 | restart-from-content **(dernier état ancien)** |
| **`d93dd02`** | **23 mai 20:38** | **REFONTE — structured course generation pipeline** |
| `5ecc320` | 23 mai 21:24 | Modularize generation and review prompts |
| `52d6b10` | 23 mai 23:57 | Persist structured pipeline artifacts |
| `c71691a` | 24 mai 00:22 | Add plan adherence quality review |
| `460bac0` | 24 mai 00:51 | Parallelize structured course generation |
| `2364973` | 30 mai 19:24 | Calibrage budget texte par section |
| `4c57232` | 31 mai 13:37 | Implement deck slide templates |
| `629cb48` | 31 mai 21:02 | Map slide source text from course blocks |

---

## 3. Ancienne pipeline (état `2f39c22`) — ✅ vérifié

**Génération** (1 dossier = 1 journée, `content_generation_service.py`) :

- ✅ **Extraction de 7 créneaux** par 1 appel Claude (`extract_sub_parts`, `_EXTRACT_PROMPT`,
  `max_tokens=1500`) → `{title, sub_parts[7]}`. Durées **codées en dur**
  (45/45/55/45/60/60/50 min, `NUM_SUB_PARTS=7`). Seule étape de structuration — **pas de
  plan**. *(2f39c22:3864-3905, 3820-3852)*
- ✅ **Génération par créneau × 3 passes** (Fondation/Pratique/Maîtrise,
  `_generate_segment_text`, `from_scratch` régénère depuis `module_content`,
  `max_tokens=16000`, 3 retries) ⇒ **21 segments**. *(2f39c22:3908-4037, 4421-4498)*
- ✅ **Slot** = profil éditorial figé par position (`_COURSE_SLOT_PROMPT_PROFILES`,
  `label/moment/intention/rhythm/structure/avoid/handoff`), injecté tronqué à 7000/9000
  car. *(2f39c22:474-666, 771-815)*
- ✅ **Budget mots** dérivé de `PLAYLIST_SPEC` (durée − 17 s − 60 s × **165,7 mots/min** ×
  marge), imposé **par passe** + boucle continuation (max 2 × +350 mots). *(2f39c22:228-321,
  4019-4034)*
- ✅ **Parallélisation** par créneau via `eventlet.GreenPool`. *(2f39c22:4530-4546)*
- ✅ **Découpage audio** = re-découpe **linéaire** du texte concaténé en 7 blocs
  (`_build_course_blocs_from_segments`, `_choose_natural_boundary`,
  `_redistribute_undershoot_backward`). **Frontière de bloc ≠ frontière de créneau.**
  *(2f39c22:2714-2845, 2503-2602)*
- ✅ **Review au niveau segment** = 2 passes (humanisation #101-114, conformité #1-27) par
  **patches à match unique** (rejet si 0 ou ≥2 occurrences), max 5/appel, budget guard.
  *(2f39c22:7163-7330, 7063-7080)*
- ✅ **Sortie** = un **unique `.txt` concaténé** vers `CONTAINER_DOCUMENTS`. **Aucun
  artefact JSON intermédiaire.** *(2f39c22:4244-4281)*

**Structure du contenu généré** : flux **oral continu** avec tags Fish Audio inline
(`[pause]`, `[emphasis]`…) — **pas de JSON, pas de sections, pas de slides, pas de
métadonnées**. Trace structurale = liste des 7 noms de créneaux.

**Réponse à « gros prompt / slots / blocs / plan ? »** → **gros prompt direct + slots, sans
plan.** Prompts monolithiques `prompt-generation-tts-direct.md` (~1164 l.) et
`prompt-generation-tts-scratch.md` (~2938 l.) portant *simultanément* paradigme + plan
11 points + style oral + tags + budget + **26-27 règles recopiées aux 3 passes**.

---

## 4. Problèmes de l'ancienne approche — ✅ vérifié (sauf ❓ slides)

| Symptôme | Mécanisme |
|---|---|
| **Dérive pédagogique** | Cours longs sans architecture imposée ; profil de slot à cheval sur 2 blocs ; intros `from_scratch` à l'aveugle ⇒ doublon d'intro, fuite d'abstraction (horaires/blocs verbalisés), contenu après conclusion. |
| **Manque de traçabilité** | 1 `.txt` concaténé, aucun artefact JSON ; review = simple snapshot `text_content_pre_review`. Audit impossible sans relire logs/texte. |
| **Budgets audio** | Imposé à **3 endroits** (ratios distincts), porté par le *texte* du prompt, **sans garde-fou programmatique** ; la calibration bloc **invalidait la conformité** (`reviewed=0`). |
| ❓ **Slides incohérentes** | *(baseline inférée : `script_slide_generation_service` existait à `2f39c22` mais sans `_extract_slide_anchors_from_plan`)* — slides extraites du `.txt` par *text-mining libre*, sans plan ni traçabilité source. |
| **Reviews trop globales** | Une review mêlant structure+éthique+oralité ; patches **rejetés silencieusement** (paraphrase = 0 match) ; plafond 5 patches/chunk. |
| **Répétitions** | Boucle de continuation + 3 passes régénérant la journée sans coordination inter-créneaux. |
| **Erreurs vues trop tard** | Conformité vérifiée seulement au *gate* `launch-audio` ; problème visible après génération + reviews aval (souvent à l'oreille, après TTS). |

Limites « méta » : duplication des 26 règles (3× + entre `direct.md`/`scratch.md` qui ont
**divergé** : règle #27 absente de `direct.md`) ; **contradiction interne** (Passe 2 « cite
des entreprises réelles » `direct.md:938` vs règle #18 « si doute → fictif » `:560-568`) ;
**fausse parallélisation** (`ThreadPoolExecutor` sérialisé par eventlet, corrigé `f0bb187`).

---

## 5. Pipeline structurée (`HEAD`) — ✅ vérifié

1. **Plan JSON verrouillé à 4 couches** (`structured-course-plan-v2`) :
   **jour → 7 cours → sections (`opening`/`parts`[2-4]/`conclusions`) → `teaching_beats`**
   (typés, chacun avec `slide_anchor`). Contrat pédagogique. *(content_generation_service.py:1457-1562)*
2. **Génération par section isolée** (`structured-section`) + `scope_guard` + budget propre.
   **1 section = 1 unité native.**
3. **Autorité serveur sur les budgets** : `_normalize_structured_course_plans` écrase les
   budgets LLM ; `validators.py` **rejette** si Σ(sections) ≠ `target_words`. *(validators.py:45-48)*
4. **`parallel_body_then_late_opening`** : corps en parallèle → résumés → **intros tardives**
   (`course_summaries[n-1]`) → `day_conclusion` tardive ; `scope_guard` anti-fuite +
   vocabulaire learner-facing interdit (`bloc/créneau/horaire/planning`). *(:8333-8761)*
5. **Prompts modularisés** : `base-course-style` + `structured-plan` + `structured-section`
   + `budget-rewrite`. *(5ecc320)*
6. **5 passes de review ciblées** (4 couches historiques réinterprétées + 1 ajoutée), ordre
   figé : **plan-adherence** (avant budget) → **budget-rewrite** → **micro-conformité
   éthique** (#1-16 + scan lexical déterministe `ethical-lexical-terms.json`) →
   **humanisation** *polish-only* (v9) → **conformité finale** (5 règles : #14,15,17,18,22).
   *(:11938-11957, :13002-13007)*
7. **10 artefacts JSON persistés** (`content-plan`, `draft-sections`, `quality-reviews`,
   `budget-calibration`, `ethical-micro-review`, `course-scripts`, `reviewed-scripts`,
   `audio-plan`, `script-plan`…), enveloppe `artifact_payload` +
   `formation_job_id`/`content_job_id`/`folder_id`. *(content_pipeline/artifacts.py)*
8. **Slides *anchor-first*** : `teaching_beat → slide_anchor` décidé **au plan**, template du
   **catalogue fermé**, traçage `source_quote` + offsets `highlight_word_start/end`, slides
   sans `slide_anchor_id` supprimées, trous comblés par *context slides*. *(script_slide_generation_service.py:611-709)*
9. **Auditabilité UI** : roadmap d'étapes cliquables, modales artefacts + **diffs
   avant/après**, events DB (`formation_pipeline_events`, `content_review_reports`),
   `EventDetailModal`, IDs explicites.
10. **Parallélisation propre** : `GreenPool` natif + gate `ANTHROPIC_MAX_CONCURRENT` +
    retries 429 typés. *(460bac0, 835a357)*

---

## 6. Tableau comparatif (cœur de la section mémoire)

| # | Ancienne pipeline | Problème | Nouvelle solution | Bénéfice | Métrique (📏 à mesurer) |
|---|---|---|---|---|---|
| 1 | 7 créneaux × 3 passes, **re-découpe linéaire** en 7 blocs (frontière bloc ≠ créneau) | Profil/handoff à cheval sur 2 blocs ; bloc non autonome | Génération **par section isolée** depuis le plan, sans re-découpe | Bloc audio = unité native, frontières nettes | Taux de blocs à intro/outro tronquée (≈ aléatoire → ~0) |
| 2 | Budget imposé à **3 endroits**, porté par le prompt, sans contrôle | Triple correction incohérente, calibration invalide la conformité | **Budgets serveur font autorité**, validés Σ(sections)=`target_words` | Cohérence math. plan↔audio ; ordre figé | Taux hors-budget (`too_short/too_long`) ; points d'imposition 3→1 |
| 3 | Slides *text-mining libre* du `.txt` | Slides non tracées au source (hallucination visuelle) | **Anchor-first** : `slide_anchor` au plan + `source_quote`+offsets | Deck 100 % piloté par le plan, traçable | % slides traçables à un passage exact (cible 100 %) |
| 4 | 2 passes **globales**, patches à match unique | Mélange dimensions ; rejet silencieux ; correctif casse la structure | **5 passes ciblées ordonnées** + scan lexical (~250 termes) | Chaque passe corrige 1 chose ; réécriture contextuelle | Nb dimensions (1→5) ; taux de patches rejetés ; couverture lexicale |
| 5 | **Aucun artefact** ; 1 `.txt` + 21 segments | Audit impossible sans relire texte/logs | **10 artefacts JSON** + diffs avant/après, IDs | Chaîne de preuves bout-en-bout | Nb artefacts/journée (1→10) ; profondeur de traçabilité |
| 6 | Intros `from_scratch` à l'aveugle, passes non coordonnées | **Doublon d'intro**, fuite d'abstraction, cours N finit N-1 | `parallel_body_then_late_opening` + `summaries[n-1]` + `scope_guard` | Raccords cohérents, fin du double accueil | Taux de répétition inter-sections ; occurrences `bloc/horaire` côté apprenant (→0) |
| 7 | `ThreadPoolExecutor` **sérialisé** par eventlet | Fausse parallélisation, latence cumulée | `GreenPool` natif + gate + retries 429 (workers 3, plafond 7) | 7 cours en parallèle réel | Temps de génération (séquentiel → ~⌈7/3⌉ lots) ; appels concurrents réels |
| 8 | Conformité au seul *gate* `launch-audio` | **Erreurs vues trop tard** (après TTS) | Observabilité **par étape** (events DB + `EventDetailModal`) | Erreur vue là où elle survient, corrélable | Délai de détection (après TTS → temps réel) ; status 1→16 étapes |
| 9 | Cours longs sans architecture visible | **Dérive pédagogique**, conclusion cassée | Plan verrouillé + review **plan-adherence** | Architecture imposée et auditée *avant* le budget | Nb d'issues d'adhérence/cours (`content-quality-reviews.json`) |

---

## 7. Honnêteté méthodologique (Codex DOIT inclure ces réserves)

- 📏 Les chiffres (3 workers, 7 cours, 165,7 mots/min, silences 17 s/60 s, ratios
  0,94/0,97/0,95) sont des **paramètres**, pas des mesures. Métriques colonne 6 = **« à
  mesurer en prod »**.
- La fiabilité de l'**audio final** n'est pas démontrée : conversion mots→secondes =
  *approximation linéaire à valider* (commentaire `R1`).
- ❓ La **baseline slides anciennes** est partiellement inférée.
- Le **coût API** (~13,50 $/formation, workflow manuel) n'est pas recoupé par un calcul de
  tokens ; surcoût de la parallélisation non chiffré — justifié par « 1 RNCP = 1 module
  durable ».
- Rigidité **7 cours/jour** : `validators.py` force `expected_courses=7` (`range(1,8)`).

---

## 8. Sources pour citation

- **Ancien service** : `git show 2f39c22:backend/services/content_generation_service.py`
  (extraction `3864-3905`, slots `474-666`, budget `228-321`, re-découpe `2714-2845`,
  review `7163-7330`, calibration bloc `3233-3354`).
- **Anciens prompts** : `git show 2f39c22:backend/prompts/prompt-generation-tts-direct.md`
  (table budget `373-382`, règles `388-866`, sortie `889-905`).
- **Nouveau service** : `backend/services/content_generation_service.py` (plan `1457-1562`,
  ordre pipeline `8333-8761`, budgets `1764-1775`, conformité finale `11938-11957` +
  `13002-13007`).
- **Modules** : `backend/services/content_pipeline/{validators,artifacts,calibration}.py`.
- **Prompts modulaires** : `backend/prompts/{generation,reviews,slides}/`.
- **Notes mémoire cohérentes** : `01-architecture/pipeline-contenu-auditable-anchor-first.md`,
  `03-decisions/pipeline-contenu-plan-json-4-couches.md`,
  `03-decisions/slides-json-maitre-anchor-first.md`,
  `02-problemes/fuite-abstraction-cours-horaires-script-oral.md`,
  `03-decisions/micro-conformite-ethique-locale.md`,
  `04-solutions/generation-structuree-intros-tardives-parallelisees.md`,
  `04-solutions/modales-audit-pipeline-artefacts-diffs.md`.

---

> Analyse produite par Claude Code (Opus 4.8, 1M) le 1ᵉʳ juin 2026, par lecture Git/code en
> **lecture seule** (état `2f39c22` vs `HEAD`) + passe critique de vérification. Aucun
> fichier source modifié.
