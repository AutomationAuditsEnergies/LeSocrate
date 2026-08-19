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
    MIN_NEW_MODULE_LEAD_HOURS,
    ScheduleValidationError,
    build_day_audio_manifest,
    calculate_course_word_budget,
    compile_day_schedule,
    compile_module_schedule,
    validate_new_module_lead_time,
)


def _valid_day(
    *,
    start_minute=9 * 60 + 7,
    course_durations=(60, 60, 60, 60),
    qa_duration=15,
    short_pause_duration=15,
    lunch_duration=60,
    lunch_after_course=2,
    final_pause=False,
):
    blocks = []
    cursor = start_minute
    for course_index, course_duration in enumerate(course_durations, start=1):
        blocks.append(
            {
                "type": "course",
                "start_minute": cursor,
                "duration_min": course_duration,
                "is_lunch": False,
            }
        )
        cursor += course_duration
        blocks.append(
            {
                "type": "qa",
                "start_minute": cursor,
                "duration_min": qa_duration,
                "is_lunch": False,
            }
        )
        cursor += qa_duration
        if course_index < len(course_durations) or final_pause:
            is_lunch = course_index == lunch_after_course
            duration = lunch_duration if is_lunch else short_pause_duration
            blocks.append(
                {
                    "type": "pause",
                    "start_minute": cursor,
                    "duration_min": duration,
                    "is_lunch": is_lunch,
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

    def test_compiles_free_minute_timeline_to_canonical_fields(self):
        compiled = compile_day_schedule(_valid_day())

        self.assertEqual(compiled["schema_version"], 2)
        self.assertEqual(compiled["course_count"], 4)
        self.assertEqual(compiled["qa_count"], 4)
        self.assertEqual(compiled["pause_count"], 3)
        self.assertEqual(compiled["audio_file_count"], 11)
        self.assertEqual(compiled["start_minute"], 9 * 60 + 7)
        self.assertEqual(compiled["amplitude_minutes"], 390)
        self.assertFalse(compiled["has_final_pause"])

        first = compiled["blocks"][0]
        self.assertEqual(
            {
                key: first[key]
                for key in (
                    "block_type",
                    "pause_kind",
                    "position",
                    "block_key",
                    "course_index",
                    "start_minute",
                    "end_minute",
                    "duration_minutes",
                )
            },
            {
                "block_type": "course",
                "pause_kind": None,
                "position": 1,
                "block_key": "course_01",
                "course_index": 1,
                "start_minute": 9 * 60 + 7,
                "end_minute": 10 * 60 + 7,
                "duration_minutes": 60,
            },
        )
        self.assertEqual(first["target_words"], 9859)

    def test_accepts_hh_mm_and_sorts_blocks_chronologically(self):
        blocks = _valid_day(start_minute=9 * 60 + 7)
        for block in blocks:
            hour, minute = divmod(block.pop("start_minute"), 60)
            block["start_time"] = f"{hour:02d}:{minute:02d}"
        blocks.reverse()

        compiled = compile_day_schedule(blocks)

        self.assertEqual(compiled["blocks"][0]["start_minute"], 9 * 60 + 7)
        self.assertEqual(
            [block["position"] for block in compiled["blocks"]],
            list(range(1, 12)),
        )

    def test_course_word_budget_always_removes_exactly_thirty_seconds(self):
        for duration in (35, 45, 60, 90):
            self.assertEqual(
                calculate_course_word_budget(duration),
                math.floor((duration - 0.5) * 165.7),
            )

    def test_course_word_budget_accepts_a_voice_specific_rate(self):
        self.assertEqual(
            calculate_course_word_budget(60, words_per_minute=120),
            math.floor(59.5 * 120),
        )

    def test_final_short_pause_is_optional(self):
        without_final = compile_day_schedule(_valid_day(final_pause=False))
        with_final = compile_day_schedule(_valid_day(final_pause=True))

        self.assertEqual(without_final["audio_file_count"], 3 * 4 - 1)
        self.assertEqual(with_final["audio_file_count"], 3 * 4)
        self.assertFalse(without_final["has_final_pause"])
        self.assertTrue(with_final["has_final_pause"])
        self.assertEqual(with_final["blocks"][-1]["pause_kind"], "short")

    def test_accepts_four_and_ten_courses(self):
        four = compile_day_schedule(_valid_day(course_durations=(60,) * 4))
        ten = compile_day_schedule(_valid_day(course_durations=(35,) * 10))

        self.assertEqual(four["course_count"], 4)
        self.assertEqual(ten["course_count"], 10)
        self.assertEqual(ten["audio_file_count"], 29)

    def test_accepts_exact_duration_and_amplitude_boundaries(self):
        exact_amplitude = compile_day_schedule(
            _valid_day(
                course_durations=(60,) * 4,
                qa_duration=10,
                short_pause_duration=10,
                lunch_duration=60,
            )
        )
        minimum_durations = compile_day_schedule(
            _valid_day(
                course_durations=(35,) * 7,
                qa_duration=5,
                short_pause_duration=5,
                lunch_duration=60,
            )
        )
        maximum_durations = compile_day_schedule(
            _valid_day(
                course_durations=(90,) * 4,
                qa_duration=30,
                short_pause_duration=30,
                lunch_duration=120,
            )
        )

        self.assertEqual(exact_amplitude["amplitude_minutes"], 360)
        self.assertEqual(exact_amplitude["total_course_minutes"], 240)
        self.assertEqual(minimum_durations["course_count"], 7)
        self.assertEqual(maximum_durations["blocks"][0]["duration_minutes"], 90)

    def test_rejects_three_or_eleven_courses(self):
        self.assertScheduleError(
            "course_count_out_of_range",
            compile_day_schedule,
            _valid_day(course_durations=(90,) * 3),
        )
        self.assertScheduleError(
            "course_count_out_of_range",
            compile_day_schedule,
            _valid_day(course_durations=(35,) * 11),
        )

    def test_rejects_course_duration_outside_35_to_90_minutes(self):
        too_short = _valid_day()
        too_short[0]["duration_min"] = 34
        self._restitch(too_short)
        self.assertScheduleError(
            "course_duration_out_of_range",
            compile_day_schedule,
            too_short,
        )

        too_long = _valid_day()
        too_long[0]["duration_min"] = 91
        self._restitch(too_long)
        self.assertScheduleError(
            "course_duration_out_of_range",
            compile_day_schedule,
            too_long,
        )

    def test_rejects_qa_duration_outside_5_to_30_minutes(self):
        for invalid_duration in (4, 31):
            blocks = _valid_day()
            blocks[1]["duration_min"] = invalid_duration
            self._restitch(blocks)
            self.assertScheduleError(
                "qa_duration_out_of_range",
                compile_day_schedule,
                blocks,
            )

    def test_rejects_short_pause_duration_outside_5_to_30_minutes(self):
        for invalid_duration in (4, 31):
            blocks = _valid_day()
            first_pause = next(
                block
                for block in blocks
                if block["type"] == "pause" and not block["is_lunch"]
            )
            first_pause["duration_min"] = invalid_duration
            self._restitch(blocks)
            self.assertScheduleError(
                "short_pause_duration_out_of_range",
                compile_day_schedule,
                blocks,
            )

    def test_rejects_lunch_duration_outside_60_to_120_minutes(self):
        for invalid_duration in (59, 121):
            blocks = _valid_day()
            lunch = next(block for block in blocks if block["is_lunch"])
            lunch["duration_min"] = invalid_duration
            self._restitch(blocks)
            self.assertScheduleError(
                "lunch_duration_out_of_range",
                compile_day_schedule,
                blocks,
            )

    def test_requires_exactly_one_lunch(self):
        no_lunch = _valid_day()
        lunch = next(block for block in no_lunch if block["is_lunch"])
        lunch["is_lunch"] = False
        lunch["duration_min"] = 15
        self._restitch(no_lunch)
        self.assertScheduleError(
            "invalid_lunch_count",
            compile_day_schedule,
            no_lunch,
        )

        two_lunches = _valid_day()
        short_pause = next(
            block
            for block in two_lunches
            if block["type"] == "pause" and not block["is_lunch"]
        )
        short_pause["is_lunch"] = True
        short_pause["duration_min"] = 60
        self._restitch(two_lunches)
        self.assertScheduleError(
            "invalid_lunch_count",
            compile_day_schedule,
            two_lunches,
        )

    def test_final_pause_cannot_be_lunch(self):
        blocks = _valid_day(final_pause=True)
        current_lunch = next(block for block in blocks if block["is_lunch"])
        current_lunch["is_lunch"] = False
        current_lunch["duration_min"] = 15
        blocks[-1]["is_lunch"] = True
        blocks[-1]["duration_min"] = 60
        self._restitch(blocks)

        self.assertScheduleError(
            "lunch_cannot_be_final",
            compile_day_schedule,
            blocks,
        )

    def test_rejects_less_than_four_hours_of_courses(self):
        self.assertScheduleError(
            "insufficient_course_minutes",
            compile_day_schedule,
            _valid_day(course_durations=(55,) * 4),
        )

    def test_rejects_day_amplitude_below_six_hours(self):
        blocks = _valid_day(
            course_durations=(60,) * 4,
            qa_duration=5,
            short_pause_duration=5,
            lunch_duration=60,
        )
        self.assertScheduleError(
            "day_amplitude_too_short",
            compile_day_schedule,
            blocks,
        )

    def test_rejects_gap_and_overlap(self):
        gap = _valid_day()
        gap[1]["start_minute"] += 1
        self.assertScheduleError(
            "gap_between_blocks",
            compile_day_schedule,
            gap,
        )

        overlap = _valid_day()
        overlap[1]["start_minute"] -= 1
        self.assertScheduleError(
            "overlapping_blocks",
            compile_day_schedule,
            overlap,
        )

    def test_rejects_invalid_course_qa_pause_grammar(self):
        blocks = _valid_day()
        blocks[1]["type"] = "pause"
        self.assertScheduleError(
            "invalid_block_sequence",
            compile_day_schedule,
            blocks,
        )

    def test_rejects_incomplete_final_course_without_qa(self):
        blocks = _valid_day()[:-1]
        self.assertScheduleError(
            "incomplete_final_sequence",
            compile_day_schedule,
            blocks,
        )

    def test_rejects_conflicting_time_representations(self):
        blocks = _valid_day()
        blocks[0]["start_time"] = "09:08"
        self.assertScheduleError(
            "conflicting_start_time",
            compile_day_schedule,
            blocks,
        )

    def test_rejects_fractional_minute_precision(self):
        fractional_start = _valid_day()
        fractional_start[0]["start_minute"] += 0.5
        self.assertScheduleError(
            "invalid_minute_value",
            compile_day_schedule,
            fractional_start,
        )

        fractional_duration = _valid_day()
        fractional_duration[0]["duration_min"] = 60.5
        self.assertScheduleError(
            "invalid_minute_value",
            compile_day_schedule,
            fractional_duration,
        )

    def test_rejects_conflicting_canonical_end_minute(self):
        canonical = compile_day_schedule(_valid_day())
        canonical["blocks"][0]["end_minute"] += 1
        self.assertScheduleError(
            "conflicting_end_minute",
            compile_day_schedule,
            canonical,
        )

    def test_day_must_end_inside_the_same_calendar_day(self):
        accepted = compile_day_schedule(
            _valid_day(start_minute=17 * 60 + 30)
        )
        self.assertEqual(accepted["end_minute"], 1440)

        self.assertScheduleError(
            "day_crosses_midnight",
            compile_day_schedule,
            _valid_day(start_minute=18 * 60),
        )

    def test_audio_manifest_has_one_stable_file_per_block(self):
        compiled = compile_day_schedule(_valid_day())
        manifest = build_day_audio_manifest(compiled)

        self.assertEqual(len(manifest), compiled["audio_file_count"])
        self.assertEqual(manifest[0]["filename"], "course_01.mp3")
        self.assertEqual(manifest[1]["filename"], "qa_01.mp3")
        self.assertEqual(manifest[2]["filename"], "pause_01.mp3")
        self.assertEqual(manifest[-1]["filename"], "qa_04.mp3")
        self.assertEqual(manifest[-1]["course_index"], 4)

    def test_canonical_output_can_be_revalidated_without_information_loss(self):
        first_compile = compile_day_schedule(_valid_day())
        second_compile = compile_day_schedule(first_compile)

        self.assertEqual(first_compile, second_compile)

    def test_pause_kind_null_is_reserved_for_non_pause_blocks(self):
        blocks = _valid_day()
        pause = next(block for block in blocks if block["type"] == "pause")
        pause.pop("is_lunch")
        pause["pause_kind"] = None

        self.assertScheduleError(
            "invalid_pause_kind",
            compile_day_schedule,
            blocks,
        )

    def test_module_compilation_sorts_dates_and_requires_one_template_each(self):
        templates = {
            "standard": {
                "name": "Journée standard",
                "blocks": _valid_day(),
            }
        }
        snapshot = compile_module_schedule(
            ["2026-09-03", "2026-09-01"],
            {
                "2026-09-01": "standard",
                "2026-09-03": "standard",
            },
            templates,
        )

        self.assertEqual(snapshot["schema_version"], 2)
        self.assertEqual(snapshot["day_count"], 2)
        self.assertEqual(
            [day["date"] for day in snapshot["days"]],
            ["2026-09-01", "2026-09-03"],
        )
        self.assertEqual(
            [day["day_number"] for day in snapshot["days"]],
            [1, 2],
        )
        self.assertEqual(snapshot["audio_file_count"], 22)
        self.assertEqual(len(snapshot["schedule_hash"]), 64)

    def test_module_hash_excludes_dates_template_ids_and_names(self):
        layout = _valid_day()
        first = compile_module_schedule(
            ["2026-09-01", "2026-09-03"],
            {
                "2026-09-01": "template-a",
                "2026-09-03": "template-a",
            },
            {"template-a": {"name": "Ancien nom", "blocks": layout}},
        )
        second = compile_module_schedule(
            ["2027-01-12", "2027-01-14"],
            {
                "2027-01-12": 999,
                "2027-01-14": 999,
            },
            {999: {"name": "Nouveau nom", "blocks": copy.deepcopy(layout)}},
        )

        self.assertEqual(first["schedule_hash"], second["schedule_hash"])

    def test_module_hash_changes_when_pedagogical_layout_changes(self):
        layout_a = _valid_day()
        layout_b = _valid_day()
        layout_b[0]["duration_min"] += 1
        self._restitch(layout_b)
        first = compile_module_schedule(
            ["2026-09-01"],
            {"2026-09-01": "a"},
            {"a": layout_a},
        )
        second = compile_module_schedule(
            ["2026-09-01"],
            {"2026-09-01": "b"},
            {"b": layout_b},
        )

        self.assertNotEqual(first["schedule_hash"], second["schedule_hash"])

    def test_module_rejects_missing_or_extra_assignment(self):
        templates = {"standard": _valid_day()}
        error = self.assertScheduleError(
            "template_assignment_mismatch",
            compile_module_schedule,
            ["2026-09-01", "2026-09-03"],
            {"2026-09-01": "standard", "2026-09-05": "standard"},
            templates,
        )
        self.assertEqual(
            error.details,
            {
                "missing_dates": ["2026-09-03"],
                "extra_dates": ["2026-09-05"],
            },
        )

    def test_module_rejects_duplicate_assignment_from_list(self):
        self.assertScheduleError(
            "duplicate_template_assignment",
            compile_module_schedule,
            ["2026-09-01"],
            [
                {"date": "2026-09-01", "template_key": "a"},
                {"date": "2026-09-01", "template_key": "b"},
            ],
            {"a": _valid_day(), "b": _valid_day()},
        )

    def test_new_module_accepts_exactly_48_hours_notice(self):
        validation_at = datetime(2026, 7, 26, 9, 0, tzinfo=timezone.utc)
        first_start_at = validation_at + timedelta(
            hours=MIN_NEW_MODULE_LEAD_HOURS
        )

        self.assertTrue(
            validate_new_module_lead_time(validation_at, first_start_at)
        )

    def test_new_module_rejects_less_than_48_hours_notice(self):
        validation_at = datetime(2026, 7, 26, 9, 0)
        first_start_at = validation_at + timedelta(hours=47, minutes=59)

        self.assertScheduleError(
            "new_module_lead_time_too_short",
            validate_new_module_lead_time,
            validation_at,
            first_start_at,
        )

    def test_reused_module_is_exempt_from_48_hour_rule(self):
        validation_at = datetime(2026, 7, 26, 9, 0)
        first_start_at = validation_at + timedelta(minutes=1)

        self.assertTrue(
            validate_new_module_lead_time(
                validation_at,
                first_start_at,
                is_reuse=True,
            )
        )

    @staticmethod
    def _restitch(blocks):
        cursor = blocks[0]["start_minute"]
        for block in blocks:
            block["start_minute"] = cursor
            cursor += block["duration_min"]


if __name__ == "__main__":
    unittest.main()
