import json
import inspect
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from routes import formation_routes as fr
from services import content_generation_service as cgs
from services import formation_pipeline_service as fps
from utils.deepseek_client import DeepSeekAPIError, DeepSeekRateLimitError


def _connect(path):
    return sqlite3.connect(path)


def _make_review_db(*, reviewed: bool, segment_count: int = 18):
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.executescript(
        """
        CREATE TABLE cours_folders (
            id INTEGER PRIMARY KEY,
            formation_job_id INTEGER NOT NULL
        );
        CREATE TABLE content_generation_jobs (
            id INTEGER PRIMARY KEY,
            folder_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            total_words INTEGER DEFAULT 0,
            current_sub_part INTEGER DEFAULT 0,
            current_passe INTEGER DEFAULT 1,
            error_message TEXT
        );
        CREATE TABLE content_generation_segments (
            id INTEGER PRIMARY KEY,
            job_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            dirty INTEGER DEFAULT 0,
            reviewed INTEGER DEFAULT 0,
            review_error TEXT,
            review_signature TEXT
        );
        INSERT INTO cours_folders (id, formation_job_id) VALUES (10, 99);
        INSERT INTO content_generation_jobs (id, folder_id, status, total_words)
        VALUES (20, 10, 'completed', 5000);
        """
    )
    for idx in range(segment_count):
        conn.execute(
            """
            INSERT INTO content_generation_segments
                (id, job_id, status, reviewed, review_signature)
            VALUES (?, 20, 'completed', ?, ?)
            """,
            (
                idx + 1,
                1 if reviewed else 0,
                "review-sig" if reviewed else None,
            ),
        )
    conn.commit()
    conn.close()
    return tmp.name


def _job(**overrides):
    completed_day = {
        "day_number": 1,
        "sub_parts": [
            {
                "name": f"Cours {index}",
                "module_content": f"Contenu pédagogique {index}",
            }
            for index in range(1, 8)
        ],
    }
    data = {
        "id": 99,
        "status": "text_ready",
        "reac_text": "reac",
        "global_program": "global",
        "daily_programs": json.dumps([completed_day]),
        "daily_programs_validated": 1,
        "nb_days": 1,
        "auto_pilot_post_review_docs_done": 0,
    }
    data.update(overrides)
    return data


