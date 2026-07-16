import unittest
from unittest.mock import patch

import config
from database import db
from database import db_safety


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

    def test_sqlite_connection_fails_closed_in_pure_postgres_mode(self):
        with patch.object(db, "sqlite_runtime_enabled", return_value=False), patch.object(
            db.sqlite3, "connect"
        ) as connect:
            with self.assertRaises(db.SQLiteRuntimeDisabledError):
                db.get_db_connection()
            connect.assert_not_called()

    def test_sqlite_initialization_fails_closed_in_pure_postgres_mode(self):
        with patch.object(db, "sqlite_runtime_enabled", return_value=False), patch.object(
            db.sqlite3, "connect"
        ) as connect:
            with self.assertRaises(db.SQLiteRuntimeDisabledError):
                db.init_database()
            connect.assert_not_called()

    def test_sqlite_maintenance_never_blocks_pure_postgres_requests(self):
        with patch.object(db_safety, "sqlite_runtime_enabled", return_value=False), patch.object(
            db_safety, "is_maintenance", return_value=True
        ):
            self.assertFalse(db_safety.maintenance_blocks_requests())

    def test_sqlite_maintenance_still_blocks_legacy_runtime(self):
        with patch.object(db_safety, "sqlite_runtime_enabled", return_value=True), patch.object(
            db_safety, "is_maintenance", return_value=True
        ):
            self.assertTrue(db_safety.maintenance_blocks_requests())


if __name__ == "__main__":
    unittest.main()
