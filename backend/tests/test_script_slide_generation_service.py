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
            "pedagogical_shape": "idee_forte",
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
                "pedagogical_shape": "idee_forte",
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
    def test_section_aligned_prompt_keeps_anchor_template_as_weak_hint(self):
        prompt = slides._prompt_for_blocks(
            [_strict_block(1)],
            "Jour test",
            slides.PACE_PROFILES["normal"],
            max_batch_slides=1,
        )

        self.assertIn('"planned_template_type": "reflection"', prompt)
        self.assertIn('"planned_pedagogical_shape": "idee_forte"', prompt)
        self.assertIn("choisis librement le meilleur `template_type`", prompt)
        self.assertIn("planned_pedagogical_shape", prompt)
        self.assertIn("ne recopie pas automatiquement son template prévu", prompt)
        self.assertNotIn('"template_type": "reflection", "visual_goal"', prompt)

    def test_extract_slide_anchor_keeps_pedagogical_shape(self):
        plan = {
            "courses": [
                {
                    "course_number": 1,
                    "course_title": "Cours test",
                    "parts": [
                        {
                            "part_number": 2,
                            "title": "Posture",
                            "teaching_beats": [
                                {
                                    "beat_id": "c1p2b1",
                                    "type": "concept",
                                    "role": "présenter trois piliers de posture",
                                    "spoken_requirement": "Nommer les trois piliers.",
                                    "slide_anchor": {
                                        "enabled": True,
                                        "anchor_id": "c1p2b1-slide",
                                        "template_type": "situations",
                                        "pedagogical_shape": "triade_structurante",
                                        "visual_goal": "Faire retenir les trois piliers.",
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        }

        anchors = slides._extract_slide_anchors_from_plan(plan)

        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0]["template_type"], "situations")
        self.assertEqual(anchors[0]["pedagogical_shape"], "triade_structurante")

    def test_slide_curation_prompt_uses_real_catalog_decision_fields(self):
        prompt = slides._prompt_for_blocks(
            [_strict_block(1)],
            "Jour test",
            slides.PACE_PROFILES["normal"],
            max_batch_slides=1,
        )

        self.assertIn("`strong_signals`", prompt)
        self.assertIn("`rejection_rules`", prompt)
        self.assertIn("`confusable_with`", prompt)
        self.assertIn('"strong_signals"', prompt)
        self.assertIn('"rejection_rules"', prompt)
        self.assertIn('"confusable_with"', prompt)
        self.assertNotIn("`weak_signals`", prompt)
        self.assertNotIn("`selection_rules`", prompt)

    def test_slide_curation_prompt_requires_pedagogical_shape_before_template(self):
        prompt = slides._prompt_for_blocks(
            [_strict_block(1)],
            "Jour test",
            slides.PACE_PROFILES["normal"],
            max_batch_slides=1,
        )

        self.assertIn("TAXONOMIE `pedagogical_shape`", prompt)
        self.assertIn("- triade_structurante: situations", prompt)
        self.assertIn("Classe d'abord la fonction pédagogique", prompt)
        exact_format = prompt.split("FORMAT EXACT:", 1)[1]
        self.assertLess(
            exact_format.index('"pedagogical_shape"'),
            exact_format.index('"template_type"'),
        )

    def test_normalized_slide_keeps_template_decision_fields(self):
        block = _strict_block(2)
        raw = {
            "source_block_id": 2,
            "template_type": "reflection",
            "event_type": "reflection",
            "event_summary": "Principe clé",
            "pedagogical_shape": "idee_forte",
            "shape_evidence": "l'idée importante",
            "template_decision_reason": "Le passage isole une idée forte plutôt qu'une méthode.",
            "rejected_templates": [
                {"template": "tip", "why": "Pas de conseil directement actionnable."}
            ],
            "data": {"title": "Principe clé", "text": "Une idée à mémoriser."},
            "slide_anchor_id": "strict-anchor-2",
            "source_quote": block["text"],
        }

        normalized = slides._normalize_slide(raw, block)
        final = slides._build_final_slide(normalized, block, 0)

        self.assertEqual(normalized["pedagogical_shape"], "idee_forte")
        self.assertEqual(normalized["shape_evidence"], "l'idée importante")
        self.assertEqual(normalized["template_decision_reason"], "Le passage isole une idée forte plutôt qu'une méthode.")
        self.assertEqual(normalized["rejected_templates"], [
            {"template": "tip", "why": "Pas de conseil directement actionnable."}
        ])
        self.assertEqual(final["pedagogical_shape"], "idee_forte")
        self.assertEqual(final["rejected_templates"][0]["template"], "tip")

    def test_normalized_slide_inherits_anchor_pedagogical_shape(self):
        block = _strict_block(3)
        block["slide_anchors"][0]["template_type"] = "situations"
        block["slide_anchors"][0]["pedagogical_shape"] = "triade_structurante"
        raw = {
            "source_block_id": 3,
            "template_type": "situations",
            "event_type": "concept",
            "event_summary": "Trois postures",
            "data": {
                "title": "Trois postures",
                "items": [
                    {"title": "Écouter", "desc": "Accueillir le signal."},
                    {"title": "Reformuler", "desc": "Stabiliser la demande."},
                    {"title": "Confirmer", "desc": "Valider la suite."},
                ],
            },
            "slide_anchor_id": "strict-anchor-3",
            "source_quote": block["text"],
        }

        normalized = slides._normalize_slide(raw, block)

        self.assertEqual(normalized["pedagogical_shape"], "triade_structurante")

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

    def test_restored_template_names_map_to_source_exact_templates(self):
        expected = {
            "framework": "framework",
            "story": "story",
            "analogy": "analogy",
            "opinion": "opinion",
            "mots_a_bannir": "situations",
            "expressions_interdites": "situations",
            "blacklist_3": "situations",
            "bannir": "warning",
            "interdit": "warning",
            "piege": "warning",
            "transition": "reflection",
            "context": "reflection",
            "stats": "recap",
            "checklist": "recap",
            "decision_tree": "reflection",
            "channel_adaptation": "reflection",
            "script": "reflection",
            "matrix": "reflection",
        }

        for raw, canonical in expected.items():
            with self.subTest(raw=raw):
                self.assertEqual(slides._canonical_template(raw), canonical)

    def test_restored_template_data_is_normalized_for_source_exact_templates(self):
        template = slides._canonical_template("framework")
        self.assertEqual(template, "framework")

        framework = slides._normalize_slide_data(
            template,
            {
                "title": "Les 4 leviers",
                "center_title": "Performance",
                "items": [
                    {"title": "Volume", "desc": "Nombre de contacts."},
                    {"title": "Qualité", "desc": "Pertinence du message."},
                ],
            },
            "Fallback",
            "Texte source.",
        )
        self.assertEqual(framework["center"]["title"], "Performance")
        self.assertEqual(framework["segments"][0]["title"], "Volume")

    def test_recap_forbidden_expressions_reroutes_to_situations(self):
        block = {
            "source_block_id": 72,
            "word_start": 0,
            "word_end": 120,
            "word_count": 120,
            "sub_part_name": "Diagnostic",
            "text": (
                "Les trois expressions interdites qui sabotent la désescalade verbale : "
                "'Calmez-vous', 'Ne vous inquiétez pas' et 'Mais'."
            ),
            "slide_anchors": [
                {
                    "anchor_id": "c6p2b4-slide",
                    "beat_id": "c6p2b4",
                    "template_type": "recap",
                    "visual_goal": "Identifier les trois mots à bannir.",
                }
            ],
        }
        raw = {
            "template_type": "recap",
            "event_type": "recap",
            "event_summary": "Trois mots à bannir",
            "data": {
                "title": "Trois mots à bannir",
                "points": ["Calmez-vous", "Ne vous inquiétez pas", "Mais"],
            },
            "slide_anchor_id": "c6p2b4-slide",
            "source_quote": block["text"],
        }

        normalized = slides._normalize_slide(raw, block)

        self.assertEqual(normalized["template_type"], "situations")
        self.assertEqual(normalized["event_type"], "warning")
        self.assertEqual(len(normalized["data"]["items"]), 3)

    def test_recap_three_pillars_reroutes_to_situations(self):
        block = {
            "source_block_id": 7,
            "word_start": 3071,
            "word_end": 4165,
            "word_count": 1094,
            "sub_part_name": "Posture professionnelle",
            "text": (
                "Je vous propose de définir cette posture professionnelle autour de trois piliers. "
                "Ces trois piliers, les voici : la neutralité bienveillante, la courtoisie professionnelle, "
                "et la représentation de l'entreprise. Voilà pour les trois piliers."
            ),
            "slide_anchors": [
                {
                    "anchor_id": "c1p2b1-slide",
                    "beat_id": "c1p2b1",
                    "template_type": "recap",
                    "visual_goal": "Présenter le trépied de la posture professionnelle.",
                }
            ],
        }
        raw = {
            "template_type": "recap",
            "event_type": "recap",
            "event_summary": "Posture professionnelle",
            "data": {
                "title": "Posture professionnelle",
                "points": [
                    "Neutralité bienveillante",
                    "Courtoisie professionnelle",
                    "Représentation de l'entreprise",
                ],
            },
            "slide_anchor_id": "c1p2b1-slide",
            "source_quote": block["text"],
        }

        normalized = slides._normalize_slide(raw, block)

        self.assertEqual(normalized["template_type"], "situations")
        self.assertEqual(normalized["pedagogical_shape"], "triade_structurante")
        self.assertEqual(normalized["rejected_templates"][0]["template"], "recap")
        self.assertEqual(normalized["event_type"], "concept")
        self.assertEqual(len(normalized["data"]["items"]), 3)

    def test_single_case_with_advice_reroutes_from_casestudy_to_tip(self):
        block = {
            "source_block_id": 8,
            "word_start": 4166,
            "word_end": 4800,
            "word_count": 634,
            "sub_part_name": "Neutralité bienveillante",
            "text": (
                "Imaginez la scène suivante. Un client a déjà appelé trois fois et une note indique client difficile. "
                "Quel est le réflexe métier à adopter dans ce cas-là ? Le réflexe, c'est de faire table rase. "
                "Je vous propose une astuce toute simple : avant de décrocher, prenez une micro-pause."
            ),
            "slide_anchors": [
                {
                    "anchor_id": "c1p2b2-slide",
                    "beat_id": "c1p2b2",
                    "template_type": "casestudy",
                    "visual_goal": "Utiliser un cas pour installer le réflexe de neutralité.",
                }
            ],
        }
        raw = {
            "template_type": "casestudy",
            "event_type": "example",
            "event_summary": "Client étiqueté difficile",
            "data": {
                "title": "Client difficile",
                "cases": [
                    {
                        "title": "L'étiquette",
                        "desc": "Le dossier porte déjà un jugement avant l'appel.",
                        "example": "Faire table rase avant de décrocher.",
                    }
                ],
            },
            "slide_anchor_id": "c1p2b2-slide",
            "source_quote": block["text"],
        }

        normalized = slides._normalize_slide(raw, block)

        self.assertEqual(normalized["template_type"], "tip")
        self.assertEqual(normalized["event_type"], "tip")
        self.assertIn("Client difficile", normalized["data"]["title"])

    def test_multiple_cases_stay_casestudy(self):
        block = {
            "source_block_id": 9,
            "word_start": 4801,
            "word_end": 5000,
            "word_count": 199,
            "sub_part_name": "Canaux",
            "text": "Comparons trois canaux : téléphone, email et chat. Chacun impose un accueil différent.",
            "slide_anchors": [],
        }
        raw = {
            "template_type": "casestudy",
            "event_type": "example",
            "event_summary": "Accueil selon le canal",
            "data": {
                "title": "Selon le canal",
                "cases": [
                    {"title": "Téléphone", "desc": "La voix porte la relation."},
                    {"title": "Email", "desc": "La clarté structure l'échange."},
                    {"title": "Chat", "desc": "La rapidité rassure."},
                ],
            },
            "source_quote": block["text"],
        }

        normalized = slides._normalize_slide(raw, block)

        self.assertEqual(normalized["template_type"], "casestudy")
        self.assertEqual(len(normalized["data"]["cases"]), 3)

    def test_two_channel_families_reroutes_to_comparison(self):
        block = {
            "source_block_id": 10,
            "word_start": 5001,
            "word_end": 5400,
            "word_count": 399,
            "sub_part_name": "Canaux de communication",
            "text": (
                "Il faut poser une distinction entre deux grandes familles de canaux. "
                "D'un côté, les canaux synchrones, comme le téléphone ou le chat, demandent une réaction immédiate. "
                "De l'autre côté, les canaux asynchrones, comme le courriel, demandent une réponse complète et autoportante."
            ),
            "slide_anchors": [
                {
                    "anchor_id": "c1p3b1-slide",
                    "beat_id": "c1p3b1",
                    "template_type": "definition",
                    "visual_goal": "Distinguer les canaux synchrones et asynchrones.",
                }
            ],
        }
        raw = {
            "template_type": "definition",
            "event_type": "definition",
            "event_summary": "Canaux synchrones et asynchrones",
            "data": {
                "title": "Synchrone ou asynchrone",
                "term": "Canaux de communication",
                "definition": "Deux familles de canaux avec des attentes différentes.",
            },
            "slide_anchor_id": "c1p3b1-slide",
            "source_quote": block["text"],
        }

        normalized = slides._normalize_slide(raw, block)

        self.assertEqual(normalized["template_type"], "comparison")
        self.assertEqual(normalized["event_type"], "comparison")
        self.assertEqual([col["label"] for col in normalized["data"]["cols"]], [
            "Canaux synchrones",
            "Canaux asynchrones",
        ])

    def test_slide_catalog_only_exposes_source_exact_templates(self):
        catalog = slides._load_slide_template_catalog()
        template_ids = {
            item.get("template_id")
            for item in catalog.get("templates") or []
            if isinstance(item, dict)
        }
        self.assertEqual(
            template_ids,
            {
                "welcome",
                "program_year",
                "day_program_7_steps",
                "chapter_opener",
                "reflection",
                "definition",
                "comparison",
                "warning",
                "casestudy",
                "situations",
                "steps",
                "flow",
                "story",
                "analogy",
                "framework",
                "opinion",
                "recap",
                "pause",
                "qa",
                "quotable",
                "tip",
            },
        )
        for forbidden in {
            "script",
            "matrix",
            "profiles",
            "timeline",
            "decisiontree",
            "channel",
            "stats",
            "checklist",
            "transition",
            "exercise",
        }:
            self.assertNotIn(forbidden, template_ids)


if __name__ == "__main__":
    unittest.main()
