# Retour d'expérience — slides anchor-first, beat-first et curation IA après texte

**Date** : 2026-06-03
**Thématique** : décision | expérimentation | génération de contenu | slides
**Statut** : actif, décision d'architecture à ajuster

## Contexte

Le pipeline de génération de formation avait déjà une logique structurée :

- construire un plan pédagogique JSON ;
- définir des sections, objectifs, budgets et intentions pédagogiques ;
- générer le texte de cours ;
- produire ensuite les supports visuels associés.

L'objectif initial était légitime : éviter que les slides soient un simple résumé
opportuniste du texte final. Pour cela, le plan JSON avait commencé à porter des
`teaching_beats` et des `slide_anchor`, c'est-à-dire des moments pédagogiques
prévisibles, parfois associés à des templates de slides.

Cependant, les tests ont révélé un problème plus fin : plus on essayait de
verrouiller les slides trop tôt, plus on risquait de dégrader le texte oral.

Ce mémo documente les approches testées, ce qu'elles cherchaient à résoudre, pourquoi
elles ne suffisent pas, et la décision retenue pour la suite.

## Problème initial

Le problème observé n'était pas simplement :

> "Le modèle ne sait pas quel template de slide choisir."

Le vrai problème était plutôt :

> "Le texte final et les slides ne partent pas toujours du même découpage
> pédagogique."

Quand une section de cours contient plusieurs idées, plusieurs exemples et plusieurs
transitions, le modèle peut produire un bon texte oral mais laisser ensuite une
ambiguïté sur ce qui doit devenir une slide. À l'inverse, si on décide trop tôt que
telle partie doit absolument correspondre à telle slide, on peut contraindre la
narration et obtenir un texte moins naturel.

Il fallait donc trouver le bon niveau d'orchestration entre :

- le plan pédagogique ;
- le texte oral ;
- les intentions visuelles ;
- le catalogue réel de templates disponibles ;
- la possibilité de faire évoluer ce catalogue.

## Approche 1 — Laboratoire temporaire "passage vers slides"

### Principe

Une première idée a été de créer un laboratoire dans l'interface permettant de coller
un extrait de cours, de choisir un template visé et de prévisualiser une slide sans
relancer toute la pipeline.

L'objectif était de tester rapidement :

- le découpage d'un passage ;
- la compatibilité entre un passage et un template ;
- le rendu visuel généré ;
- la qualité des prompts de slides.

### Ce que cette approche résout

Cette approche est utile pour tester un template isolé. Elle permet de répondre à
des questions locales :

- est-ce que le template affiche correctement les données ?
- est-ce que le prompt de slide comprend le format attendu ?
- est-ce qu'un extrait court peut être transformé en visuel exploitable ?

### Pourquoi elle ne résout pas le problème principal

Cette approche teste un passage isolé, alors que le problème réel est systémique.

Elle ne dit pas :

- pourquoi ce passage devrait devenir une slide plutôt qu'un autre ;
- où cette slide se place dans le fil du cours ;
- si elle répète une slide précédente ;
- si elle casse la progression pédagogique ;
- si le texte source est le bon morceau à visualiser ;
- si le nombre de slides est cohérent pour la section.

Elle donne donc une bonne boucle de test de rendu, mais pas une bonne boucle
d'orchestration pédagogique.

### Conclusion

Le laboratoire "passage vers slides" est utile comme outil de debug ponctuel, mais il
ne doit pas devenir le coeur de la pipeline. Il a été retiré de l'interface principale
au profit d'un mode d'itération plus proche du vrai workflow.

## Approche 2 — Slides anchor-first dans le plan JSON

### Principe

La deuxième approche consistait à faire décider le plan JSON en amont :

- quels moments pédagogiques doivent exister ;
- lesquels peuvent porter une slide ;
- quel type de template est attendu ;
- quelle intention visuelle doit guider la génération.

Dans cette logique, les `teaching_beats` et `slide_anchor` sont définis avant la
génération du texte. Le texte est ensuite censé couvrir ces moments naturellement.

### Ce que cette approche améliore

Cette approche est meilleure qu'une analyse naïve du texte après coup, car elle
force la pipeline à réfléchir avant d'écrire.

Elle apporte :

- une intention pédagogique explicite ;
- un lien entre plan, texte et slides ;
- une meilleure diversité potentielle des templates ;
- une trace auditable dans le JSON ;
- une logique de support visuel pensée avant le rendu graphique.

### Limite observée

Le défaut vient du moment où l'on fige trop de choses.

Si le plan définit trop précisément les slides avant que le texte soit réellement
écrit, il travaille sur une intention, pas sur le texte final. Or le texte final peut
évoluer :

- une idée peut être mieux formulée ailleurs ;
- un exemple peut devenir plus visuel que celui prévu ;
- une transition peut être oralement nécessaire mais inutile en slide ;
- un passage prévu comme visuel peut finalement être trop abstrait ;
- le meilleur moment à visualiser peut apparaître pendant la rédaction.

