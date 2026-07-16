# admin_routes.py --- Routes d'administration (API JSON uniquement)
from flask import Blueprint, g, request, session, jsonify, send_file
from datetime import datetime, timedelta, timezone
import hmac
import os
import re
import secrets
import sqlite3
import string
import tempfile
import requests as http_requests
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.exceptions import ResourceExistsError
from pydub import AudioSegment
from werkzeug.security import check_password_hash, generate_password_hash
import state
from config import DATABASE_BACKEND, FRANCE_TZ, DB_PATH, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL
from database.db import get_db_connection
from database import db_safety
from database.postgres import postgres_enabled
from repositories.core_repository import (
    DuplicateTrainingCenterUsername,
    create_ai_teacher_order,  # compatibility symbol retained for legacy tests; POST returns 410
    create_training_center,
    get_training_center_by_username,
    list_ai_teacher_orders,
    update_training_center_password,
    upsert_student_profile_with_id,
)
from repositories.pipeline_repository import (
    hr_resource_belongs_to_center,
    list_course_folder_rows_for_platform,
)
from repositories.course_schedule_repository import schedule_store_is_postgres
from services.time_service import set_heure_debut_cours, get_heure_debut_cours
from services.export_service import generate_excel_export
from services.course_schedule_service import create_missing_course_schedule, get_course_schedule_summary, update_course_schedule
from utils.logger import get_logger
from utils.auth_tokens import issue_auth_token
from utils.slug import slugify, unique_slug

logger = get_logger(__name__)


_ADMIN_SUPERADMIN_ACCOUNT_TYPES = {"legacy_admin", "superadmin"}
_POSTGRES_ONLY_BACKENDS = {"postgres", "postgresql", "supabase"}


class AdminPlatformNotFound(LookupError):
    """Raised when an admin session cannot access a requested platform.

    The public response deliberately does not distinguish an unknown platform
    from a platform owned by another training centre.
    """


def _internal_admin_password_valid(password: str) -> bool:
    """Validate the legacy super-admin only against deployment secrets."""
    password_hash = os.getenv("INTERNAL_ADMIN_PASSWORD_HASH", "").strip()
    if password_hash:
        try:
            return bool(password and check_password_hash(password_hash, password))
        except (TypeError, ValueError):
            logger.error("INTERNAL_ADMIN_PASSWORD_HASH invalide")
            return False
    password_secret = os.getenv("INTERNAL_ADMIN_PASSWORD", "")
    return bool(password_secret and password and hmac.compare_digest(password_secret, password))


def _create_admin_token(account_type, account_id=None, center_name=None):
    payload = {
        "account_type": account_type,
        "account_id": account_id,
        "center_name": center_name,
    }
    return issue_auth_token("admin", payload)


def _generate_temporary_password(length=12):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _supabase_admin_headers():
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def _supabase_public_headers():
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
    }


def _is_supabase_duplicate_user(response):
    text = response.text.lower()
    return response.status_code in (400, 409, 422) and (
        "already" in text
        or "registered" in text
        or "exists" in text
        or "duplicate" in text
    )


def _ensure_training_center_supabase_user(email, password=None, center_name=None):
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return False, "Supabase Admin non configuré"

    auth_password = password if password and len(password) >= 6 else _generate_temporary_password()
    try:
        response = http_requests.post(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            headers=_supabase_admin_headers(),
            json={
                "email": email,
                "password": auth_password,
                "email_confirm": True,
                "user_metadata": {
                    "role": "training_center",
                    "center_name": center_name or "",
                },
            },
            timeout=15,
        )
        if response.status_code in (200, 201):
            return True, None
        if _is_supabase_duplicate_user(response):
            return True, None

        logger.warning("❌ Provisioning Supabase centre refusé: %s", response.text[:500])
        return False, "Création Supabase refusée"
    except Exception as exc:
        logger.warning("❌ Provisioning Supabase centre impossible", exc_info=True)
        return False, str(exc)


def _authenticate_training_center_with_supabase(email, password):
    if not SUPABASE_URL or not SUPABASE_ANON_KEY or not email or "@" not in email or not password:
        return False

    try:
        response = http_requests.post(
            f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
            headers=_supabase_public_headers(),
            json={"email": email, "password": password},
            timeout=15,
        )
        if response.status_code != 200:
            return False
        data = response.json()
        return bool(data.get("access_token") or data.get("session", {}).get("access_token"))
    except Exception:
        logger.warning("⚠️ Auth Supabase centre indisponible", exc_info=True)
        return False


def _update_training_center_password_sqlite(cursor, username, password_hash, password_debug_plaintext):
    cursor.execute(
        """
        UPDATE training_center_accounts
        SET password_hash = ?,
            password_debug_plaintext = ?,
            updated_at = ?
        WHERE username = ?
        """,
        (
            password_hash,
            None,
            datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            username,
        ),
    )
    return cursor.rowcount > 0


def _parse_platform_id(raw):
    """Parse a positive platform ID without accepting booleans or fallbacks."""
    if raw is None or isinstance(raw, bool):
        raise AdminPlatformNotFound()
    try:
        platform_id = int(raw)
    except (TypeError, ValueError):
        raise AdminPlatformNotFound() from None
    if platform_id <= 0 or str(raw).strip() != str(platform_id):
        raise AdminPlatformNotFound()
    return platform_id


def _training_center_account_id():
    raw = session.get("admin_account_id")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        account_id = int(raw)
    except (TypeError, ValueError):
        return None
    return account_id if account_id > 0 else None


def _authorize_platform_id(raw):
    """Return a platform ID only when the explicit admin role may access it."""
    platform_id = _parse_platform_id(raw)
    if not session.get("is_admin"):
        raise AdminPlatformNotFound()

    account_type = str(session.get("admin_account_type") or "").strip().lower()
    if account_type in _ADMIN_SUPERADMIN_ACCOUNT_TYPES:
        return platform_id
    if account_type != "training_center":
        raise AdminPlatformNotFound()

    center_account_id = _training_center_account_id()
    if center_account_id is None:
        raise AdminPlatformNotFound()

    # A route may resolve the same platform in before_request and in its body.
    # Cache only successful checks for the lifetime of this HTTP request.
    cache = getattr(g, "admin_platform_access", None)
    if cache is None:
        cache = set()
        g.admin_platform_access = cache
    cache_key = (platform_id, center_account_id)
    if cache_key in cache:
        return platform_id

    try:
        allowed = hr_resource_belongs_to_center(
            "platform",
            platform_id,
            center_account_id,
        )
    except Exception:
        logger.warning(
            "ADMIN_TENANT_SCOPE_LOOKUP_FAILED platform_id=%s center_account_id=%s",
            platform_id,
            center_account_id,
            exc_info=True,
        )
        allowed = False

    if not allowed:
        logger.warning(
            "ADMIN_TENANT_SCOPE_DENIED platform_id=%s center_account_id=%s",
            platform_id,
            center_account_id,
        )
        raise AdminPlatformNotFound()

    cache.add(cache_key)
    return platform_id


def _get_platform_id():
    """Resolve and authorize the request platform with no implicit fallback."""
    raw = request.headers.get("X-Platform-Id")
    if raw is not None:
        return _authorize_platform_id(raw)

    for key in ("platform_id", "p"):
        if key in request.args:
            return _authorize_platform_id(request.args.get(key))

    if request.is_json:
        body = request.get_json(silent=True) or {}
        for key in ("platform_id", "p"):
            if key in body:
                return _authorize_platform_id(body.get(key))

    if "platform_id" in session:
        return _authorize_platform_id(session.get("platform_id"))

    logger.warning("ADMIN_PLATFORM_ID_MISSING path=%s", request.path)
    raise AdminPlatformNotFound()


def _mirror_training_center_to_sqlite(cursor, account, password_hash, now_str, password_debug_plaintext=None):
    cursor.execute("SELECT id FROM training_center_accounts WHERE id = ?", (account["id"],))
    existing = cursor.fetchone()
    if existing:
        cursor.execute(
            """
            UPDATE training_center_accounts
            SET username = ?,
                password_hash = ?,
                password_debug_plaintext = ?,
                center_name = ?,
                slug = ?,
                is_active = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                account["username"],
                password_hash,
                None,
                account["center_name"],
                account["slug"],
                1 if account["is_active"] else 0,
                now_str,
                account["id"],
            ),
        )
        return

    cursor.execute(
        """
        INSERT INTO training_center_accounts
            (id, username, password_hash, password_debug_plaintext, center_name, slug, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account["id"],
            account["username"],
            password_hash,
            None,
            account["center_name"],
            account["slug"],
            1 if account["is_active"] else 0,
            now_str,
            now_str,
        ),
    )


