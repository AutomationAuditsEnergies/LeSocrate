"""PostgreSQL persistence for paid AI-teacher orders.

The order is the authorization boundary: a platform can only be provisioned by
the durable fulfillment worker after this record is paid or explicitly exempt.
"""

from __future__ import annotations

import json
from typing import Any
import uuid

from database.postgres import get_postgres_connection


def _enqueue_fulfillment_in_transaction(cur, order: dict[str, Any]) -> dict[str, Any]:
    """Persist the fulfillment job and its order state in the caller transaction."""
    if order.get("fulfillment_status") in {"queued", "running", "fulfilled"}:
        return order

    public_id = str(order["public_id"])
    resource_key = f"ai-teacher-order:{order['id']}"
    base_dedupe_key = f"ai-teacher-order:{order['id']}:fulfill"

    # A handler failure can be scheduled for an automatic queue retry before the
    # order row is refreshed. Reattach to that active item instead of creating a
    # competing fulfillment for the same paid order.
    cur.execute(
        """
        SELECT id, status
        FROM pipeline_work_items
        WHERE resource_key = %s
          AND scope_key = 'fulfillment'
          AND task_type = 'ai_teacher_fulfillment'
          AND status IN ('queued', 'retry_scheduled', 'running')
        ORDER BY created_at DESC
        LIMIT 1
        FOR UPDATE
        """,
        (resource_key,),
    )
    active = cur.fetchone()
    if active:
        fulfillment_status = "running" if active["status"] == "running" else "queued"
        status = "fulfilling" if fulfillment_status == "running" else "fulfillment_queued"
        cur.execute(
            """
            UPDATE ai_teacher_orders
            SET status = %s, fulfillment_status = %s,
                fulfillment_work_item_id = %s, last_error = NULL, updated_at = NOW()
            WHERE id = %s
              AND fulfillment_status != 'fulfilled'
            RETURNING *
            """,
            (status, fulfillment_status, active["id"], int(order["id"])),
        )
        return cur.fetchone() or order

    # Keep the initial key stable for webhook idempotence. A manual retry gets a
    # fresh immutable work item so the dead-letter history is retained instead
    # of silently resetting attempts on the original row. The order lock makes
    # the transition idempotent: a repeated HTTP request sees `queued` above.
    if order.get("fulfillment_status") == "failed":
        dedupe_key = f"{base_dedupe_key}:retry:{uuid.uuid4()}"
    else:
        dedupe_key = base_dedupe_key
    work_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO pipeline_work_items (
            id, pipeline_job_id, folder_id, resource_key, run_id, task_type,
            scope_key, dedupe_key, payload_json, status, priority,
            max_attempts, available_at, created_at, updated_at
        )
        VALUES (
            %s, NULL, NULL, %s, %s, 'ai_teacher_fulfillment', 'fulfillment',
            %s, %s::jsonb, 'queued', 20, 5, NOW(), NOW(), NOW()
        )
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        (
            work_id,
            resource_key,
            f"teacher-order-{public_id}",
            dedupe_key,
            json.dumps(
                {"order_id": int(order["id"]), "order_public_id": public_id},
                sort_keys=True,
            ),
        ),
    )
    inserted = cur.fetchone()
    if inserted:
        work_item_id = inserted["id"]
    else:
        cur.execute(
            "SELECT id FROM pipeline_work_items WHERE dedupe_key = %s",
            (dedupe_key,),
        )
        existing = cur.fetchone()
        if not existing:
            raise RuntimeError("Travail durable de fulfillment introuvable après insertion")
        work_item_id = existing["id"]
    cur.execute(
        """
        UPDATE ai_teacher_orders
        SET status = 'fulfillment_queued', fulfillment_status = 'queued',
            fulfillment_work_item_id = %s, last_error = NULL, updated_at = NOW()
        WHERE id = %s
          AND fulfillment_status NOT IN ('running', 'fulfilled')
        RETURNING *
        """,
        (work_item_id, int(order["id"])),
    )
    return cur.fetchone() or order


