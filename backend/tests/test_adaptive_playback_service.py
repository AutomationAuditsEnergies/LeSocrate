import unittest

from services.adaptive_playback_service import (
    apply_occurrence_playback_manifest,
    build_occurrence_playback_manifest,
    course_playback_cap_seconds,
)


class AdaptivePlaybackServiceTest(unittest.TestCase):
    def test_early_course_extends_the_only_following_qa(self):
        playlist = [
            ("course_01.mp3", 3600, "cours", 1),
            ("qa_01.mp3", 900, "qa", 1),
        ]

        manifest = build_occurrence_playback_manifest(
            playlist,
            {"course_01.mp3": 3180.8, "qa_01.mp3": 900.1},
        )

        self.assertEqual(
            [segment["effective_duration_sec"] for segment in manifest["segments"]],
            [3181, 1319],
        )
        self.assertEqual(manifest["effective_total_duration_sec"], 4500)
        self.assertTrue(manifest["segments"][1]["elastic"])
        self.assertEqual(
            manifest["segments"][1]["generation_target_duration_sec"],
            1319,
        )
        self.assertEqual(
            manifest["strategy"],
            "natural_course_then_exact_elastic_break_assets",
        )

    def test_small_overrun_shortens_the_following_qa(self):
        playlist = [
            ("course_01.mp3", 3600, "cours", 1),
            ("qa_01.mp3", 900, "qa", 1),
        ]

        manifest = build_occurrence_playback_manifest(
            playlist,
            {"course_01.mp3": 3660.4, "qa_01.mp3": 900.0},
        )

        self.assertEqual(
            [segment["effective_duration_sec"] for segment in manifest["segments"]],
            [3661, 839],
        )
        self.assertFalse(manifest["segments"][0]["hard_stopped"])

    def test_large_overrun_hard_stops_course_and_preserves_five_minutes(self):
        playlist = [
            ("course_01.mp3", 3600, "cours", 1),
            ("qa_01.mp3", 900, "qa", 1),
        ]

        self.assertEqual(course_playback_cap_seconds(playlist, 0), 4200)
        manifest = build_occurrence_playback_manifest(
            playlist,
            {"course_01.mp3": 4400.0, "qa_01.mp3": 900.0},
        )

        self.assertEqual(
            [segment["effective_duration_sec"] for segment in manifest["segments"]],
            [4200, 300],
        )
        self.assertTrue(manifest["segments"][0]["hard_stopped"])

    def test_immediate_qa_absorbs_drift_and_pause_keeps_its_slot(self):
        playlist = [
            ("course_01.mp3", 3600, "cours", 1),
            ("qa_01.mp3", 600, "qa", 1),
            ("pause_01.mp3", 600, "pause", 1),
            ("course_02.mp3", 3600, "cours", 2),
            ("qa_02.mp3", 600, "qa", 2),
        ]

        manifest = build_occurrence_playback_manifest(
            playlist,
            {
                "course_01.mp3": 3500.0,
                "qa_01.mp3": 600.0,
                "pause_01.mp3": 600.0,
                "course_02.mp3": 3600.0,
                "qa_02.mp3": 600.0,
            },
        )

        self.assertEqual(
            [segment["effective_duration_sec"] for segment in manifest["segments"][:4]],
            [3500, 700, 600, 3600],
        )
        self.assertEqual(manifest["segments"][3]["effective_start_sec"], 4800)

    def test_hard_stop_preserves_immediate_qa_minimum_and_nominal_pause(self):
        playlist = [
            ("course_01.mp3", 3600, "cours", 1),
            ("qa_01.mp3", 600, "qa", 1),
            ("pause_01.mp3", 600, "pause", 1),
            ("course_02.mp3", 3600, "cours", 2),
            ("qa_02.mp3", 600, "qa", 2),
        ]

        self.assertEqual(course_playback_cap_seconds(playlist, 0), 3900)
        manifest = build_occurrence_playback_manifest(
            playlist,
            {
                "course_01.mp3": 4400.0,
                "qa_01.mp3": 600.0,
                "pause_01.mp3": 600.0,
                "course_02.mp3": 3600.0,
                "qa_02.mp3": 600.0,
            },
        )

        self.assertEqual(
            [segment["effective_duration_sec"] for segment in manifest["segments"][:4]],
            [3900, 300, 600, 3600],
        )
        self.assertTrue(manifest["segments"][0]["hard_stopped"])

    def test_manifest_overlay_exposes_effective_and_asset_durations(self):
        playlist = [
            {
                "id": 1,
                "filename": "course_01.mp3",
                "duration": 3600,
                "type": "cours",
                "course_index": 1,
            },
            {
                "id": 2,
                "filename": "qa_01.mp3",
                "duration": 900,
                "type": "qa",
                "course_index": 1,
            },
        ]
        manifest = build_occurrence_playback_manifest(
            [
                ("course_01.mp3", 3600, "cours", 1),
                ("qa_01.mp3", 900, "qa", 1),
            ],
            {"course_01.mp3": 3180.8, "qa_01.mp3": 900.1},
        )

        adapted = apply_occurrence_playback_manifest(playlist, manifest)

        self.assertEqual(adapted[0]["duration"], 3181)
        self.assertEqual(adapted[0]["planned_duration"], 3600)
        self.assertEqual(adapted[0]["asset_duration"], 3180.8)
        self.assertEqual(adapted[1]["duration"], 1319)


if __name__ == "__main__":
    unittest.main()
