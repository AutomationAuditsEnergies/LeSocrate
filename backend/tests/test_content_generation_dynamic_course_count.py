import json
import unittest
from unittest.mock import Mock, patch

from flask import Flask

from routes.hr_routes import create_hr_blueprint
from services import content_generation_service as cgs


def _playlist(course_count):
    items = []
    for index in range(1, course_count + 1):
        items.extend([
            (f"course_{index:02d}.mp3", 2700, "cours", index),
            (f"qa_{index:02d}.mp3", 900, "qa", index),
        ])
    return items


class ExtractSubPartsDynamicCountTest(unittest.TestCase):
    def test_extracts_exact_requested_count_and_builds_dynamic_prompt(self):
        response = json.dumps({
            "title": "TP Test",
            "sub_parts": [
                f"Cours {index} — Thème {index}"
                for index in range(1, 9)
            ],
        })
        with patch.object(cgs, "_deepseek_post", return_value=response) as post:
            result = cgs.extract_sub_parts(
                "Programme suffisamment détaillé",
                course_count=5,
            )

        self.assertEqual(len(result["sub_parts"]), 5)
        prompt = post.call_args.kwargs["messages"][0]["content"]
        self.assertIn("identifier exactement 5 cours", prompt)
        self.assertIn('"Cours 5 — Nom précis du thème"', prompt)
        self.assertNotIn('"Cours 6 — Nom précis du thème"', prompt)

    def test_pads_to_exact_requested_count(self):
        response = json.dumps({
            "title": "TP Test",
            "sub_parts": ["Cours 1 — Introduction"],
        })
        with patch.object(cgs, "_deepseek_post", return_value=response):
            result = cgs.extract_sub_parts("Programme", course_count=4)

        self.assertEqual(
            result["sub_parts"],
            ["Introduction", "Sous-partie 2", "Sous-partie 3", "Sous-partie 4"],
        )

    def test_v1_default_remains_seven(self):
        response = json.dumps({
            "title": "TP Test",
            "sub_parts": [
                f"Cours {index} — Thème {index}"
                for index in range(1, 8)
            ],
        })
        with patch.object(cgs, "_deepseek_post", return_value=response):
            result = cgs.extract_sub_parts("Programme")

        self.assertEqual(len(result["sub_parts"]), 7)

    def test_rejects_counts_outside_v2_contract(self):
        with patch.object(cgs, "_deepseek_post") as post:
            with self.assertRaisesRegex(ValueError, "entre 1 et 10"):
                cgs.extract_sub_parts("Programme", course_count=0)
            with self.assertRaisesRegex(ValueError, "entre 1 et 10"):
                cgs.extract_sub_parts("Programme", course_count=11)
        post.assert_not_called()


class PipelineContentRetryOwnershipTest(unittest.TestCase):
    def test_content_wrapper_disables_hidden_http_retries(self):
        with patch.object(cgs, "_llm_post", return_value="ok") as post:
            self.assertEqual(
                cgs._deepseek_post(
                    [{"role": "user", "content": "test"}],
                    max_tokens=100,
                    model="deepseek-v4-pro",
                ),
                "ok",
            )

        self.assertEqual(post.call_args.kwargs["http_max_attempts"], 1)

    def test_structured_plan_failure_calls_generator_once(self):
        with patch.object(
            cgs,
            "_structured_plan_two_stage_enabled",
            return_value=True,
        ), patch.object(
            cgs,
            "_generate_structured_course_plan_two_stage",
            side_effect=RuntimeError("provider indisponible"),
        ) as generate:
            with self.assertRaisesRegex(RuntimeError, "provider indisponible"):
                cgs._generate_structured_course_plan(
                    {"id": 1},
                    [],
                    [],
                    {},
                    model="deepseek-v4-pro",
                )

        generate.assert_called_once()

    def test_legacy_segment_failure_calls_model_once(self):
        with patch.object(
            cgs,
            "_deepseek_post",
            side_effect=RuntimeError("provider indisponible"),
        ) as post:
            with self.assertRaisesRegex(RuntimeError, "provider indisponible"):
                cgs._generate_segment_text(
                    1,
                    "Thème",
                    "Titre",
                    "Programme",
                    "",
                    from_scratch=True,
                    module_content="Contenu source",
                )

        post.assert_called_once()

    def test_review_failure_calls_model_once_and_propagates(self):
        with patch.object(
            cgs,
            "_deepseek_post",
            side_effect=RuntimeError("provider indisponible"),
        ) as post:
            with self.assertRaisesRegex(RuntimeError, "provider indisponible"):
                cgs._review_chunk_once("prompt", "groupe", 1)

        post.assert_called_once()


