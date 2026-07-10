import unittest
from unittest.mock import patch

from services import audio_service


class AudioPostgresRuntimeTest(unittest.TestCase):
    def test_playlist_reads_postgres_without_opening_sqlite(self):
        config = {
            "id": 12,
            "playlist_mode": "ete",
            "audio_base_url": "https://cdn.example.test/tenant-12",
            "audio_container": "tenant-12",
        }
        with patch.object(audio_service, "DATABASE_BACKEND", "postgres"), patch(
            "repositories.core_repository.get_platform_audio_config",
            return_value=config,
        ), patch(
            "database.db.get_db_connection",
            side_effect=AssertionError("SQLite must not be opened"),
        ):
            playlist = audio_service.get_playlist(12)

        self.assertTrue(playlist)
        self.assertTrue(all(
            item["filename"].startswith("https://cdn.example.test/tenant-12/")
            for item in playlist
        ))

    def test_missing_postgres_platform_never_returns_shared_default_playlist(self):
        with patch.object(audio_service, "DATABASE_BACKEND", "postgres"), patch(
            "repositories.core_repository.get_platform_audio_config",
            return_value=None,
        ), patch(
            "database.db.get_db_connection",
            side_effect=AssertionError("SQLite must not be opened"),
        ):
            with self.assertRaisesRegex(LookupError, "Plateforme 404"):
                audio_service.get_playlist(404)


if __name__ == "__main__":
    unittest.main()
