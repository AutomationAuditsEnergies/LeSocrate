"""Pure domain rules for version 2 dynamic training-day schedules.

This module intentionally has no database, HTTP, storage, or pipeline
dependency.  It is the canonical boundary between an editable timeline and
the immutable schedule consumed by the content/audio pipeline.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any


SCHEDULE_SCHEMA_VERSION = 2
WORDS_PER_MINUTE = 165.7
COURSE_AUDIO_MARGIN_MINUTES = 0.5
MIN_NEW_MODULE_LEAD_HOURS = 48

MIN_COURSES_PER_DAY = 4
MAX_COURSES_PER_DAY = 10
MIN_COURSE_MINUTES = 35
MAX_COURSE_MINUTES = 90
MIN_QA_MINUTES = 5
MAX_QA_MINUTES = 30
MIN_SHORT_PAUSE_MINUTES = 5
MAX_SHORT_PAUSE_MINUTES = 30
MIN_LUNCH_MINUTES = 60
MAX_LUNCH_MINUTES = 120
MIN_TOTAL_COURSE_MINUTES = 240
MIN_DAY_AMPLITUDE_MINUTES = 360

BLOCK_TYPES = ("course", "qa", "pause")
_TIME_RE = re.compile(r"^(?P<hour>[01]\d|2[0-3]):(?P<minute>[0-5]\d)$")
_MISSING = object()


class ScheduleValidationError(ValueError):
    """A validation failure with a stable machine-readable error code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": str(self),
        }
        if self.path is not None:
            result["path"] = self.path
        if self.details:
            result["details"] = copy.deepcopy(self.details)
        return result


