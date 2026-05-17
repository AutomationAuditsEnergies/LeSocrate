"""Apprentissage transversal des règles à partir des annotations du script TTS.

Lit toutes les annotations corrigées (status applied) d'un dossier, demande à
DeepSeek d'en extraire des règles transversales, et persiste le markdown de
règles. Ce markdown alimente la Phase 3b (revérif post-TTS) qui patche les
chunks non-conformes via la primitive de splice MP3.
"""

import json
import logging
import os
import re
from datetime import datetime

from config import DB_PATH, FRANCE_TZ
from database.db import get_db_connection
from utils.anthropic_client import (
    DEEPSEEK_DEFAULT_MODEL,
    AnthropicAPIError,
    AnthropicRateLimitError,
    post_message,
)


logger = logging.getLogger(__name__)

RULES_MODEL = os.getenv("SCRIPT_RULES_MODEL", "deepseek-v4-pro")
REVIEW_MODEL = os.getenv("SCRIPT_RULES_REVIEW_MODEL", "deepseek-v4-pro")
MIN_ANNOTATIONS_FOR_EXTRACTION = 1


def _ensure_rules_table() -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS content_script_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            rules_markdown TEXT NOT NULL DEFAULT '',
            rules_count INTEGER DEFAULT 0,
            source_annotations_count INTEGER DEFAULT 0,
            model TEXT,
            markdown_path TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(folder_id, job_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_content_script_rules_folder_job
        ON content_script_rules(folder_id, job_id)
        """
    )
    conn.commit()
    conn.close()


def _now_str() -> str:
    return datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _notes_dir() -> str:
    base_dir = os.path.dirname(DB_PATH) or os.getcwd()
    path = os.path.join(base_dir, "tts_script_reviews")
    os.makedirs(path, exist_ok=True)
    return path


def _rules_markdown_path(folder_id: int, job_id: int) -> str:
    return os.path.join(_notes_dir(), f"regles-folder-{folder_id}-job-{job_id}.md")


def _fetch_context(folder_id: int) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT j.id, j.platform_id, j.program_title, f.name
        FROM content_generation_jobs j
        JOIN cours_folders f ON f.id = j.folder_id
        WHERE j.folder_id = ?
        """,
        (folder_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "job_id": row[0],
        "platform_id": row[1],
        "program_title": row[2] or "",
        "folder_name": row[3] or f"Dossier {folder_id}",
    }


def _fetch_applied_annotations(folder_id: int, job_id: int) -> list[dict]:
    """Annotations utilisables pour l'extraction : applied (corrections validées
    par l'humain) et rejected (signal de ce qu'il ne FAUT pas faire)."""
    from services.script_annotation_service import _ensure_annotations_table
    _ensure_annotations_table()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, source_type, selected_text, comment, original_paragraph,
               proposed_text, correction_status, bloc_number, filename
        FROM content_script_annotations
        WHERE folder_id = ? AND job_id = ?
          AND status != 'deleted'
          AND correction_status IN ('applied', 'rejected', 'proposed')
        ORDER BY created_at ASC, id ASC
        """,
        (folder_id, job_id),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "source_type": r[1],
            "selected_text": r[2] or "",
            "comment": r[3] or "",
            "original_paragraph": r[4] or "",
            "proposed_text": r[5] or "",
            "correction_status": r[6] or "",
            "bloc_number": r[7],
            "filename": r[8] or "",
        }
        for r in rows
    ]


def _build_llm_prompt(context: dict, annotations: list[dict]) -> str:
    examples = []
    for idx, ann in enumerate(annotations, start=1):
        status_label = {
            "applied": "Correction validée",
            "rejected": "Correction rejetée (à ne PAS appliquer)",
            "proposed": "Correction proposée (en attente de validation)",
        }.get(ann["correction_status"], ann["correction_status"])
        block = (
            f"### Correction {idx} — {status_label}\n"
            f"- Commentaire formateur : {ann['comment']}\n"
            f"- Extrait surligné : « {ann['selected_text']} »\n"
        )
        if ann["original_paragraph"]:
            block += f"- Avant : {ann['original_paragraph']}\n"
        if ann["proposed_text"]:
            block += f"- Après : {ann['proposed_text']}\n"
        examples.append(block)
    examples_text = "\n".join(examples)

    return (
        "Tu es un assistant qui apprend des règles de qualité éditoriale à partir "
        "de corrections humaines sur le script d'un cours audio RNCP. "
        f"Programme : « {context['program_title']} ». Dossier : « {context['folder_name']} ». "
        f"Tu reçois {len(annotations)} corrections faites par le formateur.\n\n"
        "Ta tâche : extraire les règles transversales qui se dégagent. Une règle est "
        "une consigne courte, claire, **applicable automatiquement** par un agent de "
        "revérification du script à venir, sans intervention humaine.\n\n"
        "Contraintes :\n"
        "- Pas de règle évidente (ex. « bien écrire le français »).\n"
        "- Pas de règle dérivée d'un seul exemple si elle ne semble pas généralisable.\n"
        "- Privilégie l'observable et le mesurable (mots interdits, formulations à éviter, "
        "structures à respecter, transitions à ajouter, etc.).\n"
        "- Pour chaque règle, donne un titre court + une description courte + un ou deux "
        "exemples (avant → après) tirés des corrections fournies.\n"
        "- Si une correction a été REJETÉE, c'est un signal que la règle correspondante n'est "
        "PAS souhaitée — ne l'inclus pas dans le markdown.\n\n"
        "Format markdown attendu :\n\n"
        "```markdown\n"
        "# Règles de revérification — <programme>\n\n"
        "## Règle 1 — <titre court>\n\n"
        "<description courte>\n\n"
        "Exemple : « ... » → « ... »\n\n"
        "## Règle 2 — <titre court>\n"
        "...\n"
        "```\n\n"
        "Réponds uniquement par le markdown final, sans préambule, sans clôture, sans "
        "balise de code englobante.\n\n"
        "Corrections à analyser :\n\n"
        f"{examples_text}"
    )


def _count_rules_in_markdown(markdown: str) -> int:
    return sum(1 for line in (markdown or "").splitlines() if line.strip().startswith("## "))


def extract_rules_from_annotations(folder_id: int) -> dict:
    """Lance l'extraction DeepSeek et persiste le markdown.

    Renvoie {"context", "rules_markdown", "rules_count", "source_annotations_count",
              "markdown_path", "model", "generated_at"}.
    Lève ValueError si aucun job ou trop peu d'annotations.
    """
    context = _fetch_context(folder_id)
    if not context:
        raise ValueError("Aucun job de contenu pour ce dossier")

    annotations = _fetch_applied_annotations(folder_id, context["job_id"])
    if len(annotations) < MIN_ANNOTATIONS_FOR_EXTRACTION:
        raise ValueError(
            f"Trop peu d'annotations exploitables ({len(annotations)} trouvée(s), "
            f"minimum {MIN_ANNOTATIONS_FOR_EXTRACTION})"
        )

    prompt = _build_llm_prompt(context, annotations)
    try:
        markdown = post_message(
            [{"role": "user", "content": prompt}],
            max_tokens=4000,
            model=RULES_MODEL,
            timeout=240,
        )
    except (AnthropicAPIError, AnthropicRateLimitError) as exc:
        logger.warning(f"⚠️ Extraction règles DeepSeek échouée folder={folder_id}: {exc}")
        raise ValueError(f"Erreur DeepSeek : {exc}")

    markdown = (markdown or "").strip()
    if not markdown:
        raise ValueError("DeepSeek a renvoyé une réponse vide")

    path = _rules_markdown_path(folder_id, context["job_id"])
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown.rstrip() + "\n")

    rules_count = _count_rules_in_markdown(markdown)
    _ensure_rules_table()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO content_script_rules
            (folder_id, job_id, rules_markdown, rules_count, source_annotations_count,
             model, markdown_path, generated_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(folder_id, job_id) DO UPDATE SET
            rules_markdown = excluded.rules_markdown,
            rules_count = excluded.rules_count,
            source_annotations_count = excluded.source_annotations_count,
            model = excluded.model,
            markdown_path = excluded.markdown_path,
            generated_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            folder_id,
            context["job_id"],
            markdown,
            rules_count,
            len(annotations),
            RULES_MODEL,
            path,
        ),
    )
    conn.commit()
    conn.close()

    logger.info(
        f"📚 Extraction règles folder={folder_id} : {rules_count} règle(s) "
        f"sur {len(annotations)} annotation(s) via {RULES_MODEL}"
    )
    return get_rules(folder_id)


def get_rules(folder_id: int) -> dict:
    context = _fetch_context(folder_id)
    if not context:
        return {
            "context": None,
            "rules_markdown": "",
            "rules_count": 0,
            "source_annotations_count": 0,
            "markdown_path": "",
            "model": "",
            "generated_at": "",
            "updated_at": "",
        }
    _ensure_rules_table()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT rules_markdown, rules_count, source_annotations_count,
               model, markdown_path, generated_at, updated_at
        FROM content_script_rules
        WHERE folder_id = ? AND job_id = ?
        """,
        (folder_id, context["job_id"]),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {
            "context": context,
            "rules_markdown": "",
            "rules_count": 0,
            "source_annotations_count": 0,
            "markdown_path": _rules_markdown_path(folder_id, context["job_id"]),
            "model": "",
            "generated_at": "",
            "updated_at": "",
        }

    return {
        "context": context,
        "rules_markdown": row[0] or "",
        "rules_count": int(row[1] or 0),
        "source_annotations_count": int(row[2] or 0),
        "model": row[3] or "",
        "markdown_path": row[4] or _rules_markdown_path(folder_id, context["job_id"]),
        "generated_at": row[5] or "",
        "updated_at": row[6] or "",
    }


def _word_slice(text: str, start: int, end: int) -> str:
    words = (text or "").split()
    start = max(0, min(len(words), start))
    end = max(start, min(len(words), end))
    return " ".join(words[start:end]).strip()


def _build_review_prompt(rules_markdown: str, chunk_text: str, *, retry: bool = False) -> str:
    word_count = len(chunk_text.split())
    retry_preamble = (
        "⚠️ Tentative précédente : ta réponse n'était pas un JSON valide "
        "(probablement tronquée ou avec du texte parasite). Cette fois, "
        "réponds STRICTEMENT par un objet JSON valide commençant par { "
        "et finissant par }. Pas de fence ```, pas de préambule, pas de "
        "commentaire après. Échappe les guillemets internes (\\\"), "
        "les retours à la ligne (\\n) et les antislashs (\\\\).\n\n"
        if retry else ""
    )
    return (
        retry_preamble +
        "Tu es un agent de revérification CHIRURGICALE du script d'un cours audio. "
        "Tu reçois (1) un markdown de règles éditoriales établies à partir de "
        "corrections du formateur, et (2) un extrait du script lu en TTS.\n\n"
        "Ta tâche : identifier UNIQUEMENT les passages qui violent une règle et "
        "proposer des **patches ciblés** (find / replace). Tu ne réécris JAMAIS "
        "tout l'extrait. Tu ne touches PAS aux passages qui sont déjà conformes.\n\n"
        "RÈGLES IMPÉRATIVES SUR LES PATCHES :\n"
        "1. Un patch a 3 champs : `find` (texte exact à remplacer, copié mot pour "
        "mot depuis l'extrait), `replace` (texte de remplacement), `reason` "
        "(1 ligne, quelle règle s'applique et pourquoi).\n"
        "2. `find` doit être **présent une seule fois** dans l'extrait — utilise "
        "un contexte suffisamment précis pour que le remplacement soit "
        "non-ambigu (5-15 mots typiquement, parfois plus si nécessaire).\n"
        "3. `find` doit être **strictement identique** au texte de l'extrait, "
        "y compris ponctuation, espaces, tags audio entre crochets ([pause], "
        "[calm], etc.). Pas de paraphrase.\n"
        "4. `replace` peut : modifier le contenu, ajouter une phrase, supprimer "
        "une phrase, ajouter des tags audio, ralentir le rythme, etc. — selon "
        "ce que demande la règle.\n"
        "5. Préfère **plusieurs petits patches** à un seul gros. Si tu remplaces "
        "un paragraphe entier alors qu'une seule phrase pose problème, c'est "
        "incorrect.\n"
        "6. Si l'extrait est globalement conforme : `\"patches\": []` et "
        "`\"conforme\": true`.\n"
        "7. Conserve toujours le ton oral, le niveau RNCP, le sens pédagogique.\n"
        "8. Conserve tous les tags audio existants entre crochets sauf si une "
        "règle demande explicitement d'en ajouter / retirer un.\n\n"
        "Réponds EXCLUSIVEMENT par un JSON valide (rien avant, rien après) :\n"
        '{"conforme": <true|false>, '
        '"violations": ["<règle 1: courte description>", ...], '
        '"patches": [{"find": "<extrait exact>", "replace": "<nouveau texte>", '
        '"reason": "<règle X: motif>"}, ...]}\n\n'
        f"=== Règles éditoriales à appliquer ===\n{rules_markdown}\n\n"
        f"=== Extrait à vérifier ({word_count} mots) ===\n{chunk_text}\n\n"
        "JSON :"
    )


def _apply_patches(original_text: str, patches: list[dict]) -> tuple[str, int, list[str]]:
    """Applique les patches find/replace sur le texte original.

    Renvoie (texte_modifié, nb_patches_appliqués, list_d_erreurs).
    Un patch est ignoré si :
    - `find` est vide
    - `find` est introuvable dans le texte
    - `find` apparaît plusieurs fois (ambiguïté)
    """
    result = original_text
    applied = 0
    errors: list[str] = []
    for idx, patch in enumerate(patches or [], start=1):
        if not isinstance(patch, dict):
            errors.append(f"Patch #{idx} ignoré : pas un objet")
            continue
        find = (patch.get("find") or "").strip()
        replace = patch.get("replace") or ""
        if not find:
            errors.append(f"Patch #{idx} ignoré : `find` vide")
            continue
        occurrences = result.count(find)
        if occurrences == 0:
            preview = find[:80].replace("\n", " ")
            errors.append(f"Patch #{idx} ignoré : `find` introuvable ('{preview}…')")
            continue
        if occurrences > 1:
            preview = find[:80].replace("\n", " ")
            errors.append(f"Patch #{idx} ignoré : `find` ambigu ({occurrences} occurrences, '{preview}…')")
            continue
        result = result.replace(find, replace, 1)
        applied += 1
    return result, applied, errors


def _parse_review_response(raw: str) -> dict | None:
    if not raw:
        return None
    raw = raw.strip()
    # DeepSeek peut entourer le JSON de ```json ... ``` ; on l'extrait.
    fenced = re.search(r"\{[\s\S]*\}", raw)
    if not fenced:
        return None
    try:
        return json.loads(fenced.group(0))
    except Exception:
        return None


def review_chunks_with_rules(
    folder_id: int,
    *,
    dry_run: bool = False,
    bloc_numbers: list[int] | None = None,
    max_chunks: int | None = None,
) -> dict:
    """Parcourt les chunks audio d'un dossier, demande à DeepSeek de vérifier la
    conformité aux règles apprises, et splice les MP3 sur les chunks non-conformes.

    Best-effort : les erreurs par chunk sont loggées dans `details` sans bloquer.
    """
    context = _fetch_context(folder_id)
    if not context:
        raise ValueError("Aucun job de contenu pour ce dossier")

    rules = get_rules(folder_id)
    rules_markdown = (rules.get("rules_markdown") or "").strip()
    if not rules_markdown:
        raise ValueError("Aucune règle apprise — lance d'abord l'extraction")

    from services.script_slide_generation_service import get_latest_script_slide_deck
    from services.script_annotation_service import splice_chunk_audio, _course_bloc_text
    deck = get_latest_script_slide_deck(folder_id, context["job_id"])
    if not deck:
        raise ValueError("Aucun script_slide_deck pour ce dossier")
    audio_sync = deck.get("audio_sync") or {}
    timings = list(audio_sync.get("timings") or [])
    if not timings:
        raise ValueError("audio_sync.timings absent — la pipeline TTS n'a pas tourné")

    summary = {
        "dry_run": bool(dry_run),
        "chunks_examined": 0,
        "chunks_corrected": 0,
        "chunks_skipped": 0,
        "chunks_failed": 0,
        "details": [],
    }

    timings_by_bloc: dict[int, list[dict]] = {}
    for t in timings:
        if t.get("patched"):
            continue
        afn = t.get("audio_filename") or ""
        m = re.search(r"(\d+)", afn)
        if not m:
            continue
        bloc_num = int(m.group(1))
        if bloc_numbers and bloc_num not in bloc_numbers:
            continue
        timings_by_bloc.setdefault(bloc_num, []).append(t)

    bloc_texts: dict[int, str] = {}
    for bloc_num in timings_by_bloc:
        text = _course_bloc_text(folder_id, bloc_num)
        if text:
            bloc_texts[bloc_num] = text

    total_processed = 0
    for bloc_num in sorted(timings_by_bloc.keys()):
        bloc_text = bloc_texts.get(bloc_num)
        if not bloc_text:
            for t in timings_by_bloc[bloc_num]:
                summary["chunks_skipped"] += 1
                summary["details"].append({
                    "bloc_number": bloc_num,
                    "audio_filename": t.get("audio_filename"),
                    "status": "skipped",
                    "reason": f"texte bloc {bloc_num} introuvable",
                })
            continue

        # Important : à chaque splice les timings suivants se décalent.
        # On relit donc audio_sync entre chaque chunk pour rester cohérent.
        for t in list(timings_by_bloc[bloc_num]):
            if max_chunks is not None and total_processed >= max_chunks:
                break

            summary["chunks_examined"] += 1
            total_processed += 1
            try:
                word_start = int(t.get("word_start") or 0)
                word_end = int(t.get("word_end") or 0)
            except (TypeError, ValueError):
                summary["chunks_skipped"] += 1
                summary["details"].append({
                    "bloc_number": bloc_num,
                    "audio_filename": t.get("audio_filename"),
                    "status": "skipped",
                    "reason": "word_start/word_end invalides",
                })
                continue
            chunk_text = _word_slice(bloc_text, word_start, word_end)
            if not chunk_text:
                summary["chunks_skipped"] += 1
                summary["details"].append({
                    "bloc_number": bloc_num,
                    "audio_filename": t.get("audio_filename"),
                    "status": "skipped",
                    "reason": "chunk_text vide",
                })
                continue

            try:
                raw = post_message(
                    [{"role": "user", "content": _build_review_prompt(rules_markdown, chunk_text)}],
                    max_tokens=2500,
                    model=REVIEW_MODEL,
                    timeout=180,
                )
            except (AnthropicAPIError, AnthropicRateLimitError) as exc:
                summary["chunks_failed"] += 1
                summary["details"].append({
                    "bloc_number": bloc_num,
                    "audio_filename": t.get("audio_filename"),
                    "status": "failed",
                    "reason": f"DeepSeek: {exc}",
                })
                continue

            parsed = _parse_review_response(raw)
            if not parsed:
                summary["chunks_failed"] += 1
                summary["details"].append({
                    "bloc_number": bloc_num,
                    "audio_filename": t.get("audio_filename"),
                    "status": "failed",
                    "reason": "JSON DeepSeek inparseable",
                    "raw_preview": (raw or "")[:200],
                })
                continue

            conforme = bool(parsed.get("conforme"))
            corrected = (parsed.get("corrected_text") or "").strip()
            violations = parsed.get("violations") or []

            if conforme or not corrected or corrected == chunk_text.strip():
                summary["details"].append({
                    "bloc_number": bloc_num,
                    "audio_filename": t.get("audio_filename"),
                    "status": "conforme",
                    "violations": [],
                })
                continue

            entry = {
                "bloc_number": bloc_num,
                "audio_filename": t.get("audio_filename"),
                "status": "would_correct" if dry_run else "pending",
                "violations": violations,
                "chunk_text": chunk_text,
                "corrected_text": corrected,
                "start_sec": float(t.get("start_time") or 0),
                "end_sec": float(t.get("end_time") or 0),
            }

            if dry_run:
                summary["chunks_corrected"] += 1
                summary["details"].append(entry)
                continue

            # Re-lit l'audio_sync pour avoir les timings à jour (décalages
            # accumulés par les splices précédents dans le même bloc).
            deck = get_latest_script_slide_deck(folder_id, context["job_id"])
            current_sync = deck.get("audio_sync") or {}
            current_timings = current_sync.get("timings") or []
            current_t = None
            for ct in current_timings:
                if (ct.get("audio_filename") == t.get("audio_filename")
                        and int(ct.get("word_start") or -1) == word_start
                        and int(ct.get("word_end") or -1) == word_end):
                    current_t = ct
                    break
            if not current_t:
                summary["chunks_failed"] += 1
                entry["status"] = "failed"
                entry["reason"] = "timing introuvable après décalage"
                summary["details"].append(entry)
                continue

            new_word_end = word_start + len(corrected.split())
            splice_result = splice_chunk_audio(
                folder_id,
                context["platform_id"],
                deck=deck,
                audio_sync=current_sync,
                filename=t.get("audio_filename"),
                splice_start_sec=float(current_t.get("start_time") or 0),
                splice_end_sec=float(current_t.get("end_time") or 0),
                new_text=corrected,
                word_start=word_start,
                word_end_target=new_word_end,
                slide_id_for_patch=f"rules-review-bloc{bloc_num}-{word_start}",
            )
            entry["status"] = splice_result["status"]
            entry["splice_error"] = splice_result.get("error") or ""
            entry["new_duration_sec"] = splice_result.get("new_duration_sec") or 0.0
            if splice_result["status"] == "done":
                summary["chunks_corrected"] += 1
            else:
                summary["chunks_failed"] += 1
            summary["details"].append(entry)

        if max_chunks is not None and total_processed >= max_chunks:
            break

    logger.info(
        f"📚 Revérif règles folder={folder_id} : "
        f"{summary['chunks_examined']} examinés, "
        f"{summary['chunks_corrected']} corrigés, "
        f"{summary['chunks_skipped']} skip, "
        f"{summary['chunks_failed']} fail (dry_run={dry_run})"
    )
    return summary


# État partagé des tâches de revérif texte en cours. Clé = task_id, valeur =
# dict avec progression + résultat. Lifetime : process gunicorn worker.
# Volontairement non persistant : si le worker redémarre, les tâches en cours
# sont perdues (mais on a déjà géré ce cas via détection "stale running" UI).
_TEXT_REVIEW_TASKS: dict[str, dict] = {}

# Map folder_id -> dernier task_id (active ou récemment terminée). Permet au
# frontend de reprendre l'affichage de la progression à l'ouverture de la modale
# Script TTS, même si on l'avait fermée pendant le run.
_FOLDER_TO_LATEST_TASK: dict[int, str] = {}

# Cap par défaut de parallélisme entre sous-parties. Évite de saturer DeepSeek
# (rate limit) et SQLite (write-lock). Override via env.
_TEXT_REVIEW_PARALLEL = max(1, int(os.getenv("SCRIPT_RULES_TEXT_PARALLEL", "6")))


def get_text_review_task(task_id: str) -> dict | None:
    return _TEXT_REVIEW_TASKS.get(task_id)


def get_active_text_review_for_folder(folder_id: int) -> dict | None:
    """Renvoie la dernière tâche de revérif texte connue pour ce folder
    (peut être en cours ou terminée). Le frontend l'utilise à l'ouverture
    de la modale pour reprendre le suivi si la tâche tourne encore."""
    task_id = _FOLDER_TO_LATEST_TASK.get(int(folder_id))
    if not task_id:
        return None
    return _TEXT_REVIEW_TASKS.get(task_id)


def _new_text_review_task(folder_id: int, dry_run: bool, total_segments: int) -> str:
    import uuid
    task_id = uuid.uuid4().hex
    _TEXT_REVIEW_TASKS[task_id] = {
        "task_id": task_id,
        "folder_id": folder_id,
        "dry_run": dry_run,
        "status": "running",
        "segments_total": total_segments,
        "segments_done": 0,
        "segments_modified": 0,
        "segments_conforme": 0,
        "segments_skipped": 0,
        "segments_failed": 0,
        "current_segment": "",
        "current_step": "",
        "started_at": _now_str(),
        "ended_at": "",
        "result": None,
        "error": None,
        "log_lines": [],
    }
    return task_id


def _append_task_log(task_id: str, line: str) -> None:
    task = _TEXT_REVIEW_TASKS.get(task_id)
    if not task:
        return
    task["log_lines"].append(f"[{_now_str()}] {line}")
    task["log_lines"] = task["log_lines"][-50:]  # cap pour ne pas grossir indéfiniment


def start_text_review_async(folder_id: int, *, dry_run: bool = False,
                            sub_part_indices: list[int] | None = None) -> str:
    """Démarre la revérif texte dans un greenlet eventlet et retourne task_id.

    Travaille au niveau **bloc cours** (les 7 MP3 d'une journée correspondant à
    des cours de 45-55 min). Les règles éditoriales du formateur portent sur
    la structure du cours (intro, corps, conclusion, transitions) — donc le LLM
    voit le texte complet d'un cours, pas une découpe interne segments × passes.
    Les patches identifiés sont ensuite remontés aux segments source pour les
    écritures DB.
    """
    context = _fetch_context(folder_id)
    if not context:
        raise ValueError("Aucun job de contenu pour ce dossier")

    rules = get_rules(folder_id)
    if not (rules.get("rules_markdown") or "").strip():
        raise ValueError("Aucune règle apprise — lance d'abord l'extraction")

    from services.content_generation_service import get_course_script_plan_for_ui
    plan = get_course_script_plan_for_ui(folder_id)
    blocs = [b for b in (plan.get("course_blocs") or []) if (b.get("text") or "").strip()]
    if not blocs:
        raise ValueError("Aucun bloc cours disponible pour ce dossier")
    total = len(blocs)

    task_id = _new_text_review_task(folder_id, dry_run, total)
    _FOLDER_TO_LATEST_TASK[int(folder_id)] = task_id
    _append_task_log(task_id,
        f"Lancement : {total} bloc(s) cours à examiner, "
        f"dry_run={dry_run}, parallel={_TEXT_REVIEW_PARALLEL}")

    import eventlet
    def _runner():
        try:
            summary = review_blocs_with_rules(
                folder_id,
                dry_run=dry_run,
                progress_task_id=task_id,
            )
            task = _TEXT_REVIEW_TASKS.get(task_id)
            if task:
                task["status"] = "completed"
                task["result"] = summary
                task["ended_at"] = _now_str()
                _append_task_log(task_id,
                    f"Terminée : {summary['segments_modified']} "
                    f"{'à modifier' if dry_run else 'modifiés'}, "
                    f"{summary['segments_conforme']} conformes, "
                    f"{summary['segments_failed']} échecs")
        except Exception as exc:
            task = _TEXT_REVIEW_TASKS.get(task_id)
            if task:
                task["status"] = "failed"
                task["error"] = str(exc)[:500]
                task["ended_at"] = _now_str()
            logger.exception(f"❌ Revérif texte async folder={folder_id} échouée")
            _append_task_log(task_id, f"❌ Échec : {exc}")
    eventlet.spawn(_runner)
    return task_id


def _locate_patch_segment(find: str, segments_rows: list[tuple]) -> tuple[int, str] | None:
    """Cherche `find` parmi les text_content des segments. Renvoie (segment_id,
    text_content) si exactement 1 segment le contient une seule fois. Sinon
    None (ambigu, introuvable, ou multi-segments → on n'applique pas)."""
    needle = (find or "").strip()
    if not needle:
        return None
    matches: list[tuple[int, str]] = []
    for seg in segments_rows:
        seg_id, sub_idx, sub_name, passe, text, wc = seg
        if not text:
            continue
        if text.count(needle) == 1:
            matches.append((seg_id, text))
    if len(matches) == 1:
        return matches[0]
    return None


def review_blocs_with_rules(
    folder_id: int,
    *,
    dry_run: bool = False,
    progress_task_id: str | None = None,
) -> dict:
    """Revérif au niveau BLOC COURS (1 bloc = 1 MP3 de 45-55 min).

    Pour chaque bloc cours du folder :
    1. Récupère son texte complet via `get_course_script_plan_for_ui`.
    2. Appelle DeepSeek avec ce texte + règles.
    3. Pour chaque patch proposé, retrouve le `content_generation_segments`
       qui contient le `find` (recherche substring unique) et applique le
       `replace` dans ce segment (dirty=1, reviewed=0).

    Travaille en parallèle entre blocs via `_TEXT_REVIEW_PARALLEL`.
    """
    context = _fetch_context(folder_id)
    if not context:
        raise ValueError("Aucun job de contenu pour ce dossier")

    rules = get_rules(folder_id)
    rules_markdown = (rules.get("rules_markdown") or "").strip()
    if not rules_markdown:
        raise ValueError("Aucune règle apprise — lance d'abord l'extraction")

    from services.content_generation_service import get_course_script_plan_for_ui
    plan = get_course_script_plan_for_ui(folder_id)
    blocs = [b for b in (plan.get("course_blocs") or []) if (b.get("text") or "").strip()]
    if not blocs:
        raise ValueError("Aucun bloc cours disponible — la pipeline a-t-elle généré le texte ?")

    # Charge les segments source une fois (pour le mapping patches → segments)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, sub_part_index, sub_part_name, passe, text_content, word_count
        FROM content_generation_segments
        WHERE job_id = ? AND status = 'completed'
        ORDER BY sub_part_index ASC, passe ASC
        """,
        (context["job_id"],),
    )
    segments_rows = cursor.fetchall()
    conn.close()

    import eventlet
    state_lock = eventlet.semaphore.Semaphore(1)
    db_lock = eventlet.semaphore.Semaphore(1)

    summary = {
        "dry_run": bool(dry_run),
        "blocs_examined": 0,
        "blocs_modified": 0,
        "blocs_conforme": 0,
        "blocs_failed": 0,
        # Compat ascendante avec le frontend qui utilise les noms segments_*
        "segments_examined": 0,
        "segments_modified": 0,
        "segments_conforme": 0,
        "segments_failed": 0,
        "segments_skipped": 0,
        "details": [],
    }

    def _update_task(**fields):
        if not progress_task_id:
            return
        task = _TEXT_REVIEW_TASKS.get(progress_task_id)
        if task:
            task.update(fields)

    with state_lock:
        _update_task(segments_total=len(blocs))

    pool_size = max(1, min(_TEXT_REVIEW_PARALLEL, len(blocs)))
    if progress_task_id:
        _append_task_log(progress_task_id,
            f"Parallélisation : {len(blocs)} bloc(s) cours sur pool de {pool_size}")

    def _process_bloc(bloc: dict):
        bloc_num = int(bloc.get("bloc_number") or 0)
        filename = bloc.get("filename") or f"bloc_{bloc_num}"
        bloc_text = (bloc.get("text") or "").strip()
        bloc_label = f"Cours {bloc_num}/7 ({filename})"

        with state_lock:
            summary["blocs_examined"] += 1
            summary["segments_examined"] += 1  # compat frontend
            done = summary["blocs_examined"]
            _update_task(current_segment=bloc_label, current_step="lecture", segments_done=done)
        if progress_task_id:
            _append_task_log(progress_task_id,
                f"→ {done}/{len(blocs)} : {bloc_label}")

        if not bloc_text:
            with state_lock:
                summary["segments_skipped"] += 1
            if progress_task_id:
                _append_task_log(progress_task_id, f"   ⏭ {bloc_label} : texte vide")
            return

        # max_tokens dynamique sur la taille du bloc (typiquement 7000-10000 mots)
        bloc_word_count = len(bloc_text.split())
        llm_max_tokens = min(60000, max(8000, int(bloc_word_count * 1.15 * 1.6) + 800))
        with state_lock:
            _update_task(current_step=f"DeepSeek · {bloc_label}")
        try:
            raw = post_message(
                [{"role": "user", "content": _build_review_prompt(rules_markdown, bloc_text)}],
                max_tokens=llm_max_tokens,
                model=REVIEW_MODEL,
                timeout=600,
            )
        except (AnthropicAPIError, AnthropicRateLimitError) as exc:
            with state_lock:
                summary["blocs_failed"] += 1
                summary["segments_failed"] += 1
                summary["details"].append({
                    "bloc_number": bloc_num,
                    "filename": filename,
                    "sub_part_name": bloc_label,  # compat frontend
                    "passe": None,
                    "status": "failed",
                    "reason": f"DeepSeek : {exc}",
                })
            if progress_task_id:
                _append_task_log(progress_task_id,
                    f"   ❌ {bloc_label} · DeepSeek : {str(exc)[:120]}")
            return

        parsed = _parse_review_response(raw)
        if not parsed:
            # Retry une fois
            if progress_task_id:
                _append_task_log(progress_task_id, f"   ⟳ {bloc_label} · JSON inparseable, retry…")
            try:
                raw_retry = post_message(
                    [{"role": "user", "content": _build_review_prompt(rules_markdown, bloc_text, retry=True)}],
                    max_tokens=min(60000, int(llm_max_tokens * 1.5)),
                    model=REVIEW_MODEL,
                    timeout=600,
                )
                parsed = _parse_review_response(raw_retry)
                if parsed and progress_task_id:
                    _append_task_log(progress_task_id, f"   ✓ {bloc_label} · retry OK")
            except Exception as exc2:
                if progress_task_id:
                    _append_task_log(progress_task_id,
                        f"   ❌ {bloc_label} · retry : {str(exc2)[:120]}")
        if not parsed:
            with state_lock:
                summary["blocs_failed"] += 1
                summary["segments_failed"] += 1
                summary["details"].append({
                    "bloc_number": bloc_num,
                    "filename": filename,
                    "sub_part_name": bloc_label,
                    "passe": None,
                    "status": "failed",
                    "reason": "JSON DeepSeek inparseable (après retry)",
                    "raw_preview": (raw or "")[:500],
                })
            if progress_task_id:
                _append_task_log(progress_task_id, f"   ❌ {bloc_label} · JSON inparseable")
            return

        conforme = bool(parsed.get("conforme"))
        violations = parsed.get("violations") or []
        patches_raw = parsed.get("patches") or []

        # Compat ascendante (vieille forme corrected_text → 1 patch)
        if not patches_raw and parsed.get("corrected_text"):
            legacy = (parsed.get("corrected_text") or "").strip()
            if legacy and legacy != bloc_text:
                patches_raw = [{"find": bloc_text, "replace": legacy,
                                "reason": "Réponse legacy"}]

        # Map patches → segments
        patches_summary = []
        seg_updates: dict[int, list[tuple[str, str]]] = {}  # seg_id -> [(find, replace)]
        for idx_p, p in enumerate(patches_raw or []):
            if not isinstance(p, dict):
                continue
            find = (p.get("find") or "").strip()
            replace = p.get("replace") or ""
            reason = (p.get("reason") or "").strip()
            target = _locate_patch_segment(find, segments_rows)
            patches_summary.append({
                "find": find,
                "replace": replace,
                "reason": reason,
                "applied": bool(target),
                "segment_id": target[0] if target else None,
            })
            if target:
                seg_updates.setdefault(target[0], []).append((find, replace))

        if conforme or not patches_raw or not seg_updates:
            with state_lock:
                summary["blocs_conforme"] += 1
                summary["segments_conforme"] += 1
                summary["details"].append({
                    "bloc_number": bloc_num,
                    "filename": filename,
                    "sub_part_name": bloc_label,
                    "passe": None,
                    "status": "conforme",
                    "violations": violations if not conforme else [],
                    "patches": patches_summary,
                })
            if progress_task_id:
                if patches_raw and not seg_updates:
                    _append_task_log(progress_task_id,
                        f"   ⚠ {bloc_label} : {len(patches_raw)} patch(s) proposés mais aucun applicable (find ambigu/introuvable)")
                else:
                    _append_task_log(progress_task_id, f"   ✓ {bloc_label} : conforme")
            return

        # Applique les modifications sur chaque segment concerné
        words_before_bloc = bloc_word_count
        if not dry_run:
            with db_lock:
                conn2 = get_db_connection()
                cursor2 = conn2.cursor()
                for seg_id, replacements in seg_updates.items():
                    # Re-lecture du segment (peut avoir été modifié par un autre bloc en parallèle)
                    cursor2.execute(
                        "SELECT text_content FROM content_generation_segments WHERE id = ?",
                        (seg_id,),
                    )
                    row = cursor2.fetchone()
                    if not row:
                        continue
                    seg_text = row[0] or ""
                    for find, replace in replacements:
                        if seg_text.count(find) == 1:
                            seg_text = seg_text.replace(find, replace, 1)
                    cursor2.execute(
                        """
                        UPDATE content_generation_segments
                        SET text_content = ?, word_count = ?, dirty = 1,
                            humanized = 0, humanization_error = NULL, humanization_signature = NULL,
                            reviewed = 0, review_error = NULL, review_signature = NULL
                        WHERE id = ?
                        """,
                        (seg_text, len(seg_text.split()), seg_id),
                    )
                conn2.commit()
                conn2.close()

        # Calcule un corrected_text du bloc pour affichage (somme des deltas)
        bloc_corrected = bloc_text
        for p in patches_summary:
            if p["applied"] and p["find"] and bloc_corrected.count(p["find"]) == 1:
                bloc_corrected = bloc_corrected.replace(p["find"], p["replace"], 1)

        entry = {
            "bloc_number": bloc_num,
            "filename": filename,
            "sub_part_name": bloc_label,
            "passe": None,
            "status": "would_modify" if dry_run else "modified",
            "violations": violations,
            "patches": patches_summary,
            "patches_applied": sum(1 for p in patches_summary if p["applied"]),
            "segments_touched": list(seg_updates.keys()),
            "original_text": bloc_text,
            "corrected_text": bloc_corrected,
            "words_before": words_before_bloc,
            "words_after": len(bloc_corrected.split()),
        }
        with state_lock:
            summary["blocs_modified"] += 1
            summary["segments_modified"] += 1
            summary["details"].append(entry)
            _update_task(segments_modified=summary["segments_modified"])
        if progress_task_id:
            _append_task_log(progress_task_id,
                f"   ✏️ {bloc_label} · {'à modifier' if dry_run else 'modifié'} "
                f"({entry['patches_applied']}/{len(patches_summary)} patch(s), "
                f"{len(seg_updates)} segment(s) touché(s), "
                f"{entry['words_before']} → {entry['words_after']} mots, "
                f"{len(violations)} règle(s))")

    pool = eventlet.GreenPool(size=pool_size)
    pile = eventlet.GreenPile(pool)
    for bloc in blocs:
        pile.spawn(_process_bloc, bloc)
    list(pile)

    logger.info(
        f"📝 Revérif blocs cours folder={folder_id} : "
        f"{summary['blocs_examined']} examinés, "
        f"{summary['blocs_modified']} {'à modifier' if dry_run else 'modifiés'}, "
        f"{summary['blocs_conforme']} conformes, "
        f"{summary['blocs_failed']} fail (dry_run={dry_run})"
    )
    return summary


def review_segments_with_rules(
    folder_id: int,
    *,
    dry_run: bool = False,
    sub_part_indices: list[int] | None = None,
    progress_task_id: str | None = None,
) -> dict:
    """Parcourt les segments completed du job, demande à DeepSeek de vérifier
    la conformité aux règles apprises, et corrige le texte si non conforme.

    Travaille au niveau `content_generation_segments` (sub_part × passe), pas
    au niveau chunk audio — donc ne nécessite PAS de `script_slide_deck` ni
    d'`audio_sync.timings`. Les segments modifiés sont marqués `dirty=1
    reviewed=0` : la prochaine régénération TTS les re-fera.

    Conçu pour deux usages :
    - manuel via UI : bouton « Simuler texte » / « Appliquer au texte »
    - pipeline (à venir) : étape automatique entre review conformité et TTS

    Best-effort : un segment qui plante n'arrête pas les autres.
    """
    context = _fetch_context(folder_id)
    if not context:
        raise ValueError("Aucun job de contenu pour ce dossier")

    rules = get_rules(folder_id)
    rules_markdown = (rules.get("rules_markdown") or "").strip()
    if not rules_markdown:
        raise ValueError("Aucune règle apprise — lance d'abord l'extraction")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, sub_part_index, sub_part_name, passe, text_content, word_count
        FROM content_generation_segments
        WHERE job_id = ? AND status = 'completed'
        ORDER BY sub_part_index ASC, passe ASC
        """,
        (context["job_id"],),
    )
    segments = cursor.fetchall()
    conn.close()

    if sub_part_indices:
        wanted = {int(i) for i in sub_part_indices}
        segments = [s for s in segments if int(s[1]) in wanted]

    summary = {
        "dry_run": bool(dry_run),
        "segments_examined": 0,
        "segments_modified": 0,
        "segments_conforme": 0,
        "segments_skipped": 0,
        "segments_failed": 0,
        "details": [],
    }

    # Lock pour MAJ concurrentes du summary, du task state, des détails.
    import eventlet
    state_lock = eventlet.semaphore.Semaphore(1)
    # Lock écriture DB SQLite : write-lock global, mieux vaut sérialiser
    # les UPDATE pour éviter "database is locked".
    db_lock = eventlet.semaphore.Semaphore(1)

    def _update_task(**fields):
        if not progress_task_id:
            return
        task = _TEXT_REVIEW_TASKS.get(progress_task_id)
        if task:
            task.update(fields)

    with state_lock:
        _update_task(segments_total=len(segments))

    # Groupe les segments par sous-partie : 1 "agent" (greenlet) traite tous
    # les passes d'une même sous-partie séquentiellement. Pool plafonné à
    # _TEXT_REVIEW_PARALLEL pour ne pas saturer DeepSeek / SQLite.
    from collections import defaultdict
    groups: dict[int, list] = defaultdict(list)
    for seg in segments:
        groups[int(seg[1])].append(seg)
    group_keys = sorted(groups.keys())

    pool_size = max(1, min(_TEXT_REVIEW_PARALLEL, len(group_keys)))
    if progress_task_id:
        _append_task_log(progress_task_id,
            f"Parallélisation : {len(group_keys)} sous-partie(s) sur pool de {pool_size}")

    def _process_group(sub_idx_key: int):
        group_segments = groups[sub_idx_key]
        sub_idx_label = group_segments[0][2] or f"Sous-partie {sub_idx_key + 1}"
        if progress_task_id:
            _append_task_log(progress_task_id,
                f"▶ {sub_idx_label} : démarrage ({len(group_segments)} passes)")

        for seg in group_segments:
            seg_id, sub_idx, sub_name, passe, text, wc = seg
            text = (text or "").strip()
            seg_label = f"{sub_name or f'Sous-partie {sub_idx + 1}'} · passe {passe}"

            with state_lock:
                summary["segments_examined"] += 1
                done_so_far = summary["segments_examined"]
                _update_task(current_segment=seg_label, current_step="lecture",
                             segments_done=done_so_far)
            if progress_task_id:
                _append_task_log(progress_task_id,
                    f"→ {done_so_far}/{len(segments)} : {seg_label}")

            if not text:
                with state_lock:
                    summary["segments_skipped"] += 1
                    summary["details"].append({
                        "segment_id": seg_id,
                        "sub_part_name": sub_name or f"Sous-partie {sub_idx + 1}",
                        "passe": passe,
                        "status": "skipped",
                        "reason": "text_content vide",
                    })
                    _update_task(segments_skipped=summary["segments_skipped"])
                if progress_task_id:
                    _append_task_log(progress_task_id, f"   ⏭ {seg_label} : text vide")
                continue

            with state_lock:
                _update_task(current_step=f"DeepSeek · {seg_label}")
            # max_tokens calculé pour laisser de la marge : corrected_text
            # peut faire jusqu'à 1.15x le nb de mots original, ~1.5 token/mot
            # côté français, + ~500 tokens pour wrapper JSON et violations.
            seg_word_count = len(text.split())
            llm_max_tokens = min(60000, max(8000, int(seg_word_count * 1.15 * 1.6) + 800))
            try:
                raw = post_message(
                    [{"role": "user", "content": _build_review_prompt(rules_markdown, text)}],
                    max_tokens=llm_max_tokens,
                    model=REVIEW_MODEL,
                    timeout=600,
                )
            except (AnthropicAPIError, AnthropicRateLimitError) as exc:
                with state_lock:
                    summary["segments_failed"] += 1
                    summary["details"].append({
                        "segment_id": seg_id,
                        "sub_part_name": sub_name or f"Sous-partie {sub_idx + 1}",
                        "passe": passe,
                        "status": "failed",
                        "reason": f"DeepSeek : {exc}",
                    })
                    _update_task(segments_failed=summary["segments_failed"])
                if progress_task_id:
                    _append_task_log(progress_task_id,
                        f"   ❌ {seg_label} · DeepSeek : {str(exc)[:120]}")
                continue

            parsed = _parse_review_response(raw)
            if not parsed:
                # Retry une fois avec un prompt renforcé "format JSON strict"
                # + max_tokens supplémentaire. Couvre les cas de troncature
                # (réponse trop longue) ou de fence markdown intempestive.
                if progress_task_id:
                    _append_task_log(progress_task_id,
                        f"   ⟳ {seg_label} · JSON inparseable, retry…")
                with state_lock:
                    _update_task(current_step=f"DeepSeek retry · {seg_label}")
                try:
                    raw_retry = post_message(
                        [{"role": "user", "content": _build_review_prompt(rules_markdown, text, retry=True)}],
                        max_tokens=min(60000, int(llm_max_tokens * 1.5)),
                        model=REVIEW_MODEL,
                        timeout=600,
                    )
                    parsed = _parse_review_response(raw_retry)
                    if parsed and progress_task_id:
                        _append_task_log(progress_task_id, f"   ✓ {seg_label} · retry OK")
                except Exception as exc2:
                    if progress_task_id:
                        _append_task_log(progress_task_id,
                            f"   ❌ {seg_label} · retry DeepSeek : {str(exc2)[:120]}")
            if not parsed:
                with state_lock:
                    summary["segments_failed"] += 1
                    summary["details"].append({
                        "segment_id": seg_id,
                        "sub_part_name": sub_name or f"Sous-partie {sub_idx + 1}",
                        "passe": passe,
                        "status": "failed",
                        "reason": "JSON DeepSeek inparseable (après retry)",
                        "raw_preview": (raw or "")[:500],
                    })
                    _update_task(segments_failed=summary["segments_failed"])
                if progress_task_id:
                    _append_task_log(progress_task_id,
                        f"   ❌ {seg_label} · JSON inparseable (retry échoué)")
                continue

            conforme = bool(parsed.get("conforme"))
            violations = parsed.get("violations") or []
            patches_raw = parsed.get("patches") or []
            # Compat ascendante : si DeepSeek renvoie encore l'ancien format
            # `corrected_text`, on fabrique un patch unique pour ne pas casser.
            if not patches_raw and parsed.get("corrected_text"):
                legacy_corrected = (parsed.get("corrected_text") or "").strip()
                if legacy_corrected and legacy_corrected != text:
                    patches_raw = [{
                        "find": text,
                        "replace": legacy_corrected,
                        "reason": "Réponse legacy (corrected_text complet)",
                    }]

            corrected, applied_count, patch_errors = _apply_patches(text, patches_raw)
            patches_summary = []
            for idx, p in enumerate(patches_raw or []):
                if not isinstance(p, dict):
                    continue
                find_str = (p.get("find") or "").strip()
                applied_ok = bool(find_str) and find_str in text and text.count(find_str) == 1
                patches_summary.append({
                    "find": find_str,
                    "replace": p.get("replace") or "",
                    "reason": (p.get("reason") or "").strip(),
                    "applied": applied_ok,
                })

            if conforme or not patches_raw or applied_count == 0:
                with state_lock:
                    summary["segments_conforme"] += 1
                    summary["details"].append({
                        "segment_id": seg_id,
                        "sub_part_name": sub_name or f"Sous-partie {sub_idx + 1}",
                        "passe": passe,
                        "status": "conforme",
                        "violations": violations if not conforme else [],
                        "patches": patches_summary,
                        "patch_errors": patch_errors,
                    })
                    _update_task(segments_conforme=summary["segments_conforme"])
                if progress_task_id:
                    if patches_raw and applied_count == 0:
                        _append_task_log(progress_task_id,
                            f"   ⚠ {seg_label} : {len(patches_raw)} patch(s) proposés mais aucun applicable")
                    else:
                        _append_task_log(progress_task_id, f"   ✓ {seg_label} : conforme")
                continue

            entry = {
                "segment_id": seg_id,
                "sub_part_name": sub_name or f"Sous-partie {sub_idx + 1}",
                "sub_part_index": sub_idx,
                "passe": passe,
                "status": "would_modify" if dry_run else "modified",
                "violations": violations,
                "original_text": text,
                "corrected_text": corrected,
                "patches": patches_summary,
                "patches_applied": applied_count,
                "patch_errors": patch_errors,
                "words_before": int(wc or len(text.split())),
                "words_after": len(corrected.split()),
            }

            if not dry_run:
                with db_lock:  # sérialise les UPDATE SQLite
                    conn2 = get_db_connection()
                    cursor2 = conn2.cursor()
                    cursor2.execute(
                        """
                        UPDATE content_generation_segments
                        SET text_content = ?, word_count = ?, dirty = 1, reviewed = 0,
                            review_error = NULL, review_signature = NULL,
                            humanized = 0, humanization_error = NULL, humanization_signature = NULL
                        WHERE id = ?
                        """,
                        (corrected, len(corrected.split()), seg_id),
                    )
                    conn2.commit()
                    conn2.close()

            with state_lock:
                summary["segments_modified"] += 1
                summary["details"].append(entry)
                _update_task(segments_modified=summary["segments_modified"])
            if progress_task_id:
                _append_task_log(progress_task_id,
                    f"   ✏️ {seg_label} · {'à modifier' if dry_run else 'modifié'} "
                    f"({applied_count} patch(s), "
                    f"{entry['words_before']} → {entry['words_after']} mots, "
                    f"{len(violations)} règle(s))")
                if patch_errors:
                    _append_task_log(progress_task_id,
                        f"      ⚠ {len(patch_errors)} patch(s) ignoré(s) : "
                        f"{patch_errors[0][:120]}")

        if progress_task_id:
            _append_task_log(progress_task_id, f"✓ {sub_idx_label} : terminé")

    # Lance le pool de greenlets
    pool = eventlet.GreenPool(size=pool_size)
    pile = eventlet.GreenPile(pool)
    for sub_idx_key in group_keys:
        pile.spawn(_process_group, sub_idx_key)
    list(pile)  # bloque jusqu'à ce que tous les greenlets aient fini

    logger.info(
        f"📝 Revérif texte folder={folder_id} : "
        f"{summary['segments_examined']} examinés, "
        f"{summary['segments_modified']} {'à modifier' if dry_run else 'modifiés'}, "
        f"{summary['segments_conforme']} conformes, "
        f"{summary['segments_skipped']} skip, "
        f"{summary['segments_failed']} fail (dry_run={dry_run})"
    )
    return summary


def update_rules_markdown(folder_id: int, markdown: str) -> dict:
    """Permet l'édition manuelle du markdown des règles."""
    context = _fetch_context(folder_id)
    if not context:
        raise ValueError("Aucun job de contenu pour ce dossier")

    markdown = (markdown or "").strip()
    rules_count = _count_rules_in_markdown(markdown)
    path = _rules_markdown_path(folder_id, context["job_id"])
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown.rstrip() + "\n")

    _ensure_rules_table()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO content_script_rules
            (folder_id, job_id, rules_markdown, rules_count, source_annotations_count,
             model, markdown_path, generated_at, updated_at)
        VALUES (?, ?, ?, ?, 0, 'manual', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(folder_id, job_id) DO UPDATE SET
            rules_markdown = excluded.rules_markdown,
            rules_count = excluded.rules_count,
            markdown_path = excluded.markdown_path,
            updated_at = CURRENT_TIMESTAMP
        """,
        (folder_id, context["job_id"], markdown, rules_count, path),
    )
    conn.commit()
    conn.close()
    return get_rules(folder_id)
