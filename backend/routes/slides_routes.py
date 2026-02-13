# slides_routes.py - Routes API pour la génération de slides
from flask import Blueprint, jsonify, request
from services.slide_generation_service import (
    generate_slides,
    generate_slides_v3,
    get_generation_status
)
from utils.logger import get_logger

logger = get_logger(__name__)

slides_bp = Blueprint("slides", __name__, url_prefix="/api/slides")

# Stockage en mémoire des slides générées (pour le prototype)
_generated_slides = None
_generation_error = None
_generation_stats = None
_generation_timeline = None
_transcription_full = None
_pipeline_debug = None  # Données intermédiaires du pipeline


@slides_bp.route("/generate", methods=["POST"])
def generate():
    """
    Lance la génération des slides à partir d'un audio.

    Body (optionnel):
        {"audio_id": 1}  # ID de l'audio dans la playlist (défaut: 1)

    Returns:
        {"status": "success", "slides_count": 2, "slides": [...]}
        ou
        {"status": "error", "message": "..."}
    """
    global _generated_slides, _generation_error

    try:
        # Récupérer l'ID de l'audio (défaut: 1 = premier audio)
        data = request.get_json() or {}
        audio_id = data.get("audio_id", 1)

        logger.info(f"Demande de génération pour audio #{audio_id}")

        # Générer les slides
        slides = generate_slides(audio_id=audio_id)

        # Stocker le résultat
        _generated_slides = slides
        _generation_error = None

        logger.info(f"Génération réussie: {len(slides)} slides")

        return jsonify({
            "status": "success",
            "slides_count": len(slides),
            "slides": slides
        })

    except ValueError as e:
        logger.error(f"Erreur de validation: {e}")
        _generation_error = str(e)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400

    except Exception as e:
        logger.error(f"Erreur lors de la génération: {e}")
        _generation_error = str(e)
        return jsonify({
            "status": "error",
            "message": f"Erreur lors de la génération: {str(e)}"
        }), 500


@slides_bp.route("/generate-v3", methods=["POST"])
def generate_v3():
    """
    Lance la génération des slides avec le pipeline v3 (architecture hiérarchique).

    Body (optionnel):
        {
            "audio_id": 1,      # ID de l'audio dans la playlist (défaut: 1)
            "max_duration": 300 # Durée max en secondes (défaut: 300 = 5 min)
        }

    Returns:
        {
            "status": "success",
            "slides_count": N,
            "slides": [...],
            "stats": {...},
            "timeline": [...]
        }
    """
    global _generated_slides, _generation_error, _generation_stats, _generation_timeline, _transcription_full, _pipeline_debug

    try:
        data = request.get_json() or {}
        audio_id = data.get("audio_id", 1)
        max_duration = data.get("max_duration", 300)

        logger.info(f"Demande génération v3 pour audio #{audio_id} (max: {max_duration}s)")

        # Générer avec le nouveau pipeline
        result = generate_slides_v3(audio_id=audio_id, max_duration=max_duration)

        # Stocker les résultats
        _generated_slides = result["slides"]
        _generation_stats = result["stats"]
        _generation_timeline = result["timeline"]
        _transcription_full = result.get("transcription_full", "")
        _pipeline_debug = result.get("pipeline_debug", {})
        _generation_error = None

        logger.info(f"Génération v3 réussie: {len(_generated_slides)} slides")

        return jsonify({
            "status": "success",
            "slides_count": len(_generated_slides),
            "slides": _generated_slides,
            "stats": _generation_stats,
            "timeline": _generation_timeline,
            "pipeline_debug": _pipeline_debug
        })

    except ValueError as e:
        logger.error(f"Erreur de validation: {e}")
        _generation_error = str(e)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400

    except Exception as e:
        logger.error(f"Erreur lors de la génération v3: {e}")
        import traceback
        traceback.print_exc()
        _generation_error = str(e)
        return jsonify({
            "status": "error",
            "message": f"Erreur lors de la génération: {str(e)}"
        }), 500


@slides_bp.route("/data", methods=["GET"])
def get_slides():
    """
    Récupère les slides générées.

    Returns:
        {"slides": [...], "status": "success", "stats": {...}, "timeline": [...]}
        ou
        {"status": "no_data", "message": "Aucune slide générée"}
    """
    global _generated_slides, _generation_error, _generation_stats, _generation_timeline, _transcription_full, _pipeline_debug

    if _generation_error:
        return jsonify({
            "status": "error",
            "message": _generation_error
        }), 500

    if _generated_slides is None:
        return jsonify({
            "status": "no_data",
            "message": "Aucune slide générée. Utilisez POST /api/slides/generate-v3 d'abord."
        })

    response = {
        "status": "success",
        "slides": _generated_slides,
        "slides_count": len(_generated_slides)
    }

    # Ajouter les données v3 si disponibles
    if _generation_stats:
        response["stats"] = _generation_stats
    if _generation_timeline:
        response["timeline"] = _generation_timeline
    if _transcription_full:
        response["transcription"] = _transcription_full
    if _pipeline_debug:
        response["pipeline_debug"] = _pipeline_debug

    return jsonify(response)


@slides_bp.route("/status", methods=["GET"])
def status():
    """
    Retourne le statut du service de génération.

    Returns:
        {"status": "ready", "has_slides": true/false}
    """
    global _generated_slides

    service_status = get_generation_status()

    return jsonify({
        **service_status,
        "has_slides": _generated_slides is not None,
        "slides_count": len(_generated_slides) if _generated_slides else 0
    })


@slides_bp.route("/clear", methods=["POST"])
def clear():
    """
    Efface les slides générées (pour refaire une génération propre).

    Returns:
        {"status": "cleared"}
    """
    global _generated_slides, _generation_error, _generation_stats, _generation_timeline, _transcription_full, _pipeline_debug

    _generated_slides = None
    _generation_error = None
    _generation_stats = None
    _generation_timeline = None
    _transcription_full = None
    _pipeline_debug = None

    logger.info("Slides effacées")

    return jsonify({
        "status": "cleared",
        "message": "Slides effacées avec succès"
    })
