"""API de suivi de la pipeline Formation 3.

La commande d'un professeur IA est l'unique point d'entrée de création. Le
worker durable enchaîne les étapes. Ces routes exposent uniquement la lecture,
les artefacts et la reprise globale d'une pipeline interrompue.
"""

import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Blueprint, jsonify, request, session, send_file
from io import BytesIO

from services.formation_pipeline_service import (
    search_rncp,
    download_reac_text_with_retry,
    download_rc_text,
    fetch_rome_data,
    generate_global_program,
    run_daily_split,
    daily_programs_are_complete,
    update_job,
    get_job,
    _normalize_day_audio_slots,
    _format_slot_generation_source,
)
from services.knowledge_base_service import (
    build_knowledge_base,
    list_kb,
    kb_stats,
)
from utils.deepseek_client import is_deterministic_deepseek_error
from utils.logger import get_logger
from services.admin_access_service import can_access_formation_pipeline

logger = get_logger(__name__)

formation_bp = Blueprint("formation", __name__)

_SCHEDULED_AUDIO_CAPACITY_LOCK = threading.Lock()
_SCHEDULED_AUDIO_CAPACITY = None
_SCHEDULED_AUDIO_CAPACITY_LIMIT = None

_PIPELINE_MODEL_ALIASES = {
    "flash": "deepseek-v4-flash",
    "pro": "deepseek-v4-pro",
}
_PIPELINE_MODEL_CHOICES = set(_PIPELINE_MODEL_ALIASES)
_LEGACY_PIPELINE_MODEL_CHOICES = {
    "sonnet": "pro",
    "claude-sonnet-4-20250514": "pro",
    "haiku": "flash",
    "claude-haiku-4-5-20251001": "flash",
}

_RETIRED_MANUAL_PIPELINE_ENDPOINTS = frozenset({
    "init_formation",
    "init_test_pipeline",
    "fetch_reac",
    "enrich_reac",
    "generate_global",
    "validate_global",
    "split_daily",
    "validate_daily",
    "launch_tts",
    "refine",
    "launch_volume_safety",
    "review_content",
    "generate_folder_audio",
    "launch_audio",
    "stop_auto_pilot",
})
_RETIRED_MANUAL_PIPELINE_CREATION_ENDPOINTS = frozenset({
    "init_formation",
    "init_test_pipeline",
})


def _slides_folder_workers(default: int = 3) -> int:
    """Nombre de journées dont les decks slides sont générés en parallèle."""
    try:
        workers = int(os.getenv("FORMATION_SLIDES_FOLDER_WORKERS", str(default)))
    except (TypeError, ValueError):
        workers = default
    return max(1, min(8, workers))


def _resolve_pipeline_slide_model(api_model: str | None) -> str | None:
    """Modèle dédié à la curation slides.

    L'itération manuelle "Régénérer curation + slides" utilise DeepSeek Pro par
    défaut. On aligne l'auto-pilot dessus, tout en laissant un override env pour
    les environnements sans clé DeepSeek.
    """
    override = (os.getenv("FORMATION_SLIDES_MODEL") or "").strip()
    if override:
        return _PIPELINE_MODEL_ALIASES.get(override.lower(), override)
    return "deepseek-v4-pro"


def _formation_content_day_workers(default: int = 3) -> int:
    """Bound per-job fan-out so one 52-day course cannot exhaust the service.

    Horizontal queue workers provide SaaS throughput; unbounded fan-out inside
    one job used to multiply day × course workers and overwhelm DB/LLM limits.
    """
    try:
        workers = int(os.getenv("FORMATION_CONTENT_DAY_WORKERS", str(default)))
    except (TypeError, ValueError):
        workers = default
    try:
        maximum = int(os.getenv("FORMATION_CONTENT_DAY_WORKERS_MAX", "8"))
    except (TypeError, ValueError):
        maximum = 8
    return max(1, min(max(1, maximum), workers))


def _preferred_pipeline_failure_cause(failures: list[dict]) -> BaseException | None:
    """Conserve une cause exploitable par la politique de retry durable."""
    def _wait_seconds(cause: BaseException) -> float:
        try:
            return float(getattr(cause, "wait_seconds", 0) or 0)
        except (TypeError, ValueError):
            return 0

    causes = [
        failure.get("exception")
        for failure in failures
        if isinstance(failure.get("exception"), BaseException)
    ]
    return next(
        (cause for cause in causes if is_deterministic_deepseek_error(cause)),
        next(
            (
                cause
                for cause in causes
                if _wait_seconds(cause) > 0
            ),
            causes[0] if causes else None,
        ),
    )


def _raise_pipeline_batch_failure(message: str, failures: list[dict]) -> None:
    error = RuntimeError(message)
    cause = _preferred_pipeline_failure_cause(failures)
    if cause is not None:
        raise error from cause
    raise error


def _normalize_pipeline_model_choice(raw, default=None):
    """Normalise le choix UI persistant de l'auto-pilot."""
    value = (raw or default or "").strip().lower()
    value = _LEGACY_PIPELINE_MODEL_CHOICES.get(value, value)
    if value in _PIPELINE_MODEL_CHOICES:
        return value
    fallback = str(default or "").strip().lower()
    fallback = _LEGACY_PIPELINE_MODEL_CHOICES.get(fallback, fallback)
    return fallback if fallback in _PIPELINE_MODEL_CHOICES else None


def _resolve_pipeline_api_model(job: dict | None, requested_model=None):
    """Résout le modèle API à utiliser pour une action du job.

    Priorité :
      1. modèle explicite passé en argument
      2. modèle choisi au lancement (`auto_pilot_model`)
      3. fallback DeepSeek Pro

    Garantit qu'un job lancé en DeepSeek reste en DeepSeek pour TOUTES les
    étapes, même si `auto_pilot_model` n'a pas été persisté côté DB (jobs
    historiques) — ce qui évite que les services de transition retombent
    silencieusement vers un autre fournisseur.
    """
    model = requested_model or (job or {}).get("auto_pilot_model")
    if not model:
        model = "deepseek-v4-pro"
    model = str(model).strip()
    legacy_choice = _LEGACY_PIPELINE_MODEL_CHOICES.get(model.lower())
    if legacy_choice:
        return _PIPELINE_MODEL_ALIASES[legacy_choice]
    return _PIPELINE_MODEL_ALIASES.get(model.lower(), model)


def _get_platform_id():
    """Retourne platform_id depuis session ou header."""
    pid = request.headers.get("X-Platform-Id") or session.get("platform_id", 1)
    try:
        return int(pid)
    except (ValueError, TypeError):
        return 1


def _require_admin():
    """Retourne True si l'utilisateur est authentifié admin."""
    return session.get("is_admin", False)


def _admin_account_type() -> str:
    """Normalise le type explicite; une session incomplète reste non autorisée."""
    return str(session.get("admin_account_type") or "").strip().lower()


def _training_center_account_id() -> int | None:
    """Retourne un identifiant centre valide, sans valeur implicite permissive."""
    value = session.get("admin_account_id")
    if value is None or isinstance(value, bool):
        return None
    try:
        account_id = int(value)
    except (TypeError, ValueError):
        return None
    return account_id if account_id > 0 else None


def _pipeline_job_not_found():
    """Réponse volontairement non révélatrice pour toute violation de tenant."""
    return jsonify({"error": "Job introuvable"}), 404


def _formation_admin_forbidden():
    return jsonify({"error": "Non autorisé"}), 403


def _retired_manual_pipeline_response(endpoint_name: str):
    if endpoint_name in _RETIRED_MANUAL_PIPELINE_CREATION_ENDPOINTS:
        return jsonify({
            "error": (
                "La création manuelle d'une pipeline a été retirée. "
                "La pipeline démarre automatiquement après la commande d'un professeur IA."
            ),
            "code": "teacher_order_required",
        }), 410

    job_id = (request.view_args or {}).get("job_id")
    payload = {
        "error": (
            "Cette ancienne commande manuelle a été retirée. "
            "Le worker durable enchaîne automatiquement toutes les étapes."
        ),
        "code": "durable_pipeline_only",
    }
    if job_id is not None:
        payload["resume_endpoint"] = f"/api/formation/{int(job_id)}/run-auto/resume"
    return jsonify(payload), 410


@formation_bp.before_request
def _enforce_pipeline_job_tenant_scope():
    """Authenticate and scope every Formation HTTP route before execution.

    Internal workers call services/repositories directly and are unaffected.
    Job ownership is centre-scoped; folder ownership is always checked against
    the URL job before any DB/Blob/report read.
    """
    if request.method == "OPTIONS":
        # Browser CORS preflight carries no authenticated application session.
        return None
    view_args = request.view_args or {}
    if not session.get("is_admin"):
        return _formation_admin_forbidden()

    account_type = _admin_account_type()
    center_account_id = _training_center_account_id()
    if (
        account_type != "training_center"
        or center_account_id is None
        or not can_access_formation_pipeline(account_type, center_account_id)
    ):
        return _formation_admin_forbidden()

    if "job_id" in view_args and center_account_id is not None:
        try:
            from repositories.pipeline_repository import pipeline_job_belongs_to_center

            allowed = pipeline_job_belongs_to_center(
                int(view_args["job_id"]),
                center_account_id,
            )
        except Exception:
            logger.warning(
                "PIPELINE_TENANT_SCOPE_LOOKUP_FAILED job_id=%s center_account_id=%s",
                view_args.get("job_id"),
                center_account_id,
                exc_info=True,
            )
            allowed = False

        if not allowed:
            return _pipeline_job_not_found()

    if "folder_id" in view_args:
        if "job_id" not in view_args:
            return _pipeline_job_not_found()
        try:
            from repositories.pipeline_repository import course_folder_belongs_to_job

            folder_allowed = course_folder_belongs_to_job(
                int(view_args["folder_id"]),
                int(view_args["job_id"]),
            )
        except Exception:
            logger.warning(
                "PIPELINE_FOLDER_SCOPE_LOOKUP_FAILED job_id=%s folder_id=%s",
                view_args.get("job_id"),
                view_args.get("folder_id"),
                exc_info=True,
            )
            folder_allowed = False
        if not folder_allowed:
            return _pipeline_job_not_found()

    endpoint_name = str(request.endpoint or "").rsplit(".", 1)[-1]
    if endpoint_name in _RETIRED_MANUAL_PIPELINE_ENDPOINTS:
        return _retired_manual_pipeline_response(endpoint_name)
    return None


# ─── Recherche RNCP ───────────────────────────────────────────────────────────

@formation_bp.route("/api/formation/search-rncp", methods=["POST"])
def search_rncp_route():
    """
    Recherche des titres RNCP correspondant à un nom de TP.
    Body: { "query": "TP CRCD" }
    Retourne: [{ rncp_code, title }]
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    data = request.get_json() or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "Le champ 'query' est requis"}), 400

    try:
        results = search_rncp(query)
        return jsonify({"results": results})
    except Exception as e:
        logger.error(f"❌ search_rncp : {e}")
        return jsonify({"error": str(e)}), 500


# ─── Initialisation d'un job ──────────────────────────────────────────────────

@formation_bp.route("/api/formation/init", methods=["POST"])
def init_formation():
    """Ancienne commande manuelle conservée comme tombstone HTTP 410."""
    return _retired_manual_pipeline_response("init_formation")


# ─── Mode test : init avec DOCX pré-injectés (skip génération content) ───────

@formation_bp.route("/api/formation/init-test", methods=["POST"])
def init_test_pipeline():
    """Ancienne commande manuelle conservée comme tombstone HTTP 410."""
    return _retired_manual_pipeline_response("init_test_pipeline")


# ─── Statut d'un job ──────────────────────────────────────────────────────────

@formation_bp.route("/api/formation/<int:job_id>", methods=["GET"])
def get_formation_job(job_id):
    """Retourne l'état complet d'un job."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    # Ne pas renvoyer les textes bruts (trop lourds), seulement leurs tailles
    result = {k: v for k, v in job.items() if k not in ("reac_text", "rc_text", "rome_text")}
    result["reac_available"] = bool(job.get("reac_text"))
    result["reac_length"] = len(job.get("reac_text") or "")
    result["rc_length"] = len(job.get("rc_text") or "")
    result["rome_length"] = len(job.get("rome_text") or "")

    return jsonify(result)


# ─── Téléchargement REAC ──────────────────────────────────────────────────────

@formation_bp.route("/api/formation/<int:job_id>/fetch-reac", methods=["POST"])
def fetch_reac(job_id):
    """Ancienne commande manuelle conservée comme tombstone HTTP 410."""
    return _retired_manual_pipeline_response("fetch_reac")


# ─── Couche 1 : Enrichissement REAC → Knowledge Base ─────────────────────────

@formation_bp.route("/api/formation/<int:job_id>/enrich-reac", methods=["POST"])
def enrich_reac(job_id):
    """Ancienne commande manuelle conservée comme tombstone HTTP 410."""
    return _retired_manual_pipeline_response("enrich_reac")


