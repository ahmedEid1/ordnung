"""The pre-registration of the final run holds (``evals/preregistration/final-0.4.0.json`` and ``.md``).

From the code freeze to the publication of the final run, this file was frozen with ``tests/test_present_final.py``
and ``tests/test_final_gates.py`` (the pre-registration's ``code`` map names all three); CI ran it on every pull
request and every push to main in between, and at the publish commit it passes whole. Each part skips until what it
checks exists — the pre-registration, the deviations file, the phase-2 record, a final results file — and then
holds:

* every required field is there;
* every file of the ``files`` map, and the power and calibration files, are byte for byte what was registered;
* the ``code`` map is the code at HEAD (this test among it);
* every path changed since the freeze is one the pre-registration allows, and none it froze changed;
* in these two, B's runner-defect rule is the one exception: a path a ``code_hash_changed`` deviation of step
  ``runner-fix`` names as ``<path> sha256 <sha256 at HEAD>``, once the git history shows it was recorded at the time
  (a clone without the freeze commit excuses nothing), and never an input of the code digest or the fingerprints, nor
  ``evals/present/final.py`` or ``final_templates.json`` (``scripts.prereg_hashes.excused_at``);
* the pre-registration and the phase-2 record are written once after the freeze, never edited;
* every final results file passes the analysis' check of the frozen inputs;
* the published final analysis read the registered pre-registration, and is what every live final results file
  gives rendered again; the held-out Ask file of runs holds every live run of the set;
* every decision code has a template and every placeholder a source (``evals.present.final.check_templates``);
* the pledge, and every rule text, are word for word in the ``.md`` and the ``.json``;
* ``evals/present/**`` is the posted phase-2 tree, or a ``code_hash_changed`` deviation names each differing path;
* the deviations file is well formed and each entry was recorded at the time, by the git history
  (``scripts.prereg_hashes --deviations --history``);
* (slow) the planned day's build regenerates to the registered manifest.

After publication, the publish commit holds them. The pre-registration plans changes after the publish commit (a
scorer bug fixed in ``-rescored`` files, a label error or the owner's checks sent through the blind review), and the
code goes on, so the checks that hold HEAD to the freeze cannot hold at HEAD for good. Once
``evals/preregistration/published-0.4.0.json`` names the publish commit and the amendment on the pre-registration
issue that says so (``scripts.prereg_published``), they verify that commit, read from git, and skip at HEAD: the
``files`` map, the code map, the paths changed since the freeze, the final results' frozen-input check and their
analysis rendered again, the held-out Ask file of runs, the phase-2 tree and the planned day's build. At HEAD, from
then on:

* the record names the commit on HEAD's first-parent line (main's own history) that first published a final analysis
  of the registered pre-registration (its first parent holds none), a comment on the pre-registration issue, and the
  sha256 of this file, ``scripts/prereg_published.py`` and ``scripts/prereg_hashes.py``, which stay those; a change to
  the record's commit or to those files names a new amendment;
* (slow) that commit's own copy of this file passes there, every test and none skipped, in a temporary worktree of it
  with its own first-party code first on ``sys.path`` (the interpreter and the libraries are this checkout's);
* the pre-registration, its ``.md``, the phase-2 record and the power and calibration files are byte for byte the
  publish commit's, and so is every results file the final run added (a re-score is a new ``-rescored`` file), but
  the final analysis: it is rendered again when a label error or a scorer bug is recorded, and then only its list of
  deviations, the deviations file's sha256 and count and, for a label error, the label-corrected sensitivity change;
* the stress run carries the registered fingerprints (its replay compares numbers, not the replaying code);
* the deviations file starts with the publish commit's entries, unchanged; only label errors and scorer bugs are added;
* for every 0.4.x release, the README's generated block is the one published, word for word, but for its count of the
  deviations recorded at the time, which follows the file (the pledge);
* the required fields, the templates, the pledge and the rule texts, the files written once and the deviations (well
  formed, recorded at the time) hold as before.

The checks that read the git history skip in a clone without the freeze commit only while no final result is
published; from then on such a clone fails them (CI's clone must hold the history).

The checks themselves are :mod:`scripts.prereg_hashes`'s (on the code map) and, after publication,
:mod:`scripts.prereg_published`'s."""

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
from scripts import prereg_hashes, prereg_published

