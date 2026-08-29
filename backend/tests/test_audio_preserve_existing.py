import unittest
from unittest.mock import patch

from services import content_generation_service as cgs


class AudioPreserveExistingTest(unittest.TestCase):
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
                next_folder_id=None,
                is_last_folder=True,
            )

        self.assertEqual(result["generated"], 1)
        self.assertEqual(result["skipped"], 0)
        synth.assert_called_once()
        upload_blob.assert_called_once()


if __name__ == "__main__":
    unittest.main()
