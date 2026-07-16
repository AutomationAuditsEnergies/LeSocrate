import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from services import claude_code_mission_service as ccms


def _connect(path):
    return sqlite3.connect(path)


def _make_db():
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.executescript(
        """
        CREATE TABLE formation_pipeline_jobs (
            id INTEGER PRIMARY KEY,
            platform_id INTEGER NOT NULL
        );
        CREATE TABLE cours_folders (
            id INTEGER PRIMARY KEY,
            platform_id INTEGER NOT NULL,
            formation_job_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            position INTEGER NOT NULL
        );
        CREATE TABLE content_generation_jobs (
            id INTEGER PRIMARY KEY,
            folder_id INTEGER NOT NULL
        );
        CREATE TABLE content_generation_segments (
            id INTEGER PRIMARY KEY,
            job_id INTEGER NOT NULL,
            sub_part_index INTEGER NOT NULL,
            passe INTEGER NOT NULL,
            status TEXT NOT NULL,
            text_content TEXT NOT NULL,
            word_count INTEGER DEFAULT 0,
            dirty INTEGER DEFAULT 0,
            reviewed INTEGER DEFAULT 0,
            review_error TEXT,
            review_signature TEXT,
            humanized INTEGER DEFAULT 0,
            humanization_error TEXT,
            humanization_signature TEXT
        );
        INSERT INTO formation_pipeline_jobs (id, platform_id) VALUES (9, 1);
        INSERT INTO cours_folders (id, platform_id, formation_job_id, name, position)
        VALUES (10, 1, 9, 'Jour 1', 0);
        INSERT INTO content_generation_jobs (id, folder_id) VALUES (20, 10);
        """
    )
    conn.commit()
    conn.close()
    return tmp.name


def _humanization_config():
    return {
        "step_key": "humanization_review",
        "review_kind": "humanization",
        "review_label": "Humanisation",
        "reviewed_column": "humanized",
        "error_column": "humanization_error",
        "signature_column": "humanization_signature",
        "signature": "human-sig-current",
        "groups": [{
            "id": "humanisation_rythme",
            "label": "Humanisation et rythme pédagogique",
            "rules": [101, 102],
            "description": "test",
        }],
        "invalidate_compliance_on_change": True,
        "report_source": "humanization_claude_code_aggregate",
    }


class ClaudeCodeHumanizationTest(unittest.TestCase):
    def test_humanization_lister_uses_humanization_signature(self):
        db_path = _make_db()
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                INSERT INTO content_generation_segments
                    (id, job_id, sub_part_index, passe, status, text_content,
                     word_count, humanized, humanization_signature)
                VALUES
                    (1, 20, 0, 1, 'completed', 'Intro trop directe.', 3, 0, NULL),
                    (2, 20, 0, 2, 'completed', 'Déjà validé.', 2, 1, 'human-sig-current')
                """
            )
            conn.commit()
            conn.close()

            with patch.object(ccms, "get_db_connection", side_effect=lambda: _connect(db_path)), patch.object(
                ccms, "_review_step_config", return_value=_humanization_config()
            ):
                chunks = ccms._list_humanization_chunks({"id": 9})

            self.assertEqual(len(chunks), 1)
            self.assertEqual(chunks[0]["review_kind"], "humanization")
            self.assertEqual(chunks[0]["review_signature"], "human-sig-current")
            self.assertEqual([s["segment_id"] for s in chunks[0]["segments"]], [1])
        finally:
            os.unlink(db_path)

    def test_humanization_import_invalidates_compliance_when_text_changes(self):
        db_path = _make_db()
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                INSERT INTO content_generation_segments
                    (id, job_id, sub_part_index, passe, status, text_content,
                     word_count, dirty, reviewed, review_signature)
                VALUES
                    (1, 20, 0, 1, 'completed',
                     'Bonjour à tous. On entre maintenant dans le vif du sujet.',
                     10, 0, 1, 'compliance-current')
                """
            )
            conn.commit()
            conn.close()

            chunk = {
                "id": "day_1_review_humanisation_rythme",
                "folder_id": 10,
                "folder_name": "Jour 1",
                "review_step_key": "humanization_review",
                "review_kind": "humanization",
                "review_label": "Humanisation",
                "segments": [{
                    "segment_id": 1,
                    "sub_idx": 0,
                    "passe": 1,
                    "text": "Bonjour à tous. On entre maintenant dans le vif du sujet.",
                }],
            }
            output = json.dumps({
                "reviews": [{
                    "segment_id": 1,
                    "patches": [{
                        "original": "Bonjour à tous. On entre maintenant dans le vif du sujet.",
                        "replacement": "Bonjour à tous, j'espère que vous allez bien. [pause] On va avancer tranquillement.",
                        "rule_violated": "#101",
                        "reason": "Début trop brusque.",
                    }],
                }],
            })

            with patch.object(ccms, "get_db_connection", side_effect=lambda: _connect(db_path)), patch.object(
                ccms, "_review_step_config", return_value=_humanization_config()
            ):
                result = ccms._import_review_chunk(9, chunk, output, "claude_code_sonnet")

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                """
                SELECT text_content, dirty, humanized, humanization_signature,
                       reviewed, review_signature
                FROM content_generation_segments WHERE id = 1
                """
            ).fetchone()
            conn.close()

            self.assertEqual(result["review_kind"], "humanization")
            self.assertEqual(result["patches_applied"], 1)
            self.assertIn("[pause]", row[0])
            self.assertEqual(row[1], 1)
            self.assertEqual(row[2], 1)
            self.assertEqual(row[3], "human-sig-current")
            self.assertEqual(row[4], 0)
            self.assertIsNone(row[5])
        finally:
            os.unlink(db_path)


if __name__ == "__main__":
    unittest.main()
