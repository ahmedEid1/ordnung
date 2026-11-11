"""The presenter's final path: a published final run takes the headline by the pre-registered rule.

Every final run here is synthetic and lives in a temporary checkout (``tests/helpers_final.py``): the hand-built finals
of ``tests/test_present_final.py`` completed to the real analysis's shape, and a real ``evals.analysis`` final analysis
of synthetic reads written beside it. With a final analysis in ``evals/results``, ``model.build`` finds it, its
pre-registration and the files it names (``final.published``), refuses anything that does not fit them, and puts the
final run into ``presentation.json``'s ``final``; the README's block is then the registered README sentences laid out
as registered, and ``docs/evals.md`` says every registered page sentence, in order, between its own markers under
"6.1 The final run". Every word the final path adds beside the registered sentences is a template of
``evals/present/templates/views.json``. With no final file, every output stays what it is (``tests/test_present.py``).
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from evals import reproduce
from evals.present import BEGIN, END, PresentError, build, charts, final, model, site, text
from evals.present.__main__ import main

import helpers_final as hf
import test_present_final as builders

#: what a path of the building computer starts with (as tests/test_present.py)
PATH_MARKS = ("/home/", "/Users/", "/root/", "/tmp/", "\\Users\\")
FINAL_SVGS = ("docs/assets/eval-final-light.svg", "docs/assets/eval-final-dark.svg")
FINAL_OUTPUTS = (*build.OUTPUT_PATHS, *FINAL_SVGS)
#: The fields of an error row the page may show (ids and codes, never a letter's words).
ERROR_KEYS = {
    "condition",
    "split",
    "entry_id",
    "item",
    "family",
    "modality",
    "outcome",
    "direction",
    "days_off",
    "confidence",
    "flagged",
    "tier",
    "cause",
    "read",
}


class Made:
    """A checkout with a final run: its root, ``model.build`` of it and, rendered once when first asked for, every
    output ``--write`` writes."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.doc = model.build(root / "evals" / "results")
        self._outputs: dict[str, str] | None = None

    @property
    def outputs(self) -> dict[str, str]:
        if self._outputs is None:
            self._outputs = build.outputs(self.root)
        return self._outputs

    def __iter__(self) -> Iterator[Any]:
        return iter((self.root, self.doc, self.outputs))


@pytest.fixture(scope="module", autouse=True)
def _legacy_page_once() -> Iterator[None]:
    """The history page's earlier runs, rendered once: every temporary checkout links the same results files."""
    page = build.legacy_page(hf.RESULTS)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(build, "legacy_page", lambda results_dir: page)
        yield


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> Callable[[str], Made]:
    """A checkout per final, built once: its root, ``model.build`` of it and every output it renders."""
    cache: dict[str, Made] = {}

    def make(name: str) -> Made:
        if name not in cache:
            tmp = tmp_path_factory.mktemp(name)
            cache[name] = Made(hf.realistic_root(tmp) if name == "realistic" else hf.scenario_root(tmp, name))
        return cache[name]

    return make


def _flat(value: str) -> str:
    return " ".join(value.split())


def _section(report: str, title: str) -> str:
    """One ``##`` section of a Markdown page, its heading line included."""
    start = report.index(f"\n## {title}\n")
    end = report.find("\n## ", start + 1)
    return report[start : end if end >= 0 else len(report)]


def _block(readme: str) -> list[str]:
    return readme.split(BEGIN + "\n", 1)[1].split("\n" + END, 1)[0].split("\n")


def _card(report: str) -> dict[str, str]:
    rows = [line for line in _section(report, "Evaluation card").splitlines() if line.startswith("| ")]
    return {cells[0]: cells[1] for cells in (row.strip("| ").split(" | ") for row in rows[1:])}


def _views() -> dict[str, Any]:
    from evals.present import views

    return views.load()


# --------------------------------------------------------------------------------------------------
# The model: the final run found, checked and put into presentation.json
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", hf.SCENARIO_IDS)
def test_a_published_final_takes_the_headline_by_rule(made: Callable[[str], Made], name: str) -> None:
    """Whatever the result, the final run is the headline: ``presentation.json``'s ``final`` holds it, the row order
    is its mean accuracy's, the README's block says the registered README sentences and nothing of the pooled
    re-analysis, and the report's summary is the registered paragraph with the final run's chart. The pooled
    held-out splits stay in section 6.2, as recorded, with their chart."""
    root, doc, outputs = made(name)
    source, prereg, named = hf.published(root)
    assert doc["final"] is not None and doc["final"]["source"]["file"] == hf.FINAL_NAME
    means = {c: source["primary"]["conditions"][c]["mean_accuracy"]["value"] for c in final.CONDITIONS}
    assert doc["order"] == sorted(final.CONDITIONS, key=lambda c: (-means[c], final.CONDITIONS.index(c)))
    said = final.coded(source, prereg, block="readme", sources=named)
    block = _block(outputs["README.md"])
    picture = block[block.index("") + 1]
    assert block == final.readme_block(said, prereg["sentences"], picture)
    assert "Held out, read once" not in "\n".join(block) and "**Ask:**" not in "\n".join(block)
    report = outputs["docs/evals.md"]
    summary = _section(report, "1. Summary")
    paragraph = [s.text for s in said if s.slot in prereg["sentences"]["readme_layout"]["paragraph"]]
    assert _flat(" ".join(paragraph)) in _flat(summary)
    assert "assets/eval-final-light.svg" in summary and "eval-held-out" not in summary
    assert _flat(text.headline(doc)) not in _flat(report)
    results = _section(report, "6. Results")
    assert "### 6.2 The held-out splits pooled, as recorded" in results
    assert "assets/eval-held-out-light.svg" in results.split("### 6.2 ", 1)[1]
    assert "not pre-registered" not in report.split("\n## ", 1)[0]  # the header names the final run


