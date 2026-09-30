# Pipeline contenu auditable — JSON maître, prompts modulaires et slides anchor-first

**Date** : 2026-05-25
**Thématique** : architecture | décision | solution
**Statut** : actif

## Contexte

La génération de contenu formation a évolué d'un gros prompt historique vers une
pipeline structurée : plan JSON, génération par sections, reviews ciblées, artefacts,
slides et audio.

Le besoin métier s'est clarifié sur plusieurs points importants :

- les "cours" nommés dans l'architecture ne doivent pas être verbalisés comme des
  cours horaires rigides par le formateur ;
- une journée de formation doit être racontée comme une succession naturelle de
  thèmes, parties ou chapitres, avec reprise après pause quand nécessaire ;
- le formateur ne doit pas mentionner les horaires internes, les budgets de mots,
  les blocs audio, les templates de slides ou les contraintes techniques ;
- les PowerPoint doivent être cohérents avec le texte produit, sans être générés à
  partir d'une simple analyse opportuniste du script final ;
- la conformité éthique doit être contrôlable précisément, passage par passage ;
- le frontend doit permettre de cliquer sur chaque étape de la pipeline et de voir
  concrètement ce qu'elle a produit, corrigé ou validé.

## Problème / Question

La question centrale était :

Comment garder une génération rapide et automatisée, tout en donnant un contrôle
fin sur la qualité pédagogique, la conformité, les slides et les transformations
successives du texte ?

Avant cette refonte, plusieurs limites rendaient le système trop fragile :

- `prompts-generaux-contenu-formation.md` mélangeait encore l'ancien workflow,
  les règles de style, la conformité, le TTS et la pédagogie dans un gros fichier ;
- les règles étaient en partie dans le markdown, en partie dans le code, en partie
  dans les prompts de review ;
- le frontend montrait des résultats, mais pas toujours la trace exacte permettant
  de savoir à quelle étape un problème avait été introduit ;
- les slides risquaient d'être produites après coup à partir du texte, donc avec un
  alignement incertain ;
- une review conformité trop globale pouvait modifier trop large ou rater des
  violations locales ;
- le vocabulaire interne "cours 1 / trois quarts d'heure / horaires" pouvait fuiter
  dans le discours du formateur, alors que ces données ne sont que des contraintes
  d'architecture.

## Décisions structurantes

### 1. Le JSON devient le contrat pédagogique

Le plan JSON n'est plus seulement un plan de génération. Il devient le contrat
pédagogique qui pilote :

- les journées ;
- les grands thèmes ou chapitres ;
- les parties A/B/C d'un thème ;
- les objectifs ;
- les budgets ;
- les transitions ;
- les moments pédagogiques visualisables ;
- les `teaching_beats` et `slide_anchor` nécessaires aux slides.

Le texte est ensuite généré à partir de ce contrat. Cela évite que le cours parte
dans une direction et que les slides essaient de le rattraper après coup.

### 2. Séparer architecture interne et parole du formateur

La pipeline peut continuer à parler de `course`, `folder`, `section`, `budget`,
`audio_block` ou `slide_anchor` dans le code.

Mais le texte final doit parler naturellement :

- de journée ;
- de thème ;
- de partie ;
- de point ;
- de chapitre ;
- de reprise après pause ;
- de fil conducteur.

Règle importante : le formateur ne doit pas dire qu'il connaît les horaires précis,
ni parler de "trois quarts d'heure", ni demander aux apprenants de ne pas se soucier
des horaires. Les horaires, budgets et blocs sont des contraintes invisibles.

Exemple de formulation cible :

> Maintenant que le cadre général de la journée est posé, on peut entrer dans le
> premier grand thème. On va commencer par les bases de la communication à distance,
> et surtout par la posture professionnelle qui l'accompagne.

Le ton attendu est naturel, pédagogique, oral, sans annoncer mécaniquement un
"cours numéro 1".

### 3. Remplacer le gros prompt par des prompts modulaires

Les prompts ont été découpés par rôle :

- `generation/base-course-style.md` : style général du cours ;
- `generation/structured-plan.md` : création du plan JSON ;
- `generation/structured-section.md` : génération d'une section depuis le plan ;
- `generation/budget-rewrite.md` : ajustement de volume ;
- `reviews/compliance-rules.json` : règles conformité structurées ;
- `reviews/humanization-rules.json` : règles humanisation structurées ;
- `reviews/ethical-micro-review.md` : review éthique locale ;
- `reviews/plan-adherence-audit.md` : audit d'adhérence au plan ;
- `reviews/plan-adherence-repair.md` : réparation ciblée ;
- `slides/template-catalog.json` : catalogue de templates slides ;
- `slides/README.md` : logique anchor-first.

