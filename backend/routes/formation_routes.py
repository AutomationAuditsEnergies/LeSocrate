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
import os
import threading
import time

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


# ─── Helpers parsing DOCX/TXT pour le mode test ──────────────────────────────

# Sous-parties standard par défaut (6) pour les jobs de test où on n'a pas de
# vrai daily split. Aligné sur le modèle pédagogique 6 sub × 3 passes = 18 segments.
_TEST_SUB_PARTS = [
    "Introduction et contexte professionnel",
    "Les fondamentaux théoriques",
    "Méthodes et outils pratiques",
    "Études de cas et mises en situation",
    "Réglementation et cadre légal",
    "Évaluation et certification",
]


def _read_doc_text(file_storage) -> str:
    """Lit un FileStorage uploadé (.docx ou .txt) et retourne le texte brut."""
    filename = (file_storage.filename or "").lower()
    if filename.endswith(".txt"):
        raw = file_storage.read()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1", errors="ignore")
    if filename.endswith(".docx"):
        from docx import Document
        doc = Document(file_storage)
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    raise ValueError(f"Format de fichier non supporté : {filename} (attendu .docx ou .txt)")


def _split_into_18_chunks(text: str) -> list:
    """Découpe un texte en 18 chunks à peu près équilibrés en paragraphes.

    18 = 6 sous-parties × 3 passes (modèle pédagogique standard du projet).
    Si le texte a moins de 18 paragraphes, on le pad par duplication. Le but
    n'est pas de produire du contenu pédagogique fin (c'est un mode test) mais
    d'avoir 18 segments avec du texte non vide pour que la review et l'audio
    aient quelque chose à mâcher.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) < 18:
        # Pad par duplication cyclique
        paragraphs = (paragraphs * (18 // max(len(paragraphs), 1) + 1))[: max(18, len(paragraphs))]

    chunks = []
    paras_per_chunk = max(1, len(paragraphs) // 18)
    for i in range(18):
        start = i * paras_per_chunk
        end = start + paras_per_chunk if i < 17 else len(paragraphs)
        chunks.append("\n\n".join(paragraphs[start:end]).strip() or paragraphs[i % len(paragraphs)])
    return chunks


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


# ─── Mode test : init avec DOCX pré-injectés (skip génération content) ───────

@formation_bp.route("/api/formation/init-test", methods=["POST"])
def init_test_pipeline():
    """Crée une plateforme + job + folders + segments en mode TEST.

    L'auto-pilot relancé dessus skippera naturellement KB/global/daily/content
    (car tous les artefacts sont déjà en DB) et ne tournera que finalize +
    review + audio + health-check. Permet de valider la pipeline en aval en
    ~5-10 min au lieu de 30-60.

    Multipart form-data :
      - platform_name (str, requis)
      - tp_name (str, requis)
      - rncp_code (str, requis)
      - total_hours (int, requis) — doit être un multiple de 7 (1 doc par 7h)
      - tts_mode (str, optionnel, défaut 'mock')
      - auto_pilot (bool, optionnel, défaut true)
      - docs (files[], requis) — N fichiers .docx ou .txt, où N = total_hours/7

    Retourne 202 avec { job_id, platform_id, nb_days, segments_inserted }.
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    platform_name = (request.form.get("platform_name") or "").strip()
    tp_name = (request.form.get("tp_name") or "").strip()
    rncp_code = (request.form.get("rncp_code") or "").strip()
    total_hours_raw = request.form.get("total_hours") or "0"
    tts_mode = (request.form.get("tts_mode") or "mock").lower()
    auto_pilot = (request.form.get("auto_pilot") or "true").lower() == "true"

    if not platform_name or not tp_name or not rncp_code:
        return jsonify({"error": "platform_name, tp_name, rncp_code sont requis"}), 400
    try:
        total_hours = int(total_hours_raw)
    except ValueError:
        return jsonify({"error": "total_hours doit être un entier"}), 400
    if total_hours <= 0:
        return jsonify({"error": "total_hours doit être > 0"}), 400

    nb_days = math.ceil(total_hours / HOURS_PER_DAY)
    docs = request.files.getlist("docs")
    if len(docs) != nb_days:
        return jsonify({
            "error": f"Tu dois fournir exactement {nb_days} fichier(s) (1 par journée de 7h). Reçu : {len(docs)}",
        }), 400

    try:
        from database.db import get_db_connection
        from datetime import datetime
        from config import FRANCE_TZ
        import json

        # 1. Crée la plateforme (idem init_formation)
        conn = get_db_connection()
        cursor = conn.cursor()
        now_str = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO platform_config (name, upload_locked, updated_at) VALUES (?, 1, ?)",
            (platform_name, now_str),
        )
        platform_id = cursor.lastrowid
        slug = platform_name.lower().replace(" ", "-").replace("_", "-")[:40]
        cursor.execute(
            """UPDATE platform_config
               SET audio_container=?, pdf_container=?, archive_container=?, slug=?, audio_base_url=?
               WHERE id=?""",
            (
                f"formationaudio-p{platform_id}",
                f"formationpdf-p{platform_id}",
                f"formationaudio-p{platform_id}-archives",
                slug, "", platform_id,
            ),
        )
        conn.commit()
        conn.close()
        logger.info(f"🧪 [TEST] Plateforme créée : id={platform_id} '{platform_name}'")

        # 2. Crée le job pipeline avec stubs (REAC mock, global mock, daily mock)
        job_id = create_job(
            platform_id=platform_id, tp_name=tp_name, rncp_code=rncp_code,
            total_hours=total_hours, nb_days=nb_days,
        )

        daily_programs_stub = [
            {
                "day_number": i + 1,
                "title": f"Journée {i+1} (test)",
                "sub_parts": [
                    {"name": sp_name, "module_content": f"Contenu test sous-partie {idx+1}"}
                    for idx, sp_name in enumerate(_TEST_SUB_PARTS)
                ],
                "day_recap": "" if i == 0 else "Lors de la dernière séance, nous avons vu les fondamentaux.",
                "day_transition": "À la prochaine séance, nous aborderons la suite du programme.",
            }
            for i in range(nb_days)
        ]
        update_job(
            job_id,
            reac_text=f"[TEST STUB] REAC mock pour {tp_name} (RNCP {rncp_code})",
            global_program=f"[TEST STUB] Programme global mock pour {tp_name}",
            daily_programs=json.dumps(daily_programs_stub, ensure_ascii=False),
            global_program_validated=1,
            daily_programs_validated=1,
            status="daily_validated",
        )
        logger.info(f"🧪 [TEST] Job pipeline {job_id} créé avec stubs (KB/global/daily seront skippés par l'auto-pilot)")

        # 3. Crée N cours_folders + cg_jobs + 18 segments par cg_job
        conn = get_db_connection()
        cursor = conn.cursor()
        segments_inserted = 0
        for day_idx, doc_file in enumerate(docs):
            day_num = day_idx + 1
            folder_name = f"Jour {day_num} — Journée {day_num} (test)"

            cursor.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM cours_folders WHERE platform_id = ?",
                (platform_id,),
            )
            position = cursor.fetchone()[0]
            cursor.execute(
                "INSERT INTO cours_folders (platform_id, name, position) VALUES (?, ?, ?)",
                (platform_id, folder_name, position),
            )
            folder_id = cursor.lastrowid

            cursor.execute(
                """
                INSERT INTO content_generation_jobs
                    (folder_id, platform_id, program_text, program_title,
                     sub_parts, from_scratch, module_contents,
                     status, current_sub_part, current_passe, total_words, error_message)
                VALUES (?, ?, ?, ?, ?, 1, ?, 'idle', 0, 1, 0, NULL)
                """,
                (
                    folder_id, platform_id,
                    f"[TEST] Programme journée {day_num}", tp_name,
                    json.dumps(_TEST_SUB_PARTS, ensure_ascii=False),
                    json.dumps({sp: f"Contenu test {sp}" for sp in _TEST_SUB_PARTS}, ensure_ascii=False),
                ),
            )
            cg_job_id = cursor.lastrowid

            # Parse le doc + split en 18 chunks
            try:
                full_text = _read_doc_text(doc_file)
            except Exception as e:
                conn.close()
                return jsonify({"error": f"Lecture fichier '{doc_file.filename}' : {e}"}), 400
            chunks_18 = _split_into_18_chunks(full_text)

            # Insère 18 segments (6 sub × 3 passes)
            for sub_idx in range(6):
                for passe in range(1, 4):
                    seg_idx = sub_idx * 3 + (passe - 1)
                    text = chunks_18[seg_idx]
                    word_count = len(text.split())
                    cursor.execute(
                        """
                        INSERT INTO content_generation_segments
                            (job_id, sub_part_index, sub_part_name, passe, status,
                             text_content, word_count, dirty, reviewed, review_error)
                        VALUES (?, ?, ?, ?, 'completed', ?, ?, 1, 0, NULL)
                        """,
                        (
                            cg_job_id, sub_idx, _TEST_SUB_PARTS[sub_idx], passe,
                            text, word_count,
                        ),
                    )
                    segments_inserted += 1

            logger.info(f"🧪 [TEST] Folder {folder_id} (Jour {day_num}) : 18 segments injectés depuis '{doc_file.filename}'")

        conn.commit()
        conn.close()

        # 4. Si auto_pilot demandé, lancer l'auto-pilot en mode Claude Code.
        # Important : même si KB/global/daily/content sont skippés (segments déjà
        # en DB), les étapes en aval CONSOMMENT de l'IA et donc du crédit :
        #   - Volume safety : enrichit les segments < 5000 mots (Claude)
        #   - Review conformité : audit règles #1-#27 par 4 agents multi-rules (Claude)
        # Sans use_claude_code=True, ces appels passent par l'API LLM configurée
        # (DeepSeek ou Anthropic). Avec True, ils utilisent le forfait Pro/Max
        # via subprocess `claude`.
        # tts_mode=mock par défaut pour ne rien payer côté Fish Audio.
        # Modèle SONNET (pas Haiku) : la review et le volume_safety demandent du
        # jugement linguistique fin (fusion de phrases avec "que", transformation
        # discours direct→indirect avec variation lexicale, etc.). Haiku produit
        # des patches mécaniques et parfois cassés ("quimaginez" au lieu de
        # "que vous imaginez"). Le coût est sur le forfait CC, donc gratuit côté API.
        if auto_pilot:
            import eventlet
            # skip_volume_safety=True : on a validé que volume safety multi-passes
            # marche (job 14 a atteint 94k mots). Pour itérer rapidement sur la
            # qualité de la review, on saute volume safety. Chaque test = ~15 min
            # au lieu de 45-60. Si on veut re-tester volume safety, il faudra
            # ajouter un toggle frontend ou faire un job sans skip_volume_safety.
            eventlet.spawn(
                _run_auto_pilot, job_id, tts_mode, "sonnet", True,
                True,  # skip_volume_safety
            )
            logger.info(
                f"🧪 [TEST] Auto-pilot spawné pour job {job_id} "
                f"(tts={tts_mode}, mode=Claude Code Sonnet, "
                f"content+KB/global/daily skippés, volume_safety SKIPPÉ, "
                f"seul review + audio mock + health-check tournent)"
            )

        return jsonify({
            "ok": True,
            "job_id": job_id,
            "platform_id": platform_id,
            "platform_name": platform_name,
            "nb_days": nb_days,
            "segments_inserted": segments_inserted,
            "auto_pilot_started": auto_pilot,
            "tts_mode": tts_mode,
            "test_mode": True,
        }), 202

    except Exception as e:
        logger.error(f"❌ init_test_pipeline : {e}")
        import traceback
        traceback.print_exc()
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
            cursor.execute(
                "SELECT COUNT(*) FROM content_generation_segments "
                "WHERE job_id = ? AND status = 'completed' AND COALESCE(reviewed, 0) = 1",
                (cg_id,),
            )
            n_reviewed = cursor.fetchone()[0]
            # Segments dont la tentative de review a échoué (reviewed=0 ET
            # review_error défini). Comptent comme "traités" pour arrêter
            # le polling frontend, sans mentir sur la conformité.
            cursor.execute(
                "SELECT COUNT(*) FROM content_generation_segments "
                "WHERE job_id = ? AND status = 'completed' "
                "AND COALESCE(reviewed, 0) = 0 AND review_error IS NOT NULL",
                (cg_id,),
            )
            n_review_errors = cursor.fetchone()[0]
        else:
            cg_status, cg_words, cur_sub, cur_passe, cg_err = None, 0, 0, 1, None
            n_completed, n_reviewed, n_review_errors = 0, 0, 0

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
            "segments_reviewed": n_reviewed,
            "segments_review_errors": n_review_errors,
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
    """Télécharge le document Word d'une journée de formation (programme officiel).

    Query param `version` :
    - "current" (défaut) : texte DB actuel (= post-révision si appliquée)
    - "pre_review" : snapshot pris au finalize content (= avant révision)
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    version = request.args.get("version", "current")
    if version not in ("current", "pre_review"):
        return jsonify({"error": f"version invalide : {version}"}), 400

    try:
        from services.formation_docx_service import build_course_docx
        docx_bytes, filename = build_course_docx(
            job_id=job_id, folder_id=folder_id, version=version,
        )
        return send_file(
            BytesIO(docx_bytes),
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        logger.error(f"❌ Job {job_id} download_course_docx folder={folder_id} v={version} : {e}")
        return jsonify({"error": str(e)}), 500


# ─── Rapport de révision conformité ──────────────────────────────────────────

@formation_bp.route(
    "/api/formation/<int:job_id>/content/<int:folder_id>/review-report",
    methods=["GET"],
)
def get_review_report(job_id, folder_id):
    """Retourne le rapport JSON détaillé de la révision conformité pour 1
    journée. Lit `review_queue/job_X/step_review/day_N_review/review_report.json`
    (chunked) ou son équivalent archivé dans `_done/`.

    Format de retour :
    {
      "summary": {segments_reviewed, patches_proposed, patches_applied,
                  patches_rejected, segments_failed},
      "by_rule": {"#22": {proposed, applied, rejected}, ...},
      "by_segment": [{sub_idx, passe, patches_applied, patches_rejected,
                      patches_detail: [{rule, original, replacement,
                                        reason, status, reject_reason?}]}],
      "imported_at", "generated_via", "via_positional_fallback"
    }
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    import os
    import json as _json
    from services.claude_code_mission_service import (
        mission_dir, _DONE_ROOT, _REVIEW_QUEUE_ROOT,
    )

    # Trouver la position du folder pour reconstruire le chunk_id (day_N_review)
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    from database.db import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT position FROM cours_folders WHERE id = ? AND platform_id = ?",
        (folder_id, job["platform_id"]),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Folder introuvable ou hors plateforme"}), 404
    position = row[0]

    # Multi-agents : 1 chunk_dir par groupe de règles. On cherche
    # day_N_review_<group_id> pour chacun, et on agrège les review_report.json.
    # Fallback : day_N_review (legacy single-agent) si trouvé.
    from services.claude_code_mission_service import _REVIEW_RULE_GROUPS
    chunk_id_candidates = (
        [f"day_{position + 1}_review_{g['id']}" for g in _REVIEW_RULE_GROUPS]
        + [f"day_{position + 1}_review"]  # legacy
    )

    if os.path.isdir(_DONE_ROOT):
        archived = sorted(
            (d for d in os.listdir(_DONE_ROOT) if d.endswith(f"-job{job_id}-review")),
            reverse=True,
        )
    else:
        archived = []

    # Collecte tous les review_report.json existants (multi-chunks)
    sub_reports = []
    for cid in chunk_id_candidates:
        paths = [os.path.join(mission_dir(job_id, "review"), cid, "review_report.json")]
        for arch in archived:
            paths.append(os.path.join(_DONE_ROOT, arch, cid, "review_report.json"))
        for p in paths:
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        sub_reports.append((cid, _json.load(f)))
                    break  # 1 seul par chunk_id (le plus récent)
                except Exception:
                    pass

    if sub_reports:
        # Agrégation des sub_reports en un rapport unique
        agg_summary = {
            "segments_reviewed": 0, "patches_proposed": 0,
            "patches_applied": 0, "patches_rejected": 0, "segments_failed": 0,
        }
        agg_by_rule = {}
        agg_by_segment = {}  # clé (sub_idx, passe) → segment agrégé
        any_positional = False
        latest_imported = None
        generated_via = None

        for cid, rep in sub_reports:
            s = rep.get("summary", {})
            for k in agg_summary:
                agg_summary[k] = max(agg_summary[k], s.get(k, 0)) if k == "segments_reviewed" else agg_summary[k] + s.get(k, 0)
            for rule, st in (rep.get("by_rule") or {}).items():
                agg = agg_by_rule.setdefault(rule, {"proposed": 0, "applied": 0, "rejected": 0, "unknown": 0})
                for kk, vv in st.items():
                    agg[kk] = agg.get(kk, 0) + vv
            for seg in (rep.get("by_segment") or []):
                key = (seg.get("sub_idx"), seg.get("passe"))
                if key not in agg_by_segment:
                    agg_by_segment[key] = {
                        "sub_idx": seg.get("sub_idx"),
                        "passe": seg.get("passe"),
                        "segment_id_actual": seg.get("segment_id_actual"),
                        "patches_applied": 0, "patches_rejected": 0,
                        "patches_detail": [],
                    }
                agg_by_segment[key]["patches_applied"] += seg.get("patches_applied", 0)
                agg_by_segment[key]["patches_rejected"] += seg.get("patches_rejected", 0)
                for d in seg.get("patches_detail") or []:
                    d_copy = dict(d)
                    d_copy["agent_group"] = cid.replace(f"day_{position + 1}_review_", "")
                    agg_by_segment[key]["patches_detail"].append(d_copy)
            if rep.get("via_positional_fallback"):
                any_positional = True
            if rep.get("imported_at") and (latest_imported is None or rep["imported_at"] > latest_imported):
                latest_imported = rep["imported_at"]
            if not generated_via:
                generated_via = rep.get("generated_via")

        # by_segment trié par (sub_idx, passe)
        agg_segments = sorted(agg_by_segment.values(), key=lambda x: (x["sub_idx"] or 0, x["passe"] or 0))

        report = {
            "folder_id": folder_id,
            "folder_name": (sub_reports[0][1].get("folder_name") if sub_reports else None),
            "imported_at": latest_imported,
            "generated_via": generated_via,
            "via_positional_fallback": any_positional,
            "n_agents": len(sub_reports),
            "agents_used": [cid.replace(f"day_{position + 1}_review_", "") for cid, _ in sub_reports],
            "summary": agg_summary,
            "by_rule": agg_by_rule,
            "by_segment": agg_segments,
        }
        return jsonify({"report": report, "n_sub_reports": len(sub_reports)}), 200

    # Fallback : pas de review_report.json mais peut-être un output.md
    # existant d'un import antérieur (avant que je code l'écriture du
    # rapport). On reconstitue un rapport "best-effort" depuis output.md +
    # input.md + DB actuelle (heuristique : un patch est "appliqué" si son
    # replacement est dans le texte courant et son original n'y est plus).
    # Cherche dans tous les chunk_id candidats (multi-agents + legacy).
    output_md_paths = []
    for cid in chunk_id_candidates:
        output_md_paths.append(
            os.path.join(mission_dir(job_id, "review"), cid, "output.md")
        )
        for arch in archived:
            output_md_paths.append(
                os.path.join(_DONE_ROOT, arch, cid, "output.md")
            )

    chunk_dir_with_output = None
    for p in output_md_paths:
        if os.path.exists(p):
            chunk_dir_with_output = os.path.dirname(p)
            break

    if not chunk_dir_with_output:
        return jsonify({
            "error": "Aucun rapport de révision trouvé pour ce dossier",
            "report": None,
        }), 404

    try:
        with open(os.path.join(chunk_dir_with_output, "output.md"), "r", encoding="utf-8") as f:
            output_text = f.read()
        from services.claude_code_mission_service import _extract_json
        parsed = _json.loads(_extract_json(output_text))
        reviews = parsed.get("reviews", [])
    except Exception as e:
        return jsonify({"error": f"output.md illisible : {e}"}), 500

    # Récupère input.md (segments d'origine) pour la résolution positionnelle
    input_md_path = os.path.join(chunk_dir_with_output, "input.md")
    input_segments = []
    if os.path.exists(input_md_path):
        try:
            with open(input_md_path, "r", encoding="utf-8") as f:
                input_segments = _json.loads(f.read())
        except Exception:
            input_segments = []

    # Récupère les textes actuels en DB (résolution par sub_idx, passe via folder)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT s.id, s.sub_part_index, s.passe, s.text_content
        FROM content_generation_segments s
        JOIN content_generation_jobs cj ON cj.id = s.job_id
        WHERE cj.folder_id = ? AND s.status = 'completed'
        ORDER BY cj.id DESC, s.sub_part_index ASC, s.passe ASC
        """,
        (folder_id,),
    )
    db_rows = cursor.fetchall()
    conn.close()
    # Map (sub_idx, passe) → text actuel (le plus récent en cas de doublons)
    db_text_by_sp = {}
    for r in db_rows:
        key = (r[1], r[2])
        if key not in db_text_by_sp:
            db_text_by_sp[key] = (r[0], r[3])

    # Construction du rapport lite
    by_rule = {}
    by_segment = []
    applied_total = 0
    rejected_total = 0
    unknown_total = 0

    for i, rev in enumerate(reviews):
        patches = rev.get("patches", []) or []
        # Résolution positionnelle via input.md
        if i < len(input_segments):
            sub_idx = input_segments[i].get("sub_idx", -1)
            passe = input_segments[i].get("passe", -1)
        else:
            sub_idx = -1
            passe = -1
        seg_db = db_text_by_sp.get((sub_idx, passe))
        current_text = seg_db[1] if seg_db else ""
        actual_segment_id = seg_db[0] if seg_db else None

        seg_applied = 0
        seg_rejected = 0
        seg_unknown = 0
        seg_patches_detail = []
        for p in patches[:5]:
            original = (p.get("original") or "")[:1000]
            replacement = (p.get("replacement") or "")[:1000]
            rule = str(p.get("rule_violated", "?"))[:10]
            reason = str(p.get("reason", ""))[:200]
            if not original or not replacement:
                continue
            rule_stat = by_rule.setdefault(rule, {"proposed": 0, "applied": 0, "rejected": 0, "unknown": 0})
            rule_stat["proposed"] += 1
            # Heuristique
            if current_text:
                has_repl = replacement in current_text
                has_orig = original in current_text
                if has_repl and not has_orig:
                    status = "applied"
                    seg_applied += 1
                    rule_stat["applied"] += 1
                elif has_orig:
                    status = "rejected"
                    seg_rejected += 1
                    rule_stat["rejected"] += 1
                else:
                    status = "unknown"
                    seg_unknown += 1
                    rule_stat["unknown"] += 1
            else:
                status = "unknown"
                seg_unknown += 1
                rule_stat["unknown"] += 1
            seg_patches_detail.append({
                "rule": rule, "reason": reason,
                "original": original[:200], "replacement": replacement[:200],
                "status": status,
                "reject_reason": "détecté heuristiquement" if status == "rejected" else None,
            })

        applied_total += seg_applied
        rejected_total += seg_rejected
        unknown_total += seg_unknown

        by_segment.append({
            "sub_idx": sub_idx,
            "passe": passe,
            "segment_id_actual": actual_segment_id,
            "patches_applied": seg_applied,
            "patches_rejected": seg_rejected,
            "patches_unknown": seg_unknown,
            "patches_detail": seg_patches_detail,
        })

    report = {
        "folder_id": folder_id,
        "folder_name": None,  # pas dispo en mode reconstruit
        "imported_at": None,
        "generated_via": "reconstructed_from_output_md",
        "is_reconstructed": True,
        "reconstruction_note": (
            "Rapport reconstitué a posteriori depuis output.md + DB actuelle. "
            "Statuts applied/rejected déduits par heuristique (replacement "
            "présent dans le texte = appliqué, original encore présent = rejeté). "
            "Précision approximative."
        ),
        "summary": {
            "segments_reviewed": len(reviews),
            "patches_proposed": sum(len(r.get("patches", [])) for r in reviews),
            "patches_applied": applied_total,
            "patches_rejected": rejected_total,
            "patches_unknown": unknown_total,
            "segments_failed": 0,
        },
        "by_rule": by_rule,
        "by_segment": by_segment,
    }
    return jsonify({"report": report, "source_path": chunk_dir_with_output, "lite": True}), 200


# ─── Étape 6.5 — Sécurité volume (audit + enrichissement à la demande) ───────

@formation_bp.route("/api/formation/<int:job_id>/volume-audit", methods=["GET"])
def volume_audit(job_id):
    """Retourne l'audit volume par-folder pour un job.

    Pour chaque folder du job, calcule :
      - total_words : SUM(word_count) des segments completed
      - deficit : max(0, 90000 - total_words)
      - shortest_segments : top N (5) des segments les plus courts (pour
        l'affichage UI et le ciblage de l'enrichissement)

    Pas d'effet de bord — purement lecture.
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    from services.claude_code_mission_service import compute_volume_audit
    try:
        audit = compute_volume_audit(job_id)
        return jsonify(audit), 200
    except Exception as e:
        logger.error(f"❌ volume_audit job {job_id} : {e}")
        return jsonify({"error": str(e)}), 500


