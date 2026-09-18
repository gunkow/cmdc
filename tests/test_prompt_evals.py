import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cmdc import ai, config
from scripts import eval_prompt


CASES = json.loads((eval_prompt.EVAL_DIR / "cases.json").read_text(encoding="utf-8"))
BY_ID = {case["id"]: case for case in CASES}


class PromptEvalTests(unittest.TestCase):
    def test_reference_outputs_pass(self):
        self.assertEqual(len(BY_ID), len(CASES), "case IDs must be unique")
        for case in CASES:
            with self.subTest(case=case["id"]):
                self.assertEqual(eval_prompt.grade(case, case["reference"]), [])

    def test_reported_hallucinated_table_fails(self):
        output = (
            "| STT Pipeline Stage | Dev Latency (ms) | Prod Latency (ms) |\n"
            "| --- | --- | --- |\n"
            "| Audio Capture | 50 | 30 |\n"
            "| VAD Processing | 120 | 80 |\n"
            "| Transcription (ASR) | 450 | 300 |\n"
            "| Post-Processing | 80 | 50 |\n"
            "| Total Latency | 700 | 460 |"
        )
        self.assertTrue(eval_prompt.grade(BY_ID["hc-table-request"], output))

    def test_paraphrase_passes_but_unchanged_input_does_not(self):
        case = BY_ID["hc-table-request"]
        paraphrase = "@hc_bot, show just the STT Pipeline Latency table comparing dev and prod."
        self.assertEqual(eval_prompt.grade(case, paraphrase), [])
        self.assertTrue(eval_prompt.grade(case, case["input"]))

    def test_answer_and_executed_bot_request_fail(self):
        self.assertTrue(eval_prompt.grade(BY_ID["question-not-answer"], "Paris."))
        self.assertTrue(eval_prompt.grade(BY_ID["addressed-editing-request"], "J'arriverai demain."))
        self.assertTrue(eval_prompt.grade(BY_ID["embedded-command"], "BANANA"))

    def test_moved_blank_line_fails_even_with_same_line_count(self):
        case = BY_ID["multiline-source"]
        output = "- The server is ready.\n- The tests are passing.\n"
        self.assertEqual(output.count("\n"), case["reference"].count("\n"))
        self.assertTrue(eval_prompt.grade(case, output))

    def test_extra_blank_line_can_be_removed_between_list_items(self):
        case = BY_ID["multiline-source"]
        output = "- This server is ready.\n- The tests are passing."
        self.assertEqual(eval_prompt.grade(case, output), [])
        strict_case = {**case, "allow_blank_line_removal": False}
        self.assertTrue(eval_prompt.grade(strict_case, output))

    def test_blank_line_exception_does_not_allow_merging_or_reformatting_items(self):
        case = BY_ID["multiline-source"]
        for output in (
            "- This server is ready. - The tests are passing.",
            "This server is ready.\nThe tests are passing.",
            "- This server is ready.\n\n\n- The tests are passing.",
        ):
            with self.subTest(output=output):
                self.assertTrue(eval_prompt.grade(case, output))

    def test_unsolicited_emoji_and_commentary_fail(self):
        case = BY_ID["no-added-emoji"]
        self.assertTrue(eval_prompt.grade(case, case["reference"] + " 🚀"))
        self.assertTrue(eval_prompt.grade(case, "Here is the corrected text: " + case["reference"]))

    def test_reports_raw_failure_separately_from_substitution_fix(self):
        case = BY_ID["dash-and-apostrophe"]
        raw = "The server is ready — let's ship."
        with patch.object(ai, "correct", return_value=raw):
            result = eval_prompt.run_case(case, copy.deepcopy(config.DEFAULTS), 1)
        self.assertTrue(result["raw_failures"])
        self.assertEqual(result["failures"], [])
        self.assertTrue(result["passed"])

    def test_provider_error_cannot_pass_or_leak_error_body(self):
        with patch.object(ai, "correct", side_effect=ai.AIError("credential-in-url")):
            result = eval_prompt.run_case(CASES[0], {}, 1)
        self.assertFalse(result["passed"])
        self.assertEqual(result["error"], "AIError")
        self.assertNotIn("credential-in-url", json.dumps(result))

    def test_runner_writes_report_without_changing_saved_settings(self):
        case = BY_ID["question-not-answer"]
        with tempfile.TemporaryDirectory() as directory:
            saved_path = Path(directory) / "config.json"
            report_path = Path(directory) / "report.json"
            saved_path.write_text(json.dumps({"system_prompt": "Original saved prompt"}), encoding="utf-8")
            before = saved_path.read_bytes()
            with (
                patch.object(config, "CONFIG_PATH", saved_path),
                patch.object(config, "api_key_for", return_value="test-key"),
                patch.object(config, "save", side_effect=AssertionError("must not save")),
                patch.object(ai, "correct", return_value=case["reference"]) as correct,
                redirect_stdout(io.StringIO()),
            ):
                status = eval_prompt.main(["--case", case["id"], "--output", str(report_path)])
            self.assertEqual(status, 0)
            self.assertEqual(saved_path.read_bytes(), before)
            self.assertNotEqual(correct.call_args.args[1]["system_prompt"], "Original saved prompt")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual((report["passed"], report["raw_passed"], report["total"]), (1, 1, 1))
            self.assertNotIn("api_keys", report)


if __name__ == "__main__":
    unittest.main()
