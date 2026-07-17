import unittest
import sys
import types
from datetime import datetime
from unittest.mock import ANY, patch

from flask import Flask
from config import FRANCE_TZ

_export_service = types.ModuleType("services.export_service")
_export_service.generate_attendance_excel_export = lambda *_args, **_kwargs: None
_export_service.generate_excel_export = lambda *_args, **_kwargs: None
sys.modules.setdefault("services.export_service", _export_service)

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
            "teacher_name": "Camille",
            "teacher_color": "violet",
            "creation_request_id": "request_1234567890",
            "slug": "promo-juillet",
            "upload_locked": False,
            "pdf_filename": None,
            "pdf_uploaded_at": None,
            "updated_at": "2026-07-01T08:00:00+00:00",
            "status": "pending",
            "source_formation_id": None,
            "source_module_id": None,
            "center_account_id": 42,
            "center_platform_number": 1,
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
            "routes.hr_routes.schedule_store_is_postgres", return_value=True,
        ), patch(
            "routes.hr_routes.list_course_schedule_dashboard_states",
            return_value={12: {
                "platform_id": 12,
                "timezone": "Europe/Paris",
                "start_time": "09:00",
                "session_id": 91,
                "session_index": 1,
                "scheduled_at": FRANCE_TZ.localize(datetime(2026, 7, 20, 9, 0)),
                "audio_generation_status": "pending",
                "audio_generation_started_at": None,
                "audio_generation_completed_at": None,
                "audio_generation_attempts": 0,
                "audio_generation_next_retry_at": None,
            }},
        ), patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("SQLite/lazy repair must not run in PostgreSQL mode"),
        ):
            response = self.client.get("/api/hr/platforms?include_blob_stats=0&repair=1")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        platform = payload["platforms"][0]
        self.assertEqual(platform["status"], "pending")
        self.assertEqual(platform["teacher_name"], "Camille")
        self.assertEqual(platform["teacher_color"], "violet")
        self.assertEqual(platform["center_platform_number"], 1)
        self.assertEqual(platform["teacher_preparation"]["status"], "preparing")
        self.assertEqual(platform["course_schedule"]["next_session"]["audio_status"], "scheduled")
        self.assertIn("2 demande(s) de suppression", platform["alerts"])
        self.assertFalse(platform["blob_stats_loaded"])
        list_platforms.assert_called_once_with(42, scope_to_center=True)

    def test_course_time_reads_postgres_without_opening_sqlite_first(self):
        course_start = FRANCE_TZ.localize(datetime(2026, 7, 11, 9, 0))
        summary = {
            "total_training_days": 2,
            "weekly_course_count": 1,
            "weekdays": [4],
            "start_time": "09:00",
        }
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center", return_value=True
        ), patch(
            "routes.hr_routes._is_local_platform", return_value=True
        ), patch(
            "routes.hr_routes.schedule_store_is_postgres", return_value=True
        ), patch(
            "routes.hr_routes.get_course_schedule_details", return_value=summary
        ) as get_summary, patch(
            "services.time_service.get_heure_debut_cours", return_value=course_start
        ), patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("SQLite must not be opened"),
        ):
            response = self.client.get("/api/hr/platforms/12/course-time")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["schedule"], summary)
        get_summary.assert_called_once_with(None, 12)

    def test_course_schedule_update_uses_postgres_without_sqlite(self):
        updated = {"start_time": "10:00", "weekdays": [4], "total_sessions": 2}
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center", return_value=True
        ), patch(
            "routes.hr_routes._is_local_platform", return_value=True
        ), patch(
            "routes.hr_routes.schedule_store_is_postgres", return_value=True
        ), patch(
            "routes.hr_routes.update_course_schedule", return_value=updated
        ) as update, patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("SQLite must not be opened"),
        ):
            response = self.client.post(
                "/api/hr/platforms/12/config-cours",
                json={"heure_cours": "10:00", "weekdays": [4]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["schedule"], updated)
        update.assert_called_once_with(
            None,
            12,
            start_time="10:00",
            weekdays=[4],
            allow_imminent=False,
        )

    def test_training_center_cannot_force_an_imminent_course_schedule(self):
        updated = {"start_time": "09:00", "weekdays": [0], "total_sessions": 1}
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center", return_value=True
        ), patch(
            "routes.hr_routes._is_local_platform", return_value=True
        ), patch(
            "routes.hr_routes.schedule_store_is_postgres", return_value=True
        ), patch(
            "routes.hr_routes.update_course_schedule", return_value=updated
        ) as update, patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("SQLite must not be opened"),
        ):
            response = self.client.post(
                "/api/hr/platforms/12/config-cours",
                json={
                    "heure_cours": "09:00",
                    "weekdays": [0],
                    "force_schedule": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        update.assert_called_once_with(
            None,
            12,
            start_time="09:00",
            weekdays=[0],
            allow_imminent=False,
        )

    def test_training_center_can_retry_and_postpone_owned_course_session(self):
        preview = {"lesson_number": 2, "new_scheduled_at": "2026-07-20T09:00:00+02:00"}
        postponed = {**preview, "affected_session_count": 3, "idempotent": False}
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center", return_value=True
        ), patch(
            "routes.hr_routes.retry_scheduled_audio_generation",
            return_value=({"success": True, "status": 202}, 202),
        ) as retry, patch(
            "routes.hr_routes.preview_course_session_postponement",
            return_value=preview,
        ) as preview_call, patch(
            "routes.hr_routes.postpone_course_session",
            return_value=postponed,
        ) as postpone, patch(
            "routes.hr_routes.get_course_schedule_details_for_platform",
            return_value={"sessions": []},
        ):
            retry_response = self.client.post(
                "/api/hr/platforms/12/sessions/91/audio/retry"
            )
            preview_response = self.client.post(
                "/api/hr/platforms/12/sessions/92/postpone/preview",
                json={"mode": "next_occurrence"},
            )
            postpone_response = self.client.post(
                "/api/hr/platforms/12/sessions/92/postpone",
                json={"mode": "next_occurrence", "reason": "Indisponibilité"},
                headers={"Idempotency-Key": "report-92"},
            )

        self.assertEqual(retry_response.status_code, 202)
        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(postpone_response.status_code, 200)
        retry.assert_called_once_with(12, 91)
        preview_call.assert_called_once_with(12, 92, mode="next_occurrence", scheduled_at=None)
        postpone.assert_called_once_with(
            12,
            92,
            mode="next_occurrence",
            scheduled_at=None,
            reason="Indisponibilité",
            idempotency_key="report-92",
            actor_account_id=42,
        )

    def test_deleting_a_session_is_replaced_by_user_friendly_postponement(self):
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center", return_value=True
        ):
            response = self.client.delete("/api/hr/platforms/12/sessions/92")

        self.assertEqual(response.status_code, 410)
        self.assertIn("Reporter cette séance", response.get_json()["error"])

    def test_postponement_requires_an_idempotency_key(self):
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center", return_value=True
        ), patch("routes.hr_routes.postpone_course_session") as postpone:
            response = self.client.post(
                "/api/hr/platforms/12/sessions/92/postpone",
                json={"mode": "next_occurrence"},
            )

        self.assertEqual(response.status_code, 400)
        postpone.assert_not_called()

    def test_explicit_reminder_recipients_use_repository_without_sqlite(self):
        recipients = [{"id": 4, "email": "eleve@example.com", "created_at": "2026-07-10 10:00:00"}]
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center", return_value=True
        ), patch(
            "routes.hr_routes.list_explicit_course_reminder_recipients",
            return_value=recipients,
        ) as list_recipients, patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("SQLite must not be opened"),
        ):
            response = self.client.get("/api/hr/platforms/12/student-emails")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["recipients"], recipients)
        list_recipients.assert_called_once_with(12)

    def test_student_email_batch_is_limited_to_one_thousand(self):
        emails = [f"eleve{index}@example.test" for index in range(1001)]
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center", return_value=True
        ), patch(
            "routes.hr_routes.add_explicit_course_reminder_recipients"
        ) as add_recipients:
            response = self.client.post(
                "/api/hr/platforms/12/student-emails",
                json={"emails": emails},
            )

        self.assertEqual(response.status_code, 413)
        self.assertIn("1000 emails maximum", response.get_json()["error"])
        add_recipients.assert_not_called()

    def test_student_email_valid_batch_is_normalized_and_tenant_scoped(self):
        saved = [
            {"id": 4, "email": "alice@example.test"},
            {"id": 5, "email": "bob@example.test"},
        ]
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center", return_value=True
        ), patch(
            "routes.hr_routes.add_explicit_course_reminder_recipients",
            return_value=saved,
        ) as add_recipients:
            response = self.client.post(
                "/api/hr/platforms/12/student-emails",
                json={"emails": [" Alice@Example.Test ", "bob@example.test"]},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["recipients"], saved)
        add_recipients.assert_called_once_with(
            12,
            ["alice@example.test", "bob@example.test"],
            created_at=ANY,
        )

    def test_student_email_write_rejects_another_centers_platform(self):
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center", return_value=False
        ), patch(
            "routes.hr_routes.add_explicit_course_reminder_recipients"
        ) as add_recipients:
            response = self.client.post(
                "/api/hr/platforms/99/student-emails",
                json={"emails": ["alice@example.test"]},
            )

        self.assertEqual(response.status_code, 404)
        add_recipients.assert_not_called()

    def test_student_email_rejects_oversized_or_malformed_address(self):
        invalid_email = f"{'a' * 245}@example.test"
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center", return_value=True
        ), patch(
            "routes.hr_routes.add_explicit_course_reminder_recipients"
        ) as add_recipients:
            response = self.client.post(
                "/api/hr/platforms/12/student-emails",
                json={"emails": [invalid_email]},
            )

        self.assertEqual(response.status_code, 400)
        add_recipients.assert_not_called()

    def test_reminder_rule_route_rejects_subject_header_injection(self):
        payload = {
            "name": "Rappel",
            "trigger_mode": "relative_minutes",
            "minutes_before": 30,
            "subject_template": "Cours\r\nBcc: pirate@example.test",
            "content_template": "Cours à {time}",
            "recipient_scope": "all",
        }
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center", return_value=True
        ):
            response = self.client.post(
                "/api/hr/platforms/12/reminder-rules",
                json=payload,
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("saut de ligne", response.get_json()["error"])

    def test_reminder_rules_can_be_listed_and_created_by_the_center(self):
        existing = [{
            "id": 7,
            "name": "Deux jours avant",
            "trigger_mode": "local_day_time",
            "days_before": 2,
            "local_time": "18:30",
            "recipient_scope": "all",
            "recipient_ids": [],
            "is_active": True,
        }]
        created = {**existing[0], "id": 8}
        request_payload = {
            "name": "Deux jours avant",
            "trigger_mode": "local_day_time",
            "days_before": 2,
            "local_time": "18:30",
            "subject_template": "Rappel",
            "content_template": "Cours le {date} à {time}",
            "recipient_scope": "all",
            "recipient_ids": [],
            "is_active": True,
        }
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center", return_value=True
        ), patch(
            "routes.hr_routes.get_course_reminder_rules", return_value=existing
        ) as list_rules, patch(
            "routes.hr_routes.save_course_reminder_rule", return_value=created
        ) as save_rule:
            response = self.client.get("/api/hr/platforms/12/reminder-rules")
            create_response = self.client.post(
                "/api/hr/platforms/12/reminder-rules",
                json=request_payload,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["rules"], existing)
        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.get_json()["rule"], created)
        list_rules.assert_called_once_with(12)
        save_rule.assert_called_once_with(12, request_payload)


if __name__ == "__main__":
    unittest.main()