class FolderCourseCountWiringTest(unittest.TestCase):
    def test_resolves_count_from_exact_folder_playlist(self):
        with patch(
            "services.day_playlist_service.resolve_folder_playlist",
            return_value={
                "schema_version": 2,
                "playlist_items": _playlist(6),
            },
        ):
            self.assertEqual(
                cgs.resolve_folder_content_course_count(42),
                6,
            )

    def test_rejects_corrupt_manifest_count(self):
        with patch(
            "services.day_playlist_service.resolve_folder_playlist",
            return_value={
                "schema_version": 2,
                "playlist_items": _playlist(0),
            },
        ):
            with self.assertRaisesRegex(ValueError, "entre 1 et 10"):
                cgs.resolve_folder_content_course_count(42)

class HrContentJobDynamicCountTest(unittest.TestCase):
    def test_manual_content_creation_route_is_retired(self):
        app = Flask(__name__)
        app.secret_key = "retired-content-job"
        app.register_blueprint(create_hr_blueprint())
        client = app.test_client()
        with client.session_transaction() as session:
            session["is_admin"] = True
            session["admin_account_type"] = "legacy_admin"

        with patch(
            "routes.hr_routes.HR_ENABLED",
            True,
        ), patch.object(
            cgs,
            "extract_sub_parts",
        ) as extract:
            response = client.post(
                "/api/hr/cours-folders/9/content-job",
                json={"program_text": "Programme " * 10},
            )

        self.assertEqual(response.status_code, 410, response.get_json())
        self.assertEqual(response.get_json()["code"], "local_generation_retired")
        extract.assert_not_called()


