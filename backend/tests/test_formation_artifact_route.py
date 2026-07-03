import unittest
from unittest.mock import patch

from flask import Flask

from routes.formation_routes import formation_bp


class FormationArtifactRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(formation_bp)
        self.client = app.test_client()

    def test_artifact_route_uses_pipeline_repository_folder_lookup(self):
        with self.client.session_transaction() as sess:
            sess["is_admin"] = True

        with patch(
            "routes.formation_routes.get_job",
            return_value={"id": 8},
        ), patch(
            "repositories.pipeline_repository.get_content_generation_job_by_folder",
            return_value={
                "id": 9,
                "platform_id": 12,
                "formation_job_id": 8,
                "name": "Jour 1",
            },
        ) as folder_lookup, patch(
            "services.content_pipeline.artifacts.load_content_artifact",
            return_value={"structured_course_plan": {"courses": [{"course_number": 1}]}},
        ) as artifact_loader, patch(
            "database.db.get_db_connection",
            side_effect=AssertionError("legacy sqlite lookup should not be used"),
        ):
            resp = self.client.get("/api/formation/8/content/9/artifact/content-plan.json")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["folder_name"], "Jour 1")
        folder_lookup.assert_called_once_with(9)
        artifact_loader.assert_called_once_with(12, 9, "content-plan.json")


if __name__ == "__main__":
    unittest.main()
