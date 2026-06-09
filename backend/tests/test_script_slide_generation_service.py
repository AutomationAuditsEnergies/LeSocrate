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


def _strict_block(index: int) -> dict:
    return {
        "source_block_id": index,
        "word_start": index * 100,
        "word_end": index * 100 + 80,
        "word_count": 80,
        "sub_part_index": 0,
        "sub_part_name": "Cours test",
        "text": f"Texte source aligné pour anchor {index}. Il doit rester associé à sa slide.",
        "source_refs": [],
        "slide_anchors": [
            {
                "anchor_id": f"strict-anchor-{index}",
                "beat_id": f"strict-beat-{index}",
                "template_type": "reflection",
                "visual_goal": f"Visualiser le segment {index}",
            }
        ],
        "source_alignment": "section_slide_alignment",
        "section_alignment": {"status": "llm"},
    }


def _unanchored_conclusion_block(index: int) -> dict:
    return {
        "source_block_id": index,
        "word_start": index * 100,
        "word_end": index * 100 + 90,
        "word_count": 90,
        "sub_part_index": 0,
        "sub_part_name": "Cours test · conclusion du cours",
        "text": (
            "Bien. Prenons un peu de recul. Nous avons posé une posture claire. "
            "Nous avons aussi structuré l'action avec une méthode progressive. "
            "Ce qu'il faut retenir, c'est l'alliance entre posture et méthode."
        ),
        "source_refs": [
            {
                "course_number": 1,
                "part_number": 5,
                "section_label": "conclusion du cours",
                "slide_anchor_id": "",
            }
        ],
        "slide_anchors": [],
        "source_alignment": "section_unanchored",
        "section_alignment": {"status": "unanchored"},
    }


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

    def test_batch_error_fallback_preserves_strict_anchor_slides(self):
        strict_blocks = [_strict_block(index) for index in range(4)]
        anchors = [block["slide_anchors"][0] for block in strict_blocks]
        source = {
            "folder_id": 10,
            "content_job_id": 20,
            "platform_id": 1,
            "folder_name": "Jour test",
            "program_title": "Formation test",
            "segments": [{"text": "Texte source."}],
        }

        with patch.object(slides, "_extract_slide_anchors_from_plan", return_value=anchors), \
             patch.object(slides, "_build_section_aligned_source_blocks", return_value=(strict_blocks, 400, {})), \
             patch.object(slides, "_generate_batch", side_effect=RuntimeError("boom")):
            result = slides._run_slide_generation_from_source(
                source,
                job_id=99,
                max_slides=2,
                pace="normal",
                model="test-model",
                persist=False,
                content_plan={"courses": []},
            )

        self.assertEqual(len(result["slides"]), 4)
        self.assertGreaterEqual(result["stats"]["max_slides"], 4)
        self.assertEqual(result["stats"]["strict_anchor_fallback_slides"], 4)
        self.assertEqual(
            [slide.get("slide_anchor_id") for slide in result["slides"]],
            [f"strict-anchor-{index}" for index in range(4)],
        )

    def test_section_alignment_retries_with_temperature_zero_before_fallback(self):
        section = {
            "course_number": 1,
            "course_title": "Cours test",
            "section_label": "partie 1",
            "part_number": 1,
        }
        units = [
            {"unit_id": 0, "word_count": 10, "word_start": 0, "word_end": 10, "text": "Premier mouvement."},
            {"unit_id": 1, "word_count": 12, "word_start": 10, "word_end": 22, "text": "Deuxième mouvement."},
        ]
        anchors = [
            {"anchor_id": "a1", "beat_id": "b1", "template_type": "reflection"},
            {"anchor_id": "a2", "beat_id": "b2", "template_type": "reflection"},
        ]
        temperatures = []

        def fake_post_message(*_args, **kwargs):
            temperatures.append(kwargs.get("temperature"))
            if len(temperatures) == 1:
                return '{"assignments":[{"anchor_id":"a1","unit_start":0,"unit_end":0}]}'
            return '{"assignments":[{"anchor_id":"a1","unit_start":0,"unit_end":0},{"anchor_id":"a2","unit_start":1,"unit_end":1}]}'

        with patch.object(slides, "post_message", side_effect=fake_post_message):
            assignments, debug = slides._align_section_to_slide_anchors(section, units, anchors, "test-model")

        self.assertEqual(debug["status"], "llm_retry")
        self.assertEqual(debug["attempts"], 2)
        self.assertEqual(temperatures, [None, 0])
        self.assertEqual([assignment["anchor_id"] for assignment in assignments], ["a1", "a2"])

    def test_section_unanchored_slide_keeps_full_block_range(self):
        block = _unanchored_conclusion_block(3)
        slide = {
            "source_block_id": 3,
            "template_type": "recap",
            "event_type": "recap",
            "event_summary": "Ce qu'on retient",
            "data": {"title": "Ce qu'on retient", "points": ["Posture", "Méthode"]},
            "slide_anchor_id": None,
            "beat_id": "",
            "anchor_role": "",
            "source_quote": "Nous avons posé une posture claire.",
            "importance": 2,
        }

        final = slides._build_final_slide(slide, block, 0)

        self.assertEqual(final["source_ref"]["word_start"], block["word_start"])
        self.assertEqual(final["source_ref"]["word_end"], block["word_end"])
        self.assertEqual(final["source_ref"]["selection_method"], "section_unanchored")
        self.assertIn("highlight_word_start", final["source_ref"])

    def test_unanchored_conclusion_repair_adds_missing_slide(self):
        strict_block = _strict_block(0)
        unanchored_block = _unanchored_conclusion_block(1)
        anchors = [strict_block["slide_anchors"][0]]
        source = {
            "folder_id": 10,
            "content_job_id": 20,
            "platform_id": 1,
            "folder_name": "Jour test",
            "program_title": "Formation test",
            "segments": [{"text": "Texte source."}],
        }

        def generate_only_strict(blocks, _source_title, _model, _pace_profile, _max_batch_slides):
            return [_fake_generate_batch([blocks[0]], _source_title, _model, _pace_profile, 1)[0][0]], {
                "template_backlog": [],
                "curation_enabled": True,
            }

        with patch.object(slides, "_extract_slide_anchors_from_plan", return_value=anchors), \
             patch.object(slides, "_build_section_aligned_source_blocks", return_value=([strict_block, unanchored_block], 190, {})), \
             patch.object(slides, "_generate_batch", side_effect=generate_only_strict):
            result = slides._run_slide_generation_from_source(
                source,
                job_id=99,
                max_slides=1,
                pace="normal",
                model="test-model",
                persist=False,
                content_plan={"courses": []},
            )

        self.assertEqual(result["stats"]["coverage_repair_slides_inserted"], 1)
        self.assertEqual([slide["source_ref"]["source_block_id"] for slide in result["slides"]], [0, 1])
        self.assertEqual(result["slides"][1]["template_type"], "recap")
        self.assertIsNone(result["slides"][1].get("slide_anchor_id"))
        self.assertEqual(result["slides"][1]["source_ref"]["word_start"], unanchored_block["word_start"])
        self.assertEqual(result["slides"][1]["source_ref"]["word_end"], unanchored_block["word_end"])


if __name__ == "__main__":
    unittest.main()
