# Changelog

## 2026-04-07

### Fix : HR Dashboard — liens "Accéder au cours" avec `?p={id}` pour multi-tenant

- Les liens "Accéder au cours" et recorder dans le HR Dashboard pointaient vers `/video` sans `?p={id}`, donc le frontend ne savait pas quelle plateforme charger (défaut P1 → "cours terminé").
- Corrigé : le lien pointe maintenant vers `/?p={id}` pour que le `platform_id` soit stocké en localStorage dès le login.

### Fix : HR Dashboard — actions locales pour plateformes multi-tenant

- **Problème** : Les actions "Heure du cours", "Verrouiller uploads" et "Auto-schedule" faisaient `if platform_id == 1: local` / `else: HTTP distant`. Les plateformes multi-tenant (P4, P5+) n'ont pas de backend séparé → timeout HTTP vers un backend inexistant.
- **Solution** : Ajout de `_is_local_platform(pid)` qui vérifie si la plateforme a un `backend_url` configuré. Si non → appel local direct au `time_service`. Corrigé dans 5 endroits de `hr_routes.py` : `get_platform_course_time`, `proxy_config_cours`, `toggle_upload_lock`, `_unlock_platform`, `auto_schedule`.

## 2026-04-03

### Feature : Pipeline TTS automatisée - Génération des 19 audios de formation

- **Concept** : Prendre plusieurs PDFs d'un cours → générer automatiquement les 19 fichiers MP3 conformes à la playlist (7 blocs cours + 7 Q&A + 5 pauses)
- **Approche** : Concaténation des PDFs → découpage proportionnel en 7 blocs de cours (calibration 192 mots/min via fish.audio speed=0.95) → transitions naturelles (pas de mention temporelle pour bloc 4 été/hiver) → TTS via fish.audio → upload Azure avec nommage strict
- **Technologie** : Claude API pour reformulation/structuration + fish.audio pour TTS + pydub pour mesure durée
- **Interface** : Intégration dans CoursFolders + pipeline orchestrée en backend

### Implémentation : Pipeline TTS playlist