def create_admin_blueprint(socketio):
    """Factory pour créer le blueprint admin avec accès à socketio"""
    admin_bp = Blueprint("admin", __name__)

    # Only browser-facing routes whose resource is selected through a
    # platform_id participate in this guard. Service-to-service `/api/internal`
    # routes authenticate with X-Platform-Key and intentionally remain a
    # separate trust boundary.
    platform_scoped_endpoints = {
        "get_logs",
        "get_course_time",
        "config_cours",
        "export_excel",
        "list_student_accounts",
        "create_student_account",
        "update_student_account",
        "simulate_current_time",
        "reset_simulation",
        "force_logout_finished_users",
    }

    def _platform_not_found_response():
        return jsonify({"success": False, "error": "Ressource introuvable"}), 404

    @admin_bp.errorhandler(AdminPlatformNotFound)
    def handle_admin_platform_not_found(_error):
        return _platform_not_found_response()

    @admin_bp.before_request
    def enforce_admin_platform_scope():
        # Preserve the existing authentication response for anonymous callers.
        if not session.get("is_admin"):
            return None

        endpoint = (request.endpoint or "").rsplit(".", 1)[-1]
        try:
            if endpoint in platform_scoped_endpoints:
                _get_platform_id()
            elif endpoint == "create_order":
                data = request.get_json(silent=True) or {}
                if "platform_id" in data and data.get("platform_id") is not None:
                    _authorize_platform_id(data.get("platform_id"))
        except AdminPlatformNotFound:
            return _platform_not_found_response()
        return None

    @admin_bp.route("/api/admin/session", methods=["GET"])
    def get_admin_session():
        """Retourne l'état de session admin sans lire de données métier."""
        if not session.get("is_admin"):
            return jsonify({"authenticated": False, "error": "Accès refusé"}), 403

        return jsonify({
            "authenticated": True,
            "account": {
                "type": session.get("admin_account_type", "legacy_admin"),
                "id": session.get("admin_account_id"),
                "center_name": session.get("center_name"),
            },
        }), 200

    @admin_bp.route("/api/admin/logs", methods=["GET"])
    def get_logs():
        """Récupère les logs avec filtrage optionnel par prénom"""
        try:
            if not session.get("is_admin"):
                logger.warning("⚠️ Tentative accès admin sans authentification")
                return jsonify({"authenticated": False, "error": "Accès refusé"}), 403

            platform_id = _get_platform_id()
            logger.info(f"👑 Accès admin logs P{platform_id}")
            prenom_recherche = request.args.get("prenom", "")

            if prenom_recherche:
                logger.debug(f"🔍 Recherche admin par prénom: {prenom_recherche}")

            # Récupération de l'heure actuelle du cours
            heure_debut_cours = get_heure_debut_cours(platform_id)

            conn = get_db_connection()
            cursor = conn.cursor()

            if prenom_recherche:
                cursor.execute(
                    "SELECT * FROM logs WHERE platform_id = ? AND prenom LIKE ?",
                    (platform_id, "%" + prenom_recherche + "%"),
                )
            else:
                cursor.execute("SELECT * FROM logs WHERE platform_id = ?", (platform_id,))

            logs = cursor.fetchall()
            conn.close()

            logger.debug(f"📊 {len(logs)} logs récupérés")

            total_seconds = 0
            logs_with_duration = []

            for log in logs:
                id_, nom, prenom, arrivee, depart = log[0], log[1], log[2], log[3], log[4]
                if depart:
                    dt_arrivee = datetime.strptime(arrivee, "%Y-%m-%d %H:%M:%S")
                    dt_depart = datetime.strptime(depart, "%Y-%m-%d %H:%M:%S")
                    duration = dt_depart - dt_arrivee
                    seconds = duration.total_seconds()
                    total_seconds += seconds

                    minutes = int(seconds // 60)
                    secondes_restantes = int(seconds % 60)
                    duree = f"{minutes} min {secondes_restantes} sec"
                else:
                    duree = "En cours..."

                logs_with_duration.append(
                    {
                        "id": id_,
                        "nom": nom,
                        "prenom": prenom,
                        "arrivee": arrivee,
                        "depart": depart,
                        "duree": duree,
                    }
                )

            # Calcul du temps total cumulé
            total_minutes = int(total_seconds // 60)
            total_heures = total_minutes // 60
            total_minutes_restant = total_minutes % 60
            total_secondes = int(total_seconds % 60)
            temps_total_format = (
                f"{total_heures} h {total_minutes_restant} min {total_secondes} sec"
            )

            return (
                jsonify(
                    {
                        "success": True,
                        "logs": logs_with_duration,
                        "prenom_recherche": prenom_recherche,
                        "temps_total": temps_total_format,
                        "heure_debut_cours": heure_debut_cours.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    }
                ),
                200,
            )

        except Exception as e:
            logger.error(f"❌ Erreur récupération logs admin: {e}")
            return jsonify({"success": False, "error": "Erreur serveur"}), 500

    @admin_bp.route("/api/admin/internal-dashboard", methods=["GET"])
    def internal_dashboard():
        """Vue interne SaaS : centres, comptes élèves et derniers logs.

        Réservé au legacy admin. Les mots de passe ne sont jamais exposés :
        seulement un statut indiquant qu'un secret hashé existe.
        """
        if not session.get("is_admin") or session.get("admin_account_type") != "legacy_admin":
            return jsonify({"success": False, "error": "Accès refusé"}), 403

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    pc.center_account_id,
                    COUNT(*) AS platform_count,
                    COALESCE(SUM((
                        SELECT COUNT(*)
                        FROM student_profiles sp
                        WHERE sp.platform_id = pc.id
                    )), 0) AS student_count,
                    COALESCE(SUM((
                        SELECT COUNT(*)
                        FROM logs l
                        WHERE l.platform_id = pc.id
                    )), 0) AS log_count
                FROM platform_config pc
                GROUP BY pc.center_account_id
            """)
            center_stats = {
                row[0]: {
                    "platform_count": int(row[1] or 0),
                    "student_count": int(row[2] or 0),
                    "log_count": int(row[3] or 0),
                }
                for row in cursor.fetchall()
            }

            centers = [{
                "id": None,
                "center_name": "Sales Hacking / Le Socrate interne",
                "slug": "le-socrate",
                "username": "admin",
                "email": "",
                "is_active": True,
                "created_at": "",
                "updated_at": "",
                "password_status": (
                    "Configuré par secret de déploiement"
                    if os.getenv("INTERNAL_ADMIN_PASSWORD_HASH") or os.getenv("INTERNAL_ADMIN_PASSWORD")
                    else "Non configuré"
                ),
                "internal": True,
                **center_stats.get(None, {"platform_count": 0, "student_count": 0, "log_count": 0}),
            }]

            cursor.execute("""
                SELECT id, username, center_name, slug, is_active, created_at, updated_at, password_hash, password_debug_plaintext
                FROM training_center_accounts
                ORDER BY created_at DESC, id DESC
            """)
            for row in cursor.fetchall():
                username = row[1] or ""
                stats = center_stats.get(row[0], {"platform_count": 0, "student_count": 0, "log_count": 0})
                centers.append({
                    "id": row[0],
                    "username": username,
                    "email": username if "@" in username else "",
                    "center_name": row[2],
                    "slug": row[3],
                    "is_active": bool(row[4]),
                    "created_at": row[5],
                    "updated_at": row[6],
                    "password_status": "Hashé, non récupérable" if row[7] else "Non défini",
                    "internal": False,
                    **stats,
                })

            cursor.execute("""
                SELECT
                    sp.id,
                    sp.email,
                    sp.nom,
                    sp.prenom,
                    sp.role,
                    sp.is_active,
                    sp.created_at,
                    sp.updated_at,
                    sp.platform_id,
                    pc.name AS platform_name,
                    COALESCE(tca.center_name, 'Sales Hacking / Le Socrate interne') AS center_name
                FROM student_profiles sp
                LEFT JOIN platform_config pc ON pc.id = sp.platform_id
                LEFT JOIN training_center_accounts tca ON tca.id = pc.center_account_id
                ORDER BY sp.created_at DESC, sp.id DESC
                LIMIT 100
            """)
            students = [{
                "id": row[0],
                "email": row[1],
                "username": row[1],
                "nom": row[2],
                "prenom": row[3],
                "role": row[4],
                "is_active": bool(row[5]),
                "created_at": row[6],
                "updated_at": row[7],
                "platform_id": row[8],
                "platform_name": row[9],
                "center_name": row[10],
                "password_status": "Mot de passe géré par Supabase Auth",
            } for row in cursor.fetchall()]

            cursor.execute("""
                SELECT
                    l.id,
                    l.nom,
                    l.prenom,
                    l.arrivee,
                    l.depart,
                    l.platform_id,
                    pc.name AS platform_name,
                    COALESCE(tca.center_name, 'Sales Hacking / Le Socrate interne') AS center_name
                FROM logs l
                LEFT JOIN platform_config pc ON pc.id = l.platform_id
                LEFT JOIN training_center_accounts tca ON tca.id = pc.center_account_id
                ORDER BY l.arrivee DESC, l.id DESC
                LIMIT 120
            """)
            recent_logs = []
            active_count = 0
            for row in cursor.fetchall():
                if not row[4]:
                    active_count += 1
                recent_logs.append({
                    "id": row[0],
                    "nom": row[1],
                    "prenom": row[2],
                    "arrivee": row[3],
                    "depart": row[4],
                    "platform_id": row[5],
                    "platform_name": row[6],
                    "center_name": row[7],
                    "status": "En cours" if not row[4] else "Terminé",
                })

            return jsonify({
                "success": True,
                "summary": {
                    "center_count": len(centers),
                    "external_center_count": max(len(centers) - 1, 0),
                    "student_count": len(students),
                    "recent_log_count": len(recent_logs),
                    "active_session_count": active_count,
                },
                "centers": centers,
                "students": students,
                "recent_logs": recent_logs,
            }), 200
        except Exception as e:
            logger.exception("❌ Erreur dashboard interne")
            return jsonify({"success": False, "error": "Erreur serveur"}), 500
        finally:
            if conn:
                conn.close()

    @admin_bp.route("/api/admin/course-time", methods=["GET"])
    def get_course_time():
        """Retourne l'heure de début du cours actuellement configurée"""
        try:
            if not session.get("is_admin"):
                return jsonify({"success": False, "error": "Accès refusé"}), 403
            platform_id = _get_platform_id()
            heure = get_heure_debut_cours(platform_id)
            return (
                jsonify(
                    {
                        "success": True,
                        "date_cours": heure.strftime("%Y-%m-%d"),
                        "heure_cours": heure.strftime("%H:%M"),
                    }
                ),
                200,
            )
        except Exception as e:
            logger.error(f"❌ Erreur récupération heure cours: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @admin_bp.route("/api/admin/config_cours", methods=["POST"])
    def config_cours():
        """Met à jour la configuration du cours (heure de début)"""
        try:
            if not session.get("is_admin"):
                logger.warning("⚠️ Tentative config cours sans authentification admin")
                return jsonify({"success": False, "error": "Accès refusé"}), 403

            logger.info("⚙️ Configuration cours demandée")

            data = request.get_json()
            date_str = data.get("date_cours", "").strip()
            heure_str = data.get("heure_cours", "").strip()

            logger.debug(f"⚙️ Données reçues - Date: {date_str}, Heure: {heure_str}")

            if not date_str or not heure_str:
                logger.warning("⚠️ Date ou heure manquante")
                return (
                    jsonify({"success": False, "error": "Date et heure requises"}),
                    400,
                )

            # Ajouter :00 pour les secondes seulement si elles ne sont pas déjà présentes
            if heure_str.count(":") == 1:
                datetime_str = f"{date_str} {heure_str}:00"
            else:
                datetime_str = f"{date_str} {heure_str}"

            nouvelle_heure_naive = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
            nouvelle_heure_fr = FRANCE_TZ.localize(nouvelle_heure_naive)

            platform_id = _get_platform_id()
            logger.info(f"⚙️ Nouvelle heure calculée P{platform_id}: {nouvelle_heure_fr}")

            # Sauvegarder en base
            set_heure_debut_cours(nouvelle_heure_fr, platform_id)

            return (
                jsonify(
                    {
                        "success": True,
                        "message": f"Heure de début mise à jour : {nouvelle_heure_fr.strftime('%d/%m/%Y à %H:%M')}",
                    }
                ),
                200,
            )

        except ValueError as e:
            logger.error(f"❌ Format date/heure invalide: {e}")
            return (
                jsonify({"success": False, "error": "Format de date/heure invalide"}),
                400,
            )
        except Exception as e:
            logger.error(f"❌ Erreur configuration cours: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── Endpoints internes service-to-service (P1 HR → P2) ──────────────

    @admin_bp.route("/api/internal/set-lock", methods=["POST"])
    def internal_set_lock():
        """Service-to-service : verrouiller/déverrouiller l'upload (appelé par P1 HR).

        Le body doit contenir {"locked": bool, "platform_id": int}. Sans platform_id,
        refus 400 — l'ancien fallback hardcodé WHERE id=1 produisait un bug symétrique
        à celui de course-time (écriture sur la mauvaise ligne côté backend distant).
        """
        api_key = os.environ.get("PLATFORM_API_KEY", "")
        if not api_key or request.headers.get("X-Platform-Key") != api_key:
            return jsonify({"success": False, "error": "Non autorisé"}), 401
        try:
            data = request.get_json() or {}
            locked = bool(data.get("locked", True))
            raw_pid = data.get("platform_id")
            if raw_pid is None:
                return jsonify({"success": False, "error": "platform_id requis"}), 400
            try:
                platform_id = int(raw_pid)
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "platform_id invalide"}), 400
            now = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE platform_config SET upload_locked = ?, updated_at = ? WHERE id = ?",
                (1 if locked else 0, now, platform_id),
            )
            conn.commit()
            conn.close()
            logger.info(
                f"🔒 Lock interne P{platform_id} mis à jour: {'verrouillé' if locked else 'déverrouillé'}"
            )
            return jsonify({"success": True, "upload_locked": locked, "platform_id": platform_id}), 200
        except Exception as e:
            logger.error(f"❌ Erreur internal set-lock: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @admin_bp.route("/api/internal/config-cours", methods=["POST"])
    def internal_config_cours():
        """Service-to-service : configurer l'heure du cours (appelé par P1 HR)"""
        api_key = os.environ.get("PLATFORM_API_KEY", "")
        if not api_key or request.headers.get("X-Platform-Key") != api_key:
            return jsonify({"success": False, "error": "Non autorisé"}), 401
        conn = None
        try:
            data = request.get_json(silent=True) or {}
            date_str = data.get("date_cours", "").strip()
            heure_str = data.get("heure_cours", "").strip()
            weekdays = data.get("weekdays") if "weekdays" in data else None
            allow_imminent = bool(data.get("force_schedule"))
            if not heure_str:
                return (
                    jsonify({"success": False, "error": "heure_cours requis"}),
                    400,
                )
            platform_id = int(data.get("platform_id", session.get("platform_id", 1)))
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
                logger.info(f"⚙️ Planning cours P{platform_id} configuré en interne")
                return (
                    jsonify(
                        {
                            "success": True,
                            "message": "Planning des journées mis à jour",
                            "schedule": schedule_update,
                        }
                    ),
                    200,
                )
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
                logger.info(f"⚙️ Planning cours P{platform_id} créé en interne")
                return (
                    jsonify(
                        {
                            "success": True,
                            "message": "Planning des journées créé",
                            "schedule": schedule_update,
                        }
                    ),
                    200,
                )
            if conn is not None:
                conn.close()
                conn = None

            if not date_str:
                return jsonify({"success": False, "error": "date_cours requis pour une plateforme sans planning automatique"}), 400
            if heure_str.count(":") == 1:
                datetime_str = f"{date_str} {heure_str}:00"
            else:
                datetime_str = f"{date_str} {heure_str}"
            nouvelle_heure_naive = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
            nouvelle_heure_fr = FRANCE_TZ.localize(nouvelle_heure_naive)
            set_heure_debut_cours(nouvelle_heure_fr, platform_id)
            logger.info(f"⚙️ Heure cours P{platform_id} configurée en interne: {nouvelle_heure_fr}")
            return (
                jsonify(
                    {
                        "success": True,
                        "message": f"Heure mise à jour : {nouvelle_heure_fr.strftime('%d/%m/%Y à %H:%M')}",
                    }
                ),
                200,
            )
        except ValueError as e:
            if conn:
                conn.close()
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            if conn:
                conn.close()
            logger.error(f"❌ Erreur internal config-cours: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @admin_bp.route("/api/internal/course-time", methods=["GET"])
    def internal_get_course_time():
        """Service-to-service : lire l'heure du cours (appelé par P1 HR Dashboard)"""
        api_key = os.environ.get("PLATFORM_API_KEY", "")
        if not api_key or request.headers.get("X-Platform-Key") != api_key:
            return jsonify({"success": False, "error": "Non autorisé"}), 401
        try:
            try:
                platform_id = int(request.args.get("platform_id", 1))
            except (TypeError, ValueError):
                platform_id = 1
            heure = get_heure_debut_cours(platform_id)
            conn = None if schedule_store_is_postgres() else get_db_connection()
            cursor = conn.cursor() if conn is not None else None
            schedule_summary = get_course_schedule_summary(cursor, platform_id)
            if conn is not None:
                conn.close()
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
            logger.error(f"❌ Erreur internal course-time: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @admin_bp.route("/api/admin/export_excel")
    def export_excel():
        """Export Excel des logs"""
        try:
            if not session.get("is_admin"):
                return jsonify({"success": False, "error": "Accès refusé"}), 403

            platform_id = _get_platform_id()
            logger.info(f"📊 Export Excel demandé P{platform_id}")
            prenom = request.args.get("prenom", "")

            conn = get_db_connection()
            cursor = conn.cursor()

            if prenom:
                cursor.execute(
                    "SELECT * FROM logs WHERE platform_id = ? AND prenom LIKE ?",
                    (platform_id, "%" + prenom + "%"),
                )
            else:
                cursor.execute("SELECT * FROM logs WHERE platform_id = ?", (platform_id,))

            rows = cursor.fetchall()
            conn.close()

            logger.debug(f"📊 {len(rows)} lignes à exporter")

            # Utiliser le service d'export
            tmp_file = generate_excel_export(rows)

            logger.info("✅ Export Excel généré avec succès")

            return send_file(
                tmp_file,
                as_attachment=True,
                download_name="historique.xlsx",
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        except Exception as e:
            logger.error(f"❌ Erreur export Excel: {e}")
            return jsonify({"success": False, "error": "Erreur lors de l'export"}), 500

    @admin_bp.route("/api/admin/login", methods=["POST"])
    def login_admin():
        """Connexion administrateur"""
        conn = None
        try:
            data = request.get_json(silent=True) or {}
            username = data.get("username", "").strip().lower()
            password = data.get("password", "").strip()

            if session.get("is_admin") and not username and not password:
                logger.info("👑 Admin déjà connecté")
                token = request.headers.get("X-Auth-Token") or _create_admin_token(
                    session.get("admin_account_type", "legacy_admin"),
                    session.get("admin_account_id"),
                    session.get("center_name"),
                )
                return jsonify({"success": True, "message": "Déjà connecté", "token": token}), 200

            logger.info(f"🔐 Tentative connexion admin: {username}")

            if username == "admin" and _internal_admin_password_valid(password):
                session["is_admin"] = True
                session["admin_account_type"] = "legacy_admin"
                session.permanent = True
                token = _create_admin_token("legacy_admin")
                logger.info("✅ Connexion admin réussie")
                return jsonify({
                    "success": True,
                    "message": "Connexion réussie",
                    "token": token,
                    "account": {
                        "type": "legacy_admin",
                        "username": "admin",
                        "center_name": "Sales Hacking / Le Socrate interne",
                    },
                }), 200

            if postgres_enabled():
                account = get_training_center_by_username(username)
                if account:
                    if not account["is_active"]:
                        logger.warning("⚠️ Compte centre Postgres désactivé: %s", username)
                        return jsonify({"success": False, "error": "Compte désactivé"}), 403

                    password_ok = bool(password and check_password_hash(account["password_hash"], password))
                    if not password_ok and _authenticate_training_center_with_supabase(username, password):
                        password_ok = True
                        new_hash = generate_password_hash(password)
                        update_training_center_password(username, new_hash, password)
                        try:
                            mirror_conn = get_db_connection()
                            mirror_cursor = mirror_conn.cursor()
                            _update_training_center_password_sqlite(mirror_cursor, username, new_hash, password)
                            mirror_conn.commit()
                            mirror_conn.close()
                        except Exception:
                            logger.warning("⚠️ Miroir SQLite mot de passe centre impossible", exc_info=True)

                    if not password_ok:
                        logger.warning("❌ Échec connexion centre Postgres - identifiants incorrects")
                        return jsonify({"success": False, "error": "Identifiants incorrects"}), 401

                    session["is_admin"] = True
                    session["admin_account_id"] = account["id"]
                    session["admin_account_type"] = "training_center"
                    session["center_name"] = account["center_name"]
                    session.permanent = True
                    token = _create_admin_token("training_center", account["id"], account["center_name"])
                    logger.info("✅ Connexion centre Postgres réussie: %s", username)
                    return (
                        jsonify(
                            {
                                "success": True,
                                "message": "Connexion réussie",
                                "token": token,
                                "account": {
                                    "type": "training_center",
                                    "id": account["id"],
                                    "username": account["username"],
                                    "center_name": account["center_name"],
                                    "slug": account["slug"],
                                },
                            }
                        ),
                        200,
                    )

                if DATABASE_BACKEND in _POSTGRES_ONLY_BACKENDS:
                    logger.warning("❌ Compte centre Postgres inconnu: %s", username)
                    return jsonify({"success": False, "error": "Identifiants incorrects"}), 401

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, username, password_hash, center_name, is_active, slug
                FROM training_center_accounts
                WHERE username = ?
                """,
                (username,),
            )
            account = cursor.fetchone() if username else None

            if not account:
                logger.warning("❌ Échec connexion admin - identifiants incorrects")
                return (
                    jsonify({"success": False, "error": "Identifiants incorrects"}),
                    401,
                )

            if not account[4]:
                logger.warning("⚠️ Compte centre désactivé: %s", username)
                return jsonify({"success": False, "error": "Compte désactivé"}), 403

            password_ok = bool(password and check_password_hash(account[2], password))
            if not password_ok and _authenticate_training_center_with_supabase(username, password):
                password_ok = True
                _update_training_center_password_sqlite(
                    cursor,
                    username,
                    generate_password_hash(password),
                    password,
                )
                conn.commit()

            if not password_ok:
                logger.warning("❌ Échec connexion admin - identifiants incorrects")
                return (
                    jsonify({"success": False, "error": "Identifiants incorrects"}),
                    401,
                )

            session["is_admin"] = True
            session["admin_account_id"] = account[0]
            session["admin_account_type"] = "training_center"
            session["center_name"] = account[3]
            session.permanent = True
            token = _create_admin_token("training_center", account[0], account[3])
            logger.info("✅ Connexion centre réussie: %s", username)
            return (
                jsonify(
                    {
                        "success": True,
                        "message": "Connexion réussie",
                        "token": token,
                        "account": {
                            "type": "training_center",
                            "id": account[0],
                            "username": account[1],
                            "center_name": account[3],
                            "slug": account[5],
                        },
                    }
                ),
                200,
            )

        except Exception as e:
            logger.error(f"❌ Erreur login admin: {e}")
            return jsonify({"success": False, "error": "Erreur serveur"}), 500
        finally:
            if conn:
                conn.close()

    @admin_bp.route("/api/admin/forgot-password", methods=["POST"])
    def forgot_training_center_password():
        """Prépare le compte centre pour le reset Supabase côté frontend."""
        conn = None
        try:
            data = request.get_json(silent=True) or {}
            username = str(data.get("username") or data.get("email") or "").strip().lower()
            if not username:
                return jsonify({"success": False, "error": "Adresse email requise"}), 400
            if username == "admin":
                return jsonify({
                    "success": False,
                    "error": "Le compte admin interne n'utilise pas la réinitialisation par email.",
                }), 400
            if "@" not in username:
                return jsonify({
                    "success": False,
                    "error": "Entrez l'adresse email utilisée comme identifiant.",
                }), 400

            account = get_training_center_by_username(username) if postgres_enabled() else None
            if account:
                ensured, ensure_error = _ensure_training_center_supabase_user(
                    username,
                    None,
                    account.get("center_name"),
                )
                if not ensured:
                    return jsonify({"success": False, "error": ensure_error}), 503

                logger.info("✅ Compte centre Postgres prêt pour reset Supabase: %s", username)
                return jsonify({
                    "success": True,
                    "message": "Un email de réinitialisation va être envoyé.",
                }), 200

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, password_hash, password_debug_plaintext
                FROM training_center_accounts
                WHERE username = ?
                """,
                (username,),
            )
            row = cursor.fetchone()
            if not row:
                return jsonify({
                    "success": True,
                    "message": "Si un compte existe pour cette adresse, un email va être envoyé.",
                }), 200

            ensured, ensure_error = _ensure_training_center_supabase_user(username, None)
            if not ensured:
                return jsonify({"success": False, "error": ensure_error}), 503

            logger.info("✅ Compte centre SQLite prêt pour reset Supabase: %s", username)
            return jsonify({
                "success": True,
                "message": "Un email de réinitialisation va être envoyé.",
            }), 200
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error("❌ Erreur reset mot de passe centre: %s", e)
            return jsonify({"success": False, "error": "Erreur serveur"}), 500
        finally:
            if conn:
                conn.close()

    @admin_bp.route("/api/admin/register", methods=["POST"])
    def register_admin():
        """Inscription centre de formation"""
        conn = None
        try:
            data = request.get_json(silent=True) or {}
            username = data.get("username", "").strip().lower()
            password = data.get("password", "").strip()
            center_name = data.get("center_name", "").strip()

            if not username or not password or not center_name:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Nom du centre, identifiant et mot de passe requis",
                        }
                    ),
                    400,
                )
            if len(password) < 8:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Le mot de passe doit contenir au moins 8 caractères",
                        }
                    ),
                    400,
                )

            now_str = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
            password_hash = generate_password_hash(password)

            if postgres_enabled():
                try:
                    account = create_training_center(
                        username=username,
                        password_hash=password_hash,
                        password_debug_plaintext=None,
                        center_name=center_name,
                        slug_base=center_name or username,
                        now=now_str,
                    )
                except DuplicateTrainingCenterUsername:
                    return jsonify({"success": False, "error": "Cet identifiant existe déjà"}), 409

                conn = get_db_connection()
                cursor = conn.cursor()
                _mirror_training_center_to_sqlite(cursor, account, password_hash, now_str, None)
                conn.commit()

                if "@" in username:
                    ensured, ensure_error = _ensure_training_center_supabase_user(
                        username,
                        password,
                        center_name,
                    )
                    if not ensured:
                        logger.warning("⚠️ Compte centre créé sans provisioning Supabase: %s", ensure_error)

                session["is_admin"] = True
                session["admin_account_id"] = account["id"]
                session["admin_account_type"] = "training_center"
                session["center_name"] = account["center_name"]
                session.permanent = True
                token = _create_admin_token("training_center", account["id"], account["center_name"])

                logger.info("✅ Inscription centre Postgres réussie: %s", username)
                return (
                    jsonify(
                        {
                            "success": True,
                            "message": "Compte créé",
                            "token": token,
                            "account": {
                                "type": "training_center",
                                "id": account["id"],
                                "username": account["username"],
                                "center_name": account["center_name"],
                                "slug": account["slug"],
                            },
                        }
                    ),
                    201,
                )

            conn = get_db_connection()
            cursor = conn.cursor()
            center_slug = unique_slug(
                cursor,
                "training_center_accounts",
                slugify(center_name or username, fallback="centre"),
            )
            cursor.execute(
                """
                INSERT INTO training_center_accounts
                    (username, password_hash, password_debug_plaintext, center_name, slug, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    username,
                    password_hash,
                    None,
                    center_name,
                    center_slug,
                    now_str,
                    now_str,
                ),
            )
            account_id = cursor.lastrowid
            conn.commit()

            if "@" in username:
                ensured, ensure_error = _ensure_training_center_supabase_user(
                    username,
                    password,
                    center_name,
                )
                if not ensured:
                    logger.warning("⚠️ Compte centre créé sans provisioning Supabase: %s", ensure_error)

            session["is_admin"] = True
            session["admin_account_id"] = account_id
            session["admin_account_type"] = "training_center"
            session["center_name"] = center_name
            session.permanent = True
            token = _create_admin_token("training_center", account_id, center_name)

            logger.info("✅ Inscription centre réussie: %s", username)
            return (
                jsonify(
                    {
                        "success": True,
                        "message": "Compte créé",
                        "token": token,
                        "account": {
                            "type": "training_center",
                            "id": account_id,
                            "username": username,
                            "center_name": center_name,
                            "slug": center_slug,
                        },
                    }
                ),
                201,
            )
        except sqlite3.IntegrityError:
            if conn:
                conn.rollback()
            logger.warning("❌ Inscription centre refusée, identifiant déjà utilisé")
            return jsonify({"success": False, "error": "Cet identifiant existe déjà"}), 409
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"❌ Erreur inscription centre: {e}")
            return jsonify({"success": False, "error": "Erreur serveur"}), 500
        finally:
            if conn:
                conn.close()

    @admin_bp.route("/api/admin/ai-teacher-orders", methods=["GET"])
    def list_orders():
        """Liste les commandes d'agents IA du centre connecté."""
        if not session.get("is_admin") or session.get("admin_account_type") != "training_center":
            return jsonify({"success": False, "error": "Accès refusé"}), 403
        if not postgres_enabled():
            return jsonify({"success": False, "error": "Postgres non activé"}), 503

        try:
            orders = list_ai_teacher_orders(session.get("admin_account_id"))
            return jsonify({"success": True, "orders": orders}), 200
        except Exception:
            logger.exception("❌ Erreur lecture commandes IA")
            return jsonify({"success": False, "error": "Erreur serveur"}), 500

    @admin_bp.route("/api/admin/ai-teacher-orders", methods=["POST"])
    def create_order():
        """Retiré: le navigateur ne peut plus fournir lui-même un prix."""
        return jsonify({
            "success": False,
            "error": "Utilisez /api/hr/teacher-orders pour une commande tarifée côté serveur.",
        }), 410

    @admin_bp.route("/api/admin/logout", methods=["POST"])
    def logout_admin():
        """Déconnexion administrateur"""
        try:
            logger.info("👑 Déconnexion admin")
            session.pop("is_admin", None)
            session.pop("admin_account_id", None)
            session.pop("admin_account_type", None)
            session.pop("center_name", None)
            token = request.headers.get("X-Auth-Token")
            if token and hasattr(state, "admin_tokens"):
                state.admin_tokens.pop(token, None)
            return jsonify({"success": True, "message": "Déconnexion réussie"}), 200
        except Exception as e:
            logger.error(f"❌ Erreur logout admin: {e}")
            return jsonify({"success": False, "error": "Erreur serveur"}), 500

    def _require_admin():
        if not session.get("is_admin"):
            return jsonify({"success": False, "error": "Accès admin requis"}), 401
        return None

    @admin_bp.route("/api/admin/student-accounts", methods=["GET"])
    def list_student_accounts():
        denied = _require_admin()
        if denied:
            return denied
        platform_id = _get_platform_id()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, email, nom, prenom, is_active, created_at, updated_at
            FROM student_profiles
            WHERE platform_id = ?
            ORDER BY prenom COLLATE NOCASE, nom COLLATE NOCASE, email COLLATE NOCASE
            """,
            (platform_id,),
        )
        accounts = [
            {
                "id": row[0],
                "username": row[1],
                "email": row[1],
                "nom": row[2],
                "prenom": row[3],
                "is_active": bool(row[4]),
                "created_at": row[5],
                "updated_at": row[6],
            }
            for row in cursor.fetchall()
        ]
        conn.close()
        return jsonify({"success": True, "accounts": accounts}), 200

    @admin_bp.route("/api/admin/student-accounts", methods=["POST"])
    def create_student_account():
        denied = _require_admin()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        platform_id = _get_platform_id()
        email = str(data.get("email") or data.get("username") or "").strip().lower()
        password = str(data.get("password", ""))
        nom = str(data.get("nom", "")).strip()
        prenom = str(data.get("prenom", "")).strip()
        if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
            return jsonify({"success": False, "error": "Supabase Admin non configuré"}), 500
        if not email or not password or not nom or not prenom:
            return jsonify({"success": False, "error": "Email, mot de passe, nom et prénom requis"}), 400
        if len(password) < 8:
            return jsonify({"success": False, "error": "Le mot de passe doit contenir au moins 8 caractères"}), 400
        supabase_resp = http_requests.post(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {
                    "nom": nom,
                    "prenom": prenom,
                    "platform_id": platform_id,
                    "role": "student",
                },
            },
            timeout=15,
        )
        if supabase_resp.status_code not in (200, 201):
            logger.warning("❌ Création utilisateur Supabase refusée: %s", supabase_resp.text[:500])
            return jsonify({"success": False, "error": "Création Supabase refusée"}), 400
        supabase_user = supabase_resp.json()
        auth_user_id = supabase_user.get("id")
        if not auth_user_id:
            return jsonify({"success": False, "error": "Réponse Supabase invalide"}), 500
        now = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO student_profiles
                    (auth_user_id, platform_id, email, nom, prenom, role, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'student', 1, ?, ?)
                """,
                (auth_user_id, platform_id, email, nom, prenom, now, now),
            )
            profile_id = cursor.lastrowid
            conn.commit()
        except Exception as exc:
            conn.rollback()
            if "UNIQUE" in str(exc).upper():
                return jsonify({"success": False, "error": "Cet email existe déjà"}), 409
            logger.error(f"❌ Erreur création compte élève: {exc}")
            return jsonify({"success": False, "error": "Erreur serveur"}), 500
        finally:
            conn.close()

        postgres_synced = False
        if postgres_enabled():
            try:
                upsert_student_profile_with_id({
                    "id": profile_id,
                    "auth_user_id": auth_user_id,
                    "platform_id": platform_id,
                    "email": email,
                    "nom": nom,
                    "prenom": prenom,
                    "role": "student",
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                })
                postgres_synced = True
            except Exception:
                logger.warning("⚠️ Miroir Postgres profil élève impossible", exc_info=True)

        return jsonify({
            "success": True,
            "message": "Compte élève créé",
            "postgres_synced": postgres_synced,
        }), 201

    @admin_bp.route("/api/admin/student-accounts/<int:account_id>", methods=["PUT"])
    def update_student_account(account_id):
        denied = _require_admin()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        platform_id = _get_platform_id()
        updates = []
        params = []
        password_changed = False
        for field in ("nom", "prenom"):
            if field in data:
                value = str(data.get(field) or "").strip()
                if not value:
                    return jsonify({"success": False, "error": "Nom et prénom ne peuvent pas être vides"}), 400
                updates.append(f"{field} = ?")
                params.append(value)
        if "password" in data and data.get("password"):
            password = str(data.get("password"))
            if len(password) < 8:
                return jsonify({"success": False, "error": "Le mot de passe doit contenir au moins 8 caractères"}), 400
            if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
                return jsonify({"success": False, "error": "Supabase Admin non configuré"}), 500
            conn_lookup = get_db_connection()
            cursor_lookup = conn_lookup.cursor()
            cursor_lookup.execute(
                "SELECT auth_user_id FROM student_profiles WHERE id = ? AND platform_id = ?",
                (account_id, platform_id),
            )
            row = cursor_lookup.fetchone()
            conn_lookup.close()
            if not row:
                return jsonify({"success": False, "error": "Compte introuvable"}), 404
            supabase_resp = http_requests.put(
                f"{SUPABASE_URL}/auth/v1/admin/users/{row[0]}",
                headers={
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                },
                json={"password": password},
                timeout=15,
            )
            if supabase_resp.status_code not in (200, 204):
                logger.warning("❌ Reset password Supabase refusé: %s", supabase_resp.text[:500])
                return jsonify({"success": False, "error": "Mise à jour Supabase refusée"}), 400
            password_changed = True
        if "is_active" in data:
            updates.append("is_active = ?")
            params.append(1 if data.get("is_active") else 0)
        if not updates and not password_changed:
            return jsonify({"success": False, "error": "Aucune modification fournie"}), 400
        updates.append("updated_at = ?")
        params.append(datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S"))
        params.extend([account_id, platform_id])
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE student_profiles SET {', '.join(updates)} WHERE id = ? AND platform_id = ?",
            params,
        )
        conn.commit()
        changed = cursor.rowcount
        profile_row = None
        if changed:
            cursor.execute(
                """
                SELECT id, auth_user_id, platform_id, email, nom, prenom, role, is_active, created_at, updated_at
                FROM student_profiles
                WHERE id = ? AND platform_id = ?
                """,
                (account_id, platform_id),
            )
            profile_row = cursor.fetchone()
        conn.close()
        if not changed:
            return jsonify({"success": False, "error": "Compte introuvable"}), 404

        postgres_synced = False
        if postgres_enabled() and profile_row:
            try:
                upsert_student_profile_with_id({
                    "id": profile_row[0],
                    "auth_user_id": profile_row[1],
                    "platform_id": profile_row[2],
                    "email": profile_row[3],
                    "nom": profile_row[4],
                    "prenom": profile_row[5],
                    "role": profile_row[6],
                    "is_active": bool(profile_row[7]),
                    "created_at": profile_row[8],
                    "updated_at": profile_row[9],
                })
                postgres_synced = True
            except Exception:
                logger.warning("⚠️ Synchronisation Postgres profil élève impossible", exc_info=True)

        return jsonify({
            "success": True,
            "message": "Compte élève mis à jour",
            "postgres_synced": postgres_synced,
        }), 200

    @admin_bp.route("/api/admin/db/status", methods=["GET"])
    def db_status():
        """Santé de la base : intégrité, backups, mode maintenance, notices."""
        denied = _require_admin()
        if denied:
            return denied
        ok, detail = db_safety.check_integrity()
        size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
        return jsonify({
            "integrity_ok": ok,
            "integrity_detail": detail,
            "db_path": DB_PATH,
            "db_size_bytes": size,
            "health": db_safety.db_health,
            "backups": db_safety.list_backups(),
        })

    @admin_bp.route("/api/admin/db/backup", methods=["POST"])
    def db_backup():
        """Déclenche un backup manuel immédiat."""
        denied = _require_admin()
        if denied:
            return denied
        try:
            path = db_safety.create_backup(label="manual")
            return jsonify({"success": True, "backup": os.path.basename(path) if path else None})
        except Exception as e:
            logger.error(f"❌ Backup manuel en échec: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @admin_bp.route("/api/admin/db/restore", methods=["POST"])
    def db_restore():
        """Restaure un backup nommé (body JSON: {"backup": "<nom>"}).

        L'intégrité du backup est vérifiée avant remplacement, et la base
        courante est sauvegardée en 'pre-restore' — opération réversible.
        """
        denied = _require_admin()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        backup_name = (data.get("backup") or "").strip()
        if not backup_name:
            return jsonify({"success": False, "error": "Paramètre 'backup' requis"}), 400
        if db_safety.restore_backup(backup_name):
            from database.db import init_database
            init_database()  # ré-appliquer les migrations sur la base restaurée
            db_safety.set_maintenance(False)
            return jsonify({"success": True, "restored": backup_name})
        return jsonify({"success": False, "error": "Backup introuvable ou corrompu"}), 400

    @admin_bp.route("/api/admin/db/maintenance", methods=["POST"])
    def db_maintenance():
        """Active/désactive le mode maintenance (body JSON: {"enabled": bool})."""
        denied = _require_admin()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        enabled = bool(data.get("enabled"))
        reason = (data.get("reason") or "activé manuellement") if enabled else None
        db_safety.set_maintenance(enabled, reason)
        return jsonify({"success": True, "maintenance": enabled})

    @admin_bp.route("/api/admin/simulate-current-time", methods=["POST"])
    def simulate_current_time():
        """Simule l'heure actuelle pour le debug"""
        try:
            if not session.get("is_admin"):
                logger.warning("⚠️ Tentative simulation temps sans auth admin")
                return jsonify({"success": False, "error": "Accès refusé"}), 403

            logger.info("⏰ Simulation temps demandée")

            data = request.get_json()
            simulated_time_str = data.get("simulated_current_time", "").strip()

            if not simulated_time_str:
                return jsonify({"success": False, "error": "Heure manquante"}), 400

            try:
                simulated_time_naive = datetime.strptime(
                    simulated_time_str, "%Y-%m-%dT%H:%M:%S"
                )
            except ValueError:
                try:
                    simulated_time_naive = datetime.strptime(
                        simulated_time_str, "%Y-%m-%dT%H:%M"
                    )
                except ValueError:
                    return (
                        jsonify({"success": False, "error": "Format date invalide"}),
                        400,
                    )

            platform_id = _get_platform_id()
            offset_fr = FRANCE_TZ.localize(simulated_time_naive)
            state.simulated_time_offsets[platform_id] = offset_fr

            logger.info(f"✅ Heure simulée P{platform_id}: {offset_fr}")

            return (
                jsonify(
                    {
                        "success": True,
                        "message": f"Heure simulée: {offset_fr.strftime('%Y-%m-%d %H:%M:%S')}",
                    }
                ),
                200,
            )

        except Exception as e:
            logger.error(f"❌ Erreur simulation temps: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @admin_bp.route("/api/admin/reset-simulation", methods=["POST"])
    def reset_simulation():
        """Remet l'heure réelle"""
        try:
            if not session.get("is_admin"):
                return jsonify({"success": False, "error": "Accès refusé"}), 403

            platform_id = _get_platform_id()
            logger.info(f"⏰ Reset simulation demandé P{platform_id}")
            state.simulated_time_offsets.pop(platform_id, None)
            logger.info(f"✅ Simulation désactivée P{platform_id}")

            return jsonify({"success": True, "message": "Heure réelle restaurée"}), 200

        except Exception as e:
            logger.error(f"❌ Erreur reset simulation: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @admin_bp.route("/api/admin/force-logout-finished-users", methods=["POST"])
    def force_logout_finished_users():
        """Force la déconnexion de tous les utilisateurs"""
        try:
            if not session.get("is_admin"):
                return jsonify({"success": False, "error": "Accès refusé"}), 403

            platform_id = _get_platform_id()
            logger.info(f"🔒 Forçage déconnexion utilisateurs P{platform_id}")

            conn = get_db_connection()
            cursor = conn.cursor()
            depart_time = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "UPDATE logs SET depart = ? WHERE platform_id = ? AND (depart IS NULL OR depart = '')",
                (depart_time, platform_id),
            )
            affected_rows = cursor.rowcount
            conn.commit()
            conn.close()

            # Signal uniquement aux clients de la plateforme concernée
            socketio.emit(
                "force_logout",
                {
                    "message": "Formation terminée - Déconnexion automatique",
                    "redirect_url": "/logout",
                },
                room=f"platform_{platform_id}",
            )

            logger.info(f"✅ {affected_rows} utilisateurs déconnectés P{platform_id}")

            return (
                jsonify(
                    {
                        "success": True,
                        "message": f"{affected_rows} utilisateurs déconnectés",
                        "disconnected_count": affected_rows,
                    }
                ),
                200,
            )

        except Exception as e:
            logger.error(f"❌ Erreur force logout: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @admin_bp.route("/api/admin/upload-pdf", methods=["POST"])
    def upload_pdf():
        """Upload un PDF dans Azure Blob Storage et déclenche l'indexer"""
        try:
            if not session.get("is_admin"):
                return jsonify({"success": False, "error": "Accès refusé"}), 403

            if "file" not in request.files:
                return jsonify({"success": False, "error": "Aucun fichier envoyé"}), 400

            file = request.files["file"]
            if not file.filename or not file.filename.lower().endswith(".pdf"):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Seuls les fichiers PDF sont acceptés",
                        }
                    ),
                    400,
                )

            logger.info(f"📄 Upload PDF: {file.filename}")

            # Connexion Azure Blob Storage
            connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
            container_name = os.environ.get("AZURE_STORAGE_CONTAINER", "formationpdf")

            if not connection_string:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Configuration Azure Storage manquante",
                        }
                    ),
                    500,
                )

            blob_service_client = BlobServiceClient.from_connection_string(
                connection_string
            )
            container_client = blob_service_client.get_container_client(container_name)

            # Supprimer tous les anciens blobs
            logger.info("🗑️ Suppression des anciens PDFs...")
            for blob in container_client.list_blobs():
                container_client.delete_blob(blob.name)
                logger.debug(f"  Supprimé: {blob.name}")

            # Upload du nouveau PDF
            blob_client = container_client.get_blob_client(file.filename)
            blob_client.upload_blob(file.stream, overwrite=True, content_settings=None)
            logger.info(f"✅ PDF uploadé: {file.filename}")

            # Réinitialiser puis relancer l'indexer Azure AI Search
            # Le reset purge le tracking des anciens documents supprimés du container
            search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
            search_api_key = os.environ.get("AZURE_SEARCH_API_KEY")
            indexer_name = os.environ.get(
                "AZURE_SEARCH_INDEXER_NAME", "rag-1770824229421-indexer"
            )
            index_name = os.environ.get("AZURE_SEARCH_INDEX_NAME", "rag-1770824229421")

            if search_endpoint and search_api_key:
                headers = {
                    "Content-Type": "application/json",
                    "api-key": search_api_key,
                }

                # 1. Vider l'index existant (supprimer tous les documents)
                search_url = f"{search_endpoint}/indexes/{index_name}/docs/search?api-version=2024-07-01"
                search_resp = http_requests.post(
                    search_url,
                    headers=headers,
                    json={"search": "*", "select": "chunk_id", "top": 1000},
                )
                if search_resp.status_code == 200:
                    docs = search_resp.json().get("value", [])
                    if docs:
                        delete_actions = [
                            {"@search.action": "delete", "chunk_id": doc["chunk_id"]}
                            for doc in docs
                        ]
                        delete_url = f"{search_endpoint}/indexes/{index_name}/docs/index?api-version=2024-07-01"
                        del_resp = http_requests.post(
                            delete_url, headers=headers, json={"value": delete_actions}
                        )
                        if del_resp.status_code in (200, 207):
                            logger.info(
                                f"🗑️ {len(delete_actions)} documents supprimés de l'index"
                            )
                        else:
                            logger.warning(
                                f"⚠️ Suppression index: {del_resp.status_code} - {del_resp.text}"
                            )

                # 2. Reset l'indexer (purge son tracking interne)
                reset_url = f"{search_endpoint}/indexers/{indexer_name}/reset?api-version=2024-07-01"
                reset_resp = http_requests.post(reset_url, headers=headers)
                if reset_resp.status_code in (204, 200):
                    logger.info("🔄 Indexer réinitialisé")
                else:
                    logger.warning(
                        f"⚠️ Reset indexer: {reset_resp.status_code} - {reset_resp.text}"
                    )

                # 3. Relancer l'indexer (ne verra que le nouveau PDF)
                indexer_url = f"{search_endpoint}/indexers/{indexer_name}/run?api-version=2024-07-01"
                resp = http_requests.post(indexer_url, headers=headers)
                if resp.status_code in (202, 204):
                    logger.info("✅ Indexer déclenché avec succès")
                else:
                    logger.warning(
                        f"⚠️ Indexer réponse: {resp.status_code} - {resp.text}"
                    )

            return (
                jsonify(
                    {
                        "success": True,
                        "message": f"PDF '{file.filename}' uploadé, indexation lancée",
                    }
                ),
                200,
            )

        except Exception as e:
            logger.error(f"❌ Erreur upload PDF: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @admin_bp.route("/api/admin/indexer-status", methods=["GET"])
    def indexer_status():
        """Vérifie le statut de l'indexer Azure AI Search"""
        try:
            if not session.get("is_admin"):
                return jsonify({"success": False, "error": "Accès refusé"}), 403

            search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
            search_api_key = os.environ.get("AZURE_SEARCH_API_KEY")
            indexer_name = os.environ.get(
                "AZURE_SEARCH_INDEXER_NAME", "rag-1770824229421-indexer"
            )

            if not search_endpoint or not search_api_key:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Configuration Azure Search manquante",
                        }
                    ),
                    500,
                )

            status_url = f"{search_endpoint}/indexers/{indexer_name}/status?api-version=2024-07-01"
            headers = {
                "Content-Type": "application/json",
                "api-key": search_api_key,
            }
            resp = http_requests.get(status_url, headers=headers)

            if resp.status_code != 200:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Erreur API Azure: {resp.status_code}",
                        }
                    ),
                    500,
                )

            data = resp.json()
            last_result = data.get("lastResult", {})
            status = last_result.get("status", "unknown")

            status_messages = {
                "inProgress": "Indexation en cours...",
                "success": "Indexation terminée !",
                "transientFailure": "Erreur temporaire lors de l'indexation",
                "persistentFailure": "Erreur persistante lors de l'indexation",
                "reset": "Indexer réinitialisé",
            }

            return (
                jsonify(
                    {
                        "success": True,
                        "status": status,
                        "message": status_messages.get(status, f"Statut: {status}"),
                    }
                ),
                200,
            )

        except Exception as e:
            logger.error(f"❌ Erreur statut indexer: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    def clean_audio_filename(filename):
        """Nettoie un nom de fichier audio selon le format attendu par la playlist.

        Cas 1 — Nom contient le pattern playlist (type_HHhMM_HHhMM) :
          ex: pause_17h15_17h25-_1_.wav → pause_17h15_17h25.mp3
          ex: cours_9h00_9h45 (2).wav  → cours_9h00_9h45.mp3
          Types reconnus : cours, qa, pause, pause_midi

        Cas 2 — Nom générique :
          - espaces → _, points multiples → un seul, caractères spéciaux supprimés
        """
        name, _ext = os.path.splitext(filename)
        name = name.strip()

        # Cas 1 : extraire le pattern playlist (séparateurs _ ou - tolérés partout)
        # Ex: pause_17h15_17h25, pause-17h15_17h25, cours_9h00-9h45, etc.
        playlist_pattern = re.search(
            r"(cours|qa|pause_midi|pause)[_-](\d{1,2}h\d{2})[_-](\d{1,2}h\d{2})",
            name,
            re.IGNORECASE,
        )
        if playlist_pattern:
            type_part = playlist_pattern.group(1).lower()
            start_time = playlist_pattern.group(2).lower()
            end_time = playlist_pattern.group(3).lower()
            return f"{type_part}_{start_time}_{end_time}.mp3"

        # Cas 2 : nettoyage générique
        name = re.sub(r"\s+", "_", name)
        name = re.sub(r"\.{2,}", ".", name)
        name = re.sub(r"[^\w.\-]", "", name)
        name = name.strip(".")
        if not name:
            name = "audio"
        return f"{name}.mp3"

    @admin_bp.route("/api/admin/upload-audios", methods=["POST"])
    def upload_audios():
        """Upload multi-audios : sauvegarde les fichiers puis lance le traitement en arrière-plan"""
        try:
            # Refuser si un job est déjà en cours
            if state.audio_upload_job["status"] in ("saving", "processing"):
                return (
                    jsonify({"success": False, "error": "Un upload est déjà en cours"}),
                    409,
                )

            files = request.files.getlist("files")
            if not files or len(files) == 0:
                return jsonify({"success": False, "error": "Aucun fichier envoyé"}), 400

            logger.info(f"🎵 Upload audios: {len(files)} fichier(s) reçu(s)")

            connection_string = os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING")
            if not connection_string:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Configuration AZURE_AUDIO_STORAGE_CONNECTION_STRING manquante",
                        }
                    ),
                    500,
                )

            AUDIO_EXTENSIONS = {
                ".mp3",
                ".wav",
                ".ogg",
                ".m4a",
                ".flac",
                ".aac",
                ".wma",
                ".webm",
            }

            # Phase 1 : sauvegarder les fichiers dans /tmp immédiatement
            state.reset_audio_upload_job()
            state.audio_upload_job["status"] = "saving"
            state.audio_upload_job["message"] = "Réception des fichiers..."

            saved_files = []  # (original_name, cleaned_name, ext, tmp_path)
            skipped_report = []

            for file in files:
                if not file.filename:
                    continue

                _name, ext = os.path.splitext(file.filename.lower())
                if ext not in AUDIO_EXTENSIONS:
                    skipped_report.append(
                        {
                            "original": file.filename,
                            "cleaned": None,
                            "converted": False,
                            "skipped": True,
                            "reason": f"Format non supporté ({ext})",
                        }
                    )
                    continue

                cleaned_name = clean_audio_filename(file.filename)
                tmp_input = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                file.save(tmp_input.name)
                tmp_input.close()
                saved_files.append((file.filename, cleaned_name, ext, tmp_input.name))

            if not saved_files:
                state.reset_audio_upload_job()
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Aucun fichier audio valide à uploader",
                            "report": skipped_report,
                        }
                    ),
                    400,
                )

            state.audio_upload_job["total"] = len(saved_files)
            state.audio_upload_job["files_status"] = {
                cleaned_name: "pending" for _, cleaned_name, _, _ in saved_files
            }
            state.audio_upload_job["message"] = (
                f"{len(saved_files)} fichier(s) sauvegardé(s), traitement lancé..."
            )

            # Phase 2 : lancer le traitement en arrière-plan
            container_name = os.environ.get(
                "AZURE_AUDIO_CONTAINER", "formationaudio-dev"
            )
            socketio.start_background_task(
                _process_audio_upload,
                saved_files,
                skipped_report,
                connection_string,
                container_name,
            )

            return (
                jsonify(
                    {
                        "success": True,
                        "job_status": "saving",
                        "message": f"{len(saved_files)} fichier(s) en cours de traitement",
                    }
                ),
                202,
            )

        except Exception as e:
            logger.error(f"❌ Erreur upload audios: {e}")
            state.audio_upload_job["status"] = "error"
            state.audio_upload_job["message"] = str(e)
            return jsonify({"success": False, "error": str(e)}), 500

    def _process_audio_upload(
        saved_files, skipped_report, connection_string, container_name
    ):
        """Tâche de fond : conversion MP3 + upload Azure (parallèle via eventlet)"""
        import eventlet

        report = list(skipped_report)

        try:
            state.audio_upload_job["status"] = "processing"

            # Connexion Azure (une seule fois)
            blob_service_client = BlobServiceClient.from_connection_string(
                connection_string
            )
            container_client = blob_service_client.get_container_client(container_name)

            try:
                container_client.create_container()
                logger.info(f"📦 Conteneur {container_name} créé")
            except ResourceExistsError:
                pass

            completed_count = [0]
            file_reports = []

            def process_single_file(file_info):
                original_name, cleaned_name, ext, tmp_path = file_info

                try:
                    # Phase 1 : Conversion
                    state.audio_upload_job["files_status"][cleaned_name] = "converting"
                    needs_conversion = ext != ".mp3"

                    if needs_conversion:
                        logger.info(f"  🔄 Conversion {original_name} ({ext} → .mp3)")
                        audio_seg = AudioSegment.from_file(tmp_path)
                        tmp_output = tempfile.NamedTemporaryFile(
                            delete=False, suffix=".mp3"
                        )
                        audio_seg.export(tmp_output.name, format="mp3")
                        tmp_output.close()
                        upload_path = tmp_output.name
                        os.unlink(tmp_path)
                    else:
                        upload_path = tmp_path

                    # Phase 2 : Upload Azure
                    state.audio_upload_job["files_status"][cleaned_name] = "uploading"
                    blob_client = container_client.get_blob_client(cleaned_name)
                    with open(upload_path, "rb") as f:
                        blob_client.upload_blob(f, overwrite=True)
                    logger.info(f"  ✅ Uploadé: {cleaned_name}")

                    try:
                        os.unlink(upload_path)
                    except OSError:
                        pass

                    # Terminé
                    state.audio_upload_job["files_status"][cleaned_name] = "done"
                    completed_count[0] += 1
                    state.audio_upload_job["progress"] = completed_count[0]
                    state.audio_upload_job["current_file"] = cleaned_name
                    state.audio_upload_job["message"] = (
                        f"{completed_count[0]}/{len(saved_files)} fichier(s) traité(s)"
                    )

                    file_reports.append(
                        {
                            "original": original_name,
                            "cleaned": cleaned_name,
                            "converted": needs_conversion,
                            "skipped": False,
                        }
                    )

                except Exception as e:
                    logger.error(f"  ❌ Erreur {original_name}: {e}")
                    state.audio_upload_job["files_status"][cleaned_name] = "error"
                    err_msg = str(e)
                    if (
                        "Invalid data" in err_msg
                        or "Decoding failed" in err_msg
                        or "Error opening input" in err_msg
                    ):
                        friendly_reason = "Fichier audio corrompu ou format non lisible"
                    elif "No such file" in err_msg:
                        friendly_reason = "Fichier introuvable"
                    elif "codec" in err_msg.lower():
                        friendly_reason = "Codec audio non supporté"
                    else:
                        friendly_reason = "Erreur de conversion"
                    file_reports.append(
                        {
                            "original": original_name,
                            "cleaned": None,
                            "converted": False,
                            "skipped": True,
                            "reason": friendly_reason,
                        }
                    )
                    completed_count[0] += 1
                    state.audio_upload_job["progress"] = completed_count[0]
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

            # Traitement parallèle (max 4 fichiers simultanés)
            pool = eventlet.GreenPool(size=4)
            for _ in pool.imap(process_single_file, saved_files):
                pass

            report.extend(file_reports)
            uploaded_count = sum(
                1
                for s in state.audio_upload_job["files_status"].values()
                if s == "done"
            )
            logger.info(
                f"✅ {uploaded_count} fichier(s) audio uploadé(s) dans {container_name}"
            )

            state.audio_upload_job["status"] = "completed"
            state.audio_upload_job["message"] = (
                f"{uploaded_count} fichier(s) uploadé(s) dans {container_name}"
            )
            state.audio_upload_job["report"] = report

        except Exception as e:
            logger.error(f"❌ Erreur traitement audio en arrière-plan: {e}")
            state.audio_upload_job["status"] = "error"
            state.audio_upload_job["message"] = str(e)
            state.audio_upload_job["report"] = report
            for _, _, _, tmp_path in saved_files:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    @admin_bp.route("/api/admin/audio-upload-status", methods=["GET"])
    def audio_upload_status():
        """Retourne le statut du job d'upload audio en arrière-plan"""
        try:
            return jsonify({"success": True, **state.audio_upload_job}), 200

        except Exception as e:
            logger.error(f"❌ Erreur statut upload audio: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @admin_bp.route("/api/admin/audios/<path:filename>", methods=["DELETE"])
    def delete_audio(filename):
        """Supprime un audio individuel du conteneur Azure"""
        try:
            connection_string = os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING")
            if not connection_string:
                return (
                    jsonify(
                        {"success": False, "error": "Configuration Azure manquante"}
                    ),
                    500,
                )

            container_name = os.environ.get(
                "AZURE_AUDIO_CONTAINER", "formationaudio-dev"
            )
            blob_service_client = BlobServiceClient.from_connection_string(
                connection_string
            )
            container_client = blob_service_client.get_container_client(container_name)
            container_client.delete_blob(filename)

            logger.info(f"🗑️ Audio supprimé par intervenant : {filename}")
            return jsonify({"success": True, "message": f"'{filename}' supprimé"}), 200

        except Exception as e:
            logger.error(f"❌ Erreur suppression audio: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @admin_bp.route("/api/admin/audio-list", methods=["GET"])
    def audio_list():
        """Liste les fichiers audio présents dans le conteneur Azure avec URLs SAS"""
        try:
            if not session.get("is_admin"):
                return jsonify({"success": False, "error": "Accès refusé"}), 403

            connection_string = os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING")
            if not connection_string:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Configuration AZURE_AUDIO_STORAGE_CONNECTION_STRING manquante",
                        }
                    ),
                    500,
                )

            container_name = os.environ.get(
                "AZURE_AUDIO_CONTAINER", "formationaudio-dev"
            )
            blob_service_client = BlobServiceClient.from_connection_string(
                connection_string
            )
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
                audios.append(
                    {
                        "name": blob.name,
                        "size": blob.size,
                        "url": url,
                    }
                )

            return jsonify({"success": True, "audios": audios}), 200

        except Exception as e:
            logger.error(f"❌ Erreur liste audio: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    return admin_bp
