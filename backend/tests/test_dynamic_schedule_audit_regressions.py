import json
import unittest
from unittest.mock import patch

from services import content_generation_service as content
from services import script_rules_service as rules
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


class ScriptRulesDynamicCourseLabelTest(unittest.TestCase):
    def _review_labels(self, total_courses, filenames):
        blocs = [
            {
                "bloc_number": index,
                "filename": filename,
                "text": f"Texte pédagogique unique du cours {index}.",
            }
            for index, filename in enumerate(filenames, start=1)
        ]
        response = json.dumps({
            "conforme": True,
            "violations": [],
            "patches": [],
        })
        with patch.object(
            rules,
            "_fetch_context",
            return_value={"job_id": 91, "platform_id": 12},
        ), patch.object(
            rules,
            "get_rules",
            return_value={"rules_markdown": "# Règles"},
        ), patch.object(
            content,
            "get_course_script_plan_for_ui",
            return_value={"course_blocs": blocs},
        ), patch.object(
            content,
            "resolve_folder_content_course_count",
            return_value=total_courses,
        ), patch.object(
            rules,
            "_list_completed_segment_tuples",
            return_value=[],
        ), patch.object(
            rules,
            "post_message",
            return_value=response,
        ), patch.object(
            rules,
            "_TEXT_REVIEW_PARALLEL",
            1,
        ):
            result = rules.review_blocs_with_rules(118, dry_run=True)

        return [
            detail["sub_part_name"]
            for detail in result["details"]
        ]

    def test_v2_labels_use_manifest_total_instead_of_seven(self):
        labels = self._review_labels(
            5,
            [f"course_{index:02d}.mp3" for index in range(1, 6)],
        )

        self.assertEqual(len(labels), 5)
        self.assertIn("Cours 5/5 (course_05.mp3)", labels)
        self.assertTrue(all("/7" not in label for label in labels))

    def test_v1_labels_keep_seven(self):
        labels = self._review_labels(
            7,
            [f"cours_legacy_{index}.mp3" for index in range(1, 8)],
        )

        self.assertIn("Cours 7/7 (cours_legacy_7.mp3)", labels)


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
