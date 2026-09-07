# slides_routes.py - Routes API pour la génération de slides
from flask import Blueprint, jsonify, request, session
from services.script_slide_generation_service import (
    generate_slides_from_script,
    get_latest_script_slide_deck,
    preview_slides_from_text,
)
from repositories.pipeline_repository import hr_resource_belongs_to_center
from services.admin_access_service import can_access_formation_pipeline
from utils.logger import get_logger

logger = get_logger(__name__)

slides_bp = Blueprint("slides", __name__, url_prefix="/api/slides")

_RETIRED_AUDIO_SLIDE_RESPONSE = {
    "status": "retired",
    "code": "audio_slide_generation_retired",
    "message": (
        "La génération de slides depuis l'audio a été retirée. "
        "Les slides sont désormais générées depuis le script validé."
    ),
}


def _retired_audio_slide_response():
    return jsonify(_RETIRED_AUDIO_SLIDE_RESPONSE), 410


@slides_bp.before_request
def require_admin_for_slide_workbench():
    """Keep every deck operation inside its owning centre boundary.

    Retired prototype endpoints and the text preview remain super-admin only.
    A training centre can use persisted script deck endpoints only after the
    referenced folder (and an optional platform hint) resolves to its own
    PostgreSQL tenant.
    """
    if request.method == "OPTIONS":
        return None
    if not session.get("is_admin", False):
        return jsonify({"status": "error", "message": "Non autorisé"}), 403

    account_type = str(session.get("admin_account_type") or "").strip().lower()
    if request.endpoint == "slides.generate_from_script":
        account_id = session.get("admin_account_id")
        if (
            account_type != "training_center"
            or not can_access_formation_pipeline(account_type, account_id)
        ):
            return jsonify({"status": "error", "message": "Non autorisé"}), 403
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
    """Indique explicitement que l'ancien générateur audio a été retiré."""
    return _retired_audio_slide_response()


@slides_bp.route("/generate-v3", methods=["POST"])
def generate_v3():
    """Indique explicitement que l'ancien générateur audio v3 a été retiré."""
    return _retired_audio_slide_response()


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
            "model": "deepseek-v4-pro"  # optionnel
        }
    """
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

        slides = result["slides"]
        stats = result["stats"]
        timeline = result["timeline"]
        pipeline_debug = result.get("pipeline_debug", {})
        generation_mode = (stats or {}).get("generation_mode") or "script"

        logger.info("Génération script réussie: %s slides", len(slides))

        return jsonify({
            "status": "success",
            "generation_mode": generation_mode,
            "slides_count": len(slides),
            "slides": slides,
            "stats": stats,
            "timeline": timeline,
            "pipeline_debug": pipeline_debug,
        })

    except ValueError as e:
        logger.error(f"Erreur de validation génération script: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400

    except Exception as e:
        logger.exception("Erreur lors de la génération depuis script")
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
            "model": "deepseek-v4-pro"
        }
    """
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

        slides = result["slides"]
        stats = result["stats"]
        timeline = result["timeline"]
        pipeline_debug = result.get("pipeline_debug", {})

        return jsonify({
            "status": "success",
            "generation_mode": "script_preview",
            "slides_count": len(slides),
            "slides": slides,
            "stats": stats,
            "timeline": timeline,
            "pipeline_debug": pipeline_debug,
        })

    except ValueError as e:
        logger.error(f"Erreur de validation preview slides: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        logger.exception("Erreur preview slides depuis texte")
        return jsonify({
            "status": "error",
            "message": f"Erreur preview slides depuis texte: {str(e)}",
        }), 500


@slides_bp.route("/data", methods=["GET"])
def get_slides():
    """Récupère le deck persistant d'un cours."""

    folder_id = request.args.get("folder_id")
    if not folder_id:
        return jsonify({
            "status": "error",
            "code": "folder_id_required",
            "message": "Le dossier du cours est requis pour récupérer ses slides.",
        }), 400

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


@slides_bp.route("/status", methods=["GET"])
def status():
    """Indique que le statut de l'ancien générateur a été retiré."""
    return _retired_audio_slide_response()


@slides_bp.route("/clear", methods=["POST"])
def clear():
    """Indique que l'ancien stockage temporaire a été retiré."""
    return _retired_audio_slide_response()
