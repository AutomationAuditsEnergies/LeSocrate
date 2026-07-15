"""In-process health state for the embedded durable pipeline worker."""

from __future__ import annotations

import os
import threading
import time
from typing import Any


_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "task": None,
    "status": "not_started",
    "owner": None,
    "last_heartbeat_monotonic": None,
    "last_error": None,
}


def embedded_worker_expected() -> bool:
    execution_mode = os.getenv("PIPELINE_EXECUTION_MODE", "inline").strip().lower()
    embedded = os.getenv("PIPELINE_EMBEDDED_WORKER", "0").strip().lower()
    return execution_mode in {"queue", "queued", "durable"} and embedded in {
        "1",
        "true",
        "yes",
        "on",
    }


def _task_is_alive(task: Any) -> bool:
    if task is None:
        return False
    is_alive = getattr(task, "is_alive", None)
    if callable(is_alive):
        return bool(is_alive())
    greenlet = getattr(task, "g", None)
    if greenlet is not None and hasattr(greenlet, "dead"):
        return not bool(greenlet.dead)
    if hasattr(task, "dead"):
        return not bool(task.dead)
    # Flask-SocketIO only guarantees a joinable task handle. If the backend
    # does not expose lifecycle state, the independently refreshed heartbeat
    # remains authoritative.
    return True


def register_embedded_worker_task(task: Any) -> None:
    with _LOCK:
        _STATE["task"] = task
        if _STATE.get("status") != "running":
            _STATE.update(
                status="starting",
                last_heartbeat_monotonic=time.monotonic(),
                last_error=None,
            )


def mark_embedded_worker_started(owner: str | None = None) -> None:
    with _LOCK:
        _STATE.update(
            status="running",
            owner=owner,
            last_heartbeat_monotonic=time.monotonic(),
            last_error=None,
        )


def mark_embedded_worker_heartbeat() -> None:
    with _LOCK:
        _STATE.update(
            status="running",
            last_heartbeat_monotonic=time.monotonic(),
            last_error=None,
        )


def mark_embedded_worker_error(exc: BaseException) -> None:
    with _LOCK:
        _STATE.update(
            status="restarting",
            last_heartbeat_monotonic=time.monotonic(),
            last_error=f"{type(exc).__name__}: {str(exc)}"[:500],
        )


def embedded_worker_health_snapshot(*, now_monotonic: float | None = None) -> dict[str, Any]:
    now = time.monotonic() if now_monotonic is None else float(now_monotonic)
    with _LOCK:
        state = dict(_STATE)
    heartbeat = state.get("last_heartbeat_monotonic")
    return {
        "expected": embedded_worker_expected(),
        "status": state.get("status"),
        "owner": state.get("owner"),
        "task_alive": _task_is_alive(state.get("task")),
        "heartbeat_age_seconds": (max(0.0, now - heartbeat) if heartbeat is not None else None),
        "last_error": state.get("last_error"),
    }


def reset_embedded_worker_health_for_tests() -> None:
    with _LOCK:
        _STATE.update(
            task=None,
            status="not_started",
            owner=None,
            last_heartbeat_monotonic=None,
            last_error=None,
        )
