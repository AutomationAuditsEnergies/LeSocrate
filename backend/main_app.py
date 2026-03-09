# main_app.py - Point d'entrée principal de l'application (refactorisé)
# Backend API pur pour frontend React
import os
from flask import Flask, request, session
from flask_socketio import SocketIO
from flask_cors import CORS

# Configuration et logging
from config import SECRET_KEY
from utils.logger import configure_logging, get_logger

# Database
from database.db import init_database

# Routes
from routes.auth_routes import create_auth_blueprint
from routes.video_routes import video_bp
from routes.admin_routes import create_admin_blueprint
from routes.debug_routes import debug_bp
from routes.slides_routes import slides_bp
from routes.chat_routes import chat_bp
from routes.hr_routes import create_hr_blueprint

# SocketIO handlers
from socketio_handlers.handlers import register_socketio_handlers

# Configuration du logging
configure_logging()
logger = get_logger(__name__)

# Initialisation de l'application Flask (API uniquement)
app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

# Configuration des cookies de session pour le cross-origin (Azure)
is_azure = os.environ.get("WEBSITE_SITE_NAME") is not None
if is_azure:
    app.config["SESSION_COOKIE_SAMESITE"] = "None"
    app.config["SESSION_COOKIE_SECURE"] = True

# Configuration CORS pour permettre les requêtes du frontend React
# URLs connues en dur (fonctionnent toujours) + URLs dynamiques via env vars
_cors_origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://thankful-wave-043aa3b03.4.azurestaticapps.net",
    "https://brave-mud-064e06d03.2.azurestaticapps.net",
    "https://polite-bush-07d4fdd03.1.azurestaticapps.net",
]
for _i in range(1, 4):
    _url = os.environ.get(f"PLATFORM_{_i}_FRONTEND_URL", "").rstrip("/")
    if _url and _url not in _cors_origins:
        _cors_origins.append(_url)

CORS(app, resources={
    r"/*": {
        "origins": _cors_origins,
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True
    }
})

logger.info("🚀 Initialisation de l'application Flask (mode API)")
logger.info(f"✅ CORS configuré pour: {_cors_origins}")

# Initialisation de SocketIO avec eventlet et CORS
socketio = SocketIO(
    app,
    cors_allowed_origins=_cors_origins,
    async_mode="eventlet"
)
logger.info("✅ SocketIO initialisé avec eventlet et CORS")

# Enregistrement des blueprints
# Les blueprints qui ont besoin de socketio sont créés via factory
auth_bp = create_auth_blueprint(socketio)
admin_bp = create_admin_blueprint(socketio)
hr_bp = create_hr_blueprint(socketio)

app.register_blueprint(auth_bp)
app.register_blueprint(video_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(debug_bp)
app.register_blueprint(slides_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(hr_bp)

logger.info("✅ Tous les blueprints enregistrés")

# Reconstituer la session Flask depuis le header X-Auth-Token
# (pour navigation privée et navigateurs bloquant les cookies tiers)
import state as _state
@app.before_request
def populate_session_from_token():
    if "nom" not in session:
        token = request.headers.get("X-Auth-Token")
        if token and token in _state.user_tokens:
            user = _state.user_tokens[token]
            session["nom"] = user["nom"]
            session["prenom"] = user["prenom"]
            session["log_id"] = user["log_id"]

# Enregistrement des gestionnaires SocketIO
register_socketio_handlers(socketio)
logger.info("✅ Gestionnaires SocketIO enregistrés")

# Initialisation de la base de données
init_database()
logger.info("✅ Base de données initialisée")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))

    # Détection environnement Azure
    is_azure = os.environ.get("WEBSITE_SITE_NAME") is not None

    if is_azure:
        logger.info("🌐 Démarrage en mode PRODUCTION (Azure)")
        socketio.run(app, host="0.0.0.0", port=port, debug=False)
    else:
        logger.info("💻 Démarrage en mode DÉVELOPPEMENT (local)")
        socketio.run(app, host="0.0.0.0", port=port, debug=True)
