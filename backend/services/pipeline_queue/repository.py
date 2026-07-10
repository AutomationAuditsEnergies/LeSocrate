"""Durable work-item and transactional-outbox repository.

PostgreSQL is the production implementation.  SQLite implements the same
contract for local development and deterministic tests.  Both use a lease
token as a fencing token: renew/complete/retry operations from an old worker
cannot mutate a lease acquired by a newer worker.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import threading
import uuid
from typing import Any, Callable, Iterable, Mapping

from database.db import get_db_connection
from database.postgres import get_postgres_connection
from utils.logger import get_logger

from .contracts import (
    LeaseLostError,
    OutboxDelivery,
    TERMINAL_STATUSES,
    WorkItem,
    WorkItemSpec,
    WorkStatus,
    utcnow,
)


logger = get_logger(__name__)


_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_work_items (
    id TEXT PRIMARY KEY,
    pipeline_job_id INTEGER,
    folder_id INTEGER,
    resource_key TEXT NOT NULL,
    run_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    scope_key TEXT NOT NULL DEFAULT 'pipeline',
    dedupe_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    available_at TEXT NOT NULL,
    lease_owner TEXT,
    lease_token TEXT,
    lease_version INTEGER NOT NULL DEFAULT 0,
    lease_expires_at TEXT,
    last_error TEXT,
    result_json TEXT NOT NULL DEFAULT '{}',
    first_started_at TEXT,
    completed_at TEXT,
    dead_lettered_at TEXT,
    cancelled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pipeline_work_items_due
    ON pipeline_work_items(status, available_at, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_pipeline_work_items_job
    ON pipeline_work_items(pipeline_job_id, created_at);
CREATE INDEX IF NOT EXISTS idx_pipeline_work_items_folder
    ON pipeline_work_items(folder_id, created_at);

-- Reconcile rows created before the active-scope invariant existed.  Prefer
-- work already running, then a scheduled retry, then the oldest queued item.
WITH ranked_active AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY pipeline_job_id, scope_key
               ORDER BY CASE status
                            WHEN 'running' THEN 0
                            WHEN 'retry_scheduled' THEN 1
                            ELSE 2
                        END,
                        created_at,
                        id
           ) AS active_rank
    FROM pipeline_work_items
    WHERE status IN ('queued', 'retry_scheduled', 'running')
)
UPDATE pipeline_work_items
SET status = 'cancelled',
    cancelled_at = COALESCE(cancelled_at, CURRENT_TIMESTAMP),
    updated_at = CURRENT_TIMESTAMP,
    lease_owner = NULL,
    lease_token = NULL,
    lease_expires_at = NULL,
    last_error = COALESCE(
        last_error,
        'Superseded while enforcing one active pipeline item per scope'
    )
WHERE id IN (
    SELECT id FROM ranked_active WHERE active_rank > 1
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_pipeline_work_items_active_scope
    ON pipeline_work_items(pipeline_job_id, scope_key)
    WHERE status IN ('queued', 'retry_scheduled', 'running');
CREATE UNIQUE INDEX IF NOT EXISTS uq_pipeline_work_items_active_resource_scope
    ON pipeline_work_items(resource_key, scope_key)
    WHERE status IN ('queued', 'retry_scheduled', 'running');

CREATE TABLE IF NOT EXISTS pipeline_work_outbox (
    id TEXT PRIMARY KEY,
    delivery_id TEXT NOT NULL UNIQUE,
    work_item_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    available_at TEXT NOT NULL,
    publish_attempts INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at TEXT,
    last_error TEXT,
    published_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (work_item_id) REFERENCES pipeline_work_items(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_pipeline_work_outbox_due
    ON pipeline_work_outbox(status, available_at, created_at);
"""


