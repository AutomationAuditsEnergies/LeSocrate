# auth_routes.py -- Routes d'authentification et connexion utilisateur (API JSON)
from flask import Blueprint, request, session, jsonify
from datetime import datetime
from config import FRANCE_TZ
from database.db import get_db_connection
from utils.logger import get_logger

logger = get_logger(__name__)


def create_auth_blueprint(socketio):
    """Factory pour créer le blueprint auth avec accès à socketio"""
    auth_bp = Blueprint("auth", __name__)

    @auth_bp.route("/api/auth/login", methods=["POST"])
    def login():
        try:
            data = request.get_json()
            nom = data.get("nom", "").strip()
            prenom = data.get("prenom", "").strip()

            logger.info(f"👤 Tentative connexion: {nom} {prenom}")

            if not nom or not prenom:
                logger.warning("⚠️ Nom ou prénom manquant")
                return jsonify({"success": False, "error": "Nom et prénom requis"}), 400

            session["nom"] = nom
            session["prenom"] = prenom
            # Enregistrement en heure française
            arrivee_time = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
            session["arrivee"] = arrivee_time

            logger.info(f"👤 Session créée pour {nom} {prenom} à {arrivee_time}")

            # Enregistrement arrivée
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO logs (nom, prenom, arrivee) VALUES (?, ?, ?)",
                (nom, prenom, arrivee_time),
            )
            log_id = cursor.lastrowid
            session["log_id"] = log_id
            conn.commit()
            conn.close()

            logger.info(f"✅ Utilisateur enregistré en base avec ID: {log_id}")

            return (
                jsonify(
                    {
                        "success": True,
                        "user": {"nom": nom, "prenom": prenom},
                        "log_id": log_id,
                    }
                ),
                200,
            )

        except Exception as e:
            logger.error(f"❌ Erreur connexion utilisateur: {e}")
            return (
                jsonify({"success": False, "error": "Erreur lors de la connexion"}),
                500,
            )

    @auth_bp.route("/api/auth/logout", methods=["POST"])
    def logout():
        try:
            nom = session.get("nom", "Inconnu")
            prenom = session.get("prenom", "")
            logger.info(f"👋 Déconnexion {nom} {prenom}")

            if "log_id" in session:
                conn = get_db_connection()
                cursor = conn.cursor()
                # Départ en heure française
                depart = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(
                    "UPDATE logs SET depart=? WHERE id=?", (depart, session["log_id"])
                )
                conn.commit()
                conn.close()
                logger.info(f"✅ Départ enregistré: {depart}")

            session.clear()
            return jsonify({"success": True, "message": "Déconnexion réussie"}), 200

        except Exception as e:
            logger.error(f"❌ Erreur déconnexion: {e}")
            session.clear()
            return (
                jsonify({"success": False, "error": "Erreur lors de la déconnexion"}),
                500,
            )

    @auth_bp.route("/deconnexion-auto", methods=["POST"])
    def deconnexion_auto():
        try:
            nom = session.get("nom", "Inconnu")
            logger.info(f"🔄 Déconnexion automatique {nom}")

            if "log_id" in session:
                conn = get_db_connection()
                cursor = conn.cursor()
                depart = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(
                    "UPDATE logs SET depart=? WHERE id=?",
                    (depart, session["log_id"]),
                )
                conn.commit()
                conn.close()
                logger.info(f"✅ Déconnexion auto enregistrée: {depart}")

            return "", 204

        except Exception as e:
            logger.error(f"❌ Erreur déconnexion auto: {e}")
            return "", 500

    @auth_bp.route("/deconnexion-auto-tous", methods=["POST"])
    def deconnexion_auto_tous():
        try:
            logger.info(
                "🔄 Déconnexion automatique de TOUS les utilisateurs (Azure Logic Apps)"
            )

            conn = get_db_connection()
            cursor = conn.cursor()
            depart = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute(
                "UPDATE logs SET depart=? WHERE depart IS NULL OR depart = ''",
                (depart,),
            )

            nb_deconnectes = cursor.rowcount
            conn.commit()
            conn.close()
            logger.info(f"✅ {nb_deconnectes} utilisateurs déconnectés automatiquement")

            # Forcer la redirection de tous les utilisateurs connectés
            socketio.emit(
                "force_logout",
                {
                    "message": "Fin de formation - Déconnexion automatique",
                    "redirect_url": "/logout",
                },
            )
            logger.info(
                "📢 Signal de déconnexion envoyé à tous les utilisateurs connectés"
            )

            return {"success": True, "users_disconnected": nb_deconnectes}, 200

        except Exception as e:
            logger.error(f"❌ Erreur déconnexion auto: {e}")
            return {"success": False, "error": str(e)}, 500

    return auth_bp
