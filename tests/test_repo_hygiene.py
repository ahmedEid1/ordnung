"""What every copy of Ordnung and every contributor needs besides the code: the web build's licence
notices, the security policy, the issue forms and the pull request template, the Node pin, the dependency
updates, the Makefile's help, the ignore file and the contributor docs' commands, files and generated files.

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
import sys
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


def test_contributors_learn_that_the_browser_checks_want_the_node_axe_asks_for() -> None:
    """`@axe-core/playwright`, the accessibility checker of `make e2e` and `make ui-audit`, asks for a newer
    Node than the web app's own range: README and CONTRIBUTING say so next to that range."""
    lock = json.loads(_text("web/package-lock.json"))
    axe = lock["packages"]["node_modules/@axe-core/playwright"]
    assert axe["engines"] == {"node": ">=22.12.0"}, (
        "a new axe: say what Node it asks for in README and CONTRIBUTING"
    )
    readme = " ".join(_text("README.md").split())
    contributing = " ".join(_text("CONTRIBUTING.md").split())
    assert "the accessibility checker that `make e2e` and `make ui-audit` use asks for 22.12+" in readme
    assert "Use 22.12+ for the browser checks (`make e2e`, `make ui-audit`)" in contributing


def test_dependabot_updates_the_actions_and_the_web_packages_and_leaves_python_to_make_constraints() -> None:
    """No ``labels``: Dependabot then adds its own (``dependencies`` with ``github_actions`` or ``javascript``) and
    creates them where they are missing, while labels it is told to use must exist first. The repository had
    none of them, so every pull request came without labels and with a comment saying so."""
    updates = _yaml(".github/dependabot.yml")["updates"]
    assert {(update["package-ecosystem"], update["directory"]) for update in updates} == {
        ("github-actions", "/"),
        ("npm", "/web"),
    }
    for update in updates:
        assert update["schedule"]["interval"] == "weekly"
        assert "labels" not in update
        groups = list(update["groups"].values())
        assert any(sorted(group["update-types"]) == ["minor", "patch"] for group in groups)
    contributing = _text("CONTRIBUTING.md")
    assert "make constraints" in contributing and "CONSTRAINTS_ARGS=--upgrade" in contributing


def _takes_major(peer: str, major: int) -> bool:
    """Whether an npm range such as ``^5.x``, ``>=4.8.4 <6.1.0`` or ``^5 || ^7`` lets in the version
    ``major.0.0``. Only the forms the lock uses are read; any other part counts as letting it in, so the test
    below errs toward saying the wait is over."""

    wanted = (major, 0, 0)
    for alternative in peer.split("||"):
        allowed = True
        for part in alternative.split():
            if caret := re.fullmatch(r"\^(\d+)(?:\.[\dx*]+)*", part):
                allowed &= int(caret[1]) == major
            elif bound := re.fullmatch(r"(>=|>|<=|<)(\d+)(?:\.(\d+))?(?:\.(\d+))?", part):
                limit = tuple(int(number or 0) for number in bound.groups()[1:])
                allowed &= {
                    ">=": wanted >= limit,
                    ">": wanted > limit,
                    "<=": wanted <= limit,
                    "<": wanted < limit,
                }[bound[1]]
        if allowed:
            return True
    return False


