"""Ask — the only true agent loop in Ordnung (SPEC §10, §21, ADR 0008).

One question runs ``claude -p`` with no built-in tools and only Ordnung's read-only MCP tools
(:mod:`ordnung.assistant.mcp_server`, spawned per question over stdio). Every tool result has two
channels (:mod:`ordnung.assistant.channels`): Ordnung's record — what code computed, the person
confirmed or the pipeline filed with verified evidence — and the letters' text, kept inside
``<untrusted_document>``. The answer streams to the UI as ``text`` deltas plus a visible tool trace
(``tool_use`` events carry a human label, ``tool_result`` events a short summary). When the model is
done, code checks the answer before anyone sees it as final:

* every citation (``[doc:ID]`` …) must name a record that exists *and* appears in the record part
  of a tool result of this turn (an id that only a letter's text mentions is not enough); others are
  stripped;
* every sentence that states a date or amount must cite a record whose record part holds it, or be
  framed as quoting a letter whose text holds it (then the value is shown in quotation marks);
  other such sentences are removed (:mod:`ordnung.assistant.support`, the written policy);
* a short note under the answer says what was left out or quoted.

Removals are logged in the activity log. The final ``done`` event (:class:`AskEvent`) carries the
cleaned text — which replaces the streamed deltas — the validated citations with labels, and the
ids of the stored assistant message and thread. Question and answer (with the tool trace and
citations) are stored in ``chat_messages`` only when an answer arrives.
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import AsyncIterator, Collection, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from ordnung import clock
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
from ordnung.assistant.mcp_server import PARTY_FIELDS, SERVER_NAME, server_config
from ordnung.assistant.support import CheckedAnswer, TurnEvidence, check_answer
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.ids import new_id
from ordnung.ingest.extract import wrap_untrusted
from ordnung.llm.base import LLMRequest, StreamEvent
from ordnung.llm.prompts import render
from ordnung.llm.runtime import LLMService
from ordnung.models import AppSettings, ChatMessage
from ordnung.secretary.review import catalog_texts, correct_weekdays, language_name, stable_hash
from ordnung.tick import local_today

ALLOWED_TOOLS = [f"mcp__{SERVER_NAME}__*"]
MAX_BUDGET_USD = 0.5
TIMEOUT_S = 120.0
HISTORY_MESSAGES = 6
HISTORY_CHARS = 1500

NO_ANSWER = "I couldn't find an answer to that in your records."
UNSUPPORTED_ANSWER = (
    "I couldn't back up my answer with your records, so I left it out. Try asking about one letter, "
    "contract or date."
)
DEMO_MISS = (
    "The demo uses recorded answers, and there is none for this question. Try one of the suggested questions."
)
EMPTY_QUESTION = "Please type a question."

_EXTRA_BLANK_LINES = re.compile(r"\n{3,}")


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


class AskEvent(StreamEvent):
    """A stream event; the final ``done`` event also carries the answer's ids and citations."""

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


def ask_cache_key(store: Store, question: str, history: Sequence[ChatMessage], today: date) -> str:
    """Canonical stable inputs of an Ask call: the question, today, the ledger and the conversation.

    No wall-clock times and nothing that depends on the order of ingestion, so the demo's recorded
    questions replay against a rebuilt demo database.
    """
    basis = {
        "question": " ".join(question.split()),
        "today": today.isoformat(),
        "ledger": ledger_fingerprint(store),
        "history": stable_hash([[m.role, m.content] for m in history]) if history else None,
    }
    return "ask:" + json.dumps(basis, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def build_request(ctx: AskContext, question: str, history: Sequence[ChatMessage], today: date) -> LLMRequest:
    """The ``ask`` request: read-only MCP tools only, a budget cap and a timeout."""
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
            "mcp_config": server_config(ctx.paths.data_dir, today=pinned),
            "max_budget_usd": MAX_BUDGET_USD,
            "timeout_s": TIMEOUT_S,
            "cache_key": ask_cache_key(ctx.store, question, history, today),
            "prompt_version": f"{system_version}+{version}",
        }
    )


def _history_block(history: Sequence[ChatMessage]) -> str:
    if not history:
        return ""
    lines = []
    for message in history[-HISTORY_MESSAGES:]:
        speaker = "Person" if message.role == "user" else "Assistant"
        lines.append(f"{speaker}: {message.content[:HISTORY_CHARS]}")
    block = wrap_untrusted(_no_placeholders("\n\n".join(lines)))
    return f"Earlier in this conversation (context only):\n{block}\n\n"


def _no_placeholders(text: str) -> str:
    """Break ``{{`` so text can never look like a template placeholder."""
    return text.replace("{{", "{ {")


# --------------------------------------------------------------------------------------------------
# the stream
# --------------------------------------------------------------------------------------------------


async def ask_stream(
    ctx: AskContext, question: str, thread_id: str | None = None
) -> AsyncIterator[StreamEvent]:
    """Answer ``question`` (continuing ``thread_id`` if given), streaming events for the UI.

    Yields ``text`` deltas, ``tool_use`` (``name``, ``input``, ``text`` = label) and ``tool_result``
    (``name``, ``text`` = summary) events, then one :class:`AskEvent` ``done`` event with the checked
    answer — or a single ``error`` event.
    """
    question = question.strip()
    if not question:
        yield StreamEvent(type="error", error=EMPTY_QUESTION)
        return
    store = ctx.store
    thread = thread_id or new_id("thr")
    history = store.list_chat_messages(thread) if thread_id else []
    today = local_today(store)
    request = build_request(ctx, question, history, today)
    turn = _Turn(store, request)
    done: StreamEvent | None = None
    failure: StreamEvent | None = None
    async for event in ctx.llm.stream(request):  # drained to the end so the call is accounted for
        if event.type == "tool_use":
            yield turn.tool_use(event)
        elif event.type == "tool_result":
            yield turn.tool_result(event)
        elif event.type == "text":
            turn.deltas.append(event.text or "")
            yield event
        elif event.type == "done":
            done = event
        else:
            failure = event
    if failure is not None or done is None:
        yield _failure(ctx, failure, thread)
        return
    answer = (done.response.text if done.response is not None else "") or "".join(turn.deltas)
    yield _finish(
        store, turn, question=question, answer=answer, thread_id=thread, history=history, today=today
    )


