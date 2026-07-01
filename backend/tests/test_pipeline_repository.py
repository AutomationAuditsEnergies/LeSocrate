import os
import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from repositories import pipeline_repository as repo


def _connect(path):
    return sqlite3.connect(path)


def _make_pipeline_db():
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.executescript(
        """
        CREATE TABLE platform_config (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        INSERT INTO platform_config (id, name) VALUES (7, 'Centre A - TP Test');

        CREATE TABLE formation_pipeline_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL DEFAULT 1,
            tp_name TEXT NOT NULL,
            rncp_code TEXT,
            total_hours INTEGER NOT NULL,
            nb_days INTEGER NOT NULL,
            reac_text TEXT,
            rc_text TEXT,
            rome_text TEXT,
            global_program TEXT,
            global_program_validated INTEGER DEFAULT 0,
            daily_programs TEXT DEFAULT '[]',
            daily_programs_validated INTEGER DEFAULT 0,
            status TEXT DEFAULT 'init',
            error_message TEXT,
            kb_generated_via TEXT,
            global_program_generated_via TEXT,
            daily_programs_generated_via TEXT,
            auto_pilot_enabled INTEGER DEFAULT 0,
            auto_pilot_step TEXT,
            auto_pilot_model TEXT,
            auto_pilot_tts_mode TEXT,
            auto_pilot_use_cc INTEGER DEFAULT 0,
            auto_pilot_skip_vs INTEGER DEFAULT 0,
            auto_pilot_generate_audio INTEGER DEFAULT 0,
            auto_pilot_volume_done INTEGER DEFAULT 0,
            auto_pilot_post_review_docs_done INTEGER DEFAULT 0,
            auto_pilot_error TEXT,
            auto_pilot_locked_at TIMESTAMP,
            auto_pilot_lock_owner TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()
    conn.close()
    return tmp.name


class PipelineRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.db_path = _make_pipeline_db()
        self.patches = [
            patch.object(repo, "get_db_connection", lambda: _connect(self.db_path)),
            patch.object(repo, "_pipeline_primary_backend", lambda: "sqlite"),
            patch.object(repo, "_pipeline_mirror_enabled", lambda: False),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        os.unlink(self.db_path)

    def test_create_update_get_and_list_pipeline_job_on_sqlite(self):
        job_id = repo.create_pipeline_job(
            platform_id=7,
            tp_name="TP Test",
            rncp_code="RNCP123",
            total_hours=14,
            nb_days=2,
        )

        job = repo.get_pipeline_job(job_id)
        self.assertEqual(job["id"], job_id)
        self.assertEqual(job["platform_id"], 7)
        self.assertEqual(job["platform_name"], "Centre A - TP Test")
        self.assertEqual(job["status"], "init")
        self.assertFalse(job["global_program_validated"])

        repo.update_pipeline_job(job_id, status="error", error_message="boom")
        self.assertEqual(repo.get_pipeline_job(job_id)["error_message"], "boom")

        repo.update_pipeline_job(job_id, status="daily_validated")
        updated = repo.get_pipeline_job(job_id)
        self.assertEqual(updated["status"], "daily_validated")
        self.assertIsNone(updated["error_message"])

        jobs = repo.list_pipeline_jobs()
        self.assertEqual([item["id"] for item in jobs], [job_id])
        self.assertEqual(jobs[0]["platform_label"], "P7")

    def test_auto_pilot_resume_query_keeps_sqlite_lock_semantics(self):
        job_id = repo.create_pipeline_job(
            platform_id=7,
            tp_name="TP Test",
            rncp_code="RNCP123",
            total_hours=7,
            nb_days=1,
        )
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            UPDATE formation_pipeline_jobs
            SET auto_pilot_enabled = 1,
                auto_pilot_step = 'audio',
                auto_pilot_error = NULL,
                auto_pilot_locked_at = datetime('now', '-10 minutes')
            WHERE id = ?
            """,
            (job_id,),
        )
        conn.commit()
        conn.close()

        self.assertEqual(repo.get_auto_pilot_pipeline_jobs_to_resume(), [job_id])


if __name__ == "__main__":
    unittest.main()
