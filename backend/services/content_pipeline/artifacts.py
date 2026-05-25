from __future__ import annotations

import json
from datetime import datetime

from utils.logger import get_logger

logger = get_logger(__name__)

COURSE_SCRIPT_PLAN_BLOB = "content-script-plan.json"
CONTENT_PLAN_BLOB = "content-plan.json"
CONTENT_DRAFT_SECTIONS_BLOB = "content-draft-sections.json"
CONTENT_COURSE_SCRIPTS_BLOB = "content-course-scripts.json"
CONTENT_QUALITY_REVIEWS_BLOB = "content-quality-reviews.json"
CONTENT_ETHICAL_MICRO_REVIEW_BLOB = "content-ethical-micro-review.json"
CONTENT_REVIEWED_SCRIPTS_BLOB = "content-reviewed-scripts.json"
CONTENT_AUDIO_PLAN_BLOB = "content-audio-plan.json"
CONTENT_ARTIFACT_BLOBS = [
    CONTENT_PLAN_BLOB,
    CONTENT_DRAFT_SECTIONS_BLOB,
    CONTENT_COURSE_SCRIPTS_BLOB,
    CONTENT_QUALITY_REVIEWS_BLOB,
    CONTENT_ETHICAL_MICRO_REVIEW_BLOB,
    CONTENT_REVIEWED_SCRIPTS_BLOB,
    CONTENT_AUDIO_PLAN_BLOB,
    COURSE_SCRIPT_PLAN_BLOB,
]

CONTENT_ARTIFACT_DESCRIPTIONS = {
    CONTENT_PLAN_BLOB: "Plan JSON verrouillé et validation serveur.",
    CONTENT_DRAFT_SECTIONS_BLOB: "Sections brutes générées avant assemblage/calibrage.",
    CONTENT_COURSE_SCRIPTS_BLOB: "Cours complets calibrés avant reviews.",
    CONTENT_QUALITY_REVIEWS_BLOB: "Audit d'adhérence au plan et réparations ciblées avant humanisation.",
    CONTENT_ETHICAL_MICRO_REVIEW_BLOB: "Micro-conformité éthique #1-#16, patches avant/après par section.",
    CONTENT_REVIEWED_SCRIPTS_BLOB: "Scripts après humanisation/conformité.",
    CONTENT_AUDIO_PLAN_BLOB: "Texte réellement planifié/généré pour les fichiers audio.",
    COURSE_SCRIPT_PLAN_BLOB: "Plan UI historique compatible.",
}


def content_artifact_blob_path(platform_id: int, folder_id: int, filename: str) -> str:
    return f"platform-{platform_id}/folder-{folder_id}/playlist/{filename}"


def artifact_payload(job: dict | None, artifact_type: str, payload: dict) -> dict:
    job = job or {}
    return {
        "artifact_type": artifact_type,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "platform_id": job.get("platform_id"),
        "folder_id": job.get("folder_id"),
        "content_job_id": job.get("id"),
        "formation_job_id": job.get("formation_job_id"),
        "folder_position": job.get("folder_position"),
        "folder_name": job.get("folder_name"),
        **(payload or {}),
    }


def save_content_artifact(platform_id: int, folder_id: int, filename: str, payload: dict) -> None:
    try:
        from services.azure_blob_service import CONTAINER_AUDIOS, upload_blob

        upload_blob(
            CONTAINER_AUDIOS,
            content_artifact_blob_path(platform_id, folder_id, filename),
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        )
    except Exception as e:
        logger.warning("⚠️ Sauvegarde artefact contenu impossible %s folder=%s: %s", filename, folder_id, e)


def load_content_artifact(platform_id: int, folder_id: int, filename: str) -> dict | None:
    try:
        from services.azure_blob_service import CONTAINER_AUDIOS, download_blob

        raw = download_blob(CONTAINER_AUDIOS, content_artifact_blob_path(platform_id, folder_id, filename))
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        if "BlobNotFound" not in str(e) and "The specified blob does not exist" not in str(e):
            logger.warning("⚠️ Lecture artefact contenu impossible %s folder=%s: %s", filename, folder_id, e)
        return None


def content_artifacts_for_ui(platform_id: int, folder_id: int) -> list[dict]:
    return [
        {
            "name": filename,
            "blob_path": content_artifact_blob_path(platform_id, folder_id, filename),
            "description": CONTENT_ARTIFACT_DESCRIPTIONS.get(filename, ""),
        }
        for filename in CONTENT_ARTIFACT_BLOBS
    ]