def _raise(
    code: str,
    message: str,
    *,
    path: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    raise ScheduleValidationError(code, message, path=path, details=details)


def _whole_minute(value: Any, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _raise(
            "invalid_minute_value",
            "La valeur doit être un nombre entier de minutes.",
            path=path,
        )
    if not math.isfinite(value) or int(value) != value:
        _raise(
            "invalid_minute_value",
            "La précision autorisée est la minute entière.",
            path=path,
        )
    return int(value)


def _parse_start_minute(block: Mapping[str, Any], *, index: int) -> int:
    start_minute_raw = block.get("start_minute", _MISSING)
    start_time_raw = block.get("start_time", _MISSING)
    path = f"blocks[{index}]"

    if start_minute_raw is _MISSING and start_time_raw is _MISSING:
        _raise(
            "missing_start_time",
            "Chaque bloc doit définir start_time ou start_minute.",
            path=path,
        )

    parsed_from_time: int | None = None
    if start_time_raw is not _MISSING:
        if not isinstance(start_time_raw, str):
            _raise(
                "invalid_start_time",
                "start_time doit respecter le format HH:MM.",
                path=f"{path}.start_time",
            )
        match = _TIME_RE.fullmatch(start_time_raw)
        if match is None:
            _raise(
                "invalid_start_time",
                "start_time doit respecter le format HH:MM entre 00:00 et 23:59.",
                path=f"{path}.start_time",
            )
        parsed_from_time = (
            int(match.group("hour")) * 60 + int(match.group("minute"))
        )

    parsed_from_minute: int | None = None
    if start_minute_raw is not _MISSING:
        parsed_from_minute = _whole_minute(
            start_minute_raw,
            path=f"{path}.start_minute",
        )
        if not 0 <= parsed_from_minute <= 1439:
            _raise(
                "invalid_start_minute",
                "start_minute doit être compris entre 0 et 1439.",
                path=f"{path}.start_minute",
            )

    if (
        parsed_from_time is not None
        and parsed_from_minute is not None
        and parsed_from_time != parsed_from_minute
    ):
        _raise(
            "conflicting_start_time",
            "start_time et start_minute désignent deux horaires différents.",
            path=path,
        )

    return (
        parsed_from_minute
        if parsed_from_minute is not None
        else int(parsed_from_time)
    )


def _read_compatible_field(
    block: Mapping[str, Any],
    editable_name: str,
    canonical_name: str,
    *,
    index: int,
) -> Any:
    editable_value = block.get(editable_name, _MISSING)
    canonical_value = block.get(canonical_name, _MISSING)
    if editable_value is _MISSING and canonical_value is _MISSING:
        _raise(
            f"missing_{editable_name}",
            f"Chaque bloc doit définir {editable_name}.",
            path=f"blocks[{index}].{editable_name}",
        )
    if (
        editable_value is not _MISSING
        and canonical_value is not _MISSING
        and editable_value != canonical_value
    ):
        _raise(
            f"conflicting_{editable_name}",
            f"{editable_name} et {canonical_name} ne correspondent pas.",
            path=f"blocks[{index}]",
        )
    return editable_value if editable_value is not _MISSING else canonical_value


def _normalise_editable_block(
    block: Mapping[str, Any],
    *,
    index: int,
) -> dict[str, Any]:
    if not isinstance(block, Mapping):
        _raise(
            "invalid_block",
            "Chaque bloc doit être un objet.",
            path=f"blocks[{index}]",
        )

    block_type = _read_compatible_field(
        block,
        "type",
        "block_type",
        index=index,
    )
    if block_type not in BLOCK_TYPES:
        _raise(
            "invalid_block_type",
            "Le type de bloc doit être course, qa ou pause.",
            path=f"blocks[{index}].type",
        )

    duration_raw = _read_compatible_field(
        block,
        "duration_min",
        "duration_minutes",
        index=index,
    )
    duration_minutes = _whole_minute(
        duration_raw,
        path=f"blocks[{index}].duration_min",
    )
    if duration_minutes <= 0:
        _raise(
            "invalid_duration",
            "La durée d'un bloc doit être strictement positive.",
            path=f"blocks[{index}].duration_min",
        )

    is_lunch_raw = block.get("is_lunch", _MISSING)
    pause_kind_raw = block.get("pause_kind", _MISSING)
    if is_lunch_raw is not _MISSING and not isinstance(is_lunch_raw, bool):
        _raise(
            "invalid_is_lunch",
            "is_lunch doit être un booléen.",
            path=f"blocks[{index}].is_lunch",
        )
    if pause_kind_raw is not _MISSING and pause_kind_raw not in (
        None,
        "short",
        "lunch",
    ):
        _raise(
            "invalid_pause_kind",
            "pause_kind doit être null, short ou lunch.",
            path=f"blocks[{index}].pause_kind",
        )

    if block_type == "pause":
        if pause_kind_raw is None:
            _raise(
                "invalid_pause_kind",
                "Un bloc pause doit avoir pause_kind short ou lunch.",
                path=f"blocks[{index}].pause_kind",
            )
        if pause_kind_raw is _MISSING:
            is_lunch = bool(is_lunch_raw) if is_lunch_raw is not _MISSING else False
        else:
            is_lunch = pause_kind_raw == "lunch"
            if is_lunch_raw is not _MISSING and bool(is_lunch_raw) != is_lunch:
                _raise(
                    "conflicting_pause_kind",
                    "is_lunch et pause_kind ne correspondent pas.",
                    path=f"blocks[{index}]",
                )
        pause_kind = "lunch" if is_lunch else "short"
    else:
        if is_lunch_raw is True or pause_kind_raw not in (_MISSING, None):
            _raise(
                "lunch_requires_pause",
                "Seul un bloc pause peut être une pause déjeuner.",
                path=f"blocks[{index}]",
            )
        pause_kind = None

    start_minute = _parse_start_minute(block, index=index)
    end_minute = start_minute + duration_minutes
    provided_end_minute = block.get("end_minute", _MISSING)
    if provided_end_minute is not _MISSING:
        parsed_end_minute = _whole_minute(
            provided_end_minute,
            path=f"blocks[{index}].end_minute",
        )
        if not 1 <= parsed_end_minute <= 1440:
            _raise(
                "invalid_end_minute",
                "end_minute doit être compris entre 1 et 1440.",
                path=f"blocks[{index}].end_minute",
            )
        if parsed_end_minute != end_minute:
            _raise(
                "conflicting_end_minute",
                "end_minute ne correspond pas à start_minute + duration_min.",
                path=f"blocks[{index}].end_minute",
            )
    if end_minute > 1440:
        _raise(
            "day_crosses_midnight",
            "Un bloc de journée ne peut pas se terminer après minuit.",
            path=f"blocks[{index}].duration_min",
        )
    return {
        "block_type": block_type,
        "pause_kind": pause_kind,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "duration_minutes": duration_minutes,
        "_source_index": index,
    }


def _validate_duration(block: Mapping[str, Any], *, chronological_index: int) -> None:
    block_type = block["block_type"]
    duration = block["duration_minutes"]
    path = f"blocks[{block['_source_index']}].duration_min"

    if block_type == "course" and not (
        MIN_COURSE_MINUTES <= duration <= MAX_COURSE_MINUTES
    ):
        _raise(
            "course_duration_out_of_range",
            f"Un cours doit durer entre {MIN_COURSE_MINUTES} et "
            f"{MAX_COURSE_MINUTES} minutes.",
            path=path,
            details={"position": chronological_index},
        )
    if block_type == "qa" and not (
        MIN_QA_MINUTES <= duration <= MAX_QA_MINUTES
    ):
        _raise(
            "qa_duration_out_of_range",
            f"Un Q&R doit durer entre {MIN_QA_MINUTES} et "
            f"{MAX_QA_MINUTES} minutes.",
            path=path,
            details={"position": chronological_index},
        )
    if block_type == "pause":
        if block["pause_kind"] == "lunch":
            valid = MIN_LUNCH_MINUTES <= duration <= MAX_LUNCH_MINUTES
            code = "lunch_duration_out_of_range"
            message = (
                f"Une pause déjeuner doit durer entre {MIN_LUNCH_MINUTES} "
                f"et {MAX_LUNCH_MINUTES} minutes."
            )
        else:
            valid = (
                MIN_SHORT_PAUSE_MINUTES
                <= duration
                <= MAX_SHORT_PAUSE_MINUTES
            )
            code = "short_pause_duration_out_of_range"
            message = (
                f"Une pause courte doit durer entre "
                f"{MIN_SHORT_PAUSE_MINUTES} et "
                f"{MAX_SHORT_PAUSE_MINUTES} minutes."
            )
        if not valid:
            _raise(
                code,
                message,
                path=path,
                details={"position": chronological_index},
            )


def calculate_course_word_budget(duration_minutes: int) -> int:
    """Return the exact text budget for a course, with a 30-second margin."""

    duration = _whole_minute(duration_minutes, path="duration_minutes")
    if not MIN_COURSE_MINUTES <= duration <= MAX_COURSE_MINUTES:
        _raise(
            "course_duration_out_of_range",
            f"Un cours doit durer entre {MIN_COURSE_MINUTES} et "
            f"{MAX_COURSE_MINUTES} minutes.",
            path="duration_minutes",
        )
    return math.floor(
        (duration - COURSE_AUDIO_MARGIN_MINUTES) * WORDS_PER_MINUTE
    )


# Short alias convenient for prompt/content callers.
course_word_budget = calculate_course_word_budget


def _canonical_hash_payload(days: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build the pedagogical payload, deliberately excluding dates and IDs."""

    canonical_days = []
    for day in days:
        canonical_days.append(
            {
                "blocks": [
                    {
                        "block_type": block["block_type"],
                        "pause_kind": block["pause_kind"],
                        "start_minute": block["start_minute"],
                        "duration_minutes": block["duration_minutes"],
                    }
                    for block in day["blocks"]
                ]
            }
        )
    return {
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "days": canonical_days,
    }


def _hash_days(days: Sequence[Mapping[str, Any]]) -> str:
    encoded = json.dumps(
        _canonical_hash_payload(days),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compile_day_schedule(
    blocks: Sequence[Mapping[str, Any]] | Mapping[str, Any],
) -> dict[str, Any]:
    """Validate an editable timeline and return its canonical V2 schedule.

    Input order is not significant: blocks are compiled chronologically.
    Output positions are one-based and ``block_key`` values are deterministic.
    """

    if isinstance(blocks, Mapping):
        blocks = blocks.get("blocks", _MISSING)
    if (
        blocks is _MISSING
        or isinstance(blocks, (str, bytes))
        or not isinstance(blocks, Sequence)
    ):
        _raise(
            "invalid_blocks",
            "blocks doit être une liste de blocs.",
            path="blocks",
        )
    if not blocks:
        _raise(
            "empty_day",
            "Une journée doit contenir des blocs.",
            path="blocks",
        )

    chronological = sorted(
        (
            _normalise_editable_block(block, index=index)
            for index, block in enumerate(blocks)
        ),
        key=lambda block: (block["start_minute"], block["_source_index"]),
    )

    previous: Mapping[str, Any] | None = None
    expected_cycle = ("course", "qa", "pause")
    for index, block in enumerate(chronological):
        position = index + 1
        _validate_duration(block, chronological_index=position)

        if previous is not None:
            if block["start_minute"] < previous["end_minute"]:
                _raise(
                    "overlapping_blocks",
                    "Les blocs d'une journée ne peuvent pas se chevaucher.",
                    path=f"blocks[{block['_source_index']}].start_minute",
                    details={"position": position},
                )
            if block["start_minute"] > previous["end_minute"]:
                _raise(
                    "gap_between_blocks",
                    "Il ne peut pas y avoir de vide entre deux blocs.",
                    path=f"blocks[{block['_source_index']}].start_minute",
                    details={"position": position},
                )

        expected_type = expected_cycle[index % len(expected_cycle)]
        if block["block_type"] != expected_type:
            _raise(
                "invalid_block_sequence",
                "L'ordre obligatoire est cours, Q&R, pause, puis cours.",
                path=f"blocks[{block['_source_index']}].type",
                details={
                    "position": position,
                    "expected": expected_type,
                    "actual": block["block_type"],
                },
            )
        previous = block

    remainder = len(chronological) % 3
    if remainder not in (0, 2):
        _raise(
            "incomplete_final_sequence",
            "La journée doit se terminer après un Q&R ou une pause finale.",
            path="blocks",
        )

    course_count = sum(
        block["block_type"] == "course" for block in chronological
    )
    if not MIN_COURSES_PER_DAY <= course_count <= MAX_COURSES_PER_DAY:
        _raise(
            "course_count_out_of_range",
            f"Une journée doit contenir entre {MIN_COURSES_PER_DAY} et "
            f"{MAX_COURSES_PER_DAY} cours.",
            path="blocks",
            details={"course_count": course_count},
        )

    lunches = [
        block for block in chronological if block["pause_kind"] == "lunch"
    ]
    if len(lunches) != 1:
        _raise(
            "invalid_lunch_count",
            "Une journée doit contenir exactement une pause déjeuner.",
            path="blocks",
            details={"lunch_count": len(lunches)},
        )
    if chronological[-1]["pause_kind"] == "lunch":
        _raise(
            "lunch_cannot_be_final",
            "La pause finale facultative doit être une pause courte.",
            path=f"blocks[{chronological[-1]['_source_index']}].is_lunch",
        )

    total_course_minutes = sum(
        block["duration_minutes"]
        for block in chronological
        if block["block_type"] == "course"
    )
    if total_course_minutes < MIN_TOTAL_COURSE_MINUTES:
        _raise(
            "insufficient_course_minutes",
            f"Une journée doit contenir au moins "
            f"{MIN_TOTAL_COURSE_MINUTES} minutes de cours.",
            path="blocks",
            details={"total_course_minutes": total_course_minutes},
        )

    start_minute = chronological[0]["start_minute"]
    end_minute = chronological[-1]["end_minute"]
    amplitude_minutes = end_minute - start_minute
    if amplitude_minutes < MIN_DAY_AMPLITUDE_MINUTES:
        _raise(
            "day_amplitude_too_short",
            f"L'amplitude d'une journée doit atteindre au moins "
            f"{MIN_DAY_AMPLITUDE_MINUTES} minutes.",
            path="blocks",
            details={"amplitude_minutes": amplitude_minutes},
        )

    counters = {block_type: 0 for block_type in BLOCK_TYPES}
    current_course_index = 0
    compiled_blocks: list[dict[str, Any]] = []
    for position, block in enumerate(chronological, start=1):
        block_type = block["block_type"]
        counters[block_type] += 1
        if block_type == "course":
            current_course_index += 1
        compiled: dict[str, Any] = {
            "block_type": block_type,
            "pause_kind": block["pause_kind"],
            "position": position,
            "block_key": f"{block_type}_{counters[block_type]:02d}",
            "course_index": current_course_index,
            "start_minute": block["start_minute"],
            "end_minute": block["end_minute"],
            "duration_minutes": block["duration_minutes"],
        }
        if block_type == "course":
            compiled["target_words"] = calculate_course_word_budget(
                block["duration_minutes"]
            )
        compiled_blocks.append(compiled)

    day_without_hash: dict[str, Any] = {
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "blocks": compiled_blocks,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "amplitude_minutes": amplitude_minutes,
        "course_count": course_count,
        "qa_count": sum(
            block["block_type"] == "qa" for block in chronological
        ),
        "pause_count": sum(
            block["block_type"] == "pause" for block in chronological
        ),
        "total_course_minutes": total_course_minutes,
        "audio_file_count": len(compiled_blocks),
        "has_final_pause": compiled_blocks[-1]["block_type"] == "pause",
    }
    day_without_hash["schedule_hash"] = _hash_days([day_without_hash])
    return day_without_hash


def validate_day_schedule(
    blocks: Sequence[Mapping[str, Any]] | Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and return the canonical day (same contract as compilation)."""

    return compile_day_schedule(blocks)


def build_day_audio_manifest(
    day: Sequence[Mapping[str, Any]] | Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return the exact, ordered list of audio files required for a day."""

    # Recompile canonical input too: callers cannot bypass domain validation
    # merely by setting schema_version or block_key themselves.
    compiled_day = compile_day_schedule(day)

    return [
        {
            "position": block["position"],
            "block_key": block["block_key"],
            "block_type": block["block_type"],
            "pause_kind": block["pause_kind"],
            "course_index": block["course_index"],
            "filename": f"{block['block_key']}.mp3",
            "start_minute": block["start_minute"],
            "end_minute": block["end_minute"],
            "duration_minutes": block["duration_minutes"],
        }
        for block in compiled_day["blocks"]
    ]


def _normalise_date(value: Any, *, path: str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            _raise(
                "invalid_date",
                "La date doit respecter le format YYYY-MM-DD.",
                path=path,
            )
        if parsed.isoformat() != value:
            _raise(
                "invalid_date",
                "La date doit respecter le format YYYY-MM-DD.",
                path=path,
            )
        return value
    _raise(
        "invalid_date",
        "La date doit respecter le format YYYY-MM-DD.",
        path=path,
    )


def _normalise_assignments(
    assignments: Mapping[Any, Any] | Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(assignments, Mapping):
        iterable = [
            (raw_date, template_key, f"template_assignments[{raw_date!r}]")
            for raw_date, template_key in assignments.items()
        ]
    elif (
        isinstance(assignments, Sequence)
        and not isinstance(assignments, (str, bytes))
    ):
        iterable = []
        for index, assignment in enumerate(assignments):
            if not isinstance(assignment, Mapping):
                _raise(
                    "invalid_template_assignment",
                    "Chaque affectation doit être un objet.",
                    path=f"template_assignments[{index}]",
                )
            raw_date = assignment.get("date", _MISSING)
            template_key = assignment.get(
                "template_key",
                assignment.get("template_id", _MISSING),
            )
            if raw_date is _MISSING or template_key is _MISSING:
                _raise(
                    "invalid_template_assignment",
                    "Chaque affectation doit définir date et template_key.",
                    path=f"template_assignments[{index}]",
                )
            iterable.append(
                (raw_date, template_key, f"template_assignments[{index}]")
            )
    else:
        _raise(
            "invalid_template_assignments",
            "template_assignments doit être un objet ou une liste.",
            path="template_assignments",
        )

    for raw_date, template_key, path in iterable:
        date_key = _normalise_date(raw_date, path=f"{path}.date")
        if date_key in result:
            _raise(
                "duplicate_template_assignment",
                "Une date ne peut recevoir qu'un seul template.",
                path=path,
                details={"date": date_key},
            )
        if template_key is None:
            _raise(
                "missing_template_assignment",
                "Chaque date doit recevoir exactement un template.",
                path=path,
                details={"date": date_key},
            )
        result[date_key] = template_key
    return result


def compile_module_schedule(
    selected_dates: Sequence[Any],
    template_assignments: Mapping[Any, Any] | Sequence[Mapping[str, Any]],
    templates: Mapping[Any, Any],
) -> dict[str, Any]:
    """Compile chronologically assigned dates into an immutable V2 snapshot.

    Dates remain present for the initial calendar mapping, but are deliberately
    excluded from ``schedule_hash``. Template keys, names, block keys, and
    other technical identifiers are excluded too.
    """

    if (
        isinstance(selected_dates, (str, bytes))
        or not isinstance(selected_dates, Sequence)
        or not selected_dates
    ):
        _raise(
            "invalid_selected_dates",
            "selected_dates doit contenir au moins une date.",
            path="selected_dates",
        )
    if not isinstance(templates, Mapping):
        _raise(
            "invalid_templates",
            "templates doit être un objet indexé par identifiant.",
            path="templates",
        )

    normalised_dates: list[str] = []
    seen_dates: set[str] = set()
    for index, raw_date in enumerate(selected_dates):
        date_key = _normalise_date(raw_date, path=f"selected_dates[{index}]")
        if date_key in seen_dates:
            _raise(
                "duplicate_selected_date",
                "Une même date ne peut être sélectionnée qu'une seule fois.",
                path=f"selected_dates[{index}]",
                details={"date": date_key},
            )
        seen_dates.add(date_key)
        normalised_dates.append(date_key)
    normalised_dates.sort()

    assignments = _normalise_assignments(template_assignments)
    missing_dates = sorted(seen_dates - assignments.keys())
    extra_dates = sorted(assignments.keys() - seen_dates)
    if missing_dates or extra_dates:
        _raise(
            "template_assignment_mismatch",
            "Chaque date sélectionnée doit recevoir exactement un template, "
            "sans affectation supplémentaire.",
            path="template_assignments",
            details={
                "missing_dates": missing_dates,
                "extra_dates": extra_dates,
            },
        )

    compiled_templates: dict[Any, dict[str, Any]] = {}
    days: list[dict[str, Any]] = []
    for day_number, date_key in enumerate(normalised_dates, start=1):
        template_key = assignments[date_key]
        try:
            template_definition = templates[template_key]
        except (KeyError, TypeError):
            _raise(
                "unknown_template",
                "Le template affecté à une journée est introuvable.",
                path=f"template_assignments[{date_key!r}]",
                details={
                    "date": date_key,
                    "template_key": template_key,
                },
            )

        try:
            compiled_template = compiled_templates[template_key]
        except (KeyError, TypeError):
            compiled_template = compile_day_schedule(template_definition)
            try:
                compiled_templates[template_key] = compiled_template
            except TypeError:
                _raise(
                    "invalid_template_key",
                    "L'identifiant d'un template doit être une valeur simple.",
                    details={"template_key": repr(template_key)},
                )

        day = copy.deepcopy(compiled_template)
        day["day_number"] = day_number
        day["date"] = date_key
        day["template_key"] = template_key
        if isinstance(template_definition, Mapping):
            template_name = template_definition.get("name")
            if template_name:
                day["template_name"] = str(template_name)
        days.append(day)

    schedule_hash = _hash_days(days)
    return {
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "schedule_hash": schedule_hash,
        "day_count": len(days),
        "audio_file_count": sum(day["audio_file_count"] for day in days),
        "days": days,
    }


def _coerce_datetime(value: Any, *, path: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    _raise(
        "invalid_datetime",
        "La valeur doit être une date et heure ISO valide.",
        path=path,
    )


def validate_new_module_lead_time(
    validation_at: datetime | str,
    first_start_at: datetime | str,
    *,
    is_reuse: bool = False,
) -> bool:
    """Require 48 real hours before the first course of a new module.

    Reused modules are explicitly exempt because their audio assets already
    exist. Exact equality at 48 hours is accepted.
    """

    if is_reuse:
        return True

    validation = _coerce_datetime(validation_at, path="validation_at")
    first_start = _coerce_datetime(first_start_at, path="first_start_at")
    validation_is_aware = (
        validation.tzinfo is not None and validation.utcoffset() is not None
    )
    first_is_aware = (
        first_start.tzinfo is not None and first_start.utcoffset() is not None
    )
    if validation_is_aware != first_is_aware:
        _raise(
            "mixed_datetime_awareness",
            "validation_at et first_start_at doivent utiliser le même type "
            "de fuseau horaire.",
        )

    if validation_is_aware:
        validation = validation.astimezone(timezone.utc)
        first_start = first_start.astimezone(timezone.utc)

    earliest_start = validation + timedelta(hours=MIN_NEW_MODULE_LEAD_HOURS)
    if first_start < earliest_start:
        _raise(
            "new_module_lead_time_too_short",
            "La première journée d'un nouveau module doit commencer au moins "
            f"{MIN_NEW_MODULE_LEAD_HOURS} heures après la validation.",
            path="first_start_at",
            details={
                "minimum_hours": MIN_NEW_MODULE_LEAD_HOURS,
                "earliest_start_at": earliest_start.isoformat(),
            },
        )
    return True


__all__ = [
    "BLOCK_TYPES",
    "COURSE_AUDIO_MARGIN_MINUTES",
    "MAX_COURSES_PER_DAY",
    "MAX_COURSE_MINUTES",
    "MIN_COURSES_PER_DAY",
    "MIN_COURSE_MINUTES",
    "MIN_DAY_AMPLITUDE_MINUTES",
    "MIN_NEW_MODULE_LEAD_HOURS",
    "MIN_TOTAL_COURSE_MINUTES",
    "SCHEDULE_SCHEMA_VERSION",
    "ScheduleValidationError",
    "WORDS_PER_MINUTE",
    "build_day_audio_manifest",
    "calculate_course_word_budget",
    "compile_day_schedule",
    "compile_module_schedule",
    "course_word_budget",
    "validate_day_schedule",
    "validate_new_module_lead_time",
]
