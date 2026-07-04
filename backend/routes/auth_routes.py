# auth_routes.py -- Routes d'authentification et connexion utilisateur (API JSON)
import hmac
import os
from flask import Blueprint, request, session, jsonify
from datetime import datetime, timedelta
import uuid
import requests
from werkzeug.security import check_password_hash
from config import FRANCE_TZ, STUDENT_AUTH_LEGACY_FALLBACK, SUPABASE_ANON_KEY, SUPABASE_URL
from database.db import get_db_connection
from database.postgres import postgres_enabled
from repositories.core_repository import (
    count_student_accounts,
    get_student_account,
    get_student_profile,
    update_log_depart,
    upsert_log,
    upsert_student_profile,
)
from utils.logger import get_logger
import state

logger = get_logger(__name__)


def _create_local_student_session(cursor, nom, prenom, platform_id):
    session["nom"] = nom
    session["prenom"] = prenom
    session["platform_id"] = platform_id
    arrivee_time = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
    session["arrivee"] = arrivee_time

    cursor.execute(
        "INSERT INTO logs (nom, prenom, arrivee, platform_id) VALUES (?, ?, ?, ?)",
        (nom, prenom, arrivee_time, platform_id),
    )
    log_id = cursor.lastrowid
    session["log_id"] = log_id

    token = str(uuid.uuid4())
    state.user_tokens[token] = {
        "nom": nom,
        "prenom": prenom,
        "log_id": log_id,
        "platform_id": platform_id,
    }
    if postgres_enabled():
        try:
            upsert_log({
                "id": log_id,
                "platform_id": platform_id,
                "nom": nom,
                "prenom": prenom,
                "arrivee": arrivee_time,
                "depart": None,
            })
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


