import unittest
from unittest.mock import patch

from services import script_annotation_service as annotations
from services import script_rules_service as rules


class ScriptReviewBlobStorageTest(unittest.TestCase):
    def test_legacy_rules_path_is_migrated_to_blob_on_read(self):
        context = {"platform_id": 16, "job_id": 13}
        locator = (
            "azureblob://pipeline-artifacts/platform-16/folder-118/"
            "script-reviews/regles-folder-118-job-13.md"
        )
        row = {
            "rules_markdown": "# Règles\n\n## Règle 1",
            "rules_count": 1,
            "source_annotations_count": 2,
            "model": "deepseek-v4-pro",
            "markdown_path": "/home/tts_script_reviews/regles-folder-118-job-13.md",
        }
        with patch.object(rules, "_fetch_context", return_value=context), patch.object(
            rules,
            "_ensure_rules_table",
        ), patch.object(
            rules,
            "get_script_rules_row",
            return_value=row,
        ), patch.object(
            rules,
            "_rules_markdown_path",
            return_value=locator,
        ), patch.object(
            rules,
            "save_script_review_markdown",
            return_value=locator,
        ) as save_markdown, patch.object(
            rules,
            "update_script_rules_markdown_path",
        ) as update_path:
            result = rules.get_rules(118)

        self.assertEqual(result["markdown_path"], locator)
        save_markdown.assert_called_once()
        update_path.assert_called_once_with(
            folder_id=118,
            job_id=13,
            markdown_path=locator,
        )

    def test_annotation_markdown_persists_blob_locator_in_repository(self):
        context = {"platform_id": 16, "job_id": 13}
        locator = (
            "azureblob://pipeline-artifacts/platform-16/folder-118/"
            "script-reviews/tts-script-review-folder-118-job-13.md"
        )
        with patch.object(
            annotations,
            "build_script_annotations_markdown",
            return_value=("# Revue\n", "unused"),
        ), patch.object(
            annotations,
            "list_script_annotations",
            return_value={"context": context, "annotations": [], "markdown_path": locator},
        ), patch.object(
            annotations,
            "save_script_review_markdown",
            return_value=locator,
        ) as save_markdown, patch.object(
            annotations,
            "_ensure_annotations_table",
        ), patch.object(
            annotations,
            "update_script_annotations_markdown_path",
        ) as update_path:
            result = annotations.write_script_annotations_markdown(118)

        self.assertEqual(result, locator)
        save_markdown.assert_called_once_with(
            16,
            118,
            "tts-script-review-folder-118-job-13.md",
            "# Revue\n",
        )
        update_path.assert_called_once_with(
            folder_id=118,
            job_id=13,
            markdown_path=locator,
        )

    def test_manual_rules_persist_blob_locator_in_repository(self):
        context = {"platform_id": 16, "job_id": 13}
        locator = (
            "azureblob://pipeline-artifacts/platform-16/folder-118/"
            "script-reviews/regles-folder-118-job-13.md"
        )
        with patch.object(rules, "_fetch_context", return_value=context), patch.object(
            rules,
            "save_script_review_markdown",
            return_value=locator,
        ) as save_markdown, patch.object(
            rules,
            "_ensure_rules_table",
        ), patch.object(
            rules,
            "upsert_manual_script_rules",
        ) as upsert_rules, patch.object(
            rules,
            "get_rules",
            return_value={"markdown_path": locator},
        ):
            result = rules.update_rules_markdown(118, "# Règles\n\n## Règle 1\n")

        self.assertEqual(result["markdown_path"], locator)
        save_markdown.assert_called_once_with(
            16,
            118,
            "regles-folder-118-job-13.md",
            "# Règles\n\n## Règle 1\n",
        )
        upsert_rules.assert_called_once_with(
            folder_id=118,
            job_id=13,
            rules_markdown="# Règles\n\n## Règle 1",
            rules_count=1,
            markdown_path=locator,
        )


if __name__ == "__main__":
    unittest.main()
