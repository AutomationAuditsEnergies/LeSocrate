import unittest

from services.teacher_preparation_service import build_teacher_preparation_state


class TeacherPreparationServiceTest(unittest.TestCase):
    def test_running_pipeline_is_exposed_as_a_simple_product_state(self):
        state = build_teacher_preparation_state(
            platform_status="pending",
            pipeline_status="tts_launched",
            pipeline_step="slides",
            source_formation_id=71,
        )

        self.assertEqual(state["status"], "preparing")
        self.assertEqual(state["stage"], "Création des slides")
        self.assertEqual(state["progress"], 97)
        self.assertFalse(state["can_retry"])

    def test_failure_hides_internal_error_and_allows_resume(self):
        state = build_teacher_preparation_state(
            platform_status="pending",
            pipeline_status="error",
            pipeline_step="content",
            pipeline_error="provider secret details",
            source_formation_id=71,
        )

        self.assertEqual(state, {
            "status": "failed",
            "progress": 72,
            "stage": "Préparation interrompue",
            "can_retry": True,
        })
        self.assertNotIn("provider", str(state))

    def test_ready_is_only_exposed_at_a_terminal_checkpoint(self):
        preparing = build_teacher_preparation_state(
            platform_status="pending",
            pipeline_status="tts_launched",
            pipeline_step="post_review_docs",
            source_formation_id=71,
        )
        ready = build_teacher_preparation_state(
            platform_status="ready",
            pipeline_status="text_ready",
            pipeline_step="done",
            source_formation_id=71,
        )

        self.assertEqual(preparing["status"], "preparing")
        self.assertLess(preparing["progress"], 100)
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["progress"], 100)

    def test_reuse_clone_has_a_dedicated_stage(self):
        state = build_teacher_preparation_state(
            platform_status="pending",
            pipeline_status="text_ready",
            pipeline_step="done",
            source_formation_id=71,
            source_module_id=12,
        )

        self.assertEqual(state["stage"], "Copie des cours")
        self.assertEqual(state["progress"], 55)


if __name__ == "__main__":
    unittest.main()
