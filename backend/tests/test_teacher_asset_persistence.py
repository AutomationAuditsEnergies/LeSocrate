import unittest
from types import SimpleNamespace
from unittest.mock import patch

from routes import formation_routes
from services import teacher_asset_service as service


class _Downloader:
    def chunks(self):
        return iter((b"first-", b"second"))


class _BlobClient:
    def __init__(self, path, store):
        self.path = path
        self.store = store

    def exists(self):
        return self.path in self.store

    def get_blob_properties(self):
        return self.store[self.path]

    def download_blob(self, **_kwargs):
        return _Downloader()

    def upload_blob(self, data, **kwargs):
        self.store[self.path] = SimpleNamespace(
            name=self.path,
            size=sum(len(chunk) for chunk in data),
            metadata=dict(kwargs.get("metadata") or {}),
            content_settings=kwargs.get("content_settings"),
            etag="canonical-etag",
            blob_tier="Hot",
        )


class _Container:
    def __init__(self, blobs):
        self.blobs = blobs

    def list_blobs(self, **_kwargs):
        return [blob for path, blob in self.blobs.items() if path.startswith("platform-")]

    def get_blob_client(self, path):
        return _BlobClient(path, self.blobs)


class _BlobService:
    def __init__(self, documents, audios):
        self.containers = {
            service.CONTAINER_DOCUMENTS: documents,
            service.CONTAINER_AUDIOS: audios,
        }

    def get_container_client(self, name):
        return self.containers[name]


class TeacherAssetPersistenceTest(unittest.TestCase):
    def test_audio_is_snapshotted_once_under_the_teacher_namespace(self):
        source_paths = [
            f"platform-12/folder-91/{relative_path}"
            for relative_path in sorted(service.CANONICAL_AUDIO_PLAYLIST_PATHS)
        ]
        audio_store = {
            path: SimpleNamespace(
                name=path,
                size=12,
                metadata={"sha256": "source-sha"},
                content_settings=SimpleNamespace(content_type="audio/mpeg"),
                etag="source-etag",
                blob_tier="Hot",
            )
            for path in source_paths
        }
        blob_service = _BlobService(_Container({}), _Container(audio_store))
        registered = []

        with patch.object(
            service,
            "get_module_asset_identity",
            return_value={
                "id": 44,
                "voice_type": "fish_audio",
                "asset_namespace": "centres/7/modules/44/versions/2026-v1",
            },
        ), patch.object(service, "module_asset_count", return_value=0), patch.object(
            service, "_get_blob_service_client", return_value=blob_service
        ), patch.object(
            service,
            "register_module_assets",
            side_effect=lambda _module, _center, assets: registered.extend(assets) or len(assets),
        ), patch.object(
            service,
            "get_module_audio_manifest_readiness",
            return_value={"ready": True, "audio_asset_count": 19, "required_folder_count": 1},
        ), patch(
            "services.day_playlist_service.required_audio_filenames",
            return_value={
                path.rsplit("/", 1)[-1]
                for path in service.CANONICAL_AUDIO_PLAYLIST_PATHS
            },
        ):
            result = service.ensure_module_asset_manifest(
                module_id=44,
                center_account_id=7,
                source_platform_id=12,
                source_folder_ids=[91],
                force=True,
            )

        canonical_path = (
            "centres/7/modules/44/versions/2026-v1/"
            "folders/91/playlist/cours_9h00_9h45.mp3"
        )
        self.assertTrue(result["audio_ready"])
        self.assertIn(canonical_path, audio_store)
        registered_by_key = {asset["logical_key"]: asset for asset in registered}
        logical_key = "audiostts:folder:91:playlist/cours_9h00_9h45.mp3"
        self.assertEqual(registered_by_key[logical_key]["blob_path"], canonical_path)
        self.assertEqual(audio_store[canonical_path].size, len(b"first-second"))
        self.assertEqual(audio_store[canonical_path].metadata["canonical"], "true")

    def test_existing_canonical_blob_is_never_overwritten(self):
        canonical = SimpleNamespace(size=99, metadata={"canonical": "true"})
        container = _Container({"source.mp3": SimpleNamespace(size=12), "canonical.mp3": canonical})

        result = service._snapshot_blob_once(container, "source.mp3", "canonical.mp3")

        self.assertIs(result, canonical)
        self.assertEqual(container.blobs["canonical.mp3"].size, 99)

    def test_pipeline_finalization_retries_when_the_durable_playlist_is_incomplete(self):
        job = {
            "id": 9,
            "platform_id": 12,
            "rncp_code": "RNCP-TEST",
            "tp_name": "Formation test",
            "total_hours": 7,
            "nb_days": 1,
        }
        draft_module = {
            "platform_id": 12,
            "platform_ready_updated": 1,
            "module_id": 44,
            "module_created": True,
            "center_account_id": 7,
            "canonical_reuse_candidate": True,
            "canonical_reuse_allowed": True,
        }
        with patch.object(formation_routes, "get_job", return_value=job), patch(
            "repositories.pipeline_repository.finalize_pipeline_module",
            return_value=draft_module,
        ) as finalize_module, patch(
            "services.formation_pipeline_service.get_expected_course_folders",
            return_value={"folder_ids": [91]},
        ), patch(
            "services.teacher_asset_service.ensure_module_asset_manifest",
            return_value={
                "audio_ready": False,
                "audio_asset_count": 18,
                "required_folder_count": 1,
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "manifeste audio incomplet"):
                formation_routes._finalize_audio_ready_state(9, "fish_audio")
        self.assertEqual(finalize_module.call_count, 1)
        self.assertFalse(finalize_module.call_args.kwargs["audio_ready"])

    def test_each_scheduled_day_is_persisted_before_global_validation(self):
        module = {
            "id": 44,
            "status": "draft",
            "center_account_id": 7,
            "source_platform_id": 12,
        }
        with patch(
            "repositories.pipeline_repository.get_formation_module_for_pipeline_job",
            return_value=module,
        ), patch(
            "services.teacher_asset_service.ensure_module_asset_manifest",
            return_value={"registered": 19, "folder_audio_ready": True, "audio_ready": False},
        ) as ensure_manifest:
            result = formation_routes._persist_daily_teacher_audio_assets(9, 91)

        self.assertTrue(result["persisted"])
        self.assertFalse(result["audio_ready"])
        ensure_manifest.assert_called_once_with(
            module_id=44,
            center_account_id=7,
            source_platform_id=12,
            source_folder_ids=[91],
            force=True,
        )


if __name__ == "__main__":
    unittest.main()