def retry_order_fulfillment(
    order_id: int,
    center_account_id: int,
) -> dict[str, Any] | None:
    """Idempotently requeue one authorized, failed order for its owning centre."""
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM ai_teacher_orders
                WHERE id = %s AND center_account_id = %s
                FOR UPDATE
                """,
                (int(order_id), int(center_account_id)),
            )
            order = cur.fetchone()
            if not order:
                return None
            if order.get("payment_status") not in {"paid", "not_required"}:
                return order
            if order.get("fulfillment_status") in {"queued", "running", "fulfilled"}:
                return order
            if order.get("fulfillment_status") != "failed":
                return order
            return _enqueue_fulfillment_in_transaction(cur, order)


def _claim_webhook_event(cur, event: dict[str, Any]) -> bool:
    """Claim a Stripe event inside the same transaction as its side effects."""
    cur.execute(
        """
        INSERT INTO stripe_webhook_events (
            event_id, event_type, livemode, payload_json, status, attempt_count
        )
        VALUES (%s, %s, %s, %s::jsonb, 'processing', 1)
        ON CONFLICT (event_id) DO UPDATE
        SET status = 'processing',
            attempt_count = stripe_webhook_events.attempt_count + 1,
            payload_json = EXCLUDED.payload_json,
            last_error = NULL,
            updated_at = NOW()
        WHERE stripe_webhook_events.status = 'failed'
           OR (
                stripe_webhook_events.status = 'processing'
                AND stripe_webhook_events.updated_at < NOW() - INTERVAL '5 minutes'
           )
        RETURNING event_id
        """,
        (
            str(event["id"]),
            str(event["type"]),
            bool(event.get("livemode")),
            json.dumps(event, ensure_ascii=False, sort_keys=True),
        ),
    )
    return cur.fetchone() is not None


def get_center_billing_account(center_account_id: int) -> dict[str, Any] | None:
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, username, center_name, is_active, stripe_customer_id,
                       billing_mode, billing_exempt_reason, billing_exempt_at
                FROM training_center_accounts
                WHERE id = %s
                """,
                (int(center_account_id),),
            )
            return cur.fetchone()


def get_reusable_module(module_id: int, center_account_id: int) -> dict[str, Any] | None:
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id, m.tp_name, m.rncp_code, j.total_hours,
                       m.source_platform_id, m.source_pipeline_job_id, m.status,
                       m.voice_type,
                       (SELECT COUNT(*) FROM cours_folders cf
                        WHERE cf.platform_id = m.source_platform_id) AS nb_folders
                FROM formation_modules m
                LEFT JOIN formation_pipeline_jobs j ON j.id = m.source_pipeline_job_id
                WHERE m.id = %s
                  AND m.center_account_id = %s
                """,
                (int(module_id), int(center_account_id)),
            )
            return cur.fetchone()


def create_order(values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Create once per center/idempotency key and return ``(order, created)``."""
    payload_json = json.dumps(values["request_payload"], ensure_ascii=False, sort_keys=True)
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ai_teacher_orders (
                    center_account_id, operation_type, source_module_id, status,
                    payment_status, fulfillment_status, training_title, rncp_code,
                    total_hours, request_payload_json, creation_request_id,
                    request_fingerprint, pricing_key, stripe_price_id,
                    quoted_amount_cents, catalog_amount_cents, charged_amount_cents,
                    currency, authorization_kind, authorized_at
                )
                VALUES (
                    %(center_account_id)s, %(operation_type)s, %(source_module_id)s,
                    %(status)s, %(payment_status)s, 'not_started', %(training_title)s,
                    %(rncp_code)s, %(total_hours)s, %(request_payload_json)s::jsonb,
                    %(creation_request_id)s, %(request_fingerprint)s, %(pricing_key)s,
                    %(stripe_price_id)s, %(catalog_amount_cents)s,
                    %(catalog_amount_cents)s, %(charged_amount_cents)s, %(currency)s,
                    %(authorization_kind)s,
                    CASE WHEN %(payment_status)s = 'not_required' THEN NOW() ELSE NULL END
                )
                ON CONFLICT (center_account_id, creation_request_id) DO NOTHING
                RETURNING *
                """,
                {**values, "request_payload_json": payload_json},
            )
            row = cur.fetchone()
            if row:
                created = True
            else:
                cur.execute(
                    """
                    SELECT * FROM ai_teacher_orders
                    WHERE center_account_id = %s AND creation_request_id = %s
                    FOR UPDATE
                    """,
                    (int(values["center_account_id"]), values["creation_request_id"]),
                )
                row = cur.fetchone()
                created = False
            if row and row.get("payment_status") == "not_required":
                row = _enqueue_fulfillment_in_transaction(cur, row)
            return row, created


def enqueue_order_fulfillment(order_id: int) -> dict[str, Any] | None:
    """Idempotently queue an authorized order in one PostgreSQL transaction."""
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM ai_teacher_orders
                WHERE id = %s AND payment_status IN ('paid', 'not_required')
                FOR UPDATE
                """,
                (int(order_id),),
            )
            order = cur.fetchone()
            if not order:
                return None
            return _enqueue_fulfillment_in_transaction(cur, order)


