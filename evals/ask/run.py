"""Run the Ask benchmark: build the ledgers, ask every question through the real Ask, score it.

Every question goes through :func:`ordnung.assistant.ask.ask_stream` — the app's own agent loop, MCP
tools and answer check — on a copy of the demo's ledger. By default the model's turns are
**replayed** from ``evals/recorded/ask/<model>/`` (the MCP tool results are part of each recording),
so a replay recomputes every number exactly, with no model call and no cost, and re-runs the
*current* answer check on the recorded answers. ``--live`` records what is missing with the
person's ``claude`` CLI (only sample-life documents may be recorded); ``--refresh`` records anew.

``prompts.lock.json`` next to the recordings stores the digest of the Ask prompts they were made
with, and of the rest every turn is given (``ask_tools``: the server's instructions, its tools as
tools/list gives them, the allowed tools and the cost cap, under the Ask prompt's version): replay
refuses when any of it changed under the same version (Ask's replay keys carry prompt versions, not
texts). And every replayed tool call is answered again by the current MCP tools on the rebuilt ledger
(:func:`ordnung.assistant.mcp_server.stale_tool_results`): a recording whose tool results the tools
would no longer give — say, letter text moved into the record part — is *stale*, and the run fails
until it is recorded again (``--prune-stale``, then ``--live``).

The household group (:mod:`evals.ask.household`) is asked on a ledger of its own and reported apart.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import AsyncIterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from evals.ask.attacks import ATTACKS, Attack
from evals.ask.household import (
    HouseholdQuestion,
    build_household,
    household_questions,
    household_truth,
    summarise_household,
)
from evals.ask.ledger import TODAY, SampleLife, build_base, copy_database, inject, pinned_today
from evals.ask.metrics import summarise
from evals.ask.questions import Question, all_questions, load_truth, truth_values
from evals.ask.score import (
    Context,
    Scored,
    Turn,
    citation_support,
    letter_values,
    score_attack,
    score_household,
    score_question,
    unsupported_values,
)
from evals.conditions import text_sha
from evals.run import load_prompts_lock, stale_prompts, write_prompts_lock
from ordnung.assistant import ask as ask_agent
from ordnung.assistant import mcp_server
from ordnung.assistant.ask import ask_cache_key, ask_stream, check_turn
from ordnung.assistant.citations import tool_name
from ordnung.assistant.mcp_server import LedgerTools, render_result, stale_tool_results
from ordnung.assistant.support import TurnEvidence, labelled_note
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.llm import prompts
from ordnung.llm.base import LLMBackend, LLMRequest, LLMResponse, StreamEvent
from ordnung.llm.claude_cli import ClaudeCLIBackend
from ordnung.llm.replay import RecordingBackend, ReplayBackend, fixture_path
from ordnung.llm.runtime import LLMService
from ordnung.models import AppSettings

EVALS_DIR = Path(__file__).resolve().parents[1]
RECORDED_DIR = EVALS_DIR / "recorded" / "ask"
RESULTS_DIR = EVALS_DIR / "results"
DEFAULT_MODEL = "claude-sonnet-5"  # a pinned id: an alias moves with releases, the recordings do not
ASK_PROMPTS = ("ask_system", "ask")
#: The lock entry of what every Ask turn is given besides its prompts (:func:`ask_tools_digest`).
ASK_TOOLS = "ask_tools"


class BenchmarkError(RuntimeError):
    """The benchmark cannot run (the message says what to do)."""


@dataclass
class Config:
    """What a run depends on (see ``python -m evals.ask --help``)."""

    model: str = DEFAULT_MODEL
    live: bool = False
    refresh: bool = False
    only: list[str] | None = None
    concurrency: int = 3
    recorded_dir: Path = RECORDED_DIR
    live_backend: LLMBackend | None = None  # tests: stands in for the claude CLI

    @property
    def root(self) -> Path:
        return self.recorded_dir / self.model

    def wanted(self, item_id: str) -> bool:
        return not self.only or item_id in self.only


@dataclass
class RunResult:
    """Everything a run produced; ``stale``: question id → (recording, tools whose results changed)."""

    config: Config
    questions: list[Question]
    attacks: list[Attack]
    turns: dict[str, Turn]
    scored: list[Scored]
    summary: dict[str, Any]
    misses: list[str] = field(default_factory=list)
    stale: dict[str, tuple[Path | None, list[str]]] = field(default_factory=dict)
    household: list[HouseholdQuestion] = field(default_factory=list)
    household_scored: list[Scored] = field(default_factory=list)


# --------------------------------------------------------------------------------------------------
# prompts and backends
# --------------------------------------------------------------------------------------------------


def prompt_hashes() -> dict[str, tuple[str, str]]:
    """``name → (version, digest)`` of the Ask prompts."""
    return {name: (version, text_sha(body)) for name in ASK_PROMPTS for version, body in [prompts.load(name)]}


def ask_tools_digest() -> str:
    """The digest of what every Ask turn is given besides its prompts, the question and the ledger: the
    ledger-only server's instructions and its tools as tools/list gives them (names, descriptions, input
    schemas), the tools Ask may call and its cost cap. None of it is in a recording's key, and the staleness
    check compares tool results only: a changed description would reach every turn with nothing to notice."""

    async def listed() -> list[dict[str, Any]]:
        with tempfile.TemporaryDirectory(prefix="ordnung-ask-tools-") as tmp:
            store = Store.open(Paths(Path(tmp)))
            try:
                server = mcp_server.build_server(store, rules_tools=False)
                return [tool.model_dump(mode="json", exclude_none=True) for tool in await server.list_tools()]
            finally:
                store.close()

    with ThreadPoolExecutor(max_workers=1) as pool:  # its own event loop, also from inside a running one
        tools = pool.submit(asyncio.run, listed()).result()
    given = {
        "instructions": mcp_server.INSTRUCTIONS,
        "tools": tools,
        "allowed_tools": ask_agent.ALLOWED_TOOLS,
        "max_budget_usd": ask_agent.MAX_BUDGET_USD,
    }
    return text_sha(json.dumps(given, sort_keys=True, ensure_ascii=False))


def locked_inputs() -> dict[str, tuple[str, str]]:
    """What ``prompts.lock.json`` pins: the Ask prompts (:func:`prompt_hashes`) and, under the Ask system
    prompt's version, :data:`ASK_TOOLS` (:func:`ask_tools_digest`). A name an older lock lacks is not stale
    (:func:`evals.run.stale_prompts`): the next live run writes it."""
    hashes = prompt_hashes()
    return {**hashes, ASK_TOOLS: (hashes["ask_system"][0], ask_tools_digest())}


@dataclass
class _Call:
    tools: list[str] = field(default_factory=list)
    results: list[str] = field(default_factory=list)
    events: list[StreamEvent] = field(default_factory=list)
    response: LLMResponse | None = None
    error: str | None = None
    path: Path | None = None


class Capture:
    """Wraps the benchmark's backend and keeps what each Ask turn streamed: tool calls, tool
    results (the evidence of the answer check), the final response with its usage, or the error;
    ``stale``: the recordings whose tool results the current tools no longer give (by question)."""

    name = "ask-benchmark"  # not "replay": a missing recording is an error here, not a demo note

    def __init__(self, inner: LLMBackend, root: Path | None = None) -> None:
        self.inner = inner
        self.root = root
        self.calls: dict[str, _Call] = {}
        self.missed: list[str] = []  # the questions (by id) without a recording
        self.stale: dict[str, tuple[Path | None, list[str]]] = {}

    async def complete(self, req: LLMRequest) -> LLMResponse:
        return await self.inner.complete(req)

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        call = self.calls[req.cache_key or req.prompt] = _Call()
        call.path = fixture_path(self.root, req) if self.root is not None else None
        async for event in self.inner.stream(req):
            if event.type in ("tool_use", "tool_result"):
                call.events.append(event)
            if event.type == "tool_use":
                call.tools.append(tool_name(event.name))
            elif event.type == "tool_result":
                call.results.append(event.text or "")
            elif event.type == "done":
                call.response = event.response
            elif event.type == "error":
                call.error = event.error
            yield event


def make_backend(config: Config, allowed_doc_ids: set[str]) -> LLMBackend:
    """Strict replay; ``live``: replay, else record with ``claude``; ``refresh``: record everything."""
    root = config.root
    if not (config.live or config.refresh):
        stale = stale_prompts(root, locked_inputs())
        if stale:
            raise BenchmarkError(
                f"The Ask prompts or tools changed since the recordings were made ({', '.join(stale)}): "
                "record again with python -m evals.ask --live --refresh."
            )
        return ReplayBackend(root)
    live = config.live_backend or ClaudeCLIBackend(
        concurrency=1, interactive_concurrency=max(1, config.concurrency)
    )
    recorder = RecordingBackend(live, root, allowed_doc_ids=allowed_doc_ids)
    return recorder if config.refresh else ReplayBackend(root, fallback=recorder)


# --------------------------------------------------------------------------------------------------
# asking
# --------------------------------------------------------------------------------------------------


@dataclass
class _AskContext:
    paths: Paths
    store: Store
    llm: LLMService
    settings: AppSettings
    truth: tuple[frozenset[date], frozenset[int]] = (frozenset(), frozenset())


def _context(data_dir: Path, capture: Capture, model: str) -> _AskContext:
    store = Store.open(Paths(data_dir))
    settings = store.get_settings()
    settings = settings.model_copy(update={"models": settings.models.model_copy(update={"ask": model})})
    dates, cents = truth_values(load_truth().values())
    return _AskContext(
        paths=Paths(data_dir),
        store=store,
        llm=LLMService(capture, store),
        settings=settings,
        truth=(frozenset(dates), frozenset(cents)),
    )


async def _ask(ctx: _AskContext, capture: Capture, item_id: str, question: str, ledger: str) -> Turn:
    final = None
    error = None
    citations: list[str] = []
    async for event in ask_stream(ctx, question):
        if event.type == "done":
            # what the person sees: the answer, then the check's note under it
            note = getattr(event, "note", None)
            final = (event.text or "") + (f"\n\n{labelled_note(note)}" if note else "")
            citations = [ref.id for ref in getattr(event, "citations", None) or []]
        elif event.type == "error":
            error = event.error or "error"
    call = capture.calls.get(ask_cache_key(ctx.store, question, [], TODAY))
    if call is not None and (call.error or "").startswith("no recorded response"):
        capture.missed.append(item_id)
    if call is not None and (stale := stale_tool_results(LedgerTools(ctx.store, today=TODAY), call.events)):
        capture.stale[item_id] = (call.path, stale)
    if final is None or call is None or call.response is None:
        return Turn(
            item_id, question, ledger, "", "", [], call.tools if call else [], error=error or "no answer"
        )
    raw = call.response.text
    checked = check_turn(ctx.store, raw, call.results, question=question, today=TODAY)
    usage = call.response.usage
    return Turn(
        id=item_id,
        question=question,
        ledger=ledger,
        raw=raw,
        final=final,
        cited=citations,
        tools=call.tools,
        turns=usage.turns,
        cost_usd=usage.cost_usd,
        duration_ms=usage.duration_ms,
        claims=[
            {
                "text": c.text,
                "verdict": c.verdict,
                "values": list(c.values),
                "unsupported": list(c.unsupported),
                "left_out": list(c.left_out),
                "reason": c.reason,
            }
            for c in checked.claims.sentences
        ],
        letter_values=letter_values(call.results),
        support=citation_support(final, call.results, question),
        unsupported_final=unsupported_values(final, citations, call.results, question, *ctx.truth),
    )


async def _ask_many(
    data_dir: Path,
    capture: Capture,
    model: str,
    items: Sequence[tuple[str, str]],
    ledger: str,
    limit: asyncio.Semaphore,
) -> list[Turn]:
    ctx = _context(data_dir, capture, model)

    async def one(item_id: str, question: str) -> Turn:
        async with limit:
            return await _ask(ctx, capture, item_id, question, ledger)

    try:
        return list(await asyncio.gather(*(one(item_id, question) for item_id, question in items)))
    finally:
        ctx.store.close()


# --------------------------------------------------------------------------------------------------
# the scoring context: what each record belongs to, what the truth and the record hold
# --------------------------------------------------------------------------------------------------


def scoring_context(base: Path, life: SampleLife, targets: dict[str, str]) -> Context:
    """Links from every record to its letters, the truth's values and the record's values."""
    store = Store.open(Paths(base))
    try:
        slug = {doc_id: name for name, doc_id in life.doc_ids.items()}
        letters: dict[str, frozenset[str]] = {}
        documents = store.list_documents()
        for doc in documents:
            letters[doc.id] = frozenset({slug[doc.id]} if doc.id in slug else ())
        for item in store.list_items():
            letters[item.id] = letters.get(item.doc_id or "", frozenset())
        for contract in store.list_contracts():
            docs = {contract.source_doc_id, *(ev.doc_id for ev in contract.evidence)}
            letters[contract.id] = frozenset(slug[d] for d in docs if d in slug)
        for party in store.list_parties():
            letters[party.id] = frozenset(
                slug[d.id] for d in documents if d.party_id == party.id and d.id in slug
            )
        tools = LedgerTools(store, today=TODAY)
        contracts = tools.list_contracts(status="all")
        for row in contracts.record["contracts"]:  # a price letter's special window is the contract's too
            window = row.get("special_cancellation")
            if window is not None and window["doc_id"] in slug:
                letters[row["id"]] |= {slug[window["doc_id"]]}
        rendered = [
            render_result(tools.list_items(status="all", limit=200)),
            render_result(contracts),
            render_result(tools.money_summary()),
            render_result(tools.timeline("2026-01-01", "2027-12-31")),
            *(render_result(tools.explain_date(c.id)) for c in store.list_contracts()),
        ]
        evidence = TurnEvidence.from_results(rendered, today=TODAY)
    finally:
        store.close()
    truth_dates, truth_cents = truth_values(load_truth().values())
    return Context(
        record_letters=letters,
        truth_dates=frozenset(truth_dates),
        truth_cents=frozenset(truth_cents),
        item_values=_values_by_letter(evidence, letters, "itm_"),
        contract_values=_values_by_letter(evidence, letters, "ctr_"),
        target_ids=targets,
    )


def _values_by_letter(
    evidence: TurnEvidence, letters: dict[str, frozenset[str]], prefix: str
) -> dict[str, tuple[frozenset[date], frozenset[int]]]:
    """Record-part dates and amounts of the records with ``prefix``, collected by their letters."""
    dates: dict[str, set[date]] = {}
    cents: dict[str, set[int]] = {}
    for record_id, facts in evidence.record.items():
        if not record_id.startswith(prefix):
            continue
        for slug in letters.get(record_id, frozenset()):
            dates.setdefault(slug, set()).update(facts.dates)
            cents.setdefault(slug, set()).update(facts.cents)
    return {slug: (frozenset(dates[slug]), frozenset(cents.get(slug, set()))) for slug in dates}


def attack_targets(base: Path, life: SampleLife) -> dict[str, str]:
    """The record each ``cite_other`` attack wants cited: the rent to-do, the rent contract or the tax
    objection's to-do."""
    store = Store.open(Paths(base))
    try:
        lease = life.doc_ids["mietvertrag"]
        rent_item = next(
            (i.id for i in store.list_items(doc_id=lease) if i.kind == "payment" and i.amount == 640.0), None
        )
        rent_contract = next((c.id for c in store.list_contracts() if c.source_doc_id == lease), None)
        tax = life.doc_ids["steuerbescheid_2025"]
        objection = next(
            (
                i.id
                for i in store.list_items(doc_id=tax)
                if i.kind == "deadline" and i.due_date == "2026-10-21"
            ),
            None,
        )
    finally:
        store.close()
    found = {"rent_item": rent_item, "rent_contract": rent_contract, "tax_objection_item": objection}
    targets = {}
    for attack in ATTACKS:
        if attack.target is not None:
            target = found[attack.target]
            if target is None:
                raise BenchmarkError(f"The ledger has no {attack.target} for the attack {attack.id}.")
            targets[attack.id] = target
    return targets


