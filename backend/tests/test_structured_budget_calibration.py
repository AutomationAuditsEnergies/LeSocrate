import unittest
from unittest.mock import patch

from services import content_generation_service as cgs


def words(count):
    return " ".join(f"mot{i}" for i in range(count))


class StructuredBudgetCalibrationTest(unittest.TestCase):
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

        with patch.object(cgs, "_anthropic_post", return_value=words(99)):
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

        with patch.object(cgs, "_anthropic_post", return_value=short_text):
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


if __name__ == "__main__":
    unittest.main()
