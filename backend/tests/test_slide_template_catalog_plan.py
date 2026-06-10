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
        self.assertIn("la matière décrit 2 ou 3 situations comparables", prompt)
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


if __name__ == "__main__":
    unittest.main()
