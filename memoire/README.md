# Mémoire — Le Socrate

Ce dossier consolide **toutes les réflexions, décisions techniques, problèmes rencontrés et solutions** élaborés au cours du développement du projet Le Socrate. Il sert de base pour la rédaction du mémoire académique en fin d'année.

**Règle de remplissage** : à chaque réflexion, débat technique, arbitrage d'architecture ou incident non-trivial, un fichier (ou une section d'un fichier existant) est ajouté ici. Le CHANGELOG reste la vue chronologique ; ce dossier est la vue **thématique et analytique**.

---

## Méga-menu

### 1. Architecture et décisions structurantes

- [Pipeline Formation Automatisé (RNCP → TTS)](01-architecture/pipeline-formation-vue-ensemble.md) — Vue d'ensemble du pipeline bout-en-bout
- [Multi-tenant : une plateforme par pipeline](01-architecture/multi-tenant-plateforme-par-pipeline.md) — Pourquoi chaque formation crée sa propre plateforme
- [Un RNCP = un module durable (pas un job par promo)](01-architecture/un-rncp-un-module-durable.md) — Principe fondamental : pipeline exécuté une fois, module réutilisé pour toutes les promos
- [Architecture qualité programme en 4 couches](01-architecture/architecture-4-couches-qualite-programme.md) — Enrichissement / Budget / Squelette pédagogique / RAG externe

### 2. Problèmes rencontrés

- [RC et ROME indisponibles pour RNCP 35304](02-problemes/rc-rome-indisponibles.md) — Diagnostic complet et décision d'abandon
- [Ratio de dilution REAC → formation](02-problemes/ratio-dilution-reac.md) — Le problème "parler dans le vide" à N jours
- [HR Dashboard — heure cours P2/P3 figée après reload](02-problemes/hr-dashboard-heure-cours-figee-p2-p3.md) — Asymétrie GET/POST service-to-service sur `platform_id`
- [Audit global — dette de fiabilité avant extension](02-problemes/audit-global-fiabilite-projet.md) — Multi-tenant, rate-limits, frontend non vérifiable, hygiène repo
- [Régression UI après `audio_error`](02-problemes/regression-ui-apres-audio-error.md) — Boutons Voir/Word disparaissaient sur l'étape 6 quand le TTS plantait en aval, malgré données intactes. Fix : condition d'affichage découplée du `job.status`, basée sur l'existence des folders completed.
- [Claude Code subprocess tape sur API au lieu du forfait](02-problemes/claude-code-tape-sur-api-au-lieu-forfait.md) — `ANTHROPIC_API_KEY` héritée par `subprocess.Popen` faisait que la CLI utilisait le compte API à la carte (épuisé) au lieu du forfait OAuth local. Fix : strip env avant Popen.
- [Coupure du MP3 cours en pleine phrase](02-problemes/coupure-audio-tts-pleine-phrase.md) — Calibration TTS approximative + fenêtre de découpe symétrique = bloc trop long → MP3 tronqué mid-phrase ou pré-check qui stoppe l'auto-pilot 52 jours. Diagnostic complet et options envisagées.
- [Risques résiduels avant prod 52 jours auto-pilot](02-problemes/pipeline-52-jours-risques-residuels.md) — 5 risques identifiés (calibration TTS empirique, retry segment, compteur max anti-boucle, boot recovery, heartbeat eventlet) avec criticité et plan d'action.
- [Cas pathologiques pipeline audio cours — checklist de monitoring](02-problemes/cas-pathologiques-pipeline-audio.md) — 12 cas identifiés (bloc 7 surchargé, paragraphe trop gros, calibration fausse, closing hors-ton, carryover en cascade, etc.) avec détection + récup pour chacun.

### 3. Décisions techniques et arbitrages

