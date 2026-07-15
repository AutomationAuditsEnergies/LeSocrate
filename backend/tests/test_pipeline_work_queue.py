import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from services.pipeline_queue.contracts import (
    LeaseLostError,
    PermanentWorkError,
    WorkItemSpec,
    WorkResult,
    WorkStatus,
)
from services.pipeline_queue.outbox import OutboxDispatcher
from services.pipeline_queue.repository import WorkItemRepository
from services.pipeline_queue.service import cancel_latest_work_item, get_latest_work_item
from services.pipeline_queue.settings import QueueSettings
from services.pipeline_queue.worker import PipelineWorker, RetryPolicy


def _settings(backend="database"):
    return QueueSettings(
        backend=backend,
        lease_seconds=60,
        heartbeat_seconds=10,
        poll_seconds=0.05,
        outbox_batch_size=20,
        service_bus_connection_string="fake" if backend == "service_bus" else "",
        service_bus_namespace="",
        service_bus_queue_name="formation-pipeline",
        service_bus_websockets=False,
        service_bus_lock_renewal_seconds=3600,
    )


class PipelineWorkQueueTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(prefix="pipeline-work-", suffix=".db")
        os.close(fd)
        self.repo = WorkItemRepository(
            storage_backend="sqlite",
            sqlite_connection_factory=lambda: sqlite3.connect(self.db_path, timeout=5),
        )

    def tearDown(self):
        try:
            os.unlink(self.db_path)
        except FileNotFoundError:
            pass

    def _enqueue(self, **overrides):
        values = {
            "pipeline_job_id": 42,
            "task_type": "test",
            "dedupe_key": "run-1:test",
            "run_id": "run-1",
            "max_attempts": 3,
        }
        values.update(overrides)
        return self.repo.enqueue(WorkItemSpec(**values))

    def test_enqueue_is_idempotent_with_stable_dedupe_key(self):
        first = self._enqueue(payload={"value": 1})
        second = self._enqueue(payload={"value": 999})

        self.assertEqual(first.id, second.id)
        self.assertEqual(second.payload, {"value": 1})
        self.assertEqual(second.status, WorkStatus.QUEUED.value)

    def test_enqueue_returns_active_scope_item_across_run_and_dedupe_keys(self):
        first = self._enqueue(payload={"value": 1})
        second = self._enqueue(
            run_id="run-2",
            dedupe_key="run-2:different",
            payload={"value": 2},
        )

        self.assertEqual(second.id, first.id)
        self.assertEqual(second.run_id, "run-1")
        self.assertEqual(second.payload, {"value": 1})

        conn = sqlite3.connect(self.db_path)
        active_count = conn.execute(
            """
            SELECT COUNT(*) FROM pipeline_work_items
            WHERE pipeline_job_id = 42 AND scope_key = 'pipeline'
              AND status IN ('queued', 'retry_scheduled', 'running')
            """
        ).fetchone()[0]
        conn.close()
        self.assertEqual(active_count, 1)

    def test_concurrent_sqlite_enqueues_share_one_active_scope_item(self):
        def enqueue(index):
            return self._enqueue(
                run_id=f"concurrent-{index}",
                dedupe_key=f"concurrent-{index}:test",
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            items = list(pool.map(enqueue, range(16)))

        self.assertEqual(len({item.id for item in items}), 1)

    def test_different_scope_keys_can_be_active_for_the_same_job(self):
        pipeline_item = self._enqueue()
        audio_item = self._enqueue(
            run_id="audio-run",
            dedupe_key="audio-run:test",
            scope_key="audio:session-1",
        )

        self.assertNotEqual(audio_item.id, pipeline_item.id)
        self.assertEqual(audio_item.scope_key, "audio:session-1")

    def test_folder_resource_without_pipeline_job_is_durable_and_deduplicated(self):
        first = self.repo.enqueue(
            WorkItemSpec(
                folder_id=118,
                task_type="hr_playlist_generate",
                scope_key="hr_audio",
                run_id="folder-run-1",
                dedupe_key="folder:118:audio:run-1",
            )
        )
        second = self.repo.enqueue(
            WorkItemSpec(
                folder_id=118,
                task_type="hr_playlist_item",
                scope_key="hr_audio",
                run_id="folder-run-2",
                dedupe_key="folder:118:audio:run-2",
            )
        )

        self.assertEqual(first.id, second.id)
        self.assertIsNone(first.pipeline_job_id)
        self.assertEqual(first.folder_id, 118)
        self.assertEqual(first.resource_key, "folder:118")
        self.assertEqual(
            self.repo.latest_for_folder(118, scope_key="hr_audio").id,
            first.id,
        )

    def test_progress_is_persisted_and_fenced(self):
        item = self._enqueue()
        claimed = self.repo.claim(item.id, owner="worker", lease_seconds=60)
        self.repo.update_progress(
            item.id,
            claimed.lease_token,
            {"status": "running", "step": 7, "message": "TTS"},
        )
        self.assertEqual(self.repo.get(item.id).result["step"], 7)

        with self.assertRaises(LeaseLostError):
            self.repo.update_progress(
                item.id,
                "stale-token",
                {"status": "running", "step": 8},
            )

    def test_readiness_snapshot_distinguishes_due_active_and_expired_work(self):
        item = self._enqueue()
        due = self.repo.readiness_snapshot()
        self.assertEqual(due["due_count"], 1)
        self.assertEqual(due["active_running_count"], 0)

        claimed = self.repo.claim(item.id, owner="worker", lease_seconds=60)
        self.assertIsNotNone(claimed)
        active = self.repo.readiness_snapshot()
        self.assertEqual(active["due_count"], 0)
        self.assertEqual(active["active_running_count"], 1)

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE pipeline_work_items SET lease_expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (item.id,),
        )
        conn.commit()
        conn.close()

        expired = self.repo.readiness_snapshot()
        self.assertEqual(expired["active_running_count"], 0)
        self.assertEqual(expired["expired_running_count"], 1)
        self.assertIsNotNone(expired["oldest_expired_lease_at"])

    def test_stale_owner_cannot_complete_new_fenced_lease(self):
        item = self._enqueue()
        first = self.repo.claim(item.id, owner="worker-a", lease_seconds=60)
        self.assertIsNotNone(first)

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE pipeline_work_items SET lease_expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (item.id,),
        )
        conn.commit()
        conn.close()

        second = self.repo.claim(item.id, owner="worker-b", lease_seconds=60)
        self.assertIsNotNone(second)
        self.assertNotEqual(first.lease_token, second.lease_token)
        self.assertEqual(second.lease_version, first.lease_version + 1)

        with self.assertRaises(LeaseLostError):
            self.repo.complete(first.id, first.lease_token, result={"owner": "old"})

        self.repo.complete(second.id, second.lease_token, result={"owner": "new"})
        completed = self.repo.get(item.id)
        self.assertEqual(completed.status, WorkStatus.COMPLETED.value)
        self.assertEqual(completed.result, {"owner": "new"})

    def test_complete_and_enqueue_next_is_atomic_and_deduplicated(self):
        item = self._enqueue()
        claimed = self.repo.claim(item.id, owner="worker", lease_seconds=60)
        next_spec = WorkItemSpec(
            pipeline_job_id=42,
            run_id="run-1",
            task_type="next",
            dedupe_key="run-1:next",
        )

        created = self.repo.complete(
            item.id,
            claimed.lease_token,
            result={"step": "test"},
            next_items=(next_spec, next_spec),
        )

        self.assertEqual(created[0].id, created[1].id)
        self.assertEqual(self.repo.get(item.id).status, WorkStatus.COMPLETED.value)
        self.assertEqual(self.repo.latest_for_job(42).task_type, "next")

    def test_worker_retries_then_completes_without_duplicate_side_effect(self):
        item = self._enqueue()
        calls = []

        def handler(work, _lease):
            calls.append(work.attempt_count)
            if work.attempt_count == 1:
                raise RuntimeError("provider timeout")
            return {"ok": True}

        worker = PipelineWorker(
            self.repo,
            handler,
            settings=_settings(),
            owner="worker",
            retry_policy=RetryPolicy((0,), jitter_ratio=0),
        )
        first = worker.process_next()
        second = worker.process_next()

        self.assertEqual(first.status, WorkStatus.RETRY_SCHEDULED.value)
        self.assertEqual(second.status, WorkStatus.COMPLETED.value)
        self.assertEqual(calls, [1, 2])
        self.assertEqual(self.repo.get(item.id).attempt_count, 2)

    def test_permanent_error_is_dead_lettered_immediately(self):
        item = self._enqueue(max_attempts=10)

        def handler(_work, _lease):
            raise PermanentWorkError("payload invalide")

        worker = PipelineWorker(
            self.repo,
            handler,
            settings=_settings(),
            owner="worker",
            retry_policy=RetryPolicy((0,), jitter_ratio=0),
        )
        outcome = worker.process_next()

        self.assertEqual(outcome.status, WorkStatus.DEAD_LETTERED.value)
        persisted = self.repo.get(item.id)
        self.assertEqual(persisted.status, WorkStatus.DEAD_LETTERED.value)
        self.assertIn("payload invalide", persisted.last_error)

    def test_retry_budget_moves_task_to_dead_letter(self):
        item = self._enqueue(max_attempts=2)

        def handler(_work, _lease):
            raise RuntimeError("toujours indisponible")

        worker = PipelineWorker(
            self.repo,
            handler,
            settings=_settings(),
            owner="worker",
            retry_policy=RetryPolicy((0,), jitter_ratio=0),
        )
        self.assertEqual(worker.process_next().status, WorkStatus.RETRY_SCHEDULED.value)
        self.assertEqual(worker.process_next().status, WorkStatus.DEAD_LETTERED.value)
        self.assertEqual(self.repo.get(item.id).attempt_count, 2)

    def test_crashed_final_attempt_is_reconciled_without_broker_message(self):
        item = self._enqueue(max_attempts=1)
        claimed = self.repo.claim(item.id, owner="crashed-worker", lease_seconds=60)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE pipeline_work_items SET lease_expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (claimed.id,),
        )
        conn.commit()
        conn.close()

        worker = PipelineWorker(
            self.repo,
            lambda _work, _lease: {"unexpected": True},
            settings=_settings(),
            owner="reconciler",
        )
        outcome = worker.process_next()

        self.assertEqual(outcome.status, WorkStatus.DEAD_LETTERED.value)
        self.assertEqual(self.repo.get(item.id).status, WorkStatus.DEAD_LETTERED.value)

    def test_cancel_invalidates_running_lease(self):
        item = self._enqueue()
        claimed = self.repo.claim(item.id, owner="worker", lease_seconds=60)

        self.assertTrue(self.repo.cancel(item.id))
        with self.assertRaises(LeaseLostError):
            self.repo.complete(item.id, claimed.lease_token)
        self.assertEqual(self.repo.get(item.id).status, WorkStatus.CANCELLED.value)

    def test_service_can_find_and_cancel_latest_job_item(self):
        first = self._enqueue()
        second = self.repo.enqueue(
            WorkItemSpec(
                pipeline_job_id=42,
                run_id="run-2",
                task_type="test",
                dedupe_key="run-2:test",
            )
        )

        self.assertEqual(second.id, first.id)
        self.assertEqual(get_latest_work_item(42, repository=self.repo).id, first.id)
        cancelled = cancel_latest_work_item(42, repository=self.repo)
        self.assertEqual(cancelled.id, first.id)
        self.assertEqual(cancelled.status, WorkStatus.CANCELLED.value)
        self.assertEqual(self.repo.get(first.id).status, WorkStatus.CANCELLED.value)

        replacement = self.repo.enqueue(
            WorkItemSpec(
                pipeline_job_id=42,
                run_id="run-3",
                task_type="test",
                dedupe_key="run-3:test",
            )
        )
        self.assertNotEqual(replacement.id, first.id)

    def test_outbox_publishes_once_and_keeps_database_authoritative(self):
        item = self.repo.enqueue(
            WorkItemSpec(
                pipeline_job_id=42,
                task_type="test",
                run_id="run-service-bus",
                dedupe_key="run-service-bus:test",
            ),
            notify=True,
        )

        class FakeTransport:
            def __init__(self):
                self.deliveries = []

            def send(self, delivery):
                self.deliveries.append(delivery)

        transport = FakeTransport()
        dispatcher = OutboxDispatcher(self.repo, transport, owner="dispatcher")

        self.assertEqual(dispatcher.dispatch_once(limit=10), 1)
        self.assertEqual(dispatcher.dispatch_once(limit=10), 0)
        self.assertEqual(len(transport.deliveries), 1)
        self.assertEqual(transport.deliveries[0].work_item_id, item.id)

        # Broker publication does not claim or mutate the actual task.
        self.assertEqual(self.repo.get(item.id).status, WorkStatus.QUEUED.value)

    def test_outbox_send_failure_is_retained_for_retry(self):
        self.repo.enqueue(
            WorkItemSpec(
                pipeline_job_id=42,
                task_type="test",
                run_id="run-outage",
                dedupe_key="run-outage:test",
            ),
            notify=True,
        )

        class FailingTransport:
            def send(self, _delivery):
                raise OSError("service bus indisponible")

        dispatcher = OutboxDispatcher(self.repo, FailingTransport(), owner="dispatcher")
        self.assertEqual(dispatcher.dispatch_once(limit=10), 0)

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT status, publish_attempts, last_error FROM pipeline_work_outbox"
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], "pending")
        self.assertEqual(row[1], 1)
        self.assertIn("indisponible", row[2])


if __name__ == "__main__":
    unittest.main()
