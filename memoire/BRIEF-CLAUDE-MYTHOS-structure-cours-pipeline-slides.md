# Brief pour Claude Mythos - structure ecrite des cours et pipeline slides

## Role attendu

Tu es consulte comme **Claude Mythos** pour donner un avis critique, creatif et concret sur une pipeline de generation de cours RNCP avec slides pedagogiques.

Je ne veux pas une reecriture vague du projet. Je veux que tu identifies ce qui ameliorerait vraiment :

1. la structure ecrite du cours en amont ;
2. le rendu final des slides ;
3. la selection des bons templates parmi un catalogue ferme de 21 slides sources ;
4. la pipeline, sans casser ce qui marche deja.

Reponds en francais, de maniere actionnable, avec priorites.

## Contexte produit

Le projet s'appelle **Le Socrate**.

C'est une plateforme de formation RNCP qui genere des cours audio longs, structures et reutilisables. Les cours sont destines a des apprenants adultes en formation professionnelle. Le ton doit rester :

- clair ;
- professionnel ;
- oral ;
- pedagogique ;
- sobre ;
- non marketing ;
- non scolaire artificiel.

Le rendu final attendu n'est pas un simple texte lu par une IA. Il doit ressembler a un vrai cours anime : progression logique, transitions naturelles, exemples, definitions, conseils, rappels, moments forts et slides visuelles coherentes.

## Pipeline actuelle, version simplifiee

La pipeline fonctionne globalement comme ceci :

1. creation d'un plan JSON de journee ;
2. decoupage en 7 cours ;
3. decoupage de chaque cours en parties ;
4. ajout de `teaching_beats` internes pour guider l'ecriture ;
5. certains `teaching_beats` peuvent contenir un `slide_anchor` ;
6. generation du texte oral final section par section ;
7. a la fin, decoupage/alignment texte -> slides ;
8. choix du template de slide parmi les 21 templates officiels ;
9. generation des donnees de slide ;
10. rendu frontend.

Point important : **la separation finale du texte est actuellement plutot bonne**. Le probleme principal observe est plutot le choix du template.

## Source de verite slides

Decision produit recente : les seules slides autorisees sont les **21 slides visibles dans `/test-slides`**.

Ces 21 slides sont considerees comme les sources de verite officielles. Les anciens templates, templates restaures ou variantes experimentales ne doivent plus servir en production.

Le catalogue officiel est :

```text
backend/prompts/slides/template-catalog.json
```

Les templates officiels sont :

```text
welcome
program_year
day_program_7_steps
chapter_opener
reflection
definition
comparison
warning
casestudy
steps
recap
pause
qa
quotable
tip
situations
flow
story
analogy
framework
opinion
```

## Fichiers importants a lire

Si tu as acces au repo, lis prioritairement :

```text
backend/prompts/slides/template-catalog.json
backend/prompts/generation/structured-plan.md
backend/prompts/generation/structured-section.md
backend/prompts/generation/base-course-style.md
backend/services/script_slide_generation_service.py
```

Dans `script_slide_generation_service.py`, regarde surtout la phase finale de curation/alignment des slides, notamment la logique autour de :

```text
section_slide_alignment
planned_template_type
template_type
_prompt_for_blocks
```

## Probleme observe

La pipeline arrive souvent a bien separer le texte en fenetres coherentes, mais elle attribue parfois le mauvais template.

Exemples observes :

- un passage en **trois piliers** ou **trois postures** a ete classe en `recap`, alors qu'il devrait plutot etre `situations` ;
- un passage avec une **phrase cle / maxime a ancrer** devrait etre `quotable`, parfois avec une declinaison narrative en `story` ;
- un **cas unique qui amene un conseil** ne doit pas etre `casestudy`, mais plutot `tip` ou `story` selon la fonction pedagogique ;
- `casestudy` doit etre reserve a **2 ou 3 cas comparables** ;
- une opposition comme **synchrone / asynchrone**, **telephone / courriel**, **immediat / differe**, **rapidite / exhaustivite** devrait etre `comparison` ;
- `recap` doit rester une vraie synthese apres developpement, pas un template fourre-tout.

## Hypothese actuelle

Le probleme ne vient pas seulement du catalogue. Il vient probablement du fait que le modele confond :

- le **theme** du passage ;
- avec la **forme pedagogique dominante** du passage.

Exemple :

Un passage peut parler d'un cas client. Mais si ce cas unique sert a amener une bonne pratique, la forme pedagogique n'est pas "case study". C'est un conseil : `tip`.

