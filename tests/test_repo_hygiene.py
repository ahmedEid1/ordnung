"""What every copy of Ordnung and every contributor needs besides the code: the web build's licence
notices, the security policy, the issue forms, the Node pin and the dependency updates.

Written by a release audit: the build stripped every licence comment and no notices file shipped (the
fonts' SIL Open Font License and the MIT and ISC licences of the bundled code need their notice to
travel with copies), nothing said how to report a vulnerability privately, nothing warned a bug reporter
against attaching real letters, contributors had no Node pin, and pins moved only by hand.
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
GITHUB = "https://github.com/ahmedEid1/ordnung"

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


def test_the_wheel_s_licence_expression_names_every_licence_it_ships() -> None:
    """Audit (batch A review): the wheel said ``License-Expression: MIT`` beside notices for ISC and OFL-1.1
    code and fonts, the DejaVu fonts (Bitstream Vera) and GeoNames' postcodes (CC BY 4.0)."""
    pyproject = tomllib.loads(_text("pyproject.toml"))
    expression = set(pyproject["project"]["license"].split(" AND "))
    notices = _text(f"src/ordnung/web/dist/{NOTICES}")
    named = {part for line in re.findall(r"^Licence: (.+)$", notices, re.M) for part in line.split(" AND ")}
    assert named and named <= expression, named - expression
    assert "License: bitstream-vera" in _text("src/ordnung/drafts/fonts/LICENSE-DejaVu.txt")
    assert "Bitstream-Vera" in expression
    assert "CC BY 4.0" in _text("src/ordnung/rules/data/LICENSE-GeoNames.txt")
    assert "CC-BY-4.0" in expression


def test_the_readme_says_where_the_bundled_licences_are() -> None:
    readme = _text("README.md")
    disclaimer = readme.split("## Disclaimer", 1)[1]
    assert f"src/ordnung/web/dist/{NOTICES}" in disclaimer
    assert "SIL Open Font License" in disclaimer


# --------------------------------------------------------------------------------------------------
# reporting a vulnerability, a bug or an idea
# --------------------------------------------------------------------------------------------------


def test_security_problems_are_reported_privately() -> None:
    policy = _text("SECURITY.md")
    assert f"{GITHUB}/security/advisories/new" in policy
    assert "Report a vulnerability" in policy
    assert "private vulnerability reporting" in policy.lower()  # the owner has to turn it on
    for part in ("phone", "sync folder", "backup", "127.0.0.1", "MCP"):
        assert part in policy, part
    assert re.search(r"\*\*Never (send|include|attach) real letters", policy)
    config = _yaml(".github/ISSUE_TEMPLATE/config.yml")
    assert config["blank_issues_enabled"] is False
    assert any(link["url"] == f"{GITHUB}/blob/main/SECURITY.md" for link in config["contact_links"])


def test_without_private_reporting_a_security_contact_issue_asks_for_nothing_about_the_problem() -> None:
    """Audit (batch A review): SECURITY.md's fallback was an issue "that says nothing else", but blank
    issues are off and the bug form requires what happened and the steps. A form of its own asks for
    nothing but a box ticked to say the issue tells nothing about the problem."""
    form = _form(".github/ISSUE_TEMPLATE/security_contact.yml")
    assert form["title"] == "Security contact"
    fields = [element for element in form["body"] if element["type"] != "markdown"]
    assert [field["type"] for field in fields] == ["checkboxes"]
    assert all(option["required"] is True for option in fields[0]["attributes"]["options"])
    assert _warns_against_real_letters(form)
    policy = " ".join(_text("SECURITY.md").split())
    assert "**Security contact** form" in policy
    assert "says nothing else" not in policy


def _form(path: str) -> dict[str, Any]:
    form = _yaml(path)
    assert form["name"] and form["description"], path
    ids = [element["id"] for element in form["body"] if "id" in element]
    assert len(ids) == len(set(ids)), path
    return dict(form)


def _warns_against_real_letters(form: dict[str, Any]) -> bool:
    return any(
        element["type"] == "markdown"
        and re.search(r"\*\*Never attach real letters", element["attributes"]["value"])
        for element in form["body"]
    )


