"""The pre-registration's tools, on synthetic inputs: the hashes and checks (``scripts/prereg_hashes.py``), the power
simulation (``scripts/eval_power.py``), the owner's samplers and Cohen's κ (``scripts/owner_label_sample.py``,
``evals/ask/owner.py``) and the calibration on the held-out splits (``scripts/prereg_calibration.py``).

Nothing here reads a letter's or a question's text, and nothing calls a model."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from evals import analysis, conditions
from evals.ask import owner
from evals.records import CONDITIONS
from scripts import eval_power, owner_label_sample, prereg_calibration, prereg_hashes

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
COMMENT = "https://github.com/owner/repo/issues/7#issuecomment-123456"
BASELINES = ("llm_only", "llm_rules_text", "llm_rules_tool")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _put(root: Path, path: str, data: bytes | str) -> Path:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    return target


# --------------------------------------------------------------------------------------------------
# prereg_hashes: the sections
# --------------------------------------------------------------------------------------------------


def test_the_code_map_holds_the_scoring_code_the_frozen_tests_and_the_prereg_tools() -> None:
    code = prereg_hashes.code_section(ROOT)
    for path in (
        "tests/test_preregistration.py",
        "tests/test_present_final.py",
        "tests/test_final_gates.py",
        "evals/present/final.py",
        "evals/present/final_templates.json",
        "evals/analysis.py",
        "evals/stats.py",
        "evals/metrics.py",
        "evals/records.py",
        "evals/ask/owner.py",
        "scripts/prereg_hashes.py",
        "scripts/eval_power.py",
        "scripts/prereg_calibration.py",
        "scripts/owner_label_sample.py",
    ):
        assert path in code, path
    for path, digest in code.items():
        file = ROOT / path
        assert digest == (_sha(file.read_bytes()) if file.is_file() else None), path


def test_the_files_map_hashes_every_final_data_file_and_nothing_else(tmp_path: Path) -> None:
    wanted = {
        "evals/dataset/manifest.json": "{}",
        "evals/dataset/holdout4/a.pdf": b"%PDF-1",
        "evals/dataset/holdout4/facts.json": "[]",
        "evals/dataset/newkinds/b.jpg": b"\xff\xd8",
        "evals/dataset/VERIFICATION.md": "# v",
        "evals/dataset/provenance/w1a/writer-log.sha256": "0",
        "evals/gen/final.py": "X = 1\n",
        "evals/ask/heldout/questions.json": "{}",
        "evals/perturb/templates.json": "{}",
        "evals/perturb/manifest.json": "{}",
    }
    for path, data in wanted.items():
        _put(tmp_path, path, data)
    for path in (
        "evals/dataset/holdout3/c.pdf",  # an earlier split: not new
        "evals/gen/__pycache__/final.cpython-311.pyc",
        "evals/dataset/holdout4/.hidden",
        "evals/results/INDEX.json",
    ):
        _put(tmp_path, path, b"x")
    files = prereg_hashes.files_section(tmp_path)
    assert files == {
        path: _sha(data.encode() if isinstance(data, str) else data) for path, data in sorted(wanted.items())
    }
    assert list(files) == sorted(files)


def test_the_frozen_section_holds_hashes_and_versions_never_a_prompt() -> None:
    frozen = prereg_hashes.frozen_section()
    assert frozen["model"] == "claude-sonnet-5"
    assert frozen["code_digest"] == conditions._code_digest("ordnung")
    assert frozen["fingerprints"] == {c: conditions.fingerprint(c, "claude-sonnet-5") for c in CONDITIONS}
    assert frozen["prompt_hashes"]["ordnung"] == {
        name: list(pair) for name, pair in conditions.ordnung_prompt_hashes().items()
    }
    assert set(frozen["prompt_hashes"]["baselines"]) == set(BASELINES)
    assert set(frozen["environment"]) == {"evals", "generator"}
    assert frozen["environment"]["evals"] == conditions.environment()
    locks = frozen["locks"]
    assert "evals/recorded/claude-sonnet-5/requests.lock.json" in locks
    assert "evals/recorded/ask/claude-sonnet-5/prompts.lock.json" in locks
    assert frozen["index_sha256"] == _sha((ROOT / "evals/results/INDEX.json").read_bytes())
    assert frozen["items_sha256"] == _sha((ROOT / "evals/results/items.csv").read_bytes())
    text = json.dumps(frozen)
    prompts = sorted((ROOT / "evals" / "prompts").glob("*.md")) + sorted(
        (ROOT / "src" / "ordnung" / "llm" / "prompts").glob("*.md")
    )
    assert prompts
    leaked = [
        path.name
        for path in prompts
        for line in path.read_text(encoding="utf-8").splitlines()
        if len(line.strip()) > 30 and line.strip() in text
    ]
    assert not leaked, f"prompt lines in the frozen section: {sorted(set(leaked))}"


def _manifest(entries: list[dict[str, Any]], conventions: list[Any] | None = None) -> dict[str, Any]:
    return {"name": "synthetic", "conventions": conventions or [], "entries": entries}


def _entry(
    ident: str,
    split: str,
    family: str,
    dates: list[str | None],
    *,
    photo_of: str | None = None,
    kind: str = "invoice",
    variant: str = "K",
) -> dict[str, Any]:
    return {
        "id": ident,
        "split": split,
        "family": family,
        "variant": variant,
        "file": f"{split}/{ident}.{'jpg' if photo_of else 'pdf'}",
        "photo": photo_of is not None,
        "source_id": photo_of,
        "truth": {"kind": kind, "items": [{"expected_due": d} for d in dates], "optional_items": []},
    }


def test_the_data_section_gives_the_build_its_hashes_and_each_final_split_s_composition(
    tmp_path: Path,
) -> None:
    entries = [
        _entry("h4-a1", "holdout4", "tax_assessment", ["2026-12-20", None]),
        _entry("h4-a1-photo", "holdout4", "tax_assessment", ["2026-12-20", None], photo_of="h4-a1"),
        _entry("h4-b1", "holdout4", "adversarial", ["ambiguous"], variant="L"),
        _entry("nk-c1", "newkinds", "court_payment_order", ["2026-12-30"], kind="court_payment_order"),
        _entry("nk-d1", "newkinds", "dismissal", ["2027-01-04", "2027-01-05"], kind="dismissal"),
        _entry("h3-x", "holdout3", "appointment", ["2026-10-01"]),
    ]
    manifest = _manifest(
        entries,
        [{"id": "c01", "disputed": False, "text": "t"}, {"id": "c02", "disputed": True, "text": "u"}],
    )
    _put(tmp_path, "evals/dataset/manifest.json", json.dumps(manifest))
    _put(tmp_path, "evals/dataset/holdout4/h4-a1.pdf", b"%PDF")
    _put(tmp_path, "evals/gen/common.py", "A = 1\n")
    _put(tmp_path, "evals/generate.py", "B = 1\n")
    _put(tmp_path, "evals/verify_labels.py", "C = 1\n")
    data = prereg_hashes.data_section(tmp_path, final_day="2026-12-08")
    assert data["build_command"] == "python -m evals.generate --final-day 2026-12-08"
    assert data["final_day"] == "2026-12-08"
    assert data["manifest_sha256"] == _sha((tmp_path / "evals/dataset/manifest.json").read_bytes())
    assert data["files"] == 2 and len(data["tree_sha256"]) == 64
    assert data["conventions"] == [{"id": "c01", "disputed": False}, {"id": "c02", "disputed": True}]
    assert data["splits"]["holdout4"] == {
        "entries": 3,
        "pdfs": 2,
        "photos": 1,
        "adversarial": 1,
        "scored_items": 2,
        "families": {"adversarial": 1, "tax_assessment": 2},
        "kinds": ["invoice"],
        "variants": ["K", "L"],
    }
    assert data["splits"]["newkinds"]["kinds"] == ["court_payment_order", "dismissal"]
    assert data["splits"]["newkinds"]["scored_items"] == 3
    before = data["generator_tree_sha256"]
    _put(tmp_path, "evals/gen/common.py", "A = 2\n")
    assert prereg_hashes.data_section(tmp_path, final_day="2026-12-08")["generator_tree_sha256"] != before
    # the conventions as strings (before they had ids), and no final day: nothing invented
    _put(tmp_path, "evals/dataset/manifest.json", json.dumps(_manifest(entries, ["one", "two"])))
    plain = prereg_hashes.data_section(tmp_path)
    assert plain["build_command"] is None and plain["final_day"] is None
    assert plain["conventions"] == [{"id": None, "disputed": None}, {"id": None, "disputed": None}]


def test_check_names_every_difference_by_its_path_and_none_when_equal() -> None:
    computed = {
        "frozen": {"code_digest": "1" * 16, "fingerprints": {"ordnung": "f1", "llm_only": "f2"}},
        "code": {"evals/analysis.py": "aa", "tests/test_final_gates.py": None},
        "files": {"evals/dataset/manifest.json": "m1", "evals/dataset/holdout4/a.pdf": "p1"},
    }
    prereg = copy.deepcopy(computed)
    prereg["unrelated"] = {"budget": 150}
    prereg["frozen"]["cli_versions"] = ["2.1.0"]  # written by hand in B: not computed, not compared
    assert prereg_hashes.mismatches(computed, prereg) == []
    prereg["frozen"]["fingerprints"]["llm_only"] = "f9"
    prereg["code"]["tests/test_final_gates.py"] = "bb"
    del prereg["files"]["evals/dataset/holdout4/a.pdf"]
    prereg["files"]["evals/dataset/newkinds/z.pdf"] = "z1"
    found = prereg_hashes.mismatches(computed, prereg)
    assert found == [
        "code.tests/test_final_gates.py: differs",
        "files.evals/dataset/holdout4/a.pdf: not in the pre-registration",
        "files.evals/dataset/newkinds/z.pdf: in the pre-registration, not in this checkout",
        "frozen.fingerprints.llm_only: differs",
    ]
    del prereg["frozen"]
    assert "frozen: not in the pre-registration" in prereg_hashes.mismatches(computed, prereg)


def test_the_command_prints_a_section_and_checks_a_pre_registration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert prereg_hashes.main(["--section", "code"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == {"code": prereg_hashes.code_section(ROOT)}
    prereg = tmp_path / "final.json"
    prereg.write_text(json.dumps(printed), encoding="utf-8")
    assert prereg_hashes.main(["--section", "code", "--check", str(prereg)]) == 0
    assert "0 mismatches" in capsys.readouterr().out
    printed["code"]["evals/stats.py"] = "0" * 64
    prereg.write_text(json.dumps(printed), encoding="utf-8")
    assert prereg_hashes.main(["--section", "code", "--check", str(prereg)]) == 1
    out = capsys.readouterr().out
    assert "code.evals/stats.py: differs" in out and "1 mismatch" in out


# --------------------------------------------------------------------------------------------------
# prereg_hashes: the deviations file
# --------------------------------------------------------------------------------------------------

TABLE = {
    "retake": "include the retaken unit; the first attempt is published; first-attempt sensitivity",
    "code_hash_changed": "the runner-defect rule, or a presentation-only change listed per path",
    "budget_cut": "the step is not run or not completed, and is published as such",
}


def _deviation(**changes: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": "D001",
        "kind": "retake",
        "at": "2026-12-08T14:02:00Z",
        "step": "R2",
        "what": "unit holdout4-x r1 cut by the stop file",
        "evidence": ["evals/recorded/claude-sonnet-5/extract/ab.json sha256 0f0f"],
        "consequence": TABLE["retake"],
        "issue_comment_url": COMMENT,
        "created_at": "2026-12-08T14:03:10Z",
        "checkpoint_sha": SHA,
    }
    entry.update(changes)
    return entry


@pytest.mark.parametrize("shape", ["map", "nested", "list"])
def test_the_table_of_deviation_kinds_is_read_in_each_shape(shape: str) -> None:
    raw: Any = {
        "map": TABLE,
        "nested": {kind: {"consequence": text} for kind, text in TABLE.items()},
        "list": [{"kind": kind, "consequence": text} for kind, text in TABLE.items()],
    }[shape]
    assert prereg_hashes.kinds_table(raw) == TABLE


@pytest.mark.parametrize(
    "raw", [{"retake": 3}, {"retake": {"consequence": None}}, [{"kind": "retake"}], "retake", None]
)
def test_a_table_without_a_text_consequence_is_refused(raw: Any) -> None:
    with pytest.raises(ValueError):
        prereg_hashes.kinds_table(raw)


def test_a_deviation_recorded_at_the_time_is_well_formed() -> None:
    entries = [
        _deviation(),
        _deviation(id="D002", kind="budget_cut", step="R7", consequence=TABLE["budget_cut"]),
    ]
    entries[1]["applies_to"] = {"split": "holdout4", "repeat": 2}
    assert prereg_hashes.deviation_problems(entries, TABLE) == []
    assert prereg_hashes.deviation_problems([], TABLE) == []


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"issue_comment_url": None}, "D001: no comment on the pre-registration issue"),
        (
            {"issue_comment_url": "file:///tmp/issue.md#D001"},
            "D001: no comment on the pre-registration issue",
        ),
        ({"created_at": None}, "D001: no time it was recorded"),
        ({"created_at": "yesterday"}, "D001: no time it was recorded"),
        ({"checkpoint_sha": None}, "D001: no checkpoint commit"),
        ({"checkpoint_sha": "abc1234"}, "D001: no checkpoint commit"),
        ({"consequence": "exclude the read"}, "D001: its consequence is not the registered one for retake"),
        ({"kind": "label_fixed"}, "D001: kind 'label_fixed' is not in the pre-registration's table"),
        ({"step": ""}, "D001: no step"),
        ({"evidence": []}, "D001: no evidence"),
        ({"note": "x"}, "D001: unknown key note"),
        ({"what": "seen with " + "claude-" + "mini-1"}, "D001: names a model other than claude-sonnet-5"),
        ({"applies_to": ["holdout4"]}, "D001: applies_to is not an object"),
    ],
)
def test_a_deviation_that_was_not_recorded_at_the_time_is_refused(
    changes: dict[str, Any], problem: str
) -> None:
    found = prereg_hashes.deviation_problems([_deviation(**changes)], TABLE)
    assert any(line.startswith(problem) for line in found), found


def test_the_deviations_file_is_a_list_of_entries_with_one_id_each() -> None:
    assert prereg_hashes.deviation_problems({"D001": _deviation()}, TABLE) == [
        "the deviations file is not a JSON list"
    ]
    assert prereg_hashes.deviation_problems([_deviation(), _deviation()], TABLE) == [
        "D001: in the file twice"
    ]
    assert prereg_hashes.deviation_problems(["D001"], TABLE) == ["#1: not an entry with an id"]


def test_the_registered_table_must_be_the_one_the_analysis_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analysis, "DEVIATION_CONSEQUENCES", dict(TABLE), raising=False)
    assert prereg_hashes.analysis_table_problems(TABLE) == []
    other = dict(TABLE, retake="include")
    assert prereg_hashes.analysis_table_problems(other) == [
        "the pre-registration's table of deviation kinds differs from the analysis' in retake"
    ]
    monkeypatch.delattr(analysis, "DEVIATION_CONSEQUENCES")
    assert prereg_hashes.analysis_table_problems(other) == []


def test_the_command_checks_a_deviations_file_against_the_pre_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(analysis, "DEVIATION_CONSEQUENCES", dict(TABLE), raising=False)
    prereg = tmp_path / "final.json"
    prereg.write_text(json.dumps({"deviation_kinds": TABLE}), encoding="utf-8")
    deviations = tmp_path / "deviations.json"
    deviations.write_text(json.dumps([_deviation()]), encoding="utf-8")
    assert prereg_hashes.main(["--deviations", str(deviations), "--prereg", str(prereg)]) == 0
    assert "1 deviation(s), well formed" in capsys.readouterr().out
    deviations.write_text(json.dumps([_deviation(checkpoint_sha=None)]), encoding="utf-8")
    assert prereg_hashes.main(["--deviations", str(deviations), "--prereg", str(prereg)]) == 1
    out = capsys.readouterr().out
    assert "D001: no checkpoint commit" in out
    assert "unit holdout4-x" not in out  # ids and reasons only, never what was written


# --------------------------------------------------------------------------------------------------
# prereg_hashes: the phase-2 tree, the paths changed since the freeze, the required fields
# --------------------------------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    for path, text in {
        "evals/present/model.py": "M = 1\n",
        "evals/present/final.py": "F = 1\n",
        "evals/present/presentation.json": "{}\n",
        "docs/templates/evals.md": "# t\n",
        "web/e2e/eval-report.spec.ts": "test()\n",
        "evals/analysis.py": "A = 1\n",
        "README.md": "r\n",
    }.items():
        _put(root, path, text)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "one")
    return root


def test_the_phase2_record_hashes_the_presenter_at_the_posted_head(repo: Path) -> None:
    head = _git(repo, "rev-parse", "HEAD")
    record = prereg_hashes.phase2_record(repo)
    assert record["head"] == head
    assert record["files"] == {
        "docs/templates/evals.md": _sha(b"# t\n"),
        "evals/present/final.py": _sha(b"F = 1\n"),
        "evals/present/model.py": _sha(b"M = 1\n"),
        "web/e2e/eval-report.spec.ts": _sha(b"test()\n"),
    }
    assert len(record["tree_sha256"]) == 64
    assert record["exclude"] == ["evals/present/presentation.json"]  # the presenter's output, not its code
    # a later commit does not change what the posted head held
    _put(repo, "evals/present/model.py", "M = 2\n")
    _git(repo, "commit", "-q", "-am", "two")
    assert prereg_hashes.phase2_record(repo, head=head) == record
    assert prereg_hashes.phase2_record(repo)["tree_sha256"] != record["tree_sha256"]


def test_a_presenter_file_that_differs_from_the_posted_tree_needs_a_deviation_naming_it(repo: Path) -> None:
    record = prereg_hashes.phase2_record(repo)
    assert prereg_hashes.phase2_problems(record, repo, []) == []
    _put(repo, "evals/present/presentation.json", '{"final": 1}\n')  # rendered again from the results
    assert prereg_hashes.phase2_problems(record, repo, []) == []
    _put(repo, "evals/present/model.py", "M = 2\n")
    _put(repo, "evals/present/charts.py", "C = 1\n")
    (repo / "docs/templates/evals.md").unlink()
    assert prereg_hashes.phase2_problems(record, repo, []) == [
        "docs/templates/evals.md: removed since the posted phase-2 tree, and no code_hash_changed deviation names it",
        "evals/present/charts.py: not in the posted phase-2 tree, and no code_hash_changed deviation names it",
        "evals/present/model.py: differs from the posted phase-2 tree, and no code_hash_changed deviation names it",
    ]
    named = _deviation(
        kind="code_hash_changed",
        consequence=TABLE["code_hash_changed"],
        evidence=["evals/present/model.py", "evals/present/charts.py", "docs/templates/evals.md"],
    )
    assert prereg_hashes.phase2_problems(record, repo, [named]) == []
    # a retake that names the path is not the deviation the rule asks for
    assert len(prereg_hashes.phase2_problems(record, repo, [_deviation(evidence=named["evidence"])])) == 3


def test_the_command_writes_the_phase2_record_and_checks_the_checkout_against_it(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "phase2.json"
    assert prereg_hashes.main(["--phase2", str(out), "--write", "--root", str(repo)]) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == prereg_hashes.phase2_record(repo)
    capsys.readouterr()
    assert prereg_hashes.main(["--phase2", str(out), "--root", str(repo)]) == 0
    _put(repo, "web/e2e/eval-report.spec.ts", "test(2)\n")
    assert prereg_hashes.main(["--phase2", str(out), "--root", str(repo)]) == 1
    assert "web/e2e/eval-report.spec.ts: differs" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("path", "pattern", "hit"),
    [
        ("src/ordnung/llm/runtime.py", "src/ordnung/**", True),
        ("src/ordnung/x.py", "src/ordnung/**", True),
        ("evals/run.py", "evals/*.py", True),
        ("evals/ask/score.py", "evals/*.py", False),
        ("evals/recorded/claude-sonnet-5/extract/a.json", "evals/recorded/**", True),
        ("evals/preregistration/deviations-0.4.0.json", "evals/preregistration/deviations-0.4.0.json", True),
        ("tests/test_x.py", "tests/**", True),
        ("README.md", "tests/**", False),
        ("docs/evals-ask.md", "docs/evals*.md", True),
        ("docs/assets/eval-cost-dark.svg", "docs/assets/eval-*", True),
    ],
)
def test_a_path_matches_a_pattern_as_a_glob_with_double_star(path: str, pattern: str, hit: bool) -> None:
    assert prereg_hashes.matches(path, pattern) is hit


def test_a_path_changed_since_the_freeze_must_be_allowed_and_never_an_identical_one() -> None:
    frozen = {
        "identical_paths": ["src/ordnung/**", "evals/*.py", "tests/test_preregistration.py"],
        "allowed_after_freeze": ["evals/gen/**", "evals/dataset/**", "evals/preregistration/**"],
        "allowed_while_recording": ["evals/recorded/**", "evals/results/pending/**"],
        "allowed_at_publish": ["tests/**", {"path": "README.md", "note": "between the markers"}],
    }
    changed = [
        "evals/gen/final.py",
        "evals/recorded/claude-sonnet-5/extract/a.json",
        "README.md",
        "tests/test_eval_dataset.py",
        "tests/test_preregistration.py",
        "evals/analysis.py",
        "docs/SPEC.md",
    ]
    assert prereg_hashes.path_problems(changed, frozen) == [
        "evals/analysis.py: frozen since the freeze (identical_paths)",
        "tests/test_preregistration.py: frozen since the freeze (identical_paths)",
        "docs/SPEC.md: not in any list of paths allowed to change after the freeze",
    ]


def test_a_pre_registration_without_a_required_field_is_named() -> None:
    complete = {key: {} for key in prereg_hashes.REQUIRED}
    complete["registered"] = {key: "x" for key in prereg_hashes.REQUIRED_IN["registered"]}
    complete["frozen"] = {key: "x" for key in prereg_hashes.REQUIRED_IN["frozen"]}
    complete["data"] = {key: "x" for key in prereg_hashes.REQUIRED_IN["data"]}
    assert prereg_hashes.required_problems(complete) == []
    del complete["pledge"]
    del complete["frozen"]["served_models"]
    assert prereg_hashes.required_problems(complete) == [
        "pledge: missing",
        "frozen.served_models: missing",
    ]


def test_the_pledge_and_rule_texts_must_be_word_for_word_in_the_md() -> None:
    prereg = {
        "pledge": prereg_hashes.PLEDGE,
        "recording_day_rule": {"text": "Each unit keeps its day."},
        "contingency": {"text": "Complete reads stand."},
    }
    md = (
        "# Pre-registration\n\n> "
        + prereg_hashes.PLEDGE.replace(" README,", "\n> README,")
        + "\n\nEach unit keeps\nits day.\n\nComplete reads stand.\n"
    )
    assert prereg_hashes.verbatim_problems(prereg, md) == []
    assert prereg_hashes.verbatim_problems(prereg, md.replace("Complete reads", "All reads")) == [
        "contingency.text: not word for word in the .md"
    ]
    other = dict(prereg, pledge=prereg_hashes.PLEDGE.replace("14 days", "30 days"))
    assert prereg_hashes.verbatim_problems(other, md) == [
        "pledge: not the registered pledge",
        "pledge: not word for word in the .md",
    ]


def test_the_files_map_and_the_named_files_are_checked_byte_for_byte(tmp_path: Path) -> None:
    _put(tmp_path, "evals/dataset/manifest.json", "{}")
    _put(tmp_path, "evals/preregistration/power-0.4.0.json", "{}")
    prereg = {
        "files": {"evals/dataset/manifest.json": _sha(b"{}"), "evals/dataset/holdout4/gone.pdf": "0" * 64},
        "power": {"file": "evals/preregistration/power-0.4.0.json", "sha256": _sha(b"{}")},
        "calibration": {"file": "evals/preregistration/calibration-0.4.0.json", "sha256": "1" * 64},
    }
    assert prereg_hashes.files_problems(prereg, tmp_path) == [
        "evals/dataset/holdout4/gone.pdf: missing",
        "calibration: evals/preregistration/calibration-0.4.0.json missing",
    ]
    _put(tmp_path, "evals/dataset/manifest.json", "{ }")
    assert "evals/dataset/manifest.json: differs from the pre-registration (sha256)" in (
        prereg_hashes.files_problems(prereg, tmp_path)
    )


# --------------------------------------------------------------------------------------------------
# Synthetic results files
# --------------------------------------------------------------------------------------------------

DAY = "2027-03-10"


def _score_item(index: int, outcome: str) -> dict[str, Any]:
    return {
        "index": index,
        "outcome": {"right": "correct", "late": "wrong", "early": "wrong", "missed": "missed"}[outcome],
        "direction": outcome if outcome in ("late", "early") else None,
        "days_off": {"late": 2, "early": -2}.get(outcome),
        "predicted": None
        if outcome == "missed"
        else {"right": DAY, "late": "2027-03-12"}.get(outcome, "2027-03-08"),
        "pred_index": None if outcome == "missed" else index,
        "flagged": False,
        "confidence": None if outcome == "missed" else "high",
        "cause": None,
    }


def _run(
    split: str,
    read: int,
    letters: list[tuple[str, str, int]],
    outcome: Callable[[str, int, str, int], str],
) -> dict[str, Any]:
    entries = []
    for letter, cluster, count in letters:
        entries.append(
            {
                "id": f"{split}-{letter}",
                "family": "tax_assessment" if letter < "L5" else "appointment",
                "modality": "text",
                "conditions": {
                    condition: {
                        "prediction": {"items": [], "document_date": "2027-02-24"},
                        "score": {
                            "cluster": f"{split}-{cluster}",
                            "items": [
                                _score_item(i, outcome(condition, read, letter, i)) for i in range(count)
                            ],
                            "false_positives": 0,
                            "cost_usd": 0.01,
                            "latency_ms": 1000,
                            "calls": 1,
                            "kind_ok": True,
                            "tool_calls": {"compute_deadline": 1} if condition == "llm_rules_tool" else None,
                            "failed": None,
                            "error": None,
                        },
                    }
                    for condition in CONDITIONS
                },
            }
        )
    return {
        "schema": 1,
        "meta": {
            "date": f"2027-01-0{read}",
            "model": "claude-sonnet-5",
            "split": split,
            "repeat": read,
            "backend": "live",
            "commit": "abc1234",
            "conditions": list(CONDITIONS),
            "partial": False,
        },
        "entries": entries,
    }


LETTERS = [(f"L{i}", f"L{i}", 1 + i % 2) for i in range(1, 9)]


def _outcome(condition: str, read: int, letter: str, index: int) -> str:
    """Ordnung right but for L2 in read 2; the model alone wrong on most letters; the rules text on two; the agent
    on one, late."""
    number = int(letter[1:])
    if condition == "ordnung":
        return "late" if (letter, read) == ("L2", 2) else "right"
    if condition == "llm_only":
        return "right" if number in (1, 8) else ("missed" if index else "early")
    if condition == "llm_rules_text":
        return "early" if number in (3, 6) else "right"
    return "late" if number == 4 else "right"


def _reads(outcome: Callable[[str, int, str, int], str] = _outcome) -> list[analysis.Run]:
    return [analysis.load_run(_run("holdout4", r, LETTERS, outcome), name=f"r{r}") for r in (1, 2, 3)]


def _prereg() -> analysis.Prereg:
    data = {"analysis": analysis.default_prereg_analysis()}
    data["analysis"]["pool_with"] = []
    return analysis.parse_prereg(data)


# --------------------------------------------------------------------------------------------------
# eval_power
# --------------------------------------------------------------------------------------------------


def test_the_power_tool_decides_each_simulated_read_set_as_the_analysis_decides_the_final_run() -> None:
    """The same cluster totals, sign-flip test, Holm, bootstrap and rule: on synthetic reads the tool's decisions
    and p-values are the analysis' own."""
    prereg = _prereg()
    reads = _reads()
    newkinds = analysis.load_run(_run("newkinds", 1, LETTERS[:2], _outcome), name="nk")
    final = analysis.final_analysis(prereg, [*reads, newkinds])
    primary = final["primary"]
    for family in ("F1_accuracy", "F2_harm"):
        sums = {b: eval_power.cluster_sums(reads, b, family) for b in BASELINES}
        found = eval_power.family_decisions(sums, family, prereg)
        for b in BASELINES:
            row = primary["families"][family][f"ordnung-vs-{b}"]
            assert found[b]["p"] == row["signflip"]["p"]
            assert found[b]["holm"] == pytest.approx(row["holm"])
            if family == "F1_accuracy":
                key = "beats_llm_only" if b == "llm_only" else f"vs_{b}"
                assert found[b]["decision"] == primary["decisions"][key], b
            elif f"f2_vs_{b}" in primary["decisions"]:
                assert found[b]["decision"] == primary["decisions"][f"f2_vs_{b}"], b