@formation_bp.route(
    "/api/formation/<int:job_id>/content/<int:folder_id>/volume-safety",
    methods=["POST"],
)
def launch_volume_safety(job_id, folder_id):
    """Lance l'enrichissement des segments les plus courts d'un folder pour
    atteindre le seuil de 90 000 mots/journée.

    Body JSON :
      - "model": "sonnet"|"haiku" — défaut "sonnet"
      - "mode": "api"|"cc" — défaut "cc". "api" utilise l'API Anthropic
        (consomme la clé), "cc" utilise subprocess `claude` (forfait local).

    Append-only : le texte original n'est jamais réécrit. Le snapshot
    pre_review reste valide.

    Greenlet en background (eventlet) — la route retourne immédiatement
    avec un status 202 et le client peut poller `/volume-audit` pour suivre.
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    from services.claude_code_mission_service import (
        local_dev_enabled, ALLOWED_MODELS, run_volume_safety,
        run_volume_safety_api, _EXECUTION_STATE,
    )

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    payload = request.get_json(silent=True) or {}
    mode = (payload.get("mode") or "cc").lower()
    if mode not in ("api", "cc"):
        return jsonify({"error": f"mode invalide (autorisés : api, cc)"}), 400

    # Mode CC : nécessite LOCAL_DEV + claude binary. Mode API : juste la clé.
    if mode == "cc" and not local_dev_enabled():
        return jsonify({"error": "LOCAL_DEV requis pour le mode CC. Utilise mode='api'."}), 403

    if mode == "cc":
        model = (payload.get("model") or "sonnet").lower()
        if model not in ALLOWED_MODELS:
            return jsonify({"error": f"model invalide (autorisés : {sorted(ALLOWED_MODELS)})"}), 400
    else:
        # Mode API : on accepte le model ID complet ou un raccourci
        raw = (payload.get("model") or "sonnet").lower()
        if raw == "haiku":
            model = "claude-haiku-4-5-20251001"
        elif raw == "sonnet":
            model = None  # défaut FORMATION_LLM_MODEL côté service
        elif raw == "flash":
            model = "deepseek-v4-flash"
        elif raw == "pro":
            model = "deepseek-v4-pro"
        else:
            model = payload.get("model")  # ID complet passé tel quel

    state_key = (job_id, f"volume_safety_{folder_id}")
    if _EXECUTION_STATE.get(state_key, {}).get("status") == "running":
        return jsonify({"error": "Une opération volume safety est déjà en cours pour ce dossier"}), 409

    _EXECUTION_STATE[state_key] = {"status": "running", "model": str(model), "mode": mode}

    import eventlet

    def _run():
        try:
            if mode == "api":
                result = run_volume_safety_api(job_id, folder_id, model=model)
            else:
                result = run_volume_safety(job_id, folder_id, model=model)
            _EXECUTION_STATE[state_key] = {
                "status": "done",
                "model": str(model),
                "mode": mode,
                "result": result,
            }
            logger.info(
                f"📏 Volume safety [{mode}] terminé pour job {job_id}/folder {folder_id} : "
                f"{len(result.get('enriched', []))} segments enrichis"
            )
        except Exception as e:
            logger.error(f"❌ Volume safety [{mode}] job {job_id}/folder {folder_id} : {e}")
            _EXECUTION_STATE[state_key] = {
                "status": "error",
                "model": str(model),
                "mode": mode,
                "error": str(e)[:500],
            }

    eventlet.spawn(_run)
    return jsonify({"ok": True, "status": "running", "model": str(model), "mode": mode}), 202


@formation_bp.route(
    "/api/formation/<int:job_id>/content/<int:folder_id>/volume-safety/status",
    methods=["GET"],
)
def volume_safety_status(job_id, folder_id):
    """Récupère l'état de la dernière exécution volume safety pour ce folder.

    Retourne {status: 'idle'|'running'|'done'|'error', model?, result?, error?}.
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    from services.claude_code_mission_service import _EXECUTION_STATE
    state = _EXECUTION_STATE.get((job_id, f"volume_safety_{folder_id}"))
    if not state:
        return jsonify({"status": "idle"}), 200
    return jsonify(state), 200


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


