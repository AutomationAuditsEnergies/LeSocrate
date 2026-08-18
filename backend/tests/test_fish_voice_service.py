import io
import unittest
from unittest.mock import Mock, patch

from pydub import AudioSegment

from services import fish_voice_service as service


def _wav_bytes(duration_ms=10_000):
    output = io.BytesIO()
    AudioSegment.silent(duration=duration_ms).export(output, format="wav")
    return output.getvalue()


class FishVoiceServiceTest(unittest.TestCase):
    def test_clone_is_private_and_uses_fast_training(self):
        response = Mock(ok=True)
        response.json.return_value = {
            "_id": "voice-ref-123456",
            "state": "created",
            "title": "Sophie",
        }
        with patch.dict("os.environ", {"FISH_AUDIO_API_KEY": "secret"}), patch.object(
            service.http_requests,
            "post",
            return_value=response,
        ) as post:
            result = service.create_instant_clone(
                name="Sophie",
                audio_bytes=_wav_bytes(),
                filename="sophie.wav",
                mime_type="audio/wav",
            )

        self.assertEqual(result["reference_id"], "voice-ref-123456")
        data = dict(post.call_args.kwargs["data"])
        self.assertEqual(data["train_mode"], "fast")
        self.assertEqual(data["visibility"], "private")
        self.assertEqual(post.call_args.kwargs["files"][0][0], "voices")

    def test_asr_calculates_words_per_minute(self):
        response = Mock(ok=True)
        response.json.return_value = {
            "text": "un deux trois quatre cinq six",
            "duration": 3,
            "segments": [],
        }
        with patch.dict("os.environ", {"FISH_AUDIO_API_KEY": "secret"}), patch.object(
            service.http_requests,
            "post",
            return_value=response,
        ):
            result = service.transcribe_and_measure_wpm(
                audio_bytes=_wav_bytes(3_000),
                filename="calibrage.wav",
                mime_type="audio/wav",
            )

        self.assertEqual(result["word_count"], 6)
        self.assertEqual(result["words_per_minute"], 120.0)

    def test_audio_duration_limits_are_enforced(self):
        with self.assertRaises(service.FishVoiceError) as raised:
            service.validate_audio(
                _wav_bytes(5_000),
                "court.wav",
                min_seconds=10,
                max_seconds=90,
                max_bytes=10 * 1024 * 1024,
            )
        self.assertEqual(raised.exception.code, "audio_duration_invalid")


if __name__ == "__main__":
    unittest.main()