def _failure(ctx: AskContext, event: StreamEvent | None, thread_id: str) -> StreamEvent:
    """An error event — or, in the demo, a friendly note when no recorded answer exists."""
    message = (event.error if event is not None else None) or "The answer stopped unexpectedly."
    if ctx.llm.backend_name == "replay" and message.startswith("no recorded response"):
        return AskEvent(type="done", text=DEMO_MISS, citations=[], thread_id=thread_id)
    return StreamEvent(type="error", error=message)


@dataclass
class _Turn:
    """What one question's stream produced: the tool trace, tool results and text deltas."""

    store: Store
    request: LLMRequest
    calls: list[dict[str, Any]] = field(default_factory=list)
    results: list[str] = field(default_factory=list)
    deltas: list[str] = field(default_factory=list)
    _pending: deque[int] = field(default_factory=deque)

    def tool_use(self, event: StreamEvent) -> StreamEvent:
        """Label a tool call for the trace and note documents whose text is sent to the model."""
        name = tool_name(event.name)
        args = dict(event.input or {})
        label = tool_label(name, args, title_of=lambda ref_id: record_label(self.store, ref_id))
        self._pending.append(len(self.calls))
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

    def tool_result(self, event: StreamEvent) -> StreamEvent:
        """Keep the result for validation and summarise it for the trace (results arrive in call order)."""
        text = event.text or ""
        self.results.append(text)
        index = self._pending.popleft() if self._pending else None
        name = self.calls[index]["name"] if index is not None else "tool"
        summary = result_summary(name, text)
        if index is not None:
            self.calls[index]["result"] = summary
        return StreamEvent(type="tool_result", name=name, text=summary)


# --------------------------------------------------------------------------------------------------
# checking and storing the answer
# --------------------------------------------------------------------------------------------------


def _finish(
    store: Store,
    turn: _Turn,
    *,
    question: str,
    answer: str,
    thread_id: str,
    history: Sequence[ChatMessage],
    today: date,
) -> AskEvent:
    """Check the answer (citations, then claims), store question and answer, log what was changed."""
    checked = check_turn(store, answer, turn.results, question=question, history=history, today=today)
    text = checked.text
    citations = citation_refs(store, parse_citations(text))
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
    return AskEvent(type="done", text=text, citations=citations, message_id=message.id, thread_id=thread_id)


@dataclass(frozen=True)
class AnswerCheck:
    """What the checks made of one answer: the final ``text`` (with its note, or a fallback), the
    verdict on every sentence with a date, amount or § (``claims``) and the citations stripped."""

    text: str
    claims: CheckedAnswer
    removed_ids: list[str]


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

    Citations first (:func:`valid_citation_ids`), then every sentence with a date or amount
    (:func:`ordnung.assistant.support.check_answer`); weekday names are corrected and the note is
    appended. An answer left empty becomes :data:`UNSUPPORTED_ANSWER` (or :data:`NO_ANSWER`).
    """
    person = [question, *(message.content for message in history if message.role == "user")]
    evidence = TurnEvidence.from_results(tool_results, today=today, person=person, catalog=catalog_texts())
    cited = parse_citations(answer)
    valid = valid_citation_ids(store, cited, evidence.seen_ids)
    claims = check_answer(answer, evidence, citable=valid)
    body = correct_weekdays(_EXTRA_BLANK_LINES.sub("\n\n", strip_invalid(claims.text, valid)).strip(), today)
    if not body:
        text = UNSUPPORTED_ANSWER if claims.removed else NO_ANSWER
    else:
        note = claims.note()
        text = f"{body}\n\n{note}" if note else body
    return AnswerCheck(text, claims, sorted({citation.id for citation in cited} - valid))


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
    if checked.removed_ids:
        store.log_activity(
            "ask.citations_removed",
            f"Removed {len(checked.removed_ids)} citation(s) from an answer: not found in what Ask looked up",
            ref_type="chat",
            ref_id=message_id,
            data={"thread_id": thread_id, "ids": checked.removed_ids},
        )
    removed = checked.claims.removed
    if removed:
        store.log_activity(
            "ask.sentences_removed",
            f"Removed {len(removed)} sentence(s) whose dates, amounts or laws are not in the records they cite",
            ref_type="chat",
            ref_id=message_id,
            data={
                "thread_id": thread_id,
                "unsupported": list(dict.fromkeys(value for check in removed for value in check.unsupported)),
            },
        )
    quoted = checked.claims.quoted
    if quoted:
        store.log_activity(
            "ask.letter_quotes",
            f"Showed {len(quoted)} sentence(s) with dates or amounts only a letter states, as quotes",
            ref_type="chat",
            ref_id=message_id,
            data={
                "thread_id": thread_id,
                "quoted": list(dict.fromkeys(value for check in quoted for value in check.unsupported)),
            },
        )
