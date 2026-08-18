import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from repositories import ai_voice_repository as repository


class AIVoiceRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE ai_voices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                center_account_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                fish_reference_id TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                consent_statement TEXT NOT NULL,
                consent_recording_sha256 TEXT,
                consent_recording_duration_sec REAL,
                sample_sha256 TEXT,
                sample_duration_sec REAL,
                measured_wpm REAL,
                playback_speed REAL,
                language TEXT,
                fish_state TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE platform_config (
                id INTEGER PRIMARY KEY,
                center_account_id INTEGER NOT NULL,
                ai_voice_id INTEGER,
                updated_at TEXT
            );
            INSERT INTO platform_config (id, center_account_id) VALUES (7, 42);
            """
        )

        @contextmanager
        def fake_connection():
            yield self.connection, False

        self.connection_patch = patch.object(repository, "_connection", fake_connection)
        self.connection_patch.start()

    def tearDown(self):
        self.connection_patch.stop()
        self.connection.close()

    def test_voice_is_tenant_scoped_and_assignable(self):
        voice = repository.create_voice(
            42,
            name="Voix de Sophie",
            fish_reference_id="fish-ref-42",
            source="clone",
            consent_statement="consentement",
        )
        self.assertEqual(voice["center_account_id"], 42)
        self.assertIsNone(repository.get_voice(99, voice["id"]))

        calibrated = repository.update_calibration(
            42,
            voice["id"],
            measured_wpm=148.5,
            playback_speed=1.1,
        )
        self.assertEqual(calibrated["measured_wpm"], 148.5)
        self.assertTrue(repository.assign_voice_to_platform(42, 7, voice["id"]))
        settings = repository.get_platform_voice_settings(7)
        self.assertEqual(settings["fish_reference_id"], "fish-ref-42")
        self.assertEqual(settings["playback_speed"], 1.1)


if __name__ == "__main__":
    unittest.main()
