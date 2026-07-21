import unittest
from unittest.mock import patch

from services.recruitment_conversation_service import interpret_recruitment_answer


class RecruitmentConversationServiceTest(unittest.TestCase):
    @patch("services.recruitment_conversation_service._llm_post")
    def test_rejects_vague_training_even_when_model_accepts_it(self, llm_post):
        llm_post.return_value = '{"answered": true, "value": "une formation longue"}'

        result = interpret_recruitment_answer("trainingName", "une formation longue")

        self.assertFalse(result["answered"])
        self.assertIn("intitulé", result["reply"])

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
        self.assertIn("toujours", result["reply"])
        self.assertIn("35304", result["reply"])

    @patch("services.recruitment_conversation_service._llm_post")
    def test_falls_back_without_letting_provider_failure_block_the_form(self, llm_post):
        llm_post.side_effect = RuntimeError("provider unavailable")

        result = interpret_recruitment_answer("trainingDays", "Nous prévoyons 52 jours")

        self.assertEqual(result["value"], 52)


if __name__ == "__main__":
    unittest.main()
