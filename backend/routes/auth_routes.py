# auth_routes.py -- Routes d'authentification et connexion utilisateur (API JSON)
import hmac
import os
from flask import Blueprint, request, session, jsonify
from datetime import datetime, timedelta
import requests
from werkzeug.security import check_password_hash
from config import (
    DATABASE_BACKEND,
    FRANCE_TZ,
    STUDENT_AUTH_LEGACY_FALLBACK,
    SUPABASE_ANON_KEY,
    SUPABASE_URL,
)
from database.db import get_db_connection
from database.postgres import postgres_enabled
from repositories.core_repository import (
    close_open_logs,
    count_student_accounts,
    create_log,
    get_student_account,
    get_student_profile,
    record_attendance_heartbeat,
    update_log_depart,
    upsert_log,
    upsert_student_profile,
)
from repositories.course_schedule_repository import (
    get_audio_generation_session,
    list_course_session_credentials_for_window,
)
from utils.logger import get_logger
from utils.auth_tokens import (
    issue_auth_token,
    verify_course_invitation_token,
)
import state

logger = get_logger(__name__)

POSTGRES_ONLY_BACKENDS = {"postgres", "postgresql", "supabase"}


def _postgres_only_runtime():
    """Whether student auth must never consult the local SQLite database."""
    return DATABASE_BACKEND in POSTGRES_ONLY_BACKENDS


def _create_student_session(
    cursor,
    nom,
    prenom,
    platform_id,
    *,
    course_session_id=None,
    recipient_hash=None,
):
    session["nom"] = nom
    session["prenom"] = prenom
    session["platform_id"] = platform_id
    if course_session_id is not None:
        course_session_id = int(course_session_id)
        session["course_session_id"] = course_session_id
    else:
        session.pop("course_session_id", None)
    if recipient_hash:
        session["recipient_hash"] = str(recipient_hash)
    else:
        session.pop("recipient_hash", None)
    arrivee_time = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
    session["arrivee"] = arrivee_time

    log_row = {
        "platform_id": platform_id,
        "course_session_id": course_session_id,
        "recipient_hash": str(recipient_hash) if recipient_hash else None,
        "nom": nom,
        "prenom": prenom,
        "arrivee": arrivee_time,
        "depart": None,
    }
    if _postgres_only_runtime():
        log_id = create_log(log_row)
    else:
        if cursor is None:
            raise RuntimeError("Curseur SQLite manquant pour le mode de compatibilité.")
        cursor.execute(
            "INSERT INTO logs (nom, prenom, arrivee, platform_id) VALUES (?, ?, ?, ?)",
            (nom, prenom, arrivee_time, platform_id),
        )
        log_id = cursor.lastrowid
    session["log_id"] = log_id

    token_payload = {
        "nom": nom,
        "prenom": prenom,
        "log_id": log_id,
        "platform_id": platform_id,
    }
    if course_session_id is not None:
        token_payload["course_session_id"] = course_session_id
    if recipient_hash:
        token_payload["recipient_hash"] = str(recipient_hash)
    token = issue_auth_token("student", token_payload)
    if not _postgres_only_runtime() and postgres_enabled():
        try:
            upsert_log({"id": log_id, **log_row})
        except Exception:
            logger.warning("⚠️ Miroir Postgres du log élève impossible", exc_info=True)
    return log_id, token


def _get_supabase_user(access_token):
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError("Supabase Auth non configuré")
    response = requests.get(
        f"{SUPABASE_URL}/auth/v1/user",
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {access_token}",
        },
        timeout=10,
    )
    if response.status_code != 200:
        return None
    return response.json()


def _course_session_access_window():
    now = datetime.now(FRANCE_TZ)
    try:
        early_hours = max(
            1.0,
            min(8784.0, float(os.environ.get("COURSE_SESSION_PASSWORD_EARLY_HOURS", "8784"))),
        )
    except (TypeError, ValueError):
        early_hours = 8784.0
    try:
        active_hours = max(1.0, float(os.environ.get("COURSE_SESSION_ACTIVE_HOURS", "12")))
    except (TypeError, ValueError):
        active_hours = 12.0
    return now, now - timedelta(hours=active_hours), now + timedelta(hours=early_hours)


