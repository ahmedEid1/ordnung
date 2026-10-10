"""The notes of a GitHub Release: CHANGELOG.md's section for the version a tag names (.github/workflows/release.yml).

A release starts when the owner pushes a tag such as ``v0.3.0`` (docs/releasing.md). Before anything is built
or published, this script checks that

1. the tag is ``v`` + the package's version, ``__version__`` in ``src/ordnung/__init__.py``, written in
   PEP 440's normal form (the way PyPI shows it: ``0.3.0rc1``, never ``0.3.0-rc1``);
2. CHANGELOG.md has exactly one section for that version, headed ``## 0.3.0 — YYYY-MM-DD`` with a real date,
   and it isn't empty;
3. that section is the newest: above it there is at most an empty ``## Unreleased``. Anything else there means
   the tagged commit holds changes the notes leave out (a tag on main after a later merge, say), and PyPI can
   never take a version back.

Otherwise it says what is wrong and exits with 1, and the release stops. The notes are that section, with the
links that are relative to the repository pointed at the tagged files on GitHub (that is what they mean on a
release page), and a line on how to install or update. It needs the standard library only, so the workflow
runs it with the runner's own Python.

Run it from anywhere in the checkout::

    python3 scripts/release_notes.py                     # print the notes of this version
    python3 scripts/release_notes.py Unreleased          # a preview of the next ones (links to main)
    python3 scripts/release_notes.py --tag v0.3.0 --out release-notes.md   # what release.yml runs

With ``--tag``, it also adds ``version`` and ``prerelease`` to the step's outputs (``$GITHUB_OUTPUT``).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

REPOSITORY = "https://github.com/ahmedEid1/ordnung"
ROOT = Path(__file__).resolve().parents[1]
INIT = "src/ordnung/__init__.py"
UNRELEASED = "Unreleased"

#: PEP 440's normal form, without epochs and local versions (PyPI takes neither from us).
NORMAL_FORM = re.compile(r"\d+(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?")
PRERELEASE = re.compile(r"\d(a|b|rc)\d+|\.dev\d+")
#: A line that starts a block of its own (a list item, a heading, a quote, a table row) and is never joined to
#: the line before it; nothing is joined to a heading, a table row or a code fence either.
BLOCK = re.compile(r"\s*([-*+]\s|\d+[.)]\s|#|>|\|)")
STANDS_ALONE = ("#", "|", "```", "~~~")
#: An inline Markdown link or image whose target has no scheme (``https:``, ``mailto:``): relative to the
#: repository, or an anchor in CHANGELOG.md itself.
RELATIVE_LINK = re.compile(r"(!?)\[([^\]]*)\]\((?![a-zA-Z][a-zA-Z0-9+.-]*:)([^)\s]+)\)")


class ReleaseError(Exception):
    """The tag, the version or the changelog section isn't right; the message says what to fix."""


def package_version(init_text: str) -> str:
    """``__version__`` from the text of ``src/ordnung/__init__.py``, read without importing the package."""
    found = re.search(r'^__version__ = "([^"]*)"$', init_text, re.M)
    if found is None:
        raise ReleaseError(f'{INIT} has no line __version__ = "…".')
    version = found.group(1)
    if not NORMAL_FORM.fullmatch(version):
        raise ReleaseError(
            f"{INIT} says __version__ = \"{version}\", which isn't in PEP 440's normal form, the way PyPI "
            "shows it (like 0.3.0, 0.3.0rc1 or 0.3.0.post1)."
        )
    return version


def is_prerelease(version: str) -> bool:
    """An alpha, beta, release candidate or development version (``pipx install ordnung`` skips those)."""
    return PRERELEASE.search(version) is not None


def section(changelog: str, version: str) -> str:
    """The text under CHANGELOG.md's heading for ``version`` (``## 0.3.0 — 2026-11-02``, or ``## Unreleased``),
    up to the next ``## `` heading."""
    if version == UNRELEASED:
        headings = list(re.finditer(rf"^## {UNRELEASED}$", changelog, re.M))
    else:
        headings = list(
            re.finditer(rf"^## {re.escape(version)} — (\d{{4}}-\d{{2}}-\d{{2}})$", changelog, re.M)
        )
    if not headings and version == UNRELEASED:
        raise ReleaseError(f'CHANGELOG.md has no "## {UNRELEASED}" section.')
    if not headings:
        expected = f"## {version} — YYYY-MM-DD"
        if re.search(rf"^## {UNRELEASED}$", changelog, re.M):
            fix = f'rename "## {UNRELEASED}" to "{expected}" (the day of the release) and commit that first'
        else:
            fix = f'its heading must be "{expected}"'
        raise ReleaseError(f"CHANGELOG.md has no section for {version}: {fix}.")
    if len(headings) > 1:
        raise ReleaseError(f"CHANGELOG.md has two sections for {version}.")
    (heading,) = headings
    if version != UNRELEASED:
        try:
            date.fromisoformat(heading.group(1))
        except ValueError:
            raise ReleaseError(
                f"CHANGELOG.md's heading for {version}: {heading.group(1)} isn't a date."
            ) from None
    text = re.split(r"^## ", changelog[heading.end() :], maxsplit=1, flags=re.M)[0].strip()
    if not text:
        raise ReleaseError(f"CHANGELOG.md's section for {version} is empty.")
    return text


