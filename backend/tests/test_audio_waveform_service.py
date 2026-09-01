import io
import json
import math
import tempfile
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import Mock

from services.audio_waveform_service import (
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

    def test_cache_path_is_versioned_and_adjacent_to_audio(self):
        self.assertEqual(
            waveform_cache_blob_path("platform-2/folder-8/playlist/course_01.mp3"),
            "platform-2/folder-8/playlist/course_01.mp3.waveform-v1.json",
        )


if __name__ == "__main__":
    unittest.main()
