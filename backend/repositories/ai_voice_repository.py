"""Tenant-scoped persistence for Fish Audio voice models."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any

from config import DATABASE_BACKEND, FRANCE_TZ, PIPELINE_DATABASE_BACKEND
from database.db import get_db_connection
from database.postgres import get_postgres_connection


POSTGRES_BACKENDS = {"postgres", "postgresql", "supabase"}


def ai_voice_store_is_postgres() -> bool:
    return (
        DATABASE_BACKEND in POSTGRES_BACKENDS
        or PIPELINE_DATABASE_BACKEND in POSTGRES_BACKENDS
    )


@contextmanager
def _connection():
    if ai_voice_store_is_postgres():
        with get_postgres_connection() as conn:
            yield conn, True
        return
    conn = get_db_connection()
    conn.row_factory = __import__("sqlite3").Row
    try:
        yield conn, False
    finally:
        conn.close()


def _now(*, postgres: bool):
    value = datetime.now(FRANCE_TZ)
    return value if postgres else value.strftime("%Y-%m-%d %H:%M:%S")


def _voice_dict(row) -> dict[str, Any] | None:
    if row is None:
        return None
    voice = dict(row)
    for key in (
        "consent_recording_duration_sec",
        "sample_duration_sec",
        "measured_wpm",
        "playback_speed",
    ):
        voice[key] = float(voice[key]) if voice.get(key) is not None else None
    return voice


def list_voices(center_account_id: int) -> list[dict[str, Any]]:
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, center_account_id, name, fish_reference_id, source, status,
                   consent_statement, consent_recording_sha256,
                   consent_recording_duration_sec, sample_sha256,
                   sample_duration_sec, measured_wpm, playback_speed, language,
                   fish_state, created_at, updated_at
            FROM ai_voices
            WHERE center_account_id = %s AND status != 'archived'
            ORDER BY updated_at DESC, id DESC
            """ if postgres else """
            SELECT id, center_account_id, name, fish_reference_id, source, status,
                   consent_statement, consent_recording_sha256,
                   consent_recording_duration_sec, sample_sha256,
                   sample_duration_sec, measured_wpm, playback_speed, language,
                   fish_state, created_at, updated_at
            FROM ai_voices
            WHERE center_account_id = ? AND status != 'archived'
            ORDER BY updated_at DESC, id DESC
            """,
            (center_account_id,),
        )
        return [_voice_dict(row) for row in cursor.fetchall()]


def get_voice(center_account_id: int, voice_id: int) -> dict[str, Any] | None:
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM ai_voices WHERE id = %s AND center_account_id = %s"
            if postgres else
            "SELECT * FROM ai_voices WHERE id = ? AND center_account_id = ?",
            (voice_id, center_account_id),
        )
        return _voice_dict(cursor.fetchone())


def create_voice(
    center_account_id: int,
    *,
    name: str,
    fish_reference_id: str,
    source: str,
    consent_statement: str,
    consent_recording_sha256: str | None = None,
    consent_recording_duration_sec: float | None = None,
    sample_sha256: str | None = None,
    sample_duration_sec: float | None = None,
    language: str = "fr",
    fish_state: str | None = None,
) -> dict[str, Any]:
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        now = _now(postgres=postgres)
        values = (
            center_account_id,
            name,
            fish_reference_id,
            source,
            consent_statement,
            consent_recording_sha256,
            consent_recording_duration_sec,
            sample_sha256,
            sample_duration_sec,
            language,
            fish_state,
            now,
            now,
        )
        if postgres:
            cursor.execute(
                """
                INSERT INTO ai_voices (
                    center_account_id, name, fish_reference_id, source, status,
                    consent_statement, consent_recording_sha256,
                    consent_recording_duration_sec, sample_sha256,
                    sample_duration_sec, language, fish_state, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, 'ready', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                values,
            )
            voice_id = cursor.fetchone()["id"]
        else:
            cursor.execute(
                """
                INSERT INTO ai_voices (
                    center_account_id, name, fish_reference_id, source, status,
                    consent_statement, consent_recording_sha256,
                    consent_recording_duration_sec, sample_sha256,
                    sample_duration_sec, language, fish_state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'ready', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            voice_id = cursor.lastrowid
        conn.commit()
    return get_voice(center_account_id, int(voice_id))


def update_calibration(
    center_account_id: int,
    voice_id: int,
    *,
    measured_wpm: float,
    playback_speed: float,
) -> dict[str, Any] | None:
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE ai_voices
            SET measured_wpm = %s, playback_speed = %s, updated_at = %s
            WHERE id = %s AND center_account_id = %s AND status != 'archived'
            """ if postgres else """
            UPDATE ai_voices
            SET measured_wpm = ?, playback_speed = ?, updated_at = ?
            WHERE id = ? AND center_account_id = ? AND status != 'archived'
            """,
            (
                measured_wpm,
                playback_speed,
                _now(postgres=postgres),
                voice_id,
                center_account_id,
            ),
        )
        changed = cursor.rowcount > 0
        conn.commit()
    return get_voice(center_account_id, voice_id) if changed else None


def update_speed(
    center_account_id: int,
    voice_id: int,
    playback_speed: float,
) -> dict[str, Any] | None:
    voice = get_voice(center_account_id, voice_id)
    if voice is None:
        return None
    return update_calibration(
        center_account_id,
        voice_id,
        measured_wpm=float(voice.get("measured_wpm") or 0.0),
        playback_speed=playback_speed,
    )


def archive_voice(center_account_id: int, voice_id: int) -> bool:
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE ai_voices SET status = 'archived', updated_at = %s
            WHERE id = %s AND center_account_id = %s
            """ if postgres else """
            UPDATE ai_voices SET status = 'archived', updated_at = ?
            WHERE id = ? AND center_account_id = ?
            """,
            (_now(postgres=postgres), voice_id, center_account_id),
        )
        changed = cursor.rowcount > 0
        conn.commit()
        return changed


def assign_voice_to_platform(
    center_account_id: int,
    platform_id: int,
    voice_id: int | None,
) -> bool:
    if voice_id is not None and get_voice(center_account_id, voice_id) is None:
        return False
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE platform_config SET ai_voice_id = %s, updated_at = %s
            WHERE id = %s AND center_account_id = %s
            """ if postgres else """
            UPDATE platform_config SET ai_voice_id = ?, updated_at = ?
            WHERE id = ? AND center_account_id = ?
            """,
            (voice_id, _now(postgres=postgres), platform_id, center_account_id),
        )
        changed = cursor.rowcount > 0
        conn.commit()
        return changed


def get_platform_voice_settings(platform_id: int) -> dict[str, Any] | None:
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT voice.id, voice.fish_reference_id, voice.playback_speed,
                   voice.measured_wpm, voice.name
            FROM platform_config platform
            JOIN ai_voices voice ON voice.id = platform.ai_voice_id
            WHERE platform.id = %s AND voice.status = 'ready'
            """ if postgres else """
            SELECT voice.id, voice.fish_reference_id, voice.playback_speed,
                   voice.measured_wpm, voice.name
            FROM platform_config platform
            JOIN ai_voices voice ON voice.id = platform.ai_voice_id
            WHERE platform.id = ? AND voice.status = 'ready'
            """,
            (platform_id,),
        )
        return _voice_dict(cursor.fetchone())
