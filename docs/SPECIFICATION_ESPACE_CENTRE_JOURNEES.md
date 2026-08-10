# Spécification fonctionnelle — espace centre et journées de formation

> Document de référence pour l’évolution de la fiche d’un professeur dans le dashboard centre (`/dashboard-centre`).

## 1. Objectif

Remplacer les écrans techniques de gestion séparée des audios et des PDF par une vue orientée **journée de formation**.

L’administrateur doit pouvoir répondre rapidement à trois questions :

1. Quelle est la prochaine journée qui sera diffusée ?
2. Est-elle prête, avec tous ses audios et ses supports PDF ?
3. Si un fichier manque ou est incorrect, puis-je le remplacer sans gérer une liste technique globale ?

La fiche professeur reste la grande modale actuelle. Les outils ouverts depuis cette fiche utilisent le même cadre et remplacent son contenu, sans empiler une nouvelle modale par-dessus.

## 2. Décisions fonctionnelles

### 2.1. Une journée est l’unité de suivi

Les audios et les PDF sont consultés ensemble, par journée de formation. L’utilisateur ne travaille plus avec une liste globale de fichiers à affecter manuellement aux cours.

Le parcours de référence devient :

`Fiche professeur → Cours → Journée de formation → état des fichiers`

### 2.2. Suppression des écrans techniques principaux

- Supprimer l’ancienne liste globale **Audios**, notamment l’action « Remplir avec les audios ».
- Supprimer l’onglet **PDF** dédié à l’import d’un support, à la connexion d’un Drive ou à l’affectation manuelle de fichiers.
- Ne pas reproduire ces listes sous un autre nom : la source de vérité est la journée de formation.
- Les actions de correction restent accessibles uniquement dans le détail d’une journée, lorsqu’un problème est détecté.

## 3. Bloc « Prochaine diffusion »

### 3.1. Emplacement

Le bloc est placé **sous le robot, dans la partie gauche de la grande modale professeur**. Il reste visible dans la vue principale de la fiche, sans ouvrir de sous-modale.

Le badge « ARCHIVÉ » situé en haut à gauche est supprimé.

### 3.2. Contenu dynamique

Le contenu doit être calculé à partir de la prochaine séance réellement planifiée. Les dates ci-dessous illustrent le rendu attendu et ne doivent pas être codées en dur.

```text
Prochaine diffusion

Journée 4
Mardi 4 août 2026 à 09:00

Les fichiers seront préparés automatiquement
le dimanche 2 août à 09:00.

Revenez le lundi 3 août pour vérifier que la journée 4 est prête via l’onglet Cours.
```

Règles de calcul :

- **Prochaine diffusion** = prochaine séance future du planning du professeur.
- **Préparation audio** = H-48 avant l’heure de diffusion.
- **Vérification recommandée** = H-24 avant l’heure de diffusion.
- Si aucune séance future n’est planifiée, afficher un état explicite et une action pour configurer le planning.
- Afficher le fuseau horaire utilisé par le planning si celui-ci peut être différent du fuseau local.

### 3.3. États du bloc

Le bloc doit couvrir au minimum les états suivants :

- séance planifiée, préparation pas encore déclenchée ;
- préparation en cours ;
- journée prête ;
- journée prête avec avertissement (fichier manquant, taille invalide ou fichier remplacé) ;
- préparation en échec, avec message lisible et action de relance ;
- aucune prochaine séance.

Le texte doit rester factuel et institutionnel. Il ne faut pas afficher de promesse de disponibilité tant que le pipeline n’a pas confirmé l’état.

## 4. Onglet Cours et suivi d’une journée

### 4.1. Vue des journées

L’onglet **Cours** devient le point d’entrée du suivi des journées. Il affiche les journées générées pour le professeur, avec au minimum :

- numéro et titre de la journée ;
- date et heure de diffusion ;
- état global : `Prête`, `En préparation`, `À vérifier`, `Erreur` ou `Non planifiée` ;
- état des audios ;
- état du support PDF ;
- date de dernière génération ou de dernière vérification.

L’utilisateur peut sélectionner une journée dans cette vue. La sélection doit être conservée lorsqu’il revient en arrière.

### 4.2. Détail d’une journée

Le détail présente un résumé immédiatement vérifiable, sans balises techniques :

| Élément | Informations attendues |
| --- | --- |
| Audios | nombre attendu, nombre présent, état de chaque audio si nécessaire, durée ou taille si disponible |
| Support PDF | disponible ou manquant, date de génération, action d’ouverture/téléchargement |
| Texte source | état du texte final utilisé pour les fichiers, sans afficher les marqueurs internes |
| Pipeline | dernière exécution, succès ou erreur, possibilité de relancer selon les droits |

Le résumé global doit permettre de voir en un coup d’œil si **tous les PowerPoint, audios, supports PDF et autres fichiers attendus** sont présents. Si un type de support est réellement produit par le pipeline, il doit apparaître dans cette vérification ; sinon, il ne faut pas afficher une ligne vide fictive.

### 4.3. Correction manuelle limitée

La génération reste automatique, mais l’administrateur conserve une possibilité de correction en cas de bug :

- remplacer un audio précis ;
- sélectionner une autre version validée de la journée si plusieurs générations existent ;
- relancer la génération d’un fichier en erreur ;
- revenir à la version automatique confirmée.

La correction doit être contextualisée dans la journée sélectionnée. Il ne doit pas être nécessaire de parcourir tous les fichiers de toutes les journées.

Chaque remplacement affiche la date, l’auteur de la modification et un état permettant de distinguer `Automatique` de `Remplacé manuellement`.

## 5. Génération des audios

### 5.1. Déclenchement

