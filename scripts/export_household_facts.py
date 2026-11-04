"""Write ``evals/ask/heldout/household-facts.json``: what the blind writer of "Ask: new questions on the demo
household" knows of the household ledger, exported from the household group's constants (``evals/ask/household.py``)
and the sample life's truth — the member, the letters filed for him, his numbers and his passport's expiry — and
nothing of the development set's household questions.

    python -m scripts.export_household_facts            # write the file
    python -m scripts.export_household_facts --check    # exit 1 when the committed file is not what this writes
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from evals.ask.heldout import HELDOUT_DIR
from evals.ask.household import FILED, MEMBER_NAME, MEMBER_NUMBERS, household_truth

PATH = HELDOUT_DIR / "household-facts.json"
SCHEMA = "ask-heldout-household/1"
ABOUT = (
    "The household ledger is the base ledger with one person added to the household, the member below, and two "
    "letters filed for him: in the sample life they are the person's, and in this ledger they are his. On every "
    "page of them, in what was read from them and in their case's title, the person's given name becomes his (they "
    "share the surname) and the person's health insurance number and passport number become his own numbers below. "
    "The sender, the dates, the amounts and the to-dos stay the letters' own, so his passport expires on the date "
    "below. His numbers stand on no letter of the person's, and the person's numbers those two letters showed stand "
    "on none: in this ledger the person has no health insurance number and no passport of their own. Every other "
    "letter, the person's tax ID among them, stays the person's."
)


def facts() -> dict[str, Any]:
    """The file's content (the expiry read from the sample life's truth)."""
    expiry = household_truth().member_dates[0]
    return {
        "schema": SCHEMA,
        "about": ABOUT,
        "member": MEMBER_NAME,
        "letters": list(FILED),
        "numbers": [
            {"letter": letter, "label": label, "value": value}
            for (letter, label), value in MEMBER_NUMBERS.items()
        ],
        "passport_expiry": expiry.isoformat(),
    }


def rendered() -> str:
    return json.dumps(facts(), ensure_ascii=False, indent=1) + "\n"


def main(argv: Sequence[str] | None = None, *, path: Path = PATH) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.export_household_facts", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed file differs")
    args = parser.parse_args(argv)
    if args.check:
        if not path.is_file() or path.read_text(encoding="utf-8") != rendered():
            print(
                f"{path.name} is not what the household group gives: run python -m scripts.export_household_facts"
            )
            return 1
        print(f"{path.name}: up to date")
        return 0
    path.write_text(rendered(), encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
