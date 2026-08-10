# Prompt Architecture

`prompts-generaux-contenu-formation.md` est conservé comme prompt historique et
fallback legacy.

Le workflow structuré utilise désormais des fichiers spécialisés :

- `generation/base-course-style.md` : socle oral, TTS, anti-hallucination et
  architecture pédagogique commune.
- `generation/structured-plan.md` : contrat de création du plan JSON.
- `generation/structured-section.md` : contrat de génération d'une section.
- `generation/budget-rewrite.md` : contrat de réduction/enrichissement IA quand
  un cours sort de son budget mots.
- `reviews/compliance-rules.json` : règles conformité #1 à #28, extraites du
  markdown historique sans perte volontaire.
- `reviews/humanization-rules.json` : règles humanisation #101 à #119, avec le
  scope actuel limité au polish oral.
- `reviews/compliance-review.md` : rôle du reviewer conformité.
- `reviews/humanization-polish.md` : rôle du reviewer humanisation légère.

La source active des reviews est JSON. Si ces fichiers sont absents, le service
retombe sur le markdown historique pour éviter un déploiement cassé.
