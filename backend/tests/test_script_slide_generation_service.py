import unittest
from unittest.mock import patch

from services import script_slide_generation_service as slides


def _anchored_segment(index: int) -> dict:
    return {
        "segment_id": index,
        "sub_part_index": 0,
        "sub_part_name": "Cours test",
        "passe": 1,
        "text": f"Texte source de la slide {index}. Il contient une intention visuelle distincte.",
        "beat_id": f"beat-{index}",
        "beat_type": "concept",
        "beat_role": f"Role {index}",
        "spoken_requirement": f"Exigence orale {index}",
        "slide_anchor_id": f"anchor-{index}",
        "template_type": "reflection",
        "slide_anchor": {
            "enabled": True,
            "anchor_id": f"anchor-{index}",
            "template_type": "reflection",
            "visual_goal": f"Visualiser le point {index}",
        },
        "source_alignment": "draft_beat_aligned",
    }


def _fake_generate_batch(blocks, _source_title, _model, _pace_profile, max_batch_slides):
    batch_slides = []
    for block in blocks[:max_batch_slides]:
        anchor = (block.get("slide_anchors") or [{}])[0]
        batch_slides.append({
            "source_block_id": block["source_block_id"],
            "template_type": "reflection",
            "event_type": "concept",
            "event_summary": f"Slide {block['source_block_id']}",
            "importance": 3,
            "data": {
                "title": f"Slide {block['source_block_id']}",
                "text": "Point ancre.",
            },
            "slide_anchor_id": anchor.get("anchor_id"),
            "beat_id": anchor.get("beat_id") or "",
            "source_quote": block.get("text") or "",
        })
    return batch_slides, {"template_backlog": [], "curation_enabled": True}


class ScriptSlideGenerationServiceTest(unittest.TestCase):
    def test_anchor_count_raises_requested_max_slides(self):
        source = {
            "folder_id": 10,
            "content_job_id": 20,
            "platform_id": 1,
            "folder_name": "Jour test",
            "program_title": "Formation test",
            "segments": [_anchored_segment(idx) for idx in range(84)],
            "beat_aligned": True,
            "beat_aligned_segments": 84,
            "beat_aligned_anchors": 84,
        }

        with patch.object(slides, "_generate_batch", side_effect=_fake_generate_batch):
            result = slides._run_slide_generation_from_source(
                source,
                job_id=99,
                max_slides=60,
                pace="normal",
                model="test-model",
                persist=False,
            )

        self.assertEqual(len(result["slides"]), 84)
        self.assertEqual(result["stats"]["max_slides_requested"], 60)
        self.assertEqual(result["stats"]["max_slides"], 84)
        self.assertEqual(result["stats"]["slide_anchors_found"], 84)
        self.assertEqual(result["stats"]["slides_dropped_by_cap"], 0)

    def test_cap_preserves_anchored_slides_before_unanchored(self):
        anchored = [
            {
                "slide_anchor_id": f"anchor-{idx}",
                "importance": 1,
            }
            for idx in range(3)
        ]
        unanchored = [
            {
                "slide_anchor_id": None,
                "importance": 5,
            }
            for _ in range(3)
        ]

        capped, dropped = slides._cap_planned_slides(anchored + unanchored, 3)

        self.assertEqual(dropped, 3)
        self.assertEqual([slide.get("slide_anchor_id") for slide in capped], [
            "anchor-0",
            "anchor-1",
            "anchor-2",
        ])


if __name__ == "__main__":
    unittest.main()
