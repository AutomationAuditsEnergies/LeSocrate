"""
Routes pipeline formation automatisé.

POST /api/formation/search-rncp           Recherche RNCP depuis nom TP
POST /api/formation/init                  Crée un job (tp_name, total_hours, rncp_code)
GET  /api/formation/<job_id>              Statut + données du job
POST /api/formation/<job_id>/fetch-reac   Télécharge + extrait le REAC
POST /api/formation/<job_id>/generate-global   Lance génération programme global
POST /api/formation/<job_id>/validate-global   Valide (et éventuellement édite) le programme global
POST /api/formation/<job_id>/split-daily       Lance le découpage en journées
POST /api/formation/<job_id>/validate-daily    Valide les programmes journée
POST /api/formation/<job_id>/launch-tts        Crée les dossiers et lance la génération TEXTE des cours
GET  /api/formation/<job_id>/content      Liste les dossiers cours (journées) + état génération texte
GET  /api/formation/<job_id>/content/<folder_id>/docx  Télécharge le document Word d'une journée
POST /api/formation/<job_id>/launch-audio Lance la synthèse TTS Fish Audio sur toutes les journées
GET  /api/formation/list                  Liste les jobs de la plateforme
"""

import math
import threading

from flask import Blueprint, jsonify, request, session, send_file
from io import BytesIO

from services.formation_pipeline_service import (
    search_rncp,
    download_reac_text,
    download_rc_text,
    fetch_rome_data,
    launch_global_program_generation,
    launch_daily_split,
    launch_tts_for_all_days,
    create_job,
    update_job,
    get_job,
    list_jobs,
    HOURS_PER_DAY,
)
from services.knowledge_base_service import (
    launch_kb_building,
    list_kb,
    kb_stats,
)
from utils.logger import get_logger

logger = get_logger(__name__)