Le markdown historique reste un fallback de contexte, mais il ne doit plus être la
source unique de vérité.

### 4. Persister des artefacts par étape

La pipeline écrit des fichiers intermédiaires pour rendre chaque état inspectable :

- `content-plan.json` : plan verrouillé ;
- `content-draft-sections.json` : sections brutes générées ;
- `content-course-scripts.json` : scripts assemblés avant reviews ;
- `content-ethical-micro-review.json` : micro-corrections éthiques avant/après ;
- `content-quality-reviews.json` : audits qualité intermédiaires ;
- `content-reviewed-scripts.json` : scripts après reviews ;
- `content-audio-plan.json` : texte planifié pour l'audio ;
- artefacts slides : anchors et decks générés.

L'intérêt n'est pas d'avoir "plus de JSON". L'intérêt est d'avoir une chaîne de
preuves :

- si le plan est mauvais, le problème vient de la planification ;
- si le plan est bon mais la section dérape, le problème vient de la génération ;
- si la section est bonne mais le script final change, le problème vient de
  l'assemblage ou du calibrage ;
- si la review dégrade le style, on le voit en comparant avant/après ;
- si l'audio reçoit un texte différent, on le voit dans l'audio-plan.

### 5. Ajouter une review d'adhérence au plan

La conformité finale ne doit pas porter seule toute la qualité. Une review dédiée
vérifie d'abord :

- que les parties prévues sont bien traitées ;
- que l'ordre du plan est respecté ;
- que l'introduction ne se répète pas ;
- que la reprise après pause est naturelle ;
- que la conclusion ferme réellement la partie ;
- que les `teaching_beats` prévus sont couverts ;
- qu'aucune mécanique interne n'est verbalisée.

Cette review intervient avant l'humanisation orale et la conformité finale.

### 6. Faire la micro-conformité éthique sur petites portions

La conformité éthique stricte doit être appliquée tôt, section par section, sur des
portions courtes. Cela réduit trois risques :

- dilution d'attention du LLM sur un texte trop long ;
- correction trop large qui abîme le cours ;
- difficulté à savoir quel passage a été jugé problématique.

La micro-review éthique cible les règles #1 à #16, avec un artefact détaillé :

- texte original de la section ;
- texte final ;
- règle concernée ;
- passage problématique ;
- correction proposée ;
- statut du patch ;
- raison de rejet si le patch n'a pas été appliqué.

### 7. Générer les slides en anchor-first

Deux options étaient possibles :

1. générer le texte, puis analyser ce qui revient le plus souvent pour créer les
   slides ;
2. demander au plan JSON de décider les moments pédagogiques à visualiser, puis
   générer le texte et les slides autour de ces anchors.

La deuxième option a été retenue.

Raison : les slides doivent accompagner l'intention pédagogique, pas seulement
résumer a posteriori le texte. Le JSON peut imposer des moments visualisables :

- exemple ;
- conseil ;
- piège ;
- checklist ;
- comparaison ;
- schéma en étapes ;
- histoire courte ;
- méthode ;
- définition ;
- cas pratique.

Le texte doit couvrir ces moments naturellement, sans dire "sur cette slide" ou
"dans ce template". Les slides sont ensuite générées depuis les anchors validés.

### 8. Rendre la pipeline visuelle cliquable et auditable

La roadmap frontend ne doit pas seulement afficher "OK" ou "À venir". Chaque étape
doit devenir inspectable.

Décision UI :

- chaque carte de la roadmap est cliquable ;
- une modale affiche les événements pipeline liés ;
- les artefacts JSON liés à l'étape sont chargés ;
- les rapports de review sont affichés quand ils existent ;
- les corrections sont affichées en avant/après quand c'est possible.

Cas clé : étape 9, micro-conformité éthique.

La modale doit afficher :

- à gauche, le texte original avec les passages problématiques surlignés en rouge ;
- à droite, le texte corrigé avec les remplacements surlignés en bleu ;
- la règle éthique concernée ;
- la raison de la correction.

Cela transforme la pipeline en outil de contrôle, pas seulement en outil d'exécution.

## Workflow cible

Le trajet logique retenu est :

1. initialisation RNCP et plateforme ;
2. téléchargement REAC ;
3. enrichissement knowledge base ;
4. programme global ;
5. programmes journée ;
6. plan JSON verrouillé ;
7. teaching beats et anchors slides ;
8. génération par section ;
9. micro-conformité éthique ;
10. artefacts structurés ;
11. calibrage budget texte ;
12. sécurité volume ;
13. adhérence au plan ;
14. humanisation orale ;
15. calibrage blocs audio ;
16. conformité finale ;
17. budget final, Word 2 et audio-plan ;
18. slides anchor-first ;
19. audio optionnel ;
20. publication / module durable.

