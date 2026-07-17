"""Supervise the SaaS web API and its durable background workers.

Azure App Service starts this module as the container entry point.  Keeping the
HTTP server, the formation pipeline and the course scheduler in separate OS
processes prevents a long audio/LLM task from starving login and health-check
requests.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping


BASE_DIR = Path(__file__).resolve().parent
TRUE_VALUES = {"1", "true", "yes", "on"}
WORKER_RESTART_DELAY_SECONDS = 5.0
SHUTDOWN_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class ChildSpec:
    name: str
    command: tuple[str, ...]
    env: dict[str, str]
    critical: bool = False


def _enabled(env: Mapping[str, str], name: str) -> bool:
    return str(env.get(name, "0")).strip().lower() in TRUE_VALUES


def build_child_specs(env: Mapping[str, str] | None = None) -> tuple[ChildSpec, ...]:
    """Build isolated child environments without mutating ``os.environ``."""
    base_env = dict(os.environ if env is None else env)
    python = sys.executable

    web_env = {
        **base_env,
        "SOCRATE_PROCESS_ROLE": "web",
        "PIPELINE_EMBEDDED_WORKER": "0",
        "COURSE_SCHEDULER_ENABLED": "0",
    }
    specs = [
        ChildSpec("web", (python, "run.py"), web_env, critical=True),
    ]

    pipeline_enabled = _enabled(base_env, "PIPELINE_DEDICATED_WORKER") or _enabled(
        base_env,
        "PIPELINE_EMBEDDED_WORKER",
    )
    if pipeline_enabled:
        specs.append(
            ChildSpec(
                "pipeline-worker",
                (python, "-m", "workers.pipeline_worker"),
                {
                    **base_env,
                    "SOCRATE_PROCESS_ROLE": "pipeline-worker",
                    "PIPELINE_EMBEDDED_WORKER": "0",
                    "COURSE_SCHEDULER_ENABLED": "0",
                },
            )
        )

    if _enabled(base_env, "COURSE_SCHEDULER_ENABLED"):
        specs.append(
            ChildSpec(
                "course-scheduler",
                (python, "-m", "workers.course_scheduler_worker"),
                {
                    **base_env,
                    "SOCRATE_PROCESS_ROLE": "course-scheduler",
                    "PIPELINE_EMBEDDED_WORKER": "0",
                    "COURSE_SCHEDULER_ENABLED": "0",
                },
            )
        )

    return tuple(specs)


def _spawn(spec: ChildSpec) -> subprocess.Popen:
    print(
        f"SAAS_PROCESS_START name={spec.name} command={' '.join(spec.command)}",
        flush=True,
    )
    return subprocess.Popen(
        spec.command,
        cwd=BASE_DIR,
        env=spec.env,
    )


def _stop_children(children: Mapping[str, subprocess.Popen]) -> None:
    running = [
        process
        for process in reversed(tuple(children.values()))
        if process.poll() is None
    ]
    for process in running:
        process.terminate()

    deadline = time.monotonic() + SHUTDOWN_TIMEOUT_SECONDS
    for process in running:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()
    for process in running:
        if process.poll() is None:
            process.wait(timeout=5)


def main() -> int:
    specs = build_child_specs()
    specs_by_name = {spec.name: spec for spec in specs}
    stop_event = threading.Event()
    children: dict[str, subprocess.Popen] = {}

    def _request_stop(signum, _frame):
        print(f"SAAS_PROCESS_STOP_SIGNAL signal={signum}", flush=True)
        stop_event.set()

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    try:
        for spec in specs:
            children[spec.name] = _spawn(spec)

        while not stop_event.wait(1.0):
            for name, process in tuple(children.items()):
                return_code = process.poll()
                if return_code is None:
                    continue

                spec = specs_by_name[name]
                print(
                    f"SAAS_PROCESS_EXIT name={name} return_code={return_code}",
                    flush=True,
                )
                if spec.critical:
                    return return_code or 1

                if stop_event.wait(WORKER_RESTART_DELAY_SECONDS):
                    break
                children[name] = _spawn(spec)
        return 0
    finally:
        _stop_children(children)


if __name__ == "__main__":
    raise SystemExit(main())
