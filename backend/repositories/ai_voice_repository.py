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
        "calibration_duration_sec",
        "calibration_playback_speed",
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
                   sample_duration_sec, measured_wpm, calibration_status,
                   calibration_reference_key, calibration_word_count,
                   calibration_duration_sec, calibration_playback_speed,
                   calibration_error, calibrated_at,
                   playback_speed, language, fish_state, created_at, updated_at
            FROM ai_voices
            WHERE center_account_id = %s AND status != 'archived'
            ORDER BY updated_at DESC, id DESC
            """ if postgres else """
            SELECT id, center_account_id, name, fish_reference_id, source, status,
                   consent_statement, consent_recording_sha256,
                   consent_recording_duration_sec, sample_sha256,
                   sample_duration_sec, measured_wpm, calibration_status,
                   calibration_reference_key, calibration_word_count,
                   calibration_duration_sec, calibration_playback_speed,
                   calibration_error, calibrated_at,
                   playback_speed, language, fish_state, created_at, updated_at
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
    previous_speed = float(voice.get("playback_speed") or 1.0)
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        reset_calibration = abs(previous_speed - float(playback_speed)) > 0.0001
        cursor.execute(
            """
            UPDATE ai_voices
            SET playback_speed = %s,
                measured_wpm = CASE WHEN %s THEN NULL ELSE measured_wpm END,
                calibration_status = CASE WHEN %s THEN 'pending' ELSE calibration_status END,
                calibration_reference_key = CASE WHEN %s THEN NULL ELSE calibration_reference_key END,
                calibration_word_count = CASE WHEN %s THEN NULL ELSE calibration_word_count END,
                calibration_duration_sec = CASE WHEN %s THEN NULL ELSE calibration_duration_sec END,
                calibration_playback_speed = CASE WHEN %s THEN NULL ELSE calibration_playback_speed END,
                calibration_error = NULL,
                calibrated_at = CASE WHEN %s THEN NULL ELSE calibrated_at END,
                updated_at = %s
            WHERE id = %s AND center_account_id = %s AND status != 'archived'
            """ if postgres else """
            UPDATE ai_voices
            SET playback_speed = ?,
                measured_wpm = CASE WHEN ? THEN NULL ELSE measured_wpm END,
                calibration_status = CASE WHEN ? THEN 'pending' ELSE calibration_status END,
                calibration_reference_key = CASE WHEN ? THEN NULL ELSE calibration_reference_key END,
                calibration_word_count = CASE WHEN ? THEN NULL ELSE calibration_word_count END,
                calibration_duration_sec = CASE WHEN ? THEN NULL ELSE calibration_duration_sec END,
                calibration_playback_speed = CASE WHEN ? THEN NULL ELSE calibration_playback_speed END,
                calibration_error = NULL,
                calibrated_at = CASE WHEN ? THEN NULL ELSE calibrated_at END,
                updated_at = ?
            WHERE id = ? AND center_account_id = ? AND status != 'archived'
            """,
            (
                float(playback_speed),
                reset_calibration,
                reset_calibration,
                reset_calibration,
                reset_calibration,
                reset_calibration,
                reset_calibration,
                reset_calibration,
                _now(postgres=postgres),
                voice_id,
                center_account_id,
            ),
        )
        changed = cursor.rowcount > 0
        conn.commit()
    return get_voice(center_account_id, voice_id) if changed else None


def mark_reference_calibration_running(
    center_account_id: int,
    voice_id: int,
    *,
    reference_key: str,
) -> dict[str, Any] | None:
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE ai_voices
            SET calibration_status = 'running', calibration_reference_key = %s,
                calibration_error = NULL, updated_at = %s
            WHERE id = %s AND center_account_id = %s AND status != 'archived'
            """ if postgres else """
            UPDATE ai_voices
            SET calibration_status = 'running', calibration_reference_key = ?,
                calibration_error = NULL, updated_at = ?
            WHERE id = ? AND center_account_id = ? AND status != 'archived'
            """,
            (reference_key, _now(postgres=postgres), voice_id, center_account_id),
        )
        changed = cursor.rowcount > 0
        conn.commit()
    return get_voice(center_account_id, voice_id) if changed else None


def complete_reference_calibration(
    center_account_id: int,
    voice_id: int,
    *,
    reference_key: str,
    word_count: int,
    duration_sec: float,
    measured_wpm: float,
    playback_speed: float,
) -> dict[str, Any] | None:
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        now = _now(postgres=postgres)
        cursor.execute(
            """
            UPDATE ai_voices
            SET measured_wpm = %s, calibration_status = 'completed',
                calibration_reference_key = %s, calibration_word_count = %s,
                calibration_duration_sec = %s, calibration_playback_speed = %s,
                calibration_error = NULL,
                calibrated_at = %s, updated_at = %s
            WHERE id = %s AND center_account_id = %s AND status != 'archived'
            """ if postgres else """
            UPDATE ai_voices
            SET measured_wpm = ?, calibration_status = 'completed',
                calibration_reference_key = ?, calibration_word_count = ?,
                calibration_duration_sec = ?, calibration_playback_speed = ?,
                calibration_error = NULL,
                calibrated_at = ?, updated_at = ?
            WHERE id = ? AND center_account_id = ? AND status != 'archived'
            """,
            (
                float(measured_wpm),
                reference_key,
                int(word_count),
                float(duration_sec),
                float(playback_speed),
                now,
                now,
                voice_id,
                center_account_id,
            ),
        )
        changed = cursor.rowcount > 0
        conn.commit()
    return get_voice(center_account_id, voice_id) if changed else None


def fail_reference_calibration(
    center_account_id: int,
    voice_id: int,
    error: str,
) -> dict[str, Any] | None:
    with _connection() as (conn, postgres):
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE ai_voices
            SET calibration_status = 'failed', calibration_error = %s,
                updated_at = %s
            WHERE id = %s AND center_account_id = %s AND status != 'archived'
            """ if postgres else """
            UPDATE ai_voices
            SET calibration_status = 'failed', calibration_error = ?,
                updated_at = ?
            WHERE id = ? AND center_account_id = ? AND status != 'archived'
            """,
            (str(error or "")[:500], _now(postgres=postgres), voice_id, center_account_id),
        )
        changed = cursor.rowcount > 0
        conn.commit()
    return get_voice(center_account_id, voice_id) if changed else None


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
            SELECT voice.id, voice.center_account_id, voice.fish_reference_id, voice.playback_speed,
                   voice.measured_wpm, voice.calibration_status,
                   voice.calibration_reference_key, voice.calibration_word_count,
                   voice.calibration_duration_sec, voice.calibration_playback_speed,
                   voice.calibrated_at, voice.name
            FROM platform_config platform
            JOIN ai_voices voice ON voice.id = platform.ai_voice_id
            WHERE platform.id = %s AND voice.status = 'ready'
            """ if postgres else """
            SELECT voice.id, voice.center_account_id, voice.fish_reference_id, voice.playback_speed,
                   voice.measured_wpm, voice.calibration_status,
                   voice.calibration_reference_key, voice.calibration_word_count,
                   voice.calibration_duration_sec, voice.calibration_playback_speed,
                   voice.calibrated_at, voice.name
            FROM platform_config platform
            JOIN ai_voices voice ON voice.id = platform.ai_voice_id
            WHERE platform.id = ? AND voice.status = 'ready'
            """,
            (platform_id,),
        )
        return _voice_dict(cursor.fetchone())
