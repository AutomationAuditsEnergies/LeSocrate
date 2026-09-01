import unittest

from utils.auth_tokens import issue_auth_token, verify_auth_token


class AuthTokenTest(unittest.TestCase):
    def test_signed_token_is_shared_without_process_memory(self):
        token = issue_auth_token(
            "student",
            {"nom": "Martin", "prenom": "Lina", "platform_id": 7, "log_id": 12},
        )
        self.assertEqual(
            verify_auth_token("student", token),
            {"nom": "Martin", "prenom": "Lina", "platform_id": 7, "log_id": 12},
        )

    def test_kind_and_signature_are_not_interchangeable(self):
        token = issue_auth_token("admin", {"account_type": "legacy_admin"})
        self.assertIsNone(verify_auth_token("student", token))
        self.assertIsNone(verify_auth_token("admin", token + "tampered"))


if __name__ == "__main__":
    unittest.main()
