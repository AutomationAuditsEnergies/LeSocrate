"""The selected pipeline model must reach the correct API, including slides."""

import unittest
from unittest.mock import patch

from routes import formation_routes
from utils import anthropic_client


class DeepSeekFlashSelectionTest(unittest.TestCase):
    def test_flash_pipeline_and_slides_use_v41_flash(self):
        selected = formation_routes._PIPELINE_MODEL_ALIASES["flash"]
        self.assertEqual(selected, "deepseek-flash")
        with patch.dict(formation_routes.os.environ, {}, clear=True):
            self.assertEqual(formation_routes._resolve_pipeline_slide_model(selected), selected)
        self.assertEqual(
            formation_routes._resolve_pipeline_api_model(
                {"auto_pilot_model": "deepseek-v4-flash"}
            ),
            selected,
        )

    def test_explicit_pro_pipeline_keeps_pro_slides(self):
        with patch.dict(formation_routes.os.environ, {}, clear=True):
            self.assertEqual(
                formation_routes._resolve_pipeline_slide_model("deepseek-v4-pro"),
                "deepseek-v4-pro",
            )

    def test_explicit_claude_choice_keeps_anthropic_provider(self):
        with patch.dict(anthropic_client.os.environ, {
            "FORMATION_LLM_PROVIDER": "deepseek",
        }, clear=True):
            self.assertEqual(
                anthropic_client._resolve_provider("claude-sonnet-4-20250514"),
                "anthropic",
            )

    def test_flash_request_uses_deepseek_even_with_anthropic_server_default(self):
        response = type("Response", (), {
            "status_code": 200,
            "ok": True,
            "json": lambda self: {"content": [{"type": "text", "text": "ok"}]},
        })()
        with patch.dict(anthropic_client.os.environ, {
            "FORMATION_LLM_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "anthropic-test-key",
            "DEEPSEEK_API_KEY": "deepseek-test-key",
        }, clear=True), patch.object(
            anthropic_client._http, "post", return_value=response
        ) as post:
            result = anthropic_client.post_message(
                [{"role": "user", "content": "test"}], model="deepseek-v4-flash"
            )

        self.assertEqual(result, "ok")
        self.assertEqual(post.call_args.args[0], "https://api.deepseek.com/anthropic/v1/messages")
        self.assertEqual(post.call_args.kwargs["headers"]["x-api-key"], "deepseek-test-key")
        self.assertEqual(post.call_args.kwargs["json"]["model"], "deepseek-flash")


if __name__ == "__main__":
    unittest.main()