## Rationale technique

### Pourquoi ne pas simplement analyser le texte pour créer les slides ?

Analyser le texte final peut repérer des thèmes fréquents, mais ne garantit pas que
les slides couvrent les moments pédagogiques importants. Un point peut être crucial
même s'il n'est dit qu'une seule fois.

Le plan JSON permet de décider avant génération :

- ce qui doit être montré ;
- pourquoi ça doit être montré ;
- avec quel type de template ;
- à quel moment du raisonnement ;
- avec quelle relation au texte.

L'analyse après coup peut rester utile comme vérification, mais pas comme moteur
principal.

### Pourquoi ne pas faire la conformité seulement à la fin ?

Une conformité finale est nécessaire, mais insuffisante. À la fin, le texte est long,
assemblé, calibré et humanisé. Une correction éthique tardive peut devenir trop
large ou difficile à attribuer.

La micro-conformité locale permet de corriger tôt les petits problèmes sans casser
l'ensemble. La conformité finale reste ensuite responsable des hallucinations, du
TTS, de l'architecture orale et des contrôles globaux.

### Pourquoi garder les artefacts si le frontend montre déjà des choses ?

Le frontend montre l'état visible. Les artefacts montrent l'historique de fabrication.

Cette différence est centrale :

- l'interface permet de constater qu'un cours est mauvais ;
- les artefacts permettent de savoir quand il est devenu mauvais.

Sans artefacts, on debugge à l'impression. Avec artefacts, on compare des états
successifs.

## Implémentation actuelle

Principaux changements réalisés :

- modularisation des prompts ;
- extraction des règles conformité et humanisation en JSON ;
- création de `backend/services/content_pipeline/` ;
- cache de chargement des prompts ;
- validation serveur du plan JSON ;
- persistance des artefacts structurés ;
- review d'adhérence au plan ;
- génération parallèle des contenus structurés ;
- ajout des `teaching_beats` et `slide_anchor` ;
- micro-review éthique locale ;
- roadmap auto-pilot frontend complète ;
- modales d'audit cliquables par étape ;
- endpoint API de lecture des artefacts.

Commits associés :

- `5ecc320` — modularisation des prompts de génération et review ;
- `52d6b10` — persistance des artefacts structurés ;
- `7b5e934` — refactor des helpers `content_pipeline` ;
- `c71691a` — review d'adhérence au plan ;
- `460bac0` — parallélisation de la génération structurée ;
- `822b9e8` — roadmap visuelle complète de la pipeline ;
- `e48d2b1` — modales d'audit cliquables sur les étapes.

## Références code

- `backend/prompts/README.md`
- `backend/prompts/generation/base-course-style.md`
- `backend/prompts/generation/structured-plan.md`
- `backend/prompts/generation/structured-section.md`
- `backend/prompts/reviews/compliance-rules.json`
- `backend/prompts/reviews/humanization-rules.json`
- `backend/prompts/reviews/ethical-micro-review.md`
- `backend/prompts/reviews/plan-adherence-audit.md`
- `backend/prompts/slides/template-catalog.json`
- `backend/services/content_generation_service.py`
- `backend/services/content_pipeline/`
- `backend/routes/formation_routes.py`
- `frontend/src/pages/FormationPipeline.jsx`

## Points à surveiller

- enrichir fortement le catalogue de templates slides pour couvrir les formations
  métiers ;
- permettre à terme de valider, rejeter ou modifier les patches directement depuis
  la modale d'audit ;
- éviter toute fuite de vocabulaire interne dans le script oral : horaires, budget,
  slide, anchor, template, JSON ;
- vérifier que les introductions de journée ne sont pas répétées entre opening de
  journée et premier thème ;
- suivre les temps de génération après parallélisation pour ajuster les limites de
  concurrence API ;
- versionner les règles de conformité et d'humanisation pour pouvoir relire un ancien
  résultat avec les règles qui étaient actives à ce moment-là.

## Leçons / Pour le mémoire

Cette refonte illustre une évolution importante : on ne cherche plus seulement à
générer du contenu, mais à construire une chaîne de production auditable.

Le JSON n'est pas une formalité technique. Il devient le support de la gouvernance
pédagogique : il décide du plan, des moments visuels, des budgets et des contrôles.

Les artefacts transforment une génération IA opaque en pipeline vérifiable. Chaque
étape produit une preuve, ce qui permet de corriger localement au lieu de relancer
ou modifier aveuglément toute la chaîne.

Enfin, les slides ne sont pas traitées comme un export secondaire. Elles deviennent
un prolongement du plan pédagogique, grâce aux anchors décidés avant la génération
du texte.
