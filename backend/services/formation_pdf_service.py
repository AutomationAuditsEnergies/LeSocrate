"""
Génération d'un PDF "programme de formation" par journée.

Pipeline :
  1. Récupère le job formation (tp_name, RNCP, daily_programs JSON)
  2. Récupère les segments texte du dossier cours (cours × 3 passes)
  3. Nettoie les tags Fish Audio ([pause], [warm], etc.) réservés au TTS
  4. Rend un template Jinja2 LaTeX → .tex
  5. Compile avec xelatex (2 passes pour la TOC) dans un tempdir
  6. Retourne les bytes du PDF

Utilisation :
    pdf_bytes, filename = build_course_pdf(job_id=7, folder_id=42)
"""

import os
import re
import json
import shutil
import tempfile
import subprocess
from datetime import datetime
from typing import Tuple

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from repositories.pipeline_repository import (
    get_content_generation_job_by_folder,
    get_pipeline_job,
    list_completed_content_segment_rows,
    list_course_folder_ids_for_platform,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
_TEMPLATE_NAME = "formation_cours.tex.j2"

_XELATEX_BIN = shutil.which("xelatex") or "/Library/TeX/texbin/xelatex"


# ─── Helpers texte ────────────────────────────────────────────────────────────

# Caractères à échapper pour LaTeX (l'antislash doit passer en premier).
_LATEX_ESCAPE_MAP = [
    ("\\", r"\textbackslash{}"),
    ("&",  r"\&"),
    ("%",  r"\%"),
    ("$",  r"\$"),
    ("#",  r"\#"),
    ("_",  r"\_"),
    ("{",  r"\{"),
    ("}",  r"\}"),
    ("~",  r"\textasciitilde{}"),
    ("^",  r"\textasciicircum{}"),
]


def _latex_escape(text) -> str:
    if text is None:
        return ""
    s = str(text)
    for src, dst in _LATEX_ESCAPE_MAP:
        s = s.replace(src, dst)
    return s


def _latex_escape_meta(text) -> str:
    """Échappement "safe" pour les métadonnées PDF (hyperref) : pas de backslashes."""
    if text is None:
        return ""
    return re.sub(r"[\\{}%#$&_^~]", "-", str(text))


def _latex_escape_paragraphs(text) -> str:
    """Échappe paragraphe par paragraphe (préserve les sauts de paragraphe)."""
    if text is None:
        return ""
    paragraphs = re.split(r"\n{2,}", str(text).strip())
    escaped = [_latex_escape(p.strip()) for p in paragraphs if p.strip()]
    return "\n\n".join(escaped)


_FISHAUDIO_TAG_RE = re.compile(r"\[[^\[\]\n]{1,50}\]")
_AUDIO_BLOCK_MARKER_RE = re.compile(r"^\s*<<<BLOC_AUDIO_\d+>>>\s*$", re.MULTILINE)

def _strip_tts_tags(text: str) -> str:
    """Retire les tags Fish Audio type `[pause]`, `[warm]`, `[long pause]`, etc."""
    if not text:
        return ""
    cleaned = _AUDIO_BLOCK_MARKER_RE.sub("", text)
    cleaned = _FISHAUDIO_TAG_RE.sub("", cleaned)
    # Nettoyer les doubles espaces créés par la suppression
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?…])", r"\1", cleaned)
    cleaned = re.sub(r"\n[ \t]+", "\n", cleaned)
    return cleaned.strip()


def _extract_marked_audio_blocks(rows: list) -> list:
    """Si le texte a été calibré par blocs audio, restitue des sections cohérentes."""
    full_text = "\n\n".join((row.get("text_content") or "") for row in rows)
    matches = list(_AUDIO_BLOCK_MARKER_RE.finditer(full_text))
    if not matches:
        return []
    blocks = []
    for idx, match in enumerate(matches):
        bloc_num = int(re.search(r"\d+", match.group(0)).group(0))
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(full_text)
        body = _strip_tts_tags(full_text[start:end])
        if body:
            blocks.append({"name": f"Cours audio prévu {bloc_num}", "body": body})
    return blocks


# ─── Accès DB ─────────────────────────────────────────────────────────────────

def _get_formation_job(job_id: int) -> dict:
    job = get_pipeline_job(job_id)
    if not job:
        raise ValueError(f"Job formation {job_id} introuvable")
    return {
        "tp_name": job["tp_name"],
        "rncp_code": job.get("rncp_code") or "",
        "total_hours": job["total_hours"],
        "nb_days": job["nb_days"],
        "daily_programs": json.loads(job.get("daily_programs") or "[]"),
        "platform_id": job["platform_id"],
    }


def _folder_position_in_platform(folder_id: int, platform_id: int) -> int:
    """Retourne la position (0-indexed) du dossier dans la plateforme, dans l'ordre de création."""
    folder_ids = list_course_folder_ids_for_platform(platform_id)
    for idx, fid in enumerate(folder_ids):
        if fid == folder_id:
            return idx
    raise ValueError(f"Dossier {folder_id} introuvable pour plateforme {platform_id}")


