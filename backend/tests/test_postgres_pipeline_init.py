import unittest
from unittest.mock import patch

from flask import Flask

from routes.formation_routes import formation_bp


class PostgresPipelineInitRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(formation_bp)
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["is_admin"] = True
            session["admin_account_type"] = "training_center"
            session["admin_account_id"] = 42
        self.permission_patch = patch(
            "routes.formation_routes.can_access_formation_pipeline",
            return_value=True,
        )
        self.permission_patch.start()

    def tearDown(self):
        self.permission_patch.stop()

    def test_manual_init_is_retired_before_any_database_write(self):
        with patch(
            "repositories.pipeline_repository.create_postgres_pipeline_aggregate",
        ) as create_aggregate, patch(
            "repositories.pipeline_repository.create_pipeline_platform",
        ) as create_platform, patch(
            "routes.formation_routes.create_job",
        ) as create_job:
            response = self.client.post(
                "/api/formation/init",
                json={
                    "platform_name": "TP Vente 2026",
                    "tp_name": "TP Vente",
                    "rncp_code": "RNCP12345",
                    "total_hours": 14,
                },
            )

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.get_json()["code"], "teacher_order_required")
        create_aggregate.assert_not_called()
        create_platform.assert_not_called()
        create_job.assert_not_called()

    def test_manual_test_init_is_also_retired_before_any_database_write(self):
        with patch(
            "repositories.pipeline_repository.create_postgres_pipeline_aggregate",
        ) as create_aggregate, patch(
            "repositories.pipeline_repository.create_pipeline_platform",
        ) as create_platform, patch(
            "routes.formation_routes.create_job",
        ) as create_job:
            response = self.client.post("/api/formation/init-test")

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.get_json()["code"], "teacher_order_required")
        create_aggregate.assert_not_called()
        create_platform.assert_not_called()
        create_job.assert_not_called()

    def test_training_center_without_permission_cannot_reach_retired_init(self):
        with patch(
            "routes.formation_routes.can_access_formation_pipeline",
            return_value=False,
        ):
            response = self.client.post("/api/formation/init", json={})

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
