import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from azure.core.exceptions import ResourceExistsError

from services import audio_publish_service as service
from services.audio_publish_service import ensure_platform_audio_storage


class AudioPublishStorageTest(unittest.TestCase):
    def test_dynamic_platform_containers_are_provisioned_idempotently(self):
        audio = Mock()
        archive = Mock()
        audio.create_container.side_effect = ResourceExistsError("already exists")
        archive.create_container.side_effect = ResourceExistsError("already exists")
        blob_service = Mock()
        blob_service.get_container_client.side_effect = lambda name: {
            "formationaudio-p5": audio,
            "formationaudio-p5-archives": archive,
        }[name]

        with patch.dict(
            "os.environ",
            {"AZURE_AUDIO_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true"},
            clear=False,
        ):
            result = ensure_platform_audio_storage(5, blob_service_client=blob_service)

        self.assertEqual(result["audio_container"], "formationaudio-p5")
        self.assertEqual(result["archive_container"], "formationaudio-p5-archives")
        self.assertEqual(result["created"], {"audio": False, "archive": False})
        audio.create_container.assert_called_once_with()
        archive.create_container.assert_called_once_with()

    def test_scheduled_publish_uses_an_occurrence_prefix_without_archiving_another_day(self):
        source_blob = SimpleNamespace(
            name="platform-5/folder-55/playlist/cours_9h00_9h45.mp3"
        )
        source_client = Mock()
        source_client.download_blob.return_value.readall.return_value = b"mp3"
        source_container = Mock()
        source_container.list_blobs.return_value = [source_blob]
        source_container.get_blob_client.return_value = source_client

        destination_blob = Mock()
        destination_container = Mock()
        destination_container.get_blob_client.return_value = destination_blob
        tts_service = Mock()
        tts_service.get_container_client.return_value = source_container
        audio_service = Mock()
        audio_service.get_container_client.return_value = destination_container

        with patch.dict(
            service.os.environ,
            {
                "AZURE_TTS_STORAGE_CONNECTION_STRING": "tts",
                "AZURE_AUDIO_STORAGE_CONNECTION_STRING": "audio",
            },
            clear=False,
        ), patch.object(
            service.BlobServiceClient,
            "from_connection_string",
            side_effect=[tts_service, audio_service],
        ), patch.object(
            service,
            "ensure_platform_audio_storage",
        ), patch.object(
            service,
            "archive_public_platform_audios",
        ) as archive:
            result = service.publish_playlist_audio_to_platform(
                5,
                55,
                source_platform_id=5,
                archive_existing=True,
                destination_prefix="course-sessions/501",
            )

        destination_container.get_blob_client.assert_called_once_with(
            "course-sessions/501/cours_9h00_9h45.mp3"
        )
        destination_blob.upload_blob.assert_called_once()
        archive.assert_not_called()
        self.assertEqual(result["published"], ["cours_9h00_9h45.mp3"])
        self.assertEqual(
            result["published_blob_names"],
            ["course-sessions/501/cours_9h00_9h45.mp3"],
        )

    def test_legacy_archive_never_deletes_occurrence_snapshots(self):
        source_container = Mock()
        source_container.list_blobs.return_value = [
            SimpleNamespace(name="course-sessions/501/cours_9h00_9h45.mp3")
        ]
        archive_container = Mock()
        blob_service = Mock()
        blob_service.get_container_client.side_effect = lambda name: {
            "formationaudio-p5": source_container,
            "formationaudio-p5-archives": archive_container,
        }[name]

        result = service.archive_public_platform_audios(
            5,
            blob_service_client=blob_service,
        )

        self.assertEqual(result["archived"], 0)
        source_container.delete_blob.assert_not_called()


if __name__ == "__main__":
    unittest.main()
