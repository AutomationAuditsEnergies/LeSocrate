import sys
import types
import unittest

from flask import Flask

# Keep this focused route test independent from the optional Excel dependency.
_export_service = types.ModuleType("services.export_service")
_export_service.generate_attendance_excel_export = lambda *_args, **_kwargs: None
sys.modules.setdefault("services.export_service", _export_service)

from routes.hr_routes import create_hr_blueprint


class HrPlaylistQueueRouteTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test"
        self.app.register_blueprint(create_hr_blueprint())

    def test_manual_audio_and_content_generation_actions_are_absent(self):
        retired_routes = (
            ("POST", "/api/hr/cours-documents/<int:document_id>/generate-audio"),
            ("POST", "/api/hr/cours-folders/<int:folder_id>/generate-all-audio"),
            ("POST", "/api/hr/cours-folders/<int:folder_id>/generate-playlist"),
            ("POST", "/api/hr/cours-folders/<int:folder_id>/generate-playlist-item"),
            ("GET", "/api/hr/cours-folders/<int:folder_id>/playlist-status"),
            ("POST", "/api/hr/cours-folders/<int:folder_id>/content-job"),
            ("POST", "/api/hr/cours-folders/<int:folder_id>/content-job/start"),
            ("POST", "/api/hr/cours-folders/<int:folder_id>/content-job/cancel"),
            ("POST", "/api/hr/cours-folders/<int:folder_id>/content-job/rules/review-text"),
            (
                "GET",
                "/api/hr/cours-folders/<int:folder_id>/content-job/rules/review-text/status/<task_id>",
            ),
            (
                "GET",
                "/api/hr/cours-folders/<int:folder_id>/content-job/rules/review-text/active",
            ),
        )
        registered = {
            (method, rule.rule)
            for rule in self.app.url_map.iter_rules()
            for method in rule.methods
        }

        for route in retired_routes:
            with self.subTest(route=route):
                self.assertNotIn(route, registered)


if __name__ == "__main__":
    unittest.main()
