#!/usr/bin/env python3
"""Grant or revoke Stripe exemption for one existing PostgreSQL center.

Example (Formation3 environment loaded):
  python tools/billing/set_center_exemption.py \
    --username newpiprod@gmail.com --grant \
    --reason "Compte interne Le Socrate" --actor "deployment"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database.postgres import get_postgres_connection


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--grant", action="store_true")
    action.add_argument("--revoke", action="store_true")
    parser.add_argument("--reason")
    parser.add_argument("--actor", required=True)
    args = parser.parse_args()

    username = args.username.strip().lower()
    if args.grant and not (args.reason or "").strip():
        parser.error("--reason est requis avec --grant")

    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, username, center_name, is_active, billing_mode
                FROM training_center_accounts
                WHERE LOWER(username) = %s
                FOR UPDATE
                """,
                (username,),
            )
            rows = cur.fetchall()
            if len(rows) != 1:
                raise SystemExit(
                    f"Refus: attendu exactement un compte centre existant pour {username!r}, trouvé {len(rows)}."
                )
            account = rows[0]
            if not account["is_active"]:
                raise SystemExit("Refus: le compte centre est désactivé.")
            if args.grant:
                cur.execute(
                    """
                    UPDATE training_center_accounts
                    SET billing_mode = 'exempt', billing_exempt_reason = %s,
                        billing_exempt_at = NOW(), billing_exempt_updated_by = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (args.reason.strip(), args.actor.strip(), int(account["id"])),
                )
                state = "exempt"
            else:
                cur.execute(
                    """
                    UPDATE training_center_accounts
                    SET billing_mode = 'stripe_required', billing_exempt_reason = NULL,
                        billing_exempt_at = NULL, billing_exempt_updated_by = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (args.actor.strip(), int(account["id"])),
                )
                state = "stripe_required"
    print(f"Compte centre id={account['id']} username={account['username']} billing_mode={state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
