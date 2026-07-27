import os
import subprocess
import unittest
from unittest.mock import Mock, patch

from services import basic_tts_service as tts


class BasicTTSWatchdogTest(unittest.TestCase):
    def test_stuck_edge_tts_process_is_killed_at_deadline(self):
        proc = Mock()
        proc.pid = 321
        proc.poll.side_effect = [None, None, None, None]

        with (
            patch.dict(os.environ, {"EDGE_TTS_SUBPROCESS_TIMEOUT_SEC": "10"}),
            patch.object(tts.subprocess, "Popen", return_value=proc),
            patch.object(tts.time, "monotonic", side_effect=[0.0, 11.0]),
            patch.object(tts.time, "sleep"),
            patch.object(tts.os, "killpg") as killpg,
        ):
            with self.assertRaisesRegex(TimeoutError, "timeout après 10s"):
                tts._synthesize_chunk_sync("Bonjour", "voice", "+0%", "+0%")

        killpg.assert_called_with(321, tts.signal.SIGKILL)
        proc.wait.assert_called_with(timeout=5)

    def test_configured_smaller_chunks_are_used(self):
        source = ("Une phrase assez longue pour tester le découpage. " * 60).strip()
        synthesized_chunks = []

        def fake_synthesize(text, _voice, _rate, _volume):
            synthesized_chunks.append(text)
            return b"\xff\xfb" + text.encode("utf-8")

        with (
            patch.dict(
                os.environ,
                {
                    "EDGE_TTS_CHUNK_MAX_CHARS": "500",
                    "BASIC_TTS_CHUNK_DELAY_SEC": "0",
                },
            ),
            patch.object(tts, "_synthesize_chunk_sync", side_effect=fake_synthesize),
        ):
            audio = tts.convert_to_speech_basic(
                source,
                max_429_retries=0,
                parallel_workers=1,
            )

        self.assertTrue(audio)
        self.assertGreater(len(synthesized_chunks), 1)
        self.assertTrue(all(len(chunk) <= 500 for chunk in synthesized_chunks))


if __name__ == "__main__":
    unittest.main()
