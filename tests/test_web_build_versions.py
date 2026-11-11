"""The committed web build was made from the packages the lockfile pins.

The build's THIRD-PARTY-NOTICES.txt names each bundled package with the version it was built from. A
dependency update that changes ``web/package-lock.json`` without a rebuild (``npm ci``, then
``make build-web``) leaves the committed build, and so the wheel, on the old code while the lockfile and
the notices' licences say otherwise. This compares the two without Node, so it runs everywhere.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTICES = ROOT / "src" / "ordnung" / "web" / "dist" / "THIRD-PARTY-NOTICES.txt"
LOCKFILE = ROOT / "web" / "package-lock.json"

#: Each package's section in the notices opens with a rule of 80 dashes, then ``name version``.
_SECTION = re.compile(r"^-{80}\n(\S+) (\S+)\nLicence: ", re.M)


def _built_from() -> list[tuple[str, str]]:
    return _SECTION.findall(NOTICES.read_text(encoding="utf-8"))


def _pinned() -> dict[str, str]:
    """Each package the lockfile installs at the top of node_modules, with its version."""
    packages = json.loads(LOCKFILE.read_text(encoding="utf-8"))["packages"]
    prefix = "node_modules/"
    return {
        path.removeprefix(prefix): entry["version"]
        for path, entry in packages.items()
        if path.startswith(prefix) and "/node_modules/" not in path[len(prefix) :] and "version" in entry
    }


def test_the_notices_name_the_packages_of_the_build() -> None:
    """The parse below finds every section, so the comparison is not empty by accident."""
    listed = _built_from()
    names = [name for name, _ in listed]
    assert len(listed) >= 40, listed
    assert len(set(names)) == len(names), names
    for name in ("react", "react-dom", "@tanstack/react-query", "lucide-react", "motion", "vite"):
        assert name in names, name


def test_every_bundled_package_is_the_version_the_lockfile_pins() -> None:
    """After a dependency update, ``npm ci`` and ``make build-web`` bring the build to the lockfile."""
    pinned = _pinned()
    stale = {
        name: f"built from {version}, the lockfile pins {pinned.get(name, 'nothing')}"
        for name, version in _built_from()
        if pinned.get(name) != version
    }
    assert not stale, stale
