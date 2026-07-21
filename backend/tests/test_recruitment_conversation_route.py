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
        app.register_blueprint(create_hr_blueprint(None))
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


if __name__ == "__main__":
    unittest.main()
