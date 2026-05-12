"""Persist and export human review notes for generated TTS scripts."""

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

MAX_SELECTED_TEXT_CHARS = 4000
MAX_COMMENT_CHARS = 3000
MAX_PARAGRAPH_CHARS = 8000

CORRECTION_MODEL = os.getenv("SCRIPT_ANNOTATION_MODEL", DEEPSEEK_DEFAULT_MODEL)


def _ensure_annotations_table() -> None:
    """Create the annotation table lazily for already-deployed databases."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS content_script_annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'course',
            sub_part_index INTEGER,
            passe INTEGER,
            bloc_number INTEGER,
            filename TEXT,
            selected_text TEXT NOT NULL,
            comment TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            markdown_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (folder_id) REFERENCES cours_folders(id),
            FOREIGN KEY (job_id) REFERENCES content_generation_jobs(id)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_content_script_annotations_folder_job
        ON content_script_annotations(folder_id, job_id, status)
        """
    )
    for ddl in (
        "ALTER TABLE content_script_annotations ADD COLUMN original_paragraph TEXT",
        "ALTER TABLE content_script_annotations ADD COLUMN proposed_text TEXT",
        "ALTER TABLE content_script_annotations ADD COLUMN correction_status TEXT DEFAULT 'pending'",
        "ALTER TABLE content_script_annotations ADD COLUMN correction_error TEXT",
        "ALTER TABLE content_script_annotations ADD COLUMN applied_at TIMESTAMP",
        "ALTER TABLE content_script_annotations ADD COLUMN splice_status TEXT",
        "ALTER TABLE content_script_annotations ADD COLUMN splice_error TEXT",
        "ALTER TABLE content_script_annotations ADD COLUMN splice_blob_path TEXT",
    ):
        try:
            cursor.execute(ddl)
        except Exception:
            pass
    conn.commit()
    conn.close()


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
        "original_paragraph": row[14] or "",
        "proposed_text": row[15] or "",
        "correction_status": row[16] or "pending",
        "correction_error": row[17] or "",
        "applied_at": row[18] or "",
        "splice_status": row[19] or "",
        "splice_error": row[20] or "",
        "splice_blob_path": row[21] or "",
    }


