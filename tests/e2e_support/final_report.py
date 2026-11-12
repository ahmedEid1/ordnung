"""A synthetic final run's ``presentation.json``, for the report page's end-to-end cases (``web/e2e/eval-report.spec.ts``).

``python tests/e2e_support/final_report.py --scenario good --out DIR`` builds one of the synthetic final runs of
``tests/helpers_final.py`` (a hand-built final of ``tests/test_present_final.py`` completed to the real analysis's
shape, or ``realistic``, a real analysis of synthetic reads) in a temporary checkout under ``DIR``, and writes the
``presentation.json`` the presenter makes of it to ``DIR/evals/present/presentation.json``; the checkout is removed
again. The spec then builds the page from it as the Pages job builds the real one, with the standard library only:
``python3 -m evals.present --root DIR --site SITE --check-site``.

It needs the project's environment (the analysis and the test helpers: ``.venv``), writes under ``DIR`` only (never
under the repository's ``evals/results`` or ``evals/preregistration``) and makes no model call. Exit codes: 0 written;
2 a scenario it does not know (nothing written).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
#: The repository (for ``evals``) and its tests (for the synthetic finals).
PATHS = (ROOT, ROOT / "tests")


def main(argv: Sequence[str] | None = None) -> int:
    for path in PATHS:
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from evals.present import model

    import helpers_final

    parser = argparse.ArgumentParser(
        prog="final_report.py", description=__doc__.split("\n\n")[0] if __doc__ else None
    )
    parser.add_argument("--scenario", required=True, choices=[*helpers_final.SCENARIO_IDS, "realistic"])
    parser.add_argument("--out", type=Path, required=True, help="the folder to write into")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    checkout = out / "checkout"
    if args.scenario == "realistic":
        root = helpers_final.realistic_root(checkout)
    else:
        root = helpers_final.scenario_root(checkout, args.scenario)
    doc = model.build(root / "evals" / "results")
    target = out / "evals" / "present" / "presentation.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(model.dumps(doc), encoding="utf-8")
    shutil.rmtree(checkout)  # its results files are links to the repository's: removed, never followed
    print(f"{args.scenario}: {target}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
