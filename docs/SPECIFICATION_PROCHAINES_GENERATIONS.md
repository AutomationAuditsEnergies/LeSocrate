# Spécifications de développement — recrutement, planning et supports de formation

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
- Dans l’en-tête, afficher uniquement **« Support de formation »**.
- Ne pas préfixer cette mention par le nom de l’application ou de la plateforme.
- Le numéro de page doit rester affiché si cette fonctionnalité est déjà prévue.

## Assistant conversationnel de recrutement

- Quel que soit le premier message de l’utilisateur, répondre de manière aimable et constructive.
- Expliquer que l’assistant peut aider à préparer le recrutement et le calendrier de formation.
- Créer automatiquement un brouillon dès le premier échange.
- Poser uniquement les questions correspondant aux informations encore manquantes.
- Mémoriser les réponses déjà données et ne pas poser deux fois la même question.
- Demander les informations suivantes :
  - nom de la formation ;
  - code RNCP associé ;
  - date de début de la première journée ;
  - durée moyenne de la formation en semaines ou en mois ;
  - nombre moyen de jours de formation par semaine ;
  - jours habituels de formation.
- Pour le rythme hebdomadaire, préciser explicitement que l’utilisateur doit indiquer :
  - le nombre moyen de jours par semaine ;
  - les jours habituels concernés.
- Préciser que le rythme indiqué est une règle générale et que des exceptions ponctuelles sont possibles.
- Donner un exemple d’exception : une formation habituellement organisée le lundi et le mercredi peut exceptionnellement avoir lieu le mardi et le jeudi, ou le mardi et le vendredi, en cas de jour férié ou de contrainte particulière.
- Ne pas mélanger les informations de deux formations ou de deux recrutements différents.

## Brouillon de recrutement

- Le chatbot et le parcours manuel doivent utiliser le même système de brouillon.
- Le brouillon doit contenir les informations saisies dans le chatbot, le calendrier, le template et l’état d’avancement.
- Le brouillon doit être conservé pendant la création ou la sélection du template.
- Chaque recrutement indépendant possède un identifiant de brouillon distinct.
- Tant qu’il n’est pas validé, le brouillon est considéré comme actif et reprenable.
- Au retour sur la page du chatbot, afficher un bouton **« Reprendre mon recrutement »** lorsqu’un brouillon actif existe.
- Le bouton **« Recruter manuellement »** doit ouvrir le même brouillon lorsqu’il existe, sans recommencer la saisie.

## Passage vers le calendrier

- Une fois les informations principales récupérées, le chatbot récapitule les données.
- Rediriger ensuite l’utilisateur vers la page **« Calendrier et déroulé de la formation »**.
- La page doit être entièrement préremplie avec :
  - la formation ;
  - le code RNCP ;
  - la date de début ;
  - la durée ;
  - le nombre moyen de jours par semaine ;
  - les jours habituels ;
  - le calendrier initial calculé.
- L’utilisateur doit pouvoir modifier les dates et les exceptions directement dans le calendrier.
- Les exceptions hebdomadaires ne doivent pas modifier la règle générale enregistrée dans le brouillon.

## Sélection et création d’un template

- Le choix du template est disponible après une création manuelle ou une création accompagnée par le chatbot.
- Le champ **« Choisir un template »** doit ouvrir une liste déroulante défilante.
- Si aucun template n’existe, afficher l’option **« Créer un template »**.
- Si des templates existent, afficher :
  - tous les templates disponibles ;
  - l’option **« Créer un template »** en dernière option.
- L’option **« Créer un template »** doit rester accessible en faisant défiler la liste.
- Cliquer sur **« Créer un template »** doit rediriger vers **« Organisation des cours »**.
- Conserver le brouillon, le calendrier et toutes les informations déjà saisies pendant cette redirection.
- Après la création du template, revenir au calendrier avec le nouveau template automatiquement sélectionné.

## Demande d’un nouveau recrutement

- Si l’utilisateur demande clairement une nouvelle journée ou un nouveau recrutement sans rapport avec la configuration actuelle, ne rien supprimer automatiquement.
- Demander d’abord confirmation avec le message suivant :
  - « Vous souhaitez abandonner la configuration actuelle et commencer un nouveau recrutement ? Les informations non validées seront supprimées. »
- Afficher les choix suivants :
  - **« Abandonner et commencer un nouveau recrutement »** ;
  - **« Continuer la configuration actuelle »**.
- Si l’utilisateur continue la configuration actuelle, conserver le brouillon et reprendre l’étape en cours.
- Si l’utilisateur confirme l’abandon :
  - supprimer l’ancien brouillon non validé ;
  - réinitialiser le chatbot ;
  - réinitialiser le calendrier ;
  - réinitialiser la page de saisie ;
  - créer un nouveau brouillon vide.
- Ne pas archiver l’ancien brouillon après confirmation : les informations non validées sont supprimées.
- Ne jamais supprimer un recrutement déjà validé ; il reste disponible dans l’historique.

## Page finale de validation

- Avant la validation définitive, afficher un récapitulatif modifiable de :
  - la formation ;
  - le code RNCP ;
  - la date de début ;
  - la durée ;
  - le rythme hebdomadaire ;
  - les jours habituels ;
  - le calendrier détaillé ;
  - le template sélectionné ou créé.
- Permettre à l’utilisateur de revenir modifier chaque information avant validation.
- Ajouter une action **« Valider le recrutement »**.
- Après validation :
  - transformer le brouillon en recrutement confirmé ;
  - enregistrer définitivement la formation et son calendrier ;
  - réinitialiser la conversation du chatbot ;
  - réinitialiser le calendrier et la page de saisie ;
  - retirer le brouillon de la liste des brouillons actifs ;
  - conserver le recrutement confirmé dans l’historique.

## Nettoyage définitif du pipeline

- Supprimer complètement la récupération des sources **RC** et **ROME**.
- Supprimer les appels de téléchargement RC/ROME, leur stockage, leur transmission aux prompts et les champs devenus inutiles.
- Supprimer complètement la génération audio globale de toutes les journées.
- La génération audio doit fonctionner uniquement séance par séance, selon le planning validé.
- Supprimer complètement l’ancien mode **Claude Code** : code, options d’interface, variables, routes, paramètres et mécanismes de fallback associés.
- DeepSeek devient l’unique fournisseur de modèles du pipeline.
- Supprimer complètement l’étape **`humanization_review`** : code, orchestration, statuts, événements, interface et références documentaires.
- Supprimer complètement l’ancienne étape **`volume_safety`** : code, orchestration, statuts, événements, interface et références documentaires.
- Supprimer les options, indicateurs et colonnes uniquement liés à cette étape, notamment les mécanismes de skip ou de suivi `volume_safety`.
- Ne plus lancer de correction LLM globale après la génération d’une journée pour atteindre artificiellement un volume cible.
- Conserver uniquement le calcul du budget de mots intégré à la génération structurée de chaque cours.
- Conserver éventuellement un audit de volume en lecture seule, sans modification automatique du contenu.
- Supprimer complètement les anciennes actions manuelles étape par étape :
  - initialisation manuelle ;
  - récupération manuelle du REAC ;
  - enrichissement manuel ;
  - génération manuelle du programme global ;
  - découpage manuel des journées ;
  - lancement manuel du TTS global ;
  - relance manuelle de volume ;
  - review manuelle héritée ;
  - génération audio manuelle héritée ;
  - arrêt manuel de l’ancien auto-pilot.
- Supprimer les routes, boutons, états, permissions et textes d’interface liés à ces anciennes actions.
- Le pipeline durable unique devient le seul point d’entrée de génération.

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
