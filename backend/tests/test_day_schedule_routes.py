import unittest
from unittest.mock import patch

from flask import Flask

from repositories.day_schedule_repository import TemplateImmutableError
from routes.hr_routes import create_hr_blueprint


def _valid_blocks():
    return [
        {"type": "course", "start_minute": 540, "duration_min": 60},
        {"type": "qa", "start_minute": 600, "duration_min": 10},
        {
            "type": "pause",
            "start_minute": 610,
            "duration_min": 15,
            "pause_kind": "short",
        },
        {"type": "course", "start_minute": 625, "duration_min": 60},
        {"type": "qa", "start_minute": 685, "duration_min": 10},
        {
            "type": "pause",
            "start_minute": 695,
            "duration_min": 90,
            "pause_kind": "lunch",
        },
        {"type": "course", "start_minute": 785, "duration_min": 60},
        {"type": "qa", "start_minute": 845, "duration_min": 10},
        {
            "type": "pause",
            "start_minute": 855,
            "duration_min": 15,
            "pause_kind": "short",
        },
        {"type": "course", "start_minute": 870, "duration_min": 60},
        {"type": "qa", "start_minute": 930, "duration_min": 10},
    ]


class DayScheduleTemplateRoutesTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="schedule-routes-test")
        app.register_blueprint(create_hr_blueprint())
        self.client = app.test_client()
        self._login_center()

    def _login_center(self, center_id=42):
        with self.client.session_transaction() as session:
            session["is_admin"] = True
            session["admin_account_type"] = "training_center"
            session["admin_account_id"] = center_id

    def test_center_lists_only_its_template_library(self):
        templates = [{"id": 8, "center_account_id": 42, "name": "Journée A"}]
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "repositories.day_schedule_repository.list_templates",
            return_value=templates,
        ) as list_templates:
            response = self.client.get("/api/hr/day-schedule-templates")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["templates"], templates)
        list_templates.assert_called_once_with(42)

    def test_create_compiles_blocks_before_tenant_scoped_persistence(self):
        created = {
            "id": 9,
            "center_account_id": 42,
            "name": "Journée complète",
            "schedule_schema_version": 2,
        }
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "repositories.day_schedule_repository.create_template",
            return_value=created,
        ) as create_template:
            response = self.client.post(
                "/api/hr/day-schedule-templates",
                json={"name": "Journée complète", "blocks": _valid_blocks()},
            )

        self.assertEqual(response.status_code, 201, response.get_json())
        args, kwargs = create_template.call_args
        self.assertEqual(args[0:2], (42, "Journée complète"))
        self.assertEqual(kwargs["schedule_schema_version"], 2)
        self.assertEqual(len(args[2]), 11)
        self.assertEqual(args[2][5]["pause_kind"], "lunch")
        self.assertEqual(args[2][-1]["block_type"], "qa")

    def test_invalid_day_returns_structured_domain_error(self):
        response = None
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "repositories.day_schedule_repository.create_template",
        ) as create_template:
            response = self.client.post(
                "/api/hr/day-schedule-templates",
                json={
                    "name": "Invalide",
                    "blocks": [
                        {"type": "course", "start_minute": 540, "duration_min": 60},
                        {
                            "type": "pause",
                            "start_minute": 600,
                            "duration_min": 10,
                            "is_lunch": False,
                        },
                    ],
                },
            )

        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertIn("validation", response.get_json())
        create_template.assert_not_called()

    def test_used_template_update_is_rejected_but_delete_remains_available(self):
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "repositories.day_schedule_repository.update_template",
            side_effect=TemplateImmutableError("Template déjà utilisé"),
        ):
            response = self.client.patch(
                "/api/hr/day-schedule-templates/9",
                json={"name": "Nouveau nom"},
            )

        self.assertEqual(response.status_code, 409, response.get_json())
        self.assertEqual(response.get_json()["code"], "template_immutable")

        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "repositories.day_schedule_repository.soft_delete_template",
            return_value=True,
        ) as soft_delete:
            response = self.client.delete("/api/hr/day-schedule-templates/9")

        self.assertEqual(response.status_code, 200, response.get_json())
        soft_delete.assert_called_once_with(42, 9)

    def test_non_center_admin_cannot_access_center_template_library(self):
        with self.client.session_transaction() as session:
            session["admin_account_type"] = "technical_admin"
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "repositories.day_schedule_repository.list_templates",
        ) as list_templates:
            response = self.client.get("/api/hr/day-schedule-templates")

        self.assertEqual(response.status_code, 404, response.get_json())
        list_templates.assert_not_called()


if __name__ == "__main__":
    unittest.main()
