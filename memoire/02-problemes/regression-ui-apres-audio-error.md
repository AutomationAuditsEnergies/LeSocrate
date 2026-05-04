# Régression UI après `audio_error` — étapes validées qui semblent disparaître

**Date** : 2026-04-27
**Thématique** : problème
**Statut** : résolu

## Contexte

La pipeline `/formation-pipeline` est composée de 7 étapes affichées en empilement vertical. Chaque étape a un état visuel (en attente / en cours / terminé) calculé par `statusToStep(status, job)` à partir du statut de `formation_pipeline_jobs` et des champs concrets (`daily_programs_validated`, `kb_total`, etc.).

Quand un utilisateur lance le TTS (étape 7) et que celui-ci échoue (ex. 429 Google sur le mode gTTS, ou erreur Fish Audio), le backend bascule le statut du job en `audio_error`. Ce statut n'est **pas** un retour à l'étape 1 — il indique simplement "TTS a planté, les textes sont toujours là".

## Problème

Capture d'écran utilisateur du 2026-04-27 : sur l'étape 6 ("Génération des cours (texte)"), le badge `Terminé` s'affiche bien en haut à droite, mais le **corps de la carte** montre les boutons "Générer — Sonnet" et "Haiku" — ceux du mode "pending" — au lieu des boutons "Voir / Word / Word 2 / Rapport / Réviser conformité" qui devraient être présents pour des cours déjà générés.

L'utilisateur a immédiatement rapporté : « les cours ont disparu, il n'y a plus rien dans la pipeline ».

Vérifications croisées :
- Base SQLite : `content_generation_segments` contient bien 18 segments par folder avec `status='completed'` et `text_content` non-null.
- Azure Blob (`formationdocuments`) : les `.txt` finalisés sont bien présents (`platform-9/folder-5/...txt`, etc.).

Donc les données existent. Le bug est purement frontend.

## Cause racine

Dans `frontend/src/pages/FormationPipeline.jsx`, deux conditions filtraient l'accès aux contrôles de visualisation :

1. **Ligne ~2031** — la condition d'affichage du bloc "complété" de l'étape 6 :
   ```javascript
   {job.status === 'tts_launched' || job.status === 'audio_launched' || ttsResult ? (
   ```
   `audio_error` n'y figurait pas. Donc dès qu'une exécution TTS échouait, on basculait sur la branche pending, alors même que les textes étaient intacts.

2. **Ligne ~1098** — le `useEffect` qui charge `contentFolders` via `/api/formation/<id>/content` :
   ```javascript
   if (!['tts_launched', 'audio_launched'].includes(job.status)) return
   ```
   Même si la branche d'affichage acceptait `audio_error`, sans ce fetch les folders restaient vides. Effet bloquant en cascade.

3. **Ligne ~2284** — le bouton "Réviser conformité (étape 6bis) via Claude Code" était `disabled` pour tout statut autre que `tts_launched`/`audio_launched`. Or l'utilisateur peut légitimement vouloir lancer la révision sur des textes déjà générés alors que le TTS plante en aval.

## Options envisagées

**A.** Forcer côté backend que `audio_error` revienne à `tts_launched` après catch — rejeté : on perdrait l'information visuelle "TTS a planté", or l'utilisateur veut un signal rouge clair pour relancer.

**B.** Étendre les listes de statuts qui débloquent les contrôles avec `audio_error` (et autres statuts intermédiaires post-génération) — retenue.

**C.** Découpler complètement l'affichage du `job.status` et se baser uniquement sur l'existence de données (`contentFolders.some(f => f.content_status === 'completed')`) — partiellement retenue comme fallback robuste.

## Décision

Combiner **B** et **C** :

```javascript
// Ligne 2031 — condition d'affichage étendue
{job.status === 'tts_launched' ||
 job.status === 'audio_launched' ||
 job.status === 'audio_error' ||
 ttsResult ||
 (contentFolders.length > 0 &&
  contentFolders.some(f => f.content_status === 'completed')) ? (
```

Le fallback `contentFolders.some(...)` rend le UI robuste à tout futur statut intermédiaire qu'on pourrait ajouter : tant qu'il y a au moins une journée completed, on montre les contrôles.

## Rationale

> Si l'étape est validée, elle est validée — un échec d'étape ultérieure ne doit jamais masquer le résultat des étapes précédentes.

C'est un principe explicitement énoncé par l'utilisateur après plusieurs régressions du même type. La logique de `statusToStep` avait déjà été refondée pour utiliser des champs concrets plutôt qu'une cascade de statuts ; ce fix étend la même philosophie aux conditions d'affichage internes des cartes.

## Références code

- `frontend/src/pages/FormationPipeline.jsx:1098` — `useEffect` fetchContentFolders (ajout `audio_error`)
- `frontend/src/pages/FormationPipeline.jsx:2031` — condition d'affichage bloc complété étape 6
- `frontend/src/pages/FormationPipeline.jsx:2284` — bouton "Réviser conformité Claude Code" `disabled`
- `backend/services/formation_pipeline_service.py` — set status `audio_error` quand le greenlet `_run_audio` échoue

## Leçons

1. **Découpler affichage et statut** dès qu'on a un état "données persistantes" : préférer un fallback sur l'existence des données (`folders completed`) à une liste exhaustive de statuts.
2. **Fetch les données dès qu'elles peuvent exister** : un fetch conditionné par un statut bloque tous les fallbacks d'affichage.
3. **Tester les chemins d'erreur post-génération** au moins autant que les chemins succès : les utilisateurs voient PLUS souvent le UI en mode dégradé qu'en mode parfait.
4. **Les régressions silencieuses** (badge "Terminé" + boutons "Générer") sont les plus déroutantes pour l'utilisateur — il pense que la donnée a été détruite alors qu'elle est en DB. Avoir un mode "vue complète" qui ne dépend que de l'existence des données est une assurance.