def get_order(public_id: str, *, center_account_id: int | None = None) -> dict[str, Any] | None:
    params: list[Any] = [str(public_id)]
    tenant_clause = ""
    if center_account_id is not None:
        tenant_clause = " AND center_account_id = %s"
        params.append(int(center_account_id))
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM ai_teacher_orders WHERE public_id = %s{tenant_clause}",
                tuple(params),
            )
            return cur.fetchone()


def attach_checkout_session(
    order_id: int,
    *,
    checkout_session_id: str,
    payment_intent_id: str | None,
    expires_at,
) -> dict[str, Any]:
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai_teacher_orders
                SET stripe_checkout_session_id = %s,
                    stripe_payment_intent_id = COALESCE(%s, stripe_payment_intent_id),
                    checkout_expires_at = %s,
                    checkout_attempt_count = checkout_attempt_count + 1,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (checkout_session_id, payment_intent_id, expires_at, int(order_id)),
            )
            return cur.fetchone()


def update_order_state(order_id: int, **fields) -> dict[str, Any] | None:
    allowed = {
        "status", "payment_status", "fulfillment_status", "platform_id",
        "pipeline_job_id", "fulfillment_work_item_id", "last_error",
        "fulfilled_at", "refunded_at",
    }
    values = {key: value for key, value in fields.items() if key in allowed}
    if not values:
        return None
    assignments = ", ".join(f"{key} = %s" for key in values)
    if values.get("fulfillment_status") == "fulfilled" and "fulfilled_at" not in values:
        assignments += ", fulfilled_at = COALESCE(fulfilled_at, NOW())"
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE ai_teacher_orders SET {assignments}, updated_at = NOW() WHERE id = %s RETURNING *",
                (*values.values(), int(order_id)),
            )
            return cur.fetchone()


