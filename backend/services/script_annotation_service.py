"""Persist and export human review notes for generated TTS scripts."""

import logging
import os
from datetime import datetime

from config import FRANCE_TZ
from repositories.pipeline_repository import (
    create_script_annotation_row,
    ensure_script_annotations_table,
    get_content_segment_row_for_key,
    get_script_annotation_context,
    get_script_annotation_for_apply,
    list_script_annotation_rows,
    mark_script_annotation_applied,
    mark_script_annotation_deleted,
    mark_script_annotation_rejected,
    update_content_segment_plan_repair,
    update_script_annotation_correction,
    update_script_annotation_splice_result,
    update_script_annotations_markdown_path,
)
from services.content_pipeline.artifacts import (
    save_script_review_markdown,
    script_review_markdown_locator,
)
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

CORRECTION_MODEL = os.getenv("SCRIPT_ANNOTATION_MODEL", "deepseek-v4-pro")


def _ensure_annotations_table() -> None:
    """Create the annotation table lazily for already-deployed databases."""
    ensure_script_annotations_table()


def _now_str() -> str:
    return datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _markdown_filename(folder_id: int, job_id: int) -> str:
    return f"tts-script-review-folder-{folder_id}-job-{job_id}.md"


def _markdown_path(platform_id: int, folder_id: int, job_id: int) -> str:
    return script_review_markdown_locator(
        platform_id,
        folder_id,
        _markdown_filename(folder_id, job_id),
    )


def _fetch_context(folder_id: int) -> dict | None:
    row = get_script_annotation_context(folder_id)
    if not row:
        return None
    return {
        "job_id": row["job_id"],
        "platform_id": row["platform_id"],
        "program_title": row.get("program_title") or "",
        "folder_name": row.get("folder_name") or f"Dossier {folder_id}",
        "platform_name": row.get("platform_name") or f"Plateforme {row['platform_id']}",
    }