@formation_bp.route("/api/formation/<int:job_id>/kb", methods=["GET"])
def get_kb(job_id):
    """Retourne les entrées KB + statistiques pour un job."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    entries = list_kb(job_id)
    stats = kb_stats(job_id)
    return jsonify({"entries": entries, "stats": stats})


# ─── Génération programme global ──────────────────────────────────────────────

@formation_bp.route("/api/formation/<int:job_id>/generate-global", methods=["POST"])
def generate_global(job_id):
    """Ancienne commande manuelle conservée comme tombstone HTTP 410."""
    return _retired_manual_pipeline_response("generate_global")


# ─── Validation programme global ──────────────────────────────────────────────

@formation_bp.route("/api/formation/<int:job_id>/validate-global", methods=["POST"])
def validate_global(job_id):
    """Ancienne commande manuelle conservée comme tombstone HTTP 410."""
    return _retired_manual_pipeline_response("validate_global")


# ─── Découpage en journées ────────────────────────────────────────────────────

@formation_bp.route("/api/formation/<int:job_id>/split-daily", methods=["POST"])
def split_daily(job_id):
    """Ancienne commande manuelle conservée comme tombstone HTTP 410."""
    return _retired_manual_pipeline_response("split_daily")


# ─── Validation programmes journée ───────────────────────────────────────────

@formation_bp.route("/api/formation/<int:job_id>/validate-daily", methods=["POST"])
def validate_daily(job_id):
    """Ancienne commande manuelle conservée comme tombstone HTTP 410."""
    return _retired_manual_pipeline_response("validate_daily")


# ─── Lancement TTS ────────────────────────────────────────────────────────────

@formation_bp.route("/api/formation/<int:job_id>/launch-tts", methods=["POST"])
def launch_tts(job_id):
    """Ancienne commande manuelle conservée comme tombstone HTTP 410."""
    return _retired_manual_pipeline_response("launch_tts")


# ─── Affinage IA (refine) ─────────────────────────────────────────────────────

@formation_bp.route("/api/formation/<int:job_id>/refine", methods=["POST"])
def refine(job_id):
    """Ancienne commande manuelle conservée comme tombstone HTTP 410."""
    return _retired_manual_pipeline_response("refine")


# ─── Étape 6 : Contenu des journées (lecture + PDF) ──────────────────────────

@formation_bp.route("/api/formation/<int:job_id>/content", methods=["GET"])
def list_content(job_id):
    """
    Retourne la liste des dossiers cours (journées) de ce job avec leur état
    de génération texte : total de mots par journée, nb segments completed,
    statut du content_generation_job associé.
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    import json as _json
    from services.formation_pipeline_service import get_expected_course_folders
    from repositories.pipeline_repository import list_content_completion_rows_for_folders
    from services.script_slide_generation_service import get_latest_script_slide_deck

    folder_state = get_expected_course_folders(job_id)
    folders = [
        (
            f["folder_id"],
            f["name"],
            f["position"],
            f["platform_id"],
            f["formation_job_id"],
        )
        for f in folder_state.get("folders", [])
    ]
    folder_ids = [int(folder[0]) for folder in folders]
    content_rows = {
        int(row["folder_id"]): row
        for row in list_content_completion_rows_for_folders(folder_ids)
    }

    daily_programs = _json.loads(job["daily_programs"] or "[]")
    result = []
    for idx, (fid, fname, fpos, f_platform_id, f_formation_job_id) in enumerate(folders):
        day_meta = daily_programs[idx] if idx < len(daily_programs) else {}
        content_row = content_rows.get(int(fid)) or {}
        cg_id = content_row.get("content_job_id")
        cg_status = content_row.get("status")
        cg_words = content_row.get("total_words") or 0
        cur_sub = content_row.get("current_sub_part") or 0
        cur_passe = content_row.get("current_passe") or 1
        cg_err = content_row.get("error_message")
        n_completed = content_row.get("completed_segments") or 0
        n_reviewed = content_row.get("reviewed_segments") or 0
        n_humanized = content_row.get("humanized_segments") or 0
        n_review_errors = content_row.get("review_error_segments") or 0
        n_dirty = content_row.get("dirty_segments") or 0
        slide_deck_id = None
        slide_count = 0
        slide_generation_mode = None
        if cg_id:
            try:
                deck = get_latest_script_slide_deck(int(fid), content_job_id=int(cg_id))
                if deck:
                    slide_deck_id = deck.get("deck_id")
                    slide_count = len(deck.get("slides") or [])
                    slide_generation_mode = (deck.get("stats") or {}).get("generation_mode")
            except Exception:
                slide_deck_id = None
                slide_count = 0
                slide_generation_mode = None

        day_sub_parts = day_meta.get("sub_parts")
        segment_total = (len(day_sub_parts) if day_sub_parts else 6) * 3
        result.append({
            "folder_id": fid,
            "folder_label": f"F{fid}",
            "folder_name": fname,
            "position": fpos,
            "platform_id": f_platform_id,
            "formation_job_id": f_formation_job_id,
            "content_job_id": cg_id,
            "day_number": day_meta.get("day_number", idx + 1),
            "day_title": day_meta.get("title", fname),
            "content_status": cg_status,
            "total_words": cg_words or 0,
            "segments_completed": n_completed,
            "segments_total": max(3, segment_total),
            "segments_humanized": n_humanized,
            "segments_reviewed": n_reviewed,
            "segments_review_errors": n_review_errors,
            "dirty_segments": n_dirty,
            "slide_deck_id": slide_deck_id,
            "slide_count": slide_count,
            "slide_generation_mode": slide_generation_mode,
            "current_sub_part": cur_sub,
            "current_passe": cur_passe,
            "error_message": cg_err,
        })

    return jsonify({
        "folders": result,
        "job_status": job["status"],
        "folder_resolution": {
            "expected_count": folder_state.get("expected_count", 0),
            "duplicates": folder_state.get("duplicates", []),
            "missing": folder_state.get("missing", []),
        },
    })


@formation_bp.route("/api/formation/<int:job_id>/content/<int:folder_id>/text", methods=["GET"])
def get_course_text(job_id, folder_id):
    """Retourne le texte complet d'une journée assemblé section par section (pour relecture UI)."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    try:
        from services.formation_docx_service import (
            _get_segments_for_folder, _strip_tts_tags,
        )
        segments = _get_segments_for_folder(folder_id)
        # Format lisible pour la modal : chaque section précédée de son titre
        sections = []
        for i, part in enumerate(segments):
            title = f"{i + 1}. {part['name']}"
            body = _strip_tts_tags(part['body'])
            sections.append(f"═══ {title} ═══\n\n{body}")
        return jsonify({"text": "\n\n\n".join(sections), "sections_count": len(segments)})
    except Exception as e:
        logger.error(f"❌ Job {job_id} get_course_text folder={folder_id} : {e}")
        return jsonify({"error": str(e)}), 500


@formation_bp.route("/api/formation/<int:job_id>/content/<int:folder_id>/artifact/<path:filename>", methods=["GET"])
def get_content_artifact(job_id, folder_id, filename):
    """Retourne un artefact JSON structuré d'une journée pour l'audit UI."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    from services.content_pipeline.artifacts import (
        CONTENT_ARTIFACT_BLOBS,
        load_content_artifact,
    )
    from repositories.pipeline_repository import get_content_generation_job_by_folder

    filename = os.path.basename(str(filename or ""))
    if filename not in CONTENT_ARTIFACT_BLOBS:
        return jsonify({"error": "Artefact non autorisé"}), 400

    folder_row = get_content_generation_job_by_folder(folder_id)
    if not folder_row or int(folder_row.get("formation_job_id") or 0) != int(job_id):
        return jsonify({"error": "Folder introuvable ou hors pipeline"}), 404

    platform_id = int(folder_row["platform_id"])
    folder_name = folder_row.get("name") or ""
    artifact = load_content_artifact(platform_id, folder_id, filename)
    if not artifact:
        return jsonify({"error": "Artefact indisponible", "filename": filename}), 404

    return jsonify({
        "artifact": artifact,
        "filename": filename,
        "folder_id": folder_id,
        "folder_name": folder_name,
    }), 200


