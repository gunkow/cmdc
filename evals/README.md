# Prompt evals

These 15 cases check that cmdc improves requests instead of executing them,
while still applying editing instructions that have separate source text.
They cover the reported HC table failure, an escaped mention, a request without
a recipient, a question, translation with and without source text, a request to
another bot, shortening, embedded commands, blank lines and lists, numbers,
emoji, Markdown, URLs, identifiers, and punctuation.

## Run

From the repository root:

```bash
./.venv/bin/python scripts/eval_prompt.py
./.venv/bin/python scripts/eval_prompt.py --prompt evals/prompts/original.txt
./.venv/bin/python scripts/eval_prompt.py --saved-prompt --repeat 3
./.venv/bin/python scripts/eval_prompt.py --case hc-table-request --repeat 3
./.venv/bin/python scripts/eval_prompt.py --list
```

The runner uses the provider, model, credentials, endpoint, and substitutions
from cmdc settings. Each case makes one real API request per repetition and may
incur provider charges. `--list` and the unit tests make no API requests.

The default prompt is `prompts/revised.txt`. It contains the revised rules
with explicit language and escaping rules and three examples. The examples use
different wording and languages from the eval cases. `--saved-prompt` tests the
current app prompt instead.
The runner reads settings without saving or migrating them and does not touch
the clipboard or running app.

## Read results

Each case includes an illustrative reference and explicit checks. Wording can
vary when it preserves the required meaning. Checks cover required terms,
forbidden answers or fabricated measurements, word limits, corrections to
known mistakes, and line layout. Blank-line positions, indentation, and list
markers are compared against the reference layout, after removing any editing
directive. The multiline-list case allows removing extra blank lines between
items, but still requires separate lines and unchanged list markers. Identical
input fails where correction is required.

JSON reports default to `~/Documents/generated/cmdc-evals-<timestamp>.json`;
choose a path with `--output`. Reports contain inputs, references, raw responses,
final outputs, check failures, request durations, provider/model, the exact
prompt and its hash, and a hash of the cases. Raw and post-substitution scores
are separate so substitutions cannot conceal prompt failures. API errors are
reported separately and never count as passes. Credentials and endpoint URLs
are omitted.

These are deterministic checks, not a semantic judge. A pass does not prove
perfect meaning or tone preservation; review saved outputs and repeat runs to
check variation. Exit codes: `0` for all final-output checks passing, `1` for
behavioral failures, and `2` for request or configuration errors.

## Extend

Add cases to `cases.json` with `id`, `purpose`, `input`, `reference`, and
`max_words`. Optional checks are `must_include` (case-sensitive literals),
`must_match` and `must_not_match` (case-insensitive Python regexes), and
`must_change`. Set `allow_blank_line_removal` to permit deleting blank lines
without adding or moving them or merging nonblank lines. The regression tests verify that reference outputs pass and
known bad outputs fail, including the fabricated table from the original bug.
