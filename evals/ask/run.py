"""Run the Ask benchmark: build the ledgers, ask every question through the real Ask, score it.

Every question goes through :func:`ordnung.assistant.ask.ask_stream` — the app's own agent loop, MCP
tools and answer check — on a copy of the demo's ledger. By default the model's turns are
**replayed** from ``evals/recorded/ask/<model>/`` (the MCP tool results are part of each recording),
so a replay recomputes every number exactly, with no model call and no cost, and re-runs the
*current* answer check on the recorded answers. ``--live`` records what is missing with the
person's ``claude`` CLI (only sample-life documents may be recorded); ``--refresh`` records anew.

``prompts.lock.json`` next to the recordings stores the digest of the Ask prompts they were made
with: replay refuses when a prompt's text changed under the same version (Ask's replay keys carry
prompt versions, not texts).
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from evals.ask.attacks import ATTACKS, Attack
from evals.ask.ledger import TODAY, SampleLife, build_base, copy_database, inject, pinned_today
from evals.ask.metrics import summarise
from evals.ask.questions import Question, all_questions, load_truth, truth_values
from evals.ask.score import Context, Scored, Turn, score_attack, score_question
from evals.conditions import text_sha
from evals.run import load_prompts_lock, stale_prompts, write_prompts_lock
from ordnung.assistant.ask import ask_cache_key, ask_stream, check_turn
from ordnung.assistant.citations import tool_name
from ordnung.assistant.mcp_server import LedgerTools, render_result
from ordnung.assistant.support import TurnEvidence
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.llm import prompts
from ordnung.llm.base import LLMBackend, LLMRequest, LLMResponse, StreamEvent
from ordnung.llm.claude_cli import ClaudeCLIBackend
from ordnung.llm.replay import RecordingBackend, ReplayBackend
from ordnung.llm.runtime import LLMService
from ordnung.models import AppSettings

EVALS_DIR = Path(__file__).resolve().parents[1]
RECORDED_DIR = EVALS_DIR / "recorded" / "ask"
RESULTS_DIR = EVALS_DIR / "results"
DEFAULT_MODEL = "sonnet"
ASK_PROMPTS = ("ask_system", "ask")


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
    """Everything a run produced."""

    config: Config
    questions: list[Question]
    attacks: list[Attack]
    turns: dict[str, Turn]
    scored: list[Scored]
    summary: dict[str, Any]
    misses: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------------------
# prompts and backends
# --------------------------------------------------------------------------------------------------


def prompt_hashes() -> dict[str, tuple[str, str]]:
    """``name → (version, digest)`` of the Ask prompts."""
    return {name: (version, text_sha(body)) for name in ASK_PROMPTS for version, body in [prompts.load(name)]}


@dataclass
class _Call:
    tools: list[str] = field(default_factory=list)
    results: list[str] = field(default_factory=list)
    response: LLMResponse | None = None
    error: str | None = None


class Capture:
    """Wraps the benchmark's backend and keeps what each Ask turn streamed: tool calls, tool
    results (the evidence of the answer check), the final response with its usage, or the error."""

    name = "ask-benchmark"  # not "replay": a missing recording is an error here, not a demo note

    def __init__(self, inner: LLMBackend) -> None:
        self.inner = inner
        self.calls: dict[str, _Call] = {}
        self.misses: list[str] = []

    async def complete(self, req: LLMRequest) -> LLMResponse:
        return await self.inner.complete(req)

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        call = self.calls[req.cache_key or req.prompt] = _Call()
        async for event in self.inner.stream(req):
            if event.type == "tool_use":
                call.tools.append(tool_name(event.name))
            elif event.type == "tool_result":
                call.results.append(event.text or "")
            elif event.type == "done":
                call.response = event.response
            elif event.type == "error":
                call.error = event.error
                if (event.error or "").startswith("no recorded response"):
                    self.misses.append(req.cache_key or req.prompt[:80])
            yield event


def make_backend(config: Config, allowed_doc_ids: set[str]) -> LLMBackend:
    """Strict replay; ``live``: replay, else record with ``claude``; ``refresh``: record everything."""
    root = config.root
    if not (config.live or config.refresh):
        stale = stale_prompts(root, prompt_hashes())
        if stale:
            raise BenchmarkError(
                f"The Ask prompts changed since the recordings were made ({', '.join(stale)}): "
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


def _context(data_dir: Path, capture: Capture, model: str) -> _AskContext:
    store = Store.open(Paths(data_dir))
    settings = store.get_settings()
    settings = settings.model_copy(update={"models": settings.models.model_copy(update={"ask": model})})
    return _AskContext(paths=Paths(data_dir), store=store, llm=LLMService(capture, store), settings=settings)


async def _ask(ctx: _AskContext, capture: Capture, item_id: str, question: str, ledger: str) -> Turn:
    final = None
    error = None
    citations: list[str] = []
    async for event in ask_stream(ctx, question):
        if event.type == "done":
            final = event.text or ""
            citations = [ref.id for ref in getattr(event, "citations", None) or []]
        elif event.type == "error":
            error = event.error or "error"
    call = capture.calls.get(ask_cache_key(ctx.store, question, [], TODAY))
    if final is None or call is None or call.response is None:
        return Turn(
            item_id, question, ledger, "", "", [], call.tools if call else [], error=error or "no answer"
        )
    raw = call.response.text
    checked = check_turn(ctx.store, raw, call.results, question=question, today=TODAY)
    recheck = check_turn(ctx.store, final, call.results, question=question, today=TODAY)
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
            }
            for c in checked.claims.sentences
        ],
        recheck_removed=len(recheck.claims.removed),
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
        rendered = [
            render_result(tools.list_items(status="all", limit=200)),
            render_result(tools.list_contracts(status="all")),
            render_result(tools.money_summary()),
            render_result(tools.timeline("2026-01-01", "2027-12-31")),
            *(render_result(tools.explain_date(c.id)) for c in store.list_contracts()),
        ]
        evidence = TurnEvidence.from_results(rendered, today=TODAY)
        record_dates: set[date] = set(evidence.context.dates)
        record_cents: set[int] = set(evidence.context.cents)
        for facts in evidence.record.values():
            record_dates |= facts.dates
            record_cents |= facts.cents
    finally:
        store.close()
    truth_dates, truth_cents = truth_values(load_truth().values())
    return Context(
        record_letters=letters,
        truth_dates=frozenset(truth_dates),
        truth_cents=frozenset(truth_cents),
        record_dates=frozenset(record_dates),
        record_cents=frozenset(record_cents),
        target_ids=targets,
    )


def attack_targets(base: Path, life: SampleLife) -> dict[str, str]:
    """The record each ``cite_other`` attack wants cited: the rent to-do or the rent contract."""
    store = Store.open(Paths(base))
    try:
        lease = life.doc_ids["mietvertrag"]
        rent_item = next(
            (i.id for i in store.list_items(doc_id=lease) if i.kind == "payment" and i.amount == 640.0), None
        )
        rent_contract = next((c.id for c in store.list_contracts() if c.source_doc_id == lease), None)
    finally:
        store.close()
    found = {"rent_item": rent_item, "rent_contract": rent_contract}
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
) -> tuple[dict[str, Turn], list[str]]:
    capture = Capture(make_backend(config, set(life.doc_ids.values())))
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
    turns = [turn for batch in await asyncio.gather(*jobs) for turn in batch]
    return {turn.id: turn for turn in turns}, capture.misses


def run(config: Config, *, work_dir: Path | None = None) -> RunResult:
    """Build the ledgers, ask everything (replayed or live), score it and summarise."""
    life = SampleLife.load()
    questions = [q for q in all_questions() if config.wanted(q.id)]
    attacks = [a for a in ATTACKS if config.wanted(a.id)]
    with pinned_today(), tempfile.TemporaryDirectory(prefix="ordnung-ask-eval-", dir=work_dir) as tmp:
        work = Path(tmp)
        build_base(work / "base", life)
        targets = attack_targets(work / "base", life)
        turns, misses = asyncio.run(_run_all(config, work, life, questions, attacks, targets))
        context = scoring_context(work / "base", life, targets)
    if config.live or config.refresh:
        write_prompts_lock(config.root, prompt_hashes())
    scored = [score_question(q, turns[q.id], context) for q in questions]
    scored += [score_attack(a, turns[a.id], context) for a in attacks]
    return RunResult(config, questions, attacks, turns, scored, summarise(scored), misses)


def recorded_prompt_versions(root: Path) -> dict[str, list[str]]:
    """The prompt versions the recordings in ``root`` were made with."""
    return {name: sorted(versions) for name, versions in load_prompts_lock(root).items()}
