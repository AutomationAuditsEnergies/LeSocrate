#!/usr/bin/env python3
"""Grant or revoke formation-pipeline access for one PostgreSQL centre."""

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
    args = parser.parse_args()

    username = args.username.strip().lower()
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, username, center_name, is_active
                FROM training_center_accounts
                WHERE LOWER(username) = %s
                FOR UPDATE
                """,
                (username,),
            )
            rows = cur.fetchall()
            if len(rows) != 1:
                raise SystemExit(
                    "Refus: attendu exactement un compte centre existant pour "
                    f"{username!r}, trouvé {len(rows)}."
                )
            account = rows[0]
            if args.grant and not account["is_active"]:
                raise SystemExit("Refus: le compte centre est désactivé.")

            enabled = bool(args.grant)
            cur.execute(
                """
                UPDATE training_center_accounts
                SET pipeline_access_enabled = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (enabled, int(account["id"])),
            )

    state = "accordé" if enabled else "révoqué"
    print(
        "Accès formation pipeline "
        f"{state}: id={account['id']} username={account['username']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
