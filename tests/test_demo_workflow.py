""".github/workflows/demo.yml: the online demo, the web app's browser-only build on the static demo's mock world,
goes to GitHub Pages from main, so anyone can open it without an account, and the evaluation's report page goes
beside it (``/ordnung/evals/``). A pull request only builds them; only the deploy job may write to Pages, and only
on main."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / ".github" / "workflows" / "demo.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
PAGES_URL = "https://ahmedeid1.github.io/ordnung/"
REPORT_URL = f"{PAGES_URL}evals/"


def _workflow(path: Path) -> dict[Any, Any]:
    yaml = pytest.importorskip("yaml")  # PyYAML comes with uvicorn[standard]
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1 reads the bare key `on` as True
    found = workflow.get("on", workflow.get(True))
    assert isinstance(found, dict)
    return found


def _uses(path: Path) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    for job in _workflow(path)["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                name, _, ref = step["uses"].partition("@")
                refs.setdefault(name, set()).add(ref)
    return refs


def _step(job: dict[str, Any], needle: str) -> dict[str, Any]:
    steps: list[dict[str, Any]] = job["steps"]
    (found,) = [step for step in steps if needle in step.get("run", "") or needle in step.get("uses", "")]
    return found


def test_main_and_pull_requests_that_touch_the_web_app_or_the_evaluation_build_the_pages() -> None:
    on = _triggers(_workflow(DEMO))
    assert on["push"]["branches"] == ["main"]
    for event in ("push", "pull_request"):
        assert set(on[event]["paths"]) == {
            "web/**",
            "evals/results/**",
            "evals/present/**",
            ".github/workflows/demo.yml",
        }
    assert "workflow_dispatch" in on


def test_the_evaluation_report_page_is_built_beside_the_demo_and_checked() -> None:
    """``python -m evals.present --site`` writes the report page into the demo's folder, from presentation.json
    with the standard library only (the runner's own python3: no install), and checks it before the upload; the
    page's footer names the commit."""
    build = _workflow(DEMO)["jobs"]["build"]
    site = _step(build, "evals.present")
    assert site["run"].split() == [
        "python3",
        "-m",
        "evals.present",
        "--site",
        '"$RUNNER_TEMP/demo/evals"',
        "--check-site",
        "--commit",
        '"$GITHUB_SHA"',
    ]
    steps = [step.get("run", step.get("uses", "")) for step in build["steps"]]
    vite = _step(build, "vite build")["run"]
    upload = _step(build, "actions/upload-pages-artifact")["uses"]
    assert steps.index(vite) < steps.index(site["run"]) < steps.index(upload)
    assert not any("setup-python" in step or "pip install" in step for step in steps)


def test_the_demo_is_the_browser_only_build_outside_the_committed_one() -> None:
    build = _workflow(DEMO)["jobs"]["build"]
    vite = _step(build, "vite build")
    assert vite["env"] == {"VITE_STATIC_DEMO": "1"}
    assert vite["working-directory"] == "web"
    # relative asset paths, so it runs under the project's sub-path; never into src/ordnung/web/dist
    assert "--base ./" in vite["run"]
    assert '--outDir "$RUNNER_TEMP/demo"' in vite["run"]
    assert "src/ordnung/web/dist" not in DEMO.read_text(encoding="utf-8")
    steps = [step.get("run", step.get("uses", "")) for step in build["steps"]]
    assert steps.index("npm ci") < steps.index(vite["run"])
    upload = _step(build, "actions/upload-pages-artifact")
    assert upload["with"] == {"path": "${{ runner.temp }}/demo"}


def test_only_main_deploys_and_only_the_deploy_job_may_write_to_pages() -> None:
    workflow = _workflow(DEMO)
    assert workflow["permissions"] == {"contents": "read"}
    build, deploy = workflow["jobs"]["build"], workflow["jobs"]["deploy"]
    assert "permissions" not in build
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}
    assert deploy["needs"] == "build"
    assert deploy["if"] == "github.event_name != 'pull_request' && github.ref == 'refs/heads/main'"
    assert deploy["environment"]["name"] == "github-pages"
    assert [step["uses"].partition("@")[0] for step in deploy["steps"]] == ["actions/deploy-pages"]
    # a pull request's checkout keeps no token; a deploy is never cut off by the next push
    assert _step(build, "actions/checkout")["with"] == {"persist-credentials": False}
    assert workflow["concurrency"]["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"


def test_the_demo_uses_ci_s_versions_of_the_actions_and_node_it_shares() -> None:
    demo, ci = _uses(DEMO), _uses(CI)
    for action in ("actions/checkout", "actions/setup-node"):
        assert demo[action] == ci[action]
    for action in ("actions/upload-pages-artifact", "actions/deploy-pages"):
        (ref,) = demo[action]
        assert ref.startswith("v") and ref[1:].isdigit()  # by major version, as ci.yml names its actions
    node = _step(_workflow(DEMO)["jobs"]["build"], "actions/setup-node")["with"]
    ci_nodes = {
        step["with"]["node-version"]
        for job in _workflow(CI)["jobs"].values()
        for step in job["steps"]
        if "actions/setup-node" in step.get("uses", "")
    }
    assert ci_nodes == {node["node-version"]}
    assert node["cache-dependency-path"] == "web/package-lock.json"


def test_the_readme_links_the_demo_that_needs_no_account() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    # the links under the video and in "Try it in 60 seconds"; the evaluation block links the report page beside it
    assert len(re.findall(re.escape(PAGES_URL) + r"(?!evals/)", readme)) == 2
    assert f"]({REPORT_URL})" in readme
    assert "claude.ai/artifact" not in readme  # one demo link: the copy that main rebuilds by itself
    releasing = (ROOT / "docs" / "releasing.md").read_text(encoding="utf-8")
    assert PAGES_URL in releasing
    assert "Source: GitHub Actions" in releasing
