# debug_routes.py - Routes de debug pour le développement (API JSON)
from flask import Blueprint, request, session, jsonify
import state
from services.audio_service import get_current_audio_info, get_playlist
from services.time_service import get_heure_debut_cours, get_current_simulated_time
from utils.logger import get_logger

logger = get_logger(__name__)

debug_bp = Blueprint("debug", __name__)


def _get_platform_id():
    """Resolve the current platform for debug calls.

    The debug page is opened directly from tenant-specific admin URLs, so query
    and header values must override an older admin session.
    """
    raw = request.headers.get("X-Platform-Id")
    if raw and raw.isdigit():
        return int(raw)
    for key in ("platform_id", "p"):
        arg = request.args.get(key)
        if arg and str(arg).isdigit():
            return int(arg)
    pid = session.get("platform_id")
    if pid:
        try:
            return int(pid)
        except (TypeError, ValueError):
            pass
    logger.warning("⚠️ platform_id introuvable pour debug — fallback P1")
    return 1


@debug_bp.route("/api/debug/cours-info")
def debug_cours_info():
    """API pour obtenir les informations détaillées du cours (debug)"""
    try:
        if not session.get("is_admin"):
            logger.warning("⚠️ Tentative accès debug sans authentification admin")
            return jsonify({"authenticated": False, "error": "Accès refusé"}), 403

        platform_id = _get_platform_id()
        logger.info(f"🐛 Accès API debug cours-info P{platform_id}")

        # Récupérer toutes les infos
        playlist = get_playlist(platform_id)
        heure_debut_cours = get_heure_debut_cours(platform_id)
        heure_actuelle_simulee = get_current_simulated_time(platform_id)
        audio_info, offset, temps_restant = get_current_audio_info(platform_id)

        # Calculer le temps écoulé
        temps_ecoule_total = 0
        if heure_actuelle_simulee >= heure_debut_cours:
            temps_ecoule_total = int(
                (heure_actuelle_simulee - heure_debut_cours).total_seconds()
            )

        # Informations sur la playlist
        duree_totale_cours = sum(audio["duration"] for audio in playlist)

        debug_info = {
            "platform_id": platform_id,
            "heure_debut_cours": heure_debut_cours.strftime("%Y-%m-%d %H:%M:%S"),
            "heure_actuelle": heure_actuelle_simulee.strftime("%Y-%m-%d %H:%M:%S"),
            "simulation_active": state.simulated_time_offsets.get(platform_id) is not None or state.simulated_time_offset is not None,
            "temps_ecoule_secondes": temps_ecoule_total,
            "temps_ecoule_minutes": temps_ecoule_total // 60,
            "duree_totale_cours_secondes": duree_totale_cours,
            "duree_totale_cours_minutes": duree_totale_cours // 60,
            "nombre_audios": len(playlist),
        }

        if audio_info:
            debug_info.update(
                {
                    "status": "En cours",
                    "audio_actuel_id": audio_info["id"],
                    "audio_actuel_titre": audio_info["title"],
                    "audio_actuel_type": audio_info["type"],
                    "offset_dans_audio": offset,
                    "duree_audio_actuel": audio_info["duration"],
                }
            )
        elif temps_restant > 0:
            debug_info.update(
                {
                    "status": "En attente",
                    "temps_avant_debut": temps_restant,
                    "temps_avant_debut_minutes": temps_restant // 60,
                }
            )
        else:
            debug_info.update({"status": "Terminé"})

        logger.debug(f"🐛 Debug info: {debug_info}")

        return jsonify({
            "success": True,
            "debug_info": debug_info
        }), 200

    except Exception as e:
        logger.error(f"❌ Erreur API debug: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@debug_bp.route("/api/debug/playlist")
def debug_playlist():
    """API pour obtenir la playlist complète"""
    try:
        if not session.get("is_admin"):
            logger.warning("⚠️ Tentative accès debug playlist sans auth admin")
            return jsonify({"authenticated": False, "error": "Accès refusé"}), 403

        platform_id = _get_platform_id()
        logger.info(f"🐛 Accès API debug playlist P{platform_id}")

        return jsonify({
            "success": True,
            "platform_id": platform_id,
            "playlist": get_playlist(platform_id),
        }), 200

    except Exception as e:
        logger.error(f"❌ Erreur API debug playlist: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
