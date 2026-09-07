# Fuite d'abstraction : "cours", horaires et contraintes internes dans le script oral

**Date** : 2026-05-25
**Thématique** : problème | pédagogie | prompt engineering
**Statut** : résolu partiellement, à surveiller

## Contexte

La pipeline interne découpe une journée de formation en unités techniques :

- `course_number` ;
- blocs audio ;
- budgets mots ;
- étapes TTS ;
- horaires théoriques ;
- sections ;
- artefacts JSON.

Ces notions sont utiles pour organiser la génération et l'audio, mais elles ne
correspondent pas à ce que le formateur doit dire aux apprenants.

Dans la réalité pédagogique recherchée, le formateur anime une journée complète. Les
apprenants font parfois une pause, puis le formateur reprend avec un nouveau thème
ou un nouveau chapitre. Les "cours" sont donc des segments techniques, pas des
objets visibles pour l'apprenant.

## Problème / Question

Un script généré contenait des formulations du type :

- "le tout premier cours, celui qui nous occupe pour les trois quarts d'heure à
  venir" ;
- "sans vous soucier des horaires précis" ;
- "ce sont des sujets que nous allons traiter tout au long de la journée" avec une
  annonce trop mécanique du découpage.

Le problème n'est pas seulement stylistique. C'est une fuite d'abstraction : le texte
verbalise des contraintes internes de pipeline.

Le formateur ne doit pas savoir, ni dire, que l'architecture a prévu :

- 7 cours ;
- des horaires de 45 minutes ;
- des budgets de mots ;
- des blocs TTS ;
- des étapes de génération ;
- des templates slides ;
- des anchors ;
- des artefacts JSON.

## Impact pédagogique

Cette fuite casse l'illusion d'une vraie formation.

Un apprenant doit entendre :

- "on entre dans le premier grand thème" ;
- "on va travailler ce point en trois axes" ;
- "après la pause, on reprend avec..." ;
- "on va maintenant passer au chapitre suivant".

Il ne doit pas entendre :

- "cours 1" ;
- "les trois quarts d'heure à venir" ;
- "ne vous souciez pas des horaires" ;
- "template" ;
- "slide anchor" ;
- "section générée".

La formulation interne peut être correcte pour le code, mais incorrecte pour le
script oral.

## Cause probable

Le modèle reçoit des structures qui utilisent le vocabulaire technique :

- `course_title` ;
- `course_number` ;
- `opening` ;
- `parts` ;
- `word_budget` ;
- `slide_anchor`.

Si le prompt ne sépare pas explicitement le langage interne du langage oral, le LLM
reprend naturellement ces termes dans la narration.

Le risque augmente quand les prompts parlent de "cours", "horaires" ou "journée"
comme si ces mots avaient le même sens côté pipeline et côté apprenant.

## Décision finale

On conserve les noms techniques dans le code, mais on impose une couche de traduction
orale.

Correspondances retenues :

| Terme interne | Terme oral recommandé |
|---|---|
| course | thème, chapitre, partie, séquence |
| course_number | premier grand thème, point suivant |
| word_budget | invisible |
| audio_block | invisible |
| slide_anchor | invisible |
| template | invisible |
| plan JSON | invisible |
| horaires | invisible ou "dans la journée" si nécessaire |

Le formateur peut parler de progression, mais pas de mécanique.

## Formulation cible

Exemple de style attendu :

> Maintenant que le cadre général de la journée est posé, on peut entrer dans le
> premier grand thème. On va commencer par les bases de la communication à distance,
> et surtout par la posture professionnelle qui l'accompagne.

Cette formulation :

- situe l'apprenant ;
- annonce le thème ;
- reste naturelle ;
- ne parle pas de "cours numéro 1" ;
- ne mentionne aucun horaire ;
- ne révèle pas l'architecture interne.

## Règles à maintenir dans les prompts

- Ne jamais mentionner les horaires précis.
- Ne jamais dire "ce cours dure X minutes".
- Ne jamais dire "cours 1", "cours 2" dans le script oral.
- Ne jamais demander aux apprenants de ne pas se soucier des horaires.
- Ne jamais verbaliser les mots "slide", "anchor", "template", "JSON", "budget".
- Parler de thèmes, chapitres, points, axes et progression.
- Après une pause, reprendre naturellement : rappel bref, lien, nouveau thème.

## Références code

- `backend/prompts/generation/base-course-style.md`
- `backend/prompts/generation/structured-plan.md`
- `backend/prompts/generation/structured-section.md`
- `backend/prompts/reviews/plan-adherence-audit.md`
- `backend/prompts/reviews/plan-adherence-repair.md`
- `backend/prompts/reviews/ethical-micro-review.md`
- `backend/prompts/slides/README.md`
- `backend/services/content_generation_service.py`

## Leçons / Pour le mémoire

Une architecture IA peut être techniquement bien structurée tout en produisant une
expérience apprenant artificielle si ses concepts internes fuitent dans le texte.

La séparation "langage système" / "langage utilisateur" devient donc une contrainte
de qualité pédagogique. Le pipeline peut penser en JSON, blocs et budgets ; le
formateur doit parler en thèmes, cheminement et apprentissages.
