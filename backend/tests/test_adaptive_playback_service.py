import unittest

from services.adaptive_playback_service import (
    apply_occurrence_playback_manifest,
    build_occurrence_playback_manifest,
    course_playback_cap_seconds,
)


class AdaptivePlaybackServiceTest(unittest.TestCase):
    def test_early_course_extends_the_first_following_qa(self):
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
        self.assertEqual(manifest["final_drift_sec"], 0)
        self.assertTrue(manifest["segments"][1]["elastic"])
        self.assertEqual(
            manifest["strategy"],
            "recursive_course_drift_then_first_optional_flexible_block",
        )

    def test_qa_can_shrink_by_five_minutes_at_most(self):
        playlist = [
            ("course_01.mp3", 3600, "cours", 1),
            ("qa_01.mp3", 900, "qa", 1),
        ]
        manifest = build_occurrence_playback_manifest(
            playlist,
            {"course_01.mp3": 3900.0, "qa_01.mp3": 900.0},
        )

        self.assertEqual(
            [segment["effective_duration_sec"] for segment in manifest["segments"]],
            [3900, 600],
        )
        self.assertFalse(manifest["segments"][0]["hard_stopped"])

    def test_eight_minute_delay_keeps_ten_minute_qa_and_cuts_three_minutes(self):
        playlist = [
            ("course_01.mp3", 3600, "cours", 1),
            ("qa_01.mp3", 900, "qa", 1),
        ]

        self.assertEqual(course_playback_cap_seconds(playlist, 0), 3900)
        manifest = build_occurrence_playback_manifest(
            playlist,
            {"course_01.mp3": 4080.0, "qa_01.mp3": 900.0},
        )

        self.assertEqual(
            [segment["effective_duration_sec"] for segment in manifest["segments"]],
            [3900, 600],
        )
        self.assertTrue(manifest["segments"][0]["hard_stopped"])
        self.assertEqual(manifest["segments"][0]["hard_stop_sec"], 3900)

    def test_adjacent_course_chain_propagates_advance_through_jointure(self):
        playlist = [
            ("course_01.mp3", 3600, "cours", 1),
            ("jointure_01_02.mp3", 10, "jointure", 1),
            ("course_02.mp3", 3600, "cours", 2),
            ("qa_01.mp3", 900, "qa", 2),
        ]
        manifest = build_occurrence_playback_manifest(
            playlist,
            {
                "course_01.mp3": 3300.0,
                "jointure_01_02.mp3": 8.0,
                "course_02.mp3": 3600.0,
                "qa_01.mp3": 900.0,
            },
        )

        self.assertEqual(
            [segment["effective_duration_sec"] for segment in manifest["segments"]],
            [3300, 8, 3600, 1192],
        )
        self.assertEqual(manifest["segments"][2]["effective_start_sec"], 3308)
        self.assertEqual(manifest["technical_jointure_duration_sec"], 8)
        self.assertEqual(manifest["effective_total_duration_sec"], 8100)

    def test_accumulated_delay_is_cut_only_from_last_course_before_flex(self):
        playlist = [
            ("course_01.mp3", 3600, "cours", 1),
            ("jointure_01_02.mp3", 10, "jointure", 1),
            ("course_02.mp3", 3600, "cours", 2),
            ("qa_01.mp3", 900, "qa", 2),
        ]
        manifest = build_occurrence_playback_manifest(
            playlist,
            {
                "course_01.mp3": 3900.0,
                "jointure_01_02.mp3": 10.0,
                "course_02.mp3": 3900.0,
                "qa_01.mp3": 900.0,
            },
        )

        self.assertEqual(
            [segment["effective_duration_sec"] for segment in manifest["segments"]],
            [3900, 10, 3590, 600],
        )
        self.assertFalse(manifest["segments"][0]["hard_stopped"])
        self.assertTrue(manifest["segments"][2]["hard_stopped"])
        self.assertEqual(manifest["final_drift_sec"], 0)

    def test_pause_is_elastic_when_no_qa_precedes_it(self):
        playlist = [
            ("course_01.mp3", 3600, "cours", 1),
            ("pause_01.mp3", 900, "pause", 1),
            ("course_02.mp3", 3600, "cours", 2),
        ]
        manifest = build_occurrence_playback_manifest(
            playlist,
            {"course_01.mp3": 3720.0, "pause_01.mp3": 900.0, "course_02.mp3": 3600.0},
        )

        self.assertEqual(
            [segment["effective_duration_sec"] for segment in manifest["segments"][:2]],
            [3720, 780],
        )
        self.assertTrue(manifest["segments"][1]["elastic"])

    def test_only_first_optional_block_after_course_chain_is_elastic(self):
        qa_then_pause = [
            ("course_01.mp3", 3600, "cours", 1),
            ("qa_01.mp3", 600, "qa", 1),
            ("pause_01.mp3", 600, "pause", 1),
            ("course_02.mp3", 3600, "cours", 2),
        ]
        manifest = build_occurrence_playback_manifest(
            qa_then_pause,
            {"course_01.mp3": 3500.0},
        )
        self.assertEqual(
            [segment["effective_duration_sec"] for segment in manifest["segments"]],
            [3500, 700, 600, 3600],
        )
        self.assertTrue(manifest["segments"][1]["elastic"])
        self.assertFalse(manifest["segments"][2]["elastic"])

        pause_then_qa = [
            ("course_01.mp3", 3600, "cours", 1),
            ("pause_01.mp3", 600, "pause", 1),
            ("qa_01.mp3", 600, "qa", 1),
        ]
        reverse_manifest = build_occurrence_playback_manifest(
            pause_then_qa,
            {"course_01.mp3": 3500.0},
        )
        self.assertEqual(
            [segment["effective_duration_sec"] for segment in reverse_manifest["segments"]],
            [3500, 700, 600],
        )

    def test_a_day_ending_with_course_keeps_its_natural_final_drift(self):
        manifest = build_occurrence_playback_manifest(
            [("course_01.mp3", 3600, "cours", 1)],
            {"course_01.mp3": 3420.0},
        )
        self.assertEqual(manifest["effective_total_duration_sec"], 3420)
        self.assertEqual(manifest["final_drift_sec"], -180)

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
