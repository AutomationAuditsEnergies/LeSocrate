import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.audio_publish_service import publish_playlist_audio_to_platform


class AudioPublishServiceTests(unittest.TestCase):
    def test_publishes_only_mp3_files_to_the_platform_container(self):
        source_container = MagicMock()
        source_container.list_blobs.return_value = [
            SimpleNamespace(name="platform-1/folder-42/playlist/cours_9h00_9h45.mp3"),
            SimpleNamespace(name="platform-1/folder-42/playlist/audio_plan.json"),
        ]
        source_blob = source_container.get_blob_client.return_value
        source_blob.download_blob.return_value.readall.return_value = b"real mp3 bytes"

        destination_container = MagicMock()
        destination_blob = destination_container.get_blob_client.return_value

        tts_service = MagicMock()
        tts_service.get_container_client.return_value = source_container
        audio_service = MagicMock()
        audio_service.get_container_client.return_value = destination_container

        with (
            patch.dict(
                os.environ,
                {
                    "AZURE_TTS_STORAGE_CONNECTION_STRING": "tts-connection",
                    "AZURE_AUDIO_STORAGE_CONNECTION_STRING": "audio-connection",
                    "AZURE_AUDIO_CONTAINER": "formationaudio-main",
                },
                clear=False,
            ),
            patch(
                "services.audio_publish_service.BlobServiceClient.from_connection_string",
                side_effect=[tts_service, audio_service],
            ),
        ):
            result = publish_playlist_audio_to_platform(1, 42)

        source_container.list_blobs.assert_called_once_with(
            name_starts_with="platform-1/folder-42/playlist/"
        )
        audio_service.get_container_client.assert_called_once_with(
            "formationaudio-main"
        )
        destination_container.get_blob_client.assert_called_once_with(
            "cours_9h00_9h45.mp3"
        )
        destination_blob.upload_blob.assert_called_once()
        upload_args, upload_kwargs = destination_blob.upload_blob.call_args
        self.assertEqual(upload_args[0], b"real mp3 bytes")
        self.assertTrue(upload_kwargs["overwrite"])
        self.assertEqual(
            upload_kwargs["content_settings"].content_type,
            "audio/mpeg",
        )
        self.assertEqual(result["published"], ["cours_9h00_9h45.mp3"])
        self.assertEqual(result["publish_errors"], [])

    def test_reports_an_empty_source_file_as_a_publish_error(self):
        source_container = MagicMock()
        source_container.list_blobs.return_value = [
            SimpleNamespace(name="platform-2/folder-7/playlist/cours_9h00_9h45.mp3"),
        ]
        source_container.get_blob_client.return_value.download_blob.return_value.readall.return_value = b""
        destination_container = MagicMock()

        tts_service = MagicMock()
        tts_service.get_container_client.return_value = source_container
        audio_service = MagicMock()
        audio_service.get_container_client.return_value = destination_container

        with (
            patch.dict(
                os.environ,
                {
                    "AZURE_TTS_STORAGE_CONNECTION_STRING": "tts-connection",
                    "AZURE_AUDIO_STORAGE_CONNECTION_STRING": "audio-connection",
                },
                clear=False,
            ),
            patch(
                "services.audio_publish_service.BlobServiceClient.from_connection_string",
                side_effect=[tts_service, audio_service],
            ),
        ):
            result = publish_playlist_audio_to_platform(2, 7)

        self.assertEqual(result["published"], [])
        self.assertEqual(
            result["publish_errors"][0]["filename"],
            "cours_9h00_9h45.mp3",
        )
        destination_container.get_blob_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
