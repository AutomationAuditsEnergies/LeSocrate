# 📡 API Backend - Routes Disponibles

## 🔗 URL Backend
- **Développement:** `http://localhost:5001`
- **Frontend Vite proxy:** Configuré automatiquement pour `/api`

---

## 🔐 Routes d'Authentification

### POST `/api/auth/login`
Connexion utilisateur

**Request Body:**
```json
{
  "nom": "Dupont",
  "prenom": "Jean"
}
```

**Response (200):**
```json
{
  "success": true,
  "user": {
    "nom": "Dupont",
    "prenom": "Jean"
  },
  "log_id": 123
}
```

**Response (400):**
```json
{
  "success": false,
  "error": "Nom et prénom requis"
}
```

---

### POST `/api/auth/logout`
Déconnexion utilisateur

**Response (200):**
```json
{
  "success": true,
  "message": "Déconnexion réussie"
}
```

---

### POST `/deconnexion-auto`
Déconnexion automatique d'un utilisateur (interne)

**Response (204):** No content

---

### POST `/deconnexion-auto-tous`
Déconnexion automatique de TOUS les utilisateurs (Azure Logic Apps)

**Authentification :** session administrateur ou header
`X-Internal-Secret: <AUTO_LOGOUT_WEBHOOK_SECRET>`.

**Response (200):**
```json
{
  "success": true,
  "users_disconnected": 42
}
```

---

## 🎥 Routes Vidéo/Cours

### GET `/api/video/status`
Récupère l'état actuel du cours pour l'utilisateur connecté

**Requiert:** Session authentifiée

**Response - Cours en attente (200):**
```json
{
  "authenticated": true,
  "user": { "nom": "Dupont", "prenom": "Jean" },
  "status": "waiting",
  "heure_debut": "2025-05-28 16:35:00",
  "heure_actuelle": "2025-05-28 15:00:00",
  "temps_restant": 5700
}
```

**Response - Cours en cours (200):**
```json
{
  "authenticated": true,
  "user": { "nom": "Dupont", "prenom": "Jean" },
  "status": "playing",
  "audio_filename": "https://formationaudios.../cours_9h00_9h45.mp3",
  "audio_title": "Cours - Bloc 1 (9h00-9h45)",
  "audio_id": 1,
  "audio_type": "cours",
  "offset": 1234,
  "cours_termine": false
}
```

**Response - Cours terminé (200):**
```json
{
  "authenticated": true,
  "user": { "nom": "Dupont", "prenom": "Jean" },
  "status": "finished",
  "cours_termine": true
}
```

**Response - Non authentifié (401):**
```json
{
  "authenticated": false,
  "error": "Non authentifié"
}
```

---

### GET `/api/cours-status`
État du cours (sans authentification requise)

**Response (200):**
```json
{
  "status": "playing",
  "audio_id": 3,
  "audio_filename": "https://...",
  "audio_title": "Pause (9h55-10h05)",
  "audio_type": "pause",
  "offset": 125
}
```

**Statuts possibles:** `"waiting"`, `"playing"`, `"finished"`

---

### GET `/api/intro`
Page d'introduction

**Requiert:** Session authentifiée

**Response (200):**
```json
{
  "authenticated": true,
  "user": { "nom": "Dupont", "prenom": "Jean" },
  "message": "Page d'introduction"
}
```

---

## 👑 Routes Admin

### POST `/api/admin/login`
Connexion administrateur

**Request Body:**
```json
{
  "username": "admin",
  "password": "<mot-de-passe-du-déploiement>"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Connexion réussie"
}
```

**Response (401):**
```json
{
  "success": false,
  "error": "Identifiants incorrects"
}
```

---

### POST `/api/admin/logout`
Déconnexion administrateur

**Response (200):**
```json
{
  "success": true,
  "message": "Déconnexion réussie"
}
```

---

### GET `/api/admin/logs?prenom={prenom}`
Récupère les logs avec filtrage optionnel

**Requiert:** Session admin

**Query Params:**
- `prenom` (optionnel): Filtre par prénom

**Response (200):**
```json
{
  "success": true,
  "logs": [
    {
      "id": 1,
      "nom": "Dupont",
      "prenom": "Jean",
      "arrivee": "2025-05-28 09:00:00",
      "depart": "2025-05-28 18:30:00",
      "duree": "570 min 0 sec"
    }
  ],
  "prenom_recherche": "",
  "temps_total": "5 h 42 min 30 sec",
  "heure_debut_cours": "2025-05-28 09:00:00"
}
```

---

### POST `/api/admin/config_cours`
Configure l'heure de début du cours

**Requiert:** Session admin

**Request Body:**
```json
{
  "date_cours": "2025-05-28",
  "heure_cours": "09:00"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Heure de début mise à jour : 28/05/2025 à 09:00"
}
```

---

### GET `/api/admin/export_excel?prenom={prenom}`
Export Excel des logs

**Requiert:** Session admin

**Response:** Fichier Excel `historique.xlsx`

---

### POST `/api/admin/simulate-current-time`
Simule l'heure actuelle (debug)

**Requiert:** Session admin

**Request Body:**
```json
{
  "simulated_current_time": "2025-05-28T14:30:00"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Heure simulée: 2025-05-28 14:30:00"
}
```

---

### POST `/api/admin/reset-simulation`
Remet l'heure réelle

**Requiert:** Session admin

**Response (200):**
```json
{
  "success": true,
  "message": "Heure réelle restaurée"
}
```

---

### POST `/api/admin/force-logout-finished-users`
Force la déconnexion de tous les utilisateurs

**Requiert:** Session admin

**Response (200):**
```json
{
  "success": true,
  "message": "42 utilisateurs déconnectés",
  "disconnected_count": 42
}
```

---

## 🐛 Routes Debug

### GET `/api/debug/cours-info`
Informations détaillées du cours (debug)

**Requiert:** Session admin

**Response (200):**
```json
{
  "success": true,
  "debug_info": {
    "heure_debut_cours": "2025-05-28 09:00:00",
    "heure_actuelle": "2025-05-28 14:30:00",
    "simulation_active": false,
    "temps_ecoule_secondes": 19800,
    "temps_ecoule_minutes": 330,
    "duree_totale_cours_secondes": 34200,
    "duree_totale_cours_minutes": 570,
    "nombre_audios": 19,
    "status": "En cours",
    "audio_actuel_id": 11,
    "audio_actuel_titre": "Cours - Bloc 4 (13h50-14h35)",
    "audio_actuel_type": "cours",
    "offset_dans_audio": 1200,
    "duree_audio_actuel": 2700
  }
}
```

---

## 📝 Notes Importantes

1. **Sessions:** Le backend utilise des sessions Flask. Les cookies sont partagés via CORS avec `credentials: true`.

2. **CORS:** Configuré pour `http://localhost:5173` et `http://localhost:3000`.

3. **Proxy Vite:** Toutes les requêtes vers `/api` sont automatiquement proxiées vers `http://localhost:5001`.

4. **Authentification Admin:**
   - Username: `admin`
   - Mot de passe défini par `INTERNAL_ADMIN_PASSWORD_HASH` (recommandé) ou,
     temporairement, `INTERNAL_ADMIN_PASSWORD`. Aucun mot de passe par défaut
     n'est accepté.

5. **Timezone:** Toutes les dates sont en heure française (Europe/Paris).

6. **Format dates:** `YYYY-MM-DD HH:MM:SS`
