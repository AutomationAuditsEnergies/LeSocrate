import json
import unittest

from utils.planning_summary import summarize_v2_schedule


class PlanningSummaryTest(unittest.TestCase):
    def test_summarizes_only_real_course_blocks(self):
        day = {
            "blocks": [
                {"block_type": "course", "duration_minutes": 35},
                {"block_type": "qa", "duration_minutes": 10},
                {"block_type": "pause", "duration_minutes": 15},
            ]
        }
        schedule = {
            "schema_version": 2,
            "days": [{**day, "day_index": index} for index in range(1, 6)],
        }

        summary = summarize_v2_schedule(json.dumps(schedule), schema_version=2)

        self.assertEqual(summary["day_count"], 5)
        self.assertEqual(summary["course_count"], 5)
        self.assertEqual(summary["course_minutes"], 175)
        self.assertEqual(summary["uniform_daily_course_count"], 1)
        self.assertEqual(summary["uniform_course_duration_minutes"], 35)

    def test_does_not_summarize_legacy_or_incomplete_schedules(self):
        self.assertIsNone(summarize_v2_schedule({"days": []}, schema_version=1))
        self.assertIsNone(summarize_v2_schedule({"days": []}, schema_version=2))


if __name__ == "__main__":
    unittest.main()
