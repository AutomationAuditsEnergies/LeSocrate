import unittest
from pathlib import Path


class Formation3PurePostgresDeploymentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflows = Path(__file__).resolve().parents[2] / ".github" / "workflows"
        cls.workflow = (workflows / "staging_formation3.yml").read_text(encoding="utf-8")
        cls.postgres_ci = (workflows / "postgres-ci.yml").read_text(encoding="utf-8")

    def test_formation3_uses_pure_postgres(self):
        self.assertIn("DATABASE_BACKEND=postgres", self.workflow)
        self.assertIn("PIPELINE_DATABASE_BACKEND=postgres", self.workflow)
        self.assertNotIn("DATABASE_BACKEND=hybrid", self.workflow)

    def test_legacy_sqlite_settings_are_deleted_not_configured(self):
        self.assertIn("--setting-names DB_PATH SQLITE_SAFETY_STRICT", self.workflow)
        self.assertNotIn("DB_PATH=/home/database.db", self.workflow)
        self.assertNotIn("SQLITE_SAFETY_STRICT=0", self.workflow)

    def test_deployment_verifies_pure_postgres_settings(self):
        self.assertIn("PURE_POSTGRES_CONFIGURATION_FAILED", self.workflow)
        self.assertIn("PURE_POSTGRES_CONFIGURATION_OK", self.workflow)

    def test_deployment_configures_deep_readiness_thresholds(self):
        self.assertIn("PIPELINE_WORKER_READY_STALE_SECONDS=180", self.workflow)
        self.assertIn("PIPELINE_READY_QUEUE_STALL_SECONDS=600", self.workflow)
        self.assertIn("PIPELINE_READY_BLOB_CACHE_SECONDS=60", self.workflow)
        self.assertIn("--generic-configurations '{\"healthCheckPath\":\"/readyz\"}'", self.workflow)

    def test_ci_runs_formation3_boundaries_under_postgres_job_environment(self):
        start = self.postgres_ci.index("- name: Run Formation3 PostgreSQL runtime boundary tests")
        end = self.postgres_ci.index(
            "- name: Run legacy compatibility and general runtime safety tests",
            start,
        )
        boundary_step = self.postgres_ci[start:end]
        self.assertNotIn("DATABASE_BACKEND: sqlite", boundary_step)
        self.assertNotIn("PIPELINE_DATABASE_BACKEND: sqlite", boundary_step)
        for module in (
            "tests.test_audio_postgres_runtime",
            "tests.test_claude_code_humanization",
            "tests.test_course_schedule_repository",
            "tests.test_hr_playlist_queue_routes",
            "tests.test_runtime_readiness",
            "tests.test_script_review_blob_storage",
        ):
            self.assertIn(module, boundary_step)


if __name__ == "__main__":
    unittest.main()