- [Audit RAG : pourquoi RAG sur REAC est un mauvais outil](03-decisions/audit-rag-sur-reac.md) — Réflexion critique sur l'intuition RAG
- [SQLite local vs Azure SQL — arbitrage persistance](03-decisions/sqlite-vs-azure-sql.md) — Pourquoi on garde SQLite pour la knowledge base
- [Prompts TTS — règles anti-dérive + stratégie sandwich](03-decisions/prompts-tts-regles-anti-derive.md) — Principe cardinal "ne pas mentir", 6 règles #21-#26, paradigme cours à distance, 3 rappels en tête/milieu/fin pour le LLM
- [Pipeline formation double colonne — API cloud + Claude Code local](03-decisions/pipeline-dual-api-et-claude-code.md) — 2 pipelines visuelles côte à côte (séparation stylée au milieu), un seul job, mixage libre par étape, badge d'origine `generated_via`. Dropdown Haiku/Sonnet par étape. V1 export/import manuel, pas de subprocess auto. Restriction prod `LOCAL_DEV=true` + `which claude`.

### 4. Solutions techniques mises en place

- [Couche 1 — Enrichissement REAC → Knowledge Base](04-solutions/couche-1-enrichissement-reac.md) — Implémentation détaillée de la première couche de l'architecture qualité programme
- [Réparation JSON tolérante à la troncature Claude](04-solutions/json-repair-troncature-claude.md) — Parser tolérant quand `max_tokens` atteint, coupe JSON mid-string
- [Parallélisme enrichissement KB (3 workers)](04-solutions/parallelisme-enrichissement-kb.md) — Speedup ×3 via ThreadPoolExecutor + lock DB, sweet spot rate-limits Anthropic
- [Admin par plateforme — scoping complet](04-solutions/admin-par-plateforme.md) — Helper `_get_platform_id()` + fix des 8 routes admin + bouton Admin sur chaque carte HR Dashboard
- [Module formation persistant — V1](04-solutions/module-formation-persistant-v1.md) — Matérialisation de "1 RNCP = 1 module durable" via table `formation_modules` + modale pilotée par modules + auto-création au `audio_launched`
- [Découpage 7 blocs cours — cap budget + cascade paragraphes](04-solutions/decoupage-blocs-cap-budget-cascade.md) — Hard cap mots par bloc calé sur le budget TTS ; les paragraphes en surplus cascadent au bloc suivant. Déterministe, gratuit, préserve verbatim les unités d'idée. Préféré au LLM-shortening réactif.
- [Closing bloc cours contextuel — redistribution backward + texte de fin adaptatif](04-solutions/closing-bloc-cours-contextuel.md) — Suite du cap budget : si un bloc finit trop tôt, on tire d'abord des paragraphes du bloc suivant (passe 2 déterministe), puis on ajoute un closing LLM calibré sur le gap résiduel (passe 3). Le cours porte sa propre clôture pédagogique, la pause reste un sas simple.
- [Carryover bloc 7 → folder suivant + rebalancing LLM dernier jour](04-solutions/carryover-jour-a-jour-bloc-7.md) — Si bloc 7 déborde, on reporte les paragraphes excédentaires au cours suivant via `content_generation_jobs.carryover_*`. Intro fixe "au cours dernier" (jamais "hier"). Pour le dernier jour : `_reduce_last_bloc_to_budget` remanie via LLM sans ajouter d'idées.

---

## Comment naviguer ce dossier

- **Pour rédiger le mémoire** : lire par thématique (1 → 2 → 3 → 4). Chaque fichier suit une structure identique (Contexte → Problème → Options → Décision → Rationale → Références code).
- **Pour retrouver une décision précise** : utiliser la recherche full-text (`Cmd+Shift+F` dans VS Code) sur `memoire/`.
- **Pour voir la chronologie** : consulter `CHANGELOG.md` à la racine du projet.

---

## Structure type d'un mémo

```markdown
# [Titre]

**Date** : YYYY-MM-DD
**Thématique** : architecture | problème | décision | solution
**Statut** : actif | résolu | archivé

## Contexte
(Ce qui a mené à cette réflexion)

## Problème / Question
(Formulation précise)

## Options envisagées
(Alternatives discutées, avec arguments)

## Décision finale
(Ce qui a été retenu et pourquoi)

## Rationale technique
(Justification détaillée, contraintes, trade-offs)

## Références code
(Fichiers, lignes, commits concernés)

## Leçons / Pour le mémoire
(Ce qu'on retiendra pour la rédaction finale)
```