@formation_bp.route("/api/formation/<int:job_id>/content/<int:folder_id>/docx", methods=["GET"])
def download_course_docx(job_id, folder_id):
    """Télécharge le document Word d'une journée de formation (programme officiel).

    Query param `version` :
    - "current" (défaut) : texte DB actuel (= post-révision si appliquée)
    - "pre_review" : snapshot pris au finalize content (= avant révision)
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    version = request.args.get("version", "current")
    if version not in ("current", "pre_review"):
        return jsonify({"error": f"version invalide : {version}"}), 400

    try:
        from services.formation_docx_service import build_course_docx
        docx_bytes, filename = build_course_docx(
            job_id=job_id, folder_id=folder_id, version=version,
        )
        return send_file(
            BytesIO(docx_bytes),
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        logger.error(f"❌ Job {job_id} download_course_docx folder={folder_id} v={version} : {e}")
        return jsonify({"error": str(e)}), 500


# ─── Rapport de révision conformité ──────────────────────────────────────────

def _short_review_excerpt(text: str, limit: int = 220) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _build_db_review_report(job_id: int, folder_id: int) -> dict | None:
    """Fallback persistant pour les reviews API: reconstruit un rapport depuis
    la DB quand aucun ancien fichier local review_report.json n'existe.

    Les anciennes reviews API ne stockaient pas l'historique exact des patches.
    On peut tout de même afficher un rapport exploitable: segments relus,
    erreurs éventuelles, et segments dont le texte courant diffère du snapshot
    pre-review.
    """
    from repositories.pipeline_repository import list_completed_segment_review_rows_for_folder

    rows = list_completed_segment_review_rows_for_folder(
        formation_job_id=job_id,
        folder_id=folder_id,
    )
    if not rows:
        return None

    folder_name = rows[0]["folder_name"]
    by_segment = []
    changed_count = 0
    reviewed_count = 0
    failed_count = 0

    for row in rows:
        seg_id = row["segment_id"]
        sub_idx = row["sub_part_index"]
        passe = row["passe"]
        reviewed = row["reviewed"]
        review_error = row["review_error"] or ""
        text = row["text_content"] or ""
        pre_text = row["text_content_pre_review"] or ""
        word_count = row["word_count"] or 0
        reviewed = int(reviewed or 0)
        if reviewed:
            reviewed_count += 1
        if review_error and not reviewed:
            failed_count += 1

        before = (pre_text or text or "").strip()
        after = (text or "").strip()
        changed = bool(reviewed and pre_text and before != after)
        patches_detail = []
        patches_applied = 0
        patches_rejected = 0

        if changed:
            changed_count += 1
            patches_applied = 1
            patches_detail.append({
                "rule": "#DB",
                "reason": "Texte modifié par la révision API; détail exact des patches non persisté sur les anciennes exécutions.",
                "original": _short_review_excerpt(before),
                "replacement": _short_review_excerpt(after),
                "status": "applied",
            })
        elif review_error:
            patches_rejected = 1
            patches_detail.append({
                "rule": "#ERR",
                "reason": review_error[:220],
                "original": "",
                "replacement": "",
                "status": "rejected",
                "reject_reason": "erreur reviewer",
            })

        by_segment.append({
            "sub_idx": sub_idx,
            "passe": passe,
            "segment_id_actual": seg_id,
            "word_count": word_count,
            "patches_applied": patches_applied,
            "patches_rejected": patches_rejected,
            "patches_detail": patches_detail,
        })

    by_rule = {}
    if changed_count:
        by_rule["#DB"] = {
            "proposed": changed_count,
            "applied": changed_count,
            "rejected": 0,
            "unknown": 0,
        }
    if failed_count:
        by_rule["#ERR"] = {
            "proposed": failed_count,
            "applied": 0,
            "rejected": failed_count,
            "unknown": 0,
        }

    return {
        "folder_id": folder_id,
        "folder_name": folder_name,
        "imported_at": None,
        "generated_via": "db_review_status",
        "is_db_fallback": True,
        "reconstruction_note": (
            "Aucun fichier review_report.json n'a été trouvé. Rapport reconstruit "
            "depuis la base: statut des segments, erreurs reviewer et comparaison "
            "texte courant / snapshot avant révision."
        ),
        "summary": {
            "segments_reviewed": reviewed_count,
            "patches_proposed": changed_count + failed_count,
            "patches_applied": changed_count,
            "patches_rejected": failed_count,
            "patches_unknown": 0,
            "segments_failed": failed_count,
        },
        "by_rule": by_rule,
        "by_segment": by_segment,
    }


def _write_api_review_report(job_id: int, folder_id: int, result: dict, model: str | None) -> dict | None:
    """Persiste un rapport conformité pour les reviews lancées via l'API.

    La DB est la source durable. Le fichier local est seulement un artefact de
    debug, car il peut disparaître ou être inaccessible en hébergement.
    """
    import json as _json
    import os
    from datetime import datetime
    from services.formation_review_artifact_service import review_artifact_dir
    from repositories.pipeline_repository import get_text_folder_state

    folder = get_text_folder_state(folder_id)
    if not folder or int(folder.get("formation_job_id") or 0) != int(job_id):
        return
    folder_name = folder.get("folder_name") or ""
    position = int(folder.get("position") or 0)
    review_kind = result.get("review_kind") or "compliance"
    review_label = result.get("review_label") or "Révision conformité"

    by_rule = {}
    by_segment = []
    for detail in result.get("details") or []:
        applied = detail.get("applied") or []
        rejected = detail.get("rejected") or []
        patches_detail = []

        for status, patches in (("applied", applied), ("rejected", rejected)):
            for p in patches:
                rule = str(p.get("rule_violated") or p.get("rule") or "?")
                stat = by_rule.setdefault(rule, {"proposed": 0, "applied": 0, "rejected": 0, "unknown": 0})
                stat["proposed"] += 1
                stat[status] += 1
                patches_detail.append({
                    "rule": rule,
                    "reason": str(p.get("reason") or "")[:240],
                    "original": _short_review_excerpt(p.get("original") or ""),
                    "replacement": _short_review_excerpt(p.get("replacement") or ""),
                    "status": status,
                    "reject_reason": p.get("reject_reason"),
                })

        if detail.get("error"):
            stat = by_rule.setdefault("#ERR", {"proposed": 0, "applied": 0, "rejected": 0, "unknown": 0})
            stat["proposed"] += 1
            stat["rejected"] += 1
            patches_detail.append({
                "rule": "#ERR",
                "reason": str(detail.get("error") or "")[:240],
                "original": "",
                "replacement": "",
                "status": "rejected",
                "reject_reason": "erreur reviewer",
            })

        by_segment.append({
            "sub_idx": detail.get("sub_idx"),
            "passe": detail.get("passe"),
            "segment_id_actual": detail.get("segment_id"),
            "patches_proposed": detail.get("proposed", len(applied) + len(rejected)),
            "patches_applied": len(applied),
            "patches_rejected": len(rejected) + (1 if detail.get("error") else 0),
            "patches_detail": patches_detail,
        })

    report = {
        "folder_id": folder_id,
        "folder_name": folder_name,
        "imported_at": datetime.utcnow().isoformat() + "Z",
        "generated_via": model or "api",
        "review_kind": review_kind,
        "review_label": review_label,
        "review_signature": result.get("review_signature"),
        "force": bool(result.get("force")),
        "summary": {
            "segments_reviewed": result.get("segments_reviewed", 0),
            "segments_already_current": result.get("segments_already_current", 0),
            "segments_total_completed": result.get("segments_total_completed", 0),
            "patches_proposed": result.get(
                "patches_proposed",
                result.get("patches_applied", 0) + result.get("patches_rejected", 0),
            ),
            "patches_applied": result.get("patches_applied", 0),
            "patches_rejected": result.get("patches_rejected", 0),
            "segments_failed": result.get("segments_failed", 0),
        },
        "by_rule": by_rule,
        "by_segment": sorted(by_segment, key=lambda x: (x.get("sub_idx") or 0, x.get("passe") or 0)),
    }

    from services.formation_observability_service import persist_review_report
    report_id = persist_review_report(
        job_id,
        folder_id,
        report,
        source="api" if review_kind == "compliance" else f"{review_kind}_api",
        generated_via=model or "api",
    )
    report["persisted_report_id"] = report_id

    suffix = "review_api" if review_kind == "compliance" else f"review_{review_kind}_api"
    chunk_id = f"day_{int(position or 0) + 1}_{suffix}"
    chunk_dir = os.path.join(review_artifact_dir(job_id, "review"), chunk_id)
    try:
        os.makedirs(chunk_dir, exist_ok=True)
        with open(os.path.join(chunk_dir, "review_report.json"), "w", encoding="utf-8") as f:
            _json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(
            f"⚠️ Rapport conformité fichier non écrit job={job_id} "
            f"folder={folder_id} : {e}"
        )
    return report


def _review_chunk_ids_for_position(position: int) -> list[str]:
    from services.content_generation_service import _COMPLIANCE_REVIEW_RULE_GROUPS

    day = int(position or 0) + 1
    return (
        [f"day_{day}_review_{g['id']}" for g in _COMPLIANCE_REVIEW_RULE_GROUPS]
        + [
            f"day_{day}_review_api",
            f"day_{day}_review_local_compliance_api",
            f"day_{day}_review_humanization_api",
            f"day_{day}_review",
        ]
    )


def _parse_report_timestamp(value):
    if not value:
        return None
    from datetime import datetime, timezone

    raw = str(value).strip()
    if not raw:
        return None
    iso = raw.replace(" ", "T")
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _latest_continue_after_text_started_at(job_id: int, folder_id: int) -> str | None:
    from repositories.pipeline_repository import get_latest_pipeline_event_created_at

    try:
        created_at = get_latest_pipeline_event_created_at(
            job_id=job_id,
            folder_id=folder_id,
            event_type="continue_after_text_started",
        )
        return created_at.isoformat() if hasattr(created_at, "isoformat") else created_at
    except Exception:
        return None


def _report_is_after_cutoff(report: dict | None, cutoff: str | None) -> bool:
    if not cutoff:
        return True
    if not report:
        return False
    report_ts = (
        report.get("persisted_at")
        or report.get("imported_at")
        or report.get("created_at")
    )
    report_time = _parse_report_timestamp(report_ts)
    cutoff_time = _parse_report_timestamp(cutoff)
    if report_time is None or cutoff_time is None:
        return False
    return report_time >= cutoff_time


def _db_review_report_is_complete(report: dict | None) -> bool:
    if not report:
        return False
    segments = report.get("by_segment") or []
    if not segments:
        return False
    summary = report.get("summary") or {}
    processed = int(summary.get("segments_reviewed") or 0) + int(summary.get("segments_failed") or 0)
    return processed >= len(segments)


@formation_bp.route(
    "/api/formation/<int:job_id>/content/<int:folder_id>/review-report",
    methods=["GET"],
)
def get_review_report(job_id, folder_id):
    """Retourne le rapport JSON détaillé de la révision conformité pour 1
    journée. La DB est prioritaire; les anciens artefacts
    `review_queue/job_X/step_review/` restent lisibles comme compatibilité.

    Format de retour :
    {
      "summary": {segments_reviewed, patches_proposed, patches_applied,
                  patches_rejected, segments_failed},
      "by_rule": {"#22": {proposed, applied, rejected}, ...},
      "by_segment": [{sub_idx, passe, patches_applied, patches_rejected,
                      patches_detail: [{rule, original, replacement,
                                        reason, status, reject_reason?}]}],
      "imported_at", "generated_via", "via_positional_fallback"
    }
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    import os
    import json as _json
    from services.formation_review_artifact_service import (
        DONE_ARTIFACT_ROOT,
        extract_json,
        review_artifact_dir,
    )

    # Trouver la position du folder pour reconstruire le chunk_id (day_N_review)
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    from repositories.pipeline_repository import get_text_folder_state
    folder = get_text_folder_state(folder_id)
    if not folder or int(folder.get("formation_job_id") or 0) != int(job_id):
        return jsonify({"error": "Folder introuvable ou hors pipeline"}), 404
    position = int(folder.get("position") or 0)
    retry_cutoff = _latest_continue_after_text_started_at(job_id, folder_id)
    stale_report_ignored = False

    try:
        from services.formation_observability_service import get_latest_review_report
        persisted_report = get_latest_review_report(job_id, folder_id)
        if persisted_report and _report_is_after_cutoff(persisted_report, retry_cutoff):
            return jsonify({"report": persisted_report, "source": "db"}), 200
        if persisted_report:
            stale_report_ignored = True
    except Exception as e:
        logger.warning(
            f"⚠️ Lecture rapport conformité DB impossible job={job_id} "
            f"folder={folder_id} : {e}"
        )

    # Les anciens rapports pouvaient être découpés par groupe de règles. On
    # cherche le rapport courant, mais après une relance aval on ignore tout
    # rapport plus ancien.
    chunk_id_candidates = _review_chunk_ids_for_position(position)

    if os.path.isdir(DONE_ARTIFACT_ROOT):
        archived = sorted(
            (
                directory
                for directory in os.listdir(DONE_ARTIFACT_ROOT)
                if directory.endswith(f"-job{job_id}-review")
            ),
            reverse=True,
        )
    else:
        archived = []

    # Collecte tous les review_report.json existants (multi-chunks)
    sub_reports = []
    for cid in chunk_id_candidates:
        paths = [
            os.path.join(
                review_artifact_dir(job_id, "review"),
                cid,
                "review_report.json",
            )
        ]
        for arch in archived:
            paths.append(
                os.path.join(
                    DONE_ARTIFACT_ROOT,
                    arch,
                    cid,
                    "review_report.json",
                )
            )
        for p in paths:
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        loaded_report = _json.load(f)
                    if _report_is_after_cutoff(loaded_report, retry_cutoff):
                        sub_reports.append((cid, loaded_report))
                    else:
                        stale_report_ignored = True
                    break  # 1 seul par chunk_id (le plus récent)
                except Exception:
                    pass

    if sub_reports:
        # Agrégation des sub_reports en un rapport unique
        agg_summary = {
            "segments_reviewed": 0, "patches_proposed": 0,
            "patches_applied": 0, "patches_rejected": 0, "segments_failed": 0,
        }
        agg_by_rule = {}
        agg_by_segment = {}  # clé (sub_idx, passe) → segment agrégé
        any_positional = False
        latest_imported = None
        generated_via = None

        for cid, rep in sub_reports:
            s = rep.get("summary", {})
            for k in agg_summary:
                agg_summary[k] = max(agg_summary[k], s.get(k, 0)) if k == "segments_reviewed" else agg_summary[k] + s.get(k, 0)
            for rule, st in (rep.get("by_rule") or {}).items():
                agg = agg_by_rule.setdefault(rule, {"proposed": 0, "applied": 0, "rejected": 0, "unknown": 0})
                for kk, vv in st.items():
                    agg[kk] = agg.get(kk, 0) + vv
            for seg in (rep.get("by_segment") or []):
                key = (seg.get("sub_idx"), seg.get("passe"))
                if key not in agg_by_segment:
                    agg_by_segment[key] = {
                        "sub_idx": seg.get("sub_idx"),
                        "passe": seg.get("passe"),
                        "segment_id_actual": seg.get("segment_id_actual"),
                        "patches_applied": 0, "patches_rejected": 0,
                        "patches_detail": [],
                    }
                agg_by_segment[key]["patches_applied"] += seg.get("patches_applied", 0)
                agg_by_segment[key]["patches_rejected"] += seg.get("patches_rejected", 0)
                for d in seg.get("patches_detail") or []:
                    d_copy = dict(d)
                    d_copy["agent_group"] = cid.replace(f"day_{position + 1}_review_", "")
                    agg_by_segment[key]["patches_detail"].append(d_copy)
            if rep.get("via_positional_fallback"):
                any_positional = True
            if rep.get("imported_at") and (latest_imported is None or rep["imported_at"] > latest_imported):
                latest_imported = rep["imported_at"]
            if not generated_via:
                generated_via = rep.get("generated_via")

        # by_segment trié par (sub_idx, passe)
        agg_segments = sorted(agg_by_segment.values(), key=lambda x: (x["sub_idx"] or 0, x["passe"] or 0))

        report = {
            "folder_id": folder_id,
            "folder_name": (sub_reports[0][1].get("folder_name") if sub_reports else None),
            "imported_at": latest_imported,
            "generated_via": generated_via,
            "via_positional_fallback": any_positional,
            "n_agents": len(sub_reports),
            "agents_used": [cid.replace(f"day_{position + 1}_review_", "") for cid, _ in sub_reports],
            "summary": agg_summary,
            "by_rule": agg_by_rule,
            "by_segment": agg_segments,
        }
        try:
            from services.formation_observability_service import persist_review_report
            persist_review_report(
                job_id,
                folder_id,
                report,
                source="file_import",
                generated_via=generated_via,
            )
        except Exception as e:
            logger.warning(
                f"⚠️ Rapport conformité fichier non persisté job={job_id} "
                f"folder={folder_id} : {e}"
            )
        return jsonify({"report": report, "n_sub_reports": len(sub_reports)}), 200

    # Fallback : pas de review_report.json mais peut-être un output.md
    # existant d'un import antérieur (avant que je code l'écriture du
    # rapport). On reconstitue un rapport "best-effort" depuis output.md +
    # input.md + DB actuelle (heuristique : un patch est "appliqué" si son
    # replacement est dans le texte courant et son original n'y est plus).
    # Cherche dans tous les chunk_id candidats (multi-agents + legacy).
    output_md_paths = []
    for cid in chunk_id_candidates:
        output_md_paths.append(
            os.path.join(
                review_artifact_dir(job_id, "review"),
                cid,
                "output.md",
            )
        )
        for arch in archived:
            output_md_paths.append(
                os.path.join(DONE_ARTIFACT_ROOT, arch, cid, "output.md")
            )

    chunk_dir_with_output = None
    if not retry_cutoff:
        for p in output_md_paths:
            if os.path.exists(p):
                chunk_dir_with_output = os.path.dirname(p)
                break

    if not chunk_dir_with_output:
        report = _build_db_review_report(job_id, folder_id)
        if report and (not retry_cutoff or _db_review_report_is_complete(report)):
            return jsonify({"report": report, "source": "db_fallback"}), 200
        if retry_cutoff:
            return jsonify({
                "error": "Nouveau rapport de révision pas encore disponible pour cette relance",
                "report": None,
                "retry_started_at": retry_cutoff,
                "stale_report_ignored": stale_report_ignored,
            }), 404
        return jsonify({
            "error": "Aucun rapport de révision trouvé pour ce dossier",
            "report": None,
        }), 404

    try:
        with open(os.path.join(chunk_dir_with_output, "output.md"), "r", encoding="utf-8") as f:
            output_text = f.read()
        parsed = _json.loads(extract_json(output_text))
        reviews = parsed.get("reviews", [])
    except Exception as e:
        return jsonify({"error": f"output.md illisible : {e}"}), 500

    # Récupère input.md (segments d'origine) pour la résolution positionnelle
    input_md_path = os.path.join(chunk_dir_with_output, "input.md")
    input_segments = []
    if os.path.exists(input_md_path):
        try:
            with open(input_md_path, "r", encoding="utf-8") as f:
                input_segments = _json.loads(f.read())
        except Exception:
            input_segments = []

    # Récupère les textes actuels en DB (résolution par sub_idx, passe via folder)
    from repositories.pipeline_repository import list_completed_segment_review_rows_for_folder
    db_rows = list_completed_segment_review_rows_for_folder(
        formation_job_id=job_id,
        folder_id=folder_id,
    )
    # Map (sub_idx, passe) → text actuel (le plus récent en cas de doublons)
    db_text_by_sp = {}
    for r in db_rows:
        key = (r["sub_part_index"], r["passe"])
        if key not in db_text_by_sp:
            db_text_by_sp[key] = (r["segment_id"], r["text_content"])

    # Construction du rapport lite
    by_rule = {}
    by_segment = []
    applied_total = 0
    rejected_total = 0
    unknown_total = 0

    for i, rev in enumerate(reviews):
        patches = rev.get("patches", []) or []
        # Résolution positionnelle via input.md
        if i < len(input_segments):
            sub_idx = input_segments[i].get("sub_idx", -1)
            passe = input_segments[i].get("passe", -1)
        else:
            sub_idx = -1
            passe = -1
        seg_db = db_text_by_sp.get((sub_idx, passe))
        current_text = seg_db[1] if seg_db else ""
        actual_segment_id = seg_db[0] if seg_db else None

        seg_applied = 0
        seg_rejected = 0
        seg_unknown = 0
        seg_patches_detail = []
        for p in patches[:5]:
            original = (p.get("original") or "")[:1000]
            replacement = (p.get("replacement") or "")[:1000]
            rule = str(p.get("rule_violated", "?"))[:10]
            reason = str(p.get("reason", ""))[:200]
            if not original or not replacement:
                continue
            rule_stat = by_rule.setdefault(rule, {"proposed": 0, "applied": 0, "rejected": 0, "unknown": 0})
            rule_stat["proposed"] += 1
            # Heuristique
            if current_text:
                has_repl = replacement in current_text
                has_orig = original in current_text
                if has_repl and not has_orig:
                    status = "applied"
                    seg_applied += 1
                    rule_stat["applied"] += 1
                elif has_orig:
                    status = "rejected"
                    seg_rejected += 1
                    rule_stat["rejected"] += 1
                else:
                    status = "unknown"
                    seg_unknown += 1
                    rule_stat["unknown"] += 1
            else:
                status = "unknown"
                seg_unknown += 1
                rule_stat["unknown"] += 1
            seg_patches_detail.append({
                "rule": rule, "reason": reason,
                "original": original[:200], "replacement": replacement[:200],
                "status": status,
                "reject_reason": "détecté heuristiquement" if status == "rejected" else None,
            })

        applied_total += seg_applied
        rejected_total += seg_rejected
        unknown_total += seg_unknown

        by_segment.append({
            "sub_idx": sub_idx,
            "passe": passe,
            "segment_id_actual": actual_segment_id,
            "patches_applied": seg_applied,
            "patches_rejected": seg_rejected,
            "patches_unknown": seg_unknown,
            "patches_detail": seg_patches_detail,
        })

    report = {
        "folder_id": folder_id,
        "folder_name": None,  # pas dispo en mode reconstruit
        "imported_at": None,
        "generated_via": "reconstructed_from_output_md",
        "is_reconstructed": True,
        "reconstruction_note": (
            "Rapport reconstitué a posteriori depuis output.md + DB actuelle. "
            "Statuts applied/rejected déduits par heuristique (replacement "
            "présent dans le texte = appliqué, original encore présent = rejeté). "
            "Précision approximative."
        ),
        "summary": {
            "segments_reviewed": len(reviews),
            "patches_proposed": sum(len(r.get("patches", [])) for r in reviews),
            "patches_applied": applied_total,
            "patches_rejected": rejected_total,
            "patches_unknown": unknown_total,
            "segments_failed": 0,
        },
        "by_rule": by_rule,
        "by_segment": by_segment,
    }
    try:
        from services.formation_observability_service import persist_review_report
        persist_review_report(
            job_id,
            folder_id,
            report,
            source="output_md_reconstruction",
            generated_via=report["generated_via"],
        )
    except Exception as e:
        logger.warning(
            f"⚠️ Rapport conformité reconstruit non persisté job={job_id} "
            f"folder={folder_id} : {e}"
        )
    return jsonify({"report": report, "source_path": chunk_dir_with_output, "lite": True}), 200


@formation_bp.route(
    "/api/formation/<int:job_id>/content/<int:folder_id>/humanization-report",
    methods=["GET"],
)
def get_humanization_report(job_id, folder_id):
    """Retourne le rapport JSON de la passe humanisation (intros/transitions/rythme)."""
    from services.formation_observability_service import get_latest_review_report
    report = get_latest_review_report(job_id, folder_id, kind="humanization")
    if not report:
        return jsonify({"error": "Aucun rapport d'humanisation disponible pour cette journée"}), 404
    return jsonify({"report": report}), 200


# ─── Legacy — audit volume lisible, enrichissement append-only désactivé ─────

@formation_bp.route("/api/formation/<int:job_id>/volume-audit", methods=["GET"])
def volume_audit(job_id):
    """Retourne l'audit volume par-folder pour un job.

    Pour chaque folder du job, calcule :
      - total_words : mots parlés des segments completed, tags TTS exclus
      - deficit : mots manquants sous le budget minimal audio
      - shortest_segments : top N (5) des segments les plus courts (pour
        l'affichage UI et le ciblage de l'enrichissement)

    Pas d'effet de bord — purement lecture.
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    from services.formation_volume_audit_service import compute_volume_audit
    try:
        audit = compute_volume_audit(job_id)
        return jsonify(audit), 200
    except Exception as e:
        logger.error(f"❌ volume_audit job {job_id} : {e}")
        return jsonify({"error": str(e)}), 500


@formation_bp.route(
    "/api/formation/<int:job_id>/content/<int:folder_id>/volume-safety",
    methods=["POST"],
)
def launch_volume_safety(job_id, folder_id):
    """Ancienne commande manuelle conservée comme tombstone HTTP 410."""
    return _retired_manual_pipeline_response("launch_volume_safety")


# ─── Ancienne reprise partielle de la génération texte ───────────────────────

@formation_bp.route("/api/formation/<int:job_id>/resume-content", methods=["POST"])
def resume_content(job_id):
    """Ancienne reprise directe, remplacée par la reprise globale durable."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    return jsonify({
        "error": (
            "La reprise partielle du texte a été retirée. "
            "Utilise « Reprendre la pipeline » pour reprendre depuis le dernier checkpoint durable."
        ),
        "code": "durable_pipeline_resume_required",
        "resume_endpoint": f"/api/formation/{job_id}/run-auto/resume",
    }), 410


# ─── Étape 6bis : Révision conformité via reviewer API DeepSeek ──────────────
# Le runner CLI local historique a été supprimé : cette route utilise
# exclusivement le reviewer API de la pipeline courante.

@formation_bp.route(
    "/api/formation/<int:job_id>/content/<int:folder_id>/review",
    methods=["POST"],
)
def review_content(job_id, folder_id):
    """Ancienne commande manuelle conservée comme tombstone HTTP 410."""
    return _retired_manual_pipeline_response("review_content")