formation_bp = Blueprint("formation", __name__)


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
    """
    Crée un job pipeline formation + une nouvelle plateforme dédiée.
    Body: { "platform_name": "TP CRCD 2026", "tp_name": "TP CRCD", "total_hours": 70, "rncp_code": "35304" }
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    data = request.get_json() or {}
    platform_name = (data.get("platform_name") or "").strip()
    tp_name = (data.get("tp_name") or "").strip()
    rncp_code = (data.get("rncp_code") or "").strip()
    total_hours = data.get("total_hours")

    if not platform_name:
        return jsonify({"error": "Le champ 'platform_name' est requis"}), 400
    if not tp_name:
        return jsonify({"error": "Le champ 'tp_name' est requis"}), 400
    if not rncp_code:
        return jsonify({"error": "Le champ 'rncp_code' est requis"}), 400
    if not total_hours or int(total_hours) <= 0:
        return jsonify({"error": "Le champ 'total_hours' doit être > 0"}), 400

    total_hours = int(total_hours)
    nb_days = math.ceil(total_hours / HOURS_PER_DAY)

    try:
        from database.db import get_db_connection
        from datetime import datetime
        from config import FRANCE_TZ

        conn = get_db_connection()
        cursor = conn.cursor()

        # Créer une nouvelle plateforme dédiée à cette formation
        now_str = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO platform_config (name, upload_locked, updated_at) VALUES (?, 1, ?)",
            (platform_name, now_str)
        )
        new_platform_id = cursor.lastrowid

        # Containers Azure auto-générés (à créer manuellement dans Azure si besoin)
        slug = platform_name.lower().replace(" ", "-").replace("_", "-")[:40]
        cursor.execute(
            """UPDATE platform_config
               SET audio_container=?, pdf_container=?, archive_container=?, slug=?, audio_base_url=?
               WHERE id=?""",
            (
                f"formationaudio-p{new_platform_id}",
                f"formationpdf-p{new_platform_id}",
                f"formationaudio-p{new_platform_id}-archives",
                slug,
                "",  # à configurer dans Azure ensuite
                new_platform_id,
            )
        )
        conn.commit()
        conn.close()

        logger.info(f"✅ Nouvelle plateforme créée : id={new_platform_id} '{platform_name}'")

        job_id = create_job(
            platform_id=new_platform_id,
            tp_name=tp_name,
            rncp_code=rncp_code,
            total_hours=total_hours,
            nb_days=nb_days,
        )
        logger.info(f"✅ Job formation créé : {job_id} ({tp_name}, {total_hours}h, {nb_days} jours, plateforme {new_platform_id})")
        return jsonify({
            "job_id": job_id,
            "platform_id": new_platform_id,
            "platform_name": platform_name,
            "tp_name": tp_name,
            "rncp_code": rncp_code,
            "total_hours": total_hours,
            "nb_days": nb_days,
            "status": "init",
        }), 201

    except Exception as e:
        logger.error(f"❌ init_formation : {e}")
        return jsonify({"error": str(e)}), 500


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
    """
    Télécharge le REAC PDF depuis France Compétences et en extrait le texte.
    Lance en background (peut prendre ~10s).
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    if job["status"] not in ("init", "error", "reac_ready"):
        return jsonify({"error": f"Impossible de télécharger depuis le statut '{job['status']}'"}), 400

    def _fetch_thread():
        try:
            update_job(job_id, status="reac_fetching")
            rncp_code = job["rncp_code"]

            # Télécharger REAC + RC + ROME en parallèle
            results = {"reac": "", "rc": "", "rome": ""}
            errors = []

            def _dl_reac():
                try:
                    results["reac"] = download_reac_text(rncp_code)
                except Exception as e:
                    errors.append(f"REAC: {e}")

            def _dl_rc():
                try:
                    results["rc"] = download_rc_text(rncp_code)
                except Exception as e:
                    logger.warning(f"⚠️ RC optionnel non disponible : {e}")

            def _dl_rome():
                try:
                    results["rome"] = fetch_rome_data(rncp_code)
                except Exception as e:
                    logger.warning(f"⚠️ ROME optionnel non disponible : {e}")

            threads = [
                threading.Thread(target=_dl_reac, daemon=True),
                threading.Thread(target=_dl_rc, daemon=True),
                threading.Thread(target=_dl_rome, daemon=True),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            if errors:
                raise Exception("; ".join(errors))

            update_job(
                job_id,
                status="reac_ready",
                reac_text=results["reac"],
                rc_text=results["rc"] or None,
                rome_text=results["rome"] or None,
            )
            logger.info(
                f"✅ Job {job_id} : REAC={len(results['reac'])}c "
                f"RC={len(results['rc'])}c ROME={len(results['rome'])}c"
            )
        except Exception as e:
            logger.error(f"❌ Job {job_id} fetch-reac : {e}")
            update_job(job_id, status="error", error_message=str(e))

    threading.Thread(target=_fetch_thread, daemon=True).start()
    return jsonify({"message": "Téléchargement REAC lancé", "status": "reac_fetching"})


# ─── Couche 1 : Enrichissement REAC → Knowledge Base ─────────────────────────

@formation_bp.route("/api/formation/<int:job_id>/enrich-reac", methods=["POST"])
def enrich_reac(job_id):
    """
    Lance la construction de la knowledge base enrichie à partir du REAC.
    Claude extrait les compétences puis les enrichit une par une (définition,
    études de cas, pièges, vocabulaire, contexte terrain, liens connexes).
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    if not job.get("reac_text"):
        return jsonify({"error": "REAC non disponible. Lancez d'abord fetch-reac."}), 400

    if job["status"] not in ("reac_ready", "kb_ready", "error", "kb_building"):
        return jsonify({"error": f"Statut '{job['status']}' invalide pour cette action"}), 400

    data = request.get_json() or {}
    model = data.get("model") or None
    launch_kb_building(job_id, model=model)
    return jsonify({"message": "Construction knowledge base lancée", "status": "kb_building"})


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
    """Lance la génération du programme global depuis le REAC + KB enrichie."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    if not job.get("reac_text"):
        return jsonify({"error": "REAC non disponible. Lancez d'abord fetch-reac."}), 400

    if job["status"] not in ("reac_ready", "kb_ready", "error", "global_ready"):
        return jsonify({"error": f"Statut '{job['status']}' invalide pour cette action"}), 400

    data = request.get_json() or {}
    model = data.get("model") or None
    launch_global_program_generation(job_id, model=model)
    return jsonify({"message": "Génération programme global lancée", "status": "global_generating"})


# ─── Validation programme global ──────────────────────────────────────────────

@formation_bp.route("/api/formation/<int:job_id>/validate-global", methods=["POST"])
def validate_global(job_id):
    """
    Valide (et éventuellement corrige) le programme global.
    Body (optionnel): { "program_text": "...texte édité par l'humain..." }
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    if job["status"] not in ("global_ready", "daily_ready"):
        return jsonify({"error": "Programme global pas encore généré"}), 400

    data = request.get_json() or {}
    edited_program = data.get("program_text")  # None = garder le texte généré

    update_kwargs = {"global_program_validated": 1, "status": "global_validated"}
    if edited_program:
        update_kwargs["global_program"] = edited_program

    update_job(job_id, **update_kwargs)
    logger.info(f"✅ Job {job_id} : programme global validé{' (édité)' if edited_program else ''}")
    return jsonify({"message": "Programme global validé", "status": "global_validated"})


# ─── Découpage en journées ────────────────────────────────────────────────────

@formation_bp.route("/api/formation/<int:job_id>/split-daily", methods=["POST"])
def split_daily(job_id):
    """Lance le découpage du programme global en N journées."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    if not job.get("global_program"):
        return jsonify({"error": "Programme global non disponible"}), 400

    if job["status"] not in ("global_validated", "global_ready", "error", "daily_ready"):
        return jsonify({"error": f"Statut '{job['status']}' invalide pour cette action"}), 400

    data = request.get_json() or {}
    model = data.get("model") or None
    launch_daily_split(job_id, model=model)
    return jsonify({"message": "Découpage journées lancé", "status": "daily_splitting"})


# ─── Validation programmes journée ───────────────────────────────────────────

@formation_bp.route("/api/formation/<int:job_id>/validate-daily", methods=["POST"])
def validate_daily(job_id):
    """
    Valide (et éventuellement corrige) les programmes journée.
    Body (optionnel): { "daily_programs": [...array JSON édité...] }
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    if job["status"] not in ("daily_ready", "daily_validated"):
        return jsonify({"error": "Programmes journée pas encore générés"}), 400

    data = request.get_json() or {}
    edited_programs = data.get("daily_programs")  # None = garder les programmes générés

    import json
    update_kwargs = {"daily_programs_validated": 1, "status": "daily_validated"}
    if edited_programs:
        update_kwargs["daily_programs"] = json.dumps(edited_programs, ensure_ascii=False)

    update_job(job_id, **update_kwargs)
    logger.info(f"✅ Job {job_id} : programmes journée validés{' (édités)' if edited_programs else ''}")
    return jsonify({"message": "Programmes journée validés", "status": "daily_validated"})


# ─── Lancement TTS ────────────────────────────────────────────────────────────

@formation_bp.route("/api/formation/<int:job_id>/launch-tts", methods=["POST"])
def launch_tts(job_id):
    """
    Crée les dossiers cours (un par journée) et lance la génération TTS from scratch.
    Les programmes journée doivent être validés.
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    if not job.get("daily_programs_validated"):
        return jsonify({"error": "Les programmes journée doivent être validés avant de lancer le TTS"}), 400

    if job["status"] == "tts_launched":
        return jsonify({"error": "TTS déjà lancé pour ce job"}), 400

    platform_id = job["platform_id"]
    data = request.get_json() or {}
    model = data.get("model") or None

    try:
        folder_ids = launch_tts_for_all_days(job_id, platform_id, model=model)
        return jsonify({
            "message": f"Génération TTS lancée pour {len(folder_ids)} journées",
            "folder_ids": folder_ids,
            "status": "tts_launched",
        })
    except Exception as e:
        logger.error(f"❌ Job {job_id} launch-tts : {e}")
        return jsonify({"error": str(e)}), 500


# ─── Affinage IA (refine) ─────────────────────────────────────────────────────

@formation_bp.route("/api/formation/<int:job_id>/refine", methods=["POST"])
def refine(job_id):
    """
    Affine un contenu généré via une instruction en langage naturel.
    Body: { content_type: "global"|"daily", instruction: "...", current_content: "...", model: "..." }
    Retourne: { revised_content: "..." }
    Appel synchrone (l'utilisateur attend la réponse).
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    data = request.get_json() or {}
    content_type = data.get("content_type", "global")
    instruction = (data.get("instruction") or "").strip()
    current_content = (data.get("current_content") or "").strip()
    model = data.get("model") or None

    if not instruction:
        return jsonify({"error": "Le champ 'instruction' est requis"}), 400
    if not current_content:
        return jsonify({"error": "Le champ 'current_content' est requis"}), 400

    try:
        from services.formation_pipeline_service import refine_content
        revised = refine_content(
            content_type=content_type,
            current_content=current_content,
            instruction=instruction,
            tp_name=job["tp_name"],
            model=model,
        )
        return jsonify({"revised_content": revised})
    except Exception as e:
        logger.error(f"❌ Job {job_id} refine : {e}")
        return jsonify({"error": str(e)}), 500


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

    from database.db import get_db_connection
    import json as _json

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, name, position FROM cours_folders
           WHERE platform_id = ? ORDER BY position ASC, id ASC""",
        (job["platform_id"],),
    )
    folders = cursor.fetchall()

    daily_programs = _json.loads(job["daily_programs"] or "[]")
    result = []
    for idx, (fid, fname, fpos) in enumerate(folders):
        day_meta = daily_programs[idx] if idx < len(daily_programs) else {}

        cursor.execute(
            """SELECT id, status, total_words, current_sub_part, current_passe, error_message
               FROM content_generation_jobs WHERE folder_id = ?""",
            (fid,),
        )
        cg = cursor.fetchone()
        if cg:
            cg_id, cg_status, cg_words, cur_sub, cur_passe, cg_err = cg
            cursor.execute(
                "SELECT COUNT(*) FROM content_generation_segments WHERE job_id = ? AND status = 'completed'",
                (cg_id,),
            )
            n_completed = cursor.fetchone()[0]
        else:
            cg_status, cg_words, cur_sub, cur_passe, cg_err, n_completed = None, 0, 0, 1, None, 0

        result.append({
            "folder_id": fid,
            "folder_name": fname,
            "position": fpos,
            "day_number": day_meta.get("day_number", idx + 1),
            "day_title": day_meta.get("title", fname),
            "content_status": cg_status,
            "total_words": cg_words or 0,
            "segments_completed": n_completed,
            "segments_total": 18,
            "current_sub_part": cur_sub,
            "current_passe": cur_passe,
            "error_message": cg_err,
        })

    conn.close()
    return jsonify({"folders": result, "job_status": job["status"]})


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


