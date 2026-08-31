# hr_routes.py - Routes du Dashboard RH (centre de contrôle multi-plateformes)
import json
import io
import os
import re
import time
import requests as http_requests
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from flask import Blueprint, request, session, jsonify, Response, stream_with_context, send_file, g
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.exceptions import ResourceExistsError
from config import FRANCE_TZ, PIPELINE_DATABASE_BACKEND
from database.db import get_db_connection
from database.postgres import postgres_enabled
from repositories.core_repository import (
    get_platform_by_creation_request_id,
    get_training_center_by_id,
    upsert_cours_config,
    upsert_platform_config,
)
from repositories.course_schedule_repository import (
    add_explicit_course_reminder_recipients,
    assign_fallback_audio_to_session,
    delete_explicit_course_reminder_recipient,
    get_audio_generation_session,
    get_next_course_session,
    list_course_schedule_dashboard_states,
    list_course_sessions,
    list_explicit_course_reminder_recipients,
    schedule_store_is_postgres,
)
from repositories.hr_read_repository import (
    list_formation_modules as list_hr_formation_modules,
    list_formations as list_hr_formations,
    list_platforms as list_hr_platforms,
)
from repositories.hr_write_repository import (
    CloneSourceInvalid,
    CloneSourceNotFound,
    clone_postgres_course_structure,
    create_postgres_manual_formation_module,
    resolve_postgres_formation_clone_source,
    resolve_postgres_module_clone_source,
    set_postgres_platform_status,
)
from repositories import attendance_repository as attendance_repo
from repositories.center_workspace_repository import (
    complete_center_onboarding,
    get_center_onboarding_state,
    set_platform_asset_binding_mode,
    set_platform_lifecycle,
)
from repositories.teacher_asset_repository import (
    CANONICAL_AUDIO_PLAYLIST_PATHS,
    resolve_folder_asset_origin,
)
from repositories.pipeline_repository import (
    allocate_platform_id_from_postgres,
    get_course_folder_identity,
    hr_resource_belongs_to_center,
    list_course_folder_rows_for_platform,
    pipeline_job_belongs_to_center,
    platform_ids_use_postgres_allocator,
)
from services.course_schedule_service import (
    build_course_session_state,
    create_missing_course_schedule,
    ensure_course_schedule_tables,
    get_course_schedule_summary,
    get_course_schedule_details,
    get_course_schedule_details_for_platform,
    get_course_reminder_rules,
    process_due_reminders,
    postpone_course_session,
    preview_course_session_postponement,
    run_scheduler_tick,
    save_course_schedule,
    save_course_reminder_rule,
    delete_course_reminder_rule,
    update_course_schedule,
)
from services.export_service import generate_attendance_excel_export
from services.attendance_service import (
    download_daily_attendance_excel,
    get_attendance_dashboard,
)
from services.scheduled_audio_service import (
    process_due_audio_generations,
    retry_scheduled_audio_generation,
)
from services.teacher_preparation_service import build_teacher_preparation_state
from services.recruitment_conversation_service import interpret_recruitment_answer
from services.teacher_asset_service import resolve_folder_blob_path
from services.audio_publish_service import archive_public_platform_audios, publish_playlist_audio_to_platform
from utils.logger import get_logger
from utils.slug import slugify, unique_slug
import state

logger = get_logger(__name__)


def _retired_local_generation_response():
    """Bloque les anciennes générations lancées dans le processus web."""
    return jsonify({
        "success": False,
        "status": "retired",
        "code": "local_generation_retired",
        "error": (
            "Cette génération locale a été retirée. "
            "La création et la reprise passent désormais par la pipeline durable."
        ),
    }), 410

PDF_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "pdfs")

