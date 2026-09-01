import unittest
from unittest.mock import patch

from services import content_generation_service as content
from services.playlist_tts_service import PLAYLIST_SPEC


def _dynamic_playlist():
    return [
        ("course_01.mp3", 3600, "cours", 1),
        ("qa_01.mp3", 600, "qa", 1),
        ("pause_01.mp3", 600, "pause", 1),
        ("course_02.mp3", 3600, "cours", 2),
        ("qa_02.mp3", 600, "qa", 2),
        ("pause_02.mp3", 3600, "pause_midi", 2),
        ("course_03.mp3", 3600, "cours", 3),
        ("qa_03.mp3", 600, "qa", 3),
        ("pause_03.mp3", 600, "pause", 3),
        ("course_04.mp3", 3600, "cours", 4),
        ("qa_04.mp3", 600, "qa", 4),
    ]


class AudioProgressManifestFirstTest(unittest.TestCase):
    def _first_progress_total(self, playlist):
        state = {"resolved": False}
        events = []

        def resolve_playlist(*_args, **_kwargs):
            state["resolved"] = True
            return list(playlist)

        def on_progress(step, total, message):
            self.assertTrue(
                state["resolved"],
                "Aucun progrès ne doit être émis avant la résolution du manifeste",
            )
            events.append((step, total, message))

        with patch.object(
            content,
            "get_job_from_db",
            return_value={
                "id": 91,
                "platform_id": 12,
                "formation_job_id": 44,
            },
        ), patch.object(
            content,
            "_playlist_items_for_platform",
            side_effect=resolve_playlist,
        ), patch.object(
            content,
            "_load_saved_course_script_plan",
            return_value={},
        ), patch.object(
            content,
            "assert_course_day_word_budget",
            return_value={"ok": True},
        ), patch.object(
            content,
            "_find_next_folder_id",
            return_value=None,
        ), patch.object(
            content,
            "list_completed_content_segment_rows",
            return_value=[],
        ):
            with self.assertRaisesRegex(ValueError, "Aucun segment généré"):
                content.generate_audio_from_script(
                    118,
                    on_progress=on_progress,
                    mock=True,
                )

        self.assertTrue(events)
        return events

    def test_v2_first_event_uses_exact_eleven_file_manifest(self):
        events = self._first_progress_total(_dynamic_playlist())

        self.assertEqual(events[0][1], 11)
        self.assertIn("4 cours, 11 fichiers", events[0][2])
        self.assertNotIn(19, [event[1] for event in events])

    def test_v1_first_event_keeps_resolved_nineteen_file_playlist(self):
        events = self._first_progress_total(PLAYLIST_SPEC)

        self.assertEqual(events[0][1], 19)
        self.assertIn("7 cours, 19 fichiers", events[0][2])


if __name__ == "__main__":
    unittest.main()
