"""The committed outputs: rendered from the results files, written (``--write``) or compared (``--check``).

This module needs the project's environment (:mod:`evals.report` renders the history page's earlier runs, and
:mod:`evals.present.model` reads the results files); the report page (:mod:`evals.present.site`) does not.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evals.present import BEGIN, END, ROOT, PresentError, charts, model, text

README = "README.md"
REPORT = "docs/evals.md"
HISTORY = "docs/evals-history.md"
PRESENTATION = "evals/present/presentation.json"
ASSETS = "docs/assets"
#: Every file ``--write`` writes and ``--check`` compares, relative to the repository's root.
OUTPUT_PATHS = (
    PRESENTATION,
    README,
    REPORT,
    HISTORY,
    *(f"{ASSETS}/eval-{name}-{theme}.svg" for name in charts.COMMITTED for theme in ("light", "dark")),
)
#: The results files ``docs/evals.md`` was rendered from up to 0.3.0 (``python -m evals.report``'s arguments): the
#: history page keeps that page as it was, from the same files.
HISTORY_INPUTS: dict[str, str | list[str]] = {
    "runs": ["2026-09-25-sonnet-test.json"],
    "rescored": "2026-09-25-sonnet-test-rescored.json",
    "prompt_runs": ["2026-09-30-claude-sonnet-5-test.json", "2026-09-30-claude-sonnet-5-dev.json"],
    "holdout_run": "2026-09-30-claude-sonnet-5-holdout.json",
    "holdout_rescored": "2026-09-30-claude-sonnet-5-holdout-rescored.json",
    "holdout2_run": "2026-10-01-claude-sonnet-5-holdout2.json",
    "holdout2_rescored": "2026-10-06-claude-sonnet-5-holdout2-rescored.json",
    "holdout3_run": "2026-10-06-claude-sonnet-5-holdout3.json",
    "without_land": "2026-10-08-claude-sonnet-5-without-land.json",
}


def legacy_page(results_dir: Path) -> str:
    """The page ``docs/evals.md`` was until 0.3.0, rendered by ``evals.report`` from its results files."""
    from evals import (
        report,
    )  # the project's environment: evals.report reads the scorer and the app's scam rule

    loaded: dict[str, Any] = {
        key: [report.load_results(results_dir / name) for name in value]
        if isinstance(value, list)
        else report.load_results(results_dir / value)
        for key, value in HISTORY_INPUTS.items()
    }
    prompt_note = next(
        (run["meta"]["prompt_note"] for run in loaded["prompt_runs"] if run["meta"].get("prompt_note")), None
    )
    runs = loaded.pop("runs")
    return report.render_markdown(runs, prompt_note=prompt_note, **loaded)


def splice(readme: str, block: str) -> str:
    """``readme`` with the text from :data:`BEGIN` to :data:`END` replaced by ``block`` (markers included)."""
    if readme.count(BEGIN) != 1 or readme.count(END) != 1 or readme.index(BEGIN) > readme.index(END):
        raise PresentError(f"README.md needs one {BEGIN} line and one {END} line after it")
    before, rest = readme.split(BEGIN, 1)
    _, after = rest.split(END, 1)
    return before + block.removesuffix("\n") + after


def render(doc: Mapping[str, Any], readme: str, legacy: str) -> dict[str, str]:
    """Every output of ``doc``: ``{path from the root: text}``."""
    outputs = {
        PRESENTATION: model.dumps(doc),
        README: splice(readme, text.readme_block(doc)),
        REPORT: text.report(doc),
        HISTORY: text.history(doc, legacy),
    }
    for name in charts.COMMITTED:
        for theme in ("light", "dark"):
            outputs[f"{ASSETS}/eval-{name}-{theme}.svg"] = charts.svg(name, doc, theme)
    return outputs


def outputs(root: Path = ROOT, results_dir: Path | None = None) -> dict[str, str]:
    """What ``--write`` writes under ``root``, rendered from ``results_dir`` (``root``'s own by default)."""
    results = results_dir or root / "evals" / "results"
    readme = root / README
    if not readme.is_file():
        raise PresentError(f"{readme} is missing")
    return render(model.build(results), readme.read_text(encoding="utf-8"), legacy_page(results))


def write(root: Path = ROOT, results_dir: Path | None = None) -> list[str]:
    """Write every output that differs; returns their paths."""
    written = []
    for relative, content in outputs(root, results_dir).items():
        path = root / relative
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            written.append(relative)
    return written


def _stale(root: Path) -> list[str]:
    """Evaluation charts in ``docs/assets`` that nothing renders any more."""
    assets = root / ASSETS
    if not assets.is_dir():
        return []
    expected = {Path(path).name for path in OUTPUT_PATHS if path.startswith(ASSETS)}
    return sorted(f"{ASSETS}/{path.name}" for path in assets.glob("eval-*") if path.name not in expected)


def check(root: Path = ROOT, results_dir: Path | None = None) -> list[str]:
    """The outputs under ``root`` that differ from a fresh render, are missing, or are left over."""
    differ = []
    for relative, content in outputs(root, results_dir).items():
        path = root / relative
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            differ.append(relative)
    return differ + _stale(root)
