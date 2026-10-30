"""``python -m evals.present [--write | --check] [--site DIR [--check-site]]``

* ``--write``: render the committed outputs from the results files (``presentation.json``, the README block,
  ``docs/evals.md``, ``docs/evals-history.md``, ``docs/assets/eval-*.svg``) and write those that differ.
* ``--check``: render them again and exit 1 when any committed file differs, is missing or is left over (CI).
* ``--site DIR``: build the report page into ``DIR`` from ``presentation.json`` alone (standard library only);
  ``--check-site`` then checks it. ``--commit`` names the commit in the page's footer.

Exit codes: 0 ok; 1 a check found a difference or a problem; 2 the inputs do not fit (a results file of an unknown
kind, an input whose bytes changed …).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from evals.present import PRESENTATION_PATH, ROOT, PresentError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.present", description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write the committed outputs that differ")
    mode.add_argument(
        "--check", action="store_true", help="fail when a committed output differs from a render"
    )
    parser.add_argument("--site", type=Path, metavar="DIR", help="build the report page into DIR")
    parser.add_argument("--check-site", action="store_true", help="with --site: check the page it built")
    parser.add_argument("--commit", help="with --site: the commit the page is built from, for its footer")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--results-dir", type=Path, help="the results files (default: <root>/evals/results)")
    args = parser.parse_args(argv)
    if not (args.write or args.check or args.site):
        parser.error("give --write, --check or --site DIR")
    if args.check_site and not args.site:
        parser.error("--check-site checks the page --site builds")
    status = 0
    try:
        if args.write or args.check:
            from evals.present import build  # the project's environment (the results, evals.report)

            if args.write:
                written = build.write(args.root, args.results_dir)
                print(
                    "wrote " + (", ".join(written) if written else "nothing: every output is up to date"),
                    file=sys.stderr,
                )
            else:
                differ = build.check(args.root, args.results_dir)
                for relative in differ:
                    print(f"{relative}: differs from a fresh render", file=sys.stderr)
                if differ:
                    print("run python -m evals.present --write (and commit what it changes)", file=sys.stderr)
                    status = 1
                else:
                    print("every output is what the results files render", file=sys.stderr)
        if args.site:
            from evals.present import site

            source = args.root / PRESENTATION_PATH.relative_to(ROOT)
            doc = json.loads(source.read_text(encoding="utf-8"))
            site.build_site(doc, args.site, commit=args.commit)
            print(f"the report page → {args.site / 'index.html'}", file=sys.stderr)
            if args.check_site:
                problems = site.check_site(args.site, doc, forbidden=site.dataset_sentences())
                for problem in problems:
                    print(problem, file=sys.stderr)
                status = max(status, 1 if problems else 0)
    except PresentError as exc:
        print(f"python -m evals.present: {exc}", file=sys.stderr)
        return 2
    return status


if __name__ == "__main__":
    raise SystemExit(main())
