# Décision : refonte des prompts TTS avec règles anti-dérive + stratégie sandwich

**Date** : 2026-04-22
**Statut** : appliqué
**Fichiers impactés** : `prompt-generation-tts-direct.md`, `prompt-generation-tts-scratch.md`, `backend/routes/hr_routes.py`, `backend/services/knowledge_base_service.py`

---

## Contexte

Après observation des premiers cours générés par la pipeline formation
(`/formation-pipeline`), plusieurs **dérives éditoriales systématiques**
apparaissaient dans les textes produits par Claude Sonnet/Haiku. Ces
dérives auraient pollué à la fois :
- l'écoute des apprenants (contenu malhonnête ou peu pédagogique)
- le RAG en aval (qui indexerait des mensonges comme faits)
- le PDF programme officiel (non diffusable en l'état)

Le prompt existant (`prompt-generation-tts-scratch.md` utilisé en mode
`from_scratch`) était beaucoup plus maigre que `prompt-generation-tts-direct.md`
(mode expansion legacy). Les règles éthiques (#1-#16) et anti-hallucination
(#17-#20) existaient dans direct.md mais n'avaient **pas été reportées**
dans scratch.md lors de la création de ce dernier.

## Problème

### Dérives observées dans les cours générés

| # | Dérive | Exemple concret |
|---|---|---|
| 1 | Anecdote personnelle fabriquée au prétérit | *"Il y a quelques années, j'ai reçu un appel téléphonique… j'ai entendu une voix sèche qui m'a dit…"* |
| 2 | Métaphore proscrite (musique) | *"C'est du rythme. C'est de la musique."* |
| 3 | Formulation méta lourde | *"Imaginez un exemple concret. Une personne appelle…"* (deux phrases, annonce + contenu) |
| 4 | Guillemets de discours direct | *« Bonjour, service client, quel est votre numéro de commande ? »* — inaudible en TTS |
| 5 | Énumération mécanique | *"Première méthode : la fiche d'accueil. Deuxième méthode : le script. Troisième méthode : le CRM."* |
| 6 | Marqueurs de présentiel impossibles | *"Je vois que vous êtes tous bien installés."* (pas de visio) |
| 7 | Chute diluée par un connecteur | *"Et voilà, vous venez de perdre la bataille émotionnelle en dix secondes."* |
| 8 | Descriptions affirmatives en bloc | *"Ce qu'elle ressent, c'est qu'elle n'est qu'un numéro"* — plat au lieu de dialogal |

### Cause racine : 3 couches de problèmes

1. **Règles absentes de scratch.md** : les 20 règles de direct.md (éthiques
   + anti-hallucination) n'étaient pas dans le prompt actif de la pipeline.
2. **Paradigme pédagogique flou** : le préambule parlait de *"cours en
   présentiel devant 20 élèves"* (ligne 45 de direct.md), ce qui est
   faux — Le Socrate produit des MP3 diffusés sur playlist horodatée.
3. **Formulation vs sujet** : plusieurs dérives ne sont pas des mensonges
   (pas couverts par #17-#20) mais des défauts **stylistiques** récurrents
   que Claude reproduit par défaut (énumérations, méta, guillemets).

## Options envisagées

### Option A — Ajouter règles au cas par cas

Réagir à chaque dérive observée par une interdiction ciblée. Rejeté car
Claude trouve toujours de nouvelles façons de dériver qu'on n'a pas
anticipées ; on se retrouve avec un prompt gigantesque et brouillon.

### Option B — Principes généraux + applications concrètes

Formuler des **principes pédagogiques** dont les dérives observées sont
des applications parmi d'autres. Claude peut alors transposer à des
situations non listées. **Retenu** — c'est le pattern "show don't tell
appliqué aux règles".

Exemple :
- **Principe** : *"tu animes un dialogue, pas un rapport écrit"* (R9/#23)
- **Applications** : questions rhétoriques, vérifications compréhension,
  invitations à la réflexion, métadiscours — chacune avec des exemples
  ❌/✅

### Option C — Unification des 2 fichiers prompts

Refactorer pour n'avoir qu'un seul fichier. Écarté pour cette session car :
- les passes ont des structures différentes (séquentielle en expansion,
  parallèle en from_scratch)
- le mode expansion attend `{COLLER_LE_TEXTE_DE_LA_PASSE_1}` qui n'a pas
  de sens en from_scratch
- refactor trop gros pour le gain

**Compromis** : scratch.md est **reconstruit** depuis direct.md via script
Python (sync à la demande). Direct.md devient "legacy". `/schedule-config`
pointe désormais sur scratch.md.

## Décision retenue

### 1. Principe cardinal "ne jamais mentir"

Au-dessus de tout le reste (fluidité, rythme, accroche, storytelling),
placer le principe **NE JAMAIS MENTIR**. Test mental obligatoire avant
chaque affirmation :

> *"Si un élève me demandait ma source, qu'est-ce que je répondrais ?"*
> Si la réponse honnête est *"je l'ai inventé"* → reformuler ou supprimer.

### 2. Paradigme : cours à distance / classe virtuelle en ligne

Ni présentiel physique, ni visio synchrone, ni radio journalistique.
Cours audio diffusé à heure fixe sur la playlist horodatée, simulation
de direct audio pour un groupe d'apprenants qui écoutent simultanément.

**Autorisés** : "bonjour à tous", "ce matin", "après la pause", "hier on
a vu que…" (si progression cohérente).

**Interdits** : marqueurs visuels ("je vois"), consignes physiques
("notez"), interaction retour ("vous m'entendez ?").

### 3. 6 nouvelles règles de style oral (#21-#26)

- **#21 Fusion syntaxique** : `"Imaginez qu'une personne…"` fusionné
  en une phrase (jamais `"Imaginez un exemple. Une personne…"` en
  deux phrases méta)
- **#22 Zéro guillemet de discours direct** : le TTS ne prononce pas
  les « », tout basculer en discours indirect ou description qualifiante
- **#23 Posture dialogale** : interpellation tous les 150-250 mots
  (questions rhétoriques, vérifications, invitations, métadiscours)
- **#24 Chutes isolées** : punchlines sans connecteur ouvreur ni
  méta-commentaire (pas de "Et voilà…", "Comme vous pouvez le voir…")
- **#25 Contraintes cours à distance** : visuel / physique /
  interaction-retour interdits
- **#26 Pas d'énumérations mécaniques** : tissage narratif avec
  transitions variées et commentaires de relief

### 4. Stratégie "sandwich" dans le prompt

Les interdictions cardinales sont rappelées à **3 endroits** de chaque
passe pour que Claude ne les oublie pas en cours de génération :

1. **Encadré RAPPEL CRITIQUE** en tête (5 interdictions résumées)
2. **Bloc complet** SUJETS PROSCRITS + règles détaillées au milieu
3. **Encadré VÉRIFICATION FINALE** en fin (test global juste avant génération)

Impact mesuré : le mot "musique" apparaît **5 fois** dans chaque passe —
saturation intentionnelle, Claude ne peut pas ne pas voir.

### 5. `/schedule-config` pointe sur scratch.md

Changement de `_TTS_PROMPT_FILE` dans :
- `backend/routes/hr_routes.py` (endpoints GET/POST `/api/hr/tts-prompt`)
- `backend/services/knowledge_base_service.py` (chargement dynamique
  des règles éditoriales pour la KB)

Direct.md reste en place pour le mode expansion legacy mais n'est plus
édité via l'UI.

## Rationale

### Pourquoi ce découpage principes + applications ?

La littérature prompt engineering montre que les LLM généralisent mieux
quand on leur donne un principe + des exemples ❌/✅ qu'une liste
d'interdictions atomiques. On évite aussi le "pattern matching superficiel"
(Claude qui apprend juste à éviter les tournures textuellement listées
et crée de nouvelles variantes non listées).

### Pourquoi la stratégie sandwich ?

Les prompts longs (>20 k tokens) subissent le "lost in the middle" —
Claude se concentre sur le début et la fin. Les règles absolues placées
**uniquement** au milieu du prompt étaient sous-appliquées. Placer un
résumé au début + un check à la fin garantit que la contrainte reste
active tout au long de la génération.

### Pourquoi "cours à distance" et pas "radio" ni "asynchrone" ?

- **Radio** : connotation journalistique (animateur neutre), éloigne du
  registre pédagogique formateur-élèves.
- **Asynchrone** (chacun écoute quand il veut) : faux techniquement —
  la playlist est horodatée, tout le monde écoute en même temps.
- **Cours à distance** (classe virtuelle) : cadre pédagogique correct
  + permet l'adresse collective ("bonjour à tous") + permet les repères
  horaires de la journée-cours ("ce matin", "après la pause").

## Conséquences

### Positives

- Cohérence des règles entre pipeline formation (scratch.md) et
  KB (charge aussi depuis scratch.md)
- UI `/schedule-config` édite directement le prompt actif → pas de
  désynchronisation invisible
- Prompts robustes face aux dérives identifiées + capacité à généraliser
  aux dérives non anticipées (grâce aux principes)

### Négatives / dette

- **Duplication des règles** entre direct.md et scratch.md — si édition
  via UI dans scratch.md, direct.md ne suit pas. Solution provisoire :
  re-lancer le script de synchronisation manuellement si besoin. Solution
  propre future : externaliser les règles dans un fichier commun chargé
  dynamiquement.
- **Prompt long** (38 k chars par passe, vs ~15 k avant) — coût input
  tokens en légère hausse mais négligeable vs. qualité.
- **Regénération des segments déjà en DB** : les cours générés avec
  l'ancien prompt sont pollués par les dérives. À effacer + regénérer
  avec le nouveau prompt (option validée mais pas encore exécutée).

## Références code

- `prompt-generation-tts-direct.md:44-112` — préambule cours à distance
  + encadré RAPPEL CRITIQUE
- `prompt-generation-tts-direct.md:632-867` — RÈGLES #21 à #26
- `prompt-generation-tts-direct.md:869-890` — encadré VÉRIFICATION FINALE
- `prompt-generation-tts-scratch.md` — réécrit from scratch via script
  Python (copie directe des règles de direct.md)
- `backend/routes/hr_routes.py:2897+` — `_TTS_PROMPT_FILE` pointe sur scratch.md
- `backend/services/knowledge_base_service.py:53+` — idem
- `backend/services/content_generation_service.py:73+` — cache mtime
  pour que l'édition `.md` via UI ne nécessite pas de restart backend

## Leçons

1. **Les règles éthiques d'un prompt doivent être à 3 niveaux** (rappel
   en tête, détail au milieu, check en fin) pour survivre à la génération
   dans les LLM sur prompts longs.
2. **Un principe généralisable vaut mieux qu'une liste d'interdictions**
   — Claude transpose mieux avec un test mental ("si un élève me demandait
   ma source...") qu'avec une énumération.
3. **Chaque dérive observée doit être tracée à un principe** — sinon on
   ajoute des règles qui se contredisent ou se chevauchent. L'audit doit
   clustériser les dérives en familles, puis traiter les familles.
4. **Le paradigme pédagogique doit être explicite en préambule**. Un
   LLM "formateur" invente sa posture si on ne la lui donne pas :
   présentiel, visio, radio, podcast… et produit des formulations
   incohérentes avec le format réel.
