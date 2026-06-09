# Structured Plan Prompt

Objectif : produire le plan JSON verrouillable d'une journée de 7 cours audio.

Le plan est libre pendant sa création, puis obligatoire pour la génération.

Contraintes :
- 7 cours exactement.
- 2 à 4 parties par cours.
- Cours interne 1 de la première journée : accueil, programme annuel synthétique,
  thèmes de la journée, transition vers premier grand thème, objectif/axes.
- Cours interne 1 d'une journée suivante : accueil de journée et reprise de progression,
  sans refaire la présentation annuelle complète.
- Cours internes 2 à 6 : reprise naturelle cohérente avec le vocal précédent de
  fin de pause/Q/R, rappel bref de la partie précédente, lien avec le nouveau
  thème, objectif/axes.
- Cours interne 7 : conclusion de la dernière partie, conclusion globale de journée, amorce prochaine
  séance ou clôture finale, puis mention douce du tchat.
- Les exemples non sourcés doivent rester fictifs ou hypothétiques de façon
  claire et naturelle : "Imaginons...", "Imaginez qu'un client...", "Prenons un
  exemple fictif..." ou "Supposons que..." suffisent. Ne prévois pas de phrase
  méta lourde si l'hypothèse est déjà claire.
- Ne pas employer le mot "bloc" côté apprenant.
- Les objets JSON "course" sont internes. Côté apprenant, chaque entrée doit
  être formulée comme un grand thème, une partie, un chapitre ou une séquence de
  la journée, jamais comme "le cours 1" ou "ce cours".
- Les horaires, durées, créneaux, budgets mots et fichiers audio sont des
  informations internes. Le plan peut les utiliser pour organiser la journée,
  mais le texte final ne doit jamais les verbaliser.
- Ne formule jamais une consigne côté apprenant du type "sans vous soucier des
  horaires précis". Présente seulement les thèmes dans leur ordre pédagogique.
- Les plans internes doivent se traduire à l'oral en axes naturels : "d'abord",
  "ensuite", "enfin", pas en formule scolaire ou administrative.
- L'ouverture porte le cadrage. Les parties de développement ne doivent pas
  répéter l'accueil, les thèmes de la journée, le programme annuel, l'objectif
  global ou le plan déjà annoncé.
- Chaque partie de développement doit recevoir des `teaching_beats` : des
  moments pédagogiques internes qui guideront le texte. Un beat peut poser une
  définition, développer une méthode, donner un exemple, signaler un piège,
  proposer un conseil, faire une comparaison ou récapituler.
- Chaque `teaching_beat` peut contenir un `slide_anchor`. Active l'anchor
  seulement si le moment mérite vraiment une slide. Ne force jamais une forme
  visuelle si le contenu n'en a pas besoin.
- Quand tu crées plusieurs `slide_anchor` dans une même partie, chacun doit
  correspondre à un mouvement pédagogique distinct. Définis mentalement ce que
  chaque anchor couvre et ce qu'il ne doit pas couvrir pour éviter que deux
  slides voisines se partagent le même passage oral.
- Dans chaque `slide_anchor`, renseigne des indices assez précis pour guider la
  suite : `pedagogical_shape`, `visual_goal`, `fields_hint`, et si utile `must_cover` et
  `must_not_cover`. Ces champs sont internes et ne doivent jamais être prononcés
  dans le texte final.
- `pedagogical_shape` nomme la fonction pédagogique du passage avant le choix du
  template. Classe selon ce que le passage fait faire au cerveau de l'apprenant,
  pas selon son thème.
- Valeurs autorisées de `pedagogical_shape` :
  `ouverture`, `definition_notion`, `idee_forte`, `maxime_a_ancrer`,
  `recit_avec_morale`, `image_mentale`, `conseil_actionnable`,
  `mise_en_garde`, `opposition_deux_modes`, `triade_structurante`,
  `progression_ordonnee`, `cas_comparables`,
  `synthese_apres_developpement`, `modele_a_leviers`.
- Pour `analogy`, l'anchor doit couvrir une situation hors métier qui sert de
  parallèle. Un exemple fictif client/conseiller/usager doit être planifié comme
  cas métier, écart de perception, règle, conseil ou réflexion, pas comme
  analogie.
- Le catalogue de templates fait autorité : choisis un template compatible avec
  l'intention pédagogique et le nombre réel d'items. Si le contenu n'a pas cinq
  éléments, ne demande pas un visuel à cinq éléments.
- Les templates source exacts disponibles sont : `welcome`, `program_year`,
  `day_program_7_steps`, `chapter_opener`, `reflection`, `definition`,
  `comparison`, `casestudy`, `situations`, `steps`, `flow`, `story`,
  `analogy`, `framework`, `opinion`, `recap`, `warning`, `tip`, `quotable`,
  `pause`, `qa`.
  N'utilise `casestudy` que pour des cas comparables ou situations métier en
  cartes ; un récit avec morale est `story`, trois profils sont `situations`,
  quatre gestes métier sont `flow`, un modèle à leviers est `framework`.
- Une maxime, phrase clé, formule exacte ou repère à mémoriser est `quotable`.
  Si cette phrase est ensuite illustrée par une scène ou une expérience client,
  cette déclinaison narrative peut devenir `story`.
- Une structure nouvelle en trois piliers, trois repères, trois profils, trois
  postures, trois situations ou trois expressions est `situations`, pas
  `recap`. Les signaux forts sont "trois piliers", "les trois", "les voici",
  "trépied" ou "triptyque".
- Un seul cas fictif qui sert à faire passer un conseil, une astuce ou un
  réflexe métier est `tip`, pas `casestudy`. `casestudy` est réservé à 2 ou 3
  cas métier comparables en cartes.
- Une distinction en deux familles ou deux modes, comme synchrone/asynchrone,
  téléphone/courriel, immédiat/différé ou rapidité/exhaustivité, est
  `comparison`.
- Une liste de mots/formules à bannir, expressions interdites, pièges de
  langage ou erreurs à éviter n'est pas un `recap` : utilise `situations` s'il y
  a exactement 3 éléments, sinon `warning`.
- `recap` est réservé à une vraie synthèse après un développement déjà traité :
  "ce qu'on retient", "en résumé", "nous avons vu".
- Ces beats et anchors sont internes. Le texte final ne doit jamais prononcer
  "slide", "PowerPoint", "template", "anchor" ou "teaching beat".

Le JSON doit rester strictement valide.
