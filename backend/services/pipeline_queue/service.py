"""Small facade consumed by HTTP routes and schedulers."""

from __future__ import annotations

from typing import Any, Mapping

from .contracts import WorkItem, WorkItemSpec
from .repository import WorkItemRepository
from .settings import QueueSettings


def new_repository(*, storage_backend: str | None = None) -> WorkItemRepository:
    return WorkItemRepository(storage_backend=storage_backend)


def enqueue_work_item(
    *,
    pipeline_job_id: int | None = None,
    folder_id: int | None = None,
    resource_key: str | None = None,
    task_type: str = "auto_pilot_tick",
    payload: Mapping[str, Any] | None = None,
    scope_key: str = "pipeline",
    run_id: str | None = None,
    dedupe_key: str | None = None,
    priority: int = 0,
    max_attempts: int = 5,
    repository: WorkItemRepository | None = None,
    settings: QueueSettings | None = None,
) -> WorkItem:
    """Persist a work item and, for Service Bus, its outbox notification.

    Passing a stable ``dedupe_key`` makes repeated HTTP requests return the
    existing task instead of starting duplicate pipeline work.
    """
    settings = settings or QueueSettings.from_env()
    repository = repository or new_repository()
    return repository.enqueue(
        WorkItemSpec(
            pipeline_job_id=int(pipeline_job_id) if pipeline_job_id is not None else None,
            folder_id=int(folder_id) if folder_id is not None else None,
            resource_key=resource_key,
            task_type=task_type,
            payload=payload or {},
            scope_key=scope_key,
            run_id=run_id,
            dedupe_key=dedupe_key,
            priority=priority,
            max_attempts=max_attempts,
        ),
        notify=settings.uses_service_bus,
    )


def get_work_item(
    work_item_id: str,
    *,
    repository: WorkItemRepository | None = None,
) -> WorkItem | None:
    return (repository or new_repository()).get(work_item_id)


def get_latest_work_item(
    pipeline_job_id: int,
    *,
    scope_key: str | None = None,
    repository: WorkItemRepository | None = None,
) -> WorkItem | None:
    return (repository or new_repository()).latest_for_job(
        int(pipeline_job_id),
        scope_key=scope_key,
    )


def get_latest_folder_work_item(
    folder_id: int,
    *,
    scope_key: str | None = None,
    repository: WorkItemRepository | None = None,
) -> WorkItem | None:
    return (repository or new_repository()).latest_for_folder(
        int(folder_id),
        scope_key=scope_key,
    )


def cancel_latest_work_item(
    pipeline_job_id: int,
    *,
    scope_key: str | None = None,
    repository: WorkItemRepository | None = None,
) -> WorkItem | None:
    repository = repository or new_repository()
    item = repository.latest_for_job(
        int(pipeline_job_id),
        scope_key=scope_key,
    )
    if item and not item.terminal:
        repository.cancel(item.id)
        return repository.get(item.id)
    return item
