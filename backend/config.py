# config.py - Configuration centralisée pour l'application
import os
import pytz

# Fuseau horaire français
FRANCE_TZ = pytz.timezone("Europe/Paris")

# Configuration Flask
SECRET_KEY = os.getenv("SECRET_KEY", "fallback_secret_key_for_dev")
_student_auth_default = (
    "0"
    if os.getenv("DATABASE_BACKEND", "sqlite").strip().lower()
    in {"postgres", "postgresql", "supabase"}
    else "1"
)
STUDENT_AUTH_LEGACY_FALLBACK = os.getenv(
    "STUDENT_AUTH_LEGACY_FALLBACK", _student_auth_default
).lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# Configuration Azure - URL du service RAG
RAG_SERVICE_URL = os.getenv(
    "RAG_SERVICE_URL", "https://rag-b0fndpa9fycaafcr.francecentral-01.azurewebsites.net"
)

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# Postgres cible pour le SaaS multi-tenant.
# En pratique, utiliser l'URL "Connection string" Supabase/Postgres en variable
# d'environnement, jamais en dur dans le repo.
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL", "")
DATABASE_BACKEND = os.getenv("DATABASE_BACKEND", "sqlite").strip().lower()
PIPELINE_DATABASE_BACKEND = os.getenv("PIPELINE_DATABASE_BACKEND", "sqlite").strip().lower()
PIPELINE_POSTGRES_MIRROR = os.getenv("PIPELINE_POSTGRES_MIRROR", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def sqlite_runtime_enabled() -> bool:
    """Whether any authoritative runtime domain still requires SQLite.

    ``hybrid`` and ``postgres_core`` are explicit migration modes. A deployment
    configured with both business and pipeline data on Postgres must not create,
    validate, back up, or silently read a local SQLite database.
    """
    return (
        DATABASE_BACKEND in {"sqlite", "hybrid", "postgres_core"}
        or PIPELINE_DATABASE_BACKEND not in {"postgres", "postgresql", "supabase"}
    )
SQLITE_SAFETY_STRICT = os.getenv("SQLITE_SAFETY_STRICT", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# Base de données - /home est persistant sur Azure App Service, /tmp ne l'est pas.
# DB_PATH peut être surchargé par environnement Azure. Indispensable pour un
# slot staging : prod=/home/database.db, staging=/home/database-staging.db.
if os.getenv("DB_PATH"):
    DB_PATH = os.getenv("DB_PATH")
elif os.getenv("WEBSITE_SITE_NAME"):
    # Azure App Service → /home est persistant entre les restarts
    DB_PATH = "/home/database.db"
else:
    # Local dev
    DB_PATH = os.path.join(os.path.dirname(__file__), "database", "socrate.db")

# URL de base pour les audios (Azure CDN ou Blob direct selon la plateforme)
_AUDIO_BASE = os.getenv(
    "AZURE_AUDIO_BASE_URL",
    "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/formationaudio-dev"
).rstrip("/")

# Configuration du cours - PLAYLIST DES AUDIOS (Azure Storage)
COURS_PLAYLIST = [
    # === BLOC 1 : 9h00 - 10h05 ===
    {
        "id": 1,
        "filename": f"{_AUDIO_BASE}/cours_9h00_9h45.mp3",
        "duration": 2700,  # 45 minutes = 2700 secondes
        "title": "Cours - Bloc 1 (9h00-9h45)",
        "type": "cours",
    },
    {
        "id": 2,
        "filename": f"{_AUDIO_BASE}/qa_9h45_9h55.mp3",
        "duration": 600,  # 10 minutes = 600 secondes
        "title": "Questions-Réponses IA (9h45-9h55)",
        "type": "qa",
    },
    {
        "id": 3,
        "filename": f"{_AUDIO_BASE}/pause_9h55_10h05.mp3",
        "duration": 600,  # 10 minutes = 600 secondes
        "title": "Pause (9h55-10h05)",
        "type": "pause",
    },
    # === BLOC 2 : 10h05 - 11h05 ===
    {
        "id": 4,
        "filename": f"{_AUDIO_BASE}/cours_10h05_10h50.mp3",
        "duration": 2700,  # 45 minutes = 2700 secondes
        "title": "Cours - Bloc 2 (10h05-10h50)",
        "type": "cours",
    },
    {
        "id": 5,
        "filename": f"{_AUDIO_BASE}/qa_10h50_11h00.mp3",
        "duration": 600,  # 10 minutes = 600 secondes
        "title": "Questions-Réponses IA (10h50-11h00)",
        "type": "qa",
    },
    {
        "id": 6,
        "filename": f"{_AUDIO_BASE}/pause_11h00_11h05.mp3",
        "duration": 300,  # 5 minutes = 300 secondes
        "title": "Pause (11h00-11h05)",
        "type": "pause",
    },
    # === BLOC 3 : 11h05 - 12h20 ===
    {
        "id": 7,
        "filename": f"{_AUDIO_BASE}/cours_11h05_12h00.mp3",
        "duration": 3300,  # 55 minutes = 3300 secondes
        "title": "Cours - Bloc 3 (11h05-12h00)",
        "type": "cours",
    },
    {
        "id": 8,
        "filename": f"{_AUDIO_BASE}/qa_12h00_12h10.mp3",
        "duration": 600,  # 10 minutes = 600 secondes
        "title": "Questions-Réponses IA (12h00-12h10)",
        "type": "qa",
    },
    {
        "id": 9,
        "filename": f"{_AUDIO_BASE}/pause_12h10_12h20.mp3",
        "duration": 600,  # 10 minutes = 600 secondes
        "title": "Pause (12h10-12h20)",
        "type": "pause",
    },
    # === BLOC 4 : 12h15 - 14h40 ===
    {
        "id": 10,
        "filename": f"{_AUDIO_BASE}/pause_midi_13h15_14h45.mp3",
        "duration": 5400,  # 90 minutes = 5400 secondes
        "title": "Pause déjeuner (12h20-13h50)",
        "type": "pause_midi",
    },
    {
        "id": 11,
        "filename": f"{_AUDIO_BASE}/cours_12h20_13h05.mp3",
        "duration": 2700,  # 45 minutes = 2700 secondes
        "title": "Cours - Bloc 4 (13h50-14h35)",
        "type": "cours",
    },
    {
        "id": 12,
        "filename": f"{_AUDIO_BASE}/qa_13h05_13h15.mp3",
        "duration": 600,  # 10 minutes = 600 secondes
        "title": "Questions-Réponses IA (14h35-14h45)",
        "type": "qa",
    },
    # === BLOC 5 : 14h45 - 16h00 ===
    {
        "id": 13,
        "filename": f"{_AUDIO_BASE}/cours_14h45_15h45.mp3",
        "duration": 3600,  # 60 minutes = 3600 secondes
        "title": "Cours - Bloc 5 (14h45-15h45)",
        "type": "cours",
    },
    {
        "id": 14,
        "filename": f"{_AUDIO_BASE}/qa_15h45_16h00.mp3",
        "duration": 900,  # 15 minutes = 900 secondes
        "title": "Questions-Réponses IA (15h45-16h00)",
        "type": "qa",
    },
    # === BLOC 6 : 16h00 - 17h25 ===
    {
        "id": 15,
        "filename": f"{_AUDIO_BASE}/cours_16h00_17h00.mp3",
        "duration": 3600,  # 60 minutes = 3600 secondes
        "title": "Cours - Bloc 6 (16h00-17h00)",
        "type": "cours",
    },
    {
        "id": 16,
        "filename": f"{_AUDIO_BASE}/qa_17h00_17h15.mp3",
        "duration": 900,  # 15 minutes = 900 secondes
        "title": "Questions-Réponses IA (17h00-17h15)",
        "type": "qa",
    },
    {
        "id": 17,
        "filename": f"{_AUDIO_BASE}/pause_17h15_17h25.mp3",
        "duration": 600,  # 10 minutes = 600 secondes
        "title": "Pause (17h15-17h25)",
        "type": "pause",
    },
    # === BLOC 7 : 17h25 - 18h30 ===
    {
        "id": 18,
        "filename": f"{_AUDIO_BASE}/cours_17h25_18h15.mp3",
        "duration": 3000,  # 50 minutes = 3000 secondes
        "title": "Cours - Bloc 7 (17h25-18h15)",
        "type": "cours",
    },
    {
        "id": 19,
        "filename": f"{_AUDIO_BASE}/qa_18h15_18h30.mp3",
        "duration": 900,  # 15 minutes = 900 secondes
        "title": "Questions-Réponses IA (18h15-18h30)",
        "type": "qa",
    },
]