class DynamicCourseProgressAndContextTest(unittest.TestCase):
    def test_single_course_plan_uses_one_light_recap_and_slide_free_closing(self):
        playlist = [("course_01.mp3", 2100, "cours", 1)]
        raw_plan = {
            "courses": [
                {
                    "course_number": 1,
                    "course_title": "Chapitre unique",
                    "parts": [
                        {"title": "Repère 1"},
                        {"title": "Repère 2"},
                        {"title": "Repère 3"},
                    ],
                    "course_conclusion": {
                        "must_include": ["récapitulatif exhaustif de toute la journée"],
                        "teaching_beats": [{
                            "beat_id": "duplicate-heavy-conclusion",
                            "type": "warning",
                            "slide_anchor": {"enabled": True, "template_type": "warning"},
                        }],
                    },
                    "day_conclusion": {
                        "must_include": ["récapitulatif global de la journée"],
                    },
                }
            ]
        }

        plan = cgs._normalize_structured_course_plans(
            raw_plan,
            job={"folder_position": 0, "nb_days": 5},
            playlist_items=playlist,
            sub_parts=["Chapitre unique"],
        )

        course = plan["courses"][0]
        conclusion = course["course_conclusion"]
        day_closing = course["day_conclusion"]
        self.assertTrue(conclusion["single_course_light"])
        self.assertTrue(day_closing["single_course_light"])
        self.assertTrue(day_closing["suppress_slide"])
        self.assertLessEqual(conclusion["target_words"], 260)
        self.assertLessEqual(day_closing["target_words"], 80)
        self.assertIn("deux ou trois repères", " ".join(conclusion["must_include"]))
        self.assertIn("sans nouveau récapitulatif", " ".join(day_closing["must_include"]))
        self.assertNotIn("exhaustif", " ".join(conclusion["must_include"]))
        self.assertNotIn("global", " ".join(day_closing["must_include"]))
        self.assertEqual(len(conclusion["teaching_beats"]), 1)

    def test_single_course_day_closing_prompt_forbids_second_recap(self):
        guard = cgs._structured_section_scope_guard({
            "kind": "day_conclusion",
            "single_course_light": True,
        })

        self.assertIn("une à trois phrases", guard)
        self.assertIn("ne récapitule aucun contenu", guard)
        self.assertIn("ni nouvelle synthèse", guard)

    def test_single_course_before_qa_still_gets_a_light_course_conclusion(self):
        playlist = [
            ("course_01.mp3", 2100, "cours", 1),
            ("qa_01.mp3", 600, "qa", 1),
        ]
        plan = cgs._normalize_structured_course_plans(
            {
                "courses": [{
                    "course_number": 1,
                    "course_title": "Chapitre unique",
                    "parts": [{"title": "A"}, {"title": "B"}],
                }],
            },
            job={"folder_position": 0, "nb_days": 1},
            playlist_items=playlist,
            sub_parts=["Chapitre unique"],
        )

        course = plan["courses"][0]
        self.assertTrue(course["course_conclusion"]["single_course_light"])
        self.assertLessEqual(course["course_conclusion"]["target_words"], 260)
        self.assertIsNone(course["day_conclusion"])
        self.assertEqual(
            course["opening"]["target_words"]
            + sum(part["target_words"] for part in course["parts"])
            + course["course_conclusion"]["target_words"],
            course["target_words"],
        )

    def test_position_context_uses_explicit_or_playlist_total(self):
        explicit = cgs._build_course_position_context(
            sub_part_index=4,
            passe=1,
            total_courses=6,
        )
        inferred = cgs._build_course_position_context(
            sub_part_index=3,
            passe=2,
            playlist_spec=_playlist(5),
        )

        self.assertIn("Cours de la journée : 5/6.", explicit)
        self.assertIn("Cours de la journée : 4/5.", inferred)

    def test_editorial_profile_maps_relative_final_course(self):
        final_profile = cgs._course_slot_prompt_profile(
            5,
            1,
            total_courses=5,
        )
        late_profile = cgs._course_slot_prompt_profile(
            8,
            2,
            total_courses=10,
        )

        self.assertIn("Cours 5 — consolidation et clôture", final_profile)
        self.assertTrue(late_profile)
        self.assertIn("Cours 8", late_profile)

    def test_temporal_card_uses_spoken_dates_and_precise_relative_markers(self):
        snapshot = {
            "days": [
                {
                    "day_index": 1,
                    "date": "2026-08-13",
                    "blocks": [
                        {"block_type": "course", "start_minute": 540, "duration_minutes": 60},
                        {"block_type": "course", "start_minute": 600, "duration_minutes": 60},
                    ],
                },
                {
                    "day_index": 2,
                    "date": "2026-08-14",
                    "blocks": [
                        {"block_type": "course", "start_minute": 840, "duration_minutes": 60},
                    ],
                },
            ]
        }
        with patch(
            "repositories.pipeline_repository.get_pipeline_job",
            return_value={"schedule_snapshot_json": snapshot},
        ):
            first = cgs._build_course_temporal_card(
                formation_job_id=7,
                folder_position=0,
                sub_part_index=0,
            )
            second = cgs._build_course_temporal_card(
                formation_job_id=7,
                folder_position=0,
                sub_part_index=1,
            )

        self.assertIn("jeudi treize août deux mille vingt-six", first)
        self.assertIn("neuf heures", first)
        self.assertIn("formulation orale autorisée : juste après", first)
        self.assertIn("vendredi quatorze août deux mille vingt-six", second)
        self.assertIn("formulation orale autorisée : demain", second)

    def test_final_qa_temporal_closing_uses_next_day_in_spoken_form(self):
        snapshot = {
            "days": [
                {"day_index": 1, "date": "2026-08-13", "blocks": []},
                {"day_index": 2, "date": "2026-08-14", "blocks": []},
            ]
        }
        with patch(
            "repositories.pipeline_repository.get_pipeline_job",
            return_value={"schedule_snapshot_json": snapshot},
        ):
            closing = cgs._build_day_temporal_closing(
                formation_job_id=7,
                folder_position=0,
            )

        self.assertIn("demain", closing)
        self.assertIn("vendredi quatorze août deux mille vingt-six", closing)
        self.assertNotRegex(closing, r"\d")

    def test_final_qa_temporal_closing_marks_end_of_formation(self):
        snapshot = {
            "days": [
                {"day_index": 1, "date": "2026-08-13", "blocks": []},
            ]
        }
        with patch(
            "repositories.pipeline_repository.get_pipeline_job",
            return_value={"schedule_snapshot_json": snapshot},
        ):
            closing = cgs._build_day_temporal_closing(
                formation_job_id=7,
                folder_position=0,
            )

        self.assertEqual(
            closing,
            "Cette séance est terminée. Nous arrivons au terme de cette formation.",
        )

    def test_late_temporal_closing_is_added_only_when_a_course_ends_the_day(self):
        closing = "Cette séance est terminée. Nous nous retrouverons demain."
        final_course = [
            {"bloc_number": 1, "text": "Conclusion pédagogique.", "dirty": False}
        ]
        final_qa = [
            {"bloc_number": 1, "text": "Conclusion pédagogique.", "dirty": False}
        ]

        applied = cgs._apply_late_temporal_closing_to_final_course(
            final_course,
            [("course_01.mp3", 3600, "cours", 1)],
            closing,
        )
        skipped = cgs._apply_late_temporal_closing_to_final_course(
            final_qa,
            [
                ("course_01.mp3", 3600, "cours", 1),
                ("qa_01.mp3", 600, "qa", 1),
            ],
            closing,
        )

        self.assertTrue(applied)
        self.assertTrue(final_course[0]["text"].endswith(closing))
        self.assertTrue(final_course[0]["dirty"])
        self.assertFalse(skipped)
        self.assertEqual(final_qa[0]["text"], "Conclusion pédagogique.")

    def test_mock_generation_reports_manifest_course_count(self):
        progress = Mock()
        job = {
            "id": 1,
            "formation_job_id": None,
            "platform_id": 8,
            "program_text": "Programme",
            "program_title": "TP Test",
            "sub_parts": [f"Thème {index}" for index in range(1, 6)],
            "from_scratch": False,
            "module_contents": {},
            "total_words": 0,
        }
        with patch.object(
            cgs,
            "get_job_from_db",
            return_value=job,
        ), patch.object(
            cgs,
            "_playlist_items_for_platform",
            return_value=_playlist(5),
        ), patch.object(
            cgs,
            "_get_completed_segments",
            return_value=set(),
        ), patch.object(
            cgs,
            "_content_parallel_subpart_workers",
            return_value=1,
        ), patch.object(
            cgs,
            "_update_job_db",
        ), patch.object(
            cgs,
            "_save_segment_db",
        ), patch.object(
            cgs,
            "_assemble_and_upload",
            return_value=(123, "cours.txt"),
        ), patch.object(
            cgs.time,
            "sleep",
        ):
            cgs.run_content_generation(
                folder_id=9,
                on_progress=progress,
                mode="mock",
            )

        self.assertTrue(progress.called)
        self.assertEqual(
            {call.args[1] for call in progress.call_args_list},
            {5},
        )
        messages = [call.args[4] for call in progress.call_args_list]
        self.assertTrue(
            any("Sous-partie 5/5" in message for message in messages),
            messages,
        )


if __name__ == "__main__":
    unittest.main()
