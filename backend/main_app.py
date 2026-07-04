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
from database import db_safety

# Routes
from routes.auth_routes import create_auth_blueprint
from routes.video_routes import video_bp
from routes.admin_routes import create_admin_blueprint
from routes.debug_routes import debug_bp
from routes.slides_routes import slides_bp
from routes.chat_routes import chat_bp
from routes.hr_routes import create_hr_blueprint
from routes.formation_routes import formation_bp, start_auto_pilot_watchdog

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
    "https://victorious-smoke-02aaf4e03.6.azurestaticapps.net",
]
for _i in range(1, 10):
    _url = os.environ.get(f"PLATFORM_{_i}_FRONTEND_URL", "").rstrip("/")
    if _url and _url not in _cors_origins:
        _cors_origins.append(_url)

CORS(app, resources={
    r"/*": {
        "origins": _cors_origins,
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "X-Auth-Token", "X-Platform-Id", "Range"],
        "expose_headers": ["Accept-Ranges", "Content-Length", "Content-Range", "Content-Disposition"],
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
app.register_blueprint(formation_bp)

logger.info("✅ Tous les blueprints enregistrés")

# Reconstituer la session Flask depuis le header X-Auth-Token
# (pour navigation privée et navigateurs bloquant les cookies tiers)
# + injecter platform_id depuis le header X-Platform-Id
import state as _state
from flask import jsonify as _jsonify
@app.before_request
def populate_session_from_token():
    # Mode maintenance DB : tout est bloqué en 503 sauf les endpoints admin
    # nécessaires au diagnostic et à la restauration.
    if db_safety.is_maintenance() and not (
        request.path.startswith("/api/admin/db")
        or request.path.startswith("/api/admin/login")
    ):
        return _jsonify({
            "error": "maintenance",
            "message": "Plateforme en maintenance : récupération de la base de données en cours.",
            "reason": db_safety.db_health.get("maintenance_reason"),
        }), 503

    token = request.headers.get("X-Auth-Token")
    if (
        not token
        and request.method == "GET"
        and request.path.startswith("/api/hr/cours-folders/")
        and "/audio-stream/" in request.path
    ):
        token = request.args.get("auth_token")
    if not session.get("is_admin") and token:
        admin_tokens = getattr(_state, "admin_tokens", {})
        admin_user = admin_tokens.get(token)
        if admin_user:
            session["is_admin"] = True
            session["admin_account_type"] = admin_user.get("account_type", "training_center")
            if admin_user.get("account_id") is not None:
                session["admin_account_id"] = admin_user["account_id"]
            if admin_user.get("center_name"):
                session["center_name"] = admin_user["center_name"]
            session.permanent = True

    if "nom" not in session:
        if token and token in _state.user_tokens:
            user = _state.user_tokens[token]
            session["nom"] = user["nom"]
            session["prenom"] = user["prenom"]
            session["log_id"] = user["log_id"]
            session["platform_id"] = user.get("platform_id", 1)

    # Injecter platform_id depuis le header si absent de la session
    if "platform_id" not in session:
        raw = request.headers.get("X-Platform-Id")
        if raw and raw.isdigit():
            session["platform_id"] = int(raw)
        elif request.args.get("platform_id"):
            session["platform_id"] = int(request.args["platform_id"])


@app.route("/api/platform-info")
def platform_info():
    """Retourne les infos d'une plateforme (nom, slug)"""
    from database.db import get_db_connection
    from database.postgres import postgres_enabled
    from repositories.core_repository import get_platform_info

    pid = request.args.get("id", 1, type=int)
    if postgres_enabled():
        row = get_platform_info(pid)
        if row:
            return _jsonify({"id": row["id"], "name": row["name"], "slug": row["slug"]})

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, slug FROM platform_config WHERE id = ?", (pid,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return _jsonify({"error": "Platform not found"}), 404
    return _jsonify({"id": row[0], "name": row[1], "slug": row[2]})


@app.route("/api/class-access/<center_slug>/<platform_slug>")
def class_access(center_slug, platform_slug):
    """Résout l'URL publique élève vers la plateforme interne.

    Le contrat produit est l'URL lisible /classe/<centre>/<formation>. Le
    platform_id reste une clé interne, gardée pour les services existants.
    """
    from database.db import get_db_connection
    from database.postgres import postgres_enabled
    from repositories.core_repository import resolve_class_access

    row = resolve_class_access(center_slug, platform_slug) if postgres_enabled() else None
    if row:
        if not row["public_access_enabled"]:
            return _jsonify({"success": False, "error": "Classe non publiée"}), 403
        return _jsonify({
            "success": True,
            "platform": {
                "id": row["id"],
                "name": row["name"],
                "slug": row["slug"],
                "status": row["status"],
            },
            "center": {
                "slug": row["center_slug"],
                "name": row["center_name"],
            },
        })

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            pc.id,
            pc.name,
            pc.slug,
            COALESCE(tca.slug, 'le-socrate') AS center_slug,
            COALESCE(tca.center_name, 'Le Socrate') AS center_name,
            COALESCE(pc.public_access_enabled, 1) AS public_access_enabled,
            COALESCE(pc.status, 'ready') AS status
        FROM platform_config pc
        LEFT JOIN training_center_accounts tca ON tca.id = pc.center_account_id
        WHERE pc.slug = ?
          AND COALESCE(tca.slug, 'le-socrate') = ?
        LIMIT 1
        """,
        (platform_slug, center_slug),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return _jsonify({"success": False, "error": "Classe introuvable"}), 404

    platform_id, name, slug, resolved_center_slug, center_name, public_access_enabled, status = row
    if not public_access_enabled:
        return _jsonify({"success": False, "error": "Classe non publiée"}), 403

    return _jsonify({
        "success": True,
        "platform": {
            "id": platform_id,
            "name": name,
            "slug": slug,
            "status": status,
        },
        "center": {
            "slug": resolved_center_slug,
            "name": center_name,
        },
    })

# Enregistrement des gestionnaires SocketIO
register_socketio_handlers(socketio)
logger.info("✅ Gestionnaires SocketIO enregistrés")

# Sécurité DB avant tout : integrity_check + backup au boot, restauration
# automatique du dernier backup sain en cas de corruption (cf. db_safety.py)
db_safety.startup_check()

# Initialisation de la base de données (migrations incluses — doit précéder boot recovery)
init_database()
logger.info("✅ Base de données initialisée")

# Backup périodique toutes les 6h (green thread eventlet via socketio)
socketio.start_background_task(db_safety.periodic_backup_loop, socketio.sleep)
logger.info("✅ Backup DB périodique programmé (toutes les 6h)")

# Watchdog après init DB : reprend les auto-pilots interrompus ou locks zombies
start_auto_pilot_watchdog()


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
