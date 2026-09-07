import io
import sqlite3
import unittest
from unittest.mock import patch

from flask import Flask

from repositories import pipeline_repository
from repositories.hr_write_repository import CloneSourceInvalid
from routes.hr_routes import create_hr_blueprint


class HrTenantIsolationRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "hr-tenant-isolation"
        app.register_blueprint(create_hr_blueprint())
        self.client = app.test_client()

    def _login(self, *, account_type="training_center", account_id=10):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["is_admin"] = True
            sess["admin_account_type"] = account_type
            if account_id is not None:
                sess["admin_account_id"] = account_id

    def _assert_hidden_without_route_db(self, method, path, *, resource_type, resource_id, **kwargs):
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center",
            return_value=False,
        ) as belongs, patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("route DB side effect must not run"),
        ):
            response = getattr(self.client, method)(path, **kwargs)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json(),
            {"success": False, "error": "Ressource introuvable"},
        )
        belongs.assert_called_once_with(resource_type, resource_id, 10)

    def test_platform_mutations_are_blocked_before_db_remote_or_blob_side_effects(self):
        self._login()
        cases = (
            ("post", "/api/hr/platforms/2/toggle-lock", {}, "platform", 2),
            ("delete", "/api/hr/platforms/2", {}, "platform", 2),
            (
                "post",
                "/api/hr/platforms/2/upload-pdf",
                {"data": {"file": (io.BytesIO(b"%PDF"), "course.pdf")}},
                "platform",
                2,
            ),
            ("delete", "/api/hr/platforms/2/pdf", {}, "platform", 2),
            ("post", "/api/hr/platforms/2/backup-and-unlock", {}, "platform", 2),
            (
                "post",
                "/api/hr/platforms/2/student-emails",
                {"json": {"email": "student@example.test"}},
                "platform",
                2,
            ),
            (
                "post",
                "/api/hr/platforms/2/sessions/91/audio/retry",
                {},
                "platform",
                2,
            ),
            (
                "get",
                "/api/hr/platforms/2/course-materials",
                {},
                "platform",
                2,
            ),
            (
                "delete",
                "/api/hr/platforms/2/sessions/91",
                {},
                "platform",
                2,
            ),
            (
                "post",
                "/api/hr/platforms/2/sessions/91/postpone/preview",
                {"json": {"mode": "next_occurrence"}},
                "platform",
                2,
            ),
            (
                "post",
                "/api/hr/platforms/2/sessions/91/postpone",
                {"json": {"mode": "next_occurrence"}},
                "platform",
                2,
            ),
        )
        for method, path, kwargs, resource_type, resource_id in cases:
            with self.subTest(path=path):
                self._assert_hidden_without_route_db(
                    method,
                    path,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    **kwargs,
                )

    def test_course_materials_backfills_completed_legacy_pipeline(self):
        self._login(account_type="superadmin", account_id=None)
        sessions = [{"id": 501, "session_index": 1}]
        ready_material = {"session_id": 501, "session_index": 1}
        with (
            patch("routes.hr_routes.HR_ENABLED", True),
            patch("routes.hr_routes.list_course_sessions", return_value=sessions),
            patch(
                "services.daily_course_pdf_service.list_daily_course_pdf_materials",
                side_effect=[[], [ready_material]],
            ) as list_materials,
            patch(
                "repositories.pipeline_repository.find_latest_pipeline_job_id_for_platform",
                return_value=8,
            ),
            patch(
                "services.formation_pipeline_service.get_job",
                return_value={"id": 8, "status": "text_ready"},
            ),
            patch(
                "services.daily_course_pdf_service.publish_pipeline_course_pdfs",
                return_value=[ready_material],
            ) as publish_materials,
        ):
            response = self.client.get("/api/hr/platforms/5/course-materials")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["materials"], [ready_material])
        publish_materials.assert_called_once_with(job_id=8, platform_id=5)
        self.assertEqual(list_materials.call_count, 2)

    def test_indirect_folder_document_request_and_segment_ids_are_hidden_first(self):
        self._login()
        cases = (
            ("delete", "/api/hr/cours-folders/22", {}, "folder", 22),
            ("patch", "/api/hr/cours-folders/22", {"json": {"name": "X"}}, "folder", 22),
            ("delete", "/api/hr/cours-documents/33", {}, "document", 33),
            ("post", "/api/hr/cours-documents/33/generate-audio", {}, "document", 33),
            (
                "patch",
                "/api/hr/cours-folders/22/content-job/segment",
                {"json": {"sub_part_index": 0, "passe": 1, "text": "secret"}},
                "folder",
                22,
            ),
        )
        for method, path, kwargs, resource_type, resource_id in cases:
            with self.subTest(path=path):
                self._assert_hidden_without_route_db(
                    method,
                    path,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    **kwargs,
                )

    def test_legacy_recorder_deletion_routes_are_removed(self):
        self._login()
        cases = (
            ("post", "/api/hr/deletion-requests", {"json": {}}),
            ("get", "/api/hr/deletion-requests?status=all", {}),
            ("post", "/api/hr/deletion-requests/44/approve", {}),
            ("post", "/api/hr/deletion-requests/44/reject", {}),
        )

        for method, path, kwargs in cases:
            with self.subTest(path=path):
                response = getattr(self.client, method)(path, **kwargs)
                self.assertEqual(response.status_code, 404)

    def test_body_folder_is_authorized_before_fill_from_folder_side_effects(self):
        self._login()
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center",
            side_effect=[True, False],
        ) as belongs, patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("route DB side effect must not run"),
        ):
            response = self.client.post(
                "/api/hr/platforms/1/fill-from-folder",
                json={"folder_id": 22},
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            belongs.call_args_list,
            [
                unittest.mock.call("platform", 1, 10),
                unittest.mock.call("folder", 22, 10),
            ],
        )

    def test_schedule_selection_is_fully_authorized_before_reset(self):
        self._login()
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center",
            side_effect=[True, False],
        ) as belongs, patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("schedule reset must not run"),
        ):
            response = self.client.post(
                "/api/hr/schedule-config",
                json={"mode": "ete", "platform_ids": [1, 2]},
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            belongs.call_args_list,
            [
                unittest.mock.call("platform", 1, 10),
                unittest.mock.call("platform", 2, 10),
            ],
        )

    def test_platform_creation_authorizes_body_module_and_formation_sources_first(self):
        self._login()
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center",
            return_value=False,
        ) as module_belongs, patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("platform creation transaction must not start"),
        ):
            module_response = self.client.post(
                "/api/hr/platforms",
                json={"name": "Promo volée", "module_id": 22222},
            )

        self.assertEqual(module_response.status_code, 404)
        module_belongs.assert_called_once_with("module", 22222, 10)

        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.pipeline_job_belongs_to_center",
            return_value=False,
        ) as job_belongs, patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("platform creation transaction must not start"),
        ):
            formation_response = self.client.post(
                "/api/hr/platforms",
                json={"name": "Promo volée", "formation_id": 777},
            )

        self.assertEqual(formation_response.status_code, 404)
        job_belongs.assert_called_once_with(777, 10)

    def test_platform_creation_request_is_idempotent_inside_current_center(self):
        self._login()
        existing = {
            "id": 41,
            "name": "Camille · Employé commercial",
            "slug": "camille-employe-commercial",
            "status": "pending",
            "source_formation_id": 71,
            "source_module_id": None,
            "teacher_name": "Camille",
            "teacher_color": "violet",
            "creation_request_id": "request_1234567890",
        }
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.postgres_enabled", return_value=True,
        ), patch(
            "routes.hr_routes.get_platform_by_creation_request_id",
            return_value=existing,
        ) as find_existing, patch(
            "routes.hr_routes.get_training_center_by_id",
            return_value={"slug": "centre-a"},
        ), patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("a duplicate request must not create a second platform"),
        ):
            response = self.client.post(
                "/api/hr/platforms",
                json={
                    "name": "Camille · Employé commercial",
                    "teacher_name": "Camille",
                    "teacher_color": "violet",
                    "creation_request_id": "request_1234567890",
                    "new_formation": {
                        "tp_name": "Employé commercial",
                        "rncp_code": "RNCP37099",
                        "total_hours": 14,
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["deduplicated"])
        self.assertEqual(payload["platform"]["id"], 41)
        self.assertEqual(payload["platform"]["pipeline_job_id"], 71)
        find_existing.assert_called_once_with("request_1234567890", 10)

    def test_postgres_clone_source_is_resolved_before_sqlite_mirror_transaction(self):
        self._login()
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes._hr_pipeline_reads_use_postgres",
            return_value=True,
        ), patch(
            "routes.hr_routes.hr_resource_belongs_to_center",
            return_value=True,
        ), patch(
            "routes.hr_routes.resolve_postgres_module_clone_source",
            side_effect=CloneSourceInvalid("module PostgreSQL non validé"),
        ) as resolve_source, patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("SQLite mirror transaction must not start"),
        ):
            response = self.client.post(
                "/api/hr/platforms",
                json={"name": "Promo PG", "module_id": 42},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "module PostgreSQL non validé")
        resolve_source.assert_called_once_with(42, 10, scope_to_center=True)

    def test_training_center_without_valid_account_id_fails_closed(self):
        for account_id in (None, 0, -1, True, "invalid"):
            with self.subTest(account_id=account_id):
                self._login(account_id=account_id)
                with patch("routes.hr_routes.HR_ENABLED", True), patch(
                    "routes.hr_routes.hr_resource_belongs_to_center",
                ) as belongs:
                    response = self.client.get("/api/hr/platforms/1/backup-status")
                self.assertEqual(response.status_code, 404)
                belongs.assert_not_called()

    def test_admin_session_without_explicit_account_type_fails_closed(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["is_admin"] = True
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "routes.hr_routes.hr_resource_belongs_to_center",
        ) as belongs, patch(
            "routes.hr_routes.get_db_connection",
            side_effect=AssertionError("route DB side effect must not run"),
        ):
            response = self.client.post("/api/hr/platforms/1/toggle-lock")
        self.assertEqual(response.status_code, 404)
        belongs.assert_not_called()

    def test_legacy_and_superadmin_sessions_explicitly_bypass_tenant_lookup(self):
        for account_type in ("legacy_admin", "superadmin"):
            with self.subTest(account_type=account_type):
                self._login(account_type=account_type, account_id=None)
                with patch("routes.hr_routes.HR_ENABLED", True), patch(
                    "routes.hr_routes.hr_resource_belongs_to_center",
                ) as belongs:
                    response = self.client.get("/api/hr/platforms/999/backup-status")
                self.assertEqual(response.status_code, 200)
                belongs.assert_not_called()

    def test_retired_backup_unlock_route_has_no_storage_side_effect(self):
        self._login(account_type="superadmin", account_id=None)
        with patch("routes.hr_routes.HR_ENABLED", True):
            response = self.client.post("/api/hr/platforms/1/backup-and-unlock")

        self.assertEqual(response.status_code, 410)
        self.assertFalse(response.get_json()["success"])

    def test_shared_tts_prompt_is_superadmin_only(self):
        self._login()
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "builtins.open",
        ) as open_file:
            response = self.client.post(
                "/api/hr/tts-prompt",
                json={"content": "do not write"},
            )
        self.assertEqual(response.status_code, 403)
        open_file.assert_not_called()

    def test_schedule_reset_stays_inside_current_center(self):
        class _KeepOpenConnection(sqlite3.Connection):
            def close(self):
                pass

            def really_close(self):
                super().close()

        conn = sqlite3.connect(":memory:", factory=_KeepOpenConnection)
        conn.executescript(
            """
            CREATE TABLE platform_config (
                id INTEGER PRIMARY KEY,
                name TEXT,
                center_account_id INTEGER,
                playlist_mode TEXT
            );
            INSERT INTO platform_config VALUES
                (1, 'Centre A', 10, 'hiver'),
                (2, 'Centre B', 20, 'hiver');
            """
        )
        self._login()
        try:
            with patch("routes.hr_routes.HR_ENABLED", True), patch(
                "routes.hr_routes.get_db_connection",
                return_value=conn,
            ), patch(
                "routes.hr_routes.hr_resource_belongs_to_center",
                return_value=True,
            ):
                schedule_response = self.client.post(
                    "/api/hr/schedule-config",
                    json={"mode": "ete", "platform_ids": [1]},
                )

            self.assertEqual(schedule_response.status_code, 200)
            rows = conn.execute(
                "SELECT id, playlist_mode FROM platform_config ORDER BY id"
            ).fetchall()
            self.assertEqual(rows, [(1, "ete"), (2, "hiver")])
        finally:
            conn.really_close()


