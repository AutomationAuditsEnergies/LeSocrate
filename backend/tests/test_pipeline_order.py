import json
import os
import sqlite3
import types
import sys
import tempfile
import unittest
from unittest.mock import patch

from routes import formation_routes as fr
from services import content_generation_service as cgs
from services import formation_pipeline_service as fps


def _connect(path):
    return sqlite3.connect(path)


def _make_review_db(*, humanized: bool, reviewed: bool, segment_count: int = 18):
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
            humanized INTEGER DEFAULT 0,
            humanization_error TEXT,
            humanization_signature TEXT,
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
                (id, job_id, status, humanized, humanization_signature,
                 reviewed, review_signature)
            VALUES (?, 20, 'completed', ?, ?, ?, ?)
            """,
            (
                idx + 1,
                1 if humanized else 0,
                "human-sig" if humanized else None,
                1 if reviewed else 0,
                "review-sig" if reviewed else None,
            ),
        )
    conn.commit()
    conn.close()
    return tmp.name


def _job(**overrides):
    data = {
        "id": 99,
        "status": "text_ready",
        "reac_text": "reac",
        "global_program": "global",
        "daily_programs": "[{\"day_number\": 1}]",
        "nb_days": 1,
        "auto_pilot_skip_vs": 1,
        "auto_pilot_volume_done": 1,
        "auto_pilot_post_review_docs_done": 0,
        "auto_pilot_generate_audio": 0,
    }
    data.update(overrides)
    return data


class PipelineOrderTest(unittest.TestCase):
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

    def test_auto_pilot_heartbeat_interrupts_runner_after_lock_loss(self):
        import eventlet

        captured = {}

        class FakeHeartbeat:
            def __init__(self):
                self.killed = False

            def kill(self):
                self.killed = True

        heartbeat = FakeHeartbeat()

        def fake_spawn(callback):
            captured["heartbeat"] = callback
            return heartbeat

        def execute_step(*_args):
            captured["heartbeat"]()
            self.fail("le runner aurait dû être interrompu par la perte du lock")

        def inject_failure(_runner, exc):
            raise exc

        with (
            patch.object(eventlet, "spawn", side_effect=fake_spawn),
            patch.object(eventlet, "sleep", return_value=None),
            patch.object(eventlet, "getcurrent", return_value=object()),
            patch.object(eventlet.greenthread, "kill", side_effect=inject_failure),
            patch.object(fr, "_new_ap_lock_owner", return_value="worker-a"),
            patch.object(fr, "_acquire_ap_lock", return_value=True),
            patch.object(fr, "_refresh_ap_lock", return_value=False),
            patch.object(fr, "_release_ap_lock") as release,
            patch.object(fr, "get_job", return_value=_job(auto_pilot_enabled=1)),
            patch.object(fr, "_determine_next_ap_step", return_value="content"),
            patch.object(fr, "_execute_ap_step", side_effect=execute_step),
            patch.object(fr, "update_job") as update,
            patch.object(fr, "_dispatch_auto_pilot_tick") as dispatch,
            patch("services.formation_observability_service.log_pipeline_event"),
        ):
            fr._tick_auto_pilot(99)

        self.assertTrue(heartbeat.killed)
        release.assert_called_once_with(99, "worker-a")
        dispatch.assert_not_called()
        self.assertFalse(any(
            call.kwargs.get("auto_pilot_error")
            for call in update.call_args_list
        ))

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
        db_path = _make_review_db(humanized=False, reviewed=False)
        try:
            self.assertEqual(self._run_next_step(db_path, _job()), "review")
        finally:
            os.unlink(db_path)

    def test_post_review_docs_runs_after_local_compliance(self):
        db_path = _make_review_db(humanized=True, reviewed=True)
        try:
            self.assertEqual(self._run_next_step(db_path, _job()), "post_review_docs")
        finally:
            os.unlink(db_path)

    def test_audio_gate_requires_local_compliance(self):
        db_path = _make_review_db(humanized=True, reviewed=False)
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
        db_path = _make_review_db(humanized=False, reviewed=False, segment_count=7)
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

        class FakeGreenlet:
            def __init__(self, result):
                self._result = result

            def wait(self):
                return self._result

        class FakeGreenPool:
            def __init__(self, size):
                captured["pool_size"] = size

            def spawn(self, fn, task):
                captured["tasks"].append(task)
                return FakeGreenlet(fn(task))

        fake_eventlet = types.SimpleNamespace(GreenPool=FakeGreenPool, sleep=lambda _seconds: None)

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
            auto_pilot_use_cc=0,
            auto_pilot_generate_audio=0,
        )

        with patch.dict(sys.modules, {"eventlet": fake_eventlet}), patch.object(
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
