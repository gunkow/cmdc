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


if __name__ == "__main__":
    unittest.main()
