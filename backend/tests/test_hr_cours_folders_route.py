import sqlite3
import unittest
from unittest.mock import patch

from flask import Flask

from routes.hr_routes import create_hr_blueprint


class HrCoursFoldersRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(create_hr_blueprint())
        self.client = app.test_client()

    def test_cours_folders_route_uses_migrated_pipeline_repository(self):
        with self.client.session_transaction() as sess:
            sess["is_admin"] = True
            sess["admin_account_type"] = "legacy_admin"

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

    def test_next_course_selection_exposes_the_occurrence_and_current_override(self):
        with self.client.session_transaction() as sess:
            sess["is_admin"] = True
            sess["admin_account_type"] = "legacy_admin"

        course_session = {
            "id": 41,
            "platform_id": 12,
            "session_index": 2,
            "scheduled_at": "2026-09-01T09:00:00+02:00",
            "status": "planned",
            "audio_folder_id": 93,
        }
        folder_result = {
            "folders": [
                {"id": 91, "name": "Fondations", "position": 0},
                {"id": 92, "name": "Mise en pratique", "position": 1},
                {"id": 93, "name": "Perfectionnement", "position": 2},
            ],
            "platform_id": 12,
            "source_platform_id": None,
        }

        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.get_next_course_session",
            return_value=course_session,
        ), patch(
            "routes.hr_routes.list_course_folder_rows_for_platform",
            return_value=folder_result,
        ):
            resp = self.client.get(
                "/api/hr/platforms/12/next-course-selection"
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["session"]["id"], 41)
        self.assertEqual(data["session"]["scheduled_at"], "2026-09-01T09:00:00+02:00")
        self.assertEqual(data["scheduled_course"]["id"], 92)
        self.assertEqual(data["selected_course"]["id"], 93)
        self.assertEqual(data["selected_course"]["label"], "Jour 3")
        self.assertTrue(data["is_manual_override"])

    def _make_platforms_connection(self):
        class KeepOpenConnection(sqlite3.Connection):
            def close(self):
                pass

            def really_close(self):
                super().close()

        conn = sqlite3.connect(":memory:", factory=KeepOpenConnection)
        cursor = conn.cursor()
        cursor.executescript(
            """
            CREATE TABLE platform_config (
                id INTEGER PRIMARY KEY,
                name TEXT,
                teacher_name TEXT,
                teacher_color TEXT,
                creation_request_id INTEGER,
                slug TEXT,
                upload_locked INTEGER,
                pdf_filename TEXT,
                pdf_uploaded_at TEXT,
                updated_at TEXT,
                status TEXT,
                source_formation_id INTEGER,
                source_module_id INTEGER,
                center_account_id INTEGER
            );
            CREATE TABLE training_center_accounts (
                id INTEGER PRIMARY KEY,
                slug TEXT
            );
            CREATE TABLE formation_modules (
                id INTEGER PRIMARY KEY,
                rncp_code TEXT,
                tp_name TEXT
            );
            CREATE TABLE formation_pipeline_jobs (
                id INTEGER PRIMARY KEY,
                platform_id INTEGER,
                rncp_code TEXT,
                tp_name TEXT,
                status TEXT,
                auto_pilot_step TEXT,
                auto_pilot_error TEXT,
                auto_pilot_enabled INTEGER,
                auto_pilot_post_review_docs_done INTEGER DEFAULT 0
            );
            CREATE TABLE deletion_requests (
                platform_id INTEGER,
                status TEXT
            );
            CREATE TABLE cours_folders (
                id INTEGER PRIMARY KEY,
                formation_job_id INTEGER
            );
            CREATE TABLE content_generation_jobs (
                folder_id INTEGER,
                status TEXT
            );
            """
        )
        cursor.execute(
            """
            INSERT INTO platform_config (
                id, name, slug, upload_locked, pdf_filename, pdf_uploaded_at,
                updated_at, status, source_formation_id, source_module_id,
                center_account_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (12, "Teacher Test", "teacher-test", 0, None, None, "2026-07-05", "pending", None, None, None),
        )
        cursor.execute(
            """
            INSERT INTO formation_pipeline_jobs (
                id, platform_id, rncp_code, tp_name, status, auto_pilot_step,
                auto_pilot_error, auto_pilot_enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (77, 12, "37099", "TP EC", "completed", "done", None, 1),
        )
        conn.commit()
        return conn

    def test_platforms_listing_does_not_repair_by_default(self):
        with self.client.session_transaction() as sess:
            sess["is_admin"] = True
            sess["admin_account_type"] = "legacy_admin"

        conn = self._make_platforms_connection()
        try:
            with patch("routes.hr_routes.HR_ENABLED", True), patch(
                "routes.hr_routes.HR_DASHBOARD_REPAIR_ON_LOAD",
                False,
            ), patch("routes.hr_routes.get_db_connection", return_value=conn):
                resp = self.client.get("/api/hr/platforms?include_blob_stats=0")

            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(data["platforms"][0]["status"], "pending")

            cursor = conn.cursor()
            cursor.execute("SELECT status, source_formation_id FROM platform_config WHERE id = 12")
            self.assertEqual(cursor.fetchone(), ("pending", None))
        finally:
            conn.really_close()

    def test_platforms_listing_can_repair_when_requested(self):
        with self.client.session_transaction() as sess:
            sess["is_admin"] = True
            sess["admin_account_type"] = "legacy_admin"

        conn = self._make_platforms_connection()
        try:
            with patch("routes.hr_routes.HR_ENABLED", True), patch(
                "routes.hr_routes.HR_DASHBOARD_REPAIR_ON_LOAD",
                False,
            ), patch("routes.hr_routes.get_db_connection", return_value=conn):
                resp = self.client.get("/api/hr/platforms?include_blob_stats=0&repair=1")

            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(data["platforms"][0]["status"], "ready")
            self.assertEqual(data["platforms"][0]["source_formation_id"], 77)

            cursor = conn.cursor()
            cursor.execute("SELECT status, source_formation_id FROM platform_config WHERE id = 12")
            self.assertEqual(cursor.fetchone(), ("ready", 77))
        finally:
            conn.really_close()


if __name__ == "__main__":
    unittest.main()
