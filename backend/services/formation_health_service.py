"""
Service de santé / pre-flight de la pipeline formation.

Deux fonctions principales :
- `compute_preflight(job_id, tts_mode)` : audit AVANT lancement.
  Vérifie que la config + les dépendances externes sont OK pour que la pipeline
  ait une chance de tourner one-shot.
- `compute_health(job_id)` : audit APRÈS lancement. Vérifie que la pipeline a
  produit des artefacts cohérents (segments, DOCX Azure, snapshots pre-review,
  audio TTS, module persistant).

Ces deux fonctions sont appelables depuis :
- une route HTTP (UI affiche le résultat)
- l'auto-pilot lui-même (pre-flight bloque le run, health-check finalise)

Conçu pour être bon-marché (pas de gros calls externes en pre-flight, juste des
HEAD/test). Le pre-flight vérifie explicitement la configuration DeepSeek et
les accès Azure avant tout lancement.
"""

import json
import os
from typing import Optional

from repositories.pipeline_repository import (
    count_completed_segments_for_folders,
    count_dirty_completed_segments_for_folders,
    count_segments_with_pre_review_snapshot_for_folders,
    count_unreviewed_segments_without_error_for_folders,
    get_content_job_docx_state,
    get_formation_module_for_pipeline_job,
    get_pipeline_job,
    list_health_course_folder_rows,
)
from utils.deepseek_client import default_model
from utils.logger import get_logger

logger = get_logger(__name__)