# ─── Étape 6bis : Révision conformité via reviewer API Claude ────────────────
# Phase 1 de memoire/03-decisions/pipeline-dual-api-et-claude-code.md
# Scope strict : API uniquement, pas de refonte UI double colonne ici.

@formation_bp.route(
    "/api/formation/<int:job_id>/content/<int:folder_id>/review",
    methods=["POST"],
)
def review_content(job_id, folder_id):
    """
    Lance la révision conformité du texte généré pour un dossier cours.
    Boucle sur les segments `status='completed' AND reviewed=0`, appelle
    Claude reviewer, applique les patches unique-match et marque `reviewed=1`.
    Idempotent : relancer ne refait rien sur des segments déjà reviewed.
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job pipeline introuvable"}), 404

    # Vérifier que le folder appartient bien à la plateforme du job
    from database.db import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT platform_id FROM cours_folders WHERE id = ?",
        (folder_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row or row[0] != job["platform_id"]:
        return jsonify({"error": "Folder inexistant ou hors plateforme"}), 404

    data = request.get_json(silent=True) or {}
    model = data.get("model") or None  # None → CLAUDE_MODEL par défaut (Sonnet)

    import eventlet
    from services.content_generation_service import run_content_review

    def _run_review(_folder_id):
        import sys, traceback
        logger.info(f"🚀 SPAWN review greenlet job={job_id} folder={_folder_id} model={model}")
        sys.stdout.flush()
        try:
            result = run_content_review(_folder_id, model=model)
            logger.info(
                f"✅ Review job={job_id} folder={_folder_id} : "
                f"{result['segments_reviewed']} audités, "
                f"{result['patches_applied']} appliqués, "
                f"{result['patches_rejected']} rejetés"
            )
            sys.stdout.flush()
        except Exception as e:
            logger.error(f"❌ Review job={job_id} folder={_folder_id} : échec : {e}")
            logger.error(traceback.format_exc())
            sys.stdout.flush()

    eventlet.spawn(_run_review, folder_id)

    return jsonify({
        "message": "Révision conformité lancée en arrière-plan",
        "folder_id": folder_id,
        "model": model or "default (Sonnet)",
    }), 202


# ─── Missions Claude Code local (Phase 3) ────────────────────────────────────
# Export/import manuel de tâches à faire dans `claude --model haiku|sonnet`.
# Gating : nécessite LOCAL_DEV=true côté backend. Spec complète :
# memoire/03-decisions/pipeline-dual-api-et-claude-code.md

@formation_bp.route(
    "/api/formation/<int:job_id>/missions/<string:step_key>/export",
    methods=["POST"],
)
def export_claude_code_mission(job_id, step_key):
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403
    from services.claude_code_mission_service import (
        export_mission, local_dev_enabled,
    )
    if not local_dev_enabled():
        return jsonify({"error": "LOCAL_DEV non activé — fonctionnalité dev uniquement"}), 403
    data = request.get_json(silent=True) or {}
    model = data.get("model", "haiku")
    try:
        mission = export_mission(job_id, step_key, model)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except (ValueError, FileNotFoundError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"❌ export_claude_code_mission : {e}")
        return jsonify({"error": str(e)}), 500
    return jsonify({"mission": mission}), 201


@formation_bp.route(
    "/api/formation/<int:job_id>/missions/<string:step_key>/import",
    methods=["POST"],
)
def import_claude_code_mission(job_id, step_key):
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403
    from services.claude_code_mission_service import (
        import_mission_result, local_dev_enabled,
    )
    if not local_dev_enabled():
        return jsonify({"error": "LOCAL_DEV non activé — fonctionnalité dev uniquement"}), 403
    try:
        result = import_mission_result(job_id, step_key)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 400
    except NotImplementedError as e:
        # Étapes kb / content : parsers non implémentés en V1. On renvoie un
        # vrai 501 pour que le frontend affiche l'erreur et ne supprime pas
        # la mission de la file (cf. audit point #2).
        return jsonify({"error": str(e), "not_implemented": True}), 501
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"❌ import_claude_code_mission : {e}")
        return jsonify({"error": str(e)}), 500
    return jsonify(result), 200


@formation_bp.route(
    "/api/formation/<int:job_id>/missions/<string:step_key>/execute",
    methods=["POST"],
)
def execute_claude_code_mission(job_id, step_key):
    """Lance `claude -p` en subprocess (greenlet eventlet) + import auto à la fin.
    Dev local only (LOCAL_DEV=true côté backend ET `claude` dans le PATH)."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403
    from services.claude_code_mission_service import (
        execute_mission_locally, local_dev_enabled,
    )
    if not local_dev_enabled():
        return jsonify({"error": "LOCAL_DEV non activé — fonctionnalité dev uniquement"}), 403
    data = request.get_json(silent=True) or {}
    model = data.get("model", "haiku")

    # État partagé de l'exécution par (job_id, step_key) — mis à jour par le
    # greenlet et lu par le polling frontend via /missions/pending.
    import eventlet
    from services.claude_code_mission_service import _EXECUTION_STATE

    key = (job_id, step_key)
    if _EXECUTION_STATE.get(key, {}).get("status") == "running":
        return jsonify({"error": "Une exécution est déjà en cours pour cette étape"}), 409

    _EXECUTION_STATE[key] = {"status": "running", "model": model, "error": None, "result": None}

    def _run():
        import sys, traceback
        try:
            logger.info(f"🤖 Exec Claude Code : job={job_id} step={step_key} model={model}")
            sys.stdout.flush()
            result = execute_mission_locally(job_id, step_key, model)
            _EXECUTION_STATE[key] = {"status": "done", "model": model, "error": None, "result": result}
            logger.info(f"✅ Exec Claude Code terminée : job={job_id} step={step_key}")
            sys.stdout.flush()
        except Exception as e:
            logger.error(f"❌ Exec Claude Code échouée : job={job_id} step={step_key} : {e}")
            logger.error(traceback.format_exc())
            _EXECUTION_STATE[key] = {"status": "error", "model": model, "error": str(e)[:500], "result": None}
            sys.stdout.flush()

    eventlet.spawn(_run)
    return jsonify({"status": "running", "step_key": step_key, "model": model}), 202


