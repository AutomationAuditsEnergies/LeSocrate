import unittest
from unittest.mock import Mock, patch

from services import content_generation_service as cgs


class AudioTwoStageGenerationTest(unittest.TestCase):
    def test_break_is_generated_after_course_measurement_at_effective_duration(self):
        bloc = {
            "bloc_number": 1,
            "target_sec": 3600,
            "text": "texte complet du cours",
            "word_count": 4,
            "start_w": 0,
            "end_w": 4,
            "dirty": True,
            "contributing_seg_indices": {0},
            "word_budget": 8000,
            "filename": "course_01.mp3",
            "dynamic_schedule": True,
        }
        break_builder = Mock(return_value=(b"BREAK", "contextual_fish"))

        def measured_duration(audio_bytes):
            return 3300.0 if audio_bytes == b"COURSE" else 1200.0

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
                "text_content": bloc["text"],
                "word_count": 4,
                "dirty": 1,
            }]),
            patch.object(cgs, "_build_course_blocs_from_segments", return_value=([bloc], 4, "")),
            patch.object(cgs, "_playlist_items_for_platform", return_value=[
                ("course_01.mp3", 3600, "cours", 1),
                ("qa_01.mp3", 900, "qa", 1),
            ]),
            patch.object(cgs, "_find_next_folder_id", return_value=None),
            patch.object(cgs, "_course_opening_transitions_enabled", return_value=False),
            patch.object(cgs, "_fish_audio_course_workers", return_value=1),
            patch.object(cgs, "_synthesize_course_audio_to_fit", return_value=(
                b"COURSE", 3300.0, "natural", [],
            )),
            patch.object(cgs, "_build_contextual_break_audio", break_builder),
            patch.object(cgs, "_mp3_duration_seconds_no_ffprobe", side_effect=measured_duration),
            patch("services.azure_blob_service.upload_blob"),
            patch.object(cgs, "_mark_content_segments_clean"),
            patch.object(cgs, "_finalize_runtime_fit_carryover_and_clean", return_value=""),
            patch.object(cgs, "_save_course_script_plan") as save_plan,
            patch.object(cgs, "_save_content_artifact"),
            patch.object(cgs, "assert_course_day_word_budget", return_value={"ok": True}),
        ):
            result = cgs.generate_audio_from_script(
                123,
                force_all=True,
                mock=False,
                basic_tts=False,
                sync_slides=False,
                _allow_unsynced_course_audio_for_tests=True,
                next_folder_id=None,
                is_last_folder=True,
            )

        self.assertEqual(result["generated"], 2)
        self.assertEqual(break_builder.call_args.kwargs["duration_sec"], 1200)
        saved_payload = save_plan.call_args.args[2]
        manifest = saved_payload["adaptive_playback_manifest"]
        self.assertEqual(
            [segment["effective_duration_sec"] for segment in manifest["segments"]],
            [3300, 1200],
        )


if __name__ == "__main__":
    unittest.main()
