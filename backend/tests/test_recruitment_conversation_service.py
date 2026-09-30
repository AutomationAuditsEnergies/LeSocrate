import unittest
from unittest.mock import patch

from services.recruitment_conversation_service import interpret_recruitment_answer


class RecruitmentConversationServiceTest(unittest.TestCase):
    def test_rncp_question_names_the_training_to_deliver(self):
        result = interpret_recruitment_answer("rncpCode", "")

        self.assertEqual(
            result["reply"],
            "Quel est le code RNCP de la formation que vous souhaitez dispenser ?",
        )

    @patch("services.recruitment_conversation_service._llm_post")
    def test_rejects_vague_training_even_when_model_accepts_it(self, llm_post):
        llm_post.side_effect = [
            '{"understanding": "Demande une formation vague", "proposed_updates": '
            '{"trainingName": "une formation longue"}}',
            '{"reply": "J’ai besoin de l’intitulé exact du titre professionnel. Quel est-il ?"}',
        ]

        result = interpret_recruitment_answer("trainingName", "une formation longue")

        self.assertFalse(result["answered"])
        self.assertIn("intitulé exact", result["reply"])
        self.assertIn("trainingName", result["rejected_updates"])

    @patch("services.recruitment_conversation_service._llm_post")
    def test_rejects_title_professionnel_as_a_category_not_a_title(self, llm_post):
        llm_post.side_effect = [
            '{"understanding": "Catégorie générique", "proposed_updates": '
            '{"trainingName": "Un titre professionnel"}}',
            '{"reply": "Il me faut l’intitulé exact du titre professionnel. Quel est son nom ?"}',
        ]

        result = interpret_recruitment_answer("trainingName", "Un titre professionnel")

        self.assertFalse(result["answered"])
        self.assertIn("intitulé exact", result["reply"])

    @patch("services.recruitment_conversation_service._llm_post")
    def test_extracts_requested_value_from_a_longer_message(self, llm_post):
        llm_post.return_value = (
            '{"understanding": "Le professeur doit s’appeler Sofia", '
            '"proposed_updates": {"teacherName": "Sofia"}}'
        )

        result = interpret_recruitment_answer(
            "teacherName",
            "Je ne sais pas encore pour les dates, mais appelez-la Sofia.",
        )

        self.assertTrue(result["answered"])
        self.assertEqual(result["value"], "Sofia")
        self.assertEqual(result["accepted_updates"], {"teacherName": "Sofia"})
        llm_post.assert_called_once()

    @patch("services.recruitment_conversation_service._llm_post")
    def test_repeats_a_more_explicit_question_when_field_is_missing(self, llm_post):
        llm_post.side_effect = [
            '{"understanding": "Demande pourquoi", "proposed_updates": {}}',
            '{"reply": "Pour continuer, j’ai besoin du code RNCP. Par exemple : « 35304 »."}',
        ]

        result = interpret_recruitment_answer("rncpCode", "Pourquoi ?", attempt=2)

        self.assertFalse(result["answered"])
        self.assertIn("Pour continuer", result["reply"])
        self.assertIn("35304", result["reply"])

    @patch("services.recruitment_conversation_service._llm_post")
    def test_first_clarification_is_a_direct_question(self, llm_post):
        llm_post.side_effect = [
            '{"understanding": "Nom hésitant", "proposed_updates": {}}',
            '{"reply": "Quel nom souhaitez-vous donner au professeur IA ?"}',
        ]

        result = interpret_recruitment_answer("teacherName", "Pierre peut-être")

        self.assertEqual(result["reply"], "Quel nom souhaitez-vous donner au professeur IA ?")

    @patch("services.recruitment_conversation_service._llm_post")
    def test_acknowledgement_continues_with_contextual_guidance(self, llm_post):
        llm_post.side_effect = [
            '{"understanding": "L’utilisateur accepte de continuer", "proposed_updates": {}}',
            '{"reply": "D’accord, avançons ensemble. Pour identifier la formation, '
            'quel est son code RNCP ?"}',
        ]

        result = interpret_recruitment_answer("rncpCode", "ok")

        self.assertFalse(result["answered"])
        self.assertEqual(
            result["reply"],
            "D’accord, avançons ensemble. Pour identifier la formation, quel est son code RNCP ?",
        )
        self.assertEqual(llm_post.call_count, 2)

    @patch("services.recruitment_conversation_service._llm_post")
    def test_uncertain_answer_is_guided_instead_of_treated_as_off_topic(self, llm_post):
        llm_post.side_effect = [
            '{"understanding": "L’utilisateur ne choisit pas de code", "proposed_updates": {}}',
            '{"reply": "Ce n’est pas grave si vous ne l’avez pas encore. Le code RNCP '
            'figure généralement sur la fiche de la formation ; pouvez-vous la consulter ?"}',
        ]

        result = interpret_recruitment_answer("rncpCode", "n'importe quoi")

        self.assertFalse(result["answered"])
        self.assertTrue(result["reply"].startswith("Ce n’est pas grave"))
        self.assertIn("pouvez-vous la consulter ?", result["reply"])

    @patch("services.recruitment_conversation_service._llm_post")
    def test_real_off_topic_message_is_reoriented(self, llm_post):
        llm_post.side_effect = [
            '{"understanding": "Question sur la météo", "proposed_updates": {}}',
            '{"reply": "Je ne peux pas prévoir la météo de demain. Revenons à votre '
            'nouveau professeur : quel est le code RNCP de sa formation ?"}',
        ]

        result = interpret_recruitment_answer("rncpCode", "Quel temps fera-t-il demain ?")

        self.assertFalse(result["answered"])
        self.assertTrue(result["reply"].startswith("Je ne peux pas prévoir la météo"))
        self.assertIn("quel est le code RNCP", result["reply"])

    @patch("services.recruitment_conversation_service._llm_post")
    def test_social_greeting_is_answered_before_explaining_the_objective(self, llm_post):
        llm_post.side_effect = [
            '{"understanding": "Salutation", "proposed_updates": {}}',
            '{"reply": "Bonjour ! Que puis-je faire pour vous ? Ici, nous allons configurer '
            'votre professeur IA ; connaissez-vous le code RNCP de la formation ?"}',
        ]

        result = interpret_recruitment_answer("rncpCode", "hello")

        self.assertFalse(result["answered"])
        self.assertTrue(result["reply"].startswith("Bonjour !"))
        self.assertIn("connaissez-vous le code RNCP", result["reply"])

    @patch("services.recruitment_conversation_service._llm_post")
    def test_social_question_is_answered_before_returning_to_the_goal(self, llm_post):
        llm_post.side_effect = [
            '{"understanding": "Question de politesse", "proposed_updates": {}}',
            '{"reply": "Ça va bien, merci de demander ! Reprenons la création de votre '
            'professeur IA : quel est le code RNCP de la formation ?"}',
        ]

        result = interpret_recruitment_answer("rncpCode", "comment ça va ?")

        self.assertTrue(result["reply"].startswith("Ça va bien, merci"))
        self.assertIn("quel est le code RNCP", result["reply"])

    @patch("services.recruitment_conversation_service._llm_post")
    def test_guides_a_lost_user_before_asking_one_actionable_question(self, llm_post):
        llm_post.side_effect = [
            '{"understanding": "Demande comment procéder", "proposed_updates": {}}',
            '{"reply": "Je vais vous guider. Pour commencer, retrouvez le code RNCP sur la '
            'fiche de la formation. Quel est ce code ?"}',
        ]

        result = interpret_recruitment_answer(
            "rncpCode",
            "Qu'est-ce que je dois faire ?",
        )

        self.assertFalse(result["answered"])
        self.assertIn("Je vais vous guider", result["reply"])
        self.assertIn("Pour commencer", result["reply"])
        self.assertIn("Quel est ce code ?", result["reply"])
        self.assertEqual(llm_post.call_count, 2)

    @patch("services.recruitment_conversation_service._llm_post")
    def test_teacher_name_guidance_marks_personalization_as_the_last_step(self, llm_post):
        llm_post.side_effect = [
            '{"understanding": "Demande de l’aide pour le nom", "proposed_updates": {}}',
            '{"reply": "Pour terminer, choisissez un prénom simple pour le professeur. '
            'Quel nom voulez-vous lui donner ?"}',
        ]

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
        llm_post.return_value = (
            '{"understanding": "La formation durera huit semaines", '
            '"proposed_updates": {"trainingWeeks": 8}}'
        )

        result = interpret_recruitment_answer(
            "trainingWeeks",
            "Je pense que la formation durera huit semaines.",
        )

        self.assertTrue(result["answered"])
        self.assertEqual(result["value"], 8)
        self.assertEqual(result["accepted_updates"], {"trainingWeeks": 8})


if __name__ == "__main__":
    unittest.main()