@formation_bp.route(
    "/api/formation/<int:job_id>/missions/<string:step_key>/logs",
    methods=["GET"],
)
def get_claude_code_mission_logs(job_id, step_key):
    """Retourne les N dernières lignes du execution.log de la mission.
    Cherche dans review_queue/job_X/step_Y/ d'abord, puis dans _done/ en
    fallback pour les missions déjà importées et archivées."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403
    from services.claude_code_mission_service import (
        mission_dir, _DONE_ROOT, local_dev_enabled,
    )
    import os
    if not local_dev_enabled():
        return jsonify({"logs": "", "source": "disabled"}), 200

    tail_n = int(request.args.get("tail", 200))
    # Chemin actuel
    active = os.path.join(mission_dir(job_id, step_key), "execution.log")
    # Fallback : chercher le dernier _done correspondant
    archive_path = None
    if os.path.isdir(_DONE_ROOT):
        candidates = sorted(
            (d for d in os.listdir(_DONE_ROOT) if d.endswith(f"-job{job_id}-{step_key}")),
            reverse=True,
        )
        if candidates:
            archive_path = os.path.join(_DONE_ROOT, candidates[0], "execution.log")

    source = None
    path = None
    if os.path.exists(active):
        path, source = active, "active"
    elif archive_path and os.path.exists(archive_path):
        path, source = archive_path, "archived"

    if not path:
        return jsonify({"logs": "", "source": "not_found"}), 200

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        tail = "".join(lines[-tail_n:])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "logs": tail,
        "source": source,
        "total_lines": len(lines),
        "returned_lines": min(tail_n, len(lines)),
    }), 200


@formation_bp.route("/api/formation/<int:job_id>/missions/pending", methods=["GET"])
def list_claude_code_pending_missions(job_id):
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403
    from services.claude_code_mission_service import (
        list_pending_missions, local_dev_enabled,
    )
    if not local_dev_enabled():
        return jsonify({"missions": {}}), 200
    return jsonify({"missions": list_pending_missions(job_id)}), 200


# ─── Pre-flight et health-check (audit pipeline) ─────────────────────────────

@formation_bp.route("/api/formation/<int:job_id>/preflight", methods=["POST"])
def preflight_pipeline(job_id):
    """Audit AVANT lancement : valide que la pipeline a les chances de tourner
    one-shot (config + connectivité externe). Body :
      { "use_claude_code": bool, "tts_mode": "fish_audio"|"gtts"|"mock" }
    Retourne :
      { "ok": bool, "blocking": [...], "warnings": [...], "checks": {...} }
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403
    payload = request.get_json(silent=True) or {}
    use_cc = bool(payload.get("use_claude_code", False))
    tts_mode = (payload.get("tts_mode") or "gtts").lower()
    try:
        from services.formation_health_service import compute_preflight
        result = compute_preflight(job_id, use_claude_code=use_cc, tts_mode=tts_mode)
        return jsonify(result), 200 if result["ok"] else 422
    except Exception as e:
        logger.error(f"❌ preflight job {job_id} : {e}")
        return jsonify({"error": str(e)}), 500