class HrResourceOwnershipRepositoryTest(unittest.TestCase):
    def setUp(self):
        class _KeepOpenConnection(sqlite3.Connection):
            def close(self):
                pass

            def really_close(self):
                super().close()

        self.conn = sqlite3.connect(":memory:", factory=_KeepOpenConnection)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE platform_config (
                id INTEGER PRIMARY KEY,
                center_account_id INTEGER
            );
            CREATE TABLE cours_folders (
                id INTEGER PRIMARY KEY,
                platform_id INTEGER
            );
            CREATE TABLE cours_documents (
                id INTEGER PRIMARY KEY,
                folder_id INTEGER
            );
            CREATE TABLE deletion_requests (
                id INTEGER PRIMARY KEY,
                platform_id INTEGER
            );
            CREATE TABLE formation_modules (
                id INTEGER PRIMARY KEY,
                center_account_id INTEGER,
                source_platform_id INTEGER
            );

            INSERT INTO platform_config VALUES (1, 10), (2, 20), (3, NULL);
            INSERT INTO cours_folders VALUES (11, 1), (22, 2), (33, 3);
            INSERT INTO cours_documents VALUES (111, 11), (222, 22);
            INSERT INTO deletion_requests VALUES (1111, 1), (2222, 2);
            INSERT INTO formation_modules VALUES
                (11111, 10, 1),
                (22222, 20, 2),
                (33333, NULL, NULL),
                (44444, 10, 2);
            """
        )

    def tearDown(self):
        self.conn.really_close()

    def test_every_indirect_resource_resolves_through_its_tenant(self):
        owned = (
            ("platform", 1),
            ("folder", 11),
            ("document", 111),
            ("deletion_request", 1111),
            ("module", 11111),
        )
        with patch.object(pipeline_repository, "PIPELINE_DATABASE_BACKEND", "sqlite"), patch.object(
            pipeline_repository,
            "get_db_connection",
            return_value=self.conn,
        ):
            for resource_type, resource_id in owned:
                with self.subTest(resource_type=resource_type):
                    self.assertTrue(
                        pipeline_repository.hr_resource_belongs_to_center(
                            resource_type,
                            resource_id,
                            10,
                        )
                    )
                    self.assertFalse(
                        pipeline_repository.hr_resource_belongs_to_center(
                            resource_type,
                            resource_id,
                            20,
                        )
                    )

            self.assertFalse(
                pipeline_repository.hr_resource_belongs_to_center("folder", 33, 10)
            )
            self.assertFalse(
                pipeline_repository.hr_resource_belongs_to_center("module", 33333, 10)
            )
            self.assertFalse(
                pipeline_repository.hr_resource_belongs_to_center("module", 44444, 10)
            )
            self.assertFalse(
                pipeline_repository.hr_resource_belongs_to_center("unknown", 1, 10)
            )


if __name__ == "__main__":
    unittest.main()
