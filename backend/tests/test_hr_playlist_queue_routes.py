import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

# Keep this focused route test independent from the optional Excel dependency.
_export_service = types.ModuleType("services.export_service")
_export_service.generate_attendance_excel_export = lambda *_args, **_kwargs: None
sys.modules.setdefault("services.export_service", _export_service)

from routes.hr_routes import create_hr_blueprint


class HrPlaylistQueueRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(create_hr_blueprint(None))
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["is_admin"] = True
            session["admin_account_type"] = "legacy_admin"

    @staticmethod
    def _content_module():
        module = types.ModuleType("services.content_generation_service")
        module.get_job_from_db = lambda _folder_id: {"status": "completed"}
        return module

    def test_generate_playlist_enqueues_folder_resource_without_eventlet(self):
        queued = SimpleNamespace(
            id="work-audio",
            run_id="requested-run",
            status="queued",
            terminal=False,
        )

        def enqueue(**kwargs):
            queued.run_id = kwargs["run_id"]
            return queued

        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.get_course_folder_identity",
            return_value={
                "id": 118,
                "platform_id": 16,
                "formation_job_id": None,
                "name": "Jour 1",
            },
        ), patch.dict(
            sys.modules,
            {"services.content_generation_service": self._content_module()},
        ), patch(
            "services.pipeline_queue.enqueue_work_item",
            side_effect=enqueue,
        ) as enqueue_mock:
            response = self.client.post(
                "/api/hr/cours-folders/118/generate-playlist",
                json={"voice_type": "gtts", "force_all": True},
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["work_item_id"], "work-audio")
        kwargs = enqueue_mock.call_args.kwargs
        self.assertIsNone(kwargs["pipeline_job_id"])
        self.assertEqual(kwargs["folder_id"], 118)
        self.assertEqual(kwargs["resource_key"], "folder:118")
        self.assertEqual(kwargs["scope_key"], "hr_audio:118")
        self.assertEqual(kwargs["task_type"], "hr_playlist_generate")

    def test_generate_playlist_returns_conflict_for_atomic_queue_duplicate(self):
        existing = SimpleNamespace(
            id="existing-work",
            run_id="another-run",
            status="running",
            terminal=False,
        )
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.get_course_folder_identity",
            return_value={
                "id": 118,
                "platform_id": 16,
                "formation_job_id": 13,
                "name": "Jour 1",
            },
        ), patch.dict(
            sys.modules,
            {"services.content_generation_service": self._content_module()},
        ), patch(
            "services.pipeline_queue.enqueue_work_item",
            return_value=existing,
        ):
            response = self.client.post(
                "/api/hr/cours-folders/118/generate-playlist",
                json={"voice_type": "gtts"},
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["work_item_id"], "existing-work")

    def test_playlist_status_reads_persisted_progress(self):
        persisted = SimpleNamespace(
            id="work-running",
            run_id="run-118",
            status="running",
            attempt_count=2,
            max_attempts=5,
            last_error=None,
            result={
                "status": "running",
                "step": 9,
                "total_steps": 24,
                "message": "Génération cours 3",
            },
        )
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "services.pipeline_queue.get_latest_folder_work_item",
            return_value=persisted,
        ) as latest:
            response = self.client.get(
                "/api/hr/cours-folders/118/playlist-status"
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "running")
        self.assertEqual(data["queue_status"], "running")
        self.assertEqual(data["step"], 9)
        self.assertEqual(data["attempt"], 2)
        latest.assert_called_once_with(118, scope_key="hr_audio:118")


if __name__ == "__main__":
    unittest.main()