def test_the_observed_rates_are_counted_from_the_first_reads() -> None:
    reads = _reads()
    pairs = eval_power.observed(reads[:1], "F1_accuracy")
    items = 12  # 8 letters, alternately 2 and 1 scored items
    assert pairs["llm_only"].reference == 1.0
    assert pairs["llm_only"].baseline == pytest.approx(3 / items)
    assert pairs["llm_only"].discordance == pytest.approx(9 / items)
    assert pairs["llm_rules_tool"].gap == pytest.approx(1 / items)
    harm = eval_power.observed(reads[:1], "F2_harm")
    assert harm["llm_only"].baseline == pytest.approx(3 / items)  # the missed second items
    assert harm["llm_only"].reference == 0.0
    assert eval_power.structure_from_runs(reads[:1]) == [2, 1, 2, 1, 2, 1, 2, 1]


def test_the_cluster_structure_comes_from_the_manifest_with_each_photo_in_its_letter_s_cluster() -> None:
    manifest = _manifest(
        [
            _entry("h4-a", "holdout4", "tax_assessment", ["2026-12-20", "2026-12-21"]),
            _entry("h4-a-photo", "holdout4", "tax_assessment", ["2026-12-20", "2026-12-21"], photo_of="h4-a"),
            _entry("h4-b", "holdout4", "appointment", ["2026-12-22", None]),
            _entry("h3-c", "holdout3", "appointment", ["2026-10-22"]),
        ]
    )
    assert eval_power.structure_from_manifest(manifest, "holdout4") == [4, 1]
    assert eval_power.structure_from_manifest(manifest, "newkinds") == []