# ─── Pre-flight et health-check (audit pipeline) ─────────────────────────────

@formation_bp.route("/api/formation/<int:job_id>/preflight", methods=["POST"])
def preflight_pipeline(job_id):
    """Audit AVANT lancement : valide que la pipeline a les chances de tourner
    one-shot (config + connectivité externe). Body :
      { "tts_mode": "fish_audio"|"gtts"|"mock" }
    Retourne :
      { "ok": bool, "blocking": [...], "warnings": [...], "checks": {...} }
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403
    payload = request.get_json(silent=True) or {}
    tts_mode = (payload.get("tts_mode") or "gtts").lower()
    try:
        from services.formation_health_service import compute_preflight
        result = compute_preflight(job_id, tts_mode=tts_mode)
        return jsonify(result), 200 if result["ok"] else 422
    except Exception as e:
        logger.error(f"❌ preflight job {job_id} : {e}")
        return jsonify({"error": str(e)}), 500


@formation_bp.route("/api/formation/<int:job_id>/health", methods=["GET"])
def health_pipeline(job_id):
    """Audit APRÈS lancement : vérifie que la pipeline a produit des artefacts
    cohérents (segments, DOCX, snapshots, audio, module persistant).
    Retourne :
      { "ok": bool, "blocking": [...], "warnings": [...], "checks": {...} }
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403
    try:
        from services.formation_health_service import compute_health
        result = compute_health(job_id)
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"❌ health-check job {job_id} : {e}")
        return jsonify({"error": str(e)}), 500


# ─── Étape 7 : Lancement de la synthèse TTS Fish Audio ───────────────────────


class _ScheduledAudioLeaseLost(RuntimeError):
    """The scheduled-session fencing token no longer belongs to this worker."""


def _legacy_bulk_audio_enabled() -> bool:
    """Emergency-only opt-in for pre-SaaS all-days synthesis endpoints."""
    return str(os.getenv("ALLOW_LEGACY_BULK_AUDIO", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _try_acquire_scheduled_audio_capacity() -> bool:
    """Apply per-instance backpressure before claiming a durable occurrence."""
    global _SCHEDULED_AUDIO_CAPACITY, _SCHEDULED_AUDIO_CAPACITY_LIMIT
    try:
        limit = max(1, int(os.getenv("SCHEDULED_AUDIO_MAX_CONCURRENCY", "1") or "1"))
    except (TypeError, ValueError):
        limit = 1
    with _SCHEDULED_AUDIO_CAPACITY_LOCK:
        if _SCHEDULED_AUDIO_CAPACITY is None:
            _SCHEDULED_AUDIO_CAPACITY = threading.BoundedSemaphore(limit)
            _SCHEDULED_AUDIO_CAPACITY_LIMIT = limit
        # Do not replace a live semaphore when configuration changes at runtime;
        # doing so would lose the count held by active workers.
        capacity = _SCHEDULED_AUDIO_CAPACITY
    return bool(capacity.acquire(blocking=False))


def _release_scheduled_audio_capacity() -> None:
    capacity = _SCHEDULED_AUDIO_CAPACITY
    if capacity is None:
        return
    try:
        capacity.release()
    except ValueError:
        logger.error("PIPELINE_SCHEDULED_AUDIO_CAPACITY_OVER_RELEASE", exc_info=True)


def _spawn_audio_background_task(
    target,
    *,
    use_native_thread: bool,
    name: str,
):
    """Start audio independently from the HTTP request thread."""
    del use_native_thread  # Conservé dans le contrat d'appel du scheduler.
    runner = threading.Thread(target=target, name=name, daemon=True)
    runner.start()
    return runner


def _assert_scheduled_audio_ownership(
    schedule_session_id: int | None,
    schedule_claim_started_at,
    *,
    ownership_state: dict | None = None,
) -> None:
    """Touch and validate the scheduled-audio fencing token.

    A database error is treated exactly like a lost token: without a durable
    ownership proof the worker must not publish or finalize generated audio.
    """
    if not schedule_session_id:
        return
    if schedule_claim_started_at is None:
        raise _ScheduledAudioLeaseLost(
            f"Claim audio absent pour la séance {schedule_session_id}"
        )
    if ownership_state and ownership_state.get("error"):
        raise _ScheduledAudioLeaseLost(str(ownership_state["error"]))

    try:
        from datetime import datetime
        from config import FRANCE_TZ
        from repositories.course_schedule_repository import (
            touch_audio_generation_session,
        )

        owned = touch_audio_generation_session(
            int(schedule_session_id),
            updated_at=datetime.now(FRANCE_TZ),
            expected_started_at=schedule_claim_started_at,
        )
    except _ScheduledAudioLeaseLost:
        raise
    except Exception as exc:
        message = (
            f"Impossible de confirmer le lock audio de la séance "
            f"{schedule_session_id}: {exc}"
        )
        if ownership_state is not None:
            ownership_state["error"] = message
        raise _ScheduledAudioLeaseLost(message) from exc

    if not owned:
        message = (
            f"Lock audio perdu pour la séance {schedule_session_id}: "
            "le claim a été remplacé ou finalisé"
        )
        if ownership_state is not None:
            ownership_state["error"] = message
        raise _ScheduledAudioLeaseLost(message)


def _make_audio_progress_logger(
    job_id: int,
    folder_id: int,
    voice_type: str,
    schedule_session_id: int | None = None,
    schedule_claim_started_at=None,
    ownership_state: dict | None = None,
):
    """Callback branché sur generate_audio_from_script pour sortir de la boîte noire."""
    last_session_touch = {"at": 0.0}

    def _on_progress(step, total, message):
        try:
            from services.formation_observability_service import log_pipeline_event
            log_pipeline_event(
                job_id,
                "audio_progress",
                step="audio",
                status="running",
                folder_id=folder_id,
                message=message,
                data={
                    "step": step,
                    "total": total,
                    "voice_type": voice_type,
                    "tts_engine": "edge-tts" if voice_type == "gtts" else voice_type,
                },
            )
        except Exception:
            pass
        if schedule_session_id:
            if ownership_state and ownership_state.get("error"):
                raise _ScheduledAudioLeaseLost(str(ownership_state["error"]))
            now = time.time()
            if now - last_session_touch["at"] >= 60:
                last_session_touch["at"] = now
                _assert_scheduled_audio_ownership(
                    int(schedule_session_id),
                    schedule_claim_started_at,
                    ownership_state=ownership_state,
                )
    return _on_progress


def _finalize_audio_ready_state(job_id: int, voice_type: str) -> dict:
    """Marque la plateforme exploitable et garantit le module persistant.

    Idempotent : utilisé après une relance audio manuelle, notamment
    `continue_after_text`, où les MP3 sont déjà produits mais la finalisation
    historique de `launch_audio` n'était pas rejouée.
    """
    from repositories.pipeline_repository import finalize_pipeline_module

    job = get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} introuvable pour finalisation audio")
    import json
    from services.canonical_teacher_service import (
        build_canonical_teacher_signature,
        canonical_teacher_fingerprint,
    )

    canonical_signature = build_canonical_teacher_signature(
        rncp_code=job.get("rncp_code") or "",
        tp_name=job.get("tp_name") or f"Job {job_id}",
        total_hours=int(job.get("total_hours") or 0),
        nb_days=int(job.get("nb_days") or 1),
        voice_type=voice_type,
    )
    canonical_fingerprint = canonical_teacher_fingerprint(canonical_signature)
    # Create or reload the draft envelope first. Canonical assets need the
    # durable module namespace, but the module must remain non-reusable until
    # the exact audio manifest has been snapshotted and verified.
    draft_result = finalize_pipeline_module(
        formation_job_id=job_id,
        platform_id=int(job["platform_id"]),
        rncp_code=job.get("rncp_code") or "",
        tp_name=job.get("tp_name") or f"Job {job_id}",
        audio_ready=False,
    )
    manifest = None
    if (
        (
            draft_result.get("canonical_reuse_candidate")
            or draft_result.get("canonical_reuse_allowed")
        )
        and draft_result.get("center_account_id") is not None
    ):
        from services.formation_pipeline_service import get_expected_course_folders
        from services.teacher_asset_service import ensure_module_asset_manifest

        folder_ids = get_expected_course_folders(job_id).get("folder_ids") or []
        manifest = ensure_module_asset_manifest(
            module_id=int(draft_result["module_id"]),
            center_account_id=int(draft_result["center_account_id"]),
            source_platform_id=int(job["platform_id"]),
            source_folder_ids=folder_ids,
            force=True,
        )
        if not manifest.get("audio_ready"):
            raise RuntimeError(
                "Le professeur IA ne peut pas être finalisé : "
                f"manifeste audio incomplet ({manifest.get('audio_asset_count', 0)} fichier(s), "
                f"{manifest.get('required_folder_count', 0)} jour(s) attendu(s))"
            )

    result = finalize_pipeline_module(
        formation_job_id=job_id,
        platform_id=int(job["platform_id"]),
        rncp_code=job.get("rncp_code") or "",
        tp_name=job.get("tp_name") or f"Job {job_id}",
        audio_ready=True,
        voice_type=voice_type,
        canonical_fingerprint=canonical_fingerprint,
        canonical_signature_json=json.dumps(
            canonical_signature,
            ensure_ascii=False,
            sort_keys=True,
        ),
        canonical_generator_version=canonical_signature["generator_version"],
    )
    if manifest is not None:
        result["asset_manifest"] = manifest
    logger.info(
        "PIPELINE_AUDIO_FINALIZED formation_job_id=%s platform_id=%s "
        "module_id=%s module_created=%s voice_type=%s ready_updated=%s",
        job_id,
        result["platform_id"],
        result["module_id"],
        result["module_created"],
        voice_type,
        result["platform_ready_updated"],
    )
    return result


def _finalize_text_ready_state(job_id: int) -> dict:
    """Rend la plateforme consultable dès que les textes sont prêts.

    L'audio est désormais lancé séparément. Donc la fin de la pipeline texte
    doit déjà enlever l'overlay "Module en construction" et créer l'enveloppe
    module qui pointe vers les dossiers de cours, sans marquer le module comme
    validé audio.
    """
    from repositories.pipeline_repository import finalize_pipeline_module

    job = get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} introuvable pour finalisation texte")
    result = finalize_pipeline_module(
        formation_job_id=job_id,
        platform_id=int(job["platform_id"]),
        rncp_code=job.get("rncp_code") or "",
        tp_name=job.get("tp_name") or f"Job {job_id}",
        audio_ready=False,
    )
    if (
        int(job.get("schedule_schema_version") or 1) == 2
        and result.get("center_account_id") is not None
    ):
        snapshot = job.get("schedule_snapshot_json") or {}
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        days = snapshot.get("days") if isinstance(snapshot, dict) else None
        if not days:
            raise RuntimeError(
                "Le module V2 ne peut pas être finalisé sans journées verrouillées"
            )
        from repositories.day_schedule_repository import (
            bind_module_days_to_platform,
            create_module_day_snapshots,
        )
        from services.formation_pipeline_service import (
            get_expected_course_folders,
        )

        module_days = create_module_day_snapshots(
            int(result["center_account_id"]),
            int(result["module_id"]),
            days,
            schedule_schema_version=2,
        )
        folder_ids = (
            get_expected_course_folders(int(job_id)).get("folder_ids")
            or []
        )
        bindings = bind_module_days_to_platform(
            int(result["center_account_id"]),
            int(result["module_id"]),
            int(result["platform_id"]),
            folder_ids,
        )
        result["module_days"] = len(module_days)
        result["module_day_bindings"] = bindings
    logger.info(
        "PIPELINE_TEXT_FINALIZED formation_job_id=%s platform_id=%s "
        "module_id=%s module_created=%s status=%s ready_updated=%s",
        job_id,
        result["platform_id"],
        result["module_id"],
        result["module_created"],
        result["module_status"],
        result["platform_ready_updated"],
    )
    return result


def _persist_daily_teacher_audio_assets(job_id: int, folder_id: int) -> dict:
    """Snapshot one J-1 playlist as soon as that training day is complete."""
    from repositories.pipeline_repository import get_formation_module_for_pipeline_job
    from services.teacher_asset_service import ensure_module_asset_manifest

    module = get_formation_module_for_pipeline_job(int(job_id))
    if not module or module.get("center_account_id") is None:
        return {"persisted": False, "reason": "module_centre_absent"}
    source_platform_id = int(module.get("source_platform_id") or 0)
    if source_platform_id <= 0:
        raise RuntimeError("Plateforme source absente du professeur IA durable")
    manifest = ensure_module_asset_manifest(
        module_id=int(module["id"]),
        center_account_id=int(module["center_account_id"]),
        source_platform_id=source_platform_id,
        source_folder_ids=[int(folder_id)],
        force=True,
    )
    return {"persisted": True, **manifest}


def _finalize_scheduled_audio_module_if_ready(
    job_id: int,
    voice_type: str,
    *,
    completing_session_id: int | None = None,
) -> dict:
    """Promote the durable teacher only after every scheduled day is ready."""
    from repositories.course_schedule_repository import (
        get_scheduled_audio_completion_readiness,
    )

    job = get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} introuvable pour finalisation planifiée")
    readiness = get_scheduled_audio_completion_readiness(
        int(job["platform_id"]),
        int(job_id),
        required_session_count=int(job.get("nb_days") or 1),
        completing_session_id=completing_session_id,
    )
    if not readiness["ready"]:
        return {**readiness, "finalized": False, "finalize_result": None}

    finalize_result = _finalize_audio_ready_state(job_id, voice_type)
    update_job(job_id, status="audio_completed", error_message=None)
    return {
        **readiness,
        "finalized": True,
        "finalize_result": finalize_result,
    }


def _count_dirty_segments_for_job(job_id: int) -> int:
    from repositories.pipeline_repository import count_dirty_completed_segments_for_folders
    from services.formation_pipeline_service import get_expected_course_folders

    folder_ids = get_expected_course_folders(job_id).get("folder_ids") or []
    if not folder_ids:
        return 0
    return count_dirty_completed_segments_for_folders(folder_ids)


def _folder_text_reviews_ready(job_id: int, folder_id: int) -> tuple[bool, dict]:
    from repositories.pipeline_repository import get_folder_text_review_readiness
    from services.content_generation_service import (
        _current_compliance_review_signature,
    )

    compliance_signature = _current_compliance_review_signature()
    detail = get_folder_text_review_readiness(
        job_id=job_id,
        folder_id=folder_id,
        review_signature=compliance_signature,
    )
    total = int(detail.get("segments_completed") or 0)
    return total > 0 and detail["reviewed_current"] >= total, detail