def check_newest(changelog: str, version: str) -> None:
    """Refuse a release whose changelog lists anything above ``version``'s section: an empty ``## Unreleased``
    is all that may stand there. Call it after :func:`section` has found that section."""
    heading = re.search(rf"^## {re.escape(version)} — ", changelog, re.M)
    if heading is None:  # no section at all: section() says so
        return
    above = re.split(r"^## ", changelog[: heading.start()], flags=re.M)[1:]
    for part in above:
        name, _, body = part.partition("\n")
        if name.strip() == UNRELEASED and not body.strip():
            continue
        raise ReleaseError(
            f'CHANGELOG.md lists changes above the section for {version}, under "## {name.strip()}": the tagged '
            f"commit holds changes its notes leave out. Tag the commit that named the section for {version}: git "
            f"tag -a v{version} <that commit>."
        )


def unwrapped(text: str) -> str:
    """``text`` with the lines of each paragraph and list item joined. CHANGELOG.md is wrapped at 110
    characters, and a release page shows each line end as a line break. Headings, list items, code blocks,
    tables, quotes and a line that ends in a hard break (two spaces, or a backslash) stay as they are."""
    lines: list[str] = []
    fenced = False
    for line in text.split("\n"):
        fence = line.lstrip().startswith(("```", "~~~"))
        previous = lines[-1] if lines else ""
        if (
            not fenced
            and not fence
            and previous.strip()
            and line.strip()
            and not BLOCK.match(line)
            and not previous.lstrip().startswith(STANDS_ALONE)
            and not previous.endswith(("  ", "\\"))
        ):
            lines[-1] = f"{previous.rstrip()} {line.strip()}"
        else:
            lines.append(line)
        fenced ^= fence
    return "\n".join(lines)


def absolute_links(text: str, ref: str) -> str:
    """``text`` with each link relative to the repository pointed at that file on GitHub at ``ref`` (a tag, or
    ``main``): pages to their GitHub page, images to the file itself, and an anchor alone to CHANGELOG.md's."""

    def absolute(link: re.Match[str]) -> str:
        image, label, target = link.groups()
        if target.startswith("#"):
            target = f"CHANGELOG.md{target}"
        kind = "raw" if image else "blob"
        return f"{image}[{label}]({REPOSITORY}/{kind}/{ref}/{target})"

    return RELATIVE_LINK.sub(absolute, text)


def notes(changelog: str, version: str) -> str:
    """The release's notes: the version's section, unwrapped and with absolute links, then how to install or
    update."""
    ref = "main" if version == UNRELEASED else f"v{version}"
    blob = f"{REPOSITORY}/blob/{ref}"
    footer = (
        f"Install or update: [Install and run]({blob}/README.md#install-and-run) · "
        f"[Updating]({blob}/README.md#updating) · [Changelog]({blob}/CHANGELOG.md)"
    )
    return f"{absolute_links(unwrapped(section(changelog, version)), ref)}\n\n---\n\n{footer}\n"


def _release(root: Path, tag: str | None, version: str | None) -> tuple[str, str]:
    """The version and its notes; for ``tag``, after checking that it names the package's version."""
    if tag is not None or version is None:
        version_here = package_version((root / INIT).read_text(encoding="utf-8"))
        if tag is not None and tag != f"v{version_here}":
            raise ReleaseError(
                f"The tag {tag} doesn't name this version: {INIT} says {version_here}, so its tag is "
                f"v{version_here}."
            )
        version = version_here
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    text = notes(changelog, version)
    if tag is not None:
        check_newest(changelog, version)
    return version, text


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 scripts/release_notes.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "version",
        nargs="?",
        help=f"the version whose notes to print (default: this one; {UNRELEASED}: a preview)",
    )
    parser.add_argument("--tag", help="the pushed tag, which must be v + this version (release.yml)")
    parser.add_argument("--out", type=Path, help="write the notes to this file instead of printing them")
    parser.add_argument("--root", type=Path, default=ROOT, help="the checkout (default: this script's)")
    args = parser.parse_args(argv)
    if args.tag is not None and args.version is not None:
        parser.error("give a version or --tag, not both")
    try:
        version, text = _release(args.root, args.tag, args.version)
    except ReleaseError as error:
        print(error, file=sys.stderr)
        return 1
    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.write_text(text, encoding="utf-8")
        print(f"Wrote the notes of {version} to {args.out}.", file=sys.stderr)
    outputs = os.environ.get("GITHUB_OUTPUT")
    if args.tag is not None and outputs:
        with Path(outputs).open("a", encoding="utf-8") as step_outputs:
            step_outputs.write(f"version={version}\nprerelease={str(is_prerelease(version)).lower()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
