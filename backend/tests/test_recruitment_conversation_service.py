import unittest
from unittest.mock import patch

from services.recruitment_conversation_service import interpret_recruitment_answer


class RecruitmentConversationServiceTest(unittest.TestCase):
    @patch("services.recruitment_conversation_service._llm_post")
    def test_rejects_vague_training_even_when_model_accepts_it(self, llm_post):
        llm_post.return_value = '{"intent": "answer", "value": "une formation longue"}'

        result = interpret_recruitment_answer("trainingName", "une formation longue")

        self.assertFalse(result["answered"])
        self.assertIn("intitulé exact", result["reply"])

    @patch("services.recruitment_conversation_service._llm_post")
    def test_rejects_title_professionnel_as_a_category_not_a_title(self, llm_post):
        llm_post.return_value = '{"intent": "answer", "value": "Un titre professionnel"}'

        result = interpret_recruitment_answer("trainingName", "Un titre professionnel")

        self.assertFalse(result["answered"])
        self.assertIn("intitulé exact", result["reply"])

    @patch("services.recruitment_conversation_service._llm_post")
    def test_extracts_requested_value_from_a_longer_message(self, llm_post):
        llm_post.return_value = '{"intent": "answer", "value": "Sofia"}'

        result = interpret_recruitment_answer(
            "teacherName",
            "Je ne sais pas encore pour les dates, mais appelez-la Sofia.",
        )

        self.assertEqual(result, {"answered": True, "value": "Sofia", "reply": ""})

    @patch("services.recruitment_conversation_service._llm_post")
    def test_repeats_a_more_explicit_question_when_field_is_missing(self, llm_post):
        llm_post.return_value = '{"intent": "unclear", "value": null}'

        result = interpret_recruitment_answer("rncpCode", "Pourquoi ?", attempt=2)

        self.assertFalse(result["answered"])
        self.assertIn("Pour continuer", result["reply"])
        self.assertIn("35304", result["reply"])

    @patch("services.recruitment_conversation_service._llm_post")
    def test_first_clarification_is_a_direct_question(self, llm_post):
        llm_post.return_value = '{"intent": "off_topic", "value": null}'

        result = interpret_recruitment_answer("teacherName", "Je veux recruter un professeur")

        self.assertEqual(result["reply"], "Quel nom souhaitez-vous donner au professeur IA ?")

    @patch("services.recruitment_conversation_service._llm_post")
    def test_guides_a_lost_user_before_asking_one_actionable_question(self, llm_post):
        llm_post.return_value = '{"intent": "help", "value": null}'

        result = interpret_recruitment_answer(
            "rncpCode",
            "Qu'est-ce que je dois faire ?",
        )

        self.assertFalse(result["answered"])
        self.assertIn("Je vais vous guider", result["reply"])
        self.assertIn("Pour commencer", result["reply"])
        self.assertIn("Quel est ce code ?", result["reply"])
        llm_post.assert_called_once()

    @patch("services.recruitment_conversation_service._llm_post")
    def test_teacher_name_guidance_marks_personalization_as_the_last_step(self, llm_post):
        llm_post.return_value = '{"intent": "help", "value": null}'

        result = interpret_recruitment_answer("teacherName", "Que dois-je choisir ?")

        self.assertFalse(result["answered"])
        self.assertIn("Pour terminer", result["reply"])
        self.assertIn("Quel nom voulez-vous lui donner ?", result["reply"])

    @patch("services.recruitment_conversation_service._llm_post")
    def test_does_not_guess_when_the_nlp_provider_is_unavailable(self, llm_post):
        llm_post.side_effect = RuntimeError("provider unavailable")

        result = interpret_recruitment_answer("trainingDays", "Nous prévoyons 52 jours")

        self.assertFalse(result["answered"])
        self.assertIsNone(result["value"])
        self.assertIn("ne peux pas interpréter", result["reply"])

    @patch("services.recruitment_conversation_service._llm_post")
    def test_extracts_the_training_duration_in_weeks(self, llm_post):
        llm_post.return_value = '{"intent": "answer", "value": 8}'

        result = interpret_recruitment_answer(
            "trainingWeeks",
            "Je pense que la formation durera huit semaines.",
        )

        self.assertEqual(result, {"answered": True, "value": 8, "reply": ""})


if __name__ == "__main__":
    unittest.main()
