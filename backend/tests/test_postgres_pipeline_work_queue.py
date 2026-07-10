import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

from services.pipeline_queue.contracts import LeaseLostError, WorkItemSpec, WorkStatus
from services.pipeline_queue.repository import WorkItemRepository


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BACKEND_DIR / "database" / "postgres_schema.sql"


class PipelineQueueSchemaContractTest(unittest.TestCase):
    def test_schema_contains_fenced_work_items_outbox_indexes_and_rls(self):
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        for table in ("pipeline_work_items", "pipeline_work_outbox"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", schema)
            self.assertIn(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY", schema)
        for column in (
            "dedupe_key",
            "attempt_count",
            "lease_token",
            "lease_version",
            "lease_expires_at",
            "dead_lettered_at",
        ):
            self.assertRegex(schema, rf"(?m)^\s*{column}\s+")
        self.assertIn("idx_pipeline_work_items_due", schema)
        self.assertIn("uq_pipeline_work_items_active_scope", schema)
        self.assertIn("WHERE status IN ('queued', 'retry_scheduled', 'running')", schema)
        self.assertIn("idx_pipeline_work_outbox_due", schema)


@unittest.skipUnless(
    psycopg is not None
    and os.getenv("POSTGRES_TEST_DATABASE_URL")
    and os.getenv("POSTGRES_TEST_RESET_SCHEMA") == "1",
    "Nécessite un PostgreSQL jetable et POSTGRES_TEST_RESET_SCHEMA=1",
)
class PostgresPipelineWorkQueueTest(unittest.TestCase):
    def setUp(self):
        self.database_url = os.environ["POSTGRES_TEST_DATABASE_URL"]
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("DROP SCHEMA public CASCADE")
                cur.execute("CREATE SCHEMA public")
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(schema)
                cur.execute(
                    """
                    INSERT INTO platform_config (id, name, slug, updated_at)
                    VALUES (7, 'Queue test', 'queue-test', NOW())
                    """
                )
                cur.execute(
                    """
                    INSERT INTO formation_pipeline_jobs
                        (id, platform_id, tp_name, total_hours, nb_days)
                    VALUES (42, 7, 'TP Queue', 7, 1)
                    """
                )
        self.repo = WorkItemRepository(storage_backend="postgres")

    def test_competing_enqueues_return_one_active_scope_item(self):
        self.repo.ensure_schema()

        def enqueue(index):
            return self.repo.enqueue(
                WorkItemSpec(
                    pipeline_job_id=42,
                    run_id=f"pg-concurrent-{index}",
                    task_type="test",
                    dedupe_key=f"pg-concurrent-{index}:test",
                )
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(enqueue, range(16)))

        self.assertEqual(len({item.id for item in results}), 1)
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM pipeline_work_items
                    WHERE pipeline_job_id = 42
                      AND scope_key = 'pipeline'
                      AND status IN ('queued', 'retry_scheduled', 'running')
                    """
                )
                self.assertEqual(cur.fetchone()[0], 1)

    def test_competing_claims_and_fencing_are_atomic(self):
        item = self.repo.enqueue(
            WorkItemSpec(
                pipeline_job_id=42,
                run_id="pg-run",
                task_type="test",
                dedupe_key="pg-run:test",
            )
        )

        def claim(owner):
            return WorkItemRepository(storage_backend="postgres").claim(
                item.id,
                owner=owner,
                lease_seconds=60,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ("worker-a", "worker-b")))
        winners = [result for result in results if result is not None]
        self.assertEqual(len(winners), 1)

        first = winners[0]
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE pipeline_work_items SET lease_expires_at = NOW() - INTERVAL '1 second' WHERE id = %s",
                    (item.id,),
                )
        second = self.repo.claim(item.id, owner="worker-c", lease_seconds=60)
        self.assertIsNotNone(second)
        self.assertGreater(second.lease_version, first.lease_version)

        with self.assertRaises(LeaseLostError):
            self.repo.complete(first.id, first.lease_token)
        self.repo.complete(second.id, second.lease_token, result={"ok": True})
        self.assertEqual(self.repo.get(item.id).status, WorkStatus.COMPLETED.value)

    def test_transactional_outbox_references_persisted_item(self):
        item = self.repo.enqueue(
            WorkItemSpec(
                pipeline_job_id=42,
                run_id="pg-outbox",
                task_type="test",
                dedupe_key="pg-outbox:test",
            ),
            notify=True,
        )
        deliveries = self.repo.claim_due_outbox(owner="dispatcher", lease_seconds=30, limit=10)
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0].work_item_id, item.id)
        self.repo.mark_outbox_published(deliveries[0].id, deliveries[0].lease_token)

        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, published_at IS NOT NULL FROM pipeline_work_outbox WHERE id = %s",
                    (deliveries[0].id,),
                )
                self.assertEqual(cur.fetchone(), ("published", True))


if __name__ == "__main__":
    unittest.main()
