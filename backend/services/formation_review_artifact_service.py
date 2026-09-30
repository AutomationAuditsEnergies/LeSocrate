"""Helpers for durable formation review artifacts.

The database is the source of truth for current reviews.  These paths remain
available so existing report files can still be read and current API reports
can still be written during the transition away from the local CLI runner.
"""

import os
import re


REVIEW_ARTIFACT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "review_queue")
)
DONE_ARTIFACT_ROOT = os.path.join(REVIEW_ARTIFACT_ROOT, "_done")


def review_artifact_dir(job_id: int, step_key: str) -> str:
    """Return the existing artifact directory for one formation step."""
    return os.path.join(
        REVIEW_ARTIFACT_ROOT,
        f"job_{job_id}",
        f"step_{step_key}",
    )


def extract_json(text: str) -> str:
    """Extract the first JSON object or array, including from Markdown fences."""
    text = text.strip()
    if text.startswith("[") or text.startswith("{"):
        return text

    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    start = min(
        (index for index in (text.find("{"), text.find("[")) if index >= 0),
        default=-1,
    )
    end = max(text.rfind("}"), text.rfind("]"))
    if start >= 0 and end > start:
        return text[start : end + 1]
    raise ValueError("Aucun JSON détectable dans l'artefact de révision")