# --------------------------------------------------------------------------------------------------
# a run
# --------------------------------------------------------------------------------------------------


async def _run_all(
    config: Config,
    work: Path,
    life: SampleLife,
    questions: list[Question],
    attacks: list[Attack],
    targets: dict[str, str],
    household: Sequence[HouseholdQuestion] = (),
) -> tuple[dict[str, Turn], list[str], dict[str, tuple[Path | None, list[str]]]]:
    capture = Capture(make_backend(config, set(life.doc_ids.values())), config.root)
    limit = asyncio.Semaphore(max(1, config.concurrency))
    jobs = [
        _ask_many(work / "base", capture, config.model, [(q.id, q.text) for q in questions], "base", limit)
    ]
    for attack in attacks:
        folder = copy_database(work / "base", work / f"attack-{attack.id}")
        text = attack.text.replace("{target}", targets.get(attack.id, ""))
        inject(folder, life.doc_ids[attack.slug], text, channel=attack.channel)
        jobs.append(
            _ask_many(folder, capture, config.model, [(attack.id, attack.question)], attack.id, limit)
        )
    if household:
        folder = build_household(work / "base", work / "household", life)
        asked = [(q.id, q.text) for q in household]
        jobs.append(_ask_many(folder, capture, config.model, asked, "household", limit))
    turns = [turn for batch in await asyncio.gather(*jobs) for turn in batch]
    return {turn.id: turn for turn in turns}, sorted(capture.missed), capture.stale


