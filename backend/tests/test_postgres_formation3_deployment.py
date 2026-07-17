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

    def test_schema_migration_quiesces_and_always_restarts_existing_app(self):
        schema_index = self.workflow.index(
            "- name: Apply idempotent Postgres schema with application quiesced"
        )
        configure_index = self.workflow.index("- name: Configure SaaS Postgres copy")
        schema_step = self.workflow[schema_index:configure_index]
        self.assertIn("az webapp stop", schema_step)
        self.assertIn("trap restart_app EXIT", schema_step)
        self.assertIn("APPLICATION_QUIESCED", schema_step)
        self.assertIn("az webapp start", schema_step)

    def test_formation3_runs_the_durable_course_scheduler(self):
        for setting in (
            "COURSE_SCHEDULER_ENABLED=1",
            "COURSE_SCHEDULER_INTERVAL_SECONDS=30",
            "COURSE_REMINDER_DELIVERY_BATCH_SIZE=100",
            "COURSE_REMINDER_MAX_BATCHES_PER_TICK=20",
            "COURSE_REMINDER_MAX_ATTEMPTS=5",
            "REMINDER_WEBHOOK_MAX_CONCURRENCY=16",
            "COURSE_REMINDER_SMTP_TIMEOUT_SECONDS=25",
            "COURSE_REMINDER_IMAP_TIMEOUT_SECONDS=25",
            "COURSE_SESSION_PASSWORD_EARLY_HOURS=8784",
            "COURSE_SESSION_PASSWORD_LENGTH=8",
            "COURSE_INVITATION_TOKEN_MAX_AGE_SECONDS=32000000",
            "COURSE_SCHEDULE_CHANGE_CUTOFF_HOURS=72",
            "COURSE_START_TIME_POLICY=fixed_09",
            "SCHEDULED_AUDIO_HORIZON_HOURS=24",
            "SCHEDULED_AUDIO_READY_HOURS_BEFORE=24",
            "SCHEDULED_AUDIO_BUILD_BUFFER_HOURS=2",
            "SCHEDULED_AUDIO_BATCH_SIZE=50",
            "SCHEDULED_AUDIO_MAX_CONCURRENCY=1",
            "SCHEDULED_AUDIO_MAX_AUTO_ATTEMPTS=4",
            "ALLOW_LEGACY_BULK_AUDIO=0",
            "TEACHER_ASSET_GENERATOR_VERSION=pipeline-v1",
            "STUDENT_AUDIO_DELIVERY_MODE=redirect_sas",
        ):
            self.assertIn(setting, self.workflow)

    def test_web_api_and_background_workers_use_isolated_processes(self):
        self.assertIn("STARTUP_COMMAND: python run_saas.py", self.workflow)
        self.assertIn("PIPELINE_EMBEDDED_WORKER=0", self.workflow)
        self.assertIn("PIPELINE_DEDICATED_WORKER=1", self.workflow)

    def test_deployment_requires_a_real_reminder_transport(self):
        self.assertIn("REMINDER_DELIVERY_READY", self.workflow)
        self.assertIn("REMINDER_DELIVERY_MISSING", self.workflow)
        self.assertIn("REMINDER_DELIVERY_REQUIRED", self.workflow)
        self.assertIn("REMINDER_DELIVERY_OPTIONAL", self.workflow)
        self.assertIn(
            "REMINDER_WEBHOOK_URL+REMINDER_WEBHOOK_KEY|EMAIL_USERNAME+EMAIL_PASSWORD",
            self.workflow,
        )

    def test_deployment_waits_for_scm_after_configuration_restart(self):
        configure_index = self.workflow.index("- name: Configure SaaS Postgres copy")
        wait_index = self.workflow.index("- name: Wait for Azure SCM restart")
        deploy_index = self.workflow.index("- name: Deploy to Azure Web App")
        self.assertLess(configure_index, wait_index)
        self.assertLess(wait_index, deploy_index)
        self.assertIn("sleep 45", self.workflow[wait_index:deploy_index])

    def test_deployment_fails_when_the_deployed_app_never_becomes_ready(self):
        deploy_index = self.workflow.index("- name: Deploy to Azure Web App")
        readiness_index = self.workflow.index(
            "- name: Verify deployed application readiness"
        )
        self.assertLess(deploy_index, readiness_index)
        readiness = self.workflow[readiness_index:]
        self.assertIn('"https://${app_host}/readyz"', readiness)
        self.assertIn("DEPLOYMENT_NOT_READY", readiness)


if __name__ == "__main__":
    unittest.main()
