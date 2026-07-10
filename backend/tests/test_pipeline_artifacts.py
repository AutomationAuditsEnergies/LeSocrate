import os
import tempfile
import unittest
from unittest.mock import patch

from services.content_pipeline import artifacts


class PipelineArtifactStorageTest(unittest.TestCase):
    def test_script_review_markdown_is_saved_to_private_blob(self):
        with patch.dict(
            os.environ,
            {
                "AZURE_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true",
                "PIPELINE_ARTIFACTS_REQUIRED": "1",
            },
            clear=True,
        ), patch(
            "services.azure_blob_service.ensure_private_container",
        ) as ensure_container, patch(
            "services.azure_blob_service.upload_blob",
        ) as upload_blob:
            locator = artifacts.save_script_review_markdown(
                16,
                118,
                "tts-script-review-folder-118-job-13.md",
                "# Revue\n",
            )

        self.assertEqual(
            locator,
            "azureblob://pipeline-artifacts/platform-16/folder-118/"
            "script-reviews/tts-script-review-folder-118-job-13.md",
        )
        ensure_container.assert_called_once_with("pipeline-artifacts")
        upload_blob.assert_called_once_with(
            "pipeline-artifacts",
            "platform-16/folder-118/script-reviews/"
            "tts-script-review-folder-118-job-13.md",
            b"# Revue\n",
        )

    def test_required_script_review_never_falls_back_to_local_disk(self):
        with patch.dict(
            os.environ,
            {"PIPELINE_ARTIFACTS_REQUIRED": "1"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "aucune chaîne de connexion"):
                artifacts.save_script_review_markdown(16, 118, "review.md", "# Revue\n")

    def test_local_script_review_fallback_is_independent_from_db_path(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "PIPELINE_ARTIFACTS_REQUIRED": "0",
                "PIPELINE_LOCAL_ARTIFACT_DIR": tmpdir,
            },
            clear=True,
        ):
            path = artifacts.save_script_review_markdown(
                2,
                3,
                "rules.md",
                "# Règles\n",
            )

            self.assertTrue(path.startswith(tmpdir))
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "# Règles\n")

    def test_save_retries_transient_blob_error(self):
        calls = []

        def upload(container, path, raw):
            calls.append((container, path, raw))
            if len(calls) == 1:
                raise RuntimeError("connection reset")

        with patch.dict(
            "os.environ",
            {"PIPELINE_BLOB_MAX_ATTEMPTS": "3", "PIPELINE_ARTIFACTS_REQUIRED": "1"},
            clear=False,
        ), patch(
            "services.azure_blob_service.ensure_private_container",
        ), patch(
            "services.azure_blob_service.upload_blob",
            side_effect=upload,
        ), patch(
            "services.content_pipeline.artifacts.time.sleep",
        ):
            artifacts.save_content_artifact(10, 20, "content-plan.json", {"ok": True})

        self.assertEqual(len(calls), 2)
        self.assertIn("platform-10/folder-20/playlist/content-plan.json", calls[-1][1])

    def test_required_artifact_failure_is_not_silently_ignored(self):
        with patch.dict(
            "os.environ",
            {"PIPELINE_BLOB_MAX_ATTEMPTS": "1", "PIPELINE_ARTIFACTS_REQUIRED": "1"},
            clear=False,
        ), patch(
            "services.azure_blob_service.ensure_private_container",
        ), patch(
            "services.azure_blob_service.upload_blob",
            side_effect=RuntimeError("storage unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "obligatoire non sauvegardé"):
                artifacts.save_content_artifact(10, 20, "content-plan.json", {"ok": True})

    def test_missing_artifact_is_a_normal_cache_miss(self):
        missing = RuntimeError("BlobNotFound: The specified blob does not exist")
        with patch.dict(
            "os.environ",
            {"PIPELINE_BLOB_MAX_ATTEMPTS": "3", "PIPELINE_ARTIFACTS_REQUIRED": "1"},
            clear=False,
        ), patch(
            "services.azure_blob_service.download_blob",
            side_effect=missing,
        ) as download:
            result = artifacts.load_content_artifact(10, 20, "content-plan.json")

        self.assertIsNone(result)
        self.assertEqual(download.call_count, 1)


if __name__ == "__main__":
    unittest.main()
