# slides_routes.py - Routes API pour la génération de slides
from flask import Blueprint, jsonify, request, session
from services.slide_generation_service import (
    generate_slides,
    generate_slides_v3,
    get_generation_status
)
from services.script_slide_generation_service import (
    generate_slides_from_script,
    get_latest_script_slide_deck,
    preview_slides_from_text,
)
from repositories.pipeline_repository import hr_resource_belongs_to_center
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
_generation_mode = None


@slides_bp.before_request
def require_admin_for_slide_workbench():
    """Keep every deck operation inside its owning centre boundary.

    The legacy audio/preview/status endpoints use process-global prototype
    state and therefore remain super-admin only. A training centre can use the
    persisted script deck endpoints only after the referenced folder (and an
    optional platform hint) resolves to its own PostgreSQL tenant.
    """
    if request.method == "OPTIONS":
        return None
    if not session.get("is_admin", False):
        return jsonify({"status": "error", "message": "Non autorisé"}), 403

    account_type = str(session.get("admin_account_type") or "").strip().lower()
    if account_type == "legacy_admin":
        return None
    if account_type != "training_center":
        return jsonify({"status": "error", "message": "Non autorisé"}), 403

    if request.endpoint == "slides.generate_from_script":
        data = request.get_json(silent=True) or {}
        folder_id = data.get("folder_id")
        platform_id = data.get("platform_id")
    elif request.endpoint == "slides.get_slides":
        folder_id = request.args.get("folder_id")
        platform_id = None
    else:
        # Global prototype state is never shared between centre accounts.
        return jsonify({"status": "error", "message": "Non autorisé"}), 403

    try:
        center_id = int(session.get("admin_account_id"))
        folder_id = int(folder_id)
        allowed = hr_resource_belongs_to_center("folder", folder_id, center_id)
        if allowed and platform_id not in (None, ""):
            allowed = hr_resource_belongs_to_center(
                "platform",
                int(platform_id),
                center_id,
            )
    except (TypeError, ValueError):
        allowed = False
    except Exception:
        logger.warning(
            "SLIDES_TENANT_SCOPE_LOOKUP_FAILED folder_id=%s center_id=%s",
            folder_id,
            session.get("admin_account_id"),
            exc_info=True,
        )
        allowed = False
    if not allowed:
        # Same response for a missing folder and another centre's folder.
        return jsonify({"status": "error", "message": "Ressource introuvable"}), 404
    return None


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
    global _generated_slides, _generation_error, _generation_stats, _generation_timeline
    global _transcription_full, _pipeline_debug, _generation_mode

    try:
        # Récupérer l'ID de l'audio (défaut: 1 = premier audio)
        data = request.get_json() or {}
        audio_id = data.get("audio_id", 1)

        logger.info(f"Demande de génération pour audio #{audio_id}")

        # Générer les slides
        slides = generate_slides(audio_id=audio_id)

        # Stocker le résultat
        _generated_slides = slides
        _generation_stats = None
        _generation_timeline = None
        _transcription_full = None
        _pipeline_debug = None
        _generation_mode = "audio_legacy"
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
    global _generated_slides, _generation_error, _generation_stats, _generation_timeline
    global _transcription_full, _pipeline_debug, _generation_mode

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
        _generation_mode = "audio_v3"
        _generation_error = None

        logger.info(f"Génération v3 réussie: {len(_generated_slides)} slides")

        return jsonify({
            "status": "success",
            "generation_mode": _generation_mode,
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


@slides_bp.route("/generate-from-script", methods=["POST"])
def generate_from_script():
    """
    Génère des slides depuis le texte final stocké en DB.

    Body:
        {
            "folder_id": 123,          # requis
            "job_id": 7,               # optionnel, vérifie la cohérence plateforme
            "platform_id": 36,         # optionnel, prioritaire sur la session admin
            "max_slides": 60,          # cap de densité V1
            "pace": "normal",          # dense|normal|synthesis
            "model": "sonnet"          # optionnel
        }
    """
    global _generated_slides, _generation_error, _generation_stats, _generation_timeline
    global _transcription_full, _pipeline_debug, _generation_mode

    try:
        if not session.get("is_admin", False):
            return jsonify({"status": "error", "message": "Non autorisé"}), 403

        data = request.get_json() or {}
        folder_id = data.get("folder_id")
        job_id = data.get("job_id")
        max_slides = data.get("max_slides", 60)
        pace = data.get("pace", "normal")
        model = data.get("model")
        platform_id = data.get("platform_id") or session.get("platform_id")

        logger.info(
            "Demande génération slides depuis script folder=%s job=%s platform=%s max_slides=%s",
            folder_id,
            job_id,
            platform_id,
            max_slides,
        )

        result = generate_slides_from_script(
            folder_id=folder_id,
            job_id=job_id,
            platform_id=platform_id,
            max_slides=max_slides,
            pace=pace,
            model=model,
        )

        _generated_slides = result["slides"]
        _generation_stats = result["stats"]
        _generation_timeline = result["timeline"]
        _pipeline_debug = result.get("pipeline_debug", {})
        _transcription_full = None
        _generation_mode = (result.get("stats") or {}).get("generation_mode") or "script"
        _generation_error = None

        logger.info(f"Génération script réussie: {len(_generated_slides)} slides")

        return jsonify({
            "status": "success",
            "generation_mode": _generation_mode,
            "slides_count": len(_generated_slides),
            "slides": _generated_slides,
            "stats": _generation_stats,
            "timeline": _generation_timeline,
            "pipeline_debug": _pipeline_debug
        })

    except ValueError as e:
        logger.error(f"Erreur de validation génération script: {e}")
        _generation_error = str(e)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400

    except Exception as e:
        logger.error(f"Erreur lors de la génération depuis script: {e}")
        import traceback
        traceback.print_exc()
        _generation_error = str(e)
        return jsonify({
            "status": "error",
            "message": f"Erreur lors de la génération depuis script: {str(e)}"
        }), 500


@slides_bp.route("/preview-from-text", methods=["POST"])
def preview_from_text():
    """
    Mode temporaire d'itération rapide : génère des slides depuis un passage collé,
    sans relancer la pipeline et sans persister de deck.

    Body:
        {
            "text": "...",                 # requis
            "title": "Passage brouillard", # optionnel
            "template_type": "analogy",    # optionnel, force un anchor temporaire
            "visual_goal": "...",          # optionnel
            "fields_hint": {},             # optionnel
            "max_slides": 8,
            "pace": "dense",
            "model": "sonnet"
        }
    """
    global _generated_slides, _generation_error, _generation_stats, _generation_timeline
    global _transcription_full, _pipeline_debug, _generation_mode

    try:
        if not session.get("is_admin", False):
            return jsonify({"status": "error", "message": "Non autorisé"}), 403

        data = request.get_json() or {}
        text = data.get("text") or ""
        result = preview_slides_from_text(
            text,
            title=data.get("title") or "Prévisualisation passage",
            template_type=data.get("template_type"),
            visual_goal=data.get("visual_goal"),
            fields_hint=data.get("fields_hint") if isinstance(data.get("fields_hint"), dict) else None,
            max_slides=data.get("max_slides", 8),
            pace=data.get("pace", "dense"),
            model=data.get("model"),
        )

        _generated_slides = result["slides"]
        _generation_stats = result["stats"]
        _generation_timeline = result["timeline"]
        _pipeline_debug = result.get("pipeline_debug", {})
        _transcription_full = text
        _generation_mode = "script_preview"
        _generation_error = None

        return jsonify({
            "status": "success",
            "generation_mode": _generation_mode,
            "slides_count": len(_generated_slides),
            "slides": _generated_slides,
            "stats": _generation_stats,
            "timeline": _generation_timeline,
            "pipeline_debug": _pipeline_debug,
        })

    except ValueError as e:
        logger.error(f"Erreur de validation preview slides: {e}")
        _generation_error = str(e)
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        logger.error(f"Erreur preview slides depuis texte: {e}")
        import traceback
        traceback.print_exc()
        _generation_error = str(e)
        return jsonify({
            "status": "error",
            "message": f"Erreur preview slides depuis texte: {str(e)}",
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
    global _generated_slides, _generation_error, _generation_stats, _generation_timeline, _transcription_full, _pipeline_debug, _generation_mode

    folder_id = request.args.get("folder_id")
    if folder_id:
        if not session.get("is_admin", False):
            return jsonify({"status": "error", "message": "Non autorisé"}), 403
        try:
            deck = get_latest_script_slide_deck(int(folder_id))
        except (TypeError, ValueError):
            deck = None
        if deck:
            return jsonify({
                "status": "success",
                "generation_mode": (deck.get("stats") or {}).get("generation_mode") or "script",
                "slides": deck["slides"],
                "slides_count": len(deck["slides"]),
                "stats": deck["stats"],
                "timeline": deck["timeline"],
                "pipeline_debug": deck["pipeline_debug"],
                "audio_sync": deck.get("audio_sync") or {},
                "deck_id": deck.get("deck_id"),
            })
        return jsonify({
            "status": "no_data",
            "message": "Aucun deck slide généré pour ce cours.",
            "slides": [],
            "slides_count": 0,
            "audio_sync": {},
        })

    if _generation_error:
        return jsonify({
            "status": "error",
            "message": _generation_error
        }), 500

    if str(_generation_mode or "").startswith("script") and not session.get("is_admin", False):
        return jsonify({"status": "error", "message": "Non autorisé"}), 403

    if _generated_slides is None:
        return jsonify({
            "status": "no_data",
            "message": "Aucune slide générée. Utilisez POST /api/slides/generate-from-script d'abord."
        })

    response = {
        "status": "success",
        "slides": _generated_slides,
        "slides_count": len(_generated_slides),
        "generation_mode": _generation_mode
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
    global _generated_slides, _generation_error, _generation_stats, _generation_timeline, _transcription_full, _pipeline_debug, _generation_mode

    _generated_slides = None
    _generation_error = None
    _generation_stats = None
    _generation_timeline = None
    _transcription_full = None
    _pipeline_debug = None
    _generation_mode = None

    logger.info("Slides effacées")

    return jsonify({
        "status": "cleared",
        "message": "Slides effacées avec succès"
    })
