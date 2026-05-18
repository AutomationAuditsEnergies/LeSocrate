"""Observabilité durable de la pipeline formation.

Deux responsabilités :
- persister les rapports de révision conformité en DB, car les fichiers locaux
  Azure App Service ne sont pas une source fiable sur la durée ;
- journaliser les événements structurés de pipeline pour alimenter un futur
  dashboard d'analyse.
"""

import json
from datetime import datetime

from database.db import get_db_connection
from utils.logger import get_logger

logger = get_logger(__name__)


def ensure_observability_tables() -> None:
    """Crée les tables d'observabilité si l'app n'a pas encore redémarré."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS content_review_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            folder_id INTEGER NOT NULL,
            source TEXT DEFAULT 'api',
            generated_via TEXT,
            summary_json TEXT DEFAULT '{}',
            report_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_content_review_reports_job_folder
        ON content_review_reports(job_id, folder_id, created_at)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS formation_pipeline_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            folder_id INTEGER,
            step TEXT,
            event_type TEXT NOT NULL,
            status TEXT DEFAULT 'info',
            message TEXT,
            model TEXT,
            duration_ms INTEGER,
            data_json TEXT DEFAULT '{}',
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_formation_pipeline_events_job
        ON formation_pipeline_events(job_id, created_at)
        """
    )
    conn.commit()
    conn.close()


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
    ensure_observability_tables()
    summary = report.get("summary") or {}
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO content_review_reports
        (job_id, folder_id, source, generated_via, summary_json, report_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            folder_id,
            source,
            generated_via or report.get("generated_via"),
            _dumps(summary),
            _dumps(report),
        ),
    )
    report_id = cursor.lastrowid
    conn.commit()
    conn.close()
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


def get_latest_review_report(job_id: int, folder_id: int, kind: str = "compliance") -> dict | None:
    """Retourne le dernier rapport persisté pour une journée.

    `kind` : "compliance" (défaut) → source IN ('api', 'review_api', ...)
             "humanization"        → source LIKE '%humanization%'
    """
    ensure_observability_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    if kind == "humanization":
        cursor.execute(
            """
            SELECT id, source, generated_via, report_json, created_at
            FROM content_review_reports
            WHERE job_id = ? AND folder_id = ? AND source LIKE '%humanization%'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (job_id, folder_id),
        )
    else:
        cursor.execute(
            """
            SELECT id, source, generated_via, report_json, created_at
            FROM content_review_reports
            WHERE job_id = ? AND folder_id = ? AND source NOT LIKE '%humanization%'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (job_id, folder_id),
        )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    report_id, source, generated_via, report_json, created_at = row
    try:
        report = json.loads(report_json or "{}")
    except Exception as exc:
        logger.warning(
            f"⚠️ Rapport conformité DB illisible job={job_id} folder={folder_id}: {exc}"
        )
        return None
    report.setdefault("generated_via", generated_via)
    report["persisted_report_id"] = report_id
    report["persisted_source"] = source
    report["persisted_at"] = created_at
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
        ensure_observability_tables()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO formation_pipeline_events
            (job_id, folder_id, step, event_type, status, message, model,
             duration_ms, data_json, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                folder_id,
                step,
                event_type,
                status,
                message,
                model,
                duration_ms,
                _dumps(data),
                error,
            ),
        )
        event_id = cursor.lastrowid
        conn.commit()
        conn.close()
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
    ensure_observability_tables()
    limit = max(1, min(int(limit or 200), 500))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, job_id, folder_id, step, event_type, status, message, model,
               duration_ms, data_json, error, created_at
        FROM formation_pipeline_events
        WHERE job_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (job_id, limit),
    )
    rows = cursor.fetchall()
    conn.close()
    events = []
    for row in reversed(rows):
        (
            event_id,
            row_job_id,
            folder_id,
            step,
            event_type,
            status,
            message,
            model,
            duration_ms,
            data_json,
            error,
            created_at,
        ) = row
        try:
            data = json.loads(data_json or "{}")
        except Exception:
            data = {}
        events.append(
            {
                "id": event_id,
                "job_id": row_job_id,
                "folder_id": folder_id,
                "step": step,
                "event_type": event_type,
                "status": status,
                "message": message,
                "model": model,
                "duration_ms": duration_ms,
                "data": data,
                "error": error,
                "created_at": created_at,
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
    ensure_observability_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    if folder_id is None:
        cursor.execute(
            "DELETE FROM formation_pipeline_events WHERE job_id = ?",
            (job_id,),
        )
    elif include_global_events:
        cursor.execute(
            """
            DELETE FROM formation_pipeline_events
            WHERE job_id = ? AND (folder_id = ? OR folder_id IS NULL)
            """,
            (job_id, folder_id),
        )
    else:
        cursor.execute(
            "DELETE FROM formation_pipeline_events WHERE job_id = ? AND folder_id = ?",
            (job_id, folder_id),
        )
    deleted = cursor.rowcount or 0
    conn.commit()
    conn.close()
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