Le plan JSON est donc bon pour dire : "voici les intentions pédagogiques importantes".
Il est moins fiable s'il devient le seul décideur définitif des slides.

### Conclusion

Le principe anchor-first reste utile, mais il doit être assoupli.

Les anchors doivent devenir des intentions candidates ou des contraintes de cadrage,
pas des décisions finales intouchables. Le plan donne la direction ; une couche après
texte doit vérifier ce qui mérite réellement une slide.

## Approche 3 — Génération beat-first, beat par beat

### Principe

L'idée suivante était de générer le cours dans l'ordre prévu, teaching beat par
teaching beat.

Le raisonnement était :

- un beat correspond à un moment pédagogique ;
- chaque beat peut avoir un contexte précédent et suivant ;
- chaque slide éventuelle est attachée à un beat ;
- le modèle n'a plus à deviner après coup quel texte correspond à quelle slide.

Sur le papier, cette approche semblait robuste :

```text
section
  -> beat 1 : texte + slide éventuelle
  -> beat 2 : texte sans slide
  -> beat 3 : texte + slide éventuelle
  -> beat 4 : synthèse orale
```

### Ce que cette approche cherchait à corriger

Elle répondait à une vraie faiblesse : quand une section entière est générée d'un
bloc, le texte peut être bon mais la correspondance avec les slides peut rester floue.

La génération beat-first voulait donc :

- réduire l'ambiguïté texte/slide ;
- garder un contexte local clair ;
- produire des transitions beat par beat ;
- éviter que les slides soient choisies trop tard ;
- rendre l'alignement plus auditable.

### Résultat observé

Les tests ont montré une forte dégradation de la qualité du texte.

Sur une introduction qui produisait auparavant un texte plutôt naturel et un support
visuel plus pertinent, la version beat-first a donné :

- seulement deux slides ;
- une introduction visuellement générique ;
- un texte oral moins dense ;
- une formulation plus mécanique ;
- des blocs qui ressemblaient à des mini-introductions ;
- une perte du style pédagogique qui fonctionnait auparavant.

### Pourquoi cela ne fonctionne pas

Le problème est que l'unité "beat" est bonne pour raisonner, mais pas forcément bonne
comme unité de génération principale.

Quand on demande au modèle de rédiger beat par beat, il a tendance à :

- redémarrer trop souvent ;
- répéter le contexte ;
- sur-expliciter les transitions ;
- traiter chaque beat comme un petit cours autonome ;
- perdre la respiration naturelle d'une section complète ;
- réduire la richesse du discours pour rester dans le cadre du beat.

En théorie, le beat donne de la précision. En pratique, il fragmente le flux oral.

Le texte de formation n'est pas seulement une somme de moments pédagogiques. C'est
une narration continue. La génération beat-first améliore la traçabilité locale mais
dégrade la qualité globale.

### Conclusion

La génération beat-first ne doit pas être le mode par défaut.

Elle peut éventuellement servir à certains cas très contrôlés, mais elle n'est pas
adaptée comme stratégie générale pour produire le texte oral principal.

Décision appliquée : désactivation par défaut via la variable
`FORMATION_STRUCTURED_BEAT_FIRST_ENABLED=0`.

## Approche 4 — Itération rapide depuis le plan verrouillé

### Principe

Une autre tentative a consisté à ajouter un bouton permettant de relancer depuis le
plan JSON verrouillé, sans refaire toute la pipeline depuis le RNCP ou la knowledge
base.

L'idée était de conserver :

- le plan JSON ;
- les intentions pédagogiques ;
- les anchors ;
- les paramètres déjà validés.

Puis de régénérer :

- le texte ;
- les reviews nécessaires ;
- les slides.

### Ce que cette approche améliore

Cette approche est utile pour éviter de tout recommencer.

Elle permet :

- de ne pas repasser par l'enrichissement RNCP ;
- de tester une évolution de génération de texte ;
- de comparer plus vite deux stratégies ;
- de garder le même plan comme base de comparaison.

### Limite observée

Le mode d'itération ne corrige pas une mauvaise stratégie de génération.

Si la logique beat-first produit un mauvais texte, relancer rapidement depuis le plan
ne fait que reproduire plus vite le même défaut. Le problème n'était donc pas
seulement le temps d'exécution ; c'était la position de la décision slide dans la
pipeline.

Autrement dit :

- accélérer l'itération est nécessaire ;
- mais accélérer une mauvaise hypothèse ne la rend pas meilleure.

### Conclusion

Le mode d'itération rapide est utile comme outil produit, mais il ne suffit pas comme
réponse architecturelle. Il doit être utilisé sur une stratégie de génération saine :
texte naturel d'abord, curation visuelle ensuite.

## Approche retenue — Texte naturel d'abord, curation IA des slides ensuite

### Principe

La décision retenue est de revenir à une génération de texte plus proche de la version
qui fonctionnait bien, puis d'ajouter une couche IA après coup dédiée aux slides.

La pipeline cible devient :