def start_folder_audio_generation(
    job_id,
    folder_id,
    payload=None,
    *,
    schedule_session_id=None,
    target_platform_id=None,
    trigger_source="manual",
    stale_started_before=None,
    wait_for_completion=False,
):
    """Lance l'audio d'une seule journée.

    Utilisé par le bouton manuel d'une journée et par le timer 48h avant cours.
    Retourne (payload, http_status) pour rester réutilisable hors route Flask.
    """
    job = get_job(job_id)
    if not job:
        return {"error": "Job introuvable"}, 404

    publish_platform_id = int(target_platform_id or job["platform_id"])

    try:
        folder_id, folder_resolution = _resolve_continue_after_text_folder(job_id, int(folder_id))
    except ValueError as e:
        return {"error": str(e)}, 400

    data = payload or {}
    reviews_ready, review_detail = _folder_text_reviews_ready(job_id, folder_id)
    if not reviews_ready and not bool(data.get("allow_unreviewed")):
        return {
            "error": "Texte pas prêt pour l'audio : la conformité locale par morceau doit être terminée.",
            "review_detail": review_detail,
        }, 400

    tts_mode = (data.get("tts_mode") or job.get("auto_pilot_tts_mode") or "gtts").lower()
    if tts_mode not in ("fish_audio", "gtts", "mock"):
        return {"error": "tts_mode invalide (fish_audio | gtts | mock)"}, 400
    mock = tts_mode == "mock"
    basic_tts = tts_mode == "gtts"
    voice_type = "mock" if mock else ("gtts" if basic_tts else "fish_audio")
    force_all = bool(data.get("force_all", True))
    sync_slides = bool(data.get("sync_slides", True))
    auto_generate_slides = bool(data.get("auto_generate_slides", True))
    preserve_existing = bool(data.get("preserve_existing", False))
    max_slides = int(data.get("max_slides") or 60)
    pace = data.get("pace") or "normal"
    model = _resolve_pipeline_api_model(job, data.get("model"))

    from services.formation_pipeline_service import get_expected_course_folders
    folder_ids = get_expected_course_folders(job_id).get("folder_ids") or []
    if folder_id not in folder_ids:
        return {"error": "Folder hors journées attendues"}, 400
    idx = folder_ids.index(folder_id)
    next_folder_id = folder_ids[idx + 1] if idx + 1 < len(folder_ids) else None
    reuse_existing_assets = False
    if publish_platform_id != int(job["platform_id"]):
        try:
            from repositories.teacher_asset_repository import (
                get_module_audio_manifest_readiness,
                resolve_folder_asset_origin,
            )

            asset_origin = resolve_folder_asset_origin(int(folder_id)) or {}
            module_id = int(asset_origin.get("module_id") or 0)
            reuse_existing_assets = bool(
                module_id
                and get_module_audio_manifest_readiness(module_id).get("ready")
            )
        except Exception:
            logger.warning(
                "PIPELINE_REUSE_ASSET_CHECK_FAILED job=%s folder=%s target_platform=%s",
                job_id,
                folder_id,
                publish_platform_id,
                exc_info=True,
            )

    from datetime import datetime
    from config import FRANCE_TZ
    from services.content_generation_service import generate_audio_from_script

    schedule_claim_started_at = None
    scheduled_capacity_acquired = False
    if schedule_session_id:
        if not _try_acquire_scheduled_audio_capacity():
            return {
                "error": "Capacité audio planifiée saturée; la séance restera due pour le prochain tick",
                "code": "scheduled_audio_backpressure",
            }, 429
        scheduled_capacity_acquired = True
        try:
            from repositories.course_schedule_repository import (
                claim_audio_generation_session,
            )

            schedule_claim_started_at = datetime.now(FRANCE_TZ)
            claimed = claim_audio_generation_session(
                session_id=int(schedule_session_id),
                job_id=int(job_id),
                folder_id=int(folder_id),
                started_at=schedule_claim_started_at,
                stale_started_before=stale_started_before,
            )
            if not claimed:
                _release_scheduled_audio_capacity()
                return {"error": "Audio déjà lancé ou terminé pour cette séance"}, 409
        except Exception as exc:
            _release_scheduled_audio_capacity()
            logger.warning("⚠️ Impossible de marquer la séance audio running", exc_info=True)
            return {"error": f"Impossible de verrouiller la séance audio: {str(exc)[:200]}"}, 500

    def _run_one():
        started_at = time.time()
        outcome = {"success": False, "error": None}
        ownership_state = {"error": None}
        heartbeat_stop = threading.Event()
        heartbeat = None

        if schedule_session_id:
            try:
                heartbeat_seconds = max(
                    5.0,
                    float(os.getenv("SCHEDULED_AUDIO_HEARTBEAT_SECONDS", "30") or "30"),
                )
            except (TypeError, ValueError):
                heartbeat_seconds = 30.0

            def _scheduled_audio_heartbeat():
                while not heartbeat_stop.wait(heartbeat_seconds):
                    try:
                        _assert_scheduled_audio_ownership(
                            int(schedule_session_id),
                            schedule_claim_started_at,
                            ownership_state=ownership_state,
                        )
                    except _ScheduledAudioLeaseLost as exc:
                        ownership_state["error"] = str(exc)
                        logger.error(
                            "PIPELINE_SCHEDULED_AUDIO_LOCK_LOST session=%s job=%s folder=%s error=%s",
                            schedule_session_id,
                            job_id,
                            folder_id,
                            exc,
                        )
                        # Native Python threads cannot safely be killed. The
                        # progress callback and every publish/finalize boundary
                        # re-check this state and fail closed when the provider
                        # call returns.
                        return

            # This heartbeat is independent from progress callbacks. Some TTS
            # and slide-provider calls can remain silent for several minutes.
            heartbeat = threading.Thread(
                target=_scheduled_audio_heartbeat,
                name=f"scheduled-audio-heartbeat-{schedule_session_id}",
                daemon=True,
            )
            heartbeat.start()

        try:
            from services.formation_observability_service import log_pipeline_event
            if not reuse_existing_assets:
                update_job(job_id, status="audio_running", error_message=None)
            log_pipeline_event(
                job_id,
                "audio_folder_started",
                step="audio",
                status="running",
                folder_id=folder_id,
                model=str(model) if model else None,
                message="Synthèse audio journée démarrée",
                data={
                    "voice_type": voice_type,
                    "force_all": force_all,
                    "preserve_existing": preserve_existing,
                    "sync_slides": sync_slides,
                    "auto_generate_slides": auto_generate_slides,
                    "single_folder": True,
                    "trigger_source": trigger_source,
                    "schedule_session_id": schedule_session_id,
                    "reuse_existing_assets": reuse_existing_assets,
                },
            )
            if reuse_existing_assets:
                result_audio = {
                    "generated": 0,
                    "skipped": True,
                    "reused_durable_assets": True,
                }
            else:
                result_audio = generate_audio_from_script(
                    folder_id,
                    on_progress=_make_audio_progress_logger(
                        job_id,
                        folder_id,
                        voice_type,
                        schedule_session_id=schedule_session_id,
                        schedule_claim_started_at=schedule_claim_started_at,
                        ownership_state=ownership_state,
                    ),
                    force_all=force_all,
                    mock=mock,
                    basic_tts=basic_tts,
                    next_folder_id=next_folder_id,
                    is_last_folder=next_folder_id is None,
                    sync_slides=sync_slides,
                    auto_generate_slides=auto_generate_slides,
                    slide_max_slides=max_slides,
                    slide_pace=pace,
                    slide_model=model,
                    llm_model=model,
                    preserve_existing=preserve_existing,
                )
            # Generation may have taken minutes. Re-fence immediately before
            # publishing anything to the learner-visible namespace.
            _assert_scheduled_audio_ownership(
                schedule_session_id,
                schedule_claim_started_at,
                ownership_state=ownership_state,
            )
            publish_result = None
            try:
                from services.audio_publish_service import publish_playlist_audio_to_platform
                from services.day_playlist_service import required_audio_filenames

                required_files = required_audio_filenames(int(folder_id))
                publish_result = publish_playlist_audio_to_platform(
                    publish_platform_id,
                    folder_id,
                    filenames=required_files,
                    source_platform_id=int(job["platform_id"]),
                    archive_existing=True,
                    archive_reason=f"{trigger_source}-folder-{folder_id}",
                    destination_prefix=(
                        f"course-sessions/{int(schedule_session_id)}"
                        if schedule_session_id
                        else None
                    ),
                    create_playback_manifest=bool(schedule_session_id),
                )
                publish_errors = publish_result.get("publish_errors") or []
                published_files = publish_result.get("published") or []
                missing_files = sorted(required_files - set(published_files))
                if publish_errors or missing_files:
                    raise RuntimeError(
                        "Publication audio incomplète: "
                        f"{len(published_files)} fichier(s) publié(s), "
                        f"{len(publish_errors)} erreur(s), "
                        f"{len(missing_files)} fichier(s) requis manquant(s)"
                    )
            except Exception as publish_error:
                publish_result = {"published": [], "publish_errors": [{"error": str(publish_error)}]}
                logger.error(
                    "❌ Publication audio journée échouée job=%s platform=%s folder=%s: %s",
                    job_id,
                    publish_platform_id,
                    folder_id,
                    publish_error,
                    exc_info=True,
                )
                raise RuntimeError(
                    "Publication des audios vers la plateforme apprenant échouée: "
                    f"{str(publish_error)[:300]}"
                ) from publish_error
            # Publication itself can be long. A stale worker must not mark the
            # session or pipeline successful after a successor took over.
            _assert_scheduled_audio_ownership(
                schedule_session_id,
                schedule_claim_started_at,
                ownership_state=ownership_state,
            )
            n_dirty = _count_dirty_segments_for_job(job_id)
            finalize_result = None
            scheduled_readiness = None
            daily_asset_manifest = None
            if schedule_session_id:
                from repositories.course_schedule_repository import (
                    complete_audio_generation_session,
                )

                # Treat the currently owned/published occurrence as complete
                # for readiness. If durable module promotion fails, the claim
                # remains fail-able and the normal retry path can repair it.
                _assert_scheduled_audio_ownership(
                    int(schedule_session_id),
                    schedule_claim_started_at,
                    ownership_state=ownership_state,
                )
                # The day's immutable manifest becomes durable before the occurrence
                # can be marked complete. A storage/manifest failure therefore
                # follows the normal retry path without regenerating valid MP3.
                if reuse_existing_assets:
                    daily_asset_manifest = {
                        "persisted": False,
                        "reused_durable_assets": True,
                    }
                    scheduled_readiness = {
                        "ready": True,
                        "finalized": False,
                        "reused_durable_assets": True,
                    }
                else:
                    daily_asset_manifest = _persist_daily_teacher_audio_assets(
                        int(job_id),
                        int(folder_id),
                    )
                    scheduled_readiness = _finalize_scheduled_audio_module_if_ready(
                        int(job_id),
                        voice_type,
                        completing_session_id=int(schedule_session_id),
                    )
                # Re-fence immediately after the idempotent promotion and next
                # to the guarded completion write.
                _assert_scheduled_audio_ownership(
                    int(schedule_session_id),
                    schedule_claim_started_at,
                    ownership_state=ownership_state,
                )
                completed = complete_audio_generation_session(
                    int(schedule_session_id),
                    completed_at=datetime.now(FRANCE_TZ),
                    expected_started_at=schedule_claim_started_at,
                )
                if not completed:
                    raise _ScheduledAudioLeaseLost(
                        f"Finalisation refusée: lock audio perdu pour la séance {schedule_session_id}"
                    )
                heartbeat_stop.set()
            if (
                not reuse_existing_assets
                and (
                    not scheduled_readiness
                    or not scheduled_readiness.get("finalized")
                )
            ):
                update_job(job_id, status="text_ready", error_message=None)
            log_pipeline_event(
                job_id,
                "audio_folder_completed",
                step="audio",
                status="completed",
                folder_id=folder_id,
                model=str(model) if model else None,
                duration_ms=int((time.time() - started_at) * 1000),
                message="Synthèse audio journée terminée",
                data={
                    "voice_type": voice_type,
                    "remaining_dirty_segments": n_dirty,
                    "finalized": bool(scheduled_readiness and scheduled_readiness.get("finalized")),
                    "finalize_result": (
                        scheduled_readiness.get("finalize_result")
                        if scheduled_readiness
                        else finalize_result
                    ),
                    "scheduled_readiness": scheduled_readiness,
                    "daily_asset_manifest": daily_asset_manifest,
                    "generated": result_audio.get("generated") if isinstance(result_audio, dict) else None,
                    "skipped": result_audio.get("skipped") if isinstance(result_audio, dict) else None,
                    "publish": publish_result,
                    "single_folder": True,
                    "trigger_source": trigger_source,
                    "schedule_session_id": schedule_session_id,
                },
            )
            outcome["success"] = True
        except Exception as e:
            outcome["error"] = str(e)[:500]
            lease_lost = isinstance(e, _ScheduledAudioLeaseLost)
            if not lease_lost:
                update_job(job_id, status="text_ready", error_message=f"audio folder {folder_id}: {str(e)[:500]}")
                try:
                    from services.formation_observability_service import log_pipeline_event
                    log_pipeline_event(
                        job_id,
                        "audio_folder_failed",
                        step="audio",
                        status="error",
                        folder_id=folder_id,
                        model=str(model) if model else None,
                        duration_ms=int((time.time() - started_at) * 1000),
                        message="Synthèse audio journée échouée",
                        data={
                            "voice_type": voice_type,
                            "trigger_source": trigger_source,
                            "schedule_session_id": schedule_session_id,
                        },
                        error=str(e)[:500],
                    )
                except Exception:
                    pass
            if schedule_session_id:
                try:
                    from repositories.course_schedule_repository import (
                        fail_audio_generation_session,
                    )

                    fail_audio_generation_session(
                        int(schedule_session_id),
                        error=str(e),
                        failed_at=datetime.now(FRANCE_TZ),
                        expected_started_at=schedule_claim_started_at,
                    )
                except Exception:
                    logger.warning("⚠️ Impossible de marquer la séance audio error", exc_info=True)
            logger.error("❌ Audio folder job=%s folder=%s : %s", job_id, folder_id, e, exc_info=True)
        finally:
            heartbeat_stop.set()
            if heartbeat is not None:
                heartbeat.join(timeout=1.0)
            if scheduled_capacity_acquired:
                _release_scheduled_audio_capacity()
        return outcome

    run_outcome = None
    if wait_for_completion:
        run_outcome = _run_one()
    else:
        try:
            _spawn_audio_background_task(
                _run_one,
                use_native_thread=bool(schedule_session_id),
                name=(
                    f"scheduled-audio-{schedule_session_id}"
                    if schedule_session_id
                    else f"manual-audio-{job_id}-{folder_id}"
                ),
            )
        except Exception:
            if scheduled_capacity_acquired:
                _release_scheduled_audio_capacity()
            raise

    response = {
        "message": "Synthèse audio lancée pour cette journée",
        "job_id": job_id,
        "folder_id": folder_id,
        "resolved_folder_id": folder_id,
        "folder_resolution": folder_resolution,
        "next_folder_id": next_folder_id,
        "tts_mode": tts_mode,
        "voice_type": voice_type,
        "status": "audio_running",
        "schedule_session_id": schedule_session_id,
        "target_platform_id": publish_platform_id,
        "trigger_source": trigger_source,
    }
    if run_outcome is not None:
        response["waited_for_completion"] = True
        if run_outcome["success"]:
            response["message"] = "Synthèse audio terminée pour cette journée"
            response["status"] = "audio_completed"
            return response, 200
        response["error"] = run_outcome["error"] or "La synthèse audio a échoué"
        response["status"] = "audio_error"
        return response, 500
    return response, 202


@formation_bp.route("/api/formation/<int:job_id>/content/<int:folder_id>/generate-audio", methods=["POST"])
def generate_folder_audio(job_id, folder_id):
    """Ancienne commande manuelle conservée comme tombstone HTTP 410."""
    return _retired_manual_pipeline_response("generate_folder_audio")


@formation_bp.route("/api/formation/<int:job_id>/launch-audio", methods=["POST"])
def launch_audio(job_id):
    """Ancienne commande manuelle conservée comme tombstone HTTP 410."""
    return _retired_manual_pipeline_response("launch_audio")


def _completed_text_folder_candidates(job_id: int) -> list[dict]:
    """Liste les dossiers rattachés au job qui ont vraiment un texte complet."""
    from repositories.pipeline_repository import list_text_folder_states_for_folders
    from services.formation_pipeline_service import get_expected_course_folders

    folder_ids = get_expected_course_folders(job_id).get("folder_ids") or []
    if not folder_ids:
        return []
    return list_text_folder_states_for_folders(folder_ids, completed_only=True)


def _requested_text_folder_state(job_id: int, folder_id: int) -> dict | None:
    """Retourne l'état texte du folder demandé, même s'il n'est pas completed."""
    from repositories.pipeline_repository import get_text_folder_state

    return get_text_folder_state(folder_id)


