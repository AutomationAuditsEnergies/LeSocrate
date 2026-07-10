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


if __name__ == "__main__":
    unittest.main()
