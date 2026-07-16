"""Deep readiness checks for database, Blob storage, worker, and queue."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import threading
import time
from typing import Any, Callable

from services.pipeline_queue.repository import WorkItemRepository
from services.pipeline_runtime_health import embedded_worker_health_snapshot


class ReadinessCheckError(RuntimeError):
    def __init__(self, check: str, message: str):
        super().__init__(message)
        self.check = check


_BLOB_CACHE_LOCK = threading.Lock()
_BLOB_LAST_SUCCESS_MONOTONIC: float | None = None


def _enabled(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _queue_mode_enabled() -> bool:
    return os.getenv("PIPELINE_EXECUTION_MODE", "inline").strip().lower() in {
        "queue",
        "queued",
        "durable",
    }


def _as_utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def check_database() -> dict[str, Any]:
    try:
        from database.postgres import get_postgres_connection, postgres_enabled

        if postgres_enabled():
            with get_postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 AS ready")
                    cur.fetchone()
            return {"status": "ok", "backend": "postgres"}

        from database.db import get_db_connection

        conn = get_db_connection()
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        return {"status": "ok", "backend": "sqlite"}
    except Exception as exc:
        raise ReadinessCheckError("database", "Base de données indisponible") from exc


def check_blob_storage(*, force: bool = False, now_monotonic: float | None = None) -> dict[str, Any]:
    global _BLOB_LAST_SUCCESS_MONOTONIC
    if not _enabled("PIPELINE_ARTIFACTS_REQUIRED"):
        return {"status": "skipped", "required": False}

    connection_string = (
        os.getenv("AZURE_TTS_STORAGE_CONNECTION_STRING")
        or os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        or ""
    ).strip()
    if not connection_string:
        raise ReadinessCheckError("blob", "Stockage d'artefacts obligatoire non configuré")

    now = time.monotonic() if now_monotonic is None else float(now_monotonic)
    cache_seconds = _bounded_int("PIPELINE_READY_BLOB_CACHE_SECONDS", 60, 0, 600)
    with _BLOB_CACHE_LOCK:
        last_success = _BLOB_LAST_SUCCESS_MONOTONIC
    if not force and last_success is not None and now - last_success <= cache_seconds:
        return {"status": "ok", "verified": True, "cached": True}

    try:
        from services.azure_blob_service import _get_blob_service_client

        # This is an authenticated request to Azure, not a textual check of the
        # connection string. Invalid credentials and unreachable endpoints fail.
        _get_blob_service_client().get_account_information()
    except Exception as exc:
        raise ReadinessCheckError("blob", "Azure Blob inaccessible") from exc

    with _BLOB_CACHE_LOCK:
        _BLOB_LAST_SUCCESS_MONOTONIC = now
    return {"status": "ok", "verified": True, "cached": False}


def check_embedded_worker() -> dict[str, Any]:
    snapshot = embedded_worker_health_snapshot()
    if not snapshot["expected"]:
        return {"status": "skipped", "expected": False}

    if not snapshot["task_alive"]:
        raise ReadinessCheckError("worker", "Tâche du worker embarqué arrêtée")
    if snapshot["status"] != "running":
        raise ReadinessCheckError("worker", f"Worker embarqué en état {snapshot['status']}")

    default_stale = max(
        30,
        _bounded_int("PIPELINE_WORK_HEARTBEAT_SECONDS", 60, 5, 3600) * 3,
    )
    stale_seconds = _bounded_int(
        "PIPELINE_WORKER_READY_STALE_SECONDS",
        default_stale,
        15,
        3600,
    )
    heartbeat_age = snapshot["heartbeat_age_seconds"]
    if heartbeat_age is None or heartbeat_age > stale_seconds:
        raise ReadinessCheckError("worker", "Heartbeat du worker embarqué périmé")
    return {
        "status": "ok",
        "expected": True,
        "heartbeat_age_seconds": round(float(heartbeat_age), 3),
    }


def check_pipeline_queue(
    *,
    repository_factory: Callable[[], WorkItemRepository] = WorkItemRepository,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not _queue_mode_enabled():
        return {"status": "skipped", "enabled": False}

    current = _as_utc(now or datetime.now(timezone.utc))
    if current is None:  # Defensive only: the default above is always valid.
        current = datetime.now(timezone.utc)
    try:
        snapshot = repository_factory().readiness_snapshot(now=current)
    except Exception as exc:
        raise ReadinessCheckError("queue", "État de la file durable illisible") from exc

    due_count = int(snapshot.get("due_count") or 0)
    expired_count = int(snapshot.get("expired_running_count") or 0)
    active_running = int(snapshot.get("active_running_count") or 0)
    candidates = [
        value
        for value in (
            _as_utc(snapshot.get("oldest_due_at")),
            _as_utc(snapshot.get("oldest_expired_lease_at")),
        )
        if value is not None
    ]
    oldest = min(candidates) if candidates else None
    stalled_age = max(0.0, (current - oldest).total_seconds()) if oldest else 0.0
    stall_seconds = _bounded_int("PIPELINE_READY_QUEUE_STALL_SECONDS", 600, 30, 86400)

    if (due_count or expired_count) and active_running == 0 and stalled_age > stall_seconds:
        raise ReadinessCheckError(
            "queue",
            f"File durable sans progression depuis {int(stalled_age)} secondes",
        )
    return {
        "status": "ok",
        "enabled": True,
        "due_count": due_count,
        "expired_running_count": expired_count,
        "active_running_count": active_running,
        "oldest_actionable_age_seconds": round(stalled_age, 3),
    }


def run_readiness_checks() -> dict[str, Any]:
    checks = {"database": check_database()}
    checks["blob"] = check_blob_storage()
    if _queue_mode_enabled():
        checks["worker"] = check_embedded_worker()
        checks["queue"] = check_pipeline_queue()
    else:
        checks["worker"] = {"status": "skipped", "expected": False}
        checks["queue"] = {"status": "skipped", "enabled": False}
    return checks


def reset_blob_readiness_cache_for_tests() -> None:
    global _BLOB_LAST_SUCCESS_MONOTONIC
    with _BLOB_CACHE_LOCK:
        _BLOB_LAST_SUCCESS_MONOTONIC = None
