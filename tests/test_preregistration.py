"""The pre-registration of the final run holds (``evals/preregistration/final-0.4.0.json`` and ``.md``).

This file is frozen from the code freeze on, with ``tests/test_present_final.py`` and ``tests/test_final_gates.py``:
the pre-registration's ``code`` map names all three. Each part skips until what it checks exists — the
pre-registration, the deviations file, the phase-2 record, a final results file — and then holds for good:

* every required field is there;
* every file of the ``files`` map, and the power and calibration files, are byte for byte what was registered;
* the ``code`` map is the code at HEAD (this test among it);
* every path changed since the freeze is one the pre-registration allows, and none it froze changed;
* every final results file passes the analysis' check of the frozen inputs;
* every decision code has a template and every placeholder a source (``evals.present.final.check_templates``);
* the pledge, and every rule text, are word for word in the ``.md`` and the ``.json``;
* ``evals/present/**`` is the posted phase-2 tree, or a ``code_hash_changed`` deviation names each differing path;
* the deviations file is well formed (``scripts.prereg_hashes --deviations``);
* (slow) the planned day's build regenerates to the registered manifest.

The checks themselves are :mod:`scripts.prereg_hashes`'s, also on the code map."""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from evals import analysis
from scripts import prereg_hashes

ROOT = Path(__file__).resolve().parents[1]
PREREG = ROOT / "evals" / "preregistration" / "final-0.4.0.json"
PREREG_MD = PREREG.with_suffix(".md")
DEVIATIONS = ROOT / "evals" / "preregistration" / "deviations-0.4.0.json"
PHASE2 = ROOT / "evals" / "preregistration" / "phase2-0.4.0.json"
FINAL_SPLITS = ("holdout4", "newkinds")
FROZEN_TESTS = ("tests/test_preregistration.py", "tests/test_present_final.py", "tests/test_final_gates.py")


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def prereg() -> dict[str, Any]:
    if not PREREG.is_file():
        pytest.skip("no pre-registration yet")
    data = _json(PREREG)
    assert isinstance(data, dict)
    return data


def test_every_required_field_is_there(prereg: dict[str, Any]) -> None:
    assert prereg_hashes.required_problems(prereg) == []


def test_every_registered_file_is_byte_for_byte_the_same(prereg: dict[str, Any]) -> None:
    assert prereg["files"], "the files map is empty"
    assert prereg_hashes.files_problems(prereg, ROOT) == []


def test_the_code_map_is_the_code_at_head(prereg: dict[str, Any]) -> None:
    code = prereg["code"]
    for path in FROZEN_TESTS:
        assert path in code, f"the code map leaves out {path}"
    assert code == prereg_hashes.code_section(ROOT)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False)


def test_only_allowed_paths_changed_since_the_freeze(prereg: dict[str, Any]) -> None:
    freeze = str(prereg["registered"]["freeze_sha"])
    if shutil.which("git") is None or _git("cat-file", "-e", f"{freeze}^{{commit}}").returncode != 0:
        pytest.skip("the freeze commit is not in this clone (a shallow checkout)")
    changed = prereg_hashes.changed_since(ROOT, freeze)
    assert prereg_hashes.path_problems(changed, prereg["frozen"]) == []


def _final_results() -> list[Path]:
    found = []
    for path in sorted((ROOT / "evals" / "results").glob("*.json")):
        try:
            meta = _json(path).get("meta") or {}
        except (ValueError, AttributeError):
            continue
        if meta.get("split") in FINAL_SPLITS and meta.get("backend") == "live":
            found.append(path)
    return found


def test_every_final_results_file_passes_the_frozen_input_check(prereg: dict[str, Any]) -> None:
    files = _final_results()
    if not files:
        pytest.skip("no final results file is published yet (checkpoints stay in evals/results/pending/)")
    assert hasattr(analysis, "check_frozen"), "the analysis has no check of the frozen inputs"
    analysis.final_from_files(PREREG, files)  # check_frozen runs first; an unexcused mismatch raises


def test_every_decision_code_has_a_template_and_every_placeholder_a_source(prereg: dict[str, Any]) -> None:
    try:
        final = importlib.import_module("evals.present.final")
    except ModuleNotFoundError:
        pytest.fail("evals/present/final.py is missing: the sentences have no renderer")
    assert prereg["sentences"] == final.load_templates(), (
        "the registered sentences are not final_templates.json"
    )
    assert final.check_templates(prereg["sentences"]) == []


def test_the_pledge_and_the_rule_texts_are_word_for_word_in_the_md_and_the_json(
    prereg: dict[str, Any],
) -> None:
    assert PREREG_MD.is_file(), "the pre-registration has no .md for people"
    assert prereg_hashes.verbatim_problems(prereg, PREREG_MD.read_text(encoding="utf-8")) == []


def test_the_presenter_is_the_posted_phase2_tree() -> None:
    if not PHASE2.is_file():
        pytest.skip("phase 2 is not posted yet")
    deviations = _json(DEVIATIONS) if DEVIATIONS.is_file() else []
    assert prereg_hashes.phase2_problems(_json(PHASE2), ROOT, deviations) == []


def test_the_deviations_file_is_well_formed(prereg: dict[str, Any]) -> None:
    if not DEVIATIONS.is_file():
        pytest.skip("no deviations file yet")
    kinds = prereg_hashes.kinds_table(prereg["deviation_kinds"])
    assert prereg_hashes.deviation_problems(_json(DEVIATIONS), kinds) == []
    assert prereg_hashes.analysis_table_problems(kinds) == []


@pytest.mark.slow
def test_the_planned_day_s_build_regenerates_the_registered_manifest(
    prereg: dict[str, Any], tmp_path: Path
) -> None:
    """The committed manifest is the registered one; a build of the planned day gives the same letters and labels,
    and the same bytes where the generator's libraries are the registered ones (the manifest names their versions)."""
    data = prereg["data"]
    committed = ROOT / "evals" / "dataset" / "manifest.json"
    assert hashlib.sha256(committed.read_bytes()).hexdigest() == data["manifest_sha256"]
    command = [sys.executable, "-m", "evals.generate", "--out", str(tmp_path / "dataset"), "--quiet"]
    if data.get("final_day"):
        command += ["--final-day", str(data["final_day"])]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True)
    built_path = tmp_path / "dataset" / "manifest.json"
    built, registered = _json(built_path), _json(committed)
    differing = sorted(
        k
        for k in built.keys() | registered.keys()
        if k != "environment" and built.get(k) != registered.get(k)
    )
    assert not differing, (
        f"the build differs from the registered manifest in {differing}"
    )  # keys only, no letter text
    if built.get("environment") == registered.get("environment"):
        assert hashlib.sha256(built_path.read_bytes()).hexdigest() == data["manifest_sha256"]
