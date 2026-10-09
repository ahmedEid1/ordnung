"""What every copy of Ordnung needs besides the code: the web build's licence notices.

Written by a release audit: the build stripped every licence comment and no notices file shipped (the
fonts' SIL Open Font License and the MIT and ISC licences of the bundled code need their notice to
travel with copies).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
NOTICES = "THIRD-PARTY-NOTICES.txt"

_needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
#: Skipped without Node and the web app's packages, except where ``ORDNUNG_REQUIRE_MOCK_CHECK=1`` (CI's
#: end-to-end job, which has both toolchains): there a missing toolchain fails, so CI always builds.
_needs_web = pytest.mark.skipif(
    os.environ.get("ORDNUNG_REQUIRE_MOCK_CHECK") != "1"
    and (shutil.which("node") is None or not (WEB / "node_modules" / ".bin").exists()),
    reason="needs node and web/node_modules (npm ci in web/)",
)


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _yaml(path: str) -> Any:
    yaml = pytest.importorskip("yaml")  # PyYAML comes with uvicorn[standard]
    return yaml.safe_load(_text(path))


# --------------------------------------------------------------------------------------------------
# the web build's third-party notices
# --------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def web_build(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The web app built the way `make build-web` builds it, into a folder of its own."""
    out = tmp_path_factory.mktemp("web-build")
    built = subprocess.run(
        [str(WEB / "node_modules" / ".bin" / "vite"), "build", "--outDir", str(out), "--emptyOutDir"],
        cwd=WEB,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CI": ""},
    )
    assert built.returncode == 0, (built.stdout + built.stderr)[-2000:]
    return out


def _listed(notices: str) -> dict[str, str]:
    """Each package the notices list, with the licence they name for it."""
    return dict(re.findall(r"^-{80}\n(\S+) \S+\nLicence: (.+)$", notices, re.M))


@pytest.mark.slow
@_needs_web
def test_a_web_build_ships_the_licence_of_every_package_it_bundles(web_build: Path) -> None:
    notices = (web_build / NOTICES).read_text(encoding="utf-8")
    listed = _listed(notices)
    # the fonts: the SIL Open Font License's whole text travels with them
    families = {font.name.split("-")[0] for font in (web_build / "assets").glob("*.woff2")}
    assert families == {"inter", "fraunces"}
    for family in families:
        assert listed[f"@fontsource-variable/{family}"] == "OFL-1.1", family
    assert notices.count("SIL OPEN FONT LICENSE Version 1.1") >= len(families)
    assert "OTHER DEALINGS IN THE FONT SOFTWARE" in notices
    # the code: from the scripts' modules, the stylesheet's imports and the build tool's helpers
    for name, licence in {
        "react": "MIT",
        "react-dom": "MIT",
        "@tanstack/react-query": "MIT",
        "recharts": "MIT",
        "d3-scale": "ISC",
        "lucide-react": "ISC",
        "tailwindcss": "MIT",
        "vite": "MIT",
    }.items():
        assert listed.get(name) == licence, name
    assert "Permission is hereby granted, free of charge" in notices  # MIT's text
    assert "Permission to use, copy, modify, and/or distribute this software" in notices  # ISC's
    # only what the build bundles: not the test tools, not the licences of Vite's own Node code
    for name in ("vitest", "@playwright/test", "typescript", "eslint", "rollup"):
        assert name not in listed, name
    assert "# Licenses of bundled dependencies" not in notices
    assert "Python packages" in notices and "not bundled" in notices


def test_ci_builds_the_web_app_and_checks_its_notices() -> None:
    """The build test skips without web/node_modules: CI runs it where both toolchains are, and must."""
    jobs = _yaml(".github/workflows/ci.yml")["jobs"]
    steps = [step for job in jobs.values() for step in job["steps"]]
    test = "tests/test_repo_hygiene.py::test_a_web_build_ships_the_licence_of_every_package_it_bundles"
    runs = [step for step in steps if test in step.get("run", "")]
    assert runs and all(step["env"]["ORDNUNG_REQUIRE_MOCK_CHECK"] == "1" for step in runs)
    assert any("node scripts/source-hash.mjs --check" in step.get("run", "") for step in steps)


@_needs_node
def test_the_freshness_check_fails_when_the_build_has_no_notices(tmp_path: Path) -> None:
    """CI's freshness check (web/scripts/source-hash.mjs --check) refuses a committed build without
    its notices, so the wheel, which carries that build, always has them."""
    current = subprocess.run(
        ["node", "scripts/source-hash.mjs"], cwd=WEB, capture_output=True, text=True, check=True
    ).stdout.strip()
    (tmp_path / "build-info.json").write_text(json.dumps({"sourceHash": current}), encoding="utf-8")

    def check() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["node", "scripts/source-hash.mjs", "--check", str(tmp_path / "build-info.json")],
            cwd=WEB,
            capture_output=True,
            text=True,
            check=False,
        )

    missing = check()
    assert missing.returncode == 1 and NOTICES in missing.stderr, missing.stderr
    (tmp_path / NOTICES).write_text("notices\n", encoding="utf-8")
    present = check()
    assert present.returncode == 0, present.stderr


@_needs_node
def test_a_change_to_the_notices_script_makes_the_committed_build_stale(tmp_path: Path) -> None:
    """The notices script is part of what the build is made from: CI's freshness check notices a build
    that predates a change to it."""
    for folder in ("src", "public", "scripts"):
        (tmp_path / folder).mkdir()
    for name in ("index.html", "package-lock.json", "vite.config.ts", "tsconfig.json"):
        (tmp_path / name).write_text("", encoding="utf-8")
    for name in ("tsconfig.app.json", "tsconfig.node.json"):
        (tmp_path / name).write_text("", encoding="utf-8")
    script = tmp_path / "scripts" / "third-party-notices.mjs"

    def source_hash() -> str:
        module = (WEB / "scripts" / "source-hash.mjs").as_uri()
        code = f"import({json.dumps(module)}).then((m) => console.log(m.sourceHash(process.argv[1])))"
        return subprocess.run(
            ["node", "-e", code, str(tmp_path)], capture_output=True, text=True, check=True
        ).stdout.strip()

    script.write_text("export const a = 1;\n", encoding="utf-8")
    before = source_hash()
    script.write_text("export const a = 2;\n", encoding="utf-8")
    assert source_hash() != before


def test_the_wheel_lists_the_notices_among_its_licence_files() -> None:
    """The notices are in the committed build, which the wheel carries (and so its licence files)."""
    pyproject = tomllib.loads(_text("pyproject.toml"))
    assert f"src/ordnung/web/dist/{NOTICES}" in pyproject["project"]["license-files"]
    assert "src/ordnung/web/dist/**" in pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["artifacts"]


def test_the_readme_says_where_the_bundled_licences_are() -> None:
    readme = _text("README.md")
    disclaimer = readme.split("## Disclaimer", 1)[1]
    assert f"src/ordnung/web/dist/{NOTICES}" in disclaimer
    assert "SIL Open Font License" in disclaimer
