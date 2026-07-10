from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime

from utils.logger import get_logger

logger = get_logger(__name__)

COURSE_SCRIPT_PLAN_BLOB = "content-script-plan.json"
CONTENT_PLAN_BLOB = "content-plan.json"
CONTENT_DRAFT_SECTIONS_BLOB = "content-draft-sections.json"
CONTENT_COURSE_SCRIPTS_BLOB = "content-course-scripts.json"
CONTENT_BUDGET_CALIBRATION_BLOB = "content-budget-calibration.json"
CONTENT_QUALITY_REVIEWS_BLOB = "content-quality-reviews.json"
CONTENT_ETHICAL_MICRO_REVIEW_BLOB = "content-ethical-micro-review.json"
CONTENT_VOLUME_SAFETY_BLOB = "content-volume-safety.json"
CONTENT_REVIEWED_SCRIPTS_BLOB = "content-reviewed-scripts.json"
CONTENT_AUDIO_PLAN_BLOB = "content-audio-plan.json"
CONTENT_ARTIFACT_BLOBS = [
    CONTENT_PLAN_BLOB,
    CONTENT_DRAFT_SECTIONS_BLOB,
    CONTENT_QUALITY_REVIEWS_BLOB,
    CONTENT_BUDGET_CALIBRATION_BLOB,
    CONTENT_COURSE_SCRIPTS_BLOB,
    CONTENT_ETHICAL_MICRO_REVIEW_BLOB,
    CONTENT_VOLUME_SAFETY_BLOB,
    CONTENT_REVIEWED_SCRIPTS_BLOB,
    CONTENT_AUDIO_PLAN_BLOB,
    COURSE_SCRIPT_PLAN_BLOB,
]

CONTENT_ARTIFACT_DESCRIPTIONS = {
    CONTENT_PLAN_BLOB: "Plan JSON verrouillé et validation serveur.",
    CONTENT_DRAFT_SECTIONS_BLOB: "Sections brutes générées avant assemblage/calibrage.",
    CONTENT_COURSE_SCRIPTS_BLOB: "Cours complets après calibrage budget et micro-conformité, avant humanisation.",
    CONTENT_BUDGET_CALIBRATION_BLOB: "Avant/après du calibrage budget texte par cours.",
    CONTENT_QUALITY_REVIEWS_BLOB: "Audit d'adhérence au plan après génération par section, avant calibrage budget.",
    CONTENT_ETHICAL_MICRO_REVIEW_BLOB: "Micro-conformité éthique #1-#16, patches avant/après par section.",
    CONTENT_VOLUME_SAFETY_BLOB: "Ajouts de sécurité volume, avec texte avant/après et passages ajoutés.",
    CONTENT_REVIEWED_SCRIPTS_BLOB: "Scripts après humanisation/conformité.",
    CONTENT_AUDIO_PLAN_BLOB: "Texte réellement planifié/généré pour les fichiers audio.",
    COURSE_SCRIPT_PLAN_BLOB: "Plan UI historique compatible.",
}


def content_artifact_blob_path(platform_id: int, folder_id: int, filename: str) -> str:
    return f"platform-{platform_id}/folder-{folder_id}/playlist/{filename}"


def _artifacts_required() -> bool:
    return os.getenv("PIPELINE_ARTIFACTS_REQUIRED", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _blob_attempts() -> int:
    try:
        return max(1, min(8, int(os.getenv("PIPELINE_BLOB_MAX_ATTEMPTS", "3"))))
    except (TypeError, ValueError):
        return 3


def _is_missing_blob(exc: Exception) -> bool:
    message = str(exc)
    return "BlobNotFound" in message or "The specified blob does not exist" in message


def _with_blob_retry(label: str, operation):
    attempts = _blob_attempts()
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:
            if attempt >= attempts or _is_missing_blob(exc):
                raise
            delay = min(8.0, (0.4 * (2 ** (attempt - 1))) + random.uniform(0, 0.2))
            logger.warning(
                "PIPELINE_BLOB_RETRY artifact=%s attempt=%s/%s wait=%.2fs",
                label,
                attempt,
                attempts,
                delay,
            )
            time.sleep(delay)


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
        from services.azure_blob_service import (
            CONTAINER_ARTIFACTS,
            ensure_private_container,
            upload_blob,
        )

        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        def _upload():
            ensure_private_container(CONTAINER_ARTIFACTS)
            return upload_blob(
                CONTAINER_ARTIFACTS,
                content_artifact_blob_path(platform_id, folder_id, filename),
                raw,
            )

        _with_blob_retry(
            filename,
            _upload,
        )
    except Exception as e:
        logger.error(
            "PIPELINE_BLOB_SAVE_FAILED artifact=%s platform=%s folder=%s required=%s error=%s",
            filename,
            platform_id,
            folder_id,
            _artifacts_required(),
            e,
        )
        if _artifacts_required():
            raise RuntimeError(
                f"Artefact Azure Blob obligatoire non sauvegardé: {filename}"
            ) from e


def load_content_artifact(platform_id: int, folder_id: int, filename: str) -> dict | None:
    try:
        from services.azure_blob_service import CONTAINER_ARTIFACTS, download_blob

        raw = _with_blob_retry(
            filename,
            lambda: download_blob(
                CONTAINER_ARTIFACTS,
                content_artifact_blob_path(platform_id, folder_id, filename),
            ),
        )
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        if not _is_missing_blob(e):
            logger.warning("⚠️ Lecture artefact contenu impossible %s folder=%s: %s", filename, folder_id, e)
            if _artifacts_required():
                raise RuntimeError(
                    f"Artefact Azure Blob obligatoire illisible: {filename}"
                ) from e
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