SYNTHETIC = {
    "llm_only": eval_power.Pair(reference=0.95, baseline=0.75, discordance=0.26),
    "llm_rules_text": eval_power.Pair(reference=0.95, baseline=0.90, discordance=0.11),
    "llm_rules_tool": eval_power.Pair(reference=0.95, baseline=0.97, discordance=0.04),
}


def _power(**changes: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "structure": [2, 1, 1, 2] * 15,
        "pairs": SYNTHETIC,
        "family": "F1_accuracy",
        "baseline": "llm_rules_text",
        "gap": 0.05,
        "prereg": _prereg(),
        "reads": 3,
        "noise": "systematic",
        "reps": 40,
        "draws": 200,
        "resamples": 200,
        "seed": 20261029,
    }
    args.update(changes)
    result = eval_power.power(**args)
    assert result is not None
    return result


def test_a_power_run_is_deterministic() -> None:
    first = _power()
    assert _power() == first
    assert _power(seed=7) != first or _power(seed=8) != first
    assert set(first) == {"rejects", "detected"}
    assert 0 <= first["rejects"] <= 1 and 0 <= first["detected"] <= 1


def test_two_identical_conditions_are_told_apart_at_about_alpha() -> None:
    """No gap between the two conditions: the registered sign-flip test rejects at about its 5 % level."""
    pairs = {
        "llm_only": eval_power.Pair(reference=0.8, baseline=0.6, discordance=0.3),
        "llm_rules_text": eval_power.Pair(reference=0.8, baseline=0.8, discordance=0.3),
        "llm_rules_tool": eval_power.Pair(reference=0.8, baseline=0.82, discordance=0.06),
    }
    found = _power(pairs=pairs, gap=0.0, reps=400, draws=400, structure=[1, 2] * 40)
    assert 0.015 <= found["rejects"] <= 0.09, found
    assert found["detected"] <= found["rejects"]
    independent = _power(
        pairs=pairs, gap=0.0, reps=400, draws=400, structure=[1, 2] * 40, noise="independent"
    )
    assert 0.015 <= independent["rejects"] <= 0.09, independent


