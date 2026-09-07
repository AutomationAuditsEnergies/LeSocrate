import json
import unittest

from services import content_generation_service as content
from services import script_slide_generation_service as slides


class SlideTemplateCatalogPlanTest(unittest.TestCase):
    def test_plan_catalog_contains_plan_signals_not_curation_signals(self):
        prompt = content._slide_template_catalog_prompt()

        self.assertIn('"plan_signals"', prompt)
        self.assertIn('"pedagogical_shape"', prompt)
        self.assertIn('"plan_avoid"', prompt)
        self.assertIn("la matière décrit 2 à 4 situations comparables", prompt)
        self.assertNotIn('"strong_signals"', prompt)
        self.assertNotIn('"rejection_rules"', prompt)

    def test_curation_catalog_contains_curation_signals_not_plan_signals(self):
        prompt = slides._template_catalog_for_prompt()

        self.assertIn('"strong_signals"', prompt)
        self.assertIn('"rejection_rules"', prompt)
        self.assertNotIn('"plan_signals"', prompt)
        self.assertNotIn('"plan_avoid"', prompt)

    def test_plan_signals_and_avoid_are_not_domain_specific(self):
        catalog = content._load_slide_template_catalog()
        forbidden = ("canal", "client", "téléphone", "courriel", "chat", "métier")
        offenders = []
        for item in catalog.get("templates") or []:
            values = []
            values.extend(item.get("plan_signals") or [])
            if item.get("plan_avoid"):
                values.append(item["plan_avoid"])
            haystack = " ".join(str(value).lower() for value in values)
            for term in forbidden:
                if term in haystack:
                    offenders.append((item.get("template_id"), term))

        self.assertEqual(offenders, [])

    def test_plan_catalog_json_is_valid(self):
        parsed = json.loads(content._slide_template_catalog_prompt())
        self.assertTrue(parsed.get("templates"))

    def test_late_course_opening_forces_reprise_recap_anchor(self):
        beats = content._opening_structure_teaching_beats(
            course_number=2,
            day_number=1,
            job={"folder_name": "Journée test", "program_title": "Formation test"},
            sub_parts=["Cours 1", "Cours 2"],
            raw_parts=[{"title": "Axe 1"}, {"title": "Axe 2"}],
            course_title="Cours 2",
            is_first_day=True,
        )

        self.assertGreaterEqual(len(beats), 2)
        recap = beats[0]
        self.assertEqual(recap["type"], "reprise_recap")
        self.assertEqual(recap["slide_anchor"]["template_type"], "reprise_recap")
        self.assertEqual(recap["slide_anchor"]["pedagogical_shape"], "synthese_de_reprise")
        self.assertEqual(beats[1]["slide_anchor"]["template_type"], "chapter_opener")


if __name__ == "__main__":
    unittest.main()
