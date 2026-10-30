"""Run benchmark letters through the real app on their recorded readings, and observe what the person gets.

One fresh data folder per letter, deleted afterwards. The profile is the benchmark persona (``PERSONA_LANGUAGE``,
the letter's recipient Land or ``PERSONA_REGION``, no name while the letter is read — the recordings were made
with none) and the model settings name the pinned model for reading, transcribing and drafting: the app keys its
requests by those names (``ModelSettings``: an alias such as ``sonnet`` by default), so with the pinned id they are
the benchmark's own requests and replay from ``evals/recorded/<model>``. Strict replay: a reading without its
recording raises :class:`~ordnung.llm.base.ReplayMiss` and the letter is an error of the run, by id; a recorded
model failure replays as one (:class:`evals.run.RecordedFailures`), as in the benchmark. The objection letter's
optional model text has no recording: :func:`~ordnung.drafts.compose.compose` then writes the code's fixed text, and
the run counts those requests (``draft_without_recording``).

Nothing is confirmed by the person: no sender's Land, no arrival day, no suggestion accepted — the app as it is on
the day a letter arrives. The parity reference is therefore the benchmark's Ordnung condition without the sender's
Land (:func:`benchmark_dates`, ``scripts/eval_without_land.py``).
"""

from __future__ import annotations

import os
import tempfile
from collections import Counter
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evals.e2e.check import no_remedy_letter, probe_days, remedy_letter
from evals.e2e.observe import (
    AgendaProbe,
    DraftSeen,
    IdeaSeen,
    LetterObservation,
    SetAsideCause,
    StoredItem,
    calendar_events,
    pdf_lines,
)
from evals.records import PERSONA_LANGUAGE, PERSONA_REGION, Entry
from evals.run import (
    DATASET_DIR,
    DEFAULT_MODEL,
    MANIFEST_PATH,
    RECORDED_DIR,
    RecordedFailures,
    RunConfig,
    run_benchmark,
    safe_name,
)
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.calendar.ics import OPEN_STATUSES, build_ics, item_uid
from ordnung.demo.loader import OfflineTickContext
from ordnung.demo.tour import claim_document_job
from ordnung.drafts import pdf, sent
from ordnung.drafts.compose import DraftError, compose
from ordnung.ingest.outlook import as_email
from ordnung.ingest.pipeline import INJECTION_WARNING, add_file, ingest_document
from ordnung.llm.base import ClaudeBadOutput, LLMError, LLMRequest, LLMResponse, ReplayMiss, StreamEvent
from ordnung.llm.replay import ReplayBackend
from ordnung.models import AppSettings, Document, Item, ModelSettings, Profile
from ordnung.secretary.brief import build_agenda
from ordnung.secretary.triggers import HIDDEN_TEXT_SIGN, Ledger, was_history_when_filed
from ordnung.tick import DailyTick

#: The name and address the objection letter is signed with (the demo's fictional persona); set only after the
#: letter was read, as the recordings were made without a name.
SIGNER = "Sam Rivera"
SIGNER_ADDRESS = "Musterweg 1\n50667 Köln"
DRAFT_PURPOSE = "draft"
#: Kinds whose Idea window (the profile's longest reminder) the checker reads.
WINDOW_KINDS = ("deadline", "payment", "appointment", "task")
#: The words that make a warning a scam sign (``ordnung.secretary.triggers.is_scam_warning``), to name which one
#: did without quoting the warning; a sign none of them names is ``other``.
SCAM_WORDS = (
    "scam",
    "phish",
    "fraud",
    "betrug",
    "suspicious",
    "verdächtig",
    "fake",
    "gefälscht",
    "impersonat",
    "mismatch",
    "instructions addressed",
    "embedded instruction",
    "prompt injection",
    "hidden text",
)


