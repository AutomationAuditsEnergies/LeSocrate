import json
import os
import unittest
from unittest.mock import patch

from services import content_generation_service as cgs


def _course_plan():
    return {
        "course_number": 1,
        "course_title": "Relation client",
    }


def _section():
    return {
        "kind": "course_calibrated",
        "title": "Voix et écoute",
    }


class EthicalLexicalScanTest(unittest.TestCase):
    def test_scan_uses_full_lexical_rules(self):
        findings = cgs._scan_ethical_lexical_findings(
            "La musique de la voix peut influencer la perception.",
            max_findings=10,
        )

        self.assertIn(2, cgs._ETHICAL_MICRO_RULE_IDS)
        self.assertTrue(
            any(finding["rule_id"] == 2 and finding["match"].lower() == "musique" for finding in findings)
        )

    def test_micro_review_rules_include_all_sixteen_categories(self):
        rules_text = cgs._load_ethical_micro_rules_text()

        for rule_id in range(1, 17):
            self.assertIn(f"RÈGLE #{rule_id}", rules_text)
        self.assertIn("musique", rules_text)

    def test_scan_matches_music_derivatives(self):
        findings = cgs._scan_ethical_lexical_findings(
            "Une ambiance musicale et un musicien fictif apparaissent dans l'exemple.",
            max_findings=10,
        )
        matches = {finding["match"].lower() for finding in findings}

        self.assertIn("musicale", matches)
        self.assertIn("musicien", matches)

    def test_lexical_rewrite_accepts_rule_two_patch(self):
        raw = json.dumps({
            "patches": [
                {
                    "original": "La musique de la voix compte.",
                    "replacement": "Le rythme de la voix compte.",
                    "rule_violated": "#2",
                    "reason": "Terme interdit reformulé.",
                }
            ]
        })

        with patch.object(cgs, "_anthropic_post", return_value=raw):
            result = cgs._run_ethical_lexical_rewrite_for_section(
                job={"id": 1, "formation_job_id": 1},
                course_plan=_course_plan(),
                section=_section(),
                section_text="La musique de la voix compte.",
            )

        self.assertEqual(result["text"], "Le rythme de la voix compte.")
        self.assertEqual(result["residual_findings"], [])
        self.assertEqual(len(result["applied"]), 1)
        self.assertEqual(result["applied"][0]["lexical_rule_id"], 2)

    def test_lexical_rewrite_iterates_on_residual_findings(self):
        responses = [
            json.dumps({
                "patches": [
                    {
                        "original": "La musique de la voix compte.",
                        "replacement": "Le rythme de la voix compte.",
                        "rule_violated": "#2",
                        "reason": "Premier terme interdit reformulé.",
                    }
                ]
            }),
            json.dumps({
                "patches": [
                    {
                        "original": "Cette musique revient.",
                        "replacement": "Ce motif revient.",
                        "rule_violated": "#2",
                        "reason": "Résidu reformulé.",
                    }
                ]
            }),
        ]

        with patch.dict(
            os.environ,
            {
                "FORMATION_ETHICAL_LEXICAL_MAX_PATCHES": "1",
                "FORMATION_ETHICAL_LEXICAL_MAX_ITERATIONS": "2",
            },
            clear=False,
        ), patch.object(cgs, "_anthropic_post", side_effect=responses) as post:
            result = cgs._run_ethical_lexical_rewrite_for_section(
                job={"id": 1, "formation_job_id": 1},
                course_plan=_course_plan(),
                section=_section(),
                section_text="La musique de la voix compte. Cette musique revient.",
            )

        self.assertEqual(post.call_count, 2)
        self.assertNotIn("musique", result["text"].lower())
        self.assertEqual(result["residual_findings"], [])
        self.assertEqual(len(result["applied"]), 2)

    def test_confidence_assurance_exception_still_allowed(self):
        findings = cgs._scan_ethical_lexical_findings(
            "Avec de la pratique, la personne prend de l'assurance au téléphone.",
            max_findings=10,
        )

        self.assertFalse(any(finding["match"].lower() == "assurance" for finding in findings))


if __name__ == "__main__":
    unittest.main()
