"""Publish durable PostgreSQL outbox rows to Azure Service Bus.

This lightweight process stays with the API App Service.  It is the bridge
that lets both Container Apps scale to zero: inserting a database work-item
still produces a broker notification capable of waking the right worker.
"""

from __future__ import annotations

import os
import signal
import threading

from dotenv import load_dotenv


load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from services.pipeline_queue.outbox import OutboxDispatcher
from services.pipeline_queue.repository import WorkItemRepository
from services.pipeline_queue.service_bus import ServiceBusTransport
from services.pipeline_queue.settings import QueueSettings
from utils.logger import get_logger


logger = get_logger(__name__)


def main() -> int:
    settings = QueueSettings.from_env()
    if not settings.uses_service_bus:
        raise RuntimeError(
            "pipeline_outbox_worker requiert PIPELINE_QUEUE_BACKEND=service_bus"
        )

    repository = WorkItemRepository()
    repository.ensure_schema()
    transport = ServiceBusTransport(settings)
    dispatcher = OutboxDispatcher(repository, transport)
    stop_event = threading.Event()

    def _stop(signum, _frame):
        logger.warning("PIPELINE_OUTBOX_STOP_SIGNAL signal=%s", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    logger.info(
        "PIPELINE_OUTBOX_READY storage_backend=%s ai_queue=%s audio_queue=%s",
        repository.storage_backend,
        settings.service_bus_ai_queue_name or settings.service_bus_queue_name,
        settings.service_bus_audio_queue_name or settings.service_bus_queue_name,
    )
    try:
        while not stop_event.is_set():
            reconciled = repository.reconcile_outbox_notifications(
                limit=settings.outbox_batch_size,
                renotify_after_seconds=settings.outbox_renotify_seconds,
            )
            published = dispatcher.dispatch_once(limit=settings.outbox_batch_size)
            if reconciled or published:
                logger.info(
                    "PIPELINE_OUTBOX_TICK reconciled=%s published=%s",
                    reconciled,
                    published,
                )
            if reconciled == 0 and published == 0:
                stop_event.wait(settings.poll_seconds)
    finally:
        transport.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