@formation_bp.route("/api/formation/<int:job_id>/health", methods=["GET"])
def health_pipeline(job_id):
    """Audit APRÈS lancement : vérifie que la pipeline a produit des artefacts
    cohérents (segments, DOCX, snapshots, audio, module persistant).
    Retourne :
      { "ok": bool, "blocking": [...], "warnings": [...], "checks": {...} }
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403
    try:
        from services.formation_health_service import compute_health
        result = compute_health(job_id)
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"❌ health-check job {job_id} : {e}")
        return jsonify({"error": str(e)}), 500


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
    # force_all=True par défaut au lancement initial : les segments fraîchement
    # générés ont dirty=0, donc sans force_all, generate_audio_from_script
    # skipperait tous les blocs ("non modifiés, conservés") et aucun MP3 ne
    # serait produit. force_all=True garantit la 1re synthèse complète. Les
    # régénérations partielles ultérieures (via édition segment) utilisent le
    # dirty flag naturellement.
    force_all = bool(data.get("force_all", True))
    # 3 modes de synthèse audio (priorité décroissante) :
    # - mock=True      → MP3 silence 1s, test gratuit
    # - basic_tts=True → gTTS (Google, voix basique gratuite)
    # - (défaut)       → Fish Audio S2-Pro (voix studio payante)
    mock = bool(data.get("mock", False))
    basic_tts = bool(data.get("basic_tts", False))
    if mock and basic_tts:
        return jsonify({"error": "mock et basic_tts sont mutuellement exclusifs"}), 400

    import eventlet
    from services.content_generation_service import generate_audio_from_script

    def _run_audio(folder_id):
        import sys, traceback
        mode_label = "[MOCK]" if mock else "[gTTS]" if basic_tts else ""
        logger.info(f"🚀 SPAWN greenlet job={job_id} folder={folder_id} mock={mock} basic_tts={basic_tts} force_all={force_all}")
        sys.stdout.flush()
        try:
            logger.info(f"🎙️ {mode_label} Job {job_id} folder {folder_id} : synthèse audio démarrée")
            sys.stdout.flush()
            generate_audio_from_script(folder_id, force_all=force_all, mock=mock, basic_tts=basic_tts)
            logger.info(f"✅ {mode_label} Job {job_id} folder {folder_id} : synthèse audio terminée")
            sys.stdout.flush()
        except Exception as e:
            logger.error(f"❌ Job {job_id} folder {folder_id} : synthèse audio échouée : {e}")
            logger.error(traceback.format_exc())
            sys.stdout.flush()
            try:
                update_job(job_id, status="audio_error", error_message=f"folder {folder_id}: {str(e)[:500]}")
            except Exception as ue:
                logger.error(f"❌ Impossible de marquer job {job_id} en audio_error : {ue}")

    # Synthèse audio SÉQUENTIELLE entre journées (pas parallèle).
    # Raison : pour gTTS et Fish Audio, lancer plusieurs folders en parallèle
    # multiplie les requêtes simultanées vers l'API tierce → rate limit (429)
    # immédiat. On séquentialise via 1 seul greenlet qui itère.
    def _run_all_audios_sequential():
        for fid in folder_ids:
            _run_audio(fid)
            # Petit cooldown entre folders pour aérer le rate limit côté
            # API tierce. Configurable, surtout utile pour gTTS.
            import time as _t
            cooldown = int(os.getenv("AUDIO_COOLDOWN_BETWEEN_FOLDERS_SEC", "30"))
            if cooldown > 0:
                logger.info(f"⏸ Cooldown {cooldown}s avant folder suivant")
                _t.sleep(cooldown)

    eventlet.spawn(_run_all_audios_sequential)

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

    # Auto-création du module persistant (idempotent via UNIQUE constraint sur
    # source_pipeline_job_id). Principe "1 RNCP = 1 module durable" : ce module
    # devient sélectionnable dans la modale "Nouvelle plateforme" pour créer
    # les futures promos sans re-lancer la pipeline.
    #
    # voice_type trace la voix TTS qui a produit les MP3 du module. À chaque
    # relance de l'étape 7 avec une voix différente, le champ est UPDATE.
    # Les MP3 dans Azure (clé = platform_id/folder_id/filename) sont écrasés
    # par le nouveau run, donc le module pointe automatiquement vers les
    # nouveaux audios — voice_type reflète ce changement de manière persistante.
    voice_type = "mock" if mock else ("gtts" if basic_tts else "fish_audio")
    try:
        from database.db import get_db_connection as _gc
        from datetime import datetime as _dt
        from config import FRANCE_TZ as _tz
        _c2 = _gc()
        _cur2 = _c2.cursor()
        year = _dt.now(_tz).year
        rncp = job.get("rncp_code") or ""
        _cur2.execute("SELECT COUNT(*) FROM formation_modules WHERE rncp_code = ?", (rncp,))
        n = _cur2.fetchone()[0] + 1
        version = f"{year}-v{n}"
        _cur2.execute("""
            INSERT OR IGNORE INTO formation_modules
            (rncp_code, tp_name, version, status, source_pipeline_job_id,
             source_platform_id, voice_type, voice_updated_at, validated_at)
            VALUES (?, ?, ?, 'validated', ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (rncp, job["tp_name"], version, job_id, job["platform_id"], voice_type))
        if _cur2.rowcount > 0:
            logger.info(
                f"📦 Module créé : {job['tp_name']} {version} (job {job_id}) "
                f"voix={voice_type}"
            )
        else:
            # Module déjà existant — relance TTS avec une voix possiblement
            # différente. On UPDATE voice_type pour refléter les MP3 actuels.
            _cur2.execute(
                """UPDATE formation_modules
                   SET voice_type = ?, voice_updated_at = CURRENT_TIMESTAMP
                   WHERE source_pipeline_job_id = ?""",
                (voice_type, job_id),
            )
            logger.info(
                f"♻️ Module mis à jour pour job {job_id} : voix={voice_type} "
                f"(les MP3 Azure sont écrasés en place)"
            )
        _c2.commit()
        _c2.close()
    except Exception as e:
        logger.warning(f"⚠️ Création/MAJ module échouée : {e}")

    if mock:
        mode_suffix = " (MOCK — silence 1s)"
    elif basic_tts:
        mode_suffix = " (gTTS — voix basique gratuite)"
    else:
        mode_suffix = ""
    logger.info(f"🚀 Job {job_id} : synthèse audio lancée pour {len(folder_ids)} dossiers{mode_suffix}")
    return jsonify({
        "message": f"Synthèse audio lancée pour {len(folder_ids)} journées{mode_suffix}",
        "folder_ids": folder_ids,
        "status": "audio_launched",
        "mock": mock,
        "basic_tts": basic_tts,
    })


