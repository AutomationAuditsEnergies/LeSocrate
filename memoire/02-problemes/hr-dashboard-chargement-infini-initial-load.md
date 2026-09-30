# HR Dashboard — chargement infini au premier affichage

**Date** : 2026-05-25
**Thématique** : problème | frontend | performance backend
**Statut** : résolu

## Contexte

Après les modifications de pipeline et de déploiement, la page publique :

`/hr-dashboard`

affichait un spinner de chargement infini. Le frontend restait bloqué sur l'état
`loading`, sans rendre le dashboard.

## Problème / Question

Le dashboard RH charge au démarrage la liste des plateformes via :

`GET /api/hr/platforms`

Cette route ne doit pas dépendre d'opérations lourdes. Elle est la porte d'entrée
du dashboard : si elle tarde ou bloque, toute l'interface semble cassée.

## Cause probable

La route backend faisait aussi des lectures Azure Blob trop larges pour construire
des statistiques de plateformes. Selon la taille des containers ou la latence Azure,
le chargement initial pouvait devenir trop lent.

Côté frontend, l'appel n'avait pas de timeout ni d'état d'erreur visible suffisant.
Résultat : un utilisateur voyait seulement un spinner.

## Décision finale

Le chargement initial du dashboard doit être léger et borné.

Décisions prises :

- ne pas inclure les statistiques Blob lourdes par défaut ;
- ajouter un paramètre `include_blob_stats=0` côté frontend ;
- borner les scans Azure Blob côté backend ;
- ajouter un timeout frontend ;
- afficher une erreur claire si le chargement dépasse ou échoue.

## Rationale technique

Un dashboard d'administration doit privilégier le temps de première interaction.

Les statistiques lourdes peuvent être :

- chargées à la demande ;
- paginées ;
- approximées ;
- bornées en temps ;
- ou rafraîchies en arrière-plan.

Elles ne doivent pas bloquer la liste principale.

## Références code

- `frontend/src/pages/HRDashboard.jsx`
  - timeout `AbortController` ;
  - appel `/api/hr/platforms?include_blob_stats=0` ;
  - état `platformsError`.
- `backend/routes/hr_routes.py`
  - `_summarize_blobs` ;
  - variables de bornage `HR_DASHBOARD_BLOB_PAGE_SIZE`,
    `HR_DASHBOARD_BLOB_MAX_ITEMS`, `HR_DASHBOARD_BLOB_TIMEOUT_SECONDS`.
- Commit lié :
  - `1f9f5d9` — Fix HR dashboard initial load

## Leçons / Pour le mémoire

Les dashboards de contrôle de pipelines longs doivent éviter les dépendances lentes
au chargement initial. La robustesse UX n'est pas seulement une question de design :
elle dépend directement de la forme des endpoints appelés au boot.
