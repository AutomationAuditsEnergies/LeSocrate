import sqlite3
import unittest
from unittest.mock import patch

from services.day_playlist_service import build_playlist_items, resolve_folder_playlist


def _block(
    position,
    block_type,
    start,
    end,
    *,
    pause_kind=None,
):
    return {
        "position": position,
        "block_type": block_type,
        "pause_kind": pause_kind,
        "start_minute": start,
        "end_minute": end,
        "duration_minutes": end - start,
    }


class DynamicDayPlaylistServiceTest(unittest.TestCase):
    def test_four_courses_without_final_pause_produces_eleven_files(self):
        blocks = [
            _block(0, "course", 540, 600),
            _block(1, "qa", 600, 610),
            _block(2, "pause", 610, 620, pause_kind="short"),
            _block(3, "course", 620, 680),
            _block(4, "qa", 680, 690),
            _block(5, "pause", 690, 750, pause_kind="lunch"),
            _block(6, "course", 750, 810),
            _block(7, "qa", 810, 825),
            _block(8, "pause", 825, 835, pause_kind="short"),
            _block(9, "course", 835, 895),
            _block(10, "qa", 895, 910),
        ]

        playlist = build_playlist_items(blocks)

        self.assertEqual(len(playlist), 11)
        self.assertEqual(
            [item[2] for item in playlist],
            [
                "cours", "qa", "pause",
                "cours", "qa", "pause_midi",
                "cours", "qa", "pause",
                "cours", "qa",
            ],
        )
        self.assertEqual(playlist[0], ("course_01.mp3", 3600, "cours", 1))
        self.assertEqual(playlist[5], ("pause_02.mp3", 3600, "pause_midi", 2))
        self.assertEqual(playlist[-1], ("qa_04.mp3", 900, "qa", 4))

    def test_final_pause_is_rejected_by_the_canonical_compiler(self):
        blocks = [
            _block(0, "course", 540, 585),
            _block(1, "qa", 585, 595),
            _block(2, "pause", 595, 605, pause_kind="short"),
            _block(3, "course", 605, 665),
            _block(4, "qa", 665, 675),
            _block(5, "pause", 675, 735, pause_kind="lunch"),
            _block(6, "course", 735, 795),
            _block(7, "qa", 795, 805),
            _block(8, "pause", 805, 815, pause_kind="short"),
            _block(9, "course", 815, 890),
            _block(10, "qa", 890, 900),
            _block(11, "pause", 900, 910, pause_kind="short"),
        ]
        with self.assertRaisesRegex(ValueError, "ne peut pas se terminer"):
            build_playlist_items(blocks)

    def test_adjacent_courses_receive_a_hidden_ten_second_jointure(self):
        blocks = [
            _block(0, "course", 540, 600),
            _block(1, "course", 600, 645),
            _block(2, "qa", 645, 655),
        ]

        self.assertEqual(
            build_playlist_items(blocks),
            [
                ("course_01.mp3", 3600, "cours", 1),
                ("jointure_01_02.mp3", 10, "jointure", 1),
                ("course_02.mp3", 2700, "cours", 2),
                ("qa_01.mp3", 600, "qa", 2),
            ],
        )

    def test_rejects_unknown_block_type(self):
        with self.assertRaisesRegex(ValueError, "course, qa ou pause"):
            build_playlist_items([_block(0, "quiz", 540, 550)])

    def test_repository_failure_never_falls_back_to_the_legacy_playlist(self):
        with patch(
            "repositories.day_schedule_repository.get_module_day_for_folder",
            side_effect=RuntimeError("planning store unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "planning store unavailable"):
                resolve_folder_playlist(91)

    def test_historic_sqlite_without_v2_table_keeps_the_v1_playlist(self):
        with patch(
            "repositories.day_schedule_repository.get_module_day_for_folder",
            side_effect=sqlite3.OperationalError(
                "no such table: formation_module_days"
            ),
        ), patch(
            "repositories.day_schedule_repository.get_schedule_snapshot_for_folder",
            return_value={"schedule_schema_version": 1},
        ):
            resolved = resolve_folder_playlist(91)

        self.assertEqual(resolved["schema_version"], 1)
        self.assertEqual(len(resolved["playlist_items"]), 19)

    def test_historic_sqlite_without_any_v2_columns_keeps_v1(self):
        with patch(
            "repositories.day_schedule_repository.get_module_day_for_folder",
            side_effect=sqlite3.OperationalError(
                "no such table: formation_module_days"
            ),
        ), patch(
            "repositories.day_schedule_repository.get_schedule_snapshot_for_folder",
            side_effect=sqlite3.OperationalError(
                "no such column: j.schedule_schema_version"
            ),
        ):
            resolved = resolve_folder_playlist(91)

        self.assertEqual(resolved["schema_version"], 1)
        self.assertEqual(resolved["source"], "legacy")

    def test_pipeline_snapshot_failure_never_falls_back_to_legacy(self):
        with patch(
            "repositories.day_schedule_repository.get_module_day_for_folder",
            return_value=None,
        ), patch(
            "repositories.day_schedule_repository.get_schedule_snapshot_for_folder",
            side_effect=RuntimeError("snapshot unreadable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "snapshot unreadable"):
                resolve_folder_playlist(91)

    def test_explicit_v1_folder_keeps_the_historic_playlist(self):
        with patch(
            "repositories.day_schedule_repository.get_module_day_for_folder",
            return_value=None,
        ), patch(
            "repositories.day_schedule_repository.get_schedule_snapshot_for_folder",
            return_value={"schedule_schema_version": 1},
        ):
            resolved = resolve_folder_playlist(91)

        self.assertEqual(resolved["schema_version"], 1)
        self.assertEqual(resolved["source"], "legacy")
        self.assertEqual(len(resolved["playlist_items"]), 19)

    def test_v2_folder_without_a_matching_day_fails_closed(self):
        with patch(
            "repositories.day_schedule_repository.get_module_day_for_folder",
            return_value=None,
        ), patch(
            "repositories.day_schedule_repository.get_schedule_snapshot_for_folder",
            return_value={
                "schedule_schema_version": 2,
                "schedule_snapshot_json": {
                    "schema_version": 2,
                    "days": [],
                },
            },
        ):
            with self.assertRaisesRegex(ValueError, "aucune journée valide"):
                resolve_folder_playlist(91)


if __name__ == "__main__":
    unittest.main()
