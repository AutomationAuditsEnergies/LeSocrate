"""Optional Azure Service Bus notifier for durable DB work-items.

Service Bus is intentionally a notifier, not the source of truth.  A lost or
duplicated broker message is harmless because workers claim the referenced row
with a fenced database lease and also poll the database as reconciliation.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
import json
from typing import Any

from .contracts import OutboxDelivery, PermanentWorkError
from .settings import QueueSettings


def _load_azure_sdk():
    try:
        from azure.identity import DefaultAzureCredential
        from azure.servicebus import (
            AmqpTransportType,
            AutoLockRenewer,
            ServiceBusClient,
            ServiceBusMessage,
        )
    except ImportError as exc:  # pragma: no cover - exercised without Azure extra.
        raise RuntimeError(
            "Le backend Service Bus requiert azure-servicebus et azure-identity"
        ) from exc
    return {
        "DefaultAzureCredential": DefaultAzureCredential,
        "AmqpTransportType": AmqpTransportType,
        "AutoLockRenewer": AutoLockRenewer,
        "ServiceBusClient": ServiceBusClient,
        "ServiceBusMessage": ServiceBusMessage,
    }


def _fully_qualified_namespace(value: str) -> str:
    value = value.strip().removeprefix("sb://").rstrip("/")
    if value and "." not in value:
        value = f"{value}.servicebus.windows.net"
    return value


def _decode_body(message: Any) -> dict[str, Any]:
    body = getattr(message, "body", message)
    if isinstance(body, str):
        raw = body
    elif isinstance(body, (bytes, bytearray, memoryview)):
        raw = bytes(body).decode("utf-8")
    else:
        try:
            raw = b"".join(bytes(part) for part in body).decode("utf-8")
        except Exception:
            raw = str(message)
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise PermanentWorkError("Message Service Bus JSON invalide") from exc
    if not isinstance(payload, dict) or not payload.get("work_item_id"):
        raise PermanentWorkError("Message Service Bus sans work_item_id")
    if int(payload.get("version") or 0) != 1:
        raise PermanentWorkError("Version de message Service Bus non supportée")
    return payload


class ServiceBusTransport:
    def __init__(self, settings: QueueSettings, *, client=None, sdk=None):
        if not settings.uses_service_bus:
            raise ValueError("ServiceBusTransport requiert PIPELINE_QUEUE_BACKEND=service_bus")
        self.settings = settings
        self._sdk = sdk or _load_azure_sdk()
        self._credential = None
        if client is not None:
            self.client = client
            return

        kwargs = {}
        if settings.service_bus_websockets:
            kwargs["transport_type"] = self._sdk["AmqpTransportType"].AmqpOverWebsocket
        client_cls = self._sdk["ServiceBusClient"]
        if settings.service_bus_connection_string:
            self.client = client_cls.from_connection_string(
                settings.service_bus_connection_string,
                **kwargs,
            )
        else:
            self._credential = self._sdk["DefaultAzureCredential"]()
            self.client = client_cls(
                _fully_qualified_namespace(settings.service_bus_namespace),
                self._credential,
                **kwargs,
            )

    def send(self, delivery: OutboxDelivery) -> None:
        body = json.dumps(delivery.payload, ensure_ascii=False, separators=(",", ":"))
        message = self._sdk["ServiceBusMessage"](
            body,
            message_id=delivery.delivery_id,
            correlation_id=delivery.work_item_id,
            subject=str(delivery.payload.get("task_type") or "pipeline.work"),
            content_type="application/json",
            application_properties={
                "schema_version": 1,
                "pipeline_job_id": int(delivery.payload.get("pipeline_job_id") or 0),
            },
        )
        with self.client.get_queue_sender(
            queue_name=self.settings.service_bus_queue_name
        ) as sender:
            sender.send_messages(message)

    def receiver(self) -> "ServiceBusReceiverSession":
        return ServiceBusReceiverSession(self)

    def close(self) -> None:
        try:
            self.client.close()
        finally:
            if self._credential is not None:
                self._credential.close()


@dataclass
class BrokerDelivery:
    message: Any
    envelope: dict[str, Any]


class ServiceBusReceiverSession(AbstractContextManager):
    def __init__(self, transport: ServiceBusTransport):
        self.transport = transport
        self._receiver_context = None
        self.receiver_client = None
        self._renewer = None

    def __enter__(self):
        self._receiver_context = self.transport.client.get_queue_receiver(
            queue_name=self.transport.settings.service_bus_queue_name,
            max_wait_time=max(1, int(self.transport.settings.poll_seconds)),
            prefetch_count=0,
        )
        self.receiver_client = self._receiver_context.__enter__()
        self._renewer = self.transport._sdk["AutoLockRenewer"](
            max_lock_renewal_duration=self.transport.settings.service_bus_lock_renewal_seconds,
            max_workers=2,
        )
        return self

    def receive_one(self) -> BrokerDelivery | None:
        messages = self.receiver_client.receive_messages(
            max_message_count=1,
            max_wait_time=max(1, int(self.transport.settings.poll_seconds)),
        )
        if not messages:
            return None
        message = messages[0]
        self._renewer.register(
            self.receiver_client,
            message,
            max_lock_renewal_duration=self.transport.settings.service_bus_lock_renewal_seconds,
        )
        try:
            envelope = _decode_body(message)
        except PermanentWorkError as exc:
            self.receiver_client.dead_letter_message(
                message,
                reason="InvalidPipelineMessage",
                error_description=str(exc)[:4000],
            )
            return None
        return BrokerDelivery(message=message, envelope=envelope)

    def complete(self, delivery: BrokerDelivery) -> None:
        self.receiver_client.complete_message(delivery.message)

    def abandon(self, delivery: BrokerDelivery) -> None:
        self.receiver_client.abandon_message(delivery.message)

    def dead_letter(self, delivery: BrokerDelivery, *, reason: str, description: str) -> None:
        self.receiver_client.dead_letter_message(
            delivery.message,
            reason=reason[:128],
            error_description=description[:4000],
        )

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._renewer is not None:
                self._renewer.close()
        finally:
            if self._receiver_context is not None:
                self._receiver_context.__exit__(exc_type, exc, tb)
        return False