def test_power_grows_with_the_gap() -> None:
    small = _power(baseline="llm_only", gap=0.02, reps=60)
    large = _power(baseline="llm_only", gap=0.2, reps=60)
    assert large["detected"] >= 0.9 > small["detected"]


def test_an_impossible_gap_has_no_power() -> None:
    """Ordnung right 95 % of the time: no baseline can be right 10 points more often."""
    assert (
        eval_power.power(
            structure=[1] * 10,
            pairs=SYNTHETIC,
            family="F1_accuracy",
            baseline="llm_only",
            gap=-0.1,
            prereg=_prereg(),
            reads=3,
            noise="systematic",
            reps=5,
            draws=50,
            resamples=50,
            seed=1,
        )
        is None
    )


def test_the_power_file_gives_each_comparison_its_power_half_gap_power_and_mdd(tmp_path: Path) -> None:
    doc = eval_power.run(
        {"analysis": analysis.default_prereg_analysis()},
        _reads()[:1],
        structure=[2, 1] * 25,
        structure_source="synthetic",
        reps=12,
        draws=100,
        resamples=100,
        seed=20261029,
        step=0.05,
        max_gap=0.3,
        noises=("systematic",),
    )
    assert doc["schema"] == "ordnung-prereg-power/1"
    assert doc["settings"]["reps"] == 12 and doc["settings"]["target"] == 0.8
    assert doc["structure"] == {"source": "synthetic", "clusters": 50, "items": 75}
    for family in ("F1_accuracy", "F2_harm"):
        for b in BASELINES:
            row = doc["comparisons"][family][f"ordnung-vs-{b}"]
            assert 0 <= row["power"] <= 1 and 0 <= row["power_half_gap"] <= 1
            assert row["power"] == row["noise"]["systematic"]["observed"]
            assert row["detected_as"] == eval_power.detected_code(family, b, ("llm_rules_tool",))
            assert {"rejects", "detected"} == set(row["noise"]["systematic"]["null"])
            mdd = row["mdd"]
            assert mdd is None or (mdd["power"] >= 0.8 and abs(mdd["gap"]) <= 0.3)
    assert doc["comparisons"]["F1_accuracy"]["ordnung-vs-llm_rules_tool"]["detected_as"] == "non_inferior"
    assert doc["comparisons"]["F2_harm"]["ordnung-vs-llm_only"]["detected_as"] == "fewer"
    text = eval_power.render(doc)
    assert text == eval_power.render(json.loads(text))


