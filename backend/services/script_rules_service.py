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

from repositories.pipeline_repository import (
    ensure_script_rules_table,
    get_script_rules_context,
    get_script_rules_row,
    list_script_rule_annotation_rows,
    update_script_rules_markdown_path,
    upsert_generated_script_rules,
    upsert_manual_script_rules,
)
from services.content_pipeline.artifacts import (
    save_script_review_markdown,
    script_review_markdown_locator,
)
from utils.deepseek_client import (
    DEEPSEEK_DEFAULT_MODEL,
    DeepSeekAPIError,
    DeepSeekRateLimitError,
    post_message,
)


logger = logging.getLogger(__name__)

RULES_MODEL = os.getenv("SCRIPT_RULES_MODEL", "deepseek-v4-pro")
REVIEW_MODEL = os.getenv("SCRIPT_RULES_REVIEW_MODEL", "deepseek-v4-pro")
MIN_ANNOTATIONS_FOR_EXTRACTION = 1


def _ensure_rules_table() -> None:
    ensure_script_rules_table()


def _rules_markdown_filename(folder_id: int, job_id: int) -> str:
    return f"regles-folder-{folder_id}-job-{job_id}.md"


def _rules_markdown_path(platform_id: int, folder_id: int, job_id: int) -> str:
    return script_review_markdown_locator(
        platform_id,
        folder_id,
        _rules_markdown_filename(folder_id, job_id),
    )


def _fetch_context(folder_id: int) -> dict | None:
    row = get_script_rules_context(folder_id)
    if not row:
        return None
    return {
        "job_id": row["job_id"],
        "platform_id": row["platform_id"],
        "program_title": row.get("program_title") or "",
        "folder_name": row.get("folder_name") or f"Dossier {folder_id}",
    }


def _fetch_applied_annotations(folder_id: int, job_id: int) -> list[dict]:
    """Annotations utilisables pour l'extraction : applied (corrections validées
    par l'humain) et rejected (signal de ce qu'il ne FAUT pas faire)."""
    rows = list_script_rule_annotation_rows(folder_id=folder_id, job_id=job_id)
    return [
        {
            "id": r.get("id"),
            "source_type": r.get("source_type"),
            "selected_text": r.get("selected_text") or "",
            "comment": r.get("comment") or "",
            "original_paragraph": r.get("original_paragraph") or "",
            "proposed_text": r.get("proposed_text") or "",
            "correction_status": r.get("correction_status") or "",
            "bloc_number": r.get("bloc_number"),
            "filename": r.get("filename") or "",
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
    except (DeepSeekAPIError, DeepSeekRateLimitError) as exc:
        logger.warning(f"⚠️ Extraction règles DeepSeek échouée folder={folder_id}: {exc}")
        raise ValueError(f"Erreur DeepSeek : {exc}")

    markdown = (markdown or "").strip()
    if not markdown:
        raise ValueError("DeepSeek a renvoyé une réponse vide")

    path = save_script_review_markdown(
        context["platform_id"],
        folder_id,
        _rules_markdown_filename(folder_id, context["job_id"]),
        markdown.rstrip() + "\n",
    )

    rules_count = _count_rules_in_markdown(markdown)
    _ensure_rules_table()
    upsert_generated_script_rules(
        folder_id=folder_id,
        job_id=context["job_id"],
        rules_markdown=markdown,
        rules_count=rules_count,
        source_annotations_count=len(annotations),
        model=RULES_MODEL,
        markdown_path=path,
    )

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
    row = get_script_rules_row(folder_id=folder_id, job_id=context["job_id"])

    if not row:
        return {
            "context": context,
            "rules_markdown": "",
            "rules_count": 0,
            "source_annotations_count": 0,
            "markdown_path": _rules_markdown_path(
                context["platform_id"], folder_id, context["job_id"]
            ),
            "model": "",
            "generated_at": "",
            "updated_at": "",
        }

    rules_markdown = row.get("rules_markdown") or ""
    expected_path = _rules_markdown_path(
        context["platform_id"], folder_id, context["job_id"]
    )
    markdown_path = row.get("markdown_path") or expected_path
    if (
        rules_markdown
        and expected_path.startswith("azureblob://")
        and not markdown_path.startswith("azureblob://")
    ):
        markdown_path = save_script_review_markdown(
            context["platform_id"],
            folder_id,
            _rules_markdown_filename(folder_id, context["job_id"]),
            rules_markdown.rstrip() + "\n",
        )
        update_script_rules_markdown_path(
            folder_id=folder_id,
            job_id=context["job_id"],
            markdown_path=markdown_path,
        )
        logger.info(
            "SCRIPT_RULES_ARTIFACT_MIGRATED platform_id=%s folder_id=%s job_id=%s locator=%s",
            context["platform_id"],
            folder_id,
            context["job_id"],
            markdown_path,
        )

    return {
        "context": context,
        "rules_markdown": rules_markdown,
        "rules_count": int(row.get("rules_count") or 0),
        "source_annotations_count": int(row.get("source_annotations_count") or 0),
        "model": row.get("model") or "",
        "markdown_path": markdown_path,
        "generated_at": row.get("generated_at") or "",
        "updated_at": row.get("updated_at") or "",
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
            except (DeepSeekAPIError, DeepSeekRateLimitError) as exc:
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


def update_rules_markdown(folder_id: int, markdown: str) -> dict:
    """Permet l'édition manuelle du markdown des règles."""
    context = _fetch_context(folder_id)
    if not context:
        raise ValueError("Aucun job de contenu pour ce dossier")

    markdown = (markdown or "").strip()
    rules_count = _count_rules_in_markdown(markdown)
    path = save_script_review_markdown(
        context["platform_id"],
        folder_id,
        _rules_markdown_filename(folder_id, context["job_id"]),
        markdown.rstrip() + "\n",
    )

    _ensure_rules_table()
    upsert_manual_script_rules(
        folder_id=folder_id,
        job_id=context["job_id"],
        rules_markdown=markdown,
        rules_count=rules_count,
        markdown_path=path,
    )
    return get_rules(folder_id)
