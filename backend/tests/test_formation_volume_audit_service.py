import unittest
from unittest.mock import patch

from services import formation_volume_audit_service as volume_audit


class FormationVolumeAuditServiceTest(unittest.TestCase):
    def test_uses_pipeline_repository_for_postgres_job(self):
        rows = [
            {
                "folder_id": 101,
                "folder_name": "Jour 1",
                "position": 0,
                "segment_id": index,
                "sub_part_index": index - 1,
                "sub_part_name": f"Segment {index}",
                "passe": 1,
                "text_content": "un deux trois",
                "word_count": 3,
            }
            for index in range(1, 8)
        ]
        budget = {
            "target_words": 100,
            "min_words": 90,
            "max_words": 110,
            "words_per_minute": None,
            "course_seconds": None,
            "speakable_seconds": None,
            "final_silence_sec": None,
        }

        with (
            patch.object(
                volume_audit,
                "_course_day_budget_for_volume",
                return_value=budget,
            ),
            patch.object(
                volume_audit.pipeline_repo,
                "get_pipeline_job",
                return_value={"id": 13},
            ),
            patch.object(
                volume_audit.pipeline_repo,
                "list_volume_audit_rows_for_folders",
                return_value=rows,
            ) as list_rows,
            patch(
                "services.formation_pipeline_service.get_expected_course_folders",
                return_value={"folder_ids": [101]},
            ),
            patch(
                "services.content_generation_service.count_tts_spoken_words",
                side_effect=lambda text: len(text.split()),
            ),
        ):
            audit = volume_audit.compute_volume_audit(13)

        self.assertEqual(len(audit["folders"]), 1)
        self.assertEqual(audit["folders"][0]["segments_count"], 7)
        self.assertEqual(audit["folders"][0]["total_words"], 21)
        list_rows.assert_called_once_with([101])


if __name__ == "__main__":
    unittest.main()