def _expected_structured_segment_contract(
    job: dict,
    daily_programs: list,
) -> dict:
    """Resolve the authoritative expected structured segment contract.

    The legacy pipeline generated three passes per sub-part. The structured
    generator persists one final segment per sub-part, so multiplying by three
    makes successful PostgreSQL pipelines look incomplete.

    V2 never infers its course count from ``nb_days * 7`` or from generated
    pedagogical text. Its locked schedule snapshot is the source of truth.
    """
    try:
        schema_version = int(job.get("schedule_schema_version") or 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("schedule_schema_version invalide") from exc

    if schema_version == 2:
        snapshot = job.get("schedule_snapshot_json") or job.get("schedule_snapshot")
        if isinstance(snapshot, str):
            try:
                snapshot = json.loads(snapshot)
            except json.JSONDecodeError as exc:
                raise ValueError("Le snapshot V2 verrouillé contient un JSON invalide") from exc
        if not isinstance(snapshot, dict):
            raise ValueError("Le snapshot V2 verrouillé est absent")
        if job.get("schedule_locked_at") in (None, ""):
            raise ValueError("Le snapshot V2 n'est pas verrouillé")

        from repositories.day_schedule_repository import (
            _canonical_pipeline_snapshot,
        )

        try:
            canonical_snapshot, expected_hash = _canonical_pipeline_snapshot(snapshot)
        except Exception as exc:
            raise ValueError("Le snapshot V2 verrouillé est invalide") from exc

        stored_hash = str(job.get("schedule_hash") or "").strip()
        if not stored_hash or stored_hash != expected_hash:
            raise ValueError("Le hash du snapshot V2 verrouillé est invalide")
        day_count = int(canonical_snapshot["day_count"])
        declared_days = job.get("nb_days")
        if declared_days not in (None, "") and int(declared_days) != day_count:
            raise ValueError(
                "Le nombre de journées du pipeline ne correspond pas au snapshot V2"
            )

        course_counts = []
        for day_index, day in enumerate(canonical_snapshot["days"], start=1):
            course_count = sum(
                1
                for block in day.get("blocks") or []
                if block.get("block_type") == "course"
            )
            if not 4 <= course_count <= 10:
                raise ValueError(
                    f"Le manifeste V2 de la journée {day_index} contient "
                    f"{course_count} cours au lieu de 4 à 10"
                )
            course_counts.append(course_count)
        return {
            "schema_version": 2,
            "source": "locked_schedule_snapshot",
            "day_count": day_count,
            "course_counts": course_counts,
            "expected_segments": sum(course_counts),
            "schedule_hash": expected_hash,
        }

    if schema_version != 1:
        raise ValueError(
            f"schedule_schema_version non pris en charge : {schema_version}"
        )

    expected = 0
    for day_data in daily_programs:
        if not isinstance(day_data, dict):
            continue
        sub_parts = day_data.get("sub_parts")
        expected += max(1, len(sub_parts) if sub_parts else 6)
    if not expected:
        expected = int(job.get("nb_days") or 0) * 7
    return {
        "schema_version": 1,
        "source": (
            "legacy_daily_programs"
            if daily_programs
            else "legacy_seven_courses_per_day"
        ),
        "day_count": int(job.get("nb_days") or 0),
        "course_counts": [],
        "expected_segments": expected,
        "schedule_hash": None,
    }


def _expected_structured_segment_count(job: dict, daily_programs: list) -> int:
    """Backward-compatible integer facade over the explicit contract."""
    return int(
        _expected_structured_segment_contract(
            job,
            daily_programs,
        )["expected_segments"]
    )


# ─── Pre-flight ──────────────────────────────────────────────────────────────

def compute_preflight(
    job_id: int,
    tts_mode: str = "gtts",
) -> dict:
    """Audit pre-launch : valide config + connectivité externe.

    Retourne :
      {
        "ok": bool,                          # True si pipeline lançable
        "blocking": ["check1", "check2"],    # checks fatals (bloquent le run)
        "warnings": ["check3"],               # checks soft (run possible mais à risque)
        "checks": {
            "llm_provider": {ok, detail},
            "llm_api_key": {ok, detail},
            "azure_tts_blob": {ok, detail},
            "azure_audio_blob": {ok, detail},
            "fish_audio_key": {ok, detail, applicable},
            "france_competences": {ok, detail},
            "job_state": {ok, detail},
        }
      }
    """
    checks = {}
    blocking = []
    warnings = []

    # Job existence + état cohérent
    job = _get_job(job_id)
    if not job:
        return {
            "ok": False,
            "blocking": ["job_not_found"],
            "warnings": [],
            "checks": {"job_state": {"ok": False, "detail": f"Job {job_id} introuvable"}},
        }
    checks["job_state"] = {
        "ok": True,
        "detail": f"status={job['status']}, plateforme {job['platform_id']}",
    }

    # Fournisseur unique : la pipeline utilise l'API DeepSeek et sa clé est
    # toujours bloquante.
    try:
        configured_model = default_model()
    except ValueError as exc:
        checks["llm_provider"] = {"ok": False, "detail": str(exc)}
        blocking.append("llm_provider")
    else:
        checks["llm_provider"] = {
            "ok": True,
            "detail": f"DeepSeek uniquement ({configured_model})",
        }
    api_key_ok = bool((os.getenv("DEEPSEEK_API_KEY") or "").strip())
    checks["llm_api_key"] = {
        "ok": api_key_ok,
        "detail": (
            "DEEPSEEK_API_KEY présente"
            if api_key_ok
            else "DEEPSEEK_API_KEY absente"
        ),
    }
    if not api_key_ok:
        blocking.append("llm_api_key")

    # Azure TTS blob (DOCX + MP3 TTS Fish Audio)
    azure_tts_ok, azure_tts_detail = _check_azure_blob("AZURE_TTS_STORAGE_CONNECTION_STRING")
    checks["azure_tts_blob"] = {"ok": azure_tts_ok, "detail": azure_tts_detail}
    if not azure_tts_ok:
        blocking.append("azure_tts_blob")

    # Azure Audio blob (MP3 cours assemblés)
    azure_audio_ok, azure_audio_detail = _check_azure_blob("AZURE_AUDIO_STORAGE_CONNECTION_STRING")
    checks["azure_audio_blob"] = {"ok": azure_audio_ok, "detail": azure_audio_detail}
    if not azure_audio_ok:
        # Soft : seulement requis si on va générer de l'audio pour de vrai
        if tts_mode != "mock":
            blocking.append("azure_audio_blob")
        else:
            warnings.append("azure_audio_blob")

    # Fish Audio API key — uniquement si tts_mode=fish_audio
    fish_applicable = tts_mode == "fish_audio"
    if fish_applicable:
        fish_key = os.getenv("FISH_AUDIO_API_KEY")
        ok = bool(fish_key)
        checks["fish_audio_key"] = {
            "ok": ok,
            "applicable": True,
            "detail": "présente" if ok else "FISH_AUDIO_API_KEY absente",
        }
        if not ok:
            blocking.append("fish_audio_key")
    else:
        checks["fish_audio_key"] = {
            "ok": True,
            "applicable": False,
            "detail": f"non requis (tts_mode={tts_mode})",
        }

    # France Compétences accessibilité (REAC) — soft : si on a déjà reac_text on s'en fout
    has_reac = bool((job.get("reac_text") or "").strip())
    if has_reac:
        checks["france_competences"] = {
            "ok": True,
            "detail": "REAC déjà téléchargé, pas besoin de re-télécharger",
        }
    else:
        fc_ok, fc_detail = _check_france_competences()
        checks["france_competences"] = {"ok": fc_ok, "detail": fc_detail}
        if not fc_ok:
            warnings.append("france_competences")

    return {
        "ok": len(blocking) == 0,
        "blocking": blocking,
        "warnings": warnings,
        "checks": checks,
    }


# ─── Health-check (post-pipeline) ────────────────────────────────────────────

def compute_health(job_id: int) -> dict:
    """Audit post-pipeline : vérifie que tous les artefacts sont en place et cohérents.

    Retourne :
      {
        "ok": bool,
        "blocking": [...],         # incohérences fatales (DOCX manquant, etc.)
        "warnings": [...],         # incohérences mineures
        "checks": {
            "segments_completed": {ok, detail, n_completed, n_expected},
            "cg_jobs_completed": {ok, detail, idle_folders},
            "docx_uploaded": {ok, detail, missing_folders},
            "pre_review_snapshotted": {ok, detail, n_snapshotted, n_total},
            "review_consistent": {ok, detail, unreviewed_segments},
            "audio_tts_files": {ok, detail, missing_folders},
            "module_persistant": {ok, detail},
        }
      }
    """
    checks = {}
    blocking = []
    warnings = []

    job = _get_job(job_id)
    if not job:
        return {
            "ok": False,
            "blocking": ["job_not_found"],
            "warnings": [],
            "checks": {"job_state": {"ok": False, "detail": f"Job {job_id} introuvable"}},
        }

    # L'audio ne fait plus partie de la pipeline globale : chaque occurrence
    # est générée séparément par le worker H-72. Un segment ``dirty`` est donc
    # un état normal à la fin de cette pipeline texte.
    audio_deferred = True
    try:
        daily_programs = json.loads(job.get("daily_programs") or "[]")
    except Exception:
        daily_programs = []
    try:
        segment_contract = _expected_structured_segment_contract(
            job,
            daily_programs,
        )
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        logger.error(
            "PIPELINE_HEALTH_SCHEDULE_CONTRACT_INVALID job_id=%s error=%s",
            job_id,
            detail,
        )
        return {
            "ok": False,
            "blocking": ["schedule_contract"],
            "warnings": [],
            "checks": {
                "schedule_contract": {
                    "ok": False,
                    "detail": detail,
                    "schema_version": job.get("schedule_schema_version"),
                },
            },
        }

    expected_total_segments = int(segment_contract["expected_segments"])
    nb_days = int(segment_contract["day_count"])
    checks["schedule_contract"] = {
        "ok": True,
        "detail": (
            f"V2 verrouillé : {segment_contract['day_count']} journée(s), "
            f"{expected_total_segments} cours "
            f"({', '.join(str(count) for count in segment_contract['course_counts'])})"
            if segment_contract["schema_version"] == 2
            else
            f"V1 historique : {expected_total_segments} cours attendus"
        ),
        "schema_version": segment_contract["schema_version"],
        "source": segment_contract["source"],
        "day_count": segment_contract["day_count"],
        "course_counts": segment_contract["course_counts"],
        "expected_segments": expected_total_segments,
        "schedule_hash": segment_contract["schedule_hash"],
    }

    # Inventaire des cours_folders + cg_jobs + segments. On audite uniquement
    # le folder canonique de chaque journée attendue : des doublons peuvent
    # exister après un double clic/retry, mais ils ne doivent pas faire échouer
    # la pipeline si les journées attendues sont cohérentes.
    try:
        from services.formation_pipeline_service import get_expected_course_folders
        folder_state = get_expected_course_folders(job_id)
    except Exception as e:
        logger.warning(f"Health canonical folders job {job_id} : {e}")
        folder_state = {
            "expected_count": nb_days,
            "folder_ids": [],
            "duplicates": [],
            "missing": [{"name": "resolution_failed"}],
        }

    canonical_folder_ids = folder_state.get("folder_ids") or []
    duplicate_folders = folder_state.get("duplicates") or []
    missing_folders = folder_state.get("missing") or []

    if canonical_folder_ids:
        folders = list_health_course_folder_rows(canonical_folder_ids)
    else:
        folders = []
    checks["course_folders_expected"] = {
        "ok": len(folders) == nb_days and not missing_folders,
        "detail": (
            f"{len(folders)}/{nb_days} journée(s) canonique(s)"
            + (
                f" · {len(duplicate_folders)} doublon(s) ignoré(s)"
                if duplicate_folders
                else ""
            )
        ),
        "duplicates": duplicate_folders,
        "missing": missing_folders,
    }
    if missing_folders or len(folders) != nb_days:
        blocking.append("course_folders_expected")
    if duplicate_folders:
        warnings.append("duplicate_course_folders")

    # 1. Segments completed
    n_completed = 0
    if folders:
        folder_ids = [int(f["id"]) for f in folders]
        n_completed = count_completed_segments_for_folders(folder_ids)

    seg_ok = n_completed >= expected_total_segments
    checks["segments_completed"] = {
        "ok": seg_ok,
        "detail": f"{n_completed}/{expected_total_segments} segments completed",
        "n_completed": n_completed,
        "n_expected": expected_total_segments,
    }
    if not seg_ok:
        blocking.append("segments_completed")

    # 2. cg_jobs en status='completed'
    idle_folders = [
        (f["id"], f["name"])
        for f in folders
        if f.get("content_status") != "completed"
    ]
    cg_ok = len(idle_folders) == 0 and len(folders) == nb_days
    checks["cg_jobs_completed"] = {
        "ok": cg_ok,
        "detail": (
            f"{len(folders) - len(idle_folders)}/{len(folders)} cg_jobs en 'completed'"
            if folders
            else "aucun cours_folder trouvé"
        ),
        "idle_folders": [{"folder_id": fid, "name": fname} for fid, fname in idle_folders],
    }
    if not cg_ok:
        blocking.append("cg_jobs_completed")

    # 3. DOCX buildable : le service formation_docx_service génère à la volée,
    # donc il suffit de vérifier que les sub_parts sont cohérentes pour chaque
    # folder. Si segments_completed est OK ET sub_parts non vide pour chaque
    # cg_job, le DOCX est garanti téléchargeable via la route /docx.
    docx_ok, docx_detail, missing_docx = _check_docx_buildable(folders)
    checks["docx_buildable"] = {
        "ok": docx_ok,
        "detail": docx_detail,
        "missing_folders": missing_docx,
    }
    if not docx_ok:
        blocking.append("docx_buildable")

    # 4. Snapshot pre-review présent (text_content_pre_review IS NOT NULL)
    n_snapshot = 0
    if folders:
        n_snapshot = count_segments_with_pre_review_snapshot_for_folders(folder_ids)
    snap_ok = n_snapshot == n_completed and n_completed > 0
    checks["pre_review_snapshotted"] = {
        "ok": snap_ok,
        "detail": f"{n_snapshot}/{n_completed} segments avec snapshot pre-review",
        "n_snapshotted": n_snapshot,
        "n_total": n_completed,
    }
    if not snap_ok:
        warnings.append("pre_review_snapshotted")

    # 5. Review cohérent : tous les segments completed → reviewed=1 OU review_error
    n_unreviewed_no_error = 0
    if folders:
        n_unreviewed_no_error = count_unreviewed_segments_without_error_for_folders(folder_ids)
    review_ok = n_unreviewed_no_error == 0
    checks["review_consistent"] = {
        "ok": review_ok,
        "detail": (
            f"{n_unreviewed_no_error} segment(s) ni reviewed=1 ni en erreur — "
            f"la révision n'a pas été tentée"
            if not review_ok
            else "tous les segments ont été tentés en révision"
        ),
        "unreviewed_segments": n_unreviewed_no_error,
    }
    if not review_ok:
        blocking.append("review_consistent")

    # 6. Audio TTS présent si demandé. En pipeline texte, dirty=1 est normal :
    # il signifie "texte prêt, audio à générer plus tard".
    n_dirty = 0
    if folders:
        n_dirty = count_dirty_completed_segments_for_folders(folder_ids)
    audio_ok = (n_dirty == 0 and n_completed > 0) or audio_deferred
    checks["audio_tts_files"] = {
        "ok": audio_ok,
        "detail": (
            "audio différé : texte/Word/reviews prêts, MP3 à générer à la demande"
            if audio_deferred and n_dirty > 0
            else
            f"{n_dirty} segment(s) encore dirty=1 — audio non régénéré"
            if n_dirty > 0
            else "tous les segments ont leur audio à jour (dirty=0)"
        ),
        "n_dirty": n_dirty,
        "deferred": audio_deferred,
    }
    if not audio_ok:
        blocking.append("audio_tts_files")

    # 8. Module persistant créé. En pipeline texte-only, il sera finalisé après
    # la génération audio de toutes les journées.
    mod_row = get_formation_module_for_pipeline_job(job_id)
    mod_ok = bool(mod_row)
    checks["module_persistant"] = {
        "ok": mod_ok,
        "detail": (
            f"module {mod_row['version']} (status={mod_row['status']})"
            if mod_row
            else "aucune ligne dans formation_modules pour ce job"
        ),
    }
    if not mod_ok:
        warnings.append("module_persistant")

    return {
        "ok": len(blocking) == 0,
        "blocking": blocking,
        "warnings": warnings,
        "checks": checks,
    }


# ─── Helpers internes ────────────────────────────────────────────────────────

def _get_job(job_id: int) -> Optional[dict]:
    """Charge un formation_pipeline_jobs en dict."""
    return get_pipeline_job(job_id)


def _check_azure_blob(env_var: str) -> tuple:
    """Vérifie qu'on peut se connecter à un compte Azure Blob via la conn string.

    Retourne (ok: bool, detail: str). Pas de download — juste un list_containers
    qui valide les credentials et l'accessibilité réseau.
    """
    conn_str = os.getenv(env_var)
    if not conn_str:
        return False, f"{env_var} non définie dans .env"
    try:
        from azure.storage.blob import BlobServiceClient
        svc = BlobServiceClient.from_connection_string(conn_str)
        # list_containers est paginé et lazy → on prend juste 1 pour valider la connexion
        next(iter(svc.list_containers(results_per_page=1)), None)
        return True, "connexion OK"
    except Exception as e:
        return False, f"connexion Azure échouée : {str(e)[:200]}"


def _check_france_competences() -> tuple:
    """HEAD sur la home France Compétences pour valider l'accessibilité réseau."""
    try:
        import requests
        resp = requests.head("https://www.francecompetences.fr/", timeout=5, allow_redirects=True)
        if resp.status_code < 500:
            return True, f"accessible (HTTP {resp.status_code})"
        return False, f"HTTP {resp.status_code} sur la home"
    except Exception as e:
        return False, f"inaccessible : {str(e)[:150]}"


def _check_docx_buildable(folders: list) -> tuple:
    """Vérifie que chaque folder peut générer son DOCX à la volée.

    Le DOCX est construit via `build_course_docx` qui appelle
    `_get_segments_for_folder`. Pré-conditions : 1 cg_job par folder + au moins
    1 segment completed. On audite ça directement en DB (pas de build complet,
    qui serait coûteux).
    """
    if not folders:
        return False, "aucun folder", []

    missing = []
    for folder in folders:
        fid = folder["id"]
        fname = folder["name"]
        cg_job_id = folder.get("content_job_id")
        if not cg_job_id:
            missing.append({"folder_id": fid, "name": fname, "reason": "pas de cg_job"})
            continue
        row = get_content_job_docx_state(cg_job_id)
        if not row or int(row.get("completed_count") or 0) == 0:
            missing.append({"folder_id": fid, "name": fname, "reason": "0 segments completed"})
            continue
        if not row.get("sub_parts"):
            missing.append({"folder_id": fid, "name": fname, "reason": "sub_parts vide dans cg_job"})

    if missing:
        return False, f"{len(missing)}/{len(folders)} DOCX non buildables", missing
    return True, f"{len(folders)} DOCX buildables (route /docx prête)", []