ROOT = Path(__file__).resolve().parents[1]
PREREG = ROOT / "evals" / "preregistration" / "final-0.4.0.json"
PREREG_MD = PREREG.with_suffix(".md")
DEVIATIONS = ROOT / "evals" / "preregistration" / "deviations-0.4.0.json"
PHASE2 = ROOT / "evals" / "preregistration" / "phase2-0.4.0.json"
FINAL_SPLITS = ("holdout4", "newkinds")
FROZEN_TESTS = ("tests/test_preregistration.py", "tests/test_present_final.py", "tests/test_final_gates.py")
#: Committed after the publish commit, never in it: it names that commit and the amendment on the issue.
PUBLISHED = ROOT / prereg_published.RECORD
#: The test that runs the publish commit's own copy of this file at that commit.
AT_THE_PUBLISH_COMMIT = "test_the_publish_commit_s_own_copy_of_this_file_passes_there"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _until_published() -> None:
    """A check that holds HEAD to the freeze runs at HEAD until the publish record exists, then at that commit."""
    if PUBLISHED.is_file():
        pytest.skip(
            f"after publication: {prereg_published.RECORD} names the publish commit, where this check holds "
            f"({AT_THE_PUBLISH_COMMIT} runs that commit's own copy of this file there)"
        )


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
    _until_published()
    assert prereg["files"], "the files map is empty"
    assert prereg_hashes.files_problems(prereg, ROOT) == []


def _excused(prereg: dict[str, Any]) -> set[str]:
    """The paths B's runner-defect rule excuses: each named, with its sha256 at HEAD, by a ``runner-fix``
    ``code_hash_changed`` deviation of the committed deviations file that the history shows was recorded at the time
    (none while there is no such file, and none in a clone without the freeze commit)."""
    return prereg_hashes.excused_at(ROOT, prereg)


def test_the_code_map_is_the_code_at_head(prereg: dict[str, Any]) -> None:
    _until_published()
    code = prereg["code"]
    for path in FROZEN_TESTS:
        assert path in code, f"the code map leaves out {path}"
    assert prereg_hashes.code_problems(code, ROOT, _excused(prereg)) == []


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False)


def _freeze_in_history(prereg: dict[str, Any]) -> str:
    """The freeze sha, once this clone holds it; until a final result is published a clone without it skips."""
    freeze = str(prereg["registered"]["freeze_sha"])
    if shutil.which("git") is None or _git("cat-file", "-e", f"{freeze}^{{commit}}").returncode != 0:
        if _final_results() or _published_final_analyses():
            pytest.fail("the freeze commit is not in this clone: the history checks need a full clone")
        pytest.skip("the freeze commit is not in this clone (a shallow checkout)")
    return freeze


def test_only_allowed_paths_changed_since_the_freeze(prereg: dict[str, Any]) -> None:
    _until_published()
    freeze = _freeze_in_history(prereg)
    changed = prereg_hashes.changed_since(ROOT, freeze)
    assert prereg_hashes.path_problems(changed, prereg["frozen"], _excused(prereg)) == []


def test_the_pre_registration_and_the_phase2_record_are_written_once(prereg: dict[str, Any]) -> None:
    """``final-0.4.0.json`` stays what was registered: neither it, its ``.md`` nor the posted phase-2 record is
    changed by a second commit after the freeze."""
    freeze = _freeze_in_history(prereg)
    assert prereg_hashes.write_once_problems(ROOT, freeze) == []


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
    _until_published()
    files = _final_results()
    if not files:
        pytest.skip("no final results file is published yet (checkpoints stay in evals/results/pending/)")
    assert hasattr(analysis, "check_frozen"), "the analysis has no check of the frozen inputs"
    analysis.final_from_files(PREREG, files)  # check_frozen runs first; an unexcused mismatch raises


def _published_final_analyses() -> list[Path]:
    found = []
    for path in sorted((ROOT / "evals" / "results").glob("*-final.json")):
        try:
            data = _json(path)
        except ValueError:
            continue
        meta = data.get("meta") if isinstance(data, dict) else None
        if (
            isinstance(meta, dict)
            and data.get("schema") == analysis.ANALYSIS_SCHEMA
            and meta.get("kind") == "final"
        ):
            found.append(path)
    return found


def test_the_published_final_analysis_is_the_registered_one_over_every_final_read(
    prereg: dict[str, Any],
) -> None:
    """The final analysis published read ``final-0.4.0.json`` as registered (its path and sha256), took every live
    final results file as an input, and is what they give rendered again, byte for byte."""
    _until_published()
    published = _published_final_analyses()
    if not published:
        pytest.skip("no final analysis is published yet")
    files = _final_results()
    registered = {
        "file": PREREG.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(PREREG.read_bytes()).hexdigest(),
    }
    for path in published:
        meta = _json(path)["meta"]
        assert meta["prereg"] == registered, f"{path.name} did not read the registered pre-registration"
        given = sorted(str(item["file"]) for item in meta["inputs"] if item.get("role") != "pooled")
        assert given == sorted(file.name for file in files), (
            f"{path.name} leaves out a live final results file"
        )
        rendered = analysis.render(analysis.final_from_files(PREREG, files, date=str(meta["date"])))
        assert rendered == path.read_text(encoding="utf-8"), f"{path.name} is not what the final reads give"


