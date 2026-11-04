"""``docs/guide.md``, the guide to using Ordnung: the sections README links to by anchor, every environment
variable the package reads or sets, and how to note a call."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ordnung import config
from test_docs_index import _anchors

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "guide.md"
PACKAGE = ROOT / "src" / "ordnung"
#: Claude Code's own variables, which Ordnung acts on: it warns while the first is set and records the second
#: into start at login and the app-menu shortcut.
CLAUDE_CODE_VARIABLES = frozenset({"ANTHROPIC_API_KEY", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"})
_VARIABLE = re.compile(r"\b(?:ORDNUNG_[A-Z0-9_]*[A-Z0-9]|" + "|".join(sorted(CLAUDE_CODE_VARIABLES)) + r")\b")
#: docs/privacy.md, "Your controls": no AI reads a call note.
PRIVACY_CALL_NOTES = (
    "**Call notes** — what you note about a phone call is kept as you typed it; no AI reads it."
)


def _guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """``text`` with every run of whitespace as one space."""
    return " ".join(text.split())


def _section(heading: str) -> str:
    """The guide's ``## heading``, up to the next ``## `` heading."""
    return _guide().split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


def _variables_in_the_package() -> set[str]:
    """Every string in ``src/ordnung`` that is a whole variable name (``"ORDNUNG_HOME"``): the ones it reads, and
    the ones it sets for a program it starts."""
    found: set[str] = set()
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            value = node.value if isinstance(node, ast.Constant) else None
            if isinstance(value, str) and _VARIABLE.fullmatch(value):
                found.add(value)
    return found


def _rows() -> dict[str, list[str]]:
    """The environment-variable tables' rows, by the variable in their first cell: the cells after it."""
    rows = {}
    for line in _section("Environment variables").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split(" | ")]
        name = re.fullmatch(r"`([A-Z0-9_]+)`", cells[0]) if line.startswith("| `") else None
        if name:
            rows[name[1]] = cells[1:]
    return rows


def test_the_guide_has_the_sections_the_readme_links() -> None:
    """README sends readers to the guide's tour, install, updating, environment variables and limitations by
    their anchors (``docs/guide.md#install-and-run``), so a renamed heading breaks those links."""
    linked = {"a-tour", "install-and-run", "updating", "environment-variables", "limitations"}
    assert linked <= _anchors(GUIDE), linked - _anchors(GUIDE)
    headings = re.findall(r"^(#{1,3}) (.+)$", _guide(), re.M)
    assert headings[0] == ("#", "Using Ordnung")
    assert [heading for level, heading in headings if level == "##"] == [
        "A tour",
        "Install and run",
        "Environment variables",
        "Limitations",
    ]
    install = _section("Install and run")
    assert "\n### Updating\n" in install  # under Install and run, as the README had it


def test_the_guide_s_install_has_a_heading_for_each_way_to_run_ordnung() -> None:
    """Install and run's parts are ``###`` headings, not bold words at the start of a paragraph, so GitHub's
    outline lists them and each has an anchor; Updating stays last, under Install and run."""
    install = _section("Install and run")
    assert re.findall(r"^### (.+)$", install, re.M) == [
        "Words in photos (optional)",
        "Without a terminal",
        "On your phone",
        "On your other computer",
        "Claude Desktop or Claude Code",
        "From a source checkout",
        "Updating",
    ]
    assert not re.findall(r"^\*\*.+?\*\*", install, re.M)  # no paragraph left that a bold label starts
    anchors = {
        "words-in-photos-optional",
        "without-a-terminal",
        "on-your-phone",
        "on-your-other-computer",
        "claude-desktop-or-claude-code",
        "from-a-source-checkout",
        "updating",
    }
    assert anchors <= _anchors(GUIDE), anchors - _anchors(GUIDE)


def test_every_environment_variable_ordnung_reads_is_in_the_guide() -> None:
    """Every variable name the package holds as a string is in the guide's *Environment variables*, in a table or
    the sentence on the rest, with Claude Code's two; every name the section gives is one the package holds, and a
    row's *Read in* names modules that hold it."""
    section = _section("Environment variables")
    in_the_package = _variables_in_the_package()
    assert CLAUDE_CODE_VARIABLES <= in_the_package
    assert len(in_the_package) > 20, in_the_package
    named = set(_VARIABLE.findall(section))
    assert not in_the_package - named, f"not in the guide: {sorted(in_the_package - named)}"
    assert not named - in_the_package, f"the package holds no such name: {sorted(named - in_the_package)}"
    rows = _rows()
    assert {"ORDNUNG_HOME", "ORDNUNG_CLAUDE_BIN", "ORDNUNG_OCR", *CLAUDE_CODE_VARIABLES} <= set(rows)
    for name, cells in rows.items():
        modules = re.findall(r"`([a-z_/]+\.py)`", cells[-1])
        assert modules, name
        for module in modules:
            assert name in (PACKAGE / module).read_text(encoding="utf-8"), (name, module)


def test_the_guide_s_ocr_values_are_the_code_s() -> None:
    """The values the guide gives for ``ORDNUNG_OCR`` are the ones that turn text in pictures off, in any case,
    and another value leaves it as Settings says."""
    what = _rows()["ORDNUNG_OCR"][0]
    listed = re.match(r"((?:`[^`]+`, )*`[^`]+` or `[^`]+`) \(any case\) turns text in pictures off", what)
    assert listed, what
    values = re.findall(r"`([^`]+)`", listed[1])
    assert set(values) == config._OFF_VALUES and len(values) == len(config._OFF_VALUES)
    for value in values:
        assert config.ocr_turned_off({config.OCR_SWITCH: value.upper()})
    assert not config.ocr_turned_off({config.OCR_SWITCH: "on"})
    assert config.picture_text_off(False, {config.OCR_SWITCH: "on"})  # Settings' off stays off


def test_the_guide_says_how_to_note_a_call() -> None:
    """The tour's *Also* names call notes as the app does (*Note a call* in a drawer and on an overdue entry under
    *Waiting for*, the form's fields, *They kept it*), and says no AI reads them, as the privacy page does."""
    also = _flat(_section("A tour").split("**Also:**", 1)[1])
    item = also.split("*call notes* — ", 1)[1].split(" · ", 1)[0]
    assert item.startswith(
        "*Note a call* in a person's or an organisation's drawer, or on an overdue reply or promise under "
        "*Waiting for*,"
    )
    form = (ROOT / "web/src/features/party/CallNotes.tsx").read_text(encoding="utf-8")
    waiting = (ROOT / "web/src/features/waiting/WaitingList.tsx").read_text(encoding="utf-8")
    assert 'aria-label="Note a call"' in form and "Note a call" in waiting
    # the Waiting-for entries that offer Note a call
    model = (ROOT / "web/src/features/waiting/model.ts").read_text(encoding="utf-8")
    asks = model.split("function asksForACall", 1)[1].split("\n}\n", 1)[0]
    assert 'entry.status === "overdue" && (entry.source === "letter" || entry.source === "call")' in asks
    assert "when you called, with whom, what was said and what was promised, with a day and an amount" in item
    for label in ("When", "Who you spoke to", "What was said", "What they promised", "By", "Amount"):
        assert f'label="{label}"' in form, label
    assert "*They kept it*" in item and "They kept it" in form and "They kept it" in waiting
    assert item.endswith("no AI reads it")
    assert PRIVACY_CALL_NOTES in _flat((ROOT / "docs" / "privacy.md").read_text(encoding="utf-8"))
