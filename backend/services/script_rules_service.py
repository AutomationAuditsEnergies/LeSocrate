"""Apprentissage transversal des règles à partir des annotations du script TTS.

Lit toutes les annotations corrigées (status applied) d'un dossier, demande à
DeepSeek d'en extraire des règles transversales, et persiste le markdown de
règles. Ce markdown alimente la Phase 3b (revérif post-TTS) qui patche les
chunks non-conformes via la primitive de splice MP3.
"""

import logging
import os
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

RULES_MODEL = os.getenv("SCRIPT_RULES_MODEL", DEEPSEEK_DEFAULT_MODEL)
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
