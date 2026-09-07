"""Contracts shared by the durable pipeline queue implementations.

The broker message deliberately contains identifiers only.  PostgreSQL (or the
local SQLite database) remains the source of truth for payloads, attempts and
leases.  This keeps Azure Service Bus messages small and makes redelivery safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkStatus(str, Enum):
    QUEUED = "queued"
    RETRY_SCHEDULED = "retry_scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    DEAD_LETTERED = "dead_lettered"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {
    WorkStatus.COMPLETED.value,
    WorkStatus.DEAD_LETTERED.value,
    WorkStatus.CANCELLED.value,
}


@dataclass(frozen=True)
class WorkItemSpec:
    pipeline_job_id: int | None = None
    task_type: str = "auto_pilot_tick"
    payload: Mapping[str, Any] = field(default_factory=dict)
    scope_key: str = "pipeline"
    folder_id: int | None = None
    resource_key: str | None = None
    run_id: str | None = None
    dedupe_key: str | None = None
    priority: int = 0
    max_attempts: int = 5
    available_at: datetime | None = None


@dataclass(frozen=True)
class WorkItem:
    id: str
    pipeline_job_id: int | None
    folder_id: int | None
    resource_key: str
    run_id: str
    task_type: str
    scope_key: str
    dedupe_key: str
    payload: Mapping[str, Any]
    status: str
    priority: int
    attempt_count: int
    max_attempts: int
    available_at: datetime | str | None
    lease_owner: str | None
    lease_token: str | None
    lease_version: int
    lease_expires_at: datetime | str | None
    last_error: str | None
    result: Mapping[str, Any]
    created_at: datetime | str | None
    updated_at: datetime | str | None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


@dataclass(frozen=True)
class WorkResult:
    result: Mapping[str, Any] = field(default_factory=dict)
    next_items: Sequence[WorkItemSpec] = field(default_factory=tuple)


@dataclass(frozen=True)
class OutboxDelivery:
    id: str
    delivery_id: str
    work_item_id: str
    payload: Mapping[str, Any]
    available_at: datetime | str | None
    publish_attempts: int
    lease_token: str


class QueueError(RuntimeError):
    """Base exception for durable queue failures."""


class LeaseLostError(QueueError):
    """The work-item lease was replaced or cancelled by another worker."""


class RetryableWorkError(QueueError):
    """Explicitly marks a handler failure as retryable."""


class PermanentWorkError(QueueError):
    """Explicitly marks a poison/invalid task that must be dead-lettered."""
