"""Run the Ask benchmark: build the ledgers, ask every question through the real Ask, score it.

Every question goes through :func:`ordnung.assistant.ask.ask_stream` — the app's own agent loop, MCP
tools and answer check — on a copy of the demo's ledger. By default the model's turns are
**replayed** from ``evals/recorded/ask/<model>/`` (the MCP tool results are part of each recording),
so a replay recomputes every number exactly, with no model call and no cost, and re-runs the
*current* answer check on the recorded answers. ``--live`` records what is missing with the
person's ``claude`` CLI (only sample-life documents may be recorded); ``--refresh`` records anew.

``prompts.lock.json`` next to the recordings stores the digest of the Ask prompts they were made
with: replay refuses when a prompt's text changed under the same version (Ask's replay keys carry
prompt versions, not texts). And every replayed tool call is answered again by the current MCP tools
on the rebuilt ledger (:func:`ordnung.assistant.mcp_server.stale_tool_results`): a recording whose
tool results the tools would no longer give — say, letter text moved into the record part — is
*stale*, and the run fails until it is recorded again (``--prune-stale``, then ``--live``).

Two sets: the **development set** (``dev``, the questions of :mod:`evals.ask.questions` and attacks of
:mod:`evals.ask.attacks`, iterated on) and the **held-out set** (``heldout``, :mod:`evals.ask.heldout`, written
after the freeze; recorded in ``evals/recorded/ask-heldout/``). Every answer also gets its strict scores
(:mod:`evals.ask.strict`).

The benchmark harness (:mod:`evals.harness`, when present) wraps the model calls as it does the reading
benchmark's: ``--repeat N`` asks run N (≥ 2) of the same questions under replay keys of its own, with the same
request; every replayed request is checked against ``requests.lock.json``; a live run holds the one recorder lock,
stops starting calls at ``--max-cost-usd``, waits through a usage limit with ``--wait-on-limit`` and writes one
``ledger.jsonl`` line per call.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import sys
import tempfile
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from evals.ask import heldout
from evals.ask.attacks import ATTACKS, Attack
from evals.ask.ledger import TODAY, SampleLife, build_base, copy_database, inject, pinned_today
from evals.ask.metrics import summarise, summarise_strict
from evals.ask.questions import Question, all_questions, load_truth, truth_values
from evals.ask.score import (
    Context,
    Scored,
    Turn,
    citation_support,
    letter_values,
    score_attack,
    score_question,
    unsupported_values,
)
from evals.ask.strict import (
    Extras,
    Strict,
    StrictContext,
    dev_list_gold,
    member_values_as_own,
    score_strict,
    strict_attack,
    truth_items,
)
from evals.conditions import text_sha
from evals.run import load_prompts_lock, stale_prompts, write_prompts_lock
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
HELDOUT_RECORDED_DIR = EVALS_DIR / "recorded" / "ask-heldout"
RESULTS_DIR = EVALS_DIR / "results"
DEFAULT_MODEL = "claude-sonnet-5"  # a pinned id: an alias moves with releases, the recordings do not
ASK_PROMPTS = ("ask_system", "ask")
SETS = ("dev", "heldout")


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
    set_name: str = "dev"  # the development set, or the held-out set (evals/ask/heldout.py)
    heldout_dir: Path | None = None  # tests: the held-out files' folder (default evals/ask/heldout)
    #: Which run of the same questions this is (``--repeat``): run N ≥ 2 has replay keys of its own.
    repeat: int = 1
    #: A live run starts no new call once its calls cost this much (``None``: no cap).
    max_cost_usd: float | None = None
    #: A live run waits through usage limits until this many hours after it started (``None``: it stops).
    wait_on_limit_hours: float | None = None
    #: Check every replayed request against ``requests.lock.json`` (with the harness).
    check_requests: bool = True
    #: The recorder lock a live run holds (``None``: ``.recording.lock`` in ``recorded_dir``).
    recorder_lock: Path | None = None

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
    strict: list[Strict] = field(default_factory=list)
    strict_summary: dict[str, Any] = field(default_factory=dict)
    #: what the results file says about each held-out item besides its scores (group, ledger, phrasing …)
    info: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: requests that differ from the request lock (stale or unlocked recordings, with the harness)
    drift: list[str] = field(default_factory=list)


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
    events: list[StreamEvent] = field(default_factory=list)
    response: LLMResponse | None = None
    error: str | None = None
    path: Path | None = None


class Capture:
    """Wraps the benchmark's backend and keeps what each Ask turn streamed: tool calls, tool
    results (the evidence of the answer check), the final response with its usage, or the error;
    ``stale``: the recordings whose tool results the current tools no longer give (by question)."""

    name = "ask-benchmark"  # not "replay": a missing recording is an error here, not a demo note

    def __init__(self, inner: LLMBackend, root: Path | None = None, *, repeat: int = 1) -> None:
        self.inner = inner
        self.root = root
        self.repeat = repeat
        self.calls: dict[str, _Call] = {}
        self.misses: list[str] = []
        self.stale: dict[str, tuple[Path | None, list[str]]] = {}
        self.drift: list[str] = []

    async def complete(self, req: LLMRequest) -> LLMResponse:
        return await self.inner.complete(req)

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        call = self.calls[req.cache_key or req.prompt] = _Call()
        recorded = load_harness().repeat_request(req, self.repeat) if self.repeat > 1 else req
        call.path = fixture_path(self.root, recorded) if self.root is not None else None
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
                if (event.error or "").startswith("no recorded response"):
                    self.misses.append(req.cache_key or req.prompt[:80])
                elif (event.error or "").startswith(("stale recording", "unlocked recording")):
                    self.drift.append(event.error or "")
            yield event


def load_harness() -> Any:
    """The benchmark harness, :mod:`evals.harness` — or ``None`` before it is in this checkout: then a run is the
    plain replay or recorder, and a repeat, a budget or waiting on a usage limit is refused."""
    try:
        return importlib.import_module("evals.harness")
    except ModuleNotFoundError as exc:
        if exc.name != "evals.harness":
            raise
        return None


def _check_options(config: Config) -> None:
    if config.set_name not in SETS:
        raise BenchmarkError(f"no question set {config.set_name!r}: {' or '.join(SETS)}")
    if config.repeat < 1:
        raise BenchmarkError(f"--repeat counts from 1, not {config.repeat}")
    wanted = config.repeat > 1 or config.max_cost_usd is not None or config.wait_on_limit_hours is not None
    if wanted and load_harness() is None:
        raise BenchmarkError(
            "--repeat above 1, --max-cost-usd and --wait-on-limit need evals/harness.py (the benchmark harness), "
            "which this checkout does not have"
        )


def live_setup(config: Config) -> Any:
    """What a live run's backend stacks share (:class:`evals.harness.LiveSetup`): its budget and its waiting."""
    harness = load_harness()
    return harness.LiveSetup(
        repeat=config.repeat,
        budget=harness.Budget(config.max_cost_usd) if config.max_cost_usd is not None else None,
        waiter=harness.LimitWaiter(config.wait_on_limit_hours, say=_say)
        if config.wait_on_limit_hours
        else None,
        provenance={"repeat": config.repeat},
    )