def complete_order_pipeline_fulfillment(
    order_id: int,
    *,
    pipeline_job_id: int,
    platform_id: int,
) -> dict[str, Any] | None:
    """Atomically complete a paid order bound to the finishing text pipeline.

    Auto-pilot ticks are durable and can be replayed.  The pipeline binding in
    the predicate prevents a late tick from completing an order now attached
    to another pipeline, while the fulfilled guard makes duplicate terminal
    ticks harmless.
    """
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai_teacher_orders
                SET status = 'fulfilled', fulfillment_status = 'fulfilled',
                    platform_id = %s, pipeline_job_id = %s,
                    fulfilled_at = COALESCE(fulfilled_at, NOW()),
                    last_error = NULL, updated_at = NOW()
                WHERE id = %s
                  AND payment_status IN ('paid', 'not_required')
                  AND fulfillment_status != 'fulfilled'
                  AND (pipeline_job_id IS NULL OR pipeline_job_id = %s)
                RETURNING *
                """,
                (
                    int(platform_id),
                    int(pipeline_job_id),
                    int(order_id),
                    int(pipeline_job_id),
                ),
            )
            row = cur.fetchone()
            if row:
                return row
            cur.execute(
                "SELECT * FROM ai_teacher_orders WHERE id = %s",
                (int(order_id),),
            )
            return cur.fetchone()


def fail_order_pipeline_fulfillment(
    order_id: int,
    *,
    pipeline_job_id: int,
    error: str,
) -> dict[str, Any] | None:
    """Make a terminally failed paid pipeline order eligible for retry.

    A completion that won the race is never downgraded.  Retrying this failed
    order reuses its original payment authorization and creates a fresh durable
    work item via :func:`retry_order_fulfillment`.
    """
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai_teacher_orders
                SET status = 'fulfillment_failed', fulfillment_status = 'failed',
                    last_error = %s, updated_at = NOW()
                WHERE id = %s
                  AND payment_status IN ('paid', 'not_required')
                  AND fulfillment_status != 'fulfilled'
                  AND (pipeline_job_id IS NULL OR pipeline_job_id = %s)
                RETURNING *
                """,
                (str(error)[:500], int(order_id), int(pipeline_job_id)),
            )
            row = cur.fetchone()
            if row:
                return row
            cur.execute(
                "SELECT * FROM ai_teacher_orders WHERE id = %s",
                (int(order_id),),
            )
            return cur.fetchone()


