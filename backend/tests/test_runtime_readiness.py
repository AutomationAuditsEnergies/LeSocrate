import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from services import pipeline_runtime_health as worker_health
from services import runtime_readiness_service as readiness
from services.pipeline_queue.settings import QueueSettings
from services.pipeline_queue.worker import PipelineWorker


class _Task:
    def __init__(self, alive=True):
        self.alive = alive

    def is_alive(self):
        return self.alive


class RuntimeReadinessTest(unittest.TestCase):
    def setUp(self):
        readiness.reset_blob_readiness_cache_for_tests()
        worker_health.reset_embedded_worker_health_for_tests()

    def tearDown(self):
        readiness.reset_blob_readiness_cache_for_tests()
        worker_health.reset_embedded_worker_health_for_tests()

    def test_blob_readiness_performs_authenticated_request(self):
        client = Mock()
        with patch.dict(
            os.environ,
            {
                "PIPELINE_ARTIFACTS_REQUIRED": "1",
                "AZURE_TTS_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true",
            },
            clear=False,
        ), patch(
            "services.azure_blob_service._get_blob_service_client",
            return_value=client,
        ):
            result = readiness.check_blob_storage(force=True)

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["verified"])
        client.get_account_information.assert_called_once_with()

    def test_blob_readiness_rejects_invalid_credentials(self):
        client = Mock()
        client.get_account_information.side_effect = RuntimeError("AuthenticationFailed")
        with patch.dict(
            os.environ,
            {
                "PIPELINE_ARTIFACTS_REQUIRED": "1",
                "AZURE_TTS_STORAGE_CONNECTION_STRING": "invalid",
            },
            clear=False,
        ), patch(
            "services.azure_blob_service._get_blob_service_client",
            return_value=client,
        ):
            with self.assertRaises(readiness.ReadinessCheckError) as raised:
                readiness.check_blob_storage(force=True)

        self.assertEqual(raised.exception.check, "blob")

    def test_embedded_worker_readiness_rejects_dead_task(self):
        with patch.dict(
            os.environ,
            {
                "PIPELINE_EXECUTION_MODE": "queue",
                "PIPELINE_EMBEDDED_WORKER": "1",
            },
            clear=False,
        ):
            worker_health.register_embedded_worker_task(_Task(alive=False))
            worker_health.mark_embedded_worker_started("worker-test")
            with self.assertRaises(readiness.ReadinessCheckError) as raised:
                readiness.check_embedded_worker()

        self.assertEqual(raised.exception.check, "worker")

    def test_embedded_worker_readiness_rejects_stale_heartbeat(self):
        with patch.dict(
            os.environ,
            {
                "PIPELINE_EXECUTION_MODE": "queue",
                "PIPELINE_EMBEDDED_WORKER": "1",
                "PIPELINE_WORKER_READY_STALE_SECONDS": "15",
            },
            clear=False,
        ), patch.object(worker_health.time, "monotonic", return_value=10.0):
            worker_health.register_embedded_worker_task(_Task())
            worker_health.mark_embedded_worker_started("worker-test")

        with patch.dict(
            os.environ,
            {
                "PIPELINE_EXECUTION_MODE": "queue",
                "PIPELINE_EMBEDDED_WORKER": "1",
                "PIPELINE_WORKER_READY_STALE_SECONDS": "15",
            },
            clear=False,
        ), patch.object(worker_health.time, "monotonic", return_value=30.0):
            with self.assertRaises(readiness.ReadinessCheckError) as raised:
                readiness.check_embedded_worker()

        self.assertEqual(raised.exception.check, "worker")

    def test_queue_readiness_rejects_old_actionable_work_without_active_lease(self):
        now = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
        repository = Mock()
        repository.readiness_snapshot.return_value = {
            "due_count": 1,
            "oldest_due_at": now - timedelta(minutes=20),
            "active_running_count": 0,
            "expired_running_count": 0,
            "oldest_expired_lease_at": None,
        }
        with patch.dict(
            os.environ,
            {
                "PIPELINE_EXECUTION_MODE": "queue",
                "PIPELINE_READY_QUEUE_STALL_SECONDS": "600",
            },
            clear=False,
        ):
            with self.assertRaises(readiness.ReadinessCheckError) as raised:
                readiness.check_pipeline_queue(
                    repository_factory=lambda: repository,
                    now=now,
                )

        self.assertEqual(raised.exception.check, "queue")

    def test_queue_readiness_accepts_backlog_while_a_lease_is_active(self):
        now = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
        repository = Mock()
        repository.readiness_snapshot.return_value = {
            "due_count": 2,
            "oldest_due_at": now - timedelta(minutes=20),
            "active_running_count": 1,
            "expired_running_count": 0,
            "oldest_expired_lease_at": None,
        }
        with patch.dict(
            os.environ,
            {"PIPELINE_EXECUTION_MODE": "queue"},
            clear=False,
        ):
            result = readiness.check_pipeline_queue(
                repository_factory=lambda: repository,
                now=now,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["active_running_count"], 1)

    def test_worker_loop_reports_health_while_idle(self):
        repository = Mock()
        repository.claim_next.return_value = None
        repository.dead_letter_one_exhausted.return_value = None
        heartbeats = []
        worker = PipelineWorker(
            repository,
            Mock(),
            settings=QueueSettings(
                backend="database",
                lease_seconds=60,
                heartbeat_seconds=10,
                poll_seconds=0.05,
                outbox_batch_size=20,
                service_bus_connection_string="",
                service_bus_namespace="",
                service_bus_queue_name="formation-pipeline",
                service_bus_websockets=False,
                service_bus_lock_renewal_seconds=3600,
            ),
            health_callback=lambda: heartbeats.append(True),
        )

        outcome = worker.process_next()

        self.assertEqual(outcome.status, "idle")
        self.assertTrue(heartbeats)


if __name__ == "__main__":
    unittest.main()