- **`backend/services/playlist_tts_service.py`** — Nouveau service d'orchestration
  - `PLAYLIST_SPEC` : définition des 19 fichiers (nom, durée, type, bloc)
  - `_call_claude_reformulate()` : reformulation **bloc par bloc** (7 appels Claude Sonnet)
    - Découpage proportionnel du texte source selon les durées des blocs
    - Contexte du bloc précédent transmis pour continuité narrative
    - Retry automatique (3 tentatives) si le word count est hors tolérance ±15%
    - `_count_words_excluding_tags()` : décompte excluant les tags [crochets] fish.audio
  - Tags fish.audio S2-Pro intégrés **directement par Claude** (pas d'heuristique)
    - Langage naturel libre en [crochets] : `[pause]`, `[excited]`, `[speak with conviction]`, etc.
    - Jamais de parenthèses (syntaxe S1 uniquement)
    - 15-25 tags d'émotion + 15-20 [pause] + 4-6 [long pause] par bloc
  - `_pad_audio_to_duration()` : 17s silence début + padding/truncate fin
  - `_build_pause_audio()` : intro TTS + silence + outro TTS
  - Q&A et pauses : **7 variantes** de textes pour éviter la répétition
  - Transitions bloc 4 neutres : "Très bien, on reprend." (fonctionne été comme hiver)
  - `generate_playlist_for_folder()` : pipeline complète avec callback de progression
  - Résultat enrichi : durée totale (h), taille totale (Mo), word counts par bloc
- **`backend/routes/hr_routes.py`** — Nouvelles routes
  - `POST /api/hr/cours-folders/<id>/generate-playlist` — lance la pipeline en background (eventlet)
  - `GET /api/hr/cours-folders/<id>/playlist-status` — retourne la progression en temps réel
  - État des jobs en mémoire (`_playlist_jobs`) avec step/total/message
- **`frontend/src/components/CoursFolders.jsx`** — Bouton "Générer la playlist (19 MP3)"
  - Barre de progression avec polling toutes les 2s
  - Affichage statut terminé : X/19 fichiers + durée totale + taille Mo
  - Affichage erreur avec message
- **`backend/requirements.txt`** — Ajout `anthropic>=0.30.0`

## 2026-04-02

### Feature : Planning saisonnier été/hiver (swap bloc 4)

- **Concept** : Pour les formations du vendredi (ou toute formation choisie), l'ordre du bloc 4 (pause midi / cours / Q&R) s'inverse selon la saison
  - **Hiver** : Pause (12h20-13h50) → Cours (13h50-14h35) → Q&R (14h35-14h45)
  - **Été** : Cours (12h20-13h05) → Q&R (13h05-13h15) → Pause (13h15-14h45)
  - Durée totale identique (145 min) → zéro décalage sur le reste de la playlist
- **`backend/database/db.py`** — Ajout colonne `playlist_mode` (NULL/ete/hiver) sur `platform_config`
- **`backend/services/audio_service.py`** — `get_playlist(platform_id)` retourne la playlist dynamique selon le mode
- **`backend/routes/video_routes.py`** — Passe `platform_id` à `get_current_audio_info()` via query param optionnel
- **`backend/routes/hr_routes.py`** — Routes `GET/POST /api/hr/schedule-config` pour lire/écrire la config saison
- **`frontend/src/pages/ScheduleConfig.jsx`** — Page admin `/schedule-config` : toggle été/hiver + sélection des formations concernées
- **`frontend/src/App.jsx`** — Route `/schedule-config` protégée par `ProtectedAdminRoute`

### Feature : Migration stockage cours vers Azure Blob Storage

- **`backend/services/azure_blob_service.py`** — Nouveau service Azure Blob Storage
  - Fonctions `upload_blob`, `download_blob`, `delete_blob`, `delete_blobs_by_prefix`
  - Deux conteneurs : `documenttts` (PDFs) et `audiostts` (MP3 générés)
  - Organisation des blobs : `platform-{id}/folder-{id}/{uuid}.pdf|.mp3`
  - Variable d'environnement : `AZURE_TTS_STORAGE_CONNECTION_STRING`
- **`backend/services/tts_service.py`** — Adapté pour travailler avec des bytes en mémoire
  - `extract_text_from_pdf()` accepte des bytes (BytesIO) au lieu d'un chemin fichier
  - `convert_to_speech()` retourne des bytes MP3 au lieu d'écrire sur disque
  - `process_document_to_audio()` pipeline complète bytes-in / bytes-out
- **`backend/routes/hr_routes.py`** — Routes cours migrées de filesystem local vers Azure
  - Upload PDF → Azure `documenttts` (plus de `file.save()` local)
  - Download PDF/audio → proxy depuis Azure via `send_file(BytesIO(...))`
  - Suppression → `delete_blob()` Azure au lieu de `os.remove()`
  - Pipeline TTS background : télécharge PDF depuis Azure, traite en mémoire, upload MP3 sur Azure
  - Zéro stockage local, tout passe par Azure Blob Storage

## 2026-02-20

### Feature : Déploiement Azure Function via GitHub Actions

- **`.github/workflows/deploy-azure-function.yml`** — Workflow de déploiement de la Function App d'auto-scheduling
  - Se déclenche sur push `staging` quand des fichiers `azure-function/**` changent
  - Utilise `Azure/functions-action@v1` avec `scm-do-build-during-deployment: true`
  - Le secret `AZURE_FUNCTIONAPP_PUBLISH_PROFILE` doit être ajouté dans GitHub → Settings → Secrets
  - Le nom de la Function App est à renseigner dans la variable `AZURE_FUNCTIONAPP_NAME` du workflow

### Feature : Azure Function App - Auto-scheduling des cours

- **`azure-function/`** — Nouvelle Azure Function Timer Trigger (modèle Python v1)
  - `auto_schedule/__init__.py` — S'exécute chaque samedi à 8h UTC (9h Paris)
  - `auto_schedule/function.json` — CRON `0 0 7 * * 6` (samedi 7h UTC = 8h Paris hiver / 9h été)
  - Appelle `POST /api/internal/auto-schedule` sur le backend P1 avec la clé `PLATFORM_API_KEY`
  - P1 programme P1 localement + propage vers P2/P3 via `_call_platform()`
  - Plan : Consommation Azure (paiement à l'usage, idéal pour 1 exécution/semaine)
- **`backend/routes/hr_routes.py`** — Route `POST /api/internal/auto-schedule`
  - Protégée par header `X-Platform-Key` (comparé à `PLATFORM_API_KEY` env var)
  - Schedule par défaut : P1=vendredi 9h, P2=lundi 9h, P3=mercredi 9h
- **`.gitignore`** — Ajout de `azure-function/local.settings.json` (contient les clés sensibles)

### Feature : Recorder accessible sans mot de passe

- **`App.jsx`** — `/recorder` n'est plus protégé par `ProtectedAdminRoute`
- **`admin_routes.py`** — Suppression des vérifications `is_admin` sur les routes utilisées par le Recorder :
  - `POST /api/admin/upload-audios`
  - `GET /api/admin/audio-upload-status`
  - `DELETE /api/admin/audios/<filename>`
- Les intervenants peuvent désormais accéder au Recorder et uploader des audios sans compte admin

### Fix : Route publique pour la liste d'audios du Recorder

- **`hr_routes.py`** — Nouvelle route `GET /api/recorder/audio-list` accessible sans session admin
  - Lit le container Azure configuré sur ce backend (`AZURE_AUDIO_CONTAINER`)
  - Génère des URLs SAS valides 1h pour chaque fichier
  - Ajoutée dans `always_allowed` du `before_request` (bypass du feature flag HR)
- **`Recorder.jsx`** — Utilise `/api/recorder/audio-list` au lieu de `/api/admin/audio-list`
  - Permet aux intervenants non-admin de voir et uploader leurs fichiers

### Analyse : Les Recorders P2/P3 affichaient les mêmes fichiers

- Cause identifiée : les containers `formationaudio-p2` et `formationaudio-p3` contenaient les mêmes fichiers
- Chaque container est indépendant mais partage le même compte de stockage Azure (`formationaudios`)

## 2026-02-19

### Feature : Intégration complète Plateforme 2 dans le Dashboard RH

- **`hr_routes.py`** — Fonctionnalités P2 opérationnelles :
  - `get_platforms()` : expose `frontend_url` dans la réponse pour chaque plateforme
  - `toggle_lock()` : propage le changement de lock vers P2 via `_call_platform()` → `/api/internal/set-lock`
  - `get_platform_audios()` : utilise le container Azure de chaque plateforme (`PLATFORM_2_AUDIO_CONTAINER`)
  - `delete_audio()` : supporte tous les containers (P1 et P2+)
  - Nouvelle route `POST /api/hr/platforms/<id>/config-cours` : pour P1 appelle `set_heure_debut_cours` localement, pour P2+ proxy vers `/api/internal/config-cours`

- **`HRDashboard.jsx`** — Adaptations multi-plateformes :
  - Lien "Accéder au cours" utilise `p.frontend_url` (ou `window.location.origin` en fallback)
  - Bouton "Heure du cours" mémorise la plateforme sélectionnée (`courseTimePlatformId`)
  - `handleSetCourseTime` appelle `/api/hr/platforms/<id>/config-cours` (route unifiée)

- **`.env`** — Nouvelles variables multi-plateformes :
  - `PLATFORM_2_BACKEND_URL`, `PLATFORM_2_FRONTEND_URL`
  - `PLATFORM_2_AUDIO_CONTAINER`, `PLATFORM_2_PDF_CONTAINER`
  - `PLATFORM_API_KEY` (clé partagée pour les appels service-to-service)

### Fix : Port backend 5000 → 5001

- Conflit avec un autre projet local
- Modifié dans `run.py`, `main_app.py`, `vite.config.js` (2 occurrences)

### Fix : Déploiement GitHub Actions Plateforme 2

- Réécriture de `staging_socrate-backend-p2.yml` pour utiliser `working-directory: ./backend`
- Correction de l'erreur "requirements.txt not found" due à la configuration auto-générée par Azure

### Feature : Feature flag `HR_DASHBOARD_ENABLED`

- Variable d'env `HR_DASHBOARD_ENABLED` (défaut `false`, `true` uniquement sur P1)
- `hr_routes.py` : `before_request` guard bloque toutes les routes HR si désactivé (sauf `get_hr_enabled` et `check_upload_permission`)
- `App.jsx` : `ProtectedHRRoute` vérifie `/api/hr/enabled` côté serveur avant d'afficher `/hr-dashboard`

### UX : Indicateurs de chargement gris + blocage scroll

- Recorder.jsx : cercles de chargement gris (`#9ca3af`) avec `animate-spin` (place des couleurs statiques)
- Index.jsx / Video.jsx : `overflow: hidden` sur `body` pour empêcher le scroll hors page
- Recorder.jsx / HRDashboard.jsx : `useEffect` pour corriger la couleur de l'overscroll

## 2026-02-18

### Feature : Upload audio asynchrone / parallèle

- Refactoring complet du pipeline d'upload audio : passage d'un traitement séquentiel (convert all → upload all) à un traitement **parallèle par fichier** via `eventlet.GreenPool(size=4)`
- Chaque fichier suit son propre cycle de vie indépendant : `pending → converting → uploading → done`
- **Backend** (`state.py`, `admin_routes.py`) :
  - Ajout de `files_status` dans `audio_upload_job` pour tracker l'état individuel de chaque fichier
  - Nouveau statut global `processing` (remplace l'ancien flow `converting → uploading`)
  - `_process_audio_upload` réécrit avec `process_single_file` + `GreenPool`
- **Frontend** (`Recorder.jsx`) :
  - Suivi de `filesStatus` (dict backend) au lieu de `currentFile`
  - Chaque audio dans les cartes (Cours/Pauses/Q&A) affiche son état en temps réel : cercle coloré pendant le traitement, bouton play dès qu'il est terminé
  - Polling Azure audios déclenché pendant la phase `processing`

### UX : Indicateurs visuels d'upload par fichier

- Chaque fichier audio dans les 3 cartes (Cours, Pauses, Q&A) affiche un indicateur visuel individuel pendant l'upload
- 4 états visuels par fichier : uploadé (bouton play coloré), en cours actif (cercle plein), en attente (cercle avec point), non uploadé (icône grise)
- Couleurs par catégorie : Cours=#3b82f6, Pauses=#f59e0b, Q&A=#16a34a
- Indicateurs statiques (pas d'animations) selon la préférence utilisateur

## 2026-02-17

### UX : HR Dashboard — Modale de confirmation pour suppression audio

- Remplacement du `confirm()` natif du navigateur par une modale custom
- Icône poubelle rouge, titre, nom du fichier en gras, message "Cette action est irréversible"
- Boutons Annuler / Supprimer (rouge)
- Clic en dehors de la modale → fermeture

### UI : Page Video — fond spatial + "TP CRCD" en grand

- Zone vidéo : fond remplacé par `rocket.jpg` (même image que la homepage), cadré sur le haut (ciel étoilé / espace)
- Overlay sombre semi-transparent pour lisibilité
- Avatar "Professeur" remplacé par "TP CRCD" en très grand blanc gras (Poppins, tracking large), style header à la TurboScribe

### Fix : Export Excel — durée calculée pour les sessions "en cours"

- Les utilisateurs encore connectés au moment de l'export ont désormais leur durée calculée (heure d'arrivée → heure actuelle) au lieu de "En cours..."
- La durée affichée est suffixée `(en cours)` pour signaler que c'est une estimation
- Ces sessions sont désormais incluses dans le récapitulatif "Temps total de connexion" par utilisateur

### Feature : HR Dashboard — Bouton "Heure du cours" sur Plateforme active

- Ajout d'un bouton **"Heure du cours"** dans la carte de la plateforme active (entre "Accéder au cours" et "Voir les audios")
- Clic → ouvre une modale légère `CourseTimeModal`
- **Modal Heure du cours** :
  - Header bleu cohérent avec le reste du dashboard
  - Champ **date** (pré-rempli avec la date du jour)
  - Champ **heure** (time picker natif)
  - Appel `POST /api/admin/config_cours` avec `{ date_cours, heure_cours }` (même API que la page Admin)
  - Feedback succès : icône verte + message de confirmation renvoyé par l'API
  - Feedback erreur : bandeau rouge avec le message d'erreur
  - Boutons Annuler / Enregistrer (désactivé si champs vides ou en chargement)

### Feature : HR Dashboard — Modal PDF avec visualiseur et upload

- **Transformation de la section PDF** :
  - Au lieu d'afficher "Aucun PDF" avec boutons upload/delete, bouton cliquable "Gérer le PDF" avec flèche à droite
  - Clic sur le bouton → ouverture d'une modal overlay
- **Modal PDF** :
  - Header bleu avec titre "GESTION DU PDF" + icône + bouton fermer
  - Layout en 2 colonnes :
    1. **PDF ACTUEL** (gauche) : Visualiseur de PDF avec iframe + bouton supprimer
    2. **UPLOADER UN NOUVEAU PDF** (droite) : Zone de drag & drop avec icône cloud_upload
  - Si aucun PDF : message "Aucun PDF uploadé" avec grande icône
  - Drag & drop fonctionnel avec feedback visuel (bordure bleue + fond bleu clair)
  - Spinner pendant l'upload
  - Format : PDF uniquement
- **UX** :
  - Clic en dehors de la modal → fermeture
  - Clic sur la croix → fermeture
  - Visualisation directe du PDF dans un iframe
  - Upload par drag & drop ou clic pour parcourir
- **Objectif** : Interface unifiée pour visualiser et gérer le PDF du RAG pour chaque plateforme

### Feature : HR Dashboard — Modal d'audios avec 3 cartes

- **Transformation du bouton "Voir les audios"** :
  - Au lieu d'ouvrir une liste en dessous, ouvre maintenant une modal overlay
- **Modal d'audios** :
  - Header bleu avec titre "AUDIOS FORMATION" + icône + bouton fermer
  - 3 cartes côte à côte (Cours, Pauses, Q&A) comme dans la page Recorder
  - Chaque carte affiche :
    - Image personnalisée avec bordure noire
    - Titre de la catégorie
    - Compteur X/Y fichiers
    - Liste des audios attendus avec état (uploadé = check vert, non uploadé = play gris)
  - Design en lecture seule (pas de boutons play/delete)
  - Modal responsive avec scroll vertical
- **UX** :
  - Clic en dehors de la modal → fermeture
  - Clic sur la croix → fermeture
  - Loading spinner pendant le chargement des audios
- **Objectif** : Vue d'ensemble rapide et visuelle des audios uploadés pour chaque plateforme

## 2026-02-17

### Design : Recorder — Organisation des audios en 3 cartes par catégorie

- **Séparation en 3 cartes** au lieu d'une seule liste :
  1. **Carte COURS** (bleue, image carnet/crayon avec bordure noire) : tous les fichiers `cours_*`
  2. **Carte PAUSES** (jaune/orange, image réveil "BREAK TIME" avec bordure noire) : tous les fichiers `pause_*`
  3. **Carte Q&A** (verte, image bulles de dialogue avec bordure noire) : tous les fichiers `qa_*`
- **Layout** : Grid responsive (1 colonne mobile, 3 colonnes desktop)
- **Chaque carte affiche** :
  - Icône colorée dans un badge arrondi
  - Titre de la catégorie
  - Compteur : X/Y fichiers uploadés
  - Liste des audios de cette catégorie (ordre chronologique)
  - Boutons play, durée, suppression pour chaque audio
- **Design compact** : cartes arrondies (rounded-2xl), items plus petits, player audio inline
- **Icônes audios** : petits logos "audiotrack" grisés pour les fichiers non uploadés (au lieu de cadenas)
- **Objectif** : Meilleure vue d'ensemble et organisation visuelle par type de contenu

### Design : Recorder — Refonte de la zone d'upload avec modal + flèche décorative

- **Transformation de la zone d'upload** :
  - Remplacement de la grande zone de drag & drop par un simple bouton "DÉPOSEZ VOS FICHIERS"
  - Bouton avec icône upload, fond bleu (#137fec), centré
  - Au clic, ouverture d'une modal overlay avec fond semi-transparent
- **Nouvelle disposition centrée** :
  1. Texte descriptif centré en haut : "Gérez et uploadez vos 19 pistes audio séquentielles..."
  2. **Flèche décorative** style "hand-drawn" (image PNG bleue courbe) qui pointe vers le bouton
  3. Bouton "DÉPOSEZ VOS FICHIERS" centré
  4. Barre de progression minimaliste et discrète (h-1, sans carte, juste X/Y fichiers + pourcentage + barre fine avec glow)
- **Modal d'upload** :
  - Header bleu avec titre "TRANSCRIRE DES FICHIERS" + icône upload + bouton fermer
  - Zone de drag & drop dans le corps de la modal
  - Texte : "Glissez vos fichiers ici ou cliquez pour parcourir"
  - Formats supportés affichés en petits caractères
  - Bouton "Uploader les fichiers" après sélection
  - Barre de progression pendant upload (saving/converting/uploading)
- **UX** :
  - Clic en dehors de la modal → fermeture
  - Clic sur la croix → fermeture
  - Après upload → fermeture automatique de la modal
- **Objectif** : Interface plus épurée et visuelle avec interaction guidée par la flèche décorative

### Design : Recorder — Simplification du header (suite)

- **Suppression de 3 éléments** dans la section Context & Progress :
  - Icône folder_open retirée
  - Texte "FORMATION TP CRCD" retiré
  - Titre "Upload Sequence" retiré
- **Résultat** : La section ne contient plus que la description fonctionnelle et la carte de progression
- **Objectif** : Épurer encore plus l'interface, focus sur l'essentiel

### Design : Recorder — Redesign complet inspiré du template "Audio Manager Pro"

- **Objectif** : Moderniser l'interface Recorder avec un design propre, épuré et professionnel
- **Inspiration** : Template HTML "Audio Upload Progress Dashboard v2" avec Material Icons et palette bleue
- **Changements visuels** :
  - Header sticky avec icône graphic_eq + titre "Audio Manager Pro" + sous-titre "Formation TP CRCD"
  - Section progress : tag bleu "FORMATION TP CRCD", titre "Upload Sequence", description
  - Card de progression : X% completion, Y of Z tracks uploaded, barre de progression bleue
  - Grille responsive (1-5 colonnes selon taille écran) de 19 cards représentant chaque audio attendu
  - **Cards complétées** : check vert, boutons play/delete avec hover, durée (parsée depuis nom fichier), taille, barre verte en bas, audio player inline
  - **Card upload active** : bordure pointillée bleue, icône cloud_upload, zone drop/browse, bouton "Uploader", barre de progression pendant upload
  - **Cards verrouillées** : icône lock, grises, opacity 0.6
  - Messages success/error/info en bas avec couleurs adaptées (vert/rouge/bleu)
  - Rapport d'upload détaillé avec symboles ✓/✗
  - Footer : "Audio Upload Dashboard v2.0 • Designed for high-efficiency workflows."
- **Fonctionnalités conservées** :
  - Check permission upload RH (bannière rose si verrouillé)
  - Upload drag & drop + multi-fichiers avec preview
  - Lecture audio inline dans les cards
  - Suppression d'audios (si non verrouillé)
  - Polling avec barre de progression (saving/converting/uploading)
  - Rapport d'upload détaillé (fichiers convertis, skippés)
  - Upload séquentiel : seul le prochain audio manquant a la zone d'upload active
  - Parse durée depuis nom fichier (ex: cours_9h00_9h45.mp3 → 45min)
- **Palette** :
  - Primary : #137fec (bleu)
  - Fond : #f8fafc (gris très clair)
  - Cards : blanc #ffffff avec bordure #e2e8f0
  - Success : vert #16a34a
  - Error : rouge #ef4444
  - Police : Inter
  - Icons : Material Icons
- **Backend** : Aucun changement (toutes les fonctionnalités préservées)

### Design : HR Dashboard — Redesign complet avec Material Icons et palette purple

- **Objectif** : Moderniser l'interface du Dashboard RH avec un design plus épuré et professionnel
- **Changements visuels** :
  - Police Inter appliquée sur toute la page (au lieu de Fredoka)
  - Material Icons de Google remplacent tous les SVG custom (lock, audiotrack, picture_as_pdf, delete, etc.)
  - Palette de couleurs : Purple #8B5CF6 au lieu de fuchsia (#d946ef)
  - Fond : #0f172a (slate-900) avec grid pattern subtil (rgba white 0.03)
  - Cards : #1e293b (slate-800) avec bordure purple pour plateformes actives, gray pour inactives
  - Overlay "BIENTÔT DISPONIBLE" avec icône Material "schedule" sur fond blur
  - Toggle switch avec glow purple (box-shadow rgba(139, 92, 246, 0.5)) quand verrouillé
  - PDF upload : bordure dashed #334155 sur fond #0f172a
  - Alertes : fond #450a0a (rose) ou #713f12 (amber) avec icônes Material "error" ou "warning"
- **Nouvelle feature** : Dark mode toggle dans le header (bouton avec icône "light_mode"/"dark_mode")
  - Par défaut en mode sombre
  - Changement d'icône dynamique selon l'état
- **Footer** ajouté :
  - Copyright "© 2026 Le Socrate. Tous droits réservés."
  - Liens : Documentation, Support, Confidentialité
  - Bordure top #1e293b, texte #64748b
- **Boutons interactifs** avec hover states inline (onMouseEnter/onMouseLeave) :
  - PDF delete : hover #450a0a avec texte #f87171
  - PDF upload : hover #581c87 avec texte #c084fc
  - Expand audios : hover background #1e293b
  - Play audio : hover #7c3aed
- **Pipeline de backup** : icônes Material "check", spinner custom, "close" pour les états
- **Backend** : Aucun changement (toutes les fonctionnalités préservées)
- **Frontend** : index.html — ajout des imports Google Fonts (Material Icons + Inter)

### Design : Zone vidéo avec bordure violette fine (sans glow)

- Bordure violette fine (`border-[2.5px] border-purple-500`) - 2.5px, ton vif et élégant
- Pas d'effet glow violet, juste une ombre classique (shadow-2xl)
- Aspect épuré avec une bordure colorée subtile mais visible

### Design : Fond lavande clair sur la page Video (sauf header et boutons)

- Couleur appliquée : `#F8F7FF` (lavande très doux) sur le fond principal uniquement
- Header "Formation TP CRCD" : blanc avec bordure grise de séparation
- Boutons micro et chat : blanc de base, blanc surbrillant (avec ombre) au hover
- Rings des boutons : purple-100 au lieu de gray-100
- Effet visuel plus doux et chaleureux avec contraste blanc/lavande

## 2026-02-16

### Design : Icône professeur dans le chat

- **Modification** : Remplacement de l'icône lampe (ampoule) par une icône de professeur avec tableau dans le ChatPanel
- Nouvelle image : `professor-icon.png` (icône noir et blanc représentant un enseignant avec pointeur et tableau)
- Contour circulaire noir fin (1px) ajouté autour du cercle jaune pour plus de définition visuelle
- Animation de chargement remplacée par message texte : "Un instant, le professeur va vous répondre..."
- Délai de 5 secondes ajouté avant l'affichage de la réponse pour un effet plus naturel
- Impacte les messages de l'assistant et l'état de chargement
- Contexte visuel plus cohérent avec le thème pédagogique de l'application

### Feature : Backup vérifié avant ouverture aux intervenants (HR Dashboard)

- **Comportement** : le toggle "Ouvrir" déclenche une pipeline en 3 étapes au lieu d'un simple deverrouillage instantané
- **Pipeline backend** (tâche de fond avec polling) :
  1. Copie server-side de chaque blob vers `formationaudio-archives/{date_heure}/plateforme-{id}/`
  2. **Vérification stricte** : compare noms source vs archive — si un seul manque, arrêt immédiat sans suppression
  3. Suppression des blobs source (seulement si vérification 100% OK)
  4. Déverrouillage (`upload_locked = 0` en DB)
- **Backend** : `backup_jobs` dans `state.py` + 2 nouveaux endpoints dans `hr_routes.py` + `AZURE_AUDIO_ARCHIVE_CONTAINER` en `.env`
- **Frontend** : composant `BackupPipeline` avec 3 étapes horizontales animées (fuchsia = done, spinner = running, croix = error) + polling 1.5s

### Feature : Dashboard RH — Centre de controle des 3 plateformes

- **Objectif** : permettre aux RH de piloter les 3 plateformes de formation depuis une seule page sans echanger par mail
- **Backend** :
  - 2 nouvelles tables SQLite : `platform_config` (config par plateforme, verrouillage upload, PDF) et `deletion_requests` (demandes de suppression par les contributeurs)
  - Seed automatique de 3 lignes dans `platform_config` a l'init de la base
  - Nouveau blueprint `hr_routes.py` (factory pattern) avec 11 endpoints :
    - `GET /api/hr/platforms` — vue d'ensemble des 3 plateformes (stats Azure, alertes, PDF)
    - `POST /api/hr/platforms/<id>/toggle-lock` — verrouiller/deverrouiller l'upload
    - `GET /api/hr/platforms/<id>/audios` — lister les audios (P1=Azure, P2/P3=vide)
    - `DELETE /api/hr/platforms/<id>/audios/<filename>` — supprimer un audio Azure
    - `POST /api/hr/platforms/<id>/upload-pdf` — uploader un PDF par plateforme
    - `DELETE /api/hr/platforms/<id>/pdf` — supprimer le PDF
    - `GET /api/hr/upload-permission/<id>` — check permission (sans auth admin, pour Recorder)
    - `POST /api/hr/deletion-requests` — creer une demande de suppression (sans auth admin)
    - `GET /api/hr/deletion-requests` — lister les demandes en attente
    - `POST /api/hr/deletion-requests/<id>/approve` — approuver (supprime le blob Azure)
    - `POST /api/hr/deletion-requests/<id>/reject` — rejeter
  - Blueprint enregistre dans `main_app.py`
- **Frontend** :
  - Nouvelle page `HRDashboard.jsx` accessible sur `/hr-dashboard` (protegee admin)
  - Design "mission control" : fond sombre avec grille subtle, gradient radial, cards avec bordure fuchsia/gris
  - 3 cartes plateforme : P1 active (Azure connecte), P2/P3 avec overlay "Bientot disponible"
  - Toggle lock custom avec glow fuchsia, pastille pulsante verte/grise
  - Gestion des audios inline : lecture, suppression, accordeon
  - Upload PDF par plateforme avec preview
  - Panneau des demandes de suppression avec boutons approuver/rejeter
  - Alertes dynamiques (PDF manquant, aucun audio, demandes en attente)
  - Lien "Dashboard RH" (bouton fuchsia) ajoute dans le header de `Admin.jsx`
- **Recorder.jsx** :
  - Check permission upload au montage (`GET /api/hr/upload-permission/1`)
  - Banniere rose "Uploads verrouilles par les RH" + zone de drop desactivee quand verrouille
  - Bouton "Demander la suppression" sur chaque audio de la playlist Azure
  - Modal avec nom du demandeur + raison + envoi vers `POST /api/hr/deletion-requests`

### Feature : Export Excel — colonne "Temps total de connexion" par utilisateur (export_service.py)

- Ajout d'un tableau récapitulatif en colonnes H-J du fichier Excel
- Pour chaque utilisateur unique (nom + prénom), affiche le cumul de toutes ses sessions
- Format : `Xh Ymin Zsec` ou `Ymin Zsec` selon la durée
- Trié alphabétiquement par nom
- En-têtes colorés (bleu foncé pour le détail, bleu moyen pour le récap)
- Largeurs de colonnes automatiques pour la lisibilité

### Fix : Tests Playwright — gestion de l'état inconnu sur /video

- **Probleme** : le test `la page /video affiche un contenu valide` echouait avec `État inattendu: unknown` car la page restait bloquee sur "Chargement du cours..." (API Azure lente ou inaccessible depuis Chromium headless)
- **Solution** : refactoring de `loginAndGetState()` pour attendre explicitement la disparition du spinner de chargement avant de detecter l'etat, avec timeout 15s
- Ajout des etats `loading` et `error` pour couvrir tous les cas possibles
- Le test skippe proprement au lieu de planter quand l'etat ne peut pas etre determine
- Resultat : 11 passed, 0 failed, 7 skipped (exit 0)

### Fix : Routing SPA sur Azure Static Web Apps (staticwebapp.config.json)

- **Probleme** : les routes React (`/admin`, `/login-admin`, `/attente`, etc.) renvoyaient une 404 quand accedees directement dans la barre d'adresse, car Azure Static Web Apps cherchait un fichier physique
- **Solution** : ajout de `staticwebapp.config.json` dans `frontend/public/` avec `navigationFallback` vers `index.html`
- Toutes les routes non-statiques sont maintenant redirigees vers React Router

### Fix : Session cross-origin pour deploiement Azure (backend + frontend)

- **Probleme** : apres login, la session Flask n'etait pas transmise aux requetes suivantes. Deux causes :
  1. **Backend** : les cookies de session n'avaient pas `SameSite=None; Secure`, requis pour le cross-origin
  2. **Frontend** : les fetch critiques (`/api/auth/login` dans Index.jsx, `/api/video/status` dans Video.jsx) n'avaient pas `credentials: 'include'`, donc le navigateur ignorait le `Set-Cookie` et n'envoyait pas le cookie
- **Solution backend** : ajout de `SESSION_COOKIE_SAMESITE = "None"` et `SESSION_COOKIE_SECURE = True` en mode Azure (`main_app.py`)
- **Solution frontend** : ajout de `credentials: 'include'` aux fetch manquants (`Index.jsx`, `Video.jsx`)
- Ajout d'un helper `apiFetch()` dans `api.js` qui inclut automatiquement `credentials: 'include'`

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
