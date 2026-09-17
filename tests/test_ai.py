import copy
import unittest
from unittest.mock import Mock, patch

from cmdc import ai, config


class OpenAIRequestTests(unittest.TestCase):
    def test_gpt_5_6_omits_temperature(self):
        cfg = copy.deepcopy(config.DEFAULTS)
        cfg["model"] = "gpt-5.6-luna"
        cfg["api_keys"] = {"openai": "test-key"}
        response = Mock(status_code=200, text="")
        response.json.return_value = {"choices": [{"message": {"content": "Fixed."}}]}

        with patch("cmdc.ai.requests.post", return_value=response) as post:
            self.assertEqual(ai.correct("fix me", cfg), "Fixed.")

        self.assertNotIn("temperature", post.call_args.kwargs["json"])
        self.assertEqual(post.call_args.kwargs["json"]["reasoning_effort"], "none")


class GeminiRequestTests(unittest.TestCase):
    def test_gemini_3_5_sets_minimal_thinking_level(self):
        cfg = copy.deepcopy(config.DEFAULTS)
        cfg["provider"] = "gemini"
        cfg["model"] = "gemini-3.5-flash-lite"
        cfg["api_keys"] = {"gemini": "test-key"}
        cfg["providers"]["gemini"]["body"]["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
        response = Mock(status_code=200, text="")
        response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Fixed."}]}}]
        }

        with patch("cmdc.ai.requests.post", return_value=response) as post:
            self.assertEqual(ai.correct("fix me", cfg), "Fixed.")

        thinking_cfg = post.call_args.kwargs["json"]["generationConfig"]["thinkingConfig"]
        self.assertNotIn("thinkingBudget", thinking_cfg)
        self.assertEqual(thinking_cfg["thinkingLevel"], "minimal")

    def test_gemini_3_7_sets_low_thinking_level(self):
        cfg = copy.deepcopy(config.DEFAULTS)
        cfg["provider"] = "gemini"
        cfg["model"] = "gemini-3.7-flash"
        cfg["api_keys"] = {"gemini": "test-key"}
        cfg["providers"]["gemini"]["body"]["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
        response = Mock(status_code=200, text="")
        response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Fixed."}]}}]
        }

        with patch("cmdc.ai.requests.post", return_value=response) as post:
            self.assertEqual(ai.correct("fix me", cfg), "Fixed.")

        thinking_cfg = post.call_args.kwargs["json"]["generationConfig"]["thinkingConfig"]
        self.assertNotIn("thinkingBudget", thinking_cfg)
        self.assertEqual(thinking_cfg["thinkingLevel"], "low")

    def test_gemini_2_5_uses_thinking_budget(self):
        cfg = copy.deepcopy(config.DEFAULTS)
        cfg["provider"] = "gemini"
        cfg["model"] = "gemini-2.5-flash"
        cfg["api_keys"] = {"gemini": "test-key"}
        cfg["providers"]["gemini"]["body"]["generationConfig"]["thinkingConfig"] = {"thinkingLevel": "minimal"}
        response = Mock(status_code=200, text="")
        response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Fixed."}]}}]
        }

        with patch("cmdc.ai.requests.post", return_value=response) as post:
            self.assertEqual(ai.correct("fix me", cfg), "Fixed.")

        thinking_cfg = post.call_args.kwargs["json"]["generationConfig"]["thinkingConfig"]
        self.assertNotIn("thinkingLevel", thinking_cfg)
        self.assertEqual(thinking_cfg["thinkingBudget"], 0)


if __name__ == "__main__":
    unittest.main()