def test_the_bug_report_asks_for_the_version_and_the_doctor_and_warns_against_real_letters() -> None:
    form = _form(".github/ISSUE_TEMPLATE/bug_report.yml")
    assert _warns_against_real_letters(form)
    fields = {element["id"]: element for element in form["body"] if "id" in element}
    for field, command in (("version", "ordnung --version"), ("doctor", "ordnung doctor")):
        assert command in json.dumps(fields[field]["attributes"]), field
        assert fields[field]["validations"]["required"] is True, field
    assert "ordnung demo" in json.dumps(form)
    # doctor's sync line names this computer and the other one ("Annas-MacBook-Pro"), and the folders
    assert "computers' names" in fields["doctor"]["attributes"]["description"]
    options = fields["no-personal-data"]["attributes"]["options"]
    assert all(option["required"] is True for option in options)


def test_the_feature_request_warns_against_real_letters_too() -> None:
    assert _warns_against_real_letters(_form(".github/ISSUE_TEMPLATE/feature_request.yml"))


# --------------------------------------------------------------------------------------------------
# contributing: the Node pin, the checks and the dependency updates
# --------------------------------------------------------------------------------------------------


def test_contributors_get_the_node_versions_the_readme_requires() -> None:
    """README: Node.js 20.19+ or 22.12+ (what Vite 8 needs). The web app's package says so, and
    `.nvmrc` picks the line CI tests on."""
    assert "Node.js 20.19+ or 22.12+" in _text("README.md")
    package = json.loads(_text("web/package.json"))
    lock = json.loads(_text("web/package-lock.json"))
    assert package["engines"] == {"node": "^20.19.0 || >=22.12.0"}
    assert lock["packages"][""]["engines"] == package["engines"]
    nvmrc = _text(".nvmrc").strip()
    assert nvmrc in ("20", "22")
    steps = [step for job in _yaml(".github/workflows/ci.yml")["jobs"].values() for step in job["steps"]]
    node = [step["with"] for step in steps if str(step.get("uses", "")).startswith("actions/setup-node@")]
    assert node
    for setup in node:
        assert setup.get("node-version-file") == ".nvmrc" or str(setup.get("node-version")) == nvmrc, setup


def test_dependabot_updates_the_actions_and_the_web_packages_and_leaves_python_to_make_constraints() -> None:
    updates = _yaml(".github/dependabot.yml")["updates"]
    assert {(update["package-ecosystem"], update["directory"]) for update in updates} == {
        ("github-actions", "/"),
        ("npm", "/web"),
    }
    for update in updates:
        assert update["schedule"]["interval"] == "weekly"
        assert update["labels"]
        groups = list(update["groups"].values())
        assert any(sorted(group["update-types"]) == ["minor", "patch"] for group in groups)
    contributing = _text("CONTRIBUTING.md")
    assert "make constraints" in contributing and "CONSTRAINTS_ARGS=--upgrade" in contributing


def test_every_environment_variable_contributing_names_is_read_somewhere() -> None:
    """Audit (batch A review): CONTRIBUTING named ``ORDNUNG_LIVE_TESTS=1`` for tests that call Claude,
    though no such tests were left and nothing read the variable."""
    named = set(re.findall(r"\bORDNUNG_[A-Z_]+\b", _text("CONTRIBUTING.md")))
    code = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for folder in ("src/ordnung", "tests", "scripts", "evals", ".github")
        for path in (ROOT / folder).rglob("*")
        if path.suffix in {".py", ".yml", ".yaml", ".ts", ".mjs"}
        and "dist" not in path.parts
        and path != Path(__file__).resolve()
    )
    for variable in named:
        assert re.search(rf"\b{variable}\b", code), variable
    assert "never call Claude" in " ".join(_text("CONTRIBUTING.md").split())


def test_contributing_gives_ci_s_own_checks_and_the_rule_about_real_letters() -> None:
    """The checks CONTRIBUTING.md lists are CI's commands with CI's thresholds, word for word."""
    contributing = _text("CONTRIBUTING.md")
    for command in ("make install", "make check", "make e2e", "make build-web", "make openapi"):
        assert command in contributing, command
    checks = contributing.split("## Checks", 1)[1].split("\n## ", 1)[0]
    listed = [" ".join(line.split()) for line in checks.splitlines() if line.startswith(".venv/bin/")]
    jobs = _yaml(".github/workflows/ci.yml")["jobs"]
    ci = "\n".join(" ".join(step.get("run", "").split()) for job in jobs.values() for step in job["steps"])
    for needed in ("--cov=ordnung.rules", "ordnung eval", "evals.ask", "ordnung demo --check"):
        assert any(needed in command for command in listed), needed
    for command in listed:
        assert command in ci, command
    assert re.search(r"\*\*Never (commit|attach|paste|share)[^*]*real letters", contributing)
    assert "SECURITY.md" in contributing
