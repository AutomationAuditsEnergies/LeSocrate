import copy
import math
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.dynamic_day_schedule_service import (  # noqa: E402
    ScheduleValidationError,
    build_day_audio_manifest,
    calculate_course_word_budget,
    compile_day_schedule,
    compile_module_schedule,
    validate_new_module_lead_time,
)


def _timeline(spec=(("course", 60, None),), *, start_minute=9 * 60 + 7):
    blocks = []
    cursor = start_minute
    for block_type, duration, pause_kind in spec:
        blocks.append(
            {
                "type": block_type,
                "start_minute": cursor,
                "duration_min": duration,
                "is_lunch": block_type == "pause" and pause_kind == "lunch",
            }
        )
        cursor += duration
    return blocks


class DynamicDayScheduleTest(unittest.TestCase):
    def assertScheduleError(self, code, callable_, *args, **kwargs):
        with self.assertRaises(ScheduleValidationError) as raised:
            callable_(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def test_compiles_a_single_course_day(self):
        compiled = compile_day_schedule(_timeline())

        self.assertEqual(compiled["schema_version"], 2)
        self.assertEqual(compiled["course_count"], 1)
        self.assertEqual(compiled["qa_count"], 0)
        self.assertEqual(compiled["pause_count"], 0)
        self.assertEqual(compiled["jointure_count"], 0)
        self.assertEqual(compiled["audio_file_count"], 1)
        self.assertEqual(compiled["total_course_minutes"], 60)
        self.assertEqual(compiled["amplitude_minutes"], 60)
        self.assertEqual(compiled["ending_block_type"], "course")
        self.assertFalse(compiled["has_final_pause"])

        first = compiled["blocks"][0]
        self.assertEqual(first["block_key"], "course_01")
        self.assertEqual(first["course_index"], 1)
        self.assertEqual(first["start_minute"], 9 * 60 + 7)
        self.assertEqual(first["end_minute"], 10 * 60 + 7)
        self.assertEqual(first["target_words"], 9859)

    def test_accepts_every_confirmed_optional_order(self):
        cases = (
            (("course", 60, None), ("qa", 10, None)),
            (
                ("course", 60, None),
                ("qa", 10, None),
                ("pause", 10, "short"),
                ("course", 60, None),
            ),
            (("course", 60, None), ("pause", 10, "short"), ("qa", 10, None)),
            (("course", 60, None), ("course", 60, None)),
        )
        for spec in cases:
            with self.subTest(spec=spec):
                compiled = compile_day_schedule(_timeline(spec))
                self.assertEqual(
                    compiled["course_count"],
                    sum(item[0] == "course" for item in spec),
                )

    def test_accepts_one_to_ten_courses_and_inserts_hidden_jointures(self):
        one = compile_day_schedule(_timeline())
        ten = compile_day_schedule(_timeline((("course", 35, None),) * 10))

        self.assertEqual(one["course_count"], 1)
        self.assertEqual(ten["course_count"], 10)
        self.assertEqual(ten["jointure_count"], 9)
        self.assertEqual(ten["audio_file_count"], 19)

    def test_rejects_a_day_without_course_or_with_eleven_courses(self):
        self.assertScheduleError(
            "invalid_block_sequence",
            compile_day_schedule,
            _timeline((("qa", 10, None),)),
        )
        self.assertScheduleError(
            "course_count_out_of_range",
            compile_day_schedule,
            _timeline((("course", 35, None),) * 11),
        )

    def test_course_word_budget_keeps_the_thirty_second_margin(self):
        for duration in (35, 45, 60, 90):
            self.assertEqual(
                calculate_course_word_budget(duration),
                math.floor((duration - 0.5) * 165.7),
            )
        self.assertEqual(
            calculate_course_word_budget(60, words_per_minute=120),
            math.floor(59.5 * 120),
        )

    def test_enforces_confirmed_duration_bounds(self):
        invalid_cases = (
            ((("course", 34, None),), "course_duration_out_of_range"),
            ((("course", 91, None),), "course_duration_out_of_range"),
            ((("course", 60, None), ("qa", 9, None)), "qa_duration_out_of_range"),
            ((("course", 60, None), ("qa", 31, None)), "qa_duration_out_of_range"),
            (
                (("course", 60, None), ("pause", 9, "short"), ("course", 60, None)),
                "short_pause_duration_out_of_range",
            ),
            (
                (("course", 60, None), ("pause", 31, "short"), ("course", 60, None)),
                "short_pause_duration_out_of_range",
            ),
            (
                (("course", 60, None), ("pause", 59, "lunch"), ("course", 60, None)),
                "lunch_duration_out_of_range",
            ),
            (
                (("course", 60, None), ("pause", 181, "lunch"), ("course", 60, None)),
                "lunch_duration_out_of_range",
            ),
        )
        for spec, code in invalid_cases:
            with self.subTest(code=code, spec=spec):
                self.assertScheduleError(code, compile_day_schedule, _timeline(spec))

    def test_lunch_is_optional_but_unique(self):
        self.assertEqual(compile_day_schedule(_timeline())["pause_count"], 0)
        compiled = compile_day_schedule(
            _timeline(
                (("course", 60, None), ("pause", 180, "lunch"), ("course", 60, None))
            )
        )
        self.assertEqual(compiled["pause_count"], 1)

        self.assertScheduleError(
            "invalid_lunch_count",
            compile_day_schedule,
            _timeline(
                (
                    ("course", 35, None),
                    ("pause", 60, "lunch"),
                    ("course", 35, None),
                    ("pause", 60, "lunch"),
                    ("course", 35, None),
                )
            ),
        )

    def test_day_must_start_with_course_and_cannot_end_with_pause(self):
        self.assertScheduleError(
            "invalid_block_sequence",
            compile_day_schedule,
            _timeline((("qa", 10, None), ("course", 60, None))),
        )
        self.assertScheduleError(
            "pause_cannot_be_final",
            compile_day_schedule,
            _timeline((("course", 60, None), ("pause", 10, "short"))),
        )
        self.assertEqual(
            compile_day_schedule(
                _timeline((("course", 60, None), ("qa", 10, None)))
            )["ending_block_type"],
            "qa",
        )

    def test_rejects_repeated_auxiliary_types(self):
        self.assertScheduleError(
            "duplicate_auxiliary_block",
            compile_day_schedule,
            _timeline((("course", 60, None), ("qa", 10, None), ("qa", 10, None))),
        )
        self.assertScheduleError(
            "duplicate_auxiliary_block",
            compile_day_schedule,
            _timeline(
                (
                    ("course", 60, None),
                    ("pause", 10, "short"),
                    ("pause", 10, "short"),
                    ("course", 60, None),
                )
            ),
        )

    def test_rejects_gap_and_overlap(self):
        gap = _timeline((("course", 60, None), ("qa", 10, None)))
        gap[1]["start_minute"] += 1
        self.assertScheduleError("gap_between_blocks", compile_day_schedule, gap)

        overlap = _timeline((("course", 60, None), ("qa", 10, None)))
        overlap[1]["start_minute"] -= 1
        self.assertScheduleError("overlapping_blocks", compile_day_schedule, overlap)

    def test_accepts_hh_mm_and_sorts_chronologically(self):
        blocks = _timeline((("course", 60, None), ("qa", 10, None)))
        for block in blocks:
            hour, minute = divmod(block.pop("start_minute"), 60)
            block["start_time"] = f"{hour:02d}:{minute:02d}"
        blocks.reverse()

        compiled = compile_day_schedule(blocks)
        self.assertEqual(compiled["blocks"][0]["block_type"], "course")
        self.assertEqual(compiled["blocks"][0]["start_minute"], 9 * 60 + 7)

    def test_rejects_conflicting_or_fractional_times(self):
        conflicting = _timeline()
        conflicting[0]["start_time"] = "09:08"
        self.assertScheduleError("conflicting_start_time", compile_day_schedule, conflicting)

        fractional = _timeline()
        fractional[0]["duration_min"] = 60.5
        self.assertScheduleError("invalid_minute_value", compile_day_schedule, fractional)

        canonical = compile_day_schedule(_timeline())
        canonical["blocks"][0]["end_minute"] += 1
        self.assertScheduleError("conflicting_end_minute", compile_day_schedule, canonical)

    def test_day_can_end_exactly_at_midnight_but_not_after(self):
        accepted = compile_day_schedule(_timeline(start_minute=23 * 60))
        self.assertEqual(accepted["end_minute"], 1440)
        self.assertScheduleError(
            "day_crosses_midnight",
            compile_day_schedule,
            _timeline(start_minute=23 * 60 + 1),
        )

    def test_audio_manifest_inserts_jointure_only_between_adjacent_courses(self):
        compiled = compile_day_schedule(
            _timeline(
                (("course", 60, None), ("course", 45, None), ("qa", 10, None))
            )
        )
        manifest = build_day_audio_manifest(compiled)

        self.assertEqual(
            [item["filename"] for item in manifest],
            [
                "course_01.mp3",
                "jointure_01_02.mp3",
                "course_02.mp3",
                "qa_01.mp3",
            ],
        )
        jointure = manifest[1]
        self.assertTrue(jointure["technical"])
        self.assertEqual(jointure["duration_minutes"], 0)
        self.assertEqual(jointure["duration_seconds"], 10)

    def test_canonical_output_can_be_revalidated_without_loss(self):
        first = compile_day_schedule(
            _timeline((("course", 60, None), ("qa", 10, None)))
        )
        self.assertEqual(first, compile_day_schedule(first))

    def test_pause_kind_null_is_reserved_for_non_pause_blocks(self):
        blocks = _timeline(
            (("course", 60, None), ("pause", 10, "short"), ("course", 60, None))
        )
        blocks[1].pop("is_lunch")
        blocks[1]["pause_kind"] = None
        self.assertScheduleError("invalid_pause_kind", compile_day_schedule, blocks)

    def test_module_compilation_sorts_dates_and_requires_one_template_each(self):
        templates = {"simple": {"name": "Une heure", "blocks": _timeline()}}
        snapshot = compile_module_schedule(
            ["2026-09-03", "2026-09-01"],
            {"2026-09-01": "simple", "2026-09-03": "simple"},
            templates,
        )

        self.assertEqual(snapshot["day_count"], 2)
        self.assertEqual(
            [day["date"] for day in snapshot["days"]],
            ["2026-09-01", "2026-09-03"],
        )
        self.assertEqual(snapshot["audio_file_count"], 2)
        self.assertEqual(len(snapshot["schedule_hash"]), 64)

    def test_module_hash_ignores_dates_and_names_but_tracks_layout(self):
        layout = _timeline()
        first = compile_module_schedule(
            ["2026-09-01"],
            {"2026-09-01": "a"},
            {"a": {"name": "A", "blocks": layout}},
        )
        second = compile_module_schedule(
            ["2027-01-12"],
            {"2027-01-12": 99},
            {99: {"name": "B", "blocks": copy.deepcopy(layout)}},
        )
        third = compile_module_schedule(
            ["2027-01-12"],
            {"2027-01-12": "c"},
            {"c": _timeline((("course", 61, None),))},
        )
        self.assertEqual(first["schedule_hash"], second["schedule_hash"])
        self.assertNotEqual(first["schedule_hash"], third["schedule_hash"])

    def test_module_rejects_missing_or_extra_assignment(self):
        error = self.assertScheduleError(
            "template_assignment_mismatch",
            compile_module_schedule,
            ["2026-09-01", "2026-09-03"],
            {"2026-09-01": "simple", "2026-09-05": "simple"},
            {"simple": _timeline()},
        )
        self.assertEqual(error.details["missing_dates"], ["2026-09-03"])
        self.assertEqual(error.details["extra_dates"], ["2026-09-05"])

    def test_new_module_lead_time_is_twenty_four_exact_hours(self):
        validation_at = datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc)
        self.assertTrue(
            validate_new_module_lead_time(
                validation_at, validation_at + timedelta(hours=24)
            )
        )
        self.assertScheduleError(
            "new_module_lead_time_too_short",
            validate_new_module_lead_time,
            validation_at,
            validation_at + timedelta(hours=23, minutes=59),
        )
        self.assertTrue(
            validate_new_module_lead_time(
                validation_at,
                validation_at + timedelta(minutes=1),
                is_reuse=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
