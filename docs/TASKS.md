# TASKS - Pipeline Cours Formation → TTS

## Contexte global
Ajouter sur le **HR Dashboard** (`/hr-dashboard`) de la plateforme Socrate un système de **dossiers de cours dynamiques** par plateforme, avec upload de PDFs et pipeline TTS (fish.audio).

**Stack** : React 19 + Vite (frontend) / Flask + Gunicorn gthread (backend) / PostgreSQL ou SQLite local / Azure Blob Storage
**HR Dashboard existant** : `/Users/amelle/Desktop/SocrateReprise/LeSocrate/frontend/src/pages/HRDashboard.jsx`
**Backend routes HR** : `/Users/amelle/Desktop/SocrateReprise/LeSocrate/backend/routes/hr_routes.py`
**DB** : `/Users/amelle/Desktop/SocrateReprise/LeSocrate/backend/database/db.py`
**Config** : `/Users/amelle/Desktop/SocrateReprise/LeSocrate/backend/config.py`
**TTS de référence** : `/Users/amelle/Desktop/mistral_cours/text_to_speech.py`
**Voix fish.audio par défaut** : `90a39a3f3c0a45c38502fa1d99dabf96`
**API fish.audio** : `https://api.fish.audio/v1/tts`, modèle `s2-pro`, clé dans `.env` (`FISH_AUDIO_API_KEY`)

---

## Tâche 1 : Schéma DB — tables `cours_folders` et `cours_documents`

**Fichier** : `backend/database/db.py`
**Action** : Ajouter 2 tables dans la fonction `init_db()` (après les CREATE TABLE existants)

```sql
CREATE TABLE IF NOT EXISTS cours_folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cours_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL,
    status TEXT DEFAULT 'uploaded',  -- uploaded | processing | done | error
    audio_filename TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (folder_id) REFERENCES cours_folders(id)
);
```

**Statut** : [ ] À faire

---

## Tâche 2 : Routes backend CRUD dossiers de cours

**Fichier** : `backend/routes/hr_routes.py`
**Action** : Ajouter les routes suivantes dans le blueprint `hr_bp`

### 2a. Lister les dossiers d'une plateforme
- `GET /api/hr/platforms/<platform_id>/cours-folders`
- Retourne : `{ "folders": [{ "id", "name", "created_at", "document_count" }] }`

### 2b. Créer un dossier
- `POST /api/hr/platforms/<platform_id>/cours-folders`
- Body : `{ "name": "Cours 1" }`
- Retourne : `{ "id", "name" }`

### 2c. Supprimer un dossier
- `DELETE /api/hr/cours-folders/<folder_id>`
- Supprime le dossier + tous ses documents (fichiers + DB)

### 2d. Renommer un dossier
- `PATCH /api/hr/cours-folders/<folder_id>`
- Body : `{ "name": "Nouveau nom" }`

**Protection** : Les routes HR sont déjà protégées par le système d'auth existant.

**Statut** : [ ] À faire

---

## Tâche 3 : Routes backend upload/gestion de documents PDF

**Fichier** : `backend/routes/hr_routes.py`
**Action** : Ajouter les routes de gestion de documents

### 3a. Lister les documents d'un dossier
- `GET /api/hr/cours-folders/<folder_id>/documents`
- Retourne : `{ "documents": [{ "id", "filename", "original_name", "status", "audio_filename", "created_at" }] }`

### 3b. Uploader un ou plusieurs PDFs dans un dossier
- `POST /api/hr/cours-folders/<folder_id>/upload`
- Multipart form-data avec fichiers PDF
- Stockage local dans `backend/uploads/cours/<folder_id>/`
- Crée une entrée DB par fichier avec `status = 'uploaded'`

### 3c. Supprimer un document
- `DELETE /api/hr/cours-documents/<document_id>`
- Supprime le fichier PDF + l'audio MP3 si existant + l'entrée DB

### 3d. Télécharger un document PDF
- `GET /api/hr/cours-documents/<document_id>/download`
- Retourne le fichier PDF

### 3e. Télécharger l'audio généré
- `GET /api/hr/cours-documents/<document_id>/audio`
- Retourne le fichier MP3 (404 si pas encore généré)

**Statut** : [ ] À faire

---

## Tâche 4 : Service TTS — extraction PDF + conversion audio

**Fichier à créer** : `backend/services/tts_service.py`
**Référence** : `/Users/amelle/Desktop/mistral_cours/text_to_speech.py`

### 4a. Fonction `extract_text_from_pdf(pdf_path) -> str`
- Utiliser `PyPDF2` ou `pdfplumber` pour extraire le texte du PDF
- Ajouter `PyPDF2` (ou `pdfplumber`) dans `requirements.txt`

### 4b. Fonction `add_pedagogical_tags(text) -> str`
- Copier la logique de `/Users/amelle/Desktop/mistral_cours/text_to_speech.py` (lignes 24-39)
- Ajoute `[pause]`, `[long pause]`, `[short pause]` aux endroits appropriés