def _row_to_annotation(row) -> dict:
    if isinstance(row, dict):
        return {
            "id": row.get("id"),
            "folder_id": row.get("folder_id"),
            "job_id": row.get("job_id"),
            "source_type": row.get("source_type"),
            "sub_part_index": row.get("sub_part_index"),
            "passe": row.get("passe"),
            "bloc_number": row.get("bloc_number"),
            "filename": row.get("filename") or "",
            "selected_text": row.get("selected_text") or "",
            "comment": row.get("comment") or "",
            "status": row.get("status") or "open",
            "markdown_path": row.get("markdown_path") or "",
            "created_at": row.get("created_at") or "",
            "updated_at": row.get("updated_at") or "",
            "original_paragraph": row.get("original_paragraph") or "",
            "proposed_text": row.get("proposed_text") or "",
            "correction_status": row.get("correction_status") or "pending",
            "correction_error": row.get("correction_error") or "",
            "applied_at": row.get("applied_at") or "",
            "splice_status": row.get("splice_status") or "",
            "splice_error": row.get("splice_error") or "",
            "splice_blob_path": row.get("splice_blob_path") or "",
        }
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

    rows = list_script_annotation_rows(
        folder_id=folder_id,
        job_id=context["job_id"],
        include_deleted=include_deleted,
    )
    annotations = [_row_to_annotation(row) for row in rows]

    return {
        "context": context,
        "annotations": annotations,
        "markdown_path": _markdown_path(
            context["platform_id"],
            folder_id,
            context["job_id"],
        ),
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
    markdown, _ = build_script_annotations_markdown(folder_id)
    data = list_script_annotations(folder_id)
    context = data["context"]
    if context:
        path = save_script_review_markdown(
            context["platform_id"],
            folder_id,
            _markdown_filename(folder_id, context["job_id"]),
            markdown,
        )
        _ensure_annotations_table()
        update_script_annotations_markdown_path(
            folder_id=folder_id,
            job_id=context["job_id"],
            markdown_path=path,
        )
        return path
    raise ValueError("Aucun job de contenu pour ce dossier")


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

    # Important : original_paragraph = selected_text. DeepSeek réécrit STRICTEMENT
    # l'extrait surligné, pas un "paragraphe alentour" deviné. Avant : on tentait
    # _extract_paragraph_around(paragraph_context, selected_text) mais comme
    # `event.currentTarget.textContent` côté frontend collapse les sauts de ligne,
    # le code prenait le bloc entier comme paragraphe et DeepSeek réécrivait tout.
    paragraph_context = (payload.get("paragraph_context") or "").strip()[:MAX_PARAGRAPH_CHARS]
    original_paragraph = selected_text

    annotation_id = create_script_annotation_row(
        folder_id=folder_id,
        job_id=context["job_id"],
        source_type=source_type,
        sub_part_index=sub_part_index,
        passe=passe,
        bloc_number=bloc_number,
        filename=filename,
        selected_text=selected_text,
        comment=comment,
        original_paragraph=original_paragraph,
    )

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

    changed = mark_script_annotation_deleted(
        annotation_id=annotation_id,
        folder_id=folder_id,
        job_id=context["job_id"],
    )
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
        "Tu reçois un extrait précis du script TTS et un commentaire qui indique ce qui ne va pas. "
        "Ta tâche : réécrire UNIQUEMENT cet extrait en appliquant le commentaire — pas plus, pas moins.\n\n"
        "Contraintes :\n"
        "- Réécris STRICTEMENT le périmètre de l'extrait. Ne déborde pas avant ni après.\n"
        "- Le nombre de mots produit doit rester proche du nombre de mots de l'extrait (±20%).\n"
        "- Conserve le sens pédagogique et le niveau RNCP.\n"
        "- Conserve un ton oral fluide adapté à un TTS (phrases pas trop longues, transitions naturelles).\n"
        "- Conserve les tags audio existants entre crochets (ex. [pause], [calm], [emphasis]) si présents dans l'extrait.\n"
        "- Réponds uniquement par l'extrait corrigé en texte brut. "
        "Pas de préambule, pas de balise de code, pas de guillemets ouvrants/fermants, pas d'explication, pas de markdown.\n\n"
        f"Extrait à réécrire :\n{paragraph}\n\n"
        f"Commentaire du formateur :\n{comment}\n\n"
        "Extrait corrigé :"
    )

    output = post_message(
        [{"role": "user", "content": prompt}],
        max_tokens=4000,
        model=CORRECTION_MODEL,
        timeout=180,
    )
    return (output or "").strip()


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

    update_script_annotation_correction(
        annotation_id=annotation_id,
        folder_id=folder_id,
        job_id=job_id,
        original_paragraph=paragraph,
        proposed_text=corrected,
        correction_status=new_status,
        correction_error=error_msg or None,
    )


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

    row = get_script_annotation_for_apply(
        annotation_id=annotation_id,
        folder_id=folder_id,
        job_id=context["job_id"],
    )
    if not row:
        raise ValueError("Annotation introuvable")

    source_type = row["source_type"]
    sub_part_index = row["sub_part_index"]
    passe = row["passe"]
    proposed_text = row.get("proposed_text") or ""
    original_paragraph = row.get("original_paragraph") or ""
    correction_status = row.get("correction_status")
    if correction_status != "proposed" or not (proposed_text or "").strip():
        raise ValueError("Pas de correction proposée à appliquer")

    bloc_number = row.get("bloc_number")
    filename = row.get("filename") or ""

    if source_type == "segment" and sub_part_index is not None and passe is not None and original_paragraph:
        seg = get_content_segment_row_for_key(
            job_id=context["job_id"],
            sub_part_index=sub_part_index,
            passe=passe,
        )
        if seg and seg.get("text_content"):
            seg_id = seg["id"]
            current_text = seg["text_content"]
            if original_paragraph in current_text:
                new_text = current_text.replace(original_paragraph, proposed_text, 1)
                word_count = len(new_text.split())
                update_content_segment_plan_repair(
                    segment_id=seg_id,
                    text_content=new_text,
                    word_count=word_count,
                )

    mark_script_annotation_applied(annotation_id)

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

    update_script_annotation_splice_result(
        annotation_id=annotation_id,
        splice_status=splice_result["status"],
        splice_error=splice_result["error"] or None,
        splice_blob_path=splice_result["blob_path"] or None,
    )

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

    changed = mark_script_annotation_rejected(
        annotation_id=annotation_id,
        folder_id=folder_id,
        job_id=context["job_id"],
    )
    if not changed:
        raise ValueError("Annotation introuvable")

    path = write_script_annotations_markdown(folder_id)
    return {
        "annotations": list_script_annotations(folder_id)["annotations"],
        "markdown_path": path,
    }
