import unittest
from unittest.mock import patch

from flask import Flask

from routes.hr_routes import create_hr_blueprint


class HrPostgresReadRoutesTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(create_hr_blueprint(None))
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["is_admin"] = True
            sess["admin_account_type"] = "training_center"
            sess["admin_account_id"] = 42

    def test_formation_modules_reads_postgres_without_sqlite(self):
        repository_rows = [{
            "id": 8,
            "rncp_code": "RNCP37099",
            "tp_name": "Employé commercial",
            "version": "v2",
            "status": "validated",
            "source_pipeline_job_id": 71,
            "source_platform_id": 12,
            "created_at": "2026-07-10 08:00:00",
            "nb_folders": 4,
            "source_platform_name": "Promo juillet",
            "voice_type": "azure",
            "voice_updated_at": "2026-07-10 09:00:00",
            "schedule": {
                "total_training_days": 4,
                "weekly_course_count": 2,
                "weekdays": [1, 3],
                "start_time": "09:00",
            },
        }]

        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.PIPELINE_DATABASE_BACKEND",
            "postgres",
        ), patch(
            "routes.hr_routes.list_hr_formation_modules",
            return_value=repository_rows,
        ) as list_modules, patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("SQLite must not be opened in PostgreSQL mode"),
        ):
            response = self.client.get("/api/hr/formation-modules")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["modules"][0]["reusable"])
        self.assertEqual(payload["modules"][0]["schedule"]["weekdays"], [1, 3])
        list_modules.assert_called_once_with(42, scope_to_center=True)

    def test_formations_reads_postgres_without_sqlite(self):
        repository_rows = [{
            "id": 71,
            "tp_name": "Employé commercial",
            "rncp_code": "RNCP37099",
            "total_hours": 28,
            "nb_days": 4,
            "status": "completed",
            "platform_id": 12,
            "platform_name": "Promo juillet",
            "nb_folders": 4,
            "created_at": "2026-07-10 08:00:00",
        }]

        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.PIPELINE_DATABASE_BACKEND",
            "supabase",
        ), patch(
            "routes.hr_routes.list_hr_formations",
            return_value=repository_rows,
        ) as list_formations, patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("SQLite must not be opened in PostgreSQL mode"),
        ):
            response = self.client.get("/api/hr/formations")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["formations"][0]["platform_name"], "Promo juillet")
        self.assertTrue(payload["formations"][0]["reusable"])
        list_formations.assert_called_once_with(42, scope_to_center=True)

    def test_platforms_reads_postgres_and_never_runs_lazy_repair(self):
        repository_rows = [{
            "id": 12,
            "name": "Promo juillet",
            "slug": "promo-juillet",
            "upload_locked": False,
            "pdf_filename": None,
            "pdf_uploaded_at": None,
            "updated_at": "2026-07-01T08:00:00+00:00",
            "status": "pending",
            "source_formation_id": None,
            "source_module_id": None,
            "center_account_id": 42,
            "center_slug": "centre-test",
            "source_rncp_code": None,
            "source_tp_name": None,
            "pipeline_status": None,
            "pipeline_auto_pilot_step": None,
            "pipeline_auto_pilot_error": None,
            "pipeline_auto_pilot_enabled": False,
            "pending_deletion_count": 2,
        }]

        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.PIPELINE_DATABASE_BACKEND",
            "postgresql",
        ), patch(
            "routes.hr_routes.list_hr_platforms",
            return_value=repository_rows,
        ) as list_platforms, patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("SQLite/lazy repair must not run in PostgreSQL mode"),
        ):
            response = self.client.get("/api/hr/platforms?include_blob_stats=0&repair=1")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        platform = payload["platforms"][0]
        self.assertEqual(platform["status"], "pending")
        self.assertIn("2 demande(s) de suppression", platform["alerts"])
        self.assertFalse(platform["blob_stats_loaded"])
        list_platforms.assert_called_once_with(42, scope_to_center=True)


if __name__ == "__main__":
    unittest.main()
