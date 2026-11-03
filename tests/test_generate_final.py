"""The generator's final splits and what the people who write them see (``evals/generate.py``, ``evals/gen``).

* Without a ``gen/final.py`` plug-in the generator writes the five earlier splits byte for byte as before; with one
  it adds the plug-in's splits, each entry carrying ``final_day`` and ``valid_until``.
* A final letter is read on the plug-in's ``FINAL_DAY``; every scored date, contract date and appointment (and every
  date under a disputed convention's other reading) lies after ``VALID_UNTIL``; every scored item names the
  conventions its label rests on. ``--final-day`` must name the plug-in's day.
* Every convention has a stable id and a ``disputed`` flag: exactly the conventions the "Judgement calls kept on
  purpose" sections of ``evals/dataset/VERIFICATION.md`` name are disputed.
* The cap is 40 MiB, the holiday tables are checked for 2024–2029 and the environment names fontTools.
* The files a writer's sandbox holds say nothing of the software the letters are read by: a lint (the sandbox's own
  pattern) passes over them, line by line, against an allow-list of lines kept by sha256 (no line is printed).

The synthetic plug-in is ``tests/fixtures/final_plugin/final.py``. Nothing here prints letter text.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
DATASET = EVALS / "dataset"
MANIFEST = DATASET / "manifest.json"
VERIFICATION = DATASET / "VERIFICATION.md"
FIXTURE = ROOT / "tests" / "fixtures" / "final_plugin" / "final.py"

if str(EVALS) not in sys.path:
    sys.path.insert(0, str(EVALS))

import generate  # noqa: E402
from gen import law  # noqa: E402

#: The splits the generator's own builders write.
EARLIER_SPLITS = ("dev", "test", "holdout", "holdout2", "holdout3")
#: sha256 over "file NUL sha256 LF" of every letter of the earlier splits, sorted by file, as main had them.
EARLIER_LETTERS_SHA256 = "e74b7e41b9659db660973a5609237544dd1ee1bcee231de810d3ec12f5bb2338"
EARLIER_LETTERS = 280


def _letters_digest(entries: list[dict[str, Any]]) -> tuple[int, str]:
    rows = sorted((e["file"], e["sha256"]) for e in entries if e["split"] in EARLIER_SPLITS)
    return len(rows), hashlib.sha256("".join(f"{f}\0{s}\n" for f, s in rows).encode()).hexdigest()


def _fixture(name: str = "gen._final_fixture") -> ModuleType:
    """The synthetic plug-in, loaded as a module of ``gen`` (its relative imports resolve there)."""
    spec = importlib.util.spec_from_file_location(name, FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fixture() -> ModuleType:
    return _fixture()


@pytest.fixture(scope="module")
def plugin(fixture: ModuleType) -> Any:
    return generate.final_plugin(fixture)


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return data


# --------------------------------------------------------------------------------------------------
# (a) the earlier splits are unchanged
# --------------------------------------------------------------------------------------------------


def test_the_earlier_letters_are_main_s_byte_for_byte(manifest: dict[str, Any]) -> None:
    """The committed manifest lists the earlier splits' letters with main's sha256s (``tests/test_eval_dataset.py``
    regenerates them without a plug-in and compares every file with the manifest)."""
    assert _letters_digest(manifest["entries"]) == (EARLIER_LETTERS, EARLIER_LETTERS_SHA256)


def test_the_manifest_lists_the_generator_s_conventions_first(manifest: dict[str, Any]) -> None:
    assert manifest["conventions"][: len(generate.CONVENTIONS)] == generate.CONVENTIONS
    assert all(
        "final_day" not in e and "valid_until" not in e
        for e in manifest["entries"]
        if e["split"] in EARLIER_SPLITS
    )


# --------------------------------------------------------------------------------------------------
# (b) the plug-in's splits
# --------------------------------------------------------------------------------------------------


def test_the_synthetic_plug_in_builds_its_split(plugin: Any, fixture: ModuleType) -> None:
    assert plugin.final_day == fixture.FINAL_DAY and plugin.valid_until == fixture.VALID_UNTIL
    cases = generate.build_cases(plugin)
    final = [c for c in cases if c.split == "newkinds"]
    assert [c.id for c in final] == [fixture.CASE_ID]
    assert {c.split for c in cases} == {*EARLIER_SPLITS, "newkinds"}
    assert final[0].truth["kind_also_accepted"] == ["invoice"]
    without = generate.build_cases(None)
    assert {c.split for c in without} == set(EARLIER_SPLITS)


def test_each_final_entry_carries_its_day_and_window(plugin: Any, tmp_path: Path) -> None:
    (case,) = [c for c in generate.build_cases(plugin) if c.split == "newkinds"]
    entries = generate.write_case(case, tmp_path, plugin)
    assert [e["id"] for e in entries] == [case.id, f"{case.id}-photo"]
    for entry in entries:
        assert entry["today"] == entry["final_day"] == plugin.final_day.isoformat()
        assert entry["valid_until"] == plugin.valid_until.isoformat()
        assert list(entry).index("final_day") == list(entry).index("today") + 1
        assert (tmp_path / entry["file"]).is_file()
    (earlier,) = [c for c in generate.build_cases(None) if c.id == "test-dunning_fixed-C1"]
    (plain, *_rest) = generate.write_case(earlier, tmp_path, plugin)
    assert "final_day" not in plain and "valid_until" not in plain


def test_the_plug_in_s_conventions_follow_the_generator_s(plugin: Any) -> None:
    ids = [c["id"] for c in generate.all_conventions(plugin)]
    assert ids == [*(c["id"] for c in generate.CONVENTIONS), "f01"]
    assert [c["id"] for c in generate.all_conventions(None)] == [c["id"] for c in generate.CONVENTIONS]


# --------------------------------------------------------------------------------------------------
# (c) the window: today, scored dates, tags
# --------------------------------------------------------------------------------------------------


def _case(fixture: ModuleType, **kwargs: Any) -> Any:
    (case,) = fixture.payment_request(**kwargs)
    return case


def _check(case: Any, plugin: Any) -> None:
    generate.check_final_case(case, plugin, {c["id"]: c for c in generate.all_conventions(plugin)})


def _with_truth(case: Any, change: Any) -> Any:
    truth = copy.deepcopy(case.truth)
    change(truth)
    return dataclasses.replace(case, truth=truth)


def test_the_synthetic_case_passes(fixture: ModuleType, plugin: Any) -> None:
    _check(_case(fixture), plugin)


def test_a_scored_date_inside_the_window_is_refused(fixture: ModuleType, plugin: Any) -> None:
    last = plugin.valid_until
    while not all(law.is_working_day(last, land) for land in law.LAENDER):
        last -= timedelta(days=1)
    with pytest.raises(generate.FinalSplitError, match=r"items\[0\].* not after the window"):
        _check(_case(fixture, due=last), plugin)
    after = last + timedelta(days=1)
    while after <= plugin.valid_until or not all(law.is_working_day(after, land) for land in law.LAENDER):
        after += timedelta(days=1)
    _check(_case(fixture, due=after), plugin)


def test_a_letter_not_read_on_the_final_day_is_refused(fixture: ModuleType, plugin: Any) -> None:
    with pytest.raises(generate.FinalSplitError, match="today"):
        _check(_case(fixture, today=plugin.final_day - timedelta(days=1)), plugin)


def test_contract_dates_and_appointments_must_lie_after_the_window(fixture: ModuleType, plugin: Any) -> None:
    inside = plugin.valid_until.isoformat()
    later = (plugin.valid_until + timedelta(days=40)).isoformat()

    def contract(term_end: str, cancel_by: str) -> Any:
        def change(truth: dict[str, Any]) -> None:
            truth["contract"] = {
                "expected_current_term_end": term_end,
                "expected_cancel_by": cancel_by,
                "conventions": ["c22"],
                "convention_alternatives": {"expected_cancel_by": [later]},
            }

        return change

    case = _case(fixture)
    _check(_with_truth(case, contract(later, (plugin.valid_until + timedelta(days=20)).isoformat())), plugin)
    with pytest.raises(generate.FinalSplitError, match="expected_cancel_by"):
        _check(_with_truth(case, contract(later, inside)), plugin)
    with pytest.raises(generate.FinalSplitError, match="expected_current_term_end"):
        _check(_with_truth(case, contract(inside, later)), plugin)

    def appointment(truth: dict[str, Any]) -> None:
        truth["optional_items"] = [{**truth["items"][0], "kind": "appointment", "expected_due": inside}]

    with pytest.raises(generate.FinalSplitError, match=r"optional_items\[0\]"):
        _check(_with_truth(case, appointment), plugin)


def test_every_scored_item_names_known_conventions(fixture: ModuleType, plugin: Any) -> None:
    case = _case(fixture)

    def drop(truth: dict[str, Any]) -> None:
        del truth["items"][0]["conventions"]

    with pytest.raises(generate.FinalSplitError, match="conventions"):
        _check(_with_truth(case, drop), plugin)
    with pytest.raises(generate.FinalSplitError, match="c99"):
        _check(_case(fixture, tags=["c06", "c99"]), plugin)
    _check(_case(fixture, tags=[]), plugin)  # a label that rests on no listed convention

    def no_contract_tags(truth: dict[str, Any]) -> None:
        later = (plugin.valid_until + timedelta(days=40)).isoformat()
        truth["contract"] = {"expected_current_term_end": later, "expected_cancel_by": later}

    with pytest.raises(generate.FinalSplitError, match=r"contract.*conventions"):
        _check(_with_truth(case, no_contract_tags), plugin)


def test_a_disputed_convention_needs_its_other_reading(fixture: ModuleType, plugin: Any) -> None:
    disputed = next(c["id"] for c in generate.CONVENTIONS if c["disputed"])
    case = _case(fixture, tags=["c06", disputed])
    with pytest.raises(generate.FinalSplitError, match="convention_alternatives"):
        _check(case, plugin)
    due = date.fromisoformat(case.truth["items"][0]["expected_due"])

    def alternatives(*days: date) -> Any:
        def change(truth: dict[str, Any]) -> None:
            truth["items"][0]["convention_alternatives"] = [d.isoformat() for d in days]

        return change

    _check(_with_truth(case, alternatives(due + timedelta(days=1))), plugin)
    _check(_with_truth(case, alternatives()), plugin)  # the other reading gives no other date
    with pytest.raises(generate.FinalSplitError, match="label itself"):
        _check(_with_truth(case, alternatives(due)), plugin)
    with pytest.raises(generate.FinalSplitError, match="not after the window"):
        _check(_with_truth(case, alternatives(plugin.valid_until)), plugin)
    with pytest.raises(generate.FinalSplitError, match="no disputed convention"):
        _check(_with_truth(_case(fixture), alternatives(due + timedelta(days=1))), plugin)


def test_the_plug_in_s_tables_are_checked(fixture: ModuleType) -> None:
    def module(**changes: Any) -> SimpleNamespace:
        names = ("FINAL_DAY", "VALID_UNTIL", "FAMILIES", "CONVENTIONS_FINAL", "KIND_ALSO_ACCEPTED_FINAL")
        return SimpleNamespace(**{name: getattr(fixture, name) for name in names} | changes)

    generate.final_plugin(module())
    cases = [
        ({"VALID_UNTIL": fixture.FINAL_DAY - timedelta(days=1)}, "VALID_UNTIL"),
        ({"FINAL_DAY": "2026-12-08"}, "FINAL_DAY"),
        ({"CONVENTIONS_FINAL": [{"id": "c01", "disputed": False, "text": "x"}]}, "f01"),
        ({"CONVENTIONS_FINAL": [{"id": "f01", "disputed": "no", "text": "x"}]}, "disputed"),
        ({"CONVENTIONS_FINAL": [*fixture.CONVENTIONS_FINAL, *fixture.CONVENTIONS_FINAL]}, "twice"),
        ({"FAMILIES": {"holdout3": fixture.FAMILIES["newkinds"]}}, "holdout3"),
        ({"FAMILIES": {}}, "FAMILIES"),
    ]
    for changes, message in cases:
        with pytest.raises(generate.FinalSplitError, match=message):
            generate.final_plugin(module(**changes))
    del_module = module()
    del del_module.KIND_ALSO_ACCEPTED_FINAL
    with pytest.raises(generate.FinalSplitError, match="KIND_ALSO_ACCEPTED_FINAL"):
        generate.final_plugin(del_module)


def test_the_cases_must_match_the_plug_in_s_tables(fixture: ModuleType) -> None:
    def plugin(**changes: Any) -> Any:
        names = ("FINAL_DAY", "VALID_UNTIL", "FAMILIES", "CONVENTIONS_FINAL", "KIND_ALSO_ACCEPTED_FINAL")
        return generate.final_plugin(SimpleNamespace(**{n: getattr(fixture, n) for n in names} | changes))

    with pytest.raises(generate.FinalSplitError, match="newkinds-nothing"):
        generate.build_cases(plugin(KIND_ALSO_ACCEPTED_FINAL={"newkinds-nothing": ["invoice"]}))
    with pytest.raises(generate.FinalSplitError, match="template family"):
        generate.build_cases(plugin(FAMILIES={"newkinds": (("tax_assessment", fixture.payment_request),)}))
    with pytest.raises(generate.FinalSplitError, match="today"):
        generate.build_cases(
            plugin(
                FAMILIES={
                    "newkinds": (("adversarial", lambda: fixture.payment_request(today=date(2026, 1, 1))),)
                }
            )
        )


# --------------------------------------------------------------------------------------------------
# (d) --final-day
# --------------------------------------------------------------------------------------------------


def test_final_day_must_be_the_plug_in_s(
    plugin: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(generate, "load_final", lambda: plugin)
    other = plugin.final_day + timedelta(days=1)
    with pytest.raises(SystemExit) as exit_:
        generate.main(["--out", str(tmp_path / "out"), "--final-day", other.isoformat(), "--quiet"])
    assert exit_.value.code == 2
    assert (
        f"--final-day {other.isoformat()} is not the plug-in's FINAL_DAY {plugin.final_day}"
        in capsys.readouterr().err
    )
    assert not (tmp_path / "out").exists()


def test_final_day_without_a_plug_in_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(generate, "load_final", lambda: None)
    with pytest.raises(SystemExit) as exit_:
        generate.main(["--out", str(tmp_path / "out"), "--final-day", "2026-12-08", "--quiet"])
    assert exit_.value.code == 2
    assert "no final-split plug-in" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


# --------------------------------------------------------------------------------------------------
# (e) cap, environment, holiday years
# --------------------------------------------------------------------------------------------------


def test_the_cap_the_environment_and_the_holiday_years(manifest: dict[str, Any]) -> None:
    import fontTools

    assert generate.MAX_TOTAL_BYTES == 40 * 1024 * 1024
    assert manifest["total_bytes"] < generate.MAX_TOTAL_BYTES
    assert generate.HOLIDAY_YEARS == range(2024, 2030)
    law.cross_check_with_holidays_package(generate.HOLIDAY_YEARS)
    assert generate.environment()["fonttools"] == fontTools.version
    assert set(manifest["environment"]) == set(generate.environment())


# --------------------------------------------------------------------------------------------------
# conventions: ids, disputed flags, wording
# --------------------------------------------------------------------------------------------------

#: The bold lead of every bullet in VERIFICATION.md's "Judgement calls kept on purpose" sections of the earlier splits,
#: and the convention it is about (None: a fact about the calendar or a source, not a labelling convention).
JUDGEMENT_CALLS: dict[str, str | None] = {
    "A stated posting day is the anchor": "c02",
    "VwVfG / SGB X deemed-delivery day never moves": "c03",
    "The VwVfG / SGB X fiction day never moves": "c03",
    "Which law each sender uses": "c03",
    "Land VwVfG letters come after the Land's 4-day rule took effect": "c07",
    "Klage labels": "c09",
    "The Klage label": "c09",
    "The Klage labels": "c09",
    "Price-increase items are optional": "c10",
    "remedy_type follows the letter's own Rechtsbehelfsbelehrung": "c20",
    "Document kinds with two honest answers": "c20",
    "A notice deadline on a Sunday stays": "c22",
    "Holiday data source": None,
    "Berlin's one-off holiday on 08.05.2025": None,
    "A removal date in 2028": None,
}
JUDGEMENT_SECTIONS = (
    "## Judgement calls kept on purpose (documented, not changed)",
    "### Judgement calls kept on purpose (holdout)",
    "### Judgement calls kept on purpose (holdout2)",
    "### Judgement calls kept on purpose (holdout3)",
)


def _judgement_leads() -> set[str]:
    leads: set[str] = set()
    section = None
    for line in VERIFICATION.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            section = line if line in JUDGEMENT_SECTIONS else None
        elif section and line.startswith("- **"):
            lead = line[4:].split("**", 1)[0]
            leads.add(lead.replace("`", "").rstrip(".:"))
    return leads


def test_every_convention_has_a_stable_id_and_a_disputed_flag() -> None:
    conventions = generate.CONVENTIONS
    assert [c["id"] for c in conventions] == [f"c{n:02d}" for n in range(1, len(conventions) + 1)]
    for convention in conventions:
        assert list(convention) == ["id", "disputed", "text"]
        assert isinstance(convention["disputed"], bool) and convention["text"].strip()


def test_disputed_means_named_by_a_judgement_call() -> None:
    leads = _judgement_leads()
    assert leads and leads <= set(JUDGEMENT_CALLS), sorted(leads - set(JUDGEMENT_CALLS))
    named = {JUDGEMENT_CALLS[lead] for lead in leads} - {None}
    assert {c["id"] for c in generate.CONVENTIONS if c["disputed"]} == named


# --------------------------------------------------------------------------------------------------
# (f) what a writer's sandbox holds says nothing of the software that reads the letters
# --------------------------------------------------------------------------------------------------

#: The sandbox lint's pattern (case-insensitive), run over every file of a writer's sandbox.
LINT = re.compile(
    r"deadline-rules|by design|scorer|test_evals_run|src/ordnung|ordnung\.(rules|ingest|llm)|detector|pipeline"
    r"|please check|two dates|recorded|results file|prompt|\bordnung\b",
    re.IGNORECASE,
)
#: The lint's two-word phrases, found also when a line break splits them (the sandbox's own lint joins the lines).
SPLIT_ENDS = {"by": "design", "please": "check", "two": "dates", "results": "file"}
SPLIT = re.compile(rf"\b({'|'.join(SPLIT_ENDS)})\s*$", re.IGNORECASE)
#: Phrases that may hit it anywhere: the German word in an authority's name, and the attack class.
PHRASES = re.compile(r"öffentlichen? (?:Sicherheit und )?Ordnung|prompt[ -]injections?", re.IGNORECASE)
#: The data writer's sandbox (the stress-template writer's adds W1C_ONLY); the redacted VERIFICATION.md and the
#: stripped pyproject.toml are made outside the checkout and linted there.
W1_FILES = (
    "evals/gen/**/*",
    "evals/generate.py",
    "evals/verify_labels.py",
    "tests/test_eval_dataset.py",
    "constraints.txt",
    "src/ordnung/drafts/fonts/DejaVuSans.ttf",
    "src/ordnung/drafts/fonts/DejaVuSans-Bold.ttf",
    "src/ordnung/drafts/fonts/LICENSE-DejaVu.txt",
    "evals/law/**/*",
)
W1C_ONLY = ("evals/perturb/templates.py", "evals/perturb/README.md")
_NAME = "the benchmark's or the product's name, as the PDFs carry it"
_NOT_FROM = "says the labels do not come from the product's rules"
_OTHER_SENSE = "the word in another sense"
_SCHEMA = "the stress templates' schema id, which carries the benchmark's name"
#: Lines a hit is allowed on, by path and the sha256 of the line (UTF-8, without its line break), with the reason.
ALLOWED: dict[str, dict[str, str]] = {
    "evals/generate.py": {
        "0113d5206aea925f753da3587b11b9498c350b6efe0835a78aba76fb75203eb9": _NAME,
        "fadd5a4870db7658faa60e5b6e3bf3b85b1425d0c64884fd0c2433770c7a0a38": _NOT_FROM,
        "f3a47f35f1b53060adb75f8b5c517ef8b20beebe452b911721dd4308921d5fe4": _NAME,
    },
    "evals/gen/pdf.py": {
        "178d04b026e9457827677c34ea849b26dd79d084d553538511ad93f1f01ed919": "the fonts' folder",
        "303a8a1e32f9c4bdaa289b210e3e0bd0d280b0d73deb9d058959806860a63432": _NAME,
        "db77f8f6acf770b67f1ed781be27ce3f562ae70e6d044016211e478d01520ad5": _NAME,
        "e6f1a9ec20539cd3884d148d66f08e9ca26464e512d32e42cfc2824fd4231180": _NAME,
    },
    "evals/gen/photo.py": {"3ca9a83e7333e40e0b0540d5a05728d5ebff198805a7a1d2d18464db0c5fb113": _OTHER_SENSE},
    "evals/verify_labels.py": {"ab8227f4d7b49efd3e2b1ee3631b0eb8862aa0ad218a57359c85d1b27d0b19c3": _NOT_FROM},
    "tests/test_eval_dataset.py": {
        "34ec5947172b561b31b9ee9a7ebbca59719f347fcbcbedf3857ccc4bf10f6e1b": _OTHER_SENSE,
        "a6e6fb5c251d9db4fdce0f76f950f38d543e25b9e76a7f12bc16ba28b58d01c6": _NOT_FROM,
        "37ed061fe8a4eae8aacbb15c5980e381638312e13af4c052161c31c2834a8196": "says the test imports nothing of the "
        "product",
        "f7898694cb840d135785011a5f3de2a0ef2936c24a92449a04c5f29ba5987654": _NOT_FROM,
        "95335632b2a0a6262baa7a2d5cba969200180335badaa678333266d3822531aa": _OTHER_SENSE,
    },
    "evals/perturb/templates.py": {
        "a30a8538fd39dcb9d07bedcd684e8b4fecc3935be9b9e711b46a55ae6054443b": _SCHEMA
    },
    "evals/perturb/README.md": {"b868233bc5b857cf816b77a15d17fa4bc3cf4610bb2352782a485de240432ad5": _SCHEMA},
}
#: Hits other changes remove; each must still be there (delete it here when it is gone).
PENDING: dict[str, dict[str, str]] = {}


def _profile_files() -> list[str]:
    files: set[str] = set()
    for pattern in (*W1_FILES, *W1C_ONLY):
        for path in ROOT.glob(pattern) if "*" in pattern else [ROOT / pattern]:
            if path.is_file() and "__pycache__" not in path.parts:
                files.add(path.relative_to(ROOT).as_posix())
    return sorted(files)


def lint_hits(text: str) -> list[tuple[int, str, str]]:
    """(line number, matched word, sha256 of the line) for each line the lint hits outside :data:`PHRASES`."""
    lines = text.split("\n")
    hits = []
    for number, raw in enumerate(lines, 1):
        line = raw.rstrip("\r")
        rest = PHRASES.sub(" ", line)
        following = lines[number].lstrip() if number < len(lines) else ""
        if re.search(r"prompt\s*$", rest, re.IGNORECASE) and re.match(r"injection", following, re.IGNORECASE):
            rest = re.sub(
                r"prompt\s*$", " ", rest, flags=re.IGNORECASE
            )  # "prompt" / "injection" across a line break
        found = LINT.search(rest)
        word = found.group(0).lower() if found else None
        split = SPLIT.search(rest) if word is None else None
        end = SPLIT_ENDS[split.group(1).lower()] if split else ""
        if split and re.match(rf"{end}\b", following, re.IGNORECASE):
            word = f"{split.group(1).lower()} {end}"  # a phrase across a line break
        if word is not None:
            hits.append((number, word, hashlib.sha256(line.encode("utf-8")).hexdigest()))
    return hits


def _hits() -> dict[str, list[tuple[int, str, str]]]:
    return {
        path: hits
        for path in _profile_files()
        if (hits := lint_hits((ROOT / path).read_bytes().decode("utf-8", errors="replace")))
    }


def test_the_lint_allows_only_the_listed_phrases() -> None:
    def hit(text: str) -> list[str]:
        return [word for _, word, _ in lint_hits(text)]

    assert hit("Amt für öffentliche Ordnung") == [] and hit("Öffentliche Sicherheit und Ordnung") == []
    assert hit("visible and hidden prompt\ninjection, scams") == []
    assert hit("the prompt\nfile") == ["prompt"]
    assert hit("Ordnung reads it") == ["ordnung"] and hit("prompt injection, as the prompt says") == [
        "prompt"
    ]
    assert hit("Ordnungswidrigkeit; Abgabenordnung") == []
    # a phrase the lint names is found across a line break too, as the sandbox's own lint finds it
    assert hit("a contract's two\n    dates") == ["two dates"]
    assert hit("the results\nfile") == ["results file"]
    assert hit("two\ndays") == [] and hit("by\nthe design") == []


def test_a_writer_s_sandbox_holds_no_hint_of_the_software() -> None:
    """The sandbox lint passes over every file of a data or template writer's sandbox: each hit is on an allowed
    line, or on a line another change removes. Paths, line numbers, words and hashes only."""
    files = _profile_files()
    assert "evals/generate.py" in files and "evals/gen/law.py" in files and "evals/perturb/README.md" in files
    unexpected = [
        f"{path}:{number}: {word} (sha256 {sha})"
        for path, hits in _hits().items()
        for number, word, sha in hits
        if sha not in ALLOWED.get(path, {}) and sha not in PENDING.get(path, {})
    ]
    assert not unexpected, "\n".join(unexpected)


def test_every_pending_hit_is_still_there() -> None:
    present = {(path, sha) for path, hits in _hits().items() for _, _, sha in hits}
    gone = [f"{path} {sha}" for path, shas in PENDING.items() for sha in shas if (path, sha) not in present]
    assert not gone, "gone (delete from PENDING): " + ", ".join(gone)


def test_the_conventions_hold_no_hint_of_the_software() -> None:
    """The conventions go to the auditor who applies them, as written: no line of them hits the lint at all."""
    assert [c["id"] for c in generate.CONVENTIONS if LINT.search(c["text"])] == []


# --------------------------------------------------------------------------------------------------
# end to end, as a writer's sandbox runs it
# --------------------------------------------------------------------------------------------------


@pytest.mark.slow
def test_the_generator_runs_the_plug_in_from_gen_final(tmp_path: Path, manifest: dict[str, Any]) -> None:
    """A copy of the generator with the synthetic plug-in as ``gen/final.py``: ``--final-day`` must be its day;
    the earlier letters and entries are unchanged and the plug-in's two entries are added."""
    tree = tmp_path / "tree"
    shutil.copytree(
        EVALS / "gen", tree / "evals" / "gen", ignore=shutil.ignore_patterns("__pycache__", "final.py")
    )
    shutil.copy(EVALS / "generate.py", tree / "evals" / "generate.py")
    shutil.copytree(
        ROOT / "src" / "ordnung" / "drafts" / "fonts", tree / "src" / "ordnung" / "drafts" / "fonts"
    )
    shutil.copy(FIXTURE, tree / "evals" / "gen" / "final.py")
    fixture = _fixture("gen._final_fixture_e2e")

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            "-I",
            str(tree / "evals" / "generate.py"),
            "--out",
            str(tmp_path / "out"),
            *args,
        ]
        return subprocess.run(command, cwd=tree, capture_output=True, text=True, timeout=900, check=False)

    refused = run("--final-day", (fixture.FINAL_DAY + timedelta(days=1)).isoformat(), "--quiet")
    assert refused.returncode == 2 and "FINAL_DAY" in refused.stderr
    done = run("--final-day", fixture.FINAL_DAY.isoformat(), "--quiet")
    assert done.returncode == 0, done.stderr[-2000:]
    made = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    assert _letters_digest(made["entries"]) == (EARLIER_LETTERS, EARLIER_LETTERS_SHA256)
    earlier = [e for e in manifest["entries"] if e["split"] in EARLIER_SPLITS]
    assert [e for e in made["entries"] if e["split"] in EARLIER_SPLITS] == earlier
    final = [e for e in made["entries"] if e["split"] == "newkinds"]
    assert [e["id"] for e in final] == [fixture.CASE_ID, f"{fixture.CASE_ID}-photo"]
    assert all(e["final_day"] == fixture.FINAL_DAY.isoformat() for e in final)
    assert all(e["valid_until"] == fixture.VALID_UNTIL.isoformat() for e in final)
    assert made["conventions"] == [*generate.CONVENTIONS, *fixture.CONVENTIONS_FINAL]
    assert made["counts"]["newkinds"]["entries"] == 2 and made["counts"]["newkinds"]["photos"] == 1
