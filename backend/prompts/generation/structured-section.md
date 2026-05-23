# Structured Section Prompt

Objectif : écrire une seule section d'un cours audio à partir du plan verrouillé.

Contraintes :
- Respecter le plan JSON donné en contexte.
- Écrire uniquement la section demandée.
- Respecter le budget mots de la section.
- Ne pas devancer une section suivante.
- Ne pas finir le cours précédent.
- Si c'est une introduction : plan avant exemple.
- Si c'est une partie : une idée nouvelle identifiable, reliée au plan.
- Si c'est une conclusion : récapituler et fermer, sans ouvrir un nouveau sujet.
- Après Q/R ou mention du tchat : aucun nouveau développement.
- Pas de markdown ni titre écrit.
- Texte oral TTS-ready.
