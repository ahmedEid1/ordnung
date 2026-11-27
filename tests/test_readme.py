"""README.md, which is also the PyPI page: short, its sections in their order, no Mermaid but its drawn diagram,
code lines that fit GitHub's column, nothing folded that a reader must see, a CI badge that shows ``main``, the
Python versions CI tests and pyproject.toml allows, an install that says what it needs and names no tag, a scam
caption that says what SPEC §21 says, a trust table that names the phone's listener, a pre-registration bullet that
says what the evaluation card says, a lead into the evaluation block that names the pre-registration's paired tests,
the privacy statement SPEC §1 asks for.

Most of the rest of what README states is pinned where the fact lives (``tests/test_docs_claims.py``,
``test_present.py``, ``test_release_workflow.py`` and the others that read it).
"""

from __future__ import annotations

import json
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


def _unbold(text: str) -> str:
    """``text`` with its Markdown bold (``**words**``) as the words alone; nothing else changes."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)


def _card_row(name: str) -> str:
    """The evaluation card's row ``| name | … |`` in docs/evals.md, flat."""
    card = (ROOT / "docs" / "evals.md").read_text(encoding="utf-8")
    (row,) = [line for line in card.splitlines() if line.startswith(f"| {name} |")]
    return _flat(row)


def _section(heading: str) -> str:
    """README's ``## heading``, up to the next ``## `` heading."""
    return _readme().split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


#: Lines the README keeps spare outside its block until the final run is published: room for the publish PR's
#: rewrite of the two bullets that describe today's analysis, "Held out." and "Pre-registered next." (the evaluation
#: card's *Pre-registration* row changes then, and the test below on it asks README to follow; runbook §5.2).
PUBLISH_ROOM = 2


def test_the_readme_has_room_for_the_largest_final_block() -> None:
    """README.md is under its limit, today and once the final run is published: then its block
    (``evals.present.final.readme_block``) takes the place of today's and may take up to ``README_BLOCK_MAX_LINES``
    lines, a budget registered before any result, and the README's own text outside the block leaves room for it,
    whatever the final run shows. Until then it also keeps ``PUBLISH_ROOM`` lines spare, so that the publish PR can
    rewrite its two bullets on today's analysis without cutting anything else. A line added to the README later has
    to make room too."""
    from evals.present import BEGIN, END, final

    lines = _readme().splitlines()
    assert len(lines) < MAX_LINES, f"README.md has {len(lines)} lines; move the detail to docs/guide.md"
    begin, end = lines.index(BEGIN), lines.index(END)
    outside = len(lines) - (end - begin - 1)
    spare = PUBLISH_ROOM if final.published(ROOT) is None else 0
    assert outside + final.README_BLOCK_MAX_LINES + spare < MAX_LINES, (
        f"README.md has {outside} lines outside its block; with the final block's {final.README_BLOCK_MAX_LINES} "
        f"and {spare} spare for the publish PR it would reach {outside + final.README_BLOCK_MAX_LINES + spare}"
    )


#: README's drawn diagram of how a letter is handled: two SVG files kept by hand, the same but for their colours
PIPELINE = {theme: ROOT / "docs" / "assets" / f"pipeline-{theme}.svg" for theme in ("light", "dark")}
#: an SVG's text, title and description: what a reader sees, or hears from a screen reader
_SVG_WORDS = re.compile(r"<(text|title|desc)\b[^>]*>([^<]*)</\1>")


def _without_colours(svg: str) -> str:
    """An SVG of README's diagram with its colours and its ids' theme taken out."""
    return re.sub(r"#[0-9a-f]{6}\b", "#", re.sub(r"pipeline-(?:light|dark)-", "pipeline-", svg))


