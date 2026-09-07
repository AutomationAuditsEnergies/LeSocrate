import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from azure.core.exceptions import ResourceExistsError

from services import platform_storage_service as service


class PlatformStorageServiceTest(unittest.TestCase):
    def _clients(self):
        audio = Mock()
        archive = Mock()
        pdf = Mock()
        audio_service = Mock()
        pdf_service = Mock()
        audio_service.get_container_client.side_effect = lambda name: {
            "formationaudio-p5": audio,
            "formationaudio-p5-archives": archive,
        }[name]
        pdf_service.get_container_client.side_effect = lambda name: {
            "formationpdf-p5": pdf,
        }[name]
        return audio_service, pdf_service, audio, archive, pdf

    def test_full_platform_storage_is_created_private(self):
        audio_service, pdf_service, audio, archive, pdf = self._clients()

        result = service.ensure_platform_storage(
            {
                "id": 5,
                "audio_container": "formationaudio-p5",
                "archive_container": "formationaudio-p5-archives",
                "pdf_container": "formationpdf-p5",
            },
            audio_blob_service_client=audio_service,
            pdf_blob_service_client=pdf_service,
        )

        self.assertEqual(
            result["created"],
            {"audio": True, "archive": True, "pdf": True},
        )
        for container in (audio, archive, pdf):
            container.create_container.assert_called_once_with()

    def test_retry_is_idempotent_and_never_rewrites_existing_acl(self):
        audio_service, pdf_service, audio, archive, pdf = self._clients()
        for container in (audio, archive, pdf):
            container.create_container.side_effect = ResourceExistsError("exists")

        result = service.ensure_platform_storage(
            5,
            audio_blob_service_client=audio_service,
            pdf_blob_service_client=pdf_service,
        )

        self.assertEqual(
            result["created"],
            {"audio": False, "archive": False, "pdf": False},
        )
        for container in (audio, archive, pdf):
            container.create_container.assert_called_once_with()

    def test_partial_azure_failure_is_raised_for_durable_retry(self):
        audio_service, pdf_service, audio, archive, pdf = self._clients()
        archive.create_container.side_effect = RuntimeError("azure unavailable")

        with self.assertRaisesRegex(RuntimeError, "azure unavailable"):
            service.ensure_platform_storage(
                5,
                audio_blob_service_client=audio_service,
                pdf_blob_service_client=pdf_service,
            )

        audio.create_container.assert_called_once_with()
        archive.create_container.assert_called_once_with()
        pdf.create_container.assert_not_called()

    def test_audio_sas_is_read_only_blob_scoped_and_short_lived(self):
        blob_key = "course-sessions/501/cours_1.mp3"
        blob = SimpleNamespace(
            url=f"https://storage.blob.core.windows.net/formationaudio-p5/{blob_key}"
        )
        blob_service = Mock(
            account_name="storage",
            credential=SimpleNamespace(account_key="not-logged-secret"),
        )
        blob_service.get_blob_client.return_value = blob

        with patch.object(service.time, "time", return_value=1_700_000_000), patch.object(
            service,
            "generate_blob_sas",
            return_value="sp=r&se=short&sig=secret",
        ) as generate:
            url = service.issue_platform_audio_read_url(
                5,
                blob_key,
                expires_at=1_700_000_300,
                blob_service_client=blob_service,
            )

        self.assertEqual(
            url,
            f"https://storage.blob.core.windows.net/formationaudio-p5/{blob_key}?sp=r&se=short&sig=secret",
        )
        blob_service.get_blob_client.assert_called_once_with(
            container="formationaudio-p5",
            blob=blob_key,
        )
        sas_args = generate.call_args.kwargs
        self.assertEqual(sas_args["container_name"], "formationaudio-p5")
        self.assertEqual(sas_args["blob_name"], blob_key)
        self.assertTrue(sas_args["permission"].read)
        self.assertFalse(sas_args["permission"].write)

    def test_audio_sas_rejects_cross_occurrence_or_traversal_keys(self):
        blob_service = Mock(
            account_name="storage",
            credential=SimpleNamespace(account_key="not-logged-secret"),
        )
        for key in (
            "course-sessions/501/../cours_1.mp3",
            "course-sessions/not-an-id/cours_1.mp3",
            "other-prefix/501/cours_1.mp3",
        ):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "Clé audio invalide"):
                service.issue_platform_audio_read_url(
                    5,
                    key,
                    expires_at=1_700_000_300,
                    blob_service_client=blob_service,
                )


if __name__ == "__main__":
    unittest.main()
