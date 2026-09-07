import unittest
from unittest.mock import patch

from services import content_generation_service as cgs


def _course_plan(course_number: int) -> dict:
    return {
        "course_number": course_number,
        "course_title": f"Cours {course_number}",
        "filename": f"course_{course_number:02d}.mp3",
        "duration_minutes": 45,
        "target_words": 6,
        "opening": {
            "title": "Introduction",
            "target_words": 2,
        },
        "parts": [
            {
                "part_number": 1,
                "title": "Partie",
                "target_words": 4,
            }
        ],
    }


class StructuredCourseCheckpointTests(unittest.TestCase):
    def test_late_failure_reuses_finished_course_and_intermediate_bodies(self):
        plan = {
            "version": "test-v1",
            "courses": [_course_plan(1), _course_plan(2)],
        }
        job = {
            "id": 91,
            "formation_job_id": 17,
            "platform_id": 3,
            "program_title": "TP checkpoint",
            "program_text": "Programme stable",
            "folder_position": 0,
            "nb_days": 1,
            "total_hours": 7,
        }
        playlist = [
            ("course_01.mp3", 2700, "cours", 1),
            ("course_02.mp3", 2700, "cours", 2),
        ]
        plan_store = {}
        segment_rows = {}
        body_calls = []
        micro_calls = []
        fail_course_two = {"enabled": True}

        def load_plan(_job_id):
            return dict(plan_store) if plan_store else None

        def save_plan(*, job_id, plan_input_signature, structured_plan):
            self.assertEqual(job_id, job["id"])
            plan_store.update({
                "plan_input_signature": plan_input_signature,
                "structured_course_plan": structured_plan,
            })

        def save_checkpoint(
            *,
            job_id,
            sub_part_index,
            sub_part_name,
            passe,
            checkpoint_signature,
            checkpoint_phase,
            checkpoint_payload,
            text_content="",
            word_count=0,
        ):
            payload = {**checkpoint_payload, "phase": checkpoint_phase}
            segment_rows[sub_part_index] = {
                "id": sub_part_index + 1,
                "sub_part_index": sub_part_index,
                "sub_part_name": sub_part_name,
                "passe": passe,
                "status": (
                    "completed"
                    if checkpoint_phase == "final_completed"
                    else f"structured_{checkpoint_phase}"
                ),
                "text_content": text_content,
                "word_count": word_count,
                "structured_checkpoint_signature": checkpoint_signature,
                "checkpoint_payload": payload,
            }

        def list_checkpoints(_job_id):
            return [dict(row) for _, row in sorted(segment_rows.items())]

        def delete_stale(*, job_id, checkpoint_signature, valid_sub_part_indexes):
            self.assertEqual(job_id, job["id"])
            valid = set(valid_sub_part_indexes)
            stale = [
                index
                for index, row in segment_rows.items()
                if (
                    index not in valid
                    or row["structured_checkpoint_signature"] != checkpoint_signature
                )
            ]
            for index in stale:
                segment_rows.pop(index)
            return len(stale)

        def generate_body(*, course_plan, **_kwargs):
            course_number = int(course_plan["course_number"])
            body_calls.append(course_number)
            text = f"Corps stable du cours {course_number}"
            return {
                "course_number": course_number,
                "course_plan": course_plan,
                "body_text": text,
                "body_sections": [{
                    "kind": "part",
                    "part_number": 1,
                    "title": "Partie",
                    "target_words": 4,
                    "text": text,
                    "word_count": 5,
                }],
                "module_content": "",
            }

        def summarize(body_result, **_kwargs):
            course_number = int(body_result["course_number"])
            return course_number, f"Résumé stable {course_number}"

        def opening(*, body_result, **_kwargs):
            course_number = int(body_result["course_number"])
            text = f"Introduction du cours {course_number}"
            return {
                "course_number": course_number,
                "record": {
                    "kind": "opening",
                    "title": "Introduction",
                    "target_words": 2,
                    "text": text,
                    "word_count": 4,
                },
                "text": text,
            }

        def calibrate(*, draft, **_kwargs):
            text = draft["course_text"]
            return text, {
                "status": "ok",
                "changed": False,
                "min_words": 1,
                "max_words": 100,
                "calibrated_sections": draft["sections"],
            }

        def micro_review(*, course_plan, section_text, return_details=False, **_kwargs):
            course_number = int(course_plan["course_number"])
            micro_calls.append(course_number)
            if course_number == 2 and fail_course_two["enabled"]:
                raise RuntimeError("échec tardif simulé")
            if return_details:
                return {
                    "text": section_text,
                    "applied": [],
                    "rejected": [],
                    "status": "clean",
                }
            return section_text

        common_patches = [
            patch.object(cgs, "_playlist_items_for_platform", return_value=playlist),
            patch.object(cgs, "_generate_structured_course_plan", return_value=plan),
            patch.object(
                cgs,
                "_validate_structured_course_plan",
                return_value={"ok": True, "errors": [], "warnings": []},
            ),
            patch.object(cgs, "load_structured_content_plan_checkpoint", side_effect=load_plan),
            patch.object(cgs, "save_structured_content_plan_checkpoint", side_effect=save_plan),
            patch.object(cgs, "list_structured_content_checkpoint_rows", side_effect=list_checkpoints),
            patch.object(cgs, "delete_stale_structured_content_checkpoints", side_effect=delete_stale),
            patch.object(cgs, "save_structured_content_checkpoint", side_effect=save_checkpoint),
            patch.object(cgs, "_structured_course_parallel_workers", return_value=1),
            patch.object(cgs, "_generate_structured_course_body", side_effect=generate_body),
            patch.object(cgs, "_summarize_structured_course_body", side_effect=summarize),
            patch.object(cgs, "_generate_late_opening_for_structured_course", side_effect=opening),
            patch.object(
                cgs,
                "_run_plan_adherence_on_generated_drafts",
                side_effect=lambda **kwargs: kwargs["body_results"],
            ),
            patch.object(cgs, "_calibrate_structured_course_sections", side_effect=calibrate),
            patch.object(
                cgs,
                "_structured_course_budget_status",
                side_effect=lambda _plan, text: {
                    "ok": True,
                    "status": "ok",
                    "words": cgs.count_tts_spoken_words(text),
                    "target_words": 6,
                    "min_words": 1,
                },
            ),
            patch.object(cgs, "_run_ethical_micro_review_for_section", side_effect=micro_review),
            patch.object(cgs, "_log_content_pipeline_event"),
            patch.object(cgs, "_load_content_artifact", return_value=None),
            patch.object(cgs, "_save_content_artifact"),
            patch.object(cgs, "_save_course_script_plan"),
            patch.object(cgs, "_update_job_db"),
            patch.object(cgs, "_assemble_and_upload", return_value=(18, "final.txt")),
        ]

        for current_patch in common_patches:
            current_patch.start()
            self.addCleanup(current_patch.stop)

        with self.assertRaisesRegex(RuntimeError, "échec tardif simulé"):
            cgs._run_structured_content_generation(
                job=dict(job),
                folder_id=41,
                platform_id=3,
                sub_parts=["Cours 1", "Cours 2"],
                module_contents={},
            )

        self.assertEqual(segment_rows[0]["status"], "completed")
        self.assertEqual(
            segment_rows[1]["checkpoint_payload"]["phase"],
            "body_completed",
        )

        fail_course_two["enabled"] = False
        result = cgs._run_structured_content_generation(
            job=dict(job),
            folder_id=41,
            platform_id=3,
            sub_parts=["Cours 1", "Cours 2"],
            module_contents={},
        )

        self.assertEqual(result[0:2], (18, "final.txt"))
        self.assertEqual(body_calls, [1, 2])
        self.assertEqual(set(segment_rows), {0, 1})
        self.assertTrue(all(row["status"] == "completed" for row in segment_rows.values()))
        for row in segment_rows.values():
            checkpoint_payload = row["checkpoint_payload"]
            self.assertNotIn("body_result", checkpoint_payload)
            self.assertNotIn("draft", checkpoint_payload["final_result"])
            self.assertNotIn("course_plan", checkpoint_payload["final_result"])
        self.assertGreater(micro_calls.count(2), 1)


if __name__ == "__main__":
    unittest.main()