def _say(message: str) -> None:
    print(message, file=sys.stderr)


@contextlib.contextmanager
def _recording(config: Config) -> Iterator[Any]:
    """Around a live run, with the harness: the one recorder lock, and the run's :func:`live_setup`."""
    harness = load_harness()
    if harness is None or not (config.live or config.refresh):
        yield None
        return
    lock = harness.RecorderLock(
        config.recorder_lock or config.recorded_dir / harness.RECORDER_LOCK_NAME,
        command=" ".join(["evals.ask", *sys.argv[1:]]),
    )
    try:
        lock.acquire()
    except harness.RecorderBusy as exc:
        raise BenchmarkError(str(exc)) from exc
    try:
        yield live_setup(config)
    finally:
        lock.release()


def make_backend(config: Config, allowed_doc_ids: set[str], *, live: Any = None) -> LLMBackend:
    """Strict replay; ``live``: replay, else record with ``claude``; ``refresh``: record everything.

    With the harness (:mod:`evals.harness`, as the reading benchmark's ``make_backend``): the live ``claude`` is
    wrapped in its budget, waiting and ledger (``live``: the run's :func:`live_setup`); every request is checked
    against the request lock (a recorder's new recordings get their entry); run N ≥ 2 has keys of its own."""
    root = config.root
    harness = load_harness()
    stack: LLMBackend
    if not (config.live or config.refresh):
        stale = stale_prompts(root, prompt_hashes())
        if stale:
            raise BenchmarkError(
                f"The Ask prompts changed since the recordings were made ({', '.join(stale)}): "
                "record again with python -m evals.ask --live --refresh."
            )
        stack = ReplayBackend(root)
    else:
        cli: LLMBackend = config.live_backend or ClaudeCLIBackend(
            concurrency=1, interactive_concurrency=max(1, config.concurrency)
        )
        if harness is not None:
            setup = live if live is not None else live_setup(config)
            if setup.cli is None:
                setup.cli = cli
            ledger = harness.Ledger(root / harness.LEDGER_FILE, repeat=config.repeat)
            ledger.cli_version = setup.cli_version
            setup.ledgers.append(ledger)
            cli = harness.LiveCalls(cli, ledger=ledger, budget=setup.budget, waiter=setup.waiter)
        recorder = RecordingBackend(cli, root, allowed_doc_ids=allowed_doc_ids)
        stack = recorder if config.refresh else ReplayBackend(root, fallback=recorder)
    if harness is None:
        return stack
    if config.check_requests:
        stack = harness.LockedRequests(
            stack,
            harness.RequestLock(root / harness.LOCK_FILE),
            root=root,
            record=config.live or config.refresh,
            refresh=config.refresh,
            repeat=config.repeat,
        )
    if config.repeat > 1:
        stack = harness.RepeatKey(stack, config.repeat)
    return stack


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


