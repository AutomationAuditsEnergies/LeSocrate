import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from repositories import pipeline_repository as repo
from routes.formation_routes import formation_bp


def _job(**overrides):
    value = {
        "id": 42,
        "platform_id": 7,
        "status": "init",
        "reac_text": None,
        "rc_text": None,
        "rome_text": None,
        "auto_pilot_step": None,
        "auto_pilot_model": "pro",
        "auto_pilot_tts_mode": "gtts",
        "auto_pilot_generate_audio": False,
        "auto_pilot_locked_at": None,
    }
    value.update(overrides)
    return value


class PipelineTenantScopeRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "tenant-scope-test"
        app.register_blueprint(formation_bp)
        self.client = app.test_client()
        self.permission_patch = patch(
            "routes.formation_routes.can_access_formation_pipeline",
            return_value=True,
        )
        self.permission_patch.start()

    def tearDown(self):
        self.permission_patch.stop()

    def _login(self, account_type="training_center", account_id=10):
        with self.client.session_transaction() as session:
            session.clear()
            session["is_admin"] = True
            session["admin_account_type"] = account_type
            if account_id is not None:
                session["admin_account_id"] = account_id

    def test_center_a_can_read_but_manual_mutations_are_retired(self):
        self._login(account_id=10)
        with patch(
            "repositories.pipeline_repository.pipeline_job_belongs_to_center",
            return_value=True,
        ) as belongs, patch(
            "routes.formation_routes.get_job",
            return_value=_job(status="global_ready"),
        ) as get_job, patch(
            "routes.formation_routes.update_job",
        ) as update_job:
            read_response = self.client.get("/api/formation/42")
            mutation_response = self.client.post(
                "/api/formation/42/validate-global",
                json={"program_text": "Programme Centre A"},
            )

        self.assertEqual(read_response.status_code, 200)
        self.assertEqual(mutation_response.status_code, 410)
        self.assertEqual(
            mutation_response.get_json()["code"],
            "durable_pipeline_only",
        )
        self.assertEqual(belongs.call_count, 2)
        belongs.assert_called_with(42, 10)
        get_job.assert_called_once_with(42)
        update_job.assert_not_called()

    def test_center_b_is_hidden_before_mutation_run_and_stop_side_effects(self):
        self._login(account_id=20)
        with patch(
            "repositories.pipeline_repository.pipeline_job_belongs_to_center",
            return_value=False,
        ) as belongs, patch(
            "routes.formation_routes.get_job",
        ) as get_job, patch(
            "routes.formation_routes.update_job",
        ) as update_job, patch(
            "routes.formation_routes._dispatch_auto_pilot_tick",
        ) as dispatch, patch(
            "services.formation_observability_service.log_pipeline_event",
        ) as observe:
            responses = [
                self.client.post("/api/formation/42/validate-global", json={}),
                self.client.post("/api/formation/42/run-auto", json={}),
                self.client.post("/api/formation/42/run-auto/stop", json={}),
            ]

        self.assertEqual([response.status_code for response in responses], [404, 404, 404])
        self.assertTrue(all(response.get_json() == {"error": "Job introuvable"} for response in responses))
        self.assertEqual(belongs.call_count, 3)
        get_job.assert_not_called()
        update_job.assert_not_called()
        dispatch.assert_not_called()
        observe.assert_not_called()

    def test_center_a_sees_manual_start_and_stop_retired(self):
        self._login(account_id=10)
        with patch(
            "repositories.pipeline_repository.pipeline_job_belongs_to_center",
            return_value=True,
        ), patch(
            "routes.formation_routes.get_job",
            return_value=_job(auto_pilot_step="content"),
        ), patch(
            "routes.formation_routes.update_job",
        ) as update_job, patch(
            "services.pipeline_queue.cancel_latest_work_item",
            return_value=None,
        ), patch(
            "services.formation_observability_service.log_pipeline_event",
        ):
            run_response = self.client.post(
                "/api/formation/42/run-auto",
                json={"model": "pro", "tts_mode": "mock"},
            )
            stop_response = self.client.post("/api/formation/42/run-auto/stop")

        self.assertEqual(run_response.status_code, 410)
        self.assertEqual(run_response.get_json()["code"], "teacher_order_required")
        self.assertEqual(stop_response.status_code, 410)
        self.assertEqual(stop_response.get_json()["code"], "durable_pipeline_only")
        update_job.assert_not_called()

    def test_training_center_without_account_id_is_fail_closed(self):
        self._login(account_id=None)
        with patch(
            "repositories.pipeline_repository.pipeline_job_belongs_to_center",
        ) as belongs, patch(
            "routes.formation_routes.get_job",
        ) as get_job:
            response = self.client.get("/api/formation/42")

        self.assertEqual(response.status_code, 403)
        belongs.assert_not_called()
        get_job.assert_not_called()

    def test_incomplete_center_session_cannot_create_a_global_platform(self):
        self._login(account_type="training_center", account_id=None)
        with patch(
            "repositories.pipeline_repository.create_pipeline_platform",
        ) as create_platform, patch(
            "repositories.pipeline_repository.create_postgres_pipeline_aggregate",
        ) as create_aggregate:
            response = self.client.post(
                "/api/formation/init",
                json={
                    "platform_name": "Ne doit pas exister",
                    "tp_name": "TP",
                    "rncp_code": "RNCP1",
                    "total_hours": 7,
                },
            )

        self.assertEqual(response.status_code, 403)
        create_platform.assert_not_called()
        create_aggregate.assert_not_called()

    def test_admin_session_without_explicit_account_type_is_fail_closed(self):
        with self.client.session_transaction() as session:
            session.clear()
            session["is_admin"] = True
        with patch(
            "repositories.pipeline_repository.pipeline_job_belongs_to_center",
        ) as belongs, patch("routes.formation_routes.get_job") as get_job:
            response = self.client.get("/api/formation/42")

        self.assertEqual(response.status_code, 403)
        belongs.assert_not_called()
        get_job.assert_not_called()

    def test_public_and_unknown_admin_type_are_forbidden_on_all_formation_routes(self):
        public_response = self.client.post("/api/formation/search-rncp", json={"query": "vente"})

        self._login(account_type="unexpected_role", account_id=10)
        unknown_response = self.client.post(
            "/api/formation/init",
            json={
                "platform_name": "Interdit",
                "tp_name": "TP",
                "rncp_code": "RNCP1",
                "total_hours": 7,
            },
        )

        self.assertEqual(public_response.status_code, 403)
        self.assertEqual(unknown_response.status_code, 403)

    def test_legacy_and_superadmin_types_cannot_access_pipeline(self):
        for account_type in ("legacy_admin", "superadmin"):
            with self.subTest(account_type=account_type):
                self._login(account_type=account_type, account_id=None)
                with patch(
                    "repositories.pipeline_repository.pipeline_job_belongs_to_center",
                ) as belongs, patch(
                    "routes.formation_routes.get_job",
                    return_value=_job(),
                ):
                    response = self.client.get("/api/formation/42")

                self.assertEqual(response.status_code, 403)
                belongs.assert_not_called()

    def test_folder_job_mismatch_is_hidden_before_text_blob_docx_or_reports(self):
        self._login(account_type="training_center", account_id=10)
        urls = (
            "/api/formation/42/content/99/text",
            "/api/formation/42/content/99/artifact/content-plan.json",
            "/api/formation/42/content/99/docx",
            "/api/formation/42/content/99/review-report",
            "/api/formation/42/content/99/humanization-report",
        )
        with patch(
            "repositories.pipeline_repository.pipeline_job_belongs_to_center",
            return_value=True,
        ), patch(
            "repositories.pipeline_repository.course_folder_belongs_to_job",
            return_value=False,
        ) as belongs, patch("routes.formation_routes.get_job") as get_job:
            responses = [self.client.get(url) for url in urls]

        self.assertEqual([response.status_code for response in responses], [404] * len(urls))
        self.assertTrue(all(response.get_json() == {"error": "Job introuvable"} for response in responses))
        self.assertEqual(belongs.call_count, len(urls))
        belongs.assert_called_with(99, 42)
        get_job.assert_not_called()

    def test_scope_lookup_error_is_hidden_and_fail_closed(self):
        self._login(account_id=10)
        with patch(
            "repositories.pipeline_repository.pipeline_job_belongs_to_center",
            side_effect=RuntimeError("database unavailable"),
        ), patch("routes.formation_routes.get_job") as get_job:
            response = self.client.get("/api/formation/42")

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("database unavailable", response.get_data(as_text=True))
        get_job.assert_not_called()

    def test_center_list_is_filtered_and_legacy_admin_is_forbidden(self):
        self._login(account_id=10)
        with patch(
            "repositories.pipeline_repository.list_pipeline_jobs",
            return_value=[{"id": 42}],
        ) as list_jobs:
            center_response = self.client.get("/api/formation/list")

        self.assertEqual(center_response.status_code, 200)
        self.assertEqual(center_response.get_json(), {"jobs": [{"id": 42}]})
        list_jobs.assert_called_once_with(center_account_id=10)

        self._login(account_type="legacy_admin", account_id=None)
        with patch(
            "repositories.pipeline_repository.list_pipeline_jobs",
            return_value=[{"id": 42}, {"id": 43}],
        ) as list_jobs:
            legacy_response = self.client.get("/api/formation/list")

        self.assertEqual(legacy_response.status_code, 403)
        list_jobs.assert_not_called()

    def test_center_without_pipeline_permission_is_forbidden_before_business_logic(self):
        self._login(account_id=10)
        with patch(
            "routes.formation_routes.can_access_formation_pipeline",
            return_value=False,
        ), patch(
            "repositories.pipeline_repository.pipeline_job_belongs_to_center",
        ) as belongs, patch(
            "routes.formation_routes.get_job",
        ) as get_job:
            response = self.client.get("/api/formation/42")

        self.assertEqual(response.status_code, 403)
        belongs.assert_not_called()
        get_job.assert_not_called()

    def test_center_list_without_account_id_is_fail_closed(self):
        self._login(account_id=None)
        with patch("repositories.pipeline_repository.list_pipeline_jobs") as list_jobs:
            response = self.client.get("/api/formation/list")

        self.assertEqual(response.status_code, 403)
        list_jobs.assert_not_called()

    def test_legacy_claude_code_mission_routes_are_removed(self):
        self._login(account_id=10)
        urls = (
            "/api/formation/42/missions/kb/export",
            "/api/formation/42/missions/kb/import",
            "/api/formation/42/missions/kb/execute",
            "/api/formation/42/missions/kb/logs",
            "/api/formation/42/missions/pending",
        )

        responses = [
            self.client.get(url) if url.endswith(("logs", "pending")) else self.client.post(url)
            for url in urls
        ]

        self.assertEqual([response.status_code for response in responses], [404] * len(urls))


