import sys
import unittest

from run_saas import build_child_specs


class SaaSProcessSupervisorTests(unittest.TestCase):
    def test_web_and_background_work_are_isolated(self):
        specs = build_child_specs(
            {
                "PIPELINE_DEDICATED_WORKER": "1",
                "COURSE_SCHEDULER_ENABLED": "1",
                "DATABASE_URL": "postgresql://example.invalid/db",
            }
        )

        self.assertEqual(
            [spec.name for spec in specs],
            ["web", "pipeline-worker", "course-scheduler"],
        )
        web, pipeline, scheduler = specs
        self.assertEqual(web.command, (sys.executable, "run.py"))
        self.assertTrue(web.critical)
        self.assertEqual(web.env["PIPELINE_EMBEDDED_WORKER"], "0")
        self.assertEqual(web.env["COURSE_SCHEDULER_ENABLED"], "0")
        self.assertEqual(web.env["SOCRATE_PROCESS_ROLE"], "web")

        self.assertEqual(
            pipeline.command,
            (sys.executable, "-m", "workers.pipeline_worker"),
        )
        self.assertEqual(pipeline.env["SOCRATE_PROCESS_ROLE"], "pipeline-worker")
        self.assertEqual(
            scheduler.command,
            (sys.executable, "-m", "workers.course_scheduler_worker"),
        )
        self.assertEqual(scheduler.env["SOCRATE_PROCESS_ROLE"], "course-scheduler")
        self.assertEqual(scheduler.env["DATABASE_URL"], "postgresql://example.invalid/db")

    def test_background_processes_are_opt_in(self):
        specs = build_child_specs({})
        self.assertEqual([spec.name for spec in specs], ["web"])

    def test_legacy_embedded_flag_still_enables_isolated_pipeline_worker(self):
        specs = build_child_specs({"PIPELINE_EMBEDDED_WORKER": "true"})
        self.assertEqual([spec.name for spec in specs], ["web", "pipeline-worker"])


if __name__ == "__main__":
    unittest.main()
