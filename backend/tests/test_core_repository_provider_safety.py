import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from repositories import core_repository


class CoreRepositoryProviderSafetyTest(unittest.TestCase):
    def test_supabase_auth_credentials_do_not_enable_business_db_fallback(self):
        with patch.object(core_repository, "DATABASE_BACKEND", "postgres"), patch.object(
            core_repository, "SUPABASE_URL", "https://auth-project.supabase.co"
        ), patch.object(core_repository, "SUPABASE_SERVICE_ROLE_KEY", "secret"), patch.dict(
            os.environ, {"SUPABASE_DATABASE_REST_FALLBACK": "1"}, clear=False
        ):
            self.assertFalse(core_repository._supabase_rest_enabled())

    def test_supabase_database_fallback_requires_explicit_opt_in(self):
        with patch.object(core_repository, "DATABASE_BACKEND", "supabase"), patch.object(
            core_repository, "SUPABASE_URL", "https://business.supabase.co"
        ), patch.object(core_repository, "SUPABASE_SERVICE_ROLE_KEY", "secret"), patch.dict(
            os.environ, {"SUPABASE_DATABASE_REST_FALLBACK": "1"}, clear=False
        ):
            self.assertTrue(core_repository._supabase_rest_enabled())

    def test_platform_mirror_refuses_id_collision_without_rest_fallback(self):
        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, _query, _params=None):
                pass

            def fetchone(self):
                # INSERT ... ON CONFLICT ... WHERE rejected the mismatched row.
                return None

        class Connection:
            def cursor(self):
                return Cursor()

        @contextmanager
        def postgres_connection():
            yield Connection()

        with patch.object(
            core_repository,
            "get_postgres_connection",
            postgres_connection,
        ), patch.object(
            core_repository,
            "_supabase_rest_enabled",
            return_value=True,
        ), patch.object(core_repository, "_rest_upsert") as rest_upsert:
            with self.assertRaises(core_repository.PlatformIdentityConflictError):
                core_repository.upsert_platform_config({"id": 12})

        rest_upsert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
