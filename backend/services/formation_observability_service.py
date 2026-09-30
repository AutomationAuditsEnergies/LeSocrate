"""Observabilité durable de la pipeline formation.

Deux responsabilités :
- persister les rapports de révision conformité en DB, car les fichiers locaux
  Azure App Service ne sont pas une source fiable sur la durée ;
- journaliser les événements structurés de pipeline pour alimenter un futur
  dashboard d'analyse.
"""

import json
from datetime import datetime

from repositories.pipeline_repository import (
    delete_pipeline_events,
    ensure_pipeline_observability_tables,
    get_latest_review_report_row,
    insert_pipeline_event,
    insert_review_report,
    list_pipeline_event_rows,
)
from utils.logger import get_logger

logger = get_logger(__name__)

def ensure_observability_tables() -> None:
    """Crée les tables d'observabilité si l'app n'a pas encore redémarré."""
    ensure_pipeline_observability_tables()


def _dumps(value) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _compact_for_log(value, *, max_chars: int = 2200) -> str:
    """Formatte un payload pour stdout Azure sans exploser les logs."""
    try:
        rendered = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
    except Exception:
        rendered = str(value)
    rendered = rendered.replace("\n", " ")
    if len(rendered) > max_chars:
        return rendered[:max_chars] + f"... <truncated {len(rendered) - max_chars} chars>"
    return rendered


def _emit_pipeline_event_log(
    event_id: int | None,
    job_id: int,
    event_type: str,
    *,
    step: str | None,
    status: str,
    folder_id: int | None,
    message: str | None,
    model: str | None,
    duration_ms: int | None,
    data: dict | None,
    error: str | None,
) -> None:
    payload = {
        "event_id": event_id,
        "job_id": job_id,
        "folder_id": folder_id,
        "step": step,
        "event_type": event_type,
        "status": status,
        "message": message,
        "model": model,
        "duration_ms": duration_ms,
        "data": data or {},
        "error": error,
    }
    line = _compact_for_log(payload)
    if status == "error" or error:
        logger.error(f"PIPELINE_EVENT {line}")
    elif status in {"warning", "blocked"}:
        logger.warning(f"PIPELINE_EVENT {line}")
    else:
        logger.info(f"PIPELINE_EVENT {line}")


def persist_review_report(
    job_id: int,
    folder_id: int,
    report: dict,
    *,
    source: str = "api",
    generated_via: str | None = None,
) -> int:
    """Ajoute un snapshot durable du rapport de conformité."""
    summary = report.get("summary") or {}
    report_id = insert_review_report(
        job_id=job_id,
        folder_id=folder_id,
        source=source,
        generated_via=generated_via or report.get("generated_via"),
        summary_json=_dumps(summary),
        report_json=_dumps(report),
    )
    logger.info(
        "PIPELINE_REVIEW_REPORT %s",
        _compact_for_log(
            {
                "report_id": report_id,
                "job_id": job_id,
                "folder_id": folder_id,
                "source": source,
                "generated_via": generated_via or report.get("generated_via"),
                "summary": summary,
            }
        ),
    )
    return int(report_id)


def get_latest_review_report(job_id: int, folder_id: int) -> dict | None:
    """Retourne le dernier rapport de conformité persisté pour une journée."""
    row = get_latest_review_report_row(job_id=job_id, folder_id=folder_id)
    if not row:
        return None
    try:
        report = json.loads(row.get("report_json") or "{}")
    except Exception as exc:
        logger.warning(
            f"⚠️ Rapport conformité DB illisible job={job_id} folder={folder_id}: {exc}"
        )
        return None
    report.setdefault("generated_via", row.get("generated_via"))
    report["persisted_report_id"] = row.get("id")
    report["persisted_source"] = row.get("source")
    report["persisted_at"] = row.get("created_at")
    return report


def log_pipeline_event(
    job_id: int,
    event_type: str,
    *,
    step: str | None = None,
    status: str = "info",
    folder_id: int | None = None,
    message: str | None = None,
    model: str | None = None,
    duration_ms: int | None = None,
    data: dict | None = None,
    error: str | None = None,
) -> int | None:
    """Journalise un événement pipeline sans faire échouer la pipeline."""
    try:
        event_id = insert_pipeline_event(
            job_id=job_id,
            event_type=event_type,
            step=step,
            status=status,
            folder_id=folder_id,
            message=message,
            model=model,
            duration_ms=duration_ms,
            data_json=_dumps(data),
            error=error,
        )
        _emit_pipeline_event_log(
            int(event_id),
            job_id,
            event_type,
            step=step,
            status=status,
            folder_id=folder_id,
            message=message,
            model=model,
            duration_ms=duration_ms,
            data=data,
            error=error,
        )
        return int(event_id)
    except Exception as exc:
        logger.warning(f"⚠️ Event pipeline non persisté job={job_id}: {exc}")
        return None


def list_pipeline_events(job_id: int, *, limit: int = 200) -> list[dict]:
    """Liste les événements récents d'un job, du plus ancien au plus récent."""
    rows = list_pipeline_event_rows(job_id, limit=limit)
    events = []
    for row in reversed(rows):
        try:
            data = json.loads(row.get("data_json") or "{}")
        except Exception:
            data = {}
        if "output_text" in data:
            # Ne renvoie jamais un texte LLM complet dans le flux d'événements
            # pollé par le dashboard, y compris pour les anciennes traces.
            data = dict(data)
            data.pop("output_text", None)
        events.append(
            {
                "id": row.get("id"),
                "job_id": row.get("job_id"),
                "folder_id": row.get("folder_id"),
                "step": row.get("step"),
                "event_type": row.get("event_type"),
                "status": row.get("status"),
                "message": row.get("message"),
                "model": row.get("model"),
                "duration_ms": row.get("duration_ms"),
                "data": data,
                "error": row.get("error"),
                "created_at": row.get("created_at"),
            }
        )
    return events


def clear_pipeline_events(
    job_id: int,
    *,
    folder_id: int | None = None,
    include_global_events: bool = True,
) -> int:
    """Supprime les événements d'une tentative pour repartir sur un dashboard propre.

    Par défaut, sans `folder_id`, on nettoie tout le journal du job. C'est le
    comportement attendu pour une relance "continuer après le texte" : le texte
    reste en DB, mais les traces aval précédentes ne polluent plus l'UI.
    """
    deleted = delete_pipeline_events(
        job_id=job_id,
        folder_id=folder_id,
        include_global_events=include_global_events,
    )
    logger.info(
        "PIPELINE_EVENTS_CLEARED %s",
        _compact_for_log(
            {
                "job_id": job_id,
                "folder_id": folder_id,
                "include_global_events": include_global_events,
                "deleted_events": deleted,
            }
        ),
    )
    return int(deleted)


def now_iso_utc() -> str:
    return datetime.utcnow().isoformat() + "Z"
