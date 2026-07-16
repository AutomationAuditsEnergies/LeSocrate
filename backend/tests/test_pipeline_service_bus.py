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

        self.assertEqual(client.queue_name, "formation-pipeline")
        self.assertEqual(len(client.sender.messages), 1)
        message = client.sender.messages[0]
        self.assertEqual(message.properties["message_id"], "stable-delivery-id")
        self.assertEqual(message.properties["correlation_id"], "work-id")

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