```text
plan pédagogique JSON
  -> génération du texte naturel par section
  -> reviews et calibrage du texte
  -> curation IA des moments visualisables
  -> sélection d'un template existant pour chaque vraie slide
  -> génération des slides
  -> backlog de templates idéaux à créer plus tard
```

### Rôle exact du plan JSON

Le plan JSON reste important, mais son rôle change légèrement.

Il ne doit plus être compris comme :

> "Voici exactement les slides définitives."

Il doit plutôt être compris comme :

> "Voici les intentions pédagogiques, les moments probables et le cadre à respecter."

Les `teaching_beats` et `slide_anchor` deviennent donc des signaux forts, pas des
ordres aveugles.

### Rôle exact de la couche IA après texte

La couche IA post-traitement lit le texte final et décide :

- quels passages méritent vraiment une slide ;
- quel objectif visuel chaque passage sert ;
- quel template existant est le meilleur compromis ;
- quels passages doivent rester uniquement oraux ;
- quels templates manquent dans le catalogue actuel.

Point essentiel : pendant la pipeline réelle, elle doit utiliser uniquement des
templates existants. Elle ne peut pas inventer un nouveau template et l'utiliser
immédiatement.

En revanche, elle peut produire un diagnostic du type :

```text
Slide générée avec le template existant : Reflection
Template idéal recommandé pour plus tard : Signal Gap
Pourquoi : le passage compare ce que le client voit et ce qu'il interprète.
Prompt de création : créer un template en deux colonnes montrant signal absent,
interprétation probable, risque relationnel et action corrective.
```

### Pourquoi cette approche est plus robuste

Cette solution sépare mieux les responsabilités :

- le plan structure la pédagogie ;
- le texte porte la qualité orale ;
- la curation IA choisit les meilleurs moments visuels ;
- le catalogue de templates garde le système dans un cadre réel ;
- le backlog de templates permet d'améliorer progressivement le design system.

Elle évite les deux échecs précédents :

- génération trop libre où les slides arrivent trop tard et sans intention ;
- génération trop contrainte où le texte se dégrade pour servir les slides.

## Décision finale

La version stable à conserver est :

- génération du texte par section, avec continuité orale ;
- teaching beats et anchors comme contexte pédagogique, non comme découpage dur ;
- désactivation du mode beat-first par défaut ;
- ajout futur d'une couche IA de curation des slides après texte ;
- obligation d'utiliser seulement les templates existants pendant la génération ;
- création d'un backlog de templates recommandés pour les améliorations futures.

## Rationale technique

Cette décision suit une logique d'ingénierie : une abstraction doit être placée au
niveau où elle réduit la complexité sans casser la qualité du système.

Le `teaching_beat` est une bonne abstraction pour planifier et auditer. Il n'est pas
une bonne unité de rédaction principale.

Le `slide_anchor` est une bonne abstraction pour exprimer une intention visuelle. Il
n'est pas toujours une bonne décision finale avant d'avoir le texte réel.

La curation IA après texte est donc le bon compromis :

- elle conserve le bénéfice du plan ;
- elle observe le matériau réellement produit ;
- elle choisit dans un catalogue concret ;
- elle documente les manques du catalogue ;
- elle permet d'itérer sans détériorer le texte oral.

## Références code et commits

Références principales :

- `backend/services/content_generation_service.py`
- `backend/services/script_slide_generation_service.py`
- `backend/routes/formation_routes.py`
- `frontend/src/pages/FormationPipeline.jsx`
- `backend/prompts/generation/structured-plan.md`
- `backend/prompts/generation/structured-section.md`
- `backend/prompts/slides/template-catalog.json`

Commits liés à l'expérimentation :

- `e317e3e` — ajout du laboratoire temporaire passage vers slides ;
- `c3b8b79` — expérimentation de génération structurée beat-first ;
- `e13f0e3` — remplacement du laboratoire par l'itération depuis plan verrouillé ;
- `0057632` — ajout du mode d'itération rapide texte + slides ;
- `d6f2f87` — désactivation par défaut du beat-first instable.

## Leçons pour le mémoire

Cette séquence montre une démarche d'ingénieur plutôt qu'une simple intuition produit.

Hypothèse initiale :

> Plus le plan connaît les slides tôt, meilleur sera l'alignement.

Résultat :

> L'alignement s'améliore localement, mais la qualité orale peut se dégrader si la
> génération devient trop fragmentée.

Hypothèse corrigée :

> Le plan doit cadrer les intentions, mais la sélection finale des slides doit
> observer le texte réellement produit.

Le point important à retenir est que la bonne architecture n'est pas celle qui met
le maximum d'IA partout. C'est celle qui place chaque décision au bon moment :

- avant le texte pour cadrer la pédagogie ;
- pendant le texte pour préserver la continuité orale ;
- après le texte pour sélectionner les meilleurs supports visuels ;
- après les slides pour identifier les templates manquants.

Cette démarche justifie le passage d'une stratégie "anchor-first stricte" à une
stratégie "anchor-guided + curation IA".
