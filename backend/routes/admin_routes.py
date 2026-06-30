# admin_routes.py --- Routes d'administration (API JSON uniquement)
from flask import Blueprint, request, session, jsonify, send_file
from datetime import datetime, timedelta, timezone
import os
import re
import sqlite3
import tempfile
import uuid
import requests as http_requests
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.exceptions import ResourceExistsError
from pydub import AudioSegment
from werkzeug.security import check_password_hash, generate_password_hash
import state
from config import FRANCE_TZ, DB_PATH, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL
from database.db import get_db_connection
from database import db_safety
from database.postgres import postgres_enabled
from repositories.core_repository import (
    DuplicateTrainingCenterUsername,
    create_ai_teacher_order,
    create_training_center,
    get_training_center_by_username,
    list_ai_teacher_orders,
    upsert_student_profile_with_id,
)
from services.time_service import set_heure_debut_cours, get_heure_debut_cours
from services.export_service import generate_excel_export
from utils.logger import get_logger
from utils.slug import slugify, unique_slug

logger = get_logger(__name__)


def _create_admin_token(account_type, account_id=None, center_name=None):
    if not hasattr(state, "admin_tokens"):
        state.admin_tokens = {}
    token = str(uuid.uuid4())
    state.admin_tokens[token] = {
        "account_type": account_type,
        "account_id": account_id,
        "center_name": center_name,
    }
    return token


def _get_platform_id():
    """Extrait platform_id pour la requête courante avec priorité explicite.

    Ordre : X-Platform-Id header → query ?platform_id ou ?p → session → fallback 1.
    Le fallback log un warning pour repérer les oublis d'injection côté appelant.
    """
    raw = request.headers.get("X-Platform-Id")
    if raw and raw.isdigit():
        return int(raw)
    for key in ("platform_id", "p"):
        arg = request.args.get(key)
        if arg and str(arg).isdigit():
            return int(arg)
    if request.is_json:
        body = request.get_json(silent=True) or {}
        raw_body = body.get("platform_id") or body.get("p")
        if raw_body and str(raw_body).isdigit():
            return int(raw_body)
    pid = session.get("platform_id")
    if pid:
        try:
            return int(pid)
        except (TypeError, ValueError):
            pass
    logger.warning("⚠️ platform_id introuvable (header/query/session absents) — fallback sur 1 pour %s", request.path)
    return 1


