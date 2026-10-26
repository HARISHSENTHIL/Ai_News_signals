#!/usr/bin/env python3
"""Validate the LinkedIn side before trusting it with a real post.

    python scripts/check_linkedin.py             # token, scope, person URN, days left
    python scripts/check_linkedin.py --caption   # also show the escaped commentary

--caption renders today's draft the way LinkedIn will receive it, escaping and
all. Worth a look once: little-text escaping is the part most likely to make a
post read wrongly, and it is invisible until published.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from newsletter.pipeline import _caption_for, run_dir  # noqa: E402
from newsletter.publish.linkedin import LinkedInError, LinkedInPublisher  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--caption", action="store_true", help="show the escaped commentary")
    parser.add_argument("--date", help="which draft to read, YYYY-MM-DD")
    args = parser.parse_args()

    try:
        publisher = LinkedInPublisher()
        print(publisher.preflight())
    except LinkedInError as exc:
        print(f"FAIL: {exc}")
        return 1
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 1

    if args.caption:
        run_date = date.fromisoformat(args.date) if args.date else date.today()
        draft_path = run_dir(run_date) / "draft.json"
        if not draft_path.exists():
            print(f"\nno draft at {draft_path} - run the pipeline first")
            return 1
        post = json.loads(draft_path.read_text())["post"]
        print("\n--- commentary as LinkedIn receives it ---")
        print(_caption_for("linkedin", post))
        print("--- end ---")

    return 0


if __name__ == "__main__":
    sys.exit(main())
