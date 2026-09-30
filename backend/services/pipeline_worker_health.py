"""In-process health state for the embedded durable pipeline worker."""

from __future__ import annotations

from datetime import datetime, timezone
import threading
import time
from typing import Any


_lock = threading.Lock()
_state: dict[str, Any] = {
    "enabled": False,
    "running": False,
    "owner": None,
    "phase": "disabled",
    "current_work_item_id": None,
    "last_heartbeat_at": None,
    "last_heartbeat_monotonic": None,
    "last_error": None,
    "stale_after_seconds": 240.0,
}


def configure_pipeline_worker_health(*, enabled: bool, stale_after_seconds: float = 240.0) -> None:
    with _lock:
        _state.update({
            "enabled": bool(enabled),
            "running": False,
            "owner": None,
            "phase": "starting" if enabled else "disabled",
            "current_work_item_id": None,
            "last_heartbeat_at": None,
            "last_heartbeat_monotonic": None,
            "last_error": None,
            "stale_after_seconds": max(30.0, float(stale_after_seconds)),
        })


def mark_pipeline_worker_started(owner: str) -> None:
    with _lock:
        _state.update({
            "running": True,
            "owner": str(owner),
            "phase": "starting",
            "last_error": None,
        })
    record_pipeline_worker_heartbeat("starting")


def record_pipeline_worker_heartbeat(phase: str, work_item_id: str | None = None) -> None:
    now = datetime.now(timezone.utc)
    with _lock:
        _state.update({
            "running": True,
            "phase": str(phase or "polling"),
            "current_work_item_id": str(work_item_id) if work_item_id else None,
            "last_heartbeat_at": now.isoformat(),
            "last_heartbeat_monotonic": time.monotonic(),
            "last_error": None,
        })


def mark_pipeline_worker_crashed(error: str) -> None:
    with _lock:
        _state.update({
            "running": False,
            "phase": "crashed",
            "current_work_item_id": None,
            "last_error": str(error or "worker crashed")[:500],
        })


def get_pipeline_worker_health(*, now_monotonic: float | None = None) -> dict[str, Any]:
    with _lock:
        snapshot = dict(_state)
    if not snapshot["enabled"]:
        return {
            "enabled": False,
            "monitored": False,
            "healthy": True,
            "status": "disabled",
            "phase": "disabled",
            "last_heartbeat_at": None,
            "current_work_item_id": None,
        }

    current = time.monotonic() if now_monotonic is None else float(now_monotonic)
    last = snapshot.get("last_heartbeat_monotonic")
    age = None if last is None else max(0.0, current - float(last))
    stale = age is None or age > float(snapshot["stale_after_seconds"])
    healthy = bool(snapshot["running"] and not stale and not snapshot.get("last_error"))
    if healthy:
        status = "healthy"
    elif snapshot.get("last_error"):
        status = "crashed"
    elif stale and snapshot.get("running"):
        status = "stale"
    else:
        status = "starting"
    return {
        "enabled": True,
        "monitored": True,
        "healthy": healthy,
        "status": status,
        "phase": snapshot.get("phase"),
        "last_heartbeat_at": snapshot.get("last_heartbeat_at"),
        "heartbeat_age_seconds": age,
        "current_work_item_id": snapshot.get("current_work_item_id"),
    }