def list_script_annotations(folder_id: int, *, include_deleted: bool = False) -> dict:
    context = _fetch_context(folder_id)
    if not context:
        return {"context": None, "annotations": [], "markdown_path": ""}

    _ensure_annotations_table()

    conn = get_db_connection()
    cursor = conn.cursor()
    where_deleted = "" if include_deleted else "AND status != 'deleted'"
    cursor.execute(
        f"""
        SELECT id, folder_id, job_id, source_type, sub_part_index, passe,
               bloc_number, filename, selected_text, comment, status,
               markdown_path, created_at, updated_at,
               original_paragraph, proposed_text, correction_status,
               correction_error, applied_at,
               splice_status, splice_error, splice_blob_path
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
        _ensure_annotations_table()
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

    _ensure_annotations_table()

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

    paragraph_context = (payload.get("paragraph_context") or "").strip()[:MAX_PARAGRAPH_CHARS]
    original_paragraph = _extract_paragraph_around(paragraph_context, selected_text)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO content_script_annotations
            (folder_id, job_id, source_type, sub_part_index, passe, bloc_number,
             filename, selected_text, comment, status, original_paragraph,
             correction_status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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
            original_paragraph,
        ),
    )
    annotation_id = cursor.lastrowid
    conn.commit()
    conn.close()

    _attach_correction(
        annotation_id,
        folder_id,
        context["job_id"],
        paragraph=original_paragraph,
        selected_text=selected_text,
        comment=comment,
    )

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

    _ensure_annotations_table()

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


def correct_paragraph_with_llm(paragraph: str, selected_text: str, comment: str) -> str:
    """Réécrit `paragraph` en appliquant `comment` sur `selected_text`.

    Retourne le paragraphe corrigé en texte brut. Lève AnthropicAPIError /
    AnthropicRateLimitError si l'appel échoue.
    """
    paragraph = (paragraph or "").strip()[:MAX_PARAGRAPH_CHARS]
    selected_text = (selected_text or "").strip()[:MAX_SELECTED_TEXT_CHARS]
    comment = (comment or "").strip()[:MAX_COMMENT_CHARS]
    if not paragraph:
        paragraph = selected_text

    prompt = (
        "Tu es un agent de correction du script d'un cours audio destiné à un public RNCP. "
        "Tu reçois un paragraphe lu en TTS, un extrait précis surligné par le formateur, "
        "et un commentaire qui indique ce qui ne va pas. Ta tâche : réécrire le paragraphe "
        "complet en appliquant le commentaire sur l'extrait.\n\n"
        "Contraintes :\n"
        "- Conserve le sens pédagogique et le niveau RNCP du contenu.\n"
        "- Conserve un ton oral fluide adapté à un TTS (phrases pas trop longues, transitions naturelles).\n"
        "- Conserve approximativement la longueur du paragraphe d'origine.\n"
        "- Ne modifie pas ce qui n'est pas concerné par le commentaire.\n"
        "- Réponds uniquement par le paragraphe corrigé en texte brut. "
        "Pas de préambule, pas de balise, pas de guillemets, pas d'explication, pas de markdown.\n\n"
        f"Paragraphe d'origine :\n{paragraph}\n\n"
        f"Extrait surligné :\n{selected_text}\n\n"
        f"Commentaire :\n{comment}\n\n"
        "Paragraphe corrigé :"
    )

    output = post_message(
        [{"role": "user", "content": prompt}],
        max_tokens=4000,
        model=CORRECTION_MODEL,
        timeout=180,
    )
    return (output or "").strip()


def _extract_paragraph_around(full_text: str, selected_text: str) -> str:
    """Trouve le paragraphe (séparé par lignes vides) contenant `selected_text`.

    Si l'extrait chevauche plusieurs paragraphes, retourne leur union. Si rien
    ne matche, retourne `selected_text` lui-même.
    """
    text = (full_text or "").strip()
    needle = (selected_text or "").strip()
    if not text or not needle:
        return needle

    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return needle

    norm_needle = " ".join(needle.split())
    hits = []
    for idx, paragraph in enumerate(paragraphs):
        norm = " ".join(paragraph.split())
        if norm_needle in norm:
            return paragraph.strip()
        if norm and norm in norm_needle:
            hits.append(idx)

    if hits:
        first, last = min(hits), max(hits)
        return "\n\n".join(p.strip() for p in paragraphs[first : last + 1])

    needle_lower = norm_needle.lower()
    for paragraph in paragraphs:
        if needle_lower in " ".join(paragraph.split()).lower():
            return paragraph.strip()
    return needle


def _attach_correction(annotation_id: int, folder_id: int, job_id: int, *,
                       paragraph: str, selected_text: str, comment: str) -> None:
    """Génère la correction DeepSeek et la persiste sur l'annotation.

    Mode best-effort : si l'appel LLM échoue, on stocke l'erreur et on laisse
    l'annotation utilisable (status open, correction_status=error).
    """
    _ensure_annotations_table()
    try:
        corrected = correct_paragraph_with_llm(paragraph, selected_text, comment)
        new_status = "proposed" if corrected else "error"
        error_msg = "" if corrected else "DeepSeek a renvoyé une réponse vide"
    except (AnthropicAPIError, AnthropicRateLimitError) as exc:
        corrected = ""
        new_status = "error"
        error_msg = str(exc)
        logger.warning(f"⚠️ Correction DeepSeek échouée (annotation {annotation_id}) : {exc}")
    except Exception as exc:
        corrected = ""
        new_status = "error"
        error_msg = str(exc)
        logger.exception(f"❌ Correction DeepSeek annotation {annotation_id}")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE content_script_annotations
        SET original_paragraph = ?, proposed_text = ?, correction_status = ?,
            correction_error = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND folder_id = ? AND job_id = ?
        """,
        (
            paragraph,
            corrected,
            new_status,
            error_msg or None,
            annotation_id,
            folder_id,
            job_id,
        ),
    )
    conn.commit()
    conn.close()


