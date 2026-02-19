# hr_routes.py - Routes du Dashboard RH (centre de contrôle multi-plateformes)
import os
import time
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


def create_hr_blueprint(socketio):
    """Factory pour créer le blueprint HR avec accès à socketio"""
    hr_bp = Blueprint("hr", __name__)

    @hr_bp.route("/api/hr/enabled")
    def get_hr_enabled():
        return jsonify({"enabled": HR_ENABLED})

    @hr_bp.before_request
    def check_hr_enabled():
        from flask import request as req
        if req.endpoint == "hr.get_hr_enabled":
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
                active = pid == 1
                audio_count = audio_count_p1 if pid == 1 else 0
                last_upload = last_upload_p1 if pid == 1 else None

                # Pour P1, utiliser le vrai fichier Azure comme source de vérité
                real_pdf_filename = azure_pdf_filename if pid == 1 else pdf_filename
                real_pdf_url = azure_pdf_url if pid == 1 else None

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
                })

            return jsonify({"success": True, "platforms": platforms}), 200

        except Exception as e:
            logger.error(f"❌ Erreur get platforms: {e}")
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
        """Lister les audios d'une plateforme (P1=Azure, P2/P3=vide)"""
        denied = _require_admin()
        if denied:
            return denied

        if platform_id != 1:
            return jsonify({"success": True, "audios": [], "message": "Plateforme pas encore connectée"}), 200

        try:
            blob_service_client, container_client = _get_azure_audio_clients()
            if not container_client:
                return jsonify({"success": False, "error": "Configuration Azure manquante"}), 500

            account_name = blob_service_client.account_name
            account_key = blob_service_client.credential.account_key
            container_name = os.environ.get("AZURE_AUDIO_CONTAINER", "formationaudio-dev")
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
            logger.error(f"❌ Erreur liste audios HR: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ─── DELETE /api/hr/platforms/<id>/audios/<filename> ──────────────────
    @hr_bp.route("/api/hr/platforms/<int:platform_id>/audios/<path:filename>", methods=["DELETE"])
    def delete_audio(platform_id, filename):
        """Supprimer un audio (P1 seulement)"""
        denied = _require_admin()
        if denied:
            return denied

        if platform_id != 1:
            return jsonify({"success": False, "error": "Suppression non disponible pour cette plateforme"}), 400

        try:
            _, container_client = _get_azure_audio_clients()
            if not container_client:
                return jsonify({"success": False, "error": "Configuration Azure manquante"}), 500

            container_client.delete_blob(filename)
            logger.info(f"🗑️ Audio supprimé: {filename}")

            return jsonify({"success": True, "message": f"'{filename}' supprimé"}), 200

        except Exception as e:
            logger.error(f"❌ Erreur suppression audio: {e}")
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

        if platform_id != 1:
            return jsonify({"success": False, "error": "Backup non disponible pour cette plateforme"}), 400

        connection_string = os.environ.get("AZURE_AUDIO_STORAGE_CONNECTION_STRING")
        archive_container = os.environ.get("AZURE_AUDIO_ARCHIVE_CONTAINER", "formationaudio-archives")
        source_container = os.environ.get("AZURE_AUDIO_CONTAINER", "formationaudio-dev")

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
        """Met upload_locked = 0 en base"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE platform_config SET upload_locked = 0, updated_at = ? WHERE id = ?",
            (_now_str(), platform_id),
        )
        conn.commit()
        conn.close()

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

    return hr_bp
