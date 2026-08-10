import io
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from azure.core.exceptions import ResourceExistsError
from PyPDF2 import PdfReader

from services import daily_course_pdf_service as service
from routes import formation_routes
from services.playlist_tts_service import PLAYLIST_SPEC


class DailyCoursePdfServiceTest(unittest.TestCase):
    def test_render_produces_readable_tag_free_pdf(self):
        pdf_bytes = service.render_daily_course_pdf(
            formation_title="Conseiller relation client à distance",
            rncp_code="35304",
            day_number=2,
            day_title="Accueillir et comprendre la demande",
            scheduled_at="2026-07-22 09:00:00",
            sections=[
                {
                    "name": "Écoute active [section]",
                    "body": (
                        "[warm] Bonjour et bienvenue. [pause]\n\n"
                        "<<<BLOC_AUDIO_2>>>\n"
                        "La reformulation permet de vérifier la demande du client."
                    ),
                }
            ],
        )

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        text = "\n".join(
            page.extract_text() or ""
            for page in PdfReader(io.BytesIO(pdf_bytes)).pages
        )
        self.assertIn("Conseiller relation client", text)
        self.assertIn("22/07/2026", text)
        self.assertIn("La reformulation permet", text)
        self.assertNotIn("[warm]", text)
        self.assertNotIn("[pause]", text)
        self.assertNotIn("BLOC_AUDIO", text)

    def test_publish_uses_tenant_and_occurrence_scoped_blob(self):
        destination = Mock()
        container = Mock()
        container.create_container.side_effect = ResourceExistsError("exists")
        container.get_blob_client.return_value = destination
        client = Mock()
        client.get_container_client.return_value = container

        result = service.publish_daily_course_pdf(
            platform_id=5,
            session_id=501,
            pdf_bytes=b"%PDF-1.4\nfixture",
            blob_service_client=client,
        )

        client.get_container_client.assert_called_once_with(
            "formation-course-materials"
        )
        container.get_blob_client.assert_called_once_with(
            "platform-5/course-sessions/501/support-formation.pdf"
        )
        destination.upload_blob.assert_called_once()
        self.assertEqual(
            result["blob_key"],
            "platform-5/course-sessions/501/support-formation.pdf",
        )

    def test_pipeline_completion_publishes_every_daily_pdf(self):
        with (
            patch(
                "services.formation_pipeline_service.get_expected_course_folders",
                return_value={"folder_ids": [55, 56]},
            ),
            patch(
                "repositories.course_schedule_repository.list_course_sessions",
                return_value=[
                    {"id": 501, "session_index": 1, "scheduled_at": "2026-07-22 09:00:00"},
                    {"id": 502, "session_index": 2, "scheduled_at": "2026-07-23 09:00:00"},
                ],
            ),
            patch.object(
                service,
                "build_daily_course_pdf",
                side_effect=[
                    (b"%PDF day 1", service.COURSE_PDF_FILENAME, {"day_number": 1}),
                    (b"%PDF day 2", service.COURSE_PDF_FILENAME, {"day_number": 2}),
                ],
            ) as build_pdf,
            patch.object(
                service,
                "publish_daily_course_pdf",
                side_effect=[
                    {"blob_key": "platform-5/course-sessions/501/support-formation.pdf"},
                    {"blob_key": "platform-5/course-sessions/502/support-formation.pdf"},
                ],
            ) as publish_pdf,
        ):
            results = service.publish_pipeline_course_pdfs(job_id=8, platform_id=5)

        self.assertEqual(len(results), 2)
        self.assertEqual([result["folder_id"] for result in results], [55, 56])
        self.assertEqual(
            build_pdf.call_args_list,
            [
                call(job_id=8, folder_id=55, scheduled_at="2026-07-22 09:00:00"),
                call(job_id=8, folder_id=56, scheduled_at="2026-07-23 09:00:00"),
            ],
        )
        self.assertEqual(
            [item.kwargs["session_id"] for item in publish_pdf.call_args_list],
            [501, 502],
        )

    def test_finalize_text_publishes_pdfs_before_marking_pipeline_ready(self):
        calls = []
        with (
            patch.object(
                formation_routes,
                "_finalize_text_ready_state",
                side_effect=lambda job_id: calls.append(("finalize", job_id)),
            ),
            patch(
                "services.daily_course_pdf_service.publish_pipeline_course_pdfs",
                side_effect=lambda **kwargs: calls.append(("pdf", kwargs)) or [{"session_id": 501}],
            ),
            patch.object(
                formation_routes,
                "update_job",
                side_effect=lambda job_id, **kwargs: calls.append(("update", job_id, kwargs)),
            ),
        ):
            formation_routes._execute_ap_step(
                8,
                "finalize_text",
                {
                    "platform_id": 5,
                    "auto_pilot_model": "pro",
                    "auto_pilot_generate_audio": False,
                },
            )

        self.assertEqual([entry[0] for entry in calls], ["finalize", "pdf", "update"])
        self.assertEqual(calls[1][1], {"job_id": 8, "platform_id": 5})
        self.assertEqual(calls[2][2]["status"], "text_ready")

    def test_scheduled_audio_does_not_rebuild_pipeline_pdf(self):
        published_audio = [item[0] for item in PLAYLIST_SPEC]
        with (
            patch.object(formation_routes, "get_job", return_value={
                "id": 8,
                "platform_id": 5,
                "nb_days": 1,
                "auto_pilot_tts_mode": "mock",
            }),
            patch.object(
                formation_routes,
                "_resolve_continue_after_text_folder",
                return_value=(55, None),
            ),
            patch.object(
                formation_routes,
                "_folder_text_reviews_ready",
                return_value=(True, {"segments_completed": 1, "reviewed_current": 1}),
            ),
            patch.object(formation_routes, "_try_acquire_scheduled_audio_capacity", return_value=True),
            patch.object(formation_routes, "_release_scheduled_audio_capacity"),
            patch.object(formation_routes, "_assert_scheduled_audio_ownership"),
            patch.object(formation_routes, "_count_dirty_segments_for_job", return_value=0),
            patch.object(
                formation_routes,
                "_finalize_scheduled_audio_module_if_ready",
                return_value={"finalized": False},
            ),
            patch.object(formation_routes, "update_job"),
            patch(
                "services.formation_pipeline_service.get_expected_course_folders",
                return_value={"folder_ids": [55]},
            ),
            patch(
                "services.content_generation_service.generate_audio_from_script",
                return_value={"generated": published_audio, "skipped": []},
            ),
            patch(
                "repositories.course_schedule_repository.claim_audio_generation_session",
                return_value=True,
            ),
            patch(
                "repositories.course_schedule_repository.complete_audio_generation_session",
                return_value=True,
            ),
            patch(
                "services.audio_publish_service.publish_playlist_audio_to_platform",
                return_value={"published": published_audio, "publish_errors": []},
            ),
            patch(
                "services.daily_course_pdf_service.build_daily_course_pdf",
            ) as build_pdf,
            patch(
                "services.daily_course_pdf_service.publish_daily_course_pdf",
            ) as publish_pdf,
            patch("services.formation_observability_service.log_pipeline_event"),
        ):
            payload, status = formation_routes.start_folder_audio_generation(
                8,
                55,
                {"tts_mode": "mock", "preserve_existing": True},
                schedule_session_id=501,
                target_platform_id=5,
                trigger_source="scheduled_j1_preparation",
                wait_for_completion=True,
            )

        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["status"], "audio_completed")
        build_pdf.assert_not_called()
        publish_pdf.assert_not_called()

    def test_listing_never_crosses_platform_prefix(self):
        own_blob = SimpleNamespace(
            name="platform-5/course-sessions/501/support-formation.pdf",
            size=2048,
            last_modified=datetime(2026, 7, 21, 7, 0, tzinfo=timezone.utc),
        )
        other_blob = SimpleNamespace(
            name="platform-6/course-sessions/601/support-formation.pdf",
            size=4096,
            last_modified=datetime(2026, 7, 21, 7, 0, tzinfo=timezone.utc),
        )
        container = Mock()
        container.list_blobs.return_value = [own_blob, other_blob]
        client = Mock()
        client.account_name = "storage"
        client.credential.account_key = "secret"
        client.get_container_client.return_value = container
        client.get_blob_client.return_value.url = (
            "https://storage.blob.core.windows.net/formation-course-materials/own"
        )

        with patch.object(service, "generate_blob_sas", return_value="sig=read"):
            materials = service.list_daily_course_pdf_materials(
                5,
                [{
                    "id": 501,
                    "session_index": 1,
                    "audio_folder_id": 55,
                    "scheduled_at": "2026-07-22 09:00:00",
                }],
                blob_service_client=client,
            )

        container.list_blobs.assert_called_once_with(
            name_starts_with="platform-5/course-sessions/"
        )
        self.assertEqual(len(materials), 1)
        self.assertEqual(materials[0]["session_id"], 501)
        self.assertEqual(materials[0]["folder_id"], 55)
        self.assertTrue(materials[0]["url"].endswith("?sig=read"))


if __name__ == "__main__":
    unittest.main()
