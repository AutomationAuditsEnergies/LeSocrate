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
from services import formation_observability_service as obs
from services import knowledge_base_service as kbs


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

        CREATE TABLE cours_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL DEFAULT 1,
            name TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            formation_job_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE content_generation_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NOT NULL UNIQUE,
            platform_id INTEGER NOT NULL,
            program_text TEXT NOT NULL DEFAULT '',
            status TEXT DEFAULT 'idle',
            total_words INTEGER DEFAULT 0
        );

        CREATE TABLE content_generation_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending'
        );

        CREATE TABLE formation_knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            competence_index INTEGER NOT NULL,
            competence_key TEXT NOT NULL,
            competence_title TEXT NOT NULL,
            bloc TEXT,
            raw_source TEXT,
            definition_pedagogique TEXT DEFAULT '',
            etudes_de_cas TEXT DEFAULT '[]',
            pieges_frequents TEXT DEFAULT '[]',
            vocabulaire_metier TEXT DEFAULT '{}',
            contexte_terrain TEXT DEFAULT '',
            liens_connexes TEXT DEFAULT '[]',
            status TEXT DEFAULT 'pending',
            dirty INTEGER DEFAULT 0,
            error_message TEXT,
            total_words INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(job_id, competence_index)
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

    def test_expected_course_folder_queries_rank_best_candidate(self):
        job_id = repo.create_pipeline_job(
            platform_id=7,
            tp_name="TP Test",
            rncp_code="RNCP123",
            total_hours=7,
            nb_days=1,
        )
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            f"""
            INSERT INTO cours_folders (id, platform_id, name, position, formation_job_id)
            VALUES
                (10, 7, 'Jour 1 — Accueil', 0, {job_id}),
                (11, 7, 'Jour 1 — Accueil', 1, {job_id});

            INSERT INTO content_generation_jobs (id, folder_id, platform_id, program_text, status, total_words)
            VALUES
                (20, 10, 7, 'a', 'idle', 100),
                (21, 11, 7, 'b', 'completed', 50);

            INSERT INTO content_generation_segments (job_id, status)
            VALUES (21, 'completed'), (21, 'completed'), (20, 'completed');
            """
        )
        conn.commit()
        conn.close()

        matches = repo.list_expected_course_folder_matches(job_id, "Jour 1 — Accueil")

        self.assertEqual([row["id"] for row in matches], [11, 10])
        self.assertEqual(matches[0]["content_status"], "completed")
        self.assertEqual(matches[0]["segments_completed"], 2)

    def test_create_and_attach_course_folder_for_job(self):
        job_id = repo.create_pipeline_job(
            platform_id=7,
            tp_name="TP Test",
            rncp_code="RNCP123",
            total_hours=7,
            nb_days=1,
        )

        created = repo.create_course_folder_for_job(
            platform_id=7,
            folder_name="Jour 1 — Accueil",
            formation_job_id=job_id,
        )
        self.assertEqual(created["position"], 0)
        self.assertEqual(created["content_job_id"], None)
        self.assertTrue(repo.course_folder_exists_for_job(job_id, "Jour 1 — Accueil"))

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO cours_folders (platform_id, name, position, formation_job_id)
            VALUES (7, 'Jour 2 — Vente', 1, NULL)
            """
        )
        orphan_id = conn.execute("SELECT MAX(id) FROM cours_folders").fetchone()[0]
        conn.commit()
        conn.close()

        self.assertEqual(repo.find_orphan_course_folder(7, "Jour 2 — Vente"), orphan_id)
        self.assertTrue(repo.attach_course_folder_to_job(job_id, orphan_id))
        self.assertTrue(repo.course_folder_exists_for_job(job_id, "Jour 2 — Vente"))

    def test_observability_service_uses_pipeline_repository_storage(self):
        report_id = obs.persist_review_report(
            99,
            10,
            {
                "generated_via": "api",
                "summary": {"segments_reviewed": 3},
                "by_segment": [],
            },
        )
        latest = obs.get_latest_review_report(99, 10)

        self.assertEqual(latest["persisted_report_id"], report_id)
        self.assertEqual(latest["summary"]["segments_reviewed"], 3)
        self.assertEqual(latest["generated_via"], "api")

        event_id = obs.log_pipeline_event(
            99,
            "review_finished",
            step="review",
            folder_id=10,
            message="ok",
            data={"segments": 3},
        )
        events = obs.list_pipeline_events(99)

        self.assertEqual([event["id"] for event in events], [event_id])
        self.assertEqual(events[0]["data"], {"segments": 3})
        self.assertEqual(obs.clear_pipeline_events(99), 1)
        self.assertEqual(obs.list_pipeline_events(99), [])

    def test_knowledge_base_checkpoint_helpers_use_repository_storage(self):
        competences = [
            {
                "competence_key": "accueillir-client",
                "competence_title": "Accueillir le client",
                "bloc": "CCP1",
                "raw_source": "source 1",
            },
            {
                "competence_key": "vendre-produit",
                "competence_title": "Vendre un produit",
                "bloc": "CCP1",
                "raw_source": "source 2",
            },
        ]
        kbs.insert_pending_competences(123, competences)

        pending = kbs.list_kb(123)
        self.assertEqual([row["competence_key"] for row in pending], ["accueillir-client", "vendre-produit"])
        self.assertEqual(kbs.kb_stats(123)["pending"], 2)

        kbs.save_enriched_competence(
            123,
            0,
            {
                "definition_pedagogique": "Definition",
                "etudes_de_cas": [{"titre": "Cas"}],
                "pieges_frequents": [{"piege": "Piege"}],
                "vocabulaire_metier": {"terme": "definition"},
                "contexte_terrain": "Terrain",
                "liens_connexes": ["vendre-produit"],
            },
            42,
        )
        kbs.mark_competence_error(123, 1, "erreur test")

        rows = kbs.list_kb(123)
        self.assertEqual(rows[0]["status"], "completed")
        self.assertEqual(rows[0]["etudes_de_cas"], [{"titre": "Cas"}])
        self.assertEqual(rows[0]["vocabulaire_metier"], {"terme": "definition"})
        self.assertEqual(rows[1]["status"], "error")
        self.assertEqual(rows[1]["error_message"], "erreur test")

        stats = kbs.kb_stats(123)
        self.assertEqual(stats["completed"], 1)
        self.assertEqual(stats["error"], 1)
        self.assertEqual(stats["total_words"], 42)

        kbs.clear_kb(123)
        self.assertEqual(kbs.list_kb(123), [])


if __name__ == "__main__":
    unittest.main()