@formation_bp.route("/api/formation/<int:job_id>/content/<int:folder_id>/docx", methods=["GET"])
def download_course_docx(job_id, folder_id):
    """Télécharge le document Word d'une journée de formation (programme officiel)."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    try:
        from services.formation_docx_service import build_course_docx
        docx_bytes, filename = build_course_docx(job_id=job_id, folder_id=folder_id)
        return send_file(
            BytesIO(docx_bytes),
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        logger.error(f"❌ Job {job_id} download_course_docx folder={folder_id} : {e}")
        return jsonify({"error": str(e)}), 500


# ─── Reprise de la génération texte (après crash / restart backend) ──────────

@formation_bp.route("/api/formation/<int:job_id>/resume-content", methods=["POST"])
def resume_content(job_id):
    """
    Relance la génération texte sur tous les dossiers du job qui ne sont pas
    encore 'completed'. Utilise le checkpointing de run_content_generation :
    les segments déjà persistés en DB sont skippés automatiquement. Aucun
    dossier n'est recréé, aucun segment n'est effacé.
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    from database.db import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT f.id, cg.status
           FROM cours_folders f
           LEFT JOIN content_generation_jobs cg ON cg.folder_id = f.id
           WHERE f.platform_id = ? ORDER BY f.position ASC, f.id ASC""",
        (job["platform_id"],),
    )
    rows = cursor.fetchall()
    conn.close()

    to_resume = [fid for fid, status in rows if status != "completed"]
    if not to_resume:
        return jsonify({"message": "Tous les dossiers sont déjà complets", "resumed": []})

    data = request.get_json(silent=True) or {}
    model = data.get("model") or None

    import eventlet
    from services.content_generation_service import run_content_generation

    def _resume_one(folder_id):
        try:
            logger.info(f"♻️ Job {job_id} folder {folder_id} : reprise génération texte")
            run_content_generation(folder_id, mode="normal", model=model)
            logger.info(f"✅ Job {job_id} folder {folder_id} : reprise terminée")
        except Exception as e:
            logger.error(f"❌ Job {job_id} folder {folder_id} : reprise échouée : {e}")

    for fid in to_resume:
        eventlet.spawn(_resume_one, fid)

    logger.info(f"♻️ Job {job_id} : reprise texte pour {len(to_resume)} dossier(s)")
    return jsonify({
        "message": f"Reprise lancée pour {len(to_resume)} dossier(s)",
        "resumed": to_resume,
    })


# ─── Étape 7 : Lancement de la synthèse TTS Fish Audio ───────────────────────

@formation_bp.route("/api/formation/<int:job_id>/launch-audio", methods=["POST"])
def launch_audio(job_id):
    """
    Lance la synthèse audio Fish Audio S2-Pro pour toutes les journées du job.
    Pré-requis : chaque dossier cours doit avoir son content_generation_job en
    status 'completed' (textes générés par Claude). Boucle sur les dossiers et
    spawn un greenlet eventlet par journée qui appelle generate_audio_from_script.
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    from database.db import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT f.id FROM cours_folders f
           WHERE f.platform_id = ? ORDER BY f.position ASC, f.id ASC""",
        (job["platform_id"],),
    )
    folder_ids = [r[0] for r in cursor.fetchall()]

    # Vérifier que tous les dossiers ont leur texte généré
    missing = []
    for fid in folder_ids:
        cursor.execute(
            "SELECT status FROM content_generation_jobs WHERE folder_id = ?",
            (fid,),
        )
        row = cursor.fetchone()
        if not row or row[0] != "completed":
            missing.append(fid)
    conn.close()

    if missing:
        return jsonify({
            "error": f"Textes pas encore prêts pour {len(missing)} dossier(s)",
            "missing_folder_ids": missing,
        }), 400

    data = request.get_json(silent=True) or {}
    force_all = bool(data.get("force_all", False))
    # Mode mock : génère des MP3 de silence 1s au lieu d'appeler Fish Audio.
    # Utile pour tester le flux bout-en-bout sans consommer le budget TTS
    # (cf. generate_audio_from_script → _generate_silence_mp3).
    mock = bool(data.get("mock", False))

    import eventlet
    from services.content_generation_service import generate_audio_from_script

    def _run_audio(folder_id):
        try:
            mode_label = "[MOCK]" if mock else ""
            logger.info(f"🎙️ {mode_label} Job {job_id} folder {folder_id} : synthèse audio démarrée")
            generate_audio_from_script(folder_id, force_all=force_all, mock=mock)
            logger.info(f"✅ {mode_label} Job {job_id} folder {folder_id} : synthèse audio terminée")
        except Exception as e:
            logger.error(f"❌ Job {job_id} folder {folder_id} : synthèse audio échouée : {e}")

    for fid in folder_ids:
        eventlet.spawn(_run_audio, fid)

    update_job(job_id, status="audio_launched")

    # Marquer la plateforme comme 'ready' : le contenu est validé, la synthèse
    # audio tourne en background. Côté HR Dashboard, l'overlay "Module en
    # construction" disparaît dès ce moment — le module est exploitable même
    # si les derniers MP3 finissent de s'uploader (surtout en mode mock où
    # c'est instantané).
    try:
        from database.db import get_db_connection as _get_conn
        _c = _get_conn()
        _cur = _c.cursor()
        _cur.execute(
            "UPDATE platform_config SET status = 'ready' WHERE id = ? AND status = 'pending'",
            (job["platform_id"],),
        )
        _c.commit()
        _c.close()
        logger.info(f"✅ Plateforme {job['platform_id']} : status pending → ready")
    except Exception as e:
        logger.warning(f"⚠️ Impossible de marquer la plateforme ready : {e}")

    mode_suffix = " (MOCK — silence 1s)" if mock else ""
    logger.info(f"🚀 Job {job_id} : synthèse audio lancée pour {len(folder_ids)} dossiers{mode_suffix}")
    return jsonify({
        "message": f"Synthèse audio lancée pour {len(folder_ids)} journées{mode_suffix}",
        "folder_ids": folder_ids,
        "status": "audio_launched",
        "mock": mock,
    })


# ─── Liste des jobs ───────────────────────────────────────────────────────────

@formation_bp.route("/api/formation/list", methods=["GET"])
def list_formations():
    """Liste tous les jobs formation (toutes plateformes)."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    jobs = list_jobs()
    return jsonify({"jobs": jobs})
