import unittest

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

    def test_fallback_day_has_seven_audio_slots(self):
        day = fps._fallback_day_program(
            "TP Test",
            2,
            "MODULE 1 : accueil et relation client. MODULE 2 : diagnostic.",
            1,
            "json invalide",
        )

        self.assertEqual(day["day_number"], 1)
        self.assertEqual(day["hours"], 7)
        self.assertEqual(len(day["sub_parts"]), len(fps.COURSE_AUDIO_SLOTS))
        self.assertIn("generation_warning", day)


if __name__ == "__main__":
    unittest.main()
