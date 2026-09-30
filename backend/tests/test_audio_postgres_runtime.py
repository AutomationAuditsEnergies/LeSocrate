import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch

from services import audio_service
from services import content_generation_service


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

    def test_hybrid_pipeline_postgres_never_opens_sqlite(self):
        config = {
            "id": 16,
            "playlist_mode": "ete",
            "audio_base_url": "https://cdn.example.test/tenant-16",
            "audio_container": "tenant-16",
        }
        with patch.object(audio_service, "DATABASE_BACKEND", "hybrid"), patch.object(
            audio_service, "PIPELINE_DATABASE_BACKEND", "postgres"
        ), patch(
            "repositories.core_repository.get_platform_audio_config",
            return_value=config,
        ), patch(
            "database.db.get_db_connection",
            side_effect=AssertionError("SQLite must not be opened"),
        ):
            playlist = audio_service.get_playlist(16)

        self.assertTrue(playlist)
        self.assertTrue(all(
            item["filename"].startswith("https://cdn.example.test/tenant-16/")
            for item in playlist
        ))

    def test_pipeline_generation_never_falls_back_when_postgres_config_fails(self):
        with patch.object(
            content_generation_service, "PIPELINE_DATABASE_BACKEND", "postgres"
        ), patch(
            "services.audio_service.get_playlist",
            side_effect=LookupError("missing platform"),
        ), patch.dict(
            sys.modules,
            {
                "services.playlist_tts_service": SimpleNamespace(
                    PLAYLIST_SPEC=[("cours.mp3", 60, "cours", 1)]
                )
            },
        ):
            with self.assertRaisesRegex(
                RuntimeError, "Configuration playlist PostgreSQL indisponible"
            ):
                content_generation_service._playlist_items_for_platform(404)


if __name__ == "__main__":
    unittest.main()
