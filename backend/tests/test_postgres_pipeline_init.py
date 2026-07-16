import unittest
from io import BytesIO
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

    def test_init_creates_platform_in_pipeline_store_before_job(self):
        call_order = []

        def create_platform(**kwargs):
            call_order.append(("platform", kwargs))
            return {"id": 123, "name": kwargs["name"], "status": "pending"}

        def create_job(**kwargs):
            call_order.append(("job", kwargs))
            return 456

        def link(platform_id, job_id):
            call_order.append(("link", {"platform_id": platform_id, "job_id": job_id}))

        with patch(
            "routes.formation_routes.PIPELINE_DATABASE_BACKEND",
            "sqlite",
        ), patch(
            "repositories.pipeline_repository.create_pipeline_platform",
            side_effect=create_platform,
        ), patch(
            "routes.formation_routes.create_job",
            side_effect=create_job,
        ), patch(
            "repositories.pipeline_repository.link_pipeline_platform_to_job",
            side_effect=link,
        ):
            response = self.client.post(
                "/api/formation/init",
                json={
                    "platform_name": "TP Vente 2026",
                    "tp_name": "TP Vente",
                    "rncp_code": "RNCP12345",
                    "total_hours": 14,
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual([entry[0] for entry in call_order], ["platform", "job", "link"])
        self.assertEqual(call_order[0][1]["center_account_id"], 42)
        self.assertEqual(call_order[1][1]["platform_id"], 123)
        self.assertEqual(call_order[2][1], {"platform_id": 123, "job_id": 456})
        self.assertEqual(response.get_json()["job_id"], 456)

    def test_postgres_init_uses_one_atomic_aggregate_write(self):
        aggregate = {
            "platform": {"id": 123, "name": "TP Vente 2026", "status": "pending"},
            "job_id": 456,
        }
        with patch(
            "routes.formation_routes.PIPELINE_DATABASE_BACKEND",
            "postgres",
        ), patch(
            "repositories.pipeline_repository.create_postgres_pipeline_aggregate",
            return_value=aggregate,
        ) as create_aggregate, patch(
            "routes.formation_routes.create_job",
        ) as legacy_create_job:
            response = self.client.post(
                "/api/formation/init",
                json={
                    "platform_name": "TP Vente 2026",
                    "tp_name": "TP Vente",
                    "rncp_code": "RNCP12345",
                    "total_hours": 14,
                    "model": "pro",
                },
            )

        self.assertEqual(response.status_code, 201)
        legacy_create_job.assert_not_called()
        create_aggregate.assert_called_once_with(
            platform_name="TP Vente 2026",
            center_account_id=42,
            tp_name="TP Vente",
            rncp_code="RNCP12345",
            total_hours=14,
            nb_days=2,
            model="pro",
        )

    def test_init_test_validates_every_upload_before_any_database_write(self):
        with patch(
            "repositories.pipeline_repository.create_postgres_pipeline_aggregate",
        ) as create_aggregate, patch(
            "repositories.pipeline_repository.create_pipeline_platform",
        ) as create_platform, patch(
            "routes.formation_routes.create_job",
        ) as create_job:
            response = self.client.post(
                "/api/formation/init-test",
                data={
                    "platform_name": "TP Vente test",
                    "tp_name": "TP Vente",
                    "rncp_code": "RNCP12345",
                    "total_hours": "14",
                    "docs": [
                        (BytesIO(b"Premier document valide"), "jour-1.txt"),
                        (BytesIO(b"format invalide"), "jour-2.pdf"),
                    ],
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("jour-2.pdf", response.get_json()["error"])
        create_aggregate.assert_not_called()
        create_platform.assert_not_called()
        create_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