class CountingReplay:
    """Strict replay of the benchmark's recordings (recorded model failures replay as failures), counting the
    answers, misses and failures by purpose, and the letters a reading missed for."""

    name = "replay"

    def __init__(self, root: Path) -> None:
        self.inner = RecordedFailures(ReplayBackend(root), root, record=False)
        self.hits: Counter[str] = Counter()
        self.misses: Counter[str] = Counter()
        self.failures: Counter[str] = Counter()
        self.letter: str | None = None
        self.missed_for: set[str] = set()

    def _missed(self, req: LLMRequest) -> None:
        self.misses[req.purpose] += 1
        if req.purpose != DRAFT_PURPOSE and self.letter is not None:
            self.missed_for.add(self.letter)

    async def complete(self, req: LLMRequest) -> LLMResponse:
        try:
            response = await self.inner.complete(req)
        except ReplayMiss:
            self._missed(req)
            raise
        except ClaudeBadOutput:
            self.failures[req.purpose] += 1
            raise
        self.hits[req.purpose] += 1
        return response

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        self._missed(req)
        raise ReplayMiss(f"no recorded stream for {req.purpose}")
        yield  # pragma: no cover - an async generator that never yields

    def counts(self) -> dict[str, Any]:
        """The replay's accounting for the results (purposes sorted; a draft without recording is expected)."""
        misses = {purpose: n for purpose, n in sorted(self.misses.items()) if purpose != DRAFT_PURPOSE}
        return {
            "hits": dict(sorted(self.hits.items())),
            "misses": misses,
            "failures": dict(sorted(self.failures.items())),
            "draft_without_recording": self.misses.get(DRAFT_PURPOSE, 0),
        }


def _matched_words(text: str) -> str:
    folded = text.casefold()
    return "+".join(word for word in SCAM_WORDS if word in folded) or "other"


def reason_codes(reasons: Sequence[str], *, warnings: Sequence[str]) -> list[str]:
    """The app's scam verdict for a letter (``Ledger.scam_reasons``) as codes, never its words (a reading's
    warning may quote the letter): ``hidden_text``; ``injection_warning`` (the code's own warning about text
    addressed to an AI) and ``reading_warning`` (one of the reading's warnings), each with the scam words that made
    it a sign; ``iban_checksum``; ``payment_check`` (a payee or IBAN unlike the sender's earlier letters)."""
    codes = set()
    for reason in reasons:
        if reason == HIDDEN_TEXT_SIGN:
            codes.add("hidden_text")
        elif reason.startswith(INJECTION_WARNING):
            words = _matched_words(reason[len(INJECTION_WARNING) :])
            codes.add("injection_warning" if words == "other" else f"injection_warning:{words}")
        elif reason in warnings:
            codes.add(f"reading_warning:{_matched_words(reason)}")
        elif "iban" in reason.casefold() and "checksum" in reason.casefold():
            codes.add("iban_checksum")
        else:
            codes.add("payment_check")
    return sorted(codes)


def _set_aside(ledger: Ledger, item: Item) -> list[SetAsideCause]:
    causes: list[SetAsideCause] = []
    if ledger.is_suspicious_item(item):
        causes.append("scam_signs")
    if ledger.is_superseded_by_reminder(item):
        causes.append("superseded_by_reminder")
    if ledger.is_covered_by_attachment(item):
        causes.append("covered_by_attachment")
    if item.status in OPEN_STATUSES and item.recurrence is None and was_history_when_filed(item):
        causes.append("history_when_filed")
    return causes


def _stored(ledger: Ledger, item: Item) -> StoredItem:
    return StoredItem(
        id=item.id,
        kind=item.kind,
        title=item.title,
        quote=item.evidence[0].quote if item.evidence else "",
        due_date=item.due_date,
        send_by=item.send_by,
        amount=item.amount,
        status=item.status,
        set_aside=_set_aside(ledger, item),
    )