### 4c. Fonction `convert_to_speech(text, output_path, voice_id, model, speed) -> str`
- Reprendre la logique d'appel API de `text_to_speech.py` (lignes 74-109)
- Voice ID par défaut : `90a39a3f3c0a45c38502fa1d99dabf96`
- Modèle : `s2-pro`
- Clé API : `os.getenv("FISH_AUDIO_API_KEY")`
- `normalize: False` obligatoire pour les tags
- Header `model` dans les headers HTTP (pas dans le body)
- Sauvegarder le MP3 dans `backend/uploads/cours/<folder_id>/audio/`

### 4d. Fonction `process_document(document_id)`
- Pipeline complète : extraire texte → ajouter tags → appeler TTS → sauvegarder audio
- Met à jour le `status` en DB : `processing` → `done` ou `error`
- Met à jour `audio_filename` en DB quand c'est fait

**Statut** : [ ] À faire

---

## Tâche 5 : Route backend pour lancer la pipeline TTS

**Fichier** : `backend/routes/hr_routes.py`

### 5a. Lancer la TTS pour un document spécifique
- `POST /api/hr/cours-documents/<document_id>/generate-audio`
- Lance `process_document()` dans un thread local
- Retourne immédiatement `{ "status": "processing" }`

### 5b. Lancer la TTS pour tout un dossier
- `POST /api/hr/cours-folders/<folder_id>/generate-all-audio`
- Lance `process_document()` pour chaque document du dossier qui n'a pas encore d'audio
- Traitement séquentiel des documents (un par un pour ne pas surcharger l'API)

### 5c. Statut de la pipeline
- `GET /api/hr/cours-folders/<folder_id>/tts-status`
- Retourne le statut de chaque document : `{ "documents": [{ "id", "name", "status" }] }`

**Statut** : [ ] À faire

---

## Tâche 6 : Frontend — Composant `CoursFolders` pour le HR Dashboard

**Fichier à créer** : `frontend/src/components/CoursFolders.jsx`
**Intégrer dans** : `frontend/src/pages/HRDashboard.jsx`

### 6a. Vue dossiers (vue par défaut)
- Pour chaque plateforme (1, 2, 3), afficher un encadré "Cours de formation"
- Liste des dossiers avec icone dossier + nom + nombre de documents
- Bouton "+ Nouveau cours" pour créer un dossier (prompt le nom)
- Clic sur un dossier → ouvre la vue documents (6b)
- Bouton supprimer (icone poubelle) par dossier
- Style cohérent avec le reste du HR Dashboard (Tailwind, dark mode)

### 6b. Vue documents (quand on clique sur un dossier)
- Bouton retour "← Retour aux cours"
- Titre du dossier
- Zone de **drag & drop** pour déposer des PDFs (+ bouton "Parcourir")
- Liste des documents avec :
  - Nom du fichier
  - Statut (pastille : gris=uploaded, jaune=processing, vert=done, rouge=error)
  - Bouton télécharger PDF
  - Bouton écouter/télécharger audio (si disponible)
  - Bouton supprimer
- Bouton **"Générer tous les audios"** qui lance la pipeline TTS pour tout le dossier
- Polling du statut toutes les 3 secondes quand un traitement est en cours

**Statut** : [ ] À faire

---

## Tâche 7 : Intégration dans le HR Dashboard

**Fichier** : `frontend/src/pages/HRDashboard.jsx`
**Action** : 

- Importer et placer le composant `<CoursFolders platformId={X} />` dans chaque section de plateforme
- Le placer après les encadrés existants (audios, PDFs, etc.)
- Respecter le layout et le style existants

**Statut** : [ ] À faire

---

## Tâche 8 : Dépendances

**Fichier** : `backend/requirements.txt`
**Action** : Ajouter `PyPDF2` (ou `pdfplumber`) pour l'extraction de texte PDF

**Fichier** : `backend/.env` (ou `.env` racine)
**Action** : S'assurer que `FISH_AUDIO_API_KEY` est présente

**Statut** : [ ] À faire

---

## Ordre d'implémentation recommandé
1. Tâche 1 (DB) → 2 (routes dossiers) → 3 (routes documents) → 4 (service TTS) → 5 (route pipeline) → 6 (frontend composant) → 7 (intégration) → 8 (dépendances)

## Notes importantes
- **PAS de SSML** : fish.audio ne supporte pas les balises XML — utiliser les tags `[crochets]` S2-Pro
- **`normalize: false`** obligatoire dans le payload TTS
- **`reference_id`** (pas `voice_id`) dans le payload
- **Header `model`** dans les headers HTTP, pas dans le body JSON
- Le HR Dashboard est protégé par `ProtectedHRRoute` + variable d'env `HR_DASHBOARD_ENABLED`
