"""Ask — the only true agent loop in Ordnung (SPEC §10, §21, ADR 0008).

One question runs ``claude -p`` with no built-in tools and only Ordnung's read-only MCP tools
(:mod:`ordnung.assistant.mcp_server`, spawned per question over stdio). Every tool result has two
channels (:mod:`ordnung.assistant.channels`): Ordnung's record — what code computed, the person
confirmed or the pipeline filed with verified evidence — and the letters' text, kept inside
``<untrusted_document>``. The answer streams to the UI as ``text`` deltas plus a visible tool trace
(``tool_use`` events carry a human label, ``tool_result`` events a short summary). The model's text
itself is never streamed: one ``text`` event without text says the answer is being written, and
nobody sees a word of it before code has checked it:

* every citation (``[doc:ID]`` …) must name a record that exists *and* appears in the record part
  of a tool result of this turn (an id that only a letter's text mentions is not enough); others are
  stripped;
* every date, time and amount must be in the record part of a record its sentence cites (a
  letter's unverified amount and the person's own values are shown in quotation marks as
  unconfirmed); other values are left out, and a sentence with nothing left to keep is removed
  (:mod:`ordnung.assistant.support`, the written policy);
* a short note says what was left out, quoted or cited, and which citations were removed or weekday
  names corrected. Only the check writes it: a line of the model's that starts like it is left out
  (and counted in the note), and the note travels in its own field, with its label in the answer's
  language. The trace's labels show the model's search words without their digits.

Removals are logged in the activity log. The final ``done`` event (:class:`AskEvent`) carries the
checked answer — which replaces the streamed deltas — the note, the validated citations with labels,
and the ids of the stored assistant message and thread. Question and answer (with the tool trace
and citations) are stored in ``chat_messages`` only when an answer arrives; the stored answer ends
with the note under its label (in the answer's language) as its last paragraph, and
:func:`stored_answer` splits it off again for the API.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator, Collection, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Protocol

from ordnung import clock
from ordnung.assistant.channels import parse_tool_result
from ordnung.assistant.citations import (
    REF_TYPES,
    Citation,
    CitationRef,
    is_well_formed,
    parse_citations,
    result_summary,
    strip_invalid,
    tool_label,
    tool_name,
)
from ordnung.assistant.mcp_server import PARTY_FIELDS, SERVER_NAME, TOOL_NAMES, server_config
from ordnung.assistant.support import (
    NOTE_PREFIX,
    NOTE_PREFIX_DE,
    CheckedAnswer,
    TurnEvidence,
    check_answer,
    split_note,
    style_for,
)
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.ids import new_id
from ordnung.ingest.extract import wrap_untrusted
from ordnung.llm.base import LLMRequest, StreamEvent
from ordnung.llm.prompts import render
from ordnung.llm.runtime import LLMService
from ordnung.models import AppSettings, ChatMessage
from ordnung.secretary.review import catalog_texts, correct_weekdays, language_name, stable_hash
from ordnung.secretary.triggers import IDEA_LAWS
from ordnung.tick import local_today

#: Ask keeps to the ledger (ADR 0011): its server is started ``--ledger-only`` and the CLI may call only
#: Ordnung's ledger tools, by name — never the ledger-free rules tools, which compute a new date from a
#: ``DateSpec`` the model passes (possibly read from an injected letter) and have no record to cite.
ALLOWED_TOOLS = [f"mcp__{SERVER_NAME}__{name}" for name in TOOL_NAMES]
MAX_BUDGET_USD = 0.5
TIMEOUT_S = 120.0
HISTORY_MESSAGES = 6
HISTORY_CHARS = 1500

NO_ANSWER = "I couldn't find an answer to that in your records."
NO_ANSWER_DE = "Dazu habe ich in Ihren Unterlagen keine Antwort gefunden."
UNSUPPORTED_ANSWER = (
    "I couldn't back up my answer with your records, so I left it out. You can open the letter, to-do or "
    "contract itself in Ordnung to see its dates and amounts."
)
UNSUPPORTED_ANSWER_DE = (
    "Ich konnte meine Antwort nicht mit Ihren Unterlagen belegen und habe sie deshalb weggelassen. Sie "
    "können den Brief, die Aufgabe oder den Vertrag in Ordnung öffnen und dort Daten und Beträge ansehen."
)
CHECK_FAILED = "Ordnung couldn't check this answer against your records, so it isn't shown. Please ask again."
#: What an answer that broke off with an unexpected error says (the error itself goes to the log).
UNEXPECTED_STOP = (
    "Something went wrong while answering, so there is no answer. Please ask again; if it keeps happening, "
    "run “ordnung doctor”."
)
#: The message for a question the demo has no recorded answer for (sent with ``error_code`` ``demo_miss``) once
#: no suggested question is offered either (the person changed the demo: :data:`DEMO_CHANGED`).
DEMO_NOT_RECORDED = (
    "The demo replays answers recorded for its sample letters, and there is none for this question."
)
#: The message for a question the demo has no recorded answer for, while the suggested questions are offered.
DEMO_MISS = f"{DEMO_NOT_RECORDED} Try one of the suggested questions."
#: The message for a suggested question the demo recorded, asked after the person changed the letters or to-dos
#: (sent with ``error_code`` ``demo_changed``): its answers were recorded on Sam's letters as the demo started,
#: so every suggested question misses until the demo starts over — which ``ordnung demo --reset`` does only
#: once the running demo is stopped.
DEMO_CHANGED = (
    "The demo's answers were recorded for Sam's letters as the demo started, and you have changed his "
    "to-dos or letters since, so they no longer fit. To ask the suggested questions again, start the demo "
    "over. Stop the demo (Ctrl+C where it runs), then run “ordnung demo --reset”."
)
EMPTY_QUESTION = "Please type a question."

_EXTRA_BLANK_LINES = re.compile(r"\n{3,}")
logger = logging.getLogger(__name__)


class AskContext(Protocol):
    """What Ask needs from the app context (:class:`ordnung.app_context.AppContext` fits)."""

    @property
    def paths(self) -> Paths: ...

    @property
    def store(self) -> Store: ...

    @property
    def llm(self) -> LLMService: ...

    @property
    def settings(self) -> AppSettings: ...


#: Why an answer could not be given, when the UI shows more than the message: ``demo_miss`` — the demo
#: has no recorded answer for the question (asking again cannot help, a suggested question can);
#: ``demo_changed`` — a suggested question the demo recorded, but the person changed the letters or to-dos
#: since the demo started (only starting the demo over helps).
AskErrorCode = Literal["demo_miss", "demo_changed"]


class AskEvent(StreamEvent):
    """A stream event; the final ``done`` event also carries the answer check's note (without its
    label), the label in the answer's language, the answer's ids and citations; an ``error`` event may
    carry an :data:`AskErrorCode`."""

    error_code: AskErrorCode | None = None
    note: str | None = None
    note_label: str | None = None
    citations: list[CitationRef] | None = None
    message_id: str | None = None
    thread_id: str | None = None


# --------------------------------------------------------------------------------------------------
# the request
# --------------------------------------------------------------------------------------------------


#: Fields that change with time, not with what Ask can read — left out so a rebuilt demo hashes the same.
_VOLATILE_FIELDS = frozenset(
    {"created_at", "updated_at", "processed_at", "ai_processed_at", "completed_at", "deleted_at"}
)


def _rows(records: Iterable[Any]) -> list[dict[str, Any]]:
    rows = [record.model_dump(mode="json", exclude=_VOLATILE_FIELDS) for record in records]
    return sorted(rows, key=lambda row: str(row.get("id")))


def ledger_fingerprint(store: Store) -> str:
    """Hash of everything Ask's read-only tools can see (every field of letters, to-dos and contracts,
    the letters' page texts, the parties' shared fields, no timestamps), so a recorded answer replays
    only against the ledger it was recorded from — a changed warning, IBAN or page text makes a new
    recording necessary.
    """
    profile = store.get_profile()
    documents = store.list_documents()
    return stable_hash(
        {
            "profile": [profile.name, profile.language, profile.region, profile.country],
            "documents": _rows(documents),
            "texts": {doc.id: stable_hash(store.get_document_text(doc.id)) for doc in documents},
            "items": _rows(store.list_items()),
            "contracts": _rows(store.list_contracts()),
            "parties": sorted(
                (
                    p.model_dump(mode="json", include={*PARTY_FIELDS, "identifiers"})
                    for p in store.list_parties()
                ),
                key=lambda row: str(row["id"]),
            ),
        }
    )


def ask_cache_key(
    store: Store, question: str, history: Sequence[ChatMessage], today: date, *, masked_numbers: bool = False
) -> str:
    """Canonical stable inputs of an Ask call: the question, today, the ledger and the conversation
    (and, for a phone's question, that the person's own numbers were masked: never the computer's answer).

    No wall-clock times and nothing that depends on the order of ingestion, so the demo's recorded
    questions replay against a rebuilt demo database.
    """
    basis: dict[str, Any] = {
        "question": " ".join(question.split()),
        "today": today.isoformat(),
        "ledger": ledger_fingerprint(store),
        "history": stable_hash([[m.role, m.content] for m in history]) if history else None,
    }
    if masked_numbers:
        basis["masked_numbers"] = True
    return "ask:" + json.dumps(basis, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def build_request(
    ctx: AskContext,
    question: str,
    history: Sequence[ChatMessage],
    today: date,
    *,
    key_history: Sequence[ChatMessage] | None = None,
    masked_numbers: bool = False,
) -> LLMRequest:
    """The ``ask`` request: read-only MCP tools only, a budget cap and a timeout. The prompt carries
    ``history``; the cache key ``key_history`` (default: the same). ``masked_numbers``: a question asked
    on a paired phone (the tools mask the person's own numbers)."""
    profile = ctx.store.get_profile()
    system_version, system = render(
        "ask_system",
        today=f"{today.strftime('%A')}, {today.isoformat()}",
        language_name=language_name(profile.language),
    )
    version, prompt = render("ask", history=_history_block(history), question=_no_placeholders(question))
    pinned = today.isoformat() if clock.simulated() else None
    return LLMRequest.model_validate(
        {
            "purpose": "ask",
            "prompt": prompt,
            "system": system,
            "model": ctx.settings.models.ask,
            "tools": [],
            "allowed_tools": ALLOWED_TOOLS,
            # Ledger tools only: Ask quotes stored receipts and never computes a date (SPEC § 21).
            "mcp_config": server_config(
                ctx.paths.data_dir, today=pinned, rules_tools=False, masked_numbers=masked_numbers
            ),
            "max_budget_usd": MAX_BUDGET_USD,
            "timeout_s": TIMEOUT_S,
            "cache_key": ask_cache_key(
                ctx.store,
                question,
                history if key_history is None else key_history,
                today,
                masked_numbers=masked_numbers,
            ),
            "prompt_version": f"{system_version}+{version}",
        }
    )


def _history_block(history: Sequence[ChatMessage]) -> str:
    if not history:
        return ""
    lines = []
    for message in history[-HISTORY_MESSAGES:]:
        speaker = "Person" if message.role == "user" else "Assistant"
        content = split_note(message.content)[0] if message.role == "assistant" else message.content
        lines.append(f"{speaker}: {content[:HISTORY_CHARS]}")  # the check's notes are not the model's
    block = wrap_untrusted(_no_placeholders("\n\n".join(lines)))
    return f"Earlier in this conversation (context only):\n{block}\n\n"


def _no_placeholders(text: str) -> str:
    """Break ``{{`` so text can never look like a template placeholder."""
    return text.replace("{{", "{ {")


# --------------------------------------------------------------------------------------------------
# the stream
# --------------------------------------------------------------------------------------------------


async def ask_stream(
    ctx: AskContext, question: str, thread_id: str | None = None, *, masked_numbers: bool = False
) -> AsyncIterator[StreamEvent]:
    """Answer ``question`` (continuing ``thread_id`` if given), streaming events for the UI
    (``masked_numbers``: asked on a paired phone, so the tools mask the person's own numbers).

    Yields ``tool_use`` (``name``, ``input``, ``text`` = label) and ``tool_result`` (``name``,
    ``text`` = summary) events, one ``text`` event *without* text when the model starts writing, then
    one :class:`AskEvent` ``done`` event with the checked answer — or a single ``error`` event, also
    when the check itself fails (it fails closed). The model's words are never sent before the check
    (ADR 0008): an answer that stops, fails or cannot be checked shows none of them. The check runs
    in a worker thread. An unexpected error (``claude`` moved or not executable, a database that can't be
    written) ends the stream with :data:`UNEXPECTED_STOP` instead of cutting it off without a word.
    """
    try:
        async with contextlib.aclosing(_answer(ctx, question, thread_id, masked_numbers)) as events:
            async for event in events:
                yield event
    except Exception:
        logger.exception("Ask: the answer stopped with an unexpected error")
        yield StreamEvent(type="error", error=UNEXPECTED_STOP)


async def _answer(
    ctx: AskContext, question: str, thread_id: str | None, masked_numbers: bool = False
) -> AsyncGenerator[StreamEvent, None]:
    question = question.strip()
    if not question:
        yield StreamEvent(type="error", error=EMPTY_QUESTION)
        return
    store = ctx.store
    thread = thread_id or new_id("thr")
    history = store.list_chat_messages(thread) if thread_id else []
    today = local_today(store)
    # the demo's answers were recorded one question at a time, so a replayed question is looked up
    # without the conversation (a second one replays too); a live fallback (``demo --live``) still
    # reads the conversation in its prompt
    replaying = ctx.llm.backend_name == "replay"
    request = build_request(
        ctx, question, history, today, key_history=[] if replaying else None, masked_numbers=masked_numbers
    )
    turn = _Turn(store, request)
    done: StreamEvent | None = None
    failure: StreamEvent | None = None
    async for event in ctx.llm.stream(request):  # drained to the end so the call is accounted for
        if event.type == "tool_use":
            yield turn.tool_use(event)
        elif event.type == "tool_result":
            yield turn.tool_result(event)
        elif event.type == "text":
            if not turn.deltas:
                yield StreamEvent(type="text")  # "writing …": the words wait for the check
            turn.deltas.append(event.text or "")
        elif event.type == "done":
            done = event
        else:
            failure = event
    if failure is not None or done is None:
        yield _failure(ctx, failure)
        return
    answer = (done.response.text if done.response is not None else "") or "".join(turn.deltas)
    try:  # the check reads whole tool results: off the event loop, so a long answer never blocks the API
        checked = await asyncio.to_thread(
            check_turn, store, answer, turn.results, question=question, history=history, today=today
        )
    except Exception:  # fail closed: an answer the check could not read is never shown as checked
        logger.exception("Ask: the answer check failed")
        yield StreamEvent(type="error", error=CHECK_FAILED)
        return
    yield _finish(store, turn, checked, question=question, thread_id=thread)


def _failure(ctx: AskContext, event: StreamEvent | None) -> StreamEvent:
    """An error event — with the code ``demo_miss`` and :data:`DEMO_MISS` when the replayed demo has no
    recorded answer (asking again can't help; the web app shows a note, not a failure)."""
    message = (event.error if event is not None else None) or "The answer stopped unexpectedly."
    if ctx.llm.backend_name == "replay" and message.startswith("no recorded response"):
        return demo_miss_event()
    return StreamEvent(type="error", error=message)


def demo_miss_event(*, offered: bool = True) -> AskEvent:
    """The event shown instead of an answer the demo has no recording for (nothing was stored, so it
    names no thread); it points to the suggested questions only while they are ``offered``."""
    message = DEMO_MISS if offered else DEMO_NOT_RECORDED
    return AskEvent(type="error", error=message, text=message, error_code="demo_miss")


def demo_changed_event() -> AskEvent:
    """The event shown instead of a recorded answer that no longer fits: a suggested question asked after
    the person changed the demo's letters or to-dos (:data:`DEMO_CHANGED`; nothing was stored)."""
    return AskEvent(type="error", error=DEMO_CHANGED, text=DEMO_CHANGED, error_code="demo_changed")


@dataclass
class _Turn:
    """What one question's stream produced: the tool trace, tool results and text deltas."""

    store: Store
    request: LLMRequest
    calls: list[dict[str, Any]] = field(default_factory=list)
    results: list[str] = field(default_factory=list)
    deltas: list[str] = field(default_factory=list)
    _waiting: deque[int] = field(default_factory=deque)  # calls without an id, oldest first
    _by_id: dict[str, int] = field(default_factory=dict)

    def tool_use(self, event: StreamEvent) -> StreamEvent:
        """Label a tool call for the trace and note documents whose text is sent to the model."""
        name = tool_name(event.name)
        args = dict(event.input or {})
        label = tool_label(name, args, title_of=lambda ref_id: record_label(self.store, ref_id))
        if event.tool_use_id:
            self._by_id[event.tool_use_id] = len(self.calls)
        else:
            self._waiting.append(len(self.calls))
        self.calls.append({"name": name, "input": args, "label": label})
        doc_id = args.get("doc_id")
        if name == "get_document" and isinstance(doc_id, str):
            self._note_sent(doc_id)
        return StreamEvent(type="tool_use", name=name, input=args, text=label)

    def _note_sent(self, doc_id: str) -> None:
        """Add a document whose text the model reads to the request's ``doc_ids``.

        LLMService.stream logs the call after the stream ends, so "What was sent" then lists it.
        Private documents are never sent (the tool withholds them) and stay off the list.
        """
        doc = self.store.get_document(doc_id)
        if doc is not None and not doc.ai_private and doc_id not in self.request.doc_ids:
            self.request.doc_ids.append(doc_id)

    def _letters_in(self, text: str) -> Iterator[str]:
        """The letters a ledger tool result sends text of: every record its letter-text part is keyed by —
        a letter itself (a search hit's title and snippet), the letter a to-do was read from (its title or
        quote), or every letter a contract's terms were read from (its source and evidence) and the
        cancellation letter ``list_contracts`` names beside it (the end date that letter claims). A party's
        name stands in many letters and names none of them."""
        result = parse_tool_result(text)
        cancellations = _cancellation_letters(result.record)
        for ref_id in result.letters:
            prefix = ref_id.split("_", 1)[0]
            if prefix == "doc":
                yield ref_id
            elif prefix == "itm":
                item = self.store.get_item(ref_id)
                if item is not None and item.doc_id:
                    yield item.doc_id
            elif prefix == "ctr":
                contract = self.store.get_contract(ref_id)
                if contract is not None:
                    letters = [contract.source_doc_id, *(ev.doc_id for ev in contract.evidence)]
                    yield from filter(None, letters)
                if ref_id in cancellations:
                    yield cancellations[ref_id]

    def tool_result(self, event: StreamEvent) -> StreamEvent:
        """Keep the result for validation, note the letters it sent text of and summarise it for the trace.

        A result belongs to the call with its ``tool_use_id`` (parallel calls may answer out of
        order); a result without an id (fakes, older recordings) to the oldest call without an id still
        waiting — never to a call with an id, and a result no call claims stays unclaimed (review round 4
        of phase 2: an extra result recorded first became the call's). The replay's staleness check pairs
        the same way (:func:`~ordnung.assistant.mcp_server.pair_results`).
        Only a result of one of Ordnung's ledger tools (:data:`~ordnung.assistant.mcp_server.TOOL_NAMES`)
        is kept for the check (ADR 0011): the answer is checked against the records alone, so a result
        of any other tool — a rules tool's date computed from what the model passed it, or a result no
        call claims — never supports a value and never makes an id citable, whatever its text says.
        """
        text = event.text or ""
        index = self._call_for(event.tool_use_id)
        name = self.calls[index]["name"] if index is not None else "tool"
        if name in TOOL_NAMES:
            self.results.append(text)
            for doc_id in self._letters_in(text):
                self._note_sent(doc_id)
        summary = result_summary(name, text)
        if index is not None:
            self.calls[index]["result"] = summary
        return StreamEvent(type="tool_result", name=name, text=summary)

    def _call_for(self, tool_use_id: str | None) -> int | None:
        if tool_use_id:
            return self._by_id.pop(tool_use_id, None)
        return self._waiting.popleft() if self._waiting else None


def _cancellation_letters(record: Any) -> dict[str, str]:
    """Contract id → the cancellation letter a ``list_contracts`` row names as pending the person's
    confirmation (its ``cancellation_letter``)."""
    rows = record.get("contracts") if isinstance(record, dict) else None
    found: dict[str, str] = {}
    for row in rows if isinstance(rows, list) else []:
        letter = row.get("cancellation_letter") if isinstance(row, dict) else None
        doc_id = letter.get("doc_id") if isinstance(letter, dict) else None
        if isinstance(doc_id, str) and isinstance(row.get("id"), str):
            found[row["id"]] = doc_id
    return found


# --------------------------------------------------------------------------------------------------
# checking and storing the answer
# --------------------------------------------------------------------------------------------------


def _finish(store: Store, turn: _Turn, checked: AnswerCheck, *, question: str, thread_id: str) -> AskEvent:
    """Store question and checked answer, log what the check changed, and make the ``done`` event."""
    text = checked.text
    citations = citation_refs(store, parse_citations(checked.body))
    with store.tx():
        store.add_chat_message(thread_id, "user", question)
        message = store.add_chat_message(
            thread_id,
            "assistant",
            text,
            citations=[{"type": ref.type, "id": ref.id} for ref in citations],
            tool_calls=turn.calls,
        )
    _log_checks(store, message.id, thread_id, checked)
    return AskEvent(
        type="done",
        text=checked.body,
        note=checked.note,
        note_label=checked.claims.style.note_prefix,
        citations=citations,
        message_id=message.id,
        thread_id=thread_id,
    )


@dataclass(frozen=True)
class AnswerCheck:
    """What the checks made of one answer: the checked ``body`` (or a fallback), the ``note`` under it
    (without its label, :data:`~ordnung.assistant.support.NOTE_LABELS`), the verdict on every sentence with a
    date, amount or § (``claims``) and the citations stripped. ``text`` is what is stored: the body,
    then the note under its label as its own last paragraph — the label alone when the check changed
    nothing, so a stored answer always says it was checked (:func:`checked_by_claims`)."""

    body: str
    note: str | None
    claims: CheckedAnswer
    removed_ids: list[str]

    @property
    def text(self) -> str:
        label = self.claims.style.note_prefix
        return f"{self.body}\n\n{label} {self.note}" if self.note else f"{self.body}\n\n{label}"


def check_turn(
    store: Store,
    answer: str,
    tool_results: Sequence[str],
    *,
    question: str,
    history: Sequence[ChatMessage] = (),
    today: date,
) -> AnswerCheck:
    """Check ``answer`` against this turn's tool results (pure apart from reading ``store``).

    Citations first (:func:`valid_citation_ids`), then every sentence with a date, time or amount
    (:func:`ordnung.assistant.support.check_answer`); weekday names are corrected and the note is
    made (it also says when citations were removed or weekday names corrected). An answer the check emptied — of sentences it left out or of lines that looked like its note
    — becomes :data:`UNSUPPORTED_ANSWER` (in German for a German answer), and its note still says what
    was left out and why; only an answer that was empty already becomes :data:`NO_ANSWER` (in German
    for a German question).
    """
    person = [question, *(message.content for message in history if message.role == "user")]
    evidence = TurnEvidence.from_results(tool_results, today=today, person=person, catalog=known_laws())
    cited = parse_citations(answer)
    valid = valid_citation_ids(store, cited, evidence.seen_ids)
    claims = check_answer(answer, evidence, citable=valid)
    removed = sorted({citation.id for citation in cited} - valid)
    stripped = _EXTRA_BLANK_LINES.sub("\n\n", strip_invalid(claims.text, valid)).strip()
    body = correct_weekdays(stripped, today)
    note = claims.note(stripped=len(removed), weekdays=body != stripped)
    german = (claims.style if answer.strip() else style_for(question)).german
    if not body and (claims.removed or claims.forged_notes):
        body = UNSUPPORTED_ANSWER_DE if german else UNSUPPORTED_ANSWER
    elif not body:
        body, note = (NO_ANSWER_DE if german else NO_ANSWER), None
    label = claims.style.note_prefix
    return AnswerCheck(body, note.removeprefix(label).strip() if note else None, claims, removed)


def known_laws() -> list[str]:
    """The § citations any Ask sentence may state: the rules catalog and the laws Ordnung's own Ideas
    state (:data:`~ordnung.secretary.triggers.IDEA_LAWS`)."""
    return [*catalog_texts(), *IDEA_LAWS]


def stored_answer(message: ChatMessage) -> tuple[str, str | None]:
    """A stored message's text and, for an answer, the check's note split off it (without prefix;
    ``None`` when the check changed nothing, or for an answer stored before the check wrote a label)."""
    if message.role != "assistant":
        return message.content, None
    body, note = split_note(message.content)
    return body, note or None


def stored_note_label(message: ChatMessage) -> str | None:
    """The label a stored answer was checked under (in the answer's language), if it has one."""
    if message.role != "assistant" or split_note(message.content)[1] is None:
        return None
    return NOTE_PREFIX_DE if message.content.rpartition("\n\n")[2].startswith(NOTE_PREFIX_DE) else NOTE_PREFIX


def checked_by_claims(message: ChatMessage) -> bool:
    """Whether a stored answer went through the claim-level check (ADR 0008): it ends with the check's
    label, with the note or alone (:attr:`AnswerCheck.text`). An answer stored before (the earlier, weaker
    check) has none, and the app never shows it as "Checked against your records"."""
    return message.role == "assistant" and split_note(message.content)[1] is not None


def valid_citation_ids(store: Store, cited: Iterable[Citation], seen: Collection[str]) -> set[str]:
    """Ids that may stay cited: well-formed, in the record part of a tool result of this turn
    (``seen`` — an id that only a letter's text mentions does not count), and existing."""
    return {
        citation.id
        for citation in cited
        if is_well_formed(citation.type, citation.id)
        and citation.id in seen
        and record_label(store, citation.id) is not None
    }


def citation_refs(store: Store, cited: Iterable[Citation]) -> list[CitationRef]:
    """The citations of a (validated) answer, once each in order of appearance, with labels."""
    refs: dict[str, CitationRef] = {}
    for citation in cited:
        label = record_label(store, citation.id)
        if citation.id not in refs and label is not None and citation.type in REF_TYPES:
            refs[citation.id] = CitationRef(type=REF_TYPES[citation.type], id=citation.id, label=label)
    return list(refs.values())


def record_label(store: Store, ref_id: str) -> str | None:
    """Display name of a cited record (``None`` if it does not exist or is in the trash)."""
    prefix = ref_id.split("_", 1)[0]
    if prefix == "doc":
        doc = store.get_document(ref_id)
        return None if doc is None or doc.deleted_at is not None else doc.title or doc.filename
    if prefix == "itm":
        item = store.get_item(ref_id)
        return item.title if item else None
    if prefix == "ctr":
        contract = store.get_contract(ref_id)
        return contract.name if contract else None
    if prefix == "pty":
        party = store.get_party(ref_id)
        return party.name if party else None
    return None


def _log_checks(store: Store, message_id: str, thread_id: str, checked: AnswerCheck) -> None:
    """What the checks did to an answer, as one activity entry whatever they did, so answers never push the
    letters read and the exports out of the log. It reads without the chat next to it: which answer ("in
    Ask") and each thing done (``data["done"]``, joined in the message), with the ids and values behind."""
    done: list[str] = []
    data: dict[str, Any] = {"thread_id": thread_id}
    if checked.removed_ids:
        count = len(checked.removed_ids)
        sources = "1 source" if count == 1 else f"{count} sources"
        done.append(f"took out {sources} it hadn't looked up")
        data["ids"] = checked.removed_ids
    removed = checked.claims.removed + checked.claims.redacted
    if removed:
        done.append("took out sentences or values with dates, amounts or laws not in the records they cite")
        data["unsupported"] = list(dict.fromkeys(value for check in removed for value in check.left_out))
    quoted = checked.claims.quoted
    if quoted:
        done.append("showed values only a letter or the person states as quotes")
        data["quoted"] = list(
            dict.fromkeys(
                value for check in quoted for value in check.unsupported if value not in check.left_out
            )
        )
    if done:
        store.log_activity(
            "ask.checked",
            f"Checked an answer in Ask: {'; '.join(done)}",
            ref_type="chat",
            ref_id=message_id,
            data=data | {"done": done},
        )
