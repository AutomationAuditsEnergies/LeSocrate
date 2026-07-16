import unittest
from unittest.mock import patch

from utils import anthropic_client as client


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self.headers = {}

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


class AnthropicClientRetryTest(unittest.TestCase):
    def test_retries_chunked_response_then_returns_text(self):
        success = _FakeResponse(
            200,
            {"content": [{"type": "text", "text": "ok apres retry"}]},
        )

        with patch.dict(
            client.os.environ,
            {
                "DEEPSEEK_API_KEY": "test-key",
                "FORMATION_LLM_PROVIDER": "deepseek",
                "LLM_HTTP_MAX_ATTEMPTS": "3",
            },
        ), patch.object(
            client._http,
            "post",
            side_effect=[client._http.exceptions.ChunkedEncodingError("Response ended prematurely"), success],
        ) as post, patch.object(client, "_sleep") as sleep:
            result = client.post_message(
                [{"role": "user", "content": "hello"}],
                model="deepseek-v4-pro",
                max_tokens=100,
            )

        self.assertEqual(result, "ok apres retry")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(sleep.call_count, 1)

    def test_does_not_retry_insufficient_balance(self):
        response = _FakeResponse(
            402,
            {"error": {"type": "unknown_error", "message": "Insufficient Balance"}},
        )

        with patch.dict(
            client.os.environ,
            {
                "DEEPSEEK_API_KEY": "test-key",
                "FORMATION_LLM_PROVIDER": "deepseek",
                "LLM_HTTP_MAX_ATTEMPTS": "3",
            },
        ), patch.object(client._http, "post", return_value=response) as post:
            with self.assertRaises(client.AnthropicAPIError) as raised:
                client.post_message(
                    [{"role": "user", "content": "hello"}],
                    model="deepseek-v4-pro",
                    max_tokens=100,
                )

        self.assertEqual(post.call_count, 1)
        self.assertEqual(raised.exception.status_code, 402)
        self.assertTrue(raised.exception.is_deterministic)


if __name__ == "__main__":
    unittest.main()
