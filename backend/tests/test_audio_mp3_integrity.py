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
        edge_padding = _id3_header(b"edge-pad") + b"\xff\xfbPAD"

        with patch(
            "services.basic_tts_service.convert_to_speech_basic",
            side_effect=edge_chunks,
        ), patch.object(
            cgs,
            "_mp3_duration_seconds_no_ffprobe",
            side_effect=[3.0, 4.0],
        ), patch.object(
            cgs,
            "_edge_muted_padding_audio",
            return_value=(edge_padding, 2693.0),
        ) as muted_padding:
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
        muted_padding.assert_called_once()
        self.assertIn(b"PAD", audio_bytes)
        self.assertNotIn(b"meta-two", audio_bytes)

    def test_dynamic_slide_synced_course_keeps_natural_duration_without_padding(self):
        bloc = {
            "bloc_number": 1,
            "target_sec": 3600,
            "dynamic_schedule": True,
            "text": "un deux trois quatre",
            "word_count": 4,
            "start_w": 0,
            "end_w": 4,
        }
        slides = [
            {"slide_id": "s1", "source_ref": {"word_start": 0, "word_end": 4}},
        ]
        voice = _id3_header(b"edge-natural") + b"\xff\xfbVOICE"

        with patch(
            "services.basic_tts_service.convert_to_speech_basic",
            return_value=voice,
        ), patch.object(
            cgs,
            "_mp3_duration_seconds_no_ffprobe",
            return_value=3180.0,
        ), patch.object(
            cgs,
            "_edge_muted_padding_audio",
        ) as muted_padding:
            audio_bytes, voice_duration, fit_method, attempts, _timings, _, _ = (
                cgs._synthesize_course_audio_synced_to_slides(
                    bloc,
                    slides,
                    "course_01.mp3",
                    mock=False,
                    basic_tts=True,
                )
            )

        self.assertEqual(voice_duration, 3180.0)
        self.assertEqual(fit_method, "slide_sync_edge_natural")
        self.assertFalse(any(item["kind"] == "final_silence_padding" for item in attempts))
        muted_padding.assert_not_called()
        self.assertIn(b"VOICE", audio_bytes)

    def test_edge_tts_uses_measured_muted_padding_when_runtime_fit_is_disabled(self):
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

        self.assertEqual(fit_method, "slide_sync_edge_no_padding")
        self.assertEqual(voice_duration, 30.0)
        muted_padding.assert_called_once()
        self.assertTrue(any(a["kind"] == "final_silence_padding" for a in attempts))
        self.assertIn(b"VOICE", audio_bytes)
        self.assertNotIn(b"CONCL", audio_bytes)
        self.assertIn(b"PAD", audio_bytes)

    def test_fish_slide_boundaries_use_real_mp3_durations(self):
        bloc = {
            "bloc_number": 1,
            "target_sec": 60,
            "text": "un deux trois quatre",
            "word_count": 4,
            "start_w": 0,
            "end_w": 4,
        }
        slides = [
            {"slide_id": "s1", "source_ref": {"word_start": 0, "word_end": 2}},
            {"slide_id": "s2", "source_ref": {"word_start": 2, "word_end": 4}},
        ]
        timestamp_meta = {
            "provider": "fish_audio",
            "audio_duration_sec": 3.0,
            "spoken_word_count": 2,
            "words_per_minute": 40.0,
            "timeline": [],
        }

        with patch.object(
            cgs,
            "_fish_silent_mp3_approx_no_ffmpeg",
            side_effect=[(b"START", 17.0), (b"END", 34.0)],
        ), patch(
            "services.tts_service.convert_to_speech_with_timestamps",
            side_effect=[(b"VOICE1", timestamp_meta), (b"VOICE2", timestamp_meta)],
        ), patch.object(
            cgs,
            "_mp3_duration_seconds_no_ffprobe",
            side_effect=[3.4, 3.6],
        ), patch(
            "services.basic_tts_service.concat_mp3_bytes",
            return_value=b"FINAL",
        ):
            _, voice_duration, _, attempts, timings, _, _ = (
                cgs._synthesize_course_audio_synced_to_slides(
                    bloc,
                    slides,
                    "cours.mp3",
                    mock=False,
                    basic_tts=False,
                )
            )

        self.assertEqual(voice_duration, 7.0)
        self.assertEqual(timings[0]["start_time"], 17.0)
        self.assertEqual(timings[0]["end_time"], 20.4)
        self.assertEqual(timings[1]["start_time"], 20.4)
        self.assertEqual(timings[1]["end_time"], 24.0)
        self.assertEqual(attempts[0]["timeline_duration_sec"], 3.0)
        self.assertEqual(attempts[0]["media_duration_sec"], 3.4)

    def test_contextual_break_silence_fallback_preserves_slot_duration(self):
        with patch(
            "services.break_transition_service.build_break_transition_texts",
            side_effect=RuntimeError("llm unavailable"),
        ), patch(
            "services.playlist_tts_service._get_recycled_qa_pause",
            side_effect=RuntimeError("azure unavailable"),
        ), patch(
            "services.playlist_tts_service._generate_silence_mp3",
            return_value=b"FULL-SILENCE",
        ) as silence:
            audio_bytes, mode = cgs._build_contextual_break_audio(
                filename="qa_9h45_9h55.mp3",
                duration_sec=600,
                file_type="qa",
                bloc_num=1,
                item_idx=1,
                playlist_items=[
                    ("cours_9h00_9h45.mp3", 2700, "cours", 1),
                    ("qa_9h45_9h55.mp3", 600, "qa", 1),
                ],
                blocs_by_number={1: {"text": "contenu du cours"}},
            )

        silence.assert_called_once_with(600)
        self.assertEqual(audio_bytes, b"FULL-SILENCE")
        self.assertEqual(mode, "silence_fallback")

    def test_fish_end_only_break_starts_with_real_silence_without_primer_voice(self):
        with patch(
            "services.tts_service.convert_to_speech",
            return_value=b"OUTRO",
        ) as tts, patch.object(
            cgs,
            "_mp3_duration_seconds_no_ffprobe",
            return_value=5.0,
        ), patch.object(
            cgs,
            "_fish_silent_mp3_approx_no_ffmpeg",
            side_effect=[(b"LEADING-SILENCE", 53.0), (b"TAIL-SILENCE", 2.0)],
        ), patch(
            "services.basic_tts_service.concat_mp3_bytes",
            side_effect=lambda parts: b"|".join(parts),
        ):
            audio_bytes, duration = cgs._build_end_only_fish_break_audio_no_ffmpeg(
                "La pause est terminée.",
                60,
            )

        tts.assert_called_once_with("La pause est terminée.")
        self.assertEqual(duration, 60.0)
        self.assertEqual(audio_bytes, b"LEADING-SILENCE|OUTRO|TAIL-SILENCE")


if __name__ == "__main__":
    unittest.main()
