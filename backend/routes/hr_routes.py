# hr_routes.py - Routes du Dashboard RH (centre de contrôle multi-plateformes)
import json
import os
import re
import time
import requests as http_requests
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, session, jsonify, Response, stream_with_context, send_file
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.exceptions import ResourceExistsError
from config import FRANCE_TZ, PIPELINE_DATABASE_BACKEND
from database.db import get_db_connection
from database.postgres import postgres_enabled
from repositories.core_repository import (
    get_training_center_by_id,
    upsert_cours_config,
    upsert_platform_config,
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
from repositories.pipeline_repository import (
    allocate_platform_id_from_postgres,
    get_course_folder_identity,
    hr_resource_belongs_to_center,
    list_course_folder_rows_for_platform,
    pipeline_job_belongs_to_center,
    platform_ids_use_postgres_allocator,
)
from services.course_schedule_service import (
    create_missing_course_schedule,
    ensure_course_schedule_tables,
    get_course_schedule_summary,
    process_due_reminders,
    run_scheduler_tick,
    save_course_schedule,
    update_course_schedule,
)
from services.export_service import generate_attendance_excel_export
from services.scheduled_audio_service import process_due_audio_generations
from services.audio_publish_service import archive_public_platform_audios, publish_playlist_audio_to_platform
from utils.logger import get_logger
from utils.slug import slugify, unique_slug
import state

logger = get_logger(__name__)

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

_POSTGRES_PIPELINE_BACKENDS = {"postgres", "postgresql", "supabase"}
_HR_SUPERADMIN_ACCOUNT_TYPES = {"legacy_admin", "superadmin"}


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


def create_hr_blueprint(socketio):
    """Factory pour créer le blueprint HR avec accès à socketio"""
    hr_bp = Blueprint("hr", __name__)

    @hr_bp.route("/api/hr/enabled")
    def get_hr_enabled():
        return jsonify({"enabled": HR_ENABLED})

    @hr_bp.before_request
    def check_hr_enabled():
        from flask import request as req
        # Ces endpoints restent accessibles même si HR est désactivé
        always_allowed = {"hr.get_hr_enabled", "hr.check_upload_permission", "hr.recorder_audio_list", "hr.auto_schedule"}
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
            ("request_id", "deletion_request"),
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
                    "nb_folders": row.get("nb_folders", 0),
                    "source_platform_name": row.get("source_platform_name"),
                    "voice_type": row.get("voice_type"),
                    "voice_updated_at": row.get("voice_updated_at"),
                    "schedule": row.get("schedule"),
                    "reusable": (
                        row.get("status") == "validated"
                        and row.get("nb_folders", 0) > 0
                        and row.get("voice_type") != "mock"
                    ),
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
                       m.voice_type, m.voice_updated_at
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
                "schedule": schedules_by_platform.get(r[6]),
                "reusable": r[4] == "validated" and r[8] > 0 and r[10] != "mock",
            } for r in rows]
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
                                'tts_launched',
                                'audio_running',
                                'audio_launched',
                                'audio_completed',
                                'completed'
                            )
                           OR j.auto_pilot_step = 'done'
                           OR COALESCE(j.auto_pilot_post_review_docs_done, 0) = 1
                           OR (
                                EXISTS (
                                    SELECT 1
                                    FROM cours_folders cf
                                    JOIN content_generation_jobs cgj ON cgj.folder_id = cf.id
                                    WHERE cf.formation_job_id = j.id
                                      AND cgj.status = 'completed'
                                )
                            AND NOT EXISTS (
                                    SELECT 1
                                    FROM cours_folders cf
                                    LEFT JOIN content_generation_jobs cgj ON cgj.folder_id = cf.id
                                    WHERE cf.formation_job_id = j.id
                                      AND COALESCE(cgj.status, '') != 'completed'
                                )
                           )
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

                cursor.execute(f"""
                    SELECT
                        pc.id,
                        pc.name,
                        pc.slug,
                        pc.upload_locked,
                        pc.pdf_filename,
                        pc.pdf_uploaded_at,
                        pc.updated_at,
                        pc.status,
                        pc.source_formation_id,
                        pc.source_module_id,
                        pc.center_account_id,
                        COALESCE(tca.slug, 'le-socrate') AS center_slug,
                        COALESCE(fm.rncp_code, fpj.rncp_code) AS source_rncp_code,
                        COALESCE(fm.tp_name, fpj.tp_name) AS source_tp_name,
                        fpj.status AS pipeline_status,
                        fpj.auto_pilot_step AS pipeline_auto_pilot_step,
                        fpj.auto_pilot_error AS pipeline_auto_pilot_error,
                        fpj.auto_pilot_enabled AS pipeline_auto_pilot_enabled
                    FROM platform_config pc
                    LEFT JOIN training_center_accounts tca ON tca.id = pc.center_account_id
                    LEFT JOIN formation_modules fm ON fm.id = pc.source_module_id
                    LEFT JOIN formation_pipeline_jobs fpj ON fpj.id = pc.source_formation_id
                    {platform_where}
                    ORDER BY pc.id
                """, platform_params)
                rows = cursor.fetchall()

                # Compter demandes en attente par plateforme
                cursor.execute("SELECT platform_id, COUNT(*) FROM deletion_requests WHERE status='pending' GROUP BY platform_id")
                pending_counts = dict(cursor.fetchall())
                conn.close()
            else:
                rows = [(
                    row["id"],
                    row.get("name"),
                    row.get("slug"),
                    row.get("upload_locked"),
                    row.get("pdf_filename"),
                    row.get("pdf_uploaded_at"),
                    row.get("updated_at"),
                    row.get("status"),
                    row.get("source_formation_id"),
                    row.get("source_module_id"),
                    row.get("center_account_id"),
                    row.get("center_slug") or "le-socrate",
                    row.get("source_rncp_code"),
                    row.get("source_tp_name"),
                    row.get("pipeline_status"),
                    row.get("pipeline_auto_pilot_step"),
                    row.get("pipeline_auto_pilot_error"),
                    row.get("pipeline_auto_pilot_enabled"),
                ) for row in postgres_dashboard_rows]
                pending_counts = {
                    row["id"]: row.get("pending_deletion_count", 0)
                    for row in postgres_dashboard_rows
                }

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

            platforms = []
            for row in rows:
                (
                    pid,
                    name,
                    slug,
                    upload_locked,
                    pdf_filename,
                    pdf_uploaded_at,
                    updated_at,
                    p_status,
                    p_source_formation_id,
                    p_source_module_id,
                    p_center_account_id,
                    p_center_slug,
                    p_source_rncp_code,
                    p_source_tp_name,
                    p_pipeline_status,
                    p_pipeline_auto_pilot_step,
                    p_pipeline_auto_pilot_error,
                    p_pipeline_auto_pilot_enabled,
                ) = row
                pinfo = _get_platform_info(pid)
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
                pending = pending_counts.get(pid, 0)
                if pending > 0:
                    alerts.append(f"{pending} demande(s) de suppression")

                effective_status = p_status or "ready"
                if effective_status == "pending":
                    pipeline_done = (
                        p_pipeline_auto_pilot_step == "done"
                        or p_pipeline_status in ("text_ready", "audio_completed", "audio_launched", "completed")
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

                platforms.append({
                    "id": pid,
                    "name": name,
                    "slug": slug,
                    "center_account_id": p_center_account_id,
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
        """Clone les cours_folders + cours_documents + blobs Azure d'une plateforme
        source vers une cible. Lancé en thread de fond : la plateforme cible reste
        en status 'pending' jusqu'à la fin, puis passe à 'ready'.

        Les blobs sont copiés en server-side copy (rapide, pas de download local).
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

            # 3. Copier les blobs Azure (server-side) pour chaque folder source → cible
            total_copied = 0
            for src_fid, new_fid in folder_id_map.items():
                src_prefix_docs = f"platform-{source_platform_id}/folder-{src_fid}/"
                dst_prefix_docs = f"platform-{target_platform_id}/folder-{new_fid}/"
                try:
                    total_copied += copy_blobs_by_prefix(CONTAINER_DOCUMENTS, src_prefix_docs, dst_prefix_docs)
                    total_copied += copy_blobs_by_prefix(CONTAINER_AUDIOS, src_prefix_docs, dst_prefix_docs)
                except Exception as e:
                    if postgres_clone:
                        # Ne jamais publier "ready" dans la source de vérité si
                        # les artefacts associés n'ont pas pu être copiés.
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
                f"— {len(folder_id_map)} folders, {total_copied} blobs copiés"
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
        2. {name, module_id} — crée une promo liée à un module maître (nouveau).
           Clone les cours+blobs depuis la plateforme source du module. Statut
           'pending' jusqu'à fin de copie.
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

        if not name:
            return jsonify({"success": False, "error": "Le nom est requis"}), 400
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
                        public_access_enabled)
                       VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, 1)""",
                    (
                        new_id,
                        name,
                        now_str,
                        slug,
                        initial_status,
                        formation_id,
                        module_id,
                        center_account_id,
                    ),
                )
            else:
                cursor.execute(
                    """INSERT INTO platform_config
                       (name, upload_locked, updated_at, slug, status, source_formation_id, source_module_id, center_account_id, public_access_enabled)
                       VALUES (?, 1, ?, ?, ?, ?, ?, ?, 1)""",
                    (name, now_str, slug, initial_status, formation_id, module_id, center_account_id),
                )
                new_id = cursor.lastrowid

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

            return jsonify({
                "success": True,
                "platform": {
                    "id": new_id,
                    "name": name,
                    "slug": slug,
                    "center_slug": center_slug,
                    "public_path": _class_public_path(center_slug, slug),
                    "public_url": _class_public_url(_get_platform_info(new_id).get("frontend_url"), center_slug, slug),
                    "status": initial_status,
                    "source_formation_id": formation_id,
                    "source_module_id": module_id,
                    "pipeline_job_id": linked_job_id,
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

    # ─── GET /api/recorder/audio-list (PAS d'auth admin) ─────────────────
    @hr_bp.route("/api/recorder/audio-list", methods=["GET"])
    def recorder_audio_list():
        """Liste les audios du container de ce backend (accessible sans session admin)"""
        try:
            connection_string = os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING")
            if not connection_string:
                return jsonify({"success": False, "audios": []}), 200

            container_name = os.environ.get("AZURE_AUDIO_CONTAINER", "formationaudio-dev")
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
                audios.append({"name": blob.name, "size": blob.size, "url": url})

            return jsonify({"success": True, "audios": audios}), 200

        except Exception as e:
            logger.warning(f"⚠️ Erreur recorder audio-list: {e}")
            return jsonify({"success": False, "audios": []}), 200

    # ─── GET /api/hr/upload-permission/<platform_id> (PAS d'auth admin) ──
    @hr_bp.route("/api/hr/upload-permission/<int:platform_id>", methods=["GET"])
    def check_upload_permission(platform_id):
        """Vérifie si l'upload est autorisé pour une plateforme (appelé par Recorder)"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT upload_locked FROM platform_config WHERE id = ?", (platform_id,))
            row = cursor.fetchone()
            conn.close()

            if not row:
                return jsonify({"success": False, "error": "Plateforme introuvable"}), 404

            return jsonify({
                "success": True,
                "upload_allowed": not bool(row[0]),
                "upload_locked": bool(row[0]),
            }), 200

        except Exception as e:
            logger.error(f"❌ Erreur check permission: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── POST /api/hr/deletion-requests (PAS d'auth admin) ──────────────
    @hr_bp.route("/api/hr/deletion-requests", methods=["POST"])
    def create_deletion_request():
        """Créer une demande de suppression (depuis Recorder)"""
        try:
            data = request.get_json()
            platform_id = data.get("platform_id")
            filename = data.get("filename", "").strip()
            requester_name = data.get("requester_name", "").strip()
            reason = data.get("reason", "").strip()

            if not platform_id or not filename or not requester_name:
                return jsonify({"success": False, "error": "platform_id, filename et requester_name requis"}), 400

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO deletion_requests (platform_id, filename, requester_name, reason, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
                (platform_id, filename, requester_name, reason, _now_str()),
            )
            conn.commit()
            request_id = cursor.lastrowid
            conn.close()

            logger.info(f"📨 Demande suppression #{request_id} : {filename} par {requester_name}")

            return jsonify({
                "success": True,
                "message": "Demande de suppression envoyée",
                "request_id": request_id,
            }), 201

        except Exception as e:
            logger.error(f"❌ Erreur création demande suppression: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── GET /api/hr/deletion-requests (admin) ───────────────────────────
    @hr_bp.route("/api/hr/deletion-requests", methods=["GET"])
    def list_deletion_requests():
        """Lister les demandes de suppression (filtrage optionnel par status)"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            status_filter = request.args.get("status", "pending")
            conn = get_db_connection()
            cursor = conn.cursor()
            scope_sql, scope_params = _platform_access_clause("pc")

            select_sql = """
                SELECT dr.id, dr.platform_id, dr.filename, dr.requester_name,
                       dr.reason, dr.status, dr.created_at, dr.resolved_at
                FROM deletion_requests dr
                JOIN platform_config pc ON pc.id = dr.platform_id
            """

            if status_filter == "all":
                cursor.execute(
                    select_sql + f" WHERE {scope_sql} ORDER BY dr.created_at DESC",
                    scope_params,
                )
            else:
                cursor.execute(
                    select_sql
                    + f" WHERE {scope_sql} AND dr.status = ? ORDER BY dr.created_at DESC",
                    [*scope_params, status_filter],
                )

            rows = cursor.fetchall()
            conn.close()

            requests_list = []
            for row in rows:
                requests_list.append({
                    "id": row[0],
                    "platform_id": row[1],
                    "filename": row[2],
                    "requester_name": row[3],
                    "reason": row[4],
                    "status": row[5],
                    "created_at": row[6],
                    "resolved_at": row[7],
                })

            return jsonify({"success": True, "requests": requests_list}), 200

        except Exception as e:
            logger.error(f"❌ Erreur liste demandes suppression: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── POST /api/hr/deletion-requests/<id>/approve ─────────────────────
    @hr_bp.route("/api/hr/deletion-requests/<int:request_id>/approve", methods=["POST"])
    def approve_deletion(request_id):
        """Approuver une demande de suppression (supprime le blob Azure)"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT platform_id, filename, status FROM deletion_requests WHERE id = ?",
                (request_id,),
            )
            row = cursor.fetchone()

            if not row:
                conn.close()
                return jsonify({"success": False, "error": "Demande introuvable"}), 404

            platform_id, filename, status = row

            if status != "pending":
                conn.close()
                return jsonify({"success": False, "error": f"Demande déjà {status}"}), 400

            # Supprimer le blob Azure si P1
            blob_deleted = False
            if platform_id == 1:
                _, container_client = _get_azure_audio_clients()
                if container_client:
                    try:
                        container_client.delete_blob(filename)
                        blob_deleted = True
                        logger.info(f"🗑️ Blob supprimé via demande #{request_id}: {filename}")
                    except Exception as blob_err:
                        logger.warning(f"⚠️ Blob introuvable ou déjà supprimé: {blob_err}")

            now = _now_str()
            cursor.execute(
                "UPDATE deletion_requests SET status = 'approved', resolved_at = ? WHERE id = ?",
                (now, request_id),
            )
            conn.commit()
            conn.close()

            return jsonify({
                "success": True,
                "message": f"Demande #{request_id} approuvée" + (" — fichier supprimé" if blob_deleted else ""),
                "blob_deleted": blob_deleted,
            }), 200

        except Exception as e:
            logger.error(f"❌ Erreur approbation demande: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── POST /api/hr/deletion-requests/<id>/reject ──────────────────────
    @hr_bp.route("/api/hr/deletion-requests/<int:request_id>/reject", methods=["POST"])
    def reject_deletion(request_id):
        """Rejeter une demande de suppression"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM deletion_requests WHERE id = ?", (request_id,))
            row = cursor.fetchone()

            if not row:
                conn.close()
                return jsonify({"success": False, "error": "Demande introuvable"}), 404

            if row[0] != "pending":
                conn.close()
                return jsonify({"success": False, "error": f"Demande déjà {row[0]}"}), 400

            now = _now_str()
            cursor.execute(
                "UPDATE deletion_requests SET status = 'rejected', resolved_at = ? WHERE id = ?",
                (now, request_id),
            )
            conn.commit()
            conn.close()

            logger.info(f"❌ Demande #{request_id} rejetée")

            return jsonify({"success": True, "message": f"Demande #{request_id} rejetée"}), 200

        except Exception as e:
            logger.error(f"❌ Erreur rejet demande: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── POST /api/hr/platforms/<id>/backup-and-unlock ───────────────────
    @hr_bp.route("/api/hr/platforms/<int:platform_id>/backup-and-unlock", methods=["POST"])
    def backup_and_unlock(platform_id):
        """Lance le backup en arrière-plan puis déverrouille l'upload"""
        denied = _require_admin()
        if denied:
            return denied

        # Refuser si un job est déjà en cours pour cette plateforme
        job = state.backup_jobs.get(platform_id, {})
        if job.get("step_status") == "running":
            return jsonify({"success": False, "error": "Un backup est déjà en cours"}), 409

        pinfo = _get_platform_info(platform_id)
        connection_string = os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING")
        archive_container = pinfo["audio_archive_container"]
        source_container = pinfo["audio_container"]

        if not connection_string:
            return jsonify({"success": False, "error": "Configuration Azure manquante"}), 500

        state.reset_backup_job(platform_id)

        socketio.start_background_task(
            _run_backup_and_unlock,
            platform_id, connection_string, source_container, archive_container
        )

        return jsonify({"success": True, "message": "Backup lancé"}), 202

    def _run_backup_and_unlock(platform_id, connection_string, source_container, archive_container):
        """Tâche de fond : backup vérifié + suppression + déverrouillage"""
        job = state.backup_jobs[platform_id]

        try:
            blob_service_client = BlobServiceClient.from_connection_string(connection_string)
            source_client = blob_service_client.get_container_client(source_container)
            account_name = blob_service_client.account_name
            account_key = blob_service_client.credential.account_key

            # Créer le container d'archive s'il n'existe pas
            archive_client = blob_service_client.get_container_client(archive_container)
            try:
                archive_client.create_container(public_access="blob")
            except ResourceExistsError:
                pass

            # Lister les blobs sources
            source_blobs = list(source_client.list_blobs())
            if not source_blobs:
                # Rien à sauvegarder, on déverrouille directement
                _unlock_platform(platform_id)
                job["step"] = 3
                job["step_status"] = "done"
                return

            # Dossier d'archive horodaté
            archive_folder = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d_%Hh%M") + f"/plateforme-{platform_id}"
            job["archive_folder"] = archive_folder
            job["total"] = len(source_blobs)

            # ── ÉTAPE 1 : Copie vers l'archive ──────────────────────────
            job["step"] = 1
            job["step_status"] = "running"
            logger.info(f"📦 Backup P{platform_id} : {len(source_blobs)} fichiers → {archive_folder}")

            expiry = datetime.now(timezone.utc) + timedelta(hours=2)
            copied_names = []

            for idx, blob in enumerate(source_blobs):
                job["progress"] = idx + 1

                # Générer une URL SAS pour la source (copie server-side)
                sas_token = generate_blob_sas(
                    account_name=account_name,
                    container_name=source_container,
                    blob_name=blob.name,
                    account_key=account_key,
                    permission=BlobSasPermissions(read=True),
                    expiry=expiry,
                )
                source_url = f"https://{account_name}.blob.core.windows.net/{source_container}/{blob.name}?{sas_token}"

                dest_name = f"{archive_folder}/{blob.name}"
                dest_blob = archive_client.get_blob_client(dest_name)
                dest_blob.start_copy_from_url(source_url)

                # Attendre la fin de la copie
                for _ in range(60):  # max 30 secondes par fichier
                    props = dest_blob.get_blob_properties()
                    if props.copy.status == "success":
                        break
                    elif props.copy.status == "failed":
                        raise Exception(f"Copie échouée pour {blob.name} : {props.copy.status_description}")
                    time.sleep(0.5)
                else:
                    raise Exception(f"Timeout lors de la copie de {blob.name}")

                copied_names.append(blob.name)
                logger.info(f"  ✅ Archivé : {blob.name}")

            # ── VÉRIFICATION : on ne supprime rien sans confirmation ─────
            logger.info("🔍 Vérification de l'archive...")
            archive_blobs = {
                b.name.replace(f"{archive_folder}/", "")
                for b in archive_client.list_blobs(name_starts_with=archive_folder + "/")
            }
            source_names = {b.name for b in source_blobs}

            missing = source_names - archive_blobs
            if missing:
                error_msg = f"Vérification échouée — {len(missing)} fichier(s) manquant(s) dans l'archive. Aucune suppression effectuée."
                logger.error(f"❌ {error_msg} : {missing}")
                job["step_status"] = "error"
                job["error"] = error_msg
                return

            logger.info(f"✅ Vérification OK — {len(archive_blobs)} fichiers confirmés dans l'archive")

            # ── ÉTAPE 2 : Suppression des sources (vérification OK) ──────
            job["step"] = 2
            job["step_status"] = "running"
            job["progress"] = 0

            for idx, blob in enumerate(source_blobs):
                source_client.delete_blob(blob.name)
                job["progress"] = idx + 1
                logger.info(f"  🗑️ Supprimé : {blob.name}")

            # Second passage : si un blob apparaît après le listing initial, ou
            # si Azure renvoie une page incomplète pendant le backup, on vide le
            # container avant de rouvrir les uploads.
            remaining_deleted = 0
            while True:
                remaining_blobs = list(source_client.list_blobs())
                if not remaining_blobs:
                    break
                for blob in remaining_blobs:
                    source_client.delete_blob(blob.name)
                    remaining_deleted += 1
                    logger.info(f"  🗑️ Supprimé après vérification : {blob.name}")

            if remaining_deleted:
                job["remaining_deleted"] = remaining_deleted
                logger.info(
                    f"🧹 Backup P{platform_id} : {remaining_deleted} fichier(s) restant(s) supprimé(s)"
                )

            # ── ÉTAPE 3 : Déverrouillage ─────────────────────────────────
            job["step"] = 3
            job["step_status"] = "running"
            _unlock_platform(platform_id)
            logger.info(f"🔓 Plateforme {platform_id} déverrouillée")

            job["step_status"] = "done"

        except Exception as e:
            logger.error(f"❌ Erreur backup P{platform_id}: {e}")
            job["step_status"] = "error"
            job["error"] = str(e)

    def _unlock_platform(platform_id):
        """Met upload_locked = 0 en base et propage vers le backend distant (P2/P3)"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE platform_config SET upload_locked = 0, updated_at = ? WHERE id = ?",
            (_now_str(), platform_id),
        )
        conn.commit()
        conn.close()
        if not _is_local_platform(platform_id):
            _call_platform(
                platform_id,
                "/api/internal/set-lock",
                json_data={"locked": False, "platform_id": platform_id},
            )

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
                conn = get_db_connection()
                cursor = conn.cursor()
                schedule_summary = get_course_schedule_summary(cursor, platform_id)
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

    @hr_bp.route("/api/hr/platforms/<int:platform_id>/student-emails", methods=["GET"])
    def get_platform_student_emails(platform_id):
        denied = _require_admin()
        if denied:
            return denied
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            _ensure_course_reminder_recipients(cursor)
            cursor.execute(
                """
                SELECT id, email, created_at
                FROM course_reminder_recipients
                WHERE platform_id = ?
                ORDER BY email COLLATE NOCASE
                """,
                (platform_id,),
            )
            recipients = [
                {"id": row[0], "email": row[1], "created_at": row[2]}
                for row in cursor.fetchall()
            ]
            conn.close()
            return jsonify({"success": True, "recipients": recipients}), 200
        except Exception as e:
            logger.error(f"❌ Erreur get student emails P{platform_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/platforms/<int:platform_id>/student-emails", methods=["POST"])
    def add_platform_student_emails(platform_id):
        denied = _require_admin()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        raw_emails = data.get("emails")
        if raw_emails is None:
            raw_emails = data.get("email", "")
        if isinstance(raw_emails, str):
            candidates = raw_emails.replace(";", ",").replace("\n", ",").split(",")
        else:
            candidates = raw_emails or []
        emails = []
        for item in candidates:
            email = str(item or "").strip().lower()
            if not email:
                continue
            if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
                return jsonify({"success": False, "error": f"Email invalide: {email}"}), 400
            if email not in emails:
                emails.append(email)
        if not emails:
            return jsonify({"success": False, "error": "Ajoute au moins un email"}), 400
        try:
            now = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
            conn = get_db_connection()
            cursor = conn.cursor()
            _ensure_course_reminder_recipients(cursor)
            for email in emails:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO course_reminder_recipients (platform_id, email, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (platform_id, email, now),
                )
            conn.commit()
            cursor.execute(
                """
                SELECT id, email, created_at
                FROM course_reminder_recipients
                WHERE platform_id = ?
                ORDER BY email COLLATE NOCASE
                """,
                (platform_id,),
            )
            recipients = [
                {"id": row[0], "email": row[1], "created_at": row[2]}
                for row in cursor.fetchall()
            ]
            conn.close()
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
            conn = get_db_connection()
            cursor = conn.cursor()
            _ensure_course_reminder_recipients(cursor)
            cursor.execute(
                "DELETE FROM course_reminder_recipients WHERE id = ? AND platform_id = ?",
                (recipient_id, platform_id),
            )
            changed = cursor.rowcount
            conn.commit()
            conn.close()
            if not changed:
                return jsonify({"success": False, "error": "Email introuvable"}), 404
            return jsonify({"success": True}), 200
        except Exception as e:
            logger.error(f"❌ Erreur delete student email P{platform_id}: {e}")
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
        if not heure_str:
            return jsonify({"success": False, "error": "heure_cours requis"}), 400

        if _is_local_platform(platform_id):
            # Appel direct au service local
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                schedule_update = update_course_schedule(
                    cursor,
                    platform_id,
                    start_time=heure_str,
                    weekdays=weekdays,
                )
                if schedule_update:
                    conn.commit()
                    conn.close()
                    return jsonify({
                        "success": True,
                        "message": "Planning des journées mis à jour",
                        "schedule": schedule_update,
                    }), 200
                cursor.execute("SELECT COUNT(*) FROM cours_folders WHERE platform_id = ?", (platform_id,))
                folder_count = int((cursor.fetchone() or [0])[0] or 0)
                schedule_update = create_missing_course_schedule(
                    cursor,
                    platform_id,
                    total_training_days=folder_count,
                    start_time=heure_str,
                    date_str=date_str or None,
                    weekdays=weekdays,
                )
                if schedule_update:
                    conn.commit()
                    conn.close()
                    return jsonify({
                        "success": True,
                        "message": "Planning des journées créé",
                        "schedule": schedule_update,
                    }), 200
                conn.close()

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
        puis lance l'audio uniquement pour les séances dues dans la fenêtre 24h.
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
        """Lance la génération audio pour un document"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Mettre à jour le statut
            cursor.execute("UPDATE cours_documents SET status = 'processing' WHERE id = ?", (document_id,))
            conn.commit()
            conn.close()

            # Lancer en background avec eventlet
            import eventlet
            eventlet.spawn(_process_document_background, document_id)

            return jsonify({"success": True, "status": "processing"}), 200
        except Exception as e:
            logger.error(f"❌ Erreur generate_document_audio: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/generate-all-audio", methods=["POST"])
    def generate_folder_audio(folder_id):
        """Lance la génération audio pour tous les documents d'un dossier"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Récupérer les documents sans audio
            cursor.execute(f"""
                SELECT id FROM cours_documents
                WHERE folder_id = ? AND audio_filename IS NULL
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
            """, (folder_id,))
            docs = [{"id": row[0]} for row in cursor.fetchall()]
            conn.close()

            if not docs:
                return jsonify({"success": True, "message": "Tous les documents ont déjà un audio"}), 200

            # Lancer en background (séquentiel)
            import eventlet
            eventlet.spawn(_process_folder_background, folder_id)

            return jsonify({"success": True, "processing": len(docs)}), 200
        except Exception as e:
            logger.error(f"❌ Erreur generate_folder_audio: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

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

    # ─── Génération de contenu TTS-direct ────────────────────────────────

    # État en mémoire pour le suivi temps-réel (par folder_id)
    _content_jobs = {}

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job", methods=["POST"])
    def create_content_job(folder_id):
        """
        Crée ou réinitialise un job de génération de contenu.
        Extrait les sous-parties synchroniquement depuis le programme fourni.
        Body: { program_text: str }
        """
        denied = _require_admin()
        if denied:
            return denied

        data = request.get_json()
        program_text = (data.get("program_text") or "").strip()
        if not program_text or len(program_text) < 50:
            return jsonify({"success": False, "error": "Programme trop court ou vide"}), 400

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT platform_id FROM cours_folders WHERE id = ?", (folder_id,))
            row = cursor.fetchone()
            conn.close()
            if not row:
                return jsonify({"success": False, "error": "Dossier introuvable"}), 404
            platform_id = row[0]

            # Extraction des sous-parties (synchrone ~5s)
            from services.content_generation_service import extract_sub_parts
            extracted = extract_sub_parts(program_text)
            program_title = extracted["title"]
            sub_parts = extracted["sub_parts"]

            import json as _json
            conn = get_db_connection()
            cursor = conn.cursor()
            # Supprimer les anciens segments si on réinitialise
            cursor.execute("""
                DELETE FROM content_generation_segments WHERE job_id IN (
                    SELECT id FROM content_generation_jobs WHERE folder_id = ?
                )
            """, (folder_id,))
            cursor.execute("""
                INSERT OR REPLACE INTO content_generation_jobs
                    (folder_id, platform_id, program_text, program_title, sub_parts,
                     status, current_sub_part, current_passe, total_words, error_message)
                VALUES (?, ?, ?, ?, ?, 'idle', 0, 1, 0, NULL)
            """, (folder_id, platform_id, program_text, program_title, _json.dumps(sub_parts)))
            conn.commit()
            conn.close()

            # Réinitialiser l'état en mémoire
            _content_jobs[folder_id] = {
                "status": "idle",
                "current_sub_part": 0,
                "current_passe": 1,
                "total_words": 0,
                "message": "Sous-parties extraites, prêt à lancer.",
            }

            return jsonify({
                "success": True,
                "program_title": program_title,
                "sub_parts": sub_parts,
            }), 200

        except Exception as e:
            logger.error(f"❌ Erreur create_content_job: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/start", methods=["POST"])
    def start_content_job(folder_id):
        """Lance ou reprend la génération de contenu en background."""
        denied = _require_admin()
        if denied:
            return denied

        # Vérifier qu'un job n'est pas déjà en cours
        if _content_jobs.get(folder_id, {}).get("status") == "running":
            return jsonify({"success": False, "error": "Génération déjà en cours"}), 409

        from services.content_generation_service import get_job_from_db
        job = get_job_from_db(folder_id)
        if not job:
            return jsonify({"success": False, "error": "Aucun job configuré pour ce dossier"}), 404
        if job["status"] == "completed":
            return jsonify({"success": False, "error": "Job déjà terminé"}), 409

        _content_jobs[folder_id] = {
            "status": "running",
            "current_sub_part": job["current_sub_part"],
            "current_passe": job["current_passe"],
            "total_words": job["total_words"],
            "message": "Démarrage de la génération...",
        }

        def _on_progress(sub_idx, total_sub, passe, total_words, message):
            _content_jobs[folder_id].update({
                "current_sub_part": sub_idx,
                "current_passe": passe,
                "total_words": total_words,
                "message": message,
            })

        body = request.get_json(silent=True) or {}
        mode = body.get("mode", "normal")  # "normal" | "mock" | "mini"
        if mode not in ("normal", "mock", "mini"):
            mode = "normal"

        if mode != "normal":
            _content_jobs[folder_id]["message"] = f"[MODE {mode.upper()}] Démarrage..."

        def _run():
            try:
                from services.content_generation_service import run_content_generation
                run_content_generation(folder_id, on_progress=_on_progress, mode=mode)
                _content_jobs[folder_id]["status"] = "completed"
            except Exception as e:
                _content_jobs[folder_id].update({"status": "error", "message": str(e)})

        import eventlet
        eventlet.spawn(_run)

        return jsonify({"success": True, "message": "Génération lancée"}), 202

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

        # Fusionner l'état DB avec l'état en mémoire (plus frais)
        mem = _content_jobs.get(folder_id, {})
        status = mem.get("status") or job["status"]
        total_words = mem.get("total_words") or job["total_words"]
        current_sub_part = mem.get("current_sub_part", job["current_sub_part"])
        current_passe = mem.get("current_passe", job["current_passe"])
        message = mem.get("message", "")

        segments = get_segments_status(job["id"]) if job["id"] else []

        return jsonify({
            "success": True,
            "job": {
                "status": status,
                "program_title": job["program_title"],
                "sub_parts": job["sub_parts"],
                "current_sub_part": current_sub_part,
                "current_passe": current_passe,
                "total_words": total_words,
                "message": message,
                "error_message": job["error_message"],
                "segments": segments,
                "num_sub_parts": len(job["sub_parts"]),
            },
        }), 200

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/cancel", methods=["POST"])
    def cancel_content_job(folder_id):
        """Annule un job en cours (marque cancelled en DB, stoppe le polling)."""
        denied = _require_admin()
        if denied:
            return denied

        from services.content_generation_service import get_job_from_db
        job = get_job_from_db(folder_id)
        if job:
            from database.db import get_db_connection as _gdb
            conn = _gdb()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE content_generation_jobs SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE folder_id = ?",
                (folder_id,)
            )
            conn.commit()
            conn.close()

        if folder_id in _content_jobs:
            _content_jobs[folder_id]["status"] = "cancelled"

        return jsonify({"success": True}), 200

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
        """Phase 3b' : applique les règles au TEXTE des segments (pas aux MP3).

        Async : démarre un greenlet eventlet et retourne immédiatement un
        task_id. Le frontend poll ensuite GET .../rules/review-text/status/<id>
        pour suivre la progression (utile parce que la revérif prend 10-15 min
        et dépasserait le timeout HTTP Azure App Service ~230s).
        """
        denied = _require_admin()
        if denied:
            return denied
        try:
            from services.script_rules_service import start_text_review_async
            payload = request.get_json() or {}
            dry_run = bool(payload.get("dry_run") or False)
            sub_part_indices = payload.get("sub_part_indices")
            if sub_part_indices and not isinstance(sub_part_indices, list):
                sub_part_indices = None
            task_id = start_text_review_async(
                folder_id,
                dry_run=dry_run,
                sub_part_indices=sub_part_indices,
            )
            return jsonify({"success": True, "task_id": task_id, "dry_run": dry_run}), 202
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"❌ Erreur review text: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/rules/review-text/status/<task_id>", methods=["GET"])
    def review_text_status(folder_id, task_id):
        """Renvoie la progression d'une revérif texte async."""
        denied = _require_admin()
        if denied:
            return denied
        try:
            from services.script_rules_service import get_text_review_task
            task = get_text_review_task(task_id)
            if not task:
                return jsonify({"success": False, "error": "Tâche introuvable (worker redémarré ?)"}), 404
            return jsonify({"success": True, **task}), 200
        except Exception as e:
            logger.error(f"❌ Erreur status review text: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/content-job/rules/review-text/active", methods=["GET"])
    def review_text_active(folder_id):
        """Renvoie la dernière tâche de revérif texte connue pour ce dossier.

        Permet au frontend de reprendre l'affichage de progression à
        l'ouverture de la modale Script TTS (et donc de ne pas perdre le
        suivi si on l'a fermée pendant le run).
        """
        denied = _require_admin()
        if denied:
            return denied
        try:
            from services.script_rules_service import get_active_text_review_for_folder
            task = get_active_text_review_for_folder(folder_id)
            if not task:
                return jsonify({"success": True, "task": None}), 200
            return jsonify({"success": True, "task": task}), 200
        except Exception as e:
            logger.error(f"❌ Erreur active review text: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

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
                humanized = 0, humanization_error = NULL, humanization_signature = NULL,
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

    # ─── Pipeline playlist complète (19 fichiers) ─────────────────────────

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
        """Lance la génération des 19 fichiers MP3 de la playlist pour un dossier."""
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
            sync_slides = bool(req_body.get("sync_slides", False))
            auto_generate_slides = bool(req_body.get("auto_generate_slides", False))
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
            if "sync_slides" not in req_body:
                sync_slides = bool(has_script and not playlist_mock and force_all and voice_type in {"gtts", "fish_audio"})
            if "auto_generate_slides" not in req_body:
                auto_generate_slides = bool(sync_slides)

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
            is_course_audio = filename.startswith("cours_") and filename.endswith(".mp3")
            sync_slides = bool(req_body.get("sync_slides", is_course_audio)) and is_course_audio
            auto_generate_slides = bool(req_body.get("auto_generate_slides", sync_slides))
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
        """Retourne le script reformulé par Claude pour un dossier."""
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

            blob_path = f"platform-{platform_id}/folder-{folder_id}/playlist/script.json"
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
        """Liste les fichiers MP3 cours générés pour un dossier (dans audiostts)."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            folder = get_course_folder_identity(folder_id)
            if not folder:
                return jsonify({"success": False, "error": "Dossier introuvable"}), 404

            platform_id = int(folder["platform_id"])
            tts_conn = os.environ.get("AZURE_TTS_STORAGE_CONNECTION_STRING")
            if not tts_conn:
                return jsonify({"success": True, "audios": []}), 200

            prefix = f"platform-{platform_id}/folder-{folder_id}/playlist/"
            from azure.storage.blob import BlobServiceClient as _BSC
            bsc = _BSC.from_connection_string(tts_conn)
            cc = bsc.get_container_client("audiostts")

            audios = []
            for blob in cc.list_blobs(name_starts_with=prefix):
                name = blob.name.split("/")[-1]
                if name.endswith(".mp3"):
                    audios.append({
                        "filename": name,
                        "size_mb": round(blob.size / (1024 * 1024), 1),
                        "last_modified": blob.last_modified.strftime("%Y-%m-%d %H:%M") if blob.last_modified else None,
                    })

            return jsonify({"success": True, "audios": audios}), 200

        except Exception as e:
            logger.error(f"❌ Erreur get_generated_audios: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

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
            blob_path = _get_audio_blob_path(platform_id, folder_id, safe_filename)

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

    def _get_audio_blob_path(platform_id, folder_id, filename):
        return f"platform-{platform_id}/folder-{folder_id}/playlist/{filename}"

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
            platform_id = _get_platform_id_for_folder(folder_id)
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
            if filename.lower().startswith("cours_") and blob_size < 100_000:
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
            platform_id = _get_platform_id_for_folder(folder_id)
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

            uploaded = []
            failed = []
            for name in sorted(os.listdir(local_folder)):
                if not name.lower().startswith("cours_") or not name.lower().endswith(".mp3"):
                    continue
                full_path = os.path.join(local_folder, name)
                try:
                    with open(full_path, "rb") as f:
                        audio_bytes = f.read()
                    blob_path = _get_audio_blob_path(platform_id, folder_id, name)
                    upload_blob(CONTAINER_AUDIOS, blob_path, audio_bytes)
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
            blob_path = _get_audio_blob_path(platform_id, folder_id, target_filename)

            from services.azure_blob_service import upload_blob, CONTAINER_AUDIOS
            audio_bytes = file.read()
            upload_blob(CONTAINER_AUDIOS, blob_path, audio_bytes)

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
            blob_path = _get_audio_blob_path(platform_id, folder_id, filename)

            from services.azure_blob_service import download_blob, upload_blob, CONTAINER_AUDIOS
            from pydub import AudioSegment
            import io

            audio_bytes = download_blob(CONTAINER_AUDIOS, blob_path)
            audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")

            result = audio[:start_ms] + audio[end_ms:]

            buf = io.BytesIO()
            result.export(buf, format="mp3", bitrate="128k")
            result_bytes = buf.getvalue()

            upload_blob(CONTAINER_AUDIOS, blob_path, result_bytes)
            logger.info(f"✂️ Cut {filename}: [{start_ms}ms-{end_ms}ms] supprimé → {len(result_bytes)} bytes uploadé")

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
            blob_path = _get_audio_blob_path(platform_id, folder_id, filename)

            from services.azure_blob_service import download_blob, upload_blob, CONTAINER_AUDIOS
            from pydub import AudioSegment
            import io

            preview_bytes = _audio_previews.pop(preview_id)  # consommer le preview
            original_bytes = download_blob(CONTAINER_AUDIOS, blob_path)

            original = AudioSegment.from_file(io.BytesIO(original_bytes), format="mp3")
            new_segment = AudioSegment.from_file(io.BytesIO(preview_bytes), format="mp3")

            result = original[:start_ms] + new_segment + original[end_ms:]

            buf = io.BytesIO()
            result.export(buf, format="mp3", bitrate="128k")
            result_bytes = buf.getvalue()

            upload_blob(CONTAINER_AUDIOS, blob_path, result_bytes)
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
        Copie les 19 fichiers MP3 d'un dossier de cours vers le container audio de la plateforme.
        - priorité : fichiers générés du dossier depuis audiostts/platform-X/folder-Y/playlist/
        - fallback : Q&A + pauses statiques depuis audioqapause si manquants
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
            source_platform_id = folder_row[1]

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

            playlist_prefix = f"platform-{source_platform_id}/folder-{folder_id}/playlist/"

            # Lister tous les MP3 générés dans le dossier. Les pipelines récentes
            # produisent aussi les Q&A/pauses contextuels dans ce préfixe.
            playlist_blobs = [
                b for b in playlist_cc.list_blobs(name_starts_with=playlist_prefix)
                if b.name.endswith(".mp3")
            ]
            cours_blobs = [b for b in playlist_blobs if b.name.split("/")[-1].startswith("cours_")]

            if not cours_blobs:
                return jsonify({"success": False, "error": "Aucun fichier cours généré dans ce dossier. Lancez d'abord la pipeline."}), 404

            copied_files = []
            errors = []
            copied_names = set()
            archive_result = archive_public_platform_audios(
                platform_id,
                reason=f"fill-from-folder-{folder_id}",
            )

            # Copier les fichiers générés du dossier (cours + Q&A/pauses contextuels)
            for blob in playlist_blobs:
                filename = blob.name.split("/")[-1]
                try:
                    audio_bytes = playlist_cc.get_blob_client(blob.name).download_blob().readall()
                    dest_cc.get_blob_client(filename).upload_blob(audio_bytes, overwrite=True)
                    copied_files.append(filename)
                    copied_names.add(filename)
                    logger.info(f"   ✅ Playlist générée copiée : {filename}")
                except Exception as e:
                    logger.error(f"   ❌ Échec copie playlist {filename}: {e}")
                    errors.append({"filename": filename, "error": str(e)})

            # Fallback Q&A/pauses depuis audioqapause pour les fichiers non générés
            from services.audio_service import get_playlist
            expected_qa_pause = [
                os.path.basename((item["filename"] or "").split("?", 1)[0])
                for item in get_playlist(platform_id)
                if item.get("type") in ("qa", "pause", "pause_midi")
            ]

            for filename in expected_qa_pause:
                if filename in copied_names:
                    continue
                try:
                    audio_bytes = qa_pause_cc.get_blob_client(filename).download_blob().readall()
                    dest_cc.get_blob_client(filename).upload_blob(audio_bytes, overwrite=True)
                    copied_files.append(filename)
                    copied_names.add(filename)
                    logger.info(f"   ♻️ Q&A/Pause copié : {filename}")
                except Exception as e:
                    logger.error(f"   ❌ Échec copie Q&A/Pause {filename}: {e}")
                    errors.append({"filename": filename, "error": str(e)})

            logger.info(f"✅ fill-from-folder P{platform_id}/F{folder_id}: {len(copied_files)} fichiers copiés, {len(errors)} erreur(s)")

            return jsonify({
                "success": True,
                "copied": len(copied_files),
                "errors": len(errors),
                "files": copied_files,
                "error_details": errors,
                "folder_name": folder_row[0],
                "archive": archive_result,
            }), 200

        except Exception as e:
            logger.error(f"❌ Erreur fill_from_folder: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── Fonctions helpers background ───────────────────────────────────────
    def _process_document_background(document_id):
        """Traite un document en background: Azure PDF → TTS → Azure MP3"""
        try:
            from services.tts_service import process_document_to_audio
            from services.azure_blob_service import (
                download_blob, upload_blob, build_blob_path,
                CONTAINER_DOCUMENTS, CONTAINER_AUDIOS
            )
            from database.db import get_db_connection
            import uuid as uuid_mod

            conn = get_db_connection()
            cursor = conn.cursor()

            # Récupérer le document et son dossier
            cursor.execute("""
                SELECT cd.folder_id, cd.filename, cf.platform_id
                FROM cours_documents cd
                JOIN cours_folders cf ON cd.folder_id = cf.id
                WHERE cd.id = ?
            """, (document_id,))
            row = cursor.fetchone()
            if not row:
                cursor.execute("UPDATE cours_documents SET status = 'error' WHERE id = ?", (document_id,))
                conn.commit()
                conn.close()
                return

            folder_id, blob_path, platform_id = row

            # 1. Télécharger le PDF depuis Azure (en mémoire)
            pdf_bytes = download_blob(CONTAINER_DOCUMENTS, blob_path)

            # 2. Pipeline TTS: PDF bytes → MP3 bytes
            voice_id = os.getenv("FISH_AUDIO_VOICE_ID", "90a39a3f3c0a45c38502fa1d99dabf96")
            audio_bytes = process_document_to_audio(pdf_bytes, voice_id=voice_id)

            # 3. Upload l'audio vers Azure audiostts
            audio_name = f"{uuid_mod.uuid4()}.mp3"
            audio_blob_path = build_blob_path(platform_id, folder_id, audio_name)
            upload_blob(CONTAINER_AUDIOS, audio_blob_path, audio_bytes)

            # 4. Mettre à jour la DB
            cursor.execute(
                "UPDATE cours_documents SET status = 'done', audio_filename = ? WHERE id = ?",
                (audio_blob_path, document_id)
            )
            conn.commit()
            conn.close()

            logger.info(f"✅ Audio généré pour document {document_id}: {audio_blob_path}")

        except Exception as e:
            logger.error(f"❌ Erreur traitement document {document_id}: {e}")
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("UPDATE cours_documents SET status = 'error' WHERE id = ?", (document_id,))
                conn.commit()
                conn.close()
            except:
                pass

    def _process_folder_background(folder_id):
        """Traite tous les documents d'un dossier en background (séquentiel)"""
        try:
            from database.db import get_db_connection

            while True:
                conn = get_db_connection()
                cursor = conn.cursor()

                cursor.execute(f"""
                    SELECT id FROM cours_documents
                    WHERE folder_id = ? AND audio_filename IS NULL AND status != 'processing'
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
                    LIMIT 1
                """, (folder_id,))
                row = cursor.fetchone()
                if not row:
                    conn.close()
                    break

                document_id = row[0]
                cursor.execute("UPDATE cours_documents SET status = 'processing' WHERE id = ?", (document_id,))
                conn.commit()
                conn.close()

                _process_document_background(document_id)

                time.sleep(1)

        except Exception as e:
            logger.error(f"❌ Erreur traitement dossier {folder_id}: {e}")

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