Les audios d’une journée sont préparés automatiquement **H-48 avant sa diffusion**. L’administrateur n’a pas à remplir ou affecter manuellement une liste.

Le système doit être idempotent : une relance ne doit pas créer de doublons et doit conserver la version validée lorsqu’aucune nouvelle version n’est nécessaire.

### 5.2. Vérification H-24

Le bloc « Prochaine diffusion » invite l’utilisateur à revenir **H-24**. À ce moment, l’onglet Cours doit indiquer clairement :

- si tous les audios attendus sont présents ;
- si un audio est manquant, illisible ou en erreur ;
- si une action manuelle est requise ;
- si la journée peut être diffusée malgré un avertissement.

### 5.3. Gestion des bugs

Une automatisation peut échouer. Les erreurs doivent être visibles et actionnables :

- message compréhensible, sans stack trace ;
- fichier ou étape concernée ;
- date de dernière tentative ;
- bouton de relance avec état de chargement ;
- conservation de la dernière version valide si elle existe.

## 6. Génération des supports PDF

### 6.1. Déclenchement distinct des audios

Le PDF ne suit **pas** le calendrier H-48 des audios. Il doit être généré **dès que la pipeline de texte de la journée est terminée avec succès**.

Conséquence : le support PDF d’une journée peut être disponible bien avant H-48 et doit apparaître immédiatement dans l’onglet Cours.

### 6.2. Contenu et mise en page

Le PDF est construit automatiquement à partir du texte final de la journée :

- supprimer les balises, marqueurs et informations techniques internes ;
- générer une page de garde propre avec le titre de la formation, le numéro ou titre de la journée et la date si elle est connue ;
- présenter le contenu avec une hiérarchie lisible, des titres, des sous-titres et une pagination ;
- produire un document imprimable et téléchargeable ;
- conserver la version liée à la génération de texte qui l’a produite.

Si la pipeline de texte échoue, aucun PDF incomplet ne doit être déclaré comme prêt. Une erreur de génération doit rester visible dans le détail de la journée, avec une relance possible.

### 6.3. Historique et rattrapage

Les journées déjà terminées mais dépourvues de PDF doivent pouvoir être régénérées à partir de leur texte final, sans attendre une prochaine diffusion. Cette opération doit être traçable et ne doit pas modifier le contenu audio existant.

## 7. Navigation et modales

### 7.1. Même enveloppe, une seule vue active

Quand l’utilisateur ouvre **Planning**, **Cours**, **Élèves**, **Présence** ou un autre outil depuis la fiche professeur :

- l’outil prend la taille de la grande modale actuelle ;
- il s’affiche dans la même enveloppe visuelle ;
- aucune modale secondaire ne se place au-dessus ou en dessous ;
- le fond et la fiche précédente ne doivent pas rester interactifs en arrière-plan.

### 7.2. Retour arrière

Une petite flèche en haut à gauche permet de revenir à la fiche professeur. Le retour :

- ferme la vue outil courante ;
- restaure la fiche à l’état précédent ;
- conserve, si possible, la journée sélectionnée et la position de défilement ;
- ne déclenche pas de nouvelle modale par-dessus.

Le bouton de fermeture général reste disponible en haut à droite pour quitter toute la modale.

### 7.3. Cohérence visuelle

Les vues internes utilisent le même système de couleurs, de typographie, de boutons, de focus clavier et d’états de chargement que la modale professeur. Les anciens en-têtes bleus spécifiques aux modales Audios/PDF ne doivent pas être reconduits.

## 8. Parcours nominal

1. L’administrateur ouvre la fiche du professeur.
2. Sous le robot, il voit la prochaine diffusion et les horaires de préparation.
3. H-24, il ouvre **Cours** avec la flèche de navigation dans la même grande modale.
4. Il sélectionne la journée annoncée.
5. Il vérifie le statut global et la présence de tous les audios et du PDF.
6. Si tout est conforme, aucune action supplémentaire n’est requise.
7. Si un fichier est en erreur, il relance ou remplace uniquement ce fichier depuis le détail de la journée.
8. Il revient à la fiche professeur avec la flèche, sans perdre le contexte.

## 9. Critères d’acceptation

- [ ] Le badge `ARCHIVÉ` n’apparaît plus dans la fiche professeur.
- [ ] Le bloc `Prochaine diffusion` est visible sous le robot, à gauche.
- [ ] La prochaine journée et les dates sont calculées dynamiquement depuis le planning.
- [ ] Le texte distingue clairement la préparation audio H-48 de la vérification H-24.
- [ ] Les audios ne nécessitent plus d’action globale « remplir avec les audios ».
- [ ] Le PDF est généré à la fin de la pipeline de texte, indépendamment de H-48.
- [ ] Le PDF ne contient aucune balise technique et possède une page de garde lisible.
- [ ] L’onglet PDF autonome est supprimé.
- [ ] L’onglet Cours affiche chaque journée avec ses états audio et PDF.
- [ ] Un défaut de génération est visible, daté et relançable.
- [ ] Une correction manuelle est possible uniquement depuis la journée concernée.
- [ ] Planning, Cours, Élèves et Présence utilisent la taille de la grande modale existante.
- [ ] La navigation interne n’empile pas de modales et la flèche de retour restaure la fiche professeur.
- [ ] Les états de chargement, succès, avertissement et erreur sont compréhensibles au clavier comme à la souris.

## 10. Hors périmètre

- Recréer une bibliothèque globale de fichiers audio ou PDF.
- Demander à l’utilisateur d’affecter manuellement chaque fichier à un cours dans le cas nominal.
- Retarder la génération du PDF jusqu’à H-48.
- Hardcoder la journée 4 ou la date du 4 août 2026 dans l’interface.
- Modifier le planning métier ou les règles de diffusion elles-mêmes.
