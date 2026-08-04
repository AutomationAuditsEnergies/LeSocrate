import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from config import FRANCE_TZ
from services import audio_service
from services.day_playlist_service import build_playlist_items


def _valid_v2_blocks():
    specifications = [
        ("course", None, 60),
        ("qa", None, 10),
        ("pause", "short", 10),
        ("course", None, 60),
        ("qa", None, 10),
        ("pause", "lunch", 60),
        ("course", None, 60),
        ("qa", None, 10),
        ("pause", "short", 10),
        ("course", None, 60),
        ("qa", None, 10),
    ]
    cursor = 9 * 60
    blocks = []
    for position, (block_type, pause_kind, duration) in enumerate(
        specifications,
        start=1,
    ):
        blocks.append(
            {
                "position": position,
                "block_type": block_type,
                "pause_kind": pause_kind,
                "start_minute": cursor,
                "end_minute": cursor + duration,
                "duration_minutes": duration,
            }
        )
        cursor += duration
    return blocks


def _resolved_manifest(module_day_id=404):
    blocks = _valid_v2_blocks()
    return {
        "schema_version": 2,
        "source": "module_day",
        "folder_id": 52,
        "module_day_id": module_day_id,
        "blocks": blocks,
        "playlist_items": build_playlist_items(blocks),
    }