def _resolve_course_session_by_code(cursor, platform_id, password):
    """Resolve a secret to exactly one occurrence instead of platform-wide access."""
    supplied = str(password or "").strip()
    if not supplied:
        return None

    _now, lower_bound, upper_bound = _course_session_access_window()

    if _postgres_only_runtime():
        # Do not swallow a Postgres outage and silently grant legacy access.
        credentials = list_course_session_credentials_for_window(
            platform_id,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
        )
    else:
        try:
            from services.course_schedule_service import ensure_course_schedule_tables

            ensure_course_schedule_tables(cursor)
            credentials = list_course_session_credentials_for_window(
                platform_id,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
                sqlite_cursor=cursor,
            )
        except Exception:
            logger.warning("⚠️ Vérification mot de passe séance impossible", exc_info=True)
            return None

    matches = [
        row
        for row in credentials
        if row.get("session_password")
        and hmac.compare_digest(supplied, str(row["session_password"]))
    ]
    if len(matches) != 1:
        if len(matches) > 1:
            logger.error(
                "COURSE_SESSION_CODE_COLLISION platform_id=%s matching_sessions=%s",
                platform_id,
                [row.get("id") for row in matches],
            )
        return None
    return matches[0]


def _course_session_code_valid(cursor, platform_id, password):
    """Backward-compatible boolean wrapper around occurrence resolution."""
    return _resolve_course_session_by_code(cursor, platform_id, password) is not None


def _course_session_password_valid(cursor, platform_id, password):
    """Compatibility password check, used only when legacy access is enabled."""
    supplied = str(password or "").strip()
    if not supplied:
        return False
    if _course_session_code_valid(cursor, platform_id, supplied):
        return True

    expected = os.environ.get("COURSE_SESSION_PASSWORD", "").strip()
    if expected:
        return hmac.compare_digest(supplied, expected)
    return STUDENT_AUTH_LEGACY_FALLBACK


def _as_france_datetime(value):
    if isinstance(value, datetime):
        return FRANCE_TZ.localize(value) if value.tzinfo is None else value.astimezone(FRANCE_TZ)
    parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
    return FRANCE_TZ.localize(parsed) if parsed.tzinfo is None else parsed.astimezone(FRANCE_TZ)


def _resolve_course_invitation(platform_id, token):
    payload = verify_course_invitation_token(str(token or "").strip())
    if not payload or int(payload["platform_id"]) != int(platform_id):
        return None
    now = datetime.now(FRANCE_TZ)
    if now.timestamp() > int(payload["exp"]):
        return None
    course_session = get_audio_generation_session(platform_id, int(payload["session_id"]))
    if not course_session or course_session.get("status") not in {"planned", "active"}:
        return None
    scheduled_at = _as_france_datetime(course_session.get("scheduled_at"))
    if int(scheduled_at.timestamp()) != int(payload["scheduled_at"]):
        # A report invalidates links containing the former occurrence time.
        return None
    try:
        active_hours = max(1.0, float(os.environ.get("COURSE_SESSION_ACTIVE_HOURS", "12")))
    except (TypeError, ValueError):
        active_hours = 12.0
    if now > scheduled_at + timedelta(hours=active_hours):
        return None
    return {
        **course_session,
        "invitation_recipient_hash": payload["recipient"],
    }


def _course_invitation_valid(platform_id, token):
    """Backward-compatible boolean wrapper around occurrence resolution."""
    return _resolve_course_invitation(platform_id, token) is not None


def _resolve_requested_course_session(platform_id, raw_session_id):
    """Bind an already authenticated platform account to an explicit occurrence."""
    if raw_session_id in (None, "") or isinstance(raw_session_id, bool):
        return None
    try:
        session_id = int(raw_session_id)
    except (TypeError, ValueError):
        return None
    if session_id <= 0:
        return None
    row = get_audio_generation_session(int(platform_id), session_id)
    if not row or int(row.get("platform_id") or 0) != int(platform_id):
        return None
    if str(row.get("status") or "").lower() not in {"planned", "active"}:
        return None
    return row


