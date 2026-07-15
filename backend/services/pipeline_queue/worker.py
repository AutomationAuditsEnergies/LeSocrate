"""Fenced worker runtime shared by local polling and Service Bus delivery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import random
import threading
import traceback
from typing import Callable, Mapping

from utils.logger import get_logger

from .contracts import (
    LeaseLostError,
    PermanentWorkError,
    WorkItem,
    WorkResult,
    WorkStatus,
    utcnow,
)
from .outbox import OutboxDispatcher, default_worker_identity
from .repository import WorkItemRepository
from .service_bus import ServiceBusTransport
from .settings import QueueSettings


logger = get_logger(__name__)

Handler = Callable[[WorkItem, "LeaseGuard"], WorkResult | Mapping | None]


@dataclass(frozen=True)
class ProcessOutcome:
    status: str
    work_item_id: str | None = None
    error: str | None = None


class RetryPolicy:
    def __init__(
        self,
        delays_seconds=(30, 120, 600, 1800, 7200),
        *,
        jitter_ratio: float = 0.2,
        random_fn: Callable[[], float] = random.random,
    ):
        self.delays_seconds = tuple(max(0, int(value)) for value in delays_seconds) or (30,)
        self.jitter_ratio = max(0.0, min(1.0, float(jitter_ratio)))
        self.random_fn = random_fn

    def delay_seconds(self, attempt_count: int) -> float:
        base = self.delays_seconds[min(max(1, attempt_count) - 1, len(self.delays_seconds) - 1)]
        if not base or not self.jitter_ratio:
            return float(base)
        # Symmetric jitter avoids synchronized retries after a provider outage.
        factor = 1.0 + ((self.random_fn() * 2.0 - 1.0) * self.jitter_ratio)
        return max(0.0, base * factor)


class LeaseGuard:
    def __init__(
        self,
        repository: WorkItemRepository,
        item: WorkItem,
        *,
        lease_seconds: int,
        heartbeat_seconds: int,
        health_callback: Callable[[], None] | None = None,
    ):
        if not item.lease_token:
            raise ValueError("Un work-item claimé doit avoir un lease_token")
        self.repository = repository
        self.item = item
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.health_callback = health_callback
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread: threading.Thread | None = None

    def _signal_health(self) -> None:
        if self.health_callback is None:
            return
        try:
            self.health_callback()
        except Exception:
            logger.exception("PIPELINE_WORKER_HEALTH_CALLBACK_FAILED")

    @property
    def lease_token(self) -> str:
        return str(self.item.lease_token)

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"lease-heartbeat-{self.item.id[:8]}",
            daemon=True,
        )
        self._thread.start()
        self._signal_health()

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.heartbeat_seconds):
            try:
                renewed = self.repository.renew_lease(
                    self.item.id,
                    self.lease_token,
                    lease_seconds=self.lease_seconds,
                )
            except Exception:
                renewed = False
                logger.exception("PIPELINE_WORK_LEASE_RENEW_ERROR work_item_id=%s", self.item.id)
            if not renewed:
                self._lost.set()
                return
            self._signal_health()

    def checkpoint(self) -> None:
        """Handlers should call this between expensive sub-steps."""
        self._signal_health()
        if self.lost:
            raise LeaseLostError(f"Lease perdu pendant le work-item {self.item.id}")
        current = self.repository.get(self.item.id)
        if (
            not current
            or current.status != WorkStatus.RUNNING.value
            or current.lease_token != self.lease_token
        ):
            self._lost.set()
            raise LeaseLostError(f"Lease/fencing invalide pour le work-item {self.item.id}")

    def report_progress(self, progress: Mapping) -> None:
        """Persist handler progress under the current fencing token."""
        self._signal_health()
        if self.lost:
            raise LeaseLostError(f"Lease perdu pendant le work-item {self.item.id}")
        self.repository.update_progress(
            self.item.id,
            self.lease_token,
            dict(progress),
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, min(5.0, self.heartbeat_seconds)))


class PipelineWorker:
    def __init__(
        self,
        repository: WorkItemRepository,
        handler: Handler,
        *,
        settings: QueueSettings | None = None,
        owner: str | None = None,
        retry_policy: RetryPolicy | None = None,
        on_dead_letter: Callable[[WorkItem, str], None] | None = None,
        health_callback: Callable[[], None] | None = None,
    ):
        self.repository = repository
        self.handler = handler
        self.settings = settings or QueueSettings.from_env()
        self.owner = owner or default_worker_identity()
        self.retry_policy = retry_policy or RetryPolicy()
        self.on_dead_letter = on_dead_letter
        self.health_callback = health_callback

    def _signal_health(self) -> None:
        if self.health_callback is None:
            return
        try:
            self.health_callback()
        except Exception:
            logger.exception("PIPELINE_WORKER_HEALTH_CALLBACK_FAILED owner=%s", self.owner)

    def process_next(self) -> ProcessOutcome:
        self._signal_health()
        item = self.repository.claim_next(
            owner=self.owner,
            lease_seconds=self.settings.lease_seconds,
        )
        if item is None:
            exhausted = self.repository.dead_letter_one_exhausted()
            if exhausted is not None:
                if self.on_dead_letter:
                    self.on_dead_letter(exhausted, exhausted.last_error or "Tentatives épuisées")
                return ProcessOutcome(
                    WorkStatus.DEAD_LETTERED.value,
                    exhausted.id,
                    exhausted.last_error,
                )
            return ProcessOutcome("idle")
        return self._process_claimed(item)

    def process_work_item(self, work_item_id: str) -> ProcessOutcome:
        self._signal_health()
        item = self.repository.claim(
            work_item_id,
            owner=self.owner,
            lease_seconds=self.settings.lease_seconds,
        )
        if item is None:
            existing = self.repository.get(work_item_id)
            if existing is None:
                return ProcessOutcome("missing", work_item_id)
            if existing.terminal:
                return ProcessOutcome(existing.status, work_item_id, existing.last_error)
            if self.repository.mark_exhausted_if_stale(
                work_item_id,
                error=existing.last_error or "Dernière tentative interrompue; lease expiré",
            ):
                exhausted = self.repository.get(work_item_id) or existing
                if self.on_dead_letter:
                    self.on_dead_letter(
                        exhausted,
                        exhausted.last_error or "Tentatives épuisées",
                    )
                return ProcessOutcome(WorkStatus.DEAD_LETTERED.value, work_item_id)
            return ProcessOutcome("busy", work_item_id)
        return self._process_claimed(item)

    def _process_claimed(self, item: WorkItem) -> ProcessOutcome:
        guard = LeaseGuard(
            self.repository,
            item,
            lease_seconds=self.settings.lease_seconds,
            heartbeat_seconds=self.settings.heartbeat_seconds,
            health_callback=self.health_callback,
        )
        guard.start()
        logger.info(
            "PIPELINE_WORK_STARTED work_item_id=%s job_id=%s run_id=%s task_type=%s "
            "attempt=%s/%s owner=%s fence=%s",
            item.id,
            item.pipeline_job_id,
            item.run_id,
            item.task_type,
            item.attempt_count,
            item.max_attempts,
            self.owner,
            item.lease_version,
        )
        try:
            raw_result = self.handler(item, guard)
            guard.checkpoint()
            if raw_result is None:
                result = WorkResult()
            elif isinstance(raw_result, WorkResult):
                result = raw_result
            elif isinstance(raw_result, Mapping):
                result = WorkResult(result=dict(raw_result))
            else:
                raise PermanentWorkError(
                    f"Handler {item.task_type} a retourné {type(raw_result).__name__}"
                )
            guard.stop()
            self.repository.complete(
                item.id,
                guard.lease_token,
                result=result.result,
                next_items=result.next_items,
                notify=self.settings.uses_service_bus,
            )
            logger.info(
                "PIPELINE_WORK_COMPLETED work_item_id=%s job_id=%s task_type=%s attempt=%s",
                item.id,
                item.pipeline_job_id,
                item.task_type,
                item.attempt_count,
            )
            return ProcessOutcome(WorkStatus.COMPLETED.value, item.id)
        except LeaseLostError as exc:
            guard.stop()
            logger.warning(
                "PIPELINE_WORK_LEASE_LOST work_item_id=%s job_id=%s error=%s",
                item.id,
                item.pipeline_job_id,
                str(exc),
            )
            return ProcessOutcome("lease_lost", item.id, str(exc))
        except BaseException as exc:
            guard.stop()
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            error = f"{type(exc).__name__}: {str(exc)}"[:4000]
            permanent = isinstance(exc, PermanentWorkError)
            try:
                if permanent or item.attempt_count >= item.max_attempts:
                    self.repository.dead_letter(item.id, guard.lease_token, error=error)
                    if self.on_dead_letter:
                        self.on_dead_letter(item, error)
                    logger.error(
                        "PIPELINE_WORK_DEAD_LETTERED work_item_id=%s job_id=%s "
                        "task_type=%s attempt=%s/%s error=%s",
                        item.id,
                        item.pipeline_job_id,
                        item.task_type,
                        item.attempt_count,
                        item.max_attempts,
                        error,
                    )
                    return ProcessOutcome(WorkStatus.DEAD_LETTERED.value, item.id, error)

                delay = self.retry_policy.delay_seconds(item.attempt_count)
                retry_at = utcnow() + timedelta(seconds=delay)
                self.repository.retry(
                    item.id,
                    guard.lease_token,
                    error=error,
                    available_at=retry_at,
                    notify=self.settings.uses_service_bus,
                )
                logger.warning(
                    "PIPELINE_WORK_RETRY_SCHEDULED work_item_id=%s job_id=%s "
                    "task_type=%s attempt=%s/%s delay_seconds=%.1f error=%s",
                    item.id,
                    item.pipeline_job_id,
                    item.task_type,
                    item.attempt_count,
                    item.max_attempts,
                    delay,
                    error,
                )
                return ProcessOutcome(WorkStatus.RETRY_SCHEDULED.value, item.id, error)
            except LeaseLostError as lease_exc:
                logger.warning(
                    "PIPELINE_WORK_SETTLE_LEASE_LOST work_item_id=%s original_error=%s settle_error=%s",
                    item.id,
                    error,
                    lease_exc,
                )
                return ProcessOutcome("lease_lost", item.id, error)
            finally:
                logger.debug(
                    "PIPELINE_WORK_EXCEPTION_TRACE work_item_id=%s\n%s",
                    item.id,
                    "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                )

    def run_forever(self, *, stop_event: threading.Event | None = None) -> None:
        stop_event = stop_event or threading.Event()
        if self.settings.uses_service_bus:
            self._run_service_bus(stop_event)
        else:
            self._run_database(stop_event)

    def _run_database(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            outcome = self.process_next()
            if outcome.status == "idle":
                stop_event.wait(self.settings.poll_seconds)

    def _run_service_bus(self, stop_event: threading.Event) -> None:
        transport = ServiceBusTransport(self.settings)
        dispatcher = OutboxDispatcher(
            self.repository,
            transport,
            owner=f"{self.owner}:outbox",
        )
        try:
            with transport.receiver() as receiver:
                while not stop_event.is_set():
                    self._signal_health()
                    dispatcher.dispatch_once(limit=self.settings.outbox_batch_size)
                    delivery = receiver.receive_one()
                    if delivery is None:
                        # Reconciliation path: DB remains authoritative even if a
                        # broker notification was lost or never published.
                        self.process_next()
                        continue
                    work_item_id = str(delivery.envelope["work_item_id"])
                    outcome = self.process_work_item(work_item_id)
                    try:
                        if outcome.status == WorkStatus.DEAD_LETTERED.value:
                            receiver.dead_letter(
                                delivery,
                                reason="PipelineWorkDeadLettered",
                                description=outcome.error or "Work-item dead-lettered",
                            )
                        else:
                            # Completion is safe for duplicate/busy deliveries:
                            # the DB lease and reconciliation poll preserve work.
                            receiver.complete(delivery)
                    except Exception:
                        logger.exception(
                            "PIPELINE_SERVICE_BUS_SETTLEMENT_FAILED work_item_id=%s outcome=%s",
                            work_item_id,
                            outcome.status,
                        )
        finally:
            transport.close()
