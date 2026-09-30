# Modales d'audit pipeline — artefacts, événements et diffs avant/après

**Date** : 2026-05-25
**Thématique** : solution | frontend | auditabilité
**Statut** : actif

## Contexte

La roadmap auto-pilot API affiche les étapes de fabrication du contenu :

- plan ;
- génération ;
- micro-conformité ;
- artefacts ;
- calibrage ;
- reviews ;
- slides ;
- audio.

L'affichage "OK / À venir" permettait de suivre l'avancement, mais pas de comprendre
ce que chaque étape avait concrètement fait.

## Problème / Question

L'utilisateur veut pouvoir contrôler la pipeline. Pour cela, il ne suffit pas de
dire qu'une étape est terminée.

Il faut pouvoir répondre à des questions précises :

- quel artefact a été produit ?
- quel texte a été modifié ?
- quelle règle a déclenché une correction ?
- quel passage était problématique ?
- quelle correction a été appliquée ?
- quelle étape a introduit ou réparé un problème ?

Cas central : l'étape 9, micro-conformité éthique.

Besoin demandé :

- à gauche, afficher le texte original avec les passages problématiques en rouge ;
- à droite, afficher le texte corrigé avec les remplacements en bleu ;
- permettre de vérifier les règles et les raisons.

## Solution mise en place

Chaque carte de la roadmap pipeline est devenue cliquable.

Au clic, une modale affiche :

- le statut de l'étape ;
- les événements pipeline associés ;
- les artefacts JSON liés ;
- les rapports disponibles ;
- les statistiques utiles ;
- les patches avant/après quand ils existent.

## Cas spécifique : micro-conformité éthique

La pipeline persiste maintenant :

`content-ethical-micro-review.json`

Cet artefact contient :

- les sections auditées ;
- le texte original complet ;
- le texte final ;
- la liste des patches ;
- la règle concernée ;
- la raison de la correction ;
- le statut du patch.

La modale frontend lit cet artefact et affiche les corrections sous forme de diff :

- panneau gauche rouge : passage original problématique ;
- panneau droit bleu : passage corrigé ;
- contexte complet de la section ;
- méta-informations de règle.

## Cas spécifique : humanisation et conformité finale

Les étapes d'humanisation et conformité finale utilisent les rapports existants :

- `humanization-report` ;
- `review-report`.

Quand les rapports contiennent des patches, la modale les présente aussi en
avant/après.

## Cas générique : artefacts de pipeline

Pour les autres étapes, la modale charge les artefacts liés :

- `content-plan.json` ;
- `content-draft-sections.json` ;
- `content-course-scripts.json` ;
- `content-quality-reviews.json` ;
- `content-reviewed-scripts.json` ;
- `content-audio-plan.json`.

Cela permet d'inspecter le contenu exact produit par une étape, même sans diff.

## Endpoint API ajouté

Nouvel endpoint :

`GET /api/formation/<job_id>/content/<folder_id>/artifact/<filename>`

Caractéristiques :

- accès admin obligatoire ;
- vérifie que le folder appartient bien au job ;
- n'autorise que les artefacts connus ;
- retourne le contenu JSON de l'artefact ;
- évite d'exposer arbitrairement des chemins Azure.

## Rationale technique

L'auditabilité doit être intégrée à l'interface, pas seulement disponible dans les
logs. Les logs servent au développeur ; les modales d'audit servent au pilotage du
produit.

Cette solution rend visible la chaîne de transformation :

- avant ;
- après ;
- règle ;
- décision ;
- artefact.

Elle prépare aussi une future étape : éditer, accepter ou rejeter des patches depuis
l'interface.

## Limite importante

Les anciennes générations n'ont pas `content-ethical-micro-review.json`, car cet
artefact n'existait pas encore.

Pour voir les diffs rouges/bleus de l'étape 9, il faut relancer une génération avec
la nouvelle pipeline.

## Références code

- `frontend/src/pages/FormationPipeline.jsx`
  - `PipelineStepAuditModal`
  - `EthicalMicroAuditView`
  - `ReviewReportsAuditView`
  - `PatchBeforeAfter`
  - `DiffPane`
  - `HighlightedText`
  - `ArtifactAuditView`
- `backend/routes/formation_routes.py`
  - endpoint artefact pipeline.
- `backend/services/content_generation_service.py`
  - enregistrement des micro-reviews éthiques.
- `backend/services/content_pipeline/artifacts.py`
  - liste des artefacts autorisés.
- Commit lié :
  - `e48d2b1` — Add clickable pipeline audit modals

## Leçons / Pour le mémoire

Une pipeline IA longue ne doit pas être une boîte noire. L'utilisateur doit pouvoir
inspecter les preuves intermédiaires et comprendre les corrections.

La modale d'audit transforme l'auto-pilot en système contrôlable : automatisé dans
l'exécution, mais explicable dans ses décisions.
