import unittest
from unittest.mock import Mock, patch

from services import voice_reference_calibration_service as service


class VoiceReferenceCalibrationServiceTest(unittest.TestCase):
    def test_canonical_half_contains_exactly_7069_spoken_words(self):
        text, reference_key, word_count = service.load_reference_text()

        self.assertEqual(word_count, 7069)
        self.assertIn("[pause]", text)
        self.assertTrue(reference_key.startswith("fr-course-half-v1-"))

    @patch.object(service, "complete_reference_calibration")
    @patch.object(service, "mark_reference_calibration_running")
    @patch.object(service, "get_platform_voice_settings")
    def test_generation_measures_duration_and_persists_wpm(
        self,
        get_settings,
        mark_running,
        complete,
    ):
        get_settings.return_value = {
            "id": 12,
            "center_account_id": 42,
            "fish_reference_id": "fish-voice-12",
            "playback_speed": 1.1,
            "calibration_status": "pending",
        }
        complete.return_value = {"id": 12, "calibration_status": "completed"}
        synthesize = Mock(return_value=(b"mp3", {"audio_duration_sec": 2700.0}))

        result = service.calibrate_platform_voice(7, synthesize=synthesize)

        text = synthesize.call_args.args[0]
        self.assertEqual(service.count_reference_words(text), 7069)
        self.assertEqual(synthesize.call_args.kwargs["voice_id"], "fish-voice-12")
        self.assertEqual(synthesize.call_args.kwargs["speed"], 1.1)
        self.assertAlmostEqual(result["words_per_minute"], 157.089, places=3)
        mark_running.assert_called_once()
        self.assertEqual(complete.call_args.kwargs["word_count"], 7069)
        self.assertEqual(complete.call_args.kwargs["duration_sec"], 2700.0)

    @patch.object(service, "get_platform_voice_settings")
    def test_current_reference_at_same_speed_is_reused(self, get_settings):
        _, reference_key, _ = service.load_reference_text()
        get_settings.return_value = {
            "id": 12,
            "center_account_id": 42,
            "fish_reference_id": "fish-voice-12",
            "playback_speed": 1.0,
            "calibration_status": "completed",
            "calibration_reference_key": reference_key,
            "calibration_word_count": 7069,
            "calibration_duration_sec": 2700,
            "calibration_playback_speed": 1.0,
            "measured_wpm": 157.089,
        }
        synthesize = Mock()

        result = service.calibrate_platform_voice(7, synthesize=synthesize)

        self.assertEqual(result["status"], "reused")
        synthesize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
