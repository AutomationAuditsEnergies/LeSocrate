# Structured Plan Prompt

Objectif : produire le plan JSON verrouillable d'une journée de 7 cours audio.

Le plan est libre pendant sa création, puis obligatoire pour la génération.

Contraintes :
- 7 cours exactement.
- 2 à 4 parties par cours.
- Cours 1 de la première journée : accueil, programme annuel synthétique,
  thèmes de la journée, thème/objectifs/plan du cours.
- Cours 1 d'une journée suivante : accueil de journée et reprise de progression,
  sans refaire la présentation annuelle complète.
- Cours 2 à 6 : reprise naturelle cohérente avec le vocal précédent de fin de
  pause/Q/R, rappel bref du cours précédent, lien avec le thème actuel,
  thème/objectifs/plan.
- Cours 7 : conclusion du cours, conclusion globale de journée, amorce prochaine
  séance ou clôture finale, puis mention douce du tchat.
- Les exemples non sourcés doivent rester explicitement fictifs.
- Ne pas employer le mot "bloc" côté apprenant.

Le JSON doit rester strictement valide.