def apply_script_annotation(folder_id: int, annotation_id: int) -> dict:
    """Marque l'annotation comme appliquée et propage le texte corrigé en base.

    Pour les annotations source_type=segment : remplace l'extrait dans
    content_generation_segments.text_content du segment concerné. Pour les
    autres : l'annotation est marquée applied sans patch DB texte (la suite
    Phase B prendra le relais pour le splice MP3).
    """
    context = _fetch_context(folder_id)
    if not context:
        raise ValueError("Aucun job de contenu pour ce dossier")
    _ensure_annotations_table()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT source_type, sub_part_index, passe, selected_text,
               proposed_text, original_paragraph, correction_status
        FROM content_script_annotations
        WHERE id = ? AND folder_id = ? AND job_id = ? AND status != 'deleted'
        """,
        (annotation_id, folder_id, context["job_id"]),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError("Annotation introuvable")

    source_type, sub_part_index, passe, selected_text, proposed_text, original_paragraph, correction_status = row
    if correction_status != "proposed" or not (proposed_text or "").strip():
        conn.close()
        raise ValueError("Pas de correction proposée à appliquer")

    # Récupère aussi bloc_number/filename pour décider d'un éventuel splice MP3.
    cursor.execute(
        """
        SELECT bloc_number, filename
        FROM content_script_annotations WHERE id = ?
        """,
        (annotation_id,),
    )
    extra = cursor.fetchone()
    bloc_number = extra[0] if extra else None
    filename = (extra[1] if extra else None) or ""

    if source_type == "segment" and sub_part_index is not None and passe is not None and original_paragraph:
        cursor.execute(
            """
            SELECT id, text_content
            FROM content_generation_segments
            WHERE job_id = ? AND sub_part_index = ? AND passe = ?
            """,
            (context["job_id"], sub_part_index, passe),
        )
        seg = cursor.fetchone()
        if seg and seg[1]:
            seg_id, current_text = seg[0], seg[1]
            if original_paragraph in current_text:
                new_text = current_text.replace(original_paragraph, proposed_text, 1)
                word_count = len(new_text.split())
                cursor.execute(
                    """
                    UPDATE content_generation_segments
                    SET text_content = ?, word_count = ?, dirty = 1, reviewed = 0,
                        review_error = NULL
                    WHERE id = ?
                    """,
                    (new_text, word_count, seg_id),
                )

    cursor.execute(
        """
        UPDATE content_script_annotations
        SET correction_status = 'applied', applied_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (annotation_id,),
    )
    conn.commit()
    conn.close()

    # Splice MP3 chirurgical pour les annotations source_type=course.
    # Pour les annotations source_type=segment, la régénération TTS sélective
    # (dirty=1 sur le segment) couvre déjà la mise à jour audio à la prochaine
    # régénération du bloc — pas de splice direct du MP3 ici.
    splice_result = {"status": "skipped", "blob_path": "", "error": "source_type != course"}
    if source_type == "course":
        splice_result = _attempt_audio_splice(
            folder_id,
            context["job_id"],
            context["platform_id"],
            annotation_id,
            bloc_number=bloc_number,
            filename=filename,
            original_paragraph=original_paragraph,
            proposed_text=proposed_text,
        )

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE content_script_annotations
        SET splice_status = ?, splice_error = ?, splice_blob_path = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            splice_result["status"],
            splice_result["error"] or None,
            splice_result["blob_path"] or None,
            annotation_id,
        ),
    )
    conn.commit()
    conn.close()

    path = write_script_annotations_markdown(folder_id)
    return {
        "annotations": list_script_annotations(folder_id)["annotations"],
        "markdown_path": path,
    }


def _find_word_range(haystack: str, needle: str) -> tuple[int, int] | None:
    haystack_norm = " ".join((haystack or "").split())
    needle_norm = " ".join((needle or "").split())
    if not haystack_norm or not needle_norm:
        return None
    pos = haystack_norm.find(needle_norm)
    if pos < 0:
        pos = haystack_norm.lower().find(needle_norm.lower())
    if pos < 0:
        return None
    before = haystack_norm[:pos]
    word_start = len(before.split())
    word_end = word_start + len(needle_norm.split())
    return word_start, word_end


