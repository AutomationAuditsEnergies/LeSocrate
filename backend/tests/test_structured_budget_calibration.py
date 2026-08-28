import unittest
from unittest.mock import patch

from services import content_generation_service as cgs


def words(count):
    return " ".join(f"mot{i}" for i in range(count))


class StructuredBudgetCalibrationTest(unittest.TestCase):
    def test_one_course_day_accepts_the_final_audio_budget_margin(self):
        course_plan = {
            "course_number": 1,
            "total_courses": 1,
            "target_words": 6498,
        }

        status = cgs._structured_course_budget_status(course_plan, words(6573))

        self.assertTrue(status["ok"])
        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["max_words"], 6848)

    def test_course_budget_still_rejects_text_beyond_the_daily_margin(self):
        course_plan = {
            "course_number": 1,
            "total_courses": 1,
            "target_words": 6498,
        }

        status = cgs._structured_course_budget_status(course_plan, words(6849))

        self.assertFalse(status["ok"])
        self.assertEqual(status["status"], "too_long")

    def test_fixed_daily_margin_is_shared_between_multiple_courses(self):
        course_plan = {
            "course_number": 1,
            "total_courses": 4,
            "target_words": 1000,
        }

        self.assertEqual(cgs._structured_course_max_words(course_plan), 1088)

    def test_residual_shortfall_is_strict_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(cgs._structured_allow_residual_too_short())

    def test_residual_shortfall_compat_flag_can_be_enabled(self):
        with patch.dict("os.environ", {"FORMATION_STRUCTURED_ALLOW_RESIDUAL_TOO_SHORT": "1"}):
            self.assertTrue(cgs._structured_allow_residual_too_short())

    def test_section_budget_calibration_enriches_short_section_to_local_target(self):
        course_plan = {
            "course_number": 1,
            "course_title": "Accueil multicanal",
            "target_words": 150,
            "opening": {"title": "Intro", "target_words": 100},
            "parts": [],
            "course_conclusion": {"title": "Conclusion", "target_words": 50},
        }
        draft = {
            "course_text": f"{words(60)}\n\n{words(50)}",
            "sections": [
                {
                    "kind": "opening",
                    "label": "introduction",
                    "title": "Intro",
                    "target_words": 100,
                    "word_count": 60,
                    "text": words(60),
                },
                {
                    "kind": "course_conclusion",
                    "label": "conclusion du cours",
                    "title": "Conclusion",
                    "target_words": 50,
                    "word_count": 50,
                    "text": words(50),
                },
            ],
        }

        with patch.object(cgs, "_deepseek_post", return_value=words(99)):
            calibrated_text, calibration = cgs._calibrate_structured_course_sections(
                job={"program_title": "TP", "folder_name": "Jour 1"},
                course_plan=course_plan,
                draft=draft,
                module_content="source",
            )

        self.assertEqual(calibration["status"], "ok")
        self.assertEqual(cgs.count_tts_spoken_words(calibrated_text), 149)
        self.assertEqual(calibration["sections"][0]["status"], "ok")
        self.assertGreater(calibration["sections"][0]["after_words"], calibration["sections"][0]["before_words"])

    def test_short_section_is_not_marked_ok_when_model_does_not_expand(self):
        section = {"kind": "opening", "title": "Intro", "target_words": 100}
        short_text = words(60)

        with patch.object(cgs, "_deepseek_post", return_value=short_text):
            calibrated_text, calibration = cgs._calibrate_structured_section_text(
                job={"program_title": "TP", "folder_name": "Jour 1"},
                course_plan={
                    "course_number": 1,
                    "course_title": "Accueil multicanal",
                    "target_words": 100,
                    "opening": section,
                    "parts": [],
                    "course_conclusion": {"target_words": 0},
                },
                section=section,
                text=short_text,
                module_content="source",
            )

        self.assertEqual(calibrated_text, short_text)
        self.assertEqual(calibration["status"], "too_short")
        self.assertFalse(calibration["changed"])

    def test_course_budget_topup_adds_missing_words_until_range(self):
        course_plan = {
            "course_number": 2,
            "course_title": "Traiter une demande client",
            "target_words": 150,
        }
        current_text = f"{words(80)}\n\nConclusion {words(5)}"

        with patch.object(cgs, "_deepseek_post", return_value=words(60)):
            repaired_text, repair = cgs._repair_structured_course_text_to_budget(
                job={"program_title": "TP", "folder_name": "Jour 1"},
                course_plan=course_plan,
                text=current_text,
                module_content="source",
            )

        self.assertEqual(repair["status"], "ok")
        self.assertGreaterEqual(cgs.count_tts_spoken_words(repaired_text), repair["min_words"])
        self.assertIn("Conclusion", repaired_text.split("\n\n")[-1])

    def test_course_budget_topup_rephrases_too_long_addition(self):
        course_plan = {
            "course_number": 2,
            "course_title": "Traiter une demande client",
            "target_words": 150,
        }
        current_text = f"{words(80)}\n\nConclusion {words(5)}"

        with patch.object(cgs, "_deepseek_post", side_effect=[words(500), words(60)]):
            repaired_text, repair = cgs._repair_structured_course_text_to_budget(
                job={"program_title": "TP", "folder_name": "Jour 1"},
                course_plan=course_plan,
                text=current_text,
                module_content="source",
            )

        self.assertEqual(repair["status"], "ok")
        self.assertLessEqual(cgs.count_tts_spoken_words(repaired_text), 150)
        self.assertEqual(repair["attempts"][0]["raw_addition_words"], 500)
        self.assertTrue(repair["attempts"][0]["rephrased_to_fit"])
        self.assertEqual(repair["attempts"][0]["addition_words"], 60)

    def test_section_budget_topup_adds_value_inside_underfilled_part(self):
        course_plan = {
            "course_number": 2,
            "course_title": "Traiter une demande client",
            "target_words": 240,
            "opening": {"title": "Intro", "target_words": 40},
            "parts": [
                {
                    "part_number": 1,
                    "title": "Qualifier la demande",
                    "target_words": 160,
                    "teaching_beats": [],
                },
            ],
            "course_conclusion": {"title": "Conclusion", "target_words": 40},
        }
        part_text = f"{words(80)}\n\ncloturelocale {words(19)}"
        sections = [
            {
                "kind": "opening",
                "label": "introduction",
                "title": "Intro",
                "target_words": 40,
                "word_count": 40,
                "text": words(40),
            },
            {
                "kind": "part",
                "label": "partie 1",
                "part_number": 1,
                "title": "Qualifier la demande",
                "target_words": 160,
                "word_count": 100,
                "text": part_text,
            },
            {
                "kind": "course_conclusion",
                "label": "conclusion du cours",
                "title": "Conclusion",
                "target_words": 40,
                "word_count": 40,
                "text": words(40),
            },
        ]

        with patch.object(cgs, "_deepseek_post", side_effect=[words(80), words(60)]):
            repaired_text, repaired_sections, repair = cgs._repair_structured_course_sections_to_budget(
                job={"program_title": "TP", "folder_name": "Jour 1"},
                course_plan=course_plan,
                sections=sections,
                module_content="source",
            )

        self.assertEqual(repair["status"], "ok")
        self.assertLessEqual(cgs.count_tts_spoken_words(repaired_text), 240)
        self.assertEqual(repair["attempts"][0]["raw_addition_words"], 80)
        self.assertTrue(repair["attempts"][0]["rephrased_to_fit"])
        self.assertEqual(repair["attempts"][0]["addition_words"], 60)
        repaired_part = next(section for section in repaired_sections if section["kind"] == "part")
        self.assertEqual(repaired_part["word_count"], 160)
        self.assertTrue(repaired_part["text"].split("\n\n")[-1].startswith("cloturelocale"))

    def test_course_calibration_uses_section_topup_when_course_still_short(self):
        course_plan = {
            "course_number": 2,
            "course_title": "Traiter une demande client",
            "target_words": 240,
            "opening": {"title": "Intro", "target_words": 40},
            "parts": [
                {
                    "part_number": 1,
                    "title": "Qualifier la demande",
                    "target_words": 160,
                    "teaching_beats": [],
                },
            ],
            "course_conclusion": {"title": "Conclusion", "target_words": 40},
        }
        draft = {
            "course_text": f"{words(40)}\n\n{words(100)}\n\n{words(40)}",
            "sections": [
                {
                    "kind": "opening",
                    "label": "introduction",
                    "title": "Intro",
                    "target_words": 40,
                    "word_count": 40,
                    "text": words(40),
                },
                {
                    "kind": "part",
                    "label": "partie 1",
                    "part_number": 1,
                    "title": "Qualifier la demande",
                    "target_words": 160,
                    "word_count": 100,
                    "text": words(100),
                },
                {
                    "kind": "course_conclusion",
                    "label": "conclusion du cours",
                    "title": "Conclusion",
                    "target_words": 40,
                    "word_count": 40,
                    "text": words(40),
                },
            ],
        }

        def keep_section_text(**kwargs):
            section = kwargs["section"]
            return kwargs["text"], {
                "status": "ok",
                "changed": False,
                "min_words": 0,
                "max_words": section.get("target_words"),
            }

        with (
            patch.dict("os.environ", {"FORMATION_STRUCTURED_COURSE_DEFICIT_REPAIR_MAX_ATTEMPTS": "0"}),
            patch.object(cgs, "_calibrate_structured_section_text", side_effect=keep_section_text),
            patch.object(cgs, "_deepseek_post", return_value=words(60)),
        ):
            calibrated_text, calibration = cgs._calibrate_structured_course_sections(
                job={"program_title": "TP", "folder_name": "Jour 1"},
                course_plan=course_plan,
                draft=draft,
                module_content="source",
            )

        self.assertEqual(calibration["status"], "ok")
        self.assertEqual(calibration["section_topup_repair"]["status"], "ok")
        self.assertGreaterEqual(cgs.count_tts_spoken_words(calibrated_text), calibration["min_words"])
        repaired_part = next(
            section for section in calibration["calibrated_sections"]
            if section["kind"] == "part"
        )
        self.assertEqual(repaired_part["word_count"], 160)

    def test_course_deficit_repair_expands_part_when_course_stays_short(self):
        course_plan = {
            "course_number": 2,
            "course_title": "Traiter une demande client",
            "target_words": 350,
            "opening": {"title": "Intro", "target_words": 50},
            "parts": [
                {
                    "part_number": 1,
                    "title": "Qualifier la demande",
                    "target_words": 250,
                    "teaching_beats": [],
                },
            ],
            "course_conclusion": {"title": "Conclusion", "target_words": 50},
        }
        draft = {
            "course_text": f"{words(50)}\n\n{words(150)}\n\n{words(50)}",
            "sections": [
                {
                    "kind": "opening",
                    "label": "introduction",
                    "title": "Intro",
                    "target_words": 50,
                    "word_count": 50,
                    "text": words(50),
                },
                {
                    "kind": "part",
                    "label": "partie 1",
                    "part_number": 1,
                    "title": "Qualifier la demande",
                    "target_words": 250,
                    "word_count": 150,
                    "text": words(150),
                },
                {
                    "kind": "course_conclusion",
                    "label": "conclusion du cours",
                    "title": "Conclusion",
                    "target_words": 50,
                    "word_count": 50,
                    "text": words(50),
                },
            ],
        }

        with patch.object(cgs, "_deepseek_post", side_effect=[words(150), words(245)]):
            calibrated_text, calibration = cgs._calibrate_structured_course_sections(
                job={"program_title": "TP", "folder_name": "Jour 1"},
                course_plan=course_plan,
                draft=draft,
                module_content="source",
            )

        self.assertEqual(calibration["status"], "ok")
        self.assertGreaterEqual(
            cgs.count_tts_spoken_words(calibrated_text),
            calibration["min_words"],
        )
        self.assertEqual(calibration["deficit_repair"]["status"], "ok")
        self.assertTrue(calibration["deficit_repair"]["changed"])
        repaired_part = next(
            section for section in calibration["calibrated_sections"]
            if section["kind"] == "part"
        )
        self.assertEqual(repaired_part["word_count"], 245)


if __name__ == "__main__":
    unittest.main()