Autre exemple :

Un passage peut contenir trois elements. Mais si ces trois elements sont une nouvelle structure conceptuelle, ce n'est pas un recap. C'est une triade structurante : `situations`.

## Contrainte importante

Je ne veux pas casser la bonne separation texte actuelle.

L'idee produit est plutot :

```text
Le plan decide combien de slides et ou elles tombent.
Le texte final decide quel template exact utiliser.
```

Donc pendant la derniere curation :

- on garde le meme nombre de slides prevu pour une fenetre alignee ;
- on garde le rattachement au bon passage de texte ;
- mais le LLM doit pouvoir changer librement de template parmi les 21, selon le texte reel.

## Ce que je veux que tu analyses

### 1. Structure ecrite du cours

Comment structurer l'ecriture du cours pour que le texte soit naturellement plus facile a transformer en bonnes slides ?

Questions :

- Faut-il renforcer les `teaching_beats` ?
- Faut-il imposer qu'un beat slideable ait une seule fonction dominante ?
- Faut-il ajouter une notion de "forme pedagogique" avant le template ?
- Faut-il demander au texte oral de produire des signaux plus clairs, sans dire "slide" ou "template" a l'apprenant ?
- Faut-il modifier `structured-section.md` pour mieux separer definition, exemple, conseil, maxime, comparaison, recap ?

### 2. Selection de templates

Comment ameliorer le choix du template parmi les 21 ?

Questions :

- Faut-il ajouter une couche intermediaire `pedagogical_shape` ?
- Faut-il choisir d'abord une forme pedagogique, puis seulement ensuite un template ?
- Quelles formes pedagogiques proposerais-tu ?
- Comment eviter les confusions frequentes :
  - `recap` vs `situations`
  - `casestudy` vs `tip`
  - `casestudy` vs `story`
  - `reflection` vs `quotable`
  - `steps` vs `flow`
  - `comparison` vs `definition`
  - `framework` vs `situations`

### 3. Catalogue des templates

Le fichier `template-catalog.json` contient deja :

- `use_cases`
- `visual_role`
- `use_when`
- `avoid_when`
- `requires`

Question :

Faut-il ajouter d'autres champs pour mieux guider le LLM ?

Exemples possibles :

- `pedagogical_shape`
- `positive_examples`
- `negative_examples`
- `strong_signals`
- `weak_signals`
- `confusable_with`
- `decision_rule`
- `minimum_evidence`

Dis-moi ce qui serait vraiment utile et ce qui serait du bruit.

### 4. Pipeline

Comment ameliorer la pipeline sans la rendre plus fragile ?

Questions :

- Faut-il ajouter un mini-classifieur avant la generation de slide ?
- Faut-il demander au LLM de justifier le template choisi ?
- Faut-il stocker `rejected_templates` pour debug ?
- Faut-il afficher dans l'UI pourquoi une slide a ete choisie ?
- Faut-il brancher les edits faits dans `/test-slides` vers le catalogue officiel ?
- Faut-il garder les regles dans JSON, dans prompt markdown, ou les deux ?

## Format de reponse souhaite

Reponds avec :

1. **Diagnostic court** : ce qui bloque vraiment aujourd'hui.
2. **Priorites d'amelioration** : P0, P1, P2.
3. **Modifications recommandees dans les prompts** :
   - `structured-plan.md`
   - `structured-section.md`
   - prompt final de curation slides dans `script_slide_generation_service.py`
4. **Modifications recommandees dans `template-catalog.json`**.
5. **Eventuelles modifications UI** pour aider l'iteration humaine.
6. **Risques a eviter**.
7. **Proposition concrete de schema** si tu recommandes `pedagogical_shape`.

## Exigence de precision

Ne propose pas "ameliorer le prompt" de maniere generale.

Je veux des recommandations du type :

```text
Ajouter un champ `pedagogical_shape` avec les valeurs suivantes...
Ajouter dans `structured-section.md` la contrainte suivante...
Ajouter dans le catalogue `positive_examples` / `negative_examples` seulement pour les templates confondus...
Dans la curation finale, demander au modele de renvoyer `template_decision_reason` et `rejected_templates`...
```

## Point de vigilance

Ne recommande pas d'ajouter de nouveaux templates sauf si c'est absolument necessaire.

La decision actuelle est de rester sur les 21 sources officielles.

Le but n'est pas de multiplier les formes visuelles, mais de mieux choisir parmi celles qui existent.

