"""The README's "Try it in 60 seconds" path: an install from git (no Node) must bring the web app,
and a first run must say plainly when something is missing.

Written by a first-run audit that installed a clean clone the way the README says (pip, pipx and
uv tool install from git) and started ``ordnung demo``.
"""

from __future__ import annotations

import importlib.metadata
import json
import re
import shutil
import socket
import subprocess
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version
from typer.testing import CliRunner

from ordnung import cli, config, doctor
from ordnung.api import app as app_module
from ordnung.cli import app
from test_api_support import api_for, fake_web_dist

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("needs a git checkout of Ordnung")
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)


@pytest.fixture
def no_web_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Ordnung as ``pipx install git+…`` leaves it: a package folder with no ``web/dist`` (and no
    source checkout around it)."""
    missing = tmp_path / "site-packages" / "ordnung" / "web" / "dist"
    missing.parent.parent.mkdir(parents=True)
    for module in (config, doctor, app_module):
        monkeypatch.setattr(module, "web_dist_dir", lambda: missing)
    monkeypatch.setattr(cli, "web_dist_dir", lambda: missing, raising=False)
    return missing


# --------------------------------------------------------------------------------------------------
# the built web app in a git install
# --------------------------------------------------------------------------------------------------


def test_the_web_build_is_not_git_ignored() -> None:
    ignored = _git("check-ignore", "--no-index", "src/ordnung/web/dist/index.html")
    assert ignored.returncode == 1, f"ignored by: {ignored.stdout.strip()}"


# --------------------------------------------------------------------------------------------------
# what a new user is told when the web app is missing
# --------------------------------------------------------------------------------------------------


def test_serve_says_when_the_web_app_is_missing(
    data_dir: Path, no_web_app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a web build `ordnung demo`/`ordnung serve` used to look healthy (only the link panel)
    and the link led to a 503 page; now the terminal says so."""
    import uvicorn

    monkeypatch.setattr(cli, "_create_app", lambda context, token, demo: object())
    monkeypatch.setattr(uvicorn.Server, "run", lambda self: None)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    result = runner.invoke(app, ["serve", "--no-browser", "--port", str(port), "--data-dir", str(data_dir)])
    assert result.exit_code == 0, result.output
    assert "web app" in result.output.lower(), result.output


def test_serve_opens_no_browser_on_the_missing_web_app(
    data_dir: Path, no_web_app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The browser could only show the "web app is missing" page; the terminal already says it."""
    import uvicorn

    opened: list[object] = []
    monkeypatch.setattr(cli, "_create_app", lambda context, token, demo: object())
    monkeypatch.setattr(cli, "_open_browser_when_ready", lambda folder, info: opened.append(info))
    monkeypatch.setattr(uvicorn.Server, "run", lambda self: None)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    result = runner.invoke(app, ["serve", "--port", str(port), "--data-dir", str(data_dir)])
    assert result.exit_code == 0, result.output
    assert "Reinstall Ordnung" in result.output and opened == []


def test_doctor_suggests_make_build_web_only_in_a_source_checkout(no_web_app: Path) -> None:
    """A pipx/uv user has no checkout, no Makefile and no web/ folder: `make build-web` can't be
    followed there."""
    check = doctor.web_ui_check()
    assert check.status != "ok"
    checkout = no_web_app.parents[3]
    if "make build-web" in (check.fix or ""):
        assert (checkout / "Makefile").is_file(), f"advice for a missing checkout: {check.fix}"


# --------------------------------------------------------------------------------------------------
# the web app after an upgrade
# --------------------------------------------------------------------------------------------------


async def test_a_missing_asset_is_a_404_not_the_app_page(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tab left open across `pipx upgrade` lazy-loads an old page chunk; answered with index.html
    (200, text/html) Chromium fails with 'Expected a JavaScript-or-Wasm module script but the server
    responded with a MIME type of "text/html"'."""
    dist = fake_web_dist(tmp_path)
    monkeypatch.setattr(app_module, "web_dist_dir", lambda: dist)
    async with api_for(data_dir) as api:
        stale = await api.client.get("/assets/AskPage-0ldHa5h.js")
        current = await api.client.get("/assets/index-abc.js")
    assert current.status_code == 200
    assert stale.status_code == 404, stale.headers.get("content-type")


# --------------------------------------------------------------------------------------------------
# --help
# --------------------------------------------------------------------------------------------------


def test_help_shows_no_rest_markup() -> None:
    """Command docstrings are the --help text: reST ``literals`` were printed verbatim."""
    commands = ["serve", "add", "brief", "ask", "demo", "doctor", "eval", "mcp", "openapi"]
    for args in [["--help"], *([command, "--help"] for command in commands)]:
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        assert "``" not in result.output, f"ordnung {' '.join(args)}"


# --------------------------------------------------------------------------------------------------
# dependency floors and pinned versions
# --------------------------------------------------------------------------------------------------


def test_dependency_floors_install_a_working_app() -> None:
    """Below each of these floors the app was broken (CI's lowest-direct job installs the floors):
    typer crashed at start, fpdf2 broke the demo's replay, icalendar 6.0 made the .ics a 500 and
    holidays dropped the Fronleichnam warning."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    floors = dict(
        re.findall(r"^([\w.-]+)(?:\[[\w,]+\])?>=([\d.]+)", "\n".join(project["dependencies"]), re.M)
    )
    for name, needed in {"typer": "0.19", "fpdf2": "2.8.5", "icalendar": "6.1", "holidays": "0.66"}.items():
        assert Version(floors[name]) >= Version(needed), name


def test_the_server_floors_are_ones_the_lowest_job_can_install() -> None:
    """Lifecycle review: pyproject said uvicorn>=0.30 and sse-starlette>=2.1, but mcp needs uvicorn
    0.31.1 and sse-starlette 3.0, so CI's lowest-direct job installed those and the phone listener's test
    that claimed to run on uvicorn 0.30 never did. The floors are at least what mcp requires, and the
    test names the floor it runs on."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    floors = dict(
        re.findall(r"^([\w.-]+)(?:\[[\w,]+\])?>=([\d.]+)", "\n".join(project["dependencies"]), re.M)
    )
    needed: dict[str, Version] = {}
    for line in importlib.metadata.requires("mcp") or []:
        requirement = Requirement(line)
        if requirement.name in ("uvicorn", "sse-starlette") and (
            requirement.marker is None or requirement.marker.evaluate()
        ):
            needed[requirement.name] = max(
                Version(spec.version) for spec in requirement.specifier if spec.operator == ">="
            )
    assert set(needed) == {"uvicorn", "sse-starlette"}
    for name, version in needed.items():
        assert Version(floors[name]) >= version, (name, floors[name], version)
    listener = (ROOT / "tests" / "test_phone_listener.py").read_text(encoding="utf-8")
    assert f"uvicorn's floor ({floors['uvicorn']}," in listener


def test_ci_installs_the_samples_library_versions() -> None:
    """The samples regenerate byte for byte only with their manifest's libraries: CI installs with
    ``-c constraints.txt``, which pins them."""
    manifest = json.loads((ROOT / "src/ordnung/demo/samples/manifest.json").read_text(encoding="utf-8"))
    constraints = (ROOT / "constraints.txt").read_text(encoding="utf-8")
    pins = dict(re.findall(r"^([\w.-]+)==([^\s;]+)", constraints, re.M))
    for name in ("fpdf2", "fonttools", "pillow", "pypdfium2"):
        assert pins[name] == manifest["generator"]["environment"][name], name
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert workflow.count('uv pip install -e ".[dev]" -c constraints.txt') >= 2
