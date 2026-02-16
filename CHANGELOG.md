# Changelog

## 2026-02-16

### Fix : Session cross-origin pour deploiement Azure (main_app.py)

- **Probleme** : apres login, la session Flask n'etait pas transmise aux requetes suivantes car les cookies de session ne traversent pas les domaines differents (frontend sur Static Web Apps, backend sur App Service)
- **Solution** : ajout de `SESSION_COOKIE_SAMESITE = "None"` et `SESSION_COOKIE_SECURE = True` en mode Azure
- Ces parametres permettent au navigateur d'envoyer le cookie de session dans les requetes cross-origin avec `credentials: 'include'`

### Refactor : Migration de tous les fetch('/api/...') vers apiUrl('/api/...') dans le frontend

- **Objectif** : centraliser la construction des URLs API via le helper `apiUrl()` (defini dans `frontend/src/api.js`) pour faciliter le deploiement multi-environnement (dev, staging, production)
- **Fichiers modifies** (10 fichiers, 26 appels fetch au total) :
  - `pages/LoginAdmin.jsx` (1 fetch)
  - `pages/Recorder.jsx` (4 fetches)
  - `pages/Video.jsx` (2 fetches)
  - `pages/Attente.jsx` (1 fetch)
  - `pages/Admin.jsx` (7 fetches)
  - `pages/Index.jsx` (1 fetch)
  - `pages/DebugCours.jsx` (5 fetches)
  - `components/ChatPanel.jsx` (1 fetch)
  - `components/ProtectedAdminRoute.jsx` (1 fetch)
  - `pages/GeneratedSlides.jsx` (3 fetches)
- Chaque fichier importe desormais `{ apiUrl } from '../api'`
- Aucun changement de comportement : refactor pur

## 2026-02-13

### Fix : Page d'attente affiche maintenant la vraie heure de debut (Attente.jsx)

- **Probleme** : le countdown etait hardcode a 3600 secondes, sans lien avec l'heure reelle du cours
- **Solution** : le frontend appelle `/api/cours-status` pour recuperer `temps_restant` et `heure_debut`
- Le countdown se re-synchronise avec le backend toutes les 30 secondes
- L'heure de debut reelle est affichee (ex: "Debut prevu a 09:00")
- Si le cours demarre pendant l'attente, redirection automatique vers `/video`
- Ajout de `heure_debut` dans la reponse de `/api/cours-status` (backend)

### Fix : Upload PDF purge l'ancien index avant reindexation (admin_routes.py)

- **Probleme** : quand un nouveau PDF etait uploade, l'ancien contenu restait dans l'index Azure AI Search (l'indexer ne supprime pas automatiquement les documents dont le fichier source a disparu)
- **Solution** : avant de relancer l'indexer, le code supprime maintenant tous les documents de l'index puis reset l'indexer
- Pipeline complet : suppression anciens blobs → upload nouveau PDF → purge index → reset indexer → run indexer

### Amelioration : Audio demarre en muet si autoplay bloque (Video.jsx)

- Au refresh, l'audio demarre maintenant **en muet** au lieu de rester bloque en pause
- L'audio est synchronise a la bonne position immediatement
- Le bouton "Activer le son" ne fait que de-muter (un seul clic, pas de rechargement)
- Meilleure UX : l'utilisateur n'a plus l'impression que le cours est "casse" apres un refresh

## 2026-02-12

### Ajout : Upload audio en arriere-plan avec reprise apres refresh

- **Backend** (`state.py`) : Ajout de `audio_upload_job` — dictionnaire global pour tracker le statut du job (idle/saving/converting/uploading/completed/error), la progression, et le rapport final
- **Backend** (`admin_routes.py`) : Refactoring de `POST /api/admin/upload-audios` :
  - Phase 1 (synchrone) : reception et sauvegarde des fichiers dans `/tmp`, retour immediat (HTTP 202)
  - Phase 2 (arriere-plan) : conversion MP3 + upload Azure via `socketio.start_background_task()` (compatible eventlet)
  - Garde-fou : refuse un nouvel upload si un job est deja en cours (HTTP 409)
  - Nouveau endpoint `GET /api/admin/audio-upload-status` : retourne le statut complet du job
- **Frontend** (`Recorder.jsx`) : Resilience au refresh :
  - Au chargement, verifie `audio-upload-status` et reprend le polling si un job est en cours
  - Barre de progression animee avec indication de phase (sauvegarde/conversion/upload)
  - Zone de drop desactivee pendant le traitement
  - Rapport final affiche des que le job termine (meme apres un refresh)

### Ajout : Upload PDF + Ré-indexation RAG Azure

- **Backend** (`admin_routes.py`) : Ajout de 2 routes admin :
  - `POST /api/admin/upload-pdf` — Upload d'un PDF dans Azure Blob Storage (conteneur `formationpdf`), suppression des anciens blobs, puis déclenchement de l'indexer Azure AI Search
  - `GET /api/admin/indexer-status` — Polling du statut de l'indexer (inProgress / success / failure)
- **Frontend** (`Admin.jsx`) : Nouvelle section drag & drop PDF dans le panneau admin avec :
  - Zone de glisser-déposer acceptant uniquement les `.pdf`
  - Bouton "Mettre à jour le cours" avec spinner pendant l'upload
  - Polling automatique du statut de l'indexer toutes les 3s après upload
  - Affichage dynamique du statut : en cours / terminé / erreur
  - Persistance du statut : vérification de l'indexer au chargement de la page, reprise automatique du polling si indexation en cours

### Ajout : Upload multi-audios vers Azure Blob Storage

- **Backend** (`admin_routes.py`) : Ajout de la route `POST /api/admin/upload-audios` :
  - Réception multi-fichiers audio (mp3, wav, ogg, m4a, flac, aac, wma, webm)
  - Nettoyage automatique des noms de fichiers (espaces → `_`, points en trop, caractères spéciaux)
  - Conversion automatique en MP3 via pydub si le format source n'est pas MP3
  - Suppression des anciens blobs puis upload dans le conteneur Azure `formationaudio-dev`
  - Rapport détaillé par fichier (original → nettoyé, converti ou non, erreurs éventuelles)
- **Frontend** (`Admin.jsx`) : Nouvelle section drag & drop audio dans le panneau admin :
  - Zone de glisser-déposer multi-fichiers avec aperçu des noms nettoyés avant upload
  - Bouton "Uploader les audios" avec spinner pendant le traitement
  - Rapport visuel post-upload (fichiers uploadés, conversions effectuées, erreurs)
- **Config** (`.env`) : Ajout de `AZURE_AUDIO_CONTAINER=formationaudio-dev` (conteneur de test)