# ─── Liste des jobs ───────────────────────────────────────────────────────────

@formation_bp.route("/api/formation/list", methods=["GET"])
def list_formations():
    """Liste tous les jobs formation (toutes plateformes)."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    jobs = list_jobs()
    return jsonify({"jobs": jobs})


# ─── Auto-pilot pipeline (Phase C) ────────────────────────────────────────────
#
# Enchaîne automatiquement les étapes du pipeline pour simuler l'expérience
# finale de l'utilisateur (qui ne valide pas chaque étape à la main).
# Stop-on-error : si une étape plante, le job conserve son statut error et
# l'auto-pilot s'arrête. L'utilisateur peut reprendre manuellement dans
# l'onglet Formation Pipeline.
#
# État partagé pour le polling UI : _AUTO_PILOT_STATE[(job_id)] = {step, status,
# error?, started_at, ...}.

_AUTO_PILOT_STATE = {}


def _run_auto_pilot(job_id: int, tts_mode: str, model: str,
                    use_claude_code: bool = False,
                    skip_volume_safety: bool = False) -> None:
    """Greenlet qui orchestre tout le pipeline. Stop-on-error.

    Si `use_claude_code=True`, les étapes API (KB, global, daily, content) sont
    exécutées via subprocess Claude Code local (forfait Pro/Max) au lieu des
    appels API Anthropic à la carte. Économise les crédits API quand le
    compte est bas. L'étape audio TTS reste hors-CC (mock/gtts/fish_audio).
    """
    import eventlet
    from services.content_generation_service import (
        run_content_generation, generate_audio_from_script,
    )
    from database.db import get_db_connection

    # Mapping modèle :
    # - api_model : ID complet pour les services API
    #   (claude-haiku-4-5-20251001 ou None=défaut FORMATION_LLM_MODEL)
    # - cc_model : raccourci CLI Claude Code ("haiku"/"sonnet")
    if model == "haiku":
        api_model = "claude-haiku-4-5-20251001"
        cc_model = "haiku"
    elif model == "flash":
        api_model = "deepseek-v4-flash"
        cc_model = "sonnet"
    elif model == "pro":
        api_model = "deepseek-v4-pro"
        cc_model = "sonnet"
    else:
        api_model = None  # défaut via FORMATION_LLM_MODEL / FORMATION_CLAUDE_MODEL
        cc_model = "sonnet"

    poll_interval = 3
    # Cap large pour KB et content (les plus longs). Le polling lit le statut
    # — il ne tourne pas dans le vide, c'est juste un timeout de sécurité.
    max_wait_kb = 3600
    max_wait_global = 600
    max_wait_daily = 600
    max_wait_content = 14400  # 4h max pour content (90k mots × N journées)

    def _set_step(step, **kw):
        st = _AUTO_PILOT_STATE.setdefault(job_id, {})
        st["step"] = step
        st["updated_at"] = time.time()
        for k, v in kw.items():
            st[k] = v

    def _wait_for(target_statuses, max_wait):
        elapsed = 0
        while elapsed < max_wait:
            j = get_job(job_id)
            if not j:
                raise RuntimeError("Job introuvable")
            s = j["status"]
            if s in target_statuses:
                return j
            if s in ("error", "audio_error"):
                raise RuntimeError(f"Pipeline en erreur : {j.get('error_message') or s}")
            eventlet.sleep(poll_interval)
            elapsed += poll_interval
        raise TimeoutError(f"Timeout après {max_wait}s en attendant {target_statuses}")

    try:
        _set_step("start", status="running", started_at=time.time(),
                  tts_mode=tts_mode, model=model,
                  use_claude_code=use_claude_code, error=None)
        logger.info(
            f"🤖 Auto-pilot start job={job_id} tts={tts_mode} model={model} "
            f"use_claude_code={use_claude_code}"
        )

        # Pre-flight : valide la config et la connectivité externe AVANT de
        # toucher quoi que ce soit. Si bloquant, on s'arrête net avec un
        # message clair plutôt que de planter à mi-chemin avec un état partiel.
        from services.formation_health_service import compute_preflight
        preflight = compute_preflight(job_id, use_claude_code=use_claude_code, tts_mode=tts_mode)
        _set_step("start", preflight=preflight)
        if not preflight["ok"]:
            blocking_str = ", ".join(preflight["blocking"])
            details = "; ".join(
                f"{k}={preflight['checks'].get(k, {}).get('detail', '?')}"
                for k in preflight["blocking"]
            )
            raise RuntimeError(
                f"Pre-flight bloqué — checks fatals : {blocking_str}. {details}"
            )
        logger.info(f"🛂 Pre-flight OK pour job {job_id} (warnings={preflight['warnings']})")

        # Reset du statut si reprise après échec : l'auto-pilot va revérifier
        # quelle étape n'est pas faite et reprendre. On nettoie aussi
        # error_message pour ne pas garder une trace stale.
        j0 = get_job(job_id)
        if j0 and j0["status"] in ("error", "audio_error"):
            # Déduire un statut "propre" depuis les champs concrets du job.
            if (j0.get("daily_programs_validated") or 0):
                fallback = "daily_validated"
            elif j0.get("global_program_validated"):
                fallback = "global_validated"
            elif j0.get("global_program"):
                fallback = "global_ready"
            elif (j0.get("kb_total") or 0) > 0:
                fallback = "kb_ready"
            elif j0.get("reac_text"):
                fallback = "reac_ready"
            else:
                fallback = "init"
            update_job(job_id, status=fallback, error_message=None)
            logger.info(f"🤖 Reset statut error → {fallback} pour reprise job {job_id}")

        # ─── 1. REAC ─────────────────────────────────────────────────────────
        j = get_job(job_id)
        if not j.get("reac_text"):
            _set_step("reac")
            update_job(job_id, status="reac_fetching")
            try:
                reac = download_reac_text(j["rncp_code"])
            except Exception as e:
                update_job(job_id, status="error", error_message=f"REAC : {e}")
                raise
            rc_text = None
            rome_text = None
            try:
                rc_text = download_rc_text(j["rncp_code"]) or None
            except Exception:
                pass
            try:
                rome_text = fetch_rome_data(j["rncp_code"]) or None
            except Exception:
                pass
            update_job(job_id, status="reac_ready", reac_text=reac,
                       rc_text=rc_text, rome_text=rome_text)
            logger.info(f"🤖 ✓ REAC téléchargé pour job {job_id}")

        # Helper : lance l'étape via Claude Code subprocess (synchrone) si
        # use_claude_code=True, sinon via les services API Anthropic.
        from services.claude_code_mission_service import execute_mission_locally

        # ─── 2. KB ───────────────────────────────────────────────────────────
        # Skip KB si déjà construite (kb_stats.completed > 0 ou statut > kb_ready)
        j = get_job(job_id)
        kb_already_done = False
        try:
            from services.knowledge_base_service import kb_stats as _kb_stats
            stats = _kb_stats(job_id)
            kb_already_done = (stats.get("completed", 0) > 0)
        except Exception:
            pass
        # Bonus : si statut déjà au-delà de kb_ready, on est sûr que KB est faite
        if j.get("status") in ("global_ready", "global_validated", "daily_ready",
                               "daily_validated", "tts_launched", "audio_launched"):
            kb_already_done = True

        if not kb_already_done:
            _set_step("kb")
            if use_claude_code:
                execute_mission_locally(job_id, "kb", cc_model)
                # _import_kb passe le job en kb_ready directement
            else:
                launch_kb_building(job_id, model=api_model)
                _wait_for({"kb_ready"}, max_wait_kb)
            logger.info(f"🤖 ✓ KB construite pour job {job_id}")
        else:
            logger.info(f"🤖 ⏭ KB déjà construite pour job {job_id}, skip")

        # ─── 3. Programme global ─────────────────────────────────────────────
        j = get_job(job_id)
        if not j.get("global_program"):
            _set_step("global")
            if use_claude_code:
                execute_mission_locally(job_id, "global", cc_model)
                # _import_global passe le job en global_ready
            else:
                launch_global_program_generation(job_id, model=api_model)
                _wait_for({"global_ready"}, max_wait_global)
        update_job(job_id, global_program_validated=1, status="global_validated")
        logger.info(f"🤖 ✓ Programme global validé auto pour job {job_id}")

        # ─── 4. Découpage journées ───────────────────────────────────────────
        j = get_job(job_id)
        daily = j.get("daily_programs") or "[]"
        if not daily or daily in ("[]", '"[]"'):
            _set_step("daily")
            if use_claude_code:
                execute_mission_locally(job_id, "daily", cc_model)
            else:
                launch_daily_split(job_id, model=api_model)
                _wait_for({"daily_ready"}, max_wait_daily)
        update_job(job_id, daily_programs_validated=1, status="daily_validated")
        logger.info(f"🤖 ✓ Programmes journée validés auto pour job {job_id}")

        # ─── 5. Génération texte (~90k mots × N journées) ────────────────────
        j = get_job(job_id)
        _set_step("content")
        if use_claude_code:
            # _execute_chunked content : N segments × 1 subprocess Claude Code,
            # finalize par _finalize_content_step qui passe le job en tts_launched.
            execute_mission_locally(job_id, "content", cc_model)
        else:
            launch_tts_for_all_days(job_id, j["platform_id"], model=api_model)
            _wait_for({"tts_launched"}, max_wait_content)
        logger.info(f"🤖 ✓ Contenu généré pour job {job_id}")

        # ─── 5.5. Sécurité volume (toutes branches, best-effort) ─────────────
        # Pour chaque folder, si total_words < 90 000, enrichit les segments
        # les plus courts. CC mode → subprocess `claude` (forfait, gratuit).
        # API mode → appel Anthropic direct (consomme la clé). Multi-passes
        # jusqu'à 3 dans les deux cas pour atteindre le seuil 90k.
        # `skip_volume_safety=True` : utilisé par le mode TEST pour itérer plus
        # vite sur la review (volume safety prend ~30-45 min, review seule ~10-15).
        if skip_volume_safety:
            logger.info(f"⏭ Volume safety SKIPPÉ pour job {job_id} (skip_volume_safety=True)")
        else:
            from services.claude_code_mission_service import (
                compute_volume_audit, run_volume_safety, run_volume_safety_api,
            )
            j = get_job(job_id)
            try:
                audit = compute_volume_audit(job_id)
                deficit_folders = [f for f in audit.get("folders", []) if f["deficit"] > 0]
                if deficit_folders:
                    _set_step("volume_safety")
                    logger.info(
                        f"🤖 Sécurité volume ({'CC' if use_claude_code else 'API'}) : "
                        f"{len(deficit_folders)} folder(s) en déficit "
                        f"sur {len(audit.get('folders', []))} (job {job_id})"
                    )
                    for fa in deficit_folders:
                        try:
                            if use_claude_code:
                                r = run_volume_safety(job_id, fa["folder_id"], model=cc_model)
                            else:
                                r = run_volume_safety_api(job_id, fa["folder_id"], model=api_model)
                            logger.info(
                                f"🤖   ✓ Volume safety folder {fa['folder_id']} : "
                                f"{len(r.get('enriched', []))} segments enrichis "
                                f"(target_reached={r.get('target_reached', False)})"
                            )
                        except Exception as e:
                            logger.warning(
                                f"⚠️ Volume safety folder {fa['folder_id']} échoué : {e} "
                                f"— on continue malgré tout"
                            )
                else:
                    logger.info(f"🤖 ✓ Volume OK (≥90k mots/journée) pour job {job_id}")
            except Exception as e:
                logger.warning(f"⚠️ Audit volume échoué : {e} — skip volume safety")

        # ─── 5.6. Révision conformité (étape 6bis) ───────────────────────────
        # En CC : multi-agents par groupe de règles (4 chunks × N journées).
        # Marque chaque segment reviewed=1 + applique les patches éligibles.
        # Idempotent : skip les journées dont tous les segments sont reviewed=1.
        _set_step("review")
        if use_claude_code:
            try:
                execute_mission_locally(job_id, "review", cc_model)
                logger.info(f"🤖 ✓ Révision conformité (CC) appliquée pour job {job_id}")
            except Exception as e:
                # Best-effort : on note l'erreur mais on ne bloque pas l'audio.
                # On marque l'erreur dans _AUTO_PILOT_STATE pour que l'UI puisse
                # afficher un bandeau "révision non faite — relancer manuellement".
                # Sans ce tracking, l'utilisateur voit "audio_launched" sans savoir
                # que la conformité a été zappée (cas réel : LOCAL_DEV non set ou
                # claude binary disparu du PATH entre content et review).
                err_msg = str(e)[:300]
                logger.error(
                    f"❌ Révision conformité (CC) échouée pour job {job_id} : {err_msg} — "
                    f"on enchaîne quand même sur l'audio (best-effort)"
                )
                _set_step("review", review_error=err_msg, review_status="failed")
        else:
            # Mode API : la route /content/<folder>/review fait déjà tout via API.
            # On l'invoque pour chaque folder (best-effort).
            failed_folders = []
            try:
                from database.db import get_db_connection
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM cours_folders WHERE platform_id = ? ORDER BY position ASC",
                    (j["platform_id"],),
                )
                folder_ids = [r[0] for r in cursor.fetchall()]
                conn.close()
                from services.content_generation_service import run_content_review
                for fid in folder_ids:
                    try:
                        run_content_review(fid, model=api_model)
                    except Exception as e:
                        logger.warning(f"⚠️ Review API folder {fid} échoué : {e}")
                        failed_folders.append(f"{fid}:{str(e)[:80]}")
                if failed_folders:
                    _set_step("review",
                              review_error=f"folders échoués : {'; '.join(failed_folders)}",
                              review_status="failed")
                else:
                    logger.info(f"🤖 ✓ Révision conformité (API) pour job {job_id}")
            except Exception as e:
                err_msg = str(e)[:300]
                logger.warning(f"⚠️ Révision API échouée : {err_msg} — skip")
                _set_step("review", review_error=err_msg, review_status="failed")

        # ─── 6. Audio TTS séquentiel par folder ──────────────────────────────
        # On exécute generate_audio_from_script directement (pas la route
        # launch_audio) pour rester dans le greenlet et avoir un point d'arrêt
        # propre. Le module persistant est créé/MAJ à la fin (idempotent).
        _set_step("audio")
        j = get_job(job_id)
        platform_id = j["platform_id"]
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM cours_folders WHERE platform_id = ? ORDER BY position ASC",
            (platform_id,),
        )
        folder_ids = [r[0] for r in cursor.fetchall()]
        conn.close()
        if not folder_ids:
            raise RuntimeError("Aucun cours_folder trouvé pour la plateforme")

        update_job(job_id, status="audio_launched")
        mock = (tts_mode == "mock")
        basic_tts = (tts_mode == "gtts")

        for fid in folder_ids:
            try:
                generate_audio_from_script(
                    fid, force_all=True, mock=mock, basic_tts=basic_tts,
                )
            except Exception as e:
                update_job(job_id, status="audio_error", error_message=f"folder {fid} : {str(e)[:300]}")
                raise
            eventlet.sleep(5)

        # Création/MAJ du module persistant (équivalent du bloc dans launch_audio,
        # dupliqué ici car on bypass la route).
        try:
            from datetime import datetime as _dt
            from config import FRANCE_TZ as _tz
            voice_type = "mock" if mock else ("gtts" if basic_tts else "fish_audio")
            conn = get_db_connection()
            cur = conn.cursor()
            year = _dt.now(_tz).year
            rncp = j.get("rncp_code") or ""
            cur.execute("SELECT COUNT(*) FROM formation_modules WHERE rncp_code = ?", (rncp,))
            n = cur.fetchone()[0] + 1
            version = f"{year}-v{n}"
            cur.execute("""
                INSERT OR IGNORE INTO formation_modules
                (rncp_code, tp_name, version, status, source_pipeline_job_id,
                 source_platform_id, voice_type, voice_updated_at, validated_at)
                VALUES (?, ?, ?, 'validated', ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (rncp, j["tp_name"], version, job_id, platform_id, voice_type))
            if cur.rowcount == 0:
                cur.execute(
                    """UPDATE formation_modules
                       SET voice_type = ?, voice_updated_at = CURRENT_TIMESTAMP
                       WHERE source_pipeline_job_id = ?""",
                    (voice_type, job_id),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"⚠️ Auto-pilot module create/update : {e}")

        # Health-check final : audite que tous les artefacts sont cohérents
        # (segments, DOCX buildables, snapshots pre-review, audio dirty=0,
        # module persistant). Stocké dans _AUTO_PILOT_STATE pour que l'UI
        # puisse afficher un bandeau "santé OK" ou "N incohérences détectées".
        try:
            from services.formation_health_service import compute_health
            health = compute_health(job_id)
            _set_step("done", health=health)
            if health["ok"]:
                logger.info(f"💚 Health-check OK pour job {job_id}")
            else:
                logger.warning(
                    f"💛 Health-check : pipeline terminée avec {len(health['blocking'])} "
                    f"incohérence(s) bloquante(s) : {health['blocking']}"
                )
        except Exception as e:
            logger.warning(f"⚠️ Health-check final job {job_id} échoué : {e}")

        _set_step("done", status="done", finished_at=time.time())
        logger.info(f"🤖 ✅ Auto-pilot TERMINÉ pour job {job_id}")

    except Exception as e:
        logger.error(f"❌ Auto-pilot job {job_id} : {e}")
        _set_step(_AUTO_PILOT_STATE.get(job_id, {}).get("step", "?"),
                  status="error", error=str(e)[:500],
                  finished_at=time.time())