def strict_context(base: Path, context: Context) -> StrictContext:
    """What strict scoring (:mod:`evals.ask.strict`) needs besides :func:`scoring_context`'s links: each to-do's
    and contract's own dates and amounts in Ordnung's record, every value the truth gives for each letter, and
    the truth's items."""
    store = Store.open(Paths(base))
    try:
        tools = LedgerTools(store, today=TODAY)
        rendered = [
            render_result(tools.list_items(status="all", limit=200)),
            render_result(tools.list_contracts(status="all")),
        ]
        evidence = TurnEvidence.from_results(rendered, today=TODAY)
    finally:
        store.close()
    own = {
        record_id: (
            frozenset(value.day for value in values if value.kind == "date" and value.day is not None),
            frozenset(value.cents for value in values if value.kind == "amount"),
        )
        for record_id, values in evidence.own.items()
    }
    truth = load_truth()
    letter_truth = {}
    for slug, doc in truth.items():
        dates, cents = truth_values([doc])
        letter_truth[slug] = (frozenset(dates), frozenset(cents))
    return StrictContext(
        record_letters=context.record_letters, own=own, letter_truth=letter_truth, items=truth_items(truth)
    )


def attack_targets(base: Path, life: SampleLife, attacks: Sequence[Attack] = ATTACKS) -> dict[str, str]:
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
    for attack in attacks:
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
    live: Any = None,
) -> tuple[dict[str, Turn], list[str], dict[str, tuple[Path | None, list[str]]], list[str]]:
    capture = await _capture(config, life, live)
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
    return {turn.id: turn for turn in turns}, capture.misses, capture.stale, capture.drift


async def _capture(config: Config, life: SampleLife, live: Any) -> Capture:
    """The run's backend (:func:`make_backend`) inside the :class:`Capture`; a live run asks ``claude --version``
    once (no model call) for its ledger."""
    capture = Capture(
        make_backend(config, set(life.doc_ids.values()), live=live), config.root, repeat=config.repeat
    )
    if live is not None:
        await live.resolve_version()
    return capture


def run(config: Config, *, work_dir: Path | None = None) -> RunResult:
    """Build the ledgers, ask everything (replayed or live), score it and summarise."""
    _check_options(config)
    if config.set_name == "heldout":
        return run_heldout(config, work_dir=work_dir)
    life = SampleLife.load()
    questions = [q for q in all_questions() if config.wanted(q.id)]
    attacks = [a for a in ATTACKS if config.wanted(a.id)]
    with (
        _recording(config) as live,
        pinned_today(),
        tempfile.TemporaryDirectory(prefix="ordnung-ask-eval-", dir=work_dir) as tmp,
    ):
        work = Path(tmp)
        build_base(work / "base", life)
        targets = attack_targets(work / "base", life)
        turns, misses, stale, drift = asyncio.run(
            _run_all(config, work, life, questions, attacks, targets, live)
        )
        context = scoring_context(work / "base", life, targets)
        strict_ctx = strict_context(work / "base", context)
    if config.live or config.refresh:
        write_prompts_lock(config.root, prompt_hashes())
    scored = [score_question(q, turns[q.id], context) for q in questions]
    scored += [score_attack(a, turns[a.id], context) for a in attacks]
    strict = _dev_strict(questions, attacks, turns, scored, strict_ctx)
    return RunResult(
        config,
        questions,
        attacks,
        turns,
        scored,
        summarise(scored),
        misses,
        stale,
        strict=strict,
        strict_summary=summarise_strict(scored, strict),
        drift=drift,
    )


def _dev_strict(
    questions: Sequence[Question],
    attacks: Sequence[Attack],
    turns: dict[str, Turn],
    scored: Sequence[Scored],
    ctx: StrictContext,
) -> list[Strict]:
    """The development set's strict rows: its cross-letter questions are lists (gold from the truth's items)."""
    by_id = {score.id: score for score in scored}
    rows = [
        score_strict(q, turns[q.id], by_id[q.id], ctx, Extras(list=dev_list_gold(q.id, ctx.items)))
        for q in questions
    ]
    return rows + [strict_attack(by_id[a.id], a.slug) for a in attacks]


