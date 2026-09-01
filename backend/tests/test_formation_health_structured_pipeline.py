import json
import unittest
from unittest.mock import patch

from services import formation_health_service as health
from services.dynamic_day_schedule_service import compile_module_schedule
from services.formation_health_service import (
    _expected_structured_segment_count,
    _expected_structured_segment_contract,
)


def _schedule_blocks(course_count):
    blocks = []
    cursor = 9 * 60
    for course_index in range(1, course_count + 1):
        blocks.append({
            "type": "course",
            "start_minute": cursor,
            "duration_min": 60,
        })
        cursor += 60
        blocks.append({
            "type": "qa",
            "start_minute": cursor,
            "duration_min": 10,
        })
        cursor += 10
        if course_index < course_count:
            is_lunch = course_index == 2
            blocks.append({
                "type": "pause",
                "start_minute": cursor,
                "duration_min": 60 if is_lunch else 10,
                "is_lunch": is_lunch,
            })
            cursor += 60 if is_lunch else 10
    return blocks


def _v2_job(course_counts):
    dates = [
        f"2030-09-{index:02d}"
        for index in range(1, len(course_counts) + 1)
    ]
    assignments = {
        date: f"template-{index}"
        for index, date in enumerate(dates, start=1)
    }
    templates = {
        f"template-{index}": {
            "name": f"Journée {index}",
            "blocks": _schedule_blocks(course_count),
        }
        for index, course_count in enumerate(course_counts, start=1)
    }
    snapshot = compile_module_schedule(dates, assignments, templates)
    return {
        "nb_days": len(course_counts),
        "schedule_schema_version": 2,
        "schedule_snapshot_json": json.dumps(snapshot),
        "schedule_hash": snapshot["schedule_hash"],
        "schedule_locked_at": "2030-08-01T09:00:00+00:00",
    }


class StructuredPipelineHealthTests(unittest.TestCase):
    def test_expected_segments_are_one_per_structured_sub_part(self):
        job = {"nb_days": 1}
        daily_programs = [{"sub_parts": [{"title": str(i)} for i in range(7)]}]

        self.assertEqual(_expected_structured_segment_count(job, daily_programs), 7)

    def test_expected_segments_fall_back_to_seven_slots_per_day(self):
        self.assertEqual(_expected_structured_segment_count({"nb_days": 2}, []), 14)

    def test_v2_expected_segments_come_from_locked_snapshot(self):
        job = _v2_job([4, 6])
        misleading_daily_programs = [
            {"sub_parts": [{"title": str(index)} for index in range(7)]},
            {"sub_parts": [{"title": str(index)} for index in range(7)]},
        ]

        contract = _expected_structured_segment_contract(
            job,
            misleading_daily_programs,
        )

        self.assertEqual(contract["expected_segments"], 10)
        self.assertEqual(contract["course_counts"], [4, 6])
        self.assertEqual(contract["source"], "locked_schedule_snapshot")
        self.assertEqual(
            _expected_structured_segment_count(job, misleading_daily_programs),
            10,
        )

    def test_v2_invalid_hash_fails_instead_of_falling_back_to_seven(self):
        job = _v2_job([5])
        job["schedule_hash"] = "corrompu"

        with self.assertRaisesRegex(ValueError, "hash"):
            _expected_structured_segment_count(job, [])

    def test_health_returns_clean_blocking_diagnostic_for_invalid_v2(self):
        job = _v2_job([5])
        job["schedule_locked_at"] = None

        with patch.object(health, "_get_job", return_value=job):
            result = health.compute_health(42)

        self.assertFalse(result["ok"])
        self.assertEqual(result["blocking"], ["schedule_contract"])
        self.assertEqual(
            result["checks"]["schedule_contract"]["schema_version"],
            2,
        )
        self.assertIn(
            "n'est pas verrouillé",
            result["checks"]["schedule_contract"]["detail"],
        )

    def test_preflight_requires_deepseek_key_even_with_unrelated_key(self):
        job = {
            "status": "pending",
            "platform_id": 3,
            "reac_text": "déjà chargé",
        }
        with patch.object(health, "_get_job", return_value=job), patch.object(
            health,
            "_check_azure_blob",
            return_value=(True, "connexion OK"),
        ), patch.dict(
            health.os.environ,
            {
                "OTHER_LLM_API_KEY": "legacy-key",
                "FORMATION_LLM_PROVIDER": "legacy-provider",
            },
            clear=True,
        ):
            result = health.compute_preflight(42, tts_mode="mock")

        self.assertFalse(result["ok"])
        self.assertIn("llm_api_key", result["blocking"])
        self.assertEqual(
            result["checks"]["llm_provider"]["detail"],
            "DeepSeek uniquement (deepseek-v4-flash)",
        )
        self.assertEqual(
            result["checks"]["llm_api_key"]["detail"],
            "DEEPSEEK_API_KEY absente",
        )

    def test_preflight_rejects_a_non_deepseek_model(self):
        job = {
            "status": "pending",
            "platform_id": 3,
            "reac_text": "déjà chargé",
        }
        with patch.object(health, "_get_job", return_value=job), patch.object(
            health,
            "_check_azure_blob",
            return_value=(True, "connexion OK"),
        ), patch.dict(
            health.os.environ,
            {
                "DEEPSEEK_API_KEY": "deepseek-key",
                "FORMATION_LLM_MODEL": "gpt-4",
            },
            clear=True,
        ):
            result = health.compute_preflight(42, tts_mode="mock")

        self.assertFalse(result["ok"])
        self.assertIn("llm_provider", result["blocking"])
        self.assertIn(
            "uniquement DeepSeek",
            result["checks"]["llm_provider"]["detail"],
        )


if __name__ == "__main__":
    unittest.main()
