"""Adapter between immutable day schedules and the existing audio pipeline.

The historic V1 playlist is used only when the persisted folder contract is
explicitly V1. A repository or schema failure must never silently replace a V2
day with the legacy 19-file playlist.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from typing import Any, Iterable


_COURSE_AUDIO_FILENAME_RE = re.compile(r"^(?:cours|course)(?:_|-).+\.mp3$", re.IGNORECASE)


def is_course_audio_filename(value: Any) -> bool:
    """Recognize both historic V1 and canonical V2 teaching-audio names."""
    filename = os.path.basename(str(value or "").split("?", 1)[0].split("#", 1)[0])
    return bool(_COURSE_AUDIO_FILENAME_RE.fullmatch(filename))


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    return {}


def _json_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if isinstance(value, str) and value.strip():
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [dict(item) for item in parsed if isinstance(item, dict)]
    return []


def _block_duration_minutes(block: dict[str, Any]) -> int:
    duration = block.get("duration_minutes")
    if duration is None:
        start = int(block.get("start_minute") or 0)
        end = int(block.get("end_minute") or 0)
        duration = end - start
    duration = int(duration or 0)
    if duration <= 0:
        raise ValueError("Chaque bloc audio doit avoir une durée positive")
    return duration


def build_playlist_items(
    blocks: Iterable[dict[str, Any]],
) -> list[tuple[str, int, str, int]]:
    """Compile canonical V2 blocks into the tuple contract used by TTS.

    Filenames are stable inside one day folder and deliberately independent of
    calendar dates. A locked schedule can therefore be reused on other dates
    without changing any durable asset key.
    """
    from services.dynamic_day_schedule_service import build_day_audio_manifest

    # Recompilation is intentional: an invalid/corrupted snapshot must fail
    # closed before TTS rather than producing a partial learner playlist.
    manifest = build_day_audio_manifest({"blocks": list(blocks)})
    playlist: list[tuple[str, int, str, int]] = []
    for block in manifest:
        block_type = str(block["block_type"])
        duration_sec = int(
            block.get("duration_seconds")
            or int(block["duration_minutes"]) * 60
        )
        course_index = int(block["course_index"])
        filename = str(block["filename"])
        if block_type == "course":
            file_type = "cours"
        elif block_type == "qa":
            file_type = "qa"
        elif block_type == "pause":
            pause_kind = str(block.get("pause_kind") or "short").strip().lower()
            if pause_kind == "lunch":
                file_type = "pause_midi"
            else:
                file_type = "pause"
        elif block_type == "jointure":
            file_type = "jointure"
        else:
            raise ValueError(f"Type de bloc V2 inconnu : {block_type or '(vide)'}")
        playlist.append((filename, duration_sec, file_type, course_index))

    filenames = [item[0] for item in playlist]
    if len(filenames) != len(set(filenames)):
        raise ValueError("Le planning produit des noms de fichiers audio dupliqués")
    return playlist


def _day_from_pipeline_snapshot(row: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = _json_object(
        row.get("schedule_snapshot_json")
        or row.get("schedule_snapshot")
    )
    if int(snapshot.get("schema_version") or row.get("schedule_schema_version") or 1) != 2:
        return None
    folder_position = int(
        row.get("folder_position")
        if row.get("folder_position") is not None
        else row.get("position") or 0
    )
    expected_day_index = folder_position + 1
    days = [
        dict(day)
        for day in snapshot.get("days") or []
        if isinstance(day, dict)
    ]
    return next(
        (
            day
            for day in days
            if int(day.get("day_index") or 0) == expected_day_index
        ),
        days[folder_position] if 0 <= folder_position < len(days) else None,
    )


def resolve_folder_playlist(folder_id: int) -> dict[str, Any]:
    """Resolve one folder to V2 day manifest, falling back exactly to V1."""
    from repositories.day_schedule_repository import (
        get_module_day_for_folder,
        get_schedule_snapshot_for_folder,
    )
    from services.playlist_tts_service import PLAYLIST_SPEC

    folder_id = int(folder_id)
    legacy_sqlite_schema = False
    try:
        module_day = get_module_day_for_folder(folder_id)
    except sqlite3.OperationalError as exc:
        # Some historic SQLite databases predate the durable V2 table.  That
        # precise schema gap identifies a legacy store; every other repository
        # failure still propagates so a V2 playlist can never silently become
        # the static V1 playlist.
        if "no such table: formation_module_days" not in str(exc).lower():
            raise
        legacy_sqlite_schema = True
        module_day = None
    if module_day:
        blocks = _json_list(
            module_day.get("blocks_snapshot_json")
            or module_day.get("blocks")
        )
        return {
            "schema_version": 2,
            "source": "module_day",
            "folder_id": folder_id,
            "module_day_id": module_day.get("id") or module_day.get("module_day_id"),
            "day_index": int(module_day.get("day_index") or 0) or None,
            "schedule_hash": module_day.get("schedule_hash"),
            "blocks": blocks,
            "playlist_items": build_playlist_items(blocks),
        }

    try:
        pipeline_row = get_schedule_snapshot_for_folder(folder_id)
    except sqlite3.OperationalError as exc:
        missing_column = "no such column: j.schedule_" in str(exc).lower()
        if not (legacy_sqlite_schema and missing_column):
            raise
        pipeline_row = {"schedule_schema_version": 1}
    schedule_day = _day_from_pipeline_snapshot(pipeline_row or {})
    if schedule_day:
        blocks = _json_list(
            schedule_day.get("blocks")
            or schedule_day.get("blocks_snapshot_json")
        )
        return {
            "schema_version": 2,
            "source": "pipeline_snapshot",
            "folder_id": folder_id,
            "module_day_id": None,
            "day_index": int(schedule_day.get("day_index") or 0) or None,
            "schedule_hash": (
                schedule_day.get("schedule_hash")
                or (pipeline_row or {}).get("schedule_hash")
            ),
            "blocks": blocks,
            "playlist_items": build_playlist_items(blocks),
        }

    if int((pipeline_row or {}).get("schedule_schema_version") or 1) == 2:
        raise ValueError(
            "Le dossier V2 ne possède aucune journée valide dans son snapshot verrouillé"
        )

    return {
        "schema_version": 1,
        "source": "legacy",
        "folder_id": folder_id,
        "module_day_id": None,
        "day_index": None,
        "schedule_hash": None,
        "blocks": [],
        "playlist_items": list(PLAYLIST_SPEC),
    }


def required_audio_filenames(folder_id: int) -> set[str]:
    return {
        item[0]
        for item in resolve_folder_playlist(int(folder_id))["playlist_items"]
    }


def course_durations_minutes(folder_id: int) -> dict[int, float]:
    return {
        int(bloc_number): float(duration_sec) / 60.0
        for _filename, duration_sec, file_type, bloc_number
        in resolve_folder_playlist(int(folder_id))["playlist_items"]
        if file_type == "cours"
    }