async def _read(ctx: AppContext, entry: Entry, dataset_dir: Path) -> Document:
    """Add the letter's file as the person would, and read it (a recorded model failure leaves it failed). An
    Outlook ``.msg`` becomes its ``.eml`` copy first, as on upload; any other file is added as it is."""
    path = entry.path(dataset_dir)
    data, name = as_email(path.read_bytes(), path.name)
    document = await add_file(ctx, data, name, source="upload", answer_held=True)
    job = claim_document_job(ctx.store, document.id)
    if job is None:
        return document
    try:
        return await ingest_document(ctx, document.id, job_id=job.id)
    except ReplayMiss:
        raise
    except LLMError:
        stored = ctx.store.get_document(document.id)
        if stored is None:
            raise
        return stored


async def _objection(ctx: AppContext, doc_id: str) -> DraftSeen:
    """Ask for an objection letter, signed by :data:`SIGNER`, and read back the PDF the person sends."""
    with ctx.store.tx():
        profile = ctx.store.get_profile()
        ctx.store.save_profile(profile.model_copy(update={"name": SIGNER, "address": SIGNER_ADDRESS}))
    ctx.reload_settings()
    try:
        draft = await compose(ctx, "objection", doc_id=doc_id, language="de")
    except DraftError as exc:
        return DraftSeen(refused=True, error=type(exc).__name__)
    data = pdf.render(draft, sent.letter_profile(ctx.store, draft))
    guidance = draft.send_guidance
    return DraftSeen(
        recipient_block=draft.recipient_block,
        must_arrive_by=guidance.must_arrive_by if guidance else None,
        send_by=guidance.send_by if guidance else None,
        pdf_lines=pdf_lines(data),
        signer=SIGNER,
        own_checks_failed=sorted(check.id for check in draft.checks if not check.ok),
    )


def _profile(entry: Entry) -> Profile:
    return Profile(
        language=PERSONA_LANGUAGE,
        region=entry.recipient_region or PERSONA_REGION,
        country="DE",
        name="",
        onboarded=True,
    )


async def observe_letter(
    entry: Entry, data_dir: Path, backend: CountingReplay, *, dataset_dir: Path, model: str
) -> LetterObservation:
    """Everything the person gets from one letter, in a fresh data folder ``data_dir`` (the app creates it)."""
    clock.set_today(entry.today)
    ctx = build_context(data_dir, backend_obj=backend)
    try:
        models = ModelSettings(extract=model, transcribe=model, draft=model)
        with ctx.store.tx():
            ctx.store.save_profile(_profile(entry))
            ctx.store.save_settings(AppSettings(simulated_today=entry.today, concurrency=1, models=models))
        ctx.reload_settings()
        document = await _read(ctx, entry, dataset_dir)
        await DailyTick(OfflineTickContext(ctx.store)).check()
        store = ctx.store
        document = store.get_document(document.id) or document  # as the ledger holds it after the tick
        ledger = Ledger(store, entry.today_date)
        items = store.list_items(doc_id=document.id)
        uids = {item_uid(item.id): item.id for item in items}
        events = [
            event.model_copy(update={"item_id": uids.get(event.uid)})
            for event in calendar_events(build_ics(store))
        ]
        agenda = []
        for day in probe_days(entry):
            listed = build_agenda(store, day)
            ids = {
                line.ref.id
                for line in [*listed.overdue, *listed.today, *listed.next_7_days]
                if line.ref.type == "item"
            }
            agenda.append(AgendaProbe(day=day.isoformat(), item_ids=sorted(ids)))
        ideas = [
            IdeaSeen(
                rule_id=idea.rule_id or idea.source,
                kind=idea.kind,
                due_date=idea.due_date,
                item_ids=sorted(ref.id for ref in idea.refs if ref.type == "item"),
                doc_ids=sorted(ref.id for ref in idea.refs if ref.type == "document"),
            )
            for idea in store.list_suggestions()
        ]
        observation = LetterObservation(
            entry_id=entry.id,
            status=document.status,
            hidden_text=bool(document.hidden_text),
            scam_reasons=reason_codes(ledger.scam_reasons(document), warnings=document.warnings),
            items=[_stored(ledger, item) for item in items],
            events=events,
            agenda=agenda,
            ideas=sorted(ideas, key=lambda idea: (idea.rule_id, idea.due_date or "", idea.item_ids)),
            reminder_windows={kind: ledger.reminder_window(kind) for kind in WINDOW_KINDS},
        )
        if remedy_letter(entry):
            observation.draft = await _objection(ctx, document.id)
        elif no_remedy_letter(entry):
            refusal = await _objection(ctx, document.id)
            observation.objection_on_none = "refused" if refusal.refused else "drafted"
        return observation
    finally:
        ctx.close()


