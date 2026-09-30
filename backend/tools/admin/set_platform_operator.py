#!/usr/bin/env python3
"""Grant or revoke the platform-operator role for one existing PostgreSQL center.

The role (column ``is_platform_operator``) opens the cross-centre order review
inbox, skips the review before ordering and enables the test clock. It is not
the internal ``superadmin`` / ``legacy_admin`` session.

Example (environment loaded from backend/.env unless already set):
  python tools/admin/set_platform_operator.py \
    --username centre@example.com --grant \
    --reason "Opérateur Cadrenza" --actor "prenom.nom"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

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
                SELECT id, username, center_name, is_active, is_platform_operator
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
            # Retirer le rôle reste possible sur un compte désactivé.
            if args.grant and not account["is_active"]:
                raise SystemExit("Refus: le compte centre est désactivé.")
            cur.execute(
                """
                UPDATE training_center_accounts
                SET is_platform_operator = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (bool(args.grant), int(account["id"])),
            )
    print(
        f"Compte centre id={account['id']} username={account['username']} "
        f"is_platform_operator={bool(args.grant)} "
        f"(avant={bool(account['is_platform_operator'])}, "
        f"par={args.actor.strip()!r}, raison={(args.reason or '').strip()!r})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
