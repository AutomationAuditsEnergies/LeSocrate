import unittest
from unittest.mock import patch

from services.pipeline_queue.contracts import OutboxDelivery
from services.pipeline_queue.service_bus import ServiceBusTransport, _fully_qualified_namespace
from services.pipeline_queue.settings import QueueSettings


class _FakeMessage:
    def __init__(self, body, **kwargs):
        self.body = body
        self.properties = kwargs


class _FakeSender:
    def __init__(self):
        self.messages = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def send_messages(self, message):
        self.messages.append(message)


class _FakeClient:
    def __init__(self):
        self.sender = _FakeSender()
        self.queue_name = None

    def get_queue_sender(self, *, queue_name):
        self.queue_name = queue_name
        return self.sender

    def close(self):
        pass


class _FakeTransportType:
    AmqpOverWebsocket = object()


class _FakeClientFactory:
    connection_string = None
    kwargs = None

    @classmethod
    def from_connection_string(cls, connection_string, **kwargs):
        cls.connection_string = connection_string
        cls.kwargs = kwargs
        return _FakeClient()


class PipelineServiceBusTest(unittest.TestCase):
    def _settings(self):
        return QueueSettings(
            backend="service_bus",
            lease_seconds=300,
            heartbeat_seconds=60,
            poll_seconds=1,
            outbox_batch_size=20,
            service_bus_connection_string="fake",
            service_bus_namespace="",
            service_bus_queue_name="formation-pipeline",
            service_bus_websockets=False,
            service_bus_lock_renewal_seconds=3600,
            service_bus_ai_queue_name="formation-ai",
            service_bus_audio_queue_name="formation-audio",
        )

    def test_sender_uses_delivery_id_for_broker_deduplication(self):
        client = _FakeClient()
        transport = ServiceBusTransport(
            self._settings(),
            client=client,
            sdk={"ServiceBusMessage": _FakeMessage},
        )
        delivery = OutboxDelivery(
            id="outbox-id",
            delivery_id="stable-delivery-id",
            work_item_id="work-id",
            payload={
                "version": 1,
                "work_item_id": "work-id",
                "pipeline_job_id": 42,
                "task_type": "auto_pilot_tick",
            },
            available_at=None,
            publish_attempts=1,
            lease_token="lease",
        )

        transport.send(delivery)

        self.assertEqual(client.queue_name, "formation-ai")
        self.assertEqual(len(client.sender.messages), 1)
        message = client.sender.messages[0]
        self.assertEqual(message.properties["message_id"], "stable-delivery-id")
        self.assertEqual(message.properties["correlation_id"], "work-id")

    def test_sender_routes_audio_work_to_the_audio_queue(self):
        client = _FakeClient()
        transport = ServiceBusTransport(
            self._settings(),
            client=client,
            sdk={"ServiceBusMessage": _FakeMessage},
        )
        delivery = OutboxDelivery(
            id="outbox-audio",
            delivery_id="delivery-audio",
            work_item_id="work-audio",
            payload={
                "version": 1,
                "work_item_id": "work-audio",
                "pipeline_job_id": 0,
                "task_type": "hr_playlist_item",
            },
            available_at=None,
            publish_attempts=1,
            lease_token="lease",
        )

        transport.send(delivery)

        self.assertEqual(client.queue_name, "formation-audio")

    def test_sender_routes_scheduled_audio_repair_to_the_audio_queue(self):
        client = _FakeClient()
        transport = ServiceBusTransport(
            self._settings(),
            client=client,
            sdk={"ServiceBusMessage": _FakeMessage},
        )
        delivery = OutboxDelivery(
            id="outbox-scheduled-audio",
            delivery_id="delivery-scheduled-audio",
            work_item_id="work-scheduled-audio",
            payload={
                "version": 1,
                "work_item_id": "work-scheduled-audio",
                "pipeline_job_id": 8,
                "task_type": "scheduled_audio_item",
            },
            available_at=None,
            publish_attempts=1,
            lease_token="lease",
        )

        transport.send(delivery)

        self.assertEqual(client.queue_name, "formation-audio")

    def test_worker_kind_selects_its_receiver_queue(self):
        settings = self._settings()
        ai = QueueSettings(**{**settings.__dict__, "worker_kind": "ai"})
        audio = QueueSettings(**{**settings.__dict__, "worker_kind": "audio"})

        self.assertEqual(ai.receiver_queue_name, "formation-ai")
        self.assertEqual(audio.receiver_queue_name, "formation-audio")
        self.assertEqual(settings.receiver_queue_name, "formation-pipeline")

    def test_websocket_transport_uses_current_sdk_transport_type(self):
        settings = QueueSettings(
            **{
                **self._settings().__dict__,
                "service_bus_websockets": True,
            }
        )
        transport = ServiceBusTransport(
            settings,
            sdk={
                "ServiceBusClient": _FakeClientFactory,
                "TransportType": _FakeTransportType,
            },
        )

        self.assertEqual(_FakeClientFactory.connection_string, "fake")
        self.assertIs(
            _FakeClientFactory.kwargs["transport_type"],
            _FakeTransportType.AmqpOverWebsocket,
        )
        transport.close()

    def test_split_queues_default_to_legacy_queue_for_backward_compatibility(self):
        with patch.dict(
            "os.environ",
            {
                "PIPELINE_QUEUE_BACKEND": "service_bus",
                "AZURE_SERVICE_BUS_NAMESPACE": "socrate",
                "PIPELINE_SERVICE_BUS_QUEUE": "legacy",
                "PIPELINE_WORKER_KIND": "audio",
            },
            clear=True,
        ):
            settings = QueueSettings.from_env()

        self.assertEqual(settings.service_bus_ai_queue_name, "legacy")
        self.assertEqual(settings.service_bus_audio_queue_name, "legacy")
        self.assertEqual(settings.receiver_queue_name, "legacy")

    def test_namespace_short_name_is_normalized(self):
        self.assertEqual(
            _fully_qualified_namespace("socrate-prod"),
            "socrate-prod.servicebus.windows.net",
        )
        self.assertEqual(
            _fully_qualified_namespace("sb://socrate.servicebus.windows.net/"),
            "socrate.servicebus.windows.net",
        )

    def test_database_backend_is_the_no_infrastructure_default(self):
        with patch.dict("os.environ", {}, clear=True):
            settings = QueueSettings.from_env()
        self.assertEqual(settings.backend, "database")
        self.assertFalse(settings.uses_service_bus)

    def test_service_bus_backend_fails_fast_without_credentials_or_namespace(self):
        with patch.dict("os.environ", {"PIPELINE_QUEUE_BACKEND": "service_bus"}, clear=True):
            with self.assertRaisesRegex(ValueError, "Service Bus activé"):
                QueueSettings.from_env()


if __name__ == "__main__":
    unittest.main()