@formation_bp.route("/api/formation/<int:job_id>/run-auto", methods=["POST"])
def run_auto_pilot(job_id):
    """Lance l'auto-pilot : enchaîne fetch REAC → KB → global → daily → content → audio.

    Body (optionnel) :
      - tts_mode : 'fish_audio' | 'gtts' | 'mock' (défaut 'gtts')
      - model : 'sonnet' | 'haiku' (défaut 'sonnet')

    Retourne 202 immédiatement. Le client peut suivre la progression via
    GET /api/formation/<job>/run-auto/status.
    """
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404

    payload = request.get_json(silent=True) or {}
    tts_mode = (payload.get("tts_mode") or "gtts").lower()
    if tts_mode not in ("fish_audio", "gtts", "mock"):
        return jsonify({"error": "tts_mode invalide (fish_audio | gtts | mock)"}), 400
    model = (payload.get("model") or "sonnet").lower()
    if model not in ("sonnet", "haiku", "flash", "pro"):
        return jsonify({"error": "model invalide (sonnet | haiku | flash | pro)"}), 400
    use_claude_code = bool(payload.get("use_claude_code", False))

    if _AUTO_PILOT_STATE.get(job_id, {}).get("status") == "running":
        return jsonify({"error": "Auto-pilot déjà en cours pour ce job"}), 409

    import eventlet
    eventlet.spawn(_run_auto_pilot, job_id, tts_mode, model, use_claude_code)
    return jsonify({
        "ok": True, "status": "auto_pilot_started",
        "tts_mode": tts_mode, "model": model,
        "use_claude_code": use_claude_code,
    }), 202


@formation_bp.route("/api/formation/<int:job_id>/run-auto/status", methods=["GET"])
def auto_pilot_status(job_id):
    """État de l'auto-pilot (running | done | error | idle)."""
    if not _require_admin():
        return jsonify({"error": "Non autorisé"}), 403
    state = _AUTO_PILOT_STATE.get(job_id)
    if not state:
        return jsonify({"status": "idle"}), 200
    return jsonify(state), 200