def test_the_readme_draws_no_mermaid_but_its_drawn_diagram() -> None:
    """PyPI shows README.md as its project page and draws no Mermaid; the architecture's diagram is in
    docs/architecture.md. README shows its own, drawn: one ``<picture>`` with the dark file for a dark theme and
    the light one for everyone else (PyPI shows only the light ``<img>``), an alt text that says what the diagram
    says (its description, word for word), and the same words in both files, which differ only in colours and ids."""
    readme = _readme()
    assert "```mermaid" not in readme
    pictures = [
        p for p in re.findall(r"<picture>.*?</picture>", readme, re.S) if "docs/assets/pipeline-" in p
    ]
    (picture,) = pictures
    assert picture.startswith(
        '<picture><source media="(prefers-color-scheme: dark)" srcset="docs/assets/pipeline-dark.svg">'
        '<img src="docs/assets/pipeline-light.svg" '
    ), picture
    svgs = {theme: path.read_text(encoding="utf-8") for theme, path in PIPELINE.items()}
    words = {theme: [_flat(match[1]) for match in _SVG_WORDS.findall(svg)] for theme, svg in svgs.items()}
    assert words["light"] == words["dark"] and len(words["light"]) >= 10, words
    (desc,) = [_flat(match[1]) for match in _SVG_WORDS.findall(svgs["light"]) if match[0] == "desc"]
    alt = re.search(r'\balt="([^"]*)"', picture)
    assert alt and _flat(alt.group(1)) == desc
    assert _without_colours(svgs["light"]) == _without_colours(svgs["dark"])
    for svg in svgs.values():  # shown as an image: nothing to run, nothing to fetch
        assert not re.search(r"<(?:script|image|foreignObject|style)\b|@import|href=", svg)


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
    pyproject.toml's ``requires-python`` allows, which is the oldest CI tests. The job's Pythons are two lists, a
    pull request's and every other event's: a pull request tests the oldest in the lowest versions' job alone
    (tests/test_ci_workflow.py says why), so the bullet's "on every pull request" names that job's Python too."""
    readme = _readme()
    jobs = _workflow()["jobs"]
    on_pull_request, versions = (
        json.loads(listed)
        for listed in re.findall(r"'(\[[^']*\])'", jobs["backend"]["strategy"]["matrix"]["python"])
    )
    (lowest,) = [
        s["with"]["python-version"] for s in jobs["lowest"]["steps"] if "setup-uv" in s.get("uses", "")
    ]
    assert sorted({lowest, *on_pull_request}) == versions, "a pull request tests every Python main does"
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


def test_the_readme_names_the_paired_tests_the_pre_registration_uses() -> None:
    """The paragraph that leads into the evaluation block names both paired tests the pre-registration uses: the
    sign-flip test over letter clusters for the three comparisons, and McNemar for the dates' stability and the
    stress endpoints. Each p value the block prints comes from one of them (today's exact p is McNemar's)."""
    from evals.present import BEGIN

    prereg = ROOT / "evals" / "preregistration" / "final-0.4.0.json"
    rules = json.loads(prereg.read_text(encoding="utf-8"))["analysis"]["rules"]
    lead = _flat(_readme().split(BEGIN, 1)[0].rstrip().rsplit("\n\n", 1)[1])
    assert "signflip" in rules["f1_f2_test"]
    assert "sign-flip test over letter clusters" in lead
    assert "mcnemar" in rules["f3_test"]
    assert "McNemar" in lead
    # the decision rule the final run used: Holm within each family (never across the three comparisons, the
    # earlier re-analysis's), a bootstrap interval, the agent by a non-inferiority bound, steadiness by mid-p
    assert rules["multiplicity"] == "holm_within_each_family" and "Holm within each family" in lead
    assert "Holm across" not in lead
    assert rules["interval"].startswith("paired_cluster_bootstrap") and "bootstrap interval" in lead
    assert rules["noninferiority"] == "signflip_test_inversion" and "non-inferiority" in lead
    assert "midp" in rules["f3_test"] and "mid-p" in lead


def test_the_readme_s_privacy_says_spec_s_statement_and_what_stays_off() -> None:
    """SPEC §1's honest privacy statement ("use this wording everywhere"), then the features that send anything
    beyond Claude, each off until it is turned on, as docs/privacy.md's table says."""
    privacy = _unbold(_plain(_section("Privacy")))
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


