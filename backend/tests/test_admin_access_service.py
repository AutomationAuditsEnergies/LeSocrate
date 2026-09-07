import unittest
from unittest.mock import patch

from services import admin_access_service


class AdminAccessServiceTest(unittest.TestCase):
    def test_active_center_with_database_grant_can_access_pipeline(self):
        with patch.object(
            admin_access_service,
            "postgres_enabled",
            return_value=True,
        ), patch.object(
            admin_access_service,
            "get_training_center_by_id",
            return_value={
                "id": 12,
                "username": "newpiprod@gmail.com",
                "is_active": True,
                "pipeline_access_enabled": True,
            },
        ):
            permissions = admin_access_service.get_admin_permissions(
                "training_center",
                12,
            )

        self.assertEqual(permissions, {"formation_pipeline": True})

    def test_revoked_or_inactive_center_fails_closed(self):
        for account in (
            {
                "id": 12,
                "is_active": True,
                "pipeline_access_enabled": False,
            },
            {
                "id": 12,
                "is_active": False,
                "pipeline_access_enabled": True,
            },
            None,
        ):
            with self.subTest(account=account), patch.object(
                admin_access_service,
                "postgres_enabled",
                return_value=True,
            ), patch.object(
                admin_access_service,
                "get_training_center_by_id",
                return_value=account,
            ):
                self.assertFalse(
                    admin_access_service.can_access_formation_pipeline(
                        "training_center",
                        12,
                    )
                )

    def test_legacy_admin_never_inherits_center_permission(self):
        with patch.object(
            admin_access_service,
            "get_training_center_by_id",
        ) as lookup:
            permissions = admin_access_service.get_admin_permissions(
                "legacy_admin",
                None,
            )

        self.assertEqual(permissions, {"formation_pipeline": False})
        lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
