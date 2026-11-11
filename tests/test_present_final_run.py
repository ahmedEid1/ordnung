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
import html
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from evals import reproduce
from evals.present import (
    BEGIN,
    END,
    PresentError,
    build,
    charts,
    final,
    finalcharts,
    finalrun,
    finaltext,
    fmt,
    model,
    palette,
    site,
    text,
    views,
)
from evals.present.__main__ import main

import helpers_final as hf
import test_present_final as builders

#: what a path of the building computer starts with (as tests/test_present.py)
PATH_MARKS = ("/home/", "/Users/", "/root/", "/tmp/", "\\Users\\")
#: The final run's charts with three reads: the headline, the differences and the stability over the reads.
FINAL_CHARTS = ("final", "final-differences", "final-stability")
FINAL_SVGS = tuple(
    f"docs/assets/eval-{name}-{theme}.svg" for name in FINAL_CHARTS for theme in ("light", "dark")
)
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
    not held out; the final run, its order and its report stay as they are (but for the provenance's hash of
    presentation.json, which lists every results file)."""
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

    def unhashed(doc: dict[str, Any]) -> str:
        digest = hashlib.sha256(model.dumps(doc).encode("utf-8")).hexdigest()
        report = text.report(doc)
        assert report.count(f"`{digest}`") == 1
        return report.replace(f"`{digest}`", "`presentation.json`")

    assert unhashed(built) == unhashed(plain)


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


def test_the_final_outputs_are_the_no_final_ones_and_the_final_charts(made: Callable[[str], Made]) -> None:
    """With a final, ``--write`` writes today's outputs and the final run's charts (the stability over the reads only
    with two reads or more); with none, exactly today's."""
    _, doc, outputs = made("bad")
    assert build.output_paths(doc) == FINAL_OUTPUTS and set(outputs) == set(FINAL_OUTPUTS)
    assert charts.names(doc) == (*charts.NAMES, *FINAL_CHARTS)
    assert charts.committed(doc) == (*charts.COMMITTED, *FINAL_CHARTS)
    one = made("one_read").doc
    assert charts.names(one) == charts.committed(one) == (*charts.NAMES, "final", "final-differences")
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


# --------------------------------------------------------------------------------------------------
# The final run's charts: the differences (a forest) and how steady the dates are over the reads
# --------------------------------------------------------------------------------------------------

#: Each comparison of the forest, and the registered slot whose sentence prints its difference and interval.
SLOTS = {
    ("F1_accuracy", "llm_only"): "head",
    ("F1_accuracy", "llm_rules_text"): "rules_text",
    ("F1_accuracy", "llm_rules_tool"): "agent",
    **{("F2_harm", baseline): f"f2.{baseline}" for baseline in final.BASELINES},
}
#: A difference or an interval's end in points, as the registered sentences print it (``final._formatted``).
_POINTS = re.compile(r"[+−]\d+\.\d")
#: The final charts a document draws beside today's.
_DRAWN = ("final", "final-differences", "final-stability")


def _points(value: float) -> str:
    return final._formatted(value, "points", "test")


def _slot_text(doc: dict[str, Any], slot: str) -> str:
    return " ".join(s["text"] for s in doc["final"]["sentences"]["page"] if s["slot"] == slot)


def _values(svg: str) -> str:
    return html.unescape(re.search(r"<desc[^>]*>(.*?)</desc>", svg, re.S).group(1))  # type: ignore[union-attr]


def _final_charts(doc: dict[str, Any]) -> tuple[str, ...]:
    return tuple(name for name in charts.names(doc) if name in charts.FINAL_NAMES)


def _baselines(doc: dict[str, Any]) -> list[str]:
    return [c for c in doc["order"] if c != "ordnung"]


@pytest.mark.parametrize("name", ["good", "bad", "undecided", "not_confirmed", "realistic"])
def test_the_forest_chart_s_numbers_are_the_sentences_numbers(made: Callable[[str], Made], name: str) -> None:
    """The forest of the final run, Ordnung minus each baseline for exact dates and for late or missed ones, shows
    each comparison's difference and bootstrap interval in the format its registered sentence prints them, beside
    its sign-flip and Holm p; the agent's sentence prints the non-inferiority bound, which the statistics show."""
    doc = made(name).doc
    shown = doc["final"]
    _, rows = charts.table("final-differences", doc)
    pairs = [(family, b) for family in ("F1_accuracy", "F2_harm") for b in _baselines(doc)]
    assert [row[0] for row in rows] == [palette.LABELS[b] for _, b in pairs]
    for (family, baseline), row in zip(pairs, rows, strict=True):
        pair = shown["families"][family][f"ordnung-vs-{baseline}"]
        numbers = _POINTS.findall(row[2])
        said = _POINTS.findall(_slot_text(doc, SLOTS[(family, baseline)]))
        assert numbers[0] == said[0] == _points(pair["diff"]), (family, baseline)
        if pair["lo"] == pair["hi"] == 0:
            assert numbers == [_points(pair["diff"])]
        else:
            assert numbers == [_points(pair["diff"]), _points(pair["lo"]), _points(pair["hi"])]
            if (family, baseline) != ("F1_accuracy", final.AGENT):
                assert numbers == said[:3], (family, baseline)
        assert row[3:5] == [fmt.p_value(pair["p"]), fmt.p_value(pair["holm"])]
    bound = shown["noninferiority"][f"ordnung-vs-{final.AGENT}"]
    assert _POINTS.findall(_slot_text(doc, "agent"))[1:3] == [_points(bound["lo"]), _points(bound["hi"])]
    assert "[+0.0, +0.0]" not in " ".join(cell for row in rows for cell in row)


