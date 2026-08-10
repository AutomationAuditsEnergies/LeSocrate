import unittest
from unittest.mock import patch

from utils import deepseek_client as client


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


class DeepSeekClientRetryTest(unittest.TestCase):
    def test_default_model_stays_deepseek_with_legacy_anthropic_environment(self):
        with patch.dict(
            client.os.environ,
            {
                "ANTHROPIC_API_KEY": "legacy-key",
                "FORMATION_LLM_PROVIDER": "anthropic",
                "FORMATION_CLAUDE_MODEL": "claude-sonnet-4-20250514",
            },
            clear=True,
        ):
            self.assertEqual(client.default_model(), "deepseek-v4-flash")

    def test_requires_deepseek_key_even_if_an_anthropic_key_exists(self):
        with patch.dict(
            client.os.environ,
            {
                "ANTHROPIC_API_KEY": "legacy-key",
                "FORMATION_LLM_PROVIDER": "anthropic",
            },
            clear=True,
        ), patch.object(client._http, "post") as post:
            with self.assertRaisesRegex(ValueError, "DEEPSEEK_API_KEY"):
                client.post_message(
                    [{"role": "user", "content": "hello"}],
                    model="pro",
                    max_tokens=100,
                )

        post.assert_not_called()

    def test_historical_model_alias_is_rejected_before_http(self):
        with patch.dict(
            client.os.environ,
            {
                "DEEPSEEK_API_KEY": "deepseek-key",
                "ANTHROPIC_API_KEY": "must-not-be-used",
                "ANTHROPIC_BASE_URL": "https://must-not-be-used.invalid",
                "FORMATION_LLM_PROVIDER": "anthropic",
                "LOCAL_DEV": "true",
            },
            clear=True,
        ), patch.object(client._http, "post") as post:
            with self.assertRaisesRegex(ValueError, "DeepSeek"):
                client.post_message(
                    [{"role": "user", "content": "hello"}],
                    model="claude-sonnet-4-20250514",
                    max_tokens=100,
                )

        post.assert_not_called()

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

    def test_pipeline_can_disable_client_http_retries(self):
        success = _FakeResponse(
            200,
            {"content": [{"type": "text", "text": "ne doit pas être appelée"}]},
        )
        with patch.dict(
            client.os.environ,
            {"DEEPSEEK_API_KEY": "test-key"},
        ), patch.object(
            client._http,
            "post",
            side_effect=[
                client._http.exceptions.ChunkedEncodingError(
                    "Response ended prematurely"
                ),
                success,
            ],
        ) as post, patch.object(client, "_sleep") as sleep:
            with self.assertRaises(client._http.exceptions.ChunkedEncodingError):
                client.post_message(
                    [{"role": "user", "content": "hello"}],
                    model="deepseek-v4-pro",
                    max_tokens=100,
                    http_max_attempts=1,
                )

        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()

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
            with self.assertRaises(client.DeepSeekAPIError) as raised:
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
