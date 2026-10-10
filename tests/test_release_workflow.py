""".github/workflows/release.yml: a pushed version tag builds and checks the sdist and the wheel, publishes a
GitHub Release with the changelog's section, and goes to PyPI only once the owner has turned that on. It never
runs for a pull request, stores no token, and gives each job only the rights it needs."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
REPOSITORY = "ahmedEid1/ordnung"


def _workflow(path: Path = RELEASE) -> dict[Any, Any]:
    yaml = pytest.importorskip("yaml")  # PyYAML comes with uvicorn[standard]
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _jobs(path: Path = RELEASE) -> dict[str, Any]:
    return dict(_workflow(path)["jobs"])


def _runs(job: dict[str, Any]) -> list[str]:
    return [step["run"] for step in job["steps"] if "run" in step]


def _step_index(job: dict[str, Any], needle: str) -> int:
    (index,) = [i for i, step in enumerate(job["steps"]) if needle in step.get("run", "")]
    return index


def _uses(path: Path) -> dict[str, str]:
    """Each action a workflow uses, with its ref (``actions/checkout`` → ``v5``)."""
    refs: dict[str, set[str]] = {}
    for job in _jobs(path).values():
        for step in job["steps"]:
            if "uses" in step:
                name, _, ref = step["uses"].partition("@")
                refs.setdefault(name, set()).add(ref)
    assert all(len(found) == 1 for found in refs.values()), refs  # one version of each action per file
    return {name: found.pop() for name, found in refs.items()}


def test_only_a_pushed_version_tag_starts_a_release() -> None:
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))  # PyYAML reads the key `on` as True
    assert triggers == {"push": {"tags": ["v*"]}}
    concurrency = workflow["concurrency"]
    assert concurrency["cancel-in-progress"] is False and "github.ref" in concurrency["group"]
    assert all(job["timeout-minutes"] <= 30 for job in _jobs().values())


def test_each_job_gets_only_the_rights_it_needs() -> None:
    """Nothing by default; the build reads the code, the GitHub Release writes with the run's own token, and
    only the PyPI job may ask for the OIDC token PyPI checks."""
    assert _workflow()["permissions"] == {}
    jobs = _jobs()
    assert set(jobs) == {"build", "github-release", "pypi"}
    # the build reads the code, and CI's runs to check that CI passed on the tagged commit
    assert jobs["build"]["permissions"] == {"contents": "read", "actions": "read"}
    assert jobs["github-release"]["permissions"] == {"contents": "write"}
    assert jobs["pypi"]["permissions"] == {"id-token": "write"}


def test_pypi_waits_for_the_owner_s_switch_and_never_runs_for_a_pull_request_or_a_fork() -> None:
    pypi = _jobs()["pypi"]
    condition = " ".join(pypi["if"].split())
    for gate in (
        "vars.PYPI_PUBLISH == 'true'",
        "github.event_name == 'push'",
        "startsWith(github.ref, 'refs/tags/v')",
        f"github.repository == '{REPOSITORY}'",
    ):
        assert gate in condition, gate
    assert "||" not in condition and "always()" not in condition  # every gate must hold
    assert pypi["environment"]["name"] == "pypi"
    assert set(pypi["needs"]) == {"build", "github-release"}  # last: an upload can never be replaced
    assert [step.get("uses", "").split("@")[0] for step in pypi["steps"]] == [
        "actions/download-artifact",
        "pypa/gh-action-pypi-publish",
    ]
    publish = pypi["steps"][-1]
    assert set(publish.get("with", {})) <= {"packages-dir", "print-hash"}  # Trusted Publishing: no password


def test_no_token_or_password_is_stored_or_handed_over() -> None:
    """Trusted Publishing needs no stored secret; the GitHub Release uses the run's own short-lived token. (The
    file's comments may say so; what runs never names a secret, a password or an API token.)"""
    text = json.dumps(_workflow())
    for word in ("secret", "password", "api_token", "api-token", "twine_", "pypi-ag", "user:"):
        assert word not in text.lower(), word
    tokens = re.findall(r"\$\{\{([^}]*token[^}]*)\}\}", text, re.I)
    assert {token.strip() for token in tokens} == {"github.token"}, tokens
    assert _jobs()["github-release"]["steps"][-1]["env"]["GH_TOKEN"] == "${{ github.token }}"


def test_no_script_runs_a_value_from_the_push() -> None:
    """A tag name or commit message pasted into a script with ${{ }} could run as shell; the scripts read the
    runner's environment variables instead."""
    for name, job in _jobs().items():
        for run in _runs(job):
            assert "${{" not in run, (name, run)