@pytest.mark.parametrize("name", ["good", "bad", "one_read", "realistic"])
def test_every_number_in_presentation_json_final_is_the_analysis_value_at_its_path(
    made: Callable[[str], Made], name: str
) -> None:
    """``presentation.json``'s ``final`` copies the final analysis, the pre-registration and the files it names: each
    number is the value at its path, never computed again, and the registered sentences are ``final.coded``'s."""
    root, doc = made(name).root, made(name).doc
    source, prereg, named = hf.published(root)
    shown = json.loads(model.dumps(doc))["final"]
    assert shown == doc["final"]
    primary = source["primary"]
    for key in ("split", "reads", "reads_registered", "reads_used", "reads_missing", "items", "letters"):
        assert shown[key] == primary[key], key
    assert (shown["clusters"], shown["not_run"]) == (primary["clusters"], primary["not_run"])
    for condition in final.CONDITIONS:
        ours, theirs = shown["conditions"][condition], primary["conditions"][condition]
        for key in ("exact_per_read", "harmful_per_read", "late_per_read"):
            assert ours[key] == [{k: rate[k] for k in ("k", "n", "value", "ci")} for rate in theirs[key]]
        for key in ("mean_accuracy", "mean_harmful"):
            assert ours[key] == {k: theirs[key][k] for k in ("value", "ci", "method")}
        for key in ("pass_all", "pass_any", "unstable"):
            assert ours[key] == {k: theirs[key][k] for k in ("k", "n", "value", "ci")}
        for key in ("model_failed_per_read", "unanswered_per_read"):
            assert ours[key] == theirs[key]
    for family in ("F1_accuracy", "F2_harm"):
        for pair, row in primary["families"][family].items():
            got = shown["families"][family][pair]
            assert (got["n"], got["diff"], got["lo"], got["hi"], got["holm"], got["p"]) == (
                row["n"],
                row["diff"],
                row["bootstrap"]["lo"],
                row["bootstrap"]["hi"],
                row["holm"],
                row["signflip"]["p"],
            )
    stability = primary["families"]["F3_stability"]
    if stability is None:
        assert shown["families"]["F3_stability"] is None
    else:
        for pair, row in stability.items():
            for key in ("n", "b", "c", "diff", "midp", "exact_p", "bonett_price", "holm"):
                assert shown["families"]["F3_stability"][pair][key] == row[key]
    for pair, block in primary["noninferiority"].items():
        got = shown["noninferiority"][pair]
        assert (got["margin"], got["lo"], got["hi"], got["estimate"], got["errors"], got["decision"]) == (
            block["margin"],
            block["bound"]["lo"],
            block["bound"]["hi"],
            block["bound"]["estimate"],
            block["errors"],
            block["decision"],
        )
    for key in ("decisions", "decision_roles", "confirmatory"):
        assert shown[key] == primary[key], key
    assert [set(row) for row in shown["errors"]] == [ERROR_KEYS] * len(primary["errors"])
    assert shown["errors"] == [{k: row[k] for k in ERROR_KEYS} for row in primary["errors"]]
    settings = source["meta"]["settings"]
    assert shown["settings"] == {
        k: settings[k]
        for k in ("level", "alpha", "noninferiority_margin", "seed", "resamples", "signflip_draws")
    }
    assert (shown["model"], shown["date"], shown["methods"]) == (
        source["meta"]["model"],
        source["meta"]["date"],
        source["meta"]["methods"],
    )
    digest = hashlib.sha256((root / hf.FILES["prereg"]).read_bytes()).hexdigest()
    assert shown["prereg"]["file"] == hf.FILES["prereg"]
    assert shown["prereg"]["sha256"] == digest == source["meta"]["prereg"]["sha256"]
    assert shown["prereg"]["registered"] == prereg["registered"]
    assert shown["source"] == {
        "file": hf.FINAL_NAME,
        "sha256": hashlib.sha256((root / "evals" / "results" / hf.FINAL_NAME).read_bytes()).hexdigest(),
    }
    for block_name in ("page", "readme"):
        assert shown["sentences"][block_name] == [
            s._asdict() for s in final.coded(source, prereg, block=block_name, sources=named)
        ]
    sentences = prereg["sentences"]
    assert shown["layout"] == {
        "readme_block": sentences["readme_block"],
        "readme_layout": sentences["readme_layout"],
    }
    assert shown["views"] == _views()
    deviations = named["deviations"]
    assert [(row["id"], row["kind"]) for row in shown["deviations"]] == [
        (d["id"], d["kind"]) for d in deviations
    ]
    assert all("what" not in row and "evidence" not in row for row in shown["deviations"])
    assert shown["owner"] == {
        "labels": named["owner_labels"]["status"],
        "kappa": named["owner_kappa"]["status"],
    }
    if named["ask"] is None:
        assert shown["ask"] is None
    else:
        ask = named["ask"]
        assert shown["ask"]["runs"] == ask["consistency"]["runs"]
        assert shown["ask"]["strict"]["k"] == int(ask["r1"]["strict_accuracy"]["k"])
        assert shown["ask"]["harmful_any"]["k"] == int(ask["consistency"]["harmful_any"]["k"])
    endpoints = named["stress"]["endpoints"] if named["stress"] else None
    if endpoints is None:
        assert shown["stress"] is None
    else:
        for name_ in ("injection_targeted", "distractor_taken", "harmful_unflagged"):
            assert shown["stress"][name_] == {
                **{k: endpoints[name_][k] for k in ("n", "ordnung", "llm_rules_tool", "b", "c", "p")},
                "holm": endpoints["holm"][name_],
            }
    scam = named["e2e"]["metrics"]["all"]["scam"]
    assert shown["e2e"]["file"] == hf.E2E_NAME
    assert (shown["e2e"]["set_aside"], shown["e2e"]["scam_letters"]) == (
        scam["set_aside_obligations"],
        scam["scam_letters"],
    )
    assert shown["power"] == {
        family: {pair: row["power"] for pair, row in rows.items()}
        for family, rows in named["power"]["comparisons"].items()
    }

    def strings(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
        if isinstance(value, dict):
            for key, inner in value.items():
                if key not in ("sentences", "views", "layout", "methods", "consequence", "not_run"):
                    yield from strings(inner, f"{path}.{key}")
        elif isinstance(value, list):
            for inner in value:
                yield from strings(inner, path)
        elif isinstance(value, str):
            yield path, value

    # nothing but registered or templated words, codes, ids and numbers: no sentence of a letter can hide in it
    prose = [path for path, value in strings(shown) if len(value) >= 24 and value.count(" ") >= 3]
    assert prose == []


def test_a_final_in_pending_is_never_read(tmp_path: Path) -> None:
    """A checkpoint of the final run waits in ``evals/results/pending/`` until the publish branch moves it: the
    presenter reads ``evals/results`` alone, not its folders, so the outputs stay those of no final at all; and a final
    chart nothing renders is stale."""
    doc, _ = hf.scenario("good")
    read = hf.synthetic_read("holdout4", 1, 12)
    root = hf.final_root(
        tmp_path,
        None,
        prereg=hf.complete_prereg(builders.prereg()),
        extra=[
            (f"evals/results/pending/{hf.FINAL_NAME}", doc),
            ("evals/results/pending/2027-01-01-claude-sonnet-5-holdout4.json", read),
        ],
    )
    assert model.build(root / "evals" / "results") == model.build(hf.RESULTS)
    build.write(root)
    assert build.check(root) == []
    assert not (root / FINAL_SVGS[0]).exists()
    (root / FINAL_SVGS[0]).write_text("<svg/>\n", encoding="utf-8")
    assert build.check(root) == [FINAL_SVGS[0]]


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def test_a_sentence_the_rules_refuse_stops_the_write_and_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A registered sentence that cannot be said (the deviations file is missing; a decision its own interval and
    Holm p contradict) is refused, never written around: the command exits 2 and writes nothing."""
    doc, src = hf.scenario("good")
    without = dict(src, deviations=None)
    root = hf.final_root(tmp_path / "a", doc, sources=without, prereg=hf.complete_prereg(builders.prereg()))
    before = _tree(root)
    assert main(["--write", "--root", str(root)]) == 2
    assert "deviations" in capsys.readouterr().err
    assert _tree(root) == before and not (root / "docs").exists()
    contradicted = copy.deepcopy(doc)
    contradicted["primary"]["families"]["F1_accuracy"]["ordnung-vs-llm_only"]["holm"] = 0.9
    root = hf.final_root(
        tmp_path / "b", contradicted, sources=src, prereg=hf.complete_prereg(builders.prereg())
    )
    before = _tree(root)
    assert main(["--write", "--root", str(root)]) == 2
    assert "clear" in capsys.readouterr().err
    assert _tree(root) == before
    assert main(["--check", "--root", str(root)]) == 2


def _ask_run(repeat: int) -> dict[str, Any]:
    """One run of the held-out Ask set, as ``evals.ask`` writes it (what the presenter reads of it)."""
    return {
        "benchmark": "ask",
        "schema": 2,
        "set": "heldout",
        "repeat": repeat,
        "date": f"2026-12-0{repeat + 4}",
        "backend": "live",
        "recorded": None,
        "today": f"2026-12-0{repeat + 4}",
        "model": hf.MODEL,
        "summary": {},
        "questions": [],
        "attacks": [],
    }


def _ask_runs(src: dict[str, Any]) -> list[tuple[str, str]]:
    """The three held-out Ask runs, named as ``evals.ask`` names them, and listed in the Ask file of runs."""
    runs = [
        (
            f"2026-12-0{r + 4}-claude-sonnet-5-ask-heldout{'' if r == 1 else f'-r{r}'}.json",
            hf._text(_ask_run(r)),
        )
        for r in (1, 2, 3)
    ]
    src["ask"]["meta"]["inputs"] = [
        {
            "file": name,
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "repeat": r,
            "today": None,
            "date": None,
        }
        for r, (name, body) in enumerate(runs, 1)
    ]
    return runs


def test_every_final_companion_file_has_one_kind_and_role(tmp_path: Path) -> None:
    """Each file of the final run has one kind and one role, the ones ``evals.reproduce`` gives it, and is listed once:
    the Ask set's runs and its file of runs, the stress test, the end-to-end replay of the final letters, a re-scored
    holdout4 read, the replays of a read without the sender's Land and with the checks off. None of them reaches the
    pooled views, and the README's development-set Ask line stays the development set's."""
    doc, src = hf.scenario("good")
    rescored = hf.synthetic_read("holdout4", 1, 12)
    rescored["meta"]["backend"] = "replay"
    replay = {"model": hf.MODEL, "date": "2027-01-06", "repeat": 1, "backend": "replay"}
    companions = {
        hf.FINAL_NAME: ("analysis", "final"),
        hf.ASK_NAME: ("ask-final", "final"),
        hf.STRESS_NAME: ("stress", "final"),
        hf.E2E_NAME: ("e2e", "replay"),
        "2027-01-09-claude-sonnet-5-holdout4-rescored.json": ("run", "re-scored"),
        "2027-01-06-claude-sonnet-5-without-land-holdout4.json": ("without-land", "replay"),
        "2027-01-06-claude-sonnet-5-checks-ablated-holdout4.json": ("checks-ablated", "replay"),
    }
    runs = _ask_runs(src)
    companions |= {name: ("ask", "final") for name, _ in runs}
    others = [
        ("2027-01-09-claude-sonnet-5-holdout4-rescored.json", hf._text(rescored)),
        (
            "2027-01-06-claude-sonnet-5-without-land-holdout4.json",
            hf._text({"schema": "ordnung-eval-without-land/2", "meta": replay, "splits": {"holdout4": {}}}),
        ),
        (
            "2027-01-06-claude-sonnet-5-checks-ablated-holdout4.json",
            hf._text(
                {
                    "schema": "ordnung-eval-checks-ablated/1",
                    "meta": replay,
                    "splits": {"holdout4": {}},
                    "totals": {},
                }
            ),
        ),
    ]
    root = hf.final_root(
        tmp_path, doc, sources=src, prereg=hf.complete_prereg(builders.prereg()), reads=[*runs, *others]
    )
    results = root / "evals" / "results"
    for name, (kind, role) in companions.items():
        data = json.loads((results / name).read_text(encoding="utf-8"))
        assert (model.kind_of(name, data), model.role_of(name, data)) == (kind, role), name
        assert reproduce._kind(name, data) == (kind, role), name
    built, pooled = model.build(results), model.build(hf.RESULTS)
    listed = [row["file"] for row in built["files"]]
    assert sorted(listed) == sorted(path.name for path in results.glob("*.json") if path.name != "INDEX.json")
    assert len(listed) == len(set(listed))
    roles = {row["file"]: row["role"] for row in built["files"]}
    assert {name: roles[name] for name in companions} == {
        name: role for name, (_, role) in companions.items()
    }
    for key in ("headline", "ask", "without_land", "ablation", "e2e", "llm_only_first_run"):
        assert built[key] == pooled[key], key
    assert text.ask_line(built) == text.ask_line(pooled)


def test_a_read_the_final_analysis_does_not_read_is_refused(tmp_path: Path) -> None:
    """A read of a final split is shown only through the analysis that reads it: one more read beside it, or an
    analysis that reads a file that is not there, is refused by name."""
    doc, src, reads = hf.realistic()
    more = ("2027-01-04-claude-sonnet-5-holdout4-r4.json", hf._text(hf.synthetic_read("holdout4", 4, 12)))
    prereg = hf.complete_prereg(builders.prereg())
    root = hf.final_root(tmp_path / "a", doc, sources=src, prereg=prereg, reads=[*reads, more])
    with pytest.raises(PresentError, match=r"holdout4-r4\.json.*does not read"):
        model.build(root / "evals" / "results")
    root = hf.final_root(tmp_path / "b", doc, sources=src, prereg=prereg, reads=reads[1:])
    with pytest.raises(PresentError, match=reads[0][0]):
        model.build(root / "evals" / "results")
    # a final split's read with no final analysis at all
    root = hf.final_root(tmp_path / "c", None, reads=reads[:1])
    with pytest.raises(PresentError, match="final analysis"):
        model.build(root / "evals" / "results")


def test_an_input_whose_bytes_changed_is_refused_for_the_final(tmp_path: Path) -> None:
    doc, src, reads = hf.realistic()
    name, body = reads[1]
    changed = [*reads[:1], (name, body + "\n"), *reads[2:]]
    root = hf.final_root(
        tmp_path, doc, sources=src, prereg=hf.complete_prereg(builders.prereg()), reads=changed
    )
    with pytest.raises(PresentError, match=re.escape(name)):
        model.build(root / "evals" / "results")


def test_a_pre_registration_other_than_the_analysed_one_is_refused(tmp_path: Path) -> None:
    """The final analysis names the pre-registration it was run under by its hash: another file in its place is
    refused, and so is one without what the provenance shows (the registered commits and days, the data's hashes)."""
    root = hf.scenario_root(tmp_path / "a", "good")
    path = root / hf.FILES["prereg"]
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(data | {"id": "another"}), encoding="utf-8")
    with pytest.raises(PresentError, match="pre-registration"):
        model.build(root / "evals" / "results")
    doc, src = hf.scenario("good")
    bare = hf.complete_prereg(builders.prereg())
    del bare["registered"]["commit_a"]
    root = hf.final_root(tmp_path / "b", doc, sources=src, prereg=bare)
    with pytest.raises(PresentError, match="commit_a"):
        model.build(root / "evals" / "results")


def test_the_ask_runs_and_the_deviations_are_the_ones_the_final_files_name(tmp_path: Path) -> None:
    """A held-out Ask run is shown only through the Ask file of runs that lists it with its hash; the deviations the
    final analysis applied are the deviations file's, by id, and its hash is the file the analysis read."""
    prereg = hf.complete_prereg(builders.prereg())
    doc, src = hf.scenario("good")
    runs = _ask_runs(src)
    root = hf.final_root(tmp_path / "listed", doc, sources=src, prereg=prereg, reads=runs)
    assert model.build(root / "evals" / "results")["final"] is not None
    root = hf.final_root(
        tmp_path / "unlisted",
        doc,
        sources=src,
        prereg=prereg,
        reads=[*runs, ("2026-12-09-claude-sonnet-5-ask-heldout-r4.json", hf._text(_ask_run(4)))],
    )
    with pytest.raises(PresentError, match=r"ask-heldout-r4\.json"):
        model.build(root / "evals" / "results")
    doc_u, src_u = hf.scenario("undecided")  # no Ask file of runs: the runs are cut by deviations
    root = hf.final_root(tmp_path / "no-file", doc_u, sources=src_u, prereg=prereg, reads=runs[:1])
    with pytest.raises(PresentError, match="file of runs"):
        model.build(root / "evals" / "results")
    unknown = copy.deepcopy(doc)
    unknown["meta"]["deviations"] = [{"id": "D009", "kind": "retake"}]
    root = hf.final_root(tmp_path / "ids", unknown, sources=src, prereg=prereg)
    with pytest.raises(PresentError, match="D009"):
        model.build(root / "evals" / "results")
    other = copy.deepcopy(doc)
    other["meta"]["frozen_check"] = {"deviations_file": {"file": "x", "sha256": "0" * 64, "entries": 0}}
    other["meta"]["deviations"] = []
    root = hf.final_root(tmp_path / "hash", other, sources=src, prereg=prereg)
    with pytest.raises(PresentError, match="deviations"):
        model.build(root / "evals" / "results")
    same = copy.deepcopy(other)
    digest = hashlib.sha256(hf._text(src["deviations"]).encode("utf-8")).hexdigest()
    same["meta"]["frozen_check"]["deviations_file"]["sha256"] = digest
    root = hf.final_root(tmp_path / "same", same, sources=src, prereg=prereg)
    assert model.build(root / "evals" / "results")["final"] is not None


def test_a_final_is_presented_from_a_checkout_only(tmp_path: Path) -> None:
    """``final.published`` reads a checkout's ``evals/results`` and ``evals/preregistration``: a final run in a
    results folder of another layout is refused rather than shown without its pre-registration."""
    doc, _ = hf.scenario("good")
    (tmp_path / hf.FINAL_NAME).write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(PresentError, match="evals/results"):
        model.build(tmp_path)


# --------------------------------------------------------------------------------------------------
# The README block
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", [*hf.SCENARIO_IDS, "realistic"])
def test_the_readme_block_is_the_registered_layout(made: Callable[[str], Made], name: str) -> None:
    """The README's block is ``final.readme_block`` of the README sentences under the registered templates, line for
    line, within the registered budget, its chart line in the registered frame, and every README slot said whatever
    its result."""
    root, _, outputs = made(name)
    source, prereg, named = hf.published(root)
    said = final.coded(source, prereg, block="readme", sources=named)
    readme = outputs["README.md"]
    assert final.readme_problems(readme, said, prereg["sentences"]) == []
    block = _block(readme)
    assert len(block) <= final.README_BLOCK_MAX_LINES
    (picture,) = [line for line in block if line.startswith("<picture>")]
    assert final._is_picture(picture)
    assert all(len(line) <= final.README_LINE_MAX for line in block if line != picture)
    flat = _flat(" ".join(block))
    for slot in prereg["sentences"]["readme_block"]:
        texts = [s.text for s in said if s.slot == slot]
        assert texts and all(_flat(t) in flat for t in texts), slot


def test_the_final_chart_line_fits_its_frame_with_four_digit_numbers(made: Callable[[str], Made]) -> None:
    """The README's chart is the final run's: light and dark SVGs under docs/assets (the PyPI rewrite's pattern), alt
    text naming every value; with every number at four digits it stays in the frame and its maximum."""
    for name in ("good", "one_read"):
        (picture,) = [
            line for line in _block(made(name).outputs["README.md"]) if line.startswith("<picture>")
        ]
        assert 'srcset="docs/assets/eval-final-dark.svg"' in picture
        assert 'src="docs/assets/eval-final-light.svg"' in picture
        assert re.fullmatch(r"eval-[a-z-]+-(?:light|dark)\.svg", "eval-final-light.svg")
        worst = re.sub(r"\d+\.\d", "100.0", picture)
        worst = re.sub(r"(?<![\d.])\d+(?![\d.])", "9999", worst)
        assert final._is_picture(worst) and len(worst) <= final.README_PICTURE_MAX, len(worst)


def test_the_readme_outside_the_block_is_unchanged_with_a_final(made: Callable[[str], Made]) -> None:
    def outside(readme: str) -> tuple[str, str]:
        before, rest = readme.split(BEGIN, 1)
        return before, rest.split(END, 1)[1]

    readme = made("bad").outputs["README.md"]
    assert outside(readme) == outside((hf.ROOT / "README.md").read_text(encoding="utf-8"))
    assert len(readme.splitlines()) < 250


# --------------------------------------------------------------------------------------------------
# docs/evals.md and the history page
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", [*hf.SCENARIO_IDS, "realistic"])
def test_the_page_s_final_section_is_the_page_sentences_in_order(
    made: Callable[[str], Made], name: str
) -> None:
    """docs/evals.md's final section, between ``final.PAGE_BEGIN`` and ``final.PAGE_END`` under "6.1 The final run",
    is every registered page sentence in ``page_block`` order and nothing else."""
    root, _, outputs = made(name)
    source, prereg, named = hf.published(root)
    coded = final.coded(source, prereg, block="page", sources=named)
    report = outputs["docs/evals.md"]
    assert final.page_problems(report, [s.text for s in coded]) == []
    heading = report.index("\n### 6.1 The final run\n")
    assert (
        heading < report.index(final.PAGE_BEGIN) < report.index(final.PAGE_END) < report.index("\n### 6.2 ")
    )
    quiet = {"limitations.reads"} if source["primary"]["reads"] == 1 else set()
    assert {s.slot for s in coded} == set(prereg["sentences"]["page_block"]) - quiet


def test_the_card_says_pre_registered_with_file_and_hash(made: Callable[[str], Made]) -> None:
    """With a final, the evaluation card names the pre-registration (its file and hash, the freeze), the reads used of
    those registered, and the sources: the final analysis and every read it reads; it never says "not pre-registered"
    nor that the run is still to be pre-registered."""
    from evals.present import views

    for name in ("good", "two_reads", "realistic"):
        root, _, outputs = made(name)
        source, prereg, _ = hf.published(root)
        card = _card(outputs["docs/evals.md"])
        digest = hashlib.sha256((root / hf.FILES["prereg"]).read_bytes()).hexdigest()
        assert hf.FILES["prereg"] in card["Pre-registration"] and digest[:12] in card["Pre-registration"]
        assert prereg["registered"]["freeze_sha"][:12] in card["Pre-registration"]
        whole = " ".join(card.values())
        assert "not pre-registered" not in whole and "pre-registered before it is recorded" not in whole
        primary = source["primary"]
        assert card["Reads"] == views.fill(
            views.load(),
            "card.reads",
            used=len(primary["reads_used"]),
            registered=primary["reads_registered"],
        )
        assert f"`{hf.FINAL_NAME}`" in card["Sources"]
        for row in source["meta"]["inputs"]:
            assert f"`{row['file']}`" in card["Sources"]
        assert [key for key in card] == [
            "Task",
            "Model",
            "Data",
            "Primary metric",
            "Safety metric",
            "Held-out protocol",
            "Pre-registration",
            "Reads",
            "Intervals",
            "Replay",
            "Sources",
            "Newest recording",
        ]


def test_the_report_keeps_its_anchors_with_a_final(made: Callable[[str], Made]) -> None:
    """Other pages link into docs/evals.md by its headings' anchors, and the registered README link names
    ``#15-reproduce``: the report with a final keeps every section of today's, in order, and every in-page link
    resolves."""
    report = made("good").outputs["docs/evals.md"]
    today = (hf.ROOT / "docs" / "evals.md").read_text(encoding="utf-8")

    def headings(page: str) -> list[str]:
        return [line for line in page.splitlines() if line.startswith("## ")]

    assert headings(report)[: len(headings(today))] == headings(today)
    anchors = {text.slug(line.lstrip("#").strip()) for line in report.splitlines() if line.startswith("#")}
    for anchor in (
        "15-reproduce",
        "4-conditions-and-baselines",
        "8-ablations",
        "14-limitations",
        "6-results",
        "64-the-app-as-it-ships-without-the-senders-land",
    ):
        assert anchor in anchors, anchor
    for target in re.findall(r"\]\(#([^)]+)\)", report):
        assert target in anchors, target
    assert "docs/evals.md#15-reproduce" in final.load_templates()["readme_layout"]["link"]


@pytest.mark.parametrize(
    ("owner", "code"),
    [
        ("pending", "owner.pending"),
        ("labels", "owner.labels_done"),
        ("kappa", "owner.kappa_done"),
        ("done", "owner.done"),
        (None, "owner.pending"),
    ],
)
def test_the_owner_sentence_is_pending_until_the_files_say_done(
    tmp_path: Path, owner: str | None, code: str
) -> None:
    """The owner's checks are said pending until their files say done; a file not there yet is pending."""
    doc, src = hf.complete(builders.good(), builders.no_set_aside(builders.sources(owner=owner or "pending")))
    if owner is None:
        src["owner_labels"] = src["owner_kappa"] = None
    root = hf.final_root(tmp_path, doc, sources=src, prereg=hf.complete_prereg(builders.prereg()))
    built = model.build(root / "evals" / "results")
    (sentence,) = [s for s in built["final"]["sentences"]["page"] if s["slot"] == "owner"]
    assert sentence["code"] == code
    status = {"labels": "pending", "kappa": "pending"}
    if owner in ("labels", "done"):
        status["labels"] = "done"
    if owner in ("kappa", "done"):
        status["kappa"] = "done"
    assert built["final"]["owner"] == status
    report = text.report(built)
    between = report.split(final.PAGE_BEGIN, 1)[1].split(final.PAGE_END, 1)[0]
    assert _flat(sentence["text"]) in _flat(between)


def test_a_rescored_final_split_file_is_a_history_row_only(tmp_path: Path) -> None:
    """A read of a final split replayed with later code (a fix after the run) is a re-scored row of the history page,
    not held out; the final run, its order and its report stay as they are."""
    doc, src, reads = hf.realistic()
    prereg = hf.complete_prereg(builders.prereg())
    rescored = json.loads(reads[0][1])
    rescored["meta"]["backend"] = "replay"
    name = "2027-01-09-claude-sonnet-5-holdout4-rescored.json"
    plain = model.build(
        hf.final_root(tmp_path / "a", doc, sources=src, prereg=prereg, reads=reads) / "evals" / "results"
    )
    root = hf.final_root(
        tmp_path / "b", doc, sources=src, prereg=prereg, reads=[*reads, (name, hf._text(rescored))]
    )
    built = model.build(root / "evals" / "results")
    assert built["final"] == plain["final"] and built["order"] == plain["order"]
    assert [row["role"] for row in built["files"] if row["file"] == name] == ["re-scored"]
    rows = [line for line in text.history(built, "# Legacy\n").splitlines() if f"`{name}`" in line]
    assert len(rows) == 1 and "| re-scored |" in rows[0]
    assert name not in text.report(built)
    assert text.report(built) == text.report(plain)


def test_the_history_lists_every_results_file_once_with_a_final(made: Callable[[str], Made]) -> None:
    root, _, outputs = made("realistic")
    rows = [line for line in outputs["docs/evals-history.md"].splitlines() if line.startswith("| 20")]
    names = sorted(
        path.name for path in (root / "evals" / "results").glob("*.json") if path.name != "INDEX.json"
    )
    assert sorted(re.search(r"`([^`]+)`", row).group(1) for row in rows) == names  # type: ignore[union-attr]
    views = _views()["templates"]
    for name, kind in ((hf.ASK_NAME, "ask-final"), (hf.STRESS_NAME, "stress")):
        (row,) = [row for row in rows if f"`{name}`" in row]
        assert f"| {views[f'history.kind.{kind}']['text']} |" in row and "| final |" in row


# --------------------------------------------------------------------------------------------------
# --check, determinism, the page
# --------------------------------------------------------------------------------------------------


def test_the_final_outputs_are_the_no_final_ones_and_the_final_chart(made: Callable[[str], Made]) -> None:
    """With a final, ``--write`` writes today's outputs and the final run's chart; with none, exactly today's."""
    _, doc, outputs = made("bad")
    assert build.output_paths(doc) == FINAL_OUTPUTS and set(outputs) == set(FINAL_OUTPUTS)
    assert charts.names(doc) == (*charts.NAMES, "final") and charts.committed(doc) == (
        *charts.COMMITTED,
        "final",
    )
    pooled = model.build(hf.RESULTS)
    assert build.output_paths(pooled) == build.OUTPUT_PATHS
    assert charts.names(pooled) == charts.NAMES and charts.committed(pooled) == charts.COMMITTED


@pytest.fixture(scope="module")
def written(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = hf.scenario_root(tmp_path_factory.mktemp("written"), "bad")
    build.write(root)
    return root


@pytest.mark.parametrize("relative", FINAL_OUTPUTS)
def test_check_covers_every_final_output_and_fails_after_a_one_character_edit(
    written: Path, relative: str
) -> None:
    assert build.check(written) == []
    path = written / relative
    original = path.read_bytes()
    middle = original.index(b"Final run, pre-registered") if relative == "README.md" else len(original) // 2
    path.write_bytes(
        original[:middle] + (b"x" if original[middle : middle + 1] != b"x" else b"y") + original[middle + 1 :]
    )
    try:
        assert build.check(written) == [relative]
    finally:
        path.write_bytes(original)


def test_two_final_renders_are_byte_identical_and_hold_no_machine_path(
    made: Callable[[str], Made], tmp_path: Path
) -> None:
    root, _, outputs = made("realistic")
    assert build.outputs(root) == outputs
    elsewhere = hf.realistic_root(tmp_path)
    assert build.outputs(elsewhere) == outputs
    for relative, content in outputs.items():
        for mark in (str(root), str(elsewhere), str(hf.ROOT), str(Path.home()) + "/"):
            assert mark not in content, (relative, mark)
        if (
            relative != "docs/evals-history.md"
        ):  # the page of 0.3.0 shows `--results-dir /tmp/holdout` as it was
            for mark in PATH_MARKS:
                assert mark not in content, (relative, mark)


def test_the_page_with_a_final_draws_its_chart_and_passes_its_check(
    made: Callable[[str], Made], tmp_path: Path
) -> None:
    """The report page of a final run holds the final chart with its table and CSV, keeps the pooled chart under
    6.2, writes the README's final SVGs for PyPI, shows no marker line, and passes its own check."""
    _, doc, outputs = made("good")
    out = tmp_path / "site"
    site.build_site(doc, out)
    assert site.check_site(out, doc, forbidden=site.dataset_sentences()) == []
    page = (out / "index.html").read_text(encoding="utf-8")
    assert '<figure id="final">' in page and (out / "final.csv").is_file()
    for theme in ("light", "dark"):
        assert (out / f"eval-final-{theme}.svg").read_text(encoding="utf-8") == outputs[
            f"docs/assets/eval-final-{theme}.svg"
        ]
    assert final.PAGE_BEGIN not in page and final.PAGE_END not in page


# --------------------------------------------------------------------------------------------------
# The templates, the code's own words, the synthetic finals
# --------------------------------------------------------------------------------------------------


def test_the_views_templates_are_well_formed() -> None:
    """``evals/present/templates/views.json`` holds every word the final path adds beside the registered sentences:
    each template declares its placeholders, holds no number outside them and no model id but ``{model}``."""
    from evals.present import views

    loaded = views.load()
    assert loaded["schema"] == views.SCHEMA and views.check(loaded) == []

    def problems(text_: str, fields: list[str]) -> list[str]:
        broken = copy.deepcopy(loaded)
        broken["templates"]["card.reads"] = {"text": text_, "fields": fields}
        return views.check(broken)

    assert problems("{used} of {registered} reads", ["used", "registered"]) == []
    assert problems("{used} of 3 reads", ["used"])
    assert problems("{used} of {registered} reads", ["used"])
    assert problems("{used} reads", ["used", "registered"])
    assert problems("read by claude-" + "sonnet" + "-4", [])
    assert problems("read by {model}", ["model"]) == []
    filled = views.fill(loaded, "card.reads", used=2, registered=3)
    assert isinstance(filled, views.Filled) and filled.key == "card.reads" and "2" in filled and "3" in filled
    with pytest.raises(PresentError, match=r"no\.such\.key"):
        views.fill(loaded, "no.such.key")
    with pytest.raises(PresentError, match="registered"):
        views.fill(loaded, "card.reads", used=2)


#: The modules of the final path: every word they show is a template's.
FINAL_MODULES = ("finalrun.py", "views.py", "finaltext.py", "finalcharts.py")
_PROSE = re.compile(r"[A-Za-z]{3,} [A-Za-z]{3,}")


def _exempt(tree: ast.Module) -> set[int]:
    """The string constants that are no shown text: docstrings, the messages of a raise, and a check's problems."""
    exempt: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                exempt.add(id(first.value))
        shown: ast.AST | None = None
        if isinstance(node, ast.Raise):
            shown = node
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("append", "extend")
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "problems"
        ):
            shown = node
        if shown is not None:
            exempt |= {id(inner) for inner in ast.walk(shown)}
    return exempt


def test_the_final_modules_hold_no_prose_literal() -> None:
    """The final path's code writes no words of its own: every string in it that holds two words is a docstring, an
    error's message or a check's problem (so a reader's text comes from views.json or the registered sentences)."""
    for name in FINAL_MODULES:
        source = (hf.ROOT / "evals" / "present" / name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        exempt = _exempt(tree)
        found = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in exempt
            and _PROSE.search(node.value)
        ]
        assert found == [], (name, found)


def _paths(value: Any, path: str = "") -> set[str]:
    """Every key path of a document, list lengths ignored, pairs and conditions named generically."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, inner in value.items():
            key = re.sub(r"^ordnung-vs-.*", "<pair>", key)
            key = re.sub(r"^(ordnung|llm_only|llm_rules_text|llm_rules_tool)$", "<cond>", key)
            found |= {f"{path}.{key}"} | _paths(inner, f"{path}.{key}")
    elif isinstance(value, list):
        found.add(path + "[]")
        for inner in value:
            found |= _paths(inner, path + "[]")
    return found


#: What the presenter reads of a final analysis (``evals/present/finalrun.py``).
PRESENTED = (
    ".meta.kind",
    ".meta.model",
    ".meta.date",
    ".meta.prereg",
    ".meta.settings.level",
    ".meta.settings.alpha",
    ".meta.settings.noninferiority_margin",
    ".meta.settings.seed",
    ".meta.settings.resamples",
    ".meta.settings.signflip_draws",
    ".meta.methods",
    ".primary.split",
    ".primary.reads",
    ".primary.reads_registered",
    ".primary.reads_used",
    ".primary.reads_missing",
    ".primary.items",
    ".primary.letters",
    ".primary.clusters",
    ".primary.not_run",
    *(
        f".primary.conditions.<cond>.{key}"
        for key in (
            "exact_per_read",
            "harmful_per_read",
            "late_per_read",
            "mean_accuracy",
            "mean_harmful",
            "pass_all",
            "pass_any",
            "unstable",
            "model_failed_per_read",
            "unanswered_per_read",
        )
    ),
    ".primary.families",
    ".primary.noninferiority",
    ".primary.decisions",
    ".primary.decision_roles",
    ".primary.confirmatory",
    ".primary.errors",
    ".secondary.newkinds.items",
    ".secondary.newkinds.letters",
    ".secondary.newkinds.clusters",
    ".secondary.newkinds.conditions.<cond>.items",
    ".secondary.newkinds.conditions.<cond>.exact",
    ".secondary.newkinds.conditions.<cond>.harmful",
    ".sensitivities",
    ".labels",
)


def test_the_completed_builders_have_the_real_analysis_shape() -> None:
    """A hand-built final, completed, has every key path a real ``evals.analysis`` final analysis has where the
    presenter reads one, and no key a real one lacks: the completion cannot drift from the analysis."""
    real = hf.real()
    completed, _ = hf.scenario("good")

    def presented(paths: set[str]) -> set[str]:
        return {
            path
            for path in paths
            if any(path == p or path.startswith((p + ".", p + "[]")) for p in PRESENTED)
        }

    assert presented(_paths(completed)) == presented(_paths(real))
    assert _paths(completed) <= _paths(real)
    for name in hf.SCENARIO_IDS:
        doc, _ = hf.scenario(name)
        newkinds = doc["secondary"]["newkinds"]
        if "not_recorded" in newkinds:
            assert set(newkinds["not_recorded"]) == {"read", "kinds", "deviations"}, name


def test_no_presenter_test_writes_under_evals_results_or_preregistration() -> None:
    """The synthetic finals live in temporary folders: after the presenter's tests the repository's results and
    pre-registration folders are as committed."""
    result = subprocess.run(
        ["git", "-C", str(hf.ROOT), "status", "--porcelain", "--", "evals/results", "evals/preregistration"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("not a git checkout")
    assert result.stdout == ""