# --------------------------------------------------------------------------------------------------
# the held-out set
# --------------------------------------------------------------------------------------------------


def run_heldout(config: Config, *, work_dir: Path | None = None) -> RunResult:
    """Ask the held-out set (:mod:`evals.ask.heldout`) as :func:`run` asks the development set: each question on
    its ledger, each attack on a copy of its ledger with the passage injected; score, strict-score, summarise."""
    folder = config.heldout_dir or heldout.HELDOUT_DIR
    try:
        items = heldout.load_questions(folder / heldout.QUESTIONS_NAME)
        hostile = heldout.load_attacks(folder / heldout.ATTACKS_NAME)
        for name in sorted({q.ledger for q in items} | {a.ledger for a in hostile}):
            heldout.ledger_builder(name)
    except heldout.HeldOutError as exc:
        raise BenchmarkError(str(exc)) from exc
    items = [q for q in items if config.wanted(q.question.id)]
    hostile = [a for a in hostile if config.wanted(a.attack.id)]
    life = SampleLife.load()
    with (
        _recording(config) as live,
        pinned_today(),
        tempfile.TemporaryDirectory(prefix="ordnung-ask-heldout-", dir=work_dir) as tmp,
    ):
        work = Path(tmp)
        build_base(work / "base", life)
        targets = attack_targets(work / "base", life, [a.attack for a in hostile])
        turns, misses, stale, drift = asyncio.run(
            _run_heldout(config, work, life, items, hostile, targets, live)
        )
        context = scoring_context(work / "base", life, targets)
        strict_ctx = strict_context(work / "base", context)
    if config.live or config.refresh:
        write_prompts_lock(config.root, prompt_hashes())
    scored = [score_question(q.question, turns[q.question.id], context) for q in items]
    strict = [
        score_strict(q.question, turns[q.question.id], s, strict_ctx, q.extras)
        for q, s in zip(items, scored, strict=True)
    ]
    for item in hostile:
        attack, turn = item.attack, turns[item.attack.id]
        score = score_attack(attack, turn, context)
        if item.member_as_own:  # a member's value given as the person's own
            score.success_raw = turn.answered and bool(member_values_as_own(turn.raw, item.extras))
            score.success_final = turn.answered and bool(member_values_as_own(turn.final, item.extras))
        scored.append(score)
        strict.append(strict_attack(score, attack.slug))
    info: dict[str, dict[str, Any]] = {
        q.question.id: {"group": q.group, "phrasing": q.phrasing, "ledger": q.ledger} for q in items
    }
    info |= {a.attack.id: {"ledger": a.ledger} for a in hostile}
    return RunResult(
        config,
        [q.question for q in items],
        [a.attack for a in hostile],
        turns,
        scored,
        summarise(scored),
        misses,
        stale,
        strict=strict,
        strict_summary=summarise_strict(scored, strict),
        info=info,
        drift=drift,
    )


async def _run_heldout(
    config: Config,
    work: Path,
    life: SampleLife,
    items: Sequence[heldout.HeldOutQuestion],
    hostile: Sequence[heldout.HeldOutAttack],
    targets: dict[str, str],
    live: Any = None,
) -> tuple[dict[str, Turn], list[str], dict[str, tuple[Path | None, list[str]]], list[str]]:
    capture = await _capture(config, life, live)
    limit = asyncio.Semaphore(max(1, config.concurrency))
    folders = {"base": work / "base"}
    for name in sorted(({q.ledger for q in items} | {a.ledger for a in hostile}) - {"base"}):
        build = heldout.ledger_builder(name)
        assert build is not None  # only the base ledger has no builder
        folders[name] = build(work / "base", work / f"ledger-{name}", life)
    jobs = []
    for name, folder in folders.items():
        asked = [(q.question.id, q.question.text) for q in items if q.ledger == name]
        if asked:
            jobs.append(_ask_many(folder, capture, config.model, asked, name, limit))
    for item in hostile:
        attack = item.attack
        folder = copy_database(folders[item.ledger], work / f"attack-{attack.id}")
        text = attack.text.replace("{target}", targets.get(attack.id, ""))
        inject(folder, life.doc_ids[attack.slug], text, channel=attack.channel)
        jobs.append(
            _ask_many(folder, capture, config.model, [(attack.id, attack.question)], attack.id, limit)
        )
    turns = [turn for batch in await asyncio.gather(*jobs) for turn in batch]
    return {turn.id: turn for turn in turns}, capture.misses, capture.stale, capture.drift


def recorded_prompt_versions(root: Path) -> dict[str, list[str]]:
    """The prompt versions the recordings in ``root`` were made with."""
    return {name: sorted(versions) for name, versions in load_prompts_lock(root).items()}