HR_ENABLED = os.environ.get("HR_DASHBOARD_ENABLED", "false").lower() == "true"
HR_DASHBOARD_BLOB_PAGE_SIZE = int(os.environ.get("HR_DASHBOARD_BLOB_PAGE_SIZE", "200"))
HR_DASHBOARD_BLOB_MAX_ITEMS = int(os.environ.get("HR_DASHBOARD_BLOB_MAX_ITEMS", "1000"))
HR_DASHBOARD_BLOB_TIMEOUT_SECONDS = float(os.environ.get("HR_DASHBOARD_BLOB_TIMEOUT_SECONDS", "4"))
HR_DASHBOARD_REPAIR_ON_LOAD = os.environ.get("HR_DASHBOARD_REPAIR_ON_LOAD", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CENTER_ONBOARDING_VERSION = 1

_POSTGRES_PIPELINE_BACKENDS = {"postgres", "postgresql", "supabase"}
_HR_SUPERADMIN_ACCOUNT_TYPES = {"legacy_admin", "superadmin"}
_MAX_STUDENT_EMAILS_PER_REQUEST = 1000
_MAX_STUDENT_EMAIL_REQUEST_BYTES = 300_000
_STUDENT_EMAIL_RE = re.compile(
    r"^[A-Z0-9!#$%&'*+/=?^_`{|}~.-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)


def _normalize_student_email(value):
    email = str(value or "").strip().lower()
    if not email or len(email) > 254 or any(ord(char) < 32 for char in email):
        raise ValueError(f"Email invalide: {email[:80]}")
    display_name, parsed = parseaddr(email)
    local_part, separator, domain = email.rpartition("@")
    if (
        display_name
        or parsed.lower() != email
        or separator != "@"
        or not local_part
        or len(local_part) > 64
        or local_part.startswith(".")
        or local_part.endswith(".")
        or ".." in local_part
        or len(domain) > 253
        or not _STUDENT_EMAIL_RE.fullmatch(email)
    ):
        raise ValueError(f"Email invalide: {email[:80]}")
    return email


def _hr_pipeline_reads_use_postgres():
    return PIPELINE_DATABASE_BACKEND in _POSTGRES_PIPELINE_BACKENDS


_ARCHIVE_DEFAULTS = {
    1: "formationaudio-archives",
    2: "formationaudio-archives-p2",
    3: "formationaudio-p3-archives",
    4: "formationaudio-p4-archives",
}


def _get_platform_info(pid):
    """Retourne la config d'une plateforme distante depuis les env vars"""
    if pid == 1:
        return {
            "backend_url": None,
            "frontend_url": os.environ.get("PLATFORM_1_FRONTEND_URL", "http://localhost:5173"),
            "audio_container": os.environ.get("AZURE_AUDIO_CONTAINER", "formationaudio-dev"),
            "audio_archive_container": os.environ.get("AZURE_AUDIO_ARCHIVE_CONTAINER", _ARCHIVE_DEFAULTS[1]),
            "pdf_container": os.environ.get("AZURE_STORAGE_CONTAINER", "formationpdf"),
        }
    return {
        "backend_url": os.environ.get(f"PLATFORM_{pid}_BACKEND_URL"),
        "frontend_url": os.environ.get(f"PLATFORM_{pid}_FRONTEND_URL"),
        "audio_container": os.environ.get(f"PLATFORM_{pid}_AUDIO_CONTAINER", f"formationaudio-p{pid}"),
        "audio_archive_container": os.environ.get(f"PLATFORM_{pid}_AUDIO_ARCHIVE_CONTAINER", _ARCHIVE_DEFAULTS.get(pid, f"formationaudio-archives-p{pid}")),
        "pdf_container": os.environ.get(f"PLATFORM_{pid}_PDF_CONTAINER", f"formationpdf-p{pid}"),
    }


def _is_local_platform(pid):
    """True si la plateforme tourne sur ce backend (pas de backend_url distant)"""
    info = _get_platform_info(pid)
    return not info.get("backend_url")


def _class_public_path(center_slug, platform_slug):
    return f"/classe/{center_slug or 'le-socrate'}/{platform_slug}"


def _class_public_url(frontend_url, center_slug, platform_slug):
    base_url = (frontend_url or request.headers.get("Origin") or "").rstrip("/")
    path = _class_public_path(center_slug, platform_slug)
    return f"{base_url}{path}" if base_url else path


def _module_scope_clause(alias="m"):
    if session.get("admin_account_type") == "training_center":
        return f"{alias}.center_account_id = ?", [session.get("admin_account_id")]
    return "1 = 1", []


def _publish_playlist_audio_to_platform(
    platform_id,
    folder_id,
    filenames=None,
    *,
    source_platform_id=None,
    archive_existing=False,
    archive_reason="auto-publish",
):
    """Copie les MP3 générés du dossier vers le container audio public de la plateforme.

    La page /video lit les fichiers à la racine du container formationaudio-pX,
    alors que la génération TTS écrit dans audiostts/platform-X/folder-Y/playlist/.
    """
    return publish_playlist_audio_to_platform(
        platform_id,
        folder_id,
        filenames,
        source_platform_id=source_platform_id,
        archive_existing=archive_existing,
        archive_reason=archive_reason,
    )


def _bool_arg(name, default=False):
    raw = request.args.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _generated_audio_sync_readiness(folder_id, expected_filenames):
    """Require valid timings for every course file and every persisted slide."""
    from services.audio_asset_validation_service import inspect_audio_sync_readiness

    return inspect_audio_sync_readiness(folder_id, expected_filenames)


def _inspect_generated_audio_assets(folder_id, folder, playlist_contract):
    """Return only physically valid, current-manifest, synchronized assets as ready."""
    from services.audio_asset_validation_service import inspect_mp3_blob
    from services.day_playlist_service import is_course_audio_filename

    platform_id = int(folder["platform_id"])
    expected_items = [
        {
            "filename": filename,
            "duration_seconds": int(duration_seconds),
            "type": file_type,
            "course_index": int(course_index),
        }
        for filename, duration_seconds, file_type, course_index
        in playlist_contract.get("playlist_items") or []
    ]
    expected_by_name = {item["filename"]: item for item in expected_items}
    origin = resolve_folder_asset_origin(folder_id) or {}
    source_platform_id = int(origin.get("source_platform_id") or platform_id)
    source_folder_id = int(origin.get("source_folder_id") or folder_id)
    prefix = f"platform-{source_platform_id}/folder-{source_folder_id}/playlist/"

    tts_conn = os.environ.get("AZURE_TTS_STORAGE_CONNECTION_STRING")
    if not tts_conn:
        return {
            "audios": [],
            "invalid_audios": [],
            "audio_playlist_items": [
                {**item, "readiness": "missing", "readiness_reason": "storage_unconfigured"}
                for item in expected_items
            ],
            "audio_sync_status": _generated_audio_sync_readiness(
                source_folder_id,
                expected_by_name,
            ),
            "_storage": None,
        }

    bsc = BlobServiceClient.from_connection_string(tts_conn)
    cc = bsc.get_container_client("audiostts")
    sync_status = _generated_audio_sync_readiness(source_folder_id, expected_by_name)
    timing_files = set(sync_status.get("timing_files") or [])
    candidates = []
    by_name = {}
    for listed_blob in cc.list_blobs(name_starts_with=prefix):
        name = os.path.basename(listed_blob.name)
        if not name.lower().endswith(".mp3"):
            continue
        blob_client = cc.get_blob_client(listed_blob.name)
        props = None
        try:
            props = blob_client.get_blob_properties()
            expected_item = expected_by_name.get(name)
            physical = inspect_mp3_blob(
                blob_client,
                name,
                props=props,
                expected_duration_seconds=(expected_item or {}).get("duration_seconds"),
            )
        except Exception as exc:
            physical = {
                "filename": name,
                "ready": False,
                "physical_ready": False,
                "reason": "audio_inspection_failed",
                "detail": str(exc)[:240],
                "size_bytes": int(getattr(listed_blob, "size", 0) or 0),
            }

        expected_item = expected_by_name.get(name)
        expected = expected_item is not None
        is_course = is_course_audio_filename(name)
        sync_ready = not is_course or (
            bool(sync_status.get("ready")) and name in timing_files
        )
        reason = physical.get("reason")
        if not expected:
            reason = "unexpected_audio"
        elif physical.get("physical_ready") and not sync_ready:
            reason = "missing_audio_sync"
        ready = bool(expected and physical.get("physical_ready") and sync_ready)
        last_modified = getattr(props, "last_modified", None) if props is not None else None
        candidate = {
            **physical,
            "filename": name,
            "ready": ready,
            "expected": expected,
            "sync_ready": sync_ready,
            "reason": reason,
            "size_mb": round(float(physical.get("size_bytes") or 0) / (1024 * 1024), 1),
            "last_modified": last_modified.strftime("%Y-%m-%d %H:%M") if last_modified else None,
            "blob_path": listed_blob.name,
        }
        candidates.append(candidate)
        by_name[name] = candidate

    playlist_with_readiness = []
    for item in expected_items:
        candidate = by_name.get(item["filename"])
        if not candidate:
            playlist_with_readiness.append({
                **item,
                "readiness": "missing",
                "readiness_reason": "missing_audio",
            })
        else:
            playlist_with_readiness.append({
                **item,
                "readiness": "ready" if candidate["ready"] else "invalid",
                "readiness_reason": candidate.get("reason"),
                "estimated_duration_seconds": candidate.get("estimated_duration_seconds"),
            })

    return {
        "audios": [candidate for candidate in candidates if candidate["ready"]],
        "invalid_audios": [candidate for candidate in candidates if not candidate["ready"]],
        "audio_playlist_items": playlist_with_readiness,
        "audio_sync_status": sync_status,
        "_storage": {
            "container_client": cc,
            "prefix": prefix,
            "source_platform_id": source_platform_id,
            "source_folder_id": source_folder_id,
        },
    }


_FINAL_SCRIPT_DOC_WHERE = "(cd.doc_type = 'final_script' OR cd.original_name LIKE 'cours_genere_%.txt')"


def _summarize_blobs(container_client, *, max_items=None, timeout_seconds=None):
    """Résumé borné d'un container Azure pour éviter de bloquer le dashboard RH."""
    max_items = max_items or HR_DASHBOARD_BLOB_MAX_ITEMS
    timeout_seconds = timeout_seconds or HR_DASHBOARD_BLOB_TIMEOUT_SECONDS
    deadline = time.monotonic() + timeout_seconds
    count = 0
    latest_blob = None

    pager = container_client.list_blobs(timeout=timeout_seconds).by_page(
        results_per_page=HR_DASHBOARD_BLOB_PAGE_SIZE
    )
    for page in pager:
        for blob in page:
            count += 1
            if latest_blob is None or blob.last_modified > latest_blob.last_modified:
                latest_blob = blob
            if count >= max_items or time.monotonic() >= deadline:
                return count, latest_blob
        if time.monotonic() >= deadline:
            return count, latest_blob

    return count, latest_blob


def _call_platform(pid, path, method="POST", json_data=None):
    """Appel HTTP service-to-service vers le backend d'une plateforme distante"""
    info = _get_platform_info(pid)
    backend_url = info.get("backend_url")
    if not backend_url:
        return None, "Plateforme non configurée"
    api_key = os.environ.get("PLATFORM_API_KEY", "")
    try:
        resp = http_requests.request(
            method,
            f"{backend_url}{path}",
            json=json_data,
            headers={"X-Platform-Key": api_key},
            timeout=10,
        )
        return resp.json(), None
    except Exception as e:
        logger.warning(f"⚠️ Erreur appel P{pid} {path}: {e}")
        return None, str(e)


def create_hr_blueprint():
    """Crée le blueprint du workspace centre."""
    hr_bp = Blueprint("hr", __name__)

    @hr_bp.route("/api/hr/enabled")
    def get_hr_enabled():
        return jsonify({"enabled": HR_ENABLED})

    @hr_bp.route("/api/hr/onboarding", methods=["GET"])
    def get_hr_onboarding():
        """Return the durable SPEC-01 onboarding state for the signed-in centre."""
        denied = _require_admin()
        if denied:
            return denied
        if _admin_account_type() in _HR_SUPERADMIN_ACCOUNT_TYPES:
            return jsonify({
                "success": True,
                "current_version": CENTER_ONBOARDING_VERSION,
                "onboarding_version": CENTER_ONBOARDING_VERSION,
                "completed": True,
            }), 200

        center_account_id = _training_center_account_id()
        if _admin_account_type() != "training_center" or center_account_id is None:
            return _tenant_resource_not_found()
        onboarding = get_center_onboarding_state(center_account_id)
        if not onboarding:
            return _tenant_resource_not_found()
        onboarding_version = int(onboarding.get("onboarding_version") or 0)
        return jsonify({
            "success": True,
            "current_version": CENTER_ONBOARDING_VERSION,
            "onboarding_version": onboarding_version,
            "completed_at": onboarding.get("onboarding_completed_at"),
            "completed": onboarding_version >= CENTER_ONBOARDING_VERSION,
        }), 200

    @hr_bp.route("/api/hr/onboarding/complete", methods=["POST"])
    def complete_hr_onboarding():
        """Persist completion so onboarding follows the centre across devices."""
        denied = _require_admin()
        if denied:
            return denied
        center_account_id = _training_center_account_id()
        if _admin_account_type() != "training_center" or center_account_id is None:
            return jsonify({"success": False, "error": "Compte centre requis"}), 403

        data = request.get_json(silent=True) or {}
        requested_version = data.get("version", CENTER_ONBOARDING_VERSION)
        try:
            requested_version = min(CENTER_ONBOARDING_VERSION, max(1, int(requested_version)))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Version d’onboarding invalide"}), 400
        onboarding = complete_center_onboarding(center_account_id, requested_version)
        if not onboarding:
            return _tenant_resource_not_found()
        return jsonify({
            "success": True,
            "current_version": CENTER_ONBOARDING_VERSION,
            "onboarding_version": int(onboarding.get("onboarding_version") or 0),
            "completed_at": onboarding.get("onboarding_completed_at"),
            "completed": int(onboarding.get("onboarding_version") or 0) >= CENTER_ONBOARDING_VERSION,
        }), 200

    @hr_bp.route("/api/hr/recruitment/interpret", methods=["POST"])
    def interpret_hr_recruitment_answer():
        """Process one recruitment turn from conversation history and current state."""
        denied = _require_admin()
        if denied:
            return denied
        if _admin_account_type() not in _HR_SUPERADMIN_ACCOUNT_TYPES | {"training_center"}:
            return jsonify({"success": False, "error": "Compte centre requis"}), 403

        data = request.get_json(silent=True) or {}
        field = str(data.get("field") or "").strip()
        message = str(data.get("message") or "").strip()
        draft = data.get("draft") if isinstance(data.get("draft"), dict) else {}
        history = data.get("history") if isinstance(data.get("history"), list) else []
        try:
            attempt = max(0, min(5, int(data.get("attempt") or 0)))
        except (TypeError, ValueError):
            attempt = 0
        if not message or len(message) > 2000:
            return jsonify({"success": False, "error": "Réponse invalide"}), 400

        try:
            result = interpret_recruitment_answer(
                field,
                message,
                draft=draft,
                history=history,
                attempt=attempt,
            )
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        return jsonify({"success": True, **result}), 200

    @hr_bp.route("/api/hr/recruitment/rncp/<rncp_code>", methods=["GET"])
    def verify_hr_recruitment_rncp(rncp_code):
        """Resolve one exact RNCP record from the official source."""
        denied = _require_admin()
        if denied:
            return denied
        if _admin_account_type() not in _HR_SUPERADMIN_ACCOUNT_TYPES | {"training_center"}:
            return jsonify({"success": False, "error": "Compte centre requis"}), 403

        code = re.sub(r"\D", "", str(rncp_code or ""))
        if not re.fullmatch(r"\d{4,6}", code):
            return jsonify({
                "success": False,
                "error": "Le code RNCP doit contenir entre 4 et 6 chiffres",
            }), 400

        try:
            from services.formation_pipeline_service import get_rncp_certification

            certification = get_rncp_certification(code)
        except Exception:
            logger.exception("RNCP_LOOKUP_FAILED code=%s", code)
            return jsonify({
                "success": False,
                "code": "rncp_source_unavailable",
                "error": (
                    "France Compétences est temporairement inaccessible. "
                    "Réessayez la vérification dans quelques instants."
                ),
            }), 503

        if certification is None:
            return jsonify({
                "success": False,
                "code": "rncp_not_found",
                "error": (
                    f"Je ne trouve aucune fiche correspondant au code RNCP {code}. "
                    "Vérifiez le code puis réessayez."
                ),
            }), 404

        available = bool(certification.get("reac_available"))
        return jsonify({
            "success": True,
            "available": available,
            "certification": certification,
            "reply": (
                ""
                if available
                else "Désolé, nous n’avons pas encore de professeur disponible pour dispenser cette formation."
            ),
        }), 200

    def _day_schedule_center_id():
        denied = _require_admin()
        if denied:
            return None, denied
        center_account_id = _training_center_account_id()
        if (
            _admin_account_type() != "training_center"
            or center_account_id is None
        ):
            return None, (
                jsonify({"success": False, "error": "Compte centre requis"}),
                403,
            )
        return center_account_id, None

    def _validated_schedule_blocks(payload):
        from services.dynamic_day_schedule_service import compile_day_schedule

        compiled = compile_day_schedule({"blocks": payload.get("blocks")})
        return compiled["blocks"]

    @hr_bp.route("/api/hr/day-schedule-templates", methods=["GET"])
    def list_day_schedule_templates_route():
        center_account_id, denied = _day_schedule_center_id()
        if denied:
            return denied
        from repositories.day_schedule_repository import list_templates

        return jsonify({
            "success": True,
            "templates": list_templates(center_account_id),
        }), 200

    @hr_bp.route("/api/hr/day-schedule-templates", methods=["POST"])
    def create_day_schedule_template_route():
        center_account_id, denied = _day_schedule_center_id()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        try:
            blocks = _validated_schedule_blocks(data)
            from repositories.day_schedule_repository import create_template

            template = create_template(
                center_account_id,
                data.get("name"),
                blocks,
                schedule_schema_version=2,
            )
        except Exception as exc:
            from services.dynamic_day_schedule_service import (
                ScheduleValidationError,
            )

            if isinstance(exc, ScheduleValidationError):
                return jsonify({
                    "success": False,
                    "error": str(exc),
                    "validation": exc.as_dict(),
                }), 400
            if isinstance(exc, ValueError):
                return jsonify({"success": False, "error": str(exc)}), 400
            raise
        return jsonify({"success": True, "template": template}), 201

    @hr_bp.route(
        "/api/hr/day-schedule-templates/<int:template_id>",
        methods=["PATCH"],
    )
    def update_day_schedule_template_route(template_id):
        center_account_id, denied = _day_schedule_center_id()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        try:
            blocks = (
                _validated_schedule_blocks(data)
                if "blocks" in data
                else None
            )
            from repositories.day_schedule_repository import (
                TemplateImmutableError,
                update_template,
            )

            template = update_template(
                center_account_id,
                template_id,
                name=data.get("name") if "name" in data else None,
                blocks=blocks,
            )
            if template is None:
                return _tenant_resource_not_found()
        except Exception as exc:
            from repositories.day_schedule_repository import (
                TemplateImmutableError,
            )
            from services.dynamic_day_schedule_service import (
                ScheduleValidationError,
            )

            if isinstance(exc, TemplateImmutableError):
                return jsonify({
                    "success": False,
                    "error": str(exc),
                    "code": "template_immutable",
                }), 409
            if isinstance(exc, ScheduleValidationError):
                return jsonify({
                    "success": False,
                    "error": str(exc),
                    "validation": exc.as_dict(),
                }), 400
            if isinstance(exc, ValueError):
                return jsonify({"success": False, "error": str(exc)}), 400
            raise
        return jsonify({"success": True, "template": template}), 200

    @hr_bp.route(
        "/api/hr/day-schedule-templates/<int:template_id>",
        methods=["DELETE"],
    )
    def delete_day_schedule_template_route(template_id):
        center_account_id, denied = _day_schedule_center_id()
        if denied:
            return denied
        from repositories.day_schedule_repository import soft_delete_template

        if not soft_delete_template(center_account_id, template_id):
            return _tenant_resource_not_found()
        return jsonify({"success": True, "deleted": True}), 200

    def _voice_center_id():
        denied = _require_admin()
        if denied:
            return None, denied
        center_account_id = _training_center_account_id()
        if _admin_account_type() != "training_center" or center_account_id is None:
            return None, (
                jsonify({"success": False, "error": "Compte centre requis"}),
                403,
            )
        return center_account_id, None

    def _voice_error_response(exc):
        from services.fish_voice_service import FishVoiceError

        if isinstance(exc, FishVoiceError):
            return jsonify({
                "success": False,
                "error": str(exc),
                "code": exc.code,
            }), exc.status_code
        raise exc

    @hr_bp.route("/api/hr/ai-voices", methods=["GET"])
    def list_ai_voices_route():
        center_account_id, denied = _voice_center_id()
        if denied:
            return denied
        from repositories.ai_voice_repository import list_voices

        return jsonify({"success": True, "voices": list_voices(center_account_id)}), 200

    @hr_bp.route("/api/hr/ai-voices/clone", methods=["POST"])
    def clone_ai_voice_route():
        center_account_id, denied = _voice_center_id()
        if denied:
            return denied
        from repositories.ai_voice_repository import create_voice
        from services.fish_voice_service import (
            MAX_CLONE_BYTES,
            RIGHTS_DECLARATION,
            audio_sha256,
            create_instant_clone,
            validate_audio,
        )

        name = str(request.form.get("name") or "").strip()[:80]
        transcript = str(request.form.get("transcript") or "").strip()[:5000]
        rights_declared = str(request.form.get("rights_declaration_confirmed") or "").lower() == "true"
        voice_sample = request.files.get("voice_sample")
        if not name:
            return jsonify({"success": False, "error": "Donnez un nom à la voix."}), 400
        if not rights_declared:
            return jsonify({
                "success": False,
                "error": "La déclaration relative aux droits sur la voix est obligatoire.",
                "code": "voice_rights_declaration_required",
            }), 400
        if not voice_sample:
            return jsonify({"success": False, "error": "Ajoutez un échantillon vocal."}), 400

        sample_bytes = voice_sample.read(MAX_CLONE_BYTES + 1)
        try:
            sample_duration = validate_audio(
                sample_bytes,
                voice_sample.filename or "voix.webm",
                min_seconds=10,
                max_seconds=90,
                max_bytes=MAX_CLONE_BYTES,
                duration_hint=request.form.get("voice_sample_duration_sec"),
            )
            fish_voice = create_instant_clone(
                name=name,
                audio_bytes=sample_bytes,
                filename=voice_sample.filename or "voix.webm",
                mime_type=voice_sample.mimetype,
                transcript=transcript or None,
            )
            voice = create_voice(
                center_account_id,
                name=name,
                fish_reference_id=fish_voice["reference_id"],
                source="clone",
                consent_statement=RIGHTS_DECLARATION,
                sample_sha256=audio_sha256(sample_bytes),
                sample_duration_sec=sample_duration,
                language="fr",
                fish_state=fish_voice.get("state"),
            )
        except Exception as exc:
            return _voice_error_response(exc)
        return jsonify({"success": True, "voice": voice}), 201

    @hr_bp.route("/api/hr/ai-voices/import", methods=["POST"])
    def import_ai_voice_route():
        center_account_id, denied = _voice_center_id()
        if denied:
            return denied
        from repositories.ai_voice_repository import create_voice
        from services.fish_voice_service import (
            RIGHTS_DECLARATION,
            verify_reference_id,
        )

        name = str(request.form.get("name") or "").strip()[:80]
        reference_id = str(request.form.get("fish_reference_id") or "").strip()
        rights_declared = str(request.form.get("rights_declaration_confirmed") or "").lower() == "true"
        if not name or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", reference_id):
            return jsonify({"success": False, "error": "Nom ou identifiant Fish Audio invalide."}), 400
        if not rights_declared:
            return jsonify({
                "success": False,
                "error": "La déclaration relative aux droits sur la voix est obligatoire.",
                "code": "voice_rights_declaration_required",
            }), 400
        try:
            fish_voice = verify_reference_id(reference_id)
            voice = create_voice(
                center_account_id,
                name=name,
                fish_reference_id=fish_voice["reference_id"],
                source="import",
                consent_statement=RIGHTS_DECLARATION,
                language="fr",
                fish_state=fish_voice.get("state"),
            )
        except Exception as exc:
            return _voice_error_response(exc)
        return jsonify({"success": True, "voice": voice}), 201

    @hr_bp.route("/api/hr/ai-voices/<int:voice_id>/calibrate", methods=["POST"])
    def calibrate_ai_voice_route(voice_id):
        center_account_id, denied = _voice_center_id()
        if denied:
            return denied
        from repositories.ai_voice_repository import get_voice, update_calibration
        from services.fish_voice_service import (
            MAX_CALIBRATION_BYTES,
            transcribe_and_measure_wpm,
            validate_audio,
        )

        if get_voice(center_account_id, voice_id) is None:
            return _tenant_resource_not_found()
        sample = request.files.get("calibration_sample")
        if not sample:
            return jsonify({"success": False, "error": "Ajoutez un enregistrement de calibrage."}), 400
        sample_bytes = sample.read(MAX_CALIBRATION_BYTES + 1)
        try:
            validate_audio(
                sample_bytes,
                sample.filename or "calibrage.webm",
                min_seconds=60,
                max_seconds=600,
                max_bytes=MAX_CALIBRATION_BYTES,
                duration_hint=request.form.get("calibration_sample_duration_sec"),
            )
            analysis = transcribe_and_measure_wpm(
                audio_bytes=sample_bytes,
                filename=sample.filename or "calibrage.webm",
                mime_type=sample.mimetype,
                language="fr",
            )
            requested_speed = request.form.get("playback_speed")
            playback_speed = float(requested_speed or 1.0)
            if not 0.5 <= playback_speed <= 2.0:
                raise ValueError("Vitesse invalide")
            voice = update_calibration(
                center_account_id,
                voice_id,
                measured_wpm=analysis["words_per_minute"],
                playback_speed=playback_speed,
            )
        except ValueError:
            return jsonify({"success": False, "error": "La vitesse doit être comprise entre 0,5 et 2."}), 400
        except Exception as exc:
            return _voice_error_response(exc)
        return jsonify({"success": True, "voice": voice, "analysis": analysis}), 200

    @hr_bp.route("/api/hr/ai-voices/<int:voice_id>", methods=["PATCH"])
    def update_ai_voice_route(voice_id):
        center_account_id, denied = _voice_center_id()
        if denied:
            return denied
        from repositories.ai_voice_repository import update_speed

        data = request.get_json(silent=True) or {}
        try:
            speed = float(data.get("playback_speed"))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Vitesse invalide."}), 400
        if not 0.5 <= speed <= 2.0:
            return jsonify({"success": False, "error": "La vitesse doit être comprise entre 0,5 et 2."}), 400
        voice = update_speed(center_account_id, voice_id, speed)
        if voice is None:
            return _tenant_resource_not_found()
        return jsonify({"success": True, "voice": voice}), 200

    @hr_bp.route("/api/hr/ai-voices/<int:voice_id>/preview", methods=["POST"])
    def preview_ai_voice_route(voice_id):
        center_account_id, denied = _voice_center_id()
        if denied:
            return denied
        from repositories.ai_voice_repository import get_voice
        from services.fish_voice_service import synthesize_preview

        voice = get_voice(center_account_id, voice_id)
        if voice is None:
            return _tenant_resource_not_found()
        data = request.get_json(silent=True) or {}
        text = str(data.get("text") or "Bonjour, voici un aperçu de ma voix pour vos prochains cours.").strip()[:500]
        try:
            speed = float(data.get("playback_speed") or voice.get("playback_speed") or 1.0)
            if not 0.5 <= speed <= 2.0:
                raise ValueError
            audio = synthesize_preview(
                reference_id=voice["fish_reference_id"],
                speed=speed,
                text=text,
            )
        except ValueError:
            return jsonify({"success": False, "error": "Vitesse invalide."}), 400
        except Exception as exc:
            return _voice_error_response(exc)
        return send_file(io.BytesIO(audio), mimetype="audio/mpeg", download_name="apercu-voix.mp3")

    @hr_bp.route("/api/hr/ai-voices/<int:voice_id>", methods=["DELETE"])
    def archive_ai_voice_route(voice_id):
        center_account_id, denied = _voice_center_id()
        if denied:
            return denied
        from repositories.ai_voice_repository import archive_voice

        if not archive_voice(center_account_id, voice_id):
            return _tenant_resource_not_found()
        return jsonify({"success": True, "archived": True}), 200

    @hr_bp.before_request
    def check_hr_enabled():
        from flask import request as req
        # Ces endpoints restent accessibles même si HR est désactivé
        always_allowed = {"hr.get_hr_enabled", "hr.auto_schedule"}
        if req.endpoint in always_allowed:
            return None
        if not HR_ENABLED:
            return jsonify({"success": False, "error": "Feature non disponible"}), 404

    def _require_admin():
        if not session.get("is_admin"):
            return jsonify({"success": False, "error": "Accès refusé"}), 403
        return None

    def _admin_account_type():
        # Seuls les types explicitement émis par l'authentification sont
        # reconnus. Une session ancienne/incomplète doit se reconnecter.
        return str(session.get("admin_account_type") or "").strip().lower()

    def _training_center_account_id():
        value = session.get("admin_account_id")
        if value is None or isinstance(value, bool):
            return None
        try:
            account_id = int(value)
        except (TypeError, ValueError):
            return None
        return account_id if account_id > 0 else None

    def _tenant_resource_not_found():
        # Même réponse pour une ressource absente et une ressource d'un autre
        # centre afin de ne pas révéler son existence.
        return jsonify({"success": False, "error": "Ressource introuvable"}), 404

    def _test_clock_center_id():
        denied = _require_admin()
        if denied:
            return None, denied
        center_account_id = _training_center_account_id()
        if _admin_account_type() != "training_center" or center_account_id is None:
            return None, (jsonify({"success": False, "error": "Compte centre requis"}), 403)

        account = get_training_center_by_id(center_account_id) or {}
        verified_email = str(
            getattr(g, "supabase_auth_claims", {}).get("email")
            or account.get("username")
            or ""
        ).strip().lower()
        if verified_email != "newpiprod@gmail.com":
            return None, (jsonify({
                "success": False,
                "error": "Horloge de test non autorisée pour ce compte",
                "code": "TEST_CLOCK_FORBIDDEN",
            }), 403)
        return center_account_id, None

    def _test_clock_payload(center_account_id):
        from services.time_service import get_center_test_time

        simulated_now = get_center_test_time(center_account_id)
        real_now = datetime.now(FRANCE_TZ)
        return {
            "success": True,
            "active": simulated_now is not None,
            "current_time": (simulated_now or real_now).isoformat(),
            "real_time": real_now.isoformat(),
            "timezone": "Europe/Paris",
        }

    @hr_bp.route("/api/hr/test-clock", methods=["GET"])
    def get_test_clock():
        center_account_id, denied = _test_clock_center_id()
        if denied:
            return denied
        return jsonify(_test_clock_payload(center_account_id)), 200

    @hr_bp.route("/api/hr/test-clock", methods=["PUT"])
    def update_test_clock():
        center_account_id, denied = _test_clock_center_id()
        if denied:
            return denied
        raw_value = str((request.get_json(silent=True) or {}).get("datetime") or "").strip()
        try:
            requested_time = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
            if requested_time.tzinfo is None:
                requested_time = FRANCE_TZ.localize(requested_time)
            requested_time = requested_time.astimezone(FRANCE_TZ)
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Date ou heure invalide"}), 400

        real_now = datetime.now(FRANCE_TZ)
        if abs((requested_time - real_now).total_seconds()) > 366 * 2 * 24 * 3600:
            return jsonify({
                "success": False,
                "error": "L’heure de test doit rester à moins de deux ans de l’heure réelle",
            }), 400

        from repositories.test_clock_repository import (
            list_center_platform_ids,
            set_center_test_clock,
        )

        set_center_test_clock(center_account_id, requested_time, real_now)
        platform_ids = list_center_platform_ids(center_account_id)
        # Le réglage est immédiatement observable : nul besoin d'attendre le
        # prochain passage du planificateur périodique.
        run_scheduler_tick(platform_ids=platform_ids)
        reminder_results = process_due_reminders(
            base_url=(
                os.environ.get("FRONTEND_PUBLIC_URL")
                or os.environ.get("PLATFORM_1_FRONTEND_URL")
            ),
            now=requested_time,
            platform_ids=platform_ids,
        )
        payload = _test_clock_payload(center_account_id)
        payload["scheduler"] = {
            "platform_count": len(platform_ids),
            "reminder_count": len(reminder_results or []),
        }
        return jsonify(payload), 200

    @hr_bp.route("/api/hr/test-clock", methods=["DELETE"])
    def reset_test_clock():
        center_account_id, denied = _test_clock_center_id()
        if denied:
            return denied
        from repositories.test_clock_repository import delete_center_test_clock

        delete_center_test_clock(center_account_id)
        return jsonify(_test_clock_payload(center_account_id)), 200

    def _require_hr_resource_access(resource_type, resource_id):
        """Fail-closed tenant check, reusable for URL and request-body ids."""
        account_type = _admin_account_type()
        if account_type in _HR_SUPERADMIN_ACCOUNT_TYPES:
            return None
        if account_type != "training_center":
            return _tenant_resource_not_found()

        center_account_id = _training_center_account_id()
        if center_account_id is None:
            return _tenant_resource_not_found()

        try:
            allowed = hr_resource_belongs_to_center(
                resource_type,
                resource_id,
                center_account_id,
            )
        except Exception:
            logger.warning(
                "HR_TENANT_SCOPE_LOOKUP_FAILED resource_type=%s resource_id=%s center_account_id=%s",
                resource_type,
                resource_id,
                center_account_id,
                exc_info=True,
            )
            return _tenant_resource_not_found()
        if not allowed:
            logger.warning(
                "HR_TENANT_SCOPE_DENIED resource_type=%s resource_id=%s center_account_id=%s",
                resource_type,
                resource_id,
                center_account_id,
            )
            return _tenant_resource_not_found()
        return None

    @hr_bp.before_request
    def enforce_hr_tenant_scope():
        """Resolve every URL resource before its route can cause side effects."""
        if not session.get("is_admin"):
            return None

        account_type = _admin_account_type()
        if account_type in _HR_SUPERADMIN_ACCOUNT_TYPES:
            return None
        if account_type != "training_center" or _training_center_account_id() is None:
            return _tenant_resource_not_found()

        view_args = request.view_args or {}
        resource_keys = (
            ("platform_id", "platform"),
            ("folder_id", "folder"),
            ("document_id", "document"),
            ("module_id", "module"),
        )
        for argument_name, resource_type in resource_keys:
            if argument_name in view_args:
                denied = _require_hr_resource_access(resource_type, view_args[argument_name])
                if denied:
                    return denied
        return None

    def _require_global_hr_admin():
        denied = _require_admin()
        if denied:
            return denied
        if _admin_account_type() not in _HR_SUPERADMIN_ACCOUNT_TYPES:
            return jsonify({"success": False, "error": "Accès superadmin requis"}), 403
        return None

    def _now_str():
        return datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")

    def _platform_access_clause(alias="pc"):
        if session.get("admin_account_type") == "training_center":
            return f"{alias}.center_account_id = ?", [session.get("admin_account_id")]
        return "1 = 1", []

    def _get_accessible_platform(cursor, platform_id):
        scope_sql, scope_params = _platform_access_clause("pc")
        cursor.execute(
            f"SELECT pc.id, pc.name FROM platform_config pc WHERE pc.id = ? AND {scope_sql}",
            [platform_id] + scope_params,
        )
        return cursor.fetchone()

    def _ensure_student_attendance_records(cursor):
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS student_attendance_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform_id INTEGER NOT NULL,
                student_profile_id INTEGER NOT NULL,
                course_date TEXT NOT NULL,
                slots_json TEXT NOT NULL DEFAULT '[]',
                total_minutes INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'absent',
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(platform_id, student_profile_id, course_date)
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_student_attendance_platform_date ON student_attendance_records(platform_id, course_date)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_student_attendance_student ON student_attendance_records(student_profile_id)"
        )

    def _parse_course_date(value):
        raw = str(value or "").strip()
        if not raw:
            return datetime.now(FRANCE_TZ).strftime("%Y-%m-%d")
        try:
            return datetime.strptime(raw, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            raise ValueError("Date du cours invalide")

    def _attendance_week_bounds(value):
        date_value = datetime.strptime(_parse_course_date(value), "%Y-%m-%d")
        week_start = date_value - timedelta(days=date_value.weekday())
        week_end = week_start + timedelta(days=6)
        return week_start.strftime("%Y-%m-%d"), week_end.strftime("%Y-%m-%d")

    def _time_to_minutes(value):
        raw = str(value or "").strip()
        if not re.match(r"^\d{2}:\d{2}$", raw):
            raise ValueError("Les heures doivent être au format HH:MM")
        hours, minutes = [int(part) for part in raw.split(":")]
        if hours > 23 or minutes > 59:
            raise ValueError("Heure invalide")
        return hours * 60 + minutes

    def _normalize_attendance_slots(raw_slots):
        slots = []
        total_minutes = 0
        for raw_slot in raw_slots or []:
            start = str((raw_slot or {}).get("start") or "").strip()
            end = str((raw_slot or {}).get("end") or "").strip()
            if not start and not end:
                continue
            start_minutes = _time_to_minutes(start)
            end_minutes = _time_to_minutes(end)
            if end_minutes <= start_minutes:
                raise ValueError("L'heure de départ doit être après l'heure d'arrivée")
            slots.append({"start": start, "end": end})
            total_minutes += end_minutes - start_minutes
        return slots, total_minutes

    def _serialize_attendance_row(row, slots_index=4):
        slots = []
        try:
            slots = json.loads(row[slots_index] or "[]")
        except Exception:
            slots = []
        return {
            "id": row[0],
            "platform_id": row[1],
            "student_profile_id": row[2],
            "course_date": row[3],
            "slots": slots,
            "total_minutes": int(row[slots_index + 1] or 0),
            "status": row[slots_index + 2] or "absent",
            "notes": row[slots_index + 3] or "",
            "created_at": row[slots_index + 4],
            "updated_at": row[slots_index + 5],
            "source": "saved",
        }

    def _get_azure_audio_clients():
        """Retourne (blob_service_client, container_client) pour le conteneur audio P1"""
        connection_string = os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING")
        if not connection_string:
            return None, None
        container_name = os.environ.get("AZURE_AUDIO_CONTAINER", "formationaudio-dev")
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client(container_name)
        return blob_service_client, container_client

    def _get_azure_pdf_info():
        """Retourne (pdf_filename, pdf_url) depuis le container Azure formationpdf"""
        connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            return None, None
        try:
            container_name = os.environ.get("AZURE_STORAGE_CONTAINER", "formationpdf")
            blob_service_client = BlobServiceClient.from_connection_string(connection_string)
            container_client = blob_service_client.get_container_client(container_name)
            _, blob = _summarize_blobs(container_client)
            if not blob:
                return None, None
            account_name = blob_service_client.account_name
            account_key = blob_service_client.credential.account_key
            expiry = datetime.now(timezone.utc) + timedelta(hours=2)
            sas_token = generate_blob_sas(
                account_name=account_name,
                container_name=container_name,
                blob_name=blob.name,
                account_key=account_key,
                permission=BlobSasPermissions(read=True),
                expiry=expiry,
            )
            url = f"https://{account_name}.blob.core.windows.net/{container_name}/{blob.name}?{sas_token}"
            return blob.name, url
        except Exception as e:
            logger.warning(f"⚠️ Erreur lecture PDF Azure: {e}")
            return None, None

    def _make_pdf_url(platform_id, filename):
        """Build a short-lived read URL for a known PDF blob without scanning Azure."""
        if not filename:
            return None
        connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            return None
        try:
            pinfo = _get_platform_info(int(platform_id))
            container_name = pinfo["pdf_container"]
            blob_service_client = BlobServiceClient.from_connection_string(connection_string)
            expiry = datetime.now(timezone.utc) + timedelta(hours=2)
            sas_token = generate_blob_sas(
                account_name=blob_service_client.account_name,
                container_name=container_name,
                blob_name=filename,
                account_key=blob_service_client.credential.account_key,
                permission=BlobSasPermissions(read=True),
                expiry=expiry,
            )
            return f"https://{blob_service_client.account_name}.blob.core.windows.net/{container_name}/{filename}?{sas_token}"
        except Exception as e:
            logger.warning(f"⚠️ Erreur génération URL PDF P{platform_id}: {e}")
            return None

    # ─── GET /api/hr/formation-modules ───────────────────────────────────
    # Liste des modules maîtres disponibles pour créer une nouvelle plateforme.
    # Principe "1 RNCP = 1 module durable" : un module est un produit fini
    # autonome (sortie d'une pipeline), indépendant des plateformes qui le
    # consomment. Le module pointe vers sa plateforme source (d'où sont clonés
    # les blobs pour chaque nouvelle promo).
    def _formation_module_is_reusable(module):
        base_ready = (
            module.get("status") == "validated"
            and int(module.get("nb_folders") or 0) > 0
            and module.get("voice_type") != "mock"
        )
        schema_version = int(module.get("schedule_schema_version") or 1)
        if not base_ready or schema_version < 2:
            return base_ready

        expected_days = int(module.get("nb_days") or 0)
        if (
            expected_days <= 0
            or int(module.get("module_day_count") or 0) != expected_days
            or int(module.get("nb_folders") or 0) < expected_days
            or int(module.get("asset_count") or 0) <= 0
        ):
            return False
        reusable_at = module.get("reusable_at")
        if not reusable_at:
            return False
        if not isinstance(reusable_at, datetime):
            try:
                reusable_at = datetime.fromisoformat(
                    str(reusable_at).replace("Z", "+00:00")
                )
            except ValueError:
                return False
        if reusable_at.tzinfo is None:
            reusable_at = FRANCE_TZ.localize(reusable_at)
        return reusable_at.astimezone(FRANCE_TZ) <= datetime.now(FRANCE_TZ)

    @hr_bp.route("/api/hr/formation-modules", methods=["GET"])
    def list_formation_modules():
        """Modules formation disponibles (regroupement canonique des pipelines terminées)."""
        denied = _require_admin()
        if denied:
            return denied
        try:
            if _hr_pipeline_reads_use_postgres():
                scope_to_center = session.get("admin_account_type") == "training_center"
                rows = list_hr_formation_modules(
                    session.get("admin_account_id"),
                    scope_to_center=scope_to_center,
                )
                modules = [{
                    "id": row["id"],
                    "rncp_code": row.get("rncp_code") or "",
                    "tp_name": row.get("tp_name"),
                    "version": row.get("version"),
                    "status": row.get("status"),
                    "source_pipeline_job_id": row.get("source_pipeline_job_id"),
                    "source_platform_id": row.get("source_platform_id"),
                    "created_at": row.get("created_at"),
                    "total_hours": row.get("total_hours"),
                    "nb_folders": row.get("nb_folders", 0),
                    "source_platform_name": row.get("source_platform_name"),
                    "voice_type": row.get("voice_type"),
                    "voice_updated_at": row.get("voice_updated_at"),
                    "teacher_name": row.get("teacher_name") or "",
                    "teacher_color": row.get("teacher_color") or "violet",
                    "asset_namespace": row.get("asset_namespace") or "",
                    "immutable": bool(row.get("immutable")),
                    "nb_days": row.get("nb_days"),
                    "schedule_schema_version": int(
                        row.get("schedule_schema_version") or 1
                    ),
                    "schedule_hash": row.get("schedule_hash"),
                    "schedule_locked_at": row.get("schedule_locked_at"),
                    "reusable_at": row.get("reusable_at"),
                    "module_day_count": int(row.get("module_day_count") or 0),
                    "asset_count": int(row.get("asset_count") or 0),
                    "active_use_count": int(row.get("active_use_count") or 0),
                    "completed_use_count": int(row.get("completed_use_count") or 0),
                    "storage_mode": "shared",
                    "schedule": row.get("schedule"),
                    "reusable": _formation_module_is_reusable(row),
                } for row in rows]
                return jsonify({"success": True, "modules": modules}), 200

            conn = get_db_connection()
            cursor = conn.cursor()
            module_scope_sql, module_scope_params = _module_scope_clause("m")
            cursor.execute("""
                SELECT m.id, m.rncp_code, m.tp_name, m.version, m.status,
                       m.source_pipeline_job_id, m.source_platform_id, m.created_at,
                       (SELECT COUNT(*) FROM cours_folders WHERE platform_id = m.source_platform_id) AS nb_folders,
                       pc.name AS source_platform_name,
                       m.voice_type, m.voice_updated_at,
                       m.teacher_name, m.teacher_color, m.asset_namespace,
                       COALESCE(m.immutable, 0),
                       (
                           SELECT COUNT(*) FROM formation_module_assets asset
                           WHERE asset.module_id = m.id AND asset.status = 'ready'
                       ) AS asset_count,
                       (
                           SELECT COUNT(*) FROM platform_config usage_platform
                           WHERE (usage_platform.source_module_id = m.id OR usage_platform.id = m.source_platform_id)
                             AND usage_platform.lifecycle_status = 'active'
                       ) AS active_use_count,
                       (
                           SELECT COUNT(*) FROM platform_config usage_platform
                           WHERE (usage_platform.source_module_id = m.id OR usage_platform.id = m.source_platform_id)
                             AND usage_platform.lifecycle_status IN ('completed', 'archived')
                       ) AS completed_use_count,
                       m.nb_days, m.schedule_schema_version, m.schedule_hash,
                       m.schedule_locked_at, m.reusable_at,
                       (
                           SELECT COUNT(*) FROM formation_module_days module_day
                           WHERE module_day.module_id = m.id
                             AND module_day.center_account_id = m.center_account_id
                       ) AS module_day_count
                FROM formation_modules m
                LEFT JOIN platform_config pc ON pc.id = m.source_platform_id
                WHERE m.status != 'archived'
                  AND """ + module_scope_sql + """
                ORDER BY m.created_at DESC
            """, module_scope_params)
            rows = cursor.fetchall()
            ensure_course_schedule_tables(cursor)
            source_ids = sorted({r[6] for r in rows if r[6]})
            schedules_by_platform = {}
            if source_ids:
                placeholders = ",".join("?" for _ in source_ids)
                cursor.execute(
                    f"""
                    SELECT platform_id, total_training_days, weekly_course_count,
                           weekdays_json, start_time
                    FROM course_schedule_config
                    WHERE platform_id IN ({placeholders})
                    """,
                    source_ids,
                )
                for platform_id, total_days, weekly_count, weekdays_json, start_time in cursor.fetchall():
                    try:
                        weekdays = json.loads(weekdays_json or "[]")
                    except Exception:
                        weekdays = []
                    schedules_by_platform[platform_id] = {
                        "total_training_days": total_days,
                        "weekly_course_count": weekly_count,
                        "weekdays": weekdays,
                        "start_time": start_time,
                    }
            conn.close()
            modules = [{
                "id": r[0],
                "rncp_code": r[1] or "",
                "tp_name": r[2],
                "version": r[3],
                "status": r[4],
                "source_pipeline_job_id": r[5],
                "source_platform_id": r[6],
                "created_at": r[7],
                "nb_folders": r[8],
                "source_platform_name": r[9],
                "voice_type": r[10],
                "voice_updated_at": r[11],
                "teacher_name": r[12] or "",
                "teacher_color": r[13] or "violet",
                "asset_namespace": r[14] or "",
                "immutable": bool(r[15]),
                "nb_days": r[19],
                "schedule_schema_version": int(r[20] or 1),
                "schedule_hash": r[21],
                "schedule_locked_at": r[22],
                "reusable_at": r[23],
                "module_day_count": int(r[24] or 0),
                "asset_count": int(r[16] or 0),
                "active_use_count": int(r[17] or 0),
                "completed_use_count": int(r[18] or 0),
                "storage_mode": "shared",
                "schedule": schedules_by_platform.get(r[6]),
                "reusable": False,
            } for r in rows]
            for module in modules:
                module["reusable"] = _formation_module_is_reusable(module)
            return jsonify({"success": True, "modules": modules}), 200
        except Exception as e:
            logger.error(f"❌ Erreur list formation-modules: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── DELETE /api/hr/formation-modules/<id> ────────────────────────────
    # Suppression d'un module catalogue. Refuse si une plateforme l'utilise
    # encore (platform_config.source_module_id), pour éviter les promos
    # orphelines. La pipeline source (formation_pipeline_jobs) et la
    # plateforme source (platform_config) sont préservées — un module est
    # juste l'enveloppe "produit fini" autour d'une pipeline. Sa suppression
    # n'efface ni les cours, ni les blobs, ni l'historique.
    @hr_bp.route("/api/hr/formation-modules/<int:module_id>", methods=["DELETE"])
    def delete_formation_module(module_id):
        """Supprimer un module du catalogue. Bloqué si des plateformes l'utilisent."""
        denied = _require_admin()
        if denied:
            return denied
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            module_scope_sql, module_scope_params = _module_scope_clause("formation_modules")

            cursor.execute(
                f"SELECT id, tp_name, version FROM formation_modules WHERE id = ? AND {module_scope_sql}",
                [module_id] + module_scope_params,
            )
            row = cursor.fetchone()
            if not row:
                conn.close()
                return jsonify({"success": False, "error": "Module introuvable"}), 404
            mod_tp, mod_version = row[1], row[2]

            # Vérifie qu'aucune plateforme n'utilise ce module comme source.
            cursor.execute(
                "SELECT id, name FROM platform_config WHERE source_module_id = ?",
                (module_id,),
            )
            using = cursor.fetchall()
            if using:
                conn.close()
                names = ", ".join(p[1] for p in using)
                return jsonify({
                    "success": False,
                    "error": (
                        f"{len(using)} plateforme(s) utilisent encore ce module : {names}. "
                        f"Supprime-les (ou bascule-les sur un autre module) avant de retirer le module."
                    ),
                    "blocking_platforms": [{"id": p[0], "name": p[1]} for p in using],
                }), 409

            cursor.execute("DELETE FROM formation_modules WHERE id = ?", (module_id,))
            conn.commit()
            conn.close()
            logger.info(f"🗑️  Module {module_id} ({mod_tp} {mod_version}) supprimé du catalogue")
            return jsonify({
                "success": True,
                "module_id": module_id,
                "tp_name": mod_tp,
                "version": mod_version,
            }), 200
        except Exception as e:
            logger.error(f"❌ Erreur delete formation-module {module_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── GET /api/hr/formations ──────────────────────────────────────────
    # Legacy : liste des jobs pipeline (kept pour compat backward si autre code
    # l'appelle encore). La modale "Nouvelle plateforme" utilise désormais
    # /api/hr/formation-modules à la place.
    @hr_bp.route("/api/hr/formations", methods=["GET"])
    def list_formations():
        """Liste les formations pipeline (completed ou en cours) pour le select de création plateforme."""
        denied = _require_admin()
        if denied:
            return denied
        try:
            if _hr_pipeline_reads_use_postgres():
                scope_to_center = session.get("admin_account_type") == "training_center"
                rows = list_hr_formations(
                    session.get("admin_account_id"),
                    scope_to_center=scope_to_center,
                )
                formations = [{
                    "id": row["id"],
                    "tp_name": row.get("tp_name"),
                    "rncp_code": row.get("rncp_code") or "",
                    "total_hours": row.get("total_hours"),
                    "nb_days": row.get("nb_days"),
                    "status": row.get("status"),
                    "platform_id": row.get("platform_id"),
                    "platform_name": row.get("platform_name") or f"Plateforme {row.get('platform_id')}",
                    "nb_folders": row.get("nb_folders", 0),
                    "created_at": row.get("created_at"),
                    "reusable": row.get("status") == "completed" and row.get("nb_folders", 0) > 0,
                } for row in rows]
                return jsonify({"success": True, "formations": formations}), 200

            conn = get_db_connection()
            cursor = conn.cursor()
            platform_where = ""
            platform_params = []
            if session.get("admin_account_type") == "training_center":
                platform_where = "WHERE pc.center_account_id = ?"
                platform_params.append(session.get("admin_account_id"))
            cursor.execute("""
                SELECT j.id, j.tp_name, j.rncp_code, j.total_hours, j.nb_days,
                       j.status, j.platform_id, pc.name,
                       (SELECT COUNT(*) FROM cours_folders WHERE platform_id = j.platform_id) as nb_folders,
                       j.created_at
                FROM formation_pipeline_jobs j
                LEFT JOIN platform_config pc ON pc.id = j.platform_id
                """ + platform_where + """
                ORDER BY j.created_at DESC
            """, platform_params)
            rows = cursor.fetchall()
            conn.close()
            formations = [{
                "id": r[0],
                "tp_name": r[1],
                "rncp_code": r[2] or "",
                "total_hours": r[3],
                "nb_days": r[4],
                "status": r[5],
                "platform_id": r[6],
                "platform_name": r[7] or f"Plateforme {r[6]}",
                "nb_folders": r[8],
                "created_at": r[9],
                "reusable": r[5] == "completed" and r[8] > 0,
            } for r in rows]
            return jsonify({"success": True, "formations": formations}), 200
        except Exception as e:
            logger.error(f"❌ Erreur list formations: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── GET /api/hr/platforms ────────────────────────────────────────────
    @hr_bp.route("/api/hr/platforms", methods=["GET"])
    def get_platforms():
        """Vue d'ensemble des 3 plateformes avec stats et alertes"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            include_blob_stats = _bool_arg("include_blob_stats", default=False)
            repair_on_load = _bool_arg("repair", default=HR_DASHBOARD_REPAIR_ON_LOAD)
            if _admin_account_type() == "training_center":
                # Les réparations sont des UPDATE de maintenance globaux ; un
                # centre ne peut jamais les déclencher pour les autres tenants.
                repair_on_load = False
            postgres_dashboard_rows = None
            if _hr_pipeline_reads_use_postgres():
                # GET reads are side-effect free in the authoritative store.
                # Legacy repair remains available only on the explicit SQLite
                # path and must be handled by a migration/admin operation in PG.
                repair_on_load = False
                scope_to_center = session.get("admin_account_type") == "training_center"
                postgres_dashboard_rows = list_hr_platforms(
                    session.get("admin_account_id"),
                    scope_to_center=scope_to_center,
                )
                conn = None
                cursor = None
            else:
                conn = get_db_connection()
                cursor = conn.cursor()

            if repair_on_load:
                # Ces réparations écrivent dans SQLite. Elles sont utiles en
                # maintenance, mais ne doivent pas bloquer le simple affichage du
                # dashboard pendant qu'un pipeline écrit déjà en parallèle.
                cursor.execute("""
                    UPDATE platform_config
                    SET source_formation_id = (
                        SELECT j.id
                        FROM formation_pipeline_jobs j
                        WHERE j.platform_id = platform_config.id
                        ORDER BY j.id DESC
                        LIMIT 1
                    )
                    WHERE source_formation_id IS NULL
                      AND EXISTS (
                        SELECT 1
                        FROM formation_pipeline_jobs j
                        WHERE j.platform_id = platform_config.id
                      )
                """)

                cursor.execute("""
                    UPDATE platform_config
                    SET status = 'ready'
                    WHERE status = 'pending'
                      AND id IN (
                        SELECT j.platform_id
                        FROM formation_pipeline_jobs j
                        WHERE j.status IN (
                                'text_ready',
                                'audio_running',
                                'audio_launched',
                                'audio_completed',
                                'completed'
                            )
                           OR j.auto_pilot_step = 'done'
                      )
                """)
                if cursor.rowcount > 0:
                    logger.info(f"🔧 Auto-repair : {cursor.rowcount} plateforme(s) stuck pending → ready")

                cursor.execute("""
                    UPDATE platform_config
                    SET status = 'error'
                    WHERE status = 'pending'
                      AND source_formation_id IS NOT NULL
                      AND (
                        EXISTS (
                            SELECT 1
                            FROM formation_pipeline_jobs j
                            WHERE j.id = platform_config.source_formation_id
                              AND (
                                j.auto_pilot_error IS NOT NULL
                                OR j.status IN ('error', 'audio_error')
                                OR j.auto_pilot_step = 'stopped'
                              )
                        )
                        OR NOT EXISTS (
                            SELECT 1
                            FROM formation_pipeline_jobs j
                            WHERE j.id = platform_config.source_formation_id
                        )
                      )
                """)
                if cursor.rowcount > 0:
                    logger.info(f"🔧 Auto-repair : {cursor.rowcount} plateforme(s) stuck pending → error")

                cursor.execute("""
                    UPDATE platform_config
                    SET status = 'error'
                    WHERE status = 'pending'
                      AND source_formation_id IS NULL
                      AND updated_at IS NOT NULL
                      AND datetime(updated_at) < datetime('now', '-2 hours')
                """)
                if cursor.rowcount > 0:
                    logger.info(f"🔧 Auto-repair : {cursor.rowcount} plateforme(s) orphan pending → error")

                if conn.total_changes > 0:
                    conn.commit()

            if postgres_dashboard_rows is None:
                platform_where = ""
                platform_params = []
                if session.get("admin_account_type") == "training_center":
                    platform_where = "WHERE pc.center_account_id = ?"
                    platform_params.append(session.get("admin_account_id"))

                cursor.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'course_sessions'"
                )
                sqlite_has_course_sessions = cursor.fetchone() is not None
                cursor.execute("PRAGMA table_info(platform_config)")
                sqlite_platform_columns = {row[1] for row in cursor.fetchall()}
                lifecycle_status_sql = (
                    "pc.lifecycle_status" if "lifecycle_status" in sqlite_platform_columns else "'active'"
                )
                completed_at_sql = (
                    "pc.completed_at" if "completed_at" in sqlite_platform_columns else "NULL"
                )
                archived_at_sql = (
                    "pc.archived_at" if "archived_at" in sqlite_platform_columns else "NULL"
                )
                asset_binding_mode_sql = (
                    "pc.asset_binding_mode" if "asset_binding_mode" in sqlite_platform_columns else "'canonical'"
                )
                center_platform_number_sql = (
                    "pc.center_platform_number"
                    if "center_platform_number" in sqlite_platform_columns
                    else """
                        CASE
                            WHEN pc.center_account_id IS NULL THEN pc.id
                            ELSE (
                                SELECT COUNT(*)
                                FROM platform_config numbered_pc
                                WHERE numbered_pc.center_account_id = pc.center_account_id
                                  AND numbered_pc.id <= pc.id
                            )
                        END
                    """
                )
                total_session_sql = (
                    "(SELECT COUNT(*) FROM course_sessions cs WHERE cs.platform_id = pc.id)"
                    if sqlite_has_course_sessions else "0"
                )
                remaining_session_sql = (
                    """(SELECT COUNT(*) FROM course_sessions cs
                         WHERE cs.platform_id = pc.id
                           AND cs.status IN ('planned', 'active')
                           AND cs.scheduled_at >= CURRENT_TIMESTAMP)"""
                    if sqlite_has_course_sessions else "0"
                )

                cursor.execute(f"""
                    SELECT
                        pc.id,
                        pc.name,
                        pc.teacher_name,
                        pc.teacher_color,
                        pc.creation_request_id,
                        pc.slug,
                        pc.upload_locked,
                        pc.pdf_filename,
                        pc.pdf_uploaded_at,
                        pc.updated_at,
                        pc.status,
                        pc.source_formation_id,
                        pc.source_module_id,
                        pc.center_account_id,
                        {center_platform_number_sql} AS center_platform_number,
                        COALESCE(tca.slug, 'le-socrate') AS center_slug,
                        COALESCE(fm.rncp_code, fpj.rncp_code) AS source_rncp_code,
                        COALESCE(fm.tp_name, fpj.tp_name) AS source_tp_name,
                        fpj.status AS pipeline_status,
                        fpj.auto_pilot_step AS pipeline_auto_pilot_step,
                        fpj.auto_pilot_error AS pipeline_auto_pilot_error,
                        fpj.auto_pilot_enabled AS pipeline_auto_pilot_enabled,
                        {lifecycle_status_sql} AS lifecycle_status,
                        {completed_at_sql} AS completed_at,
                        {archived_at_sql} AS archived_at,
                        {asset_binding_mode_sql} AS asset_binding_mode,
                        {total_session_sql} AS total_session_count,
                        {remaining_session_sql} AS remaining_session_count
                    FROM platform_config pc
                    LEFT JOIN training_center_accounts tca ON tca.id = pc.center_account_id
                    LEFT JOIN formation_modules fm ON fm.id = pc.source_module_id
                    LEFT JOIN formation_pipeline_jobs fpj ON fpj.id = pc.source_formation_id
                    {platform_where}
                    ORDER BY pc.id
                """, platform_params)
                rows = cursor.fetchall()

                conn.close()
            else:
                rows = [(
                    row["id"],
                    row.get("name"),
                    row.get("teacher_name"),
                    row.get("teacher_color"),
                    row.get("creation_request_id"),
                    row.get("slug"),
                    row.get("upload_locked"),
                    row.get("pdf_filename"),
                    row.get("pdf_uploaded_at"),
                    row.get("updated_at"),
                    row.get("status"),
                    row.get("source_formation_id"),
                    row.get("source_module_id"),
                    row.get("center_account_id"),
                    row.get("center_platform_number"),
                    row.get("center_slug") or "le-socrate",
                    row.get("source_rncp_code"),
                    row.get("source_tp_name"),
                    row.get("pipeline_status"),
                    row.get("pipeline_auto_pilot_step"),
                    row.get("pipeline_auto_pilot_error"),
                    row.get("pipeline_auto_pilot_enabled"),
                    row.get("lifecycle_status"),
                    row.get("completed_at"),
                    row.get("archived_at"),
                    row.get("asset_binding_mode"),
                    row.get("total_session_count"),
                    row.get("remaining_session_count"),
                ) for row in postgres_dashboard_rows]
            # Stats Azure : optionnelles, car scanner les containers peut bloquer
            # le chargement initial du dashboard si Azure Storage répond lentement.
            audio_count_p1 = None
            last_upload_p1 = None
            blob_service_client, container_client = _get_azure_audio_clients() if include_blob_stats else (None, None)
            if include_blob_stats and container_client:
                try:
                    audio_count_p1, latest = _summarize_blobs(container_client)
                    if latest:
                        last_upload_p1 = latest.last_modified.astimezone(FRANCE_TZ).strftime("%Y-%m-%d %H:%M")
                except Exception as e:
                    logger.warning(f"⚠️ Erreur lecture Azure audio: {e}")

            # PDF réel depuis Azure (source de vérité)
            azure_pdf_filename, azure_pdf_url = _get_azure_pdf_info() if include_blob_stats else (None, None)

            platform_ids = [int(row["id"] if isinstance(row, dict) else row[0]) for row in rows]
            schedule_dashboard_states = (
                list_course_schedule_dashboard_states(platform_ids)
                if schedule_store_is_postgres()
                else {}
            )
            platforms = []
            for row in rows:
                (
                    pid,
                    name,
                    teacher_name,
                    teacher_color,
                    creation_request_id,
                    slug,
                    upload_locked,
                    pdf_filename,
                    pdf_uploaded_at,
                    updated_at,
                    p_status,
                    p_source_formation_id,
                    p_source_module_id,
                    p_center_account_id,
                    p_center_platform_number,
                    p_center_slug,
                    p_source_rncp_code,
                    p_source_tp_name,
                    p_pipeline_status,
                    p_pipeline_auto_pilot_step,
                    p_pipeline_auto_pilot_error,
                    p_pipeline_auto_pilot_enabled,
                    p_lifecycle_status,
                    p_completed_at,
                    p_archived_at,
                    p_asset_binding_mode,
                    p_total_session_count,
                    p_remaining_session_count,
                ) = row
                pinfo = _get_platform_info(pid)
                schedule_row = schedule_dashboard_states.get(int(pid))
                course_schedule = None
                if schedule_row:
                    from services.time_service import get_current_simulated_time
                    platform_now = get_current_simulated_time(pid)
                    upcoming_sessions = []
                    for session_row in schedule_row.get("upcoming_sessions") or []:
                        if isinstance(session_row, dict) and session_row.get("id"):
                            upcoming_sessions.append(build_course_session_state(session_row, now=platform_now))
                    past_sessions = []
                    for session_row in schedule_row.get("past_sessions") or []:
                        if isinstance(session_row, dict) and session_row.get("id"):
                            past_sessions.append(build_course_session_state(session_row, now=platform_now))
                    next_session = upcoming_sessions[0] if upcoming_sessions else None
                    if next_session is None and schedule_row.get("session_id"):
                        next_session = build_course_session_state({
                            "id": schedule_row["session_id"],
                            "session_index": schedule_row.get("session_index"),
                            "scheduled_at": schedule_row.get("scheduled_at"),
                            "status": "planned",
                            "audio_generation_status": schedule_row.get("audio_generation_status"),
                            "audio_generation_started_at": schedule_row.get("audio_generation_started_at"),
                            "audio_generation_completed_at": schedule_row.get("audio_generation_completed_at"),
                            "audio_generation_attempts": schedule_row.get("audio_generation_attempts"),
                            "audio_generation_next_retry_at": schedule_row.get("audio_generation_next_retry_at"),
                        }, now=platform_now)
                    course_schedule = {
                        "timezone": schedule_row.get("timezone") or "Europe/Paris",
                        "start_time": schedule_row.get("start_time") or "09:00",
                        "next_session": next_session,
                        "upcoming_sessions": upcoming_sessions or ([next_session] if next_session else []),
                        "past_sessions": past_sessions,
                    }
                # En multi-tenant, toute plateforme en BDD est active
                active = pid == 1 or bool(pinfo.get("backend_url")) or pid >= 4

                # Stats audio pour P2+ depuis leur container Azure
                if pid == 1:
                    audio_count = audio_count_p1
                    last_upload = last_upload_p1
                else:
                    audio_count = None
                    last_upload = None
                    if include_blob_stats and active:
                        try:
                            cs = os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING")
                            if cs:
                                bsc = BlobServiceClient.from_connection_string(cs)
                                cc = bsc.get_container_client(pinfo["audio_container"])
                                audio_count, latest = _summarize_blobs(cc)
                                if latest:
                                    last_upload = latest.last_modified.astimezone(FRANCE_TZ).strftime("%Y-%m-%d %H:%M")
                        except Exception:
                            pass

                # Pour P1, utiliser le vrai fichier Azure comme source de vérité
                # Pour P2+, chercher dans leur container PDF Azure
                if pid == 1:
                    real_pdf_filename = azure_pdf_filename if include_blob_stats else pdf_filename
                    real_pdf_url = azure_pdf_url if include_blob_stats else _make_pdf_url(pid, pdf_filename)
                else:
                    real_pdf_filename = pdf_filename
                    real_pdf_url = _make_pdf_url(pid, pdf_filename)
                    if include_blob_stats and active:
                        try:
                            cs = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
                            if cs:
                                from azure.storage.blob import generate_blob_sas, BlobSasPermissions
                                bsc = BlobServiceClient.from_connection_string(cs)
                                cc = bsc.get_container_client(pinfo["pdf_container"])
                                _, blob = _summarize_blobs(cc)
                                if blob:
                                    real_pdf_filename = blob.name
                                    expiry = datetime.now(timezone.utc) + timedelta(hours=2)
                                    sas = generate_blob_sas(
                                        account_name=bsc.account_name,
                                        container_name=pinfo["pdf_container"],
                                        blob_name=blob.name,
                                        account_key=bsc.credential.account_key,
                                        permission=BlobSasPermissions(read=True),
                                        expiry=expiry,
                                    )
                                    real_pdf_url = f"https://{bsc.account_name}.blob.core.windows.net/{pinfo['pdf_container']}/{blob.name}?{sas}"
                        except Exception:
                            pass

                alerts = []
                if active:
                    if not real_pdf_filename:
                        alerts.append("PDF manquant")
                    if include_blob_stats and audio_count == 0:
                        alerts.append("Aucun audio")
                effective_status = p_status or "ready"
                if effective_status == "pending":
                    pipeline_done = (
                        not p_source_module_id
                        and (
                            p_pipeline_auto_pilot_step == "done"
                            or p_pipeline_status in ("text_ready", "audio_completed", "audio_launched", "completed")
                        )
                    )
                    pipeline_failed = (
                        bool(p_pipeline_auto_pilot_error)
                        or p_pipeline_status in ("error", "audio_error")
                        or p_pipeline_auto_pilot_step == "stopped"
                    )
                    if pipeline_done:
                        effective_status = "ready"
                    elif pipeline_failed or (p_source_formation_id and not p_pipeline_status and not p_pipeline_auto_pilot_step):
                        effective_status = "error"
                    elif repair_on_load and not p_source_formation_id and updated_at:
                        try:
                            updated_dt = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
                            if updated_dt.tzinfo is None:
                                updated_dt = updated_dt.replace(tzinfo=timezone.utc)
                            if datetime.now(timezone.utc) - updated_dt > timedelta(hours=2):
                                effective_status = "error"
                        except Exception:
                            pass

                total_session_count = int(p_total_session_count or 0)
                remaining_session_count = int(p_remaining_session_count or 0)
                effective_lifecycle = p_lifecycle_status or "active"
                if (
                    effective_lifecycle == "active"
                    and effective_status == "ready"
                    and total_session_count > 0
                    and remaining_session_count == 0
                ):
                    effective_lifecycle = "completed"

                platforms.append({
                    "id": pid,
                    "name": name,
                    "teacher_name": teacher_name or "",
                    "teacher_color": teacher_color or "",
                    "creation_request_id": creation_request_id or "",
                    "slug": slug,
                    "center_account_id": p_center_account_id,
                    "center_platform_number": int(p_center_platform_number or pid),
                    "center_slug": p_center_slug,
                    "active": active,
                    "upload_locked": bool(upload_locked),
                    "audio_count": audio_count,
                    "last_upload_date": last_upload,
                    "pdf_filename": real_pdf_filename,
                    "pdf_url": real_pdf_url,
                    "pdf_uploaded_at": pdf_uploaded_at,
                    "alerts": alerts,
                    "updated_at": updated_at,
                    "frontend_url": pinfo.get("frontend_url"),
                    "public_path": _class_public_path(p_center_slug, slug),
                    "public_url": _class_public_url(pinfo.get("frontend_url"), p_center_slug, slug),
                    "status": effective_status,
                    "source_formation_id": p_source_formation_id,
                    "source_module_id": p_source_module_id,
                    "source_rncp_code": p_source_rncp_code or "",
                    "source_tp_name": p_source_tp_name or "",
                    "pipeline_status": p_pipeline_status or "",
                    "pipeline_auto_pilot_step": p_pipeline_auto_pilot_step or "",
                    "pipeline_auto_pilot_error": p_pipeline_auto_pilot_error or "",
                    "pipeline_auto_pilot_enabled": bool(p_pipeline_auto_pilot_enabled),
                    "lifecycle_status": effective_lifecycle,
                    "completed_at": p_completed_at,
                    "archived_at": p_archived_at,
                    "asset_binding_mode": p_asset_binding_mode or "canonical",
                    "total_session_count": total_session_count,
                    "remaining_session_count": remaining_session_count,
                    "teacher_preparation": build_teacher_preparation_state(
                        platform_status=effective_status,
                        pipeline_status=p_pipeline_status,
                        pipeline_step=p_pipeline_auto_pilot_step,
                        pipeline_error=p_pipeline_auto_pilot_error,
                        source_formation_id=p_source_formation_id,
                        source_module_id=p_source_module_id,
                    ),
                    "course_schedule": course_schedule,
                    "blob_stats_loaded": include_blob_stats,
                })

            return jsonify({"success": True, "platforms": platforms}), 200

        except Exception as e:
            logger.error(f"❌ Erreur get platforms: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    def _mirror_clone_status_sqlite(target_platform_id, status):
        """Best-effort compatibility mirror; PostgreSQL stays authoritative."""
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE platform_config SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now_str(), target_platform_id),
            )
            conn.commit()
        except Exception:
            logger.warning(
                "HR_CLONE_SQLITE_STATUS_MIRROR_FAILED platform_id=%s status=%s",
                target_platform_id,
                status,
                exc_info=True,
            )
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _clone_formation_async(
        source_platform_id,
        target_platform_id,
        source_formation_id,
        *,
        source_module_id=None,
        postgres_clone=False,
        center_account_id=None,
        scope_to_center=False,
    ):
        """Bind a target promotion to a reusable course structure.

        PostgreSQL module reuses share one immutable Azure manifest. The older
        formation/SQLite compatibility path still copies blobs because it has
        no durable clone mapping/asset registry.
        """
        from services.azure_blob_service import (
            copy_blobs_by_prefix, CONTAINER_DOCUMENTS, CONTAINER_AUDIOS,
        )
        try:
            if postgres_clone:
                clone_result = clone_postgres_course_structure(
                    target_platform_id=target_platform_id,
                    module_id=source_module_id,
                    formation_id=None if source_module_id is not None else source_formation_id,
                    center_account_id=center_account_id,
                    scope_to_center=scope_to_center,
                )
                source_platform_id = clone_result["source_platform_id"]
                folder_id_map = clone_result["folder_id_map"]
            else:
                conn = get_db_connection()
                cursor = conn.cursor()
                # 1. Cloner chaque cours_folder en préservant l'ordre
                cursor.execute(
                    """SELECT id, name, position, created_at FROM cours_folders
                       WHERE platform_id = ? ORDER BY position ASC, id ASC""",
                    (source_platform_id,),
                )
                source_folders = cursor.fetchall()
                folder_id_map = {}  # source_folder_id -> new_folder_id

                for src_fid, fname, position, created_at in source_folders:
                    cursor.execute(
                        "INSERT INTO cours_folders (platform_id, name, position) VALUES (?, ?, ?)",
                        (target_platform_id, fname, position),
                    )
                    new_fid = cursor.lastrowid
                    folder_id_map[src_fid] = new_fid

                    # 2. Cloner les documents liés. Les content jobs et leurs
                    # segments ne faisaient pas partie du clone historique.
                    cursor.execute(
                        """SELECT filename, original_name, status, audio_filename, COALESCE(doc_type, 'source')
                           FROM cours_documents WHERE folder_id = ?""",
                        (src_fid,),
                    )
                    for filename, original_name, status, audio_filename, doc_type in cursor.fetchall():
                        cursor.execute(
                            """INSERT INTO cours_documents
                               (folder_id, filename, original_name, status, audio_filename, doc_type)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (new_fid, filename, original_name, status, audio_filename, doc_type),
                        )
                conn.commit()
                conn.close()

            total_copied = 0
            shared_asset_count = 0
            if postgres_clone and source_module_id and center_account_id is not None:
                manifest = ensure_module_asset_manifest(
                    module_id=source_module_id,
                    center_account_id=center_account_id,
                    source_platform_id=source_platform_id,
                    source_folder_ids=folder_id_map.keys(),
                )
                shared_asset_count = int(manifest.get("registered") or 0)
                set_platform_asset_binding_mode(target_platform_id, "shared")
            else:
                # Compatibility for non-module clones without a durable asset
                # registry. New centre flows never take this path.
                for src_fid, new_fid in folder_id_map.items():
                    src_prefix_docs = f"platform-{source_platform_id}/folder-{src_fid}/"
                    dst_prefix_docs = f"platform-{target_platform_id}/folder-{new_fid}/"
                    try:
                        total_copied += copy_blobs_by_prefix(CONTAINER_DOCUMENTS, src_prefix_docs, dst_prefix_docs)
                        total_copied += copy_blobs_by_prefix(CONTAINER_AUDIOS, src_prefix_docs, dst_prefix_docs)
                    except Exception as e:
                        if postgres_clone:
                            raise RuntimeError(
                                f"Copie Blob incomplète pour le dossier {src_fid}→{new_fid}: {e}"
                            ) from e
                        logger.warning(f"⚠️ Copie blobs folder {src_fid}→{new_fid} : {e}")

            # 4. Marquer la source de vérité puis seulement son miroir local.
            if postgres_clone:
                set_postgres_platform_status(
                    target_platform_id,
                    "ready",
                    center_account_id,
                    scope_to_center=scope_to_center,
                )
                _mirror_clone_status_sqlite(target_platform_id, "ready")
            else:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE platform_config SET status = 'ready', updated_at = ? WHERE id = ?",
                    (_now_str(), target_platform_id),
                )
                conn.commit()
                conn.close()
            logger.info(
                f"✅ Clone formation {source_formation_id} : P{source_platform_id}→P{target_platform_id} "
                f"— {len(folder_id_map)} folders, {shared_asset_count} ressources partagées, "
                f"{total_copied} blobs de compatibilité copiés"
            )
        except Exception as e:
            logger.error(f"❌ Clone formation {source_formation_id} P{source_platform_id}→P{target_platform_id} : {e}")
            if postgres_clone:
                try:
                    set_postgres_platform_status(
                        target_platform_id,
                        "error",
                        center_account_id,
                        scope_to_center=scope_to_center,
                    )
                except Exception:
                    logger.exception(
                        "HR_CLONE_POSTGRES_ERROR_STATUS_FAILED platform_id=%s",
                        target_platform_id,
                    )
                _mirror_clone_status_sqlite(target_platform_id, "error")
            else:
                _mirror_clone_status_sqlite(target_platform_id, "error")

    # ─── POST /api/hr/platforms (Créer une nouvelle plateforme) ──────────
    @hr_bp.route("/api/hr/platforms", methods=["POST"])
    def create_platform():
        """Crée une nouvelle plateforme. 4 modes exclusifs :

        1. {name} — plateforme vide, pas de cours (comportement historique)
        2. {name, module_id} — crée une promo liée à un module maître. Clone la
           structure en base et partage le manifeste Azure immuable du module.
        3. {name, formation_id} — legacy : clone depuis une formation pipeline
           (équivalent à module_id mais pointe vers le job au lieu du module).
           Gardé pour compat, la modale utilise maintenant module_id.
        4. {name, new_formation: {tp_name, rncp_code, total_hours}} — crée un job
           pipeline lié à cette plateforme, statut 'pending' jusqu'à fin pipeline.
           L'admin finit les étapes (validation humaine) sur /formation-pipeline.
        """
        denied = _require_admin()
        if denied:
            return denied

        data = request.get_json(silent=True) or {}
        name = data.get("name", "").strip()
        module_id = data.get("module_id")         # NOUVEAU — mode module maître
        formation_id = data.get("formation_id")   # legacy
        new_formation = data.get("new_formation") # mode pipeline
        teacher_name = str(data.get("teacher_name") or "").strip()[:80] or None
        teacher_color = str(data.get("teacher_color") or "").strip().lower() or None
        raw_ai_voice_id = data.get("ai_voice_id")
        try:
            ai_voice_id = int(raw_ai_voice_id) if raw_ai_voice_id not in (None, "") else None
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Voix IA invalide"}), 400
        creation_request_id = str(data.get("creation_request_id") or "").strip() or None

        if not name:
            return jsonify({"success": False, "error": "Le nom est requis"}), 400
        if teacher_color and teacher_color not in {"violet", "blue", "pink", "green", "amber"}:
            return jsonify({"success": False, "error": "Couleur de professeur invalide"}), 400
        if creation_request_id and not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", creation_request_id):
            return jsonify({"success": False, "error": "Identifiant de création invalide"}), 400
        if new_formation and not teacher_name:
            return jsonify({"success": False, "error": "Le prénom du professeur IA est requis"}), 400
        if ai_voice_id is not None:
            from repositories.ai_voice_repository import get_voice

            owner_center_id = _training_center_account_id()
            if (
                _admin_account_type() != "training_center"
                or owner_center_id is None
                or get_voice(owner_center_id, ai_voice_id) is None
            ):
                return jsonify({"success": False, "error": "Voix IA introuvable"}), 404

        # A browser retry or double click must resolve to the same professor.
        # The key is looked up inside the current centre only, so it cannot be
        # used to discover another tenant's platform.
        if (
            creation_request_id
            and session.get("admin_account_type") == "training_center"
            and postgres_enabled()
        ):
            existing = get_platform_by_creation_request_id(
                creation_request_id,
                session.get("admin_account_id"),
            )
            if existing:
                existing_id = int(existing["id"])
                center = get_training_center_by_id(session.get("admin_account_id"))
                center_slug = (center or {}).get("slug") or "le-socrate"
                existing_status = existing.get("status") or "pending"
                return jsonify({
                    "success": True,
                    "deduplicated": True,
                    "platform": {
                        "id": existing_id,
                        "center_platform_number": int(
                            existing.get("center_platform_number") or existing_id
                        ),
                        "name": existing.get("name"),
                        "slug": existing.get("slug"),
                        "center_slug": center_slug,
                        "public_path": _class_public_path(center_slug, existing.get("slug")),
                        "public_url": _class_public_url(
                            _get_platform_info(existing_id).get("frontend_url"),
                            center_slug,
                            existing.get("slug"),
                        ),
                        "status": existing_status,
                        "source_formation_id": existing.get("source_formation_id"),
                        "source_module_id": existing.get("source_module_id"),
                        "pipeline_job_id": existing.get("source_formation_id"),
                        "teacher_name": existing.get("teacher_name") or teacher_name or "",
                        "teacher_color": existing.get("teacher_color") or teacher_color or "violet",
                        "creation_request_id": creation_request_id,
                    },
                }), 200
        # Vérif qu'au plus un des 3 modes "avec contenu" est fourni
        content_modes = sum(1 for x in (module_id, formation_id, new_formation) if x)
        if content_modes > 1:
            return jsonify({"success": False, "error": "Choisir UN seul mode : module existant, formation existante, ou nouvelle formation"}), 400

        # Les sources sont des IDs indirects fournis dans le corps : les
        # résoudre avant d'ouvrir la transaction qui créera la plateforme.
        if module_id:
            if isinstance(module_id, bool):
                return jsonify({"success": False, "error": "module_id invalide"}), 400
            try:
                module_id = int(module_id)
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "module_id invalide"}), 400
            source_denied = _require_hr_resource_access("module", module_id)
            if source_denied:
                return source_denied
        elif formation_id:
            if isinstance(formation_id, bool):
                return jsonify({"success": False, "error": "formation_id invalide"}), 400
            try:
                formation_id = int(formation_id)
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "formation_id invalide"}), 400
            if _admin_account_type() == "training_center":
                center_account_id = _training_center_account_id()
                try:
                    source_allowed = pipeline_job_belongs_to_center(
                        formation_id,
                        center_account_id,
                    )
                except Exception:
                    logger.warning(
                        "HR_TENANT_SCOPE_LOOKUP_FAILED resource_type=pipeline_job resource_id=%s center_account_id=%s",
                        formation_id,
                        center_account_id,
                        exc_info=True,
                    )
                    source_allowed = False
                if not source_allowed:
                    return _tenant_resource_not_found()

        # When the pipeline catalogue is authoritative in PostgreSQL, resolve
        # clone sources there as well.  Falling back to the SQLite mirror here
        # made PG-visible modules impossible to clone and reintroduced a split
        # brain between the catalogue and the writer.
        postgres_clone = _hr_pipeline_reads_use_postgres() and bool(module_id or formation_id)
        source_platform_id = None
        scope_to_center = _admin_account_type() == "training_center"
        request_center_account_id = (
            _training_center_account_id() if scope_to_center else None
        )
        if postgres_clone:
            try:
                if module_id:
                    source = resolve_postgres_module_clone_source(
                        module_id,
                        request_center_account_id,
                        scope_to_center=scope_to_center,
                    )
                    source_platform_id = int(source["source_platform_id"])
                    # Preserve the legacy link to the originating pipeline job
                    # when the reusable module has one.
                    formation_id = source.get("source_pipeline_job_id")
                else:
                    source = resolve_postgres_formation_clone_source(
                        formation_id,
                        request_center_account_id,
                        scope_to_center=scope_to_center,
                    )
                    source_platform_id = int(source["source_platform_id"])
            except CloneSourceNotFound as exc:
                return jsonify({"success": False, "error": str(exc)}), 404
            except CloneSourceInvalid as exc:
                return jsonify({"success": False, "error": str(exc)}), 400
            except Exception:
                logger.exception("HR_POSTGRES_CLONE_SOURCE_LOOKUP_FAILED")
                return jsonify({
                    "success": False,
                    "error": "Source de clonage PostgreSQL indisponible",
                }), 503

        # Tenant ownership and source validity are deliberately checked first
        # so this billing boundary never reveals another centre's resources.
        if (
            _admin_account_type() == "training_center"
            and (module_id is not None or formation_id is not None or new_formation is not None)
        ):
            return jsonify({
                "success": False,
                "error": "Passez par la commande sécurisée avant de créer ou réutiliser un professeur IA.",
                "code": "teacher_order_required",
            }), 402

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            center_account_id = None
            center_slug = "le-socrate"
            if session.get("admin_account_type") == "training_center":
                center_account_id = session.get("admin_account_id")
                cursor.execute(
                    "SELECT slug FROM training_center_accounts WHERE id = ?",
                    (center_account_id,),
                )
                row = cursor.fetchone()
                center_slug = row[0] if row and row[0] else center_slug
                if center_slug == "le-socrate" and postgres_enabled():
                    pg_center = get_training_center_by_id(center_account_id)
                    if pg_center and pg_center["slug"]:
                        center_slug = pg_center["slug"]

            slug = unique_slug(
                cursor,
                "platform_config",
                slugify(name, fallback="formation"),
                scope_column="center_account_id",
                scope_value=center_account_id,
            )

            if not postgres_clone:
                source_platform_id = None

            # Mode module_id (nouveau — priorité sur formation_id si les deux présents)
            if module_id and not postgres_clone:
                module_scope_sql, module_scope_params = _module_scope_clause("formation_modules")
                cursor.execute(
                    "SELECT source_platform_id, status, source_pipeline_job_id, voice_type "
                    f"FROM formation_modules WHERE id = ? AND {module_scope_sql}",
                    [module_id] + module_scope_params,
                )
                row = cursor.fetchone()
                if not row:
                    conn.close()
                    return jsonify({"success": False, "error": "Module introuvable"}), 404
                source_platform_id, m_status, m_job_id, m_voice_type = row
                if m_status == "archived":
                    conn.close()
                    return jsonify({"success": False, "error": "Ce module est archivé"}), 400
                if m_voice_type == "mock":
                    conn.close()
                    return jsonify({
                        "success": False,
                        "error": (
                            "Ce module a été généré en mode test silencieux. "
                            "Relancez le TTS avec Edge TTS ou Fish Audio avant de créer une plateforme."
                        ),
                    }), 400
                cursor.execute("SELECT COUNT(*) FROM cours_folders WHERE platform_id = ?", (source_platform_id,))
                if cursor.fetchone()[0] == 0:
                    conn.close()
                    return jsonify({"success": False, "error": "Le module n'a pas de cours générés (source vide)"}), 400
                # On aligne formation_id sur le job pipeline du module pour compat avec
                # l'ancien _clone_formation_async (3e argument = source_formation_id)
                formation_id = m_job_id

            # Mode formation_id (legacy) : vérifier que la formation existe et a des cours
            elif formation_id and not postgres_clone:
                cursor.execute(
                    "SELECT platform_id, status FROM formation_pipeline_jobs WHERE id = ?",
                    (formation_id,),
                )
                row = cursor.fetchone()
                if not row:
                    conn.close()
                    return jsonify({"success": False, "error": "Formation introuvable"}), 404
                source_platform_id, fstatus = row
                if fstatus != "completed":
                    conn.close()
                    return jsonify({"success": False, "error": f"La formation n'est pas complétée (statut : {fstatus})"}), 400
                cursor.execute("SELECT COUNT(*) FROM cours_folders WHERE platform_id = ?", (source_platform_id,))
                if cursor.fetchone()[0] == 0:
                    conn.close()
                    return jsonify({"success": False, "error": "La formation n'a pas encore de cours générés"}), 400

            # Valider le mode new_formation
            schedule_config_result = None
            if new_formation:
                tp_name = (new_formation.get("tp_name") or "").strip()
                rncp_code = (new_formation.get("rncp_code") or "").strip()
                total_hours = new_formation.get("total_hours")
                if not tp_name or not rncp_code or not total_hours:
                    conn.close()
                    return jsonify({"success": False, "error": "tp_name, rncp_code et total_hours requis pour une nouvelle formation"}), 400
                try:
                    total_hours = int(total_hours)
                except (TypeError, ValueError):
                    conn.close()
                    return jsonify({"success": False, "error": "total_hours doit être un entier"}), 400
                from services.formation_pipeline_service import HOURS_PER_DAY
                if total_hours <= 0 or total_hours % HOURS_PER_DAY != 0:
                    conn.close()
                    return jsonify({
                        "success": False,
                        "error": f"La durée doit être un multiple de {HOURS_PER_DAY}h : 1 journée = {HOURS_PER_DAY}h.",
                    }), 400
                schedule_config = new_formation.get("schedule") or {}
                if schedule_config:
                    try:
                        int(schedule_config.get("total_training_days") or 0)
                        int(schedule_config.get("weekly_course_count") or 0)
                    except (TypeError, ValueError):
                        conn.close()
                        return jsonify({"success": False, "error": "Planning professeur IA invalide"}), 400

            now_str = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")

            # Statut initial : 'pending' pour les modes qui lancent un travail
            # async, 'ready' pour une plateforme vide
            has_content = bool(module_id or formation_id or new_formation)
            initial_status = "pending" if has_content else "ready"

            # En mode hybride, PostgreSQL est l'unique allocateur d'identités.
            # On relève sa séquence au-dessus du max SQLite puis on réutilise
            # explicitement l'ID réservé dans le miroir local. SQLite pur garde
            # son AUTOINCREMENT historique.
            if platform_ids_use_postgres_allocator():
                cursor.execute("SELECT COALESCE(MAX(id), 0) FROM platform_config")
                sqlite_max_id = int(cursor.fetchone()[0])
                new_id = allocate_platform_id_from_postgres(sqlite_max_id=sqlite_max_id)
                cursor.execute(
                    """INSERT INTO platform_config
                       (id, name, upload_locked, updated_at, slug, status,
                        source_formation_id, source_module_id, center_account_id,
                        public_access_enabled, teacher_name, teacher_color,
                        creation_request_id)
                       VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                    (
                        new_id,
                        name,
                        now_str,
                        slug,
                        initial_status,
                        formation_id,
                        module_id,
                        center_account_id,
                        teacher_name,
                        teacher_color,
                        creation_request_id,
                    ),
                )
            else:
                cursor.execute(
                    """INSERT INTO platform_config
                       (name, upload_locked, updated_at, slug, status,
                        source_formation_id, source_module_id, center_account_id,
                        public_access_enabled, teacher_name, teacher_color,
                        creation_request_id)
                       VALUES (?, 1, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                    (
                        name, now_str, slug, initial_status, formation_id,
                        module_id, center_account_id, teacher_name,
                        teacher_color, creation_request_id,
                    ),
                )
                new_id = cursor.lastrowid

            cursor.execute("PRAGMA table_info(platform_config)")
            creation_platform_columns = {column[1] for column in cursor.fetchall()}
            center_platform_number = None
            if "center_platform_number" in creation_platform_columns:
                cursor.execute(
                    "SELECT center_platform_number FROM platform_config WHERE id = ?",
                    (new_id,),
                )
                number_row = cursor.fetchone()
                center_platform_number = number_row[0] if number_row else None
            if center_platform_number is None and center_account_id is not None:
                cursor.execute(
                    "SELECT COUNT(*) FROM platform_config WHERE center_account_id = ? AND id <= ?",
                    (center_account_id, new_id),
                )
                center_platform_number = int(cursor.fetchone()[0])
            if center_platform_number is None:
                center_platform_number = new_id

            # Noms des containers
            audio_container = f"formationaudio-p{new_id}"
            pdf_container = f"formationpdf-p{new_id}"
            archive_container = f"formationaudio-p{new_id}-archives"

            cursor.execute(
                "UPDATE platform_config SET audio_container = ?, pdf_container = ?, archive_container = ? WHERE id = ?",
                (audio_container, pdf_container, archive_container, new_id),
            )

            # Créer une entrée cours_config par défaut
            cursor.execute("SELECT heure_debut FROM cours_config WHERE platform_id = 1")
            default_row = cursor.fetchone()
            default_heure = default_row[0] if default_row else now_str
            cursor.execute(
                "INSERT INTO cours_config (id, heure_debut, platform_id) VALUES (?, ?, ?)",
                (new_id, default_heure, new_id),
            )

            if new_formation and (new_formation.get("schedule") or None):
                schedule_config_result = save_course_schedule(
                    cursor,
                    new_id,
                    new_formation.get("schedule"),
                )
                if schedule_config_result.get("first_session_at"):
                    default_heure = schedule_config_result["first_session_at"]
                    cursor.execute(
                        "UPDATE cours_config SET heure_debut = ? WHERE platform_id = ?",
                        (default_heure, new_id),
                    )

            # ─── Plateforme "fait main" — module catalogue auto ──────────────
            # Quand l'admin crée une plateforme VIDE (sans pipeline ni clone),
            # il va y uploader manuellement audios + cours. Ces plateformes
            # sont des "modules faits mains" — on les inscrit dans le catalogue
            # formation_modules pour qu'elles apparaissent dans l'onglet Modules
            # et soient supprimables via le bouton catalogue. Pas de
            # source_pipeline_job_id (NULL — distinguable des modules pipeline).
            if not has_content:
                if center_account_id is None:
                    cursor.execute(
                        "SELECT COUNT(*) FROM formation_modules WHERE source_pipeline_job_id IS NULL AND center_account_id IS NULL"
                    )
                else:
                    cursor.execute(
                        "SELECT COUNT(*) FROM formation_modules WHERE source_pipeline_job_id IS NULL AND center_account_id = ?",
                        (center_account_id,),
                    )
                n_manual = cursor.fetchone()[0] + 1
                manual_version = f"manuel-v{n_manual}"
                cursor.execute(
                    """INSERT INTO formation_modules
                       (rncp_code, tp_name, version, status, source_pipeline_job_id,
                        source_platform_id, center_account_id, validated_at)
                       VALUES (?, ?, ?, 'validated', NULL, ?, ?, ?)""",
                    (None, name, manual_version, new_id, center_account_id, now_str),
                )
                logger.info(f"✏️  Module 'fait main' inscrit au catalogue : {name} ({manual_version}) → P{new_id}")

            postgres_synced = False
            if postgres_enabled():
                try:
                    upsert_platform_config({
                        "id": new_id,
                        "center_account_id": center_account_id,
                        "name": name,
                        "slug": slug,
                        "upload_locked": True,
                        "public_access_enabled": True,
                        "pdf_filename": None,
                        "pdf_uploaded_at": None,
                        "updated_at": now_str,
                        "playlist_mode": None,
                        "audio_container": audio_container,
                        "pdf_container": pdf_container,
                        "archive_container": archive_container,
                        "audio_base_url": None,
                        "status": initial_status,
                        "source_formation_id": formation_id,
                        "source_module_id": module_id,
                        "teacher_name": teacher_name,
                        "teacher_color": teacher_color,
                        "creation_request_id": creation_request_id,
                    })
                    upsert_cours_config({
                        "id": new_id,
                        "platform_id": new_id,
                        "heure_debut": default_heure,
                    })
                    if not has_content:
                        create_postgres_manual_formation_module(
                            platform_id=new_id,
                            tp_name=name,
                            center_account_id=center_account_id,
                        )
                    postgres_synced = True
                except Exception:
                    conn.rollback()
                    logger.exception("❌ Synchronisation Postgres plateforme échouée")
                    return jsonify({
                        "success": False,
                        "error": "Plateforme non créée: synchronisation Postgres impossible",
                    }), 500

            conn.commit()
            conn.close()

            # Créer les containers Azure Blob (toujours, quel que soit le mode)
            containers_created = []
            for cs_env, containers in [
                ("AZURE_AUDIO_STORAGE_CONNECTION_STRING", [audio_container, archive_container]),
                ("AZURE_STORAGE_CONNECTION_STRING", [pdf_container]),
            ]:
                cs = os.environ.get(cs_env)
                if cs:
                    bsc = BlobServiceClient.from_connection_string(cs)
                    for cname in containers:
                        # Le container playlist doit être lisible anonymement :
                        # le lecteur streame les MP3 via FrontDoor sans SAS
                        # (même convention que formationaudio-dev/p2/p3/p4).
                        # Archives et PDFs restent privés (accès via SAS).
                        public_access = "blob" if cname == audio_container else None
                        try:
                            bsc.create_container(cname, public_access=public_access)
                            containers_created.append(cname)
                            logger.info(f"✅ Container Azure créé : {cname} (public={public_access or 'private'})")
                        except ResourceExistsError:
                            containers_created.append(f"{cname} (existait déjà)")
                            if public_access:
                                try:
                                    bsc.get_container_client(cname).set_container_access_policy(
                                        signed_identifiers={}, public_access=public_access
                                    )
                                    logger.info(f"✅ Accès public '{public_access}' appliqué au container existant : {cname}")
                                except Exception as e:
                                    logger.warning(f"⚠️ Impossible d'appliquer l'accès public sur {cname}: {e}")
                        except Exception as e:
                            logger.warning(f"⚠️ Erreur création container {cname}: {e}")

            # Mode réutilisation : lancer le clone en background
            linked_job_id = None
            if (module_id or formation_id) and source_platform_id:
                import threading
                t = threading.Thread(
                    target=_clone_formation_async,
                    args=(source_platform_id, new_id, formation_id),
                    kwargs={
                        "source_module_id": module_id,
                        "postgres_clone": postgres_clone,
                        "center_account_id": center_account_id,
                        "scope_to_center": scope_to_center,
                    },
                    daemon=True,
                )
                t.start()
                logger.info(f"🔄 Clone formation {formation_id} (P{source_platform_id}→P{new_id}) lancé en background")

            # Mode nouvelle formation : créer le job pipeline (l'admin finit les étapes sur /formation-pipeline)
            elif new_formation:
                from services.formation_pipeline_service import create_job, HOURS_PER_DAY
                th = int(total_hours)
                nb_days = th // HOURS_PER_DAY
                linked_job_id = create_job(
                    platform_id=new_id,
                    tp_name=tp_name,
                    rncp_code=rncp_code,
                    total_hours=th,
                    nb_days=nb_days,
                )
                link_updated_at = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
                link_conn = get_db_connection()
                link_cursor = link_conn.cursor()
                try:
                    link_cursor.execute(
                        """
                        UPDATE platform_config
                        SET source_formation_id = ?,
                            updated_at = ?
                        WHERE id = ?
                          AND source_formation_id IS NULL
                        """,
                        (linked_job_id, link_updated_at, new_id),
                    )
                    link_conn.commit()
                finally:
                    link_conn.close()
                if postgres_enabled():
                    try:
                        upsert_platform_config({
                            "id": new_id,
                            "center_account_id": center_account_id,
                            "name": name,
                            "slug": slug,
                            "upload_locked": True,
                            "public_access_enabled": True,
                            "pdf_filename": None,
                            "pdf_uploaded_at": None,
                            "updated_at": link_updated_at,
                            "playlist_mode": None,
                            "audio_container": audio_container,
                            "pdf_container": pdf_container,
                            "archive_container": archive_container,
                            "audio_base_url": None,
                            "status": initial_status,
                            "source_formation_id": linked_job_id,
                            "source_module_id": module_id,
                            "teacher_name": teacher_name,
                            "teacher_color": teacher_color,
                            "creation_request_id": creation_request_id,
                        })
                    except Exception:
                        logger.warning(
                            "⚠️ Synchronisation Postgres du lien source_formation_id ignorée P%s job=%s",
                            new_id,
                            linked_job_id,
                            exc_info=True,
                        )
                logger.info(f"🚀 Pipeline formation job {linked_job_id} initié pour plateforme {new_id} — l'admin doit continuer sur /formation-pipeline")

            logger.info(f"✅ Plateforme {new_id} '{name}' créée (status={initial_status}) avec containers: {containers_created}")

            if ai_voice_id is not None and center_account_id is not None:
                from repositories.ai_voice_repository import assign_voice_to_platform

                if not assign_voice_to_platform(center_account_id, new_id, ai_voice_id):
                    logger.warning(
                        "AI_VOICE_PLATFORM_ASSIGNMENT_FAILED platform_id=%s voice_id=%s center_account_id=%s",
                        new_id,
                        ai_voice_id,
                        center_account_id,
                    )

            return jsonify({
                "success": True,
                "platform": {
                    "id": new_id,
                    "center_platform_number": center_platform_number,
                    "name": name,
                    "slug": slug,
                    "center_slug": center_slug,
                    "public_path": _class_public_path(center_slug, slug),
                    "public_url": _class_public_url(_get_platform_info(new_id).get("frontend_url"), center_slug, slug),
                    "status": initial_status,
                    "source_formation_id": formation_id,
                    "source_module_id": module_id,
                    "pipeline_job_id": linked_job_id,
                    "teacher_name": teacher_name or "",
                    "teacher_color": teacher_color or "violet",
                    "ai_voice_id": ai_voice_id,
                    "creation_request_id": creation_request_id or "",
                    "schedule": schedule_config_result,
                    "audio_container": audio_container,
                    "pdf_container": pdf_container,
                    "archive_container": archive_container,
                    "containers_created": containers_created,
                    "postgres_synced": postgres_synced,
                },
            }), 201

        except Exception as e:
            logger.error(f"❌ Erreur création plateforme: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── POST /api/hr/platforms/<id>/toggle-lock ─────────────────────────
    @hr_bp.route("/api/hr/platforms/<int:platform_id>/toggle-lock", methods=["POST"])
    def toggle_lock(platform_id):
        """Basculer le verrouillage d'upload pour une plateforme"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT upload_locked FROM platform_config WHERE id = ?", (platform_id,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return jsonify({"success": False, "error": "Plateforme introuvable"}), 404

            new_value = 0 if row[0] else 1
            cursor.execute(
                "UPDATE platform_config SET upload_locked = ?, updated_at = ? WHERE id = ?",
                (new_value, _now_str(), platform_id),
            )
            conn.commit()
            conn.close()

            status_label = "verrouillé" if new_value else "déverrouillé"
            logger.info(f"🔒 Plateforme {platform_id} upload {status_label}")

            # Propager le changement vers la plateforme distante (si elle a son propre backend)
            if not _is_local_platform(platform_id):
                _call_platform(
                    platform_id,
                    "/api/internal/set-lock",
                    json_data={"locked": bool(new_value), "platform_id": platform_id},
                )

            return jsonify({
                "success": True,
                "upload_locked": bool(new_value),
                "message": f"Upload {status_label} pour plateforme {platform_id}",
            }), 200

        except Exception as e:
            logger.error(f"❌ Erreur toggle lock: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── PATCH /api/hr/platforms/<id>/lifecycle ───────────────────────────
    @hr_bp.route("/api/hr/platforms/<int:platform_id>/lifecycle", methods=["PATCH"])
    def update_platform_lifecycle(platform_id):
        """Archive or restore a teacher without deleting its durable module/assets."""
        denied = _require_admin()
        if denied:
            return denied
        center_account_id = _training_center_account_id()
        if _admin_account_type() != "training_center" or center_account_id is None:
            return jsonify({"success": False, "error": "Compte centre requis"}), 403

        data = request.get_json(silent=True) or {}
        lifecycle_status = str(data.get("lifecycle_status") or "").strip().lower()
        try:
            lifecycle = set_platform_lifecycle(platform_id, center_account_id, lifecycle_status)
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        if not lifecycle:
            return _tenant_resource_not_found()
        return jsonify({
            "success": True,
            "platform": lifecycle,
            "message": (
                "Professeur archivé. Son identité, ses cours et ses audios restent réutilisables."
                if lifecycle_status == "archived"
                else "Cycle de vie du professeur mis à jour."
            ),
        }), 200

    # ─── DELETE /api/hr/platforms/<id> ────────────────────────────────────
    # Suppression définitive d'une plateforme. Cascade DB :
    #   - content_generation_segments → content_generation_jobs (FK)
    #   - formation_knowledge_base → formation_pipeline_jobs (FK)
    #   - cours_documents → cours_folders → cours_config
    #   - formation_modules :
    #     · modules "fait main" (source_pipeline_job_id IS NULL) → DELETE
    #       (la plateforme EST le module, ils représentent la même chose)
    #     · modules pipeline (source_pipeline_job_id NOT NULL) → SET source_platform_id = NULL
    #       (le module reste dans le catalogue, réutilisable indépendamment)
    #   - logs et video_visits préservés (audit trail historique)
    # Côté Azure : blobs PDF/audios/archives non supprimés en V1 — nettoyage manuel.
    @hr_bp.route("/api/hr/platforms/<int:platform_id>", methods=["DELETE"])
    def delete_platform(platform_id):
        """Supprimer définitivement une plateforme et son contenu pédagogique."""
        denied = _require_admin()
        if denied:
            return denied
        if _admin_account_type() == "training_center":
            return jsonify({
                "success": False,
                "error": "La suppression définitive est désactivée pour les centres. Archivez le professeur afin de préserver ses cours et ses audios réutilisables.",
                "code": "archive_required",
            }), 409
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT id, name FROM platform_config WHERE id = ?", (platform_id,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return jsonify({"success": False, "error": "Plateforme introuvable"}), 404
            platform_name = row[1]

            # 1. Pipeline content : segments → jobs
            cursor.execute(
                "DELETE FROM content_generation_segments WHERE job_id IN ("
                "SELECT id FROM content_generation_jobs WHERE platform_id = ?)",
                (platform_id,),
            )
            cursor.execute(
                "DELETE FROM content_generation_jobs WHERE platform_id = ?",
                (platform_id,),
            )

            # 2. Pipeline formation : KB → jobs
            cursor.execute(
                "DELETE FROM formation_knowledge_base WHERE job_id IN ("
                "SELECT id FROM formation_pipeline_jobs WHERE platform_id = ?)",
                (platform_id,),
            )
            cursor.execute(
                "DELETE FROM formation_pipeline_jobs WHERE platform_id = ?",
                (platform_id,),
            )

            # 3. Contenu pédagogique : documents → folders + config
            cursor.execute(
                "DELETE FROM cours_documents WHERE folder_id IN ("
                "SELECT id FROM cours_folders WHERE platform_id = ?)",
                (platform_id,),
            )
            cursor.execute("DELETE FROM cours_folders WHERE platform_id = ?", (platform_id,))
            cursor.execute("DELETE FROM cours_config WHERE platform_id = ?", (platform_id,))
            cursor.execute("DELETE FROM course_sessions WHERE platform_id = ?", (platform_id,))
            cursor.execute("DELETE FROM course_schedule_config WHERE platform_id = ?", (platform_id,))
            _ensure_student_attendance_records(cursor)
            cursor.execute("DELETE FROM student_attendance_records WHERE platform_id = ?", (platform_id,))
            _ensure_course_reminder_recipients(cursor)
            cursor.execute("DELETE FROM course_reminder_recipients WHERE platform_id = ?", (platform_id,))

            # 4a. Modules "fait main" liés (la plateforme EST le module) → DELETE
            cursor.execute(
                "DELETE FROM formation_modules "
                "WHERE source_platform_id = ? AND source_pipeline_job_id IS NULL",
                (platform_id,),
            )
            n_manual_deleted = cursor.rowcount

            # 4b. Modules pipeline qui pointaient vers cette plateforme : préservés
            #     (produit durable réutilisable indépendamment de la promo source)
            cursor.execute(
                "UPDATE formation_modules SET source_platform_id = NULL "
                "WHERE source_platform_id = ? AND source_pipeline_job_id IS NOT NULL",
                (platform_id,),
            )

            # 5. La plateforme elle-même
            cursor.execute("DELETE FROM platform_config WHERE id = ?", (platform_id,))

            conn.commit()
            conn.close()

            logger.info(
                f"🗑️  Plateforme {platform_id} ({platform_name}) supprimée — "
                f"cascade DB ok (modules fait main supprimés : {n_manual_deleted})"
            )
            return jsonify({
                "success": True,
                "platform_id": platform_id,
                "platform_name": platform_name,
                "manual_modules_deleted": n_manual_deleted,
                "warning": "Blobs Azure (PDF/audios/archives) non supprimés — nettoyage manuel.",
            }), 200
        except Exception as e:
            logger.error(f"❌ Erreur delete platform {platform_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── GET /api/hr/platforms/<id>/audios ────────────────────────────────
    @hr_bp.route("/api/hr/platforms/<int:platform_id>/audios", methods=["GET"])
    def get_platform_audios(platform_id):
        """Lister les audios d'une plateforme (tous containers Azure)"""
        denied = _require_admin()
        if denied:
            return denied

        pinfo = _get_platform_info(platform_id)
        connection_string = os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING")

        try:
            if not connection_string:
                return jsonify({"success": False, "error": "Configuration Azure manquante"}), 500

            container_name = pinfo["audio_container"]
            blob_service_client = BlobServiceClient.from_connection_string(connection_string)
            container_client = blob_service_client.get_container_client(container_name)

            account_name = blob_service_client.account_name
            account_key = blob_service_client.credential.account_key
            expiry = datetime.now(timezone.utc) + timedelta(hours=1)

            audios = []
            for blob in sorted(container_client.list_blobs(), key=lambda b: b.name):
                sas_token = generate_blob_sas(
                    account_name=account_name,
                    container_name=container_name,
                    blob_name=blob.name,
                    account_key=account_key,
                    permission=BlobSasPermissions(read=True),
                    expiry=expiry,
                )
                url = f"https://{account_name}.blob.core.windows.net/{container_name}/{blob.name}?{sas_token}"
                audios.append({
                    "name": blob.name,
                    "size": blob.size,
                    "url": url,
                    "last_modified": blob.last_modified.astimezone(FRANCE_TZ).strftime("%Y-%m-%d %H:%M"),
                })

            return jsonify({"success": True, "audios": audios}), 200

        except Exception as e:
            logger.error(f"❌ Erreur liste audios HR P{platform_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── DELETE /api/hr/platforms/<id>/audios/<filename> ──────────────────
    @hr_bp.route("/api/hr/platforms/<int:platform_id>/audios/<path:filename>", methods=["DELETE"])
    def delete_audio(platform_id, filename):
        """Supprimer un audio depuis le container Azure de la plateforme"""
        denied = _require_admin()
        if denied:
            return denied

        pinfo = _get_platform_info(platform_id)
        connection_string = os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING")

        try:
            if not connection_string:
                return jsonify({"success": False, "error": "Configuration Azure manquante"}), 500

            blob_service_client = BlobServiceClient.from_connection_string(connection_string)
            container_client = blob_service_client.get_container_client(pinfo["audio_container"])
            container_client.delete_blob(filename)
            logger.info(f"🗑️ Audio supprimé (P{platform_id}): {filename}")

            return jsonify({"success": True, "message": f"'{filename}' supprimé"}), 200

        except Exception as e:
            logger.error(f"❌ Erreur suppression audio P{platform_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── POST /api/hr/platforms/<id>/upload-pdf ──────────────────────────
    @hr_bp.route("/api/hr/platforms/<int:platform_id>/upload-pdf", methods=["POST"])
    def upload_platform_pdf(platform_id):
        """Uploader un PDF pour une plateforme (stocké localement)"""
        denied = _require_admin()
        if denied:
            return denied

        if "file" not in request.files:
            return jsonify({"success": False, "error": "Aucun fichier envoyé"}), 400

        file = request.files["file"]
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            return jsonify({"success": False, "error": "Seuls les fichiers PDF sont acceptés"}), 400

        try:
            os.makedirs(PDF_UPLOAD_DIR, exist_ok=True)

            # Supprimer l'ancien PDF de cette plateforme
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT pdf_filename FROM platform_config WHERE id = ?", (platform_id,))
            row = cursor.fetchone()
            if row and row[0]:
                old_path = os.path.join(PDF_UPLOAD_DIR, f"p{platform_id}_{row[0]}")
                if os.path.exists(old_path):
                    os.remove(old_path)

            # Sauvegarder le nouveau PDF
            safe_name = f"p{platform_id}_{file.filename}"
            file.save(os.path.join(PDF_UPLOAD_DIR, safe_name))

            now = _now_str()
            cursor.execute(
                "UPDATE platform_config SET pdf_filename = ?, pdf_uploaded_at = ?, updated_at = ? WHERE id = ?",
                (file.filename, now, now, platform_id),
            )
            conn.commit()
            conn.close()

            logger.info(f"📄 PDF uploadé pour plateforme {platform_id}: {file.filename}")

            return jsonify({
                "success": True,
                "message": f"PDF '{file.filename}' uploadé pour plateforme {platform_id}",
                "pdf_filename": file.filename,
                "pdf_uploaded_at": now,
            }), 200

        except Exception as e:
            logger.error(f"❌ Erreur upload PDF HR: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── POST /api/hr/platforms/<id>/set-pdf-name ────────────────────────
    @hr_bp.route("/api/hr/platforms/<int:platform_id>/set-pdf-name", methods=["POST"])
    def set_pdf_name(platform_id):
        """Enregistre uniquement le nom du PDF en base (sans upload de fichier)"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            data = request.get_json()
            filename = data.get("filename", "").strip()
            if not filename:
                return jsonify({"success": False, "error": "filename requis"}), 400

            now = _now_str()
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE platform_config SET pdf_filename = ?, pdf_uploaded_at = ?, updated_at = ? WHERE id = ?",
                (filename, now, now, platform_id),
            )
            conn.commit()
            conn.close()

            return jsonify({"success": True}), 200

        except Exception as e:
            logger.error(f"❌ Erreur set-pdf-name: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── DELETE /api/hr/platforms/<id>/pdf ────────────────────────────────
    @hr_bp.route("/api/hr/platforms/<int:platform_id>/pdf", methods=["DELETE"])
    def delete_platform_pdf(platform_id):
        """Supprimer le PDF d'une plateforme"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT pdf_filename FROM platform_config WHERE id = ?", (platform_id,))
            row = cursor.fetchone()

            if row and row[0]:
                old_path = os.path.join(PDF_UPLOAD_DIR, f"p{platform_id}_{row[0]}")
                if os.path.exists(old_path):
                    os.remove(old_path)

            cursor.execute(
                "UPDATE platform_config SET pdf_filename = NULL, pdf_uploaded_at = NULL, updated_at = ? WHERE id = ?",
                (_now_str(), platform_id),
            )
            conn.commit()
            conn.close()

            logger.info(f"🗑️ PDF supprimé pour plateforme {platform_id}")

            return jsonify({"success": True, "message": "PDF supprimé"}), 200

        except Exception as e:
            logger.error(f"❌ Erreur suppression PDF HR: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── POST /api/hr/platforms/<id>/backup-and-unlock ───────────────────
    @hr_bp.route("/api/hr/platforms/<int:platform_id>/backup-and-unlock", methods=["POST"])
    def backup_and_unlock(platform_id):
        """Reject the retired destructive audio backup/unlock workflow."""
        denied = _require_admin()
        if denied:
            return denied

        return jsonify({
            "success": False,
            "error": (
                "Cette action a été retirée : les audios sont désormais "
                "conservés automatiquement avec le professeur IA."
            ),
        }), 410


    # ─── POST /api/hr/platforms/<id>/upload-pdf-rag ──────────────────────
    @hr_bp.route("/api/hr/platforms/<int:platform_id>/upload-pdf-rag", methods=["POST"])
    def upload_pdf_rag(platform_id):
        """Upload un PDF dans le bon container Azure et déclenche l'indexer de la plateforme"""
        denied = _require_admin()
        if denied:
            return denied

        if "file" not in request.files:
            return jsonify({"success": False, "error": "Aucun fichier envoyé"}), 400
        file = request.files["file"]
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            return jsonify({"success": False, "error": "Seuls les fichiers PDF sont acceptés"}), 400

        pinfo = _get_platform_info(platform_id)
        connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            return jsonify({"success": False, "error": "Configuration Azure Storage manquante"}), 500

        pdf_container = pinfo["pdf_container"]

        # Config indexer par plateforme (même service Azure AI Search, noms différents)
        if platform_id == 1:
            indexer_name = os.environ.get("AZURE_SEARCH_INDEXER_NAME", "rag-1770824229421-indexer")
            index_name = os.environ.get("AZURE_SEARCH_INDEX_NAME", "rag-1770824229421")
        else:
            indexer_name = os.environ.get(f"PLATFORM_{platform_id}_AZURE_SEARCH_INDEXER_NAME", f"rag-p{platform_id}-indexer")
            index_name = os.environ.get(f"PLATFORM_{platform_id}_AZURE_SEARCH_INDEX_NAME", f"rag-p{platform_id}")

        try:
            from azure.storage.blob import BlobServiceClient as _BSC
            blob_service_client = _BSC.from_connection_string(connection_string)
            container_client = blob_service_client.get_container_client(pdf_container)

            # Supprimer les anciens PDFs du container
            for blob in container_client.list_blobs():
                container_client.delete_blob(blob.name)

            # Upload du nouveau PDF
            blob_client = container_client.get_blob_client(file.filename)
            blob_client.upload_blob(file.stream, overwrite=True)
            logger.info(f"✅ PDF uploadé P{platform_id} → {pdf_container}/{file.filename}")

            # Enregistrer le nom du PDF en base
            now = _now_str()
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE platform_config SET pdf_filename = ?, pdf_uploaded_at = ?, updated_at = ? WHERE id = ?",
                (file.filename, now, now, platform_id),
            )
            conn.commit()
            conn.close()

            # Déclencher l'indexer Azure AI Search
            search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
            search_api_key = os.environ.get("AZURE_SEARCH_API_KEY")
            if search_endpoint and search_api_key:
                headers = {"Content-Type": "application/json", "api-key": search_api_key}

                # Vider l'index existant
                search_url = f"{search_endpoint}/indexes/{index_name}/docs/search?api-version=2024-07-01"
                search_resp = http_requests.post(search_url, headers=headers, json={"search": "*", "select": "chunk_id", "top": 1000})
                if search_resp.status_code == 200:
                    docs = search_resp.json().get("value", [])
                    if docs:
                        delete_actions = [{"@search.action": "delete", "chunk_id": d["chunk_id"]} for d in docs]
                        delete_url = f"{search_endpoint}/indexes/{index_name}/docs/index?api-version=2024-07-01"
                        http_requests.post(delete_url, headers=headers, json={"value": delete_actions})

                # Reset + relance de l'indexer
                http_requests.post(f"{search_endpoint}/indexers/{indexer_name}/reset?api-version=2024-07-01", headers=headers)
                http_requests.post(f"{search_endpoint}/indexers/{indexer_name}/run?api-version=2024-07-01", headers=headers)
                logger.info(f"🔄 Indexer P{platform_id} ({indexer_name}) déclenché")

            return jsonify({
                "success": True,
                "message": f"PDF '{file.filename}' uploadé pour P{platform_id}, indexation lancée",
                "pdf_filename": file.filename,
                "pdf_uploaded_at": now,
                "pdf_url": _make_pdf_url(platform_id, file.filename),
            }), 200

        except Exception as e:
            logger.error(f"❌ Erreur upload PDF RAG P{platform_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── GET /api/hr/platforms/<id>/course-time ───────────────────────────
    @hr_bp.route("/api/hr/platforms/<int:platform_id>/course-time", methods=["GET"])
    def get_platform_course_time(platform_id):
        """Lire l'heure du cours d'une plateforme (P1=local, P2+=proxy)"""
        denied = _require_admin()
        if denied:
            return denied

        if _is_local_platform(platform_id):
            try:
                conn = None if schedule_store_is_postgres() else get_db_connection()
                cursor = conn.cursor() if conn is not None else None
                schedule_summary = get_course_schedule_details(cursor, platform_id)
                if conn is not None:
                    conn.close()
                from services.time_service import get_heure_debut_cours
                heure = get_heure_debut_cours(platform_id)
                payload = {
                    "success": True,
                    "date_cours": heure.strftime("%Y-%m-%d"),
                    "heure_cours": heure.strftime("%H:%M"),
                    "has_schedule": bool(schedule_summary),
                }
                if schedule_summary:
                    payload.update({
                        "heure_cours": schedule_summary.get("start_time") or payload["heure_cours"],
                        "schedule": schedule_summary,
                    })
                return jsonify(payload), 200
            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 500
        else:
            result, error = _call_platform(platform_id, f"/api/internal/course-time?platform_id={platform_id}", method="GET")
            if error:
                return jsonify({"success": False, "error": error}), 500
            if result is None:
                return jsonify({"success": False, "error": "Plateforme non configurée"}), 400
            return jsonify(result), 200

    def _ensure_course_reminder_recipients(cursor):
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS course_reminder_recipients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(platform_id, email)
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_course_reminder_recipients_platform ON course_reminder_recipients(platform_id)"
        )

    def _attendance_record_from_logs(log_rows):
        slots = []
        total = 0
        for arrivee, depart in log_rows:
            if not arrivee or not depart:
                continue
            try:
                start = str(arrivee)[11:16]
                end = str(depart)[11:16]
                start_minutes = _time_to_minutes(start)
                end_minutes = _time_to_minutes(end)
                if end_minutes <= start_minutes:
                    continue
            except Exception:
                continue
            slots.append({"start": start, "end": end})
            total += end_minutes - start_minutes
        return {
            "id": None,
            "slots": slots,
            "total_minutes": total,
            "status": "present" if total > 0 else "absent",
            "notes": "",
            "source": "logs" if slots else "empty",
        }

    @hr_bp.route("/api/hr/platforms/<int:platform_id>/attendance", methods=["GET"])
    def get_platform_attendance(platform_id):
        denied = _require_admin()
        if denied:
            return denied
        try:
            course_date = _parse_course_date(request.args.get("course_date"))
            if schedule_store_is_postgres():
                center_account_id = (
                    session.get("admin_account_id")
                    if session.get("admin_account_type") == "training_center"
                    else None
                )
                return jsonify(get_attendance_dashboard(
                    platform_id,
                    course_date,
                    center_account_id=center_account_id,
                )), 200
            conn = get_db_connection()
            cursor = conn.cursor()
            _ensure_student_attendance_records(cursor)

            platform = _get_accessible_platform(cursor, platform_id)
            if not platform:
                conn.close()
                return jsonify({"success": False, "error": "Plateforme introuvable"}), 404

            cursor.execute(
                """
                SELECT id, email, nom, prenom, is_active
                FROM student_profiles
                WHERE platform_id = ?
                ORDER BY prenom COLLATE NOCASE, nom COLLATE NOCASE, email COLLATE NOCASE
                """,
                (platform_id,),
            )
            student_rows = cursor.fetchall()
            student_ids = [row[0] for row in student_rows]

            saved_by_student = {}
            if student_ids:
                placeholders = ",".join("?" for _ in student_ids)
                cursor.execute(
                    f"""
                    SELECT id, platform_id, student_profile_id, course_date, slots_json,
                           total_minutes, status, notes, created_at, updated_at
                    FROM student_attendance_records
                    WHERE platform_id = ?
                      AND course_date = ?
                      AND student_profile_id IN ({placeholders})
                    """,
                    [platform_id, course_date] + student_ids,
                )
                saved_by_student = {
                    row[2]: _serialize_attendance_row(row)
                    for row in cursor.fetchall()
                }

            cursor.execute(
                """
                SELECT nom, prenom, arrivee, depart
                FROM logs
                WHERE platform_id = ?
                  AND substr(arrivee, 1, 10) = ?
                ORDER BY arrivee ASC
                """,
                (platform_id, course_date),
            )
            logs_by_name = {}
            for nom, prenom, arrivee, depart in cursor.fetchall():
                key = (str(nom or "").strip().lower(), str(prenom or "").strip().lower())
                logs_by_name.setdefault(key, []).append((arrivee, depart))

            cursor.execute(
                """
                SELECT student_profile_id, SUM(total_minutes), COUNT(DISTINCT course_date), MAX(course_date)
                FROM student_attendance_records
                WHERE platform_id = ?
                GROUP BY student_profile_id
                """,
                (platform_id,),
            )
            totals_by_student = {
                row[0]: {
                    "total_minutes": int(row[1] or 0),
                    "recorded_days": int(row[2] or 0),
                    "last_course_date": row[3],
                }
                for row in cursor.fetchall()
            }

            cursor.execute(
                """
                SELECT course_date, COUNT(*), SUM(total_minutes)
                FROM student_attendance_records
                WHERE platform_id = ?
                GROUP BY course_date
                ORDER BY course_date DESC
                LIMIT 20
                """,
                (platform_id,),
            )
            recent_dates = [
                {
                    "course_date": row[0],
                    "student_count": int(row[1] or 0),
                    "total_minutes": int(row[2] or 0),
                }
                for row in cursor.fetchall()
            ]

            cursor.execute(
                """
                SELECT course_date, COUNT(*), SUM(total_minutes)
                FROM student_attendance_records
                WHERE platform_id = ?
                GROUP BY course_date
                ORDER BY course_date DESC
                LIMIT 120
                """,
                (platform_id,),
            )
            weeks_by_start = {}
            for course_date_row, student_count, total_minutes in cursor.fetchall():
                week_start, week_end = _attendance_week_bounds(course_date_row)
                week = weeks_by_start.setdefault(week_start, {
                    "week_start": week_start,
                    "week_end": week_end,
                    "date_count": 0,
                    "student_count": 0,
                    "total_minutes": 0,
                })
                week["date_count"] += 1
                week["student_count"] += int(student_count or 0)
                week["total_minutes"] += int(total_minutes or 0)
            recent_weeks = sorted(
                weeks_by_start.values(),
                key=lambda item: item["week_start"],
                reverse=True,
            )[:12]
            conn.close()

            students = []
            for row in student_rows:
                student_id, email, nom, prenom, is_active = row
                attendance = saved_by_student.get(student_id)
                if not attendance:
                    key = (str(nom or "").strip().lower(), str(prenom or "").strip().lower())
                    attendance = {
                        "platform_id": platform_id,
                        "student_profile_id": student_id,
                        "course_date": course_date,
                        **_attendance_record_from_logs(logs_by_name.get(key, [])),
                    }
                students.append({
                    "id": student_id,
                    "email": email,
                    "nom": nom,
                    "prenom": prenom,
                    "is_active": bool(is_active),
                    "attendance": attendance,
                    "totals": totals_by_student.get(student_id, {
                        "total_minutes": 0,
                        "recorded_days": 0,
                        "last_course_date": None,
                    }),
                })

            return jsonify({
                "success": True,
                "platform": {"id": platform[0], "name": platform[1]},
                "course_date": course_date,
                "students": students,
                "recent_dates": recent_dates,
                "recent_weeks": recent_weeks,
            }), 200
        except LookupError as exc:
            return jsonify({"success": False, "error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        except Exception as e:
            logger.error(f"❌ Erreur get attendance P{platform_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/platforms/<int:platform_id>/attendance/<int:student_id>", methods=["POST"])
    def save_student_attendance(platform_id, student_id):
        denied = _require_admin()
        if denied:
            return denied
        if schedule_store_is_postgres():
            return jsonify({
                "success": False,
                "error": "Les présences sont enregistrées automatiquement depuis la salle de cours.",
            }), 405
        try:
            data = request.get_json(silent=True) or {}
            course_date = _parse_course_date(data.get("course_date"))
            slots, total_minutes = _normalize_attendance_slots(data.get("slots") or [])
            requested_status = str(data.get("status") or "").strip().lower()
            allowed_statuses = {"present", "partial", "absent", "excused"}
            if requested_status not in allowed_statuses:
                requested_status = "present" if total_minutes > 0 else "absent"
            if total_minutes == 0 and requested_status == "present":
                requested_status = "absent"
            notes = str(data.get("notes") or "").strip()[:1000]
            now = _now_str()

            conn = get_db_connection()
            cursor = conn.cursor()
            _ensure_student_attendance_records(cursor)
            platform = _get_accessible_platform(cursor, platform_id)
            if not platform:
                conn.close()
                return jsonify({"success": False, "error": "Plateforme introuvable"}), 404
            cursor.execute(
                "SELECT id FROM student_profiles WHERE id = ? AND platform_id = ?",
                (student_id, platform_id),
            )
            if not cursor.fetchone():
                conn.close()
                return jsonify({"success": False, "error": "Élève introuvable"}), 404

            cursor.execute(
                """
                INSERT INTO student_attendance_records
                    (platform_id, student_profile_id, course_date, slots_json, total_minutes, status, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform_id, student_profile_id, course_date)
                DO UPDATE SET
                    slots_json = excluded.slots_json,
                    total_minutes = excluded.total_minutes,
                    status = excluded.status,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                (
                    platform_id,
                    student_id,
                    course_date,
                    json.dumps(slots, ensure_ascii=False),
                    total_minutes,
                    requested_status,
                    notes,
                    now,
                    now,
                ),
            )
            conn.commit()
            cursor.execute(
                """
                SELECT id, platform_id, student_profile_id, course_date, slots_json,
                       total_minutes, status, notes, created_at, updated_at
                FROM student_attendance_records
                WHERE platform_id = ? AND student_profile_id = ? AND course_date = ?
                """,
                (platform_id, student_id, course_date),
            )
            record = _serialize_attendance_row(cursor.fetchone())
            conn.close()
            return jsonify({"success": True, "record": record}), 200
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        except Exception as e:
            logger.error(f"❌ Erreur save attendance P{platform_id} S{student_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/platforms/<int:platform_id>/attendance/export", methods=["GET"])
    def export_platform_attendance(platform_id):
        denied = _require_admin()
        if denied:
            return denied
        try:
            if schedule_store_is_postgres():
                center_account_id = (
                    session.get("admin_account_id")
                    if session.get("admin_account_type") == "training_center"
                    else None
                )
                if not attendance_repo.get_accessible_platform(platform_id, center_account_id):
                    return jsonify({"success": False, "error": "Plateforme introuvable"}), 404
                course_date = _parse_course_date(request.args.get("course_date"))
                export_row = attendance_repo.get_ready_daily_export_for_date(
                    platform_id,
                    course_date,
                    center_account_id=center_account_id,
                )
                if not export_row:
                    return jsonify({
                        "success": False,
                        "error": "Le fichier de cette journée sera disponible le lendemain matin.",
                    }), 404
                excel_bytes = download_daily_attendance_excel(export_row)
                return send_file(
                    io.BytesIO(excel_bytes),
                    as_attachment=True,
                    download_name=export_row["filename"],
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            conn = get_db_connection()
            cursor = conn.cursor()
            _ensure_student_attendance_records(cursor)
            platform = _get_accessible_platform(cursor, platform_id)
            if not platform:
                conn.close()
                return jsonify({"success": False, "error": "Plateforme introuvable"}), 404
            week_start = request.args.get("week_start")
            week_end = request.args.get("week_end")
            where_sql = "ar.platform_id = ?"
            query_params = [platform_id]
            export_label = ""
            if week_start or week_end:
                start_date = _parse_course_date(week_start)
                end_date = _parse_course_date(week_end or week_start)
                if end_date < start_date:
                    start_date, end_date = end_date, start_date
                where_sql += " AND ar.course_date BETWEEN ? AND ?"
                query_params.extend([start_date, end_date])
                export_label = f"-semaine-{start_date}"
            cursor.execute(
                f"""
                SELECT ar.course_date, sp.nom, sp.prenom, sp.email, ar.status,
                       ar.slots_json, ar.total_minutes, ar.notes
                FROM student_attendance_records ar
                JOIN student_profiles sp ON sp.id = ar.student_profile_id
                WHERE {where_sql}
                ORDER BY ar.course_date ASC, sp.nom COLLATE NOCASE, sp.prenom COLLATE NOCASE
                """,
                query_params,
            )
            records = []
            for course_date, nom, prenom, email, status, slots_json, total_minutes, notes in cursor.fetchall():
                try:
                    slots = json.loads(slots_json or "[]")
                except Exception:
                    slots = []
                records.append({
                    "course_date": course_date,
                    "nom": nom,
                    "prenom": prenom,
                    "email": email,
                    "status": status,
                    "slots": slots,
                    "total_minutes": int(total_minutes or 0),
                    "notes": notes or "",
                })
            conn.close()
            tmp_file = generate_attendance_excel_export(records, platform_name=platform[1])
            filename = f"presences-{slugify(platform[1], fallback=f'plateforme-{platform_id}')}{export_label}.xlsx"
            return send_file(
                tmp_file,
                as_attachment=True,
                download_name=filename,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception as e:
            logger.error(f"❌ Erreur export attendance P{platform_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/platforms/<int:platform_id>/attendance/exports/<int:export_id>", methods=["GET"])
    def download_platform_attendance_export(platform_id, export_id):
        denied = _require_admin()
        if denied:
            return denied
        try:
            center_account_id = (
                session.get("admin_account_id")
                if session.get("admin_account_type") == "training_center"
                else None
            )
            if not attendance_repo.get_accessible_platform(platform_id, center_account_id):
                return jsonify({"success": False, "error": "Plateforme introuvable"}), 404
            export_row = attendance_repo.get_daily_export(
                export_id,
                platform_id=platform_id,
                center_account_id=center_account_id,
            )
            if not export_row or export_row.get("status") != "ready":
                return jsonify({"success": False, "error": "Fichier de présence indisponible"}), 404
            excel_bytes = download_daily_attendance_excel(export_row)
            return send_file(
                io.BytesIO(excel_bytes),
                as_attachment=True,
                download_name=export_row["filename"],
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception:
            logger.exception(
                "❌ Téléchargement présence impossible P%s export=%s",
                platform_id,
                export_id,
            )
            return jsonify({"success": False, "error": "Téléchargement momentanément indisponible"}), 500

    @hr_bp.route("/api/hr/platforms/<int:platform_id>/student-emails", methods=["GET"])
    def get_platform_student_emails(platform_id):
        denied = _require_admin()
        if denied:
            return denied
        try:
            recipients = list_explicit_course_reminder_recipients(platform_id)
            return jsonify({"success": True, "recipients": recipients}), 200
        except Exception as e:
            logger.error(f"❌ Erreur get student emails P{platform_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/platforms/<int:platform_id>/student-emails", methods=["POST"])
    def add_platform_student_emails(platform_id):
        denied = _require_admin()
        if denied:
            return denied
        if (
            request.content_length is not None
            and request.content_length > _MAX_STUDENT_EMAIL_REQUEST_BYTES
        ):
            return jsonify({
                "success": False,
                "error": "Lot trop volumineux (1000 emails maximum)",
            }), 413
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({"success": False, "error": "Corps JSON invalide"}), 400
        raw_students = data.get("students")
        if raw_students is not None:
            if not isinstance(raw_students, list):
                return jsonify({"success": False, "error": "students doit être une liste"}), 400
            if len(raw_students) > _MAX_STUDENT_EMAILS_PER_REQUEST:
                return jsonify({"success": False, "error": "1000 élèves maximum par lot"}), 413
            students = []
            seen = set()
            for item in raw_students:
                if not isinstance(item, dict):
                    return jsonify({"success": False, "error": "Chaque élève doit contenir prénom, nom et e-mail"}), 400
                try:
                    email = _normalize_student_email(item.get("email"))
                except ValueError as exc:
                    return jsonify({"success": False, "error": str(exc)}), 400
                nom = str(item.get("nom") or "").strip()
                prenom = str(item.get("prenom") or "").strip()
                if not nom or not prenom:
                    return jsonify({"success": False, "error": "Prénom et nom requis pour chaque élève"}), 400
                if email not in seen:
                    seen.add(email)
                    students.append({"email": email, "nom": nom, "prenom": prenom})
            if not students:
                return jsonify({"success": False, "error": "Ajoutez au moins un élève"}), 400
            try:
                recipients = add_explicit_course_reminder_recipients(
                    platform_id, students, created_at=datetime.now(FRANCE_TZ)
                )
                return jsonify({"success": True, "recipients": recipients}), 201
            except Exception as e:
                logger.error(f"❌ Erreur add students P{platform_id}: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        raw_emails = data.get("emails")
        if raw_emails is None:
            raw_emails = data.get("email", "")
        if isinstance(raw_emails, str):
            candidates = raw_emails.replace(";", ",").replace("\n", ",").split(",")
        elif isinstance(raw_emails, list):
            candidates = raw_emails
        else:
            return jsonify({"success": False, "error": "emails doit être une liste ou du texte"}), 400
        if len(candidates) > _MAX_STUDENT_EMAILS_PER_REQUEST:
            return jsonify({
                "success": False,
                "error": "1000 emails maximum par lot; ajoutez les suivants dans un autre lot",
            }), 413
        emails = []
        seen = set()
        for item in candidates:
            if item is None or not str(item).strip():
                continue
            try:
                email = _normalize_student_email(item)
            except ValueError as exc:
                return jsonify({"success": False, "error": str(exc)}), 400
            if email not in seen:
                seen.add(email)
                emails.append(email)
        if not emails:
            return jsonify({"success": False, "error": "Ajoute au moins un email"}), 400
        try:
            recipients = add_explicit_course_reminder_recipients(
                platform_id,
                emails,
                created_at=datetime.now(FRANCE_TZ),
            )
            return jsonify({"success": True, "recipients": recipients}), 201
        except Exception as e:
            logger.error(f"❌ Erreur add student emails P{platform_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/platforms/<int:platform_id>/student-emails/<int:recipient_id>", methods=["DELETE"])
    def delete_platform_student_email(platform_id, recipient_id):
        denied = _require_admin()
        if denied:
            return denied
        try:
            changed = delete_explicit_course_reminder_recipient(
                platform_id,
                recipient_id,
            )
            if not changed:
                return jsonify({"success": False, "error": "Email introuvable"}), 404
            return jsonify({"success": True}), 200
        except Exception as e:
            logger.error(f"❌ Erreur delete student email P{platform_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/platforms/<int:platform_id>/reminder-rules", methods=["GET"])
    def get_platform_reminder_rules(platform_id):
        denied = _require_admin()
        if denied:
            return denied
        try:
            rules = get_course_reminder_rules(platform_id)
            return jsonify({"success": True, "rules": rules}), 200
        except Exception as e:
            logger.error(f"❌ Erreur get reminder rules P{platform_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/platforms/<int:platform_id>/reminder-rules", methods=["POST"])
    def create_platform_reminder_rule(platform_id):
        denied = _require_admin()
        if denied:
            return denied
        try:
            rule = save_course_reminder_rule(
                platform_id,
                request.get_json(silent=True) or {},
            )
            return jsonify({"success": True, "rule": rule}), 201
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"❌ Erreur create reminder rule P{platform_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route(
        "/api/hr/platforms/<int:platform_id>/reminder-rules/<int:rule_id>",
        methods=["PUT"],
    )
    def update_platform_reminder_rule(platform_id, rule_id):
        denied = _require_admin()
        if denied:
            return denied
        try:
            rule = save_course_reminder_rule(
                platform_id,
                request.get_json(silent=True) or {},
                rule_id=rule_id,
            )
            if not rule:
                return jsonify({"success": False, "error": "Rappel introuvable"}), 404
            return jsonify({"success": True, "rule": rule}), 200
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"❌ Erreur update reminder rule P{platform_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route(
        "/api/hr/platforms/<int:platform_id>/reminder-rules/<int:rule_id>",
        methods=["DELETE"],
    )
    def delete_platform_reminder_rule(platform_id, rule_id):
        denied = _require_admin()
        if denied:
            return denied
        try:
            if not delete_course_reminder_rule(platform_id, rule_id):
                return jsonify({
                    "success": False,
                    "error": "Rappel introuvable ou rappel par défaut à désactiver plutôt qu'à supprimer",
                }), 404
            return jsonify({"success": True}), 200
        except Exception as e:
            logger.error(f"❌ Erreur delete reminder rule P{platform_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── POST /api/hr/platforms/<id>/config-cours ─────────────────────────
    @hr_bp.route("/api/hr/platforms/<int:platform_id>/config-cours", methods=["POST"])
    def proxy_config_cours(platform_id):
        """Configurer l'heure du cours (P1=local, P2+=proxy service-to-service)"""
        denied = _require_admin()
        if denied:
            return denied

        data = request.get_json(silent=True) or {}
        date_str = (data or {}).get("date_cours", "").strip()
        heure_str = (data or {}).get("heure_cours", "").strip()
        weekdays = data.get("weekdays") if "weekdays" in data else None
        allow_imminent = bool(data.get("force_schedule")) and _admin_account_type() in _HR_SUPERADMIN_ACCOUNT_TYPES
        if not heure_str:
            return jsonify({"success": False, "error": "heure_cours requis"}), 400

        if _is_local_platform(platform_id):
            # Appel direct au service local
            conn = None
            try:
                postgres_schedule = schedule_store_is_postgres()
                conn = None if postgres_schedule else get_db_connection()
                cursor = conn.cursor() if conn is not None else None
                schedule_update = update_course_schedule(
                    cursor,
                    platform_id,
                    start_time=heure_str,
                    weekdays=weekdays,
                    allow_imminent=allow_imminent,
                )
                if schedule_update:
                    if conn is not None:
                        conn.commit()
                        conn.close()
                        conn = None
                    schedule_details = schedule_update
                    locked_count = int(schedule_update.get("locked_future_sessions") or 0)
                    message = "Planning des journées mis à jour"
                    if locked_count:
                        suffix = "s" if locked_count > 1 else ""
                        message = (
                            f"Planning mis à jour. {locked_count} séance{suffix} dans les 72 h "
                            "reste inchangée" + ("s" if locked_count > 1 else "") + "."
                        )
                    return jsonify({
                        "success": True,
                        "message": message,
                        "schedule": schedule_details or schedule_update,
                    }), 200
                if postgres_schedule:
                    folder_count = len(
                        list_course_folder_rows_for_platform(platform_id)["folders"]
                    )
                else:
                    cursor.execute(
                        "SELECT COUNT(*) FROM cours_folders WHERE platform_id = ?",
                        (platform_id,),
                    )
                    folder_count = int((cursor.fetchone() or [0])[0] or 0)
                schedule_update = create_missing_course_schedule(
                    cursor,
                    platform_id,
                    total_training_days=folder_count,
                    start_time=heure_str,
                    date_str=date_str or None,
                    weekdays=weekdays,
                    allow_imminent=allow_imminent,
                )
                if schedule_update:
                    if conn is not None:
                        conn.commit()
                        conn.close()
                        conn = None
                    schedule_details = schedule_update
                    return jsonify({
                        "success": True,
                        "message": "Planning des journées créé",
                        "schedule": schedule_details or schedule_update,
                    }), 200
                if conn is not None:
                    conn.close()
                    conn = None

                if not date_str:
                    return jsonify({"success": False, "error": "date_cours requis pour une plateforme sans planning automatique"}), 400
                from services.time_service import set_heure_debut_cours
                if heure_str.count(':') == 1:
                    datetime_str = f"{date_str} {heure_str}:00"
                else:
                    datetime_str = f"{date_str} {heure_str}"
                nouvelle_heure_naive = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
                nouvelle_heure_fr = FRANCE_TZ.localize(nouvelle_heure_naive)
                set_heure_debut_cours(nouvelle_heure_fr, platform_id)
                return jsonify({
                    "success": True,
                    "message": f"Cours programmé pour le {date_str} à {heure_str}",
                }), 200
            except ValueError as e:
                if conn:
                    conn.close()
                return jsonify({"success": False, "error": str(e)}), 400
            except Exception as e:
                if conn:
                    conn.close()
                logger.error(f"❌ Erreur config-cours P{platform_id}: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        else:
            # Ajouter platform_id au payload pour que le backend distant sache quelle plateforme mettre à jour
            payload = {**data, "platform_id": platform_id}
            result, error = _call_platform(platform_id, "/api/internal/config-cours", json_data=payload)
            if error:
                return jsonify({"success": False, "error": error}), 500
            if result is None:
                return jsonify({"success": False, "error": "Plateforme non configurée"}), 400
            return jsonify(result), 200

    @hr_bp.route(
        "/api/hr/platforms/<int:platform_id>/sessions/<int:session_id>/audio/retry",
        methods=["POST"],
    )
    def retry_platform_session_audio(platform_id, session_id):
        denied = _require_admin()
        if denied:
            return denied
        try:
            payload, status = retry_scheduled_audio_generation(platform_id, session_id)
            if status >= 500:
                logger.error(
                    "SCHEDULED_AUDIO_MANUAL_RETRY_FAILED platform_id=%s session_id=%s",
                    platform_id,
                    session_id,
                )
                return jsonify({"success": False, "error": "La reprise audio n'a pas pu démarrer"}), status
            return jsonify(payload), status
        except Exception:
            logger.exception(
                "SCHEDULED_AUDIO_MANUAL_RETRY_CRASHED platform_id=%s session_id=%s",
                platform_id,
                session_id,
            )
            return jsonify({"success": False, "error": "La reprise audio n'a pas pu démarrer"}), 500

    @hr_bp.route(
        "/api/hr/platforms/<int:platform_id>/course-materials",
        methods=["GET"],
    )
    def list_platform_course_materials(platform_id):
        """List pipeline-generated PDF supports for this platform's days."""
        denied = _require_admin()
        if denied:
            return denied
        try:
            from services.daily_course_pdf_service import (
                list_daily_course_pdf_materials,
                publish_pipeline_course_pdfs,
            )

            sessions = list_course_sessions(int(platform_id), limit=1000)
            materials = list_daily_course_pdf_materials(
                int(platform_id),
                sessions,
            )
            # Compatibility backfill for formations whose text pipeline
            # completed before daily supports became a finalization artifact.
            # The publisher overwrites stable blob keys, so retrying is safe.
            if len(materials) < len(sessions):
                try:
                    from repositories.pipeline_repository import (
                        find_latest_pipeline_job_id_for_platform,
                    )
                    from services.formation_pipeline_service import get_job

                    job_id = find_latest_pipeline_job_id_for_platform(
                        int(platform_id)
                    )
                    job = get_job(int(job_id)) if job_id else None
                    if job and job.get("status") in {
                        "text_ready",
                        "audio_running",
                        "audio_launched",
                        "audio_completed",
                    }:
                        publish_pipeline_course_pdfs(
                            job_id=int(job_id),
                            platform_id=int(platform_id),
                        )
                        materials = list_daily_course_pdf_materials(
                            int(platform_id),
                            sessions,
                        )
                except Exception:
                    logger.exception(
                        "COURSE_PDF_COMPAT_BACKFILL_FAILED platform_id=%s",
                        platform_id,
                    )
            return jsonify({"success": True, "materials": materials}), 200
        except Exception:
            logger.exception(
                "COURSE_PDF_LIST_FAILED platform_id=%s",
                platform_id,
            )
            return jsonify({
                "success": False,
                "error": "Les supports PDF ne peuvent pas être chargés",
            }), 500

    @hr_bp.route(
        "/api/hr/platforms/<int:platform_id>/sessions/<int:session_id>/postpone/preview",
        methods=["POST"],
    )
    def preview_platform_session_postponement(platform_id, session_id):
        denied = _require_admin()
        if denied:
            return denied
        try:
            data = request.get_json(silent=True) or {}
            preview = preview_course_session_postponement(
                platform_id,
                session_id,
                mode=data.get("mode") or "next_occurrence",
                scheduled_at=data.get("scheduled_at"),
            )
            return jsonify({"success": True, "preview": preview}), 200
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 409
        except Exception:
            logger.exception(
                "COURSE_SESSION_POSTPONEMENT_PREVIEW_FAILED platform_id=%s session_id=%s",
                platform_id,
                session_id,
            )
            return jsonify({"success": False, "error": "Le report ne peut pas être préparé"}), 500

    @hr_bp.route(
        "/api/hr/platforms/<int:platform_id>/sessions/<int:session_id>/postpone",
        methods=["POST"],
    )
    def postpone_platform_session(platform_id, session_id):
        denied = _require_admin()
        if denied:
            return denied
        try:
            data = request.get_json(silent=True) or {}
            idempotency_key = request.headers.get("Idempotency-Key") or data.get("idempotency_key")
            if not str(idempotency_key or "").strip():
                return jsonify({
                    "success": False,
                    "error": "La demande de report est incomplète. Rechargez la page puis réessayez.",
                }), 400
            result = postpone_course_session(
                platform_id,
                session_id,
                mode=data.get("mode") or "next_occurrence",
                scheduled_at=data.get("scheduled_at"),
                reason=data.get("reason"),
                idempotency_key=idempotency_key,
                actor_account_id=session.get("admin_account_id"),
            )
            schedule = get_course_schedule_details_for_platform(platform_id)
            return jsonify({
                "success": True,
                "message": f"Le cours {result['lesson_number']} a bien été reporté",
                "postponement": result,
                "schedule": schedule,
            }), 200
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 409
        except Exception:
            logger.exception(
                "COURSE_SESSION_POSTPONEMENT_FAILED platform_id=%s session_id=%s",
                platform_id,
                session_id,
            )
            return jsonify({"success": False, "error": "Le cours n'a pas pu être reporté"}), 500

    @hr_bp.route(
        "/api/hr/platforms/<int:platform_id>/sessions/<int:session_id>",
        methods=["DELETE"],
    )
    def cancel_platform_session(platform_id, session_id):
        denied = _require_admin()
        if denied:
            return denied
        return jsonify({
            "success": False,
            "error": "Une séance ne se supprime plus : utilisez « Reporter cette séance ».",
        }), 410

    # ─── POST /api/internal/auto-schedule ────────────────────────────────
    @hr_bp.route("/api/internal/auto-schedule", methods=["POST"])
    def auto_schedule():
        """Configure automatiquement les horaires des cours pour la semaine suivante.
        Protégé par X-Platform-Key. Appelé par Azure Function (Timer Trigger).

        Schedule par défaut :
          - P1 : vendredi à 9h00
          - P2 : lundi à 9h00
          - P3 : lundi à 9h00

        Corps JSON optionnel pour surcharger :
          { "schedule": [{"platform_id": 1, "weekday": 4, "hour": 9}] }
          weekday : 0=lundi, 1=mardi, 2=mercredi, 3=jeudi, 4=vendredi, 5=samedi, 6=dimanche

        Sans corps `schedule`, utilise le planning persistant créé par le flow
        "Nouveau professeur IA", pousse la prochaine séance dans cours_config,
        puis lance l'audio uniquement pour les séances dues dans la fenêtre H-72.
        """
        api_key = request.headers.get("X-Platform-Key", "")
        expected_key = os.environ.get("PLATFORM_API_KEY", "")
        if not expected_key or api_key != expected_key:
            return jsonify({"success": False, "error": "Clé invalide"}), 403

        DEFAULT_SCHEDULE = [
            {"platform_id": 1, "weekday": 4, "hour": 9},  # vendredi
            {"platform_id": 2, "weekday": 0, "hour": 9},  # lundi
            {"platform_id": 3, "weekday": 0, "hour": 9},  # lundi
            {"platform_id": 4, "weekday": 3, "hour": 9},  # jeudi
        ]

        data = request.get_json(silent=True) or {}
        if "schedule" not in data:
            try:
                results = run_scheduler_tick(data.get("platform_ids"))
                audio_results = process_due_audio_generations(
                    data.get("platform_ids"),
                    dry_run=bool(data.get("dry_run_audio", False)),
                    horizon_hours=data.get("audio_horizon_hours"),
                )
                return jsonify({
                    "success": True,
                    "mode": "course_sessions",
                    "results": results,
                    "audio_results": audio_results,
                }), 200
            except Exception as e:
                logger.error(f"❌ Auto-schedule course_sessions : {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        schedule = data.get("schedule", DEFAULT_SCHEDULE)

        today = datetime.now(FRANCE_TZ)
        results = []

        for item in schedule:
            platform_id = item["platform_id"]
            weekday = item["weekday"]
            hour = item.get("hour", 9)
            minute = item.get("minute", 0)

            # Prochaine occurrence de ce jour de la semaine (jamais aujourd'hui)
            days_ahead = weekday - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            next_date = today + timedelta(days=days_ahead)

            date_str = next_date.strftime("%Y-%m-%d")
            heure_str = f"{hour:02d}:{minute:02d}"

            if _is_local_platform(platform_id):
                try:
                    from services.time_service import set_heure_debut_cours
                    nouvelle_heure_naive = datetime.strptime(
                        f"{date_str} {heure_str}:00", "%Y-%m-%d %H:%M:%S"
                    )
                    nouvelle_heure_fr = FRANCE_TZ.localize(nouvelle_heure_naive)
                    set_heure_debut_cours(nouvelle_heure_fr, platform_id)
                    results.append({"platform_id": platform_id, "success": True, "scheduled": f"{date_str} {heure_str}"})
                    logger.info(f"📅 Auto-schedule P{platform_id} : {date_str} {heure_str}")
                except Exception as e:
                    results.append({"platform_id": platform_id, "success": False, "error": str(e)})
                    logger.error(f"❌ Auto-schedule P{platform_id} : {e}")
            else:
                result, error = _call_platform(
                    platform_id,
                    "/api/internal/config-cours",
                    json_data={"date_cours": date_str, "heure_cours": heure_str, "platform_id": platform_id},
                )
                if error:
                    results.append({"platform_id": platform_id, "success": False, "error": error})
                    logger.error(f"❌ Auto-schedule P{platform_id} : {error}")
                else:
                    results.append({"platform_id": platform_id, "success": True, "scheduled": f"{date_str} {heure_str}"})
                    logger.info(f"📅 Auto-schedule P{platform_id} : {date_str} {heure_str}")

        all_ok = all(r["success"] for r in results)
        return jsonify({"success": all_ok, "results": results}), 200

    @hr_bp.route("/api/internal/reminders/tick", methods=["POST"])
    def reminders_tick():
        """Traite les rappels élèves dus.

        Le backend calcule les rappels depuis course_sessions :
        - veille au soir (18h par défaut)
        - 5 minutes avant le cours

        Si REMINDER_WEBHOOK_URL est configuré, il poste les rappels dessus et
        marque les séances comme envoyées. Sinon, `dry_run=true` permet de
        récupérer les rappels dus sans mutation pour brancher l'automatisation
        existante.
        """
        api_key = request.headers.get("X-Platform-Key", "")
        expected_key = os.environ.get("PLATFORM_API_KEY", "")
        if not expected_key or api_key != expected_key:
            return jsonify({"success": False, "error": "Clé invalide"}), 403

        data = request.get_json(silent=True) or {}
        origin = (
            data.get("frontend_url")
            or os.environ.get("FRONTEND_PUBLIC_URL")
            or os.environ.get("PLATFORM_1_FRONTEND_URL")
            or request.headers.get("Origin")
        )
        dry_run = bool(data.get("dry_run", False))

        try:
            results = process_due_reminders(base_url=origin, dry_run=dry_run)
            all_ok = all(item.get("success") for item in results)
            return jsonify({"success": all_ok, "results": results}), 200
        except Exception as e:
            logger.error(f"❌ Reminders tick : {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── GET /api/hr/platforms/<id>/backup-status ─────────────────────────
    @hr_bp.route("/api/hr/platforms/<int:platform_id>/backup-status", methods=["GET"])
    def backup_status(platform_id):
        """Retourne l'état courant du job de backup"""
        denied = _require_admin()
        if denied:
            return denied

        job = state.backup_jobs.get(platform_id)
        if not job:
            return jsonify({"success": True, "step": 0, "step_status": "idle"}), 200

        return jsonify({"success": True, **job}), 200

    # ─── Routes Cours Folders ───────────────────────────────────────────────
    # Azure Blob Storage pour les cours (plus de stockage local)
    from services.azure_blob_service import (
        upload_blob, download_blob, delete_blob, delete_blobs_by_prefix,
        build_blob_path, CONTAINER_DOCUMENTS, CONTAINER_AUDIOS
    )

    @hr_bp.route("/api/hr/platforms/<int:platform_id>/cours-folders", methods=["GET"])
    def get_cours_folders(platform_id):
        """Liste les dossiers de cours d'une plateforme"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            result = list_course_folder_rows_for_platform(platform_id)
            return jsonify({
                "success": True,
                "folders": result["folders"],
                "platform_id": result["platform_id"],
                "source_platform_id": result["source_platform_id"],
            }), 200
        except Exception as e:
            logger.error(f"❌ Erreur get_cours_folders: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route(
        "/api/hr/platforms/<int:platform_id>/next-course-selection",
        methods=["GET"],
    )
    def get_next_course_selection(platform_id):
        """Describe the course currently bound to one upcoming occurrence."""
        denied = _require_admin()
        if denied:
            return denied
        platform_denied = _require_hr_resource_access("platform", platform_id)
        if platform_denied:
            return platform_denied

        raw_session_id = request.args.get("session_id")
        if raw_session_id not in (None, ""):
            try:
                session_id = int(raw_session_id)
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "session_id invalide"}), 400
            if session_id <= 0:
                return jsonify({"success": False, "error": "session_id invalide"}), 400
            course_session = get_audio_generation_session(platform_id, session_id)
        else:
            course_session = get_next_course_session(platform_id)

        if not course_session or str(course_session.get("status") or "") not in {"planned", "active"}:
            return jsonify({
                "success": True,
                "session": None,
                "scheduled_course": None,
                "selected_course": None,
                "is_manual_override": False,
            }), 200

        folder_result = list_course_folder_rows_for_platform(platform_id)
        folders = list(folder_result.get("folders") or [])

        def serialize_course(folder):
            if not folder:
                return None
            folder_id = int(folder["id"])
            folder_index = next(
                (index for index, item in enumerate(folders) if int(item["id"]) == folder_id),
                int(folder.get("position") or 0),
            )
            day_number = folder_index + 1
            return {
                "id": folder_id,
                "name": str(folder.get("name") or f"Jour {day_number}"),
                "day_number": day_number,
                "label": f"Jour {day_number} — {folder.get('name') or f'Jour {day_number}'}",
            }

        session_index = int(course_session.get("session_index") or 0)
        scheduled_folder = (
            folders[session_index - 1]
            if 0 < session_index <= len(folders)
            else None
        )
        selected_folder = scheduled_folder
        selected_folder_id = course_session.get("audio_folder_id")
        if selected_folder_id:
            selected_folder = next(
                (
                    folder for folder in folders
                    if int(folder["id"]) == int(selected_folder_id)
                ),
                None,
            )
            if selected_folder is None:
                selected_folder = get_course_folder_identity(int(selected_folder_id))

        scheduled_course = serialize_course(scheduled_folder)
        selected_course = serialize_course(selected_folder)
        scheduled_at = course_session.get("scheduled_at")
        if hasattr(scheduled_at, "isoformat"):
            scheduled_at = scheduled_at.isoformat()
        elif scheduled_at:
            try:
                parsed_scheduled_at = datetime.fromisoformat(str(scheduled_at))
                if parsed_scheduled_at.tzinfo is None:
                    parsed_scheduled_at = FRANCE_TZ.localize(parsed_scheduled_at)
                scheduled_at = parsed_scheduled_at.astimezone(FRANCE_TZ).isoformat()
            except (TypeError, ValueError):
                scheduled_at = str(scheduled_at)

        return jsonify({
            "success": True,
            "session": {
                "id": int(course_session["id"]),
                "session_index": session_index,
                "scheduled_at": scheduled_at,
                "status": str(course_session.get("status") or "planned"),
            },
            "scheduled_course": scheduled_course,
            "selected_course": selected_course,
            "is_manual_override": bool(
                scheduled_course
                and selected_course
                and int(scheduled_course["id"]) != int(selected_course["id"])
            ),
        }), 200

    @hr_bp.route("/api/hr/platforms/<int:platform_id>/cours-folders", methods=["POST"])
    def create_cours_folder(platform_id):
        """Crée un nouveau dossier de cours"""
        denied = _require_admin()
        if denied:
            return denied

        data = request.get_json()
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"success": False, "error": "Le nom du dossier est requis"}), 400

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            # Position = max existant + 1 pour cette plateforme
            cursor.execute("SELECT COALESCE(MAX(position), -1) FROM cours_folders WHERE platform_id = ?", (platform_id,))
            max_pos = cursor.fetchone()[0]
            new_position = max_pos + 1
            cursor.execute(
                "INSERT INTO cours_folders (platform_id, name, position) VALUES (?, ?, ?)",
                (platform_id, name, new_position)
            )
            folder_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return jsonify({"success": True, "id": folder_id, "name": name, "position": new_position}), 201
        except Exception as e:
            logger.error(f"❌ Erreur create_cours_folder: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>", methods=["DELETE"])
    def delete_cours_folder(folder_id):
        """Supprime un dossier et tous ses documents (Azure + DB)"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Récupérer le platform_id et les documents
            cursor.execute("SELECT platform_id FROM cours_folders WHERE id = ?", (folder_id,))
            folder_row = cursor.fetchone()
            if not folder_row:
                conn.close()
                return jsonify({"success": False, "error": "Dossier non trouvé"}), 404
            platform_id = folder_row[0]

            # Supprimer tous les blobs Azure avec le préfixe du dossier
            prefix = f"platform-{platform_id}/folder-{folder_id}/"
            delete_blobs_by_prefix(CONTAINER_DOCUMENTS, prefix)
            delete_blobs_by_prefix(CONTAINER_AUDIOS, prefix)

            # Supprimer les entrées DB
            cursor.execute("DELETE FROM cours_documents WHERE folder_id = ?", (folder_id,))
            cursor.execute("DELETE FROM cours_folders WHERE id = ?", (folder_id,))
            conn.commit()
            conn.close()

            return jsonify({"success": True}), 200
        except Exception as e:
            logger.error(f"❌ Erreur delete_cours_folder: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>", methods=["PATCH"])
    def rename_cours_folder(folder_id):
        """Renomme un dossier de cours"""
        denied = _require_admin()
        if denied:
            return denied

        data = request.get_json()
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"success": False, "error": "Le nom du dossier est requis"}), 400

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE cours_folders SET name = ? WHERE id = ?", (name, folder_id))
            conn.commit()
            conn.close()
            return jsonify({"success": True}), 200
        except Exception as e:
            logger.error(f"❌ Erreur rename_cours_folder: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/platforms/<int:platform_id>/cours-folders/reorder", methods=["PUT"])
    def reorder_cours_folders(platform_id):
        """Réordonne les dossiers d'une plateforme — reçoit [{id, position}, ...]"""
        denied = _require_admin()
        if denied:
            return denied

        data = request.get_json()
        order = data.get("order", [])  # [{id: int, position: int}, ...]
        if not order:
            return jsonify({"success": False, "error": "ordre manquant"}), 400

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            for item in order:
                cursor.execute(
                    "UPDATE cours_folders SET position = ? WHERE id = ? AND platform_id = ?",
                    (item["position"], item["id"], platform_id)
                )
            conn.commit()
            conn.close()
            logger.info(f"✅ Dossiers plateforme {platform_id} réordonnés: {[i['id'] for i in order]}")
            return jsonify({"success": True}), 200
        except Exception as e:
            logger.error(f"❌ Erreur reorder_cours_folders: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── Routes Cours Documents ─────────────────────────────────────────────
    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/documents", methods=["GET"])
    def get_cours_documents(folder_id):
        """Liste les documents d'un dossier"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT id, filename, original_name, status, audio_filename, created_at
                FROM cours_documents
                WHERE folder_id = ?
                  AND (
                    NOT EXISTS (
                        SELECT 1
                        FROM cours_documents cd
                        WHERE cd.folder_id = cours_documents.folder_id
                          AND {_FINAL_SCRIPT_DOC_WHERE}
                    )
                    OR id = (
                        SELECT cd.id
                        FROM cours_documents cd
                        WHERE cd.folder_id = cours_documents.folder_id
                          AND {_FINAL_SCRIPT_DOC_WHERE}
                        ORDER BY cd.created_at DESC, cd.id DESC
                        LIMIT 1
                    )
                  )
                ORDER BY created_at DESC
            """, (folder_id,))
            docs = [{"id": row[0], "filename": row[1], "original_name": row[2], "status": row[3], "audio_filename": row[4], "created_at": row[5]} for row in cursor.fetchall()]
            conn.close()
            return jsonify({"success": True, "documents": docs}), 200
        except Exception as e:
            logger.error(f"❌ Erreur get_cours_documents: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/upload", methods=["POST"])
    def upload_cours_documents(folder_id):
        """Upload un ou plusieurs fichiers (PDF, TXT, MD) dans un dossier → Azure Blob Storage"""
        denied = _require_admin()
        if denied:
            return denied

        if "files" not in request.files:
            return jsonify({"success": False, "error": "Aucun fichier"}), 400

        files = request.files.getlist("files")
        uploaded = []
        _ALLOWED_EXTENSIONS = (".pdf", ".txt", ".md")

        try:
            import uuid as uuid_mod
            conn = get_db_connection()
            cursor = conn.cursor()

            # Récupérer le platform_id du dossier
            cursor.execute("SELECT platform_id FROM cours_folders WHERE id = ?", (folder_id,))
            folder_row = cursor.fetchone()
            if not folder_row:
                conn.close()
                return jsonify({"success": False, "error": "Dossier non trouvé"}), 404
            platform_id = folder_row[0]

            for file in files:
                if not file or not file.filename:
                    continue
                ext = "." + file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
                if ext not in _ALLOWED_EXTENSIONS:
                    continue

                # Générer un nom unique en conservant l'extension d'origine
                unique_name = f"{uuid_mod.uuid4()}{ext}"
                blob_path = build_blob_path(platform_id, folder_id, unique_name)

                # Upload vers Azure documenttts
                file_bytes = file.read()
                upload_blob(CONTAINER_DOCUMENTS, blob_path, file_bytes)

                # Créer l'entrée DB (filename = blob path dans le container)
                cursor.execute(
                    "INSERT INTO cours_documents (folder_id, filename, original_name, doc_type, status) VALUES (?, ?, ?, 'source', 'uploaded')",
                    (folder_id, blob_path, file.filename)
                )
                doc_id = cursor.lastrowid
                uploaded.append({"id": doc_id, "filename": file.filename})

            conn.commit()
            conn.close()

            return jsonify({"success": True, "uploaded": uploaded}), 200
        except Exception as e:
            logger.error(f"❌ Erreur upload_cours_documents: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-documents/<int:document_id>", methods=["DELETE"])
    def delete_cours_document(document_id):
        """Supprime un document et son audio (Azure + DB)"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT filename, audio_filename FROM cours_documents WHERE id = ?", (document_id,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return jsonify({"success": False, "error": "Document non trouvé"}), 404

            filename, audio_filename = row

            # Supprimer le PDF sur Azure
            delete_blob(CONTAINER_DOCUMENTS, filename)

            # Supprimer l'audio sur Azure si existe
            if audio_filename:
                delete_blob(CONTAINER_AUDIOS, audio_filename)

            # Supprimer l'entrée DB
            cursor.execute("DELETE FROM cours_documents WHERE id = ?", (document_id,))
            conn.commit()
            conn.close()

            return jsonify({"success": True}), 200
        except Exception as e:
            logger.error(f"❌ Erreur delete_cours_document: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-documents/<int:document_id>/download", methods=["GET"])
    def download_cours_document(document_id):
        """Télécharge le PDF depuis Azure"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT filename, original_name FROM cours_documents WHERE id = ?", (document_id,))
            row = cursor.fetchone()
            conn.close()

            if not row:
                return jsonify({"success": False, "error": "Document non trouvé"}), 404

            filename, original_name = row

            import io
            from flask import send_file
            pdf_bytes = download_blob(CONTAINER_DOCUMENTS, filename)
            return send_file(
                io.BytesIO(pdf_bytes),
                as_attachment=True,
                download_name=original_name,
                mimetype="application/pdf"
            )
        except Exception as e:
            logger.error(f"❌ Erreur download_cours_document: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-documents/<int:document_id>/audio", methods=["GET"])
    def download_cours_audio(document_id):
        """Télécharge l'audio depuis Azure"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT audio_filename, original_name FROM cours_documents WHERE id = ?", (document_id,))
            row = cursor.fetchone()
            conn.close()

            if not row:
                return jsonify({"success": False, "error": "Document non trouvé"}), 404

            audio_filename, original_name = row
            if not audio_filename:
                return jsonify({"success": False, "error": "Audio non généré"}), 404

            import io
            from flask import send_file
            audio_bytes = download_blob(CONTAINER_AUDIOS, audio_filename)
            audio_name = os.path.splitext(original_name)[0] + ".mp3"
            return send_file(
                io.BytesIO(audio_bytes),
                as_attachment=True,
                download_name=audio_name,
                mimetype="audio/mpeg"
            )
        except Exception as e:
            logger.error(f"❌ Erreur download_cours_audio: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── Routes Pipeline TTS ────────────────────────────────────────────────
    @hr_bp.route("/api/hr/cours-documents/<int:document_id>/generate-audio", methods=["POST"])
    def generate_document_audio(document_id):
        """Ancienne génération directe, remplacée par la file durable."""
        denied = _require_admin()
        if denied:
            return denied
        return _retired_local_generation_response()

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/generate-all-audio", methods=["POST"])
    def generate_folder_audio(folder_id):
        """Ancienne génération directe, remplacée par la file durable."""
        denied = _require_admin()
        if denied:
            return denied
        return _retired_local_generation_response()

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/tts-status", methods=["GET"])
    def get_folder_tts_status(folder_id):
        """Retourne le statut TTS d'un dossier"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT id, original_name, status
                FROM cours_documents
                WHERE folder_id = ?
                  AND (
                    NOT EXISTS (
                        SELECT 1
                        FROM cours_documents cd
                        WHERE cd.folder_id = cours_documents.folder_id
                          AND {_FINAL_SCRIPT_DOC_WHERE}
                    )
                    OR id = (
                        SELECT cd.id
                        FROM cours_documents cd
                        WHERE cd.folder_id = cours_documents.folder_id
                          AND {_FINAL_SCRIPT_DOC_WHERE}
                        ORDER BY cd.created_at DESC, cd.id DESC
                        LIMIT 1
                    )
                  )
                ORDER BY created_at DESC
            """, (folder_id,))
            docs = [{"id": row[0], "name": row[1], "status": row[2]} for row in cursor.fetchall()]
            conn.close()

            # Compter par statut
            status_counts = {}
            for doc in docs:
                status = doc["status"]
                status_counts[status] = status_counts.get(status, 0) + 1

            return jsonify({"success": True, "documents": docs, "counts": status_counts}), 200
        except Exception as e:
            logger.error(f"❌ Erreur get_folder_tts_status: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── Consultation et correction du contenu généré ───────────────────

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job", methods=["POST"])
    def create_content_job(folder_id):
        """Ancienne création manuelle, remplacée par la pipeline durable."""
        denied = _require_admin()
        if denied:
            return denied
        return _retired_local_generation_response()

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/start", methods=["POST"])
    def start_content_job(folder_id):
        """Ancien lancement manuel, remplacé par la pipeline durable."""
        denied = _require_admin()
        if denied:
            return denied
        return _retired_local_generation_response()

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job", methods=["GET"])
    def get_content_job(folder_id):
        """Retourne le statut du job de génération de contenu."""
        denied = _require_admin()
        if denied:
            return denied

        from services.content_generation_service import get_job_from_db, get_segments_status
        job = get_job_from_db(folder_id)
        if not job:
            return jsonify({"success": True, "job": None}), 200

        segments = get_segments_status(job["id"]) if job["id"] else []

        return jsonify({
            "success": True,
            "job": {
                "status": job["status"],
                "program_title": job["program_title"],
                "sub_parts": job["sub_parts"],
                "current_sub_part": job["current_sub_part"],
                "current_passe": job["current_passe"],
                "total_words": job["total_words"],
                "message": "",
                "error_message": job["error_message"],
                "segments": segments,
                "num_sub_parts": len(job["sub_parts"]),
            },
        }), 200

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/cancel", methods=["POST"])
    def cancel_content_job(folder_id):
        """Ancienne annulation locale, remplacée par la pipeline durable."""
        denied = _require_admin()
        if denied:
            return denied
        return _retired_local_generation_response()

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/preview", methods=["GET"])
    def preview_content_prompt(folder_id):
        """Retourne le prompt Passe 1 pré-rempli pour prévisualisation."""
        denied = _require_admin()
        if denied:
            return denied

        from services.content_generation_service import get_job_from_db, _get_passe_prompts, _EXTRACT_PROMPT
        job = get_job_from_db(folder_id)
        if not job:
            return jsonify({"success": False, "error": "Aucun job configuré"}), 404

        try:
            prompts = _get_passe_prompts()
            sub_parts = job["sub_parts"]
            first_sub = sub_parts[0] if sub_parts else "Sous-partie 1"
            preview = prompts[0]
            preview = preview.replace("{NOM_DU_TITRE_PROFESSIONNEL}", job["program_title"])
            preview = preview.replace("{NOM_DE_LA_SOUS_PARTIE}", first_sub)
            preview = preview.replace("{COLLER_LE_PROGRAMME_ICI}", job["program_text"][:3000] + "...")
            return jsonify({"success": True, "prompt_preview": preview, "sub_part": first_sub}), 200
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/dirty-blocs", methods=["GET"])
    def get_dirty_blocs(folder_id):
        """Retourne le nombre de blocs audio qui seraient régénérés (segments dirty)."""
        denied = _require_admin()
        if denied:
            return denied
        from services.content_generation_service import get_script_dirty_blocs
        result = get_script_dirty_blocs(folder_id)
        return jsonify({"success": True, **result}), 200

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/script", methods=["GET"])
    def get_content_script(folder_id):
        """Retourne le script TTS-direct généré (segments assemblés depuis la DB)."""
        denied = _require_admin()
        if denied:
            return denied

        from services.content_generation_service import (
            get_course_script_plan_for_ui,
            get_job_from_db,
        )
        from repositories.pipeline_repository import list_completed_content_segment_rows
        job = get_job_from_db(folder_id)
        if not job:
            return jsonify({"success": False, "error": "Aucun job pour ce dossier"}), 404

        rows = list_completed_content_segment_rows(job["id"])

        if not rows:
            return jsonify({"success": False, "error": "Aucun segment généré"}), 404

        # Grouper par sous-partie
        sub_parts_data = {}
        for row in rows:
            sub_idx = row["sub_part_index"]
            sub_name = row["sub_part_name"]
            passe = row["passe"]
            text = row["text_content"]
            word_count = row["word_count"] or 0
            if sub_idx not in sub_parts_data:
                sub_parts_data[sub_idx] = {"name": sub_name, "passes": {}, "total_words": 0}
            sub_parts_data[sub_idx]["passes"][passe] = {"text": text, "word_count": word_count}
            sub_parts_data[sub_idx]["total_words"] += word_count

        sub_parts_list = [
            {
                "index": idx,
                "name": data["name"],
                "total_words": data["total_words"],
                "passes": [
                    {"passe": p, "word_count": data["passes"][p]["word_count"], "text": data["passes"][p]["text"]}
                    for p in sorted(data["passes"].keys())
                ]
            }
            for idx, data in sorted(sub_parts_data.items())
        ]

        course_plan = get_course_script_plan_for_ui(folder_id, job=job)
        from services.script_annotation_service import list_script_annotations
        annotations_data = list_script_annotations(folder_id)

        return jsonify({
            "success": True,
            "program_title": job["program_title"],
            "total_words": job["total_words"],
            "sub_parts": sub_parts_list,
            "annotations": annotations_data["annotations"],
            "annotations_count": len(annotations_data["annotations"]),
            "annotations_markdown_path": annotations_data["markdown_path"],
            **course_plan,
        }), 200

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/annotations", methods=["GET"])
    def list_content_script_annotations(folder_id):
        """Retourne les annotations humaines du script TTS."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            from services.script_annotation_service import list_script_annotations
            data = list_script_annotations(folder_id)
            if not data["context"]:
                return jsonify({"success": False, "error": "Aucun job pour ce dossier"}), 404
            return jsonify({
                "success": True,
                "annotations": data["annotations"],
                "annotations_count": len(data["annotations"]),
                "markdown_path": data["markdown_path"],
            }), 200
        except Exception as e:
            logger.error(f"❌ Erreur list annotations script: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/annotations", methods=["POST"])
    def create_content_script_annotation(folder_id):
        """Cree une annotation sur une selection du script TTS et regenere le markdown."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            from services.script_annotation_service import create_script_annotation
            result = create_script_annotation(folder_id, request.get_json() or {})
            return jsonify({
                "success": True,
                "annotation": result["annotation"],
                "annotations": result["annotations"],
                "annotations_count": len(result["annotations"]),
                "markdown_path": result["markdown_path"],
            }), 201
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"❌ Erreur create annotation script: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/annotations/<int:annotation_id>", methods=["DELETE"])
    def delete_content_script_annotation(folder_id, annotation_id):
        """Supprime logiquement une annotation et regenere le markdown."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            from services.script_annotation_service import delete_script_annotation
            result = delete_script_annotation(folder_id, annotation_id)
            return jsonify({
                "success": True,
                "annotations": result["annotations"],
                "annotations_count": len(result["annotations"]),
                "markdown_path": result["markdown_path"],
            }), 200
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except Exception as e:
            logger.error(f"❌ Erreur delete annotation script: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/annotations/<int:annotation_id>/apply", methods=["POST"])
    def apply_content_script_annotation(folder_id, annotation_id):
        """Applique la correction proposée par DeepSeek (Phase A : patch texte segment)."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            from services.script_annotation_service import apply_script_annotation
            result = apply_script_annotation(folder_id, annotation_id)
            return jsonify({
                "success": True,
                "annotations": result["annotations"],
                "annotations_count": len(result["annotations"]),
                "markdown_path": result["markdown_path"],
            }), 200
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"❌ Erreur apply annotation script: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/annotations/<int:annotation_id>/reject", methods=["POST"])
    def reject_content_script_annotation(folder_id, annotation_id):
        """Rejette la correction proposée (l'annotation reste tracée pour le markdown)."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            from services.script_annotation_service import reject_script_annotation
            result = reject_script_annotation(folder_id, annotation_id)
            return jsonify({
                "success": True,
                "annotations": result["annotations"],
                "annotations_count": len(result["annotations"]),
                "markdown_path": result["markdown_path"],
            }), 200
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except Exception as e:
            logger.error(f"❌ Erreur reject annotation script: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/rules", methods=["GET"])
    def get_content_script_rules(folder_id):
        """Retourne le markdown des règles apprises depuis les annotations."""
        denied = _require_admin()
        if denied:
            return denied
        try:
            from services.script_rules_service import get_rules
            data = get_rules(folder_id)
            if not data["context"]:
                return jsonify({"success": False, "error": "Aucun job pour ce dossier"}), 404
            return jsonify({
                "success": True,
                "rules_markdown": data["rules_markdown"],
                "rules_count": data["rules_count"],
                "source_annotations_count": data["source_annotations_count"],
                "model": data["model"],
                "generated_at": data["generated_at"],
                "updated_at": data["updated_at"],
                "markdown_path": data["markdown_path"],
            }), 200
        except Exception as e:
            logger.error(f"❌ Erreur get rules: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/rules/extract", methods=["POST"])
    def extract_content_script_rules(folder_id):
        """Lance l'extraction DeepSeek des règles depuis les annotations appliquées."""
        denied = _require_admin()
        if denied:
            return denied
        try:
            from services.script_rules_service import extract_rules_from_annotations
            data = extract_rules_from_annotations(folder_id)
            return jsonify({
                "success": True,
                "rules_markdown": data["rules_markdown"],
                "rules_count": data["rules_count"],
                "source_annotations_count": data["source_annotations_count"],
                "model": data["model"],
                "generated_at": data["generated_at"],
                "updated_at": data["updated_at"],
                "markdown_path": data["markdown_path"],
            }), 200
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"❌ Erreur extract rules: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/rules", methods=["PUT"])
    def update_content_script_rules(folder_id):
        """Permet l'édition manuelle du markdown des règles par l'admin."""
        denied = _require_admin()
        if denied:
            return denied
        try:
            from services.script_rules_service import update_rules_markdown
            payload = request.get_json() or {}
            data = update_rules_markdown(folder_id, payload.get("rules_markdown") or "")
            return jsonify({
                "success": True,
                "rules_markdown": data["rules_markdown"],
                "rules_count": data["rules_count"],
                "updated_at": data["updated_at"],
            }), 200
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"❌ Erreur update rules: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/rules/review-text", methods=["POST"])
    def review_text_with_rules(folder_id):
        """Ancienne correction asynchrone locale, désormais retirée."""
        denied = _require_admin()
        if denied:
            return denied
        return _retired_local_generation_response()

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/rules/review-text/status/<task_id>", methods=["GET"])
    def review_text_status(folder_id, task_id):
        """Ancien suivi en mémoire, désormais retiré."""
        denied = _require_admin()
        if denied:
            return denied
        return _retired_local_generation_response()

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/rules/review-text/active", methods=["GET"])
    def review_text_active(folder_id):
        """Ancien suivi en mémoire, désormais retiré."""
        denied = _require_admin()
        if denied:
            return denied
        return _retired_local_generation_response()

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/rules/review-post-tts", methods=["POST"])
    def review_post_tts_with_rules(folder_id):
        """Phase 3b : parcourt les chunks audio, applique les règles, splice les MP3 non-conformes."""
        denied = _require_admin()
        if denied:
            return denied
        try:
            from services.script_rules_service import review_chunks_with_rules
            payload = request.get_json() or {}
            dry_run = bool(payload.get("dry_run") or False)
            bloc_numbers = payload.get("bloc_numbers")
            if bloc_numbers and not isinstance(bloc_numbers, list):
                bloc_numbers = None
            max_chunks = payload.get("max_chunks")
            if max_chunks is not None:
                try:
                    max_chunks = int(max_chunks)
                except (TypeError, ValueError):
                    max_chunks = None
            summary = review_chunks_with_rules(
                folder_id,
                dry_run=dry_run,
                bloc_numbers=bloc_numbers,
                max_chunks=max_chunks,
            )
            return jsonify({"success": True, **summary}), 200
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"❌ Erreur review post-tts: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/rules/markdown", methods=["GET"])
    def download_content_script_rules_markdown(folder_id):
        """Télécharge le markdown des règles."""
        denied = _require_admin()
        if denied:
            return denied
        try:
            from services.script_rules_service import get_rules
            data = get_rules(folder_id)
            if not data["context"]:
                return jsonify({"success": False, "error": "Aucun job pour ce dossier"}), 404
            markdown = data["rules_markdown"] or "_Aucune règle apprise pour ce dossier._\n"
            filename = os.path.basename(data["markdown_path"])
            return Response(
                markdown,
                mimetype="text/markdown; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except Exception as e:
            logger.error(f"❌ Erreur download rules markdown: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/annotations/markdown", methods=["GET"])
    def download_content_script_annotations_markdown(folder_id):
        """Retourne le markdown de revue du script TTS."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            from services.script_annotation_service import build_script_annotations_markdown, write_script_annotations_markdown
            markdown, path = build_script_annotations_markdown(folder_id)
            write_script_annotations_markdown(folder_id)
            filename = os.path.basename(path)
            return Response(
                markdown,
                mimetype="text/markdown; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except Exception as e:
            logger.error(f"❌ Erreur markdown annotations script: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/segment", methods=["PATCH"])
    def patch_content_segment(folder_id):
        """Modifie le texte d'un segment généré et recalcule le total_words du job."""
        denied = _require_admin()
        if denied:
            return denied

        data = request.get_json() or {}
        sub_part_index = data.get("sub_part_index")
        passe = data.get("passe")
        new_text = data.get("text", "")

        if sub_part_index is None or passe is None:
            return jsonify({"success": False, "error": "sub_part_index et passe sont requis"}), 400

        from services.content_generation_service import get_job_from_db
        job = get_job_from_db(folder_id)
        if not job:
            return jsonify({"success": False, "error": "Aucun job pour ce dossier"}), 404

        new_word_count = len(new_text.split())

        conn = get_db_connection()
        cursor = conn.cursor()

        # Mettre à jour le segment et le marquer comme modifié : dirty=1
        # (TTS doit ré-synthétiser), reviewed=0 (révision conformité doit
        # ré-auditer le texte modifié), review_error=NULL (toute ancienne
        # erreur reviewer devient obsolète sur un texte modifié).
        cursor.execute("""
            UPDATE content_generation_segments
            SET text_content = ?, word_count = ?, dirty = 1,
                reviewed = 0, review_error = NULL, review_signature = NULL
            WHERE job_id = ? AND sub_part_index = ? AND passe = ?
        """, (new_text, new_word_count, job["id"], sub_part_index, passe))

        # Recalculer total_words depuis tous les segments complétés
        cursor.execute("""
            SELECT COALESCE(SUM(word_count), 0)
            FROM content_generation_segments
            WHERE job_id = ? AND status = 'completed'
        """, (job["id"],))
        new_total = cursor.fetchone()[0]

        cursor.execute("""
            UPDATE content_generation_jobs SET total_words = ? WHERE id = ?
        """, (new_total, job["id"]))

        conn.commit()
        conn.close()

        return jsonify({"success": True, "new_word_count": new_word_count, "new_total_words": new_total}), 200

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/course-bloc", methods=["PATCH"])
    def patch_content_course_bloc(folder_id):
        """Modifie le texte d'un cours audio avant génération TTS."""
        denied = _require_admin()
        if denied:
            return denied

        data = request.get_json() or {}
        bloc_number = data.get("bloc_number")
        if bloc_number is None:
            return jsonify({"success": False, "error": "bloc_number est requis"}), 400

        try:
            from services.content_generation_service import update_course_script_bloc_text

            result = update_course_script_bloc_text(
                folder_id,
                int(bloc_number),
                data.get("text") or "",
            )
            return jsonify({"success": True, **result}), 200
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"❌ Erreur update course bloc script: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/break", methods=["PATCH"])
    def patch_content_break_text(folder_id):
        """Modifie le texte d'un Q&A ou d'une pause pour les prochaines générations."""
        denied = _require_admin()
        if denied:
            return denied

        data = request.get_json() or {}
        filename = data.get("filename")
        if not filename:
            return jsonify({"success": False, "error": "filename est requis"}), 400

        try:
            from services.content_generation_service import update_course_script_break_text

            result = update_course_script_break_text(
                folder_id,
                filename,
                data.get("intro") or "",
                data.get("outro") or "",
            )
            return jsonify({"success": True, **result}), 200
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"❌ Erreur update break script: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── Pipeline playlist complète (manifeste V1 ou V2) ──────────────────

    _HR_AUDIO_QUEUE_SCOPE_PREFIX = "hr_audio"

    def _hr_audio_queue_scope(folder_id):
        # Keep compatibility with the historical pipeline-job/scope index while
        # allowing different folders of the same formation to run in parallel.
        return f"{_HR_AUDIO_QUEUE_SCOPE_PREFIX}:{int(folder_id)}"

    def _enqueue_hr_audio_job(folder, task_type, payload):
        """Atomically enqueue one audio operation for a folder resource."""
        import uuid
        from services.pipeline_queue import enqueue_work_item

        folder_id = int(folder["id"])
        pipeline_job_id = folder.get("formation_job_id")
        run_id = uuid.uuid4().hex
        item = enqueue_work_item(
            pipeline_job_id=(int(pipeline_job_id) if pipeline_job_id is not None else None),
            folder_id=folder_id,
            resource_key=f"folder:{folder_id}",
            task_type=task_type,
            scope_key=_hr_audio_queue_scope(folder_id),
            run_id=run_id,
            dedupe_key=f"folder:{folder_id}:audio:{run_id}",
            payload={**payload, "folder_id": folder_id},
            max_attempts=5,
        )
        deduplicated = item.run_id != run_id
        if deduplicated:
            logger.warning(
                "HR_PLAYLIST_QUEUE_DUPLICATE folder_id=%s existing_work_item_id=%s "
                "existing_status=%s requested_task_type=%s",
                folder_id,
                item.id,
                item.status,
                task_type,
            )
        else:
            logger.info(
                "HR_PLAYLIST_QUEUE_ENQUEUED folder_id=%s pipeline_job_id=%s "
                "work_item_id=%s run_id=%s task_type=%s",
                folder_id,
                pipeline_job_id,
                item.id,
                item.run_id,
                task_type,
            )
        return item, deduplicated

    def _latest_hr_audio_job(folder_id):
        from services.pipeline_queue import get_latest_folder_work_item

        return get_latest_folder_work_item(
            folder_id,
            scope_key=_hr_audio_queue_scope(folder_id),
        )

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/generate-playlist", methods=["POST"])
    def generate_playlist(folder_id):
        """Lance la génération du manifeste MP3 exact d'un dossier."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            # Vérifier que le dossier existe et récupérer le platform_id
            folder = get_course_folder_identity(folder_id)
            if not folder:
                return jsonify({"success": False, "error": "Dossier introuvable"}), 404

            platform_id = int(folder["platform_id"])

            req_body = request.get_json(silent=True) or {}
            playlist_mock = req_body.get("mock", False)   # mock mode classique (sans script)
            script_mock = req_body.get("script_mock", False)  # mock mode script (silence au lieu TTS)
            force_all = req_body.get("force_all", False)
            preserve_existing = bool(req_body.get("preserve_existing", False))
            include_breaks = bool(req_body.get("include_breaks", True))
            parallel_breaks = bool(req_body.get("parallel_breaks", False))
            slide_max_slides = int(req_body.get("max_slides") or req_body.get("slide_max_slides") or 60)
            slide_pace = str(req_body.get("pace") or req_body.get("slide_pace") or "normal")
            requested_voice_type_raw = str(req_body.get("voice_type") or req_body.get("tts_mode") or "").strip().lower()
            voice_aliases = {
                "gtts": "gtts",
                "edge": "gtts",
                "edge_tts": "gtts",
                "basic": "gtts",
                "basic_tts": "gtts",
                "fish": "fish_audio",
                "fish_audio": "fish_audio",
                "fishaudio": "fish_audio",
                "mock": "mock",
            }
            requested_voice_type = voice_aliases.get(requested_voice_type_raw) if requested_voice_type_raw else None

            if requested_voice_type_raw and not requested_voice_type:
                return jsonify({
                    "success": False,
                    "error": "Moteur audio inconnu. Utilise 'gtts' ou 'fish_audio'."
                }), 400

            # Vérifier si un script TTS existe pour ce dossier
            from services.content_generation_service import get_job_from_db as _get_cjob
            content_job = _get_cjob(folder_id)
            has_script = bool(content_job and content_job.get("status") == "completed")

            if requested_voice_type == "mock" and not script_mock and not playlist_mock:
                script_mock = has_script
                playlist_mock = not has_script

            if script_mock and not has_script:
                return jsonify({
                    "success": False,
                    "error": "Le mock script nécessite un script texte déjà généré pour ce dossier."
                }), 400

            if requested_voice_type and requested_voice_type != "mock" and not playlist_mock and not has_script:
                return jsonify({
                    "success": False,
                    "error": "Génère d'abord le script texte du dossier avant de lancer l'audio gTTS ou Fish Audio."
                }), 400

            if script_mock or playlist_mock:
                voice_type = "mock"
            elif requested_voice_type:
                voice_type = requested_voice_type
            else:
                # Compatibilité ancienne UI/API : sans choix explicite, l'ancien comportement reste Fish Audio.
                voice_type = "fish_audio"

            voice_label = "gTTS" if voice_type == "gtts" else "Fish Audio" if voice_type == "fish_audio" else "Mock"
            if voice_type == "fish_audio":
                parallel_breaks = False
            production_audio = bool(
                has_script
                and not playlist_mock
                and voice_type in {"gtts", "fish_audio"}
            )
            if production_audio:
                # A real course MP3 without slide timings is an invalid asset.
                # Do not let legacy clients opt out of the synchronization
                # contract by sending sync_slides=false.
                sync_slides = True
                auto_generate_slides = True
            else:
                sync_slides = False
                auto_generate_slides = False

            item, deduplicated = _enqueue_hr_audio_job(
                folder,
                "hr_playlist_generate",
                {
                    "platform_id": platform_id,
                    "has_script": has_script,
                    "playlist_mock": bool(playlist_mock),
                    "script_mock": bool(script_mock),
                    "force_all": bool(force_all),
                    "preserve_existing": preserve_existing,
                    "include_breaks": include_breaks,
                    "parallel_breaks": parallel_breaks,
                    "sync_slides": sync_slides,
                    "auto_generate_slides": auto_generate_slides,
                    "slide_max_slides": slide_max_slides,
                    "slide_pace": slide_pace,
                    "voice_type": voice_type,
                    "voice_label": voice_label,
                    "total_steps": 24,
                    "initial_message": f"Démarrage audio {voice_label}...",
                },
            )
            if deduplicated:
                return jsonify({
                    "success": False,
                    "error": "Une génération est déjà en cours pour ce dossier",
                    "work_item_id": item.id,
                    "queue_status": item.status,
                }), 409
            return jsonify({
                "success": True,
                "message": "Pipeline mise en file durable",
                "work_item_id": item.id,
                "run_id": item.run_id,
                "queue_status": item.status,
            }), 202

        except Exception as e:
            logger.exception(
                "HR_PLAYLIST_QUEUE_ENQUEUE_FAILED folder_id=%s error=%s",
                folder_id,
                str(e),
            )
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/generate-playlist-item", methods=["POST"])
    def generate_playlist_item(folder_id):
        """Lance la génération d'un seul fichier MP3 de la playlist."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            folder = get_course_folder_identity(folder_id)
            if not folder:
                return jsonify({"success": False, "error": "Dossier introuvable"}), 404
            platform_id = int(folder["platform_id"])

            req_body = request.get_json(silent=True) or {}
            filename = os.path.basename(str(req_body.get("filename") or "").split("?", 1)[0])
            if not filename:
                return jsonify({"success": False, "error": "filename est requis"}), 400

            requested_voice_type_raw = str(req_body.get("voice_type") or "").strip().lower()
            voice_aliases = {
                "gtts": "gtts",
                "edge": "gtts",
                "edge_tts": "gtts",
                "basic": "gtts",
                "basic_tts": "gtts",
                "fish": "fish_audio",
                "fish_audio": "fish_audio",
                "fishaudio": "fish_audio",
            }
            voice_type = voice_aliases.get(requested_voice_type_raw)
            if not voice_type:
                return jsonify({
                    "success": False,
                    "error": "Moteur audio inconnu. Utilise 'gtts' ou 'fish_audio'."
                }), 400

            from services.content_generation_service import get_job_from_db as _get_cjob
            content_job = _get_cjob(folder_id)
            has_script = bool(content_job and content_job.get("status") == "completed")
            if not has_script:
                return jsonify({
                    "success": False,
                    "error": "Génère d'abord le script texte du dossier avant de lancer l'audio."
                }), 400

            voice_label = "gTTS" if voice_type == "gtts" else "Fish Audio"
            from services.day_playlist_service import is_course_audio_filename

            is_course_audio = is_course_audio_filename(filename)
            # Course audio is always generated with a usable slide contract;
            # the request body can no longer disable it.
            sync_slides = bool(is_course_audio)
            auto_generate_slides = bool(is_course_audio)
            slide_max_slides = int(req_body.get("max_slides") or req_body.get("slide_max_slides") or 60)
            slide_pace = str(req_body.get("pace") or req_body.get("slide_pace") or "normal")
            item, deduplicated = _enqueue_hr_audio_job(
                folder,
                "hr_playlist_item",
                {
                    "platform_id": platform_id,
                    "filename": filename,
                    "voice_type": voice_type,
                    "voice_label": voice_label,
                    "sync_slides": sync_slides,
                    "auto_generate_slides": auto_generate_slides,
                    "slide_max_slides": slide_max_slides,
                    "slide_pace": slide_pace,
                    "total_steps": 1,
                    "initial_message": f"Démarrage {filename} en {voice_label}...",
                },
            )
            if deduplicated:
                return jsonify({
                    "success": False,
                    "error": "Une génération est déjà en cours pour ce dossier",
                    "work_item_id": item.id,
                    "queue_status": item.status,
                }), 409
            return jsonify({
                "success": True,
                "message": "Génération fichier mise en file durable",
                "work_item_id": item.id,
                "run_id": item.run_id,
                "queue_status": item.status,
            }), 202

        except Exception as e:
            logger.exception(
                "HR_PLAYLIST_ITEM_QUEUE_ENQUEUE_FAILED folder_id=%s error=%s",
                folder_id,
                str(e),
            )
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/repair-audio-sync", methods=["POST"])
    def repair_audio_sync(folder_id):
        """Répare la synchro slides/audio depuis les timelines Fish déjà générées."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            if not get_course_folder_identity(folder_id):
                return jsonify({"success": False, "error": "Dossier introuvable"}), 404

            active_audio_job = _latest_hr_audio_job(folder_id)
            if active_audio_job and not active_audio_job.terminal:
                return jsonify({
                    "success": False,
                    "error": "Une génération est déjà en cours pour ce dossier",
                    "work_item_id": active_audio_job.id,
                    "queue_status": active_audio_job.status,
                }), 409

            req_body = request.get_json(silent=True) or {}
            dry_run = bool(req_body.get("dry_run", False))

            from services.content_generation_service import repair_audio_sync_from_existing_timelines
            result = repair_audio_sync_from_existing_timelines(folder_id, dry_run=dry_run)
            return jsonify(result), 200

        except Exception as e:
            logger.error(f"❌ Erreur repair_audio_sync: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/playlist-script", methods=["GET"])
    def get_playlist_script(folder_id):
        """Retourne le script reformulé par DeepSeek pour un dossier."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            folder = get_course_folder_identity(folder_id)
            if not folder:
                return jsonify({"success": False, "error": "Dossier introuvable"}), 404

            platform_id = int(folder["platform_id"])

            from services.azure_blob_service import download_blob, CONTAINER_AUDIOS
            import json as _json

            blob_path = resolve_folder_blob_path(
                folder_id,
                CONTAINER_AUDIOS,
                "playlist/script.json",
                fallback_platform_id=platform_id,
            )
            script_bytes = download_blob(CONTAINER_AUDIOS, blob_path)
            script_data = _json.loads(script_bytes.decode("utf-8"))

            return jsonify({"success": True, **script_data}), 200

        except Exception as e:
            if "BlobNotFound" in str(e) or "The specified blob does not exist" in str(e):
                return jsonify({"success": False, "error": "Aucun script généré pour ce dossier"}), 404
            logger.error(f"❌ Erreur get_playlist_script: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/playlist-status", methods=["GET"])
    def get_playlist_status(folder_id):
        """Retourne l'état de la pipeline playlist pour un dossier."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            job = _latest_hr_audio_job(folder_id)
            if not job:
                return jsonify({"success": True, "status": "idle"}), 200

            persisted = dict(job.result or {})
            status_map = {
                "queued": "running",
                "retry_scheduled": "running",
                "running": "running",
                "completed": "completed",
                "dead_lettered": "error",
                "cancelled": "error",
            }
            api_status = status_map.get(job.status, job.status)
            message = persisted.get("message")
            if job.status == "queued":
                message = message or "En attente du worker audio..."
            elif job.status == "retry_scheduled":
                message = job.last_error or message or "Nouvelle tentative planifiée..."
            elif job.status in {"dead_lettered", "cancelled"}:
                message = job.last_error or message or "Pipeline audio interrompue"
            return jsonify({
                "success": True,
                **persisted,
                "status": api_status,
                "queue_status": job.status,
                "work_item_id": job.id,
                "run_id": job.run_id,
                "attempt": job.attempt_count,
                "max_attempts": job.max_attempts,
                "message": message,
                "last_error": job.last_error,
            }), 200
        except Exception as e:
            logger.exception("HR_PLAYLIST_QUEUE_STATUS_FAILED folder_id=%s", folder_id)
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/generated-audios", methods=["GET"])
    def get_generated_audios(folder_id):
        """Liste le manifeste attendu et les MP3 déjà générés d'un dossier."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            folder = get_course_folder_identity(folder_id)
            if not folder:
                return jsonify({"success": False, "error": "Dossier introuvable"}), 404

            platform_id = int(folder["platform_id"])
            from services.day_playlist_service import resolve_folder_playlist

            playlist_contract = resolve_folder_playlist(folder_id)
            inspection = _inspect_generated_audio_assets(
                folder_id,
                folder,
                playlist_contract,
            )
            inspection.pop("_storage", None)

            return jsonify({
                "success": True,
                "schedule_schema_version": int(
                    playlist_contract.get("schema_version") or 1
                ),
                **inspection,
            }), 200

        except Exception as e:
            logger.error(f"❌ Erreur get_generated_audios: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route(
        "/api/hr/cours-folders/<int:folder_id>/cleanup-invalid-audios",
        methods=["POST"],
    )
    def cleanup_invalid_audios(folder_id):
        """Quarantine corrupt or stale MP3s; sync-only failures remain repairable."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            folder = get_course_folder_identity(folder_id)
            if not folder:
                return jsonify({"success": False, "error": "Dossier introuvable"}), 404
            from services.day_playlist_service import resolve_folder_playlist

            inspection = _inspect_generated_audio_assets(
                folder_id,
                folder,
                resolve_folder_playlist(folder_id),
            )
            storage = inspection.get("_storage")
            if not storage:
                return jsonify({"success": False, "error": "Stockage audio indisponible"}), 503
            if (
                int(storage["source_folder_id"]) != int(folder_id)
                or int(storage["source_platform_id"]) != int(folder["platform_id"])
            ):
                return jsonify({
                    "success": False,
                    "error": (
                        "Les audios invalides appartiennent à un professeur partagé. "
                        "Créez une personnalisation avant nettoyage."
                    ),
                    "code": "shared_asset_immutable",
                }), 409

            candidates = [
                item for item in inspection.get("invalid_audios") or []
                if not item.get("physical_ready") or item.get("reason") == "unexpected_audio"
            ]
            sync_only = [
                item["filename"] for item in inspection.get("invalid_audios") or []
                if item.get("physical_ready") and item.get("reason") == "missing_audio_sync"
            ]
            quarantine_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            cc = storage["container_client"]
            quarantined = []
            failures = []
            for item in candidates:
                source_path = item.get("blob_path")
                if not source_path:
                    continue
                filename = os.path.basename(source_path)
                target_path = (
                    f"platform-{int(folder['platform_id'])}/folder-{int(folder_id)}/"
                    f"quarantine/{quarantine_stamp}/playlist/{filename}"
                )
                try:
                    source_client = cc.get_blob_client(source_path)
                    props = source_client.get_blob_properties()
                    audio_bytes = source_client.download_blob().readall()
                    cc.get_blob_client(target_path).upload_blob(
                        audio_bytes,
                        overwrite=False,
                        content_settings=props.content_settings,
                        metadata={
                            "quarantine_reason": str(item.get("reason") or "invalid")[:120],
                            "original_filename": filename,
                        },
                    )
                    source_client.delete_blob()
                    quarantined.append({
                        "filename": filename,
                        "reason": item.get("reason"),
                        "quarantine_path": target_path,
                        "recoverable": True,
                    })
                except Exception as exc:
                    failures.append({"filename": filename, "error": str(exc)[:240]})

            return jsonify({
                "success": not failures,
                "quarantined": quarantined,
                "sync_only_not_deleted": sync_only,
                "failures": failures,
            }), 200 if not failures else 500
        except Exception as exc:
            logger.exception("cleanup_invalid_audios folder_id=%s", folder_id)
            return jsonify({"success": False, "error": str(exc)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/audio/<path:filename>", methods=["DELETE"])
    def delete_generated_audio(folder_id, filename):
        """Supprime un MP3 généré du dossier et sa copie publiée sur la plateforme."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            platform_id = _get_platform_id_for_folder(folder_id)
            safe_filename = os.path.basename(str(filename or "").split("?", 1)[0])
            if not safe_filename or not safe_filename.lower().endswith(".mp3"):
                return jsonify({"success": False, "error": "Nom de fichier audio invalide"}), 400

            tts_conn = os.environ.get("AZURE_TTS_STORAGE_CONNECTION_STRING")
            audio_conn = os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING") or os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
            if not tts_conn:
                return jsonify({"success": False, "error": "AZURE_TTS_STORAGE_CONNECTION_STRING manquant"}), 500

            deleted = []
            errors = []
            blob_path = _get_audio_blob_path(platform_id, folder_id, safe_filename, for_write=True)
            resolved_read_path = _get_audio_blob_path(platform_id, folder_id, safe_filename)
            if resolved_read_path != blob_path:
                return jsonify({
                    "success": False,
                    "error": (
                        "Cet audio appartient à la version partagée du professeur IA. "
                        "Créez une personnalisation pour cette promotion avant de le supprimer."
                    ),
                    "code": "shared_asset_immutable",
                }), 409

            try:
                tts_bsc = BlobServiceClient.from_connection_string(tts_conn)
                tts_bsc.get_blob_client(container="audiostts", blob=blob_path).delete_blob()
                deleted.append(f"audiostts/{blob_path}")
                logger.info(f"🗑️ Audio généré supprimé: audiostts/{blob_path}")
            except Exception as e:
                if "BlobNotFound" in str(e) or "The specified blob does not exist" in str(e):
                    logger.info(f"ℹ️ Audio généré déjà absent: audiostts/{blob_path}")
                else:
                    errors.append({"target": f"audiostts/{blob_path}", "error": str(e)})

            if audio_conn:
                try:
                    pinfo = _get_platform_info(int(platform_id))
                    public_container = pinfo["audio_container"]
                    audio_bsc = BlobServiceClient.from_connection_string(audio_conn)
                    audio_bsc.get_blob_client(container=public_container, blob=safe_filename).delete_blob()
                    deleted.append(f"{public_container}/{safe_filename}")
                    logger.info(f"🗑️ Audio publié supprimé: {public_container}/{safe_filename}")
                except Exception as e:
                    if "BlobNotFound" in str(e) or "The specified blob does not exist" in str(e):
                        logger.info(f"ℹ️ Audio publié déjà absent: {safe_filename}")
                    else:
                        errors.append({"target": safe_filename, "error": str(e)})

            if errors:
                return jsonify({
                    "success": False,
                    "error": "Suppression partielle ou échouée",
                    "deleted": deleted,
                    "errors": errors,
                    "filename": safe_filename,
                }), 500

            return jsonify({
                "success": True,
                "filename": safe_filename,
                "deleted": deleted,
            }), 200

        except Exception as e:
            logger.error(f"❌ delete_generated_audio: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── Éditeur audio ───────────────────────────────────────────────────────

    _audio_previews = {}  # {preview_id: bytes} — stockage temporaire des TTS preview

    def _get_audio_blob_path(platform_id, folder_id, filename, *, for_write=False):
        relative_path = f"playlist/{os.path.basename(str(filename).split('?', 1)[0])}"
        if for_write:
            return f"platform-{platform_id}/folder-{folder_id}/{relative_path}"
        return resolve_folder_blob_path(
            folder_id,
            CONTAINER_AUDIOS,
            relative_path,
            fallback_platform_id=platform_id,
        )

    def _get_platform_id_for_folder(folder_id):
        folder = get_course_folder_identity(folder_id)
        if not folder:
            raise ValueError(f"Dossier {folder_id} introuvable")
        return int(folder["platform_id"])

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/audio-url/<path:filename>", methods=["GET"])
    def get_audio_sas_url(folder_id, filename):
        """Génère une SAS URL temporaire (1h) pour streamer l'audio directement depuis Azure."""
        denied = _require_admin()
        if denied:
            return denied
        try:
            folder = get_course_folder_identity(folder_id)
            if not folder:
                return jsonify({"success": False, "error": "Dossier introuvable"}), 404
            platform_id = int(folder["platform_id"])
            from services.day_playlist_service import resolve_folder_playlist

            inspection = _inspect_generated_audio_assets(
                folder_id,
                folder,
                resolve_folder_playlist(folder_id),
            )
            ready_by_name = {
                item["filename"]: item for item in inspection.get("audios") or []
            }
            if filename not in ready_by_name:
                invalid = next(
                    (
                        item for item in inspection.get("invalid_audios") or []
                        if item.get("filename") == filename
                    ),
                    None,
                )
                return jsonify({
                    "success": False,
                    "error": (
                        "Audio non prêt: le MP3 doit être lisible et sa "
                        "synchronisation slides complète."
                    ),
                    "code": (invalid or {}).get("reason") or "audio_not_ready",
                    "audio": invalid,
                    "audio_sync_status": inspection.get("audio_sync_status") or {},
                }), 422
            blob_path = _get_audio_blob_path(platform_id, folder_id, filename)
            cs = os.environ.get("AZURE_TTS_STORAGE_CONNECTION_STRING")
            if not cs:
                return jsonify({"success": False, "error": "AZURE_TTS_STORAGE_CONNECTION_STRING manquant"}), 500
            blob_service_client = BlobServiceClient.from_connection_string(cs)
            blob_client = blob_service_client.get_blob_client(container="audiostts", blob=blob_path)
            try:
                props = blob_client.get_blob_properties()
            except Exception as prop_error:
                if "BlobNotFound" in str(prop_error) or "The specified blob does not exist" in str(prop_error):
                    return jsonify({
                        "success": False,
                        "error": f"Fichier audio introuvable: {filename}",
                        "blob_path": blob_path,
                    }), 404
                raise

            blob_size = int(props.size or 0)
            from services.day_playlist_service import is_course_audio_filename

            if is_course_audio_filename(filename) and blob_size < 100_000:
                return jsonify({
                    "success": False,
                    "error": (
                        f"Fichier audio trop court ou silencieux: {filename} "
                        f"({blob_size} octets). Relance la génération audio du cours."
                    ),
                    "blob_path": blob_path,
                    "size": blob_size,
                }), 422

            account_name = blob_service_client.account_name
            account_key = blob_service_client.credential.account_key
            expiry = datetime.now(timezone.utc) + timedelta(hours=1)
            sas_token = generate_blob_sas(
                account_name=account_name,
                container_name="audiostts",
                blob_name=blob_path,
                account_key=account_key,
                permission=BlobSasPermissions(read=True),
                expiry=expiry,
                content_type="audio/mpeg",
                content_disposition=f'inline; filename="{os.path.basename(filename)}"',
            )
            url = f"https://{account_name}.blob.core.windows.net/audiostts/{blob_path}?{sas_token}"
            return jsonify({
                "success": True,
                "url": url,
                "size": blob_size,
                "content_type": props.content_settings.content_type,
                "content_disposition": props.content_settings.content_disposition,
            })
        except Exception as e:
            logger.error(f"❌ get_audio_sas_url: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/audio-stream/<path:filename>", methods=["GET"])
    def stream_audio_file(folder_id, filename):
        """Proxy l'audio depuis Azure audiostts vers le frontend.

        Supporte les Range requests (206 Partial Content) pour permettre au
        navigateur de seek dans la piste audio — sans ça, cliquer vers la fin
        de la waveform échoue silencieusement.
        """
        denied = _require_admin()
        if denied:
            return denied
        try:
            folder = get_course_folder_identity(folder_id)
            if not folder:
                return jsonify({"success": False, "error": "Dossier introuvable"}), 404
            platform_id = int(folder["platform_id"])
            from services.day_playlist_service import resolve_folder_playlist

            inspection = _inspect_generated_audio_assets(
                folder_id,
                folder,
                resolve_folder_playlist(folder_id),
            )
            ready_names = {
                item["filename"] for item in inspection.get("audios") or []
            }
            if filename not in ready_names:
                invalid = next(
                    (
                        item for item in inspection.get("invalid_audios") or []
                        if item.get("filename") == filename
                    ),
                    None,
                )
                return jsonify({
                    "success": False,
                    "error": "Audio non prêt ou synchronisation slides incomplète.",
                    "code": (invalid or {}).get("reason") or "audio_not_ready",
                }), 422
            blob_path = _get_audio_blob_path(platform_id, folder_id, filename)
            from services.azure_blob_service import CONTAINER_AUDIOS

            cs = os.environ.get("AZURE_TTS_STORAGE_CONNECTION_STRING")
            if not cs:
                return jsonify({"success": False, "error": "AZURE_TTS_STORAGE_CONNECTION_STRING manquant"}), 500

            blob_service_client = BlobServiceClient.from_connection_string(cs)
            blob_client = blob_service_client.get_blob_client(container=CONTAINER_AUDIOS, blob=blob_path)
            total_size = blob_client.get_blob_properties().size
            content_disposition = f'inline; filename="{os.path.basename(filename)}"'

            def _stream_blob(offset=None, length=None):
                downloader = blob_client.download_blob(offset=offset, length=length)
                for chunk in downloader.chunks():
                    yield chunk

            range_header = request.headers.get("Range")
            if not range_header:
                return Response(
                    stream_with_context(_stream_blob()),
                    mimetype="audio/mpeg",
                    headers={
                        "Content-Disposition": content_disposition,
                        "Accept-Ranges": "bytes",
                        "Content-Length": str(total_size),
                        "Cache-Control": "no-store",
                    },
                )

            # Format attendu : "bytes=START-END" (END optionnel) ou "bytes=-SUFFIX"
            try:
                units, _, rng = range_header.partition("=")
                if units.strip().lower() != "bytes":
                    raise ValueError("unit non supportée")
                start_s, _, end_s = rng.partition("-")
                start_s, end_s = start_s.strip(), end_s.strip()
                if start_s == "":
                    suffix = int(end_s)
                    start = max(0, total_size - suffix)
                    end = total_size - 1
                else:
                    start = int(start_s)
                    end = int(end_s) if end_s else total_size - 1
            except (ValueError, TypeError):
                return Response(
                    status=416,
                    headers={"Content-Range": f"bytes */{total_size}"},
                )

            end = min(end, total_size - 1)
            if start < 0 or start > end or start >= total_size:
                return Response(
                    status=416,
                    headers={"Content-Range": f"bytes */{total_size}"},
                )

            return Response(
                stream_with_context(_stream_blob(offset=start, length=end - start + 1)),
                status=206,
                mimetype="audio/mpeg",
                headers={
                    "Content-Disposition": content_disposition,
                    "Accept-Ranges": "bytes",
                    "Content-Range": f"bytes {start}-{end}/{total_size}",
                    "Content-Length": str(end - start + 1),
                    "Cache-Control": "no-store",
                },
            )
        except Exception as e:
            logger.error(f"❌ stream_audio_file: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/mock-upload-local", methods=["POST"])
    def mock_upload_local(folder_id):
        """
        [DEV ONLY] Upload automatique de tous les cours_*.mp3 depuis un dossier
        local du projet (ex: output_jour1) vers audiostts.
        Les fichiers locaux ne sont pas modifiés — seuls les octets sont copiés.
        """
        denied = _require_admin()
        if denied:
            return denied
        try:
            data = request.get_json() or {}
            source_dir = data.get("source_dir", "output_jour1")

            # Sécurité : empêcher toute traversée de chemin
            if "/" in source_dir or "\\" in source_dir or ".." in source_dir:
                return jsonify({"success": False, "error": "source_dir invalide"}), 400

            project_root = os.path.join(os.path.dirname(__file__), "..", "..")
            local_folder = os.path.abspath(os.path.join(project_root, source_dir))

            if not os.path.isdir(local_folder):
                return jsonify({"success": False, "error": f"Dossier introuvable: {source_dir}"}), 404

            platform_id = _get_platform_id_for_folder(folder_id)

            from services.azure_blob_service import upload_blob, CONTAINER_AUDIOS
            from services.day_playlist_service import is_course_audio_filename

            uploaded = []
            failed = []
            for name in sorted(os.listdir(local_folder)):
                if not is_course_audio_filename(name):
                    continue
                full_path = os.path.join(local_folder, name)
                try:
                    with open(full_path, "rb") as f:
                        audio_bytes = f.read()
                    blob_path = _get_audio_blob_path(platform_id, folder_id, name, for_write=True)
                    upload_blob(CONTAINER_AUDIOS, blob_path, audio_bytes)
                    set_platform_asset_binding_mode(platform_id, "copy_on_write")
                    size_mb = round(len(audio_bytes) / (1024 * 1024), 2)
                    uploaded.append({"filename": name, "size_mb": size_mb})
                    logger.info(f"🧪 Mock local upload: {name} ({size_mb} Mo) → {blob_path}")
                except Exception as fe:
                    logger.error(f"❌ Mock local upload {name}: {fe}")
                    failed.append({"filename": name, "error": str(fe)})

            return jsonify({
                "success": True,
                "source_dir": source_dir,
                "uploaded": uploaded,
                "failed": failed,
                "count": len(uploaded),
            }), 200

        except Exception as e:
            logger.error(f"❌ mock_upload_local: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/mock-upload-audio", methods=["POST"])
    def mock_upload_audio(folder_id):
        """
        [DEV ONLY] Upload direct d'un fichier audio local dans audiostts,
        au chemin attendu par la playlist (platform-X/folder-Y/playlist/<filename>).
        Sert à tester le découpage/remplacement sans avoir à générer le TTS.
        """
        denied = _require_admin()
        if denied:
            return denied
        try:
            if "file" not in request.files:
                return jsonify({"success": False, "error": "Aucun fichier envoyé"}), 400

            file = request.files["file"]
            if not file or not file.filename:
                return jsonify({"success": False, "error": "Fichier vide"}), 400

            # Optionnellement accepter un nom cible distinct (target_filename)
            target_filename = request.form.get("target_filename") or file.filename
            if not target_filename.lower().endswith(".mp3"):
                return jsonify({"success": False, "error": "Seuls les .mp3 sont acceptés"}), 400

            platform_id = _get_platform_id_for_folder(folder_id)
            blob_path = _get_audio_blob_path(platform_id, folder_id, target_filename, for_write=True)

            from services.azure_blob_service import upload_blob, CONTAINER_AUDIOS
            audio_bytes = file.read()
            upload_blob(CONTAINER_AUDIOS, blob_path, audio_bytes)
            set_platform_asset_binding_mode(platform_id, "copy_on_write")

            size_mb = round(len(audio_bytes) / (1024 * 1024), 2)
            logger.info(f"🧪 Mock upload: {target_filename} ({size_mb} Mo) → {blob_path}")

            return jsonify({
                "success": True,
                "filename": target_filename,
                "size_mb": size_mb,
                "blob_path": blob_path,
            }), 200

        except Exception as e:
            logger.error(f"❌ mock_upload_audio: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/audio/<path:filename>/cut", methods=["POST"])
    def cut_audio_region(folder_id, filename):
        """Coupe une région [start_ms, end_ms] de l'audio et upload le résultat."""
        denied = _require_admin()
        if denied:
            return denied
        try:
            data = request.get_json() or {}
            start_ms = int(data.get("start_ms", 0))
            end_ms = int(data.get("end_ms", 0))
            if end_ms <= start_ms:
                return jsonify({"success": False, "error": "end_ms doit être > start_ms"}), 400

            platform_id = _get_platform_id_for_folder(folder_id)
            source_blob_path = _get_audio_blob_path(platform_id, folder_id, filename)
            target_blob_path = _get_audio_blob_path(platform_id, folder_id, filename, for_write=True)

            from services.azure_blob_service import download_blob, upload_blob, CONTAINER_AUDIOS
            from pydub import AudioSegment
            import io

            audio_bytes = download_blob(CONTAINER_AUDIOS, source_blob_path)
            audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")

            result = audio[:start_ms] + audio[end_ms:]

            buf = io.BytesIO()
            result.export(buf, format="mp3", bitrate="128k")
            result_bytes = buf.getvalue()

            upload_blob(CONTAINER_AUDIOS, target_blob_path, result_bytes)
            set_platform_asset_binding_mode(platform_id, "copy_on_write")
            logger.info(
                "✂️ Cut %s: [%sms-%sms] supprimé → %s bytes uploadé en surcharge %s",
                filename,
                start_ms,
                end_ms,
                len(result_bytes),
                target_blob_path,
            )

            return jsonify({
                "success": True,
                "original_duration_ms": len(audio),
                "new_duration_ms": len(result),
                "cut_ms": end_ms - start_ms,
            }), 200

        except Exception as e:
            logger.error(f"❌ cut_audio_region: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/audio/<path:filename>/replace-preview", methods=["POST"])
    def replace_audio_preview(folder_id, filename):
        """Génère un aperçu TTS du nouveau texte. Retourne preview_id + audio base64."""
        denied = _require_admin()
        if denied:
            return denied
        try:
            data = request.get_json() or {}
            text = data.get("text", "").strip()
            if not text:
                return jsonify({"success": False, "error": "Texte requis"}), 400

            from services.tts_service import convert_to_speech
            import base64, uuid

            audio_bytes = convert_to_speech(text)
            preview_id = str(uuid.uuid4())
            _audio_previews[preview_id] = audio_bytes

            return jsonify({
                "success": True,
                "preview_id": preview_id,
                "audio_b64": base64.b64encode(audio_bytes).decode("utf-8"),
                "duration_ms": len(audio_bytes) // 16,  # approximation
            }), 200

        except Exception as e:
            logger.error(f"❌ replace_audio_preview: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/audio/<path:filename>/replace-confirm", methods=["POST"])
    def replace_audio_confirm(folder_id, filename):
        """Splice le preview TTS dans l'audio original et upload sur Azure (irréversible)."""
        denied = _require_admin()
        if denied:
            return denied
        try:
            data = request.get_json() or {}
            preview_id = data.get("preview_id")
            start_ms = int(data.get("start_ms", 0))
            end_ms = int(data.get("end_ms", 0))

            if not preview_id or preview_id not in _audio_previews:
                return jsonify({"success": False, "error": "Preview introuvable ou expiré"}), 404
            if end_ms <= start_ms:
                return jsonify({"success": False, "error": "end_ms doit être > start_ms"}), 400

            platform_id = _get_platform_id_for_folder(folder_id)
            source_blob_path = _get_audio_blob_path(platform_id, folder_id, filename)
            target_blob_path = _get_audio_blob_path(platform_id, folder_id, filename, for_write=True)

            from services.azure_blob_service import download_blob, upload_blob, CONTAINER_AUDIOS
            from pydub import AudioSegment
            import io

            preview_bytes = _audio_previews.pop(preview_id)  # consommer le preview
            original_bytes = download_blob(CONTAINER_AUDIOS, source_blob_path)

            original = AudioSegment.from_file(io.BytesIO(original_bytes), format="mp3")
            new_segment = AudioSegment.from_file(io.BytesIO(preview_bytes), format="mp3")

            result = original[:start_ms] + new_segment + original[end_ms:]

            buf = io.BytesIO()
            result.export(buf, format="mp3", bitrate="128k")
            result_bytes = buf.getvalue()

            upload_blob(CONTAINER_AUDIOS, target_blob_path, result_bytes)
            set_platform_asset_binding_mode(platform_id, "copy_on_write")
            logger.info(f"🔄 Replace {filename}: [{start_ms}ms-{end_ms}ms] → {len(new_segment)}ms de nouveau TTS")

            return jsonify({
                "success": True,
                "original_duration_ms": len(original),
                "new_duration_ms": len(result),
            }), 200

        except Exception as e:
            logger.error(f"❌ replace_audio_confirm: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── Détection anomalies audio ───────────────────────────────────────────
    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/audio/<path:filename>/detect-bugs", methods=["POST"])
    def detect_audio_bugs(folder_id, filename):
        """
        Détecte les passages où la voix TTS change de caractère (timbre, pitch anormal).
        Utilise les MFCCs (empreinte vocale) sur les frames vocalisées uniquement.
        Ignore les silences et pauses normales.
        """
        denied = _require_admin()
        if denied:
            return denied
        try:
            import tempfile
            import numpy as np
            import librosa
            from services.azure_blob_service import download_blob, CONTAINER_AUDIOS

            data = request.get_json() or {}
            seuil = float(data.get("seuil", 4.5))
            duree_min = float(data.get("duree_min", 1.5))

            platform_id = _get_platform_id_for_folder(folder_id)
            blob_path = _get_audio_blob_path(platform_id, folder_id, filename)

            logger.info(f"🔍 Analyse bugs audio : {blob_path}")
            audio_bytes = download_blob(CONTAINER_AUDIOS, blob_path)

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            try:
                y, sr = librosa.load(tmp_path, sr=22050, mono=True)
            finally:
                import os as _os
                _os.unlink(tmp_path)

            hop_length = 512  # ~23ms par frame

            # ── Étape 1 : masque de silence ──────────────────────────────────
            # On ignore les frames silencieuses (pauses normales entre phrases)
            rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
            seuil_silence = np.percentile(rms, 20)  # les 20% les plus calmes = silence
            voiced_mask = rms > (seuil_silence * 3)   # frame active si énergie > 3x le bruit de fond

            # ── Étape 2 : MFCCs — empreinte du timbre vocal ──────────────────
            # 13 coefficients cepstraux = signature du caractère de la voix
            mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, hop_length=hop_length)

            # ── Étape 3 : centroïde spectral — détecte les aigus/graves anormaux
            centroide = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop_length)[0]

            # ── Étape 4 : pitch (hauteur fondamentale) ───────────────────────
            pitch = librosa.yin(y, fmin=60, fmax=400, hop_length=hop_length)

            n_frames = min(len(voiced_mask), mfcc.shape[1], len(centroide), len(pitch))
            suspicion = np.zeros(n_frames, dtype=float)

            # Calculer les stats uniquement sur les frames vocalisées
            voiced_indices = np.where(voiced_mask[:n_frames])[0]
            if len(voiced_indices) < 10:
                return jsonify({"success": True, "bugs": [], "total": 0}), 200

            # Anomalie sur chaque MFCC coefficient (timbre)
            for i in range(mfcc.shape[0]):
                coef = mfcc[i, :n_frames]
                voiced_vals = coef[voiced_indices]
                median = np.median(voiced_vals)
                std = np.std(voiced_vals)
                if std < 1e-6:
                    continue
                z = np.abs((coef - median) / std)
                # Compter seulement sur les frames vocalisées
                suspicion += (z > seuil) * voiced_mask[:n_frames]

            # Anomalie sur le centroïde spectral (aigus/graves)
            c_voiced = centroide[:n_frames][voiced_indices]
            c_median = np.median(c_voiced)
            c_std = np.std(c_voiced)
            if c_std > 1e-6:
                z_c = np.abs((centroide[:n_frames] - c_median) / c_std)
                suspicion += (z_c > seuil) * voiced_mask[:n_frames] * 2  # poids double car très discriminant

            # Anomalie sur le pitch
            p_voiced = pitch[:n_frames][voiced_indices]
            p_voiced = p_voiced[p_voiced > 0]  # ignorer les frames non-pitchées (consonnes, silences)
            if len(p_voiced) > 10:
                p_median = np.median(p_voiced)
                p_std = np.std(p_voiced)
                if p_std > 1e-6:
                    z_p = np.abs((pitch[:n_frames] - p_median) / p_std)
                    suspicion += (z_p > seuil) * voiced_mask[:n_frames] * 2  # poids double

            # Normaliser : seuil de suspicion global pour marquer une frame comme bug
            seuil_bug = 3  # au moins 3 points de suspicion cumulés
            bug_frames = suspicion > seuil_bug

            # ── Étape 5 : regrouper les frames consécutives en segments ──────
            frames_temps = librosa.frames_to_time(np.arange(n_frames), sr=sr, hop_length=hop_length)

            bugs = []
            en_bug = False
            debut_bug = 0.0
            score_max = 0.0

            for i in range(n_frames):
                t = float(frames_temps[i])
                is_bug = bool(bug_frames[i])
                score = float(suspicion[i])

                if is_bug and not en_bug:
                    en_bug = True
                    debut_bug = t
                    score_max = score
                elif is_bug and en_bug:
                    score_max = max(score_max, score)
                elif not is_bug and en_bug:
                    duree = t - debut_bug
                    if duree >= duree_min:
                        severity = 3 if score_max > 15 else 2 if score_max > 8 else 1
                        bugs.append({"start": debut_bug, "end": t, "severity": severity})
                    en_bug = False
                    score_max = 0.0

            if en_bug and n_frames > 0:
                duree = float(frames_temps[-1]) - debut_bug
                if duree >= duree_min:
                    severity = 3 if score_max > 15 else 2 if score_max > 8 else 1
                    bugs.append({"start": debut_bug, "end": float(frames_temps[-1]), "severity": severity})

            logger.info(f"✅ {len(bugs)} anomalies vocales détectées dans {filename}")
            return jsonify({"success": True, "bugs": bugs, "total": len(bugs)}), 200

        except Exception as e:
            logger.error(f"❌ detect_audio_bugs: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── Analyse mots d'un dossier ───────────────────────────────────────────
    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/analyse", methods=["GET"])
    def analyse_folder_words(folder_id):
        """Compte les mots des PDFs d'un dossier et indique si le contenu suffit pour une journée."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            folder = get_course_folder_identity(folder_id)
            if not folder:
                return jsonify({"success": False, "error": "Dossier introuvable"}), 404

            platform_id = int(folder["platform_id"])

            from services.playlist_tts_service import count_words_in_folder
            result = count_words_in_folder(platform_id, folder_id)

            return jsonify({"success": True, **result}), 200

        except Exception as e:
            logger.error(f"❌ Erreur analyse_folder_words: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── Remplir plateforme depuis un dossier ────────────────────────────────
    @hr_bp.route("/api/hr/platforms/<int:platform_id>/fill-from-folder", methods=["POST"])
    def fill_from_folder(platform_id):
        """
        Copie la playlist exacte d'un dossier vers le container audio de la plateforme.
        Un dossier V2 utilise son manifeste immuable dynamique ; un dossier
        historique conserve les 19 noms canoniques.

        Tous les fichiers requis sont validés et lus en mémoire avant
        l'archivage des audios publics. Le fallback ``audioqapause`` reste
        strictement réservé aux playlists V1 historiques.
        """
        denied = _require_admin()
        if denied:
            return denied

        try:
            data = request.get_json() or {}
            folder_id = data.get("folder_id")
            if not folder_id:
                return jsonify({"success": False, "error": "folder_id requis"}), 400
            if isinstance(folder_id, bool):
                return jsonify({"success": False, "error": "folder_id invalide"}), 400
            try:
                folder_id = int(folder_id)
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "folder_id invalide"}), 400
            raw_session_id = data.get("session_id")
            session_id = None
            if raw_session_id not in (None, ""):
                if isinstance(raw_session_id, bool):
                    return jsonify({"success": False, "error": "session_id invalide"}), 400
                try:
                    session_id = int(raw_session_id)
                except (TypeError, ValueError):
                    return jsonify({"success": False, "error": "session_id invalide"}), 400
                if session_id <= 0:
                    return jsonify({"success": False, "error": "session_id invalide"}), 400

            # ``folder_id`` vient du corps et n'est donc pas couvert par le
            # garde URL. Résoudre son centre avant le moindre lookup Blob/DB
            # métier empêche de copier le contenu d'un autre tenant.
            folder_denied = _require_hr_resource_access("folder", folder_id)
            if folder_denied:
                return folder_denied

            # Vérifier que le dossier appartient à cette plateforme, ou à la
            # plateforme générée qui sert de source à cette plateforme historique.
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT cf.name, cf.platform_id
                FROM cours_folders cf
                LEFT JOIN platform_config source_pc ON source_pc.id = cf.platform_id
                WHERE cf.id = ?
                  AND (cf.platform_id = ? OR source_pc.source_formation_id = ?)
                """,
                (folder_id, platform_id, platform_id),
            )
            folder_row = cursor.fetchone()
            conn.close()

            if not folder_row:
                return jsonify({"success": False, "error": "Dossier introuvable pour cette plateforme"}), 404
            origin = resolve_folder_asset_origin(folder_id) or {}
            source_platform_id = int(origin.get("source_platform_id") or folder_row[1])

            tts_conn = os.environ.get("AZURE_TTS_STORAGE_CONNECTION_STRING")
            audio_conn = os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING")

            if not tts_conn or not audio_conn:
                return jsonify({"success": False, "error": "Configuration Azure manquante"}), 500

            pinfo = _get_platform_info(platform_id)
            dest_container = pinfo["audio_container"]

            from azure.storage.blob import BlobServiceClient as _BSC
            tts_bsc = _BSC.from_connection_string(tts_conn)
            audio_bsc = _BSC.from_connection_string(audio_conn)

            dest_cc = audio_bsc.get_container_client(dest_container)
            qa_pause_cc = audio_bsc.get_container_client("audioqapause")
            playlist_cc = tts_bsc.get_container_client("audiostts")

            # Résoudre chaque fichier via le manifeste du professeur. Un clone
            # inter-centres lit ainsi la copie canonique immuable et ne dépend
            # plus du chemin historique de la plateforme qui l'a générée.
            from services.day_playlist_service import resolve_folder_playlist

            playlist_contract = resolve_folder_playlist(folder_id)
            schedule_schema_version = int(
                playlist_contract.get("schema_version") or 1
            )
            if schedule_schema_version not in (1, 2):
                return jsonify({
                    "success": False,
                    "error": (
                        "Version de planning audio non prise en charge : "
                        f"{schedule_schema_version}"
                    ),
                }), 409

            playlist_items = list(playlist_contract.get("playlist_items") or [])
            if not playlist_items:
                return jsonify({
                    "success": False,
                    "error": "Le manifeste audio du dossier est vide",
                }), 409

            # Construire le plan de copie dans l'ordre exact du manifeste.
            # En V2, aucune liste historique ni aucun fichier statique ne doit
            # pouvoir compléter silencieusement le snapshot immuable.
            copy_plan = []
            seen_filenames = set()
            invalid_manifest_files = []
            has_course = False
            for item in playlist_items:
                try:
                    filename, _duration, file_type, _course_index = item
                except (TypeError, ValueError):
                    invalid_manifest_files.append(str(item))
                    continue
                filename = str(filename or "").strip()
                file_type = str(file_type or "").strip().lower()
                safe_filename = os.path.basename(filename)
                relative_path = f"playlist/{safe_filename}"
                if (
                    not filename
                    or filename != safe_filename
                    or safe_filename in seen_filenames
                    or (
                        schedule_schema_version == 1
                        and relative_path not in CANONICAL_AUDIO_PLAYLIST_PATHS
                    )
                ):
                    invalid_manifest_files.append(filename or "(vide)")
                    continue
                seen_filenames.add(safe_filename)
                has_course = has_course or file_type in ("course", "cours")
                copy_plan.append({
                    "filename": safe_filename,
                    "file_type": file_type,
                    "relative_path": relative_path,
                })

            if invalid_manifest_files or len(copy_plan) != len(playlist_items):
                return jsonify({
                    "success": False,
                    "error": "Le manifeste audio du dossier est invalide",
                    "invalid_files": invalid_manifest_files,
                }), 409
            if not has_course:
                return jsonify({
                    "success": False,
                    "error": (
                        "Aucun fichier cours généré dans ce dossier. "
                        "Lancez d'abord la pipeline."
                    ),
                }), 404

            if session_id is not None:
                target_session = get_audio_generation_session(platform_id, session_id)
                if not target_session or str(target_session.get("status") or "") not in {"planned", "active"}:
                    return jsonify({
                        "success": False,
                        "error": "La séance de remplacement est introuvable ou terminée",
                    }), 404
                module_day_id = playlist_contract.get("module_day_id")
                if schedule_schema_version != 2 or not module_day_id:
                    return jsonify({
                        "success": False,
                        "error": "Seule une journée planifiée V2 peut remplacer cette séance",
                    }), 409

                publish_result = publish_playlist_audio_to_platform(
                    platform_id,
                    folder_id,
                    filenames=[item["filename"] for item in copy_plan],
                    source_platform_id=source_platform_id,
                    destination_prefix=f"course-sessions/{session_id}",
                    create_playback_manifest=True,
                )
                publish_errors = publish_result.get("publish_errors") or []
                published = publish_result.get("published") or []
                if publish_errors or len(published) != len(copy_plan):
                    return jsonify({
                        "success": False,
                        "error": "La copie du cours de remplacement est incomplète",
                        "error_details": publish_errors,
                    }), 409
                completed_at = datetime.now(FRANCE_TZ)
                assigned = assign_fallback_audio_to_session(
                    platform_id,
                    session_id,
                    module_day_id=int(module_day_id),
                    folder_id=folder_id,
                    completed_at=completed_at,
                )
                if not assigned:
                    return jsonify({
                        "success": False,
                        "error": "La séance a changé pendant la copie. Rechargez la fiche.",
                    }), 409
                return jsonify({
                    "success": True,
                    "copied": len(published),
                    "errors": 0,
                    "files": published,
                    "folder_name": folder_row[0],
                    "session_id": session_id,
                    "scheduled_at": target_session.get("scheduled_at"),
                    "schedule_schema_version": schedule_schema_version,
                    "fallback_assigned": True,
                }), 200

            prepared_files = []
            missing_required_files = []
            unreadable_required_files = []
            for planned in copy_plan:
                filename = planned["filename"]
                blob_path = resolve_folder_blob_path(
                    folder_id,
                    CONTAINER_AUDIOS,
                    planned["relative_path"],
                    fallback_platform_id=source_platform_id,
                )
                source_client = playlist_cc.get_blob_client(blob_path)
                audio_bytes = None
                source_kind = "playlist"
                source_error = None
                try:
                    if source_client.exists():
                        audio_bytes = source_client.download_blob().readall()
                except Exception as exc:
                    source_error = exc
                if audio_bytes is not None and not audio_bytes:
                    source_error = ValueError("fichier audio vide")
                    audio_bytes = None

                # Compatibilité V1 uniquement : les Q&R et pauses historiques
                # peuvent toujours provenir du container statique.
                if (
                    audio_bytes is None
                    and schedule_schema_version == 1
                    and planned["file_type"] in ("qa", "pause", "pause_midi")
                ):
                    try:
                        audio_bytes = (
                            qa_pause_cc.get_blob_client(filename)
                            .download_blob()
                            .readall()
                        )
                        source_kind = "audioqapause"
                        source_error = None
                    except Exception as exc:
                        source_error = exc
                    if audio_bytes is not None and not audio_bytes:
                        source_error = ValueError("fichier audio statique vide")
                        audio_bytes = None

                if audio_bytes is None:
                    if source_error is None:
                        missing_required_files.append(filename)
                    else:
                        unreadable_required_files.append({
                            "filename": filename,
                            "error": str(source_error),
                        })
                    continue
                prepared_files.append({
                    "filename": filename,
                    "audio_bytes": audio_bytes,
                    "source": source_kind,
                })

            # Condition de sécurité : aucun archivage ni upload public tant que
            # chaque octet du manifeste n'a pas été lu avec succès.
            if missing_required_files or unreadable_required_files:
                version_label = "V2" if schedule_schema_version == 2 else "V1"
                failed_names = missing_required_files + [
                    item["filename"] for item in unreadable_required_files
                ]
                return jsonify({
                    "success": False,
                    "error": (
                        f"La playlist {version_label} est incomplète ou illisible : "
                        + ", ".join(failed_names)
                    ),
                    "missing_files": missing_required_files,
                    "unreadable_files": unreadable_required_files,
                }), 409

            archive_result = archive_public_platform_audios(
                platform_id,
                reason=f"fill-from-folder-{folder_id}",
            )

            copied_files = []
            errors = []
            for prepared in prepared_files:
                filename = prepared["filename"]
                try:
                    dest_cc.get_blob_client(filename).upload_blob(
                        prepared["audio_bytes"],
                        overwrite=True,
                    )
                    copied_files.append(filename)
                    if prepared["source"] == "audioqapause":
                        logger.info(f"   ♻️ Q&A/Pause V1 copié : {filename}")
                    else:
                        logger.info(f"   ✅ Playlist générée copiée : {filename}")
                except Exception as e:
                    logger.error(f"   ❌ Échec copie playlist {filename}: {e}")
                    errors.append({"filename": filename, "error": str(e)})

            logger.info(f"✅ fill-from-folder P{platform_id}/F{folder_id}: {len(copied_files)} fichiers copiés, {len(errors)} erreur(s)")

            return jsonify({
                "success": True,
                "copied": len(copied_files),
                "errors": len(errors),
                "files": copied_files,
                "error_details": errors,
                "folder_name": folder_row[0],
                "schedule_schema_version": schedule_schema_version,
                "archive": archive_result,
            }), 200

        except Exception as e:
            logger.error(f"❌ Erreur fill_from_folder: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── Routes Config Planning Été/Hiver ──────────────────────────────────
    @hr_bp.route("/api/hr/schedule-config", methods=["GET"])
    def get_schedule_config():
        """Retourne la config été/hiver pour toutes les plateformes"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            scope_sql, scope_params = _platform_access_clause("pc")
            cursor.execute(
                f"""
                SELECT pc.id, pc.name, pc.playlist_mode
                FROM platform_config pc
                WHERE {scope_sql}
                ORDER BY pc.id
                """,
                scope_params,
            )
            platforms = []
            for row in cursor.fetchall():
                platforms.append({
                    "id": row[0],
                    "name": row[1],
                    "playlist_mode": row[2],
                })
            conn.close()
            return jsonify({"success": True, "platforms": platforms}), 200
        except Exception as e:
            logger.error(f"❌ Erreur get_schedule_config: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/schedule-config", methods=["POST"])
    def set_schedule_config():
        """Met à jour le mode été/hiver pour les plateformes sélectionnées"""
        denied = _require_admin()
        if denied:
            return denied

        data = request.get_json()
        mode = data.get("mode")  # 'ete' ou 'hiver'
        raw_platform_ids = data.get("platform_ids", [])  # IDs des plateformes concernées

        if mode not in ("ete", "hiver"):
            return jsonify({"success": False, "error": "Mode invalide (ete ou hiver)"}), 400

        if not isinstance(raw_platform_ids, list):
            return jsonify({"success": False, "error": "platform_ids doit être une liste"}), 400
        if any(isinstance(pid, bool) for pid in raw_platform_ids):
            return jsonify({"success": False, "error": "platform_ids invalide"}), 400
        try:
            platform_ids = list(dict.fromkeys(int(pid) for pid in raw_platform_ids))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "platform_ids invalide"}), 400
        if any(pid <= 0 for pid in platform_ids):
            return jsonify({"success": False, "error": "platform_ids invalide"}), 400

        # Valider toute la sélection avant le reset. Sans ce préflight, une
        # liste mixte A+B pouvait déjà modifier A avant de découvrir B.
        for platform_id in platform_ids:
            platform_denied = _require_hr_resource_access("platform", platform_id)
            if platform_denied:
                return platform_denied

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            if _admin_account_type() == "training_center":
                center_account_id = _training_center_account_id()
                cursor.execute(
                    "UPDATE platform_config SET playlist_mode = NULL WHERE center_account_id = ?",
                    (center_account_id,),
                )
            else:
                # Le reset global reste une action superadmin explicite.
                cursor.execute("UPDATE platform_config SET playlist_mode = NULL")

            # Appliquer le mode aux plateformes sélectionnées
            for pid in platform_ids:
                if _admin_account_type() == "training_center":
                    cursor.execute(
                        """
                        UPDATE platform_config
                        SET playlist_mode = ?
                        WHERE id = ? AND center_account_id = ?
                        """,
                        (mode, pid, _training_center_account_id()),
                    )
                else:
                    cursor.execute(
                        "UPDATE platform_config SET playlist_mode = ? WHERE id = ?",
                        (mode, pid),
                    )

            conn.commit()
            conn.close()
            logger.info(f"✅ Schedule config: mode={mode}, plateformes={platform_ids}")
            return jsonify({"success": True}), 200
        except Exception as e:
            logger.error(f"❌ Erreur set_schedule_config: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── Routes Prompt TTS ─────────────────────────────────────────────────
    # Édite le prompt général de génération du contenu de formation.
    _TTS_PROMPT_FILE = os.path.join(
        os.path.dirname(__file__), "..", "prompts", "prompts-generaux-contenu-formation.md"
    )

    @hr_bp.route("/api/hr/tts-prompt", methods=["GET"])
    def get_tts_prompt():
        """Retourne le contenu du fichier de prompts généraux."""
        # Ce fichier est partagé par tous les tenants du processus : tant
        # qu'il n'existe pas de prompt par centre, il reste superadmin-only.
        denied = _require_global_hr_admin()
        if denied:
            return denied
        try:
            if not os.path.exists(_TTS_PROMPT_FILE):
                return jsonify({"success": True, "content": "", "exists": False}), 200
            with open(_TTS_PROMPT_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            return jsonify({"success": True, "content": content, "exists": True}), 200
        except Exception as e:
            logger.error(f"❌ Erreur get_tts_prompt: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/tts-prompt", methods=["POST"])
    def set_tts_prompt():
        """Écrase le contenu du fichier de prompts généraux."""
        denied = _require_global_hr_admin()
        if denied:
            return denied
        data = request.get_json() or {}
        content = data.get("content")
        if content is None:
            return jsonify({"success": False, "error": "content manquant"}), 400
        try:
            os.makedirs(os.path.dirname(_TTS_PROMPT_FILE), exist_ok=True)
            with open(_TTS_PROMPT_FILE, "w", encoding="utf-8") as f:
                f.write(content)
            # Invalider le cache des prompts chargés en mémoire
            # (le cache mtime du service rechargera automatiquement, mais on
            # force au cas où le mtime n'a pas changé avec précision suffisante)
            try:
                from services import content_generation_service as _cgs
                _cgs._PASSE_PROMPTS_SCRATCH = None
                _cgs._PASSE_PROMPTS = None
            except Exception:
                pass
            logger.info(f"✅ Prompt TTS (scratch) mis à jour ({len(content)} caractères)")
            return jsonify({"success": True}), 200
        except Exception as e:
            logger.error(f"❌ Erreur set_tts_prompt: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    return hr_bp