def test_the_power_command_writes_and_checks_its_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prereg = tmp_path / "draft.json"
    prereg.write_text(json.dumps({"analysis": analysis.default_prereg_analysis()}), encoding="utf-8")
    runs = tmp_path / "holdout.json"
    runs.write_text(json.dumps(_run("holdout", 1, LETTERS, _outcome)), encoding="utf-8")
    out = tmp_path / "power.json"
    args = [
        "--prereg",
        str(prereg),
        "--runs",
        str(runs),
        "--manifest",
        str(tmp_path / "none.json"),
        "--reps",
        "4",
        "--draws",
        "50",
        "--resamples",
        "50",
        "--step",
        "0.1",
        "--noise",
        "systematic",
    ]
    assert eval_power.main([*args, "--out", str(out)]) == 0
    written = out.read_text(encoding="utf-8")
    assert json.loads(written)["structure"]["source"] == "the runs' clusters (no holdout4 letters yet)"
    assert eval_power.main([*args, "--check", str(out)]) == 0
    out.write_text(written.replace('"reps": 4', '"reps": 5'), encoding="utf-8")
    assert eval_power.main([*args, "--check", str(out)]) == 1


# --------------------------------------------------------------------------------------------------
# The owner's checks: label sample and Cohen's κ
# --------------------------------------------------------------------------------------------------


