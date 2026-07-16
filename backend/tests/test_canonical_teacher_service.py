import unittest
from unittest.mock import patch

from services import canonical_teacher_service as service
from repositories import pipeline_repository as pipeline_repo
from repositories import hr_write_repository as hr_write_repo
from repositories import teacher_asset_repository as asset_repo


class CanonicalTeacherServiceTest(unittest.TestCase):
    def test_module_with_only_one_audio_is_not_a_canonical_match(self):
        class FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, params):
                self.query = query
                self.params = params

            def fetchall(self):
                return [{
                    "module_id": 44,
                    "canonical_fingerprint": "a" * 64,
                    "canonical_generator_version": "pipeline-v2",
                    "voice_type": "fish_audio",
                    "version": "2026-v1",
                    "nb_days": 1,
                    "asset_count": 1,
                    "audio_assets": [{
                        "source_folder_id": 91,
                        "logical_key": "audiostts:folder:91:playlist/cours_9h00_9h45.mp3",
                    }],
                }]

        class FakeConnection:
            def cursor(self):
                return FakeCursor()

        class FakeContext:
            def __enter__(self):
                return FakeConnection()

            def __exit__(self, *_args):
                return False

        with (
            patch.object(asset_repo, "_uses_postgres", return_value=True),
            patch.object(asset_repo, "get_postgres_connection", return_value=FakeContext()),
        ):
            match = asset_repo.find_canonical_reusable_module("a" * 64)

        self.assertIsNone(match)

    def test_cross_tenant_clone_wrapper_keeps_target_tenant_scoped(self):
        with patch.object(
            hr_write_repo,
            "clone_postgres_course_structure",
            return_value={"target_platform_id": 120},
        ) as clone:
            result = hr_write_repo.clone_canonical_module_course_structure(
                target_platform_id=120,
                module_id=44,
                target_center_account_id=42,
            )

        self.assertEqual(result["target_platform_id"], 120)
        clone.assert_called_once_with(
            target_platform_id=120,
            module_id=44,
            center_account_id=42,
            scope_to_center=True,
            allow_canonical_cross_tenant=True,
        )

    def test_postgres_finalization_persists_canonical_identity_for_saas_teacher(self):
        captured = {}

        class FakeCursor:
            rowcount = 1

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, params=None):
                self.query = query
                if "INSERT INTO formation_modules" in query:
                    captured["insert_query"] = query
                    captured["insert_params"] = params

            def fetchone(self):
                if "FROM platform_config WHERE id" in self.query:
                    return {
                        "center_account_id": 7,
                        "teacher_name": "Socrate",
                        "teacher_color": "violet",
                        "creation_request_id": "teacher-order-order_123",
                    }
                if "FROM formation_modules" in self.query and "source_pipeline_job_id" in self.query:
                    return None
                if "SELECT COUNT(*) AS count" in self.query:
                    return {"count": 0}
                if "RETURNING id, version, status" in self.query:
                    return {
                        "id": 44,
                        "version": "2026-v1",
                        "status": "validated",
                        "created": True,
                    }
                return None

        class FakeConnection:
            def cursor(self):
                return FakeCursor()

        class FakeContext:
            def __enter__(self):
                return FakeConnection()

            def __exit__(self, *_args):
                return False

        with (
            patch.object(pipeline_repo, "_pipeline_primary_backend", return_value="postgres"),
            patch.object(pipeline_repo, "get_postgres_connection", return_value=FakeContext()),
            patch.object(pipeline_repo, "_sqlite_pipeline_mirror_required", return_value=False),
        ):
            result = pipeline_repo.finalize_pipeline_module(
                formation_job_id=9,
                platform_id=12,
                rncp_code="RNCP37682",
                tp_name="TP CRCD",
                audio_ready=True,
                voice_type="fish_audio",
                canonical_fingerprint="a" * 64,
                canonical_signature_json='{"signature_version":"teacher-assets-v1"}',
                canonical_generator_version="pipeline-v2",
            )

        params = captured["insert_params"]
        self.assertEqual(params[7:11], (True, "fish_audio", True, True))
        self.assertEqual(params[11:13], (True, "a" * 64))
        self.assertEqual(params[-1], True)
        self.assertTrue(result["canonical_reuse_allowed"])
        self.assertEqual(result["canonical_fingerprint"], "a" * 64)

    def test_equivalent_characteristics_have_one_schedule_independent_fingerprint(self):
        first = service.build_canonical_teacher_signature(
            rncp_code=" rncp 37682 ",
            tp_name="Conseiller relation client à distance",
            total_hours=14,
            nb_days=2,
            voice_type="fish_audio",
            generator_version="pipeline-v2",
        )
        second = service.build_canonical_teacher_signature(
            rncp_code="RNCP 37682",
            tp_name="  CONSEILLER   RELATION CLIENT À DISTANCE ",
            total_hours=14,
            nb_days=2,
            voice_type="FISH_AUDIO",
            generator_version="pipeline-v2",
        )

        self.assertEqual(first, second)
        self.assertEqual(
            service.canonical_teacher_fingerprint(first),
            service.canonical_teacher_fingerprint(second),
        )
        self.assertNotIn("center_account_id", first)
        self.assertNotIn("schedule", first)

    def test_voice_or_duration_changes_compatibility(self):
        base = dict(
            rncp_code="RNCP37682",
            tp_name="TP CRCD",
            total_hours=14,
            nb_days=2,
            generator_version="pipeline-v2",
        )
        fish = service.build_canonical_teacher_signature(**base, voice_type="fish_audio")
        edge = service.build_canonical_teacher_signature(**base, voice_type="gtts")
        longer = service.build_canonical_teacher_signature(
            **{**base, "total_hours": 21}, voice_type="fish_audio"
        )
        self.assertNotEqual(
            service.canonical_teacher_fingerprint(fish),
            service.canonical_teacher_fingerprint(edge),
        )
        self.assertNotEqual(
            service.canonical_teacher_fingerprint(fish),
            service.canonical_teacher_fingerprint(longer),
        )

    def test_resolver_returns_no_source_tenant_metadata(self):
        match = {
            "module_id": 44,
            "canonical_generator_version": "pipeline-v2",
            "voice_type": "fish_audio",
            "version": "2026-v1",
            "asset_count": 38,
            "center_account_id": 999,
            "center_name": "Secret source centre",
        }
        with patch.object(service, "find_canonical_reusable_module", return_value=match):
            resolved = service.resolve_compatible_canonical_teacher(
                rncp_code="RNCP37682",
                tp_name="TP CRCD",
                total_hours=14,
                nb_days=2,
                voice_type="fish_audio",
                generator_version="pipeline-v2",
            )

        self.assertEqual(resolved["module_id"], 44)
        self.assertNotIn("center_account_id", resolved)
        self.assertNotIn("center_name", resolved)


if __name__ == "__main__":
    unittest.main()
