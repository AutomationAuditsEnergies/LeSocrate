import json
import unittest
from unittest.mock import patch

from services import formation_pipeline_service as fps


def _schedule_blocks(
    course_durations,
    *,
    start_minute=9 * 60 + 7,
    qa_duration=15,
    short_pause_duration=15,
    lunch_after_course=2,
    lunch_duration=60,
    final_pause=False,
):
    blocks = []
    cursor = start_minute
    for course_index, course_duration in enumerate(course_durations, start=1):
        blocks.append(
            {
                "block_type": "course",
                "pause_kind": None,
                "start_minute": cursor,
                "duration_minutes": course_duration,
            }
        )
        cursor += course_duration
        blocks.append(
            {
                "block_type": "qa",
                "pause_kind": None,
                "start_minute": cursor,
                "duration_minutes": qa_duration,
            }
        )
        cursor += qa_duration
        if course_index < len(course_durations) or final_pause:
            is_lunch = course_index == lunch_after_course
            duration = lunch_duration if is_lunch else short_pause_duration
            blocks.append(
                {
                    "block_type": "pause",
                    "pause_kind": "lunch" if is_lunch else "short",
                    "start_minute": cursor,
                    "duration_minutes": duration,
                }
            )
            cursor += duration
    return blocks


def _v2_job(days, **overrides):
    snapshot_days = [
        {
            "day_index": index,
            "template_name": f"Modèle {index}",
            "blocks": blocks,
        }
        for index, blocks in enumerate(days, start=1)
    ]
    data = {
        "id": 91,
        "platform_id": 12,
        "tp_name": "TP dynamique",
        "total_hours": 999,
        "nb_days": 999,
        "schedule_schema_version": 2,
        "schedule_snapshot_json": json.dumps(
            {
                "schema_version": 2,
                "days": snapshot_days,
            }
        ),
        "global_program": "Programme global",
        "reac_text": "Référentiel",
        "rc_text": "",
        "rome_text": "",
    }
    data.update(overrides)
    return data


def _raw_generated_day(day_number, course_count, *, title=None):
    return {
        "day_number": day_number,
        "title": title or f"Journée dynamique {day_number}",
        "sub_parts": [
            {
                "name": f"Cours {index} — Thème {index}",
                "module_content": f"Contenu pédagogique {index}",
                "generation_brief": {
                    "finish": (
                        "Conclusion de journée"
                        if index == course_count
                        else "Transition vers la suite"
                    )
                },
            }
            for index in range(1, course_count + 1)
        ],
    }