def _final_manifest() -> dict[str, Any]:
    entries = []
    families = [f"fam{i:02d}" for i in range(12)]
    for i, family in enumerate(families):
        for j in range(1 + i % 3):
            ident = f"holdout4-{family}-{j}"
            entries.append(_entry(ident, "holdout4", family, ["2026-12-20", "ambiguous", "2026-12-21"]))
            entries.append(_entry(f"{ident}-photo", "holdout4", family, ["2026-12-20"], photo_of=ident))
    for k in range(7):
        entries.append(_entry(f"newkinds-k{k}", "newkinds", f"kind{k}", ["2027-01-04", "2027-01-05"]))
    return _manifest(entries)


def test_the_owner_s_label_sample_is_20_holdout4_dates_by_family_and_10_newkinds() -> None:
    manifest = _final_manifest()
    sample = owner_label_sample.sample(manifest, seed=20261029)
    holdout4 = [row for row in sample if row["split"] == "holdout4"]
    newkinds = [row for row in sample if row["split"] == "newkinds"]
    assert (len(holdout4), len(newkinds)) == (20, 10)
    assert len({row["family"] for row in holdout4}) == 12  # every family
    assert len({row["family"] for row in newkinds}) == 7
    assert not any(row["entry_id"].endswith("-photo") for row in sample)  # a photo carries its letter's dates
    assert all(row["slot"] in ("i0", "i2") for row in holdout4)  # dated slots only
    assert all(row["slot"] in ("i0", "i1") for row in newkinds)
    assert len({(row["entry_id"], row["slot"]) for row in sample}) == 30
    assert owner_label_sample.sample(manifest, seed=20261029) == sample
    assert owner_label_sample.sample(manifest, seed=1) != sample
    for row in sample:  # ids and where to find the letter, never a label or an answer
        assert set(row) == {"split", "entry_id", "slot", "family", "file"}