def _mirror_training_center_to_sqlite(cursor, account, password_hash, now_str):
    cursor.execute(
        """
        INSERT INTO training_center_accounts
            (id, username, password_hash, center_name, slug, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            username = excluded.username,
            password_hash = excluded.password_hash,
            center_name = excluded.center_name,
            slug = excluded.slug,
            is_active = excluded.is_active,
            updated_at = excluded.updated_at
        """,
        (
            account["id"],
            account["username"],
            password_hash,
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
        try:
            data = request.get_json()
            date_str = data.get("date_cours", "").strip()
            heure_str = data.get("heure_cours", "").strip()
            if not date_str or not heure_str:
                return (
                    jsonify({"success": False, "error": "Date et heure requises"}),
                    400,
                )
            if heure_str.count(":") == 1:
                datetime_str = f"{date_str} {heure_str}:00"
            else:
                datetime_str = f"{date_str} {heure_str}"
            nouvelle_heure_naive = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
            nouvelle_heure_fr = FRANCE_TZ.localize(nouvelle_heure_naive)
            # Récupérer platform_id depuis le body ou la session (défaut: 1)
            platform_id = data.get("platform_id", session.get("platform_id", 1))
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
        except Exception as e:
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
            return jsonify({
                "success": True,
                "date_cours": heure.strftime("%Y-%m-%d"),
                "heure_cours": heure.strftime("%H:%M"),
            }), 200
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
            if session.get("is_admin"):
                logger.info("👑 Admin déjà connecté")
                token = request.headers.get("X-Auth-Token") or _create_admin_token(
                    session.get("admin_account_type", "legacy_admin"),
                    session.get("admin_account_id"),
                    session.get("center_name"),
                )
                return jsonify({"success": True, "message": "Déjà connecté", "token": token}), 200

            data = request.get_json(silent=True) or {}
            username = data.get("username", "").strip().lower()
            password = data.get("password", "").strip()

            logger.info(f"🔐 Tentative connexion admin: {username}")

            if username == "admin" and password.replace(" ", "") == "secret123":
                session["is_admin"] = True
                session["admin_account_type"] = "legacy_admin"
                session.permanent = True
                token = _create_admin_token("legacy_admin")
                logger.info("✅ Connexion admin réussie")
                return jsonify({"success": True, "message": "Connexion réussie", "token": token}), 200

            if postgres_enabled():
                account = get_training_center_by_username(username)
                if account:
                    if not password or not check_password_hash(account["password_hash"], password):
                        logger.warning("❌ Échec connexion centre Postgres - identifiants incorrects")
                        return jsonify({"success": False, "error": "Identifiants incorrects"}), 401
                    if not account["is_active"]:
                        logger.warning("⚠️ Compte centre Postgres désactivé: %s", username)
                        return jsonify({"success": False, "error": "Compte désactivé"}), 403

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
                                    "id": account["id"],
                                    "username": account["username"],
                                    "center_name": account["center_name"],
                                    "slug": account["slug"],
                                },
                            }
                        ),
                        200,
                    )

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

            if not account or not password or not check_password_hash(account[2], password):
                logger.warning("❌ Échec connexion admin - identifiants incorrects")
                return (
                    jsonify({"success": False, "error": "Identifiants incorrects"}),
                    401,
                )

            if not account[4]:
                logger.warning("⚠️ Compte centre désactivé: %s", username)
                return jsonify({"success": False, "error": "Compte désactivé"}), 403

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
                        center_name=center_name,
                        slug_base=center_name or username,
                        now=now_str,
                    )
                except DuplicateTrainingCenterUsername:
                    return jsonify({"success": False, "error": "Cet identifiant existe déjà"}), 409

                conn = get_db_connection()
                cursor = conn.cursor()
                _mirror_training_center_to_sqlite(cursor, account, password_hash, now_str)
                conn.commit()

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
                    (username, password_hash, center_name, slug, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    username,
                    password_hash,
                    center_name,
                    center_slug,
                    now_str,
                    now_str,
                ),
            )
            account_id = cursor.lastrowid
            conn.commit()

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
        """Crée une commande d'agent IA en brouillon côté SaaS core."""
        if not session.get("is_admin") or session.get("admin_account_type") != "training_center":
            return jsonify({"success": False, "error": "Accès refusé"}), 403
        if not postgres_enabled():
            return jsonify({"success": False, "error": "Postgres non activé"}), 503

        data = request.get_json(silent=True) or {}
        training_title = str(data.get("training_title") or "").strip()
        rncp_code = str(data.get("rncp_code") or "").strip() or None
        platform_id = data.get("platform_id")
        quoted_amount_cents = data.get("quoted_amount_cents")
        try:
            total_hours = int(data.get("total_hours") or 0)
        except (TypeError, ValueError):
            total_hours = 0

        if not training_title or total_hours <= 0:
            return jsonify({
                "success": False,
                "error": "training_title et total_hours sont requis",
            }), 400

        try:
            order = create_ai_teacher_order({
                "center_account_id": session.get("admin_account_id"),
                "platform_id": int(platform_id) if platform_id else None,
                "status": "draft",
                "training_title": training_title,
                "rncp_code": rncp_code,
                "total_hours": total_hours,
                "quoted_amount_cents": int(quoted_amount_cents) if quoted_amount_cents else None,
                "currency": "eur",
                "stripe_checkout_session_id": None,
                "stripe_payment_intent_id": None,
            })
            return jsonify({"success": True, "order": order}), 201
        except Exception:
            logger.exception("❌ Erreur création commande IA")
            return jsonify({"success": False, "error": "Erreur serveur"}), 500

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
