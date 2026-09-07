"""Shared validation helpers for SQLite -> PostgreSQL data migrations."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Iterable
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class MigrationValidationError(ValueError):
    """Raised before PostgreSQL receives a value that cannot be migrated safely."""


def timezone_from_name(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(str(name or "").strip())
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise MigrationValidationError(f"Fuseau horaire inconnu: {name!r}") from exc


def normalize_bool(value: Any, *, context: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"0", "false", "no", "off"}:
            return False
        if normalized in {"1", "true", "yes", "on"}:
            return True
    raise MigrationValidationError(f"Booléen invalide pour {context}: {value!r}")


def normalize_timestamp(
    value: Any,
    *,
    assumed_timezone: ZoneInfo,
    context: str,
) -> datetime | None:
    """Return an aware UTC datetime, never a server-timezone-dependent string."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise MigrationValidationError(
                f"Timestamp invalide pour {context}: {value!r}"
            ) from exc
    else:
        raise MigrationValidationError(
            f"Type de timestamp invalide pour {context}: {type(value).__name__}"
        )

    if parsed.tzinfo is None:
        candidates = []
        for fold in (0, 1):
            candidate = parsed.replace(tzinfo=assumed_timezone, fold=fold)
            round_trip = (
                candidate.astimezone(timezone.utc)
                .astimezone(assumed_timezone)
                .replace(tzinfo=None)
            )
            if round_trip == parsed:
                candidates.append(candidate)
        if not candidates:
            raise MigrationValidationError(
                f"Heure locale inexistante (changement DST) pour {context}: {value!r}"
            )
        if len(candidates) == 2 and candidates[0].utcoffset() != candidates[1].utcoffset():
            raise MigrationValidationError(
                f"Heure locale ambiguë (changement DST) pour {context}: {value!r}; "
                "fournissez un offset explicite"
            )
        parsed = candidates[0]
    return parsed.astimezone(timezone.utc)


def normalize_json_text(value: Any, *, context: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            json.loads(value)
        except json.JSONDecodeError as exc:
            raise MigrationValidationError(
                f"JSON invalide pour {context}: {exc.msg} (position {exc.pos})"
            ) from exc
        return value
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise MigrationValidationError(f"JSON invalide pour {context}: {value!r}") from exc


def normalize_uuid(value: Any, *, context: str) -> UUID | None:
    if value is None or value == "":
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise MigrationValidationError(f"UUID invalide pour {context}: {value!r}") from exc


def normalize_date(value: Any, *, context: str) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise MigrationValidationError(f"Date invalide pour {context}: {value!r}") from exc


def normalize_sqlite_row(
    *,
    table: str,
    columns: Iterable[str],
    row: Any,
    bool_columns: set[str] | None = None,
    json_columns: set[str] | None = None,
    timestamp_columns: set[str] | None = None,
    uuid_columns: set[str] | None = None,
    date_columns: set[str] | None = None,
    assumed_timezone: ZoneInfo,
) -> list[Any]:
    bool_columns = bool_columns or set()
    json_columns = json_columns or set()
    timestamp_columns = timestamp_columns or set()
    uuid_columns = uuid_columns or set()
    date_columns = date_columns or set()
    if "id" in row.keys():
        row_id = row["id"]
    elif "platform_id" in row.keys():
        row_id = row["platform_id"]
    else:
        row_id = "?"

    values: list[Any] = []
    for column in columns:
        value = row[column]
        context = f"{table}[{row_id}].{column}"
        if column in bool_columns:
            value = normalize_bool(value, context=context)
        elif column in json_columns:
            value = normalize_json_text(value, context=context)
        elif column in timestamp_columns:
            value = normalize_timestamp(
                value,
                assumed_timezone=assumed_timezone,
                context=context,
            )
        elif column in uuid_columns:
            value = normalize_uuid(value, context=context)
        elif column in date_columns:
            value = normalize_date(value, context=context)
        values.append(value)
    return values
