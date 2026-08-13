# Spécifications de développement — prochaines diffusions

- Ce document constitue le cahier des charges à transmettre à l’agent chargé du développement.
- L’agent doit implémenter les règles ci-dessous dans l’interface et dans la logique de génération.
- Chaque séance est traitée séparément.
- Chaque séance possède sa propre date, son heure et son identifiant unique.
- La génération d’une séance démarre automatiquement 72 heures avant son début.
- Le bloc de l’interface s’intitule **« Prochaines diffusions »**.
- Le bloc affiche le message suivant :
  - « Vos prochaines séances seront générées automatiquement 72 heures avant leur début. Vérifiez ensuite que chaque séance a bien été générée. »
- Si une séance n’est pas disponible après la génération prévue :
  - afficher un message d’erreur technique compréhensible ;
  - permettre de programmer un ancien cours pour cette séance ;
  - demander à l’utilisateur de signaler l’erreur technique.
- Sous ce message, afficher la section **« Prochaines générations »**.
- Afficher au maximum les trois prochaines générations planifiées.
- Afficher les générations dans l’ordre chronologique.
- Pour chaque génération, afficher :
  - la date et l’heure prévues de génération ;
  - la date et l’heure de la séance concernée.
- Exemple :
  - Lundi 10 août à 9 h — séance du jeudi 13 août à 9 h.
  - Mardi 11 août à 7 h — séance du vendredi 14 août à 7 h.
  - Mercredi 12 août à 13 h — séance du samedi 15 août à 13 h.
- Si moins de trois séances sont planifiées, afficher uniquement les séances existantes.
- Si plusieurs séances sont proches ou doivent être générées dans une période similaire, les afficher simultanément sans les regrouper ni les remplacer.
- Si aucune séance n’est planifiée, afficher un état explicite indiquant qu’aucune séance n’est programmée.

## Organisation de la fiche professeur

- Supprimer complètement la catégorie **Audio** de la fiche professeur.
- La fiche professeur ne doit plus contenir que quatre encadrés :
  - **Planning** ;
  - **Cours** ;
  - **Élèves** ;
  - **Présence**.
- Supprimer de la catégorie Audio les actions permettant de consulter ou de remplir les audios.
- Le suivi des audios doit être intégré directement dans la catégorie **Cours**.
- Chaque journée affichée dans **Cours** doit indiquer clairement si ses audios sont :
  - générés et disponibles ;
  - en cours de génération ;
  - manquants ;
  - en erreur.
- Ajouter dans la catégorie **Cours**, au-dessus de la liste des journées, un petit bouton **« Remplir »**.
- Le bouton **« Remplir »** doit permettre de sélectionner la journée à utiliser pour la prochaine journée de formation.
- L’action **« Remplir »** doit être réalisée depuis la vue **Cours**, sans réintroduire une catégorie Audio séparée.
- Après le remplissage, l’état des audios concernés doit être visible directement sur la journée sélectionnée.

## Contenu du PDF généré

- Ne jamais afficher le nom **« Le Socrate »** dans le PDF généré.
- Supprimer cette mention du bandeau supérieur, du pied de page, de la page de garde et des métadonnées visibles.
- Le PDF peut conserver la mention générique **« Support de formation »**.
- Le numéro de page doit rester affiché si cette fonctionnalité est déjà prévue.

## Génération adaptative des audios

### Principe général

- Chaque journée doit être générée en deux étapes :
  1. générer et mesurer les audios de cours ;
  2. calculer les durées définitives, puis générer les audios de Q&R et de pause.
- Le planning définit les horaires fixes de la journée, notamment le début de chaque cours.
- Les écarts de durée d’un cours sont absorbés par le bloc situé immédiatement après ce cours, normalement le Q&R.
- Le cours suivant doit toujours commencer à l’heure prévue.
- La pause située après le Q&R conserve son horaire et sa durée prévus.

### Texte et durée naturelle des cours

- Avant la synthèse vocale, estimer la quantité de texte adaptée à la durée prévue et à la vitesse configurée de la voix.
- Utiliser cette estimation pour calibrer le texte avant sa génération audio.
- Générer ensuite l’intégralité du texte validé avec la vitesse de voix configurée.
- Mesurer la durée réelle du MP3 obtenu.
- Après cette mesure, ne pas enrichir, raccourcir ou réécrire le texte pour corriger l’écart de durée.
- Conserver la durée naturelle produite par la voix.
- Ne pas ajouter de silence à la fin d’un cours uniquement pour atteindre sa durée théorique.

### Calcul de la durée du Q&R

- Si le cours se termine en avance :
  - démarrer immédiatement le Q&R ;
  - allonger le Q&R afin de rejoindre l’horaire prévu du bloc suivant.
- Si le cours dépasse légèrement :
  - laisser le cours se terminer naturellement ;
  - raccourcir le Q&R de la même durée.
- Un Q&R ou une pause courte doit toujours conserver au moins **5 minutes**.
- Une pause déjeuner doit toujours conserver au moins **60 minutes**.
- Si le dépassement du cours consomme toute la marge disponible :
  - arrêter net la lecture du cours à la dernière limite permettant de conserver la durée minimale du bloc suivant ;
  - démarrer immédiatement le Q&R ou la pause ;
  - ne pas modifier le texte source ni le fichier MP3 complet du cours.
- Cette coupure est une sécurité exceptionnelle. Un dépassement aussi important ne doit normalement pas se produire.

### Génération des audios de Q&R et de pause

- Calculer d’abord la durée définitive de chaque Q&R et de chaque pause à partir des durées réelles des cours.
- Générer ensuite chaque MP3 directement avec cette durée définitive.
- Le début du fichier doit contenir un véritable silence numérique.
- Ne placer au début aucune syllabe, aucun mot et aucune tonalité d’amorce.
- Placer la voix annonçant la reprise à la fin du fichier.
- Exemple : pour un Q&R de 15 minutes avec 10 secondes de voix finale, générer environ 14 minutes et 50 secondes de silence, puis 10 secondes de voix.
- Le MP3 doit conserver toute sa durée, y compris lorsque sa majeure partie contient du silence.
- Dans le fonctionnement normal, le lecteur ne doit ni avancer dans le fichier ni prolonger artificiellement son silence : le fichier doit déjà avoir la bonne durée.

### Diffusion et synchronisation

- À la fin d’un cours, démarrer simultanément :
  - le MP3 du Q&R ou de la pause depuis son début ;
  - la diapositive correspondante ;
  - le décompte correspondant à sa durée définitive.
- Le MP3 doit réellement être lu pendant tout le bloc, même si son début est silencieux.
- La voix de reprise doit être diffusée à la fin du bloc, au moment prévu.
- Enregistrer le planning définitif propre à chaque séance après la mesure et la génération des audios.
- Le serveur doit être la référence pour le bloc en cours, ses horaires, le décompte et la position de lecture.
- Après un rechargement, une déconnexion ou une reconnexion, reprendre au bon bloc et au bon emplacement.
- Une séance déjà générée doit être régénérée et republiée pour bénéficier de ce nouveau fonctionnement.