def test_typescript_majors_wait_until_the_packages_that_need_typescript_take_them() -> None:
    """Pull request #18 (TypeScript 7) failed at `npm ci`: openapi-typescript (``npm run gen:api``) takes
    only ``^5.x`` and typescript-eslint only below 6.1. So Dependabot skips TypeScript majors (minor and patch
    updates still come). This fails once no package in the lock refuses TypeScript 7: then remove the
    ``ignore`` rule in .github/dependabot.yml, and this test with it."""
    (npm,) = [u for u in _yaml(".github/dependabot.yml")["updates"] if u["package-ecosystem"] == "npm"]
    assert npm["ignore"] == [
        {"dependency-name": "typescript", "update-types": ["version-update:semver-major"]}
    ]
    lock = json.loads(_text("web/package-lock.json"))
    refusing = sorted(
        name.removeprefix("node_modules/")
        for name, package in lock["packages"].items()
        if "typescript" in package.get("peerDependencies", {})
        and not _takes_major(package["peerDependencies"]["typescript"], 7)
    )
    assert refusing, (
        "every package in web/package-lock.json takes TypeScript 7 now: remove the ignore rule for typescript "
        "in .github/dependabot.yml (and this test)"
    )
    named = {"openapi-typescript", "typescript-eslint"} & set(refusing)
    assert named, (
        f"the comment in .github/dependabot.yml names packages that take TypeScript 7 now: {refusing}"
    )
    # how the ranges in the lock read
    assert not _takes_major("^5.x", 7) and _takes_major("^5.x", 5)
    assert not _takes_major(">=4.8.4 <6.1.0", 7) and _takes_major(">=4.8.4 <6.1.0", 6)
    assert _takes_major(">=4.8.4", 7) and _takes_major("^5.x || ^7.0.0", 7)


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


# --------------------------------------------------------------------------------------------------
# the pull request template, the Makefile's help, the ignore file and the contributor docs
# --------------------------------------------------------------------------------------------------

#: A rule in the Makefile: its name, then what follows the colon (prerequisites and the ``##`` text).
_RULE = re.compile(r"^([a-z][a-z0-9-]*):(?![:=])(.*)$", re.M)
_needs_make = pytest.mark.skipif(shutil.which("make") is None, reason="needs make")
_needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _make_targets() -> dict[str, str]:
    """Every target the Makefile defines, with its ``##`` text ('' when it has none)."""
    return {
        name: rest.split("##", 1)[1].strip() if "##" in rest else ""
        for name, rest in _RULE.findall(_text("Makefile"))
    }


