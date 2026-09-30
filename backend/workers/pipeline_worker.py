"""Run the durable formation worker.

Local: ``python -m workers.pipeline_worker``
Azure App Service continuous WebJob: use the same command with
``PIPELINE_QUEUE_BACKEND=service_bus``.
"""

from __future__ import annotations

import argparse
import importlib
import os
import signal
import threading

from dotenv import load_dotenv


load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from services.pipeline_queue.handlers import mark_pipeline_dead_letter
from services.pipeline_queue.repository import WorkItemRepository
from services.pipeline_queue.routing import (
    normalize_worker_kind,
    task_types_for_worker,
)
from services.pipeline_queue.settings import QueueSettings
from services.pipeline_queue.worker import PipelineWorker
from utils.logger import get_logger


logger = get_logger(__name__)


def _load_handler(path: str):
    module_name, separator, attribute = path.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("PIPELINE_WORKER_HANDLER doit être au format module:function")
    module = importlib.import_module(module_name)
    handler = getattr(module, attribute)
    if not callable(handler):
        raise TypeError(f"Handler non callable: {path}")
    return handler


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Worker durable des pipelines formation")
    parser.add_argument("--once", action="store_true", help="Traite au plus un work-item DB")
    parser.add_argument(
        "--worker-kind",
        choices=("general", "ai", "audio"),
        default=None,
        help="Limite le processus aux tâches IA ou audio",
    )
    args = parser.parse_args(argv)

    if args.worker_kind:
        os.environ["PIPELINE_WORKER_KIND"] = args.worker_kind
    settings = QueueSettings.from_env()
    worker_kind = normalize_worker_kind(settings.worker_kind)
    accepted_task_types = task_types_for_worker(worker_kind)
    handler_path = os.getenv(
        "PIPELINE_WORKER_HANDLER",
        "services.pipeline_queue.handlers:handle_pipeline_work_item",
    )
    repository = WorkItemRepository()
    worker = PipelineWorker(
        repository,
        _load_handler(handler_path),
        settings=settings,
        on_dead_letter=mark_pipeline_dead_letter,
        accepted_task_types=accepted_task_types,
    )
    repository.ensure_schema()
    logger.info(
        "PIPELINE_WORKER_READY owner=%s kind=%s queue_backend=%s broker_queue=%s "
        "storage_backend=%s handler=%s task_types=%s",
        worker.owner,
        worker_kind,
        settings.backend,
        settings.receiver_queue_name if settings.uses_service_bus else "-",
        repository.storage_backend,
        handler_path,
        sorted(accepted_task_types) if accepted_task_types else ["*"],
    )

    if args.once:
        outcome = worker.process_next()
        logger.info("PIPELINE_WORKER_ONCE outcome=%s work_item_id=%s", outcome.status, outcome.work_item_id)
        return 0

    stop_event = threading.Event()

    def _stop(signum, _frame):
        logger.warning("PIPELINE_WORKER_STOP_SIGNAL signal=%s", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker.run_forever(stop_event=stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