def _claim_single_completed_orphan_folder(job_id: int, requested: dict | None) -> dict | None:
    """Rattache un unique folder completed orphelin quand l'ancien lien est cassé."""
    from repositories.pipeline_repository import claim_single_completed_orphan_folder

    job = get_job(job_id)
    if not job:
        return None
    day_number = None
    if requested and requested.get("folder_name"):
        import re

        match = re.match(r"^\s*Jour\s+(\d+)\b", requested["folder_name"], flags=re.IGNORECASE)
        if match:
            day_number = int(match.group(1))
    row = claim_single_completed_orphan_folder(
        formation_job_id=job_id,
        platform_id=int(job["platform_id"]),
        day_number=day_number,
    )
    if not row:
        return None
    logger.warning(
        "PIPELINE_FOLDER_REPAIR job=%s repaired=1 missing=0 folders=%s reason=continue_after_text_orphan",
        job_id,
        [{"folder_id": row["folder_id"], "name": row["folder_name"]}],
    )
    return row


def _resolve_continue_after_text_folder(job_id: int, requested_folder_id: int) -> tuple[int, dict | None]:
    """Valide le folder de relance aval et corrige les anciens liens cassés."""
    try:
        from services.formation_pipeline_service import repair_orphan_content_folders
        repair_orphan_content_folders(job_id)
    except Exception as e:
        logger.warning(f"⚠️ Réparation folders avant relance aval job {job_id} ignorée : {e}")

    requested = _requested_text_folder_state(job_id, requested_folder_id)
    if (
        requested
        and requested.get("formation_job_id") == job_id
        and requested.get("content_status") == "completed"
        and (requested.get("segments_completed") or 0) > 0
    ):
        return requested_folder_id, None

    candidates = _completed_text_folder_candidates(job_id)
    if requested and requested.get("position") is not None:
        same_position = [c for c in candidates if c.get("position") == requested.get("position")]
        if len(same_position) == 1:
            resolved = same_position[0]
            return int(resolved["folder_id"]), {
                "requested_folder_id": requested_folder_id,
                "resolved_folder_id": resolved["folder_id"],
                "reason": "same_position_completed_folder",
                "requested_state": requested,
            }
    if len(candidates) == 1:
        resolved = candidates[0]
        return int(resolved["folder_id"]), {
            "requested_folder_id": requested_folder_id,
            "resolved_folder_id": resolved["folder_id"],
            "reason": "single_completed_folder_for_job",
            "requested_state": requested,
        }

    orphan = _claim_single_completed_orphan_folder(job_id, requested)
    if orphan:
        return int(orphan["folder_id"]), {
            "requested_folder_id": requested_folder_id,
            "resolved_folder_id": orphan["folder_id"],
            "reason": "single_completed_orphan_folder_claimed",
            "requested_state": requested,
        }

    available = [
        f"folder {c['folder_id']} ({c['segments_completed']} segments, {c['total_words']} mots)"
        for c in candidates
    ]
    requested_detail = (
        "introuvable"
        if not requested
        else (
            f"status={requested.get('content_status') or 'aucun content_job'}, "
            f"segments={requested.get('segments_completed') or 0}, "
            f"formation_job_id={requested.get('formation_job_id')}"
        )
    )
    raise ValueError(
        f"Folder {requested_folder_id} non prêt pour relance aval ({requested_detail}). "
        + (
            "Folder(s) texte completed disponible(s) : " + "; ".join(available)
            if available
            else "Aucun folder texte completed disponible pour ce job."
        )
    )


def _delete_slide_deck_for_resume(folder_id: int, content_job_id: int) -> int:
    """Supprime le deck slides existant pour forcer la régénération à l'étape suivante."""
    from repositories.pipeline_repository import delete_script_slide_decks_for_content_job

    return delete_script_slide_decks_for_content_job(folder_id, content_job_id)


@formation_bp.route(
    "/api/formation/<int:job_id>/content/<int:folder_id>/continue-after-text",
    methods=["POST"],
)
def continue_after_text(job_id, folder_id):
    """Ancienne relance partielle, remplacée par la reprise durable globale."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403
    return jsonify({
        "error": (
            "Cette relance partielle a été retirée. "
            "Utilisez la reprise globale de la pipeline."
        ),
        "code": "durable_pipeline_resume_required",
    }), 410


# ─── Liste des jobs ───────────────────────────────────────────────────────────

@formation_bp.route("/api/formation/list", methods=["GET"])
def list_formations():
    """Liste les jobs visibles par le compte admin courant."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    from repositories.pipeline_repository import list_pipeline_jobs

    center_account_id = _training_center_account_id()
    if center_account_id is None:
        return _pipeline_job_not_found()
    jobs = list_pipeline_jobs(center_account_id=center_account_id)
    return jsonify({"jobs": jobs})


# ─── Pipeline automatique — orchestration durable unique ─────────────────────
#
# Chaque work-item exécute une seule étape, sauvegarde l'état en PostgreSQL,
# puis crée atomiquement le work-item suivant. Les leases de la file durable
# assurent à eux seuls heartbeat, fencing, reprise après crash et retries.


def _dispatch_auto_pilot_tick(
    job_id: int,
    *,
    reason: str,
    force_new_run: bool = False,
    chain_payload: dict | None = None,
) -> dict:
    """Place one resumable pipeline step in the durable queue."""
    from services.pipeline_queue import enqueue_work_item, get_latest_work_item

    latest = get_latest_work_item(job_id)
    if latest and not latest.terminal and not force_new_run:
        return {
            "mode": "queue",
            "work_item_id": latest.id,
            "run_id": latest.run_id,
            "deduplicated": True,
            "queue_status": latest.status,
        }

    step = _determine_next_ap_step(job_id)
    run_id = uuid.uuid4().hex
    try:
        max_attempts = int(os.getenv("PIPELINE_WORK_MAX_ATTEMPTS", "5"))
    except (TypeError, ValueError):
        max_attempts = 5
    max_attempts = max(1, min(20, max_attempts))
    item = enqueue_work_item(
        pipeline_job_id=job_id,
        task_type="auto_pilot_tick",
        scope_key="pipeline",
        run_id=run_id,
        dedupe_key=f"job:{job_id}:run:{run_id}:step:{step or 'done'}",
        payload={
            **dict(chain_payload or {}),
            "expected_step": step,
            "dispatch_reason": reason,
        },
        max_attempts=max_attempts,
    )
    return {
        "mode": "queue",
        "work_item_id": item.id,
        "run_id": item.run_id,
        "deduplicated": False,
        "queue_status": item.status,
    }


def _queue_status_for_job(job_id: int) -> dict:
    try:
        from services.pipeline_queue import get_latest_work_item

        item = get_latest_work_item(job_id)
        if not item:
            return {"mode": "queue", "status": "missing"}
        return {
            "mode": "queue",
            "status": item.status,
            "work_item_id": item.id,
            "run_id": item.run_id,
            "attempt": item.attempt_count,
            "max_attempts": item.max_attempts,
            "last_error": item.last_error,
        }
    except Exception as exc:
        logger.warning("PIPELINE_QUEUE_STATUS_FAILED job=%s", job_id, exc_info=True)
        return {"mode": "queue", "status": "unavailable", "error": str(exc)[:300]}


def _pipeline_error_fallback_status(job: dict) -> str:
    """Return the last stable product status without mutating the pipeline."""
    if job.get("daily_programs_validated"):
        return "daily_validated"
    if job.get("global_program_validated"):
        return "global_validated"
    if job.get("global_program"):
        return "global_ready"
    if job.get("reac_text"):
        return "reac_ready"
    return "init"


def _determine_next_ap_step(job_id: int) -> str | None:
    """Read-only calculation of the next durable step. None means completed."""
    import json as _json
    j = get_job(job_id)
    if not j:
        return None

    # 1. REAC
    if not j.get("reac_text"):
        return "reac"

    # 2. KB
    kb_done = bool(j.get("global_program")) or j.get("status") in (
        "kb_ready", "global_ready", "global_validated", "daily_ready",
        "daily_validated", "text_ready", "tts_launched", "audio_running",
        "audio_completed", "audio_launched",
    )
    if not kb_done:
        try:
            from services.knowledge_base_service import kb_stats as _kb_stats
            stats = _kb_stats(job_id)
            kb_done = (
                int(stats.get("total") or 0) > 0
                and int(stats.get("completed") or 0) == int(stats.get("total") or 0)
            )
        except Exception:
            pass
    if not kb_done:
        return "kb"

    # 3. Programme global
    if not j.get("global_program"):
        return "global"

    # 4. Programmes journée
    if (
        not j.get("daily_programs_validated")
        or not daily_programs_are_complete(j)
    ):
        return "daily"

    # 5. Génération contenu.
    # Ancien garde-fou : comparer les segments terminés à `sub_parts × 3`.
    # Ce n'est plus fiable depuis la génération structurée : un dossier peut être
    # complet avec un nombre de segments différent de l'ancien pipeline 3 passes.
    # La source de vérité devient donc le job contenu par dossier :
    # tous les dossiers attendus doivent exister, avoir un content job `completed`
    # et contenir au moins un segment finalisé.
    from services.formation_pipeline_service import get_expected_course_folders
    folder_state = get_expected_course_folders(job_id)
    folder_ids = folder_state.get("folder_ids") or []
    expected_folder_count = int(j.get("nb_days") or 0)
    if len(folder_ids) < expected_folder_count:
        return "content"
    from repositories.pipeline_repository import (
        count_dirty_completed_segments_for_folders,
        count_segments_pending_review_for_folders,
        get_latest_script_slide_deck_row,
        list_completed_content_jobs_for_folders,
        list_content_completion_rows_for_folders,
    )
    content_rows = list_content_completion_rows_for_folders(folder_ids)
    completed_folder_ids = {
        row["folder_id"]
        for row in content_rows
        if row.get("status") == "completed"
        and (int(row.get("total_words") or 0) > 0 or int(row.get("completed_segments") or 0) > 0)
    }
    if len(completed_folder_ids) < len(folder_ids):
        return "content"

    # Volume safety append-only retirée du flux auto-pilot : elle ajoutait parfois
    # du développement après les conclusions/Q-R. Le rattrapage de volume se fait
    # désormais dans le calibrage budget texte, avec le plan verrouillé comme contexte.

    from services.content_generation_service import _current_compliance_review_signature
    compliance_signature = _current_compliance_review_signature()

    # 6. Conformité locale par segment, après adhérence au plan, calibrage
    # budget et micro-review éthique intégrés à la génération structurée.
    not_reviewed = count_segments_pending_review_for_folders(folder_ids, compliance_signature)
    if not_reviewed > 0:
        return "review"

    # 7. Document post-révision : ré-assemble le texte courant validé avant
    # d'autoriser slides et synthèse audio.
    if not j.get("auto_pilot_post_review_docs_done"):
        return "post_review_docs"

    # 8. Slides anchor-first : elles sont générées explicitement avant la fin
    # texte, pour ne plus rester cachées dans l'étape TTS synchronisée.
    slide_rows = list_completed_content_jobs_for_folders(folder_ids)
    missing_slide_decks = []
    from services.script_slide_generation_service import is_script_slide_deck_usable
    for row in slide_rows:
        fid = int(row["folder_id"])
        deck_row = get_latest_script_slide_deck_row(
            folder_id=fid,
            content_job_id=int(row["content_job_id"]),
        )
        deck_is_usable = False
        if deck_row:
            try:
                deck_is_usable = is_script_slide_deck_usable({
                    "slides": _json.loads(deck_row.get("slides_json") or "[]"),
                    "pipeline_debug": _json.loads(
                        deck_row.get("pipeline_debug_json") or "{}"
                    ),
                })
            except Exception:
                deck_is_usable = False
        if not deck_is_usable:
            missing_slide_decks.append(fid)
    if missing_slide_decks:
        return "slides"

    # 10. Audio TTS optionnel. Par défaut l'auto-pilot s'arrête texte prêt :
    # les audios se génèrent ensuite à la demande, journée/semaine par journée/semaine.
    bulk_audio_enabled = bool(
        j.get("auto_pilot_generate_audio") and _legacy_bulk_audio_enabled()
    )
    if not bulk_audio_enabled:
        # Finalization is a real durable step. Merely asking for status must
        # never expose the platform or create its module envelope.
        return None if j.get("status") == "text_ready" else "finalize_text"

    # Si l'audio auto est explicitement demandé, on vérifie via dirty=0 sur tous les segments (pas le status qui
    # est positionné au début du loop audio, donc non fiable en cas de restart)
    dirty_count = count_dirty_completed_segments_for_folders(folder_ids)
    if dirty_count > 0 or j.get("status") not in ("audio_completed", "audio_launched"):
        return "audio"

    return None  # tout est fait



