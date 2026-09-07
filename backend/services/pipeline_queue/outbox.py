"""Transactional outbox dispatcher."""

from __future__ import annotations

from datetime import timedelta
import socket
import uuid

from utils.logger import get_logger

from .contracts import utcnow
from .repository import WorkItemRepository
from .service_bus import ServiceBusTransport


logger = get_logger(__name__)


def default_worker_identity(prefix: str = "pipeline-worker") -> str:
    # Unlike the previous PID-only lock, this stays unique across App Service
    # instances and process restarts.
    return f"{prefix}:{socket.gethostname()}:{uuid.uuid4()}"


class OutboxDispatcher:
    def __init__(
        self,
        repository: WorkItemRepository,
        transport: ServiceBusTransport,
        *,
        owner: str | None = None,
        lease_seconds: int = 60,
    ):
        self.repository = repository
        self.transport = transport
        self.owner = owner or default_worker_identity("pipeline-outbox")
        self.lease_seconds = max(10, lease_seconds)

    def dispatch_once(self, *, limit: int = 20) -> int:
        deliveries = self.repository.claim_due_outbox(
            owner=self.owner,
            lease_seconds=self.lease_seconds,
            limit=limit,
        )
        published = 0
        for delivery in deliveries:
            try:
                self.transport.send(delivery)
                self.repository.mark_outbox_published(delivery.id, delivery.lease_token)
                published += 1
            except Exception as exc:
                delay = min(300, 2 ** min(delivery.publish_attempts, 8))
                self.repository.mark_outbox_failed(
                    delivery.id,
                    delivery.lease_token,
                    error=str(exc),
                    retry_at=utcnow() + timedelta(seconds=delay),
                )
                logger.warning(
                    "PIPELINE_OUTBOX_SEND_FAILED outbox_id=%s work_item_id=%s attempt=%s error=%s",
                    delivery.id,
                    delivery.work_item_id,
                    delivery.publish_attempts,
                    str(exc)[:300],
                )
        return published
