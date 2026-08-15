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
            "La clôture de l'exercice comptable est ensuite détaillée. "
            "Aucune mise en situation n'est prévue et les jeux de rôle sont exclus. "
            "Le cours se déroule sans atelier pédagogique ni QCM."
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

    def test_daily_split_repairs_invalid_activity_before_returning(self):
        schedule_days = fps._v2_schedule_days(
            _v2_job([self.day_four])
        )
        invalid_day = _raw_generated_day(1, 4)
        invalid_day["sub_parts"][0]["name"] = "Cours 1 — Cas pratique guidé"
        repaired_day = _raw_generated_day(1, 4)
        repaired_day["sub_parts"][0]["name"] = "Cours 1 — Exemple professionnel commenté"

        with patch.object(
            fps,
            "_deepseek_post",
            side_effect=[
                json.dumps({"days": [invalid_day]}),
                json.dumps({"days": [repaired_day]}),
            ],
        ) as deepseek:
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
        self.assertTrue(
            all(
                call_item.kwargs["http_max_attempts"] == 2
                for call_item in deepseek.call_args_list
            )
        )
        self.assertEqual(
            days[0]["sub_parts"][0]["name"],
            "Cours 1 — Exemple professionnel commenté",
        )

    def test_daily_split_delegates_failed_semantic_repair_to_durable_retry(self):
        schedule_days = fps._v2_schedule_days(_v2_job([self.day_four]))
        invalid_day = _raw_generated_day(1, 4)
        invalid_day["sub_parts"][0]["name"] = "Cours 1 — Mise en situation"

        with patch.object(
            fps,
            "_deepseek_post",
            return_value=json.dumps({"days": [invalid_day]}),
        ) as deepseek:
            with self.assertRaisesRegex(
                fps.DailySplitGenerationError,
                "activité apprenant interdite",
            ):
                fps._split_batch(
                    tp_name="TP dynamique",
                    nb_days=1,
                    global_program="Programme",
                    day_start=1,
                    day_end=1,
                    model="test-model",
                    schedule_days=schedule_days,
                )

        self.assertEqual(deepseek.call_count, 2)

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
        saved_days = [
            json.loads(fields["daily_programs"])
            for fields in updates
            if "daily_programs" in fields
        ]
        self.assertEqual(saved_days, [[]])
        self.assertFalse(
            any(fields.get("daily_programs_validated") == 1 for fields in updates)
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
        final_update = next(
            call.kwargs
            for call in update.call_args_list
            if call.kwargs.get("status") == "daily_validated"
        )
        saved_days = json.loads(final_update["daily_programs"])
        self.assertEqual(
            [len(day["sub_parts"]) for day in saved_days],
            [4, 5],
        )
        self.assertEqual(final_update["daily_programs_validated"], 1)

    def test_run_daily_split_resumes_only_the_missing_days(self):
        schedule_days = fps._v2_schedule_days(
            _v2_job([self.day_four, self.day_five])
        )
        persisted_day = fps._complete_day_program_shape(
            _raw_generated_day(1, 4),
            1,
            "TP dynamique",
            schedule_day=schedule_days[0],
        )
        job = _v2_job(
            [self.day_four, self.day_five],
            daily_programs=json.dumps([persisted_day]),
            daily_programs_validated=0,
        )
        captured = []

        def fake_split(**kwargs):
            captured.append(kwargs)
            return [_raw_generated_day(2, 5)]

        with (
            patch.object(fps, "get_job", return_value=job),
            patch.object(fps, "update_job") as update,
            patch.object(fps, "_split_batch", side_effect=fake_split),
        ):
            result = fps.run_daily_split(91, model="test-model")

        self.assertEqual(len(captured), 1)
        self.assertEqual(
            (captured[0]["day_start"], captured[0]["day_end"]),
            (2, 2),
        )
        self.assertEqual(result["resumed_days"], 1)
        self.assertEqual(result["generated_days"], 1)
        final_update = next(
            call.kwargs
            for call in update.call_args_list
            if call.kwargs.get("status") == "daily_validated"
        )
        self.assertEqual(
            [
                day["day_number"]
                for day in json.loads(final_update["daily_programs"])
            ],
            [1, 2],
        )

    def test_successful_day_is_checkpointed_before_another_day_fails(self):
        job = _v2_job([self.day_four, self.day_five])

        def fake_split(**kwargs):
            if kwargs["day_start"] == 2:
                raise fps.DailySplitGenerationError(
                    "Journée 2 impossible à générer correctement"
                )
            return [_raw_generated_day(1, 4)]

        with (
            patch.object(fps, "BATCH_SIZE", 1),
            patch.object(fps, "get_job", return_value=job),
            patch.object(fps, "update_job") as update,
            patch.object(fps, "_split_batch", side_effect=fake_split),
        ):
            with self.assertRaises(fps.DailySplitGenerationError):
                fps.run_daily_split(91, model="test-model")

        saved_payloads = [
            json.loads(call.kwargs["daily_programs"])
            for call in update.call_args_list
            if "daily_programs" in call.kwargs
        ]
        self.assertTrue(
            any(
                [day["day_number"] for day in payload] == [1]
                for payload in saved_payloads
            )
        )
        self.assertFalse(
            any(
                call.kwargs.get("daily_programs_validated") == 1
                for call in update.call_args_list
            )
        )

    def test_multi_day_batch_still_checkpoints_each_day_separately(self):
        job = _v2_job([self.day_four, self.day_five])

        with (
            patch.object(fps, "BATCH_SIZE", 2),
            patch.object(fps, "get_job", return_value=job),
            patch.object(fps, "update_job") as update,
            patch.object(
                fps,
                "_split_batch",
                return_value=[
                    _raw_generated_day(1, 4),
                    _raw_generated_day(2, 5),
                ],
            ),
        ):
            fps.run_daily_split(91, model="test-model")

        partial_sizes = [
            len(json.loads(call.kwargs["daily_programs"]))
            for call in update.call_args_list
            if call.kwargs.get("status") == "daily_splitting"
            and "daily_programs" in call.kwargs
        ]
        self.assertEqual(partial_sizes, [0, 1, 2])

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
