# admin_routes.py --- Routes d'administration (API JSON uniquement)
from flask import Blueprint, request, session, jsonify, send_file
from datetime import datetime, timedelta, timezone
import os
import re
import tempfile
import requests as http_requests
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.exceptions import ResourceExistsError
from pydub import AudioSegment
import state
from config import FRANCE_TZ
from database.db import get_db_connection
from services.time_service import set_heure_debut_cours, get_heure_debut_cours
from services.export_service import generate_excel_export
from utils.logger import get_logger

logger = get_logger(__name__)


def create_admin_blueprint(socketio):
    """Factory pour créer le blueprint admin avec accès à socketio"""
    admin_bp = Blueprint("admin", __name__)

    @admin_bp.route("/api/admin/logs", methods=["GET"])
    def get_logs():
        """Récupère les logs avec filtrage optionnel par prénom"""
        try:
            if not session.get("is_admin"):
                logger.warning("⚠️ Tentative accès admin sans authentification")
                return jsonify({"authenticated": False, "error": "Accès refusé"}), 403

            logger.info("👑 Accès admin logs")
            prenom_recherche = request.args.get("prenom", "")

            if prenom_recherche:
                logger.debug(f"🔍 Recherche admin par prénom: {prenom_recherche}")

            # Récupération de l'heure actuelle du cours
            heure_debut_cours = get_heure_debut_cours()

            conn = get_db_connection()
            cursor = conn.cursor()

            if prenom_recherche:
                cursor.execute(
                    "SELECT * FROM logs WHERE prenom LIKE ?",
                    ("%" + prenom_recherche + "%",),
                )
            else:
                cursor.execute("SELECT * FROM logs")

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
            heure = get_heure_debut_cours()
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

            logger.info(f"⚙️ Nouvelle heure calculée: {nouvelle_heure_fr}")

            # Sauvegarder en base
            set_heure_debut_cours(nouvelle_heure_fr)

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
        """Service-to-service : verrouiller/déverrouiller l'upload (appelé par P1 HR)"""
        api_key = os.environ.get("PLATFORM_API_KEY", "")
        if not api_key or request.headers.get("X-Platform-Key") != api_key:
            return jsonify({"success": False, "error": "Non autorisé"}), 401
        try:
            data = request.get_json()
            locked = bool(data.get("locked", True))
            now = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE platform_config SET upload_locked = ?, updated_at = ? WHERE id = 1",
                (1 if locked else 0, now),
            )
            conn.commit()
            conn.close()
            logger.info(
                f"🔒 Lock interne mis à jour: {'verrouillé' if locked else 'déverrouillé'}"
            )
            return jsonify({"success": True, "upload_locked": locked}), 200
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
            set_heure_debut_cours(nouvelle_heure_fr)
            logger.info(f"⚙️ Heure cours configurée en interne: {nouvelle_heure_fr}")
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
            heure = get_heure_debut_cours()
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

            logger.info("📊 Export Excel demandé")
            prenom = request.args.get("prenom", "")

            conn = get_db_connection()
            cursor = conn.cursor()

            if prenom:
                cursor.execute(
                    "SELECT * FROM logs WHERE prenom LIKE ?", ("%" + prenom + "%",)
                )
            else:
                cursor.execute("SELECT * FROM logs")

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
        try:
            if session.get("is_admin"):
                logger.info("👑 Admin déjà connecté")
                return jsonify({"success": True, "message": "Déjà connecté"}), 200

            data = request.get_json()
            username = data.get("username", "").strip()
            password = data.get("password", "").strip()

            logger.info(f"🔐 Tentative connexion admin: {username}")

            if username == "admin" and password == "secret123":
                session["is_admin"] = True
                session.permanent = True
                logger.info("✅ Connexion admin réussie")
                return jsonify({"success": True, "message": "Connexion réussie"}), 200
            else:
                logger.warning("❌ Échec connexion admin - identifiants incorrects")
                return (
                    jsonify({"success": False, "error": "Identifiants incorrects"}),
                    401,
                )

        except Exception as e:
            logger.error(f"❌ Erreur login admin: {e}")
            return jsonify({"success": False, "error": "Erreur serveur"}), 500

    @admin_bp.route("/api/admin/logout", methods=["POST"])
    def logout_admin():
        """Déconnexion administrateur"""
        try:
            logger.info("👑 Déconnexion admin")
            session.pop("is_admin", None)
            return jsonify({"success": True, "message": "Déconnexion réussie"}), 200
        except Exception as e:
            logger.error(f"❌ Erreur logout admin: {e}")
            return jsonify({"success": False, "error": "Erreur serveur"}), 500

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

            state.simulated_time_offset = FRANCE_TZ.localize(simulated_time_naive)

            logger.info(f"✅ Heure simulée: {state.simulated_time_offset}")

            return (
                jsonify(
                    {
                        "success": True,
                        "message": f"Heure simulée: {state.simulated_time_offset.strftime('%Y-%m-%d %H:%M:%S')}",
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

            logger.info("⏰ Reset simulation demandé")
            state.simulated_time_offset = None
            logger.info("✅ Simulation désactivée")

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

            logger.info("🔒 Forçage déconnexion utilisateurs")

            conn = get_db_connection()
            cursor = conn.cursor()
            depart_time = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "UPDATE logs SET depart = ? WHERE depart IS NULL OR depart = ''",
                (depart_time,),
            )
            affected_rows = cursor.rowcount
            conn.commit()
            conn.close()

            # Signal à tous les clients
            socketio.emit(
                "force_logout",
                {
                    "message": "Formation terminée - Déconnexion automatique",
                    "redirect_url": "/logout",
                },
            )

            logger.info(f"✅ {affected_rows} utilisateurs déconnectés")

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