@dataclass
class Observed:
    """The harness's run: an observation per letter it could run, an error per letter it couldn't."""

    observations: list[LetterObservation] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    replay: dict[str, Any] = field(default_factory=dict)


async def observe_all(
    entries: Sequence[Entry],
    *,
    dataset_dir: Path = DATASET_DIR,
    recorded_dir: Path = RECORDED_DIR,
    model: str = DEFAULT_MODEL,
) -> Observed:
    """Observe every entry, one after the other (the app's clock is pinned to each letter's day), and put the
    clock back as it was."""
    backend = CountingReplay(recorded_dir / safe_name(model))
    observed = Observed()
    previous = clock.today() if clock.simulated() and not os.environ.get("ORDNUNG_TODAY") else None
    try:
        with tempfile.TemporaryDirectory(prefix="ordnung-e2e-") as work:
            for entry in entries:
                backend.letter = entry.id
                try:
                    observation = await observe_letter(
                        entry, Path(work) / entry.id, backend, dataset_dir=dataset_dir, model=model
                    )
                except Exception as exc:  # every letter of the run, then the errors by id
                    observed.errors.append({"entry_id": entry.id, "error": type(exc).__name__})
                    continue
                if entry.id in backend.missed_for:
                    observed.errors.append({"entry_id": entry.id, "error": "ReplayMiss"})
                    continue
                observed.observations.append(observation)
    finally:
        clock.set_today(previous)
        clock.stamp_simulated_day(False)
    observed.replay = backend.counts()
    return observed


async def benchmark_dates(
    entries: Sequence[Entry],
    *,
    model: str = DEFAULT_MODEL,
    manifest_path: Path = MANIFEST_PATH,
    recorded_dir: Path = RECORDED_DIR,
) -> dict[str, dict[int, str | None]]:
    """The date the benchmark's Ordnung condition gives each required labelled item (by index) when replayed
    without the sender's Land, by entry id — the parity reference (nothing is written; no model is called)."""
    from scripts.eval_without_land import sender_land_unknown

    by_split: dict[str, list[str]] = {}
    for entry in entries:
        by_split.setdefault(entry.split, []).append(entry.id)
    dates: dict[str, dict[int, str | None]] = {}
    with tempfile.TemporaryDirectory(prefix="ordnung-e2e-bench-") as work, sender_land_unknown():
        for split, ids in by_split.items():
            config = RunConfig(
                split=split,
                models=[model],
                conditions=["ordnung"],
                ids=ids,
                resume=False,
                write_results=False,
                write_docs=False,
                manifest_path=manifest_path,
                recorded_dir=recorded_dir,
                results_dir=Path(work) / split,
            )
            outcome = await run_benchmark(config)
            (run,) = outcome.runs
            if run.results is None:
                problems = (
                    "; ".join(f"{p.entry_id}: {p.error}" for p in run.errors[:5]) or run.fatal or "no results"
                )
                raise RuntimeError(f"the benchmark replay of {split} failed: {problems}")
            for row in run.results["entries"]:
                items = row["conditions"]["ordnung"]["score"]["items"]
                dates[row["id"]] = {item["index"]: item["predicted"] for item in items if item["required"]}
    return dates
