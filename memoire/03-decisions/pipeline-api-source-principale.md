# Pipeline API comme source principale, Claude Code comme secondaire

**Date** : 2026-05-25
**Thématique** : décision | architecture | exploitation
**Statut** : actif

## Contexte

Le projet a longtemps conservé deux chemins d'exécution :

- pipeline API cloud ;
- pipeline Claude Code locale.

La pipeline Claude Code était utile pour expérimenter, corriger rapidement et tester
certains workflows sans consommer ou bloquer les mêmes ressources. Mais l'objectif
produit est de lancer les formations via l'interface et l'auto-pilot API.

## Problème / Question

À mesure que la pipeline devient plus structurée, maintenir deux chemins strictement
équivalents devient coûteux.

Chaque nouvelle étape doit alors être dupliquée ou synchronisée :

- prompts modulaires ;
- plan JSON ;
- artefacts ;
- micro-conformité ;
- slides ;
- reviews ;
- audio-plan ;
- roadmap frontend ;
- rapports d'audit.

Si l'effort principal reste dispersé, la pipeline réellement utilisée par
l'utilisateur risque de ne pas être celle qui reçoit les corrections.

## Décision finale

La pipeline API devient la source principale.

Conséquences :

- les corrections doivent viser d'abord le chemin API ;
- l'auto-pilot frontend doit refléter les étapes API réelles ;
- les artefacts doivent être produits par l'API ;
- les endpoints d'audit doivent lire les sorties de l'API ;
- Claude Code reste secondaire : expérimentation, fallback local, débogage, mais pas
  chemin prioritaire.

## Rationale technique

La pipeline API est celle qui sera utilisée en production par l'interface. Elle doit
donc porter :

- la vérité fonctionnelle ;
- les garde-fous ;
- la traçabilité ;
- les optimisations de vitesse ;
- les rapports lisibles depuis le frontend.

Claude Code garde une valeur, mais il ne doit pas ralentir l'évolution du produit.
Le risque principal est la divergence : une correction présente localement mais pas
dans l'API donnerait une fausse impression de qualité.

## Trade-offs

### Avantage

- moins de duplication ;
- moins de comportements divergents ;
- meilleure cohérence entre frontend, backend et déploiement ;
- pipeline testable via l'interface réelle.

### Inconvénient

- certaines expérimentations locales deviennent secondaires ;
- il faut accepter que tous les garde-fous importants soient portés côté API ;
- les coûts API doivent être surveillés.

## Références code

- `backend/routes/formation_routes.py`
- `backend/services/content_generation_service.py`
- `backend/services/content_pipeline/`
- `backend/services/claude_code_mission_service.py`
- `frontend/src/pages/FormationPipeline.jsx`
- Mémo connexe :
  - `03-decisions/pipeline-dual-api-et-claude-code.md`

## Leçons / Pour le mémoire

Dans un projet IA avec plusieurs chemins d'exécution, il faut choisir un chemin
canonique. Sinon, la complexité augmente à chaque amélioration.

Ici, la décision produit est claire : l'API doit être la pipeline fiable, auditable
et lançable par l'utilisateur final. Le local reste un atelier, pas la chaîne de
production principale.