_POSTGRES_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS pipeline_work_items (
        id UUID PRIMARY KEY,
        pipeline_job_id BIGINT REFERENCES formation_pipeline_jobs(id) ON DELETE CASCADE,
        folder_id BIGINT REFERENCES cours_folders(id) ON DELETE CASCADE,
        resource_key TEXT NOT NULL,
        run_id TEXT NOT NULL,
        task_type TEXT NOT NULL,
        scope_key TEXT NOT NULL DEFAULT 'pipeline',
        dedupe_key TEXT NOT NULL UNIQUE,
        payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        status TEXT NOT NULL DEFAULT 'queued',
        priority INTEGER NOT NULL DEFAULT 0,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 5,
        available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        lease_owner TEXT,
        lease_token UUID,
        lease_version BIGINT NOT NULL DEFAULT 0,
        lease_expires_at TIMESTAMPTZ,
        last_error TEXT,
        result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        first_started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        dead_lettered_at TIMESTAMPTZ,
        cancelled_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_pipeline_work_items_due
    ON pipeline_work_items(status, available_at, priority DESC, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_pipeline_work_items_job
    ON pipeline_work_items(pipeline_job_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_pipeline_work_items_folder
    ON pipeline_work_items(folder_id, created_at)
    """,
    """
    WITH ranked_active AS (
        SELECT id,
               ROW_NUMBER() OVER (
                   PARTITION BY pipeline_job_id, scope_key
                   ORDER BY CASE status
                                WHEN 'running' THEN 0
                                WHEN 'retry_scheduled' THEN 1
                                ELSE 2
                            END,
                            created_at,
                            id
               ) AS active_rank
        FROM pipeline_work_items
        WHERE status IN ('queued', 'retry_scheduled', 'running')
    )
    UPDATE pipeline_work_items AS item
    SET status = 'cancelled',
        cancelled_at = COALESCE(item.cancelled_at, NOW()),
        updated_at = NOW(),
        lease_owner = NULL,
        lease_token = NULL,
        lease_expires_at = NULL,
        last_error = COALESCE(
            item.last_error,
            'Superseded while enforcing one active pipeline item per scope'
        )
    FROM ranked_active
    WHERE item.id = ranked_active.id
      AND ranked_active.active_rank > 1
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_pipeline_work_items_active_scope
    ON pipeline_work_items(pipeline_job_id, scope_key)
    WHERE status IN ('queued', 'retry_scheduled', 'running')
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_pipeline_work_items_active_resource_scope
    ON pipeline_work_items(resource_key, scope_key)
    WHERE status IN ('queued', 'retry_scheduled', 'running')
    """,
    """
    CREATE TABLE IF NOT EXISTS pipeline_work_outbox (
        id UUID PRIMARY KEY,
        delivery_id UUID NOT NULL UNIQUE,
        work_item_id UUID NOT NULL REFERENCES pipeline_work_items(id) ON DELETE CASCADE,
        payload_json JSONB NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        publish_attempts INTEGER NOT NULL DEFAULT 0,
        lease_owner TEXT,
        lease_token UUID,
        lease_expires_at TIMESTAMPTZ,
        last_error TEXT,
        published_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_pipeline_work_outbox_due
    ON pipeline_work_outbox(status, available_at, created_at)
    """,
    "ALTER TABLE pipeline_work_items ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE pipeline_work_outbox ENABLE ROW LEVEL SECURITY",
)


def _storage_backend_from_env() -> str:
    # Import lazily so tests can patch the environment before constructing the
    # repository without reloading config.py.
    import os

    value = (os.getenv("PIPELINE_DATABASE_BACKEND") or "sqlite").strip().lower()
    return "postgres" if value in {"postgres", "postgresql", "supabase"} else "sqlite"


def _json(value: Mapping[str, Any] | None) -> str:
    return json.dumps(dict(value or {}), ensure_ascii=False, separators=(",", ":"))


def _decode_json(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if value in (None, ""):
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except (TypeError, ValueError):
        return {}


def _sqlite_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _row_dict(row: Any, cursor=None) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    if cursor is None or not cursor.description:
        raise TypeError("Impossible de convertir la ligne SQL sans description")
    return {column[0]: value for column, value in zip(cursor.description, row)}


def _to_work_item(row: Mapping[str, Any]) -> WorkItem:
    return WorkItem(
        id=str(row["id"]),
        pipeline_job_id=(
            int(row["pipeline_job_id"])
            if row.get("pipeline_job_id") is not None
            else None
        ),
        folder_id=int(row["folder_id"]) if row.get("folder_id") is not None else None,
        resource_key=str(row.get("resource_key") or ""),
        run_id=str(row["run_id"]),
        task_type=str(row["task_type"]),
        scope_key=str(row.get("scope_key") or "pipeline"),
        dedupe_key=str(row["dedupe_key"]),
        payload=_decode_json(row.get("payload_json")),
        status=str(row["status"]),
        priority=int(row.get("priority") or 0),
        attempt_count=int(row.get("attempt_count") or 0),
        max_attempts=int(row.get("max_attempts") or 1),
        available_at=row.get("available_at"),
        lease_owner=row.get("lease_owner"),
        lease_token=str(row["lease_token"]) if row.get("lease_token") else None,
        lease_version=int(row.get("lease_version") or 0),
        lease_expires_at=row.get("lease_expires_at"),
        last_error=row.get("last_error"),
        result=_decode_json(row.get("result_json")),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


class WorkItemRepository:
    def __init__(
        self,
        *,
        storage_backend: str | None = None,
        sqlite_connection_factory: Callable[[], Any] | None = None,
        postgres_connection_factory: Callable[[], Any] | None = None,
    ):
        self.storage_backend = storage_backend or _storage_backend_from_env()
        if self.storage_backend not in {"sqlite", "postgres"}:
            raise ValueError("storage_backend doit être sqlite ou postgres")
        self._sqlite_connection_factory = sqlite_connection_factory or get_db_connection
        self._postgres_connection_factory = postgres_connection_factory or get_postgres_connection
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    @property
    def is_postgres(self) -> bool:
        return self.storage_backend == "postgres"

    @contextmanager
    def _connection(self, *, immediate: bool = False):
        if self.is_postgres:
            with self._postgres_connection_factory() as conn:
                yield conn
            return

        conn = self._sqlite_connection_factory()
        try:
            conn.row_factory = sqlite3.Row
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._connection() as conn:
                if self.is_postgres:
                    with conn.cursor() as cur:
                        # PostgreSQL DDL is applied by the deployment/migration
                        # step. Running CREATE INDEX/repair DDL independently
                        # in every API or worker process can deadlock during a
                        # simultaneous cold start. Runtime initialization is
                        # therefore read-only and fails fast on an incomplete
                        # deployment.
                        cur.execute(
                            """
                            SELECT to_regclass('pipeline_work_items') AS work_items,
                                   to_regclass('pipeline_work_outbox') AS work_outbox,
                                   to_regclass('uq_pipeline_work_items_active_scope') AS active_scope_index,
                                   to_regclass('uq_pipeline_work_items_active_resource_scope') AS active_resource_scope_index
                            """
                        )
                        row = _row_dict(cur.fetchone(), cur) or {}
                        missing = [
                            name
                            for name, value in row.items()
                            if value is None
                        ]
                        if missing:
                            raise RuntimeError(
                                "Schéma PostgreSQL de queue incomplet: "
                                + ", ".join(sorted(missing))
                            )
                else:
                    conn.executescript(_SQLITE_SCHEMA)
            self._schema_ready = True

    def enqueue(self, spec: WorkItemSpec, *, notify: bool = False) -> WorkItem:
        self.ensure_schema()
        with self._connection(immediate=not self.is_postgres) as conn:
            item, _created = self._insert_work_item(conn, spec, notify=notify)
            return item

    def _insert_work_item(self, conn, spec: WorkItemSpec, *, notify: bool) -> tuple[WorkItem, bool]:
        work_id = str(uuid.uuid4())
        run_id = spec.run_id or str(uuid.uuid4())
        dedupe_key = spec.dedupe_key or f"work:{work_id}"
        now = utcnow()
        available_at = spec.available_at or now
        max_attempts = max(1, min(100, int(spec.max_attempts)))
        task_type = str(spec.task_type or "").strip()
        if not task_type:
            raise ValueError("task_type est requis")
        pipeline_job_id = int(spec.pipeline_job_id) if spec.pipeline_job_id is not None else None
        folder_id = int(spec.folder_id) if spec.folder_id is not None else None
        resource_key = str(spec.resource_key or "").strip()
        if not resource_key:
            if folder_id is not None:
                resource_key = f"folder:{folder_id}"
            elif pipeline_job_id is not None:
                resource_key = f"pipeline:{pipeline_job_id}"
        if not resource_key:
            raise ValueError("pipeline_job_id, folder_id ou resource_key est requis")

        values = (
            work_id,
            pipeline_job_id,
            folder_id,
            resource_key,
            run_id,
            task_type,
            str(spec.scope_key or "pipeline"),
            dedupe_key,
            _json(spec.payload),
            WorkStatus.QUEUED.value,
            int(spec.priority),
            max_attempts,
            available_at if self.is_postgres else _sqlite_time(available_at),
            now if self.is_postgres else _sqlite_time(now),
            now if self.is_postgres else _sqlite_time(now),
        )
        if self.is_postgres:
            with conn.cursor() as cur:
                row = None
                created = False
                # PostgreSQL's unique partial index serializes concurrent
                # enqueues for the same job/scope.  A conflicting transaction
                # may finish between INSERT and SELECT, so retry a few times if
                # neither the active row nor the dedupe row remains visible.
                for _attempt in range(3):
                    cur.execute(
                        """
                        INSERT INTO pipeline_work_items
                            (id, pipeline_job_id, folder_id, resource_key,
                             run_id, task_type, scope_key,
                             dedupe_key, payload_json, status, priority, max_attempts,
                             available_at, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        RETURNING *
                        """,
                        values,
                    )
                    row = _row_dict(cur.fetchone(), cur)
                    if row is not None:
                        created = True
                        break
                    cur.execute(
                        """
                        SELECT * FROM pipeline_work_items
                        WHERE resource_key = %s
                          AND scope_key = %s
                          AND status IN ('queued', 'retry_scheduled', 'running')
                        ORDER BY created_at, id
                        LIMIT 1
                        """,
                        (resource_key, str(spec.scope_key or "pipeline")),
                    )
                    row = _row_dict(cur.fetchone(), cur)
                    if row is not None:
                        break
                    cur.execute(
                        "SELECT * FROM pipeline_work_items WHERE dedupe_key = %s",
                        (dedupe_key,),
                    )
                    row = _row_dict(cur.fetchone(), cur)
                    if row is not None:
                        break
                if row is None:
                    raise RuntimeError("Work-item introuvable après enqueue")
                item = _to_work_item(row)
                if created and notify:
                    self._insert_outbox(conn, item, available_at=available_at)
                return item, created

        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO pipeline_work_items
                (id, pipeline_job_id, folder_id, resource_key,
                 run_id, task_type, scope_key,
                 dedupe_key, payload_json, status, priority, max_attempts,
                 available_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        created = cur.rowcount == 1
        row = None
        if created:
            cur.execute("SELECT * FROM pipeline_work_items WHERE id = ?", (work_id,))
            row = _row_dict(cur.fetchone(), cur)
        else:
            cur.execute(
                """
                SELECT * FROM pipeline_work_items
                WHERE resource_key = ?
                  AND scope_key = ?
                  AND status IN ('queued', 'retry_scheduled', 'running')
                ORDER BY created_at, id
                LIMIT 1
                """,
                (resource_key, str(spec.scope_key or "pipeline")),
            )
            row = _row_dict(cur.fetchone(), cur)
            if row is None:
                cur.execute(
                    "SELECT * FROM pipeline_work_items WHERE dedupe_key = ?",
                    (dedupe_key,),
                )
                row = _row_dict(cur.fetchone(), cur)
        if row is None:
            raise RuntimeError("Work-item introuvable après enqueue")
        item = _to_work_item(row)
        if created and notify:
            self._insert_outbox(conn, item, available_at=available_at)
        return item, created

    def _insert_outbox(self, conn, item: WorkItem, *, available_at: datetime) -> None:
        now = utcnow()
        outbox_id = str(uuid.uuid4())
        delivery_id = str(uuid.uuid4())
        envelope = {
            "version": 1,
            "delivery_id": delivery_id,
            "work_item_id": item.id,
            "pipeline_job_id": item.pipeline_job_id,
            "run_id": item.run_id,
            "task_type": item.task_type,
        }
        values = (
            outbox_id,
            delivery_id,
            item.id,
            _json(envelope),
            available_at if self.is_postgres else _sqlite_time(available_at),
            now if self.is_postgres else _sqlite_time(now),
            now if self.is_postgres else _sqlite_time(now),
        )
        if self.is_postgres:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pipeline_work_outbox
                        (id, delivery_id, work_item_id, payload_json, available_at,
                         created_at, updated_at)
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
                    """,
                    values,
                )
            return
        conn.execute(
            """
            INSERT INTO pipeline_work_outbox
                (id, delivery_id, work_item_id, payload_json, available_at,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )

    def get(self, work_item_id: str) -> WorkItem | None:
        self.ensure_schema()
        ph = "%s" if self.is_postgres else "?"
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM pipeline_work_items WHERE id = {ph}", (work_item_id,))
            row = _row_dict(cur.fetchone(), cur)
            return _to_work_item(row) if row else None

    def latest_for_job(self, pipeline_job_id: int) -> WorkItem | None:
        self.ensure_schema()
        ph = "%s" if self.is_postgres else "?"
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT * FROM pipeline_work_items
                WHERE pipeline_job_id = {ph}
                ORDER BY created_at DESC LIMIT 1
                """,
                (pipeline_job_id,),
            )
            row = _row_dict(cur.fetchone(), cur)
            return _to_work_item(row) if row else None

    def latest_for_folder(
        self,
        folder_id: int,
        *,
        scope_key: str | None = None,
    ) -> WorkItem | None:
        self.ensure_schema()
        ph = "%s" if self.is_postgres else "?"
        scope_clause = f" AND scope_key = {ph}" if scope_key is not None else ""
        params = (int(folder_id), scope_key) if scope_key is not None else (int(folder_id),)
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT * FROM pipeline_work_items
                WHERE folder_id = {ph}{scope_clause}
                ORDER BY created_at DESC LIMIT 1
                """,
                params,
            )
            row = _row_dict(cur.fetchone(), cur)
            return _to_work_item(row) if row else None

    def claim_next(self, *, owner: str, lease_seconds: int) -> WorkItem | None:
        return self._claim(owner=owner, lease_seconds=lease_seconds, work_item_id=None)

    def claim(self, work_item_id: str, *, owner: str, lease_seconds: int) -> WorkItem | None:
        return self._claim(owner=owner, lease_seconds=lease_seconds, work_item_id=work_item_id)

    def _claim(
        self,
        *,
        owner: str,
        lease_seconds: int,
        work_item_id: str | None,
    ) -> WorkItem | None:
        self.ensure_schema()
        now = utcnow()
        expires = now + timedelta(seconds=max(1, lease_seconds))
        token = str(uuid.uuid4())

        if self.is_postgres:
            id_filter = "AND id = %s" if work_item_id else ""
            params: list[Any] = [now]
            if work_item_id:
                params.append(work_item_id)
            params.extend([owner, token, expires, now])
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        WITH candidate AS (
                            SELECT id
                            FROM pipeline_work_items
                            WHERE attempt_count < max_attempts
                              AND (
                                  (status IN ('queued', 'retry_scheduled') AND available_at <= %s)
                                  OR (status = 'running' AND lease_expires_at < %s)
                              )
                              {id_filter}
                            ORDER BY priority DESC, available_at, created_at
                            FOR UPDATE SKIP LOCKED
                            LIMIT 1
                        )
                        UPDATE pipeline_work_items AS item
                        SET status = 'running',
                            attempt_count = item.attempt_count + 1,
                            lease_owner = %s,
                            lease_token = %s,
                            lease_version = item.lease_version + 1,
                            lease_expires_at = %s,
                            first_started_at = COALESCE(item.first_started_at, %s),
                            updated_at = %s
                        FROM candidate
                        WHERE item.id = candidate.id
                        RETURNING item.*
                        """,
                        # now is repeated for the stale lease predicate and updated_at.
                        ([now, now] + ([work_item_id] if work_item_id else []) + [owner, token, expires, now, now]),
                    )
                    row = _row_dict(cur.fetchone(), cur)
                    return _to_work_item(row) if row else None

        now_s = _sqlite_time(now)
        expires_s = _sqlite_time(expires)
        with self._connection(immediate=True) as conn:
            cur = conn.cursor()
            params: list[Any] = [now_s, now_s]
            id_filter = ""
            if work_item_id:
                id_filter = "AND id = ?"
                params.append(work_item_id)
            cur.execute(
                f"""
                SELECT id FROM pipeline_work_items
                WHERE attempt_count < max_attempts
                  AND (
                      (status IN ('queued', 'retry_scheduled') AND available_at <= ?)
                      OR (status = 'running' AND lease_expires_at < ?)
                  )
                  {id_filter}
                ORDER BY priority DESC, available_at, created_at
                LIMIT 1
                """,
                params,
            )
            candidate = cur.fetchone()
            if not candidate:
                return None
            candidate_id = candidate["id"]
            cur.execute(
                """
                UPDATE pipeline_work_items
                SET status = 'running', attempt_count = attempt_count + 1,
                    lease_owner = ?, lease_token = ?, lease_version = lease_version + 1,
                    lease_expires_at = ?, first_started_at = COALESCE(first_started_at, ?),
                    updated_at = ?
                WHERE id = ?
                  AND attempt_count < max_attempts
                  AND (
                      (status IN ('queued', 'retry_scheduled') AND available_at <= ?)
                      OR (status = 'running' AND lease_expires_at < ?)
                  )
                """,
                (owner, token, expires_s, now_s, now_s, candidate_id, now_s, now_s),
            )
            if cur.rowcount != 1:
                return None
            cur.execute("SELECT * FROM pipeline_work_items WHERE id = ?", (candidate_id,))
            row = _row_dict(cur.fetchone(), cur)
            return _to_work_item(row) if row else None

    def renew_lease(self, work_item_id: str, lease_token: str, *, lease_seconds: int) -> bool:
        self.ensure_schema()
        now = utcnow()
        expires = now + timedelta(seconds=max(1, lease_seconds))
        if self.is_postgres:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE pipeline_work_items
                        SET lease_expires_at = %s, updated_at = %s
                        WHERE id = %s AND status = 'running' AND lease_token = %s
                        """,
                        (expires, now, work_item_id, lease_token),
                    )
                    return cur.rowcount == 1
        with self._connection(immediate=True) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE pipeline_work_items
                SET lease_expires_at = ?, updated_at = ?
                WHERE id = ? AND status = 'running' AND lease_token = ?
                """,
                (_sqlite_time(expires), _sqlite_time(now), work_item_id, lease_token),
            )
            return cur.rowcount == 1

    def update_progress(
        self,
        work_item_id: str,
        lease_token: str,
        progress: Mapping[str, Any],
    ) -> None:
        """Persist progress while fencing stale or replaced workers."""
        self.ensure_schema()
        now = utcnow()
        if self.is_postgres:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE pipeline_work_items
                        SET result_json = %s::jsonb, updated_at = %s
                        WHERE id = %s AND status = 'running' AND lease_token = %s
                        """,
                        (_json(progress), now, work_item_id, lease_token),
                    )
                    if cur.rowcount != 1:
                        raise LeaseLostError(
                            f"Lease perdu pendant la progression du work-item {work_item_id}"
                        )
            return

        now_s = _sqlite_time(now)
        with self._connection(immediate=True) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE pipeline_work_items
                SET result_json = ?, updated_at = ?
                WHERE id = ? AND status = 'running' AND lease_token = ?
                """,
                (_json(progress), now_s, work_item_id, lease_token),
            )
            if cur.rowcount != 1:
                raise LeaseLostError(
                    f"Lease perdu pendant la progression du work-item {work_item_id}"
                )

    def complete(
        self,
        work_item_id: str,
        lease_token: str,
        *,
        result: Mapping[str, Any] | None = None,
        next_items: Iterable[WorkItemSpec] = (),
        notify: bool = False,
    ) -> list[WorkItem]:
        self.ensure_schema()
        now = utcnow()
        next_created: list[WorkItem] = []
        with self._connection(immediate=not self.is_postgres) as conn:
            cur = conn.cursor()
            if self.is_postgres:
                cur.execute(
                    """
                    UPDATE pipeline_work_items
                    SET status = 'completed', result_json = %s::jsonb,
                        completed_at = %s, updated_at = %s,
                        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL
                    WHERE id = %s AND status = 'running' AND lease_token = %s
                    """,
                    (_json(result), now, now, work_item_id, lease_token),
                )
            else:
                now_s = _sqlite_time(now)
                cur.execute(
                    """
                    UPDATE pipeline_work_items
                    SET status = 'completed', result_json = ?, completed_at = ?, updated_at = ?,
                        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL
                    WHERE id = ? AND status = 'running' AND lease_token = ?
                    """,
                    (_json(result), now_s, now_s, work_item_id, lease_token),
                )
            if cur.rowcount != 1:
                raise LeaseLostError(f"Lease perdu avant completion du work-item {work_item_id}")
            for spec in next_items:
                item, _created = self._insert_work_item(conn, spec, notify=notify)
                next_created.append(item)
        return next_created

    def retry(
        self,
        work_item_id: str,
        lease_token: str,
        *,
        error: str,
        available_at: datetime,
        notify: bool = False,
    ) -> str:
        self.ensure_schema()
        current = self.get(work_item_id)
        if not current or current.lease_token != lease_token or current.status != WorkStatus.RUNNING.value:
            raise LeaseLostError(f"Lease perdu avant retry du work-item {work_item_id}")
        if current.attempt_count >= current.max_attempts:
            self.dead_letter(work_item_id, lease_token, error=error)
            return WorkStatus.DEAD_LETTERED.value

        now = utcnow()
        with self._connection(immediate=not self.is_postgres) as conn:
            cur = conn.cursor()
            if self.is_postgres:
                cur.execute(
                    """
                    UPDATE pipeline_work_items
                    SET status = 'retry_scheduled', available_at = %s,
                        last_error = %s, updated_at = %s,
                        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL
                    WHERE id = %s AND status = 'running' AND lease_token = %s
                    RETURNING *
                    """,
                    (available_at, error[:4000], now, work_item_id, lease_token),
                )
            else:
                cur.execute(
                    """
                    UPDATE pipeline_work_items
                    SET status = 'retry_scheduled', available_at = ?,
                        last_error = ?, updated_at = ?,
                        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL
                    WHERE id = ? AND status = 'running' AND lease_token = ?
                    """,
                    (
                        _sqlite_time(available_at),
                        error[:4000],
                        _sqlite_time(now),
                        work_item_id,
                        lease_token,
                    ),
                )
            if cur.rowcount != 1:
                raise LeaseLostError(f"Lease perdu pendant retry du work-item {work_item_id}")
            if self.is_postgres:
                row = _row_dict(cur.fetchone(), cur)
            else:
                cur.execute("SELECT * FROM pipeline_work_items WHERE id = ?", (work_item_id,))
                row = _row_dict(cur.fetchone(), cur)
            if notify and row:
                self._insert_outbox(conn, _to_work_item(row), available_at=available_at)
        return WorkStatus.RETRY_SCHEDULED.value

    def dead_letter(self, work_item_id: str, lease_token: str, *, error: str) -> None:
        self.ensure_schema()
        now = utcnow()
        ph = "%s" if self.is_postgres else "?"
        with self._connection(immediate=not self.is_postgres) as conn:
            cur = conn.cursor()
            params = (
                error[:4000],
                now if self.is_postgres else _sqlite_time(now),
                now if self.is_postgres else _sqlite_time(now),
                work_item_id,
                lease_token,
            )
            cur.execute(
                f"""
                UPDATE pipeline_work_items
                SET status = 'dead_lettered', last_error = {ph},
                    dead_lettered_at = {ph}, updated_at = {ph},
                    lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL
                WHERE id = {ph} AND status = 'running' AND lease_token = {ph}
                """,
                params,
            )
            if cur.rowcount != 1:
                raise LeaseLostError(f"Lease perdu avant DLQ du work-item {work_item_id}")

    def mark_exhausted_if_stale(self, work_item_id: str, *, error: str) -> bool:
        """Dead-letter a crashed last attempt after its lease expires."""
        self.ensure_schema()
        now = utcnow()
        ph = "%s" if self.is_postgres else "?"
        now_value = now if self.is_postgres else _sqlite_time(now)
        with self._connection(immediate=not self.is_postgres) as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                UPDATE pipeline_work_items
                SET status = 'dead_lettered', last_error = {ph},
                    dead_lettered_at = {ph}, updated_at = {ph},
                    lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL
                WHERE id = {ph} AND status = 'running'
                  AND attempt_count >= max_attempts
                  AND lease_expires_at < {ph}
                """,
                (error[:4000], now_value, now_value, work_item_id, now_value),
            )
            return cur.rowcount == 1

    def dead_letter_one_exhausted(self) -> WorkItem | None:
        """Reconcile a crashed final attempt even when no broker message remains."""
        self.ensure_schema()
        now = utcnow()
        error = "Dernière tentative interrompue; lease expiré"
        if self.is_postgres:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        WITH candidate AS (
                            SELECT id
                            FROM pipeline_work_items
                            WHERE status = 'running'
                              AND attempt_count >= max_attempts
                              AND lease_expires_at < %s
                            ORDER BY lease_expires_at, created_at
                            FOR UPDATE SKIP LOCKED
                            LIMIT 1
                        )
                        UPDATE pipeline_work_items AS item
                        SET status = 'dead_lettered', last_error = %s,
                            dead_lettered_at = %s, updated_at = %s,
                            lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL
                        FROM candidate
                        WHERE item.id = candidate.id
                        RETURNING item.*
                        """,
                        (now, error, now, now),
                    )
                    row = _row_dict(cur.fetchone(), cur)
                    return _to_work_item(row) if row else None

        now_s = _sqlite_time(now)
        with self._connection(immediate=True) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id FROM pipeline_work_items
                WHERE status = 'running'
                  AND attempt_count >= max_attempts
                  AND lease_expires_at < ?
                ORDER BY lease_expires_at, created_at LIMIT 1
                """,
                (now_s,),
            )
            candidate = cur.fetchone()
            if not candidate:
                return None
            cur.execute(
                """
                UPDATE pipeline_work_items
                SET status = 'dead_lettered', last_error = ?,
                    dead_lettered_at = ?, updated_at = ?,
                    lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL
                WHERE id = ? AND status = 'running'
                  AND attempt_count >= max_attempts
                  AND lease_expires_at < ?
                """,
                (error, now_s, now_s, candidate["id"], now_s),
            )
            if cur.rowcount != 1:
                return None
            cur.execute("SELECT * FROM pipeline_work_items WHERE id = ?", (candidate["id"],))
            row = _row_dict(cur.fetchone(), cur)
            return _to_work_item(row) if row else None

    def cancel(self, work_item_id: str) -> bool:
        self.ensure_schema()
        now = utcnow()
        ph = "%s" if self.is_postgres else "?"
        now_value = now if self.is_postgres else _sqlite_time(now)
        terminal = tuple(TERMINAL_STATUSES)
        placeholders = ", ".join([ph] * len(terminal))
        with self._connection(immediate=not self.is_postgres) as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                UPDATE pipeline_work_items
                SET status = 'cancelled', cancelled_at = {ph}, updated_at = {ph},
                    lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL
                WHERE id = {ph} AND status NOT IN ({placeholders})
                """,
                (now_value, now_value, work_item_id, *terminal),
            )
            return cur.rowcount == 1

    def claim_due_outbox(
        self,
        *,
        owner: str,
        lease_seconds: int,
        limit: int,
    ) -> list[OutboxDelivery]:
        self.ensure_schema()
        deliveries: list[OutboxDelivery] = []
        for _ in range(max(0, limit)):
            delivery = self._claim_one_outbox(owner=owner, lease_seconds=lease_seconds)
            if not delivery:
                break
            deliveries.append(delivery)
        return deliveries

    def _claim_one_outbox(self, *, owner: str, lease_seconds: int) -> OutboxDelivery | None:
        now = utcnow()
        expires = now + timedelta(seconds=max(1, lease_seconds))
        token = str(uuid.uuid4())
        if self.is_postgres:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        WITH candidate AS (
                            SELECT outbox.id
                            FROM pipeline_work_outbox AS outbox
                            JOIN pipeline_work_items AS item ON item.id = outbox.work_item_id
                            WHERE item.status IN ('queued', 'retry_scheduled', 'running')
                              AND outbox.available_at <= %s
                              AND (
                                  outbox.status = 'pending'
                                  OR (outbox.status = 'publishing' AND outbox.lease_expires_at < %s)
                              )
                            ORDER BY outbox.available_at, outbox.created_at
                            FOR UPDATE SKIP LOCKED
                            LIMIT 1
                        )
                        UPDATE pipeline_work_outbox AS outbox
                        SET status = 'publishing', publish_attempts = outbox.publish_attempts + 1,
                            lease_owner = %s, lease_token = %s, lease_expires_at = %s,
                            updated_at = %s
                        FROM candidate
                        WHERE outbox.id = candidate.id
                        RETURNING outbox.*
                        """,
                        (now, now, owner, token, expires, now),
                    )
                    row = _row_dict(cur.fetchone(), cur)
        else:
            now_s = _sqlite_time(now)
            with self._connection(immediate=True) as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT outbox.id
                    FROM pipeline_work_outbox AS outbox
                    JOIN pipeline_work_items AS item ON item.id = outbox.work_item_id
                    WHERE item.status IN ('queued', 'retry_scheduled', 'running')
                      AND outbox.available_at <= ?
                      AND (
                          outbox.status = 'pending'
                          OR (outbox.status = 'publishing' AND outbox.lease_expires_at < ?)
                      )
                    ORDER BY outbox.available_at, outbox.created_at
                    LIMIT 1
                    """,
                    (now_s, now_s),
                )
                candidate = cur.fetchone()
                if not candidate:
                    return None
                cur.execute(
                    """
                    UPDATE pipeline_work_outbox
                    SET status = 'publishing', publish_attempts = publish_attempts + 1,
                        lease_owner = ?, lease_token = ?, lease_expires_at = ?, updated_at = ?
                    WHERE id = ?
                      AND (status = 'pending' OR (status = 'publishing' AND lease_expires_at < ?))
                    """,
                    (owner, token, _sqlite_time(expires), now_s, candidate["id"], now_s),
                )
                if cur.rowcount != 1:
                    return None
                cur.execute("SELECT * FROM pipeline_work_outbox WHERE id = ?", (candidate["id"],))
                row = _row_dict(cur.fetchone(), cur)
        if not row:
            return None
        return OutboxDelivery(
            id=str(row["id"]),
            delivery_id=str(row["delivery_id"]),
            work_item_id=str(row["work_item_id"]),
            payload=_decode_json(row.get("payload_json")),
            available_at=row.get("available_at"),
            publish_attempts=int(row.get("publish_attempts") or 0),
            lease_token=str(row["lease_token"]),
        )

    def mark_outbox_published(self, outbox_id: str, lease_token: str) -> None:
        self._settle_outbox(outbox_id, lease_token, published=True, error=None, retry_at=None)

    def mark_outbox_failed(
        self,
        outbox_id: str,
        lease_token: str,
        *,
        error: str,
        retry_at: datetime,
    ) -> None:
        self._settle_outbox(
            outbox_id,
            lease_token,
            published=False,
            error=error,
            retry_at=retry_at,
        )

    def _settle_outbox(
        self,
        outbox_id: str,
        lease_token: str,
        *,
        published: bool,
        error: str | None,
        retry_at: datetime | None,
    ) -> None:
        self.ensure_schema()
        now = utcnow()
        with self._connection(immediate=not self.is_postgres) as conn:
            cur = conn.cursor()
            if published:
                status = "published"
                available_at = now
                published_at = now
            else:
                status = "pending"
                available_at = retry_at or now
                published_at = None
            values = (
                status,
                available_at if self.is_postgres else _sqlite_time(available_at),
                error[:4000] if error else None,
                published_at if self.is_postgres else (_sqlite_time(published_at) if published_at else None),
                now if self.is_postgres else _sqlite_time(now),
                outbox_id,
                lease_token,
            )
            ph = "%s" if self.is_postgres else "?"
            cur.execute(
                f"""
                UPDATE pipeline_work_outbox
                SET status = {ph}, available_at = {ph}, last_error = {ph},
                    published_at = {ph}, updated_at = {ph},
                    lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL
                WHERE id = {ph} AND status = 'publishing' AND lease_token = {ph}
                """,
                values,
            )
            if cur.rowcount != 1:
                raise LeaseLostError(f"Lease outbox perdu pour {outbox_id}")