def _course_bloc_text(folder_id: int, bloc_number: int) -> str | None:
    """Récupère le texte complet d'un bloc cours via le plan UI."""
    try:
        from services.content_generation_service import get_course_script_plan_for_ui
        plan = get_course_script_plan_for_ui(folder_id)
        for bloc in plan.get("course_blocs") or []:
            if int(bloc.get("bloc_number") or 0) == int(bloc_number):
                return bloc.get("text") or ""
    except Exception as exc:
        logger.warning(f"⚠️ Lecture course_blocs impossible folder={folder_id} bloc={bloc_number}: {exc}")
    return None


def _splice_recompute_timings(timings: list, audio_filename: str, splice_start_sec: float,
                              splice_end_sec: float, new_dur_sec: float,
                              word_start: int, word_end: int, slide_id: str) -> list:
    """Remplace les timings dans [splice_start_sec, splice_end_sec] par un seul
    timing patch, et décale les suivants de la différence de durée."""
    delta_sec = new_dur_sec - (splice_end_sec - splice_start_sec)
    out = []
    insertion_done = False
    patch = {
        "slide_id": slide_id,
        "audio_filename": audio_filename,
        "start_time": round(splice_start_sec, 3),
        "end_time": round(splice_start_sec + new_dur_sec, 3),
        "duration": round(new_dur_sec, 3),
        "word_start": int(word_start),
        "word_end": int(word_end),
        "patched": True,
    }
    for item in timings or []:
        if item.get("audio_filename") != audio_filename:
            out.append(item)
            continue
        t_start = float(item.get("start_time") or 0)
        t_end = float(item.get("end_time") or 0)
        if t_end <= splice_start_sec + 1e-6:
            out.append(item)
        elif t_start >= splice_end_sec - 1e-6:
            if not insertion_done:
                out.append(patch)
                insertion_done = True
            shifted = dict(item)
            shifted["start_time"] = round(t_start + delta_sec, 3)
            shifted["end_time"] = round(t_end + delta_sec, 3)
            out.append(shifted)
        # else : chunk dans la plage, supprimé (remplacé par patch)
    if not insertion_done:
        out.append(patch)
    return out


def splice_chunk_audio(
    folder_id: int,
    platform_id: int,
    *,
    deck: dict,
    audio_sync: dict,
    filename: str,
    splice_start_sec: float,
    splice_end_sec: float,
    new_text: str,
    word_start: int,
    word_end_target: int,
    slide_id_for_patch: str,
) -> dict:
    """Primitive de splice ms-précis réutilisable.

    Effectue : TTS(new_text) → download MP3 → splice pydub (crossfade 25ms) →
    upload Azure → recompute timings → update audio_sync.

    Retourne {"status": done|error, "blob_path": str, "error": str,
              "new_duration_sec": float}.
    """
    out = {"status": "error", "blob_path": "", "error": "", "new_duration_sec": 0.0}
    try:
        from services.tts_service import convert_to_speech
        from services.azure_blob_service import download_blob, upload_blob, CONTAINER_AUDIOS
        from services.script_slide_generation_service import update_script_slide_deck_audio_sync
        from pydub import AudioSegment
        import io

        splice_start_ms = max(0, int(splice_start_sec * 1000))
        splice_end_ms = max(splice_start_ms + 1, int(splice_end_sec * 1000))

        new_tts_bytes = convert_to_speech(new_text)
        new_segment = AudioSegment.from_file(io.BytesIO(new_tts_bytes), format="mp3")

        blob_path = f"platform-{platform_id}/folder-{folder_id}/playlist/{filename}"
        original_bytes = download_blob(CONTAINER_AUDIOS, blob_path)
        original = AudioSegment.from_file(io.BytesIO(original_bytes), format="mp3")

        head = original[:splice_start_ms]
        tail = original[splice_end_ms:]
        crossfade = 25 if len(head) > 50 and len(new_segment) > 50 else 0
        if crossfade:
            patched = head.append(new_segment, crossfade=crossfade)
        else:
            patched = head + new_segment
        if crossfade and len(tail) > 50:
            patched = patched.append(tail, crossfade=crossfade)
        else:
            patched = patched + tail

        buf = io.BytesIO()
        patched.export(buf, format="mp3", bitrate="128k")
        upload_blob(CONTAINER_AUDIOS, blob_path, buf.getvalue())

        new_dur_sec = len(new_segment) / 1000.0
        timings = audio_sync.get("timings") or []
        new_timings = _splice_recompute_timings(
            timings,
            filename,
            splice_start_sec,
            splice_end_sec,
            new_dur_sec,
            word_start,
            word_end_target,
            slide_id_for_patch,
        )
        audio_sync_updated = dict(audio_sync)
        audio_sync_updated["timings"] = new_timings
        update_script_slide_deck_audio_sync(deck["deck_id"], audio_sync_updated)

        out["status"] = "done"
        out["blob_path"] = blob_path
        out["new_duration_sec"] = new_dur_sec
        logger.info(
            f"✂️ Splice {filename} [{splice_start_sec:.2f}s-{splice_end_sec:.2f}s] "
            f"→ {new_dur_sec:.2f}s (Δ={new_dur_sec - (splice_end_sec - splice_start_sec):+.2f}s) "
            f"via {slide_id_for_patch}"
        )
    except Exception as exc:
        out["error"] = str(exc)[:500]
        logger.exception(f"❌ Splice {filename} échoué")
    return out