#: README's headings in their order: what Ordnung is and how to try it first (the example, install, what it does,
#: privacy and limits), then how it works and how it is measured for a reader who wants to check the work.
#: docs/SPEC.md §19 gives the same order; release notes link *Install and run* and *Updating*.
SECTIONS = [
    "## The model reads, code computes",
    "## Install and run",
    "### Updating",
    "## What it does",
    "## Privacy",
    "## Limitations",
    "## How it works",
    "### Trust boundaries",
    "### Tested",
    "## Evaluation",
    "### Why these numbers can be checked",
    "## How it was built",
    "## Documentation",
    "## Disclaimer",
]


def _outside_code(text: str) -> str:
    """``text`` without its fenced code blocks."""
    return re.sub(r"^```.*?^```", "", text, flags=re.M | re.S)


def test_the_readme_s_sections_keep_their_order() -> None:
    """The order is the page's design: a visitor reads what Ordnung is, how to try it and whether to trust it with
    their letters before the engineering and the evaluation."""
    headings = [line for line in _outside_code(_readme()).splitlines() if re.match(r"#{1,6} ", line)]
    assert headings == SECTIONS
    spec = _flat((ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8"))
    contract = spec.split("## 19. Docs contract", 1)[1].split("**The guide**", 1)[0]
    names = [heading.lstrip("# ").lower() for heading in SECTIONS if heading.startswith("## ")]
    found = [contract.lower().find(f"*{name}*") for name in names]
    assert -1 not in found and found == sorted(found), list(zip(names, found))


#: The widest line a README code block may have, in characters. GitHub shows a README in a column 830 px wide on a
#: desktop (a 1280 px window); a code block has 16 px of padding each side and a monospace font at 13.6 px whose
#: characters are at most 8.2 px wide (SF Mono, Menlo and Liberation Mono at 0.6 em; Consolas is narrower): 97 fit.
#: A line beyond that is cut off and scrolls sideways.
CODE_LINE_MAX = 90


def test_no_readme_code_line_is_wider_than_github_s_column() -> None:
    """Every line of a fenced code block fits GitHub's desktop column, with room to spare for the widest font."""
    blocks = re.findall(r"^```[a-z]*\n(.*?)^```", _readme(), re.M | re.S)
    assert blocks
    wide = [line for block in blocks for line in block.splitlines() if len(line) > CODE_LINE_MAX]
    assert not wide, wide


def _unfolded(text: str) -> str:
    """``text`` without what its ``<details>`` fold away: what a reader sees before opening anything, and all a
    PyPI reader gets (PyPI shows every fold closed)."""
    return re.sub(r"<details>.*?</details>", "", text, flags=re.S)


def test_the_readme_shows_the_phones_the_recording_clock_and_the_credits_unfolded() -> None:
    """Some things a fold must never hide: the two phone pictures (light and dark), the final run's recording
    clock, an honesty note on its dates, under its "(written after the results)" heading, and the licence
    credits GeoNames' CC BY licence asks for."""
    visible = _flat(_unfolded(_readme()))
    for words in (
        'src="docs/assets/mobile.png"',
        'src="docs/assets/mobile-dark.png"',
        "**Pre-registered (written after the results).**",
        "Recorded on real 17 Nov 2026 with the clock 7 days ahead (K29): recording and analysis dates are the day "
        "the model was told; deviation times, commits and PRs are real.",
        "Postcode data © [GeoNames](https://www.geonames.org/)",
        "under their own licences (MIT, ISC and the SIL Open Font License 1.1)",
        "MIT licensed",
        "<b>Light and dark.</b>",
    ):
        assert words in visible, words
    side_by_side = r'<img src="docs/assets/mobile\.png"[^>]*> &nbsp; <img src="docs/assets/mobile-dark\.png"'
    assert re.search(side_by_side, _readme()), "the phone pictures stand side by side"
