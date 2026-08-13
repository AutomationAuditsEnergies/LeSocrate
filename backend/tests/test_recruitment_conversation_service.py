import unittest
from unittest.mock import patch

from services.recruitment_conversation_service import interpret_recruitment_answer


class RecruitmentConversationServiceTest(unittest.TestCase):
    @patch("services.recruitment_conversation_service._llm_post")
    def test_rejects_vague_training_even_when_model_accepts_it(self, llm_post):
        llm_post.return_value = '{"answered": true, "value": "une formation longue"}'

        result = interpret_recruitment_answer("trainingName", "une formation longue")

        self.assertFalse(result["answered"])
        self.assertIn("intitulé exact", result["reply"])

    @patch("services.recruitment_conversation_service._llm_post")
    def test_rejects_title_professionnel_as_a_category_not_a_title(self, llm_post):
        llm_post.return_value = '{"answered": true, "value": "Un titre professionnel"}'

        result = interpret_recruitment_answer("trainingName", "Un titre professionnel")

        self.assertFalse(result["answered"])
        self.assertIn("catégorie de certification", result["reply"])
        self.assertIn("nom exact du titre professionnel", result["reply"])

    @patch("services.recruitment_conversation_service._llm_post")
    def test_extracts_requested_value_from_a_longer_message(self, llm_post):
        llm_post.return_value = '{"answered": true, "value": "Sofia"}'

        result = interpret_recruitment_answer(
            "teacherName",
            "Je ne sais pas encore pour les dates, mais appelez-la Sofia.",
        )

        self.assertEqual(result, {"answered": True, "value": "Sofia", "reply": ""})

    @patch("services.recruitment_conversation_service._llm_post")
    def test_repeats_a_more_explicit_question_when_field_is_missing(self, llm_post):
        llm_post.return_value = '{"answered": false, "value": null}'

        result = interpret_recruitment_answer("rncpCode", "Pourquoi ?", attempt=2)

        self.assertFalse(result["answered"])
        self.assertIn("Pour continuer", result["reply"])
        self.assertIn("35304", result["reply"])

    @patch("services.recruitment_conversation_service._llm_post")
    def test_first_clarification_is_a_direct_question(self, llm_post):
        llm_post.return_value = '{"answered": false, "value": null}'

        result = interpret_recruitment_answer("teacherName", "Je veux recruter un professeur")

        self.assertEqual(result["reply"], "Quel nom souhaitez-vous donner au professeur IA ?")

    @patch("services.recruitment_conversation_service._llm_post")
    def test_falls_back_without_letting_provider_failure_block_the_form(self, llm_post):
        llm_post.side_effect = RuntimeError("provider unavailable")

        result = interpret_recruitment_answer("trainingDays", "Nous prévoyons 52 jours")

        self.assertEqual(result["value"], 52)


if __name__ == "__main__":
    unittest.main()
