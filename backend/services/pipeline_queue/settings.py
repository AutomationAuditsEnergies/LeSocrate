"""Environment-backed settings for the durable pipeline queue."""

from __future__ import annotations

from dataclasses import dataclass
import os

from .routing import normalize_worker_kind, worker_kind_for_task


def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class QueueSettings:
    backend: str
    lease_seconds: int
    heartbeat_seconds: int
    poll_seconds: float
    outbox_batch_size: int
    service_bus_connection_string: str
    service_bus_namespace: str
    service_bus_queue_name: str
    service_bus_websockets: bool
    service_bus_lock_renewal_seconds: int
    worker_kind: str = "general"
    service_bus_ai_queue_name: str = ""
    service_bus_audio_queue_name: str = ""
    outbox_renotify_seconds: int = 600

    @property
    def uses_service_bus(self) -> bool:
        return self.backend == "service_bus"

    @property
    def receiver_queue_name(self) -> str:
        if self.worker_kind == "ai":
            return self.service_bus_ai_queue_name or self.service_bus_queue_name
        if self.worker_kind == "audio":
            return self.service_bus_audio_queue_name or self.service_bus_queue_name
        return self.service_bus_queue_name

    def queue_name_for_task(self, task_type: str | None) -> str:
        kind = worker_kind_for_task(task_type)
        if kind == "ai":
            return self.service_bus_ai_queue_name or self.service_bus_queue_name
        if kind == "audio":
            return self.service_bus_audio_queue_name or self.service_bus_queue_name
        return self.service_bus_queue_name

    @classmethod
    def from_env(cls) -> "QueueSettings":
        backend = (os.getenv("PIPELINE_QUEUE_BACKEND") or "database").strip().lower()
        aliases = {
            "db": "database",
            "postgres": "database",
            "sqlite": "database",
            "azure": "service_bus",
            "azure_service_bus": "service_bus",
        }
        backend = aliases.get(backend, backend)
        if backend not in {"database", "service_bus"}:
            raise ValueError("PIPELINE_QUEUE_BACKEND doit être database ou service_bus")

        lease_seconds = _int("PIPELINE_WORK_LEASE_SECONDS", 300, 30, 3600)
        heartbeat_seconds = _int(
            "PIPELINE_WORK_HEARTBEAT_SECONDS",
            min(60, max(10, lease_seconds // 3)),
            5,
            max(5, lease_seconds - 1),
        )
        connection_string = (os.getenv("AZURE_SERVICE_BUS_CONNECTION_STRING") or "").strip()
        namespace = (os.getenv("AZURE_SERVICE_BUS_NAMESPACE") or "").strip()
        queue_name = (
            os.getenv("PIPELINE_SERVICE_BUS_QUEUE")
            or os.getenv("AZURE_SERVICE_BUS_QUEUE")
            or "formation-pipeline"
        ).strip()
        ai_queue_name = (
            os.getenv("PIPELINE_SERVICE_BUS_AI_QUEUE") or queue_name
        ).strip()
        audio_queue_name = (
            os.getenv("PIPELINE_SERVICE_BUS_AUDIO_QUEUE") or queue_name
        ).strip()
        worker_kind = normalize_worker_kind(os.getenv("PIPELINE_WORKER_KIND"))
        if backend == "service_bus" and not (connection_string or namespace):
            raise ValueError(
                "Service Bus activé mais AZURE_SERVICE_BUS_CONNECTION_STRING ou "
                "AZURE_SERVICE_BUS_NAMESPACE est absent"
            )

        return cls(
            backend=backend,
            lease_seconds=lease_seconds,
            heartbeat_seconds=heartbeat_seconds,
            poll_seconds=_float("PIPELINE_WORKER_POLL_SECONDS", 1.0, 0.05, 60.0),
            outbox_batch_size=_int("PIPELINE_OUTBOX_BATCH_SIZE", 20, 1, 200),
            service_bus_connection_string=connection_string,
            service_bus_namespace=namespace,
            service_bus_queue_name=queue_name,
            service_bus_websockets=(
                os.getenv("AZURE_SERVICE_BUS_WEBSOCKETS", "0").strip().lower()
                in {"1", "true", "yes", "on"}
            ),
            service_bus_lock_renewal_seconds=_int(
                "PIPELINE_SERVICE_BUS_LOCK_RENEWAL_SECONDS", 21600, 300, 86400
            ),
            worker_kind=worker_kind,
            service_bus_ai_queue_name=ai_queue_name,
            service_bus_audio_queue_name=audio_queue_name,
            outbox_renotify_seconds=_int(
                "PIPELINE_OUTBOX_RENOTIFY_SECONDS", 600, 60, 86400
            ),
        )
