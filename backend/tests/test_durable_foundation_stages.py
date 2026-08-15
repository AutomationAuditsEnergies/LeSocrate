import inspect
import json
import unittest
from unittest.mock import call, patch

from services import formation_pipeline_service as fps
from services import knowledge_base_service as kbs
from services.pipeline_queue.contracts import LeaseLostError


class DurableFoundationStagesTest(unittest.TestCase):
    @staticmethod
    def _valid_enriched_payload():
        return {
            "definition_pedagogique": "Une définition pédagogique complète.",
            "etudes_de_cas": [{
                "titre": "Cas client",
                "situation": "Exemple fictif commenté par le formateur.",
                "enjeu": "Comprendre la demande.",
                "resolution_attendue": "Le formateur explique la conduite adaptée.",
                "variantes": "Une variante.",
            }],
            "pieges_frequents": [{
                "piege": "Répondre trop vite.",
                "pourquoi_frequent": "Le contexte est incomplet.",
                "comment_eviter": "Reformuler avant de répondre.",
            }],
            "vocabulaire_metier": {"reformulation": "Vérification du besoin exprimé."},
            "contexte_terrain": "Un contexte professionnel réaliste et vérifiable.",
            "liens_connexes": [],
        }

    def test_kb_parser_repairs_the_malformed_property_error_from_the_pipeline(self):
        payload = self._valid_enriched_payload()
        malformed = json.dumps(payload, ensure_ascii=False, indent=2)
        malformed = malformed.replace(
            '  "contexte_terrain"',
            '  contexte_terrain',
        )

        with patch.object(kbs, "_deepseek_post", return_value=malformed) as deepseek:
            result = kbs.enrich_competence(
                {
                    "bloc": "CCP2",
                    "competence_title": "Assurer le recouvrement amiable de créances",
                    "raw_source": "Source REAC",
                },
                "TP Test",
                "RNCP1",
            )

        self.assertEqual(result["contexte_terrain"], payload["contexte_terrain"])
        deepseek.assert_called_once()

    def test_kb_rejects_repaired_but_incomplete_payload(self):
        incomplete = json.dumps({
            "definition_pedagogique": "Définition reçue avant troncature"
        })

        with patch.object(kbs, "_deepseek_post", return_value=incomplete):
            with self.assertRaisesRegex(ValueError, "contexte_terrain"):
                kbs.enrich_competence(
                    {
                        "bloc": "CCP2",
                        "competence_title": "Compétence",
                        "raw_source": "Source REAC",
                    },
                    "TP Test",
                    "RNCP1",
                )

    def test_formation_wrappers_disable_hidden_http_retries(self):
        with patch.object(
            fps,
            "_post_deepseek_message",
            return_value="formation",
        ) as formation_post, patch.object(
            kbs,
            "_post_deepseek_message",
            return_value="kb",
        ) as kb_post:
            self.assertEqual(fps._deepseek_post([], model="model"), "formation")
            self.assertEqual(kbs._deepseek_post([], model="model"), "kb")

        self.assertEqual(
            formation_post.call_args.kwargs["http_max_attempts"],
            1,
        )
        self.assertEqual(kb_post.call_args.kwargs["http_max_attempts"], 1)

    def test_long_foundation_generation_can_enable_bounded_transport_retry(self):
        with patch.object(
            fps,
            "_post_deepseek_message",
            return_value="programme",
        ) as formation_post:
            result = fps._deepseek_post(
                [],
                model="deepseek-v4-flash",
                http_max_attempts=2,
            )

        self.assertEqual(result, "programme")
        self.assertEqual(
            formation_post.call_args.kwargs["http_max_attempts"],
            2,
        )

    def test_kb_extraction_calls_the_model_once_per_durable_attempt(self):
        with patch.object(
            kbs,
            "_deepseek_post",
            side_effect=RuntimeError("provider indisponible"),
        ) as deepseek:
            with self.assertRaisesRegex(RuntimeError, "provider indisponible"):
                kbs.extract_competences(
                    "REAC",
                    "TP Test",
                    "RNCP1",
                )

        deepseek.assert_called_once()

    def test_kb_context_turns_legacy_cases_into_narrated_examples(self):
        with patch.object(
            kbs,
            "list_kb",
            return_value=[{
                "competence_title": "Conseiller un client",
                "definition_pedagogique": "",
                "contexte_terrain": "",
                "etudes_de_cas": [{
                    "titre": "Cas pratique guidé",
                    "situation": "Exemple fictif : un client hésite.",
                    "enjeu": "Clarifier le besoin.",
                    "resolution_attendue": "Le professeur explique la méthode.",
                }],
                "pieges_frequents": [],
                "vocabulaire_metier": {},
                "status": "completed",
            }],
        ):
            context = kbs.build_kb_context(42)

        self.assertIn("Illustrations professionnelles fictives", context)
        self.assertIn("Exemple fictif : un client hésite.", context)
        self.assertNotIn("Cas pratique guidé", context)
        self.assertNotIn("Études de cas", context)

    def test_completed_kb_runs_synchronously_and_keeps_its_checkpoints(self):
        job = {
            "id": 42,
            "tp_name": "TP Test",
            "rncp_code": "RNCP1",
            "reac_text": "Référentiel complet",
        }
        existing = [{
            "competence_index": 0,
            "competence_title": "Compétence",
            "competence_key": "competence",
            "bloc": "Bloc 1",
            "raw_source": "Source",
            "status": "completed",
            "total_words": 1200,
        }]
        checkpoints = []

        with patch.object(fps, "get_job", return_value=job), patch.object(
            fps,
            "update_job",
        ) as update, patch.object(
            kbs,
            "list_kb",
            return_value=existing,
        ), patch.object(
            kbs,
            "kb_stats",
            return_value={"total": 1, "completed": 1, "error": 0},
        ):
            kbs.build_knowledge_base(
                42,
                model="deepseek-v4-pro",
                checkpoint=lambda: checkpoints.append("ok"),
            )

        self.assertGreaterEqual(len(checkpoints), 2)
        self.assertEqual(
            update.call_args_list,
            [
                call(42, status="kb_building"),
                call(42, status="kb_ready", kb_generated_via="api"),
            ],
        )
        self.assertNotIn(
            "threading.Thread",
            inspect.getsource(kbs.build_knowledge_base),
        )
        self.assertFalse(hasattr(kbs, "launch_kb_building"))

    def test_lost_kb_lease_stops_without_writing_a_false_business_error(self):
        job = {
            "id": 42,
            "tp_name": "TP Test",
            "rncp_code": "RNCP1",
            "reac_text": "Référentiel complet",
        }
        existing = [{
            "competence_index": 0,
            "competence_title": "Compétence",
            "competence_key": "competence",
            "bloc": "Bloc 1",
            "raw_source": "Source",
            "status": "completed",
            "total_words": 1200,
        }]
        checkpoint_count = 0

        def checkpoint():
            nonlocal checkpoint_count
            checkpoint_count += 1
            if checkpoint_count == 2:
                raise LeaseLostError("lease remplacé")

        with patch.object(fps, "get_job", return_value=job), patch.object(
            fps,
            "update_job",
        ) as update, patch.object(
            kbs,
            "list_kb",
            return_value=existing,
        ), patch.object(
            kbs,
            "kb_stats",
            return_value={"total": 1, "completed": 1, "error": 0},
        ):
            with self.assertRaisesRegex(LeaseLostError, "lease remplacé"):
                kbs.build_knowledge_base(42, checkpoint=checkpoint)

        self.assertEqual(update.call_args_list, [call(42, status="kb_building")])

    def test_partial_kb_failure_is_retried_without_reextracting_or_marking_ready(self):
        job = {
            "id": 42,
            "tp_name": "TP Test",
            "rncp_code": "RNCP1",
            "reac_text": "Référentiel complet",
        }
        existing = [{
            "competence_index": 0,
            "competence_title": "Compétence déjà terminée",
            "competence_key": "terminee",
            "bloc": "Bloc 1",
            "raw_source": "Source 1",
            "status": "completed",
            "total_words": 1200,
        }, {
            "competence_index": 1,
            "competence_title": "Compétence à reprendre",
            "competence_key": "reprendre",
            "bloc": "Bloc 1",
            "raw_source": "Source 2",
            "status": "error",
            "total_words": 0,
        }]

        with patch.object(fps, "get_job", return_value=job), patch.object(
            fps,
            "update_job",
        ) as update, patch.object(
            kbs,
            "list_kb",
            return_value=existing,
        ), patch.object(
            kbs,
            "extract_competences",
        ) as extract, patch.object(
            kbs,
            "enrich_competence",
            side_effect=ValueError("JSON toujours incomplet"),
        ) as enrich, patch.object(
            kbs,
            "mark_competence_error",
        ) as mark_error, patch.object(
            kbs,
            "kb_stats",
            return_value={"total": 2, "completed": 1, "error": 1},
        ):
            with self.assertRaisesRegex(RuntimeError, "1/2 compétences terminées"):
                kbs.build_knowledge_base(42)

        extract.assert_not_called()
        enrich.assert_called_once()
        self.assertEqual(enrich.call_args.kwargs["competence"]["competence_index"], 1)
        mark_error.assert_called_once_with(42, 1, "JSON toujours incomplet")
        self.assertEqual(update.call_args_list[0], call(42, status="kb_building"))
        self.assertEqual(update.call_args_list[-1][0], (42,))
        self.assertEqual(update.call_args_list[-1].kwargs["status"], "error")
        self.assertFalse(
            any(call_item.kwargs.get("status") == "kb_ready" for call_item in update.call_args_list)
        )

    def test_kb_failure_is_propagated_to_the_durable_worker(self):
        job = {
            "id": 42,
            "tp_name": "TP Test",
            "rncp_code": "RNCP1",
            "reac_text": "",
        }
        with patch.object(fps, "get_job", return_value=job), patch.object(
            fps,
            "update_job",
        ) as update:
            with self.assertRaisesRegex(RuntimeError, "REAC vide"):
                kbs.build_knowledge_base(42)

        update.assert_called_once_with(
            42,
            status="error",
            error_message="REAC vide — télécharger d'abord le REAC",
        )

    def test_global_program_runs_synchronously_under_the_same_lease(self):
        job = {
            "id": 42,
            "tp_name": "TP Test",
            "rncp_code": "RNCP1",
            "reac_text": "Référentiel complet",
            "nb_days": 2,
        }
        checkpoints = []

        with patch.object(fps, "get_job", return_value=job), patch.object(
            fps,
            "update_job",
        ) as update, patch.object(
            fps,
            "_v2_schedule_days",
            return_value=[],
        ), patch(
            "services.knowledge_base_service.build_kb_context",
            return_value="Base enrichie",
        ), patch.object(
            fps,
            "_build_global_program_prompt",
            return_value="Prompt",
        ), patch.object(
            fps,
            "_deepseek_post",
            return_value="Programme global",
        ):
            fps.generate_global_program(
                42,
                model="deepseek-v4-pro",
                checkpoint=lambda: checkpoints.append("ok"),
            )

        self.assertGreaterEqual(len(checkpoints), 3)
        self.assertEqual(
            update.call_args_list,
            [
                call(42, status="global_generating"),
                call(
                    42,
                    status="global_ready",
                    global_program="Programme global",
                    global_program_generated_via="api",
                ),
            ],
        )
        self.assertNotIn(
            "threading.Thread",
            inspect.getsource(fps.generate_global_program),
        )
        self.assertFalse(hasattr(fps, "launch_global_program_generation"))

    def test_global_program_repairs_invalid_activity_before_persisting(self):
        job = {
            "id": 42,
            "tp_name": "TP Test",
            "rncp_code": "RNCP1",
            "reac_text": "Référentiel complet",
            "nb_days": 2,
        }
        invalid_program = "### MODULE 1.1 : Cas pratique guidé"
        repaired_program = "### MODULE 1.1 : Exemple professionnel commenté"
        with patch.object(fps, "get_job", return_value=job), patch.object(
            fps,
            "update_job",
        ) as update, patch.object(
            fps,
            "_v2_schedule_days",
            return_value=[],
        ), patch(
            "services.knowledge_base_service.build_kb_context",
            return_value="Base enrichie",
        ), patch.object(
            fps,
            "_build_global_program_prompt",
            return_value="Prompt",
        ), patch.object(
            fps,
            "_deepseek_post",
            side_effect=[invalid_program, repaired_program],
        ) as deepseek:
            fps.generate_global_program(42)

        self.assertEqual(deepseek.call_count, 2)
        self.assertTrue(
            all(
                call_item.kwargs["http_max_attempts"] == 2
                for call_item in deepseek.call_args_list
            )
        )
        self.assertEqual(
            update.call_args_list,
            [
                call(42, status="global_generating"),
                call(
                    42,
                    status="global_ready",
                    global_program=repaired_program,
                    global_program_generated_via="api",
                ),
            ],
        )

    def test_global_program_delegates_failed_semantic_repair_to_durable_retry(self):
        job = {
            "id": 42,
            "tp_name": "TP Test",
            "rncp_code": "RNCP1",
            "reac_text": "Référentiel complet",
            "nb_days": 2,
        }
        invalid_program = "### MODULE 1.1 : Mise en situation guidée"
        with patch.object(fps, "get_job", return_value=job), patch.object(
            fps,
            "update_job",
        ) as update, patch.object(
            fps,
            "_v2_schedule_days",
            return_value=[],
        ), patch(
            "services.knowledge_base_service.build_kb_context",
            return_value="Base enrichie",
        ), patch.object(
            fps,
            "_build_global_program_prompt",
            return_value="Prompt",
        ), patch.object(
            fps,
            "_deepseek_post",
            return_value=invalid_program,
        ) as deepseek:
            with self.assertRaisesRegex(ValueError, "activité apprenant interdite"):
                fps.generate_global_program(42)

        self.assertEqual(deepseek.call_count, 2)
        self.assertEqual(update.call_args_list[0], call(42, status="global_generating"))
        self.assertEqual(update.call_args_list[-1][0], (42,))
        self.assertEqual(update.call_args_list[-1].kwargs["status"], "error")

    def test_global_program_failure_is_propagated_to_the_durable_worker(self):
        job = {
            "id": 42,
            "tp_name": "TP Test",
            "rncp_code": "RNCP1",
            "reac_text": "Référentiel complet",
            "nb_days": 2,
        }
        with patch.object(fps, "get_job", return_value=job), patch.object(
            fps,
            "update_job",
        ) as update, patch.object(
            fps,
            "_v2_schedule_days",
            return_value=[],
        ), patch(
            "services.knowledge_base_service.build_kb_context",
            return_value="Base enrichie",
        ), patch.object(
            fps,
            "_build_global_program_prompt",
            return_value="Prompt",
        ), patch.object(
            fps,
            "_deepseek_post",
            side_effect=RuntimeError("LLM indisponible"),
        ):
            with self.assertRaisesRegex(RuntimeError, "LLM indisponible"):
                fps.generate_global_program(42)

        self.assertEqual(
            update.call_args_list,
            [
                call(42, status="global_generating"),
                call(
                    42,
                    status="error",
                    error_message="LLM indisponible",
                ),
            ],
        )

    def test_lost_global_lease_stops_before_the_llm_call(self):
        job = {
            "id": 42,
            "tp_name": "TP Test",
            "rncp_code": "RNCP1",
            "reac_text": "Référentiel complet",
            "nb_days": 2,
        }
        checkpoint_count = 0

        def checkpoint():
            nonlocal checkpoint_count
            checkpoint_count += 1
            if checkpoint_count == 2:
                raise LeaseLostError("lease remplacé")

        with patch.object(fps, "get_job", return_value=job), patch.object(
            fps,
            "update_job",
        ) as update, patch.object(
            fps,
            "_v2_schedule_days",
            return_value=[],
        ), patch(
            "services.knowledge_base_service.build_kb_context",
            return_value="Base enrichie",
        ), patch.object(
            fps,
            "_build_global_program_prompt",
            return_value="Prompt",
        ), patch.object(fps, "_deepseek_post") as deepseek:
            with self.assertRaisesRegex(LeaseLostError, "lease remplacé"):
                fps.generate_global_program(42, checkpoint=checkpoint)

        deepseek.assert_not_called()
        self.assertEqual(
            update.call_args_list,
            [call(42, status="global_generating")],
        )


if __name__ == "__main__":
    unittest.main()
