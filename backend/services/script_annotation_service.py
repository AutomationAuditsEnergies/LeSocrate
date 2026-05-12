"""Persist and export human review notes for generated TTS scripts."""

import os
from datetime import datetime

from config import DB_PATH, FRANCE_TZ
from database.db import get_db_connection


MAX_SELECTED_TEXT_CHARS = 4000
MAX_COMMENT_CHARS = 3000


def _now_str() -> str:
    return datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _notes_dir() -> str:
    base_dir = os.path.dirname(DB_PATH) or os.getcwd()
    path = os.path.join(base_dir, "tts_script_reviews")
    os.makedirs(path, exist_ok=True)
    return path


def _markdown_filename(folder_id: int, job_id: int) -> str:
    return f"tts-script-review-folder-{folder_id}-job-{job_id}.md"


def _markdown_path(folder_id: int, job_id: int) -> str:
    return os.path.join(_notes_dir(), _markdown_filename(folder_id, job_id))


def _fetch_context(folder_id: int) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT j.id, j.platform_id, j.program_title, f.name, pc.name
        FROM content_generation_jobs j
        JOIN cours_folders f ON f.id = j.folder_id
        LEFT JOIN platform_config pc ON pc.id = j.platform_id
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
        "platform_name": row[4] or f"Plateforme {row[1]}",
    }


def _row_to_annotation(row) -> dict:
    return {
        "id": row[0],
        "folder_id": row[1],
        "job_id": row[2],
        "source_type": row[3],
        "sub_part_index": row[4],
        "passe": row[5],
        "bloc_number": row[6],
        "filename": row[7] or "",
        "selected_text": row[8] or "",
        "comment": row[9] or "",
        "status": row[10] or "open",
        "markdown_path": row[11] or "",
        "created_at": row[12] or "",
        "updated_at": row[13] or "",
    }


def list_script_annotations(folder_id: int, *, include_deleted: bool = False) -> dict:
    context = _fetch_context(folder_id)
    if not context:
        return {"context": None, "annotations": [], "markdown_path": ""}

    conn = get_db_connection()
    cursor = conn.cursor()
    where_deleted = "" if include_deleted else "AND status != 'deleted'"
    cursor.execute(
        f"""
        SELECT id, folder_id, job_id, source_type, sub_part_index, passe,
               bloc_number, filename, selected_text, comment, status,
               markdown_path, created_at, updated_at
        FROM content_script_annotations
        WHERE folder_id = ? AND job_id = ? {where_deleted}
        ORDER BY created_at ASC, id ASC
        """,
        (folder_id, context["job_id"]),
    )
    annotations = [_row_to_annotation(row) for row in cursor.fetchall()]
    conn.close()

    return {
        "context": context,
        "annotations": annotations,
        "markdown_path": _markdown_path(folder_id, context["job_id"]),
    }


def _annotation_label(annotation: dict) -> str:
    source_type = annotation.get("source_type")
    if source_type == "segment":
        sub_idx = annotation.get("sub_part_index")
        passe = annotation.get("passe")
        if sub_idx is not None and passe is not None:
            return f"Sous-partie {int(sub_idx) + 1}, passe {passe}"
        return "Segment source"
    if source_type == "course":
        bloc = annotation.get("bloc_number")
        filename = annotation.get("filename")
        if bloc:
            return f"Cours audio {bloc}" + (f" ({filename})" if filename else "")
        return filename or "Cours audio"
    return source_type or "Source inconnue"


def _quote_markdown(text: str) -> str:
    lines = (text or "").strip().splitlines() or [""]
    return "\n".join(f"> {line}" if line else ">" for line in lines)


