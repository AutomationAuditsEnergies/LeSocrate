import unittest
from unittest.mock import patch

from services import formation_pipeline_service as fps


class ReacRetryTest(unittest.TestCase):
    def test_reac_retry_succeeds_on_third_attempt(self):
        events = []

        with patch.object(
            fps,
            "download_reac_text",
            side_effect=[RuntimeError("temp 1"), RuntimeError("temp 2"), "texte reac"],
        ) as download, patch.object(fps, "_cooperative_sleep") as sleep:
            text = fps.download_reac_text_with_retry(
                "12345",
                attempts=3,
                delays_sec=[0, 0],
                on_attempt=lambda **payload: events.append(payload),
            )

        self.assertEqual(text, "texte reac")
        self.assertEqual(download.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual([e["status"] for e in events].count("retrying"), 2)
        self.assertEqual(events[-1]["status"], "success")

    def test_reac_retry_fails_clearly_after_three_attempts(self):
        events = []

        with patch.object(
            fps,
            "download_reac_text",
            side_effect=RuntimeError("france competences indisponible"),
        ), patch.object(fps, "_cooperative_sleep"):
            with self.assertRaisesRegex(RuntimeError, "3 tentatives"):
                fps.download_reac_text_with_retry(
                    "12345",
                    attempts=3,
                    delays_sec=[0, 0],
                    on_attempt=lambda **payload: events.append(payload),
                )

        self.assertEqual(events[-1]["status"], "failed")
        self.assertIn("france competences", events[-1]["error"])


if __name__ == "__main__":
    unittest.main()
