import json
import os
import unittest

from services.formation_review_artifact_service import (
    REVIEW_ARTIFACT_ROOT,
    extract_json,
    review_artifact_dir,
)


class FormationReviewArtifactServiceTest(unittest.TestCase):
    def test_keeps_the_existing_review_queue_layout(self):
        self.assertEqual(
            review_artifact_dir(42, "review"),
            os.path.join(REVIEW_ARTIFACT_ROOT, "job_42", "step_review"),
        )

    def test_extracts_historical_fenced_json_output(self):
        payload = extract_json(
            "Rapport historique\n```json\n{\"reviews\": [{\"id\": 1}]}\n```"
        )

        self.assertEqual(
            json.loads(payload),
            {"reviews": [{"id": 1}]},
        )


if __name__ == "__main__":
    unittest.main()
