import unittest
from pathlib import Path


class Formation3PurePostgresDeploymentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (
            Path(__file__).resolve().parents[2]
            / ".github"
            / "workflows"
            / "staging_formation3.yml"
        ).read_text(encoding="utf-8")

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

    def test_formation3_runs_the_durable_course_scheduler(self):
        for setting in (
            "COURSE_SCHEDULER_ENABLED=1",
            "COURSE_SCHEDULER_INTERVAL_SECONDS=300",
            "COURSE_SCHEDULE_CHANGE_CUTOFF_HOURS=72",
            "SCHEDULED_AUDIO_HORIZON_HOURS=24",
            "SCHEDULED_AUDIO_MAX_AUTO_ATTEMPTS=4",
        ):
            self.assertIn(setting, self.workflow)

    def test_deployment_waits_for_scm_after_configuration_restart(self):
        configure_index = self.workflow.index("- name: Configure SaaS Postgres copy")
        wait_index = self.workflow.index("- name: Wait for Azure SCM restart")
        deploy_index = self.workflow.index("- name: Deploy to Azure Web App")
        self.assertLess(configure_index, wait_index)
        self.assertLess(wait_index, deploy_index)
        self.assertIn("sleep 45", self.workflow[wait_index:deploy_index])


if __name__ == "__main__":
    unittest.main()
