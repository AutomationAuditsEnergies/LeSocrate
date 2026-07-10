import unittest

from services.formation_health_service import (
    _expected_structured_segment_count,
    _humanization_is_embedded,
)


class StructuredPipelineHealthTests(unittest.TestCase):
    def test_expected_segments_are_one_per_structured_sub_part(self):
        job = {"nb_days": 1}
        daily_programs = [{"sub_parts": [{"title": str(i)} for i in range(7)]}]

        self.assertEqual(_expected_structured_segment_count(job, daily_programs), 7)

    def test_expected_segments_fall_back_to_seven_slots_per_day(self):
        self.assertEqual(_expected_structured_segment_count({"nb_days": 2}, []), 14)

    def test_auto_pilot_embeds_humanization_in_initial_generation(self):
        self.assertTrue(_humanization_is_embedded({"auto_pilot_enabled": True}))
        self.assertFalse(_humanization_is_embedded({"auto_pilot_enabled": False}))


if __name__ == "__main__":
    unittest.main()
