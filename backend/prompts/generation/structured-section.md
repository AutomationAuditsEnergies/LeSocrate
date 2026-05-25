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