def test_the_owner_s_label_file_is_pending_and_names_its_manifest(tmp_path: Path) -> None:
    path = _put(tmp_path, "manifest.json", json.dumps(_final_manifest()))
    record = owner_label_sample.record(path, seed=20261029)
    assert record["status"] == "pending"
    assert record["manifest_sha256"] == _sha(path.read_bytes())
    assert record["plan"] == {"holdout4": 20, "newkinds": 10}
    assert (record["checked"], record["agree"], record["source"]) == (None, None, None)
    assert all(row["verdict"] is None for row in record["items"])


def test_the_label_sample_waits_for_the_final_letters(tmp_path: Path) -> None:
    manifest = _manifest([_entry("h3-a", "holdout3", "appointment", ["2026-10-01"])])
    with pytest.raises(owner_label_sample.SampleError, match="holdout4"):
        owner_label_sample.sample(manifest, seed=20261029)


@pytest.mark.parametrize(
    ("pairs", "kappa"),
    [
        ([(True, True), (False, False), (True, True), (False, False)], 1.0),
        ([(True, True), (True, False), (False, True), (False, False)], 0.0),
        # 50 items: both yes 20, yes/no 5, no/yes 10, both no 15: p_o 0.7, p_e 0.5
        ([("y", "y")] * 20 + [("y", "n")] * 5 + [("n", "y")] * 10 + [("n", "n")] * 15, 0.4),
        # three categories: p_o 0.6, p_e 0.42
        (
            [("a", "a")] * 4 + [("b", "b")] * 1 + [("c", "c")] * 1 + [("a", "b")] * 2 + [("c", "a")] * 2,
            0.3103,
        ),
    ],
)
def test_cohen_s_kappa_on_textbook_tables(pairs: list[tuple[Any, Any]], kappa: float) -> None:
    assert owner.cohen_kappa(pairs) == pytest.approx(kappa, abs=1e-4)


def test_kappa_is_undefined_without_pairs_or_with_one_category() -> None:
    assert owner.cohen_kappa([]) is None
    assert owner.cohen_kappa([(True, True), (True, True)]) is None


def test_the_allocation_gives_every_stratum_one_and_the_rest_by_size() -> None:
    assert owner.allocate({"a": 10, "b": 30, "c": 60}, 10) == {"a": 1, "b": 3, "c": 6}
    assert owner.allocate({"a": 1, "b": 1, "c": 98}, 10) == {"a": 1, "b": 1, "c": 8}
    assert owner.allocate({"a": 2, "b": 50}, 40) == {"a": 2, "b": 38}
    assert sum(owner.allocate({f"s{i}": 5 + i for i in range(12)}, 20).values()) == 20
    with pytest.raises(ValueError, match="only 3"):
        owner.allocate({"a": 1, "b": 2}, 4)


def _ask_results() -> dict[str, Any]:
    categories = ["deadline"] * 30 + ["payment"] * 20 + ["household"] * 16 + ["unanswerable"] * 16
    questions = []
    for i, category in enumerate(categories):
        listed = category == "payment" and i % 4 == 0
        questions.append(
            {
                "id": f"ho-{i:03d}",
                "category": category,
                "question": "never exported",
                "scores": {"abstained_final": category == "unanswerable" and i % 5 != 0},
                "strict": {
                    "harmful": i % 7 == 0,
                    "list_gold": 3 if listed else 0,
                    "list_false": 1 if listed and i % 8 == 0 else 0,
                },
                "turn": {"final": "never exported"},
            }
        )
    return {"set": "heldout", "repeat": 1, "questions": questions, "attacks": []}


def test_the_ask_sample_is_40_answers_of_run_1_by_category_and_carries_no_answer() -> None:
    results = _ask_results()
    sample = owner.sample_answers(results, seed=20261029)
    assert len(sample) == 40 and len({row["id"] for row in sample}) == 40
    counts = {
        c: sum(1 for row in sample if row["category"] == c)
        for c in ("deadline", "payment", "household", "unanswerable")
    }
    assert counts == {"deadline": 14, "payment": 10, "household": 8, "unanswerable": 8}
    assert owner.sample_answers(results, seed=20261029) == sample
    assert all(set(row) == {"id", "category"} for row in sample)
    with pytest.raises(ValueError, match="repeat 1"):
        owner.sample_answers(dict(results, repeat=2), seed=20261029)


def test_the_scorer_s_labels_are_what_the_owner_labels_by_hand() -> None:
    rows = {row["id"]: row for row in _ask_results()["questions"]}
    assert owner.scorer_labels(rows["ho-000"]) == {
        "abstained": False,
        "false_inclusion": None,
        "harmful": True,
    }
    assert owner.scorer_labels(rows["ho-032"]) == {
        "abstained": False,
        "false_inclusion": True,
        "harmful": False,
    }
    assert owner.scorer_labels(rows["ho-036"]) == {
        "abstained": False,
        "false_inclusion": False,
        "harmful": False,
    }
    assert owner.scorer_labels(rows["ho-071"]) == {
        "abstained": True,
        "false_inclusion": None,
        "harmful": False,
    }


