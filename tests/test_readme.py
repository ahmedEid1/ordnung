"""README.md, which is also the PyPI page: short, no Mermaid, a CI badge that shows ``main``, the Python versions
CI tests and pyproject.toml allows, an install that says what it needs and names no tag, a scam caption that says
what SPEC §21 says, a trust table that names the phone's listener, a pre-registration bullet that says what the
evaluation card says, the privacy statement SPEC §1 asks for, and no source comments left in it.

Most of the rest of what README states is pinned where the fact lives (``tests/test_docs_claims.py``,
``test_present.py``, ``test_release_workflow.py`` and the others that read it).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from ordnung.secretary.triggers import Ledger
from test_ci_workflow import _workflow

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
#: The README is the PyPI page and the first thing a visitor reads: what does not fit is in docs/guide.md.
MAX_LINES = 250
REPOSITORY = "https://github.com/ahmedEid1/ordnung"
#: SPEC §1's lead to its privacy statement, which is in italics after it.
SPEC_PRIVACY = "**Honest privacy statement (use this wording everywhere):** *"
#: A command line that installs Ordnung with pipx or uv.
_INSTALL = re.compile(r"\b(?:pipx|uv tool) install\b")


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """``text`` with every run of whitespace as one space."""
    return " ".join(text.split())


def _plain(text: str) -> str:
    """``text`` flat, with each Markdown link as its words (``[uv](https://…)`` reads ``uv``)."""
    return _flat(re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text))


def _card_row(name: str) -> str:
    """The evaluation card's row ``| name | … |`` in docs/evals.md, flat."""
    card = (ROOT / "docs" / "evals.md").read_text(encoding="utf-8")
    (row,) = [line for line in card.splitlines() if line.startswith(f"| {name} |")]
    return _flat(row)


def _section(heading: str) -> str:
    """README's ``## heading``, up to the next ``## `` heading."""
    return _readme().split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


def test_the_readme_is_under_250_lines() -> None:
    lines = _readme().splitlines()
    assert len(lines) < MAX_LINES, f"README.md has {len(lines)} lines; move the detail to docs/guide.md"


def test_the_readme_draws_no_mermaid() -> None:
    """PyPI shows README.md as its project page and draws no Mermaid; the architecture's diagram is in
    docs/architecture.md, and README draws its own in plain text."""
    readme = _readme()
    assert "```mermaid" not in readme
    assert "```text\n" in readme


def test_the_readme_s_ci_badge_counts_pushes_to_main_only() -> None:
    """CI also runs on pull requests and on a Monday schedule that checks the newest dependencies; the badge
    shows the runs on ``main`` after a merge."""
    (badge,) = re.findall(r'<img alt="CI" src="([^"]+)"', _readme())
    assert badge == f"{REPOSITORY}/actions/workflows/ci.yml/badge.svg?branch=main&amp;event=push"
    triggers = _workflow()[True]  # PyYAML reads the key ``on:`` as True
    assert triggers["push"] == {"branches": ["main"]}
    assert "pull_request" in triggers and "schedule" in triggers


def test_the_readme_s_python_versions_are_the_ones_ci_tests_and_pyproject_allows() -> None:
    """The badge and the CI bullet name the backend job's Python versions, and the install names the oldest that
    pyproject.toml's ``requires-python`` allows, which is the oldest CI tests."""
    readme = _readme()
    versions = _workflow()["jobs"]["backend"]["strategy"]["matrix"]["python"]
    oldest, newest = versions[0], versions[-1]
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["requires-python"] == f">={oldest}"
    badge = f'<img alt="Python {oldest}–{newest}" src="https://img.shields.io/badge/python-{oldest}%E2%80%93{newest}-'
    assert badge in readme
    assert f"You need Git, Python {oldest} or newer," in _plain(readme)
    tested = ", ".join(versions[:-1]) + f" and {newest}"
    assert f"the backend tests on Python {tested};" in _flat(readme)


def test_the_readme_names_git_and_uv_or_pipx_before_its_first_install_line() -> None:
    """Ordnung installs from its Git repository with uv or pipx, so a reader learns what to have first."""
    lines = _readme().splitlines()
    first = next(number for number, line in enumerate(lines) if _INSTALL.search(line))
    before = _plain("\n".join(lines[:first]))
    assert re.search(r"\bGit\b", before), "say that Git is needed before the first install line"
    assert re.search(r"\buv\b", before) and "pipx" in before, "say uv or pipx before the first install line"
    assert "git+https://github.com/ahmedEid1/ordnung" in lines[first]


def test_the_readme_installs_no_tag() -> None:
    """No release has a tag on GitHub yet: an install line names the repository, and docs/guide.md's *Updating*
    says how to install a release by its tag (``@vX.Y.Z``)."""
    install_lines = [line for line in _readme().splitlines() if _INSTALL.search(line)]
    assert install_lines
    assert [line for line in install_lines if "@v" in line] == []


def test_the_readme_s_scam_caption_says_where_the_dates_show_and_what_brings_the_reminders_back() -> None:
    """SPEC §21 "Scam checks": a flagged letter's dates still show on its page and in the warning, *I checked —
    it's genuine* brings its to-dos back, and it never gets a GiroCode (``Ledger.scam_checked``)."""
    cells = [cell.split("</td>", 1)[0] for cell in _readme().split("<td")[1:]]
    (caption,) = [_flat(cell) for cell in cells if 'src="docs/assets/scam.png"' in cell]
    for words in (
        "Its dates still show on its page and in the warning",
        "stay off Today, the calendar and the notification until you choose <i>I checked — it's genuine</i>",
        "it never gets a GiroCode",
    ):
        assert words in caption, words
    scam = _flat((ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8"))
    scam = scam.split("**Scam checks (code, not model).**", 1)[1].split("**GiroCode (EPC-QR).**", 1)[0]
    for words in (
        "its dates still show on its page",
        'and in the warning ("It asks you to act by …")',
        "*I checked — it's genuine* dismisses the warning",
        "(`Ledger.scam_checked`), its to-dos count again",
        "but never get a GiroCode",
    ):
        assert words in scam, words
    assert hasattr(Ledger, "scam_checked")


def test_the_readme_s_trust_boundaries_name_the_phone_s_listener() -> None:
    """The browser talks to Ordnung on ``127.0.0.1``; phone access, once it is turned on, adds a second listener
    on one home-network address that answers only paired phones (docs/architecture.md's *Phone → Ordnung* row,
    ADR 0017). The README's short table says both, and what calendar sync and the sync folder get."""
    table = _readme().split("\n### Trust boundaries\n", 1)[1].split("\n### ", 1)[0]
    rows = [_flat(line) for line in table.splitlines() if line.startswith("| ")]
    (computer,) = [row for row in rows if "`127.0.0.1` only" in row]
    assert computer.startswith("| Browser → Ordnung on your computer |")
    (phone,) = [row for row in rows if row.startswith("| Phone → Ordnung (opt-in) |")]
    for words in (
        "a second listener",
        "HTTPS on one home-network address",
        "answering only phones you paired with a one-time code",
        "never their requests for settings, backups or deletion",
        "(docs/decisions/0017-phone-access-over-the-home-network.md)",
    ):
        assert words in phone, words
    (world,) = [row for row in rows if row.startswith("| Ordnung → the world |")]
    for words in ("Calendar sync", "*With details*", "hand-off sync writes only encrypted files"):
        assert words in world, words
    architecture = _flat((ROOT / "docs" / "architecture.md").read_text(encoding="utf-8"))
    phone_row = "| Phone → Ordnung (home network, opt-in) | A second uvicorn server in the same process"
    assert phone_row in architecture
    assert "bound to one home-network IPv4 address of the computer, never `0.0.0.0`" in architecture
    assert "discreet by default (dates, times and alarms — no titles, names or amounts)" in architecture
    assert "| Ordnung → sync folder (opt-in) | Only ciphertext is written" in architecture


def test_the_readme_says_pre_registered_as_the_card_does() -> None:
    """The evaluation card's *Pre-registration* row decides what README says: while the card says these
    statistics are **not pre-registered**, so does README, and the promise for the final run is in both. When the
    final run is recorded the card changes, and this test asks README to follow."""
    readme = _flat(_readme())
    row = _card_row("Pre-registration")
    assert ("not pre-registered" in readme) == ("**not pre-registered**" in row)
    promise = "pre-registered before it is recorded"
    assert (promise in readme) == (promise in row)


def test_the_readme_s_privacy_says_spec_s_statement_and_what_stays_off() -> None:
    """SPEC §1's honest privacy statement ("use this wording everywhere"), then the features that send anything
    beyond Claude, each off until it is turned on, as docs/privacy.md's table says."""
    privacy = _plain(_section("Privacy"))
    spec = _flat((ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8"))
    statement = spec.split(SPEC_PRIVACY, 1)[1].split("*", 1)[0]
    assert privacy.startswith(statement)
    stay_off = "Phone access, calendar sync and sync between your computers stay off until you turn them on."
    assert stay_off in privacy
    table = (ROOT / "docs" / "privacy.md").read_text(encoding="utf-8")
    for row in (
        "| Calendar sync (only if you connect a calendar) |",
        "| Phone access (only if you turn it on) |",
        "| Hand-off sync between your computers (only if you set it up) |",
    ):
        assert row in table, row
    assert "(docs/privacy.md#if-your-computer-is-lost-or-stolen)" in _section("Privacy")


def test_the_readme_carries_no_source_comments() -> None:
    """README was written with a source comment after each claim; they are for the reviewer, not the reader, and
    the PyPI page would carry them."""
    assert "<!-- src:" not in _readme()