def build_script_annotations_markdown(folder_id: int) -> tuple[str, str]:
    data = list_script_annotations(folder_id)
    context = data["context"]
    if not context:
        raise ValueError("Aucun job de contenu pour ce dossier")

    annotations = data["annotations"]
    path = data["markdown_path"]
    generated_at = _now_str()

    lines = [
        f"# Revue script TTS - {context['program_title'] or context['folder_name']}",
        "",
        f"- Plateforme: {context['platform_name']} (id {context['platform_id']})",
        f"- Dossier cours: {context['folder_name']} (id {folder_id})",
        f"- Content job: {context['job_id']}",
        f"- Genere le: {generated_at}",
        f"- Annotations ouvertes: {len(annotations)}",
        "",
        "## Consigne pour l'agent de correction",
        "",
        "Relire les annotations dans l'ordre, retrouver chaque extrait dans le script TTS source, appliquer le commentaire sans changer le niveau RNCP ni le ton oral, puis marquer les segments corriges comme dirty avant de relancer la generation audio. Utiliser DeepSeek via le client Anthropic-compatible deja configure si une correction automatique est lancee.",
        "",
        "## Annotations",
        "",
    ]

    if not annotations:
        lines.append("_Aucune annotation ouverte._")
    else:
        for index, annotation in enumerate(annotations, start=1):
            lines.extend(
                [
                    f"### {index}. {_annotation_label(annotation)}",
                    "",
                    f"- Statut: {annotation.get('status') or 'open'}",
                    f"- Cree le: {annotation.get('created_at') or ''}",
                    f"- Reference: source_type={annotation.get('source_type')}, sub_part_index={annotation.get('sub_part_index')}, passe={annotation.get('passe')}, bloc_number={annotation.get('bloc_number')}, filename={annotation.get('filename') or ''}",
                    "",
                    "**Commentaire**",
                    "",
                    annotation.get("comment") or "",
                    "",
                    "**Extrait selectionne**",
                    "",
                    _quote_markdown(annotation.get("selected_text") or ""),
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n", path


def write_script_annotations_markdown(folder_id: int) -> str:
    markdown, path = build_script_annotations_markdown(folder_id)
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown)

    data = list_script_annotations(folder_id)
    context = data["context"]
    if context:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE content_script_annotations
            SET markdown_path = ?, updated_at = CURRENT_TIMESTAMP
            WHERE folder_id = ? AND job_id = ? AND status != 'deleted'
            """,
            (path, folder_id, context["job_id"]),
        )
        conn.commit()
        conn.close()
    return path


def create_script_annotation(folder_id: int, payload: dict) -> dict:
    context = _fetch_context(folder_id)
    if not context:
        raise ValueError("Aucun job de contenu pour ce dossier")

    source_type = (payload.get("source_type") or "").strip()
    if source_type not in {"segment", "course"}:
        raise ValueError("source_type doit valoir 'segment' ou 'course'")

    selected_text = (payload.get("selected_text") or "").strip()
    comment = (payload.get("comment") or "").strip()
    if len(selected_text) < 3:
        raise ValueError("Selection trop courte")
    if not comment:
        raise ValueError("Commentaire requis")

    selected_text = selected_text[:MAX_SELECTED_TEXT_CHARS]
    comment = comment[:MAX_COMMENT_CHARS]

    sub_part_index = payload.get("sub_part_index")
    passe = payload.get("passe")
    bloc_number = payload.get("bloc_number")
    filename = (payload.get("filename") or "").strip()[:255]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO content_script_annotations
            (folder_id, job_id, source_type, sub_part_index, passe, bloc_number,
             filename, selected_text, comment, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (
            folder_id,
            context["job_id"],
            source_type,
            sub_part_index,
            passe,
            bloc_number,
            filename,
            selected_text,
            comment,
        ),
    )
    annotation_id = cursor.lastrowid
    conn.commit()
    conn.close()

    path = write_script_annotations_markdown(folder_id)
    annotations = list_script_annotations(folder_id)["annotations"]
    created = next((item for item in annotations if item["id"] == annotation_id), None)
    return {
        "annotation": created,
        "annotations": annotations,
        "markdown_path": path,
    }


def delete_script_annotation(folder_id: int, annotation_id: int) -> dict:
    data = list_script_annotations(folder_id)
    context = data["context"]
    if not context:
        raise ValueError("Aucun job de contenu pour ce dossier")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE content_script_annotations
        SET status = 'deleted', updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND folder_id = ? AND job_id = ?
        """,
        (annotation_id, folder_id, context["job_id"]),
    )
    changed = cursor.rowcount
    conn.commit()
    conn.close()
    if not changed:
        raise ValueError("Annotation introuvable")

    path = write_script_annotations_markdown(folder_id)
    return {
        "annotations": list_script_annotations(folder_id)["annotations"],
        "markdown_path": path,
    }