def _close_student_log(log_id, depart):
    if _postgres_only_runtime():
        return update_log_depart(log_id, depart)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE logs SET depart=? WHERE id=?", (depart, log_id))
        conn.commit()
        updated = cursor.rowcount > 0
    finally:
        conn.close()

    if postgres_enabled():
        try:
            update_log_depart(log_id, depart)
        except Exception:
            logger.warning("⚠️ Miroir Postgres du départ impossible", exc_info=True)
    return updated


def _close_all_student_logs(depart):
    if _postgres_only_runtime():
        return close_open_logs(depart)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE logs SET depart=? WHERE depart IS NULL OR depart = ''",
            (depart,),
        )
        disconnected = cursor.rowcount
        conn.commit()
    finally:
        conn.close()

    if postgres_enabled():
        try:
            close_open_logs(depart)
        except Exception:
            logger.warning("⚠️ Miroir Postgres des départs automatiques impossible", exc_info=True)
    return disconnected


def create_auth_blueprint(socketio):
    """Factory pour créer le blueprint auth avec accès à socketio"""
    auth_bp = Blueprint("auth", __name__)

    @auth_bp.route("/api/auth/supabase-config", methods=["GET"])
    def supabase_config():
        """Expose la configuration publique Supabase nécessaire au frontend."""
        if not SUPABASE_URL or not SUPABASE_ANON_KEY:
            return jsonify({"success": False, "error": "Supabase Auth non configuré"}), 503
        return jsonify({
            "success": True,
            "url": SUPABASE_URL,
            "anon_key": SUPABASE_ANON_KEY,
        }), 200

    @auth_bp.route("/api/auth/login", methods=["POST"])
    def login():
        conn = None
        try:
            data = request.get_json(silent=True) or {}
            username = str(data.get("username") or "").strip().lower()
            password = str(data.get("password") or "")
            invitation_token = str(data.get("invitation_token") or "").strip()
            requested_course_session_id = data.get("course_session_id")
            nom = str(data.get("nom") or "").strip()
            prenom = str(data.get("prenom") or "").strip()
            try:
                platform_id = int(data.get("platform_id", 1))
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "Plateforme invalide"}), 400

            logger.info(f"👤 Tentative connexion élève: {username or nom} (P{platform_id})")

            invitation_access = False
            authenticated_course_session = None
            if invitation_token:
                if not nom or not prenom:
                    return jsonify({"success": False, "error": "Nom et prénom requis"}), 400
                authenticated_course_session = _resolve_course_invitation(
                    platform_id,
                    invitation_token,
                )
                if not authenticated_course_session:
                    logger.warning("❌ Invitation de cours invalide ou expirée sur P%s", platform_id)
                    return jsonify({"success": False, "error": "Lien d'invitation invalide ou expiré"}), 401
                invitation_access = True

            postgres_only = _postgres_only_runtime()
            cursor = None
            account = None
            pg_account = None
            if postgres_only:
                if username:
                    pg_account = get_student_account(platform_id, username)
            else:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, username, password_hash, nom, prenom, is_active
                    FROM student_accounts
                    WHERE platform_id = ? AND username = ?
                    """,
                    (platform_id, username),
                )
                account = cursor.fetchone() if username else None
                if postgres_enabled() and username:
                    try:
                        pg_account = get_student_account(platform_id, username)
                    except Exception:
                        logger.warning("⚠️ Lecture compte élève Postgres impossible", exc_info=True)

            if invitation_access:
                logger.info("✅ Invitation signée acceptée sur P%s", platform_id)
            elif pg_account:
                if not pg_account["is_active"]:
                    logger.warning("⚠️ Compte élève Postgres désactivé: %s P%s", username, platform_id)
                    return jsonify({"success": False, "error": "Compte désactivé"}), 403
                if not password or not check_password_hash(pg_account["password_hash"], password):
                    logger.warning("❌ Échec connexion élève Postgres: %s P%s", username, platform_id)
                    return jsonify({"success": False, "error": "Identifiants incorrects"}), 401
                nom = pg_account["nom"]
                prenom = pg_account["prenom"]
            elif account:
                if not account[5]:
                    logger.warning("⚠️ Compte élève désactivé: %s P%s", username, platform_id)
                    return jsonify({"success": False, "error": "Compte désactivé"}), 403
                if not password or not check_password_hash(account[2], password):
                    logger.warning("❌ Échec connexion élève: %s P%s", username, platform_id)
                    return jsonify({"success": False, "error": "Identifiants incorrects"}), 401
                nom = account[3]
                prenom = account[4]
            else:
                if nom and prenom:
                    authenticated_course_session = _resolve_course_session_by_code(
                        cursor,
                        platform_id,
                        password,
                    )
                session_code_access = bool(authenticated_course_session)
                if session_code_access:
                    logger.info(
                        "✅ Code de séance accepté sur P%s occurrence=%s",
                        platform_id,
                        authenticated_course_session.get("id"),
                    )
                else:
                    if postgres_only:
                        has_accounts = count_student_accounts(platform_id) > 0
                    else:
                        cursor.execute(
                            "SELECT COUNT(*) FROM student_accounts WHERE platform_id = ?",
                            (platform_id,),
                        )
                        has_accounts = cursor.fetchone()[0] > 0
                    if not postgres_only and postgres_enabled():
                        try:
                            has_accounts = has_accounts or count_student_accounts(platform_id) > 0
                        except Exception:
                            logger.warning("⚠️ Comptage comptes élèves Postgres impossible", exc_info=True)
                    if has_accounts or not STUDENT_AUTH_LEGACY_FALLBACK:
                        logger.warning("❌ Compte élève inconnu: %s P%s", username, platform_id)
                        return jsonify({"success": False, "error": "Identifiants incorrects"}), 401
                    if not nom or not prenom:
                        logger.warning("⚠️ Identifiants élève manquants")
                        return jsonify({"success": False, "error": "Identifiant et mot de passe requis"}), 400
                    if not _course_session_password_valid(cursor, platform_id, password):
                        logger.warning("❌ Mot de passe session invalide: %s %s P%s", prenom, nom, platform_id)
                        return jsonify({"success": False, "error": "Mot de passe incorrect"}), 401
                    logger.warning(
                        "⚠️ Connexion élève legacy nom/prénom acceptée sur P%s car aucun compte n'existe",
                        platform_id,
                    )

            if authenticated_course_session is None and requested_course_session_id not in (None, ""):
                authenticated_course_session = _resolve_requested_course_session(
                    platform_id,
                    requested_course_session_id,
                )
                if authenticated_course_session is None:
                    return jsonify({"success": False, "error": "Séance non autorisée"}), 403

            course_session_id = (
                int(authenticated_course_session["id"])
                if authenticated_course_session and authenticated_course_session.get("id") is not None
                else None
            )
            recipient_hash = (
                authenticated_course_session.get("invitation_recipient_hash")
                if authenticated_course_session
                else None
            )
            log_id, token = _create_student_session(
                cursor,
                nom,
                prenom,
                platform_id,
                course_session_id=course_session_id,
                recipient_hash=recipient_hash,
            )
            if conn is not None:
                conn.commit()

            logger.info(f"✅ Utilisateur enregistré en base avec ID: {log_id}")

            return (
                jsonify(
                    {
                        "success": True,
                        "user": {"nom": nom, "prenom": prenom},
                        "log_id": log_id,
                        "course_session_id": course_session_id,
                        "token": token,
                    }
                ),
                200,
            )

        except Exception as e:
            logger.error(f"❌ Erreur connexion utilisateur: {e}")
            return (
                jsonify({"success": False, "error": "Erreur lors de la connexion"}),
                500,
            )
        finally:
            if conn:
                conn.close()

    @auth_bp.route("/api/auth/supabase-session", methods=["POST"])
    def supabase_session():
        conn = None
        try:
            data = request.get_json(silent=True) or {}
            access_token = str(data.get("access_token") or "").strip()
            requested_course_session_id = data.get("course_session_id")
            try:
                requested_platform_id = int(data.get("platform_id", 1))
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "Plateforme invalide"}), 400
            if not access_token:
                return jsonify({"success": False, "error": "Token Supabase requis"}), 400

            supabase_user = _get_supabase_user(access_token)
            if not supabase_user:
                return jsonify({"success": False, "error": "Session Supabase invalide"}), 401

            auth_user_id = supabase_user.get("id")
            email = supabase_user.get("email") or ""
            postgres_only = _postgres_only_runtime()
            pg_profile = None
            cursor = None
            if postgres_only:
                pg_profile = get_student_profile(auth_user_id)
            elif postgres_enabled():
                try:
                    pg_profile = get_student_profile(auth_user_id)
                except Exception:
                    logger.warning("⚠️ Lecture profil élève Postgres impossible", exc_info=True)

            if not postgres_only:
                conn = get_db_connection()
                cursor = conn.cursor()
            if pg_profile:
                profile = (
                    pg_profile["nom"],
                    pg_profile["prenom"],
                    pg_profile["platform_id"],
                    pg_profile["is_active"],
                    pg_profile["role"],
                )
            elif cursor is not None:
                cursor.execute(
                    """
                    SELECT nom, prenom, platform_id, is_active, role
                    FROM student_profiles
                    WHERE auth_user_id = ?
                    """,
                    (auth_user_id,),
                )
                profile = cursor.fetchone()
            else:
                profile = None

            if not profile:
                # Supabase ``user_metadata`` is editable by the authenticated
                # user and must never grant a tenant/platform membership. The
                # server-side student_profiles row is provisioned by admins and
                # remains the sole authorization source.
                logger.warning(
                    "⚠️ Session Supabase refusée: profil serveur absent pour auth_user_id=%s",
                    auth_user_id,
                )
                return jsonify({"success": False, "error": "Profil élève introuvable"}), 403
            else:
                nom, prenom, platform_id, is_active, role = profile
                if not is_active:
                    return jsonify({"success": False, "error": "Compte désactivé"}), 403
                if int(platform_id) != requested_platform_id:
                    return jsonify({"success": False, "error": "Compte non autorisé sur cette plateforme"}), 403
                if not postgres_only and postgres_enabled() and not pg_profile:
                    try:
                        now = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
                        upsert_student_profile({
                            "auth_user_id": auth_user_id,
                            "platform_id": int(platform_id),
                            "email": email,
                            "nom": nom,
                            "prenom": prenom,
                            "role": role or "student",
                            "is_active": bool(is_active),
                            "created_at": now,
                            "updated_at": now,
                        })
                    except Exception:
                        logger.warning("⚠️ Synchronisation profil élève Postgres impossible", exc_info=True)

            authenticated_course_session = _resolve_requested_course_session(
                int(platform_id),
                requested_course_session_id,
            )
            if requested_course_session_id not in (None, "") and authenticated_course_session is None:
                return jsonify({"success": False, "error": "Séance non autorisée"}), 403
            course_session_id = (
                int(authenticated_course_session["id"])
                if authenticated_course_session
                else None
            )
            log_id, token = _create_student_session(
                cursor,
                nom,
                prenom,
                int(platform_id),
                course_session_id=course_session_id,
            )
            if conn is not None:
                conn.commit()
            logger.info("✅ Session Supabase reliée au log %s pour %s P%s", log_id, email, platform_id)
            return jsonify({
                "success": True,
                "user": {"nom": nom, "prenom": prenom, "email": email},
                "log_id": log_id,
                "course_session_id": course_session_id,
                "token": token,
            }), 200
        except Exception as e:
            logger.exception("❌ Erreur session Supabase")
            return jsonify({"success": False, "error": "Erreur lors de la connexion"}), 500
        finally:
            if conn:
                conn.close()

    @auth_bp.route("/api/auth/logout", methods=["POST"])
    def logout():
        try:
            nom = session.get("nom", "Inconnu")
            prenom = session.get("prenom", "")
            logger.info(f"👋 Déconnexion {nom} {prenom}")

            if "log_id" in session:
                # Départ en heure française
                depart = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
                _close_student_log(session["log_id"], depart)
                logger.info(f"✅ Départ enregistré: {depart}")

            token = request.headers.get("X-Auth-Token")
            if token:
                state.user_tokens.pop(token, None)

            session.clear()
            return jsonify({"success": True, "message": "Déconnexion réussie"}), 200

        except Exception as e:
            logger.error(f"❌ Erreur déconnexion: {e}")
            session.clear()
            return (
                jsonify({"success": False, "error": "Erreur lors de la déconnexion"}),
                500,
            )

    @auth_bp.route("/api/auth/heartbeat", methods=["POST"])
    def attendance_heartbeat():
        """Record actual room presence independently from the login form."""
        try:
            log_id = session.get("log_id")
            if not log_id or not session.get("nom"):
                return jsonify({"success": False, "error": "Session élève requise"}), 401
            observed_at = datetime.now(FRANCE_TZ)
            heartbeat = record_attendance_heartbeat(log_id, observed_at)
            if not heartbeat:
                return jsonify({"success": False, "error": "Session de présence introuvable"}), 404

            replacement_token = None
            if int(heartbeat["log_id"]) != int(log_id):
                session["log_id"] = int(heartbeat["log_id"])
                token_payload = {
                    "nom": session["nom"],
                    "prenom": session.get("prenom", ""),
                    "log_id": int(heartbeat["log_id"]),
                    "platform_id": int(session.get("platform_id", 1)),
                }
                if session.get("course_session_id") is not None:
                    token_payload["course_session_id"] = int(session["course_session_id"])
                if session.get("recipient_hash"):
                    token_payload["recipient_hash"] = session["recipient_hash"]
                replacement_token = issue_auth_token("student", token_payload)

            return jsonify({
                "success": True,
                "log_id": int(heartbeat["log_id"]),
                "reopened": bool(heartbeat.get("reopened")),
                "token": replacement_token,
                "observed_at": observed_at.isoformat(),
            }), 200
        except Exception:
            logger.exception("❌ Signal de présence impossible")
            return jsonify({"success": False, "error": "Présence momentanément indisponible"}), 500

    @auth_bp.route("/deconnexion-auto", methods=["POST"])
    def deconnexion_auto():
        try:
            nom = session.get("nom", "Inconnu")
            logger.info(f"🔄 Déconnexion automatique {nom}")

            if "log_id" in session:
                depart = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
                _close_student_log(session["log_id"], depart)
                logger.info(f"✅ Déconnexion auto enregistrée: {depart}")

            return "", 204

        except Exception as e:
            logger.error(f"❌ Erreur déconnexion auto: {e}")
            return "", 500

    @auth_bp.route("/deconnexion-auto-tous", methods=["POST"])
    def deconnexion_auto_tous():
        try:
            webhook_secret = os.environ.get("AUTO_LOGOUT_WEBHOOK_SECRET", "")
            supplied_secret = request.headers.get("X-Internal-Secret", "")
            authorized = bool(session.get("is_admin")) or (
                bool(webhook_secret)
                and bool(supplied_secret)
                and hmac.compare_digest(supplied_secret, webhook_secret)
            )
            if not authorized:
                logger.warning("⚠️ Appel non autorisé à la déconnexion globale")
                return {"success": False, "error": "Non autorisé"}, 403

            logger.info(
                "🔄 Déconnexion automatique de TOUS les utilisateurs (Azure Logic Apps)"
            )

            depart = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
            nb_deconnectes = _close_all_student_logs(depart)
            logger.info(f"✅ {nb_deconnectes} utilisateurs déconnectés automatiquement")

            # Forcer la redirection de tous les utilisateurs connectés
            socketio.emit(
                "force_logout",
                {
                    "message": "Fin de formation - Déconnexion automatique",
                    "redirect_url": "/logout",
                },
            )
            logger.info(
                "📢 Signal de déconnexion envoyé à tous les utilisateurs connectés"
            )

            return {"success": True, "users_disconnected": nb_deconnectes}, 200

        except Exception as e:
            logger.error(f"❌ Erreur déconnexion auto: {e}")
            return {"success": False, "error": str(e)}, 500

    return auth_bp
