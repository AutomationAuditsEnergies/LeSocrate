"""Read-only volume audit for generated formation days."""

from repositories import pipeline_repository as pipeline_repo
from utils.logger import get_logger


logger = get_logger(__name__)

_LEGACY_TARGET_WORDS_PER_DAY = 90000
_VOLUME_AUDIT_TOP_N = 5


def _course_day_budget_for_volume() -> dict:
    try:
        from services.content_generation_service import get_course_day_word_budget

        budget = get_course_day_word_budget()
        return {
            "target_words": int(budget["target_words"]),
            "min_words": int(budget["min_words"]),
            "max_words": int(budget["max_words"]),
            "words_per_minute": budget.get("words_per_minute"),
            "course_seconds": budget.get("course_seconds"),
            "speakable_seconds": budget.get("speakable_seconds"),
            "final_silence_sec": budget.get("final_silence_sec"),
        }
    except Exception:
        logger.warning("Fallback budget journée audit volume", exc_info=True)
        return {
            "target_words": _LEGACY_TARGET_WORDS_PER_DAY,
            "min_words": int(_LEGACY_TARGET_WORDS_PER_DAY * 0.94),
            "max_words": int(_LEGACY_TARGET_WORDS_PER_DAY * 1.02),
            "words_per_minute": None,
            "course_seconds": None,
            "speakable_seconds": None,
            "final_silence_sec": None,
        }


def compute_volume_audit(job_id: int) -> dict:
    """Compute spoken-word totals and deficits for every canonical course day."""
    budget = _course_day_budget_for_volume()
    job = pipeline_repo.get_pipeline_job(job_id)
    if not job:
        return {
            "target": budget["target_words"],
            "min_target": budget["min_words"],
            "max_target": budget["max_words"],
            "budget": budget,
            "folders": [],
        }

    try:
        from services.formation_pipeline_service import get_expected_course_folders

        folder_state = get_expected_course_folders(job_id)
        canonical_ids = folder_state.get("folder_ids") or []
    except Exception:
        logger.warning(
            "Volume audit canonical folders failed for job %s",
            job_id,
            exc_info=True,
        )
        canonical_ids = []

    rows = pipeline_repo.list_volume_audit_rows_for_folders(canonical_ids)
    folders: dict[int, dict] = {}
    for row in rows:
        folder_id = int(row["folder_id"])
        folder = folders.setdefault(
            folder_id,
            {
                "folder_id": folder_id,
                "folder_name": row["folder_name"],
                "position": row["position"],
                "segments": [],
            },
        )
        folder["segments"].append(row)

    try:
        from services.content_generation_service import count_tts_spoken_words
    except Exception:
        count_tts_spoken_words = lambda text: len((text or "").split())

    audited_folders = []
    for folder in folders.values():
        segments = folder["segments"]
        normalized_segments = []
        total = 0
        raw_total = 0

        for segment in segments:
            text_content = segment["text_content"] or ""
            spoken_word_count = count_tts_spoken_words(text_content)
            raw_word_count = int(
                segment["word_count"] or len(text_content.split())
            )
            total += spoken_word_count
            raw_total += raw_word_count
            normalized_segments.append(
                {
                    "segment_id": segment["segment_id"],
                    "sub_idx": segment["sub_part_index"],
                    "sub_part_name": segment["sub_part_name"],
                    "passe": segment["passe"],
                    "word_count": int(spoken_word_count),
                    "raw_word_count": raw_word_count,
                }
            )

        normalized_segments.sort(key=lambda segment: segment["word_count"])
        audited_folders.append(
            {
                "folder_id": folder["folder_id"],
                "folder_name": folder["folder_name"],
                "day_number": (folder["position"] or 0) + 1,
                "total_words": total,
                "raw_words": raw_total,
                "deficit": max(0, int(budget["min_words"]) - total),
                "overflow": max(0, total - int(budget["max_words"])),
                "target_words": budget["target_words"],
                "min_words": budget["min_words"],
                "max_words": budget["max_words"],
                "segments_count": len(segments),
                "shortest_segments": normalized_segments[:_VOLUME_AUDIT_TOP_N],
            }
        )

    logger.info(
        "VOLUME_AUDIT_COMPUTED job_id=%s canonical_folders=%s "
        "audited_folders=%s completed_segments=%s",
        job_id,
        len(canonical_ids),
        len(audited_folders),
        len(rows),
    )
    return {
        "target": budget["target_words"],
        "min_target": budget["min_words"],
        "max_target": budget["max_words"],
        "budget": budget,
        "folders": audited_folders,
    }
