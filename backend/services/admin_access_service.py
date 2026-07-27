"""Server-side permissions for authenticated training-centre accounts.

Permissions are deliberately reloaded from the authoritative database for
every protected request. A revoked permission therefore takes effect even
when the browser still holds a valid signed authentication token.
"""

from database.db import get_db_connection
from database.postgres import postgres_enabled
from repositories.core_repository import get_training_center_by_id
from utils.logger import get_logger

logger = get_logger(__name__)

FORMATION_PIPELINE_PERMISSION = "formation_pipeline"


def _empty_permissions() -> dict[str, bool]:
    return {FORMATION_PIPELINE_PERMISSION: False}


def permissions_from_account(account_type, account) -> dict[str, bool]:
    permissions = _empty_permissions()
    if str(account_type or "").strip().lower() != "training_center":
        return permissions
    if not account or not bool(account.get("is_active")):
        return permissions
    permissions[FORMATION_PIPELINE_PERMISSION] = bool(
        account.get("pipeline_access_enabled")
    )
    return permissions


def _sqlite_training_center_access(account_id: int) -> dict | None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT id, username, is_active, pipeline_access_enabled
            FROM training_center_accounts
            WHERE id = ?
            """,
            (account_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None
    return {
        "id": row[0],
        "username": row[1],
        "is_active": bool(row[2]),
        "pipeline_access_enabled": bool(row[3]),
    }


def get_admin_permissions(account_type, account_id) -> dict[str, bool]:
    """Return the current permissions for one authenticated admin account.

    Only database-backed ``training_center`` accounts can receive product
    permissions. Legacy/superadmin sessions intentionally receive none.
    Invalid or unavailable account data fails closed.
    """

    permissions = _empty_permissions()
    if str(account_type or "").strip().lower() != "training_center":
        return permissions
    if account_id is None or isinstance(account_id, bool):
        return permissions

    try:
        normalized_id = int(account_id)
    except (TypeError, ValueError):
        return permissions
    if normalized_id <= 0:
        return permissions

    try:
        account = (
            get_training_center_by_id(normalized_id)
            if postgres_enabled()
            else _sqlite_training_center_access(normalized_id)
        )
    except Exception:
        logger.warning(
            "ADMIN_PERMISSION_LOOKUP_FAILED account_id=%s",
            normalized_id,
            exc_info=True,
        )
        return permissions

    return permissions_from_account(account_type, account)


def can_access_formation_pipeline(account_type, account_id) -> bool:
    return get_admin_permissions(account_type, account_id)[
        FORMATION_PIPELINE_PERMISSION
    ]