class PipelineTenantScopeRepositoryTest(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.close()
        self.db_path = Path(handle.name)
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE platform_config (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                center_account_id INTEGER
            );
            CREATE TABLE formation_pipeline_jobs (
                id INTEGER PRIMARY KEY,
                platform_id INTEGER NOT NULL,
                tp_name TEXT NOT NULL,
                rncp_code TEXT,
                total_hours INTEGER NOT NULL,
                nb_days INTEGER NOT NULL,
                status TEXT,
                global_program_validated INTEGER DEFAULT 0,
                daily_programs_validated INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE cours_folders (
                id INTEGER PRIMARY KEY,
                platform_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                position INTEGER NOT NULL,
                formation_job_id INTEGER
            );

            INSERT INTO platform_config VALUES (1, 'Centre A', 10);
            INSERT INTO platform_config VALUES (2, 'Centre B', 20);
            INSERT INTO platform_config VALUES (3, 'Plateforme sans tenant', NULL);
            INSERT INTO formation_pipeline_jobs VALUES
                (41, 1, 'TP A', 'RNCP-A', 7, 1, 'init', 0, 0, '2026-01-03', '2026-01-03'),
                (42, 2, 'TP B', 'RNCP-B', 7, 1, 'init', 0, 0, '2026-01-02', '2026-01-02'),
                (43, 3, 'TP sans tenant', 'RNCP-X', 7, 1, 'init', 0, 0, '2026-01-01', '2026-01-01'),
                (44, 999, 'TP orphelin', 'RNCP-O', 7, 1, 'init', 0, 0, '2025-12-31', '2025-12-31');
            INSERT INTO cours_folders VALUES
                (101, 1, 'Jour A', 0, 41),
                (102, 2, 'Jour B', 0, 42),
                (103, 1, 'Orphelin', 1, NULL),
                (104, 2, 'Lien job incohérent', 2, 41);
            """
        )
        conn.commit()
        conn.close()
        self.patches = [
            patch.object(repo, "_pipeline_primary_backend", return_value="sqlite"),
            patch.object(repo, "get_db_connection", side_effect=self._connect),
        ]
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self):
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.db_path.unlink(missing_ok=True)

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def test_job_membership_uses_platform_center_and_fails_closed(self):
        self.assertTrue(repo.pipeline_job_belongs_to_center(41, 10))
        self.assertFalse(repo.pipeline_job_belongs_to_center(41, 20))
        self.assertFalse(repo.pipeline_job_belongs_to_center(43, 10))
        self.assertFalse(repo.pipeline_job_belongs_to_center(44, 10))
        self.assertFalse(repo.pipeline_job_belongs_to_center(999, 10))

    def test_folder_membership_requires_exact_pipeline_job(self):
        self.assertTrue(repo.course_folder_belongs_to_job(101, 41))
        self.assertFalse(repo.course_folder_belongs_to_job(101, 42))
        self.assertFalse(repo.course_folder_belongs_to_job(103, 41))
        self.assertFalse(repo.course_folder_belongs_to_job(104, 41))
        self.assertFalse(repo.course_folder_belongs_to_job(999, 41))

    def test_list_jobs_filters_by_center_and_can_combine_platform(self):
        center_a_jobs = repo.list_pipeline_jobs(center_account_id=10)
        center_b_jobs = repo.list_pipeline_jobs(center_account_id=20)
        mismatched_platform = repo.list_pipeline_jobs(2, center_account_id=10)

        self.assertEqual([job["id"] for job in center_a_jobs], [41])
        self.assertEqual([job["id"] for job in center_b_jobs], [42])
        self.assertEqual(mismatched_platform, [])


if __name__ == "__main__":
    unittest.main()
