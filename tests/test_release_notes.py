"""scripts/release_notes.py: a release's notes are CHANGELOG.md's section for the version its tag names, with
links to the tagged files on GitHub; a tag that names another version, or a version without its section,
stops the release before anything is built or published (.github/workflows/release.yml)."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import ordnung

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.release_notes import (  # noqa: E402
    REPOSITORY,
    ReleaseError,
    absolute_links,
    is_prerelease,
    main,
    notes,
    package_version,
    section,
    unwrapped,
)

VERSION = ordnung.__version__
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

TWO_VERSIONS = """# Changelog

## Unreleased

- Something not released yet.

## 0.3.0 — 2026-11-02

The third one.

### Added

- **A thing.** See [Updating](README.md#updating).

## 0.2.0 — 2026-10-08

The second one.
"""

#: the changelog of the release commit: the version's section is the newest (an empty Unreleased above it is
#: fine)
RELEASED = TWO_VERSIONS.replace("## Unreleased\n\n- Something not released yet.\n\n", "## Unreleased\n\n")


def _root(tmp_path: Path, version: str, changelog: str) -> Path:
    """A checkout with only what the script reads: CHANGELOG.md and src/ordnung/__init__.py."""
    (tmp_path / "src" / "ordnung").mkdir(parents=True)
    (tmp_path / "src" / "ordnung" / "__init__.py").write_text(
        f'"""Ordnung."""\n\n__version__ = "{version}"\n', encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return tmp_path


def _relative_links(text: str) -> list[str]:
    return re.findall(r"\]\((?![a-z][a-z0-9+.-]*:)([^)\s]+)\)", text)


def test_the_notes_are_the_changelog_s_section_for_the_version() -> None:
    released = section(CHANGELOG, VERSION)
    assert released.startswith("The first numbered release.")
    assert "### Since the first commit" in released and "### Upgrading" in released
    assert not re.search(r"^## ", released, re.M)  # neither its own heading nor the next one
    assert "Dates you add yourself can repeat" not in released  # Unreleased stays out
    assert section(TWO_VERSIONS, "0.3.0") == (
        "The third one.\n\n### Added\n\n- **A thing.** See [Updating](README.md#updating)."
    )
    assert section(TWO_VERSIONS, "0.2.0") == "The second one."


def test_the_version_is_read_from_init_py_without_importing_the_package() -> None:
    assert package_version((ROOT / "src/ordnung/__init__.py").read_text(encoding="utf-8")) == VERSION
    with pytest.raises(ReleaseError, match="__version__"):
        package_version('"""No version here."""\n')


def test_a_tag_that_doesn_t_name_the_version_stops_the_release(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path, "0.3.0", TWO_VERSIONS)
    out = tmp_path / "release-notes.md"
    for tag in ("v0.3.1", "0.3.0", "v0.3", "release-0.3.0"):
        assert main(["--root", str(root), "--tag", tag, "--out", str(out)]) == 1, tag
        error = capsys.readouterr().err
        assert f"The tag {tag} doesn't name this version" in error, tag
        assert "src/ordnung/__init__.py says 0.3.0, so its tag is v0.3.0" in error, tag
    assert not out.exists()


@pytest.mark.parametrize(
    ("changelog", "says"),
    [
        (
            "# Changelog\n\n## Unreleased\n\n- Not released yet.\n",
            'CHANGELOG.md has no section for 0.3.0: rename "## Unreleased" to "## 0.3.0 — YYYY-MM-DD"',
        ),
        ("## 0.3.0 - 2026-11-02\n\nA hyphen, not a dash.\n", "CHANGELOG.md has no section for 0.3.0"),
        ("## 0.3.0 — 2026-11-02\n\n## 0.2.0 — 2026-10-08\n\nOlder.\n", "section for 0.3.0 is empty"),
        ("## 0.3.0 — 2026-13-02\n\nA month that doesn't exist.\n", "2026-13-02 isn't a date"),
        ("## 0.3.0 — 2026-11-02\n\nOne.\n\n## 0.3.0 — 2026-11-03\n\nTwo.\n", "two sections for 0.3.0"),
    ],
    ids=["only-unreleased", "hyphen", "empty", "no-such-date", "twice"],
)
def test_a_version_without_its_changelog_section_stops_the_release(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], changelog: str, says: str
) -> None:
    with pytest.raises(ReleaseError, match=re.escape(says)):
        section(changelog, "0.3.0")
    root = _root(tmp_path, "0.3.0", changelog)
    out = tmp_path / "release-notes.md"
    assert main(["--root", str(root), "--tag", "v0.3.0", "--out", str(out)]) == 1
    assert says in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.parametrize(
    ("above", "named"),
    [
        ("## Unreleased\n\n### Fixed\n\n- A small fix after the release.\n\n", "Unreleased"),
        ("## 0.4.0 — 2026-12-01\n\nLater.\n\n", "0.4.0 — 2026-12-01"),
    ],
    ids=["unreleased-changes", "a-newer-version"],
)
def test_a_tag_on_a_commit_with_changes_its_notes_leave_out_stops_the_release(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], above: str, named: str
) -> None:
    """The tagged commit is what gets released: when the changelog lists anything above the version's section,
    that commit holds changes the notes leave out (a tag on main after a later merge, or on a version whose
    release commit is long past). PyPI could never take that version back."""
    changelog = "# Changelog\n\n" + above + RELEASED.split("## Unreleased\n\n", 1)[1]
    root = _root(tmp_path, "0.3.0", changelog)
    out = tmp_path / "release-notes.md"
    assert main(["--root", str(root), "--tag", "v0.3.0", "--out", str(out)]) == 1
    error = " ".join(capsys.readouterr().err.split())
    assert f'CHANGELOG.md lists changes above the section for 0.3.0, under "## {named}"' in error
    assert "Tag the commit that named the section for 0.3.0: git tag -a v0.3.0 <that commit>" in error
    assert not out.exists()
    # without a tag it is only a preview: the notes print
    assert main(["--root", str(root), "0.3.0"]) == 0


def test_an_empty_unreleased_section_above_the_version_is_fine(tmp_path: Path) -> None:
    root = _root(tmp_path, "0.3.0", RELEASED)
    out = tmp_path / "release-notes.md"
    assert main(["--root", str(root), "--tag", "v0.3.0", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == notes(RELEASED, "0.3.0")


def test_links_point_to_the_tagged_files_on_github() -> None:
    blob, raw = f"{REPOSITORY}/blob/v0.3.0", f"{REPOSITORY}/raw/v0.3.0"
    text = (
        "[Updating](README.md#updating), [ADR 19](docs/decisions/0019-x.md), [the decisions](docs/decisions/), "
        "[below](#upgrading), ![a picture](docs/assets/today.png), [PyPI](https://pypi.org/project/ordnung/), "
        "[mail](mailto:someone@example.org)"
    )
    assert absolute_links(text, "v0.3.0") == (
        f"[Updating]({blob}/README.md#updating), [ADR 19]({blob}/docs/decisions/0019-x.md), "
        f"[the decisions]({blob}/docs/decisions/), [below]({blob}/CHANGELOG.md#upgrading), "
        f"![a picture]({raw}/docs/assets/today.png), [PyPI](https://pypi.org/project/ordnung/), "
        "[mail](mailto:someone@example.org)"
    )


def test_the_lines_of_a_paragraph_or_list_item_are_joined_for_the_release_page() -> None:
    """CHANGELOG.md is wrapped at 110 characters; a release page shows each line end as a line break."""
    wrapped = (
        "The first\nnumbered release.\n\n### Added\n\n- **A thing.** It\n  does this,\n  and that.\n"
        "  - a nested\n    item\n- Another, with a break  \n  kept.\n\n```\ncode stays\nas it is\n```\nAfter."
    )
    assert unwrapped(wrapped) == (
        "The first numbered release.\n\n### Added\n\n- **A thing.** It does this, and that.\n"
        "  - a nested item\n- Another, with a break  \n  kept.\n\n```\ncode stays\nas it is\n```\nAfter."
    )
    released = notes(CHANGELOG, VERSION)
    assert (
        "Every install before it reports 0.1.0, the version of the first commit (2026-09-25), and pip"
        in released
    )
    assert not re.search(r"^ +\S", released, re.M)  # no list item of 0.2.0's goes on over two lines


def test_every_link_in_the_released_notes_names_a_file_of_the_tagged_commit() -> None:
    written = notes(CHANGELOG, VERSION)
    assert not _relative_links(written)
    tagged = f"{REPOSITORY}/blob/v{VERSION}/"
    linked = re.findall(rf"\]\({re.escape(tagged)}([^)#\s]+)", written)
    assert "README.md" in linked and "CHANGELOG.md" in linked
    for path in linked:
        assert (ROOT / path).exists(), path


def test_the_footer_says_how_to_install_or_update() -> None:
    footer = notes(TWO_VERSIONS, "0.3.0").rsplit("\n\n---\n\n", 1)[1]
    blob = f"{REPOSITORY}/blob/v0.3.0"
    assert footer == (
        f"Install or update: [Install and run]({blob}/README.md#install-and-run) · "
        f"[Updating]({blob}/README.md#updating) · [Changelog]({blob}/CHANGELOG.md)\n"
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert re.search(r"^## Install and run$", readme, re.M) and re.search(r"^### Updating$", readme, re.M)


@pytest.mark.parametrize(
    ("version", "prerelease"),
    [
        ("0.3.0", False),
        ("1.0", False),
        ("0.3.0.post1", False),
        ("0.3.0rc1", True),
        ("0.3.0a1", True),
        ("0.3.0b2", True),
        ("0.3.0.dev1", True),
    ],
)
def test_a_pre_release_is_marked_as_one(version: str, prerelease: bool) -> None:
    assert is_prerelease(version) is prerelease


@pytest.mark.parametrize("version", ["0.3.0-rc1", "v0.3.0", "0.3.0RC1", "0.3.0 ", "0.3.0+local"])
def test_a_version_pypi_would_spell_differently_is_refused(version: str) -> None:
    """The tag must equal ``v`` + ``__version__`` and PyPI shows the version in its normal form, so both are
    the normal form: ``0.3.0rc1``, never ``0.3.0-rc1``."""
    with pytest.raises(ReleaseError, match="normal form"):
        package_version(f'__version__ = "{version}"\n')


def test_the_workflow_run_writes_the_notes_and_its_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path / "checkout", "0.3.0rc1", RELEASED.replace("0.3.0 —", "0.3.0rc1 —"))
    outputs = tmp_path / "github-output"
    outputs.write_text("earlier=kept\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    out = tmp_path / "release-notes.md"
    assert main(["--root", str(root), "--tag", "v0.3.0rc1", "--out", str(out)]) == 0
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert out.read_text(encoding="utf-8") == notes(changelog, "0.3.0rc1")
    assert outputs.read_text(encoding="utf-8") == "earlier=kept\nversion=0.3.0rc1\nprerelease=true\n"


def test_without_a_tag_it_prints_the_notes_of_this_version_or_of_unreleased(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert main([]) == 0
    assert capsys.readouterr().out == notes(CHANGELOG, VERSION)
    assert main(["Unreleased"]) == 0  # a preview before the release commit: links to main, no tag yet
    preview = capsys.readouterr().out
    assert preview.startswith("### Added\n")
    assert f"{REPOSITORY}/blob/main/README.md#updating" in preview and "/blob/v" not in preview


def test_the_script_runs_with_the_standard_library_alone(tmp_path: Path) -> None:
    """release.yml runs it with the runner's own Python, before anything is installed."""
    script = ROOT / "scripts" / "release_notes.py"
    imported = {
        (node.module if isinstance(node, ast.ImportFrom) else alias.name).split(".")[0]
        for node in ast.walk(ast.parse(script.read_text(encoding="utf-8")))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported
    root = _root(tmp_path / "checkout", "0.3.0", RELEASED)
    out = tmp_path / "release-notes.md"
    done = subprocess.run(
        [sys.executable, "-I", str(script), "--root", str(root), "--tag", "v0.3.0", "--out", str(out)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={name: value for name, value in os.environ.items() if name != "GITHUB_OUTPUT"},
    )
    assert done.returncode == 0, done.stderr
    assert out.read_text(encoding="utf-8") == notes(RELEASED, "0.3.0")
