"""The factual claims of README.md and docs/, checked against the code.

Written by a documentation audit: each test states a documented claim as an assertion, so a change
that makes the docs untrue fails here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from helpers_secretary import TODAY, seed_ledger
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.assistant.rules_tools import build_rules_server
from ordnung.db.store import Store
from ordnung.drafts.compose import compose
from ordnung.drafts.template_letters import TEMPLATES
from ordnung.ingest.extract import ExtractionInput, extraction_request
from ordnung.ingest.plan import VerifiedItem
from ordnung.llm.base import LLMRequest
from ordnung.llm.fake import FakeBackend
from ordnung.llm.runtime import LLMService
from ordnung.models import DateSpec, Evidence, ExtractedItem, Identifier, Page, Party, Profile
from ordnung.tick import DailyTick

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-09-25T10:00:00Z"


# --------------------------------------------------------------------------------------------------
# README.md
# --------------------------------------------------------------------------------------------------


def test_readme_has_no_unrendered_placeholders() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert re.findall(r"\{\{[A-Z_]+\}\}", text) == []


def test_a_git_install_contains_the_built_web_app() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "src/ordnung/web/dist/index.html"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert tracked == "src/ordnung/web/dist/index.html"


def _photo_read_item() -> VerifiedItem:
    """A photo-read deadline whose quote is found in the AI transcript and states its values."""
    spec = DateSpec(type="fixed", date="2026-10-02", nature="payment", text="bis zum 02.10.2026")
    item = ExtractedItem(kind="payment", title="Pay the fine", date=spec, quote="Zahlbar bis zum 02.10.2026")
    evidence = Evidence(doc_id="doc_x", page=1, quote=item.quote, grounding="model_read", score=100.0)
    return VerifiedItem(item=item, evidence=evidence, reasons=(), slot_key="payment:1")


def test_a_date_read_from_a_photo_is_labelled_not_flagged() -> None:
    """README: a date whose sentence is found (in the text layer or the photo's transcript) and states
    its numbers is not marked Please check; a photo-read one is labelled as read from the photo."""
    item = _photo_read_item()
    assert not item.needs_check and item.evidence is not None and item.evidence.grounding == "model_read"


def _wrong_llm_only_items(results: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    wrong = []
    for entry in results["entries"]:
        condition = entry["conditions"]["llm_only"]
        for scored in condition["score"]["items"]:
            if scored.get("required") and scored["outcome"] == "wrong":
                predicted = condition["prediction"]["items"][scored["pred_index"]]
                wrong.append((entry["id"], scored, predicted))
    return wrong


_THIRD_DAY = re.compile(r"third day|3rd day|3 days after|\+ ?3 days", re.IGNORECASE)


def test_readme_llm_only_error_counts_that_hold() -> None:
    """README.md:193-196: 10 of 56 wrong, all four late answers moved a delivery day off a weekend."""
    results = json.loads((ROOT / "evals/results/2026-09-25-sonnet-test.json").read_text(encoding="utf-8"))
    wrong = _wrong_llm_only_items(results)
    assert len(wrong) == 10
    late = [(entry, predicted) for entry, scored, predicted in wrong if scored["direction"] == "late"]
    assert len(late) == 4
    assert all(re.search(r"shift|moves|next working day|Werktag", p["explanation"]) for _, p in late)


def test_readme_eight_llm_only_errors_used_the_three_day_rule() -> None:
    """README: 'Eight of those used the 3-day delivery rule' (from the stored explanations)."""
    assert "Eight of those used the 3-day delivery rule" in (ROOT / "README.md").read_text(encoding="utf-8")
    results = json.loads((ROOT / "evals/results/2026-09-25-sonnet-test.json").read_text(encoding="utf-8"))
    three_day = [
        entry
        for entry, _, predicted in _wrong_llm_only_items(results)
        if _THIRD_DAY.search(predicted["explanation"])
    ]
    assert len(three_day) == 8, three_day


def test_rules_branch_coverage_is_a_ci_gate() -> None:
    """README.md:232 lists '100 % branch coverage of rules/' as a quality gate: CI must measure
    branches and fail under 100 % (it used to do neither)."""
    config = "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in (".github/workflows/ci.yml", "Makefile", "pyproject.toml")
    )
    assert re.search(r"cov-branch|branch\s*=\s*true", config) and re.search(r"fail[-_]under", config)


def test_mypy_is_strict_on_the_rules_engine() -> None:
    """README.md:232 says 'mypy (strict on the core)': pyproject.toml gives the rules engine the
    per-module checks of ``mypy --strict``."""
    mypy = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["mypy"]
    strict = [o for o in mypy.get("overrides", []) if "ordnung.rules.*" in o["module"]]
    assert strict and all(
        strict[0].get(flag) is True
        for flag in ("disallow_untyped_defs", "disallow_any_generics", "warn_return_any", "strict_equality")
    )
    assert strict[0].get("implicit_reexport") is False


def test_demo_check_runs_in_ci() -> None:
    """README.md:232 and docs/privacy.md:87: CI runs ``ordnung demo --check`` (added in abe86a7)."""
    assert "ordnung demo --check" in (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def _readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def _pct(value: float) -> str:
    """A rate as the README prints it: one decimal, "100" and "0" without one."""
    text = f"{value * 100:.1f}"
    return text.removesuffix(".0") if text in ("100.0", "0.0") else text


def _with_interval(metric: dict[str, Any]) -> str:
    low, high = metric["ci"]
    return f"{_pct(metric['value'])} % [{_pct(low)}–{_pct(high)}]"


def _results(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "evals" / "results" / name).read_text(encoding="utf-8"))


def test_readme_extraction_benchmark_numbers_match_the_results() -> None:
    """README's benchmark table: the held-out run (2026-09-25) for LLM only, LLM + rules text and
    Ordnung; the run after the engine fix (2026-09-26, not held-out) for Ordnung re-scored and LLM +
    rules tool; the split's size and the late count of LLM only."""
    readme = _readme()
    held_out = _results("2026-09-25-sonnet-test.json")
    after_fix = _results("2026-09-26-sonnet-test.json")
    rows = {
        "LLM only": held_out["metrics"]["llm_only"],
        "LLM + rules text": held_out["metrics"]["llm_rules_text"],
        "**Ordnung**": held_out["metrics"]["ordnung"],
        "**Ordnung**, after fixing the gap that run found²": after_fix["metrics"]["ordnung"],
        "LLM + rules tool, with the fixed engine³": after_fix["metrics"]["llm_rules_tool"],
    }
    for label, metrics in rows.items():
        row = f"| {label} | {_with_interval(metrics['due_date_accuracy'])} |"
        assert row in readme, row
    late = held_out["metrics"]["llm_only"]["dangerous_late_rate"]
    assert f"**{_pct(late['value'])} %** ({int(late['k'])} of {int(late['n'])})" in readme
    for metrics in (held_out["metrics"]["ordnung"], after_fix["metrics"]["llm_rules_tool"]):
        assert metrics["dangerous_late_rate"]["k"] == 0
    meta = held_out["meta"]
    split = (
        f"{meta['scored_items']} dated obligations in {meta['entries']} synthetic\n"
        f"letters ({meta['photos']} of them phone photos, {meta['adversarial']} adversarial)"
    )
    assert split in readme


def _words(n: int) -> str:
    """A small count as README writes it ("two late dates")."""
    return ("no", "one", "two", "three", "four", "five", "six")[n] if n <= 6 else str(n)


def _latest_holdout() -> dict[str, Any]:
    """The newest holdout results file (by its own generated_at): the one README's held-out row must match."""
    runs = [_results(path.name) for path in (ROOT / "evals" / "results").glob("*-holdout.json")]
    return max(runs, key=lambda run: run["meta"]["generated_at"])


def test_readme_prompt_now_and_held_out_rows_match_the_results() -> None:
    """README's last two benchmark rows: Ordnung with the extraction prompt the app uses now (2026-09-30,
    test split on the pinned model, not held-out) and Ordnung on the holdout split (the newest holdout run,
    recorded once); the footnotes' scores per prompt version and model, the holdout split's size and what
    its three misses are."""
    readme = _readme()
    now = _results("2026-09-30-claude-sonnet-5-test.json")["metrics"]["ordnung"]
    assert now["dangerous_late_rate"]["k"] == 0
    assert (
        f"| **Ordnung**, with the extraction prompt the app uses now⁴ | {_with_interval(now['due_date_accuracy'])} "
        "| **0 %** | no |"
    ) in readme
    holdout = _latest_holdout()
    meta, held = holdout["meta"], holdout["metrics"]["ordnung"]
    assert meta["split"] == "holdout" and "ordnung" in meta["conditions"] and not meta["partial"]
    late = held["dangerous_late_rate"]
    assert (
        f"| **Ordnung**, on a fresh held-out split⁵ | {_with_interval(held['due_date_accuracy'])} "
        f"| **{_pct(late['value'])} %** ({int(late['k'])} of {int(late['n'])}) | yes |"
    ) in readme
    assert (
        f"⁵ {meta['entries']} new letters ({meta['photos']} photos, {meta['adversarial']} adversarial; "
        f"{meta['scored_items']} dated obligations)"
    ) in readme
    exact = int(held["due_date_accuracy"]["k"])
    assert f"Ordnung got {exact} of {int(late['n'])} right" in readme
    # the baselines on the same letters, in the bullet's own words
    baselines = {name: holdout["metrics"][name] for name in ("llm_rules_text", "llm_rules_tool", "llm_only")}
    text, tool, only = (int(m["due_date_accuracy"]["k"]) for m in baselines.values())
    assert baselines["llm_rules_text"]["dangerous_late_rate"]["k"] == 0 and tool == int(late["n"])
    assert f"the rules-text prompt also scored {text} of 56, with no\n  late date" in readme
    assert f"the agent with the calculator all {tool} again" in readme
    assert (
        f"the model alone {only} of 56 with {_words(int(baselines['llm_only']['dangerous_late_rate']['k']))} late"
        in readme
    )
    scores = [
        int(_results(name)["metrics"]["ordnung"]["due_date_accuracy"]["k"])
        for name in (
            "2026-09-29-sonnet-test-prompt9.json",
            "2026-09-29-sonnet-test-prompt10.json",
            "2026-09-29-sonnet-test.json",
            "2026-09-30-sonnet-test.json",
        )
    ]
    assert f"({', '.join(map(str, scores[:-1]))} and {scores[-1]} of 56, on Sonnet 5.5)" in readme
    assert (
        f"lost access to 5.5 ({int(now['due_date_accuracy']['k'])} of 56, the run this row shows)" in readme
    )
    # the two late dates are the two conflicting-date letters; the third miss is early
    misses = [g for g in holdout["gallery"] if g["condition"] == "ordnung"]
    assert len(misses) == int(late["n"]) - exact == 3
    assert sorted(g["entry_id"] for g in misses if g["direction"] == "late") == [
        "holdout-adversarial-conflicting_dates-1",
        "holdout-adversarial-conflicting_dates-2",
    ]
    assert [g["direction"] for g in misses if g["entry_id"] == "holdout-tax_assessment-F1"] == ["early"]
    # the test split's two letters of that class were read right with the same prompt
    test_run = _results("2026-09-30-claude-sonnet-5-test.json")
    for entry in test_run["entries"]:
        if entry["id"].startswith("test-adversarial-conflicting_dates-"):
            items = entry["conditions"]["ordnung"]["score"]["items"]
            assert items and all(item["outcome"] == "correct" for item in items if item["required"])


def test_readme_ask_benchmark_numbers_match_the_latest_results() -> None:
    """README's Ask benchmark table and its sizes are the newest recorded Ask run's."""
    readme = _readme()
    latest = sorted((ROOT / "evals" / "results").glob("*-ask.json"))[-1]
    summary = json.loads(latest.read_text(encoding="utf-8"))["summary"]

    def rate(name: str) -> str:
        metric = summary[name]
        return f"{_pct(metric['value'])} % ({int(metric['k'])}/{int(metric['n'])})"

    assert (
        f"{summary['questions']} questions about the demo's sample life ({summary['answerable']} answerable, "
        f"{summary['unanswerable']} with no answer in the records) and {summary['attacks']}\nletters"
    ) in readme
    in_record = summary["accuracy_in_record"]
    assert (
        f"| {rate('accuracy')}; {_pct(in_record['value'])} % ({int(in_record['k'])}/{int(in_record['n'])}) "
        "where the answer is in Ordnung's record |"
    ) in readme
    assert f"| {rate('citation_support')} |" in readme
    assert f"| {rate('abstention')} |" in readme
    assert f"| {rate('attack_success')}, against {rate('attack_success_raw')} before the check |" in readme
    assert "| Unsupported values left in final answers | 0 |" in readme
    results = json.loads(latest.read_text(encoding="utf-8"))
    assert summary["guard"]["unsupported_in_final"] == 0
    assert all(
        entry["scores"]["unsupported_final"] == 0 for entry in results["questions"] + results["attacks"]
    )
    wrong = int(summary["accuracy"]["n"] - summary["accuracy"]["k"])
    if wrong:
        assert (
            f"The {['one', 'two', 'three', 'four', 'five', 'six'][wrong - 1]} wrong answers are gaps"
            in readme
        )
    else:  # every answer right: the README says what the earlier wrong ones were, not that some are wrong
        assert "wrong answers are gaps" not in readme
        assert "earlier recordings got wrong were gaps in the ledger" in readme.replace("\n", " ")


async def test_readme_names_exactly_the_rules_tools() -> None:
    """README: the rules engine as MCP tools — the four it names are the rules-only server's."""
    paragraph = _readme().split("**The deadline engine in Claude Desktop or Claude Code.**", 1)[1]
    paragraph = paragraph.split("```", 1)[0]
    named = set(re.findall(r"`([a-z_]+)`", paragraph))
    listed = {tool.name for tool in await build_rules_server().list_tools()}
    assert named == listed


def test_readme_lists_every_template_letter() -> None:
    """README's *template letters* list has one entry per template the composer offers."""
    listed = _readme().split("*template letters* — ", 1)[1].split(" · ", 1)[0]
    entries = [entry.strip() for entry in listed.replace("\n", " ").split(",")]
    assert len(entries) == len(TEMPLATES) == 8


def test_readme_demo_has_25_letters_three_in_new_mail() -> None:
    """README: the demo is 25 letters, three of them unopened in the New-mail tray."""
    documents = json.loads((ROOT / "src/ordnung/demo/samples/manifest.json").read_text(encoding="utf-8"))[
        "documents"
    ]
    assert "Musterstadt: 25 letters" in _readme() and len(documents) == 25
    assert "three unopened letters" in _readme() and sum(1 for d in documents if d.get("tray")) == 3


def _claimed(pattern: str) -> int:
    found = re.search(pattern, _readme())
    assert found, pattern
    return int(found.group(1).replace(",", ""))


def test_readme_backend_test_count_holds() -> None:
    """README's "N+ backend tests" is at most what pytest collects."""
    claimed = _claimed(r"(\d[\d,]*)\+ backend tests")
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # pytest's -q prints "N tests collected"; with the configured -q on top, one "file: N" line per file
    total = re.search(r"(\d+) tests? collected", collected)
    count = (
        int(total.group(1))
        if total
        else sum(int(n) for n in re.findall(r"^tests/\S+: (\d+)$", collected, re.M))
    )
    assert count >= claimed, collected[-500:]


_WEB = ROOT / "web"
_needs_web = pytest.mark.skipif(
    shutil.which("node") is None or not (_WEB / "node_modules" / ".bin").exists(),
    reason="needs node and web/node_modules (npm ci in web/)",
)


@_needs_web
def test_readme_vitest_and_playwright_counts_hold() -> None:
    """README's "N+ Vitest tests" and "N+ Playwright tests" are at most what the runners list."""
    env = {**os.environ, "CI": ""}
    vitest = subprocess.run(
        [str(_WEB / "node_modules" / ".bin" / "vitest"), "list"],
        cwd=_WEB,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout
    assert len([line for line in vitest.splitlines() if " > " in line]) >= _claimed(
        r"(\d[\d,]*)\+ Vitest tests"
    )
    playwright = subprocess.run(
        [str(_WEB / "node_modules" / ".bin" / "playwright"), "test", "--list"],
        cwd=_WEB,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout
    total = re.search(r"Total: (\d+) tests?", playwright)
    assert total, playwright[-500:]
    assert int(total.group(1)) >= _claimed(r"(\d[\d,]*)\+ Playwright tests")


# --------------------------------------------------------------------------------------------------
# docs/privacy.md — what each feature sends
# --------------------------------------------------------------------------------------------------


def _page(text: str) -> Page:
    return Page.model_validate(
        {
            "doc_id": "doc_x",
            "page": 1,
            "width": 10,
            "height": 10,
            "image_path": "p.jpg",
            "text": text,
            "text_source": "text",
        }
    )


def _party(name: str, **fields: Any) -> Party:
    return Party.model_validate(
        {
            "id": f"pty_{hashlib.sha1(name.encode()).hexdigest()[:12]}",
            "name": name,
            "created_at": NOW,
            "updated_at": NOW,
            **fields,
        }
    )


def test_reading_a_letter_sends_only_the_names_of_known_organisations() -> None:
    """docs/privacy.md: reading a letter sends the names and kinds of known organisations, no numbers
    read from other letters (they used to include passport and staff numbers)."""
    passport_office = _party(
        "Ministry of Interior", kind="authority", identifiers=[{"label": "Passport No.", "value": "X1234567"}]
    )
    employer = _party(
        "Muster Tech GmbH", kind="employer", identifiers=[{"label": "Personalnummer", "value": "10482"}]
    )
    data = ExtractionInput(
        doc_id="doc_x",
        sha256="f" * 64,
        pages=[_page("Rechnung Nr. 1 vom 01.09.2026 über 12,00 EUR.")],
        today="2026-09-25",
        language="en",
        region="NW",
        country="DE",
        person_name="Sam Rivera",
        known_parties=[passport_office, employer],
    )
    request = extraction_request(data, model="sonnet")
    sent = request.prompt + request.system
    assert "Ministry of Interior" in sent and "Muster Tech GmbH" in sent  # the documented part
    assert "X1234567" not in sent and "10482" not in sent


@pytest.fixture
def draft_ctx(data_dir: Path) -> Iterator[tuple[AppContext, FakeBackend]]:
    answer = {
        "subject": "",
        "body": "Vielen Dank.",
        "body_translation": "Thank you.",
        "enclosures": [],
        "notes_for_user": [],
    }
    backend = FakeBackend({"draft": answer})
    clock.set_today(TODAY)
    context = build_context(data_dir, backend_obj=backend)
    yield context, backend
    context.close()
    clock.set_today(None)


async def test_drafting_a_letter_never_sends_your_address(draft_ctx: tuple[AppContext, FakeBackend]) -> None:
    """docs/privacy.md: your address is never sent; drafting sends the recipient's name (first line)."""
    ctx, backend = draft_ctx
    ctx.store.save_profile(
        Profile(name="Sam Rivera", address="Beispielweg 5\n12345 Musterstadt", language="en", region="NW")
    )
    telecom = ctx.store.add_party(
        name="FunkNetz Mobile",
        kind="telecom",
        address="Funkallee 1\n10115 Berlin",
        identifiers=[Identifier(label="Kundennummer", value="4711-0815")],
    ).id
    contract = ctx.store.add_contract(
        name="FunkNetz Mobil",
        category="mobile",
        party_id=telecom,
        customer_number="4711-0815",
        concluded_date="2025-01-10",
        start_date="2025-01-15",
        initial_term_months=24,
        notice_value=1,
        notice_unit="months",
    ).id
    draft = await compose(ctx, "cancellation", contract_id=contract, instructions="Bitte bestätigen")
    assert "Beispielweg 5" in draft.sender_block  # the letter itself has the address
    (request,) = [call for call in backend.calls if isinstance(call, LLMRequest) and call.purpose == "draft"]
    sent = request.prompt + request.system
    assert "Beispielweg 5" not in sent and "12345 Musterstadt" not in sent
    assert "10115 Berlin" not in sent


async def test_weekly_review_can_be_switched_off(store: Store) -> None:
    """docs/privacy.md: the weekly Ideas review can be switched off in Settings."""
    ids = seed_ledger(store)
    backend = FakeBackend(
        {
            "brief": {"text": "Good morning."},
            "review": {
                "suggestions": [
                    {
                        "kind": "saving",
                        "title": "Check your ticket",
                        "body": "You pay for a ticket.",
                        "rationale": "An active contract.",
                        "refs": [{"type": "contract", "id": ids["ticket"]}],
                    }
                ]
            },
        }
    )

    class Ctx:
        def __init__(self) -> None:
            self.store = store
            self.llm = LLMService(backend, sink=store)
            self.bus = None

    clock.set_today(TODAY)
    try:
        settings = store.get_settings()
        every_switch_off = {
            name: False
            for name, field in type(settings).model_fields.items()
            if field.annotation is bool and name != "demo"
        }
        store.save_settings(settings.model_copy(update=every_switch_off))
        tick = DailyTick(Ctx())  # type: ignore[arg-type]
        result = await tick.check()
        await tick.stop()
    finally:
        clock.set_today(None)
    assert not result.review_started
