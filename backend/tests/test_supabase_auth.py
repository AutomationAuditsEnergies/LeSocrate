import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from utils import supabase_auth


class SupabaseAuthTokenTest(unittest.TestCase):
    def setUp(self):
        self.issuer = "https://project-ref.supabase.co/auth/v1"
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.public_key = self.private_key.public_key()

    def _token(self, **overrides):
        now = int(time.time())
        claims = {
            "aud": "authenticated",
            "exp": now + 3600,
            "iat": now,
            "iss": self.issuer,
            "role": "authenticated",
            "session_id": "3d1867e8-1e3d-4e97-a26c-cf78911cd863",
            "sub": "0ac71ef2-930a-4b90-88b2-c7a576d96c19",
            "email": "centre@example.test",
        }
        claims.update(overrides)
        return jwt.encode(
            claims,
            self.private_key,
            algorithm="ES256",
            headers={"kid": "test-signing-key"},
        )

    def test_accepts_a_valid_supabase_session_jwt(self):
        jwks_client = SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(
                key=self.public_key
            )
        )
        with patch.object(supabase_auth, "_issuer", self.issuer), patch.object(
            supabase_auth,
            "_jwks_client",
            jwks_client,
        ):
            claims = supabase_auth.verify_supabase_access_token(self._token())

        self.assertEqual(
            claims["sub"],
            "0ac71ef2-930a-4b90-88b2-c7a576d96c19",
        )
        self.assertEqual(claims["role"], "authenticated")

    def test_rejects_wrong_role_and_expired_tokens(self):
        jwks_client = SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(
                key=self.public_key
            )
        )
        with patch.object(supabase_auth, "_issuer", self.issuer), patch.object(
            supabase_auth,
            "_jwks_client",
            jwks_client,
        ):
            self.assertIsNone(
                supabase_auth.verify_supabase_access_token(
                    self._token(role="service_role")
                )
            )
            self.assertIsNone(
                supabase_auth.verify_supabase_access_token(
                    self._token(exp=int(time.time()) - 1)
                )
            )

    def test_extracts_only_a_bearer_token(self):
        self.assertEqual(
            supabase_auth.extract_bearer_token("Bearer signed-token"),
            "signed-token",
        )
        self.assertEqual(
            supabase_auth.extract_bearer_token("bearer signed-token"),
            "signed-token",
        )
        self.assertIsNone(supabase_auth.extract_bearer_token("Basic value"))
        self.assertIsNone(supabase_auth.extract_bearer_token(""))


if __name__ == "__main__":
    unittest.main()
