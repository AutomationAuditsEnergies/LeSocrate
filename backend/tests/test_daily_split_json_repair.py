import unittest
from unittest.mock import patch

from services import formation_pipeline_service as fps


class DailySplitJsonRepairTest(unittest.TestCase):
    def test_repairs_missing_comma_between_days(self):
        raw = """
        ```json
        {
          "days": [
            {
              "day_number": 1,
              "title": "Jour 1",
              "hours": 7,
              "sub_parts": []
            }
            {
              "day_number": 2,
              "title": "Jour 2",
              "hours": 7,
              "sub_parts": []
            }
          ]
        }
        ```
        """

        data = fps._clean_json(raw)
        days = fps._normalize_daily_payload(data, 1, 2, "TP Test")

        self.assertEqual([day["day_number"] for day in days], [1, 2])
        self.assertEqual(len(days[0]["sub_parts"]), len(fps.COURSE_AUDIO_SLOTS))
        self.assertEqual(days[0]["sub_parts"][0]["audio_slot"], "Cours 1")

    def test_invalid_response_is_delegated_to_the_durable_retry(self):
        with (
            patch.object(
                fps,
                "_deepseek_post",
                return_value="réponse sans JSON",
            ) as deepseek,
        ):
            with self.assertRaisesRegex(
                fps.DailySplitGenerationError,
                "Journée 1 impossible à générer correctement",
            ):
                fps._split_batch(
                    tp_name="TP Test",
                    nb_days=1,
                    global_program="MODULE 1 : accueil et relation client.",
                    day_start=1,
                    day_end=1,
                    model="test-model",
                )

        self.assertEqual(deepseek.call_count, 1)


if __name__ == "__main__":
    unittest.main()
