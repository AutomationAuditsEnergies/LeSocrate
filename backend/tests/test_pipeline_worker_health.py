import unittest
from unittest.mock import Mock, patch

from services.pipeline_queue.worker import PipelineWorker
from services.pipeline_worker_health import (
    configure_pipeline_worker_health,
    get_pipeline_worker_health,
    mark_pipeline_worker_crashed,
    mark_pipeline_worker_started,
    record_pipeline_worker_heartbeat,
)


class PipelineWorkerHealthTest(unittest.TestCase):
    def tearDown(self):
        configure_pipeline_worker_health(enabled=False)

    def test_required_worker_is_unhealthy_until_it_heartbeats(self):
        configure_pipeline_worker_health(enabled=True, stale_after_seconds=30)
        self.assertFalse(get_pipeline_worker_health()["healthy"])

        mark_pipeline_worker_started("worker-test")
        healthy = get_pipeline_worker_health()
        self.assertTrue(healthy["healthy"])
        self.assertEqual(healthy["status"], "healthy")

    def test_stale_or_crashed_worker_is_not_reported_healthy(self):
        with patch("services.pipeline_worker_health.time.monotonic", return_value=100.0):
            configure_pipeline_worker_health(enabled=True, stale_after_seconds=30)
            mark_pipeline_worker_started("worker-test")
            record_pipeline_worker_heartbeat("working", "work-1")
        stale = get_pipeline_worker_health(now_monotonic=131.0)
        self.assertFalse(stale["healthy"])
        self.assertEqual(stale["status"], "stale")

        mark_pipeline_worker_crashed("database unavailable")
        crashed = get_pipeline_worker_health()
        self.assertFalse(crashed["healthy"])
        self.assertEqual(crashed["status"], "crashed")

    def test_worker_runtime_reports_polling_heartbeats(self):
        callback = Mock()
        repository = Mock()
        repository.claim_next.return_value = None
        repository.dead_letter_one_exhausted.return_value = None
        worker = PipelineWorker(repository, Mock(), health_callback=callback)

        outcome = worker.process_next()
        worker._report_health("polling")

        self.assertEqual(outcome.status, "idle")
        repository.claim_next.assert_called_once_with(
            owner=worker.owner,
            lease_seconds=worker.settings.lease_seconds,
            task_types=None,
        )
        repository.dead_letter_one_exhausted.assert_called_once_with(task_types=None)
        callback.assert_called_with("polling", None)


if __name__ == "__main__":
    unittest.main()
