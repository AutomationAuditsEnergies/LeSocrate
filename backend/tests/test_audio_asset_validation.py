import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services.audio_asset_validation_service import (
    inspect_audio_sync_payload,
    inspect_mp3_blob,
    validate_mp3_bytes,
)
from services.day_playlist_service import is_course_audio_filename


class _Download:
    def __init__(self, payload):
        self.payload = payload

    def readall(self):
        return self.payload


class _BlobClient:
    def __init__(self, payload=b"x" * 600_000):
        self.payload = payload
        self.downloads = []

    def download_blob(self, offset=0, length=None):
        self.downloads.append((offset, length))
        end = None if length is None else offset + length
        return _Download(self.payload[offset:end])


class AudioAssetValidationTest(unittest.TestCase):
    def test_course_filename_contract_accepts_v1_and_v2(self):
        self.assertTrue(is_course_audio_filename("cours_9h00_9h45.mp3"))
        self.assertTrue(is_course_audio_filename("course_01.mp3"))
        self.assertTrue(is_course_audio_filename("COURSE-02.MP3?sig=x"))
        self.assertFalse(is_course_audio_filename("qa_01.mp3"))

    def test_small_v2_course_is_rejected_before_download(self):
        client = _BlobClient(b"x" * 50_000)
        props = SimpleNamespace(
            size=50_000,
            etag="small-v2",
            metadata={},
            content_settings=SimpleNamespace(content_type="audio/mpeg"),
        )

        result = inspect_mp3_blob(
            client,
            "course_01.mp3",
            props=props,
            expected_duration_seconds=2100,
        )

        self.assertFalse(result["ready"])
        self.assertEqual(result["reason"], "course_audio_too_small")
        self.assertEqual(client.downloads, [])

    def test_bounded_head_and_tail_validation_accepts_a_coherent_course(self):
        client = _BlobClient(b"x" * 2_000_000)
        props = SimpleNamespace(
            size=2_000_000,
            etag="valid-v2",
            metadata={"duration_seconds": "900"},
            content_settings=SimpleNamespace(content_type="audio/mpeg"),
        )

        with patch(
            "services.audio_asset_validation_service._measure_sample",
            return_value=30.0,
        ):
            result = inspect_mp3_blob(
                client,
                "course_01.mp3",
                props=props,
                expected_duration_seconds=2100,
            )

        self.assertTrue(result["ready"])
        self.assertEqual(result["estimated_duration_seconds"], 900.0)
        self.assertEqual(len(client.downloads), 2)

    def test_full_prepublication_validation_rejects_an_undersized_course(self):
        with self.assertRaisesRegex(ValueError, "trop petit"):
            validate_mp3_bytes(
                "course_01.mp3",
                b"not-enough",
                expected_duration_seconds=2100,
            )

    def test_sync_payload_rejects_timing_for_unknown_slide(self):
        deck = {
            "deck_id": 12,
            "slides": [{"slide_id": "slide-real"}],
            "audio_sync": {
                "timings": [{
                    "slide_id": "slide-deleted",
                    "audio_filename": "course_01.mp3",
                    "start_time": 0,
                    "end_time": 30,
                }],
            },
        }

        result = inspect_audio_sync_payload(
            deck,
            ["course_01.mp3"],
            require_all_slides=False,
        )

        self.assertFalse(result["ready"])
        self.assertEqual(result["missing_course_files"], ["course_01.mp3"])
        self.assertEqual(result["missing_slide_ids"], ["slide-real"])

    def test_single_file_sync_can_be_validated_without_other_slide_coverage(self):
        deck = {
            "deck_id": 13,
            "slides": [{"slide_id": "s1"}, {"slide_id": "s2"}],
            "audio_sync": {
                "timings": [{
                    "slide_id": "s1",
                    "audio_filename": "course_01.mp3",
                    "start_time": 0,
                    "end_time": 30,
                }],
            },
        }

        result = inspect_audio_sync_payload(
            deck,
            ["course_01.mp3"],
            require_all_slides=False,
        )

        self.assertTrue(result["ready"])
        self.assertEqual(result["missing_slide_ids"], ["s2"])


if __name__ == "__main__":
    unittest.main()
