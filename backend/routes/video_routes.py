# video_routes.py --- Routes pour l'API vidéo et cours (JSON uniquement)
from flask import Blueprint, session, jsonify, request, Response
import requests as http_requests
from services.audio_service import get_current_audio_info
from services.script_slide_generation_service import get_latest_script_slide_deck_for_audio
from services.time_service import get_heure_debut_cours, get_current_simulated_time
from utils.logger import get_logger

logger = get_logger(__name__)

video_bp = Blueprint("video", __name__)


def _get_platform_id():
    """Récupère le platform_id depuis le query param ou la session (défaut: 1)"""
    pid = request.args.get("platform_id", type=int)
    if pid:
        return pid
    header_pid = request.headers.get("X-Platform-Id")
    if header_pid:
        try:
            return int(header_pid)
        except (TypeError, ValueError):
            pass
    return session.get("platform_id", 1)


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

        platform_id = _get_platform_id()
        audio_info, offset, temps_restant = get_current_audio_info(platform_id)

        logger.debug(
            f"🎥 Info audio: {audio_info['title'] if audio_info else 'None'}, offset: {offset}, temps_restant: {temps_restant}"
        )

        # Si le cours n'a pas encore commencé
        if audio_info is None and temps_restant > 0:
            heure_debut_cours = get_heure_debut_cours(platform_id)
            heure_actuelle_simulee = get_current_simulated_time(platform_id)

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
                    "audio_duration": audio_info.get("duration", 0),
                    "offset": offset,
                    "remaining": max(0, int(audio_info.get("duration", 0)) - int(offset or 0)),
                    "cours_termine": False,
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"❌ Erreur API video/status: {e}")
        return jsonify({"success": False, "error": "Erreur serveur"}), 500


@video_bp.route("/api/video/slides")
def video_slides():
    """Retourne le deck synchronisé avec l'audio actuellement projetable côté cours."""
    try:
        if "nom" not in session:
            logger.warning("⚠️ Accès /api/video/slides sans session")
            return jsonify({"authenticated": False, "error": "Non authentifié"}), 401

        platform_id = _get_platform_id()
        audio_filename = request.args.get("audio_filename")
        if not audio_filename:
            audio_info, _offset, _temps_restant = get_current_audio_info(platform_id)
            audio_filename = audio_info.get("filename") if audio_info else None

        if not audio_filename:
            return jsonify({"status": "no_data", "message": "Aucun audio en cours"}), 200

        deck = get_latest_script_slide_deck_for_audio(audio_filename, platform_id=platform_id)
        if not deck:
            return jsonify({"status": "no_data", "message": "Aucun deck synchronisé pour cet audio"}), 200

        return jsonify(
            {
                "authenticated": True,
                "status": "success",
                "deck_id": deck.get("deck_id"),
                "folder_id": deck.get("folder_id"),
                "audio_sync": deck.get("audio_sync") or {},
                "slides": deck.get("slides") or [],
            }
        )

    except Exception as e:
        logger.error(f"❌ Erreur API video/slides: {e}")
        return jsonify({"success": False, "error": "Erreur serveur"}), 500


@video_bp.route("/api/audio/stream")
def audio_stream():
    """Proxy l'audio depuis Azure Blob Storage avec support des Range requests"""
    try:
        platform_id = _get_platform_id()
        audio_info, offset, temps_restant = get_current_audio_info(platform_id)
        if not audio_info:
            return "Pas d'audio en cours", 404

        blob_url = audio_info["filename"]
        range_header = request.headers.get("Range")

        # Transférer la requête Range à Azure (server-to-server, pas de CORS)
        headers = {}
        if range_header:
            headers["Range"] = range_header

        resp = http_requests.get(blob_url, headers=headers, stream=True)

        # Construire les headers de la réponse
        response_headers = {
            "Content-Type": "audio/mpeg",
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache",
        }
        if resp.headers.get("Content-Length"):
            response_headers["Content-Length"] = resp.headers["Content-Length"]
        if resp.headers.get("Content-Range"):
            response_headers["Content-Range"] = resp.headers["Content-Range"]

        status = 206 if resp.status_code == 206 else 200
        return Response(
            resp.iter_content(chunk_size=8192),
            status=status,
            headers=response_headers,
        )

    except Exception as e:
        logger.error(f"❌ Erreur proxy audio: {e}")
        return "Erreur serveur", 500


@video_bp.route("/api/cours-status")
def cours_status():
    """API endpoint pour obtenir l'état actuel du cours (sans authentification requise)"""
    try:
        logger.debug("📊 Demande statut cours")

        platform_id = _get_platform_id()
        audio_info, offset, temps_restant = get_current_audio_info(platform_id)

        if audio_info is None and temps_restant > 0:
            heure_debut_cours = get_heure_debut_cours(platform_id)
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
                "audio_duration": audio_info.get("duration", 0),
                "offset": offset,
                "remaining": max(0, int(audio_info.get("duration", 0)) - int(offset or 0)),
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