def _attempt_audio_splice(
    folder_id: int,
    job_id: int,
    platform_id: int,
    annotation_id: int,
    *,
    bloc_number: int | None,
    filename: str,
    original_paragraph: str,
    proposed_text: str,
) -> dict:
    """Tente le splice ms-précis du MP3 du bloc cours concerné.

    Retourne {"status": done|skipped|error, "blob_path": str, "error": str}.
    Best-effort : toute exception est captée et renvoyée en status=error.
    """
    out = {"status": "skipped", "blob_path": "", "error": ""}
    if not filename or not bloc_number or not original_paragraph or not proposed_text:
        out["error"] = "données manquantes (filename/bloc_number/paragraph)"
        return out

    try:
        from services.script_slide_generation_service import get_latest_script_slide_deck
        deck = get_latest_script_slide_deck(folder_id, job_id)
        if not deck:
            out["error"] = "Aucun script_slide_deck pour ce job"
            return out
        audio_sync = deck.get("audio_sync") or {}
        timings = audio_sync.get("timings") or []
        if not timings:
            out["error"] = "audio_sync.timings absent"
            return out

        bloc_text = _course_bloc_text(folder_id, int(bloc_number))
        if not bloc_text:
            out["error"] = f"texte bloc {bloc_number} introuvable"
            return out

        rng = _find_word_range(bloc_text, original_paragraph)
        if not rng:
            out["error"] = "paragraphe introuvable dans le texte du bloc"
            return out
        word_start, word_end = rng

        overlapping = [
            t for t in timings
            if t.get("audio_filename") == filename
            and (
                (int(t.get("word_start") or -1) < word_end)
                and (int(t.get("word_end") or -1) > word_start)
            )
        ]
        if not overlapping:
            out["error"] = f"aucun timing ne couvre word_range=[{word_start},{word_end}] pour {filename}"
            return out

        splice_start_sec = min(float(t.get("start_time") or 0) for t in overlapping)
        splice_end_sec = max(float(t.get("end_time") or 0) for t in overlapping)
        new_word_end = word_start + len(" ".join(proposed_text.split()).split())
        result = splice_chunk_audio(
            folder_id,
            platform_id,
            deck=deck,
            audio_sync=audio_sync,
            filename=filename,
            splice_start_sec=splice_start_sec,
            splice_end_sec=splice_end_sec,
            new_text=proposed_text,
            word_start=word_start,
            word_end_target=new_word_end,
            slide_id_for_patch=f"patched-{annotation_id}",
        )
        out["status"] = result["status"]
        out["blob_path"] = result["blob_path"]
        out["error"] = result["error"]
    except Exception as exc:
        out["status"] = "error"
        out["error"] = str(exc)[:500]
        logger.exception(f"❌ Splice annotation {annotation_id} échoué")
    return out


def reject_script_annotation(folder_id: int, annotation_id: int) -> dict:
    context = _fetch_context(folder_id)
    if not context:
        raise ValueError("Aucun job de contenu pour ce dossier")
    _ensure_annotations_table()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE content_script_annotations
        SET correction_status = 'rejected', updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND folder_id = ? AND job_id = ? AND status != 'deleted'
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