class DynamicOccurrenceAudioTest(unittest.TestCase):
    def test_v2_occurrence_streams_course_qa_and_pauses_in_locked_order(self):
        occurrence = {
            "module_day_id": 404,
            "session_index": 2,
        }

        with (
            patch(
                "repositories.pipeline_repository."
                "list_course_folder_ids_for_platform",
                return_value=[51, 52],
            ),
            patch(
                "services.day_playlist_service.resolve_folder_playlist",
                side_effect=lambda folder_id: (
                    _resolved_manifest()
                    if folder_id == 52
                    else {
                        "schema_version": 2,
                        "module_day_id": 303,
                        "blocks": _valid_v2_blocks(),
                        "playlist_items": build_playlist_items(
                            _valid_v2_blocks()
                        ),
                    }
                ),
            ),
        ):
            playlist = audio_service.get_course_session_playlist(
                12,
                occurrence,
            )

        self.assertEqual(
            [item["type"] for item in playlist],
            [
                "cours",
                "qa",
                "pause",
                "cours",
                "qa",
                "pause_midi",
                "cours",
                "qa",
                "pause",
                "cours",
                "qa",
            ],
        )
        self.assertEqual(
            [item["block_key"] for item in playlist[:4]],
            ["course_01", "qa_01", "pause_01", "course_02"],
        )
        self.assertTrue(
            all(item["module_day_id"] == 404 for item in playlist)
        )
        self.assertTrue(all(item["folder_id"] == 52 for item in playlist))

    def test_v2_occurrence_applies_its_immutable_adaptive_timeline(self):
        occurrence = {
            "module_day_id": 404,
            "session_index": 1,
            "audio_storage_prefix": "course-sessions/701",
        }
        adaptive_manifest = {
            "schema_version": 1,
            "segments": [
                {
                    "filename": "course_01.mp3",
                    "asset_duration_sec": 3180.8,
                    "effective_start_sec": 0,
                    "effective_duration_sec": 3180,
                    "effective_end_sec": 3180,
                },
                {
                    "filename": "qa_01.mp3",
                    "asset_duration_sec": 600.1,
                    "effective_start_sec": 3180,
                    "effective_duration_sec": 1020,
                    "effective_end_sec": 4200,
                    "elastic": True,
                },
            ],
        }

        with (
            patch(
                "repositories.pipeline_repository."
                "list_course_folder_ids_for_platform",
                return_value=[52],
            ),
            patch(
                "services.day_playlist_service.resolve_folder_playlist",
                return_value=_resolved_manifest(),
            ),
            patch(
                "services.adaptive_playback_service."
                "load_occurrence_playback_manifest",
                return_value=adaptive_manifest,
            ) as load_manifest,
        ):
            playlist = audio_service.get_course_session_playlist(12, occurrence)

        self.assertEqual(playlist[0]["duration"], 3180)
        self.assertEqual(playlist[0]["asset_duration"], 3180.8)
        self.assertEqual(playlist[1]["duration"], 1020)
        self.assertTrue(playlist[1]["elastic"])
        load_manifest.assert_called_once_with(12, "course-sessions/701")

    def test_server_clock_moves_through_v2_manifest_in_the_same_order(self):
        occurrence = {
            "module_day_id": 404,
            "session_index": 1,
        }
        start = FRANCE_TZ.localize(datetime(2026, 9, 1, 9, 0))
        resolved = _resolved_manifest()
        with (
            patch(
                "repositories.pipeline_repository."
                "list_course_folder_ids_for_platform",
                return_value=[52],
            ),
            patch(
                "services.day_playlist_service.resolve_folder_playlist",
                return_value=resolved,
            ),
        ):
            course = audio_service.get_course_session_audio_info(
                12,
                start,
                now=start + timedelta(seconds=12),
                occurrence=occurrence,
            )
            qa = audio_service.get_course_session_audio_info(
                12,
                start,
                now=start + timedelta(seconds=3600),
                occurrence=occurrence,
            )
            pause = audio_service.get_course_session_audio_info(
                12,
                start,
                now=start + timedelta(seconds=4200),
                occurrence=occurrence,
            )
            next_course = audio_service.get_course_session_audio_info(
                12,
                start,
                now=start + timedelta(seconds=4800),
                occurrence=occurrence,
            )

        self.assertEqual(course[0]["block_key"], "course_01")
        self.assertEqual(course[1], 12)
        self.assertEqual(qa[0]["block_key"], "qa_01")
        self.assertEqual(qa[1], 0)
        self.assertEqual(pause[0]["block_key"], "pause_01")
        self.assertEqual(next_course[0]["block_key"], "course_02")

    def test_v2_missing_manifest_never_calls_legacy_playlist(self):
        occurrence = {
            "module_day_id": 404,
            "session_index": 1,
        }
        with (
            patch(
                "repositories.pipeline_repository."
                "list_course_folder_ids_for_platform",
                return_value=[],
            ),
            patch.object(audio_service, "get_playlist") as legacy,
        ):
            with self.assertRaisesRegex(
                audio_service.CourseSessionPlaylistUnavailable,
                "Aucun dossier audio",
            ):
                audio_service.get_course_session_playlist(12, occurrence)

        legacy.assert_not_called()

    def test_explicit_v2_occurrence_without_module_day_never_uses_legacy_playlist(self):
        occurrence = {
            "module_day_id": None,
            "local_date": "2026-09-01",
            "session_index": 1,
        }
        with patch.object(audio_service, "get_playlist") as legacy:
            with self.assertRaisesRegex(
                audio_service.CourseSessionPlaylistUnavailable,
                "n'est pas liée à une journée pédagogique V2",
            ):
                audio_service.get_course_session_playlist(12, occurrence)

        legacy.assert_not_called()

    def test_v2_corrupt_manifest_never_calls_legacy_playlist(self):
        occurrence = {
            "module_day_id": 404,
            "session_index": 1,
        }
        corrupt = _resolved_manifest()
        corrupt["playlist_items"] = corrupt["playlist_items"][:-1]
        with (
            patch(
                "repositories.pipeline_repository."
                "list_course_folder_ids_for_platform",
                return_value=[52],
            ),
            patch(
                "services.day_playlist_service.resolve_folder_playlist",
                return_value=corrupt,
            ),
            patch.object(audio_service, "get_playlist") as legacy,
        ):
            with self.assertRaisesRegex(
                audio_service.CourseSessionPlaylistUnavailable,
                "Manifeste V2 invalide",
            ):
                audio_service.get_course_session_playlist(12, occurrence)

        legacy.assert_not_called()

    def test_v1_occurrence_keeps_the_historic_platform_playlist(self):
        legacy_playlist = [{"id": 1, "filename": "legacy.mp3"}]
        with patch.object(
            audio_service,
            "get_playlist",
            return_value=legacy_playlist,
        ) as legacy:
            result = audio_service.get_course_session_playlist(
                12,
                {"module_day_id": None, "session_index": 1},
            )

        self.assertIs(result, legacy_playlist)
        legacy.assert_called_once_with(12)

    def test_current_playback_context_uses_v2_occurrence_manifest(self):
        start = FRANCE_TZ.localize(datetime(2026, 9, 1, 9, 0))
        occurrence = {
            "id": 701,
            "platform_id": 12,
            "module_day_id": 404,
            "session_index": 1,
            "scheduled_at": start,
            "status": "active",
        }
        playlist = [
            {
                "id": 1,
                "filename": "course_01.mp3",
                "duration": 3600,
                "title": "Cours 1",
                "type": "cours",
                "folder_id": 52,
                "module_day_id": 404,
            }
        ]
        with (
            patch.object(audio_service, "get_heure_debut_cours", return_value=start),
            patch.object(
                audio_service,
                "get_current_simulated_time",
                return_value=start + timedelta(seconds=30),
            ),
            patch.object(
                audio_service,
                "_current_v2_occurrence",
                return_value=occurrence,
            ),
            patch.object(
                audio_service,
                "get_course_session_playlist",
                return_value=playlist,
            ) as v2_playlist,
            patch.object(audio_service, "get_playlist") as legacy_playlist,
            patch.object(audio_service, "get_current_audio_info") as legacy_info,
        ):
            context = audio_service.get_current_playback_context(12)

        self.assertEqual(context["schedule_schema_version"], 2)
        self.assertIs(context["occurrence"], occurrence)
        self.assertIs(context["playlist"], playlist)
        self.assertEqual(context["audio_info"]["filename"], "course_01.mp3")
        self.assertEqual(context["offset"], 30)
        v2_playlist.assert_called_once_with(12, occurrence)
        legacy_playlist.assert_not_called()
        legacy_info.assert_not_called()

    def test_current_v2_occurrence_matches_the_room_clock_not_another_day(self):
        start = FRANCE_TZ.localize(datetime(2026, 9, 8, 9, 0))
        other_day = {
            "id": 700,
            "module_day_id": 303,
            "scheduled_at": start - timedelta(days=7),
            "status": "active",
        }
        expected = {
            "id": 701,
            "module_day_id": 404,
            "scheduled_at": start,
            "status": "planned",
        }
        with patch(
            "repositories.course_schedule_repository.list_course_sessions",
            return_value=[other_day, expected],
        ):
            occurrence = audio_service._current_v2_occurrence(12, start)

        self.assertIs(occurrence, expected)

    def test_current_v2_occurrence_keeps_incomplete_explicit_day_fail_closed(self):
        start = FRANCE_TZ.localize(datetime(2026, 9, 8, 9, 0))
        expected = {
            "id": 701,
            "module_day_id": None,
            "local_date": "2026-09-08",
            "scheduled_at": start,
            "status": "planned",
        }
        with patch(
            "repositories.course_schedule_repository.list_course_sessions",
            return_value=[expected],
        ):
            occurrence = audio_service._current_v2_occurrence(12, start)

        self.assertIs(occurrence, expected)

    def test_current_playback_context_keeps_v1_functions_unchanged(self):
        start = FRANCE_TZ.localize(datetime(2026, 9, 1, 9, 0))
        legacy_audio = {
            "id": 1,
            "filename": "legacy.mp3",
            "duration": 3600,
            "title": "Cours historique",
            "type": "cours",
        }
        with (
            patch.object(audio_service, "get_heure_debut_cours", return_value=start),
            patch.object(audio_service, "_current_v2_occurrence", return_value=None),
            patch.object(
                audio_service,
                "get_current_simulated_time",
                return_value=start + timedelta(seconds=30),
            ),
            patch.object(
                audio_service,
                "get_current_audio_info",
                return_value=(legacy_audio, 30, 0),
            ) as legacy_info,
            patch.object(
                audio_service,
                "get_playlist",
                return_value=[legacy_audio],
            ) as legacy_playlist,
        ):
            context = audio_service.get_current_playback_context(12)

        self.assertEqual(context["schedule_schema_version"], 1)
        self.assertIsNone(context["occurrence"])
        self.assertEqual(context["playlist"], [legacy_audio])
        self.assertIs(context["audio_info"], legacy_audio)
        legacy_info.assert_called_once_with(12)
        legacy_playlist.assert_called_once_with(12)


if __name__ == "__main__":
    unittest.main()