def _make(*args: str) -> str:
    """What ``make`` prints in the checkout (silent, as a top-level make, whatever runs this test)."""
    env = {key: value for key, value in os.environ.items() if key not in {"MAKEFLAGS", "MFLAGS", "MAKELEVEL"}}
    done = subprocess.run(
        ["make", "--no-print-directory", "-s", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def _section(text: str, heading: str) -> str:
    """The body of a ``## heading`` section of a Markdown page."""
    assert f"\n## {heading}\n" in text, heading
    return text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


def _commands(markdown: str) -> list[str]:
    """Every command line of a page's ``bash`` blocks, without its comment."""
    commands = []
    for block in re.findall(r"```bash\n(.*?)```", markdown, re.S):
        for line in block.splitlines():
            command = re.split(r"\s+#", line, maxsplit=1)[0].strip()
            if command and not command.startswith("#"):
                commands.append(command)
    return commands


def test_a_pull_request_template_warns_against_real_letters_and_names_what_ci_checks() -> None:
    """Pull requests are public, as issues are: the template carries the issue forms' warning, and reminds of the
    steps CI or the reviewer checks (the rebuilt web app, a recording a replay misses, the changelog)."""
    template = _text(".github/pull_request_template.md")
    assert re.search(r"\*\*Never attach real letters or personal data\*\*", template)
    boxes = re.findall(r"^- \[ \] (.+)$", template, re.M)
    assert len(boxes) >= 3 and any("real letters" in box for box in boxes)
    named = re.findall(r"`make ([a-z-]+)`", template)
    assert "build-web" in named and "`src/ordnung/web/dist`" in template
    assert set(named) <= set(_make_targets()), set(named) - set(_make_targets())
    assert "CHANGELOG.md" in template and "Unreleased" in template
    assert "recording" in template
    assert len(template.strip().splitlines()) <= 10  # a reminder, not a form


def test_every_make_target_says_what_it_does_and_help_is_the_default() -> None:
    """`make` alone installed everything, `.PHONY` named a `dev` target that did nothing, and `lint` and
    `typecheck` had no text: now a bare `make` prints the targets (`make help`)."""
    makefile = _text("Makefile")
    targets = _make_targets()
    assert "help" in targets
    assert [name for name, text in targets.items() if not text] == []
    phony = re.search(r"^\.PHONY:(.*)$", makefile, re.M)
    assert phony is not None and sorted(phony[1].split()) == sorted(targets)
    assert re.search(r"^\.DEFAULT_GOAL\s*:=\s*help\s*$", makefile, re.M)


@_needs_make
def test_make_help_prints_every_target_with_its_text() -> None:
    listed = {}
    for line in _make("help").splitlines():
        name, _, text = line.strip().partition(" ")
        listed[name] = text.strip()
    assert listed == _make_targets()
    # a bare `make` is `make help` (dry runs, so nothing is installed whatever the default is)
    assert _make("-n") == _make("-n", "help")


def test_make_eval_says_what_it_writes() -> None:
    """`make eval` (`ordnung eval`, no gate) writes the test split's results file into evals/results/ with
    today's date, unlike CI's gate (evals/run.py: a replay with thresholds writes none)."""
    from evals import run as eval_run

    targets = _make_targets()
    assert "evals/results/" in targets["eval"]
    config = eval_run.config_from_args(eval_run.build_parser().parse_args([]))
    assert config.split == "test" and config.results_dir == eval_run.RESULTS_DIR
    assert "sample life" in targets["samples"] and "dataset" not in targets["samples"]


@_needs_git
def test_git_ignores_a_linked_venv_and_claude_code_s_local_files(tmp_path: Path) -> None:
    """In a worktree with the virtual environment linked in (`ln -s …/.venv .venv`), `.venv/` (a folder only)
    let `git add -A` take the link, and nothing kept Claude Code's local settings and nested worktrees out. The
    shared settings (`.claude/settings.json`) stay committable. The web packages linked in
    (`ln -s …/web/node_modules web/node_modules`) are ignored the same way."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    shutil.copyfile(ROOT / ".gitignore", repo / ".gitignore")
    (tmp_path / "venv").mkdir()
    (tmp_path / "node_modules").mkdir()
    (repo / "web").mkdir()
    try:
        (repo / ".venv").symlink_to(tmp_path / "venv", target_is_directory=True)
        (repo / "web" / "node_modules").symlink_to(tmp_path / "node_modules", target_is_directory=True)
    except OSError:
        pytest.skip("this system makes no symbolic links")
    worktree = repo / ".claude" / "worktrees" / "wf_1"
    worktree.mkdir(parents=True)
    (worktree / "README.md").write_text("a nested checkout\n", encoding="utf-8")
    (repo / ".claude" / "settings.local.json").write_text("{}\n", encoding="utf-8")
    (repo / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout
    assert sorted(line[3:] for line in status.splitlines()) == [".claude/settings.json", ".gitignore"]


def test_every_path_contributing_names_is_in_the_repository() -> None:
    """A path in backticks (`tests/…`, `web/…`, `scripts/…`) names a file or folder that exists; patterns and
    placeholders (`*`, `<…>`) aside. What `make install` makes (`web/node_modules`, `.venv`) is not in the
    repository: CI's backend jobs run this test without it, so naming it as a path would pass only where it is
    installed."""
    named = re.findall(r"`((?:\.github|src|tests|web|scripts|evals|docs)/[^`\s]*)`", _text("CONTRIBUTING.md"))
    assert named
    installed = {"node_modules", ".venv"}
    missing = [
        path
        for path in named
        if not re.search(r"[*<>{}$…]", path)
        and (installed & set(Path(path).parts) or not (ROOT / path.split("::", 1)[0].rstrip("/")).exists())
    ]
    assert missing == []


def test_the_fast_loop_runs_tests_that_exist() -> None:
    """CONTRIBUTING's fast loop: one test file by name (pytest `-k`), one web folder (Vitest) and one end-to-end
    spec (Playwright), each of which exists."""
    commands = _commands(_section(_text("CONTRIBUTING.md"), "Fast loop"))
    runs = {
        tool: [command for command in commands if marker in command]
        for tool, marker in (
            ("pytest", ".venv/bin/pytest "),
            ("vitest", "npx vitest run "),
            ("playwright", "npx playwright test "),
        )
    }
    assert all(runs.values()), runs
    for command in runs["pytest"]:
        words = command.split()
        path = ROOT / words[1]
        keyword = words[words.index("-k") + 1]
        assert re.search(rf"^def test_\w*{keyword}", path.read_text(encoding="utf-8"), re.M), command
    for command in runs["vitest"]:
        assert (
            command.startswith("cd web && ")
            and (WEB / command.split("npx vitest run ", 1)[1].split()[0]).exists()
        )
    for command in runs["playwright"]:
        spec = command.split("npx playwright test ", 1)[1].split()[0]
        assert command.startswith("cd web && ") and spec.endswith(".spec.ts") and (WEB / spec).is_file()


def test_the_fast_loop_says_which_jobs_the_end_to_end_job_waits_for() -> None:
    """The fast loop's sentence on when CI's end-to-end job starts names exactly the jobs its ``needs:`` lists
    (ci.yml's job ids): a workflow that starts it sooner or later fails here until the sentence follows."""
    yaml = pytest.importorskip("yaml")  # PyYAML comes with uvicorn[standard]
    jobs = yaml.safe_load(_text(".github/workflows/ci.yml"))["jobs"]
    needs = jobs["e2e"]["needs"]
    needs = {needs} if isinstance(needs, str) else set(needs)
    fast_loop = " ".join(_section(_text("CONTRIBUTING.md"), "Fast loop").split())
    (sentence,) = [part for part in re.split(r"(?<=\.) ", fast_loop) if "end-to-end job" in part]
    assert "starts once" in sentence, sentence
    named = {
        job for job in jobs if job != "e2e" and re.search(rf"(?<![\w-]){re.escape(job)}(?![\w-])", sentence)
    }
    assert named == needs, f"{sentence!r} names {sorted(named)}; ci.yml's e2e needs {sorted(needs)}"


def test_one_test_file_runs_alone_as_the_fast_loop_runs_it() -> None:
    """CONTRIBUTING's fast loop runs one file with `.venv/bin/pytest`, which puts its own folder first on sys.path,
    not the checkout, and `make install` adds only `src`. A test that imports `evals` (the checks of the generated
    files among them) then found it only when a module collected before it had added the checkout, and failed
    alone: pytest's `pythonpath` setting adds it to every run. Here without the checkout on the path, as there."""
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    kept = [
        str(Path(entry).resolve())
        for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep)
        if entry and Path(entry).resolve() != ROOT
    ]
    if kept:
        env["PYTHONPATH"] = os.pathsep.join(kept)
    files = ["test_results_index.py", "test_items_export.py", "test_present.py", "test_repo_hygiene.py"]
    only = ["-k", "test_make_eval_says_what_it_writes"]
    done = subprocess.run(
        [
            sys.executable,
            "-P",
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            *(f"tests/{name}" for name in files),
            *only,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=300,
    )
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-2000:]
    assert "1 passed" in done.stdout, done.stdout[-3000:]


def _generated_rows() -> list[list[str]]:
    """The rows of CONTRIBUTING's "Generated files" table: file(s), command, what fails while it is stale."""
    table = [
        line
        for line in _section(_text("CONTRIBUTING.md"), "Generated files").splitlines()
        if line.startswith("|")
    ]
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in table[2:]]
    assert rows and all(len(row) == 3 for row in rows), rows
    return rows


def test_contributing_lists_every_generated_file_with_its_command_and_its_check() -> None:
    """Every committed file a script, a make target or a runner writes, with the command that writes it and the
    check that fails while it is stale: each named file, command and test exists, and no generator is left out."""
    import fnmatch
    import importlib.util

    import typer
    from evals import analysis
    from evals.present import build as present_build

    from ordnung import cli

    rows = _generated_rows()
    targets = _make_targets()
    listed: list[str] = []
    for files, command, check in rows:
        for pattern in re.findall(r"`([^`]+)`", files):
            assert pattern.startswith(tuple(f"{top}/" for top in ("src", "web", "evals", "docs"))) or (
                pattern in {"README.md", "constraints.txt"}
            ), pattern
            assert any(ROOT.glob(pattern.rstrip("/"))), pattern
            listed.append(pattern.rstrip("/"))
        for cell in (command, check):
            for target in re.findall(r"`make ([a-z-]+)", cell):
                assert target in targets, target
            for script in re.findall(r"\b((?:scripts|evals)/[\w/]+\.py)\b", cell):
                assert (ROOT / script).is_file(), script
            for module in re.findall(r"python -m ([\w.]+)", cell):
                assert importlib.util.find_spec(module) is not None, module
            for test in re.findall(r"`(tests/test_\w+\.py)(?:::(\w+))?`", cell):
                source = (ROOT / test[0]).read_text(encoding="utf-8")
                assert not test[1] or re.search(rf"^def {test[1]}\(", source, re.M), test
            for args in re.findall(r"`\.venv/bin/ordnung ([^`<]+)`", cell):
                # the command takes these options (`demo --rebuild` without `--no-serve` would also start the demo)
                name, *options = args.split()
                group = typer.main.get_command(cli.app)
                sub = group.get_command(group.make_context("ordnung", [name], resilient_parsing=True), name)
                assert sub is not None, args
                sub.make_context(name, list(options))  # click consumes the list it is given
                assert "--rebuild" not in options or "--no-serve" in options, args
        assert command and check, files

    def covered(path: str) -> bool:
        return any(
            path == item or path.startswith(f"{item}/") or fnmatch.fnmatch(path, item) for item in listed
        )

    made_by = " ".join(row[1] for row in rows)
    # the two scripts a make target runs are named by their target
    wrapped = {"make_sample_life.py": "samples", "make_postcode_table.py": "postcodes"}
    for script in sorted([*(ROOT / "scripts").glob("gen_mock_*.py"), *(ROOT / "scripts").glob("make_*.py")]):
        if script.name in wrapped:
            assert f"scripts/{script.name}" in _text("Makefile") and f"make {wrapped[script.name]}" in made_by
        else:
            assert f"scripts/{script.name}" in made_by, script.name
    for target in ("build-web", "openapi", "samples", "postcodes", "capture", "constraints"):
        assert f"make {target}" in made_by, target
    for path in sorted((WEB / "src" / "mocks" / "data").glob("*.ts")):
        if path.read_text(encoding="utf-8").startswith("// Generated by "):
            assert covered(f"web/src/mocks/data/{path.name}"), path.name
    for path in [*present_build.OUTPUT_PATHS, "evals/results/INDEX.json", "evals/results/items.csv"]:
        assert covered(path), path
    # the benchmark analysis (`python -m evals.analysis`), which docs/evals.md takes its numbers from: the held-out
    # re-analysis and, once it is run, the pre-registered final analysis; `make eval-reproduce` renders each again
    analyses = [
        path
        for kind in (analysis.REANALYSIS_KIND, analysis.FINAL_KIND)
        for path in sorted((ROOT / "evals" / "results").glob(f"*-{kind}.json"))
    ]
    assert analyses and "python -m evals.analysis" in made_by
    for path in analyses:
        assert covered(f"evals/results/{path.name}"), path.name
    for path in (
        "src/ordnung/web/dist/build-info.json",
        "web/openapi.json",
        "web/src/api/schema.d.ts",
        "src/ordnung/demo/samples/manifest.json",
        "src/ordnung/demo/demo_db/ordnung.db",
        "src/ordnung/demo/fixtures/extract",
        "src/ordnung/rules/data/postcodes_de.tsv",
        "docs/evals-ask.md",
        "evals/dataset/manifest.json",
        "web/e2e/fixtures/outlook-bill.msg",
        "web/e2e/fixtures/private-photo.jpg",
        # the benchmarks' recordings and their locks, written by a recording run (evals/README.md)
        "evals/recorded/claude-sonnet-5/requests.lock.json",
        "evals/recorded/ask/claude-sonnet-5/prompts.lock.json",
        "constraints.txt",
    ):
        assert covered(path), path


def test_a_generated_file_said_to_have_no_check_has_none() -> None:
    """A row whose last column says nothing checks the file holds only while no test runs its script: once one
    does (a ``tests/test_mock_<name>.py``, as for the GiroCodes), the row names that test instead."""
    tests = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "tests").glob("test_*.py"))
        if path.name != "test_repo_hygiene.py" and not path.name.startswith("test_docs_")
    }
    nothing = [row for row in _generated_rows() if row[2].startswith("nothing")]
    assert nothing
    for files, command, _ in nothing:
        for script in re.findall(r"\bscripts/(\w+)\.py\b", command):
            running = [name for name, source in tests.items() if re.search(rf"\b{script}\b", source)]
            assert not running, f"{files}: the table says nothing checks it, but {running} run(s) {script}.py"


