# hr_routes.py - Routes du Dashboard RH (centre de contrôle multi-plateformes)
import os
import time
import requests as http_requests
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, session, jsonify
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.exceptions import ResourceExistsError
from config import FRANCE_TZ
from database.db import get_db_connection
from utils.logger import get_logger
import state

logger = get_logger(__name__)

PDF_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "pdfs")

HR_ENABLED = os.environ.get("HR_DASHBOARD_ENABLED", "false").lower() == "true"


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

    def _now_str():
        return datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")

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
            blobs = list(container_client.list_blobs())
            if not blobs:
                return None, None
            # Prendre le blob le plus récent
            blob = max(blobs, key=lambda b: b.last_modified)
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

    # ─── GET /api/hr/platforms ────────────────────────────────────────────
    @hr_bp.route("/api/hr/platforms", methods=["GET"])
    def get_platforms():
        """Vue d'ensemble des 3 plateformes avec stats et alertes"""
        denied = _require_admin()
        if denied:
            return denied

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, upload_locked, pdf_filename, pdf_uploaded_at, updated_at FROM platform_config ORDER BY id")
            rows = cursor.fetchall()

            # Compter demandes en attente par plateforme
            cursor.execute("SELECT platform_id, COUNT(*) FROM deletion_requests WHERE status='pending' GROUP BY platform_id")
            pending_counts = dict(cursor.fetchall())
            conn.close()

            # Stats Azure pour P1
            audio_count_p1 = 0
            last_upload_p1 = None
            blob_service_client, container_client = _get_azure_audio_clients()
            if container_client:
                try:
                    blobs = list(container_client.list_blobs())
                    audio_count_p1 = len(blobs)
                    if blobs:
                        latest = max(blobs, key=lambda b: b.last_modified)
                        last_upload_p1 = latest.last_modified.astimezone(FRANCE_TZ).strftime("%Y-%m-%d %H:%M")
                except Exception as e:
                    logger.warning(f"⚠️ Erreur lecture Azure audio: {e}")

            # PDF réel depuis Azure (source de vérité)
            azure_pdf_filename, azure_pdf_url = _get_azure_pdf_info()

            platforms = []
            for row in rows:
                pid, name, upload_locked, pdf_filename, pdf_uploaded_at, updated_at = row
                pinfo = _get_platform_info(pid)
                # En multi-tenant, toute plateforme en BDD est active
                active = pid == 1 or bool(pinfo.get("backend_url")) or pid >= 4

                # Stats audio pour P2+ depuis leur container Azure
                if pid == 1:
                    audio_count = audio_count_p1
                    last_upload = last_upload_p1
                else:
                    audio_count = 0
                    last_upload = None
                    if active:
                        try:
                            cs = os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING")
                            if cs:
                                bsc = BlobServiceClient.from_connection_string(cs)
                                cc = bsc.get_container_client(pinfo["audio_container"])
                                blobs = list(cc.list_blobs())
                                audio_count = len(blobs)
                                if blobs:
                                    latest = max(blobs, key=lambda b: b.last_modified)
                                    last_upload = latest.last_modified.astimezone(FRANCE_TZ).strftime("%Y-%m-%d %H:%M")
                        except Exception:
                            pass

                # Pour P1, utiliser le vrai fichier Azure comme source de vérité
                # Pour P2+, chercher dans leur container PDF Azure
                if pid == 1:
                    real_pdf_filename = azure_pdf_filename
                    real_pdf_url = azure_pdf_url
                else:
                    real_pdf_filename = pdf_filename
                    real_pdf_url = None
                    if active:
                        try:
                            cs = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
                            if cs:
                                from azure.storage.blob import generate_blob_sas, BlobSasPermissions
                                bsc = BlobServiceClient.from_connection_string(cs)
                                cc = bsc.get_container_client(pinfo["pdf_container"])
                                blobs = list(cc.list_blobs())
                                if blobs:
                                    blob = max(blobs, key=lambda b: b.last_modified)
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
                    if audio_count == 0:
                        alerts.append("Aucun audio")
                pending = pending_counts.get(pid, 0)
                if pending > 0:
                    alerts.append(f"{pending} demande(s) de suppression")

                platforms.append({
                    "id": pid,
                    "name": name,
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
                })

            return jsonify({"success": True, "platforms": platforms}), 200

        except Exception as e:
            logger.error(f"❌ Erreur get platforms: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── POST /api/hr/platforms (Créer une nouvelle plateforme) ──────────
    @hr_bp.route("/api/hr/platforms", methods=["POST"])
    def create_platform():
        """Crée une nouvelle plateforme : DB + containers Azure Blob"""
        denied = _require_admin()
        if denied:
            return denied

        data = request.get_json() or {}
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"success": False, "error": "Le nom est requis"}), 400

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Générer le slug depuis le nom
            import re
            slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')

            # Vérifier unicité du slug
            cursor.execute("SELECT COUNT(*) FROM platform_config WHERE slug = ?", (slug,))
            if cursor.fetchone()[0] > 0:
                conn.close()
                return jsonify({"success": False, "error": "Ce nom de plateforme existe déjà"}), 409

            now_str = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")

            # Insérer la plateforme (auto-increment)
            cursor.execute(
                "INSERT INTO platform_config (name, upload_locked, updated_at, slug) VALUES (?, 1, ?, ?)",
                (name, now_str, slug),
            )
            new_id = cursor.lastrowid

            # Noms des containers
            audio_container = f"formationaudio-p{new_id}"
            pdf_container = f"formationpdf-p{new_id}"
            archive_container = f"formationaudio-p{new_id}-archives"

            # Mettre à jour les noms de containers
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

            conn.commit()
            conn.close()

            # Créer les containers Azure Blob
            containers_created = []
            for cs_env, containers in [
                ("AZURE_AUDIO_STORAGE_CONNECTION_STRING", [audio_container, archive_container]),
                ("AZURE_STORAGE_CONNECTION_STRING", [pdf_container]),
            ]:
                cs = os.environ.get(cs_env)
                if cs:
                    bsc = BlobServiceClient.from_connection_string(cs)
                    for cname in containers:
                        try:
                            bsc.create_container(cname)
                            containers_created.append(cname)
                            logger.info(f"✅ Container Azure créé : {cname}")
                        except ResourceExistsError:
                            containers_created.append(f"{cname} (existait déjà)")
                        except Exception as e:
                            logger.warning(f"⚠️ Erreur création container {cname}: {e}")

            logger.info(f"✅ Plateforme {new_id} '{name}' créée avec containers: {containers_created}")

            return jsonify({
                "success": True,
                "platform": {
                    "id": new_id,
                    "name": name,
                    "slug": slug,
                    "audio_container": audio_container,
                    "pdf_container": pdf_container,
                    "archive_container": archive_container,
                    "containers_created": containers_created,
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

            # Propager le changement vers la plateforme distante (P2+)
            if platform_id != 1:
                _call_platform(platform_id, "/api/internal/set-lock", json_data={"locked": bool(new_value)})

            return jsonify({
                "success": True,
                "upload_locked": bool(new_value),
                "message": f"Upload {status_label} pour plateforme {platform_id}",
            }), 200

        except Exception as e:
            logger.error(f"❌ Erreur toggle lock: {e}")
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

            if status_filter == "all":
                cursor.execute("SELECT id, platform_id, filename, requester_name, reason, status, created_at, resolved_at FROM deletion_requests ORDER BY created_at DESC")
            else:
                cursor.execute(
                    "SELECT id, platform_id, filename, requester_name, reason, status, created_at, resolved_at FROM deletion_requests WHERE status = ? ORDER BY created_at DESC",
                    (status_filter,),
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
        if platform_id != 1:
            _call_platform(platform_id, "/api/internal/set-lock", json_data={"locked": False})

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

            return jsonify({"success": True, "message": f"PDF '{file.filename}' uploadé pour P{platform_id}, indexation lancée"}), 200

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

        if platform_id == 1:
            try:
                from services.time_service import get_heure_debut_cours
                heure = get_heure_debut_cours()
                return jsonify({
                    "success": True,
                    "date_cours": heure.strftime("%Y-%m-%d"),
                    "heure_cours": heure.strftime("%H:%M"),
                }), 200
            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 500
        else:
            result, error = _call_platform(platform_id, "/api/internal/course-time", method="GET")
            if error:
                return jsonify({"success": False, "error": error}), 500
            if result is None:
                return jsonify({"success": False, "error": "Plateforme non configurée"}), 400
            return jsonify(result), 200

    # ─── POST /api/hr/platforms/<id>/config-cours ─────────────────────────
    @hr_bp.route("/api/hr/platforms/<int:platform_id>/config-cours", methods=["POST"])
    def proxy_config_cours(platform_id):
        """Configurer l'heure du cours (P1=local, P2+=proxy service-to-service)"""
        denied = _require_admin()
        if denied:
            return denied

        data = request.get_json()
        date_str = (data or {}).get("date_cours", "").strip()
        heure_str = (data or {}).get("heure_cours", "").strip()
        if not date_str or not heure_str:
            return jsonify({"success": False, "error": "date_cours et heure_cours requis"}), 400

        if platform_id == 1:
            # Appel direct au service local
            try:
                from services.time_service import set_heure_debut_cours
                if heure_str.count(':') == 1:
                    datetime_str = f"{date_str} {heure_str}:00"
                else:
                    datetime_str = f"{date_str} {heure_str}"
                nouvelle_heure_naive = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
                nouvelle_heure_fr = FRANCE_TZ.localize(nouvelle_heure_naive)
                set_heure_debut_cours(nouvelle_heure_fr)
                return jsonify({
                    "success": True,
                    "message": f"Cours programmé pour le {date_str} à {heure_str}",
                }), 200
            except Exception as e:
                logger.error(f"❌ Erreur config-cours P1: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        else:
            result, error = _call_platform(platform_id, "/api/internal/config-cours", json_data=data)
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
          - P3 : mercredi à 9h00

        Corps JSON optionnel pour surcharger :
          { "schedule": [{"platform_id": 1, "weekday": 4, "hour": 9}] }
          weekday : 0=lundi, 1=mardi, 2=mercredi, 3=jeudi, 4=vendredi, 5=samedi, 6=dimanche
        """
        api_key = request.headers.get("X-Platform-Key", "")
        expected_key = os.environ.get("PLATFORM_API_KEY", "")
        if not expected_key or api_key != expected_key:
            return jsonify({"success": False, "error": "Clé invalide"}), 403

        DEFAULT_SCHEDULE = [
            {"platform_id": 1, "weekday": 4, "hour": 9},  # vendredi
            {"platform_id": 2, "weekday": 0, "hour": 9},  # lundi
            {"platform_id": 3, "weekday": 2, "hour": 9},  # mercredi
            {"platform_id": 4, "weekday": 3, "hour": 9},  # jeudi
        ]

        data = request.get_json() or {}
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

            if platform_id == 1:
                try:
                    from services.time_service import set_heure_debut_cours
                    nouvelle_heure_naive = datetime.strptime(
                        f"{date_str} {heure_str}:00", "%Y-%m-%d %H:%M:%S"
                    )
                    nouvelle_heure_fr = FRANCE_TZ.localize(nouvelle_heure_naive)
                    set_heure_debut_cours(nouvelle_heure_fr)
                    results.append({"platform_id": 1, "success": True, "scheduled": f"{date_str} {heure_str}"})
                    logger.info(f"📅 Auto-schedule P1 : {date_str} {heure_str}")
                except Exception as e:
                    results.append({"platform_id": 1, "success": False, "error": str(e)})
                    logger.error(f"❌ Auto-schedule P1 : {e}")
            else:
                result, error = _call_platform(
                    platform_id,
                    "/api/internal/config-cours",
                    json_data={"date_cours": date_str, "heure_cours": heure_str},
                )
                if error:
                    results.append({"platform_id": platform_id, "success": False, "error": error})
                    logger.error(f"❌ Auto-schedule P{platform_id} : {error}")
                else:
                    results.append({"platform_id": platform_id, "success": True, "scheduled": f"{date_str} {heure_str}"})
                    logger.info(f"📅 Auto-schedule P{platform_id} : {date_str} {heure_str}")

        all_ok = all(r["success"] for r in results)
        return jsonify({"success": all_ok, "results": results}), 200

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
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT cf.id, cf.name, cf.created_at, COUNT(cd.id) as document_count
                FROM cours_folders cf
                LEFT JOIN cours_documents cd ON cf.id = cd.folder_id
                WHERE cf.platform_id = ?
                GROUP BY cf.id
                ORDER BY cf.created_at DESC
            """, (platform_id,))
            folders = [{"id": row[0], "name": row[1], "created_at": row[2], "document_count": row[3]} for row in cursor.fetchall()]
            conn.close()
            return jsonify({"success": True, "folders": folders}), 200
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
            cursor.execute(
                "INSERT INTO cours_folders (platform_id, name) VALUES (?, ?)",
                (platform_id, name)
            )
            folder_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return jsonify({"success": True, "id": folder_id, "name": name}), 201
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
            cursor.execute("""
                SELECT id, filename, original_name, status, audio_filename, created_at
                FROM cours_documents
                WHERE folder_id = ?
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
        """Upload un ou plusieurs PDFs dans un dossier → Azure Blob Storage"""
        denied = _require_admin()
        if denied:
            return denied

        if "files" not in request.files:
            return jsonify({"success": False, "error": "Aucun fichier"}), 400

        files = request.files.getlist("files")
        uploaded = []

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
                if not file.filename.lower().endswith(".pdf"):
                    continue

                # Générer un nom unique et construire le blob path
                unique_name = f"{uuid_mod.uuid4()}.pdf"
                blob_path = build_blob_path(platform_id, folder_id, unique_name)

                # Upload vers Azure documenttts
                file_bytes = file.read()
                upload_blob(CONTAINER_DOCUMENTS, blob_path, file_bytes)

                # Créer l'entrée DB (filename = blob path dans le container)
                cursor.execute(
                    "INSERT INTO cours_documents (folder_id, filename, original_name, status) VALUES (?, ?, ?, 'uploaded')",
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
            cursor.execute("""
                SELECT id FROM cours_documents
                WHERE folder_id = ? AND audio_filename IS NULL
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
            cursor.execute("""
                SELECT id, original_name, status
                FROM cours_documents
                WHERE folder_id = ?
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

    # ─── Pipeline playlist complète (19 fichiers) ─────────────────────────

    # État global de la pipeline playlist (par folder_id)
    _playlist_jobs = {}

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/generate-playlist", methods=["POST"])
    def generate_playlist(folder_id):
        """Lance la génération des 19 fichiers MP3 de la playlist pour un dossier."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            # Vérifier que le dossier existe et récupérer le platform_id
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT platform_id FROM cours_folders WHERE id = ?", (folder_id,))
            row = cursor.fetchone()
            conn.close()

            if not row:
                return jsonify({"success": False, "error": "Dossier introuvable"}), 404

            platform_id = row[0]

            # Vérifier qu'il n'y a pas déjà une pipeline en cours
            if folder_id in _playlist_jobs and _playlist_jobs[folder_id].get("status") == "running":
                return jsonify({
                    "success": False,
                    "error": "Une génération est déjà en cours pour ce dossier"
                }), 409

            # Initialiser le job
            _playlist_jobs[folder_id] = {
                "status": "running",
                "step": 0,
                "total_steps": 24,
                "message": "Démarrage de la pipeline...",
                "result": None,
            }

            def _run_playlist_pipeline(platform_id, folder_id):
                try:
                    from services.playlist_tts_service import generate_playlist_for_folder

                    def on_progress(step, total, message):
                        _playlist_jobs[folder_id].update({
                            "step": step,
                            "total_steps": total,
                            "message": message,
                        })

                    result = generate_playlist_for_folder(
                        platform_id, folder_id, progress_callback=on_progress
                    )
                    _playlist_jobs[folder_id].update({
                        "status": "completed",
                        "result": result,
                        "message": f"Terminé : {result['generated']}/19 fichiers générés",
                    })
                except Exception as e:
                    logger.error(f"❌ Pipeline playlist échouée: {e}")
                    _playlist_jobs[folder_id].update({
                        "status": "error",
                        "message": str(e),
                    })

            import eventlet
            eventlet.spawn(_run_playlist_pipeline, platform_id, folder_id)

            return jsonify({"success": True, "message": "Pipeline démarrée"}), 202

        except Exception as e:
            logger.error(f"❌ Erreur generate_playlist: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @hr_bp.route("/api/hr/cours-folders/<int:folder_id>/playlist-script", methods=["GET"])
    def get_playlist_script(folder_id):
        """Retourne le script reformulé par Claude pour un dossier."""
        denied = _require_admin()
        if denied:
            return denied

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT platform_id FROM cours_folders WHERE id = ?", (folder_id,))
            row = cursor.fetchone()
            conn.close()

            if not row:
                return jsonify({"success": False, "error": "Dossier introuvable"}), 404

            platform_id = row[0]

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

        job = _playlist_jobs.get(folder_id)
        if not job:
            return jsonify({"success": True, "status": "idle"}), 200

        return jsonify({"success": True, **job}), 200

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

                cursor.execute("""
                    SELECT id FROM cours_documents
                    WHERE folder_id = ? AND audio_filename IS NULL AND status != 'processing'
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
            cursor.execute("SELECT id, name, playlist_mode FROM platform_config ORDER BY id")
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
        platform_ids = data.get("platform_ids", [])  # IDs des plateformes concernées

        if mode not in ("ete", "hiver"):
            return jsonify({"success": False, "error": "Mode invalide (ete ou hiver)"}), 400

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Remettre toutes les plateformes à NULL (non concernées)
            cursor.execute("UPDATE platform_config SET playlist_mode = NULL")

            # Appliquer le mode aux plateformes sélectionnées
            for pid in platform_ids:
                cursor.execute(
                    "UPDATE platform_config SET playlist_mode = ? WHERE id = ?",
                    (mode, pid)
                )

            conn.commit()
            conn.close()
            logger.info(f"✅ Schedule config: mode={mode}, plateformes={platform_ids}")
            return jsonify({"success": True}), 200
        except Exception as e:
            logger.error(f"❌ Erreur set_schedule_config: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    return hr_bp
