import os
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from routes import admin_routes


class AdminSecretSafetyTest(unittest.TestCase):
    def test_historical_hardcoded_password_is_not_a_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(admin_routes._internal_admin_password_valid("secret123"))

    def test_deployment_hash_authenticates_without_plaintext_storage(self):
        password_hash = generate_password_hash("a-long-deployment-secret")
        with patch.dict(
            os.environ,
            {"INTERNAL_ADMIN_PASSWORD_HASH": password_hash},
            clear=True,
        ):
            self.assertTrue(
                admin_routes._internal_admin_password_valid("a-long-deployment-secret")
            )
            self.assertFalse(admin_routes._internal_admin_password_valid("wrong"))


if __name__ == "__main__":
    unittest.main()
