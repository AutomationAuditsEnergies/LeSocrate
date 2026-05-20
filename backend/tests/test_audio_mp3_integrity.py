import unittest
from unittest.mock import patch

from services.basic_tts_service import concat_mp3_bytes
from services import content_generation_service as cgs


def _id3_header(payload: bytes) -> bytes:
    size = len(payload)
    return bytes([
        0x49, 0x44, 0x33, 0x04, 0x00, 0x00,
        (size >> 21) & 0x7F,
        (size >> 14) & 0x7F,
        (size >> 7) & 0x7F,
        size & 0x7F,
    ]) + payload


class AudioMp3IntegrityTest(unittest.TestCase):
    def test_concat_mp3_bytes_strips_intermediate_id3_headers(self):
        first = _id3_header(b"meta-one") + b"\xff\xfbFIRST"
        second = _id3_header(b"meta-two") + b"\xff\xfbSECOND"

        result = concat_mp3_bytes([first, second])

        self.assertEqual(result.count(b"ID3"), 1)
        self.assertIn(b"\xff\xfbFIRST", result)
        self.assertIn(b"\xff\xfbSECOND", result)
        self.assertNotIn(b"meta-two", result)

    def test_slide_synced_edge_tts_does_not_prefix_bundled_silence(self):
        bloc = {
            "bloc_number": 1,
            "target_sec": 2700,
            "text": "un deux trois quatre",
            "word_count": 4,
            "start_w": 0,
            "end_w": 4,
        }
        slides = [
            {"slide_id": "s1", "source_ref": {"word_start": 0, "word_end": 2}},
            {"slide_id": "s2", "source_ref": {"word_start": 2, "word_end": 4}},
        ]
        edge_chunks = [
            _id3_header(b"edge-one") + b"\xff\xfbVOICE1",
            _id3_header(b"edge-two") + b"\xff\xfbVOICE2",
        ]

        with patch(
            "services.basic_tts_service.convert_to_speech_basic",
            side_effect=edge_chunks,
        ), patch.object(
            cgs,
            "_mp3_duration_seconds_no_ffprobe",
            side_effect=[3.0, 4.0],
        ):
            audio_bytes, voice_duration, fit_method, attempts, timings, unconsumed, consumed = (
                cgs._synthesize_course_audio_synced_to_slides(
                    bloc,
                    slides,
                    "cours_9h00_9h45.mp3",
                    mock=False,
                    basic_tts=True,
                )
            )

        self.assertEqual(fit_method, "slide_sync_edge_no_padding")
        self.assertEqual(voice_duration, 7.0)
        self.assertEqual(attempts[0]["duration"], 3.0)
        self.assertEqual(timings[0]["start_time"], 0.0)
        self.assertEqual(unconsumed, [])  # runtime_fit=False par défaut → rien reporté
        self.assertEqual(consumed, [])
        self.assertNotIn(b"meta-two", audio_bytes)

    def test_runtime_fit_edge_tts_uses_measured_muted_padding(self):
        bloc = {
            "bloc_number": 1,
            "target_sec": 300,
            "text": "un deux trois quatre",
            "word_count": 4,
            "start_w": 0,
            "end_w": 4,
        }
        voice = _id3_header(b"edge-voice") + b"\xff\xfbVOICE"
        conclusion = _id3_header(b"edge-concl") + b"\xff\xfbCONCL"
        padding = _id3_header(b"edge-pad") + b"\xff\xfbPAD"

        with patch(
            "services.basic_tts_service.convert_to_speech_basic",
            return_value=voice,
        ), patch.object(
            cgs,
            "_synthesize_short_conclusion_audio",
            return_value=(conclusion, 10.0),
        ), patch.object(
            cgs,
            "_edge_muted_padding_audio",
            return_value=(padding, 260.0),
        ) as muted_padding, patch.object(
            cgs,
            "_mp3_duration_seconds_no_ffprobe",
            side_effect=[30.0, 300.0],
        ):
            audio_bytes, voice_duration, fit_method, attempts, _timings, _unconsumed, _consumed = (
                cgs._synthesize_course_audio_synced_to_slides(
                    bloc,
                    [],
                    "cours_9h00_9h45.mp3",
                    mock=False,
                    basic_tts=True,
                    runtime_fit=True,
                )
            )

        self.assertEqual(fit_method, "slide_sync_edge_runtime_fit")
        self.assertEqual(voice_duration, 30.0)
        muted_padding.assert_called_once()
        self.assertTrue(any(a["kind"] == "final_silence_padding" for a in attempts))
        self.assertIn(b"VOICE", audio_bytes)
        self.assertNotIn(b"CONCL", audio_bytes)
        self.assertIn(b"PAD", audio_bytes)


if __name__ == "__main__":
    unittest.main()
