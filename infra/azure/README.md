# Stockage Azure — professeurs IA durables

Cette configuration accompagne SPEC-01. PostgreSQL conserve les identités,
versions, usages et chemins logiques. Azure Blob conserve une seule copie
canonique des documents et audios d'un professeur. Une promotion réutilisée
pointe vers cette copie et ne crée une surcharge que lorsqu'un fichier est
modifié (`copy_on_write`).

## État observé le 16 juillet 2026

- abonnement : `Azure subscription 1` (`3fbd881e-a7d7-4bdf-8cec-e1ac0a4ee9e4`) ;
- région des comptes inspectés : France Central ;
- `formationaudios` : StorageV2 Standard RAGRS, soft delete 7 jours, accès Blob public encore autorisé ;
- `documentstts` : StorageV2 Standard RAGRS, soft delete 7 jours, accès Blob public désactivé ;
- versioning Blob et règles de cycle de vie : non configurés au moment de l'inventaire.

L'inventaire a été effectué en lecture seule. Aucun changement n'est appliqué
automatiquement par le dépôt.

## Paramètres applicatifs recommandés

Sur Formation3, activer une identité managée et définir :

```text
AZURE_TTS_STORAGE_ACCOUNT_URL=https://documentstts.blob.core.windows.net
AZURE_MANAGED_IDENTITY_CLIENT_ID=<client-id si identité affectée par l'utilisateur>
```

Attribuer à cette identité le rôle minimal `Storage Blob Data Contributor` sur
le compte ou, de préférence, sur les containers nécessaires. Ne pas ajouter de
clé de compte ou de connection string dans Git. Le code conserve la connection
string comme fallback de développement local.

## Durcissement à valider puis appliquer

Les commandes suivantes sont volontairement manuelles. Elles doivent être
relues avec le propriétaire Azure avant exécution :

```bash
az account set --subscription 3fbd881e-a7d7-4bdf-8cec-e1ac0a4ee9e4

az storage account blob-service-properties update \
  --account-name documentstts \
  --resource-group deconnexion-auto-vendredi_group \
  --enable-versioning true \
  --enable-delete-retention true \
  --delete-retention-days 30 \
  --enable-container-delete-retention true \
  --container-delete-retention-days 30

az storage account management-policy create \
  --account-name documentstts \
  --resource-group deconnexion-auto-vendredi_group \
  --policy @infra/azure/storage-lifecycle-policy.json
```

Avant de désactiver `allowBlobPublicAccess` sur `formationaudios`, vérifier que
Front Door accède au container courant via origine privée, identité ou SAS. Les
containers d'archive créés par l'application sont privés ; seul le cache de
diffusion courant peut nécessiter une exposition contrôlée.

## Principes de rétention

- `audiostts` et `documenttts` : contenu canonique conservé, passage en Cool à 30 jours, anciennes versions supprimées après 90 jours ;
- `pipeline-artifacts` : diagnostics temporaires, Cool à 7 jours puis suppression à 45 jours ;
- archives des audios publiés : Cool à 30 jours puis Archive à 180 jours ;
- aucune règle ne supprime automatiquement la version courante d'un professeur durable.
