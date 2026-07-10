import unittest
from unittest.mock import patch

import config


class DatabaseRuntimeModeTest(unittest.TestCase):
    def test_pure_postgres_has_no_sqlite_runtime_dependency(self):
        with patch.object(config, "DATABASE_BACKEND", "postgres"), patch.object(
            config, "PIPELINE_DATABASE_BACKEND", "postgres"
        ):
            self.assertFalse(config.sqlite_runtime_enabled())

    def test_hybrid_keeps_legacy_sqlite_runtime(self):
        with patch.object(config, "DATABASE_BACKEND", "hybrid"), patch.object(
            config, "PIPELINE_DATABASE_BACKEND", "postgres"
        ):
            self.assertTrue(config.sqlite_runtime_enabled())

    def test_postgres_core_with_sqlite_pipeline_keeps_sqlite(self):
        with patch.object(config, "DATABASE_BACKEND", "postgres_core"), patch.object(
            config, "PIPELINE_DATABASE_BACKEND", "sqlite"
        ):
            self.assertTrue(config.sqlite_runtime_enabled())


if __name__ == "__main__":
    unittest.main()