def claim_order_for_fulfillment(order_id: int) -> dict[str, Any] | None:
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai_teacher_orders
                SET status = 'fulfilling', fulfillment_status = 'running',
                    last_error = NULL, updated_at = NOW()
                WHERE id = %s
                  AND payment_status IN ('paid', 'not_required')
                  AND fulfillment_status IN ('not_started', 'queued', 'failed')
                RETURNING *
                """,
                (int(order_id),),
            )
            row = cur.fetchone()
            if row:
                return row
            cur.execute("SELECT * FROM ai_teacher_orders WHERE id = %s", (int(order_id),))
            return cur.fetchone()


def apply_stripe_webhook_event(event: dict[str, Any]) -> bool:
    """Apply a verified Stripe event and enqueue fulfillment atomically.

    The event claim, order transition and durable queue insert commit together.
    A duplicate event is a no-op; a crashed transaction is safely retryable.
    """
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            if not _claim_webhook_event(cur, event):
                return False
            event_type = str(event["type"])
            obj = dict(event["data"]["object"])
            order = None

            if event_type in {
                "checkout.session.completed",
                "checkout.session.async_payment_succeeded",
            }:
                cur.execute(
                    "SELECT * FROM ai_teacher_orders WHERE stripe_checkout_session_id = %s FOR UPDATE",
                    (str(obj.get("id") or ""),),
                )
                order = cur.fetchone()
                if order and obj.get("payment_status") in {"paid", "no_payment_required"}:
                    if str(order["public_id"]) != str(obj.get("client_reference_id") or ""):
                        raise ValueError("Référence Stripe incohérente")
                    metadata = dict(obj.get("metadata") or {})
                    if (
                        metadata.get("ai_teacher_order_id")
                        and str(metadata["ai_teacher_order_id"]) != str(order["id"])
                    ):
                        raise ValueError("Métadonnée de commande Stripe incohérente")
                    if (
                        metadata.get("order_public_id")
                        and str(metadata["order_public_id"]) != str(order["public_id"])
                    ):
                        raise ValueError("Métadonnée publique Stripe incohérente")
                    amount = int(obj.get("amount_total") or 0)
                    if amount != int(order.get("catalog_amount_cents") or -1):
                        raise ValueError("Montant Stripe incohérent")
                    if str(obj.get("currency") or "").lower() != str(order["currency"]).lower():
                        raise ValueError("Devise Stripe incohérente")
                    cur.execute(
                        """
                        UPDATE ai_teacher_orders
                        SET status = CASE WHEN status = 'fulfilled' THEN status ELSE 'authorized' END,
                            payment_status = 'paid',
                            stripe_payment_intent_id = COALESCE(%s, stripe_payment_intent_id),
                            charged_amount_cents = %s,
                            paid_at = COALESCE(paid_at, NOW()),
                            authorized_at = COALESCE(authorized_at, NOW()),
                            last_error = NULL, updated_at = NOW()
                        WHERE id = %s
                          AND authorization_kind = 'stripe'
                          AND payment_status IN ('awaiting_payment', 'processing', 'paid')
                        RETURNING *
                        """,
                        (obj.get("payment_intent"), amount, int(order["id"])),
                    )
                    authorized_order = cur.fetchone()
                    if authorized_order:
                        order = _enqueue_fulfillment_in_transaction(cur, authorized_order)
                elif order and order.get("payment_status") not in {"paid", "refunded"}:
                    cur.execute(
                        """
                        UPDATE ai_teacher_orders
                        SET payment_status = 'processing', updated_at = NOW()
                        WHERE id = %s
                        """,
                        (int(order["id"]),),
                    )
            elif event_type in {"checkout.session.async_payment_failed", "checkout.session.expired"}:
                cur.execute(
                    """
                    UPDATE ai_teacher_orders
                    SET status = %s, payment_status = %s, updated_at = NOW()
                    WHERE stripe_checkout_session_id = %s
                      AND payment_status NOT IN ('paid', 'refunded')
                    """,
                    (
                        "payment_failed" if event_type.endswith("failed") else "expired",
                        "failed" if event_type.endswith("failed") else "expired",
                        str(obj.get("id") or ""),
                    ),
                )
            elif event_type == "charge.refunded":
                fully_refunded = bool(obj.get("refunded")) or (
                    int(obj.get("amount") or 0) > 0
                    and int(obj.get("amount_refunded") or 0) >= int(obj.get("amount") or 0)
                )
                payment_intent_id = str(obj.get("payment_intent") or "")
                metadata = dict(obj.get("metadata") or {})
                order_id = metadata.get("ai_teacher_order_id")
                if payment_intent_id:
                    cur.execute(
                        """
                        SELECT * FROM ai_teacher_orders
                        WHERE stripe_payment_intent_id = %s
                        FOR UPDATE
                        """,
                        (payment_intent_id,),
                    )
                    order = cur.fetchone()
                if not order and str(order_id or "").isdigit():
                    cur.execute(
                        "SELECT * FROM ai_teacher_orders WHERE id = %s FOR UPDATE",
                        (int(order_id),),
                    )
                    order = cur.fetchone()
                if order and fully_refunded:
                    cur.execute(
                        """
                        UPDATE ai_teacher_orders
                        SET status = 'refunded', payment_status = 'refunded',
                            stripe_payment_intent_id = COALESCE(NULLIF(%s, ''), stripe_payment_intent_id),
                            refunded_at = COALESCE(refunded_at, NOW()), updated_at = NOW()
                        WHERE id = %s
                        """,
                        (payment_intent_id, int(order["id"])),
                    )

            cur.execute(
                """
                UPDATE stripe_webhook_events
                SET status = 'processed', last_error = NULL,
                    processed_at = NOW(), updated_at = NOW()
                WHERE event_id = %s
                """,
                (str(event["id"]),),
            )
            return True


def record_webhook_failure(event: dict[str, Any], error: str) -> None:
    """Persist diagnostics after the atomic event transaction rolls back."""
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO stripe_webhook_events (
                    event_id, event_type, livemode, payload_json, status,
                    attempt_count, last_error
                )
                VALUES (%s, %s, %s, %s::jsonb, 'failed', 1, %s)
                ON CONFLICT (event_id) DO UPDATE
                SET status = 'failed',
                    attempt_count = stripe_webhook_events.attempt_count + 1,
                    payload_json = EXCLUDED.payload_json,
                    last_error = EXCLUDED.last_error,
                    updated_at = NOW()
                WHERE stripe_webhook_events.status != 'processed'
                """,
                (
                    str(event["id"]),
                    str(event["type"]),
                    bool(event.get("livemode")),
                    json.dumps(event, ensure_ascii=False, sort_keys=True),
                    str(error)[:500],
                ),
            )