def test_the_build_checks_the_tag_the_branch_and_the_files_before_anything_is_published() -> None:
    build = _jobs()["build"]
    checkout = build["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"] == {"fetch-depth": 0, "persist-credentials": False}
    order = [
        'python3 scripts/release_notes.py --tag "$GITHUB_REF_NAME" --out release-notes.md',
        'git merge-base --is-ancestor "$GITHUB_SHA" origin/main',
        "actions/workflows/ci.yml/runs?head_sha=$GITHUB_SHA&event=push&status=success",
        "node scripts/source-hash.mjs --check ../src/ordnung/web/dist/build-info.json",
        "uv build",
        "uvx twine check --strict dist/*",
        '"$RUNNER_TEMP/wheel/bin/ordnung" demo --check',
    ]
    indices = [_step_index(build, needle) for needle in order]
    assert indices == sorted(indices), dict(zip(order, indices, strict=True))
    notes_step = build["steps"][indices[0]]
    assert build["outputs"] == {
        "version": f"${{{{ steps.{notes_step['id']}.outputs.version }}}}",
        "prerelease": f"${{{{ steps.{notes_step['id']}.outputs.prerelease }}}}",
    }
    uploads = {
        step["with"]["name"]: step["with"]
        for step in build["steps"]
        if "upload-artifact" in step.get("uses", "")
    }
    assert uploads["dist"]["path"] == "dist/"  # the distributions only: PyPI's action uploads all of dist/
    assert uploads["notes"]["path"] == "release-notes.md"
    assert all(upload["if-no-files-found"] == "error" for upload in uploads.values())


def test_the_build_checks_the_files_as_ci_s_wheel_job_does_and_more() -> None:
    script = "\n".join(_runs(_jobs()["build"]))
    wheel = _jobs(ROOT / ".github/workflows/ci.yml")["wheel"]
    for line in "\n".join(_runs(wheel)).splitlines():
        assert line.strip() in script, line
    assert 'grep -q " ordnung/demo/demo_db/ordnung.db$"' in script


def test_the_github_release_has_the_notes_and_both_files_and_checks_out_no_code() -> None:
    release = _jobs()["github-release"]
    assert release["needs"] == "build" or release["needs"] == ["build"]
    assert not any("checkout" in step.get("uses", "") for step in release["steps"])
    (run,) = _runs(release)
    command = " ".join(run.replace("\\\n", " ").split())
    assert 'gh release create "$GITHUB_REF_NAME" dist/*' in command
    for flag in ("--verify-tag", "--notes-file notes/release-notes.md", '--repo "$GITHUB_REPOSITORY"'):
        assert flag in command, flag
    assert "--prerelease" in command
    assert release["steps"][-1]["env"]["PRERELEASE"] == "${{ needs.build.outputs.prerelease }}"


def test_ci_must_have_passed_on_the_tagged_commit() -> None:
    """Being on main isn't enough: CI's run for that commit on main must have passed (a scheduled run skips the
    tests, so only a push counts)."""
    build = _jobs()["build"]
    step = build["steps"][_step_index(build, "actions/workflows/ci.yml/runs")]
    assert step["env"] == {"GH_TOKEN": "${{ github.token }}"}
    assert "gh api" in step["run"] and "exit 1" in step["run"]


def test_the_release_build_restores_no_cache() -> None:
    """A cache another run wrote could change what the release builds and uploads."""
    for step in _jobs()["build"]["steps"]:
        uses = step.get("uses", "")
        if uses.startswith("astral-sh/setup-uv@"):
            assert step["with"]["enable-cache"] is False
        if uses.startswith("actions/setup-node@"):
            assert step["with"]["package-manager-cache"] is False


def test_the_actions_are_pinned_to_commits_of_the_versions_ci_uses() -> None:
    """The PyPI job holds the token PyPI accepts as the owner: every action of the release runs a fixed commit,
    never a tag or branch that can be moved, with its version beside it (Dependabot keeps both up to date), and
    the same major version as CI's."""
    ci = _uses(ROOT / ".github/workflows/ci.yml")
    text = RELEASE.read_text(encoding="utf-8")
    pinned = dict(re.findall(r"uses: ([\w.-]+/[\w.-]+)@[0-9a-f]{40} # (v\d+\.\d+\.\d+)$", text, re.M))
    assert set(pinned) == set(_uses(RELEASE)), "every action of release.yml is pinned to a commit"
    assert len(re.findall(r"uses: ", text)) == len(re.findall(r"uses: \S+@[0-9a-f]{40} # v", text))
    for name, version in pinned.items():
        if name in ci:
            assert version.split(".")[0] == ci[name], name
    assert pinned["pypa/gh-action-pypi-publish"].startswith("v1.")  # its documented release/v1 line
    assert set(pinned) - set(ci) == {"actions/download-artifact", "pypa/gh-action-pypi-publish"}
    nvmrc = (ROOT / ".nvmrc").read_text(encoding="utf-8").strip()
    for job in _jobs().values():
        for step in job["steps"]:
            if step.get("uses", "").startswith("actions/setup-node@"):
                assert str(step["with"]["node-version"]) == nvmrc


