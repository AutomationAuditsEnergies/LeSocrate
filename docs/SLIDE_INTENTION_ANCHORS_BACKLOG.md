# Evolution future : une intention pedagogique = une slide

Ce document met de cote l'idee discutee pendant le travail sur la journee 1 : mieux controler le decoupage du script oral en slides en partant des intentions pedagogiques, plutot qu'en partant uniquement de blocs de texte.

Cette evolution n'est pas a appliquer maintenant. On continue d'abord a travailler les slides une par une, en validant les templates Claude Design et le rendu final. Cette note servira de reference quand on reviendra sur la generation automatique a la fin.

## Idee de depart

Aujourd'hui, un passage audio peut etre rattache a une seule slide meme s'il contient plusieurs moments pedagogiques distincts.

Exemple :

- installer un cas fictif ;
- montrer le decalage entre l'intention du conseiller et la perception du client ;
- formuler la regle a retenir.

Ces trois moments peuvent appartenir au meme passage oral, mais ils ne demandent pas forcement la meme visualisation. L'idee est donc de poser une regle simple :

> Une slide doit porter une intention pedagogique claire, pas seulement un morceau de texte.

Cela ne veut pas dire creer plus de slides partout. Cela veut dire mieux choisir quand un passage merite d'etre subdivise.

## Pourquoi c'est interessant

Cette approche permettrait de produire des slides plus utiles pour les apprenants :

- chaque slide aurait une fonction precise ;
- le visuel serait moins decoratif et plus pedagogique ;
- les cas, comparaisons, definitions, transitions et recapitulatif seraient mieux separes ;
- Claude Design pourrait travailler un template par intention au lieu de recevoir une slide trop chargee ;
- le script oral resterait fluide, pendant que les slides deviendraient plus lisibles.

Exemple pour le passage sur le client dans le brouillard :

1. Slide `CAS TERRAIN`
   Montrer la situation : un client appelle pour une coupure de connexion.

2. Slide `FAIT vs PERCU`
   Comparer ce que fait le conseiller et ce que le client interprete.

3. Slide `REGLE CLE`
   Ancrer l'idee : a distance, vous n'etes jamais neutre.

## Point important : ne pas rallonger le script oral

Le risque principal serait de croire qu'ajouter des slides signifie ajouter du texte oral. Ce n'est pas l'objectif.

La bonne regle serait :

> Un `slide_anchor` ne cree pas de texte audio supplementaire. Il indique seulement qu'un passage deja present merite une visualisation.

Donc le budget de mots doit rester pilote par le contenu oral, pas par le nombre de slides.

Il faut separer trois niveaux :

- le script oral : ce qui sera dit par le formateur ;
- les intentions pedagogiques : ce que chaque moment doit faire comprendre ;
- le contenu visible de slide : ce que l'apprenant voit a l'ecran.

Le controle du budget de mots doit continuer a s'appliquer au script oral. Les slides doivent avoir leur propre controle de concision : titre court, peu de texte visible, message clair.

## Ce qu'il faudrait modifier plus tard

### 1. Le plan structure

Le prompt de plan devrait rendre explicite :

- un `teaching_beat` = une seule intention pedagogique verifiable ;
- si un passage contient un cas, une comparaison et une regle, il faut creer plusieurs beats ;
- un beat peut avoir un `slide_anchor` si une visualisation aide vraiment ;
- il ne faut pas creer une slide pour chaque phrase ;
- il ne faut pas gonfler le texte oral pour justifier une slide.

### 2. Les slide anchors

Les `slide_anchor` devraient decrire :

- l'intention de la slide ;
- le template conseille ;
- le passage oral source ;
- le message visible principal ;
- la raison pedagogique de la slide.

L'anchor doit etre une instruction de visualisation, pas une nouvelle section de cours.

### 3. Le catalogue de templates

Le catalogue devra contenir les templates exacts disponibles dans le deck React, par exemple :

- `welcome`
- `day_program`
- `chapter_opener`
- `casestudy`
- `comparison`
- `beforeafter`
- `reflection`
- `recap`
- `tip`
- `warning`
- `transition`

Il faudra eviter les aliases trop flous. Si on demande une slide de comparaison, elle ne doit pas retomber automatiquement sur un simple cas terrain si le rendu attendu est different.

### 4. Le service de generation de slides

Le service qui transforme le script en slides devra accepter les nouveaux templates.

Point a verifier plus tard :

- les templates autorises dans le prompt ;
- les aliases de templates ;
- la normalisation des donnees ;
- la limite du nombre de slides par bloc ;
- le comportement quand plusieurs `slide_anchor` existent dans un meme passage.

Il faudra probablement laisser les anchors explicites depasser la limite normale par bloc, mais sans augmenter automatiquement le nombre de slides partout.

## Risques

Cette evolution peut ameliorer fortement la qualite, mais elle peut aussi casser la generation si elle est appliquee trop vite.

Risques identifies :

- trop de slides generees ;
- slides trop proches les unes des autres ;
- script oral fragmente artificiellement ;
- budget de mots mal interprete ;
- verification plus difficile si elle porte sur les intentions au lieu du texte oral ;
- templates demandes mais non disponibles cote React ;
- fallback silencieux vers un mauvais template.

C'est pour cela qu'on ne l'applique pas maintenant.

## Strategie de test plus tard

Quand les templates principaux seront stabilises, tester cette evolution sur un seul extrait de la journee.

Extrait candidat :

- passage du client dans le brouillard ;
- objectif : obtenir 3 slides distinctes ;
- aucune augmentation du texte oral ;
- verification du rendu dans le deck ;
- verification que le script reste naturel a l'oral.

Critere de reussite :

- chaque slide a une intention nette ;
- le passage oral reste coherent sans doublon ;
- les slides ne sont pas decoratives ;
- le nombre de slides reste pedagogiquement justifie ;
- le template choisi correspond vraiment au moment du cours.

## Decision actuelle

On garde cette idee pour la fin.

Pour l'instant, la priorite est :

- continuer a decouper la journee slide par slide ;
- creer ou porter les templates Claude Design exacts ;
- verifier le rendu visuel ;
- garder la structure actuelle de generation sans prendre de risque.