class FormationPipelineDynamicScheduleTest(unittest.TestCase):
    def setUp(self):
        self.day_four = _schedule_blocks((60, 60, 60, 60))
        self.day_five = _schedule_blocks(
            (50, 50, 50, 50, 50),
            qa_duration=10,
            short_pause_duration=10,
        )

    def test_v2_snapshot_is_the_day_count_and_schedule_source_of_truth(self):
        job = _v2_job([self.day_five, self.day_four])

        days = fps._v2_schedule_days(job)

        self.assertEqual([day["day_index"] for day in days], [1, 2])
        self.assertEqual([day["course_count"] for day in days], [5, 4])
        self.assertEqual(
            [day["total_course_minutes"] for day in days],
            [250, 240],
        )

    def test_v2_normalization_keeps_exactly_the_snapshot_courses(self):
        schedule_day = fps._v2_schedule_days(
            _v2_job([self.day_four])
        )[0]
        generated = _raw_generated_day(1, 7)

        day = fps._complete_day_program_shape(
            generated,
            1,
            "TP dynamique",
            schedule_day=schedule_day,
        )

        self.assertEqual(len(day["sub_parts"]), 4)
        self.assertEqual(day["course_minutes"], 240)
        self.assertEqual(day["hours"], 4)
        self.assertEqual(day["audio_file_count"], 11)
        self.assertEqual(len(day["audio_manifest"]), 11)
        self.assertEqual(
            [part["duration_min"] for part in day["sub_parts"]],
            [60, 60, 60, 60],
        )
        self.assertEqual(
            [part["filename"] for part in day["sub_parts"]],
            [
                "course_01.mp3",
                "course_02.mp3",
                "course_03.mp3",
                "course_04.mp3",
            ],
        )
        self.assertTrue(day["sub_parts"][-1]["is_last_course"])

    def test_v1_normalization_remains_exactly_seven_fixed_slots(self):
        day = fps._normalize_day_audio_slots(
            {
                "sub_parts": [
                    {"name": "Introduction"},
                    {"name": "Méthode"},
                ]
            }
        )

        self.assertEqual(day["hours"], fps.HOURS_PER_DAY)
        self.assertEqual(len(day["sub_parts"]), 7)
        self.assertEqual(
            [part["filename"] for part in day["sub_parts"]],
            [slot["filename"] for slot in fps.COURSE_AUDIO_SLOTS],
        )

    def test_v2_global_prompt_uses_real_course_minutes_not_total_hours(self):
        job = _v2_job([self.day_four, self.day_five])
        schedule_days = fps._v2_schedule_days(job)

        prompt = fps._build_global_program_prompt(
            job,
            "SOURCE REAC",
            schedule_days=schedule_days,
        )

        self.assertIn("490 minutes sur 2 journées", prompt)
        self.assertIn("Journée 1 : 4 cours", prompt)
        self.assertIn("Journée 2 : 5 cours", prompt)
        self.assertNotIn("999", prompt)
        self.assertNotIn("journées de 7h", prompt)
        self.assertNotIn("{TOTAL_HOURS}", prompt)

    def test_global_prompt_requires_lecture_only_programming(self):
        prompt = fps._build_global_program_prompt(
            {
                "tp_name": "TP cours pur",
                "total_hours": 14,
                "nb_days": 2,
            },
            "SOURCE",
        )

        self.assertIn("100% du volume pédagogique est du cours magistral audio", prompt)
        self.assertIn("Exemples professionnels commentés à intégrer au cours", prompt)
        self.assertNotIn("Cas pratiques suggérés", prompt)

    def test_activity_detector_keeps_professional_context_but_rejects_exercises(self):
        legitimate = (
            "Les conditions d'exercice du métier et les modalités d’exercice "
            "de la profession sont expliquées par le professeur. "
            "La clôture de l'exercice comptable est ensuite détaillée."
        )
        self.assertEqual(fps._learner_activity_violations(legitimate), [])

        for forbidden in (
            "Séance d'exercices",
            "Cas pratique guidé",
            "Étude de cas en groupe",
            "Atelier d'application",
            "Mise en situation",
            "Jeu de rôle",
            "QCM final",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertTrue(fps._learner_activity_violations(forbidden))

    def test_v1_global_prompt_remains_byte_for_byte_legacy(self):
        job = {
            "tp_name": "TP historique",
            "total_hours": 14,
            "nb_days": 2,
        }
        expected = (
            fps._GLOBAL_PROGRAM_PROMPT
            .replace("{TP_NAME}", "TP historique")
            .replace("{TOTAL_HOURS}", "14")
            .replace("{NB_DAYS}", "2")
            .replace("{REAC_TEXT}", "SOURCE")
        )

        self.assertEqual(
            fps._build_global_program_prompt(job, "SOURCE"),
            expected,
        )

    def test_v2_daily_prompt_and_payload_follow_each_day_schedule(self):
        schedule_days = fps._v2_schedule_days(
            _v2_job([self.day_four, self.day_five])
        )
        response = json.dumps(
            {
                "days": [
                    _raw_generated_day(1, 4),
                    _raw_generated_day(2, 5),
                ]
            }
        )
        captured = {}

        def fake_post(*, messages, **_kwargs):
            captured["prompt"] = messages[0]["content"]
            return response

        with patch.object(fps, "_deepseek_post", side_effect=fake_post):
            days = fps._split_batch(
                tp_name="TP dynamique",
                nb_days=2,
                global_program="Programme",
                day_start=1,
                day_end=2,
                model="test-model",
                schedule_days=schedule_days,
            )

        self.assertEqual([len(day["sub_parts"]) for day in days], [4, 5])
        self.assertEqual(
            [
                [part["duration_min"] for part in day["sub_parts"]]
                for day in days
            ],
            [[60, 60, 60, 60], [50, 50, 50, 50, 50]],
        )
        self.assertIn("Journée 1 : 4 cours vocaux", captured["prompt"])
        self.assertIn("Journée 2 : 5 cours vocaux", captured["prompt"])
        self.assertIn("50 min", captured["prompt"])
        self.assertNotIn("EXACTEMENT 7", captured["prompt"])
        self.assertIn("exclusivement un cours magistral", captured["prompt"])

    def test_daily_split_regenerates_a_learner_activity(self):
        schedule_days = fps._v2_schedule_days(
            _v2_job([self.day_four])
        )
        invalid_day = _raw_generated_day(1, 4)
        invalid_day["sub_parts"][0]["name"] = "Cours 1 — Cas pratique guidé"
        valid_day = _raw_generated_day(1, 4)

        with patch.object(
            fps,
            "DAILY_SPLIT_ATTEMPTS",
            2,
        ), patch.object(
            fps,
            "_deepseek_post",
            side_effect=[
                json.dumps({"days": [invalid_day]}),
                json.dumps({"days": [valid_day]}),
            ],
        ) as deepseek, patch.object(fps.time, "sleep"):
            days = fps._split_batch(
                tp_name="TP dynamique",
                nb_days=1,
                global_program="Programme",
                day_start=1,
                day_end=1,
                model="test-model",
                schedule_days=schedule_days,
            )

        self.assertEqual(deepseek.call_count, 2)
        self.assertEqual(days[0]["sub_parts"][0]["name"], "Cours 1 — Thème 1")

    def test_run_daily_split_never_persists_a_fallback_after_failure(self):
        job = _v2_job([self.day_five])
        failure = fps.DailySplitGenerationError(
            "Journée 1 impossible à générer correctement"
        )

        with (
            patch.object(fps, "get_job", return_value=job),
            patch.object(fps, "update_job") as update,
            patch.object(fps, "_split_batch", side_effect=failure),
        ):
            with self.assertRaises(fps.DailySplitGenerationError):
                fps.run_daily_split(91, model="test-model")

        updates = [item.kwargs for item in update.call_args_list]
        self.assertEqual(updates[0]["status"], "daily_splitting")
        self.assertEqual(updates[-1]["status"], "error")
        self.assertIn(str(failure), updates[-1]["error_message"])
        self.assertFalse(any("daily_programs" in fields for fields in updates))
        self.assertFalse(
            any(fields.get("status") == "daily_ready" for fields in updates)
        )

    def test_run_daily_split_uses_snapshot_length_not_legacy_nb_days(self):
        job = _v2_job([self.day_four, self.day_five])
        captured = []

        def fake_split(**kwargs):
            captured.append(kwargs)
            return [
                _raw_generated_day(day_number, 4 if day_number == 1 else 5)
                for day_number in range(
                    kwargs["day_start"],
                    kwargs["day_end"] + 1,
                )
            ]

        with (
            patch.object(fps, "get_job", return_value=job),
            patch.object(fps, "update_job") as update,
            patch.object(fps, "_split_batch", side_effect=fake_split),
        ):
            result = fps.run_daily_split(91, model="test-model")

        self.assertEqual(result["days"], 2)
        self.assertEqual(captured[0]["nb_days"], 2)
        self.assertEqual(len(captured[0]["schedule_days"]), 2)
        saved = next(
            call.kwargs["daily_programs"]
            for call in update.call_args_list
            if "daily_programs" in call.kwargs
        )
        saved_days = json.loads(saved)
        self.assertEqual(
            [len(day["sub_parts"]) for day in saved_days],
            [4, 5],
        )

    def test_launch_tts_passes_exactly_x_v2_courses_and_their_budgets(self):
        generated_day = _raw_generated_day(
            1,
            5,
            title="Journée dynamique",
        )
        job = _v2_job(
            [self.day_five],
            nb_days=1,
            daily_programs=json.dumps([generated_day]),
        )
        folder_name = "Jour 1 — Journée dynamique"

        with (
            patch.object(fps, "get_job", return_value=job),
            patch.object(
                fps,
                "get_expected_course_folders",
                return_value={
                    "folder_ids": [501],
                    "folders": [
                        {
                            "folder_id": 501,
                            "expected_name": folder_name,
                        }
                    ],
                },
            ),
            patch(
                "services.content_generation_service.get_job_from_db",
                return_value=None,
            ),
            patch(
                "services.content_generation_service.start_generation_job",
            ) as start,
            patch.object(fps, "update_job") as update,
        ):
            folder_ids = fps.launch_tts_for_all_days(91, 12)

        self.assertEqual(folder_ids, [501])
        kwargs = start.call_args.kwargs
        self.assertEqual(len(kwargs["sub_parts_override"]), 5)
        self.assertEqual(len(kwargs["module_contents"]), 5)
        self.assertIn("Cours 1 sur 5", kwargs["program_text"])
        self.assertIn("50 minutes", kwargs["program_text"])
        self.assertIn("cible 8202 mots", kwargs["program_text"])
        self.assertIn(
            "dernier cours de la journée",
            kwargs["module_contents"][kwargs["sub_parts_override"][-1]],
        )
        update.assert_called_with(91, status="tts_launched")

    def test_invalid_v2_job_without_snapshot_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "schedule_snapshot_json"):
            fps._v2_schedule_days(
                {
                    "schedule_schema_version": 2,
                    "schedule_snapshot_json": None,
                }
            )


if __name__ == "__main__":
    unittest.main()
