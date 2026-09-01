import unittest
from unittest.mock import patch

from services import content_generation_service as content


def _section_with_anchors() -> dict:
    return {
        "kind": "part",
        "part_number": 2,
        "teaching_beats": [
            {
                "beat_id": "c1p2b1",
                "type": "idee_forte",
                "role": "Poser le principe.",
                "spoken_requirement": "Nommer le principe.",
                "slide_anchor": {
                    "enabled": True,
                    "template_type": "reflection",
                    "pedagogical_shape": "idee_forte",
                },
            },
            {
                "beat_id": "c1p2b2",
                "type": "triade_structurante",
                "role": "Donner trois repères.",
                "spoken_requirement": "Nommer les trois repères.",
                "slide_anchor": {
                    "enabled": True,
                    "template_type": "situations",
                    "pedagogical_shape": "triade_structurante",
                    "items_expected": 3,
                },
            },
        ],
    }


class SlideDisplayMapTest(unittest.TestCase):
    def test_parse_strips_block_and_keeps_entries(self):
        raw = """On traite l'affaire avec calme. Trois repères suivent.

===ORDRE_AFFICHAGE_SLIDES===
c1p2b1, c1p2b2
===CARTE_AFFICHAGE_SLIDES===
c1p2b1 | ANCRAGE: "On traite l'affaire avec calme"
c1p2b2 | ANCRAGE: "Trois repères suivent" | ITEMS: clarté; écoute; constance
===FIN_CARTE===
"""

        clean, entries, errors = content._parse_slide_display_map(raw)

        self.assertEqual(clean, "On traite l'affaire avec calme. Trois repères suivent.")
        self.assertEqual(errors, [])
        self.assertEqual([entry["beat_id"] for entry in entries], ["c1p2b1", "c1p2b2"])
        self.assertEqual(entries[1]["items"], ["clarté", "écoute", "constance"])
        self.assertNotIn("CARTE_AFFICHAGE_SLIDES", clean)

    def test_parse_strips_map_without_order_marker(self):
        raw = """On traite l'affaire avec calme.

===CARTE_AFFICHAGE_SLIDES===
c1p2b1 | ANCRAGE: "On traite l'affaire avec calme"
c1p2b2 | ANCRAGE: "Trois repères suivent" | ITEMS: clarté; écoute; constance
===FIN_CARTE===
"""

        clean, entries, errors, order = content._parse_slide_display_map_with_order(raw)

        self.assertEqual(clean, "On traite l'affaire avec calme.")
        self.assertEqual(errors, [])
        self.assertEqual(order, [])
        self.assertEqual([entry["beat_id"] for entry in entries], ["c1p2b1", "c1p2b2"])
        self.assertNotIn("CARTE_AFFICHAGE_SLIDES", clean)

    def test_fit_section_strips_residual_display_map_leak(self):
        raw = """On traite l'affaire avec calme.

===CARTE_AFFICHAGE_SLIDES===
c1p2b1 | ANCRAGE: "On traite l'affaire avec calme"
"""

        clean = content._fit_generated_section_to_budget(raw, 200)

        self.assertEqual(clean, "On traite l'affaire avec calme.")
        self.assertNotIn("ANCRAGE", clean)

    def test_validate_accepts_typographic_apostrophe_and_nbsp(self):
        section = _section_with_anchors()
        text = "On traite l’affaire\u00a0avec calme. Trois repères suivent: clarté, écoute, constance."
        entries = [
            {"beat_id": "c1p2b1", "anchor_text": "On traite l'affaire avec calme", "quote": "", "items": []},
            {
                "beat_id": "c1p2b2",
                "anchor_text": "Trois repères suivent",
                "quote": "",
                "items": ["clarté", "écoute", "constance"],
            },
        ]

        validated, errors = content._validate_slide_display_map(section, entries, text)

        self.assertEqual(errors, [])
        self.assertEqual([entry["status"] for entry in validated], ["ok", "ok"])

    def test_validate_reports_duplicate_anchor(self):
        section = _section_with_anchors()
        text = "Même phrase repère. Même phrase repère. Trois repères suivent."
        entries = [
            {"beat_id": "c1p2b1", "anchor_text": "Même phrase repère", "quote": "", "items": []},
            {
                "beat_id": "c1p2b2",
                "anchor_text": "Trois repères suivent",
                "quote": "",
                "items": ["clarté", "écoute", "constance"],
            },
        ]

        _validated, errors = content._validate_slide_display_map(section, entries, text)

        self.assertIn("ambiguous_anchor:c1p2b1", errors)

    def test_validate_does_not_match_inside_longer_token(self):
        section = _section_with_anchors()
        text = "On traite l'affaire calmement. Trois repères suivent: clarté, écoute, constance."
        entries = [
            {"beat_id": "c1p2b1", "anchor_text": "calme", "quote": "", "items": []},
            {
                "beat_id": "c1p2b2",
                "anchor_text": "Trois repères suivent",
                "quote": "",
                "items": ["clarté", "écoute", "constance"],
            },
        ]

        _validated, errors = content._validate_slide_display_map(section, entries, text)

        self.assertIn("missing_anchor:c1p2b1", errors)

    def test_validate_drops_missing_quote_without_failing_anchor(self):
        section = _section_with_anchors()
        text = "On traite l'affaire avec calme. Trois repères suivent."
        entries = [
            {
                "beat_id": "c1p2b1",
                "anchor_text": "On traite l'affaire avec calme",
                "quote": "Phrase absente du texte",
                "items": [],
            },
            {
                "beat_id": "c1p2b2",
                "anchor_text": "Trois repères suivent",
                "quote": "",
                "items": ["clarté", "écoute", "constance"],
            },
        ]

        validated, errors = content._validate_slide_display_map(section, entries, text)

        self.assertEqual(errors, [])
        self.assertEqual(validated[0]["quote"], "")

    def test_prepare_missing_block_fails_without_exception(self):
        section = _section_with_anchors()
        raw = "On traite l'affaire avec calme. Trois repères suivent."

        with patch.object(content, "_repair_slide_display_map_block", return_value=None):
            payload = content._prepare_slide_display_map_for_section(section, raw)

        self.assertEqual(payload["text"], raw)
        self.assertEqual(payload["display_map_status"], "failed")
        self.assertIn("missing_block", payload["display_map_errors"])

    def test_thread_display_map_relocates_anchor_through_patch(self):
        before = (
            "Premier repère à afficher avec musique claire. "
            "Trois repères suivent: clarté, écoute, constance."
        )
        patches = [{"original": "musique claire", "replacement": "formulation claire"}]
        after, applied, _rejected = content._apply_patches(before, patches)
        section = {
            **_section_with_anchors(),
            "text": before,
            "display_map_status": "ok",
            "slide_display_map": [
                {
                    "beat_id": "c1p2b1",
                    "anchor_text": "Premier repère à afficher avec musique claire",
                    "quote": "",
                    "items": [],
                    "status": "ok",
                },
                {
                    "beat_id": "c1p2b2",
                    "anchor_text": "Trois repères suivent",
                    "quote": "",
                    "items": ["clarté", "écoute", "constance"],
                    "status": "ok",
                },
            ],
            "display_map_errors": [],
        }

        threaded = content._thread_slide_display_map_through_patches(
            section,
            before_text=before,
            after_text=after,
            applied_patches=applied,
            pass_name="micro_review",
        )

        self.assertEqual(threaded["display_map_status"], "relocated_patch")
        self.assertEqual(
            threaded["slide_display_map"][0]["anchor_text"],
            "Premier repère à afficher avec formulation claire.",
        )
        self.assertEqual(threaded["slide_display_map"][0]["status"], "relocated_patch")

    def test_thread_display_map_relocates_quote_through_patch(self):
        before = (
            "Retenez cette phrase: on promet toujours un résultat clair. "
            "Trois repères suivent: clarté, écoute, constance."
        )
        patches = [{
            "original": "on promet toujours un résultat clair",
            "replacement": "on annonce toujours un cadre clair",
        }]
        after, applied, _rejected = content._apply_patches(before, patches)
        section = {
            **_section_with_anchors(),
            "text": before,
            "display_map_status": "ok",
            "slide_display_map": [
                {
                    "beat_id": "c1p2b1",
                    "anchor_text": "Retenez cette phrase",
                    "quote": "on promet toujours un résultat clair",
                    "items": [],
                    "status": "ok",
                },
                {
                    "beat_id": "c1p2b2",
                    "anchor_text": "Trois repères suivent",
                    "quote": "",
                    "items": ["clarté", "écoute", "constance"],
                    "status": "ok",
                },
            ],
            "display_map_errors": [],
        }

        threaded = content._thread_slide_display_map_through_patches(
            section,
            before_text=before,
            after_text=after,
            applied_patches=applied,
            pass_name="micro_review",
        )

        self.assertEqual(threaded["display_map_status"], "relocated_patch")
        self.assertEqual(threaded["slide_display_map"][0]["anchor_text"], "Retenez cette phrase")
        self.assertEqual(threaded["slide_display_map"][0]["quote"], "on annonce toujours un cadre clair.")
        self.assertEqual(threaded["slide_display_map"][0]["status"], "relocated_patch")

    def test_thread_display_map_keeps_map_when_patch_is_elsewhere(self):
        before = (
            "On traite l'affaire avec calme. "
            "Trois repères suivent: clarté, écoute, constance. "
            "La conclusion mentionne une musique claire."
        )
        patches = [{"original": "musique claire", "replacement": "formulation claire"}]
        after, applied, _rejected = content._apply_patches(before, patches)
        section = {
            **_section_with_anchors(),
            "text": before,
            "display_map_status": "ok",
            "slide_display_map": [
                {
                    "beat_id": "c1p2b1",
                    "anchor_text": "On traite l'affaire avec calme",
                    "quote": "",
                    "items": [],
                    "status": "ok",
                },
                {
                    "beat_id": "c1p2b2",
                    "anchor_text": "Trois repères suivent",
                    "quote": "",
                    "items": ["clarté", "écoute", "constance"],
                    "status": "ok",
                },
            ],
            "display_map_errors": [],
        }

        threaded = content._thread_slide_display_map_through_patches(
            section,
            before_text=before,
            after_text=after,
            applied_patches=applied,
            pass_name="micro_review",
        )

        self.assertEqual(threaded["display_map_status"], "ok")
        self.assertEqual(
            threaded["slide_display_map"][0]["anchor_text"],
            "On traite l'affaire avec calme",
        )


if __name__ == "__main__":
    unittest.main()
