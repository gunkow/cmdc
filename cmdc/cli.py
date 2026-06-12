"""Test the correction pipeline without hotkeys: cmdc-fix "some text" (or stdin)."""

import sys

from . import ai, config


def main():
    text = " ".join(sys.argv[1:]).strip() or sys.stdin.read().strip()
    if not text:
        print("usage: cmdc-fix <text>  (or pipe text via stdin)", file=sys.stderr)
        sys.exit(1)
    cfg = config.load()
    try:
        fixed = ai.correct(text, cfg)
    except ai.AIError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
    print(ai.apply_substitutions(fixed, cfg))


if __name__ == "__main__":
    main()
