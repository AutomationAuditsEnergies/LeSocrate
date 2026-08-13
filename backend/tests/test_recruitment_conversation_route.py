import sys
import types
import unittest
from unittest.mock import patch

from flask import Flask

_export_service = types.ModuleType("services.export_service")
_export_service.generate_attendance_excel_export = lambda *_args, **_kwargs: None
_export_service.generate_excel_export = lambda *_args, **_kwargs: None
sys.modules.setdefault("services.export_service", _export_service)

from routes.hr_routes import create_hr_blueprint


class RecruitmentConversationRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(create_hr_blueprint())
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["is_admin"] = True
            session["admin_account_type"] = "training_center"
            session["admin_account_id"] = 42

    def test_interpretation_is_scoped_to_authenticated_centres(self):
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.interpret_recruitment_answer",
            return_value={"answered": True, "value": "Pierre", "reply": ""},
        ) as interpret:
            response = self.client.post(
                "/api/hr/recruitment/interpret",
                json={"field": "teacherName", "message": "Appelez-le Pierre"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["value"], "Pierre")
        interpret.assert_called_once()

    def test_interpretation_rejects_oversized_messages(self):
        with patch("routes.hr_routes.HR_ENABLED", True):
            response = self.client.post(
                "/api/hr/recruitment/interpret",
                json={"field": "teacherName", "message": "x" * 2001},
            )

        self.assertEqual(response.status_code, 400)

    def test_rncp_lookup_returns_the_official_available_title(self):
        certification = {
            "rncp_code": "37099",
            "title": "TP - Employé commercial",
            "active": True,
            "reac_available": True,
            "source_url": "https://www.francecompetences.fr/recherche/rncp/37099/",
        }
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "services.formation_pipeline_service.get_rncp_certification",
            return_value=certification,
        ):
            response = self.client.get("/api/hr/recruitment/rncp/37099")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["available"])
        self.assertEqual(
            response.get_json()["certification"]["title"],
            "TP - Employé commercial",
        )

    def test_inactive_rncp_remains_available_when_its_reac_exists(self):
        certification = {
            "rncp_code": "12345",
            "title": "Ancien titre",
            "active": False,
            "reac_available": True,
            "replacement_certifications": [{
                "rncp_code": "67890",
                "title": "Nouveau titre",
            }],
        }
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "services.formation_pipeline_service.get_rncp_certification",
            return_value=certification,
        ):
            response = self.client.get("/api/hr/recruitment/rncp/12345")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["available"])
        self.assertEqual(response.get_json()["reply"], "")

    def test_missing_reac_uses_the_product_unavailability_message(self):
        certification = {
            "rncp_code": "12345",
            "title": "Titre sans REAC",
            "active": True,
            "reac_available": False,
        }
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "services.formation_pipeline_service.get_rncp_certification",
            return_value=certification,
        ):
            response = self.client.get("/api/hr/recruitment/rncp/12345")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["available"])
        self.assertEqual(
            response.get_json()["reply"],
            "Désolé, nous n’avons pas encore de professeur disponible pour dispenser cette formation.",
        )


if __name__ == "__main__":
    unittest.main()
