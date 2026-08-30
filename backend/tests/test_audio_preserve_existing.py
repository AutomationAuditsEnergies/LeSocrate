import unittest
from unittest.mock import patch

from services import content_generation_service as cgs


class AudioPreserveExistingTest(unittest.TestCase):
    def test_sync_generation_fails_before_upload_when_no_slide_can_be_bound(self):
        bloc = {
            "bloc_number": 1,
            "target_sec": 100,
            "text": "texte du bloc courant",
            "word_count": 4,
            "start_w": 0,
            "end_w": 4,
            "dirty": True,
            "contributing_seg_indices": {0},
            "word_budget": 20,
            "filename": "course_01.mp3",
            "dynamic_schedule": True,
        }
        deck = {
            "deck_id": 77,
            "slides": [{
                "slide_id": "other-course",
                "source_text": "aucune correspondance avec le texte courant",
                "source_ref": {
                    "word_start": 100,
                    "word_end": 120,
                    "segments": [{"course_number": 2}],
                },
            }],
            "pipeline_debug": {},
            "audio_sync": {},
        }

        with (
            patch.object(cgs, "get_job_from_db", return_value={
                "id": 42,
                "platform_id": 7,
                "status": "completed",
                "formation_job_id": 99,
            }),
            patch.object(cgs, "_load_saved_course_script_plan", return_value={}),
            patch.object(cgs, "list_completed_content_segment_rows", return_value=[{
                "sub_part_index": 0,
                "passe": 1,
                "text_content": "texte source complet",
                "word_count": 3,
                "dirty": 1,
            }]),
            patch.object(cgs, "_build_course_blocs_from_segments", return_value=([bloc], 4, "")),
            patch.object(cgs, "_playlist_items_for_platform", return_value=[
                ("course_01.mp3", 100, "cours", 1),
            ]),
            patch.object(cgs, "_find_next_folder_id", return_value=None),
            patch.object(cgs, "assert_course_day_word_budget", return_value={"ok": True}),
            patch(
                "services.script_slide_generation_service.get_latest_script_slide_deck",
                return_value=deck,
            ),
            patch(
                "services.script_slide_generation_service.is_script_slide_deck_usable",
                return_value=True,
            ),
            patch.object(cgs, "_synthesize_course_audio_synced_to_slides") as synth,
            patch("services.azure_blob_service.upload_blob") as upload_blob,
        ):
            with self.assertRaisesRegex(ValueError, "aucune diapositive"):
                cgs.generate_audio_from_script(
                    123,
                    force_all=True,
                    basic_tts=True,
                    # Even a legacy/new caller asking for no synchronization
                    # is forced through the production slide contract.
                    sync_slides=False,
                    auto_generate_slides=False,
                    next_folder_id=None,
                    is_last_folder=True,
                )

        synth.assert_not_called()
        upload_blob.assert_not_called()

    def test_single_course_regeneration_keeps_other_course_timings(self):
        def bloc(number):
            return {
                "bloc_number": number,
                "target_sec": 100,
                "text": f"texte du bloc {number}",
                "word_count": 4,
                "start_w": (number - 1) * 4,
                "end_w": number * 4,
                "dirty": False,
                "contributing_seg_indices": {0},
                "word_budget": 20,
                "filename": f"course_{number:02d}.mp3",
                "dynamic_schedule": True,
            }

        blocs = [bloc(1), bloc(2)]
        deck = {
            "deck_id": 77,
            "slides": [
                {"slide_id": "s1", "source_ref": {"word_start": 0, "word_end": 4}},
                {"slide_id": "s2", "source_ref": {"word_start": 4, "word_end": 8}},
            ],
            "pipeline_debug": {},
            "audio_sync": {
                "generated_files": ["course_01.mp3", "course_02.mp3"],
                "timings": [
                    {
                        "slide_id": "s1",
                        "audio_filename": "course_01.mp3",
                        "start_time": 0,
                        "end_time": 40,
                    },
                    {
                        "slide_id": "s2",
                        "audio_filename": "course_02.mp3",
                        "start_time": 0,
                        "end_time": 40,
                    },
                ],
            },
        }
        persisted_payloads = []

        def persist(_deck_id, payload):
            persisted_payloads.append(payload)
            return {**deck, "audio_sync": payload}

        synth = unittest.mock.Mock(return_value=(
            b"fresh-mp3",
            40.0,
            "edge",
            [],
            [{
                "slide_id": "s2",
                "audio_filename": "course_02.mp3",
                "start_time": 0,
                "end_time": 40,
            }],
            [],
            [],
        ))

        with (
            patch.object(cgs, "get_job_from_db", return_value={
                "id": 42,
                "platform_id": 7,
                "status": "completed",
                "formation_job_id": 99,
            }),
            patch.object(cgs, "_load_saved_course_script_plan", return_value={}),
            patch.object(cgs, "list_completed_content_segment_rows", return_value=[{
                "sub_part_index": 0,
                "passe": 1,
                "text_content": "texte source complet",
                "word_count": 3,
                "dirty": 0,
            }]),
            patch.object(cgs, "_build_course_blocs_from_segments", return_value=(blocs, 8, "")),
            patch.object(cgs, "_playlist_items_for_platform", return_value=[
                ("course_01.mp3", 100, "cours", 1),
                ("course_02.mp3", 100, "cours", 2),
            ]),
            patch.object(cgs, "_find_next_folder_id", return_value=None),
            patch.object(cgs, "_course_opening_transitions_enabled", return_value=False),
            patch.object(
                cgs,
                "_build_slide_audio_chunks",
                side_effect=lambda audio_bloc, _slides: [{
                    "slide_id": f"s{audio_bloc['bloc_number']}",
                    "word_start": audio_bloc["start_w"],
                    "word_end": audio_bloc["end_w"],
                    "text": audio_bloc["text"],
                }],
            ),
            patch.object(cgs, "_synthesize_course_audio_synced_to_slides", synth),
            patch.object(cgs, "_mp3_duration_seconds_no_ffprobe", return_value=40.0),
            patch("services.azure_blob_service.upload_blob"),
            patch.object(cgs, "_finalize_runtime_fit_carryover_and_clean", return_value=""),
            patch.object(cgs, "_save_course_script_plan"),
            patch.object(cgs, "_save_content_artifact"),
            patch.object(cgs, "assert_course_day_word_budget", return_value={"ok": True}),
            patch(
                "services.script_slide_generation_service.get_latest_script_slide_deck",
                return_value=deck,
            ),
            patch(
                "services.script_slide_generation_service.is_script_slide_deck_usable",
                return_value=True,
            ),
            patch(
                "services.script_slide_generation_service.update_script_slide_deck_audio_sync",
                side_effect=persist,
            ),
        ):
            result = cgs.generate_audio_from_script(
                123,
                force_all=False,
                basic_tts=True,
                sync_slides=True,
                auto_generate_slides=True,
                target_filename="course_02.mp3",
                next_folder_id=None,
                is_last_folder=True,
            )

        final_sync = persisted_payloads[-1]
        timings_by_file = {
            timing["audio_filename"] for timing in final_sync["timings"]
        }
        self.assertEqual(timings_by_file, {"course_01.mp3", "course_02.mp3"})
        self.assertEqual(result["generated"], 1)
        synth.assert_called_once()
        self.assertEqual(synth.call_args.kwargs["platform_id"], 7)

    def test_preserve_existing_skips_existing_audio_even_when_force_all(self):
        bloc = {
            "bloc_number": 1,
            "target_sec": 2700,
            "text": "texte du bloc",
            "word_count": 3,
            "start_w": 0,
            "end_w": 3,
            "dirty": True,
            "contributing_seg_indices": {0},
            "word_budget": 8000,
            "filename": "cours_9h00_9h45.mp3",
        }

        synth = unittest.mock.Mock(return_value=(b"mp3", 10.0, "mock", [], [], [], []))

        with (
            patch.object(
                cgs,
                "get_job_from_db",
                return_value={
                    "id": 42,
                    "platform_id": 7,
                    "status": "completed",
                    "formation_job_id": 99,
                },
            ),
            patch.object(cgs, "_load_saved_course_script_plan", return_value={}),
            patch.object(
                cgs,
                "list_completed_content_segment_rows",
                return_value=[
                    {
                        "sub_part_index": 0,
                        "passe": 1,
                        "text_content": "texte du bloc",
                        "word_count": 3,
                        "dirty": 1,
                    }
                ],
            ),
            patch.object(
                cgs,
                "_build_course_blocs_from_segments",
                return_value=([bloc], 3, ""),
            ),
            patch.object(
                cgs,
                "_playlist_items_for_platform",
                return_value=[("cours_9h00_9h45.mp3", 2700, "cours", 1)],
            ),
            patch.object(cgs, "_find_next_folder_id", return_value=None),
            patch.object(cgs, "_course_opening_transitions_enabled", return_value=False),
            patch.object(cgs, "_synthesize_course_audio_synced_to_slides", synth),
            patch("services.azure_blob_service.blob_exists", return_value=True),
            patch("services.azure_blob_service.download_blob", return_value=b"valid-mp3"),
            patch(
                "services.audio_asset_validation_service.validate_mp3_bytes",
                return_value={"duration_seconds": 2400.0},
            ),
            patch("services.azure_blob_service.upload_blob") as upload_blob,
            patch.object(cgs, "_finalize_runtime_fit_carryover_and_clean", return_value=""),
            patch.object(cgs, "_save_course_script_plan"),
            patch.object(cgs, "_save_content_artifact"),
            patch.object(cgs, "assert_course_day_word_budget", return_value={"ok": True}),
        ):
            result = cgs.generate_audio_from_script(
                123,
                force_all=True,
                preserve_existing=True,
                mock=False,
                basic_tts=True,
                sync_slides=False,
                _allow_unsynced_course_audio_for_tests=True,
                next_folder_id=None,
                is_last_folder=True,
            )

        self.assertEqual(result["generated"], 0)
        self.assertEqual(result["skipped"], 1)
        synth.assert_not_called()
        upload_blob.assert_not_called()

    def test_preserve_existing_regenerates_a_corrupt_blob(self):
        bloc = {
            "bloc_number": 1,
            "target_sec": 2700,
            "text": "texte du bloc",
            "word_count": 3,
            "start_w": 0,
            "end_w": 3,
            "dirty": True,
            "contributing_seg_indices": {0},
            "word_budget": 8000,
            "filename": "course_01.mp3",
        }
        synth = unittest.mock.Mock(
            return_value=(b"fresh-mp3", 10.0, "edge", [], [], [], [])
        )

        with (
            patch.object(
                cgs,
                "get_job_from_db",
                return_value={
                    "id": 42,
                    "platform_id": 7,
                    "status": "completed",
                    "formation_job_id": 99,
                },
            ),
            patch.object(cgs, "_load_saved_course_script_plan", return_value={}),
            patch.object(
                cgs,
                "list_completed_content_segment_rows",
                return_value=[{
                    "sub_part_index": 0,
                    "passe": 1,
                    "text_content": "texte du bloc",
                    "word_count": 3,
                    "dirty": 1,
                }],
            ),
            patch.object(
                cgs,
                "_build_course_blocs_from_segments",
                return_value=([bloc], 3, ""),
            ),
            patch.object(
                cgs,
                "_playlist_items_for_platform",
                return_value=[("course_01.mp3", 2700, "cours", 1)],
            ),
            patch.object(cgs, "_find_next_folder_id", return_value=None),
            patch.object(cgs, "_course_opening_transitions_enabled", return_value=False),
            patch.object(cgs, "_synthesize_course_audio_synced_to_slides", synth),
            patch("services.azure_blob_service.blob_exists", return_value=True),
            patch("services.azure_blob_service.download_blob", return_value=b"broken"),
            patch(
                "services.audio_asset_validation_service.validate_mp3_bytes",
                side_effect=ValueError("Audio invalide"),
            ),
            patch("services.azure_blob_service.upload_blob") as upload_blob,
            patch.object(cgs, "_finalize_runtime_fit_carryover_and_clean", return_value=""),
            patch.object(cgs, "_save_course_script_plan"),
            patch.object(cgs, "_save_content_artifact"),
            patch.object(cgs, "assert_course_day_word_budget", return_value={"ok": True}),
        ):
            result = cgs.generate_audio_from_script(
                123,
                force_all=True,
                preserve_existing=True,
                mock=False,
                basic_tts=True,
                sync_slides=False,
                _allow_unsynced_course_audio_for_tests=True,
                next_folder_id=None,
                is_last_folder=True,
            )

        self.assertEqual(result["generated"], 1)
        self.assertEqual(result["skipped"], 0)
        synth.assert_called_once()
        upload_blob.assert_called_once()


if __name__ == "__main__":
    unittest.main()