class _Parsed(Exception):
    """Raised in place of running a command once its own parser has read its arguments."""


def _parse_only(module: str, args: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """``python -m <module> <args>`` read by the module's own parser and nothing run: it fails on a flag or a
    value the parser refuses."""
    import argparse
    import importlib

    parse = argparse.ArgumentParser.parse_args

    def parse_then_stop(self: argparse.ArgumentParser, *a: Any, **k: Any) -> Any:
        parse(self, *a, **k)
        raise _Parsed

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", parse_then_stop)
    try:
        entry = importlib.import_module(f"{module}.__main__")
    except ModuleNotFoundError:
        entry = importlib.import_module(module)
    main = getattr(entry, "main", None) or entry.run_cli
    try:
        main(args)
    except _Parsed:
        return
    except SystemExit as exc:
        pytest.fail(f"python -m {module} {' '.join(args)}: refused ({exc.code})")
    pytest.fail(f"python -m {module} {' '.join(args)}: not parsed by argparse")


def test_the_evals_readme_names_commands_that_run_and_no_number(monkeypatch: pytest.MonkeyPatch) -> None:
    """evals/README.md: every command is one its program takes, the recording commands are ones the harness
    accepts on any day (evals/harness.py: a live run refuses a set pinned to another day without
    ``--allow-another-today``), every path it names exists, and the numbers are left to docs/evals.md."""
    import shlex
    from datetime import UTC, datetime

    import typer
    from evals import harness
    from evals import run as eval_run
    from evals.ask import __main__ as ask_main
    from evals.ask import run as ask_run
    from evals.records import load_manifest

    from ordnung import cli

    readme = _text("evals/README.md")
    assert "../docs/evals.md" in readme
    assert not re.search(r"\d\s?%", readme), "the numbers are docs/evals.md's"
    for path in re.findall(r"`((?:\.\./)?[\w.-]+(?:/[\w.-]*)+)`", readme):
        # a path from this folder (`dataset/`) or from the repository's root (`src/ordnung/…`)
        assert (ROOT / "evals" / path).exists() or (ROOT / path.removeprefix("../")).exists(), path

    monkeypatch.setattr(harness, "_now", lambda: datetime(2027, 3, 3, 9, tzinfo=UTC))  # no letter's day
    commands = _commands(readme)
    live = 0
    for command in commands:
        words = shlex.split(command)
        while words and re.fullmatch(r"[A-Z_]+=\S*", words[0]):
            words = words[1:]
        program, args = words[0], words[1:]
        if program == "make":
            assert set(args) <= set(_make_targets()), command
        elif program in {".venv/bin/ordnung", "ordnung"} and args[:1] == ["eval"]:
            _parse_only("evals.run", args[1:], monkeypatch)
            module, args = "evals.run", args[1:]
        elif program in {".venv/bin/ordnung", "ordnung"}:
            group = typer.main.get_command(cli.app)
            sub = group.get_command(group.make_context("ordnung", args[:1], resilient_parsing=True), args[0])
            assert sub is not None, command
            sub.make_context(args[0], args[1:])  # refuses an option the command doesn't take
            continue
        else:
            assert program in {".venv/bin/python", "python"} and args[0] == "-m", command
            module, args = args[1], args[2:]
            _parse_only(module, args, monkeypatch)
        monkeypatch.undo()
        monkeypatch.setattr(harness, "_now", lambda: datetime(2027, 3, 3, 9, tzinfo=UTC))
        if program == "make" or "--live" not in args:
            continue
        live += 1
        if module == "evals.ask":
            ns = ask_main.parse_args(args)
            ask_run.recording_day(
                ask_run.Config(
                    set_name=ns.set,
                    live=True,
                    today=ns.today,
                    allow_another_today=ns.allow_another_today,
                    recorded_dir=ns.recorded_dir or ask_run.RECORDED_DIR,
                )
            )
        else:
            assert module == "evals.run", command
            config = eval_run.config_from_args(eval_run.build_parser().parse_args(args))
            entries = [
                entry for entry in load_manifest(eval_run.MANIFEST_PATH) if entry.split == config.split
            ]
            eval_run.recording_day(config, entries)
    assert live >= 2 and any(command.startswith("make eval-reproduce") for command in commands)


class _RunAsked(Exception):
    """Raised in place of a benchmark run, with the configuration ``run_cli`` built for it."""


def test_the_evals_readme_s_replays_write_no_results_file_into_the_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A replay without the gate's thresholds writes a results file, and one in evals/results/ that INDEX.json
    doesn't list fails `make eval-reproduce` and the results index tests (the commands they print would then write
    the throwaway replay into INDEX.json and the history page): every replay the README gives writes its file into
    a folder of its own, or none. `make eval` writes into evals/results/, so its help line says what fails."""
    import shlex

    from evals import run as eval_run

    async def ask_run(config: Any, **_: Any) -> Any:
        raise _RunAsked(config)

    monkeypatch.setattr(eval_run, "run_benchmark", ask_run)
    replays = _commands(_section(_text("evals/README.md"), "Replay (no model call, no tokens)"))
    benchmark = 0
    for command in replays:
        words = shlex.split(command)
        if words[:2] in ([".venv/bin/ordnung", "eval"], ["ordnung", "eval"]):
            args = words[2:]
        elif words[1:3] == ["-m", "evals.run"]:
            args = words[3:]
        else:
            assert "make eval" not in command or command.startswith("make eval-reproduce"), command
            continue
        benchmark += 1
        with pytest.raises(_RunAsked) as asked:
            eval_run.run_cli(args)
        config = asked.value.args[0]
        writes_here = config.write_results and config.results_dir.resolve().is_relative_to(ROOT)
        assert not writes_here, (
            f"{command}: writes {config.results_dir / config.results_name(config.models[0])}"
        )
    assert benchmark >= 2
    assert "evals/results/" in _make_targets()["eval"] and "make eval-reproduce" in _make_targets()["eval"]


def test_the_repository_settings_are_the_project_s_own() -> None:
    """docs/releasing.md lists what only the owner sets on GitHub: the website is the online demo, the topics
    leave out `rag` (ADR 0005: no vector database), and private vulnerability reporting is the step SECURITY.md
    asks of the owner."""
    from evals.present import PAGES_URL

    settings = " ".join(
        _section(_text("docs/releasing.md"), "Repository settings (once, by the owner)").split()
    )
    assert PAGES_URL.removesuffix("evals/") in settings
    topics = re.search(r"\*Topics\*: (.+?) - \*", settings)  # up to the next item
    assert topics is not None
    names = re.findall(r"`([^`]+)`", topics[1])
    assert names and "rag" not in names and all(re.fullmatch(r"[a-z0-9-]+", name) for name in names)
    for setting in (
        "Social preview",
        "Pull request title and description",
        "Automatically delete head branches",
    ):
        assert setting in settings, setting
    assert "Private vulnerability reporting" in settings
    assert "private vulnerability reporting" in _text("SECURITY.md").lower()