def test_the_kappa_file_goes_from_pending_to_drawn_to_scored(tmp_path: Path) -> None:
    pending = owner.pending_record()
    assert pending["status"] == "pending" and pending["sample"] is None
    assert (pending["answers"], pending["kappa"]) == (None, None)
    results = _ask_results()
    run = _put(tmp_path, "r1.json", json.dumps(results))
    drawn = owner.drawn_record(run)
    assert drawn["status"] == "pending" and len(drawn["sample"]) == 40
    assert drawn["run"] == {"file": "r1.json", "sha256": _sha(run.read_bytes())}
    rows = {row["id"]: row for row in results["questions"]}
    labels = {row["id"]: owner.scorer_labels(rows[row["id"]]) for row in drawn["sample"]}
    first = drawn["sample"][0]["id"]
    labels[first] = dict(labels[first], harmful=not labels[first]["harmful"])
    scored = owner.scored_record(drawn, results, labels)
    assert scored["status"] == "done" and scored["answers"] == 40
    assert 0 < scored["kappa"] < 1
    assert scored["by_aspect"]["abstained"]["kappa"] == 1.0
    assert scored["by_aspect"]["harmful"]["agree"] == scored["by_aspect"]["harmful"]["n"] - 1
    with pytest.raises(ValueError, match="no labels for"):
        owner.scored_record(drawn, results, dict(list(labels.items())[1:]))


def test_the_owner_s_commands_write_the_files_each_step_needs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _put(tmp_path, "manifest.json", json.dumps(_final_manifest()))
    labels = tmp_path / "owner-labels.json"
    assert owner_label_sample.main(["--manifest", str(manifest), "--out", str(labels)]) == 0
    assert json.loads(labels.read_text(encoding="utf-8"))["status"] == "pending"
    assert owner_label_sample.main(["--manifest", str(manifest), "--check", str(labels)]) == 0
    assert owner_label_sample.main(["--manifest", str(manifest), "--seed", "1", "--check", str(labels)]) == 1
    empty = _put(tmp_path, "empty.json", json.dumps(_manifest([])))
    assert owner_label_sample.main(["--manifest", str(empty), "--out", str(tmp_path / "x.json")]) == 2
    kappa = tmp_path / "owner-kappa.json"
    assert owner.main(["--pending", "--out", str(kappa)]) == 0
    assert json.loads(kappa.read_text(encoding="utf-8")) == owner.pending_record()
    run = _put(tmp_path, "r1.json", json.dumps(_ask_results()))
    assert owner.main(["--draw", str(run), "--out", str(kappa)]) == 0
    drawn = json.loads(kappa.read_text(encoding="utf-8"))
    rows = {row["id"]: row for row in _ask_results()["questions"]}
    drawn["labels"] = {row["id"]: owner.scorer_labels(rows[row["id"]]) for row in drawn["sample"]}
    kappa.write_text(json.dumps(drawn), encoding="utf-8")
    scored = tmp_path / "scored.json"
    assert owner.main(["--score", str(kappa), "--run", str(run), "--out", str(scored)]) == 0
    assert json.loads(scored.read_text(encoding="utf-8"))["kappa"] == 1.0
    other = _put(tmp_path, "r2.json", json.dumps(dict(_ask_results(), repeat=2)))
    with pytest.raises(SystemExit):
        owner.main(["--score", str(kappa), "--run", str(other)])
    assert "not the run the sample was drawn from" in capsys.readouterr().err


# --------------------------------------------------------------------------------------------------
# The calibration on the held-out splits
# --------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def calibration() -> dict[str, Any]:
    return prereg_calibration.calibrate()


def test_the_calibration_reproduces_the_dry_run(calibration: dict[str, Any]) -> None:
    """The held-out splits recorded before the freeze, pooled as three identical reads: Ordnung 163 of 168 in each,
    31 against 4 discordant with the model alone in read 1, no item unstable, and the decisions clear, level within
    noise and cannot tell."""
    primary = calibration["primary"]
    assert (primary["items"], primary["letters"], primary["clusters"], primary["reads"]) == (168, 189, 129, 3)
    assert primary["conditions"]["ordnung"]["exact_per_read"] == [163, 163, 163]
    assert primary["conditions"]["llm_only"]["exact_per_read"] == [136, 136, 136]
    assert primary["conditions"]["ordnung"]["harmful_per_read"] == [3, 3, 3]
    sensitivity = primary["sensitivity_r1"]["accuracy"]["ordnung-vs-llm_only"]
    assert (sensitivity["b"], sensitivity["c"]) == (31, 4)
    decisions = primary["decisions"]
    assert decisions["beats_llm_only"] == "clear"
    assert decisions["vs_llm_rules_text"] == "level_within_noise"
    assert decisions["vs_llm_rules_tool"] == "cannot_tell"
    for row in primary["families"]["F3_stability"].values():
        assert (row["b"], row["c"]) == (0, 0)
    for condition in CONDITIONS:
        assert primary["conditions"][condition]["unstable"] == 0
    assert [row["role"] for row in calibration["inputs"]] == [
        "pooled reads",
        "pooled reads",
        "pooled reads and newkinds",
    ]


def test_the_calibration_names_its_inputs_by_hash_and_holds_no_text(calibration: dict[str, Any]) -> None:
    for row in calibration["inputs"]:
        path = ROOT / "evals" / "results" / row["file"]
        assert row["sha256"] == _sha(path.read_bytes())
    text = prereg_calibration.render(calibration)
    assert "question" not in text and "quote" not in text and "title" not in text


def test_the_calibration_command_writes_and_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calibration: dict[str, Any]
) -> None:
    monkeypatch.setattr(prereg_calibration, "calibrate", lambda results_dir=None: calibration)
    out = tmp_path / "calibration.json"
    assert prereg_calibration.main(["--out", str(out)]) == 0
    assert prereg_calibration.main(["--check", str(out)]) == 0
    assert prereg_calibration.main(["--check", str(tmp_path / "none.json")]) == 1
    out.write_text(out.read_text(encoding="utf-8").replace("163", "164", 1), encoding="utf-8")
    assert prereg_calibration.main(["--check", str(out)]) == 1
