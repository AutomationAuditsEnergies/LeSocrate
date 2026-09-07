# Structured Section Prompt

Objectif : écrire une seule section d'un cours audio à partir du plan verrouillé.

Contraintes :
- Respecter le plan JSON donné en contexte.
- Écrire uniquement la section demandée.
- Respecter le budget mots de la section.
- Ne pas devancer une section suivante.
- Ne pas finir le cours précédent.
- Si c'est une introduction : plan avant exemple. C'est l'unique endroit où
  l'on accueille, cadre la journée ou annonce le thème global et ses axes.
- Si c'est une partie : une idée nouvelle identifiable, reliée au plan.
  Une partie de développement ne refait jamais l'introduction, ne répète jamais
  les thèmes de la journée, le programme annuel, le cadrage général, l'objectif
  global ou le plan déjà annoncé.
- Si la section contient des `teaching_beats`, le texte doit les couvrir de
  façon naturelle. Ces beats structurent le fond, mais ils ne
  doivent jamais être nommés comme des beats, slides, anchors, templates,
  PowerPoint ou teaching beats.
- Quand un `teaching_beat` contient un `slide_anchor`, traite ce beat comme un
  contrat de moment d'affichage distinct : la phrase où son développement
  principal commence doit être identifiable, même si une idée est préparée ou
  rappelée ailleurs.
- Une section peut additionner plusieurs beats, mais elle ne doit pas les
  morceler. Une idée peut être annoncée ou rappelée ailleurs en une phrase,
  mais son développement principal a un seul moment d'activation.
- Pour chaque beat avec slide_anchor, respecte mentalement trois frontières :
  ce que ce segment doit couvrir, ce qu'il doit seulement préparer, et ce qu'il
  doit laisser au segment suivant. Ces frontières restent invisibles pour
  l'apprenant.
- Si un beat est une analogie, garde l'analogie dans son segment : scène hors
  métier, mécanisme rendu mémorable, puis pont court vers le métier. Ne lui
  rattache pas l'explication conceptuelle complète ni l'exemple métier suivant.
- Si le beat suivant définit un concept, explique ce concept dans un nouveau
  mouvement oral reconnaissable, sans reprendre longuement l'histoire ou
  l'image du beat précédent.
- Si un beat porte une maxime, une phrase clé ou une formule à ancrer, énonce
  la phrase exacte une seule fois, telle quelle, introduite naturellement
  ("retenez ceci", "la voici", "la phrase à garder en tête"). Ne la dilue pas
  en plusieurs reformulations.
- Si un beat oppose deux familles, deux modes ou deux postures, nomme
  explicitement les deux côtés dans le texte oral, par exemple "d'un côté..."
  puis "de l'autre...". Ne laisse pas l'opposition implicite.
- Si c'est une conclusion : récapituler et fermer, sans ouvrir un nouveau sujet.
- Après Q/R ou mention du tchat : aucun nouveau développement.
- Si la section contient des beats avec `slide_anchor.enabled=true`, termine
  obligatoirement la réponse par un bloc technique, après le texte oral. Ce
  bloc n'est jamais lu à l'oral et sert uniquement au système :

===ORDRE_AFFICHAGE_SLIDES===
c1p2b1, c1p2b3, c1p2b2
===CARTE_AFFICHAGE_SLIDES===
c1p2b1 | ANCRAGE: "8 à 15 mots copiés exactement depuis le texte"
c1p2b3 | ANCRAGE: "..." | ITEMS: clarté; écoute; constance
c1p2b2 | ANCRAGE: "..." | QUOTE: "On traite la demande, jamais le client."
===FIN_CARTE===

- `ORDRE_AFFICHAGE_SLIDES` déclare l'ordre narratif choisi pour les slides de
  cette section. Il peut différer de l'ordre du plan si la prose le demande.
- Une seule entrée par beat ancré. L'`ANCRAGE` est le début exact de la phrase
  où le développement principal du beat commence, copié caractère pour
  caractère depuis le texte oral.
- Pour un beat `maxime_a_ancrer`, ajoute `QUOTE` avec la phrase exacte
  prononcée. Pour une triade, ajoute `ITEMS` avec les trois éléments séparés
  par des points-virgules.
- Pas de markdown ni titre écrit.
- Texte oral TTS-ready.
- Dans le texte oral, ne mentionne jamais les horaires, créneaux, durées,
  budgets mots, noms de fichiers ou marqueurs techniques. Le bloc technique
  final demandé pour les slides est la seule exception, et il reste hors oral.
- Ne dis pas "sans vous soucier des horaires précis" ni aucune variante. Si tu
  présentes la journée, annonce simplement les thèmes dans l'ordre pédagogique.
- Après une pause ou un Q/R, reprends naturellement : rappel bref, lien avec le
  nouveau thème, objectif, plan. Ne commente pas la mécanique de planning.
- Si la section est une introduction, ne dis pas "ce cours", "premier cours",
  "cours actuel" ni "trois quarts d'heure". Présente plutôt "le premier grand
  thème", "cette première partie", "ce chapitre" ou "cette séquence".
- Le plan oral doit sonner naturel : "Pour avancer progressivement, on va suivre
  trois grands axes. D'abord... Ensuite... Et enfin...".
- Pour une introduction seulement, le ton attendu est sobre et fluide : "Bien.
  Maintenant que le cadre général est posé, on peut entrer dans le premier grand
  thème." Ce modèle donne la direction, il ne doit pas être recopié mot pour mot
  à chaque fois. Pour une partie de développement, ne commence pas par ce type
  de cadrage : entre directement dans l'axe prévu.
- Ne fabrique pas de punchline artificielle et ne durcis pas une formulation
  prudente simplement pour produire plus d'impact. Une nuance comme "peut
  paraître" ou "peut donner l'impression" est correcte si elle sert le sens.
