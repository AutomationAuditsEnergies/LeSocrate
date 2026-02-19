# video_routes.py --- Routes pour l'API vidéo et cours (JSON uniquement)
from flask import Blueprint, session, jsonify
from services.audio_service import get_current_audio_info
from services.time_service import get_heure_debut_cours, get_current_simulated_time
from utils.logger import get_logger

logger = get_logger(__name__)

video_bp = Blueprint("video", __name__)


@video_bp.route("/api/video/status")
def video_status():
    """Retourne l'état actuel du cours pour l'utilisateur connecté"""
    try:
        if "nom" not in session:
            logger.warning("⚠️ Accès /api/video/status sans session")
            return jsonify({"authenticated": False, "error": "Non authentifié"}), 401

        nom = session.get("nom")
        prenom = session.get("prenom")
        logger.info(f"🎥 Demande statut vidéo par {nom} {prenom}")

        # Appel direct sans synchronisation
        audio_info, offset, temps_restant = get_current_audio_info()

        logger.debug(
            f"🎥 Info audio: {audio_info['title'] if audio_info else 'None'}, offset: {offset}, temps_restant: {temps_restant}"
        )

        # Si le cours n'a pas encore commencé
        if audio_info is None and temps_restant > 0:
            heure_debut_cours = get_heure_debut_cours()
            heure_actuelle_simulee = get_current_simulated_time()

            logger.info(f"⏳ Cours pas encore commencé, attente de {temps_restant}s")

            return (
                jsonify(
                    {
                        "authenticated": True,
                        "user": {"nom": nom, "prenom": prenom},
                        "status": "waiting",
                        "heure_debut": heure_debut_cours.strftime("%Y-%m-%d %H:%M:%S"),
                        "heure_actuelle": heure_actuelle_simulee.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        "temps_restant": temps_restant,
                    }
                ),
                200,
            )

        # Si le cours est terminé
        if audio_info is None:
            logger.info("🏁 Cours terminé")
            return (
                jsonify(
                    {
                        "authenticated": True,
                        "user": {"nom": nom, "prenom": prenom},
                        "status": "finished",
                        "cours_termine": True,
                    }
                ),
                200,
            )

        # Le cours est en cours
        logger.info(f"▶️ Cours en cours: {audio_info['title']}")
        return (
            jsonify(
                {
                    "authenticated": True,
                    "user": {"nom": nom, "prenom": prenom},
                    "status": "playing",
                    "audio_filename": audio_info["filename"],
                    "audio_title": audio_info["title"],
                    "audio_id": audio_info["id"],
                    "audio_type": audio_info["type"],
                    "offset": offset,
                    "cours_termine": False,
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"❌ Erreur API video/status: {e}")
        return jsonify({"success": False, "error": "Erreur serveur"}), 500


@video_bp.route("/api/cours-status")
def cours_status():
    """API endpoint pour obtenir l'état actuel du cours (sans authentification requise)"""
    try:
        logger.debug("📊 Demande statut cours")

        # Appel direct sans synchronisation
        audio_info, offset, temps_restant = get_current_audio_info()

        if audio_info is None and temps_restant > 0:
            heure_debut_cours = get_heure_debut_cours()
            result = {
                "status": "waiting",
                "temps_restant": temps_restant,
                "heure_debut": heure_debut_cours.strftime("%H:%M"),
            }
        elif audio_info is None:
            result = {"status": "finished"}
        else:
            result = {
                "status": "playing",
                "audio_id": audio_info["id"],
                "audio_filename": audio_info["filename"],
                "audio_title": audio_info["title"],
                "audio_type": audio_info["type"],
                "offset": offset,
            }

        logger.debug(f"📊 Statut cours: {result['status']}")
        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Erreur API cours-status: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@video_bp.route("/api/intro")
def intro():
    """Retourne les informations pour la page d'introduction"""
    try:
        if "nom" not in session:
            logger.warning("⚠️ Accès /api/intro sans session")
            return jsonify({"authenticated": False, "error": "Non authentifié"}), 401

        nom = session.get("nom")
        prenom = session.get("prenom")
        logger.info(f"📺 Demande page intro par {nom} {prenom}")

        return (
            jsonify(
                {
                    "authenticated": True,
                    "user": {"nom": nom, "prenom": prenom},
                    "message": "Page d'introduction",
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"❌ Erreur API intro: {e}")
        return jsonify({"success": False, "error": "Erreur serveur"}), 500
