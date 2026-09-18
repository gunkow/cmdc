"""Live prompt evals using cmdc's provider and substitution pipeline."""

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from cmdc import ai, config


EVAL_DIR = Path(__file__).resolve().parents[1] / "evals"


def line_layout(text):
    """Compare blank lines, indentation, and Markdown line prefixes."""
    return [
        None if not line.strip() else re.match(
            r"^[ \t]*(?:[-*+] |\d+[.)] |#{1,6} )?", line
        ).group()
        for line in text.split("\n")
    ]


def grade(case, output):
    failures = []
    if not output.strip():
        failures.append("empty output")
    if line_layout(output) != line_layout(case["reference"]):
        failures.append("line breaks, blank lines, or Markdown prefixes changed")
    if case.get("must_change") and output == case["input"]:
        failures.append("input was not corrected")
    for literal in case.get("must_include", []):
        if literal not in output:
            failures.append(f"missing literal: {literal}")
    for pattern in case.get("must_match", []):
        if not re.search(pattern, output, re.IGNORECASE):
            failures.append(f"missing pattern: {pattern}")
    for pattern in case.get("must_not_match", []):
        if re.search(pattern, output, re.IGNORECASE):
            failures.append(f"forbidden pattern: {pattern}")
    if len(output.split()) > case["max_words"]:
        failures.append(f"exceeds {case['max_words']} words")
    if re.search(r"^(?:here(?:'s| is)|corrected (?:text|version)|output\s*:)", output, re.I):
        failures.append("added commentary")
    if output.startswith(('"', '“', '```')):
        failures.append("added wrapping quotes or code fence")
    return failures


def run_case(case, cfg, iteration):
    started = time.monotonic()
    result = {"id": case["id"], "iteration": iteration, "input": case["input"],
              "reference": case["reference"]}
    try:
        raw = ai.correct(case["input"], cfg)
        output = ai.apply_substitutions(raw, cfg)
        result.update(raw_output=raw, output=output,
                      raw_failures=grade(case, raw), failures=grade(case, output))
    except ai.AIError:
        # HTTP errors can contain credential-bearing URLs or response bodies.
        result.update(error="AIError", failures=["provider request failed; not scored"])
    result["elapsed_sec"] = round(time.monotonic() - started, 3)
    result["passed"] = not result["failures"]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    prompts = parser.add_mutually_exclusive_group()
    prompts.add_argument("--prompt", type=Path, help="Prompt file; defaults to evals/prompts/revised.txt")
    prompts.add_argument("--saved-prompt", action="store_true", help="Use the prompt saved in cmdc settings")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--case", action="append", dest="case_ids", help="Run only this case ID (repeatable)")
    parser.add_argument("--output", type=Path, help="JSON report path; defaults to ~/Documents/generated/")
    parser.add_argument("--list", action="store_true", help="List cases without making API requests")
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    cases_path = EVAL_DIR / "cases.json"
    cases_text = cases_path.read_text(encoding="utf-8")
    cases = json.loads(cases_text)
    if args.case_ids:
        unknown = set(args.case_ids) - {case["id"] for case in cases}
        if unknown:
            parser.error(f"unknown case IDs: {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case["id"] in args.case_ids]
    if args.list:
        for case in cases:
            print(f"{case['id']}: {case['purpose']}")
        return 0

    # Read without config.load(), whose automatic migrations can save settings.
    try:
        saved = json.loads(config.CONFIG_PATH.read_text(encoding="utf-8")) if config.CONFIG_PATH.exists() else {}
        cfg = config._merge(config.DEFAULTS, saved)
        prompt_path = args.prompt or EVAL_DIR / "prompts" / "revised.txt"
        if not args.saved_prompt:
            cfg["system_prompt"] = prompt_path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        parser.error("could not read the prompt or cmdc configuration")
    if not cfg["system_prompt"].strip():
        parser.error("the prompt must not be empty")
    if not config.api_key_for(cfg):
        parser.error("no API key available for the configured provider")

    started = datetime.now(timezone.utc)
    output_path = args.output or (
        Path.home() / "Documents" / "generated" /
        f"cmdc-evals-{started.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    )
    report = {
        "started_at": started.isoformat(),
        "provider": cfg["provider"], "model": config.model_for(cfg),
        "prompt_source": "saved settings" if args.saved_prompt else str(prompt_path.resolve()),
        "prompt": cfg["system_prompt"],
        "prompt_sha256": hashlib.sha256(cfg["system_prompt"].encode()).hexdigest(),
        "cases_sha256": hashlib.sha256(cases_text.encode()).hexdigest(),
        "substitutions_enabled": bool(cfg.get("substitutions_enabled")),
        "repeat": args.repeat, "results": [],
    }
    print(f"Provider: {report['provider']} | Model: {report['model']} | {len(cases) * args.repeat} requests", flush=True)
    for iteration in range(1, args.repeat + 1):
        for case in cases:
            result = run_case(case, cfg, iteration)
            report["results"].append(result)
            status = "ERROR" if "error" in result else "PASS" if result["passed"] else "FAIL"
            print(f"{status} [{iteration}/{args.repeat}] {case['id']} ({result['elapsed_sec']:.1f}s)", flush=True)
            if not result["passed"]:
                for failure in result["failures"]:
                    print(f"  {failure}", flush=True)
                if "output" in result:
                    print(f"  Output: {json.dumps(result['output'], ensure_ascii=False)}", flush=True)

    results = report["results"]
    report["total"] = len(results)
    report["passed"] = sum(result["passed"] for result in results)
    report["errors"] = sum("error" in result for result in results)
    report["raw_passed"] = sum(not result.get("raw_failures", ["error"]) for result in results)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{report['passed']}/{report['total']} passed; {report['errors']} provider errors. Raw model: {report['raw_passed']}/{report['total']} passed.")
    print(f"Report: {output_path.resolve()}")
    return 2 if report["errors"] else 1 if report["passed"] != report["total"] else 0


if __name__ == "__main__":
    sys.exit(main())
