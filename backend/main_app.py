# main_app.py - Point d'entrée principal de l'application (refactorisé)
# Backend API pur pour frontend React
import os
from flask import Flask
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
CORS(app, resources={
    r"/*": {
        "origins": [
            "http://localhost:5173",
            "http://localhost:3000",
            "https://thankful-wave-043aa3b03.4.azurestaticapps.net",
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True
    }
})

logger.info("🚀 Initialisation de l'application Flask (mode API)")
logger.info("✅ CORS configuré pour frontend React")

# Initialisation de SocketIO avec eventlet et CORS
socketio = SocketIO(
    app,
    cors_allowed_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "https://thankful-wave-043aa3b03.4.azurestaticapps.net",
    ],
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
