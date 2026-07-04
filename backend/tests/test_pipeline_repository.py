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
from services import content_generation_service as cgs
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
            name TEXT NOT NULL,
            source_formation_id INTEGER
        );
        INSERT INTO platform_config (id, name) VALUES (7, 'Centre A - TP Test');

        CREATE TABLE course_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL,
            session_index INTEGER NOT NULL,
            scheduled_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'planned',
            activated_at TEXT,
            completed_at TEXT,
            reminder_previous_evening_sent_at TEXT,
            reminder_5min_sent_at TEXT,
            audio_generation_status TEXT DEFAULT 'pending',
            audio_generation_started_at TEXT,
            audio_generation_completed_at TEXT,
            audio_generation_error TEXT,
            audio_job_id INTEGER,
            audio_folder_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(platform_id, session_index)
        );

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

        CREATE TABLE cours_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            doc_type TEXT DEFAULT 'source',
            status TEXT DEFAULT 'uploaded',
            audio_filename TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE content_generation_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NOT NULL UNIQUE,
            platform_id INTEGER NOT NULL,
            program_text TEXT NOT NULL,
            program_title TEXT DEFAULT '',
            sub_parts TEXT DEFAULT '[]',
            status TEXT DEFAULT 'idle',
            current_sub_part INTEGER DEFAULT 0,
            current_passe INTEGER DEFAULT 1,
            total_words INTEGER DEFAULT 0,
            error_message TEXT,
            from_scratch INTEGER DEFAULT 0,
            module_contents TEXT DEFAULT '{}',
            carryover_in_text TEXT DEFAULT '',
            carryover_in_source_folder_id INTEGER,
            carryover_out_text TEXT DEFAULT '',
            carryover_out_target_folder_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE content_generation_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            sub_part_index INTEGER NOT NULL,
            sub_part_name TEXT NOT NULL,
            passe INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            text_content TEXT DEFAULT '',
            word_count INTEGER DEFAULT 0,
            dirty INTEGER DEFAULT 0,
            humanized INTEGER DEFAULT 0,
            humanization_error TEXT,
            humanization_signature TEXT,
            reviewed INTEGER DEFAULT 0,
            review_error TEXT,
            review_signature TEXT,
            text_content_pre_review TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(job_id, sub_part_index, passe)
        );

        CREATE TABLE formation_modules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            center_account_id INTEGER,
            rncp_code TEXT,
            tp_name TEXT NOT NULL,
            version TEXT NOT NULL,
            status TEXT DEFAULT 'validated',
            source_pipeline_job_id INTEGER UNIQUE,
            source_platform_id INTEGER,
            voice_type TEXT,
            voice_updated_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            validated_at TIMESTAMP,
            archived_at TIMESTAMP
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

    def test_postgres_update_pipeline_job_coerces_auto_pilot_booleans(self):
        class FakeCursor:
            def __init__(self):
                self.rowcount = 1
                self.calls = []

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, params=None):
                self.calls.append((sql, params))

        class FakeConn:
            def __init__(self, cursor):
                self.cursor_obj = cursor

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def cursor(self):
                return self.cursor_obj

        cursor = FakeCursor()
        with (
            patch.object(repo, "_pipeline_primary_backend", lambda: "postgres"),
            patch.object(repo, "get_postgres_connection", lambda: FakeConn(cursor)),
        ):
            repo.update_pipeline_job(
                42,
                auto_pilot_enabled=1,
                auto_pilot_use_cc=0,
                auto_pilot_generate_audio="true",
            )

        self.assertEqual(cursor.calls[0][1], [True, False, True, 42])

    def test_auto_pilot_lock_helpers_keep_sqlite_lock_semantics(self):
        job_id = repo.create_pipeline_job(
            platform_id=7,
            tp_name="TP Test",
            rncp_code="RNCP123",
            total_hours=7,
            nb_days=1,
        )
        repo.update_pipeline_job(job_id, auto_pilot_enabled=1)

        self.assertTrue(repo.acquire_auto_pilot_lock(job_id, owner="worker-a", ttl_seconds=300))
        self.assertFalse(repo.acquire_auto_pilot_lock(job_id, owner="worker-b", ttl_seconds=300))

        repo.refresh_auto_pilot_lock(job_id, owner="worker-a")
        repo.release_auto_pilot_lock(job_id)

        self.assertTrue(repo.acquire_auto_pilot_lock(job_id, owner="worker-b", ttl_seconds=300))

    def test_due_audio_generation_sessions_use_repository_storage(self):
        old_job_id = repo.create_pipeline_job(
            platform_id=7,
            tp_name="TP Test A",
            rncp_code="RNCP123",
            total_hours=7,
            nb_days=1,
        )
        new_job_id = repo.create_pipeline_job(
            platform_id=7,
            tp_name="TP Test B",
            rncp_code="RNCP456",
            total_hours=7,
            nb_days=1,
        )
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            INSERT INTO course_sessions
                (id, platform_id, session_index, scheduled_at, status, audio_generation_started_at)
            VALUES
                (100, 7, 1, '2026-01-01 10:00:00', 'planned', NULL),
                (101, 7, 2, '2026-01-01 11:00:00', 'active', '2026-01-01 08:00:00'),
                (102, 7, 3, '2026-01-03 10:00:00', 'planned', NULL);
            """
        )
        conn.commit()
        conn.close()

        rows = repo.list_due_audio_generation_sessions(
            lower_bound="2026-01-01 00:00:00",
            upper_bound="2026-01-02 00:00:00",
            platform_ids=[7],
        )
        self.assertEqual([row["id"] for row in rows], [100])
        self.assertEqual(rows[0]["formation_job_id"], new_job_id)

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE platform_config SET source_formation_id = ? WHERE id = 7",
            (old_job_id,),
        )
        conn.commit()
        conn.close()

        rows = repo.list_due_audio_generation_sessions(
            lower_bound="2026-01-01 00:00:00",
            upper_bound="2026-01-02 00:00:00",
            platform_ids=[7],
        )
        self.assertEqual(rows[0]["formation_job_id"], old_job_id)

    def test_due_audio_generation_sessions_retry_failed_unfinished_session(self):
        job_id = repo.create_pipeline_job(
            platform_id=7,
            tp_name="TP Test",
            rncp_code="RNCP123",
            total_hours=7,
            nb_days=1,
        )
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            INSERT INTO course_sessions
                (id, platform_id, session_index, scheduled_at, status,
                 audio_generation_status, audio_generation_started_at,
                 audio_generation_completed_at)
            VALUES
                (110, 7, 1, '2026-01-01 10:00:00', 'planned',
                 'error', '2026-01-01 08:00:00', NULL),
                (111, 7, 2, '2026-01-01 11:00:00', 'planned',
                 'completed', '2026-01-01 08:00:00', '2026-01-01 09:00:00');
            """
        )
        conn.commit()
        conn.close()

        rows = repo.list_due_audio_generation_sessions(
            lower_bound="2026-01-01 00:00:00",
            upper_bound="2026-01-02 00:00:00",
            platform_ids=[7],
        )

        self.assertEqual([row["id"] for row in rows], [110])
        self.assertEqual(rows[0]["formation_job_id"], job_id)

    def test_due_audio_generation_sessions_read_sqlite_schedule_with_postgres_pipeline(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            UPDATE platform_config SET source_formation_id = 42 WHERE id = 7;
            INSERT INTO course_sessions
                (id, platform_id, session_index, scheduled_at, status, audio_generation_started_at)
            VALUES
                (120, 7, 1, '2026-01-01 10:00:00', 'planned', NULL);
            """
        )
        conn.commit()
        conn.close()

        def fail_postgres():
            raise AssertionError("course_sessions must not be read from Postgres")

        with (
            patch.object(repo, "_pipeline_primary_backend", lambda: "postgres"),
            patch.object(repo, "get_postgres_connection", fail_postgres),
        ):
            rows = repo.list_due_audio_generation_sessions(
                lower_bound="2026-01-01 00:00:00",
                upper_bound="2026-01-02 00:00:00",
                platform_ids=[7],
            )

        self.assertEqual([row["id"] for row in rows], [120])
        self.assertEqual(rows[0]["formation_job_id"], 42)

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

            INSERT INTO content_generation_segments (job_id, sub_part_index, sub_part_name, passe, status)
            VALUES
                (21, 0, 'A', 1, 'completed'),
                (21, 1, 'B', 1, 'completed'),
                (20, 0, 'A', 1, 'completed');
            """
        )
        conn.commit()
        conn.close()

        matches = repo.list_expected_course_folder_matches(job_id, "Jour 1 — Accueil")

        self.assertEqual([row["id"] for row in matches], [11, 10])
        self.assertEqual(matches[0]["content_status"], "completed")
        self.assertEqual(matches[0]["segments_completed"], 2)
        self.assertEqual(repo.list_course_folder_ids_for_platform(7), [10, 11])

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

    def test_content_generation_job_and_segments_use_repository_storage(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO cours_folders (id, platform_id, name, position, formation_job_id)
            VALUES (50, 7, 'Jour 1 — Accueil', 0, NULL)
            """
        )
        conn.commit()
        conn.close()

        repo.reset_and_upsert_content_generation_job(
            folder_id=50,
            platform_id=7,
            program_text="Programme",
            program_title="TP Test",
            sub_parts_json='["Cours 1"]',
            from_scratch=True,
            module_contents_json='{"Cours 1": "Brief"}',
        )
        job = cgs.get_job_from_db(50)

        self.assertEqual(job["folder_id"], 50)
        self.assertEqual(job["platform_id"], 7)
        self.assertEqual(job["sub_parts"], ["Cours 1"])
        self.assertTrue(job["from_scratch"])
        self.assertEqual(job["module_contents"], {"Cours 1": "Brief"})

        cgs._save_segment_db(job["id"], 0, "Cours 1", 1, "Bonjour tout le monde")
        self.assertEqual(cgs._get_completed_segments(job["id"]), {(0, 1)})
        self.assertEqual(cgs._get_segment_text(job["id"], 0, 1), "Bonjour tout le monde")
        self.assertEqual(cgs.get_segments_status(job["id"])[0]["word_count"], 4)

        cgs.mark_segment_modified(job["id"], 0, 1)
        snapshot = cgs._content_segments_artifact_snapshot(job["id"])
        self.assertEqual(snapshot[0]["sub_part_name"], "Cours 1")
        self.assertTrue(snapshot[0]["dirty"])
        self.assertFalse(snapshot[0]["reviewed"])

    def test_cross_day_carryover_uses_repository_storage(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            INSERT INTO cours_folders (id, platform_id, name, position, formation_job_id)
            VALUES
                (60, 7, 'Jour 1 — Accueil', 0, NULL),
                (61, 7, 'Jour 2 — Vente', 1, NULL);
            """
        )
        conn.commit()
        conn.close()

        for folder_id in (60, 61):
            repo.reset_and_upsert_content_generation_job(
                folder_id=folder_id,
                platform_id=7,
                program_text="Programme",
                program_title="TP Test",
                sub_parts_json='["Cours 1"]',
                from_scratch=True,
                module_contents_json='{}',
            )
            job = cgs.get_job_from_db(folder_id)
            cgs._save_segment_db(job["id"], 0, "Cours 1", 1, "Texte initial")

        target_job = cgs.get_job_from_db(61)
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE content_generation_segments SET dirty = 0 WHERE job_id = ?", (target_job["id"],))
        conn.commit()
        conn.close()

        self.assertEqual(cgs._find_next_folder_id(7, 60), 61)

        cgs._store_cross_day_carryover(60, 61, "Synthese du jour 1")
        source_job = cgs.get_job_from_db(60)
        target_job = cgs.get_job_from_db(61)

        self.assertEqual(source_job["carryover_out_text"], "Synthese du jour 1")
        self.assertEqual(source_job["carryover_out_target_folder_id"], 61)
        self.assertIn("Synthese du jour 1", target_job["carryover_in_text"])
        self.assertEqual(target_job["carryover_in_source_folder_id"], 60)
        self.assertEqual(cgs._get_existing_carryover_out(60, 61), "Synthese du jour 1")
        self.assertTrue(cgs._content_segments_artifact_snapshot(target_job["id"])[0]["dirty"])

        cgs._clear_cross_day_carryover_from_source(60, 61)
        self.assertEqual(cgs.get_job_from_db(60)["carryover_out_text"], "")
        self.assertEqual(cgs.get_job_from_db(61)["carryover_in_text"], "")

    def test_content_segment_helpers_use_repository_storage(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO cours_folders (id, platform_id, name, position, formation_job_id)
            VALUES (70, 7, 'Jour 1 — Segments', 0, NULL)
            """
        )
        conn.commit()
        conn.close()

        repo.reset_and_upsert_content_generation_job(
            folder_id=70,
            platform_id=7,
            program_text="Programme",
            program_title="TP Test",
            sub_parts_json='["Cours 1"]',
            from_scratch=True,
            module_contents_json='{}',
        )
        job = cgs.get_job_from_db(70)
        repo.save_completed_content_segment(
            job_id=job["id"],
            sub_part_index=0,
            sub_part_name="Cours 1",
            passe=1,
            text_content="Texte initial",
            word_count=2,
        )

        rows = repo.list_completed_content_segment_rows(job["id"])
        self.assertEqual(len(rows), 1)
        self.assertIn("id", rows[0])
        self.assertTrue(rows[0]["dirty"])

        repo.mark_content_segments_clean(job["id"], {(0, 1)})
        self.assertFalse(repo.list_completed_content_segment_rows(job["id"])[0]["dirty"])

        repo.update_content_segment_audio_calibration(
            segment_id=rows[0]["id"],
            text_content="<<<BLOC_AUDIO_1>>>\n\nTexte calibre",
            word_count=2,
            humanization_signature="sig-audio",
        )
        calibrated = repo.list_completed_content_segment_rows(job["id"])[0]
        self.assertEqual(calibrated["text_content"], "<<<BLOC_AUDIO_1>>>\n\nTexte calibre")
        self.assertTrue(calibrated["humanized"])
        self.assertFalse(calibrated["reviewed"])

        repo.update_content_segment_plan_repair(
            segment_id=rows[0]["id"],
            text_content="Texte repare",
            word_count=2,
        )
        repaired = repo.list_completed_content_segment_rows(job["id"])[0]
        self.assertEqual(repaired["text_content"], "Texte repare")
        self.assertFalse(repaired["humanized"])
        self.assertFalse(repaired["reviewed"])

        repo.delete_content_segments_for_job(job["id"])
        self.assertEqual(repo.list_completed_content_segment_rows(job["id"]), [])

    def test_final_script_document_helpers_replace_existing_rows(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            INSERT INTO cours_folders (id, platform_id, name, position, formation_job_id)
            VALUES (80, 7, 'Jour 1 — Documents', 0, NULL);

            INSERT INTO cours_documents
                (folder_id, filename, original_name, doc_type, status, audio_filename)
            VALUES
                (80, 'old-final.txt', 'script_tts_final.txt', 'final_script', 'uploaded', 'old-final.mp3'),
                (80, 'legacy.txt', 'cours_genere_123.txt', 'source', 'uploaded', NULL),
                (80, 'source.pdf', 'source.pdf', 'source', 'uploaded', NULL);
            """
        )
        conn.commit()
        conn.close()

        old_docs = repo.list_final_script_document_rows(80)
        self.assertEqual({row["filename"] for row in old_docs}, {"old-final.txt", "legacy.txt"})

        repo.replace_final_script_document_record(
            folder_id=80,
            filename="new-final.txt",
            original_name="script_tts_final.txt",
        )

        final_docs = repo.list_final_script_document_rows(80)
        self.assertEqual([row["filename"] for row in final_docs], ["new-final.txt"])

        conn = sqlite3.connect(self.db_path)
        remaining_sources = conn.execute(
            "SELECT filename FROM cours_documents WHERE folder_id = 80 AND doc_type = 'source'"
        ).fetchall()
        conn.close()
        self.assertEqual(remaining_sources, [("source.pdf",)])

    def test_content_review_helpers_use_repository_storage(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO cours_folders (id, platform_id, name, position, formation_job_id)
            VALUES (90, 7, 'Jour 1 — Review', 0, NULL)
            """
        )
        conn.commit()
        conn.close()

        repo.reset_and_upsert_content_generation_job(
            folder_id=90,
            platform_id=7,
            program_text="Programme",
            program_title="TP Test",
            sub_parts_json='["Cours 1"]',
            from_scratch=True,
            module_contents_json='{}',
        )
        job = cgs.get_job_from_db(90)
        repo.save_completed_content_segment(
            job_id=job["id"],
            sub_part_index=0,
            sub_part_name="Cours 1",
            passe=1,
            text_content="Texte a reviser",
            word_count=3,
        )

        repo.ensure_content_review_state_columns()
        self.assertEqual(repo.snapshot_content_segments_pre_review(job["id"]), 1)
        self.assertEqual(repo.snapshot_content_segments_pre_review(job["id"]), 0)

        total, rows = repo.select_content_segments_for_review(
            job_id=job["id"],
            reviewed_column="reviewed",
            signature_column="review_signature",
            review_signature="sig-review",
            force=False,
        )
        self.assertEqual(total, 1)
        self.assertEqual(len(rows), 1)
        seg_id = rows[0]["id"]

        repo.reset_content_segments_review_state(
            segment_ids=[seg_id],
            reviewed_column="reviewed",
            error_column="review_error",
        )
        repo.record_content_segment_review_error(
            segment_id=seg_id,
            error_column="review_error",
            error_message="erreur reviewer",
        )
        conn = sqlite3.connect(self.db_path)
        review_error = conn.execute(
            "SELECT review_error FROM content_generation_segments WHERE id = ?",
            (seg_id,),
        ).fetchone()[0]
        conn.close()
        self.assertEqual(review_error, "erreur reviewer")

        repo.mark_content_segment_review_clean(
            segment_id=seg_id,
            reviewed_column="reviewed",
            error_column="review_error",
            signature_column="review_signature",
            review_signature="sig-review",
        )
        total, rows = repo.select_content_segments_for_review(
            job_id=job["id"],
            reviewed_column="reviewed",
            signature_column="review_signature",
            review_signature="sig-review",
            force=False,
        )
        self.assertEqual(total, 1)
        self.assertEqual(rows, [])

        repo.mark_content_segment_review_patched(
            segment_id=seg_id,
            text_content="Texte humanise",
            word_count=2,
            reviewed_column="humanized",
            error_column="humanization_error",
            signature_column="humanization_signature",
            review_signature="sig-human",
            invalidate_compliance_on_change=True,
        )
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            """
            SELECT text_content, word_count, dirty, humanized, humanization_signature,
                   reviewed, review_signature, text_content_pre_review
            FROM content_generation_segments
            WHERE id = ?
            """,
            (seg_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], "Texte humanise")
        self.assertEqual(row[1], 2)
        self.assertEqual(row[2], 1)
        self.assertEqual(row[3], 1)
        self.assertEqual(row[4], "sig-human")
        self.assertEqual(row[5], 0)
        self.assertIsNone(row[6])
        self.assertEqual(row[7], "Texte a reviser")

    def test_health_helpers_use_repository_storage(self):
        job_id = repo.create_pipeline_job(
            platform_id=7,
            tp_name="TP Health",
            rncp_code="RNCP999",
            total_hours=14,
            nb_days=2,
        )
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            f"""
            INSERT INTO cours_folders (id, platform_id, name, position, formation_job_id)
            VALUES
                (110, 7, 'Jour 1 — Health', 0, {job_id}),
                (111, 7, 'Jour 2 — Health', 1, {job_id});

            INSERT INTO content_generation_jobs
                (id, folder_id, platform_id, program_text, program_title, sub_parts, status)
            VALUES
                (210, 110, 7, 'p', 'TP', '["Cours 1"]', 'completed'),
                (211, 111, 7, 'p', 'TP', '["Cours 1"]', 'idle');

            INSERT INTO content_generation_segments
                (job_id, sub_part_index, sub_part_name, passe, status, text_content,
                 word_count, dirty, humanized, humanization_error, reviewed, review_error,
                 text_content_pre_review)
            VALUES
                (210, 0, 'Cours 1', 1, 'completed', 'Texte 1', 2, 1, 0, NULL, 1, NULL, 'Avant 1'),
                (210, 0, 'Cours 1', 2, 'completed', 'Texte 2', 2, 0, 1, NULL, 0, NULL, NULL),
                (211, 0, 'Cours 1', 1, 'pending', 'Texte 3', 2, 0, 0, NULL, 0, NULL, NULL);

            INSERT INTO formation_modules
                (source_pipeline_job_id, source_platform_id, tp_name, rncp_code, version, status)
            VALUES
                ({job_id}, 7, 'TP Health', 'RNCP999', 'v1', 'validated');
            """
        )
        conn.commit()
        conn.close()

        folders = repo.list_health_course_folder_rows([110, 111])
        self.assertEqual([row["id"] for row in folders], [110, 111])
        self.assertEqual(folders[0]["content_job_id"], 210)
        self.assertEqual(folders[1]["content_status"], "idle")

        self.assertEqual(repo.count_completed_segments_for_folders([110, 111]), 2)
        self.assertEqual(repo.count_segments_with_pre_review_snapshot_for_folders([110, 111]), 1)
        self.assertEqual(repo.count_unhumanized_segments_without_error_for_folders([110, 111]), 1)
        self.assertEqual(repo.count_unreviewed_segments_without_error_for_folders([110, 111]), 1)
        self.assertEqual(repo.count_dirty_completed_segments_for_folders([110, 111]), 1)
        completion_rows = repo.list_content_completion_rows_for_folders([110, 111])
        completion_by_folder = {row["folder_id"]: row for row in completion_rows}
        self.assertEqual(completion_by_folder[110]["status"], "completed")
        self.assertEqual(completion_by_folder[110]["completed_segments"], 2)
        self.assertEqual(completion_by_folder[111]["status"], "idle")
        self.assertEqual(
            repo.list_completed_content_jobs_for_folders([110, 111]),
            [{"folder_id": 110, "content_job_id": 210}],
        )
        self.assertEqual(repo.count_segments_pending_review_for_folders([110, 111], "sig-review"), 2)

        docx_state = repo.get_content_job_docx_state(210)
        self.assertEqual(docx_state["completed_count"], 2)
        self.assertEqual(docx_state["sub_parts"], '["Cours 1"]')

        module = repo.get_formation_module_for_pipeline_job(job_id)
        self.assertEqual(module["version"], "v1")
        self.assertEqual(module["status"], "validated")

    def test_script_annotation_helpers_use_repository_storage(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO cours_folders (id, platform_id, name, position, formation_job_id)
            VALUES (120, 7, 'Jour 1 — Annotation', 0, NULL)
            """
        )
        conn.commit()
        conn.close()

        repo.reset_and_upsert_content_generation_job(
            folder_id=120,
            platform_id=7,
            program_text="Programme",
            program_title="TP Annotation",
            sub_parts_json='["Cours 1"]',
            from_scratch=True,
            module_contents_json='{}',
        )
        job = cgs.get_job_from_db(120)
        cgs._save_segment_db(job["id"], 0, "Cours 1", 1, "Bonjour ancien texte")

        repo.ensure_script_annotations_table()
        context = repo.get_script_annotation_context(120)
        self.assertEqual(context["job_id"], job["id"])
        self.assertEqual(context["platform_name"], "Centre A - TP Test")

        annotation_id = repo.create_script_annotation_row(
            folder_id=120,
            job_id=job["id"],
            source_type="segment",
            sub_part_index=0,
            passe=1,
            bloc_number=None,
            filename="",
            selected_text="ancien texte",
            comment="rendre plus clair",
            original_paragraph="ancien texte",
        )
        rows = repo.list_script_annotation_rows(folder_id=120, job_id=job["id"])
        self.assertEqual([row["id"] for row in rows], [annotation_id])
        self.assertEqual(rows[0]["correction_status"], "pending")

        repo.update_script_annotation_correction(
            annotation_id=annotation_id,
            folder_id=120,
            job_id=job["id"],
            original_paragraph="ancien texte",
            proposed_text="nouveau texte",
            correction_status="proposed",
            correction_error=None,
        )
        apply_row = repo.get_script_annotation_for_apply(
            annotation_id=annotation_id,
            folder_id=120,
            job_id=job["id"],
        )
        self.assertEqual(apply_row["proposed_text"], "nouveau texte")

        seg = repo.get_content_segment_row_for_key(
            job_id=job["id"],
            sub_part_index=0,
            passe=1,
        )
        self.assertIn("ancien texte", seg["text_content"])

        repo.update_content_segment_plan_repair(
            segment_id=seg["id"],
            text_content=seg["text_content"].replace("ancien texte", "nouveau texte"),
            word_count=3,
        )
        repo.mark_script_annotation_applied(annotation_id)
        repo.update_script_annotation_splice_result(
            annotation_id=annotation_id,
            splice_status="skipped",
            splice_error="source_type != course",
            splice_blob_path=None,
        )

        applied = repo.list_script_annotation_rows(folder_id=120, job_id=job["id"])[0]
        self.assertEqual(applied["correction_status"], "applied")
        self.assertEqual(applied["splice_status"], "skipped")
        self.assertEqual(repo.get_content_segment_text(job["id"], 0, 1), "Bonjour nouveau texte")

        changed = repo.mark_script_annotation_rejected(
            annotation_id=annotation_id,
            folder_id=120,
            job_id=job["id"],
        )
        self.assertEqual(changed, 1)
        rejected = repo.list_script_annotation_rows(folder_id=120, job_id=job["id"])[0]
        self.assertEqual(rejected["correction_status"], "rejected")

        changed = repo.mark_script_annotation_deleted(
            annotation_id=annotation_id,
            folder_id=120,
            job_id=job["id"],
        )
        self.assertEqual(changed, 1)
        self.assertEqual(repo.list_script_annotation_rows(folder_id=120, job_id=job["id"]), [])
        self.assertEqual(
            len(repo.list_script_annotation_rows(folder_id=120, job_id=job["id"], include_deleted=True)),
            1,
        )

    def test_script_rules_helpers_use_repository_storage(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO cours_folders (id, platform_id, name, position, formation_job_id)
            VALUES (130, 7, 'Jour 1 - Rules', 0, NULL)
            """
        )
        conn.commit()
        conn.close()

        repo.reset_and_upsert_content_generation_job(
            folder_id=130,
            platform_id=7,
            program_text="Programme",
            program_title="TP Rules",
            sub_parts_json='["Cours 1"]',
            from_scratch=True,
            module_contents_json='{}',
        )
        job = cgs.get_job_from_db(130)
        cgs._save_segment_db(job["id"], 0, "Cours 1", 1, "Segment a corriger")

        repo.ensure_script_annotations_table()
        applied_id = repo.create_script_annotation_row(
            folder_id=130,
            job_id=job["id"],
            source_type="segment",
            sub_part_index=0,
            passe=1,
            bloc_number=None,
            filename="",
            selected_text="corriger",
            comment="plus oral",
            original_paragraph="Segment a corriger",
        )
        repo.update_script_annotation_correction(
            annotation_id=applied_id,
            folder_id=130,
            job_id=job["id"],
            original_paragraph="Segment a corriger",
            proposed_text="Segment corrige",
            correction_status="applied",
            correction_error=None,
        )
        proposed_id = repo.create_script_annotation_row(
            folder_id=130,
            job_id=job["id"],
            source_type="course",
            sub_part_index=None,
            passe=None,
            bloc_number=1,
            filename="bloc_1.mp3",
            selected_text="texte propose",
            comment="test",
            original_paragraph="texte propose",
        )
        repo.update_script_annotation_correction(
            annotation_id=proposed_id,
            folder_id=130,
            job_id=job["id"],
            original_paragraph="texte propose",
            proposed_text="texte propose modifie",
            correction_status="proposed",
            correction_error=None,
        )
        deleted_id = repo.create_script_annotation_row(
            folder_id=130,
            job_id=job["id"],
            source_type="segment",
            sub_part_index=0,
            passe=1,
            bloc_number=None,
            filename="",
            selected_text="ignore",
            comment="ignore",
            original_paragraph="ignore",
        )
        repo.mark_script_annotation_deleted(
            annotation_id=deleted_id,
            folder_id=130,
            job_id=job["id"],
        )

        rule_annotations = repo.list_script_rule_annotation_rows(folder_id=130, job_id=job["id"])
        self.assertEqual([row["id"] for row in rule_annotations], [applied_id, proposed_id])
        self.assertEqual(rule_annotations[0]["correction_status"], "applied")

        context = repo.get_script_rules_context(130)
        self.assertEqual(context["job_id"], job["id"])
        self.assertEqual(context["folder_name"], "Jour 1 - Rules")

        repo.ensure_script_rules_table()
        repo.upsert_generated_script_rules(
            folder_id=130,
            job_id=job["id"],
            rules_markdown="# Règles\n\n## Règle 1\n",
            rules_count=1,
            source_annotations_count=2,
            model="model-a",
            markdown_path="/tmp/generated-rules.md",
        )
        rules = repo.get_script_rules_row(folder_id=130, job_id=job["id"])
        self.assertEqual(rules["rules_count"], 1)
        self.assertEqual(rules["source_annotations_count"], 2)
        self.assertEqual(rules["model"], "model-a")

        repo.upsert_manual_script_rules(
            folder_id=130,
            job_id=job["id"],
            rules_markdown="# Manuel\n\n## Règle 2\n",
            rules_count=1,
            markdown_path="/tmp/manual-rules.md",
        )
        manual_rules = repo.get_script_rules_row(folder_id=130, job_id=job["id"])
        self.assertEqual(manual_rules["rules_markdown"], "# Manuel\n\n## Règle 2\n")
        self.assertEqual(manual_rules["markdown_path"], "/tmp/manual-rules.md")
        self.assertEqual(manual_rules["source_annotations_count"], 2)
        self.assertEqual(manual_rules["model"], "model-a")

        segments = repo.list_completed_content_segment_rows(job["id"])
        self.assertEqual(len(segments), 1)
        segment_id = segments[0]["id"]
        self.assertEqual(repo.get_content_segment_text_by_id(segment_id), "Segment a corriger")
        repo.update_content_segment_plan_repair(
            segment_id=segment_id,
            text_content="Segment corrige",
            word_count=2,
        )
        self.assertEqual(repo.get_content_segment_text_by_id(segment_id), "Segment corrige")

    def test_script_slide_deck_helpers_use_repository_storage(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            ALTER TABLE platform_config ADD COLUMN source_module_id INTEGER;

            INSERT INTO formation_pipeline_jobs
                (id, platform_id, tp_name, total_hours, nb_days, status)
            VALUES
                (999, 7, 'TP Slides', 7, 1, 'completed');

            INSERT INTO formation_modules
                (id, source_pipeline_job_id, source_platform_id, tp_name, rncp_code, version, status)
            VALUES
                (77, 888, 42, 'Module Slides', 'RNCP777', 'v1', 'validated');

            UPDATE platform_config
            SET source_formation_id = 999, source_module_id = 77
            WHERE id = 7;

            INSERT INTO cours_folders (id, platform_id, name, position, formation_job_id)
            VALUES (140, 7, 'Jour 1 - Slides', 0, 999);
            """
        )
        conn.commit()
        conn.close()

        repo.reset_and_upsert_content_generation_job(
            folder_id=140,
            platform_id=7,
            program_text="Programme",
            program_title="TP Slides",
            sub_parts_json='["Cours 1"]',
            from_scratch=True,
            module_contents_json='{}',
        )
        job = cgs.get_job_from_db(140)
        cgs._save_segment_db(job["id"], 0, "Cours 1", 1, "Segment slide complet")

        source = repo.get_script_slide_source_row(140)
        self.assertEqual(source["folder_name"], "Jour 1 - Slides")
        self.assertEqual(source["content_job_id"], job["id"])

        formation_job = repo.get_formation_pipeline_job_identity(999)
        self.assertEqual(formation_job["tp_name"], "TP Slides")

        refs = repo.get_platform_slide_source_refs(7)
        self.assertEqual(refs["source_formation_id"], 999)
        self.assertEqual(refs["source_pipeline_job_id"], 888)
        self.assertEqual(refs["source_platform_id"], 42)

        repo.ensure_script_slide_decks_table()
        deck_id = repo.insert_script_slide_deck(
            folder_id=140,
            content_job_id=job["id"],
            formation_job_id=999,
            platform_id=7,
            generation_mode="script",
            pace="normal",
            max_slides=12,
            model="model-slides",
            slides_json='[{"slide_id":"s1"}]',
            timeline_json='[{"slide_index":0}]',
            stats_json='{"generation_mode":"script"}',
            pipeline_debug_json='{"ok":true}',
        )

        latest = repo.get_latest_script_slide_deck_row(folder_id=140, content_job_id=job["id"])
        self.assertEqual(latest["id"], deck_id)
        self.assertEqual(latest["model"], "model-slides")

        lookup_rows = repo.list_script_slide_deck_rows_for_audio_lookup(
            platform_ids=[7],
            job_ids=[999],
            limit=10,
        )
        self.assertEqual([row["id"] for row in lookup_rows], [deck_id])

        repo.update_script_slide_deck_audio_sync_row(
            deck_id=deck_id,
            slides_json='[{"slide_id":"s1","audio_filename":"cours_1.mp3"}]',
            timeline_json='[{"slide_index":0,"audio_filename":"cours_1.mp3"}]',
            stats_json='{"audio_sync":{"enabled":true}}',
            pipeline_debug_json='{"audio_sync":{"mode":"test"}}',
            audio_sync_json='{"timings":[{"audio_filename":"cours_1.mp3"}]}',
        )
        updated = repo.get_script_slide_deck_row(deck_id)
        self.assertIn("cours_1.mp3", updated["slides_json"])
        self.assertIn("timings", updated["audio_sync_json"])


if __name__ == "__main__":
    unittest.main()
