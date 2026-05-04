# Décision : pipeline formation en **double colonne** — API cloud ET Claude Code local

**Date** : 2026-04-24
**Statut** : décidé, mémo + wireframe à valider avant implémentation
**Renomme et élargit** : `pipeline-review-3-boutons.md` (ancien périmètre limité à l'étape 6)
**Fichiers impactés (à venir)** : `backend/routes/formation_routes.py`, `backend/services/content_generation_service.py`, `backend/services/knowledge_base_service.py`, `backend/services/formation_pipeline_service.py`, `backend/database/db.py`, `frontend/src/pages/FormationPipeline.jsx`

---

## Contexte

Deux besoins parallèles sont apparus au cours des sessions précédentes :

1. **Besoin qualité** — Claude Sonnet produit des passages non conformes
   malgré la stratégie sandwich du prompt (règles #1-#27). Il faut une
   étape de vérification/correction.
2. **Besoin économique + contextuel** — en dev local, l'utilisateur a
   Claude Code avec son forfait Max (illimité) et accès au **contexte
   repo complet** (CLAUDE.md, wiki, prompts, mémoire). Un agent Claude
   Code qui fait la même tâche qu'un appel API est souvent **plus
   précis** (contexte projet) **et moins cher** (forfait vs tokens).

Ces deux besoins convergent : **la pipeline doit pouvoir tourner en
deux modes** selon l'environnement. Mais au lieu de disséminer des
boutons "Claude Code" à côté de chaque bouton "API" (ce qui fait une UX
à tiroirs), on matérialise la dualité **dans le design** :

> **Deux pipelines côte à côte, une ligne de séparation au milieu.**
> Gauche = API cloud. Droite = Claude Code local.

## Problème

Concevoir un pattern unifié qui :

1. **Matérialise visuellement** les deux voies (API vs local) sans
   noyer l'utilisateur sous les boutons.
2. **Autorise le mixage par étape** (ex : KB en Haiku local, programme
   global en Sonnet API, cours en Sonnet local). Un même RNCP peut
   exploiter le meilleur des deux mondes.
3. **Reste idempotent et auditable** : pour chaque artefact produit, on
   sait **via quel modèle / mode** il a été généré.
4. **Réserve la colonne locale au dev**. En prod Azure, le binaire
   `claude` n'est pas installé — il faut masquer/griser cette colonne
   sans dégrader l'ergonomie.
5. **Conserve un seul `formation_pipeline_job`** plutôt que d'éclater
   en deux jobs parallèles difficiles à réconcilier.

## Options envisagées

### Option A — Bouton Claude Code à côté de chaque bouton API

Rejeté. L'UI accumule les boutons, l'utilisateur doit lire chaque bouton
pour savoir lequel fait quoi, les dropdowns modèle se multiplient. Ça
marche pour 1 étape (c'était l'idée initiale pour l'étape 6) mais pas
pour 4-5 étapes.

### Option B — Toggle global "Mode API / Mode Claude Code" en haut de page

Rejeté. L'utilisateur ne peut plus mixer par étape. Trop binaire : si
Haiku suffit pour la KB mais qu'on veut Sonnet API pour le programme
global, le toggle force à rebasculer plusieurs fois, et l'historique de
qui a fait quoi devient confus.

### Option C — Deux jobs parallèles (un par mode)

Rejeté. Crée deux formations en base pour un seul RNCP, divergence
garantie sur les artefacts (KB, programme, segments, etc.), pas de
possibilité de reprendre une pipeline commencée à gauche en basculant
à droite.

### Option D — **Deux pipelines côte à côte, un seul job, mixage libre** ✅

Retenu. Détails :

- Un seul `formation_pipeline_job.id`, un seul ensemble d'artefacts
  (`formation_knowledge_base`, `formation_programs`, `cours_folders`,
  `content_generation_segments`, etc.).
- Chaque artefact porte une **trace de son origine** via une colonne
  `generated_via TEXT` avec valeurs : `'api'`, `'claude_code_haiku'`,
  `'claude_code_sonnet'`.
- UI : deux colonnes verticales avec les mêmes étapes, séparées par
  une **ligne stylée au milieu**. Étapes 1-2 en **en-tête commun**
  au-dessus du split, étape 7 (TTS Fish Audio) en **pied commun**
  en-dessous.
- Une étape exécutée côté gauche affiche ensuite un badge **"Généré
  via API"** (visible dans les deux colonnes). Côté droit, idem avec
  **"Généré via Claude Code (Haiku|Sonnet)"**. L'étape n'est pas
  désactivée dans l'autre colonne — tu peux **relancer** via l'autre
  voie si tu veux comparer ou corriger.
- Le dernier `generated_via` d'une étape est celui qui prime pour la
  suite (le programme global utilisé par l'étape 5 est celui qui a
  été produit en dernier, quel que soit le mode).

## Décision — architecture retenue

### Layout UI

```
┌─────────────────────────────────────────────────────────────────────┐
│ EN-TÊTE COMMUN                                                      │
│   TP : Employé Commercial · RNCP 35028 · 5 jours                    │
│   ① Recherche RNCP    [auto]  ✓                                     │
│   ② Téléchargement REAC [auto] ✓                                    │
├─────────────────────────────┬───────────────────────────────────────┤
│                             │                                       │
│   ⚙️  API CLOUD              │           💻  CLAUDE CODE LOCAL        │
│   (Anthropic par token)     │           (forfait Claude Code)       │
│                             │                                       │
│   ③ Enrichir KB             │    ③ Enrichir KB                      │
│      [ Lancer via API ]     │       Modèle : [Haiku ▾]              │
│      …barre progress…       │       [ Exporter mission ]            │
│                             │                                       │
│   ④ Programme global        │    ④ Programme global                 │
│      [ Lancer via API ]     │       Modèle : [Haiku ▾]              │
│                             │       [ Exporter mission ]            │
│                             │                                       │
│   ⑤ Programmes journée      │    ⑤ Programmes journée               │
│      [ Lancer via API ]     │       Modèle : [Haiku ▾]              │
│                             │       [ Exporter mission ]            │
│                             │                                       │
│   ⑥ Génération cours (text) │    ⑥ Génération cours (text)          │
│      [ Lancer via API ]     │       Modèle : [Sonnet ▾]             │
│      Enchaîner review ☐     │       [ Exporter mission ]            │
│                             │                                       │
│   ⑥bis Révision conformité  │    ⑥bis Révision conformité           │
│      [ Lancer via API ]     │       Modèle : [Sonnet ▾]             │
│                             │       [ Exporter mission ]            │
│                             │                                       │
├─────────────────────────────┴───────────────────────────────────────┤
│ PIED COMMUN                                                         │
│   ⑦ Synthèse TTS Fish Audio (identique des 2 côtés)                 │
│      [ Relancer TTS test (gratuit) ] [ Relancer TTS payant ]        │
└─────────────────────────────────────────────────────────────────────┘
```

Séparateur central : **trait vertical sobre** blanc translucide
(`rgba(255,255,255,0.12)`, largeur 1 px, pas de halo ni de gradient —
l'effet gadget dégrade plus qu'il n'apporte). Sur mobile / écran étroit
(< 900 px) : colonnes empilées (API en haut, Claude Code en bas) avec
un séparateur horizontal du même style.

### Badge d'origine sur chaque étape

Une fois une étape exécutée, les **deux colonnes** affichent la même
étiquette discrète à côté du nom de l'étape :

```
③ Enrichir KB  ✓  [Généré via Claude Code · Haiku · 11:23]
```

Code couleur :
- API → badge `#60a5fa` (bleu) avec icône `cloud`
- Claude Code Haiku → badge `#f59e0b` (ambre) avec icône `terminal`
- Claude Code Sonnet → badge `#8b5cf6` (violet) avec icône `terminal`

### Mixage libre, relance possible

- Tu peux faire l'étape 3 via Claude Code Haiku, puis l'étape 4 via
  API, puis l'étape 5 via Claude Code Sonnet. Rien ne te l'interdit.
- Relancer une étape **écrase** le précédent artefact et met à jour
  `generated_via`. Les étapes aval **se resalissent** (flag `dirty=1`
  sur les artefacts dérivés si l'étape amont a changé).
- La règle d'aval ne concerne pas les étapes déjà en aval du flow :
  si tu régénères la KB (étape 3), les étapes 4-5-6 restent marquées
  `stale` jusqu'à relance manuelle. Pas de cascade automatique.

### Dropdown modèle — par étape, pas global

Côté Claude Code, chaque étape a son propre dropdown `[Haiku ▾]` avec
options `Haiku` et `Sonnet`. Pas d'Opus (overkill, pas demandé).

Rationale : on peut vouloir Haiku pour la KB (150k mots, besoin de
volume rapide, qualité "OK") et Sonnet pour l'étape 6 (génération cours
avec règles sandwich, besoin de qualité + respect des règles éditoriales)
et l'étape 6bis (révision fine, Sonnet capture mieux les dérives
stylistiques subtiles).

Défaut par étape proposé :
| Étape | Défaut |
|---|---|
| 3 (KB) | Haiku |
| 4 (programme global) | Haiku |
| 5 (programmes journée) | Haiku |
| 6 (génération cours) | Sonnet |
| 6bis (révision) | Sonnet |

Modifiable librement par l'utilisateur dans le dropdown.

### V1 — export/import manuel, pas subprocess

**Décision importante** (nuance apportée après proposition initiale) :

Pour V1 Claude Code, **pas de `subprocess.Popen(['claude', ...])`
depuis le backend**. Trop fragile :
- Permissions (`--allowed-tools`, `--dangerously-skip-permissions` ?)
- Détection des confirmations interactives bloquantes
- Logs / streaming sortie
- Reprise après crash partiel
- Installation variable de `claude` selon la machine dev
- Serveur Flask transformé en orchestrateur de terminal interactif

À la place, workflow **export/import manuel** uniforme sur toutes les
étapes Claude Code :

1. **Clic "Exporter mission"** côté droit
2. Le backend écrit dans `review_queue/<job>/<folder_or_step>/` :
   - `task.md` — consigne précise pour Claude Code (sortie attendue,
     chemin où écrire, format)
   - `input.md` — les données d'entrée (REAC brut, KB, programme,
     segment de cours selon l'étape)
   - `rules.md` — pour les étapes où des règles s'appliquent (étape 6
     et 6bis), extrait des règles #1-#27
3. L'UI affiche une modale avec :
   - La commande à taper : `claude --model haiku` (ou `claude --model sonnet`)
   - L'instruction à donner à Claude Code : *"Exécute la mission décrite
     dans `review_queue/<job>/<step>/task.md`"*
   - Un bouton "J'ai terminé, importer le résultat"
4. Claude Code écrit `output.md` (ou plusieurs fichiers selon l'étape).
5. **Clic "Importer le résultat"** côté UI → le backend lit `output.md`,
   parse selon le format attendu de l'étape, met à jour la DB, met à
   jour `generated_via='claude_code_<model>'`.
6. Archive : `review_queue/<job>/<step>/` → `review_queue/_done/<timestamp>-<step>/`.

On reconsidérera le subprocess auto en V2+ uniquement après que le
workflow manuel ait prouvé sa valeur et ses points de friction réels.

### Restriction prod : LOCAL_DEV=true

La colonne droite n'apparaît que si la variable `.env` `LOCAL_DEV=true`
est définie côté backend (sinon la route d'export renvoie 403, et le
frontend bascule en mono-colonne — une seule pipeline API, pas de
split, pas de ligne de séparation).

Pas de check `shutil.which('claude')` en V1 — le workflow export/import
est indépendant de la présence locale du binaire `claude`. L'utilisateur
peut très bien exporter les fichiers depuis sa machine de dev puis
exécuter Claude Code depuis une autre machine/contexte. Le check
`which claude` deviendra pertinent **seulement** si on implémente en
V2+ le subprocess auto.

### Format de sortie du reviewer — match textuel unique

(Décision déjà actée dans l'ancien mémo, maintenue.)

Pour l'étape 6bis de révision, le reviewer Claude (API ou Claude Code)
reçoit le texte + règles et renvoie un JSON :

```json
{
  "patches": [
    {
      "original": "phrase EXACTE à remplacer (copie verbatim)",
      "replacement": "phrase corrigée",
      "rule_violated": "#27",
      "reason": "registre trop écrit : 'il convient de' → 'il faut'"
    }
  ]
}
```

Côté backend, application :

```python
occurrences = text.count(patch["original"])
if occurrences == 1:
    text = text.replace(patch["original"], patch["replacement"])
    log_patch_applied(patch)
elif occurrences == 0:
    log_patch_rejected(patch, reason="original not found")
else:
    log_patch_rejected(patch, reason=f"ambiguous ({occurrences} occurrences)")
```

Max 5 patches par appel. Règle cruciale : toute modification d'un
segment (régénération, édition manuelle, patch reviewer appliqué) doit
remettre `reviewed=0` ET `dirty=1`. Centralisée dans un helper DB
`mark_segment_modified(segment_id)` à créer.

## Rationale

### Pourquoi un seul job et pas deux

Deux jobs = deux formations en base = risque de divergence +
double maintenance + impossible de mixer en cours de route. Un seul
job avec trace d'origine par artefact = flexibilité maximale + audit
préservé.

### Pourquoi étapes 1-2 en en-tête et étape 7 en pied

Étapes 1-2 (recherche RNCP + téléchargement REAC) ne font pas d'appel
Claude — aucune différence API vs Claude Code. Les dupliquer est un
bruit visuel.

Étape 7 (TTS Fish Audio) fait un appel **Fish Audio** pas Anthropic —
ne rentre pas dans la dichotomie API Claude / Claude Code. La laisser
en pied commun garde le sens.

### Pourquoi mixage libre

Contrainte d'usage réelle : Haiku est idéal pour le volume (KB 150k
mots), Sonnet pour la précision (règles éditoriales cours). Forcer un
seul mode = perdre le meilleur des deux. L'audit via `generated_via`
permet de savoir a posteriori ce qui a été bien fait vs mal fait.

### Pourquoi dropdown par étape

Même rationale : Haiku KB + Sonnet cours est le pattern optimal. Un
dropdown global empêche cette combinaison courante.

### Pourquoi V1 sans subprocess auto

Complexité trop haute pour le bénéfice. Le workflow manuel (export →
commande → import) marche toujours, peu importe la machine, peu
importe la version de `claude` installée. Subprocess auto = économie
de 2 clics par étape, au prix d'un code fragile difficile à débogguer.
Commencer simple, complexifier si besoin est avéré.

### Pourquoi restriction prod LOCAL_DEV

Claude Code n'est pas installé sur Azure App Service. Afficher une
colonne qui ne marche pas = frustration. Détection bornée par env var
+ `shutil.which('claude')` = dégradation gracieuse en mono-colonne
côté prod.

## Risques et mitigations

| Risque | Mitigation |
|---|---|
| Bloat UI sur grands écrans — 2 colonnes trop larges | Width max par colonne (ex : `max-w-2xl`) + centrage du split |
| Confusion utilisateur sur "quelle colonne a produit quoi" | Badge d'origine visible sur chaque étape, dans les DEUX colonnes (pas juste celle qui a lancé) |
| Export/import oublié — l'utilisateur clique "Exporter" puis oublie de revenir | Modale persistante tant que l'import n'est pas fait ; bandeau rouge en haut de la page "N missions export en attente" |
| Patches reviewer non trouvés (`original` introuvable) | Log clair côté UI "N appliqués / M rejetés", détails rejetés affichés |
| Cascade d'aval non gérée | Marqueur `stale=1` sur artefacts en aval d'une étape modifiée, affichage visuel "Version dépassée" |
| Colonne droite visible en prod par erreur | Variable `LOCAL_DEV=true` explicitement requise (non définie en prod Azure). Routes backend export/import renvoient 403 si absent, frontend bascule en mono-colonne |
| `review_queue/` qui grossit infiniment | Archive dans `_done/<timestamp>-<step>/` avec rotation automatique (nettoyage >30 jours) |

## Références code (à venir, Phase 1 — étape 6 + 6bis)

- `backend/database/db.py` — migrations :
  - `content_generation_segments.reviewed INTEGER DEFAULT 0`
  - `content_generation_segments.generated_via TEXT`
  - `formation_knowledge_base.generated_via TEXT` (par ligne)
  - `formation_programs.generated_via TEXT`
  - etc. sur chaque table d'artefact
- `backend/services/content_generation_service.py` :
  - fonction `run_content_review(folder_id)` (API)
  - helper `export_claude_code_mission(job_id, step, model)`
  - helper `import_claude_code_result(job_id, step)`
  - helper `mark_segment_modified(segment_id)` qui remet
    `reviewed=0 AND dirty=1`
- `backend/routes/formation_routes.py` :
  - `POST /api/formation/<job>/content/<folder>/review` (API)
  - `POST /api/formation/<job>/step/<step>/export-mission` (Claude Code)
  - `POST /api/formation/<job>/step/<step>/import-result` (Claude Code)
  - `GET /api/formation/<job>/pending-missions` (pour le bandeau rouge)
- `backend/services/formation_pipeline_service.py` :
  - colonnes `LOCAL_DEV_ENABLED` calculée au boot
- `frontend/src/pages/FormationPipeline.jsx` :
  - refonte layout 2 colonnes, séparateur
  - composant `StepCard` avec prop `column: 'api' | 'claude_code'`
  - composant `OriginBadge` (API / CC Haiku / CC Sonnet)
  - composant `ExportMissionModal` avec instructions
  - state `pendingMissions` + bandeau global

## Phases d'implémentation

**Phase 1 — Étape 6 + 6bis (priorité)**
- Bouton API "Réviser la conformité" sous "Générer" côté colonne gauche
- Bouton Claude Code "Exporter mission révision" côté colonne droite
- Table `content_generation_segments` : ajout `reviewed`, `generated_via`
- Format patches `{original, replacement}` opérationnel
- Helper `mark_segment_modified`
- Endpoint export/import mission

**Phase 2 — Refonte UI 2 colonnes sur /formation-pipeline**
- Layout 2 colonnes + séparateur
- Badges d'origine
- Dropdowns modèle par étape
- Variable LOCAL_DEV + détection `which claude`

**Phase 3 — Étapes 3, 4, 5 côté Claude Code**
- Export/import missions pour KB, programme global, programmes journée
- Attention étape 3 : Claude Code doit boucler en interne (150k mots
  sortie > 1 appel Haiku), `task.md` doit l'expliquer
- Colonne `generated_via` sur les tables correspondantes

**Phase 4 (optionnelle, future)**
- Pipeline auto chaînée (case à cocher "enchaîner" sur étape 6 → 6bis)
- Cascade aval (marquage `stale=1` automatique)
- Éventuel subprocess `claude` auto si le manuel s'avère frustrant

## Leçons (pré-implémentation)

1. **Le design matérialise la décision**. Deux colonnes visibles
   communiquent instantanément "tu as deux voies possibles" alors
   qu'un toggle cache cette dualité. L'UI est pédagogique avant
   d'être fonctionnelle.

2. **Un seul job, N origines**. Architecturalement plus simple et
   plus souple que N jobs parallèles. La trace d'origine (colonne
   `generated_via`) remplace l'isolement par duplication.

3. **Refuser le subprocess auto en V1**. Règle simplicité : un
   workflow manuel qui marche vaut mieux qu'un workflow auto
   fragile. Ne complexifier qu'une fois qu'on a constaté le besoin
   réel.

4. **Restriction par env var + détection runtime**. Le pattern
   `LOCAL_DEV=true` + `shutil.which('claude')` est copiable sur
   d'autres features réservées au dev (ex : panneau debug,
   regénération forcée, etc.).

5. **Mixage par étape plutôt que mode global**. Les décisions réelles
   (Haiku volumineux vs Sonnet précis) sont granulaires — le design
   doit permettre cette granularité, pas la forcer vers un choix
   global.

## Liens

- `memoire/01-architecture/un-rncp-un-module-durable.md` — principe
  qui justifie l'investissement dans la qualité
- `memoire/03-decisions/prompts-tts-regles-anti-derive.md` — les règles
  #1-#27 que le reviewer applique
- `memoire/01-architecture/pipeline-formation-vue-ensemble.md` — où
  s'insèrent les 2 pipelines
- Wireframe détaillé : à générer en complément (ASCII ou Figma)