def test_the_stability_chart_is_drawn_from_two_reads_and_never_from_one(made: Callable[[str], Made]) -> None:
    """How steady the dates are over the reads (right in every read, and changed between reads, each with its
    Clopper–Pearson interval) is drawn from two reads or more, with the analysis's numbers; with one read there is no
    such chart, only the registered sentence that it was not measured."""
    for name in ("good", "two_reads"):
        _, doc, outputs = made(name)
        assert "final-stability" in charts.names(doc) and "final-stability" in charts.committed(doc)
        assert "docs/assets/eval-final-stability-light.svg" in build.output_paths(doc)
        _, rows = charts.table("final-stability", doc)
        for condition, row in zip(doc["order"], rows, strict=True):
            summary = doc["final"]["conditions"][condition]
            assert row[0] == palette.LABELS[condition]
            for cells, rate in ((row[1:4], summary["pass_all"]), (row[4:7], summary["unstable"])):
                assert cells == [fmt.pct(rate["value"]), fmt.kn(rate), fmt.ci(rate["ci"])]
        final_run = _section(outputs["docs/evals.md"], "6. Results").split("\n### 6.2 ", 1)[0]
        assert "assets/eval-final-stability-light.svg" in final_run
    _, doc, outputs = made("one_read")
    assert "final-stability" not in charts.names(doc) and "final-stability" not in charts.committed(doc)
    assert "eval-final-stability" not in outputs["docs/evals.md"]
    assert not [path for path in outputs if "final-stability" in path]
    with pytest.raises(PresentError):
        charts.svg("final-stability", doc)
    (sentence,) = [s for s in doc["final"]["sentences"]["page"] if s["slot"] == "stability"]
    assert sentence["code"] == "stability.not_run"


@pytest.mark.parametrize("name", ["good", "two_reads", "realistic"])
def test_the_hero_shows_each_read_and_the_mean_with_its_interval(
    made: Callable[[str], Made], name: str
) -> None:
    """The headline chart shows, per condition, the mean over the reads with its interval (exact dates and late or
    missed ones) and each read alone as a hollow ring, every value named in its description."""
    doc = made(name).doc
    shown = doc["final"]
    svg = charts.svg("final", doc, "light")
    rings = re.findall(r'<circle [^>]*style="fill:none;[^"]*"><title>[^<]+</title>', svg)
    assert len(rings) == 2 * len(final.CONDITIONS) * len(shown["reads_used"])
    assert len(re.findall(r"stroke-linecap:round", svg)) == 2 * len(final.CONDITIONS)
    description = _values(svg)
    for condition in doc["order"]:
        summary = shown["conditions"][condition]
        for mean, per_read in (("mean_accuracy", "exact_per_read"), ("mean_harmful", "harmful_per_read")):
            assert fmt.pct(summary[mean]["value"]) in description
            assert fmt.ci(summary[mean]["ci"]) in description
            assert " · ".join(fmt.num(rate["value"]) for rate in summary[per_read]) in description


@pytest.mark.parametrize("name", _DRAWN)
@pytest.mark.parametrize("theme", ["light", "dark", "css"])
@pytest.mark.parametrize("narrow", [False, True])
def test_every_final_chart_names_itself_every_value_and_has_its_table(
    made: Callable[[str], Made], name: str, theme: str, narrow: bool
) -> None:
    """Each final chart has a title, a description naming every condition and value, a title on every mark and a
    table twin with the same numbers, in light, dark and the page's CSS colours, wide and narrow."""
    doc = made("good").doc
    svg = charts.svg(name, doc, theme, narrow=narrow)
    assert svg.startswith("<svg ") and 'role="img"' in svg and "aria-labelledby=" in svg
    title = re.search(r'<title id="[^"]+">([^<]+)</title>', svg)
    assert title and html.unescape(title.group(1)) == charts.title(name, doc)
    description = _values(svg)
    assert description == charts.description(name, doc)
    header, rows = charts.table(name, doc)
    assert rows and all(len(row) == len(header) for row in rows)
    unescaped = html.unescape(svg)
    for row in rows:
        assert row[0] in description, (name, row[0])
        for cell in row[1:]:
            plain = cell.replace("`", "")
            assert plain in description or plain in unescaped, (name, cell)
    titled = re.findall(r"<(?:circle|rect|polygon)[^>]*><title>[^<]+</title>", svg)
    assert len(titled) >= len(rows)
    series = {palette.LIGHT[c] for c in palette.CONDITIONS} | {palette.DARK[c] for c in palette.CONDITIONS}
    assert not [fill for fill in re.findall(r'<text[^>]*style="fill:([^;"]+)', svg) if fill in series]
    assert site.caption(name, doc) == finalcharts.caption(name, doc)


