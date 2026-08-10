"""Build and store the printable support for one scheduled course occurrence.

The document is derived from the same reviewed, current folder text consumed by
the TTS pipeline.  It is intentionally stored outside the RAG PDF containers so
that weekly supports do not pollute the search index or replace the reference
document uploaded by an operator.
"""

from __future__ import annotations

import html
import io
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)

from utils.logger import get_logger


logger = get_logger(__name__)

COURSE_MATERIALS_CONTAINER = "formation-course-materials"
COURSE_PDF_FILENAME = "support-formation.pdf"

_TECHNICAL_TAG_RE = re.compile(r"\[[^\[\]\n]{1,80}\]")
_AUDIO_BLOCK_MARKER_RE = re.compile(r"^\s*<<<BLOC_AUDIO_\d+>>>\s*$", re.MULTILINE)


def _storage_connection_string() -> str:
    value = (os.environ.get("AZURE_STORAGE_CONNECTION_STRING") or "").strip()
    if not value:
        raise ValueError("Connexion Azure PDF manquante")
    return value


def course_materials_container() -> str:
    value = (
        os.environ.get("AZURE_COURSE_MATERIALS_CONTAINER")
        or COURSE_MATERIALS_CONTAINER
    ).strip().lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])", value):
        raise ValueError("Nom du conteneur de supports de cours invalide")
    return value


def daily_course_pdf_blob_key(platform_id: int, session_id: int) -> str:
    platform_id = int(platform_id)
    session_id = int(session_id)
    if platform_id <= 0 or session_id <= 0:
        raise ValueError("Identifiant de support de cours invalide")
    return (
        f"platform-{platform_id}/course-sessions/{session_id}/"
        f"{COURSE_PDF_FILENAME}"
    )


def _strip_technical_tags(text: str) -> str:
    """Remove TTS-only markers while retaining the written teaching content."""
    cleaned = _AUDIO_BLOCK_MARKER_RE.sub("", str(text or ""))
    cleaned = _TECHNICAL_TAG_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?…])", r"\1", cleaned)
    cleaned = re.sub(r"\n[ \t]+", "\n", cleaned)
    return cleaned.strip()


def _paragraphs(text: str) -> list[str]:
    cleaned = _strip_technical_tags(text)
    return [part.strip() for part in re.split(r"\n{2,}", cleaned) if part.strip()]


def _format_course_date(value) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return str(value)
    return parsed.strftime("%d/%m/%Y")