def _course_session_password_valid(cursor, platform_id, password):
    supplied = str(password or "").strip()
    if not supplied:
        return False

    try:
        from services.course_schedule_service import ensure_course_schedule_tables

        ensure_course_schedule_tables(cursor)
        now = datetime.now(FRANCE_TZ)
        early_hours = float(os.environ.get("COURSE_SESSION_PASSWORD_EARLY_HOURS", "24"))
        active_hours = float(os.environ.get("COURSE_SESSION_ACTIVE_HOURS", "12"))
        lower_bound = (now - timedelta(hours=active_hours)).strftime("%Y-%m-%d %H:%M:%S")
        upper_bound = (now + timedelta(hours=early_hours)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            """
            SELECT session_password
            FROM course_sessions
            WHERE platform_id = ?
              AND status IN ('planned', 'active')
              AND scheduled_at >= ?
              AND scheduled_at <= ?
              AND session_password IS NOT NULL
              AND session_password != ''
            ORDER BY scheduled_at ASC
            """,
            (platform_id, lower_bound, upper_bound),
        )
        session_passwords = [str(row[0] or "") for row in cursor.fetchall() if row[0]]
        if session_passwords:
            return any(hmac.compare_digest(supplied, expected) for expected in session_passwords)
    except Exception:
        logger.warning("⚠️ Vérification mot de passe séance impossible", exc_info=True)

    expected = os.environ.get("COURSE_SESSION_PASSWORD", "").strip()
    if expected:
        return hmac.compare_digest(supplied, expected)
    return STUDENT_AUTH_LEGACY_FALLBACK


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
            nom = str(data.get("nom") or "").strip()
            prenom = str(data.get("prenom") or "").strip()
            try:
                platform_id = int(data.get("platform_id", 1))
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "Plateforme invalide"}), 400

            logger.info(f"👤 Tentative connexion élève: {username or nom} (P{platform_id})")

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
            pg_account = None
            if postgres_enabled() and username:
                try:
                    pg_account = get_student_account(platform_id, username)
                except Exception:
                    logger.warning("⚠️ Lecture compte élève Postgres impossible", exc_info=True)

            if pg_account:
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
                cursor.execute(
                    "SELECT COUNT(*) FROM student_accounts WHERE platform_id = ?",
                    (platform_id,),
                )
                has_accounts = cursor.fetchone()[0] > 0
                if postgres_enabled():
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

            log_id, token = _create_local_student_session(cursor, nom, prenom, platform_id)
            conn.commit()

            logger.info(f"✅ Utilisateur enregistré en base avec ID: {log_id}")

            return (
                jsonify(
                    {
                        "success": True,
                        "user": {"nom": nom, "prenom": prenom},
                        "log_id": log_id,
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
            metadata = supabase_user.get("user_metadata") or {}
            pg_profile = None
            if postgres_enabled():
                try:
                    pg_profile = get_student_profile(auth_user_id)
                except Exception:
                    logger.warning("⚠️ Lecture profil élève Postgres impossible", exc_info=True)

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
            else:
                cursor.execute(
                    """
                    SELECT nom, prenom, platform_id, is_active, role
                    FROM student_profiles
                    WHERE auth_user_id = ?
                    """,
                    (auth_user_id,),
                )
                profile = cursor.fetchone()

            if not profile:
                nom = str(metadata.get("nom") or metadata.get("last_name") or "").strip()
                prenom = str(metadata.get("prenom") or metadata.get("first_name") or "").strip()
                platform_id = int(metadata.get("platform_id") or requested_platform_id)
                if not nom or not prenom:
                    return jsonify({"success": False, "error": "Profil élève introuvable"}), 403
                now = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(
                    """
                    INSERT INTO student_profiles
                        (auth_user_id, platform_id, email, nom, prenom, role, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'student', 1, ?, ?)
                    """,
                    (auth_user_id, platform_id, email, nom, prenom, now, now),
                )
                if postgres_enabled():
                    try:
                        upsert_student_profile({
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
                    except Exception:
                        logger.warning("⚠️ Miroir Postgres profil élève impossible", exc_info=True)
            else:
                nom, prenom, platform_id, is_active, role = profile
                if not is_active:
                    return jsonify({"success": False, "error": "Compte désactivé"}), 403
                if int(platform_id) != requested_platform_id:
                    return jsonify({"success": False, "error": "Compte non autorisé sur cette plateforme"}), 403
                if postgres_enabled() and not pg_profile:
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

            log_id, token = _create_local_student_session(cursor, nom, prenom, int(platform_id))
            conn.commit()
            logger.info("✅ Session Supabase reliée au log %s pour %s P%s", log_id, email, platform_id)
            return jsonify({
                "success": True,
                "user": {"nom": nom, "prenom": prenom, "email": email},
                "log_id": log_id,
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
                conn = get_db_connection()
                cursor = conn.cursor()
                # Départ en heure française
                depart = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(
                    "UPDATE logs SET depart=? WHERE id=?", (depart, session["log_id"])
                )
                conn.commit()
                conn.close()
                try:
                    update_log_depart(session["log_id"], depart)
                except Exception:
                    logger.warning("⚠️ Miroir Postgres du départ impossible", exc_info=True)
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

    @auth_bp.route("/deconnexion-auto", methods=["POST"])
    def deconnexion_auto():
        try:
            nom = session.get("nom", "Inconnu")
            logger.info(f"🔄 Déconnexion automatique {nom}")

            if "log_id" in session:
                conn = get_db_connection()
                cursor = conn.cursor()
                depart = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(
                    "UPDATE logs SET depart=? WHERE id=?",
                    (depart, session["log_id"]),
                )
                conn.commit()
                conn.close()
                try:
                    update_log_depart(session["log_id"], depart)
                except Exception:
                    logger.warning("⚠️ Miroir Postgres du départ auto impossible", exc_info=True)
                logger.info(f"✅ Déconnexion auto enregistrée: {depart}")

            return "", 204

        except Exception as e:
            logger.error(f"❌ Erreur déconnexion auto: {e}")
            return "", 500

    @auth_bp.route("/deconnexion-auto-tous", methods=["POST"])
    def deconnexion_auto_tous():
        try:
            logger.info(
                "🔄 Déconnexion automatique de TOUS les utilisateurs (Azure Logic Apps)"
            )

            conn = get_db_connection()
            cursor = conn.cursor()
            depart = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute(
                "UPDATE logs SET depart=? WHERE depart IS NULL OR depart = ''",
                (depart,),
            )

            nb_deconnectes = cursor.rowcount
            conn.commit()
            conn.close()
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