def test_every_final_chart_follows_the_final_order_and_draws_ordnung_last_when_last(
    made: Callable[[str], Made],
) -> None:
    """One row order on every chart, the final run's mean accuracy: when Ordnung's is the lowest, its row is the
    last of every final chart, drawn last, its label bold and its markers the size of everyone's."""
    doc = copy.deepcopy(made("bad").doc)
    conditions = doc["final"]["conditions"]
    lowest = min(summary["mean_accuracy"]["value"] for summary in conditions.values())
    conditions["ordnung"]["mean_accuracy"]["value"] = lowest - 0.01
    doc["order"] = finalrun.order(doc["final"])
    assert doc["order"][-1] == "ordnung"
    labels = [palette.LABELS[c] for c in doc["order"]]
    ordnung = palette.LIGHT["ordnung"]
    for name in _DRAWN:
        _, rows = charts.table(name, doc)
        expected = (
            [label for label in labels if label != "Ordnung"] * 2 if name == "final-differences" else labels
        )
        assert [row[0] for row in rows] == expected, name
        for narrow in (False, True):
            svg = charts.svg(name, doc, "light", narrow=narrow)
            drawn = [value for value in re.findall(r">([^<>]+)</text>", svg) if value in labels]
            once = [label for label in labels if label in drawn]
            assert once == [label for label in labels if label in set(expected)]
            assert drawn == once * (len(drawn) // len(once)), (name, narrow)
            markers = re.findall(
                r'<(?:circle|rect|polygon) [^>]*style="fill:(#[0-9a-f]{6});stroke:[^"]*', svg
            )
            sizes = set(re.findall(r'<circle [^>]*r="([\d.]+)" style="fill:#', svg))
            if name != "final-differences":
                assert markers[-1] == ordnung, (name, narrow)
                assert re.search(r'font-weight="600"[^>]*>Ordnung</text>', svg)
            assert len(sizes) <= 1, (name, sizes)


def test_no_interval_reads_plus_zero_to_plus_zero(made: Callable[[str], Made]) -> None:
    """When no deadline differs between Ordnung and a baseline (an interval of 0 to 0), the forest draws no interval
    and says so in words of its templates, never "[+0.0, +0.0]"."""
    doc = copy.deepcopy(made("good").doc)
    for family in ("F1_accuracy", "F2_harm"):
        doc["final"]["families"][family]["ordnung-vs-llm_rules_text"].update(diff=0.0, lo=0.0, hi=0.0)
    _, rows = charts.table("final-differences", doc)
    same = [row for row in rows if row[0] == palette.LABELS["llm_rules_text"]]
    assert len(same) == 2
    for row in same:
        assert row[2] == views.fill(doc["final"]["views"], "chart.final-differences.none", d=_points(0.0))
    shown = [cell for row in rows for cell in row]
    shown += [charts.description("final-differences", doc), finalcharts.caption("final-differences", doc)]
    for theme in ("light", "dark", "css"):
        for narrow in (False, True):
            svg = charts.svg("final-differences", doc, theme, narrow=narrow)
            shown.append(svg)
            if theme == "light":
                assert len(re.findall(r"stroke-linecap:round", svg)) == 2 * (len(final.BASELINES) - 1)
    for value in shown:
        assert "[+0.0, +0.0]" not in value and "+0.0 to +0.0" not in value


@pytest.mark.parametrize("name", ["good", "one_read", "realistic"])
def test_the_final_charts_are_small_and_byte_identical(made: Callable[[str], Made], name: str) -> None:
    """Every final chart renders the same bytes twice (and from presentation.json as written), stays under 40 KB,
    and keeps its narrow text at 12 px or more on a 288 px column."""
    doc = made(name).doc
    again = json.loads(model.dumps(doc))
    for chart in _final_charts(doc):
        for theme in ("light", "dark", "css"):
            for narrow in (False, True):
                svg = charts.svg(chart, doc, theme, narrow=narrow)
                assert svg == charts.svg(chart, again, theme, narrow=narrow), (chart, theme, narrow)
                assert len(svg.encode("utf-8")) <= 40_000, (chart, theme, narrow)
        svg = charts.svg(chart, doc, "css", narrow=True)
        width = float(re.search(r'viewBox="0 0 ([\d.]+) ', svg).group(1))  # type: ignore[union-attr]
        smallest = min(float(size) for size in re.findall(r'font-size="([\d.]+)"', svg))
        assert smallest * 288 / width >= 12, (chart, smallest)
    for relative, content in made(name).outputs.items():
        if relative.endswith(".svg"):
            assert len(content.encode("utf-8")) <= 40_000, relative


def _template_pattern(template: str) -> re.Pattern[str]:
    """A template as a pattern whose groups are its placeholders' values."""
    pattern, seen = "", set()
    for i, part in enumerate(re.split(r"\{([^{}]*)\}", template)):
        if i % 2 == 0:
            pattern += re.escape(part)
        elif part in seen:
            pattern += f"(?P={part})"
        else:
            seen.add(part)
            pattern += f"(?P<{part}>.+?)"
    return re.compile(pattern, re.S)


def test_every_final_caption_is_a_filled_view_template(made: Callable[[str], Made]) -> None:
    """Each final chart's "What this shows" is its view template filled with values only: numbers, and the code of a
    registered sentence, never a word chosen for the result."""
    templates = _views()["templates"]
    for name in ("good", "bad", "one_read", "realistic"):
        doc = made(name).doc
        for chart in _final_charts(doc):
            caption = finalcharts.caption(chart, doc)
            assert isinstance(caption, views.Filled) and caption.key == f"chart.{chart}.caption", chart
            match = _template_pattern(templates[caption.key]["text"]).fullmatch(caption)
            assert match, (chart, caption)
            for value in match.groupdict().values():
                assert not re.search(r"[A-Za-z]", value) or re.fullmatch(r"[a-z_]+(?:\.[a-z_]+)+", value), (
                    value
                )


# --------------------------------------------------------------------------------------------------
# The final report's sections: summary, results, statistics, failures, deviations, provenance
# --------------------------------------------------------------------------------------------------

#: The verdict table's rows: each registered slot that says a decision, and the analysis's key for it (harm against
#: the agent is described, not decided).
VERDICTS = (
    ("head", "beats_llm_only"),
    ("rules_text", "vs_llm_rules_text"),
    ("agent", "vs_llm_rules_tool"),
    ("f2.llm_only", "f2_vs_llm_only"),
    ("f2.llm_rules_text", "f2_vs_llm_rules_text"),
    ("f2.llm_rules_tool", None),
    ("stability", "more_stable_than_llm_only"),
)
#: The sections whose numbers are the earlier held-out splits' with a final run, each carrying that label.
POOLED_SECTIONS = (
    "8. Ablations",
    "9. Robustness",
    "10. Safety and selective prediction",
    "12. Cost and latency",
    "13. From a letter to a reminder",
)


def _table(blocks: list[text.Block], key: str) -> text.Table:
    """The one table among ``blocks`` whose caption is the view template ``key``."""
    (found,) = [
        block
        for block in blocks
        if isinstance(block, text.Table) and getattr(block.caption, "key", None) == key
    ]
    return found


def _no_words(value: str) -> bool:
    """Numbers, signs and ids or codes in backticks only."""
    return not re.search(r"[A-Za-z]", re.sub(r"`[^`]*`", "", value))


def _templated(value: str, said: list[str]) -> bool:
    """A view template filled, a registered sentence (or several), a condition's name, or no word at all."""
    if isinstance(value, views.Filled) or value in palette.LABELS.values():
        return True
    rest = value
    for sentence in sorted(said, key=len, reverse=True):
        rest = rest.replace(sentence, " ")
    return _no_words(rest)


def _shown(doc: dict[str, Any], blocks: list[text.Block]) -> Iterator[str]:
    """Every string a reader sees of ``blocks``: paragraphs, bullets, headings, tables, and each chart's title,
    description, caption and table."""
    for block in blocks:
        if isinstance(block, (text.Paragraph, text.Subheading)):
            yield block.text
        elif isinstance(block, text.Bullets):
            yield from block.items
        elif isinstance(block, text.Table):
            yield block.caption
            yield from block.header
            yield from (cell for row in block.rows for cell in row)
        elif isinstance(block, text.Chart):
            yield charts.title(block.name, doc)
            yield charts.description(block.name, doc)
            yield finalcharts.caption(block.name, doc)
            header, rows = charts.table(block.name, doc)
            yield from header
            yield from (cell for row in rows for cell in row)


@pytest.mark.parametrize("name", ["good", "bad", "one_read", "realistic"])
def test_the_final_report_s_prose_is_registered_or_templated(
    made: Callable[[str], Made], name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every string the final run adds to sections 1, 6.1 and 7 (and draws in its charts: titles, subtitles,
    headings, values, tooltips, footnotes, descriptions, captions) is a view template filled, a registered sentence,
    a condition's name, an id or code, or a number: nothing worded in code or after the results."""
    doc = made(name).doc
    said = [s["text"] for block in ("page", "readme") for s in doc["final"]["sentences"][block]]
    drawn: list[str] = []
    original = charts._dot_chart

    def capture(
        ident: str,
        theme: str,
        narrow: bool,
        title: str,
        subtitle: str,
        description: str,
        panels: Any,
        footnote: str,
    ) -> str:
        drawn.extend([title, subtitle, description, footnote])
        for panel in panels:
            drawn.append(panel.heading)
            for row in panel.rows:
                drawn.extend([row.shown, row.tip, *(tip for _, tip in row.rings)])
        return original(ident, theme, narrow, title, subtitle, description, panels, footnote)

    monkeypatch.setattr(charts, "_dot_chart", capture)
    for chart in _final_charts(doc):
        charts.svg(chart, doc, "light")
    assert drawn
    blocks = [*finaltext.summary(doc), *finaltext.final_run(doc), *finaltext.statistics(doc)]
    shown = list(_shown(doc, blocks))
    assert [value for value in [*shown, *drawn] if not _templated(value, said)] == []


@pytest.mark.parametrize("name", ["good", "bad", "one_read", "realistic"])
def test_the_verdict_table_shows_decision_codes_not_words(made: Callable[[str], Made], name: str) -> None:
    """The summary's verdict table has one row per pre-registered comparison, in the registered order: what it
    compares and how it is tested (view templates), its numbers, its role, the analysis's decision code and the code
    of the registered sentence that says it; no verdict in words of its own."""
    doc = made(name).doc
    shown = doc["final"]
    table = _table(finaltext.summary(doc), "verdict.caption")
    assert all(isinstance(cell, views.Filled) for cell in table.header)
    assert len(table.rows) == len(VERDICTS)
    page = shown["sentences"]["page"]
    for (slot, key), row in zip(VERDICTS, table.rows, strict=True):
        comparison, test, result, role, decision, sentence = row
        assert isinstance(comparison, views.Filled) and isinstance(test, views.Filled)
        assert isinstance(result, views.Filled) or _no_words(result), result
        codes = [
            s["code"]
            for s in page
            if s["slot"] == slot and s["code"].split(".")[1] not in ("intro", "deviations")
        ]
        assert sentence == f"`{codes[0]}`", slot
        if key is None:
            assert (role, decision) == ("—", "—")
            continue
        assert role == f"`{shown['decision_roles'][key]}`"
        value = shown["decisions"][key]
        expected = "—" if value is None else f"`{json.dumps(value) if isinstance(value, bool) else value}`"
        assert decision == expected, slot
    assert table.rows[0][3] == "`confirmatory`"


@pytest.mark.parametrize("name", ["good", "bad", "realistic"])
def test_the_gallery_lists_harmful_errors_first_by_id_only(made: Callable[[str], Made], name: str) -> None:
    """Section 11 opens with the final run's failures: every late or missed date first (every condition and read),
    then Ordnung's other wrong dates, in the page's row order; letter ids, reads and codes only. The earlier held-out
    splits' table follows under its own label."""
    _, doc, outputs = made(name)
    rank = {c: i for i, c in enumerate(doc["order"])}

    def harmful(row: dict[str, Any]) -> bool:
        return bool(row["outcome"] == "missed" or row["direction"] == "late")

    chosen = sorted(
        (row for row in doc["final"]["errors"] if harmful(row) or row["condition"] == "ordnung"),
        key=lambda row: (
            not harmful(row),
            rank[row["condition"]],
            row["read"],
            row["split"],
            row["entry_id"],
            row["item"],
        ),
    )
    assert chosen and harmful(chosen[0])
    table = _table(finaltext.gallery(doc), "gallery.caption")
    assert [row[0] for row in table.rows] == [f"`{row['entry_id']}`" for row in chosen]
    assert [row[1] for row in table.rows] == [str(row["read"]) for row in chosen]
    assert [row[2] for row in table.rows] == [palette.LABELS[row["condition"]] for row in chosen]
    for row in table.rows:
        assert all(_no_words(cell) for cell in row[3:]), row
    failures = _section(outputs["docs/evals.md"], "11. Failure analysis")
    pooled = views.fill(doc["final"]["views"], "gallery.pooled.heading")
    first = failures.index(f"`{chosen[0]['entry_id']}`")
    assert first < failures.index(f"### {pooled}") < failures.index("| Letter | Condition |")


def _deviation_entries() -> list[dict[str, Any]]:
    """One deviation of each kind the section must list, recorded at the time."""
    entries = [
        hf._deviation(1, "code_hash_changed", None)
        | {"evidence": ["evals/present/text.py presentation only", "evals/present/site.py"]},
        hf._deviation(2, "budget_cut", {"split": "stress"}),
        hf._deviation(3, "unanswered", {"split": "holdout4", "repeat": 2, "entries": ["holdout4-syn-001"]}),
        hf._deviation(
            4,
            "retake",
            {"split": "holdout4", "repeat": 1, "entries": ["holdout4-syn-002", "holdout4-syn-003"]},
        ),
        hf._deviation(
            5, "label_error", {"split": "holdout4", "items": [{"entry_id": "holdout4-syn-004", "item": 0}]}
        ),
    ]
    for entry in entries:
        entry["what"] = "a distinctive account of what happened"
    return entries


def test_the_deviations_section_lists_every_entry_and_its_count_matches(
    made: Callable[[str], Made], tmp_path: Path
) -> None:
    """Section 16 lists every entry of the deviations file: its id and kind, what it applies to, its registered
    consequence, when it was recorded, its comment and checkpoint; never its ``what``. Its count is the head's and the
    provenance sentence's; an empty file says there is none."""
    doc, src = hf.scenario("good")
    src["deviations"] = _deviation_entries()
    root = hf.final_root(tmp_path, doc, sources=src, prereg=hf.complete_prereg(builders.prereg()))
    built = model.build(root / "evals" / "results")
    report = text.report(built)
    section = _section(report, "16. Deviations")
    rows = [line for line in section.splitlines() if line.startswith("| `D")]
    assert len(rows) == len(src["deviations"]) == 5
    for entry, row in zip(src["deviations"], rows, strict=True):
        assert row.startswith(f"| `{entry['id']}` | `{entry['kind']}` |")
        assert entry["consequence"] in row and entry["created_at"] in row
        assert f"]({entry['issue_comment_url']})" in row and f"`{entry['checkpoint_sha'][:12]}`" in row
    assert "`evals/present/text.py`" in rows[0] and "`evals/present/site.py`" in rows[0]
    assert "`holdout4`" in rows[2] and "`stress`" in rows[1]
    assert "a distinctive account" not in report
    sentences = {s["code"]: s["text"] for s in built["final"]["sentences"]["page"]}
    assert sentences["head.deviations"].endswith(": 5.") and "5 deviations" in sentences["provenance.some"]
    assert views.fill(
        built["final"]["views"], "deviations.lead", file=hf.FILES["deviations"], count=5
    ) in _flat(section)
    empty = made("good")
    none = views.fill(empty.doc["final"]["views"], "deviations.none", file=hf.FILES["deviations"])
    assert none in _flat(_section(empty.outputs["docs/evals.md"], "16. Deviations"))


def _recorded(doc: dict[str, Any]) -> set[str]:
    """Every value the provenance may show: the recorded fields of the pre-registration, the final analysis and the
    files they name, and presentation.json's hash as rendered."""
    shown = doc["final"]
    prereg = shown["prereg"]
    values = {prereg["file"], prereg["sha256"], *map(str, prereg["registered"].values())}
    values |= {*prereg["data"].values(), *prereg["blind_writing"], *prereg["blind_writing"].values()}
    values |= {shown["source"]["file"], shown["source"]["sha256"]}
    for row in shown["inputs"]:
        values |= {str(row[key]) for key in ("file", "sha256", "date", "commit", "role")}
    for row in shown["files"].values():
        if row:
            values |= {row["file"], row["sha256"]}
    if shown["phase2"]:
        values |= {str(value) for value in shown["phase2"].values()}
    values.add(hashlib.sha256(model.dumps(doc).encode("utf-8")).hexdigest())
    values.add(build.PRESENTATION)
    return values


def test_every_provenance_value_is_a_recorded_field(made: Callable[[str], Made], tmp_path: Path) -> None:
    """Section 17's values are recorded fields only (the pre-registration and its hash, the freeze, the commit that
    added the letters, the days, the data's and the blind writing's hashes, the final analysis and its reads, the
    named files, the presenter's posted tree when there is one) and presentation.json's hash as rendered; no hash is
    typed into a template."""
    doc, src, reads = hf.realistic()
    record = {"head": "c" * 40, "tree_sha256": "d" * 64}
    root = hf.final_root(
        tmp_path,
        doc,
        sources=src,
        prereg=hf.complete_prereg(builders.prereg()),
        reads=reads,
        extra=[("evals/preregistration/phase2-0.4.0.json", record)],
    )
    with_phase2 = model.build(root / "evals" / "results")
    assert with_phase2["final"]["phase2"] == record
    for built in (made("good").doc, made("realistic").doc, with_phase2):
        recorded = _recorded(built)
        table = _table(finaltext.provenance(built), "provenance.caption")
        values = [row[1] for row in table.rows]
        for value in values:
            tokens = re.findall(r"`([^`]+)`", value) + re.findall(r"\b\d{4}-\d{2}-\d{2}\b", value)
            tokens += re.findall(r"#(\d+)\b", value)
            assert tokens and all(token in recorded for token in tokens), value
        joined = " ".join(values)
        presentation = hashlib.sha256(model.dumps(built).encode("utf-8")).hexdigest()
        assert presentation in joined and built["final"]["prereg"]["sha256"] in joined
        for value in built["final"]["prereg"]["blind_writing"].values():
            assert value in joined
        if built["final"]["phase2"]:
            assert record["head"] in joined and record["tree_sha256"] in joined
    raw = views.VIEWS_PATH.read_text(encoding="utf-8")
    assert not re.search(r"\b[0-9a-f]{12,}\b", raw)


def _places(made_: Made) -> tuple[Any, ...]:
    """Where the final run is said: the report's headings, the charts, the registered slots and the summary's and
    statistics' tables."""
    report = made_.outputs["docs/evals.md"]
    doc = made_.doc
    blocks = [*finaltext.summary(doc), *finaltext.statistics(doc)]
    return (
        [line for line in report.splitlines() if line.startswith(("## ", "### "))],
        charts.names(doc),
        list(dict.fromkeys(s["slot"] for s in doc["final"]["sentences"]["page"])),
        list(dict.fromkeys(s["slot"] for s in doc["final"]["sentences"]["readme"])),
        [(list(block.header), len(block.rows)) for block in blocks if isinstance(block, text.Table)],
    )


def test_good_and_bad_results_fill_the_same_places(made: Callable[[str], Made]) -> None:
    """Whatever the result, the final run is said in the same places: the same sections and subsections, charts,
    registered slots and tables; only the codes and the values differ."""
    assert _places(made("good")) == _places(made("bad"))


@pytest.mark.parametrize("name", ["two_reads", "one_read"])
def test_a_read_not_run_is_said_with_its_deviation(made: Callable[[str], Made], name: str) -> None:
    """A registered read that was not recorded is published as such: section 6.1 lists it with the kind and id of the
    deviation recorded at the time, the card says how many reads were used of those registered, and nothing is
    drawn from a read that does not exist."""
    _, doc, outputs = made(name)
    shown = doc["final"]
    assert shown["reads_missing"]
    table = _table(finaltext.final_run(doc), "results.final.missing.caption")
    assert table.rows == [
        [
            str(row["read"]),
            ", ".join(f"`{kind}`" for kind in row["kinds"]),
            ", ".join(f"`{dev}`" for dev in row["deviations"]),
        ]
        for row in shown["reads_missing"]
    ]
    report = outputs["docs/evals.md"]
    final_run = _section(report, "6. Results").split("\n### 6.2 ", 1)[0]
    deviations = _section(report, "16. Deviations")
    for row in shown["reads_missing"]:
        for dev in row["deviations"]:
            assert f"`{dev}`" in final_run and f"`{dev}`" in deviations
    assert "`budget_cut`" in final_run
    assert _card(report)["Reads"] == views.fill(
        shown["views"], "card.reads", used=len(shown["reads_used"]), registered=shown["reads_registered"]
    )
    _, rows = charts.table("final", doc)
    assert all(len(row[3].split(" · ")) == len(shown["reads_used"]) for row in rows)


def test_sensitivities_sit_beside_the_primary_under_their_labels(made: Callable[[str], Made]) -> None:
    """Each sensitivity analysis is a row under its own label beside the primary analysis, with its own numbers;
    the headline, the summary and the charts keep the primary's."""
    _, doc, outputs = made("bad")
    shown = doc["final"]
    table = _table(finaltext.final_run(doc), "results.final.sens.caption")
    names = [name for name in finalrun.SENSITIVITIES if name in shown["sensitivities"]]
    assert [row[0] for row in table.rows] == [
        views.fill(shown["views"], f"results.final.sens.{name}") for name in ("primary", *names)
    ]
    primary, s_conv = table.rows[0], table.rows[1]
    ours = shown["conditions"]["ordnung"]["mean_accuracy"]["value"]
    sensitivity = shown["sensitivities"]["s_conv"]
    assert primary[2] == fmt.pct(ours)
    assert s_conv[1] == str(sensitivity["items_changed"])
    assert s_conv[2] == fmt.pct(sensitivity["conditions"]["ordnung"]["mean_accuracy"]) != primary[2]
    assert s_conv[4] == f"`{sensitivity['decisions']['beats_llm_only']}`"
    summary = _table(finaltext.summary(doc), "summary.caption")
    (row,) = [row for row in summary.rows if row[0] == "Ordnung"]
    assert row[1].startswith(fmt.pct(ours))
    assert fmt.pct(ours) in charts.description("final", doc)
    final_run = _section(outputs["docs/evals.md"], "6. Results").split("\n### 6.2 ", 1)[0]
    label = views.fill(shown["views"], "results.final.sens.s_conv")
    assert final_run.index(final.PAGE_END) < final_run.index(f"| {label} | {s_conv[1]} | {s_conv[2]} |")


@pytest.mark.parametrize("name", ["good", "realistic"])
def test_the_timeline_names_the_final_split_as_recorded(made: Callable[[str], Made], name: str) -> None:
    """With a final run, section 3's timeline and table show holdout4 (and the new kinds) as recorded: when, how many
    reads, Ordnung's exact dates over them, and the split's part in the words of the view templates; never "not yet
    written"."""
    _, doc, outputs = made(name)
    shown = doc["final"]
    rows = {row["split"]: row for row in doc["splits"]}
    held = rows["holdout4"]
    assert held["role"] == views.fill(shown["views"], "split.role.holdout4")
    exact = shown["conditions"]["ordnung"]["exact_per_read"]
    assert (held["ordnung"]["k"], held["ordnung"]["n"]) == (
        sum(rate["k"] for rate in exact),
        sum(rate["n"] for rate in exact),
    )
    assert held["recordings"] == len(shown["reads_used"])
    dates = sorted(row["date"] for row in shown["inputs"] if row["split"] == "holdout4")
    assert held["recorded"] == (dates[0] if dates else shown["date"])
    newkinds = rows["newkinds"]
    assert newkinds["role"] == views.fill(shown["views"], "split.role.newkinds")
    assert newkinds["ordnung"]["k"] == shown["newkinds"]["conditions"]["ordnung"]["exact"]["k"]
    _, table = charts.table("timeline", doc)
    (row,) = [row for row in table if row[0] == "holdout4"]
    assert row[1] == held["recorded"] and row[5] == fmt.of(held["ordnung"])
    assert row[4] == views.fill(shown["views"], "split.short.holdout4")
    for content in (
        outputs["docs/evals.md"],
        outputs["evals/present/presentation.json"],
        charts.svg("timeline", doc),
    ):
        assert "not yet written" not in content and "to be pre-registered" not in content


def test_the_pooled_numbers_carry_their_not_pre_registered_label_with_a_final(
    made: Callable[[str], Made],
) -> None:
    """With a final run the earlier held-out splits' numbers are never a headline: every section and subsection that
    shows them says they are as recorded, not pre-registered, and no line still says the final run is to come."""
    _, doc, outputs = made("good")
    report = outputs["docs/evals.md"]
    note = views.fill(
        doc["final"]["views"],
        "pooled.note",
        results=finaltext.RESULTS_ANCHOR,
        statistics=finaltext.STATISTICS_ANCHOR,
    )
    assert "not pre-registered" in note
    pooled = _section(report, "6. Results").split("\n### 6.2 ", 1)[1]
    assert note in _flat(pooled.split("\n### 6.3 ", 1)[0])
    statistics = _section(report, "7. Statistics")
    heading = views.fill(doc["final"]["views"], "stats.pooled.heading")
    assert "not pre-registered" in heading and f"\n### {heading}\n" in statistics
    assert statistics.index(f"### {heading}") < statistics.index("assets/eval-differences-light.svg")
    assert statistics.index("assets/eval-final-differences-light.svg") < statistics.index(f"### {heading}")
    for title in POOLED_SECTIONS:
        assert note in _flat(_section(report, title)), title
    gallery = views.fill(doc["final"]["views"], "gallery.pooled.heading")
    assert "not pre-registered" in gallery and f"### {gallery}" in _section(report, "11. Failure analysis")
    for stale in (
        "will be pre-registered",
        "One read per letter",
        "Not yet run: the targeted injections",
        "has not been recorded yet",
    ):
        assert stale not in report, stale
    limitations = _section(report, "14. Limitations")
    assert f"`{doc['final']['model']}`" in limitations and "**not pre-registered**" in limitations
    assert "#17-provenance" in limitations and "\n## 17. Provenance\n" in report


# --------------------------------------------------------------------------------------------------
# The report page of the final run
# --------------------------------------------------------------------------------------------------


class _Seen(HTMLParser):
    """A page's text as a reader sees it: no tags, no style, no chart's <title> or <desc>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("style", "title", "desc"):
            self._skip.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._skip and self._skip[-1] == tag:
            self._skip.pop()

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def _seen(page: str) -> str:
    parser = _Seen()
    parser.feed(page)
    return _flat("".join(parser.parts))


def _plain(sentence: str) -> str:
    """A registered sentence as the page shows it: its inline markup (code, bold, links) dropped."""
    value = re.sub(r"\[([^\]]+)\]\([^)\s]+\)", r"\1", sentence)
    value = re.sub(r"\*\*(.+?)\*\*", r"\1", value).replace("`", "")
    return _flat(value)


def _tiles(page: str) -> list[tuple[str, str]]:
    return [
        (html.unescape(value), html.unescape(label))
        for value, label in re.findall(
            r'<li class="tile"><span class="v">(.*?)</span><span class="l">(.*?)</span></li>', page
        )
    ]


def _harm(summary: dict[str, Any]) -> tuple[int, int]:
    """Late or missed over the reads: ``(k, n)`` summed over every read."""
    rates = summary["harmful_per_read"]
    return sum(int(rate["k"]) for rate in rates), sum(int(rate["n"]) for rate in rates)


def _changed(shown: str) -> str:
    """A sentence's HTML with the last letter a reader sees changed."""
    depth = 0
    for i in range(len(shown) - 1, -1, -1):
        if shown[i] == ">":
            depth += 1
        elif shown[i] == "<":
            depth -= 1
        elif depth == 0 and shown[i].isalpha():
            return shown[:i] + ("x" if shown[i] != "x" else "y") + shown[i + 1 :]
    raise AssertionError("a sentence without a letter")


def _captions(blocks: list[text.Block]) -> list[str]:
    return [block.caption for block in blocks if isinstance(block, text.Table)]


@pytest.mark.parametrize("name", ["good", "bad", "one_read", "realistic"])
def test_the_final_page_holds_every_sentence_chart_gallery_deviations_and_provenance(
    made: Callable[[str], Made], name: str, tmp_path: Path
) -> None:
    """The report page of a final run: its tiles, lede and description are the final run's (view templates filled
    with its numbers), every registered page sentence is there as a reader sees it, every final chart has its table
    and CSV (the stability over the reads only with two reads or more), the gallery, the deviations and the
    provenance follow with sections 16 and 17 in the contents, and the footer names ``presentation.json``'s hash."""
    _, doc, outputs = made(name)
    shown, templates = doc["final"], doc["final"]["views"]
    out = tmp_path / "site"
    site.build_site(doc, out)
    assert site.check_site(out, doc, forbidden=site.dataset_sentences()) == []
    page = (out / "index.html").read_text(encoding="utf-8")
    seen = _seen(page)

    # every registered page sentence, decided or not, in the page's text
    for i, sentence in enumerate(shown["sentences"]["page"], 1):
        assert _plain(sentence["text"]) in seen, (i, sentence["slot"], sentence["code"])

    # the tiles: the final run's mean accuracy for Ordnung and the model alone, and the late or missed dates over
    # the reads against the model alone's
    conditions = shown["conditions"]
    o, alone = conditions["ordnung"], conditions["llm_only"]
    level = final._formatted(shown["settings"]["level"], "percent_number", finalcharts.WHERE)

    def interval(summary: dict[str, Any]) -> str:
        low, high = summary["mean_accuracy"]["ci"]
        return views.fill(templates, "interval", level=level, lo=fmt.num(low), hi=fmt.num(high))

    k, n = _harm(o)
    assert _tiles(page) == [
        (
            fmt.pct(o["mean_accuracy"]["value"]),
            views.fill(templates, "site.tile.exact", interval=interval(o)),
        ),
        (f"{k} of {n}", views.fill(templates, "site.tile.harm", alone=_harm(alone)[0])),
        (
            fmt.pct(alone["mean_accuracy"]["value"]),
            views.fill(templates, "site.tile.alone", interval=interval(alone)),
        ),
    ]
    lede, description = views.fill(templates, "site.lede"), views.fill(templates, "site.description")
    assert f'<p class="lede">{html.escape(lede, quote=False)}</p>' in page
    assert f'<meta name="description" content="{html.escape(description)}">' in page
    assert html.escape(site.DESCRIPTION) not in page and "held out)</span>" not in page

    # every chart with its table and CSV; the stability over the reads with two reads or more only
    for chart in charts.names(doc):
        figure = page.split(f'<figure id="{chart}">', 1)[1].split("</figure>", 1)[0]
        assert "<table" in figure and f'href="{chart}.csv"' in figure and (out / f"{chart}.csv").is_file(), (
            chart
        )
    assert ('<figure id="final-stability">' in page) == (int(shown["reads"]) >= 2)
    timeline = page.split('<figure id="timeline">', 1)[1].split("</figure>", 1)[0]
    caption = html.unescape(timeline.split("<figcaption>", 1)[1].split("</figcaption>", 1)[0])
    assert caption == "What this shows: " + views.fill(templates, "chart.timeline.caption")

    # every section in the contents, the deviations and the provenance last; the final run's tables
    sections = text.sections(doc)
    for section in sections:
        assert f'<section id="{section.anchor}"' in page and f'href="#{section.anchor}"' in page, (
            section.title
        )
    assert [section.title for section in sections[-2:]] == ["16. Deviations", "17. Provenance"]
    tables = (
        _captions(finaltext.summary(doc))
        + _captions(finaltext.final_run(doc))
        + _captions(finaltext.statistics(doc))
        + _captions(finaltext.gallery(doc))
        + _captions(finaltext.deviations(doc))
        + _captions(finaltext.provenance(doc))
    )
    assert views.fill(templates, "provenance.caption") in tables
    for table in tables:
        assert f"<caption>{html.escape(table)}</caption>" in page, table

    # the footer names the hash of presentation.json as built, the one the provenance lists
    digest = hashlib.sha256(outputs["evals/present/presentation.json"].encode("utf-8")).hexdigest()
    assert digest == hashlib.sha256((out / "data.json").read_bytes()).hexdigest()
    footer = page.split("<footer>", 1)[1]
    assert (
        digest in footer
        and digest in page.split('<section id="17-provenance"', 1)[1].split("</section>", 1)[0]
    )
    assert '<a href="#17-provenance">' in footer


def test_the_final_page_passes_its_own_check_and_fails_on_each_mutation(
    made: Callable[[str], Made], tmp_path: Path
) -> None:
    """``--check-site`` on a final run's page passes, and still fails on a picture without alt text, a final chart
    without its table or its CSV, a link to nowhere, section 16 or 17 missing, a registered sentence missing or
    changed, a number the presenter does not render and a sentence of a benchmark letter."""
    _, doc, _ = made("good")
    built = tmp_path / "site"
    site.build_site(doc, built)
    good = (built / "index.html").read_text(encoding="utf-8")
    checked = iter(range(100))

    def problems(page: str, *, forbidden: tuple[str, ...] = (), drop: str = "") -> list[str]:
        out = tmp_path / f"check-{next(checked)}"
        out.mkdir()
        for path in built.iterdir():
            if path.name != drop:
                (out / path.name).write_bytes(path.read_bytes())
        (out / "index.html").write_text(page, encoding="utf-8")
        return site.check_site(out, doc, forbidden=forbidden)

    def mutated(old: str, new: str, *, count: int = 1) -> str:
        assert old in good, old
        return good.replace(old, new, count)

    assert problems(good) == []
    assert any(
        "alt text" in p for p in problems(mutated("</main>", '<img src="eval-final-light.svg"></main>'))
    )
    head, figure = good.split('<figure id="final-differences">', 1)
    no_table = head + '<figure id="final-differences">' + figure.replace("<table", "<tabel", 1)
    assert any("final-differences has no table" in p for p in problems(no_table))
    assert any("final has no CSV" in p for p in problems(good, drop="final.csv"))
    assert any("eval-final-dark.svg" in p for p in problems(good, drop="eval-final-dark.svg"))
    assert any("#nowhere" in p for p in problems(mutated('href="#16-deviations"', 'href="#nowhere"')))
    assert any("17-provenance" in p for p in problems(mutated("17-provenance", "seventeen", count=-1)))
    assert any("16-deviations" in p for p in problems(mutated("16-deviations", "sixteen", count=-1)))
    # a page-only sentence (the owner's checks, the provenance) left out, or a letter of it changed
    for slot in ("owner", "provenance"):
        sentence = next(s for s in doc["final"]["sentences"]["page"] if s["slot"] == slot)
        shown = site.inline(sentence["text"])
        gone = problems(mutated(shown, "", count=-1))
        assert any(f"({slot}" in p and "registered sentence" in p for p in gone), (slot, gone)
        assert any(f"({slot}" in p for p in problems(mutated(shown, _changed(shown), count=-1))), slot
    assert any("12.3 %" in p for p in problems(mutated("</main>", "<p>Ordnung scored 12.3 %.</p></main>")))
    assert any("77 of 168" in p for p in problems(mutated("</main>", "<p>77 of 168 right.</p></main>")))
    secret = "Bitte zahlen Sie den Betrag bis zum Ende des Monats"
    leaked = problems(mutated("</main>", f"<p>{secret}</p></main>"), forbidden=(secret,))
    assert leaked and all(secret not in p for p in leaked)  # named without printing it


def test_the_final_page_builds_from_presentation_json_with_the_standard_library_only(
    made: Callable[[str], Made], tmp_path: Path
) -> None:
    """With a final run, ``--site`` still reads ``presentation.json`` alone, with the standard library only (the
    Pages job installs nothing): neither ``ordnung`` nor the analysis is imported, and ``data.json`` is the file
    byte for byte."""
    _, _, outputs = made("bad")
    root = tmp_path / "root"
    presentation = root / build.PRESENTATION
    presentation.parent.mkdir(parents=True)
    presentation.write_text(outputs[build.PRESENTATION], encoding="utf-8")
    out = tmp_path / "site"
    script = (
        "import sys\n"
        "from evals.present.__main__ import main\n"
        f"code = main(['--root', {str(root)!r}, '--site', {str(out)!r}, '--check-site'])\n"
        "heavy = sorted(m for m in ('rapidfuzz', 'pydantic', 'ordnung', 'evals.metrics', 'evals.analysis', "
        "'evals.stats', 'evals.present.model', 'evals.present.finalrun') if m in sys.modules)\n"
        "print(','.join(heavy))\n"
        "raise SystemExit(code)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=hf.ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""
    assert (out / "data.json").read_bytes() == presentation.read_bytes()
    assert '<figure id="final">' in (out / "index.html").read_text(encoding="utf-8")


#: The report page's end-to-end cases build their final run's ``presentation.json`` with this script.
FINAL_REPORT = hf.ROOT / "tests" / "e2e_support" / "final_report.py"


def test_the_report_page_s_end_to_end_cases_build_a_synthetic_final_in_their_own_folder(
    tmp_path: Path,
) -> None:
    """``tests/e2e_support/final_report.py`` (``web/e2e/eval-report.spec.ts``'s final cases) writes a synthetic final
    run's ``presentation.json`` into the folder it is given, and nothing outside it; the page built from it passes
    its check."""
    out = tmp_path / "one_read"
    result = subprocess.run(
        [sys.executable, str(FINAL_REPORT), "--scenario", "one_read", "--out", str(out)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in tmp_path.iterdir()) == ["one_read"]
    doc = json.loads((out / build.PRESENTATION).read_text(encoding="utf-8"))
    assert doc["final"]["reads"] == 1
    assert charts.names(doc) == (*charts.NAMES, "final", "final-differences")
    assert main(["--root", str(out), "--site", str(tmp_path / "site"), "--check-site"]) == 0
    refused = subprocess.run(
        [sys.executable, str(FINAL_REPORT), "--scenario", "no such run", "--out", str(tmp_path / "x")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert refused.returncode == 2 and not (tmp_path / "x").exists()
