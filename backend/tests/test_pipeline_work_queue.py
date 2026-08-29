import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from services.pipeline_queue.contracts import (
    LeaseLostError,
    PermanentWorkError,
    WorkItemSpec,
    WorkResult,
    WorkStatus,
)
from services.pipeline_queue.outbox import OutboxDispatcher
from services.pipeline_queue.repository import WorkItemRepository
from services.pipeline_queue.routing import AUDIO_TASK_TYPES, AI_TASK_TYPES
from services.pipeline_queue.service import cancel_latest_work_item, get_latest_work_item
from services.pipeline_queue.settings import QueueSettings
from services.pipeline_queue.worker import (
    PipelineWorker,
    RetryPolicy,
    retry_delay_seconds,
)


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
    def test_durable_retry_respects_provider_retry_after(self):
        error = RuntimeError("rate limit")
        error.wait_seconds = 180

        self.assertEqual(
            retry_delay_seconds(
                RetryPolicy((30,), jitter_ratio=0),
                1,
                error,
            ),
            180,
        )

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

    def test_workers_serialize_different_audio_items_for_the_same_folder(self):
        first = self.repo.enqueue(
            WorkItemSpec(
                folder_id=118,
                resource_key="course-session:91:audio:course_01.mp3",
                task_type="scheduled_audio_item",
                scope_key="scheduled_audio:91:course_01.mp3",
                run_id="scheduled-1",
                dedupe_key="scheduled-1:course_01.mp3",
            )
        )
        second = self.repo.enqueue(
            WorkItemSpec(
                folder_id=118,
                resource_key="course-session:91:audio:course_02.mp3",
                task_type="scheduled_audio_item",
                scope_key="scheduled_audio:91:course_02.mp3",
                run_id="scheduled-2",
                dedupe_key="scheduled-2:course_02.mp3",
            )
        )

        claimed_first = self.repo.claim(first.id, owner="audio-a", lease_seconds=60)
        self.assertIsNotNone(claimed_first)
        self.assertIsNone(
            self.repo.claim(second.id, owner="audio-b", lease_seconds=60),
            "Deux workers ne doivent jamais réécrire le même deck en parallèle",
        )

        self.repo.complete(first.id, claimed_first.lease_token, result={"ok": True})
        self.assertIsNotNone(
            self.repo.claim(second.id, owner="audio-b", lease_seconds=60)
        )

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

    def test_complete_serializes_datetime_results_from_voice_calibration(self):
        item = self._enqueue()
        claimed = self.repo.claim(item.id, owner="worker", lease_seconds=60)
        calibrated_at = datetime(2026, 8, 27, 14, 38, 13, tzinfo=timezone.utc)

        self.repo.complete(
            item.id,
            claimed.lease_token,
            result={"voice": {"calibrated_at": calibrated_at}},
        )

        self.assertEqual(
            self.repo.get(item.id).result["voice"]["calibrated_at"],
            "2026-08-27T14:38:13+00:00",
        )

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

    def test_ai_and_audio_workers_only_claim_their_own_task_types(self):
        ai_item = self._enqueue(
            task_type="auto_pilot_tick",
            dedupe_key="run-1:ai",
            scope_key="pipeline",
        )
        audio_item = self.repo.enqueue(
            WorkItemSpec(
                folder_id=118,
                task_type="hr_playlist_item",
                scope_key="hr_audio",
                run_id="run-audio",
                dedupe_key="run-audio:item",
            )
        )
        processed = []

        ai_worker = PipelineWorker(
            self.repo,
            lambda work, _lease: processed.append(work.task_type) or {"ok": True},
            settings=_settings(),
            owner="ai-worker",
            accepted_task_types=AI_TASK_TYPES,
        )
        audio_worker = PipelineWorker(
            self.repo,
            lambda work, _lease: processed.append(work.task_type) or {"ok": True},
            settings=_settings(),
            owner="audio-worker",
            accepted_task_types=AUDIO_TASK_TYPES,
        )

        self.assertEqual(ai_worker.process_next().work_item_id, ai_item.id)
        self.assertEqual(ai_worker.process_next().status, "idle")
        self.assertEqual(audio_worker.process_next().work_item_id, audio_item.id)
        self.assertEqual(processed, ["auto_pilot_tick", "hr_playlist_item"])

    def test_targeted_worker_rejects_a_broker_message_for_another_kind(self):
        audio_item = self.repo.enqueue(
            WorkItemSpec(
                folder_id=118,
                task_type="hr_playlist_generate",
                scope_key="hr_audio",
                run_id="audio-run",
                dedupe_key="audio-run:generate",
            )
        )
        worker = PipelineWorker(
            self.repo,
            lambda _work, _lease: self.fail("handler must not run"),
            settings=_settings(),
            owner="ai-worker",
            accepted_task_types=AI_TASK_TYPES,
        )

        outcome = worker.process_work_item(audio_item.id)

        self.assertEqual(outcome.status, "unsupported")
        self.assertEqual(self.repo.get(audio_item.id).status, WorkStatus.QUEUED.value)

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

    def test_pipeline_scope_is_not_masked_by_a_newer_audio_item(self):
        pipeline_item = self._enqueue()
        audio_item = self.repo.enqueue(
            WorkItemSpec(
                pipeline_job_id=42,
                folder_id=118,
                resource_key="course-session:91:audio:course_01.mp3",
                scope_key="scheduled_audio:91:course_01.mp3",
                run_id="audio-run",
                task_type="scheduled_audio_item",
                dedupe_key="audio-run:course_01.mp3",
            )
        )

        self.assertEqual(get_latest_work_item(42, repository=self.repo).id, audio_item.id)
        self.assertEqual(
            get_latest_work_item(42, scope_key="pipeline", repository=self.repo).id,
            pipeline_item.id,
        )

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

    def test_outbox_reconciliation_backfills_work_queued_before_cutover(self):
        item = self._enqueue()

        created = self.repo.reconcile_outbox_notifications(
            limit=20,
            renotify_after_seconds=600,
        )
        created_again = self.repo.reconcile_outbox_notifications(
            limit=20,
            renotify_after_seconds=600,
        )

        self.assertEqual(created, 1)
        self.assertEqual(created_again, 0)
        deliveries = self.repo.claim_due_outbox(
            owner="dispatcher",
            lease_seconds=60,
            limit=20,
        )
        self.assertEqual([delivery.work_item_id for delivery in deliveries], [item.id])


if __name__ == "__main__":
    unittest.main()
