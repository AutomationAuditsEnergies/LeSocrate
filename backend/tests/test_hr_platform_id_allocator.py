import os
import sqlite3
import unittest
from unittest.mock import patch

from flask import Flask

from routes.hr_routes import create_hr_blueprint


class _KeepOpenConnection(sqlite3.Connection):
    def close(self):
        pass

    def really_close(self):
        super().close()


def _make_hr_database():
    conn = sqlite3.connect(":memory:", factory=_KeepOpenConnection)
    conn.executescript(
        """
        CREATE TABLE platform_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            center_account_id INTEGER,
            name TEXT NOT NULL,
            slug TEXT,
            upload_locked INTEGER DEFAULT 1,
            public_access_enabled INTEGER DEFAULT 1,
            updated_at TEXT,
            audio_container TEXT,
            pdf_container TEXT,
            archive_container TEXT,
            status TEXT DEFAULT 'ready',
            source_formation_id INTEGER,
            source_module_id INTEGER,
            teacher_name TEXT,
            teacher_color TEXT,
            creation_request_id TEXT
        );
        INSERT INTO platform_config (id, name, slug) VALUES (7, 'Existante', 'existante');

        CREATE TABLE cours_config (
            id INTEGER PRIMARY KEY,
            heure_debut TEXT,
            platform_id INTEGER NOT NULL
        );
        INSERT INTO cours_config (id, heure_debut, platform_id)
        VALUES (1, '2026-07-10 09:00:00', 1);

        CREATE TABLE formation_modules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rncp_code TEXT,
            tp_name TEXT NOT NULL,
            version TEXT NOT NULL,
            status TEXT,
            source_pipeline_job_id INTEGER,
            source_platform_id INTEGER,
            center_account_id INTEGER,
            validated_at TEXT
        );
        """
    )
    conn.commit()
    return conn


class HrPlatformIdAllocatorTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(create_hr_blueprint())
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["is_admin"] = True
            sess["admin_account_type"] = "legacy_admin"

    def _post_empty_platform(self, conn, *, postgres_allocator):
        env = {
            "AZURE_AUDIO_STORAGE_CONNECTION_STRING": "",
            "AZURE_STORAGE_CONNECTION_STRING": "",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "routes.hr_routes.HR_ENABLED", True
        ), patch(
            "routes.hr_routes.get_db_connection", return_value=conn
        ), patch(
            "routes.hr_routes.platform_ids_use_postgres_allocator",
            return_value=postgres_allocator,
        ), patch(
            "routes.hr_routes.allocate_platform_id_from_postgres",
            return_value=50,
        ) as allocate_id, patch(
            "routes.hr_routes.postgres_enabled", return_value=postgres_allocator
        ), patch(
            "routes.hr_routes.upsert_platform_config"
        ) as upsert_platform, patch(
            "routes.hr_routes.upsert_cours_config"
        ), patch(
            "routes.hr_routes.create_postgres_manual_formation_module"
        ):
            response = self.client.post(
                "/api/hr/platforms",
                json={"name": "Nouvelle plateforme"},
            )
        return response, allocate_id, upsert_platform

    def test_hybrid_creation_uses_postgres_id_above_sqlite_max(self):
        conn = _make_hr_database()
        try:
            response, allocate_id, upsert_platform = self._post_empty_platform(
                conn,
                postgres_allocator=True,
            )

            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.get_json()["platform"]["id"], 50)
            allocate_id.assert_called_once_with(sqlite_max_id=7)
            row = conn.execute(
                "SELECT id, name, slug FROM platform_config WHERE id = 50"
            ).fetchone()
            self.assertEqual(row, (50, "Nouvelle plateforme", "nouvelle-plateforme"))
            self.assertEqual(upsert_platform.call_args.args[0]["id"], 50)
        finally:
            conn.really_close()

    def test_sqlite_mode_preserves_native_autoincrement(self):
        conn = _make_hr_database()
        try:
            response, allocate_id, upsert_platform = self._post_empty_platform(
                conn,
                postgres_allocator=False,
            )

            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.get_json()["platform"]["id"], 8)
            allocate_id.assert_not_called()
            upsert_platform.assert_not_called()
        finally:
            conn.really_close()


if __name__ == "__main__":
    unittest.main()
