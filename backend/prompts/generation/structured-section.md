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
- Si la section contient des `teaching_beats`, le texte doit les couvrir dans
  l'ordre et de façon naturelle. Ces beats structurent le fond, mais ils ne
  doivent jamais être nommés comme des beats, slides, anchors, templates,
  PowerPoint ou teaching beats.
- Quand un `teaching_beat` contient un `slide_anchor`, traite ce beat comme un
  contrat de segment oral distinct : la portion de texte correspondante doit
  porter précisément l'intention du beat et de son anchor, avant de passer au
  beat suivant.
- Une section peut additionner plusieurs beats, mais elle ne doit pas les
  mélanger. Le passage oral du premier beat ne doit pas absorber la définition,
  l'exemple, la règle ou la transition prévus pour le beat suivant.
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
- Pas de markdown ni titre écrit.
- Texte oral TTS-ready.
- Ne mentionne jamais les horaires, créneaux, durées, budgets mots, noms de
  fichiers ou marqueurs techniques. Ces informations servent uniquement au
  système.
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