def test_the_held_out_ask_file_of_runs_holds_every_run_recorded() -> None:
    _until_published()
    from evals.ask import heldout
    from evals.ask.run import DEFAULT_MODEL

    results = ROOT / "evals" / "results"
    files = sorted(results.glob(heldout.final_name("*", DEFAULT_MODEL)))
    recorded = heldout.recorded_runs(results, DEFAULT_MODEL)
    if not files:
        if recorded:
            pytest.fail("held-out Ask runs are published without their file of runs")
        pytest.skip("the held-out Ask set's file of runs is not published yet")
    for path in files:
        inputs = {str(item["file"]) for item in _json(path)["meta"]["inputs"]}
        missing = sorted(run.name for run in recorded if run.name not in inputs)
        assert not missing, f"{path.name} leaves out recorded runs: {', '.join(missing)}"


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
    _until_published()
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


def test_every_deviation_was_recorded_at_the_time(prereg: dict[str, Any]) -> None:
    """By the history: each entry's checkpoint commit holds it, it was written no later, before the results were
    published (a label error or a scorer bug aside), on the registered issue; the file only ever grew."""
    if not DEVIATIONS.is_file():
        pytest.skip("no deviations file yet")
    freeze = _freeze_in_history(prereg)
    issue = prereg["registered"].get("issue_url")
    assert prereg_hashes.history_problems(ROOT, _json(DEVIATIONS), freeze=freeze, issue=issue) == []


@pytest.mark.slow
def test_the_planned_day_s_build_regenerates_the_registered_manifest(
    prereg: dict[str, Any], tmp_path: Path
) -> None:
    """The committed manifest is the registered one; a build of the planned day gives the same letters and labels,
    and the same bytes where the generator's libraries are the registered ones (the manifest names their versions)."""
    _until_published()
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


# --------------------------------------------------------------------------------------------------
# After publication: the publish commit holds the checks above, and what it published stays
# --------------------------------------------------------------------------------------------------


