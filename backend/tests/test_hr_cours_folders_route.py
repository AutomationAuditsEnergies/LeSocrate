import unittest
from unittest.mock import patch

from flask import Flask

from routes.hr_routes import create_hr_blueprint


class HrCoursFoldersRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(create_hr_blueprint(None))
        self.client = app.test_client()

    def test_cours_folders_route_uses_migrated_pipeline_repository(self):
        with self.client.session_transaction() as sess:
            sess["is_admin"] = True

        repository_result = {
            "folders": [{
                "id": 9,
                "name": "Jour 1 - Accueil",
                "created_at": "2026-07-04T08:00:00",
                "document_count": 1,
                "position": 0,
            }],
            "platform_id": 12,
            "source_platform_id": None,
        }

        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.list_course_folder_rows_for_platform",
            return_value=repository_result,
        ) as list_folders, patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("legacy sqlite lookup should not be used"),
        ):
            resp = self.client.get("/api/hr/platforms/12/cours-folders")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["platform_id"], 12)
        self.assertEqual(data["folders"][0]["id"], 9)
        self.assertEqual(data["folders"][0]["document_count"], 1)
        list_folders.assert_called_once_with(12)


if __name__ == "__main__":
    unittest.main()