def run(config: Config, *, work_dir: Path | None = None) -> RunResult:
    """Build the ledgers, ask everything (replayed or live), score it and summarise; the household group's
    numbers go in a block of their own (``summary["household"]``), never into the headline's."""
    life = SampleLife.load()
    questions = [q for q in all_questions() if config.wanted(q.id)]
    attacks = [a for a in ATTACKS if config.wanted(a.id)]
    household = [q for q in household_questions() if config.wanted(q.id)]
    with pinned_today(), tempfile.TemporaryDirectory(prefix="ordnung-ask-eval-", dir=work_dir) as tmp:
        work = Path(tmp)
        build_base(work / "base", life)
        targets = attack_targets(work / "base", life)
        turns, misses, stale = asyncio.run(
            _run_all(config, work, life, questions, attacks, targets, household)
        )
        context = scoring_context(work / "base", life, targets)
    if config.live or config.refresh:
        write_prompts_lock(config.root, locked_inputs())
    scored = [score_question(q, turns[q.id], context) for q in questions]
    scored += [score_attack(a, turns[a.id], context) for a in attacks]
    truth = household_truth()
    household_scored = [score_household(q, turns[q.id], truth) for q in household]
    summary = summarise(scored)
    if household:
        summary["household"] = summarise_household(household_scored)
    return RunResult(
        config, questions, attacks, turns, scored, summary, misses, stale, household, household_scored
    )


def recorded_prompt_versions(root: Path) -> dict[str, list[str]]:
    """The prompt versions the recordings in ``root`` were made with."""
    return {name: sorted(versions) for name, versions in load_prompts_lock(root).items()}
