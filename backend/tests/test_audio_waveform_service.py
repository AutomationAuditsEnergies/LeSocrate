import io
import json
import math
import tempfile
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

from services.audio_waveform_service import (
    create_waveform_for_uploaded_bytes,
    extract_waveform,
    get_or_create_waveform,
    waveform_cache_blob_path,
)


def _wav_bytes(duration_seconds=0.25, sample_rate=8000):
    frame_count = int(duration_seconds * sample_rate)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            value = int(12000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(value.to_bytes(2, "little", signed=True))
        wav.writeframes(frames)
    return output.getvalue()


class AudioWaveformServiceTest(unittest.TestCase):
    def test_extract_waveform_returns_bounded_normalised_peaks(self):
        payload = _wav_bytes()
        with tempfile.NamedTemporaryFile(suffix=".wav") as audio_file:
            audio_file.write(payload)
            audio_file.flush()
            result = extract_waveform(audio_file.name, points=256)

        self.assertAlmostEqual(result["duration"], 0.25, places=2)
        self.assertLessEqual(result["points"], 256)
        self.assertTrue(result["peaks"])
        self.assertTrue(all(0 <= value <= 1 for value in result["peaks"]))

    def test_valid_cache_avoids_downloading_source_audio(self):
        manifest = {
            "schema_version": 1,
            "source_etag": "etag-1",
            "source_size": 123,
            "duration": 10.0,
            "peaks": [0.1, 0.2],
        }
        audio_blob = Mock()
        cache_blob = Mock()
        cache_blob.download_blob.return_value.readall.return_value = json.dumps(manifest).encode()

        result = get_or_create_waveform(
            audio_blob,
            cache_blob,
            audio_properties=SimpleNamespace(etag='"etag-1"', size=123),
        )

        self.assertTrue(result["cache_hit"])
        audio_blob.download_blob.assert_not_called()
        cache_blob.upload_blob.assert_not_called()

    def test_missing_cache_can_return_immediately_without_source_download(self):
        audio_blob = Mock()
        cache_blob = Mock()
        cache_blob.download_blob.side_effect = RuntimeError("missing")

        with self.assertRaises(FileNotFoundError):
            get_or_create_waveform(
                audio_blob,
                cache_blob,
                audio_properties=SimpleNamespace(etag='"etag-1"', size=70_000_000),
                generate_if_missing=False,
            )

        audio_blob.download_blob.assert_not_called()

    def test_upload_bytes_generate_cache_without_redownloading_audio(self):
        audio_blob = Mock()
        audio_blob.blob_name = "course_01.wav"
        cache_blob = Mock()

        result = create_waveform_for_uploaded_bytes(
            audio_blob,
            cache_blob,
            _wav_bytes(),
            audio_properties=SimpleNamespace(etag='"etag-upload"', size=4044),
            points=256,
        )

        self.assertAlmostEqual(result["duration"], 0.25, places=2)
        audio_blob.download_blob.assert_not_called()
        cache_blob.upload_blob.assert_called_once()

    def test_cache_path_is_versioned_and_adjacent_to_audio(self):
        self.assertEqual(
            waveform_cache_blob_path("platform-2/folder-8/playlist/course_01.mp3"),
            "platform-2/folder-8/playlist/course_01.mp3.waveform-v1.json",
        )

    def test_audio_upload_precomputes_waveform_from_existing_bytes(self):
        from services import azure_blob_service

        source_blob = Mock()
        source_blob.get_blob_properties.return_value = SimpleNamespace(
            etag='"new-etag"',
            size=1234,
        )
        cache_blob = Mock()
        storage_client = Mock()
        storage_client.get_blob_client.side_effect = [source_blob, cache_blob]

        with patch.object(
            azure_blob_service,
            "_get_blob_service_client",
            return_value=storage_client,
        ), patch(
            "services.audio_waveform_service.create_waveform_for_uploaded_bytes",
        ) as create_waveform:
            azure_blob_service.upload_blob(
                azure_blob_service.CONTAINER_AUDIOS,
                "platform-2/folder-8/playlist/course_01.mp3",
                b"already-generated-mp3",
            )

        source_blob.upload_blob.assert_called_once()
        create_waveform.assert_called_once_with(
            source_blob,
            cache_blob,
            b"already-generated-mp3",
            audio_properties=source_blob.get_blob_properties.return_value,
        )


if __name__ == "__main__":
    unittest.main()
