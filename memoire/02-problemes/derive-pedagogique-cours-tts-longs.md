# Dérive pédagogique des cours TTS longs

**Date** : 2026-05-25
**Thématique** : problème | pédagogie | génération IA
**Statut** : résolu

## Contexte

Le projet Le Socrate ne génère pas de simples textes à lire. Il doit produire une
illusion crédible de vraie formation professionnelle diffusée en direct : accueil,
progression, reprises, transitions, conclusions, questions-réponses et continuité
sur plusieurs journées.

L'analyse des premiers résultats de pipeline a montré que le contenu généré pouvait
être riche et oral, mais manquer d'architecture visible. Le cas le plus représentatif
était le premier cours de la journée, puis le début du cours 2.

## Problème / Question

Le problème central était la charge cognitive de l'apprenant.

Dans le script initial, l'apprenant ne savait pas clairement :

- où il était dans la formation ;
- ce qu'il était en train d'apprendre ;
- pourquoi il l'apprenait ;
- ce qui allait venir ensuite ;
- comment le cours était structuré ;
- où la partie actuelle se situait dans la journée et dans le parcours global.

Le texte ressemblait parfois à un formateur inspiré qui parle longtemps, mais sans
carte mentale explicite. Cela rend le cours fatigant, même quand les idées sont
bonnes.

## Symptômes observés

### Cours 1 qui démarre trop vite

Le cours 1 commençait directement par des idées générales :

- importance de la relation client ;
- rôle de la voix de l'entreprise ;
- exemple de client mécontent ;
- métaphores et storytelling.

Ces éléments ne sont pas mauvais en soi. Le problème est qu'ils apparaissaient avant
le cadrage pédagogique. L'apprenant recevait des exemples avant de savoir :

- le thème exact du cours ;
- ce qu'il allait apprendre aujourd'hui ;
- les grands thèmes de la journée ;
- le programme annuel en version synthétique ;
- les objectifs finaux ;
- le plan de la séance.

### Transitions invisibles

Le texte passait d'une notion à l'autre sans signal clair :

- posture d'accueil ;
- sourire vocal ;
- scripts ;
- adaptation langagière ;
- email ;
- profils clients.

Sans formules de transition explicites, le cerveau ne range pas les connaissances.
La progression existe peut-être dans le prompt ou le planning officiel, mais elle
n'est pas audible dans le cours.

### Tunnels émotionnels trop longs

Certains passages enchaînaient plusieurs minutes de métaphores, exemples,
reformulations et encouragements sans nouvelle idée identifiable. L'effet produit
était : "ça parle beaucoup, mais ça avance peu".

Cette dérive est typique des générations longues : le modèle maintient un ton, mais
perd la fonction pédagogique de chaque développement.

### Conclusion cassée et contenu après Q/R

Un autre symptôme fort était la fin du cours 1 : après une conclusion correcte qui
annonçait les questions-réponses, le modèle ajoutait plusieurs paragraphes de
mini-synthèse répétée.

Le texte contenait plusieurs fois des blocs du type "Prenons quelques secondes pour
ancrer cette idée". Le problème n'était pas seulement la répétition : le contenu
arrivait après la conclusion, donc il cassait la structure de l'expérience.

### Cours 2 qui finit le cours 1

Le début du cours 2 reprenait en réalité la fin du cours 1 :

- rappel des trois points du cours précédent ;
- image de conclusion ;
- annonce Q/R ;
- puis seulement ensuite introduction du nouveau thème.

Cela révélait une confusion structurelle classique :

- où finit un cours ;
- où commence le suivant ;
- ce qui appartient à une pause ou à une Q/R ;
- ce qui relève du chapitre précédent ;
- ce qui relève du nouveau chapitre.

## Options envisagées

### Option A — Corriger seulement le prompt général

Avantage : simple.

Limite : trop fragile. Un prompt général peut rappeler des principes, mais il ne
force pas suffisamment une architecture cours par cours. Le modèle peut encore
improviser un discours inspirant.

### Option B — Ajouter des prompts spécifiques par cours seulement

Avantage : permet d'adapter le cours 1, le cours 2, etc.

Limite : si le plan n'est pas verrouillé et auditable, le prompt spécifique devient
une consigne de plus dans un contexte long. Il ne garantit pas le respect du budget,
des parties, des conclusions ou des transitions.

### Option C — Structurer la pipeline autour d'un plan JSON verrouillé

Avantage : le plan devient le contrat pédagogique. Le texte final doit suivre une
structure explicite : opening, parties, conclusion, et conclusion de journée si
nécessaire.

Limite : demande une refonte plus large de la pipeline, des artefacts et des reviews.

## Décision finale

La solution retenue est une pipeline structurée :

1. créer un plan JSON par journée ;
2. verrouiller le plan après validation ;
3. générer chaque cours par sections ;
4. imposer 2 à 4 parties par cours ;
5. réserver un budget mots par section ;
6. produire une vraie conclusion avant Q/R ;
7. arrêter strictement le cours après l'annonce Q/R ;
8. ajouter une review dédiée d'adhérence au plan ;
9. puis seulement humaniser et vérifier la conformité.

## Rationale technique

Le problème n'était pas un manque de style, mais un manque de structure vérifiable.

La clarté devient donc une contrainte aussi importante que le contenu. Le modèle ne
doit pas seulement "bien parler". Il doit aider l'apprenant à savoir :

- où il est ;
- ce qu'il vient de voir ;
- ce qu'il voit maintenant ;
- ce qu'il verra ensuite ;
- pourquoi cette partie sert le métier.

Cette contrainte est particulièrement forte pour une formation longue, car la fatigue
cognitive s'accumule. Un cours audio de 45 minutes sans architecture visible devient
difficile à suivre, même si chaque paragraphe isolé est correct.

## Références code

- `backend/services/content_generation_service.py`
- `backend/services/content_pipeline/`
- `backend/prompts/generation/structured-plan.md`
- `backend/prompts/generation/structured-section.md`
- `backend/prompts/reviews/plan-adherence-audit.md`
- `backend/prompts/reviews/plan-adherence-repair.md`
- Commits liés :
  - `8f3a0d7` — Use structured plans in content reviews
  - `52d6b10` — Persist structured pipeline artifacts
  - `c71691a` — Add plan adherence quality review

## Leçons / Pour le mémoire

La génération pédagogique longue ne se résume pas à produire du texte oral. Elle
nécessite une réalisation pédagogique :

- architecture visible ;
- rythme cognitif ;
- transitions explicites ;
- conclusions propres ;
- continuité entre cours ;
- séparation stricte entre contenu, pause et Q/R.

La qualité perçue d'une formation IA se joue donc beaucoup dans cette architecture
invisible. Le modèle peut produire du bon contenu, mais sans structure imposée il
retombe facilement dans un discours fluide, long et difficile à mémoriser.