def _execute_ap_step(job_id: int, step: str, job: dict, *, checkpoint=None) -> None:
    """Exécute UNE étape de l'auto-pilot (synchrone — bloque le tick courant)."""
    if job.get("status") in ("error", "audio_error"):
        fallback = _pipeline_error_fallback_status(job)
        update_job(job_id, status=fallback, error_message=None)
        job = {**job, "status": fallback, "error_message": None}

    model = _normalize_pipeline_model_choice(job.get("auto_pilot_model"), default="pro")
    tts_mode = job.get("auto_pilot_tts_mode") or "gtts"
    if job.get("auto_pilot_use_cc"):
        logger.warning(
            "PIPELINE_LEGACY_CLAUDE_CODE_DISABLED job=%s fallback=deepseek",
            job_id,
        )
        update_job(job_id, auto_pilot_use_cc=0, auto_pilot_model=model)
    platform_id = job["platform_id"]

    api_model = _PIPELINE_MODEL_ALIASES[model]

    if step == "reac":
        from services.formation_health_service import compute_preflight
        preflight = compute_preflight(job_id, tts_mode=tts_mode)
        if not preflight["ok"]:
            raise RuntimeError(f"Pre-flight bloqué : {', '.join(preflight['blocking'])}")
        logger.info(f"🛂 Pre-flight OK job {job_id}")
        update_job(job_id, status="reac_fetching")

        def _log_reac_attempt(**payload):
            try:
                from services.formation_observability_service import log_pipeline_event
                status = payload.get("status") or "info"
                attempt = payload.get("attempt")
                total = payload.get("total")
                wait_seconds = payload.get("wait_seconds") or 0
                error = payload.get("error")
                message = f"REAC tentative {attempt}/{total} : {status}"
                if status == "retrying":
                    message += f" — nouvelle tentative dans {wait_seconds:.0f}s"
                log_pipeline_event(
                    job_id,
                    "reac_download_attempt",
                    step="reac",
                    status="error" if status == "failed" else status,
                    message=message,
                    model=api_model,
                    data={
                        "attempt": attempt,
                        "total": total,
                        "wait_seconds": wait_seconds,
                        "rncp_code": job["rncp_code"],
                    },
                    error=error,
                )
            except Exception:
                pass

        reac = download_reac_text_with_retry(
            job["rncp_code"],
            attempts=1,
            on_attempt=_log_reac_attempt,
        )
        rc_text, rome_text = None, None
        try:
            rc_text = download_rc_text(job["rncp_code"]) or None
        except Exception:
            pass
        try:
            rome_text = fetch_rome_data(job["rncp_code"]) or None
        except Exception:
            pass
        update_job(job_id, status="reac_ready", reac_text=reac,
                   rc_text=rc_text, rome_text=rome_text)
        logger.info(f"🤖 ✓ REAC téléchargé job {job_id}")

    elif step == "kb":
        build_knowledge_base(job_id, model=api_model, checkpoint=checkpoint)
        logger.info(f"🤖 ✓ KB construite job {job_id}")

    elif step == "global":
        generate_global_program(job_id, model=api_model, checkpoint=checkpoint)
        update_job(job_id, global_program_validated=1, status="global_validated")
        logger.info(f"🤖 ✓ Programme global validé job {job_id}")

    elif step == "daily":
        run_daily_split(job_id, model=api_model, checkpoint=checkpoint)
        logger.info(f"🤖 ✓ Programmes journée validés job {job_id}")

    elif step == "content":
        # Mode API : génération synchrone par folder, avec concurrence bornée.
        # Pas de tâche background détachée : run_content_generation reste appelé
        # dans le work item durable — résiste aux restarts Azure car :
        #   - folder existant mais job running/idle → run reprend les segments manquants
        #   - folder existant + job completed → skip via done_set
        #   - aucun thread mort possible (pas de thread du tout)
        import json as _json
        from services.content_generation_service import run_content_generation
        from repositories.pipeline_repository import (
            list_content_completion_rows_for_folders,
            reset_and_upsert_content_generation_jobs,
        )
        from services.formation_pipeline_service import (
            _format_day_program_text,
            expected_course_folder_name,
            get_expected_course_folders,
            repair_orphan_content_folders,
        )

        daily_programs = _json.loads(job.get("daily_programs") or "[]")
        update_job(
            job_id,
            status="tts_launched",
            auto_pilot_volume_done=0,
            auto_pilot_post_review_docs_done=0,
            error_message=None,
        )
        # Historical folders are repaired only while the durable worker owns
        # the content step, never while an admin is merely viewing the page.
        repair_orphan_content_folders(job_id)
        folder_state = get_expected_course_folders(
            job_id,
            create_missing=True,
            platform_id=platform_id,
        )
        folders_by_name = {
            f["expected_name"]: f
            for f in folder_state.get("folders", [])
        }
        if folder_state.get("duplicates"):
            logger.warning(
                "PIPELINE_CONTENT_DUPLICATE_FOLDERS job=%s duplicates=%s",
                job_id,
                [
                    {
                        "folder_id": d["folder_id"],
                        "name": d["name"],
                        "duplicate_of": d.get("duplicate_of"),
                    }
                    for d in folder_state["duplicates"]
                ],
            )

        planned_days = []
        for idx, day_data in enumerate(daily_programs):
            day_data = _normalize_day_audio_slots(day_data)
            folder_name = expected_course_folder_name(day_data, idx + 1)
            folder_info = folders_by_name.get(folder_name)
            if not folder_info:
                raise RuntimeError(f"Folder attendu introuvable : {folder_name}")
            folder_id = folder_info["folder_id"]
            day_num = day_data.get("day_number", idx + 1)

            planned_days.append({
                "day_num": day_num,
                "folder_id": folder_id,
                "day_data": day_data,
            })

        folder_ids = [day["folder_id"] for day in planned_days]
        content_rows = {
            int(row["folder_id"]): row
            for row in list_content_completion_rows_for_folders(folder_ids)
        }
        day_tasks = []
        jobs_to_create = []
        for planned_day in planned_days:
            day_num = planned_day["day_num"]
            folder_id = planned_day["folder_id"]
            content_row = content_rows.get(folder_id) or {}
            if content_row.get("content_job_id") and content_row.get("status") == "completed":
                logger.info(f"🤖   ⏭ Jour {day_num} déjà complété (folder {folder_id}), skip")
                continue

            if not content_row.get("content_job_id"):
                day_data = planned_day["day_data"]
                sub_parts = [sp["name"] for sp in day_data.get("sub_parts", [])]
                module_contents = {}
                for sp in day_data.get("sub_parts", []):
                    module_contents[sp["name"]] = _format_slot_generation_source(sp)
                jobs_to_create.append({
                    "folder_id": folder_id,
                    "platform_id": platform_id,
                    "program_text": _format_day_program_text(day_data, job["tp_name"]),
                    "program_title": job["tp_name"],
                    "sub_parts_json": _json.dumps(sub_parts, ensure_ascii=False),
                    "from_scratch": True,
                    "module_contents_json": _json.dumps(module_contents, ensure_ascii=False),
                })

            day_tasks.append({"day_num": day_num, "folder_id": folder_id})

        if jobs_to_create:
            reset_and_upsert_content_generation_jobs(jobs_to_create)
        logger.info(
            "PIPELINE_CONTENT_DAY_JOB_PREP job=%s folders=%s created=%s runnable=%s",
            job_id,
            len(planned_days),
            len(jobs_to_create),
            len(day_tasks),
        )

        day_workers = min(_formation_content_day_workers(), max(1, len(day_tasks) or 1))
        logger.info(
            "PIPELINE_CONTENT_DAY_PARALLEL_CONFIG job=%s workers=%s days=%s",
            job_id,
            day_workers,
            len(day_tasks),
        )

        def _run_content_day(task: dict) -> dict:
            day_num = task["day_num"]
            folder_id = task["folder_id"]
            try:
                # run_content_generation lit les segments déjà complétés :
                # idempotent, reprise naturelle si un folder avait déjà démarré.
                logger.info(f"🤖   Génération Jour {day_num} (folder {folder_id})…")
                run_content_generation(folder_id, model=api_model)
                logger.info(f"🤖   ✓ Jour {day_num} terminé (folder {folder_id})")
                return {"ok": True, "day_num": day_num, "folder_id": folder_id}
            except Exception as exc:
                logger.exception(
                    "PIPELINE_CONTENT_DAY_FAILED job=%s day=%s folder=%s",
                    job_id,
                    day_num,
                    folder_id,
                )
                return {
                    "ok": False,
                    "day_num": day_num,
                    "folder_id": folder_id,
                    "error": str(exc)[:500],
                    "exception": exc,
                }

        if day_workers <= 1:
            day_results = [_run_content_day(task) for task in day_tasks]
        else:
            with ThreadPoolExecutor(
                max_workers=day_workers,
                thread_name_prefix=f"pipeline-{job_id}-day",
            ) as pool:
                futures = [pool.submit(_run_content_day, task) for task in day_tasks]
                day_results = [future.result() for future in futures]

        failed_days = [result for result in day_results if not result.get("ok")]
        if failed_days:
            _raise_pipeline_batch_failure(
                "Génération contenu échouée sur journées : "
                + ", ".join(
                    f"J{result['day_num']} folder={result['folder_id']} ({result.get('error')})"
                    for result in failed_days
                ),
                failed_days,
            )

        logger.info(f"🤖 ✓ Contenu généré job {job_id}")

    elif step == "volume_safety":
        logger.warning(
            "🤖 Auto-pilot job %s : étape volume_safety ignorée, réparation append-only désactivée",
            job_id,
        )
        update_job(job_id, auto_pilot_volume_done=1, auto_pilot_post_review_docs_done=0)

    elif step == "humanization_review":
        logger.info(
            "🤖 Auto-pilot job %s : étape humanization_review ignorée, "
            "l'oralité est portée par le prompt initial",
            job_id,
        )
        update_job(job_id, auto_pilot_post_review_docs_done=0)

    elif step == "review":
        from services.formation_pipeline_service import get_expected_course_folders
        folder_ids = get_expected_course_folders(job_id).get("folder_ids") or []
        from services.content_generation_service import run_content_review
        failed = []
        reports_written = 0
        for fid in folder_ids:
            try:
                result = run_content_review(fid, model=api_model)
                _write_api_review_report(job_id, fid, result, api_model)
                reports_written += 1
                if result.get("segments_failed", 0) > 0:
                    error_samples = []
                    for detail in result.get("details") or []:
                        error = str((detail or {}).get("error") or "").strip()
                        if not error:
                            continue
                        error = " ".join(error.split())[:180]
                        if error not in error_samples:
                            error_samples.append(error)
                        if len(error_samples) >= 2:
                            break
                    suffix = f" : {' ; '.join(error_samples)}" if error_samples else ""
                    failed.append({
                        "label": f"{fid}({result['segments_failed']} segments échoués{suffix})",
                    })
            except Exception as e:
                logger.warning(f"⚠️ Review folder {fid} : {e}")
                failed.append({
                    "label": f"{fid}({str(e)[:180]})",
                    "exception": e,
                })
        if failed:
            _raise_pipeline_batch_failure(
                "Review échouée sur folders : "
                + ", ".join(failure["label"] for failure in failed),
                failed,
            )
        logger.info(
            "🤖 ✓ Rapports conformité persistés job %s : %s/%s",
            job_id,
            reports_written,
            len(folder_ids),
        )
        update_job(job_id, auto_pilot_post_review_docs_done=0)
        logger.info(f"🤖 ✓ Conformité locale terminée job {job_id}")

    elif step == "post_review_docs":
        from services.content_generation_service import (
            _assemble_and_upload,
            _update_job_db,
            assert_course_day_word_budget,
        )
        from services.formation_pipeline_service import get_expected_course_folders
        from repositories.pipeline_repository import list_completed_content_jobs_for_folders
        folder_ids = get_expected_course_folders(job_id).get("folder_ids") or []
        if not folder_ids:
            raise RuntimeError("Aucun texte complété à assembler après révision")
        rows = [
            (int(row["folder_id"]), int(row["content_job_id"]))
            for row in list_completed_content_jobs_for_folders(folder_ids)
        ]
        if not rows:
            raise RuntimeError("Aucun texte complété à assembler après révision")

        for fid, cg_job_id in rows:
            budget_audit = assert_course_day_word_budget(
                fid,
                context="auto_pilot_post_review_docs",
            )
            try:
                from services.formation_observability_service import log_pipeline_event
                log_pipeline_event(
                    job_id,
                    "day_word_budget_verified",
                    step="word_budget_review",
                    status="completed",
                    folder_id=fid,
                    model=api_model,
                    message="Budget mots journée vérifié avant Word 2",
                    data={
                        "spoken_words": budget_audit.get("spoken_words"),
                        "raw_words": budget_audit.get("raw_words"),
                        "deficit": budget_audit.get("deficit"),
                        "overflow": budget_audit.get("overflow"),
                        "budget": {
                            "target_words": budget_audit.get("budget", {}).get("target_words"),
                            "min_words": budget_audit.get("budget", {}).get("min_words"),
                            "max_words": budget_audit.get("budget", {}).get("max_words"),
                            "words_per_minute": budget_audit.get("budget", {}).get("words_per_minute"),
                            "course_seconds": budget_audit.get("budget", {}).get("course_seconds"),
                            "speakable_seconds": budget_audit.get("budget", {}).get("speakable_seconds"),
                        },
                    },
                )
            except Exception:
                pass
            final_words, filename = _assemble_and_upload(fid, platform_id, cg_job_id)
            _update_job_db(cg_job_id, total_words=final_words)
            try:
                deleted_decks = _delete_slide_deck_for_resume(fid, cg_job_id)
            except Exception as e:
                deleted_decks = 0
                logger.warning(
                    "⚠️ Nettoyage deck slides post-Word2 impossible job=%s folder=%s: %s",
                    job_id,
                    fid,
                    str(e)[:300],
                )
            logger.info(
                f"🤖   ✓ Document post-révision folder {fid} : "
                f"{final_words} mots, {filename}, decks slides supprimés={deleted_decks}"
            )
        # Les slides sont encore à produire. Garder un statut intermédiaire
        # empêche le dashboard de déclarer le professeur prêt trop tôt.
        # La prochaine étape durable `finalize_text` rendra le professeur prêt
        # uniquement après avoir vérifié les slides de chaque journée.
        update_job(job_id, status="tts_launched", auto_pilot_post_review_docs_done=1)
        logger.info(
            f"🤖 ✓ Documents post-révision générés job {job_id} "
            "(status=tts_launched, slides requises)"
        )

    elif step == "slides":
        from services.formation_pipeline_service import get_expected_course_folders
        from services.script_slide_generation_service import (
            generate_slides_from_script,
            get_latest_script_slide_deck,
            is_script_slide_deck_usable,
        )
        from services.formation_observability_service import log_pipeline_event
        from repositories.pipeline_repository import list_completed_content_jobs_for_folders

        folder_ids = get_expected_course_folders(job_id).get("folder_ids") or []
        if not folder_ids:
            raise RuntimeError("Aucun cours_folder trouvé pour générer les slides")
        rows = [
            (int(row["folder_id"]), int(row["content_job_id"]))
            for row in list_completed_content_jobs_for_folders(folder_ids)
        ]
        if not rows:
            raise RuntimeError("Aucun texte complété disponible pour générer les slides")

        generated = 0
        skipped = 0
        failures = []
        slide_api_model = _resolve_pipeline_slide_model(api_model)
        slide_workers = min(_slides_folder_workers(), max(1, len(rows)))
        pending_rows = []
        for fid, cg_job_id in rows:
            existing = get_latest_script_slide_deck(fid, content_job_id=cg_job_id)
            if is_script_slide_deck_usable(existing):
                skipped += 1
                continue
            pending_rows.append((fid, cg_job_id))

        logger.info(
            "🤖 Slides job %s : folders=%s pending=%s skipped=%s workers=%s model=%s",
            job_id,
            len(rows),
            len(pending_rows),
            skipped,
            min(slide_workers, max(1, len(pending_rows))) if pending_rows else 0,
            slide_api_model,
        )

        def _generate_slide_folder(fid: int, cg_job_id: int) -> dict:
            started = time.time()
            try:
                log_pipeline_event(
                    job_id,
                    "slides_folder_started",
                    step="slides",
                    status="running",
                    folder_id=fid,
                    model=slide_api_model,
                    message="Génération slides anchor-first démarrée",
                    data={
                        "content_job_id": cg_job_id,
                        "max_slides": 60,
                        "pace": "normal",
                        "parallel_folders": min(slide_workers, max(1, len(pending_rows))),
                    },
                )
                result = generate_slides_from_script(
                    folder_id=fid,
                    job_id=job_id,
                    platform_id=platform_id,
                    max_slides=60,
                    pace="normal",
                    model=slide_api_model,
                )
                log_pipeline_event(
                    job_id,
                    "slides_folder_completed",
                    step="slides",
                    status="completed",
                    folder_id=fid,
                    model=slide_api_model,
                    duration_ms=int((time.time() - started) * 1000),
                    message="Génération slides anchor-first terminée",
                    data={
                        "content_job_id": cg_job_id,
                        "deck_id": (result.get("stats") or {}).get("deck_id"),
                        "slides_generated": (result.get("stats") or {}).get("slides_generated"),
                        "slide_anchors_found": (result.get("stats") or {}).get("slide_anchors_found"),
                        "generation_mode": (result.get("stats") or {}).get("generation_mode"),
                        "slide_batch_workers": (result.get("stats") or {}).get("slide_batch_workers"),
                    },
                )
                return {"status": "generated", "folder_id": fid}
            except Exception as e:
                err = str(e)[:500]
                try:
                    log_pipeline_event(
                        job_id,
                        "slides_folder_failed",
                        step="slides",
                        status="error",
                        folder_id=fid,
                        model=slide_api_model,
                        duration_ms=int((time.time() - started) * 1000),
                        message="Génération slides anchor-first échouée",
                        error=err,
                    )
                except Exception:
                    pass
                return {
                    "status": "failed",
                    "folder_id": fid,
                    "error": err,
                    "exception": e,
                }

        if pending_rows:
            active_workers = min(slide_workers, len(pending_rows))
            if active_workers > 1:
                with ThreadPoolExecutor(max_workers=active_workers) as pool:
                    future_map = {
                        pool.submit(_generate_slide_folder, fid, cg_job_id): (fid, cg_job_id)
                        for fid, cg_job_id in pending_rows
                    }
                    for future in as_completed(future_map):
                        result = future.result()
                        if result.get("status") == "generated":
                            generated += 1
                        else:
                            failures.append(result)
            else:
                for fid, cg_job_id in pending_rows:
                    result = _generate_slide_folder(fid, cg_job_id)
                    if result.get("status") == "generated":
                        generated += 1
                    else:
                        failures.append(result)
        if failures:
            _raise_pipeline_batch_failure(
                "Slides échouées sur folders : "
                + ", ".join(
                    f"{failure.get('folder_id')}({failure.get('error')})"
                    for failure in failures
                ),
                failures,
            )
        logger.info(
            "🤖 ✓ Slides générées job %s : generated=%s skipped=%s workers=%s model=%s",
            job_id,
            generated,
            skipped,
            min(slide_workers, max(1, len(pending_rows))) if pending_rows else 0,
            slide_api_model,
        )

    elif step == "finalize_text":
        # This transition creates the module envelope and exposes the platform.
        # Keeping it inside its own work item makes failures retryable without
        # letting a GET/status request perform business writes.
        _finalize_text_ready_state(job_id)
        from services.daily_course_pdf_service import publish_pipeline_course_pdfs

        published_course_pdfs = publish_pipeline_course_pdfs(
            job_id=int(job_id),
            platform_id=int(platform_id),
        )
        update_kwargs = {
            "status": "text_ready",
            "error_message": None,
        }
        if job.get("auto_pilot_generate_audio") and not _legacy_bulk_audio_enabled():
            update_kwargs["auto_pilot_generate_audio"] = 0
        update_job(job_id, **update_kwargs)
        logger.info(
            "🤖 ✓ Finalisation texte durable terminée job %s, supports_pdf=%s",
            job_id,
            len(published_course_pdfs),
        )

    elif step == "audio":
        if not _legacy_bulk_audio_enabled():
            raise RuntimeError(
                "Synthèse audio bulk désactivée : utiliser le déclenchement durable J-1 par séance"
            )
        from services.content_generation_service import generate_audio_from_script
        from services.formation_pipeline_service import get_expected_course_folders
        folder_ids = get_expected_course_folders(job_id).get("folder_ids") or []
        if not folder_ids:
            raise RuntimeError("Aucun cours_folder trouvé pour la plateforme")

        mock = (tts_mode == "mock")
        basic_tts = (tts_mode == "gtts")
        voice_type = "mock" if mock else ("gtts" if basic_tts else "fish_audio")
        update_job(job_id, status="audio_running", error_message=None)
        for idx, fid in enumerate(folder_ids):
            next_fid = folder_ids[idx + 1] if idx + 1 < len(folder_ids) else None
            folder_started_at = time.time()
            try:
                from services.formation_observability_service import log_pipeline_event
                log_pipeline_event(
                    job_id,
                    "audio_folder_started",
                    step="audio",
                    status="running",
                    folder_id=fid,
                    message="Synthèse audio journée démarrée",
                    model=_resolve_pipeline_api_model(job),
                    data={"voice_type": voice_type, "auto_pilot": True},
                )
            except Exception:
                pass
            try:
                generate_audio_from_script(
                    fid,
                    on_progress=_make_audio_progress_logger(job_id, fid, voice_type),
                    force_all=False,
                    mock=mock,
                    basic_tts=basic_tts,
                    next_folder_id=next_fid,
                    is_last_folder=next_fid is None,
                    sync_slides=True,
                    auto_generate_slides=True,
                    slide_max_slides=60,
                    slide_pace="normal",
                    slide_model=_resolve_pipeline_api_model(job),
                    llm_model=_resolve_pipeline_api_model(job),
                )
            except Exception as e:
                try:
                    from services.formation_observability_service import log_pipeline_event
                    log_pipeline_event(
                        job_id,
                        "audio_folder_failed",
                        step="audio",
                        status="error",
                        folder_id=fid,
                        duration_ms=int((time.time() - folder_started_at) * 1000),
                        message="Synthèse audio journée échouée",
                        model=_resolve_pipeline_api_model(job),
                        data={"voice_type": voice_type, "auto_pilot": True},
                        error=str(e)[:500],
                    )
                except Exception:
                    pass
                raise
            try:
                from services.formation_observability_service import log_pipeline_event
                log_pipeline_event(
                    job_id,
                    "audio_folder_completed",
                    step="audio",
                    status="completed",
                    folder_id=fid,
                    duration_ms=int((time.time() - folder_started_at) * 1000),
                    message="Synthèse audio journée terminée",
                    model=_resolve_pipeline_api_model(job),
                    data={"voice_type": voice_type, "auto_pilot": True},
                )
            except Exception:
                pass
            time.sleep(5)
        # Status posé APRÈS le loop — si Azure redémarre en cours de route,
        # dirty=1 sur les folders non traités permettra à _determine_next_ap_step
        # de détecter que l'audio est incomplet et de relancer l'étape.
        update_job(job_id, status="audio_completed", error_message=None)

        _finalize_audio_ready_state(job_id, voice_type)

        # Health-check final — bloque sur les incohérences bloquantes.
        # Un warning silencieux permettrait à l'auto-pilot de finir avec une
        # formation incomplète (segments manquants, audios dirty, etc.).
        from services.formation_health_service import compute_health
        health = compute_health(job_id)
        if health["ok"]:
            logger.info(f"💚 Health-check OK job {job_id}")
        else:
            blocking = health.get("blocking", [])
            raise RuntimeError(
                f"Health-check : {len(blocking)} incohérence(s) bloquante(s) : {blocking}"
            )
        logger.info(f"🤖 ✓ Audio TTS terminé job {job_id}")


