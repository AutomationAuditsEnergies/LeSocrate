import sys
import types
import unittest
from unittest.mock import patch

from services.hr_playlist_pipeline_service import handle_hr_playlist_work_item
from services.pipeline_queue.contracts import WorkItem


class _Lease:
    def __init__(self):
        self.progress = []
        self.checkpoints = 0

    def report_progress(self, value):
        self.progress.append(dict(value))

    def checkpoint(self):
        self.checkpoints += 1


def _item(attempt=1):
    return WorkItem(
        id="11111111-1111-1111-1111-111111111111",
        pipeline_job_id=None,
        folder_id=118,
        resource_key="folder:118",
        run_id="run-118",
        task_type="hr_playlist_item",
        scope_key="hr_audio:118",
        dedupe_key="folder:118:audio:run-118",
        payload={
            "folder_id": 118,
            "platform_id": 16,
            "filename": "cours_9h00_9h45.mp3",
            "voice_type": "gtts",
            "voice_label": "gTTS",
            "sync_slides": False,
            "auto_generate_slides": False,
        },
        status="running",
        priority=0,
        attempt_count=attempt,
        max_attempts=5,
        available_at=None,
        lease_owner="worker",
        lease_token="22222222-2222-2222-2222-222222222222",
        lease_version=attempt,
        lease_expires_at=None,
        last_error=None,
        result={},
        created_at=None,
        updated_at=None,
    )


class HrPlaylistQueueHandlerTest(unittest.TestCase):
    def test_retry_resumes_item_without_regenerating_existing_audio(self):
        calls = []
        content = types.ModuleType("services.content_generation_service")

        def generate(folder_id, **kwargs):
            calls.append((folder_id, kwargs))
            kwargs["on_progress"](1, 1, "Audio généré")
            return {"generated": 0, "skipped": 1}

        content.generate_audio_from_script = generate
        lease = _Lease()
        with patch(
            "services.hr_playlist_pipeline_service.get_course_folder_identity",
            return_value={
                "id": 118,
                "platform_id": 16,
                "formation_job_id": None,
            },
        ), patch.dict(
            sys.modules,
            {"services.content_generation_service": content},
        ), patch(
            "services.hr_playlist_pipeline_service._publish",
            return_value={"published": ["cours_9h00_9h45.mp3"]},
        ):
            result = handle_hr_playlist_work_item(_item(attempt=2), lease)

        self.assertTrue(calls[0][1]["preserve_existing"])
        self.assertGreaterEqual(len(lease.progress), 2)
        self.assertEqual(lease.progress[-1]["step"], 1)
        self.assertEqual(lease.checkpoints, 1)
        self.assertEqual(result.result["status"], "completed")
        self.assertEqual(result.result["result"]["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
