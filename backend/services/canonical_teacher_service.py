"""Canonical identity and privacy-safe lookup for reusable AI teachers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from typing import Any

from repositories.teacher_asset_repository import find_canonical_reusable_module


CANONICAL_SIGNATURE_VERSION = "teacher-assets-v1"


def _normalized_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _voice_profile(voice_type: str) -> str:
    mode = _normalized_text(voice_type) or "fish_audio"
    if mode == "fish_audio":
        return os.getenv(
            "FISH_AUDIO_VOICE_ID",
            "90a39a3f3c0a45c38502fa1d99dabf96",
        ).strip()
    if mode == "gtts":
        return os.getenv("EDGE_TTS_VOICE", "fr-FR-DeniseNeural").strip()
    return mode


def build_canonical_teacher_signature(
    *,
    rncp_code: str | None,
    tp_name: str,
    total_hours: int,
    nb_days: int,
    voice_type: str,
    generator_version: str | None = None,
) -> dict[str, Any]:
    """Build a stable signature excluding tenant, promotion and calendar data."""
    resolved_generator = str(
        generator_version
        or os.getenv("TEACHER_ASSET_GENERATOR_VERSION", "pipeline-v1")
    ).strip()
    normalized_rncp = re.sub(r"[^A-Z0-9]", "", _normalized_text(rncp_code).upper())
    return {
        "signature_version": CANONICAL_SIGNATURE_VERSION,
        "rncp_code": normalized_rncp,
        "tp_name": _normalized_text(tp_name),
        "total_hours": int(total_hours),
        "nb_days": int(nb_days),
        "language": "fr-FR",
        "voice_type": _normalized_text(voice_type),
        "voice_profile": _voice_profile(voice_type),
        "generator_version": resolved_generator,
    }


def canonical_teacher_fingerprint(signature: dict[str, Any]) -> str:
    payload = json.dumps(
        signature,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def resolve_compatible_canonical_teacher(
    *,
    rncp_code: str | None,
    tp_name: str,
    total_hours: int,
    nb_days: int,
    voice_type: str,
    generator_version: str | None = None,
) -> dict[str, Any] | None:
    """Return an internal compatibility handle, never source-tenant metadata."""
    signature = build_canonical_teacher_signature(
        rncp_code=rncp_code,
        tp_name=tp_name,
        total_hours=total_hours,
        nb_days=nb_days,
        voice_type=voice_type,
        generator_version=generator_version,
    )
    fingerprint = canonical_teacher_fingerprint(signature)
    match = find_canonical_reusable_module(fingerprint)
    if not match:
        return None
    return {
        "module_id": int(match["module_id"]),
        "canonical_fingerprint": fingerprint,
        "canonical_generator_version": match.get("canonical_generator_version"),
        "voice_type": match.get("voice_type"),
        "version": match.get("version"),
        "asset_count": int(match.get("asset_count") or 0),
    }