def _get_segments_for_folder(folder_id: int) -> list:
    """Liste des segments content_generation_segments completed, ordonnés."""
    content_job = get_content_generation_job_by_folder(folder_id)
    if not content_job:
        raise ValueError(f"Aucun job de génération de contenu pour le dossier {folder_id}")

    cg_job_id = content_job["id"]
    sub_parts_json = content_job.get("sub_parts") or "[]"
    sub_parts_names = json.loads(sub_parts_json or "[]")

    rows = list_completed_content_segment_rows(cg_job_id)

    marked_blocks = _extract_marked_audio_blocks(rows)
    if marked_blocks:
        return marked_blocks

    # Regroupement par sub_part
    grouped = {}
    for row in rows:
        grouped.setdefault(row["sub_part_index"], []).append(
            (row["passe"], row.get("text_content") or "")
        )

    result = []
    for idx, name in enumerate(sub_parts_names):
        passes = sorted(grouped.get(idx, []), key=lambda x: x[0])
        body = "\n\n".join(_strip_tts_tags(txt) for _, txt in passes).strip()
        result.append({"name": name, "body": body})

    return result


# ─── Rendu Jinja2 + compile XeLaTeX ───────────────────────────────────────────

def _jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        block_start_string="((*",
        block_end_string="*))",
        variable_start_string="(((",
        variable_end_string=")))",
        comment_start_string="((=",
        comment_end_string="=))",
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
        autoescape=False,
    )
    env.filters["latex_escape"] = _latex_escape
    env.filters["latex_escape_meta"] = _latex_escape_meta
    env.filters["latex_escape_paragraphs"] = _latex_escape_paragraphs
    return env


def _compile_xelatex(tex_source: str, workdir: str) -> bytes:
    """Écrit le .tex dans workdir, compile deux fois (pour la TOC), retourne les bytes PDF."""
    tex_path = os.path.join(workdir, "cours.tex")
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex_source)

    cmd = [
        _XELATEX_BIN,
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-output-directory", workdir,
        tex_path,
    ]

    # 2 passes : la 1re construit la TOC, la 2de l'intègre dans le PDF.
    for pass_no in (1, 2):
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            log_path = os.path.join(workdir, "cours.log")
            log_tail = ""
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    log_tail = f.read()[-4000:]
            raise RuntimeError(
                f"Échec compilation XeLaTeX (passe {pass_no}) : "
                f"{result.stderr[-600:]}\n---LOG---\n{log_tail}"
            )

    pdf_path = os.path.join(workdir, "cours.pdf")
    with open(pdf_path, "rb") as f:
        return f.read()


# ─── API publique ─────────────────────────────────────────────────────────────

def build_course_pdf(job_id: int, folder_id: int) -> Tuple[bytes, str]:
    """
    Produit un PDF d'une journée de formation.
    Retourne (pdf_bytes, suggested_filename).
    """
    job = _get_formation_job(job_id)
    position = _folder_position_in_platform(folder_id, job["platform_id"])
    daily_programs = job["daily_programs"]

    if position >= len(daily_programs):
        raise ValueError(
            f"Position dossier ({position}) dépasse nb_days ({len(daily_programs)}) — "
            f"le dossier n'appartient pas à la pipeline formation"
        )
    day_data = daily_programs[position]
    day_number = day_data.get("day_number", position + 1)
    day_title = day_data.get("title", f"Journée {day_number}")

    segments = _get_segments_for_folder(folder_id)
    module_by_name = {
        sp.get("name"): sp.get("module_content", "")
        for sp in day_data.get("sub_parts", [])
    }

    sub_parts_render = []
    total_words = 0
    for part in segments:
        body = part["body"]
        total_words += len(body.split())
        sub_parts_render.append({
            "name": part["name"],
            "module_content": module_by_name.get(part["name"], ""),
            "body": body,
        })

    env = _jinja_env()
    template = env.get_template(_TEMPLATE_NAME)
    tex_source = template.render(
        tp_name=job["tp_name"],
        rncp_code=job["rncp_code"] or "—",
        total_hours=job["total_hours"],
        nb_days=job["nb_days"],
        day_number=day_number,
        day_title=day_title,
        day_recap=_strip_tts_tags(day_data.get("day_recap") or ""),
        day_transition=_strip_tts_tags(day_data.get("day_transition") or ""),
        sub_parts=sub_parts_render,
        total_words=f"{total_words:,}".replace(",", " "),
        generated_at=datetime.now().strftime("%d/%m/%Y %H:%M"),
    )

    with tempfile.TemporaryDirectory(prefix="socrate-pdf-") as workdir:
        pdf_bytes = _compile_xelatex(tex_source, workdir)

    slug = re.sub(r"[^a-zA-Z0-9]+", "-", job["tp_name"].lower()).strip("-")[:40]
    filename = f"programme-{slug}-jour{day_number}.pdf"
    logger.info(f"✅ PDF généré : {filename} ({len(pdf_bytes):,} bytes, {total_words} mots)")
    return pdf_bytes, filename
