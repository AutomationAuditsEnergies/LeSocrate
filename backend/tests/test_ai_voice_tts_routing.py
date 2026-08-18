import unittest
from unittest.mock import Mock, patch

from services import tts_service


class AIVoiceTTSRoutingTest(unittest.TestCase):
    def test_platform_voice_overrides_global_reference_and_speed(self):
        response = Mock(status_code=200, content=b"mp3")
        with (
            patch.dict("os.environ", {"FISH_AUDIO_API_KEY": "secret"}),
            patch(
                "repositories.ai_voice_repository.get_platform_voice_settings",
                return_value={
                    "fish_reference_id": "center-voice-ref",
                    "playback_speed": 1.15,
                },
            ),
            patch.object(tts_service.http_requests, "post", return_value=response) as post,
        ):
            audio = tts_service.convert_to_speech("Bonjour", platform_id=17)

        self.assertEqual(audio, b"mp3")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["reference_id"], "center-voice-ref")
        self.assertEqual(payload["prosody"]["speed"], 1.15)


if __name__ == "__main__":
    unittest.main()
