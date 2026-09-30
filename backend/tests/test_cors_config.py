import unittest

from flask import Flask

from utils.cors_config import configure_api_cors


class CorsConfigTest(unittest.TestCase):
    def test_patch_preflight_is_allowed_for_center_archive_route(self):
        origin = "https://polite-bush-07d4fdd03.1.azurestaticapps.net"
        app = Flask(__name__)
        configure_api_cors(app, [origin])

        @app.patch("/api/hr/platforms/<int:platform_id>/lifecycle")
        def update_lifecycle(platform_id):
            return {"platform_id": platform_id}

        response = app.test_client().options(
            "/api/hr/platforms/12/lifecycle",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "Content-Type,X-Auth-Token,Idempotency-Key",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), origin)
        self.assertIn("PATCH", response.headers.get("Access-Control-Allow-Methods", ""))
        allowed_headers = response.headers.get("Access-Control-Allow-Headers", "")
        self.assertIn("Content-Type", allowed_headers)
        self.assertIn("X-Auth-Token", allowed_headers)
        self.assertIn("Idempotency-Key", allowed_headers)


if __name__ == "__main__":
    unittest.main()