@formation_bp.route("/api/formation/<int:job_id>/run-auto", methods=["POST"])
def run_auto_pilot(job_id):
    """Ancien démarrage manuel, remplacé par la commande professeur IA."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403
    return jsonify({
        "error": (
            "Le démarrage manuel a été retiré. "
            "La pipeline démarre automatiquement après la commande d'un professeur IA."
        ),
        "code": "teacher_order_required",
    }), 410


@formation_bp.route("/api/formation/<int:job_id>/run-auto/resume", methods=["POST"])
def resume_auto_pilot(job_id):
    """Reprend l'auto-pilot sans réinitialiser les flags déjà validés."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    force = bool((request.get_json(silent=True) or {}).get("force"))
    from services.pipeline_queue import get_latest_work_item

    active_item = get_latest_work_item(job_id)
    if active_item and not active_item.terminal:
        if force and active_item.status != "running":
            active_item = None
        else:
            message = (
                "Une étape est réellement en cours; arrêt coopératif requis avant reprise"
                if force and active_item.status == "running"
                else "Auto-pilot déjà en file ou en cours pour ce job"
            )
            return jsonify({
                "error": message,
                "work_item_id": active_item.id,
                "queue_status": active_item.status,
                "run_id": active_item.run_id,
            }), 409

    try:
        next_step = _determine_next_ap_step(job_id)
    except Exception as e:
        return jsonify({"error": f"Impossible de calculer la prochaine étape : {str(e)[:300]}"}), 500

    resume_updates = {
        "auto_pilot_enabled": 1,
        "auto_pilot_error": None,
        "auto_pilot_step": next_step or "done",
    }
    if job.get("status") in ("error", "audio_error"):
        resume_updates.update(
            status=_pipeline_error_fallback_status(job),
            error_message=None,
        )
    update_job(job_id, **resume_updates)

    if next_step is None:
        return jsonify({
            "ok": True,
            "status": "done",
            "step": "done",
            "next_step": None,
        }), 200

    try:
        from services.formation_observability_service import log_pipeline_event
        log_pipeline_event(
            job_id,
            "pipeline_resume_requested",
            step=next_step,
            status="running",
            model=job.get("auto_pilot_model"),
            message=f"Reprise auto-pilot demandée : {next_step}",
            data={"previous_step": job.get("auto_pilot_step")},
        )
    except Exception:
        pass

    linked_order = None
    center_account_id = _training_center_account_id()
    if center_account_id is not None:
        try:
            from repositories.billing_repository import get_order_by_pipeline_job_id

            linked_order = get_order_by_pipeline_job_id(
                job_id,
                center_account_id=center_account_id,
            )
        except Exception:
            logger.warning(
                "PIPELINE_RESUME_ORDER_LOOKUP_FAILED job=%s center=%s",
                job_id,
                center_account_id,
                exc_info=True,
            )

    if force:
        from services.pipeline_queue import cancel_latest_work_item

        cancel_latest_work_item(job_id)
    dispatch = _dispatch_auto_pilot_tick(
        job_id,
        reason="manual_resume",
        force_new_run=force,
        chain_payload=(
            {"teacher_order_id": int(linked_order["id"])}
            if linked_order and linked_order.get("id")
            else None
        ),
    )
    if linked_order and linked_order.get("id"):
        try:
            from repositories.billing_repository import mark_order_pipeline_resume_requested

            mark_order_pipeline_resume_requested(
                int(linked_order["id"]),
                pipeline_job_id=job_id,
            )
        except Exception:
            logger.warning(
                "PIPELINE_RESUME_ORDER_STATE_FAILED job=%s order=%s",
                job_id,
                linked_order.get("id"),
                exc_info=True,
            )
    return jsonify({
        "ok": True,
        "status": "auto_pilot_resumed",
        "step": next_step,
        "next_step": next_step,
        "model": job.get("auto_pilot_model"),
        "tts_mode": job.get("auto_pilot_tts_mode"),
        "generate_audio": bool(job.get("auto_pilot_generate_audio")),
        "dispatch": dispatch,
    }), 202


@formation_bp.route("/api/formation/<int:job_id>/run-auto/stop", methods=["POST"])
def stop_auto_pilot(job_id):
    """Ancienne commande manuelle conservée comme tombstone HTTP 410."""
    return _retired_manual_pipeline_response("stop_auto_pilot")


@formation_bp.route("/api/formation/<int:job_id>/run-auto/status", methods=["GET"])
def auto_pilot_status(job_id):
    """État de l'auto-pilot lu depuis la DB (résiste aux restarts)."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404
    queue_state = _queue_status_for_job(job_id)
    if not job.get("auto_pilot_enabled"):
        if job.get("auto_pilot_step") == "stopped":
            try:
                next_step = _determine_next_ap_step(job_id)
            except Exception:
                next_step = None
            return jsonify({
                "status": "stopped",
                "step": "stopped",
                "next_step": next_step,
                "model": job.get("auto_pilot_model"),
                "tts_mode": job.get("auto_pilot_tts_mode"),
                "generate_audio": bool(job.get("auto_pilot_generate_audio")),
                "queue": queue_state,
            }), 200
        return jsonify({"status": "idle", "queue": queue_state}), 200
    step = job.get("auto_pilot_step")
    error = job.get("auto_pilot_error")
    model = job.get("auto_pilot_model")
    tts_mode = job.get("auto_pilot_tts_mode")
    generate_audio = bool(job.get("auto_pilot_generate_audio"))
    try:
        next_step = _determine_next_ap_step(job_id)
    except Exception:
        next_step = None
    if step == "done":
        return jsonify({"status": "done", "step": "done", "next_step": next_step, "model": model, "tts_mode": tts_mode, "generate_audio": generate_audio, "queue": queue_state}), 200
    if error:
        return jsonify({"status": "error", "step": step, "next_step": next_step, "error": error, "model": model, "tts_mode": tts_mode, "generate_audio": generate_audio, "queue": queue_state}), 200
    if step:
        return jsonify({"status": "running", "step": step, "next_step": next_step, "model": model, "tts_mode": tts_mode, "generate_audio": generate_audio, "queue": queue_state}), 200
    return jsonify({"status": "starting", "next_step": next_step, "model": model, "tts_mode": tts_mode, "generate_audio": generate_audio, "queue": queue_state}), 200


@formation_bp.route("/api/formation/<int:job_id>/events", methods=["GET"])
def formation_pipeline_events(job_id):
    """Retourne les événements structurés de pipeline pour diagnostic/dashboard."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404
    try:
        limit = int(request.args.get("limit", 200))
    except (TypeError, ValueError):
        limit = 200
    from services.formation_observability_service import list_pipeline_events
    return jsonify({"events": list_pipeline_events(job_id, limit=limit)}), 200


@formation_bp.route("/api/formation/<int:job_id>/diagnostic", methods=["GET"])
def formation_pipeline_diagnostic(job_id):
    """Snapshot exploitable par l'UI : état job + health + événements récents.

    Objectif : ne plus diagnostiquer une pipeline depuis un simple status global.
    Cet endpoint agrège les signaux de contrôle sans relancer d'étape coûteuse.
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    try:
        events_limit = int(request.args.get("events_limit", 80))
    except (TypeError, ValueError):
        events_limit = 80

    try:
        from services.formation_health_service import compute_health
        health = compute_health(job_id)
    except Exception as e:
        logger.warning(f"⚠️ Diagnostic health job {job_id} : {e}")
        health = {
            "ok": False,
            "blocking": ["health_error"],
            "warnings": [],
            "checks": {"health_error": {"ok": False, "detail": str(e)[:500]}},
        }

    try:
        from services.formation_volume_audit_service import compute_volume_audit
        volume_audit = compute_volume_audit(job_id)
    except Exception as e:
        logger.warning(f"⚠️ Diagnostic volume job {job_id} : {e}")
        volume_audit = None

    from services.formation_observability_service import list_pipeline_events
    events = list_pipeline_events(job_id, limit=events_limit)

    try:
        from services.formation_pipeline_service import get_expected_course_folders
        folder_state = get_expected_course_folders(job_id)
    except Exception as e:
        logger.warning(f"⚠️ Diagnostic résolution folders job {job_id} : {e}")
        folder_state = {"expected_count": 0, "folder_ids": [], "duplicates": [], "missing": []}

    try:
        next_auto_step = _determine_next_ap_step(job_id)
    except Exception as e:
        logger.warning(f"⚠️ Diagnostic next auto step job {job_id} : {e}")
        next_auto_step = None

    folders = []
    try:
        from repositories.pipeline_repository import (
            list_content_completion_rows_for_folders,
            list_text_folder_states_for_folders,
        )
        folder_ids = folder_state.get("folder_ids") or []
        if folder_ids:
            completion_by_folder = {
                int(row["folder_id"]): row
                for row in list_content_completion_rows_for_folders(folder_ids)
            }
            for state in list_text_folder_states_for_folders(folder_ids):
                folder_id = int(state["folder_id"])
                completion = completion_by_folder.get(folder_id) or {}
                folders.append({
                    "folder_id": folder_id,
                    "folder_label": f"F{folder_id}",
                    "name": state.get("folder_name"),
                    "position": state.get("position"),
                    "platform_id": state.get("platform_id"),
                    "formation_job_id": state.get("formation_job_id"),
                    "content_job_id": state.get("content_job_id"),
                    "content_status": state.get("content_status"),
                    "total_words": state.get("total_words") or 0,
                    "segments_total": completion.get("segments_total") or 0,
                    "segments_completed": completion.get("completed_segments") or 0,
                    "reviewed_segments": completion.get("reviewed_segments") or 0,
                    "review_errors": completion.get("review_error_segments") or 0,
                    "dirty_segments": completion.get("dirty_segments") or 0,
                })
    except Exception as e:
        logger.warning(f"⚠️ Diagnostic folders job {job_id} : {e}")

    public_job = {
        key: job.get(key)
        for key in (
            "id",
            "job_label",
            "status",
            "platform_id",
            "platform_label",
            "platform_name",
            "tp_name",
            "rncp_code",
            "nb_days",
            "auto_pilot_enabled",
            "auto_pilot_step",
            "auto_pilot_error",
            "auto_pilot_model",
            "auto_pilot_tts_mode",
            "error_message",
        )
        if key in job
    }

    return jsonify({
        "job": public_job,
        "health": health,
        "volume_audit": volume_audit,
        "folders": folders,
        "folder_resolution": {
            "expected_count": folder_state.get("expected_count", 0),
            "duplicates": folder_state.get("duplicates", []),
            "missing": folder_state.get("missing", []),
        },
        "next_auto_step": next_auto_step,
        "events": events,
        # Kept for API compatibility. Finalization is performed only by a
        # durable worker, never by this monitoring endpoint.
        "finalize": None,
    }), 200
