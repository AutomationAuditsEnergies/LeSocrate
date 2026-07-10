import unittest
from unittest.mock import patch
import json

from flask import Flask

from services.formation_docx_service import build_course_docx
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
            sess["admin_account_type"] = "legacy_admin"

        with patch(
            "routes.formation_routes.get_job",
            return_value={"id": 8},
        ), patch(
            "repositories.pipeline_repository.course_folder_belongs_to_job",
            return_value=True,
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

    def test_content_list_uses_pipeline_repository_counts(self):
        with self.client.session_transaction() as sess:
            sess["is_admin"] = True
            sess["admin_account_type"] = "legacy_admin"

        job = {
            "id": 8,
            "status": "tts_launched",
            "daily_programs": json.dumps([{"day_number": 1, "title": "Jour 1", "sub_parts": []}]),
        }
        folders = [{
            "folder_id": 9,
            "name": "Jour 1",
            "position": 0,
            "platform_id": 12,
            "formation_job_id": 8,
        }]
        content_rows = [{
            "folder_id": 9,
            "content_job_id": 9,
            "status": "completed",
            "total_words": 67425,
            "current_sub_part": 6,
            "current_passe": 1,
            "error_message": None,
            "completed_segments": 7,
            "reviewed_segments": 7,
            "humanized_segments": 0,
            "review_error_segments": 0,
            "dirty_segments": 7,
        }]

        with patch(
            "routes.formation_routes.get_job",
            return_value=job,
        ), patch(
            "services.formation_pipeline_service.repair_orphan_content_folders",
            return_value=None,
        ), patch(
            "services.formation_pipeline_service.get_expected_course_folders",
            return_value={"expected_count": 1, "folders": folders, "duplicates": [], "missing": []},
        ), patch(
            "repositories.pipeline_repository.list_content_completion_rows_for_folders",
            return_value=content_rows,
        ) as content_lookup, patch(
            "services.script_slide_generation_service.get_latest_script_slide_deck",
            return_value={"deck_id": 4, "slides": [{}, {}], "stats": {"generation_mode": "anchor_first"}},
        ), patch(
            "database.db.get_db_connection",
            side_effect=AssertionError("legacy sqlite lookup should not be used"),
        ):
            resp = self.client.get("/api/formation/8/content")

        self.assertEqual(resp.status_code, 200)
        folder = resp.get_json()["folders"][0]
        self.assertEqual(folder["content_status"], "completed")
        self.assertEqual(folder["segments_reviewed"], 7)
        self.assertEqual(folder["segments_completed"], 7)
        self.assertEqual(folder["slide_count"], 2)
        content_lookup.assert_called_once_with([9])

    def test_docx_route_uses_migrated_docx_service(self):
        with self.client.session_transaction() as sess:
            sess["is_admin"] = True
            sess["admin_account_type"] = "legacy_admin"

        with patch(
            "routes.formation_routes.get_job",
            return_value={"id": 8},
        ), patch(
            "repositories.pipeline_repository.course_folder_belongs_to_job",
            return_value=True,
        ), patch(
            "services.formation_docx_service.build_course_docx",
            return_value=(b"docx-bytes", "jour1.docx"),
        ) as build_docx, patch(
            "database.db.get_db_connection",
            side_effect=AssertionError("legacy sqlite lookup should not be used"),
        ):
            resp = self.client.get("/api/formation/8/content/9/docx?version=current")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, b"docx-bytes")
        self.assertIn("attachment; filename=jour1.docx", resp.headers.get("Content-Disposition", ""))
        build_docx.assert_called_once_with(job_id=8, folder_id=9, version="current")

    def test_docx_service_reads_migrated_pipeline_data(self):
        job = {
            "id": 8,
            "tp_name": "TP Test",
            "rncp_code": "12345",
            "total_hours": 7,
            "nb_days": 1,
            "platform_id": 12,
            "daily_programs": json.dumps([{
                "day_number": 1,
                "title": "Accueil",
                "sub_parts": [{"name": "Intro", "module_content": "Plan module"}],
            }]),
        }
        folder_row = {
            "id": 9,
            "platform_id": 12,
            "formation_job_id": 8,
            "position": 0,
            "sub_parts": json.dumps(["Intro"]),
        }
        segment_rows = [{
            "id": 1,
            "sub_part_index": 0,
            "sub_part_name": "Intro",
            "passe": 1,
            "text_content": "Texte final [pause]",
            "text_content_pre_review": "Texte avant review",
            "word_count": 3,
        }]

        with patch(
            "services.formation_docx_service.get_formation_pipeline_job",
            return_value=job,
        ), patch(
            "services.formation_docx_service.get_content_generation_job_by_folder",
            return_value=folder_row,
        ), patch(
            "services.formation_docx_service.list_completed_content_segment_rows",
            return_value=segment_rows,
        ), patch(
            "database.db.get_db_connection",
            side_effect=AssertionError("legacy sqlite lookup should not be used"),
        ):
            docx_bytes, filename = build_course_docx(8, 9, version="pre_review")

        self.assertGreater(len(docx_bytes), 1000)
        self.assertEqual(filename, "programme-tp-test-jour1-pre-review.docx")


if __name__ == "__main__":
    unittest.main()