def _record(prereg: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """The publish record, checked: a commit on HEAD's first-parent line (main's own history) after the freeze, a
    comment on the pre-registration issue the first checkpoint commit names, and the sha256 of the files that check
    after publication. Until it is committed, this skips."""
    record = prereg_published.load_record(ROOT)
    if record is None:
        pytest.skip(
            f"not published yet: no {prereg_published.RECORD}, so the checks above hold HEAD to the freeze"
        )
    freeze = _freeze_in_history(prereg)
    issue = prereg_hashes.bound_issue(ROOT, freeze)
    assert prereg_published.record_problems(record, ROOT, freeze=freeze, issue=issue) == []
    return record, freeze


def _registered() -> dict[str, str]:
    return {
        "file": PREREG.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(PREREG.read_bytes()).hexdigest(),
    }


def test_the_publish_record_names_the_commit_that_published_the_final_run(prereg: dict[str, Any]) -> None:
    """Only the commit on main that first published a final analysis of the registered pre-registration can end the
    freeze: the first one on HEAD's first-parent line after the freeze that holds one. A commit before publication
    holds none; a later one, even one that adds the analysis back after a removal, is not the first."""
    record, freeze = _record(prereg)
    pattern = prereg["sentences"]["files"]["final"]
    assert (
        prereg_published.first_publication_problems(
            ROOT, record["commit"], pattern, _registered(), freeze=freeze
        )
        == []
    )


def test_the_files_that_check_after_publication_are_the_ones_the_record_names(prereg: dict[str, Any]) -> None:
    """Once the checks above skip at HEAD, nothing else holds this file and the scripts it runs: the record names
    their sha256 as merged (and the amendment does), and a change to them, or to the record's commit, names a new
    amendment on the pre-registration issue."""
    record, _ = _record(prereg)
    assert prereg_published.checked_by_problems(record, ROOT) == []
    assert prereg_published.record_history_problems(ROOT) == []


@pytest.mark.slow
def test_the_publish_commit_s_own_copy_of_this_file_passes_there(
    prereg: dict[str, Any], tmp_path: Path
) -> None:
    """Every check above that holds HEAD to the freeze, at the publish commit: its own copy of this file, every test
    and the slow one too, none skipped, in a temporary worktree of that commit, with that commit's code (``src``,
    ``evals``, ``scripts``) first on ``sys.path``. The worktree is removed afterwards, whatever happened."""
    record, _ = _record(prereg)
    outcome = prereg_published.run_frozen_tests(ROOT, record["commit"], tmp_path)
    print(f"{record['commit']}: {len(outcome.tests)} tests in {outcome.seconds:.0f} s")
    problems = prereg_published.outcome_problems(outcome)
    assert not problems, "\n".join(problems)


def test_the_registered_files_are_the_publish_commit_s(prereg: dict[str, Any]) -> None:
    record, _ = _record(prereg)
    kept = [*prereg_hashes.WRITE_ONCE, *(str(prereg[name]["file"]) for name in prereg_hashes.NAMED_FILES)]
    assert prereg_published.unchanged_problems(ROOT, record["commit"], kept) == []


def test_the_final_run_s_results_files_are_the_publish_commit_s(prereg: dict[str, Any]) -> None:
    """Every results file the final run added (under evals/results, but the checkpoints of ``pending/``, and
    evals/retakes) stays byte for byte: a scorer bug is fixed after publication in new ``-rescored`` files, never in
    the primary file. The final analysis reads the deviations file, so a label error or a scorer bug recorded after
    publication renders it again: then only its list of deviations, the file's sha256 and count and, for a label
    error, the label-corrected sensitivity change, and its results stay what was published."""
    record, freeze = _record(prereg)
    added = prereg_published.added_results(ROOT, freeze, record["commit"])
    assert added, "the publish commit added no results file"
    finals = set(
        prereg_published.final_analyses_at(
            ROOT, record["commit"], prereg["sentences"]["files"]["final"], _registered()
        )
    )
    assert finals and finals <= set(added), "the final run added no final analysis"
    assert (
        prereg_published.unchanged_problems(ROOT, record["commit"], [p for p in added if p not in finals])
        == []
    )
    for path in sorted(finals):
        published = prereg_published.at_commit(ROOT, record["commit"], path)
        assert published is not None and (ROOT / path).is_file(), f"{path}: removed since the publish commit"
        assert prereg_published.final_analysis_problems(path, (ROOT / path).read_bytes(), published) == []


def test_the_stress_run_was_recorded_with_the_registered_code(prereg: dict[str, Any]) -> None:
    """The stress replay (``make eval-reproduce``) compares the numbers, not the fingerprints of the code that
    replays, which every later change to the code moves: the fingerprints the stress run recorded are held to the
    registered ones here (or to a runner fix's, which its ``code_hash_changed`` deviation names)."""
    record, freeze = _record(prereg)
    stress = []
    for path in prereg_published.added_results(ROOT, freeze, record["commit"]):
        try:
            doc = _json(ROOT / path)
        except ValueError:
            continue
        if isinstance(doc, dict) and str(doc.get("schema", "")).startswith("ordnung-eval-stress/"):
            stress.append((path, doc))
    if not stress:
        pytest.skip("the final run published no stress results file")
    deviations = _json(DEVIATIONS) if DEVIATIONS.is_file() else []
    for path, doc in stress:
        found = prereg_published.stress_fingerprint_problems(
            doc, prereg["frozen"]["fingerprints"], deviations
        )
        assert found == [], f"{path}: {found}"


def test_the_deviations_file_only_grows_after_publication(prereg: dict[str, Any]) -> None:
    """The publish commit's entries stay first and unchanged, and only label errors and scorer bugs are added; at
    every commit after the publish commit the file is there, and an entry added later stays as it was recorded (its
    ``checkpoint_sha`` filled in once), so removing the file and writing it again rewrites nothing."""
    record, _ = _record(prereg)
    published = prereg_published.at_commit(ROOT, record["commit"], prereg_hashes.DEVIATIONS_PATH)
    assert published is not None, "the publish commit has no deviations file"
    assert prereg_published.deviations_kept_problems(_json(DEVIATIONS), json.loads(published)) == []
    assert prereg_published.deviations_history_problems(ROOT, record["commit"]) == []


def test_the_readme_keeps_the_published_block_for_every_0_4_x_release(prereg: dict[str, Any]) -> None:
    """The pledge: "The generated block, including its 'where it falls short' line, stays in the README for every
    0.4.x release." Word for word the publish commit's, but for the count of deviations recorded at the time, which
    grows with the deviations file when a label error or a scorer bug is recorded after publication."""
    record, _ = _record(prereg)
    version = prereg_published.version(ROOT)
    assert version is not None, (
        "the package's version cannot be read (src/ordnung/__init__.py's __version__, or pyproject.toml's "
        "[project] version): the pledge holds the block for every 0.4.x release, so the check must know which"
    )
    if not version.startswith("0.4."):
        pytest.skip(f"the pledge holds the block for every 0.4.x release; this is {version}")
    published = prereg_published.at_commit(ROOT, record["commit"], "README.md")
    assert published is not None, "the publish commit has no README.md"
    sentences = prereg["sentences"]
    assert (
        prereg_published.readme_problems(
            (ROOT / "README.md").read_text(encoding="utf-8"),
            published.decode("utf-8"),
            template=sentences["templates"]["head.deviations"]["text"],
            deviations_file=sentences["files"]["deviations"],
            deviations=len(_json(DEVIATIONS)),
        )
        == []
    )
