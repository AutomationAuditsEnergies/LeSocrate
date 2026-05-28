import json
import os
import sqlite3
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
            total_words INTEGER DEFAULT 0
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
    def _run_next_step(self, db_path, job):
        with patch.object(fr, "get_job", return_value=job), patch.object(
            fps,
            "get_expected_course_folders",
            return_value={"folder_ids": [10], "folders": []},
        ), patch("database.db.get_db_connection", side_effect=lambda: _connect(db_path)), patch.object(
            cgs,
            "_current_humanization_review_signature",
            return_value="human-sig",
        ), patch.object(
            cgs,
            "_current_compliance_review_signature",
            return_value="review-sig",
        ):
            return fr._determine_next_ap_step(99)

    def test_humanization_review_runs_before_compliance_review(self):
        db_path = _make_review_db(humanized=False, reviewed=False)
        try:
            self.assertEqual(self._run_next_step(db_path, _job()), "humanization_review")
        finally:
            os.unlink(db_path)

    def test_post_review_docs_runs_after_both_reviews(self):
        db_path = _make_review_db(humanized=True, reviewed=True)
        try:
            self.assertEqual(self._run_next_step(db_path, _job()), "post_review_docs")
        finally:
            os.unlink(db_path)

    def test_audio_gate_requires_humanization_and_compliance(self):
        db_path = _make_review_db(humanized=True, reviewed=False)
        try:
            with patch("database.db.get_db_connection", side_effect=lambda: _connect(db_path)), patch.object(
                cgs,
                "_current_humanization_review_signature",
                return_value="human-sig",
            ), patch.object(
                cgs,
                "_current_compliance_review_signature",
                return_value="review-sig",
            ):
                ok, detail = fr._folder_text_reviews_ready(99, 10)

            self.assertFalse(ok)
            self.assertEqual(detail["humanized_current"], 18)
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
                "humanization_review",
            )
        finally:
            os.unlink(db_path)


if __name__ == "__main__":
    unittest.main()
