import sqlite3
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
                auto_pilot_enabled INTEGER
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
