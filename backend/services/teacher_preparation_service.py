"""Public preparation state for an AI teacher.

The formation pipeline keeps detailed technical checkpoints.  Training centres
only need a stable product state and a concise, non-sensitive progress label.
This module is deliberately pure so every API surface uses the same mapping.
"""

from __future__ import annotations

from typing import Any


_STEP_PROGRESS = {
    "reac": (8, "Analyse du référentiel"),
    "kb": (22, "Préparation des connaissances"),
    "global": (30, "Construction du programme"),
    "daily": (36, "Organisation des journées"),
    "content": (72, "Rédaction des cours"),
    "review": (84, "Vérification pédagogique"),
    "post_review_docs": (90, "Finalisation des supports"),
    "slides": (97, "Création des slides"),
    "audio": (99, "Préparation des audios"),
    "done": (100, "Professeur prêt"),
}

_STATUS_PROGRESS = {
    "init": (5, "Initialisation"),
    "reac_ready": (14, "Analyse du référentiel"),
    "kb_building": (20, "Préparation des connaissances"),
    "global_generating": (26, "Construction du programme"),
    "global_ready": (31, "Construction du programme"),
    "global_validated": (34, "Programme validé"),
    "daily_splitting": (36, "Organisation des journées"),
    "daily_ready": (38, "Organisation des journées"),
    "daily_validated": (40, "Journées validées"),
    "tts_launched": (90, "Finalisation des supports"),
    "text_ready": (100, "Professeur prêt"),
    "audio_running": (99, "Préparation des audios"),
    "audio_launched": (100, "Professeur prêt"),
    "audio_completed": (100, "Professeur prêt"),
    "completed": (100, "Professeur prêt"),
}


def build_teacher_preparation_state(
    *,
    platform_status: str | None,
    pipeline_status: str | None = None,
    pipeline_step: str | None = None,
    pipeline_error: str | None = None,
    source_formation_id: int | None = None,
    source_module_id: int | None = None,
) -> dict[str, Any]:
    """Return the centre-facing lifecycle state for one teacher.

    Error details stay private.  The UI receives only a stable status, a stage,
    a monotonic checkpoint percentage, and whether an idempotent resume is
    available.
    """

    raw_platform_status = str(platform_status or "ready").strip().lower()
    raw_pipeline_status = str(pipeline_status or "").strip().lower()
    raw_step = str(pipeline_step or "").strip().lower()

    failed = bool(pipeline_error) or raw_platform_status == "error" or raw_pipeline_status in {
        "error",
        "audio_error",
    } or raw_step == "stopped"

    progress, stage = _STEP_PROGRESS.get(
        raw_step,
        _STATUS_PROGRESS.get(raw_pipeline_status, (8, "Initialisation")),
    )

    if failed:
        return {
            "status": "failed",
            "progress": min(99, max(1, int(progress))),
            "stage": "Préparation interrompue",
            "can_retry": bool(source_formation_id),
        }

    # A reused module points to its already-completed source pipeline.  That
    # source must not make the new platform look ready while its own course and
    # Blob copy is still running.
    if source_module_id and raw_platform_status == "pending":
        return {
            "status": "preparing",
            "progress": 55,
            "stage": "Copie des cours",
            "can_retry": False,
        }

    pipeline_done = raw_step == "done" or raw_pipeline_status in {
        "text_ready",
        "audio_launched",
        "audio_completed",
        "completed",
    }
    if raw_platform_status == "ready" or pipeline_done:
        return {
            "status": "ready",
            "progress": 100,
            "stage": "Professeur prêt",
            "can_retry": False,
        }

    return {
        "status": "preparing",
        "progress": min(99, max(1, int(progress))),
        "stage": stage,
        "can_retry": False,
    }
