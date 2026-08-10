"""Run course scheduling, H-72 audio and reminder ticks outside the web process.

Use ``python -m workers.course_scheduler_worker`` for a dedicated singleton
scheduler, or add ``--once`` for deployment smoke tests and cron-style runs.
The worker never overlaps its own ticks: it waits for one complete pass before
starting the next one.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
import signal
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from dotenv import load_dotenv


load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from services.course_schedule_service import (  # noqa: E402
    process_due_reminders,
    run_scheduler_tick as advance_course_schedules,
)
from services.scheduled_audio_service import process_due_audio_generations  # noqa: E402
from services.attendance_service import process_due_attendance_exports  # noqa: E402
from utils.logger import configure_logging, get_logger  # noqa: E402


logger = get_logger(__name__)
DEFAULT_INTERVAL_SECONDS = 300.0
MIN_INTERVAL_SECONDS = 30.0


def _result_counts(result: Any) -> tuple[int, int]:
    if result is None:
        return 0, 0
    items = list(result) if isinstance(result, (list, tuple)) else [result]
    failed = sum(
        1
        for item in items
        if isinstance(item, Mapping) and item.get("success") is False
    )
    return len(items), failed


def run_scheduler_tick_once(*, wait_for_audio: bool = False) -> dict[str, Any]:
    """Run one isolated pass over the existing business services.

    A failed stage does not prevent the other due work from running. Only
    aggregate counts and bounded errors are logged, never reminder recipients.
    """
    started_at = datetime.now(timezone.utc)
    started_monotonic = time.monotonic()
    steps: dict[str, dict[str, Any]] = {}
    callbacks: tuple[tuple[str, Callable[[], Any]], ...] = (
        ("schedule", advance_course_schedules),
        (
            "audio_j_minus_1",
            lambda: process_due_audio_generations(
                wait_for_completion=wait_for_audio,
            ),
        ),
        ("reminders", process_due_reminders),
        ("attendance_exports", process_due_attendance_exports),
    )

    for name, callback in callbacks:
        step_started = time.monotonic()
        try:
            result = callback()
            processed, failed = _result_counts(result)
            steps[name] = {
                "success": failed == 0,
                "processed": processed,
                "failed": failed,
                "duration_seconds": round(time.monotonic() - step_started, 3),
            }
            if failed:
                logger.warning(
                    "COURSE_SCHEDULER_STEP_DEGRADED step=%s processed=%s failed=%s",
                    name,
                    processed,
                    failed,
                )
        except Exception as exc:
            steps[name] = {
                "success": False,
                "processed": 0,
                "failed": 1,
                "duration_seconds": round(time.monotonic() - step_started, 3),
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            }
            logger.exception("COURSE_SCHEDULER_STEP_FAILED step=%s", name)

    duration = round(time.monotonic() - started_monotonic, 3)
    healthy = all(step["success"] for step in steps.values())
    totals = {name: step["processed"] for name, step in steps.items()}
    log = logger.info if healthy else logger.warning
    log(
        "COURSE_SCHEDULER_HEARTBEAT healthy=%s started_at=%s duration_seconds=%s "
        "schedule=%s audio_j_minus_1=%s reminders=%s attendance_exports=%s",
        healthy,
        started_at.isoformat(),
        duration,
        totals.get("schedule", 0),
        totals.get("audio_j_minus_1", 0),
        totals.get("reminders", 0),
        totals.get("attendance_exports", 0),
    )
    return {
        "healthy": healthy,
        "started_at": started_at.isoformat(),
        "duration_seconds": duration,
        "steps": steps,
    }


def scheduler_interval_seconds(value: float | str | None = None) -> float:
    raw = value if value is not None else os.getenv(
        "COURSE_SCHEDULER_INTERVAL_SECONDS",
        str(DEFAULT_INTERVAL_SECONDS),
    )
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "COURSE_SCHEDULER_INTERVAL_INVALID value=%r fallback=%s",
            raw,
            DEFAULT_INTERVAL_SECONDS,
        )
        parsed = DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, parsed)


def run_scheduler_loop(
    stop_event: threading.Event,
    *,
    interval_seconds: float | str | None = None,
    max_ticks: int | None = None,
) -> int:
    """Run sequential ticks until stopped; ``max_ticks`` is a test hook."""
    interval = scheduler_interval_seconds(interval_seconds)
    tick_count = 0
    logger.info("COURSE_SCHEDULER_WORKER_READY interval_seconds=%s", interval)

    while not stop_event.is_set():
        cycle_started = time.monotonic()
        run_scheduler_tick_once()
        tick_count += 1
        if max_ticks is not None and tick_count >= max(0, int(max_ticks)):
            break

        elapsed = time.monotonic() - cycle_started
        # Keep a small retry pause after an overrun instead of spinning.
        wait_seconds = max(1.0, interval - elapsed)
        if stop_event.wait(wait_seconds):
            break

    logger.info("COURSE_SCHEDULER_WORKER_STOPPED tick_count=%s", tick_count)
    return tick_count


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Scheduler durable des cours")
    parser.add_argument("--once", action="store_true", help="Exécute un seul tick puis quitte")
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=None,
        help="Cadence de boucle (minimum 30 secondes)",
    )
    args = parser.parse_args(argv)
    configure_logging()

    if args.once:
        # A one-shot process cannot leave claimed audio in a daemon thread:
        # the interpreter would terminate it as soon as main returns. Run each
        # due occurrence inline so cron/smoke mode exits only after completion
        # (or after the durable claim has been marked failed).
        return 0 if run_scheduler_tick_once(wait_for_audio=True)["healthy"] else 1

    stop_event = threading.Event()

    def _stop(signum, _frame):
        logger.warning("COURSE_SCHEDULER_STOP_SIGNAL signal=%s", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    run_scheduler_loop(stop_event, interval_seconds=args.interval_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