def render_daily_course_pdf(
    *,
    formation_title: str,
    rncp_code: str,
    day_number: int,
    day_title: str,
    sections: list[dict[str, Any]],
    scheduled_at=None,
) -> bytes:
    """Render a sober A4 PDF from already selected course-day sections."""
    # Lazy imports keep the web process bootable while deployments roll out the
    # new dependency; PDF generation itself fails explicitly if it is missing.
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    violet = colors.HexColor("#7C3AED")
    ink = colors.HexColor("#0F172A")
    slate = colors.HexColor("#475569")
    pale = colors.HexColor("#F5F3FF")
    line = colors.HexColor("#E2E8F0")

    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=22 * mm,
        bottomMargin=20 * mm,
        title=f"{formation_title} - Journée {day_number}",
        author="Support de formation",
        subject="Support de formation",
    )
    base = getSampleStyleSheet()
    brand = ParagraphStyle(
        "Brand",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=violet,
        alignment=TA_CENTER,
        spaceAfter=5 * mm,
    )
    title_style = ParagraphStyle(
        "CourseTitle",
        parent=base["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=27,
        textColor=ink,
        alignment=TA_CENTER,
        spaceAfter=3 * mm,
    )
    day_style = ParagraphStyle(
        "DayTitle",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=slate,
        alignment=TA_CENTER,
        spaceAfter=7 * mm,
    )
    intro_style = ParagraphStyle(
        "Intro",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=16,
        textColor=slate,
        alignment=TA_CENTER,
        spaceAfter=9 * mm,
    )
    section_style = ParagraphStyle(
        "Section",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=19,
        textColor=ink,
        alignment=TA_LEFT,
        spaceBefore=7 * mm,
        spaceAfter=3 * mm,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=base["BodyText"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=16,
        textColor=ink,
        alignment=TA_LEFT,
        spaceAfter=3.5 * mm,
        allowWidows=0,
        allowOrphans=0,
    )

    course_date = _format_course_date(scheduled_at)
    meta = []
    if rncp_code:
        clean_code = str(rncp_code).strip()
        meta.append(("Certification", clean_code if clean_code.upper().startswith("RNCP") else f"RNCP {clean_code}"))
    if course_date:
        meta.append(("Date", course_date))
    meta.append(("Journée", str(day_number)))

    story = [
        Paragraph("SUPPORT DE FORMATION", brand),
        Spacer(1, 18 * mm),
        Paragraph(html.escape(_strip_technical_tags(formation_title)), title_style),
        Paragraph(
            html.escape(_strip_technical_tags(day_title) or f"Journée {day_number}"),
            day_style,
        ),
    ]

    meta_table = Table(
        [[Paragraph(f"<b>{html.escape(label)}</b><br/>{html.escape(value)}", intro_style) for label, value in meta]],
        colWidths=[document.width / len(meta)] * len(meta),
    )
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), pale),
        ("BOX", (0, 0), (-1, -1), 0.6, line),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, line),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.extend([
        meta_table,
        Spacer(1, 8 * mm),
        Paragraph(
            "Ce document reprend le texte pédagogique diffusé pendant cette journée de formation.",
            intro_style,
        ),
        PageBreak(),
    ])

    rendered_sections = 0
    for index, section in enumerate(sections, start=1):
        paragraphs = _paragraphs(section.get("body") or "")
        if not paragraphs:
            continue
        heading = _strip_technical_tags(section.get("name") or f"Partie {index}")
        story.append(Paragraph(html.escape(heading), section_style))
        for paragraph in paragraphs:
            story.append(Paragraph(html.escape(paragraph).replace("\n", "<br/>"), body_style))
        rendered_sections += 1

    if not rendered_sections:
        raise ValueError("Le texte de cette journée est vide")

    def _cover_chrome(canvas, _doc):
        canvas.saveState()
        width, height = A4
        canvas.setFillColor(violet)
        canvas.rect(0, height - 5 * mm, width, 5 * mm, stroke=0, fill=1)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(slate)
        canvas.drawCentredString(width / 2, 10 * mm, "Support de formation")
        canvas.restoreState()

    def _page_chrome(canvas, doc):
        canvas.saveState()
        width, _height = A4
        canvas.setStrokeColor(line)
        canvas.setLineWidth(0.5)
        canvas.line(20 * mm, 14 * mm, width - 20 * mm, 14 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(slate)
        canvas.drawString(20 * mm, 9.5 * mm, "Support de formation")
        canvas.drawRightString(width - 20 * mm, 9.5 * mm, f"Page {doc.page - 1}")
        canvas.restoreState()

    document.build(story, onFirstPage=_cover_chrome, onLaterPages=_page_chrome)
    return output.getvalue()


def build_daily_course_pdf(
    *,
    job_id: int,
    folder_id: int,
    scheduled_at=None,
) -> tuple[bytes, str, dict[str, Any]]:
    """Build the final reviewed text for one pipeline course-day folder."""
    from repositories.pipeline_repository import get_content_generation_job_by_folder
    from services.formation_docx_service import _get_segments_for_folder
    from services.formation_pipeline_service import get_job

    job = get_job(int(job_id))
    if not job:
        raise ValueError(f"Job formation {job_id} introuvable")
    folder = get_content_generation_job_by_folder(int(folder_id))
    if not folder or int(folder.get("formation_job_id") or 0) != int(job_id):
        raise ValueError(f"Dossier {folder_id} hors de la formation {job_id}")

    position = int(folder.get("position") or 0)
    day_number = position + 1
    daily_programs = job.get("daily_programs") or []
    if isinstance(daily_programs, str):
        daily_programs = json.loads(daily_programs or "[]")
    day_data = daily_programs[position] if position < len(daily_programs) else {}
    day_number = int(day_data.get("day_number") or day_number)
    day_title = (
        day_data.get("title")
        or folder.get("name")
        or f"Journée {day_number}"
    )
    formation_title = job.get("tp_name") or "Formation professionnelle"
    sections = _get_segments_for_folder(int(folder_id), version="current")
    pdf_bytes = render_daily_course_pdf(
        formation_title=formation_title,
        rncp_code=job.get("rncp_code") or "",
        day_number=day_number,
        day_title=day_title,
        sections=sections,
        scheduled_at=scheduled_at,
    )
    return pdf_bytes, COURSE_PDF_FILENAME, {
        "day_number": day_number,
        "day_title": day_title,
        "section_count": len([item for item in sections if (item.get("body") or "").strip()]),
    }


def publish_daily_course_pdf(
    *,
    platform_id: int,
    session_id: int,
    pdf_bytes: bytes,
    filename: str = COURSE_PDF_FILENAME,
    blob_service_client=None,
) -> dict[str, Any]:
    """Idempotently publish one immutable occurrence-scoped PDF support."""
    if filename != COURSE_PDF_FILENAME:
        raise ValueError("Nom de support PDF invalide")
    if not pdf_bytes or not bytes(pdf_bytes).startswith(b"%PDF"):
        raise ValueError("Support PDF invalide")

    client = blob_service_client or BlobServiceClient.from_connection_string(
        _storage_connection_string()
    )
    container_name = course_materials_container()
    container = client.get_container_client(container_name)
    try:
        container.create_container()
    except ResourceExistsError:
        pass

    blob_key = daily_course_pdf_blob_key(platform_id, session_id)
    container.get_blob_client(blob_key).upload_blob(
        pdf_bytes,
        overwrite=True,
        content_settings=ContentSettings(
            content_type="application/pdf",
            content_disposition='inline; filename="support-formation.pdf"',
        ),
    )
    logger.info(
        "COURSE_PDF_PUBLISHED platform_id=%s session_id=%s blob=%s bytes=%s",
        platform_id,
        session_id,
        blob_key,
        len(pdf_bytes),
    )
    return {
        "container": container_name,
        "blob_key": blob_key,
        "filename": filename,
        "size": len(pdf_bytes),
    }


def publish_pipeline_course_pdfs(
    *,
    job_id: int,
    platform_id: int,
) -> list[dict[str, Any]]:
    """Build every daily support as the text pipeline reaches completion.

    The operation is idempotent: retries overwrite the same occurrence-scoped
    blobs. Audio preparation can therefore remain independent at H-72.
    """
    from repositories.course_schedule_repository import list_course_sessions
    from services.formation_pipeline_service import get_expected_course_folders

    job_id = int(job_id)
    platform_id = int(platform_id)
    folder_ids = [
        int(folder_id)
        for folder_id in (
            get_expected_course_folders(job_id).get("folder_ids") or []
        )
    ]
    if not folder_ids:
        raise ValueError(f"Aucune journée disponible pour le job {job_id}")

    sessions = list_course_sessions(
        platform_id,
        limit=max(50, len(folder_ids)),
    )
    sessions_by_index = {
        int(session.get("session_index") or 0): session
        for session in sessions
        if int(session.get("session_index") or 0) > 0
    }

    published = []
    for day_index, folder_id in enumerate(folder_ids, start=1):
        session = sessions_by_index.get(day_index)
        if not session or not session.get("id"):
            raise RuntimeError(
                f"Séance {day_index} introuvable pour la plateforme {platform_id}"
            )
        session_id = int(session["id"])
        pdf_bytes, pdf_filename, pdf_metadata = build_daily_course_pdf(
            job_id=job_id,
            folder_id=folder_id,
            scheduled_at=session.get("scheduled_at"),
        )
        result = publish_daily_course_pdf(
            platform_id=platform_id,
            session_id=session_id,
            pdf_bytes=pdf_bytes,
            filename=pdf_filename,
        )
        published.append({
            **result,
            "session_id": session_id,
            "folder_id": folder_id,
            "metadata": pdf_metadata,
        })

    logger.info(
        "PIPELINE_COURSE_PDFS_PUBLISHED job_id=%s platform_id=%s count=%s",
        job_id,
        platform_id,
        len(published),
    )
    return published


def list_daily_course_pdf_materials(
    platform_id: int,
    sessions: list[dict[str, Any]],
    *,
    blob_service_client=None,
) -> list[dict[str, Any]]:
    """Return short-lived read URLs for one platform's generated supports."""
    platform_id = int(platform_id)
    client = blob_service_client or BlobServiceClient.from_connection_string(
        _storage_connection_string()
    )
    container_name = course_materials_container()
    container = client.get_container_client(container_name)
    prefix = f"platform-{platform_id}/course-sessions/"
    try:
        blobs = {
            blob.name: blob
            for blob in container.list_blobs(name_starts_with=prefix)
            if str(blob.name).endswith(f"/{COURSE_PDF_FILENAME}")
        }
    except ResourceNotFoundError:
        return []

    credential = getattr(client, "credential", None)
    account_key = getattr(credential, "account_key", None)
    account_name = str(getattr(client, "account_name", "") or "").strip()
    if not account_name or not account_key:
        raise RuntimeError("Clé Azure requise pour signer les supports PDF")
    expiry = datetime.now(timezone.utc).timestamp() + 2 * 60 * 60

    materials = []
    for session in sessions:
        session_id = int(session["id"])
        blob_key = daily_course_pdf_blob_key(platform_id, session_id)
        blob = blobs.get(blob_key)
        if not blob:
            continue
        sas = generate_blob_sas(
            account_name=account_name,
            container_name=container_name,
            blob_name=blob_key,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.fromtimestamp(expiry, tz=timezone.utc),
        )
        materials.append({
            "session_id": session_id,
            "session_index": int(session.get("session_index") or 0),
            "folder_id": (
                int(session["audio_folder_id"])
                if session.get("audio_folder_id") is not None
                else None
            ),
            "scheduled_at": session.get("scheduled_at"),
            "filename": COURSE_PDF_FILENAME,
            "size": int(getattr(blob, "size", 0) or 0),
            "generated_at": (
                blob.last_modified.isoformat()
                if getattr(blob, "last_modified", None)
                else None
            ),
            "url": f"{client.get_blob_client(container=container_name, blob=blob_key).url}?{sas}",
        })
    return sorted(
        materials,
        key=lambda item: (item["session_index"], item["session_id"]),
    )