class PipelineOrderTest(unittest.TestCase):
    def test_parallel_step_failure_preserves_deterministic_provider_cause(self):
        transient = RuntimeError("timeout")
        deterministic = DeepSeekAPIError(
            401,
            "authentication_error",
            "clé invalide",
        )

        with self.assertRaisesRegex(RuntimeError, "étape échouée") as raised:
            fr._raise_pipeline_batch_failure(
                "étape échouée",
                [
                    {"exception": transient},
                    {"exception": deterministic},
                ],
            )

        self.assertIs(raised.exception.__cause__, deterministic)

    def test_parallel_step_failure_preserves_provider_retry_after(self):
        rate_limit = DeepSeekRateLimitError(180)

        with self.assertRaisesRegex(RuntimeError, "étape échouée") as raised:
            fr._raise_pipeline_batch_failure(
                "étape échouée",
                [
                    {"exception": RuntimeError("autre erreur")},
                    {"exception": rate_limit},
                ],
            )

        self.assertIs(raised.exception.__cause__, rate_limit)

    def test_scheduled_audio_is_not_completed_after_partial_publication(self):
        source = inspect.getsource(fr.start_folder_audio_generation)
        publication_guard = source.index("if publish_errors or missing_files")
        completion = source.index("complete_audio_generation_session")
        self.assertLess(publication_guard, completion)

    def test_reused_schedule_publishes_source_audio_to_target_platform(self):
        source = inspect.getsource(fr.start_folder_audio_generation)
        self.assertIn("publish_platform_id", source)
        self.assertIn('source_platform_id=int(job["platform_id"])', source)

    def test_scheduled_capacity_is_bounded_per_process(self):
        previous_capacity = fr._SCHEDULED_AUDIO_CAPACITY
        previous_limit = fr._SCHEDULED_AUDIO_CAPACITY_LIMIT
        try:
            fr._SCHEDULED_AUDIO_CAPACITY = None
            fr._SCHEDULED_AUDIO_CAPACITY_LIMIT = None
            with patch.dict(os.environ, {"SCHEDULED_AUDIO_MAX_CONCURRENCY": "1"}):
                self.assertTrue(fr._try_acquire_scheduled_audio_capacity())
                self.assertFalse(fr._try_acquire_scheduled_audio_capacity())
                fr._release_scheduled_audio_capacity()
                self.assertTrue(fr._try_acquire_scheduled_audio_capacity())
                fr._release_scheduled_audio_capacity()
        finally:
            fr._SCHEDULED_AUDIO_CAPACITY = previous_capacity
            fr._SCHEDULED_AUDIO_CAPACITY_LIMIT = previous_limit

    def test_scheduled_module_is_validated_only_when_all_days_are_complete(self):
        pending = {
            "ready": False,
            "required_session_count": 2,
            "session_count": 2,
            "completed_count": 1,
        }
        with (
            patch.object(fr, "get_job", return_value={"platform_id": 12, "nb_days": 2}),
            patch(
                "repositories.course_schedule_repository.get_scheduled_audio_completion_readiness",
                return_value=pending,
            ),
            patch.object(fr, "_finalize_audio_ready_state") as finalize,
            patch.object(fr, "update_job") as update,
        ):
            result = fr._finalize_scheduled_audio_module_if_ready(99, "fish_audio")

        self.assertFalse(result["finalized"])
        finalize.assert_not_called()
        update.assert_not_called()

        ready = {**pending, "ready": True, "completed_count": 2}
        with (
            patch.object(fr, "get_job", return_value={"platform_id": 12, "nb_days": 2}),
            patch(
                "repositories.course_schedule_repository.get_scheduled_audio_completion_readiness",
                return_value=ready,
            ),
            patch.object(fr, "_finalize_audio_ready_state", return_value={"module_status": "validated"}) as finalize,
            patch.object(fr, "update_job") as update,
        ):
            result = fr._finalize_scheduled_audio_module_if_ready(99, "fish_audio")

        self.assertTrue(result["finalized"])
        finalize.assert_called_once_with(99, "fish_audio")
        update.assert_called_once_with(99, status="audio_completed", error_message=None)

    def test_scheduled_audio_progress_fails_closed_when_claim_is_lost(self):
        state = {"error": None}
        callback = fr._make_audio_progress_logger(
            99,
            10,
            "gtts",
            schedule_session_id=7,
            schedule_claim_started_at="claim-token",
            ownership_state=state,
        )
        with patch(
            "services.formation_observability_service.log_pipeline_event",
        ), patch(
            "repositories.course_schedule_repository.touch_audio_generation_session",
            return_value=False,
        ):
            with self.assertRaisesRegex(fr._ScheduledAudioLeaseLost, "Lock audio perdu"):
                callback(1, 21, "progress")

        self.assertIn("séance 7", state["error"])

    def test_content_day_workers_default_is_bounded(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(fr._formation_content_day_workers(), 3)

    def test_content_day_workers_allows_lower_override(self):
        with patch.dict(os.environ, {"FORMATION_CONTENT_DAY_WORKERS": "6"}):
            self.assertEqual(fr._formation_content_day_workers(), 6)

    def test_content_day_workers_caps_at_configured_safety_limit(self):
        with patch.dict(os.environ, {"FORMATION_CONTENT_DAY_WORKERS": "200"}):
            self.assertEqual(fr._formation_content_day_workers(), 8)

    def _run_next_step(self, db_path, job):
        with patch.object(fr, "get_job", return_value=job), patch.object(
            fps,
            "get_expected_course_folders",
            return_value={"folder_ids": [10], "folders": []},
        ), patch("database.db.get_db_connection", side_effect=lambda: _connect(db_path)), patch.object(
            cgs,
            "_current_compliance_review_signature",
            return_value="review-sig",
        ), patch("repositories.pipeline_repository.get_db_connection", side_effect=lambda: _connect(db_path)):
            return fr._determine_next_ap_step(99)

    def test_local_compliance_runs_after_content(self):
        db_path = _make_review_db(reviewed=False)
        try:
            self.assertEqual(self._run_next_step(db_path, _job()), "review")
        finally:
            os.unlink(db_path)

    def test_post_review_docs_runs_after_local_compliance(self):
        db_path = _make_review_db(reviewed=True)
        try:
            self.assertEqual(self._run_next_step(db_path, _job()), "post_review_docs")
        finally:
            os.unlink(db_path)

    def test_post_review_documents_do_not_mark_teacher_ready_before_slides(self):
        job = _job(platform_id=1)
        with patch.object(
            fps,
            "get_expected_course_folders",
            return_value={"folder_ids": [10]},
        ), patch(
            "repositories.pipeline_repository.list_completed_content_jobs_for_folders",
            return_value=[{"folder_id": 10, "content_job_id": 20}],
        ), patch.object(
            cgs,
            "assert_course_day_word_budget",
            return_value={"budget": {}},
        ), patch.object(
            cgs,
            "_assemble_and_upload",
            return_value=(5000, "jour-1.docx"),
        ), patch.object(
            cgs,
            "_update_job_db",
        ), patch.object(
            fr,
            "_delete_slide_deck_for_resume",
            return_value=0,
        ), patch.object(
            fr,
            "_finalize_text_ready_state",
        ) as finalize, patch.object(
            fr,
            "update_job",
        ) as update:
            fr._execute_ap_step(99, "post_review_docs", job)

        finalize.assert_not_called()
        update.assert_called_once_with(
            99,
            status="tts_launched",
            auto_pilot_post_review_docs_done=1,
        )

    def test_teacher_finalization_is_scheduled_after_every_slide_deck_exists(self):
        job = _job(
            platform_id=1,
            status="tts_launched",
            auto_pilot_post_review_docs_done=1,
        )
        with patch.object(fr, "get_job", return_value=job), patch.object(
            fps,
            "get_expected_course_folders",
            return_value={"folder_ids": [10]},
        ), patch(
            "repositories.pipeline_repository.list_content_completion_rows_for_folders",
            return_value=[{
                "folder_id": 10,
                "status": "completed",
                "total_words": 5000,
                "completed_segments": 7,
            }],
        ), patch(
            "repositories.pipeline_repository.count_segments_pending_review_for_folders",
            return_value=0,
        ), patch(
            "repositories.pipeline_repository.list_completed_content_jobs_for_folders",
            return_value=[{"folder_id": 10, "content_job_id": 20}],
        ), patch(
            "repositories.pipeline_repository.get_latest_script_slide_deck_row",
            return_value={"slides_json": '[{"title": "Introduction"}]'},
        ), patch.object(
            cgs,
            "_current_compliance_review_signature",
            return_value="review-sig",
        ), patch.object(
            fr,
            "_finalize_text_ready_state",
        ) as finalize, patch.object(
            fr,
            "update_job",
        ) as update:
            next_step = fr._determine_next_ap_step(99)

        self.assertEqual(next_step, "finalize_text")
        finalize.assert_not_called()
        update.assert_not_called()

    def test_text_finalization_failure_is_retried_instead_of_reporting_ready(self):
        job = _job(
            platform_id=1,
            status="tts_launched",
            auto_pilot_post_review_docs_done=1,
        )
        with patch.object(
            fr,
            "_finalize_text_ready_state",
            side_effect=RuntimeError("module envelope unavailable"),
        ), patch.object(fr, "update_job") as update:
            with self.assertRaisesRegex(RuntimeError, "module envelope"):
                fr._execute_ap_step(99, "finalize_text", job)

        update.assert_not_called()

    def test_finalize_text_step_marks_the_teacher_ready(self):
        job = _job(
            platform_id=1,
            status="tts_launched",
            auto_pilot_post_review_docs_done=1,
        )
        with patch.object(
            fr,
            "_finalize_text_ready_state",
            return_value={"module_status": "draft"},
        ) as finalize, patch(
            "services.daily_course_pdf_service.publish_pipeline_course_pdfs",
            return_value=[{"session_id": 501}],
        ) as publish_pdfs, patch.object(fr, "update_job") as update:
            fr._execute_ap_step(99, "finalize_text", job)

        finalize.assert_called_once_with(99)
        publish_pdfs.assert_called_once_with(job_id=99, platform_id=1)
        update.assert_called_once_with(99, status="text_ready", error_message=None)

    def test_next_step_calculation_has_no_business_writes(self):
        source = inspect.getsource(fr._determine_next_ap_step)

        self.assertNotIn("update_job(", source)
        self.assertNotIn("_finalize_text_ready_state(", source)
        self.assertNotIn("_finalize_audio_ready_state(", source)

    def test_partial_knowledge_base_is_resumed_instead_of_skipped(self):
        job = _job(
            status="kb_building",
            global_program=None,
            daily_programs="[]",
        )
        with patch.object(fr, "get_job", return_value=job), patch(
            "services.knowledge_base_service.kb_stats",
            return_value={
                "total": 4,
                "completed": 1,
                "pending": 3,
                "error": 0,
            },
        ):
            self.assertEqual(fr._determine_next_ap_step(99), "kb")

    def test_kb_and_global_steps_run_inside_the_durable_work_item(self):
        job = _job(
            platform_id=1,
            status="reac_ready",
            global_program=None,
            daily_programs="[]",
        )
        checkpoints = []

        def checkpoint():
            checkpoints.append("checked")

        with patch.object(fr, "build_knowledge_base") as build_kb:
            fr._execute_ap_step(99, "kb", job, checkpoint=checkpoint)

        build_kb.assert_called_once_with(
            99,
            model="deepseek-v4-pro",
            checkpoint=checkpoint,
        )

        with patch.object(fr, "generate_global_program") as generate_global, patch.object(
            fr,
            "update_job",
        ) as update:
            fr._execute_ap_step(99, "global", job, checkpoint=checkpoint)

        generate_global.assert_called_once_with(
            99,
            model="deepseek-v4-pro",
            checkpoint=checkpoint,
        )
        update.assert_called_once_with(
            99,
            global_program_validated=1,
            status="global_validated",
        )
        self.assertEqual(checkpoints, [])

    def test_daily_step_is_not_validated_when_generation_fails(self):
        job = _job(
            platform_id=1,
            status="global_validated",
            daily_programs="[]",
        )
        with patch.object(
            fr,
            "run_daily_split",
            side_effect=RuntimeError("Journée 1 impossible à générer correctement"),
        ), patch.object(fr, "update_job") as update:
            with self.assertRaisesRegex(
                RuntimeError,
                "Journée 1 impossible à générer correctement",
            ):
                fr._execute_ap_step(99, "daily", job)

        update.assert_not_called()

    def test_daily_step_delegates_checkpoint_and_validation_atomically(self):
        job = _job(
            platform_id=1,
            status="global_validated",
            daily_programs="[]",
        )

        def checkpoint():
            return None

        with patch.object(fr, "run_daily_split") as run_daily, patch.object(
            fr,
            "update_job",
        ) as update:
            fr._execute_ap_step(99, "daily", job, checkpoint=checkpoint)

        run_daily.assert_called_once_with(
            99,
            model="deepseek-v4-pro",
            checkpoint=checkpoint,
        )
        update.assert_not_called()

    def test_partial_or_unvalidated_daily_checkpoint_stays_on_daily_step(self):
        day_one = fps._normalize_day_audio_slots(
            {
                "day_number": 1,
                "sub_parts": [
                    {
                        "name": f"Cours {index}",
                        "module_content": f"Contenu {index}",
                    }
                    for index in range(1, 8)
                ],
            }
        )
        day_two = fps._normalize_day_audio_slots(
            {
                "day_number": 2,
                "sub_parts": [
                    {
                        "name": f"Cours {index}",
                        "module_content": f"Contenu {index}",
                    }
                    for index in range(1, 8)
                ],
            }
        )
        partial = _job(
            status="daily_splitting",
            nb_days=2,
            daily_programs=json.dumps([day_one]),
            daily_programs_validated=1,
        )
        complete_but_unvalidated = _job(
            status="daily_splitting",
            nb_days=2,
            daily_programs=json.dumps([day_one, day_two]),
            daily_programs_validated=0,
        )

        with patch.object(fr, "get_job", return_value=partial):
            self.assertEqual(fr._determine_next_ap_step(99), "daily")
        with patch.object(fr, "get_job", return_value=complete_but_unvalidated):
            self.assertEqual(fr._determine_next_ap_step(99), "daily")

    def test_audio_gate_requires_local_compliance(self):
        db_path = _make_review_db(reviewed=False)
        try:
            with patch("database.db.get_db_connection", side_effect=lambda: _connect(db_path)), patch.object(
                cgs,
                "_current_compliance_review_signature",
                return_value="review-sig",
            ), patch("repositories.pipeline_repository.get_db_connection", side_effect=lambda: _connect(db_path)):
                ok, detail = fr._folder_text_reviews_ready(99, 10)

            self.assertFalse(ok)
            self.assertEqual(detail["reviewed_current"], 0)
        finally:
            os.unlink(db_path)

    def test_structured_content_completion_uses_job_status_not_legacy_segment_count(self):
        db_path = _make_review_db(reviewed=False, segment_count=7)
        daily = [{
            "day_number": 1,
            "sub_parts": [{"name": f"Partie {idx}"} for idx in range(7)],
        }]
        try:
            self.assertEqual(
                self._run_next_step(db_path, _job(daily_programs=json.dumps(daily))),
                "review",
            )
        finally:
            os.unlink(db_path)

    def test_content_step_bulk_prepares_missing_jobs_before_parallel_launch(self):
        daily_programs = [
            {
                "day_number": day_number,
                "sub_parts": [{"name": f"Cours {day_number}"}],
            }
            for day_number in range(1, 53)
        ]
        folder_state = {
            "folders": [
                {
                    "expected_name": f"Jour {day_number}",
                    "folder_id": 100 + day_number,
                }
                for day_number in range(1, 53)
            ],
            "duplicates": [],
        }
        existing_content_rows = [
            {
                "folder_id": 100 + day_number,
                "content_job_id": 1000 + day_number,
                "status": "idle",
            }
            for day_number in range(1, 7)
        ]
        captured = {"pool_size": None, "tasks": [], "created_jobs": [], "run_calls": []}

        class FakeFuture:
            def __init__(self, result):
                self._result = result

            def result(self):
                return self._result

        class FakeThreadPoolExecutor:
            def __init__(self, max_workers, **_kwargs):
                captured["pool_size"] = max_workers

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def submit(self, fn, task):
                captured["tasks"].append(task)
                return FakeFuture(fn(task))

        def fake_reset_jobs(jobs):
            captured["created_jobs"].extend(jobs)

        def fake_run_content_generation(folder_id, model=None):
            captured["run_calls"].append((folder_id, model))

        job = _job(
            id=10,
            platform_id=14,
            tp_name="TP EC",
            daily_programs=json.dumps(daily_programs),
            auto_pilot_model="pro",
        )

        with patch.object(
            fr,
            "ThreadPoolExecutor",
            FakeThreadPoolExecutor,
        ), patch.object(
            fr,
            "update_job",
        ), patch.object(
            fr,
            "_formation_content_day_workers",
            return_value=52,
        ), patch.object(
            fr,
            "_normalize_day_audio_slots",
            side_effect=lambda day: day,
        ), patch.object(
            fr,
            "_format_slot_generation_source",
            side_effect=lambda slot: slot["name"],
        ), patch(
            "services.formation_pipeline_service.get_expected_course_folders",
            return_value=folder_state,
        ), patch(
            "services.formation_pipeline_service.repair_orphan_content_folders",
            return_value={"repaired": 0, "missing": 0, "folders": []},
        ), patch(
            "services.formation_pipeline_service.expected_course_folder_name",
            side_effect=lambda _day, fallback: f"Jour {fallback}",
        ), patch(
            "services.formation_pipeline_service._format_day_program_text",
            side_effect=lambda day, tp_name: f"{tp_name} jour {day['day_number']}",
        ), patch(
            "repositories.pipeline_repository.list_content_completion_rows_for_folders",
            return_value=existing_content_rows,
        ), patch(
            "repositories.pipeline_repository.reset_and_upsert_content_generation_jobs",
            side_effect=fake_reset_jobs,
        ), patch(
            "services.content_generation_service.run_content_generation",
            side_effect=fake_run_content_generation,
        ):
            fr._execute_ap_step(10, "content", job)

        self.assertEqual(len(captured["created_jobs"]), 46)
        self.assertEqual(captured["pool_size"], 52)
        self.assertEqual(len(captured["tasks"]), 52)
        self.assertEqual(len(captured["run_calls"]), 52)
        self.assertEqual(captured["tasks"][0], {"day_num": 1, "folder_id": 101})
        self.assertEqual(captured["tasks"][-1], {"day_num": 52, "folder_id": 152})


if __name__ == "__main__":
    unittest.main()