def test_ci_s_wheel_job_checks_that_the_description_renders_on_pypi() -> None:
    wheel = _jobs(ROOT / ".github/workflows/ci.yml")["wheel"]
    assert _step_index(wheel, "uvx twine check --strict dist/*") == _step_index(wheel, "uv build") + 1


def test_releasing_md_says_how_to_release_and_how_the_owner_turns_pypi_on() -> None:
    text = (ROOT / "docs" / "releasing.md").read_text(encoding="utf-8")
    for target in re.findall(r"\]\((?![a-z][a-z0-9+.-]*:|#)([^)#\s]+)", text):
        assert (ROOT / "docs" / target).resolve().exists(), target
    page = " ".join(text.split())
    for needed in (
        "git tag -a vX.Y.Z <merge commit>",
        "git push origin v",
        "Required reviewers",
        "ruleset",
        "python3 scripts/release_notes.py",
        "## Unreleased",
        "pending publisher",
        "Trusted Publishing",
        "release.yml",
        "`pypi`",
        "PYPI_PUBLISH",
        REPOSITORY.split("/")[0],
        "npm version",
        "make openapi",
        "ordnung demo --rebuild",
        "make build-web",
    ):
        assert needed in page, needed


# --------------------------------------------------------------------------------------------------
# the PyPI page: the README, with every link and picture pointing to GitHub
# --------------------------------------------------------------------------------------------------

GITHUB = f"https://github.com/{REPOSITORY}"
BLOB = f"{GITHUB}/blob/main/"
RAW = f"https://raw.githubusercontent.com/{REPOSITORY}/main/"


def _pyproject() -> dict[str, Any]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _pypi_description() -> str:
    """What PyPI shows: the README after pyproject.toml's substitutions, applied as hatch-fancy-pypi-readme
    applies them (``re.sub`` over the joined fragments)."""
    hook = _pyproject()["tool"]["hatch"]["metadata"]["hooks"]["fancy-pypi-readme"]
    text = "".join((ROOT / fragment["path"]).read_text(encoding="utf-8") for fragment in hook["fragments"])
    for substitution in hook["substitutions"]:
        flags = re.IGNORECASE if substitution.get("ignore-case") else 0
        text = re.sub(substitution["pattern"], substitution["replacement"], text, flags=flags)
    return text


def test_the_pypi_page_is_the_readme_with_every_link_and_picture_pointing_to_github() -> None:
    """PyPI shows the README without the repository around it: a relative link or picture is broken there, and
    so is an anchor (PyPI gives headings no ids)."""
    project = _pyproject()["project"]
    assert "readme" not in project and "readme" in project["dynamic"]
    hook = _pyproject()["tool"]["hatch"]["metadata"]["hooks"]["fancy-pypi-readme"]
    assert hook["content-type"] == "text/markdown"
    assert hook["fragments"] == [{"path": "README.md"}]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    description = _pypi_description()
    left = re.findall(r'(?:src|href)="(?!https?://)[^"]*"|\]\((?![a-z][a-z0-9+.-]*:)[^)\s]+\)', description)
    assert not left, left
    for page in re.findall(rf"{re.escape(BLOB)}([^)\"#\s]+)", description):
        assert (ROOT / page).exists(), page
    pictures = re.findall(rf"{re.escape(RAW)}([^)\"\s]+)", description)
    assert len(pictures) >= 20 and all((ROOT / picture).is_file() for picture in pictures)
    assert re.search(rf'href="{re.escape(GITHUB)}#install-and-run"', description)
    # nothing else changed: taking the prefixes away gives the README back
    assert description.replace(RAW, "").replace(BLOB, "").replace(f"{GITHUB}#", "#") == readme


def test_the_readme_plugin_is_pinned_and_the_sdist_leaves_out_the_readme_s_pictures() -> None:
    """The plugin writes what PyPI shows, so a release builds it with one known version. The pictures (15 MB)
    stay on GitHub, where the PyPI page loads them from."""
    pyproject = _pyproject()
    requires = pyproject["build-system"]["requires"]
    assert "hatchling>=1.26" in requires
    (plugin,) = [requirement for requirement in requires if requirement.startswith("hatch-fancy-pypi-readme")]
    assert re.fullmatch(r"hatch-fancy-pypi-readme==\d+\.\d+\.\d+", plugin), plugin
    sdist = pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]
    assert sdist["exclude"] == ["docs/assets"]
    assert {"src/ordnung", "README.md", "CHANGELOG.md", "LICENSE", "docs"} <= set(sdist["include"])
